#!/bin/bash
# Cross-compile vl_native for the board. No sail, no Python: it links the same
# libbmrt/libbmlib the installed service links, so what it measures is what the
# product would do.
#
#   tools/ocr/vl_native/build.sh [out-dir]
#
# The board's libsophon is 0.4.15 (== libsophon-current); headers and libs come
# from the libsophon tree this workspace builds, and the RPATH points at the
# board's own install so the binary runs there without LD_LIBRARY_PATH.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
OUT="${1:-$HERE/out}"

CROSS="${CROSS:-/home/zzt/workspace/cv84x2/host-tools/gcc/arm-gnu-toolchain-11.3.rel1-x86_64-aarch64-none-linux-gnu/bin/aarch64-none-linux-gnu-g++}"
LIBSOPHON_SRC="${LIBSOPHON_SRC:-/home/zzt/workspace/cv84x2/libsophon}"
INC_RT="$LIBSOPHON_SRC/tpu-runtime/include"
INC_LIB="$LIBSOPHON_SRC/bmlib/include"
# Board-side paths: the binary runs on .157, so it must find these there.
BOARD_PREFIX=/opt/sophon/libsophon-0.4.15
# Link against the libsophon tree in this workspace (the board's install ships
# only the versioned .so.0/.so.1.0 plus the linker symlinks, so linking is done
# here and the RPATH resolves on the board).
LIBSOPHON_LIB="${LIBSOPHON_LIB:-$LIBSOPHON_SRC/build/install/libsophon-0.4.15/lib}"

if [ ! -x "$CROSS" ]; then
  echo "cross compiler not found: $CROSS" >&2
  exit 1
fi
for d in "$INC_RT" "$INC_LIB"; do
  [ -d "$d" ] || { echo "missing headers: $d" >&2; exit 1; }
done

mkdir -p "$OUT"
"$CROSS" -std=c++17 -O2 -Wall -Wextra \
  -I"$INC_RT" -I"$INC_LIB" \
  "$HERE/vl_native.cpp" \
  -L"$LIBSOPHON_LIB" -lbmrt -lbmlib -lpthread \
  -Wl,-rpath,"$BOARD_PREFIX/lib" \
  -o "$OUT/vl_native"

echo "built $OUT/vl_native"
"$CROSS" -v 2>&1 | tail -1 || true
