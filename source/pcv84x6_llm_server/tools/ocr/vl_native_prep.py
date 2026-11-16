#!/usr/bin/env python3
"""Prepare one element for ``vl_native``, and compare what comes back.

MYS-2660 splits the work deliberately: Python owns everything that can be
diffed against a reference on the host (layout, crop, resize, patch packing,
tokenisation, decoding the ids back to text), and the C++ program owns only the
NPU. ``prep`` writes a directory ``vl_native`` reads; ``reference`` runs the HF
model on exactly the same pixels and greedy-decodes; ``compare`` aligns the two
token sequences.

**The pixel contract is the point of ``reference``.** The board runs a *fixed*
vit stage (576 patches, `168x672`/`336x336`/`672x168`, and the 784 stage these
alignments use), so a crop is letterboxed into that stage -- aspect preserved,
white padding -- whatever its aspect ratio. Calling the HF processor's
``smart_resize`` would resize the same crop to a different grid and produce a
different image, which would make every downstream difference unattributable.
So ``prep`` records the exact pixels it packed, and ``reference`` feeds those
pixels (already at the board's grid) back through the model's *own* image
processor path with resizing disabled. A second, separate reference
(``--smart-resize``) uses the model's default resize so the cost of the fixed
stage can be quantified on its own.

Usage::

    # host: pack patches + the prompt ids for one element
    python3 tools/ocr/vl_native_prep.py prep --img page.png --heads heads.npz \\
        --label table --out work/el1

    # board
    ./vl_native --bmodel vl576.bmodel --work work/el1 --out work/el1

    # host: the reference on the same pixels, and the diff
    python3 tools/ocr/vl_native_prep.py reference --work work/el1 --model-dir M
    python3 tools/ocr/vl_native_prep.py compare --work work/el1
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

PATCH = 14
MERGE = 2
FACTOR = PATCH * MERGE

#: The prompt head/tail, verbatim from the reference's chat template. A3
#: recorded that the trailing newline matters: ``Assistant:\n`` and
#: ``Assistant: `` are different token spans and only one of them is what the
#: reference was trained to continue.
HEAD = "<|begin_of_sentence|>User: <|IMAGE_START|>"
TAIL = "<|IMAGE_END|>{prompt}\nAssistant:\n"

#: PP-DocLayout-M class -> the instruction the official PaddleOCR-VL pipeline
#: gives it. Transcribed from PaddleOCR-VL-1.5.yaml (``layout_prep_cfg`` and the
#: pipeline's prompt map), not guessed: the VLM was trained with these exact
#: strings, and ``OCR:`` vs ``Table Recognition:`` alone changes the output
#: format from prose to OTSL.
PROMPT_BY_LABEL = {
    "text": "OCR:",
    "title": "OCR:",
    "paragraph_title": "OCR:",
    "doc_title": "OCR:",
    "abstract": "OCR:",
    "content": "OCR:",
    "reference": "OCR:",
    "footnote": "OCR:",
    "header": "OCR:",
    "footer": "OCR:",
    "number": "OCR:",
    "aside_text": "OCR:",
    "vertical_text": "OCR:",
    "formula": "Formula Recognition:",
    "equation": "Formula Recognition:",
    "table": "Table Recognition:",
    "chart": "Chart Recognition:",
    "figure": "Chart Recognition:",
    "image": "Chart Recognition:",
    "seal": "OCR:",
}
#: Blocks the official pipeline drops before recognition.
SKIP_LABELS = {"header_image", "footer_image"}


def prompt_for(label: str) -> str | None:
    if label in SKIP_LABELS:
        return None
    return PROMPT_BY_LABEL.get(label, "OCR:")


def letterbox(crop_bgr: np.ndarray, stage_h: int, stage_w: int) -> np.ndarray:
    """Scale into the stage **preserving the aspect**, then pad to its size.

    The arithmetic is ``app/engine/paddle_vl._fit_into_square``'s, and it has to
    be bit-identical: ``tests/data/ocr/vl_prep`` is regenerated here and then
    asserted against the service's ``preprocess_image`` element by element.

    Padding is white (255), which is what these crops' own background is; a
    letterbox that padded black would introduce edges the page does not have.

    Why preserve the aspect at all: the model's own ``smart_resize`` does, and
    stretching a 15:1 title into a square makes it hallucinate a fluent line
    (``docs/ocr-vl.md`` §11.9). Since MYS-2681 the chat path does this too, so
    one crop has exactly one tensor whichever surface it arrives on.
    """
    import cv2

    height, width = crop_bgr.shape[:2]
    scale = min(stage_h / float(height), stage_w / float(width))
    new_h = max(1, int(round(height * scale)))
    new_w = max(1, int(round(width * scale)))
    resized = cv2.resize(crop_bgr, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    canvas = np.full((stage_h, stage_w, 3), 255, dtype=np.uint8)
    top = (stage_h - new_h) // 2
    left = (stage_w - new_w) // 2
    canvas[top:top + new_h, left:left + new_w] = resized
    return canvas


def vit_input(crop_bgr: np.ndarray, stage_h: int, stage_w: int) -> np.ndarray:
    """Letterbox to the compiled stage and pack patches, as the service does."""
    import cv2

    resized = letterbox(crop_bgr, stage_h, stage_w)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32)
    x = (rgb / 255.0 - 0.5) / 0.5
    gh, gw = stage_h // PATCH, stage_w // PATCH
    x = x.reshape(gh, PATCH, gw, PATCH, 3).transpose(0, 2, 4, 1, 3)
    return x.reshape(gh * gw, 3, PATCH, PATCH).astype(np.float32)


def mrope_positions(seq_len: int, grid_h: int, grid_w: int,
                    text_before: int) -> np.ndarray:
    """The [3, seq] (t,h,w) table. Mirrors ``get_rope_index`` in the reference.

    ``tools/ocr/check_vl_mrope.py`` diffs this against the model's own
    computation; the C++ side has an independent transcription of the same
    rule, and ``compare`` fails if the two ever disagree about a prompt this
    long.
    """
    h, w = grid_h // MERGE, grid_w // MERGE
    img = h * w
    if text_before + img > seq_len:
        raise ValueError(f"seq {seq_len} < {text_before} text + {img} image")
    pos = np.zeros((3, seq_len), np.int32)
    for r in range(3):
        pos[r, :text_before] = np.arange(text_before)
    base = text_before
    pos[0, base:base + img] = 0
    pos[1, base:base + img] = np.repeat(np.arange(h), w) + base
    pos[2, base:base + img] = np.tile(np.arange(w), h) + base
    tail = base + img
    if tail < seq_len:
        start = int(pos[:, :tail].max()) + 1
        for r in range(3):
            pos[r, tail:] = np.arange(seq_len - tail) + start
    return pos


def build_ids(tok, instruction: str, n_image_tokens: int) -> tuple[list[int], int]:
    """Prompt ids and where the image block starts.

    The placeholder count *must* equal the merged patch count, or vit rows land
    in the wrong positions -- which still runs and still emits text.
    """
    ph = tok.token_to_id("<|IMAGE_PLACEHOLDER|>")
    head = tok.encode(HEAD, add_special_tokens=False).ids
    tail = tok.encode(TAIL.format(prompt=instruction), add_special_tokens=False).ids
    return head + [ph] * n_image_tokens + tail, len(head)


# ---------------------------------------------------------------------------
# prep
# ---------------------------------------------------------------------------

def _write_meta(path: Path, fields: dict) -> None:
    path.write_text("".join(f"{k} {v}\n" for k, v in fields.items()), encoding="utf-8")


def cmd_prep(args) -> int:
    import cv2

    from tokenizers import Tokenizer

    from vl_stages import nearest_stage

    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    bgr = cv2.imread(str(args.img))
    if bgr is None:
        raise SystemExit(f"cannot read {args.img}")

    # Either an explicit box (--box x1,y1,x2,y2) or the whole image, so one
    # element can be prepared without re-running the layout detector.
    if args.box:
        x1, y1, x2, y2 = (int(v) for v in args.box.split(","))
        crop = bgr[y1:y2, x1:x2].copy()
    else:
        crop = bgr
    ch, cw = crop.shape[:2]

    stages = (args.stage,) if args.stage else None
    if stages:
        h, w = (int(v) for v in args.stage.split("x"))
        stage, dev = _Stage(h, w), 1.0
    else:
        from vl_page import page_stages
        stage, dev = nearest_stage(ch, cw, page_stages())
    gh, gw = stage.grid
    n_img = stage.image_tokens

    patches = vit_input(crop, stage.h, stage.w)
    patches.tofile(out / "patches.f32")
    cv2.imwrite(str(out / "crop.png"), crop)
    # The resized image the vit actually consumed, written out so the reference
    # can be handed it directly with do_resize=False. Without this the
    # processor would resize the crop a second time (PIL BICUBIC, not
    # cv2.INTER_CUBIC) and pick its own grid.
    cv2.imwrite(str(out / "stage.png"), letterbox(crop, stage.h, stage.w))

    instruction = args.prompt or prompt_for(args.label or "text")
    tok = Tokenizer.from_file(str(args.tokenizer))
    ids, head_len = build_ids(tok, instruction, n_img)
    np.asarray(ids, np.int32).tofile(out / "ids.i32")

    eos = tok.token_to_id("</s>")
    _write_meta(out / "meta.txt", {
        "head_len": head_len, "grid_h": gh, "grid_w": gw,
        "max_new": args.max_new, "eos_id": eos, "seq": args.seq,
    })
    (out / "prep.json").write_text(json.dumps({
        "image": str(args.img), "crop_size": [cw, ch], "label": args.label,
        "prompt": instruction, "stage": str(stage), "grid": [gh, gw],
        "image_tokens": n_img, "prompt_tokens": len(ids),
        "head_len": head_len, "aspect_deviation": round(dev, 4),
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{cw}x{ch} crop -> {stage} grid {gh}x{gw}, {n_img} image tokens, "
          f"{len(ids)} prompt ids", file=sys.stderr)
    return 0


class _Stage:
    """A stage given on the command line; same arithmetic as vl_stages.Stage."""

    def __init__(self, h: int, w: int):
        self.h, self.w = h, w

    @property
    def grid(self) -> tuple[int, int]:
        return self.h // PATCH, self.w // PATCH

    @property
    def patches(self) -> int:
        gh, gw = self.grid
        return gh * gw

    @property
    def image_tokens(self) -> int:
        return self.patches // (MERGE * MERGE)

    def __str__(self) -> str:
        gh, gw = self.grid
        return f"{self.h}x{self.w} (grid {gh}x{gw}, {self.patches} patches)"


# ---------------------------------------------------------------------------
# reference
# ---------------------------------------------------------------------------

def _apply_reference_shims() -> None:
    """The two transformers-5 compatibility bridges make_golden.py needs.

    PaddleOCR-VL-1.5's shipped modeling file predates transformers 5: it calls
    ``create_causal_mask(inputs_embeds=...)`` (renamed to ``input_embeds``) and
    indexes ``ROPE_INIT_FUNCTIONS["default"]`` (removed). Both are imported from
    make_golden rather than reimplemented -- the golden set in
    tests/data/ocr/golden.json was produced through them, so a reference that
    skipped them would not be the same reference.
    """
    from make_golden import _bridge_mask_kwarg, _ensure_default_rope_registered

    _bridge_mask_kwarg()
    _ensure_default_rope_registered()


def cmd_reference(args) -> int:
    """Greedy-decode with HF transformers.

    Two modes, and the difference between them is the whole point:

    **same pixels (default).** ``patches.f32`` -- the exact tensor ``vl_native``
    uploaded -- is fed straight in as ``pixel_values``, bypassing the
    processor's resize. Re-deriving it through the processor instead is NOT
    equivalent: ``prep`` resizes with ``cv2.INTER_CUBIC`` and the processor uses
    PIL/torchvision BICUBIC, and on a 1240x1400 table crop those two disagree by
    up to 1.42 in normalised pixel units (measured). Feeding the identical
    tensor is what makes a difference in the tokens attributable to the engine.

    **``--smart-resize``.** The model's own resize, at the grid it would pick
    for this crop. This is the reference a deployment *without* a fixed vit
    stage would produce; its grid differs from the board's, and that difference
    is the cost of the fixed stage, reported separately and never mixed with
    the first.
    """
    import torch
    from PIL import Image
    from transformers import AutoProcessor, AutoModelForCausalLM

    _apply_reference_shims()

    work = args.work
    prep = json.loads((work / "prep.json").read_text(encoding="utf-8"))
    gh, gw = prep["grid"]

    proc = AutoProcessor.from_pretrained(args.model_dir, trust_remote_code=True)
    crop = Image.open(work / "crop.png").convert("RGB")

    messages = [{"role": "user", "content": [
        {"type": "image"},
        {"type": "text", "text": prep["prompt"]},
    ]}]
    text = proc.apply_chat_template(messages, add_generation_prompt=True)

    if args.smart_resize:
        inputs = proc(text=text, images=[crop], return_tensors="pt")
    else:
        # Already at the board's stage size: do_resize=False keeps the
        # processor from resampling it a second time and from choosing a
        # different grid, so the placeholder expansion matches the board's
        # prompt length.
        proc.image_processor.do_resize = False
        stage_img = Image.open(work / "stage.png").convert("RGB")
        inputs = proc(text=text, images=[stage_img], return_tensors="pt")
        # Then overwrite with the board's exact patch tensor. Bit-identical
        # input is what makes a token difference attributable to the engine
        # rather than to a resampler.
        patches = np.fromfile(work / "patches.f32", dtype=np.float32)
        pv = torch.from_numpy(patches.reshape(gh * gw, 3, PATCH, PATCH).copy())
        inputs["pixel_values"] = pv.to(inputs["pixel_values"].dtype)
        if "image_grid_thw" in inputs:
            t = int(inputs["image_grid_thw"][0][0])
            inputs["image_grid_thw"] = torch.tensor([[t, gh, gw]])

    # float32, matching make_golden.py: CPU bf16 is dramatically slower and the
    # comparison wants a reference free of its own rounding noise.
    model = AutoModelForCausalLM.from_pretrained(
        args.model_dir, trust_remote_code=True, dtype=torch.float32)
    model.eval()

    with torch.no_grad():
        gen = model.generate(**inputs, max_new_tokens=args.max_new,
                             do_sample=False, temperature=None, top_p=None,
                             top_k=None)
    prompt_len = inputs["input_ids"].shape[1]
    new_ids = gen[0, prompt_len:].tolist()

    if args.price_at:
        positions = [int(v) for v in args.price_at.split(",") if v.strip()]
        steps = _price_positions(model, inputs, new_ids, positions)
    else:
        steps = _reference_steps(model, inputs, new_ids, args.ctx)

    grid = (inputs["image_grid_thw"][0][1:].tolist()
            if "image_grid_thw" in inputs else None)
    name = "reference_smart_resize.json" if args.smart_resize else "reference.json"
    (work / name).write_text(json.dumps({
        "tokens": new_ids,
        "text": proc.decode(new_ids, skip_special_tokens=True),
        "prompt_tokens": prompt_len,
        "grid": grid,
        "board_grid": [gh, gw],
        "smart_resize": bool(args.smart_resize),
        "steps": steps,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(new_ids)} tokens, grid {grid}: "
          f"{proc.decode(new_ids, skip_special_tokens=True)!r}", file=sys.stderr)
    return 0


def _price_positions(model, inputs, tokens, positions) -> list[dict]:
    """Reference top-2 logits at specific generated positions.

    One forward per requested position, feeding the reference's own tokens up
    to it so the context is exactly what the reference saw. This classifies a
    divergence: if the board picked the reference's runner-up with a small gap
    it is bf16 rounding; if the gap is large the two runs saw genuinely
    different distributions.

    Pricing positions are the ones that matter. Pricing only the first N
    answers "was the start right", which is almost never where a greedy decode
    parts company -- on the six-image set every divergence was past position
    14 and the first two positions matched everywhere.
    """
    import torch

    out = []
    want = set(positions)
    if not want:
        return out
    ids = inputs["input_ids"]
    mask = inputs.get("attention_mask")
    for i in range(max(want) + 1):
        with torch.no_grad():
            logits = model(input_ids=ids, attention_mask=mask,
                           pixel_values=inputs.get("pixel_values"),
                           image_grid_thw=inputs.get("image_grid_thw")).logits
        if i in want:
            last = logits[0, -1].float()
            top = torch.topk(last, 2)
            out.append({
                "pos": i,
                "chosen": int(tokens[i]) if i < len(tokens) else None,
                "top1": int(top.indices[0]),
                "top1_logit": float(top.values[0]),
                "top2": int(top.indices[1]),
                "top2_logit": float(top.values[1]),
                "gap": float(top.values[0] - top.values[1]),
            })
        if i < len(tokens):
            ids = torch.cat(
                [ids, torch.tensor([[tokens[i]]], dtype=ids.dtype)], dim=1)
            if mask is not None:
                mask = torch.cat([mask, torch.ones((1, 1), dtype=torch.long)], dim=1)
    return out


def _reference_steps(model, inputs, tokens, ctx: int) -> list[dict]:
    """Teacher-forced top-2 logits at each generated position.

    Re-running the model once per position is slow but exact, and it is the only
    way to answer "was the divergence a near-tie or a real difference". ``ctx``
    caps how many positions are priced, because each one is a full forward.
    """
    import torch

    out = []
    ids = inputs["input_ids"]
    for i, tok in enumerate(tokens[:ctx]):
        with torch.no_grad():
            logits = model(input_ids=ids, attention_mask=inputs["attention_mask"],
                           pixel_values=inputs.get("pixel_values"),
                           image_grid_thw=inputs.get("image_grid_thw")).logits
        last = logits[0, -1].float()
        top = torch.topk(last, 2)
        out.append({
            "pos": i,
            "chosen": int(tok),
            "top1": int(top.indices[0]),
            "top1_logit": float(top.values[0]),
            "top2": int(top.indices[1]),
            "top2_logit": float(top.values[1]),
            "gap": float(top.values[0] - top.values[1]),
        })
        ids = torch.cat([ids, torch.tensor([[tok]], dtype=ids.dtype)], dim=1)
        if "attention_mask" in inputs:
            inputs["attention_mask"] = torch.cat(
                [inputs["attention_mask"], torch.ones((1, 1), dtype=torch.long)], dim=1)
    return out


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------

def cmd_compare(args) -> int:
    work = args.work
    board = _read_tokens(work / "tokens.i32")
    ref_name = "reference_smart_resize.json" if args.smart_resize else "reference.json"
    ref = json.loads((work / ref_name).read_text(encoding="utf-8"))
    ref_ids = ref["tokens"]

    n = min(len(board), len(ref_ids))
    first = next((i for i in range(n) if board[i] != ref_ids[i]), None)
    same = sum(1 for i in range(n) if board[i] == ref_ids[i])

    detail = None
    if first is not None:
        steps = {s["pos"]: s for s in ref.get("steps", [])}
        s = steps.get(first)
        detail = {
            "first_divergence": first,
            "board_token": board[first] if first < len(board) else None,
            "reference_token": ref_ids[first],
            "reference_top1": s["top1"] if s else None,
            "reference_top2": s["top2"] if s else None,
            "reference_top1_logit": s["top1_logit"] if s else None,
            "reference_top2_logit": s["top2_logit"] if s else None,
            # Small gaps mean the board's token was the reference's runner-up,
            # i.e. bf16 noise; a large gap means the board saw a different
            # distribution, i.e. a real difference in the inputs or the graph.
            "gap": s["gap"] if s else None,
        }

    result = {
        "element": str(work),
        "board_tokens": len(board),
        "reference_tokens": len(ref_ids),
        "compared": n,
        "identical": same,
        "ratio": round(same / n, 4) if n else 0.0,
        "exact_match": board[:n] == ref_ids[:n],
        "divergence": detail,
        "board_text": None,
        "reference_text": ref["text"],
    }
    if args.tokenizer:
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(str(args.tokenizer))
        result["board_text"] = tok.decode(board, skip_special_tokens=True)

    (work / ("compare_smart_resize.json" if args.smart_resize
             else "compare.json")).write_text(
        json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("board_text", "reference_text")},
                     indent=1, ensure_ascii=False))
    return 0 if result["exact_match"] else 1


def _read_tokens(path: Path) -> list[int]:
    """Read ``tokens.i32`` exactly as ``vl_native`` writes it.

    Little-endian int32, no header: the C++ does
    ``spit(out + "/tokens.i32", out_ids.data(), n * sizeof(int32_t))`` and the
    target is aarch64, so byte order and element size are fixed. Kept next to
    the writer's twin (``cmd_prep``) so the two cannot drift.
    """
    raw = path.read_bytes()
    return list(struct.unpack(f"<{len(raw) // 4}i", raw))


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prep", help="host: pack patches + prompt ids")
    p.add_argument("--img", required=True, type=Path)
    p.add_argument("--box", default=None, help="x1,y1,x2,y2; default: whole image")
    p.add_argument("--label", default=None, help="layout class, picks the prompt")
    p.add_argument("--prompt", default=None, help="override the instruction")
    p.add_argument("--stage", default=None, help="HxW, e.g. 168x672")
    p.add_argument("--tokenizer", required=True, type=Path,
                   help="the model's tokenizer.json")
    p.add_argument("--max-new", type=int, default=48)
    p.add_argument("--seq", type=int, default=2048)
    p.add_argument("--out", required=True, type=Path)
    p.set_defaults(fn=cmd_prep)

    r = sub.add_parser("reference", help="host: HF greedy decode on the same pixels")
    r.add_argument("--work", required=True, type=Path)
    r.add_argument("--model-dir", required=True)
    r.add_argument("--max-new", type=int, default=48)
    r.add_argument("--ctx", type=int, default=8,
                   help="how many positions get top-2 logit pricing")
    r.add_argument("--price-at", default=None,
                   help="comma-separated generated positions to price instead "
                        "of the first --ctx; use this on the positions where "
                        "the board diverged")
    r.add_argument("--smart-resize", action="store_true",
                   help="let the processor resize (measures the fixed-stage cost)")
    r.set_defaults(fn=cmd_reference)

    c = sub.add_parser("compare", help="host: align the two token sequences")
    c.add_argument("--work", required=True, type=Path)
    c.add_argument("--tokenizer", default=None, type=Path)
    c.add_argument("--smart-resize", action="store_true")
    c.set_defaults(fn=cmd_compare)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
