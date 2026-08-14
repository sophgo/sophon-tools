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

# strip release 冗余：go build 已带 -s -w 去符号/DWARF，这里再删 .comment（工具链
# 版本注释）与 .note.go.buildid（构建 ID），并 --strip-unneeded 兜底清局部符号。
find_strip() {
  # 优先与编译器同族的 musl strip；无则回退系统 strip。
  for c in aarch64-linux-musl-strip aarch64-linux-gnu-strip strip llvm-strip; do
    if command -v "$c" >/dev/null 2>&1; then echo "$c"; return 0; fi
  done
  return 1
}
if STRIP_BIN="$(find_strip)"; then
  "$STRIP_BIN" --strip-unneeded --remove-section=.comment --remove-section=.note.go.buildid bmssm-arm64 \
    && echo "strip $STRIP_BIN ok" \
    || echo "WARN: strip 失败（跳过，产物保留 -s -w 级别）" >&2
else
  echo "WARN: 未找到 strip 命令，跳过（产物保留 -s -w 级别）" >&2
fi

mkdir -p release
# 先清空 release/ 再落产物，避免上一架构残留（如连续 all 构建 arm64→amd64 中断）
rm -f release/bmssm release/bmssm.yaml
cp bmssm-arm64 release/bmssm
cp config/bmssm.yaml release/
echo "built release/bmssm (arm64, musl static)"
