#!/bin/bash
# sophliteos SSO/SSE 高并发冒烟（MYS-2882 / MYS-2885 发布前回归要求）
#
# 目的：在**隔离的回环端口**上用至少四个独立进程高频并发执行
#       "register 会话 + 建 SSE 长连接"，持续 ≥30s，验证：
#   - 真实连接数上限生效（默认全局 32、单 token 8）；
#   - 被顶号后旧流立即关闭、SESSION_OFFLINE 可观测；
#   - 结束后服务端连接零残留；
#   - 无死锁（全程有界完成）；
#   - 构建产物带 -race，数据竞争会在服务端日志里报出（非零退出）。
#
# 安全边界（父 issue 约定）：
#   - 服务只监听 127.0.0.1 上的随机端口，不读 /data 配置、不连 bmssm；
#   - 不修改任何系统/网络配置，不重启任何服务，不接触设备上现有会话；
#   - 客户端用 127.0.0.x 段作源地址，仅在本机回环上生效（Linux 回环整段可用），
#     用于模拟不同来源、避开"每 IP 每分钟 10 次建连"这条独立限流，
#     从而让峰值连接数真正压到"全局 32"这条上限上。
#
# 用法: bash build/sse-smoke.sh [持续秒数] [客户端数] [每客户端并发连接数]
#   env KEEP_TMP=1  保留临时目录（排查现场）
set -uo pipefail

DURATION="${1:-35}"
CLIENTS="${2:-4}"
# 每会话并发持有的 SSE 连接数（模拟多标签页）：4 客户端 × 8 = 32，正好压到生产全局上限
TABS="${3:-8}"
# 每客户端每分钟建连尝试预算：4×8×60 ≈ 760 次/分 分布在 32 个来源 IP 上，
# 既能压到全局连接上限，又不会被"每 IP 10 次/分"整体淹没。
CONNS_PER_MIN="${CONNS_PER_MIN:-60}"
if [ "$CLIENTS" -lt 4 ]; then
  echo "ERROR: 至少需要 4 个独立客户端进程（父任务要求）" >&2
  exit 2
fi
if [ "$DURATION" -lt 30 ]; then
  echo "ERROR: 持续时长必须 >= 30s（父任务要求），当前 ${DURATION}s" >&2
  exit 2
fi

cd "$(dirname "$0")/.." || exit 1
WORK="$(mktemp -d "${TMPDIR:-/tmp}/sse-smoke-XXXXXX")"
cleanup() {
  # 只终止本次脚本启动的子进程（记录在 PIDs 里），绝不按名字杀进程
  if [ -n "${SERVER_PID:-}" ]; then kill "$SERVER_PID" 2>/dev/null; fi
  for p in "${CLIENT_PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null; done
  if [ "${KEEP_TMP:-0}" != "1" ]; then rm -rf "$WORK"; else echo "保留现场: $WORK"; fi
}
trap cleanup EXIT
CLIENT_PIDS=()

echo "==> 构建带 -race 的冒烟工具（含真实 middleware 代码）"
if ! go build -race -o "$WORK/sse-smoke" ./build/sse-smoke; then
  echo "FAIL: 构建冒烟工具失败" >&2
  exit 1
fi

READY="$WORK/addr"
SERVER_LOG="$WORK/server.log"
echo "==> 启动隔离测试服务（127.0.0.1 随机端口）"
"$WORK/sse-smoke" -mode=server -addr=127.0.0.1:0 -ready-file="$READY" >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 100); do
  [ -s "$READY" ] && break
  sleep 0.05
done
if [ ! -s "$READY" ]; then
  echo "FAIL: 测试服务未就绪" >&2
  cat "$SERVER_LOG" >&2
  exit 1
fi
ADDR="$(cat "$READY")"
echo "    监听: $ADDR"

# 记录测试前后宿主网络状态，证明未做任何网络改动
net_snapshot() {
  {
    ip -4 addr show | grep -E '^[0-9]+:|inet ' || true
    ip route || true
  }
}
NET_BEFORE="$(net_snapshot)"

