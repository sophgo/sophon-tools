"""OpenClaw's generated config, and the reverse proxy that makes it embeddable.

Two things are tested here that a unit test cannot fake into passing:

* ``write_config`` produces the exact document OpenClaw 2026.10.7 accepts. The
  field names were validated against the real ``openclaw config validate``, so
  this test is the regression guard for that shape.
* The proxy really forwards HTTP and WebSocket traffic to a live upstream and
  really rewrites the two framing headers. The upstream here is a stdlib HTTP
  server and a hand-rolled WebSocket echo, both started as real processes, so
  the assertions are about bytes on the wire rather than about mocks.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import os
import socket
import subprocess
import tarfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents import openclaw as openclaw_mod
from app.agents.openclaw import BASE_PATH, PROVIDER, OpenclawSpec
from app.agents.spec import AgentSpec, Artifact, InstallContext, ModelChoice, host_arch
from app.main import create_app

# -- expected config -------------------------------------------------------
OPENCLAW_EXPECTED = {
    "gateway": {
        "mode": "local",
        "port": 18790,
        "bind": "loopback",
        "auth": {"mode": "token", "token": "secret-token"},
        "controlUi": {
            "basePath": "/agents/openclaw",
            "allowedOrigins": ["http://127.0.0.1:18080", "http://localhost:18080"],
        },
    },
    "logging": {"file": "/tmp/agent/logs/openclaw.log"},
    "agents": {
        "defaults": {
            "model": {"primary": "cv84x6/test-32k"},
            "thinkingDefault": "off",
            "workspace": "/tmp/agent/workspace",
        },
    },
    "models": {
        "providers": {
            "cv84x6": {
                "baseUrl": "http://127.0.0.1:18080/v1",
                "apiKey": "sk-test-key",
                "api": "openai-completions",
                "timeoutSeconds": 1800,
                "models": [
                    {
                        "id": "test-32k",
                        "name": "test-32k",
                        "reasoning": True,
                        "input": ["text", "image"],
                        "contextWindow": 32768,
                        "maxTokens": 16384,
                        "compat": {
                            "maxTokensField": "max_tokens",
                            "thinkingFormat": "qwen",
                            "supportsTools": True,
                        },
                    },
                    {
                        "id": "test-128k",
                        "name": "test-128k",
                        "reasoning": True,
                        "input": ["text"],
                        "contextWindow": 131072,
                        "maxTokens": 16384,
                        "compat": {
                            "maxTokensField": "max_tokens",
                            "thinkingFormat": "qwen",
                            "supportsTools": True,
                        },
                    },
                ],
            },
        },
    },
    # The MCP server every install is preconfigured against. ``transport`` is
    # mandatory: an ``url`` alone makes OpenClaw assume SSE, which this endpoint
    # does not serve.
    "mcp": {
        "servers": {
            "cv84x6": {
                "url": "http://127.0.0.1:18080/mcp",
                "transport": "streamable-http",
                "headers": {"Authorization": "Bearer sk-test-key"},
                "enabled": True,
            },
        },
    },
}


def _ctx(**over) -> InstallContext:
    base = dict(
        service_port=18080,
        api_key="sk-test-key",
        models=[
            ModelChoice(id="test-32k", context=32768, vision=True),
            ModelChoice(id="test-128k", context=131072, vision=False),
        ],
        default_model="test-32k",
        thinking=False,
        secret="secret-token",
        port=18790,
    )
    base.update(over)
    return InstallContext(**base)


def test_openclaw_write_config_matches_the_contract_item_by_item(tmp_path):
    spec = OpenclawSpec()
    directory = Path("/tmp/agent")
    spec.write_config(directory, _ctx())
    path = spec.config_path(directory)
    assert path == directory / "config" / "openclaw.json"
    assert json.loads(path.read_text()) == OPENCLAW_EXPECTED
    # The plaintext API key and the gateway token are in the file.
    assert path.stat().st_mode & 0o777 == 0o600


def test_openclaw_max_tokens_is_half_the_context_capped_at_16384(tmp_path):
    """The cap matters: this board decodes ~20-30 tokens/s, so 16384 is 10-14 minutes."""
    spec = OpenclawSpec()
    cfg = spec.build_config(Path("/tmp/agent"), _ctx(models=[
        ModelChoice(id="small", context=4096),
        ModelChoice(id="mid", context=60000),
        ModelChoice(id="huge", context=131072),
    ]))
    got = {m["id"]: m["maxTokens"] for m in cfg["models"]["providers"][PROVIDER]["models"]}
    assert got == {"small": 2048, "mid": 16384, "huge": 16384}


def test_openclaw_context_window_is_always_written(tmp_path):
    """Without it OpenClaw assumes 200 000 tokens and overruns the model."""
    spec = OpenclawSpec()
    cfg = spec.build_config(Path("/tmp/agent"), _ctx(models=[
        ModelChoice(id="no-context-known", context=0),
    ]))
    entry = cfg["models"]["providers"][PROVIDER]["models"][0]
    assert entry["contextWindow"] == 2048  # the floor, never zero or absent


def test_openclaw_vision_models_advertise_image_input(tmp_path):
    spec = OpenclawSpec()
    cfg = spec.build_config(Path("/tmp/agent"), _ctx())
    entries = cfg["models"]["providers"][PROVIDER]["models"]
    assert entries[0]["input"] == ["text", "image"]
    assert entries[1]["input"] == ["text"]


def test_openclaw_thinking_default_follows_the_operator_setting(tmp_path):
    spec = OpenclawSpec()
    on = spec.build_config(Path("/tmp/agent"), _ctx(thinking=True))
    off = spec.build_config(Path("/tmp/agent"), _ctx(thinking=False))
    assert on["agents"]["defaults"]["thinkingDefault"] == "low"
    assert off["agents"]["defaults"]["thinkingDefault"] == "off"


def test_openclaw_existing_key_reads_back_from_its_own_config(tmp_path):
    spec = OpenclawSpec()
    spec.write_config(tmp_path, _ctx(api_key="sk-abc"))
    assert spec.existing_key(tmp_path) == "sk-abc"
    assert spec.existing_key(tmp_path / "nowhere") == ""


def test_openclaw_web_url_is_a_path_on_this_service_with_the_token_in_the_fragment():
    """The UI reads ``#token=``; a fragment never reaches a server log."""
    url = OpenclawSpec().web_url("172.26.166.96", 18790, "s3cr3t")
    assert url == f"{BASE_PATH}/#token=s3cr3t"
    assert not url.startswith("http")  # relative: works from any host


