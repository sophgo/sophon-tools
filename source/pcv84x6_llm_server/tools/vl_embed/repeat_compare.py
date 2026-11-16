#!/usr/bin/env python3
"""MYS-2913: is one encoder call reproducible?

Issues the *same* input repeatedly against one encoder handle and reports, per
call, whether the engine actually executed a forward, or refused because the
handle was already latched into the fault state.

That distinction is the whole point of the accounting here. The native engine
latches ``fault`` the first time it sees a zero or non-finite vector
(``native/src/vl_embed_engine.cpp:384``), and every later ``forward`` returns
"NPU engine faulted; reload required" at ``:281`` *without running anything*.
Counting those refusals as further zero vectors inflates the failure rate and
mismeasures what was actually observed, so each call is classified as exactly
one of:

    ok              the forward ran and returned a usable vector
    zero            the forward ran and produced an all-zero vector
    nonfinite       the forward ran and produced NaN/Inf
    refused         no forward ran: the handle was already faulted
    input_error     rejected before any device work (token/image limits)

Only ``zero`` and ``nonfinite`` are device observations. ``refused`` is the
protection working as designed.

An *independent trial* is one fresh handle, which is the only way to observe
more than one first-failure; ``--trials`` repeats the whole sequence that way.

Usage::

    python3 tools/vl_embed/repeat_compare.py --library ... --config ... --model ... \\
        --calls 6 --text "hello world"
    python3 tools/vl_embed/repeat_compare.py ... --image 384x512 --trials 3
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repeat_probe import Encoder, make_png, _size  # noqa: E402

REFUSED = "NPU engine faulted"
ZERO = "zero vector"


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else float("nan")


def max_abs(a, b) -> float:
    return max(abs(x - y) for x, y in zip(a, b))


def classify(rec: dict) -> str:
    """What actually happened on this call -- see the module docstring."""
    if rec.get("ok"):
        return "ok"
    error = rec.get("error") or ""
    if REFUSED in error:
        return "refused"
    if ZERO in error:
        return "zero"
    if "non-finite" in error:
        return "nonfinite"
    return "input_error"


def one_trial(a, text: str, png, trial: int) -> dict:
    """One fresh handle, ``--calls`` identical requests, classified per call."""
    enc = Encoder(a.library, a.model, a.config)
    calls, vectors = [], []
    try:
        for index in range(a.calls):
            rec = enc.encode(text=text, png=png, dimensions=a.dimensions,
                             keep_vector=True)
            verdict = classify(rec)
            # ``forward_executed`` is the only honest denominator: a refusal
            # never reached the device, so it cannot be a device observation.
            executed = verdict in ("ok", "zero", "nonfinite")
            calls.append({
                "index": index,
                "verdict": verdict,
                "forward_executed": executed,
                "tokens": rec.get("tokens"),
                "bucket": rec.get("bucket"),
                "norm": rec.get("norm"),
                "nonzero": rec.get("nonzero"),
                "vecsha": rec.get("vecsha"),
                "error": rec.get("error"),
                "faulted_after": rec.get("faulted"),
                "total_ms": rec.get("total_ms"),
                "vision_ms": rec.get("vision_ms"),
                "encoder_ms": rec.get("encoder_ms"),
            })
            vectors.append(rec.get("vec") if verdict == "ok" else None)
    finally:
        enc.close()

    pairs = []
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            vi, vj = vectors[i], vectors[j]
            if vi is None or vj is None:
                continue
            pairs.append({"i": i, "j": j,
                          "cosine": round(cosine(vi, vj), 9),
                          "max_abs": round(max_abs(vi, vj), 9)})
    shas = [c["vecsha"] for c in calls if c["verdict"] == "ok"]
    counts = {}
    for call in calls:
        counts[call["verdict"]] = counts.get(call["verdict"], 0) + 1
    return {
        "trial": trial,
        "tokens": calls[0]["tokens"] if calls else None,
        "bucket": calls[0]["bucket"] if calls else None,
        "calls": calls,
        "counts": counts,
        "forward_executed": sum(1 for c in calls if c["forward_executed"]),
        "first_failure_index": next(
            (c["index"] for c in calls if c["verdict"] in ("zero", "nonfinite")), None),
        "successful_vectors": len(shas),
        "distinct_vectors": len(set(shas)),
        "worst_cosine": min((p["cosine"] for p in pairs), default=None),
        "worst_max_abs": max((p["max_abs"] for p in pairs), default=None),
        "pairs": pairs,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--library", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--calls", type=int, default=6,
                   help="identical requests per trial (default 6)")
    p.add_argument("--trials", type=int, default=1,
                   help="independent trials, each on a fresh handle (default 1)")
    p.add_argument("--text", default="A photograph of a meal on a wooden table.")
    p.add_argument("--long-text-repeats", type=int, default=0,
                   help="repeat --text this many times to select a larger bucket")
    p.add_argument("--image", help="HxW pixels, e.g. 384x512; omit for text only")
    p.add_argument("--dimensions", type=int, default=None)
    p.add_argument("--output")
    a = p.parse_args()

    text = (" ".join([a.text] * a.long_text_repeats) if a.long_text_repeats else a.text)
    png = None
    if a.image:
        h, w = _size(a.image)
        png = make_png(h, w, 20261116)

    trials = [one_trial(a, text, png, t) for t in range(a.trials)]

    totals = {}
    for trial in trials:
        for verdict, count in trial["counts"].items():
            totals[verdict] = totals.get(verdict, 0) + count
    report = {
        "input": {"text_chars": len(text), "image": a.image},
        "calls_per_trial": a.calls,
        "trials": trials,
        "totals": totals,
        # The honest headline: how many trials ever produced a device-level
        # failure, and how many forwards actually ran.
        "trials_with_zero": sum(1 for t in trials if t["counts"].get("zero")),
        "trials_with_nonfinite": sum(1 for t in trials if t["counts"].get("nonfinite")),
        "forwards_executed": sum(t["forward_executed"] for t in trials),
        "worst_cosine": min((t["worst_cosine"] for t in trials
                             if t["worst_cosine"] is not None), default=None),
    }
    if a.output:
        Path(a.output).write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "trials"},
                     ensure_ascii=False), flush=True)
    for trial in trials:
        detail = " ".join(f"{c['index']}:{c['verdict']}" for c in trial["calls"])
        print(f"  trial{trial['trial']} tokens={trial['tokens']} "
              f"bucket={trial['bucket']} distinct={trial['distinct_vectors']}/"
              f"{trial['successful_vectors']} worst_cos={trial['worst_cosine']} [{detail}]",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
