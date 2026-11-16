#!/usr/bin/env python3
"""Whole-page prototype: layout -> per-table SLANet -> PP-OCR cells -> Markdown.

This is the deliverable the card asks for: a page image in, Markdown out, with
the three models wired the way an integration would wire them. It is a
**prototype**, not the service: it imports the existing PP-OCR pieces from
``app/engine/ocr_ppocr.py`` (the same code ``/v1/ocr`` runs) rather than
duplicating them, and it drives the three structure bmodels through the same
ctypes bmrt helper the acceptance runs use.

    # on the board, with the four bmodels + the PP-OCR config
    python3 tools/ocr/structure_page.py page.png \\
        --layout /data/structure/dlS_f16_480_bm1684x2_static.bmodel \\
        --table  /data/structure/slanet_plus_f16_488_bm1684x2_static_64.bmodel \\
        --ppocr-model-dir /data/ocr-test/models/ppocrv6-medium \\
        --ppocr-config model-config/ppocr_v6 --out page.md

Design decisions worth knowing, because they are the ones an integration would
have to revisit:

* **Reading order comes from the layout model, not from PP-OCR's box sorter.**
  The layout detector already returns document order; re-sorting its regions by
  PP-OCR's line heuristic would scramble a two-column page.
* **Each table region is recognised twice**: once by SLANet for the structure
  and once cell-by-cell by PP-OCR. The two are joined by matching each cell
  box SLANet emits to the OCR lines that fall inside it. A cell whose text
  cannot be cropped precisely keeps an empty string -- the prototype does not
  guess.
* **Markdown when the structure is expressible, HTML when it is not.** A table
  with rowspan/colspan has no Markdown form, so those are emitted as HTML
  (GFM renders it). This is the rule the card states, and
  ``is_markdown_expressible`` is the single place that decides it.
* Per-stage timings are accumulated, because the card asks for where a page's
  time goes, and a single total cannot answer that.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout_postprocess as post  # noqa: E402
import table_postprocess as tables  # noqa: E402

#: Labels whose regions become a table in the output.
TABLE_LABELS = {"table"}

#: Labels that are page furniture: emitted, but never recognised as text.
SKIP_TEXT_LABELS = {"header", "footer", "header_image", "footer_image"}


class Stage:
    """Accumulates per-stage wall time so a page's cost can be attributed."""

    def __init__(self):
        self.ms: dict[str, float] = {}
        self.calls: dict[str, int] = {}

    def add(self, name: str, ms: float) -> None:
        self.ms[name] = self.ms.get(name, 0.0) + ms
        self.calls[name] = self.calls.get(name, 0) + 1

    def report(self) -> dict:
        return {k: {"ms": round(v, 1), "calls": self.calls[k]}
                for k, v in self.ms.items()}


def _clip(box, page):
    """Clamp a region to the page and pad slightly.

    The layout model's boxes are tight; a table's outer rule sits *on* the
    boundary, so a one-pixel pad keeps it inside the crop instead of being cut
    into a border line SLANet then reads as an extra row.
    """
    x1, y1, x2, y2 = box
    h, w = page
    pad = 2
    return (max(0, int(x1) - pad), max(0, int(y1) - pad),
            min(w, int(x2) + pad), min(h, int(y2) + pad))


def is_markdown_expressible(html: str) -> bool:
    """Does this table have a faithful Markdown form?

    Markdown pipe tables cannot express a cell spanning rows or columns, so any
    ``rowspan``/``colspan`` at all forces HTML. Nested tables (a table inside a
    ``<td>``) also force it, since GFM has no nested-table syntax.
    """
    if "rowspan" in html or "colspan" in html:
        return False
    # two opening <table> tags means a nested table
    return html.count("<table") <= 1