def test_openclaw_env_keeps_everything_inside_the_agent_tree(tmp_path):
    d = tmp_path / "agent"
    spec = OpenclawSpec()
    env = spec.env(d, "pw")
    assert env["HOME"] == str(d / "home")
    assert env["OPENCLAW_HOME"] == str(d / "home")
    assert env["OPENCLAW_STATE_DIR"] == str(d / "state")
    assert env["OPENCLAW_CONFIG_PATH"] == str(d / "config" / "openclaw.json")
    assert env["OPENCLAW_WORKSPACE_DIR"] == str(d / "workspace")
    assert env["NODE_COMPILE_CACHE"] == str(d / "cache" / "node")
    assert env["OPENCLAW_NO_RESPAWN"] == "1"
    assert env["TMPDIR"] == str(d / "tmp")
    # The private Node comes first on PATH; the system Node 22 must not win.
    assert env["PATH"].split(os.pathsep)[0] == str(d / "runtime" / "node" / "bin")
    # NODE_OPTIONS would actively *remove* OpenClaw's per-worker heap cap.
    assert "NODE_OPTIONS" not in env


def test_openclaw_command_uses_the_private_node_and_the_generated_port(tmp_path):
    d = tmp_path / "agent"
    spec = OpenclawSpec()
    cmd = spec.command(d, 18790)
    assert cmd[0] == str(d / "runtime" / "node" / "bin" / "node")
    assert cmd[1] == str(d / "app" / "node_modules" / "openclaw" / "openclaw.mjs")
    assert cmd[2:] == ["gateway", "run", "--port", "18790", "--bind", "loopback"]


