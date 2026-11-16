#!/usr/bin/env python3
"""Prefill cost vs row count: does one prefilled row cost the same at every width?

MYS-2474 asks which layer of the stack still has lossless headroom. Decode is
already pinned to the memory roofline (docs/research/decode-optimization.md and
the number this branch re-measured: 33.19 ms/token against a 30.68 ms weight-read
floor). Prefill was never measured the same way, even though it dominates the
product: the ledger records 16k cold prefill at ~100 s, 62k at ~13 min, 127k at
~46 min, against ~24 tok/s of decode.

The dynamic prefill graphs are compiled with ``max_input`` rows (2048 here), so a
prompt is fed as chunks of at most that width. Whether the *time per row* is flat
in the row count decides where to look next:

  * ms/row roughly constant  -> the graph is compute/weight bound at that width
    and only a bmodel change can move it;
  * ms/row falling with width -> fixed per-launch cost dominates the narrow
    chunks, so feeding wider chunks (a larger ``max_input``) is worth a
    recompile;
  * ms/row rising with width -> attention over the chunk is dominating, which is
    the O(L^2) prefill-mask path and a different fix.

Everything is measured through the shipped C ABI with one engine load, so the
numbers include the engine's own per-chunk bookkeeping (embedding, image splice,
KV d2d) and not just the graph.

    LLM_TRACE=0 timeout 1800 python3 analysis/prefill_scaling.py \\
        --lib /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \\
        --model <128k bmodel> --rows 64,128,256,512,1024,2048 --repeat 3

A second mode (``--tail``) prefills the same total length but as ``--tail``
separate extend calls instead of one chunk, which is how a multi-turn
conversation actually grows a session. Comparing the two separates "cost per
row at width L" from "cost of starting a new chunk".
"""
from __future__ import annotations

import argparse
import ctypes
import os
import signal
import statistics
import sys
import time

# A launch that wedges the TPU never runs a Python signal handler, so an
# in-process alarm cannot rescue it: os._exit is the only thing that fires.
# Same rule as the other board probes (analysis/README.md).
WATCHDOG_SECS = 600
EXIT_WATCHDOG = 3

_P = ctypes.POINTER


def bind(path):
    lib = ctypes.CDLL(path)
    err = _P(ctypes.c_char_p)
    lib.llm_engine_load.restype = ctypes.c_void_p
    lib.llm_engine_load.argtypes = [ctypes.c_char_p, ctypes.c_int, err]
    lib.llm_engine_free.argtypes = [ctypes.c_void_p]
    lib.llm_last_error.restype = ctypes.c_char_p
    lib.llm_engine_max_input_length.restype = ctypes.c_int
    lib.llm_engine_max_input_length.argtypes = [ctypes.c_void_p]
    lib.llm_engine_context_length.restype = ctypes.c_int
    lib.llm_engine_context_length.argtypes = [ctypes.c_void_p]
    lib.llm_session_new.restype = ctypes.c_void_p
    lib.llm_session_new.argtypes = [ctypes.c_void_p, err]
    lib.llm_session_free.argtypes = [ctypes.c_void_p]
    lib.llm_session_token_len.restype = ctypes.c_int
    lib.llm_session_token_len.argtypes = [ctypes.c_void_p]
    lib.llm_session_prefill.restype = ctypes.c_int
    lib.llm_session_prefill.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p,
        _P(ctypes.c_int), ctypes.c_int, _P(ctypes.c_int),
        ctypes.c_int, _P(ctypes.c_int), _P(ctypes.c_int),
        _P(_P(ctypes.c_float)), _P(_P(ctypes.c_int)), _P(_P(ctypes.c_int)),
        _P(_P(ctypes.c_float)), err]
    lib.llm_session_extend.argtypes = lib.llm_session_prefill.argtypes
    lib.llm_session_extend.restype = ctypes.c_int
    return lib


def watchdog_rearm(secs=WATCHDOG_SECS):
    signal.alarm(0)
    signal.alarm(secs)


def _alarm(signum, frame):
    sys.stderr.write(f"[probe] watchdog fired after {WATCHDOG_SECS}s; hard exit\n")
    sys.stderr.flush()
    os._exit(EXIT_WATCHDOG)


def fill_safe(token_id, n):
    """A prompt that cannot wedge the KV index, and does not collapse routing.

    Two constraints, both learned the expensive way:

    * The FA graphs index their history buffers with the positions they are
      handed; this probe hands positions 0..n-1 with a zeroed state, so every
      index is in range.
    * A single repeated token drives every row to the same 8 experts, which
      makes the MoE weight traffic artificially *low* and would flatter the
      numbers. So the sequence walks a wide, deterministic spread of ordinary
      text ids instead (``token_id`` seeds it). It is still the same sequence at
      every width, which is what the scaling comparison needs.
    """
    span = 4096
    base = token_id % 1000 + 1000
    return (ctypes.c_int * n)(*((base + (i * 2654435761) % span) % 200000
                                for i in range(n)))


def prefilled_weight_bytes(rows):
    """Weights a prefill of `rows` rows must read, from the bmodel's own layout.

    Unlike decode, prefill is *not* expert-sparse per token: each of the `rows`
    rows routes to its own 8 of 256 experts, so by ~256 rows essentially every
    expert is touched and the layer is read in full. That is why prefill cost is
    dominated by weight streaming and scales sub-linearly in ms/row.

    Numbers are the bmodel's per-layer weights (model_tool --weight, 128k
    bmodel): 418.8 MiB per linear layer, 431.4 MiB per FA layer, of which
    3 x 128 MiB is the routed-expert stack. Only the experts actually reachable
    by `rows` rows are counted, 256 * (1 - (1 - 1/256)^(8*rows)).
    """
    expert = 134_217_728
    lin_dense = 439_123_968 - 3 * expert
    fa_dense = 452_407_296 - 3 * expert
    touched = 256 * (1 - (1 - 1 / 256) ** (8 * rows))
    routed = 3 * expert * touched / 256
    return 30 * (lin_dense + routed) + 10 * (fa_dense + routed)


