import json
from e2e_common import admin
_r = admin.post("/api/apps/kb", json={"name": "e2e-probe"}).json(); print(_r); kb = _r.get("id") or _r.get("kb", {}).get("id")
admin.post(f"/api/apps/kb/{kb}/docs", files=[("files", ("说明.txt", "三号线下月停产检修。".encode(), "text/plain"))])
import time
for _ in range(40):
    d = admin.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
    if d and d[0]["status"] == "ready": break
    time.sleep(2)
ids = [x["chunk_id"] for x in admin.post(f"/api/apps/kb/{kb}/search", json={"query": "检修", "top_k": 1}).json()["results"]]
with admin.stream("POST", f"/api/apps/kb/{kb}/answer", json={"query": "三号线什么时候检修？", "chunk_ids": ids, "max_tokens": 120}, timeout=600) as s:
    for line in s.iter_lines():
        if line.strip(): print(line[:200])
admin.delete(f"/api/apps/kb/{kb}")