def test_openclaw_declares_the_memory_its_own_measurement_needs():
    """The floor covers the measured startup peak (~1.55 GB, board 2026-10-26).

    Lower, a start proceeds into the OOM killer, which may choose the model
    worker -- and a worker killed mid-launch can hang the TPU. The idle board
    offers ~1.8 GB, so "unload the model, then start OpenClaw" still works;
    with a 35B model loaded (~1.1 GB free) the start is refused with a reason.
    """
    spec = OpenclawSpec()
    assert spec.memory_floor_bytes == 1600 * 1024 * 1024
    # And it is proxied, which is the only way its DENY-framing UI embeds.
    assert spec.proxied is True
    assert spec.embeddable is True
    assert spec.default_port != 18789  # OpenClaw's own default is left free


def test_openclaw_card_states_its_memory_cost_only():
    """The card answers one question: what does running this cost me?

    The capacity/co-existence wording it used to carry ("the board only has
    2.6 GB", "cannot run beside opencode or a model, the kernel will OOM it")
    was wrong twice over: it stated a fixed hardware size that differs per
    board, and it pre-empted a start-time memory check that already answers the
    fit question from the board's real MemAvailable. See
    ``test_agent_card_copy`` for the rule applied to all three agents.
    """
    note = OpenclawSpec().card_note
    assert note.startswith("预估内存：")
    assert "1.4 GB" in note  # measured idle, 10.42.0.242, 2026-10-27
    assert "1.9 GB" in note  # measured after a conversation


def test_openclaw_node_artifacts_are_pinned():
    spec = OpenclawSpec()
    for arch in ("arm64", "x64"):
        art = spec.artifacts[arch]
        assert len(art.sha256) == 64
        # dfss first (the board is offline in normal operation), upstream second.
        assert art.urls[0].startswith("dfss://")
        assert f"node-v{openclaw_mod.NODE_VERSION}-linux-{arch}.tar.xz" in art.urls[0]
        assert f"node-v{openclaw_mod.NODE_VERSION}-linux-{arch}.tar.xz" in art.urls[1]
        assert art.urls[1].startswith("https://nodejs.org/")


def test_openclaw_prebuilt_app_is_pinned_and_dfss_only():
    """The offline path is one archive on dfss; there is no upstream for it."""
    art = openclaw_mod.APP_ARTIFACTS["arm64"]
    assert art.urls == (
        "dfss://open@sophgo.com:/tools/cv84x6_llm_server/agents/"
        f"openclaw-{openclaw_mod.VERSION}-app-linux-arm64.tar.gz",
    )
    assert len(art.sha256) == 64
    assert art.size == 164854736
    # x64 has no prebuilt build: the spec falls back to npm there.
    assert "x64" not in openclaw_mod.APP_ARTIFACTS


def test_openclaw_shasums_cross_check_reads_the_listing():
    line = f"{'a' * 64}  node-v24.22.1-linux-arm64.tar.xz\n{'b' * 64}  other.tar.xz\n"
    assert openclaw_mod._checksum_for(line, "node-v24.22.1-linux-arm64.tar.xz") == "a" * 64
    assert openclaw_mod._checksum_for(line, "missing.tar.xz") == ""


async def test_openclaw_install_rejects_a_republished_node_tarball(tmp_path, monkeypatch):
    """A release whose published checksum no longer matches the pin is refused."""
    spec = OpenclawSpec()
    listing = tmp_path / openclaw_mod.SHASUMS_FILENAME
    listing.write_text(f"{'c' * 64}  node-v24.22.1-linux-arm64.tar.xz\n")

    async def fake_fetch(artifact, name, progress):
        # The listing is fetched through the same fetcher as everything else, so
        # its own pin is what the manager verified before this point.
        assert artifact is openclaw_mod.SHASUMS_ARTIFACT
        return listing

    with pytest.raises(openclaw_mod.AgentError, match="SHA256SUMS256"):
        await spec._verify_against_shasums(fake_fetch, "arm64", lambda d, t: None)


