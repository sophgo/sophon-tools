#! /bin/bash

set -e

unset build_shell
if [[ "$(uname -s)" == "Darwin" ]]; then
	# macOS 没有 readlink -f
	build_shell="$(cd "$(dirname "$0")" && pwd -P)"
else
	build_shell="$(dirname "$(readlink -f "$0")")"
fi

unset CROSS_COMPILE
unset CC
unset CXX
unset ARCH
unset CROSS_COMPILE

if [[ "$(uname -s)" == "Darwin" ]]; then
	# macOS 上不需要 sudo（解压目录属于当前用户），避免交互式密码卡住
	rm -rf libssh*
	rm -rf zlib*
	rm -rf mbedtls*
else
	sudo rm -rf libssh*
	sudo rm -rf zlib*
	sudo rm -rf mbedtls*
fi

tar -xaf "$(find ${build_shell}/zips/ -name "libssh2*")" -C ./
mv libssh2* libssh2

tar -xaf "$(find ${build_shell}/zips/ -name "zlib*")" -C ./
mv zlib* zlib

tar -xaf "$(find ${build_shell}/zips/ -name "mbedtls*")" -C ./
mv mbedtls* mbedtls

unset CC
unset CXX
unset LD
unset AR
unset CROSS_COMPILE

build_target="${build_shell}/${1}_build"
if [[ "$(uname -s)" == "Darwin" ]]; then
	rm -rf "${build_target}"
else
	sudo rm -rf "${build_target}"
fi

if [[ "$1" == "host" ]]; then
	# host gcc
	rm -rf host_build
	mkdir -p host_build
	unset CROSS_COMPILE

	## zlib static
	pushd "${build_shell}/zlib"
	CC=gcc ./configure --prefix="${build_target}" --static
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #zlib

	## mbedtls static
	pushd "${build_shell}/mbedtls"
	mkdir build
	cd build
	SHARED=0 cmake -DCMAKE_BUILD_TYPE=Release -DENABLE_TESTING=OFF -DUSE_STATIC_MBEDTLS_LIBRARY=ON -DUSE_SHARED_MBEDTLS_LIBRARY=OFF -DINSTALL_MBEDTLS_HEADERS=ON  -DCMAKE_INSTALL_PREFIX="${build_target}" ..
	make -j$(nproc)
	make install -j$(nproc)
	cd ..
	popd

	## libssh2 static
	pushd "${build_shell}/libssh2"
	./configure --disable-examples-build --disable-sshd-tests --disable-docker-tests --with-sysroot="${build_target}" --enable-static=yes --enable-shared=no --with-libmbedcrypto-prefix="${build_target}" --prefix="${build_target}" --with-crypto=mbedtls --with-libz --with-libz-prefix="${build_target}"
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #libssh2
elif [[ "$1" == "aarch64" ]]; then
	aarch64-linux-gnu-gcc -v || exit 1
	# aarch64 gcc
	rm -rf aarch64_build
	mkdir -p aarch64_build
	export CROSS_COMPILE=aarch64-linux-gnu-

	## zlib static
	pushd "${build_shell}/zlib"
	CC=${CROSS_COMPILE}gcc CFLAGS="-O3 -fPIC" ./configure --prefix="${build_target}" --static
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #zlib

	## mbedtls static
	pushd "${build_shell}/mbedtls"
	mkdir build
	cd build
	CFLAGS="-Wno-error=array-bounds" CC=${CROSS_COMPILE}gcc SHARED=0 cmake -DCMAKE_BUILD_TYPE=Release -DENABLE_TESTING=OFF -DUSE_STATIC_MBEDTLS_LIBRARY=ON -DUSE_SHARED_MBEDTLS_LIBRARY=OFF -DINSTALL_MBEDTLS_HEADERS=ON -DCMAKE_INSTALL_PREFIX="${build_target}" ..
	make -j$(nproc)
	make install -j$(nproc)
	cd ..
	popd

	pushd "${build_target}"
	ln -s lib lib64
	popd

	export CC=aarch64-linux-gnu-gcc
	export CXX=aarch64-linux-gnu-g++
	export LD=aarch64-linux-gnu-ld
	export AR=aarch64-linux-gnu-ar
	export CROSS_COMPILE=aarch64-linux-gnu-

	## libssh2 static
	pushd "${build_shell}/libssh2"
	make clean 2>/dev/null || true

	./configure --disable-examples-build --disable-sshd-tests --disable-docker-tests --host=aarch64-linux-gnu --with-sysroot="${build_target}" --enable-static=yes --enable-shared=no --with-libmbedcrypto-prefix="${build_target}" --prefix="${build_target}" --with-crypto=mbedtls --with-libz --with-libz-prefix="${build_target}"
	unset CC
	unset CXX
	unset LD
	unset AR
	make clean
	make -j$(nproc) VERBOSE=1 || exit 1
	make install -j$(nproc)
	popd #libssh2
