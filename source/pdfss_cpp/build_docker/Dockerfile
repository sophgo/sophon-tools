FROM ubuntu:20.04

SHELL ["/bin/bash", "-c"]

# Add apt sources
RUN cp -a /etc/apt/sources.list /etc/apt/sources.list.bak \
&& sed -i 's@//.*archive.ubuntu.com@//mirrors.ustc.edu.cn@g' /etc/apt/sources.list

# set ulimit
RUN ulimit -n 8192

# install pack
RUN export DEBIAN_FRONTEND=noninteractive \
&& apt-get update \
&& apt-get upgrade -y \
&& apt-get install -y --no-install-recommends \
android-sdk-ext4-utils android-sdk-libsparse-utils autoconf automake bc binfmt-support \
bison bsdmainutils build-essential bzip2 ca-certificates cmake cpio debootstrap g++-aarch64-linux-gnu \
device-tree-compiler dosfstools dpkg-dev exfat-utils fakeroot flex g++ g++-arm-linux-gnueabi \
g++-riscv64-linux-gnu gcc gcc-arm-none-eabi git git-lfs gitg gitk gdb curl \
kmod kpartx language-pack-en language-pack-zh-hans libboost-all-dev libevent-dev \
libgflags-dev libgoogle-glog-dev libisl-dev libncurses5 libncurses5-dev libprotobuf-dev \
libssl-dev libtool libxml2 libxml2-dev lrzsz lzop meld minicom nano ninja-build \
openssh-client openssh-server parallel p7zip-full pkg-config protobuf-compiler python3-dev \
python3-distutils python3-pip python3-sphinx qemu qemu-user qemu-user-static rsync pigz \
scons slib squashfs-tools sudo tcl texlive-xetex tree u-boot-tools uuid uuid-dev vim wget \
mingw-w64 mingw-w64-tools mingw-w64-i686-dev mingw-w64-common g++-mingw-w64 \
&& apt-get autoclean && apt clean
RUN python3 -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple \
&& python3 -m pip install dfss --upgrade -i https://pypi.tuna.tsinghua.edu.cn/simple
RUN curl https://mirrors.tuna.tsinghua.edu.cn/git/git-repo -o repo && mv repo /usr/bin/

# set work dir
WORKDIR /workspace

# copy files
RUN mkdir -p /env
COPY ./cross_build_tools /env
RUN pushd /env \
&& python3 -m dfss --url=open@sophgo.com:/toolchains/swgcc830-aad2d38bfa-202405-4253-cross-3231.tar.gz \
&& python3 -m dfss --url=open@sophgo.com:/toolchains/x86_64-cross-tools-loongarch64-binutils_2.43.1-gcc_14.2.0-glibc_2.40.tar.xz \
&& tar -I pigz -xf swgcc830-aad2d38bfa-202405-4253-cross-3231.tar.gz \
&& tar -I xz -xf x86_64-cross-tools-loongarch64-binutils_2.43.1-gcc_14.2.0-glibc_2.40.tar.xz \
&& mv /env/cross-tools /env/loongarch64-cross-tools-gcc_14.2.0 \
&& mkdir /usr/sw \
&& mv /env/swgcc830_cross_tools /usr/sw \
&& popd
RUN cat /env/bashrc_add.sh >> /root/.bashrc

# Set the locale
RUN git config --global --add safe.directory "*"
RUN locale-gen en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en
ENV LC_ALL en_US.UTF-8
