#!/bin/bash
# pget_info 统一构建接口 (M1 规范 v0.1)
# 用法: bash release.sh [ARCH] [VERSION]
#   ARCH:    amd64|arm64|all（默认 amd64；纯脚本，架构仅作标识）
#   VERSION: 显式版本号（默认从 get_info.sh 提取）
#   env OUTPUT_DIR: 产物目录（默认 <repo>/output/pget_info/）
set -uo pipefail

BUILD_RET=0

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$SCRIPT_DIR"   # 打包源/产物路径全部以本脚本目录为基准，消除对调用方 cwd 的依赖
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARCH="${1:-amd64}"
VERSION="${2:-$(awk -F'"' '/^GET_INFO_VERSION=/{print $2}' "$SCRIPT_DIR/get_info.sh")}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/output/pget_info}"

echo "build get_info (arch=$ARCH version=$VERSION) ..."

# 本地中间目录：打包源为 $SCRIPT_DIR 下脚本文件，zip 条目以 get_info/ 为顶层，
# 与现场 `unzip get_info.zip; cd get_info` 的用法一致。
rm -rf "$SCRIPT_DIR/output" 2>/dev/null
mkdir -p "$SCRIPT_DIR/output/get_info"
cp "$SCRIPT_DIR/get_info.sh" "$SCRIPT_DIR/output/get_info/"
cp "$SCRIPT_DIR/get_info_log_to_png."* "$SCRIPT_DIR/output/get_info/"

if command -v 7z >/dev/null 2>&1; then
	echo "found 7z"
	( cd "$SCRIPT_DIR/output" && 7z a -mx9 get_info.zip get_info ) >/dev/null
	BUILD_RET=$?
elif command -v zip >/dev/null 2>&1; then
	echo "found zip"
	( cd "$SCRIPT_DIR/output" && zip -r -9 get_info.zip get_info ) >/dev/null
	BUILD_RET=$?
else
	echo "Unsatisfied build dependencies"
	BUILD_RET=-1
fi

# 校验 zip 非空且至少含 3 个条目（get_info.sh / get_info_log_to_png.py /
# get_info_log_to_png.yaml），防止错误 cwd 下静默产出空包仍被拷贝
if [ "$BUILD_RET" = "0" ] && [ -s "$SCRIPT_DIR/output/get_info.zip" ]; then
	if command -v unzip >/dev/null 2>&1; then
		if ZIP_LIST="$(unzip -Z1 "$SCRIPT_DIR/output/get_info.zip" 2>/dev/null)"; then
			ZIP_ENTRIES=0
			while IFS= read -r _entry; do ZIP_ENTRIES=$((ZIP_ENTRIES + 1)); done <<EOF
$ZIP_LIST
EOF
			if [ "$ZIP_ENTRIES" -lt 3 ]; then
				echo "ERROR: get_info.zip 条目数 $ZIP_ENTRIES < 3，打包失败" >&2
				BUILD_RET=1
			else
				echo "get_info.zip ok, entries=$ZIP_ENTRIES"
			fi
		else
			echo "ERROR: get_info.zip 无法解析（unzip 失败），打包失败" >&2
			BUILD_RET=1
		fi
	else
		echo "get_info.zip ok (unzip 不可用，跳过条目校验)"
	fi
else
	echo "ERROR: get_info.zip 缺失或为空，打包失败" >&2
	BUILD_RET=1
fi

# 统一接口：汇聚产物到 OUTPUT_DIR
mkdir -p "$OUTPUT_DIR"
if [ "$BUILD_RET" = "0" ]; then
	cp "$SCRIPT_DIR/output/get_info.zip" "$OUTPUT_DIR/"
fi

exit $BUILD_RET
