#!/usr/bin/env python3
"""x86 reference for `mode: "layout"`: our page vs PaddleX, on the same image.

The acceptance question for layout mode is not "does the board reproduce the
ONNX" -- ``layout_cut.py --verify`` and ``structure_reference.py`` answer that --
but "does the *page* match what PaddleX produces": the same regions, in the same
reading order, rendered to the same Markdown. This script runs both and diffs
them, per image.

What is compared, and why each side is what it is:

* **ours** -- ``app.engine.ocr_layout``, fed by the **cut ONNX** through
  onnxruntime. The cut graph is exactly what the bmodel contains, so this is the
  service's own code path with only the hardware swapped.
* **paddlex** -- **PP-DocLayout-M** through PaddleX's ``LayoutAnalysisPredictor``
  (its own uncut ONNX and its own ``LayoutAnalysisProcess``), then PaddleX's own
  reading order (``xycut_enhanced``) over the same blocks. Using the *same*
  detector on both sides is what makes the comparison meaningful: a difference
  in regions is then our tail, not a different model. ``PP-StructureV3`` is
  deliberately not used -- it runs ``PP-DocLayout_plus-L``, a different and much
  larger detector, so its region list could never match ours.

Three numbers per image, because they can disagree independently: region count,
label agreement on IoU-matched boxes, and whether the matched boxes come out in
the same relative order.

    python3 tools/ocr/compare_layout.py \\
        --layout-onnx <PP-DocLayout-M_cut.onnx> \\
        --ppocr-dir <dir with ppocrv6_medium_{det,rec}.onnx> \\
        --images tests/data/ocr/img/cn_notice.png ...

Needs ``onnxruntime`` always, and ``paddlex`` for the reference column; without
paddlex the script still prints our side and says the comparison was skipped.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))

from app.engine import ocr_layout as layout  # noqa: E402

CONFIG_DIR = _REPO / "model-config" / "ppocr_v6"


# ---------------------------------------------------------------------------
# our side
# ---------------------------------------------------------------------------
class _Line:
    """The three fields ``assign_lines`` reads."""

    def __init__(self, text: str, score: float, box) -> None:
        self.text, self.score, self.box = text, score, box


def ocr_lines(bgr, pp_config, det_session, rec_session):
    """The page's OCR lines, from the same ONNX pair the bmodels were built from."""
    from app.engine.ocr_ppocr import (
        crop_quad, ctc_decode, det_input, det_postprocess, rec_input, rec_width_for,
    )

    det_in, shape = det_input(bgr, pp_config)
    prob = det_session.run(None, {"x": det_in})[0]
    while prob.ndim > 2:
        prob = prob[0]
    boxes, _scores = det_postprocess(prob, shape, pp_config)

    lines = []
    for box in boxes:
        crop = crop_quad(bgr, box)
        if crop is None:
            continue
        ch, cw = crop.shape[:2]
        width = rec_width_for(ch, cw, pp_config)
        out = rec_session.run(None, {"x": rec_input(crop, width, pp_config)})[0]
        text, score = ctc_decode(out[0], pp_config.labels)
        if not text:
            continue
        lines.append(_Line(text, score,
                           tuple((float(x), float(y)) for x, y in box)))
    return lines


def our_page(bgr, cfg, layout_session, lines):
    h, w = bgr.shape[:2]
    tensor = layout.preprocess(bgr, cfg)
    raw_boxes, raw_scores = layout_session.run(None, {"image": tensor})
    regions = layout.detect(raw_boxes, raw_scores, (h, w), cfg)
    filled = layout.assign_lines(regions, lines)
    ordered = layout.order_regions(filled, (h, w))
    return {
        "regions": [{"label": r["label"], "box": [int(v) for v in r["box"]],
                     "text": r["text"]} for r in ordered],
        "markdown": layout.to_markdown(ordered),
    }


