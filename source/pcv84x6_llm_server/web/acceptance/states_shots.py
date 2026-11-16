#!/usr/bin/env python3
"""Screenshot + contrast the states that only exist once something is loaded.

The plain page sweep never renders a model card's 在线 pill, the chat workspace,
an agent's running controls, or a fresh API key — and those are where the accent
fill appears as a button background, which is exactly the pairing that has to
clear 4.5:1. So this drives the mock through those states and captures them.

Read-only with respect to the NPU: it loads *mock* models, never 10.42.

    python3 web/acceptance/states_shots.py --base http://127.0.0.1:8802 --out ./states
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT_DEFAULT = "./states"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8802")
    ap.add_argument("--password", default="admin")
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=1000)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    shots: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        def new_page():
            ctx = browser.new_context(viewport={"width": a.width, "height": a.height})
            page = ctx.new_page()
            page.on("console", lambda m: errors.append(f"console: {m.text}")
                    if m.type() == "error" else None)
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.goto(a.base, wait_until="networkidle")
            page.fill('[data-testid="login-password"]', a.password)
            page.click('[data-testid="login-submit"]')
            page.wait_for_selector('[data-testid="nav"]')
            return page

        # -- load both mock models through the API --------------------------
        page = new_page()
        loaded = page.evaluate(
            """async () => {
                 const r = await fetch('/api/models');
                 const j = await r.json();
                 const out = [];
                 for (const m of j.models) {
                   const resp = await fetch(`/api/models/${encodeURIComponent(m.id)}/load`,
                                            { method: 'POST' });
                   out.push(`${m.id}:${resp.status}`);
                 }
                 return out;
               }"""
        )
        print("model load:", ", ".join(loaded))

        def shot(pg, name, theme=None, full=True):
            if theme:
                pg.evaluate(
                    "t => { localStorage.setItem('cv84x6.theme', t);"
                    "document.documentElement.setAttribute('data-theme', t);"
                    "document.documentElement.style.colorScheme = t; }",
                    theme,
                )
                pg.wait_for_timeout(250)
            p = out / f"{name}.png"
            pg.screenshot(path=str(p), full_page=full)
            shots.append(str(p))
            print("  shot", p.name)

        # -- model cards, loaded: 在线 pill + 卸载 (danger outline) ----------
        for theme in ("light", "dark"):
            page.click('[data-testid="nav-models"]')
            page.wait_for_timeout(2200)
            shot(page, f"models-loaded-{theme}", theme)

        # -- playground with a real (mock) exchange -------------------------
        for theme in ("light", "dark"):
            page.evaluate(
                "t => { localStorage.setItem('cv84x6.theme', t);"
                "document.documentElement.setAttribute('data-theme', t);"
                "document.documentElement.style.colorScheme = t; }", theme)
            page.click('[data-testid="nav-playground"]')
            page.wait_for_selector('[data-testid="chat-log"]')
            page.fill('[data-testid="chat-input"]', '用一句话说明这块板子能做什么')
            page.click('[data-testid="chat-send"]')
            page.wait_for_selector('[data-testid="chat-stop"]', timeout=8000)
            shot(page, f"playground-streaming-{theme}", theme)
            page.wait_for_selector('[data-testid="chat-send"]', timeout=90000)
            page.wait_for_timeout(400)
            shot(page, f"playground-answer-{theme}", theme)
            page.click('[data-testid="chat-clear"]')

        # -- a fresh API key: the callout surface --------------------------
        for theme in ("light", "dark"):
            page.evaluate(
                "t => { localStorage.setItem('cv84x6.theme', t);"
                "document.documentElement.setAttribute('data-theme', t);"
                "document.documentElement.style.colorScheme = t; }", theme)
            page.click('[data-testid="nav-keys"]')
            page.wait_for_timeout(700)
            page.fill('input[placeholder*="用途备注"]', f'ui-refine-{theme}')
            page.click('button.btn:has-text("创建")')
            page.wait_for_selector('[data-testid="fresh-key"]', timeout=8000)
            shot(page, f"keys-fresh-{theme}", theme)

        # -- settings after a save: 实际生效 + clamped/notice surfaces ------
        page.click('[data-testid="nav-settings"]')
        page.wait_for_timeout(1200)
        page.click('button.btn:has-text("保存")')
        page.wait_for_timeout(1800)
        shot(page, "settings-applied-light")
        page.evaluate(
            "t => { localStorage.setItem('cv84x6.theme', t);"
            "document.documentElement.setAttribute('data-theme', t);"
            "document.documentElement.style.colorScheme = t; }", "dark")
        page.wait_for_timeout(250)
        shot(page, "settings-applied-dark")

        # -- the docs page in both themes, full length ---------------------
        for theme in ("light", "dark"):
            page.click('[data-testid="nav-docs"]')
            page.wait_for_timeout(1200)
            shot(page, f"docs-{theme}", theme)

        # -- 1024 laptop, both themes --------------------------------------
        page.set_viewport_size({"width": 1024, "height": 800})
        for theme in ("light", "dark"):
            page.evaluate(
                "t => { localStorage.setItem('cv84x6.theme', t);"
                "document.documentElement.setAttribute('data-theme', t);"
                "document.documentElement.style.colorScheme = t; }", theme)
            page.click('[data-testid="nav-overview"]')
            page.wait_for_timeout(1600)
            shot(page, f"overview-laptop-{theme}", theme)
            page.click('[data-testid="nav-models"]')
            page.wait_for_timeout(1500)
            shot(page, f"models-laptop-{theme}", theme)

        browser.close()

    summary = {"shots": shots, "errors": errors,
               "models_loaded": loaded}
    (out / "states.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    if errors:
        print("\nCONSOLE ERRORS:")
        for e in errors:
            print("  " + e)
        return 1
    print(f"\n{len(shots)} screenshots, no console errors -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
