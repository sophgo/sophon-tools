# arm64 改为 musl 静态链接 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `psophliteos` 的 arm64 (SoC) 产物从动态链接 glibc 改为 musl 全静态链接,消除在 sophon 设备(glibc 2.31)上 `GLIBC_2.x not found` 报错;amd64 不变。

**Architecture:** 新增一个独立的工具链获取脚本 `build/fetch-musl-toolchain.sh`(下载 musl.cc 预构建 `aarch64-linux-musl-cross` 工具链,带 SHA256 校验与缓存),由 `scrip/package.sh` 的 arm64 段调用。arm64 构建改为 `CC=aarch64-linux-musl-gcc` + `-linkmode external -extldflags "-static"` + `netgo osusergo sqlite_omit_load_extension` 构建标签,产出完全静态的二进制。amd64 段、前端构建、deb 打包、安装脚本全部不动。

**Tech Stack:** Go 1.19、CGO(`go-sqlite3`)、musl.cc 预构建 `aarch64-linux-musl-cross` 工具链、bash/sh 构建脚本。

参考 spec: `docs/superpowers/specs/2026-06-23-arm64-musl-static-link-design.md`

---

## File Structure

- **Create** `build/fetch-musl-toolchain.sh` — 独立脚本,单一职责:确保 `aarch64-linux-musl-gcc` 可用(系统已有则跳过;否则下载、校验、解压、输出 bin 路径)。被 `package.sh` 调用,不内联下载逻辑,保持 `package.sh` 干净。
- **Modify** `scrip/package.sh` — 仅 arm64 段:调用工具链脚本、改 `CC`/`CXX`/构建标签/ldflags、构建后加静态链接验证门禁。amd64 段不动。
- (无新增 Go 源码;无新增测试文件——本变更作用于构建链路,验证方式为构建期 `file`/`ldd` 门禁 + 设备侧功能冒烟。)

---

### Task 1: 新增 musl 工具链获取脚本

**Files:**
- Create: `build/fetch-musl-toolchain.sh`

- [ ] **Step 1: 创建脚本文件**

写入 `build/fetch-musl-toolchain.sh`:

```sh
#!/bin/sh
# 确保 aarch64-linux-musl 交叉工具链可用。
# - 若系统 PATH 中已有 aarch64-linux-musl-gcc,直接退出(不输出,沿用系统工具链)。
# - 否则从 musl.cc 下载预构建工具链到 build/toolchain/,校验 SHA256,解压后输出 bin 目录路径
#   (供调用方加入 PATH)。
#
# 可重复性:设置环境变量 MUSL_TOOLCHAIN_SHA256 固定下载内容哈希。
# 首次下载时该变量留空会在 stderr 打印当前 sha256,填回即可固定。
set -e

TOOLCHAIN_NAME="aarch64-linux-musl-cross"
TOOLCHAIN_URL="https://musl.cc/${TOOLCHAIN_NAME}.tgz"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLCHAIN_ROOT="${MUSL_TOOLCHAIN_ROOT:-${SCRIPT_DIR}/toolchain}"
TOOLCHAIN_DIR="${TOOLCHAIN_ROOT}/${TOOLCHAIN_NAME}"
EXPECTED_SHA256="${MUSL_TOOLCHAIN_SHA256:-}"

# 1) 系统 PATH 已有该工具链,直接退出(不输出,沿用系统)
if command -v aarch64-linux-musl-gcc >/dev/null 2>&1; then
  exit 0
fi

# 2) 已下载并解压,直接输出 bin 路径
if [ -x "${TOOLCHAIN_DIR}/bin/aarch64-linux-musl-gcc" ]; then
  echo "${TOOLCHAIN_DIR}/bin"
  exit 0
fi

mkdir -p "${TOOLCHAIN_ROOT}"
ARCHIVE="${TOOLCHAIN_ROOT}/${TOOLCHAIN_NAME}.tgz"

echo "下载 musl 交叉工具链: ${TOOLCHAIN_URL}"
if command -v curl >/dev/null 2>&1; then
  curl -fL -o "${ARCHIVE}" "${TOOLCHAIN_URL}"
elif command -v wget >/dev/null 2>&1; then
  wget -O "${ARCHIVE}" "${TOOLCHAIN_URL}"
else
  echo "ERROR: 需要 curl 或 wget 之一" >&2
  exit 1
fi

ACTUAL_SHA256="$(sha256sum "${ARCHIVE}" | awk '{print $1}')"

if [ -z "${EXPECTED_SHA256}" ]; then
  echo "WARN: 未固定工具链 SHA256。将 MUSL_TOOLCHAIN_SHA256 环境变量设为下方值可固定:" >&2
  echo "      ${ACTUAL_SHA256}" >&2
else
  if [ "${ACTUAL_SHA256}" != "${EXPECTED_SHA256}" ]; then
    echo "ERROR: 工具链 SHA256 不匹配" >&2
    echo "  期望: ${EXPECTED_SHA256}" >&2
    echo "  实际: ${ACTUAL_SHA256}" >&2
    rm -f "${ARCHIVE}"
    exit 1
  fi
fi

tar -xzf "${ARCHIVE}" -C "${TOOLCHAIN_ROOT}"
rm -f "${ARCHIVE}"

if [ ! -x "${TOOLCHAIN_DIR}/bin/aarch64-linux-musl-gcc" ]; then
  echo "ERROR: 解压后未找到 aarch64-linux-musl-gcc,检查 musl.cc 产物结构" >&2
  exit 1
fi

echo "${TOOLCHAIN_DIR}/bin"
```

