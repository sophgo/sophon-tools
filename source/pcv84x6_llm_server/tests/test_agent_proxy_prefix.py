"""The reverse proxy for an origin-root agent UI (opencode) under ``/agents/<id>/``.

The upstream here is a **real** HTTP server that behaves like opencode 1.19.4
measured on the board:

* its index names ``/assets/index-<hash>.js`` and ``/favicon.png`` absolutely,
* its router treats the request path as a route, so an unknown path gets the SPA
  shell (that is what made a prefixed visit render nothing),
* its API lives at the origin root (``/global/health``) and 401s without basic
  auth,
* it sets a ``Path=/`` cookie and redirects to an absolute loopback URL.

Assertions are about what a browser would receive -- status, headers and body
bytes -- because every failure mode this module fixes is visible there and
nowhere else.
"""

from __future__ import annotations

import base64
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app.agents.spec import AgentSpec
from app.api.agent_proxy import _PrefixRewriter, _rewrite_cookie, _shim_js
from app.main import create_app

PREFIX = "/agents/prox"
CREDENTIALS = "opencode:s3cr3t"
BASIC = "Basic " + base64.b64encode(CREDENTIALS.encode()).decode()

INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Opencode</title>
    <script type="module" crossorigin src="/assets/index-abc123.js"></script>
    <link rel="stylesheet" crossorigin href="/assets/index-abc123.css" />
  </head>
  <body><div id="root"></div></body>
</html>
"""

BUNDLE_JS = (
    'const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=["assets/a.js"])))=>i.map(i=>d[i]);'
    'let NJ=()=>location.origin;'
    'function Qfe(){return window.location.pathname+window.location.search}'
    'const w="/assets/worker-x.js";'
)

BUNDLE_CSS = (
    "@font-face{src:url(/assets/Inter.woff2) format('woff2')}"
    ".a{background:url('/assets/bg.png')}"
    ".b{background:url(\"/assets/bg2.png\")}"
    ".c{background:url('https://elsewhere.example/x.png')}"
)

HEALTH = {"healthy": True, "version": "1.19.4"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Upstream:
    """A stdlib server that answers the way opencode does."""

    def __init__(self, require_auth: bool = True) -> None:
        # A base-path agent (OpenClaw) authenticates with its own token/cookie
        # instead of basic auth, so the fake has to be able to model both.
        self.require_auth = require_auth
        self.port = free_port()
        self.requests: list[dict] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _handler(self):
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # keep pytest output clean
                pass

            def _record(self) -> None:
                outer.requests.append({
                    "method": self.command,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                })

            def _send(self, code, body: bytes, ctype: str, extra=()):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Frame-Options", "DENY")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval' "
                    "sha256-abc=; connect-src * data: blob:",
                )
                for k, v in extra:
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _authorised(self) -> bool:
                if not outer.require_auth:
                    return True
                if self.headers.get("authorization") == BASIC:
                    return True
                self._send(401, b"unauthorized", "text/plain")
                return False

            def do_GET(self):
                self._record()
                if not self._authorised():
                    return
                path = self.path.split("?", 1)[0]
                if path == "/global/health":
                    body = json.dumps(HEALTH).encode()
                    self._send(200, body, "application/json")
                    return
                if path == "/assets/index-abc123.js":
                    self._send(200, BUNDLE_JS.encode(), "text/javascript")
                    return
                if path == "/assets/index-abc123.css":
                    self._send(200, BUNDLE_CSS.encode(), "text/css")
                    return
                if path == "/redirect":
                    # An absolute loopback redirect, as after a login flow.
                    self._send(302, b"", "text/plain",
                               extra=[("Location", f"http://127.0.0.1:{outer.port}/login")])
                    return
                if path == "/set-cookie":
                    self._send(200, INDEX_HTML.encode(), "text/html; charset=utf-8",
                               extra=[("Set-Cookie", "session=abc; Path=/; HttpOnly"),
                                      ("Set-Cookie", "theme=dark; Path=/settings")])
                    return
                if path == "/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    for chunk in (b"data: one\n\n", b"data: two\n\n"):
                        self.wfile.write(hex(len(chunk))[2:].encode() + b"\r\n" + chunk + b"\r\n")
                    self.wfile.write(b"0\r\n\r\n")
                    return
                # Everything else is the SPA shell -- including unknown routes,
                # which is exactly why a prefix the app cannot route was blank.
                self._send(200, INDEX_HTML.encode(), "text/html; charset=utf-8")

            def do_POST(self):
                self._record()
                if not self._authorised():
                    return
                n = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(n)
                body = json.dumps({
                    "path": self.path,
                    "origin": self.headers.get("origin"),
                    "host": self.headers.get("host"),
                    "body": raw.decode(),
                }).encode()
                self._send(200, body, "application/json")

        return H

    def __enter__(self):
        self.thread.start()
        for _ in range(200):
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return self
            except OSError:
                time.sleep(0.02)
        raise AssertionError("the fake agent never started")

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)

    def finds(self, path: str) -> list[dict]:
        return [r for r in self.requests if r["path"].split("?", 1)[0] == path]


class PrefixSpec(AgentSpec):
    """An opencode-shaped agent: origin root, basic auth, proxied."""

    id = "prox"
    name = "代理测试 agent"
    version = "1.0.0"
    default_port = 0
    embeddable = True
    proxied = True
    prefix_root = True
    executable = "server.py"
    payload_root = "bin"
    key_in_config = False

    def upstream_basic_auth(self, secret):
        return ("opencode", secret) if secret else None


@pytest.fixture()
def app_with_agent(tmp_path):
    """A live app whose single agent is installed, running, and pointing upstream."""
    upstream = _Upstream()
    with upstream:
        models = tmp_path / "models"
        models.mkdir()
        app = create_app(
            data_dir=tmp_path / "state", models_dir=models, backend_kind="mock",
            web_dir=tmp_path / "web", data_root=tmp_path / "root",
            agent_specs=[PrefixSpec()], service_port=18080,
        )
        mgr = app.state.agents
        directory = mgr.directory("prox")
        (directory / "bin").mkdir(parents=True, exist_ok=True)
        (directory / "bin" / "server.py").write_text("#!/bin/sh\n")
        st = mgr.state("prox")
        st.port = upstream.port
        st.secret = "s3cr3t"
        mgr.save_state()
        mgr._runtime["prox"].status = "running"

        class FakeProc:
            pid = 0
            returncode = None

            def send_signal(self, sig):
                pass

        mgr._runtime["prox"].proc = FakeProc()
        yield app, upstream


def login(client: TestClient) -> None:
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200


# -- the actual bug: nothing may escape the prefix ------------------------

def test_the_embedded_page_never_names_the_agents_own_port(app_with_agent):
    """The reported symptom: the frame went to ``http://<host>:<agent port>``."""
    app, upstream = app_with_agent
    with TestClient(app) as client:
        login(client)
        body = client.get(f"{PREFIX}/").text
    assert str(upstream.port) not in body
    # And no absolute origin URL at all: every asset is under the prefix.
    assert 'src="/assets/' not in body
    assert f'src="{PREFIX}/assets/index-abc123.js"' in body
    assert f'href="{PREFIX}/assets/index-abc123.css"' in body


