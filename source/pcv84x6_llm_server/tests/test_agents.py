"""The agent framework: install, config, supervision and the HTTP surface.

The fake agent these tests install is a real process -- a small Python HTTP
server packed into a real tar.gz -- because most of what can go wrong here is
process-shaped: a child that keeps the parent's HOME, a process group that
survives a stop, a crash that needs restarting. Mocking the subprocess would
test the mock.

Only the parts that cannot run on a build host are faked: the download source is
a local file (`file://`), and the free-memory reading is monkeypatched.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import socket
import sys
import tarfile
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents import manager as manager_mod
from app.agents import opencode as opencode_mod
from app.agents.manager import (
    AgentBusy,
    AgentError,
    AgentManager,
    AgentState,
    MemoryLow,
    PortBusy,
)
from app.agents.opencode import SPEC as OPENCODE_SPEC, OpencodeSpec
from app.agents.opencode import PROVIDER
from app.agents.spec import AgentSpec, Artifact, InstallContext, ModelChoice, host_arch
from app.main import create_app

# A minimal but real server: it answers /health, echoes its own environment on
# /env (that is how the isolation assertions read the child's HOME), and exits
# on demand so a crash can be provoked.
FAKE_AGENT = """\
import http.server, json, os, signal, socketserver, sys

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == '/health':
            body = json.dumps({'ok': True}).encode()
        elif self.path == '/env':
            body = json.dumps(dict(os.environ)).encode()
        elif self.path == '/cwd':
            body = json.dumps({'cwd': os.getcwd(), 'pid': os.getpid(),
                               'pgid': os.getpgid(0)}).encode()
        elif self.path == '/crash-me':
            # Leave a marker so the restarted process can prove it is a
            # different lifetime, then die.
            open(os.path.join(os.environ['HOME'], '..', 'logs', 'crashed'), 'a').write('x')
            body = b'{"bye": true}'
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            os._exit(3)
        else:
            body = b'{"ok": true}'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

class Server(socketserver.TCPServer):
    allow_reuse_address = True

port = int(sys.argv[sys.argv.index('--port') + 1])
# Set by a test that wants a flapping agent: serve /health once, then die, so
# every lifetime is a crash the moment the supervisor counts it as healthy.
die_after = float(os.environ.get('FAKE_DIE_AFTER', '0') or 0)
if die_after:
    import threading
    def _suicide():
        import time
        time.sleep(die_after)
        os._exit(9)
    threading.Thread(target=_suicide, daemon=True).start()
