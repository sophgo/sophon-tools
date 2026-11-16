import json, time, httpx
from e2e_common import BASE, record
A = "A6 Agent"
c = httpx.Client(base_url=BASE, timeout=900)
assert c.post("/api/login", json={"password": "admin"}).status_code == 200
s = c.post("/agents/opencode/session", json={"title": "e2e"})
print("session", s.status_code, s.text[:150])
sid = s.json()["id"]
cfg = c.get("/agents/opencode/config").json()
print("model", cfg.get("model"), "mcp", list((cfg.get("mcp") or {}).keys()))
t0 = time.time()
r = c.post(f"/agents/opencode/session/{sid}/message", json={"parts": [{"type": "text",
    "text": "请调用 cv84x6 的 kb_list 工具，告诉我设备上有几个知识库以及它们的名字。只调用这一个工具，然后用一句话回答。"}]})
dt = time.time() - t0
d = r.json() if r.status_code == 200 else {}
tools = [(p.get("tool"), (p.get("state") or {}).get("status"), str((p.get("state") or {}).get("output", ""))[:120]) for p in d.get("parts", []) if p.get("type") == "tool"]
text = " ".join(p.get("text", "") for p in d.get("parts", []) if p.get("type") == "text")
info = d.get("info") or {}
print("tools", tools); print("text", text[:300]); print("info", info.get("modelID"), info.get("tokens"))
ok = r.status_code == 200 and any("kb_list" in (t or "") and st == "completed" for t, st, _ in tools) and len(text) > 0
record(A, "opencode 经代理对话 + 调用 cv84x6 MCP（kb_list）", ok,
       f"{r.status_code} {dt:.0f}s model={info.get('modelID')} tools={tools} answer={text[:120]!r}")
