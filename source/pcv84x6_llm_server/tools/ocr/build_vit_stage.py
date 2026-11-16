#!/usr/bin/env python3
"""Build one vit stage of PaddleOCR-VL-1.5, reusing the LLM build's weights.

Stage A of MYS-2591 has to answer "can several vision-tower shapes share one set
of weights, so the stage set does not multiply the bmodel's size". The honest
way to answer it is to build two stages and compare what the compiler emits:
``model_tool --weight`` reports each network's weight bytes, and two stages with
the same weight size is evidence. "It should share" is not.

The converter's positional-embedding interpolation is what makes the shape
matter at all -- it is baked as a constant scale from ``max_shape`` to the
27x27 source grid -- so each stage is a separate ``llm_convert`` invocation with
its own ``--max_pixels``. The LLM blocks/embedding are byte-identical across
invocations; only the vit's geometry changes.

    python3 tools/ocr/build_vit_stage.py <weights-dir> <h> <w> <out-dir>

``h``/``w`` are resized image pixels, multiples of 28 (patch 14 x merge 2);
``vl_stages.py`` is the table those come from.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paddleocr_vl_convert as shim  # noqa: E402  (applies the patches on import)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("weights", type=Path)
    ap.add_argument("height", type=int)
    ap.add_argument("width", type=int)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--seq", type=int, default=2048)
    ap.add_argument("--num-core", type=int, default=4)
    ap.add_argument("--chip", default="bm1684x2")
    ap.add_argument("--only-mlir", action="store_true")
    args = ap.parse_args()

    patches = (args.height // 14) * (args.width // 14)
    print(f"vit stage {args.height}x{args.width}: grid "
          f"{args.height // 14}x{args.width // 14}, {patches} patches",
          file=sys.stderr)

    # NOTE ON ARGUMENT ORDER: llm_convert's help text calls --max_pixels
    # "width,height", but the code assigns args.max_shape = list(args.max_pixels)
    # verbatim and gen_vit_mlir then uses max_shape[0] as the resize *height*.
    # The shipped 784,784 build was square, so it could not tell the two orders
    # apart. Every stage here is non-square on purpose, which is what pins the
    # order down; the report states the measured grid.
    argv = [
        "llm_convert",
        "--model_path", str(args.weights),
        "-q", "bf16",
        "-g", "64",
        "-c", args.chip,
        "-s", str(args.seq),
        "--max_pixels", f"{args.height},{args.width}",
        "--num_core", str(args.num_core),
        "--out_dir", str(args.out_dir),
    ]
    if args.only_mlir:
        argv.append("--only_mlir")
    sys.argv = argv
    return shim.main()


if __name__ == "__main__":
    raise SystemExit(main())
