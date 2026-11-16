#!/usr/bin/env python3
"""Compare a board-side sweep against the HF reference, on the host.

``aux_hf_reference.py`` produces the independent answer (what PyTorch says) for
the texts both sweeps synthesise; ``aux_seq_sweep.py`` produces the board answer
and stores only latencies in its JSON. This tool closes the loop: it re-derives
the same texts' *vectors* from the board's builds and reports both comparisons
the issue asks for --

    bmodel vs HF   -- is the compiled graph right at all?
    bmodel vs bmodel -- did the recompile change anything? (the sweep's own
                        ``cosine`` column already covers this)

Runs on the board (it needs ``libcv84x6_llm.so``), reading the HF JSON copied
over from the build container.

    python3 aux_vs_hf.py --lib /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \\
        --kind embed --config /opt/sophgo/cv84x6_llm_server/model-config/qwen3_embedding \\
        --hf /data/mys2702/hf_embed.json \\
        --model static={{…seq2048….bmodel}} --model dyn={{…dynamic….bmodel}}

The rerank side takes a logit from each build and reports the absolute
difference, because a reranker's output is a score, not a direction: a cosine
would be meaningless on a 1-element vector.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import aux_seq_sweep as sweep_mod


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else float("nan")


def compare_embed(lib, args, models, hf) -> int:
    tok = lib.open_tokenizer(os.path.join(args.config, "tokenizer.json"))
    worst = {}
    for name, path in models:
        h, seq, hidden = lib.open_embed(path)
        print("== %s  seq=%d" % (name, seq))
        for key, ref in hf["lens"].items():
            # The stored text, not one re-derived from the token count: the two
            # sides size their texts with different tokenizers (HF vs the
            # service's C++ one), so re-deriving lands on a different string and
            # the cosine would compare different documents (~0.73 for the same
            # subject, which looks like a precision bug and is not one).
            text = ref["text"]
            got = len(lib.encode(tok, text))
            if got > seq:
                print("   %5d tok  n/a (build is seq%d)" % (got, seq))
                continue
            vec = lib.embed(h, lib.encode(tok, text), hidden)
            cos = cosine(ref["vector"], vec)
            worst[name] = min(worst.get(name, 1.0), cos)
            print("   %5d tok  cos vs HF %.7f" % (got, cos))
        lib.lib.cv_embed_destroy(h)

    print("\n== worst cosine vs HF (bar 0.999):")
    bad = 0
    for name, cos in worst.items():
        ok = cos >= 0.999
        bad += 0 if ok else 1
        print("   %-14s %.7f  %s" % (name, cos, "PASS" if ok else "FAIL"))
    return 0 if bad == 0 else 1


def compare_rerank(lib, args, models, hf) -> int:
    hf_tok = sweep_mod.HFTokenizer(args.config)
    worst = {}
    for name, path in models:
        h, seq, _hidden = lib.open_rerank(path)
        print("== %s  seq=%d" % (name, seq))
        for key, ref in hf["lens"].items():
            if ref.get("logit") is None:
                continue
            # The stored document, for the same reason as in compare_embed: the
            # two sides size their texts with different tokenizers.
            ids, mask, pos, real = hf_tok.encode_pair(hf["query"], ref["doc"], seq)
            if real > seq:
                print("   pair %5d tok  n/a (build is seq%d)" % (real, seq))
                continue
            logit = lib.rerank(h, ids, pos, mask)
            delta = abs(logit - ref["logit"])
            worst[name] = max(worst.get(name, 0.0), delta)
            print("   pair %5d tok  bmodel %8.4f  HF %8.4f  |Δ| %.4f" % (
                real, logit, ref["logit"], delta))
        lib.lib.cv_rerank_destroy(h)

    print("\n== worst |Δlogit| vs HF:")
    for name, delta in worst.items():
        print("   %-14s %.4f" % (name, delta))
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lib", required=True)
    ap.add_argument("--kind", choices=("embed", "rerank"), required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--hf", required=True, help="the aux_hf_reference.py JSON")
    ap.add_argument("--model", action="append", required=True, metavar="NAME=PATH")
    args = ap.parse_args(argv[1:])

    models = [tuple(s.split("=", 1)) for s in args.model]
    with open(args.hf) as f:
        hf = json.load(f)

    lib = sweep_mod.Lib(args.lib)
    if args.kind == "embed":
        return compare_embed(lib, args, models, hf)
    return compare_rerank(lib, args, models, hf)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
