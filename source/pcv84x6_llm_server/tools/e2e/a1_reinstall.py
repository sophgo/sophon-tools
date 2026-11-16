"""Area 1b: uninstall -> fresh install (data kept) -> reboot -> service + autostart agent come back."""
import time

import httpx

from e2e_common import BASE, admin, board, record

A = "A1 安装与升级"
P = "__SUDO_PW__"
pre = {m["id"] for m in admin.get("/api/models").json()["models"]}
nkeys = len(admin.get("/api/keys").json()["keys"])
out = board(f"echo {P} | sudo -S dpkg -r cv84x6-llm-server 2>&1 | tail -3; sleep 3; systemctl is-active cv84x6-llm; "
            "ls /opt/sophgo/cv84x6_llm_server 2>&1 | head -2; ls /data/cv84x6_llm_server/models | wc -l; "
            "ls /data/cv84x6_llm_server/state/state.json; pgrep -f 'app.engine.worker' | wc -l")
record(A, "卸载（dpkg -r）：服务停止、数据目录保留", "inactive" in out or "unknown" in out, out.replace("\n", " | ")[-300:])
out = board(f"echo {P} | sudo -S dpkg -i /data/rc29/cv84x6-llm-server_0.6.29_arm64.deb 2>&1 | tail -2; "
            "for i in $(seq 1 60); do curl -s -o /dev/null -w '%{http_code}' localhost:8000/healthz | grep -q 200 && break; sleep 2; done; "
            "systemctl is-active cv84x6-llm; curl -s localhost:8000/healthz")
time.sleep(3)
post = {m["id"] for m in admin.get("/api/models").json()["models"]}
record(A, "全新安装：服务起来、模型与 key 仍在", '"ok":true' in out and post == pre and len(admin.get("/api/keys").json()["keys"]) == nkeys,
       out.replace("\n", " | ")[-200:] + f" models {len(post)}/{len(pre)} keys={nkeys}")
ag = {a["id"]: a for a in admin.get("/api/agents").json()["agents"]}
record(A, "全新安装：agent 安装与设置保留", all(a.get("installed") for a in ag.values()) and ag["picoclaw"].get("autostart"),
       f"installed={[i for i, a in ag.items() if a.get('installed')]} picoclaw.autostart={ag['picoclaw'].get('autostart')}")

