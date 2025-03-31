#! /bin/bash

unset build_shell
build_shell="$(dirname "$(readlink -f "$0")")"

unset CROSS_COMPILE
unset CC
unset CXX
unset ARCH
unset CROSS_COMPILE

sudo rm -rf libssh*
sudo rm -rf zlib*
sudo rm -rf mbedtls*

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
sudo rm -rf "${build_target}"

if [[ "$1" == "host" ]]; then
	# host gcc
	rm -rf host_build
	mkdir -p host_build
	unset CROSS_COMPILE

	## zlib static
	pushd "${build_shell}/zlib"
	CC=${CROSS_COMPILE}gcc ./configure --prefix="${build_target}" --static
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
	CC=${CROSS_COMPILE}gcc CC=${CROSS_COMPILE}gcc ./configure --prefix="${build_target}" --static
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
	make clean

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
	CC=${CROSS_COMPILE}gcc ./configure --prefix="${build_target}" --static
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #zlib

	## mbedtls static
	pushd "${build_shell}/mbedtls"
	mkdir build
	cd build
	WINDOWS=1 CC=${CROSS_COMPILE}gcc SHARED=0 cmake -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_SYSTEM_PROCESSOR=x86_64 -DCMAKE_BUILD_TYPE=Release -DENABLE_TESTING=OFF -DUSE_STATIC_MBEDTLS_LIBRARY=ON -DUSE_SHARED_MBEDTLS_LIBRARY=OFF -DINSTALL_MBEDTLS_HEADERS=ON  -DCMAKE_INSTALL_PREFIX="${build_target}" ..
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
	make clean

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
	CC=${CROSS_COMPILE}gcc ./configure --prefix="${build_target}" --static
	make clean
	make -j$(nproc)
	make install -j$(nproc)
	popd #zlib

	## mbedtls static
	pushd "${build_shell}/mbedtls"
	mkdir build
	cd build
	WINDOWS=1 CC=${CROSS_COMPILE}gcc SHARED=0 cmake -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_SYSTEM_PROCESSOR=i686 -DCMAKE_BUILD_TYPE=Release -DENABLE_TESTING=OFF -DUSE_STATIC_MBEDTLS_LIBRARY=ON -DUSE_SHARED_MBEDTLS_LIBRARY=OFF -DINSTALL_MBEDTLS_HEADERS=ON  -DCMAKE_INSTALL_PREFIX="${build_target}" ..
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
	make clean

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
	loongarch64-unknown-linux-gnu-gcc -v || exit 1

	rm -rf loongarch64_build
	mkdir -p loongarch64_build
	export CROSS_COMPILE=loongarch64-unknown-linux-gnu-

	## zlib static
	pushd "${build_shell}/zlib"
	CC=${CROSS_COMPILE}gcc ./configure --prefix="${build_target}" --static
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

	export CC=loongarch64-unknown-linux-gnu-gcc
	export CXX=loongarch64-unknown-linux-gnu-g++
	export LD=loongarch64-unknown-linux-gnu-ld
	export AR=loongarch64-unknown-linux-gnu-ar
	export CROSS_COMPILE=loongarch64-unknown-linux-gnu-

	## libssh2 static
	pushd "${build_shell}/libssh2"
	make clean

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
	CC=${CROSS_COMPILE}gcc ./configure --prefix="${build_target}" --static
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
	make clean

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
	CC=${CROSS_COMPILE}gcc ./configure --prefix="${build_target}" --static
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
	make clean

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
	CC=${CROSS_COMPILE}gcc ./configure --prefix="${build_target}" --static
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
	make clean

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
fi
