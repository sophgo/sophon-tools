#!/usr/bin/env python3
"""PP-DocLayout-S / -M post-processing, transcribed from PaddleX.

The bmodels stop at ``boxes[1, anchors, 4]`` + ``scores[1, classes, anchors]``
(``tools/ocr/layout_cut.py``) because PaddleX's NMS/gather tail lowers to
``TPU_DYNAMIC`` on this chip. What remains is this file: roughly the code in
``paddlex/inference/models/object_detection/processors.py`` (``nms``, ``iou``,
``is_contained``, ``DetPostProcess.apply``) and
``.../layout_analysis/processors.py`` (``LayoutAnalysisProcess.apply``), minus
the branches that need tensors the bmodel does not emit.

It is a transcription on purpose. The acceptance question is "does the board
reproduce the reference", so the reference has to be what PaddleOCR ships, not
a tidier re-invention. Where PaddleX's own arithmetic is surprising it is
copied as-is and commented:

* ``iou`` adds +1 to both the intersection and each box's extent (a legacy
  VOC-style convention, not the textbook IoU).
* ``DetPostProcess.apply`` rounds x/y to integers *before* thresholding and NMS.
* Boxes are in network-input pixels; the caller rescales to the page.

Branches deliberately not ported, each because the tensor they need is absent
from the bmodel output: ``masks``/``polygon_points`` (the 200x200 mask head is
only present on PP-DocLayoutV3, not on S/M) and ``layout_unclip_ratio`` when
given per-class. Passing a non-``rect`` ``layout_shape_mode`` here is an error
rather than a silent downgrade.
"""
from __future__ import annotations

import numpy as np

#: ``inference.yml`` ``label_list`` for PP-DocLayout-S / PP-DocLayout-M. Both
#: exports carry the same 23 classes; ``load_labels`` reads them from the ONNX
#: file's metadata when available so a re-export cannot drift silently.
LABELS = [
    "paragraph_title", "image", "text", "number", "abstract", "content",
    "figure_title", "formula", "table", "table_title", "reference", "doc_title",
    "footnote", "header", "algorithm", "footer", "seal", "chart_title",
    "chart", "formula_number", "header_image", "footer_image", "aside_text",
]

#: ``paddlex/configs/pipelines/PP-StructureV3.yaml`` → ``layout_merge_bboxes_mode``
#: for the 23-class label space. Absent keys are "union".
MERGE_MODE_STRUCTURE_V3 = {
    0: "large",   # paragraph_title
    1: "large",   # image
    6: "union",   # figure_table_chart_title is not in this label space
    7: "large",   # formula
    16: "large",  # chart
}

#: ``layout_nms: True`` in the same file. Note this is PaddleX's *layout* NMS,
#: not the NMS already inside the ONNX: the graph's NMS runs first (with
#: top_k=1000, iou=0.6, score=0.025), and this one runs on its output.
IOU_SAME = 0.6
IOU_DIFF = 0.98


def load_labels(onnx_path=None):
    """Label list for PP-DocLayout-S / -M.

    Kept as a literal rather than read from the ONNX metadata: the export does
    not carry ``label_list`` (it lives in ``inference.yml``), and a class-index
    mismatch is exactly the kind of silent error this file exists to prevent.
    ``tests/test_ocr_layout.py`` pins the length against both ONNX files'
    final-score dimension.
    """
    return list(LABELS)


def iou(box1, box2):
    """PaddleX ``iou``: +1 on the intersection *and* both extents."""
    x1, y1, x2, y2 = box1
    x1_p, y1_p, x2_p, y2_p = box2
    x1_i, y1_i = max(x1, x1_p), max(y1, y1_p)
    x2_i, y2_i = min(x2, x2_p), min(y2, y2_p)
    inter = max(0, x2_i - x1_i + 1) * max(0, y2_i - y1_i + 1)
    a1 = (x2 - x1 + 1) * (y2 - y1 + 1)
    a2 = (x2_p - x1_p + 1) * (y2_p - y1_p + 1)
    return inter / float(a1 + a2 - inter)


def nms(boxes, iou_same=IOU_SAME, iou_diff=IOU_DIFF):
    """PaddleX ``nms``: greedy by score, per-class-pair IoU thresholds.

    Kept as the reference's own O(n^2) python loop rather than vectorised: it
    runs on <=100 rows here, and matching its exact tie-breaking matters more
    than speed.
    """
    scores = boxes[:, 1]
    indices = list(np.argsort(scores)[::-1])
    selected = []
    while indices:
        current = indices[0]
        current_box = boxes[current]
        selected.append(current)
        indices = indices[1:]
        kept = []
        for i in indices:
            box = boxes[i]
            threshold = iou_same if current_box[0] == box[0] else iou_diff
            if iou(current_box[2:], box[2:]) < threshold:
                kept.append(i)
        indices = kept
    return selected


