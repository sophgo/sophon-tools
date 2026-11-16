#!/usr/bin/env python3
"""Render the two Chinese table images the acceptance criterion asks for.

The task requires at least two *new* Chinese table images, one of them with
merged cells, each ≤300 KB, in ``tests/data/ocr/img/``. They are generated
rather than sourced so they are reproducible and unambiguously licensed, and so
the merged-cell geometry is known exactly -- which is what makes them usable as
an assertion rather than decoration.

Everything is drawn at 2x and downsampled: at native size the 1 px grid lines
develop sub-pixel gaps that the detector then reads as two tables.

    python3 tools/ocr/make_table_images.py --out tests/data/ocr/img
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

FONT_CANDIDATES = [
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-DemiLight.ttc",
    "/usr/share/fonts/wenquanyi/wqy-zenhei/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]
SCALE = 2
INK = (25, 25, 25)
RULE = (60, 60, 60)


def _font(size: int):
    from PIL import ImageFont

    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit("no CJK font found; install fonts-noto-cjk")


def _grid(draw, x0, y0, col_w, row_h, rows, cols, spans, width):
    """Draw the ruling, leaving merged blocks open.

    The suppression test is *block identity*, not coordinates. An earlier
    version marked only the non-anchor cells of a block as "covered" and then
    asked whether the two cells a rule separates were both covered -- which is
    false at the block's own anchor, so every merged block kept a rule through
    it. That is exactly what left a vertical line crossing the header merge and
    an extra horizontal line inside the left-column merge.

    So: give every cell in a block the same block id, then skip a rule when the
    cells on both sides share an id. ``spans`` maps the block's top-left cell to
    ``(rowspan, colspan)``.
    """
    xs = [x0 + sum(col_w[:c]) for c in range(cols + 1)]
    ys = [y0 + row_h * r for r in range(rows + 1)]

    # block[r][c] = an id shared by every cell of the same merged block
    block = [[(r, c) for c in range(cols)] for r in range(rows)]
    for (r, c), (rs, cs) in spans.items():
        for rr in range(r, r + rs):
            for cc in range(c, c + cs):
                block[rr][cc] = (r, c)

    # Fill merged interiors white first: a rule belonging to a neighbouring row
    # or column can still reach into the block otherwise.
    for (r, c), (rs, cs) in spans.items():
        if rs * cs > 1:
            draw.rectangle(
                [xs[c] + width, ys[r] + width,
                 xs[c + cs] - width - 1, ys[r + rs] - width - 1], fill="white")

    # outer frame
    draw.rectangle([xs[0], ys[0], xs[-1], ys[-1]], outline=RULE, width=width)

    for c in range(1, cols):
        for r in range(rows):
            if block[r][c] == block[r][c - 1]:
                continue                      # same merged block: no rule
            draw.line([xs[c], ys[r], xs[c], ys[r + 1]], fill=RULE, width=width)
    for r in range(1, rows):
        for c in range(cols):
            if block[r][c] == block[r - 1][c]:
                continue                      # same merged block: no rule
            draw.line([xs[c], ys[r], xs[c + 1], ys[r]], fill=RULE, width=width)
    return xs, ys


def _cell_text(draw, xs, ys, r, c, text, font, spans):
    rs, cs = spans.get((r, c), (1, 1))
    x1, x2 = xs[c], xs[c + cs]
    y1, y2 = ys[r], ys[r + rs]
    box = draw.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    draw.text(((x1 + x2 - tw) / 2 - box[0], (y1 + y2 - th) / 2 - box[1]),
              text, font=font, fill=INK)


def _truth(col_w, row_h, rows, cols, spans, grid, x0=28, y0=62):
    """Ground truth in the *saved* image's pixel space.

    The canvas is drawn at ``SCALE`` and downsampled, so every coordinate is
    divided by ``SCALE`` on the way out. Returning 2x coordinates would put the
    truth boxes outside the image and silently make every comparison fail to
    overlap -- the sort of mismatch that reads as "the model is wrong".
    """
    """The ground truth for one table, in the same shape the tests compare.

    ``grid`` is ``(text, row, col, rowspan, colspan)`` for every *logical* cell,
    which is the only description that distinguishes "5 columns with two merged
    blocks" from "5 rows of 3 cells". Recording it here rather than in the test
    keeps the truth next to the code that drew the pixels -- a test that
    restated the layout could drift from the image just as easily as the
    detector can.

    Coordinates are in the *saved* image's pixel space (the canvas is drawn at
    ``SCALE`` then downsampled, so everything is divided by ``SCALE``).
    """
    xs = [(x0 + sum(col_w[:c])) / SCALE for c in range(cols + 1)]
    ys = [(y0 + row_h * r) / SCALE for r in range(rows + 1)]
    cells = []
    for text, r, c, rs, cs in grid:
        cells.append({
            "text": text,
            "row": r, "col": c, "rowspan": rs, "colspan": cs,
            "box": [round(xs[c], 1), round(ys[r], 1),
                    round(xs[c + cs], 1), round(ys[r + rs], 1)],
        })
    return {
        "rows": rows, "cols": cols, "spans": {f"{r},{c}": [rs, cs]
                                              for (r, c), (rs, cs) in spans.items()},
        "cells": cells,
        "col_edges": [round(v, 1) for v in xs],
        "row_edges": [round(v, 1) for v in ys],
    }


def make_merged(out: Path) -> Path:
    """Chinese table with a 2x2 merged header cell and a 3-row merged side cell."""
    from PIL import Image, ImageDraw

    W, H = 760, 396
    img = Image.new("RGB", (W * SCALE, H * SCALE), "white")
    d = ImageDraw.Draw(img)
    title = _font(26 * SCALE)
    body = _font(19 * SCALE)

    d.text((28 * SCALE, 16 * SCALE), "2026 年第三季度设备巡检记录", font=title, fill=INK)

    # 5 rows total: one header row, three data rows, one totals row. The
    # header merges 2 columns; the left column merges the last 3 rows.
    cols, rows = 5, 5
    col_w = [150, 120, 120, 150, 150]
    row_h = 52 * SCALE
    x0, y0 = 28 * SCALE, 62 * SCALE
    spans = {(0, 0): (1, 2), (2, 0): (3, 1)}
    xs, ys = _grid(d, x0, y0, [w * SCALE for w in col_w], row_h, rows, cols,
                   spans, 2 * SCALE)

    _cell_text(d, xs, ys, 0, 0, "区域 / 设备", body, spans)
    _cell_text(d, xs, ys, 0, 2, "巡检日期", body, spans)
    _cell_text(d, xs, ys, 0, 3, "状态", body, spans)
    _cell_text(d, xs, ys, 0, 4, "负责人", body, spans)
    _cell_text(d, xs, ys, 1, 0, "二号机房", body, spans)
    _cell_text(d, xs, ys, 1, 1, "服务器 D", body, spans)
    _cell_text(d, xs, ys, 1, 2, "2026-06-30", body, spans)
    _cell_text(d, xs, ys, 1, 3, "正常", body, spans)
    _cell_text(d, xs, ys, 1, 4, "赵敏", body, spans)
    _cell_text(d, xs, ys, 2, 0, "一号机房", body, spans)

    data = [
        ("2026-07-12", "正常", "张伟"),
        ("2026-08-09", "告警", "李娜"),
        ("2026-09-15", "正常", "王强"),
    ]
    for i, (dt, st, who) in enumerate(data):
        r = 2 + i
        _cell_text(d, xs, ys, r, 1, ("服务器 A", "服务器 B", "服务器 C")[i],
                   body, spans)
        _cell_text(d, xs, ys, r, 2, dt, body, spans)
        _cell_text(d, xs, ys, r, 3, st, body, spans)
        _cell_text(d, xs, ys, r, 4, who, body, spans)
    d.text((28 * SCALE, (H - 34) * SCALE), "备注：告警项已复检完毕。", font=body, fill=INK)

    img = img.resize((W, H), Image.LANCZOS)
    path = out / "cn_table_merged.png"
    img.save(path, optimize=True)
    return path, _truth(col_w, row_h, rows, cols, spans, grid=(
        ("区域 / 设备", 0, 0, 1, 2), ("巡检日期", 0, 2, 1, 1),
        ("状态", 0, 3, 1, 1), ("负责人", 0, 4, 1, 1),
        ("二号机房", 1, 0, 1, 1), ("服务器 D", 1, 1, 1, 1),
        ("2026-06-30", 1, 2, 1, 1), ("正常", 1, 3, 1, 1), ("赵敏", 1, 4, 1, 1),
        ("一号机房", 2, 0, 3, 1),
        ("服务器 A", 2, 1, 1, 1), ("2026-07-12", 2, 2, 1, 1),
        ("正常", 2, 3, 1, 1), ("张伟", 2, 4, 1, 1),
        ("服务器 B", 3, 1, 1, 1), ("2026-08-09", 3, 2, 1, 1),
        ("告警", 3, 3, 1, 1), ("李娜", 3, 4, 1, 1),
        ("服务器 C", 4, 1, 1, 1), ("2026-09-15", 4, 2, 1, 1),
        ("正常", 4, 3, 1, 1), ("王强", 4, 4, 1, 1),
    ))


def make_plain(out: Path) -> Path:
    """Plain 4x5 Chinese table, no merges -- the contrast case."""
    from PIL import Image, ImageDraw

    W, H = 700, 400
    img = Image.new("RGB", (W * SCALE, H * SCALE), "white")
    d = ImageDraw.Draw(img)
    title = _font(25 * SCALE)
    body = _font(18 * SCALE)

    d.text((26 * SCALE, 14 * SCALE), "物料入库明细表", font=title, fill=INK)

    cols, rows = 5, 5
    col_w = [70, 190, 110, 110, 120]
    row_h = 48 * SCALE
    xs, ys = _grid(d, 26 * SCALE, 58 * SCALE, [w * SCALE for w in col_w],
                   row_h, rows, cols, {}, 2 * SCALE)

    header = ["序号", "物料名称", "数量", "单位", "存放位置"]
    for c, t in enumerate(header):
        _cell_text(d, xs, ys, 0, c, t, body, {})
    rows_data = [
        ("1", "不锈钢螺栓 M8", "1200", "个", "A 区 3 号架"),
        ("2", "密封圈 45mm", "860", "个", "B 区 1 号架"),
        ("3", "轴承 6204", "340", "套", "A 区 2 号架"),
        ("4", "润滑油 2L", "48", "桶", "C 区 4 号架"),
    ]
    for r, row in enumerate(rows_data, start=1):
        for c, t in enumerate(row):
            _cell_text(d, xs, ys, r, c, t, body, {})

    img = img.resize((W, H), Image.LANCZOS)
    path = out / "cn_table_simple.png"
    img.save(path, optimize=True)
    grid = [(t, 0, c, 1, 1) for c, t in enumerate(header)]
    for r, row in enumerate(rows_data, start=1):
        grid += [(t, r, c, 1, 1) for c, t in enumerate(row)]
    return path, _truth(col_w, row_h, rows, cols, {}, grid=grid)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tests/data/ocr/img", type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    truths = {}
    for fn in (make_merged, make_plain):
        p, truth = fn(args.out)
        truths[p.name] = truth
        kb = p.stat().st_size / 1024
        print(f"{p.name}: {p.stat().st_size} bytes ({kb:.1f} KB), "
              f"{len(truth['cells'])} truth cells"
              f"{'  OVER 300 KB' if kb > 300 else ''}")
    # Written beside the images so the comparison can load it without the
    # generator (the board has no PIL).
    tpath = args.out.parent / "table_truth.json"
    tpath.write_text(json.dumps(truths, ensure_ascii=False, indent=1))
    print(f"wrote {tpath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
