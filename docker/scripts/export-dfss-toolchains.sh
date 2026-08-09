#!/usr/bin/env bash
# 从 13.24 服务器的容器导出 dfss 私有工具链（sw_64 / loongarch64）。
# 用法:
#   bash docker/scripts/export-dfss-toolchains.sh [--container <name>] [--out <dir>]
#     --container  源容器名（默认 bm1684_zzt，镜像 cross_build_sophon_u20:v1）
#     --out        导出目录（默认 docker/toolchains/）
#
# 导出为 .tar.zst 后，`bash docker/build.sh --with-dfss-toolchains` 会将其内置于镜像；
# 若导出目录已存在同名归档，直接复用，不重复导出。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DOCKER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

CONTAINER="${CONTAINER:-bm1684_zzt}"
OUT_DIR="${OUT_DIR:-${DOCKER_DIR}/toolchains}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --container) CONTAINER="$2"; shift 2 ;;
    --out) OUT_DIR="$2"; shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

mkdir -p "${OUT_DIR}"

# 容器内工具链路径（cross_build_sophon_u20:v1 / cross_build_sophon:v7 通用）
SW64_SRC="/usr/sw/swgcc830_cross_tools"
LOONG_SRC="/env/loongson-gnu-toolchain-8.3-x86_64-loongarch64-linux-gnu-rc1.1"

SW64_ARCHIVE="${OUT_DIR}/swgcc830_cross_tools.tar.zst"
LOONG_ARCHIVE="${OUT_DIR}/loongarch64-cross-tools.tar.zst"

# 区分容器 / 镜像两种来源: 容器用 docker exec, 镜像用 docker run（避免镜像名误入 docker exec 报误导错误）
RUN_MODE=""
if docker inspect "${CONTAINER}" >/dev/null 2>&1; then
  RUN_MODE="container"
elif docker image inspect "${CONTAINER}" >/dev/null 2>&1; then
  RUN_MODE="image"
else
  echo "错误: 找不到容器/镜像 '${CONTAINER}'。" >&2
  echo "请在 13.24 服务器上运行（镜像 cross_build_sophon_u20:v1 / cross_build_sophon:v7 内置工具链）:" >&2
  echo "  docker run -d --name dfss-toolchain-src --entrypoint sleep cross_build_sophon_u20:v1 infinity" >&2
  exit 1
fi

# 在容器 / 镜像内执行命令
run_in() {
  local cmd="$1"
  if [[ "${RUN_MODE}" = "container" ]]; then
    docker exec "${CONTAINER}" sh -c "${cmd}"
  else
    docker run --rm --entrypoint sh "${CONTAINER}" -c "${cmd}"
  fi
}

# 工具链是否在容器 / 镜像内
if ! run_in "test -d '${SW64_SRC}'" >/dev/null 2>&1 \
   && ! run_in "test -d '${LOONG_SRC}'" >/dev/null 2>&1; then
  echo "错误: ${RUN_MODE} '${CONTAINER}' 中未找到 ${SW64_SRC} 或 ${LOONG_SRC}。" >&2
  exit 1
fi

# 打 tar（容器内无 zstd 则用 tar czf 走 gzip）
pack_from_container() {
  local src="$1" archive="$2"
  if [[ -f "${archive}" ]]; then
    echo "已存在: ${archive}（跳过）"
    return 0
  fi
  echo "导出 ${src} -> ${archive} ..."
  if run_in 'command -v zstd' >/dev/null 2>&1; then
    run_in "tar -C '$(dirname "${src}")' -cf - '$(basename "${src}")' | zstd -q -T0" > "${archive}"
  else
    run_in "tar -C '$(dirname "${src}")' -czf - '$(basename "${src}")'" > "${archive}"
  fi
  ls -lh "${archive}"
}

pack_from_container "${SW64_SRC}" "${SW64_ARCHIVE}"
pack_from_container "${LOONG_SRC}" "${LOONG_ARCHIVE}"

echo "完成。工具链归档位于 ${OUT_DIR}"
echo "构建镜像时加 --with-dfss-toolchains 自动内置，或在 Dockerfile 构建上下文放 toolchains/ 目录。"
