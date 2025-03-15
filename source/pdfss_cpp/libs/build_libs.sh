#! /bin/bash

unset build_shell
build_shell="$(dirname "$(readlink -f "$0")")"

unset CROSS_COMPILE
unset CC
unset CXX
unset ARCH
unset CROSS_COMPILE

sudo rm -rf openss*
sudo rm -rf libssh*
sudo rm -rf libssh
sudo rm -rf zlib*

tar -xaf "$(find ${build_shell}/zips/ -name "openssl*")" -C ./
mv openssl* openssl

tar -xaf "$(find ${build_shell}/zips/ -name "libssh-*")"
mv libssh-* libssh
rm -rf libssh-*

tar -xaf "$(find ${build_shell}/zips/ -name "libssh2-*")" -C ./
mv libssh2* libssh2

tar -xaf "$(find ${build_shell}/zips/ -name "zlib*")" -C ./
mv zlib* zlib

unset CC
unset CXX
unset LD
unset AR
unset CROSS_COMPILE

if [[ "$1" == "host" ]]; then
	# host gcc
	rm -rf host_build
	mkdir -p host_build

	## openssl static
	pushd "${build_shell}/openssl"

	./config no-shared no-asm --prefix="${build_shell}/host_build"
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #openssl

	# ## libssh2 static
	# pushd "${build_shell}/libssh2"
	# ./configure --disable-examples-build --disable-sshd-tests --disable-docker-tests --disable-tests --with-sysroot="${build_shell}/host_build" --enable-static=yes --enable-shared=no --with-libssl-prefix="${build_shell}/host_build" --prefix="${build_shell}/host_build" --with-crypto=openssl --without-libz
	# make clean
	# make -j$(nproc)
	# make install -j$(nproc)
	# popd #libssh2

	## libssh static
	pushd "${build_shell}/libssh"
	mkdir build
	pushd build
	cmake -DCMAKE_INSTALL_PREFIX="${build_shell}/host_build" -DOPENSSL_ROOT_DIR="${build_shell}/host_build" -DCMAKE_BUILD_TYPE=Release -DWITH_ZLIB=OFF -DBUILD_STATIC_LIB=ON -DBUILD_SHARED_LIBS=OFF -DWITH_EXAMPLES=OFF -DWITH_BENCHMARKS=OFF -DWITH_SERVER=OFF -DWITH_DEBUG_CALLTRACE=OFF -DWITH_GSSAPI=OFF ..
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #build
	popd #libssh
elif [[ "$1" == "aarch64" ]]; then
	aarch64-linux-gnu-gcc -v || exit 1
	# aarch64 gcc
	rm -rf aarch64_build
	mkdir -p aarch64_build
	export CROSS_COMPILE=aarch64-linux-gnu-
	## openssl static
	pushd "${build_shell}/openssl"
	make clean
	./config no-shared no-asm --prefix="${build_shell}/aarch64_build" linux-aarch64
	make clean
	make -j$(nproc) VERBOSE=1 || exit 1
	make install -j$(nproc)
	popd #openssl

	# export CC=aarch64-linux-gnu-gcc
	# export CXX=aarch64-linux-gnu-g++
	# export LD=aarch64-linux-gnu-ld
	# export AR=aarch64-linux-gnu-ar
	# export CROSS_COMPILE=aarch64-linux-gnu-

	# ## libssh2 static
	# pushd "${build_shell}/libssh2"
	# make clean

	# ./configure --disable-examples-build --disable-sshd-tests --disable-docker-tests --disable-tests --host=aarch64-linux-gnu --with-sysroot="${build_shell}/aarch64_build" --enable-static=yes --enable-shared=no --with-libssl-prefix="${build_shell}/aarch64_build" --prefix="${build_shell}/aarch64_build" --with-crypto=openssl
	# unset CC
	# unset CXX
	# unset LD
	# unset AR
	# make clean
	# make -j$(nproc) VERBOSE=1 || exit 1
	# make install -j$(nproc)
	# popd #libssh2

	## libssh static
	pushd "${build_shell}/libssh"
	mkdir build
	pushd build
	COMPILER_P="aarch64-linux-gnu-"
	cmake -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_C_COMPILER=${COMPILER_P}gcc -DCMAKE_ADDR2LINE=${COMPILER_P}addr2line -DCMAKE_C_COMPILER_AR=${COMPILER_P}ar -DCMAKE_CXX_COMPILER_AR=${COMPILER_P}ar -DCMAKE_LINKER=${COMPILER_P}ld -DCMAKE_CXX_COMPILER=${COMPILER_P}g++ -DCMAKE_INSTALL_PREFIX="${build_shell}/aarch64_build" -DOPENSSL_ROOT_DIR="${build_shell}/aarch64_build" -DCMAKE_BUILD_TYPE=Release -DWITH_ZLIB=OFF -DBUILD_STATIC_LIB=ON -DBUILD_SHARED_LIBS=OFF -DWITH_EXAMPLES=OFF -DWITH_BENCHMARKS=OFF -DWITH_SERVER=OFF -DWITH_DEBUG_CALLTRACE=OFF -DWITH_GSSAPI=OFF ..
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #build
	popd #libssh
