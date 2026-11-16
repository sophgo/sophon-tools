"""Area 6a: agent lifecycle -- start, health, RSS, embedded page via console, restart, stop."""
import time

from playwright.sync_api import sync_playwright

from e2e_common import BASE, admin, board, load, models, record

A = "A6 Agent"
if not models()["qwen3.6-35b-a3b-128k"]["loaded"]:
    load("qwen3.6-35b-a3b-128k")
for _ in range(60):
    ag = {a["id"]: a for a in admin.get("/api/agents").json()["agents"]}
    if all(a.get("installed") for a in ag.values()):
        break
    time.sleep(5)
record(A, "4 个 agent 离线安装（安装包从 dfss 下载）", all(a.get("installed") for a in ag.values()),
       "; ".join(f"{i}={a.get('version')}" for i, a in ag.items()))


def wait(aid, running, secs=180):
    t0 = time.time()
    while time.time() - t0 < secs:
        a = next(x for x in admin.get("/api/agents").json()["agents"] if x["id"] == aid)
        if bool(a.get("running")) == running and not a.get("operation"):
            return a, time.time() - t0
        time.sleep(3)
    return a, time.time() - t0


for aid in ("dsh", "picoclaw", "opencode", "openclaw"):
    r = admin.post(f"/api/agents/{aid}/start")
    a, dt = wait(aid, True)
    rss = a.get("rss_bytes") or (a.get("memory") or {}).get("rss_bytes")
    record(A, f"{aid} 启动", r.status_code in (200, 202) and a.get("running"),
           f"{r.status_code} {dt:.0f}s port={a.get('port')} rss={rss and rss >> 20} MiB err={a.get('last_error','')[:80]}")

with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page(viewport={"width": 1440, "height": 1000})
    p.goto(BASE)
    p.fill("[data-testid=login-password]", "admin")
    p.click("[data-testid=login-submit]")
    p.wait_for_timeout(1000)
    for aid in ("dsh", "picoclaw", "opencode", "openclaw"):
        a = next(x for x in admin.get("/api/agents").json()["agents"] if x["id"] == aid)
        url = a.get("url") or a.get("open_url") or (f"/agents/{aid}/" if a.get("proxied") else None)
        errs = []
        p.on("pageerror", lambda e: errs.append(str(e)[:120]))
        if url and url.startswith("/"):
            resp = p.goto(BASE + url)
            p.wait_for_timeout(6000)
            title = p.title()
            p.screenshot(path=f"/home/zzt/workspace/cv84x6-e2e/shots/agent-{aid}.png")
            record(A, f"{aid} 内嵌页面（同源代理 {url}）", resp is not None and resp.status < 400 and title != "",
                   f"status={resp.status if resp else None} title={title!r} pageerrors={errs[:2]}")
        else:
            out = board(f"curl -s -o /dev/null -w '%{{http_code}}' localhost:{a.get('port')}/")
            record(A, f"{aid} 页面（直连端口 {a.get('port')}）", out.strip().endswith(("200", "302", "401")), f"board curl={out.strip()[-10:]} url={url}")
    b.close()

for aid in ("picoclaw",):
    r = admin.post(f"/api/agents/{aid}/restart")
    a, dt = wait(aid, True)
    record(A, f"{aid} 重启", r.status_code in (200, 202) and a.get("running"), f"{r.status_code} {dt:.0f}s")
