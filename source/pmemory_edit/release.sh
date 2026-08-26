#!/bin/bash
# pmemory_edit 统一构建接口 (M1 规范 v0.1)
# 用法: bash release.sh [ARCH] [VERSION]
#   ARCH:    arm64（唯一支持平台）。bintools（cpio/dtc/dumpimage/file/mkimage）
#            为 aarch64 预编译二进制，无 x86_64 版本，故本包仅产出 arm64 deb。
#            传 amd64 会报错退出，避免与 arm64 产物混淆。
#   VERSION: 显式版本号（默认从 source/memory_edit/memory_edit.sh 提取 2.12.1）
#   env OUTPUT_DIR: 产物目录（默认 <repo>/output/pmemory_edit/）
set -uo pipefail

BUILD_RET=0

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARCH="${1:-arm64}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/output/pmemory_edit}"

# 版本号默认从 memory_edit.sh 的版本行提取；提取失败时显式报错退出，
# 避免产出版本号为空/占位符的产物（memory_edit_v.tar.xz）。
default_version() {
	grep "INFO: version: " "$SCRIPT_DIR/source/memory_edit/memory_edit.sh" | awk -F' ' '{print $(NF)}' | tr -d '"'
}
MEMORY_EDIT_VERSION="${2:-$(default_version)}"
if [ -z "$MEMORY_EDIT_VERSION" ]; then
	echo "ERROR: 无法从 memory_edit.sh 提取版本号，请显式传入 VERSION" >&2
	exit 1
fi

# 平台校验：bintools 为 aarch64 预编译，仅支持 arm64
if [ "$ARCH" != "arm64" ]; then
	echo "ERROR: 仅支持 arm64（bintools 为 aarch64 预编译，无 x86_64 版本），收到 ARCH=$ARCH" >&2
	exit 1
fi

echo "build memory_edit (arch=$ARCH version=$MEMORY_EDIT_VERSION) ..."

# 中间目录与产物一律基于 $SCRIPT_DIR，消除对调用方 cwd 的依赖
BUILD_DIR="$SCRIPT_DIR/output"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

if command -v dpkg-deb >/dev/null 2>&1; then
	# 源码 tar.xz
	tar -caf "$BUILD_DIR/memory_edit_v${MEMORY_EDIT_VERSION}.tar.xz" -C "$SCRIPT_DIR/source" memory_edit
	BUILD_RET=$?

	# deb 打包：在 staging 目录复制 DEBIAN + opt，再对副本做版本替换并打包，
	# 原 source/deb/DEBIAN/control 零改动，构建中断也不污染源码树。
	STAGE="$BUILD_DIR/deb-stage"
	rm -rf "$STAGE"
	mkdir -p "$STAGE"
	cp -r "$SCRIPT_DIR/source/deb/DEBIAN" "$STAGE/DEBIAN"
	cp -r "$SCRIPT_DIR/source/deb/opt" "$STAGE/opt"
	# 版本占位符写入 staging 副本内的 control；先转义 / 防 sed 破坏
	VERSION_SAFE="$(printf '%s' "$MEMORY_EDIT_VERSION" | sed 's|/|\\/|g')"
	if ! sed -i "s/MEMORY_EDIT_VERSION/$VERSION_SAFE/" "$STAGE/DEBIAN/control"; then
		echo "ERROR: 写入版本号到 control 失败" >&2
		BUILD_RET=1
	fi
	# 需要被打进 deb 的 opt/sophon/memory_edit.tar.xz 由 staging 提供
	cp "$BUILD_DIR/memory_edit_v${MEMORY_EDIT_VERSION}.tar.xz" "$STAGE/opt/sophon/memory_edit.tar.xz"
	if [ "$BUILD_RET" = "0" ]; then
		echo "deb build version: v${MEMORY_EDIT_VERSION}"
		# --root-owner-group：无论构建者 uid，deb 内文件统一 root:root，符合 deb 规范
		if ! dpkg-deb --root-owner-group -b "$STAGE" "$BUILD_DIR/memory_edit_v${MEMORY_EDIT_VERSION}.deb" 2>&1 | tail -2; then
			echo "ERROR: dpkg-deb 打包失败" >&2
			BUILD_RET=1
		fi
	fi
else
	echo "Unsatisfied build dependencies"
	BUILD_RET=-1
fi

# 校验产物存在且非空，失败时才退出非零
if [ "$BUILD_RET" = "0" ] && [ -s "$BUILD_DIR/memory_edit_v${MEMORY_EDIT_VERSION}.tar.xz" ] && [ -s "$BUILD_DIR/memory_edit_v${MEMORY_EDIT_VERSION}.deb" ]; then
	echo "build ok: $BUILD_DIR/memory_edit_v${MEMORY_EDIT_VERSION}.tar.xz / .deb"
else
	echo "ERROR: 产物缺失或为空，打包失败" >&2
	BUILD_RET=1
fi

# 统一接口：汇聚产物到 OUTPUT_DIR（校验通过才拷贝）
mkdir -p "$OUTPUT_DIR"
if [ "$BUILD_RET" = "0" ]; then
	cp "$BUILD_DIR/memory_edit_v${MEMORY_EDIT_VERSION}.tar.xz" "$BUILD_DIR/memory_edit_v${MEMORY_EDIT_VERSION}.deb" "$OUTPUT_DIR/"
fi

exit $BUILD_RET