"""The MCP server entry in the three agents' configs, over the real lifecycle.

The card's requirements are behavioural, so the tests are too:

* **installed** -> the agent's config names this service's MCP endpoint;
* **reset** -> the config is rewritten and still names it (reset wipes
  ``config/`` and writes a fresh one with a *new* key, so a stale entry would
  leave the agent presenting a revoked key);
* **sync** -> same, and the key in the MCP header follows the key in the provider
  block;
* **the operator's own servers survive** all three.

The last one is the requirement most easily got wrong: a config rewrite that
rebuilt the block from nothing would delete a server the operator added from the
agent's own UI, and nothing in the service would ever mention it again.

These drive the real ``AgentManager`` with a fake agent (the same one
``tests/test_agents.py`` installs), so "install writes the config" is tested
against the code path that really runs, not against ``write_config`` alone.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import tarfile
import textwrap
from pathlib import Path

import pytest

from app.agents import openclaw as openclaw_mod
from app.agents import opencode as opencode_mod
from app.agents import picoclaw as picoclaw_mod
from app.agents.manager import AgentManager
from app.agents.spec import (
    MCP_SERVER_NAME,
    AgentSpec,
    Artifact,
    InstallContext,
    ModelChoice,
    mcp_url,
)

# A real server, packed into a real tar.gz: the manager's install path unpacks it
# and the health probe talks to it, so mocking the subprocess would test nothing.
FAKE_AGENT = """\
import http.server, json, socketserver, sys
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def do_GET(self):
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
class Server(socketserver.TCPServer):
    allow_reuse_address = True
