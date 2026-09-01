#!/bin/bash
# memory_edit -p 打印 vs 实际校验 一致性回归测试（CV84X6）
#
# 背景：CV84X6 环境下 -p 打印的 max vpp / max npu+vpp 比实际可配上限多 2M，
# 根因是打印未减 vpp_size_add（FREERTOS 预留 2M），而 -c 校验减了。
# 修复后打印与校验一致，-p 报出的上限即真实可配上限。
#
# 用法：
#   MEMORY_EDIT_KIT=<kit 目录> \
#     bash tests/check_max_size_consistency.sh
#
# kit 目录 = memory_edit 在目标机上解包后的工作目录，需含：
#   <kit>/memory_edit.sh  <kit>/bintools/  <kit>/boot.itb
#   <kit>/multi.its  <kit>/output/<dts>.dts
# 可用真机 /data/.memedit/memory_edit 或 memory_edit.sh -d 生成的目录。
#
# 断言（无硬编码，全部由 -p 解析值推导，对不同 DDR 容量通用）：
#   A. -c 用 max_vpp 提交必须通过（vpp 单项）
#   B. -c 用 npu=max_npuvpp-4096, vpp=4096 提交必须通过（总量，vpp 在安全区）
set -u

KIT="${MEMORY_EDIT_KIT:-}"
if [ -z "$KIT" ] || [ ! -f "$KIT/boot.itb" ] || [ ! -f "$KIT/multi.its" ]; then
  echo "ERROR: 需要 MEMORY_EDIT_KIT=<kit 目录>（含 boot.itb + multi.its）" >&2
  exit 2
fi
KIT=$(readlink -f "$KIT")

# 在临时副本里跑，绝不污染真实 kit；memory_edit.sh 用本仓库源码覆盖 kit 自带版
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp -a "$KIT"/. "$TMP"/
SRC=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
cp -f "$SRC/source/memory_edit/memory_edit.sh" "$TMP/"
cd "$TMP"

# 记录 pristine dts（-c 会改写 output dts）
PRISTINE=$(ls "$TMP"/output/*.dts 2>/dev/null | head -1)
if [ -n "$PRISTINE" ]; then
  cp -f "$PRISTINE" "$PRISTINE.pristine"
fi
restore_dts() {
  if [ -n "$PRISTINE" ] && [ -f "$PRISTINE.pristine" ]; then
    cp -f "$PRISTINE.pristine" "$PRISTINE"
  fi
}

P_OUT=$(MEMORY_EDIT_ITB_FILE=./boot.itb MEMORY_EDIT_CHPI_TYPE=cv84x6 ./memory_edit.sh -p 2>&1)
if ! echo "$P_OUT" | grep -q "max vpp size:"; then
  echo "P 模式失败，输出尾部：" && echo "$P_OUT" | tail -15
  exit 1
fi
MAX_VPP=$(echo "$P_OUT" | grep "Info: max vpp size:" | grep -oE "\[[0-9]+ MiB\]" | grep -oE "[0-9]+")
MAX_NPUVPP=$(echo "$P_OUT" | grep "Info: max npu+vpp size:" | grep -oE "\[[0-9]+ MiB\]" | grep -oE "[0-9]+")
echo "[-p 打印] max_vpp=$MAX_VPP MiB  max_npu+vpp=$MAX_NPUVPP MiB"

# A. vpp 单项：用打印的 max_vpp 提交
restore_dts
echo "== A: vpp=$MAX_VPP MiB (npu=1024 MiB) =="
A_OUT=$(MEMORY_EDIT_ITB_FILE=./boot.itb MEMORY_EDIT_CHPI_TYPE=cv84x6 ./memory_edit.sh -c -npu 1024 -vpu 0 -vpp "$MAX_VPP" 2>&1)
if echo "$A_OUT" | grep -q "Error: vpp size"; then A=FAIL; else A=PASS; fi

# B. 总量：npu=打印总量-4096, vpp=4096（vpp 远离单项上限，只测总量约束）
restore_dts
V_SUB=4096
N_TOT=$((MAX_NPUVPP - V_SUB))
echo "== B: npu=$N_TOT MiB vpp=$V_SUB MiB (npu+vpp = 打印总量) =="
B_OUT=$(MEMORY_EDIT_ITB_FILE=./boot.itb MEMORY_EDIT_CHPI_TYPE=cv84x6 ./memory_edit.sh -c -npu "$N_TOT" -vpu 0 -vpp "$V_SUB" 2>&1)
if echo "$B_OUT" | grep -q "Error:"; then B=FAIL; else B=PASS; fi

echo "RESULT: A=[$A] B=[$B]"
[ "$A" = PASS ] && [ "$B" = PASS ]