import time
from e2e_common import board, load, models, record
A = "A2 模型"
code, secs, _ = load("qwen3-embedding-0.6b")
pid = models()["qwen3-embedding-0.6b"]["pid"]
time.sleep(2)
out = board(f"MAIN=$(systemctl show cv84x6-llm -p ExecMainPID --value); echo main=$MAIN worker={pid}; echo __SUDO_PW__ | sudo -S kill -9 $MAIN; sleep 1; "
            f"ps -p {pid} -o pid,stat,cmd --no-headers || echo worker_gone_1s; sleep 9; ps -p {pid} -o pid,stat --no-headers || echo worker_gone_10s; "
            "for i in $(seq 1 40); do curl -s -o /dev/null -w '%{http_code}' localhost:8000/healthz | grep -q 200 && break; sleep 2; done; "
            "systemctl show cv84x6-llm -p ExecMainPID -p NRestarts --value | tr '\\n' ' '")
time.sleep(3)
m = models()["qwen3-embedding-0.6b"]
record(A, "服务进程崩溃（kill -9 主进程，worker 空闲）后接管", m["loaded"] and m.get("adopted") and m["pid"] == pid,
       f"{out.strip()[-260:]} | after: loaded={m['loaded']} adopted={m.get('adopted')} pid={m['pid']} conflict={m.get('conflict')}")