async def test_openclaw_shasums_are_read_from_dfss_before_nodejs(tmp_path):
    """The cross-check must work on a board that cannot reach nodejs.org."""
    spec = OpenclawSpec()
    listing = tmp_path / openclaw_mod.SHASUMS_FILENAME
    # A listing that agrees with the pin: the point here is *where* it comes
    # from, not what happens when it disagrees (that test is above).
    listing.write_text(
        f"{openclaw_mod.NODE_ARTIFACTS['arm64'].sha256}  node-v24.22.1-linux-arm64.tar.xz\n"
    )
    seen = []

    async def fake_fetch(artifact, name, progress):
        seen.append(artifact.urls)
        return listing

    await spec._verify_against_shasums(fake_fetch, "arm64", lambda d, t: None)
    urls = openclaw_mod.SHASUMS_ARTIFACT.urls
    assert urls[0].startswith("dfss://")
    assert urls[1].startswith("https://nodejs.org/")
    assert seen == [urls]
    # The listing's own sha256 is pinned, so an unverified one is never used.
    assert len(openclaw_mod.SHASUMS_SHA256) == 64


async def test_openclaw_install_skips_npm_when_the_prebuilt_package_is_there(
    tmp_path, monkeypatch,
):
    """The whole point of the archive: no npm, no registry, no network."""
    from app.agents import openclaw as mod

    spec = OpenclawSpec()
    directory = tmp_path / "agent"
    app_archive = _prebuilt_app_archive(tmp_path / "app.tar.gz")
    node_archive = _fake_node_archive(tmp_path / "node.tar.xz")

    async def fake_fetch(artifact, name, progress):
        if artifact is mod.SHASUMS_ARTIFACT:
            raise openclaw_mod.AgentError("校验失败：no listing here")
        if artifact is mod.APP_ARTIFACTS["arm64"]:
            return app_archive
        # Node: the prebuilt app make this an unpinned call, but the spec still
        # cross-checks the listing, which is absent here by design.
        return node_archive

    called = []

    async def fake_npm(self, d, report):
        called.append(d)

    monkeypatch.setattr(OpenclawSpec, "_npm_install", fake_npm)
    await spec.install(directory, fake_fetch, "arm64")

    assert called == []  # npm was never reached
    assert (directory / "app" / "node_modules" / "openclaw" / "openclaw.mjs").is_file()
    assert (directory / "runtime" / "node" / "bin" / "node").is_file()
    assert not (directory / "app" / "app").exists()  # no app/app nesting


async def test_openclaw_install_falls_back_to_npm_without_a_prebuilt_package(
    tmp_path, monkeypatch,
):
    spec = OpenclawSpec()
    directory = tmp_path / "agent"
    node_archive = _fake_node_archive(tmp_path / "node.tar.xz")

    async def fake_fetch(artifact, name, progress):
        if artifact is openclaw_mod.SHASUMS_ARTIFACT:
            raise openclaw_mod.AgentError("校验失败：no listing here")
        if artifact is openclaw_mod.APP_ARTIFACTS["arm64"]:
            raise openclaw_mod.AgentError("安装包下载失败：dfss://…: 连不上")
        return node_archive

    called = []

    async def fake_npm(self, d, report):
        called.append(Path(d))
        entry = Path(d) / "app" / "node_modules" / "openclaw" / "openclaw.mjs"
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text("// stub\n")

    monkeypatch.setattr(OpenclawSpec, "_npm_install", fake_npm)
    await spec.install(directory, fake_fetch, "arm64")

    assert called == [directory]


async def test_openclaw_x64_has_no_prebuilt_package_and_uses_npm(
    tmp_path, monkeypatch,
):
    """x64 has no prebuilt build, so npm is the prescribed path there."""
    spec = OpenclawSpec()
    directory = tmp_path / "agent"
    node_archive = _fake_node_archive(tmp_path / "node.tar.xz")

    async def fake_fetch(artifact, name, progress):
        if artifact is openclaw_mod.SHASUMS_ARTIFACT:
            raise openclaw_mod.AgentError("校验失败：no listing here")
        return node_archive

    called = []

    async def fake_npm(self, d, report):
        called.append(Path(d))
        entry = Path(d) / "app" / "node_modules" / "openclaw" / "openclaw.mjs"
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text("// stub\n")

    monkeypatch.setattr(OpenclawSpec, "_npm_install", fake_npm)
    await spec.install(directory, fake_fetch, "x64")
    assert called == [directory]


def _prebuilt_app_archive(path: Path) -> Path:
    """A tar.gz shaped like the one dfss holds: one top-level ``app/``."""
    entry = "app/node_modules/openclaw/openclaw.mjs"
    with tarfile.open(path, "w:gz") as tf:
        info = tarfile.TarInfo(entry)
        data = b"// stub\n"
        info.size = len(data)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(data))
    return path


