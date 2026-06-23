#!/bin/sh
# 确保 aarch64-linux-musl 交叉工具链可用。
# - 若系统 PATH 中已有 aarch64-linux-musl-gcc,直接退出(不输出,沿用系统工具链)。
# - 否则从 musl.cc 下载预构建工具链到 build/toolchain/,校验 SHA256,解压后输出 bin 目录路径
#   (供调用方加入 PATH)。
#
# 可重复性:设置环境变量 MUSL_TOOLCHAIN_SHA256 固定下载内容哈希。
# 首次下载时该变量留空会在 stderr 打印当前 sha256,填回即可固定。
set -e

TOOLCHAIN_NAME="aarch64-linux-musl-cross"
TOOLCHAIN_URL="https://musl.cc/${TOOLCHAIN_NAME}.tgz"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLCHAIN_ROOT="${MUSL_TOOLCHAIN_ROOT:-${SCRIPT_DIR}/toolchain}"
TOOLCHAIN_DIR="${TOOLCHAIN_ROOT}/${TOOLCHAIN_NAME}"
EXPECTED_SHA256="${MUSL_TOOLCHAIN_SHA256:-}"

# 1) 系统 PATH 已有该工具链,直接退出(不输出,沿用系统)
if command -v aarch64-linux-musl-gcc >/dev/null 2>&1; then
  exit 0
fi

# 2) 已下载并解压,直接输出 bin 路径
if [ -x "${TOOLCHAIN_DIR}/bin/aarch64-linux-musl-gcc" ]; then
  echo "${TOOLCHAIN_DIR}/bin"
  exit 0
fi

mkdir -p "${TOOLCHAIN_ROOT}"
ARCHIVE="${TOOLCHAIN_ROOT}/${TOOLCHAIN_NAME}.tgz"

echo "下载 musl 交叉工具链: ${TOOLCHAIN_URL}"
if command -v curl >/dev/null 2>&1; then
  curl -fL -o "${ARCHIVE}" "${TOOLCHAIN_URL}"
elif command -v wget >/dev/null 2>&1; then
  wget -O "${ARCHIVE}" "${TOOLCHAIN_URL}"
else
  echo "ERROR: 需要 curl 或 wget 之一" >&2
  exit 1
fi

ACTUAL_SHA256="$(sha256sum "${ARCHIVE}" | awk '{print $1}')"

if [ -z "${EXPECTED_SHA256}" ]; then
  echo "WARN: 未固定工具链 SHA256。将 MUSL_TOOLCHAIN_SHA256 环境变量设为下方值可固定:" >&2
  echo "      ${ACTUAL_SHA256}" >&2
else
  if [ "${ACTUAL_SHA256}" != "${EXPECTED_SHA256}" ]; then
    echo "ERROR: 工具链 SHA256 不匹配" >&2
    echo "  期望: ${EXPECTED_SHA256}" >&2
    echo "  实际: ${ACTUAL_SHA256}" >&2
    rm -f "${ARCHIVE}"
    exit 1
  fi
fi

tar -xzf "${ARCHIVE}" -C "${TOOLCHAIN_ROOT}"
rm -f "${ARCHIVE}"

if [ ! -x "${TOOLCHAIN_DIR}/bin/aarch64-linux-musl-gcc" ]; then
  echo "ERROR: 解压后未找到 aarch64-linux-musl-gcc,检查 musl.cc 产物结构" >&2
  exit 1
fi

echo "${TOOLCHAIN_DIR}/bin"
