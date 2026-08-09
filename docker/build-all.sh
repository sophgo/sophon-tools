#!/usr/bin/env bash
# sophon-tools-build 统一构建全部子项目（镜像内一键编译）
#
# 目标: 在 sophon-tools-build 统一镜像内预装工具链, 对全部子项目执行所有平台的编译。
# 本脚本是统一入口, 按 M1 规范驱动每个子项目的 release.sh（统一接口）。
#
# M5 变更: 单镜像方案。三镜像(sophon-tools-build:m2 / sophon-tools-build-pqt /
# cross_build_sophon_u20:v1)合并为单个 ubuntu:20.04 基座镜像 sophon-tools-build:unified,
# 不再按子项目切换镜像; pqt 系列/pSophUI 全部在统一镜像内构建。
#
# 统一接口 (M1 规范 v0.1):
#   bash release.sh [ARCH] [VERSION]
#     ARCH:    arm64 | amd64 | all（默认按子项目）
#     VERSION: 显式版本号（缺省用子项目版本来源）
#     env OUTPUT_DIR: 覆盖产物目录（默认 <repo>/output/<子项目>/）
#
# 范围: 16 个子项目（pmulti_video_qt 已按 MYSWY 决定排除）
#
# 用法:
#   bash docker/build-all.sh                    # 构建全部子项目(默认平台)
#   bash docker/build-all.sh --project pbmssm   # 只构建指定子项目
#   bash docker/build-all.sh --arch arm64       # 只构建指定架构
#   bash docker/build-all.sh --image sophon-tools-build:unified
#   bash docker/build-all.sh --version 2.1.0    # 统一显式版本号（透传给所有 release.sh）
#   bash docker/build-all.sh --list             # 列出子项目与平台
#
# 产物: 全部汇聚到仓库根 output/<子项目>/ (与根 release.sh 一致)
# 失败隔离: 单子项目失败不影响其他项目，结束后汇总 PASS/FAIL，非零退出码。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
DOCKER_DIR="${SCRIPT_DIR}"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

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
ONLY_PROJECT=""
ONLY_ARCH=""
BUILD_VERSION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) ONLY_PROJECT="$2"; shift 2; continue ;;
    --arch) ONLY_ARCH="$2"; shift 2; continue ;;
    --image) IMAGE="$2"; shift 2; continue ;;
    --version) BUILD_VERSION="$2"; shift 2; continue ;;
    --list) LIST_ONLY=1 ;;
    -h|--help) grep -E '^#' "$0" | sed 's/^# \{0,1\}//' | head -40; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
  shift
done

# 子项目 -> 默认平台 (release.sh 的第一参数 ARCH)
declare -A DEFAULT_ARCH
DEFAULT_ARCH[pbmssm]=arm64
DEFAULT_ARCH[psophliteos]=arm64
DEFAULT_ARCH[pbmsec]=all
DEFAULT_ARCH[psocbak]=arm64
DEFAULT_ARCH[pget_info]=amd64
DEFAULT_ARCH[pmem_aging_test]=arm64
DEFAULT_ARCH[pmemory_edit]=arm64
DEFAULT_ARCH[pota_update]=arm64
DEFAULT_ARCH[pautotelecomm]=arm64
DEFAULT_ARCH[pbm_set_ip]=arm64
DEFAULT_ARCH[pdfss_cpp]=host
DEFAULT_ARCH[pqt_batch_deployment]=amd64
DEFAULT_ARCH[pqt_memory_edit]=amd64
DEFAULT_ARCH[pSophUI]=arm64
# pmulti_video_qt: 按 MYSWY 决定（2026-08-08）不需要做，从统一构建范围排除
DEFAULT_ARCH[psoph_phytool]=all
DEFAULT_ARCH[pspacc_efuse_demo]=amd64

# 子项目 -> 平台说明 (M1 盘点)
declare -A PLATFORMS
PLATFORMS[pbmssm]="arm64(musl静态)/amd64"
PLATFORMS[psophliteos]="arm64(musl静态)/amd64"
PLATFORMS[pbmsec]="all(deb含双架构)"
PLATFORMS[psocbak]="arm64"
PLATFORMS[pget_info]="arm64/amd64"
PLATFORMS[pmem_aging_test]="arm64"
PLATFORMS[pmemory_edit]="arm64"
PLATFORMS[pota_update]="arm64"
PLATFORMS[pautotelecomm]="arm64(仅arm64，aarch64预编译二进制)"
PLATFORMS[pbm_set_ip]="arm64(musl静态)/amd64"
PLATFORMS[pdfss_cpp]="amd64/arm64/armbi/loongarch64/riscv64/sw_64/win-amd64/win-i686"
PLATFORMS[pqt_batch_deployment]="amd64/arm64 + windows"
PLATFORMS[pqt_memory_edit]="amd64/arm64 + windows"
PLATFORMS[pSophUI]="arm64(交叉Qt)"
PLATFORMS[psoph_phytool]="通用脚本"
PLATFORMS[pspacc_efuse_demo]="amd64/arm64"

