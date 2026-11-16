#!/usr/bin/env python3
"""Aggregate per-trial JSON files produced by repeat_compare.py into one row.

Each trial is written by a *separate process* so that a faulted handle can never
influence the next trial through bmlib state (observed: re-creating a handle in
a process that already faulted can fail with "bmodel loading failed" /
"bm free gmem failed"). Aggregating here keeps that isolation while still
reporting one line per arm.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    label, out_path, *paths = sys.argv[1:]
    trials = []
    for path in paths:
        try:
            data = json.loads(Path(path).read_text())
        except Exception as exc:  # noqa: BLE001
            trials.append({"load_failed": f"unreadable report: {exc}", "counts": {},
                           "calls": [], "forward_executed": 0,
                           "distinct_vectors": 0, "successful_vectors": 0,
                           "worst_cosine": None, "tokens": None, "bucket": None})
            continue
        # --trials 1 means exactly one entry; keep its shape.
        trials.extend(data["trials"])

    totals = {}
    for trial in trials:
        for verdict, count in trial.get("counts", {}).items():
            totals[verdict] = totals.get(verdict, 0) + count
    distinct = [t["distinct_vectors"] for t in trials if not t.get("load_failed")]
    report = {
        "arm": label,
        "trials": len(trials),
        "totals": totals,
        "forwards_executed": sum(t.get("forward_executed", 0) for t in trials),
        "trials_load_failed": sum(1 for t in trials if t.get("load_failed")),
        "trials_with_zero": sum(1 for t in trials if t.get("counts", {}).get("zero")),
        "trials_with_nonfinite": sum(
            1 for t in trials if t.get("counts", {}).get("nonfinite")),
        "distinct_per_trial": distinct,
        "worst_cosine": min((t["worst_cosine"] for t in trials
                             if t.get("worst_cosine") is not None), default=None),
        "detail": [{k: t.get(k) for k in
                    ("tokens", "bucket", "counts", "distinct_vectors",
                     "successful_vectors", "worst_cosine", "load_failed",
                     "first_failure_index")} for t in trials],
    }
    Path(out_path).write_text(json.dumps(report, indent=1) + "\n")
    print(f"    {label}: zero={totals.get('zero', 0)} nonfin={totals.get('nonfinite', 0)} "
          f"refused={totals.get('refused', 0)} ok={totals.get('ok', 0)} "
          f"forwards={report['forwards_executed']} loadfail={report['trials_load_failed']} "
          f"distinct={distinct} worst_cos={report['worst_cosine']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