elif [[ "$1" == "mingw64" ]]; then
	x86_64-w64-mingw32-gcc -v || exit 1
	# mingw64 gcc
	rm -rf win64_build
	mkdir -p win64_build
	export CROSS_COMPILE=x86_64-w64-mingw32-
	## openssl static
	pushd "${build_shell}/openssl"
	make clean
	./config no-shared no-asm --prefix="${build_shell}/win64_build" mingw64
	make clean
	make -j$(nproc) VERBOSE=1 || exit 1
	make install -j$(nproc)
	popd #openssl

	pushd "${build_shell}/win64_build"
	ln -s lib64 lib
	popd

	# export CC=x86_64-w64-mingw32-gcc
	# export CXX=x86_64-w64-mingw32-g++
	# export LD=x86_64-w64-mingw32-ld
	# export AR=x86_64-w64-mingw32-ar
	# export CROSS_COMPILE=x86_64-w64-mingw32-

	# ## libssh2 static
	# pushd "${build_shell}/libssh2"
	# make clean

	# ./configure --host=x86_64-pc-mingw64 --disable-examples-build --disable-sshd-tests --disable-docker-tests --disable-tests --with-sysroot="${build_shell}/win64_build" --enable-static=yes --enable-shared=no --with-libssl-prefix="${build_shell}/win64_build" --prefix="${build_shell}/win64_build" --with-crypto=openssl
	# unset CC
	# unset CXX
	# unset LD
	# unset AR
	# unset CROSS_COMPILE
	# make clean
	# make -j$(nproc) VERBOSE=1 || exit 1
	# make install -j$(nproc)
	# popd #libssh2

	## libssh static
	pushd "${build_shell}/libssh"
	mkdir build
	pushd build
	COMPILER_P="x86_64-w64-mingw32-"
	cmake -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_C_COMPILER=${COMPILER_P}gcc -DCMAKE_ADDR2LINE=${COMPILER_P}addr2line -DCMAKE_C_COMPILER_AR=${COMPILER_P}ar -DCMAKE_CXX_COMPILER_AR=${COMPILER_P}ar -DCMAKE_LINKER=${COMPILER_P}ld -DCMAKE_CXX_COMPILER=${COMPILER_P}g++ -DCMAKE_INSTALL_PREFIX="${build_shell}/win64_build" -DOPENSSL_ROOT_DIR="${build_shell}/win64_build" -DCMAKE_BUILD_TYPE=Release -DWITH_ZLIB=OFF -DBUILD_STATIC_LIB=ON -DBUILD_SHARED_LIBS=OFF -DWITH_EXAMPLES=OFF -DWITH_BENCHMARKS=OFF -DWITH_SERVER=OFF -DWITH_DEBUG_CALLTRACE=OFF -DWITH_GSSAPI=OFF ..
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #build
	popd #libssh
