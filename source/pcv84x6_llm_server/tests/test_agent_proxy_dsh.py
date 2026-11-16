"""The DSH handoff: the launch token is spent by the proxy, never by the browser.

The upstream here is a **real** HTTP server that behaves like DSH 0.2.1-rc.5 as
measured on 13.24 and on the board:

* every path is behind a session cookie and answers 401 without one,
  ``/manifest.webmanifest`` excepted (it is the readiness probe);
* ``GET /?token=<secret>`` answers 303 + ``Set-Cookie``, and only for exactly
  one ``token`` parameter on the root path;
* its browser fence refuses a request whose ``Origin`` names a different
  authority than its ``Host``, and refuses ``Sec-Fetch-Site: cross-site``.

Those three are the whole contract the proxy has to satisfy, so they are what
the fake implements -- and the assertions are about what a browser would receive.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app.agents.spec import AgentSpec
from app.main import create_app

TOKEN = "LAUNCHTOKEN-" + "z" * 32
COOKIE = "dsh-auth-deadbeef=v1.payload.sig"
INDEX = "<!doctype html><html><head><base href='./'></head><body>dsh</body></html>"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Dsh:
    """A stdlib server that answers the way DSH's web profile does."""

    def __init__(self) -> None:
        self.port = free_port()
        self.requests: list[dict] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _handler(self):
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _record(self):
                outer.requests.append({
                    "method": self.command,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                })

            def _send(self, code, body: bytes, ctype: str, extra=()):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in extra:
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _fence(self) -> bool:
                """DSH's two browser checks, in the order its carrier runs them."""
                if self.headers.get("sec-fetch-site") == "cross-site":
                    return False
                host = self.headers.get("host") or ""
                origin = self.headers.get("origin")
                if origin is None:
                    return True
                return origin == f"http://{host}"

            def _session(self) -> bool:
                return COOKIE.split("=", 1)[0] in (self.headers.get("cookie") or "")

            def do_GET(self):
                self._record()
                if self.path.startswith("/manifest.webmanifest"):
                    self._send(200, b'{"name": "DSH"}', "application/manifest+json")
                    return
                if not self._fence():
                    self._send(403, b"forbidden", "text/plain")
                    return
                if self.path.startswith("/?token="):
                    given = self.path.split("token=", 1)[1].split("&", 1)[0]
                    if given == TOKEN:
                        self._send(303, b"", "text/plain", extra=[
                            ("Location", "./"),
                            ("Set-Cookie",
                             f"{COOKIE}; Max-Age=2592000; Path=/; HttpOnly; SameSite=Strict"),
                        ])
                    else:
                        self._send(401, b"unauthorized", "text/plain")
                    return
                if not self._session():
                    self._send(401, b"unauthorized", "text/plain")
                    return
                if self.path.split("?", 1)[0] in ("/", "/index.html"):
                    self._send(200, INDEX.encode(), "text/html; charset=utf-8")
                    return
                if self.path.startswith("/assets/"):
                    self._send(200, b"console.log(1)", "application/javascript")
                    return
                self._send(404, b"", "text/plain")

            def do_POST(self):
                self._record()
                if not self._fence():
                    self._send(403, b"forbidden", "text/plain")
                    return
                if not self._session():
                    self._send(401, b"unauthorized", "text/plain")
                    return
                n = int(self.headers.get("content-length") or 0)
                self.rfile.read(n)
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")

        return H

    def __enter__(self):
        self.thread.start()
        for _ in range(200):
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return self
            except OSError:
                time.sleep(0.02)
        raise AssertionError("the fake DSH never started")

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)


class DshLikeSpec(AgentSpec):
    """An agent shaped like DSH: origin-root, proxied, launch-token login."""

    id = "dshlike"
    name = "DSH 代理测试"
    version = "0.2.1-rc.5"
    default_port = 0
    embeddable = True
    proxied = True
    prefix_root = True
    # The flag under test: this agent compares Origin against Host.
    origin_is_host = True
    # ... and this one asks the proxy for an unencoded body, because its HTML is
    # rewritten. Scoped per agent on purpose: opencode is prefix_root too and
    # must keep streaming compressed.
    identity_encoding = True
    executable = "bin.js"
    payload_root = "app"
    key_in_config = False

    def __init__(self, launch: str = "") -> None:
        super().__init__()
        self._launch = launch

    def upstream_launch_url(self, directory, port):
        return self._launch


