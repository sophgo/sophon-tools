"""Structural tests for the SAIL backend, run against a fake sail module.

These cannot prove the model produces correct text -- that needs the board. They
do prove the port's bookkeeping is right, which is where this class of code
actually breaks: mask shape/position, KV offsets, block counts, session
isolation.
"""

import asyncio
from pathlib import Path

import numpy as np
import pytest

from . import fake_sail


class FakeTokenizer:
    def __init__(self):
        self.vocab = {"<|im_end|>": 2, "<|end|>": 3, "<|image_pad|>": 4, "<|vision_start|>": 5}

    def convert_tokens_to_ids(self, t):
        return self.vocab.get(t, 0)

    def decode(self, ids, skip_special_tokens=True):
        return " ".join(f"t{i}" for i in ids)

    def __call__(self, text, return_tensors=None):
        return {"input_ids": [11, 12, 13]}


class FakeProcessor:
    def __init__(self, *a, **k):
        self.tokenizer = FakeTokenizer()


def make_config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text('{"hidden_size": 1024}')
    return d


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    """A SailBackend wired to the fake engine."""
    engine = fake_sail.install(monkeypatch)

    import sys, types
    tr = types.ModuleType("transformers")
    tr.AutoProcessor = types.SimpleNamespace(from_pretrained=lambda *a, **k: FakeProcessor())
    monkeypatch.setitem(sys.modules, "transformers", tr)

    from app.engine.sail_backend import SailBackend

    be = SailBackend("m", "/fake/model.bmodel", str(make_config_dir(tmp_path)), 0)
    return be, engine


def test_shapes_and_layers_come_from_the_bmodel_not_config(backend):
    """config.json in the demo is wrong (hidden 1024 vs 2048); the bmodel wins."""
    be, _ = backend
    assert be.num_layers == 8
    assert be.hidden_size == 64          # from the engine, not config's 1024
    assert be.context_length == 2048


def test_chunked_prefill_is_declared_unsupported(backend):
    be, _ = backend
    assert be.supports_chunked_prefill is False


def test_session_kv_is_per_session(backend):
    """Two sessions must not share KV tensors -- that is the whole design."""
    be, _ = backend
    async def go():
        a = await be.new_session()
        b = await be.new_session()
        await a.feed_prompt([1, 2, 3])
        await b.feed_prompt([1, 2, 3])
        return a, b
    a, b = asyncio.run(go())
    fa = [i for i in range(be.num_layers) if be.is_fa(i)][0]
    assert a.past_key[fa] is not b.past_key[fa]


def test_prefill_runs_every_block_and_sets_kv(backend):
    be, engine = backend
    async def go():
        s = await be.new_session()
        await s.feed_prompt([1, 2, 3, 4])
        return s
    s = asyncio.run(go())

    graphs = [g for g, _ in engine.calls]
    assert graphs.count("embedding") == 1
    for i in range(be.num_layers):
        assert f"block_{i}" in graphs, f"layer {i} was skipped"
    assert "lm_head" in graphs
    assert s.kv_len == 4
    # Every FA layer's KV must have been written.
    for i in range(be.num_layers):
        if be.is_fa(i):
            assert s.past_key[i].synced, f"FA layer {i} never synced its K cache"


def test_prefill_mask_is_causal(backend):
    """The mask handed to the FA block must be lower-triangular."""
    be, engine = backend
    n = 4
    async def go():
        s = await be.new_session()
        await s.feed_prompt([1] * n)
    asyncio.run(go())

    from app.engine.sail_backend import FA_INTERVAL
    fa_call = next(c for c in engine.calls if c[0] == f"block_{FA_INTERVAL - 1}")
    mask_tensor = fa_call[1]["inputs"][2]
    # The tensor was allocated at max shape then reshaped to the live prompt
    # size; read it through the live shape, not the allocation.
    assert mask_tensor.shape == [1, 1, n, n], mask_tensor.shape
    mask = mask_tensor.asnumpy().reshape(-1)[: n * n].reshape(n, n)
    assert mask.shape == (n, n)
    # 0 on/below the diagonal, non-zero above it.
    for i in range(n):
        for j in range(n):
            if j <= i:
                assert mask[i, j] == 0, f"position ({i},{j}) should be visible"
            else:
                assert mask[i, j] != 0, f"position ({i},{j}) should be masked"


