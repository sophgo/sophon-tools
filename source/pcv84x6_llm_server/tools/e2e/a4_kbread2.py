import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from e2e_common import BASE, INFER_KEY
async def main():
    async with streamablehttp_client(f"{BASE}/mcp", headers={"Authorization": f"Bearer {INFER_KEY}"}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for cid in ("681c49268db348d394597b094107c4a1:0", "4b76aacde0ee49028a8bac7d262dc04b:1"):
                rr = await s.call_tool("kb_read", {"chunk_id": cid, "neighbors": 1})
                print("=====", cid); print("\n".join(c.text for c in rr.content)[:900])
asyncio.run(main())
