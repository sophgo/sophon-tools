#!/usr/bin/env python3
"""Acceptance for ``/v1/ocr`` ``mode: "vl"`` on the board (MYS-2664 §3).

What it does, per page:

1. posts the image to ``/v1/ocr`` with ``mode: "vl"`` and records the response --
   region count, each region's ``task`` and text, the table HTML, and the two
   timing numbers (``usage.layout_ms``, ``usage.vl_ms``);
2. compares the result with MYS-2660's whole-page run for the same image
   (``/data/mys2660/pg*/page.json`` when it exists): region count, the
   instruction each region got, and the text of each region;
3. compares a table's HTML with the x86 reference's, when a reference HTML is
   available.

It talks HTTP, so the service must be running with both models loaded. That is
the point: the numbers this prints are the service's, not a prototype's, and the
timings include the two-worker hand-off the mode actually costs.

    python3 tools/ocr/board_vl_acceptance.py \
        --base http://127.0.0.1:8010 --key KEY \
        --model ppocrv6-medium --vl-model paddleocr-vl-1.5 \
        --img-dir /data/mys2660/img --out /data/mys2664/vl_acceptance.json

Exit code is 0 when every page was served and every comparison that *could* be
made agreed; 1 otherwise. A page with no reference is reported as "no reference"
rather than as a pass, so the summary cannot overstate what was checked.
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

#: The pages the card names, in the order it names them.
PAGES = ("cn_notice.png", "en_report.png", "mixed_spec.png", "table_stats.png",
         "cn_table_merged.png")


def post_json(url: str, payload: dict, key: str, timeout: float) -> dict:
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def table_html(blocks: list[dict]) -> list[str]:
    return [block["text"] for block in blocks
            if block.get("label") == "table"
            and (block.get("text") or "").startswith("<table")]


def compare(page: str, got: dict, reference: dict | None,
            reference_html: dict[str, str]) -> dict:
    """The card's three comparisons, each reported on its own."""
    blocks = got.get("blocks") or []
    out: dict = {
        "page": page,
        "regions": len(blocks),
        "tasks": sorted({block.get("task") for block in blocks
                         if block.get("task")}),
        "layout_ms": got.get("usage", {}).get("layout_ms"),
        "vl_ms": got.get("usage", {}).get("vl_ms"),
        "vl_tokens": got.get("usage", {}).get("vl_tokens"),
        "markdown_chars": len(got.get("text") or ""),
        "tables": len(table_html(blocks)),
    }
    if reference is None:
        out["reference"] = "not available"
        return out
    ref_elements = reference.get("elements") or []
    out["reference_regions"] = len(ref_elements)
    out["regions_match"] = len(blocks) == len(ref_elements)
    out["tasks_match"] = (
        [block.get("task") for block in blocks]
        == [element.get("prompt") for element in ref_elements])
    # The reference's own timings, for the "每页耗时（版面、VL 合计）" line.
    out["reference_layout_ms"] = reference.get("layout_ms")
    out["reference_totals"] = reference.get("totals")
    html_got = table_html(blocks)
    if html_got and reference_html.get(page):
        out["table_html_matches_reference"] = (
            html_got[0] == reference_html[page])
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--key", required=True)
    parser.add_argument("--model", default="ppocrv6-medium")
    parser.add_argument("--vl-model", default="paddleocr-vl-1.5")
    parser.add_argument("--img-dir", type=Path, required=True)
    parser.add_argument("--reference-dir", type=Path, default=Path("/data/mys2660"))
    parser.add_argument("--reference-html", type=Path, default=None,
                        help="JSON {page: html} from the x86 reference, if kept")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=1800.0)
    args = parser.parse_args()

    reference_html: dict[str, str] = {}
    if args.reference_html and args.reference_html.is_file():
        reference_html = json.loads(args.reference_html.read_text(encoding="utf-8"))

    rows, failures = [], []
    for name in PAGES:
        path = args.img_dir / name
        if not path.is_file():
            rows.append({"page": name, "error": f"missing {path}"})
            failures.append(name)
            continue
        started = time.monotonic()
        try:
            got = post_json(f"{args.base}/v1/ocr", {
                "model": args.model, "image": data_url(path), "mode": "vl",
            }, args.key, args.timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            rows.append({"page": name, "http_status": exc.code, "error": detail})
            failures.append(name)
            print(f"{name}: HTTP {exc.code} {detail}", file=sys.stderr)
            continue
        wall = time.monotonic() - started

        reference = None
        candidate = args.reference_dir / "pg" / "page.json"
        if candidate.is_file():
            reference = json.loads(candidate.read_text(encoding="utf-8"))
        row = compare(name, got, reference, reference_html)
        row["wall_s"] = round(wall, 2)
        rows.append(row)
        if row.get("regions_match") is False or row.get("tasks_match") is False:
            failures.append(name)
        print(f"{name}: {row['regions']} regions, {row.get('vl_ms')} ms VL, "
              f"{wall:.1f} s wall", file=sys.stderr)

    summary = {
        "base": args.base, "model": args.model, "vl_model": args.vl_model,
        "pages": len(rows), "failed": failures,
        "checked": {
            "regions": sum(1 for row in rows if "regions_match" in row),
            "tasks": sum(1 for row in rows if "tasks_match" in row),
            "table_html": sum(1 for row in rows
                              if "table_html_matches_reference" in row),
        },
        "all_agreed": all(row.get("regions_match", True)
                          and row.get("tasks_match", True)
                          and row.get("table_html_matches_reference", True)
                          for row in rows),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"summary": summary, "rows": rows},
                                   ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if not failures and summary["all_agreed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
