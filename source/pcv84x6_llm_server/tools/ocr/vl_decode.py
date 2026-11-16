#!/usr/bin/env python3
"""One element on the board: prompt -> vit -> prefill -> greedy decode.

**One bmrt context, 40 networks.** The bmodel is 2.27 GB of weights; loading it
once per network exhausts the NPU heap partway through the decode layers
(measured: ``bm_malloc_device_byte_u64`` fails while loading ``lm_head``). So
``Context`` loads the file once and every ``Net`` is a thin view of one network
inside it — which is what the C++ sample does with ``sail.EngineLLM``.

**KV cache.** ``block_cache_N`` is ``addr mode: 1``: the caller owns
``history_k``/``history_v`` (``[1,2048,2,128]`` bf16 bfloat16) and the graph
writes the new row at the current position. The sample does this with
``sail.Tensor(mem, shape, offset)``; with raw bmrt it is an address offset on
the tensor handed to the launch. Wrong offsets are silent, so the probe reports
the tokens it produced rather than only their count.

Prompt layout mirrors ``tests/data/ocr/golden.json`` (``paddleocr_vl.cases``)::

    <|begin_of_sentence|>User: <|IMAGE_START|> <|IMAGE_PLACEHOLDER|>*N
    <|IMAGE_END|><instruction>\\nAssistant:
"""
import argparse, ctypes as C, json, sys, time
sys.path.insert(0, "/data/qa3")
import numpy as np
import board_npu as B
from tokenizers import Tokenizer

SEQ, HID, KV_ELEMS = 2048, 1024, 2 * 128
MASK_NEG = np.float32(-9984)


def _d2d(lib, handle, dst_mem, dst_elem, src_mem, src_elem, elems, esz):
    """Device-to-device copy with the offsets the header expects (bytes)."""
    return lib.bm_memcpy_d2d(handle, dst_mem, dst_elem * esz,
                             src_mem, src_elem * esz, elems * esz)



def _f32_to_bf16(x: np.ndarray) -> np.ndarray:
    """float32 -> raw bf16 words (uint16), round-to-nearest-even.

    ``B.DTYPES[8]`` is ``uint16`` because that is how a bf16 tensor is *read*
    off the device; it is not a write type. Casting float32 to uint16 truncates
    toward zero, so every value below 1.0 became 0 and the next network saw an
    all-zero activation -- which still runs, and still emits a token.
    """
    f = np.ascontiguousarray(x, dtype=np.float32)
    u = f.view(np.uint32)
    lsb = (u >> 16) & 1
    rounded = u + 0x7FFF + lsb
    return (rounded >> 16).astype(np.uint16)


class Context:
    """One loaded bmodel; ``net(name)`` returns a launchable view."""

    def __init__(self, path):
        self.bmrt, self.bmlib = B.load_libs()
        self.bmlib.bm_memcpy_d2d.restype = C.c_int
        self.bmlib.bm_memcpy_d2d.argtypes = [C.c_void_p, B.BmMemDesc, C.c_int,
                                             B.BmMemDesc, C.c_int, C.c_int]
        self.h = C.c_void_p()
        assert self.bmlib.bm_dev_request(C.byref(self.h), 0) == 0 and self.h
        self.rt = self.bmrt.bmrt_create(self.h)
        assert self.bmrt.bmrt_load_bmodel(self.rt, path.encode()), f"load {path}"
        self.owned = []

    def alloc(self, nbytes):
        m = B.BmMemDesc()
        rc = self.bmlib.bm_malloc_device_byte_heap_mask(self.h, C.byref(m), 3, nbytes)
        assert rc == 0, f"malloc({nbytes}) rc={rc}"
        self.owned.append(m)
        return m

    def net(self, name):
        return Net(self, name)

    def copy(self, dst, dst_elem, src, src_elem, elems, esz):
        return _d2d(self.bmlib, self.h, dst, dst_elem, src, src_elem, elems, esz)

    def close(self):
        for m in self.owned:
            self.bmlib.bm_free_device(self.h, m)
        self.bmrt.bmrt_destroy(self.rt)
        self.bmlib.bm_dev_free(self.h)


