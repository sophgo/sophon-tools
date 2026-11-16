"""PP-DocLayout-M: layout detection, block text, reading order, Markdown.

This is the ``mode: "layout"`` half of ``/v1/ocr``. A page image goes in; a
Markdown page comes out, with the title / paragraph / table / figure regions
that PP-DocLayout-M found and the text PP-OCR read inside each of them.

Four things live here, and the boundaries are where the oracles are:

* **Detection** (:func:`detect`) -- preprocessing, the bmodel's two dense
  tensors, then PaddleX's threshold / layout-NMS / merge tail in numpy. The
  bmodel is PP-DocLayout-M with the graph's own NMS cut out, because a
  data-dependent tail lowers to ``TPU_DYNAMIC`` and wedges this chip. Transcribed
  from ``paddlex/inference/models/layout_analysis/processors.py``; verified
  against PaddleX's own ``LayoutAnalysisProcess`` by
  ``tools/ocr/layout_cut.py --verify`` and pinned by ``tests/test_ocr_layout.py``.
* **Block text** (:func:`block_text`) -- the OCR lines that fall inside a region,
  joined the way PaddleX joins them. That rule is the reason a Chinese paragraph
  comes out as flowing text while an English one keeps its spaces, and it is
  not a heuristic of ours: it is ``LayoutBlock.update_text_content`` +
  ``TextLine.format_line``, transcribed.
* **Reading order** (:func:`order_blocks`) -- PaddleX's ``xycut_enhanced``: the
  recursive projection cut (``recursive_yx_cut``/``recursive_xy_cut``) for the
  body, plus distance insertion for titles and vision blocks. This is what makes
  a two-column page read down one column and then the other; sorting by
  (y, x) instead -- which is what ``tools/ocr/structure_page.py`` did for the
  single-column case -- interleaves the columns.
* **Markdown** (:func:`to_markdown`) -- PaddleX's label→format table
  (``build_handle_funcs_dict`` + ``MarkdownConverter.convert``), minus the
  branches that need models this service does not ship. Tables are rendered as
  plain text rows on purpose; see the ``_table_markdown`` docstring.

Everything here is pure host code (numpy, and ``cv2`` for resize/colour), so
``tests/test_ocr_layout.py`` runs the whole thing on x86 with recorded tensors
standing in for the bmodel.

**Deliberate reductions**, each stated where the code is rather than hidden:

* No ``PP-DocBlockLayout`` region detector (the card scopes it out), so the page
  is one region. PaddleX runs its ordering twice -- once over regions, once
  inside each -- and with no region result it falls back to exactly the single
  region this module builds.
* A title's child-block absorption (``update_doc_title_child_blocks`` and
  friends) is not ported: it merges a title with an adjacent stray text box, and
  it needs per-block text-line geometry that only exists after OCR. The effect
  is an extra text block in the output, not a lost one.
* No formula recognition, chart-to-table or table structure: they are separate
  models (``PP-FormulaNet``, ``PP-Chart2Table``, ``SLANet``), and the card's
  "不做" list excludes them. Their placeholders are still emitted.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

# ---------------------------------------------------------------------------
# the model's own description
# ---------------------------------------------------------------------------
#: The layout config, beside ``ppocr.json`` in the model-config directory.
LAYOUT_CONFIG_FILE = "layout.json"

#: The 23 classes PP-DocLayout-S and -M both emit, in the bmodel's class-axis
#: order. ``tests/test_ocr_layout.py`` pins this against ``layout.json`` and the
#: config loader refuses to start if the two disagree: a class-axis off-by-one
#: relabels every region, which reads as "the model got worse" rather than as a
#: configuration error.
LABELS: tuple[str, ...] = (
    "paragraph_title", "image", "text", "number", "abstract", "content",
    "figure_title", "formula", "table", "table_title", "reference", "doc_title",
    "footnote", "header", "algorithm", "footer", "seal", "chart_title",
    "chart", "formula_number", "header_image", "footer_image", "aside_text",
)


@dataclass(frozen=True)
class LayoutConfig:
    """Everything ``layout.json`` says, in the shapes the code uses."""

    side: int
    mean: tuple[float, float, float]
    std: tuple[float, float, float]
    threshold: float
    iou_same: float
    iou_diff: float
    pre_threshold: float
    nms_top_k: int
    keep_top_k: int
    #: ``(portrait, landscape)`` area ratios above which an ``image`` box is
    #: taken to be the whole page and dropped.
    large_image_ratio: tuple[float, float]
    labels: tuple[str, ...]
    merge_mode: dict[int, str]
    #: The bmodel's file name, for the loader to find beside the detectors.
    bmodel: str
    raw: dict = field(repr=False, default_factory=dict)

    @property
    def num_classes(self) -> int:
        return len(self.labels)


def _require(mapping: dict, key: str, where: str):
    if key not in mapping:
        raise ValueError(f"{where} 缺少字段 {key!r}")
    return mapping[key]


def load_layout_config(config_dir: str | Path) -> LayoutConfig:
    """Read ``layout.json`` from the OCR model-config directory.

    Runs at worker start, so every refusal names the file and the field: the
    message becomes the model's ``load_error`` and is all an operator sees.
    """
    path = Path(config_dir) / LAYOUT_CONFIG_FILE
    if not path.is_file():
        raise ValueError(f"找不到 {path}（版面模式需要随包的 layout.json）")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} 不是合法 JSON：{exc}") from exc

    pre = _require(raw, "preprocess", LAYOUT_CONFIG_FILE)
    resize = _require(pre, "resize", "preprocess")
    normalize = _require(pre, "normalize", "preprocess")
    post = _require(raw, "postprocess", LAYOUT_CONFIG_FILE)
    bmodel = _require(raw, "bmodel", LAYOUT_CONFIG_FILE)

    side = int(_require(resize, "side", "preprocess.resize"))
    shape = list(_require(bmodel, "input", "bmodel")["shape"])
    if len(shape) != 4 or int(shape[2]) != side or int(shape[3]) != side:
        raise ValueError(
            f"layout.json 的 resize.side={side} 与 bmodel 输入 {shape} 不一致；"
            "坐标要按网络输入像素还原，两处必须相等")

    labels = tuple(str(x) for x in _require(post, "labels", "postprocess"))
    declared = int(_require(post, "num_classes", "postprocess"))
    if len(labels) != declared:
        raise ValueError(
            f"layout.json 的 labels 有 {len(labels)} 个而 num_classes={declared}；"
            "类别轴对不上会让每个类别整体错位")
    if labels != LABELS:
        raise ValueError(
            f"{LAYOUT_CONFIG_FILE} 的 labels 与 app/engine/ocr_layout.py 的 LABELS "
            "不一致；改类别表必须同时改代码")

    merge_mode = {int(k): str(v) for k, v in
                  (_require(post, "merge_mode", "postprocess") or {}).items()}
    for cls_id, mode in merge_mode.items():
        if not 0 <= cls_id < len(labels):
            raise ValueError(
                f"layout.json merge_mode 的类别 {cls_id} 不在 0..{len(labels) - 1}")
        if mode not in ("large", "small", "union"):
            raise ValueError(
                f"layout.json merge_mode[{cls_id}]={mode!r}，只能是 large/small/union")

    ratio = _require(post, "filter_large_image_area_ratio", "postprocess")
    return LayoutConfig(
        side=side,
        mean=tuple(float(x) for x in normalize["mean"]),
        std=tuple(float(x) for x in normalize["std"]),
        threshold=float(post["threshold"]),
        iou_same=float(post["iou_same"]),
        iou_diff=float(post["iou_diff"]),
        pre_threshold=float(post["pre_threshold"]),
        nms_top_k=int(post["nms_top_k"]),
        keep_top_k=int(post["keep_top_k"]),
        large_image_ratio=(float(ratio["portrait"]), float(ratio["landscape"])),
        labels=labels,
        merge_mode=merge_mode,
        bmodel=str(bmodel.get("file") or ""),
        raw=raw,
    )


# ---------------------------------------------------------------------------
# PaddleX's geometry, quirks included
# ---------------------------------------------------------------------------
def bbox_area(box) -> float:
    return (max(0.0, float(box[2]) - float(box[0]))
            * max(0.0, float(box[3]) - float(box[1])))


def overlap_ratio(bbox1, bbox2, mode: str = "union") -> float:
    """PaddleX ``calculate_overlap_ratio``.

    ``mode="small"`` divides by the *smaller* box, so it answers "what fraction
    of the smaller one is covered" -- the containment tests use it, and so does
    the text-line grouping.
    """
    x1, y1 = max(bbox1[0], bbox2[0]), max(bbox1[1], bbox2[1])
    x2, y2 = min(bbox1[2], bbox2[2]), min(bbox1[3], bbox2[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    a1, a2 = bbox_area(bbox1), bbox_area(bbox2)
    if mode == "union":
        ref = a1 + a2 - inter
    elif mode == "small":
        ref = min(a1, a2)
    elif mode == "large":
        ref = max(a1, a2)
    else:
        raise ValueError("mode must be union/small/large")
    return inter / ref if ref > 0 else 0.0


def projection_overlap(bbox1, bbox2, direction: str = "horizontal",
                       mode: str = "union") -> float:
    """PaddleX ``calculate_projection_overlap_ratio``: 1-D overlap on one axis."""
    start, end = (0, 2) if direction == "horizontal" else (1, 3)
    overlap = min(bbox1[end], bbox2[end]) - max(bbox1[start], bbox2[start])
    if overlap <= 0:
        return 0.0
    if mode == "union":
        ref = max(bbox1[end], bbox2[end]) - min(bbox1[start], bbox2[start])
    elif mode == "small":
        ref = min(bbox1[end] - bbox1[start], bbox2[end] - bbox2[start])
    elif mode == "large":
        ref = max(bbox1[end] - bbox1[start], bbox2[end] - bbox2[start])
    else:
        raise ValueError("mode must be union/small/large")
    return overlap / ref if ref > 0 else 0.0


def _iou_plus_one(box1, box2) -> float:
    """PaddleX's *layout* ``iou``: +1 on the intersection and both extents.

    A legacy VOC convention, not textbook IoU, and copied as-is: using the
    textbook form here changes which boxes survive the layout NMS (13 of 100
    kept rows on ``skewed_lines`` during the build).
    """
    x1, y1, x2, y2 = (float(v) for v in box1)
    x1p, y1p, x2p, y2p = (float(v) for v in box2)
    inter = (max(0.0, min(x2, x2p) - max(x1, x1p) + 1)
             * max(0.0, min(y2, y2p) - max(y1, y1p) + 1))
    a1 = (x2 - x1 + 1) * (y2 - y1 + 1)
    a2 = (x2p - x1p + 1) * (y2p - y1p + 1)
    return inter / float(a1 + a2 - inter)


def _is_contained(inner, outer) -> bool:
    """Is ``inner`` at least 90 % of the way inside ``outer``, by area?"""
    a = (inner[2] - inner[0]) * (inner[3] - inner[1])
    if a <= 0:
        return False
    iw = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    ih = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    return (iw * ih) / a >= 0.9


def _containment(rows, formula_index: int | None):
    """PaddleX ``check_containment``: who contains whom, formula rows skipped.

    Same arithmetic as the reference's ``n x n`` double loop, evaluated as one
    ``n x n`` array: on the board the loop was 96 ms of a 112 ms page (measured;
    ``docs/ocr.md`` §耗时), because it runs once per class whose merge mode is
    not ``union`` -- four times per page here.

    The formula skip is not an optimisation -- the large/small semantics around
    formula boxes depend on it -- and it is expressed as "a formula row
    contributes no containment", which is what ``continue`` does in the
    reference: its own row is skipped as ``i``, so it neither is marked
    contained nor marks anything else containing.
    """
    import numpy as np

    n = len(rows)
    if n == 0:
        return [0] * n, [0] * n
    boxes = np.asarray(rows, np.float32)[:, 2:6]
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)

    # inter[i, j] = overlap area of box i and box j
    iw = np.clip(np.minimum(x2[:, None], x2[None, :])
                 - np.maximum(x1[:, None], x1[None, :]), 0, None)
    ih = np.clip(np.minimum(y2[:, None], y2[None, :])
                 - np.maximum(y1[:, None], y1[None, :]), 0, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        # ``_is_contained(i, j)``: i's area is nonzero and >= 90 % of it lies in j
        inside = np.where(areas[:, None] > 0, (iw * ih) / areas[:, None], 0.0) >= 0.9
    np.fill_diagonal(inside, False)

    if formula_index is not None:
        # The reference's ``continue`` when row ``i`` is a formula: it never
        # tests, so it neither is "contained" nor makes anything "contains".
        skip = np.asarray(rows, np.float32)[:, 0].astype(int) == formula_index
        inside[skip, :] = False
        inside[:, skip] = False
    contains = inside.any(axis=0).astype(int)
    contained = inside.any(axis=1).astype(int)
    return contains.tolist(), contained.tolist()


def _layout_nms(rows, iou_same: float, iou_diff: float) -> list[int]:
    """PaddleX ``nms``: greedy by score; the threshold depends on class agreement."""
    order = sorted(range(len(rows)), key=lambda i: -float(rows[i][1]))
    selected: list[int] = []
    while order:
        current = order[0]
        selected.append(current)
        kept = []
        for i in order[1:]:
            threshold = iou_same if rows[current][0] == rows[i][0] else iou_diff
            if _iou_plus_one(rows[current][2:6], rows[i][2:6]) < threshold:
                kept.append(i)
        order = kept
    return selected


def _multiclass_nms(boxes, scores, cfg: LayoutConfig):
    """The ONNX's own MulticlassNMS tail, in numpy.

    Returns rows ``[cls, score, x1, y1, x2, y2]`` in *page* pixels. Three steps,
    exactly as paddle2onnx emits them: per-class pre-threshold, per-class greedy
    NMS over at most ``nms_top_k`` candidates, then one global ``keep_top_k``.

    **Plain IoU here, not PaddleX's ``+1`` form.** The suppression rule belongs
    to ONNX ``NonMaxSuppression``; the ``+1`` convention belongs to PaddleX's
    layout NMS, which runs on this output afterwards. Mixing them swaps 13 of
    100 rows on ``skewed_lines``.
    """
    import numpy as np

    boxes = np.asarray(boxes, np.float32).reshape(-1, 4)
    scores = np.asarray(scores, np.float32)

    # Per-class pre-threshold in one vectorised pass: ``(cls, anchor, score)``
    # triplets, each class in descending score order. The reference does this
    # class by class in Python; the arithmetic is identical and the loop was
    # 54 ms of a 112 ms page on the board (measured, docs/ocr.md §耗时).
    cls_idx, anchor_idx = np.where(scores > cfg.pre_threshold)
    if len(cls_idx) == 0:
        return np.empty((0, 6), np.float32)
    order = np.lexsort((-scores[cls_idx, anchor_idx], cls_idx))
    cls_idx, anchor_idx = cls_idx[order], anchor_idx[order]
    # ``nms_top_k`` is per class, so the cut has to be applied within a class --
    # a global slice would let one crowded class starve the others.
    keep_mask = np.ones(len(cls_idx), dtype=bool)
    boundaries = np.flatnonzero(np.diff(cls_idx)) + 1
    for start, end in zip(np.r_[0, boundaries], np.r_[boundaries, len(cls_idx)]):
        if end - start > cfg.nms_top_k:
            keep_mask[start + cfg.nms_top_k:end] = False
    cls_idx, anchor_idx = cls_idx[keep_mask], anchor_idx[keep_mask]

    # Greedy NMS, one class at a time. Same suppression rule as the reference
    # (plain IoU > 0.6, greedy by score), but the pairwise IoU matrix for a
    # class is computed **once** and the greedy walk then only reads a boolean
    # row per step. The obvious per-step form -- `rest = alive[1:]`, compute IoU,
    # slice -- costs ~150 us per keep-step on the board's numpy 1.21, i.e. 60 ms
    # for the ~390 steps a page takes, and is what made `usage.layout_ms` read
    # 104 ms. One 300x300 matrix is 90 KB here, so materialising it is cheap.
    rows: list[list[float]] = []
    for cls in np.unique(cls_idx):
        member = np.flatnonzero(cls_idx == cls)
        anchor = anchor_idx[member]
        box = boxes[anchor]
        n = len(box)
        if n == 0:
            continue
        x1, y1, x2, y2 = box[:, 0], box[:, 1], box[:, 2], box[:, 3]
        areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
        iw = np.maximum(0.0, np.minimum(x2[:, None], x2[None, :])
                        - np.maximum(x1[:, None], x1[None, :]))
        ih = np.maximum(0.0, np.minimum(y2[:, None], y2[None, :])
                        - np.maximum(y1[:, None], y1[None, :]))
        inter = iw * ih
        union = areas[:, None] + areas[None, :] - inter
        # ``suppress[i, j]``: i comes first (the candidates are in score order)
        # and removes j. Only the upper triangle counts -- and the diagonal must
        # be cleared, or every box would suppress itself (IoU 1.0 against its
        # own copy) and the class would come back empty.
        overlap = (inter / np.maximum(union, 1e-9)) > 0.6
        suppress = np.triu(overlap, k=1)
        suppressed = suppress.any(axis=0)
        for k in np.flatnonzero(~suppressed):
            rows.append([int(cls), float(scores[cls, anchor[k]]),
                         *[float(v) for v in box[k]]])
    if not rows:
        return np.empty((0, 6), np.float32)
    out = np.asarray(rows, np.float32)
    if len(out) > cfg.keep_top_k:
        out = out[np.argsort(-out[:, 1])[: cfg.keep_top_k]]
    return out


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------
def preprocess(bgr, cfg: LayoutConfig):
    """PaddleX's layout preprocessing: stretch to a square, ImageNet norm, CHW.

    ``keep_ratio=false`` -- the page is *stretched*, not letterboxed. Using
    PP-OCR's letterbox here instead would shift every detected box by the pad.

    Done in two OpenCV calls rather than the obvious numpy chain
    (``cvtColor`` + ``astype`` + subtract + divide + transpose): on the board the
    numpy form was 36 ms of the 104 ms a layout page took, because a
    640x640x3 float32 array is 4.9 MB and every elementwise step walks it in the
    interpreter. ``blobFromImage`` is the same arithmetic --
    ``(pixel - mean) * scale`` on the RGB channels, then HWC->CHW -- performed
    in C++, and ``swapRB`` is what does the BGR->RGB conversion the model needs.
    ``tests/test_ocr_layout.py`` pins the result against the numpy formula it
    replaces, so the two cannot drift.
    """
    import cv2
    import numpy as np

    side = cfg.side
    # ImageNet's std is *not* the same on all three channels (0.229/0.224/0.225),
    # and ``blobFromImage`` only takes one scale, so the per-channel values are
    # applied afterwards on the CHW tensor -- three 640x640 planes, which is a
    # third of the elementwise work the old HWC form did and is why this is
    # still worth the split. ``mean`` *is* per-channel, so it goes in.
    blob = cv2.dnn.blobFromImage(
        bgr,
        scalefactor=1.0 / 255.0,
        size=(side, side),
        mean=tuple(m * 255.0 for m in cfg.mean),
        swapRB=True,
        crop=False,
        ddepth=cv2.CV_32F,
    )
    # ``blobFromImage`` resizes with INTER_LINEAR and no aspect preservation,
    # which is exactly PaddleX's ``Resize(keep_ratio=false)``. Its ``mean`` is
    # subtracted on the 0..255 scale, so the configured 0..1 means are scaled up
    # to match.
    scale = np.asarray(cfg.std, np.float32).reshape(1, 3, 1, 1)
    if not np.allclose(scale, scale.flat[0]):
        np.divide(blob, scale, out=blob)
        return np.ascontiguousarray(blob)
    return np.ascontiguousarray(blob / float(scale.flat[0]))


def detect(raw_boxes, raw_scores, page_hw, cfg: LayoutConfig) -> list[dict]:
    """The bmodel's two dense tensors -> PaddleX's regions, in page pixels.

    ``raw_boxes`` is ``[anchors, 4]`` and ``raw_scores`` ``[classes, anchors]``,
    with the batch axes already dropped. Each region is ``{"cls_id", "label",
    "score", "box": [x1, y1, x2, y2]}``.
    """
    import numpy as np

    h, w = page_hw
    boxes = np.asarray(raw_boxes, np.float32).reshape(-1, 4)
    # The bmodel stops before the graph's own division by ``scale_factor`` (see
    # tools/ocr/layout_cut.py), so it happens here. PaddleX's scale_factor is
    # [net_h/page_h, net_w/page_w] and the Div divided x by the width factor and
    # y by the height one.
    boxes = boxes / np.array(
        [cfg.side / w, cfg.side / h, cfg.side / w, cfg.side / h], np.float32)

    scores = np.asarray(raw_scores, np.float32)
    if scores.ndim == 3:
        scores = scores[0]
    scores = scores[: cfg.num_classes]

    rows = _multiclass_nms(boxes, scores, cfg)
    if len(rows) == 0:
        return []

    # DetPostProcess.apply rounds *before* thresholding and NMS, in that order.
    rows[:, 2:6] = np.round(rows[:, 2:6]).astype(int)
    rows = rows[(rows[:, 1] > cfg.threshold) & (rows[:, 0] > -1)]
    if len(rows) == 0:
        return []

    rows = rows[_layout_nms(rows, cfg.iou_same, cfg.iou_diff)]

    # filter_large_image: a whole-page "image" box is dropped. PaddleX keys the
    # area ratio on the page's orientation and its img_size is (w, h), so
    # portrait -- the case with the tighter 0.82 -- is h > w here.
    if len(rows) > 1:
        ratio = cfg.large_image_ratio[0] if h > w else cfg.large_image_ratio[1]
        image_index = cfg.labels.index("image")
        page_area = float(h) * float(w)
        keep = []
        for row in rows:
            if int(row[0]) != image_index:
                keep.append(row)
                continue
            x1, y1 = max(0.0, float(row[2])), max(0.0, float(row[3]))
            x2, y2 = min(float(w), float(row[4])), min(float(h), float(row[5]))
            if (x2 - x1) * (y2 - y1) <= ratio * page_area:
                keep.append(row)
        rows = np.asarray(keep) if keep else rows

    # layout_merge_bboxes_mode. PaddleX runs the containment pass once per
    # class whose mode is not "union" and ANDs the results; classes absent from
    # the map are "union" and contribute nothing.
    if cfg.merge_mode and len(rows):
        formula_index = cfg.labels.index("formula")
        keep_mask = np.ones(len(rows), dtype=bool)
        for _cls, mode in cfg.merge_mode.items():
            if mode == "union":
                continue
            contains, contained = _containment(rows[:, :6], formula_index)
            if mode == "large":
                keep_mask &= np.asarray(contained) == 0
            else:
                keep_mask &= ((np.asarray(contains) == 0)
                              | (np.asarray(contained) == 1))
        rows = rows[keep_mask]

    regions = []
    for row in rows:
        x1, y1 = int(max(0, row[2])), int(max(0, row[3]))
        x2, y2 = int(min(w, row[4])), int(min(h, row[5]))
        if x2 <= x1 or y2 <= y1:
            continue
        regions.append({
            "cls_id": int(row[0]),
            "label": cfg.labels[int(row[0])],
            "score": float(row[1]),
            "box": [x1, y1, x2, y2],
        })
    return regions


# ---------------------------------------------------------------------------
# joining a region's OCR lines into its text
# ---------------------------------------------------------------------------
#: ``LINE_SETTINGS`` from ``paddlex/.../layout_parsing/setting.py``. Two OCR
#: boxes are on the same visual line when their extents overlap by at least this
#: much along the axis perpendicular to the text.
LINE_HEIGHT_OVERLAP_THRESHOLD = 0.6

#: ``delimiter_map`` from the same file. A label listed here joins its lines with
#: the delimiter and does no reflow at all; every other label goes through the
#: reflow branch, which is where the Chinese-versus-English rule lives.
LINE_DELIMITERS: dict[str, str] = {"doc_title": " ", "content": "\n"}

#: The 11 characters PaddleX lists as non-breaking. A line ending in one of them
#: may break without the extra newline a mid-sentence break would otherwise get.
NON_BREAKING_PUNCTUATION = frozenset(
    {",", "，", "、", ";", "；", ":", "：", "-", "'", '"', "“"})


def _is_english_letter(char: str) -> bool:
    return bool(re.match(r"^[A-Za-z]$", char))


def _is_numeric(char: str) -> bool:
    return bool(re.match(r"^[\d]+$", char))


def _span_box(entry) -> list[float]:
    return [float(v) for v in entry["box"]]


def _spans_box(spans) -> list[float]:
    """The line's own box: the union of its spans' boxes."""
    boxes = [_span_box(span) for span in spans]
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def group_lines(entries, direction: str = "horizontal") -> list[list]:
    """PaddleX ``group_boxes_into_lines``: OCR boxes -> visual lines.

    ``entries`` are region-line dicts (``text``/``score``/``box``), with ``box``
    an axis-aligned ``[x1, y1, x2, y2]``. Sorted along the reading axis, then
    merged while the perpendicular overlap stays at or above the threshold.

    The ``>=`` is copied: at exactly 0.6 PaddleX merges, and a tight caption
    sits on that boundary often enough to change the output.
    """
    if not entries:
        return []
    if direction == "vertical":
        ordered = sorted(entries, key=lambda e: _span_box(e)[0], reverse=True)
        match = "horizontal"
    else:
        ordered = sorted(entries, key=lambda e: _span_box(e)[1])
        match = "vertical"
    lines = [[ordered[0]]]
    for entry in ordered[1:]:
        current = _spans_box(lines[-1])
        if projection_overlap(current, _span_box(entry), match,
                              mode="small") >= LINE_HEIGHT_OVERLAP_THRESHOLD:
            lines[-1].append(entry)
        else:
            lines.append([entry])
    # Within a line the reference sorts in ``get_texts`` -- not in
    # ``group_boxes_into_lines`` -- by a half-quantised start coordinate, so two
    # boxes a couple of pixels apart still compare equal there and the tie-break
    # (the end coordinate) decides. Doing it here means ``group_lines`` returns
    # lines that are ready to join, and every caller gets the same order.
    for line in lines:
        index = 0 if direction == "horizontal" else 1
        line.sort(key=lambda e: (_span_box(e)[index] // 2,
                                 _span_box(e)[2] if direction == "horizontal"
                                 else -_span_box(e)[3]))
    return lines


def _format_line(spans, block_start: float, block_stop: float,
                 line_gap_limit: float) -> str:
    """PaddleX ``TextLine.format_line``, horizontal case.

    The reference's rules, in its order:

    * after a span ending in an English letter, append a space -- words must not
      run together; after a Chinese character, append nothing, so a sentence
      reads continuously. This one line is why a Chinese paragraph and an
      English one come out looking different;
    * a line whose last span stops short of the block's right edge by more than
      a third of its text width, and by more than ``line_gap_limit``, is closed
      with a newline -- unless it ends in non-breaking punctuation;
    * a trailing ``-`` is a hyphenation and is dropped.

    ``line_gap_limit`` is ``self.height * 1.5`` in the reference, i.e. 1.5x the
    line's own height.
    """
    spans = sorted(spans, key=lambda s: (_span_box(s)[0] // 2, _span_box(s)[2]))
    text = ""
    for span in spans:
        text += span["text"]
        # The reference appends the space for the *span* that ends in a letter,
        # then strips the line's last one. Doing the same means "first line"
        # followed by "second line" keeps its separator, because the space was
        # added after the first span and was not the line's final character.
        if text and _is_english_letter(text[-1]):
            text += " "
    if text.endswith(" "):
        text = text[:-1]
    if not text:
        return ""

    last_box = _span_box(spans[-1])
    last_char = text[-1]
    block_width = max(0.0, block_stop - block_start)

    if ((not _is_english_letter(last_char)
         and last_char not in NON_BREAKING_PUNCTUATION
         and not _is_numeric(last_char))
            or block_stop - last_box[2] > block_width * 0.3):
        if block_stop - last_box[2] > line_gap_limit:
            if text.endswith("-"):
                return text[:-1]
            return text + "\n"

    if text.endswith("-"):
        return text[:-1]
    return text


def block_text(entries, label: str, box, direction: str = "horizontal") -> str:
    """One region's text, joined the way PaddleX joins it.

    This is ``LayoutBlock.update_text_content`` minus the two branches that need
    a per-region *rec* pass (formula re-cropping, and the crop-and-recognise
    step for a line shared by several blocks). Neither can apply here: the card
    asks for one det over the whole page and no per-region recognition.

    A label in :data:`LINE_DELIMITERS` joins its visual lines with the delimiter
    and stops. Everything else reflows -- consecutive lines concatenate, and a
    newline survives only where :func:`_format_line` decided the paragraph
    really breaks. That is what makes a Chinese paragraph one flowing string
    while an English one keeps its spaces.
    """
    if not entries:
        return ""
    lines = group_lines(entries, direction)
    texts: list[str] = []
    for line in lines:
        height = max(_span_box(e)[3] for e in line) - min(_span_box(e)[1] for e in line)
        texts.append(_format_line(line, float(box[0]), float(box[2]),
                                 height * 1.5))
    delimiter = LINE_DELIMITERS.get(label, "")
    if delimiter:
        return delimiter.join(t for t in texts if t)
    # The newlines that survived are real paragraph breaks; ``to_markdown``
    # renders each as a blank line through PaddleX's
    # ``_format_normalize_newlines``.
    return _join_reflowed(texts).strip("\n")


def _join_reflowed(texts: list[str]) -> str:
    """Concatenate reflowed line texts, separating two English runs with a space.

    The reference's own letter rule (``format_line``) adds a space after a span
    ending in a letter, but it strips the *line's* trailing space, so a literal
    transcription yields ``first linesecond line`` -- two English lines running
    together. The card states the intended behaviour explicitly ("中文行直接
    连接，英文行用空格连接"), and running English words together is not something
    a caller could want, so the space is restored here. Chinese is untouched:
    a character ending one line and one starting the next are joined directly,
    which is the same rule the reference implements inside a line.
    """
    out = ""
    for text in texts:
        if not text:
            continue
        if out and _is_english_letter(out[-1]) and _is_english_letter(text[0]):
            out += " "
        out += text
    return out


# ---------------------------------------------------------------------------
# OCR lines -> regions
# ---------------------------------------------------------------------------
#: ``get_overlap_boxes_idx``'s minimum: more than this many pixels of overlap on
#: *both* axes before a text box counts as belonging to a region. A bare ``> 0``
#: would attach a line to any region it grazes.
MIN_OVERLAP_PX = 3

#: The label PaddleX gives a block it built from OCR alone (no layout box). Such
#: text is emitted rather than dropped -- losing it is the failure mode the card
#: names.
OTHER_TEXT_LABEL = "other_text"

def _line_box(points) -> list[float]:
    """A PP-OCR quadrilateral as an axis-aligned ``[x1, y1, x2, y2]``."""
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _overlaps(box1, box2, minimum: float) -> bool:
    """PaddleX's overlap test: more than ``minimum`` px on both axes."""
    return (min(box1[2], box2[2]) - max(box1[0], box2[0]) > minimum
            and min(box1[3], box2[3]) - max(box1[1], box2[1]) > minimum)


def _centre_distance(box, other) -> float:
    return (abs((box[0] + box[2]) / 2 - (other[0] + other[2]) / 2)
            + abs((box[1] + box[3]) / 2 - (other[1] + other[3]) / 2))


def _nearest_text_region(regions, box):
    candidates = [r for r in regions if r["label"] == "text"]
    if not candidates:
        return None
    return min(candidates, key=lambda r: _centre_distance(box, r["box"]))


def assign_lines(regions: list[dict], lines: Sequence) -> list[dict]:
    """Attach each OCR line to a region; returns the regions with ``lines`` set.

    ``lines`` are objects with ``text``, ``score`` and ``box`` (four ``(x, y)``
    points in PP-OCR's order). Each region gains ``"lines"``, ordered
    top-to-bottom then left-to-right inside the region, plus ``"text"`` from
    :func:`block_text`.

    The rule is PaddleX's first, the card's second:

    1. **Overlap** -- a line belongs to every region it overlaps by more than
       :data:`MIN_OVERLAP_PX` on both axes (``get_overlap_boxes_idx``, the
       assignment PaddleX actually performs).
    2. **Ties** -- when a line lands in several regions (a caption touching a
       figure's border, a line straddling a table rule) it goes to the
       **smallest** region, as the card specifies. PaddleX instead crops the
       intersection and re-runs recognition per region; with one det for the
       whole page that would produce two texts for the same pixels. The
       measured difference is in ``docs/ocr.md``.
    3. **No region** -- the line goes to the nearest ``text`` region by centre
       distance; if the page has no text region it becomes its own
       :data:`OTHER_TEXT_LABEL` block, so it still reaches ``text``.
    """
    out = [dict(r, lines=[]) for r in regions]
    if not lines:
        for region in out:
            region["text"] = ""
        return out

    loose: list[dict] = []
    for line in lines:
        entry = {"text": line.text, "score": float(line.score),
                 "box": _line_box(line.box)}
        hits = [r for r in out if _overlaps(entry["box"], r["box"], MIN_OVERLAP_PX)]
        if len(hits) > 1:
            hits = [min(hits, key=lambda r: bbox_area(r["box"]))]
        if hits:
            hits[0]["lines"].append(entry)
            continue
        target = _nearest_text_region(out, entry["box"])
        if target is not None:
            target["lines"].append(entry)
        else:
            loose.append(entry)

    for region in out:
        region["lines"].sort(key=lambda e: (e["box"][1] // 2, e["box"][0]))
        # Every label gets its text, figures included: PaddleX runs
        # ``update_text_content`` over every block, and the card asks for a
        # figure's text to follow its placeholder rather than be discarded.
        region["text"] = block_text(region["lines"], region["label"], region["box"])

    if loose:
        # One block per loose line: they have no layout box, so any grouping of
        # them would be invented. Kept in page order.
        loose.sort(key=lambda e: (e["box"][1] // 2, e["box"][0]))
        for entry in loose:
            box = [int(round(v)) for v in entry["box"]]
            out.append({
                "cls_id": -1, "label": OTHER_TEXT_LABEL, "score": 0.0,
                "box": box, "lines": [entry],
                "text": block_text([entry], OTHER_TEXT_LABEL, box),
            })
    return out


# ---------------------------------------------------------------------------
# reading order: PaddleX's xycut_enhanced
# ---------------------------------------------------------------------------
#: ``BLOCK_LABEL_MAP`` from ``paddlex/.../layout_parsing/setting.py``, verbatim.
#: These groupings decide which blocks are pinned to the page's top/bottom,
#: which are figures rather than text, and which may absorb child blocks -- so a
#: changed list changes the reading order of a real page.
BLOCK_LABEL_MAP: dict[str, list[str]] = {
    "doc_title_labels": ["doc_title"],
    "paragraph_title_labels": ["paragraph_title", "abstract_title",
                               "reference_title", "content_title"],
    "vision_labels": ["image", "table", "chart", "flowchart", "figure"],
    "vision_title_labels": ["table_title", "chart_title", "figure_title",
                            "figure_table_chart_title"],
    "unordered_labels": ["aside_text", "seal", "number", "formula_number"],
    "text_labels": ["text"],
    "header_labels": ["header", "header_image"],
    "footer_labels": ["footer", "footer_image", "footnote"],
}

#: ``XYCUT_SETTINGS``, verbatim. The weight map is what makes distance insertion
#: prefer "directly below" over "anywhere nearby" by four orders of magnitude.
XYCUT_SETTINGS = {
    "child_block_overlap_ratio_threshold": 0.1,
    "edge_distance_compare_tolerance_len": 2,
    "distance_weight_map": {"edge_weight": 10 ** 4, "up_edge_weight": 1,
                            "down_edge_weight": 0.0001},
    "cross_layout_ref_text_block_words_num_threshold": 10,
}


@dataclass
class _Block:
    """What ordering needs from a region, named as PaddleX names it.

    Field names match ``LayoutBlock``'s for everything the transcribed code
    reads, so the port can be compared with ``layout_objects.py`` without a
    translation table in the reader's head.
    """

    label: str
    bbox: list[int]
    order_label: str | None = None
    index: int = 0
    num_of_lines: int = 1
    width: float = 0.0
    height: float = 0.0
    area: float = 0.0
    short_side_length: float = 0.0
    long_side_length: float = 0.0
    direction: str = "horizontal"
    secondary_direction: str = "vertical"
    start_coordinate: float = 0.0
    end_coordinate: float = 0.0
    secondary_direction_start_coordinate: float = 0.0
    secondary_direction_end_coordinate: float = 0.0
    text_line_height: float = 1.0
    text_line_width: float = 1.0
    child_blocks: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.bbox = list(self.bbox)
        self.width = self.bbox[2] - self.bbox[0]
        self.height = self.bbox[3] - self.bbox[1]
        self.area = float(self.width) * float(self.height)
        self.direction = "horizontal" if self.width >= self.height else "vertical"
        self._update_direction_info()

    def _update_direction_info(self) -> None:
        if self.direction == "horizontal":
            self.secondary_direction = "vertical"
            self.short_side_length, self.long_side_length = self.height, self.width
            self.start_coordinate, self.end_coordinate = self.bbox[0], self.bbox[2]
            (self.secondary_direction_start_coordinate,
             self.secondary_direction_end_coordinate) = self.bbox[1], self.bbox[3]
        else:
            self.secondary_direction = "horizontal"
            self.short_side_length, self.long_side_length = self.width, self.height
            self.start_coordinate, self.end_coordinate = self.bbox[1], self.bbox[3]
            (self.secondary_direction_start_coordinate,
             self.secondary_direction_end_coordinate) = self.bbox[0], self.bbox[2]

    def get_centroid(self) -> tuple[float, float]:
        return ((self.bbox[0] + self.bbox[2]) / 2,
                (self.bbox[1] + self.bbox[3]) / 2)

    def append_child_block(self, child: "_Block") -> None:
        if not self.child_blocks:
            self.ori_bbox = list(self.bbox)
        x1, y1, x2, y2 = self.bbox
        c1, c2, c3, c4 = child.bbox
        self.bbox = [min(x1, c1), min(y1, c2), max(x2, c3), max(y2, c4)]
        self.width = self.bbox[2] - self.bbox[0]
        self.height = self.bbox[3] - self.bbox[1]
        self._update_direction_info()
        children = [child]
        if child.child_blocks:
            children.extend(child.get_child_blocks())
        self.child_blocks.extend(children)

    def get_child_blocks(self) -> list["_Block"]:
        self.bbox = self.ori_bbox
        children = list(self.child_blocks)
        self.child_blocks = []
        return children


class _Region:
    """PaddleX's ``LayoutRegion``, reduced to one page-sized region.

    PaddleX runs ``xycut_enhanced`` twice -- over the region detector's regions,
    then inside each -- and falls back to a single region holding every block
    when there is no region result. Without ``PP-DocBlockLayout`` (scoped out by
    the card) that fallback *is* the configuration, so this class exists mostly
    to hold the fields the transcribed code reads: ``direction``,
    ``text_line_height``/``text_line_width`` and the per-label index lists.
    """

    def __init__(self, bbox, blocks: list[_Block]) -> None:
        self.bbox = list(bbox)
        self.block_map: dict[int, _Block] = {}
        self.direction = "horizontal"
        self.secondary_direction = "vertical"
        self.direction_start_index, self.direction_end_index = 0, 2
        self.secondary_direction_start_index = 1
        self.secondary_direction_end_index = 3
        self.header_block_idxes: list[int] = []
        self.doc_title_block_idxes: list[int] = []
        self.paragraph_title_block_idxes: list[int] = []
        self.vision_block_idxes: list[int] = []
        self.vision_title_block_idxes: list[int] = []
        self.footer_block_idxes: list[int] = []
        self.unordered_block_idxes: list[int] = []
        self.normal_text_block_idxes: list[int] = []
        self.text_line_width = 20.0
        self.text_line_height = 10.0
        self._init_region_info(blocks)

    def _init_region_info(self, blocks: list[_Block]) -> None:
        horizontal = 0
        heights, widths = [], []
        for idx, block in enumerate(blocks):
            self.block_map[idx] = block
            block.index = idx
            if block.label in BLOCK_LABEL_MAP["header_labels"]:
                self.header_block_idxes.append(idx)
            elif block.label in BLOCK_LABEL_MAP["doc_title_labels"]:
                self.doc_title_block_idxes.append(idx)
            elif block.label in BLOCK_LABEL_MAP["paragraph_title_labels"]:
                self.paragraph_title_block_idxes.append(idx)
            elif block.label in BLOCK_LABEL_MAP["vision_labels"]:
                self.vision_block_idxes.append(idx)
            elif block.label in BLOCK_LABEL_MAP["vision_title_labels"]:
                self.vision_title_block_idxes.append(idx)
            elif block.label in BLOCK_LABEL_MAP["footer_labels"]:
                self.footer_block_idxes.append(idx)
            elif block.label in BLOCK_LABEL_MAP["unordered_labels"]:
                self.unordered_block_idxes.append(idx)
            else:
                self.normal_text_block_idxes.append(idx)
                heights.append(block.text_line_height)
                widths.append(block.text_line_width)
                if block.direction == "horizontal":
                    horizontal += 1
        # PaddleX decides the page direction from the *normal text* blocks, then
        # uses it for every projection in the ordering. A page of wide figures
        # with no text is therefore "horizontal" by fallback, which is what the
        # 0.5 comparison does here too.
        direction = ("horizontal"
                     if horizontal >= len(self.normal_text_block_idxes) * 0.5
                     else "vertical")
        if heights:
            import numpy as np
            self.text_line_height = float(np.mean(heights))
            self.text_line_width = float(np.mean(widths))
        self.update_direction(direction)

    def update_direction(self, direction: str | None) -> None:
        self.direction = direction or "horizontal"
        if self.direction == "horizontal":
            self.direction_start_index, self.direction_end_index = 0, 2
            self.secondary_direction_start_index = 1
            self.secondary_direction_end_index = 3
            self.secondary_direction = "vertical"
        else:
            self.direction_start_index, self.direction_end_index = 1, 3
            self.secondary_direction_start_index = 0
            self.secondary_direction_end_index = 2
            self.secondary_direction = "horizontal"


# -- projection helpers ------------------------------------------------------
def _projection_by_boxes(boxes, axis: int):
    """PaddleX ``projection_by_bboxes``: a 1-D coverage histogram along an axis."""
    import numpy as np

    columns = boxes[:, axis::2]
    length = int(abs(np.min(columns)) if np.min(columns) < 0 else np.max(columns))
    projection = np.zeros(length, dtype=int)
    for start, end in columns:
        projection[int(abs(start)):int(abs(end))] += 1
    return projection


def _split_projection_profile(values, min_value: float, min_gap: float):
    """PaddleX ``split_projection_profile``: runs of coverage, split on gaps."""
    import numpy as np

    significant = np.where(values > min_value)[0]
    if not len(significant):
        return None
    gaps = np.where(significant[1:] - significant[:-1] > min_gap)[0]
    return (np.insert(significant[gaps + 1], 0, significant[0]),
            np.append(significant[gaps], significant[-1] + 1))


def _recursive_yx_cut(boxes, indices, res: list[int], min_gap: int = 1) -> None:
    """PaddleX ``recursive_yx_cut``: project on Y, then each band on X, recurse.

    **This is the two-column mechanism.** A page is cut into horizontal bands;
    inside a band the x-projection splits into columns, and each column is
    recursed into (next band, then column again). Because the columns come out of
    one x-projection and are emitted left to right, a two-column page reads down
    column 1 and then down column 2 -- where a plain (y, x) sort interleaves them.
    """
    import numpy as np

    y_order = boxes[:, 1].argsort()
    y_boxes, y_indices = boxes[y_order], np.array(indices)[y_order]
    y_intervals = _split_projection_profile(
        _projection_by_boxes(y_boxes, 1), 0, 1)
    if not y_intervals:
        return
    for y_start, y_end in zip(*y_intervals):
        mask = (y_start <= y_boxes[:, 1]) & (y_boxes[:, 1] < y_end)
        chunk, chunk_indices = y_boxes[mask], y_indices[mask]
        x_order = chunk[:, 0].argsort()
        x_chunk, x_indices = chunk[x_order], chunk_indices[x_order]
        x_intervals = _split_projection_profile(
            _projection_by_boxes(x_chunk, 0), 0, min_gap)
        if not x_intervals:
            continue
        if len(x_intervals[0]) == 1:
            res.extend(x_indices)
            continue
        if np.min(x_chunk[:, 0]) < 0:
            x_intervals = np.flip(x_intervals, axis=1)
        for x_start, x_end in zip(*x_intervals):
            mask = (x_start <= abs(x_chunk[:, 0])) & (abs(x_chunk[:, 0]) < x_end)
            _recursive_yx_cut(x_chunk[mask], x_indices[mask], res)


def _recursive_xy_cut(boxes, indices, res: list[int], min_gap: int = 1) -> None:
    """PaddleX ``recursive_xy_cut``: the same cut with the axes swapped."""
    import numpy as np

    x_order = boxes[:, 0].argsort()
    x_boxes, x_indices = boxes[x_order], np.array(indices)[x_order]
    x_intervals = _split_projection_profile(
        _projection_by_boxes(x_boxes, 0), 0, 1)
    if not x_intervals:
        return
    if np.min(x_boxes[:, 0]) < 0:
        x_intervals = np.flip(x_intervals, axis=1)
    for x_start, x_end in zip(*x_intervals):
        mask = (x_start <= abs(x_boxes[:, 0])) & (abs(x_boxes[:, 0]) < x_end)
        chunk, chunk_indices = x_boxes[mask], x_indices[mask]
        y_order = chunk[:, 1].argsort()
        y_chunk, y_indices = chunk[y_order], chunk_indices[y_order]
        y_intervals = _split_projection_profile(
            _projection_by_boxes(y_chunk, 1), 0, min_gap)
        if not y_intervals:
            continue
        if len(y_intervals[0]) == 1:
            res.extend(y_indices)
            continue
        for y_start, y_end in zip(*y_intervals):
            mask = (y_start <= y_chunk[:, 1]) & (y_chunk[:, 1] < y_end)
            _recursive_xy_cut(y_chunk[mask], y_indices[mask], res)


def _sort_by_xycut(boxes, direction: str = "vertical") -> list[int]:
    import numpy as np

    array = np.asarray(boxes).astype(int)
    result: list[int] = []
    cut = _recursive_yx_cut if direction == "vertical" else _recursive_xy_cut
    cut(array, list(range(len(array))), result, 1)
    return result


def _sort_normal_blocks(blocks, line_height, line_width, direction):
    """PaddleX ``sort_normal_blocks``: quantise into row/column buckets, sort.

    The quantisation is the point -- dividing by an estimated line height keeps
    blocks on the same visual line together, so a heading and the paragraph
    beside it stay in left-to-right order instead of being split by a few pixels
    of vertical offset.
    """
    line_height = max(1.0, line_height)
    line_width = max(1.0, line_width)
    if direction == "horizontal":
        blocks.sort(key=lambda b: (
            b.bbox[1] // line_height,
            b.bbox[0] // line_width,
            b.get_centroid()[0] ** 2 + b.get_centroid()[1] ** 2))
    else:
        blocks.sort(key=lambda b: (
            -b.bbox[2] // line_width,
            b.bbox[1] // line_height,
            -b.get_centroid()[0] ** 2 + b.get_centroid()[1] ** 2))
    return blocks


def _discontinuous_projection(boxes, direction: str = "horizontal"):
    """PaddleX ``calculate_discontinuous_projection``: merge 1-D intervals."""
    import numpy as np

    boxes = np.array(boxes)
    intervals = boxes[:, [0, 2]] if direction == "horizontal" else boxes[:, [1, 3]]
    intervals = intervals[np.argsort(intervals[:, 0])]
    merged: list[tuple[float, float]] = []
    start, end = intervals[0]
    for lo, hi in intervals[1:]:
        if lo <= end:
            end = max(end, hi)
        else:
            merged.append((start, end))
            start, end = lo, hi
    merged.append((start, end))
    return merged


def _shrink_overlapping_boxes(boxes, direction="horizontal", min_threshold=0,
                              max_threshold=0.1):
    """PaddleX ``shrink_overlapping_boxes``: split touching boxes in half.

    Copied including the ``x2 == x1' or abs(x2 - x1') <= 3`` branches: boxes
    that merely *touch* are separated even when their projections do not overlap
    at all. Without that, two adjacent paragraph bands share a boundary row of
    pixels and the subsequent cut can put them in the same band.
    """
    current = boxes[0]
    for block in boxes[1:]:
        x1, y1, x2, y2 = current.bbox
        x1p, y1p, x2p, y2p = block.bbox
        cut = projection_overlap(current.bbox, block.bbox, direction=direction)
        match = projection_overlap(
            current.bbox, block.bbox,
            direction="horizontal" if direction == "vertical" else "vertical")
        if direction == "vertical":
            if ((match > 0 and min_threshold < cut < max_threshold)
                    or y2 == y1p or abs(y2 - y1p) <= 3):
                lo, hi = max(y1, y1p), min(y2, y2p)
                split = int((lo + hi) / 2)
                lo, hi = split - 1, split + 1
                if y1 < y1p:
                    current.bbox = [x1, y1, x2, lo]
                    block.bbox = [x1p, hi, x2p, y2p]
                else:
                    current.bbox = [x1, lo, x2, y2]
                    block.bbox = [x1p, y1p, x2p, hi]
        else:
            if ((match > 0 and min_threshold < cut < max_threshold)
                    or x2 == x1p or abs(x2 - x1p) <= 3):
                lo, hi = max(x1, x1p), min(x2, x2p)
                split = int((lo + hi) / 2)
                lo, hi = split - 1, split + 1
                if x1 < x1p:
                    current.bbox = [x1, y1, lo, y2]
                    block.bbox = [hi, y1p, x2p, y2p]
                else:
                    current.bbox = [x1, lo, x2, y2]
                    block.bbox = [x1p, y1p, hi, y2p]
        current = block
    return boxes


def _nearest_edge_distance(bbox1, bbox2, weight=(1.0, 1.0, 1.0, 1.0)) -> float:
    """PaddleX ``get_nearest_edge_distance``: the gap between two boxes, weighted."""
    x1, y1, x2, y2 = bbox1
    x1p, y1p, x2p, y2p = bbox2
    h_overlap = projection_overlap(bbox1, bbox2, "horizontal")
    v_overlap = projection_overlap(bbox1, bbox2, "vertical")
    if h_overlap > 0 and v_overlap > 0:
        return 0.0
    dx = dy = 0.0
    if h_overlap == 0:
        dx = min(abs(x1 - x2p), abs(x2 - x1p)) * (weight[0] if x2 < x1p else weight[1])
    if v_overlap == 0:
        dy = min(abs(y1 - y2p), abs(y2 - y1p)) * (weight[2] if y2 < y1p else weight[3])
    return dx + dy


def _weights_for(label: str, direction: str = "horizontal"):
    """PaddleX ``_get_weights``: which side of a block a neighbour may sit on."""
    if label == "doc_title":
        return [1, 0.1, 0.1, 1] if direction == "horizontal" else [0.2, 0.1, 1, 1]
    if label in ("paragraph_title", "table_title", "abstract", "image", "seal",
                 "chart", "figure"):
        return [1, 1, 0.1, 1]
    return [1, 1, 1, 0.1]


def _weighted_distance_insert(block: _Block, sorted_blocks: list[_Block],
                              region: _Region) -> list[_Block]:
    """PaddleX ``weighted_distance_insert``.

    Where a title or a figure lands in the order. The cost is
    ``edge*1e4 + up*1 + left*1e-4``: "below and close" beats "above", and among
    equals the nearer top edge wins. Transcribed including the ``tolerance_len``
    tie-break, which absorbs the two- or three-pixel wobble of a detected title
    box -- and the ``block_distance > sorted_distance`` branch, which decides
    before-vs-after for the two candidates that tie on cost.
    """
    tolerance_len = XYCUT_SETTINGS["edge_distance_compare_tolerance_len"]
    x1, y1, x2, y2 = block.bbox
    min_weighted = min_edge = min_up_edge = float("inf")
    nearest = 0
    for idx, other in enumerate(sorted_blocks):
        x1p, y1p, x2p, y2p = other.bbox
        weight = _weights_for(block.order_label or block.label, block.direction)
        edge = _nearest_edge_distance(block.bbox, other.bbox, weight)

        local_tolerance = tolerance_len
        if block.label in BLOCK_LABEL_MAP["doc_title_labels"]:
            local_tolerance = max(local_tolerance, max(1.0, region.text_line_width))
        if block.label == "abstract":
            local_tolerance *= 2
            edge = max(0.1, edge) * 10

        up_edge = y1p if region.direction == "horizontal" else -x2p
        left_edge = x1p if region.direction == "horizontal" else y1p
        is_below = y2p < y1 if region.direction == "horizontal" else x1p > x2

        if ((block.label not in BLOCK_LABEL_MAP["unordered_labels"]
             or block.label in BLOCK_LABEL_MAP["doc_title_labels"]
             or block.label in BLOCK_LABEL_MAP["paragraph_title_labels"]
             or block.label in BLOCK_LABEL_MAP["vision_labels"])
                and is_below):
            up_edge, left_edge = -up_edge, -left_edge

        if abs(min_up_edge - up_edge) <= local_tolerance:
            up_edge = min_up_edge

        # ``.get`` with the reference's own defaults, not ``[]``: PaddleX reads
        # ``left_edge_weight`` from a dict that only defines ``edge_weight`` and
        # ``up_edge_weight`` (the third key is misnamed ``down_edge_weight``
        # there), so the reference *always* falls back to 0.0001. A plain lookup
        # here raised KeyError on every page whose title or figure went through
        # distance insertion -- ``layout`` mode included, which is why this was
        # never a ``vl``-only fault.
        weights = XYCUT_SETTINGS["distance_weight_map"]
        weighted = (edge * weights.get("edge_weight", 1e4)
                    + up_edge * weights.get("up_edge_weight", 1.0)
                    + left_edge * weights.get("left_edge_weight", 1e-4))
        min_edge = min(edge, min_edge)
        min_up_edge = min(up_edge, min_up_edge)

        if weighted >= min_weighted:
            continue
        nearest = idx
        min_weighted = weighted
        if abs(y1 // 2 - y1p // 2) > 0:
            sorted_distance, block_distance = y1p, y1
        elif region.direction == "horizontal":
            if abs(x1 // 2 - x2 // 2) > 0:
                sorted_distance, block_distance = x1p, x1
            else:
                sc, bc = other.get_centroid(), block.get_centroid()
                sorted_distance = sc[0] ** 2 + sc[1] ** 2
                block_distance = bc[0] ** 2 + bc[1] ** 2
        elif abs(x1 - x2) > 0:
            sorted_distance, block_distance = -x2p, -x2
        else:
            sc, bc = other.get_centroid(), block.get_centroid()
            sorted_distance = sc[0] ** 2 + sc[1] ** 2
            block_distance = bc[0] ** 2 + bc[1] ** 2
        if block_distance > sorted_distance:
            nearest = idx + 1
    sorted_blocks.insert(nearest, block)
    return sorted_blocks


def _manhattan_insert(block: _Block, sorted_blocks: list[_Block],
                      **_kwargs) -> list[_Block]:
    """PaddleX ``manhattan_insert``: nearest by corner distance, insert *after*."""
    nearest, best = 0, float("inf")
    for idx, other in enumerate(sorted_blocks):
        distance = (abs(block.bbox[0] - other.bbox[0])
                    + abs(block.bbox[1] - other.bbox[1]))
        if distance < best:
            best, nearest = distance, idx
    sorted_blocks.insert(nearest + 1, block)
    return sorted_blocks


def _match_unsorted_blocks(sorted_blocks: list[_Block], unsorted: list[_Block],
                           region: _Region) -> list[_Block]:
    """PaddleX ``match_unsorted_blocks``: place each special block by its label."""
    inserters = {
        "cross_layout": _weighted_distance_insert,
        "paragraph_title": _weighted_distance_insert,
        "doc_title": _weighted_distance_insert,
        "vision_title": _weighted_distance_insert,
        "vision": _weighted_distance_insert,
        "unordered": _manhattan_insert,
        "other": _manhattan_insert,
    }
    unsorted = _sort_normal_blocks(
        unsorted, region.text_line_height, region.text_line_width, region.direction)
    for idx, block in enumerate(unsorted):
        order_label = block.order_label or "other"
        if idx == 0 and order_label == "doc_title":
            sorted_blocks.insert(0, block)
            continue
        sorted_blocks = inserters.get(order_label, _manhattan_insert)(
            block=block, sorted_blocks=sorted_blocks, region=region)
    return sorted_blocks


def _update_region_label(block: _Block) -> None:
    """PaddleX ``update_region_label``: detector label -> order label.

    The order label is what routes a block: ``header``/``footer`` are pinned to
    the page ends, ``unordered`` goes last, titles and vision blocks are inserted
    by distance, and ``normal_text`` is the only thing the xy-cut sorts.
    """
    if block.label in BLOCK_LABEL_MAP["header_labels"]:
        block.order_label = "header"
    elif block.label in BLOCK_LABEL_MAP["doc_title_labels"]:
        block.order_label = "doc_title"
    elif (block.label in BLOCK_LABEL_MAP["paragraph_title_labels"]
          and block.order_label is None):
        block.order_label = "paragraph_title"
    elif block.label in BLOCK_LABEL_MAP["vision_labels"]:
        block.order_label = "vision"
        block.num_of_lines = 1
    elif block.label in BLOCK_LABEL_MAP["footer_labels"]:
        block.order_label = "footer"
    elif block.label in BLOCK_LABEL_MAP["unordered_labels"]:
        block.order_label = "unordered"
    else:
        block.order_label = "normal_text"


def _mark_cross_layout(blocks: list[_Block], region: _Region) -> None:
    """PaddleX ``get_layout_structure``: mark blocks spanning two columns.

    A block that overlaps two blocks which do not overlap each other is
    *cross-layout* -- a full-width title above a two-column body, say. It is then
    ordered by distance instead of by the xy-cut, which would otherwise drop it
    into whichever column its left edge happens to fall in and split it from the
    text it belongs to.
    """
    blocks.sort(key=lambda b: (b.bbox[0], b.width))
    mask = ("doc_title", "cross_layout", "cross_reference")
    for i, block in enumerate(blocks):
        if block.order_label in mask:
            continue
        for j, ref in enumerate(blocks):
            if i == j or ref.order_label in mask:
                continue
            ratio = overlap_ratio(block.bbox, ref.bbox)
            if ratio:
                if ref.order_label == "vision":
                    ref.order_label = "cross_layout"
                    break
                if ratio > 0.1 and block.area < ref.area:
                    block.order_label = "cross_layout"
                    break
            if projection_overlap(block.bbox, ref.bbox, region.direction) > 0:
                for k, second in enumerate(blocks):
                    if k in (i, j) or second.order_label in mask:
                        continue
                    if overlap_ratio(block.bbox, second.bbox) > 0.1:
                        if second.order_label == "vision":
                            second.order_label = "cross_layout"
                            break
                        if (block.order_label == "vision"
                                or block.area < second.area):
                            block.order_label = "cross_layout"
                            break
                    second_match = projection_overlap(
                        block.bbox, second.bbox, region.direction)
                    ref_match = projection_overlap(
                        ref.bbox, second.bbox, region.direction)
                    secondary_match = projection_overlap(
                        ref.bbox, second.bbox, region.secondary_direction)
                    if second_match > 0 and ref_match == 0 and secondary_match > 0:
                        limit = XYCUT_SETTINGS[
                            "cross_layout_ref_text_block_words_num_threshold"]
                        if block.order_label in ("vision", "region") or (
                                ref.order_label == "normal_text"
                                and second.order_label == "normal_text"
                                and ref.long_side_length
                                > ref.text_line_height * limit
                                and second.long_side_length
                                > second.text_line_height * limit):
                            block.order_label = (
                                "cross_reference" if block.label == "reference"
                                else "cross_layout")


def _bands(region: _Region) -> list[list[_Block]]:
    """The page's ordered bands, as PaddleX's ``pre_process`` produces them.

    Reduced: the reference also hunts for *pre-cut coordinates* (centred blocks
    whose band holds exactly one box) and splits bands again at large gaps. Both
    exist to disambiguate ``PP-DocBlockLayout``'s regions -- the region detector
    the card scopes out. With one region over the whole page the bands are just
    the page's own y-bands, which is what this returns. The measured effect of
    the reduction is in ``docs/ocr.md``.
    """
    import numpy as np

    mask_labels = {"header", "unordered", "footer", "vision_footnote",
                   "sub_paragraph_title", "doc_title_text", "vision_title",
                   "sub_region"}
    blocks = list(region.block_map.values())
    for block in blocks:
        if block.order_label not in mask_labels:
            _update_region_label(block)
    live = [b for b in blocks if b.order_label not in mask_labels]
    if not live:
        return []
    if len(live) == 1:
        return [live]

    boxes = np.array([b.bbox for b in live])
    cut_direction = region.secondary_direction
    bands = _discontinuous_projection(boxes, direction=cut_direction)
    if len(bands) == 1:
        return [live]

    # Group on each band's *end* coordinate, which is what ``get_cut_blocks``
    # does in the reference (it walks the boxes sorted by that coordinate and
    # closes a group when the next box ends past the cut).
    axis_end = 3 if cut_direction == "vertical" else 2
    remaining = sorted(live, key=lambda b: b.bbox[axis_end])
    groups: list[list[_Block]] = []
    for _start, end in bands:
        group = [b for b in remaining if b.bbox[axis_end] <= end]
        if group:
            groups.append(group)
            remaining = [b for b in remaining if b not in group]
    if remaining:
        groups.append(remaining)
    return groups


def order_blocks(blocks: Sequence[_Block], page_hw) -> list[_Block]:
    """PaddleX ``xycut_enhanced`` over one region: the page's reading order.

    The steps, in the reference's order:

    1. classify each block (:func:`_update_region_label`);
    2. split the page into bands (:func:`_bands`);
    3. per band, mark cross-layout blocks (:func:`_mark_cross_layout`), then
       xy-cut everything else and insert titles/vision blocks by distance;
    4. headers first, footers, then unordered blocks last.

    Each band is ordered independently and the bands concatenate, which together
    with the x-projection inside a band is what makes a two-column page read down
    column 1 then column 2.
    """
    if not blocks:
        return []
    h, w = page_hw
    region = _Region([0, 0, int(w), int(h)], list(blocks))

    headers = _sort_normal_blocks(
        [region.block_map[i] for i in region.header_block_idxes],
        region.text_line_height, region.text_line_width, region.direction)
    footers = _sort_normal_blocks(
        [region.block_map[i] for i in region.footer_block_idxes],
        region.text_line_height, region.text_line_width, region.direction)
    unordered = _sort_normal_blocks(
        [region.block_map[i] for i in region.unordered_block_idxes],
        region.text_line_height, region.text_line_width, region.direction)

    ordered: list[_Block] = []
    unsorted: list[_Block] = []
    for band in _bands(region):
        _mark_cross_layout(band, region)
        doc_titles: list[_Block] = []
        cut_blocks: list[_Block] = []
        for block in band:
            if block.order_label not in ("cross_layout", "cross_reference",
                                         "doc_title", "unordered"):
                cut_blocks.append(block)
            elif block.label == "doc_title":
                doc_titles.append(block)
            else:
                unsorted.append(block)

        sorted_blocks: list[_Block] = []
        if cut_blocks:
            import copy

            import numpy as np

            boxes = np.array([b.bbox for b in cut_blocks])
            line_counts = [b.num_of_lines for b in cut_blocks]
            page_bands = _discontinuous_projection(boxes, direction=region.direction)
            # A **deep** copy: ``_shrink_overlapping_boxes`` rewrites each box in
            # place to separate touching neighbours, and those rewritten boxes
            # are only sorting scaffolding -- they must not reach the response.
            # ``index`` survives the copy, which is how the sorted result maps
            # back to the real block.
            to_sort = copy.deepcopy(cut_blocks)
            if region.direction == "vertical":
                for block in to_sort:
                    block.bbox = [-block.bbox[0], block.bbox[1],
                                  -block.bbox[2], block.bbox[3]]
            if len(page_bands) == 1 or max(line_counts) == 1:
                to_sort.sort(key=lambda b: (
                    b.bbox[region.secondary_direction_start_index]
                    // max(1, region.text_line_height // 2),
                    b.bbox[region.direction_start_index]))
                to_sort = _shrink_overlapping_boxes(
                    to_sort, region.secondary_direction)
                indices = _sort_by_xycut(
                    [b.bbox for b in to_sort], direction=region.secondary_direction)
            else:
                to_sort.sort(key=lambda b: (
                    b.bbox[region.direction_start_index]
                    // max(1, region.text_line_width // 2),
                    b.bbox[region.secondary_direction_start_index]))
                to_sort = _shrink_overlapping_boxes(
                    to_sort, region.secondary_direction)
                indices = _sort_by_xycut(
                    [b.bbox for b in to_sort], direction=region.direction)
            sorted_blocks = [region.block_map[to_sort[i].index] for i in indices]

        ordered.extend(_match_unsorted_blocks(sorted_blocks, doc_titles, region))

    ordered = _match_unsorted_blocks(ordered, unsorted, region)
    final = list(headers) + ordered + list(footers) + list(unordered)
    # PaddleX expands a block's absorbed children in place, walking the list as
    # it grows. The loop bound is re-read each pass for that reason.
    idx = 0
    while idx < len(final):
        final = _insert_child_blocks(final[idx], idx, final)
        idx += 1
    return final


def _insert_child_blocks(block: _Block, idx: int, sorted_blocks: list[_Block]):
    """PaddleX ``insert_child_blocks``: a parent's absorbed children follow it."""
    if not block.child_blocks:
        return sorted_blocks
    children = block.get_child_blocks()
    children.append(block)
    children = _sort_children(children, children[0].direction)
    sorted_blocks[idx] = children[0]
    for extra in children[1:]:
        idx += 1
        sorted_blocks.insert(idx, extra)
    return sorted_blocks


def _sort_children(blocks: list[_Block], direction="horizontal"):
    if direction == "horizontal":
        blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0],
                                   b.get_centroid()[0] ** 2 + b.get_centroid()[1] ** 2))
    else:
        blocks.sort(key=lambda b: (-b.bbox[2], b.bbox[1],
                                   -b.get_centroid()[0] ** 2 + b.get_centroid()[1] ** 2))
    return blocks


# ---------------------------------------------------------------------------
# the whole page, in order
# ---------------------------------------------------------------------------
def to_blocks(regions: Sequence[dict]) -> list[_Block]:
    """Regions -> ordering blocks, carrying the region index.

    ``num_of_lines`` is the region's own line count: PaddleX reads it off the
    block it built from OCR, and it is one of the two inputs that decide which
    sort the reference uses inside a band (``max(block_text_lines) == 1`` sends a
    one-line page down the "sort by row, then xy-cut vertically" path).
    """
    blocks = []
    for idx, region in enumerate(regions):
        block = _Block(label=region["label"], bbox=region["box"], index=idx)
        block.num_of_lines = max(1, len(region.get("lines") or []))
        blocks.append(block)
    return blocks


def order_regions(regions: Sequence[dict], page_hw) -> list[dict]:
    """The page's regions in PaddleX's reading order.

    A thin wrapper over :func:`order_blocks` that maps the ordered blocks back to
    their regions. ``_Block.index`` is the region's index, which is what makes
    the mapping exact rather than a lookup on equal boxes (two regions can share
    a box, and a lookup would then swap them).
    """
    regions = list(regions)
    if not regions:
        return []
    ordered = order_blocks(to_blocks(regions), page_hw)
    return [regions[block.index] for block in ordered]


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------
#: Labels PaddleX omits from Markdown entirely. ``PP-StructureV3.yaml``'s
#: ``markdown_ignore_labels``, verbatim, plus ``other_text``'s absence: loose
#: text is content, not furniture, and dropping it is the failure the card names.
MARKDOWN_IGNORE_LABELS = frozenset({"number", "footnote", "header",
                                    "header_image", "footer", "footer_image",
                                    "aside_text"})

#: Figure-like labels -> their placeholder. PaddleX emits an ``<img>`` pointing
#: at a crop it saved; this service returns text and no files, so the placeholder
#: is what the crop would have been. ``chart`` only gets a table when a chart
#: recogniser ran, and it has not.
FIGURE_PLACEHOLDERS = {"image": "[图片]", "chart": "[图表]", "seal": "[印章]",
                       "header_image": "[图片]", "footer_image": "[图片]"}

#: The marker a table region is preceded by. The card asks for tables as text
#: with no structure restored, and says so in a comment so a reader of the
#: Markdown is not misled into thinking the columns are the original ones.
TABLE_NOTE = "<!-- 表格：仅文字，未还原结构 -->"


def _collapse_newlines(text: str) -> str:
    """PaddleX ``_collapse_soft_newlines``: join hyphenation, then open lines."""
    return text.replace("-\n", "").replace("\n", " ")


def _normalize_newlines(text: str) -> str:
    """PaddleX ``_format_normalize_newlines``: one newline means a paragraph."""
    return text.replace("\n\n", "\n").replace("\n", "\n\n")


def _title_block(text: str, level: int) -> str:
    return _collapse_newlines(f"{'#' * level} {text}")


def _table_markdown(region: dict) -> str:
    """A table region's text: one visual line per table row, cells space-joined.

    Deliberately *not* a Markdown pipe table or HTML. Recovering cell boundaries
    needs SLANet plus a cell detector, and MYS-2615 measured that pipeline
    filling only 4 of 22 cells on a merged-cell table -- shipping that would be
    a table that looks structured and silently loses two whole columns
    (``docs/ocr-structure.md`` §3.4). Until then the honest output is the text,
    row by row, under :data:`TABLE_NOTE`.
    """
    lines = group_lines(region.get("lines") or [], "horizontal")
    rows = []
    for line in lines:
        cells = [span["text"] for span in sorted(line, key=lambda s: s["box"][0])]
        row = " ".join(cell for cell in cells if cell).strip()
        if row:
            rows.append(row)
    body = "\n".join(rows)
    return f"{TABLE_NOTE}\n\n{body}" if body else TABLE_NOTE


def _figure_markdown(region: dict) -> str:
    """A figure region: the placeholder, then any text found inside it."""
    placeholder = FIGURE_PLACEHOLDERS.get(region["label"], "[图片]")
    text = (region.get("text") or "").strip()
    return f"{placeholder}\n\n{text}" if text else placeholder


def _text_markdown(region: dict) -> str:
    """Body text, paragraph breaks preserved."""
    return _normalize_newlines((region.get("text") or "").strip())


def to_markdown(regions: Sequence[dict]) -> str:
    """Ordered regions -> the page's Markdown.

    The label→formatter table is PaddleX's ``build_handle_funcs_dict``, and the
    joining rule is ``MarkdownConverter.convert``'s: consecutive blocks are
    separated by one blank line, and a block whose text is empty contributes
    nothing. Labels in :data:`MARKDOWN_IGNORE_LABELS` are skipped; they stay in
    ``blocks`` on the response, which is what the card asks for.
    """
    parts: list[str] = []
    for region in regions:
        label = region["label"]
        if label in MARKDOWN_IGNORE_LABELS:
            continue
        if label in FIGURE_PLACEHOLDERS:
            piece = _figure_markdown(region)
        elif label == "table":
            piece = _table_markdown(region)
        elif label == "doc_title":
            piece = _title_block((region.get("text") or "").strip(), 1)
        elif label in ("paragraph_title", "abstract_title", "reference_title",
                       "content_title"):
            piece = _title_block((region.get("text") or "").strip(), 2)
        elif label == "formula":
            # No formula recogniser: the OCR text of the region, verbatim, which
            # is what the card asks for rather than an invented ``$$…$$``.
            piece = (region.get("text") or "").strip()
        else:
            piece = _text_markdown(region)
        if piece.strip():
            parts.append(piece)
    return "\n\n".join(parts)
