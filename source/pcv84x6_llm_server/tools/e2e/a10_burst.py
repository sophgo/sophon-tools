"""Area 10b: high-frequency concurrent smoke -- 24 clients (12 chat, 6 embed, 6 rerank) for N seconds."""
import collections
import statistics
import sys
import threading
import time

import httpx

from e2e_common import BASE, INFER_KEY, record, stats

DUR = int(sys.argv[1]) if len(sys.argv) > 1 else 300
A = "A10 稳定性"
res = collections.defaultdict(list)   # kind -> [(code, secs)]
lock = threading.Lock()
stop = time.time() + DUR


def worker(kind: str, i: int):
    c = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {INFER_KEY}"}, timeout=120)
    n = 0
    while time.time() < stop:
        n += 1
        t0 = time.time()
        try:
            if kind == "chat":
                r = c.post("/v1/chat/completions", json={"model": "qwen3.6-35b-a3b-128k", "max_tokens": 16,
                           "messages": [{"role": "user", "content": f"客户端{i}第{n}次：说一个颜色。"}]})
            elif kind == "embed":
                r = c.post("/v1/embeddings", json={"model": "qwen3-embedding-0.6b", "input": f"客户端{i}第{n}次巡检"})
            else:
                r = c.post("/v1/rerank", json={"model": "bge-reranker-v2-m3", "query": "合格率",
                                               "documents": [f"第{n}条：合格率 99%", "无关内容"]})
            code = r.status_code
        except Exception as e:
            code = f"exc:{type(e).__name__}"
        with lock:
            res[kind].append((code, time.time() - t0))
        if code == 429:
            time.sleep(0.5)


ts = [threading.Thread(target=worker, args=(k, i)) for k, n in (("chat", 12), ("embed", 6), ("rerank", 6)) for i in range(n)]
s0 = stats()
for t in ts:
    t.start()
for t in ts:
    t.join()
s1 = stats()
lines = []
ok_all = True
for k, rows in res.items():
    codes = collections.Counter(c for c, _ in rows)
    lat = sorted(s for c, s in rows if c == 200)
    other = {c: n for c, n in codes.items() if c not in (200, 429)}
    ok_all &= not other and codes.get(200, 0) > 0
    p = lambda q: lat[min(len(lat) - 1, int(q * len(lat)))] if lat else None
    lines.append(f"{k}: n={len(rows)} 200={codes.get(200,0)} 429={codes.get(429,0)} other={other} "
                 f"p50={p(.5):.2f}s p95={p(.95):.2f}s max={lat[-1]:.2f}s" if lat else f"{k}: {codes}")
wk = {m: (w or {}).get("pid") for m, w in s1.get("workers", {}).items()}
record(A, f"高频并发冒烟（24 客户端，{DUR}s）", ok_all, " | ".join(lines) + f" | workers alive={len(wk)}")
print("\n".join(lines))
