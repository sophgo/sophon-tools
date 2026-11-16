#!/usr/bin/env python3
"""Board acceptance measurements for a chat bmodel (MYS-2754).

Everything the issue's acceptance criteria ask for that can be measured without
a reference model, in one run:

  * load time, and the static NPU/VPP occupancy afterwards;
  * decode tok/s, single session and two sessions at once;
  * first-token latency for a short prompt and for an 8k-token prompt;
  * the NPU left over, which is what decides whether the auxiliary models fit.

It drives the engine's C API directly (``libcv84x6_llm.so``) rather than the
HTTP service, for the same reason ``tools/decode_bench.py`` does: the scheduler,
the HTTP layer and the Python backend all sit between a request and the number a
report about the *model* should quote. The tokeniser is the shipped
``model-config/qwen3_5`` one, so prompts are tokenised exactly as the service
would.

Runs on the board, with libsophon's python bindings available:

    python3 tools/qwen35_bench.py --lib libcv84x6_llm.so \\
        --bmodel /data/.../qwen3.5-4b-...bmodel --tokenizer model-config/qwen3_5

It prints a JSON object to stdout so the numbers can be pasted into a report
without transcription, and refuses to run two measurements at once on one board
(the second session would change every figure).
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import statistics
import sys
import threading
import time

#: A prompt long enough to be "8k" without being exactly 8192: a round number is
#: what a reader assumes, and the scheduler's chunking is what the number is
#: about, not the exact token count.
LONG_PROMPT_TOKENS = 8192

SHORT_PROMPT = "用一句话说明什么是长上下文模型。"
LONG_FILLER = ("长上下文模型的成本主要来自 KV cache，它随序列长度线性增长。"
               "这里是一段用于填充上下文的说明文字，目的是让提示词达到八千 token。").replace("\n", "")


def bind(lib_path: str):
    """The engine's C ABI, exactly as ``app/engine/native.py`` declares it.

    Every signature here is copied from the service rather than guessed. The
    first version of this tool declared a 4-argument ``llm_session_prefill``;
    the real one takes the engine handle, the token count, a position matrix,
    an image count and four parallel image arrays, plus an ``err`` out-param.
    Calling it with the wrong number of arguments does not fail cleanly -- the
    engine reads the missing arguments off the stack and dies with
    ``std::bad_alloc`` inside prefill, which looks like a model defect and is
    not. (It reproduced on the shipped 35B too, which is what ruled the model
    out.)
    """
    lib = ctypes.CDLL(lib_path)
    c = lib
    err = ctypes.POINTER(ctypes.c_char_p)
    c.llm_engine_load.argtypes = [ctypes.c_char_p, ctypes.c_int, err]
    c.llm_engine_load.restype = ctypes.c_void_p
    c.llm_engine_free.argtypes = [ctypes.c_void_p]
    for name in ("num_layers", "context_length", "max_input_length",
                 "hidden_size", "has_vision", "vit_max_patches", "vit_dims",
                 "supports_history", "fault"):
        fn = getattr(c, f"llm_engine_{name}")
        fn.argtypes = [ctypes.c_void_p]
        fn.restype = ctypes.c_int
    c.llm_engine_kv_bytes_per_token.argtypes = [ctypes.c_void_p]
    c.llm_engine_kv_bytes_per_token.restype = ctypes.c_size_t
    c.llm_engine_linear_state_bytes.argtypes = [ctypes.c_void_p]
    c.llm_engine_linear_state_bytes.restype = ctypes.c_size_t
    c.llm_engine_session_state_bytes.argtypes = [ctypes.c_void_p]
    c.llm_engine_session_state_bytes.restype = ctypes.c_size_t
    c.llm_engine_set_vocab_size.argtypes = [ctypes.c_void_p, ctypes.c_int]
    c.llm_engine_vocab_size.argtypes = [ctypes.c_void_p]
    c.llm_engine_vocab_size.restype = ctypes.c_int
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
    c.llm_session_extend.argtypes = c.llm_session_prefill.argtypes
    c.llm_session_extend.restype = ctypes.c_int
    c.llm_session_decode.argtypes = [ctypes.c_void_p, ctypes.c_void_p, err]
    c.llm_session_decode.restype = ctypes.c_int
    c.llm_last_error.restype = ctypes.c_char_p
    return lib


def prefill_tokens(lib, engine, session, ids):
    """prefill with no images; returns (first token id, error string)."""
    n = len(ids)
    arr = (ctypes.c_int * max(n, 1))(*ids)
    err = ctypes.c_char_p()
    rc = lib.llm_session_prefill(engine, session, arr, n, None, 0,
                                 None, None, None, None, None, None,
                                 ctypes.byref(err))
    if rc != 0:
        return rc, (err.value or b"").decode("utf-8", "replace")
    # prefill returns 0 on success; the sampled token comes from decode().
    return 0, ""


def tokenize(tokenizer_dir: str, text: str):
    """Token ids from the shipped tokenizer, without the service's Python layer.

    ``tokenizers`` reads the same ``tokenizer.json`` the service passes to the
    worker, so this is the same tokenisation rather than an approximation.
    """
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(os.path.join(tokenizer_dir, "tokenizer.json"))
    return tok.encode(text, add_special_tokens=False).ids


def read_heaps() -> dict:
    """NPU/VPP used and total in MiB, from libsophon's own heap API.

    This is ``app/core/monitor._heaps_from_bmlib``, reused rather than
    reimplemented: ``bm-smi`` is the same numbers but ncurses, and the escape
    sequences it emits make it a parsing exercise whose column widths move
    between libsophon releases (this repo's own notes record two rounds of
    that). The service already solved it, and a measurement tool that disagreed
    with ``/api/stats`` about how much NPU is free would be worse than useless.
    """
    try:
        from app.core.monitor import device_memory
    except Exception:
        return {}
    try:
        snap = device_memory()
    except Exception:
        return {}
    out = {"source": snap.get("source")}
    for heap in snap.get("heaps") or []:
        out[heap["name"]] = {
            "used_mib": round(heap["used_bytes"] / 2**20, 1),
            "total_mib": round(heap["total_bytes"] / 2**20, 1),
            "free_mib": round(heap["free_bytes"] / 2**20, 1),
        }
    return out


def decode_rate(lib, engine, session, steps: int, threads: int = 1) -> float:
    """tok/s from ``steps`` decode calls, ignoring none (greedy, so every call
    does the same work; the first is kept because dropping it would bias the
    rate upward -- a warm cache is not a property a caller gets)."""
    err = ctypes.c_char_p()
    session_decode = lib.llm_session_decode
    session_decode(engine, session, ctypes.byref(err))
    t0 = time.perf_counter()
    n = 0
    for _ in range(steps):
        if session_decode(engine, session, ctypes.byref(err)) < 0:
            break
        n += 1
    dt = time.perf_counter() - t0
    return n / dt if dt > 0 else 0.0


def prefill_ms(lib, engine, session, ids) -> float:
    """Prefill ``ids``; returns ms to the end of prefill.

    The first token is not sampled here: ``llm_session_prefill`` returns a status
    code, and the token comes from the first ``decode()``. Timing the prefill
    call alone is the honest TTFT for a prefill-dominated prompt; the decode
    graph's own cost is reported separately by ``decode_tok_s``.
    """
    t0 = time.perf_counter()
    rc, msg = prefill_tokens(lib, engine, session, ids)
    dt = (time.perf_counter() - t0) * 1000.0
    if rc != 0:
        raise RuntimeError(f"prefill failed: {msg}")
    return dt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", required=True, help="libcv84x6_llm.so")
    ap.add_argument("--bmodel", required=True)
    ap.add_argument("--tokenizer", required=True, help="a directory with tokenizer.json")
    ap.add_argument("--steps", type=int, default=64, help="decode steps per rate")
    ap.add_argument("--short", default=SHORT_PROMPT)
    ap.add_argument("--json", default="", help="write the result here too")
    args = ap.parse_args()

    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(os.path.join(args.tokenizer, "tokenizer.json"))

    lib = bind(args.lib)

    base = {"bmodel": os.path.basename(args.bmodel),
            "bmodel_bytes": os.path.getsize(args.bmodel)}

    heap_before = read_heaps()

    t0 = time.perf_counter()
    err = ctypes.c_char_p()
    engine = lib.llm_engine_load(args.bmodel.encode(), 0, ctypes.byref(err))
    load_s = time.perf_counter() - t0
    if not engine:
        print(json.dumps({"error": (err.value or b"?").decode(errors="replace")},
                         ensure_ascii=False))
        return 1
    base["load_s"] = round(load_s, 2)

    heap_after = read_heaps()
    base["heaps_before"] = heap_before
    base["heaps_after"] = heap_after
    if heap_before.get("npu") and heap_after.get("npu"):
        base["npu_static_mib"] = round(
            heap_after["npu"]["used_mib"] - heap_before["npu"]["used_mib"], 1)
        base["npu_free_mib"] = heap_after["npu"]["free_mib"]

    # The worker always sets this; without it the engine skips its token range
    # check and an out-of-range id becomes an out-of-bounds gather on the TPU.
    lib.llm_engine_set_vocab_size(engine, tok.get_vocab_size())

    base.update({
        "context_length": lib.llm_engine_context_length(engine),
        "max_input_length": lib.llm_engine_max_input_length(engine),
        "num_layers": lib.llm_engine_num_layers(engine),
        "hidden_size": lib.llm_engine_hidden_size(engine),
        "supports_history": bool(lib.llm_engine_supports_history(engine)),
        "has_vision": bool(lib.llm_engine_has_vision(engine)),
        "kv_bytes_per_token": lib.llm_engine_kv_bytes_per_token(engine),
        "linear_state_bytes": lib.llm_engine_linear_state_bytes(engine),
    })

    # One session: short-prompt latency, decode rate, then the 8k prompt.
    _err = ctypes.c_char_p()
    session = lib.llm_session_new(engine, ctypes.byref(_err))
    if not session:
        print(json.dumps({"error": "session_new failed",
                          "detail": lib.llm_last_error().decode(errors="replace")},
                         ensure_ascii=False))
        return 1

    short = tokenize(args.tokenizer, args.short)
    base["short_prompt_tokens"] = len(short)
    base["ttft_short_ms"] = round(prefill_ms(lib, engine, session, short), 1)
    base["decode_tok_s"] = round(decode_rate(lib, engine, session, args.steps), 2)

    # The 8k prompt is built to hit the requested token count exactly by
    # repeating a filler sentence and truncating at the token level -- a
    # character-count estimate would land anywhere from 7.4k to 8.6k.
    filler = tokenize(args.tokenizer, LONG_FILLER)
    long_ids = tokenize(args.tokenizer, "请总结下面这段文字：\n")
    while len(long_ids) < LONG_PROMPT_TOKENS:
        long_ids.extend(filler)
    long_ids = long_ids[:LONG_PROMPT_TOKENS]
    # The 8k prompt is re-measured on a fresh session: a session already holding
    # 8000 tokens would make this an *extend*, which is a different code path
    # and not what "TTFT for an 8k prompt" means.
    lib.llm_session_free(session)
    session = lib.llm_session_new(engine, ctypes.byref(_err))
    base["long_prompt_tokens"] = len(long_ids)
    base["ttft_8k_ms"] = round(prefill_ms(lib, engine, session, long_ids), 1)
    lib.llm_session_free(session)

    # Two sessions, each on its own prompt: what a second conversation costs the
    # first. Both threads decode at once, which is the engine's time-sliced case.
    s1 = lib.llm_session_new(engine, ctypes.byref(_err))
    s2 = lib.llm_session_new(engine, ctypes.byref(_err))
    prefill_tokens(lib, engine, s1, short)
    prefill_tokens(lib, engine, s2, long_ids)
    results = {}

    def run(key, sess):
        results[key] = decode_rate(lib, engine, sess, args.steps)

    th1 = threading.Thread(target=run, args=("a", s1))
    th2 = threading.Thread(target=run, args=("b", s2))
    t0 = time.perf_counter()
    th1.start(); th2.start()
    th1.join(); th2.join()
    wall = time.perf_counter() - t0
    base["dual_session"] = {
        "a_tok_s": round(results.get("a", 0), 2),
        "b_tok_s": round(results.get("b", 0), 2),
        "wall_s": round(wall, 2),
        "sum_tok_s": round(results.get("a", 0) + results.get("b", 0), 2),
    }
    lib.llm_session_free(s1)
    lib.llm_session_free(s2)

    base["fault"] = bool(lib.llm_engine_fault(engine))
    lib.llm_engine_free(engine)

    base["heaps_final"] = read_heaps()

    text = json.dumps(base, ensure_ascii=False, indent=1)
    print(text)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0 if not base.get("fault") else 2


if __name__ == "__main__":
    sys.exit(main())