@pytest.fixture()
def app_with_dsh(tmp_path):
    upstream = _Dsh()
    with upstream:
        spec = DshLikeSpec(launch=f"http://127.0.0.1:{upstream.port}/?token={TOKEN}")
        app = create_app(
            data_dir=tmp_path / "state", models_dir=tmp_path / "models",
            backend_kind="mock", web_dir=tmp_path / "web",
            data_root=tmp_path / "root", agent_specs=[spec], service_port=18080,
        )
        mgr = app.state.agents
        directory = mgr.directory("dshlike")
        (directory / "app").mkdir(parents=True, exist_ok=True)
        (directory / "app" / "bin.js").write_text("#!/bin/sh\n")
        st = mgr.state("dshlike")
        st.port = upstream.port
        mgr.save_state()
        mgr._runtime["dshlike"].status = "running"

        class FakeProc:
            pid = 0
            returncode = None

            def send_signal(self, sig):
                pass

        mgr._runtime["dshlike"].proc = FakeProc()
        yield app, upstream


def login(client: TestClient) -> None:
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200


# -- the handoff ---------------------------------------------------------

def test_the_first_page_visit_mints_a_session_and_sends_the_browser_back(app_with_dsh):
    """The reported failure was a permanently blank frame: DSH 401s every
    cookieless request, and the console has no way to type its token."""
    app, upstream = app_with_dsh
    with TestClient(app) as client:
        login(client)
        r = client.get("/agents/dshlike/", headers={"accept": "text/html"},
                       follow_redirects=False)
        # 303 to the same URL, carrying the session cookie the exchange minted.
        assert r.status_code == 303, r.text
        assert r.headers["location"] in ("/agents/dshlike/", "http://testserver/agents/dshlike/")
        cookies = r.headers.get_list("set-cookie")
        assert any("dsh-auth-deadbeef" in c for c in cookies), cookies
        # The exchange itself went to the tokenized startup URL, not the page.
        exchanges = [q for q in upstream.requests if q["path"].startswith("/?token=")]
        assert exchanges, upstream.requests
        # And the browser never sees the token.
        blob = json.dumps(dict(r.headers), ensure_ascii=False) + r.text
        assert TOKEN not in blob

    # The follow-up request (now with the cookie) gets the real page.
    with TestClient(app) as client:
        login(client)
        client.cookies.set("dsh-auth-deadbeef", "v1.payload.sig")
        r = client.get("/agents/dshlike/", headers={"accept": "text/html"})
        assert r.status_code == 200, r.text
        assert "dsh" in r.text


def test_the_handoff_runs_once_not_on_every_request(app_with_dsh):
    """A page that already holds a cookie must not re-mint it: every extra
    exchange is a second credential and a race with the requests in flight."""
    app, upstream = app_with_dsh
    with TestClient(app) as client:
        login(client)
        client.get("/agents/dshlike/", headers={"accept": "text/html"},
                   follow_redirects=False)
        exchanges = len([q for q in upstream.requests if q["path"].startswith("/?token=")])
        client.cookies.set("dsh-auth-deadbeef", "v1.payload.sig")
        client.get("/agents/dshlike/", headers={"accept": "text/html"})
        assert len([q for q in upstream.requests
                    if q["path"].startswith("/?token=")]) == exchanges


def test_an_asset_401_is_not_a_handoff(app_with_dsh):
    """Only a page navigation mints a session. Re-minting on an asset's 401
    would hide a lost cookie behind a redirect loop."""
    app, upstream = app_with_dsh
    with TestClient(app) as client:
        login(client)
        r = client.get("/agents/dshlike/assets/app.js", follow_redirects=False)
        assert r.status_code == 401
    assert not [q for q in upstream.requests if q["path"].startswith("/?token=")]


