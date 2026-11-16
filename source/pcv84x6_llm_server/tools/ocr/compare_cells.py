#!/usr/bin/env python3
"""Compare a table's recognised cells against the generator's ground truth.

Acceptance criterion 3 asks for cell text, not just structure, and for two
comparisons per table: board vs x86, and both vs truth. This tool does both
from saved artefacts, so the numbers in the report are reproducible without
re-running the board.

    python3 tools/ocr/compare_cells.py --truth tests/data/ocr/table_truth.json \\
        --got-json page.json --table cn_table_merged.png

``--got-json`` is a ``structure_page.py --json`` dump; the table block's HTML is
parsed into cells. Everything is reported per cell, including the text that is
*missing*: a comparison that only counts matches hides the failure mode this
project actually has (columns dropped entirely).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def parse_cells(html: str) -> list[dict]:
    """Cells in document order, with their span attributes.

    Parsed with a regex over ``<tr>``/``<td>`` rather than an HTML parser
    because the strings SLANet emits are frequently *not* well-formed (an
    unclosed ``<td`` is a real token in its vocabulary), so a strict parser
    would reject the very output being measured.
    """
    cells = []
    for row in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        for m in re.finditer(r"<td([^>]*)>(.*?)(?=<td|</tr>|$)", row, re.S):
            attrs, text = m.group(1), m.group(2)
            rs = re.search(r'rowspan="(\d+)"', attrs)
            cs = re.search(r'colspan="(\d+)"', attrs)
            cells.append({
                "text": re.sub(r"<[^>]+>", "", text).strip(),
                "rowspan": int(rs.group(1)) if rs else 1,
                "colspan": int(cs.group(1)) if cs else 1,
            })
    return cells


def _norm(s: str) -> str:
    """Whitespace-insensitive form: the OCR inserts spaces that truth has not."""
    return re.sub(r"\s+", "", s)


def compare(html: str, truth: dict) -> dict:
    got = parse_cells(html)
    want = truth["cells"]
    rows_got = len(re.findall(r"<tr>", html))

    got_text = [_norm(c["text"]) for c in got]
    want_text = [_norm(c["text"]) for c in want]

    # Per-cell: was the truth cell's text found anywhere in the output?
    per_cell = []
    for cell in want:
        needle = _norm(cell["text"])
        found = needle in got_text
        per_cell.append({
            "text": cell["text"], "row": cell["row"], "col": cell["col"],
            "found": found,
        })

    got_spans = sorted((c["rowspan"], c["colspan"]) for c in got
                       if c["rowspan"] > 1 or c["colspan"] > 1)
    want_spans = sorted((c["rowspan"], c["colspan"]) for c in want
                        if c["rowspan"] > 1 or c["colspan"] > 1)

    return {
        "rows_got": rows_got,
        "rows_want": truth["rows"],
        "cells_got": len(got),
        "cells_want": len(want),
        "text_found": sum(1 for c in per_cell if c["found"]),
        "text_total": len(per_cell),
        "spans_got": got_spans,
        "spans_want": want_spans,
        "spans_match": got_spans == want_spans,
        "per_cell": per_cell,
        "rows_missing": [c["text"] for c in per_cell if not c["found"]],
    }


def render(result: dict, label: str) -> str:
    lines = [
        f"{label}",
        f"  rows   {result['rows_got']}/{result['rows_want']}",
        f"  cells  {result['cells_got']}/{result['cells_want']}",
        f"  text   {result['text_found']}/{result['text_total']} truth cells found",
        f"  spans  {result['spans_got']} vs {result['spans_want']} "
        f"({'same' if result['spans_match'] else 'DIFFERENT'})",
    ]
    if result["rows_missing"]:
        lines.append(f"  missing: {', '.join(result['rows_missing'])}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", required=True, type=Path)
    ap.add_argument("--got-json", action="append", default=[], type=Path,
                    help="structure_page.py --json dump (repeatable)")
    ap.add_argument("--got-html", action="append", default=[], type=Path,
                    help="a raw HTML file, e.g. PaddleX's pred_html")
    ap.add_argument("--table", required=True)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    truths = json.loads(args.truth.read_text())
    if args.table not in truths:
        raise SystemExit(f"{args.table} not in {args.truth}")
    truth = truths[args.table]

    results = {}
    sources = []
    for jp in args.got_json:
        page = json.loads(jp.read_text())
        block = next((b for b in page["blocks"] if b["kind"] == "table"), None)
        if block is not None:
            sources.append((jp.name, block["html"]))
    for hp in args.got_html:
        sources.append((hp.name, hp.read_text()))

    for name, html in sources:
        r = compare(html, truth)
        results[name] = r
        print(render(r, name))
        print()

    if args.out:
        args.out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
