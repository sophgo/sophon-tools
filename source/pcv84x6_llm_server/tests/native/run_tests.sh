#!/bin/sh
# Build and run the host-side engine tests (no NPU, no libsophon install).
#
# Links the real native/src/llm_engine.cpp against tests/native/fake_bm.cpp,
# which supplies the bmrt/bmlib symbols. The assertions then observe the engine
# binary's actual launch/sync/copy behaviour instead of grepping its source.
#
#   tests/native/run_tests.sh [path-to-libsophon-headers]
#
# Default headers: /opt/sophon/libsophon-current/include (the board layout).
set -e
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
inc=${1:-/opt/sophon/libsophon-current/include}

if [ ! -f "$inc/bmruntime_interface.h" ]; then
  echo "no libsophon headers at $inc (pass the include dir as \$1)" >&2
  exit 2
fi

out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT

g++ -std=c++17 -O1 -g -Wall -Wextra \
  -I"$inc" -I"$repo/native/include" -I"$here" \
  "$repo/native/src/llm_engine.cpp" "$here/fake_bm.cpp" "$here/test_decode_submit.cpp" \
  -o "$out/test_decode_submit" -lpthread

"$out/test_decode_submit" /dev/null

# The generic single-graph runner (OCR det/rec). Separate binary: it shares the
# fake bmrt but not the chat fixture, and one build failure must not hide the
# other's results.
g++ -std=c++17 -O1 -g -Wall -Wextra \
  -I"$inc" -I"$repo/native/include" -I"$here" \
  "$repo/native/src/net_engine.cpp" "$here/fake_bm.cpp" "$here/test_net_engine.cpp" \
  -o "$out/test_net_engine" -lpthread

"$out/test_net_engine"

g++ -std=c++17 -O1 -g -Wall -Wextra \
  -I"$inc" -I"$repo/native/include" -I"$here" \
  "$repo/native/src/vl_embed_engine.cpp" "$repo/native/src/vl_embed_c_api.cpp" "$repo/native/src/vision.cpp" \
  "$here/fake_bm.cpp" "$here/test_vl_embed_engine.cpp" \
  -o "$out/test_vl_embed_engine" -lpthread -ljpeg -lz

"$out/test_vl_embed_engine"
