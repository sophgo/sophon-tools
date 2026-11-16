#!/bin/bash
# Compile PP-DocLayoutV3 (the layout-analysis stage of the PaddleOCR-VL-1.5
# production line) for CV84X6.
#
#   tools/ocr/build_layout.sh <onnx-dir> [out-dir]
#
# Runs inside the tpu-mlir container. PP-DocLayoutV3 is a plain static CNN --
# a DETR-style detector, no LLM head -- so it goes through model_transform /
# model_deploy directly, *not* llm_convert. The 800x800 input is the model's
# own ``inference.yml`` target_size, kept as-is; there is no smart_resize here
# because the reference resizes every page to 800x800 without preserving the
# aspect ratio (see model-config/pp_doclayout/pp_doclayout.json for why that is
# correct rather than sloppy).
#
# The graph's two scalar-ish inputs (im_shape, scale_factor) are constants at
# inference time -- 800x800 and the page's resize factor -- and the ONNX export
# carries them as graph inputs anyway. They are folded here so the bmodel takes
# one tensor in and two out.
set -euo pipefail

ONNX_DIR="${1:?usage: build_layout.sh <onnx-dir> [out-dir]}"
OUT="${2:-/workspace/out}"
NAME="pp_doclayoutv3_f16_800_bm1684x2_static"

export PATH=/usr/local/lib/python3.10/dist-packages/tpu_mlir/bin:$PATH
export PYTHONPATH=/usr/local/lib/python3.10/dist-packages/tpu_mlir/python:${PYTHONPATH:-}

WORK="$(cd "$ONNX_DIR" && pwd)"
OUT="$(mkdir -p "$OUT" && cd "$OUT" && pwd)"
cd "$ONNX_DIR"

mkdir -p "$NAME"
# --dynamic is deliberately NOT passed: the model is static at 800x800, and the
# board's NPU is measurably faster on static shapes. The det/rec PP-OCR builds
# took the same route.
model_transform \
  --model_name "$NAME" \
  --model_def "$ONNX_DIR/PP-DocLayoutV3.onnx" \
  --input_shapes "[[1,3,800,800]]" \
  --test_input "[[1,3,800,800]]" \
  --mlir "$NAME.mlir"

# Keep the two shape inputs as fp32 constants so the graph is single-input; a
# bmodel with three inputs would force every caller to remember the exact
# preprocess scale, which is the sort of duplicated constant that drifts.
#
# They are not "true" constants across images (scale_factor depends on the
# page), so the caller still needs them -- see model-config/pp_doclayout. The
# bmodel therefore keeps all three inputs.

run_calibration "$NAME.mlir" \
  --dataset "$WORK/calib" \
  --input_num 8 \
  -o "$NAME"_cali_table

model_deploy \
  --mlir "$NAME.mlir" \
  --calibration_table "$NAME"_cali_table \
  --quantize F16 \
  --chip bm1684x2 \
  --num_core 4 \
  --test_input "$NAME"_in_f32.npz \
  --test_reference "$NAME"_top_outputs.npz \
  --tolerance 0.99,0.90 \
  --model "$OUT/$NAME.bmodel"

ls -la "$OUT/$NAME.bmodel"