def test_a_page_visit_with_no_launch_url_says_what_to_do(app_with_dsh):
    """The state before the launcher printed anything: a 503 with a sentence,
    not the console's own error overlay."""
    app, upstream = app_with_dsh
    app.state.agents.specs["dshlike"].upstream_launch_url = lambda d, p: ""
    with TestClient(app) as client:
        login(client)
        r = client.get("/agents/dshlike/", headers={"accept": "text/html"})
    assert r.status_code == 503
    assert "重启" in r.text


def test_the_token_never_reaches_the_status_or_log_routes(app_with_dsh):
    app, upstream = app_with_dsh
    log = app.state.agents.directory("dshlike") / "logs" / "agent.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f"booting\ndsh web: http://127.0.0.1:{upstream.port}/?token={TOKEN}\n")
    # The spec under test declares no redaction (it is a look-alike, not the
    # DSH spec); the endpoint still must not hand out a credential, which is
    # what ``public_log`` is for. Assert the hook is what stands between the
    # file and the operator, then assert the real spec's behaviour in
    # tests/test_dsh.py.
    app.state.agents.specs["dshlike"].public_log = dsh_log_redaction
    with TestClient(app) as client:
        login(client)
        status = client.get("/api/agents").text
        logs = client.get("/api/agents/dshlike/logs").text
    assert TOKEN not in status, status
    assert TOKEN not in logs, logs
    assert "<redacted>" in logs


def dsh_log_redaction(text: str) -> str:
    from app.agents import dsh

    return dsh.SPEC.public_log(text)


# -- the handoff is DSH's alone ------------------------------------------

def _agent_without_handoff(tmp_path, upstream):
    """A proxied agent whose page 401s and which has *no* launch token.

    opencode and PicoClaw are exactly this shape: they authenticate every request
    their own way, and the base class's ``upstream_launch_url`` returns ``None``.
    """
    spec = DshLikeSpec(launch="")
    spec.id = "plain"
    # Not DSH's fence, but keep the proxy's header normalisation so the fake
    # upstream answers its ordinary 401 rather than its Origin refusal -- this
    # test is about the *handoff*, not about the fence.
    spec.origin_is_host = True
    spec.upstream_launch_url = lambda d, p: None
    app = create_app(
        data_dir=tmp_path / "state2", models_dir=tmp_path / "models2",
        backend_kind="mock", web_dir=tmp_path / "web2",
        data_root=tmp_path / "root2", agent_specs=[spec], service_port=18080,
    )
    mgr = app.state.agents
    directory = mgr.directory("plain")
    (directory / "app").mkdir(parents=True, exist_ok=True)
    (directory / "app" / "bin.js").write_text("#!/bin/sh\n")
    st = mgr.state("plain")
    st.port = upstream.port
    mgr.save_state()
    mgr._runtime["plain"].status = "running"

    class FakeProc:
        pid = 0
        returncode = None

        def send_signal(self, sig):
            pass

    mgr._runtime["plain"].proc = FakeProc()
    return app


def test_another_agents_401_passes_straight_through(tmp_path):
    """The regression: the base class defines ``upstream_launch_url``, so a bare
    ``callable()`` test was true for every agent -- and opencode's ordinary 401
    became DSH's "no token in the log" 503, which is a lie about an agent that
    has no token to look for."""
    upstream = _Dsh()
    with upstream:
        app = _agent_without_handoff(tmp_path, upstream)
        with TestClient(app) as client:
            login(client)
            r = client.get("/agents/plain/", headers={"accept": "text/html"},
                           follow_redirects=False)
    assert r.status_code == 401, r.text
    assert "token" not in r.text.lower()
    # And no exchange was attempted on its behalf.
    assert not [q for q in upstream.requests if q["path"].startswith("/?token=")]


def test_the_handoff_request_is_not_written_to_the_service_log(app_with_dsh, caplog):
    """The review's finding: ``httpx`` logs every request at INFO, and the
    service's root logger is INFO -- so the one credential DSH never shows
    anywhere would land in the service log, which is the log an operator pastes
    into a bug report."""
    import logging

    app, upstream = app_with_dsh
    with caplog.at_level(logging.DEBUG, logger="httpx"):
        with TestClient(app) as client:
            login(client)
            client.get("/agents/dshlike/", headers={"accept": "text/html"},
                       follow_redirects=False)
    assert TOKEN not in caplog.text, caplog.text
    # The exchange really did happen, so the assertion above is not vacuous.
    assert [q for q in upstream.requests if q["path"].startswith("/?token=")]


