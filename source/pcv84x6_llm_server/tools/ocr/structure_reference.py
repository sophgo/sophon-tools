#!/usr/bin/env python3
"""x86 reference for the structure pipeline: ONNX + the same numpy tail.

The point of this script is that the *only* thing that differs between it and
the board run is which engine executes the graph. Pre-processing, the cut
graph's tensors, the NMS/top-k tail and the PaddleX post-processing are all
shared code (``layout_postprocess.py``, ``table_postprocess.py``), so a
difference in the final boxes can only come from f16-on-NPU versus f32-on-CPU.

Two references are produced, deliberately:

* ``onnx`` -- the **cut** graph, i.e. what the bmodel contains, plus the numpy
  tail. This is the correctness reference: same graph, same tail, different
  hardware.
* ``paddlex`` -- PP-DocLayout-S/-M through PaddleX's own predictor, which runs
  the *uncut* graph and PaddleX's own post-processing. This is the "are we
  reproducing the product" reference.

    python3 tools/ocr/structure_reference.py --onnx-dir <dir> \\
        --img-dir tests/data/ocr/img --out <dir>

Writes, per model and image, an ``.npz`` of the bmodel's two input tensors
(``image``, and boxes after rescale) plus a ``reference.json`` of the boxes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout_postprocess as post  # noqa: E402

LAYOUT_MODELS = {"PP-DocLayout-S": 480, "PP-DocLayout-M": 640}


def preprocess(bgr: np.ndarray, side: int):
    """PaddleX ``Resize(keep_ratio=false)`` + ImageNet norm + CHW, fp32."""
    import cv2

    h, w = bgr.shape[:2]
    x = cv2.resize(bgr, (side, side), interpolation=cv2.INTER_LINEAR)
    x = cv2.cvtColor(x, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / \
        np.array([0.229, 0.224, 0.225], np.float32)
    x = np.ascontiguousarray(x.transpose(2, 0, 1)[None])
    # PaddleX's scale_factor: [net_h / page_h, net_w / page_w]
    sf = np.array([side / h, side / w], np.float32)
    return x, (h, w), sf


def boxes_from_raw(raw_boxes, raw_scores, page, sf, labels,
                   merge_mode=None, threshold=0.5):
    """The whole numpy tail, shared with the board runner."""
    boxes = post.rescale_boxes(raw_boxes.reshape(-1, 4), sf)
    return post.det_postprocess(boxes[None], raw_scores, page,
                                threshold=threshold, labels=labels,
                                merge_mode=merge_mode)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx-dir", required=True, type=Path,
                    help="dir with PP-DocLayout-{S,M}_cut.onnx")
    ap.add_argument("--img-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--no-paddlex", action="store_true",
                    help="skip the PaddleX predictor comparison")
    args = ap.parse_args()

    import cv2
    import onnxruntime as ort

    args.out.mkdir(parents=True, exist_ok=True)
    labels = post.load_labels()
    merge = post.MERGE_MODE_STRUCTURE_V3
    images = sorted(p for p in args.img_dir.iterdir()
                    if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp"))

    result = {}
    for name, side in LAYOUT_MODELS.items():
        cut = args.onnx_dir / f"{name}_cut.onnx"
        sess = ort.InferenceSession(str(cut), providers=["CPUExecutionProvider"])
        per_image = {}
        for p in images:
            img = cv2.imread(str(p))
            x, page, sf = preprocess(img, side)
            raw_boxes, raw_scores = sess.run(None, {"image": x})
            np.savez_compressed(args.out / f"{name}__{p.stem}.npz",
                                image=x, scale_factor=sf)
            boxes = boxes_from_raw(raw_boxes, raw_scores, page, sf, labels, merge)
            per_image[p.name] = {
                "page_hw": list(page),
                "boxes": [{"label": b["label"], "score": b["score"],
                           "coordinate": b["coordinate"]} for b in boxes],
            }
        result[name] = per_image
        print(f"{name}: {len(images)} images, "
              f"{sum(len(v['boxes']) for v in per_image.values())} boxes")

    if not args.no_paddlex:
        result["paddlex"] = _paddlex_reference(images, labels, args.img_dir)

    (args.out / "reference.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1))
    print(f"wrote {args.out/'reference.json'}")
    return 0


def _paddlex_reference(images, labels, img_dir):
    """PaddleX's own predictor on the same images, for the product comparison.

    Failures are recorded rather than raised: the predictor needs a GPU-less
    paddle build and its own model download, and this script's primary job is
    the ONNX reference above.
    """
    out = {}
    try:
        from paddlex.inference.models.layout_analysis.predictor import (
            LayoutAnalysisPredictor,
        )
    except Exception as exc:                     # pragma: no cover - env specific
        print(f"paddlex unavailable: {exc}")
        return {"error": str(exc)}
    for model in LAYOUT_MODELS:
        try:
            pred = LayoutAnalysisPredictor(model_name=model)
            per_image = {}
            for p in images:
                res = pred.process([str(p)])[0]
                per_image[p.name] = [
                    {"label": b["label"], "score": round(b["score"], 4),
                     "coordinate": b["coordinate"]} for b in res["boxes"]]
            out[model] = per_image
            print(f"paddlex/{model}: "
                  f"{sum(len(v) for v in per_image.values())} boxes")
        except Exception as exc:                 # pragma: no cover
            print(f"paddlex/{model} failed: {exc}")
            out[model] = {"error": str(exc)}
    return out


if __name__ == "__main__":
    raise SystemExit(main())
