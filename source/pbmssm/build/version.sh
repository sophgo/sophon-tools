#!/bin/bash
# 生成版本头信息，写入 build/version.txt 供 ldflags 读取
# DEFAULT_VERSION 是 bmssm 版本号的唯一权威定义；release.sh / build-deb 从此处
# 提取默认值（规范：版本号在工具代码中更新，仓库根 release 禁止传版本号进来）。
set -e
DEFAULT_VERSION="2.3.5"
VERSION="${1:-$DEFAULT_VERSION}"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
BUILDTIME="$(date '+%Y-%m-%d_%H:%M:%S')"
cat > "$(dirname "$0")/version.txt" <<EOF
${VERSION}|${COMMIT}|${BUILDTIME}
EOF
cat "$(dirname "$0")/version.txt"
