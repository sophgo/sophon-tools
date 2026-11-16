"""RC2: retest D1, D2, D3, D5, D8 on the board."""
import asyncio
import base64
import time

import httpx
import openai
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from e2e_common import BASE, INFER_KEY, admin, board, load, record, unload

IMG = "/home/zzt/workspace/cv84x6-demo-ui/tests/data/ocr/img/"
P = "__SUDO_PW__"

# D5: OCR unload x5 (with layout so the lazy layout engine exists), then the journal
t0 = time.strftime("%Y-%m-%d %H:%M:%S")
b64 = base64.b64encode(open(IMG + "table_stats.png", "rb").read()).decode()
for i in range(5):
    load("ppocrv6-medium")
    httpx.post(f"{BASE}/v1/ocr", headers={"Authorization": f"Bearer {INFER_KEY}"},
               json={"model": "ppocrv6-medium", "image": b64, "mode": "layout"}, timeout=120)
    unload("ppocrv6-medium")
    time.sleep(1)
out = board(f"echo {P} | sudo -S journalctl -u cv84x6-llm --since '{t0}' --no-pager 2>/dev/null | grep -c -E 'terminate called|bmlib_memory\\]\\[error|bmlib_runtime\\]\\[error|BM_CHECK'; "
            "grep -c 'terminate called' /data/cv84x6_llm_server/state/logs/worker-ppocrv6-medium.log; "
            f"echo {P} | sudo -S dmesg 2>/dev/null | grep -c 'wait api timeout'")
nums = [l.strip() for l in out.splitlines() if l.strip().isdigit()]
record("RC2 复测", "D5 OCR 加载/卸载 5 次（含 layout 引擎）", nums[:1] == ["0"],
       f"本轮 journal 中 terminate/bmlib error 行数={nums[0] if nums else '?'}；worker 日志累计 terminate={nums[1] if len(nums) > 1 else '?'}（含 RC1 时的旧记录）；dmesg wait api timeout={nums[2] if len(nums) > 2 else '?'}")

# D1: /v1 error shape via the OpenAI SDK
cli = openai.OpenAI(base_url=f"{BASE}/v1", api_key="sk-wrong", max_retries=0)
try:
    cli.models.list()
    msg = None
except openai.AuthenticationError as e:
    msg = (e.body or {}).get("message") if isinstance(e.body, dict) else str(e.body)
cli2 = openai.OpenAI(base_url=f"{BASE}/v1", api_key=INFER_KEY, max_retries=0)
try:
    cli2.chat.completions.create(model="qwen3-embedding-0.6b-not-loaded", messages=[{"role": "user", "content": "x"}])
    msg2 = None
except openai.APIStatusError as e:
    msg2 = (e.body or {}).get("message") if isinstance(e.body, dict) else str(e.body)
record("RC2 复测", "D1 /v1 错误为 OpenAI error 对象（SDK 能读出 message）", msg == "invalid API key" and bool(msg2),
       f"401 message={msg!r}; 不存在的模型 message={str(msg2)[:80]!r}")


# D2/D3: MCP kb tools
async def mcp():
    async with streamablehttp_client(f"{BASE}/mcp", headers={"Authorization": f"Bearer {INFER_KEY}"}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("kb_search", {"query": "合格率", "top_k": 3})
            text = "\n".join(c.text for c in res.content)
            rows = (res.structuredContent or {}).get("results", [])
            d3 = rows and all(f"chunk_id={x['chunk_id']}" in text for x in rows)
            record("RC2 复测", "D3 kb_search 文本带 chunk_id", bool(d3), f"{text[:160]!r}")
            ok = True
            ev = []
            for x in rows:
                rr = await s.call_tool("kb_read", {"chunk_id": x["chunk_id"], "neighbors": 3})
                docs = {c["chunk_id"].rsplit(":", 1)[0] for c in (rr.structuredContent or {}).get("chunks", [])}
                ok &= docs == {x["chunk_id"].rsplit(":", 1)[0]}
                ev.append(f"{x['doc_name']}→{len(docs)} doc")
            record("RC2 复测", "D2 kb_read 相邻片段不跨文档", ok, "; ".join(ev))

load("qwen3-embedding-0.6b")
load("bge-reranker-v2-m3")
asyncio.run(mcp())

# D8: opencode bind
admin.post("/api/agents/opencode/stop")
time.sleep(3)
admin.post("/api/agents/opencode/start")
time.sleep(15)
out = board("ss -ltnp 2>/dev/null | grep ':14096 '")
record("RC2 复测", "D8 opencode 只监听 127.0.0.1", "127.0.0.1:14096" in out and "0.0.0.0:14096" not in out, out.strip()[:120])
