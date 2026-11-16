#!/usr/bin/env python3
"""Generate the OCR golden set in ``tests/data/ocr/``.

Two independent things are recorded here, both on x86:

* **PP-OCRv6 (det + rec)** -- the *same* ONNX graph the bmodel was compiled
  from, run under onnxruntime with PaddleOCR's own pre/post-processing, plus a
  second opinion from the official ``paddleocr`` package. The bmodel's job is to
  reproduce the ONNX path, so that path is the oracle; the ``paddleocr`` run
  exists to catch the case where our hand-written pre/post-processing drifted
  from the reference while still agreeing with itself.
* **PaddleOCR-VL-1.5** -- the HF reference (``transformers``,
  ``trust_remote_code``, CPU) for three of the images, under two prompts. Beyond
  the output text the *inputs* are recorded: the post-preprocessing pixel tensor
  shape, the image token count and the ``input_ids``. Stage-2 integration has to
  feed the bmodel the exact same token layout, and a one-token slip silently
  writes embeddings into the wrong rows, so those are pinned token for token.

Run it on an x86 box with a venv that has onnxruntime, paddleocr, torch and
transformers -- the board never needs this file.

    python3 tools/ocr/make_golden.py \\
        --onnx-dir /path/to/onnx --vl-model /path/to/PaddleOCR-VL-1.5 \\
        --img-dir tests/data/ocr/img --out tests/data/ocr

Every input to that command is recorded in the emitted ``golden.json`` under
``provenance`` so a later reader can tell what produced the numbers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

#: Det input side the bmodel was compiled at. Must match
#: ``model-config/ppocr_v6/ppocr.json``; ``tests/test_ocr_assets.py`` asserts it.
DET_SIDE = 736
#: Rec input height, and the compiled widths.
REC_HEIGHT = 48
REC_WIDTHS = (320, 640, 1600)

#: Pick the narrowest compiled width that does **not** squash the line. An
#: earlier version clamped everything wider than 13.33:1 to 640, which squashed
#: a 34.8:1 report line into 640 px and decoded it as `dubuy`; the same crop at
#: 1600 decoded correctly. 3200 is the ceiling the model's own inference.yml
#: declares. Between tiers the narrower one is chosen when the squash factor is
#: under 1.15 -- a small, measured amount is harmless and the cost is real.
WIDTH_SQUASH_TOLERANCE = 1.15


def rec_width_for(h: int, w: int) -> int:
    ideal = REC_HEIGHT * (w / float(h))
    return rec_width_for_ideal(ideal)


def rec_width_for_ideal(ideal_width: float) -> int:
    for tier in REC_WIDTHS:
        if ideal_width <= tier:
            return tier
    return REC_WIDTHS[-1]



#: The 2 images PaddleOCR-VL is exercised on: a compact UI screenshot (short
#: text, fast) and a table (the markup case). Deliberately not three: the
#: reference prefill costs ~9 minutes per image on CPU and dominates the run,
#: and a third image would buy a third sample of the same layout proof.
VL_IMAGES = ("ui_status.png", "table_stats.png")
VL_PROMPTS = (("ocr", "OCR:"), ("table", "Table Recognition:"))

#: Cap per VL case. Greedy on CPU measured ~17 s/token at 5000 patches, so a
#: six-case run has to be bounded deliberately: 64 tokens is enough for "OCR:"
#: to emit the top of a page and for "Table Recognition:" to show its markup,
#: and keeps the whole run near an hour. The point of the golden is to prove
#: the layout and the first tokens, not to reproduce a full transcription.
VL_MAX_NEW_TOKENS = 48

#: Golden must stay under 1 MB, so det probability maps are summarised rather
#: than stored. These are the summary stats the task asks for.
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# PP-OCR det
# --------------------------------------------------------------------------- #
def det_preprocess(bgr: np.ndarray, side: int = DET_SIDE):
    """PaddleOCR ``DetResizeForTest`` + ``NormalizeImage`` + ``ToCHWImage``.

    Mirrors ``sophon-demo sample/PP-OCR/python/ppocr_det_opencv.py:preprocess``
    and the model's own ``inference.yml`` transform list.
    """
    import cv2

    h, w = bgr.shape[:2]
    size_max = max(h, w)
    if size_max >= side:
        ratio = float(side) / size_max
    else:
        ratio = 1.0
    resize_h, resize_w = int(h * ratio), int(w * ratio)
    interp = cv2.INTER_LINEAR
    if h != resize_h or w != resize_w:
        bgr = cv2.resize(bgr, (resize_w, resize_h), interpolation=interp)

    img = bgr.astype(np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    img = (img - mean) / std
    img = np.transpose(img, (2, 0, 1))

    padded = np.zeros((3, side, side), dtype=np.float32)
    padded[:, :resize_h, :resize_w] = img
    return padded, (h, w, resize_h, resize_w)


def det_postprocess(prob: np.ndarray, shape, params):
    """DB post-processing, following PaddleOCR's ``DBPostProcess``.

    ``prob`` is the bmodel/ONNX sigmoid map at full model resolution.
    """
    import cv2
    import pyclipper
    from shapely.geometry import Polygon

    thresh = params["thresh"]
    box_thresh = params["box_thresh"]
    max_candidates = params["max_candidates"]
    unclip_ratio = params["unclip_ratio"]
    min_size = params["min_size"]

    src_h, src_w, resize_h, resize_w = shape
    pred = prob[:resize_h, :resize_w]
    segmentation = pred > thresh

    boxes, scores = [], []
    found = cv2.findContours((segmentation.astype(np.uint8) * 255), cv2.RETR_LIST,
                             cv2.CHAIN_APPROX_SIMPLE)
    # OpenCV 4 returns (image, contours, hierarchy); OpenCV 5 returns
    # (contours, hierarchy). The contours are the second element only in the
    # 3-tuple form. Getting this wrong silently yields zero boxes, because the
    # hierarchy array has no contour in it.
    contours = found[1] if len(found) == 3 else found[0]
    if isinstance(contours, np.ndarray):
        contours = [contours] if contours.ndim == 3 else []
    for contour in list(contours)[:max_candidates]:
        if contour is None or len(contour) < 4:
            continue
        contour = np.asarray(contour, dtype=np.int32).reshape(-1, 1, 2)
        points, sside = _mini_box(contour)
        if sside < min_size:
            continue
        points = np.array(points)
        score = _box_score_fast(pred, points.reshape(-1, 2))
        if box_thresh > score:
            continue

        box = _unclip(points, unclip_ratio).reshape(-1, 1, 2)
        box, sside = _mini_box(box)
        if sside < min_size + 2:
            continue
        box = np.array(box)
        # map back to source resolution
        box[:, 0] = np.clip(np.round(box[:, 0] / resize_w * src_w), 0, src_w)
        box[:, 1] = np.clip(np.round(box[:, 1] / resize_h * src_h), 0, src_h)
        boxes.append([[float(x), float(y)] for x, y in box])
        scores.append(float(score))
    return boxes, scores


def _mini_box(contour):
    """PaddleOCR ``DBPostProcess.get_mini_boxes``, verbatim in behaviour."""
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
    import cv2

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


def _unclip(points, unclip_ratio):
    from shapely.geometry import Polygon
    import pyclipper

    poly = Polygon(points)
    distance = poly.area * unclip_ratio / poly.length
    offset = pyclipper.PyclipperOffset()
    offset.AddPath(points, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    expanded = offset.Execute(distance)
    return np.array(expanded[0]) if expanded else points


# --------------------------------------------------------------------------- #
# PP-OCR rec
# --------------------------------------------------------------------------- #
def _order_clockwise(pts):
    """Order four points top-left, top-right, bottom-right, bottom-left."""
    import numpy as np

    pts = np.asarray(pts, dtype=np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).reshape(-1)
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)],
                     pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def _crop_quad(bgr: np.ndarray, box):
    """Rectify a det quadrilateral to an upright rectangle.

    An axis-aligned bounding box is not enough: a 7-degree-skewed line has a
    bbox several times taller than the glyphs, and the recogniser then sees the
    rotation smeared into the crop and returns fragments. PaddleOCR and
    sophon-demo both do a four-point perspective warp; the earlier bbox-only
    version decoded the skewed sample as `库盘点WarehousenySt` where the
    reference reads `仓库盘点单 Warehouse Inventory Sheet`.
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


