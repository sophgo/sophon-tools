#!/usr/bin/env python3
"""Record the tensor-level golden for the OCR pre/post-processing tests.

``golden.json`` pins what the *pipeline* produces (boxes, text, confidences).
That is enough to prove the board agrees with onnxruntime, but not enough to
tell a post-processing bug from a detection bug: if the boxes are wrong, the
question "was it the DB decode or the contour stage?" has no answer without the
probability map that went into it.

So this script records the two tensors the bmodels produce, on the same x86
onnxruntime run the other golden came from:

* ``det/<image>``  -- the detector's probability map, cropped to the resized
  region the post-processor actually reads. **float32**: quantising it to f16
  moves boxes by hundreds of pixels on five of the seven images, because
  ``thresh``/``box_thresh`` sit right on the edge of the distribution and a
  half-float rounding flips candidate contours in and out. The map is the
  oracle; degrading it would make the test measure the degradation.
* ``rec/<image>/<line>`` -- the recogniser's ``[T, C]`` softmax output for one
  det crop. **float16**: the decoded text is identical for all 103 lines and the
  confidence moves by at most 1.6e-4, while the file shrinks from 543 MB (all
  f32) to 7.7 MB. That is the trade a checked-in fixture has to make, and
  ``tests/test_ocr_postprocess.py`` asserts the text equality rather than
  assuming it.

The numpy archive is ``tests/data/ocr/postprocess.npz``. Arrays are keyed by
these names so a test can look one up without knowing the layout.

    python3 tools/ocr/make_postprocess_golden.py \\
        --onnx-dir /path/to/onnx --out tests/data/ocr/postprocess.npz

Run it on x86 with onnxruntime and OpenCV; the board never needs it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--onnx-dir", required=True, type=Path)
    ap.add_argument("--img-dir", type=Path, default=Path("tests/data/ocr/img"))
    ap.add_argument("--golden", type=Path, default=Path("tests/data/ocr/golden.json"))
    ap.add_argument("--config", type=Path,
                    default=Path("model-config/ppocr_v6/ppocr.json"))
    ap.add_argument("--out", type=Path,
                    default=Path("tests/data/ocr/postprocess.npz"))
    args = ap.parse_args()

    import cv2
    import onnxruntime as ort

    from app.engine.ocr_ppocr import (
        crop_quad,
        det_input,
        load_config,
        rec_input,
        rec_width_for,
    )

    cfg = load_config(args.config.parent)
    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    det_entries = {e["image"]: e for e in golden["ppocr"]["det"]["images"]}

    det_sess = ort.InferenceSession(str(args.onnx_dir / "ppocrv6_medium_det.onnx"),
                                    providers=["CPUExecutionProvider"])
    rec_sess = ort.InferenceSession(str(args.onnx_dir / "ppocrv6_medium_rec.onnx"),
                                    providers=["CPUExecutionProvider"])

    arrays: dict[str, np.ndarray] = {}
    for name, entry in det_entries.items():
        bgr = cv2.imread(str(args.img_dir / name), cv2.IMREAD_COLOR)
        if bgr is None:
            raise SystemExit(f"cannot decode {name}")
        inp, shape = det_input(bgr, cfg)
        prob = det_sess.run(None, {"x": inp})[0][0, 0]
        src_h, src_w, resize_h, resize_w = shape
        # Exactly the region DBPostProcess reads, so the test cannot accidentally
        # pass by looking at padding the model never filled.
        arrays[f"det/{name}"] = prob[:resize_h, :resize_w].astype(np.float32)

    for entry in golden["ppocr"]["rec"]["images"]:
        bgr = cv2.imread(str(args.img_dir / entry["image"]), cv2.IMREAD_COLOR)
        for index, line in enumerate(entry["lines"]):
            box = det_entries[entry["image"]]["boxes"][line["box_index"]]
            crop = crop_quad(bgr, box)
            if crop is None:
                raise SystemExit(f"{entry['image']}: box {index} does not crop")
            h, w = crop.shape[:2]
            width = rec_width_for(h, w, cfg)
            probs = rec_sess.run(None, {"x": rec_input(crop, width, cfg)})[0][0]
            arrays[f"rec/{entry['image']}/{index}"] = probs.astype(np.float16)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "wb") as handle:
        np.savez_compressed(handle, **arrays)
    size = args.out.stat().st_size
    print(f"wrote {args.out} ({size / 2**20:.1f} MiB, {len(arrays)} tensors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
