"""CPU reference for the int4 AutoRound Qwen3.5/3.6-35B-A3B checkpoints.

Dequantises the GPTQ-packed weights to bf16, builds the HF text model and runs
greedy decoding on the same prompt the board probe uses, printing the top-5
next-token probabilities at every step -- so a board answer can be checked
against what the weights themselves predict.

    python3 hf_ref.py --hf /workspace/hf/Qwen3.6-35B-A3B-int4-AutoRound --reps 456 --steps 8
"""
import argparse
import json
import os
import re
import time

import torch
from safetensors import safe_open
from tokenizers import Tokenizer
from transformers import AutoConfig
from transformers.models.qwen3_5_moe.modeling_qwen3_5_moe import (
    Qwen3_5MoeForCausalLM, Qwen3_5MoeTextRotaryEmbedding)

FILLER = ("The archive room held shelves of ledgers, maps and letters, each catalogued by "
          "a clerk who wrote the date, the sender and a short summary on a card. ")


def render(user):
    return (f"<|im_start|>user\n{user}<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n\n</think>\n\n")


def unpack_cols(q):  # int32 [r, c] -> int4 [r, 8c] (low nibble first)
    sh = torch.arange(0, 32, 4, dtype=torch.int32)
    return ((q.unsqueeze(-1) >> sh) & 0xF).reshape(q.shape[0], -1)


def unpack_rows(q):  # int32 [r, c] -> int4 [8r, c]
    sh = torch.arange(0, 32, 4, dtype=torch.int32)
    return ((q.unsqueeze(1) >> sh.view(1, 8, 1)) & 0xF).reshape(-1, q.shape[1])


def dequant(qweight, qzeros, scales, zero_offset):
    w = unpack_rows(qweight)                       # [in, out]
    z = unpack_cols(qzeros) + zero_offset          # [groups, out]
    g = w.shape[0] // scales.shape[0]
    zf = z.repeat_interleave(g, 0).float()
    sf = scales.float().repeat_interleave(g, 0)
    return ((w.float() - zf) * sf).t().contiguous().to(torch.bfloat16)  # [out, in]


def load(hf):
    cfg = AutoConfig.from_pretrained(hf).text_config
    if hasattr(cfg, "quantization_config"):
        delattr(cfg, "quantization_config")
    idx = json.load(open(os.path.join(hf, "model.safetensors.index.json")))["weight_map"]
    files = {}

    def get(n):
        f = files.get(idx[n]) or files.setdefault(idx[n], safe_open(os.path.join(hf, idx[n]), "pt"))
        return f.get_tensor(n)

    # auto_gptq packing stores zero-1; sym int4 means the true zero is 8.
    probe = [n for n in idx if n.endswith(".qzeros")][0]
    zraw = unpack_cols(get(probe)).unique().tolist()
    zero_offset = 1 if zraw == [7] else 0
    print(f"qzeros raw values {zraw} -> offset {zero_offset}", flush=True)

    with torch.device("meta"):
        model = Qwen3_5MoeForCausalLM(cfg)
    want = dict(model.named_parameters())
    sd = {}
    prefix = "model.language_model."
    experts: dict = {}
    t0 = time.time()
    for n in idx:
        if not n.startswith(prefix) and not n.startswith("lm_head"):
            continue
        base = n[len(prefix):] if n.startswith(prefix) else n
        if n.endswith((".qzeros", ".scales")):
            continue
        if n.endswith(".qweight"):
            stem = n[: -len(".qweight")]
            w = dequant(get(n), get(stem + ".qzeros"), get(stem + ".scales"), zero_offset)
            key = base[: -len(".qweight")] + ".weight"
        else:
            w = get(n).to(torch.bfloat16) if get(n).is_floating_point() else get(n)
            key = base
        m = re.match(r"layers\.(\d+)\.mlp\.experts\.(\d+)\.(gate_proj|up_proj|down_proj)\.weight", key)
        if m:
            experts.setdefault(int(m.group(1)), {}).setdefault(m.group(3), {})[int(m.group(2))] = w
            continue
        k = ("model." + key) if not key.startswith("lm_head") else key
        sd[k] = w
    for li in sorted(experts):
        d = experts.pop(li)
        E = len(d["gate_proj"])
        gu = torch.stack([torch.cat([d["gate_proj"][e], d["up_proj"][e]], 0) for e in range(E)])
        dn = torch.stack([d["down_proj"][e] for e in range(E)])
        sd[f"model.layers.{li}.mlp.experts.gate_up_proj"] = gu
        sd[f"model.layers.{li}.mlp.experts.down_proj"] = dn
        del d, gu, dn
    missing = [k for k in want if k not in sd]
    extra = [k for k in sd if k not in want]
    print(f"converted in {time.time() - t0:.0f}s; missing={missing[:8]} ({len(missing)}) "
          f"extra={extra[:8]} ({len(extra)})", flush=True)
    for k in missing:
        if k.endswith("lm_head.weight") and "model.embed_tokens.weight" in sd:
            sd[k] = sd["model.embed_tokens.weight"]
    for k, p in want.items():
        if sd[k].shape != p.shape:
            raise SystemExit(f"shape mismatch {k}: {tuple(sd[k].shape)} vs {tuple(p.shape)}")
    model.load_state_dict(sd, strict=False, assign=True)
    # Non-persistent buffers stay on the meta device: build the rotary table for real.
    model.model.rotary_emb = Qwen3_5MoeTextRotaryEmbedding(cfg)
    left = [n for n, b in model.named_buffers() if b.is_meta] + \
           [n for n, p in model.named_parameters() if p.is_meta]
    if left:
        raise SystemExit(f"still on meta: {left[:5]}")
    model.eval()
    return model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf", required=True)
    ap.add_argument("--reps", default="456")
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--threads", type=int, default=16)
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    tok = Tokenizer.from_file(os.path.join(a.hf, "tokenizer.json"))
    model = load(a.hf)
    for reps in [int(x) for x in a.reps.split(",")]:
        ids = tok.encode(render(FILLER * reps + "\nRepeat the word archive forever."),
                         add_special_tokens=False).ids
        t0 = time.time()
        with torch.no_grad():
            out = model(input_ids=torch.tensor([ids]), use_cache=True, logits_to_keep=1)
            print(f"reps={reps} prompt={len(ids)} prefill {time.time() - t0:.0f}s", flush=True)
            cache = out.past_key_values
            logits = out.logits[0, -1].float()
            gen = []
            for step in range(a.steps):
                p = logits.softmax(-1)
                top = p.topk(5)
                nxt = int(top.indices[0])
                desc = ", ".join(f"{tok.decode([int(i)])!r}:{float(v):.3f}"
                                 for v, i in zip(top.values, top.indices))
                print(f"  step {step}: {desc}", flush=True)
                gen.append(nxt)
                if nxt in (tok.token_to_id("<|im_end|>"), tok.token_to_id("<|endoftext|>")):
                    break
                out = model(input_ids=torch.tensor([[nxt]]), past_key_values=cache, use_cache=True)
                cache = out.past_key_values
                logits = out.logits[0, -1].float()
            print(f"  greedy: {tok.decode(gen)!r}", flush=True)


if __name__ == "__main__":
    main()
