"""Area 2c: per-model memory cap (queue, not OOM) and per-model idle unload / on-demand load."""
import concurrent.futures as cf
import time

from e2e_common import admin, infer, models, record, stats

A = "A2 模型"
MID = "qwen3.6-35b-a3b-128k"
# global idle was set to 10 min / auto-load on before the upgrade; make it the shipped default for this test
admin.post("/api/settings", json={"aux_idle_unload_min": 0, "aux_auto_load": False})

m = models()[MID]
static = m["mem_static_bytes"] >> 20
r = admin.put(f"/api/models/{MID}/settings", json={"mem_limit_mb": static + 48})
record(A, "35B 内存上限设为 静态+48 MiB", r.status_code == 200, f"{r.status_code} static={static} applied={r.json().get('applied')}")


def ask(i):
    t0 = time.time()
    rr = infer.post("/v1/chat/completions", json={"model": MID, "max_tokens": 200, "messages": [
        {"role": "user", "content": f"第{i}题：" + "请详细介绍设备巡检的流程。" * 30}]}, timeout=600)
    return rr.status_code, round(time.time() - t0, 1)


with cf.ThreadPoolExecutor(3) as ex:
    res = list(ex.map(ask, range(3)))
w = stats().get("workers", {}).get(MID, {})
record(A, "小上限下 3 并发：排队而非 OOM", all(c == 200 for c, _ in res),
       f"{res} memory_waits={w.get('memory_waits')} kv_budget={w.get('kv_budget_bytes')}")
r = admin.put(f"/api/models/{MID}/settings", json={"mem_limit_mb": 1024})
record(A, "上限改到低于当前占用 → 400", r.status_code == 400, f"{r.status_code} {r.text[:140]}")
admin.put(f"/api/models/{MID}/settings", json={"mem_limit_mb": None})

# per-model idle: reranker 1 min + auto-load; embedding untouched (global default now off)
admin.put("/api/models/bge-reranker-v2-m3/settings", json={"idle_unload_min": 1, "auto_load": True})
t0 = time.time()
gone = None
while time.time() - t0 < 200:
    ms = models()
    if not ms["bge-reranker-v2-m3"]["loaded"]:
        gone = time.time() - t0
        break
    time.sleep(5)
ms = models()
record(A, "按模型空闲卸载（Reranker 1 分钟，Embedding 不设）",
       gone is not None and ms["qwen3-embedding-0.6b"]["loaded"] and ms["bge-reranker-v2-m3"].get("unloaded_reason") == "idle",
       f"reranker unloaded after {gone and round(gone)}s, embedding loaded={ms['qwen3-embedding-0.6b']['loaded']}")
t0 = time.time()
r = infer.post("/v1/rerank", json={"model": "bge-reranker-v2-m3", "query": "合格率", "documents": ["合格率 99%", "无关"]})
record(A, "按模型按需加载（Reranker 卸载后直接请求）", r.status_code == 200, f"{r.status_code} {time.time() - t0:.1f}s")
r = infer.post("/v1/embeddings", json={"model": "qwen3-asr-0.6b", "input": "x"})
admin.put("/api/models/bge-reranker-v2-m3/settings", json={"idle_unload_min": None, "auto_load": None})
print("settings restored")