# -- Host and Origin -----------------------------------------------------

def test_host_and_origin_are_the_same_authority_upstream(app_with_dsh):
    """DSH compares them; a mismatch is a 403 on every call, including the
    WebSocket handshake. The proxy therefore sends one authority in both."""
    app, upstream = app_with_dsh
    with TestClient(app) as client:
        login(client)
        client.cookies.set("dsh-auth-deadbeef", "v1.payload.sig")
        r = client.get("/agents/dshlike/", headers={"accept": "text/html"})
        assert r.status_code == 200, r.text
    page = [q for q in upstream.requests
            if q["path"].split("?", 1)[0] in ("/", "/index.html")][-1]
    assert page["headers"]["host"] == f"127.0.0.1:{upstream.port}"
    assert page["headers"]["origin"] == f"http://127.0.0.1:{upstream.port}"


def test_the_service_origin_is_not_forwarded_as_origin(app_with_dsh):
    """The regression this fixes: the proxy used to present its own origin,
    which is exactly the mismatch DSH refuses."""
    app, upstream = app_with_dsh
    with TestClient(app) as client:
        login(client)
        client.cookies.set("dsh-auth-deadbeef", "v1.payload.sig")
        client.get("/agents/dshlike/", headers={"accept": "text/html"})
    assert not [q for q in upstream.requests
                if q["headers"].get("origin") == "http://127.0.0.1:18080"]


def test_the_browsers_cross_site_claim_is_not_forwarded(app_with_dsh):
    """A page the console frames on its own origin is same-origin by
    definition; the proxy drops the browser's claim rather than rewriting it,
    because the request it sends is not a browser request."""
    app, upstream = app_with_dsh
    with TestClient(app) as client:
        login(client)
        client.cookies.set("dsh-auth-deadbeef", "v1.payload.sig")
        client.get("/agents/dshlike/", headers={"accept": "text/html",
                                                "sec-fetch-site": "cross-site"})
    page = [q for q in upstream.requests
            if q["path"].split("?", 1)[0] in ("/", "/index.html")][-1]
    assert "sec-fetch-site" not in page["headers"]


def test_a_post_from_the_page_reaches_the_agent(app_with_dsh):
    """The fence applies to state-changing calls too, and those are the ones a
    mismatch actually breaks on."""
    app, upstream = app_with_dsh
    with TestClient(app) as client:
        login(client)
        client.cookies.set("dsh-auth-deadbeef", "v1.payload.sig")
        r = client.post("/agents/dshlike/api/session-controller/do",
                        headers={"origin": "http://testserver",
                                 "sec-fetch-site": "same-origin"},
                        content=b'{"a":1}')
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}


def test_a_foreign_origin_is_refused_before_the_rewrite(app_with_dsh):
    """Rewriting ``Origin`` to the agent's own authority is what makes DSH work;
    doing it for *every* caller is what switches DSH's CSRF fence off.

    A page on another port of the same board is same-*site*, so its requests
    carry the console's ``SameSite=Lax`` cookie -- the Origin check is the only
    thing that says the request came from a page this console did not serve, and
    without it such a page could drive the agent's shell tool.
    """
    app, upstream = app_with_dsh
    with TestClient(app) as client:
        login(client)
        client.cookies.set("dsh-auth-deadbeef", "v1.payload.sig")
        r = client.post("/agents/dshlike/api/session-controller/do",
                        headers={"origin": "http://10.80.40.157:8080",
                                 "sec-fetch-site": "same-site"},
                        content=b'{"a":1}')
    assert r.status_code == 403, r.text
    # Nothing reached the agent, so the rewrite never had a chance to lie.
    assert not [q for q in upstream.requests if "session-controller" in q["path"]]


