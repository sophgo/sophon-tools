#!/bin/bash
# pota_update 统一构建接口 (M1 规范 v0.1)
# 用法: bash release.sh [ARCH] [VERSION]
#   ARCH:    arm64（默认，设备）；amd64 仅打包脚本不交叉编译（bc 依赖系统自带）
#   VERSION: 显式版本号（默认从 ota.sh 提取 v1.4.0）
#   env OUTPUT_DIR: 产物目录（默认 <repo>/output/pota_update/）
set -uo pipefail

BUILD_RET=0

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$SCRIPT_DIR" || exit 1   # 打包源/产物路径全部以本脚本目录为基准，消除对调用方 cwd 的依赖
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARCH="${1:-arm64}"
VERSION="${2:-$(grep -oE 'version: v[0-9]+\.[0-9]+\.[0-9]+' "$SCRIPT_DIR/ota.sh" | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/output/pota_update}"

case "$ARCH" in
  arm64|amd64) ;;
  *) echo "ERROR: ARCH 必须是 arm64|amd64，得到: $ARCH" >&2; exit 1 ;;
esac

# 版本号校验：必须为纯数字版本，防止含 / 或空值污染文件名
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
    echo "ERROR: VERSION 非法（应为数字版本号，如 1.4.0），得到: '$VERSION'" >&2
    exit 1
fi

echo "==> pota_update build arch=$ARCH version=$VERSION"

# 本地中间目录：打包源为 $SCRIPT_DIR 下脚本文件，zip 条目以 pota_update_${VERSION}/ 为顶层，
# 与现场 `unzip 包; cp ota_update.sh 刷机包/` 的用法一致。
rm -rf "$SCRIPT_DIR/output" 2>/dev/null || true
mkdir -p "$SCRIPT_DIR/output/pota_update_${VERSION}"

# 主脚本（release 产物名为 ota_update.sh，源码文件为 ota.sh；用户部署时按 readme 自行改名）
cp "$SCRIPT_DIR/ota.sh" "$SCRIPT_DIR/output/pota_update_${VERSION}/ota_update.sh"
# 附加脚本与 arm64 二进制（bc 为 aarch64 ELF，仅 arm64 设备可用；amd64 设备依赖系统自带 bc）
cp "$SCRIPT_DIR/get_network_info.sh" "$SCRIPT_DIR/output/pota_update_${VERSION}/" 2>/dev/null || true
if [ "$ARCH" = "arm64" ]; then
  cp -r "$SCRIPT_DIR/arm64_bin" "$SCRIPT_DIR/output/pota_update_${VERSION}/" 2>/dev/null || true
fi

# 打包为带版本标识的整包（zip 优先，缺 zip 退 tar.gz）
PACKED=""
if command -v 7z >/dev/null 2>&1; then
  echo "found 7z"
  ( cd "$SCRIPT_DIR/output" && 7z a -y -mx9 "pota_update_${VERSION}.zip" "pota_update_${VERSION}" ) >/dev/null
  BUILD_RET=$?
  PACKED="$SCRIPT_DIR/output/pota_update_${VERSION}.zip"
elif command -v zip >/dev/null 2>&1; then
  echo "found zip"
  ( cd "$SCRIPT_DIR/output" && zip -r -9 "pota_update_${VERSION}.zip" "pota_update_${VERSION}" ) >/dev/null
  BUILD_RET=$?
  PACKED="$SCRIPT_DIR/output/pota_update_${VERSION}.zip"
elif command -v tar >/dev/null 2>&1; then
  echo "found tar"
  ( cd "$SCRIPT_DIR/output" && tar -czf "pota_update_${VERSION}.tgz" "pota_update_${VERSION}" ) >/dev/null
  BUILD_RET=$?
  PACKED="$SCRIPT_DIR/output/pota_update_${VERSION}.tgz"
else
  echo "ERROR: 需要 7z / zip / tar 之一来打包" >&2
  BUILD_RET=-1
fi

# 校验产物非空且内容含关键文件，防止错误 cwd 下静默产出空包仍被拷贝
if [ "$BUILD_RET" = "0" ]; then
  if [ ! -s "$PACKED" ] || [ ! -f "$SCRIPT_DIR/output/pota_update_${VERSION}/ota_update.sh" ]; then
    echo "ERROR: 打包产物缺失或为空（$PACKED），打包失败" >&2
    BUILD_RET=1
  else
    echo "打包 ok: $PACKED"
  fi
fi

# 统一接口：汇聚产物到 OUTPUT_DIR（校验通过才拷贝）
mkdir -p "$OUTPUT_DIR"
if [ "$BUILD_RET" = "0" ]; then
  cp "$SCRIPT_DIR/output/pota_update_${VERSION}/ota_update.sh" "$OUTPUT_DIR/"
  cp "$SCRIPT_DIR/output/pota_update_${VERSION}/get_network_info.sh" "$OUTPUT_DIR/" 2>/dev/null || true
  if [ "$ARCH" = "arm64" ]; then
    cp -r "$SCRIPT_DIR/output/pota_update_${VERSION}/arm64_bin" "$OUTPUT_DIR/" 2>/dev/null || true
  fi
  cp "$PACKED" "$OUTPUT_DIR/"
  echo "==> pota_update 完成, 产物: $OUTPUT_DIR"
  ls -la "$OUTPUT_DIR"
fi

exit $BUILD_RET
