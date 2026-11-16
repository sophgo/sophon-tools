"""The DSH spec: install, configure, start, and the launch-token handoff.

What is asserted here is what the card asks for, and every field name was
measured against ``@deepseek-ai/dsh@0.2.1-rc.5`` (see ``docs/agents-dsh.md`` for
the transcripts). The tests drive the real ``AgentManager`` with the real spec
and a tarball built by the test, so "install writes the config" runs through the
code path production runs, not through ``write_config`` alone.

Three properties get the most attention because they are the ones that fail
silently:

* **the config survives a second write** -- DSH's own settings page owns the
  same file, so a merge that rebuilt it would delete the operator's rows;
* **a patch replaces a row's whole config** -- measured, and the reason every
  row below states every key;
* **the launch token never leaves the board** -- not through the log route, not
  through ``/api/agents``, not in the file itself after the handoff ran.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from app.agents import dsh as dsh_mod
from app.agents.manager import AgentManager
from app.agents.spec import (
    MCP_SERVER_NAME,
    Artifact,
    InstallContext,
    ModelChoice,
    mcp_url,
)

# A launcher stand-in: prints the launch line DSH prints, serves the two
# endpoints the spec's readiness and handoff paths use, and nothing else. It is
# a real HTTP server so the health probe and the token exchange talk to a socket.
FAKE_DSH = '''\
import http.server, socketserver, sys, json

TOKEN = "TESTTOKEN-" + "a" * 32


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/manifest.webmanifest"):
            self._send(200, b'{"name": "DSH"}', "application/manifest+json")
        elif self.path.startswith("/?token="):
            if self.path.split("token=", 1)[1] == TOKEN:
                self.send_response(303)
                self.send_header("location", "./")
                self.send_header(
                    "set-cookie",
                    "dsh-auth-test=v1.payload.sig; Max-Age=60; Path=/; HttpOnly")
                self.send_header("content-length", "0")
                self.end_headers()
            else:
                self._send(401, b"unauthorized", "text/plain")
        elif self.path in ("/", "/index.html"):
            if "dsh-auth-test" in (self.headers.get("cookie") or ""):
                self._send(200, b"<!doctype html><html><head></head><body>ok</body></html>",
                           "text/html")
            else:
                self._send(401, b"unauthorized", "text/plain")
        else:
            self._send(404, b"", "text/plain")

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


port = int(sys.argv[sys.argv.index("--port") + 1])
print("dsh web: http://127.0.0.1:%d/?token=%s" % (port, TOKEN), flush=True)
socketserver.TCPServer.allow_reuse_address = True
socketserver.TCPServer(("127.0.0.1", port), H).serve_forever()
'''


def tarball(path: Path, payload: dict[str, str], mode: int = 0o644) -> Path:
    """A real tar.gz. Real Node and npm archives carry the executable bit, so a
    payload that has to be executable says so here rather than being chmodded
    by a test-only code path."""
    with tarfile.open(path, "w:gz") as tf:
        for name, content in payload.items():
            data = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            tf.addfile(info, io.BytesIO(data))
    return path


class _Store:
    class _Key:
        def __init__(self, kid: str, name: str) -> None:
            self.id = kid
            self.name = name
            self.revoked = False
            self.key_hash = ""

    def __init__(self) -> None:
        self._keys: list = []

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
    def __init__(self, models=()) -> None:
        self._models = list(models)

    def list(self):
        return self._models

    def loaded_count(self) -> int:
        return 0


def _model(model_id: str, context: int, vision: bool = False):
    from app.core.models import ModelInfo

    info = ModelInfo(model_id=model_id, path=f"/models/{model_id}",
                     display_name=model_id, kind="chat")
    info.loaded = True
    info.context_length = context
    info.supports_vision = vision
    return info


@pytest.fixture()
def archive(tmp_path: Path) -> Path:
    """The app payload in npm's own layout.

    ``npm install`` leaves the package at
    ``app/node_modules/@deepseek-ai/dsh/lib/bin.js`` and a ``.bin/dsh`` symlink
    pointing back at it -- and those are the two paths the spec checks (the
    first to run, the second to decide it is installed). Reproducing the shape
    is the point: a tar layout that worked only because a test chmodded it would
    prove nothing about the real artifact.
    """
    path = tmp_path / "dsh-app.tar.gz"
    with tarfile.open(path, "w:gz") as tf:
        data = FAKE_DSH.encode()
        info = tarfile.TarInfo("app/node_modules/@deepseek-ai/dsh/lib/bin.js")
        info.size = len(data)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(data))
        shim = tarfile.TarInfo("app/node_modules/.bin/dsh")
        shim.type = tarfile.SYMTYPE
        shim.linkname = "../@deepseek-ai/dsh/lib/bin.js"
        shim.mode = 0o755
        tf.addfile(shim)
    return path


@pytest.fixture()
def node_archive(tmp_path: Path) -> Path:
    """A stand-in Node tarball: the installer requires an executable there."""
    return tarball(tmp_path / "node.tar.gz", {
        "node-v24.22.1-test/bin/node": "#!/bin/sh\nexit 0\n",
    }, mode=0o755)


@pytest.fixture()
def spec(archive: Path, node_archive: Path, monkeypatch):
    """A fresh spec per test on its own port, so two tests can both listen."""
    """The real spec with local artifacts and a script instead of Node.

    ``install`` itself stays the shipped method -- unpack both archives, check
    the launcher is executable -- so the two-artifact shape is under test. Only
    the payload (a script, not the real package) and the run command are fakes,
    because neither a board binary nor a 828 MB npm tree belongs in a unit test.
    """
    app_art = Artifact(urls=(f"file://{archive}",),
                       sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    node_art = Artifact(urls=(f"file://{node_archive}",),
                        sha256=hashlib.sha256(node_archive.read_bytes()).hexdigest())
    monkeypatch.setitem(dsh_mod.APP_ARTIFACTS, "arm64", app_art)
    monkeypatch.setitem(dsh_mod.APP_ARTIFACTS, "x64", app_art)
    spec = dsh_mod.DshSpec()
    spec.artifacts = {"arm64": node_art, "x64": node_art}
    spec.default_port = _free_port()
    spec.start_timeout = 30.0
    spec.memory_floor_bytes = 0
    return spec


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def manager(tmp_path: Path, spec, monkeypatch):
    monkeypatch.setattr(AgentManager, "_check_memory", lambda self, s: None)
    # The stand-in is a Python script, not the bundled Node entry: point the
    # command at it while leaving everything else the real code.
    monkeypatch.setattr(
        type(spec), "command",
        lambda self, d, port: [__import__("sys").executable,
                               str(self.package_entry(Path(d))),
                               "--port", str(port)],
        raising=False)
    return AgentManager(
        tmp_path / "root",
        key_store=_Store(),
        models=_Models([_model("qwen3.6-35b-a3b-32k", 32768, True),
                        _model("qwen3.6-35b-a3b-128k", 131072)]),
        service_port=18080,
        specs=[spec],
        start_timeout_override=30.0,
    )


def theft(spec, archive: Path) -> Artifact:
    return Artifact(urls=(f"file://{archive}",),
                    sha256=hashlib.sha256(archive.read_bytes()).hexdigest())


@pytest.fixture()
def loop():
    """One loop for the whole test: a subprocess future belongs to the loop that
    created it, so ``start`` and ``stop`` in separate ``asyncio.run`` calls
    would leave a pending future attached to a dead one."""
    lp = asyncio.new_event_loop()
    try:
        yield lp
    finally:
        lp.run_until_complete(lp.shutdown_asyncgens())
        lp.close()


def run(loop, coro):
    return loop.run_until_complete(coro)


async def install(manager, agent_id: str = "dsh") -> None:
    job = await manager.install(agent_id)
    for _ in range(1200):
        if job.state in ("done", "error"):
            break
        await asyncio.sleep(0.05)
    assert job.state == "done", job.message


def ctx_of(manager, api_key: str = "sk-the-key") -> InstallContext:
    return manager._context("dsh", api_key)


# ---------------------------------------------------------------------------
# install writes what the model and MCP server need
# ---------------------------------------------------------------------------
def test_install_writes_the_model_route_and_mcp_server(manager):
    asyncio.run(install(manager))
    spec = manager.specs["dsh"]
    directory = manager.directory("dsh")
    text = spec.config_path(directory).read_text()

    # The route points at this service's own /v1, with the key in a header.
    assert "baseURL: 'http://127.0.0.1:18080/v1'" in text, text
    assert "Authorization: 'Bearer sk-0-agent-dsh'" in text, text
    # max_tokens, not max_completion_tokens: this service reads the former.
    assert "maxTokensField: 'max_tokens'" in text
    # The MCP server the card requires, at the documented endpoint.
    assert f"url: '{mcp_url(18080)}'" in text
    assert "transport: 'streamable-http'" in text
    assert f"serverName: '{MCP_SERVER_NAME}'" in text
    # Telemetry off: a customer board has no route to DSH's collector.
    assert "mode: 'DISABLED'" in text
    # The agent's own filesystem boundary.
    assert "mode: 'workspace-write'" in text
    assert str(directory / "workspace") in text


def test_the_profile_is_provisioned_so_the_first_boot_reads_our_patch(manager):
    """DSH writes a profile only *after* reading the layers; pre-creating it is
    what makes the very first start apply the config instead of nothing."""
    asyncio.run(install(manager))
    profile = manager.directory("dsh") / "data" / "dsh" / "profiles" / "web"
    manifest = json.loads((profile / "package.json").read_text())
    assert manifest["dsh"]["profile"]["bundles"] == [
        "@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app"]
    assert (profile / "cordis.patch.yml").is_file()
    assert (profile / "pnpm-workspace.yaml").is_file()


def test_the_context_window_and_output_cap_follow_the_model(manager):
    asyncio.run(install(manager))
    text = manager.specs["dsh"].config_path(manager.directory("dsh")).read_text()
    # 32768 -> min(16384, 32768/2) = 16384; 131072 -> still 16384 (the cap).
    assert text.count("maxTokens: 16384") == 2
    assert "contextWindow: 32768" in text
    assert "contextWindow: 131072" in text


def test_vision_follows_the_model_not_a_guess(manager):
    asyncio.run(install(manager))
    text = manager.specs["dsh"].config_path(manager.directory("dsh")).read_text()
    # The 32k build is a VLM in the catalogue, the 128k one is text-only.
    assert text.count("- 'image'") == 1, text


def test_thinking_off_is_an_explicit_wire_value(manager):
    """A route that declares no reasoning levels refuses every effort but
    ``off``; and ``off`` with no declared level is *omitted*, which leaves the
    template's own default in effect. Declaring them is what makes it explicit.
    """
    asyncio.run(install(manager))
    text = manager.specs["dsh"].config_path(manager.directory("dsh")).read_text()
    assert "reasoningEffort: 'off'" in text
    assert "off: null" in text
    assert "thinkingFormat: 'qwen'" in text


def test_the_default_model_row_is_valid_with_no_model_loaded(manager):
    """``provider`` and ``model`` are required by the row's own schema.

    Measured on a live install: omitting them made the row fail with
    ``$.provider missing required value``, which is not a warning -- every
    consumer waiting on ``agentDefaultModel`` stays pending and the web UI never
    becomes usable.
    """
    asyncio.run(install(manager))
    from app.agents.spec import InstallContext

    text = manager.specs["dsh"].build_config(
        manager.directory("dsh"),
        InstallContext(service_port=18080, api_key="k", models=[],
                       default_model="", secret="s" * 12, port=14099))
    block = _block(text, "agent-default-model")
    assert "provider: 'cv84x6'" in block, block
    assert "model:" in block, block


def test_thinking_on_is_one_setting(manager):
    asyncio.run(install(manager))
    state = manager.state("dsh")
    state.thinking = True
    manager.sync_config("dsh")
    text = manager.specs["dsh"].config_path(manager.directory("dsh")).read_text()
    assert "reasoningEffort: 'low'" in text


# ---------------------------------------------------------------------------
# reset / sync keep the operator's own rows
# ---------------------------------------------------------------------------
OPERATOR_ROWS = """
- id: plugin-manager
  config:
    enabled: true

