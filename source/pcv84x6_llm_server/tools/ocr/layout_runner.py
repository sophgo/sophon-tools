#!/usr/bin/env python3
"""Layout bmodel -> boxes, as the pipeline will drive it.

The bmodel stops at the decoder heads (`boxes`/`logits`/`order`, each
[1, layers, 300, *]) because PaddleX's post-processing is Python anyway and its
dynamic ops hang this chip's NPU. This script is the other half: take the bmodel
outputs, apply the reference's own post-process, and print the boxes.

    python3 tools/ocr/layout_runner.py --heads heads.npz --image page.png
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout_reference as ref


def boxes_from_heads(raw, img_size, threshold=0.3, merge_mode=None):
    boxes_all, logits_all, order_all = raw
    # Last decoder layer only: PPDocLayoutV3.forward takes intermediate[-1].
    boxes = boxes_all[0, -1]
    logits = logits_all[0, -1]
    order = order_all[0, -1]
    scores = 1.0 / (1.0 + np.exp(-logits))          # sigmoid, focal loss
    # top-k over (query, class): exactly PPDocLayoutV3PostProcess's
    # `scores.flatten(1)` then `index % num_classes`.
    num_classes = scores.shape[-1]
    flat = scores.reshape(-1)
    top = np.argsort(-flat)[:300]
    labels = top % num_classes
    qidx = top // num_classes
    picked_boxes = boxes[qidx]
    picked_scores = flat[top]
    # normalised cxcywh -> absolute xyxy
    h, w = img_size
    cx, cy, bw, bh = picked_boxes.T
    xyxy = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1)
    xyxy[:, [0, 2]] *= w
    xyxy[:, [1, 3]] *= h
    rows = np.concatenate([labels[:, None].astype(np.float32),
                           picked_scores[:, None], xyxy], axis=1)
    # Order: the reference's `get_order` vote over the full 300x300 matrix of
    # the last layer, then sampled at the picked queries. get_order expects a
    # batch axis, so the [300, 300] matrix goes in as [1, 300, 300].
    seq, _ = ref.get_order(order[None].astype(np.float32))
    rows = np.concatenate([rows, seq[0][qidx][:, None].astype(np.float32)], axis=1)
    return ref.decode([rows, np.array([len(rows)], np.int32), None],
                      img_size, threshold=threshold, merge_mode=merge_mode)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--heads", required=True, type=Path)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--threshold", type=float, default=0.3)
    ap.add_argument("--merge-mode", choices=("union", "yaml"), default="yaml")
    args = ap.parse_args()
    d = np.load(args.heads)
    raw = [d["boxes"], d["logits"], d["order"]]
    merge = ref.MERGE_MODE_15 if args.merge_mode == "yaml" else None
    boxes = boxes_from_heads(raw, (args.height, args.width), args.threshold, merge)
    print(f"{len(boxes)} boxes", file=sys.stderr)
    for i, b in enumerate(boxes):
        x1, y1, x2, y2 = b["coordinate"]
        print(f"{i:3d} {b['label']:<18} {b['score']:.3f} "
              f"[{x1:7.1f},{y1:7.1f},{x2:7.1f},{y2:7.1f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
