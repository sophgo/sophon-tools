#!/bin/bash
# Build the model-free A->B->C copy-chain probe (MYS-2913).
#
#   bash copy_chain_build.sh [out-dir]
#
# Default out-dir is a fresh mktemp directory, so an existing tree is never
# overwritten. The build fails loudly (non-zero) if the compiler fails.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LIBSOPHON="${LIBSOPHON:-/opt/sophon/libsophon-current}"

if [ ! -d "$LIBSOPHON/include" ] || [ ! -d "$LIBSOPHON/lib" ]; then
  echo "copy_chain_build: libsophon not found at $LIBSOPHON" >&2
  exit 1
fi

if [ $# -ge 1 ]; then
  OUT="$1"
  if [ -e "$OUT" ]; then
    echo "copy_chain_build: refusing to reuse existing path $OUT" >&2
    exit 1
  fi
  mkdir -p "$OUT"
else
  OUT="$(mktemp -d "${TMPDIR:-/tmp}/mys2913-copychain.XXXXXX")"
fi

echo "copy_chain_build: out-dir=$OUT"
g++ -std=c++17 -O2 -Wall -Wextra -Werror \
    -o "$OUT/copy-chain" "$HERE/copy_chain.cpp" \
    -I"$LIBSOPHON/include" \
    -L"$LIBSOPHON/lib" -lbmlib \
    -Wl,-rpath,"$LIBSOPHON/lib"

echo "copy_chain_build: built $OUT/copy-chain"
sha256sum "$OUT/copy-chain"
echo "$OUT/copy-chain"
