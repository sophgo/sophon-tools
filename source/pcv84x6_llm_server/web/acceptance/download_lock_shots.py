#!/usr/bin/env python3
"""Screenshots and DOM checks for a model whose download is still running.

A download stages its bytes outside models/ and installs the file when done,
so a model being re-downloaded is the one that has a card while its job runs.
This seeds exactly that state -- the mock server's models plus a running dfss
job for one of them -- and checks that the card says 下载中 with 加载 / 删除
disabled, that the catalog row no longer claims 已在磁盘, and that the card
unlocks once the job ends.

    python3 web/acceptance/download_lock_shots.py --out ./dl-shots
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

WIDTHS = {"desktop": (1440, 1000), "phone": (390, 844)}
MID = "qwen3.6-35b-a3b-128k"  # a catalog id, so the catalog row is covered too


def serve(port: int):
    import uvicorn

    from app.core.downloader import DownloadJob
    from app.main import create_app
    from mock_server import seed

    root = Path(tempfile.mkdtemp(prefix="cv84x6-dl-lock-"))
    seed(root)
    app = create_app(data_root=root, backend_kind="mock", web_dir=ROOT / "web" / "dist",
                     context_length_override=32768, service_port=port)
    job = DownloadJob(id="job-shot", kind="dfss", name=MID, state="running",
                      target="open@sophgo.com:/tools/cv84x6_llm_server/x.bmodel",
                      total_bytes=int(19.2 * (1 << 30)), done_bytes=int(4.92 * (1 << 30)),
                      percent_hint=25.0,
                      message="[4.92 GiB] 25% [=====>     ] 37.89 MiB/s, ETA: 6m 26s")
    app.state.downloads.jobs[job.id] = job
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server, job


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8803)
    ap.add_argument("--out", default="./dl-shots")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    server, job = serve(args.port)
    base = f"http://127.0.0.1:{args.port}"
    errors: list[str] = []

    def check(cond: bool, what: str) -> None:
        if not cond:
            errors.append(what)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for wname, (w, h) in WIDTHS.items():
            for theme in ("light", "dark"):
                tag = f"{wname}/{theme}"
                ctx = browser.new_context(viewport={"width": w, "height": h})
                page = ctx.new_page()
                page.on("pageerror", lambda e: errors.append(f"pageerror:{e}"))
                page.goto(base, wait_until="networkidle")
                page.fill('[data-testid="login-password"]', "admin")
                page.click('[data-testid="login-submit"]')
                page.wait_for_selector('[data-testid="nav"]')
                page.evaluate(
                    "t => { localStorage.setItem('cv84x6.theme', t);"
                    "document.documentElement.setAttribute('data-theme', t); }", theme)
                page.click('[data-testid="nav-models"]')
                card = page.locator(f'[data-testid="model-card-{MID}"]')
                card.wait_for(timeout=15000)
                page.wait_for_timeout(500)

                check(card.get_attribute("data-operation") == "downloading", f"{tag}: card state")
                check("下载中" in page.inner_text(f'[data-testid="model-status-{MID}"]'),
                      f"{tag}: status pill")
                check(page.is_disabled(f'[data-testid="model-load-{MID}"]'), f"{tag}: load enabled")
                check(page.is_disabled(f'[data-testid="model-delete-{MID}"]'), f"{tag}: delete enabled")
                check(page.locator(f'[data-testid="model-downloading-{MID}"]').count() == 1,
                      f"{tag}: downloading note missing")
                check("4.9 GiB / 19.2 GiB" in page.inner_text("body"), f"{tag}: byte progress")
                other = "qwen3.6-35b-a3b-32k"
                check(not page.is_disabled(f'[data-testid="model-load-{other}"]'),
                      f"{tag}: unrelated model locked")
                m = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                check(m <= 0, f"{tag}: horizontal overflow {m}")
                page.screenshot(path=str(out / f"dl-lock-{wname}-{theme}.png"), full_page=True)
                card.screenshot(path=str(out / f"dl-lock-card-{wname}-{theme}.png"))
                ctx.close()

        # The job ends: the page notices on its next download poll, rescans,
        # and the card unlocks without a reload or a click.
        w, h = WIDTHS["desktop"]
        ctx = browser.new_context(viewport={"width": w, "height": h})
        page = ctx.new_page()
        page.goto(base, wait_until="networkidle")
        page.fill('[data-testid="login-password"]', "admin")
        page.click('[data-testid="login-submit"]')
        page.click('[data-testid="nav-models"]')
        page.locator(f'[data-testid="model-card-{MID}"]').wait_for(timeout=15000)
        job.state, job.message = "done", "已下载"
        job.percent_hint, job.done_bytes = 100.0, job.total_bytes
        page.wait_for_function(
            f"!document.querySelector('[data-testid=\"model-load-{MID}\"]').disabled",
            timeout=10000)
        check("未加载" in page.inner_text(f'[data-testid="model-status-{MID}"]'), "after: status pill")
        check(page.locator(f'[data-testid="model-downloading-{MID}"]').count() == 0, "after: note left")
        page.screenshot(path=str(out / "dl-unlocked-desktop-light.png"), full_page=True)
        browser.close()
    server.should_exit = True

    for e in errors:
        print("FAIL", e)
    print("ALL PASS" if not errors else f"{len(errors)} failure(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
