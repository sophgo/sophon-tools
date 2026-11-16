#!/usr/bin/env python3
"""Full-page screenshots of every console page, for a light/dark × width matrix.

Runs against web/acceptance/mock_server.py, so nothing touches the NPU.

    python3 shots.py --base http://127.0.0.1:8802 --out ./shots-before
    python3 shots.py --base http://127.0.0.1:8802 --out ./shots-after --only overview,models
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = ["overview", "models", "agents", "playground", "keys", "settings", "docs"]
WIDTHS = {"desktop": (1440, 1000), "laptop": (1024, 800), "phone": (390, 844)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8802")
    ap.add_argument("--out", default="./shots")
    ap.add_argument("--password", default="admin")
    ap.add_argument("--only", default="")
    ap.add_argument("--themes", default="light,dark")
    ap.add_argument("--widths", default=",".join(WIDTHS))
    args = ap.parse_args()

    pages = [p.strip() for p in args.only.split(",") if p.strip()] or PAGES
    themes = [t.strip() for t in args.themes.split(",") if t.strip()]
    width_sel = [w.strip() for w in args.widths.split(",") if w.strip()]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for wname in width_sel:
            w, h = WIDTHS[wname]
            for theme in themes:
                ctx = browser.new_context(viewport={"width": w, "height": h})
                page = ctx.new_page()
                page.on("console", lambda m: errors.append(f"console:{m.text}") if m.type() == "error" else None)
                page.on("pageerror", lambda e: errors.append(f"pageerror:{e}"))
                page.goto(args.base, wait_until="networkidle")
                page.screenshot(path=str(out / f"00-login-{wname}-{theme}.png"))
                page.fill('[data-testid="login-password"]', args.password)
                page.click('[data-testid="login-submit"]')
                page.wait_for_selector('[data-testid="nav"]')
                page.evaluate(
                    "t => { localStorage.setItem('cv84x6.theme', t);"
                    "document.documentElement.setAttribute('data-theme', t);"
                    "document.documentElement.style.colorScheme = t; }",
                    theme,
                )
                for p in pages:
                    page.click(f'[data-testid="nav-{p}"]')
                    page.wait_for_timeout(1800)
                    page.evaluate("window.scrollTo(0, 0)")
                    page.wait_for_timeout(150)
                    page.screenshot(path=str(out / f"{p}-{wname}-{theme}.png"), full_page=True)
                    m = page.evaluate(
                        "() => ({s: document.documentElement.scrollWidth,"
                        " c: document.documentElement.clientWidth})"
                    )
                    if m["s"] > m["c"] + 1:
                        errors.append(f"overflow {p} {wname} {theme}: {m['s']} > {m['c']}")
                ctx.close()
        browser.close()

    print(f"screenshots in {out}")
    if errors:
        print("ISSUES:")
        for e in errors:
            print("  " + e)
        return 1
    print("no console errors, no horizontal overflow")
    return 0


if __name__ == "__main__":
    sys.exit(main())
