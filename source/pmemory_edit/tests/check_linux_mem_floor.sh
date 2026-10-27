#!/bin/bash
# memory_edit - Linux 内存下限护栏回归测试（CV84X6 64GB panic 实机反例）
#
# 背景：CV84X6 64GB 实机上，按 -p 报的 max npu+vpp 配 npu=54952 / vpp=8190，
# 工具判定 "check edit size ok" 并接受，但内核起来后高位 DDR 区被吃满：
#   Memory: 22640K/66048000K available
#   Out of memory and no killable processes...
#   Kernel panic - not syncing: System is deadlocked on memory
# 且该机 panic=0 不会自动重启，只能断电恢复。
#
# 修复后：-c 必须拒绝"给 Linux 剩余不足下限"的组合，-p 报的上限必须落在下限之内。
#
# 用法：
#   MEMORY_EDIT_KIT=<kit 目录> bash tests/check_linux_mem_floor.sh
#
# kit 目录 = memory_edit 在目标机上解包后的工作目录，需含：
#   <kit>/memory_edit.sh  <kit>/bintools/  <kit>/boot.itb  <kit>/multi.its
# 断言（无硬编码容量，全部由 -p 输出推导，32G/64G 通用）：
#   A. -p 报的 max npu+vpp 必须被 -c 接受（打印与校验一致）
#   B. 超出 -p 报的 max npu+vpp 1 MiB 必须被拒绝
#   C. 把 DDR 吃到只剩 0 给 Linux 的组合（npu=max_npu, vpp=max_vpp）必须被拒绝
set -u

KIT="${MEMORY_EDIT_KIT:-}"
if [ -z "$KIT" ] || [ ! -f "$KIT/boot.itb" ] || [ ! -f "$KIT/multi.its" ]; then
	echo "ERROR: 需要 MEMORY_EDIT_KIT=<kit 目录>（含 boot.itb + multi.its）" >&2
	exit 2
fi
KIT=$(readlink -f "$KIT")

# 在临时副本里跑，绝不污染真实 kit；用本仓库源码覆盖 kit 自带版
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp -a "$KIT"/. "$TMP"/
SRC=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
cp -f "$SRC/source/memory_edit/memory_edit.sh" "$TMP/"
cd "$TMP" || exit 1

# -c 会改写 output dts，每轮前恢复原始副本
PRISTINE=""
for f in "$TMP"/output/*.dts; do
	[ -e "$f" ] || continue
	cp -f "$f" "$f.pristine"
	PRISTINE="$f"
	break
done
restore_dts() {
	[ -n "$PRISTINE" ] && [ -f "$PRISTINE.pristine" ] && cp -f "$PRISTINE.pristine" "$PRISTINE"
	rm -f "$TMP"/output/*.dts.new 2>/dev/null
}

run_p() {
	MEMORY_EDIT_ITB_FILE=./boot.itb MEMORY_EDIT_CHPI_TYPE=cv84x6 ./memory_edit.sh -p 2>&1
}
run_c() {
	local npu="$1" vpp="$2"
	MEMORY_EDIT_ITB_FILE=./boot.itb MEMORY_EDIT_CHPI_TYPE=cv84x6 \
		./memory_edit.sh -c -npu "$npu" -vpu 0 -vpp "$vpp" 2>&1
}

P_OUT=$(run_p)
if ! echo "$P_OUT" | grep -q "max npu+vpp size:"; then
	echo "P 模式失败，输出尾部：" && echo "$P_OUT" | tail -15
	exit 1
fi
MAX_NPUVPP=$(echo "$P_OUT" | grep "Info: max npu+vpp size:" | grep -oE "\[[0-9]+ MiB\]" | grep -oE "[0-9]+")
MAX_NPU=$(echo "$P_OUT" | grep "Info: max npu size:" | grep -oE "\[[0-9]+ MiB\]" | grep -oE "[0-9]+")
MAX_VPP=$(echo "$P_OUT" | grep "Info: max vpp size:" | grep -oE "\[[0-9]+ MiB\]" | grep -oE "[0-9]+")
MIN_LINUX=$(echo "$P_OUT" | grep "Info: min linux memory:" | grep -oE "[0-9]+ MiB" | grep -oE "[0-9]+")
echo "[-p] max_npu+vpp=${MAX_NPUVPP}M max_npu=${MAX_NPU}M max_vpp=${MAX_VPP}M min_linux=${MIN_LINUX:-?}M"

restore_dts
echo "== A: npu=$((MAX_NPUVPP - 4096)) vpp=4096 (等于 -p 报的总量) =="
A_OUT=$(run_c "$((MAX_NPUVPP - 4096))" 4096)
if echo "$A_OUT" | grep -q "^Error"; then A=FAIL; else A=PASS; fi

restore_dts
echo "== B: npu=$((MAX_NPUVPP - 4096 + 1)) vpp=4096 (超总量 1 MiB) =="
B_OUT=$(run_c "$((MAX_NPUVPP - 4096 + 1))" 4096)
if echo "$B_OUT" | grep -q "^Error"; then B=PASS; else B=FAIL; fi

restore_dts
echo "== C: npu=$MAX_NPU vpp=$MAX_VPP (吃满 DDR，Linux 余 0 -> 必须拒绝) =="
C_OUT=$(run_c "$MAX_NPU" "$MAX_VPP")
# 任何 Error 都算拒绝；若由更早的总量校验拦下也算正确（护栏是兜底，不是唯一防线）
if echo "$C_OUT" | grep -q "^Error"; then C=PASS; else C=FAIL; fi

# D 专测"新增护栏本身"：选一个能过旧校验、但会把 Linux 饿死的组合。
# 旧校验只要求 npu+npu_size_add <= ddr_size（不扣 Linux 余量），
# 故 npu 取"新上限 + 512M"仍在旧校验范围内，必须由新护栏拦下。
restore_dts
D_NPU=$((MAX_NPU + 512))
echo "== D: npu=$D_NPU vpp=0 (过旧校验但饿死 Linux，专测新护栏) =="
D_OUT=$(run_c "$D_NPU" 0)
if echo "$D_OUT" | grep -qi "for Linux"; then D=PASS; else D=FAIL; fi

echo "RESULT: A=[$A] B=[$B] C=[$C] D=[$D]"
if [ "$C" = FAIL ] || [ "$D" = FAIL ]; then
	echo "  C 的输出尾部（应为拒绝）:"; echo "$C_OUT" | tail -6
	echo "  D 的输出尾部（应为 Linux 余量不足）:"; echo "$D_OUT" | tail -6
fi
[ "$A" = PASS ] && [ "$B" = PASS ] && [ "$C" = PASS ] && [ "$D" = PASS ]
