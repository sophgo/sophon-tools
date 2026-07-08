#!/bin/bash
# sophliteos .deb 打包：把 tmp/（tgz 解压产物）装入 staging 数据树，dpkg-deb 输出。
# 用法: bash build/package-deb.sh <soc|pcie> [VERSION]
#   soc  → arm64（设备）；pcie → amd64（开发机）
#   VERSION 注入 control（默认 2.0.0）；产物 build/sophliteos_<PRODUCT>_<VERSION>.deb
#
# 在 staging 临时目录组装，避免把 control.bak/changelog 等源码模板打进 deb 控制归档。
set -e

TOP=$(dirname "$0")
SRC_DEBIAN="$TOP/sophliteos/DEBIAN"
PRODUCT="$1"
VERSION="${2:-2.0.0}"

if [ -z "$PRODUCT" ]; then
  echo "usage: package-deb.sh <soc|pcie> [VERSION]" >&2
  exit 1
fi

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
chmod 755 "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$STAGE/data/sophliteos"

# 控制文件：模板注入 Version + Architecture；仅拷运行时脚本（control.bak/changelog 不进 deb）
sed "s/@VERSION@/$VERSION/" "$SRC_DEBIAN/control.bak" > "$STAGE/DEBIAN/control"
if [ "$PRODUCT" = "soc" ]; then
  printf 'Architecture: arm64\n' >> "$STAGE/DEBIAN/control"
else
  PRODUCT=pcie
  printf 'Architecture: amd64\n' >> "$STAGE/DEBIAN/control"
fi
cp "$SRC_DEBIAN/postinst" "$SRC_DEBIAN/preinst" "$SRC_DEBIAN/prerm" "$SRC_DEBIAN/postrm" "$STAGE/DEBIAN/"

# 数据：tgz 解压产物（sophliteos 二进制/dist/config/service/install.sh 等）
cp -r "$TOP/tmp/"* "$STAGE/data/sophliteos/"

# md5sums（仅数据文件，路径对齐安装后绝对路径去掉前导 /，即 data/sophliteos/...）
( cd "$STAGE" && find data -type f -print0 | sort -z | xargs -0 md5sum ) \
  > "$STAGE/DEBIAN/md5sums"

chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/preinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"
chmod 0644 "$STAGE/DEBIAN/control" "$STAGE/DEBIAN/md5sums"

# 打包（--root-owner-group 让数据树属主 root:root）
OUT="$TOP/sophliteos_${PRODUCT}_${VERSION}.deb"
dpkg-deb --root-owner-group -b "$STAGE" "$OUT"
echo "✓ built $OUT"
