#!/usr/bin/env python3
"""PP-DocLayoutV3 reference: ONNX graph + PaddleX's own post-processing.

Written for the stage-A feasibility report (MYS-2591). It is deliberately a
*transcription* of ``paddlex/inference/models/object_detection/modeling/
pp_doclayout_v3.py`` (``PPDocLayoutV3PostProcess``) and ``layout_analysis/
processors.py`` (``LayoutAnalysisProcess``), not an independent reinvention:
the acceptance question is whether the board reproduces this, so the reference
has to be the thing PaddleOCR actually ships.

Two deliberate omissions, both recorded in the report:

* ``layout_shape_mode`` is forced to ``rect``, so the 200x200 mask branch is
  not exercised. The bmodel is being asked for boxes, and the polygon branch is
  pure post-processing with no model content.
* ``layout_merge_bboxes_mode`` defaults to ``union`` for every class, which is
  what ``PaddleOCR-VL-1.5.yaml`` specifies for 21 of its 25 labels; the four
  ``large`` classes (chart/display_formula/doc_title/inline_formula/
  paragraph_title) are applied when ``--merge-mode yaml`` is passed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

LABELS = [
    "abstract", "algorithm", "aside_text", "chart", "content", "display_formula",
    "doc_title", "figure_title", "footer", "footer_image", "footnote",
    "formula_number", "header", "header_image", "image", "inline_formula",
    "number", "paragraph_title", "reference", "reference_content", "seal",
    "table", "text", "vertical_text", "vision_footnote",
]

#: From ``paddlex/configs/pipelines/PaddleOCR-VL-1.5.yaml``. Everything not
#: listed is "union", i.e. keep every box.
MERGE_MODE_15 = {
    3: "large",   # chart
    5: "large",   # display_formula
    6: "large",   # doc_title
    15: "large",  # inline_formula
    17: "large",  # paragraph_title
}

SIDE = 800


def preprocess(bgr: np.ndarray):
    """Resize to 800x800 without keeping aspect, RGB, /255, ImageNet norm, CHW.

    ``inference.yml`` declares Resize(keep_ratio=false, 800x800) +
    NormalizeImage(mean 0, std 1) + Permute; but the graph itself takes
    ``im_shape``/``scale_factor`` and the exported ONNX folds the mean/std in,
    so the caller supplies already-normalised pixels. Both the ONNX README and
    the PaddleX processor for this model normalise with the ImageNet constants
    *after* the /255, so that is what is done here.
    """
    import cv2

    h, w = bgr.shape[:2]
    resized = cv2.resize(bgr, (SIDE, SIDE), interpolation=cv2.INTER_LINEAR)
    x = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    x = (x - mean) / std
    x = np.transpose(x, (2, 0, 1))[None]
    im_shape = np.array([[SIDE, SIDE]], dtype=np.float32)
    scale = np.array([[SIDE / float(h), SIDE / float(w)]], dtype=np.float32)
    return x, im_shape, scale


def bbox_cxcywh_to_xyxy(x):
    cx, cy, w, h = np.split(x, 4, axis=-1)
    return np.concatenate([cx - 0.5 * w, cy - 0.5 * h, cx + 0.5 * w, cy + 0.5 * h],
                          axis=-1)


def get_order(order_logits):
    """``get_order`` from pp_doclayout_v3.py: a Bradley-Terry style vote."""
    s = 1.0 / (1.0 + np.exp(-order_logits))
    n = s.shape[1]
    upper = np.triu(np.ones((n, n), dtype=np.float32), 1)
    lower = np.tril(np.ones((n, n), dtype=np.float32), -1)
    q = s * upper + (1.0 - np.transpose(s, (0, 2, 1))) * lower
    votes = q.sum(axis=1)
    pointers = np.argsort(votes, axis=1)
    seq = np.full(pointers.shape, -1, dtype=np.int64)
    np.put_along_axis(seq, pointers, np.tile(np.arange(n), (pointers.shape[0], 1)), axis=1)
    return seq, votes


def decode(raw, im_shape, scale=None, threshold=0.3, merge_mode=None,
           unclip=(1.0, 1.0), shape_mode="rect"):
    """Full PaddleX decode for a single image.

    ``raw`` is the ONNX session output list. The exported graph already folds
    the top-k, sigmoid and box scale into the graph (its third output is the
    per-query mask logits and its first is the final 8-column box tensor), so
    what remains here is exactly the ``LayoutAnalysisProcess`` stage:
    threshold, NMS, containment merge, unclip, order sort.
    """
    boxes = np.asarray(raw[0], dtype=np.float32)
    n = int(np.asarray(raw[1]).reshape(-1)[0])
    boxes = boxes[:n].copy()

    # layout_shape_mode="rect" -> the mask branch is skipped entirely
    # (processors.py: layout_shape_mode == "rect" sets masks = None).
    boxes[:, 2:6] = np.round(boxes[:, 2:6])

    keep = (boxes[:, 1] > threshold) & (boxes[:, 0] > -1)
    boxes = boxes[keep]
    if len(boxes) == 0:
        return []

    chosen = nms(boxes[:, :6], iou_same=0.6, iou_diff=0.98)
    boxes = boxes[chosen]

    # filter_large_image: drop an "image" box that covers the whole page.
    if len(boxes) > 1:
        area_thres = 0.82 if im_shape[0] > im_shape[1] else 0.93
        image_index = LABELS.index("image")
        img_area = float(im_shape[0] * im_shape[1])
        kept = []
        for box in boxes:
            label_index, _score, xmin, ymin, xmax, ymax = box[:6]
            if int(label_index) == image_index:
                xmin = max(0.0, xmin)
                ymin = max(0.0, ymin)
                xmax = min(float(im_shape[1]), xmax)
                ymax = min(float(im_shape[0]), ymax)
                if (xmax - xmin) * (ymax - ymin) <= area_thres * img_area:
                    kept.append(box)
            else:
                kept.append(box)
        boxes = np.array(kept) if kept else boxes

    if merge_mode:
        formula_index = LABELS.index("formula") if "formula" in LABELS else None
        keep_mask = np.ones(len(boxes), dtype=bool)
        for category_index, mode in merge_mode.items():
            if mode == "union":
                continue
            contains, contained = check_containment(boxes[:, :6], formula_index,
                                                    category_index, mode=mode)
            if mode == "large":
                keep_mask &= contained == 0
            else:
                keep_mask &= (contains == 0) | (contained == 1)
        boxes = boxes[keep_mask]
        if len(boxes) == 0:
            return []

    if boxes.shape[1] == 8:
        order = np.lexsort((-boxes[:, 7], boxes[:, 6]))
        boxes = boxes[order]
    elif boxes.shape[1] == 7:
        boxes = boxes[np.argsort(boxes[:, 6])]
    boxes = boxes[:, :6]

    if unclip:
        boxes = unclip_boxes(boxes, unclip)

    return restructured(boxes, im_shape)


def nms(boxes, iou_same=0.6, iou_diff=0.98):
    """PaddleX ``nms``: same-class IoU 0.6, cross-class IoU 0.98."""
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 2], boxes[:, 3], boxes[:, 4], boxes[:, 5]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = np.argsort(-boxes[:, 1])
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[rest] - inter + 1e-9)
        same = boxes[rest, 0] == boxes[i, 0]
        limit = np.where(same, iou_same, iou_diff)
        order = rest[iou <= limit]
    return keep


def is_contained(box1, box2):
    """PaddleX ``is_contained``: >=90% of box1's area lies inside box2."""
    _, _, x1, y1, x2, y2 = box1
    _, _, x1_p, y1_p, x2_p, y2_p = box2
    area = (x2 - x1) * (y2 - y1)
    iw = max(0.0, min(x2, x2_p) - max(x1, x1_p))
    ih = max(0.0, min(y2, y2_p) - max(y1, y1_p))
    return (iw * ih) / area if area > 0 else 0.0


