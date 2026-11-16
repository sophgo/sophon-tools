#!/usr/bin/env python3
"""The HF reference for the two auxiliary text models, as a re-runnable dump.

``aux_seq_sweep.py`` measures the bmodels against *each other*: it says whether
a dynamic build reproduces a static one, which answers "did the recompile change
the vector" but not "is either build right". This tool produces the independent
answer -- the same texts through the original PyTorch checkpoints -- as a JSON
file the board-side comparison reads.

Runs in the build container (it needs torch + transformers); the board has
neither, and should not: the point is an out-of-band reference.

    docker exec embed_build python3 /workspace/aux_hf_reference.py \\
        --kind embed --model /workspace/tpuc/Qwen3-Embedding-0.6B \\
        --config /workspace/tpuc/Qwen3-Embedding-0.6B --json /workspace/hf_embed.json

The texts are exactly the ones ``aux_seq_sweep.py`` synthesises (its ``FILLER``
list and ``text_at_tokens``), imported from that file rather than copied, so the
two sides cannot drift apart.

Two details that make the comparison meaningful:

* **Embedding pools the last token**, not the CLS token, and normalises -- that
  is what the service does (``native/src/embed_engine.cpp`` reads row ``n-1``),
  and Qwen3-Embedding is trained for it. A CLS-pooled reference would be a
  different model.
* **Rerank uses right padding with XLM-R position ids** (padding -> pad id,
  real tokens counting from ``pad_id + 1``), which is the reference pipeline's
  rule and the one the service reproduces. HF's own default would give every
  pad position the same id and shift nothing, so the ids are built here.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys

import numpy as np
import torch


def load_sweep_module(path: str):
    """Import ``aux_seq_sweep.py`` for its corpus, without running it."""
    spec = importlib.util.spec_from_file_location("aux_seq_sweep", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def embed_reference(model_dir: str, sweep, grid) -> dict:
    from transformers import AutoModel, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    model = AutoModel.from_pretrained(model_dir, trust_remote_code=True,
                                     dtype=torch.float32)
    model.eval()

    out = {"kind": "embed", "model": model_dir, "lens": {}}
    for want in grid:
        text, _got = sweep.text_at_tokens(
            lambda t: len(tok(t)["input_ids"]), want, seed=want, cap=want)
        enc = tok(text, return_tensors="pt", truncation=False)
        with torch.no_grad():
            hidden = model(**enc).last_hidden_state
        # Last-token pooling. `tokenizer.json`'s post-processor appends
        # <|endoftext|>, so the last row *is* that token -- and it is the one the
        # service pools too (`aux_tok._truncate` keeps the trailing special).
        vec = hidden[0, -1, :].float().numpy()
        norm = float(np.linalg.norm(vec))
        vec = vec / norm if norm else vec
        out["lens"][want] = {
            "tokens": int(enc["input_ids"].shape[1]),
            # The exact text is stored, not just its length. The board side must
            # embed THIS text: it sizes its own text with a different tokenizer
            # (the service's C++ one), so re-deriving from the token count lands
            # on a different string and the two cosine columns would compare
            # different documents.
            "text": text,
            "vector": vec.tolist(),
        }
        print("embed %5d tokens: |v|=%.4f" % (out["lens"][want]["tokens"], norm))
    return out


def rerank_reference(model_dir: str, sweep, grid, query: str | None) -> dict:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_dir, dtype=torch.float32)
    model.eval()
    pad_id = tok.pad_token_id

    query = query or sweep.FILLER[0][:60]
    query_tokens = len(tok(query)["input_ids"])
    out = {"kind": "rerank", "model": model_dir,
           "query": query, "query_tokens": query_tokens, "lens": {}}
    for want in grid:
        # The grid is a pair length; grow the document until the encoded pair
        # reaches it, exactly as aux_seq_sweep.py does.
        doc, _ = sweep.text_at_tokens(
            lambda t: query_tokens + len(tok(t)["input_ids"]) + 3, want,
            seed=want + 1, cap=max(grid))
        # `doc` is stored below so the board compares the same string.
        enc = tok(query, doc, return_tensors="pt", truncation=False)
        ids = enc["input_ids"][0]
        real = int(ids.shape[0])
        if real > max(grid):
            out["lens"][want] = {"pair_tokens": real, "real_len": real,
                                 "logit": None}
            continue
        # XLM-R position ids: pad -> pad_id, everything else a counter from
        # pad_id + 1. HF would otherwise reuse the pad id for padding.
        pos = []
        nxt = pad_id + 1
        for token in ids.tolist():
            if token == pad_id:
                pos.append(pad_id)
            else:
                pos.append(nxt)
                nxt += 1
        with torch.no_grad():
            logits = model(input_ids=enc["input_ids"],
                           attention_mask=enc["attention_mask"],
                           position_ids=torch.tensor([pos])).logits
        logit = float(logits[0, 0])
        out["lens"][want] = {"pair_tokens": real, "real_len": real,
                             "doc": doc, "logit": round(logit, 6)}
        print("rerank pair %5d tokens: logit %.4f" % (real, logit))
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", choices=("embed", "rerank"), required=True)
    ap.add_argument("--model", required=True, help="the HF checkpoint directory")
    ap.add_argument("--sweep", required=True, help="path to aux_seq_sweep.py")
    ap.add_argument("--grid", default="64,256,512,1024,2048,4096,8192")
    ap.add_argument("--query", help="rerank only: override the paired query")
    ap.add_argument("--json", required=True)
    args = ap.parse_args(argv[1:])

    sweep = load_sweep_module(args.sweep)
    grid = [int(x) for x in args.grid.split(",")]
    torch.set_grad_enabled(False)

    result = (embed_reference(args.model, sweep, grid) if args.kind == "embed"
              else rerank_reference(args.model, sweep, grid, args.query))
    with open(args.json, "w") as f:
        json.dump(result, f, ensure_ascii=False)
    print("== wrote", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
