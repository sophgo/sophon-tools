#!/bin/bash
# aarch64 交叉编译（musl 全静态链接，修复真机 glibc 过旧）
set -e
cd "$(dirname "$0")/.."
VERSION="${1:-2.1.0}"
bash build/version.sh "$VERSION"
read VERSION COMMIT BUILDTIME < <(tr '|' ' ' < build/version.txt)

# 确保 musl 工具链可用（系统已装则直接用，否则下载）
MUSL_BIN="$(bash build/fetch-musl-toolchain.sh)"
[ -n "$MUSL_BIN" ] && export PATH="$MUSL_BIN:$PATH"

# ldflags 用单/双引号拼接：version 三项 -X 走变量展开，static 段走字面
CGO_ENABLED=1 GOOS=linux GOARCH=arm64 \
  CC=aarch64-linux-musl-gcc \
  CXX=aarch64-linux-musl-g++ \
  go build -trimpath \
    -tags 'netgo osusergo sqlite_omit_load_extension' \
    -ldflags '-s -w -X bmssm/global.version='"${VERSION}"' -X bmssm/global.gitCommit='"${COMMIT}"' -X bmssm/global.buildTime='"${BUILDTIME}"' -linkmode external -extldflags "-static"' \
  -o bmssm-arm64 . \
  || { echo "ERROR: arm64 构建失败"; exit 1; }

# 静态链接门禁
file bmssm-arm64 | grep -q 'statically linked' \
  || { echo "ERROR: arm64 产物不是静态链接"; exit 1; }
echo "arm64 产物静态链接校验通过"

mkdir -p release
cp bmssm-arm64 release/bmssm
cp config/bmssm.yaml release/
echo "built release/bmssm (arm64, musl static)"
