#!/usr/bin/env python3
"""Prove the interactive documents work with no network (MYS-2676).

    python3 tools/check_admin_docs_offline.py --port 18210 --out ./docs-offline

What it does, and why each part is needed:

1. Starts the real service with the mock backend on a free port, with a seeded
   model so the document is not empty.
2. Loads ``/api/docs`` and ``/api/redoc`` in headless Chromium and **fails the
   check if any request leaves this origin** -- via Playwright's request
   interception, before the request is attempted. A page that silently succeeds
   because the CI machine has a network is exactly the failure this task is
   about, so "it rendered" is not enough.
3. Asserts the Swagger page actually painted operations (not just its chrome):
   the operation blocks are counted, and the tag headings must match the
   document's tags.
4. Screenshots both pages for the review comment.

Not part of the pytest suite: it needs a Chromium download, and the board's
build must stay browser-free (see ``web/acceptance/README.md`` for the same
reasoning about the console checks).
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def seed(root: Path) -> None:
    """One model of every kind the catalogue names, so the document has substance."""
    models = {
        "qwen3.6-35b-a3b-128k": [
            "qwen3.6-35b-a3b-128k-int4_w4bf16_seq131072_4core_dynamic.bmodel"],
        "qwen3-embedding-0.6b": [
            "qwen3-embedding-0.6b_bf16_seq8192_bm1684x2_4core_static.bmodel"],
        "ppocrv6-medium": [
            "ppocrv6-medium-det_f16_736_bm1684x2_static_20261103.bmodel",
            "ppocrv6-medium-rec_f16_48x320_bm1684x2_static_20261103.bmodel"],
    }
    for model_id, files in models.items():
        directory = root / "models" / model_id
        (directory / "config").mkdir(parents=True, exist_ok=True)
        (directory / "config" / "config.json").write_text("{}")
        for name in files:
            (directory / name).write_bytes(b"\x00" * (1 << 20))


def serve(root: Path, port: int):
    """Run the real app in a thread; returns (server, thread, app)."""
    import uvicorn

    from app.main import create_app

    app = create_app(data_dir=root / "data", models_dir=root / "models",
                     backend_kind="mock", web_dir=root / "web")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                            timeout_graceful_shutdown=5)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not server.started:
        time.sleep(0.1)
    if not server.started:
        raise RuntimeError("the service did not start")
    return server, app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--out", default=str(BASE / "docs-offline"))
    args = parser.parse_args(argv)
    port = args.port or free_port()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    import tempfile

    from playwright.sync_api import sync_playwright

    root = Path(tempfile.mkdtemp(prefix="cv84x6-docs-offline-"))
    seed(root)
    server, app = serve(root, port)
    origin = f"http://127.0.0.1:{port}"
    results: dict = {"origin": origin, "pages": {}, "external_requests": []}
    failures: list[str] = []
    print(f"service on {origin}")

    try:
        # A session cookie, obtained the way a browser would: POST the login.
        import httpx

        client = httpx.Client(base_url=origin, timeout=20)
        login = client.post("/api/login", json={"password": "admin"})
        assert login.status_code == 200, login.text
        cookies = [{"name": k, "value": v, "domain": "127.0.0.1", "path": "/"}
                   for k, v in client.cookies.items()]
        tags = [t["name"] for t in app.openapi().get("tags", [])]

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for page_path, name, selector, min_count in (
                    ("/api/docs", "swagger", ".opblock", 60),
                    ("/api/redoc", "redoc", "[data-section-id]", 5)):
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                context.add_cookies(cookies)
                page = context.new_page()
                external: list[str] = []

                def route_handler(route, request, external=external):
                    if not request.url.startswith(origin) and not request.url.startswith("data:"):
                        external.append(request.url)
                        # Abort rather than let it through: if a CDN URL ever comes
                        # back, the page must fail *here* the way it would on the
                        # board, not silently succeed on a machine with a network.
                        route.abort()
                    else:
                        route.continue_()

                page.route("**/*", route_handler)
                errors: list[str] = []
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                page.goto(f"{origin}{page_path}", wait_until="networkidle", timeout=60_000)
                page.wait_for_timeout(1500)
                count = page.locator(selector).count()
                shots = out / f"{name}.png"
                page.screenshot(path=str(shots), full_page=False)
                results["pages"][name] = {
                    "path": page_path, "elements": count, "external": external,
                    "screenshot": shots.name, "errors": errors}
                if external:
                    failures.append(f"{page_path} requested off-origin assets: {external}")
                if count < min_count:
                    failures.append(
                        f"{page_path} rendered {count} {selector} blocks, expected >= {min_count}")
                if errors:
                    failures.append(f"{page_path} raised script errors: {errors}")
                if name == "swagger":
                    # The tag headings are the document's own tags: proof the
                    # operation metadata (not just some document) is rendered.
                    body = page.inner_text("body")
                    missing = [tag for tag in tags if tag not in body]
                    if missing:
                        failures.append(f"/api/docs is missing tag headings: {missing}")
                    results["pages"][name]["tags"] = tags
                context.close()
            browser.close()

        # The pages must also be *refused* without a credential -- checked here as
        # well as in pytest because this is the run a reviewer reproduces.
        anonymous = httpx.Client(base_url=origin, timeout=10)
        for path in ("/api/docs", "/api/redoc", "/api/openapi.json"):
            r = anonymous.get(path)
            if r.status_code != 401:
                failures.append(f"{path} answered {r.status_code} without a credential")
        results["anonymous_refused"] = True
    finally:
        server.should_exit = True
        results["ok"] = not failures
        results["failures"] = failures
        (out / "results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            app.state.audit.close()
            app.state.inference_log.close()
        except Exception:  # pragma: no cover
            pass

    print(json.dumps(results, ensure_ascii=False, indent=2))
    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print(f"OK: {out}/swagger.png and {out}/redoc.png; no off-origin requests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
