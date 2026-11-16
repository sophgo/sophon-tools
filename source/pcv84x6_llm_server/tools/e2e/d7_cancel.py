"""D7 hypothesis H3: requests cancelled mid-generation (client disconnects) leave the TPU in a
state that later hangs. Mixed load as in the soak, plus two 'cancellers' that open streaming
chat / VL requests and drop the connection after a random 0.5-3 s. Samples TPU and dmesg."""
import base64
import json
import random
import sys
import threading
import time

import httpx

from e2e_common import BASE, INFER_KEY, ROOT, board, stats

DUR = int(sys.argv[1]) if len(sys.argv) > 1 else 540
SEG = sys.argv[2] if len(sys.argv) > 2 else "h3"
stop = time.time() + DUR
b64 = base64.b64encode(open("/home/zzt/workspace/cv84x6-demo-ui/tests/data/ocr/img/table_stats.png", "rb").read()).decode()
H = {"Authorization": f"Bearer {INFER_KEY}"}
log = (ROOT / "d7_req.jsonl").open("a")
lock = threading.Lock()


def note(kind, code, s):
    with lock:
        log.write(json.dumps({"seg": SEG, "kind": kind, "code": code, "s": round(s, 2)}) + "\n")
        log.flush()


def steady(kind, body_fn, path, pause):
    c = httpx.Client(base_url=BASE, headers=H, timeout=600)
    n = 0
    while time.time() < stop:
        n += 1
        t0 = time.time()
        try:
            code = c.post(path, **body_fn(n)).status_code
        except Exception as e:
            code = f"exc:{type(e).__name__}"
        note(kind, code, time.time() - t0)
        time.sleep(pause)


def canceller(kind, body):
    n = 0
    while time.time() < stop:
        n += 1
        t0 = time.time()
        cut = random.uniform(0.5, 3.0)
        try:
            with httpx.Client(base_url=BASE, headers=H, timeout=30) as c:
                with c.stream("POST", "/v1/chat/completions", json=body(n)) as r:
                    for _ in r.iter_lines():
                        if time.time() - t0 > cut:
                            break
            code = "cancelled"
        except Exception as e:
            code = f"exc:{type(e).__name__}"
        note(kind, code, time.time() - t0)
        time.sleep(0.3)


chat_body = lambda n: {"json": {"model": "qwen3.6-35b-a3b-128k", "max_tokens": 128, "messages": [
    {"role": "user", "content": f"第{n}次：用两三句话解释设备巡检。"}]}}
threads = [
    threading.Thread(target=steady, args=("chat", chat_body, "/v1/chat/completions", 0.5)),
    threading.Thread(target=steady, args=("embed", lambda n: {"json": {"model": "qwen3-embedding-0.6b", "input": f"第{n}次"}}, "/v1/embeddings", 2)),
    threading.Thread(target=steady, args=("rerank", lambda n: {"json": {"model": "bge-reranker-v2-m3", "query": "合格率", "documents": ["99%", "无关"]}}, "/v1/rerank", 2)),
    threading.Thread(target=steady, args=("ocr", lambda n: {"json": {"model": "ppocrv6-medium", "image": b64}}, "/v1/ocr", 5)),
    threading.Thread(target=canceller, args=("chat-cancel", lambda n: {"model": "qwen3.6-35b-a3b-128k", "stream": True, "max_tokens": 400,
                                              "messages": [{"role": "user", "content": f"第{n}次：写一篇 300 字的巡检报告。"}]})),
    threading.Thread(target=canceller, args=("vl-cancel", lambda n: {"model": "paddleocr-vl-1.5", "stream": True, "max_tokens": 400,
                                            "messages": [{"role": "user", "content": [
                                                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
                                                {"type": "text", "text": "OCR:"}]}]})),
]
for t in threads:
    t.start()
while time.time() < stop:
    try:
        d = stats()["device"]
        print(time.strftime("%H:%M:%S"), {h["name"]: h["used_bytes"] >> 20 for h in d["device_mem"]["heaps"]},
              d["tpu_usage"]["percent"], d["tpu_usage"]["cores"], flush=True)
    except Exception as e:
        print("stats error", e, flush=True)
    time.sleep(30)
for t in threads:
    t.join()
print("dmesg timeouts:", board("echo __SUDO_PW__ | sudo -S dmesg 2>/dev/null | grep -c 'wait api timeout'").strip().splitlines()[-1])
print("segment done")