def check_containment(boxes, formula_index=None, category_index=None, mode=None):
    """PaddleX ``check_containment``, transcribed.

    Note the asymmetry the original has: in ``large`` mode only pairs where the
    *container* ``j`` is of the category count, so a ``large`` class is kept only
    when nothing else of its own class encloses it.
    """
    n = len(boxes)
    contains = np.zeros(n, dtype=int)
    contained = np.zeros(n, dtype=int)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if formula_index is not None:
                if boxes[i][0] == formula_index and boxes[j][0] != formula_index:
                    continue
            if category_index is not None and mode is not None:
                if mode == "large" and boxes[j][0] == category_index:
                    if is_contained(boxes[i], boxes[j]) >= 0.9:
                        contained[i] = 1
                        contains[j] = 1
                if mode == "small" and boxes[i][0] == category_index:
                    if is_contained(boxes[i], boxes[j]) >= 0.9:
                        contained[i] = 1
                        contains[j] = 1
            else:
                if is_contained(boxes[i], boxes[j]) >= 0.9:
                    contained[i] = 1
                    contains[j] = 1
    return contains, contained


def unclip_boxes(boxes, ratio):
    """PaddleX ``unclip_boxes``: grow each box about its own centre."""
    if isinstance(ratio, (int, float)):
        ratio = (ratio, ratio)
    out = boxes.copy()
    w = boxes[:, 4] - boxes[:, 2]
    h = boxes[:, 5] - boxes[:, 3]
    cx = boxes[:, 2] + w / 2.0
    cy = boxes[:, 3] + h / 2.0
    out[:, 2] = cx - w * ratio[0] / 2.0
    out[:, 3] = cy - h * ratio[1] / 2.0
    out[:, 4] = cx + w * ratio[0] / 2.0
    out[:, 5] = cy + h * ratio[1] / 2.0
    return out


