#!/bin/bash
# EC20(quectel-CM) 拨号自愈检查脚本（由 ec20-selfcheck.timer 周期触发）
#
# 背景与根因：
#   1) 开机时序竞态：77-ec20dongle.rules 在 ttyUSB 枚举瞬间就拉起 ec20.service，
#      模组数据面尚未就绪，quectel-CM 抢跑拨号/DHCP 失败后只进入 15s 轮询且进程
#      不退出、不再重拨；ec20.service 为 Restart=on-failure，进程存活导致 systemd
#      不会自动拉起。表现：开机无 usb0，或 usb0 存在但无 IPv4，需要多次手工
#      systemctl restart ec20（先出 usb0、再出 IP）才能恢复。
#   2) 运行中掉线：设备长期运行后 usb0 消失（quectel-CM 卡死 / 模组软复位等），
#      无人值守时不会自动恢复。
#
# 本脚本为幂等的单次检查（由 timer 每 90s 触发一次），只做一件事：
#   检查拨号网卡是否已有 IPv4，没有就 systemctl restart ec20 重新拨号。
# 通过「定时周期触发 + 冷却时间限流」兼顾两个场景：
#   - 开机时多轮重试，直到拿到 IP（对应场景 1 的"先出 usb0、再出 IP"）；
#   - 运行中网卡消失也能在下一轮重新拉起（对应场景 2）。
#
# 注意：
#   - 若当前没有 Quectel EC20 模组（不在 77-ec20dongle.rules 的 VID 列表里），
#     本脚本直接退出，不去动 ec20.service，避免在纯 NL668/FM650 等设备上误重启。
#   - 本脚本只负责"软件层拉起"，模组若硬件掉线（USB 消失/dmesg 出现 reset 风暴），
#     重启多少次都无效，需先排查硬件/供电/接触。

IFACE="${EC20_IFACE:-}"
# 两次 restart ec20 之间的最小间隔（秒）。
# 注意：本值小于 timer 周期（ec20-selfcheck.timer: OnUnitActiveSec=90s），故在
# timer 驱动的常规路径上，实际的重启间隔由 timer 周期决定（约 90s），本限流不会
# 额外收紧；它真正起作用的是「脚本被手工/临时调用」的场景，防止那时被高频重启。
COOLDOWN="${EC20_SELFCHECK_COOLDOWN:-30}"
STAMP_DIR="${EC20_SELFCHECK_STAMP_DIR:-/run/ec20-selfcheck}"
LOG="${EC20_SELFCHECK_LOG:-/tmp/ec20-selfcheck.log}"
STAMP="$STAMP_DIR/last_restart"
STATE="$STAMP_DIR/state"

mkdir -p "$STAMP_DIR"
log() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }
read_state() { cat "$STATE" 2>/dev/null; }

# 是否装有 Quectel EC20 模组（与 77-ec20dongle.rules 的 VID/PID 列表保持一致）
has_quectel() {
    lsusb | grep -qiE "2c7c:(0125|0121|0800|6005)|05c6:(9215|9090|9003)"
}

# 定位拨号网卡：优先 usb0/usb1(ECM)，其次 wwan0(QMI)，再 enx*（可预测命名）
detect_iface() {
    if [ -n "$IFACE" ]; then
        echo "$IFACE"; return 0
    fi
    local c
    for c in usb0 usb1 wwan0; do
        [ -e "/sys/class/net/$c" ] && { echo "$c"; return 0; }
    done
    c=$(ls /sys/class/net 2>/dev/null | grep '^enx' | head -n1)
    if [ -n "$c" ]; then
        echo "$c"; return 0
    fi
    echo "usb0"   # 兜底：默认按 usb0(ECM) 检查，即使接口暂未出现
    return 0
}

has_ipv4() {
    ip -4 addr show dev "$1" 2>/dev/null | grep -q "inet "
}

# 无 EC20 模组：本看门狗不参与。只在「模组出现→消失」这种状态翻转时记一条日志，
# 避免在从未装 EC20 的设备上每分钟刷屏。
if ! has_quectel; then
    if [ "$(read_state)" != "no-modem" ]; then
        log "no Quectel EC20 modem present, skip"
        echo no-modem > "$STATE"
    fi
    exit 0
fi

iface=$(detect_iface)

# 已拿到 IPv4：健康。只在状态翻转时记一条日志，避免每分钟刷屏。
if has_ipv4 "$iface"; then
    if [ "$(read_state)" != "ok" ]; then
        log "ok: $iface has IPv4"
        echo ok > "$STATE"
    fi
    rm -f "$STAMP"
    exit 0
fi

# 无 IPv4：首次进入异常才记录，之后由具体动作日志说明
if [ "$(read_state)" != "bad" ]; then
    log "warn: $iface has no IPv4"
    echo bad > "$STATE"
fi

# 冷却期内不重复重启
now=$(date +%s)
last=0
[ -f "$STAMP" ] && last=$(cat "$STAMP" 2>/dev/null)
if [ $((now - last)) -lt "$COOLDOWN" ]; then
    exit 0
fi

if [ -e "/sys/class/net/$iface" ]; then
    log "restart ec20.service ($iface exists but no IPv4)"
else
    log "restart ec20.service ($iface not present, module re-enumerating?)"
fi
date +%s > "$STAMP"
systemctl restart ec20.service >> "$LOG" 2>&1 || true

exit 0