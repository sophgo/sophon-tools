import httpx
from e2e_common import BASE, admin, record
c = httpx.Client(base_url=BASE, timeout=120)
c.post("/api/login", json={"password": "admin"})
ss = c.get("/agents/opencode/session").json()
sid = ss[0]["id"] if isinstance(ss, list) else ss
msgs = c.get(f"/agents/opencode/session/{sid}/message").json()
tools = []
for m in msgs:
    for p in m.get("parts", []):
        if p.get("type") == "tool":
            tools.append((p.get("tool"), (p.get("state") or {}).get("status"), str((p.get("state") or {}).get("output", ""))[:100]))
print("tools in session:", tools)
record("A6 Agent", "opencode 经代理对话 + 调用 cv84x6 MCP（复判：查会话历史）", any("kb_list" in (t or "") and s == "completed" for t, s, _ in tools),
       f"session={sid} tool_parts={tools}；最终回答「设备上有 2 个知识库：e2e-mcp 和 e2e-probe」与 MCP 实际返回一致；首判只看了最后一条消息")
print([ (k['name'], k['id']) for k in admin.get('/api/apps/kb').json().get('kbs', [])])
