#!/usr/bin/env python3
"""MYS-2913: is one encoder call reproducible, and does a sync change that?

Issues the *same* input N times through one encoder handle and reports, for
every pair of results, the max absolute difference and the cosine similarity.
Two calls whose vectors differ are a defect on their own -- an embedding that
changes between identical requests cannot be indexed consistently.

``--sync`` inserts a ``bm_thread_sync`` (via the C API's fault probe, which does
not, so instead we use a dedicated no-op forward gate) ... see below: the sync
variant is exercised by comparing against the instrumented library, whose
per-stage readbacks imply a device sync. This script only measures the shipped
library.

Usage::

    python3 tools/vl_embed/repeat_compare.py --library ... --config ... --model ... \\
        --calls 6 --text "hello world"
    python3 tools/vl_embed/repeat_compare.py ... --image 384x512
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repeat_probe import Encoder, make_png, _size  # noqa: E402


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else float("nan")


def max_abs(a, b) -> float:
    return max(abs(x - y) for x, y in zip(a, b))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--library", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--calls", type=int, default=6)
    p.add_argument("--text", default="A photograph of a meal on a wooden table.")
    p.add_argument("--long-text-repeats", type=int, default=0,
                   help="repeat --text this many times to select a larger bucket")
    p.add_argument("--image", help="HxW pixels, e.g. 384x512; omit for text only")
    p.add_argument("--dimensions", type=int, default=None)
    p.add_argument("--output")
    a = p.parse_args()

    text = (" ".join([a.text] * a.long_text_repeats) if a.long_text_repeats else a.text)
    png = None
    if a.image:
        h, w = _size(a.image)
        png = make_png(h, w, 20261116)

    enc = Encoder(a.library, a.model, a.config)
    vectors, records = [], []
    try:
        for index in range(a.calls):
            rec = enc.encode(text=text, png=png, dimensions=a.dimensions, keep_vector=True)
            rec["index"] = index
            records.append({k: v for k, v in rec.items() if k != "vec"})
            vectors.append(rec.get("vec"))
    finally:
        enc.close()

    pairs = []
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            vi, vj = vectors[i], vectors[j]
            if vi is None or vj is None:
                pairs.append({"i": i, "j": j, "comparable": False})
                continue
            pairs.append({"i": i, "j": j, "comparable": True,
                          "cosine": round(cosine(vi, vj), 9),
                          "max_abs": round(max_abs(vi, vj), 9)})
    comparable = [x for x in pairs if x["comparable"]]
    report = {
        "input": {"text_chars": len(text), "image": a.image},
        "tokens": records[0].get("tokens") if records else None,
        "bucket": records[0].get("bucket") if records else None,
        "calls": records,
        "pairs": pairs,
        "worst_cosine": min((x["cosine"] for x in comparable), default=None),
        "worst_max_abs": max((x["max_abs"] for x in comparable), default=None),
        "distinct_vectors": len({r.get("vecsha") for r in records if r.get("vecsha")}),
    }
    if a.output:
        Path(a.output).write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "pairs"}, ensure_ascii=False),
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
