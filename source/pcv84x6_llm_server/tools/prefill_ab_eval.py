#!/usr/bin/env python3
"""Answer-accuracy A/B: prefill alignment 64 (current rule) vs 16 (candidate).

MYS-2394 measured what widening the dynamic prefill buys (first-token latency)
and what it costs (the 16 greedy tokens diverge as soon as the set of rows
replayed through the exact decode graphs changes). Divergence is not the same
thing as a worse answer, so this tool asks the question the decision actually
turns on: **does the answer change, and does it get worse?**

It loads the model once, then runs 40 graded cases in order, each in its own
session, and grades the text the model produced against the case's pattern.
The alignment is not an argument -- it is read from ``LLM_PREFILL_ALIGN`` and
written into the report, so the number reported is the one the engine used.
``LLM_ALIGN_ABOVE`` must stay 0 (the engine's default), as in the probe.

    LLM_PREFILL_ALIGN=16 timeout 3600 python3 tools/prefill_ab_eval.py \\
        --lib /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \\
        --model /data/cv84x6_llm_server/models/qwen3.6-35b-32k/model.bmodel \\
        --cases tools/prefill_ab_cases/cases.json --out logs/align-16.json --dev 0

Each case records ``id, type, n_prompt, n_delta, ttft_s, text, tokens, pass``.
``ttft_s`` is the prefill call for an A/B case and the extend call for a C case
(the follow-up is what a user waits on); a C case additionally records
``prefill_s`` for its history. ``n_prompt`` is every token fed in the case, so
for C it is history + follow-up, and ``n_delta`` is the follow-up chunk.

``--exact-tail K`` (default 0, i.e. the engine's own behaviour) asks the engine
to replay the last K rows of the *last* prefill/extend call through the exact
decode graphs (``llm_session_set_exact_tail``, one call only). For a C case it
is set before the follow-up extend, never before the history prefill, matching
where the product puts it (``app/engine/scheduler.py``). The value is written
into the report so a run can never be mislabelled.

The in-process watchdog is re-armed per case with a full 300 s budget and
``os._exit(3)`` on expiry, because a launch that wedges the TPU blocks in the
driver for 120 s and runs no Python signal handler until it returns. Run the
whole thing under ``timeout 3600`` as well.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import signal
import statistics
import sys
import time

WATCHDOG_SECS = 300          # per case, re-armed before each one
EXIT_WATCHDOG = 3
MAX_DECODE = 64              # greedy tokens per case (the card's budget)
DEFAULT_TOKENIZER = "/opt/sophgo/cv84x6_llm_server/model-config/qwen3_5/tokenizer.json"

_P = ctypes.POINTER


# --------------------------------------------------------------------------
# The engine's C ABI (same binding as tools/prefill_width_probe.py)
# --------------------------------------------------------------------------
def bind(path: str) -> ctypes.CDLL:
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
    lib.llm_session_set_exact_tail.restype = None
    lib.llm_session_set_exact_tail.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.llm_engine_max_input_length.restype = ctypes.c_int
    lib.llm_engine_max_input_length.argtypes = [ctypes.c_void_p]
    return lib


def bind_tokenizer(path: str) -> ctypes.CDLL:
    lib = ctypes.CDLL(path)
    err = _P(ctypes.c_char_p)
    lib.llm_tokenizer_load.restype = ctypes.c_void_p
    lib.llm_tokenizer_load.argtypes = [ctypes.c_char_p, err]
    lib.llm_tokenizer_free.argtypes = [ctypes.c_void_p]
    lib.llm_tokenizer_decode.restype = ctypes.c_int
    lib.llm_tokenizer_decode.argtypes = [ctypes.c_void_p, _P(ctypes.c_int), ctypes.c_int,
                                         ctypes.c_char_p, ctypes.c_int, ctypes.c_int, err]
    lib.llm_tokenizer_token_to_id.restype = ctypes.c_int
    lib.llm_tokenizer_token_to_id.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    return lib


class Tokenizer:
    def __init__(self, lib: ctypes.CDLL, path: str):
        self.lib = lib
        self.err = ctypes.c_char_p()
        self.h = lib.llm_tokenizer_load(path.encode(), ctypes.byref(self.err))
        if not self.h:
            raise SystemExit(f"tokenizer_load: {self.err.value}")

    def decode(self, ids: list[int], skip_special: bool = True) -> str:
        n = len(ids)
        arr = (ctypes.c_int * max(n, 1))(*ids)
        need = self.lib.llm_tokenizer_decode(self.h, arr, n, None, 0,
                                            1 if skip_special else 0,
                                            ctypes.byref(self.err))
        if need < 0:
            raise RuntimeError(f"decode: {self.err.value}")
        buf = ctypes.create_string_buffer(need + 1)
        got = self.lib.llm_tokenizer_decode(self.h, arr, n, buf, need + 1,
                                            1 if skip_special else 0,
                                            ctypes.byref(self.err))
        if got < 0:
            raise RuntimeError(f"decode: {self.err.value}")
        return buf.value.decode("utf-8", "replace")

    def stop_ids(self, names: list[str]) -> set[int]:
        out = set()
        for name in names:
            i = self.lib.llm_tokenizer_token_to_id(self.h, name.encode())
            if i >= 0:
                out.add(int(i))
        return out

    def close(self) -> None:
        if self.h:
            self.lib.llm_tokenizer_free(self.h)
            self.h = None


class Session:
    """One engine session per case: new, fed, decoded, freed."""

    def __init__(self, lib: ctypes.CDLL, eng: int):
        self.lib, self.eng = lib, eng
        self.err = ctypes.c_char_p()
        self.h = lib.llm_session_new(eng, ctypes.byref(self.err))
        if not self.h:
            raise RuntimeError(f"session_new: {self.err.value}")

    def _feed(self, fn, tokens: list[int]) -> float:
        n = len(tokens)
        arr = (ctypes.c_int * max(n, 1))(*tokens)
        t0 = time.perf_counter()
        rc = fn(self.eng, self.h, arr, n, None, 0, None, None, None,
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
        tok = self.lib.llm_session_decode(self.eng, self.h, ctypes.byref(self.err))
        if tok < 0:
            raise RuntimeError(f"decode: {self.err.value}")
        return int(tok)

    def set_exact_tail(self, rows: int) -> None:
        """Replay the last `rows` rows of the *next* feed through the decode
        graphs. The engine clears it after that call, so this is per-call."""
        self.lib.llm_session_set_exact_tail(self.h, rows)

    def close(self) -> None:
        if self.h:
            self.lib.llm_session_free(self.h)
            self.h = None


# --------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------
def ids_of(cases_dir: str, name: str) -> list[int]:
    with open(os.path.join(cases_dir, name), encoding="utf-8") as f:
        return [int(x) for x in f.read().replace("\n", ",").split(",") if x.strip()]


def load_cases(path: str) -> tuple[dict, list[dict]]:
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    return doc, doc["cases"]


def case_inputs(case: dict, cases_dir: str) -> tuple[list[int], list[int] | None]:
    """(prompt ids, follow-up ids or None) for one case."""
    if case["type"] == "C":
        return (ids_of(cases_dir, case["history_ids_file"]),
                ids_of(cases_dir, case["delta_ids_file"]))
    return ids_of(cases_dir, case["ids_file"]), None


def run_case(lib, tok, eng, case: dict, cases_dir: str,
             stop_ids: set[int], exact_tail: int = 0) -> dict:
    prompt, delta = case_inputs(case, cases_dir)
    out = {"id": case["id"], "type": case["type"],
           "n_prompt": len(prompt) + (len(delta) if delta else 0),
           "n_delta": len(delta) if delta else 0,
           "ttft_s": None, "prefill_s": None, "text": "", "tokens": [],
           "pass": False, "rc": 0}
    s = Session(lib, eng)
    try:
        if delta is not None:
            out["prefill_s"] = round(s.prefill(prompt), 4)
            # The token the history prefill sampled: it closes the assistant
            # turn the history ends at, and the state has to hold it before the
            # follow-up chunk can be extended onto it.
            s.decode()
            # Per-call: the engine clears it after this feed, so the history
            # prefill above is untouched even if the request asked for a tail.
            if exact_tail:
                s.set_exact_tail(exact_tail)
            out["ttft_s"] = round(s.extend(delta), 4)
        else:
            if exact_tail:
                s.set_exact_tail(exact_tail)
            out["ttft_s"] = round(s.prefill(prompt), 4)
        produced: list[int] = []
        for _ in range(MAX_DECODE):
            t = s.decode()
            if t in stop_ids:
                break
            produced.append(t)
        out["tokens"] = produced
        out["text"] = tok.decode(produced)
        out["pass"] = bool(re.search(case["match"], out["text"], re.IGNORECASE))
    except RuntimeError as exc:
        out["rc"] = 1
        out["error"] = str(exc)
    finally:
        s.close()
    return out


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def median(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 4) if values else None


def summarise(results: list[dict]) -> dict:
    summary: dict = {"overall": {}, "by_type": {}}
    for kind in ("A", "B", "C"):
        rows = [r for r in results if r["type"] == kind]
        if not rows:
            continue
        summary["by_type"][kind] = {
            "cases": len(rows),
            "passed": sum(1 for r in rows if r["pass"]),
            "ttft_median_s": median([r["ttft_s"] for r in rows]),
        }
    summary["overall"] = {
        "cases": len(results),
        "passed": sum(1 for r in results if r["pass"]),
        "ttft_median_s": median([r["ttft_s"] for r in results]),
        "failures": [r["id"] for r in results if not r["pass"]],
        "errors": [r["id"] for r in results if r.get("rc")],
    }
    return summary


def md5_of(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Graded answer A/B for the prefill alignment rule.")
    ap.add_argument("--lib", required=True, help="path to libcv84x6_llm.so")
    ap.add_argument("--model", required=True, help="path to the .bmodel")
    ap.add_argument("--cases", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "prefill_ab_cases", "cases.json"),
        help="path to cases.json")
    ap.add_argument("--out", required=True, help="where to write the JSON report")
    ap.add_argument("--tokenizer", default=DEFAULT_TOKENIZER,
                    help="tokenizer.json for detokenising the answer (default: the "
                         "installed package's)")
    ap.add_argument("--only", default="",
                    help="comma-separated case ids to run (debugging a few cases "
                         "without paying for the whole set); default all 40")
    ap.add_argument("--exact-tail", type=int, default=0, metavar="K",
                    help="replay the last K rows of the graded prefill/extend call "
                         "through the exact decode graphs (default 0: the engine's "
                         "own rule). For C this applies to the follow-up extend only, "
                         "never to the history prefill")
    ap.add_argument("--dev", type=int, default=0)
    a = ap.parse_args()
    if a.exact_tail < 0:
        ap.error("--exact-tail must be >= 0")

    align = int(os.environ.get("LLM_PREFILL_ALIGN", "64").strip() or "64")
    above = os.environ.get("LLM_ALIGN_ABOVE", "0").strip() or "0"
    if above != "0":
        raise SystemExit(f"LLM_ALIGN_ABOVE={above} is set; the engine's rule assumes 0, "
                         f"so the width reported would not be the one used")
    cases_dir = os.path.dirname(os.path.abspath(a.cases))
    _, cases = load_cases(a.cases)
    if a.only:
        wanted = [x.strip() for x in a.only.split(",") if x.strip()]
        known = {c["id"] for c in cases}
        missing = [x for x in wanted if x not in known]
        if missing:
            raise SystemExit(f"unknown case ids: {missing}")
        cases = [c for c in cases if c["id"] in wanted]

    lib = bind(a.lib)
    toklib = bind_tokenizer(a.lib)
    tok = Tokenizer(toklib, a.tokenizer)
    stop_ids = tok.stop_ids(["<|im_end|>", "<|endoftext|>"])
    if not stop_ids:
        raise SystemExit("tokenizer has no <|im_end|>: cannot tell where an answer ends")

    doc: dict = {"align": align, "exact_tail": a.exact_tail,
                 "device": os.uname().nodename, "dev": a.dev,
                 "lib": a.lib, "lib_md5": md5_of(a.lib),
                 "model": a.model, "model_md5": md5_of(a.model),
                 "cases_file": a.cases, "max_decode": MAX_DECODE,
                 "stop_ids": sorted(stop_ids), "cases": [], "summary": {}}
    results = doc["cases"]

    def dump() -> None:
        doc["summary"] = summarise(results)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")

    def watchdog(_sig, _frm):
        doc["error"] = f"watchdog: no return from case " \
                       f"{cases[len(results)].get('id') if len(results) < len(cases) else '?'} " \
                       f"in {WATCHDOG_SECS}s"
        try:
            dump()
        finally:
            # _exit, not exit: the launch is still inside libbmrt and unwinding
            # Python state would take the interpreter down through a C frame.
            os._exit(EXIT_WATCHDOG)

    signal.signal(signal.SIGALRM, watchdog)

    t = time.perf_counter()
    err = ctypes.c_char_p()
    eng = lib.llm_engine_load(a.model.encode(), a.dev, ctypes.byref(err))
    if not eng:
        raise SystemExit(f"engine load failed: {err.value}")
    print(f"load {time.perf_counter() - t:.1f}s align={align} "
          f"exact_tail={a.exact_tail} "
          f"max_input={lib.llm_engine_max_input_length(eng)}", file=sys.stderr, flush=True)

    try:
        for i, case in enumerate(cases):
            signal.alarm(WATCHDOG_SECS)
            r = run_case(lib, tok, eng, case, cases_dir, stop_ids, a.exact_tail)
            signal.alarm(0)
            results.append(r)
            suffix = "+%d" % r["n_delta"] if r["n_delta"] else ""
            print(f"[{i + 1}/{len(cases)}] {r['id']} {r['type']} "
                  f"n={r['n_prompt']}{suffix} "
                  f"ttft={r['ttft_s']}s rc={r['rc']} "
                  f"{'PASS' if r['pass'] else 'FAIL'} {r['text'][:60]!r}",
                  file=sys.stderr, flush=True)
            dump()
    finally:
        signal.alarm(0)
        tok.close()
        lib.llm_engine_free(eng)

    dump()
    s = doc["summary"]["overall"]
    print(f"align={align} exact_tail={a.exact_tail}: {s['passed']}/{s['cases']} "
          f"passed, ttft median {s['ttft_median_s']}s -> {a.out}",
          file=sys.stderr, flush=True)
    return 0 if not s["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
