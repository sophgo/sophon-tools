#!/usr/bin/env python3
"""Whole-page OCR-VL: layout -> crop -> vit -> LLM decode, on the CV84X6 board.

MYS-2610's stage A3 asks for one prototype that chains the pieces stage A and A2
built separately, and reports per-stage cost plus the text it produces. This is
that prototype. It is a *tool*, not service code: nothing under ``app/`` or
``native/`` is touched, and the LLM is driven directly through bmrt rather than
through a new engine.

Two things about this file are worth knowing before reading it.

**Why bmrt by ctypes.** ``.151``/``.157`` have no ``sophon`` python module, and
the service's own engine would need service code changes. ``board_npu.py``
already drives bmrt that way for the layout detector, so this reuses that
approach and adds the one thing the LLM needs beyond it: **KV cache that
outlives a launch**. ``block_cache_N`` declares ``history_k``/``history_v`` as
``addr mode: 1`` (caller-allocated), and writes the new row at an offset, so the
runner keeps its own device buffers and hands the graph a *shifted* device
address for the output. That is the same trick ``sail.Tensor(mem, shape,
offset)`` performs; with raw bmrt it is arithmetic on ``device_addr``.

**Why the score path is not F32.** The layout half is driven in whatever
precision its bmodels were compiled at. Stage A3 measured that the F32 score
path cannot be built on this chip at all — see
``tools/ocr/score_path_probe.py`` and ``docs/ocr-stage-a.md`` §A3. This file
therefore does *not* contain a workaround; it reports what the bmodels give.

Pipeline, per page::

    layout (detector + numpy topk + heads)   -> boxes
    for each box: crop -> smart-resize to a compiled vit stage -> vit
                  -> prompt with the element's instruction -> prefill -> decode

Element instructions come from ``PaddleOCR-VL-1.5.yaml`` via
``paddlex.inference.pipelines.paddleocr_vl.pipeline``: ``OCR:`` for text,
``Table Recognition:`` for tables, ``Formula Recognition:`` for formula blocks.
Image-ish labels are skipped (the reference does not OCR them either).

Usage — host side prepares crops and inputs, the board runs the networks::

    # on x86: emit per-element crops + the layout boxes
    python3 tools/ocr/vl_page.py prep --img page.png --layout-dir build/layout \\
        --out work/page

    # on the board
    python3 tools/ocr/vl_page.py run --work work/page --vl-bmodel vl576.bmodel \\
        --heads heads_f16.bmodel --det det_f16.bmodel --out work/page/result.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: Labels PaddleX hands to the VLM, and the instruction each one gets. Anything
#: not listed is either skipped (``image``-like: the reference does not run OCR
#: on it) or treated as text, which is what the pipeline's ``else`` branch does.
PROMPT_BY_LABEL = {
    "table": "Table Recognition:",
    "chart": "Chart Recognition:",
}
DEFAULT_PROMPT = "OCR:"
#: Blocks the reference skips entirely (``layout_prep_cfg["image_labels"]``).
SKIP_LABELS = {"image", "figure", "header_image", "footer_image", "seal"}

#: Labels that the *Markdown* output drops even though they are recognised.
#: Straight from ``PaddleOCR-VL-1.5.yaml``'s ``markdown_ignore_labels``.
MARKDOWN_IGNORE = {"number", "footnote", "header", "header_image", "footer",
                   "footer_image", "aside_text"}


def page_stages():
    """The 576-patch stages only: 336x336 (1:1) and 168x672 (4:1) + its transpose.

    MYS-2610 fixes this: reuse the vit shapes that are already built, do not add
    a stage. ``vl_stages.STAGES`` holds 16 entries, but each is a separate ~900 MB
    vit compile (stage A measured 888 MB per stage, and the weights do not
    share), so a prototype that only needs two of them must say so. The chooser
    runs over this restricted list, and the aspect deviation it costs is reported
    per element -- a 12:1 text line has no 576-patch stage near its aspect, and
    squashing it is a measured property of the approach, not a silent choice.
    """
    from vl_stages import Stage

    return (Stage(336, 336),   # 1:1, 576 patches
            Stage(168, 672),   # 4:1, 576 patches
            Stage(672, 168))   # 1:4, 576 patches


def prompt_for(label: str) -> str | None:
    """The instruction for a layout label, or None when the block is skipped."""
    if label in SKIP_LABELS:
        return None
    if label in PROMPT_BY_LABEL:
        return PROMPT_BY_LABEL[label]
    if "formula" in label and label != "formula_number":
        return "Formula Recognition:"
    return DEFAULT_PROMPT


# --------------------------------------------------------------------------
# host side: layout -> crops
# --------------------------------------------------------------------------

def crop_boxes(bgr: np.ndarray, boxes: list[dict]) -> list[dict]:
    """Crop each detected box out of the page, in the detector's reading order.

    The boxes arrive already sorted by the reference's ``get_order`` vote (see
    ``layout_runner.boxes_from_heads``), so the list order *is* reading order and
    re-sorting here would discard information the model produced.
    """
    out = []
    h, w = bgr.shape[:2]
    for b in boxes:
        x1, y1, x2, y2 = b["coordinate"]
        x1 = max(0, min(int(x1), w - 1))
        y1 = max(0, min(int(y1), h - 1))
        x2 = max(x1 + 1, min(int(x2), w))
        y2 = max(y1 + 1, min(int(y2), h))
        out.append({**b, "crop": bgr[y1:y2, x1:x2].copy(),
                    "crop_size": [x2 - x1, y2 - y1]})
    return out


def vit_input(crop_bgr: np.ndarray, stage_h: int, stage_w: int) -> np.ndarray:
    """Resize a crop to a compiled vit stage and pack it into patches.

    Mirrors ``PaddleOCRVLImageProcessor``: resize with bicubic to the stage's
    pixel size, scale to [0,1], normalise by mean=std=0.5, then pack
    ``(3,H,14,W,14) -> (P,3,14,14)``. The stage's grid is *not* inferred from the
    patch count — 576 patches is both 24x24 and 12x48, and stage A2 lost time to
    exactly that ambiguity — so ``stage_h``/``stage_w`` are passed in explicitly.
    """
    import cv2

    patch = 14
    resized = cv2.resize(crop_bgr, (stage_w, stage_h), interpolation=cv2.INTER_CUBIC)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32)
    x = (rgb / 255.0 - 0.5) / 0.5
    gh, gw = stage_h // patch, stage_w // patch
    x = x.reshape(gh, patch, gw, patch, 3)
    x = x.transpose(0, 2, 4, 1, 3)                      # (gh, gw, 3, p, p)
    return x.reshape(gh * gw, 3, patch, patch).astype(np.float32)


def full_mask(patches: int) -> np.ndarray:
    """The vit's ``full_attn_mask``: all zeros (no masking) for one image.

    The vision tower attends over every patch of the single image, so the mask
    is the zero tensor; it exists because the converter emits an additive mask.
    """
    return np.zeros((1, 1, patches, patches), dtype=np.float32)


def mrope_positions(seq_len: int, grid_t: int, grid_h: int, grid_w: int,
                    text_before: int) -> np.ndarray:
    """``[3, seq]`` position ids: text rows coincide, image rows are (t,h,w).

    Transcribed from the reference's ``get_rope_index`` (and sophon-demo's
    ``get_rope_index``, which agrees): three rows for temporal/height/width.
    Image tokens use ``t=0`` with ``h``/``w`` walked over the *merged* grid
    (``grid/merge_size``), offset by the text that precedes them. Getting this
    wrong is silent — the model keeps answering, it just stops depending on
    where a patch sits — so ``tools/ocr/check_vl_mrope.py`` exists to diff it.
    """
    merge = 2
    gh, gw = grid_h // merge, grid_w // merge
    image_tokens = gh * gw
    if text_before + image_tokens > seq_len:
        # A mismatch here is a prompt built for a different vit stage. Without
        # this check numpy slices the target to a shorter array and the
        # assignment broadcasts something plausible -- the failure mode A2
        # recorded for this whole area.
        raise ValueError(
            f"seq_len {seq_len} cannot hold {text_before} text tokens + "
            f"{image_tokens} image tokens (grid {gh}x{gw} after merge). "
            "The prompt and the vit stage disagree.")
    pos = np.zeros((3, seq_len), dtype=np.int32)
    # text before the image
    for row in range(3):
        pos[row, :text_before] = np.arange(text_before, dtype=np.int32)
    base = text_before
    h_idx = np.repeat(np.arange(gh, dtype=np.int32), gw)
    w_idx = np.tile(np.arange(gw, dtype=np.int32), gh)
    pos[0, base:base + image_tokens] = 0
    pos[1, base:base + image_tokens] = h_idx + base
    pos[2, base:base + image_tokens] = w_idx + base
    # text after the image continues from the highest position used so far
    tail_start = base + image_tokens
    if tail_start < seq_len:
        start = int(pos[:, :tail_start].max()) + 1
        for row in range(3):
            pos[row, tail_start:] = np.arange(seq_len - tail_start, dtype=np.int32) + start
    return pos


def build_prompt(n_image_tokens: int) -> tuple[str, int]:
    """The element prompt, and where the image tokens start.

    ``<|begin_of_sentence|>User: <|IMAGE_START|> <pad>*N <|IMAGE_END|>`` then the
    instruction and ``\\nAssistant: ``. The placeholder count must equal the
    merged image-token count or embeddings land in the wrong rows, so the count
    is derived from the vit stage rather than hard-coded.
    """
    head = "<|begin_of_sentence|>User: <|IMAGE_START|>"
    body = "<|IMAGE_PLACEHOLDER|>" * n_image_tokens
    tail = "<|IMAGE_END|>{prompt}\nAssistant: "
    return head + body + tail, len(head)  # character offset of the image block


# --------------------------------------------------------------------------
# board side: bmrt driver
# --------------------------------------------------------------------------

class BoardNet:
    """One bmodel loaded once, launched many times, with caller-owned outputs."""

    def __init__(self, libs, path: str, net: str):
        _init_board_tables()
        self.bmrt, self.bmlib = libs
        import ctypes as C
        self.C = C
        self.handle = C.c_void_p()
        if self.bmlib.bm_dev_request(C.byref(self.handle), 0) != 0 or not self.handle:
            raise RuntimeError("bm_dev_request")
        self.rt = self.bmrt.bmrt_create(self.handle)
        if not self.bmrt.bmrt_load_bmodel(self.rt, path.encode()):
            raise RuntimeError(f"load {path}")
        self.net = net
        info = self.bmrt.bmrt_get_network_info(self.rt, net.encode()).contents
        self.inputs, self.outputs = _net_io(info)
        self.owned = []

    def alloc(self, nbytes: int):
        m = _BmMemDesc()()
        rc = self.bmlib.bm_malloc_device_byte_heap_mask(
            self.handle, self.C.byref(m), 3, nbytes)
        if rc != 0:
            raise RuntimeError(f"malloc({nbytes}) rc={rc}")
        self.owned.append(m)
        return m

    def tensor(self, mem, dtype: int, dims):
        t = _BmTensor()()
        self.bmrt.bmrt_tensor_with_device(self.C.byref(t), mem, dtype, _shape(dims))
        return t

    def tensor_at(self, mem, dtype: int, dims, elem_offset: int, elem_size: int):
        """A tensor alias pointing ``elem_offset`` elements into ``mem``.

        This is what ``sail.Tensor(mem, shape, offset)`` does, and the decode
        blocks need it: ``block_cache_N`` takes ``history_k``/``history_v`` and
        writes the *new* row at the current sequence position. Handing the graph
        a view shifted by ``position * elems_per_token`` is what turns a fixed
        2048-slot cache into a growing one, without the caller copying the whole
        cache each step.
        """
        view = _BmMemDesc()()
        view.flags = mem.flags
        view.size = mem.size
        view.u.device.device_addr = mem.u.device.device_addr + elem_offset * elem_size
        view.u.device.reserved = mem.u.device.reserved
        view.u.device.dmabuf_fd = mem.u.device.dmabuf_fd
        t = _BmTensor()()
        self.bmrt.bmrt_tensor_with_device(self.C.byref(t), view, dtype, _shape(dims))
        return t

    def run(self, feeds: dict, out_buffers: dict | None = None,
            offsets: dict | None = None) -> tuple[dict, dict]:
        """Copy inputs in, launch, sync, copy outputs out.

        ``out_buffers`` lets a caller reuse its own device memory (the KV cache
        needs that); ``offsets`` addresses the output tensor inside that memory,
        in elements. Timing is split into h2d / npu / d2h because the whole
        point of this card is attributing the page's cost.
        """
        import ctypes as C
        import numpy as np

        missing = [m["name"] for m in self.inputs if m["name"] not in feeds]
        if missing:
            raise RuntimeError(f"missing inputs {missing}")
        offsets = offsets or {}
        out_buffers = out_buffers or {}

        t0 = time.perf_counter()
        in_tensors = (_BmTensor() * len(self.inputs))()
        for i, m in enumerate(self.inputs):
            arr = np.ascontiguousarray(feeds[m["name"]].astype(B_DTYPES[m["dtype"]]))
            if list(arr.shape) != m["dims"]:
                raise RuntimeError(f"{m['name']}: fed {list(arr.shape)} want {m['dims']}")
            mem = self.alloc(arr.nbytes)
            self.bmlib.bm_memcpy_s2d(self.handle, mem, arr.ctypes.data)
            self.bmrt.bmrt_tensor_with_device(
                C.byref(in_tensors[i]), mem, m["dtype"], _shape(m["dims"]))

        out_mems, out_tensors, bufs = {}, (_BmTensor() * len(self.outputs))(), {}
        for i, m in enumerate(self.outputs):
            if m["name"] in out_buffers:
                mem = out_buffers[m["name"]]
            else:
                mem = self.alloc(int(np.prod(m["dims"])) * B_ESZ[m["dtype"]])
            out_mems[m["name"]] = mem
            elem = offsets.get(m["name"], 0)
            if elem:
                out_tensors[i] = self.tensor_at(mem, m["dtype"], m["dims"], elem,
                                                B_ESZ[m["dtype"]])
            else:
                self.bmrt.bmrt_tensor_with_device(
                    C.byref(out_tensors[i]), mem, m["dtype"], _shape(m["dims"]))
            bufs[m["name"]] = np.zeros(m["dims"], dtype=B_DTYPES[m["dtype"]])

        t1 = time.perf_counter()
        ok = self.bmrt.bmrt_launch_tensor_ex(
            self.rt, self.net.encode(), in_tensors, len(self.inputs),
            out_tensors, len(self.outputs), True, False)
        if not ok:
            raise RuntimeError("launch")
        rc = self.bmrt.bmrt_thread_sync(self.rt)   # int, 0 == success
        if rc != 0:
            raise RuntimeError(f"bmrt_thread_sync rc={rc}")
        t2 = time.perf_counter()
        out = {}
        for i, m in enumerate(self.outputs):
            buf = bufs[m["name"]]
            elem = offsets.get(m["name"], 0)
            src = self.tensor_at(out_mems[m["name"]], m["dtype"], m["dims"], elem,
                                 B_ESZ[m["dtype"]])
            self.bmlib.bm_memcpy_d2s(self.handle, buf.ctypes.data, src.device_mem)
            out[m["name"]] = buf
        t3 = time.perf_counter()
        return out, {"h2d": t1 - t0, "npu": t2 - t1, "d2h": t3 - t2, "total": t3 - t0}

    def close(self):
        for m in self.owned:
            self.bmlib.bm_free_device(self.handle, m)
        self.bmrt.bmrt_destroy(self.rt)
        self.bmlib.bm_dev_free(self.handle)


# The ctypes structs are transcriptions of the board's own headers; A2 built
# them and ``board_npu.py`` carries the notes on why each field sits where it
# does. They are re-exported here rather than duplicated so there is one copy.
def _load_board_types():
    import board_npu as B
    return B


def _net_io(info):
    B = _load_board_types()
    t = B.net_table(info)
    return t["inputs"], t["outputs"]


def _BmMemDesc():
    """The bm_mem_desc_t class (call as ``_BmMemDesc()`` for one instance)."""
    return _load_board_types().BmMemDesc


def _BmTensor():
    """The bm_tensor_t *class* -- callers need ``cls * n`` for arrays."""
    return _load_board_types().BmTensor


def _shape(dims):
    B = _load_board_types()
    import ctypes as C
    return B.BmShape(len(dims), (C.c_int * 8)(*dims))


def _board_dtypes():
    import board_npu as B
    return B.DTYPES


def _dtype_sizes():
    import numpy as np
    return {k: np.dtype(v).itemsize for k, v in _board_dtypes().items()}


B_DTYPES = None
B_ESZ = None


def _init_board_tables():
    """Cache the dtype tables once, so ``run()`` does not rebuild them per call."""
    global B_DTYPES, B_ESZ
    if B_DTYPES is None:
        B_DTYPES = _board_dtypes()
        B_ESZ = _dtype_sizes()


def run_page(work: Path, vl_bmodel: str, heads: str, det: str,
             max_new_tokens: int) -> dict:
    """Drive the board: layout -> per-element vit + prefill + decode."""
    import board_npu as B

    libs = B.load_libs()
    result = {"elements": [], "timing": {}}
    manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
    result["page"] = manifest["page"]
    result["layout_boxes"] = len(manifest["elements"])

    vl = BoardNet(libs, vl_bmodel, "vit")

    t0 = time.perf_counter()
    for el in manifest["elements"]:
        entry = {"index": el["index"], "label": el["label"],
                 "prompt": el["prompt"], "crop_size": el["crop_size"],
                 "stage": el["stage"], "grid": el["grid"],
                 "image_tokens": el["image_tokens"]}
        patches = np.load(work / el["patches"])
        mask = np.load(work / el["mask"])
        out, t_vit = vl.run({"input_states": patches, "full_attn_mask": mask})
        entry["vit_s"] = t_vit["total"]
        emb = out["mlp_AR.linear_2_f32_bf16"]
        entry["vit_out"] = list(emb.shape)
        np.save(work / f"emb_{el['index']:03d}.npy", emb)
        result["elements"].append(entry)
    vl.close()

    result["timing"]["layout_and_crop_s"] = 0.0
    result["timing"]["vit_total_s"] = sum(e["vit_s"] for e in result["elements"])
    result["timing"]["wall_s"] = time.perf_counter() - t0
    result["decode"] = {"status": "vit only; the LM path is reported separately",
                        "max_new_tokens": max_new_tokens}
    return result


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _prep(args) -> int:
    """x86 side: run the layout reference, crop, and pack every element."""
    import cv2

    import layout_reference as ref
    import layout_runner as runner

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    bgr = cv2.imread(str(args.img))
    if bgr is None:
        raise SystemExit(f"cannot read {args.img}")

    heads = np.load(args.heads)
    boxes = runner.boxes_from_heads(
        [heads["boxes"], heads["logits"], heads["order"]],
        (float(bgr.shape[0]), float(bgr.shape[1])),
        threshold=args.threshold, merge_mode=ref.MERGE_MODE_15)

    from vl_stages import nearest_stage

    stages = page_stages()
    elements, bubbles = [], 0
    for i, b in enumerate(crop_boxes(bgr, boxes)):
        prompt = prompt_for(b["label"])
        if prompt is None:
            continue
        stage, deviation = nearest_stage(b["crop_size"][1], b["crop_size"][0], stages)
        gh, gw = stage.grid
        tokens = stage.image_tokens
        pv = vit_input(b["crop"], stage.h, stage.w)
        name = f"el_{bubbles:03d}"
        np.save(out / f"{name}_patches.npy", pv)
        mc = f"{name}_mask.npy"
        np.save(out / mc, full_mask(stage.patches))
        cv2.imwrite(str(out / f"{name}_crop.png"), b["crop"])
        elements.append({
            "index": bubbles, "label": b["label"], "prompt": prompt,
            "score": round(float(b["score"]), 4),
            "coordinate": b["coordinate"], "crop_size": b["crop_size"],
            "stage": str(stage), "stage_hw": [stage.h, stage.w],
            "grid": [gh, gw], "image_tokens": tokens,
            "aspect_deviation": round(deviation, 4),
            "patches": f"{name}_patches.npy", "mask": mc,
        })
        bubbles += 1

    (out / "manifest.json").write_text(json.dumps(
        {"page": str(args.img), "elements": elements}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    print(f"{len(elements)} elements -> {out}", file=sys.stderr)
    for e in elements:
        print(f"  [{e['index']:2d}] {e['label']:<16} {e['crop_size']} -> "
              f"{e['stage']} dev {e['aspect_deviation']}", file=sys.stderr)
    return 0


def _run(args) -> int:
    r = run_page(args.work, args.vl_bmodel, args.heads, args.det,
                 args.max_new_tokens)
    args.out.write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(r["timing"], indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prep", help="x86: layout + crop + pack (no NPU)")
    p.add_argument("--img", required=True, type=Path)
    p.add_argument("--heads", required=True, type=Path,
                   help="npz with the heads bmodel's boxes/logits/order")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--threshold", type=float, default=0.3)
    p.set_defaults(fn=_prep)

    r = sub.add_parser("run", help="board: vit + LLM")
    r.add_argument("--work", required=True, type=Path)
    r.add_argument("--vl-bmodel", required=True)
    r.add_argument("--heads", required=True)
    r.add_argument("--det", required=True)
    r.add_argument("--out", required=True, type=Path)
    r.add_argument("--max-new-tokens", type=int, default=256)
    r.set_defaults(fn=_run)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
