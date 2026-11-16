#!/bin/bash
# Compile the PP-OCRv6-medium det + rec bmodels for CV84X6 (tpu-mlir chip name
# `bm1684x2`) and stage them under $OUT with the release naming scheme.
#
#   tools/ocr/build_ppocr.sh [work-dir] [out-dir]
#
# Runs inside the tpu-mlir container (see tools/ocr/README.md). The ONNX files
# come from PaddleOCR's official inference models via paddle2onnx; the exact
# command is in the README.
set -euo pipefail

WORK="${1:-/workspace/work}"
OUT="${2:-/workspace/out}"
DET_ONNX="${DET_ONNX:-$WORK/ppocrv6_medium_det.onnx}"
REC_ONNX="${REC_ONNX:-$WORK/ppocrv6_medium_rec.onnx}"
DATE="$(date +%Y%m%d)"

DET_SIDE=736
REC_H=48
REC_WIDTHS=(320 640)

cd "$WORK"
mkdir -p "$OUT"

if [[ ! -f "$DET_ONNX" || ! -f "$REC_ONNX" ]]; then
  echo "missing onnx: $DET_ONNX / $REC_ONNX" >&2
  exit 1
fi

# --- det: one static shape, 736x736 --------------------------------------- #
echo "=== det: model_transform ${DET_SIDE}x${DET_SIDE} ==="
python3 -c "
import numpy as np
np.savez('det_in.npz', x=np.random.rand(1,3,${DET_SIDE},${DET_SIDE}).astype(np.float32))
"
model_transform.py \
  --model_name ppocrv6_medium_det \
  --model_def "$DET_ONNX" \
  --input_shapes "[[1,3,${DET_SIDE},${DET_SIDE}]]" \
  --test_input det_in.npz \
  --test_result det_top_outputs.npz \
  --tolerance 0.99,0.99 \
  --mlir ppocrv6_medium_det.mlir

echo "=== det: model_deploy F16 bm1684x2 ==="
model_deploy.py \
  --mlir ppocrv6_medium_det.mlir \
  --quantize F16 \
  --chip bm1684x2 \
  --test_input det_in.npz \
  --tolerance 0.99,0.90 \
  --model "$OUT/ppocrv6-medium-det_f16_${DET_SIDE}_bm1684x2_static_${DATE}.bmodel"

# --- rec: one static shape per width tier ---------------------------------- #
# Two separate bmodels rather than one dynamic one: sophon-demo splits by width
# and the caller picks the tier from the crop's aspect ratio. A dynamic-shape
# model would work too but costs the compiler's static scheduling.
for W in "${REC_WIDTHS[@]}"; do
  echo "=== rec ${REC_H}x${W}: model_transform ==="
  python3 -c "
import numpy as np
np.savez('rec${W}_in.npz', x=np.random.rand(1,3,${REC_H},${W}).astype(np.float32))
"
  model_transform.py \
    --model_name "ppocrv6_medium_rec_${W}" \
    --model_def "$REC_ONNX" \
    --input_shapes "[[1,3,${REC_H},${W}]]" \
    --test_input "rec${W}_in.npz" \
    --test_result "rec${W}_top_outputs.npz" \
    --tolerance 0.99,0.99 \
    --mlir "ppocrv6_medium_rec_${W}.mlir"

  echo "=== rec ${REC_H}x${W}: model_deploy F16 bm1684x2 ==="
  model_deploy.py \
    --mlir "ppocrv6_medium_rec_${W}.mlir" \
    --quantize F16 \
    --chip bm1684x2 \
    --test_input "rec${W}_in.npz" \
    --tolerance 0.99,0.90 \
    --model "$OUT/ppocrv6-medium-rec_f16_${REC_H}x${W}_bm1684x2_static_${DATE}.bmodel"
done

echo "=== done ==="
ls -la "$OUT"/*.bmodel
