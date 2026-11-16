#!/bin/bash
# Build the MYS-2913 instrumented WeMM encoder from a clean checkout.
#
#   bash tools/vl_embed/MYS-2913-build-diag.sh <package-root> [work-dir]
#
#   <package-root>  source/pcv84x6_llm_server (a clean checkout of this package)
#   [work-dir]      a path that MUST NOT already exist. When omitted, a fresh
#                   mktemp directory is created. The script never removes a
#                   directory it did not just create, so passing an existing
#                   tree is refused rather than deleted.
#
# Output: <work-dir>/libcv84x6_vl_diag.so
#
# The instrumented source is native/src/vl_embed_engine.cpp plus
# MYS-2913-instrumentation.patch, which only adds per-stage readbacks and the
# CV_VLE_* A/B switches. It is a diagnostic artifact: the production library at
# /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so is never touched.
#
# Every step that can fail is checked and aborts the script with a non-zero
# status; nothing is left reporting success after a failed compile or patch.
set -euo pipefail

PKG="${1:?usage: $0 <package-root> [work-dir]}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PKG="$(cd "$PKG" && pwd)"

if [ $# -ge 2 ]; then
  WORK="$2"
  if [ -e "$WORK" ]; then
    echo "MYS-2913-build-diag: refusing to reuse existing path $WORK" >&2
    exit 1
  fi
  mkdir -p "$WORK"
else
  WORK="$(mktemp -d "${TMPDIR:-/tmp}/mys2913-diag-build.XXXXXX")"
fi

LIBSOPHON="${LIBSOPHON:-/opt/sophon/libsophon-current}"
if [ ! -d "$LIBSOPHON/include" ]; then
  echo "MYS-2913-build-diag: missing $LIBSOPHON/include" >&2
  exit 1
fi
if [ ! -d "$PKG/native/src" ]; then
  echo "MYS-2913-build-diag: $PKG does not look like the package root" >&2
  exit 1
fi

# libjpeg ships as a versioned soname with no bare .so symlink on this image.
JPEG="$(ls /usr/lib/*/libjpeg.so.8 /lib/*/libjpeg.so.8 2>/dev/null | head -1 || true)"
if [ -z "$JPEG" ]; then
  echo "MYS-2913-build-diag: libjpeg.so.8 not found" >&2
  exit 1
fi

echo "== work dir: $WORK"
# Keep the package layout (native/src, native/include) so the patch, which is
# rooted at the package directory, applies with -p1.
cp -r "$PKG/native" "$WORK/native"

echo "== applying MYS-2913-instrumentation.patch"
if ! ( cd "$WORK" && patch -p1 --no-backup-if-mismatch --batch --forward \
        < "$HERE/MYS-2913-instrumentation.patch" ); then
  echo "MYS-2913-build-diag: patch failed" >&2
  exit 1
fi

echo "== compiling"
# -Werror: a format/type warning in the diagnostic printf helpers must fail the
# build rather than ship a binary that prints wrong numbers.
g++ -std=c++17 -O2 -fPIC -shared -Wall -Wextra -Werror \
    -I"$WORK/native/include" -I"$LIBSOPHON/include" \
    "$WORK/native/src/vl_embed_engine.cpp" \
    "$WORK/native/src/vl_embed_c_api.cpp" \
    "$WORK/native/src/vision.cpp" \
    -o "$WORK/libcv84x6_vl_diag.so" \
    -L"$LIBSOPHON/lib" -lbmrt -lbmlib -lpthread "$JPEG" -lz \
    -Wl,-rpath,"$LIBSOPHON/lib"

if [ ! -f "$WORK/libcv84x6_vl_diag.so" ]; then
  echo "MYS-2913-build-diag: compiler produced no library" >&2
  exit 1
fi

echo "== built $WORK/libcv84x6_vl_diag.so"
sha256sum "$WORK/libcv84x6_vl_diag.so"
echo "$WORK/libcv84x6_vl_diag.so"
