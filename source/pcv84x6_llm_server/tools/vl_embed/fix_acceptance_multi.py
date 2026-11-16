#!/usr/bin/env python3
"""Run ``fix_acceptance.py`` in N fresh processes and aggregate the verdicts.

Why separate processes: the encoder latches a fault for the life of the handle,
and on the field SDK a faulted handle cannot be re-created in the same process
(``bmodel loading failed``). One process per round is therefore the only way to
observe more than one independent first-run, and the delivery asks for at least
three fresh processes of at least 30 valid requests each.

This driver adds what a single process cannot show:

* every process reports its own vectors; the **cross-process** repeat check
  compares the same input's vector between processes. A vector that is
  reproducible inside one process but drifts between them would be a different
  defect, and it would pass a single-process run.
* the aggregate fails if any process failed, if any process faulted, or if the
  processes disagree on an input's vector.

Usage::

    python3 tools/vl_embed/fix_acceptance_multi.py --processes 3 \\
        --library ... --config ... --model ... \\
        --reference ... --reference-boundary ... --image-dir ... \\
        --out-dir /data/mys2914/accept

Exit codes: 0 every process passed and agreed; 1 a gate failed; 2 setup error.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SINGLE = HERE / "fix_acceptance.py"
MIN_VALID_REQUESTS = 30


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else float("nan")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--processes", type=int, default=3)
    p.add_argument("--library", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--reference", type=Path)
    p.add_argument("--reference-boundary", type=Path)
    p.add_argument("--reference-extra", type=Path, action="append", default=[],
                   help="additional reference file (e.g. the 63/64/65-token set)")
    p.add_argument("--image-dir", type=Path)
    p.add_argument("--boundary-dir", type=Path,
                   help="boundary fixture set; its eval.json pairs case ids with images")
    p.add_argument("--require-file", type=Path,
                   help="file listing cases that MUST be compared for the numeric "
                        "gate to pass")
    p.add_argument("--per-shape", type=int, default=10)
    p.add_argument("--rounds", type=int, default=30)
    p.add_argument("--warmup", type=int, default=2)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--skip-reference", action="store_true")
    a = p.parse_args()
    if a.processes < 1:
        p.error("--processes must be >= 1")
    a.out_dir.mkdir(parents=True, exist_ok=True)

    runs, failures = [], []
    for index in range(a.processes):
        out = a.out_dir / f"process-{index}.json"
        cmd = [sys.executable, str(SINGLE),
               "--library", a.library, "--config", a.config, "--model", a.model,
               "--per-shape", str(a.per_shape), "--rounds", str(a.rounds),
               "--warmup", str(a.warmup), "--process", str(index), "--out", str(out)]
        if a.reference:
            cmd += ["--reference", str(a.reference)]
        if a.reference_boundary:
            cmd += ["--reference-boundary", str(a.reference_boundary)]
        for extra in a.reference_extra:
            cmd += ["--reference-extra", str(extra)]
        if a.image_dir:
            cmd += ["--image-dir", str(a.image_dir)]
        if a.boundary_dir:
            cmd += ["--boundary-dir", str(a.boundary_dir)]
        if a.require_file:
            cmd += ["--require-file", str(a.require_file)]
        if a.skip_reference:
            cmd += ["--skip-reference"]
        print(f"[multi] process {index} ...", file=sys.stderr, flush=True)
        started = time.perf_counter()
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        took = time.perf_counter() - started
        print(f"[multi] process {index} rc={done.returncode} in {took:.0f}s",
              file=sys.stderr, flush=True)
        if done.returncode != 0:
            failures.append(f"process {index} rc={done.returncode}: "
                            f"{(done.stderr or done.stdout).strip()[-1500:]}")
            continue
        try:
            runs.append(json.loads(out.read_text()))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"process {index}: unreadable report: {exc}")

    # A process must have done real work: "three processes ran" is worthless if
    # each served four requests.
    for index, run in enumerate(runs):
        repeat = run["repeat"]
        served = repeat.get("valid_requests") or sum(
            shape["calls"] for shape in repeat["shapes"])
        if served < MIN_VALID_REQUESTS:
            failures.append(f"process {index}: only {served} valid requests "
                            f"(< {MIN_VALID_REQUESTS})")
        # Switch equality must actually have been exercised in every process.
        # A process that repeated each shape in place but never revisited an
        # earlier one has not tested the transition the field failure needed.
        if not repeat.get("revisit_requests"):
            failures.append(f"process {index}: no revisit was issued; "
                            f"switch equality was not tested")
        if repeat.get("revisit_failures"):
            failures.append(f"process {index}: {repeat['revisit_failures']} of "
                            f"{repeat['revisit_requests']} revisits differed "
                            f"from their baseline")
        if not run.get("passed", False):
            failures.append(f"process {index}: {len(run.get('failures') or [])} gate "
                            f"failures: {(run.get('failures') or [])[:3]}")

    # Cross-process reproducibility: the same shape must produce the same vector
    # in every process. The single-process run already proves intra-process
    # stability; this is the part a fresh handle could break, and it would pass
    # a one-process run.
    cross = {"shapes": [], "failures": []}
    if len(runs) > 1:
        names = [shape["shape"] for shape in runs[0]["repeat"]["shapes"]]
        for name in names:
            digests = {}
            for index, run in enumerate(runs):
                for shape in run["repeat"]["shapes"]:
                    if shape["shape"] == name and shape.get("digest"):
                        digests[index] = shape["digest"]
            entry = {"shape": name, "digests": digests,
                     "identical": len(set(digests.values())) <= 1}
            cross["shapes"].append(entry)
            if not entry["identical"]:
                cross["failures"].append(
                    f"{name}: cross-process digests differ: {digests}")
    failures += cross["failures"]

    report = {"processes": a.processes, "runs": runs, "cross_process": cross,
              "failures": failures, "passed": not failures,
              "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    (a.out_dir / "multi.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n")

    for index, run in enumerate(runs):
        buckets = run["repeat"]["buckets_seen"]
        served = sum(shape["calls"] for shape in run["repeat"]["shapes"])
        print(f"process {index}: requests={served} buckets={buckets} "
              f"revisits={run['repeat'].get('revisit_requests')} "
              f"(failed {run['repeat'].get('revisit_failures')}) "
              f"passed={run.get('passed')}")
        if "numeric" in run:
            numeric = run["numeric"]
            worst = min(v for v in numeric["worst"].values() if v is not None)
            print(f"  reference {numeric['compared']}/{numeric['rows']} compared, "
                  f"worst cosine {worst:.6f}, "
                  f"required missing {numeric.get('required_missing')}")
    if failures:
        print(f"FAILED ({len(failures)}):", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print(f"PASS ({len(runs)} processes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
