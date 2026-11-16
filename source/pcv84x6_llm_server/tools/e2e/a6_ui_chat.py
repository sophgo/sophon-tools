"""Area 6c: chat in each embedded agent page (console proxy) with a question only the cv84x6 MCP can answer."""
import sys
import time

from playwright.sync_api import sync_playwright

from e2e_common import BASE, record

Q = "用 cv84x6 提供的知识库工具查一下：设备上有几个知识库，分别叫什么？用一句话回答。"
agents = sys.argv[1:] or ["dsh", "picoclaw", "openclaw"]
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for aid in agents:
        p = b.new_page(viewport={"width": 1440, "height": 1000})
        p.goto(BASE)
        p.fill("[data-testid=login-password]", "admin")
        p.click("[data-testid=login-submit]")
        p.wait_for_timeout(1000)
        from e2e_common import admin
        ainfo = next(x for x in admin.get("/api/agents").json()["agents"] if x["id"] == aid)
        p.goto(BASE + (ainfo.get("web_url") or f"/agents/{aid}/"))
        p.wait_for_timeout(8000)
        pw_box = p.locator("input[type=password]")
        if pw_box.count() and pw_box.first.is_visible() and (ainfo.get("web") or {}).get("password"):
            pw_box.first.fill(ainfo["web"]["password"])
            p.keyboard.press("Enter")
            p.wait_for_timeout(12000)
        for name in ("Continue", "继续", "Got it", "OK", "Close", "关闭", "Skip tour"):
            btn = p.get_by_role("button", name=name)
            if not btn.count():
                btn = p.get_by_text(name, exact=True)
            if btn.count() and btn.first.is_visible():
                btn.first.click()
                p.wait_for_timeout(1500)
        box = None
        for sel in ("textarea", "[contenteditable=true]", "input[type=text]"):
            loc = p.locator(sel)
            if loc.count():
                for i in range(loc.count()):
                    if loc.nth(i).is_visible():
                        box = loc.nth(i)
                        break
            if box:
                break
        if box is None:
            p.screenshot(path=f"/home/zzt/workspace/cv84x6-e2e/shots/agent-{aid}-nobox.png")
            record("A6 Agent", f"{aid} 内嵌页面对话 + MCP", None, "找不到输入框（截图 agent-%s-nobox.png）" % aid)
            p.close()
            continue
        box.click()
        box.fill(Q) if box.evaluate("e => e.tagName") in ("TEXTAREA", "INPUT") else box.type(Q)
        p.keyboard.press("Enter")
        t0 = time.time()
        found = False
        while time.time() - t0 < 600:
            body = p.inner_text("body")
            if "e2e-mcp" in body and body.count("e2e-mcp") >= 1 and ("个知识库" in body.split(Q)[-1] if Q in body else True):
                found = True
                break
            p.wait_for_timeout(5000)
        p.wait_for_timeout(2000)
        p.screenshot(path=f"/home/zzt/workspace/cv84x6-e2e/shots/agent-{aid}-chat.png")
        tail = p.inner_text("body")[-300:].replace("\n", " ")
        record("A6 Agent", f"{aid} 内嵌页面对话 + MCP（kb_list）", found, f"{time.time() - t0:.0f}s tail={tail[-160:]!r}")
        p.close()
    b.close()
