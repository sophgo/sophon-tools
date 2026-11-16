#!/usr/bin/env bash
# Compile a Qwen3-ASR bmodel for CV84X6 (bm1684x2) inside the tpuc22 container.
#
#   tools/asr/build_bmodel.sh <weights-dir> <out-dir> [seq_length] [max_input_length]
#
# <weights-dir> is a ModelScope download of Qwen/Qwen3-ASR-1.7B or -0.6B:
#
#   modelscope download --model Qwen/Qwen3-ASR-1.7B --local_dir Qwen3-ASR-1.7B
#
# Run this ON the build host (13.24), not on the board: tpu-mlir needs x86 and
# the tpuc22 container. The container's /workspace is the host's
# /mnt/sda2/cv84x6_llm_server/build35, so paths below are container paths.
#
# Why the trailing python shim: the container's tpu_mlir 1.30.2 has a
# Qwen3AsrConverter that predates llm_convert.py's `loader=` keyword. The shim
# patches that one class in memory (see asr_convert.py next to this script) and
# leaves the container's site-packages alone, because the 35B builds share it.
set -euo pipefail

WEIGHTS=${1:?weights dir (container path)}
OUT=${2:?output dir (container path)}
SEQ=${3:-1024}
MAXIN=${4:-512}
CONTAINER=${CONTAINER:-tpuc22}
VENV=${VENV:-/workspace/asr-venv}
SHIM=${SHIM:-/workspace/asr/asr_convert.py}
STUB=${STUB:-/workspace/asr/stub}

echo "== compiling $WEIGHTS -> $OUT (seq=$SEQ max_in=$MAXIN) in $CONTAINER"
docker exec "$CONTAINER" bash -lc "
  set -euo pipefail
  test -d '$WEIGHTS' || { echo 'no weights at $WEIGHTS' >&2; exit 2; }
  PYTHONPATH=$STUB $VENV/bin/python $SHIM \\
    -m '$WEIGHTS' \\
    -s $SEQ --max_input_length $MAXIN --quantize bf16 \\
    -c bm1684x2 --out_dir '$OUT'
"

echo "== done; artifacts:"
docker exec "$CONTAINER" bash -lc "ls -la '$OUT'/*.bmodel"
echo
echo "Report the metadata with:"
echo "  docker exec $CONTAINER model_tool --info $OUT/<model>.bmodel"
