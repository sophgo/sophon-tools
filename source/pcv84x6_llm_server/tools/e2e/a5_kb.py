"""Area 5: knowledge-base app over /api/apps/kb with an admin key (txt, text pdf, scanned pdf, image)."""
import json
import time

from e2e_common import admin, record

A = "A5 应用·知识库"
D = "/home/zzt/workspace/cv84x6-demo-ui/tests/data/"
r = admin.post("/api/apps/kb", json={"name": "e2e-kb"})
kb = r.json().get("id") or r.json().get("kb", {}).get("id")
record(A, "建库", r.status_code == 200 and bool(kb), f"{r.status_code} id={kb}")

files = [("files", ("制度.pdf", open(D + "kb/text.pdf", "rb"), "application/pdf")),
         ("files", ("扫描件.pdf", open(D + "kb/scan.pdf", "rb"), "application/pdf")),
         ("files", ("产量表.png", open(D + "ocr/img/table_stats.png", "rb"), "image/png")),
         ("files", ("说明.txt", "二号线合格率为 99.1%，负责人李静。三号线下月停产检修。".encode(), "text/plain"))]
r = admin.post(f"/api/apps/kb/{kb}/docs", files=files, timeout=300)
record(A, "上传 4 个文件（txt / 文字 pdf / 扫描 pdf / 图片）", r.status_code == 200, f"{r.status_code} {r.text[:160]}")

t0 = time.time()
docs = []
for _ in range(120):
    docs = admin.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
    if docs and all(d["status"] in ("ready", "failed") for d in docs):
        break
    time.sleep(3)
ready = [d for d in docs if d["status"] == "ready"]
record(A, "建库完成（含 OCR）", len(ready) == 4,
       f"{time.time() - t0:.0f}s " + "; ".join(f"{d['name']}={d['status']}/{d.get('chunks')}" + (f" err={d.get('error')}" if d.get('error') else "") for d in docs))

r = admin.post(f"/api/apps/kb/{kb}/search", json={"query": "三号线什么时候检修", "top_k": 3})
d = r.json()
res = d.get("results", [])
record(A, "混合检索 + 精排", r.status_code == 200 and res and "检修" in res[0]["text"],
       f"{r.status_code} stages={[(s.get('name'), s.get('status')) for s in d.get('stages', [])] if isinstance(d.get('stages'), list) else d.get('stages')} top={res[0]['doc_name'] if res else None}")
r = admin.post(f"/api/apps/kb/{kb}/search", json={"query": "四号线产量", "top_k": 3})
res2 = r.json().get("results", [])
record(A, "检索图片 OCR 内容", res2 and any("产量表" in x["doc_name"] for x in res2),
       f"top docs={[x['doc_name'] for x in res2]}")
r = admin.post(f"/api/apps/kb/{kb}/search", json={"query": "附件一 盘点作业指导书", "top_k": 3})
res3 = r.json().get("results", [])
record(A, "检索扫描 PDF 内容", res3 and any("扫描件" in x["doc_name"] for x in res3),
       f"top docs={[x['doc_name'] for x in res3]}")

ids = [x["chunk_id"] for x in res[:3]]
text, events = "", 0
with admin.stream("POST", f"/api/apps/kb/{kb}/answer", json={"query": "三号线什么时候检修？", "chunk_ids": ids,
                                                               "max_tokens": 200}, timeout=600) as s:
    code = s.status_code
    for line in s.iter_lines():
        if line.startswith("data:"):
            events += 1
            try:
                ev = json.loads(line[5:])
            except Exception:
                continue
            for ch in ev.get("choices") or []:
                text += (ch.get("delta") or {}).get("content") or ""
record(A, "问答（35B，流式，带引用）", code == 200 and "检修" in text and "[" in text, f"{code} events={events} {text[:120]!r}")

doc = next(x for x in docs if x["name"] == "说明.txt")
r = admin.get(f"/api/apps/kb/{kb}/docs/{doc['id']}/chunks")
record(A, "查看片段", r.status_code == 200 and r.json().get("chunks"), f"{r.status_code} n={len(r.json().get('chunks', []))}")
r = admin.delete(f"/api/apps/kb/{kb}/docs/{doc['id']}")
left = [x["name"] for x in admin.get(f"/api/apps/kb/{kb}/docs").json()["docs"]]
record(A, "删除文档", r.status_code == 200 and "说明.txt" not in left, f"{r.status_code} left={left}")
r = admin.delete(f"/api/apps/kb/{kb}")
record(A, "删除知识库", r.status_code == 200 and all(k["id"] != kb for k in admin.get("/api/apps/kb").json().get("kbs", admin.get("/api/apps/kb").json() if isinstance(admin.get("/api/apps/kb").json(), list) else [])),
       f"{r.status_code}")