def rec_width_for(h: int, w: int) -> int:
    """Narrowest compiled width whose capacity is at least ``1.15`` x the line."""
    ideal = REC_HEIGHT * (w / float(h))
    return rec_width_for_ideal(ideal * WIDTH_SQUASH_TOLERANCE)


def rec_preprocess(bgr: np.ndarray, width: int):
    import cv2

    h, w = bgr.shape[:2]
    resized_w = int(REC_HEIGHT * w / float(h))
    resized_w = max(1, min(resized_w, width))
    img = cv2.resize(bgr, (resized_w, REC_HEIGHT))
    img = img.astype(np.float32)
    img = np.transpose(img, (2, 0, 1))
    img -= 127.5
    img *= 0.0078125
    padded = np.zeros((3, REC_HEIGHT, width), dtype=np.float32)
    padded[:, :, :resized_w] = img
    return padded


def ctc_decode(probs: np.ndarray, labels) -> dict:
    """Greedy CTC: argmax -> collapse repeats -> drop blank -> map -> mean conf."""
    idx = probs.argmax(axis=1)
    conf = probs.max(axis=1)
    chars, confs = [], []
    prev = -1
    for t, c in enumerate(idx):
        if c != 0 and c != prev:
            chars.append(labels[c])
            confs.append(float(conf[t]))
        prev = c
    return {
        "text": "".join(chars),
        "confidence": float(np.mean(confs)) if confs else 0.0,
        "char_count": len(chars),
    }