port = int(sys.argv[sys.argv.index('--port') + 1])
Server(('0.0.0.0', port), Handler).serve_forever()
"""


def tarball(path: Path, payload: dict[str, str]) -> Path:
    with tarfile.open(path, "w:gz") as tf:
        for name, content in payload.items():
            data = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return path


class ConfSpec(AgentSpec):
    """One of the three real specs, with a local artifact and a fake command.

    Subclassing the real class rather than building a look-alike keeps the
    *config* code under test exactly the shipped code: ``write_config``,
    ``build_config`` and the MCP block are the real methods. Only the payload
    and the run command are replaced, because the board's binaries are not on a
    build host.
    """

    start_timeout = 30.0

    def __init__(self, base, artifact: Artifact, executable: str, **over) -> None:
        self._base = base
        self.artifacts = {a: artifact for a in ("arm64", "x64")}
        self.executable = executable
        self.payload_root = "bin"
        self.key_in_config = True
        self.scratch_paths = ()
        for key, value in over.items():
            setattr(self, key, value)

    # -- delegate the config behaviour to the real spec -------------------
    def config_path(self, directory: Path) -> Path:
        return self._base.config_path(directory)

    def write_config(self, directory: Path, ctx: InstallContext) -> None:
        self._base.write_config(directory, ctx)

    def build_config(self, *args, **kwargs):
        return self._base.build_config(*args, **kwargs)

    def existing_key(self, directory: Path) -> str:
        return self._base.existing_key(directory)

    def env(self, directory: Path, secret: str = "") -> dict[str, str]:
        return self._base.env(directory, secret)

    def command(self, directory: Path, port: int) -> list[str]:
        import sys

        return [sys.executable, str(Path(directory) / "bin" / "agent"), "--port", str(port)]

    def health_url(self, port: int) -> str:
        return f"http://127.0.0.1:{port}/health"


REAL = {
    "picoclaw": picoclaw_mod.SPEC,
    "opencode": opencode_mod.SPEC,
    "openclaw": openclaw_mod.SPEC,
}

#: Where each agent's MCP servers live in its config, and what one entry looks
#: like. The JSON paths come from the agents' own schemas -- see docs/mcp.md.
PROBE = {
    "picoclaw": (("tools", "mcp", "servers"), "type"),
    "opencode": (("mcp",), "type"),
    "openclaw": (("mcp", "servers"), "transport"),
}


def read_servers(agent_id: str, directory: Path) -> dict:
    spec = REAL[agent_id]
    data = json.loads(spec.config_path(directory).read_text())
    node = data
    for key in PROBE[agent_id][0]:
        node = node.get(key) or {}
    return node


@pytest.fixture()
def manager(tmp_path: Path, monkeypatch):
    """An AgentManager whose three agents are the real specs with local artifacts."""
    artifact = tarball(tmp_path / "agent.tar.gz", {
        "agent": FAKE_AGENT,
        "picoclaw-launcher": "#!/bin/sh\n",
    })
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    art = Artifact(urls=(f"file://{artifact}",), sha256=digest)

    specs = []
    for agent_id, base in REAL.items():
        spec = ConfSpec(base, art, "agent")
        # Instance attributes the class body would otherwise supply.
        spec.id = agent_id
        spec.name = base.name
        spec.version = base.version
        spec.default_port = base.default_port
        specs.append(spec)

    monkeypatch.setattr(AgentManager, "_check_memory", lambda self, spec: None)
    mgr = AgentManager(
        tmp_path / "root",
        key_store=_Store(),
        models=_Models(),
        service_port=18080,
        specs=specs,
        start_timeout_override=20.0,
    )
    return mgr


class _Store:
    """The minimum key store the manager needs: create, revoke, list."""

    def __init__(self) -> None:
        self._keys: list = []

    class _Key:
        def __init__(self, kid: str, name: str) -> None:
            self.id = kid
            self.name = name
            self.revoked = False
            self.key_hash = ""

    def create_key(self, name: str):
        raw = f"sk-{len(self._keys)}-{name}"
        key = self._Key(f"k{len(self._keys)}", name)
        self._keys.append(key)
        return raw, key

    @property
    def keys(self):
        return self._keys

    def revoke_key(self, key_id: str) -> bool:
        for key in self._keys:
            if key.id == key_id:
                key.revoked = True
                return True
        return False

    def save(self) -> None:
        return None


class _Models:
    def list(self):
        return []

    def loaded_count(self) -> int:
        return 0


async def install(manager, agent_id: str) -> None:
    job = await manager.install(agent_id)
    for _ in range(600):
        if job.state in ("done", "error"):
            break
        await asyncio.sleep(0.05)
    assert job.state == "done", job.message


@pytest.mark.parametrize("agent_id", ["picoclaw", "opencode", "openclaw"])
async def test_install_writes_the_mcp_server(manager, agent_id):
    await install(manager, agent_id)
    directory = manager.directory(agent_id)
    servers = read_servers(agent_id, directory)
    assert MCP_SERVER_NAME in servers, servers
    entry = servers[MCP_SERVER_NAME]
    assert entry["url"] == mcp_url(18080) == "http://127.0.0.1:18080/mcp"
    assert entry["enabled"] is True
    # The key in the header is the key the provider block got: one install, one
    # key, so an operator reading the config sees one consistent credential.
    raw = manager._recover_key(agent_id)
    assert entry["headers"]["Authorization"] == f"Bearer {raw}"


@pytest.mark.parametrize("agent_id", ["picoclaw", "opencode", "openclaw"])
async def test_reset_rewrites_the_config_and_keeps_it(manager, agent_id):
    """Reset wipes config/ and issues a *new* key; the MCP entry must follow."""
    await install(manager, agent_id)
    directory = manager.directory(agent_id)
    before = read_servers(agent_id, directory)[MCP_SERVER_NAME]

    # A server the operator added from the agent's own UI, before the reset.
    path = REAL[agent_id].config_path(directory)
    data = json.loads(path.read_text())
    node = data
    for key in PROBE[agent_id][0]:
        node = node.setdefault(key, {})
    node["operator-server"] = {"url": "http://127.0.0.1:9999/mcp", "type": "remote",
                               "transport": "streamable-http", "enabled": True}
    path.write_text(json.dumps(data))

    await manager.reset(agent_id)

    servers = read_servers(agent_id, directory)
    assert MCP_SERVER_NAME in servers
    after = servers[MCP_SERVER_NAME]
    assert after["url"] == before["url"]
    # A new key was issued, so the header must carry the new one -- an entry
    # still presenting the revoked key is an agent whose tool calls all 401.
    raw = manager._recover_key(agent_id)
    assert after["headers"]["Authorization"] == f"Bearer {raw}"


@pytest.mark.parametrize("agent_id", ["picoclaw", "opencode", "openclaw"])
async def test_sync_keeps_a_server_the_operator_added(manager, agent_id):
    await install(manager, agent_id)
    directory = manager.directory(agent_id)
    path = REAL[agent_id].config_path(directory)
    data = json.loads(path.read_text())
    node = data
    for key in PROBE[agent_id][0]:
        node = node.setdefault(key, {})
    node["operator-server"] = {"url": "http://127.0.0.1:9999/mcp", "type": "remote",
                               "transport": "streamable-http", "enabled": True}
    path.write_text(json.dumps(data))

    await manager.sync(agent_id)

    servers = read_servers(agent_id, directory)
    assert "operator-server" in servers, servers
    assert servers["operator-server"]["url"] == "http://127.0.0.1:9999/mcp"
    assert MCP_SERVER_NAME in servers


@pytest.mark.parametrize("agent_id", ["picoclaw", "opencode", "openclaw"])
async def test_a_second_sync_does_not_duplicate_or_drift(manager, agent_id):
    await install(manager, agent_id)
    directory = manager.directory(agent_id)
    first = read_servers(agent_id, directory)
    await manager.sync(agent_id)
    await manager.sync(agent_id)
    assert read_servers(agent_id, directory) == first


@pytest.mark.parametrize("agent_id", ["picoclaw", "opencode", "openclaw"])
async def test_the_block_lands_where_each_agent_schema_expects_it(manager, agent_id):
    """The three configs are not the same shape, and each has a field that is
    mandatory for Streamable HTTP specifically."""
    await install(manager, agent_id)
    directory = manager.directory(agent_id)
    data = json.loads(REAL[agent_id].config_path(directory).read_text())
    if agent_id == "picoclaw":
        mcp = data["tools"]["mcp"]
        # `enabled` defaults to FALSE in PicoClaw's DefaultConfig, so the block
        # is dead without it.
        assert mcp["enabled"] is True
        # An omitted `type` would be inferred as SSE from the URL.
        assert mcp["servers"][MCP_SERVER_NAME]["type"] == "streamable-http"
    elif agent_id == "opencode":
        entry = data["mcp"][MCP_SERVER_NAME]
        assert entry["type"] == "remote"
        assert "command" not in entry
    else:
        entry = data["mcp"]["servers"][MCP_SERVER_NAME]
        # An `url` alone makes OpenClaw assume SSE.
        assert entry["transport"] == "streamable-http"
        assert "command" not in entry


# ---------------------------------------------------------------------------
# the key survives a sync even when the provider block carries none
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("agent_id", ["picoclaw", "opencode", "openclaw"])
async def test_the_key_is_recoverable_from_the_mcp_header_alone(manager, agent_id):
    """An agent installed with no model loaded has no key in its provider block.

    PicoClaw's ``model_list`` and the others' ``models`` are empty in that case,
    so ``existing_key`` would answer "" and ``_recover_key`` would revoke the
    live key and issue a new one on *every* sync -- rotating a working credential
    once per console page refresh. The MCP header is the second copy, and is
    what makes recovery work there. This is the property, asserted directly on
    the spec so it cannot regress by a manager change.
    """
    directory = Path("/tmp/mcp-key-recovery") / agent_id
    if directory.exists():
        import shutil

        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    ctx = InstallContext(service_port=18080, api_key="sk-the-only-copy",
                         models=[], default_model="", secret="s" * 12, port=14097)
    REAL[agent_id].write_config(directory, ctx)
    assert REAL[agent_id].existing_key(directory) == "sk-the-only-copy"


@pytest.mark.parametrize("agent_id", ["picoclaw", "opencode", "openclaw"])
async def test_a_sync_does_not_rotate_the_key_when_no_model_is_loaded(manager, agent_id):
    """The regression the second key location prevents, driven end to end.

    With no model loaded the provider block this service writes is empty, so
    ``existing_key`` used to answer "" and ``_recover_key`` revoked the live key
    and issued a new one -- on *every* sync, i.e. on every start and every console
    "同步配置". The MCP header is the copy that makes recovery work here.
    """
    await install(manager, agent_id)
    directory = manager.directory(agent_id)
    assert json.loads(REAL[agent_id].config_path(directory).read_text())  # sanity
    first_key_id = manager.state(agent_id).key_id
    first_header = read_servers(agent_id, directory)[MCP_SERVER_NAME]["headers"]

    await manager.sync(agent_id)
    await manager.sync(agent_id)

    assert manager.state(agent_id).key_id == first_key_id, "the key was rotated"
    assert read_servers(agent_id, directory)[MCP_SERVER_NAME]["headers"] == first_header
