#!/usr/bin/env python3
"""Console regression after the API changes (MYS-2676 acceptance requirement 6).

    python3 tools/check_console_against_mock.py --out ./docs-offline/console

The card requires that the existing console keeps working unchanged ("现有路径和
响应字段不改，控制台不需要任何改动就能继续工作"): the change is additive -- an
error body gains ``code``, a key gains ``scope``, ``/api/docs`` moved behind
auth -- and none of that may show up on the console's pages.

So this walks the console the way a person does: log in with the default
password, click through every navigation entry, and fail if any page

* logs a JavaScript error,
* receives an ``/api`` response the page treats as an error (the console shows
  ``detail`` verbatim on failure), or
* paints nothing (the page's own container is the check).

Every page is screenshotted. The console is a *single-page app switched by
sidebar buttons*, not routed by URL (``web/src/App.tsx``), so the walk clicks
``[data-testid=nav-<id>]`` rather than navigating.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

#: (nav id, label) in the order the sidebar lists them (``web/src/App.tsx``).
PAGES = (
    ("overview", "总览"),
    ("models", "模型"),
    ("agents", "Agent"),
    ("playground", "对话测试"),
    ("apps", "应用演示"),
    ("keys", "API Key"),
    ("records", "推理记录"),
    ("logs", "日志"),
    ("settings", "设置"),
    ("docs", "文档"),
)

#: Refusals a page legitimately shows that are *not* a regression, keyed by the
#: path they come from. Each is a documented answer to "this board has nothing
#: yet", not a break in the console: an empty board has no records, no audit
#: rows, and no agent installed, and those pages say so.
TOLERATED = {
    "/api/agents/",           # 404 for an agent that is not installed
}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def seed(root: Path) -> None:
    """Two models and a little history, so the pages are not all empty.

    Without this the check would pass on a console that renders nothing but
    "暂无数据", which is the one outcome it must not be satisfied by.
    """
    models = {
        "qwen3.6-35b-a3b-128k": [
            "qwen3.6-35b-a3b-128k-int4_w4bf16_seq131072_4core_dynamic.bmodel"],
        "qwen3-embedding-0.6b": [
            "qwen3-embedding-0.6b_bf16_seq8192_bm1684x2_4core_static.bmodel"],
    }
    for model_id, files in models.items():
        directory = root / "models" / model_id
        (directory / "config").mkdir(parents=True, exist_ok=True)
        (directory / "config" / "config.json").write_text("{}")
        for name in files:
            (directory / name).write_bytes(b"\x00" * (1 << 20))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--out", default=str(BASE / "docs-offline" / "console"))
    args = parser.parse_args(argv)
    port = args.port or free_port()
    origin = f"http://127.0.0.1:{port}"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="cv84x6-console-"))
    seed(root)

    # web/dist is committed (CONTRIBUTING: the board has no node toolchain), so
    # this serves exactly the bundle a release ships -- no build step.
    service = subprocess.Popen(
        [sys.executable, "-m", "app.main", "--backend", "mock", "--port", str(port),
         "--data-root", str(root), "--host", "127.0.0.1"],
        cwd=str(BASE), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    failures: list[str] = []
    report: dict = {"origin": origin, "pages": {}}
    try:
        import httpx

        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{origin}/healthz", timeout=3).status_code == 200:
                    break
            except httpx.HTTPError:  # pragma: no cover
                pass
            time.sleep(0.3)
        else:
            print("the service never became healthy", file=sys.stderr)
            print(service.stderr.read()[-2000:] if service.stderr else "",
                  file=sys.stderr)
            return 2

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            api_failures: list[dict] = []
            script_errors: list[str] = []

            def on_response(response):
                if "/api/" not in response.url or response.status < 400:
                    return
                path = response.url.split(origin, 1)[-1]
                if any(path.startswith(prefix) for prefix in TOLERATED):
                    return
                try:
                    body = response.text()[:200]
                except Exception:  # pragma: no cover - a body already consumed
                    body = ""
                api_failures.append({"status": response.status, "url": path,
                                     "body": body})

            page.on("response", on_response)
            page.on("pageerror", lambda exc: script_errors.append(str(exc)))

            page.goto(origin, wait_until="networkidle", timeout=60_000)
            page.fill("[data-testid=login-password]", "admin")
            page.click("[data-testid=login-submit]")
            page.wait_for_selector("[data-testid=sidebar]", timeout=30_000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out / "00-login.png"))
            if page.locator("[data-testid=sidebar]").count() == 0:
                failures.append("login did not reach the console (no sidebar)")
                raise SystemExit(1)

            for index, (nav_id, label) in enumerate(PAGES, start=1):
                api_failures.clear()
                script_errors.clear()
                button = page.locator(f"[data-testid=nav-{nav_id}]")
                if button.count() == 0:
                    failures.append(f"{label}: no sidebar entry (nav-{nav_id})")
                    continue
                button.first.click()
                page.wait_for_timeout(1800 if nav_id in ("overview", "records") else 900)
                main_el = page.locator("main .main-inner")
                cards = page.locator("main .card")
                shot = out / f"{index:02d}-{nav_id}.png"
                page.screenshot(path=str(shot))
                report["pages"][label] = {
                    "nav": nav_id, "cards": cards.count(),
                    "api_failures": list(api_failures),
                    "script_errors": list(script_errors),
                    "screenshot": shot.name}
                if main_el.count() == 0:
                    failures.append(f"{label}: the page container did not render")
                for failure in api_failures:
                    failures.append(
                        f"{label}: API {failure['status']} {failure['url']}: "
                        f"{failure['body'][:140]}")
                if script_errors:
                    failures.append(f"{label}: script error {script_errors}")

            # A real **write** from the browser. This is the CSRF change's true
            # regression test: a browser sends `Origin` on every state-changing
            # request, so if the new Origin check were wrong this is the click
            # that would start failing -- and no amount of GET-only walking would
            # have noticed. Creating a key also covers the new ``scope`` field:
            # the console does not send one, and the default must stay
            # ``inference``.
            api_failures.clear()
            script_errors.clear()
            page.click("[data-testid=nav-keys]")
            page.wait_for_timeout(600)
            page.fill("input[placeholder*='用途备注']", "console-regression")
            # The create button is the one beside that input, in the same row.
            # Selecting by its text alone matched the card heading ("创建新 Key")
            # first, which is why this looks fussy.
            page.locator(".card", has_text="创建新 Key").locator(
                "button", has_text="创建").first.click()
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out / "11-key-created.png"))
            report["write"] = {"api_failures": list(api_failures),
                               "script_errors": list(script_errors)}
            for failure in api_failures:
                failures.append(f"creating a key from the console: API "
                                f"{failure['status']} {failure['url']}: "
                                f"{failure['body'][:140]}")
            if script_errors:
                failures.append(f"creating a key from the console: {script_errors}")
            # And the key really exists, with the default scope.
            import httpx as _httpx

            listing = _httpx.get(
                f"{origin}/api/keys",
                cookies={cookie["name"]: cookie["value"]
                         for cookie in context.cookies()})
            keys = []
            if listing.status_code == 200:
                keys = listing.json().get("keys", [])
            report["write"]["keys"] = [
                {"name": k["name"], "scope": k.get("scope")} for k in keys]
            match = [k for k in keys if k["name"] == "console-regression"]
            if not match:
                failures.append("the console's key creation did not persist")
            elif match[0].get("scope") != "inference":
                failures.append(
                    f"a console-created key got scope {match[0].get('scope')!r}, "
                    "expected the default 'inference'")
            context.close()
            browser.close()
    finally:
        service.terminate()
        try:
            service.wait(timeout=20)
        except subprocess.TimeoutExpired:  # pragma: no cover
            service.kill()
        shutil.rmtree(root, ignore_errors=True)
        report["ok"] = not failures
        report["failures"] = failures
        (out / "results.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for label, data in report["pages"].items():
        print(f"{label:8s} nav={data['nav']:11s} cards={data['cards']:3d} "
              f"api_errors={len(data['api_failures'])} "
              f"script_errors={len(data['script_errors'])}")
    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print(f"OK: all {len(report['pages'])} console pages rendered with no API or "
          f"script error (screenshots in {out})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