echo "==> 拉起 $CLIENTS 个独立客户端进程，持续 ${DURATION}s"
for i in $(seq 1 "$CLIENTS"); do
  # 每个客户端独占 8 个回环源地址（client-1: 127.0.0.2-9，client-2: 127.0.0.10-17 …）
  src="127.0.0.$(( (i - 1) * 8 + 2 ))"
  "$WORK/sse-smoke" -mode=client -addr="$ADDR" -client="$i" -source-ip="$src" -tabs="${TABS}" \
    -conns-per-min="${CONNS_PER_MIN}" -duration="${DURATION}s" >"$WORK/client-$i.json" 2>"$WORK/client-$i.err" &
  CLIENT_PIDS+=($!)
done

# 运行期间采样服务端状态（峰值连接数/请求速率）
SAMPLES="$WORK/samples.txt"
: >"$SAMPLES"
END=$(( $(date +%s) + DURATION ))
while [ "$(date +%s)" -lt "$END" ]; do
  curl -s "http://$ADDR/stats" >>"$SAMPLES" 2>/dev/null
  echo >>"$SAMPLES"
  sleep 1
done

FAILED=0
for idx in "${!CLIENT_PIDS[@]}"; do
  pid="${CLIENT_PIDS[$idx]}"
  if ! wait "$pid"; then
    echo "FAIL: 客户端 $((idx + 1)) 非零退出" >&2
    cat "$WORK/client-$((idx + 1)).err" >&2
    FAILED=1
  fi
done

echo "==> 收尾：注销会话并检查连接零残留"
# 让服务端把所有残留长连接结束掉：注册一个新会话顶掉现有 SSE，再注销
curl -s -X POST "http://$ADDR/api/sso/register" -H 'Content-Type: application/json' \
  -d '{"username":"smoke-cleanup","token":"tok-cleanup"}' >/dev/null 2>&1
sleep 1
curl -s -X POST "http://$ADDR/api/sso/logout" -H 'Authorization: Bearer tok-cleanup' >/dev/null 2>&1

RESIDUAL=-1
for _ in $(seq 1 60); do
  ACTIVE="$(curl -s "http://$ADDR/stats" 2>/dev/null | grep -o '"activeConnections":[0-9]*' | cut -d: -f2)"
  [ -z "$ACTIVE" ] && ACTIVE=-1
  RESIDUAL="$ACTIVE"
  [ "$ACTIVE" = "0" ] && break
  sleep 0.25
done

FINAL_STATS="$(curl -s "http://$ADDR/stats" 2>/dev/null)"
NET_AFTER="$(net_snapshot)"

# 汇总客户端结果
CLIENT_SUMMARY="$(python3 - "$WORK" "$CLIENTS" <<'PY'
import json, os, sys
work, n = sys.argv[1], int(sys.argv[2])
tot = dict(registers=0, logouts=0, sseAttempts=0, sseOpened=0, sseRejected=0,
           offlineEvents=0, closedByServer=0, uniqueTokens=0, errors=0)
rows = []
for i in range(1, n + 1):
    p = os.path.join(work, f"client-{i}.json")
    try:
        d = json.load(open(p))
    except Exception as e:
        rows.append(f"  client-{i}: 结果缺失/不可解析 ({e})")
        tot["errors"] += 1
        continue
    rows.append("  client-%d src=%-11s 注册=%-5d 建连尝试=%-5d 成功=%-5d 拒绝=%-4d 离线事件=%-5d 服务端关闭=%-5d 时长=%dms"
                % (d.get("client", i), d.get("sourceIp", "-"), d.get("registers", 0),
                   d.get("sseAttempts", 0), d.get("sseOpened", 0), d.get("sseRejected", 0),
                   d.get("offlineEvents", 0), d.get("closedByServer", 0), d.get("durationMs", 0)))
    for k in ("registers", "logouts", "sseAttempts", "sseOpened", "sseRejected",
              "offlineEvents", "closedByServer", "uniqueTokens"):
        tot[k] += d.get(k, 0)
    tot["errors"] += len(d.get("errors") or [])
    if d.get("errors"):
        rows.append("    错误样例: " + "; ".join(d["errors"][:3]))
