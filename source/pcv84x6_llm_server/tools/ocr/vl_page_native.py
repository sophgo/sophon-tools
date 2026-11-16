#!/usr/bin/env python3
"""Whole-page PaddleOCR-VL: PP-DocLayout-M -> crop -> vit -> prefill -> decode.

MYS-2660's page pipeline. It composes the pieces that already exist and are
already validated rather than re-deriving them:

* **layout** -- ``ppdoclayout-m_f16_640_bm1684x2_static`` through the same
  bmrt ctypes helper (``board_npu.py``) the layout work uses, with the numpy
  tail from ``layout_postprocess.py`` (PaddleX's MulticlassNMS, per-class
  thresholds, ``layout_nms``, and the 23-class merge modes). The postprocess
  is the part that is easy to get subtly wrong, so it is imported, not copied.
* **prompt per class** -- ``vl_native_prep.PROMPT_BY_LABEL``, transcribed from
  the official PaddleOCR-VL-1.5 pipeline.
* **recognition** -- ``vl_native`` per element, which owns vit + the LLM and is
  the only thing that touches the NPU for those graphs.

Two things this file deliberately does NOT do:

* it does not resize a crop to a stage the vit was not compiled for (see the
  fixed-stage note in ``vl_native/README.md``);
* it does not fall back to PP-OCR. Every element is recognised by the VLM, so
  the page result is one model's opinion end to end and a difference against
  the reference is attributable.

Runs on the board. The reading order comes from the layout model itself; the
boxes arrive from ``det_postprocess`` in the order PaddleX would keep them.

    python3 tools/ocr/vl_page_native.py page.png \\
        --layout ppdoclayout-m_f16_640_bm1684x2_static_20261104.bmodel \\
        --vl-bmodel paddleocr-vl-1.5_...bmodel \\
        --tokenizer /data/qa3/vlcfg/paddleocr_vl_1_5/tokenizer.json \\
        --vl-native ./vl_native --out /data/mys2660/page1
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import layout_postprocess as post          # noqa: E402
import board_npu as B                      # noqa: E402
from vl_native_prep import (               # noqa: E402
    SKIP_LABELS, build_ids, prompt_for, vit_input, PATCH,
)

SIDE = 640          # PP-DocLayout-M's network square


# ---------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------

def layout_input(bgr: np.ndarray) -> np.ndarray:
    """The detector's input: square resize, RGB, ImageNet normalisation.

    ``keep_ratio: false`` is the model's own definition (see build_layout_sm.sh),
    not a shortcut -- the graph takes the page squashed to a square.
    """
    import cv2

    resized = cv2.resize(bgr, (SIDE, SIDE), interpolation=cv2.INTER_LINEAR)
    x = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], np.float32)
    std = np.array([0.229, 0.224, 0.225], np.float32)
    # ascontiguousarray is NOT optional. `transpose` returns a view whose
    # `.ctypes.data` still points into the HWC buffer, so uploading it hands
    # bmrt interleaved channels where it expects planar NCHW. The graph still
    # runs and still returns well-formed boxes -- with the table's score at
    # 0.436 instead of 0.892, which reads like a broken model rather than a
    # scrambled input.
    out = ((x - mean) / std).transpose(2, 0, 1)[None]
    return np.ascontiguousarray(out, dtype=np.float32)


def run_layout(bmodel: Path, bgr: np.ndarray, threshold: float,
               merge_mode) -> list[dict]:
    """One layout pass. Returns boxes in page pixels, in the model's order."""
    bmrt, bmlib = B.load_libs()
    import ctypes as C

    handle = C.c_void_p()
    if bmlib.bm_dev_request(C.byref(handle), 0) != 0 or not handle:
        raise RuntimeError("bm_dev_request")
    rt = bmrt.bmrt_create(handle)
    if not bmrt.bmrt_load_bmodel(rt, str(bmodel).encode()):
        raise RuntimeError(f"load {bmodel}")

    info = bmrt.bmrt_get_network_info(rt, b"dlM").contents
    table = B.net_table(info)
    owned = []

    def alloc(n):
        m = B.BmMemDesc()
        if bmlib.bm_malloc_device_byte_heap_mask(handle, C.byref(m), 3, n) != 0:
            raise RuntimeError(f"malloc({n})")
        owned.append(m)
        return m

    x = layout_input(bgr)
    tin = (B.BmTensor * 1)()
    mem = alloc(x.nbytes)
    bmlib.bm_memcpy_s2d(handle, mem, x.ctypes.data)
    bmrt.bmrt_tensor_with_device(C.byref(tin[0]), mem, table["inputs"][0]["dtype"],
                                 B.BmShape(4, (C.c_int * 8)(*x.shape)))

    tout = (B.BmTensor * len(table["outputs"]))()
    outs = {}
    for i, m in enumerate(table["outputs"]):
        arr = np.zeros(m["dims"], np.float32)
        om = alloc(arr.nbytes)
        bmrt.bmrt_tensor_with_device(C.byref(tout[i]), om, m["dtype"],
                                     B.BmShape(len(m["dims"]), (C.c_int * 8)(*m["dims"])))
        outs[m["name"]] = (arr, om)

    if not bmrt.bmrt_launch_tensor_ex(rt, b"dlM", tin, 1, tout, len(tout), True, False):
        raise RuntimeError("layout launch")
    if bmlib.bm_thread_sync(handle) != 0:
        raise RuntimeError("layout sync")
    for i, m in enumerate(table["outputs"]):
        arr, om = outs[m["name"]]
        bmlib.bm_memcpy_d2s(handle, arr.ctypes.data, om)

    for m in owned:
        bmlib.bm_free_device(handle, m)
    bmrt.bmrt_destroy(rt)
    bmlib.bm_dev_free(handle)

    # Output order comes from the graph's own shapes, not from a guess: the
    # last-dim-4 output is the boxes, the one whose axis 1 is the class count
    # is the per-class scores.
    b_arr = next(v[0] for v in outs.values() if v[0].shape[-1] == 4)
    s_arr = next(v[0] for v in outs.values() if v[0].shape[1] == len(post.LABELS))
    h, w = bgr.shape[:2]
    sf = (SIDE / float(h), SIDE / float(w))
    b_page = post.rescale_boxes(b_arr.reshape(-1, 4), sf)
    # det_postprocess already ends in restructured_boxes: it returns the
    # finished dicts (label, score, coordinate, order), not raw rows.
    return post.det_postprocess(b_page, s_arr, (float(h), float(w)),
                                threshold=threshold,
                                num_classes=len(post.LABELS),
                                labels=post.LABELS,
                                layout_nms=True, merge_mode=merge_mode)


