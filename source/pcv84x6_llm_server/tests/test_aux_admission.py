"""Embedding / rerank workers serve one request at a time, start to finish.

The NPU runs one forward at a time, so concurrency never made a request
faster; it held inputs in memory and, with requests interleaving text by text,
made everyone slower. These pin the behaviour with a fake engine (the real one
needs the device): FIFO per request, at most ``AUX_TEXT_MAX_QUEUE`` admitted,
the rest refused with ``AuxBusy`` immediately.
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from app.engine import aux_backend as ab


class _FakeTok:
    def encode_single_full(self, text):
        ids = [1] * max(1, len(text))
        return ids, len(ids)

    def encode_pair_full(self, query, doc):
        ids = [1] * (len(query) + len(doc))
        return ids, [1] * len(ids), list(range(len(ids))), len(ids)

    def token_count(self, ids):
        return len(ids)


class _FakeEngine:
    """Records which request each forward belonged to; one forward at a time."""

    def __init__(self):
        self.calls: list[str] = []
        self.busy = threading.Lock()
        self.overlap = False

    def forward(self, ids, *rest):
        if not self.busy.acquire(blocking=False):
            self.overlap = True
            self.busy.acquire()
        try:
            self.calls.append(self.current)
            time.sleep(0.02)
            return [0.0] if rest and rest[0] is None else 0.5
        finally:
            self.busy.release()


def _embed_backend(max_queue=16):
    b = object.__new__(ab.AuxEmbedBackend)
    b._model_id = "emb"
    b._tok = _FakeTok()
    b._engine = _FakeEngine()
    b.seq_len = 8192
    b._gate = ab._Serialised(min(max_queue, ab.AUX_TEXT_MAX_QUEUE))
    return b


def test_the_queue_ceiling_is_one_running_one_waiting():
    assert ab.AUX_TEXT_MAX_QUEUE == 2
    assert _embed_backend(16)._gate.max_queue == 2
    assert _embed_backend(1)._gate.max_queue == 1


@pytest.mark.asyncio
async def test_a_request_runs_all_its_texts_before_the_next_starts():
    b = _embed_backend()
    engine = b._engine

    async def tagged(tag, texts):
        # Tag forwards by the request whose batch is on the engine: the fake
        # reads ``current`` at call time, set when the batch starts.
        orig = b._forward_all

        def run(encoded, dims):
            engine.current = tag
            return orig(encoded, dims)
        b_forward = run
        return await ab._run_whole(b._gate, b_forward, [[1]] * len(texts), None)

    await asyncio.gather(tagged("A", ["x"] * 3), tagged("B", ["y"] * 3))
    assert engine.calls in (["A"] * 3 + ["B"] * 3, ["B"] * 3 + ["A"] * 3)
    assert not engine.overlap


@pytest.mark.asyncio
async def test_a_third_concurrent_request_is_refused_at_once():
    b = _embed_backend()
    b._engine.current = "x"
    first = asyncio.create_task(b.embed(["a"] * 10))
    second = asyncio.create_task(b.embed(["b"] * 10))
    await asyncio.sleep(0.01)
    t0 = time.monotonic()
    with pytest.raises(ab.AuxBusy):
        await b.embed(["c"])
    assert time.monotonic() - t0 < 0.05  # refused, not queued
    vectors, counts = await first
    assert len(vectors) == 10 and counts == [1] * 10
    await second


@pytest.mark.asyncio
async def test_every_input_is_validated_before_the_first_forward():
    b = _embed_backend()
    b.seq_len = 3
    b._engine.current = "x"
    with pytest.raises(ab.AuxRequestError):
        await b.embed(["ok", "much too long"])
    assert b._engine.calls == []


@pytest.mark.asyncio
async def test_rerank_also_runs_its_pairs_as_one_request():
    r = object.__new__(ab.AuxRerankBackend)
    r._model_id = "rr"
    r._tok = _FakeTok()
    r._engine = _FakeEngine()
    r._engine.current = "q"
    r.seq_len = 8192
    r._gate = ab._Serialised(ab.AUX_TEXT_MAX_QUEUE)
    logits, counts = await r.rerank("q", ["d1", "d2", "d3"])
    assert logits == [0.5, 0.5, 0.5] and counts == [3, 3, 3]
    assert r._engine.calls == ["q", "q", "q"]