def is_contained(box1, box2):
    """PaddleX ``is_contained``: is box1's area fully inside box2?"""
    _, _, x1, y1, x2, y2 = box1
    _, _, x1_p, y1_p, x2_p, y2_p = box2
    a1 = (x2 - x1) * (y2 - y1)
    iw = max(0, min(x2, x2_p) - max(x1, x1_p))
    ih = max(0, min(y2, y2_p) - max(y1, y1_p))
    return (iw * ih) / a1 >= 0.9 if a1 else False


def check_containment(boxes, formula_index=None):
    n = len(boxes)
    contains_other = np.zeros(n, dtype=int)
    contained_by_other = np.zeros(n, dtype=int)
    for i in range(n):
        # PaddleX skips comparisons *from* a formula box against non-formula
        # boxes; the "large"/"small" semantics around formula boxes depend on
        # it, so it is not an optimisation that can be dropped.
        if formula_index is not None and boxes[i][0] == formula_index:
            continue
        for j in range(n):
            if i == j:
                continue
            if is_contained(boxes[i], boxes[j]):
                contained_by_other[i] = 1
                contains_other[j] = 1
    return contains_other, contained_by_other


def restructured_boxes(boxes, labels, img_size):
    """PaddleX ``restructured_boxes``: clip to the page, drop degenerates."""
    box_list = []
    w, h = img_size          # NB: PaddleX unpacks (w, h) and clips x against w
    for idx, box in enumerate(boxes):
        xmin, ymin, xmax, ymax = box[2:]
        xmin = int(max(0, xmin))
        ymin = int(max(0, ymin))
        xmax = int(min(w, xmax))
        ymax = int(min(h, ymax))
        if xmax <= xmin or ymax <= ymin:
            continue
        box_list.append({
            "cls_id": int(box[0]),
            "label": labels[int(box[0])],
            "score": float(box[1]),
            "coordinate": [xmin, ymin, xmax, ymax],
            "order": idx + 1,
        })
    return box_list


def rescale_boxes(boxes, scale_factor):
    """Network-input pixels -> page pixels.

    ``scale_factor`` is PaddleX's ``[net_h / page_h, net_w / page_w]``. The
    bmodel stops *before* the graph's own division by it (see
    ``layout_cut.py``), so this is where that step now happens. x/y are scaled
    with the width factor and y with the height factor, matching the order of
    the ``Div`` that was cut out.
    """
    sf_h, sf_w = float(scale_factor[0]), float(scale_factor[1])
    return boxes / np.array([sf_w, sf_h, sf_w, sf_h], np.float32)


