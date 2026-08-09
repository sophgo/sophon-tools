#!/bin/bash
# =============================================================================
# sophon-tools 一键全量 release（M4 统一入口 / M5 单镜像；各子项目默认平台）
#
# 用法:
#   bash release.sh [--project <子项目>] [--version <版本号>] [--no-image-check]
#
# 行为:
#   1. 检查统一构建镜像 sophon-tools-build:unified（M5 单镜像, ubuntu:20.04 基座）
#      是否可用；缺失时提示用 `bash docker/build.sh` 构建（不自动构建，避免长时间阻塞）。
#   2. 驱动 docker/build-all.sh 对全部子项目做构建（各子项目默认平台；失败隔离：
#      单项目失败不阻塞整体，结束后列出失败项，非零退出）。
#   3. 汇聚产物到 output/<子项目>/（保持既有 output 约定），并生成:
#        - output/MANIFEST.txt   产物清单（子项目/文件名/架构/版本/md5）
#        - output/git_hash.txt   构建时仓库 HEAD
#        - output/.build-status.txt  各子项目 PASS/FAIL 状态（供脚本读取）
#
# 退出码:
#   0  全部子项目构建成功
#   1  存在失败子项目（含镜像缺失等前置检查失败）
#
# 向后兼容: 支持 --project 单项目快速构建; 无参数 = 全量。
# =============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "${SCRIPT_DIR}" || exit 1

# 默认镜像: 优先带版本号 tag（docker/versions.env 的 IMAGE_TAG），未定义则回退 unified
if [[ -z "${IMAGE:-}" ]]; then
  if [[ -f "${SCRIPT_DIR}/docker/versions.env" ]]; then
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/docker/versions.env"
    IMAGE="sophon-tools-build:${IMAGE_TAG:-unified}"
  else
    IMAGE="sophon-tools-build:unified"
  fi
fi
ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) ARGS+=(--project "$2"); shift 2; continue ;;
    --version) ARGS+=(--version "$2"); shift 2; continue ;;
    --image) IMAGE="$2"; shift 2; continue ;;
    --no-image-check) NO_IMAGE_CHECK=1; shift ;;
    -h|--help)
      grep -E '^# ' "$0" | sed 's/^# \{0,1\}//' | head -40
      exit 0 ;;
    *) echo "未知参数: $1（用 bash release.sh --help 查看）" >&2; exit 1 ;;
  esac
  shift
done

echo "==> sophon-tools 一键全量 release（M5 单镜像 ${IMAGE}）"
echo "==> 工作目录: ${SCRIPT_DIR}"

# --- 1. 镜像前置检查 --------------------------------------------------------
if [[ -z "${NO_IMAGE_CHECK:-}" ]]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: 未找到 docker，本构建依赖 Docker 统一镜像。请先安装 docker。" >&2
    exit 1
  fi
  if ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
    echo "ERROR: 统一构建镜像 ${IMAGE} 不存在。" >&2
    echo "       获取方式（按优先级）:" >&2
    echo "         1) 从 dfss 服务器拉取已构建镜像（推荐，免本地构建）:" >&2
    echo "            python3 -m dfss --url=open@sophgo.com:/<dfss路径>/${IMAGE%%:*}-${IMAGE#*:}.tar.zst" >&2
    echo "            docker load -i ${IMAGE%%:*}-${IMAGE#*:}.tar.zst" >&2
    echo "         2) 本地构建: bash docker/build.sh [--with-dfss-toolchains]" >&2
    echo "         3) 指定已有镜像: bash release.sh --image <镜像名>" >&2
    exit 1
  fi
  echo "==> 镜像就绪: ${IMAGE}"
fi

# --- 2. 全量构建（失败隔离由 docker/build-all.sh 负责） -----------------------
bash "${SCRIPT_DIR}/docker/build-all.sh" --image "${IMAGE}" "${ARGS[@]}"
BUILD_RC=$?

# --- 3. 产物清单 + git_hash + 构建状态 ----------------------------------------
echo ""
echo "==> 生成产物清单..."
bash "${SCRIPT_DIR}/docker/gen-manifest.sh" >/dev/null 2>&1 \
  && echo "==> 产物清单: output/MANIFEST.txt" \
  || echo "WARN: 生成产物清单失败" >&2

echo "==> 写入 git_hash.txt ..."
git rev-parse HEAD 2>/dev/null | tee output/git_hash.txt \
  || echo "WARN: 无法获取 git HEAD（非 git 仓库？）" >&2

# 构建状态汇总由 docker/build-all.sh 写入 output/.build-status.txt
# （各子项目 PASS / FAIL:<rc> / SKIP），供脚本与人读取。

if [[ "${BUILD_RC}" = "0" ]]; then
  echo ""
  echo "=========================================================="
  echo "==> ✅ 全部子项目构建成功"
  echo "==> 产物目录: output/"
  echo "==> 清单文件: output/MANIFEST.txt"
  echo "=========================================================="
  exit 0
else
  echo ""
  echo "=========================================================="
  echo "==> ⚠️ 存在失败子项目（见上方构建汇总）"
  echo "==> 其余子项目产物仍已生成，见 output/MANIFEST.txt"
  echo "=========================================================="
  exit 1
fi