class Net:
    def __init__(self, ctx, name):
        self.ctx, self.name = ctx, name
        self.bmrt, self.bmlib, self.h = ctx.bmrt, ctx.bmlib, ctx.h
        self.rt = ctx.rt
        info = self.bmrt.bmrt_get_network_info(ctx.rt, name.encode())
        assert info, f"no network {name}"
        t = B.net_table(info.contents)
        self.inputs, self.outputs = t["inputs"], t["outputs"]
        self.tin = (B.BmTensor * len(self.inputs))()
        self.tout = (B.BmTensor * len(self.outputs))()
        self.out_mem, self.out_buf = {}, {}
        for m in self.outputs:
            n = int(np.prod(m["dims"])) * np.dtype(B.DTYPES[m["dtype"]]).itemsize
            self.out_mem[m["name"]] = ctx.alloc(n)
            self.out_buf[m["name"]] = np.zeros(m["dims"], dtype=B.DTYPES[m["dtype"]])

    def _bind(self, t, mem, dtype, dims, off=0):
        if off:
            v = B.BmMemDesc()
            v.flags, v.size = mem.flags, mem.size
            esz = np.dtype(B.DTYPES[dtype]).itemsize
            v.u.device.device_addr = mem.u.device.device_addr + off * esz
            v.u.device.reserved = mem.u.device.reserved
            v.u.device.dmabuf_fd = mem.u.device.dmabuf_fd
            self.bmrt.bmrt_tensor_with_device(C.byref(t), v, dtype,
                                              B.BmShape(len(dims), (C.c_int*8)(*dims)))
        else:
            self.bmrt.bmrt_tensor_with_device(C.byref(t), mem, dtype,
                                              B.BmShape(len(dims), (C.c_int*8)(*dims)))

    def run(self, feeds, bind=None, offsets=None):
        bind, offsets = bind or {}, offsets or {}
        for i, m in enumerate(self.inputs):
            if m["name"] in bind:
                self._bind(self.tin[i], bind[m["name"]], m["dtype"], m["dims"],
                           offsets.get(m["name"], 0))
                continue
            feed = feeds[m["name"]]
            arr = (_f32_to_bf16(feed) if m["dtype"] == 8
                   else np.ascontiguousarray(feed.astype(B.DTYPES[m["dtype"]])))
            if list(arr.shape) != m["dims"]:
                raise RuntimeError(f"{self.name}/{m['name']}: {list(arr.shape)} != {m['dims']}")
            mem = self.ctx.alloc(arr.nbytes)
            self.bmlib.bm_memcpy_s2d(self.h, mem, arr.ctypes.data)
            self._bind(self.tin[i], mem, m["dtype"], m["dims"])
        for i, m in enumerate(self.outputs):
            mem = bind.get(m["name"], self.out_mem[m["name"]])
            self._bind(self.tout[i], mem, m["dtype"], m["dims"], offsets.get(m["name"], 0))
        t0 = time.perf_counter()
        assert self.bmrt.bmrt_launch_tensor_ex(
            self.rt, self.name.encode(), self.tin, len(self.inputs),
            self.tout, len(self.outputs), True, False), f"launch {self.name}"
        rc = self.bmrt.bmrt_thread_sync(self.rt)
        assert rc == 0, f"sync rc={rc}"
        dt = time.perf_counter() - t0
        out = {}
        for i, m in enumerate(self.outputs):
            buf = self.out_buf[m["name"]]
            self.bmlib.bm_memcpy_d2s(self.h, buf.ctypes.data, self.tout[i].device_mem)
            # BM_BFLOAT16 (dtype 8) arrives as raw 16-bit words; widening them is
            # the caller's job. Skipping this hands the next network bit
            # patterns it reads as numbers, which still "runs" and still emits
            # tokens -- it just emits nonsense (measured: <|LOC_283|> for a crop
            # that should read "CPU 使用率").
            out[m["name"]] = B.bf16_to_f32(buf) if m["dtype"] == 8 else buf
        return out, dt


