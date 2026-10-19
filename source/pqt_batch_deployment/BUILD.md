# 构建说明（Go + Fyne）

本工具自 v2.0.0 起改为 Go + Fyne 实现，Linux 与 Windows 均产出**单个可执行文件**。

## 1. 为什么放弃 Qt 打包

| 方案 | 问题 |
| --- | --- |
| Linux AppImage | 本质是自挂载 squashfs 包，不是单二进制 |
| Windows Enigma Virtual Box | 打箱产物，不是单二进制 |
| Qt 静态链接 | Linux 侧需自行编译静态 Qt + 静态图形栈（wayland/xkbcommon 无静态库）；Windows 侧本仓库 `/opt/qt-mingw` 的静态库与宿主 mingw CRT 不匹配，链接报 `__imp__vsnprintf` 未定义 |

Go + Fyne 两端都能直接 `go build` 出单个二进制，资源（Logo、字体、内置预设）
用 `go:embed` 内嵌，运行时不需要任何附属文件。

## 2. 依赖

### 通用
- **Go ≥ 1.25.5**（`go.mod` 的 `go` 指令即 1.25.5，与统一构建镜像自带版本一致）

依赖通过 `go.mod` 锁定：
- `fyne.io/fyne/v2` —— 跨平台 GUI
- `golang.org/x/crypto/ssh` —— SSH
- `github.com/pkg/sftp` —— SFTP

> **为什么锁 1.25.5 而不是更高**：`docker/versions.env` 的 `GO_VERSION=1.25.5`，
> 容器内 `GOTOOLCHAIN=auto`。若 `go.mod` 要求更高版本，首次构建会联网下载新工具链，
> 在受限网络下直接失败。`golang.org/x/*` 也相应锁在仍声明 `go 1.25` 的版本上
> （crypto v0.55.0 / net v0.57.0 / sys v0.47.0 / text v0.41.0 / term v0.45.0），
> 否则 `go mod tidy` 会把 `go` 指令顶到 1.26。

### Linux
```bash
apt-get install -y gcc libgl1-mesa-dev xorg-dev
```
（Fyne 需要 CGO 与 X11/OpenGL 头文件。）

### Windows 交叉编译
```bash
apt-get install -y gcc-mingw-w64-x86-64 g++-mingw-w64-x86-64
```

### 模块代理
构建机访问 `proxy.golang.org` 不稳定时：
```bash
export GOPROXY=https://goproxy.cn,direct
export GOSUMDB=sum.golang.google.cn
```
`release.sh` 已默认设置，可用环境变量覆盖。

## 3. 构建

```bash
# 两端一起
bash release.sh all

# 单平台
bash release.sh linux
bash release.sh windows

# 指定版本号（默认取 src/version.go）
bash release.sh all 2.0.1

# 指定产物目录
OUTPUT_DIR=/tmp/out bash release.sh linux
```

`release.sh` 会先跑 `go test ./...`，测试不过不出包。

产物命名：
```
qt_batch_deployment_V<ver>_linux_amd64
qt_batch_deployment_V<ver>_windows_amd64.exe
qt_batch_deployment_V<ver>_linux_amd64.deps.txt   # Linux 动态依赖清单
```

## 4. 交付形态说明（重要）

**Windows**：真正的单二进制。`objdump -p` 只能看到系统 DLL
（KERNEL32 / USER32 / GDI32 / OPENGL32 / SHELL32 + api-ms-win-crt-*），
不需要 Qt、不需要 DLL 目录、不需要解压。

**Linux**：单个可执行文件、免安装，但**不是纯静态**。Fyne 必须链接系统图形栈：

```
libX11 libXcursor libXrandr libXinerama libXi libxkbcommon
libwayland-client libwayland-cursor libwayland-egl
libGL libGLX libGLdispatch libxcb libffi libm libresolv libc
```

这是 Linux GUI 程序的固有约束，已与需求方确认接受
（`release.sh` 同时产出 `.deps.txt` 以便发布说明如实交代）。

## 5. 版本号

唯一来源：`src/version.go` 的 `Version` 常量。
`release.sh` 从中解析，无需在两处同步（旧版 GUI 与 no_ui 各自写死版本号，长期不一致）。

## 6. 测试

```bash
cd src
go test ./...
go vet ./...
```

测试不依赖真实设备：连接类用例对 `127.0.0.1:1` 断言「快速失败 + 正确错误」，
不依赖外部网络。

## 7. 在统一构建镜像内构建

`docker/Dockerfile` 已内置 Go 1.25.5 与 mingw-w64，并已补上 Fyne 所需的
Linux 图形开发库（`libgl1-mesa-dev` / `xorg-dev` / `libxkbcommon-dev`）。
`docker/build-all.sh` 里本项目的 `EXTRA_ENV` 也改为把 `/opt/go/bin` 加入 PATH，
因此统一构建入口可以直接两端出包。
