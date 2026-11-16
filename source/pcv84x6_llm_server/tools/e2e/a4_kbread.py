import asyncio, json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from e2e_common import BASE, INFER_KEY, record
async def main():
    async with streamablehttp_client(f"{BASE}/mcp", headers={"Authorization": f"Bearer {INFER_KEY}"}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tl = {t.name: t for t in (await s.list_tools()).tools}
            print("kb_search desc:", tl["kb_search"].description[:300])
            print("kb_read desc:", tl["kb_read"].description[:300])
            res = await s.call_tool("kb_search", {"query": "合格率", "top_k": 2})
            print("structured:", json.dumps(res.structuredContent, ensure_ascii=False)[:600])
            hits = (res.structuredContent or {}).get("results") or (res.structuredContent or {}).get("hits") or []
            cid = hits[0].get("chunk_id") or hits[0].get("id") if hits else None
            if cid:
                rr = await s.call_tool("kb_read", {"chunk_id": cid, "neighbors": 1})
                t = "\n".join(c.text for c in rr.content)
                record("A4 MCP", "kb_read（取 structuredContent 的 chunk_id）", not rr.isError and len(t) > 10, f"chunk={cid} {t[:120]!r}")
asyncio.run(main())
