#!/bin/bash
# psewriter (SE写卡工具) 统一构建接口 (sophon-tools M1 规范)
# 统一入口在子项目根 source/psewriter/release.sh，由它转发到本脚本（两者等价）。
# 用法: bash release.sh [ARCH] [VERSION]
#   ARCH:    windows（默认；32+64 位 exe）| linux（本机 CLI）| all
#   VERSION: 显式版本号（默认读本目录 VERSION 文件，唯一版本源）
#   env OUTPUT_DIR: 产物目录（默认 <repo>/output/psewriter/）
#   env IMAGE:      可选，把该文件包/整卡镜像内置进 exe（默认不内置）
# 产物:
#   sewriter.exe（32 位，Win7+ 通用，默认交付物）/ sewriter-x64.exe
#   sewriter-linux（ARCH=linux|all 时）
#   sewriter-embedded.exe（设了 IMAGE 时）
# 依赖: Go（Win7 兼容需 1.20.x，脚本内用 GOTOOLCHAIN 自动拉取）+
#       mingw windres（可用时重建 manifest 资源，否则用仓库内置 .syso）
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$SCRIPT_DIR"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
ARCH="${1:-windows}"
VERSION="${2:-$(sed -n '1p' "$SCRIPT_DIR/VERSION" 2>/dev/null | tr -d '[:space:]')}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/output/psewriter}"

case "$ARCH" in
  windows) ARCH_LIST="windows" ;;
  linux)   ARCH_LIST="linux" ;;
  all)     ARCH_LIST="windows linux" ;;
  *) echo "ERROR: ARCH 必须是 windows|linux|all，得到: $ARCH" >&2; exit 1 ;;
esac
[ -n "$VERSION" ] || { echo "ERROR: 取不到版本号（本目录 VERSION 为空）" >&2; exit 1; }

echo "==> psewriter build arch=$ARCH version=$VERSION image=${IMAGE:-<none>}"

BUILD_ARGS=(--test)
# 版本号以 VERSION 文件为唯一源；这里只做校验（build.sh 自己读同一份）
FILE_VER="$(sed -n '1p' "$SCRIPT_DIR/VERSION" | tr -d '[:space:]')"
[ "$VERSION" = "$FILE_VER" ] || echo "  ⚠ VERSION 文件是 $FILE_VER，本次按 $VERSION 构建（演练模式）"

for a in $ARCH_LIST; do
  case "$a" in
    windows) : ;;
    linux)   BUILD_ARGS+=(--linux) ;;
  esac
done
[ -n "${IMAGE:-}" ] && BUILD_ARGS+=(--image "$IMAGE")

# 本地中间产物目录（build.sh 默认 ./output）
rm -rf "$SCRIPT_DIR/output"
mkdir -p "$SCRIPT_DIR/output"

if ! OUT="$SCRIPT_DIR/output" bash "$SCRIPT_DIR/build.sh" "${BUILD_ARGS[@]}"; then
  echo "ERROR: build.sh 失败" >&2
  exit 1
fi

# 统一接口：产物汇聚到 OUTPUT_DIR（output/<子项目>/）
mkdir -p "$OUTPUT_DIR"
COPIED=0
for f in "$SCRIPT_DIR"/output/sewriter.exe "$SCRIPT_DIR"/output/sewriter-x64.exe \
         "$SCRIPT_DIR"/output/sewriter-linux "$SCRIPT_DIR"/output/sewriter-embedded.exe; do
  [ -f "$f" ] || continue
  cp "$f" "$OUTPUT_DIR/"
  echo "  → $(basename "$f")  ($(stat -c %s "$f") 字节)"
  COPIED=$((COPIED + 1))
done
if [ "$COPIED" -eq 0 ]; then
  echo "ERROR: 没有产出任何文件" >&2
  exit 1
fi

echo "==> psewriter 完成, 产物: $OUTPUT_DIR"
exit 0
