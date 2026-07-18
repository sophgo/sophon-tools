#!/bin/bash
# 生成版本头信息，写入 build/version.txt 供 ldflags 读取
set -e
VERSION="${1:-2.1.0}"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
BUILDTIME="$(date '+%Y-%m-%d_%H:%M:%S')"
cat > "$(dirname "$0")/version.txt" <<EOF
${VERSION}|${COMMIT}|${BUILDTIME}
EOF
cat "$(dirname "$0")/version.txt"
