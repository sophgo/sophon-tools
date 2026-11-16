#!/usr/bin/env python3
"""Board greedy output for the dense Qwen3.5 builds (MYS-2754).

Drives the engine's C API directly, on the board, for the same prompts the x86
reference used (``tools/qwen35_prompts.json``), and writes the file
``tools/qwen35_compare.py`` reads.

    python3 tools/qwen35_board_run.py --lib libcv84x6_llm.so \\
        --bmodel /data/.../qwen3.5-4b-...bmodel --tokenizer model-config/qwen3_5 \\
        --prompts tools/qwen35_prompts.json --out board-4b-w4.json --steps 128

Deliberately no HTTP: the service's scheduler may admit a request later than it
arrives or apply a different max_tokens, and a precision comparison needs the
board to answer the exact tokens it was given. The image case is skipped unless
``--image`` names a file, for the reason given in ``tools/qwen35_hf_ref.py``.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time


def bind(lib_path: str):
    """The engine's C ABI, exactly as ``app/engine/native.py`` declares it.

    Copied from the service rather than guessed -- see the note in
    ``tools/qwen35_bench.py``: a wrong ``llm_session_prefill`` signature does not
    raise, it makes the engine read arguments off the stack and die with
    ``std::bad_alloc``, which is indistinguishable from a model defect.
    """
    lib = ctypes.CDLL(lib_path)
    c = lib
    err = ctypes.POINTER(ctypes.c_char_p)
    c.llm_engine_load.argtypes = [ctypes.c_char_p, ctypes.c_int, err]
    c.llm_engine_load.restype = ctypes.c_void_p
    c.llm_engine_free.argtypes = [ctypes.c_void_p]
    for name in ("context_length", "max_input_length", "has_vision", "fault"):
        fn = getattr(c, f"llm_engine_{name}")
        fn.argtypes = [ctypes.c_void_p]
        fn.restype = ctypes.c_int
    c.llm_engine_set_vocab_size.argtypes = [ctypes.c_void_p, ctypes.c_int]
    c.llm_session_new.argtypes = [ctypes.c_void_p, err]
    c.llm_session_new.restype = ctypes.c_void_p
    c.llm_session_free.argtypes = [ctypes.c_void_p]
    c.llm_session_token_len.argtypes = [ctypes.c_void_p]
    c.llm_session_token_len.restype = ctypes.c_int
    c.llm_session_prefill.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
        ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_int,
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_float)),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_int)),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_int)),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_float)), err]
    c.llm_session_prefill.restype = ctypes.c_int
    c.llm_session_decode.argtypes = [ctypes.c_void_p, ctypes.c_void_p, err]
    c.llm_session_decode.restype = ctypes.c_int
    c.llm_last_error.restype = ctypes.c_char_p
    return lib


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", required=True)
    ap.add_argument("--bmodel", required=True)
    ap.add_argument("--tokenizer", required=True)
    ap.add_argument("--prompts", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=128)
    ap.add_argument("--image", default="")
    a = ap.parse_args()

    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(os.path.join(a.tokenizer, "tokenizer.json"))
    lib = bind(a.lib)

    t0 = time.perf_counter()
    err = ctypes.c_char_p()
    engine = lib.llm_engine_load(a.bmodel.encode(), 0, ctypes.byref(err))
    if not engine:
        print("load failed:", (err.value or b"?").decode(errors="replace"))
        return 1
    load_s = time.perf_counter() - t0
    ctx = lib.llm_engine_context_length(engine)
    # The bmodel does not carry the vocabulary size; the tokenizer does, and the
    # engine range-checks every prompt id against it (an out-of-range id is an
    # out-of-bounds gather the TPU faults on, not an error it reports).
    lib.llm_engine_set_vocab_size(engine, tok.get_vocab_size())
    print(f"loaded in {load_s:.1f}s, context {ctx}, vocab {tok.get_vocab_size()}")

    cases = json.load(open(a.prompts))
    results = []
    for case in cases:
        if case.get("image") and not a.image:
            continue
        text = case["text"]
        if case.get("image"):
            text = text.replace("<image>", "<|vision_start|><|image_pad|><|vision_end|>")
        ids = tok.encode(render(text), add_special_tokens=False).ids
        if len(ids) > ctx:
            print(f"skip {case['id']}: {len(ids)} tokens > context {ctx}")
            continue

        session = lib.llm_session_new(engine, ctypes.byref(err))
        arr = (ctypes.c_int * max(len(ids), 1))(*ids)
        rc = lib.llm_session_prefill(engine, session, arr, len(ids), None, 0,
                                     None, None, None, None, None, None,
                                     ctypes.byref(err))
        gen = []
        if rc == 0:
            for _ in range(a.steps):
                t = lib.llm_session_decode(engine, session, ctypes.byref(err))
                if t < 0:
                    break
                gen.append(t)
        else:
            print(f"{case['id']}: prefill failed: "
                  f"{(err.value or b'').decode(errors='replace')}")
        lib.llm_session_free(session)

        results.append({
            "id": case["id"],
            "prompt_tokens": len(ids),
            "tokens": gen,
            "text": tok.decode(gen),
            "image": bool(case.get("image")),
        })
        print(f"{case['id']}: {len(ids)} prompt, {len(gen)} generated")

        if lib.llm_engine_fault(engine):
            print("TPU fault after this case; stopping", file=sys.stderr)
            break

    faulted = bool(lib.llm_engine_fault(engine))
    lib.llm_engine_free(engine)

    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump({"bmodel": os.path.basename(a.bmodel), "steps": a.steps,
                   "load_s": round(load_s, 1), "cases": results}, fh,
                  ensure_ascii=False, indent=1)
    print("wrote", a.out, "| faulted" if faulted else "")
    return 2 if faulted else 0


def render(user: str) -> str:
    """Must match ``tools/qwen35_hf_ref.py:render`` exactly.

    If the two disagree the comparison measures the prompt, not the model -- the
    reference and the board would be answering different questions.
    """
    return (f"<|im_start|>user\n{user}<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n\n</think>\n\n")


if __name__ == "__main__":
    sys.exit(main())
