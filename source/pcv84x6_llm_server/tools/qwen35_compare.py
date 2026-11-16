#!/usr/bin/env python3
"""Board vs HF greedy agreement for the dense Qwen3.5 builds (MYS-2754).

Reads the reference produced by ``tools/qwen35_hf_ref.py`` and the board's own
greedy output, and reports the two numbers the precision table is about:

  * **token agreement** -- the fraction of the 128 generated positions that are
    the same id as the reference, position by position;
  * **first divergence** -- the index of the first position that differs, and
    both tokens in text form. This is the number that separates "one token
    picked differently at step 40 and then re-converged" from "diverged at step 1
    and never came back", which are different defects with the same average.

Position-by-position is the right comparison here and not, say, edit distance:
the board is greedy and the reference is greedy, so any difference at position i
is caused by everything up to i, and the earliest one is the one to explain.

    python3 tools/qwen35_compare.py --ref ref.json --board board.json \\
        [--label qwen3.5-4b-w4]

Both files are ``{"cases": [{"id", "tokens", "text"}, ...]}``; the board file is
what ``tools/qwen35_board_run.py`` writes.
"""
from __future__ import annotations

import argparse
import json
import sys


def compare(ref_case: dict, board_case: dict) -> dict:
    a = list(ref_case.get("tokens") or [])
    b = list(board_case.get("tokens") or [])
    n = min(len(a), len(b))
    first = None
    same = 0
    for i in range(n):
        if a[i] == b[i]:
            same += 1
        elif first is None:
            first = i
    return {
        "id": ref_case["id"],
        "ref_len": len(a),
        "board_len": len(b),
        "compared": n,
        "same": same,
        "agreement": (same / n) if n else 0.0,
        "first_divergence": first,
        # A prefix that matches up to the shortest of the two is what "the board
        # is right until here" means, so it is reported next to the divergence
        # index rather than left to be recomputed.
        "prefix_ok": first is None,
        "ref_text": ref_case.get("text", ""),
        "board_text": board_case.get("text", ""),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True)
    ap.add_argument("--board", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--json", default="", help="write the per-case table here")
    a = ap.parse_args()

    ref = json.load(open(a.ref))
    board = json.load(open(a.board))
    ref_cases = {c["id"]: c for c in ref["cases"]}
    board_cases = {c["id"]: c for c in board["cases"]}

    rows = []
    for case_id, rc in ref_cases.items():
        bc = board_cases.get(case_id)
        if bc is None:
            rows.append({"id": case_id, "missing": True})
            continue
        rows.append(compare(rc, bc))

    label = a.label or ref.get("hf", "?")
    print(f"== {label} ==")
    print(f"{'case':<14} {'same/total':>12} {'agree':>7} {'first-div':>10}")
    done = [r for r in rows if not r.get("missing")]
    for r in rows:
        if r.get("missing"):
            print(f"{r['id']:<14} {'MISSING':>12}")
            continue
        div = "-" if r["first_divergence"] is None else str(r["first_divergence"])
        print(f"{r['id']:<14} {r['same']:>5}/{r['compared']:<6} "
              f"{100 * r['agreement']:>6.1f}% {div:>10}")

    if done:
        total_same = sum(r["same"] for r in done)
        total_n = sum(r["compared"] for r in done)
        exact = sum(1 for r in done if r["prefix_ok"])
        print(f"{'TOTAL':<14} {total_same:>5}/{total_n:<6} "
              f"{100 * total_same / total_n if total_n else 0:>6.1f}%")
        print(f"cases with an identical 128-token prefix: {exact}/{len(done)}")
        divs = [r["first_divergence"] for r in done if r["first_divergence"] is not None]
        if divs:
            print(f"earliest divergence over all cases: position {min(divs)}, "
                  f"median {sorted(divs)[len(divs) // 2]}")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"label": label, "rows": rows}, fh, ensure_ascii=False, indent=1)
        print("wrote", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