def load_labels(dict_path: Path):
    lines = dict_path.read_text(encoding="utf-8").splitlines()
    return ["<blank>"] + lines + [" "]


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--onnx-dir", required=True, type=Path,
                    help="directory holding ppocrv6_medium_det.onnx / _rec.onnx")
    ap.add_argument("--dict", type=Path,
                    default=Path("model-config/ppocr_v6/ppocr_keys_v1.txt"))
    ap.add_argument("--img-dir", type=Path, default=Path("tests/data/ocr/img"))
    ap.add_argument("--out", type=Path, default=Path("tests/data/ocr"))
    ap.add_argument("--vl-model", type=Path, default=None,
                    help="PaddleOCR-VL-1.5 HF directory; VL golden is skipped when omitted")
    ap.add_argument("--skip-paddleocr", action="store_true",
                    help="skip the official-paddleocr cross-check")
    ap.add_argument("--paddleocr-reference", type=Path, default=None,
                    help="an earlier golden.json whose paddleocr_reference "
                         "section is reused verbatim (for machines without "
                         "the paddleocr package)")
    ap.add_argument("--vl-from", type=Path, default=None,
                    help="an earlier golden.json whose paddleocr_vl section is "
                         "reused verbatim (for machines without torch)")
    ap.add_argument("--layout-onnx", type=Path, default=None,
                    help="PP-DocLayout-M_cut.onnx; records the layout golden "
                         "(the two dense tensors the bmodel exposes)")
    args = ap.parse_args()

    import cv2
    import onnxruntime as ort

    cfg = json.loads((Path("model-config/ppocr_v6/ppocr.json")).read_text())
    labels = load_labels(args.dict)
    images = sorted(p for p in args.img_dir.glob("*.png"))

    det_sess = ort.InferenceSession(str(args.onnx_dir / "ppocrv6_medium_det.onnx"),
                                    providers=["CPUExecutionProvider"])
    rec_sess = ort.InferenceSession(str(args.onnx_dir / "ppocrv6_medium_rec.onnx"),
                                    providers=["CPUExecutionProvider"])

    det_out = {"images": []}
    for path in images:
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            raise SystemExit(f"cannot decode {path}")
        inp, shape = det_preprocess(bgr)
        prob = det_sess.run(None, {"x": inp[None, ...]})[0][0, 0]
        boxes, scores = det_postprocess(prob, shape, cfg["det"]["postprocess"])
        det_out["images"].append({
            "image": path.name,
            "size": [int(bgr.shape[1]), int(bgr.shape[0])],
            "resize": [int(shape[2]), int(shape[3])],
            "box_count": len(boxes),
            "boxes": boxes,
            "box_scores": scores,
            "prob_stats": {
                "mean": float(prob.mean()),
                "over_thresh_pixels": int((prob > cfg["det"]["postprocess"]["thresh"]).sum()),
                "total_pixels": int(prob.size),
            },
        })

    # rec runs on the *det crops*, which is the only input shape it is fed in
    # production; running it on whole pages produces meaningless garbage.
    rec_out = {"images": []}
    det_by_image = {e["image"]: e for e in det_out["images"]}
    for path in images:
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        boxes = det_by_image[path.name]["boxes"]
        entries = []
        for idx, box in enumerate(boxes):
            crop = _crop_quad(bgr, box)
            if crop is None or crop.size == 0:
                continue
            h, w = crop.shape[:2]
            width = rec_width_for(h, w)
            inp = rec_preprocess(crop, width)
            probs = rec_sess.run(None, {"x": inp[None, ...]})[0][0]
            dec = ctc_decode(probs, labels)
            entries.append({
                "box_index": idx,
                "crop_size": [int(w), int(h)],
                "width_tier": width,
                "input_shape": list(inp.shape),
                "output_shape": list(probs.shape),
                **dec,
            })
        rec_out["images"].append({
            "image": path.name,
            "line_count": len(entries),
            "lines": entries,
        })

    golden = {
        "schema": 1,
        "ppocr": {
            "det": {"model": "ppocrv6_medium_det.onnx", **det_out},
            "rec": {
                "model": "ppocrv6_medium_rec.onnx",
                "labels": {"count": len(labels), "blank_index": 0,
                           "space_index": len(labels) - 1,
                           "dict_lines": len(labels) - 2},
                **rec_out,
            },
        },
    }

    if args.paddleocr_reference is not None:
        # Reuse a recorded reference verbatim. ``paddleocr`` is not installed in
        # every environment this script runs in (it pins its own paddle build),
        # and dropping the section would silently weaken
        # ``tests/test_ocr_assets.py::test_agreement_with_official_paddleocr``
        # from "agrees with the official pipeline" to "the golden is missing
        # that claim". Passing the previous golden's section keeps the oracle
        # while only re-recording what actually changed.
        previous = json.loads(args.paddleocr_reference.read_text(encoding="utf-8"))
        golden["ppocr"]["paddleocr_reference"] = previous["ppocr"][
            "paddleocr_reference"]
    elif not args.skip_paddleocr:
        golden["ppocr"]["paddleocr_reference"] = _paddleocr_reference(images)

    if args.layout_onnx is not None:
        golden["layout"] = _layout_golden(args.layout_onnx, images, args.out)

    if args.vl_model is not None:
        golden["paddleocr_vl"] = _vl_golden(args.vl_model, args.img_dir)
    elif args.vl_from is not None:
        # Same reason as ``--paddleocr-reference``: the VL reference needs
        # torch, and re-running it would re-download a 2 GB checkpoint to
        # reproduce numbers that did not change. Its inputs are pinned token for
        # token by ``tests/test_ocr_assets.py``, which is the whole point.
        previous = json.loads(args.vl_from.read_text(encoding="utf-8"))
        if "paddleocr_vl" in previous:
            golden["paddleocr_vl"] = previous["paddleocr_vl"]

    golden["provenance"] = {
        "det_onnx_sha256": _sha256(args.onnx_dir / "ppocrv6_medium_det.onnx"),
        "rec_onnx_sha256": _sha256(args.onnx_dir / "ppocrv6_medium_rec.onnx"),
        "dict_sha256": _sha256(args.dict),
        "onnxruntime": ort.__version__,
        "images": {p.name: _sha256(p) for p in images},
    }
    if args.layout_onnx is not None:
        golden["provenance"]["layout_onnx_sha256"] = _sha256(args.layout_onnx)

    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / "golden.json"
    out_path.write_text(json.dumps(golden, ensure_ascii=False, indent=1), encoding="utf-8")
    size = out_path.stat().st_size
    print(f"wrote {out_path} ({size/1024:.1f} KiB)")
    if size > 1024 * 1024:
        print("WARNING: golden exceeds the 1 MB budget", file=sys.stderr)
    return 0


