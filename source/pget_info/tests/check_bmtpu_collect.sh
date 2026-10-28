#!/bin/bash
# get_info.sh 的 /proc/bmtpu 采集回归测试（CV84X6）
#
# 背景：CV84X6 的 TPU 运行态（固件版本、核心忙闲、TSH 队列积压）只存在于 /proc/bmtpu，
# get_info 原先完全没有采集。新增采集时必须同时守住三条安全边界（真机 + libsophon
# 源码双证，2026-10-28 于 10.42.0.242 实测）：
#   1. 绝不读 bmdi_api_info —— CV84X6 上该 proc_show 走
#      bm1688_base_get_core_num() → otp_reg_read(0x2014)，而 84x6 的 BAR 不覆盖
#      0x27100000（dmesg: bm_get_bar_offset invalid address = 0x27100000），基址为 NULL，
#      ioread32 直接内核 Oops（Unable to handle kernel paging request at 0x2014）。
#      实测 cat /proc/bmtpu/bmdi_api_info 两次均触发 Oops。
#   2. 绝不写 shmpacket / txpsys / wakeup_control —— 写会改全局调试状态。
#   3. 输出格式仍是 KEY|VALUE|，字段解析失败时留空，不填 0 冒充真实读数。
#
# 用法：
#   bash source/pget_info/tests/check_bmtpu_collect.sh
# 无需 root、无需开发板：夹具为真机 /proc/bmtpu 输出的裁剪副本，内联在本文件中。
set -u

SCRIPT_DIR=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
SRC_SH="${GET_INFO_SRC:-$(cd "$SCRIPT_DIR/.." && pwd)/get_info.sh}"
if [ ! -f "$SRC_SH" ]; then
    echo "ERROR: 找不到 get_info.sh（$SRC_SH），可用 GET_INFO_SRC 指定" >&2
    exit 2
fi