elif [[ "$1" == "mingw64" ]]; then
	x86_64-w64-mingw32-gcc -v || exit 1
	# mingw64 gcc
	rm -rf win64_build
	mkdir -p win64_build
	export CROSS_COMPILE=x86_64-w64-mingw32-

	## zlib static
	pushd "${build_shell}/zlib"
	CC=${CROSS_COMPILE}gcc CFLAGS="-O3 -fPIC" ./configure --prefix="${build_target}" --static
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #zlib

	## mbedtls static
	pushd "${build_shell}/mbedtls"
	mkdir build
	cd build
	WINDOWS=1 CC=${CROSS_COMPILE}gcc SHARED=0 cmake -DCMAKE_C_FLAGS="-Wno-error=format -Wno-error" -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_SYSTEM_PROCESSOR=x86_64 -DCMAKE_BUILD_TYPE=Release -DENABLE_TESTING=OFF -DUSE_STATIC_MBEDTLS_LIBRARY=ON -DUSE_SHARED_MBEDTLS_LIBRARY=OFF -DINSTALL_MBEDTLS_HEADERS=ON  -DCMAKE_INSTALL_PREFIX="${build_target}" ..
	WINDOWS=1 make -j$(nproc) CC=${CROSS_COMPILE}gcc
	WINDOWS=1 make install -j$(nproc) CC=${CROSS_COMPILE}gcc
	cd ..
	popd

	pushd "${build_target}"
	ln -s lib lib64
	popd

	export CC=x86_64-w64-mingw32-gcc
	export CXX=x86_64-w64-mingw32-g++
	export LD=x86_64-w64-mingw32-ld
	export AR=x86_64-w64-mingw32-ar
	export CROSS_COMPILE=x86_64-w64-mingw32-

	## libssh2 static
	pushd "${build_shell}/libssh2"
	make clean 2>/dev/null || true

	./configure --host=x86_64-pc-mingw64 --disable-examples-build --disable-sshd-tests --disable-docker-tests --with-sysroot="${build_target}" --enable-static=yes --enable-shared=no --with-libmbedcrypto-prefix="${build_target}" --prefix="${build_target}" --with-crypto=mbedtls --with-libz --with-libz-prefix="${build_target}"
	unset CC
	unset CXX
	unset LD
	unset AR
	unset CROSS_COMPILE
	make clean
	make -j$(nproc) VERBOSE=1 || exit 1
	make install -j$(nproc)
	popd #libssh2
