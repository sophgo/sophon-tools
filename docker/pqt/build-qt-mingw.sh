#!/usr/bin/env bash
# 交叉编译 Qt 5.15.2 (mingw-w64 静态) —— pqt 系列 windows 端前置依赖
#
# 背景:
#   pqt_memory_edit / pqt_batch_deployment 的 windows 端依赖 Qt 5.15 mingw 静态库
#   (仓库 libs/win_amd64 只含 libssh2/openssl, 不含 Qt)。完整交叉编译一次约 20-40 分钟。
#
# 关键点:
#   * Qt 5.15.2 的 qglobal.h/qfloat16.h/qendian.h 缺 <limits> include (新 gcc 报错) —— 自动 patch
#   * mingw-w64 默认 win32 线程模型缺 std::mutex/condition_variable (Qt testlib 需要) —— 强制用 posix 变体
#   * testlib 模块依赖 posix 线程, 用 -no-feature-testlib 禁用
#
# 用法:
#   bash docker/pqt/build-qt-mingw.sh [--prefix /opt/qt-mingw] [--jobs N]
#
# 产物: 交叉编译的 Qt 静态库, 安装到 --prefix (默认 /opt/qt-mingw)。
#   构建 windows exe 时挂载该目录, 设置 QT_PLATFORM_DIR 指向它。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

QT_VERSION="5.15.2"
QT_MODULE="qtbase-everywhere-src-${QT_VERSION}"
QT_URL="https://mirrors.tuna.tsinghua.edu.cn/qt/archive/qt/5.15/${QT_VERSION}/submodules/${QT_MODULE}.tar.xz"
PREFIX="${PREFIX:-/opt/qt-mingw}"
JOBS="${JOBS:-$(nproc)}"
# 默认镜像: 优先带版本号 tag（docker/versions.env 的 IMAGE_TAG），未定义则回退 unified
if [[ -z "${IMAGE:-}" ]]; then
  if [[ -f "${SCRIPT_DIR}/../versions.env" ]]; then
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/../versions.env"
    IMAGE="sophon-tools-build:${IMAGE_TAG:-unified}"
  else
    IMAGE="sophon-tools-build:unified"
  fi
fi

echo "==> 下载 Qt ${QT_VERSION} qtbase 源码..."
if [[ ! -f "${REPO_ROOT}/docker/toolchains/${QT_MODULE}.tar.xz" ]]; then
  mkdir -p "${REPO_ROOT}/docker/toolchains"
  curl -fsSL "${QT_URL}" -o "${REPO_ROOT}/docker/toolchains/${QT_MODULE}.tar.xz"
fi
SRC_TARBALL="${REPO_ROOT}/docker/toolchains/${QT_MODULE}.tar.xz"

echo "==> 在镜像 ${IMAGE} 内交叉编译 Qt (jobs=${JOBS}, prefix=${PREFIX})..."
docker run --rm \
  -v "${SRC_TARBALL}":/host/qtbase.tar.xz \
  -v "${PREFIX}":/opt/qt-mingw \
  "${IMAGE}" bash -c "
    set -e
    export DEBIAN_FRONTEND=noninteractive
    # 确保 mingw g++ 存在
    if ! command -v x86_64-w64-mingw32-g++-posix >/dev/null; then
      apt-get update -qq
      apt-get install -y --no-install-recommends g++-mingw-w64-x86-64 >/dev/null 2>&1
    fi
    # 强制 posix 线程模型 (win32 变体缺 std::mutex, Qt testlib 需要)
    # 用 wrapper 覆盖默认 g++/gcc -> posix 变体
    mkdir -p /opt/mingw-posix/bin
    for t in gcc g++ cpp cc c++ gcc-ar gcc-nm gcc-ranlib; do
      if [ -x /usr/bin/x86_64-w64-mingw32-\${t}-posix ]; then
        ln -sf /usr/bin/x86_64-w64-mingw32-\${t}-posix /opt/mingw-posix/bin/x86_64-w64-mingw32-\${t}
      fi
    done
    export PATH=/opt/mingw-posix/bin:\$PATH
    # 验证 posix 线程
    printf '#include <mutex>\nint main(){std::mutex m; m.lock(); return 0;}\n' > /tmp/mt.cpp
    x86_64-w64-mingw32-g++ /tmp/mt.cpp -o /tmp/mt.exe || { echo 'posix g++ 不可用' >&2; exit 1; }
    echo 'posix g++ OK'
    # 解压 + patch
    cd /tmp && rm -rf qte && mkdir qte && tar -xJf /host/qtbase.tar.xz -C qte && cd qte/${QT_MODULE}
    python3 - <<PYEOF
for path in ['src/corelib/global/qglobal.h', 'src/corelib/global/qfloat16.h', 'src/corelib/global/qendian.h']:
    with open(path) as f: content = f.read()
    if '#include <limits>' not in content:
        content = content.replace('#  include <type_traits>', '#  include <type_traits>\n#  include <limits>', 1)
    with open(path, 'w') as f: f.write(content)
print('patched limits include')
PYEOF
    # 配置 + 编译 + 安装
    ./configure -xplatform win32-g++ -device-option CROSS_COMPILE=x86_64-w64-mingw32- \
        -static -release -opensource -confirm-license \
        -prefix /opt/qt-mingw -nomake examples -nomake tests -no-opengl \
        -no-feature-testlib
    make -j${JOBS}
    make install
    echo '==> Qt mingw 交叉编译完成: /opt/qt-mingw'
    ls /opt/qt-mingw/lib/libQt5*.a 2>/dev/null | wc -l
"

echo "==> 完成。构建 pqt windows 时设置:"
echo "    QT_PLATFORM_DIR=${PREFIX}  QT_GCC_PLATFORM_DIR=<mingw posix bin dir>"