def test_the_proxy_forwards_to_the_root_and_the_page_stays_prefixed(app_with_agent):
    """Server-side half: the prefix is stripped before it reaches the agent."""
    app, upstream = app_with_agent
    with TestClient(app) as client:
        login(client)
        assert client.get(f"{PREFIX}/").status_code == 200
    assert upstream.finds("/"), "the agent's own root was never requested"


def test_the_prefix_is_redirected_to_its_slashed_form(app_with_agent):
    """``/agents/opencode`` would resolve the page's relative URLs one level up."""
    app, _upstream = app_with_agent
    with TestClient(app, follow_redirects=False) as client:
        login(client)
        r = client.get(PREFIX)
    assert r.status_code == 307
    assert r.headers["location"] == f"{PREFIX}/"


def test_javascript_asset_paths_are_prefixed(app_with_agent):
    """Absolute names are rewritten; the dep table's relative ones are not.

    The distinction is measured, not stylistic. Vite's preload helper computes
    ``"/" + "assets/chunk.js"`` at run time; prefixing the literal instead makes
    it ``"//agents/prox/assets/chunk.js"``, which the browser treats as
    protocol-relative (host ``agents``) and refuses under the agent's own CSP.
    The run-time value is left to the shim, which sees the finished ``/assets/``
    URL on the ``<link>`` the helper creates.
    """
    app, _upstream = app_with_agent
    with TestClient(app) as client:
        login(client)
        js = client.get(f"{PREFIX}/assets/index-abc123.js").text
    # A static absolute name is prefixed...
    assert f'"{PREFIX}/assets/worker-x.js"' in js
    # ...the dep table stays relative for the preload helper...
    assert '"assets/a.js"' in js
    assert f'"//{PREFIX.lstrip("/")}' not in js
    # ...and the router's pathname read is handed to the shim's helper, whole:
    # ``window.location.pathname`` keeps its receiver, and the helper is called
    # by its bare global name so no receiver can fail to have the method.
    assert "__consolePath(window.location.pathname)" in js
    assert "window.__consolePath" not in js


def test_a_pathname_read_keeps_its_receiver():
    """The crash this guards: ``e.location.pathname`` → ``e.__consolePath(...)``.

    Measured on the board against PicoClaw's real bundle, which reads the
    pathname four ways -- ``window.``, ``globalThis.``, ``t.`` and ``e.``. The
    old implementation replaced the bare substring ``location.pathname``, which
    rewrote the receiver too: ``e.location.pathname`` became
    ``e.__consolePath(location.pathname)``, and ``e`` (the router's store) has
    no such method -- ``TypeError: e.__consolePath is not a function`` inside
    ``Object.select``, which is the blank ``Something went wrong!`` page.
    """
    rw = _PrefixRewriter(PREFIX)
    # The four forms verbatim from PicoClaw 0.3.1's index-B3x-7GgS.js.
    bundle = (
        'c=e?.parseLocation??(()=>Mr(`${t.location.pathname}${t.location.search}`));'
        'let n=window.location.pathname.match(/\\/([a-zA-Z-]*)/g);'
        'function sm(){let o=t.location.pathname}'
        'select:e=>({pathname:e.location.pathname,matches:e.matches})'
        'dt(globalThis.location===void 0?e.pathname:globalThis.location.pathname||`/`)'
    )
    out = rw.js(bundle)
    for receiver in ("t", "window", "e", "globalThis"):
        # Every read is wrapped whole...
        assert f"__consolePath({receiver}.location.pathname)" in out
        # ...and no receiver is ever asked for a method it does not have.
        assert f"{receiver}.__consolePath" not in out


