#!/usr/bin/env python3
"""Serve the local `web/dist` while forwarding only READS to a real board.

Purpose: screenshot the redesigned console against a live CV84X6 (10.42.0.242)
without deploying it and without changing anything on that board.

The safety property is enforced here, not by convention: every request method
other than GET/HEAD is refused before it is forwarded, with the single exception
of POST /api/login (a session cookie is what a read requires). So a stray click
on 加载 / 启动 / 保存 in the browser cannot reach the board — it gets a 405 from
this process and the board never sees it.

    python3 tools/probe_console_readonly_proxy.py \
        --upstream http://10.42.0.242:8000 --port 8899

Then open http://127.0.0.1:8899 and log in with the board's own password.
"""
from __future__ import annotations

import argparse
import http.client
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "web" / "dist"

READ_METHODS = {"GET", "HEAD"}
# The only mutating call a read-only walk of the UI genuinely needs: it returns a
# session cookie. It writes no service state.
ALLOWED_WRITES = {("POST", "/api/login")}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".json": "application/json",
    ".woff2": "font/woff2",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    upstream = "http://10.42.0.242:8000"

    def log_message(self, fmt, *args):  # keep the transcript readable
        sys.stderr.write("  %s\n" % (fmt % args))

    # -- routing ----------------------------------------------------------
    def _is_api(self, path: str) -> bool:
        return path.startswith("/api/") or path.startswith("/v1/")

    def _refuse(self, why: str) -> None:
        body = (f"read-only proxy: {why}\n"
                "This process forwards GET/HEAD only, plus POST /api/login.\n"
                "Nothing was sent to the board.\n").encode()
        self.send_response(405)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _forward(self) -> None:
        path = self.path
        allowed = (self.command in READ_METHODS
                   or (self.command, urlparse(path).path) in ALLOWED_WRITES)
        if not allowed:
            self._refuse(f"{self.command} {path} is not on the read-only allow-list")
            return

        up = urlparse(self.upstream)
        conn = http.client.HTTPConnection(up.hostname, up.port or 80, timeout=30)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in {"host", "connection"}}
        headers["Host"] = up.netloc
        try:
            conn.request(self.command, path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
        except Exception as e:  # upstream down / board busy -- say so, do not fake it
            msg = f"upstream error: {e}\n".encode()
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return
        finally:
            conn.close()

        self.send_response(resp.status)
        for k, v in resp.getheaders():
            # Length is recomputed; hop-by-hop headers are dropped.
            if k.lower() in {"content-length", "transfer-encoding", "connection"}:
                continue
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _static(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", ""):
            path = "/index.html"
        target = (DIST / path.lstrip("/")).resolve()
        # Never serve outside dist/.
        if not str(target).startswith(str(DIST.resolve())) or not target.is_file():
            target = DIST / "index.html"      # SPA fallback
        if not target.is_file():
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type",
                         CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_GET(self):
        self._forward() if self._is_api(self.path) else self._static()

    def do_HEAD(self):
        self._forward() if self._is_api(self.path) else self._static()

    def do_POST(self):
        if self._is_api(self.path):
            self._forward()
        else:
            self._refuse("non-API POST has no meaning here")

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", default="http://10.42.0.242:8000")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()

    if not (DIST / "index.html").is_file():
        print(f"no build at {DIST} — run scripts/build_web.sh", file=sys.stderr)
        return 2
    Handler.upstream = a.upstream
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"serving {DIST}")
    print(f"read-only proxy -> {a.upstream}")
    print(f"open http://{a.host}:{a.port}")
    print("refused: every method but GET/HEAD, and every non-login write")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