def test_decode_advances_step_and_appends_at_the_right_offset(backend):
    be, engine = backend
    async def go():
        s = await be.new_session()
        await s.feed_prompt([1, 2, 3])
        engine.calls.clear()
        await s.step()
        return s
    s = asyncio.run(go())
    assert s.kv_len == 4, "decode must advance the KV length"
    fa = [i for i in range(be.num_layers) if be.is_fa(i)][0]
    # The last sync is the decode append, at offset (tokens_before * kv_stride).
    # Prefill also synced (at offset 0), so check the last one rather than all.
    offsets = [dst for (_src, dst, _n) in s.past_key[fa].synced]
    assert offsets[-1] == 3 * be.kv_stride, offsets


def test_decode_mask_matches_reference_offsets(backend):
    """Decode mask must mask exactly [kv_len:] , as the vendor demo does.

    This asserts parity with qwen3_5.py:forward_next
    (``attention_mask[0, 0, 0, self.step:self.seq_len] = MASK_VALUE``) rather
    than a semantic guess about whether the current position is visible: the
    offset is the thing a port can get wrong, and the mask's exact interpretation
    is a property of the compiled graph that only the board can confirm.
    """
    be, engine = backend
    async def go():
        s = await be.new_session()
        await s.feed_prompt([1, 2, 3])
        engine.calls.clear()
        await s.step()
        return s
    s = asyncio.run(go())
    from app.engine.sail_backend import FA_INTERVAL
    fa_calls = [c for c in engine.calls if c[0] == f"block_cache_{FA_INTERVAL - 1}"]
    assert fa_calls, "the attention block never ran"
    mask = fa_calls[0][1]["inputs"][2].asnumpy().reshape(-1)
    kv_len = 3  # prompt length at the time of the first decode step
    assert all(mask[i] == 0 for i in range(kv_len)), "past positions must not be masked"
    assert mask[kv_len] != 0, "the mask must start exactly at kv_len"
    assert mask[kv_len + 1] != 0


def test_stop_tokens_recognised(backend):
    be, _ = backend
    assert be.stop_ids == {2, 3}


def test_restore_puts_kv_back(backend):
    """A restored snapshot must leave the session decoding from that state."""
    be, _ = backend
    async def go():
        a = await be.new_session()
        await a.feed_prompt([1, 2, 3, 4])
        snap = await a.snapshot(4)
        b = await be.new_session()
        await b.restore(snap)
        return a, b, snap
    a, b, snap = asyncio.run(go())
    assert snap.token_len == 4
    assert b.token_len == 4
    assert b.kv_len == 4
    # One slot per layer (K and V), FA sized per token, linear state in full.
    fa_layers = [i for i in range(be.num_layers) if be.is_fa(i)]
    assert len(snap.tensors) == 2 * be.num_layers
    assert snap.nbytes > 0


def test_snapshot_covers_exactly_the_requested_prefix(backend):
    """Snapshotting a prompt prefix must not store the generated tokens.

    Regression: snapshot() used to take the session's *current* length, so a
    request that generated N tokens stored prompt+N of KV under a key that the
    cache advertised as prompt-only. A later hit then restored a longer context
    than the request contained.
    """
    be, _ = backend
    async def go():
        s = await be.new_session()
        await s.feed_prompt([1, 2, 3, 4])
        for _ in range(3):
            await s.step()          # pretend to generate
        return s, await s.snapshot(4)   # prompt-only snapshot
    s, snap = asyncio.run(go())
    assert s.kv_len == 7, "session has grown past the prompt"
    assert snap.token_len == 4, "snapshot must cover only the prompt prefix"

    # And restoring it reproduces the prompt state, not the generated one.
    async def restore():
        t = await be.new_session()
        await t.restore(snap)
        return t
    t = asyncio.run(restore())
    assert t.kv_len == 4


def test_shapes_ignore_config_json_entirely(backend):
    """Every shape must survive a config.json that lies.

    The 35B model ships hidden_size 1024 / 24 layers against a bmodel that is
    2048 / 40, so a config-derived shape would silently allocate wrong buffers.
    """
    be, _ = backend
    # The fixture's config.json claims 1024; the engine says 64.
    assert be.config.get("hidden_size") == 1024
    assert be.hidden_size == 64
    assert be.shape_source == "bmodel"


def test_missing_config_json_still_loads(tmp_path, monkeypatch):
    """No config.json must not prevent load; shapes come from the bmodel anyway."""
    fake_sail.install(monkeypatch)
    import sys, types
    tr = types.ModuleType("transformers")
    tr.AutoProcessor = types.SimpleNamespace(from_pretrained=lambda *a, **k: FakeProcessor())
    monkeypatch.setitem(sys.modules, "transformers", tr)

    d = tmp_path / "cfg"
    d.mkdir()
    from app.engine.sail_backend import SailBackend
    be = SailBackend("m", "/fake/m.bmodel", str(d), 0)
    assert be.hidden_size == 64
    assert be.num_layers == 8
