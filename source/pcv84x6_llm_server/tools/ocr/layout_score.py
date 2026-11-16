#!/usr/bin/env python3
"""Score board heads output against the x86 reference boxes.

    python3 tools/ocr/layout_score.py --ref ref_boxes.json \
        --prefix board/f16.json --out board/score_f16.json

Matching criterion (from the issue): a reference box counts as matched when
some board box has IoU >= 0.9 *and* the same class. Boxes are compared in the
reference's own reading order, so a missing box is identifiable rather than
just a count shortfall.
"""
import argparse, json, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout_reference as ref
import layout_runner as runner


def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    ua = max(0.0, ax2-ax1)*max(0.0, ay2-ay1) + max(0.0, bx2-bx1)*max(0.0, by2-by1) - inter
    return inter / ua if ua > 0 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True)
    ap.add_argument("--prefix", required=True, help="board_layout.py --out value")
    ap.add_argument("--threshold", type=float, default=0.3)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    r = json.loads(Path(args.ref).read_text(encoding="utf-8"))
    meta = json.loads(Path(args.prefix).read_text(encoding="utf-8"))
    report, tot_ref, tot_ok, tot_cls = {}, 0, 0, 0
    for name, entry in sorted(r.items()):
        w, h = entry["size"]
        base = Path(f"{args.prefix}.{name}")
        boxes_all = np.load(str(base) + ".helper.unsqueeze.264_Unsqueeze.npy")
        logits_all = np.load(str(base) + ".helper.unsqueeze.265_Unsqueeze_f32.npy")
        order_all = np.load(str(base) + ".helper.unsqueeze.267_Unsqueeze_f32.npy")
        got = runner.boxes_from_heads([boxes_all, logits_all, order_all],
                                      (float(h), float(w)),
                                      threshold=args.threshold,
                                      merge_mode=ref.MERGE_MODE_15)
        want = entry["boxes"]
        rows, ok, cls_ok = [], 0, 0
        for b in want:
            best = (0.0, None)
            for g in got:
                if g["cls_id"] != b["cls_id"]:
                    continue
                v = iou(b["coordinate"], g["coordinate"])
                if v > best[0]:
                    best = (v, g)
            hit = best[0] >= 0.9
            ok += hit
            cls_ok += bool(best[1] is not None)
            rows.append({"label": b["label"], "ref_score": round(b["score"], 4),
                         "ref_box": b["coordinate"], "iou": round(best[0], 4),
                         "board_box": best[1]["coordinate"] if best[1] else None,
                         "matched": hit})
        report[name] = {"ref": len(want), "board": len(got), "matched": ok,
                        "class_present": cls_ok, "boxes": rows}
        tot_ref += len(want); tot_ok += ok; tot_cls += cls_ok
        print(f"{name:16s} ref {len(want):3d}  board {len(got):3d}  "
              f"IoU>=0.9 {ok:3d}  ratio {ok/max(1,len(want))*100:5.1f}%")
    summary = {"total_ref": tot_ref, "total_matched": tot_ok,
               "ratio": tot_ok / max(1, tot_ref), "class_present": tot_cls}
    report["_summary"] = summary
    Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nTOTAL {tot_ok}/{tot_ref} = {summary['ratio']*100:.1f}%")


if __name__ == "__main__":
    main()
