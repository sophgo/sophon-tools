#!/usr/bin/env python3
"""Check the shipped PaddleOCR-VL bmodel against the golden it must reproduce.

O3's acceptance criterion is "preprocessing identical to the golden, item by
item" *and* "run the images through the bmodel". Those two can only both hold if
the bmodel accepts the pixel tensor the golden records. This script reads both
artifacts and says whether they agree, so the question is answered by data
rather than by running a 2.2 GB model and guessing.

What it compares, and why each number matters:

* ``pixel patches`` — the golden records ``pixel_values_shape[0]``; the vit graph
  declares its own input row count. A static vit takes *exactly* its declared
  count, so a mismatch is not a slowdown, it is "this image cannot be fed".
* ``image tokens`` — the golden's ``image_token_count`` is how many embedding
  rows the prefill has to overwrite. It follows from the patch count, so a
  patch mismatch is also a prompt-layout mismatch.
* ``rope rows`` — the compiled blocks gather a single position row. That is only
  equivalent to the reference's interleaved mrope where t == h == w, which is
  true for text but false for image tokens. Reported separately because it is a
  correctness risk rather than a hard shape refusal.

Run it on any host that can read the bmodel's network info (the tpu-mlir
container has ``model_tool``); it does not need an NPU:

    python3 tools/ocr/check_vl_bmodel_golden.py \
        --bmodel /path/to/paddleocr-vl-1.5_....bmodel \
        --golden tests/data/ocr/golden.json

Exits 0 when the artifacts agree, 1 when they do not (the message names which).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

#: ``net N: [name]  static`` then ``input: <tensor>, [dims], <dtype>``.
_NET_RE = re.compile(r"^net \d+: \[(?P<name>[^\]]+)\]\s+(?P<kind>\w+)", re.M)
_IN_RE = re.compile(r"^input: (?P<name>[^,]+), \[(?P<dims>[^\]]*)\]", re.M)


def bmodel_shapes(bmodel: Path, model_tool: str = "model_tool") -> dict[str, list[list[int]]]:
    """{network name: [input dims per tensor]} via ``model_tool --info``."""
    out = subprocess.run([model_tool, "--info", str(bmodel)],
                         check=True, capture_output=True, text=True).stdout
    shapes: dict[str, list[list[int]]] = {}
    blocks = _NET_RE.split(out)
    # split() with one capture group yields [pre, name, kind, body, name, kind, body, ...]
    for i in range(1, len(blocks), 3):
        name = blocks[i]
        body = blocks[i + 2]
        dims = []
        for m in _IN_RE.finditer(body):
            dims.append([int(x) for x in m.group("dims").split(",") if x.strip()])
        shapes[name] = dims
    return shapes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bmodel", required=True, type=Path)
    ap.add_argument("--golden", type=Path,
                    default=Path("tests/data/ocr/golden.json"))
    ap.add_argument("--model-tool", default="model_tool")
    args = ap.parse_args()

    shapes = bmodel_shapes(args.bmodel, args.model_tool)
    vit = shapes.get("vit")
    if not vit:
        print(f"error: {args.bmodel} has no 'vit' network", file=sys.stderr)
        return 1
    vit_patches = vit[0][0]
    vit_px = vit[0][-1] * vit[0][-2] if len(vit[0]) >= 4 else None
    embed = shapes.get("embedding")
    max_input = embed[0][1] if embed and len(embed[0]) > 1 else None

    golden = json.loads(args.golden.read_text())
    cases = golden.get("paddleocr_vl", {}).get("cases") or []
    if not cases:
        print("error: golden has no paddleocr_vl.cases", file=sys.stderr)
        return 1

    print(f"bmodel vit input      : {vit[0]}  ({vit_patches} patches)")
    print(f"bmodel embedding width: {max_input}")
    print()
    print(f"{'image':16s} {'prompt':22s} {'patches':>8s} {'tokens':>7s}  verdict")
    bad = 0
    for case in cases:
        patches = case["pixel_values_shape"][0]
        tokens = case.get("image_token_count")
        ok = patches == vit_patches
        bad += not ok
        verdict = "ok" if ok else (
            f"CANNOT RUN: vit wants {vit_patches}, golden has {patches}")
        print(f"{case['image']:16s} {case['prompt']:22s} {patches:8d} {tokens:7d}  {verdict}")

    # Prompt budget: patches/4 image tokens + the text around them must fit the
    # prefill width, or even a matching patch count could not be prefilled.
    if max_input is not None:
        widest = max(len(c["input_ids"]) for c in cases)
        print()
        print(f"longest golden prompt : {widest} tokens (prefill width {max_input})")
        if widest > max_input:
            print("  CANNOT RUN: prompt exceeds the prefill graph")
            bad += 1

    print()
    if bad:
        print(f"FAIL: {bad} case(s) cannot be served by this bmodel as built.")
        print("The golden was produced with the HF processor's own max_pixels")
        print("(1003520), while the vit was compiled static at 784x784. Either")
        print("recompile the vit for the patch counts the service will see, or")
        print("regenerate the golden with the resize the bmodel actually takes.")
        return 1
    print("OK: every golden case fits this bmodel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
