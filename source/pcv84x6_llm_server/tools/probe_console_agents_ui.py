"""Browser check of the console's Agent page: plaintext credentials, iframe, open.

Runs the real service with a fake agent upstream and the built console in
Chromium, because the two things being checked are only observable in a browser:
that the password is readable/selectable text (not dots), and that the embed
iframe loads the agent through ``/agents/<id>/`` and stays there.

    python3 tools/probe_console_agents_ui.py
"""

from __future__ import annotations

import asyncio
import base64
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PORT = 18110
BASIC = "Basic " + base64.b64encode(b"opencode:s3cr3t").decode()

INDEX = """<!doctype html><html><head><title>agent ui</title>
<script type="module" src="/assets/app.js"></script></head>
<body><div id="root">agent ui loaded</div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.headers.get("authorization") != BASIC:
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        path = self.path.split("?", 1)[0]
        body = b'{"healthy":true}' if path == "/global/health" else INDEX.encode()
        ctype = "application/json" if path == "/global/health" else "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)


async def main() -> int:
    import httpx
    import uvicorn
    from playwright.async_api import async_playwright

    from app.agents.spec import AgentSpec
    from app.main import create_app

    class OpenCodeLike(AgentSpec):
        id = "opencode"
        name = "opencode"
        version = "9.9.9"
        embeddable = True
        proxied = True
        prefix_root = True
        executable = "opencode"

        def web_url(self, host, port, secret):
            return "/agents/opencode/"

        def web_credentials(self, secret):
            return ("opencode", secret)

        def upstream_basic_auth(self, secret):
            return ("opencode", secret) if secret else None

    up = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=up.serve_forever, daemon=True).start()

    tmp = Path(tempfile.mkdtemp())
    app = create_app(
        data_dir=tmp / "state", models_dir=tmp / "models", backend_kind="mock",
        web_dir=ROOT / "web" / "dist", data_root=tmp / "root",
        agent_specs=[OpenCodeLike()], service_port=PORT,
    )
    mgr = app.state.agents
    d = mgr.directory("opencode")
    (d / "bin").mkdir(parents=True, exist_ok=True)
    (d / "bin" / "opencode").write_text("#!/bin/sh\n")
    st = mgr.state("opencode")
    st.port = up.server_address[1]
    st.secret = "s3cr3t"
    mgr.save_state()
    mgr._runtime["opencode"].status = "running"

    class F:
        pid = 0
        returncode = None

        def send_signal(self, s):
            pass

    mgr._runtime["opencode"].proc = F()

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT,
                                          log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    base = f"http://127.0.0.1:{PORT}"
    problems: list[str] = []
    async with httpx.AsyncClient(base_url=base) as c:
        await c.post("/api/login", json={"password": "admin"})
        cookie = "; ".join(f"{k}={v}" for k, v in c.cookies.items())

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda e: problems.append(f"pageerror {e}"))
        page.on("response", lambda r: problems.append(f"{r.status} {r.url}")
                if r.status >= 400 and "/api/" not in r.url else None)
        for k, v in (x.split("=", 1) for x in cookie.split("; ")):
            await page.context.add_cookies(
                [{"name": k, "value": v, "domain": "127.0.0.1", "path": "/"}])

        # The console has no URL routing: it is a state machine behind the nav.
        await page.goto(f"{base}/", wait_until="networkidle")
        await page.get_by_role("button", name="Agent").click()
        await page.wait_for_timeout(1500)

        # The password must be plain, readable text.
        if await page.locator('[data-testid="agent-password-opencode"]').count() == 0:
            problems.append("no plaintext password field")
        else:
            value = await page.input_value('[data-testid="agent-password-opencode"]')
            print("  password field value:", value)
            if value != "s3cr3t":
                problems.append(f"password field is not the real password: {value!r}")
        print("  page has dots:", "••••" in await page.inner_text("body"))

        # The open link must be the proxy path, not the agent's port.
        href = await page.get_attribute('[data-testid="agent-open-opencode"]', "href")
        print("  open href:", href)
        if href != "/agents/opencode/" or str(up.server_address[1]) in (href or ""):
            problems.append(f"open href is {href!r}")

        # And the embed must actually render the agent inside the console page.
        await page.click('[data-testid="agent-embed-opencode"]')
        await page.wait_for_timeout(2500)
        frames = page.frames
        print("  frames:", [f.url for f in frames])
        agent_frame = [f for f in frames if "/agents/opencode/" in f.url]
        if not agent_frame:
            problems.append("the embed iframe never loaded the agent")
        else:
            text = await agent_frame[0].inner_text("body")
            print("  iframe text:", repr(text[:80]))
            if "agent ui loaded" not in text:
                problems.append(f"iframe content: {text[:80]!r}")
        await page.screenshot(path=str(ROOT / "console-agent-card.png"))

        # Same origin: the iframe URL and the console URL share host:port.
        for f in agent_frame:
            if not f.url.startswith(base):
                problems.append(f"iframe escaped the origin: {f.url}")
        await browser.close()

    server.should_exit = True
    await task
    up.shutdown()

    if problems:
        print("\nFAILURES:")
        for p in problems:
            print("  -", p)
        return 1
    print("\nOK: plaintext credentials, proxy-path link, and a working same-origin embed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
