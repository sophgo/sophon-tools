#!/bin/bash
# pSophUI 统一构建接口 (M1 规范 v0.1)
# 用法: bash release.sh [ARCH] [VERSION]
#   ARCH:    arm64（默认，设备 HDMI）
#   VERSION: 显式版本号（默认从 deb control 提取 1.6.8）
#   env OUTPUT_DIR: 产物目录（默认 <repo>/output/pSophUI/）
#   env QT_CROSS_PREFIX: aarch64 Qt 交叉安装前缀
#     默认 /env/qt_5.12.8_nosysroot（13.24 cross_build_sophon_u20 容器同款）
#   env CROSS_PREFIX: aarch64 交叉编译器前缀
#     默认 /usr（系统 apt aarch64-linux-gnu-gcc 9.4；Linaro GCC 6.3 已移除）
# 说明: 工程自带 lxqt qtermwidget arm64 静态库 + Makefile 为 qmake 生成物。
#       本脚本用 qmake 重新生成 Makefile（消除 /env/qt_fl2000 绝对路径依赖），
#       再 make 出 arm64 二进制并打 deb。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARCH="${1:-arm64}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/output/pSophUI}"

# 版本号默认从 deb control 提取（sophgo-hdmi_1.6.8_arm64.deb）
VERSION="${2:-$(grep -oE '[0-9]+\.[0-9]+\.[0-9]+' "$SCRIPT_DIR/SophUI/deb/DEBIAN/control" 2>/dev/null | head -1)}"
VERSION="${VERSION:-1.6.8}"

QT_CROSS_PREFIX="${QT_CROSS_PREFIX:-/env/qt_5.12.8_nosysroot}"
# 交叉编译器: 默认用系统 aarch64-linux-gnu-gcc（apt, GCC 9.4），替代原 Linaro GCC 6.3
# （Linaro 依赖已从统一镜像移除，见 docker/Dockerfile 的 WITH_SOPHUI 精简）
CROSS_PREFIX="${CROSS_PREFIX:-/usr}"

QMAKE="$QT_CROSS_PREFIX/bin/qmake"
CROSS_GCC="$CROSS_PREFIX/bin/aarch64-linux-gnu-gcc"

if [ "$ARCH" != "arm64" ]; then
  echo "ERROR: pSophUI 仅支持 arm64（设备 HDMI 交叉编译）" >&2
  exit 1
fi
if [ ! -x "$QMAKE" ]; then
  echo "ERROR: 未找到 aarch64 Qt qmake: $QMAKE" >&2
  echo "       需要交叉 Qt 环境（统一镜像内置 /env/qt_5.12.8_nosysroot）" >&2
  exit 2
fi
if [ ! -x "$CROSS_GCC" ]; then
  echo "ERROR: 未找到 aarch64 交叉编译器: $CROSS_GCC" >&2
  echo "       默认使用系统工具链（apt aarch64-linux-gnu-gcc）" >&2
  echo "       如用其它工具链: CROSS_PREFIX=<prefix> bash release.sh $ARCH" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR"
echo "==> pSophUI build arch=arm64 version=$VERSION (qmake=$QMAKE)"

BUILD_DIR="$SCRIPT_DIR/SophUI"
pushd "$BUILD_DIR" >/dev/null

  export PATH="$QT_CROSS_PREFIX/bin:$CROSS_PREFIX/bin:$PATH"
  export QMAKESPEC="${QT_CROSS_PREFIX}/mkspecs/linux-aarch64-gnu-g++"

  # 重新生成 Makefile（消除 Makefile 里硬编码的 /env/qt_fl2000 路径）
  rm -f Makefile
  "$QMAKE" SophUI.pro

  # 编译（post-link 的 upx 步骤失败仅告警，不影响二进制产出）
  # make 返回非零时可能只是尾部 upx 缺失（二进制已生成），也可能是真编译失败。
  # 以二进制 mtime 是否新于 Makefile 区分：真失败时残留旧二进制会早于刚生成的 Makefile。
  MAKE_RC=0
  make -j"$(nproc)" 2>&1 | tail -5 || MAKE_RC=1

  BIN="SophUI"
  if [ ! -f "$BIN" ]; then
    echo "ERROR: 未生成 $BIN" >&2
    exit 1
  fi
  if [ "$MAKE_RC" != "0" ]; then
    if [ "$BIN" -ot "Makefile" ]; then
      echo "ERROR: make 失败且二进制早于 Makefile（残留旧产物），中止打包" >&2
      exit 1
    fi
    echo "WARN: make 有非零退出（多为尾部 upx 缺失），二进制已更新，继续" >&2
  fi
  file "$BIN" | head -1

  # 打 deb：复制 deb 数据树到临时目录再修改，避免 sed -i 污染仓库跟踪的 control。
  # 二进制拷到与运行脚本/服务一致的 /bm_services/SophonHDMI/ 布局
  # （run_hdmi_show.sh、SophonHDMI.service 均从该路径启动 SophUI）。
  if [ -d deb ] && command -v dpkg-deb >/dev/null 2>&1; then
    DEB_TMP="$(mktemp -d "${TMPDIR:-/tmp}/pSophUI-deb.XXXXXX")"
    cp -a deb/. "$DEB_TMP/"
    DEST_DIR="$DEB_TMP/bm_services/SophonHDMI"
    mkdir -p "$DEST_DIR"
    cp -f "$BIN" "$DEST_DIR/"
    DEST_VER="${VERSION}"
    sed -i "s/1\.6\.8/${DEST_VER}/" "$DEB_TMP/DEBIAN/control"
    dpkg-deb --root-owner-group -b "$DEB_TMP" "$OUTPUT_DIR/sophgo-hdmi_${DEST_VER}_arm64.deb" 2>&1 | tail -2 || true
    rm -rf "$DEB_TMP"
    cp -f "$BIN" "$OUTPUT_DIR/SophUI_arm64"
  else
    cp -f "$BIN" "$OUTPUT_DIR/SophUI_arm64"
  fi

popd >/dev/null

echo "==> pSophUI 完成, 产物: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"
