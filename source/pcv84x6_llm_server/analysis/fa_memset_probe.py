#!/usr/bin/env python3
"""Attribute a fresh prefill to its memsets: is the 2.50 GiB clear really gone?

MYS-2477 removes the fresh-prefill FA memset, so the interesting question is not
"is the process faster" but "did the 20 x 128 MiB clears disappear, and what
does the remaining time cost". This drives exactly one fresh prefill of `--rows`
rows and prints every bm_memset_device_ext the engine issues for it, plus the
prefill wall time, so the two can be compared against the same run.

    BM_PROF=1 BM_PROF_OUT=/tmp/p.json BM_PROF_CALLS=/tmp/p.csv \
      LD_PRELOAD=./bmprof.so python3 analysis/fa_memset_probe.py \\
        --lib .../libcv84x6_llm.so --model .../x.bmodel --rows 64
"""
from __future__ import annotations

import argparse
import ctypes
import os
import signal
import sys
import time

WATCHDOG_SECS = 600
_P = ctypes.POINTER


def bind(path):
    lib = ctypes.CDLL(path)
    err = _P(ctypes.c_char_p)
    lib.llm_engine_load.restype = ctypes.c_void_p
    lib.llm_engine_load.argtypes = [ctypes.c_char_p, ctypes.c_int, err]
    lib.llm_engine_free.argtypes = [ctypes.c_void_p]
    lib.llm_engine_context_length.restype = ctypes.c_int
    lib.llm_engine_context_length.argtypes = [ctypes.c_void_p]
    lib.llm_session_new.restype = ctypes.c_void_p
    lib.llm_session_new.argtypes = [ctypes.c_void_p, err]
    lib.llm_session_free.argtypes = [ctypes.c_void_p]
    lib.llm_session_prefill.restype = ctypes.c_int
    lib.llm_session_prefill.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p,
        _P(ctypes.c_int), ctypes.c_int, _P(ctypes.c_int),
        ctypes.c_int, _P(ctypes.c_int), _P(ctypes.c_int),
        _P(_P(ctypes.c_float)), _P(_P(ctypes.c_int)), _P(_P(ctypes.c_int)),
        _P(_P(ctypes.c_float)), err]
    return lib


def _alarm(signum, frame):
    sys.stderr.write("[probe] watchdog fired; hard exit\n")
    sys.stderr.flush()
    os._exit(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--rows", type=int, default=64)
    ap.add_argument("--sessions", type=int, default=1,
                    help="how many fresh sessions to prefill (one memset set each)")
    ap.add_argument("--seed", type=int, default=9707)
    a = ap.parse_args()

    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(WATCHDOG_SECS)
    lib = bind(a.lib)
    err = ctypes.c_char_p()
    eng = lib.llm_engine_load(a.model.encode(), 0, ctypes.byref(err))
    if not eng:
        raise SystemExit(f"load: {err.value}")
    ctx = lib.llm_engine_context_length(eng)
    if not 0 < a.rows < ctx:
        raise SystemExit(f"refusing rows={a.rows} (context {ctx})")
    span, base = 4096, a.seed % 1000 + 1000
    ids = (ctypes.c_int * a.rows)(
        *(((base + (i * 2654435761) % span) % 200000) for i in range(a.rows)))
    pos = (ctypes.c_int * (3 * a.rows))()
    for r in range(3):
        for i in range(a.rows):
            pos[r * a.rows + i] = i

    total = 0.0
    for k in range(a.sessions):
        s = lib.llm_session_new(eng, ctypes.byref(err))
        if not s:
            raise SystemExit(f"session_new: {err.value}")
        signal.alarm(WATCHDOG_SECS)
        t0 = time.perf_counter()
        rc = lib.llm_session_prefill(eng, s, ids, a.rows, pos, 0,
                                     None, None, None, None, None, None,
                                     ctypes.byref(err))
        dt = time.perf_counter() - t0
        lib.llm_session_free(s)
        if rc != 0:
            raise SystemExit(f"prefill {k}: {err.value}")
        total += dt
        print(f"session {k + 1}/{a.sessions}: prefill {a.rows} rows = {dt * 1000:.2f} ms",
              flush=True)
    print(f"total {a.sessions} fresh prefills: {total * 1000:.2f} ms "
          f"({total * 1000 / a.sessions:.2f} ms each)", flush=True)
    lib.llm_engine_free(eng)


main()
