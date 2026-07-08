#!/bin/bash
# ssm .deb 打包：交叉编译 arm64 静态二进制 + 组装 deb 数据树 + dpkg-deb。
# 用法: bash build/build-deb-ssm.sh [VERSION] [ARCH]
#   VERSION 默认 2.0.0（与 build/version.sh 一致）
#   ARCH   默认 arm64（设备）；amd64 用于 PCIE/开发机
# 产物: release/ssm_${VERSION}_${ARCH}.deb
set -e

cd "$(dirname "$0")/.."
VERSION="${1:-2.0.0}"
ARCH="${2:-arm64}"

# 1. 交叉编译静态二进制 + 打包 ssm.yaml 到 release/
#    arm64 走 musl 静态；amd64 用宿主 gcc 动态链接（开发机用）
if [ "$ARCH" = "arm64" ]; then
  bash build/build-ssm-arm64.sh "$VERSION"
else
  bash build/build-ssm.sh "$VERSION"
fi

# 2. 组装 deb 数据树（绝对路径布局，postinst 建运行目录）
DEBROOT=build/deb/ssm-root
rm -rf "$DEBROOT"
mkdir -p "$DEBROOT/DEBIAN" \
         "$DEBROOT/opt/sophon/ssm/bin" \
         "$DEBROOT/opt/sophon/ssm/config" \
         "$DEBROOT/etc/systemd/system"

cp release/ssm "$DEBROOT/opt/sophon/ssm/bin/ssm"
chmod 0755 "$DEBROOT/opt/sophon/ssm/bin/ssm"
cp release/ssm.yaml "$DEBROOT/opt/sophon/ssm/config/ssm.yaml"
cp build/ssm.service "$DEBROOT/etc/systemd/system/ssm.service"

# 3. DEBIAN 控制文件（Version/Architecture 注入）
sed -e "s/@VERSION@/$VERSION/" -e "s/@ARCH@/$ARCH/" \
  build/deb/ssm.control > "$DEBROOT/DEBIAN/control"
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
OUT="release/ssm_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group -b "$DEBROOT" "$OUT"
rm -rf "$DEBROOT"

echo
echo "✓ built $OUT"
dpkg-deb -f "$OUT" Package Version Architecture Maintainer
echo "--- contents ---"
dpkg-deb -c "$OUT" | grep -vE '/$'
