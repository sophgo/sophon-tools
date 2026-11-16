#!/usr/bin/env python3
"""Check why the HF embedding reference disagrees with every bmodel.

MYS-2702 measured all bmodels agreeing with each other at cosine >= 0.9995 while
every one of them disagrees with ``aux_hf_reference.py``'s vectors at 0.73-0.90.
One of the two sides is computing a different function, and the bmodels cannot
all be wrong in the same way while agreeing with each other, so the reference is
the suspect.

This probes the two differences that would explain it, on the same text:

1. **The final token.** Qwen3-Embedding pools the *last* token, and its
   tokenizer template appends ``<|endoftext|>``. ``AutoTokenizer(text)`` does not
   apply that template, so the reference pools a different position than the
   service does -- the service tokenises through the template.
2. **The instruction prefix.** The reference pipeline embeds a query as
   ``Instruct: ...\\nQuery: <text>`` and a document bare.

Prints, for one text: the cosine between each candidate reference vector and the
``plain`` one, so it is visible which choice moves the vector and by how much.

    docker exec embed_build python3 /workspace/diag_embed_ref.py
"""
import json

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

MODEL = "/workspace/tpuc/Qwen3-Embedding-0.6B"
INSTRUCTION = ("Instruct: Given a web search query, retrieve relevant passages "
               "that answer the query\nQuery: ")
TEXT = ("知识库的切片目标长度是四百字，重叠六十个字。切片按句子边界切分，"
        "因此相邻两片之间共享的是一句完整的话，而不是从中间截断的半句。")


def embed(tok, model, text, *, template=False, prepend=""):
    payload = prepend + text
    if template:
        # What a chat/instruct template does: ids plus the trailing special.
        ids = tok.apply_chat_template(
            [{"role": "user", "content": payload}], tokenize=True,
            add_generation_prompt=False)
        enc = {"input_ids": torch.tensor([ids])}
    else:
        enc = tok(payload, return_tensors="pt")
    with torch.no_grad():
        h = model(**enc).last_hidden_state
    v = h[0, -1, :].float().numpy()
    return v / np.linalg.norm(v), enc["input_ids"].shape[1]


def cos(a, b):
    return float(np.dot(a, b))


def main():
    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModel.from_pretrained(MODEL, dtype=torch.float32).eval()

    variants = {
        "plain": dict(),
        "plain+eos_token": dict(prepend=""),
        "instruct": dict(prepend=INSTRUCTION),
    }
    base, n = embed(tok, model, TEXT, **variants["plain"])
    print("plain: %d tokens, |v|=1" % n)

    # Explicitly append the EOS the service's template appends.
    eos = tok.eos_token or "<|endoftext|>"
    print("tokenizer eos_token:", tok.eos_token, "-> id", tok.convert_tokens_to_ids(eos))

    for name, kw in variants.items():
        if name == "plain":
            continue
        v, m = embed(tok, model, TEXT, **kw)
        print("%-16s %4d tokens  cos vs plain = %.7f" % (name, m, cos(base, v)))

    # The service appends the EOS; simulate exactly that by tokenising then
    # appending the id the tokenizer template would.
    ids = tok(TEXT)["input_ids"]
    id_eos = tok.convert_tokens_to_ids(eos)
    for label, seq in (("plain ids", ids), ("plain ids + eos", ids + [id_eos])):
        with torch.no_grad():
            h = model(input_ids=torch.tensor([seq])).last_hidden_state
        v = h[0, -1, :].float().numpy()
        v /= np.linalg.norm(v)
        print("%-18s %4d tokens  cos vs plain = %.7f" % (label, len(seq), cos(base, v)))


if __name__ == "__main__":
    main()
