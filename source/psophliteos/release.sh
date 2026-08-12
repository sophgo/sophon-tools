#!/bin/bash
# psophliteos 统一构建接口 (M1 规范 v0.1)
# 用法: bash release.sh [ARCH] [VERSION]
#   ARCH:    arm64(soc) | amd64(pcie) | all（默认 arm64）
#   VERSION: 显式版本号（默认 2.1.0，与 build/version.sh 一致）
#   env OUTPUT_DIR: 产物目录（默认 <repo>/output/psophliteos/）
# 产物: sophliteos_soc_<ver>.deb + sophliteos_pcie_<ver>.deb（单文件二进制，前端 go:embed 内嵌）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARCH="${1:-arm64}"
VERSION="${2:-2.1.0}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/output/psophliteos}"

case "$ARCH" in
  arm64) PRODUCT_LIST="soc" ;;
  amd64) PRODUCT_LIST="pcie" ;;
  all)   PRODUCT_LIST="soc pcie" ;;
  *) echo "ERROR: ARCH 必须是 arm64|amd64|all，得到: $ARCH" >&2; exit 1 ;;
esac

mkdir -p "$OUTPUT_DIR"

# pnpm install/run 会在 lock 与 package.json 不一致时改写 frontend/pnpm-lock.yaml
# （该文件被 git 跟踪），导致每次统一构建弄脏工作区（docker 挂载源码树）。
# 构建前备份、退出时还原，保证构建不影响 git 工作区。
LOCKFILE="$SCRIPT_DIR/frontend/pnpm-lock.yaml"
LOCKFILE_BACKUP=""
if [ -f "$LOCKFILE" ]; then
  LOCKFILE_BACKUP="$(mktemp)"
  cp "$LOCKFILE" "$LOCKFILE_BACKUP"
fi
restore_lockfile() {
  if [ -n "$LOCKFILE_BACKUP" ] && [ -f "$LOCKFILE_BACKUP" ]; then
    cp "$LOCKFILE_BACKUP" "$LOCKFILE" 2>/dev/null || true
    rm -f "$LOCKFILE_BACKUP"
  fi
}
trap restore_lockfile EXIT

# 前端依赖预装：build-deb-sophliteos.sh 内 pnpm 失败会退到 yarn（慢且易挂），
# 这里先用 pnpm --no-frozen-lockfile 显式装好（M2 实测路径），node_modules 复用。
prepare_frontend() {
  local fe="$SCRIPT_DIR/frontend"
  if [ ! -d "$fe/node_modules" ]; then
    echo "==> 前端依赖 pnpm install ..."
    (cd "$fe" && rm -rf node_modules && CI=true pnpm install --no-frozen-lockfile) \
      || (cd "$fe" && CI=true npm install --no-frozen-lockfile 2>/dev/null) \
      || { echo "ERROR: 前端依赖安装失败" >&2; exit 1; }
  else
    echo "==> 前端 node_modules 已存在, 复用"
  fi
}

prepare_frontend

build_one() {
  local product="$1"
  echo "==> psophliteos build product=$product version=$VERSION"
  bash build/build-deb-sophliteos.sh "$VERSION" "$product"
  local deb="release/sophliteos_${product}_${VERSION}.deb"
  if [ ! -f "$deb" ]; then
    echo "ERROR: 未找到产物 $deb" >&2
    exit 1
  fi
  cp "$deb" "$OUTPUT_DIR/"
  file "$deb" | head -1
}

for p in $PRODUCT_LIST; do build_one "$p"; done

echo "==> psophliteos 完成, 产物: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"
