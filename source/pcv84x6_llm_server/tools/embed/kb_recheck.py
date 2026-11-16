#!/usr/bin/env python3
"""Does an existing knowledge base still retrieve the same chunks after the swap?

P1's premise is that the vectors do not change, so a library built with the
seq8192 bmodel needs no rebuild. ``cmp_models.py`` shows the vectors are equal to
0.9996 cosine on a synthetic corpus; this checks the claim that actually matters
to a user -- that asking the same question returns the same **chunks**, in the
same order.

The comparison is done against a library's stored ``vectors.npy`` and
``chunks.jsonl``: the query is embedded once with the old bmodel and once with
the new one, and both are scored the same way the search path scores them
(cosine over the stored matrix). Anything else would be testing the ranking code
twice rather than the model swap.

    python3 kb_recheck.py --lib lib/libcv84x6_llm.so \\
        --config model-config/qwen3_embedding \\
        --old old.bmodel --new new.bmodel \\
        --library /data/.../apps/kb/<id> --top 3

Exits non-zero if any query's top-N differs between the two models.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from cmp_models import Lib, cosine  # noqa: E402  (same directory, same harness)

#: The retrieval instruction, character for character (docs/aux-models.md: a
#: single changed word moves the reference similarities out of tolerance).
INSTRUCTION = ("Instruct: Given a web search query, retrieve relevant passages "
               "that answer the query\nQuery: ")

#: Questions a user would actually type at this library's two demo documents.
#: Mixing a question that is *in* the material with one that is not is
#: deliberate: the second shows the two models agree about irrelevance too.
QUERIES = [
    "这段文档讲了什么？",
    "向量检索的候选数量怎么定？",
    "如何避免切片切断句子？",
    "what does the document say about chunk overlap?",
    "设备内存上限是怎么算出来的？",
    "今天的天气怎么样？",
]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lib", required=True)
    ap.add_argument("--config", required=True, help="tokenizer dir")
    ap.add_argument("--old", required=True, help="seq8192 bmodel")
    ap.add_argument("--new", required=True, help="seq2048 bmodel")
    ap.add_argument("--library", required=True,
                    help="knowledge-base directory holding vectors.npy + chunks.jsonl")
    ap.add_argument("--top", type=int, default=3)
    args = ap.parse_args(argv[1:])

    lib = Lib(args.lib)
    tok = lib.open_tokenizer(str(Path(args.config) / "tokenizer.json"))
    matrix = np.load(Path(args.library) / "vectors.npy")
    chunks = [json.loads(line) for line in
              (Path(args.library) / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip()]
    assert matrix.shape[0] == len(chunks), (
        f"the matrix has {matrix.shape[0]} rows and there are {len(chunks)} chunks")
    # The stored vectors are L2-normalised (the engine normalises before
    # returning), so a dot product is the cosine -- the same arithmetic the
    # search path does.
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = matrix / np.maximum(norms, 1e-12)
    print(f"== library: {len(chunks)} chunks, dims {matrix.shape[1]}")

    old_h, old_seq, old_hidden = lib.open_model(args.old)
    new_h, new_seq, new_hidden = lib.open_model(args.new)
    print(f"== old seq={old_seq}, new seq={new_seq}")

    failures = 0
    for query in QUERIES:
        ids = lib.encode(tok, INSTRUCTION + query)
        if len(ids) > min(old_seq, new_seq):
            print(f"  {query!r}: {len(ids)} tokens, skipped (over both models)")
            continue
        vec_old = lib.forward(old_h, ids, old_hidden)
        vec_new = lib.forward(new_h, ids, new_hidden)
        q_old = np.array(vec_old, dtype=np.float32)
        q_new = np.array(vec_new, dtype=np.float32)
        q_old /= np.linalg.norm(q_old)
        q_new /= np.linalg.norm(q_new)

        order_old = np.argsort(-(matrix @ q_old))[:args.top]
        order_new = np.argsort(-(matrix @ q_new))[:args.top]
        same = list(order_old) == list(order_new)
        if not same:
            failures += 1
        cos_q = cosine(vec_old, vec_new)
        print(f"  {'OK  ' if same else 'DIFF'} query-cosine={cos_q:.7f}  {query}")
        # Document-prefix + row index: the ids alone repeat across chunks of one
        # document, which makes the output look identical when it is not.
        print(f"       old top{args.top}: {[(chunks[i]['id'][:8], i) for i in order_old]}")
        if not same:
            print(f"       new top{args.top}: {[(chunks[i]['id'][:8], i) for i in order_new]}")

    print(f"\n== {len(QUERIES) - failures}/{len(QUERIES)} queries returned the same "
          f"top-{args.top} chunks")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