elif [[ "$1" == "mingw" ]]; then
	i686-w64-mingw32-gcc -v || exit 1
	# mingw gcc
	rm -rf win32_build
	mkdir -p win32_build
	export CROSS_COMPILE=i686-w64-mingw32-

	## zlib static
	pushd "${build_shell}/zlib"
	CC=${CROSS_COMPILE}gcc CFLAGS="-O3 -fPIC" ./configure --prefix="${build_target}" --static
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #zlib

	## mbedtls static
	pushd "${build_shell}/mbedtls"
	mkdir build
	cd build
	WINDOWS=1 CC=${CROSS_COMPILE}gcc SHARED=0 cmake -DCMAKE_C_FLAGS="-Wno-error=format -Wno-error" -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_SYSTEM_PROCESSOR=i686 -DCMAKE_BUILD_TYPE=Release -DENABLE_TESTING=OFF -DUSE_STATIC_MBEDTLS_LIBRARY=ON -DUSE_SHARED_MBEDTLS_LIBRARY=OFF -DINSTALL_MBEDTLS_HEADERS=ON  -DCMAKE_INSTALL_PREFIX="${build_target}" ..
	WINDOWS=1 CC=${CROSS_COMPILE}gcc make -j$(nproc)
	WINDOWS=1 CC=${CROSS_COMPILE}gcc make install -j$(nproc)
	cd ..
	popd

	pushd "${build_target}"
	ln -s lib lib64
	popd

	export CC=i686-w64-mingw32-gcc
	export CXX=i686-w64-mingw32-g++
	export LD=i686-w64-mingw32-ld
	export AR=i686-w64-mingw32-ar
	export CROSS_COMPILE=i686-w64-mingw32-

	## libssh2 static
	pushd "${build_shell}/libssh2"
	make clean 2>/dev/null || true

	./configure --host=i686-pc-mingw32 --disable-examples-build --disable-sshd-tests --disable-docker-tests --with-sysroot="${build_target}" --enable-static=yes --enable-shared=no --with-libmbedcrypto-prefix="${build_target}" --prefix="${build_target}" --with-crypto=mbedtls --with-libz --with-libz-prefix="${build_target}"
	unset CC
	unset CXX
	unset LD
	unset AR
	unset CROSS_COMPILE
	make clean
	make -j$(nproc) VERBOSE=1 || exit 1
	make install -j$(nproc)
	popd #libssh2
elif [[ "$1" == "loongarch64" ]]; then
	loongarch64-linux-gnu-gcc -v || exit 1

	rm -rf loongarch64_build
	mkdir -p loongarch64_build
	export CROSS_COMPILE=loongarch64-linux-gnu-

	## zlib static
	pushd "${build_shell}/zlib"
	CC=${CROSS_COMPILE}gcc CFLAGS="-O3 -fPIC" ./configure --prefix="${build_target}" --static
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #zlib

	## mbedtls static
	pushd "${build_shell}/mbedtls"
	mkdir build
	cd build
	CC=${CROSS_COMPILE}gcc SHARED=1 cmake -DCMAKE_BUILD_TYPE=Release -DENABLE_TESTING=OFF -DUSE_STATIC_MBEDTLS_LIBRARY=ON -DUSE_SHARED_MBEDTLS_LIBRARY=OFF -DINSTALL_MBEDTLS_HEADERS=ON  -DCMAKE_INSTALL_PREFIX="${build_target}" ..
	make -j$(nproc)
	make install -j$(nproc)
	cd ..
	popd

	pushd "${build_target}"
	ln -s lib lib64
	popd

	export CC=loongarch64-linux-gnu-gcc
	export CXX=loongarch64-linux-gnu-g++
	export LD=loongarch64-linux-gnu-ld
	export AR=loongarch64-linux-gnu-ar
	export CROSS_COMPILE=loongarch64-linux-gnu-

	## libssh2 static
	pushd "${build_shell}/libssh2"
	make clean 2>/dev/null || true

	./configure --host=loongarch64-pc-linux --disable-examples-build --disable-sshd-tests --disable-docker-tests --with-sysroot="${build_target}" --enable-static=yes --enable-shared=no --with-libmbedcrypto-prefix="${build_target}" --prefix="${build_target}" --with-crypto=mbedtls --with-libz --with-libz-prefix="${build_target}"
	unset CC
	unset CXX
	unset LD
	unset AR
	unset CROSS_COMPILE
	make clean
	make -j$(nproc) VERBOSE=1 || exit 1
	make install -j$(nproc)
	popd #libssh2