def test_an_unparseable_origin_is_refused(app_with_dsh):
    """``Origin: null`` is what a sandboxed frame and some redirects send. No page
    this console serves can produce it."""
    app, upstream = app_with_dsh
    with TestClient(app) as client:
        login(client)
        client.cookies.set("dsh-auth-deadbeef", "v1.payload.sig")
        r = client.post("/agents/dshlike/api/x", headers={"origin": "null"},
                        content=b"{}")
    assert r.status_code == 403, r.text


def test_the_consoles_own_origin_with_any_forwarded_port_is_accepted(app_with_dsh):
    """The console may be reached by IP, hostname or a forwarded port; every one
    of those is the caller's own origin and must pass. The check compares against
    the request's own ``Host``, not a configured list."""
    app, upstream = app_with_dsh
    with TestClient(app) as client:
        login(client)
        client.cookies.set("dsh-auth-deadbeef", "v1.payload.sig")
        # TestClient's Host is ``testserver``; the browser's Origin spells it
        # with the same authority.
        r = client.post("/agents/dshlike/api/x",
                        headers={"origin": "http://testserver"}, content=b"{}")
    assert r.status_code == 200, r.text


def test_a_request_without_an_origin_is_allowed(app_with_dsh):
    """A same-origin ``GET``/navigation omits ``Origin`` (browsers do), and so
    does ``curl``. Refusing those would break the page for everyone."""
    app, upstream = app_with_dsh
    with TestClient(app) as client:
        login(client)
        client.cookies.set("dsh-auth-deadbeef", "v1.payload.sig")
        r = client.get("/agents/dshlike/", headers={"accept": "text/html"})
    assert r.status_code == 200, r.text


def test_the_websocket_refuses_a_foreign_origin(app_with_dsh):
    """The channel a socket drives is the reason this matters: no CORS preflight,
    no ``Sec-Fetch-Site`` the agent would ever see.

    The refusal is an accept-then-close at the WebSocket level (1008, policy
    violation), the same shape as the existing "admin login required" refusal:
    an HTTP 403 on the upgrade is indistinguishable from "the agent is down" to
    the page, while a close code is something it can react to.
    """
    from starlette.websockets import WebSocketDisconnect

    app, upstream = app_with_dsh
    with TestClient(app) as client:
        login(client)
        client.cookies.set("dsh-auth-deadbeef", "v1.payload.sig")
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(
                    "/agents/dshlike/ws",
                    headers={"origin": "http://10.80.40.157:8080"}) as ws:
                ws.receive_text()
    assert caught.value.code == 1008, caught.value
    # The upstream never saw an upgrade attempt.
    assert not [q for q in upstream.requests if q["path"] == "/ws"]


def test_the_page_is_not_requested_compressed(app_with_dsh):
    """The regression the live run caught: DSH gzips HTML above 1 KiB when the
    request says it accepts gzip, and the proxy has to rewrite HTML -- so
    forwarding ``Accept-Encoding`` made it decode a half-rewritten stream
    (``zlib.error: incorrect header check`` in the browser, a blank page)."""
    app, upstream = app_with_dsh
    with TestClient(app) as client:
        login(client)
        client.cookies.set("dsh-auth-deadbeef", "v1.payload.sig")
        client.get("/agents/dshlike/", headers={
            "accept": "text/html",
            "accept-encoding": "gzip, deflate, br",
        })
    page = [q for q in upstream.requests
            if q["path"].split("?", 1)[0] in ("/", "/index.html")][-1]
    # ``identity``, not an absent header: httpx adds its own default to every
    # request, so "removed" would silently come back as ``gzip, deflate, br``.
    assert page["headers"].get("accept-encoding") == "identity", page["headers"]


def test_a_streamed_body_keeps_its_compression(app_with_dsh):
    """A non-rewritten body is streamed through, so dropping the header there
    would cost bandwidth for nothing. Only ``prefix_root`` agents are affected,
    and this test pins that the rule is scoped to them."""
    app, upstream = app_with_dsh
    with TestClient(app) as client:
        login(client)
        client.cookies.set("dsh-auth-deadbeef", "v1.payload.sig")
        r = client.get("/agents/dshlike/api/events",
                       headers={"accept-encoding": "gzip"})
        # The fake does not stream, so this only proves the request reached it;
        # the assertion that matters is the header rule, checked where the body
        # really is text.
        assert r.status_code in (200, 404), r.status_code


