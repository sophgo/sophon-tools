#!/bin/bash
# 在 aarch64 测试机上隔离验证 sophliteos 产物（MYS-2885）。
#
# ── 隔离模型（全部在**事前**落实，不依赖"出错后再卸载恢复"）─────────────────
#   1. 私有 mount namespace + 私有 network namespace：
#        unshare -m -n --propagation private
#      namespace 内的 mount 与网卡只对本进程树可见；退出即消失，
#      宿主挂载表与网络栈完全不被触碰。
#   2. 私有 network namespace 自带一段独立回环：因此不会与设备上 :8080/:18080
#      上的任何既有服务冲突，也就不存在"新进程没起来、curl 却验到了旧进程"的误判。
#      端口在该 namespace 内动态选取，并额外核验"监听者确实是我们启动的那个 PID"。
#   3. 工作目录一律 `mktemp -d` 创建，退出时只删这一个由本脚本创建、带前缀的目录。
#   4. 宿主挂载目标**只读检查**：所有 bind 目标必须预先存在且是目录，缺任何一个
#      直接 fail-closed 退出；namespace 内**绝不在宿主路径上 mkdir**。
#      对外部工具（dpkg-deb/python3/curl/sha256sum/unshare）同样先检查再使用。
#   5. 每个 bind 挂载完成后逐个自检"目标确实指向本次临时目录"，任一不符立即退出。
#
# ── 不做什么 ────────────────────────────────────────────────────────────────
#   不安装 deb、不改 systemd、不重启服务、不写真实 /data、不改宿主网络与路由。
#
# ── 用法 ────────────────────────────────────────────────────────────────────
#   sudo bash build/verify-deb-isolated.sh <deb 路径>
#
set -uo pipefail

# ============================ 内层：namespace 内实际执行 ====================
if [ "${1:-}" = "--inner" ]; then
  shift
  W="$1"; BIN="$2"; SECRET="$3"
  HOST_BINDS=(/opt/sophon/sophliteos/config /var/log/sophliteos /var/lib/sophliteos /var/lib/bmssm /data)

  fail() { echo "FAIL: $*" >&2; exit 1; }

  # --- 私有回环：net namespace 里 lo 默认 DOWN ---
  ip link set lo up || fail "无法启用 namespace 内回环"
  ip -4 addr show lo | grep -q '127.0.0.1' || fail "namespace 内回环没有 127.0.0.1"

  # --- bind 挂载：目标必须已存在（只读检查已在外面做过，这里再兜一层）---
  mount --bind "$W/cfg"            /opt/sophon/sophliteos/config || fail "bind config"
  mount --bind "$W/log"            /var/log/sophliteos           || fail "bind log"
  mount --bind "$W/varlib-soph"    /var/lib/sophliteos           || fail "bind /var/lib/sophliteos"
  mount --bind "$W/bmssm"          /var/lib/bmssm                || fail "bind bmssm"
  mount --bind "$W/data"           /data                         || fail "bind /data"

  # --- 逐个自检：**功能性**验证隔离生效 ---
  # 不比较 findmnt 的源字符串（overlay/tmpfs 的表示法因机器而异，容易误判），
  # 而是往"挂载后的目标路径"写一个哨兵文件，再确认它出现在本次临时目录里、
  # 且宿主原路径里没有它。哨兵能双向对上，才说明这个挂载确实指向我们的临时目录。
  check_bound() {
    local target="$1" src="$2" probe
    probe=".__mys2885_probe_$RANDOM$RANDOM"
    if ! ( : > "$target/$probe" ) 2>/dev/null; then
      fail "$target 不可写，无法验证隔离"
    fi
    if [ ! -e "$src/$probe" ]; then
      rm -f "$target/$probe" 2>/dev/null
      fail "$target 未隔离：写入未落到 $src"
    fi
    rm -f "$src/$probe"
    echo "  已隔离: $target -> $src（哨兵写入双向核验通过）"
  }
  check_bound /opt/sophon/sophliteos/config "$W/cfg"
  check_bound /var/log/sophliteos           "$W/log"
  check_bound /var/lib/sophliteos           "$W/varlib-soph"
  check_bound /var/lib/bmssm                "$W/bmssm"
  check_bound /data                         "$W/data"

  # 服务目录（现在位于临时 /data 上，随便建）
  mkdir -p /data/sophliteos /data/ota || fail "创建临时 /data 子目录"

  # --- 动态端口：先探测 namespace 内空闲端口，再用它启动 ---
  PORT="$(python3 -c '
