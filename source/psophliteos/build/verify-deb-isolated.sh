#!/bin/bash
# 在 10157 测试机（aarch64）上隔离验证 sophliteos 产物。
#
# ⚠️ 安全前提：所有 bind mount 必须在 **私有 mount namespace** 内完成。
# 脚本用一个外层 `unshare -m` 包住整段业务：命名空间内的 mount 只对本次运行的
# 子进程树可见，退出即消失，绝不改写设备的真实挂载表/目录内容。
# 脚本最后会自检：命名空间内看到的 /data 必须是本次临时目录的 bind，且外层宿主
# 上不得出现任何 mys-sophliteos 相关挂载（出现即报错退出）。
#
# 隔离与安全边界：
#   - 只监听 127.0.0.1:18080，不占用设备上的 8080；
#   - /opt/sophon/sophliteos/config、/var/log/sophliteos、/var/lib/sophliteos/db、
#     /var/lib/bmssm、/data 在命名空间内替换为临时目录；
#   - 不安装 deb、不改 systemd、不重启任何服务、不写真实 /data。
#
# 验证内容（对应 MYS-2885 验收）：
#   1) 未登录调用旧 /api/upgrade、/api/upgrade/confirm → 401（鉴权保留）
#   2) 已登录调用 → HTTP 200 + 业务码 501 + 明确提示；服务目录无新增/无改动
#   3) 服务进程未重启、全局阻塞未生效（本地接口仍 200）
#   4) SSE：同 token 重注册幂等；被顶号后收到 SESSION_OFFLINE 且服务端关闭旧流
#   5) 输出测试前后宿主网络指纹供比对
set -uo pipefail

DEB="${1:-/tmp/sophliteos_soc_2.2.14.deb}"
W="${WORKDIR:-/tmp/mys2885-verify}"

net_fingerprint() { { ip -4 addr show | grep -E '^[0-9]+:|inet '; ip route; } | sha256sum | cut -d" " -f1; }

NET_BEFORE="$(net_fingerprint)"
echo "网络指纹(前): $NET_BEFORE"

rm -rf "$W"
mkdir -p "$W"/{root,cfg,log,db,data,out,bmssm}
dpkg-deb -x "$DEB" "$W/root"
BIN="$W/root/opt/sophon/sophliteos/bin/sophliteos"
[ -x "$BIN" ] || { echo "FAIL: 产物中无 sophliteos 可执行文件"; exit 1; }

# 基于产物自带默认配置，仅调整端口与路径（全部在临时目录内）
sed -e 's/^  port: 8080/  port: 18080/' \
    -e "s#^  path: /var/log/sophliteos#  path: $W/log#" \
    -e "s#^  path: /var/lib/sophliteos/db/sophliteos.db#  path: $W/db/sophliteos.db#" \
    "$W/root/opt/sophon/sophliteos/config/sophliteos.yaml" > "$W/cfg/sophliteos.yaml"

SECRET="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
printf '%s' "$SECRET" > "$W/bmssm/jwt_secret"

# 进入私有 mount namespace 后执行全部业务；--propagation private 保证 mount 不外泄
unshare -m --propagation private -- bash -s "$W" "$BIN" "$SECRET" <<'INNER'
set -uo pipefail
W="$1"; BIN="$2"; SECRET="$3"

mount --bind "$W/cfg"    /opt/sophon/sophliteos/config || { echo "FAIL: bind config"; exit 1; }
mount --bind "$W/log"    /var/log/sophliteos            || { echo "FAIL: bind log";    exit 1; }
mkdir -p /var/lib/sophliteos/db
mount --bind "$W/db"     /var/lib/sophliteos/db         || { echo "FAIL: bind db";     exit 1; }
mkdir -p /var/lib/bmssm
mount --bind "$W/bmssm"  /var/lib/bmssm                 || { echo "FAIL: bind bmssm";  exit 1; }
mount --bind "$W/data"   /data                          || { echo "FAIL: bind data";   exit 1; }
mkdir -p /data/sophliteos /data/ota

# 自检：确认 /data 在命名空间内确实是临时目录的 bind。
# 该机型根文件系统是 overlayfs：bind 到 overlay 之上时 findmnt 会同时列出下层设备
# 与 "overlay[<bind源>]"，故只要求"绑定源出现在 SOURCE 中"。
DATA_SRC="$(findmnt -n -o SOURCE /data)"
if ! printf '%s' "$DATA_SRC" | grep -qF "$W/data"; then
  echo "FAIL: /data 未隔离（SOURCE=$DATA_SRC），立即中止"
  exit 1
fi
echo "自检通过：/data 已隔离到 $W/data（SOURCE=$DATA_SRC）"

FAIL=0
# 服务目录内预置"陷阱"文件：旧实现会先 O_TRUNC 再校验文件名，从而把它截断
printf 'ORIGINAL-CONTENT-DO-NOT-TOUCH' > /data/sophliteos/sophliteos-linux_arm64.tgz
printf '#!/bin/sh\necho should-not-be-truncated\n' > /data/sophliteos/evil.sh
TRAP_MD5="$(md5sum /data/sophliteos/sophliteos-linux_arm64.tgz /data/sophliteos/evil.sh)"
DIR_BEFORE="$(ls -A /data/sophliteos | sort | tr '\n' ' ')"

"$BIN" > "$W/out/sophliteos.out" 2>&1 &
SRV_PID=$!
trap 'kill "$SRV_PID" 2>/dev/null' EXIT

