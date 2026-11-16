"""Area 3b: admission queue and 429 on the 35B (max_concurrent 2, max_queue 1)."""
import concurrent.futures as cf, time
from e2e_common import admin, infer, record
A = "A3 /v1 对话"; MID = "qwen3.6-35b-a3b-128k"
before = admin.get("/api/settings").json()
admin.post("/api/settings", json={"max_queue": 1})
def one(i):
    t0 = time.time()
    r = infer.post("/v1/chat/completions", json={"model": MID, "max_tokens": 120,
        "messages": [{"role": "user", "content": f"第{i}题：写一段 100 字左右的春天描写。"}]})
    return r.status_code, round(time.time() - t0, 1), r.text[:160] if r.status_code != 200 else ""
with cf.ThreadPoolExecutor(6) as ex:
    res = list(ex.map(one, range(6)))
codes = sorted(c for c, _, _ in res)
admin.post("/api/settings", json={"max_queue": before["max_queue"]})
rej = [t for c, _, t in res if c == 429]
record(A, "排队与 429（并发 2 + 队列 1，发 6 个）", codes.count(200) == 3 and codes.count(429) == 3,
       f"codes={codes} times={[s for _, s, _ in res]} 429body={rej[0][:120] if rej else None}")
print("restored max_queue", admin.get("/api/settings").json()["max_queue"], "max_concurrent", before["max_concurrent_per_model"])
