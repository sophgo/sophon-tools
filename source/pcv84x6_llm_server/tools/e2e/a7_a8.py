"""Areas 7 + 8: admin API (auth, errors, docs offline, settings) and logs/audit (incl. secret scan)."""
import io
import re
import zipfile

import httpx

from e2e_common import ADMIN_KEY, BASE, INFER_KEY, ROOT, admin, board, record

A7, A8 = "A7 管理 API", "A8 日志与审计"
anon = httpx.Client(base_url=BASE, timeout=60)

# docs offline + gated
for path in ("/api/docs", "/api/redoc", "/api/openapi.json", "/v1/openapi.json"):
    r = admin.get(path)
    ext = re.findall(r"https?://(?!127\.0\.0\.1|localhost)[a-zA-Z0-9.\-]+\.(?:com|net|org|io|dev)[^\s\"'<>]*", r.text) if path.endswith(("docs", "redoc")) else []
    ra = anon.get(path)
    record(A7, f"{path} 管理凭据可读、匿名拒绝", r.status_code == 200 and ra.status_code in (401, 403),
           f"admin={r.status_code} anon={ra.status_code} bytes={len(r.content)}" + (f" external={ext[:3]}" if ext else ""))
for asset_path in re.findall(r'(?:src|href)="(/api/[^"]+)"', admin.get("/api/docs").text):
    rr = admin.get(asset_path)
    if rr.status_code != 200:
        record(A7, f"文档静态资源 {asset_path}", False, f"{rr.status_code}")
spec = admin.get("/api/openapi.json").json()
ops = sum(len(v) for v in spec["paths"].values())
untagged = [f"{m.upper()} {p}" for p, v in spec["paths"].items() for m, o in v.items() if not o.get("tags") or not o.get("summary")]
record(A7, "OpenAPI 完整（tags + summary）", ops > 50 and not untagged, f"ops={ops} untagged={untagged[:5]}")

# errors
r = admin.post("/api/models/no-such-model/load")
record(A7, "错误码 404 not_found", r.status_code == 404 and r.json().get("code") == "not_found", f"{r.status_code} {r.text[:120]}")
r = admin.post("/api/settings", json={"max_queue": "twelve"})
record(A7, "错误码 422 validation_error（中文）", r.status_code == 422 and r.json().get("code") == "validation_error", f"{r.text[:140]}")
r = httpx.get(f"{BASE}/api/models", headers={"Authorization": f"Bearer {INFER_KEY}"})
record(A7, "推理 key 调 /api → 403 forbidden_scope", r.status_code == 403 and r.json().get("code") == "forbidden_scope", f"{r.status_code}")

# settings + per-model settings round trip
s0 = admin.get("/api/settings").json()
r = admin.post("/api/settings", json={"prefix_cache_ttl_min": s0["prefix_cache_ttl_min"] + 1})
ok = r.status_code == 200 and r.json()["settings"]["prefix_cache_ttl_min"] == s0["prefix_cache_ttl_min"] + 1
admin.post("/api/settings", json={"prefix_cache_ttl_min": s0["prefix_cache_ttl_min"]})
record(A7, "设置读写", ok, f"{r.status_code}")
mid = "qwen3-embedding-0.6b"
r = admin.put(f"/api/models/{mid}/settings", json={"idle_unload_min": 7, "auto_load": True, "mem_limit_mb": 3072})
g = admin.get(f"/api/models/{mid}/settings").json()
ok = r.status_code == 200 and g["settings"] == {"idle_unload_min": 7, "auto_load": True, "mem_limit_mb": 3072}
r2 = admin.put(f"/api/models/{mid}/settings", json={"idle_unload_min": None, "auto_load": None, "mem_limit_mb": None})
record(A7, "按模型设置读写与恢复默认", ok and r2.status_code == 200 and r2.json()["settings"] == {"idle_unload_min": None, "auto_load": None, "mem_limit_mb": None},
       f"{r.status_code} {g['settings']} -> {r2.json()['settings']}")
