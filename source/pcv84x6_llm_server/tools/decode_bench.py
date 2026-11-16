"""Single-stream decode benchmark over the engine's C API, no Python backend.

    ./decode_bench --lib libcv84x6_llm.so --model X_history.bmodel \
        --tokens 9700,11,220,16,13,44,25 --tokens ... --runs 2 [--warmup 1]

Why this exists next to tools/engine_check.py: the question MYS-2377 answers is
"how fast does the engine submit and retire a decode step", and everything in
the HTTP/scheduler/Python layers sits between a measurement and the answer.
This drives llm_session_decode() in a loop and times only that call, so an A/B
of two .so builds differs by engine work alone.

It also prints the generated token ids. Two builds must produce the same ids
for the same input -- the optimisations must not move a single number, and an
argmax-only model makes that an exact check rather than a similarity score.

`--tokens` is the prompt, as token ids (tokenise once with tools/engine_check.py
or the Python backend if you want text; keeping ids out of here means the
benchmark needs nothing on the board but libsophon and the .so).
"""
import argparse
import ctypes
import os
import statistics
import sys
import time


def bind(lib_path):
    lib = ctypes.CDLL(lib_path)
    err = ctypes.POINTER(ctypes.c_char_p)
    lib.llm_engine_load.restype = ctypes.c_void_p
    lib.llm_engine_load.argtypes = [ctypes.c_char_p, ctypes.c_int, err]
    lib.llm_engine_free.argtypes = [ctypes.c_void_p]
    for name in ("num_layers", "context_length", "max_input_length", "hidden_size",
                 "supports_history"):
        fn = getattr(lib, f"llm_engine_{name}")
        fn.restype = ctypes.c_int
        fn.argtypes = [ctypes.c_void_p]
    lib.llm_last_error.restype = ctypes.c_char_p
    lib.llm_session_new.restype = ctypes.c_void_p
    lib.llm_session_new.argtypes = [ctypes.c_void_p, err]
    lib.llm_session_free.argtypes = [ctypes.c_void_p]
    lib.llm_session_token_len.restype = ctypes.c_int
    lib.llm_session_token_len.argtypes = [ctypes.c_void_p]
    lib.llm_session_prefill.restype = ctypes.c_int
    lib.llm_session_prefill.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_void_p,
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, err]
    lib.llm_session_decode.restype = ctypes.c_int
    lib.llm_session_decode.argtypes = [ctypes.c_void_p, ctypes.c_void_p, err]
    return lib


def make_session(lib, eng):
    err = ctypes.c_char_p()
    sess = lib.llm_session_new(eng, ctypes.byref(err))
    if not sess:
        raise SystemExit(f"session_new failed: {err.value}")
    return sess


def prefill(lib, eng, sess, ids):
    err = ctypes.c_char_p()
    arr = (ctypes.c_int * len(ids))(*ids)
    rc = lib.llm_session_prefill(eng, sess, arr, len(ids), None, 0, None, None,
                                 None, None, None, None, ctypes.byref(err))
    if rc != 0:
        raise SystemExit(f"prefill failed: {err.value}")


def decode_run(lib, eng, sess, n):
    """`n` decode calls, returning (token ids, wall seconds)."""
    err = ctypes.c_char_p()
    out = []
    t0 = time.perf_counter()
    for _ in range(n):
        t = lib.llm_session_decode(eng, sess, ctypes.byref(err))
        if t < 0:
            raise SystemExit(f"decode failed after {len(out)} tokens: {err.value}")
        out.append(t)
    return out, time.perf_counter() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--tokens", required=True,
                    help="comma-separated prompt token ids")
    ap.add_argument("--runs", type=int, default=2,
                    help="timed decode rounds in this process (>=2 for an A/B-ready spread)")
    ap.add_argument("--warmup", type=int, default=1, help="untimed decode rounds first")
    ap.add_argument("--decode", type=int, default=64, help="tokens per round")
    ap.add_argument("--dev", type=int, default=0)
    ap.add_argument("--expect", default=None,
                    help="file of token ids from the baseline build; compare and exit 1 on mismatch")
    a = ap.parse_args()

    prompt = [int(x) for x in a.tokens.split(",") if x.strip()]
    lib = bind(a.lib)
    err = ctypes.c_char_p()
    eng = lib.llm_engine_load(a.model.encode(), a.dev, ctypes.byref(err))
    if not eng:
        raise SystemExit(f"load failed: {err.value}")
    print(f"lib={a.lib} layers={lib.llm_engine_num_layers(eng)} "
          f"ctx={lib.llm_engine_context_length(eng)} "
          f"max_input={lib.llm_engine_max_input_length(eng)} "
          f"history={lib.llm_engine_supports_history(eng)} prompt_tokens={len(prompt)}",
          flush=True)

    # One session, prefill once, then decode round after round: a fresh session
    # per round would fold prefill cost and cache warmth into the number.
    sess = make_session(lib, eng)
    try:
        prefill(lib, eng, sess, prompt)
        first, _ = decode_run(lib, eng, sess, 1)  # the token prefill sampled
        print(f"first_token={first[0]} history={lib.llm_session_token_len(sess)}", flush=True)

        ids, secs = [], []
        for r in range(a.warmup + a.runs):
            got, dt = decode_run(lib, eng, sess, a.decode)
            if r < a.warmup:
                print(f"warmup {r + 1}: {a.decode / dt:.2f} tok/s", flush=True)
                continue
            ids, secs = got, secs + [dt]
            print(f"run {r - a.warmup + 1}: {a.decode} tokens in {dt:.3f}s "
                  f"= {a.decode / dt:.2f} tok/s", flush=True)
    finally:
        lib.llm_session_free(sess)
        lib.llm_engine_free(eng)

    tps = [a.decode / s for s in secs]
    mean = statistics.fmean(tps)
    spread = f"{min(tps):.2f}-{max(tps):.2f}" if len(tps) > 1 else f"{tps[0]:.2f}"
    print(f"RESULT decode_tps_mean={mean:.2f} spread={spread} n_runs={len(tps)}", flush=True)
    print("TOKENS " + ",".join(str(t) for t in ids), flush=True)

    if a.expect:
        want = [int(x) for x in open(a.expect).read().replace("TOKENS", "").strip(" ,\n").split(",") if x.strip()]
        if want == ids:
            print(f"MATCH baseline ids ({len(ids)} tokens)")
        else:
            at = next((i for i, (x, y) in enumerate(zip(want, ids)) if x != y),
                      min(len(want), len(ids)))
            print(f"MISMATCH at token {at}: baseline={want[at:at + 8]} new={ids[at:at + 8]}")
            sys.exit(1)


if __name__ == "__main__":
    main()
