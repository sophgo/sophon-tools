"""PP-OCRv6: detection, rectification and recognition on the NPU.

The reference is PaddleOCR's own det+rec pair, run the way
``sophon-demo sample/PP-OCR/python/ppocr_{det,rec}_opencv.py`` runs it, with two
deliberate differences that are measured rather than stylistic:

* **the parameters come from ``model-config/ppocr_v6/ppocr.json``**, not from
  constants. The sophon demo hardcodes PP-OCR**v4**'s thresholds
  (``0.3/0.6/1.5``); PP-OCRv6's own ``inference.yml`` says
  ``0.2/0.45/1.4/max_candidates=3000``, and using v4's numbers loses the
  low-confidence boxes v6 deliberately emits. ``tools/ocr/make_golden.py`` and
  this module read the same file, which is what makes the golden a valid oracle.
* **crops are rectified by a four-point perspective warp**, not clipped to a
  bounding box. A 7-degree-skewed line has a bbox several times the glyph height,
  and the recogniser then sees the rotation smeared across the crop: the golden
  generator's bbox version read ``库盘点WarehousenySt`` where the reference reads
  ``仓库盘点单 Warehouse Inventory Sheet``. Warping took line agreement from 81 %
  to 97.9 %.

Both halves are pure host software -- OpenCV for resize/contour/warp, numpy for
the arithmetic, pyclipper for DB's unclip -- and the NPU only runs the two
forward passes. That split is what lets ``tests/test_ocr_postprocess.py`` check
the whole pipeline against the golden on x86, with recorded det maps and rec
logits standing in for the bmodels.

**OpenCV comes from the device.** The board ships Sophon's build at
``/opt/sophon/sophon-opencv-latest/opencv-python/cv2.so`` (4.8.0); nothing is
vendored, for the same reason ffmpeg is not (see docs/aux-models.md). The import
is attempted at worker start, and its failure is reported as a load error that
names the missing piece rather than as a 500 on the first request.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .aux_backend import AuxBusy, AuxRequestError, _Serialised
from .aux_native import AuxNativeError, NetEngine

logger = logging.getLogger(__name__)

#: Where the device keeps Sophon's OpenCV. Tried in this order; a build without
#: any of them cannot serve an OCR model at all (there is no pure-numpy
#: substitute for ``minAreaRect``/``warpPerspective`` at a sane speed, and
#: reimplementing DB's contour stage would be a second, untested implementation
#: of the thing the golden pins).
OPENCV_DIRS = (
    "/opt/sophon/sophon-opencv-latest/opencv-python",
    "/opt/sophon/sophon-opencv_2.3.0/opencv-python",
)

#: The config file inside the model-config directory, and the dictionary beside
#: it. Both are shipped in the deb, so a dfss download of the bmodels alone is a
#: complete model directory.
CONFIG_FILE = "ppocr.json"
DICT_FILE = "ppocr_keys_v1.txt"

#: Longest side fed to det, and the rec input height -- read from the config at
#: load, but repeated here as the two numbers the code assumes exist so a
#: config missing them fails at load rather than mid-request.
DET_INPUT_NAME = "x"


class OcrUnavailable(AuxNativeError):
    """This device cannot run OCR at all: a prerequisite is missing.

    Distinct from ``AuxRequestError`` (the caller's image is unusable) because
    the operator's action is different: install the SDK's OpenCV, or rebuild the
    library, rather than change the request.
    """


def ensure_opencv() -> "object":
    """Import ``cv2`` from the device's Sophon build; returns the module.

    ``sys.path`` is extended rather than ``PYTHONPATH`` set: the service runs one
    interpreter and a module-level import is the only place that matters, while
    an environment variable would have to be baked into the systemd unit and
    would then also apply to the chat worker, which has no use for OpenCV.

    A plain ``import cv2`` is tried first so a dev checkout with an ordinary
    opencv-python (x86, for the golden tests) works unchanged.
    """
    import importlib
    import sys

    try:
        return importlib.import_module("cv2")
    except ImportError:
        pass
    tried = []
    for directory in OPENCV_DIRS:
        if not os.path.isdir(directory):
            tried.append(f"{directory}（不存在）")
            continue
        if directory not in sys.path:
            sys.path.insert(0, directory)
        try:
            return importlib.import_module("cv2")
        except ImportError as exc:
            tried.append(f"{directory}（{exc}）")
    raise OcrUnavailable(
        "缺少 sophon-opencv：本机找不到可导入的 cv2（路径来自设备自带的 SDK）。"
        f"已尝试：{'；'.join(tried) or '默认 site-packages'}。"
        "OCR 的前后处理依赖它，请确认设备上安装了 sophon-opencv-latest"
        "（/opt/sophon/sophon-opencv-latest/opencv-python/cv2.so）")


def ensure_pyclipper():
    """``pyclipper``, vendored by scripts/package.sh (DB's unclip needs it)."""
    try:
        import pyclipper
    except ImportError as exc:  # pragma: no cover - the release always has it
        raise OcrUnavailable(
            "缺少 pyclipper：DB 后处理的文本框外扩需要它。"
            "发布包已内置（scripts/package.sh 以 --no-deps 装入 vendor/），"
            f"开发环境请 pip install pyclipper（{exc}）") from exc
    return pyclipper


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OcrConfig:
    """Everything ``ppocr.json`` says, in the shapes the code uses.

    Parsed once at load. Every number below appears in that file; none is
    duplicated as a default here, because the whole point of the file is that
    the model's own ``inference.yml`` is authoritative and a second copy would
    drift.
    """

    det_input_side: int
    det_mean: tuple[float, float, float]
    det_std: tuple[float, float, float]
    thresh: float
    box_thresh: float
    unclip_ratio: float
    max_candidates: int
    min_size: int
    rec_height: int
    #: (max ratio, width, bmodel file) in ascending width order.
    rec_tiers: tuple[tuple[float, int, str], ...]
    squash_tolerance: float
    rec_mean: float
    rec_scale: float
    labels: tuple[str, ...]
    raw: dict = field(repr=False, default_factory=dict)


def _require(mapping: dict, key: str, where: str):
    if key not in mapping:
        raise ValueError(f"{where} 缺少字段 {key!r}")
    return mapping[key]


def load_config(config_dir: str | Path) -> OcrConfig:
    """Read ``ppocr.json`` and the dictionary from ``config_dir``.

    Raises ``ValueError`` with a message naming the file and field: this runs at
    worker start, where the message becomes the model's ``load_error`` and is
    the only thing an operator sees.
    """
    directory = Path(config_dir)
    config_path = directory / CONFIG_FILE
    if not config_path.is_file():
        raise ValueError(f"找不到 {config_path}（OCR 模型需要随包的 ppocr.json）")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{config_path} 不是合法 JSON：{exc}") from exc

    det = _require(raw, "det", CONFIG_FILE)
    rec = _require(raw, "rec", CONFIG_FILE)
    det_pre = _require(det, "preprocess", "det")
    det_post = _require(det, "postprocess", "det")
    rec_pre = _require(rec, "preprocess", "rec")
    rec_post = _require(rec, "postprocess", "rec")
    selection = _require(rec, "width_selection", "rec")

    normalize = _require(det_pre, "normalize", "det.preprocess")
    resize = _require(det_pre, "resize", "det.preprocess")
    rec_normalize = _require(rec_pre, "normalize", "rec.preprocess")
    rec_resize = _require(rec_pre, "resize", "rec.preprocess")

    side = int(_require(det, "input", "det")["shape"][2])
    if int(resize["limit_side_len"]) != side:
        raise ValueError(
            f"det 的 resize.limit_side_len={resize['limit_side_len']} 与 "
            f"input.shape 的长边 {side} 不一致；后处理裁剪的区域模型没有输出过")

    bmodels = _require(rec, "bmodels", "rec")
    tiers = []
    for entry in bmodels:
        tiers.append((float("inf"), int(entry["width"]), str(entry["file"])))
    # The selector's own table is authoritative for the cut points; the bmodel
    # list just says which widths exist. Joining them here means a config that
    # adds a tier without compiling it (or the reverse) fails at load.
    cut = {int(t["width"]): float(t["max_ratio"]) for t in _require(selection, "tiers",
                                                                  "rec.width_selection")}
    joined = []
    for order, (_inf, width, name) in enumerate(sorted(tiers, key=lambda t: t[1])):
        if width not in cut:
            raise ValueError(f"rec.width_selection 里没有 {width} 档的 max_ratio")
        joined.append((cut[width], width, name))
    joined.sort(key=lambda t: t[1])

    dict_path = directory / str(rec_post.get("labels_file", DICT_FILE))
    if not dict_path.is_file():
        raise ValueError(f"找不到字符字典 {dict_path}")
    lines = dict_path.read_text(encoding="utf-8").splitlines()
    class_count = int(_require(rec_post, "class_count", "rec.postprocess"))
    # blank first, space last: PaddleOCR's CTC layout. The arithmetic has to
    # hold or every recognised character is shifted by one row of the table,
    # which reads as plausible text rather than as an error.
    if 1 + len(lines) + 1 != class_count:
        raise ValueError(
            f"字典 {dict_path.name} 有 {len(lines)} 行，加上 blank 与空格应为 "
            f"{class_count} 类（bmodel 输出 {class_count}），实际 1+{len(lines)}+1="
            f"{1 + len(lines) + 1}")

    return OcrConfig(
        det_input_side=side,
        det_mean=tuple(float(x) for x in normalize["mean"]),
        det_std=tuple(float(x) for x in normalize["std"]),
        thresh=float(det_post["thresh"]),
        box_thresh=float(det_post["box_thresh"]),
        unclip_ratio=float(det_post["unclip_ratio"]),
        max_candidates=int(det_post["max_candidates"]),
        min_size=int(det_post["min_size"]),
        rec_height=int(rec_resize["height"]),
        rec_tiers=tuple(joined),
        squash_tolerance=float(selection.get("squash_tolerance", 1.0)),
        rec_mean=float(rec_normalize["mean"]),
        rec_scale=float(rec_normalize["scale"]),
        labels=("<blank>", *lines, " "),
        raw=raw,
    )


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OcrLine:
    """One recognised line: its text, its confidence, and where it was."""

    text: str
    score: float
    #: Four points in the *source* image's coordinates, ordered top-left,
    #: top-right, bottom-right, bottom-left -- the order PaddleOCR emits.
    box: tuple[tuple[float, float], ...]
    #: Which compiled rec width this line ran at, for the record and for
    #: debugging a line that decoded badly.
    width_tier: int = 0


@dataclass(frozen=True)
class OcrResult:
    """One image's transcription."""

    text: str
    lines: list[OcrLine]
    det_ms: float
    rec_ms: float
    #: The image's size, which the record reports instead of the image itself.
    width: int
    height: int
    #: ``"lines"`` for the flat transcription, ``"layout"`` for a page laid out
    #: into regions. Always present so a caller never has to guess, and equal to
    #: the request's mode -- which is what makes the two modes distinguishable in
    #: an inference record after the fact.
    mode: str = "lines"
    #: Layout mode only: the page's regions in reading order. Each is
    #: ``{"index", "type", "label", "score", "box", "text", "lines"}``; see
    #: ``app.engine.ocr_layout.assign_lines`` for how a line is placed.
    blocks: tuple[dict, ...] = ()
    #: Layout mode only: how long detection took, separately from det+rec, so a
    #: page's cost can be attributed. ``det_ms``/``rec_ms`` still count the OCR
    #: work itself.
    layout_ms: float = 0.0


#: The two values ``mode`` may take. ``lines`` is the default in every entry
#: point -- API field, worker op, MCP argument -- so an existing caller that
#: never sends the field keeps the response it had.
MODE_LINES = "lines"
MODE_LAYOUT = "layout"
#: ``mode: "vl"`` belongs to ``/v1/ocr``, but *not* to this backend's
#: ``recognise``: a whole page is two ops on two workers (``detect_page`` here,
#: ``ocr_page`` on the VLM -- see ``app/engine/ocr_vl_page.py``). It is named
#: here so the API, the docs and the worker's own messages cannot disagree about
#: the set of modes, and kept out of :data:`MODES` so ``_check_mode`` still
#: refuses it on the op that cannot serve it.
MODE_VL = "vl"
MODES = (MODE_LINES, MODE_LAYOUT)


class OcrModeUnavailable(OcrUnavailable):
    """``mode: "layout"`` was asked for and this installation cannot serve it.

    A separate class from :class:`OcrUnavailable` because the operator's action
    is different and so is the HTTP status: the model *works*, it is one file
    short, and the fix is to update it in the console's model page rather than
    to install an SDK. The worker turns this into ``invalid_request`` (a 400)
    with a message naming the file, which is what the card asks for.
    """


def _check_mode(mode) -> str:
    """``mode`` as one of :data:`MODES`, or a 400-shaped refusal.

    Validated in the *worker*, not only at the API: the worker is the thing that
    owns the mode's meaning, and a second caller (the console's test route, the
    MCP bridge) must not be able to reach the pipeline with a third value.
    Absent is ``lines`` -- the card's "缺省为 lines", and what keeps an existing
    caller's request byte-identical.
    """
    if mode is None:
        return MODE_LINES
    value = str(mode).strip().lower()
    if value in MODES:
        return value
    raise AuxRequestError(
        f"mode 只能是 {' / '.join(MODES)}（收到 {mode!r}）；"
        f"缺省是 {MODE_LINES}")


def _block_type(label: str) -> str:
    """The response's coarse ``type`` for a PP-DocLayout label.

    The card lists ``title | text | table | image | formula | header | footer |
    …`` with the ellipsis doing real work: the model has 23 classes and a caller
    that wants "is this text or not" should not have to know all of them. The
    raw PP-DocLayout class travels beside it in ``label``, so nothing is lost.

    The assignments follow PaddleX's own groupings (``BLOCK_LABEL_MAP``) rather
    than being invented here.
    """
    if label == "doc_title":
        return "title"
    if label in ("paragraph_title", "abstract_title", "reference_title",
                 "content_title"):
        return "subtitle"
    if label in ("table", "table_title"):
        return "table"
    if label in ("image", "header_image", "footer_image"):
        return "image"
    if label == "chart" or label == "chart_title":
        return "chart"
    if label == "formula" or label == "formula_number":
        return "formula"
    if label == "header":
        return "header"
    if label == "footer" or label == "footnote":
        return "footer"
    if label == "seal":
        return "seal"
    if label in ("number", "aside_text"):
        return label
    return "text"


def _take_line(pool: dict, entry: dict):
    """The ``OcrLine`` a region entry came from, consumed from ``pool``.

    ``assign_lines`` works on copies that carry an axis-aligned box; the response
    wants PP-OCR's own quadrilateral and its width tier. The two are matched on
    (text, axis-aligned box), and each pool entry is used once -- two identical
    lines on a page are a real thing (a repeated header), and handing the same
    object out twice would make ``lines`` claim a line twice.
    """
    candidates = pool.get(entry["text"]) or []
    for index, line in enumerate(candidates):
        xs = [p[0] for p in line.box]
        ys = [p[1] for p in line.box]
        box = [min(xs), min(ys), max(xs), max(ys)]
        if all(abs(a - b) <= 0.5 for a, b in zip(box, entry["box"])):
            return candidates.pop(index)
    return None


# ---------------------------------------------------------------------------
# preprocessing
# ---------------------------------------------------------------------------
def det_input(bgr, cfg: OcrConfig):
    """PaddleOCR's ``DetResizeForTest`` + normalise + CHW + zero pad.

    Returns ``(padded[N,3,S,S], (src_h, src_w, resize_h, resize_w))``. The four
    numbers are what the postprocess scales boxes back through, and they are
    returned rather than recomputed there because getting the rule wrong twice
    would be indistinguishable from getting it wrong once.
    """
    import cv2
    import numpy as np

    side = cfg.det_input_side
    h, w = bgr.shape[:2]
    longest = max(h, w)
    # Shrink only: an image smaller than the input is used at its own size and
    # padded, not blown up. That is what the reference does and what the golden
    # recorded -- two of the seven test images are smaller than 736.
    ratio = float(side) / longest if longest >= side else 1.0
    resize_h, resize_w = int(h * ratio), int(w * ratio)
    if (resize_h, resize_w) != (h, w):
        bgr = cv2.resize(bgr, (resize_w, resize_h), interpolation=cv2.INTER_LINEAR)

    img = bgr.astype(np.float32) / 255.0
    img = (img - np.array(cfg.det_mean, dtype=np.float32)) / np.array(
        cfg.det_std, dtype=np.float32)
    img = np.transpose(img, (2, 0, 1))

    padded = np.zeros((3, side, side), dtype=np.float32)
    padded[:, :resize_h, :resize_w] = img
    return padded[None, ...], (h, w, resize_h, resize_w)


def _mini_box(contour):
    """PaddleOCR's ``get_mini_boxes``: min-area rectangle, points ordered.

    Byte-for-byte the reference's rule, including the sort on x and the two
    conditional swaps. It looks like it could be simplified and cannot: the
    order decides which corner is "top-left" for the perspective warp, and a
    warp with the corners rotated 90 degrees produces a recognisable but
    transposed crop.
    """
    import cv2

    rect = cv2.minAreaRect(contour)
    points = sorted(list(cv2.boxPoints(rect)), key=lambda p: p[0])
    idx_1 = idx_3 = 0
    idx_2 = idx_4 = 1
    if points[1][1] > points[0][1]:
        idx_1, idx_4 = 0, 1
    else:
        idx_1, idx_4 = 1, 0
    if points[3][1] > points[2][1]:
        idx_2, idx_3 = 2, 3
    else:
        idx_2, idx_3 = 3, 2
    box = [points[idx_1], points[idx_2], points[idx_3], points[idx_4]]
    return box, min(rect[1])


def _box_score_fast(bitmap, box):
    """Mean probability inside the box -- PaddleOCR's ``box_score_fast``."""
    import cv2
    import numpy as np

    h, w = bitmap.shape[:2]
    box = box.copy()
    xmin = np.clip(np.floor(box[:, 0].min()).astype(np.int32), 0, w - 1)
    xmax = np.clip(np.ceil(box[:, 0].max()).astype(np.int32), 0, w - 1)
    ymin = np.clip(np.floor(box[:, 1].min()).astype(np.int32), 0, h - 1)
    ymax = np.clip(np.ceil(box[:, 1].max()).astype(np.int32), 0, h - 1)
    mask = np.zeros((ymax - ymin + 1, xmax - xmin + 1), dtype=np.uint8)
    box[:, 0] = box[:, 0] - xmin
    box[:, 1] = box[:, 1] - ymin
    cv2.fillPoly(mask, box.reshape(1, -1, 2).astype(np.int32), 1)
    return cv2.mean(bitmap[ymin:ymax + 1, xmin:xmax + 1], mask)[0]


def _polygon_area_and_perimeter(points):
    """Area (shoelace) and perimeter of a simple polygon, in numpy.

    PaddleOCR calls ``Polygon(points).area / Polygon(points).length`` from
    shapely for exactly these two numbers. shapely is a large native dependency
    whose only use here is this division, so it is computed directly; the result
    is identical for a simple (non-self-intersecting) polygon, which a DB
    min-area-rectangle always is. ``tests/test_ocr_postprocess.py`` pins the
    boxes it produces against the golden, so a difference would fail there
    rather than show up as slightly different text on the board.
    """
    import numpy as np

    pts = np.asarray(points, dtype=np.float64)
    x, y = pts[:, 0], pts[:, 1]
    area = 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
    deltas = pts - np.roll(pts, -1, axis=0)
    perimeter = float(np.sqrt((deltas ** 2).sum(axis=1)).sum())
    return area, perimeter


def _unclip(points, unclip_ratio):
    """DB's text-region expansion: offset the polygon outwards by area/perimeter."""
    import numpy as np
    import pyclipper

    area, perimeter = _polygon_area_and_perimeter(points)
    if perimeter <= 0.0:
        return np.asarray(points)
    distance = area * unclip_ratio / perimeter
    offset = pyclipper.PyclipperOffset()
    offset.AddPath(np.asarray(points, dtype=np.float64).tolist(),
                   pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    expanded = offset.Execute(distance)
    return np.array(expanded[0]) if expanded else np.asarray(points)


def det_postprocess(prob, shape, cfg: OcrConfig):
    """DB postprocess: probability map -> boxes in source coordinates.

    ``prob`` is the map the det graph produced, at the model's resolution.
    Returns ``(boxes, scores)`` where each box is four [x, y] pairs.
    """
    import cv2
    import numpy as np

    src_h, src_w, resize_h, resize_w = shape
    pred = prob[:resize_h, :resize_w]
    segmentation = pred > cfg.thresh

    found = cv2.findContours((segmentation.astype(np.uint8) * 255), cv2.RETR_LIST,
                             cv2.CHAIN_APPROX_SIMPLE)
    # OpenCV 4 returns (image, contours, hierarchy); OpenCV 5 returns
    # (contours, hierarchy). The contours are the second element only in the
    # 3-tuple form, and picking the wrong one silently yields zero boxes because
    # the hierarchy array contains no contour.
    contours = found[1] if len(found) == 3 else found[0]
    if isinstance(contours, np.ndarray):
        contours = [contours] if contours.ndim == 3 else []

    boxes, scores = [], []
    for contour in list(contours)[: cfg.max_candidates]:
        if contour is None or len(contour) < 4:
            continue
        contour = np.asarray(contour, dtype=np.int32).reshape(-1, 1, 2)
        points, sside = _mini_box(contour)
        if sside < cfg.min_size:
            continue
        points = np.array(points)
        score = _box_score_fast(pred, points.reshape(-1, 2))
        if cfg.box_thresh > score:
            continue
        box = _unclip(points, cfg.unclip_ratio).reshape(-1, 1, 2)
        box, sside = _mini_box(box)
        if sside < cfg.min_size + 2:
            continue
        box = np.array(box)
        # Back to the *source* image's pixels, not the resized canvas.
        box[:, 0] = np.clip(np.round(box[:, 0] / resize_w * src_w), 0, src_w)
        box[:, 1] = np.clip(np.round(box[:, 1] / resize_h * src_h), 0, src_h)
        boxes.append([[float(x), float(y)] for x, y in box])
        scores.append(float(score))
    return boxes, scores


def _order_clockwise(points):
    """Order four points top-left, top-right, bottom-right, bottom-left."""
    import numpy as np

    pts = np.asarray(points, dtype=np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).reshape(-1)
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)],
                     pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def crop_quad(bgr, box):
    """Rectify a det quadrilateral to an upright image, or None when degenerate.

    A four-point perspective warp, not a bounding box: see the module docstring
    for the measured difference on a 7-degree line.
    """
    import cv2
    import numpy as np

    pts = _order_clockwise(box)
    w = int(max(np.linalg.norm(pts[0] - pts[1]), np.linalg.norm(pts[2] - pts[3])))
    h = int(max(np.linalg.norm(pts[0] - pts[3]), np.linalg.norm(pts[1] - pts[2])))
    if w < 2 or h < 2:
        return None
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(pts, dst)
    return cv2.warpPerspective(bgr, matrix, (w, h))


def rec_width_for(crop_h: int, crop_w: int, cfg: OcrConfig) -> int:
    """The narrowest compiled width that does not squash this line.

    ``ratio = w/h`` against each tier's ``max_ratio``, with the config's
    ``squash_tolerance`` (1.15) letting a slightly-longer line use the narrower,
    cheaper model. Measured: without the tolerance a 34.8:1 report line is sent
    to the 640 tier, compressed 2.3x horizontally, and decodes as ``dubuy`` where
    1600 reads the line correctly.
    """
    # The tier's ``max_ratio`` is width/height (6.667 for 320), so the comparison
    # is between aspect ratios, not pixels -- multiplying by the rec height here
    # would make every line select the widest tier.
    ratio = (crop_w / float(crop_h)) * cfg.squash_tolerance
    for max_ratio, width, _name in cfg.rec_tiers:
        if ratio <= max_ratio:
            return width
    return cfg.rec_tiers[-1][1]


def rec_input(crop, width: int, cfg: OcrConfig):
    """PaddleOCR's rec resize (height 48, keep aspect) + normalise + right pad."""
    import cv2
    import numpy as np

    height = cfg.rec_height
    h, w = crop.shape[:2]
    resized_w = max(1, min(int(height * w / float(h)), width))
    img = cv2.resize(crop, (resized_w, height))
    img = img.astype(np.float32)
    img = np.transpose(img, (2, 0, 1))
    img -= cfg.rec_mean
    img *= cfg.rec_scale
    padded = np.zeros((3, height, width), dtype=np.float32)
    padded[:, :, :resized_w] = img
    return padded[None, ...]


def ctc_decode(probs, labels: Sequence[str]) -> tuple[str, float]:
    """Greedy CTC: argmax, collapse repeats, drop blank, map, mean confidence.

    ``probs`` is ``[T, C]`` and already softmaxed by the graph, so a second
    softmax would look plausible and be wrong. Confidence is the mean over the
    steps that survived (as PaddleOCR and sophon-demo compute it), not over all
    ``T`` -- padding steps would drag a short line's confidence down in
    proportion to how much room it did not use.
    """
    import numpy as np

    arr = np.asarray(probs)
    idx = arr.argmax(axis=1)
    conf = arr.max(axis=1)
    chars: list[str] = []
    confs: list[float] = []
    prev = -1
    for t in range(idx.shape[0]):
        c = int(idx[t])
        if c != 0 and c != prev:
            chars.append(labels[c])
            confs.append(float(conf[t]))
        prev = c
    text = "".join(chars)
    if not confs:
        return "", 0.0
    return text, float(sum(confs) / len(confs))


# ---------------------------------------------------------------------------
# reading order
# ---------------------------------------------------------------------------
def reading_order(boxes: Sequence[Sequence[Sequence[float]]]) -> list[int]:
    """Indices of ``boxes`` in reading order: top to bottom, then left to right.

    Grouped into lines first, because a page of two-column text or a table would
    otherwise interleave columns purely by y coordinate -- two boxes on the same
    visual line differ by a few pixels, and sorting strictly by y turns a
    paragraph into alternating fragments.

    A box joins an existing line when its vertical centre is within half the
    line's median height of that line's centre; lines are then emitted top to
    bottom, and within a line left to right.
    """
    entries = []
    for i, box in enumerate(boxes):
        ys = [float(p[1]) for p in box]
        xs = [float(p[0]) for p in box]
        entries.append({
            "index": i,
            "top": min(ys), "bottom": max(ys),
            "left": min(xs), "centre": (min(ys) + max(ys)) / 2.0,
            "height": max(1.0, max(ys) - min(ys)),
        })
    entries.sort(key=lambda e: e["centre"])

    lines: list[list[dict]] = []
    for entry in entries:
        placed = False
        for line in lines:
            median = sorted(e["height"] for e in line)[len(line) // 2]
            if abs(entry["centre"] - line[0]["centre"]) <= median * 0.5:
                line.append(entry)
                placed = True
                break
        if not placed:
            lines.append([entry])
    for line in lines:
        line.sort(key=lambda e: e["left"])
    lines.sort(key=lambda line: sum(e["centre"] for e in line) / len(line))
    return [entry["index"] for line in lines for entry in line]


# ---------------------------------------------------------------------------
# the backend
# ---------------------------------------------------------------------------
class OcrBackend:
    """PP-OCRv6 det + three rec tiers, behind the auxiliary RPC surface.

    One model directory holds four bmodels (det at 736 and rec at 320/640/1600).
    ``model_path`` is the det build; the rec files are found by name beside it,
    which is the layout ``CATALOG`` downloads into and the layout an operator
    copying a directory by hand will produce.

    The rec engines are created lazily, on first use of each tier. Loading all
    four at start would allocate ~220 MB of NPU memory for a 320-tier page that
    may never arrive, and the admission check upstream is computed from the
    total anyway.
    """

    kind = "ocr"
    supports_vision = False

    def __init__(self, model_path: str, config_dir: str, model_id: str,
                 lib_path: str | None = None, dev_id: int = 0,
                 max_queue: int = 16) -> None:
        from .aux_backend import _default_lib_path

        self._model_id = model_id
        self._config_dir = str(config_dir)
        self._model_path = str(model_path)
        self._lib_path = lib_path or _default_lib_path()
        self._dev_id = dev_id
        self._gate = _Serialised(max_queue)
        self._lock = threading.Lock()

        # Layout mode's engine and config. Both stay ``None`` until the first
        # ``layout`` request: a deployment that only ever asks for ``lines``
        # never spends the ~21.5 MB the layout bmodel maps.
        self._layout: NetEngine | None = None
        self._layout_cfg = None

        # Prerequisites first, so a missing OpenCV or pyclipper is the load
        # error instead of the first request's 500.
        self._cv2 = ensure_opencv()
        self._pyclipper = ensure_pyclipper()
        self._cfg = load_config(config_dir)

        self._det = NetEngine(model_path, self._lib_path, dev_id)
        try:
            self._check_det_graph()
            self._rec: dict[int, NetEngine] = {}
            self._rec_paths = self._find_rec_models(Path(model_path).parent)
        except BaseException:
            self._det.close()
            raise

    # -- geometry --------------------------------------------------------
    def _check_det_graph(self) -> None:
        """The det bmodel must take the tensor the config describes.

        Checked at load rather than assumed: a wrong det build (say, the 960
        variant) would still run and produce boxes scaled by the wrong factor,
        which reads as "the model got worse" rather than as a configuration
        error. The rec graphs are checked when each tier is first used, since
        only then is one loaded.
        """
        side = self._cfg.det_input_side
        expected = (1, 3, side, side)
        if self._det.num_inputs != 1:
            raise OcrUnavailable(
                f"det bmodel 有 {self._det.num_inputs} 个输入，OCR 的 det 图只有一个")
        if tuple(self._det.input_shapes[0]) != expected:
            raise OcrUnavailable(
                f"det bmodel 的输入是 {self._det.input_shapes[0]}，"
                f"而 ppocr.json 描述的是 {expected}；两者必须一致")

    def _find_rec_models(self, directory: Path) -> dict[int, Path]:
        """Locate each tier's rec bmodel beside the det one.

        Matched by the file name recorded in the config, so the mapping is data
        rather than a guess: a directory holding two builds of the same tier
        cannot silently pick the older one.
        """
        found: dict[int, Path] = {}
        missing = []
        for _max_ratio, width, filename in self._cfg.rec_tiers:
            path = directory / filename
            if not path.is_file():
                missing.append(filename)
                continue
            found[width] = path
        if missing:
            raise OcrUnavailable(
                f"OCR 模型目录 {directory} 缺少 rec bmodel：{'、'.join(missing)}；"
                "一个 OCR 模型需要 det 和全部三档 rec")
        return found

    # -- properties the manager/API read ---------------------------------
    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def context_length(self) -> int:
        """What /v1/models reports. OCR has no context; the det input is the
        one number that describes the model's working size, so it is reported
        instead of a meaningless zero."""
        return self._cfg.det_input_side

    # -- the request ------------------------------------------------------
    async def recognise(self, image: bytes, mode: str = MODE_LINES) -> OcrResult:
        """Decode ``image``, detect lines, recognise each one.

        The whole pipeline runs in one worker thread: det must finish before any
        crop exists, so serialising the halves buys nothing but a second
        hand-off, and the NPU is one device anyway.

        ``mode="layout"`` reuses **that same det and rec pass** and only adds a
        layout pass plus the region assembly -- the card's rule is one det for
        the whole page, never one per region. So the extra cost of layout mode
        is the layout model's own ~3 ms plus the ordering, not a second OCR.
        """
        mode = _check_mode(mode)
        return await self._gate.run(self._recognise_sync, image, mode)

    def _recognise_sync(self, image: bytes, mode: str = MODE_LINES) -> OcrResult:
        import numpy as np

        cv2 = self._cv2
        buf = np.frombuffer(image, dtype=np.uint8)
        bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if bgr is None:
            raise AuxRequestError(
                "无法解码这张图片；支持 PNG/JPEG/BMP/WebP 等 OpenCV 能读的格式")
        src_h, src_w = bgr.shape[:2]
        if src_w < 2 or src_h < 2:
            raise AuxRequestError(f"图片太小：{src_w}x{src_h}")

        started = time.monotonic()
        det_in, shape = det_input(bgr, self._cfg)
        # The graph's output is [1, 1, side, side]; DB needs the 2-D map. The
        # rank is reduced explicitly, and both leading axes are dropped -- the
        # obvious `[0][0]` chain is right by accident here, and the obvious
        # "if ndim == 3" repair is wrong outright: on the board the output is
        # rank 4, so a 3-D test never fires and a rank-3 array (whose first two
        # axes slice to rank 3) reaches OpenCV's findContours, which rejects it
        # with Sophon's "copyMakeBorder ... _src.dims() <= 2" assertion instead
        # of anything that names the mistake.
        det_out = self._det.run(det_in)[0]
        while det_out.ndim > 2:
            if det_out.shape[0] != 1:
                raise AuxNativeError(
                    f"det 图输出是 {det_out.shape}，无法还原成二维概率图")
            det_out = det_out[0]
        if det_out.ndim != 2:
            raise AuxNativeError(
                f"det 图输出是 {det_out.shape}，无法还原成二维概率图")
        probs = det_out
        boxes, _scores = det_postprocess(probs, shape, self._cfg)
        det_ms = (time.monotonic() - started) * 1000.0

        started = time.monotonic()
        lines: list[OcrLine] = []
        for box in boxes:
            crop = crop_quad(bgr, box)
            if crop is None:
                continue
            h, w = crop.shape[:2]
            width = rec_width_for(h, w, self._cfg)
            engine = self._rec_engine(width)
            out = engine.run(rec_input(crop, width, self._cfg))[0]
            # The graph emits [1, T, C]; the decoder wants [T, C].
            text, score = ctc_decode(out[0], self._cfg.labels)
            if not text:
                # A box that decodes to nothing is noise the detector drew
                # around a texture; PaddleOCR drops it too (drop_score 0.5 is a
                # confidence gate, and an empty string has no confidence).
                continue
            lines.append(OcrLine(
                text=text, score=score,
                box=tuple((float(x), float(y)) for x, y in box),
                width_tier=width))
        rec_ms = (time.monotonic() - started) * 1000.0

        if mode == MODE_LAYOUT:
            return self._layout_page(bgr, lines, src_w, src_h,
                                     det_ms, rec_ms)

        order = reading_order([line.box for line in lines])
        ordered = [lines[i] for i in order]
        return OcrResult(
            text="\n".join(line.text for line in ordered),
            lines=ordered,
            det_ms=det_ms,
            rec_ms=rec_ms,
            width=src_w,
            height=src_h,
        )

    # -- layout mode ------------------------------------------------------
    def layout_regions(self, bgr, src_w: int, src_h: int) -> tuple[list[dict], float]:
        """One layout pass: ``(regions in page pixels, elapsed ms)``.

        Split out of :meth:`_layout_page` because ``mode: "vl"`` needs the boxes
        *without* the OCR pass: the VLM reads each region, so running PP-OCR
        first would be thousands of recognitions nobody uses -- and, on a dense
        page, most of the request's time.

        Raises :class:`OcrModeUnavailable` when the layout bmodel is missing,
        naming the file, exactly as ``layout`` mode does.
        """
        from . import ocr_layout as layout_mod

        engine = self._layout_engine(Path(self._model_path).parent)
        started = time.monotonic()
        tensor = layout_mod.preprocess(bgr, self._layout_cfg)
        outputs = engine.run(tensor)
        if len(outputs) != 2:
            raise AuxNativeError(
                f"版面 bmodel 有 {len(outputs)} 个输出，需要 boxes 与 scores 两个；"
                "这个文件不是 PP-DocLayout-M 的切图版本")
        regions = layout_mod.detect(outputs[0], outputs[1], (src_h, src_w),
                                    self._layout_cfg)
        return regions, (time.monotonic() - started) * 1000.0

    async def detect_page(self, image: bytes) -> dict:
        """``mode: "vl"``, layout half: the page's regions, no OCR pass.

        Returns the shape the API's page orchestration consumes --
        ``{"width", "height", "regions": [{label, score, box, type}],
        "layout_ms"}`` -- so the worker can hand it to the ``ocr_vl`` model
        without either side decoding the image twice.

        Runs under the same admission slot as ``recognise``: a page holds the
        detector, and two pages at once would only queue behind each other anyway
        (one NPU).
        """
        return await self._gate.run(self._detect_page_sync, image)

    def _detect_page_sync(self, image: bytes) -> dict:
        bgr = self._decode(image)
        src_h, src_w = bgr.shape[:2]
        regions, layout_ms = self.layout_regions(bgr, src_w, src_h)
        return {
            "width": src_w, "height": src_h,
            "layout_ms": round(layout_ms, 2),
            "regions": [
                {"label": region["label"], "score": float(region["score"]),
                 "box": [int(v) for v in region["box"]],
                 "type": _block_type(region["label"])}
                for region in regions
            ],
        }

    def _decode(self, image: bytes):
        """One image blob -> BGR, with the two refusals every mode shares."""
        import numpy as np

        cv2 = self._cv2
        buf = np.frombuffer(image, dtype=np.uint8)
        bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if bgr is None:
            raise AuxRequestError(
                "无法解码这张图片；支持 PNG/JPEG/BMP/WebP 等 OpenCV 能读的格式")
        src_h, src_w = bgr.shape[:2]
        if src_w < 2 or src_h < 2:
            raise AuxRequestError(f"图片太小：{src_w}x{src_h}")
        return bgr

    def _layout_page(self, bgr, lines, src_w: int, src_h: int,
                     det_ms: float, rec_ms: float) -> OcrResult:
        """Layout-detect the page, place the OCR lines, order, render Markdown.

        ``lines`` are the *same* lines ``lines`` mode returns, in PP-OCR's own
        reading order; they are re-ordered here by the layout regions, which is
        what the card asks for (``lines`` in a layout response is in the new
        order, not the old one).
        """
        from . import ocr_layout as layout_mod

        regions, layout_ms = self.layout_regions(bgr, src_w, src_h)

        filled = layout_mod.assign_lines(regions, lines)
        ordered = layout_mod.order_regions(filled, (src_h, src_w))

        blocks = []
        flat: list[OcrLine] = []
        by_text = {}
        for line in lines:
            by_text.setdefault(line.text, []).append(line)
        for index, region in enumerate(ordered):
            region_lines = []
            for entry in region["lines"]:
                # The region's entries are copies (they carry an axis-aligned
                # box); the OcrLine objects are matched back by text and box so
                # ``lines`` keeps PP-OCR's quadrilateral and its width tier.
                source = _take_line(by_text, entry)
                if source is None:
                    continue
                region_lines.append(source)
                flat.append(source)
            blocks.append({
                "index": index,
                "type": _block_type(region["label"]),
                "label": region["label"],
                "score": round(float(region["score"]), 6),
                "box": [int(v) for v in region["box"]],
                "text": region["text"],
                "lines": region_lines,
            })

        return OcrResult(
            text=layout_mod.to_markdown(ordered),
            lines=flat,
            det_ms=det_ms,
            rec_ms=rec_ms,
            width=src_w,
            height=src_h,
            mode=MODE_LAYOUT,
            blocks=tuple(blocks),
            layout_ms=layout_ms,
        )

    def _layout_engine(self, model_dir: Path) -> NetEngine:
        """The layout bmodel, loaded on first use.

        Loaded lazily for the same reason the rec tiers are: ~21.5 MB of NPU
        memory that a ``lines``-only deployment never needs. The *check* that the
        file exists happens on every layout request, though -- a device with the
        four-file model must get a 400 that says which file is missing, not a
        500 from a failed load.
        """
        with self._lock:
            if self._layout is not None:
                return self._layout
            if self._layout_cfg is None:
                from .ocr_layout import load_layout_config
                self._layout_cfg = load_layout_config(self._config_dir)
            path = model_dir / self._layout_cfg.bmodel
            if not path.is_file():
                raise OcrModeUnavailable(
                    f"版面模式需要版面模型 {self._layout_cfg.bmodel}，"
                    f"但模型目录 {model_dir} 里没有这个文件。"
                    "这个模型目录只有旧的四个文件（det + 三档 rec）。"
                    "请在控制台的「模型」页对 PP-OCR 模型点「更新」，"
                    "下载第 5 个文件后再试；lines 模式不受影响")
            engine = NetEngine(str(path), self._lib_path, self._dev_id)
            expected = (1, 3, self._layout_cfg.side, self._layout_cfg.side)
            if engine.num_inputs != 1 or tuple(engine.input_shapes[0]) != expected:
                engine.close()
                raise OcrUnavailable(
                    f"{path.name} 的输入是 {engine.input_shapes}，"
                    f"而 layout.json 要求单输入 {expected}")
            self._layout = engine
            return engine

    def _rec_engine(self, width: int) -> NetEngine:
        """The rec engine for one tier, created on first use (see the class doc)."""
        with self._lock:
            engine = self._rec.get(width)
            if engine is not None:
                return engine
            path = self._rec_paths[width]
            engine = NetEngine(str(path), self._lib_path, self._dev_id)
            expected = (1, 3, self._cfg.rec_height, width)
            if tuple(engine.input_shapes[0]) != expected:
                engine.close()
                raise OcrUnavailable(
                    f"{path.name} 的输入是 {engine.input_shapes[0]}，"
                    f"而配置要求 {expected}")
            self._rec[width] = engine
            return engine

    async def close(self) -> None:
        """Close every engine, in reverse of the order it was created.

        The order is the fix, not a preference, and it is what the board
        measured. All four graphs share libbmrt's process-wide compute pool.
        ``ComputeMemory::Destroy`` shrinks that pool when the net being destroyed
        was the largest one still in it -- ``Resize``, which is a
        ``bm_free_device_u64`` followed by ``bm_malloc_device_byte_u64`` of the
        smaller size, issued from *inside* ``bmrt_destroy``. On this chip both
        halves fail once another engine's handle has already gone: the trace is

            bmdev handle sync api failed, ioclt ret = -1 533      (EBADF)
            bm free gmem failed, ioclt ret = -1:815
            bm_alloc_gmem failed ... size = 0x960000
            BM_CHECK_RET fail ... bm_malloc_device_byte_u64: 1204
            BMRT_ASSERT: bm_malloc_device_byte_u64(...) == BM_SUCCESS
            terminate called after throwing an instance of 'std::runtime_error'

        The last line is the damage: ``BMRT_ASSERT`` throws, the throw leaves a
        destructor, and C++ calls ``std::terminate`` -- so an unload did not just
        fail, it killed the whole OCR worker. Every observed unload did this.

        det is created first and is by far the largest graph (0x4fe3000 of neuron
        memory against 0x156b000 for the widest rec tier), so closing it first
        was exactly the case that triggers the shrink. Reverse of creation order
        destroys the small graphs first; by the time det goes there is nothing
        smaller left to resize down to, so the ``Resize`` never happens.

        Measured on the 10155 board, three runs per order: det-first terminated
        3/3 with two ``bm free gmem`` errors; reverse 0/3, clean log.

        Each close is guarded: one engine failing must not leave the rest open,
        because this runs while the process is shutting down and the others still
        own NPU memory. The layout engine is created last of all (only on the
        first ``layout`` request) and was missing from this method entirely -- a
        worker that had served one layout page leaked its ~21.5 MB until the
        process exited.
        """
        engines: list[tuple[str, NetEngine]] = []
        if self._layout is not None:
            engines.append(("layout", self._layout))
        # Widest rec tier first: that is reverse of creation order, because a
        # page widens the tier as it goes and the widest tier is created last.
        for width in sorted(self._rec, reverse=True):
            engines.append((f"rec {width}", self._rec[width]))
        engines.append(("det", self._det))

        self._layout = None
        self._rec = {}

        for name, engine in engines:
            try:
                engine.close()
            except Exception:  # noqa: BLE001 -- see the docstring
                logger.exception("%s engine failed to close; continuing the "
                                 "teardown so the others still release their "
                                 "NPU memory", name)

