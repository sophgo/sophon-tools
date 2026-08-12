#!/usr/bin/env bash
# se-rag-core 统一构建接口 (对齐 sophon-tools M1 规范)
# 用法: bash release.sh [ARCH] [VERSION]
#   ARCH:    arm64 | amd64 | all（默认 all）
#   VERSION: 显式版本号（默认 1.0.0）
#   env OUTPUT_DIR: 产物目录（默认 <repo>/output/se-rag-core/）
# 产物: se-rag-linux-<arch>-<ver> （静态二进制，CGO_ENABLED=0）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARCH="${1:-all}"
VERSION="${2:-1.0.0}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/output/se-rag-core}"

mkdir -p "$OUTPUT_DIR"

build_one() {
  local arch="$1"
  echo "==> se-rag build GOARCH=$arch version=$VERSION"
  (cd "$SCRIPT_DIR" && GOOS=linux GOARCH="$arch" CGO_ENABLED=0 go build \
     -trimpath -ldflags "-s -w" \
     -o "$OUTPUT_DIR/se-rag-linux-$arch-$VERSION" ./cmd/se-rag)
}

case "$ARCH" in
  arm64) build_one arm64 ;;
  amd64) build_one amd64 ;;
  all)   build_one arm64 ; build_one amd64 ;;
  *) echo "ERROR: ARCH 必须是 arm64|amd64|all，得到: $ARCH" >&2; exit 1 ;;
esac

echo "==> done: $OUTPUT_DIR"
ls -lh "$OUTPUT_DIR"