def _fake_node_archive(path: Path) -> Path:
    """A tar.xz with a private Node inside, as the real one has."""
    with tarfile.open(path, "w:xz") as tf:
        info = tarfile.TarInfo("node-v24.22.1-linux-arm64/bin/node")
        data = b"#!/bin/sh\nexit 0\n"
        info.size = len(data)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(data))
    return path


# -- the reverse proxy -----------------------------------------------------
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveServer:
    """A real uvicorn server on a free port, stoppable from the test.

    Needed because the WebSocket routes only exist over an HTTP upgrade, which
    Starlette's TestClient cannot exercise: the proxy has to be reached by a
    real WebSocket client over a real socket.
    """

    def __init__(self, app) -> None:
        import uvicorn

        self.port = free_port()
        config = uvicorn.Config(
            app, host="127.0.0.1", port=self.port, log_level="error", ws="websockets",
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> "LiveServer":
        self.thread.start()
        for _ in range(400):
            if self.server.started:
                return self
            time.sleep(0.05)
        msg = "the service never started"
        raise AssertionError(msg)

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        # uvicorn's own loop needs a moment to unwind the listener; joining keeps
        # one test's socket out of the next test's free_port().
        self.thread.join(timeout=15)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def ws_headers(cookie: str) -> dict:
    """The handshake-header keyword this ``websockets`` version accepts.

    ``extra_headers`` (<=13) became ``additional_headers`` (>=14), and
    ``requirements-vendor.txt`` allows ``>=13,<15`` -- so both are live. Passing
    the wrong one is not a warning: 13.1 forwards it to the event loop's
    ``create_connection`` and raises ``TypeError``, so these two tests failed on
    an install that met its own pin. Detected from the signature, the same way
    ``app/api/agent_proxy.py`` does it for the server side.
    """
    import inspect

    import websockets

    params = inspect.signature(websockets.connect).parameters
    name = "additional_headers" if "additional_headers" in params else "extra_headers"
    return {name: [("Cookie", cookie)]}



PROXY_PATH = "/agents/prox"  # the proxy serves /agents/<spec id>/


class ProxiedSpec(AgentSpec):
    """A spec that points the proxy at a real local server."""

    id = "prox"
    name = "代理测试 agent"
    version = "1.0.0"
    default_port = 0
    embeddable = True
    proxied = True
    memory_floor_bytes = 0
    executable = "server.py"
    payload_root = "bin"
    key_in_config = False


@pytest.fixture()
def upstream_http():
    """A stdlib HTTP server that sends OpenClaw's refusing headers."""
    port = free_port()
    handler = type("Handler", (), {})
    # The script is imported into this process: it is a real socket server, but
    # running it in-thread keeps the fixture simple and its lifecycle certain.
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="text/html", extra=()):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; frame-ancestors 'none'; script-src 'self'",
            )
            self.send_header("Set-Cookie", "a=1; Path=/")
            self.send_header("Set-Cookie", "b=2; Path=/")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.endswith("/redirect"):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{port}/elsewhere")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path.endswith("/echo-headers"):
                body = json.dumps({k.lower(): v for k, v in self.headers.items()}).encode()
                self._send(200, body, "application/json")
                return
            self._send(200, b"<html><body>upstream ui</body></html>")

        def do_POST(self):
            n = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(n)
            body = json.dumps({
                "got": raw.decode(),
                "origin": self.headers.get("origin"),
                "host": self.headers.get("host"),
            }).encode()
            self._send(200, body, "application/json")

    server = ThreadingHTTPServer(("127.0.0.1", port), H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def ws_echo_upstream():
    """A real WebSocket echo server on a system-assigned port.

    A real server rather than a mock because the thing under test is the byte
    path: the proxy has to complete an RFC 6455 handshake and relay frames.
    Port 0 keeps parallel runs from colliding on a fixed number.
    """
    import hashlib

    async def echo(reader, writer):
        try:
            request = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, ConnectionError):
            return
        key = ""
        for line in request.decode("latin-1").split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        writer.write(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
        )
        await writer.drain()
        while True:
            try:
                head = await reader.readexactly(2)
            except (asyncio.IncompleteReadError, ConnectionError):
                return
            opcode = head[0] & 0x0F
            masked = head[1] & 0x80
            length = head[1] & 0x7F
            if length == 126:
                length = int.from_bytes(await reader.readexactly(2), "big")
            elif length == 127:
                length = int.from_bytes(await reader.readexactly(8), "big")
            mask = await reader.readexactly(4) if masked else b"\0\0\0\0"
            payload = bytearray(await reader.readexactly(length)) if length else bytearray()
            for i in range(length):
                payload[i] ^= mask[i % 4]
            if opcode == 8:
                writer.write(bytes([0x88, 0x00]))
                await writer.drain()
                return
            if opcode == 9:
                writer.write(bytes([0x8A, len(payload)]) + bytes(payload))
                await writer.drain()
                continue
            body = bytes(payload)
            # Server-to-client frames are never masked.
            writer.write(bytes([0x81, len(body)]) + body)
            await writer.drain()

    holder: dict = {}

    def run():
        loop = asyncio.new_event_loop()
        holder["loop"] = loop

        async def main():
            server = await asyncio.start_server(echo, "127.0.0.1", 0)
            holder["server"] = server
            holder["port"] = server.sockets[0].getsockname()[1]
            async with server:
                await server.serve_forever()

        try:
            loop.run_until_complete(main())
        except (asyncio.CancelledError, RuntimeError):
            pass

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    for _ in range(200):
        if "port" in holder:
            break
        time.sleep(0.05)
    else:
        pytest.fail("the echo upstream never started")
    try:
        yield holder["port"]
    finally:
        loop, server = holder.get("loop"), holder.get("server")
        if server is not None and loop is not None:
            loop.call_soon_threadsafe(server.close)


