#!/bin/bash

build_shell="$(dirname "$(readlink -f "$0")")"

if [[ "$2" == "lib" ]]; then
	pushd libs
	bash build_libs.sh "$1"
	popd
fi

mkdir -p output
cp ${build_shell}/src/*.json ${build_shell}/output/

git config --global --add safe.directory "${build_shell}"

pushd src
if [[ "$1" == "host" ]]; then
	make clean
	EXT_LIB_FLAG_STATIC=" -Wl,-Bstatic -lssh -lssl -lcrypto " EXT_LIB_FLAG_DYNAMIC=" -Wl,-Bdynamic -ldl -lpthread " EXT_FLAG="" ARCH="$(uname -m)" BUILD_PATH="${build_shell}" CROSS_COMPILE="" LIBS_TYPE="host_build" make VERBOSE=1
	mv dfss-cpp ${build_shell}/output/dfss-cpp-linux-amd64
elif [[ "$1" == "aarch64" ]]; then
	make clean
	EXT_LIB_FLAG_STATIC=" -Wl,-Bstatic -lssh -lssl -lcrypto " EXT_LIB_FLAG_DYNAMIC=" -Wl,-Bdynamic -ldl -lpthread " EXT_FLAG="" ARCH="aarch64" BUILD_PATH="${build_shell}" CROSS_COMPILE="aarch64-linux-gnu-" LIBS_TYPE="aarch64_build" make VERBOSE=1
	mv dfss-cpp ${build_shell}/output/dfss-cpp-linux-arm64
elif [[ "$1" == "mingw64" ]]; then
	make clean
	EXT_LIB_FLAG_STATIC=" -static-libgcc -static-libstdc++ -Wl,-Bstatic -lstdc++ -lpthread -lssh -lssl -lcrypto  -lws2_32 -liphlpapi -lgdi32 -lcrypt32 " EXT_LIB_FLAG_DYNAMIC=" -Wl,-Bdynamic -ldl " EXT_FLAG=" -m64 -static " ARCH="x86_64" BUILD_PATH="${build_shell}" CROSS_COMPILE="x86_64-w64-mingw32-" LIBS_TYPE="win64_build" make VERBOSE=1
	mv dfss-cpp.exe ${build_shell}/output/dfss-cpp-win-amd64.exe
elif [[ "$1" == "mingw" ]]; then
	make clean
	EXT_LIB_FLAG_STATIC=" -static-libgcc -static-libstdc++ -Wl,-Bstatic -lstdc++ -lpthread -lssh -lssl -lcrypto  -lws2_32 -liphlpapi -lgdi32 -lcrypt32 " EXT_LIB_FLAG_DYNAMIC=" -Wl,-Bdynamic -ldl " EXT_FLAG=" -m32 -static " ARCH="i686" BUILD_PATH="${build_shell}" CROSS_COMPILE="i686-w64-mingw32-" LIBS_TYPE="win32_build" make VERBOSE=1
	mv dfss-cpp.exe ${build_shell}/output/dfss-cpp-win-i686.exe
elif [[ "$1" == "loongarch64" ]]; then
	make clean
	EXT_LIB_FLAG_STATIC=" -Wl,-Bstatic -lssh -lssl -lcrypto " EXT_LIB_FLAG_DYNAMIC=" -Wl,-Bdynamic -ldl -lpthread " EXT_FLAG=" " ARCH="loongarch64" BUILD_PATH="${build_shell}" CROSS_COMPILE="loongarch64-linux-gnu-" LIBS_TYPE="loongarch64_build" make VERBOSE=1
	mv dfss-cpp ${build_shell}/output/dfss-cpp-linux-loongarch64
elif [[ "$1" == "riscv64" ]]; then
	make clean
	EXT_LIB_FLAG_STATIC=" -Wl,-Bstatic -lssh -lssl -lcrypto " EXT_LIB_FLAG_DYNAMIC=" -Wl,-Bdynamic -ldl -lpthread " EXT_FLAG=" " ARCH="riscv64" BUILD_PATH="${build_shell}" CROSS_COMPILE="riscv64-linux-gnu-" LIBS_TYPE="riscv64_build" make VERBOSE=1
	mv dfss-cpp ${build_shell}/output/dfss-cpp-linux-riscv64
elif [[ "$1" == "armbi" ]]; then
	make clean
	EXT_LIB_FLAG_STATIC=" -Wl,-Bstatic -lssh -lssl -lcrypto -latomic " EXT_LIB_FLAG_DYNAMIC=" -Wl,-Bdynamic -ldl -lpthread " EXT_FLAG=" " ARCH="armbi" BUILD_PATH="${build_shell}" CROSS_COMPILE="arm-linux-gnueabi-" LIBS_TYPE="armbi_build" make VERBOSE=1
	mv dfss-cpp ${build_shell}/output/dfss-cpp-linux-armbi
elif [[ "$1" == "sw_64" ]]; then
	make clean
	EXT_LIB_FLAG_STATIC=" -Wl,-Bstatic -lssh -lssl -lcrypto " EXT_LIB_FLAG_DYNAMIC=" -Wl,-Bdynamic -ldl -lpthread -Wl,-rpath=/lib/ " EXT_FLAG=" -Wl,--dynamic-linker=/lib/ld-linux.so.2 " ARCH="sw_64" BUILD_PATH="${build_shell}" CROSS_COMPILE="sw_64-sunway-linux-gnu-" LIBS_TYPE="sw_64_build" make VERBOSE=1
	mv dfss-cpp ${build_shell}/output/dfss-cpp-linux-sw_64
fi
popd
