#!/bin/bash
# sophliteos .deb 打包（docker-free）：pnpm 前端 + go 交叉编译（前端 go:embed 内嵌）+ dpkg-deb。
# 用法: bash build/build-deb-sophliteos.sh [VERSION] [soc|pcie]
#   VERSION 默认 2.1.0
#   soc=arm64（设备，默认）；pcie=amd64（开发机）
# 产物: release/sophliteos_<PRODUCT>_<VERSION>.deb（单文件二进制，前端内嵌）
#
# 规范化打包：前端静态资源在 go build 阶段经 //go:embed dist 打进二进制，
# 数据树只含 二进制 + config + systemd 服务，不再单独安装 dist 目录。
# dpkg 直接追踪所有文件；postinst 仅建运行时目录 + systemd enable/restart。
# db 文件由 app 首次启动自动创建（/var/lib/sophliteos/db），属运行时状态，不打包。
set -e

cd "$(dirname "$0")/.."
VERSION="${1:-2.1.0}"
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
  pnpm install || yarn install
fi
pnpm run build || yarn build
cd ..
# 合入内嵌暂存目录 dist/（覆盖占位的 dist/index.html），go:embed 即在下一步编译期把整套前端打进二进制
cp -r frontend/dist/. dist/

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
# 前端已内嵌到二进制，deb 只带 二进制 + 配置 + systemd 服务，不再单独打包 dist 目录。
STAGE=build/stage
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" \
         "$STAGE/opt/sophon/sophliteos/bin" \
         "$STAGE/opt/sophon/sophliteos/config" \
         "$STAGE/usr/lib/systemd/system"
install -m 0755 sophliteos "$STAGE/opt/sophon/sophliteos/bin/sophliteos"
install -m 0644 scrip/sophliteos.service "$STAGE/usr/lib/systemd/system/sophliteos.service"
install -m 0644 config/sophliteos.yaml "$STAGE/opt/sophon/sophliteos/config/sophliteos.yaml"
install -m 0644 release_version.txt "$STAGE/opt/sophon/sophliteos/release_version.txt"

# 5. DEBIAN 控制信息（模板注入 Version + Architecture；@ARCH@ 位于 Description 前，
#    符合 deb-policy 字段序，不再追加到 control 尾部）
SRC_DEBIAN=build/sophliteos/DEBIAN
sed -e "s/@VERSION@/$VERSION/" -e "s/@ARCH@/$ARCH/" "$SRC_DEBIAN/control.bak" > "$STAGE/DEBIAN/control"
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

# 7. 清理项目根临时构建产物；把内嵌暂存目录 dist/ 重置为只含占位 index.html，
#    使 git 跟踪的 dist/index.html 保持原样（真实前端产物仅留在 frontend/dist）。
rm -f sophliteos release_version.txt
rm -rf build/stage dist
mkdir -p dist
# 重写占位内容，与 git 跟踪的 dist/index.html 保持一致，构建后工作区不产生 dirty 差异。
cat > dist/index.html <<'PLACEHOLDER_EOF'
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>SophLiteOS</title>
</head>
<body>
  <p>SophLiteOS 前端未构建。请通过 sophliteos 统一构建流程生成 dist 后再 go build。</p>
</body>
</html>
PLACEHOLDER_EOF

echo
echo "✓ built $OUT"
dpkg-deb -f "$OUT" Package Version Architecture Maintainer
echo "--- contents (top) ---"
dpkg-deb -c "$OUT" | head -10
