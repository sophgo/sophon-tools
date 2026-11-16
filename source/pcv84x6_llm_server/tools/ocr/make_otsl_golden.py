#!/usr/bin/env python3
"""Regenerate ``tests/data/ocr/otsl_golden.json`` from PaddleX's own converter.

The OTSL -> HTML port in ``app/engine/ocr_vl_page.py`` is only worth anything if
it is compared against the reference rather than against a second transcription
of the same reading. So this tool imports PaddleX's real
``convert_otsl_to_html`` -- loading ``uilts.py`` in isolation, with its two
geometry imports and its ``colorlog`` logger stubbed, none of which the OTSL
functions call -- and records its output for a fixed set of inputs.

Requires a PaddleX source tree; nothing in the service depends on it.

    python3 tools/ocr/make_otsl_golden.py --paddlex /path/to/paddlex-3.7.2/paddlex

The curated inputs are the real board answers from MYS-2660 (``docs/ocr-vl.md``
§5) plus one case per construct the grammar allows, because those are the ones
where a padding or span rule decides the result. The fuzz cases are a fixed
seed, so re-running this produces the same file.

The reference *raises* on a `<lcel>`/`<ucel>` that has no cell to its left/above
(``uilts.py``'s ``count_right`` indexes past the row). Those inputs are recorded
with ``html: null``: the service must answer HTML rather than a 500 for text a
model can legitimately emit, so there is no reference output to match -- but the
case is worth pinning so the difference is deliberate and visible.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "data" / "ocr" / "otsl_golden.json"

#: The real answers the board produced in MYS-2660, abbreviated where the full
#: row list does not add a construct (the span cases are kept whole).
CURATED = [
    # table_stats: 6 rows x 4 cols, one <lcel> header span
    "<fcel>2026年第三季度生产数据统计表<lcel><lcel><lcel><nl><fcel>产线<fcel>产量（台）"
    "<fcel>合格率<fcel>负责人<nl><fcel>一号线<fcel>4,120<fcel>99.6%<fcel>张伟<nl>"
    "<fcel>二号线<fcel>3,860<fcel>99.1%<fcel>李静<nl><fcel>三号线<fcel>3,300<fcel>98.7%"
    "<fcel>王强<nl><fcel>四号线<fcel>1,200<fcel>99.4%<fcel>赵敏<nl><fcel>合计"
    "<fcel>12,480<fcel>99.2%<fcel>—<nl>",
    # cn_table_merged: both a <lcel> header span and a 3-row <ucel> span
    "<fcel>2026年第三季度设备巡检记录<lcel><lcel><lcel><lcel><nl><fcel>区域/设备<lcel>"
    "<fcel>巡检日期<fcel>状态<fcel>负责人<nl><fcel>二号机房<fcel>服务器D<fcel>2026-06-30"
    "<fcel>正常<fcel>赵敏<nl><fcel>一号机房<fcel>服务器A<fcel>2026-07-12<fcel>正常"
    "<fcel>张伟<nl><ucel><fcel>服务器B<fcel>2026-08-09<fcel>告警<fcel>李娜<nl><ucel>"
    "<fcel>服务器C<fcel>2026-09-01<fcel>正常<fcel>王强<nl>",
    # the minimal table
    "<fcel>a<fcel>b<nl><fcel>c<fcel>d<nl>",
    # a short row: the padder appends <ecel>
    "<fcel>a<fcel>b<fcel>c<nl><fcel>d<nl>",
    # an empty cell
    "<ecel><fcel>x<nl>",
    # <xcel> is a span in both directions
    "<fcel>a<xcel><nl><xcel><fcel>b<nl>",
    # a span wider than the row that follows it
    "<fcel>a<lcel><lcel><nl><fcel>b<fcel>c<nl>",
    # a span that runs past the end of its own row
    "<fcel>a<fcel>b<lcel><nl><fcel>c<fcel>d<fcel>e<nl>",
    # a rowspan whose lower row is entirely covered
    "<fcel>a<fcel>b<nl><ucel><ucel><nl>",
    # HTML-special characters in cell text
    "<fcel>a<b<fcel>&amp<fcel>\"q\"<nl>",
    # surrounding whitespace and a missing terminator
    "\n<fcel>a<fcel>b<nl>\n",
    "<fcel>only<nl>",
    # a decode that stopped mid-cell: the partial tag becomes cell text
    "<fcel>a<fcel>b<nl><fcel>c<fcel>",
    # a blank line inside the table
    "<fcel>a<nl><nl><fcel>b<nl>",
    # prose around the table (a text prompt's answer) -> just the table
    "text before<fcel>a<nl>text after",
    # no cells at all -> ""
    "",
    "<nl>",
    "上表是 2026 年第三季度的产线统计。一号线产量最高。",
]

#: The 15 000-odd OTSL strings a 23-class page can produce are far fewer in
#: shape than they look; a fixed seed over the tag alphabet covers the rest.
FUZZ_CASES = 60
FUZZ_SEED = 20261107


def _load_uilts(paddlex_root: Path):
    """Import PaddleX's ``uilts.py`` without importing PaddleX."""
    for name, rel in [("px", "."), ("px.inference", "inference"),
                      ("px.inference.pipelines", "inference/pipelines"),
                      ("px.inference.pipelines.paddleocr_vl",
                       "inference/pipelines/paddleocr_vl")]:
        module = types.ModuleType(name)
        module.__path__ = [str(paddlex_root / rel)]
        sys.modules[name] = module

    colorlog = types.ModuleType("colorlog")

    class _Logger:
        def __getattr__(self, _name):
            return lambda *a, **k: None

    colorlog.getLogger = lambda *a, **k: _Logger()
    colorlog.StreamHandler = object
    colorlog.ColoredFormatter = object
    colorlog.basicConfig = lambda *a, **k: None
    sys.modules["colorlog"] = colorlog

    geometry = types.ModuleType("px.inference.pipelines.layout_parsing.utils")
    for name in ("calculate_overlap_ratio", "calculate_projection_overlap_ratio"):
        def _unused(*a, _n=name, **k):
            raise NotImplementedError(f"{_n} is not used by the OTSL functions")
        setattr(geometry, name, _unused)
    sys.modules[geometry.__name__] = geometry

    spec = importlib.util.spec_from_file_location(
        "px.inference.pipelines.paddleocr_vl.uilts",
        paddlex_root / "inference/pipelines/paddleocr_vl/uilts.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fuzz() -> list[str]:
    tags = ["<fcel>", "<ecel>", "<nl>", "<lcel>", "<ucel>", "<xcel>"]
    words = ["a", "产线", "4,120", "", "x y", "<b>&", "—", "\"q\""]
    rng = random.Random(FUZZ_SEED)
    out = []
    for _ in range(FUZZ_CASES):
        pieces = []
        for _ in range(rng.randint(1, 22)):
            tag = rng.choice(tags)
            pieces.append(tag)
            if tag == "<fcel>" and rng.random() < 0.8:
                pieces.append(rng.choice(words))
        out.append("".join(pieces))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paddlex", required=True, type=Path,
                        help="the paddlex package directory (…/paddlex), not its parent")
    parser.add_argument("--out", type=Path, default=GOLDEN)
    args = parser.parse_args()

    uilts = _load_uilts(args.paddlex)
    cases = []
    for otsl in CURATED:
        cases.append({"otsl": otsl, "html": uilts.convert_otsl_to_html(otsl),
                      "note": "curated"})
    for otsl in _fuzz():
        try:
            rendered = uilts.convert_otsl_to_html(otsl)
        except Exception as exc:  # the reference's own IndexError, see the docstring
            cases.append({"otsl": otsl, "html": None,
                          "note": f"PaddleX raises {type(exc).__name__}; ours must"
                                  " still answer HTML"})
            continue
        cases.append({"otsl": otsl, "html": rendered, "note": "fuzz"})

    payload = {
        "source": "paddlex 3.7.2 paddlex/inference/pipelines/paddleocr_vl/"
                  "uilts.py::convert_otsl_to_html",
        "generator": "tools/ocr/make_otsl_golden.py",
        "cases": cases,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    print(f"{len(cases)} cases -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
