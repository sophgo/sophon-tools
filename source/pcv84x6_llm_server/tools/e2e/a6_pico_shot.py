from playwright.sync_api import sync_playwright
from e2e_common import BASE, admin
a = next(x for x in admin.get("/api/agents").json()["agents"] if x["id"] == "picoclaw")
with sync_playwright() as pw:
    b = pw.chromium.launch(); p = b.new_page(viewport={"width": 1440, "height": 1000})
    p.goto(BASE); p.fill("[data-testid=login-password]", "admin"); p.click("[data-testid=login-submit]"); p.wait_for_timeout(1000)
    p.goto(BASE + a["web_url"]); p.wait_for_timeout(5000)
    p.locator("input[type=password]").first.fill(a["web"]["password"]); p.keyboard.press("Enter"); p.wait_for_timeout(12000)
    p.screenshot(path="/home/zzt/workspace/cv84x6-e2e/shots/agent-picoclaw-overlay.png")
    print([ (d.inner_text()[:150]) for d in p.locator("[role=dialog]").all()])
    b.close()