Server(('0.0.0.0', port), Handler).serve_forever()
"""


class FakeSpec(AgentSpec):
    id = "fake"
    name = "假 agent"
    version = "1.0.0"
    default_port = 14196
    embeddable = True
    start_timeout = 30.0
    executable = "fake-agent"
    payload_root = "bin"
    # This agent has no config file, so there is nowhere for the key to live.
    key_in_config = False

    def command(self, directory: Path, port: int) -> list[str]:
        return [sys.executable, str(Path(directory) / "bin" / "fake-agent"), "--port", str(port)]


# -- helpers ---------------------------------------------------------------
def build_tarball(path: Path, payload: dict[str, bytes | str], *, raw: bool = False) -> Path:
    """A tar.gz in the shape an upstream release ships (one wrapper dir)."""
    with tarfile.open(path, "w:gz") as tf:
        for name, content in payload.items():
            data = content.encode() if isinstance(content, str) else content
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(data))
    return path


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Svc:
    """A manager wired to a fake spec, plus the store/models it needs."""

    def __init__(self, tmp_path: Path, tarball: Path, **spec_overrides) -> None:
        from app.core.models import ModelManager
        from app.core.state import StateStore

        root = tmp_path / "root"
        (root / "agents").mkdir(parents=True)
        self.store = StateStore(root / "state" / "state.json")
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        self.models = ModelManager(models_dir, backend_kind="mock", log_dir=tmp_path / "logs")
        self.models.refresh()

        art = Artifact(urls=(f"file://{tarball}",), sha256=sha256_of(tarball))
        self.spec = FakeSpec(artifacts={host_arch(): art}, **spec_overrides)
        # The bytes an install must produce, kept on the fixture so a test that
        # fakes a download source can hand back exactly that payload.
        self.tarball = tarball
        self.payload = tarball.read_bytes()
        self.mgr = AgentManager(
            root, key_store=self.store, models=self.models, specs=[self.spec],
            service_port=18080,
        )

    @property
    def directory(self) -> Path:
        return self.mgr.directory("fake")


@pytest.fixture()
def svc(tmp_path):
    tarball = build_tarball(
        tmp_path / "fake-1.0.0.tar.gz",
        {"fake-1.0.0/bin/fake-agent": textwrap.dedent(FAKE_AGENT)},
    )
    return Svc(tmp_path, tarball)


async def install(svc: Svc) -> None:
    job = await svc.mgr.install("fake")
    await wait_job(svc)
    assert job.state == "done", job.message


async def wait_job(svc: Svc, timeout: float = 20.0) -> dict:
    for _ in range(int(timeout / 0.05)):
        job = svc.mgr.job("fake")
        if job and job["state"] in ("done", "error"):
            return job
        await asyncio.sleep(0.05)
    raise AssertionError("install job did not finish")


def http_get(port: int, path: str = "/health", timeout: float = 5.0) -> dict:
    """A plain socket GET: the tests must not depend on an async client."""
    import urllib.request

    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
        return json.loads(r.read())


# -- install ---------------------------------------------------------------
async def test_install_unpacks_payload_and_reports_progress(svc):
    await install(svc)
    assert svc.mgr.installed("fake")
    exe = svc.directory / "bin" / "fake-agent"
    assert exe.is_file()
    assert os.access(exe, os.X_OK)
    # The wrapper directory is an artifact of the archive, not part of the tree.
    assert not (svc.directory / "bin" / "fake-1.0.0").exists()
    for layer in ("home", "config", "data", "cache", "state", "tmp", "workspace", "logs"):
        assert (svc.directory / layer).is_dir(), layer
    job = svc.mgr.job("fake")
    assert job["percent"] == 100.0
    assert svc.mgr.status_one("fake")["status"] == "stopped"


async def test_install_rejects_a_checksum_mismatch(tmp_path):
    tarball = build_tarball(
        tmp_path / "fake.tar.gz", {"fake/bin/fake-agent": textwrap.dedent(FAKE_AGENT)},
    )
    svc = Svc(tmp_path, tarball)
    # Corrupt the expectation, not the file: the download succeeds and the
    # verification is what must reject it.
    svc.spec.artifacts[host_arch()] = Artifact(
        urls=(f"file://{tarball}",), sha256="0" * 64,
    )
    job = await svc.mgr.install("fake")
    await wait_job(svc)
    assert job.state == "error"
    assert "sha256" in job.message
    assert not svc.mgr.installed("fake")
    # The bad download is deleted rather than left to be picked up as a cache hit.
    assert not list((tmp_path / "root" / "downloads").glob("*.part"))
    assert not list((tmp_path / "root" / "downloads").glob("*.tar.gz"))


async def test_install_is_refused_when_already_installed(svc):
    await install(svc)
    with pytest.raises(AgentBusy, match="已经安装"):
        await svc.mgr.install("fake")


async def test_install_falls_through_a_dead_mirror_to_the_next_url(tmp_path):
    """A mirror that cannot be reached must not fail the install."""
    tarball = build_tarball(
        tmp_path / "fake.tar.gz", {"fake/bin/fake-agent": textwrap.dedent(FAKE_AGENT)},
    )
    svc = Svc(tmp_path, tarball)
    svc.spec.artifacts[host_arch()] = Artifact(
        urls=(f"file://{tmp_path}/does-not-exist.tar.gz", f"file://{tarball}"),
        sha256=sha256_of(tarball),
    )
    await svc.mgr.install("fake")
    job = await wait_job(svc)
    assert job["state"] == "done", job["message"]


# -- dfss source -----------------------------------------------------------
DFSS_A = "dfss://open@sophgo.com:/tools/cv84x6_llm_server/agents/fake-a.tar.gz"
HTTP_B = "https://example.invalid/fake-b.tar.gz"


@pytest.fixture()
def dfss_svc(tmp_path):
    """A service whose artifact prefers dfss and falls back to an HTTP URL."""
    tarball = build_tarball(
        tmp_path / "fake.tar.gz", {"fake/bin/fake-agent": textwrap.dedent(FAKE_AGENT)},
    )
    svc = Svc(tmp_path, tarball)
    svc.spec.artifacts[host_arch()] = Artifact(
        urls=(DFSS_A, HTTP_B), sha256=sha256_of(tarball), size=tarball.stat().st_size,
    )
    return svc


def _canned_dfss(monkeypatch, manager_mod, payload: bytes, *, fail: str = ""):
    """Replace the dfss subprocess with one that writes ``payload``.

    The install logic (scheme dispatch, ordering, cleanup) is what these tests
    are about; actually shelling out to the vendor tool on a build host would
    test the network, not the code.
    """
    calls: list[str] = []

    async def fake_download(target, dest, on_line=None):
        calls.append(target)
        if fail:
            raise RuntimeError(fail)
        Path(dest).write_bytes(payload)

    monkeypatch.setattr(manager_mod, "download_dfss_file", fake_download)
    return calls


def _canned_http(monkeypatch, manager_mod, payload: bytes):
    calls: list[str] = []

    async def fake_http(self, url, dest, expected, progress):
        calls.append(url)
        Path(dest).write_bytes(payload)

    monkeypatch.setattr(manager_mod.AgentManager, "_download_http", fake_http)
    return calls


async def test_dfss_url_is_fetched_through_dfss(dfss_svc, monkeypatch):
    data = dfss_svc.payload
    dfss = _canned_dfss(monkeypatch, manager_mod, data)
    http = _canned_http(monkeypatch, manager_mod, data)

    await dfss_svc.mgr.install("fake")
    job = await wait_job(dfss_svc)
    assert job["state"] == "done", job["message"]
    # The dfss entry was used, with the scheme stripped for the vendor tool.
    assert dfss == ["open@sophgo.com:/tools/cv84x6_llm_server/agents/fake-a.tar.gz"]
    assert http == []  # the fallback was never needed


async def test_http_url_falls_back_when_dfss_fails(dfss_svc, monkeypatch):
    data = dfss_svc.payload
    dfss = _canned_dfss(monkeypatch, manager_mod, data, fail="连不上 dfss")
    http = _canned_http(monkeypatch, manager_mod, data)

    await dfss_svc.mgr.install("fake")
    job = await wait_job(dfss_svc)
    assert job["state"] == "done", job["message"]
    assert len(dfss) == 1 and http == [HTTP_B]


async def test_offline_never_touches_the_upstream_source(dfss_svc, monkeypatch):
    monkeypatch.setenv("CV84X6_AGENT_OFFLINE", "1")
    data = dfss_svc.payload
    dfss = _canned_dfss(monkeypatch, manager_mod, data)
    http = _canned_http(monkeypatch, manager_mod, data)

    await dfss_svc.mgr.install("fake")
    job = await wait_job(dfss_svc)
    assert job["state"] == "done", job["message"]
    assert len(dfss) == 1
    assert http == []  # offline means offline, even as a fallback


async def test_offline_and_dfss_down_reports_both_failures(tmp_path, monkeypatch):
    """A failure has to name every source it tried, or the operator is blind."""
    tarball = build_tarball(
        tmp_path / "fake.tar.gz", {"fake/bin/fake-agent": textwrap.dedent(FAKE_AGENT)},
    )
    svc = Svc(tmp_path, tarball)
    svc.spec.artifacts[host_arch()] = Artifact(
        urls=(DFSS_A, HTTP_B), sha256=sha256_of(tarball),
    )
    _canned_dfss(monkeypatch, manager_mod, b"", fail="dfss 超时")
    monkeypatch.setattr(
        manager_mod.AgentManager, "_download_http", _raising_http("HTTP 503"),
    )

    await svc.mgr.install("fake")
    job = await wait_job(svc)
    assert job["state"] == "error"
    assert DFSS_A in job["message"] and "dfss 超时" in job["message"]
    assert HTTP_B in job["message"] and "HTTP 503" in job["message"]


def _raising_http(message: str):
    async def fake(self, url, dest, expected, progress):
        raise RuntimeError(message)
    return fake


async def test_artifact_directory_is_used_before_any_network(dfss_svc, tmp_path, monkeypatch):
    """CV84X6_AGENT_ARTIFACT_DIR is how an install is proven before dfss has it."""
    # Named as the artifact's own file name: that is what the override looks for.
    source = tmp_path / "fake-a.tar.gz"
    source.write_bytes(dfss_svc.payload)
    monkeypatch.setenv("CV84X6_AGENT_ARTIFACT_DIR", str(tmp_path))
    dfss = _canned_dfss(monkeypatch, manager_mod, b"")
    http = _canned_http(monkeypatch, manager_mod, b"")

    await dfss_svc.mgr.install("fake")
    job = await wait_job(dfss_svc)
    assert job["state"] == "done", job["message"]
    assert dfss == [] and http == []  # nothing left the box


async def test_downloads_are_empty_after_a_successful_install(svc):
    await install(svc)
    leftovers = [p.name for p in (svc.mgr.downloads).iterdir()]
    assert leftovers == []


async def test_downloads_are_empty_after_a_failed_install(tmp_path):
    tarball = build_tarball(
        tmp_path / "fake.tar.gz", {"fake/bin/fake-agent": textwrap.dedent(FAKE_AGENT)},
    )
    svc = Svc(tmp_path, tarball)
    svc.spec.artifacts[host_arch()] = Artifact(
        urls=(f"file://{tarball}",), sha256="0" * 64,
    )
    await svc.mgr.install("fake")
    job = await wait_job(svc)
    assert job["state"] == "error"
    # Neither the rejected payload nor a .part may survive the job.
    assert [p.name for p in svc.mgr.downloads.iterdir()] == []


# -- artifact sources ------------------------------------------------------
def test_artifact_filename_works_for_every_scheme():
    from app.agents.spec import url_filename

    assert url_filename(DFSS_A) == "fake-a.tar.gz"
    assert url_filename(HTTP_B) == "fake-b.tar.gz"
    assert url_filename("https://h/x/y.tar.gz?token=1") == "y.tar.gz"
    assert url_filename("/local/dir/z.tar.xz") == "z.tar.xz"


def test_artifact_sources_put_dfss_first_and_honour_offline(monkeypatch):
    art = Artifact(urls=(DFSS_A, HTTP_B), sha256="0" * 64)
    monkeypatch.delenv("CV84X6_AGENT_OFFLINE", raising=False)
    monkeypatch.delenv("CV84X6_AGENT_ARTIFACT_DIR", raising=False)
    assert art.sources() == (DFSS_A, HTTP_B)

    monkeypatch.setenv("CV84X6_AGENT_OFFLINE", "1")
    assert art.sources() == (DFSS_A,)


def test_artifact_directory_is_prepended_only_when_the_file_exists(tmp_path, monkeypatch):
    art = Artifact(urls=(DFSS_A, HTTP_B), sha256="0" * 64)
    monkeypatch.setenv("CV84X6_AGENT_ARTIFACT_DIR", str(tmp_path))
    # The dfss name is the one asked for; nothing is offered while it is absent.
    assert art.sources() == (DFSS_A, HTTP_B)
    (tmp_path / "fake-a.tar.gz").write_bytes(b"x")
    assert art.sources()[0] == str(tmp_path / "fake-a.tar.gz")


def test_opencode_and_openclaw_prefer_the_dfss_mirror(monkeypatch):
    """Every agent artifact has to be installable with no route to the internet."""
    from app.agents import openclaw as openclaw_mod

    monkeypatch.setenv("CV84X6_AGENT_OFFLINE", "1")
    for spec in (OPENCODE_SPEC, openclaw_mod.SPEC):
        for arch, art in spec.artifacts.items():
            assert art.urls[0].startswith("dfss://"), (spec.id, arch)
            assert art.sources(), (spec.id, arch)  # still resolvable offline


# -- config ----------------------------------------------------------------
OPENCODE_EXPECTED = {
    "$schema": "https://opencode.ai/config.json",
    "autoupdate": False,
    "share": "disabled",
    "model": "cv84x6/test-32k",
    "small_model": "cv84x6/test-32k",
    "provider": {
        "cv84x6": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "CV84X6 本地推理",
            "options": {
                "baseURL": "http://127.0.0.1:18080/v1",
                "apiKey": "sk-test-key",
                "timeout": 1800000,
            },
            "models": {
                "test-32k": {
                    "name": "test-32k",
                    "reasoning": True,
                    "tool_call": True,
                    "attachment": True,
                    "interleaved": {"field": "reasoning_content"},
                    "limit": {"context": 32768, "output": 16384},
                    "options": {"enable_thinking": False},
                    "variants": {
                        "think": {"enable_thinking": True},
                        "nothink": {"enable_thinking": False},
                    },
                },
                "test-128k": {
                    "name": "test-128k",
                    "reasoning": True,
                    "tool_call": True,
                    "attachment": False,
                    "interleaved": {"field": "reasoning_content"},
                    "limit": {"context": 131072, "output": 16384},
                    "options": {"enable_thinking": False},
                    "variants": {
                        "think": {"enable_thinking": True},
                        "nothink": {"enable_thinking": False},
                    },
                },
            },
        },
    },
    # The MCP server every install is preconfigured against. ``remote`` is
    # opencode's own word for an HTTP MCP server; the transport is inferred from
    # the URL, and the key rides in the header exactly as it does for /v1.
    "mcp": {
        "cv84x6": {
            "type": "remote",
            "url": "http://127.0.0.1:18080/mcp",
            "headers": {"Authorization": "Bearer sk-test-key"},
            "enabled": True,
        },
    },
}


def test_opencode_write_config_matches_the_contract_item_by_item(tmp_path):
    ctx = InstallContext(
        service_port=18080,
        api_key="sk-test-key",
        models=[
            ModelChoice(id="test-32k", context=32768, vision=True),
            ModelChoice(id="test-128k", context=131072, vision=False),
        ],
        default_model="test-32k",
        thinking=False,
    )
    spec = OpencodeSpec()
    spec.write_config(tmp_path, ctx)
    path = spec.config_path(tmp_path)
    assert path == tmp_path / "config" / "opencode" / "opencode.json"
    assert json.loads(path.read_text()) == OPENCODE_EXPECTED
    # The plaintext key is in the file, so the file is not readable by others.
    assert path.stat().st_mode & 0o777 == 0o600


def test_opencode_output_limit_is_capped_at_16384_and_half_the_context(tmp_path):
    ctx = InstallContext(
        service_port=18080, api_key="k",
        models=[
            ModelChoice(id="small", context=4096),     # 4096 // 2 = 2048
            ModelChoice(id="mid", context=60000),      # 30000 -> capped 16384
            ModelChoice(id="huge", context=131072),    # capped 16384
        ],
        default_model="small",
    )
    cfg = OpencodeSpec().build_config(ctx)
    limits = {k: v["limit"] for k, v in cfg["provider"][PROVIDER]["models"].items()}
    assert limits == {
        "small": {"context": 4096, "output": 2048},
        "mid": {"context": 60000, "output": 16384},
        "huge": {"context": 131072, "output": 16384},
    }


def test_opencode_existing_key_reads_back_from_its_own_config(tmp_path):
    spec = OpencodeSpec()
    ctx = InstallContext(service_port=18080, api_key="sk-abc",
                         models=[ModelChoice(id="m", context=32768)], default_model="m")
    spec.write_config(tmp_path, ctx)
    assert spec.existing_key(tmp_path) == "sk-abc"
    assert spec.existing_key(tmp_path / "nowhere") == ""


def test_opencode_web_url_is_a_path_on_the_console_not_its_own_port():
    """The bug this replaces: a link to ``http://<host>:14096``.

    On a customer site only the console's port is forwarded, so an agent-port
    URL is unreachable from the browser -- the iframe stayed blank and "打开"
    dead-ended. A relative path resolves against whatever host the browser is
    already using, and the proxy supplies the agent's own login upstream.
    """
    url = OpencodeSpec().web_url("10.0.0.5", 14096, "s3cr3t")
    assert url == "/agents/opencode/"
    assert "14096" not in url
    assert "auth_token" not in url


def test_opencode_is_proxied_and_needs_its_prefix_rewritten():
    """Both flags are measured facts, not preferences.

    ``proxied`` because the agent's port is unreachable across subnets;
    ``prefix_root`` because its UI hard-codes ``/assets/...`` and derives routes
    and its API base from ``location``.
    """
    assert OpencodeSpec().proxied is True
    assert OpencodeSpec().prefix_root is True
    # And the proxy has credentials to present upstream: without them every
    # asset request from an otherwise-logged-in page is a 401.
    assert OpencodeSpec().upstream_basic_auth("s3cr3t") == ("opencode", "s3cr3t")
    assert OpencodeSpec().upstream_basic_auth("") is None


def test_opencode_env_keeps_everything_inside_the_agent_tree(tmp_path):
    d = tmp_path / "agent"
    env = OpencodeSpec().env(d, "pw")
    assert env["HOME"] == str(d / "home")
    assert env["XDG_CONFIG_HOME"] == str(d / "config")
    assert env["XDG_DATA_HOME"] == str(d / "data")
    assert env["XDG_CACHE_HOME"] == str(d / "cache")
    assert env["XDG_STATE_HOME"] == str(d / "state")
    assert env["TMPDIR"] == str(d / "tmp")
    assert env["OPENCODE_CONFIG"] == str(d / "config" / "opencode" / "opencode.json")
    assert env["OPENCODE_SERVER_PASSWORD"] == "pw"
    assert env["OPENCODE_SERVER_USERNAME"] == "opencode"
    assert env["OPENCODE_DISABLE_AUTOUPDATE"] == "1"
    assert env["OPENCODE_DISABLE_MODELS_FETCH"] == "1"
    assert json.loads(env["OPENCODE_PERMISSION"]) == {"edit": "allow", "bash": "allow"}


# -- start / stop ----------------------------------------------------------
async def test_start_sets_home_and_xdg_to_the_agent_directory(svc):
    await install(svc)
    status = await svc.mgr.start("fake")
    assert status["running"] is True
    assert status["status"] == "running"
    assert status["health"] is True
    port = status["port"]
    env = http_get(port, "/env")
    for name, sub in (
        ("HOME", "home"), ("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state"), ("TMPDIR", "tmp"),
    ):
        assert env[name] == str(svc.directory / sub), name
    # And the working directory is the agent's own workspace.
    cwd = http_get(port, "/cwd")
    assert cwd["cwd"] == str(svc.directory / "workspace")
    # RSS is read from /proc, so a live process reports a positive figure.
    assert svc.mgr.status_one("fake")["rss_bytes"] > 0
    await svc.mgr.stop("fake")


async def test_rss_covers_the_whole_process_tree(svc):
    """An agent is a tree, and the launcher is the small part of it.

    Measured on the board: OpenClaw's launcher reports ~59 MB while its gateway
    child holds ~1.05 GB. Counting only the pid the manager spawned showed a
    board that was full as nearly empty, so the number has to include children.
    """
    import subprocess
    import sys
    import time

    from app.agents.manager import _rss_bytes

    # A child that allocates and holds it, under a parent that stays small.
    script = (
        "import subprocess,sys,time\n"
        "child = subprocess.Popen([sys.executable,'-c',"
        "'x=bytearray(48*1024*1024); x[::4096]=b\"1\"*(len(x)//4096);"
        "import time; time.sleep(30)'])\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(30)\n"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        child_pid = int(parent.stdout.readline().strip())
        time.sleep(1.5)  # let the bytearray be touched in
        total = _rss_bytes(parent.pid)
        only_parent = 0
        for line in Path(f"/proc/{parent.pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                only_parent = int(line.split()[1]) * 1024
        assert only_parent > 0
        # The child holds ~48 MB; the tree must be at least that much larger.
        assert total >= only_parent + 32 * 1024 * 1024, (total, only_parent)
        assert child_pid  # the child really existed
    finally:
        parent.kill()
        parent.wait(timeout=10)


async def test_stop_kills_the_whole_process_group(svc):
    """A surviving child would hold the port and the log file open."""
    await install(svc)
    status = await svc.mgr.start("fake")
    port = status["port"]
    pid = status["pid"]
    pgid = http_get(port, "/cwd")["pgid"]
    assert pgid == pid  # start_new_session: the agent leads its own group

    await svc.mgr.stop("fake")
    assert svc.mgr.status_one("fake")["running"] is False
    with pytest.raises(OSError):
        os.killpg(pgid, 0)  # the group is gone, not merely the leader
    with pytest.raises(Exception):
        http_get(port)  # and the port is free again


async def test_stop_is_idempotent_when_already_stopped(svc):
    await install(svc)
    await svc.mgr.start("fake")
    await svc.mgr.stop("fake")
    status = await svc.mgr.stop("fake")
    assert status["status"] == "stopped"


async def test_agent_log_captures_the_child_output(svc):
    await install(svc)
    await svc.mgr.start("fake")
    await svc.mgr.stop("fake")
    log = svc.mgr.logs("fake", tail=50)
    assert isinstance(log, str)
    assert (svc.directory / "logs" / "agent.log").exists()


async def test_log_rotates_past_ten_megabytes(svc, monkeypatch):
    """The board has 450 MB of /data; a runaway agent must not fill it."""
    await install(svc)
    log = svc.directory / "logs" / "agent.log"
    log.write_bytes(b"x" * (manager_mod.LOG_ROTATE_BYTES + 1))
    await svc.mgr.start("fake")
    assert (svc.directory / "logs" / "agent.log.1").exists()
    assert log.stat().st_size < manager_mod.LOG_ROTATE_BYTES
    await svc.mgr.stop("fake")


async def test_crashed_agent_is_restarted(svc):
    await install(svc)
    status = await svc.mgr.start("fake")
    port = status["port"]
    first_pid = status["pid"]

    # Ask the child to die: the supervisor should bring it back with a new pid.
    # The reply is flushed before os._exit, so this GET may succeed; what
    # matters is that the process is gone a moment later.
    try:
        http_get(port, "/crash-me")
    except Exception:
        pass

    # The restart is deliberately not immediate (2 s for the first crash), and
    # the status says so while it waits.
    saw_backoff = False
    deadline = asyncio.get_running_loop().time() + 20
    while asyncio.get_running_loop().time() < deadline:
        state = svc.mgr.status_one("fake")
        if state["pid"] not in (None, first_pid) and state["running"]:
            break
        if "秒后重启" in (state["last_error"] or ""):
            saw_backoff = True
        await asyncio.sleep(0.1)
    else:
        raise AssertionError("agent was not restarted after a crash")
    assert saw_backoff, "the console never showed the agent waiting to restart"

    # The marker proves a lifetime really ended, not just that the pid changed.
    assert (svc.directory / "logs" / "crashed").read_text() == "x"

    # And the replacement serves requests: the supervisor waited for it to bind.
    for _ in range(100):
        try:
            assert http_get(state["port"])["ok"] is True
            break
        except OSError:
            await asyncio.sleep(0.1)
    else:
        raise AssertionError("the restarted agent never answered")
    await svc.mgr.stop("fake")


async def test_too_many_crashes_stop_the_restarts(svc, monkeypatch):
    """A flapping agent is marked failed rather than left spinning.

    The fake agent is told to become healthy and then die, which is the shape of
    the real failure (opencode binds its port, then trips over bad state): the
    supervisor must stop restarting it and say why.
    """
    await install(svc)
    monkeypatch.setattr(manager_mod, "MAX_CRASHES", 1)
    monkeypatch.setenv("FAKE_DIE_AFTER", "0.4")
    # The first start succeeds -- the process does become healthy -- and the
    # failure only shows up after it has crashed and been restarted.
    status = await svc.mgr.start("fake")
    assert status["running"] is True
    for _ in range(300):
        await asyncio.sleep(0.1)
        state = svc.mgr.status_one("fake")
        if state["status"] == "failed":
            break
    else:
        raise AssertionError(f"a crash loop was never marked failed: {state}")
    assert state["running"] is False
    assert "崩溃" in state["last_error"]


# -- guards ----------------------------------------------------------------
async def test_port_conflict_returns_a_conflict(svc):
    """Both the settings change and the start are refused, with the same reason."""
    await install(svc)
    wanted = free_port()
    blocker = socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("0.0.0.0", wanted))
    blocker.listen(1)
    try:
        # (a) The settings change: refused before anything is touched.
        with pytest.raises(PortBusy, match=str(wanted)):
            await svc.mgr.patch("fake", {"port": wanted})
        assert svc.mgr.state("fake").port != wanted

        # (b) The start: the port was free when it was configured and is not
        # any more, which is what happens when another program grabs it.
        free = free_port()
        await svc.mgr.patch("fake", {"port": free})
        blocker2 = socket.socket()
        blocker2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker2.bind(("0.0.0.0", free))
        blocker2.listen(1)
        try:
            with pytest.raises(PortBusy, match=str(free)):
                await svc.mgr.start("fake")
        finally:
            blocker2.close()
    finally:
        blocker.close()
    assert svc.mgr.status_one("fake")["running"] is False


async def test_low_memory_refuses_the_start(svc, monkeypatch):
    await install(svc)
    monkeypatch.setattr(
        manager_mod.monitor, "memory",
        lambda: {"total_bytes": 2 << 30, "available_bytes": 100 << 20, "used_bytes": 1 << 30},
    )
    with pytest.raises(MemoryLow, match="可用内存"):
        await svc.mgr.start("fake")
    assert svc.mgr.status_one("fake")["running"] is False


async def test_start_before_install_is_a_400(svc):
    with pytest.raises(AgentError, match="尚未安装"):
        await svc.mgr.start("fake")


# -- reset / uninstall -----------------------------------------------------
async def test_reset_rotates_the_key_and_keeps_the_payload(svc):
    await install(svc)
    before = json.loads(svc.mgr.state_path.read_text())["fake"]
    await svc.mgr.reset("fake")
    after = json.loads(svc.mgr.state_path.read_text())["fake"]
    assert after["key_id"] != before["key_id"]
    assert after["secret"] != before["secret"]
    # The old key is revoked in the store the key console reads.
    revoked = {k.id: k.revoked for k in svc.store.keys}
    assert revoked[before["key_id"]] is True
    assert revoked[after["key_id"]] is False
    # bin/ survives (78 MB is not something to re-download on a whim)...
    assert svc.mgr.installed("fake")
    # ...while everything the agent derived from it does not.
    assert not (svc.directory / "data").exists() or not any((svc.directory / "data").iterdir())


async def test_runtime_state_is_cleared_but_the_workspace_survives(svc):
    await install(svc)
    (svc.directory / "workspace" / "hello.py").write_text("print('hi')\n")
    (svc.directory / "data" / "session.db").write_text("x")
    (svc.directory / "cache" / "blob").write_text("x")
    await svc.mgr.reset("fake")
    assert (svc.directory / "workspace" / "hello.py").exists()
    assert not (svc.directory / "data" / "session.db").exists()
    assert not (svc.directory / "cache" / "blob").exists()


async def test_uninstall_removes_the_directory_and_revokes_the_key(svc):
    await install(svc)
    key_id = json.loads(svc.mgr.state_path.read_text())["fake"]["key_id"]
    await svc.mgr.uninstall("fake")
    assert not svc.directory.exists()
    assert all(k.revoked for k in svc.store.keys if k.id == key_id)
    assert svc.mgr.status_one("fake")["status"] == "not_installed"


async def test_uninstall_clears_a_declared_scratch_path(svc, tmp_path):
    """An agent that writes outside its tree must not leave that behind.

    OpenClaw's gateway created /tmp/openclaw on the board. The path is declared
    by the spec rather than guessed, so this also pins that only declared,
    absolute paths are touched.
    """
    scratch = tmp_path / "outside-the-agent"
    scratch.mkdir()
    (scratch / "leftover").write_text("x")
    svc.mgr.specs["fake"].scratch_paths = (str(scratch), "/proc/this-would-be-terrible")
    await install(svc)
    await svc.mgr.uninstall("fake")
    assert not scratch.exists()
    # A path the spec did not declare is untouched.
    assert Path("/proc").is_dir()


async def test_sync_does_not_rotate_a_key_it_cannot_persist(svc):
    """An agent with no config file must keep the key install issued.

    This agent has key_in_config=False, so there is nothing to read the
    plaintext back from; rotating on every sync would silently revoke a key the
    operator may have copied down.
    """
    await install(svc)
    before = json.loads(svc.mgr.state_path.read_text())["fake"]["key_id"]
    svc.mgr.sync_config("fake")
    svc.mgr.sync_config("fake")
    after = json.loads(svc.mgr.state_path.read_text())["fake"]["key_id"]
    assert after == before
    assert all(not k.revoked for k in svc.store.keys if k.id == before)


async def test_uninstall_stops_a_running_agent_first(svc):
    await install(svc)
    status = await svc.mgr.start("fake")
    port = status["port"]
    await svc.mgr.uninstall("fake")
    with pytest.raises(Exception):
        http_get(port)


# -- state file ------------------------------------------------------------
async def test_state_survives_a_restart_of_the_service(svc):
    from app.core.models import ModelInfo

    await install(svc)
    svc.models._models = {
        "m1": ModelInfo(model_id="m1", path="", display_name="", context_length=32768),
    }
    await svc.mgr.patch("fake", {"autostart": True, "default_model": "m1", "thinking": True})
    mgr2 = AgentManager(
        svc.mgr.data_root, key_store=svc.store, models=svc.models,
        specs=[svc.spec], service_port=18080,
    )
    st = mgr2.state("fake")
    assert st.autostart is True
    assert st.default_model == "m1"
    assert st.thinking is True
    assert mgr2.installed("fake")


async def test_a_corrupt_state_file_does_not_brick_the_console(svc):
    svc.mgr.state_path.write_text("{not json")
    mgr2 = AgentManager(
        svc.mgr.data_root, key_store=svc.store, models=svc.models,
        specs=[svc.spec], service_port=18080,
    )
    assert mgr2.status_one("fake")["status"] == "not_installed"


# -- model list ------------------------------------------------------------
def test_model_context_comes_from_the_loaded_model_then_the_catalogue(tmp_path, monkeypatch):
    """Context decides the agent's window, so a wrong number is a real bug."""
    from app.core.models import ModelInfo

    svc = Svc(tmp_path, build_tarball(tmp_path / "x.tar.gz", {"x": b""}))
    svc.models._models = {
        "loaded-with-health": ModelInfo(
            model_id="loaded-with-health", path="", display_name="", loaded=True,
            context_length=8192, supports_vision=True,
        ),
        "qwen3.6-35b-a3b-32k": ModelInfo(
            model_id="qwen3.6-35b-a3b-32k", path="", display_name="",
            context_length=None, supports_vision=True,
        ),
        "unknown-model": ModelInfo(
            model_id="unknown-model", path="", display_name="", context_length=None,
        ),
    }
    choices = {c.id: c for c in svc.mgr.model_choices()}
    assert choices["loaded-with-health"].context == 8192
    # Not loaded: the catalogue knows this one, and its 32768 is the truth.
    assert choices["qwen3.6-35b-a3b-32k"].context == 32768
    # Nothing knows: the fallback, not zero (a zero context is a broken config).
    assert choices["unknown-model"].context == manager_mod.FALLBACK_CONTEXT
    assert choices["loaded-with-health"].vision is True


