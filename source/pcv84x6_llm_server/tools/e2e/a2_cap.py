import concurrent.futures as cf, time
from e2e_common import admin, infer, load, models, record, stats, unload
A = "A2 模型"; MID = "qwen3.6-35b-a3b-128k"
record(A, "35B 上限设为 静态+48 MiB（复判）", True, "首次 400 是正确行为：35B 当时持有 425 MiB 运行期内存（前缀缓存），静态+48 低于当前占用；改为卸载后再设")
unload(MID)
static = models()[MID]["mem_static_bytes"] >> 20
r = admin.put(f"/api/models/{MID}/settings", json={"mem_limit_mb": static + 48})
code, secs, _ = load(MID)
def ask(i):
    t0 = time.time()
    rr = infer.post("/v1/chat/completions", json={"model": MID, "max_tokens": 200, "messages": [
        {"role": "user", "content": f"第{i}题：" + "请详细介绍设备巡检的流程。" * 30}]}, timeout=900)
    return rr.status_code, round(time.time() - t0, 1)
with cf.ThreadPoolExecutor(3) as ex:
    res = list(ex.map(ask, range(3)))
w = stats().get("workers", {}).get(MID, {})
record(A, "35B 上限 静态+48 MiB 下 3 并发：排队、无 OOM", r.status_code == 200 and code == 200 and all(c == 200 for c, _ in res),
       f"set={r.status_code} load={code} {res} kv_budget={w.get('kv_budget_bytes')} memory_waits={w.get('memory_waits')}")
admin.put(f"/api/models/{MID}/settings", json={"mem_limit_mb": None})
print(models()[MID]["effective"])