def run_prefill(lib, eng, ids, n, dev_pos, ctx):
    """One prefill of n ids; returns (seconds, error, token_len_after).

    `n` is checked against the context window before the call. That check is
    not decoration: the engine trusts it, and a bogus row count makes the FA
    graph index past its history buffer, which on CV84X6 does not raise -- it
    wedges the TPU until the board is rebooted (see analysis/README.md). The
    caller's ids are int32, so a mis-ordered call site is exactly how that
    happens.
    """
    if not isinstance(n, int) or not 0 < n < ctx:
        raise SystemExit(f"refusing prefill of n={n!r} rows (context={ctx})")
    err = ctypes.c_char_p()  # must outlive every call: the engine writes through it
    s = lib.llm_session_new(eng, ctypes.byref(err))
    if not s:
        raise SystemExit(f"session_new: {err.value}")
    try:
        pos = (ctypes.c_int * (3 * n))()
        for r in range(3):
            for i in range(n):
                pos[r * n + i] = dev_pos + i
        t0 = time.perf_counter()
        rc = lib.llm_session_prefill(
            eng, s, ids, n, pos,
            0,                                        # n_images
            None, None, None, None, None, None,       # per-image arrays
            ctypes.byref(err))
        dt = time.perf_counter() - t0
        if rc != 0:
            return None, str(err.value), lib.llm_session_token_len(s)
        return dt, None, lib.llm_session_token_len(s)
    finally:
        lib.llm_session_free(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--dev", type=int, default=0)
    ap.add_argument("--rows", default="64,128,256,512,1024,2048")
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--token-id", type=int, default=9707,
                    help="a plain text token id; the prompt is this repeated")
    ap.add_argument("--total", type=int, default=2048,
                    help="--tail mode: total rows to reach, grown in pieces")
    ap.add_argument("--tail", type=int, default=0,
                    help="--tail mode piece size (0 = disabled)")
    ap.add_argument("--dev-pos", type=int, default=0)
    a = ap.parse_args()

    signal.signal(signal.SIGALRM, _alarm)
    lib = bind(a.lib)
    err = ctypes.c_char_p()
    eng = lib.llm_engine_load(a.model.encode(), a.dev, ctypes.byref(err))
    if not eng:
        raise SystemExit(f"load: {err.value}")
    max_input = lib.llm_engine_max_input_length(eng)
    ctx = lib.llm_engine_context_length(eng)
    print(f"engine: max_input={max_input} context={ctx}", flush=True)

    try:
        if a.tail:
            return run_tail(lib, eng, a, ctx)
        rows = [int(x) for x in a.rows.split(",") if x.strip()]
        print(f"{'rows':>6} {'chunks':>7} {'ms':>10} {'ms/row':>9} {'rows/s':>9}"
              f" {'GiB wts':>8} {'eff GB/s':>9}", flush=True)
        for n in rows:
            n = min(n, ctx - 1)
            ids = fill_safe(a.token_id, n)
            samples = []
            for _ in range(a.repeat):
                watchdog_rearm()
                dt, e, tl = run_prefill(lib, eng, ids, n, a.dev_pos, ctx)
                if dt is None:
                    print(f"{n:>6}  FAILED (token_len={tl}): {e}", flush=True)
                    break
                samples.append(dt)
            if not samples:
                continue
            med = statistics.median(samples)
            ms = med * 1e3
            chunks = -(-n // max_input)
            wts = prefilled_weight_bytes(n)
            print(f"{n:>6} {chunks:>7} {ms:>10.1f} {ms / n:>9.3f}"
                  f" {n / med:>9.1f} {wts / 2**30:>8.2f}"
                  f" {wts / med / 1e9:>9.1f}", flush=True)
    finally:
        lib.llm_engine_free(eng)


def run_tail(lib, eng, a, ctx):
    """Grow one session to --total rows as --tail separate extend calls."""
    err = ctypes.c_char_p()
    s = lib.llm_session_new(eng, ctypes.byref(err))
    if not s:
        raise SystemExit(f"session_new: {err.value}")
    try:
        done = 0
        print(f"{'call':>5} {'rows':>6} {'cum':>7} {'ms':>10} {'ms/row':>9}", flush=True)
        call = 0
        while done < a.total:
            n = min(a.tail, a.total - done)
            if not isinstance(n, int) or not 0 < n < ctx:
                raise SystemExit(f"refusing extend of n={n!r} rows (context={ctx})")
            ids = fill_safe(a.token_id, n)
            pos = (ctypes.c_int * (3 * n))()
            for r in range(3):
                for i in range(n):
                    pos[r * n + i] = a.dev_pos + done + i
            watchdog_rearm()
            t0 = time.perf_counter()
            fn = lib.llm_session_prefill if done == 0 else lib.llm_session_extend
            rc = fn(eng, s, ids, n, pos, 0, None, None, None, None, None, None,
                    None, ctypes.byref(err))
            dt = time.perf_counter() - t0
            if rc != 0:
                print(f"  extend failed at cum={done}: {err.value}", flush=True)
                return 1
            done += n
            call += 1
            print(f"{call:>5} {n:>6} {done:>7} {dt * 1e3:>10.1f}"
                  f" {dt * 1e3 / n:>9.3f}", flush=True)
        return 0
    finally:
        lib.llm_session_free(s)


if __name__ == "__main__":
    raise SystemExit(main() or 0)
