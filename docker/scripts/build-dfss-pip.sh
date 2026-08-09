#!/usr/bin/env bash
# 在 sophon-tools-build 镜像内编译 dfss pip 包（dfss-cpp 8 架构 + python 打包）
#
# 产物: source/pdfss_cpp/dfss_pip/dist/dfss-<version>.whl + .tar.gz
#   内含 8 架构 dfss-cpp 二进制 (amd64/arm64/armbi/loongarch64/riscv64/sw_64 + win-amd64/win-i686)
#
# 用法:
#   bash docker/scripts/build-dfss-pip.sh [--skip-libs] [--arch aarch64] ...
#
# 前置: sophon-tools-build 镜像(含全部 8 架构交叉工具链), 网络可达(musl.cc/go.dev 已内置)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
DOCKER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# 默认镜像: 优先带版本号 tag（docker/versions.env 的 IMAGE_TAG），未定义则回退 unified
if [[ -z "${IMAGE:-}" ]]; then
  if [[ -f "${DOCKER_DIR}/versions.env" ]]; then
    # shellcheck disable=SC1091
    source "${DOCKER_DIR}/versions.env"
    IMAGE="sophon-tools-build:${IMAGE_TAG:-unified}"
  else
    IMAGE="sophon-tools-build:unified"
  fi
fi
PDFSS_SRC="${REPO_ROOT}/source/pdfss_cpp"
SKIP_LIBS=0
ARCHES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-libs) SKIP_LIBS=1 ;;
    --arch) ARCHES+=("$2"); shift 2; continue ;;
    --image) IMAGE="$2"; shift 2; continue ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
  shift
done

[[ ${#ARCHES[@]} -gt 0 ]] || ARCHES=(host aarch64 armbi loongarch64 riscv64 sw_64 mingw64 mingw)

# 需要 dfss 私有工具链的架构（loongarch64 / sw_64）: 循环前预检, 避免前 4 个架构白编
NEEDS_DFSS=0
for a in "${ARCHES[@]}"; do
  case "$a" in
    loongarch64|sw_64) NEEDS_DFSS=1 ;;
  esac
done

echo "==> 在镜像 ${IMAGE} 内编译 dfss-cpp 全部架构: ${ARCHES[*]}"
docker run --rm \
  -v "${PDFSS_SRC}":/workspace/pdfss_cpp \
  -w /workspace/pdfss_cpp \
  "${IMAGE}" bash -c "
    set -e
    export PATH=\"/env/loongson-gnu-toolchain-8.3-x86_64-loongarch64-linux-gnu-rc1.1/bin:/usr/sw/swgcc830_cross_tools/usr/bin:\$PATH\"
    git config --global --add safe.directory /workspace/pdfss_cpp

    if [ \"${NEEDS_DFSS}\" = \"1\" ] && ! command -v loongarch64-linux-gnu-gcc >/dev/null 2>&1; then
      echo 'ERROR: 架构含 loongarch64/sw_64, 但镜像未内置 dfss 私有工具链。' >&2
      echo '       请用 --with-dfss-toolchains 重建镜像(或从 13.24 容器导出归档: bash docker/scripts/export-dfss-toolchains.sh)。' >&2
      exit 1
    fi

    for arch in ${ARCHES[*]}; do
      echo \"===== 构建 \${arch} =====\"
      # libs 阶段(除 host 外需要交叉静态库); 首次构建可能因 mbedtls 并行竞态失败, 重跑一次
      if [[ \"${SKIP_LIBS}\" = \"0\" ]]; then
        # 清理 mbedtls build 残留避免竞态
        rm -rf libs/mbedtls/build
        bash linux_release.sh \"\${arch}\" lib >/dev/null 2>&1 || {
          echo \"libs 重试...\"
          rm -rf libs/mbedtls/build
          bash linux_release.sh \"\${arch}\" lib
        }
      fi
      bash linux_release.sh \"\${arch}\"
    done

    echo '===== 打包 pip ====='
    cd dfss_pip
    rm -rf dist build dfss.egg-info
    rm -f dfss/output/dfss-cpp* dfss/output/git_version 2>/dev/null || true
    python3 setup.py sdist bdist_wheel --universal
    echo '===== 产物 ====='
    ls -la dist/
"

echo "==> 完成。pip 包: ${PDFSS_SRC}/dfss_pip/dist/"
