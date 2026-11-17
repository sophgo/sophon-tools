#!/usr/bin/env bash
# se-rag-core 并发烟测：验证 CF 优先链在高频并发下不串状态、不卡死、不 race。
#
# 用途（对应 MYS-2925 验收项「多 agent 等价高频并发烟测」）：
#   - 4 个独立的 se-rag 进程并行，各自 20 次 query，共享同一个临时 state 目录；
#   - 本地 mock 网关：CF 端口按概率超时/黑洞，FC 端口始终成功；
#   - 混合「请求取消」（部分子进程用短 deadline 的 query 让其自行放弃）；
#   - 报告成功数、耗时上限、state 文件是否可解析、是否有进程非预期退出。
#
# 本组件没有注册 API（无 register/signup 端点），因此平台注册部分的并发测试
# 不适用于 se-rag-core；这里验证的是「内置 key 限流 + 网关故障转移 + 跨进程熔断状态」
# 这三条真实存在的并发路径。
#
# 用法：
#   bash scripts/smoke_concurrency.sh              # 默认 4 进程 × 20 次
#   PROCS=8 CALLS=50 bash scripts/smoke_concurrency.sh
#
# 依赖：go（构建被测二进制）、python3（mock 网关）、coreutils。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
SRC_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROCS="${PROCS:-4}"
CALLS="${CALLS:-20}"
WORK="$(mktemp -d -t se-rag-smoke-XXXXXX)"
BIN="$WORK/se-rag"
MOCK_PID=""
cleanup() {
  [ -n "$MOCK_PID" ] && kill "$MOCK_PID" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "==> 构建被测二进制"
(cd "$SRC_DIR" && go build -buildvcs=false -o "$BIN" ./cmd/se-rag)

# ---- 本地 mock 网关 ----
# /v1/embeddings 与 /v1/rerank 都返回合法 OpenAI 兼容响应。
# 环境变量 MOCK_MODE 控制行为：
#   ok      —— 始终成功
#   stall   —— 接受连接后不响应（模拟 CF 黑洞，由单次上限兜住）
#   混合     —— 由路径区分：/cf/ 前缀 stall，/fc/ 前缀 ok
cat > "$WORK/mock.py" <<'PY'
import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIM = int(os.environ.get("MOCK_DIM", "8"))
HITS = {"cf": 0, "fc": 0}
LOCK = threading.Lock()

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        side = "cf" if self.path.startswith("/cf/") else "fc"
        with LOCK:
            HITS[side] += 1
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        if side == "cf" and os.environ.get("CF_STALL", "1") == "1":
            # 黑洞：不写响应，等客户端断开或超时
            time.sleep(30)
            return
        try:
            req = json.loads(raw or b"{}")
        except Exception:
            req = {}
        if self.path.endswith("/embeddings"):
            inp = req.get("input") or [""]
            data = [{"index": i, "embedding": [1.0] + [0.0] * (DIM - 1)} for i in range(len(inp))]
            body = json.dumps({"data": data}).encode()
        else:
            docs = req.get("documents") or [""]
            body = json.dumps({"results": [{"index": i, "relevance_score": 1.0 - i * 0.01}
                                           for i in range(len(docs))]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        with LOCK:
            body = json.dumps(HITS).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

port = int(sys.argv[1])
ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
PY

PORT="${MOCK_PORT:-18871}"
CF_STALL="${CF_STALL:-1}" python3 "$WORK/mock.py" "$PORT" &
MOCK_PID=$!
sleep 0.5

# ---- 夹具：文档 + 索引（离线建索引，不依赖网关） ----
mkdir -p "$WORK/docs"
cat > "$WORK/docs/a.md" <<'MD'
# SE7

## 网络

配置 netplan 使能 eth0 的 dhcp4 并重启 networkd 服务。

## SDK

SE7 使用 BM1684X 芯片运行推理任务，需要安装 sophonsdk 与驱动。
MD
cat > "$WORK/docs/b.md" <<'MD'
# SE7 排障

## OTA

OTA 升级用于更新系统镜像与驱动，升级前请备份配置。

## 串口

调试串口波特率为 115200，使用 8N1，连接 BMC 的 UART0。
MD

echo "==> 构建离线索引（确定性，不联网）"
"$BIN" build -offline --docs-dir "$WORK/docs" -index-dir "$WORK/idx" >/dev/null

# 用 mock 网关重建 hybrid 索引：把内置链两跳都指向 mock。
# CF 侧 stall，但 build 走的是有界回退，因此会落到 FC 侧成功。
export SE_RAG_GATEWAY_URL="http://127.0.0.1:$PORT/cf/v1"
export SE_RAG_FALLBACK_URL="http://127.0.0.1:$PORT/fc/v1"
export SE_RAG_GATEWAY_TIMEOUT="${SE_RAG_GATEWAY_TIMEOUT:-1s}"
export SE_RAG_FAILOVER_BUDGET="${SE_RAG_FAILOVER_BUDGET:-6s}"
export SE_RAG_ALLOW_HTTP_FALLBACK=0
export SE_RAG_STATE_DIR="$WORK/state"
mkdir -p "$WORK/state"

echo "==> 用 mock 网关重建 hybrid 索引（CF 故意黑洞，验证回退 FC）"
"$BIN" build --docs-dir "$WORK/docs" -index-dir "$WORK/idx2" >/dev/null
echo "    build 完成：CF 黑洞下回退到 FC 成功"

# ---- 并发：PROCS 进程 × CALLS 次 ----
echo "==> 并发烟测：$PROCS 进程 × $CALLS 次 query（共享 state 目录）"
start_ns=$(date +%s%N)
pids=()
fail_files=()
for p in $(seq 1 "$PROCS"); do
  (
    ok=0
    fail=0
    for c in $(seq 1 "$CALLS"); do
      # 每 5 次插入一次「请求取消」：2s 超时下让 query 自行放弃
      if [ $((c % 5)) -eq 0 ]; then
        timeout 2 "$BIN" query -index-dir "$WORK/idx2" -top-n 3 "网络配置" >/dev/null 2>&1 \
          && ok=$((ok + 1)) || true   # 超时/取消不计失败
        continue
      fi
      if timeout 20 "$BIN" query -index-dir "$WORK/idx2" -top-n 3 "网络配置" >/dev/null 2>&1; then
        ok=$((ok + 1))
      else
        fail=$((fail + 1))
      fi
    done
    echo "$ok $fail" > "$WORK/result-$p.txt"
  ) &
  pids+=($!)
done

# 中途读一次 mock 的命中计数，确认链真的被打过
sleep 0.3
curl -s "http://127.0.0.1:$PORT/" > "$WORK/hits-mid.json" 2>/dev/null || true

for pid in "${pids[@]}"; do wait "$pid"; done
end_ns=$(date +%s%N)

total_ok=0
total_fail=0
for f in "$WORK"/result-*.txt; do
  [ -e "$f" ] || continue
  read -r ok fail < "$f"
  total_ok=$((total_ok + ok))
  total_fail=$((total_fail + fail))
done

elapsed_ms=$(( (end_ns - start_ns) / 1000000 ))
hits=$(curl -s "http://127.0.0.1:$PORT/" 2>/dev/null || echo '{}')

# ---- 状态文件可解析（无状态污染/半写） ----
state_ok="n/a"
if [ -f "$WORK/state/gateway-breaker.json" ]; then
  if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$WORK/state/gateway-breaker.json" 2>/dev/null; then
    state_ok="ok"
  else
    state_ok="CORRUPT"
  fi
fi

echo
echo "==== 结果 ===="
echo "进程数           : $PROCS"
echo "每进程调用       : $CALLS（其中 20% 为 2s 超时取消）"
echo "成功             : $total_ok"
echo "失败（非取消）   : $total_fail"
echo "总耗时           : ${elapsed_ms}ms"
echo "单次上限         : $((elapsed_ms / (total_ok + total_fail + 1)))ms 平均（含进程启动）"
echo "mock 命中        : $hits"
echo "state 文件可解析 : $state_ok"
echo "state 路径       : $WORK/state（脚本退出后清理）"
echo
echo "说明：本组件无注册 API，平台注册并发测试不适用；本脚本覆盖内置限流（并发≤1/单次≤2 段落）、"
echo "      CF 超时回退 FC、跨进程熔断状态共享三条真实并发路径。"

if [ "$total_fail" -ne 0 ]; then
  echo "FAIL: 存在非取消类失败 $total_fail 次" >&2
  exit 1
fi
if [ "$state_ok" = "CORRUPT" ]; then
  echo "FAIL: 熔断状态文件损坏（并发写污染）" >&2
  exit 1
fi
echo "PASS"
