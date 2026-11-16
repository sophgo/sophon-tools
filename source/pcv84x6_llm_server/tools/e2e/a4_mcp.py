"""Area 4: MCP over Streamable HTTP with the official SDK -- every tool, including the path allowlist."""
import asyncio
import json
import sys
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from e2e_common import BASE, INFER_KEY, record

A = "A4 MCP"
INBOX = "/data/cv84x6_llm_server/inbox/e2e"
WITH_VL = "--vl" in sys.argv


def text_of(res) -> str:
    return "\n".join(getattr(c, "text", "") for c in res.content)


async def main():
    async with streamablehttp_client(f"{BASE}/mcp", headers={"Authorization": f"Bearer {INFER_KEY}"}) as (r, w, _):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            record(A, "initialize", bool(init.serverInfo.name), f"server={init.serverInfo.name} proto={init.protocolVersion}")
            tools = {t.name for t in (await s.list_tools()).tools}
            want = {"kb_list", "kb_create", "kb_search", "kb_read", "kb_list_documents", "kb_add_document",
                    "kb_document_status", "ocr_read", "transcribe_audio"}
            record(A, "tools/list（9 个）", want <= tools, f"{sorted(tools)}")

            async def call(name, args):
                t0 = time.time()
                res = await s.call_tool(name, args)
                return res, text_of(res), time.time() - t0

            if WITH_VL:
                res, t, dt = await call("ocr_read", {"path": f"{INBOX}/cn_table_merged.png", "mode": "vl"})
                record(A, "ocr_read mode=vl（合并单元格表格）", not res.isError and "rowspan" in t and "colspan" in t,
                       f"{dt:.1f}s {t[:160]!r}")
                res, t, dt = await call("ocr_read", {"path": f"{INBOX}/scan.pdf", "mode": "vl"})
                record(A, "ocr_read mode=vl 扫描 PDF", not res.isError and len(t) > 50, f"{dt:.1f}s {t[:160]!r}")
                return

            res, t, dt = await call("kb_create", {"name": "e2e-mcp"})
            kb = (res.structuredContent or {}).get("id") or (json.loads(t).get("id") if t.strip().startswith("{") else None)
            if not kb:
                import re
                m = re.search(r"\b([0-9a-f]{8,})\b", t)
                kb = m.group(1) if m else None
            record(A, "kb_create", not res.isError and bool(kb), f"kb={kb} {t[:120]!r}")
            res, t, dt = await call("kb_add_document", {"kb": kb, "path": f"{INBOX}/text.pdf"})
            st = res.structuredContent or {}
            doc = st.get("doc_id") or st.get("id")
            record(A, "kb_add_document（PDF 路径）", not res.isError, f"doc={doc} {t[:120]!r}")
            res2, t2, _ = await call("kb_add_document", {"kb": kb, "text": "二号线合格率为 99.1%，负责人李静。一号线产量最高。", "name": "说明.txt"})
            record(A, "kb_add_document（文本）", not res2.isError, f"{t2[:120]!r}")
            for _ in range(60):
                res, t, _ = await call("kb_list_documents", {"kb": kb})
                if t.count("ready") >= 2 or ("failed" in t):
                    break
                await asyncio.sleep(3)
            record(A, "kb_list_documents / 建库完成", "ready" in t and "failed" not in t, f"{t[:200]!r}")
            if doc:
                res, t, _ = await call("kb_document_status", {"kb": kb, "doc_id": doc})
                record(A, "kb_document_status", not res.isError and "ready" in t, f"{t[:120]!r}")
            res, t, dt = await call("kb_search", {"query": "哪条产线的合格率是 99.1%", "kb": kb, "top_k": 3})
            record(A, "kb_search（混合检索 + 精排）", not res.isError and "99.1" in t, f"{dt:.1f}s {t[:200]!r}")
            import re
            cid = re.search(r"chunk_id=([A-Za-z0-9_\-]+:[0-9]+)", t)
            if cid:
                res, t, _ = await call("kb_read", {"chunk_id": cid.group(1), "neighbors": 1})
                record(A, "kb_read", not res.isError and len(t) > 10, f"{t[:120]!r}")
            else:
                record(A, "kb_read", None, f"no chunk id in kb_search output to read: {t[:160]!r}")
            res, t, _ = await call("kb_list", {})
            record(A, "kb_list", not res.isError and "e2e-mcp" in t, f"{t[:120]!r}")
            res, t, dt = await call("ocr_read", {"path": f"{INBOX}/table_stats.png"})
            record(A, "ocr_read 图片（lines）", not res.isError and "合格率" in t, f"{dt:.1f}s {t[:100]!r}")
            res, t, dt = await call("ocr_read", {"path": f"{INBOX}/mixed.pdf"})
            record(A, "ocr_read PDF（文字层 + 扫描混合）", not res.isError and len(t) > 50, f"{dt:.1f}s {t[:160]!r}")
            res, t, dt = await call("ocr_read", {"path": f"{INBOX}/scan.pdf", "mode": "layout"})
            record(A, "ocr_read 扫描 PDF layout", not res.isError and len(t) > 50, f"{dt:.1f}s {t[:120]!r}")
            res, t, dt = await call("transcribe_audio", {"path": f"{INBOX}/asr_zh.mp3"})
            record(A, "transcribe_audio", not res.isError and "停滞" in t, f"{dt:.1f}s {t[:100]!r}")
            res, t, _ = await call("ocr_read", {"path": "/etc/passwd"})
            record(A, "路径白名单拒绝 /etc/passwd", res.isError and "root:" not in t, f"isError={res.isError} {t[:120]!r}")
            res, t, _ = await call("ocr_read", {"path": f"{INBOX}/../../state/state.json"})
            record(A, "路径穿越被拒（../）", res.isError and "keys" not in t, f"isError={res.isError} {t[:120]!r}")


asyncio.run(main())
