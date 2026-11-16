#!/bin/bash
# Board verification for the converged MYS-2913 deliverables.
#
#   bash verify.sh <package-root>
#
# 1. builds the diagnostic library from a fresh temp dir (-Werror: any format
#    warning fails the build)
# 2. builds and runs the model-free A->B->C probe, both arms, 64 trials each
# Everything is allocated by this run and removed afterwards.
set -uo pipefail
PKG="${1:?usage: $0 <package-root>}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== 1. diagnostic library build (fresh dir, -Werror)"
BUILD_OUT="$(bash "$HERE/MYS-2913-build-diag.sh" "$PKG" 2>&1)"
BUILD_RC=$?
echo "$BUILD_OUT" | tail -6
echo "build_rc=$BUILD_RC"
if [ "$BUILD_RC" -ne 0 ]; then
  echo "BUILD FAILED" >&2
  exit 1
fi
# The build script's last line is the .so path; the work dir is its parent.
WORKDIR="$(dirname "$(echo "$BUILD_OUT" | tail -1)")"
echo "warnings_in_build=$(echo "$BUILD_OUT" | grep -c 'warning:' || true)"

echo
echo "== 2. model-free A->B->C probe"
CHAIN_OUT="$(bash "$HERE/copy_chain_build.sh" 2>&1)"
CHAIN_RC=$?
echo "$CHAIN_OUT" | tail -3
if [ "$CHAIN_RC" -ne 0 ]; then
  echo "CHAIN BUILD FAILED" >&2
  exit 1
fi
BIN="$(echo "$CHAIN_OUT" | tail -1)"

echo "-- arm: no fence (64 trials)"
"$BIN" --trials 64 --no-fence
echo "no_fence_rc=$?"

echo "-- arm: fence between copies (64 trials)"
"$BIN" --trials 64 --fence
echo "fence_rc=$?"

echo
echo "== cleanup"
rm -rf "$WORKDIR" "$(dirname "$BIN")"
for d in "$WORKDIR" "$(dirname "$BIN")"; do
  if [ -e "$d" ]; then echo "WARNING: $d still exists" >&2; else echo "removed $d"; fi
done