- [ ] **Step 2: 赋予可执行权限**

Run:
```bash
chmod +x build/fetch-musl-toolchain.sh
```

- [ ] **Step 3: 运行脚本,确认工具链下载并输出 bin 路径**

Run(首次会下载约 150MB,可能耗时数分钟):
```bash
bash build/fetch-musl-toolchain.sh
```
Expected: stderr 打印下载进度 + 一条 `WARN: 未固定工具链 SHA256 ...` 与当前 sha256;stdout 打印一行 bin 路径,形如 `/home/zzt/workspace/sophon-tools/source/psophliteos/build/toolchain/aarch64-linux-musl-cross/bin`。

- [ ] **Step 4: 验证工具链可用**

Run(把上一步输出的 bin 路径代入):
```bash
PATH="$(bash build/fetch-musl-toolchain.sh):$PATH" aarch64-linux-musl-gcc --version
```
Expected: 打印一行类似 `aarch64-linux-musl-gcc (crosstool-NG ...) 10.x.x` 的版本信息,无报错。

- [ ] **Step 5: (可选)固定 SHA256,再次运行确认校验通过**

将 Step 3 stderr 中打印的 sha256 填入环境变量后重跑:
```bash
MUSL_TOOLCHAIN_SHA256=<Step3打印的sha256> bash build/fetch-musl-toolchain.sh
```
Expected: 不再有 `WARN`,直接输出 bin 路径(命中缓存分支,不重新下载)。

- [ ] **Step 6: 提交**

```bash
git add build/fetch-musl-toolchain.sh
git commit -m "$(cat <<'EOF'
build(psophliteos): 新增 aarch64 musl 交叉工具链获取脚本

下载 musl.cc 预构建 aarch64-linux-musl-cross 工具链,带 SHA256 校验与
本地缓存,为 arm64 静态链接构建做准备。

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 切换 arm64 构建为 musl 静态链接并加验证门禁

**Files:**
- Modify: `scrip/package.sh:14-22`(arm64 段)

- [ ] **Step 1: 修改 package.sh 的 arm64 段**

将 `scrip/package.sh` 中第 14-22 行的 arm64 构建段:

```bash
CGO_ENABLED=1 GOOS=linux GOARCH=arm64 CC=aarch64-linux-gnu-gcc go build -trimpath -ldflags '-s -w'  && tar -zcvf sophliteos-linux_arm64.tgz sophliteos \
    dist \
    config/sophliteos.yaml \
    database/sophliteos.db \
    sophliteos.service \
    install.sh \
    uninstall.sh \
    release_version.txt \
    upgrade.sh
```

替换为(在 arm64 构建前调用工具链脚本,改 CC/CXX/标签/ldflags,构建后加静态链接门禁):

```bash
# arm64: 切换到 musl 静态链接,消除对目标设备 glibc 版本的依赖
MUSL_BIN="$(bash "$(dirname "$0")/../build/fetch-musl-toolchain.sh")"
[ -n "$MUSL_BIN" ] && export PATH="$MUSL_BIN:$PATH"

CGO_ENABLED=1 GOOS=linux GOARCH=arm64 \
  CC=aarch64-linux-musl-gcc \
  CXX=aarch64-linux-musl-g++ \
  go build -trimpath \
    -tags 'netgo osusergo sqlite_omit_load_extension' \
    -ldflags '-s -w -linkmode external -extldflags "-static"' \
  && tar -zcvf sophliteos-linux_arm64.tgz sophliteos \
    dist \
    config/sophliteos.yaml \
    database/sophliteos.db \
    sophliteos.service \
    install.sh \
    uninstall.sh \
    release_version.txt \
    upgrade.sh

