#!/bin/bash
# psophliteos 统一构建接口 (M1 规范 v0.1)
# 用法: bash release.sh [ARCH] [VERSION]
#   ARCH:    arm64(soc) | amd64(pcie) | all（默认 arm64）
#   VERSION: 显式版本号（默认从 build/version.sh DEFAULT_VERSION 提取）
#   env OUTPUT_DIR: 产物目录（默认 <repo>/output/psophliteos/）
# 产物: sophliteos_soc_<ver>.deb + sophliteos_pcie_<ver>.deb（单文件二进制，前端 go:embed 内嵌）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARCH="${1:-arm64}"
# 版本默认值从 build/version.sh 的 DEFAULT_VERSION（唯一权威）提取，禁止在此硬编码
VERSION="${2:-$(grep -oE '^DEFAULT_VERSION="[^"]+"' "$SCRIPT_DIR/build/version.sh" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')}"
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
  # 两个构建环境兼容点（CV84X2 真机验证踩坑记录，2026-08-26）：
  # ① pnpm-workspace.yaml 仅含 pnpm 10 的 allowBuilds 字段（无 packages:），pnpm 9 会把
  #    它当 workspace 根解析并报 "packages field missing or empty"——pnpm<10 时构建期
  #    临时移开，装完还原（pnpm 10 下该文件合法且被消费，不动）。
  # ② husky 的 prepare 脚本在 docker 挂载源码树里找不到 .git，HUSKY=0 跳过。
  local ws="$fe/pnpm-workspace.yaml" ws_bak=""
  if [ -f "$ws" ] && ! grep -qE '^[[:space:]]*packages:' "$ws"; then
    local pnpm_major
    pnpm_major="$(pnpm --version 2>/dev/null | cut -d. -f1 || true)"
    if [ -z "$pnpm_major" ] || [ "$pnpm_major" -lt 10 ] 2>/dev/null; then
      ws_bak="${ws}.release-bak"
      mv "$ws" "$ws_bak"
      echo "==> pnpm<10 且 workspace 文件无 packages 字段, 构建期临时移开 $ws"
    fi
  fi
  # husky v7 的 prepare("husky install") 在 docker 挂载源码树内找不到 .git 导致安装失败
  # （HUSKY=0/HUSKY_SKIP_INSTALL 对 v7 均无效），构建期把它替换为 no-op，装完还原。
  local pkg="$fe/package.json" pkg_bak=""
  if grep -q '"prepare"[[:space:]]*:[[:space:]]*"husky' "$pkg" 2>/dev/null; then
    pkg_bak="${pkg}.release-bak"
    cp "$pkg" "$pkg_bak"
    node -e "const fs=require('fs'),p=process.argv[1];const j=JSON.parse(fs.readFileSync(p,'utf8'));j.scripts.prepare='node -e 0';fs.writeFileSync(p,JSON.stringify(j,null,2)+'\n')" "$pkg"
    echo "==> 构建期临时替换 husky prepare 钩子为 no-op"
  fi
  if [ ! -d "$fe/node_modules" ]; then
    echo "==> 前端依赖 pnpm install ..."
    (cd "$fe" && rm -rf node_modules && CI=true pnpm install --no-frozen-lockfile) \
      || (cd "$fe" && CI=true npm install --no-frozen-lockfile 2>/dev/null) \
      || { [ -n "$ws_bak" ] && mv "$ws_bak" "$ws"; [ -n "$pkg_bak" ] && mv "$pkg_bak" "$pkg"; \
           echo "ERROR: 前端依赖安装失败" >&2; exit 1; }
  else
    echo "==> 前端 node_modules 已存在, 复用"
  fi
  [ -n "$ws_bak" ] && mv "$ws_bak" "$ws"
  [ -n "$pkg_bak" ] && mv "$pkg_bak" "$pkg"
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
