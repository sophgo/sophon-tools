"""An agent's operation as the backend reports it (MYS-2388).

``status`` deliberately folds "starting"/"stopping" into ``stopped`` (there is
no process to point at yet), so the console had no way to know a start was in
flight -- and after a page refresh it showed an idle agent whose start button
was live again. These tests pin the contract that fixes it: an ``operation``
derived from the runtime/job the manager already keeps, never a second copy.
"""

from __future__ import annotations

import asyncio
import json
import socket
import textwrap
import threading
import time
from pathlib import Path

import pytest

from app.agents.manager import AGENT_OPERATIONS, AgentBusy
from tests.test_agents import FakeSpec, Svc, build_tarball, install, wait_job  # noqa: F401


@pytest.fixture()
def svc(tmp_path):
    tarball = build_tarball(
        tmp_path / "fake-1.0.0.tar.gz",
        {"fake-1.0.0/bin/fake-agent": textwrap.dedent(
            __import__("tests.test_agents", fromlist=["FAKE_AGENT"]).FAKE_AGENT)},
    )
    return Svc(tmp_path, tarball)


async def wait_operation(svc, operation: str, timeout: float = 20.0) -> dict:
    """Poll status the way a reloaded page does, until ``operation`` appears."""
    for _ in range(int(timeout / 0.05)):
        state = svc.mgr.status_one("fake")
        if state.get("operation") == operation:
            return state
        await asyncio.sleep(0.05)
    raise AssertionError(
        f"operation never became {operation!r}; last state {svc.mgr.status_one('fake')}")


def test_the_reported_operation_is_one_of_the_documented_set():
    """The console switches on these strings; an undocumented one would be a bug."""
    assert set(AGENT_OPERATIONS) == {
        "installing", "starting", "stopping", "restarting", "resetting",
        "uninstalling", "configuring",
    }


async def test_idle_agent_reports_no_operation(svc):
    state = svc.mgr.status_one("fake")
    assert state["operation"] is None
    assert state["busy"] is False
    assert state["operation_since"] is None


async def test_install_is_visible_as_an_operation_after_a_reload(svc):
    """The install job used to be the only trace; `operation` must carry it too."""
    job = await svc.mgr.install("fake")
    assert job.state == "running"
    state = svc.mgr.status_one("fake")
    assert state["operation"] == "installing", state
    assert state["busy"] is True
    assert state["operation_label"] == "安装"
    await wait_job(svc)
    assert svc.mgr.status_one("fake")["operation"] is None


async def test_starting_is_visible_while_health_is_pending(svc, monkeypatch):
    """`status` says "stopped" during a start; `operation` must say "starting".

    This is exactly the state a refreshed console used to misread: the four
    value `status` cannot express "a process is coming up", so the start button
    came back live and a second start raced the first.
    """
    await install(svc)
    release = threading.Event()

    original = svc.mgr._wait_healthy

    async def slow_healthy(agent_id, timeout):
        await asyncio.get_running_loop().run_in_executor(None, release.wait, 20)
        return await original(agent_id, timeout)

    monkeypatch.setattr(svc.mgr, "_wait_healthy", slow_healthy)
    task = asyncio.create_task(svc.mgr.start("fake"))
    state = await wait_operation(svc, "starting")
    assert state["status"] in ("stopped", "starting"), state["status"]
    assert state["running"] is False
    assert state["operation_label"] == "启动"
    # A second start while the first is in flight is refused, not queued behind
    # a health wait that can run for 30 s.
    with pytest.raises(AgentBusy, match="启动"):
        await svc.mgr.start("fake")

    release.set()
    await task
    assert svc.mgr.status_one("fake")["operation"] is None
    assert svc.mgr.status_one("fake")["running"] is True
    await svc.mgr.stop("fake")


async def test_stopping_is_visible_and_blocks_a_second_stop(svc, monkeypatch):
    await install(svc)
    await svc.mgr.start("fake")
    release = threading.Event()
    original = svc.mgr._stop_locked

    async def slow_stop(agent_id, kill_only=False):
        await asyncio.get_running_loop().run_in_executor(None, release.wait, 20)
        return await original(agent_id, kill_only)

    monkeypatch.setattr(svc.mgr, "_stop_locked", slow_stop)
    task = asyncio.create_task(svc.mgr.stop("fake"))
    state = await wait_operation(svc, "stopping")
    assert state["operation_label"] == "停止"
    with pytest.raises(AgentBusy, match="停止"):
        await svc.mgr.stop("fake")
    release.set()
    await task
    assert svc.mgr.status_one("fake")["operation"] is None
    assert svc.mgr.status_one("fake")["running"] is False


