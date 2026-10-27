#!/bin/bash

if [[ "$(uname -s)" == "Darwin" ]]; then
	# macOS 没有 readlink -f
	build_shell="$(cd "$(dirname "$0")" && pwd -P)"
else
	build_shell="$(dirname "$(readlink -f "$0")")"
fi
# 脚本路径自包含：以下相对路径（libs/src/output）均以脚本所在目录为基准
cd "$build_shell"

if [[ "$2" == "lib" ]]; then
	pushd libs
	bash build_libs.sh "$1"
	popd
fi

NEED_DEBUG=0
if [[ "${3:-}" == "debug" ]]; then
	NEED_DEBUG=1
fi

# 编译期版本信息（MYS-2414）：统一构建容器内常常拿不到 .git（只挂子目录，
# 或 worktree 的 gitdir 引用解析失败），Makefile 的 $(shell git ...) 会静默失败，
# 编出的二进制打印 "version: (-)[]"。
# 这里在还能拿到 git 时（宿主机或已挂主 git 目录的容器）先算好 export 给 make；
# 拿不到则交给 Makefile 回退到 git_version（会带 -nogit 标记，不伪装成正常构建）。
if [[ -z "${GIT_COMMIT_HASH:-}" ]]; then
	_desc="$(git describe --tags 2>/dev/null)" || _desc=""
	if [[ -z "${_desc}" ]]; then
		_desc="$(git describe --tags --always 2>/dev/null)" || _desc=""
	fi
	_sha="$(git rev-parse HEAD 2>/dev/null)" || _sha=""
	if [[ -n "${_desc}" && -n "${_sha}" ]]; then
		GIT_COMMIT_HASH="${_desc}-${_sha}"
	elif [[ -n "${_sha}" ]]; then
		GIT_COMMIT_HASH="${_sha}"
	fi
	unset _desc _sha
fi
if [[ -z "${GIT_COMMIT_DATE:-}" ]]; then
	GIT_COMMIT_DATE="$(git show -s --format=%ci HEAD 2>/dev/null)" || GIT_COMMIT_DATE=""
fi
export GIT_COMMIT_HASH GIT_COMMIT_DATE
echo "==> 编译期版本: ${GIT_COMMIT_HASH:-<由 Makefile 回退 git_version>} [${GIT_COMMIT_DATE:-Unknown}]"