def make_app(tmp_path: Path, service_port: int, agent_port: int, spec: AgentSpec | None = None):
    """An app whose single agent is already installed and pointed at ``agent_port``."""
    models = tmp_path / "models"
    models.mkdir(exist_ok=True)
    spec = spec or ProxiedSpec()
    app = create_app(
        data_dir=tmp_path / "state", models_dir=models, backend_kind="mock",
        web_dir=tmp_path / "web", data_root=tmp_path / "root",
        agent_specs=[spec], service_port=service_port,
    )
    mgr = app.state.agents
    # Installed, running, on a port we control: the proxy only cares about the
    # manager's answer, and this is the answer a live upstream would produce.
    directory = mgr.directory(spec.id)
    (directory / "bin").mkdir(parents=True, exist_ok=True)
    (directory / "bin" / spec.executable).write_text("#!/bin/sh\n")
    st = mgr.state(spec.id)
    st.port = agent_port
    st.secret = "proxied-secret"
    mgr.save_state()
    mgr._runtime[spec.id].status = "running"

    # A real, harmless process in its own session stands in for the agent.
    # Never this test's own pid: stopping the "agent" signals its process
    # group, and pytest's group is the shell that runs it.
    stand_in = subprocess.Popen(["sleep", "300"], start_new_session=True)
    _STAND_INS.append(stand_in)

    class FakeProc:
        pid = stand_in.pid
        returncode = None

        def send_signal(self, sig):
            stand_in.send_signal(sig)

    mgr._runtime[spec.id].proc = FakeProc()
    return app, mgr


_STAND_INS: list = []


@pytest.fixture(autouse=True)
def _reap_stand_ins():
    yield
    while _STAND_INS:
        p = _STAND_INS.pop()
        if p.poll() is None:
            p.kill()
        p.wait()


def login(client: TestClient) -> None:
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200


def test_proxy_requires_an_admin_session(tmp_path, upstream_http):
    app, _ = make_app(tmp_path, 18080, upstream_http)
    with TestClient(app) as client:
        r = client.get(f"{PROXY_PATH}/")
        assert r.status_code == 401
        assert r.json()["detail"] == "admin login required"


def test_proxy_strips_x_frame_options_and_relaxes_frame_ancestors(tmp_path, upstream_http):
    """The whole point: the console may frame it, nobody else may."""
    app, _ = make_app(tmp_path, 18080, upstream_http)
    with TestClient(app) as client:
        login(client)
        r = client.get(f"{PROXY_PATH}/")
    assert r.status_code == 200
    assert "upstream ui" in r.text
    assert "x-frame-options" not in {k.lower() for k in r.headers}
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors 'self'" in csp
    assert "'none'" not in csp
    # Everything else in the policy is untouched.
    assert "script-src 'self'" in csp