# 静态链接门禁:arm64 产物必须是全静态,否则会在旧 glibc 设备上报 GLIBC 符号缺失
file sophliteos | grep -q 'statically linked' \
  || { echo "ERROR: arm64 产物不是静态链接,检查 musl 工具链与 extldflags"; exit 1; }
echo "arm64 产物静态链接校验通过"
```

> 说明:`$(dirname "$0")` 在 `build_2_release.sh` 以 `sh ./scrip/package.sh` 方式从仓库根调用时解析为 `./scrip`,`../build` 即仓库根下的 `build/`。直接在仓库根执行 `sh ./scrip/package.sh` 同样成立。`package.sh` 顶部无 `set -e`,此处用 `|| { ...; exit 1; }` 显式失败。

- [ ] **Step 2: 准备构建所需的前置文件**

`package.sh` 第 3 行会 `cp scrip/sophliteos.service scrip/install.sh scrip/uninstall.sh scrip/upgrade.sh .`,且 arm64 段 tar 包含 `dist`、`config/sophliteos.yaml`、`database/sophliteos.db`、`release_version.txt`。若仓库根缺少 `release_version.txt` 或 `dist/`,补齐以便单独验证 arm64 构建:

Run:
```bash
test -f release_version.txt || (cd build && sh version.sh "V1.1.2" && mv release_version.txt ../)
test -d dist || echo "WARN: dist/ 不存在,前端未构建;仅验证 Go 静态产物时可临时建空目录: mkdir -p dist"
```

- [ ] **Step 3: 运行 package.sh,确认 arm64 产物为静态链接**

Run(从仓库根执行):
```bash
sh ./scrip/package.sh
```
Expected: 末尾打印 `arm64 产物静态链接校验通过`;生成 `sophliteos-linux_arm64.tgz` 与 `sophliteos-linux_amd64.tgz`。若 musl 工具链首次下载,会先看到下载日志。

- [ ] **Step 4: 复核静态属性与依赖**

Run:
```bash
file sophliteos
ldd sophliteos 2>&1 || true
```
Expected:
- `file`: 输出含 `statically linked`(如 `ELF 64-bit LSB executable, ARM aarch64, version 1 (SYSV), statically linked, ...`)。
- `ldd`: 输出 `not a dynamic executable`(退出码非 0,故用 `|| true`)。

- [ ] **Step 5: (可选,若构建机有 qemu-user)本地冒烟运行 arm64 静态二进制**

Run:
```bash
command -v qemu-aarch64-static >/dev/null 2>&1 \
  && qemu-aarch64-static ./sophliteos --version 2>&1 | head \
  || echo "无 qemu-aarch64-static,跳过本地冒烟,转设备侧验证"
```
Expected: 二进制能启动(打印版本或正常的服务启动日志)而非 `GLIBC_2.x not found`;无 qemu 则按提示跳过。

- [ ] **Step 6: 提交**

```bash
git add scrip/package.sh
git commit -m "$(cat <<'EOF'
build(psophliteos): arm64 切换为 musl 静态链接

将 arm64(SoC)产物从动态链接 glibc 改为 musl 全静态链接,使用
aarch64-linux-musl-gcc + -linkmode external -extldflags -static,
并加 netgo/osusergo/sqlite_omit_load_extension 构建标签。构建后加
静态链接门禁。amd64 不变。

修复 sophon 设备(glibc 2.31)上 GLIBC_2.x not found 报错。

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 端到端构建与设备侧功能冒烟

**Files:**
- 无新增/修改文件(本任务为验证)

- [ ] **Step 1: 通过完整发布脚本构建,确认全链路产物正常**

Run(必须先 `cd build`,脚本自身要求在 build 目录执行):
```bash
cd build && bash build_2_release.sh
```
Expected: 流程跑完,`release/` 下生成 `sophliteos-linux_arm64.tgz`、`sophliteos-linux_amd64.tgz` 及四个 deb 包(`sophliteos_soc_1.1.2.deb`、`sophliteos_soc_1.1.2_sdk.deb`、`sophliteos_pcie_1.1.2.deb`、`sophliteos_pcie_1.1.2_sdk.deb`)。构建日志末尾出现 `arm64 产物静态链接校验通过`。

- [ ] **Step 2: 解包 arm64 tgz 复核二进制静态属性**

