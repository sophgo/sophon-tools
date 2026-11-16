#!/usr/bin/env python3
"""Aggregate per-trial JSON files produced by repeat_compare.py into one row.

Each trial is written by a *separate process* so that a faulted handle can never
influence the next trial through bmlib state (observed: re-creating a handle in
a process that already faulted can fail with "bmodel loading failed" /
"bm free gmem failed").

This tool fails loudly. A missing file, unparsable JSON, or a trial that failed
to load is an error with a non-zero exit status: an arm with a hole in it must
not be summarised as if the hole were a result.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: aggregate.py <label> <out.json> <trial.json>...", file=sys.stderr)
        return 2
    label, out_path, *paths = sys.argv[1:]
    if not paths:
        print(f"aggregate: no trial files for {label}", file=sys.stderr)
        return 2

    trials, problems = [], []
    for path in paths:
        p = Path(path)
        if not p.exists():
            problems.append(f"missing trial file: {path}")
            continue
        try:
            data = json.loads(p.read_text())
        except Exception as exc:  # noqa: BLE001
            problems.append(f"unparsable trial file {path}: {exc}")
            continue
        if (not isinstance(data, dict) or not isinstance(data.get("trials"), list)
                or not data["trials"]):
            problems.append(f"not a repeat_compare report: {path}")
            continue
        for trial in data["trials"]:
            if not isinstance(trial, dict):
                problems.append(f"invalid trial object: {path}")
                continue
            if trial.get("load_failed"):
                problems.append(f"{path}: trial load failed: {trial['load_failed']}")
            elif not trial.get("counts"):
                problems.append(f"{path}: trial has no observations")
            trials.append(trial)

    totals: dict[str, int] = {}
    for trial in trials:
        for verdict, count in trial.get("counts", {}).items():
            totals[verdict] = totals.get(verdict, 0) + count

    report = {
        "arm": label,
        "trials": len(trials),
        "totals": totals,
        "forwards_executed": sum(t.get("forward_executed", 0) for t in trials),
        "forwards_unknown": sum(t.get("forward_unknown", 0) for t in trials),
        "trials_load_failed": sum(1 for t in trials if t.get("load_failed")),
        "trials_with_zero": sum(1 for t in trials if t.get("counts", {}).get("zero")),
        "trials_with_nonfinite": sum(
            1 for t in trials if t.get("counts", {}).get("nonfinite")),
        "distinct_per_trial": [t.get("distinct_vectors") for t in trials
                               if not t.get("load_failed")],
        "worst_cosine": min((t["worst_cosine"] for t in trials
                             if t.get("worst_cosine") is not None), default=None),
        "problems": problems,
        "complete": not problems,
        "detail": [{k: t.get(k) for k in
                    ("tokens", "bucket", "counts", "distinct_vectors",
                     "successful_vectors", "worst_cosine", "load_failed",
                     "first_failure_index")} for t in trials],
    }
    Path(out_path).write_text(json.dumps(report, indent=1) + "\n")

    print(f"    {label}: zero={totals.get('zero', 0)} "
          f"nonfin={totals.get('nonfinite', 0)} refused={totals.get('refused', 0)} "
          f"other={totals.get('other_error', 0)} ok={totals.get('ok', 0)} "
          f"forwards={report['forwards_executed']} "
          f"fwd_unknown={report['forwards_unknown']} "
          f"loadfail={report['trials_load_failed']} "
          f"distinct={report['distinct_per_trial']} "
          f"worst_cos={report['worst_cosine']}")
    if problems:
        for problem in problems:
            print(f"    ERROR {problem}", file=sys.stderr)
        print(f"aggregate: {label} is INCOMPLETE ({len(problems)} problem(s))",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