def _layout_golden(onnx_path: Path, images, out_dir: Path) -> dict:
    """The layout model's two dense tensors, per image, plus the reference boxes.

    Records what the *bmodel* would produce (the cut graph's ``boxes`` and
    ``scores``), which is not something a pure-python test can recompute -- so
    ``tests/test_ocr_layout.py`` replays these through the numpy tail instead.
    The boxes are then also recorded after the full PaddleX tail, which is the
    number the board has to reproduce.

    The graph is cut (``tools/ocr/layout_cut.py``), so this is *not* PaddleX's
    end-to-end layout predictor: it is the same graph the bmodel runs, executed
    on the CPU, so a difference downstream can only come from f16-on-NPU versus
    f32-on-CPU.
    """
    import cv2
    import onnxruntime as ort

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from app.engine import ocr_layout as layout
    from app.engine.ocr_layout import load_layout_config

    cfg = load_layout_config(Path("model-config/ppocr_v6"))
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    result = {"model": onnx_path.name, "side": cfg.side, "images": []}
    # The raw tensors go beside the golden in an ``.npz``, not inline: 8500x4
    # floats per image is ~1.7 MB of JSON per page, and the only thing a reader
    # of the golden needs is the box list. ``tests/test_ocr_layout.py`` replays
    # these through the numpy tail, which is how the tail stays pinned without
    # onnxruntime on the board.
    # Kept to the anchors that survive the model's own 0.025 pre-threshold in at
    # least one class: 8500 x 4 + 23 x 8500 floats per page is 8 MB for ten
    # pages at full width, and the dropped rows are ones ``_multiclass_nms``
    # discards by construction. The box indices are unchanged -- only whole
    # *anchors* are removed -- so replaying the pruned tensors exercises the
    # same code path with the same numbers.
    tensors: dict[str, np.ndarray] = {}
    for path in images:
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            raise SystemExit(f"cannot decode {path}")
        h, w = bgr.shape[:2]
        tensor = layout.preprocess(bgr, cfg)
        raw_boxes, raw_scores = session.run(None, {"image": tensor})
        regions = layout.detect(raw_boxes, raw_scores, (h, w), cfg)
        keep = np.where(
            (raw_scores[0] > cfg.pre_threshold).any(axis=0))[0]
        tensors[f"boxes/{path.name}"] = raw_boxes[0][keep].astype(np.float32)
        tensors[f"scores/{path.name}"] = raw_scores[0][:, keep].astype(np.float32)
        result["images"].append({
            "image": path.name,
            "size": [int(w), int(h)],
            "input_shape": list(tensor.shape),
            "raw_boxes_shape": list(raw_boxes.shape),
            "raw_scores_shape": list(raw_scores.shape),
            "kept_anchors": int(keep.size),
            "raw_boxes_md5": _md5_array(raw_boxes),
            "raw_scores_md5": _md5_array(raw_scores),
            "score_max": float(raw_scores.max()),
            "regions": [{"label": r["label"], "score": round(r["score"], 6),
                         "box": r["box"]} for r in regions],
        })
    np.savez_compressed(out_dir / "layout_tensors.npz", **tensors)
    return result