# M5: 全部子项目统一用 sophon-tools-build:unified（20.04 基座）, 不再按子项目切换镜像。
#   pqt 系列: 统一镜像基座即 20.04(glibc 2.31), AppImage 的 linuxdeployqt 约束已满足,
#             windows exe 依赖的 Qt mingw 静态库由 --with-qt-mingw 内置。
#   pSophUI: 统一镜像内置 /env/qt_5.12.8_nosysroot（编译用系统 apt aarch64-linux-gnu-gcc 9.4）。

# 子项目 -> 额外环境 (镜像内 export; 以 ; 分隔)
# M5: 统一镜像已在 PATH/ENV 预置 Go/Node/Rust/交叉工具链及 pSophUI 工具链,
#       release.sh 默认即指向 /env 路径, 一般无需额外 export。
# pqt 系列: build-pqt.sh 以 PQT_INPLACE=1 直接在容器内执行(不再嵌套 docker)。
declare -A EXTRA_ENV
EXTRA_ENV[pbm_set_ip]="export PATH=\${HOME}/.cargo/bin:/opt/cargo/bin:\$PATH"
EXTRA_ENV[psophliteos]="export PATH=/opt/nodejs/bin:/opt/go/bin:\$PATH"
EXTRA_ENV[pbmssm]="export PATH=/opt/go/bin:\$PATH"
EXTRA_ENV[pdfss_cpp]="export PATH=/env/loongson-gnu-toolchain-8.3-x86_64-loongarch64-linux-gnu-rc1.1/bin:/usr/sw/swgcc830_cross_tools/usr/bin:\$PATH"
EXTRA_ENV[pqt_batch_deployment]="export PQT_INPLACE=1"
EXTRA_ENV[pqt_memory_edit]="export PQT_INPLACE=1"

# 子项目 -> 构建依赖（先构建依赖方，再构建本项目）
# pbmsec 的 socbak.zip 取自 psocbak（release.sh 会优先复用其产物，缺失时现场打包），
# 因此 psocbak 必须先于 pbmsec 构建，否则干净 checkout 上 pbmsec 会失败。
declare -A DEPENDS
DEPENDS[pbmsec]=psocbak

if [[ "${LIST_ONLY:-0}" = "1" ]]; then
  echo "=== sophon-tools 16 子项目构建清单（pmulti_video_qt 已排除，单镜像 ${IMAGE}） ==="
  for p in $(echo "${!DEFAULT_ARCH[@]}" | tr ' ' '\n' | sort); do
    printf "  %-22s 平台: %-40s 镜像: %s\n" "$p" "${PLATFORMS[$p]}" "${IMAGE}"
  done
  exit 0
fi

# 输出目录
mkdir -p "${REPO_ROOT}/output"
echo "==> 统一构建, 输出: ${REPO_ROOT}/output, 镜像: ${IMAGE}"

# 各子项目构建结果（失败隔离汇总）: "<项目>|<退出码>"
RESULTS=()

run_one() {
  local p="$1"
  local arch="${ONLY_ARCH:-${DEFAULT_ARCH[$p]}}"
  echo ""
  echo "========== [${p}] 平台: ${PLATFORMS[$p]} arch=${arch} 镜像: ${IMAGE} =========="
  local src_dir="${REPO_ROOT}/source/${p}"
  if [[ ! -d "${src_dir}" ]]; then
    echo "  [SKIP] 目录不存在: ${src_dir}"
    RESULTS+=("${p}|skip")
    return 0
  fi

  local rc=0
  local extra_env="${EXTRA_ENV[$p]:-}"
  docker run --rm --privileged \
    -v /dev:/dev \
    -v "${REPO_ROOT}":/workspace/sophon-tools \
    -w "/workspace/sophon-tools/source/${p}" \
    -e OUTPUT_DIR="/workspace/sophon-tools/output/${p}" \
    "${IMAGE}" bash -c "
      set -euo pipefail
      git config --global --add safe.directory '*' 2>/dev/null || true
      git config --global --add safe.directory /workspace/sophon-tools 2>/dev/null || true
      ${extra_env}
      echo '  >> bash release.sh ${arch} ${BUILD_VERSION}'
      bash release.sh ${arch} ${BUILD_VERSION} 2>&1 | tail -20
    " 2>&1 | sed 's/^/    /'
  rc=${PIPESTATUS[0]}
  echo "  [${p}] 退出码: ${rc}"

  if [[ "${rc}" = "0" ]]; then
    RESULTS+=("${p}|ok")
  else
    RESULTS+=("${p}|fail:${rc}")
  fi
}

