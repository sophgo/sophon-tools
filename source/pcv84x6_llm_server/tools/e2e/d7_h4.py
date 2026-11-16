"""D7 hypothesis H4: kill -9 of the service while the 35B is generating, then sustained load."""
import threading
import time

import httpx

from e2e_common import BASE, INFER_KEY, board, models, record

P = "__SUDO_PW__"
pid35 = models()["qwen3.6-35b-a3b-128k"]["pid"]
got = {}


def gen():
    try:
        with httpx.stream("POST", f"{BASE}/v1/chat/completions", headers={"Authorization": f"Bearer {INFER_KEY}"},
                          json={"model": "qwen3.6-35b-a3b-128k", "stream": True, "max_tokens": 600,
                                "messages": [{"role": "user", "content": "写一篇 500 字的设备巡检制度。"}]}, timeout=120) as r:
            for _ in r.iter_lines():
                got["n"] = got.get("n", 0) + 1
    except Exception as e:
        got["err"] = type(e).__name__


t = threading.Thread(target=gen)
t.start()
time.sleep(6)  # mid-generation
out = board(f"cat /sys/class/bm-tpu/bm-tpu0/device/npu_usage | head -1; MAIN=$(systemctl show cv84x6-llm -p ExecMainPID --value); "
            f"echo {P} | sudo -S kill -9 $MAIN; sleep 2; ps -p {pid35} -o pid= || echo GONE; "
            "for i in $(seq 1 60); do curl -s -o /dev/null -w '%{http_code}' localhost:8000/healthz | grep -q 200 && break; sleep 2; done; "
            f"sleep 20; echo {P} | sudo -S dmesg 2>/dev/null | grep -c 'wait api timeout'")
t.join(timeout=60)
time.sleep(3)
m = models()["qwen3.6-35b-a3b-128k"]
print(out)
record("D7 实验", "H4 前置：35B 生成中 kill -9 主进程 → worker 存活并被接管", m["loaded"] and m.get("adopted") and m["pid"] == pid35,
       f"生成了 {got.get('n')} 个 SSE 事件后中断（{got.get('err')}）；{out.strip().splitlines()[0][:40]}；35B pid {pid35}→{m['pid']} adopted={m.get('adopted')}；dmesg timeout={out.strip().splitlines()[-1]}")
r = httpx.post(f"{BASE}/v1/chat/completions", headers={"Authorization": f"Bearer {INFER_KEY}"},
               json={"model": "qwen3.6-35b-a3b-128k", "max_tokens": 16, "messages": [{"role": "user", "content": "你好"}]}, timeout=300)
print("post-takeover chat", r.status_code, r.text[:120])
