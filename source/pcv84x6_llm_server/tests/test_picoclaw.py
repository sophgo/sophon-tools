"""PicoClaw: its generated config, its two-process lifecycle, and its proxy paths.

Three groups of assertions, each about something a unit test can fake into
passing and therefore must not:

* **The config.** Field names come from PicoClaw 0.3.1's own structs, so the
  regression guard is the *real binary*: where the release package is available
  it is asked to load the generated file (``picoclaw agent -m``), and the file
  it read is compared field by field. A schema this test invented would prove
  nothing.
* **The lifecycle.** A launcher that forks a gateway is a real two-process
  shape, so the fake launcher here is a real process that forks a real child --
  and the tests drive it through the manager's own ``start``/``stop``/
  ``restart``/``uninstall`` rather than through the spec's helpers.
* **The proxy.** The dashboard's chat socket is built as
  ``ws://host/pico/ws`` from the page, and its assets as ``/assets/...``. The
  shim that moves those under the prefix is exercised through node, because the
  bug it fixes (a ``ws:`` origin never comparing equal to an ``http:`` one) is
  invisible to a Python assertion.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import socket
import subprocess
import sys
import tarfile
import textwrap
import time
from pathlib import Path

import pytest

from app.agents.picoclaw import (
    BASE_PATH,
    DEFAULT_PORT,
    MAX_OUTPUT_TOKENS,
    PROVIDER,
    PicoclawSpec,
)
from app.agents.manager import AgentManager, PortBusy
from app.agents.spec import AgentSpec, InstallContext, ModelChoice, host_arch
from app.api.agent_proxy import _PrefixRewriter, _shim_js

# The four models this project ships, in the order the catalogue lists them. The
# agent config is checked against all four rather than one: the context length is
# what decides both ``context_window`` and the output cap, so a single 32k case
# would pass while a 128k model got a 128000-token window it cannot take.
FOUR_MODELS = [
    ModelChoice(id="qwen3.6-35b-a3b-128k", context=131072, vision=True),
    ModelChoice(id="qwen3.5-35b-a3b-128k", context=131072, vision=True),
    ModelChoice(id="qwen3.6-35b-a3b-32k", context=32768, vision=True),
    ModelChoice(id="qwen3.5-35b-a3b-32k", context=32768, vision=True),
]

# Where the official release package is unpacked. The tests that need a real
# binary skip when this is absent; every other test runs everywhere. Set
# ``PICOCLAW_RELEASE_DIR`` to run them against the arm64 build on the board --
# that is the architecture the release is for, so it is the better place for
# these two tests, not a worse one.
LOCAL_RELEASE = Path(os.environ.get("PICOCLAW_RELEASE_DIR")
                     or "/home/zzt/workspace/picoclaw-local")


def _ctx(**over) -> InstallContext:
    base = dict(
        service_port=18080,
        api_key="sk-agent-key",
        models=list(FOUR_MODELS),
        default_model="qwen3.6-35b-a3b-32k",
        thinking=False,
        secret="dashboard-secret-1234",
        port=DEFAULT_PORT,
    )
    base.update(over)
    return InstallContext(**base)


def free_port() -> int:
    """A launcher port whose gateway port is free too, and that nobody else's
    allocation can take between the check and the bind.

    PicoClaw listens on ``port`` and forks a gateway onto ``port + 1``, and the
    fake launcher here does the same -- so *both* numbers have to be usable, and
    both have to stay usable until the launcher binds them. Two independent
    races break that, and the helper has to close both:

    **The kernel's outbound pool.** ``bind(("127.0.0.1", 0))`` returns a port
    from ``ip_local_port_range`` (32768-60999 here), the same pool the kernel
    hands out as the *source* port of every outbound connection. When one of
    this process' own requests -- a health probe, ``/api/auth/setup``, the mock
    ``/v1`` server -- is given ``port + 1``, that number is ESTABLISHED and the
    gateway's bind fails with EADDRINUSE. The fake launcher then exits 0, which
    reaches the test as the misleading ``进程退出（exit=0），运行 0 秒``. So the
    pair is drawn from *below* the range, where only a listener can hold a port.

    **Another pytest process.** Two runs of this file at once draw from
    overlapping candidates; "free" is true for both until one of them binds, and
    the loser fails to bind its *launcher* port (exit=1 from the launcher
    itself, a different symptom of the same root cause). Each process therefore
    gets its own slice of the pool, keyed on its pid, so two allocations cannot
    be looking at the same numbers at the same time. A single run draws from the
    whole pool.

    This is the test's own allocation problem, not the manager's: production
    ports come from ``agents.json`` (14097/14098 for PicoClaw), far outside the
    range. See ``test_the_gateway_port_allocation_avoids_the_ephemeral_range``.
    """
    candidates = _candidate_pairs()
    random.shuffle(candidates)
    for port in candidates:
        if _port_is_free(port) and _port_is_free(port + 1):
            return port
    raise AssertionError("no free launcher/gateway port pair in the test's slice")


def _candidate_pairs() -> list[int]:
    """Launcher ports below the ephemeral range, sliced by this process' pid.

    Even numbers only: the gateway takes ``port + 1``, so an even launcher port
    means a pair never overlaps its neighbour's.
    """
    low = _ephemeral_low()
    floor = max(1024, low - 400)
    even = list(range(floor + (floor % 2), low - 2, 2))
    # 16 slices of roughly 12 ports each for the pool below 32768. The slice is
    # derived from the pid so concurrent pytest processes almost never share
    # one; an exhausted slice falls back to the whole pool rather than failing,
    # because correctness under contention is the launcher's bind, not this.
    slices = 16
    index = os.getpid() % slices
    size = max(1, len(even) // slices)
    mine = even[index * size:(index + 1) * size] or even
    return mine


def _ephemeral_low() -> int:
    """``ip_local_port_range``'s lower bound; the documented default otherwise."""
    try:
        low, _high = Path("/proc/sys/net/ipv4/ip_local_port_range").read_text().split()
        return int(low)
    except (OSError, ValueError):
        return 32768


