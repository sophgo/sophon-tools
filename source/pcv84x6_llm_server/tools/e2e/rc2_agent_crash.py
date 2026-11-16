import time
from e2e_common import admin, board, record
P = "__SUDO_PW__"
before = next(a for a in admin.get("/api/agents").json()["agents"] if a["id"] == "picoclaw")
out = board(f"MAIN=$(systemctl show cv84x6-llm -p ExecMainPID --value); echo {P} | sudo -S kill -9 $MAIN; sleep 2; ps -p {before['pid']} -o pid= || echo GONE; "
            "for i in $(seq 1 60); do curl -s -o /dev/null -w '%{http_code}' localhost:8000/healthz | grep -q 200 && break; sleep 2; done")
time.sleep(5)
after = next(a for a in admin.get("/api/agents").json()["agents"] if a["id"] == "picoclaw")
record("RC2 复测", "D6 主进程崩溃时 agent 存活并被接管（picoclaw）", "GONE" not in out and after.get("running") and after.get("pid") == before["pid"] and after.get("adopted"),
       f"pid {before['pid']} → {after.get('pid')} running={after.get('running')} adopted={after.get('adopted')}")
