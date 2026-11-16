import asyncio, json, time
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from e2e_common import BASE, INFER_KEY, admin, record
async def m():
    async with streamablehttp_client(f"{BASE}/mcp", headers={"Authorization": f"Bearer {INFER_KEY}"}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("kb_search", {"query": "哪条产线的合格率是 99.1%", "top_k": 3})
            t = "\n".join(c.text for c in res.content)
            import re
            cid = re.search(r"chunk_id=([A-Za-z0-9_\-]+:[0-9]+)", t).group(1)
            rr = await s.call_tool("kb_read", {"chunk_id": cid, "neighbors": 1})
            tt = "\n".join(c.text for c in rr.content)
            record("A4 MCP", "kb_read", not rr.isError and cid in tt, f"从 kb_search 文本取 chunk_id={cid} 调 kb_read 成功：{tt[:100]!r}（首判是测试正则未包含「:n」）")
asyncio.run(m())
kb = admin.post("/api/apps/kb", json={"name": "e2e-answer"}).json()["kb"]["id"]
admin.post(f"/api/apps/kb/{kb}/docs", files=[("files", ("说明.txt", "二号线合格率为 99.1%，负责人李静。三号线下月停产检修。".encode(), "text/plain"))])
for _ in range(40):
    d = admin.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
    if d and d[0]["status"] == "ready": break
    time.sleep(2)
ids = [x["chunk_id"] for x in admin.post(f"/api/apps/kb/{kb}/search", json={"query": "检修", "top_k": 1}).json()["results"]]
text = ""; cites = None
with admin.stream("POST", f"/api/apps/kb/{kb}/answer", json={"query": "三号线什么时候检修？", "chunk_ids": ids, "max_tokens": 120}, timeout=600) as s:
    for line in s.iter_lines():
        if line.startswith("data:") and line[5:].strip() != "[DONE]":
            ev = json.loads(line[5:])
            if ev.get("type") == "citations": cites = ev["items"]
            for ch in ev.get("choices") or []:
                text += (ch.get("delta") or {}).get("content") or ""
record("A5 应用·知识库", "问答（35B，流式，带引用）", "检修" in text and bool(cites), f"{text!r} citations={cites}")
admin.delete(f"/api/apps/kb/{kb}")
