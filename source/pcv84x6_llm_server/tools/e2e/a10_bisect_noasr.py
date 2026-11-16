"""Area 10a: mixed-load soak segment (run several back to back). Appends samples to soak.jsonl and
per-request outcomes to soak_req.jsonl. Load: 2 chat streams, embed, rerank, ocr, VL chat, ASR."""
import base64
import json
import sys
import threading
import time

import httpx

from e2e_common import BASE, INFER_KEY, ROOT, stats

DUR = int(sys.argv[1]) if len(sys.argv) > 1 else 540
SEG = sys.argv[2] if len(sys.argv) > 2 else "s"
stop = time.time() + DUR
IMG = "/home/zzt/workspace/cv84x6-demo-ui/tests/data/ocr/img/"
png = open(IMG + "table_stats.png", "rb").read()
b64 = base64.b64encode(png).decode()
mp3 = (ROOT / "asr_zh.mp3").read_bytes()
lock = threading.Lock()
req_log = (ROOT / "soak_req.jsonl").open("a")


def run(kind, fn, pause):
    c = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {INFER_KEY}"}, timeout=600)
    n = 0
    while time.time() < stop:
        n += 1
        t0 = time.time()
        try:
            code = fn(c, n)
        except Exception as e:
            code = f"exc:{type(e).__name__}"
        with lock:
            req_log.write(json.dumps({"seg": SEG, "kind": kind, "code": code, "s": round(time.time() - t0, 2)}) + "\n")
            req_log.flush()
        time.sleep(pause)


def chat(c, n):
    return c.post("/v1/chat/completions", json={"model": "qwen3.6-35b-a3b-128k", "max_tokens": 128, "messages": [
        {"role": "user", "content": f"第{n}次：用两三句话解释一下什么是设备巡检。"}]}).status_code


def embed(c, n):
    return c.post("/v1/embeddings", json={"model": "qwen3-embedding-0.6b", "input": f"第{n}次巡检记录"}).status_code


def rerank(c, n):
    return c.post("/v1/rerank", json={"model": "bge-reranker-v2-m3", "query": "合格率",
                                      "documents": ["合格率 99%", "无关内容", f"第{n}条"]}).status_code


def ocr(c, n):
    return c.post("/v1/ocr", json={"model": "ppocrv6-medium", "image": b64}).status_code


def vl(c, n):
    return c.post("/v1/chat/completions", json={"model": "paddleocr-vl-1.5", "max_tokens": 256, "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}, {"type": "text", "text": "OCR:"}]}]}).status_code


def asr(c, n):
    return c.post("/v1/audio/transcriptions", data={"model": "qwen3-asr-0.6b"},
                  files={"file": ("a.mp3", mp3, "audio/mpeg")}).status_code


ts = [threading.Thread(target=run, args=a) for a in (
    ("chat", chat, 0.5), ("chat", chat, 0.5), ("embed", embed, 2), ("rerank", rerank, 2),
    ("ocr", ocr, 5), ("vl", vl, 5))]
for t in ts:
    t.start()
samples = (ROOT / "soak.jsonl").open("a")
while time.time() < stop:
    try:
        s = stats()
        d = s["device"]
        row = {"t": time.strftime("%H:%M:%S"), "seg": SEG,
               "heaps": {h["name"]: h["used_bytes"] >> 20 for h in d["device_mem"]["heaps"]},
               "sys_avail_mib": (d["memory"]["available_bytes"] or 0) >> 20,
               "tpu": d["tpu_usage"]["percent"],
               "workers": {m: (w or {}).get("pid") for m, w in s.get("workers", {}).items()}}
    except Exception as e:
        row = {"t": time.strftime("%H:%M:%S"), "seg": SEG, "error": str(e)[:120]}
    samples.write(json.dumps(row) + "\n")
    samples.flush()
    print(row.get("t"), row.get("heaps"), row.get("sys_avail_mib"), row.get("tpu"), len(row.get("workers", {})), flush=True)
    time.sleep(30)
for t in ts:
    t.join()
print("segment done")
