#!/usr/bin/env python3
"""Drive the layout bmodels on the board's NPU and compare with the reference.

Runs **on the board**. It reads the ``.npz`` inputs that
``structure_reference.py`` wrote on the host (the *same* pre-processed tensors,
so preprocessing cannot be the explanation for a difference), launches the
bmodel through ``board_npu.py``, applies the same numpy tail as the reference,
and prints the per-image comparison.

    python3 structure_board.py --bmodel dlS.bmodel --model PP-DocLayout-S \\
        --ref-dir ref --out board.json

The tail is imported from the same files the host used, so this is a
like-for-like comparison: graph + hardware is the only variable.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout_postprocess as post  # noqa: E402


_WARMED: set[str] = set()


def warm(bpy: str, bmodel: Path, workdir: Path) -> None:
    """Absorb the first-launch-after-boot zero result.

    Measured on `.157`: the first NPU launch after a boot returns all zeros
    (scores 0.0, boxes 0.0); every launch after it is correct and stable. Each
    launch here is a separate process, so it is the *first process to touch the
    NPU* that pays, not the first launch in a process -- which is why this was
    invisible while a previous run had already warmed the device and then made
    a whole verification look like a 0/27 regression.
    """
    if str(bmodel) in _WARMED:
        return
    import subprocess
    proc = subprocess.run([sys.executable, bpy, "--bmodel", str(bmodel), "--json"],
                          capture_output=True, text=True)
    if proc.returncode == 0:
        dims = tuple(json.loads(proc.stdout)[0]["inputs"][0]["dims"])
        name = json.loads(proc.stdout)[0]["inputs"][0]["name"]
        np.save(workdir / "warm.npy", np.zeros(dims, np.float32))
        subprocess.run([sys.executable, bpy, "--bmodel", str(bmodel),
                        "--input", f"{name}={workdir/'warm.npy'}",
                        "--out", str(workdir / "warm.npz")],
                       capture_output=True, text=True)
    _WARMED.add(str(bmodel))


def run_bmodel(py: str, bmodel: Path, image: np.ndarray, workdir: Path) -> list:
    """One NPU launch through board_npu.py; returns the two output tensors."""
    np.save(workdir / "in.npy", image)
    out = workdir / "out.npz"
    cmd = [sys.executable, py, "--bmodel", str(bmodel),
           "--input", f"image={workdir/'in.npy'}", "--out", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"board_npu failed:\n{proc.stdout}\n{proc.stderr}")
    d = np.load(out)
    # The two outputs are emitted in the graph's declared order: boxes, scores.
    return [d[k] for k in d.files]


def iou(a, b):
    """Plain IoU on xyxy boxes (the acceptance metric, not PaddleX's +1 form)."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    ub = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    denom = ua + ub - inter
    return inter / denom if denom > 0 else 0.0


def match(ours, ref, iou_thr=0.9):
    """Greedy one-to-one match by IoU; returns (matched, total_ref, same_label)."""
    used = set()
    matched = same_label = 0
    for r in ref:
        best, best_iou = None, 0.0
        for i, o in enumerate(ours):
            if i in used:
                continue
            v = iou(o["coordinate"], r["coordinate"])
            if v > best_iou:
                best, best_iou = i, v
        if best is not None and best_iou >= iou_thr:
            used.add(best)
            matched += 1
            same_label += int(ours[best]["label"] == r["label"])
    return matched, len(ref), same_label


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bmodel", required=True, type=Path)
    ap.add_argument("--model", required=True)
    ap.add_argument("--ref-dir", required=True, type=Path)
    ap.add_argument("--board-npu", default="board_npu.py")
    ap.add_argument("--out", type=Path, default=Path("board.json"))
    ap.add_argument("--repeat", type=int, default=5,
                    help="launches per image for the timing median")
    args = ap.parse_args()

    ref = json.loads((args.ref_dir / "reference.json").read_text())[args.model]
    labels = post.load_labels()
    merge = post.MERGE_MODE_STRUCTURE_V3

    results = {}
    totals = {"matched": 0, "ref": 0, "label": 0}
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        warm(args.board_npu, args.bmodel, work)
        for npz in sorted((args.ref_dir).glob(f"{args.model}__*.npz")):
            d = np.load(npz)
            image, sf = d["image"], d["scale_factor"]
            # npz are written as "<model>__<stem>.npz"; reference.json is
            # keyed by "<stem>.<ext>" because it is indexed by p.name.
            stem = npz.name[len(args.model) + 2:-4]
            name = next(k for k in ref if k.rsplit(".", 1)[0] == stem)

            times = []
            outs = None
            for i in range(args.repeat):
                t0 = time.perf_counter()
                outs = run_bmodel(args.board_npu, args.bmodel, image, work)
                times.append((time.perf_counter() - t0) * 1000.0)

            raw_boxes, raw_scores = outs[0], outs[1]
            page = tuple(ref[name]["page_hw"])
            boxes = post.det_postprocess(
                post.rescale_boxes(raw_boxes.reshape(-1, 4), sf)[None],
                raw_scores, page, labels=labels, merge_mode=merge)

            # The launch time includes python startup + NPU load, so report it
            # as wall time per launch rather than pretending it is pure NPU.
            matched, total, same = match(boxes, ref[name]["boxes"])
            totals["matched"] += matched
            totals["ref"] += total
            totals["label"] += same
            results[name] = {
                "boxes": len(boxes), "ref_boxes": total,
                "iou90": matched, "same_label": same,
                "median_ms": round(float(np.median(times)), 1),
            }
            print(f"  {name:20s} ours={len(boxes):3d} ref={total:3d} "
                  f"IoU>=0.9 {matched}/{total} label {same}/{total} "
                  f"{np.median(times):7.1f} ms")

    summary = {
        "model": args.model,
        "iou90_ratio": round(totals["matched"] / totals["ref"], 4)
        if totals["ref"] else None,
        "label_ratio": round(totals["label"] / totals["ref"], 4)
        if totals["ref"] else None,
        "totals": totals,
        "per_image": results,
    }
    print(f"{args.model}: IoU>=0.9 {totals['matched']}/{totals['ref']} = "
          f"{summary['iou90_ratio']}, label {totals['label']}/{totals['ref']}")
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
