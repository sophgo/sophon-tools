#!/usr/bin/env bash
# pqt 系列(Qt GUI 工具)一键编译脚本 —— linux AppImage / windows exe
#
# 支持子项目: pqt_memory_edit(图形化远程内存修改工具)
#
# 注意: pqt_batch_deployment(批量部署工具)自 v2.0.0 起改为 Go + Fyne 实现,
#   不再走 Qt/AppImage/Enigma 这套流程, 请直接用它的自带脚本:
#       cd source/pqt_batch_deployment && bash release.sh all
#   本脚本对它只报错退出, 避免有人照着旧文档跑出莫名其妙的 CMake 错误。
#
# 用法:
#   bash docker/pqt/build-pqt.sh --project pqt_memory_edit --linux       # linux AppImage
#   bash docker/pqt/build-pqt.sh --project pqt_memory_edit --windows     # windows exe (需 Qt mingw)
#   bash docker/pqt/build-pqt.sh --project pqt_memory_edit --all         # 两端
#   bash docker/pqt/build-pqt.sh --project pqt_memory_edit --all
#
# 两种运行模式:
#   * 宿主模式(默认): 用 docker 起 pqt 专用容器(旧三镜像方案, 镜像 sophon-tools-build-pqt)。
#   * inplace 模式(--inplace 或 env PQT_INPLACE=1): 直接在当前环境执行(不嵌套 docker)。
#     M5 起统一镜像 sophon-tools-build:unified 已内置全部依赖(20.04 基座 + Qt5 + mingw),
#     build-all.sh 在统一镜像内以 PQT_INPLACE=1 驱动本脚本, 不再按子项目切换镜像。
#
# 关键前置(linux): pqt_memory_edit 的 resources.qrc 引用 memory_edit.tar.xz,
#   该文件由 source/pmemory_edit/release.sh 生成; 构建前自动生成并复制。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
DOCKER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# 默认镜像: 优先带版本号 tag（docker/versions.env 的 IMAGE_TAG），未定义则回退 unified
if [[ -z "${PQT_IMAGE:-}" ]]; then
  if [[ -f "${DOCKER_DIR}/versions.env" ]]; then
    # shellcheck disable=SC1091
    source "${DOCKER_DIR}/versions.env"
    PQT_IMAGE="sophon-tools-build:${IMAGE_TAG:-unified}"
  else
    PQT_IMAGE="sophon-tools-build:unified"
  fi
fi
PROJECT="pqt_memory_edit"
MODE=""  # linux / windows / all
INPLACE="${PQT_INPLACE:-0}"
VERSION=""       # 显式版本号（透传给 linux_release.sh / CMake）
OUTPUT_DIR=""    # 产物目录（透传给 linux_release.sh 作为工作目录）

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2; continue ;;
    --linux) MODE="linux" ;;
    --windows) MODE="windows" ;;
    --all) MODE="all" ;;
    --inplace) INPLACE=1 ;;
    --version) VERSION="$2"; shift 2; continue ;;
    --output) OUTPUT_DIR="$2"; shift 2; continue ;;
    --image) PQT_IMAGE="$2"; shift 2; continue ;;
    -h|--help)
      grep -E '^#' "$0" | sed 's/^# \{0,1\}//' | head -35
      exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
  shift
done

[[ -n "${MODE}" ]] || { echo "请指定 --linux 或 --windows 或 --all" >&2; exit 1; }
SRC_DIR="${REPO_ROOT}/source/${PROJECT}"
[[ -d "${SRC_DIR}" ]] || { echo "未找到子项目: ${SRC_DIR}" >&2; exit 1; }

# pqt_batch_deployment 已迁到 Go + Fyne，本脚本的 Qt/AppImage 流程对它不再适用。
if [[ "${PROJECT}" = "pqt_batch_deployment" ]]; then
  echo "ERROR: ${PROJECT} 自 v2.0.0 起为 Go + Fyne 实现，不再使用本脚本。" >&2
  echo "       请改用: cd source/${PROJECT} && bash release.sh [all|linux|windows]" >&2
  exit 1
fi

