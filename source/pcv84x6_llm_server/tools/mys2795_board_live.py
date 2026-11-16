"""板上核对修正后的增额算式（真实 native worker，不注入读数）。

asks for a limit whose runtime budget increase is larger than
``free - own old budget - floor`` -- the exact arithmetic the first review found
to be wrong -- and checks it is refused, and that a smaller raise still works.
"""
import json, subprocess, urllib.request as u, http.cookiejar
MIB = 1 << 20
BM_SMI = "/opt/sophon/libsophon-current/bin/bm-smi"
cj = http.cookiejar.CookieJar(); op = u.build_opener(u.HTTPCookieProcessor(cj))
base = "http://127.0.0.1:8010"
def call(p, d=None, m=None):
    r = u.Request(base+p, None if d is None else json.dumps(d).encode(),
                  {"Content-Type": "application/json"}, method=m)
    try:
        x = op.open(r, timeout=300); return x.status, json.loads(x.read())
    except u.HTTPError as e:
        return e.code, json.loads(e.read())
def free_mib():
    from app.core.monitor import parse_bm_smi
    raw = subprocess.run([BM_SMI, "-noloop"], capture_output=True, timeout=10).stdout
    i = parse_bm_smi(raw)
    return (i["mem_total_bytes"] - i["mem_used_bytes"]) // MIB
call("/api/login", {"password": "admin"})
S = "/api/models/qwen3.5-9b-128k/settings"
call("/api/models/qwen3.5-9b-128k/load", {}, "POST")
st = call(S)[1]; static = st["mem_static_bytes"] >> 20
call(S, {"mem_limit_mb": static + 400}, "PUT")
old = (call(S)[1]["effective"]["mem_limit_bytes"] >> 20) - static
free = free_mib(); reserve = 1024
# 可承诺的增额 = free - 本模型原预算 - reserve（修正后的算式）
allow = free - old - reserve
print("静态=%d 原预算=%d free=%d reserve=%d => 本次最多可增 %d MiB"
      % (static, old, free, reserve, allow))
print("\n-- A. 增加 %d MiB（= 可承诺量，应当成功）" % (allow - 64))
code, body = call(S, {"mem_limit_mb": static + old + allow - 64}, "PUT")
print("   HTTP %d，worker 预算=%s MiB" % (code, (body.get("applied") or {}).get("mem_runtime_budget_bytes", 0)//MIB))
now = (call(S)[1]["effective"]["mem_limit_bytes"] >> 20) - static
print("\n-- B. 再增加 %d MiB（超过剩余可承诺量，必须拒绝）" % (allow + 256))
code, body = call(S, {"mem_limit_mb": static + now + allow + 256}, "PUT")
print("   HTTP %d code=%s" % (code, body.get("code")))
print("   detail:", str(body.get("detail"))[:170])
after = call(S)[1]
print("   拒绝后：设置=%d MiB，生效上限=%d MiB" % (after["settings"]["mem_limit_mb"], after["effective"]["mem_limit_bytes"] >> 20))
print("\n-- C. 恢复默认（同一条准入路径）")
print("   HTTP %d" % call(S, {"mem_limit_mb": None}, "PUT")[0])