elif [[ "$1" == "riscv64" ]]; then
	riscv64-linux-gnu-gcc -v || exit 1

	rm -rf riscv64_build
	mkdir -p riscv64_build
	export CROSS_COMPILE=riscv64-linux-gnu-

	## zlib static
	pushd "${build_shell}/zlib"
	CC=${CROSS_COMPILE}gcc CFLAGS="-O3 -fPIC" ./configure --prefix="${build_target}" --static
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #zlib

	## mbedtls static
	pushd "${build_shell}/mbedtls"
	mkdir build
	cd build
	CC=${CROSS_COMPILE}gcc SHARED=0 cmake -DCMAKE_BUILD_TYPE=Release -DENABLE_TESTING=OFF -DUSE_STATIC_MBEDTLS_LIBRARY=ON -DUSE_SHARED_MBEDTLS_LIBRARY=OFF -DINSTALL_MBEDTLS_HEADERS=ON  -DCMAKE_INSTALL_PREFIX="${build_target}" ..
	make -j$(nproc)
	make install -j$(nproc)
	cd ..
	popd

	pushd "${build_target}"
	ln -s lib lib64
	popd

	export CC=riscv64-linux-gnu-gcc
	export CXX=riscv64-linux-gnu-g++
	export LD=riscv64-linux-gnu-ld
	export AR=riscv64-linux-gnu-ar
	export CROSS_COMPILE=riscv64-linux-gnu-

	## libssh2 static
	pushd "${build_shell}/libssh2"
	make clean 2>/dev/null || true

	./configure --host=riscv64-pc-linux --disable-examples-build --disable-sshd-tests --disable-docker-tests --with-sysroot="${build_target}" --enable-static=yes --enable-shared=no --with-libmbedcrypto-prefix="${build_target}" --prefix="${build_target}" --with-crypto=mbedtls --with-libz --with-libz-prefix="${build_target}"
	unset CC
	unset CXX
	unset LD
	unset AR
	unset CROSS_COMPILE
	make clean
	make -j$(nproc) VERBOSE=1 || exit 1
	make install -j$(nproc)
	popd #libssh2
elif [[ "$1" == "armbi" ]]; then
	arm-linux-gnueabi-gcc -v || exit 1

	rm -rf armbi_build
	mkdir -p armbi_build
	export CROSS_COMPILE=arm-linux-gnueabi-

	## zlib static
	pushd "${build_shell}/zlib"
	CC=${CROSS_COMPILE}gcc CFLAGS="-O3 -fPIC" ./configure --prefix="${build_target}" --static
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #zlib

	## mbedtls static
	pushd "${build_shell}/mbedtls"
	mkdir build
	cd build
	CC=${CROSS_COMPILE}gcc SHARED=1 cmake -DCMAKE_BUILD_TYPE=Release -DENABLE_TESTING=OFF -DUSE_STATIC_MBEDTLS_LIBRARY=ON -DUSE_SHARED_MBEDTLS_LIBRARY=OFF -DINSTALL_MBEDTLS_HEADERS=ON  -DCMAKE_INSTALL_PREFIX="${build_target}" ..
	make -j$(nproc)
	make install -j$(nproc)
	cd ..
	popd

	export CC=arm-linux-gnueabi-gcc
	export CXX=arm-linux-gnueabi-g++
	export LD=arm-linux-gnueabi-ld
	export AR=arm-linux-gnueabi-ar
	export CROSS_COMPILE=arm-linux-gnueabi-

	## libssh2 static
	pushd "${build_shell}/libssh2"
	make clean 2>/dev/null || true

	./configure --host=arm-pc-linux --disable-examples-build --disable-sshd-tests --disable-docker-tests --with-sysroot="${build_target}" --enable-static=yes --enable-shared=no --with-libmbedcrypto-prefix="${build_target}" --prefix="${build_target}" --with-crypto=mbedtls --with-libz --with-libz-prefix="${build_target}"
	unset CC
	unset CXX
	unset LD
	unset AR
	unset CROSS_COMPILE
	make clean
	make -j$(nproc) VERBOSE=1 || exit 1
	make install -j$(nproc)
	popd #libssh2