# ---- 准备 memory_edit.tar.xz (pqt_memory_edit 专用) ----
prepare_memory_edit_tarxz() {
  if [[ "${PROJECT}" != "pqt_memory_edit" ]]; then return 0; fi
  local src="${SRC_DIR}/memory_edit.tar.xz"
  if [[ -f "${src}" ]]; then
    echo "==> 已有 memory_edit.tar.xz, 复用"
    return 0
  fi
  echo "==> 生成 memory_edit.tar.xz (来自 pmemory_edit)..."
  local pmem="${REPO_ROOT}/source/pmemory_edit"
  (cd "${pmem}" && bash release.sh >/dev/null 2>&1)
  local tarxz
  tarxz="$(find "${pmem}/output" -name 'memory_edit_*.tar.xz' 2>/dev/null | head -1)"
  if [[ -z "${tarxz}" ]]; then
    echo "错误: pmemory_edit 未产出 memory_edit tar.xz" >&2
    exit 1
  fi
  cp "${tarxz}" "${src}"
  echo "==> 已复制: ${src}"
}

# mingw posix 线程包装(统一镜像/宿主通用): Qt 静态库需要 std::mutex, 强制 posix 变体
setup_mingw_posix() {
  if ! command -v x86_64-w64-mingw32-g++-posix >/dev/null; then
    echo "==> 安装 g++-mingw-w64-x86-64 (posix)..." >&2
    apt-get update -qq
    apt-get install -y --no-install-recommends g++-mingw-w64-x86-64 >/dev/null 2>&1
  fi
  mkdir -p /opt/mingw-posix/bin
  for t in gcc g++ cpp cc c++ gcc-ar gcc-nm gcc-ranlib; do
    [ -x /usr/bin/x86_64-w64-mingw32-${t}-posix ] && ln -sf /usr/bin/x86_64-w64-mingw32-${t}-posix /opt/mingw-posix/bin/x86_64-w64-mingw32-${t}
  done
  export PATH=/opt/mingw-posix/bin:$PATH
  printf '#include <mutex>\nint main(){std::mutex m; m.lock(); return 0;}\n' > /tmp/mt.cpp
  x86_64-w64-mingw32-g++ /tmp/mt.cpp -o /tmp/mt.exe || { echo 'posix g++ 不可用' >&2; exit 1; }
}

# 大写 mingw 头文件 + WS2_32 兼容(代码 include <Winsock2.h>)
setup_mingw_headers() {
  mkdir -p /tmp/mingw-inc
  ln -sf /usr/x86_64-w64-mingw32/include/winsock2.h /tmp/mingw-inc/Winsock2.h
  ln -sf /usr/x86_64-w64-mingw32/lib/libws2_32.a /usr/x86_64-w64-mingw32/lib/libWS2_32.a
}

# ---- linux 端: AppImage ----
build_linux() {
  prepare_memory_edit_tarxz
  # linux_release.sh 工作目录：独立 .build-linux 子目录，OUTPUT_DIR 根只放最终 AppImage
  local work="${OUTPUT_DIR:-${SRC_DIR}/.build}/.build-linux"
  mkdir -p "${work}"
  if [[ "${INPLACE}" = "1" ]]; then
    echo "==> (inplace) 构建 ${PROJECT} linux AppImage ..."
    (cd "${SRC_DIR}" && bash linux_release.sh "${work}" "${VERSION}")
    echo "==> linux AppImage 完成"
    # 收拢最终 AppImage 到 OUTPUT_DIR 根，清理中间产物
    local out_root="${work%/.build-linux}"
    find "${work}" -maxdepth 1 -name '*.AppImage' -exec cp -f {} "${out_root}"/ \;
    rm -rf "${work}" 2>/dev/null || sudo rm -rf "${work}" 2>/dev/null || true
    return 0
  fi
  echo "==> 构建 ${PROJECT} linux AppImage (镜像 ${PQT_IMAGE})..."
  # 确保镜像存在
  docker image inspect "${PQT_IMAGE}" >/dev/null 2>&1 || {
    echo "ERROR: 统一构建镜像 ${PQT_IMAGE} 不存在。" >&2
    echo "       获取方式:" >&2
    echo "         1) 从 dfss 拉取: bash docker/build.sh --from-dfss" >&2
    echo "         2) 本地构建:     bash docker/build.sh --with-dfss-toolchains --with-qt-mingw --with-sophui-toolchain" >&2
    echo "       或改用 inplace 模式在统一镜像内直接执行: PQT_INPLACE=1 bash $0 --project ${PROJECT} --linux" >&2
    return 1
  }
  docker run --rm --privileged \
    -v /dev:/dev \
    -v "${SRC_DIR}":/root/workspace \
    -v "${work}":/pqt-output \
    -w /root/workspace \
    "${PQT_IMAGE}" /bin/bash -c "
      git config --global --add safe.directory /root/workspace
      bash linux_release.sh /pqt-output ${VERSION}
    " 2>&1 | tail -20
  echo "==> linux AppImage 完成"
  # 收拢最终 AppImage 到 OUTPUT_DIR 根，清理中间产物
  local out_root="${work%/.build-linux}"
  find "${work}" -maxdepth 1 -name '*.AppImage' -exec cp -f {} "${out_root}"/ \;
  rm -rf "${work}" 2>/dev/null || sudo rm -rf "${work}" 2>/dev/null || true
}