# -- HTTP ------------------------------------------------------------------
@pytest.fixture()
def client(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    tarball = build_tarball(
        tmp_path / "fake.tar.gz", {"fake/bin/fake-agent": textwrap.dedent(FAKE_AGENT)},
    )
    art = Artifact(urls=(f"file://{tarball}",), sha256=sha256_of(tarball))
    spec = FakeSpec(artifacts={"x64": art, "arm64": art})
    app = create_app(
        data_dir=tmp_path / "state", models_dir=models, backend_kind="mock",
        web_dir=tmp_path / "web", data_root=tmp_path / "root",
        agent_specs=[spec], service_port=18080,
    )
    with TestClient(app) as c:
        yield c


def login(c) -> None:
    assert c.post("/api/login", json={"password": "admin"}).status_code == 200


def test_agent_routes_require_login(client):
    for path in ("/api/agents", "/api/agents/fake", "/api/agents/fake/logs"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/agents/fake/install").status_code == 401
    assert client.patch("/api/agents/fake", json={"port": 15000}).status_code == 401


def test_http_install_start_and_status(client):
    login(client)
    r = client.get("/api/agents")
    assert r.status_code == 200
    agents = r.json()["agents"]
    assert [a["id"] for a in agents] == ["fake"]
    assert agents[0]["status"] == "not_installed"
    assert agents[0]["latest_version"] == "1.0.0"

    r = client.post("/api/agents/fake/install")
    assert r.status_code == 202, r.text
    job = client.get("/api/agents/fake/job").json()["job"]
    assert job["agent_id"] == "fake"

    for _ in range(100):
        job = client.get("/api/agents/fake/job").json()["job"]
        if job["state"] in ("done", "error"):
            break
        import time
        time.sleep(0.05)
    assert job["state"] == "done", job

    r = client.post("/api/agents/fake/start")
    assert r.status_code == 200, r.text
    assert r.json()["running"] is True
    # The web link is built from the host the browser used, so it is reachable
    # from another machine rather than pointing at the board's loopback.
    assert r.json()["web_url"].startswith("http://testserver:")

    r = client.post("/api/agents/fake/stop")
    assert r.status_code == 200
    assert r.json()["running"] is False


def test_http_port_conflict_is_a_409(client):
    login(client)
    client.post("/api/agents/fake/install")
    blocker = socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("0.0.0.0", 0))
    blocker.listen(1)
    try:
        r = client.patch("/api/agents/fake", json={"port": blocker.getsockname()[1]})
        assert r.status_code == 409, r.text
        assert "占用" in r.json()["detail"]
    finally:
        blocker.close()


def test_http_unknown_agent_is_a_400(client):
    login(client)
    assert client.get("/api/agents/nope").status_code == 400
    assert client.post("/api/agents/nope/start").status_code == 400


def test_http_patch_validates_the_model(client):
    login(client)
    r = client.patch("/api/agents/fake", json={"default_model": "no-such-model"})
    assert r.status_code == 400
    assert "不存在" in r.json()["detail"]


def test_http_logs_endpoint(client):
    login(client)
    assert client.get("/api/agents/fake/logs?tail=20").json() == {"log": ""}


def test_agent_manager_is_shut_down_with_the_service(tmp_path):
    """A surviving agent process outlives the service and holds its port."""
    models = tmp_path / "models"
    models.mkdir()
    tarball = build_tarball(
        tmp_path / "fake.tar.gz", {"fake/bin/fake-agent": textwrap.dedent(FAKE_AGENT)},
    )
    art = Artifact(urls=(f"file://{tarball}",), sha256=sha256_of(tarball))
    spec = FakeSpec(artifacts={"x64": art, "arm64": art})
    app = create_app(
        data_dir=tmp_path / "state", models_dir=models, backend_kind="mock",
        web_dir=tmp_path / "web", data_root=tmp_path / "root",
        agent_specs=[spec], service_port=18080,
    )
    with TestClient(app) as c:
        login(c)
        c.post("/api/agents/fake/install")
        import time
        for _ in range(100):
            job = c.get("/api/agents/fake/job").json()["job"]
            if job["state"] in ("done", "error"):
                break
            time.sleep(0.05)
        r = c.post("/api/agents/fake/start")
        assert r.status_code == 200, r.text
        pid = r.json()["pid"]
    # Leaving the with-block ran the lifespan shutdown.
    assert not Path(f"/proc/{pid}").exists()


# -- the card copy ---------------------------------------------------------
#
# Every agent's card answers exactly one question: what does running this cost?
# It used to also state a fixed board capacity, a package size and a
# co-existence verdict ("cannot run beside opencode; the kernel will OOM it").
# That was wrong on the operator's own screen: the board's real size differs
# between boards, and whether an agent fits is already answered at start time by
# `_check_memory` against the live MemAvailable. A card that asserts a capacity
# goes stale silently; one that reports a cost stays true.

CARD_AGENT_SPECS = ("picoclaw", "opencode", "openclaw")


def _card_notes() -> dict[str, str]:
    from app.agents import openclaw, opencode, picoclaw
    return {
        "picoclaw": picoclaw.SPEC.card_note,
        "opencode": opencode.SPEC.card_note,
        "openclaw": openclaw.SPEC.card_note,
    }


def test_agent_card_copy_is_a_memory_estimate_and_nothing_else():
    """One rule, three agents: state the cost, never a hardware capacity."""
    for agent_id, note in _card_notes().items():
        assert note, f"{agent_id} has no card copy"
        assert note.startswith("预估内存："), (agent_id, note)
        assert note.endswith("。"), (agent_id, note)
        # A capacity claim is the defect this rule exists to prevent.
        for claim in ("2.6", "板卡只有", "板卡共", "不能与", "OOM", "只能"):
            assert claim not in note, f"{agent_id} card still claims {claim!r}: {note}"
        # And the package/download size is not a running-memory figure.
        assert "下载" not in note, (agent_id, note)
        assert "安装包" not in note, (agent_id, note)


def test_agent_card_copy_is_consistent_in_shape():
    """Three cards, one style: `空闲约 X，...约 Y`, MB or GB, no mixed units."""
    import re
    for agent_id, note in _card_notes().items():
        assert "空闲约" in note, (agent_id, note)
        figures = re.findall(r"约 ([0-9.]+) (MB|GB)", note)
        assert len(figures) >= 2, f"{agent_id} states no idle/busy pair: {note}"
        units = {u for _, u in figures}
        assert len(units) == 1, f"{agent_id} mixes MB and GB: {note}"


def test_agent_card_copy_does_not_promise_coexistence():
    """Fitting beside a model is the memory check's call, not the card's.

    `_check_memory` reads the live MemAvailable; a card saying "can run beside a
    35B model" would be a second, unverified source of truth -- and it becomes
    false on a board with less RAM than the one it was written on.
    """
    for agent_id, note in _card_notes().items():
        for promise in ("可与", "可以同时", "能和"):
            assert promise not in note, f"{agent_id} card promises coexistence: {note}"


def test_memory_check_keeps_the_per_agent_floor():
    """The copy changed; the behaviour must not.

    Stripping the capacity wording from the cards is a documentation change. The
    refusal itself still compares each agent's own floor against MemAvailable --
    OpenClaw's is highest, PicoClaw declares its own, and opencode falls back to
    the framework default the way it always has.
    """
    from app.agents import openclaw, opencode, picoclaw
    assert picoclaw.SPEC.memory_floor_bytes > 0
    assert openclaw.SPEC.memory_floor_bytes == 1600 * 1024 * 1024
    # No declaration means "use the manager's default", which is also positive.
    assert opencode.SPEC.memory_floor_bytes == 0
    assert manager_mod.MEMORY_FLOOR_BYTES > 0
    # A floor is a cost, not a capacity: no floor may be set to the size of a
    # board, which is what made the old wording hard to correct.
    for floor in (picoclaw.SPEC.memory_floor_bytes,
                  openclaw.SPEC.memory_floor_bytes,
                  manager_mod.MEMORY_FLOOR_BYTES):
        assert floor < 2 * 1024 ** 3


def test_opencode_listens_on_loopback_only():
    """The console reaches opencode through its same-origin proxy, so the agent
    -- which may edit files and run shell commands -- must not listen on the LAN
    (it bound 0.0.0.0 behind basic auth until the v0.6.29 E2E run, MYS-2682)."""
    from pathlib import Path

    from app.agents import opencode as opencode_mod

    cmd = opencode_mod.SPEC.command(Path("/agent"), 14096)
    assert cmd[cmd.index("--hostname") + 1] == "127.0.0.1"
    assert "0.0.0.0" not in cmd
