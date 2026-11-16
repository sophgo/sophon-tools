"""Area 3c: embeddings / rerank / transcriptions (+ stream) / ocr lines+layout, co-loaded with the 35B."""
import base64
import json

from openai import OpenAI

from e2e_common import BASE, INFER_KEY, ROOT, admin, heaps, infer, load, models, record

A = "A3 /v1 辅助"
IMG = "/home/zzt/workspace/cv84x6-demo-ui/tests/data/ocr/img/"
cli = OpenAI(base_url=f"{BASE}/v1", api_key=INFER_KEY, timeout=600, max_retries=0)

for mid in ("qwen3.6-35b-a3b-128k", "qwen3-embedding-0.6b", "bge-reranker-v2-m3", "qwen3-asr-0.6b", "ppocrv6-medium"):
    if not models()[mid]["loaded"]:
        code, secs, body = load(mid)
        if code != 200:
            record("A2 模型", f"同时加载 {mid}", False, f"{code} {body}")
record("A2 模型", "35B + 4 个辅助模型同时在线", all(models()[m]["loaded"] for m in (
    "qwen3.6-35b-a3b-128k", "qwen3-embedding-0.6b", "bge-reranker-v2-m3", "qwen3-asr-0.6b", "ppocrv6-medium")),
    f"heaps MiB {heaps()}")

# embeddings via SDK, batch + dimensions (MRL)
e = cli.embeddings.create(model="qwen3-embedding-0.6b", input=["巡检规范", "合格率", "温度过高告警"])
record(A, "embeddings（SDK，批量 3 条）", len(e.data) == 3 and len(e.data[0].embedding) == 1024 and e.usage.prompt_tokens > 0,
       f"n={len(e.data)} dim={len(e.data[0].embedding)} usage={e.usage.prompt_tokens}")
r = infer.post("/v1/embeddings", json={"model": "qwen3-embedding-0.6b", "input": "巡检规范", "dimensions": 256})
dim = len(r.json()["data"][0]["embedding"]) if r.status_code == 200 else None
record(A, "embeddings dimensions=256", r.status_code == 200 and dim == 256, f"{r.status_code} dim={dim} {r.text[:100] if r.status_code != 200 else ''}")
r = infer.post("/v1/embeddings", json={"model": "qwen3-embedding-0.6b", "input": "x", "encoding_format": "base64"})
ok = r.status_code == 200 and isinstance(r.json()["data"][0]["embedding"], str)
record(A, "embeddings encoding_format=base64", ok, f"{r.status_code} type={type(r.json()['data'][0]['embedding']).__name__ if r.status_code == 200 else r.text[:80]}")

# rerank: top_n + return_documents
docs = ["二号线合格率 99.1%", "今天天气晴朗", "一号线产量 4120 台，合格率 99.6%", "食堂菜单"]
r = infer.post("/v1/rerank", json={"model": "bge-reranker-v2-m3", "query": "哪条产线合格率最高", "documents": docs,
                                   "top_n": 2, "return_documents": False})
d = r.json()
res = d.get("results", [])
record(A, "rerank top_n=2", r.status_code == 200 and len(res) == 2 and {x["index"] for x in res} <= {0, 2},
       f"{r.status_code} {[(x['index'], round(x['relevance_score'], 3)) for x in res]}")

# transcriptions: json / text / verbose_json
for fmt in ("json", "text", "verbose_json"):
    with open(ROOT / "asr_zh.mp3", "rb") as f:
        r = infer.post("/v1/audio/transcriptions", data={"model": "qwen3-asr-0.6b", "response_format": fmt},
                       files={"file": ("asr_zh.mp3", f, "audio/mpeg")})
    body = r.text
    ok = r.status_code == 200 and "停滞" in body
    if fmt == "verbose_json" and ok:
        ok = "segments" in r.json()
    record(A, f"transcriptions response_format={fmt}", ok, f"{r.status_code} {body[:100]!r}")
# SDK
with open(ROOT / "asr_zh.mp3", "rb") as f:
    t = cli.audio.transcriptions.create(model="qwen3-asr-0.6b", file=f)
record(A, "transcriptions（SDK）", "停滞" in t.text, f"{t.text!r}")
# long audio (95 s, chunked)
with open(ROOT / "long95.wav", "rb") as f:
    r = infer.post("/v1/audio/transcriptions", data={"model": "qwen3-asr-0.6b", "response_format": "verbose_json"},
                   files={"file": ("long95.wav", f, "audio/wav")}, timeout=900)
d = r.json() if r.status_code == 200 else {}
record(A, "transcriptions 95 秒长音频", r.status_code == 200 and len(d.get("segments", [])) >= 3,
       f"{r.status_code} duration={d.get('duration')} segments={len(d.get('segments', []))} text={d.get('text', '')[:40]!r}")
# streaming (console app endpoint, SSE)
with open(ROOT / "long95.wav", "rb") as f:
    with admin.stream("POST", "/api/apps/asr/transcriptions/stream", data={"model": "qwen3-asr-0.6b"},
                      files={"file": ("long95.wav", f, "audio/wav")}, timeout=900) as s:
        events = [l for l in s.iter_lines() if l.startswith("data:") or l.startswith("event:")]
        code = s.status_code
segs = [e for e in events if '"segment"' in e or "segment" in e]
record(A, "ASR 流式转写（SSE）", code == 200 and len(events) >= 4, f"{code} events={len(events)} first={events[0][:80] if events else None} last={events[-1][:80] if events else None}")

# OCR lines + layout
b64 = base64.b64encode(open(IMG + "cn_notice.png", "rb").read()).decode()
r = infer.post("/v1/ocr", json={"model": "ppocrv6-medium", "image": b64, "return_boxes": True})
d = r.json()
record(A, "/v1/ocr lines", r.status_code == 200 and len(d["lines"]) > 5 and d["lines"][0].get("box"),
       f"{r.status_code} lines={len(d['lines'])} usage={d['usage']}")
for img in ("twocolumn.png", "table_stats.png"):
    b64 = base64.b64encode(open(IMG + img, "rb").read()).decode()
    r = infer.post("/v1/ocr", json={"model": "ppocrv6-medium", "image": b64, "mode": "layout"})
    d = r.json()
    record(A, f"/v1/ocr layout {img}", r.status_code == 200 and d.get("mode") == "layout" and len(d.get("blocks", [])) > 1,
           f"{r.status_code} blocks={[(b['type']) for b in d.get('blocks', [])]} usage={d.get('usage')}")
# multipart form + mode
with open(IMG + "en_report.png", "rb") as f:
    r = infer.post("/v1/ocr", data={"model": "ppocrv6-medium", "mode": "layout"}, files={"file": ("en_report.png", f, "image/png")})
record(A, "/v1/ocr multipart + layout", r.status_code == 200 and r.json().get("mode") == "layout", f"{r.status_code} blocks={len(r.json().get('blocks', [])) if r.status_code == 200 else r.text[:80]}")
r = infer.post("/v1/ocr", json={"model": "ppocrv6-medium", "image": "bm90IGFuIGltYWdl"})
record(A, "/v1/ocr 坏图片 400", r.status_code == 400, f"{r.status_code} {r.text[:120]}")
