# syntax=docker/dockerfile:1
# =============================================================================
# sophon-tools-build —— sophon-tools 16 子项目统一编译镜像（M5 单镜像合并）
#
# 设计:
#   * 基座 ubuntu:20.04（glibc 2.31）: 满足 pqt AppImage 的 linuxdeployqt 硬约束
#     (glibc<=2.31)，同时作为全部子项目唯一基座，替代 M4 的三镜像方案:
#        - 旧 sophon-tools-build:m2      (ubuntu:22.04 主镜像)  -> 本镜像
#        - 旧 sophon-tools-build-pqt     (ubuntu:20.04 pqt 专用) -> 本镜像(合并 pqt 依赖)
#        - 旧 cross_build_sophon_u20:v1  (ubuntu:20.04 pSophUI)  -> 本镜像(并入 aarch64 Qt)
#   * 多阶段构建: Stage1 下载并校验国外大体积工具链(Go/Node); Stage2 汇入运行镜像。
#     pSophUI 的 aarch64 Qt 库(Stage3 独立镜像 cross_build_sophon_u20:v1)已并入本镜像,
#     通过 toolchains/sophui-cross-toolchains.tar.zst 归档内置, 不再依赖独立镜像。
#   * 版本唯一来源 docker/versions.env(由 docker/build.sh 注入 ARG), 全部版本锁定。
#   * 交叉工具链: apt 精确版本(glibc) + musl.cc(静态) + dfss 私有工具链(sw_64/loongarch64)。
#   * dfss 私有工具链默认不内置(私有源, 体积大); 通过 --with-dfss-toolchains 或构建上下文
#     toolchains/ 目录内置。
#   * Qt mingw 静态库(pqt windows exe 依赖)默认不内置; 通过 --with-qt-mingw 或构建上下文
#     toolchains/qt-mingw/ 目录内置。
#   * pSophUI 交叉 Qt 库(aarch64 Qt 5.12.8)默认不内置(约 300MB, 私有源);
#     通过 --with-sophui-toolchain 或构建上下文 toolchains/sophui-cross-toolchains.tar.zst 内置。
#     pSophUI 编译用系统 apt aarch64-linux-gnu-gcc 9.4(Linaro GCC 6.3 已移除)。
#
# 构建(一条命令):  bash docker/build.sh
# 构建(含私有工具链): bash docker/build.sh --with-dfss-toolchains --with-qt-mingw --with-sophui-toolchain
# =============================================================================

# ---- ARG 集合(由 build.sh 从 versions.env 注入) ----
ARG UBUNTU_BASE_DIGEST
ARG GO_VERSION GO_TARBALL_URL GO_TARBALL_SHA256
ARG RUST_VERSION
ARG NODE_TARBALL_URL NODE_TARBALL_SHA256
ARG PNPM_VERSION YARN_VERSION
ARG MUSL_AARCH64_URL MUSL_AARCH64_SHA256 MUSL_X86_64_URL MUSL_X86_64_SHA256
ARG UPX_TARBALL_URL UPX_TARBALL_SHA256
ARG WITH_DFSS=0
ARG WITH_QT_MINGW=0
ARG WITH_SOPHUI=0

# ---- Stage 1: 下载 + 校验(仅构建期需要, 不进入最终镜像) ----
FROM ${UBUNTU_BASE_DIGEST} AS downloader
ARG GO_VERSION GO_TARBALL_URL GO_TARBALL_SHA256
ARG NODE_TARBALL_URL NODE_TARBALL_SHA256
ARG RUST_VERSION
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl xz-utils bzip2 zstd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /dl
# Go 工具链: 下载 + SHA256 校验
RUN curl -fsSL "${GO_TARBALL_URL}" -o go.tar.gz \
    && echo "${GO_TARBALL_SHA256}  go.tar.gz" | sha256sum -c - \
    && tar -C /opt -xzf go.tar.gz \
    && /opt/go/bin/go version
# Node.js: 下载 + SHA256 校验
RUN curl -fsSL "${NODE_TARBALL_URL}" -o node.tar.xz \
    && echo "${NODE_TARBALL_SHA256}  node.tar.xz" | sha256sum -c - \
    && mkdir -p /opt/nodejs && tar -C /opt/nodejs --strip-components=1 -xJf node.tar.xz \
    && /opt/nodejs/bin/node --version

