#!/bin/bash
# Build the MYS-2913 instrumented encoder in /tmp/mys2913/diag.
#
# This is a *diagnostic copy* of native/src/vl_embed_engine.cpp with per-stage
# readbacks added (token embedding, ViT output, and every encoder block's output
# row). It is compiled here, in a temporary directory, and links against the
# board's own libsophon. The production library is never replaced and the
# production service is never restarted.
set -eu
SRC="${1:-/tmp/mys2913/diag}"
OUT=/tmp/mys2913/build
mkdir -p "$OUT"

g++ -std=c++17 -O2 -fPIC -shared -Wall -Wextra \
    -I"$SRC/include" \
    -I/opt/sophon/libsophon-current/include \
    "$SRC/vl_embed_engine_diag.cpp" "$SRC/vl_embed_c_api.cpp" "$SRC/vision.cpp" \
    -o "$OUT/libcv84x6_vl_diag.so" \
    -L/opt/sophon/libsophon-current/lib -lbmrt -lbmlib -lpthread /usr/lib/aarch64-linux-gnu/libjpeg.so.8 -lz \
    -Wl,-rpath,/opt/sophon/libsophon-current/lib
echo "built $OUT/libcv84x6_vl_diag.so"
ls -l "$OUT/libcv84x6_vl_diag.so"