def test_a_pathname_read_is_rewritten_exactly_once():
    """The server pass and the shim can both see a value; a re-wrap must not stack."""
    rw = _PrefixRewriter(PREFIX)
    once = rw.js("x=window.location.pathname")
    assert once == "x=__consolePath(window.location.pathname)"
    assert rw.js(once) == once


def test_a_pathname_assignment_is_left_alone():
    """Wrapping an assignment target is a syntax error, not a redirect.

    ``=``, ``+=`` and ``??=`` all write; ``==``/``===``/``=>`` only read. The
    distinction matters more than it looks: a wrapped write target does not
    misbehave at run time, it fails to *parse*, which takes down every module
    sharing the file.
    """
    rw = _PrefixRewriter(PREFIX)
    src = (
        "location.pathname='/x';"
        "location.pathname += 'a';"
        "location.pathname ??= '/b';"
        "location.pathname==='/y';"
        "a=location.pathname;"
    )
    out = rw.js(src)
    assert "location.pathname='/x'" in out
    assert "location.pathname += 'a'" in out
    assert "location.pathname ??= '/b'" in out
    # Comparisons are reads.
    assert "__consolePath(location.pathname)==='/y'" in out
    assert "a=__consolePath(location.pathname)" in out


def test_a_computed_receiver_is_left_whole():
    """Only an identifier chain can be wrapped; half a member expression cannot.

    ``x[0].location.pathname`` is not a form this console's agents emit, and a
    wrong rewrite is worse than none -- it would move the property lookup onto
    the wrong object exactly the way the reported crash did.
    """
    rw = _PrefixRewriter(PREFIX)
    out = rw.js("y=x[0].location.pathname")
    assert out == "y=x[0].location.pathname"


def test_a_hard_navigation_is_handed_to_the_shim():
    """``location.assign('/')`` would leave the prefix, so the shim moves it.

    Measured in PicoClaw 0.3.1: a successful sign-in answers with
    ``globalThis.location.assign(`/`)``, a fresh workspace with
    ``.assign(`/launcher-setup`)``. Both are hard navigations to a prefix-less
    path, so the browser leaves ``/agents/<id>/`` and loads the console's own
    SPA inside the frame.

    A shim hook cannot catch them: in Chromium ``location.assign``,
    ``location.replace`` and the ``href`` accessor are all own,
    non-configurable properties of the ``Location`` instance (defining any of
    them throws). The bundle is rewritten to hand the call to the shim, which
    keeps the method's own semantics (``replace`` must not add a history entry).
    """
    rw = _PrefixRewriter(PREFIX)
    out = rw.js(
        "if(n.ok){globalThis.location.assign(`/`);return}"
        "if(n.status===409){globalThis.location.assign(`/launcher-setup`);return}"
        "i.replace?window.location.replace(t):window.location.href=t"
    )
    assert f"__consoleGo(globalThis.location,`/`,'assign')" in out
    assert f"__consoleGo(globalThis.location,`/launcher-setup`,'assign')" in out
    # ``replace`` keeps its name so the shim can call the replacing method.
    assert "__consoleGo(window.location,t,'replace')" in out
    # The ``href =`` spelling (PicoClaw's SSO chunk) is a navigation too.
    assert "__consoleGo(window.location,t,'assign')" in out
    # No raw hard navigation survives.
    assert "location.assign(" not in out.replace("__consoleGo(", "")
    assert "location.replace(" not in out.replace("__consoleGo(", "")


def test_a_href_comparison_is_not_a_navigation():
    """``href`` is also read; only a write is a navigation."""
    rw = _PrefixRewriter(PREFIX)
    for src in ("if(location.href==='/x'){}", "a=location.href===b",
                "x=>location.href", "s=String(location.href)"):
        assert rw.js(src) == src, src


def test_a_cross_origin_navigation_is_left_alone():
    """Another origin is not this proxy's business, and must still be reachable.

    The rewrite cannot decide by inspecting the argument -- it may be a variable
    -- so the shim's existing same-origin rule decides at run time. What the
    rewrite must not do is drop the call: an off-site redirect (an OAuth URL)
    has to keep working.
    """
    rw = _PrefixRewriter(PREFIX)
    out = rw.js("globalThis.location.assign('https://elsewhere.example/auth')")
    assert out == (
        "__consoleGo(globalThis.location,"
        "'https://elsewhere.example/auth','assign')")
    # A receiver that is not the page's own address bar is somebody else's
    # object; the rewrite must not touch it. ``frame.contentWindow.location``
    # is a *different* document, and an object with a ``location`` field is not
    # a Location at all -- moving either would navigate to the wrong URL.
    for src in ("router.assign('/x')", "cfg.location.assign('/x')",
                "frame.contentWindow.location.assign('/x')",
                "const p = w.location.href"):
        assert rw.js(src) == src, src


def test_css_urls_are_prefixed_and_absolute_ones_are_left_alone(app_with_agent):
    app, _upstream = app_with_agent
    with TestClient(app) as client:
        login(client)
        css = client.get(f"{PREFIX}/assets/index-abc123.css").text
    assert f"url({PREFIX}/assets/Inter.woff2)" in css
    assert f"url('{PREFIX}/assets/bg.png')" in css
    assert f'url("{PREFIX}/assets/bg2.png")' in css
    # Another origin is not this proxy's business.
    assert "url('https://elsewhere.example/x.png')" in css