# ---- windows 端: exe (需 Qt mingw 交叉编译环境) ----
build_windows() {
  echo "==> windows 端交叉编译..."
  prepare_memory_edit_tarxz
  # 产物基线名（无版本号）：裸名 exe 由 CMake install(TARGETS) 生成，是中间产物；
  # 最终交付的是带版本号的 <basename>_<ver>.exe，收拢时只保留后者。
  local exe_basename
  case "$PROJECT" in
    pqt_memory_edit) exe_basename="qt_mem_edit.exe" ;;
    *) exe_basename="" ;;
  esac
  local qt_prefix="${QT_PREFIX:-/opt/qt-mingw}"
  # 确保 Qt mingw 静态库存在
  if [[ ! -f "${qt_prefix}/lib/libQt5Widgets.a" ]]; then
    if [[ "${INPLACE}" = "1" ]]; then
      echo "错误: 统一镜像内缺少 Qt mingw 静态库 (${qt_prefix})。" >&2
      echo "       请用 --with-qt-mingw 重建统一镜像(或把 13.24 /opt/qt-mingw 导出为 toolchains/qt-mingw.tar.zst)。" >&2
      exit 1
    fi
    echo "==> 未找到 Qt mingw 静态库 (${qt_prefix}), 先交叉编译 Qt (约 20-40 分钟)..."
    PREFIX="${qt_prefix}" bash "${DOCKER_DIR}/pqt/build-qt-mingw.sh" || {
      echo "Qt mingw 编译失败" >&2; exit 1
    }
  fi

  # 独立构建子目录（.build-win）：OUTPUT_DIR 根只放最终产物，中间产物（cmake 生成物）全部在此，构建后清理
  local wdir="${OUTPUT_DIR:-${SRC_DIR}/build-win}/.build-win"
  mkdir -p "${wdir}"

  if [[ "${INPLACE}" = "1" ]]; then
    # 直接在统一镜像内执行(工具链已内置, 当前 shell 内函数可直接使用)
    setup_mingw_posix
    setup_mingw_headers
    cd "${wdir}"
    export QT_PLATFORM_DIR="${qt_prefix}"
    export QT_GCC_PLATFORM_DIR=/opt/mingw-posix/bin
    cat > /tmp/tc.cmake <<TOOL
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(CMAKE_C_COMPILER x86_64-w64-mingw32-gcc)
set(CMAKE_CXX_COMPILER x86_64-w64-mingw32-g++)
set(CMAKE_FIND_ROOT_PATH ${qt_prefix} /usr/x86_64-w64-mingw32)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
TOOL
    cmake "${SRC_DIR}" -DCMAKE_TOOLCHAIN_FILE=/tmp/tc.cmake -DCMAKE_BUILD_TYPE=Release \
      "-DCMAKE_CXX_FLAGS=-I/tmp/mingw-inc" "-DCMAKE_C_FLAGS=-I/tmp/mingw-inc" \
      ${VERSION:+-DMY_PROJECT_VERSION=${VERSION}}
    make -j"$(nproc)"
    # windeployqt/openssl 拷贝/静态改名打包步骤挂在 install() 上，必须 make install 才能产出自包含 exe
    make install
    echo "==> windows exe 产物:"
    find . -maxdepth 3 -name '*.exe' | head -5
    # 收拢最终 exe 到 OUTPUT_DIR 根（只留带版本号的 exe，排除裸名中间产物），
    # 清理构建中间产物（先 cd 出去再删，避免删除当前工作目录）
    local out_root="${wdir%/.build-win}"
    find . -maxdepth 3 -name '*.exe' ! -name "${exe_basename}" -exec cp -f {} "${out_root}"/ \;
    cd "${out_root}"
    rm -rf "${wdir}" 2>/dev/null || sudo rm -rf "${wdir}" 2>/dev/null || true
    return 0
  fi

  # 宿主模式: 在 sophon-tools-build 镜像内交叉编译（out-of-source: 构建目录为 .build-win 子目录）
  local image="${IMAGE:-sophon-tools-build:unified}"
  local out_root="${wdir%/.build-win}"
  mkdir -p "${out_root}"
  docker run --rm \
    -v "${SRC_DIR}":/workspace/src \
    -v "${wdir}":/pqt-win-output \
    -v "${out_root}":/pqt-out-root \
    -v "${qt_prefix}":/opt/qt-mingw \
    -e PQT_WIN_OUT="/pqt-win-output" \
    -e PQT_VERSION="${VERSION}" \
    -e EXE_BASENAME="${exe_basename}" \
    "${image}" bash -c '
      set -e
      export DEBIAN_FRONTEND=noninteractive
      if ! command -v x86_64-w64-mingw32-g++-posix >/dev/null; then
        apt-get update -qq
        apt-get install -y --no-install-recommends g++-mingw-w64-x86-64 >/dev/null 2>&1
      fi
      # posix 线程模型 (Qt 静态库需要 std::mutex)
      mkdir -p /opt/mingw-posix/bin
      for t in gcc g++ cpp cc c++ gcc-ar gcc-nm gcc-ranlib; do
        [ -x /usr/bin/x86_64-w64-mingw32-${t}-posix ] && ln -sf /usr/bin/x86_64-w64-mingw32-${t}-posix /opt/mingw-posix/bin/x86_64-w64-mingw32-${t}
      done
      export PATH=/opt/mingw-posix/bin:$PATH
      # 大写 mingw 头文件符号链接 (代码 include <Winsock2.h>)
      mkdir -p /tmp/mingw-inc
      ln -sf /usr/x86_64-w64-mingw32/include/winsock2.h /tmp/mingw-inc/Winsock2.h
      # WS2_32 库大小写兼容
      ln -sf /usr/x86_64-w64-mingw32/lib/libws2_32.a /usr/x86_64-w64-mingw32/lib/libWS2_32.a
      # mingw toolchain
      cat > /tmp/tc.cmake <<TOOL
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(CMAKE_C_COMPILER x86_64-w64-mingw32-gcc)
set(CMAKE_CXX_COMPILER x86_64-w64-mingw32-g++)
set(CMAKE_FIND_ROOT_PATH /opt/qt-mingw /usr/x86_64-w64-mingw32)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
TOOL
      export QT_PLATFORM_DIR=/opt/qt-mingw
      export QT_GCC_PLATFORM_DIR=/opt/mingw-posix/bin
      mkdir -p "${PQT_WIN_OUT}" && cd "${PQT_WIN_OUT}"
      cmake /workspace/src -DCMAKE_TOOLCHAIN_FILE=/tmp/tc.cmake -DCMAKE_BUILD_TYPE=Release \
        "-DCMAKE_CXX_FLAGS=-I/tmp/mingw-inc" "-DCMAKE_C_FLAGS=-I/tmp/mingw-inc" \
        ${PQT_VERSION:+-DMY_PROJECT_VERSION=${PQT_VERSION}}
      make -j$(nproc)
      # windeployqt/openssl 拷贝/静态改名打包步骤挂在 install() 上，必须 make install 才能产出自包含 exe
      make install
      echo "==> windows exe 产物:"
      find . -maxdepth 3 -name '*.exe' | head -5
      # 收拢最终 exe 到输出根目录（挂载的 /pqt-out-root = OUTPUT_DIR），
      # 只留带版本号的 exe，排除裸名中间产物；构建中间产物留在 .build-win
      mkdir -p /pqt-out-root
      find . -maxdepth 3 -name '*.exe' ! -name "${EXE_BASENAME}" -exec cp -f {} /pqt-out-root/ \;
    '

  # 构建中间产物（.build-win）留在宿主 wdir，构建完成后清理
  rm -rf "${wdir}" 2>/dev/null || sudo rm -rf "${wdir}" 2>/dev/null || true
}

case "${MODE}" in
  linux) build_linux ;;
  windows) build_windows ;;
  all) build_linux; build_windows ;;
esac