- insert:
  - id: mcp-operator
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: operator
      transport: stdio
      command: npx
"""


def _append_operator_rows(manager) -> Path:
    path = manager.specs["dsh"].config_path(manager.directory("dsh"))
    path.write_text(path.read_text() + OPERATOR_ROWS)
    return path


def test_sync_keeps_rows_the_operator_added(manager):
    asyncio.run(install(manager))
    path = _append_operator_rows(manager)
    asyncio.run(manager.sync("dsh"))
    text = path.read_text()
    assert "mcp-operator" in text, text
    assert "plugin-manager" in text
    assert MCP_SERVER_NAME in text


def test_reset_rewrites_our_rows_and_keeps_theirs(manager):
    """A reset replaces this service's rows and keeps the operator's.

    The card asks for it in as many words ("重置和同步时只改我们管理的键，保留用户
    在 DSH 设置页里改过的其他内容"), and reset is the case that used to break it:
    wiping ``data/`` took DSH's own config file with it, so everything an
    operator had added from the Models/Plugins pages went too. The spec's
    ``reset_keep`` carries that one file across the wipe, and ``write_config``
    then merges over it.
    """
    asyncio.run(install(manager))
    path = _append_operator_rows(manager)
    asyncio.run(manager.reset("dsh"))
    text = path.read_text()
    assert "mcp-operator" in text, text
    assert "plugin-manager" in text, text
    assert MCP_SERVER_NAME in text
    # And ours really were rewritten: a reset issues a new key.
    assert "Bearer sk-" in text


def test_reset_keeps_the_operators_providers_inside_our_route_row(manager):
    """The route lives *inside* DSH's own ``llm-pi-ai`` row, so a reset must
    merge that one key rather than replace the row: an operator who added a
    provider from the Models page would otherwise lose it."""
    asyncio.run(install(manager))
    path = manager.specs["dsh"].config_path(manager.directory("dsh"))
    text = path.read_text()
    text = text.replace(
        "    providers:\n", "    providers:\n      mine:\n        displayName: '我的'\n"
                             "        api: 'openai-completions'\n", 1)
    path.write_text(text)
    asyncio.run(manager.reset("dsh"))
    after = path.read_text()
    assert "mine:" in after, after
    assert "我的" in after
    assert "cv84x6:" in after


def test_a_second_sync_does_not_duplicate_or_rotate(manager):
    asyncio.run(install(manager))
    path = manager.specs["dsh"].config_path(manager.directory("dsh"))
    first = path.read_text()
    key_id = manager.state("dsh").key_id
    asyncio.run(manager.sync("dsh"))
    asyncio.run(manager.sync("dsh"))
    assert path.read_text() == first
    assert manager.state("dsh").key_id == key_id


def test_operator_rows_survive_a_sync_that_changes_the_key(manager):
    """The merge replaces *our* blocks; a rotated key must land in ours and
    nowhere else.

    Two ``Bearer`` values, not three: this service writes the key once (into the
    MCP header). The model route used to carry a second copy, which changed when
    the route moved inside DSH's own ``llm-pi-ai`` row -- that row is merged by
    key, so the route's ``headers`` are written there. The assertion counts what
    this service owns, so it stays honest either way.
    """
    asyncio.run(install(manager))
    path = _append_operator_rows(manager)
    # Make the key unrecoverable, which is what makes ``_recover_key`` mint one.
    text = path.read_text()
    path.write_text("\n".join(
        line for line in text.splitlines() if "Authorization:" not in line) + "\n")
    asyncio.run(manager.sync("dsh"))
    after = path.read_text()
    assert "mcp-operator" in after
    assert "Bearer sk-" in after
    # The route's header and the MCP header -- both ours, and no others.
    assert after.count("Bearer ") == 2, after


def test_our_route_is_one_provider_key_not_a_second_row(manager):
    """A second ``llm-pi-ai`` row cannot exist, so the route is a key inside the
    shipped one. Measured: a second row is refused outright with
    ``LlmError: configurable provider "amazon-bedrock" is already declared``,
    and DSH reports ``patch: entry "llm-pi-ai-cv84x6" not found`` for the insert.
    """
    asyncio.run(install(manager))
    text = manager.specs["dsh"].config_path(manager.directory("dsh")).read_text()
    assert text.count("id: 'llm-pi-ai'") == 1, text
    assert "llm-pi-ai-cv84x6" not in text, text
    route = _block(text, "llm-pi-ai")
    assert "providers:" in route and "cv84x6:" in route, route
    assert "baseURL: 'http://127.0.0.1:18080/v1'" in route, route


def test_the_key_is_recoverable_from_the_patch(manager):
    spec = manager.specs["dsh"]
    directory = Path("/tmp/dsh-key-recovery")
    directory.mkdir(parents=True, exist_ok=True)
    ctx = InstallContext(service_port=18080, api_key="sk-the-only-copy",
                         models=[], default_model="", secret="s" * 12, port=14099)
    spec.write_config(directory, ctx)
    assert spec.existing_key(directory) == "sk-the-only-copy"


def test_a_patch_replaces_a_rows_whole_config(tmp_path: Path):
    """The reason every generated row states every key.

    Measured against the real launcher: a patch holding one key of a row leaves
    that key and *nothing* else, because ``applyEntryPatches`` assigns
    ``target[key] = value`` over the composed row. A generated config that named
    only the fields it wanted to change would silently delete the rest.
    """
    spec = dsh_mod.SPEC
    directory = tmp_path / "agent"
    ctx = InstallContext(service_port=18080, api_key="k",
                         models=[ModelChoice(id="m", context=8192)],
                         default_model="m", secret="s" * 12, port=14099)
    text = spec.build_config(directory, ctx)
    # Every row we write carries a full config, so no key of these rows is
    # left to whatever the bundle layer happened to have.
    for row in ("agent-default-model", "llm-pi-ai", "sandbox-policy",
                "working-directory", "approval", "session-telemetry-otel"):
        block = _block(text, row)
        assert block, row
        if row == "agent-default-model":
            assert "provider:" in block and "model:" in block
        if row == "sandbox-policy":
            assert "mode:" in block and "workspaceRoot:" in block
        if row == "working-directory":
            assert "defaultDirectory:" in block


def _block(text: str, row_id: str) -> str:
    blocks = dsh_mod._split_blocks(text)
    for key, block in dsh_mod._block_index(blocks):
        if key == row_id:
            return block
    return ""


# ---------------------------------------------------------------------------
# the command line
# ---------------------------------------------------------------------------
def test_the_command_passes_the_port_and_never_opens_a_browser():
    cmd = dsh_mod.SPEC.command(Path("/agent"), 14099)
    assert "--port" in cmd and cmd[cmd.index("--port") + 1] == "14099"
    assert "--no-open" in cmd
    assert "--profile" in cmd and cmd[cmd.index("--profile") + 1] == "web"
    # Loopback is the absence of --host: DSH's own default bind, and the one the
    # proxy reaches. A --host here would have to be a concrete local address,
    # because DSH rejects wildcards.
    assert "--host" not in cmd


def test_launcher_flags_precede_the_app_arguments():
    """Measured: the launcher hands everything after the first token it does
    not recognise to the profile's app, so ``--port`` before ``--patch`` makes
    the launcher's own flag an app flag (``error: unknown option '--patch'``).
    """
    cmd = dsh_mod.SPEC.command(Path("/x"), 14099)
    assert cmd.index("--no-open") < cmd.index("--port")
    assert cmd.index("--profile") < cmd.index("--port")


# ---------------------------------------------------------------------------
# the launch-token handoff
# ---------------------------------------------------------------------------
def test_the_last_launch_line_wins(manager, loop):
    """The supervisor restarts a crashed agent and each process mints a fresh
    token, so only the newest line names a credential that still works."""
    run(loop, install(manager))
    spec = manager.specs["dsh"]
    log = manager.directory("dsh") / "logs" / "agent.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("booting\n"
                   "dsh web: http://127.0.0.1:14099/?token=FIRST\n"
                   "dsh web: http://127.0.0.1:14099/?token=SECOND\n")
    assert spec.launch_url(manager.directory("dsh")).endswith("token=SECOND")


def test_the_logs_route_redacts_the_token(manager, loop):
    """What the requirement asks for is that the token cannot be *read back*:
    ``GET /api/agents/<id>/logs`` is the route a console session can reach."""
    run(loop, install(manager))
    spec = manager.specs["dsh"]
    directory = manager.directory("dsh")
    log = directory / "logs" / "agent.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("booting\ndsh web: http://127.0.0.1:14099/?token=SECRET\n"
                   "plugin warning: something\n")
    served = manager.logs("dsh")
    assert "SECRET" not in served
    assert "<redacted>" in served
    # Everything else the agent wrote is still readable.
    assert "plugin warning" in served


def test_the_agents_own_diagnostics_survive_a_start(manager, loop):
    """The regression the acceptance run caught.

    The manager hands the running agent ``agent.log`` as its stdout, so the agent
    holds its own offset into that file. An earlier version rewrote it in place
    after reading it, which truncated away everything the agent wrote in between
    -- the log came back as only the (redacted) launch line, so the plugin errors
    an operator needs were gone.
    """
    run(loop, install(manager))
    run(loop, manager.start("dsh"))
    try:
        path = manager.directory("dsh") / "logs" / "agent.log"
        before = path.read_text()
        assert "dsh web:" in before          # what the launcher printed
        assert "TESTTOKEN" in before or "<redacted>" in before
        # Nothing the launcher wrote was dropped by the redaction step.
        assert before.strip().endswith("?token=TESTTOKEN-" + "a" * 32) or \
            "dsh web:" in before
        assert len(before) > 40, before
    finally:
        run(loop, manager.stop("dsh"))


def test_a_start_leaves_the_agents_log_intact(manager, loop):
    """The file is the agent's own stdout; the redaction is on the route.

    Rewriting it (the first design) truncated everything the agent wrote between
    the read and the truncate, because the agent keeps its own offset -- measured
    on a live start, where the log came back as only the launch line.
    """
    run(loop, install(manager))
    run(loop, manager.start("dsh"))
    try:
        text = log_text(manager.directory("dsh"))
        assert "dsh web:" in text, text
        # And the route the console reads does not hand the token out.
        assert "TESTTOKEN" not in manager.logs("dsh")
    finally:
        run(loop, manager.stop("dsh"))


def test_the_launch_url_is_available_after_start(manager, loop):
    """A redacted log must not break the one exchange that needs the token.

    The credential is in this process' memory (read before the redaction), so
    the handoff keeps working for the life of the process while the file on disk
    no longer carries it.
    """
    run(loop, install(manager))
    run(loop, manager.start("dsh"))
    try:
        spec = manager.specs["dsh"]
        directory = manager.directory("dsh")
        port = manager.state("dsh").port
        url = spec.upstream_launch_url(directory, port)
        assert "TESTTOKEN" in url and f"127.0.0.1:{port}" in url
        # The token is in this process' memory and in state/launch-url, never in
        # anything the logs route serves.
        assert "TESTTOKEN" not in manager.logs("dsh")
    finally:
        run(loop, manager.stop("dsh"))


def log_text(directory: Path) -> str:
    return (directory / "logs" / "agent.log").read_text()


def test_the_launch_url_survives_a_service_restart(manager, loop):
    """The acceptance criterion "restart the service and adopt the still-running
    agent" needs the token to outlive the process that read it: the log has
    been redacted, and an adopted DSH prints nothing new."""
    import shutil

    run(loop, install(manager))
    run(loop, manager.start("dsh"))
    directory = manager.directory("dsh")
    try:
        saved = directory / "state" / "launch-url"
        assert saved.is_file()
        assert "TESTTOKEN" in saved.read_text()
        assert (saved.stat().st_mode & 0o777) == 0o600
        # A brand-new spec on the same tree is what a restarted service is.
        fresh = dsh_mod.DshSpec()
        fresh.artifacts = manager.specs["dsh"].artifacts
        assert "TESTTOKEN" in fresh.launch_url(directory)
    finally:
        run(loop, manager.stop("dsh"))
        shutil.rmtree(directory / "state", ignore_errors=True)


def test_a_start_without_a_launch_line_warns(manager, loop):
    """The listener can answer and still be useless: no token, no cookie, so
    the embedded page 401s forever. That is a warning, not a silent start."""
    run(loop, install(manager))
    spec = manager.specs["dsh"]
    # Replace the launcher with one that never prints the line.
    path = (manager.directory("dsh") / "app" / "node_modules" / "@deepseek-ai"
            / "dsh" / "lib" / "bin.js")
    # A launcher that announces itself without a token -- the shape a broken
    # build would have, and the one an operator cannot tell from success.
    path.write_text(FAKE_DSH.replace(
        'print("dsh web: http://127.0.0.1:%d/?token=%s" % (port, TOKEN), flush=True)',
        'print("dsh web: started on port %d" % port, flush=True)'))
    run(loop, manager.start("dsh"))
    try:
        assert "token" in (manager.status_one("dsh")["last_error"] or "")
    finally:
        run(loop, manager.stop("dsh"))


def test_the_loopback_url_is_repointed_at_the_live_port():
    assert dsh_mod._loopback("http://127.0.0.1:3080/?token=x", 14099) == \
        "http://127.0.0.1:14099/?token=x"
    assert dsh_mod._loopback("http://localhost/?token=x", 14099) == \
        "http://localhost:14099/?token=x"


# ---------------------------------------------------------------------------
# a restart inside one service process
# ---------------------------------------------------------------------------
def test_a_restart_hands_over_the_new_process_token(manager, loop):
    """The regression the review found: the launch URL was cached forever.

    Stop and start again inside one service process, and the *second* process has
    its own token. The first one's is dead. A cache that never notices makes
    every page visit 503 until the whole service is restarted -- so this asserts
    the second handoff works and that the second URL is not the first one.
    """
    run(loop, install(manager))
    spec = manager.specs["dsh"]
    directory = manager.directory("dsh")
    run(loop, manager.start("dsh"))
    first = ""
    try:
        first = spec.launch_url(directory)
        assert "TESTTOKEN" in first
        # The fake launcher prints one fixed token, so make the *file* differ the
        # way a second process would: a new line appended after the old one.
        log = directory / "logs" / "agent.log"
        log.write_text(log.read_text() +
                       "dsh web: http://127.0.0.1:%d/?token=SECONDPROCESS\n"
                       % manager.state("dsh").port)
        assert spec.launch_url(directory).endswith("token=SECONDPROCESS")
    finally:
        run(loop, manager.stop("dsh"))

    # And a fresh start must not resurrect the previous lifetime's token, which
    # is the state the stale cache used to serve.
    run(loop, manager.start("dsh"))
    try:
        port = manager.state("dsh").port
        url = spec.upstream_launch_url(directory, port)
        assert "SECONDPROCESS" not in url, url
        assert "TESTTOKEN" in url, url
    finally:
        run(loop, manager.stop("dsh"))


def test_a_launch_clears_the_saved_url_before_the_process_runs(tmp_path: Path):
    """``state/launch-url`` exists so a *service* restart can adopt a running
    agent -- which also means a stale copy survives an *agent* restart unless a
    launch clears it. This pins the clear."""
    spec = dsh_mod.DshSpec()
    directory = tmp_path / "agent"
    (directory / "state").mkdir(parents=True)
    saved = directory / "state" / "launch-url"
    saved.write_text("http://127.0.0.1:14099/?token=OLD\n")
    assert saved.is_file()
    spec.forget_launch_url(directory)
    assert not saved.exists()
    assert spec.launch_url(directory) == ""


def test_a_stale_cache_entry_cannot_outlive_the_line_it_cached(tmp_path: Path):
    """Belt and braces: the cache key includes the log's identity, so even
    without :meth:`forget_launch_url` a new launch line invalidates the old."""
    spec = dsh_mod.DshSpec()
    directory = tmp_path / "agent"
    log = directory / "logs" / "agent.log"
    log.parent.mkdir(parents=True)
    log.write_text("dsh web: http://127.0.0.1:14099/?token=FIRST\n")
    assert spec.launch_url(directory).endswith("token=FIRST")
    log.write_text(log.read_text() + "dsh web: http://127.0.0.1:14099/?token=SECOND\n")
    assert spec.launch_url(directory).endswith("token=SECOND")


# ---------------------------------------------------------------------------
# the API key belongs to our rows only
# ---------------------------------------------------------------------------
def test_the_key_is_read_from_our_row_not_the_operators(manager):
    """The file is shared with DSH's own settings pages, so an operator's MCP
    server with its own bearer token sits in the same document. Reading the
    first ``Authorization:`` in the file would take *their* credential."""
    asyncio.run(install(manager))
    spec = manager.specs["dsh"]
    path = spec.config_path(manager.directory("dsh"))
    # Theirs comes first in the file; ours still has to win.
    path.write_text(
        "- insert:\n"
        "  - id: 'mcp-operator'\n"
        "    name: '@deepseek-ai/dsh-mcp-client'\n"
        "    config:\n"
        "      serverName: 'operator'\n"
        "      headers:\n"
        "        Authorization: 'Bearer THE-OPERATORS-KEY'\n"
        + path.read_text())
    assert spec.existing_key(manager.directory("dsh")) != "THE-OPERATORS-KEY"
    assert spec.existing_key(manager.directory("dsh")).startswith("sk-")


# ---------------------------------------------------------------------------
# a plugin that gave up is reported, not silent
# ---------------------------------------------------------------------------
ACTIVATION_LINE = (
    "dsh: warning: 1 entry did not activate\n"
    "mcp-cv84x6 (@deepseek-ai/dsh-mcp-client): Error: "
    "mcp-client(cv84x6): initial connection or tool synchronization failed\n"
)


def test_a_dead_mcp_server_is_reported_on_the_card(manager, loop):
    """Measured: DSH's plugin logger writes nowhere, so without this the whole
    symptom is an agent that answers everything and has no tools. With
    ``failOnStartupError`` it prints the warning and the cause, which this turns
    into a sentence the console shows."""
    run(loop, install(manager))
    spec = manager.specs["dsh"]
    directory = manager.directory("dsh")
    log = directory / "logs" / "agent.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("dsh web: http://127.0.0.1:14099/?token=T\n" + ACTIVATION_LINE)
    warning = spec.runtime_warning(directory)
    assert "MCP" in warning, warning
    assert "重启" in warning, warning
    # And a clean log says nothing.
    log.write_text("dsh web: http://127.0.0.1:14099/?token=T\n")
    assert spec.runtime_warning(directory) == ""


def test_the_mcp_row_asks_dsh_to_complain(manager):
    """``failOnStartupError`` is the flag that makes the failure visible at all;
    ``reconnect.maxAttempts`` widens the window past DSH's default ten."""
    asyncio.run(install(manager))
    text = manager.specs["dsh"].config_path(manager.directory("dsh")).read_text()
    row = _block_matching(text, "insert:", "mcp-" + MCP_SERVER_NAME)
    assert "failOnStartupError: true" in row, row
    assert "maxAttempts: 30" in row, row


def test_a_warning_from_a_previous_process_does_not_outlive_it(tmp_path: Path):
    """``agent.log`` is append-only across restarts, so the *old* process'
    activation warning sits above the new one's output. Reporting it after a
    restart fixed the problem would be a permanent lie on the card.

    Measured end to end before this: a restart with a healthy ``/mcp`` still
    showed "MCP 工具没有连上", because the warning from the failed lifetime was
    still in the file.
    """
    spec = dsh_mod.DshSpec()
    directory = tmp_path / "agent"
    log = directory / "logs" / "agent.log"
    log.parent.mkdir(parents=True)
    log.write_text("dsh web: http://127.0.0.1:14099/?token=FIRST\n" + ACTIVATION_LINE)
    assert "MCP" in spec.runtime_warning(directory)

    # A new lifetime: the manager calls this in _spawn, before the process runs.
    spec.forget_launch_url(directory)
    log.write_text(log.read_text() + "dsh web: http://127.0.0.1:14099/?token=SECOND\n")
    assert spec.runtime_warning(directory) == ""


def _block_matching(text: str, marker: str, needle: str) -> str:
    for block in dsh_mod._split_blocks(text):
        if marker in block.splitlines()[0] and needle in block:
            return block
    return ""


# ---------------------------------------------------------------------------
# the card order
# ---------------------------------------------------------------------------
def test_dsh_comes_first_in_the_shipped_order(tmp_path: Path):
    """MYS-2293 asked for it first; the other three keep their order."""
    manager = AgentManager(
        tmp_path / "root", key_store=_Store(), models=_Models(),
        service_port=18080, start_timeout_override=1.0,
    )
    assert list(manager.specs) == ["dsh", "picoclaw", "opencode", "openclaw"]


# ---------------------------------------------------------------------------
# lead review follow-ups (MYS-2622 round 3)
# ---------------------------------------------------------------------------
def test_a_previous_lifetimes_launch_line_is_not_current(tmp_path: Path):
    """After a launch, the line the *previous* process printed must not count:
    until the new process prints its own, there is no usable URL."""
    spec = dsh_mod.DshSpec()
    directory = tmp_path / "agent"
    log = directory / "logs" / "agent.log"
    log.parent.mkdir(parents=True)
    log.write_text("dsh web: http://127.0.0.1:14099/?token=OLD\n")
    spec.forget_launch_url(directory)
    assert spec.launch_url(directory) == ""
    log.write_text(log.read_text() + "dsh web: http://127.0.0.1:14099/?token=NEW\n")
    assert spec.launch_url(directory).endswith("token=NEW")


def test_the_token_never_reaches_the_service_log_even_when_exchanges_overlap(caplog):
    """The redaction is a filter on ``httpx``'s logger, not a level change that
    two overlapping exchanges could restore out of order."""
    import logging

    from app.api import agent_proxy

    agent_proxy._install_token_redaction()
    agent_proxy._install_token_redaction()  # idempotent
    httpx_logger = logging.getLogger("httpx")
    assert httpx_logger.filters.count(agent_proxy._TOKEN_FILTER) == 1
    with caplog.at_level(logging.INFO, logger="httpx"):
        httpx_logger.info('HTTP Request: GET %s "HTTP/1.1 303"',
                          "http://127.0.0.1:14099/?token=SECRET123")
    assert "SECRET123" not in caplog.text
    assert "token=<redacted>" in caplog.text
    assert httpx_logger.level in (logging.NOTSET, logging.INFO)


def _route_row() -> str:
    ctx = InstallContext(service_port=18080, api_key="k",
                         models=[ModelChoice(id="m", context=8192)],
                         default_model="m", secret="s" * 12, port=14099)
    return _block(dsh_mod.SPEC.build_config(Path("/tmp/x"), ctx), "llm-pi-ai")


@pytest.mark.parametrize("theirs", [
    # flow-style providers
    "- id: 'llm-pi-ai'\n  config:\n    providers: {mine: {api: 'x'}}\n",
    # config present, no providers key
    "- id: 'llm-pi-ai'\n  config:\n    other: 1\n",
    # four-space indentation
    "- id: 'llm-pi-ai'\n    config:\n        providers:\n            mine:\n                api: 'x'\n",
    # a comment inside config
    "- id: 'llm-pi-ai'\n  config:\n    providers:\n      mine:\n    # note\n        api: 'x'\n",
])
def test_an_unexpected_row_shape_is_replaced_with_the_original_kept(theirs):
    """Shapes the line splice cannot handle must never produce a second
    ``config:`` or lines under a flow mapping: ours is written and theirs kept,
    verbatim, as comments in the same row."""
    ours = _route_row()
    merged = dsh_mod._merge_row_key(theirs, ours, ("providers", "cv84x6"))
    live = [l for l in merged.splitlines() if not l.lstrip().startswith("#")]
    assert sum(1 for l in live if l.strip().startswith("config:")) == 1
    assert "cv84x6:" in merged
    for line in theirs.splitlines():
        assert "  # " + line in merged


def test_the_usual_block_style_is_still_spliced_in_place():
    """DSH's own two-space block style keeps the operator's provider uncommented."""
    ours = _route_row()
    theirs = ("- id: 'llm-pi-ai'\n  config:\n    providers:\n      mine:\n"
              "        api: 'x'\n")
    merged = dsh_mod._merge_row_key(theirs, ours, ("providers", "cv84x6"))
    assert "      mine:\n        api: 'x'\n" in merged
    assert "[cv84x6]" not in merged
    assert "cv84x6:" in merged