def test_the_shim_is_injected_before_the_apps_own_scripts(app_with_agent):
    app, _upstream = app_with_agent
    with TestClient(app) as client:
        login(client)
        body = client.get(f"{PREFIX}/").text
    shim_at = body.index(f"{PREFIX}/_console_proxy.js")
    module_at = body.index(f"{PREFIX}/assets/index-abc123.js")
    assert shim_at < module_at
    # The app's module scripts still load as modules (the shim does not
    # downgrade them to classic scripts).
    assert 'type="module"' in body


def test_the_shim_is_served_by_the_console_not_forwarded(app_with_agent):
    app, upstream = app_with_agent
    with TestClient(app) as client:
        login(client)
        r = client.get(f"{PREFIX}/_console_proxy.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert "window.fetch" in r.text
    assert upstream.finds("/_console_proxy.js") == []


def test_the_shim_hooks_every_way_a_url_leaves_the_page():
    """The runtime half, checked where it is cheapest: in the served source."""
    js = _shim_js()
    for hook in ("window.fetch", "XMLHttpRequest.prototype.open", "window.WebSocket",
                 "EventSource", "pushState", "replaceState", "document.createElement",
                 "Element.prototype.setAttribute"):
        assert hook in js, hook
    # It reads its prefix from its own tag, so no inline script is needed (the
    # agent's CSP usually has no 'unsafe-inline' for scripts).
    assert "data-console-prefix" in js
    assert "currentScript" in js


def test_an_api_call_from_the_page_reaches_the_agent_under_the_prefix(app_with_agent):
    """The browser asks ``/agents/prox/global/health``; the agent sees ``/global/health``."""
    app, upstream = app_with_agent
    with TestClient(app) as client:
        login(client)
        r = client.get(f"{PREFIX}/global/health")
    assert r.status_code == 200
    assert r.json() == HEALTH
    assert upstream.finds("/global/health")


def test_a_post_keeps_its_body_and_presents_a_loopback_origin(app_with_agent):
    app, upstream = app_with_agent
    with TestClient(app) as client:
        login(client)
        r = client.post(f"{PREFIX}/session", json={"hello": "world"},
                        headers={"origin": "http://evil.example"})
    assert r.status_code == 200
    seen = r.json()
    assert seen["path"] == "/session"
    assert json.loads(seen["body"]) == {"hello": "world"}
    # The proxy has already authenticated the caller, so it presents the origin
    # the agent's config allows instead of trusting the browser's claim.
    assert seen["origin"] == "http://127.0.0.1:18080"
    assert upstream.finds("/session")


def test_the_proxy_supplies_the_agents_own_login(app_with_agent):
    """opencode 401s every request that does not carry basic auth.

    Without this the first asset request from an otherwise-logged-in page fails
    and the frame is blank -- the "still asks for a password" symptom.
    """
    app, upstream = app_with_agent
    with TestClient(app) as client:
        login(client)
        assert client.get(f"{PREFIX}/global/health").status_code == 200
    assert upstream.requests, "nothing reached the agent"
    assert upstream.requests[0]["headers"]["authorization"] == BASIC


def test_the_agent_still_requires_an_admin_session(app_with_agent):
    """The proxy is not a way around the console's own login."""
    app, upstream = app_with_agent
    with TestClient(app) as client:
        r = client.get(f"{PREFIX}/global/health")
    assert r.status_code == 401
    assert upstream.requests == []


def test_an_absolute_loopback_redirect_is_moved_under_the_prefix(app_with_agent):
    app, upstream = app_with_agent
    with TestClient(app, follow_redirects=False) as client:
        login(client)
        r = client.get(f"{PREFIX}/redirect")
    assert r.status_code == 302
    # Not ``/login`` (the console's own route) and not the loopback address.
    assert r.headers["location"] == f"{PREFIX}/login"
    assert str(upstream.port) not in r.headers["location"]


def test_cookies_are_narrowed_to_the_agents_subtree(app_with_agent):
    app, _upstream = app_with_agent
    with TestClient(app) as client:
        login(client)
        r = client.get(f"{PREFIX}/set-cookie")
    cookies = [v for k, v in r.headers.multi_items() if k.lower() == "set-cookie"]
    assert "session=abc; Path=/agents/prox/; HttpOnly" in cookies
    # A sub-path is kept, one level down, rather than flattened to the prefix.
    assert "theme=dark; Path=/agents/prox/settings" in cookies


def test_the_framing_refusal_is_still_relaxed_for_a_prefixed_agent(app_with_agent):
    app, _upstream = app_with_agent
    with TestClient(app) as client:
        login(client)
        r = client.get(f"{PREFIX}/")
    assert "x-frame-options" not in {k.lower() for k in r.headers}
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors 'self'" in csp
    assert "'none'" not in csp


def test_a_streamed_response_is_not_buffered_or_rewritten(app_with_agent):
    """SSE must arrive as it was sent; rewriting it would corrupt the stream."""
    app, _upstream = app_with_agent
    with TestClient(app) as client:
        login(client)
        r = client.get(f"{PREFIX}/stream")
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert r.text == "data: one\n\ndata: two\n\n"


def test_an_unknown_route_still_serves_the_spa_shell(app_with_agent):
    """The app's own routes are client-side; they must all reach the app."""
    app, _upstream = app_with_agent
    with TestClient(app) as client:
        login(client)
        r = client.get(f"{PREFIX}/session/abc123")
    assert r.status_code == 200
    assert f'src="{PREFIX}/assets/index-abc123.js"' in r.text


# -- unit-level: the rewriter and the cookie rule -------------------------

def test_the_rewriter_leaves_urls_it_must_not_touch():
    rw = _PrefixRewriter("/agents/x")
    html = (
        '<img src="/a.png"><img src="//cdn.example/b.png">'
        '<a href="https://example.com/c">c</a><a href="#frag">f</a>'
        '<script src="/agents/x/already.js"></script>'
    )
    out = rw.html(html)
    assert 'src="/agents/x/a.png"' in out
    assert 'src="//cdn.example/b.png"' in out          # protocol-relative
    assert 'href="https://example.com/c"' in out       # another origin
    assert 'href="#frag"' in out                       # fragment
    assert 'src="/agents/x/already.js"' in out         # idempotent


def test_a_cookie_without_a_path_is_confined_to_the_agent():
    assert _rewrite_cookie("a=1", True, "prox") == "a=1; Path=/agents/prox/"
    # A non-prefix agent keeps its cookie exactly as the agent wrote it.
    assert _rewrite_cookie("a=1; Path=/", False, "prox") == "a=1; Path=/"


def test_the_ws_keyword_is_chosen_from_the_installed_signature():
    """websockets renamed the handshake-header keyword in 14; both are pinned."""
    import inspect

    import websockets

    from app.api.agent_proxy import _ws_connect_kwargs

    kwargs = _ws_connect_kwargs([("Cookie", "a=1")])
    params = inspect.signature(websockets.connect).parameters
    assert set(kwargs) <= set(params), (kwargs, list(params))
    assert list(kwargs.values()) == [[("Cookie", "a=1")]]


# -- the two agents need different treatment at the bare prefix ------------

class BasePathSpec(PrefixSpec):
    """An OpenClaw-shaped agent: configured to serve itself under the prefix."""

    id = "path"
    prefix_root = False

    def upstream_basic_auth(self, secret):
        return None


def test_a_base_path_agent_is_proxied_at_the_bare_prefix_not_redirected(tmp_path):
    """OpenClaw's gateway expects ``/agents/openclaw`` verbatim; a 307 breaks it.

    The two shapes are both real, so the bare-prefix route has to answer each on
    its own terms: redirect for an origin-root app (its relative URLs need the
    slash), straight through for an app configured with this very path.
    """
    upstream = _Upstream(require_auth=False)
    with upstream:
        models = tmp_path / "models"
        models.mkdir()
        app = create_app(
            data_dir=tmp_path / "state", models_dir=models, backend_kind="mock",
            web_dir=tmp_path / "web", data_root=tmp_path / "root",
            agent_specs=[BasePathSpec()], service_port=18080,
        )
        mgr = app.state.agents
        d = mgr.directory("path")
        (d / "bin").mkdir(parents=True, exist_ok=True)
        (d / "bin" / "server.py").write_text("#!/bin/sh\n")
        st = mgr.state("path")
        st.port = upstream.port
        st.secret = "s3cr3t"
        mgr.save_state()
        mgr._runtime["path"].status = "running"

        class FakeProc:
            pid = 0
            returncode = None

            def send_signal(self, sig):
                pass

        mgr._runtime["path"].proc = FakeProc()

        with TestClient(app, follow_redirects=False) as client:
            login(client)
            r = client.get("/agents/path")
        # Not a redirect: the agent sees the path its basePath names.
        assert r.status_code == 200
        assert upstream.finds("/agents/path"), [x["path"] for x in upstream.requests]


_SHIM_HARNESS = r"""
const seen = [];
const seenInit = [];
globalThis.window = globalThis;
globalThis.location = new URL("http://board:8000/agents/prox/session/x");
globalThis.document = {currentScript: {getAttribute: () => "/agents/prox"},
                       createElement: () => ({}), addEventListener() {}};
globalThis.history = {pushState() {}, replaceState() {}};
globalThis.XMLHttpRequest = function () {};
XMLHttpRequest.prototype.open = function () {};
globalThis.WebSocket = function () {};
globalThis.fetch = async (input, init) => { seen.push(input); seenInit.push(init);
                                            return new Response("ok"); };
// A browser resolves a relative Request URL against the page; node does not.
const NativeRequest = Request;
// Chrome uploads a Request built from another Request's body as a stream,
// which needs HTTP/2; node buffers it, so flag the pattern itself.
let rewrappedBody = false;
globalThis.Request = function (u, init) {
  if (typeof u === "string" && u.startsWith("/")) u = new URL(u, location.href).href;
  if (init instanceof NativeRequest && init.body !== null) rewrappedBody = true;
  return new NativeRequest(u, init);
};
globalThis.HTMLElement = function () {};
globalThis.Element = function () {};
Element.prototype.setAttribute = function () {};
SHIM
(async () => {
  // opencode's SDK: a Request with a JSON body, addressed at the origin root.
  await window.fetch(new Request("http://board:8000/session/s1/prompt_async", {
    method: "POST", headers: {"content-type": "application/json"},
    body: JSON.stringify({parts: [{type: "text", text: "hi"}]})}));
  await window.fetch(new Request("http://board:8000/global/health"));
  const post = seen[0], get = seen[1];
  console.log(JSON.stringify({
    post_url: post.url, post_method: post.method,
    post_type: post.headers.get("content-type"),
    post_body: await post.text(), get_url: get.url, rewrapped_body: rewrappedBody}));
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(not __import__("shutil").which("node"), reason="needs node")
def test_shim_keeps_the_body_of_a_rewritten_post_request(tmp_path):
    """MYS-2293: re-wrapping a Request as new Request(url, request) turned its
    body into a stream; Chrome refused to upload it over HTTP/1.1 and opencode
    got an empty prompt ("Expected object, got undefined")."""
    import subprocess

    script = tmp_path / "shim.js"
    script.write_text(_SHIM_HARNESS.replace("SHIM", _shim_js()))
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["post_url"] == "http://board:8000/agents/prox/session/s1/prompt_async"
    assert got["post_method"] == "POST"
    assert got["post_type"] == "application/json"
    assert json.loads(got["post_body"]) == {"parts": [{"type": "text", "text": "hi"}]}
    assert got["get_url"] == "http://board:8000/agents/prox/global/health"
    assert got["rewrapped_body"] is False


# -- MYS-2410: multipart bodies and the withheld crypto.subtle --------------
#
# The reported bug was "the embedded opencode page cannot upload files or
# images". Two separate things had to hold for that to be provable, and the
# harness below pins both, running the *actual* JS the proxy serves rather than
# a copy of it.

_UPLOAD_HARNESS = r"""
const seen = [], seenInit = [];
globalThis.window = globalThis;
globalThis.location = new URL("http://board:8000/agents/prox/session/x");
globalThis.document = {currentScript: {getAttribute: () => "/agents/prox"},
                       createElement: () => ({}), addEventListener() {}};
globalThis.history = {pushState() {}, replaceState() {}};
globalThis.XMLHttpRequest = function () {};
XMLHttpRequest.prototype.open = function () {};
globalThis.WebSocket = function () {};
globalThis.fetch = async (input, init) => { seen.push(input); seenInit.push(init);
                                            return new Response("ok"); };
// The shim hands a plain string straight to the real fetch, so record both
// shapes: a value with ``.url`` for Request/URL inputs, the string otherwise.
const urlOf = v => (typeof v === "string" ? v : (v instanceof URL ? v.href : v.url));
const NativeRequest = Request;
globalThis.Request = function (u, init) {
  if (typeof u === "string" && u.startsWith("/")) u = new URL(u, location.href).href;
  return new NativeRequest(u, init);
};
globalThis.HTMLElement = function () {};
globalThis.Element = function () {};
Element.prototype.setAttribute = function () {};

SHIM

const hex = b => Array.from(new Uint8Array(b))
  .map(x => x.toString(16).padStart(2, "0")).join("");

function parseMultipart(buf, boundary) {
  // Split on the boundary the header *claims*, which is the whole point: a
  // re-encoded body that kept the old header would produce one giant part here.
  //
  // Parsed at the byte level on purpose. ``TextDecoder("latin1")`` is really
  // windows-1252 in both Node and the browsers, so it maps 0x89 to U+2030 and
  // silently corrupts exactly the non-ASCII bytes a PNG contains.
  const bytes = new Uint8Array(buf);
  const enc = new TextEncoder();
  const findFrom = (needle, from) => {
    outer: for (let i = from; i + needle.length <= bytes.length; i++) {
      for (let j = 0; j < needle.length; j++) {
        if (bytes[i + j] !== needle[j]) continue outer;
      }
      return i;
    }
    return -1;
  };
  const delim = enc.encode("--" + boundary);
  const crlfcrlf = enc.encode("\r\n\r\n");
  const parts = [];
  let at = findFrom(delim, 0);
  while (at !== -1) {
    const start = at + delim.length;
    const next = findFrom(delim, start);
    if (next === -1) break;
    // The bytes between two delimiters, minus the CRLF that precedes the next one.
    let end = next;
    if (end >= 2 && bytes[end - 2] === 0x0d && bytes[end - 1] === 0x0a) end -= 2;
    const chunk = bytes.subarray(start, end);
    const hp = findFrom(crlfcrlf, start);
    const headerEnd = hp === -1 || hp > end ? start : hp;
    const headers = new TextDecoder("utf-8").decode(bytes.subarray(start, headerEnd));
    const content = bytes.subarray(Math.min(headerEnd + 4, end), end);
    const name = /name="([^"]*)"/.exec(headers);
    const filename = /filename="([^"]*)"/.exec(headers);
    const ctype = /Content-Type:\s*([^\r\n]*)/i.exec(headers);
    parts.push({
      name: name ? name[1] : null,
      filename: filename ? filename[1] : null,
      content_type: ctype ? ctype[1].trim() : null,
      bytes: Array.from(content),
      text: new TextDecoder("utf-8").decode(content),
    });
    at = next;
  }
  return parts;
}

