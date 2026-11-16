#!/usr/bin/env python3
"""Render the two-column page the reading-order criterion asks for.

The criterion is "prove a two-column page does not interleave". A real
two-column scan would do it, but then the expected order could only be asserted
as "whatever the model said", which proves nothing on the next run. So this page
is drawn instead, and the generator writes ``tests/data/ocr/twocolumn_truth.json``
with every line's text and box in the order a human reads it. The test compares
against *that*.

The geometry is measured, not chosen: three lines per column block with a 36 px
lead, a 180 px gutter and a 450 px column is what makes PP-DocLayout-M emit
**four separate body blocks and one cross-layout block** instead of a single
"text" region covering the whole page. Looser arrangements merge (the sweep is in
``docs/ocr.md``), which would leave the page unable to test anything.

The page therefore has exactly the properties the ordering code must get right:

* **A full-width title above the columns** -- detected as ``paragraph_title``, so
  the distance-insertion path is exercised rather than only the xy-cut.
* **Two column pairs**, each side a separate region. Two pairs mean a page-level
  left/right split cannot fake the result: the order has to be left-top,
  right-top, cross-layout, left-bottom, right-bottom.
* **A full-width paragraph between the pairs** -- the cross-layout case. Sorted
  by (y, x) it lands inside the left column and splits the second pair, so a page
  that *looks* ordered is wrong at exactly this line.
* **Three lines per column block**, so each region holds several OCR lines and
  the in-region line joining is exercised too.

Drawn at 2x and downsampled, like ``make_table_images.py``, so the glyphs
survive the detector's resize to 640x640.

    python3 tools/ocr/make_twocolumn_image.py --out tests/data/ocr/img
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

INK = (20, 20, 20)
PAGE_W, PAGE_H = 1240, 1754
SCALE = 2

#: Same candidate list as ``make_table_images.py``, so a difference between the
#: two images is never a difference of font.
FONT_CANDIDATES = [
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-DemiLight.ttc",
    "/usr/share/fonts/wenquanyi/wqy-zenhei/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]

#: Measured (see the module docstring): the tightest arrangement the layout
#: model still separates into four body blocks plus one cross-layout block.
MARGIN = 80
GUTTER = 180
COL_W = 450
FONT_SIZE = 24
TITLE_FONT_SIZE = 44
LEAD = 36
TITLE_Y = 130
BODY_TOP = 230
PARAGRAPH_GAP = 90

#: The page, as blocks. ``("title"|"full", [text, ...])`` is one full-width
#: region; ``("columns", [left...], [right...])`` is one row of the two-column
#: body -- its left and right halves become separate regions sharing a y range.
#:
#: The cross-layout paragraph sits *between* the column pairs on purpose: that is
#: the only arrangement where a naive (y, x) sort puts it inside the left column.
CONTENT: list[tuple] = [
    ("title", ["双栏排版阅读顺序测试页"]),
    ("columns",
     ["左栏第一段第一行的正文内容，用于验证分栏顺序",
      "左栏第一段第二行的正文内容，用于验证分栏顺序",
      "左栏第一段第三行的正文内容，用于验证分栏顺序"],
     ["右栏第一段第一行的正文内容，同样验证分栏顺序",
      "右栏第一段第二行的正文内容，同样验证分栏顺序",
      "右栏第一段第三行的正文内容，同样验证分栏顺序"]),
    ("full",
     ["通栏正文第一行，这一行横跨左右两栏的整个宽度，应排在两组栏位之间",
      "通栏正文第二行，同样横跨两栏的整个宽度，不应落进左栏或右栏里面"]),
    ("columns",
     ["左栏第二段第一行的正文内容，验证第二组栏位",
      "左栏第二段第二行的正文内容，验证第二组栏位",
      "左栏第二段第三行的正文内容，验证第二组栏位"],
     ["右栏第二段第一行的正文内容，验证第二组栏位",
      "右栏第二段第二行的正文内容，验证第二组栏位",
      "右栏第二段第三行的正文内容，验证第二组栏位"]),
]


def _font(size: int):
    from PIL import ImageFont

    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit("no CJK font found; install fonts-noto-cjk")


def layout() -> list[dict]:
    """Every drawn line's kind, text and box, in the order a human reads them.

    A ``columns`` row contributes its left block (all three lines) and *then* its
    right block -- which is exactly the order the feature has to reproduce, and
    exactly the order a (y, x) sort does not produce.
    """
    entries: list[dict] = []
    left_x = MARGIN
    right_x = MARGIN + COL_W + GUTTER
    full_width = COL_W * 2 + GUTTER
    y = BODY_TOP

    def add(kind, text, box, column=None):
        entries.append({"kind": kind, "text": text, "box": [int(v) for v in box],
                        "column": column})

    for item in CONTENT:
        kind = item[0]
        if kind == "title":
            add("title", item[1][0],
                [left_x, TITLE_Y, left_x + full_width, TITLE_Y + LEAD])
            continue
        if kind == "full":
            for offset, text in enumerate(item[1]):
                top = y + offset * LEAD
                add("full", text, [left_x, top, left_x + full_width,
                                   top + LEAD - 8])
            y += LEAD * len(item[1]) + PARAGRAPH_GAP
            continue
        lefts, rights = item[1], item[2]
        for offset, text in enumerate(lefts):
            top = y + offset * LEAD
            add("body", text, [left_x, top, left_x + COL_W, top + LEAD - 8], "left")
        for offset, text in enumerate(rights):
            top = y + offset * LEAD
            add("body", text, [right_x, top, right_x + COL_W, top + LEAD - 8],
                "right")
        y += LEAD * len(lefts) + PARAGRAPH_GAP
    return entries


def render(out_dir: Path) -> dict:
    from PIL import Image, ImageDraw

    entries = layout()
    image = Image.new("RGB", (PAGE_W * SCALE, PAGE_H * SCALE), "white")
    draw = ImageDraw.Draw(image)
    font = _font(FONT_SIZE * SCALE)
    title_font = _font(TITLE_FONT_SIZE * SCALE)
    for entry in entries:
        x1, y1, _x2, _y2 = entry["box"]
        use = title_font if entry["kind"] == "title" else font
        draw.text((x1 * SCALE, y1 * SCALE), entry["text"], fill=INK, font=use)

    image = image.resize((PAGE_W, PAGE_H), Image.LANCZOS)
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / "twocolumn.png"
    image.save(png, optimize=True)

    truth = {
        "image": png.name,
        "size": [PAGE_W, PAGE_H],
        "columns": {"left_x": MARGIN, "right_x": MARGIN + COL_W + GUTTER,
                    "width": COL_W, "gutter": GUTTER},
        "reading_order": [entry["text"] for entry in entries],
        "lines": entries,
    }
    (out_dir.parent / "twocolumn_truth.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    return truth


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("tests/data/ocr/img"),
                    help="directory the PNG goes in")
    args = ap.parse_args()
    truth = render(args.out)
    png = args.out / truth["image"]
    print(f"{png}: {png.stat().st_size} bytes, {len(truth['lines'])} lines")
    if png.stat().st_size > 300 * 1024:
        raise SystemExit(f"{png} exceeds the 300 KB budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