elif [[ "$1" == "mingw" ]]; then
	i686-w64-mingw32-gcc -v || exit 1
	# mingw gcc
	rm -rf win32_build
	mkdir -p win32_build
	export CROSS_COMPILE=i686-w64-mingw32-
	## openssl static
	pushd "${build_shell}/openssl"
	make clean
	./config no-shared no-asm --prefix="${build_shell}/win32_build" mingw
	make clean
	make -j$(nproc) VERBOSE=1 || exit 1
	make install -j$(nproc)
	popd #openssl

	pushd "${build_shell}/win32_build"
	ln -s lib64 lib
	popd

	# export CC=i686-w64-mingw32-gcc
	# export CXX=i686-w64-mingw32-g++
	# export LD=i686-w64-mingw32-ld
	# export AR=i686-w64-mingw32-ar
	# export CROSS_COMPILE=i686-w64-mingw32-

	# ## libssh2 static
	# pushd "${build_shell}/libssh2"
	# make clean

	# ./configure --host=i686-pc-mingw32 --disable-examples-build --disable-sshd-tests --disable-docker-tests --disable-tests --with-sysroot="${build_shell}/win32_build" --enable-static=yes --enable-shared=no --with-libssl-prefix="${build_shell}/win32_build" --prefix="${build_shell}/win32_build" --with-crypto=openssl
	# unset CC
	# unset CXX
	# unset LD
	# unset AR
	# unset CROSS_COMPILE
	# make clean
	# make -j$(nproc) VERBOSE=1 || exit 1
	# make install -j$(nproc)
	# popd #libssh2

	## libssh static
	pushd "${build_shell}/libssh"
	mkdir build
	pushd build
	COMPILER_P="i686-w64-mingw32-"
	cmake -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_C_COMPILER=${COMPILER_P}gcc -DCMAKE_ADDR2LINE=${COMPILER_P}addr2line -DCMAKE_C_COMPILER_AR=${COMPILER_P}ar -DCMAKE_CXX_COMPILER_AR=${COMPILER_P}ar -DCMAKE_LINKER=${COMPILER_P}ld -DCMAKE_CXX_COMPILER=${COMPILER_P}g++ -DCMAKE_INSTALL_PREFIX="${build_shell}/win32_build" -DOPENSSL_ROOT_DIR="${build_shell}/win32_build" -DCMAKE_BUILD_TYPE=Release -DWITH_ZLIB=OFF -DBUILD_STATIC_LIB=ON -DBUILD_SHARED_LIBS=OFF -DWITH_EXAMPLES=OFF -DWITH_BENCHMARKS=OFF -DWITH_SERVER=OFF -DWITH_DEBUG_CALLTRACE=OFF -DWITH_GSSAPI=OFF ..
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #build
	popd #libssh
elif [[ "$1" == "loongarch64" ]]; then
	loongarch64-linux-gnu-gcc -v || exit 1
	# mingw gcc
	rm -rf loongarch64_build
	mkdir -p loongarch64_build
	export CROSS_COMPILE=loongarch64-linux-gnu-
	## openssl static
	pushd "${build_shell}/openssl"
	make clean
	./config no-shared no-asm --prefix="${build_shell}/loongarch64_build" linux64-loongarch64
	make clean
	make -j$(nproc) VERBOSE=1 || exit 1
	make install -j$(nproc)
	popd #openssl

	pushd "${build_shell}/loongarch64_build"
	ln -s lib64 lib
	popd

	# export CC=loongarch64-linux-gnu-gcc
	# export CXX=loongarch64-linux-gnu-g++
	# export LD=loongarch64-linux-gnu-ld
	# export AR=loongarch64-linux-gnu-ar
	# export CROSS_COMPILE=loongarch64-linux-gnu-

	# ## libssh2 static
	# pushd "${build_shell}/libssh2"
	# make clean

	# ./configure --host=loongarch64-pc-linux --disable-examples-build --disable-sshd-tests --disable-docker-tests --disable-tests --with-sysroot="${build_shell}/loongarch64_build" --enable-static=yes --enable-shared=no --with-libssl-prefix="${build_shell}/loongarch64_build" --prefix="${build_shell}/loongarch64_build" --with-crypto=openssl
	# unset CC
	# unset CXX
	# unset LD
	# unset AR
	# unset CROSS_COMPILE
	# make clean
	# make -j$(nproc) VERBOSE=1 || exit 1
	# make install -j$(nproc)
	# popd #libssh2

	## libssh static
	pushd "${build_shell}/libssh"
	mkdir build
	pushd build
	COMPILER_P="loongarch64-linux-gnu-"
	cmake -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_C_COMPILER=${COMPILER_P}gcc -DCMAKE_ADDR2LINE=${COMPILER_P}addr2line -DCMAKE_C_COMPILER_AR=${COMPILER_P}ar -DCMAKE_CXX_COMPILER_AR=${COMPILER_P}ar -DCMAKE_LINKER=${COMPILER_P}ld -DCMAKE_CXX_COMPILER=${COMPILER_P}g++ -DCMAKE_INSTALL_PREFIX="${build_shell}/loongarch64_build" -DOPENSSL_ROOT_DIR="${build_shell}/loongarch64_build" -DCMAKE_BUILD_TYPE=Release -DWITH_ZLIB=OFF -DBUILD_STATIC_LIB=ON -DBUILD_SHARED_LIBS=OFF -DWITH_EXAMPLES=OFF -DWITH_BENCHMARKS=OFF -DWITH_SERVER=OFF -DWITH_DEBUG_CALLTRACE=OFF -DWITH_GSSAPI=OFF ..
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #build
	popd #libssh