# ---- Stage 2: 最终运行镜像 ----
FROM ${UBUNTU_BASE_DIGEST}
ARG GO_VERSION RUST_VERSION PNPM_VERSION YARN_VERSION WITH_DFSS WITH_QT_MINGW WITH_SOPHUI

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH="/opt/go/bin:/opt/nodejs/bin:/opt/rust/bin:/opt/musl/aarch64-linux-musl-cross/bin:/opt/musl/x86_64-linux-musl-cross/bin:/usr/local/go/bin:${PATH}"

SHELL ["/bin/bash", "-c"]

# ---- 系统依赖 + apt 交叉工具链(精确版本, 由 ubuntu:20.04 仓库固定) ----
# pdfss_cpp 8 架构: aarch64/armel/riscv64 + mingw-w64(windows amd64/i686)
# Rust/Go 静态: musl 工具链在 PATH(由 pbmssm 的 fetch-musl-toolchain.sh 识别复用)
# pqt 系列: qtbase5-dev(Qt 5.12.8, 20.04 仓库) + libgl1-mesa-dev + fuse + patchelf(AppImage)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc g++ make cmake pkg-config \
        gcc-aarch64-linux-gnu g++-aarch64-linux-gnu \
        gcc-arm-linux-gnueabi g++-arm-linux-gnueabi \
        gcc-riscv64-linux-gnu g++-riscv64-linux-gnu \
        gcc-mingw-w64-x86-64 g++-mingw-w64-x86-64 gcc-mingw-w64-i686 g++-mingw-w64-i686 \
        dpkg dpkg-dev fakeroot \
        qtbase5-dev qttools5-dev-tools \
        libgl1-mesa-dev libglib2.0-0 \
        ca-certificates curl wget git \
        zip unzip p7zip-full patchelf \
        python3 python3-pip python3-dev \
        brotli zstd xz-utils bzip2 \
        libssl-dev libtool autoconf automake \
        file binutils \
        qemu-user qemu-user-static binfmt-support \
        libfuse2 fuse ssh strace pandoc sudo \
    && rm -rf /var/lib/apt/lists/*

# ---- upx(固定 4.x, 静态链接; 替代 ubuntu 仓库 upx-ucl 3.95) ----
# upx 3.x 不支持压缩 static-pie(Rust musl 静态产物), 统一镜像内压缩会静默失败(MYS-58 O-2)。
# 固定 4.2.4 静态二进制, 下载即校验 SHA256(versions.env 锁定)。
ARG UPX_TARBALL_URL UPX_TARBALL_SHA256
RUN curl -fsSL "${UPX_TARBALL_URL}" -o /tmp/upx.tar.xz \
    && echo "${UPX_TARBALL_SHA256}  /tmp/upx.tar.xz" | sha256sum -c - \
    && tar -C /usr/local/bin -xJf /tmp/upx.tar.xz --strip-components=1 --wildcards '*/upx' \
    && rm /tmp/upx.tar.xz \
    && upx --version | head -1

# ---- Go(来自 Stage1, 已校验) ----
COPY --from=downloader /opt/go /opt/go
RUN /opt/go/bin/go version

# ---- Node.js + pnpm + yarn(来自 Stage1, 已校验) ----
COPY --from=downloader /opt/nodejs /opt/nodejs
ENV PATH="/opt/nodejs/bin:${PATH}"
RUN npm install -g "pnpm@${PNPM_VERSION}" "yarn@${YARN_VERSION}" \
    && node --version && pnpm --version && yarn --version

# ---- Rust(rustup 锁定版本, 含 aarch64/x86_64 musl + gnu target + 交叉链接器) ----
RUN curl -fsSL https://sh.rustup.rs -o /tmp/rustup-init.sh \
    && chmod +x /tmp/rustup-init.sh \
    && RUSTUP_HOME=/opt/rust CARGO_HOME=/opt/cargo /tmp/rustup-init.sh \
        -y --default-toolchain "${RUST_VERSION}" \
        --profile minimal \
        --component clippy --component rustfmt \
    && rm /tmp/rustup-init.sh
ENV RUSTUP_HOME=/opt/rust CARGO_HOME=/opt/cargo \
    PATH="/opt/cargo/bin:${PATH}"