def _port_is_free(port: int) -> bool:
    """Whether a listener could bind ``port`` -- the question the gateway asks.

    A bind, not a connect: a port held by an outbound connection refuses a bind
    while accepting nothing, so a connect probe calls it free.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


@pytest.fixture()
def model_service():
    """A stand-in for this service: ``/v1``, and the ``/mcp`` endpoint beside it.

    PicoClaw's launcher probes ``/v1/models`` before forking its gateway, so a
    mock that answers ``[]`` makes the launcher stay up alone and every gateway
    assertion in this file fail for a reason that has nothing to do with the code
    under test. ``requests`` records what the agent actually sent, which is the
    only way to check the model id and the output field after PicoClaw's own
    provider layer has rewritten them.

    **It answers ``/mcp`` as well, because the real service does.** The configs
    this spec writes now name an MCP server at ``http://127.0.0.1:<port>/mcp``,
    and PicoClaw connects to it before the first turn -- a mock that answered
    that POST with a chat completion made the agent fail with
    ``invalid message version tag ""; expected "2.0"``, which looks like a config
    bug and is really this fixture describing a service that does not exist. The
    JSON-RPC stub below is the minimum for PicoClaw's client to connect; it is
    not a second implementation of ``app/mcp`` (``tests/test_mcp_*.py`` drive the
    real one).
    """
    import http.server
    import threading

    seen: list[dict] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send({"object": "list",
                        "data": [{"id": c.id, "object": "model"} for c in FOUR_MODELS]})

        def _mcp(self, raw: bytes) -> None:
            message = json.loads(raw or b"{}")
            seen.append({"path": self.path, "body": message})
            method = message.get("method")
            if message.get("id") is None:
                # A notification: 202, no body (what the real endpoint answers).
                self.send_response(202)
                self.send_header("content-length", "0")
                self.end_headers()
                return
            if method == "initialize":
                result = {"protocolVersion": "2025-06-18",
                          "capabilities": {"tools": {}},
                          "serverInfo": {"name": "mock-cv84x6", "version": "0"}}
            elif method == "tools/list":
                result = {"tools": []}
            else:
                result = {}
            self._send({"jsonrpc": "2.0", "id": message["id"], "result": result})

        def do_POST(self):
            n = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(n)
            if self.path.rstrip("/") == "/mcp":
                self._mcp(raw)
                return
            seen.append({"path": self.path,
                         "body": json.loads(raw or b"{}")})
            self._send({
                "id": "x", "object": "chat.completion", "created": 0, "model": "m",
                "choices": [{"index": 0, "message": {"role": "assistant",
                                                    "content": "pong"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                          "total_tokens": 2},
            })

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    class Service:
        port = server.server_address[1]
        requests = seen

    try:
        yield Service()
    finally:
        server.shutdown()


# -- the config contract, model by model ----------------------------------

@pytest.mark.parametrize("choice", FOUR_MODELS, ids=lambda c: c.id)
def test_every_model_entry_matches_the_contract(choice):
    """One entry per model, every field the service reads set exactly.

    ``model`` is ``openai/<id>`` and ``model_name`` is the bare id: PicoClaw
    looks an entry up by ``model_name`` and strips the provider prefix before
    the request goes out, so putting ``openai/`` in ``model_name`` would make the
    agent ask for a model this service does not have.
    """
    spec = PicoclawSpec()
    cfg = spec.build_config(Path("/tmp/agent"), _ctx(default_model=choice.id))
    entries = {m["model_name"]: m for m in cfg["model_list"]}
    assert set(entries) == {c.id for c in FOUR_MODELS}
    entry = entries[choice.id]
    assert entry["model_name"] == choice.id
    assert entry["model"] == f"{PROVIDER}/{choice.id}"
    assert entry["api_base"] == "http://127.0.0.1:18080/v1"
    assert entry["api_keys"] == ["sk-agent-key"]
    assert entry["max_tokens_field"] == "max_tokens"
    assert entry["thinking_level"] == "off"
    assert "extra_body" not in entry


@pytest.mark.parametrize("choice", FOUR_MODELS, ids=lambda c: c.id)
def test_context_window_is_the_models_own_length(choice):
    """32768 or 131072 -- never a rounded default such as 128000."""
    spec = PicoclawSpec()
    cfg = spec.build_config(Path("/tmp/agent"), _ctx(default_model=choice.id))
    assert cfg["agents"]["defaults"]["context_window"] == choice.context
    assert cfg["agents"]["defaults"]["max_tokens"] == min(MAX_OUTPUT_TOKENS,
                                                         choice.context // 2)


def test_the_default_model_is_a_model_name_not_a_provider_path():
    spec = PicoclawSpec()
    cfg = spec.build_config(Path("/tmp/agent"),
                            _ctx(default_model="qwen3.5-35b-a3b-128k"))
    assert cfg["agents"]["defaults"]["model_name"] == "qwen3.5-35b-a3b-128k"


def test_thinking_off_writes_nothing_the_service_would_read_as_on():
    spec = PicoclawSpec()
    cfg = spec.build_config(Path("/tmp/agent"), _ctx(thinking=False))
    for entry in cfg["model_list"]:
        assert entry["thinking_level"] == "off"
        assert "extra_body" not in entry


def test_thinking_on_uses_the_one_field_picoclaw_actually_sends():
    """``thinking_level`` has no "on" half for this provider.

    Measured: PicoClaw maps ``off`` to ``enable_thinking=false`` for a Qwen model
    id, and sends nothing for any other level -- so "on" has to be an explicit
    ``extra_body`` field, which its client merges into the request last. This
    service reads ``enable_thinking`` (and the vLLM-style
    ``chat_template_kwargs``), so the field is real rather than aspirational.
    """
    spec = PicoclawSpec()
    cfg = spec.build_config(Path("/tmp/agent"), _ctx(thinking=True))
    for entry in cfg["model_list"]:
        assert entry["thinking_level"] == "low"
        assert entry["extra_body"] == {"enable_thinking": True}


def test_the_gateway_gets_its_own_loopback_port_beside_openclaw():
    """18790 is OpenClaw's gateway in this project, and 18800 the launcher default.

    Neither may be reused, and the gateway may not be reachable from the LAN: the
    console talks to it through the launcher, which this service proxies.
    """
    spec = PicoclawSpec()
    cfg = spec.build_config(Path("/tmp/agent"), _ctx(port=DEFAULT_PORT))
    assert cfg["gateway"]["port"] == DEFAULT_PORT + 1
    assert cfg["gateway"]["port"] != 18790
    assert cfg["gateway"]["host"] == "127.0.0.1"
    assert spec.children_ports(Path("/tmp/agent"), DEFAULT_PORT) == (DEFAULT_PORT + 1,)


def test_the_workspace_is_the_agents_own_directory(tmp_path):
    spec = PicoclawSpec()
    cfg = spec.build_config(tmp_path, _ctx())
    assert cfg["agents"]["defaults"]["workspace"] == str(tmp_path / "workspace")
    assert cfg["agents"]["defaults"]["restrict_to_workspace"] is True


def test_write_config_is_0600_and_creates_the_workspace(tmp_path):
    """The file holds the API key in plaintext, so it is not readable by others."""
    spec = PicoclawSpec()
    spec.write_config(tmp_path, _ctx())
    path = spec.config_path(tmp_path)
    assert path == tmp_path / "config" / "picoclaw.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "workspace").is_dir()
    assert json.loads(path.read_text())["version"] == 3


def test_existing_key_reads_back_what_the_config_holds(tmp_path):
    spec = PicoclawSpec()
    spec.write_config(tmp_path, _ctx(api_key="sk-recover-me"))
    assert spec.existing_key(tmp_path) == "sk-recover-me"


def test_existing_key_survives_the_launchers_security_split(tmp_path):
    """PicoClaw moves ``api_keys`` out of its config on first load.

    Measured on the board: after one start, ``picoclaw.json`` has no ``api_keys``
    at all and the key lives in a sibling ``.security.yml`` keyed
    ``model_list.<name>:<index>``. A recovery that only read the config would
    report "no key", and the manager's next sync would revoke the operator's key
    and issue a new one -- on every start. That is the failure this pins.
    """
    spec = PicoclawSpec()
    spec.write_config(tmp_path, _ctx(api_key="sk-moved-away"))
    config = spec.config_path(tmp_path)
    # Exactly what the launcher does: strip the key from the config, write it to
    # the security file with its own index format.
    data = json.loads(config.read_text())
    for entry in data["model_list"]:
        entry.pop("api_keys", None)
    config.write_text(json.dumps(data, indent=2))
    (tmp_path / "config" / ".security.yml").write_text(
        "channels:\n"
        "  pico:\n"
        "    settings:\n"
        "      token: abc123\n"
        "model_list:\n"
        "  qwen3.6-35b-a3b-32k:0:\n"
        "    api_keys:\n"
        "      - sk-moved-away\n"
        "web:\n"
        "  brave: {}\n"
    )
    assert spec.existing_key(tmp_path) == "sk-moved-away"


def test_rewriting_the_config_clears_the_stale_security_copy(tmp_path):
    """A stale ``.security.yml`` would silently outrank the config we just wrote.

    Measured on the board: PicoClaw merges the secure fields in *after* parsing
    the config, so a leftover key there wins. A rotated key would then be
    invisible -- the agent's requests 401 while the config reads correctly -- so
    the rewrite has to clear that section rather than trust the config alone.
    Everything else in the vendor's file (channel tokens) stays as it was.
    """
    spec = PicoclawSpec()
    spec.write_config(tmp_path, _ctx(api_key="sk-current"))
    path = tmp_path / "config" / ".security.yml"
    path.write_text(
        "channels:\n"
        "  pico:\n"
        "    settings:\n"
        "      token: keep-me\n"
        "model_list:\n"
        "  qwen3.6-35b-a3b-32k:0:\n"
        "    api_keys:\n"
        "      - sk-stale-revoked\n"
        "web:\n"
        "  brave: {}\n"
    )
    # Before the rewrite, the stale copy is what PicoClaw would use.
    assert spec.existing_key(tmp_path) == "sk-current"  # config read first
    spec.write_config(tmp_path, _ctx(api_key="sk-rotated"))
    text = path.read_text()
    assert "model_list" not in text
    assert "sk-stale-revoked" not in text
    # The vendor's own channel token is left alone.
    assert "keep-me" in text
    assert spec.existing_key(tmp_path) == "sk-rotated"


def test_a_missing_security_file_is_not_an_error(tmp_path):
    """The ordinary install case: the launcher has not written one yet."""
    spec = PicoclawSpec()
    spec.write_config(tmp_path, _ctx(api_key="sk-first"))
    assert not (tmp_path / "config" / ".security.yml").exists()
    assert spec.existing_key(tmp_path) == "sk-first"


def test_existing_key_is_empty_when_no_copy_of_it_survives(tmp_path):
    """A corrupt security file must read as "no key", never as a partial one.

    There are three places the key can live now -- ``model_list``,
    ``tools.mcp.servers.cv84x6.headers``, and the launcher's ``.security.yml`` --
    so this strips all of them. Any one of them surviving is a *recovery*, not a
    failure: see ``test_existing_key_survives_the_launchers_security_split`` and
    ``test_the_key_is_recoverable_from_the_mcp_header_alone`` in
    ``tests/test_mcp_agent_config.py``.
    """
    spec = PicoclawSpec()
    spec.write_config(tmp_path, _ctx())
    config = spec.config_path(tmp_path)
    data = json.loads(config.read_text())
    for entry in data["model_list"]:
        entry.pop("api_keys", None)
    for entry in data["tools"]["mcp"]["servers"].values():
        entry.pop("headers", None)
    config.write_text(json.dumps(data, indent=2))
    (tmp_path / "config" / ".security.yml").write_text("model_list: {}\n")
    assert spec.existing_key(tmp_path) == ""


def test_the_mcp_header_is_the_key_when_the_provider_block_has_none(tmp_path):
    """The second copy is a recovery path, not a duplicate to be cleaned up.

    Measured shape: PicoClaw's launcher moves ``api_keys`` into
    ``.security.yml`` on first load, and an install with no model loaded writes
    an empty ``model_list`` in the first place. Either way the provider block has
    no key, and without this the manager would revoke and reissue on every sync.
    """
    spec = PicoclawSpec()
    spec.write_config(tmp_path, _ctx(api_key="sk-only-in-mcp"))
    config = spec.config_path(tmp_path)
    data = json.loads(config.read_text())
    for entry in data["model_list"]:
        entry.pop("api_keys", None)
    config.write_text(json.dumps(data, indent=2))
    assert spec.existing_key(tmp_path) == "sk-only-in-mcp"


def test_the_x64_artifact_has_its_own_checksum():
    """Reusing the arm64 value would verify the wrong file and pass for nothing."""
    spec = PicoclawSpec()
    arm, x64 = spec.artifacts["arm64"], spec.artifacts["x64"]
    assert arm.sha256 != x64.sha256
    assert arm.size != x64.size
    # Both name the vendor mirror first and the official release second.
    for art in (arm, x64):
        assert art.urls[0].startswith("dfss://")
        assert "github.com/sipeed/picoclaw/releases" in art.urls[1]


# -- the real binary reads the generated file -----------------------------

def _real_binary() -> Path | None:
    candidate = LOCAL_RELEASE / "picoclaw"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate
    return None


needs_binary = pytest.mark.skipif(
    _real_binary() is None,
    reason="the official PicoClaw binary is not unpacked on this host",
)


@needs_binary
def test_the_real_binary_accepts_the_generated_config(tmp_path, model_service):
    """PicoClaw itself loads the file, and the fields survive its own loader.

    ``picoclaw agent -m`` reads the config through ``config.LoadConfig`` -- the
    same path the gateway uses -- and exits non-zero on a malformed file. The
    recorded request is the other half: it proves the id and the output cap this
    service receives are the ones the contract names, after PicoClaw's own
    provider layer has had its way with them.
    """
    seen = model_service.requests
    spec = PicoclawSpec()
    spec.write_config(tmp_path, _ctx(service_port=model_service.port,
                                     default_model="qwen3.6-35b-a3b-32k"))
    env = dict(os.environ)
    env.update({
        "HOME": str(tmp_path / "home"),
        "PICOCLAW_HOME": str(tmp_path / "pico-home"),
        "PICOCLAW_CONFIG": str(spec.config_path(tmp_path)),
        "TMPDIR": str(tmp_path / "tmp"),
    })
    (tmp_path / "home").mkdir()
    (tmp_path / "tmp").mkdir()
    out = subprocess.run(
        [str(_real_binary()), "agent", "-m", "hi"],
        capture_output=True, text=True, timeout=180, env=env,
    )
    assert "pong" in out.stdout, (out.stdout[-2000:], out.stderr[-2000:])

    posts = [r for r in seen if r["path"].endswith("/chat/completions")]
    assert posts, "the agent never sent a request"
    body = posts[0]["body"]
    # The id on the wire is the model this service serves, without the prefix.
    assert body["model"] == "qwen3.6-35b-a3b-32k"
    # ...and the output cap is the field this service reads.
    assert body["max_tokens"] == min(MAX_OUTPUT_TOKENS, 32768 // 2)
    assert body["enable_thinking"] is False


@needs_binary
def test_the_real_binary_reads_the_gateway_port_we_choose(tmp_path, model_service):
    """The launcher forks the gateway on ``gateway.port``; that field is honoured.

    Asserted by starting the real launcher and looking at the socket it opens,
    because "we wrote the field" and "it listens there" are different facts. The
    launcher only forks the gateway when the default model passes its own
    reachability probe against this service's ``/v1/models``, so the mock below
    stands in for this service rather than the check being stubbed out.
    """
    spec = PicoclawSpec()
    launcher_port = free_port()
    spec.write_config(tmp_path, _ctx(port=launcher_port,
                                     service_port=model_service.port))
    launcher = LOCAL_RELEASE / "picoclaw-launcher"
    if not launcher.is_file():
        pytest.skip("the official launcher binary is not unpacked on this host")
    env = dict(os.environ)
    env.update(spec.env(tmp_path, "dashboard-secret-1234"))
    env["PICOCLAW_BINARY"] = str(LOCAL_RELEASE / "picoclaw")
    proc = subprocess.Popen(
        [str(launcher), "-console", "-no-browser", "--port", str(launcher_port),
         str(spec.config_path(tmp_path))],
        cwd=str(tmp_path), env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        gateway_port = spec.gateway_port(launcher_port)
        deadline = time.time() + 90
        up = False
        while time.time() < deadline:
            if _listening(launcher_port) and _listening(gateway_port):
                up = True
                break
            time.sleep(0.4)
        output = ""
        if not up:
            _kill_group(proc)
            proc.wait(timeout=30)
            output = proc.stdout.read().decode("utf-8", "replace")[-1500:]
        assert up, (f"launcher or gateway never listened "
                    f"(launcher={launcher_port}, gateway={gateway_port}): {output}")
        # The gateway is in the launcher's own process group, which is why a
        # group signal is enough for a normal stop.
        gateway_pids = [p for p in _children_of(proc.pid)]
        assert gateway_pids, "the gateway is not a child of the launcher"
        assert os.getpgid(gateway_pids[0]) == os.getpgid(proc.pid)
    finally:
        _kill_group(proc)
        proc.wait(timeout=30)


def _children_of(pid: int) -> list[int]:
    """Live children of ``pid``, read from /proc."""
    out: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "status").read_text().splitlines()
        except OSError:
            continue
        for line in fields:
            if line.startswith("PPid:") and line.split()[1] == str(pid):
                out.append(int(entry.name))
    return out


def _listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _kill_group(proc: subprocess.Popen) -> None:
    import signal

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except OSError:
        proc.terminate()


# -- the two-process lifecycle --------------------------------------------

# A launcher stand-in with the shape of the real one: it answers
# ``/api/auth/status`` (public, JSON), accepts ``/api/auth/setup`` while no
# password exists, and forks the *engine binary* -- ``$PICOCLAW_BINARY gateway``
# -- exactly the way the real launcher does. The child is a real process in the
# launcher's own process group, and its executable is the one ``leftovers`` has
# to be able to prove, so the reaping tests exercise the shipped rule rather than
# a stand-in for it.
FAKE_LAUNCHER = textwrap.dedent("""\
import http.server, json, os, socketserver, subprocess, sys, threading

