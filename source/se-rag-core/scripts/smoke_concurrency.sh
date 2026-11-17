#!/usr/bin/env bash
# se-rag-core 并发烟测：验证 CF 优先链在高频并发下不串状态、不卡死、不 race。
#
# 用途（对应 MYS-2925 验收项「多 agent 等价高频并发烟测」）：
#   - PROCS 个独立的 se-rag 进程并行，各自 CALLS 次 query，共享同一个临时 state 目录；
#   - 本地 mock 网关：CF 侧黑洞（超时后回退 FC），FC 侧始终成功；
#   - 混合「请求取消」：部分调用用 timeout 主动放弃；
#   - **断言实际结果**，不只是退出码。
#
# 与上一版的差别（验收退回要求）：旧版只看退出码，因此 BM25 降级、接口串了、
# 甚至 rerank 完全没被调用都能 PASS。本版：
#   1. 断言输出含 mode=hybrid 且**不含** fallback（降级即失败）；
#   2. 断言 mock 真实收到 /v1/rerank 且 documents 数 > 0（串接口/未调用即失败）；
#   3. 断言 mock 只收到预期的接口路径，其它路径一律 404（mock 不会再对错误接口返回 200）；
#   4. 断言 CF 与 FC 都被真实命中；
#   5. 准确区分 timeout(124) 与真实错误（其它非 0 退出码）；
#   6. 逐请求记录耗时，报告 max / p95，而不是「总耗时 ÷ 成功数」这种伪指标；
#   7. 隔离环境：清空所有 OPENAI_*/SE_RAG_* 业务变量，禁止继承宿主 key 而误打公网。
#
# 本组件没有注册 API（无 register/signup 端点），因此平台注册部分的并发测试
# 不适用于 se-rag-core；这里验证的是「内置 key 限流 + 网关故障转移 + 跨进程熔断状态」
# 这三条真实存在的并发路径。不声称覆盖注册。
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
CANCEL_EVERY="${CANCEL_EVERY:-5}"   # 每 N 次插入一次主动取消
WORK="$(mktemp -d -t se-rag-smoke-XXXXXX)"
BIN="$WORK/se-rag"
MOCK_PIDS=()
MOCK_PID=""
cleanup() {
  for pid in "${MOCK_PIDS[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  [ -n "$MOCK_PID" ] && kill "$MOCK_PID" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

# ---- 环境隔离：绝不继承宿主/CI 的真实 key 或配置 ----
unset OPENAI_BASE_URL OPENAI_API_KEY OPENAI_EMBEDDING_MODEL OPENAI_RERANKING_MODEL
unset SE_RAG_CONFIG SE_RAG_EMBED_KEY SE_RAG_RERANK_KEY SE_RAG_EMBED_BASE_URL SE_RAG_RERANK_BASE_URL
unset SE_RAG_EMBED_MODEL SE_RAG_RERANK_MODEL SE_RAG_EMBED_DIM SE_RAG_FAKE_EMBED
unset SE_RAG_GATEWAY_URL SE_RAG_FALLBACK_URL SE_RAG_GATEWAY_TIMEOUT SE_RAG_ALLOW_HTTP_FALLBACK
unset SE_RAG_DATA_DIR SE_RAG_STATE_TTL

echo "==> 构建被测二进制"
(cd "$SRC_DIR" && go build -buildvcs=false -o "$BIN" ./cmd/se-rag)

# ---- 本地 mock 网关 ----
# 两个实例共用一个脚本，用 **端口 + 主机名** 区分 CF / FC（真实部署是不同主机、同接口路径）。
# 只接受 /v1/embeddings 与 /v1/rerank；其它路径一律 404、空 body——这样「接口串了」
# 会立刻变成可见失败，而不是假 200。
# SIDE=cf 的实例延迟 CF_STALL_MS 后才返回（模拟慢 CF，配合单次上限表现为超时回退）；
# SIDE=fc 的实例立即成功。
cat > "$WORK/mock.py" <<'PY'
import json, os, socket, ssl, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIM = int(os.environ.get("MOCK_DIM", "8"))
STALL_FILE = os.environ.get("STALL_FILE", "")

def stall_ms():
    """每次请求实时读取 stall 毫秒数，便于脚本中途切换 CF 健康/卡住。"""
    if STALL_FILE:
        try:
            with open(STALL_FILE) as f:
                return int(f.read().strip() or 0)
        except Exception:
            pass
    return int(os.environ.get("CF_STALL_MS", "5000"))
SIDE = os.environ.get("SIDE", "fc")
LOCK = threading.Lock()
# 按「侧 + 接口」分别计数：能证明 rerank 真的被调用，而不是只打了 embeddings。
HITS = {}
BAD_PATHS = {}

ALLOWED = {"/v1/embeddings", "/v1/rerank"}

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        path = self.path
        if path not in ALLOWED:
            with LOCK:
                BAD_PATHS[path] = BAD_PATHS.get(path, 0) + 1
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        side = SIDE                        # cf | fc（由端口决定，不是路径）
        kind = path.rsplit("/", 1)[1]      # embeddings | rerank
        key = side + "/" + kind
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        with LOCK:
            HITS[key] = HITS.get(key, 0) + 1

        delay = stall_ms()
        if side == "cf" and delay > 0:
            # 慢响应：模拟 CF 卡住。客户端单次上限到点会放弃并转 FC。
            time.sleep(delay / 1000.0)

        try:
            req = json.loads(raw or b"{}")
        except Exception:
            req = {}

        # 路径与负载必须匹配：rerank 的负载带 query/documents，embeddings 带 input。
        # 若 rerank 的负载打到了 /embeddings（串接口），这里直接判为错误并返回 400，
        # 绝不能"对错误接口也返回 200 假数据"——那样客户端会当作成功继续跑。
        mismatch = None
        if kind == "embeddings" and ("documents" in req or "query" in req):
            mismatch = "rerank-payload-on-embeddings"
        elif kind == "rerank" and "input" in req and "documents" not in req:
            mismatch = "embeddings-payload-on-rerank"
        if mismatch:
            with LOCK:
                BAD_PATHS[mismatch] = BAD_PATHS.get(mismatch, 0) + 1
            body = json.dumps({"error": mismatch}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if kind == "embeddings":
            inp = req.get("input") or [""]
            vec = [1.0] + [0.0] * (DIM - 1)
            body = json.dumps({"data": [{"index": i, "embedding": vec} for i in range(len(inp))]}).encode()
        else:
            docs = req.get("documents") or [""]
            if not docs:
                # documents 为空说明调用方根本没传候选 —— 让它在客户端表现为空结果，
                # 而不是伪装成功（旧 mock 返回固定 index 0，掩盖了这个问题）。
                body = json.dumps({"results": []}).encode()
            else:
                # 反序返回：只有结果被真正采用，输出头条才会是原候选的最后一条。
                body = json.dumps({"results": [
                    {"index": i, "relevance_score": (i + 1) / len(docs)}
                    for i in range(len(docs) - 1, -1, -1)
                ]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        with LOCK:
            body = json.dumps({"hits": HITS, "bad_paths": BAD_PATHS}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

port = int(sys.argv[1])
certfile = os.environ.get("TLS_CERT", "")
keyfile = os.environ.get("TLS_KEY", "")
# 同时监听 IPv4/IPv6：两跳用不同主机名（127.0.0.1 vs localhost），
# 而 localhost 在部分系统上优先解析到 ::1。只绑 IPv4 会让 FC 侧直接连不上，
# 于是"串接口"缺陷被 failover 掩盖（CF 打错路径超时 → FC 连不上 → 全错，
# 反而看不出路径问题）。
class DualStack(ThreadingHTTPServer):
    address_family = socket.AF_INET6

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except Exception:
            pass
        super().server_bind()

def serve(addr):
    srv = DualStack(addr, H)
    if certfile and keyfile:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile, keyfile)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    srv.serve_forever()

try:
    serve(("::", port))
except OSError:
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
PY

# 自签证书：让 mock 走 HTTPS（与真实网关一致）。测试二进制通过 SSL_CERT_FILE
# 信任它，因此不需要 -k/insecure 之类的旁路。
CF_CERT="$WORK/cert.pem"
CF_KEY="$WORK/key.pem"
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$CF_KEY" -out "$CF_CERT" -days 2 \
  -subj "/CN=se-rag-smoke" -addext "subjectAltName=IP:127.0.0.1,DNS:localhost" 2>/dev/null

CF_PORT="${MOCK_CF_PORT:-18871}"
FC_PORT="${MOCK_FC_PORT:-18872}"
MOCK_PIDS=()
export STALL_FILE="$WORK/cf_stall_ms"
echo "${CF_STALL_MS:-5000}" > "$STALL_FILE"
SIDE=cf TLS_CERT="$CF_CERT" TLS_KEY="$CF_KEY" python3 "$WORK/mock.py" "$CF_PORT" 2>"$WORK/mock-cf.err" &
MOCK_PIDS+=($!)
SIDE=fc TLS_CERT="$CF_CERT" TLS_KEY="$CF_KEY" python3 "$WORK/mock.py" "$FC_PORT" 2>"$WORK/mock-fc.err" &
MOCK_PIDS+=($!)
MOCK_PID="${MOCK_PIDS[0]}"
sleep 0.7

export SE_RAG_STATE_DIR="$WORK/state"
mkdir -p "$SE_RAG_STATE_DIR"

# 内置链两跳都指向 mock；CF 侧慢 5s，单次上限设 800ms，因此每次都会先超时再回退 FC。
# 两跳用**不同主机名**（127.0.0.1 vs localhost）：真实部署是
# *.workers.dev 与 *.fcapp.run，host 不同。若两跳共用一个 host，粘滞身份会
# 撞在一起、触发歧义保护而不做重排，从而掩盖串接口缺陷。
export SE_RAG_GATEWAY_URL="https://127.0.0.1:$CF_PORT/v1"
export SE_RAG_FALLBACK_URL="https://localhost:$FC_PORT/v1"
# 让被测二进制信任测试自签证书（只影响本脚本启动的子进程）。
export SSL_CERT_FILE="$CF_CERT"
export SE_RAG_GATEWAY_TIMEOUT="${SE_RAG_GATEWAY_TIMEOUT:-800ms}"
export SE_RAG_FAILOVER_BUDGET="${SE_RAG_FAILOVER_BUDGET:-6s}"
export SE_RAG_ALLOW_HTTP_FALLBACK=0

# ---- 夹具 ----
mkdir -p "$WORK/docs"
cat > "$WORK/docs/a.md" <<'MD'
# SE7

## 网络

配置 netplan 使能 eth0 的 dhcp4 并重启 networkd 服务。
MD
cat > "$WORK/docs/b.md" <<'MD'
# SE7 排障

## OTA

OTA 升级用于更新系统镜像与驱动，升级前请备份配置。

## 串口

调试串口波特率为 115200，使用 8N1，连接 BMC 的 UART0。
MD

echo "==> 用 mock 网关建立 hybrid 索引（CF 慢，验证超时回退 FC）"
"$BIN" build --docs-dir "$WORK/docs" -index-dir "$WORK/idx" > "$WORK/build.log" 2>&1 || {
  echo "FAIL: build 失败"; cat "$WORK/build.log"; exit 1
}

# 基线：单次 query 必须 hybrid 且 rerank 真被调用。
echo "==> 基线校验（单次 query）"
BASE_OUT="$("$BIN" query -index-dir "$WORK/idx" -top-n 3 "网络配置" 2>"$WORK/base.err")"
if ! grep -q 'mode=hybrid' <<<"$BASE_OUT"; then
  echo "FAIL: 基线 query 未走 hybrid（输出如下）"; echo "$BASE_OUT"; exit 1
fi
if grep -q 'fallback:' <<<"$BASE_OUT"; then
  echo "FAIL: 基线 query 发生了降级"; echo "$BASE_OUT"; cat "$WORK/base.err"; exit 1
fi
merge_stats() { python3 - "$@" <<'PY2'
import json, sys
hits, bad = {}, {}
for raw in sys.argv[1:]:
    d = json.loads(raw or "{}")
    for k, v in d.get("hits", {}).items():
        hits[k] = hits.get(k, 0) + v
    for k, v in d.get("bad_paths", {}).items():
        bad[k] = bad.get(k, 0) + v
print(json.dumps({"hits": hits, "bad_paths": bad}))
PY2
}
BASE_STATS="$(merge_stats "$(curl -sk "https://127.0.0.1:$CF_PORT/")" "$(curl -sk "https://localhost:$FC_PORT/")")"
if ! python3 -c '
import json,sys
d=json.load(sys.stdin)
assert d["hits"].get("fc/rerank",0) > 0, "基线未命中 fc/rerank: %r" % d
' <<<"$BASE_STATS"; then
  echo "FAIL: 基线 query 没有真正调用 /rerank"; echo "$BASE_STATS"; exit 1
fi
if ! python3 -c '
import json,sys
d=json.load(sys.stdin)
assert not d["bad_paths"], "出现非预期接口路径: %r" % d["bad_paths"]
' <<<"$BASE_STATS"; then
  echo "FAIL: 出现了非预期的接口路径"; echo "$BASE_STATS"; exit 1
fi

# ---- 相位 A：CF 健康时的接口正确性 ----
# 这一相位必须单独跑：并发相位里 CF 始终卡住，第一次超时后 CF 就进了熔断冷却，
# rerank 阶段直接走 FC，**结构上绕开了"同网关 embeddings/rerank 粘滞串接口"**。
# 只有让 CF 健康、两跳都由 CF 服务，才能观察到 rerank 是否真打到 /rerank。
echo "==> 相位 A：CF 健康时校验接口不串"
echo 0 > "$STALL_FILE"
sleep 0.2
"$BIN" query -index-dir "$WORK/idx" -top-n 3 "网络配置" > "$WORK/healthy1.out" 2>"$WORK/healthy1.err"
"$BIN" query -index-dir "$WORK/idx" -top-n 3 "网络配置" > "$WORK/healthy2.out" 2>"$WORK/healthy2.err"
for f in "$WORK/healthy1.out" "$WORK/healthy2.out"; do
  grep -q 'mode=hybrid' "$f" || { echo "FAIL: CF 健康时 query 未走 hybrid"; cat "$f"; exit 1; }
  grep -q 'fallback:' "$f" && { echo "FAIL: CF 健康时发生降级"; cat "$f"; exit 1; }
  grep -qE '^\*[1-9][0-9]* results' "$f" || { echo "FAIL: CF 健康时结果为空"; cat "$f"; exit 1; }
done
HEALTHY_STATS="$(merge_stats "$(curl -sk "https://127.0.0.1:$CF_PORT/")" "$(curl -sk "https://localhost:$FC_PORT/")")"
python3 - "$HEALTHY_STATS" <<'PY2' || { echo "FAIL: CF 健康时接口串了（见上）"; exit 1; }
import json, sys
d = json.loads(sys.argv[1]); hits, bad = d.get("hits", {}), d.get("bad_paths", {})
problems = []
if bad:
    problems.append("非预期接口路径/负载: %r" % bad)
if hits.get("cf/rerank", 0) < 2:
    problems.append("CF 健康时 /rerank 命中不足（串接口会落到 /embeddings）: %r" % hits)
if hits.get("cf/embeddings", 0) == 0:
    problems.append("CF 健康时 /embeddings 未命中: %r" % hits)
for p in problems: print("FAIL:", p)
sys.exit(1 if problems else 0)
PY2
echo "    CF 健康相位通过：cf/embeddings 与 cf/rerank 均真实命中"

# ---- 相位 B：CF 卡住 → 回退 FC，并在并发下验证不串状态 ----
echo "${CF_STALL_MS:-5000}" > "$STALL_FILE"
echo "==> 并发烟测：$PROCS 进程 × $CALLS 次 query（共享 state 目录）"
START=$(date +%s%N)
pids=()
for p in $(seq 1 "$PROCS"); do
  (
    # 本子 shell 需要读取每条命令的退出码做分类，因此关闭 errexit
    # （否则 timeout 的 124/137 会在 rc=$? 之前就终止整个子 shell）。
    set +e
    ok=0; fail=0; cancel=0
    for c in $(seq 1 "$CALLS"); do
      t0=$(date +%s%N)
      if [ $((c % CANCEL_EVERY)) -eq 0 ]; then
        # 主动取消：300ms 后放弃（远小于一次完整回退所需时间）。
        timeout --signal=KILL 0.3 "$BIN" query -index-dir "$WORK/idx" -top-n 3 "网络配置" \
          > "$WORK/out-$p-$c.txt" 2> "$WORK/err-$p-$c.txt" 2>/dev/null
        rc=$?
        if [ "$rc" -eq 137 ] || [ "$rc" -eq 124 ]; then
          cancel=$((cancel + 1))
        elif [ "$rc" -ne 0 ]; then
          # 取消之外的错误必须算失败——旧版这里吞掉了所有错误。
          fail=$((fail + 1)); echo "rc=$rc" >> "$WORK/fail-$p.log"
        else
          ok=$((ok + 1))
        fi
      else
        "$BIN" query -index-dir "$WORK/idx" -top-n 3 "网络配置" \
          > "$WORK/out-$p-$c.txt" 2> "$WORK/err-$p-$c.txt"
        rc=$?
        if [ "$rc" -ne 0 ]; then
          fail=$((fail + 1)); echo "rc=$rc" >> "$WORK/fail-$p.log"
        elif ! grep -q 'mode=hybrid' "$WORK/out-$p-$c.txt"; then
          fail=$((fail + 1)); echo "not-hybrid" >> "$WORK/fail-$p.log"
        elif grep -q 'fallback:' "$WORK/out-$p-$c.txt"; then
          fail=$((fail + 1)); echo "fallback" >> "$WORK/fail-$p.log"
        elif ! grep -qE '^\*[1-9][0-9]* results' "$WORK/out-$p-$c.txt"; then
          # 结果数为 0 说明 rerank 拿到了空候选或接口串了——旧版只看退出码，
          # 这种情况会被误判为成功。
          fail=$((fail + 1)); echo "no-results" >> "$WORK/fail-$p.log"
        else
          ok=$((ok + 1))
        fi
      fi
      t1=$(date +%s%N)
      echo $(( (t1 - t0) / 1000000 )) >> "$WORK/lat-$p.txt"
    done
    echo "$ok $fail $cancel" > "$WORK/result-$p.txt"
  ) &
  pids+=($!)
done

for pid in "${pids[@]}"; do wait "$pid"; done
END=$(date +%s%N)

total_ok=0; total_fail=0; total_cancel=0
for f in "$WORK"/result-*.txt; do
  [ -e "$f" ] || continue
  read -r ok fail cancel < "$f"
  total_ok=$((total_ok + ok)); total_fail=$((total_fail + fail)); total_cancel=$((total_cancel + cancel))
done
ELAPSED_MS=$(( (END - START) / 1000000 ))

# 逐请求耗时：max / p95（真实指标，不是总耗时÷成功数）
LAT_STATS="$(cat "$WORK"/lat-*.txt 2>/dev/null | sort -n | awk '
  {v[NR]=$1}
  END {
    if (NR == 0) { print "n=0 max=0 p95=0"; exit }
    p95i = int(NR * 0.95); if (p95i < 1) p95i = 1; if (p95i > NR) p95i = NR
    printf "n=%d max=%d p95=%d\n", NR, v[NR], v[p95i]
  }')"

FINAL_STATS="$(merge_stats "$(curl -sk "https://127.0.0.1:$CF_PORT/")" "$(curl -sk "https://localhost:$FC_PORT/")")"

# 状态文件可解析（原子写 + rename 应保证不会读到半写内容）
STATE_OK="n/a"
if [ -f "$SE_RAG_STATE_DIR/gateway-breaker.json" ]; then
  if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$SE_RAG_STATE_DIR/gateway-breaker.json" 2>/dev/null; then
    STATE_OK="ok"
  else
    STATE_OK="CORRUPT"
  fi
fi

echo
echo "==== 结果 ===="
echo "进程数 / 每进程调用 : $PROCS / $CALLS（每 $CANCEL_EVERY 次插入一次 300ms 取消）"
echo "成功 / 失败 / 取消  : $total_ok / $total_fail / $total_cancel"
echo "并发墙钟            : ${ELAPSED_MS}ms"
echo "逐请求耗时          : $LAT_STATS   （含进程冷启动）"
echo "mock 命中           : $FINAL_STATS"
echo "state 文件可解析    : $STATE_OK"
echo
echo "断言：hybrid 且无 fallback、/rerank 真命中、无非法接口路径、CF 与 FC 均被请求。"

FAILED=0
[ "$total_fail" -eq 0 ] || { echo "FAIL: 非取消失败 $total_fail 次："; cat "$WORK"/fail-*.log 2>/dev/null | sort | uniq -c; FAILED=1; }
[ "$STATE_OK" != "CORRUPT" ] || { echo "FAIL: 熔断状态文件损坏（并发写污染）"; FAILED=1; }

python3 - "$FINAL_STATS" <<'PY' || FAILED=1
import json, sys
d = json.loads(sys.argv[1])
hits, bad = d.get("hits", {}), d.get("bad_paths", {})
problems = []
if bad:
    problems.append("非预期接口路径（说明接口串了）: %r" % bad)
if hits.get("fc/rerank", 0) == 0:
    problems.append("嘈杂并发下 /rerank 从未命中：%r" % hits)
if hits.get("fc/embeddings", 0) == 0:
    problems.append("/embeddings 从未命中：%r" % hits)
if hits.get("cf/embeddings", 0) == 0:
    problems.append("CF 从未被请求（CF 优先未生效）: %r" % hits)
for p in problems:
    print("FAIL:", p)
sys.exit(1 if problems else 0)
PY

if [ "$FAILED" -ne 0 ]; then
  echo "==== 失败样本 ===="
  head -20 "$WORK"/out-* 2>/dev/null | head -40
  exit 1
fi

echo "PASS"
echo
echo "说明：本组件无注册 API，平台注册并发测试不适用；覆盖内置限流（并发≤1/单次≤2 段落）、"
echo "      CF 超时回退 FC、跨进程熔断状态共享三条真实并发路径。"