RUN rustup target add aarch64-unknown-linux-musl aarch64-unknown-linux-gnu \
                             x86_64-unknown-linux-musl \
    && rustc --version && cargo --version \
    && mkdir -p "${CARGO_HOME}" \
    && printf '[target.aarch64-unknown-linux-musl]\nlinker = "aarch64-linux-musl-gcc"\nrustflags = ["-C", "link-arg=-s"]\n' > "${CARGO_HOME}/config.toml"

# ---- musl 交叉工具链(静态链接: pbmssm/psophliteos/pbm_set_ip) ----
# 预置 aarch64 + x86_64; 下载即校验 SHA256(versions.env 锁定); 若构建期网络受限,
# 子项目脚本会自行从 musl.cc 拉取。
ARG MUSL_AARCH64_URL MUSL_AARCH64_SHA256 MUSL_X86_64_URL MUSL_X86_64_SHA256
RUN mkdir -p /opt/musl \
    && curl -fsSL "${MUSL_AARCH64_URL}" -o /tmp/musl-aarch64.tgz \
    && echo "${MUSL_AARCH64_SHA256}  /tmp/musl-aarch64.tgz" | sha256sum -c - \
    && tar -C /opt/musl -xzf /tmp/musl-aarch64.tgz && rm /tmp/musl-aarch64.tgz \
    && curl -fsSL "${MUSL_X86_64_URL}" -o /tmp/musl-x86_64.tgz \
    && echo "${MUSL_X86_64_SHA256}  /tmp/musl-x86_64.tgz" | sha256sum -c - \
    && tar -C /opt/musl -xzf /tmp/musl-x86_64.tgz && rm /tmp/musl-x86_64.tgz \
    && aarch64-linux-musl-gcc --version | head -1 && x86_64-linux-musl-gcc --version | head -1

# ---- pSophUI 交叉 Qt 库(aarch64 Qt 5.12.8) ----
# 与 13.24 cross_build_sophon_u20:v1 一致, 保持 /env 原始路径。
# 来源: toolchains/sophui-cross-toolchains.tar.zst(由 export-sophui-toolchains.sh 从
#       13.24 cross_build_sophon_u20:v1 导出), 解压到 /env 原始路径。
# 注意: 仅含 aarch64 Qt 库, 不含交叉编译器——pSophUI 编译用系统 apt 的
#       aarch64-linux-gnu-gcc 9.4(source/pSophUI/release.sh 默认 CROSS_PREFIX=/usr),
#       替代原 Linaro GCC 6.3(已移除, 省约 731MB)。
# 不把 /env/qt_5.12.8_nosysroot/bin 加入全局 PATH——其含通用名 qmake/moc,
#       会遮蔽宿主机 Qt5 qmake, 破坏 pqt 系列(linuxdeployqt)构建。
#       pSophUI 的 release.sh 内部自行 export 自己的 qmake/gcc 到 PATH(见 source/pSophUI/release.sh)。
# 默认不内置(约 300MB, 私有源); 加 --with-sophui-toolchain 或构建上下文 toolchains/ 放
# sophui-cross-toolchains.tar.zst 自动内置（与 dfss 段语义一致）。
ARG WITH_SOPHUI=0
COPY toolchains/ /tmp/toolchains/
RUN if { [ "${WITH_SOPHUI}" = "1" ] || [ -f /tmp/toolchains/sophui-cross-toolchains.tar.zst ]; } \
       && [ -f /tmp/toolchains/sophui-cross-toolchains.tar.zst ]; then \
        mkdir -p /env \
        && tar -C /env -I zstd -xf /tmp/toolchains/sophui-cross-toolchains.tar.zst \
        && rm -f /tmp/toolchains/sophui-cross-toolchains.tar.zst \
        && rm -rf /env/qt_5.12.8_nosysroot/examples /env/qt_5.12.8_nosysroot/qml; \
    fi

