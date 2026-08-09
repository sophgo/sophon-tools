#!/bin/bash
# pspacc_efuse_demo 统一构建接口 (M1 规范 v0.1)
# 用法: bash release.sh [ARCH] [VERSION]
#   ARCH:    amd64|arm64|all（默认 amd64；arm64 走交叉编译；all 依次构建双架构）
#   VERSION: 无版本号（保留参数兼容）
#   env OUTPUT_DIR: 产物目录（默认 <repo>/output/pspacc_efuse_demo/）
# 产物: 单 arch 输出 spacc_efuse_demo；all 输出 spacc_efuse_demo_<arch>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$SCRIPT_DIR"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARCH="${1:-amd64}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/output/pspacc_efuse_demo}"

case "$ARCH" in
  amd64|arm64) ;;
  all) ARCH_LIST="amd64 arm64" ;;
  *) echo "ERROR: ARCH 必须是 amd64|arm64|all，得到: $ARCH" >&2; exit 1 ;;
esac

mkdir -p "$OUTPUT_DIR"

build_one() {
  local arch="$1"
  local bin="spacc_efuse_demo"
  if [ "$ARCH" = "all" ]; then
    bin="spacc_efuse_demo_$arch"
  fi
  echo "==> pspacc_efuse_demo gcc 编译 arch=$arch"
  case "$arch" in
    amd64)
      gcc spacc_efuse_demo.c -o "$OUTPUT_DIR/$bin"
      ;;
    arm64)
      CC="${CC:-aarch64-linux-gnu-gcc}"
      if ! command -v "$CC" >/dev/null 2>&1; then
        echo "ERROR: 交叉编译器 $CC 不可用" >&2; exit 1
      fi
      "$CC" -march=armv8-a spacc_efuse_demo.c -o "$OUTPUT_DIR/$bin"
      ;;
  esac
  chmod +x "$OUTPUT_DIR/$bin"
  file "$OUTPUT_DIR/$bin" | head -1
}

if [ -n "${ARCH_LIST:-}" ]; then
  for a in $ARCH_LIST; do build_one "$a"; done
else
  build_one "$ARCH"
fi

echo "==> pspacc_efuse_demo 完成, 产物: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"