# ---------------------------------------------------------------------------
# one element
# ---------------------------------------------------------------------------

def prep_element(bgr: np.ndarray, box: dict, stage, tok, out: Path,
                 max_new: int, seq: int) -> dict | None:
    """Write one element's ``vl_native`` input dir. None when skipped."""
    prompt = prompt_for(box["label"])
    if prompt is None or box["label"] in SKIP_LABELS:
        return None
    import cv2

    x1, y1, x2, y2 = box["coordinate"]
    crop = bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    gh, gw = stage.grid
    out.mkdir(parents=True, exist_ok=True)
    vit_input(crop, stage.h, stage.w).tofile(out / "patches.f32")
    cv2.imwrite(str(out / "crop.png"), crop)
    cv2.imwrite(str(out / "stage.png"),
                cv2.resize(crop, (stage.w, stage.h), interpolation=cv2.INTER_CUBIC))
    ids, head_len = build_ids(tok, prompt, stage.image_tokens)
    np.asarray(ids, np.int32).tofile(out / "ids.i32")
    eos = tok.token_to_id("</s>")
    (out / "meta.txt").write_text(
        f"head_len {head_len}\ngrid_h {gh}\ngrid_w {gw}\n"
        f"max_new {max_new}\neos_id {eos}\nseq {seq}\n", encoding="utf-8")
    (out / "prep.json").write_text(json.dumps({
        "crop_size": [x2 - x1, y2 - y1], "label": box["label"], "prompt": prompt,
        "stage": str(stage), "grid": [gh, gw],
        "image_tokens": stage.image_tokens, "prompt_tokens": len(ids),
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"label": box["label"], "prompt": prompt, "coordinate": box["coordinate"],
            "crop_size": [x2 - x1, y2 - y1], "stage": str(stage),
            "grid": [gh, gw], "prompt_tokens": len(ids),
            "image_tokens": stage.image_tokens}


def read_timings(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition(" ")
        if k == "tokens":
            out["tokens"] = [int(t) for t in v.split()]
        else:
            try:
                out[k] = float(v)
            except ValueError:
                pass
    return out


# ---------------------------------------------------------------------------

def cmd_layout(args) -> int:
    """Layout only, in its own process. Writes boxes.json."""
    import cv2

    bgr = cv2.imread(str(args.image))
    if bgr is None:
        raise SystemExit(f"cannot read {args.image}")
    merge = (post.MERGE_MODE_STRUCTURE_V3 if args.merge_mode == "structure_v3"
             else None)
    t0 = time.perf_counter()
    boxes = run_layout(args.layout, bgr, args.threshold, merge)
    dt = time.perf_counter() - t0
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "boxes.json").write_text(json.dumps(
        {"boxes": boxes, "layout_ms": round(dt * 1e3, 2),
         "page_size": [bgr.shape[1], bgr.shape[0]]},
        indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(boxes)} boxes in {dt*1e3:.1f} ms", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", type=Path)
    ap.add_argument("--layout", required=True, type=Path)
    ap.add_argument("--vl-bmodel", required=True, type=Path)
    ap.add_argument("--tokenizer", required=True, type=Path)
    ap.add_argument("--vl-native", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--stage", required=True,
                    help="HxW the vit was compiled for, e.g. 784x784")
    ap.add_argument("--max-new", type=int, default=256)
    ap.add_argument("--seq", type=int, default=2048)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--merge-mode", default="structure_v3",
                    choices=["structure_v3", "union"])
    ap.add_argument("--limit", type=int, default=0,
                    help="only the first N elements (0 = all); for a smoke run")
    ap.add_argument("--layout-only", action="store_true",
                    help="run just the layout pass into --out/boxes.json")
    ap.add_argument("--boxes", type=Path, default=None,
                    help="boxes.json from --layout-only; skips layout, which is "
                         "required to run the VL afterwards (the 2.27 GB bmodel "
                         "will not load while the detector holds device memory)")
    args = ap.parse_args()
    if args.layout_only:
        return cmd_layout(args)

    import cv2
    from tokenizers import Tokenizer

    from vl_native_prep import _Stage

    bgr = cv2.imread(str(args.image))
    if bgr is None:
        raise SystemExit(f"cannot read {args.image}")
    h, w = (int(v) for v in args.stage.split("x"))
    stage = _Stage(h, w)
    tok = Tokenizer.from_file(str(args.tokenizer))
    merge = (post.MERGE_MODE_STRUCTURE_V3 if args.merge_mode == "structure_v3"
             else None)

    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    if args.boxes is not None:
        pre = json.loads(args.boxes.read_text(encoding="utf-8"))
        boxes = pre["boxes"]
        layout_s = pre["layout_ms"] / 1e3
    else:
        t0 = time.perf_counter()
        boxes = run_layout(args.layout, bgr, args.threshold, merge)
        layout_s = time.perf_counter() - t0

    elements, skipped = [], []
    for i, box in enumerate(boxes):
        if args.limit and len(elements) >= args.limit:
            break
        el_dir = out / f"el{i:03d}"
        meta = prep_element(bgr, box, stage, tok, el_dir, args.max_new, args.seq)
        if meta is None:
            skipped.append({"label": box["label"], "coordinate": box["coordinate"]})
            continue
        t0 = time.perf_counter()
        # Resolve every path handed to the child: it runs with the same cwd but
        # bmrt opens the bmodel by raw path, so a relative one is resolved
        # against whatever directory the caller happened to be in.
        def abspath(p: Path) -> Path:
            return p if p.is_absolute() else (Path.cwd() / p).resolve()

        native = abspath(args.vl_native)
        vl_bmodel = abspath(args.vl_bmodel)
        el_dir, el_out = abspath(el_dir), abspath(el_dir)
        proc = subprocess.run(
            [str(native), "--bmodel", str(vl_bmodel),
             "--work", str(el_dir), "--out", str(el_out)],
            capture_output=True, text=True, timeout=600)
        wall = time.perf_counter() - t0
        if proc.returncode != 0:
            meta["error"] = proc.stderr.strip()[-400:]
            elements.append(meta)
            continue
        tm = read_timings(el_dir / "timings.txt")
        tokens = tm.pop("tokens", [])
        meta.update({
            "tokens": tokens,
            "text": tok.decode(tokens, skip_special_tokens=True),
            "wall_s": round(wall, 3),
            "vit_ms": tm.get("vit_ms"), "prefill_ms": tm.get("prefill_ms"),
            "decode_ms": tm.get("decode_ms"),
            "decode_steps": tm.get("decode_steps"),
            "decode_per_token_median_ms": tm.get("decode_per_token_median_ms"),
        })
        elements.append(meta)
        print(f"[{i:2d}] {meta['label']:<16} {meta['crop_size']} "
              f"{len(tokens)} tok  vit {meta['vit_ms']:.0f} "
              f"prefill {meta['prefill_ms']:.0f} decode {meta['decode_ms']:.0f} ms",
              file=sys.stderr, flush=True)

    result = {
        "page": str(args.image), "page_size": [w, h],
        "stage": str(stage), "layout_ms": round(layout_s * 1e3, 2),
        "boxes": len(boxes), "recognised": len(elements),
        "skipped": skipped, "elements": elements,
        "totals": {
            "vit_ms": round(sum(e.get("vit_ms") or 0 for e in elements), 1),
            "prefill_ms": round(sum(e.get("prefill_ms") or 0 for e in elements), 1),
            "decode_ms": round(sum(e.get("decode_ms") or 0 for e in elements), 1),
            "wall_s": round(sum(e.get("wall_s") or 0 for e in elements), 1),
        },
    }
    result["totals"]["page_s"] = round(
        layout_s + result["totals"]["wall_s"], 2)
    (out / "page.json").write_text(json.dumps(result, indent=1, ensure_ascii=False),
                                   encoding="utf-8")
    print(json.dumps({"boxes": len(boxes), "recognised": len(elements),
                      "layout_ms": result["layout_ms"], **result["totals"]},
                     indent=1), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
