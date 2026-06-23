#!/bin/bash

cp scrip/sophliteos.service scrip/install.sh  scrip/uninstall.sh scrip/upgrade.sh .

CGO_ENABLED=1 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags '-s -w'  && tar -zcvf sophliteos-linux_amd64.tgz sophliteos \
    dist \
    config/sophliteos.yaml \
    database/sophliteos.db \
    sophliteos.service \
    install.sh \
    uninstall.sh \
    release_version.txt \
    upgrade.sh
# arm64: 切换到 musl 静态链接,消除对目标设备 glibc 版本的依赖
MUSL_BIN="$(bash "$(dirname "$0")/../build/fetch-musl-toolchain.sh")"
[ -n "$MUSL_BIN" ] && export PATH="$MUSL_BIN:$PATH"

CGO_ENABLED=1 GOOS=linux GOARCH=arm64 \
  CC=aarch64-linux-musl-gcc \
  CXX=aarch64-linux-musl-g++ \
  go build -trimpath \
    -tags 'netgo osusergo sqlite_omit_load_extension' \
    -ldflags '-s -w -linkmode external -extldflags "-static"' \
  && tar -zcvf sophliteos-linux_arm64.tgz sophliteos \
    dist \
    config/sophliteos.yaml \
    database/sophliteos.db \
    sophliteos.service \
    install.sh \
    uninstall.sh \
    release_version.txt \
    upgrade.sh \
  || { echo "ERROR: arm64 构建/打包失败,见上方 go build 输出"; exit 1; }

# 静态链接门禁:arm64 产物必须是全静态,否则会在旧 glibc 设备上报 GLIBC 符号缺失
file sophliteos | grep -q 'statically linked' \
  || { echo "ERROR: arm64 产物不是静态链接,检查 musl 工具链与 extldflags"; exit 1; }
echo "arm64 产物静态链接校验通过"

rm sophliteos.service install.sh  uninstall.sh upgrade.sh 