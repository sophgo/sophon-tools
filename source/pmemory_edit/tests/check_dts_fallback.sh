#!/bin/bash
# memory_edit -p 的 dts 自动检测回退回归测试（CV84X6）
#
# 背景：CV84X2/CV84X6 的 boot1 分区 offset160 不存放板名（bm1688 存放），按板名查找
# 恒失败；EVB 的 multi.its 含多个 fdt 配置节点（本机 8 个），v2.12.1 的「仅一个 fdt
# 节点才回退」分支不命中，-p 直接报 `Error: cannot find used dts file on bm1688`。
# 修复后改为逐级回退（u-boot.env 的 DTS_TYPE → multi.its 的 default → 单 fdt 节点），
# 每级都要求把配置名解析成真实的 fdt 节点，解析不出继续降级。
#
# 断言：
#   A. -p 必须成功，且打印 "Info: use dts file ..."
#   B. 解析出的 dts 名必须是 multi.its 里真实声明过的 fdt 数据文件（不是凭空拼的名字）
#   C. -p 为只读路径：跑完不动 /boot，且不产生新的 boot.itb
#
# 用法：
#   MEMORY_EDIT_KIT=<kit 目录> bash tests/check_dts_fallback.sh
#
# kit 目录 = memory_edit 在目标机上解包后的工作目录，需含：
#   <kit>/multi.its  <kit>/boot.itb
# 可用真机 /data/<memory_edit 解包目录>，或用 memory_edit.sh -d 生成的目录。
# 本测试只用 -p（只读），不会改设备内存布局。
set -u

KIT="${MEMORY_EDIT_KIT:-}"
if [ -z "$KIT" ] || [ ! -f "$KIT/multi.its" ] || [ ! -f "$KIT/boot.itb" ]; then
  echo "ERROR: 需要 MEMORY_EDIT_KIT=<kit 目录>（含 multi.its + boot.itb）" >&2
  exit 2
fi
KIT=$(readlink -f "$KIT")

# 待测脚本：默认取脚本上一级目录（仓库布局 = pmemory_edit/，含 source/memory_edit/；
# 产物布局 = kit 根，含 memory_edit.sh）。也可用 MEMORY_EDIT_SRC 显式指定。
SCRIPT_DIR=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
SRC="${MEMORY_EDIT_SRC:-$(cd "$SCRIPT_DIR/.." && pwd)}"
if [ -f "$SRC/source/memory_edit/memory_edit.sh" ]; then
  SRC_SH="$SRC/source/memory_edit/memory_edit.sh"
elif [ -f "$SRC/memory_edit.sh" ]; then
  SRC_SH="$SRC/memory_edit.sh"
else
  echo "ERROR: 找不到 memory_edit.sh（试过 $SRC/source/memory_edit/ 与 $SRC/），可用 MEMORY_EDIT_SRC 指定" >&2
  exit 2
fi

# 在临时副本里跑，绝不污染真实 kit；用本仓库源码覆盖 kit 自带版
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp -a "$KIT"/. "$TMP"/ 2>/dev/null
cp -f "$SRC_SH" "$TMP/"
cd "$TMP"

FDT_NODES=$(grep -c 'fdt = ' multi.its)
echo "[环境] multi.its fdt 配置节点数 = $FDT_NODES"

# 记录自身只读性基线：-p 不应改动 kit 内文件
BEFORE=$(ls -la boot.itb multi.its 2>/dev/null | md5sum)

P_OUT=$(MEMORY_EDIT_ITB_FILE=./boot.itb MEMORY_EDIT_CHPI_TYPE=cv84x6 ./memory_edit.sh -p 2>&1)
P_RC=$?

# A. -p 成功且给出 dts 文件
if [ $P_RC -ne 0 ] || ! echo "$P_OUT" | grep -q "Info: use dts file"; then
  echo "A=FAIL: -p 未解析出 dts（rc=$P_RC）"
  echo "$P_OUT" | tail -15
  A=FAIL
else
  A=PASS
fi

# B. 解析出的 dts 必须真实存在于 multi.its 声明的 fdt 数据文件里
RESOLVED=$(echo "$P_OUT" | grep -m1 "Info: use dts file" | sed 's#.*/##; s/\.dts$//')
if [ -z "$RESOLVED" ]; then
  echo "B=FAIL: 未从输出解析出 dts 名"
  B=FAIL
elif grep -q "/${RESOLVED}\.dtb" multi.its; then
  echo "[解析] dts=$RESOLVED（multi.its 中真实存在）"
  B=PASS
else
  echo "B=FAIL: 解析出的 $RESOLVED 不在 multi.its 声明的 dtb 列表中"
  grep 'dtb"' multi.its | grep 'data =' | awk -F'"' '{print "  候选: " $(NF-1)}'
  B=FAIL
fi

# C. 只读性：-p 不改动 boot.itb / multi.its
AFTER=$(ls -la boot.itb multi.its 2>/dev/null | md5sum)
if [ "$BEFORE" = "$AFTER" ]; then C=PASS; else echo "C=FAIL: -p 改动了 kit 内文件"; C=FAIL; fi

echo "RESULT: A=[$A] B=[$B] C=[$C]"
if [ "$A" = PASS ] && [ "$B" = PASS ] && [ "$C" = PASS ]; then
  exit 0
fi
exit 1