r = admin.put(f"/api/models/{mid}/settings", json={"mem_limit_mb": 1})
record(A7, "按模型设置越界 400", r.status_code == 400, f"{r.status_code} {r.text[:120]}")
for p in ("/api/storage", "/api/keys", "/api/catalog", "/api/agents", "/api/inference-records?limit=2"):
    r = admin.get(p)
    record(A7, f"GET {p.split('?')[0]}", r.status_code == 200, f"{r.status_code}")

# logs
src = admin.get("/api/logs/sources").json()["sources"]
ids = [s["id"] for s in src]
record(A8, "日志源（平台 + 各 worker）", "platform" in ids and any(i.startswith("worker:") for i in ids), f"{ids}")
p = admin.get("/api/logs/platform", params={"limit": 50}).json()
record(A8, "平台日志最新 N 行", len(p["lines"]) > 0, f"lines={len(p['lines'])} last={p['lines'][-1]['message'][:80] if p['lines'] else None}")
w = admin.get("/api/logs/platform", params={"level": "warning", "limit": 200}).json()
bad = [l for l in w["lines"] if l["level"] and l["level"].upper() in ("INFO", "DEBUG")]
record(A8, "级别过滤（warning 及以上）", not bad, f"n={len(w['lines'])} sample={[l['message'][:60] for l in w['lines'][-3:]]}")
q = admin.get("/api/logs/platform", params={"q": "loaded", "limit": 50}).json()
record(A8, "关键字过滤", all("loaded" in l["message"].lower() for l in q["lines"]) and q["lines"], f"n={len(q['lines'])}")
if p.get("cursor"):
    older = admin.get("/api/logs/platform", params={"limit": 50, "cursor": p["cursor"]}).json()
    record(A8, "翻页（cursor）", older["lines"] and older["lines"][-1]["ts"] <= p["lines"][0]["ts"], f"older={len(older['lines'])}")
r = admin.get("/api/logs/platform/download", params={"q": "loaded"})
record(A8, "下载筛选结果（文本）", r.status_code == 200 and "loaded" in r.text and r.headers.get("content-type", "").startswith("text/"), f"{r.status_code} {r.headers.get('content-type')} {len(r.content)} B")
wid = next(i for i in ids if i.startswith("worker:"))
r = admin.get(f"/api/logs/{wid}/download")
try:
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
except Exception as e:
    names = [f"not a zip: {e}"]
record(A8, "下载全部（zip）", r.status_code == 200 and names and not names[0].startswith("not a zip"), f"{r.status_code} {names[:4]}")
r = admin.get("/api/logs/..%2F..%2Fetc%2Fpasswd")
record(A8, "日志源路径穿越被拒", r.status_code in (400, 404), f"{r.status_code}")

# audit
a = admin.get("/api/audit", params={"limit": 200}).json()
items = a["items"]
loads = [i for i in items if i["path"].endswith("/load") and i["actor_name"] == "e2e-admin"]
fails = [i for i in items if not i["ok"]]
record(A8, "审计覆盖本次操作（e2e-admin 加载模型等）", len(loads) >= 5 and a["total"] > 20, f"total={a['total']} loads_by_e2e={len(loads)} failures={len(fails)}")
r = admin.get("/api/audit/export")
csv = r.content.decode("utf-8-sig", errors="replace")
secrets = [k for k in (ADMIN_KEY, INFER_KEY, (ROOT / "prekey").read_text().strip()) if k in csv]
record(A8, "审计 CSV 导出（BOM + 无密钥）", r.status_code == 200 and r.content[:3] == b"\xef\xbb\xbf" and not secrets, f"{r.status_code} rows={csv.count(chr(10))} leaked={len(secrets)}")
keys = [ADMIN_KEY, INFER_KEY, (ROOT / "prekey").read_text().strip()]
out = board("cd /data/cv84x6_llm_server/state && for k in " + " ".join(k[:24] for k in keys) +
            "; do c=$(grep -c -a -F \"$k\" audit.db* 2>/dev/null | awk -F: '{s+=$2} END {print s+0}'); echo \"$c\"; done; "
            "grep -c -a -F '\"password\"' audit.db* | awk -F: '{s+=$2} END {print \"pwfield\", s+0}'")
counts = [l for l in out.splitlines() if l.strip()]
record(A8, "audit.db 中无任何 key（含前 24 字符）与密码字段", all(c.split()[-1] == "0" for c in counts), f"{counts}")
