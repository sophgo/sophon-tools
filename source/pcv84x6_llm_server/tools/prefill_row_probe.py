#!/usr/bin/env python3
"""What the engine actually ran for one prompt: prefill width L and replayed rows.

MYS-2405 asks for a table of "n, n % 64, the real prefill row count L, replayed
rows, TTFT" to check the claim that the cost tracks the number of rows replayed
rather than the prompt length. That claim comes from the engine's own arithmetic
(``native/src/llm_engine.cpp``, ``Session::prefill_impl``):

    exact_from = n - min(n, exact_tail)
    L = cur                                  per chunk of ``max_input`` rows
    if cur % al != 0:            L = (cur / al) * al
    if c0 + L > exact_from:      L = max(0, (exact_from - c0) / al * al)
    replayed rows = cur - L

Re-deriving that formula in Python would only prove it equals itself. So this
tool counts the graph launches the engine really made, which is a statement about
the device, not about the source:

  * ``block_<i>`` / ``block_kv_<i>`` -- the dynamic prefill graph, one launch per
    layer per chunk, at width L;
  * ``block_cache_<i>``             -- the single-row decode graph, one launch per
    layer per *replayed row*.

Every layer launches exactly one of each, so ``L`` = prefill launches / layers and
replayed rows = decode launches / layers, with the layer count read off the same
trace (``max(index) + 1``). ``embedding`` / ``lm_head`` are per-chunk or per-call
fixed costs and are excluded from both counts.

    LLM_TRACE=1 LLM_PREFILL_ALIGN=16 timeout 900 \\
        python3 tools/prefill_row_probe.py --lib libcv84x6_llm.so \\
            --model model.bmodel --cases tools/prefill_ab_cases/low/cases.json \\
            --only a01,a06 --exact-tail 8 --out logs/rows-G1.json

The launch trace is C++ ``stderr``, so stderr is redirected to a file around each
feed and parsed back. One engine load per process, one session per case, the same
ABI binding as ``prefill_ab_eval.py`` -- the widths reported are the ones a graded
run of the same case and alignment uses. Run under ``timeout`` as well: a launch
that wedges the TPU blocks in the driver without running Python signal handlers.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import prefill_ab_eval as ev  # noqa: E402  (same ABI binding, same cases)

WATCHDOG_SECS = 300
EXIT_WATCHDOG = 3

_LAUNCH = re.compile(r"^\[launch\] (\S+) ([\d.]+) ms", re.MULTILINE)
_BLOCK = re.compile(r"^block_(\d+)$")
_BLOCK_KV = re.compile(r"^block_kv_(\d+)$")
_DECODE = re.compile(r"^block_cache_(\d+)$")
_LAYERS_LINE = re.compile(r"layers=(\d+)")


# --------------------------------------------------------------------------
# Trace capture
# --------------------------------------------------------------------------
class TraceTap:
    """Redirect fd 2 to a file for the duration of one call, then parse it.

    A file rather than a pipe: the engine writes from the calling thread, so
    nothing can be lost, while a pipe would need a reader thread and could block
    the TPU call on a full buffer.
    """

    def __init__(self, path: str):
        self.path = path
        self.saved = -1
        self.fd = -1

    def __enter__(self):
        sys.stderr.flush()
        self.saved = os.dup(2)
        self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        os.dup2(self.fd, 2)
        return self

    def __exit__(self, *exc):
        sys.stderr.flush()
        os.dup2(self.saved, 2)
        os.close(self.saved)
        os.close(self.fd)
        self.saved = self.fd = -1
        return False

    def launches(self) -> list[tuple[str, float]]:
        with open(self.path, encoding="utf-8", errors="replace") as f:
            return parse_trace(f.read())

    def raw(self) -> str:
        with open(self.path, encoding="utf-8", errors="replace") as f:
            return f.read()


def parse_trace(text: str) -> list[tuple[str, float]]:
    """``(graph name, milliseconds)`` for every launch the engine logged."""
    return [(m.group(1), float(m.group(2))) for m in _LAUNCH.finditer(text)]


def classify(launches: list[tuple[str, float]]) -> dict:
    """Split launches into prefill-graph, decode-graph, and fixed cost."""
    prefill_ms = decode_ms = other_ms = 0.0
    layers, dlayers = set(), set()
    n_prefill = n_decode = 0
    widths = {}
    for name, ms in launches:
        m = _DECODE.match(name)
        if m:
            n_decode += 1
            decode_ms += ms
            dlayers.add(int(m.group(1)))
            continue
        m = _BLOCK.match(name) or _BLOCK_KV.match(name)
        if m:
            n_prefill += 1
            prefill_ms += ms
            layers.add(int(m.group(1)))
            # Which prefill graph was used says whether a chunk was split off the
            # history path; per-chunk *width* is not in the trace, so it is not
            # claimed here (L comes from the launch count instead).
            widths[name] = widths.get(name, 0) + 1
            continue
        other_ms += ms
    return {"prefill_launches": n_prefill, "decode_launches": n_decode,
            "prefill_layers": len(layers), "decode_layers": len(dlayers),
            "prefill_ms": round(prefill_ms, 3),
            "decode_ms": round(decode_ms, 3),
            "other_ms": round(other_ms, 3),
            "kinds": sorted(widths)}


def feed(fn, tokens: list[int], tap: TraceTap) -> tuple[float, list]:
    """Time one feed and hand back the launches it made."""
    with tap:
        secs = fn(tokens)
    return secs, tap.launches()


def rows_of(c: dict, layers: int) -> dict:
    """L and replayed rows, from launch counts."""
    pl = c["prefill_layers"] or layers
    dl = c["decode_layers"] or layers
    return {"L": c["prefill_launches"] // max(pl, 1),
            "replay": c["decode_launches"] // max(dl, 1),
            "prefill_ms": c["prefill_ms"], "replay_ms": c["decode_ms"],
            "other_ms": c["other_ms"]}


def predict(n: int, align: int, exact_tail: int, max_input: int) -> dict:
    """The engine's arithmetic, per ``prefill_impl`` -- to be compared, not used."""
    exact_from = n - min(n, max(0, exact_tail))
    total_l = total_replay = 0
    for c0 in range(0, n, max_input):
        cur = min(max_input, n - c0)
        L = cur
        if cur % align != 0:
            L = (cur // align) * align
        if c0 + L > exact_from:
            L = max(0, (exact_from - c0) // align * align)
        total_l += L
        total_replay += cur - L
    return {"L": total_l, "replay": total_replay}


# --------------------------------------------------------------------------
def measure(lib, eng, tok, case: dict, cases_dir: str, exact_tail: int,
            layers: int, tap: TraceTap) -> dict:
    prompt, delta = ev.case_inputs(case, cases_dir)
    out = {"id": case["id"], "type": case["type"], "n": len(prompt),
           "n_delta": len(delta) if delta else 0}
    s = ev.Session(lib, eng)
    try:
        if delta is not None:
            # The tail applies to the follow-up extend only, where the product
            # puts it; the history prefill is measured as its own row.
            h_secs, h_launch = feed(s.prefill, prompt, tap)
            h = dict(rows_of(classify(h_launch), layers), n=len(prompt),
                     ttft_s=round(h_secs, 4))
            out["history"] = h
            s.decode()   # the token the history sampled; state must hold it
            if exact_tail:
                s.set_exact_tail(exact_tail)
            secs, launches = feed(s.extend, delta, tap)
            n = len(delta)
        else:
            if exact_tail:
                s.set_exact_tail(exact_tail)
            secs, launches = feed(s.prefill, prompt, tap)
            n = len(prompt)
        row = dict(rows_of(classify(launches), layers), n=n,
                   ttft_s=round(secs, 4))
        out.update(row)
        out["align"] = int(os.environ.get("LLM_PREFILL_ALIGN", "64"))
        out["exact_tail"] = exact_tail
        out["predicted"] = predict(n, out["align"], exact_tail, MAX_INPUT[0])
    except RuntimeError as exc:
        out["error"] = str(exc)
    finally:
        s.close()
    return out


MAX_INPUT = [2048]   # the engine's own max_input; read from the load below


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Count the prefill width and the replayed rows the engine ran.")
    ap.add_argument("--lib", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--cases", required=True)
    ap.add_argument("--tokenizer", default=ev.DEFAULT_TOKENIZER)
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--exact-tail", type=int, default=0, metavar="K")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dev", type=int, default=0)
    a = ap.parse_args()

    if not os.environ.get("LLM_TRACE"):
        raise SystemExit("LLM_TRACE must be set: this tool counts launches, it does "
                         "not re-derive the formula")
    if os.environ.get("LLM_ALIGN_ABOVE", "0") != "0":
        raise SystemExit("LLM_ALIGN_ABOVE is set; the engine's rule assumes 0")

    cases_dir = os.path.dirname(os.path.abspath(a.cases))
    _, cases = ev.load_cases(a.cases)
    if a.only:
        wanted = [x.strip() for x in a.only.split(",") if x.strip()]
        by_id = {c["id"]: c for c in cases}
        missing = [x for x in wanted if x not in by_id]
        if missing:
            raise SystemExit(f"unknown case ids: {missing}")
        cases = [by_id[x] for x in wanted]

    tok = ev.Tokenizer(ev.bind_tokenizer(a.lib), a.tokenizer)
    lib = ev.bind(a.lib)
    # ev.bind() already declares these, but the declarations are repeated here
    # because ctypes' default conversion truncates a ctypes-array pointer to a
    # 32-bit int: the engine would then dereference garbage and die *inside*
    # itself, which reads like a driver fault (tests/test_tool_bindings.py).
    lib.llm_engine_load.restype = ctypes.c_void_p
    lib.llm_engine_load.argtypes = [ctypes.c_char_p, ctypes.c_int,
                                    ctypes.POINTER(ctypes.c_char_p)]
    lib.llm_engine_free.restype = None
    lib.llm_engine_free.argtypes = [ctypes.c_void_p]
    tap = TraceTap(os.path.join(os.path.dirname(os.path.abspath(a.out)), "_trace.tmp"))

    doc: dict = {"align": int(os.environ.get("LLM_PREFILL_ALIGN", "64")),
                 "exact_tail": a.exact_tail, "lib": a.lib,
                 "lib_md5": ev.md5_of(a.lib), "model": a.model,
                 "model_md5": ev.md5_of(a.model), "cases_file": a.cases,
                 "cases": []}

    def dump() -> None:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")

    signal.signal(signal.SIGALRM, lambda *_: (dump(), os._exit(EXIT_WATCHDOG)))

    err = ctypes.c_char_p()
    t = time.perf_counter()
    # Tapped too, so the engine's own "layers=" and "max_input=" are on record
    # rather than assumed.
    with tap:
        eng = lib.llm_engine_load(a.model.encode(), a.dev, ctypes.byref(err))
    raw = tap.raw()
    if not eng:
        raise SystemExit(f"engine load failed: {err.value}")
    m = _LAYERS_LINE.search(raw)
    layers = int(m.group(1)) if m else 40
    MAX_INPUT[0] = lib.llm_engine_max_input_length(eng)
    doc["layers"], doc["max_input"] = layers, MAX_INPUT[0]
    print(f"load {time.perf_counter() - t:.1f}s align={doc['align']} "
          f"tail={a.exact_tail} layers={layers} max_input={MAX_INPUT[0]}",
          file=sys.stderr, flush=True)

    try:
        for case in cases:
            signal.alarm(WATCHDOG_SECS)
            r = measure(lib, eng, tok, case, cases_dir, a.exact_tail, layers, tap)
            signal.alarm(0)
            doc["cases"].append(r)
            print(f"{r['id']} {r['type']} n={r['n']}"
                  f"{'+%d' % r['n_delta'] if r['n_delta'] else ''} "
                  f"L={r.get('L')} replay={r.get('replay')} "
                  f"pred_L={r.get('predicted', {}).get('L')} "
                  f"pred_replay={r.get('predicted', {}).get('replay')} "
                  f"ttft={r.get('ttft_s')}", file=sys.stderr, flush=True)
            dump()
    finally:
        signal.alarm(0)
        tok.close()
        lib.llm_engine_free(eng)
    dump()
    return 0


if __name__ == "__main__":
    sys.exit(main())
