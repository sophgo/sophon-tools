# U1 工具链核对清单（ubuntu:20.04 基座）

**基座**: ubuntu:20.04 (digest `sha256:8feb4d8ca5354def3d8fce243717141ce31e2c428701f6682bd2fafe15388214`, glibc 2.31)
**镜像**: `sophon-tools-build:u1-20.04`（含 dfss 私有工具链, 8.47GB）
**验证方式**: 镜像内实测版本 + 实际交叉编译目标架构二进制

## 版本变化对照表

| 工具链 | 22.04 (旧基座) | 20.04 (新基座) | 变化 | 验证结果 |
|--------|---------------|---------------|------|---------|
| 宿主 gcc/g++ | 11.x | **9.4.0** | ⚠️ 版本降级 | ✅ 编译 host 产物 |
| gcc-aarch64-linux-gnu | 11.x | **9.4.0** | ⚠️ 版本降级 | ✅ 编译出 AArch64 ELF |
| gcc-arm-linux-gnueabi | 11.x | **9.4.0** | ⚠️ 版本降级 | ✅ 编译出 ARM ELF |
| gcc-riscv64-linux-gnu | 11.x | **9.4.0** | ⚠️ 版本降级 | ✅ 编译出 RISC-V ELF |
| gcc-mingw-w64-x86-64 | 10.3.0 | **9.3-win32** | ⚠️ 版本降级 | ✅ 编译出 pei-x86-64 |
| gcc-mingw-w64-i686 | 10.3.0 | **9.3-win32** | ⚠️ 版本降级 | ✅ 编译出 pei-i386 |
| cmake | 3.22.1 | **3.16.3** | ⚠️ 版本降级 | ✅ 正常 |
| make | 4.3 | **4.2.1** | ⚠️ 版本降级 | ✅ 正常 |
| dpkg-deb / dpkg-dev | 1.21.1 | **1.19.7** | ⚠️ 版本降级 | ✅ 打包测试通过 |
| patchelf | 0.14.3 | **0.10** | ⚠️ 版本降级 | ✅ 正常 |
| upx-ucl | 3.96 | **3.95** | 微变 | ✅ 正常 |
| pandoc | 2.9.2.1 | **2.5** | ⚠️ 版本降级 | ✅ markdown→html 通过 |
| sudo | 1.9.9 | **1.8.31** | ⚠️ 版本降级 | ✅ 正常 |
| qmake / Qt | 5.15.3 | **5.12.8** | ⚠️ 版本降级 (U2 pqt 涉及) | ✅ 正常 |
| qemu-user-static | 6.2 | **4.2** | ⚠️ 版本降级 | ✅ 正常 |
| glibc | 2.35 | **2.31** | ✅ 本次切换核心目的 (AppImage 硬约束) | ✅ 实测 2.31 |

## 不受影响（tarball/rustup 安装，不挑宿主 glibc）

| 工具链 | 版本 | 验证 |
|--------|------|------|
| Go | 1.25.5 | ✅ `go version` |
| Rust / cargo | 1.97.1 | ✅ rustc/cargo |
| Node.js | 20.19.0 | ✅ node/pnpm/yarn |
| pnpm / yarn | 9.15.9 / 1.22.22 | ✅ |
| musl 交叉 (aarch64/x86_64) | 11.2.1 (musl.cc) | ✅ 独立工具链 |

## dfss 私有工具链（关键验收）

| 工具链 | 版本 | 基座变化影响 | 验证 |
|--------|------|-------------|------|
| sw_64 (SWREACH) | 8.3.0 | prefix 硬编码 `/usr/sw/swgcc830_cross_tools`, 已按原路径解压 | ✅ `-static` 编译出 ELF64 |
| loongarch64 | 8.3.0 | prefix 硬编码 `/env/loongson-gnu-toolchain-8.3-...`, 已按原路径解压 | ✅ `-static` 编译出 ELF64 |

两个 gcc prefix 硬编码路径保持不变（与 22.04 及源容器一致），基座切换后重新验证编译通过。

## 注意事项

1. **交叉 gcc 版本降级是预期**：20.04 apt 仓库只有 gcc 9.x 交叉工具链，22.04 是 11.x。pdfss_cpp 8 架构产物改用 gcc 9.3 编译，全量回归（U4）需重点验证产物兼容性。
2. **mingw gcc 9.3-win32**：C++ 标准库/工具链与 10.3 有差异，U4 回归验证 pqt exe 产物。
3. **dfss ldd 遮蔽**: 镜像 PATH 中 `/usr/sw/swgcc830_cross_tools/usr/bin` 在前，其自带 ldd 遮蔽系统 ldd（22.04 m2 镜像同样如此，为既有行为）。不影响编译；真实 glibc 为 2.31。
4. 本里程碑不做 pqt/pSophUI 合并（U2/U3），Qt 5.12.8 为 U1 保留版本。