def _md5_array(array) -> str:
    """A digest of a tensor's bytes, so a golden can pin it without the array."""
    import hashlib

    return hashlib.md5(np.ascontiguousarray(array, dtype=np.float32).tobytes()).hexdigest()


def _paddleocr_reference(images):
    """Run the official ``paddleocr`` package over the same images.

    ``enable_mkldnn=False`` is required: with oneDNN on, paddle 3.0 dies with
    ``ConvertPirAttribute2RuntimeAttribute not support
    [pir::ArrayAttribute<pir::DoubleAttribute>]`` before the det model runs.
    """
    try:
        from paddleocr import PaddleOCR
    except Exception as exc:  # noqa: BLE001 - optional, recorded not raised
        return {"available": False, "error": repr(exc)}
    try:
        ocr = PaddleOCR(use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                        lang="ch", enable_mkldnn=False)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": repr(exc)}

    out = {"available": True, "images": []}
    for path in images:
        res = ocr.predict(str(path))
        texts = []
        for page in res:
            data = getattr(page, "json", None)
            body = data.get("res", data) if isinstance(data, dict) else {}
            texts.extend(body.get("rec_texts", []) or [])
        out["images"].append({"image": path.name, "texts": texts})
    return out


def _bridge_mask_kwarg() -> None:
    """Let the model's 4.x-era ``create_causal_mask`` call run on transformers 5.

    ``modeling_paddleocr_vl.py:606`` calls
    ``create_causal_mask(config=..., inputs_embeds=..., ...)``, but every
    transformers 5 release renamed that first tensor argument to
    ``input_embeds``. The rename is cosmetic -- it is the same embedding tensor
    in the same position -- so accepting the old spelling restores the call the
    model was written for. Applied in memory; the installed package is untouched.
    """
    import transformers.masking_utils as _mu

    original = _mu.create_causal_mask
    if getattr(original, "_paddleocr_vl_bridged", False):
        return

    def create_causal_mask(*args, **kwargs):
        if "inputs_embeds" in kwargs and "input_embeds" not in kwargs:
            kwargs["input_embeds"] = kwargs.pop("inputs_embeds")
        # Drop position_ids entirely. The model passes a [3, batch, seq] mrope
        # tensor, whose row 0 is *not* monotonic for image tokens (it is the
        # height index, repeating 0..grid_h-1). A causal mask built from those
        # values masks out the whole image, and the model then produces
        # identical logits whether the image is real or all zeros -- a failure
        # that looks like a broken vision tower and is not one. Without the
        # argument the helper builds the ordinary causal mask from the
        # embeddings, which is the correct mask for both text and image rows.
        kwargs.pop("position_ids", None)
        return original(*args, **kwargs)

    create_causal_mask._paddleocr_vl_bridged = True
    _mu.create_causal_mask = create_causal_mask