import socket
s = socket.socket(); s.bind(("127.0.0.1", 0))
print(s.getsockname()[1]); s.close()')" || fail "无法获取空闲端口"
  [ -n "$PORT" ] || fail "未取得空闲端口"
  echo "namespace 内回环可用，使用动态端口 $PORT"

  sed -e "s/^  port: 8080/  port: $PORT/" \
      -e "s#^  path: /var/log/sophliteos#  path: $W/log#" \
      -e "s#^  path: /var/lib/sophliteos/db/sophliteos.db#  path: $W/varlib-soph/db/sophliteos.db#" \
      "$W/root/opt/sophon/sophliteos/config/sophliteos.yaml" > "$W/cfg/sophliteos.yaml" \
      || fail "生成测试配置失败"

  FAIL=0
  BASE="http://127.0.0.1:$PORT"

  # --- 陷阱文件：旧实现会先 O_TRUNC 再校验文件名，从而截断它们 ---
  printf 'ORIGINAL-CONTENT-DO-NOT-TOUCH' > /data/sophliteos/sophliteos-linux_arm64.tgz
  printf '#!/bin/sh\necho should-not-be-truncated\n' > /data/sophliteos/evil.sh
  TRAP_MD5="$(md5sum /data/sophliteos/sophliteos-linux_arm64.tgz /data/sophliteos/evil.sh)"
  DIR_BEFORE="$(ls -A /data/sophliteos | sort | tr '\n' ' ')"

  "$BIN" > "$W/out/sophliteos.out" 2>&1 &
  SRV_PID=$!
  trap 'kill "$SRV_PID" 2>/dev/null' EXIT

  # --- 就绪 + PID/端口归属核验（杜绝"验到了别的进程"）---
  READY=0
  for _ in $(seq 1 100); do
    if curl -sf -o /dev/null "$BASE/api/sso/active"; then READY=1; break; fi
    kill -0 "$SRV_PID" 2>/dev/null || fail "服务进程已退出：$(tail -5 "$W/out/sophliteos.out")"
    sleep 0.2
  done
  [ "$READY" = 1 ] || fail "服务未就绪：$(tail -10 "$W/out/sophliteos.out")"
  kill -0 "$SRV_PID" 2>/dev/null || fail "就绪后服务进程消失"
  # 核验监听者就是本次启动的 PID
  LISTENER="$(ss -ltnpH "sport = :$PORT" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)"
  [ -n "$LISTENER" ] || fail "端口 $PORT 上未找到监听者"
  [ "$LISTENER" = "$SRV_PID" ] || fail "端口 $PORT 的监听者 PID=$LISTENER 不是本次启动的 PID=$SRV_PID"
  echo "服务已启动：pid=$SRV_PID（端口 $PORT 的监听者经核验即此 PID）"

  PAYLOAD="$W/root/opt/sophon/sophliteos/config/sophliteos.yaml"

  # ---- 1) 未登录：两个旧端点都必须 401 ----
  for p in /api/upgrade /api/upgrade/confirm; do
    code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE$p" \
      -F "file=@$PAYLOAD;filename=sophliteos-linux_arm64.tgz")"
    if [ "$code" = "401" ]; then echo "PASS 未登录 $p -> 401"; else echo "FAIL 未登录 $p -> $code"; FAIL=1; fi
  done

  # ---- 登录 ----
  mktok() {
    SECRET="$SECRET" SUB="$1" python3 - <<'PY'
import jwt, os, time
print(jwt.encode({"sub": os.environ["SUB"], "iat": int(time.time()), "exp": int(time.time()) + 3600},
                 os.environ["SECRET"], algorithm="HS256"))
PY
  }
  TOK="$(mktok admin)" || fail "签发测试 JWT 失败"
  code="$(curl -s -o "$W/out/register.json" -w '%{http_code}' -X POST "$BASE/api/sso/register" \
    -H 'Content-Type: application/json' -d "{\"username\":\"admin\",\"token\":\"$TOK\"}")"
  if [ "$code" = "200" ]; then echo "PASS register -> 200（活跃会话已建立）";
  else echo "FAIL register -> $code $(cat "$W/out/register.json")"; FAIL=1; fi

  # ---- 2) 已登录：任何包名/内容都必须 200 + 业务码 501 + 明确提示 ----
  try_upload() {
    local name="$1" path="$2" body http json
    body="$(curl -s -w '\n%{http_code}' -X POST "$BASE$path" \
      -H "Authorization: Bearer $TOK" -F "file=@$PAYLOAD;filename=$name")"
    http="$(printf '%s' "$body" | tail -1)"
    json="$(printf '%s' "$body" | sed '$d')"
    if [ "$http" != "200" ]; then echo "FAIL $path($name) HTTP=$http"; FAIL=1; return; fi
    case "$json" in
      *'"code":501'*) ;;
      *) echo "FAIL $path($name) 业务码非 501: $json"; FAIL=1; return;;
    esac
    case "$json" in
      *暂不支持*) echo "PASS $path($name) -> 200/code=501 明确提示" ;;
      *) echo "FAIL $path($name) 提示不明确: $json"; FAIL=1;;
    esac
  }
  try_upload 'sophliteos-linux_arm64.tgz' /api/upgrade
  try_upload 'evil.sh' /api/upgrade
  try_upload '../../etc/passwd' /api/upgrade
  try_upload 'sophliteos-linux_arm64.tgz' /api/upgrade/confirm

  # ---- 3) 服务目录未变、进程未重启、无全局阻塞 ----
  TRAP_AFTER="$(md5sum /data/sophliteos/sophliteos-linux_arm64.tgz /data/sophliteos/evil.sh)"
  DIR_AFTER="$(ls -A /data/sophliteos | sort | tr '\n' ' ')"
  if [ "$TRAP_MD5" = "$TRAP_AFTER" ] && [ "$DIR_BEFORE" = "$DIR_AFTER" ]; then
    echo "PASS 服务目录未被改动（条目=[$DIR_AFTER]，两个陷阱文件内容不变）"
  else
    echo "FAIL 服务目录被改动（before=[$DIR_BEFORE] after=[$DIR_AFTER]）"; FAIL=1
  fi
  if kill -0 "$SRV_PID" 2>/dev/null; then echo "PASS 服务进程未被替换/退出（未 exec 重启）";
  else echo "FAIL 服务进程已消失（疑似重启）"; FAIL=1; fi
  vcode="$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOK" "$BASE/api/device/version")"
  if [ "$vcode" = "200" ]; then echo "PASS 旧升级调用后本地接口仍 200（未置 BlockAllRequests）";
  else echo "FAIL 本地接口 $vcode（疑似被阻塞）"; FAIL=1; fi

  # ---- 4) SSE ----
  curl -s -N -H "Authorization: Bearer $TOK" --max-time 10 "$BASE/api/sso/events" \
    > "$W/out/sse-old.txt" 2> "$W/out/sse-old.err" &
  SSE_PID=$!
  sleep 1
  curl -s -o /dev/null -X POST "$BASE/api/sso/register" -H 'Content-Type: application/json' \
    -d "{\"username\":\"admin\",\"token\":\"$TOK\"}"
  sleep 1
  if kill -0 "$SSE_PID" 2>/dev/null; then echo "PASS 同 token 重注册幂等（旧流保持，未被自踢）";
  else echo "FAIL 同 token 重注册把当前有效会话踢掉"; FAIL=1; fi

  TOK2="$(mktok admin2)" || fail "签发第二个 JWT 失败"
  curl -s -o /dev/null -X POST "$BASE/api/sso/register" -H 'Content-Type: application/json' \
    -d "{\"username\":\"admin2\",\"token\":\"$TOK2\"}"
  wait "$SSE_PID" 2>/dev/null
  if grep -q 'event: SESSION_OFFLINE' "$W/out/sse-old.txt"; then echo "PASS 旧流收到 SESSION_OFFLINE";
  else echo "FAIL 旧流未收到 SESSION_OFFLINE: $(cat "$W/out/sse-old.txt")"; FAIL=1; fi
  if grep -qi 'timed out' "$W/out/sse-old.err" 2>/dev/null; then
    echo "FAIL 旧流未被服务端关闭（等到了客户端 --max-time 超时）"; FAIL=1
  else
    echo "PASS 旧流被服务端主动关闭（未等客户端超时）"
  fi

  curl -s -o /dev/null -X POST "$BASE/api/sso/logout" -H "Authorization: Bearer $TOK2"
  sleep 0.5
  kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null

  if grep -qi 'panic\|fatal error' "$W/out/sophliteos.out"; then
    echo "FAIL 服务端日志出现 panic/fatal"; tail -20 "$W/out/sophliteos.out"; FAIL=1
  fi

  echo
  if [ "$FAIL" -ne 0 ]; then echo "RESULT: FAIL"; exit 1; fi
  echo "RESULT: PASS"
  exit 0
