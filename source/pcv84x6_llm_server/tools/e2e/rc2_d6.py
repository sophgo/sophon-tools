import time
from e2e_common import board, load, models, record
P = "__SUDO_PW__"
load("qwen3-embedding-0.6b")
pid = models()["qwen3-embedding-0.6b"]["pid"]
out = board(f"MAIN=$(systemctl show cv84x6-llm -p ExecMainPID --value); echo {P} | sudo -S kill -9 $MAIN; sleep 2; ps -p {pid} -o pid= || echo GONE; "
            "for i in $(seq 1 60); do curl -s -o /dev/null -w '%{http_code}' localhost:8000/healthz | grep -q 200 && break; sleep 2; done; echo restarted")
time.sleep(4)
m = models()["qwen3-embedding-0.6b"]
record("RC2 复测", "D6 主进程崩溃（kill -9，worker 空闲）→ worker 存活并被接管", "GONE" not in out and m["loaded"] and m.get("adopted") and m["pid"] == pid,
       f"worker pid={pid} 崩溃后 {'存活' if 'GONE' not in out else '消失'}；重启后 loaded={m['loaded']} adopted={m.get('adopted')} pid={m['pid']}")
out = board(f"echo {P} | sudo -S systemctl restart cv84x6-llm; sleep 1; ps -p {pid} -o pid= || echo GONE; "
            "for i in $(seq 1 60); do curl -s -o /dev/null -w '%{http_code}' localhost:8000/healthz | grep -q 200 && break; sleep 2; done; "
            "tail -3 /data/cv84x6_llm_server/state/logs/worker-qwen3-embedding-0.6b.log")
time.sleep(3)
m = models()["qwen3-embedding-0.6b"]
record("RC2 复测", "D6 systemctl restart → worker 优雅卸载（非 SIGKILL）", "GONE" in out and "stopped cleanly" in out and not m["loaded"],
       f"{out.strip().splitlines()[-1][:120] if out.strip() else ''}; 重启后 loaded={m['loaded']}")
