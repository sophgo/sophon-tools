#!/bin/bash
# Build diagnostics and run the model-free copy-chain control; no service changes.
# Usage: bash verify.sh <package-root>
set -euo pipefail
PKG="${1:?usage: $0 <package-root>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/mys2913-verify.XXXXXX")"
# Remove only this invocation's private directory, including on failures.
trap 'rm -rf -- "$WORK"' EXIT

timeout --foreground 120 bash "$HERE/MYS-2913-build-diag.sh" "$PKG" "$WORK/diag" \
  >"$WORK/build.log" 2>&1 || { cat "$WORK/build.log" >&2; exit 1; }
cat "$WORK/build.log"
timeout --foreground 120 bash "$HERE/copy_chain_build.sh" "$WORK/chain"

# An intermittent baseline mismatch (rc=1) is a valid observation; API errors
# and timeouts are tool failures. The synchronized control must match exactly.
no_fence_rc=0
timeout --foreground 60 "$WORK/chain/copy-chain" --trials 64 --no-fence || no_fence_rc=$?
echo "no_fence_rc=$no_fence_rc"
if [ "$no_fence_rc" -gt 1 ]; then exit "$no_fence_rc"; fi
fence_rc=0
timeout --foreground 60 "$WORK/chain/copy-chain" --trials 64 --fence || fence_rc=$?
echo "fence_rc=$fence_rc"
if [ "$fence_rc" -ne 0 ]; then exit "$fence_rc"; fi
echo "Verification complete: tool steps succeeded and the synchronized control matched."