# ---- Qt mingw 静态库(pqt windows exe 依赖) ----
# 构建上下文需含 qt-mingw.tar.zst 或 toolchains/qt-mingw/ 目录(由 build-qt-mingw.sh 在 20.04
# 基座内从源码编译)。默认不内置; 加 --with-qt-mingw 构建。
# 仅消费 qt-mingw 相关文件, 不触碰同目录下 dfss 归档。
ARG WITH_QT_MINGW=0
COPY toolchains/ /tmp/toolchains/
RUN if [ "${WITH_QT_MINGW}" = "1" ] && { [ -f /tmp/toolchains/qt-mingw.tar.zst ] || [ -d /tmp/toolchains/qt-mingw ]; }; then \
        mkdir -p /opt/qt-mingw \
        && if [ -f /tmp/toolchains/qt-mingw.tar.zst ]; then \
            tar -C /opt/qt-mingw -I zstd -xf /tmp/toolchains/qt-mingw.tar.zst; \
        else \
            cp -a /tmp/toolchains/qt-mingw/. /opt/qt-mingw/; \
        fi \
        && rm -rf /tmp/toolchains/qt-mingw /tmp/toolchains/qt-mingw.tar.zst; \
    fi

# ---- dfss 私有工具链(sw_64 / loongarch64) ----
# 构建上下文需含 toolchains/ 目录(由 export-dfss-toolchains.sh 导出), 或用 --with-dfss-toolchains。
# 注意: sw_64 工具链 gcc 编译期 prefix 硬编码为 /usr/sw/swgcc830_cross_tools,
#       loongarch64 硬编码为 /env/loongson-gnu-toolchain-8.3-x86_64-loongarch64-linux-gnu-rc1.1,
#       故解压到容器内原始路径, 保证绝对引用全部有效(与 13.24 源容器一致)。
# 重要: 不把 /usr/sw/.../bin 加入全局 PATH——其含通用名 ldd(sw64 glibc 版), 会遮蔽系统 ldd,
#       破坏 linuxdeployqt/pqt 等对宿主 ldd 的依赖(对 x86 二进制的解析)。dfss 工具链仅
#       pdfss_cpp 需要, 由 build-all.sh 的 EXTRA_ENV 按子项目注入 PATH。
ARG WITH_DFSS=0
RUN if { [ "${WITH_DFSS}" = "1" ] || [ -n "$(ls /tmp/toolchains 2>/dev/null)" ]; } \
       && { [ -f /tmp/toolchains/swgcc830_cross_tools.tar.zst ] || [ -f /tmp/toolchains/loongarch64-cross-tools.tar.zst ]; }; then \
        if [ -f /tmp/toolchains/swgcc830_cross_tools.tar.zst ]; then \
            mkdir -p /usr/sw \
            && tar -C /usr/sw -I zstd -xf /tmp/toolchains/swgcc830_cross_tools.tar.zst; \
        fi \
        && if [ -f /tmp/toolchains/loongarch64-cross-tools.tar.zst ]; then \
            mkdir -p /env \
            && tar -C /env -I zstd -xf /tmp/toolchains/loongarch64-cross-tools.tar.zst; \
        fi \
        && rm -rf /tmp/toolchains; \
    fi
ENV DFSS_TOOLCHAIN_ROOT="/usr/sw/swgcc830_cross_tools"

# ---- 工作区约定 ----
WORKDIR /workspace
RUN git config --global --add safe.directory "*" \
    && printf '#!/bin/bash\nif [ -x /usr/sw/swgcc830_cross_tools/usr/bin/sw_64-sunway-linux-gnu-gcc ] && [ -x /env/loongson-gnu-toolchain-8.3-x86_64-loongarch64-linux-gnu-rc1.1/bin/loongarch64-linux-gnu-gcc ]; then\n  echo "[sophon-tools-build] dfss 私有工具链已就绪 (sw_64 + loongarch64)"\nelse\n  echo "[sophon-tools-build] dfss 私有工具链未内置 (构建时加 --with-dfss-toolchains)"\nfi\n' > /usr/local/bin/dfss-check \
    && chmod +x /usr/local/bin/dfss-check \
    && printf '#!/bin/bash\nif [ -x /env/qt_5.12.8_nosysroot/bin/qmake ]; then\n  echo "[sophon-tools-build] pSophUI 交叉 Qt 库已就绪 (aarch64 Qt 5.12.8)"\nelse\n  echo "[sophon-tools-build] pSophUI 交叉 Qt 库缺失 (构建时加 --with-sophui-toolchain)"\nfi\n' > /usr/local/bin/sophui-check \
    && chmod +x /usr/local/bin/sophui-check

CMD ["/bin/bash"]