async def test_a_failed_start_clears_the_operation(svc, monkeypatch):
    """A refused start must not lock the card in "starting" forever."""
    await install(svc)
    monkeypatch.setattr(svc.mgr, "start_timeout_override", 0.3)

    async def never_healthy(agent_id, timeout):
        return False

    monkeypatch.setattr(svc.mgr, "_wait_healthy", never_healthy)
    with pytest.raises(AgentBusy):
        await svc.mgr.start("fake")
    state = svc.mgr.status_one("fake")
    assert state["operation"] is None, "a failed start left the console locked"
    assert state["running"] is False


async def test_reset_and_uninstall_clear_their_operation(svc):
    await install(svc)
    await svc.mgr.reset("fake")
    assert svc.mgr.status_one("fake")["operation"] is None
    await svc.mgr.uninstall("fake")
    state = svc.mgr.status_one("fake")
    assert state["operation"] is None
    assert state["status"] == "not_installed"


async def test_sync_reports_configuring_and_releases(svc):
    await install(svc)
    await svc.mgr.sync("fake")
    assert svc.mgr.status_one("fake")["operation"] is None


async def test_operation_and_status_stay_consistent_through_a_restart(svc):
    """After the whole cycle, no operation is left behind."""
    await install(svc)
    await svc.mgr.start("fake")
    try:
        assert svc.mgr.status_one("fake")["operation"] is None
        await svc.mgr.restart("fake")
        state = svc.mgr.status_one("fake")
        assert state["operation"] is None
        assert state["status"] == "running" and state["running"] is True
    finally:
        await svc.mgr.stop("fake")


async def test_status_and_operation_describe_the_same_process(svc):
    """`running`/`pid`/`operation` must never contradict each other."""
    await install(svc)
    state = await svc.mgr.start("fake")
    try:
        assert state["running"] is True and state["pid"]
        assert state["operation"] is None
        assert state["health"] is True
    finally:
        state = await svc.mgr.stop("fake")
    assert state["running"] is False and state["pid"] is None
    assert state["operation"] is None


def test_the_http_status_carries_the_operation(tmp_path):
    """The console reads `operation` off GET /api/agents after a reload."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    tarball = build_tarball(
        tmp_path / "fake-1.0.0.tar.gz",
        {"fake-1.0.0/bin/fake-agent": textwrap.dedent(
            __import__("tests.test_agents", fromlist=["FAKE_AGENT"]).FAKE_AGENT)},
    )
    import hashlib

    from app.agents.spec import Artifact, host_arch

    art = Artifact(urls=(f"file://{tarball}",),
                   sha256=hashlib.sha256(tarball.read_bytes()).hexdigest())
    spec = FakeSpec(artifacts={"x64": art, "arm64": art})
    models = tmp_path / "models"
    models.mkdir()
    app = create_app(
        data_dir=tmp_path / "state", models_dir=models, backend_kind="mock",
        web_dir=tmp_path / "web", data_root=tmp_path / "root",
        agent_specs=[spec], service_port=18080,
    )
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        agent = c.get("/api/agents").json()["agents"][0]
        assert agent["operation"] is None and agent["busy"] is False

        assert c.post("/api/agents/fake/install").status_code == 202
        # The fake payload installs in milliseconds, so racing the poll would
        # make this assertion depend on the machine. Park the job in `running`
        # the way a 78 MB download over a slow link really does, read what a
        # reloaded page sees, then put the real job back.
        from app.agents.manager import Job

        mgr = app.state.agents
        real_job = mgr._jobs["fake"]
        mgr._jobs["fake"] = Job(agent_id="fake", state="running", message="正在下载 1.0 MiB")
        listed = c.get("/api/agents").json()["agents"][0]
        assert listed["operation"] == "installing", listed
        assert listed["busy"] is True
        assert listed["operation_label"] == "安装"
        mgr._jobs["fake"] = real_job

        for _ in range(200):
            job = c.get("/api/agents/fake/job").json()["job"]
            if job["state"] in ("done", "error"):
                break
            time.sleep(0.05)
        assert job["state"] == "done", job
        assert c.get("/api/agents").json()["agents"][0]["operation"] is None

        r = c.post("/api/agents/fake/start")
        assert r.status_code == 200, r.text
        started = r.json()
        assert started["operation"] is None
        assert started["running"] is True
        # Starting again while it runs is a state refusal, reported as such.
        r = c.post("/api/agents/fake/start")
        assert r.status_code == 200, r.text
        assert r.json()["running"] is True

        assert c.post("/api/agents/fake/stop").status_code == 200
        stopped = c.get("/api/agents").json()["agents"][0]
        assert stopped["operation"] is None and stopped["running"] is False
