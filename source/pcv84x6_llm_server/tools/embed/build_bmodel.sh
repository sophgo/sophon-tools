#!/usr/bin/env bash
# Compile a Qwen3-Embedding-0.6B bmodel for CV84X6 (bm1684x2), at any SEQLEN.
#
#   tools/embed/build_bmodel.sh <seq-length> [out-dir-name]
#
# Parameter-identical to the vendor build this replaces
# (qwen3-embedding-0.6b_bf16_seq8192_bm1684x2_4core_static_20260920_184312),
# except for `-s`: bf16, CV84X6 target, 4 cores, static, last-token pooling.
# The two accepted builds from MYS-2696 are therefore:
#
#   tools/embed/build_bmodel.sh 2048     # shipped: seq2048
#   tools/embed/build_bmodel.sh 1024     # comparison only, not published
#
# MYS-2702 added the dynamic variant (it measured dynamic against static and
# against several static lengths; see docs/research/aux-dynamic-seq.md):
#
#   DYNAMIC=1 tools/embed/build_bmodel.sh 8192 out_dyn8192
#
# Dynamic means the block graphs take their sequence dimension from the real
# token count instead of the compiled one. It is compiled the same way; only
# `--dynamic` is added.
#
# Run this ON the build host (13.24), not on the board. It drives the
# `embed_build` container, whose /workspace is the host's
# /mnt/sda2/cv84x6_llm_server/build_embed. That layout is:
#
#   weights/Qwen3-Embedding-0.6B        ModelScope download, keys unprefixed
#   tpuc/Qwen3-Embedding-0.6B           same weights, keys prefixed for tpu-mlir
#   out_seq<SEQ>/                       output
#
# The second directory exists because llm_convert.py cannot read the upstream
# checkpoint: its qwen3 weight map addresses `model.layers.*` / `model.norm`,
# and the published checkpoint stores `layers.*` / `norm`. See
# tools/embed/fix_weight_prefix.py, which this script runs when the prefixed
# copy is missing.
set -euo pipefail

SEQ=${1:?sequence length, e.g. 2048}
CONTAINER=${CONTAINER:-embed_build}
BUILD=${BUILD:-/mnt/sda2/cv84x6_llm_server/build_embed}
SRC=${SRC:-Qwen3-Embedding-0.6B}
OUT=${2:-out_seq${SEQ}}
#: `DYNAMIC=1` compiles the dynamic variant (MYS-2702). Empty == static.
DYNAMIC_FLAG=""
[ "${DYNAMIC:-0}" = "1" ] && DYNAMIC_FLAG="--dynamic"

HERE=$(cd "$(dirname "$0")" && pwd)

if [ ! -f "$BUILD/tpuc/$SRC/model.safetensors" ]; then
  echo "== prefixing weights (tpu-mlir wants model.layers.*, upstream has layers.*)"
  python3 "$HERE/fix_weight_prefix.py" "$BUILD/weights/$SRC" "$BUILD/tpuc/$SRC"
fi

echo "== compiling $SRC seq=$SEQ${DYNAMIC_FLAG:+ (dynamic)} -> $BUILD/$OUT in $CONTAINER"
docker inspect "$CONTAINER" >/dev/null 2>&1 || {
  echo "no container '$CONTAINER'; create it with:" >&2
  echo "  docker run -d --name $CONTAINER -v $BUILD:/workspace ocr-tpu:1.30.2 sleep infinity" >&2
  exit 2
}

docker exec "$CONTAINER" bash -lc "
  set -euo pipefail
  cd /workspace
  rm -rf '$OUT'
  llm_convert.py -m ./tpuc/$SRC -s $SEQ -c bm1684x2 -q bf16 --num_core 4 \\
    $DYNAMIC_FLAG --out_dir /workspace/$OUT
"

echo "== done; artifacts:"
ls -la "$BUILD/$OUT"/*.bmodel
md5sum "$BUILD/$OUT"/*.bmodel
echo
echo "Report the metadata with:"
echo "  docker exec $CONTAINER model_tool --info /workspace/$OUT/<model>.bmodel"