(async () => {
  const out = {};

  // --- 1. crypto.subtle: present or supplied, and numerically correct -----
  out.subtle_type = typeof crypto.subtle;
  out.subtle_digest_type = typeof (crypto.subtle || {}).digest;
  const enc = new TextEncoder();
  out.sha256 = {};
  for (const [label, input, want] of [
      ["empty", "", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],
      ["abc", "abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"],
      ["448bit", "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
       "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"],
      ["1000a", "a".repeat(1000),
       "41edece42d63e8d9bf515a9ba6932e1c20cbc9f5a5d134645adb5db1b9737ea3"],
      ["55byte", "a".repeat(55),
       "9f4390f8d30c2dd92ec9f095b65e2b9ae9b0a925a5258e241c9f1e910f734318"],
      ["56byte", "a".repeat(56),
       "b35439a4ac6f0948b6d6f9e3c6af0f5f590ce20f1bde7090ef7970686ec6738a"],
      ["64byte", "a".repeat(64),
       "ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb"],
  ]) {
    const got = hex(await crypto.subtle.digest("SHA-256", enc.encode(input)));
    out.sha256[label] = got === want ? "ok" : got;
  }
  // The digest must accept an ArrayBuffer as well as a view.
  const ab = new TextEncoder().encode("abc").buffer;
  out.sha256_arraybuffer =
    hex(await crypto.subtle.digest("SHA-256", ab)) ===
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
  // 2 MB, to prove it is not accidentally quadratic or block-size-limited.
  const big = new Uint8Array(2 * 1024 * 1024);
  for (let i = 0; i < big.length; i++) big[i] = i & 0xff;
  const t0 = Date.now();
  out.sha256_big = hex(await crypto.subtle.digest("SHA-256", big));
  out.sha256_big_ms = Date.now() - t0;
  // An unsupported algorithm must reject, never return a bogus digest.
  out.sha256_rejects_other =
    await crypto.subtle.digest("SHA-512", enc.encode("x")).then(() => "wrong", () => "rejected");

  // --- 2. Request + FormData through the shim ----------------------------
  // opencode's own upload shape: text field, a text file, a PNG.
  const png = Uint8Array.from([0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a,
                               0x00,0x00,0x00,0x0d,0x49,0x48,0x44,0x52,
                               0xff,0xfe,0x00,0x80,0x7f,0x01,0x02,0x03]);
  const fd = new FormData();
  fd.append("path", "notes/mys2410.txt");
  fd.append("file", new File([new TextEncoder().encode("MYS2410UPLOAD alpha-42\n")],
                             "mys2410-note.txt", {type: "text/plain"}));
  fd.append("image", new File([png], "mys2410-dot.png", {type: "image/png"}));

  const original = new Request("http://board:8000/session/s1/upload",
                               {method: "POST", body: fd});
  out.original_type = original.headers.get("content-type");
  await window.fetch(original);
  const sent = seen[seen.length - 1];
  const body = new Uint8Array(await sent.clone().arrayBuffer());

  out.sent_url = sent.url;
  out.sent_method = sent.method;
  out.sent_type = sent.headers.get("content-type");
  const boundary = (out.sent_type || "").split("boundary=")[1];
  out.has_boundary = !!boundary;
  out.body_mentions_boundary =
    boundary ? new TextDecoder("latin1").decode(body).includes(boundary) : false;
  out.parts = boundary ? parseMultipart(body, boundary) : [];
  out.part_names = out.parts.map(p => p.name);
  out.part_filenames = out.parts.map(p => p.filename);
  out.part_content_types = out.parts.map(p => p.content_type);
  out.png_bytes_ok = (() => {
    const part = (out.parts || []).find(p => p.filename === "mys2410-dot.png");
    return !!part && part.bytes.length === png.length &&
           part.bytes.every((v, i) => v === png[i]);
  })();
  out.reencoded = out.sent_type !== out.original_type;

  // --- 3. fetch(request, init): init must survive ------------------------
  const withInit = new Request("http://board:8000/session/s2/upload", {method: "POST", body: fd});
  const initSignal = new AbortController();
  await window.fetch(withInit, {credentials: "include", signal: initSignal.signal,
                                headers: {"x-console-init": "kept"}});
  out.init_passed_through = seenInit[seenInit.length - 1] != null;
  out.init_credentials = seenInit[seenInit.length - 1]?.credentials ?? null;
  out.init_header_seen = sent.headers.get("x-console-init");

  // --- 4. a plain string FormData POST is single-wrapped ------------------
  await window.fetch("http://board:8000/session/s3/upload", {method: "POST", body: fd});
  out.string_url = urlOf(seen[seen.length - 1]);

  console.log(JSON.stringify(out));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


@pytest.mark.skipif(not __import__("shutil").which("node"), reason="needs node")
def test_shim_preserves_a_multipart_request_and_the_init_argument(tmp_path):
    """MYS-2410: a ``Request`` built from ``FormData`` must arrive at the agent
    byte-for-byte, with the boundary its header claims.

    The MYS-2293 fix buffers the body and rebuilds the request. That is right
    for JSON, but a multipart body is only meaningful together with the exact
    boundary in ``content-type``: re-encoding the body while keeping the header
    (or dropping the header) gives the agent a request it cannot parse, which is
    indistinguishable from "uploads do not work".
    """
    import subprocess

    script = tmp_path / "upload.js"
    script.write_text(_UPLOAD_HARNESS.replace("SHIM", _shim_js()))
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])

    # The URL moved under the prefix and the method survived.
    assert got["sent_url"] == "http://board:8000/agents/prox/session/s1/upload"
    assert got["sent_method"] == "POST"

    # A multipart content-type, with a boundary, on both sides of the rewrite.
    assert got["original_type"].startswith("multipart/form-data; boundary="), got["original_type"]
    assert got["sent_type"].startswith("multipart/form-data; boundary="), got["sent_type"]
    assert got["has_boundary"] is True
    assert got["reencoded"] is False

    # The body is a real multipart body for *that* boundary.
    assert got["body_mentions_boundary"] is True
    assert got["part_names"] == ["path", "file", "image"], got["part_names"]
    assert got["part_filenames"] == [None, "mys2410-note.txt", "mys2410-dot.png"], \
        got["part_filenames"]
    assert got["part_content_types"] == [None, "text/plain", "image/png"], \
        got["part_content_types"]

    parts = {p["name"]: p for p in got["parts"]}
    assert parts["path"]["text"] == "notes/mys2410.txt"
    assert parts["file"]["text"] == "MYS2410UPLOAD alpha-42\n"
    # The PNG's bytes are not text: they must survive as bytes, including the
    # 0xff 0xfe / 0x00 0x80 sequence that a utf-8 round trip would mangle.
    assert got["png_bytes_ok"] is True, parts["image"]["bytes"]

    # ``fetch(request, init)`` must not silently drop init when it buffers.
    assert got["init_passed_through"] is True
    assert got["init_credentials"] == "include"

    # A string-addressed upload is rewritten too. A string comes back as a path
    # (the browser resolves it against the page) rather than an absolute URL.
    assert got["string_url"] == "/agents/prox/session/s3/upload"


