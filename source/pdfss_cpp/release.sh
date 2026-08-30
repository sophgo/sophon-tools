#!/bin/bash
# pdfss_cpp 统一构建接口 (M1 规范 v0.1)
# 用法: bash release.sh [ARCH] [VERSION]
#   ARCH:    host(amd64) | arm64 | darwin（macOS 本机） | all（默认 host；all=8 架构，含 win/loongarch64/riscv64/sw_64/armbi）
#   VERSION: 显式版本号（默认读 git_version 文件）
#   env OUTPUT_DIR: 产物目录（默认 <repo>/output/pdfss_cpp/）
# 注意: 多架构交叉需要对应工具链，全部在 sophon-tools-build 镜像内预置。
set -euo pipefail

if [[ "$(uname -s)" == "Darwin" ]]; then
	# macOS 没有 readlink -f
	SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
else
	SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
fi
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARCH="${1:-host}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/output/pdfss_cpp}"

# 版本号来源：git_version 文件（如 v1.10.5），无则 fallback
VERSION="${2:-$(cat "$SCRIPT_DIR/git_version" 2>/dev/null || echo v0.0.0)}"
echo "==> pdfss_cpp version=$VERSION"

case "$ARCH" in
  host|amd64) TARGETS="host" ;;
  arm64)      TARGETS="aarch64" ;;
  all)        TARGETS="host aarch64 armbi loongarch64 riscv64 sw_64 mingw64 mingw" ;; # darwin 需在 macOS 主机单独构建
  darwin)     TARGETS="darwin" ;;
  sw_64)      TARGETS="sw_64" ;;
  loongarch64) TARGETS="loongarch64" ;;
  *) echo "ERROR: ARCH 必须是 host|amd64|arm64|darwin|all，得到: $ARCH" >&2; exit 1 ;;
esac

mkdir -p "$OUTPUT_DIR"
echo "==> pdfss_cpp targets: $TARGETS"

# Windows 端需要 posix 线程模型（std::thread/std::mutex）。
# 镜像内 mingw g++ 默认是 win32 线程（update-alternatives 优先级高），
# 这里做一个 PATH shim，把 x86_64/i686-w64-mingw32-gcc/g++ 指向 -posix 变体
# （与 docker/pqt/build-pqt.sh --windows 的处理一致）。
MINGW_SHIM="$SCRIPT_DIR/.mingw-posix-bin"
if [[ " $TARGETS " == *" mingw"* || " $TARGETS " == *"mingw64"* ]]; then
  mkdir -p "$MINGW_SHIM"
  for base in x86_64-w64-mingw32 i686-w64-mingw32; do
    for tool in gcc g++ cpp c++ cc; do
      if [ -x "/usr/bin/${base}-${tool}-posix" ]; then
        ln -sf "/usr/bin/${base}-${tool}-posix" "$MINGW_SHIM/${base}-${tool}"
      fi
    done
  done
  export PATH="$MINGW_SHIM:$PATH"
fi

# libs 依赖需先构建（mbedtls/libssh2/zlib 静态库），镜像内可复用缓存。
# 注意 build_libs.sh 有 mbedtls 并行编译竞态（M2 已知），失败时清理重试一次。
build_libs() {
  local target="$1"
  echo "==> 编译静态依赖 libs (${target}) ..."
  rm -rf libs/mbedtls/build 2>/dev/null || true
  (cd libs && bash build_libs.sh "$target") || {
    echo "==> libs (${target}) 竞态重试 ..."
    rm -rf libs/mbedtls/build 2>/dev/null || true
    (cd libs && bash build_libs.sh "$target")
  }
}

for t in $TARGETS; do
  # 每个 target 需要自己的交叉静态库（<target>_build，镜像内可复用缓存）。
  # 判断完成标志：libssh2.h 存在（build_libs.sh 的 libssh2 是最后一步）。
  local_libdir="libs/${t}_build"

  if [ -f "$SCRIPT_DIR/$local_libdir/include/libssh2.h" ]; then
    echo "==> libs 已存在 ($local_libdir), 复用"
  else
    build_libs "$t"
  fi
  echo "==> linux_release.sh $t"
  bash linux_release.sh "$t"
done

# 清理 mingw posix shim
rm -rf "$MINGW_SHIM" 2>/dev/null || true

# ---- dfss pip 包（仅 all 全架构模式；wheel 内含 8 架构二进制，需先完成全部架构编译）----
if [ "$ARCH" = "all" ]; then
  echo "==> 构建 dfss pip 包 ..."
  (cd "$SCRIPT_DIR/dfss_pip" && rm -rf dist build dfss.egg-info \
    && rm -f dfss/output/dfss-cpp* dfss/output/git_version 2>/dev/null || true \
    && python3 setup.py sdist bdist_wheel --universal) || {
      echo "WARN: dfss pip 包构建失败（不影响二进制产物）" >&2
    }
  if ls "$SCRIPT_DIR/dfss_pip/dist"/dfss-*.whl >/dev/null 2>&1; then
    cp "$SCRIPT_DIR/dfss_pip/dist"/dfss-*.whl "$OUTPUT_DIR/"
    cp "$SCRIPT_DIR/dfss_pip/dist"/dfss-*.tar.gz "$OUTPUT_DIR/" 2>/dev/null || true
  fi
fi

# 汇聚产物（linux_release.sh 输出到 source/pdfss_cpp/output/）
local_out="$SCRIPT_DIR/output"
if [ -d "$local_out" ]; then
  cp -a "$local_out"/dfss-cpp-* "$OUTPUT_DIR/" 2>/dev/null || true
fi

echo "==> pdfss_cpp 完成, 产物: $OUTPUT_DIR"
ls -la "$OUTPUT_DIR"
file "$OUTPUT_DIR"/* 2>/dev/null | head -20