elif [[ "$1" == "riscv64" ]]; then
	riscv64-linux-gnu-gcc -v || exit 1
	# mingw gcc
	rm -rf riscv64_build
	mkdir -p riscv64_build
	export CROSS_COMPILE=riscv64-linux-gnu-
	## openssl static
	pushd "${build_shell}/openssl"
	make clean
	./config no-shared no-asm --prefix="${build_shell}/riscv64_build" linux64-riscv64
	make clean
	make -j$(nproc) VERBOSE=1 || exit 1
	make install -j$(nproc)
	popd #openssl

	pushd "${build_shell}/riscv64_build"
	ln -s lib64 lib
	popd

	# export CC=riscv64-linux-gnu-gcc
	# export CXX=riscv64-linux-gnu-g++
	# export LD=riscv64-linux-gnu-ld
	# export AR=riscv64-linux-gnu-ar
	# export CROSS_COMPILE=riscv64-linux-gnu-

	# ## libssh2 static
	# pushd "${build_shell}/libssh2"
	# make clean

	# ./configure --host=riscv64-pc-linux --disable-examples-build --disable-sshd-tests --disable-docker-tests --disable-tests --with-sysroot="${build_shell}/riscv64_build" --enable-static=yes --enable-shared=no --with-libssl-prefix="${build_shell}/riscv64_build" --prefix="${build_shell}/riscv64_build" --with-crypto=openssl
	# unset CC
	# unset CXX
	# unset LD
	# unset AR
	# unset CROSS_COMPILE
	# make clean
	# make -j$(nproc) VERBOSE=1 || exit 1
	# make install -j$(nproc)
	# popd #libssh2

	## libssh static
	pushd "${build_shell}/libssh"
	mkdir build
	pushd build
	COMPILER_P="riscv64-linux-gnu-"
	cmake -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_C_COMPILER=${COMPILER_P}gcc -DCMAKE_ADDR2LINE=${COMPILER_P}addr2line -DCMAKE_C_COMPILER_AR=${COMPILER_P}ar -DCMAKE_CXX_COMPILER_AR=${COMPILER_P}ar -DCMAKE_LINKER=${COMPILER_P}ld -DCMAKE_CXX_COMPILER=${COMPILER_P}g++ -DCMAKE_INSTALL_PREFIX="${build_shell}/riscv64_build" -DOPENSSL_ROOT_DIR="${build_shell}/riscv64_build" -DCMAKE_BUILD_TYPE=Release -DWITH_ZLIB=OFF -DBUILD_STATIC_LIB=ON -DBUILD_SHARED_LIBS=OFF -DWITH_EXAMPLES=OFF -DWITH_BENCHMARKS=OFF -DWITH_SERVER=OFF -DWITH_DEBUG_CALLTRACE=OFF -DWITH_GSSAPI=OFF ..
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #build
	popd #libssh