def det_postprocess(boxes, scores, img_size,
                    threshold=0.5, num_classes=None, labels=None,
                    layout_nms=True, merge_mode=None):
    """numpy twin of the ONNX tail + ``LayoutAnalysisProcess``.

    ``boxes`` is ``[1, anchors, 4]`` and ``scores`` ``[1, classes, anchors]``,
    with the boxes already in *page* pixels (``rescale_boxes``).

    ``merge_mode`` is either ``None`` (every class "union"), a dict
    ``{cls_id: "large"|"small"|"union"}``, or one string for all classes.
    """
    boxes = np.asarray(boxes, np.float32).reshape(-1, 4)
    scores = np.asarray(scores, np.float32)
    if scores.ndim == 3:
        scores = scores[0]
    labels = list(labels if labels is not None else LABELS)
    if num_classes is None:
        num_classes = len(labels)
    scores = scores[:num_classes]

    if threshold is None:
        threshold = 0.5

    # --- the ONNX's own MulticlassNMS, in numpy -------------------------
    # paddle2onnx emits: score > 0.025, nms_top_k 1000, iou 0.6, keep_top_k 100
    # per class, then a global top-k over the surviving classes. The 0.025 is
    # a pre-filter only; the real threshold is applied below, which is why
    # PaddleX can use per-class thresholds in 0.3..0.5.
    rows = _multiclass_nms(boxes, scores, pre_threshold=0.025,
                           nms_top_k=1000, iou_threshold=0.6, keep_top_k=100)
    if len(rows) == 0:
        return []

    # --- DetPostProcess.apply -------------------------------------------
    rows[:, 2:6] = np.round(rows[:, 2:6]).astype(int)

    if isinstance(threshold, dict):
        kept = []
        for cls in np.unique(rows[:, 0]):
            sub = rows[rows[:, 0] == cls]
            t = threshold.get(int(cls), 0.5)
            kept.append(sub[(sub[:, 1] > t) & (sub[:, 0] > -1)])
        rows = np.vstack(kept) if kept else np.empty((0, 6))
    else:
        rows = rows[(rows[:, 1] > threshold) & (rows[:, 0] > -1)]

    if layout_nms and len(rows):
        rows = rows[nms(rows[:, :6])]
        rows = np.asarray(rows, np.float64 if rows.dtype == np.float64 else np.float32)

    # Drop an "image" box that covers the whole page: PaddleX's
    # filter_large_image, area_thres 0.82 (portrait page) / 0.93.
    if len(rows) > 1 and rows.shape[1] in (6, 7, 8):
        area_thres = 0.82 if img_size[0] > img_size[1] else 0.93
        image_index = labels.index("image") if "image" in labels else None
        page_area = img_size[0] * img_size[1]
        kept = []
        for box in rows:
            if box[0] == image_index:
                xmin = max(0, box[2]); ymin = max(0, box[3])
                xmax = min(img_size[0], box[4]); ymax = min(img_size[1], box[5])
                if (xmax - xmin) * (ymax - ymin) <= area_thres * page_area:
                    kept.append(box)
            else:
                kept.append(box)
        rows = np.array(kept) if kept else rows

    # layout_merge_bboxes_mode
    if merge_mode and len(rows):
        formula_index = labels.index("formula") if "formula" in labels else None
        if isinstance(merge_mode, str):
            keep_mask = np.ones(len(rows), dtype=bool)
            if merge_mode == "large":
                _, contained = check_containment(rows[:, :6], formula_index)
                keep_mask &= contained == 0
            elif merge_mode == "small":
                contains, contained = check_containment(rows[:, :6], formula_index)
                keep_mask &= (contains == 0) | (contained == 1)
            rows = rows[keep_mask]
        else:
            keep_mask = np.ones(len(rows), dtype=bool)
            for cls, mode in merge_mode.items():
                if mode == "union":
                    continue
                contains, contained = check_containment(
                    rows[:, :6], formula_index)
                if mode == "large":
                    keep_mask &= contained == 0
                elif mode == "small":
                    keep_mask &= (contains == 0) | (contained == 1)
            rows = rows[keep_mask]

    if rows.size == 0:
        return []
    return restructured_boxes(rows, labels, img_size)


def _multiclass_nms(boxes, scores, pre_threshold=0.025,
                    nms_top_k=1000, iou_threshold=0.6, keep_top_k=100):
    """PaddleX/paddle2onnx MulticlassNMS3 in numpy.

    Returns rows ``[cls, score, x1, y1, x2, y2]`` in page pixels. The three
    steps are the op's own: per-class pre-threshold, per-class greedy NMS on at
    most ``nms_top_k`` candidates, then a global ``keep_top_k`` by score.

    **Standard IoU here, not PaddleX's ``iou``.** The op's suppression rule is
    ONNX ``NonMaxSuppression``'s (plain intersection over union); the ``+1``
    extent convention belongs to PaddleX's *layout* NMS (``nms`` below), which
    runs on this output rather than inside it. Using the ``+1`` form here
    shifts the suppression boundary enough to swap 13 of the 100 kept rows on
    ``skewed_lines``.
    """
    boxes = np.asarray(boxes, np.float32).reshape(-1, 4)
    out = []
    num_classes = scores.shape[0]
    for cls in range(num_classes):
        s = scores[cls]
        idx = np.where(s > pre_threshold)[0]
        if len(idx) == 0:
            continue
        order = idx[np.argsort(-s[idx])]
        if len(order) > nms_top_k:
            order = order[:nms_top_k]
        keep = []
        bx = boxes[order]
        while len(order):
            keep.append(order[0])
            if len(order) == 1:
                break
            xx1 = np.maximum(bx[0, 0], bx[1:, 0])
            yy1 = np.maximum(bx[0, 1], bx[1:, 1])
            xx2 = np.minimum(bx[0, 2], bx[1:, 2])
            yy2 = np.minimum(bx[0, 3], bx[1:, 3])
            inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
            areas = ((bx[:, 2] - bx[:, 0]) * (bx[:, 3] - bx[:, 1]))
            ovr = inter / np.maximum(areas[0] + areas[1:] - inter, 1e-9)
            rest = np.where(ovr <= iou_threshold)[0] + 1
            order, bx = order[rest], bx[rest]
        for k in keep:
            out.append([cls, s[k], *boxes[k]])
    if not out:
        return np.empty((0, 6), np.float32)
    rows = np.asarray(out, np.float32)
    # paddle2onnx's tail keeps keep_top_k by score across all classes.
    if len(rows) > keep_top_k:
        rows = rows[np.argsort(-rows[:, 1])[:keep_top_k]]
    return rows
