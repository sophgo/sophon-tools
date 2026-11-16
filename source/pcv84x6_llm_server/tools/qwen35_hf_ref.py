#!/usr/bin/env python3
"""x86 HF reference for the dense Qwen3.5 9B / 4B builds (MYS-2754).

Generates greedy continuations from the *original* checkpoint on CPU, so a board
answer can be compared token by token. This is the ground truth the issue's
precision table is measured against; without it "the board answered something
plausible" is the only available claim.

Two checkpoints, deliberately:
  * ``--hf`` pointing at the bf16 release is the reference for the **bf16**
    board build. It is the same floats the board build was compiled from, so an
    agreement below 100% is an engine/compiler defect, not a quantisation cost.
  * ``--hf`` pointing at the AutoRound int4 release is the reference for the
    **w4** board build, after dequantising the GPTQ-packed weights to bf16. The
    two references then differ from each other by exactly the quantisation, and
    the board's w4 build is compared against the dequantised checkpoint its
    weights actually came from.

Greedy only (``do_sample=False`` / argmax), fixed 128 tokens, one prompt per
line of ``--prompts``. Image prompts are skipped here: the vit reference for a
board image is a property of the vision tower's compile, and comparing a text
continuation off a vit-spliced prompt would attribute a vision difference to the
text model. ``--image`` handles that case separately by reporting the first
tokens only, which is what "did the image reach the model" is answerable as.

    python3 tools/qwen35_hf_ref.py --hf <ckpt> --prompts tools/qwen35_prompts.json \\
        --out ref.json --steps 128

Runs where torch can (the tpu-mlir container has 5.6.2, which has qwen3_5); the
board cannot, which is the point.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

import torch
from safetensors import safe_open
from tokenizers import Tokenizer
from transformers import AutoConfig, AutoProcessor

FILLER = ("The archive room held shelves of ledgers, maps and letters, each "
          "catalogued by a clerk who wrote the date, the sender and a short "
          "summary on a card. ")


def render(user: str) -> str:
    """The chat template the service sends, in its plain-text form.

    ``<think>`` is empty because greedy comparison is about the answer; a model
    that reasons first would spend all 128 tokens thinking and the comparison
    would cover less of the generation.
    """
    return (f"<|im_start|>user\n{user}<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n\n</think>\n\n")


def unpack_cols(q):
    sh = torch.arange(0, 32, 4, dtype=torch.int32)
    return ((q.unsqueeze(-1) >> sh) & 0xF).reshape(q.shape[0], -1)


def unpack_rows(q):
    sh = torch.arange(0, 32, 4, dtype=torch.int32)
    return ((q.unsqueeze(1) >> sh.view(1, 8, 1)) & 0xF).reshape(-1, q.shape[1])


def dequant(qweight, qzeros, scales, zero_offset):
    w = unpack_rows(qweight)
    z = unpack_cols(qzeros) + zero_offset
    g = w.shape[0] // scales.shape[0]
    zf = z.repeat_interleave(g, 0).float()
    sf = scales.float().repeat_interleave(g, 0)
    return ((w.float() - zf) * sf).t().contiguous().to(torch.bfloat16)


def load(hf: str):
    """The HF model, with int4 weights dequantised when the checkpoint has them.

    ``init_empty_weights``-style building would be better but the meta-device
    dance in ``tools/precision/hf_ref.py`` depends on the MoE class layout; the
    dense model loads normally with enough RAM (9B bf16 is 19 GB, this box has
    250 GB), and loading normally removes a whole class of "still on meta"
    failure.
    """
    from transformers import Qwen3_5ForConditionalGeneration

    cfg = AutoConfig.from_pretrained(hf)
    if hasattr(cfg, "quantization_config"):
        delattr(cfg, "quantization_config")
    if hasattr(cfg, "text_config") and hasattr(cfg.text_config, "quantization_config"):
        delattr(cfg.text_config, "quantization_config")

    idx_path = os.path.join(hf, "model.safetensors.index.json")
    quantized = False
    if os.path.exists(idx_path):
        idx = json.load(open(idx_path))["weight_map"]
        quantized = any(k.endswith(".qweight") for k in idx)
    else:
        idx = None

    if not quantized:
        # A plain bf16 checkpoint: let transformers do the work.
        model = Qwen3_5ForConditionalGeneration.from_pretrained(
            hf, dtype=torch.bfloat16, low_cpu_mem_usage=True)
        model.eval()
        return model

    # int4 AutoRound: dequantise every packed linear to bf16 and load that. The
    # prefix differs from the MoE checkpoint's, so the mapping is built from the
    # model's own parameter names rather than assumed.
    files = {}

    def get(n):
        f = files.get(idx[n]) or files.setdefault(
            idx[n], safe_open(os.path.join(hf, idx[n]), "pt"))
        return f.get_tensor(n)

    probe = next(n for n in idx if n.endswith(".qzeros"))
    zraw = unpack_cols(get(probe)).unique().tolist()
    zero_offset = 1 if zraw == [7] else 0
    print(f"qzeros raw {zraw} -> offset {zero_offset}", flush=True)

    with torch.device("meta"):
        model = Qwen3_5ForConditionalGeneration(cfg)
    want = dict(model.named_parameters())
    sd = {}
    for n in idx:
        if n.endswith((".qzeros", ".scales")):
            continue
        if n.endswith(".qweight"):
            stem = n[: -len(".qweight")]
            w = dequant(get(n), get(stem + ".qzeros"), get(stem + ".scales"),
                        zero_offset)
            key = stem + ".weight"
        else:
            t = get(n)
            w = t.to(torch.bfloat16) if t.is_floating_point() else t
            key = n
        if key in want:
            sd[key] = w
    # ``tie_word_embeddings: true`` (the 4B; the 9B is false) means the
    # checkpoint ships no lm_head tensor at all -- the two module attributes are
    # THE SAME tensor object. Feeding a separate ``lm_head.weight`` into
    # ``load_state_dict`` therefore detaches the tie and leaves the real
    # parameter on meta; the fix is to let the embedding table fill both, which
    # is why lm_head is dropped from the expected set here.
    tied = bool(getattr(model.config, "tie_word_embeddings", False))
    if tied:
        # Drop it BEFORE the completeness check: for a tied model it is not a
        # missing weight, it is the embedding table under a second name.
        sd.pop("lm_head.weight", None)
    missing = [k for k in want if k not in sd]
    if tied and "lm_head.weight" in missing:
        missing.remove("lm_head.weight")
    if missing:
        raise SystemExit(f"unmapped parameters ({len(missing)}): {missing[:6]}")
    for k, prm in want.items():
        if k in sd and sd[k].shape != prm.shape:
            raise SystemExit(f"shape mismatch {k}: {tuple(sd[k].shape)} vs {tuple(prm.shape)}")
    model.load_state_dict(sd, strict=False, assign=True)
    if tied and hasattr(model, "lm_head"):
        # Re-tie explicitly: ``assign=True`` replaces tensors rather than copying
        # into them, so the sharing the constructor set up is lost by then.
        embed = model.model.language_model.embed_tokens.weight
        model.lm_head.weight = embed

    # The rotary modules are built with ``torch.device("meta")`` above and their
    # ``inv_freq`` buffers are non-persistent, so ``load_state_dict`` never
    # fills them -- every forward then fails on a meta tensor. Rebuilding those
    # two modules outside the meta context is what makes them real; they have no
    # learned weights, only a frequency table derived from the config.
    from transformers.models.qwen3_5.modeling_qwen3_5 import (
        Qwen3_5TextRotaryEmbedding, Qwen3_5VisionRotaryEmbedding)

    text_cfg = model.config.text_config
    model.model.language_model.rotary_emb = Qwen3_5TextRotaryEmbedding(
        text_cfg, device="cpu")
    # The vision rotary DOES hold an ``inv_freq`` buffer (dim, theta) -> a table
    # derived from the config, so it has to be rebuilt too. Its ``dim`` is half
    # the vision head dimension: the table is built as
    # ``arange(0, dim, 2)`` over the rotary dimension, and the rotary dimension
    # is head_dim/2 for this model family (head_dim 64 -> dim 32 -> 16 entries).
    vision_cfg = getattr(model.config, "vision_config", None)
    if vision_cfg is not None and hasattr(model.model, "visual"):
        head_dim = vision_cfg.hidden_size // vision_cfg.num_heads
        model.model.visual.rotary_pos_emb = Qwen3_5VisionRotaryEmbedding(
            head_dim // 2)

    left = [n for n, b in model.named_buffers() if b.is_meta] + \
           [n for n, prm in model.named_parameters() if prm.is_meta]
    if left:
        raise SystemExit(f"still on meta: {left[:5]}")
    model.eval()
    return model


def greedy(model, ids, steps: int) -> list[int]:
    out_ids = []
    with torch.no_grad():
        out = model(input_ids=torch.tensor([ids]), use_cache=True)
        past = out.past_key_values
        tok = int(out.logits[0, -1].argmax())
        out_ids.append(tok)
        for _ in range(steps - 1):
            out = model(input_ids=torch.tensor([[tok]]), past_key_values=past,
                        use_cache=True)
            past = out.past_key_values
            tok = int(out.logits[0, -1].argmax())
            out_ids.append(tok)
            if tok == model.config.text_config.eos_token_id:
                break
    return out_ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf", required=True)
    ap.add_argument("--prompts", required=True, help="JSON: [{id, text, image?}]")
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=128)
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--image", default="", help="run one image prompt instead")
    a = ap.parse_args()

    torch.set_num_threads(a.threads)
    tok = Tokenizer.from_file(os.path.join(a.hf, "tokenizer.json"))
    t0 = time.time()
    model = load(a.hf)
    print(f"model loaded in {time.time() - t0:.0f}s", flush=True)

    cases = json.load(open(a.prompts))
    results = []
    for case in cases:
        if case.get("image") and not a.image:
            # Text reference only; the image case is generated separately so a
            # vit difference cannot be read as a text-model difference.
            continue
        text = case["text"]
        if a.image:
            # Replace the bare image marker with the chat template's vision
            # block, which is what the processor expands.
            text = text.replace("<image>", "<|vision_start|><|image_pad|><|vision_end|>")
        ids = tok.encode(render(text), add_special_tokens=False).ids
        t0 = time.time()
        gen = greedy(model, ids, a.steps)
        results.append({
            "id": case["id"],
            "prompt_tokens": len(ids),
            "prompt_ids": ids,
            "tokens": gen,
            "text": tok.decode(gen),
            "seconds": round(time.time() - t0, 1),
            "image": bool(case.get("image")),
        })
        print(f"{case['id']}: {len(ids)} prompt tokens, {len(gen)} generated "
              f"in {time.time() - t0:.0f}s", flush=True)

    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump({"hf": a.hf, "steps": a.steps, "cases": results}, fh,
                  ensure_ascii=False, indent=1)
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
