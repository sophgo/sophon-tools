#!/bin/bash
# Build the MYS-2913 instrumented WeMM encoder from a *clean* checkout.
#
# Everything it needs is in this repository plus the board's own libsophon; it
# creates its own working directory and consumes no pre-existing /tmp layout.
#
#   bash tools/vl_embed/MYS-2913-build-diag.sh <package-root> [work-dir]
#
#   <package-root>  source/pcv84x6_llm_server (a clean checkout of this package)
#   [work-dir]      defaults to $PWD/mys2913-diag-build
#
# Output: <work-dir>/libcv84x6_vl_diag.so
#
# The instrumented source is native/src/vl_embed_engine.cpp plus
# MYS-2913-instrumentation.patch, which only adds per-stage readbacks and the
# CV_VLE_* A/B switches. It is a diagnostic artifact: the production library at
# /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so is never touched.
set -eu

PKG="${1:?usage: $0 <package-root> [work-dir]}"
WORK="${2:-$PWD/mys2913-diag-build}"
PKG="$(cd "$PKG" && pwd)"
HERE="$(cd "$(dirname "$0")" && pwd)"

LIBSOPHON="${LIBSOPHON:-/opt/sophon/libsophon-current}"
test -d "$LIBSOPHON/include" || { echo "missing $LIBSOPHON/include" >&2; exit 1; }

# libjpeg ships as a versioned soname with no bare .so symlink on this image.
JPEG="$(ls /usr/lib/*/libjpeg.so.8 /lib/*/libjpeg.so.8 2>/dev/null | head -1 || true)"
test -n "$JPEG" || { echo "libjpeg.so.8 not found" >&2; exit 1; }

echo "== work dir: $WORK"
rm -rf "$WORK"
mkdir -p "$WORK"
# Keep the package layout (native/src, native/include) so the patch, which is
# rooted at the package directory, applies with -p1.
cp -r "$PKG/native" "$WORK/native"

echo "== applying MYS-2913-instrumentation.patch"
( cd "$WORK" && patch -p1 --no-backup-if-mismatch --batch \
    < "$HERE/MYS-2913-instrumentation.patch" )

echo "== compiling"
g++ -std=c++17 -O2 -fPIC -shared -Wall -Wextra \
    -I"$WORK/native/include" -I"$LIBSOPHON/include" \
    "$WORK/native/src/vl_embed_engine.cpp" \
    "$WORK/native/src/vl_embed_c_api.cpp" \
    "$WORK/native/src/vision.cpp" \
    -o "$WORK/libcv84x6_vl_diag.so" \
    -L"$LIBSOPHON/lib" -lbmrt -lbmlib -lpthread "$JPEG" -lz \
    -Wl,-rpath,"$LIBSOPHON/lib"

echo "== built $WORK/libcv84x6_vl_diag.so"
sha256sum "$WORK/libcv84x6_vl_diag.so"