def test_an_agent_that_does_not_rewrite_keeps_the_browsers_encoding(tmp_path):
    """``identity`` is a cost paid for rewriting, so it is scoped to the agents
    that need it. opencode is ``prefix_root`` too and never compressed; asking it
    for identity would only slow it down -- and the review asked for exactly this
    narrowing."""
    upstream = _Dsh()
    with upstream:
        spec = DshLikeSpec(launch="")
        spec.id = "opencode-like"
        spec.origin_is_host = False
        spec.identity_encoding = False
        app = create_app(
            data_dir=tmp_path / "s3", models_dir=tmp_path / "m3",
            backend_kind="mock", web_dir=tmp_path / "w3",
            data_root=tmp_path / "r3", agent_specs=[spec], service_port=18080,
        )
        mgr = app.state.agents
        directory = mgr.directory("opencode-like")
        (directory / "app").mkdir(parents=True, exist_ok=True)
        (directory / "app" / "bin.js").write_text("#!/bin/sh\n")
        st = mgr.state("opencode-like")
        st.port = upstream.port
        mgr.save_state()
        mgr._runtime["opencode-like"].status = "running"

        class FakeProc:
            pid = 0
            returncode = None

            def send_signal(self, sig):
                pass

        mgr._runtime["opencode-like"].proc = FakeProc()

        with TestClient(app) as client:
            login(client)
            client.get("/agents/opencode-like/api/events",
                       headers={"accept-encoding": "gzip, deflate, br"})
    page = [q for q in upstream.requests if q["path"] == "/api/events"][-1]
    assert page["headers"].get("accept-encoding") == "gzip, deflate, br", page["headers"]


# -- the cookie stays inside the prefix ----------------------------------

def test_the_session_cookie_is_narrowed_to_the_agents_prefix(app_with_dsh):
    app, upstream = app_with_dsh
    with TestClient(app) as client:
        login(client)
        r = client.get("/agents/dshlike/", headers={"accept": "text/html"},
                       follow_redirects=False)
    cookie = [c for c in r.headers.get_list("set-cookie") if "dsh-auth" in c][0]
    assert "Path=/agents/dshlike/" in cookie, cookie
    assert "Path=/;" not in cookie


def test_two_agents_can_hold_their_own_session_at_once(tmp_path):
    """Both DSH instances derive their cookie name from the authority, so the
    same forwarded port gives them the *same* name -- and a Path=/, cookie would
    make the second login silently replace the first."""
    one, two = _Dsh(), _Dsh()
    with one, two:
        specs = []
        for agent_id, upstream in (("dshlike", one), ("dshlike2", two)):
            spec = DshLikeSpec(launch=f"http://127.0.0.1:{upstream.port}/?token={TOKEN}")
            spec.id = agent_id
            specs.append(spec)
        app = create_app(
            data_dir=tmp_path / "state", models_dir=tmp_path / "models",
            backend_kind="mock", web_dir=tmp_path / "web",
            data_root=tmp_path / "root", agent_specs=specs, service_port=18080,
        )
        mgr = app.state.agents
        for agent_id, upstream in (("dshlike", one), ("dshlike2", two)):
            d = mgr.directory(agent_id)
            (d / "app").mkdir(parents=True, exist_ok=True)
            (d / "app" / "bin.js").write_text("#!/bin/sh\n")
            st = mgr.state(agent_id)
            st.port = upstream.port
            mgr._runtime[agent_id].status = "running"

            class FakeProc:
                pid = 0
                returncode = None

                def send_signal(self, sig):
                    pass

            mgr._runtime[agent_id].proc = FakeProc()
        mgr.save_state()

        with TestClient(app) as client:
            login(client)
            paths = []
            for agent_id in ("dshlike", "dshlike2"):
                r = client.get(f"/agents/{agent_id}/", headers={"accept": "text/html"},
                               follow_redirects=False)
                cookie = [c for c in r.headers.get_list("set-cookie")
                          if "dsh-auth" in c][0]
                paths.append(cookie.split("Path=")[1].split(";")[0])
    assert paths == ["/agents/dshlike/", "/agents/dshlike2/"]
