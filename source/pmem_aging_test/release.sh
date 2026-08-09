#!/bin/bash
# pmem_aging_test 统一构建接口 (M1 规范 v0.1)
# 用法: bash release.sh [ARCH] [VERSION]
#   ARCH:    arm64（默认，设备侧现场编译）；amd64 仅打包
#   VERSION: 显式版本号（默认从 memtest_a53_gdma/start.sh 提取 V1.4.1）
#   env OUTPUT_DIR: 产物目录（默认 <repo>/output/pmem_aging_test/）
#
# 注意：本包为源码包（memtest_a53_gdma/memtest_gdma 需在设备侧用 build.sh 现场编译，
# memtester 为 aarch64 预编译二进制），ARCH 仅作标识、不参与构建。
set -uo pipefail

BUILD_RET=0

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARCH="${1:-arm64}"
VERSION="${2:-$(awk '/MEMTEST VERSION:/{print $NF}' "$SCRIPT_DIR/memtest_a53_gdma/start.sh" | tr -d '"')}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/output/pmem_aging_test}"

echo "build memtest_a53_gdma ${VERSION} (arch=$ARCH) ..."

# 源路径与中间产物一律基于 $SCRIPT_DIR，消除对调用方 cwd 的依赖
rm -rf "$SCRIPT_DIR/output"
mkdir -p "$SCRIPT_DIR/output"
cp -r "$SCRIPT_DIR/memtest_a53_gdma" "$SCRIPT_DIR/output/mem_aging_test_${VERSION}"
cp "$SCRIPT_DIR"/*.md "$SCRIPT_DIR/output/mem_aging_test_${VERSION}/"

pushd "$SCRIPT_DIR/output" >/dev/null
	# 打包前删除同版本旧 zip，避免 7z 对已存在 zip 走 .tmp 更新失败
	rm -f "mem_aging_test_${VERSION}.zip"
	if command -v 7z >/dev/null 2>&1; then
		echo "found 7z"
		7z a -y -mx9 "mem_aging_test_${VERSION}.zip" "mem_aging_test_${VERSION}" >/dev/null
		BUILD_RET=$?
	elif command -v zip >/dev/null 2>&1; then
		echo "found zip"
		zip -r -9 "mem_aging_test_${VERSION}.zip" "mem_aging_test_${VERSION}" >/dev/null
		BUILD_RET=$?
	else
		echo "Unsatisfied build dependencies"
		BUILD_RET=-1
	fi
popd >/dev/null

# 校验 zip 非空且至少含 8 个条目，防止错误 cwd/打包失败时静默产出空包仍被拷贝
if [ "$BUILD_RET" = "0" ] && [ -s "$SCRIPT_DIR/output/mem_aging_test_${VERSION}.zip" ]; then
	if command -v unzip >/dev/null 2>&1; then
		if ZIP_LIST="$(unzip -Z1 "$SCRIPT_DIR/output/mem_aging_test_${VERSION}.zip" 2>/dev/null)"; then
			ZIP_ENTRIES=0
			while IFS= read -r _entry; do ZIP_ENTRIES=$((ZIP_ENTRIES + 1)); done <<EOF
$ZIP_LIST
EOF
			if [ "$ZIP_ENTRIES" -lt 8 ]; then
				echo "ERROR: mem_aging_test_${VERSION}.zip 条目数 $ZIP_ENTRIES < 8，打包失败" >&2
				BUILD_RET=1
			else
				echo "mem_aging_test_${VERSION}.zip ok, entries=$ZIP_ENTRIES"
			fi
		else
			echo "ERROR: mem_aging_test_${VERSION}.zip 无法解析（unzip 失败），打包失败" >&2
			BUILD_RET=1
		fi
	else
		echo "mem_aging_test_${VERSION}.zip ok (unzip 不可用，跳过条目校验)"
	fi
else
	echo "ERROR: mem_aging_test_${VERSION}.zip 缺失或为空，打包失败" >&2
	BUILD_RET=1
fi

# 统一接口：汇聚产物到 OUTPUT_DIR（校验通过才拷贝）
mkdir -p "$OUTPUT_DIR"
if [ "$BUILD_RET" = "0" ]; then
	cp "$SCRIPT_DIR/output/mem_aging_test_${VERSION}.zip" "$OUTPUT_DIR/"
fi

exit $BUILD_RET
