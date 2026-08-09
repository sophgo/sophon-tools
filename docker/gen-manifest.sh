#!/usr/bin/env bash
# 生成统一产物清单 MANIFEST.txt（文件名 / 架构 / 版本 / md5）
#
# 用法:
#   bash docker/gen-manifest.sh                 # 默认扫描仓库根 output/
#   bash docker/gen-manifest.sh --output <dir>  # 指定产物目录
#
# 输出: <output>/MANIFEST.txt
# 说明:
#   - 递归扫描 output/<子项目>/ 下的全部文件（跳过顶层 MANIFEST.txt/git_hash.txt 等元数据）
#   - 架构: 优先从文件名关键字推断; 否则用 `file` 探测; 无信息记 unknown
#   - 版本: 从文件名中的 v?<数字>.<数字>.<数字> 提取; 无则 unknown
#   - md5: 全部计算
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUT_ROOT="${OUTPUT_ROOT:-${REPO_ROOT}/output}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) OUT_ROOT="$2"; shift 2; continue ;;
    -h|--help) grep -E '^#' "$0" | sed 's/^# \{0,1\}//' | head -20; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
  shift
done

MANIFEST="${OUT_ROOT}/MANIFEST.txt"
: > "${MANIFEST}"

detect_arch() {
  # $1=文件名 $2=文件路径
  local name="$1" path="$2"
  case "$name" in
    *win*amd64*|*win*x86_64*) echo "win-amd64"; return ;;
    *win*i686*|*win*32*)      echo "win-i686"; return ;;
    # 无 win 关键字的 .exe：用 file 探测区分 PE32+ / PE32（不再无条件 win-amd64）
    *\.exe)
      local ftype
      ftype="$(file -b "$path" 2>/dev/null)"
      case "$ftype" in
        *PE32+*) echo "win-amd64"; return ;;
        *PE32*)  echo "win-i686"; return ;;
      esac
      echo "win-amd64"; return ;;
    *arm64*|*aarch64*|*_arm64*)  echo "arm64"; return ;;
    *amd64*|*x86_64*|*x86-64*)   echo "amd64"; return ;;
    *armbi*) echo "armbi"; return ;;
    *loongarch64*) echo "loongarch64"; return ;;
    *riscv64*) echo "riscv64"; return ;;
    *sw_64*) echo "sw_64"; return ;;
    *i686*) echo "i686"; return ;;
  esac
  # .deb 用包元数据（Architecture 字段）
  if [[ "${name}" == *.deb ]] && command -v dpkg-deb >/dev/null 2>&1; then
    local a
    a="$(dpkg-deb -f "$path" Architecture 2>/dev/null)"
    case "$a" in
      arm64|amd64|armel|all) echo "${a}"; return ;;
    esac
  fi
  # 探测 ELF/PE
  local ftype
  ftype="$(file -b "$path" 2>/dev/null)"
  case "$ftype" in
    *aarch64*) echo "arm64"; return ;;
    *x86-64*) echo "amd64"; return ;;
    *ARM*) echo "arm"; return ;;
    *MIPS*) echo "mips"; return ;;
    *"RISC-V"*) echo "riscv64"; return ;;
    *PE32+*) echo "win-amd64"; return ;;
    *PE32*) echo "win-i686"; return ;;
    *ELF*) echo "elf"; return ;;
  esac
  echo "unknown"
}

detect_ver() {
  local name="$1"
  local v
  v="$(echo "$name" | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1)"
  echo "${v:-unknown}"
}

echo "==> 生成产物清单: ${MANIFEST}"
printf '%-22s | %-52s | %-14s | %-10s | %s\n' \
  "子项目" "文件名" "架构" "版本" "md5" | tee -a "${MANIFEST}"
printf '%s\n' "---------------------+-----------------------------------------------------+----------------+------------+----------------------------------" >> "${MANIFEST}"

TOTAL=0
for pdir in "${OUT_ROOT}"/*/; do
  [[ -d "${pdir}" ]] || continue
  p="$(basename "${pdir}")"
  [[ "${p}" = "." || "${p}" = ".." ]] && continue
  # 递归扫描子目录内全部文件（如 pota_update/arm64_bin/bc），跳过顶层元数据文件
  while IFS= read -r -d '' f; do
    rel="${f#"${pdir}"}"
    name="$(basename "${f}")"
    if [[ "${rel}" != */* ]]; then
      case "${name}" in
        MANIFEST.txt|git_hash.txt|.build-status.txt|.gitkeep) continue ;;
      esac
    fi
    md5="$(md5sum "${f}" | awk '{print $1}')"
    arch="$(detect_arch "${name}" "${f}")"
    ver="$(detect_ver "${name}")"
    printf '%-22s | %-52s | %-14s | %-10s | %s\n' \
      "${p}" "${rel}" "${arch}" "${ver}" "${md5}" | tee -a "${MANIFEST}"
    TOTAL=$((TOTAL+1))
  done < <(find "${pdir}" -type f -print0)
done

echo "==> 清单完成: ${TOTAL} 个文件, 见 ${MANIFEST}"