def html_to_markdown(html: str) -> str:
    """``<table>`` -> GFM pipe table, for the expressible case only."""
    import re

    rows = re.findall(r"<tr>(.*?)</tr>", html, re.S)
    parsed = []
    for row in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        parsed.append([re.sub(r"<[^>]+>", "", c).strip() for c in cells])
    if not parsed:
        return ""
    width = max(len(r) for r in parsed)
    parsed = [r + [""] * (width - len(r)) for r in parsed]
    out = ["| " + " | ".join(parsed[0]) + " |",
           "| " + " | ".join(["---"] * width) + " |"]
    for r in parsed[1:]:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def reading_order(blocks, line_height=20, line_width=20):
    """Order layout regions for reading, as PaddleX does.

    A transcription of ``sort_normal_blocks`` from PaddleX's
    ``layout_parsing/xycut_enhanced/utils.py``. PaddleX does *not* trust the
    detector's own order: it re-sorts every block by quantised row then column,
    which is what makes a single-column page come out top-to-bottom. The
    detector's emitted order on ``cn_notice.png`` is scrambled (it put the
    footer paragraph first and the title last), so without this the page reads
    backwards.

    ``xycut_enhanced`` proper also handles multi-column cuts, nested regions and
    header/footer pinning; that is a much larger piece of machinery and this
    prototype only needs the single-column case. The limitation is stated in
    the report rather than papered over: a two-column page will interleave.

    The quantisation is deliberate -- dividing by an estimated line height
    keeps blocks that sit on the same visual line together, so a heading and a
    paragraph beside it stay in left-to-right order instead of being split by a
    few pixels of vertical offset.
    """
    def key(b):
        x1, y1, x2, y2 = b["box"]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        return (y1 // line_height, x1 // line_width, cx * cx + cy * cy)

    return sorted(blocks, key=key)


def _distance(box_1, box_2):
    """PaddleX ``distance``: L1 on both corner pairs, plus the nearer one twice."""
    x1, y1, x2, y2 = box_1
    x3, y3, x4, y4 = box_2
    dis = abs(x3 - x1) + abs(y3 - y1) + abs(x4 - x2) + abs(y4 - y2)
    dis_2 = abs(x3 - x1) + abs(y3 - y1)
    dis_3 = abs(x4 - x2) + abs(y4 - y2)
    return dis + min(dis_2, dis_3)


def _compute_iou(rec1, rec2):
    """PaddleX ``compute_iou`` -- note it returns 0 on a degenerate overlap."""
    S_rec1 = (rec1[2] - rec1[0]) * (rec1[3] - rec1[1])
    S_rec2 = (rec2[2] - rec2[0]) * (rec2[3] - rec2[1])
    sum_area = S_rec1 + S_rec2
    left_line = max(rec1[0], rec2[0])
    right_line = min(rec1[2], rec2[2])
    top_line = max(rec1[1], rec2[1])
    bottom_line = min(rec1[3], rec2[3])
    if left_line >= right_line or top_line >= bottom_line:
        return 0.0
    intersect = (right_line - left_line) * (bottom_line - top_line)
    return (intersect / (sum_area - intersect)) * 1.0


class StructurePage:
    """The three-model pipeline. Engines are injected so this stays testable."""

    def __init__(self, layout_run, table_run, ocr_recognise, chars,
                 layout_labels=None, layout_side=480, merge_mode=None):
        self._layout_run = layout_run        # callable(np.ndarray) -> (boxes, scores)
        self._table_run = table_run          # callable(np.ndarray) -> (bbox, struct)
        self._ocr = ocr_recognise            # callable(bgr) -> [(text, score, box)]
        self._chars = chars
        self._labels = layout_labels or post.load_labels()
        self._side = layout_side
        self._merge = merge_mode if merge_mode is not None else \
            post.MERGE_MODE_STRUCTURE_V3
        self.stage = Stage()

    # -- layout ---------------------------------------------------------
    def regions(self, bgr):
        import cv2

        h, w = bgr.shape[:2]
        side = self._side
        x = cv2.resize(bgr, (side, side), interpolation=cv2.INTER_LINEAR)
        x = cv2.cvtColor(x, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / \
            np.array([0.229, 0.224, 0.225], np.float32)
        x = np.ascontiguousarray(x.transpose(2, 0, 1)[None])
        sf = np.array([side / h, side / w], np.float32)

        t0 = time.perf_counter()
        raw_boxes, raw_scores = self._layout_run(x)
        self.stage.add("layout", (time.perf_counter() - t0) * 1000)
        boxes = post.rescale_boxes(raw_boxes.reshape(-1, 4), sf)
        return post.det_postprocess(boxes[None], raw_scores, (h, w),
                                    labels=self._labels, merge_mode=self._merge)

    # -- table ----------------------------------------------------------
    def table(self, crop):
        x, padded, ori = tables.preprocess(crop)
        t0 = time.perf_counter()
        bbox_pred, struct_pred = self._table_run(x)
        self.stage.add("table_structure", (time.perf_counter() - t0) * 1000)
        return tables.decode(struct_pred[0], bbox_pred[0], self._chars,
                             padded, ori)

    # -- text -----------------------------------------------------------
    def text(self, crop):
        t0 = time.perf_counter()
        lines = self._ocr(crop)
        self.stage.add("ocr", (time.perf_counter() - t0) * 1000)
        return lines

    def fill_cells(self, crop, cells, lines):
        """Attach OCR lines to SLANet's cell boxes, the way PaddleX does.

        Transcribed from ``paddlex/inference/pipelines/table_recognition/
        table_recognition_post_processing.py`` (``match_table_and_ocr``):

            for each OCR box, score every cell by
                (1 - IoU, distance)          # distance = L1 on both corners
            and take the cell that sorts first by (1-IoU, distance).

        Two things about it matter and are easy to get wrong:

        * **Every OCR line is assigned to some cell.** There is no
          "centre not inside any cell -> drop it" step. An earlier version of
          this function did exactly that and silently lost text (review caught
          it); PaddleX instead lets each line fall to its nearest cell, so a
          line whose box sits slightly outside a cell still lands somewhere
          rather than vanishing.
        * **The comparison is box-to-box, not point-in-polygon.** A tall merged
          cell overlaps its children's lines more than they overlap it only
          once IoU is considered, which is why IoU comes first and the L1
          distance only breaks ties.

        Multiple lines in one cell are concatenated in the order they arrive,
        matching PaddleX's ``"".join`` of the matched indices.
        """
        if not cells:
            return []
        import numpy as np

        cell_boxes = [np.array([c[0], c[1], c[4], c[5]], np.float32)
                      for c in cells]
        # SLANet emits 8-point polygons; PaddleX's matcher works on the
        # axis-aligned pair of corners (left, top, right, bottom).
        filled = [""] * len(cell_boxes)

        for text, _score, line_box in lines:
            xs = [p[0] for p in line_box]
            ys = [p[1] for p in line_box]
            ocr_box = np.array([min(xs), min(ys), max(xs), max(ys)], np.float32)

            best_cell, best_key = -1, None
            for j, cell_box in enumerate(cell_boxes):
                key = (1.0 - _compute_iou(cell_box, ocr_box),
                       _distance(cell_box, ocr_box))
                if best_key is None or key < best_key:
                    best_cell, best_key = j, key

            if best_cell < 0:
                continue
            joined = (filled[best_cell] + " " + text).strip() if filled[best_cell] else text
            filled[best_cell] = joined
        return filled

    def run(self, bgr) -> dict:
        h, w = bgr.shape[:2]
        regions = self.regions(bgr)
        blocks = []
        for r in regions:
            label = r["label"]
            x1, y1, x2, y2 = _clip(r["coordinate"], (h, w))
            if x2 - x1 < 8 or y2 - y1 < 8:
                continue
            crop = bgr[y1:y2, x1:x2]
            if label in TABLE_LABELS:
                html, cells, score = self.table(crop)
                lines = self.text(crop)
                filled = self.fill_cells(crop, cells, lines)
                blocks.append({
                    "kind": "table", "label": label, "box": [x1, y1, x2, y2],
                    "html": self._inject_text(html, filled),
                    "cells": len(cells), "cell_text": filled,
                    "structure_score": round(score, 4),
                })
            elif label in SKIP_TEXT_LABELS:
                blocks.append({"kind": "skip", "label": label,
                               "box": [x1, y1, x2, y2]})
            else:
                lines = self.text(crop)
                blocks.append({
                    "kind": "text", "label": label, "box": [x1, y1, x2, y2],
                    "text": "\n".join(t for t, _s, _b in lines),
                })
        blocks = reading_order(blocks)
        return {"page_hw": [h, w], "blocks": blocks, "stage": self.stage.report()}

    @staticmethod
    def _inject_text(html: str, filled) -> str:
        """Put the recognised text into the empty ``<td>`` slots, in order."""
        import re

        parts = re.split(r"(<td[^>]*>)", html)
        out, k = [], 0
        for piece in parts:
            out.append(piece)
            if piece.startswith("<td"):
                # the text goes immediately after the opening tag
                if k < len(filled) and filled[k]:
                    out.append(filled[k])
                k += 1
        return "".join(out)


def to_markdown(page: dict) -> str:
    """Blocks -> Markdown, in layout order."""
    out = []
    for b in page["blocks"]:
        if b["kind"] == "skip":
            continue
        if b["kind"] == "text":
            if b["text"].strip():
                out.append(b["text"].strip())
        elif b["kind"] == "table":
            if is_markdown_expressible(b["html"]):
                out.append(html_to_markdown(b["html"]))
            else:
                out.append(b["html"])
    return "\n\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# board wiring
# ---------------------------------------------------------------------------

def ppocr_engine(model_dir: Path, config_dir: Path, npu_py: Path,
                 det_model: Path | None = None):
    """A PP-OCR det+rec callable built from the service's own helpers.

    Reuses ``app/engine/ocr_ppocr.py``'s preprocessing, DB post-processing and
    CTC decode -- the code ``/v1/ocr`` runs -- so the page prototype's text is
    the product's text, not a second implementation that could drift. Only the
    inference call is substituted: it goes through ``board_npu.py`` instead of
    the native engine, because the prototype must not need the library built.

    The engine reads the bmodels that already sit in ``model_dir``; it does not
    require all three rec tiers the service insists on, because a prototype
    page only ever exercises the tiers its crops need.
    """
    import cv2
    import subprocess
    import tempfile

    # The service's own helpers, imported lazily: ``app.engine.ocr_ppocr``
    # pulls in the native tokenizer/backend modules, which this prototype does
    # not need and which would otherwise have to be shipped to the board as a
    # package tree. The four functions used here are pure -- numpy + opencv +
    # pyclipper -- so importing the module that holds them is the only way to
    # avoid duplicating them.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from app.engine.ocr_ppocr import (  # noqa: E402
        crop_quad, ctc_decode, det_input, det_postprocess, load_config,
        reading_order, rec_input, rec_width_for,
    )

    cfg = load_config(config_dir)
    det_path = det_model or _find(model_dir, "det")

    def run(path: Path, name: str, array: np.ndarray):
        with tempfile.TemporaryDirectory() as td:
            inp, outp = Path(td) / "i.npy", Path(td) / "o.npz"
            np.save(inp, array)
            proc = subprocess.run(
                [sys.executable, str(npu_py), "--bmodel", str(path),
                 "--input", f"{name}={inp}", "--out", str(outp)],
                capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError(f"board_npu({path.name}): {proc.stderr[-300:]}")
            d = np.load(outp)
            return d[d.files[0]]

    def recognise(bgr):
        det_in, shape = det_input(bgr, cfg)
        prob = run(det_path, _graph_io(det_path, npu_py)["inputs"][0]["name"],
                   det_in)
        while prob.ndim > 2:
            prob = prob[0]
        boxes, _scores = det_postprocess(prob, shape, cfg)
        lines = []
        for box in boxes:
            crop = crop_quad(bgr, box)
            if crop is None:
                continue
            h, w = crop.shape[:2]
            width = rec_width_for(h, w, cfg)
            rec_path = _find(model_dir, f"rec{width}")
            out = run(rec_path, "x", rec_input(crop, width, cfg))
            text, score = ctc_decode(out[0], cfg.labels)
            if not text:
                continue
            lines.append((text, score, [(float(x), float(y)) for x, y in box]))
        order = reading_order([l[2] for l in lines])
        return [lines[i] for i in order]

    return recognise


def _find(model_dir: Path, kind: str) -> Path:
    """Locate a bmodel by tier: 'det', 'rec320', 'rec640', 'rec1600'."""
    hits = []
    for p in sorted(model_dir.glob("*.bmodel")):
        n = p.name
        if kind == "det" and "-det_" in n:
            hits.append(p)
        elif kind.startswith("rec") and f"rec_f16_48x{kind[3:]}_" in n:
            hits.append(p)
    if len(hits) != 1:
        raise SystemExit(f"expected one {kind} bmodel in {model_dir}, found "
                         f"{[h.name for h in hits]}")
    return hits[0]


_WARMED: set[str] = set()


def _warmup(npu_py: Path, bmodel: Path, name: str, dims: tuple) -> bool:
    """Spend the first-launch-after-boot zero result on a throwaway input."""
    import subprocess
    import tempfile

    if str(bmodel) in _WARMED:
        return True
    _WARMED.add(str(bmodel))
    with tempfile.TemporaryDirectory() as td:
        inp = Path(td) / "w.npy"
        outp = Path(td) / "w.npz"
        np.save(inp, np.zeros(dims, np.float32))
        proc = subprocess.run(
            [sys.executable, str(npu_py), "--bmodel", str(bmodel),
             "--input", f"{name}={inp}", "--out", str(outp)],
            capture_output=True, text=True)
        return proc.returncode == 0


def _graph_io(bmodel: Path, npu_py: Path):
    """The bmodel's tensor table, read once.

    One ``--json`` probe per model, not one per question: each probe is a full
    ``bmrt_load_bmodel``, and repeated loads have been observed to leave the
    device in a state where the *next* real launch returns zeros.
    """
    import subprocess
    proc = subprocess.run([sys.executable, str(npu_py), "--bmodel", str(bmodel),
                           "--json"], capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)[0]
    except Exception:
        return None


def _bmrt_runner(bmodel: Path, npu_py: Path):
    """A ``callable(np.ndarray) -> list[np.ndarray]`` for one bmodel.

    Goes through ``board_npu.py`` as a subprocess so this prototype does not
    grow a second copy of the ctypes bindings. One process per launch is
    honest about the cost: it is what a per-element pipeline would pay unless
    the backend keeps the graph resident, which is exactly the integration
    question the report has to answer.
    """
    import subprocess
    import tempfile

    # The graph's own input name, read once from the bmodel rather than guessed
    # from the tensor's size: the layout and table graphs use different names,
    # and a heuristic on shape breaks the moment a model has a 488 input for
    # another reason (which is exactly what happened here).
    meta = _graph_io(bmodel, npu_py)
    name = meta["inputs"][0]["name"] if meta else "image"

    # **The first launch of a freshly-booted board returns zeros.** Measured on
    # `.157`: launch 0 after a clean boot -> scores all 0.0, launches 1..2 ->
    # 0.891, stable. It is not a warm-up cache effect that a second launch in
    # the same process would fix -- each launch here is a new process, so the
    # first one to touch the NPU pays it. A page pipeline would show an empty
    # first page, so this is a real integration constraint, not a test artifact.
    # One throwaway launch below absorbs it.
    if meta:
        _warmup(npu_py, bmodel, name, tuple(meta["inputs"][0]["dims"]))

    def run(array: np.ndarray):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.npy"
            outp = Path(td) / "out.npz"
            np.save(inp, array)
            proc = subprocess.run(
                [sys.executable, str(npu_py), "--bmodel", str(bmodel),
                 "--input", f"{name}={inp}", "--out", str(outp)],
                capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError(f"board_npu failed: {proc.stderr[-400:]}")
            d = np.load(outp)
            return [d[k] for k in d.files]
    return run


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", type=Path)
    ap.add_argument("--layout", required=True, type=Path)
    ap.add_argument("--table", required=True, type=Path)
    ap.add_argument("--table-yml", required=True, type=Path,
                    help="SLANet inference.yml (for the character dictionary)")
    ap.add_argument("--ppocr-model-dir", type=Path, default=None,
                    help="PP-OCRv6 model dir; omit to skip text recognition")
    ap.add_argument("--ppocr-config", type=Path, default=None)
    ap.add_argument("--board-npu", type=Path, default=Path("board_npu.py"))
    ap.add_argument("--layout-side", type=int, default=480)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    import cv2

    chars = tables.load_chars(args.table_yml)
    layout_run = _bmrt_runner(args.layout, args.board_npu)
    table_run = _bmrt_runner(args.table, args.board_npu)

    if args.ppocr_model_dir:
        ocr = ppocr_engine(args.ppocr_model_dir, args.ppocr_config,
                           args.board_npu)
    else:
        def ocr(_bgr):
            return []

    pipe = StructurePage(layout_run, table_run, ocr, chars,
                         layout_side=args.layout_side)
    bgr = cv2.imread(str(args.image))
    if bgr is None:
        raise SystemExit(f"cannot read {args.image}")
    page = pipe.run(bgr)
    md = to_markdown(page)
    print(md)
    print("--- stage times (ms) ---", file=sys.stderr)
    for k, v in page["stage"].items():
        print(f"  {k:16s} {v['ms']:8.1f}  x{v['calls']}", file=sys.stderr)
    if args.out:
        args.out.write_text(md)
    if args.json:
        args.json.write_text(json.dumps(page, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