def mrope(seq_len, gh, gw, text_before):
    """[3, seq]: image rows are (t=0, h, w) over the 2x2-merged grid."""
    h, w = gh // 2, gw // 2
    img = h * w
    pos = np.zeros((3, seq_len), np.int32)
    for r in range(3):
        pos[r, :text_before] = np.arange(text_before)
    base = text_before
    pos[1, base:base+img] = np.repeat(np.arange(h), w) + base
    pos[2, base:base+img] = np.tile(np.arange(w), h) + base
    tail = base + img
    if tail < seq_len:
        st = int(pos[:, :tail].max()) + 1
        for r in range(3):
            pos[r, tail:] = np.arange(seq_len - tail) + st
    return pos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="page_ui2")
    ap.add_argument("--bmodel", default="vl576.bmodel")
    ap.add_argument("--cfg", default="vlcfg/paddleocr_vl_1_5")
    ap.add_argument("--element", type=int, default=1)
    ap.add_argument("--max-new", type=int, default=24)
    ap.add_argument("--out", default="decode_one.json")
    a = ap.parse_args()

    man = json.load(open(f"{a.work}/manifest.json"))
    el = [e for e in man["elements"] if e["index"] == a.element][0]
    tok = Tokenizer.from_file(f"{a.cfg}/tokenizer.json")
    PH = tok.token_to_id("<|IMAGE_PLACEHOLDER|>")
    EOS = tok.token_to_id("</s>")

    head = "<|begin_of_sentence|>User: <|IMAGE_START|>"
    tail = f"<|IMAGE_END|>{el['prompt']}\nAssistant:\n"
    head_ids = tok.encode(head, add_special_tokens=False).ids
    tail_ids = tok.encode(tail, add_special_tokens=False).ids
    n_img = el["image_tokens"]
    ids = head_ids + [PH] * n_img + tail_ids
    L = len(ids)
    print(f"prompt {L} ids (head {len(head_ids)}, img {n_img}, tail {len(tail_ids)})",
          file=sys.stderr)

    ctx = Context(a.bmodel)
    tm = {}

    vit = ctx.net("vit")
    vout, tm["vit"] = vit.run({"input_states": np.load(f"{a.work}/{el['patches']}"),
                               "full_attn_mask": np.load(f"{a.work}/{el['mask']}")})
    vemb = vout["mlp_AR.linear_2_f32_bf16"].astype(np.float32)
    print(f"vit {tm['vit']*1e3:.1f}ms -> {vemb.shape}", file=sys.stderr)

    embed = ctx.net("embedding")
    pad = np.zeros((1, SEQ), np.int32); pad[0, :L] = ids
    eout, tm["embed"] = embed.run({"input_ids": pad})
    hidden = eout["embedding"].astype(np.float32)
    rows = slice(len(head_ids), len(head_ids) + n_img)
    assert hidden[0, rows].shape == vemb[0].shape
    hidden[0, rows] = vemb[0]

    # mrope over this element's own geometry: image rows are (t=0, h, w) on the
    # 2x2-merged grid, text rows are sequential on both sides. Using a flat
    # arange for all three rows instead is a documented-looking shortcut that
    # produces fluent-looking but wrong text (measured: <|LOC_283|>).
    pos = mrope(L, el["grid"][0], el["grid"][1], len(head_ids))
    assert pos.shape == (3, L)
    pos_pad = np.zeros((3, SEQ), np.int32); pos_pad[:, :L] = pos
    am = np.zeros((1, 1, SEQ, SEQ), np.float32)
    am[0, 0, :L, :L] = np.triu(np.ones((L, L), np.float32), 1) * MASK_NEG

    # one cache per layer: [1,2048,2,128] bf16 for k and v
    kv = [ctx.alloc(SEQ * KV_ELEMS * 2 * 2) for _ in range(18)]
    cur = hidden
    t0 = time.perf_counter()
    for i in range(18):
        blk = ctx.net(f"block_{i}")
        o, _ = blk.run({"input_states": cur, "position_ids": pos_pad, "attention_mask": am})
        cur = o["output_states"].astype(np.float32)
        # k_cache/v_cache are the layer's first token rows; stash them where the
        # decode blocks look for history_k/history_v.
        assert ctx.copy(kv[i], 0, blk.tout[1].device_mem, 0, L * KV_ELEMS, 2) == 0
        assert ctx.copy(kv[i], SEQ * KV_ELEMS, blk.tout[2].device_mem, 0,
                        L * KV_ELEMS, 2) == 0
    tm["prefill"] = time.perf_counter() - t0
    print(f"prefill {tm['prefill']*1e3:.1f}ms", file=sys.stderr)

    lm = ctx.net("lm_head")
    lout, tm["lm_head"] = lm.run({"hidden_states": cur[0, L-1:L].reshape(1, HID)})
    tokid = int(lout["token_id"].reshape(-1)[0])
    print(f"token0 {tokid} {tok.get_vocab().get(tokid,'')!r}", file=sys.stderr)

    # ---- decode loop ----
    dec = [ctx.net(f"block_cache_{i}") for i in range(18)]
    ecache = ctx.net("embedding_cache")
    out_ids = [tokid]
    n = L
    t0 = time.perf_counter()
    for step in range(a.max_new - 1):
        if tokid == EOS or n + 1 >= SEQ:
            break
        ec, _ = ecache.run({"input_ids": np.array([[tokid]], np.int32)})
        x = ec["embedding_cache"].astype(np.float32)
        p = np.zeros((3, 1), np.int32)
        p[:, 0] = mrope(n + 1, el["grid"][0], el["grid"][1], len(head_ids))[:, n]
        m = np.zeros((1, 1, 1, SEQ + 1), np.float32)
        m[0, 0, 0, n:SEQ] = MASK_NEG
        for i in range(18):
            bind = {"history_k": kv[i], "history_v": kv[i],
                    "k_cache": kv[i], "v_cache": kv[i]}
            offs = {"history_k": 0, "history_v": SEQ * KV_ELEMS,
                    "k_cache": n * KV_ELEMS, "v_cache": SEQ * KV_ELEMS + n * KV_ELEMS}
            o, _ = dec[i].run({"input_states": x, "position_ids": p,
                               "attention_mask": m}, bind=bind, offsets=offs)
            x = o["output_states"].astype(np.float32)
        lo, _ = lm.run({"hidden_states": x.reshape(1, HID)})
        tokid = int(lo["token_id"].reshape(-1)[0])
        out_ids.append(tokid)
        n += 1
    tm["decode"] = time.perf_counter() - t0
    ctx.close()

    text = tok.decode(out_ids, skip_special_tokens=True)
    print(f"decode {tm['decode']*1e3:.1f}ms for {len(out_ids)} tokens", file=sys.stderr)
    print(f"TEXT: {text!r}", file=sys.stderr)
    json.dump({"element": a.element, "label": el["label"], "prompt": el["prompt"],
               "prompt_tokens": L, "tokens": out_ids, "text": text,
               "timings_ms": {k: round(v*1e3, 2) for k, v in tm.items()}},
              open(a.out, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