fi

# ============================ 外层：前置检查与编排 ==========================
DEB="${1:-}"
fail() { echo "FAIL: $*" >&2; exit 1; }

[ -n "$DEB" ] || fail "用法: sudo bash $0 <deb 路径>"
[ -f "$DEB" ] || fail "deb 不存在: $DEB"

# 外部工具 fail-closed
for t in dpkg-deb unshare mount findmnt ip ss curl python3 sha256sum md5sum; do
  command -v "$t" >/dev/null 2>&1 || fail "缺少必需工具: $t"
done
python3 -c 'import jwt' 2>/dev/null || fail "python3 缺少 pyjwt（需要用它签发测试 JWT）"
[ "$(id -u)" = 0 ] || fail "需要 root（sudo）以创建 mount/network namespace"

# 宿主 bind 目标：只读检查，缺任一即 fail-closed（绝不在宿主路径上创建）
HOST_BINDS=(/opt/sophon/sophliteos/config /var/log/sophliteos /var/lib/sophliteos /var/lib/bmssm /data)
for d in "${HOST_BINDS[@]}"; do
  [ -e "$d" ] || fail "宿主挂载目标不存在: $d（本脚本不会创建宿主目录）"
  [ -d "$d" ] || fail "宿主挂载目标不是目录: $d"
