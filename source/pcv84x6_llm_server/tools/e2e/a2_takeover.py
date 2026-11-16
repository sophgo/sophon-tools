import time
from e2e_common import board, infer, models, record
A = "A2 模型"
before = {m: (v["pid"], v["loaded"]) for m, v in models().items() if v["loaded"]}
out = board("echo __SUDO_PW__ | sudo -S systemctl restart cv84x6-llm; for i in $(seq 1 60); do curl -s -o /dev/null -w '%{http_code}' localhost:8000/healthz | grep -q 200 && break; sleep 2; done; curl -s localhost:8000/healthz")
time.sleep(3)
after = {m: (v["pid"], v["loaded"], v.get("adopted")) for m, v in models().items() if v["loaded"]}
same = all(after.get(m, (None,))[0] == pid for m, (pid, _) in before.items())
r = infer.post("/v1/chat/completions", json={"model": "qwen3.6-35b-a3b-128k", "max_tokens": 16, "messages": [{"role": "user", "content": "你好"}]})
record(A, "服务重启后接管运行中的 worker（不重新加载）", same and len(after) == len(before) and r.status_code == 200,
       f"health={out.strip()[-60:]} before={ {m: p for m, (p, _) in before.items()} } adopted={ {m: a for m, (_, _, a) in after.items()} } chat={r.status_code}")
