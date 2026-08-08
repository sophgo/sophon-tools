# syntax=docker/dockerfile:1
# =============================================================================
# sophon-tools-build —— sophon-tools 17 子项目统一编译镜像
#
# 基座: ubuntu:20.04 (U1 单镜像合并决定; digest 锁定见 docker/versions.env)
#   glibc 2.31, 满足 pqt AppImage 对宿主 glibc ≤ 2.31 的硬约束。
#   apt 交叉 gcc 为 9.3.0 (22.04 是 11.x), 已实测可编译各目标架构。
#
# 设计:
#   * 多阶段构建: Stage1 下载并校验国外大体积工具链(Go/Node); Stage2 汇入运行镜像。
#   * 版本唯一来源 docker/versions.env(由 docker/build.sh 注入 ARG), 全部版本锁定。
#   * 交叉工具链: apt 精确版本(glibc) + musl.cc(静态) + dfss 私有工具链(sw_64/loongarch64)。
#   * dfss 私有工具链默认不内置(私有源, 体积大); 通过 --with-dfss-toolchains 或构建上下文
#     toolchains/ 目录内置。
#
# 构建(一条命令):  bash docker/build.sh
# 构建(含私有工具链): bash docker/build.sh --with-dfss-toolchains
# =============================================================================

# ---- ARG 集合(由 build.sh 从 versions.env 注入) ----
ARG UBUNTU_BASE_DIGEST
ARG GO_VERSION GO_TARBALL_URL GO_TARBALL_SHA256
ARG RUST_VERSION
ARG NODE_TARBALL_URL NODE_TARBALL_SHA256
ARG PNPM_VERSION YARN_VERSION
ARG WITH_DFSS=0

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
ARG GO_VERSION RUST_VERSION PNPM_VERSION YARN_VERSION WITH_DFSS

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH="/opt/go/bin:/opt/nodejs/bin:/opt/rust/bin:/opt/musl/aarch64-linux-musl-cross/bin:/opt/musl/x86_64-linux-musl-cross/bin:/usr/local/go/bin:${PATH}"

SHELL ["/bin/bash", "-c"]

# ---- 系统依赖 + apt 交叉工具链(精确版本, 由 ubuntu:20.04 仓库固定, 均为 9.3.0) ----
# pdfss_cpp 8 架构: aarch64/armel/riscv64 + mingw-w64(windows amd64/i686)
# Rust/Go 静态: musl 工具链在 PATH(由 pbmssm 的 fetch-musl-toolchain.sh 识别复用)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc g++ make cmake pkg-config \
        gcc-aarch64-linux-gnu g++-aarch64-linux-gnu \
        gcc-arm-linux-gnueabi g++-arm-linux-gnueabi \
        gcc-riscv64-linux-gnu g++-riscv64-linux-gnu \
        gcc-mingw-w64-x86-64 g++-mingw-w64-x86-64 gcc-mingw-w64-i686 g++-mingw-w64-i686 \
        dpkg dpkg-dev fakeroot \
        qtbase5-dev qttools5-dev-tools \
        ca-certificates curl wget git \
        zip unzip p7zip-full patchelf \
        python3 python3-pip python3-dev \
        brotli zstd xz-utils bzip2 \
        libssl-dev libtool autoconf automake \
        file binutils upx-ucl \
        qemu-user qemu-user-static binfmt-support \
        libfuse2 ssh strace pandoc sudo \
    && rm -rf /var/lib/apt/lists/*

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
# 预置 aarch64 + x86_64; 若构建期网络受限, 子项目脚本会自行从 musl.cc 拉取。
RUN mkdir -p /opt/musl \
    && curl -fsSL "https://musl.cc/aarch64-linux-musl-cross.tgz" -o /tmp/musl-aarch64.tgz \
    && tar -C /opt/musl -xzf /tmp/musl-aarch64.tgz && rm /tmp/musl-aarch64.tgz \
    && curl -fsSL "https://musl.cc/x86_64-linux-musl-cross.tgz" -o /tmp/musl-x86_64.tgz \
    && tar -C /opt/musl -xzf /tmp/musl-x86_64.tgz && rm /tmp/musl-x86_64.tgz \
    && aarch64-linux-musl-gcc --version | head -1 && x86_64-linux-musl-gcc --version | head -1

# ---- dfss 私有工具链(sw_64 / loongarch64)----
# 构建上下文需含 toolchains/ 目录(由 export-dfss-toolchains.sh 导出), 或用 --with-dfss-toolchains。
# 注意: sw_64 工具链 gcc 编译期 prefix 硬编码为 /usr/sw/swgcc830_cross_tools,
#       loongarch64 硬编码为 /env/loongson-gnu-toolchain-8.3-x86_64-loongarch64-linux-gnu-rc1.1,
#       故解压到容器内原始路径, 保证绝对引用全部有效(与 13.24 源容器一致)。
ARG WITH_DFSS=0
COPY toolchains/ /tmp/toolchains/
RUN if [ "${WITH_DFSS}" = "1" ] || [ -n "$(ls /tmp/toolchains 2>/dev/null)" ]; then \
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
ENV DFSS_TOOLCHAIN_ROOT="/usr/sw/swgcc830_cross_tools" \
    PATH="/usr/sw/swgcc830_cross_tools/usr/bin:/env/loongson-gnu-toolchain-8.3-x86_64-loongarch64-linux-gnu-rc1.1/bin:${PATH}"

# ---- 工作区约定 ----
WORKDIR /workspace
RUN git config --global --add safe.directory "*" \
    && printf '#!/bin/bash\nif [ -x /usr/sw/swgcc830_cross_tools/usr/bin/sw_64-sunway-linux-gnu-gcc ] && [ -x /env/loongson-gnu-toolchain-8.3-x86_64-loongarch64-linux-gnu-rc1.1/bin/loongarch64-linux-gnu-gcc ]; then\n  echo "[sophon-tools-build] dfss 私有工具链已就绪 (sw_64 + loongarch64)"\nelse\n  echo "[sophon-tools-build] dfss 私有工具链未内置 (构建时加 --with-dfss-toolchains)"\nfi\n' > /usr/local/bin/dfss-check \
    && chmod +x /usr/local/bin/dfss-check

CMD ["/bin/bash"]