def test_proxy_preserves_multiple_set_cookie_headers(tmp_path, upstream_http):
    app, _ = make_app(tmp_path, 18080, upstream_http)
    with TestClient(app) as client:
        login(client)
        r = client.get(f"{PROXY_PATH}/")
    cookies = [v for k, v in r.headers.multi_items() if k.lower() == "set-cookie"]
    assert sorted(cookies) == ["a=1; Path=/", "b=2; Path=/"]


def test_proxy_forwards_the_body_and_presents_a_loopback_origin(tmp_path, upstream_http):
    """The gateway checks Origin; the proxy has already authenticated, so it
    presents the loopback origin rather than the browser's claim."""
    app, _ = make_app(tmp_path, 18080, upstream_http)
    with TestClient(app) as client:
        login(client)
        r = client.post(f"{PROXY_PATH}/echo", json={"hello": "world"},
                        headers={"origin": "http://evil.example"})
    assert r.status_code == 200
    seen = r.json()
    assert json.loads(seen["got"]) == {"hello": "world"}
    assert seen["origin"] == "http://127.0.0.1:18080"
    assert seen["host"] == f"127.0.0.1:{upstream_http}"


def test_proxy_rewrites_a_loopback_redirect_to_a_relative_location(tmp_path, upstream_http):
    """The browser cannot reach the agent's own port, so an absolute redirect
    to it would leave the console on a dead address."""
    app, _ = make_app(tmp_path, 18080, upstream_http)
    with TestClient(app, follow_redirects=False) as client:
        login(client)
        r = client.get(f"{PROXY_PATH}/redirect")
    assert r.status_code == 302
    assert r.headers["location"] == "/elsewhere"


def test_proxy_refuses_an_agent_that_is_not_proxied(tmp_path):
    """opencode keeps its own origin; only a proxied agent gets this path."""

    class NotProxied(ProxiedSpec):
        id = "plain"
        proxied = False

    models = tmp_path / "models"
    models.mkdir()
    app = create_app(
        data_dir=tmp_path / "state", models_dir=models, backend_kind="mock",
        web_dir=tmp_path / "web", data_root=tmp_path / "root",
        agent_specs=[NotProxied()], service_port=18080,
    )
    with TestClient(app) as client:
        login(client)
        assert client.get("/agents/plain/").status_code == 404


def test_proxy_reports_a_stopped_agent_as_a_conflict(tmp_path, upstream_http):
    app, mgr = make_app(tmp_path, 18080, upstream_http)
    with TestClient(app) as client:
        login(client)
        mgr._runtime["prox"].proc = None
        r = client.get(f"{PROXY_PATH}/")
    assert r.status_code == 409
    assert "没有在运行" in r.json()["detail"]