def restructured(boxes, im_shape):
    """``restructured_boxes`` with ``shape_mode='rect'``."""
    out = []
    h, w = im_shape
    for idx, box in enumerate(boxes):
        label_index, score, x1, y1, x2, y2 = box
        x1 = int(max(0, x1))
        y1 = int(max(0, y1))
        x2 = int(min(w, x2))
        y2 = int(min(h, y2))
        if x2 <= x1 or y2 <= y1:
            continue
        out.append({"cls_id": int(label_index), "label": LABELS[int(label_index)],
                    "score": float(score), "coordinate": [x1, y1, x2, y2],
                    "order": idx + 1})
    return out


def run_onnx(session, bgr):
    x, im_shape, scale = preprocess(bgr)
    raw = session.run(None, {"im_shape": im_shape, "image": x,
                             "scale_factor": scale})
    h, w = bgr.shape[:2]
    return decode(raw, (float(h), float(w)), scale)


def main() -> int:
    import cv2
    import onnxruntime as ort

    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True, type=Path)
    ap.add_argument("--img-dir", required=True, type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--threshold", type=float, default=0.3)
    ap.add_argument("--merge-mode", choices=("union", "yaml", "large"),
                    default="union")
    ap.add_argument("--images", nargs="*")
    args = ap.parse_args()

    merge = {"union": None, "yaml": MERGE_MODE_15,
             "large": {i: "large" for i in range(len(LABELS))}}[args.merge_mode]

    session = ort.InferenceSession(str(args.onnx), providers=["CPUExecutionProvider"])
    names = args.images or sorted(p.name for p in args.img_dir.glob("*.png"))
    result = {}
    for name in names:
        path = args.img_dir / name
        if not path.exists():
            print(f"skip {name}: no such file", file=sys.stderr)
            continue
        bgr = cv2.imread(str(path))
        x, im_shape, scale = preprocess(bgr)
        raw = session.run(None, {"im_shape": im_shape, "image": x,
                                 "scale_factor": scale})
        boxes = decode(raw, (float(bgr.shape[0]), float(bgr.shape[1])),
                       threshold=args.threshold, merge_mode=merge)
        result[name] = boxes
        print(f"\n=== {name}  ({bgr.shape[1]}x{bgr.shape[0]})  {len(boxes)} boxes",
              file=sys.stderr)
        for i, b in enumerate(boxes):
            x1, y1, x2, y2 = b["coordinate"]
            print(f"{i:3d} {b['label']:<18} {b['score']:.3f} "
                  f"[{x1:7.1f},{y1:7.1f},{x2:7.1f},{y2:7.1f}]", file=sys.stderr)

    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        print(f"\nwrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