Run:
```bash
mkdir -p /tmp/arm64-check && tar -xzf release/sophliteos-linux_arm64.tgz -C /tmp/arm64-check
file /tmp/arm64-check/sophliteos
```
Expected: 输出含 `statically linked`。

- [ ] **Step 3: 部署到 sophon SoC 设备并启动服务**

将 `release/sophliteos-linux_arm64.tgz` 拷到目标 sophon 设备,在该设备上执行项目自带安装脚本(或手动替换二进制后重启 systemd 服务):

```bash
# 在设备上(示例,按实际 install.sh 用法)
tar -xzf sophliteos-linux_arm64.tgz
sudo sh install.sh        # 或按项目既有部署方式
systemctl status sophliteos
```
Expected: 服务 `active (running)`;**不再出现** `/lib/aarch64-linux-gnu/libc.so.6: version GLIBC_2.x not found` 报错;`journalctl -u sophliteos` 无启动失败。

- [ ] **Step 4: 设备侧功能冒烟(musl/静态化最可能暴露差异的点)**

逐项验证(通过 Web 界面或 API 触发均可):

- **sqlite 建表/读写**:确认 `user`、`alarm`、`opt_log` 三张表在 `database/sophliteos.db` 中自动创建且可读写(`dbconnect.go` 的 `CreateTableIfNotExist` 路径)。
- **regexp SQL 函数**:登录或任意用到 `regexp` 的查询正常(`dbconnect.go` 中 `RegisterFunc("regexp", ...)`,验证 Go 回调在 musl 下可用)。
- **登录流程**:用 `admin` 账号登录成功(用户表查询、admin 初始化、密码校验)。
- **cron 清理任务**:服务启动后 cron 调度器初始化无报错(`dbconnect.go` 末尾 `cron.New` + `AddFunc`);如可等待到次日 0 点或手动触发,确认过期 `alarm`/`opt_log` 清理生效。
- **外部 HTTP 调用(验证 netgo)**:触发任一需要外发的网络请求(设备发现/上报等),确认 DNS 解析与连通正常——这是 `netgo` 纯 Go 解析器与 glibc 解析器行为差异最可能暴露之处。

Expected: 上述功能全部正常。若 `netgo` 导致 DNS 问题,可仅移除 `netgo` 标签(musl 的 C 解析器在静态链接下仍可工作)并复测,记录结论。

- [ ] **Step 5: 记录验证结论并提交(若有变更)**

若设备侧冒烟全过且无代码变更,无需提交(本任务为纯验证)。若过程中调整了构建标签或脚本(例如移除 `netgo`),则:

```bash
git add -A
git commit -m "$(cat <<'EOF'
build(psophliteos): 设备侧冒烟后微调 musl 静态构建

<具体调整说明>

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

并在 `docs/superpowers/specs/2026-06-23-arm64-musl-static-link-design.md` 末尾追加一条验证结论(可选用):
```bash
# 例:echo "- 验证: 2026-06-23 在 sophon SoC(glibc 2.31)部署通过,sqlite/regexp/cron/登录/外发HTTP 均正常。" >> docs/superpowers/specs/2026-06-23-arm64-musl-static-link-design.md
```

---

## Self-Review

**1. Spec 覆盖:** spec 第 4 节(工具链来源,主选 musl.cc + 备选 zig)→ Task 1;第 5 节(package.sh 改动 + 工具链获取 + 不变项)→ Task 1 Step1 获取脚本 + Task 2 Step1 package.sh;第 6 节(构建标签与 ldflags)→ Task 2 Step1;第 7 节(验证 file/ldd/qemu/设备侧 sqlite·regexp·cron·登录·HTTP)→ Task 2 Step3-5 + Task 3 Step2-4;第 8 节(风险 netgo、回滚 git revert)→ Task 2 Step1 注释 + Task 3 Step4 netgo 回退说明。覆盖完整。

**2. 占位符扫描:** 无 TBD/TODO;`MUSL_TOOLCHAIN_SHA256` 留空为运行时计算值,脚本有实际处理逻辑并打印提示,非占位符。Task 2 Step1 提供完整可粘贴代码,无"类似 Task N"。

**3. 类型/命名一致性:** 工具链目录名 `aarch64-linux-musl-cross`、bin 可执行 `aarch64-linux-musl-gcc`/`aarch64-linux-musl-g++`、环境变量 `MUSL_TOOLCHAIN_SHA256`/`MUSL_TOOLCHAIN_ROOT`、输出 bin 路径——Task 1 与 Task 2 中一致。构建标签 `netgo osusergo sqlite_omit_load_extension` 与 spec 一致。