def test_websocket_proxy_relays_frames_both_ways(tmp_path, upstream_http):
    """A real WebSocket echo behind the proxy, driven by a real client.

    The Control UI is a WebSocket client; a proxy that forwards HTTP but not
    the upgrade shows a page that loads and then never connects.
    """
    import websockets

    ws_port = free_port()

    # A minimal RFC 6455 echo server: real handshake, real frames.
    async def echo(reader, writer):
        request = await reader.readuntil(b"\r\n\r\n")
        key = ""
        for line in request.decode("latin-1").split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        import hashlib
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        writer.write(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
        )
        await writer.drain()
        while True:
            try:
                head = await reader.readexactly(2)
            except (asyncio.IncompleteReadError, ConnectionError):
                return
            opcode = head[0] & 0x0F
            masked = head[1] & 0x80
            length = head[1] & 0x7F
            if length == 126:
                length = int.from_bytes(await reader.readexactly(2), "big")
            elif length == 127:
                length = int.from_bytes(await reader.readexactly(8), "big")
            mask = await reader.readexactly(4) if masked else b"\0\0\0\0"
            payload = bytearray(await reader.readexactly(length)) if length else bytearray()
            for i in range(length):
                payload[i] ^= mask[i % 4]
            if opcode == 8:
                writer.write(bytes([0x88, 0x00]))
                await writer.drain()
                return
            if opcode == 9:  # ping -> pong
                writer.write(bytes([0x8A, len(payload)]) + bytes(payload))
                await writer.drain()
                continue
            body = bytes(payload)
            # Client-to-server frames are masked; server-to-client must not be.
            writer.write(bytes([0x81, len(body)]) + body)
            await writer.drain()

    loop_holder: dict = {}

    def run_upstream():
        loop = asyncio.new_event_loop()
        loop_holder["loop"] = loop

        async def main():
            server = await asyncio.start_server(echo, "127.0.0.1", ws_port)
            loop_holder["server"] = server
            async with server:
                await server.serve_forever()

        try:
            loop.run_until_complete(main())
        except (asyncio.CancelledError, RuntimeError):
            pass

    thread = threading.Thread(target=run_upstream, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", ws_port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    else:
        pytest.fail("the echo upstream never started")

    app, _ = make_app(tmp_path, 18080, ws_port)

    async def drive(base_url: str) -> list[str]:
        import httpx as _httpx

        # Log in over HTTP first: the WebSocket route reads the same cookie.
        async with _httpx.AsyncClient(base_url=base_url) as client:
            r = await client.post("/api/login", json={"password": "admin"})
            assert r.status_code == 200
            cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items())

        got = []
        async with websockets.connect(
            f"ws://127.0.0.1:{ws_service_port}/agents/prox/socket",
            open_timeout=10, **ws_headers(cookie),
        ) as ws:
            for text in ("first", "second", "中文"):
                await ws.send(text)
                got.append(await asyncio.wait_for(ws.recv(), timeout=10))
        return got

    try:
        with LiveServer(app) as live:
            ws_service_port = live.port
            got = asyncio.run(drive(live.base_url))
    finally:
        server = loop_holder.get("server")
        loop = loop_holder.get("loop")
        if server is not None and loop is not None:
            loop.call_soon_threadsafe(server.close)
    assert got == ["first", "second", "中文"]


def test_websocket_proxy_closes_an_unauthenticated_upgrade(tmp_path, upstream_http):
    """No session cookie means no socket, and a clean close rather than a hang."""
    import websockets

    app, _ = make_app(tmp_path, 18080, upstream_http)

    async def drive(port: int):
        async with websockets.connect(
            f"ws://127.0.0.1:{port}/agents/prox/socket", open_timeout=10,
        ) as ws:
            await asyncio.wait_for(ws.recv(), timeout=5)
        return None

    with LiveServer(app) as live:
        try:
            code = asyncio.run(drive(live.port))
        except websockets.exceptions.ConnectionClosed as exc:
            code = exc.code
        except Exception as exc:  # noqa: BLE001 - the close is what matters
            code = type(exc).__name__
    assert code == 1008


def test_websocket_proxy_accepts_the_bare_base_path(tmp_path, ws_echo_upstream):
    """``<origin>/agents/openclaw`` -- no trailing slash -- must upgrade.

    Measured on the board: OpenClaw 2026.10.7's Control UI derives its default
    gateway URL from ``controlUi.basePath`` with no trailing slash. Starlette's
    ``{path:path}`` matches the empty string, so the HTTP route swallowed that
    URL and answered the upgrade with 403: the embedded panel showed "Gateway
    unreachable" while ``/agents/openclaw/`` worked. The UI is not ours to
    patch, so the proxy has to serve the URL the UI really uses.
    """
    import websockets

    app, _ = make_app(tmp_path, 18080, ws_echo_upstream)

    async def drive(port: int):
        import httpx as _httpx

        async with _httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            assert (await client.post("/api/login", json={"password": "admin"})).status_code == 200
            cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
        # Exactly the URL the Control UI asks for: the prefix, nothing after it.
        async with websockets.connect(
            f"ws://127.0.0.1:{port}/agents/prox",
            open_timeout=10, **ws_headers(cookie),
        ) as ws:
            await ws.send("hello")
            return [await asyncio.wait_for(ws.recv(), timeout=10)]

    with LiveServer(app) as live:
        assert asyncio.run(drive(live.port)) == ["hello"]
