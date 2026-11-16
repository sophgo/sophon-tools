import base64, httpx
from e2e_common import BASE, INFER_KEY, admin, load, record, unload
H = {"Authorization": f"Bearer {INFER_KEY}"}
A = "最终包冒烟"
ok = all(load(m)[0] == 200 for m in ("qwen3-embedding-0.6b", "bge-reranker-v2-m3", "ppocrv6-medium", "paddleocr-vl-1.5"))
r1 = httpx.post(f"{BASE}/v1/embeddings", headers=H, json={"model": "qwen3-embedding-0.6b", "input": "巡检"}, timeout=120)
r2 = httpx.post(f"{BASE}/v1/rerank", headers=H, json={"model": "bge-reranker-v2-m3", "query": "合格率", "documents": ["99%", "无关"]}, timeout=120)
b64 = base64.b64encode(open("/home/zzt/workspace/cv84x6-demo-ui/tests/data/ocr/img/cn_table_merged.png", "rb").read()).decode()
r3 = httpx.post(f"{BASE}/v1/ocr", headers=H, json={"model": "ppocrv6-medium", "image": b64, "mode": "vl"}, timeout=600)
r4 = httpx.post(f"{BASE}/v1/chat/completions", headers=H, json={"model": "not-loaded", "messages": [{"role": "user", "content": "x"}]}, timeout=60)
record(A, "加载 4 个模型 + embeddings / rerank / OCR vl 模式 / OpenAI 错误格式", ok and r1.status_code == 200 and r2.status_code == 200
       and r3.status_code == 200 and "rowspan" in r3.json().get("text", "") and "error" in r4.json(),
       f"embed {r1.status_code} rerank {r2.status_code} ocr-vl {r3.status_code} rowspan={'rowspan' in r3.text} 404-shape={list(r4.json())}")
for m in ("qwen3-embedding-0.6b", "bge-reranker-v2-m3", "ppocrv6-medium", "paddleocr-vl-1.5"):
    unload(m)
