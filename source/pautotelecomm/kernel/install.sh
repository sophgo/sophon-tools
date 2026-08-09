#!/bin/bash
# pautotelecomm 内核模块安装脚本（在设备端以 root 执行）
# 设备端安装: bash install.sh [KERNEL_HEADERS_SCRIPT]
#   可选参数 KERNEL_HEADERS_SCRIPT: 内核头缺失时用于安装内核头的脚本路径
#   （如开发机 bsp-debs 的 linux-headers-install.sh）；缺省则直接报错并提示。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
KERNEL_HEADERS_SCRIPT="${1:-}"

if [ "$(id -u)" != "0" ]; then
    echo "ERROR: 需要 root 权限执行（安装将写入 /lib/modules 并注册内核模块）" >&2
    echo "       请以 root 身份执行: sudo bash $0 ${KERNEL_HEADERS_SCRIPT:+$KERNEL_HEADERS_SCRIPT}" >&2
    exit 1
fi

if [[ "$(modinfo cdc-wdm 2>/dev/null | wc -l)" != "0" ]] && \
   [[ "$(modinfo qmi_wwan 2>/dev/null | wc -l)" != "0" ]] && \
   [[ "$(modinfo qmi_wwan_q 2>/dev/null | wc -l)" != "0" ]]; then
    echo "cdc-wdm, qmi_wwan, qmi_wwan_q installed"
    exit 0
fi

export KSRC=/lib/modules/$(uname -r)/build
export ARCH=arm64
export CROSS_COMPILE="${CROSS_COMPILE:-}"
# 仓库内无 include/platform 目录，仅当存在时追加，避免 CFLAGS 指向空路径
export USER_EXTRA_CFLAGS=""
if [ -d "$SCRIPT_DIR/include" ]; then
    USER_EXTRA_CFLAGS="-I$SCRIPT_DIR/include"
fi
if [ -d "$SCRIPT_DIR/platform" ]; then
    USER_EXTRA_CFLAGS="$USER_EXTRA_CFLAGS -I$SCRIPT_DIR/platform"
fi

if [ ! -d "$KSRC" ]; then
    if [ -n "$KERNEL_HEADERS_SCRIPT" ] && [ -x "$KERNEL_HEADERS_SCRIPT" ]; then
        echo "[install kernel headers] 执行 $KERNEL_HEADERS_SCRIPT ..."
        bash "$KERNEL_HEADERS_SCRIPT"
    else
        echo "ERROR: 未找到内核头目录 $KSRC" >&2
        echo "       当前设备缺少内核开发头文件（linux-headers），无法编译/安装内核模块。" >&2
        echo "       请先安装与当前内核 $(uname -r) 匹配的 linux-headers 包，" >&2
        echo "       或提供内核头安装脚本: bash install.sh /path/to/linux-headers-install.sh" >&2
        exit 1
    fi
fi
if [ ! -d "$KSRC" ]; then
    echo "ERROR: 安装内核头后仍未找到内核头目录 $KSRC" >&2
    exit 1
fi

# 本脚本已要求 root 执行，直接以当前身份运行 make install（不依赖 sudo 可用/免密）
pushd "$SCRIPT_DIR/cdc_wdm" || exit 1

make clean
make
make install
make clean

popd

modprobe cdc-wdm 2>/dev/null || echo "WARN: modprobe cdc-wdm 失败（模块可能需重启后加载）"

pushd "$SCRIPT_DIR/qmi_wwan" || exit 1

make clean
make
make install
make clean

popd

echo "==> autotelecomm 内核模块安装完成，请重启设备"