port = int(sys.argv[sys.argv.index('--port') + 1])
config_path = sys.argv[-1]
cfg = json.load(open(config_path))
gateway_port = int(cfg['gateway']['port'])
state_path = os.path.join(os.environ['PICOCLAW_HOME'], 'password.json')

def password():
    try:
        return json.load(open(state_path))['password']
    except (OSError, ValueError, KeyError):
        return ''

def set_password(value):
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    json.dump({'password': value}, open(state_path, 'w'))

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('content-type', 'application/json')
        self.send_header('content-length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if self.path == '/api/auth/status':
            return self._json(200, {'authenticated': False,
                                    'initialized': bool(password())})
        if self.path == '/api/gateway/logs':
            return self._json(200, {'logs': ''})
        return self._json(404, {'error': 'not found'})
    def do_POST(self):
        n = int(self.headers.get('content-length') or 0)
        body = json.loads(self.rfile.read(n) or b'{}')
        if self.path == '/api/auth/setup':
            if password():
                return self._json(401, {'error': 'already initialized'})
            set_password(body.get('password') or '')
            return self._json(200, {'status': 'ok'})
        return self._json(404, {'error': 'not found'})

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

engine = os.environ['PICOCLAW_BINARY']
# ``gateway -E`` is how the real launcher starts its engine; the fake engine
# reads its port from the config the same way.
child = subprocess.Popen([engine, 'gateway', str(gateway_port)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
threading.Thread(target=Server(('127.0.0.1', port), Handler).serve_forever,
                 daemon=True).start()
rc = child.wait()
# The gateway's exit status is the only evidence of a bind that failed, and it
# is otherwise swallowed: this launcher then exits 0, which reaches the manager
# as "进程退出（exit=0），运行 0 秒" with no hint that the *child* is what died.
# The launcher's stdout already goes to the agent's log, so saying it here costs
# nothing and turns that message into a lead. Lifetime is unchanged -- the exit
# is still immediately after the wait.
print('gateway exited rc=%s on port %s' % (rc, gateway_port), flush=True)
""")

# The engine stand-in: answers ``/health``, which is the only thing this service
# asks of it.
FAKE_ENGINE = textwrap.dedent("""\
#!/usr/bin/env python3
import http.server, sys

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

http.server.HTTPServer(('127.0.0.1', int(sys.argv[2])), H).serve_forever()
""")


def _picoclaw_shaped_spec(directory_payload: dict) -> AgentSpec:
    """A spec that runs the fake launcher but keeps PicoClaw's own hooks.

    ``command``, ``health_url``, ``children_ports``, ``after_start`` and
    ``leftovers`` come from the real spec, so what these tests exercise is the
    shipped lifecycle code rather than a second implementation of it.
    """

    class FakePicoclaw(PicoclawSpec):
        id = "picoclaw"
        artifacts = {}

        def command(self, directory: Path, port: int) -> list[str]:
            return [sys.executable,
                    str(Path(directory) / "bin" / "picoclaw-launcher"),
                    "--port", str(port),
                    str(self.config_path(directory))]

        async def install(self, directory, fetch, arch=None, progress=None):
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            for name, content in directory_payload.items():
                (bin_dir / name).write_text(content)
                (bin_dir / name).chmod(0o755)

        def existing_key(self, directory: Path) -> str:
            return "sk-agent-key"

    return FakePicoclaw()


def _manager(tmp_path: Path, spec: AgentSpec) -> AgentManager:
    from app.core.models import ModelManager
    from app.core.state import StateStore

    root = tmp_path / "root"
    (root / "agents").mkdir(parents=True)
    store = StateStore(root / "state" / "state.json")
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    models = ModelManager(models_dir, backend_kind="mock", log_dir=tmp_path / "logs")
    models.refresh()
    return AgentManager(root, key_store=store, models=models, specs=[spec],
                        service_port=18080)


async def _install(mgr: AgentManager) -> None:
    job = await mgr.install("picoclaw")
    for _ in range(200):
        if job.state in ("done", "error"):
            break
        await _sleep(0.05)
    assert job.state == "done", job.message


async def _sleep(seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds)


@pytest.mark.asyncio
async def test_start_provisions_the_dashboard_password_and_waits_for_the_gateway(tmp_path):
    """Both halves of PicoClaw's readiness, through the manager's own start."""
    spec = _picoclaw_shaped_spec({"picoclaw-launcher": FAKE_LAUNCHER,
                                  "picoclaw": FAKE_ENGINE})
    mgr = _manager(tmp_path, spec)
    await _install(mgr)
    st = mgr.state("picoclaw")
    st.port = free_port()
    st.secret = "dashboard-secret-1234"
    mgr.save_state()

    status = await mgr.start("picoclaw")
    try:
        assert status["status"] == "running"
        assert status["last_error"] == ""
        # The password PicoClaw now holds is the agent's own secret -- that is
        # what the console shows on the card.
        state_path = mgr.directory("picoclaw") / "data" / "picoclaw" / "password.json"
        assert json.loads(state_path.read_text())["password"] == "dashboard-secret-1234"
        # ...and the gateway the launcher forked is really up.
        assert _listening(spec.gateway_port(st.port))
        assert status["child_ports"] == [spec.gateway_port(st.port)]
    finally:
        await mgr.stop("picoclaw")


@pytest.mark.asyncio
async def test_stop_takes_the_gateway_with_the_launcher(tmp_path):
    """A stop must not leave a gateway holding the model connection."""
    spec = _picoclaw_shaped_spec({"picoclaw-launcher": FAKE_LAUNCHER,
                                  "picoclaw": FAKE_ENGINE})
    mgr = _manager(tmp_path, spec)
    await _install(mgr)
    st = mgr.state("picoclaw")
    st.port = free_port()
    mgr.save_state()

    await mgr.start("picoclaw")
    gateway_port = spec.gateway_port(st.port)
    assert _listening(gateway_port)
    await mgr.stop("picoclaw")
    await _sleep(0.6)
    assert not _listening(st.port)
    assert not _listening(gateway_port), "the gateway outlived the launcher"


@pytest.mark.asyncio
async def test_a_gateway_whose_launcher_died_is_still_collected(tmp_path):
    """The case a group signal cannot cover: the parent is already gone.

    Provoked by killing only the launcher -- the gateway is left reparented, and
    a stop must still reap it, or the next start fails on a busy port.
    """
    spec = _picoclaw_shaped_spec({"picoclaw-launcher": FAKE_LAUNCHER,
                                  "picoclaw": FAKE_ENGINE})
    mgr = _manager(tmp_path, spec)
    await _install(mgr)
    st = mgr.state("picoclaw")
    st.port = free_port()
    mgr.save_state()

    await mgr.start("picoclaw")
    gateway_port = spec.gateway_port(st.port)
    rt = mgr._runtime["picoclaw"]
    launcher_pid = rt.proc.pid
    os.kill(launcher_pid, 9)
    await _sleep(0.8)
    assert _listening(gateway_port), "the fixture did not leave a live gateway"

    await mgr.stop("picoclaw")
    await _sleep(0.8)
    assert not _listening(gateway_port), "the orphaned gateway was not reaped"


@pytest.mark.asyncio
async def test_the_gateway_port_cannot_be_given_to_another_agent(tmp_path):
    """``port + 1`` belongs to this agent even though no command line names it.

    A conflict check that only looks at the port it was handed would happily
    move another agent onto PicoClaw's gateway port, and the start that failed
    would be the *other* agent's -- with an EADDRINUSE on a number neither the
    console nor ``agents.json`` ever mentioned.
    """
    spec = _picoclaw_shaped_spec({"picoclaw-launcher": FAKE_LAUNCHER,
                                  "picoclaw": FAKE_ENGINE})
    mgr = _manager(tmp_path, spec)
    await _install(mgr)

    class Other(AgentSpec):
        id = "other"
        name = "另一个 agent"
        default_port = 14150
        executable = "other"
        artifacts = {}

        def command(self, directory, port):
            return [sys.executable, "-c", "pass"]

    other = Other()
    mgr.specs["other"] = other
    mgr.states["other"] = mgr.state("other")
    mgr._runtime["other"] = type(mgr._runtime["picoclaw"])()

    # PicoClaw is up (the manager's conflict rules are about two live agents),
    # and its gateway owns the next port up.
    mgr.state("picoclaw").port = DEFAULT_PORT
    mgr.save_state()

    class FakeProc:
        pid = 0
        returncode = None

        def send_signal(self, sig):
            pass

    mgr._runtime["picoclaw"].proc = FakeProc()

    with pytest.raises(PortBusy, match=str(DEFAULT_PORT + 1)):
        mgr._check_port("other", DEFAULT_PORT + 1)
    # A port of its own is fine -- only the gateway's number is taken.
    mgr._check_port("other", 14150)


@pytest.mark.asyncio
async def test_a_live_gateway_that_never_answers_is_reported_not_hidden(tmp_path):
    """A launcher with a dead gateway looks healthy; the start must say so.

    This is the failure with no other symptom: the dashboard loads, the console
    shows "running", and no message is ever answered. Provoked by forking a child
    that stays alive but never listens, so the launcher keeps running alone --
    exactly what a gateway that cannot start leaves behind.
    """
    broken = FAKE_LAUNCHER.replace(
        "child = subprocess.Popen([engine, 'gateway', str(gateway_port)],\n"
        "                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)",
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3600)'])",
    )
    assert "child.wait()" in broken
    spec = _picoclaw_shaped_spec({"picoclaw-launcher": broken,
                                  "picoclaw": FAKE_ENGINE})
    spec.start_timeout = 60.0
    mgr = _manager(tmp_path, spec)
    await _install(mgr)
    st = mgr.state("picoclaw")
    st.port = free_port()
    mgr.save_state()

    import app.agents.picoclaw as picoclaw_mod
    original = picoclaw_mod.GATEWAY_TIMEOUT_S
    picoclaw_mod.GATEWAY_TIMEOUT_S = 1.5
    try:
        status = await mgr.start("picoclaw")
    finally:
        picoclaw_mod.GATEWAY_TIMEOUT_S = original
        await mgr.stop("picoclaw")
    assert status["status"] == "running"
    assert "gateway" in status["last_error"]
    assert str(spec.gateway_port(st.port)) in status["last_error"]


@pytest.mark.asyncio
async def test_restart_handshakes_the_gateway_again(tmp_path):
    """A restart is stop+start, and the second start must not think it is done.

    The password is already provisioned by then, so this also covers the branch
    that must skip ``/api/auth/setup`` -- calling it again would be refused as
    unauthenticated and would fail the restart.
    """
    spec = _picoclaw_shaped_spec({"picoclaw-launcher": FAKE_LAUNCHER,
                                  "picoclaw": FAKE_ENGINE})
    mgr = _manager(tmp_path, spec)
    await _install(mgr)
    st = mgr.state("picoclaw")
    st.port = free_port()
    mgr.save_state()

    await mgr.start("picoclaw")
    status = await mgr.restart("picoclaw")
    try:
        assert status["status"] == "running"
        assert status["last_error"] == ""
        assert _listening(spec.gateway_port(st.port))
    finally:
        await mgr.stop("picoclaw")


@pytest.mark.asyncio
async def test_uninstall_leaves_no_launcher_and_no_gateway(tmp_path):
    spec = _picoclaw_shaped_spec({"picoclaw-launcher": FAKE_LAUNCHER,
                                  "picoclaw": FAKE_ENGINE})
    mgr = _manager(tmp_path, spec)
    await _install(mgr)
    st = mgr.state("picoclaw")
    st.port = free_port()
    mgr.save_state()

    await mgr.start("picoclaw")
    gateway_port = spec.gateway_port(st.port)
    await mgr.uninstall("picoclaw")
    await _sleep(0.8)
    assert not mgr.directory("picoclaw").exists()
    assert not _listening(st.port)
    assert not _listening(gateway_port)


@pytest.mark.asyncio
async def test_reset_reissues_the_password_store_too(tmp_path):
    """A reset must take the launcher's password store with the config.

    Otherwise the agent keeps a password the console no longer shows, and the
    next start's provisioning would be refused as unauthenticated.
    """
    spec = _picoclaw_shaped_spec({"picoclaw-launcher": FAKE_LAUNCHER,
                                  "picoclaw": FAKE_ENGINE})
    mgr = _manager(tmp_path, spec)
    await _install(mgr)
    st = mgr.state("picoclaw")
    st.port = free_port()
    mgr.save_state()

    await mgr.start("picoclaw")
    state_path = mgr.directory("picoclaw") / "data" / "picoclaw" / "password.json"
    assert state_path.is_file()
    await mgr.reset("picoclaw")
    assert not state_path.exists(), "reset kept the launcher's password store"
    status = await mgr.start("picoclaw")
    try:
        assert status["status"] == "running"
        assert json.loads(state_path.read_text())["password"] == mgr.state("picoclaw").secret
    finally:
        await mgr.stop("picoclaw")


# -- the console's card order ---------------------------------------------

def test_dsh_is_first_in_the_console(tmp_path):
    """The order of the default spec list *is* the order of the cards.

    DSH leads because the operator asked for it there (MYS-2293). The other
    three keep the order they had, and nothing sorts the list behind the page's
    back.
    """
    from app.core.models import ModelManager
    from app.core.state import StateStore

    root = tmp_path / "root"
    (root / "agents").mkdir(parents=True)
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    models = ModelManager(models_dir, backend_kind="mock", log_dir=tmp_path / "logs")
    models.refresh()
    mgr = AgentManager(root, key_store=StateStore(root / "state" / "state.json"),
                       models=models)
    assert list(mgr.specs) == ["dsh", "picoclaw", "opencode", "openclaw"]
    assert [s["id"] for s in mgr.status()] == [
        "dsh", "picoclaw", "opencode", "openclaw"]


def test_the_agents_api_returns_dsh_first(tmp_path):
    """The console's card order comes from the API, not from the page's own list.

    Asserted on the response the page consumes: ``status_all`` keeps the spec
    list's order, so this is also the guard that nothing sorts the agents by id
    or by install state behind the page's back.
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    app = create_app(
        data_dir=tmp_path / "state", models_dir=models_dir, backend_kind="mock",
        web_dir=tmp_path / "web", data_root=tmp_path / "root", service_port=18080,
    )
    with TestClient(app) as client:
        assert client.post("/api/login", json={"password": "admin"}).status_code == 200
        r = client.get("/api/agents")
    assert r.status_code == 200
    ids = [a["id"] for a in r.json()["agents"]]
    assert ids == ["dsh", "picoclaw", "opencode", "openclaw"]


# -- the proxy: the dashboard's own URLs ----------------------------------

@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_shim_moves_a_ws_url_under_the_prefix(tmp_path):
    """PicoClaw builds ``ws://host/pico/ws``; a ``ws:`` URL is not another origin.

    The shim used to compare ``URL.origin`` exactly, and ``origin`` for a
    WebSocket address is ``ws://host`` -- so the socket stayed at the site root
    and the upgrade 404'd. Here the browser's own URL builder decides, which is
    why this runs in node rather than against a Python string.
    """
    script = tmp_path / "ws.js"
    script.write_text(_WS_HARNESS.replace("SHIM", _shim_js()))
    out = subprocess.run(["node", str(script)], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    # ``ws://`` and ``wss://`` both resolve to their own scheme; what matters is
    # that the path is under the prefix on the same host.
    assert got["ws"] == "ws://board:8000/agents/prox/pico/ws"
    assert got["wss"] == "wss://board:8000/agents/prox/pico/ws"
    assert got["relative"] == "http://board:8000/agents/prox/pico/ws"
    # A different host is still somebody else's business.
    assert got["other_host"] == "wss://elsewhere.example/pico/ws"


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_router_initialises_under_the_prefix(tmp_path):
    """The reported crash, run for real: the router must not call a receiver's method.

    This is the gap the previous delivery left: ``_WS_HARNESS`` only proved the
    shim moves a socket URL, so a bundle whose *router* was rewritten into
    ``e.__consolePath(...)`` passed CI and still showed
    ``Something went wrong!`` on the board. Here the rewritten call sites are
    the four shapes PicoClaw 0.3.1 actually ships -- ``t.``, ``e.``,
    ``globalThis.`` and a ``window`` binding that is the *module's* namespace,
    not the global, exactly as a bundler parameter shadows it.

    The assertion is the user-visible one: every pathname the router ends up
    with is ``/launcher-login`` rather than ``/agents/picoclaw/launcher-login``,
    and nothing throws.
    """
    got = _run_router(tmp_path, _PrefixRewriter(BASE_PATH).js(B_ROUTER_BUNDLE))
    assert got["errors"] == []
    assert got["parse"] == "/launcher-login"
    assert got["lookup"] == "launcher-login"
    assert got["select"] == "/launcher-login"
    assert got["globalthis"] == "/launcher-login"
    assert got["namespace_window"] == "/launcher-login"
    # The module's own ``window`` binding is not a place to hang a helper on.
    assert got["namespace_window_untouched"] is True
    # Hard navigations stay inside the prefix, and ``replace`` keeps its
    # history-replacing semantics (``assign`` would add an entry).
    assert got["navs"] == [
        ["assign", f"{BASE_PATH}/"],
        ["replace", f"{BASE_PATH}/launcher-setup"],
        # Somebody else's origin is still theirs to navigate to.
        ["assign", "https://elsewhere.example/auth"],
    ]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_login_navigation_would_leave_the_prefix_without_the_rewrite(tmp_path):
    """Pin the second half of the bug: the sign-in redirect escaped the prefix.

    With only the pathname fix, the router initialises and the login form
    renders -- and then a successful sign-in runs ``location.assign(`/`)``,
    which is a *hard* navigation to a prefix-less path. Measured in Chromium on
    the board: the browser left ``/agents/picoclaw/`` and loaded the console's
    own SPA inside the frame, so the user saw the console where the agent should
    be. Running the same bundle unrewritten reproduces exactly that.
    """
    got = _run_router(tmp_path, B_ROUTER_BUNDLE)
    assert got["errors"] == []
    assert got["navs"][0] == ["assign", "/"], "the unrewritten bundle goes to '/'"


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_previous_rewrite_of_the_same_bundle_crashes(tmp_path):
    """The harness is only worth anything if it fails on the code that shipped.

    The old implementation replaced the substring ``location.pathname``, so
    ``e.location.pathname`` became ``e.__consolePath(location.pathname)``. Run
    through the same harness, that reproduces the board's error verbatim --
    which is what proves the test above actually covers the bug instead of
    merely describing it.
    """
    old = B_ROUTER_BUNDLE.replace(
        "location.pathname", "__consolePath(location.pathname)")
    got = _run_router(tmp_path, old)
    assert got["errors"], "the old rewrite was expected to throw"
    assert "__consolePath is not a function" in got["errors"][0]


def _run_router(tmp_path, bundle: str) -> dict:
    script = tmp_path / "router.js"
    script.write_text(
        ROUTER_HARNESS.replace("SHIM", _shim_js()).replace("BUNDLE", bundle))
    out = subprocess.run(["node", str(script)], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# The router initialisation from PicoClaw 0.3.1's ``index-B3x-7GgS.js``,
# reduced to the four pathname reads it contains, each keeping the receiver it
# really uses. ``window`` is the function's own parameter -- the bundler's
# namespace binding, which shadows the global and carries no console helper.
B_ROUTER_BUNDLE = r"""
function run(window) {
  const t = globalThis;      // the router's window handle: ``e?.window ?? window``
  const e = store;           // the router's store, which has no such method
  return {
    parse: () => `${t.location.pathname}${t.location.search}`,
    lookup: () => {
      const n = e.location.pathname.match(/\/([a-zA-Z-]*)/g);
      return Array.isArray(n) ? n[0]?.replace(`/`, ``) : undefined;
    },
    select: () => ({pathname: e.location.pathname, matches: []}),
    globalthis: () => String(globalThis.location.pathname || `/`),
    namespace_window: () => window.location.pathname,
    // The three hard navigations PicoClaw's login screen performs, verbatim.
    goRoot: () => globalThis.location.assign(`/`),
    goSetup: () => globalThis.location.replace(`/launcher-setup`),
    goElsewhere: () => window.location.assign(`https://elsewhere.example/auth`),
  };
}
"""


# The browser-shaped scope PicoClaw's bundle runs in. ``window`` *is* the
# global here, which is what makes ``window.__consolePath = ...`` in the shim
# define a resolvable bare name; the bundle's ``window`` parameter above then
# shadows it for the file's own reads.
ROUTER_HARNESS = r"""
const report = {errors: [], namespace_window_untouched: true};
const navs = [];
// A stand-in for the real ``Location``: it records what the page would be told
// to navigate to, and which method carried it. The *read* side (``href``,
// ``pathname``) delegates to a real URL so the shim's same-origin rule sees
// what a browser would. Every navigation the console intercepts is a write,
// which is exactly what a browser's Location also refuses to let us patch.
const realLoc = new URL("http://board:8000/agents/picoclaw/launcher-login");
const fakeLoc = {
  assign(u) { navs.push(["assign", String(u)]); },
  replace(u) { navs.push(["replace", String(u)]); },
  set href(u) { navs.push(["assign", String(u)]); },
  get href() { return realLoc.href; },
  get pathname() { return realLoc.pathname; },
  get search() { return realLoc.search; },
  get host() { return realLoc.host; },
};
globalThis.window = globalThis;
globalThis.location = fakeLoc;
globalThis.document = {
  currentScript: {getAttribute: () => "/agents/picoclaw"},
  createElement: () => ({}), addEventListener() {},
};
globalThis.history = {pushState() {}, replaceState() {}, state: null};
globalThis.XMLHttpRequest = function () {};
XMLHttpRequest.prototype.open = function () {};
globalThis.Element = function () {};
Element.prototype.setAttribute = function () {};
SHIM
// Both bindings are taken *after* the swap, so the bundle's receivers and the
// global agree on which object is the address bar.
const store = {location: fakeLoc};
const namespaceWindow = {location: fakeLoc};
BUNDLE
try {
  const r = run(namespaceWindow);
  report.parse = globalThis.__consolePath(r.parse());
  report.lookup = r.lookup();
  report.select = r.select().pathname;
  report.globalthis = r.globalthis();
  report.namespace_window = r.namespace_window();
  if (namespaceWindow.__consolePath !== undefined) {
    report.namespace_window_untouched = false;
  }
  // Hard navigations go through the shim's own helper: a fake Location records
  // where the page would end up, and which method was used.
  r.goRoot();
  r.goSetup();
  r.goElsewhere();
  report.navs = navs;
} catch (err) {
  report.errors.push(String((err && err.message) || err));
}
console.log(JSON.stringify(report));
"""


_WS_HARNESS = r"""
const seen = [];
globalThis.window = globalThis;
globalThis.location = new URL("http://board:8000/agents/prox/");
globalThis.document = {currentScript: {getAttribute: () => "/agents/prox"},
                       createElement: () => ({}), addEventListener() {}};
globalThis.history = {pushState() {}, replaceState() {}};
globalThis.XMLHttpRequest = function () {};
XMLHttpRequest.prototype.open = function () {};
globalThis.Element = function () {};
Element.prototype.setAttribute = function () {};
// The shim hands the WebSocket constructor whatever the hook produced; a
// browser then resolves a relative value against the page, and so does this --
// otherwise "did the prefix survive" and "was the URL absolute" would be
// indistinguishable.
class FakeSocket { constructor(u) { seen.push(new URL(u, location.href).href); } }
globalThis.WebSocket = FakeSocket;
FakeSocket.prototype = {CONNECTING: 0};
SHIM
(() => {
  const mk = (u) => new window.WebSocket(u);
  mk("ws://board:8000/pico/ws");
  mk("wss://board:8000/pico/ws");
  mk("/pico/ws");
  mk("wss://elsewhere.example/pico/ws");
  console.log(JSON.stringify({ws: seen[0], wss: seen[1], relative: seen[2],
                              other_host: seen[3]}));
})();
"""


def test_the_prefix_rewriter_leaves_the_paths_picoclaw_serves_alone():
    """Assets and API paths are the app's own; only the prefix is added.

    The rewriter must not touch a URL that is already inside the subtree, which
    is what makes a double-rewrite (the shim on top of the server-side pass)
    harmless.
    """
    from app.api.agent_proxy import _PrefixRewriter

    rw = _PrefixRewriter(BASE_PATH)
    html = (
        '<script type="module" crossorigin src="/assets/index-abc.js"></script>'
        '<link rel="stylesheet" href="/assets/index-abc.css">'
        '<link rel="icon" href="/favicon.svg">'
    )
    out = rw.html(html)
    assert f'src="{BASE_PATH}/assets/index-abc.js"' in out
    assert f'href="{BASE_PATH}/assets/index-abc.css"' in out
    assert f'href="{BASE_PATH}/favicon.svg"' in out
    # The shim is injected before the app's own scripts, with the prefix on it.
    assert f'src="{BASE_PATH}/' in out
    assert out.index("_console_proxy.js") < out.index("index-abc.js")


def test_the_upstream_ws_path_is_stripped_for_a_prefix_agent():
    """What the launcher is asked for: its own path, without this console's prefix."""
    from app.api.agent_proxy import _upstream_ws_path

    spec = PicoclawSpec()
    prefix = BASE_PATH
    assert _upstream_ws_path(spec, f"{prefix}/pico/ws") == "/pico/ws"
    assert _upstream_ws_path(spec, f"{prefix}/pico/media/abc") == "/pico/media/abc"
    assert _upstream_ws_path(spec, prefix) == "/"

    from app.agents.openclaw import OpenclawSpec

    # OpenClaw's basePath *is* the prefix, so its path must arrive unchanged.
    assert _upstream_ws_path(OpenclawSpec(), f"{prefix}/pico/ws") == f"{prefix}/pico/ws"


def test_the_gateway_port_allocation_avoids_the_ephemeral_range():
    """The helper behind every lifecycle test must not hand out a port the
    kernel can also give to an outbound connection.

    This is the fix for the intermittent ``进程退出（exit=0），运行 0 秒``: a
    port drawn with ``bind(("127.0.0.1", 0))`` comes from
    ``ip_local_port_range``, and ``port + 1`` -- the gateway's number -- came
    from the same pool. One of the process' own connections taking it makes the
    gateway's bind fail, which the launcher reports as a clean exit. Two
    properties prevent it, and both are asserted here rather than left to the
    docstring: the pair sits below the range, and both numbers are really free.
    """
    low = _ephemeral_low()
    for _ in range(20):
        port = free_port()
        assert port + 1 < low, (
            f"free_port() gave {port}, whose gateway port {port + 1} is inside "
            f"the ephemeral range {low}+ -- an outbound connection can take it")
        assert _port_is_free(port), f"{port} is not actually free"
        assert _port_is_free(port + 1), f"gateway port {port + 1} is not free"


def test_a_taken_gateway_port_is_the_failure_the_helper_avoids():
    """The bug, reproduced deterministically, so the guard above has a reason.

    An outbound connection parks its local port in ESTABLISHED. A bind on that
    number then fails (so the gateway dies) while a connect probe calls it free
    -- which is why the manager's own ``_port_in_use`` could not have caught it
    and why the fix belongs in the test's allocation rather than in the manager.
    """
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    client = socket.socket()
    client.connect(listener.getsockname())
    try:
        held = client.getsockname()[1]
        # What the gateway asks: can I bind?
        assert not _port_is_free(held), "a held port accepted a bind"
        # What a connect probe asks: is somebody serving here?
        from app.agents.manager import _port_in_use
        assert not _port_in_use(held), (
            "the connect probe now sees ESTABLISHED ports; the comment on "
            "_port_in_use and this test's premise need revisiting")
    finally:
        client.close()
        listener.close()


def test_the_launcher_is_started_in_the_foreground_with_its_own_port(tmp_path):
    """``-console`` keeps it a process this manager owns; ``--port`` is its listen port."""
    spec = PicoclawSpec()
    cmd = spec.command(tmp_path, DEFAULT_PORT)
    assert cmd[0] == str(tmp_path / "bin" / "picoclaw-launcher")
    assert "-console" in cmd
    assert "-no-browser" in cmd
    assert cmd[cmd.index("--port") + 1] == str(DEFAULT_PORT)
    assert cmd[-1] == str(spec.config_path(tmp_path))
    # The engine binary is named through the environment, not the command line:
    # the launcher is what the manager supervises.
    env = spec.env(tmp_path, "s")
    assert env["PICOCLAW_BINARY"] == str(tmp_path / "bin" / "picoclaw")
    assert env["PICOCLAW_HOME"] == str(tmp_path / "data" / "picoclaw")
    # The gateway's port is not on any command line, so it has to be declared.
    assert spec.children_ports(tmp_path, DEFAULT_PORT) == (DEFAULT_PORT + 1,)


# -- the launcher's own redirects -----------------------------------------

@pytest.mark.parametrize("value", [
    "/launcher-login",
    "http://127.0.0.1:18800/launcher-login",
    "http://localhost:18800/launcher-login",
])
def test_every_form_of_the_launchers_redirect_stays_inside_the_prefix(value):
    """PicoClaw's dashboard answers ``/`` with a redirect to its login page.

    Measured on the board: it is root-relative (``Location: /launcher-login``),
    and passed through unchanged the browser leaves ``/agents/picoclaw/`` and
    lands on the *console's* router -- the embedded frame then shows the console
    inside itself. The absolute-loopback form is the same failure with a host the
    browser cannot reach. All three forms have to arrive under the prefix, and a
    path already there must not be prefixed twice.
    """
    from app.api.agent_proxy import _rewrite_location

    spec = PicoclawSpec()
    assert _rewrite_location(value, 8000, spec) == f"{BASE_PATH}/launcher-login"
    # idempotent: the second pass changes nothing
    once = _rewrite_location(value, 8000, spec)
    assert _rewrite_location(once, 8000, spec) == once


def test_a_relative_redirect_is_left_alone():
    """A value with no leading slash already resolves inside the prefix."""
    from app.api.agent_proxy import _rewrite_location

    assert _rewrite_location("login", 8000, PicoclawSpec()) == "login"
    assert _rewrite_location("?next=1", 8000, PicoclawSpec()) == "?next=1"


def test_another_origin_redirect_is_never_rewritten():
    from app.api.agent_proxy import _rewrite_location

    spec = PicoclawSpec()
    assert _rewrite_location("https://accounts.example/oauth", 8000, spec) == \
        "https://accounts.example/oauth"


def test_a_base_path_agent_keeps_its_own_redirects():
    """OpenClaw's basePath *is* the prefix, so its paths are already correct."""
    from app.api.agent_proxy import _rewrite_location
    from app.agents.openclaw import OpenclawSpec

    spec = OpenclawSpec()
    assert _rewrite_location("/agents/openclaw/chat", 8000, spec) == \
        "/agents/openclaw/chat"
    # Only the unreachable absolute form is replaced.
    assert _rewrite_location("http://127.0.0.1:18790/agents/openclaw/chat",
                             8000, spec) == "/agents/openclaw/chat"


def test_the_ws_bridge_does_not_duplicate_the_host_header():
    """A hand-written ``Host`` sends a second, malformed one.

    Measured against PicoClaw 0.3.1's launcher: a handshake with an explicit
    ``Host`` is answered 400, while the identical one without it succeeds --
    the WebSocket client already derives it from the URL. OpenClaw happened to
    tolerate the duplicate, so this only surfaced with the new agent.
    """
    import inspect

    from app.api import agent_proxy

    source = inspect.getsource(agent_proxy._bridge_ws)
    assert '"Host"' not in source and "'Host'" not in source, \
        "the bridge must let the client derive Host"
    # The Origin the agent's own config allows is still presented.
    assert '"Origin"' in source or "'Origin'" in source


# -- a stopped agent still gets its new settings --------------------------

@pytest.mark.asyncio
async def test_changing_the_model_of_a_stopped_agent_rewrites_its_config(tmp_path):
    """State and config must not disagree while an agent is stopped.

    Measured on the board: switching a *stopped* OpenClaw to the 32k model saved
    the new default to ``agents.json`` and left ``openclaw.json`` naming the
    128k one -- the console showed 32k, the next start would have run 128k. The
    restart path rewrote the config because a restart implies a start; the
    stopped path has to do it explicitly.
    """
    spec = _picoclaw_shaped_spec({"picoclaw-launcher": FAKE_LAUNCHER,
                                  "picoclaw": FAKE_ENGINE})
    mgr = _manager(tmp_path, spec)
    await _install(mgr)
    st = mgr.state("picoclaw")
    st.port = free_port()
    mgr.save_state()
    # Two models to choose between, at the two contexts the board really has.
    from app.core.models import ModelInfo

    mgr.models._models = {
        "m-128k": ModelInfo(model_id="m-128k", path="", display_name="",
                            context_length=131072, supports_vision=True),
        "m-32k": ModelInfo(model_id="m-32k", path="", display_name="",
                           context_length=32768, supports_vision=True),
    }
    await mgr.sync("picoclaw")
    await mgr.patch("picoclaw", {"default_model": "m-128k"})
    assert spec.existing_key(mgr.directory("picoclaw"))  # config exists
    cfg = json.loads(spec.config_path(mgr.directory("picoclaw")).read_text())
    assert cfg["agents"]["defaults"]["model_name"] == "m-128k"
    assert cfg["agents"]["defaults"]["context_window"] == 131072

    # The agent is stopped: this is the case that used to only touch agents.json.
    await mgr.patch("picoclaw", {"default_model": "m-32k"})
    cfg = json.loads(spec.config_path(mgr.directory("picoclaw")).read_text())
    assert cfg["agents"]["defaults"]["model_name"] == "m-32k"
    assert cfg["agents"]["defaults"]["context_window"] == 32768
    assert cfg["agents"]["defaults"]["max_tokens"] == min(MAX_OUTPUT_TOKENS, 32768 // 2)
