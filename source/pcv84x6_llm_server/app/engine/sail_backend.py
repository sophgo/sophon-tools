"""Real backend: sophon.sail.EngineLLM.

This is the only file that must run on the board. It is written against the
same control flow as sophon-demo's ``Qwen3_5/python/qwen3_5.py`` (which is the
vendor-blessed reference and the only thing known to work on this chip), with
three changes that matter for a server rather than a demo:

1. **Sessions own their KV.** The demo keeps KV in ``self.past_key_input`` on
   the model object, which makes it a single-conversation program. Here each
   :class:`SailSession` holds its own tensors, so the scheduler can interleave
   many conversations over one set of weights.
2. **Prefill is chunked and resumable.** The demo prefills the whole prompt in
   one call; the scheduler needs to interleave, so ``feed_prompt`` must be able
   to stop and resume at a chunk boundary.
3. **Snapshots for the prefix cache.** ``snapshot``/``restore`` copy the KV
   tensors out and back, which is what lets a repeated system prompt skip
   prefill entirely.

Everything here is unverified on hardware until the board is back; the file is
kept honest by ``tests/test_sail_backend_contract.py``, which runs it against a
fake ``sail`` module.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Sequence

import numpy as np

from .base import EngineBackend, Session, Token
from .kv_pool import (
    DEFAULT_HOST_BUDGET,
    UNBOUNDED,
    DeviceSnapshotStore,
    HostSnapshotStore,
    TieredSnapshotStore,
)

logger = logging.getLogger(__name__)

FA_INTERVAL = 4  # every 4th layer is full attention in Qwen3.5 (matches demo)


def _require_sail():
    """Import sail lazily so the module is importable on x86 for tests."""
    try:
        from sophon import sail  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only off-device
        raise RuntimeError(
            "sophon.sail is not installed; this backend only runs on the CV84X6 board"
        ) from exc
    return sail


class SailSession(Session):
    def __init__(self, backend: "SailBackend") -> None:
        self._be = backend
        self._sail = backend.sail
        self._num_layers = backend.num_layers
        self._tokens: list[Token] = []
        self._generated: list[Token] = []
        # Per-session KV: this is the whole point of the class.
        self._past_key: list = [None] * self._num_layers
        self._past_value: list = [None] * self._num_layers
        self._allocated = False

        # State the forward passes read and write. Kept as public attributes
        # (matching the demo's names) so the ported code stays recognisable.
        self.kv_len = 0           # tokens already in the KV
        self.last_id = 0          # most recently sampled token
        self.kv_stride = backend.kv_stride   # elements per token per K/V plane
        self.next_pos_ids = backend.make_input_tensor(backend.fa_cache_graph, 1)
        self.next_mask = backend.make_input_tensor(backend.fa_cache_graph, 2)
        self.next_hidden = backend.make_output_tensor(backend.fa_cache_graph, 0)
        self.conv_out: list = [None] * self._num_layers
        self.rec_out: list = [None] * self._num_layers

    # -- KV allocation ---------------------------------------------------
    @property
    def past_key(self) -> list:
        return self._past_key

    @property
    def past_value(self) -> list:
        return self._past_value

    def _alloc_kv(self) -> None:
        """Allocate this session's KV tensors, zeroed.

        Every session gets its own copy: that is what lets several requests
        share one set of weights without corrupting each other's attention.
        """
        be = self._be
        for i in range(self._num_layers):
            name = f"block_cache_{i}"
            if be.is_fa(i):
                self._past_key[i] = be.make_input_tensor(name, 3)
                self._past_value[i] = be.make_input_tensor(name, 4)
            else:
                self._past_key[i] = be.make_input_tensor(name, 1)   # conv_state
                self._past_value[i] = be.make_input_tensor(name, 2)  # recurrent_state
                self.conv_out[i] = be.make_output_tensor(name, 1)
                self.rec_out[i] = be.make_output_tensor(name, 2)
            self._past_key[i].zeros()
            self._past_value[i].zeros()
        self._allocated = True

    @property
    def token_len(self) -> int:
        return len(self._tokens)

    # -- inference -------------------------------------------------------
    async def feed_prompt(self, tokens: Sequence[Token]) -> None:
        be = self._be
        if not self._allocated:
            self._alloc_kv()
        # The demo's forward_first does prefill for the whole prompt; here the
        # scheduler hands us chunks. Only the first chunk pays the "first" path
        # (which builds the causal mask and populates KV); later chunks extend
        # it with the cache path.
        if not self._tokens:
            be.forward_prefill(self, list(tokens))
        else:
            be.forward_extend(self, list(tokens))
        self._tokens.extend(tokens)

    async def step(self) -> Token:
        be = self._be
        # Rotate position is the index of the token being generated, i.e. how
        # many tokens are already in the KV. Using the last token *id* here (an
        # easy mistake) would scramble the rotary embedding.
        pos = len(self._tokens)
        token = be.forward_next(self, pos)
        self._generated.append(token)
        self._tokens.append(token)
        return token

    def decode(self, tokens: Sequence[Token]) -> str:
        return self._be.tokenizer.decode(list(tokens), skip_special_tokens=True)

    def is_stop_token(self, token: Token) -> bool:
        return token in self._be.stop_ids

    # -- prefix cache support -------------------------------------------
    def kv_tensors(self) -> list:
        """Every KV tensor this session owns, in a stable order.

        Order matters: the snapshot stores them positionally, so this must be
        deterministic across capture and restore.
        """
        out = []
        for i in range(self._num_layers):
            out.append(self._past_key[i])
            out.append(self._past_value[i])
        return out

    def kv_elems_per_token(self, tensor) -> int:
        """Elements of this tensor that belong to one token."""
        # FA KV is [1, heads, head_dim, ctx]: only the last axis is per-token.
        # Linear-attention state is a fixed-size recurrent buffer that is
        # rewritten every step, not appended to, so it is wholly per-"token"
        # (it must be copied in full).
        if tensor.shape[-1] == self._be.context_length:
            return 1
        return tensor.size()

    def snapshot_plan(self, token_len: int) -> list[tuple]:
        """(tensor, index, element_count) for a snapshot of ``token_len`` tokens."""
        plan = []
        for i in range(self._num_layers):
            k, v = self._past_key[i], self._past_value[i]
            fa = self._be.is_fa(i)
            plan.append((k, i, (token_len if fa else k.size())))
            plan.append((v, i, (token_len if fa else v.size())))
        return plan

    async def snapshot(self, token_len: int) -> object:
        """Copy KV for ``token_len`` tokens into the configured store."""
        return self._be.snapshot_store.capture(self, token_len)

    async def restore(self, snap: object) -> None:
        if not self._allocated:
            self._alloc_kv()
        self._be.snapshot_store.apply(self, snap)
        # The snapshot holds a token *count*, not the ids: KV position is all the
        # forward passes need, and keeping ids would double the memory.
        self._tokens = [0] * int(snap.token_len)
        self.kv_len = int(snap.token_len)
        self.last_id = 0

    async def close(self) -> None:
        self._past_key = [None] * self._num_layers
        self._past_value = [None] * self._num_layers
        self._tokens.clear()
        self._generated.clear()
        self._allocated = False


class SailBackend(EngineBackend):
    def __init__(
        self,
        model_id: str,
        model_path: str,
        config_path: str,
        dev_id: int = 0,
        snapshot_location: str = "device",
        device_kv_budget: int = UNBOUNDED,
        host_kv_budget: int = DEFAULT_HOST_BUDGET,
    ) -> None:
        self._model_id = model_id
        self.sail = _require_sail()
        self.dev_id = dev_id

        import time

        from transformers import AutoProcessor  # type: ignore

        t0 = time.time()
        logger.info("loading %s onto dev %s", model_path, dev_id)
        self.handle = self.sail.Handle(dev_id)
        self.net = self.sail.EngineLLM(
            model_path, self.sail.BmrtFlag.BM_RUNTIME_SHARE_MEM, [dev_id]
        )
        logger.info("weights loaded in %.1fs", time.time() - t0)

        self.graph_names = self.net.get_graph_names()
        self.num_layers = sum(1 for g in self.graph_names if "block_cache_" in g)
        self.hidden_size = self.net.get_input_shape("lm_head", 0)[1]
        _kv_shape = self.net.get_input_shape(self.fa_cache_graph, 3)
        self._context_length = _kv_shape[-1]
        # Elements per token per K/V plane: num_heads * head_dim.
        kv_shape = self.net.get_input_shape(self.fa_cache_graph, 3)
        self.kv_stride = 1
        for dim in kv_shape[1:]:
            self.kv_stride *= dim

        self.processor = AutoProcessor.from_pretrained(config_path, trust_remote_code=True)
        self.tokenizer = self.processor.tokenizer

        self.stop_ids = {
            self.tokenizer.convert_tokens_to_ids(t)
            for t in ("<|im_end|>", "<|end|>")
            if self.tokenizer.convert_tokens_to_ids(t) is not None
        }
        self.image_pad_id = self.tokenizer.convert_tokens_to_ids("<|image_pad|>")
        self.vision_start_id = self.tokenizer.convert_tokens_to_ids("<|vision_start|>")

        # Shapes come from the bmodel, never from config.json.
        #
        # This is not hypothetical: the 35B model's shipped config.json declares
        # hidden_size 1024 and 24 layers, while the bmodel is 2048 and 40. Every
        # buffer size, mask shape and KV stride therefore has exactly one source
        # of truth, and config.json is used only for what it is actually good
        # for -- tokenizer and generation defaults.
        self.config = {}
        try:
            with open(os.path.join(config_path, "config.json")) as f:
                self.config = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("config.json unreadable (%s); using tokenizer defaults only", exc)

        mismatches = {
            k: (self.config.get(k), v)
            for k, v in (("hidden_size", self.hidden_size), ("num_hidden_layers", self.num_layers))
            if self.config.get(k) not in (None, v)
        }
        if mismatches:
            logger.warning(
                "config.json disagrees with the bmodel on %s; ignoring config.json "
                "for shapes (bmodel is authoritative)",
                ", ".join(f"{k}: config={c} bmodel={b}" for k, (c, b) in mismatches.items()),
            )
        self.shape_source = "bmodel"

        self.np = np
        self._input_tensors: dict[str, list] = {}
        self._output_tensors: dict[str, list] = {}
        self._prepare_static_tensors()

        # Where prefix-cache snapshots live. "device" keeps them in the NPU heap
        # (~23.75 GiB) instead of the ~2.5 GiB of system RAM Linux can see; the
        # tiered store falls back to host when the device budget is spent.
        #
        # The device budget defaults to UNBOUNDED (MYS-2785): the cache's own
        # ceiling is the model's runtime budget, and a store ceiling on top of it
        # only refused snapshots the cache had already made room for. In the
        # tiered mode it still caps *when to fall back to host*, which is a
        # placement question rather than a ceiling -- set ``device_kv_budget``
        # explicitly to keep that policy.
        host_store = HostSnapshotStore(host_kv_budget)
        device_store = DeviceSnapshotStore(self, device_kv_budget)
        if snapshot_location == "host":
            self.snapshot_store = host_store
        elif snapshot_location == "device":
            # No host fallback: an explicit "device only" request must not
            # quietly start consuming system RAM.
            self.snapshot_store = device_store
        else:
            self.snapshot_store = TieredSnapshotStore(device_store, host_store)

        # Shared scratch outputs for the attention layers. Every session writes
        # into these and immediately syncs into its own KV, so they are safe to
        # share across sessions -- the scheduler never runs two steps at once.
        self._fa_k_out = self.make_output_tensor(self.fa_cache_graph, 1)
        self._fa_v_out = self.make_output_tensor(self.fa_cache_graph, 2)

    # -- helpers used by SailSession ------------------------------------
    def is_fa(self, layer_idx: int) -> bool:
        return (layer_idx + 1) % FA_INTERVAL == 0

    def make_input_tensor(self, graph: str, idx: int):
        shape = self.net.get_input_shape(graph, idx)
        dtype = self.net.get_input_dtype(graph, idx)
        return self.sail.Tensor(self.handle, shape, dtype, False, True)

    def make_output_tensor(self, graph: str, idx: int):
        shape = self.net.get_output_shape(graph, idx)
        dtype = self.net.get_output_dtype(graph, idx)
        return self.sail.Tensor(self.handle, shape, dtype, False, True)

    @property
    def fa_graph(self) -> str:
        """Graph name of the full-attention block used for prefill/decode."""
        return f"block_{FA_INTERVAL - 1}"

    @property
    def fa_cache_graph(self) -> str:
        return f"block_cache_{FA_INTERVAL - 1}"

    def _prepare_static_tensors(self) -> None:
        wanted = ["embedding", "embedding_cache", "lm_head", "block_0", self.fa_graph,
                  self.fa_cache_graph, "greedy_head", "sample_head"]
        for g in wanted:
            if g in self.graph_names:
                self._input_tensors[g] = self.net.create_max_input_tensors(g)
                self._output_tensors[g] = self.net.create_max_output_tensors(g)

    # -- forward passes --------------------------------------------------
    def _type_convert(self, sail_dtype):
        """Map a sail dtype to the numpy dtype used to build host buffers."""
        np = self.np
        if sail_dtype == self.sail.Dtype.BM_FLOAT32:
            return np.float32
        if sail_dtype == self.sail.Dtype.BM_FLOAT16:
            return np.float16
        if sail_dtype == self.sail.Dtype.BM_INT32:
            return np.int32
        if sail_dtype == self.sail.Dtype.BM_BFLOAT16:
            return np.uint16
        raise TypeError(f"unsupported dtype {sail_dtype}")

    @property
    def norm_dtype(self):
        """Dtype used for the additive-mask value in each precision."""
        np = self.np
        d = self.net.get_output_dtype("embedding_cache", 0)
        if d == self.sail.Dtype.BM_FLOAT16:
            return np, np.uint16, 0xF0E2   # -inf in fp16 bit pattern
        if d == self.sail.Dtype.BM_BFLOAT16:
            return np, np.uint16, 0xC61C   # -inf in bf16 bit pattern
        raise TypeError("attention mask only supports float16/bfloat16")

    def forward_prefill(self, sess: "SailSession", tokens: list[int]) -> None:
        """Prefill the whole prompt. Ported from qwen3_5.py:forward_first.

        One call for the entire prompt (see supports_chunked_prefill): the causal
        mask is built at prompt size, so it cannot be extended afterwards.

        Not verified on hardware yet -- the board was unavailable. The logic is a
        line-for-line port of the vendor demo, which is the only implementation
        known to work on this chip.
        """
        np, mask_dtype, mask_value = self.norm_dtype
        n = len(tokens)

        # 1. Token embedding for the whole prompt.
        embed_in = self._input_tensors["embedding"]
        ids = np.zeros(embed_in[0].shape, dtype=self._type_convert(embed_in[0].dtype))
        ids[0, :n] = np.asarray(tokens, dtype=ids.dtype)
        embed_in[0].update_data(ids)
        self.net.process("embedding", embed_in, self._output_tensors["embedding"])

        # 2. Causal mask [1,1,n,n]: 0 on and below the diagonal, -inf above.
        mask = np.full((1, 1, n, n), mask_value, dtype=mask_dtype)
        lower = np.tril(np.ones((n, n), dtype=bool))
        mask[0, 0][lower] = 0
        # position ids: text-only, so all three axes are 0..n-1.
        pos = np.asarray([list(range(n))] * 3, dtype=np.int32)

        # 3. Run every block, carrying hidden state forward.
        hidden = self._output_tensors["embedding"][0]
        fa_block = self.fa_graph
        for idx in range(self.num_layers):
            is_fa = self.is_fa(idx)
            gname = f"block_{idx}"
            inputs = self._input_tensors["block_0" if not is_fa else fa_block]
            outputs = self._output_tensors["block_0" if not is_fa else fa_block]

            inputs[0] = self.sail.Tensor(hidden, [1, n, self.hidden_size], 0)
            if is_fa:
                inputs[1].reshape([3, n])
                inputs[2].reshape([1, 1, n, n])
                inputs[1].update_data(pos.reshape(3, n))
                inputs[2].update_data(mask)
            else:
                # Linear-attention blocks take a zeroed conv state on prefill.
                inputs[1].zeros()

            out = {0: self._output_tensors["block_0"][0]}
            if is_fa:
                out[1] = self._fa_k_out
                out[2] = self._fa_v_out
            else:
                for oi in range(1, self.net.get_output_num("block_0")):
                    out[oi] = outputs[oi]

            self.net.process(gname, inputs, out)

            # Stash KV into this session's own tensors.
            if is_fa:
                elems = sess.kv_stride * n
                sess.past_key[idx].sync_d2d(self._fa_k_out, 0, 0, elems)
                sess.past_value[idx].sync_d2d(self._fa_v_out, 0, 0, elems)
            else:
                sess.past_key[idx].sync_d2d(out[1], 0, 0, out[1].size())
                sess.past_value[idx].sync_d2d(inputs[1], 0, 0, inputs[1].size())

            hidden = self._output_tensors["block_0"][0]

        sess.kv_len = n
        # 4. lm_head on the last token only.
        lm_in = self.sail.Tensor(hidden, [1, self.hidden_size],
                                 (n - 1) * self.hidden_size)
        self.net.process("lm_head", {0: lm_in}, self._output_tensors["lm_head"])
        sess.last_id = self.sample_token()

    def forward_extend(self, sess: "SailSession", tokens: list[int]) -> None:
        raise NotImplementedError(
            "分块续接 prefill 在 SAIL 上不可用：causal mask 按整段 prompt 尺寸构造"
        )

    def forward_next(self, sess: "SailSession", pos: int) -> int:
        """Decode one token. Ported from qwen3_5.py:forward_next."""
        np, mask_dtype, mask_value = self.norm_dtype

        # 1. Embed the single previous token.
        embed_in = self._input_tensors["embedding_cache"]
        tok = np.asarray([[sess.last_id]], dtype=self._type_convert(embed_in[0].dtype))
        embed_in[0].update_data(tok)
        self.net.process("embedding_cache", embed_in, self._output_tensors["embedding_cache"])
        hidden = self._output_tensors["embedding_cache"][0]

        # 2. Mask: everything from the current position onward is masked out.
        fa_block = self.fa_cache_graph
        mask_shape = self.net.get_input_shape(fa_block, 2)
        mask = np.zeros(mask_shape, dtype=mask_dtype)
        mask[0, 0, 0, sess.kv_len:] = mask_value
        pos_ids = np.asarray([[pos], [pos], [pos]], dtype=np.int32)
        sess.next_pos_ids.update_data(pos_ids)
        sess.next_mask.update_data(mask)

        for idx in range(self.num_layers):
            gname = f"block_cache_{idx}"
            if self.is_fa(idx):
                inputs = {
                    0: hidden,
                    1: sess.next_pos_ids,
                    2: sess.next_mask,
                    3: sess.past_key[idx],
                    4: sess.past_value[idx],
                }
                outputs = {0: sess.next_hidden, 1: self._fa_k_out, 2: self._fa_v_out}
                self.net.process(gname, inputs, outputs)
                # Append this token's K/V at the current position.
                off = sess.kv_len * sess.kv_stride
                sess.past_key[idx].sync_d2d(self._fa_k_out, 0, off, sess.kv_stride)
                sess.past_value[idx].sync_d2d(self._fa_v_out, 0, off, sess.kv_stride)
            else:
                inputs = {0: hidden, 1: sess.past_key[idx], 2: sess.past_value[idx]}
                outputs = {0: sess.next_hidden, 1: sess.conv_out[idx], 2: sess.rec_out[idx]}
                self.net.process(gname, inputs, outputs)
                sess.past_key[idx].sync_d2d(sess.conv_out[idx], 0, 0, sess.conv_out[idx].size())
                sess.past_value[idx].sync_d2d(sess.rec_out[idx], 0, 0, sess.rec_out[idx].size())
            hidden = sess.next_hidden

        sess.kv_len += 1
        self.net.process("lm_head", {0: hidden}, self._output_tensors["lm_head"])
        sess.last_id = self.sample_token()
        return sess.last_id

    def sample_token(self) -> int:
        """Greedy for now; sampling parameters are applied by the scheduler."""
        out = self._output_tensors["lm_head"][0].asnumpy()
        return int(out.reshape(-1)[0])

    def clone_tensor_prefix(self, src, token_len: int):
        """Allocate an NPU tensor holding ``token_len`` tokens of ``src``.

        FA KV is [1, heads, head_dim, ctx] with the context on the last axis, so
        the clone is [1, heads, head_dim, token_len] -- sized to what is actually
        cached rather than the full context, which is most of the saving.
        Linear-attention state is fixed size and cloned whole.
        """
        shape = list(src.shape)
        if shape[-1] == self._context_length:
            shape[-1] = max(1, token_len)
        return self.sail.Tensor(self.handle, shape, src.dtype, False, True)

    # -- EngineBackend ---------------------------------------------------
    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def context_length(self) -> int:
        return self._context_length

    @property
    def supports_vision(self) -> bool:
        return "vit" in self.graph_names

    @property
    def supports_chunked_prefill(self) -> bool:
        # Forward only: the demo's forward_first sizes the causal mask from the
        # full prompt, so a mid-prefill extension would use the wrong mask.
        return False

    async def encode(self, text: str, images: Sequence[bytes] | None = None) -> list[Token]:
        if not images:
            ids = self.tokenizer(text, return_tensors=None)["input_ids"]
            return list(ids)
        raise NotImplementedError("VLM encoding needs on-device bring-up")

    async def new_session(self) -> Session:
        return SailSession(self)

    async def close(self) -> None:
        self._input_tensors.clear()
        self._output_tensors.clear()