mkdir -p output
cp ${build_shell}/src/*.json ${build_shell}/output/

git config --global --add safe.directory "${build_shell}"

build_target="${1}_build"

pushd src
if [[ "$1" == "host" ]]; then
	make clean
	EXT_LIB_FLAG_STATIC=" -static -Wl,-Bstatic -lssh2 -lmbedcrypto -lpthread -lz " EXT_LIB_FLAG_DYNAMIC=" " EXT_FLAG=" -march=k8 -mtune=k8 " ARCH="$(uname -m)" BUILD_PATH="${build_shell}" CROSS_COMPILE="" LIBS_TYPE="${build_target}" NEED_DEBUG="${NEED_DEBUG}" make VERBOSE=1
	mv dfss-cpp ${build_shell}/output/dfss-cpp-linux-amd64
elif [[ "$1" == "aarch64" ]]; then
	make clean
	EXT_LIB_FLAG_STATIC=" -static -Wl,-Bstatic -lssh2 -lmbedcrypto -pthread -lz " EXT_LIB_FLAG_DYNAMIC=" " EXT_FLAG=" -march=armv8-a " ARCH="aarch64" BUILD_PATH="${build_shell}" CROSS_COMPILE="aarch64-linux-gnu-" LIBS_TYPE="${build_target}" NEED_DEBUG="${NEED_DEBUG}" make VERBOSE=1
	mv dfss-cpp ${build_shell}/output/dfss-cpp-linux-arm64
elif [[ "$1" == "mingw64" ]]; then
	make clean
	EXT_LIB_FLAG_STATIC=" -static-libgcc -static-libstdc++ -Wl,-Bstatic -lstdc++ -lpthread -lssh2 -lmbedcrypto -lbcrypt -lws2_32 -lgdi32 -lz " EXT_LIB_FLAG_DYNAMIC=" " EXT_FLAG=" -m64 -static " ARCH="x86_64" BUILD_PATH="${build_shell}" CROSS_COMPILE="x86_64-w64-mingw32-" LIBS_TYPE="${build_target}" NEED_DEBUG="${NEED_DEBUG}" make VERBOSE=1
	mv dfss-cpp.exe ${build_shell}/output/dfss-cpp-win-amd64.exe
elif [[ "$1" == "mingw" ]]; then
	make clean
	EXT_LIB_FLAG_STATIC=" -static-libgcc -static-libstdc++ -Wl,-Bstatic -lstdc++ -lpthread -lssh2 -lmbedcrypto -lbcrypt -lws2_32 -lgdi32 -lz " EXT_LIB_FLAG_DYNAMIC=" " EXT_FLAG=" -m32 -static " ARCH="i686" BUILD_PATH="${build_shell}" CROSS_COMPILE="i686-w64-mingw32-" LIBS_TYPE="${build_target}" NEED_DEBUG="${NEED_DEBUG}" make VERBOSE=1
	mv dfss-cpp.exe ${build_shell}/output/dfss-cpp-win-i686.exe
elif [[ "$1" == "loongarch64" ]]; then
	make clean
	EXT_LIB_FLAG_STATIC=" -static -Wl,-Bstatic -lssh2 -lmbedcrypto -lpthread -lz " EXT_LIB_FLAG_DYNAMIC=" " EXT_FLAG=" -march=loongarch64 -mno-lsx -mno-lasx " ARCH="loongarch64" BUILD_PATH="${build_shell}" CROSS_COMPILE="loongarch64-linux-gnu-" LIBS_TYPE="${build_target}" NEED_DEBUG="${NEED_DEBUG}" make VERBOSE=1
	mv dfss-cpp ${build_shell}/output/dfss-cpp-linux-loongarch64
elif [[ "$1" == "riscv64" ]]; then
	make clean
	EXT_LIB_FLAG_STATIC=" -static -Wl,-Bstatic -lssh2 -lmbedcrypto -lpthread -lz " EXT_LIB_FLAG_DYNAMIC=" " EXT_FLAG=" " ARCH="riscv64" BUILD_PATH="${build_shell}" CROSS_COMPILE="riscv64-linux-gnu-" LIBS_TYPE="${build_target}" NEED_DEBUG="${NEED_DEBUG}" make VERBOSE=1
	mv dfss-cpp ${build_shell}/output/dfss-cpp-linux-riscv64
elif [[ "$1" == "armbi" ]]; then
	make clean
	EXT_LIB_FLAG_STATIC=" -Wl,-Bstatic -lssh2 -lmbedcrypto -lz " EXT_LIB_FLAG_DYNAMIC=" -Wl,-Bdynamic -ldl -lpthread " EXT_FLAG=" " ARCH="armbi" BUILD_PATH="${build_shell}" CROSS_COMPILE="arm-linux-gnueabi-" LIBS_TYPE="${build_target}" NEED_DEBUG="${NEED_DEBUG}" make VERBOSE=1
	mv dfss-cpp ${build_shell}/output/dfss-cpp-linux-armbi
elif [[ "$1" == "sw_64" ]]; then
	make clean
	EXT_LIB_FLAG_STATIC=" -static -Wl,-Bstatic -lssh2 -lmbedcrypto -lpthread -lz " EXT_LIB_FLAG_DYNAMIC=" " EXT_FLAG=" " ARCH="sw_64" BUILD_PATH="${build_shell}" CROSS_COMPILE="sw_64-sunway-linux-gnu-" LIBS_TYPE="${build_target}" NEED_DEBUG="${NEED_DEBUG}" make VERBOSE=1
	mv dfss-cpp ${build_shell}/output/dfss-cpp-linux-sw_64
elif [[ "$1" == "darwin" ]]; then
	# macOS 本机编译（x86_64 / arm64 取决于当前 Mac），交叉编译 darwin 需要 macOS SDK，仅本机构建
	if [[ "$(uname -s)" != "Darwin" ]]; then
		echo "ERROR: darwin 目标必须在 macOS 主机上构建（需要 macOS SDK/工具链）。非 macOS 主机请构建 linux/win 目标。" >&2
		exit 1
	fi
	make clean
	MAC_ARCH="$(uname -m)"
	export EXT_LIB_FLAG_STATIC=" -Wl,-force_load,${build_shell}/libs/darwin_build/lib/libssh2.a -Wl,-force_load,${build_shell}/libs/darwin_build/lib/libmbedtls.a -Wl,-force_load,${build_shell}/libs/darwin_build/lib/libmbedx509.a -Wl,-force_load,${build_shell}/libs/darwin_build/lib/libmbedcrypto.a -Wl,-force_load,${build_shell}/libs/darwin_build/lib/libz.a "
	export EXT_LIB_FLAG_DYNAMIC=" -lpthread "
	EXT_FLAG=" -mmacosx-version-min=10.15 " ARCH="${MAC_ARCH}" BUILD_PATH="${build_shell}" CROSS_COMPILE="" LIBS_TYPE="darwin_build" NEED_DEBUG="${NEED_DEBUG}" make VERBOSE=1
	mv dfss-cpp ${build_shell}/output/dfss-cpp-darwin-${MAC_ARCH}
fi
popd