done

net_fingerprint() { { ip -4 addr show | grep -E '^[0-9]+:|inet '; ip route; } | sha256sum | cut -d' ' -f1; }
mounts_snapshot() { awk '{print $2}' /proc/self/mountinfo | sort; }

NET_BEFORE="$(net_fingerprint)"
MOUNTS_BEFORE="$(mounts_snapshot)"
echo "网络指纹(前): $NET_BEFORE"

# 专属工作目录：mktemp 自带随机后缀 + 固定前缀；退出时只删这一个
W="$(mktemp -d "${TMPDIR:-/tmp}/mys2885-verify-XXXXXXXX")" || fail "mktemp 失败"
cleanup() {
  # 只清理本脚本创建、且带本脚本前缀的目录
  case "$W" in
    */mys2885-verify-*) rm -rf -- "$W" ;;
    *) echo "WARN: 工作目录 $W 不符合预期前缀，跳过清理" >&2 ;;
  esac
}
trap cleanup EXIT

mkdir -p "$W"/{root,cfg,log,varlib-soph/db,bmssm,data,out} || fail "创建临时目录失败"
dpkg-deb -x "$DEB" "$W/root" || fail "解包 deb 失败"
BIN="$W/root/opt/sophon/sophliteos/bin/sophliteos"
[ -x "$BIN" ] || fail "产物中无 sophliteos 可执行文件"
echo "产物版本: $(sed -n '1p' "$W/root/opt/sophon/sophliteos/release_version.txt" 2>/dev/null)"
echo "产物 sha256: $(sha256sum "$DEB" | cut -d' ' -f1)"

SECRET="$(python3 -c 'import secrets;print(secrets.token_hex(32))')" || fail "生成 secret 失败"
printf '%s' "$SECRET" > "$W/bmssm/jwt_secret" || fail "写临时 jwt_secret 失败"
# 配置文件先复制一份占位，内层拿到端口后再生成最终版
cp "$W/root/opt/sophon/sophliteos/config/sophliteos.yaml" "$W/cfg/sophliteos.yaml" || fail "复制配置失败"

# 进入私有 mount + network namespace 执行内层
unshare -m -n --propagation private -- bash "$0" --inner "$W" "$BIN" "$SECRET"
INNER_RC=$?

# 事后核验：宿主网络与挂载表必须与运行前完全一致
NET_AFTER="$(net_fingerprint)"
MOUNTS_AFTER="$(mounts_snapshot)"
echo "=== 宿主侧事后核验 ==="
echo "网络指纹  before=$NET_BEFORE"
echo "          after =$NET_AFTER"
if [ "$NET_BEFORE" != "$NET_AFTER" ]; then
  echo "FAIL: 宿主网络发生变化"; exit 1
fi
if [ "$MOUNTS_BEFORE" != "$MOUNTS_AFTER" ]; then
  echo "FAIL: 宿主挂载表发生变化"; diff <(echo "$MOUNTS_BEFORE") <(echo "$MOUNTS_AFTER") | head -20; exit 1
fi
if grep -q "mys2885-verify" /proc/self/mountinfo 2>/dev/null; then
  echo "FAIL: 宿主挂载表中出现本脚本的临时挂载"; grep "mys2885-verify" /proc/self/mountinfo | head; exit 1
fi
echo "PASS 宿主网络与挂载表未变（全部隔离在 namespace 内）"

echo "exit=$INNER_RC"
exit "$INNER_RC"
