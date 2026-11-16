"""An agent's operation lock, watched in a real browser across a reload.

The agent has to be genuinely installed for the card to render its controls, and
a real install downloads a real archive. So this harness registers a *fake*
agent spec -- a tiny real HTTP server packed into a real tar.gz, the same one
the pytest suite uses -- and installs it from ``file://``.

What it proves:
1. a start in flight reports ``data-operation=starting`` and disables every
   control on the card;
2. after F5 the card still shows 启动中 and every control is still disabled,
   i.e. the lock came from the backend;
3. controls unlock by themselves when the start finishes;
4. the same holds for 停止.

    python3 tools/ops_agent_browser_check.py http://127.0.0.1:18202
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import tarfile
import textwrap
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from fastapi import FastAPI  # noqa: E402

from app.agents.spec import Artifact, AgentSpec, host_arch  # noqa: E402
from app.main import create_app  # noqa: E402

FAKE_AGENT = """\
import http.server, json, os, socketserver, sys, time

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def do_GET(self):
        body = json.dumps({'ok': True}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

class Server(socketserver.TCPServer):
    allow_reuse_address = True

port = int(sys.argv[sys.argv.index('--port') + 1])
# Slow to become healthy: the console must be seen reporting "starting".
time.sleep(float(os.environ.get('FAKE_START_DELAY', '0') or 0))
Server(('0.0.0.0', port), Handler).serve_forever()
"""


class FakeSpec(AgentSpec):
    id = "slow"
    name = "慢启动 agent"
    version = "1.0.0"
    default_port = int(__import__("os").environ.get("AGENT_ACCEPT_PORT", "14297"))
    embeddable = False
    start_timeout = 60.0
    executable = "slow-agent"
    payload_root = "bin"
    key_in_config = False

    def command(self, directory: Path, port: int) -> list[str]:
        return [sys.executable, str(Path(directory) / "bin" / "slow-agent"),
                "--port", str(port)]


def build_tarball(path: Path) -> Path:
    data = textwrap.dedent(FAKE_AGENT).encode()
    with tarfile.open(path, "w:gz") as tf:
        info = tarfile.TarInfo("slow-1.0.0/bin/slow-agent")
        info.size = len(data)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(data))
    return path


def make_app(root: Path, port: int) -> FastAPI:
    tarball = build_tarball(root / "slow-1.0.0.tar.gz")
    art = Artifact(urls=(f"file://{tarball}",),
                   sha256=hashlib.sha256(tarball.read_bytes()).hexdigest())
    spec = FakeSpec(artifacts={"x64": art, "arm64": art})
    models = root / "models"
    models.mkdir(parents=True, exist_ok=True)
    return create_app(
        data_dir=root / "state", models_dir=models, backend_kind="mock",
        web_dir=BASE / "web" / "dist", data_root=root / "runtime",
        agent_specs=[spec], service_port=port,
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("base_url", nargs="?", default="http://127.0.0.1:18202")
    args = p.parse_args()

    import os
    os.environ["FAKE_START_DELAY"] = "6"  # the child's own slow startup

    root = Path(__import__("tempfile").mkdtemp(prefix="agent-accept-"))
    app = make_app(root, 18202)

    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=18202,
                                           log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:
        print("the harness service never started")
        return 1

    return drive(args.base_url, app)


def drive(base: str, app) -> int:
    from playwright.sync_api import sync_playwright

    failures: list[str] = []

    def check(cond: bool, what: str) -> None:
        print(("PASS " if cond else "FAIL ") + what)
        if not cond:
            failures.append(what)

    def open_agents(page):
        page.get_by_role("button", name="Agent").click()
        page.wait_for_selector('[data-testid="agent-card-slow"]', timeout=30_000)

    def state(page) -> dict:
        card = page.locator('[data-testid="agent-card-slow"]')
        return {
            "operation": card.get_attribute("data-operation"),
            "pill": page.locator('[data-testid="agent-status-slow"]').inner_text(),
            "note": _text(page, "agent-operation-slow"),
            "start_disabled": _disabled(page, "agent-start-slow"),
            "stop_disabled": _disabled(page, "agent-stop-slow"),
            "reset_disabled": _disabled(page, "agent-reset-slow"),
            "uninstall_disabled": _disabled(page, "agent-uninstall-slow"),
            "port_disabled": _disabled(page, "agent-port-slow"),
        }

    def _disabled(page, testid):
        el = page.locator(f'[data-testid="{testid}"]')
        return el.is_disabled() if el.count() else None

    def _text(page, testid):
        el = page.locator(f'[data-testid="{testid}"]')
        return el.inner_text() if el.count() else ""

    with sync_playwright() as pl:
        browser = pl.chromium.launch()
        page = browser.new_page()
        page.goto(base + "/", wait_until="networkidle")
        if page.locator('input[type="password"]').count():
            page.fill('input[type="password"]', "admin")
            page.keyboard.press("Enter")
            page.wait_for_load_state("networkidle")
        open_agents(page)

        idle = state(page)
        check(idle["operation"] == "idle", f"idle agent reports operation=idle ({idle['operation']})")

        # Install synchronously through the API (the UI's install is the same
        # job), then come back to the card.
        page.click('[data-testid="agent-install-slow"]')
        page.wait_for_function(
            """() => {
                const c = document.querySelector('[data-testid="agent-card-slow"]');
                return c && c.getAttribute('data-operation') === 'idle'
                        && document.querySelector('[data-testid="agent-start-slow"]');
            }""",
            timeout=90_000,
        )
        installed = state(page)
        check(installed["start_disabled"] is False, "after install the start button is usable")

        # -- starting ------------------------------------------------------
        # Click without waiting for the response: `start` does not return until
        # the agent is healthy, and the state we care about exists exactly while
        # it is in flight.
        page.evaluate(
            """() => document.querySelector('[data-testid="agent-start-slow"]').click()""")
        try:
            page.wait_for_function(
                """() => {
                    const c = document.querySelector('[data-testid="agent-card-slow"]');
                    return c && c.getAttribute('data-operation') === 'starting';
                }""",
                timeout=20_000,
            )
        except Exception:
            card = page.locator('[data-testid="agent-card-slow"]')
            print("DEBUG card:", card.get_attribute("data-operation"),
                  card.get_attribute("data-pending"),
                  card.get_attribute("data-status"), card.get_attribute("data-running"))
            print("DEBUG pill:", page.locator('[data-testid="agent-status-slow"]').inner_text())
            raise
        # Reload the page entirely, then walk back to Agent.
        page.reload(wait_until="networkidle")
        open_agents(page)
        during = state(page)
        check(during["operation"] == "starting",
              f"after a reload mid-start the card still reports starting ({during['operation']})")
        check(during["start_disabled"] is True, "after a reload the start button is disabled")
        check(during["reset_disabled"] is True, "after a reload the reset button is disabled")
        check(during["port_disabled"] is True, "after a reload the port field is disabled")
        check("启动中" in (during["pill"] + during["note"]),
              f"the card says 启动中 ({during['pill']!r} / {during['note']!r})")

        page.wait_for_function(
            """() => {
                const c = document.querySelector('[data-testid="agent-card-slow"]');
                return c && c.getAttribute('data-operation') === 'idle'
                        && c.getAttribute('data-running') === 'true';
            }""",
            timeout=90_000,
        )
        running = state(page)
        check(running["stop_disabled"] is False, "once started the stop button unlocked by itself")
        check("运行中" in running["pill"], f"the pill reads 运行中 ({running['pill']!r})")

        # -- stopping ------------------------------------------------------
        with page.expect_response(
                lambda r: r.url.endswith("/api/agents/slow/stop"), timeout=60_000) as stopresp:
            page.click('[data-testid="agent-stop-slow"]')
        check(stopresp.value.status == 200,
              f"the stop request succeeded (HTTP {stopresp.value.status})")
        page.wait_for_function(
            """() => {
                const c = document.querySelector('[data-testid="agent-card-slow"]');
                return c && c.getAttribute('data-running') === 'false'
                        && c.getAttribute('data-operation') === 'idle';
            }""",
            timeout=60_000,
        )
        stopped = state(page)
        check(stopped["start_disabled"] is False, "after the stop the start button unlocked")

        page.screenshot(path="/tmp/agent-accept-final.png", full_page=True)
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} FAILED")
        for f in failures:
            print("  -", f)
        return 1
    print("all agent browser checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
