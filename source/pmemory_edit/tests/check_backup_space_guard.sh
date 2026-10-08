#!/bin/bash
# memory_edit 备份 /boot 的空间预检回归测试
#
# 背景：脚本末尾会把 /boot/$itb 备份成同分区 .memeditBak。CV84X2 EVB 的 /boot 只有
# 42MB，而 boot.itb 有 24.8MB，剩余空间往往放不下第二份；原来的 `sudo cp ... 2>/dev/null`
# 会静默截断备份、甚至把 /boot 撑到 100%（曾实测复现），且报错被吞掉。修复后改为
# 先查剩余空间：不足则打印警告并跳过备份，不阻塞内存修改流程。
#
# 断言（全部在 mount namespace 内用受控 tmpfs 顶替 /boot，不碰真实 /boot）：
#   A. 空间不足 -> 退出码 0（不阻塞）+ 打印警告 + 不产生 .memeditBak
#   B. 空间充足 -> 退出码 0 + 产生 .memeditBak 且与源逐字节一致（未被截断）
#
# 用法：
#   MEMORY_EDIT_KIT=<kit 目录> bash tests/check_backup_space_guard.sh
#
# kit 目录 = memory_edit 在目标机上解包后的工作目录，需含：
#   <kit>/multi.its  <kit>/boot.itb
# 需要 root（unshare -m + mount tmpfs）。真实 /boot 全程只读。
# 若环境不支持 unshare -m，测试会 SKIP 而非失败。
set -u

KIT="${MEMORY_EDIT_KIT:-}"
if [ -z "$KIT" ] || [ ! -f "$KIT/multi.its" ] || [ ! -f "$KIT/boot.itb" ]; then
  echo "ERROR: 需要 MEMORY_EDIT_KIT=<kit 目录>（含 multi.its + boot.itb）" >&2
  exit 2
fi
KIT=$(readlink -f "$KIT")
SCRIPT_DIR=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
SRC="${MEMORY_EDIT_SRC:-$(cd "$SCRIPT_DIR/.." && pwd)}"
if [ -f "$SRC/source/memory_edit/memory_edit.sh" ]; then
  SRC_SH="$SRC/source/memory_edit/memory_edit.sh"
elif [ -f "$SRC/memory_edit.sh" ]; then
  SRC_SH="$SRC/memory_edit.sh"
else
  echo "ERROR: 找不到 memory_edit.sh（$SRC），可用 MEMORY_EDIT_SRC 指定" >&2
  exit 2
fi

if [ "$(id -u)" != "0" ]; then
  echo "ERROR: 需要 root 运行（unshare -m + mount tmpfs）" >&2
  exit 2
fi
if ! unshare -m true 2>/dev/null; then
  echo "SKIP: 环境不支持 unshare -m，跳过（本测试需要 mount namespace）"
  exit 0
fi

ITB_SIZE=$(stat -c %s "$KIT/boot.itb")
echo "[素材] boot.itb = $ITB_SIZE bytes（每次用例需再放一份同尺寸副本）"

# 在 namespace 内跑一次 -c，/boot 用指定大小的 tmpfs 顶替。
# 参数：size 标签 -> 输出 "rc=..  bak=<无|尺寸>" 到 stdout，细节进 CASELOG
run_case() {
  local tsize="$1" label="$2"
  local caselog; caselog=$(mktemp)
  local wrk; wrk=$(mktemp -d)
  cp -a "$KIT"/. "$wrk"/ 2>/dev/null
  cp -f "$SRC_SH" "$wrk/" 2>/dev/null || cp -f "$SRC_SH" "$wrk/memory_edit.sh"

  unshare -m bash -c "
    mount -t tmpfs -o size=$tsize tmpfs /boot 2>/dev/null || exit 9
    cp '$KIT/boot.itb' /boot/boot.itb
    cp '$KIT/multi.its' /boot/multi.its
    cd '$wrk' || exit 9
    MEMORY_EDIT_ITB_FILE=./boot.itb MEMORY_EDIT_CHPI_TYPE=cv84x6 \
      ./memory_edit.sh -c -npu 2048 -vpu 0 -vpp 2048 > '$caselog' 2>&1
    rc=\$?
    echo \"rc=\$rc\"
    if [ -f /boot/boot.itb.memeditBak ]; then
      echo \"bak=\$(stat -c %s /boot/boot.itb.memeditBak)\"
      echo \"bak_md5=\$(md5sum /boot/boot.itb.memeditBak | cut -d' ' -f1)\"
    else
      echo 'bak=none'
    fi
  " > /tmp/.bsg_out.$$ 2>&1

  local rc bak bak_md5
  rc=$(grep -m1 '^rc=' /tmp/.bsg_out.$$ | cut -d= -f2)
  bak=$(grep -m1 '^bak=' /tmp/.bsg_out.$$ | cut -d= -f2)
  bak_md5=$(grep -m1 '^bak_md5=' /tmp/.bsg_out.$$ | cut -d= -f2)
  local src_md5; src_md5=$(md5sum "$KIT/boot.itb" | cut -d' ' -f1)
  echo "$label: rc=$rc bak=$bak src_md5=$src_md5 bak_md5=${bak_md5:-none}"
  echo "$label 警告行：" ; grep -E 'Warning|not enough space|backup' "$caselog" | tail -2
  rm -f /tmp/.bsg_out.$$
  rm -rf "$wrk"; rm -f "$caselog"

  LAST_RC="$rc"; LAST_BAK="$bak"; LAST_BAK_MD5="${bak_md5:-}"; LAST_SRC_MD5="$src_md5"
}

# A. 空间不足：tmpfs 略大于一份 itb，放不下第二份
NEED_MB=$(( ITB_SIZE / 1024 / 1024 + 4 ))
A_SIZE="$(( NEED_MB + 6 ))M"
echo
echo "== A 空间不足（/boot=$A_SIZE，仅够一份 itb）=="
run_case "$A_SIZE" "A"
A=PASS
[ "$LAST_RC" = "0" ]        || { echo "  A FAIL: 退出码 $LAST_RC != 0（不应阻塞内存修改）"; A=FAIL; }
[ "$LAST_BAK" = "none" ]    || { echo "  A FAIL: 竟然产生了备份（$LAST_BAK）"; A=FAIL; }

# B. 空间充足：tmpfs 能放下两份
B_SIZE="$(( NEED_MB * 2 + 20 ))M"
echo
echo "== B 空间充足（/boot=$B_SIZE）=="
run_case "$B_SIZE" "B"
B=PASS
[ "$LAST_RC" = "0" ]                          || { echo "  B FAIL: 退出码 $LAST_RC != 0"; B=FAIL; }
[ "$LAST_BAK" = "$ITB_SIZE" ]                 || { echo "  B FAIL: 备份尺寸 $LAST_BAK != $ITB_SIZE（被截断）"; B=FAIL; }
[ "$LAST_BAK_MD5" = "$LAST_SRC_MD5" ]         || { echo "  B FAIL: 备份 md5 与源不一致（内容被截断）"; B=FAIL; }

echo
echo "RESULT: A(空间不足:告警+跳过) = [$A]  B(空间充足:完整备份) = [$B]"
if [ "$A" = PASS ] && [ "$B" = PASS ]; then exit 0; fi
exit 1