@pytest.mark.skipif(not __import__("shutil").which("node"), reason="needs node")
def test_shim_supplies_sha256_when_the_browser_withholds_crypto_subtle(tmp_path):
    """MYS-2410: plain HTTP is not a secure context, so ``crypto.subtle`` is
    undefined on the board and opencode cannot hash an attachment.

    Measured against opencode 1.19.4: attaching any file throws
    ``TypeError: Cannot read properties of undefined (reading 'digest')`` from
    the composer's ``putBlob``, both through the proxy and straight from the
    agent's own port. The shim supplies the one algorithm the agents use.
    """
    import subprocess

    # Reproduce the board's browser exactly: crypto present, subtle withheld.
    # Node defines ``crypto`` as a getter-only accessor on the global, so a
    # plain assignment silently keeps the real one; it has to be redefined.
    harness = _UPLOAD_HARNESS.replace("SHIM", _shim_js())
    harness = harness.replace(
        "const seen = [], seenInit = [];",
        "const seen = [], seenInit = [];\n"
        "Object.defineProperty(globalThis, 'crypto', {configurable: true,\n"
        "  value: {getRandomValues(a){return a}, randomUUID(){return 'u'}}});\n"
        "if ('subtle' in globalThis.crypto) throw new Error('subtle should be absent');",
        1,
    )
    script = tmp_path / "subtle.js"
    script.write_text(harness)
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])

    assert got["subtle_type"] == "object"
    assert got["subtle_digest_type"] == "function"
    # Every NIST vector, including the 55/56/64-byte padding edges.
    assert all(v == "ok" for v in got["sha256"].values()), got["sha256"]
    assert got["sha256_arraybuffer"] is True
    assert got["sha256_rejects_other"] == "rejected"
    # 2 MiB must be fast enough that hashing a photo is not a stall.
    assert got["sha256_big_ms"] < 10000, got["sha256_big_ms"]

    # And the multipart path still works with the polyfill installed.
    assert got["part_filenames"] == [None, "mys2410-note.txt", "mys2410-dot.png"]