# 构建顺序: 有依赖的项目等其依赖方先构建完；无依赖按字母序。
# 去重 + 拓扑排序（本项目仅一层依赖，简单处理即可）。
build_order() {
  local order=() seen=" "
  local p d
  for p in $(echo "${!DEFAULT_ARCH[@]}" | tr ' ' '\n' | sort); do
    d="${DEPENDS[$p]:-}"
    if [[ -n "$d" && "$seen" != *" $d "* ]]; then
      order+=("$d"); seen="$seen$d "
    fi
    if [[ "$seen" != *" $p "* ]]; then
      order+=("$p"); seen="$seen$p "
    fi
  done
  printf '%s\n' "${order[@]}"
}

if [[ -n "${ONLY_PROJECT}" ]]; then
  run_one "${ONLY_PROJECT}"
else
  for p in $(build_order); do
    run_one "$p"
  done
fi

# ---- 构建后清理：pSophUI 的 qmake 会在源码树内重生成 Makefile 并留下编译产物 ----
# Makefile 是 qmake 生成物（仓库内为旧版 /env/qt_fl2000 路径），构建时被重写。
# 为避免每次全量 release 弄脏工作区，构建后恢复仓库内 Makefile 并移除编译产物。
# 产物由容器内 root 创建，清理时优先 sudo（与根 release.sh 旧版一致），无 sudo 则尽力而为。
if [[ -z "${ONLY_PROJECT}" || "${ONLY_PROJECT}" = "pSophUI" ]]; then
  pui="${REPO_ROOT}/source/pSophUI/SophUI"
  if [[ -d "${pui}" ]]; then
    git -C "${REPO_ROOT}" checkout -- "source/pSophUI/SophUI/Makefile" 2>/dev/null || true
    if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
      sudo rm -rf "${pui}"/.qmake.stash \
                  "${pui}"/Makefile.Debug \
                  "${pui}"/Makefile.Release \
                  "${pui}"/release \
                  "${pui}"/ui_mainwindow.h 2>/dev/null || true
      sudo rm -f "${pui}/SophUI" 2>/dev/null || true
      sudo rm -rf "${pui}/deb/opt" 2>/dev/null || true
    else
      rm -rf "${pui}"/.qmake.stash \
             "${pui}"/Makefile.Debug \
             "${pui}"/Makefile.Release \
             "${pui}"/release \
             "${pui}"/ui_mainwindow.h 2>/dev/null || true
      rm -f "${pui}/SophUI" 2>/dev/null || true
      rm -rf "${pui}/deb/opt" 2>/dev/null || true
    fi
  fi
fi

# ---- 构建后清理：pbmsec 的 pandoc/socbak 会把 HTML/man/zip 生成到源码树 deb/ 下 ----
# 这些是中间产物（*.html / *.1 / *.zip 被 gitignore，但目录由容器内 root 创建，
# 宿主后续构建会因权限失败）。统一构建后移除，保持工作区可被宿主持续使用。
if [[ -z "${ONLY_PROJECT}" || "${ONLY_PROJECT}" = "pbmsec" ]]; then
  pbmsec_gen="${REPO_ROOT}/source/pbmsec/deb/opt/sophon/bmsec/doc"
  pbmsec_share="${REPO_ROOT}/source/pbmsec/deb/usr/share"
  pbmsec_socbak="${REPO_ROOT}/source/pbmsec/deb/opt/sophon/bmsec/binTools/socbak.zip"
  if [[ -d "${pbmsec_gen}" || -d "${pbmsec_share}" || -f "${pbmsec_socbak}" ]]; then
    if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
      sudo rm -rf "${pbmsec_gen}" "${pbmsec_share}" "${pbmsec_socbak}" 2>/dev/null || true
    else
      rm -rf "${pbmsec_gen}" "${pbmsec_share}" "${pbmsec_socbak}" 2>/dev/null || true
    fi
  fi
fi

echo ""
echo "=========================================================="
echo "==> 统一构建完成, 产物在 ${REPO_ROOT}/output/"
echo "==> 构建汇总:"
PASS_N=0; FAIL_N=0; SKIP_N=0
STATUS_FILE="${REPO_ROOT}/output/.build-status.txt"
: > "${STATUS_FILE}"
for r in "${RESULTS[@]:-}"; do
  p="${r%%|*}"; st="${r#*|}"
  printf "    %-24s %s\n" "$p" "$st"
  printf "%-24s %s\n" "$p" "$st" >> "${STATUS_FILE}"
  case "$st" in
    ok) PASS_N=$((PASS_N+1)) ;;
    skip) SKIP_N=$((SKIP_N+1)) ;;
    *) FAIL_N=$((FAIL_N+1)) ;;
  esac
done
echo "==> 通过: ${PASS_N}  失败: ${FAIL_N}  跳过: ${SKIP_N}"
echo "==> 状态文件: ${STATUS_FILE}"
echo "=========================================================="
echo "==> 产物清单: bash docker/gen-manifest.sh"
[[ "${FAIL_N}" = "0" ]] || { echo "==> 存在失败项, 请查看上方 [xxx] 退出码" >&2; exit 1; }
echo "==> 镜像自检: bash docker/verify.sh --image ${IMAGE}"
