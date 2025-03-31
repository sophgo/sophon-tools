#!/bin/bash

build_shell="$(dirname "$(readlink -f "$0")")"

if [[ "$2" == "lib" ]]; then
	pushd libs
	bash build_libs.sh "$1"
	popd
fi

NEED_DEBUG=0
if [[ "$3" == "debug" ]]; then
	NEED_DEBUG=1
fi

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
	EXT_LIB_FLAG_STATIC=" -static -Wl,-Bstatic -lssh2 -lmbedcrypto -lpthread -lz " EXT_LIB_FLAG_DYNAMIC=" " EXT_FLAG=" -march=loongarch64 -mno-lsx -mno-lasx " ARCH="loongarch64" BUILD_PATH="${build_shell}" CROSS_COMPILE="loongarch64-unknown-linux-gnu-" LIBS_TYPE="${build_target}" NEED_DEBUG="${NEED_DEBUG}" make VERBOSE=1
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
fi
popd
