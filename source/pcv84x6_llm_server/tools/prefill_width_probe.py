#!/usr/bin/env python3
"""One dynamic prefill launch: width, survival, and what the width buys (MYS-2394).

The engine runs a dynamic prefill graph only at a width that is a multiple of
``LLM_PREFILL_ALIGN`` (64 by default) and replays the rest of the chunk through
the decode graphs, one row per launch, at roughly 30 ms per token
(``native/src/llm_engine.cpp``, ``Session::prefill_impl``). For a follow-up
message shorter than 64 tokens that means *all* of it is replayed, which is the
1-2 s of first token latency a multi-turn conversation pays every turn.

This tool drives one launch of the same C ABI the worker uses
(``native/src/c_api.cpp``) and reports three things for one exact prompt length
and one alignment:

  * did it survive -- ``rc``, and no driver timeout / oops / wedged TPU;
  * how long the prefill (``fresh``) or extend (``extend``) call took, i.e. the
    first-token latency the alignment rule costs;
  * the 16 greedy tokens it produced, so the same length at another alignment
    can be compared token for token against the 64-aligned baseline.

The alignment is *not* an argument: it is read from ``LLM_PREFILL_ALIGN`` so the
number in the output is the one the engine actually used. ``LLM_ALIGN_ABOVE``
must stay 0 (the engine's default); a nonzero value changes which chunks are
aligned at all, so the probe refuses to run with it.

    LLM_PREFILL_ALIGN=1 ./prefill_width_probe.py --lib libcv84x6_llm.so \\
        --model model.bmodel --case fresh \\
        --prompt ../tools/prefill_probe_prompts/fresh-63.txt

Output: one JSON line on stdout, everything else on stderr --
``case, align, prompt_len, history_len, ttft_s, tokens, rc`` (plus ``error``
when ``rc`` is nonzero). Meant to be run as

    timeout 360 ./prefill_width_probe.py ...

so that a launch the in-process watchdog cannot interrupt (a blocking ioctl
runs no Python signal handler) still ends. The watchdog is armed for the load
and re-armed with a full budget once the engine is up, so a slow 20 GB load
does not eat the launch's 300 s. Diagnose an unexpected success
or failure with ``LLM_TRACE=1``: every graph launch is printed with its name
and cost, so ``block_<i>`` / ``block_kv_<i>`` launches are the dynamic prefill
widths and a run of one-row launches is the replay path.

The prompt files are real text encoded by the release package's own tokenizer
and chat template (``gen_prefill_probe_prompts.py``); never hand-written id
lists -- arbitrary id sequences are what made earlier multi-session drivers
time out on this board.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import signal
import sys
import time

# A dynamic prefill that hangs the TPU blocks in the driver for 120 s before it
# errors out, and every later call in the same process fails at once. 300 s
# covers a slow but healthy 2048-token extend with room to spare.
WATCHDOG_SECS = 300
EXIT_WATCHDOG = 3
EXIT_USAGE = 2

_P = ctypes.POINTER


def ids_of(path: str) -> list[int]:
    with open(path, encoding="utf-8") as f:
        return [int(x) for x in f.read().replace("\n", ",").split(",") if x.strip()]


def bind(path: str) -> ctypes.CDLL:
    """The engine's C ABI, with argtypes declared.

    Declaring them is not optional: without ``llm_session_prefill.argtypes``
    ctypes converts the token array to a plain C int, i.e. truncates the
    pointer, and the engine reads the prompt through a garbage address
    (immediate SIGSEGV inside ``Session::prefill_impl``).
    """
    lib = ctypes.CDLL(path)
    err = _P(ctypes.c_char_p)
    lib.llm_engine_load.restype = ctypes.c_void_p
    lib.llm_engine_load.argtypes = [ctypes.c_char_p, ctypes.c_int, err]
    lib.llm_engine_free.argtypes = [ctypes.c_void_p]
    lib.llm_last_error.restype = ctypes.c_char_p
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
    lib.llm_session_decode.restype = ctypes.c_int
    lib.llm_session_decode.argtypes = [ctypes.c_void_p, ctypes.c_void_p, err]
    lib.llm_engine_max_input_length.restype = ctypes.c_int
    lib.llm_engine_max_input_length.argtypes = [ctypes.c_void_p]
    return lib


class Probe:
    def __init__(self, lib: ctypes.CDLL, eng: int):
        self.lib, self.eng = lib, eng
        self.err = ctypes.c_char_p()
        self.session = None

    def open(self) -> None:
        self.session = self.lib.llm_session_new(self.eng, ctypes.byref(self.err))
        if not self.session:
            raise RuntimeError(f"session_new: {self.err.value}")

    def _feed(self, fn, tokens: list[int]) -> float:
        """Run one prefill/extend; return the wall time of the call itself.

        Position ids are left to the engine (plain text: 0..n-1, or absolute
        when extending), and no images are spliced in.
        """
        n = len(tokens)
        arr = (ctypes.c_int * max(n, 1))(*tokens)
        t0 = time.perf_counter()
        rc = fn(self.eng, self.session, arr, n, None, 0, None, None, None,
                None, None, None, ctypes.byref(self.err))
        secs = time.perf_counter() - t0
        if rc != 0:
            raise RuntimeError(f"{self.err.value} (rc={rc})")
        return secs

    def prefill(self, tokens: list[int]) -> float:
        return self._feed(self.lib.llm_session_prefill, tokens)

    def extend(self, tokens: list[int]) -> float:
        return self._feed(self.lib.llm_session_extend, tokens)

    def decode(self) -> int:
        tok = self.lib.llm_session_decode(self.eng, self.session,
                                          ctypes.byref(self.err))
        if tok < 0:
            raise RuntimeError(f"decode: {self.err.value}")
        return int(tok)

    def token_len(self) -> int:
        return self.lib.llm_session_token_len(self.session)

    def close(self) -> None:
        if self.session:
            self.lib.llm_session_free(self.session)
            self.session = None


def align_of_env() -> int:
    raw = os.environ.get("LLM_PREFILL_ALIGN", "64").strip() or "64"
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"LLM_PREFILL_ALIGN={raw!r} is not an integer")


def run(a) -> dict:
    align = align_of_env()
    above = os.environ.get("LLM_ALIGN_ABOVE", "0").strip() or "0"
    if above not in ("0",):
        raise SystemExit(
            f"LLM_ALIGN_ABOVE={above} is set: chunks of that size or smaller are "
            "never aligned, so the width this probe reports is not the one the "
            "engine used (the engine's rule assumes 0)")
    prompt = ids_of(a.prompt)
    history = ids_of(a.history) if a.history else []
    if a.case == "extend" and not history:
        raise SystemExit("--case extend needs --history")
    if a.case == "fresh" and history:
        raise SystemExit("--case fresh takes no --history")

    out = {"case": a.case, "align": align, "prompt_len": len(prompt),
           "history_len": len(history), "ttft_s": None, "tokens": [], "rc": 0}
    lib = bind(a.lib)
    err = ctypes.c_char_p()
    t = time.perf_counter()
    eng = lib.llm_engine_load(a.model.encode(), a.dev, ctypes.byref(err))
    if not eng:
        out["rc"] = 1
        out["error"] = f"load: {err.value}"
        return out
    print(f"load {time.perf_counter() - t:.2f}s max_input="
          f"{lib.llm_engine_max_input_length(eng)}", file=sys.stderr, flush=True)

    p = Probe(lib, eng)
    try:
        # The load reads a 20 GB bmodel off the eMMC, so the launch gets its own
        # full watchdog budget rather than whatever is left of the load's.
        signal.alarm(WATCHDOG_SECS)
        p.open()
        if a.case == "fresh":
            out["ttft_s"] = p.prefill(prompt)
        else:
            p.prefill(history)
            p.decode()  # the token that prefill sampled; appends it to the state
            out["ttft_s"] = p.extend(prompt)
        out["tokens"] = [p.decode() for _ in range(a.decode)]
        print(f"session tokens={p.token_len()}", file=sys.stderr, flush=True)
    except RuntimeError as exc:
        out["rc"] = 1
        out["error"] = str(exc)
    finally:
        p.close()
        lib.llm_engine_free(eng)
    out["ttft_s"] = None if out["ttft_s"] is None else round(out["ttft_s"], 4)
    return out


def emit(out: dict) -> None:
    print(json.dumps(out, ensure_ascii=False), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="One dynamic prefill launch: width, survival, TTFT.")
    ap.add_argument("--lib", required=True, help="path to libcv84x6_llm.so")
    ap.add_argument("--model", required=True, help="path to the .bmodel")
    ap.add_argument("--case", choices=("fresh", "extend"), required=True,
                    help="fresh = prefill a whole prompt (no history, FA runs "
                         "block_<i>); extend = prefill a history, decode one "
                         "token, then extend (FA runs block_kv_<i>)")
    ap.add_argument("--prompt", required=True, help="file of comma-separated ids")
    ap.add_argument("--history", default=None,
                    help="file of comma-separated ids, extend only")
    ap.add_argument("--decode", type=int, default=16,
                    help="greedy tokens to decode after the launch (default 16)")
    ap.add_argument("--dev", type=int, default=0)
    a = ap.parse_args()

    partial: dict = {}

    def watchdog(_sig, _frm):
        out = partial or {"case": a.case, "align": align_of_env(), "ttft_s": None,
                          "tokens": [], "rc": EXIT_WATCHDOG}
        out["rc"] = EXIT_WATCHDOG
        out["error"] = f"watchdog: no return from the {a.case} launch in " \
                       f"{WATCHDOG_SECS}s"
        emit(out)
        # _exit, not exit: the launch is still inside libbmrt and unwinding
        # Python state would take the interpreter down through a C frame.
        os._exit(EXIT_WATCHDOG)

    signal.signal(signal.SIGALRM, watchdog)
    signal.alarm(WATCHDOG_SECS)
    try:
        partial = run(a)
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - reported, not raised
        partial = {"case": a.case, "align": align_of_env(),
                   "prompt_len": len(ids_of(a.prompt)),
                   "history_len": len(ids_of(a.history)) if a.history else 0,
                   "ttft_s": None, "tokens": [], "rc": 1, "error": repr(exc)}
    signal.alarm(0)
    emit(partial)
    return 0 if partial.get("rc") == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
