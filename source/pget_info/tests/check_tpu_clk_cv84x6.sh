#!/bin/bash
# get_info.sh 的 CV84X6 TPU 频率采集回归测试
#
# 背景：CV84X6 上 TPU 频率有两个 debugfs/sysfs 来源，它们在真机上**不一致**且**单位不同**：
#   * /sys/devices/platform/cv84x2-dvfs/tpu_freq_mhz  单位 MHz，DVFS 驱动上报的当前
#     运行频率——唯一"就是频率"的来源。
#   * /sys/kernel/debug/clk/clk_tpu_ip/clk_rate       单位 Hz，报的是 TPU 时钟域的
#     分频前基准，**只有真实运行频率的一半**。
#
# 缺陷形态：早先版本直接读 debugfs 并当作 Hz 输出，于是 TPU_CLK 恒为真实值的一半
# （真机对照：debugfs 1000000000 ↔ sysfs 2000 MHz，差整整 2 倍）。
#
# 本测试守住三条不变量：
#   1. sysfs 可读时，输出 = sysfs 的 MHz × 1e6，且**不受 debugfs 影响**；
#   2. sysfs 缺失/非法时回退 debugfs 并 ×2 校正，绝不输出未校正的一半值；
#   3. 两个来源都取不到时输出空串（不填 0 冒充真实读数）。
#
# 用法：
#   bash source/pget_info/tests/check_tpu_clk_cv84x6.sh
# 无需 root、无需开发板：通过 SYSFS_ROOT 前缀把 sysfs/debugfs 路径重定向到夹具目录。
set -u

SCRIPT_DIR=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
SRC_SH="${GET_INFO_SRC:-$(cd "$SCRIPT_DIR/.." && pwd)/get_info.sh}"
if [ ! -f "$SRC_SH" ]; then
    echo "ERROR: 找不到 get_info.sh（$SRC_SH），可用 GET_INFO_SRC 指定" >&2
    exit 2
fi

PASS=0
FAIL=0
function ok()  { PASS=$((PASS + 1)); echo "  PASS  $1"; }
function bad() { FAIL=$((FAIL + 1)); echo "  FAIL  $1"; [ -n "${2:-}" ] && echo "        $2"; }

# [名称] [期望] [实际]
function expect_eq() {
    if [ "$2" = "$3" ]; then
        ok "$1 = $3"
    else
        bad "$1 期望 [$2] 实际 [$3]"
    fi
}

# ---------------------------------------------------------------- 加载被测函数
# get_info.sh 自顶向下执行，不能整体 source；只抽被测函数。
FUNCS=$(mktemp) || exit 2
trap 'rm -f "$FUNCS"' EXIT
sed -n "/^function get_tpu_clk_cv84x6()/,/^}\$/p" "$SRC_SH" >> "$FUNCS"
if [ ! -s "$FUNCS" ]; then
    echo "ERROR: 未能从 $SRC_SH 抽取 get_tpu_clk_cv84x6（函数名/格式变了？）" >&2
    exit 2
fi

WORK=$(mktemp -d) || exit 2
trap 'rm -f "$FUNCS"; rm -rf "$WORK"' EXIT

# 把被测函数里的绝对路径重定向到夹具目录，其余逻辑原样保留。
# 这样测的是仓库里的真实实现，而不是测试里另抄一份的副本。
SANDBOX="$WORK/funcs.sh"
sed -e "s#/sys/devices/platform/cv84x2-dvfs/tpu_freq_mhz#${WORK}/sysfs_tpu_freq_mhz#" \
    -e "s#/sys/kernel/debug/clk/clk_tpu_ip/clk_rate#${WORK}/debugfs_clk_tpu_ip#" \
    "$FUNCS" > "$SANDBOX"
if ! grep -q "${WORK}/sysfs_tpu_freq_mhz" "$SANDBOX"; then
    echo "ERROR: 路径重定向失败——get_info.sh 里的 sysfs 路径可能已变更，请同步本测试" >&2
    exit 2
fi
# shellcheck disable=SC1090
. "$SANDBOX"

SYSFS="${WORK}/sysfs_tpu_freq_mhz"
DEBUGFS="${WORK}/debugfs_clk_tpu_ip"

function reset_fixtures() { rm -f "$SYSFS" "$DEBUGFS"; }

echo "--- sysfs 可读（正常路径） ---"
reset_fixtures
printf '2000' > "$SYSFS"
printf '1000000000\n' > "$DEBUGFS"
# 关键回归点：sysfs=2000MHz 时输出必须是 2e9，绝不能是 debugfs 的 1e9（一半）
expect_eq "sysfs 2000MHz 优先于 debugfs 1e9Hz" "2000000000" "$(get_tpu_clk_cv84x6)"

reset_fixtures
printf '1500\n' > "$SYSFS"
expect_eq "sysfs 1500MHz（DVFS 降频）" "1500000000" "$(get_tpu_clk_cv84x6)"

reset_fixtures
printf ' 2000 \n' > "$SYSFS"
expect_eq "sysfs 带空白也能解析" "2000000000" "$(get_tpu_clk_cv84x6)"

echo "--- sysfs 不可用（回退 debugfs，必须 ×2 校正） ---"
reset_fixtures
printf '1000000000\n' > "$DEBUGFS"
expect_eq "缺 sysfs，debugfs 1e9Hz → ×2" "2000000000" "$(get_tpu_clk_cv84x6)"

reset_fixtures
printf 'abc\n' > "$SYSFS"
printf '1000000000\n' > "$DEBUGFS"
expect_eq "sysfs 非数字 → 回退并 ×2" "2000000000" "$(get_tpu_clk_cv84x6)"

echo "--- 两个来源都取不到（不得填 0） ---"
reset_fixtures
expect_eq "sysfs 与 debugfs 均缺失 → 空串" "" "$(get_tpu_clk_cv84x6)"

reset_fixtures
printf '1000000000\n' > "$DEBUGFS"
printf 'x' > "$SYSFS"
# debugfs 合法、sysfs 非法 → 仍应得到校正值
expect_eq "sysfs 非法 + debugfs 合法" "2000000000" "$(get_tpu_clk_cv84x6)"

echo "--- 静态约束：不得再无条件信任 debugfs ---"
# 守住缺陷本身：cv84x6 分支里不应再出现「直接读 clk_tpu_ip 并赋给 TPU_CLK」
if grep -qE 'TPU_CLK=\$\(cat[^)]*clk_tpu_ip' "$SRC_SH"; then
    bad "仍有把 debugfs clk_tpu_ip 直接当 TPU_CLK 的代码（会是真实值的一半）"
else
    ok "未无条件信任 debugfs clk_tpu_ip"
fi
if grep -q "tpu_freq_mhz" "$SRC_SH"; then
    ok "已接入 sysfs tpu_freq_mhz"
else
    bad "未接入 sysfs tpu_freq_mhz"
fi

echo
echo "----------------------------------------"
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
