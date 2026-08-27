#!/bin/bash
# pbmssm 统一构建接口 (M1 规范 v0.1)
# 用法: bash release.sh [ARCH] [VERSION] [REASONIX_BIN]
#   ARCH:          arm64 | amd64 | all（默认 arm64）
#   VERSION:       显式版本号（默认从 build/version.sh DEFAULT_VERSION 提取）
#   REASONIX_BIN:  reasonix arm64 二进制路径。不传（或未设 env）时默认取
#                  build/reasonix/bin/ 下的仓库内置版本（bmssm 包必须内置
#                  reasonix——MYSWY 要求）；显式传第 3 个参数（含空串 ""）可跳过/覆盖。
#   env OUTPUT_DIR: 产物目录（默认 <repo>/output/pbmssm/）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$SCRIPT_DIR"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARCH="${1:-arm64}"
# 版本默认值从 build/version.sh 的 DEFAULT_VERSION（唯一权威）提取，禁止在此硬编码
VERSION="${2:-$(grep -oE '^DEFAULT_VERSION="[^"]+"' "$SCRIPT_DIR/build/version.sh" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')}"
# Reasonix 内嵌默认：仓库内置二进制（build/reasonix/bin/），存在即内嵌；
# 第 3 个参数显式提供（含空串跳过）时不自动探测。此前默认不传导致 deb 无
# reasonix 二进制，真机 Agent 服务开关报 "executable file not found in $PATH"
# （2026-08-27 复现）。
if [ $# -ge 3 ]; then
  REASONIX_BIN="$3" # 显式传参（含空串 "" 跳过内嵌）优先
elif [ -z "${REASONIX_BIN:-}" ]; then
  for _f in "$SCRIPT_DIR"/build/reasonix/bin/reasonix-arm64*; do
    [ -f "$_f" ] && REASONIX_BIN="$_f" && break
  done
fi
unset _f
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/output/pbmssm}"

case "$ARCH" in
  arm64|amd64) ;;
  all) ARCH_LIST="arm64 amd64" ;;
  *) echo "ERROR: ARCH 必须是 arm64|amd64|all，得到: $ARCH" >&2; exit 1 ;;
esac

mkdir -p "$OUTPUT_DIR"

build_one() {
  local arch="$1"
  echo "==> pbmssm build arch=$arch version=$VERSION reasonix=${REASONIX_BIN:-<none>}"
  bash build/build-deb-bmssm.sh "$VERSION" "$arch" "$REASONIX_BIN"
  # build-deb-bmssm.sh 固定产出两个后缀变体（_noskill 默认 / _se7 带 SE7 skill），
  # 逐个校验并拷贝到 OUTPUT_DIR；无匹配视为构建失败。
  for suffix in _noskill _se7; do
    local deb="release/bmssm_${VERSION}_${arch}${suffix}.deb"
    if [ ! -f "$deb" ]; then
      echo "ERROR: 未找到产物 $deb" >&2
      exit 1
    fi
    cp "$deb" "$OUTPUT_DIR/"
    file "$deb" | head -1
  done
}

if [ -n "${ARCH_LIST:-}" ]; then
  for a in $ARCH_LIST; do build_one "$a"; done
else
  build_one "$ARCH"
fi

echo "==> pbmssm 完成, 产物: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"
