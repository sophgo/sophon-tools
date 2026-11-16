#!/bin/bash
# Compile PP-DocLayout-S / -M for CV84X6 (tpu-mlir chip name `bm1684x2`).
#
#   tools/ocr/build_layout_sm.sh <onnx-dir> [out-dir]
#
# Runs inside the tpu-mlir container (see tools/ocr/README.md). The ONNX must
# already be **cut**: this script compiles `<name>_cut.onnx`, whose outputs are
# the dense pre-NMS tensors. Compiling the published ONNX is what made stage A's
# layout detector hang -- it contains a data-dependent NMS/top-k that tpu-mlir
# lowers to a TPU_DYNAMIC subnet, and a dynamic subnet wedges this NPU
# (docs/ocr-stage-a.md §2). Produce the cut file with:
#
#   python3 tools/ocr/layout_cut.py --onnx PP-DocLayout-S.onnx \
#           --out PP-DocLayout-S_cut.onnx --verify <img dir>
#
# Unlike the V3 build in build_layout.sh this one keeps *no* shape inputs: the
# cut lands before the graph's own division by scale_factor, so the bmodel takes
# one tensor in and two out. That is deliberate -- a [1,2] input is one more
# thing every caller has to get right, and one more symbolic shape for the
# compiler to leave in the module.
set -euo pipefail

ONNX_DIR="${1:?usage: build_layout_sm.sh <onnx-dir> [out-dir]}"
OUT="${2:-/workspace/out}"
DATE="$(date +%Y%m%d)"

export PATH=/usr/local/lib/python3.10/dist-packages/tpu_mlir/bin:$PATH
export PYTHONPATH=/usr/local/lib/python3.10/dist-packages/tpu_mlir/python:${PYTHONPATH:-}

mkdir -p "$OUT"
cd "$ONNX_DIR"

# name:side -- the network square from each model's own inference.yml.
# PP-DocLayout-S 480, PP-DocLayout-M 640. Resize keeps no aspect ratio
# (keep_ratio: false), which is the model's own definition, not a shortcut.
for ENTRY in "PP-DocLayout-S:480" "PP-DocLayout-M:640"; do
  NAME="${ENTRY%%:*}"
  SIDE="${ENTRY##*:}"
  CUT="${NAME}_cut.onnx"
  TAG="$(echo "$NAME" | tr 'A-Z-' 'a-z_')"

  if [[ ! -f "$CUT" ]]; then
    echo "missing $CUT -- run tools/ocr/layout_cut.py first" >&2
    exit 1
  fi

  # A 4-D input shape is enough; the cut graph's other inputs are gone.
  python3 -c "
import numpy as np
np.savez('${TAG}_in.npz', image=np.random.rand(1,3,${SIDE},${SIDE}).astype(np.float32))
"

  echo "=== ${NAME}: model_transform ${SIDE}x${SIDE} ==="
  model_transform \
    --model_name "$TAG" \
    --model_def "$CUT" \
    --input_shapes "[[1,3,${SIDE},${SIDE}]]" \
    --mlir "${TAG}.mlir"

  echo "=== ${NAME}: model_deploy F16 ==="
  model_deploy \
    --mlir "${TAG}.mlir" \
    --quantize F16 \
    --chip bm1684x2 \
    --num_core 4 \
    --model "$OUT/${TAG}_f16_${SIDE}_bm1684x2_static_${DATE}.bmodel"

  echo "=== ${NAME}: subnet modes ==="
  grep -o "run_mode [A-Z_]*" "${TAG}_tpu.mlir" 2>/dev/null | sort | uniq -c || true
done

echo "=== done ==="
ls -la "$OUT"/*.bmodel