def _ensure_default_rope_registered() -> None:
    """Restore the RoPE init function transformers 5.x removed.

    PaddleOCR-VL-1.5's shipped ``modeling_paddleocr_vl.py`` indexes
    ``ROPE_INIT_FUNCTIONS[self.rope_type]`` with ``rope_type="default"``, and
    transformers 5 renamed/removed that key (only linear/dynamic/yarn/longrope/
    llama3/proportional remain), so loading the model dies with
    ``KeyError: 'default'`` before a single token is generated.

    The function below is transformers 4.x's ``_compute_default_rope_parameters``,
    reproduced exactly: the plain, unscaled inverse frequencies. Registering it
    restores the behaviour the model was written against instead of changing the
    model's maths. Nothing on disk changes.
    """
    import torch
    from transformers import modeling_rope_utils as _mru

    if "default" in _mru.ROPE_INIT_FUNCTIONS:
        return

    def _default_rope_parameters(config=None, device=None, seq_len=None,
                                 layer_type=None, head_dim_key="head_dim"):
        base = config.rope_theta
        partial_rotary_factor = getattr(config, "partial_rotary_factor", 1.0)
        head_dim = (getattr(config, "head_dim", None)
                    or config.hidden_size // config.num_attention_heads)
        dim = int(head_dim * partial_rotary_factor)
        inv_freq = 1.0 / (base ** (torch.arange(0, dim, 2, dtype=torch.int64)
                                   .float().to(device) / dim))
        return inv_freq, 1.0

    _mru.ROPE_INIT_FUNCTIONS["default"] = _default_rope_parameters

    # transformers 5's own weight initialiser re-derives the rope buffer for any
    # module it recognises as a rotary embedding:
    #   modeling_utils.py:2379  rope_fn = ... else module.compute_default_rope_parameters
    # PaddleOCR-VL's RotaryEmbedding has no such method, so loading dies with
    # AttributeError before generation. The model class is only known after
    # from_pretrained, so the fallback goes on nn.Module: a property that any
    # rotary module resolves through, and that nothing else ever asks for.
    from torch import nn

    def _compute_default_rope_parameters(self, config=None, device=None, **kwargs):
        return _default_rope_parameters(config if config is not None else
                                        getattr(self, "config", None), device, **kwargs)

    if not hasattr(nn.Module, "compute_default_rope_parameters"):
        nn.Module.compute_default_rope_parameters = _compute_default_rope_parameters


def _vl_golden(model_dir: Path, img_dir: Path):
    """HF reference for PaddleOCR-VL-1.5: outputs + the exact model inputs."""
    import torch
    from transformers import AutoProcessor

    _bridge_mask_kwarg()
    _ensure_default_rope_registered()
    processor = AutoProcessor.from_pretrained(str(model_dir), trust_remote_code=True)
    model = None
    try:
        from transformers import AutoModelForCausalLM
        # No device_map: it would drag in `accelerate`, whose version has to
        # agree with both transformers and torch. A plain CPU load needs
        # neither, and this model is small enough to place by hand.
        # torch_dtype, not dtype: this model's __init__ predates the rename.
        model = AutoModelForCausalLM.from_pretrained(
            str(model_dir), trust_remote_code=True, torch_dtype=torch.float32)
        model.eval()
    except Exception as exc:  # noqa: BLE001
        model_error = repr(exc)
    else:
        model_error = None

    out = {"model_dir": str(model_dir), "cases": [], "model_error": model_error}
    for name in VL_IMAGES:
        path = img_dir / name
        if not path.exists():
            continue
        from PIL import Image
        img = Image.open(path).convert("RGB")
        for key, prompt in VL_PROMPTS:
            messages = [{"role": "user", "content": [
                {"type": "image", "image": str(path)},
                {"type": "text", "text": prompt},
            ]}]
            text = processor.apply_chat_template(messages, tokenize=False,
                                                 add_generation_prompt=True)
            inputs = processor(text=[text], images=[img], return_tensors="pt")
            case = {
                "image": name,
                "prompt": prompt,
                "input_ids": inputs["input_ids"][0].tolist(),
                "pixel_values_shape": list(inputs["pixel_values"].shape),
                "image_grid_thw": (inputs["image_grid_thw"].tolist()
                                   if "image_grid_thw" in inputs else None),
            }
            if "image_grid_thw" in inputs:
                t, hh, ww = inputs["image_grid_thw"][0].tolist()
                case["image_token_count"] = int(t * hh * ww)
            if model is not None:
                try:
                    # Prefer the model's own generate(): it applies the mrope
                    # positions and rope deltas the reference intends. The
                    # manual loop below exists only for transformers 5, where
                    # this model's prepare_inputs_for_generation is incompatible.
                    with torch.no_grad():
                        gen = model.generate(**inputs, max_new_tokens=VL_MAX_NEW_TOKENS,
                                             do_sample=False)
                    new_tokens = gen[0, inputs["input_ids"].shape[1]:].tolist()
                    case["decode_mode"] = "generate"
                except Exception as exc:  # noqa: BLE001
                    case["generate_error"] = repr(exc)
                    new_tokens = _greedy_generate(model, inputs, processor, VL_MAX_NEW_TOKENS)
                    case["decode_mode"] = "manual_greedy"
                case["output_text"] = processor.tokenizer.decode(
                    new_tokens, skip_special_tokens=True)
                case["output_token_count"] = int(len(new_tokens))
            out["cases"].append(case)
            # Progress goes to stderr and is flushed: a CPU generate over six
            # cases takes tens of minutes, and without this the run looks hung.
            print(f"  VL {name} | {prompt!r} -> {case.get('output_token_count')} tokens",
                  file=sys.stderr, flush=True)
    return out


def _greedy_generate(model, inputs, processor, max_new_tokens: int = 512):
    """Plain greedy loop over the model's own forward.

    ``model.generate`` is not usable here: the model's shipped
    ``prepare_inputs_for_generation`` predates transformers 5's decoding API and
    indexes a ``cache_position`` that 5.x no longer passes, so it dies with
    ``'NoneType' object is not subscriptable``. Driving ``forward`` directly is
    also exactly what the criterion needs -- greedy, one token at a time, no
    sampling and no KV-cache policy hidden inside a helper.
    """
    import torch

    ids = inputs["input_ids"]
    pixel_values = inputs.get("pixel_values")
    grid = inputs.get("image_grid_thw")
    generated = []
    cache = None
    with torch.no_grad():
        for step in range(max_new_tokens):
            # position_ids is deliberately NOT passed: the model's own
            # get_rope_index computes the mrope positions, and for image tokens
            # those are grid coordinates, not sequential indices. Substituting
            # sequential positions makes the vision features land at the wrong
            # rotary phases and the model degenerates into repeating one token.
            # _bridge_mask_kwarg reduces the resulting 3-D tensor for the mask
            # helper, which is the only place transformers 5 objects to it.
            kwargs = {}
            if cache is None:
                kwargs["input_ids"] = ids
                if pixel_values is not None:
                    kwargs["pixel_values"] = pixel_values
                if grid is not None:
                    kwargs["image_grid_thw"] = grid
            else:
                # Decode step: only the newest token is fed; the image is
                # already folded into the cached prefill state.
                kwargs["input_ids"] = ids[:, -1:]
                kwargs["past_key_values"] = cache
            out = model(**kwargs, use_cache=True)
            cache = out.past_key_values
            nxt = int(torch.argmax(out.logits[:, -1, :], dim=-1)[0])
            eos = getattr(processor.tokenizer, "eos_token_id", None)
            if eos is not None and nxt == eos:
                break
            generated.append(nxt)
            ids = torch.cat([ids, torch.tensor([[nxt]], dtype=ids.dtype)], dim=1)
    return generated


if __name__ == "__main__":
    raise SystemExit(main())
