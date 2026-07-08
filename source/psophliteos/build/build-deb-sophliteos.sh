#!/bin/bash
# sophliteos .deb 打包（docker-free）：pnpm 前端 + go 交叉编译 + dpkg-deb。
# 用法: bash build/build-deb-sophliteos.sh [VERSION] [soc|pcie]
#   VERSION 默认 2.0.0
#   soc=arm64（设备，默认）；pcie=amd64（开发机）
# 产物: release/sophliteos_<PRODUCT>_<VERSION>.deb
#
# 规范化打包：数据树按最终路径布局（/opt/sophon/sophliteos、/etc/systemd），
# dpkg 直接追踪所有文件；postinst 仅建运行时目录 + systemd enable/restart，不再散布/复制文件。
# db 文件由 app 首次启动自动创建（/var/lib/sophliteos/db），属运行时状态，不打包。
set -e

cd "$(dirname "$0")/.."
VERSION="${1:-2.0.0}"
PRODUCT="${2:-soc}"
if [ "$PRODUCT" != "soc" ] && [ "$PRODUCT" != "pcie" ]; then
  echo "PRODUCT 必须是 soc 或 pcie" >&2; exit 1
fi
ARCH="$([ "$PRODUCT" = "pcie" ] && echo amd64 || echo arm64)"

# 1. 版本信息（release_version.txt 落到项目根，供数据树打包）
bash build/version.sh "V$VERSION"

# 2. 前端 dist（本地 pnpm，无 docker；无 node_modules 时自动 install）
cd frontend
if [ ! -d node_modules ]; then
  pnpm install 2>/dev/null || yarn install
fi
pnpm run build 2>/dev/null || yarn build
cd ..
cp -r frontend/dist dist

# 3. go 交叉编译（arm64 走 musl 静态；amd64 宿主 gcc 动态）
if [ "$ARCH" = "arm64" ]; then
  MUSL_BIN="$(bash build/fetch-musl-toolchain.sh)"
  [ -n "$MUSL_BIN" ] && export PATH="$MUSL_BIN:$PATH"
  CGO_ENABLED=1 GOOS=linux GOARCH=arm64 \
    CC=aarch64-linux-musl-gcc CXX=aarch64-linux-musl-g++ \
    go build -trimpath \
      -tags 'netgo osusergo sqlite_omit_load_extension' \
      -ldflags '-s -w -linkmode external -extldflags "-static"'
  file sophliteos | grep -q 'statically linked' \
    || { echo "ERROR: arm64 产物不是静态链接，检查 musl 工具链与 extldflags"; exit 1; }
else
  CGO_ENABLED=1 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags '-s -w'
fi

# 4. 组装数据树（最终绝对路径布局，dpkg 直接追踪）
STAGE=build/stage
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" \
         "$STAGE/opt/sophon/sophliteos/bin" \
         "$STAGE/opt/sophon/sophliteos/config" \
         "$STAGE/opt/sophon/sophliteos/dist" \
         "$STAGE/usr/lib/systemd/system"
install -m 0755 sophliteos "$STAGE/opt/sophon/sophliteos/bin/sophliteos"
install -m 0644 scrip/sophliteos.service "$STAGE/usr/lib/systemd/system/sophliteos.service"
install -m 0644 config/sophliteos.yaml "$STAGE/opt/sophon/sophliteos/config/sophliteos.yaml"
cp -r dist/. "$STAGE/opt/sophon/sophliteos/dist/"
install -m 0644 release_version.txt "$STAGE/opt/sophon/sophliteos/release_version.txt"

# 5. DEBIAN 控制信息（模板注入 Version + Architecture）
SRC_DEBIAN=build/sophliteos/DEBIAN
sed "s/@VERSION@/$VERSION/" "$SRC_DEBIAN/control.bak" > "$STAGE/DEBIAN/control"
printf 'Architecture: %s\n' "$ARCH" >> "$STAGE/DEBIAN/control"
cp "$SRC_DEBIAN/conffiles" "$STAGE/DEBIAN/conffiles"
cp "$SRC_DEBIAN/postinst" "$STAGE/DEBIAN/postinst"
cp "$SRC_DEBIAN/prerm"    "$STAGE/DEBIAN/prerm"
cp "$SRC_DEBIAN/postrm"   "$STAGE/DEBIAN/postrm"
# md5sums（仅数据文件，路径去前导 ./，对齐 deb policy）
( cd "$STAGE" && find . -type f ! -path './DEBIAN/*' -printf '%P\0' | sort -z | xargs -0 md5sum ) \
  > "$STAGE/DEBIAN/md5sums"
chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"
chmod 0644 "$STAGE/DEBIAN/control" "$STAGE/DEBIAN/conffiles" "$STAGE/DEBIAN/md5sums"

# 6. 打包（--root-owner-group 让数据树属主 root:root）
mkdir -p release
OUT="release/sophliteos_${PRODUCT}_${VERSION}.deb"
dpkg-deb --root-owner-group -b "$STAGE" "$OUT"

# 7. 清理项目根临时构建产物（保留 release/ 与源码）
rm -rf dist sophliteos release_version.txt build/stage

echo
echo "✓ built $OUT"
dpkg-deb -f "$OUT" Package Version Architecture Maintainer
echo "--- contents (top) ---"
dpkg-deb -c "$OUT" | head -10