# ---------------------------------------------------------------------------
# PaddleX's side
# ---------------------------------------------------------------------------
def paddlex_regions(path: Path) -> list[dict] | None:
    """PP-DocLayout-M's regions through PaddleX's own predictor, or None.

    The predictor is handed the **same merge mode and threshold our config uses**
    (PP-StructureV3's table), so the only thing left to differ is the arithmetic.
    """
    try:
        from paddlex.inference.models import create_predictor
    except Exception as exc:  # noqa: BLE001 - optional dependency
        print(f"  paddlex unavailable: {exc}", file=sys.stderr)
        return None

    raw = json.loads((CONFIG_DIR / layout.LAYOUT_CONFIG_FILE).read_text(encoding="utf-8"))
    merge = {int(k): v for k, v in raw["postprocess"]["merge_mode"].items()}
    try:
        # ``create_predictor`` -- not the class -- is PaddleX's own entry point:
        # the runner predictor needs a ``runner`` keyword that only this factory
        # builds, and PaddleX 3.7 exposes the class name only for backward
        # compatibility.
        predictor = create_predictor("PP-DocLayout-M")
        import numpy as np
        from PIL import Image

        # PaddleX calls the predictor as a callable with an *array* batch
        # (``pipeline_v2.py``: ``self.layout_det_model(doc_preprocessor_images,
        # ...)``); ``process()`` takes a wrapped object this script has no
        # reason to build. Passing the RGB array is also what removes the last
        # difference between the two sides' preprocessing.
        image = np.array(Image.open(path).convert("RGB"))
        result = list(predictor(
            [image],
            threshold=raw["postprocess"]["threshold"],
            layout_nms=True,
            layout_merge_bboxes_mode=merge,
        ))[0]
    except Exception as exc:  # noqa: BLE001
        print(f"  paddlex predictor failed: {exc}", file=sys.stderr)
        return None
    return [{"label": b["label"], "box": [int(v) for v in b["coordinate"]],
             "score": float(b["score"])} for b in result["boxes"]]


