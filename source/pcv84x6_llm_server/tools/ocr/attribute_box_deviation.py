#!/usr/bin/env python3
"""Attribute a box deviation: our arithmetic, or the bmodel's f16?

A board run reports "N of M boxes pixel-identical, worst X px". That number by
itself cannot say whether the difference is a bug here or the bmodel's numerics,
and the two call for completely different responses. This separates them with
two experiments that need nothing but the golden and a board:

1. **Same arithmetic, reference input.** Feed the golden's own float32
   probability map to ``det_postprocess`` *on the board*. If the boxes come back
   identical to the golden's, this implementation's arithmetic matches the one
   that produced the golden and the deviation is not here.
2. **Same input, different numerics.** Compare the NPU's map with the golden's,
   and perturb ``thresh`` by a few thousandths. If a box moves by the observed
   deviation under a threshold change smaller than the map difference, the
   contour is sitting on the edge of the distribution -- which is what f16
   accumulation moves and what no amount of arithmetic care can undo.

It needs ``tests/data/ocr/postprocess.npz`` (``make_postprocess_golden.py``) and
a board with the bmodel loaded. Run it on the board:

    python3 tools/ocr/attribute_box_deviation.py \\
        --model-dir <bmodel dir> --lib <libcv84x6_llm.so> --repo <checkout> \\
        --images table_stats.png en_report.png
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path


def _deviation(boxes, want) -> tuple[int, float]:
    if len(boxes) != len(want):
        return 0, float("nan")
    worst = 0.0
    exact = 0
    for a, b in zip(boxes, want):
        d = max(max(abs(pa[0] - pb[0]), abs(pa[1] - pb[1])) for pa, pb in zip(a, b))
        worst = max(worst, d)
        exact += d == 0.0
    return exact, worst


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", required=True, type=Path)
    ap.add_argument("--lib", required=True, type=Path)
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--images", nargs="*", default=None,
                    help="which golden images to analyse (default: all)")
    args = ap.parse_args()

    sys.path.insert(0, str(args.repo.resolve()))
    sys.path.insert(0, "/opt/sophon/sophon-opencv-latest/opencv-python")

    import json

    import cv2
    import numpy as np

    from app.engine.ocr_ppocr import OcrBackend, det_input, det_postprocess

    repo = args.repo
    golden = json.loads((repo / "tests" / "data" / "ocr" / "golden.json")
                        .read_text(encoding="utf-8"))
    golden_det = {e["image"]: e for e in golden["ppocr"]["det"]["images"]}
    archive = repo / "tests" / "data" / "ocr" / "postprocess.npz"
    if not archive.exists():
        print(f"missing {archive}; run tools/ocr/make_postprocess_golden.py")
        return 1
    with np.load(archive) as handle:
        recorded = {name: handle[name] for name in handle.files}

    det_path = sorted(args.model_dir.glob("*det*.bmodel"))[0]
    backend = OcrBackend(str(det_path), str(repo / "model-config" / "ppocr_v6"),
                         "ppocrv6-medium", lib_path=str(args.lib.resolve()))

    names = args.images or sorted(golden_det)
    for name in names:
        entry = golden_det[name]
        shape = (entry["size"][1], entry["size"][0], *entry["resize"])
        want = entry["boxes"]
        key = f"det/{name}"
        if key not in recorded:
            print(f"{name}: no recorded map, skipped")
            continue

        # -- 1: our arithmetic on the reference map -------------------------
        reference = recorded[key].astype(np.float32)
        boxes_ref, _ = det_postprocess(reference, shape, backend._cfg)
        exact_ref, worst_ref = _deviation(boxes_ref, want)

        # -- 2: the NPU's own map ------------------------------------------
        bgr = cv2.imread(str(repo / "tests" / "data" / "ocr" / "img" / name),
                         cv2.IMREAD_COLOR)
        tensor, _ = det_input(bgr, backend._cfg)
        out = backend._det.run(tensor)[0]
        while out.ndim > 2:
            out = out[0]
        npu = out[:shape[2], :shape[3]]
        boxes_npu, _ = det_postprocess(npu, shape, backend._cfg)
        exact_npu, worst_npu = _deviation(boxes_npu, want)

        diff = np.abs(npu - reference)
        flip = int(((npu > backend._cfg.thresh) ^
                    (reference > backend._cfg.thresh)).sum())

        print(f"\n{name}")
        print(f"  our arithmetic on the golden map : {exact_ref}/{len(want)} exact, "
              f"worst {worst_ref:.0f} px")
        print(f"  our arithmetic on the NPU map    : {exact_npu}/{len(want)} exact, "
              f"worst {worst_npu:.0f} px")
        print(f"  NPU map vs golden map            : max {diff.max():.6f}, "
              f"mean {diff.mean():.6f}, {flip} threshold-crossing pixels")

        # -- 3: how far the threshold would have to move ------------------
        print("  threshold sweep on the NPU map (worst deviation per delta):")
        for delta in (-0.004, -0.002, 0.0, 0.002, 0.004):
            swept = dataclasses.replace(backend._cfg,
                                        thresh=backend._cfg.thresh + delta)
            boxes, _ = det_postprocess(npu, shape, swept)
            _e, worst = _deviation(boxes, want)
            print(f"    thresh{delta:+.3f}: worst {worst:.0f} px")

    import asyncio

    asyncio.run(backend.close())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
