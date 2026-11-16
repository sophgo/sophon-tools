#!/bin/bash
# Compile the PaddleOCR-VL-1.5 bmodel for CV84X6 (tpu-mlir chip
# `bm1684x2`) through tools/ocr/paddleocr_vl_convert.py, which patches three
# converter defects in memory before invoking llm_convert.
#
#   tools/ocr/build_paddleocr_vl.sh <weights-dir> [out-dir]
#
# Runs inside the tpu-mlir container. See tools/ocr/README.md for the container
# setup and for what each patch fixes.
set -euo pipefail

WEIGHTS="${1:?usage: build_paddleocr_vl.sh <weights-dir> [out-dir]}"
OUT="${2:-/workspace/out}"
SHIM="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/paddleocr_vl_convert.py"

SEQ=2048
MAX_PIXELS=784,784
# bf16 weights. -g is the quant group size; with bf16 it is inert but kept at
# 64 to match the reference/sophon-demo command exactly, so a future switch to
# w4bf16 does not silently change group size.
GROUP=64

mkdir -p "$OUT"

# The converter writes ./<model>_<chip>_<quant>/ next to itself and combines
# into a timestamped bmodel; --out_dir takes the directory, not a filename.
python3 "$SHIM" \
  --model_path "$WEIGHTS" \
  -q bf16 \
  -g "$GROUP" \
  -c bm1684x2 \
  -s "$SEQ" \
  --max_pixels "$MAX_PIXELS" \
  --num_core 4 \
  --out_dir "$OUT"

echo "=== done ==="
ls -la "$OUT"/*.bmodel 2>/dev/null || find "$OUT" -name "*.bmodel" -newermt "-1 hour"