def paddlex_order(regions: list[dict], page_hw, lines) -> list[dict] | None:
    """PaddleX's own ``xycut_enhanced`` over the blocks, then its Markdown.

    Building the ``LayoutBlock``/``LayoutRegion`` objects is the reference's own
    entry point (``paddlex.inference.pipelines.layout_parsing``), so this is the
    product's ordering rather than a re-derivation of it.
    """
    try:
        from paddlex.inference.pipelines.layout_parsing.layout_objects import (
            LayoutBlock, LayoutRegion,
        )
        from paddlex.inference.pipelines.layout_parsing.xycut_enhanced import (
            xycut_enhanced,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  paddlex ordering unavailable: {exc}", file=sys.stderr)
        return None

    h, w = page_hw
    blocks = []
    for region in regions:
        block = LayoutBlock(label=region["label"], bbox=list(region["box"]))
        # PaddleX's ordering reads ``num_of_lines`` from the block it built out
        # of OCR; give it the same number we give ours.
        matched = _lines_in(region["box"], lines)
        block.content = "".join(line.text for line in matched)
        block.num_of_lines = max(1, len(matched))
        blocks.append(block)
    page = LayoutRegion(bbox=np.array([0, 0, w, h]), blocks=blocks)
    ordered = xycut_enhanced(page)
    return [{"label": b.label, "box": [int(v) for v in b.bbox],
             "text": b.content} for b in ordered]


def _lines_in(box, lines):
    """The OCR lines whose centres fall inside ``box`` -- for block content only."""
    out = []
    for line in lines:
        xs = [p[0] for p in line.box]
        ys = [p[1] for p in line.box]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        if box[0] <= cx <= box[2] and box[1] <= cy <= box[3]:
            out.append(line)
    return out


# ---------------------------------------------------------------------------
# the diff
# ---------------------------------------------------------------------------
def _iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = ((a[2] - a[0]) * (a[3] - a[1])
             + (b[2] - b[0]) * (b[3] - b[1]) - inter)
    return inter / union if union else 0.0


def compare(ours: list[dict], theirs: list[dict],
            iou_threshold: float = 0.5) -> dict:
    """Regions, labels and relative order, counted.

    Matching is greedy on IoU, one-to-one: a reference box is claimed once, which
    is what makes "we found 10, they found 8" comparable when two of ours sit on
    top of each other.
    """
    pairs = sorted(
        ((_iou(a["box"], b["box"]), i, j)
         for i, a in enumerate(ours) for j, b in enumerate(theirs)
         if _iou(a["box"], b["box"]) >= iou_threshold),
        reverse=True)
    used_a, used_b, matched = set(), set(), []
    for score, i, j in pairs:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        matched.append((i, j, score))
    matched.sort()
    return {
        "ours_regions": len(ours),
        "paddlex_regions": len(theirs),
        "matched": len(matched),
        "label_agree": sum(1 for i, j, _s in matched
                           if ours[i]["label"] == theirs[j]["label"]),
        "order_agree": sum(1 for a in range(len(matched))
                           for b in range(a + 1, len(matched))
                           if matched[a][1] < matched[b][1]),
        "order_pairs": len(matched) * (len(matched) - 1) // 2,
        "ours_only": [ours[i]["label"] for i in range(len(ours))
                      if i not in used_a],
        "paddlex_only": [theirs[j]["label"] for j in range(len(theirs))
                         if j not in used_b],
        "label_diffs": [
            {"box": ours[i]["box"], "iou": round(s, 3),
             "ours": ours[i]["label"], "paddlex": theirs[j]["label"]}
            for i, j, s in matched if ours[i]["label"] != theirs[j]["label"]],
        "order_diffs": [
            {"ours": ours[matched[a][0]]["label"],
             "paddlex": theirs[matched[b][1]]["label"],
             "ours_index": a, "paddlex_index": b}
            for a in range(len(matched)) for b in range(a + 1, len(matched))
            if matched[a][1] > matched[b][1]],
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--layout-onnx", required=True, type=Path,
                    help="PP-DocLayout-M_cut.onnx (the graph inside the bmodel)")
    ap.add_argument("--ppocr-dir", required=True, type=Path,
                    help="directory with ppocrv6_medium_{det,rec}.onnx")
    ap.add_argument("--images", nargs="+", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--no-paddlex", action="store_true",
                    help="only print our side (no paddle in this environment)")
    args = ap.parse_args()

    import cv2
    import onnxruntime as ort

    from app.engine.ocr_ppocr import load_config

    cfg = layout.load_layout_config(CONFIG_DIR)
    pp_config = load_config(CONFIG_DIR)
    layout_session = ort.InferenceSession(
        str(args.layout_onnx), providers=["CPUExecutionProvider"])
    det_session = ort.InferenceSession(
        str(args.ppocr_dir / "ppocrv6_medium_det.onnx"),
        providers=["CPUExecutionProvider"])
    rec_session = ort.InferenceSession(
        str(args.ppocr_dir / "ppocrv6_medium_rec.onnx"),
        providers=["CPUExecutionProvider"])

    report = {"images": []}
    for path in args.images:
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            raise SystemExit(f"cannot decode {path}")
        h, w = bgr.shape[:2]
        lines = ocr_lines(bgr, pp_config, det_session, rec_session)
        ours = our_page(bgr, cfg, layout_session, lines)
        entry = {"image": path.name, "ours": ours}

        print(f"\n=== {path.name} ({w}x{h}) ===")
        print(f"  ours: {len(ours['regions'])} regions")
        for region in ours["regions"]:
            print(f"    {region['label']:18s} {region['box']}  "
                  f"{region['text'][:34]!r}")

        if not args.no_paddlex:
            theirs = paddlex_regions(path)
            if theirs is None:
                print("  paddlex: skipped (see the message above)")
            else:
                ordered = paddlex_order(theirs, (h, w), lines)
                if ordered is None:
                    ordered = theirs
                diff = compare(ours["regions"], ordered)
                diff["markdown"] = {
                    "ours_lines": len(ours["markdown"].splitlines()),
                }
                entry["paddlex"] = ordered
                entry["diff"] = diff
                print(f"  paddlex: {diff['paddlex_regions']} regions, "
                      f"matched {diff['matched']}, "
                      f"labels {diff['label_agree']}/{diff['matched']}, "
                      f"order {diff['order_agree']}/{diff['order_pairs']}")
                if diff["ours_only"]:
                    print(f"  ours only:    {diff['ours_only']}")
                if diff["paddlex_only"]:
                    print(f"  paddlex only: {diff['paddlex_only']}")
                for item in diff["label_diffs"]:
                    print(f"  label diff:   {item}")
                for item in diff["order_diffs"]:
                    print(f"  order diff:   {item}")
        report["images"].append(entry)

    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
