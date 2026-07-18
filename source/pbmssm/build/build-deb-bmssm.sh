#!/bin/bash
# bmssm .deb 打包：交叉编译 arm64 静态二进制 + 组装 deb 数据树 + dpkg-deb。
# 用法: bash build/build-deb-bmssm.sh [VERSION] [ARCH]
#   VERSION 默认 2.1.0（与 build/version.sh 一致）
#   ARCH   默认 arm64（设备）；amd64 用于 PCIE/开发机
# 产物: release/bmssm_${VERSION}_${ARCH}.deb
set -e

cd "$(dirname "$0")/.."
VERSION="${1:-2.1.0}"
ARCH="${2:-arm64}"

# 1. 交叉编译静态二进制 + 打包 bmssm.yaml 到 release/
#    arm64 走 musl 静态；amd64 用宿主 gcc 动态链接（开发机用）
if [ "$ARCH" = "arm64" ]; then
  bash build/build-bmssm-arm64.sh "$VERSION"
else
  bash build/build-bmssm.sh "$VERSION"
fi

# 2. 组装 deb 数据树（绝对路径布局，postinst 建运行目录）
DEBROOT=build/deb/bmssm-root
rm -rf "$DEBROOT"
mkdir -p "$DEBROOT/DEBIAN" \
         "$DEBROOT/opt/sophon/bmssm/bin" \
         "$DEBROOT/opt/sophon/bmssm/config" \
         "$DEBROOT/usr/lib/systemd/system"

cp release/bmssm "$DEBROOT/opt/sophon/bmssm/bin/bmssm"
chmod 0755 "$DEBROOT/opt/sophon/bmssm/bin/bmssm"
cp release/bmssm.yaml "$DEBROOT/opt/sophon/bmssm/config/bmssm.yaml"
cp build/bmssm.service "$DEBROOT/usr/lib/systemd/system/bmssm.service"

# 3. DEBIAN 控制文件（Version/Architecture 注入）
sed -e "s/@VERSION@/$VERSION/" -e "s/@ARCH@/$ARCH/" \
  build/deb/bmssm.control > "$DEBROOT/DEBIAN/control"
cp build/deb/postinst "$DEBROOT/DEBIAN/postinst"
cp build/deb/prerm    "$DEBROOT/DEBIAN/prerm"
cp build/deb/postrm   "$DEBROOT/DEBIAN/postrm"
cp build/deb/conffiles "$DEBROOT/DEBIAN/conffiles"
chmod 0755 "$DEBROOT/DEBIAN/postinst" "$DEBROOT/DEBIAN/prerm" "$DEBROOT/DEBIAN/postrm"
chmod 0644 "$DEBROOT/DEBIAN/control" "$DEBROOT/DEBIAN/conffiles"

# 4. md5sums（数据文件校验和，路径不含前导 /，对齐 deb policy）
( cd "$DEBROOT" && find . -type f ! -path './DEBIAN/*' -printf '%P\0' | \
  sort -z | xargs -0 md5sum ) > "$DEBROOT/DEBIAN/md5sums"

# 5. 打包
mkdir -p release
OUT="release/bmssm_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group -b "$DEBROOT" "$OUT"
rm -rf "$DEBROOT"

echo
echo "✓ built $OUT"
dpkg-deb -f "$OUT" Package Version Architecture Maintainer
echo "--- contents ---"
dpkg-deb -c "$OUT" | grep -vE '/$'