for _ in $(seq 1 75); do
  curl -sf -o /dev/null http://127.0.0.1:18080/api/sso/active && break
  sleep 0.2
done
if ! curl -sf -o /dev/null http://127.0.0.1:18080/api/sso/active; then
  echo "FAIL: 服务未就绪"; head -20 "$W/out/sophliteos.out"; exit 1
fi
echo "服务已启动 (pid=$SRV_PID, 127.0.0.1:18080)"

PAYLOAD="$W/root/opt/sophon/sophliteos/config/sophliteos.yaml"

# ---- 1) 未登录：两个旧端点都必须 401 ----
for p in /api/upgrade /api/upgrade/confirm; do
  code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:18080$p" \
    -F "file=@$PAYLOAD;filename=sophliteos-linux_arm64.tgz")"
  if [ "$code" = "401" ]; then echo "PASS 未登录 $p -> 401"; else echo "FAIL 未登录 $p -> $code"; FAIL=1; fi
done

# ---- 登录：签发与 bmssm 同格式的 JWT 并 register ----
mktok() {
  SECRET="$SECRET" SUB="$1" python3 - <<'PY'
import jwt, os, time
print(jwt.encode({"sub": os.environ["SUB"], "iat": int(time.time()), "exp": int(time.time()) + 3600},
                 os.environ["SECRET"], algorithm="HS256"))
PY
}
TOK="$(mktok admin)"
code="$(curl -s -o "$W/out/register.json" -w '%{http_code}' -X POST http://127.0.0.1:18080/api/sso/register \
  -H 'Content-Type: application/json' -d "{\"username\":\"admin\",\"token\":\"$TOK\"}")"
if [ "$code" = "200" ]; then echo "PASS register -> 200（活跃会话已建立）";
else echo "FAIL register -> $code $(cat "$W/out/register.json")"; FAIL=1; fi

# ---- 2) 已登录：合法/非法包名与任意内容都必须 200 + 业务码 501 + 明确提示 ----
try_upload() {
  local name="$1" path="$2" body http json
  body="$(curl -s -w '\n%{http_code}' -X POST "http://127.0.0.1:18080$path" \
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
  echo "FAIL 服务目录被改动:"; echo " before=[$DIR_BEFORE]"; echo " after =[$DIR_AFTER]"
  echo "$TRAP_MD5" > "$W/out/trap-before.txt"; echo "$TRAP_AFTER" > "$W/out/trap-after.txt"
  diff "$W/out/trap-before.txt" "$W/out/trap-after.txt"; FAIL=1
fi
if kill -0 "$SRV_PID" 2>/dev/null; then echo "PASS 服务进程未被替换/退出（未 exec 重启）";
else echo "FAIL 服务进程已消失（疑似重启）"; FAIL=1; fi
vcode="$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOK" http://127.0.0.1:18080/api/device/version)"
if [ "$vcode" = "200" ]; then echo "PASS 旧升级调用后本地接口仍 200（未置 BlockAllRequests）";
else echo "FAIL 本地接口 $vcode（疑似被阻塞）"; FAIL=1; fi

# ---- 4) SSE ----
curl -s -N -H "Authorization: Bearer $TOK" --max-time 10 http://127.0.0.1:18080/api/sso/events \
  > "$W/out/sse-old.txt" 2> "$W/out/sse-old.err" &
SSE_PID=$!
sleep 1
curl -s -o /dev/null -X POST http://127.0.0.1:18080/api/sso/register -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"token\":\"$TOK\"}"
sleep 1
if kill -0 "$SSE_PID" 2>/dev/null; then echo "PASS 同 token 重注册幂等（旧流保持，未被自踢）";
else echo "FAIL 同 token 重注册把当前有效会话踢掉"; FAIL=1; fi

TOK2="$(mktok admin2)"
curl -s -o /dev/null -X POST http://127.0.0.1:18080/api/sso/register -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin2\",\"token\":\"$TOK2\"}"
wait "$SSE_PID" 2>/dev/null
if grep -q 'event: SESSION_OFFLINE' "$W/out/sse-old.txt"; then echo "PASS 旧流收到 SESSION_OFFLINE";
else echo "FAIL 旧流未收到 SESSION_OFFLINE: $(cat "$W/out/sse-old.txt")"; FAIL=1; fi
if grep -qi 'timed out' "$W/out/sse-old.err" 2>/dev/null; then
  echo "FAIL 旧流未被服务端关闭（等到了客户端 --max-time 超时）"; FAIL=1
else
  echo "PASS 旧流被服务端主动关闭（未等客户端超时）"
fi

curl -s -o /dev/null -X POST http://127.0.0.1:18080/api/sso/logout -H "Authorization: Bearer $TOK2"
sleep 0.5
kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null

if grep -qi 'panic\|fatal error' "$W/out/sophliteos.out"; then
  echo "FAIL 服务端日志出现 panic/fatal"; tail -20 "$W/out/sophliteos.out"; FAIL=1
fi

echo
if [ "$FAIL" -ne 0 ]; then echo "RESULT: FAIL"; exit 1; fi
echo "RESULT: PASS"
exit 0
INNER

INNER_RC=$?

NET_AFTER="$(net_fingerprint)"
echo "=== 网络指纹（测试前后必须一致）==="
echo "before=$NET_BEFORE"
echo "after =$NET_AFTER"
if [ "$NET_BEFORE" != "$NET_AFTER" ]; then
  echo "FAIL: 验证过程改动了宿主网络"; exit 1
fi
echo "（一致：未改动网络地址/路由）"
echo "exit=$INNER_RC"
exit "$INNER_RC"
