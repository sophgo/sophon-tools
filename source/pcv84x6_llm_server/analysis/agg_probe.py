"""Aggregate decode throughput for N concurrent sessions on one engine.

    ./agg_probe.py --lib X.so --model Y.bmodel --prompt-a idlist.txt \
        --sessions 3 --decode 32

The scheduler's whole design (app/scheduler.py's docstring: "a single decode
step is ~45 ms of NPU work and the NPU is only 6-7% busy", round-robin so N
clients stream at once) rests on the NPU having headroom. This measures the
thing that premise is about: with one engine and k sessions advanced strictly
round-robin, does aggregate tok/s rise with k, stay flat, or fall?

  * aggregate rises with k  -> the TPU is idle between steps; batching /
    interleaving genuinely buys throughput.
  * aggregate flat in k     -> the TPU is saturated; concurrency only shares a
    fixed budget and the "headroom" premise is wrong.
  * aggregate falls with k  -> interleaving costs state swaps (each decode parks
    the other sessions' FA KV + linear state), which is a real per-step tax.

Reports per-session tok/s and the aggregate, plus the wall time per step, so the
difference between "the NPU is busy" and "the host is busy" is visible.

Sessions are created after one prefill each, exactly like the scheduler does,
and every session decodes `--decode` tokens. Exits non-zero if the tokens of
session 0 differ from its solo run (interleaving must not change a number).
"""
import argparse
import ctypes
import statistics
import sys
import time

_ERR = ctypes.POINTER(ctypes.c_char_p)


def bind(path):
    lib = ctypes.CDLL(path)
    lib.llm_engine_load.restype = ctypes.c_void_p
    lib.llm_engine_load.argtypes = [ctypes.c_char_p, ctypes.c_int, _ERR]
    lib.llm_engine_free.argtypes = [ctypes.c_void_p]
    lib.llm_last_error.restype = ctypes.c_char_p
    lib.llm_session_new.restype = ctypes.c_void_p
    lib.llm_session_new.argtypes = [ctypes.c_void_p, _ERR]
    lib.llm_session_free.argtypes = [ctypes.c_void_p]
    lib.llm_session_token_len.restype = ctypes.c_int
    lib.llm_session_token_len.argtypes = [ctypes.c_void_p]
    lib.llm_session_decode.restype = ctypes.c_int
    lib.llm_session_decode.argtypes = [ctypes.c_void_p, ctypes.c_void_p, _ERR]
    lib.llm_session_prefill.restype = ctypes.c_int
    lib.llm_session_prefill.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.c_int,
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, _ERR]
    return lib


def ids_of(path):
    return [int(x) for x in open(path).read().replace("\n", "").split(",") if x.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--prompt", required=True, help="file of comma-separated ids")
    ap.add_argument("--sessions", type=int, default=1)
    ap.add_argument("--decode", type=int, default=32)
    ap.add_argument("--dev", type=int, default=0)
    ap.add_argument("--quantum", type=int, default=1,
                    help="tokens each session runs before handing the TPU on; 1 is "
                         "the worker's current round-robin, larger values amortise the "
                         "per-switch state copy")
    a = ap.parse_args()

    prompt = ids_of(a.prompt)
    lib = bind(a.lib)
    err = ctypes.c_char_p()
    eng = lib.llm_engine_load(a.model.encode(), a.dev, ctypes.byref(err))
    if not eng:
        raise SystemExit(f"load: {err.value}")

    def new_sess():
        h = lib.llm_session_new(eng, ctypes.byref(err))
        if not h:
            raise SystemExit(f"session_new: {err.value}")
        arr = (ctypes.c_int * len(prompt))(*prompt)
        rc = lib.llm_session_prefill(eng, h, arr, len(prompt), None, 0, None, None,
                                     None, None, None, None, ctypes.byref(err))
        if rc != 0:
            raise SystemExit(f"prefill: {err.value}")
        return h

    def step(h):
        t = lib.llm_session_decode(eng, h, ctypes.byref(err))
        if t < 0:
            raise SystemExit(f"decode: {err.value}")
        return t

    try:
        # Solo reference: one session, decode alone.
        h = new_sess()
        first = step(h)  # the token prefill sampled, no NPU work
        t0 = time.perf_counter()
        solo = [step(h) for _ in range(a.decode)]
        solo_dt = time.perf_counter() - t0
        lib.llm_session_free(h)
        solo_tps = a.decode / solo_dt
        print(f"solo        1 session  {a.decode} tok in {solo_dt:.3f}s = {solo_tps:.2f} tok/s",
              flush=True)

        if a.sessions <= 1:
            return 0

        # Interleaved: k sessions, `quantum` steps each per visit. quantum=1 is the
        # worker's current round-robin (a full park/unpark of both sessions'
        # linear state on every single token); larger values amortise that copy.
        hs = [new_sess() for _ in range(a.sessions)]
        for h in hs:
            step(h)  # each session's pending hand-back
        outs = [[] for _ in hs]
        t0 = time.perf_counter()
        done = 0
        while done < a.decode:
            n = min(a.quantum, a.decode - done)
            for i, h in enumerate(hs):
                outs[i].extend(step(h) for _ in range(n))
            done += n
        dt = time.perf_counter() - t0
        total = a.decode * a.sessions
        agg = total / dt
        print(f"interleaved {a.sessions} sessions (quantum {a.quantum})  {total} tok in {dt:.3f}s = {agg:.2f} tok/s "
              f"aggregate, {agg / a.sessions:.2f} tok/s each", flush=True)
        print(f"  vs solo: aggregate x{agg / solo_tps:.2f}, per-session x"
              f"{(agg / a.sessions) / solo_tps:.2f}", flush=True)
        ok = outs[0] == solo
        if not ok:
            at = next((i for i, (x, y) in enumerate(zip(outs[0], solo)) if x != y),
                      min(len(outs[0]), len(solo)))
            print(f"  TOKENS DIFFER from solo at {at}: {outs[0][at:at + 6]} vs {solo[at:at + 6]}")
        else:
            print(f"  session 0 tokens identical to solo ({len(solo)} tokens)")
        for h in hs:
            lib.llm_session_free(h)
        return 0 if ok else 1
    finally:
        lib.llm_engine_free(eng)


if __name__ == "__main__":
    sys.exit(main())