elif [[ "$1" == "sw_64" ]]; then
	## sw_64 cross tools must at /usr/sw/
	sw_64-sunway-linux-gnu-gcc -v || exit 1

	rm -rf sw_64_build
	mkdir -p sw_64_build
	export CROSS_COMPILE=sw_64-sunway-linux-gnu-

	## zlib static
	pushd "${build_shell}/zlib"
	CC=${CROSS_COMPILE}gcc CFLAGS="-O3 -fPIC" ./configure --prefix="${build_target}" --static
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #zlib

	## mbedtls static
	pushd "${build_shell}/mbedtls"
	mkdir build
	cd build
	CC=${CROSS_COMPILE}gcc SHARED=1 cmake -DCMAKE_BUILD_TYPE=Release -DENABLE_TESTING=OFF -DUSE_STATIC_MBEDTLS_LIBRARY=ON -DUSE_SHARED_MBEDTLS_LIBRARY=OFF -DINSTALL_MBEDTLS_HEADERS=ON  -DCMAKE_INSTALL_PREFIX="${build_target}" ..
	make -j$(nproc)
	make install -j$(nproc)
	cd ..
	popd

	pushd "${build_target}"
	ln -s lib lib64
	popd

	export CC=sw_64-sunway-linux-gnu-gcc
	export CXX=sw_64-sunway-linux-gnu-g++
	export LD=sw_64-sunway-linux-gnu-ld
	export AR=sw_64-sunway-linux-gnu-ar
	export CROSS_COMPILE=sw_64-sunway-linux-gnu-

	## libssh2 static
	pushd "${build_shell}/libssh2"
	make clean 2>/dev/null || true

	./configure --host=alpha-pc-linux --disable-examples-build --disable-sshd-tests --disable-docker-tests --with-sysroot="${build_target}" --enable-static=yes --enable-shared=no --with-libmbedcrypto-prefix="${build_target}" --prefix="${build_target}" --with-crypto=mbedtls --with-libz --with-libz-prefix="${build_target}"
	unset CC
	unset CXX
	unset LD
	unset AR
	unset CROSS_COMPILE
	make clean
	make -j$(nproc) VERBOSE=1 || exit 1
	make install -j$(nproc)
	popd #libssh2
elif [[ "$1" == "darwin" ]]; then
	# macOS 本机编译（x86_64 / arm64 取决于当前 Mac），交叉编译 darwin 需要 macOS SDK，仅本机构建
	if [[ "$(uname -s)" != "Darwin" ]]; then
		echo "ERROR: darwin 目标必须在 macOS 主机上构建（需要 macOS SDK/工具链）。非 macOS 主机请构建 linux/win 目标。" >&2
		exit 1
	fi
	rm -rf darwin_build
	mkdir -p darwin_build
	unset CROSS_COMPILE
	unset CC
	unset CXX

	make_procs="$(sysctl -n hw.ncpu 2>/dev/null || echo 1)"

	## zlib static
	pushd "${build_shell}/zlib"
	CC=gcc ./configure --prefix="${build_target}" --static
	make clean
	make -j"${make_procs}"
	make install -j"${make_procs}"
	popd #zlib

	## mbedtls static
	pushd "${build_shell}/mbedtls"
	mkdir -p build
	cd build
	cmake -DCMAKE_BUILD_TYPE=Release -DENABLE_TESTING=OFF -DUSE_STATIC_MBEDTLS_LIBRARY=ON -DUSE_SHARED_MBEDTLS_LIBRARY=OFF -DINSTALL_MBEDTLS_HEADERS=ON -DCMAKE_INSTALL_PREFIX="${build_target}" ..
	make -j"${make_procs}"
	make install -j"${make_procs}"
	cd ..
	popd #mbedtls

	pushd "${build_target}"
	ln -s lib lib64 2>/dev/null || true
	popd

	## libssh2 static
	pushd "${build_shell}/libssh2"
	./configure --disable-examples-build --disable-sshd-tests --disable-docker-tests --with-sysroot="${build_target}" --enable-static=yes --enable-shared=no --with-libmbedcrypto-prefix="${build_target}" --prefix="${build_target}" --with-crypto=mbedtls --with-libz --with-libz-prefix="${build_target}"
	make clean
	make -j"${make_procs}" VERBOSE=1 || exit 1
	make install -j"${make_procs}"
	popd #libssh2
fi
