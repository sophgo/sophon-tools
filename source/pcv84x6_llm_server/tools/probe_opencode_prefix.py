"""Run the real console app against a real opencode server and check the UI loads.

Not part of the pytest suite (it needs the 78 MB opencode binary and a browser),
but it is the check that the prefix rewriting actually works on the real bundle
rather than on a fixture shaped like it: opencode's asset hashes, its Vite dep
table and its router are all real here.

    python3 tools/probe_opencode_prefix.py <opencode-binary> [service-port]
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def main(binary: str, service_port: int = 18099) -> int:
    import httpx
    import uvicorn
    from playwright.async_api import async_playwright

    from app.main import create_app

    tmp = Path(tempfile.mkdtemp(prefix="oc-probe-"))
    agent_dir = tmp / "root" / "agents" / "opencode"
    (agent_dir / "bin").mkdir(parents=True)
    (agent_dir / "bin" / "opencode").write_text("#!/bin/sh\n")
    (agent_dir / "bin" / "opencode").chmod(0o755)
    (agent_dir / "config").mkdir(parents=True)

    app = create_app(
        data_dir=tmp / "state", models_dir=tmp / "models", backend_kind="mock",
        web_dir=ROOT / "web" / "dist", data_root=tmp / "root",
        service_port=service_port,
    )
    mgr = app.state.agents
    st = mgr.state("opencode")
    st.secret = "s3cr3t"
    mgr.save_state()

    # Start opencode for real, with the same auth the manager would give it.
    env = dict(os.environ)
    env.update({
        "HOME": str(agent_dir / "home"),
        "OPENCODE_CONFIG": str(agent_dir / "config" / "opencode" / "opencode.json"),
        "OPENCODE_SERVER_USERNAME": "opencode",
        "OPENCODE_SERVER_PASSWORD": "s3cr3t",
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
        "OPENCODE_DISABLE_MODELS_FETCH": "1",
        "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
    })
    (agent_dir / "home").mkdir(parents=True, exist_ok=True)
    (agent_dir / "config" / "opencode").mkdir(parents=True, exist_ok=True)
    (agent_dir / "config" / "opencode" / "opencode.json").write_text("{}")
    proc = await asyncio.create_subprocess_exec(
        binary, "serve", "--port", "0", "--hostname", "127.0.0.1",
        env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    port = None
    assert proc.stdout is not None
    for _ in range(120):
        line = (await proc.stdout.readline()).decode("utf-8", "replace")
        print("  agent:", line.strip()[:120])
        if "listening on" in line:
            port = int(line.strip().rsplit(":", 1)[1])
            break
    if port is None:
        proc.kill()
        print("opencode never announced a port")
        return 1
    st.port = port
    mgr.save_state()
    mgr._runtime["opencode"].status = "running"

    class FakeProc:
        pid = proc.pid
        returncode = None

        def send_signal(self, sig):
            pass

    mgr._runtime["opencode"].proc = FakeProc()

    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=service_port, log_level="warning", ws="websockets",
    ))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    base = f"http://127.0.0.1:{service_port}"

    failures: list[str] = []
    async with httpx.AsyncClient(base_url=base) as client:
        assert (await client.post("/api/login", json={"password": "admin"})).status_code == 200
        cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
        r = await client.get("/api/agents")
        web = {a["id"]: a for a in r.json()["agents"]}["opencode"]
        print("  web_url:", web["web_url"])
        if ":14096" in web["web_url"] or str(port) in web["web_url"]:
            failures.append("web_url still names the agent's own port")

        index = await client.get("/agents/opencode/")
        print("  index:", index.status_code, len(index.text), "bytes")
        if index.status_code != 200:
            failures.append(f"index status {index.status_code}")
        if 'src="/assets/' in index.text:
            failures.append("index still has a root-absolute asset")
        if str(port) in index.text:
            failures.append("index names the agent's port")

        # Every asset the page names must be fetchable through the proxy.
        import re
        for url in re.findall(r'(?:src|href)="(/agents/opencode/[^"]+)"', index.text):
            got = await client.get(url)
            print(f"  asset {url[-52:]:<54} {got.status_code} {len(got.content)}")
            if got.status_code != 200:
                failures.append(f"{url} -> {got.status_code}")

        health = await client.get("/agents/opencode/global/health")
        print("  health:", health.status_code, health.text[:80])
        if health.status_code != 200:
            failures.append(f"proxied API -> {health.status_code}")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        await page.context.add_cookies([{
            "name": k, "value": v, "domain": "127.0.0.1", "path": "/",
        } for k, v in (c.split("=", 1) for c in cookie.split("; "))])
        bad: list[str] = []
        page.on("pageerror", lambda e: bad.append(f"pageerror: {e}"))
        page.on("response", lambda r: bad.append(f"{r.status} {r.url}")
                if r.status >= 400 else None)
        await page.goto(f"{base}/agents/opencode/", wait_until="load", timeout=60000)
        await page.wait_for_timeout(6000)
        text = await page.inner_text("body")
        print("  rendered text:", repr(text[:160]))
        if "Nothing here yet" not in text and "Projects" not in text:
            failures.append("the UI did not render inside the iframe route")
        for entry in bad[:10]:
            failures.append(entry)
        await page.screenshot(path=str(ROOT / "opencode-embed-proof.png"))
        await browser.close()

    server.should_exit = True
    await task
    proc.terminate()
    await proc.wait()

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print("\nOK: opencode renders under /agents/opencode/ with nothing escaping the prefix")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main(sys.argv[1],
                                     int(sys.argv[2]) if len(sys.argv) > 2 else 18099)))