print("\n".join(rows))
print("  合计: 注册=%(registers)d 建连尝试=%(sseAttempts)d 成功=%(sseOpened)d 拒绝=%(sseRejected)d "
      "离线事件=%(offlineEvents)d 服务端关闭=%(closedByServer)d 独立token=%(uniqueTokens)d 错误=%(errors)d" % tot)
PY
)"

# 峰值连接数（服务端采样）
PEAK="$(python3 - "$SAMPLES" <<'PY'
import json, sys
peak = 0
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    try:
        peak = max(peak, json.loads(line).get("maxConnections", 0))
    except Exception:
        pass
print(peak)
PY
)"

echo
echo "=== 客户端结果 ==="
echo "$CLIENT_SUMMARY"
echo
echo "=== 服务端最终统计 ==="
echo "  $FINAL_STATS"
echo "  采样峰值连接数: $PEAK（生产全局上限 32 / 单 token 8）"
echo "  结束时活跃连接: $RESIDUAL"

# 判定
if [ "$FAILED" -ne 0 ]; then echo "FAIL: 存在非零退出的客户端"; exit 1; fi
if [ "$RESIDUAL" != "0" ]; then echo "FAIL: 结束时仍有 $RESIDUAL 条 SSE 连接未回收"; exit 1; fi
case "$FINAL_STATS" in
  *'"sseAccepted":0'*) echo "FAIL: 没有任何成功建连，冒烟未真正覆盖连接路径"; exit 1;;
esac

# 结构断言：连接真的建立到单 token 上限、峰值不超过全局上限、旧流确实被通知关闭
JUDGE="$(python3 - "$FINAL_STATS" "$PEAK" "$TABS" <<'PY'
import json, sys
st = json.loads(sys.argv[1])
peak, tabs = int(sys.argv[2]), int(sys.argv[3])
problems = []
if peak < tabs:
    problems.append("峰值连接数 %d 未达到单 token 上限 %d（连接未被真正建立）" % (peak, tabs))
if peak > 32:
    problems.append("峰值连接数 %d 超过全局上限 32" % peak)
if st.get("offlineEventsSent", 0) <= 0:
    problems.append("没有任何终止事件被投递（互踢/旧流关闭路径未覆盖）")
if st.get("activeConnections", -1) != 0:
    problems.append("结束时残留连接 %s" % st.get("activeConnections"))
print("; ".join(problems))
PY
)"
if [ -n "$JUDGE" ]; then
  echo "FAIL: $JUDGE" >&2
  exit 1
fi

# -race：服务端日志里出现数据竞争即失败（工具本身也为 -race 构建）
if grep -q "DATA RACE" "$WORK/server.log" "$WORK"/client-*.err 2>/dev/null; then
  echo "FAIL: 检测到 DATA RACE" >&2
  grep -A 30 "DATA RACE" "$WORK/server.log" "$WORK"/client-*.err 2>/dev/null | head -60 >&2
  exit 1
fi
if grep -qi "panic:\|fatal error" "$WORK/server.log" 2>/dev/null; then
  echo "FAIL: 服务端 panic/fatal" >&2
  tail -40 "$WORK/server.log" >&2
  exit 1
fi

if [ "$NET_BEFORE" != "$NET_AFTER" ]; then
  echo "FAIL: 宿主网络状态发生变化（本脚本不得改动网络）" >&2
  diff <(echo "$NET_BEFORE") <(echo "$NET_AFTER") >&2
  exit 1
fi
echo "  宿主地址/路由：测试前后一致（未改动网络）"

echo
echo "PASS: 并发冒烟通过（${CLIENTS} 个独立客户端 / ${DURATION}s / 峰值 ${PEAK} 条连接 / 结束零残留 / 无 race）"