@pytest.mark.skipif(not __import__("shutil").which("node"), reason="needs node")
def test_the_polyfilled_digest_matches_node_crypto(tmp_path):
    """The shim's SHA-256 must equal a real implementation on random input.

    Vector tests only cover the shapes someone thought of; this compares against
    Node's own ``crypto.subtle`` for a spread of lengths, so an off-by-one in the
    padding cannot pass.
    """
    import subprocess

    harness = f"""
const {{ webcrypto }} = require("node:crypto");
globalThis.window = globalThis;
globalThis.location = new URL("http://board:8000/agents/prox/x");
globalThis.document = {{currentScript: {{getAttribute: () => "/agents/prox"}},
                       createElement: () => ({{}}), addEventListener() {{}}}};
globalThis.history = {{pushState() {{}}, replaceState() {{}}}};
globalThis.XMLHttpRequest = function () {{}};
XMLHttpRequest.prototype.open = function () {{}};
globalThis.WebSocket = function () {{}};
globalThis.fetch = async () => new Response("ok");
globalThis.HTMLElement = function () {{}};
globalThis.Element = function () {{}};
Element.prototype.setAttribute = function () {{}};
// Node's ``crypto`` is a getter-only global accessor: redefining it is the only
// way to model a browser where ``crypto`` exists but ``subtle`` does not.
Object.defineProperty(globalThis, "crypto", {{configurable: true,
  value: {{getRandomValues(a) {{return a}}}}}});
{_shim_js()}
const hex = b => Array.from(new Uint8Array(b))
  .map(x => x.toString(16).padStart(2, "0")).join("");
(async () => {{
  const bad = [];
  const lengths = [0,1,2,3,54,55,56,57,63,64,65,119,120,127,128,129,255,256,1000,4096,70000];
  for (const n of lengths) {{
    const data = new Uint8Array(n);
    for (let i = 0; i < n; i++) data[i] = (i * 31 + n) & 0xff;
    const mine = hex(await crypto.subtle.digest("SHA-256", data));
    const ref = hex(await webcrypto.subtle.digest("SHA-256", data));
    if (mine !== ref) bad.push({{n, mine, ref}});
  }}
  console.log(JSON.stringify({{checked: lengths.length, mismatches: bad}}));
}})().catch(e => {{ console.error(e); process.exit(1); }});
"""
    script = tmp_path / "compare.js"
    script.write_text(harness)
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["mismatches"] == [], got["mismatches"]
    assert got["checked"] >= 20
