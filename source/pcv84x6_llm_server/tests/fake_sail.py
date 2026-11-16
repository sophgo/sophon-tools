"""A fake `sophon.sail` sufficient to exercise SailBackend's control flow on x86.

It does not do arithmetic. It records the graph calls and shapes, which is what
the port can actually get wrong: a mask indexed at the wrong position, KV synced
to the wrong offset, the wrong number of blocks, and so on.
"""

from __future__ import annotations

import numpy as np


class Dtype:
    BM_FLOAT32 = "f32"
    BM_FLOAT16 = "f16"
    BM_INT32 = "i32"
    BM_BFLOAT16 = "bf16"


class BmrtFlag:
    BM_RUNTIME_SHARE_MEM = 0


class Tensor:
    def __init__(self, handle, shape, dtype, is_npu=True, is_dynamic=False):
        self.shape = list(shape)
        self.dtype = dtype
        self._data = np.zeros(shape, dtype=np.uint16)
        self.synced: list[tuple] = []
        self.zeroed = False

    def zeros(self):
        self._data[...] = 0
        self.zeroed = True

    def reshape(self, shape):
        self.shape = list(shape)

    def update_data(self, data):
        arr = np.asarray(data)
        flat = arr.reshape(-1)
        n = min(flat.size, self._data.size)
        self._data.reshape(-1)[:n] = flat[:n].astype(self._data.dtype)

    def asnumpy(self):
        return self._data

    def size(self):
        return self._data.size

    def sync_d2d(self, other, src_off, dst_off, count):
        self.synced.append((src_off, dst_off, count))

    @property
    def nbytes(self):
        return self._data.nbytes


class _Engine:
    """Fake EngineLLM whose graphs mirror Qwen3.5's layout."""

    def __init__(self, path, flag, devs, num_layers=8, hidden=64, ctx=2048,
                 kv_heads=4, head_dim=16, vision=False):
        self.num_layers = num_layers
        self.hidden = hidden
        self.ctx = ctx
        self.kv_heads = kv_heads
        self.head_dim = head_dim
        self.vision = vision
        self.calls: list[tuple[str, dict]] = []

    def get_graph_names(self):
        names = ["embedding", "embedding_cache", "lm_head", "greedy_head"]
        if self.vision:
            names.append("vit")
        for i in range(self.num_layers):
            names.append(f"block_{i}")
            names.append(f"block_cache_{i}")
        return names

    def _kv_shape(self):
        return [1, self.kv_heads, self.head_dim, self.ctx]

    def get_input_num(self, g):
        if g.startswith("block_cache_"):
            layer = int(g.rsplit("_", 1)[1])
            return 5 if (layer + 1) % 4 == 0 else 3
        if g.startswith("block_"):
            layer = int(g.rsplit("_", 1)[1])
            return 3 if (layer + 1) % 4 == 0 else 2
        return 3

    def get_output_num(self, g):
        return 3

    def get_input_shape(self, g, i):
        if g == "embedding":
            return [1, self.ctx] if i == 0 else [1]
        if g == "embedding_cache":
            return [1, 1] if i == 0 else [1]
        if g == "lm_head":
            return [1, self.hidden] if i == 0 else [1]
        if g.startswith("block_cache_"):
            layer = int(g.rsplit("_", 1)[1])
            fa = (layer + 1) % 4 == 0
            if i == 0:
                return [1, 1, self.hidden]
            if fa:
                return {1: [3, 1], 2: [1, 1, 1, self.ctx],
                        3: self._kv_shape(), 4: self._kv_shape()}[i]
            return {1: [1, 4, self.hidden], 2: [1, self.hidden]}[i]
        if g == "vit":
            return [[196, self.hidden], [196, 2], [196, 4], [196, 4, 1]][i]
        if g.startswith("block_"):
            layer = int(g.rsplit("_", 1)[1])
            fa = (layer + 1) % 4 == 0
            if i == 0:
                return [1, self.ctx, self.hidden]
            if fa:
                # prefill: position ids [3, seq] and the causal mask [-1,-1,seq,seq]
                return {1: [3, self.ctx], 2: [1, 1, self.ctx, self.ctx]}[i]
            return {1: [1, 4, self.hidden]}[i]
        return [1, self.ctx, self.hidden]

    def get_output_shape(self, g, i):
        if g == "embedding" or g == "embedding_cache":
            return [1, self.ctx, self.hidden] if i == 0 else [1]
        if g == "lm_head":
            return [1, 152064] if i == 0 else [1]
        if g == "greedy_head":
            return [1]
        if g.startswith("block_cache_"):
            layer = int(g.rsplit("_", 1)[1])
            fa = (layer + 1) % 4 == 0
            if i == 0:
                return [1, 1, self.hidden]
            if fa:
                return [1, self.kv_heads, self.head_dim, 1] if i in (1, 2) else [1]
            return [1, 4, self.hidden] if i == 1 else [1, self.hidden]
        if g == "vit":
            return [196, self.hidden]
        return [1, self.ctx, self.hidden]

    def get_input_dtype(self, g, i):
        return Dtype.BM_BFLOAT16 if "block" in g or g in ("embedding", "embedding_cache") else Dtype.BM_INT32

    def get_output_dtype(self, g, i):
        return Dtype.BM_BFLOAT16

    def create_max_input_tensors(self, g):
        return [Tensor(None, self.get_input_shape(g, i), self.get_input_dtype(g, i))
                for i in range(self.get_input_num(g))]

    def create_max_output_tensors(self, g):
        return [Tensor(None, self.get_output_shape(g, i), self.get_output_dtype(g, i))
                for i in range(self.get_output_num(g))]

    def get_is_dynamic(self, g):
        return False

    def process(self, g, inputs, outputs):
        self.calls.append((g, {"inputs": inputs, "outputs": outputs}))


class Handle:
    def __init__(self, dev):
        self.dev = dev


def install(monkeypatch, **engine_kw):
    """Install a fake `sophon.sail` module and return the fake engine."""
    import sys
    import types

    engine = _Engine("m", 0, [0], **engine_kw)
    sail = types.ModuleType("sophon.sail")
    sail.Dtype = Dtype
    sail.BmrtFlag = BmrtFlag
    sail.Tensor = Tensor
    sail.Handle = Handle
    sail.EngineLLM = lambda *a, **k: engine

    sophon = types.ModuleType("sophon")
    sophon.sail = sail
    monkeypatch.setitem(sys.modules, "sophon", sophon)
    monkeypatch.setitem(sys.modules, "sophon.sail", sail)
    return engine
