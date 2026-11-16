from playwright.sync_api import sync_playwright
from e2e_common import BASE, admin
a = next(x for x in admin.get("/api/agents").json()["agents"] if x["id"] == "picoclaw")
print("web", {k: (v if k != "password" else "***") for k, v in (a.get("web") or {}).items()}, a.get("web_url"))
with sync_playwright() as pw:
    b = pw.chromium.launch(); p = b.new_page(viewport={"width": 1440, "height": 1000})
    logs = []
    p.on("console", lambda m: logs.append(f"console.{m.type}: {m.text[:160]}"))
    p.on("pageerror", lambda e: logs.append(f"pageerror: {str(e)[:200]}"))
    p.on("response", lambda r: logs.append(f"{r.status} {r.request.method} {r.url.replace(BASE,'')[:100]}") if r.status >= 400 or "picoclaw" in r.url and r.request.resource_type in ("document","xhr","fetch","websocket") else None)
    p.goto(BASE); p.fill("[data-testid=login-password]", "admin"); p.click("[data-testid=login-submit]"); p.wait_for_timeout(1000)
    p.goto(BASE + a["web_url"]); p.wait_for_timeout(6000)
    pwb = p.locator("input[type=password]")
    print("password box visible:", pwb.count() and pwb.first.is_visible())
    if pwb.count():
        pwb.first.fill(a["web"]["password"]); p.keyboard.press("Enter"); p.wait_for_timeout(8000)
    print("url after login:", p.url, "title:", p.title())
    print("body text:", p.inner_text("body")[:200].replace("\n", " | "))
    p.screenshot(path="/home/zzt/workspace/cv84x6-e2e/shots/agent-picoclaw-probe.png")
    print("\n".join(logs[-25:]))
    b.close()
