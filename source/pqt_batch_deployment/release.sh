#!/bin/bash
# qt_batch_deployment（批量部署工具）构建入口 —— Go + Fyne 单二进制
#
# 用法: bash release.sh [ARCH] [VERSION]
#   ARCH:    linux | windows | all（默认 all）
#   VERSION: 显式版本号（默认从 src/version.go 解析，唯一版本源）
#   env OUTPUT_DIR: 产物目录（默认 <repo>/output/pqt_batch_deployment/）
#
# 产物（每种平台都是**单个可执行文件**，无需安装、不随附任何资源目录）:
#   qt_batch_deployment_V<ver>_linux_amd64      Linux 可执行文件
#   qt_batch_deployment_V<ver>_windows_amd64.exe Windows 可执行文件
#
# 依赖:
#   * Go >= 1.22（go:embed / fyne v2.8）
#   * Linux 构建：gcc + 系统图形开发库（libgl1-mesa-dev libx11-dev 等）
#   * Windows 构建：mingw-w64 交叉编译器（x86_64-w64-mingw32-gcc）
#
# 为什么这个工具不再用 Qt/AppImage/Enigma:
#   单二进制是硬需求。Qt 在 Linux 只能靠 AppImage（自挂载 squashfs 包）假装单文件，
#   Windows 则依赖 Enigma Virtual Box 打箱;两者都不满足"单个可执行文件"。
#   Go + Fyne 两端都能直接产出单个二进制（资源用 go:embed 内嵌）。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SRC_DIR="$SCRIPT_DIR/src"
ARCH="${1:-all}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/output/pqt_batch_deployment}"

VERSION="${2:-$(grep -oE 'Version = "[^"]+"' "$SRC_DIR/version.go" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')}"
if [ -z "$VERSION" ]; then
  echo "ERROR: 无法从 src/version.go 解析版本号，请显式传入 VERSION" >&2
  exit 1
fi

echo "==> qt_batch_deployment (Go+Fyne) version=$VERSION arch=$ARCH"

if ! command -v go >/dev/null 2>&1; then
  echo "ERROR: 未找到 go，请先安装 Go >= 1.22" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
cd "$SRC_DIR" || exit 1

# 国内模块代理：proxy.golang.org 在部分构建机不可达
export GOPROXY="${GOPROXY:-https://goproxy.cn,direct}"
export GOSUMDB="${GOSUMDB:-sum.golang.google.cn}"
export GOFLAGS="${GOFLAGS:-}"

# 先跑测试：构建失败或测试不过都不出包
echo "==> go test ..."
if ! go test ./... 2>&1 | tail -20; then
  echo "ERROR: 测试未通过，终止出包" >&2
  exit 1
fi

build_linux() {
  local out="$OUTPUT_DIR/qt_batch_deployment_V${VERSION}_linux_amd64"
  echo "==> 构建 Linux 单文件 ..."
  if ! CGO_ENABLED=1 go build -trimpath -ldflags "-s -w" -o "$out" . ; then
    echo "ERROR: Linux 构建失败" >&2
    return 1
  fi
  chmod +x "$out"
  echo "    产物: $out ($(du -h "$out" | cut -f1))"
  # 记录动态依赖，便于发布说明里如实交代"不是纯静态"
  ldd "$out" 2>/dev/null | awk '{print $1}' | grep -E '^lib' | sort -u > "$out.deps.txt" || true
}

build_windows() {
  local out="$OUTPUT_DIR/qt_batch_deployment_V${VERSION}_windows_amd64.exe"
  local cc="x86_64-w64-mingw32-gcc"
  local cxx="x86_64-w64-mingw32-g++"
  if ! command -v "$cc" >/dev/null 2>&1; then
    echo "ERROR: 未找到 mingw-w64 交叉编译器 ($cc)" >&2
    echo "       Ubuntu: apt-get install gcc-mingw-w64-x86-64 g++-mingw-w64-x86-64" >&2
    return 1
  fi
  echo "==> 构建 Windows 单文件 ..."
  # -H windowsgui: 双击不弹控制台窗口（命令行模式仍可用，参数照常传入）
  if ! CGO_ENABLED=1 GOOS=windows GOARCH=amd64 CC="$cc" CXX="$cxx" \
       go build -trimpath -ldflags "-s -w -H windowsgui" -o "$out" . ; then
    echo "ERROR: Windows 构建失败" >&2
    return 1
  fi
  echo "    产物: $out ($(du -h "$out" | cut -f1))"
}

rc=0
case "$ARCH" in
  linux)   build_linux   || rc=1 ;;
  windows|win) build_windows || rc=1 ;;
  all)     build_linux   || rc=1
           build_windows || rc=1 ;;
  *) echo "ERROR: ARCH 必须是 linux|windows|all，得到: $ARCH" >&2; exit 1 ;;
esac

echo "==> 完成，产物目录: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"
exit $rc