elif [[ "$1" == "armbi" ]]; then
	arm-linux-gnueabi-gcc -v || exit 1
	# mingw gcc
	rm -rf armbi_build
	mkdir -p armbi_build
	export CROSS_COMPILE=arm-linux-gnueabi-
	## openssl static
	pushd "${build_shell}/openssl"
	make clean
	./config no-shared no-asm --prefix="${build_shell}/armbi_build" linux-armv4
	make clean
	make -j$(nproc) VERBOSE=1 || exit 1
	make install -j$(nproc)
	popd #openssl

	pushd "${build_shell}/armbi_build"
	ln -s lib64 lib
	popd

	# export CC=arm-linux-gnueabi-gcc
	# export CXX=arm-linux-gnueabi-g++
	# export LD=arm-linux-gnueabi-ld
	# export AR=arm-linux-gnueabi-ar
	# export CROSS_COMPILE=arm-linux-gnueabi-

	# ## libssh2 static
	# pushd "${build_shell}/libssh2"
	# make clean

	# ./configure --host=arm-pc-linux --disable-examples-build --disable-sshd-tests --disable-docker-tests --disable-tests --with-sysroot="${build_shell}/armbi_build" --enable-static=yes --enable-shared=no --with-libssl-prefix="${build_shell}/armbi_build" --prefix="${build_shell}/armbi_build" --with-crypto=openssl
	# unset CC
	# unset CXX
	# unset LD
	# unset AR
	# unset CROSS_COMPILE
	# make clean
	# make -j$(nproc) VERBOSE=1 || exit 1
	# make install -j$(nproc)
	# popd #libssh2

	## libssh static
	pushd "${build_shell}/libssh"
	mkdir build
	pushd build
	COMPILER_P="arm-linux-gnueabi-"
	cmake -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_C_COMPILER=${COMPILER_P}gcc -DCMAKE_ADDR2LINE=${COMPILER_P}addr2line -DCMAKE_C_COMPILER_AR=${COMPILER_P}ar -DCMAKE_CXX_COMPILER_AR=${COMPILER_P}ar -DCMAKE_LINKER=${COMPILER_P}ld -DCMAKE_CXX_COMPILER=${COMPILER_P}g++ -DCMAKE_INSTALL_PREFIX="${build_shell}/armbi_build" -DOPENSSL_ROOT_DIR="${build_shell}/armbi_build" -DCMAKE_BUILD_TYPE=Release -DWITH_ZLIB=OFF -DBUILD_STATIC_LIB=ON -DBUILD_SHARED_LIBS=OFF -DWITH_EXAMPLES=OFF -DWITH_BENCHMARKS=OFF -DWITH_SERVER=OFF -DWITH_DEBUG_CALLTRACE=OFF -DWITH_GSSAPI=OFF ..
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #build
	popd #libssh
elif [[ "$1" == "sw_64" ]]; then
	## sw_64 cross tools must at /usr/sw/
	sw_64-sunway-linux-gnu-gcc -v || exit 1
	# mingw gcc
	rm -rf sw_64_build
	mkdir -p sw_64_build
	export CROSS_COMPILE=sw_64-sunway-linux-gnu-
	## openssl static
	pushd "${build_shell}/openssl"
	make clean
	./config no-shared no-asm --prefix="${build_shell}/sw_64_build" linux-alpha-gcc
	make clean
	make -j$(nproc) VERBOSE=1 || exit 1
	make install -j$(nproc)
	popd #openssl

	pushd "${build_shell}/sw_64_build"
	ln -s lib64 lib
	popd

	# export CC=sw_64-sunway-linux-gnu-gcc
	# export CXX=sw_64-sunway-linux-gnu-g++
	# export LD=sw_64-sunway-linux-gnu-ld
	# export AR=sw_64-sunway-linux-gnu-ar
	# export CROSS_COMPILE=sw_64-sunway-linux-gnu-

	# ## libssh2 static
	# pushd "${build_shell}/libssh2"
	# make clean

	# ./configure --host=alpha-pc-linux --disable-examples-build --disable-sshd-tests --disable-docker-tests --disable-tests --with-sysroot="${build_shell}/sw_64_build" --enable-static=yes --enable-shared=no --with-libssl-prefix="${build_shell}/sw_64_build" --prefix="${build_shell}/sw_64_build" --with-crypto=openssl
	# unset CC
	# unset CXX
	# unset LD
	# unset AR
	# unset CROSS_COMPILE
	# make clean
	# make -j$(nproc) VERBOSE=1 || exit 1
	# make install -j$(nproc)
	# popd #libssh2

	## libssh static
	pushd "${build_shell}/libssh"
	mkdir build
	pushd build
	COMPILER_P="sw_64-sunway-linux-gnu-"
	cmake -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_C_COMPILER=${COMPILER_P}gcc -DCMAKE_ADDR2LINE=${COMPILER_P}addr2line -DCMAKE_C_COMPILER_AR=${COMPILER_P}ar -DCMAKE_CXX_COMPILER_AR=${COMPILER_P}ar -DCMAKE_LINKER=${COMPILER_P}ld -DCMAKE_CXX_COMPILER=${COMPILER_P}g++ -DCMAKE_INSTALL_PREFIX="${build_shell}/sw_64_build" -DOPENSSL_ROOT_DIR="${build_shell}/sw_64_build" -DCMAKE_BUILD_TYPE=Release -DWITH_ZLIB=OFF -DBUILD_STATIC_LIB=ON -DBUILD_SHARED_LIBS=OFF -DWITH_EXAMPLES=OFF -DWITH_BENCHMARKS=OFF -DWITH_SERVER=OFF -DWITH_DEBUG_CALLTRACE=OFF -DWITH_GSSAPI=OFF ..
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #build
	popd #libssh
fi
