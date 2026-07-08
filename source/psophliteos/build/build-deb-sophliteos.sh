#!/bin/bash
# sophliteos .deb 打包（docker-free）：本地 pnpm 构建前端 + go 交叉编译 + dpkg-deb。
# 用法: bash build/build-deb-sophliteos.sh [VERSION] [soc|pcie]
#   VERSION 默认 2.0.0
#   soc=arm64（设备，默认）；pcie=amd64（开发机）
# 产物: release/sophliteos_<PRODUCT>_<VERSION>.deb
#
# 与 build/build_2_release.sh 的区别：不依赖 docker 构建 frontend，直接用本地 pnpm；
# 便于在无 docker 环境复现，且 VERSION 可注入到 control。
set -e

cd "$(dirname "$0")/.."
VERSION="${1:-2.0.0}"
PRODUCT="${2:-soc}"

if [ "$PRODUCT" != "soc" ] && [ "$PRODUCT" != "pcie" ]; then
  echo "PRODUCT 必须是 soc 或 pcie" >&2
  exit 1
fi

# 1. 版本信息（release_version.txt 落到项目根，供 package.sh 打入 tgz）
bash build/version.sh "V$VERSION"
[ -f build/release_version.txt ] && mv -f build/release_version.txt .

# 2. 前端 dist（本地 pnpm，不依赖 docker；无 node_modules 时自动 install）
cd frontend
if [ ! -d node_modules ]; then
  pnpm install 2>/dev/null || yarn install
fi
pnpm run build 2>/dev/null || yarn build
cd ..
cp -r frontend/dist .

# 3. go 交叉编译 + tar（scrip/package.sh 产出 sophliteos-linux_{arm64,amd64}.tgz）
bash scrip/package.sh

# 4. 解压目标架构 tgz 到 build/tmp，组装 deb
rm -rf build/tmp
mkdir -p build/tmp release
TGZ="sophliteos-linux_arm64.tgz"
[ "$PRODUCT" = "pcie" ] && TGZ="sophliteos-linux_amd64.tgz"
tar -xzf "$TGZ" -C build/tmp
bash build/package-deb.sh "$PRODUCT" "$VERSION"

# 5. 归档产物到 release/
OUT="release/sophliteos_${PRODUCT}_${VERSION}.deb"
mv -f "build/sophliteos_${PRODUCT}_${VERSION}.deb" "$OUT"

# 6. 清理项目根的临时构建产物（保留 release/ 与源码）
rm -rf dist sophliteos sophliteos-linux_*.tgz install.sh uninstall.sh upgrade.sh sophliteos.service release_version.txt build/tmp

echo
echo "✓ built $OUT"
dpkg-deb -f "$OUT" Package Version Architecture Maintainer
echo "--- contents (top) ---"
dpkg-deb -c "$OUT" | head -8