PASS=0
FAIL=0
function ok()   { PASS=$((PASS + 1)); echo "  PASS  $1"; }
function bad()  { FAIL=$((FAIL + 1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && echo "        $2"; }

# [名称] [期望] [实际]
function expect_eq() {
    if [ "$2" = "$3" ]; then
        ok "$1 = $3"
    else
        bad "$1 期望 [$2] 实际 [$3]"
    fi
}

# ---------------------------------------------------------------- 加载被测函数
# get_info.sh 是「自顶向下直接执行」的单文件脚本，不能整体 source；
# 只把被测算法的函数体抽出来 source，避免执行主流程。
FUNCS=$(mktemp) || exit 2
trap 'rm -f "$FUNCS"' EXIT
for fn in parse_bmtpu_scaler_info parse_bmtpu_kernel_info collect_bmtpu_metrics \
          _bmtpu_now_ns _bmtpu_decode_core_state; do
    sed -n "/^function ${fn}()/,/^}\$/p" "$SRC_SH" >> "$FUNCS"
done
if [ ! -s "$FUNCS" ]; then
    echo "ERROR: 未能从 $SRC_SH 抽取被测函数（函数名/格式变了？）" >&2
    exit 2
fi
# shellcheck disable=SC1090
. "$FUNCS"

# ---------------------------------------------------------------- 夹具
WORK=$(mktemp -d) || exit 2
trap 'rm -f "$FUNCS"; rm -rf "$WORK"' EXIT

# 真机（10.42.0.242，libsophon 0.4.15 / 固件 fd3aca2）4 核 scaler_info 的裁剪副本
function write_scaler_all_same() {
    cat > "$1" <<'EOF'
Scaler Driver Statistics
================================
Total logs received: 0

Core 0:
  Status: Active
  Logs processed: 0
  Logs dropped: 0
  Last timestamp: 0 ms
  Firmware: FIRMWARE_VERSION=fd3aca2
BUILD_TIME=2026-08-14 00:23:55
  recvmsg_cnt: 222657
  procmsg_cnt: 222657
  running_flag: aa550304
  using_flag: 0
  debug_run_cnt: 62018657
  cur_api_id: 0x90000003
  cur_packet_addr: 0
  cur_group_idx: 0, cur_start_core_idx: 0
  cur_group_num: 1, cur_block_num: 1
  cur_api_result: 0
  log enable: 0
  Buffer usage: 0/2092928 (0%)

Core 1:
  Status: Active
  Logs processed: 0
  Logs dropped: 0
  Last timestamp: 0 ms
  Firmware: FIRMWARE_VERSION=fd3aca2
BUILD_TIME=2026-08-14 00:25:22
  recvmsg_cnt: 192488
  procmsg_cnt: 192488
  running_flag: aa550304
  using_flag: 0
  debug_run_cnt: 63332234
  cur_api_result: 0
  Buffer usage: 0/2092928 (0%)

Core 2:
  Status: Active
  Firmware: FIRMWARE_VERSION=fd3aca2
BUILD_TIME=2026-08-14 00:26:40
  recvmsg_cnt: 192488
  procmsg_cnt: 192488
  running_flag: aa550304
  using_flag: 0
  cur_api_result: 0

Core 3:
  Status: Active
  Firmware: FIRMWARE_VERSION=fd3aca2
BUILD_TIME=2026-08-14 00:27:43
  recvmsg_cnt: 192488
  procmsg_cnt: 192488
  running_flag: aa550304
  using_flag: 0
  cur_api_result: 0
EOF
}

# 真机 kernel_info 裁剪副本：8 个 HWQ，pushed == done（空闲），free_slots 全 16
function write_kernel_info_idle() {
    cat > "$1" <<'EOF'
=== BMDev Kernel Information ===
  dev_index: 0
Global max_depth: 16
Number of HWQs (NUM_HWQS): 8
  irq_tasklet state: 0
  irq_handle_cnt   : 222652
  irq_fallback_cnt : 27

--- HWQ Index: 0 ---
  hwq_idx: 0
  hwq_load_counters: 1
  free_slots: 16
  pushed_cnt: 19459
  total done: 19459
  filename: /data/irq_hwq0_4294894529.txt

--- HWQ Index: 1 ---
  hwq_idx: 1
  hwq_load_counters: 1
  free_slots: 16
  pushed_cnt: 103171
  total done: 103171
  filename: /data/irq_hwq1_4294894529.txt

--- HWQ Index: 2 ---
  hwq_idx: 2
  free_slots: 16
  pushed_cnt: 115
  total done: 115

--- HWQ Index: 3 ---
  hwq_idx: 3
  free_slots: 16
  pushed_cnt: 95621
  total done: 95621

--- HWQ Index: 4 ---
  hwq_idx: 4
  free_slots: 16
  pushed_cnt: 0
  total done: 0

--- HWQ Index: 5 ---
  hwq_idx: 5
  free_slots: 16
  pushed_cnt: 0
  total done: 0

--- HWQ Index: 6 ---
  hwq_idx: 6
  free_slots: 16
  pushed_cnt: 4174
  total done: 4174

--- HWQ Index: 7 ---
  hwq_idx: 7
  free_slots: 16
  pushed_cnt: 117
  total done: 117
EOF
}

echo "== 1. scaler_info 解析：4 核、同固件、全空闲 =="
D1="$WORK/d1"; mkdir -p "$D1"
write_scaler_all_same "$D1/scaler_info"
OUT=$(parse_bmtpu_scaler_info "$D1/scaler_info")
expect_eq "核心行数" "4" "$(printf '%s\n' "$OUT" | grep -c .)"
expect_eq "core0 整行" "0|fd3aca2|2026-08-14_00:23:55|aa550304|0|222657|222657" "$(printf '%s\n' "$OUT" | sed -n 1p)"
expect_eq "core3 整行" "3|fd3aca2|2026-08-14_00:27:43|aa550304|0|192488|192488" "$(printf '%s\n' "$OUT" | sed -n 4p)"

echo "== 2. collect：固件去重 + 每核状态 + 计数合计 =="
M=$(GET_INFO_BMTPU_DIR="$D1" GET_INFO_BMTPU_INTERVAL=0.01 collect_bmtpu_metrics)
get_m() { printf '%s\n' "$M" | awk -F'|' -v k="$1" '$1==k{print $2}'; }
expect_eq "TPU_FW_VERSION（4 核同版本去重）" "fd3aca2" "$(get_m TPU_FW_VERSION)"
expect_eq "TPU_FW_BUILD_TIME（4 核各不相同，逗号分隔、空格替 _）" \
    "2026-08-14_00:23:55,2026-08-14_00:25:22,2026-08-14_00:26:40,2026-08-14_00:27:43" \
    "$(get_m TPU_FW_BUILD_TIME)"
expect_eq "TPU_CORE_STATE（全空闲）" "IDLE,IDLE,IDLE,IDLE" "$(get_m TPU_CORE_STATE)"
expect_eq "TPU_TASK_RATE（夹具静态，无增量）" "0.00" "$(get_m 'TPU_TASK_RATE(tasks/s)')"

echo "== 3. running_flag 解码 =="
expect_eq "0xAA550304 → IDLE"       "IDLE"     "$(_bmtpu_decode_core_state aa550304 0)"
expect_eq "0xAA550002 + using 0xa5a5 → BUSY" "BUSY" "$(_bmtpu_decode_core_state aa550002 a5a5)"
expect_eq "0xAA55DEAD → EXITED"     "EXITED"   "$(_bmtpu_decode_core_state aa55dead 0)"
expect_eq "信号号 0x0b(SIGSEGV) → CRASH11" "CRASH11" "$(_bmtpu_decode_core_state aa0b0304 0)"
expect_eq "0 → UNKNOWN"             "UNKNOWN"  "$(_bmtpu_decode_core_state 0 0)"
expect_eq "空串 → UNKNOWN"          "UNKNOWN"  "$(_bmtpu_decode_core_state "" "")"

echo "== 4. 多固件版本不退化成单值 =="
D2="$WORK/d2"; mkdir -p "$D2"
write_scaler_all_same "$D2/scaler_info"
sed -i '0,/FIRMWARE_VERSION=fd3aca2/s//FIRMWARE_VERSION=abc1234/' "$D2/scaler_info"
M2=$(GET_INFO_BMTPU_DIR="$D2" GET_INFO_BMTPU_INTERVAL=0.01 collect_bmtpu_metrics)
expect_eq "两版固件并列" "abc1234,fd3aca2" \
    "$(printf '%s\n' "$M2" | awk -F'|' '$1=="TPU_FW_VERSION"{print $2}')"

echo "== 5. kernel_info 解析：积压深度 / 最小空闲槽 =="
D3="$WORK/d3"; mkdir -p "$D3"
write_kernel_info_idle "$D3/kernel_info"
write_scaler_all_same "$D3/scaler_info"
expect_eq "空闲夹具 depth|free_min" "0|16" "$(parse_bmtpu_kernel_info "$D3/kernel_info")"
M3=$(GET_INFO_BMTPU_DIR="$D3" GET_INFO_BMTPU_INTERVAL=0.01 collect_bmtpu_metrics)
expect_eq "TPU_QUEUE_DEPTH" "0" "$(printf '%s\n' "$M3" | awk -F'|' '$1=="TPU_QUEUE_DEPTH"{print $2}')"
expect_eq "TPU_HWQ_FREE_MIN" "16" "$(printf '%s\n' "$M3" | awk -F'|' '$1=="TPU_HWQ_FREE_MIN"{print $2}')"

# 积压夹具：hwq1 pushed 103171 / done 103000（积压 171）、hwq3 free_slots 0（硬背压）
cat > "$D3/kernel_info" <<'EOF'
--- HWQ Index: 0 ---
  free_slots: 16
  pushed_cnt: 100
  total done: 100

--- HWQ Index: 1 ---
  free_slots: 4
  pushed_cnt: 103171
  total done: 103000

--- HWQ Index: 3 ---
  free_slots: 0
  pushed_cnt: 9
  total done: 5
EOF
expect_eq "积压夹具 depth|free_min" "175|0" "$(parse_bmtpu_kernel_info "$D3/kernel_info")"

echo "== 6. 速率：窗口内 recvmsg 增量必须反映到 tasks/s =="
# 采样期间改写 scaler_info（每核 recvmsg +25，4 核共 +100），窗口 1.0s → 期望 100.00。
# 这是唯一能确定性地测速率公式的办法：真机上负载是突发且不可控的。
D5="$WORK/d5"; mkdir -p "$D5"
write_scaler_all_same "$D5/scaler_info"
(
    sleep 0.4
    sed -i 's/recvmsg_cnt: 222657/recvmsg_cnt: 222682/; s/recvmsg_cnt: 192488/recvmsg_cnt: 192513/' "$D5/scaler_info"
) &
BUMPER=$!
RATE=$(GET_INFO_BMTPU_DIR="$D5" GET_INFO_BMTPU_INTERVAL=1.0 collect_bmtpu_metrics \
        | awk -F'|' '$1=="TPU_TASK_RATE(tasks/s)"{print $2}')
wait "$BUMPER" 2>/dev/null
# 速率按实测经过时间算（比假定 sleep 精确到毫秒更准），故给 ±5% 容差
if awk -v r="${RATE}" 'BEGIN{ exit !(r >= 95.0 && r <= 105.0) }'; then
    ok "窗口内 +100 次 / 约 1s → $RATE tasks/s（落在 95~105）"
else
    bad "速率计算偏差过大：期望 95~105，实际 [$RATE]"
fi

# 计数器回退（固件重启归零）不得输出负数
D6="$WORK/d6"; mkdir -p "$D6"
write_scaler_all_same "$D6/scaler_info"
(
    sleep 0.4
    sed -i 's/recvmsg_cnt: 222657/recvmsg_cnt: 100/; s/recvmsg_cnt: 192488/recvmsg_cnt: 100/' "$D6/scaler_info"
) &
BUMPER=$!
RATE=$(GET_INFO_BMTPU_DIR="$D6" GET_INFO_BMTPU_INTERVAL=1.0 collect_bmtpu_metrics \
        | awk -F'|' '$1=="TPU_TASK_RATE(tasks/s)"{print $2}')
wait "$BUMPER" 2>/dev/null
expect_eq "计数器回退按 0 处理" "0.00" "$RATE"

echo "== 7. 退化输入不得崩、不得填 0 冒充读数 =="
D4="$WORK/d4"; mkdir -p "$D4"
: > "$D4/scaler_info"
expect_eq "空 scaler_info → 无输出" "" "$(parse_bmtpu_scaler_info "$D4/scaler_info")"
M4=$(GET_INFO_BMTPU_DIR="$D4" GET_INFO_BMTPU_INTERVAL=0.01 collect_bmtpu_metrics)
expect_eq "空 scaler_info → 不产出任何 key" "" "$M4"
expect_eq "空 kernel_info → 无输出" "" "$(parse_bmtpu_kernel_info "$D4/kernel_info")"
expect_eq "不存在的目录 → 无输出" "" "$(GET_INFO_BMTPU_DIR="$WORK/nope" collect_bmtpu_metrics)"

echo "== 8. 安全边界：只允许读白名单文件 =="
# 采集段里出现的每一个 /proc/bmtpu/<name> 都必须在白名单内；bmdi_api_info 会触发内核 Oops。
ALLOWED="scaler_info kernel_info bmdi_base_info"
SEEN=$(grep -oE '\$\{?_?[A-Za-z_]*[Dd][Ii][Rr][^}]*\}?/([a-z_]+)' "$SRC_SH" 2>/dev/null | sed 's|.*/||' | sort -u)
SEEN=$(printf '%s\n' "$SEEN" | grep -E '^(scaler_info|kernel_info|bmdi_base_info|bmdi_api_info|shmpacket|txpsys|wakeup_control|kernel_fifo)$' | sort -u)
BADF=""
for f in $SEEN; do
    case " $ALLOWED " in *" $f "*) ;; *) BADF="$BADF $f" ;; esac
done
if [ -z "$BADF" ]; then
    ok "被采集的 bmtpu 文件均在白名单内（$ALLOWED）"
else
    bad "采集了非白名单 bmtpu 文件:$BADF"
fi
if grep -qE '>\s*"?\$\{?[A-Za-z_]*[Dd][Ii][Rr][^}]*\}?/(shmpacket|txpsys|wakeup_control)' "$SRC_SH"; then
    bad "采集段对 shmpacket/txpsys/wakeup_control 做了写操作"
else
    ok "采集段未写 shmpacket/txpsys/wakeup_control"
fi

echo
echo "----------------------------------------"
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
