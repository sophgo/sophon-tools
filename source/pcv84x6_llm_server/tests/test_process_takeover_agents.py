"""Agent processes that outlive a restart of the service (MYS-2392).

Same shape as ``test_process_takeover_models.py``: real processes, started with
the argv and cwd ``AgentManager._spawn`` uses, abandoned, then found by a fresh
manager. What is specific to agents is that the *supervisor* is what would
duplicate them: an agent marked ``autostart`` is started on every boot, so a
restart without takeover means two gateways on one port (the second one fails,
loudly, and the console reports the wrong process).

The rejection half matters more here than for models: an agent's own port and
directory are the only thing separating it from an unrelated program, and a
wrong ``stop`` signals a whole process group.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from app.core import procs
from app.core.models import ModelManager
from app.core.state import StateStore
from app.agents.manager import AgentBusy, AgentManager
from app.agents.spec import AgentSpec
from tests.test_process_takeover_models import FAKE_AGENT, free_port, wait_for

BASE = Path(__file__).resolve().parent.parent


class FakeSpec(AgentSpec):
    """The smallest real agent: one script, one port, GET /health."""

    id = "fake"
    name = "假 agent"
    version = "1.0.0"
    default_port = 14196
    embeddable = True
    start_timeout = 30.0
    executable = "fake-agent"
    payload_root = "bin"
    key_in_config = False

    def command(self, directory: Path, port: int) -> list[str]:
        return [sys.executable, str(Path(directory) / "bin" / "fake-agent"),
                "--port", str(port)]


def build_manager(tmp_path: Path, *, port: int | None = None) -> AgentManager:
    root = tmp_path / "root"
    (root / "agents").mkdir(parents=True, exist_ok=True)
    store = StateStore(root / "state" / "state.json")
    models_dir = tmp_path / "models"
    models_dir.mkdir(exist_ok=True)
    models = ModelManager(models_dir, backend_kind="mock", log_dir=tmp_path / "logs")
    models.refresh()
    mgr = AgentManager(root, key_store=store, models=models,
                       specs=[FakeSpec(artifacts={})], service_port=18080)
    return mgr


def install_payload(mgr: AgentManager, port: int) -> Path:
    """Put the executable where ``installed()`` looks and record the port.

    This is the state an install leaves behind, which is also the only state in
    which a surviving process can be attributed to an agent: without the payload
    the agent reads as "not installed" and nothing is adopted.
    """
    directory = mgr.directory("fake")
    (directory / "bin").mkdir(parents=True, exist_ok=True)
    exe = directory / "bin" / "fake-agent"
    exe.write_text(FAKE_AGENT)
    exe.chmod(0o755)
    (directory / "workspace").mkdir(exist_ok=True)
    (directory / "logs").mkdir(exist_ok=True)
    st = mgr.state("fake")
    st.port = port
    st.secret = "s3cr3t"
    mgr.save_state()
    return exe


def spawn_agent(mgr: AgentManager, exe: Path, port: int, *, cwd: Path | None = None,
                argv_extra: list[str] | None = None,
                executable: str | None = None) -> subprocess.Popen:
    directory = mgr.directory("fake")
    argv = [executable or sys.executable, str(exe), *(argv_extra or []), "--port", str(port)]
    return subprocess.Popen(
        argv, cwd=str(cwd or (directory / "workspace")),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def healthy(port: int, timeout: float = 20.0) -> bool:
    def check() -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                return json.loads(r.read()).get("ok") is True
        except OSError:
            return False
    return wait_for(check, timeout)


@pytest.fixture()
def agents(tmp_path):
    """Every process a test starts is reaped here, adopted or not."""
    started: list[subprocess.Popen] = []

    def track(proc: subprocess.Popen) -> subprocess.Popen:
        started.append(proc)
        return proc

    yield track
    for proc in started:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), 9)
            except OSError:
                proc.kill()
            proc.wait(timeout=10)


# -- takeover --------------------------------------------------------------
async def test_a_surviving_agent_is_taken_over_and_reports_running(tmp_path, agents):
    """The reported bug: after a restart the agent read as stopped.

    The process is started the way ``_spawn`` starts it -- own session, cwd in
    the agent's workspace -- and then the manager is built fresh, which is all a
    restart really is.
    """
    port = free_port()
    mgr = build_manager(tmp_path)
    exe = install_payload(mgr, port)
    survivor = agents(spawn_agent(mgr, exe, port))
    assert healthy(port), "the fake agent never came up"

    fresh = build_manager(tmp_path)
    status = {a["id"]: a for a in fresh.status()}["fake"]
    assert status["running"] is False  # nothing in memory, before recovery

    adopted = await fresh.adopt()
    assert [a["id"] for a in adopted] == ["fake"]
    status = fresh.status_one("fake")
    assert status["running"] is True
    assert status["status"] == "running"
    assert status["pid"] == survivor.pid
    assert status["health"] is True
    assert status["adopted"] is True

    # The adopted process is reachable through the console's view of an agent.
    assert status["web_url"]
    assert status["operation"] is None


async def test_an_adopted_agent_that_dies_stops_reading_as_running(tmp_path, agents):
    """Nothing reaps an adopted process, so its death is only visible to a look.

    An adopted agent has no supervisor task -- there is no child to ``await`` --
    so ``returncode`` never changes on its own. Without this correction the
    console keeps showing "running" with a dead pid, and neither autostart nor
    the crash counter ever learns the agent is gone.
    """
    port = free_port()
    mgr = build_manager(tmp_path)
    exe = install_payload(mgr, port)
    survivor = agents(spawn_agent(mgr, exe, port))
    assert healthy(port)

    fresh = build_manager(tmp_path)
    await fresh.adopt()
    assert fresh.status_one("fake")["running"] is True

    survivor.kill()
    survivor.wait(timeout=10)
    assert wait_for(lambda: not procs.process_alive(survivor.pid), timeout=10)

    status = fresh.status_one("fake")
    assert status["running"] is False
    assert status["status"] == "stopped"
    assert status["pid"] is None
    assert status["adopted"] is False
    assert "已退出" in status["last_error"]
    # And the record is corrected, not merely hidden: a start works again.
    assert fresh._runtime["fake"].proc is None


async def test_an_adopted_agent_can_still_be_stopped(tmp_path, agents):
    """Takeover is only worth anything if the process group can still be stopped."""
    port = free_port()
    mgr = build_manager(tmp_path)
    exe = install_payload(mgr, port)
    survivor = agents(spawn_agent(mgr, exe, port))
    assert healthy(port)

    fresh = build_manager(tmp_path)
    await fresh.adopt()
    assert fresh.status_one("fake")["running"] is True

    stopped = await fresh.stop("fake")
    assert stopped["running"] is False and stopped["pid"] is None
    assert wait_for(lambda: survivor.poll() is not None, timeout=15)
    with pytest.raises(OSError):
        os.killpg(survivor.pid, 0)  # the whole group went, not just the leader


async def test_autostart_does_not_start_a_second_copy(tmp_path, agents):
    """The duplication bug, at its source: a restart plus ``autostart: true``.

    Before takeover the manager saw nothing running and spawned a second agent
    on the same port. Now the agent is already up, so ``start`` is a no-op and
    no second process exists.
    """
    port = free_port()
    mgr = build_manager(tmp_path)
    exe = install_payload(mgr, port)
    mgr.state("fake").autostart = True
    mgr.save_state()
    survivor = agents(spawn_agent(mgr, exe, port))
    assert healthy(port)

    fresh = build_manager(tmp_path)
    await fresh.adopt()
    before = {p.pid for p in procs.scan_processes()
              if procs.same_path(p.exe, os.path.realpath(sys.executable))
              and str(exe) in p.argv}
    await fresh.autostart()
    after = {p.pid for p in procs.scan_processes()
             if procs.same_path(p.exe, os.path.realpath(sys.executable))
             and str(exe) in p.argv}
    assert after == before == {survivor.pid}, (before, after)
    assert fresh.status_one("fake")["running"] is True


# -- rejections ------------------------------------------------------------
async def test_an_agent_on_another_port_is_not_adopted(tmp_path, agents):
    """Two data roots (a second checkout, an old release) each own a port.

    The survivor here is a real agent of this spec, in this agent's directory --
    but on a port agents.json does not name, so it is not the process this run
    would have started, and taking it over would mean two consoles driving one
    directory.
    """
    mgr = build_manager(tmp_path)
    our_port = free_port()
    other_port = free_port()
    exe = install_payload(mgr, our_port)
    survivor = agents(spawn_agent(mgr, exe, other_port))
    assert healthy(other_port)

    fresh = build_manager(tmp_path)
    assert await fresh.adopt() == []
    status = fresh.status_one("fake")
    assert status["running"] is False and status["pid"] is None
    assert survivor.poll() is None, "a process on another port must not be touched"


async def test_a_process_run_by_another_binary_is_not_adopted(tmp_path, agents):
    """Everything matches except the file being executed.

    The candidate here is a *working* agent: the real payload, the right port,
    the right cwd, and an identical command line -- run by a copy of the
    interpreter rather than by the one ``spec.command`` names. That difference is
    the whole point: this run would never have started it, so it cannot claim to
    know what that process is. Removing this check means "open the agent's
    directory and run its payload with your own python" becomes a hijack of the
    console's stop button.
    """
    port = free_port()
    mgr = build_manager(tmp_path)
    exe = install_payload(mgr, port)
    other_python = tmp_path / "elsewhere" / "python3"
    other_python.parent.mkdir(parents=True)
    shutil.copy2(os.path.realpath(sys.executable), other_python)
    other_python.chmod(0o755)
    survivor = agents(spawn_agent(mgr, exe, port, executable=str(other_python)))
    assert healthy(port)

    cand = procs.ProcInfo(pid=survivor.pid,
                          argv=procs.read_cmdline(survivor.pid),
                          cwd=procs.read_cwd(survivor.pid),
                          exe=procs.read_exe(survivor.pid),
                          start_time=procs.read_start_time(survivor.pid))
    ident = mgr._agent_identity("fake")
    # The candidate matches on everything the easy checks look at...
    assert cand.cwd == str(mgr.directory("fake") / "workspace")
    assert procs.arg_value(cand.argv, "--port") == str(port)
    assert str(exe) in cand.argv
    # ...and fails only the executable comparison.
    assert not procs.same_path(cand.exe, ident["exe"]), (cand.exe, ident["exe"])

    fresh = build_manager(tmp_path)
    assert await fresh.adopt() == []
    assert fresh.status_one("fake")["running"] is False
    assert survivor.poll() is None, "an unproven process must not be signalled"


async def test_an_agent_that_does_not_answer_health_is_refused_not_restarted(
        tmp_path, agents):
    """Right process, no health: report it, refuse the start, never duplicate.

    This is the ``_wait_healthy`` contract applied to a process we did not
    spawn. Its pid is kept so ``stop`` can reach it; ``running`` stays false so
    the console never offers a UI that cannot answer.
    """
    port = free_port()
    mgr = build_manager(tmp_path)
    exe = install_payload(mgr, port)
    survivor = agents(spawn_agent(mgr, exe, port))
    assert healthy(port)
    os.kill(survivor.pid, 19)  # SIGSTOP: alive, bound, answering nothing
    try:
        fresh = build_manager(tmp_path)
        assert await fresh.adopt() == []
        status = fresh.status_one("fake")
        assert status["running"] is False
        assert status["health"] is False
        assert status["orphan_pid"] == survivor.pid
        assert status["pid"] == survivor.pid, "the process must stay visible"
        assert "接管失败" in status["last_error"]

        # A start is refused instead of spawning a second copy on that port.
        with pytest.raises(AgentBusy, match="健康检查"):
            await fresh.start("fake")
        assert survivor.poll() is None

        # And "stop" is the way out: it signals the process and clears the record.
        os.kill(survivor.pid, 18)  # SIGCONT, so it can honour the SIGTERM
        stopped = await fresh.stop("fake")
        assert stopped["orphan_pid"] is None
        assert stopped["running"] is False
        assert wait_for(lambda: survivor.poll() is not None, timeout=15)
    finally:
        if survivor.poll() is None:
            os.kill(survivor.pid, 18)


async def test_an_uninstalled_agent_is_not_searched_for(tmp_path, agents):
    """Nothing to attribute a process to: no payload, no adoption.

    An uninstall is ``rm -rf`` on the directory; a process still running out of
    it would be pointed at files that no longer exist, and the manager must not
    pretend it can drive that.
    """
    port = free_port()
    mgr = build_manager(tmp_path)
    exe = install_payload(mgr, port)
    survivor = agents(spawn_agent(mgr, exe, port))
    assert healthy(port)
    shutil.rmtree(mgr.directory("fake"))

    fresh = build_manager(tmp_path)
    assert await fresh.adopt() == []
    assert survivor.poll() is None


# -- HTTP surface ----------------------------------------------------------
def test_a_restart_takes_the_agent_over_at_startup(tmp_path, agents):
    """End to end through the lifespan hook the console actually sees."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    port = free_port()
    mgr = build_manager(tmp_path)
    exe = install_payload(mgr, port)
    state_root = mgr.data_root
    survivor = agents(spawn_agent(mgr, exe, port))
    assert healthy(port)

    app = create_app(
        data_dir=state_root / "state", models_dir=tmp_path / "models",
        backend_kind="mock", web_dir=tmp_path / "web",
        data_root=state_root, agent_specs=[FakeSpec(artifacts={})],
        service_port=18080,
    )
    with TestClient(app) as c:
        c.post("/api/login", json={"password": "admin"})
        a = c.get("/api/agents/fake").json()
        assert a["running"] is True
        assert a["pid"] == survivor.pid
        assert a["adopted"] is True
        # Starting again is idempotent: no second process, same pid.
        r = c.post("/api/agents/fake/start")
        assert r.status_code == 200, r.text
        assert r.json()["pid"] == survivor.pid
        r = c.post("/api/agents/fake/stop")
        assert r.status_code == 200, r.text
        assert r.json()["running"] is False
    assert wait_for(lambda: survivor.poll() is not None, timeout=15)


# -- the signalling guard --------------------------------------------------
def test_signal_group_refuses_pids_that_are_not_processes(monkeypatch):
    """``kill(0, sig)`` means *this process group*; it must never be reachable.

    The console's tests build stand-in processes with ``pid = 0`` (they only need
    something to report), and a manager that signalled such a handle would take
    down the process that owns it -- pytest, uvicorn, the shell. The guard is one
    line and this is the test that keeps it there.
    """
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append((pid, sig)))
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: sent.append((-pgid, sig)))

    for bad in (0, -1):
        procs.signal_group(bad, 15)
    assert sent == [], sent

    # A real pid in its own group is signalled by group; one in ours as a bare
    # process (the group form would hit this test's own process group).
    procs.signal_group(os.getpid(), 15)
    assert sent == [(os.getpid(), 15)], sent
