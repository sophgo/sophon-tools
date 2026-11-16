"""Area 9: walk every console page on the real board (via tunnel), desktop light + phone dark.
Collect console errors, failed /api requests and horizontal overflow; screenshot each page."""
import json
import os
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e2e_common import BASE, ROOT, record  # noqa: E402

PAGES = ["overview", "models", "agents", "playground", "apps", "keys", "records", "logs", "settings", "docs"]
OUT = ROOT / "shots"
problems = []
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for theme, w, h in (("light", 1440, 1000), ("dark", 390, 1600)):
        ctx = b.new_context(viewport={"width": w, "height": h})
        p = ctx.new_page()
        errs, bad = [], []
        p.on("console", lambda m: errs.append(m.text[:200]) if m.type == "error" else None)
        p.on("response", lambda r: bad.append(f"{r.status} {r.request.method} {r.url.replace(BASE, '')}")
             if r.status >= 400 and "/api/" in r.url else None)
        p.goto(BASE)
        p.fill("[data-testid=login-password]", "admin")
        p.click("[data-testid=login-submit]")
        p.wait_for_timeout(1500)
        p.click(f"[data-testid=theme-{theme}]")
        for pg in PAGES:
            errs.clear(); bad.clear()
            p.click(f"[data-testid=nav-{pg}]")
            p.wait_for_timeout(2500)
            sw = p.evaluate("document.documentElement.scrollWidth")
            iw = p.evaluate("window.innerWidth")
            p.screenshot(path=str(OUT / f"{pg}-{theme}.png"), full_page=True)
            ok = not errs and not bad and sw <= iw
            if not ok:
                problems.append({"page": pg, "theme": theme, "errors": errs[:3], "http": bad[:5], "overflow": sw > iw})
            record("A9 控制台", f"{pg}（{'桌面亮' if theme == 'light' else '手机暗'}）", ok,
                   f"console_errors={len(errs)} api_errors={bad[:3]} scrollWidth={sw}/{iw}")
        ctx.close()
    b.close()
print(json.dumps(problems, ensure_ascii=False, indent=1))
