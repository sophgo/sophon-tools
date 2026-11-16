"""Prefill accuracy vs chunk size: every row's last-layer output, saved for
comparison with the HF reference (cmp_rows.py).

    LLM_DEBUG_HIDDEN=2 python3 lc_rows.py --model X --config cfg --lib lib.so \
        --chunks 2048,1024,512,256,128,64 --n 4096 --replay 512 --out rows/
"""
import argparse
import asyncio
import ctypes
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.environ.get("APP_ROOT", "."))

from app.engine.native import NativeBackend, Prompt  # noqa: E402

TEXT = ("In the spring of that year the river rose higher than anyone in the valley could "
        "remember. The miller moved his sacks to the loft, the baker baked through the night, "
        "and the children counted boats drifting past the church. ")


def rows(be, sess, hidden):
    buf = (ctypes.c_uint16 * (4096 * hidden))()
    n = be._lib.lib.llm_session_debug_rows(ctypes.c_void_p(sess._handle), buf, 4096 * hidden)
    raw = np.frombuffer(bytes(buf)[: 2 * n], dtype=np.uint16).astype(np.uint32) << 16
    return raw.view(np.float32).reshape(-1, hidden)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--lib", default=None)
    ap.add_argument("--chunks", default="2048,1024,512,256,128,64")
    ap.add_argument("--n", type=int, default=4096)
    ap.add_argument("--replay", type=int, default=512, help="rows for the decode-only reference")
    ap.add_argument("--out", default="rows")
    ap.add_argument("--layers", default="", help="LLM_DEBUG_LAYER values to loop over")
    a = ap.parse_args()
    be = NativeBackend(a.model, os.path.join(a.config, "tokenizer.json"), "r", lib_path=a.lib)
    lib = be._lib.lib
    lib.llm_session_debug_rows.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint16),
                                           ctypes.c_int]
    lib.llm_session_debug_rows.restype = ctypes.c_int
    H = 2048
    P = Prompt(be.tokenizer_encode(TEXT * 400)[: a.n])
    os.makedirs(a.out, exist_ok=True)
    plan = [("replay", a.replay)] if a.replay else []
    plan += [(f"c{c}", int(c)) for c in a.chunks.split(",")]
    layers = [int(x) for x in a.layers.split(",")] if a.layers else [None]
    plan = [(f"{n}_l{k}" if k is not None else n, c, k) for k in layers for n, c in plan]
    for name, c, layer in plan:
        if layer is not None:
            os.environ["LLM_DEBUG_LAYER"] = str(layer)
        if name.startswith("replay"):
            os.environ["LLM_PREFILL_ALIGN"], os.environ["LLM_ALIGN_ABOVE"] = "1000000", "0"
            n, step = c, c
        else:
            os.environ["LLM_PREFILL_ALIGN"], os.environ["LLM_ALIGN_ABOVE"] = "64", "0"
            n, step = a.n, c
        s = await be.new_session()
        t0 = time.time()
        got = []
        for off in range(0, n, step):
            await s.feed_prompt(P.segment(off, min(n, off + step)))
            got.append(rows(be, s, H))
        await s.close()
        m = np.concatenate(got)
        np.save(os.path.join(a.out, f"{name}.npy"), m)
        print(f"{name}: {m.shape[0]} rows in {time.time() - t0:.1f}s", flush=True)
    await be.close()


asyncio.run(main())
