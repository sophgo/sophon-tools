"""Taking over the processes a previous run of the service left behind (MYS-2392).

Every test here drives **real** processes. That is the point of the module: the
bug it fixes was a manager that trusted its own memory, so a test that fakes the
process would only prove a mock can be adopted. The processes are the real
worker (``python -m app.engine.worker --backend mock``) and a real HTTP agent,
started with the exact argv and cwd the managers use, then abandoned -- which is
precisely the state a ``systemctl restart`` leaves behind.

The dangerous half is signalled everywhere: a wrong adoption means a stranger's
pid in ``_procs``, and a stop that follows kills it. So each rejection test
starts a process that *looks* like a candidate in one specific way (right argv,
wrong cwd; right cwd, wrong executable; right everything, wrong port) and asserts
it is still alive afterwards, with ``SIGTERM``/``SIGKILL`` replaced by recorders
for the pid-signalling cases that must never happen.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.core import procs
from app.core.models import ModelConflict, ModelManager
from app.main import create_app

BASE = Path(__file__).resolve().parent.parent

# The smallest agent that is still a real one: it answers /health the way the
# real specs do and reports its own pid/pgid, which is how a test proves that a
# stop reached the process it meant to.
FAKE_AGENT = """\
import http.server, json, os, socketserver, sys

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({'ok': True, 'pid': os.getpid(),
                           'pgid': os.getpgid(0)}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

class Server(socketserver.TCPServer):
    allow_reuse_address = True

port = int(sys.argv[sys.argv.index('--port') + 1])
Server(('0.0.0.0', port), Handler).serve_forever()
"""


# -- helpers ---------------------------------------------------------------
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_model(root: Path, name: str = "m") -> Path:
    d = root / name
    (d / "config").mkdir(parents=True, exist_ok=True)
    (d / f"{name}_int4_w4bf16_seq2048_4core_dynamic.bmodel").write_bytes(b"\x00" * 1024)
    (d / "config" / "config.json").write_text("{}")
    return d


def wait_for(predicate, timeout: float = 20.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def wait_port(port: int, timeout: float = 20.0) -> bool:
    def ready() -> bool:
        with socket.socket() as s:
            s.settimeout(0.2)
            return s.connect_ex(("127.0.0.1", port)) == 0
    return wait_for(ready, timeout)


def alive(pid: int) -> bool:
    return procs.process_alive(pid)


@pytest.fixture()
def track():
    """Every process a test starts, killed afterwards whatever happened."""
    started: list[subprocess.Popen] = []

    def start(argv, **kwargs) -> subprocess.Popen:
        proc = subprocess.Popen(argv, **kwargs)
        started.append(proc)
        return proc

    yield start
    for proc in started:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def spawn_worker(models_root: Path, model_id: str = "m", port: int | None = None,
                 cwd: Path | None = None, track=None, pythonpath: bool = False,
                 executable: str | None = None,
                 extra: list[str] | None = None) -> subprocess.Popen:
    """Start the real worker the way ``ModelManager._load_locked`` does.

    Logs go to a file rather than a pipe: an unread pipe would fill and block the
    worker on its own output. ``pythonpath`` lets a worker run from a cwd that is
    not the service tree (it would otherwise fail to import ``app`` at all, and
    the point of those tests is a *working* process that must still be rejected).
    ``extra`` appends flags, for tests that need the worker to report something
    the default argv would not -- a capability the adoption must pick up.
    """
    port = port or free_port()
    model = models_root / model_id
    bmodel = next(model.glob("*.bmodel"))
    log = open(os.devnull if track is None else os.devnull, "wb")
    env = dict(os.environ)
    if pythonpath:
        env["PYTHONPATH"] = str(BASE)
    argv = [
        executable or sys.executable, "-m", "app.engine.worker",
        "--model-id", model_id, "--port", str(port), "--backend", "mock",
        "--model-path", str(bmodel), "--config-path", str(model / "config"),
    ] + list(extra or [])
    return (track or subprocess.Popen)(
        argv, cwd=str(cwd or BASE), env=env, stdout=log, stderr=log,
        start_new_session=True,
    )


def worker_alive_on(port: int, model_id: str = "m", timeout: float = 20.0) -> bool:
    """Whether a worker answers its health op on ``port`` for ``model_id``."""
    import socket as _socket

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with _socket.create_connection(("127.0.0.1", port), timeout=1) as s:
                s.sendall(b'{"op":"health"}\n')
                s.settimeout(5)
                line = s.makefile().readline()
            reply = json.loads(line)
            if reply.get("ok") and reply.get("model") == model_id:
                return True
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    return False


def spawn_agent(directory: Path, port: int, track=None) -> subprocess.Popen:
    """Install-and-run the fake agent exactly as ``AgentManager._spawn`` does."""
    exe = directory / "bin" / "fake-agent"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text(FAKE_AGENT)
    exe.chmod(0o755)
    (directory / "workspace").mkdir(parents=True, exist_ok=True)
    log = open(os.devnull, "wb")
    return (track or subprocess.Popen)(
        [sys.executable, str(exe), "--port", str(port)],
        cwd=str(directory / "workspace"), stdout=log, stderr=log,
        start_new_session=True,
    )


# -- model discovery and takeover -----------------------------------------
@pytest.mark.asyncio
async def test_a_surviving_worker_is_taken_over_not_respawned(tmp_path, track):
    """The reported bug: a restart must not start a second worker.

    The worker is spawned directly (not through the manager) with the manager's
    own argv and cwd, which is the only way to reproduce "a previous run left
    this behind": a manager that spawned it would remember it.
    """
    models = tmp_path / "models"
    make_model(models)
    port = free_port()
    survivor = spawn_worker(models, "m", port, track=track)
    try:
        assert wait_port(port), "the worker never came up"
        assert worker_alive_on(port), "the worker never answered health"

        mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
        mgr.refresh()
        # Before recovery it believes nothing is loaded -- exactly the state that
        # used to make a load spawn a second worker.
        assert mgr.loaded_count == 0

        adopted = await mgr.adopt()
        assert [m.model_id for m in adopted] == ["m"]
        info = mgr.get("m")
        assert info.loaded is True
        assert info.adopted is True
        assert info.pid == survivor.pid, (info.pid, survivor.pid)
        assert info.port == port
        assert info.adopted is True
        assert mgr.worker_pids() == {survivor.pid}

        # A load now joins the adopted worker instead of spawning.
        same = await mgr.load("m")
        assert same is info and same.pid == survivor.pid
    finally:
        pass


@pytest.mark.asyncio
async def test_unloading_a_taken_over_worker_still_stops_it(tmp_path, track):
    """Adoption has to be worth something: unload must actually free the NPU.

    An adopted handle refuses SIGKILL (we cannot see its exit status and a
    mid-prefill kill can wedge the TPU), so this also proves the graceful path
    -- SIGTERM to the group -- is what does the work.
    """
    models = tmp_path / "models"
    make_model(models)
    port = free_port()
    survivor = spawn_worker(models, "m", port, track=track)
    assert wait_port(port) and worker_alive_on(port)

    mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()
    await mgr.adopt()
    assert mgr.get("m").loaded

    info = await mgr.unload("m")
    assert info.loaded is False and info.pid is None and info.port is None
    assert info.adopted is False
    assert wait_for(lambda: survivor.poll() is not None, timeout=15), \
        "the adopted worker survived unload"
    assert not mgr.worker_pids()


@pytest.mark.asyncio
async def test_a_worker_on_the_wrong_port_is_not_adopted(tmp_path, track):
    """The process is a real worker for this model -- but not on our tree's terms.

    The point of the check is the *pair*: the pid must belong to this models
    root. A worker started from another checkout (a second data root, an old
    release still running) is precisely the "old and new version coexist" case,
    and it must not be silently taken over.
    """
    models = tmp_path / "models"
    other = tmp_path / "other-models"
    make_model(models)
    make_model(other)
    port = free_port()
    survivor = spawn_worker(other, "m", port, track=track)
    try:
        assert wait_port(port) and worker_alive_on(port)

        mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
        mgr.refresh()
        assert await mgr.adopt() == []
        info = mgr.get("m")
        assert info.loaded is False and info.pid is None
        assert info.conflict is None, info.conflict
        # And it was left strictly alone.
        assert survivor.poll() is None
        assert mgr.worker_pids() == set()
    finally:
        survivor.kill()
        survivor.wait(timeout=10)


@pytest.mark.asyncio
async def test_a_process_with_the_right_argv_but_a_foreign_cwd_is_not_adopted(
        tmp_path, track):
    """argv alone is not identity: an unrelated process can say anything.

    This is the false-positive that would be expensive -- adopting it and then
    unloading would SIGTERM a process this service never started.
    """
    models = tmp_path / "models"
    make_model(models)
    port = free_port()
    # Same argv and the same models tree, but started from the temp dir instead
    # of the service's own cwd. PYTHONPATH makes that a *working* worker: the
    # rejection has to come from the cwd check, not from an import error.
    survivor = spawn_worker(models, "m", port, cwd=tmp_path, track=track,
                            pythonpath=True)
    try:
        assert wait_port(port) and worker_alive_on(port)
        mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
        mgr.refresh()
        assert await mgr.adopt() == []
        assert mgr.get("m").loaded is False
        assert survivor.poll() is None, "an unproven process must not be signalled"
    finally:
        survivor.kill()
        survivor.wait(timeout=10)


@pytest.mark.asyncio
async def test_a_process_that_only_mentions_the_worker_is_not_adopted(tmp_path, track):
    """A command line can *mention* the module without being run as it.

    ``python -c "..." -m app.engine.worker --model-id m ...`` runs this
    interpreter, from the right cwd, with this model's path -- and is a stranger
    all the same. Only ``-m app.engine.worker`` in their own positions makes a
    process a worker; matching the token anywhere in argv is how a ``grep``, a
    pager or an editor would get adopted and then SIGTERMmed.
    """
    models = tmp_path / "models"
    make_model(models)
    bmodel = next((models / "m").glob("*.bmodel"))
    port = free_port()
    decoy = (track or subprocess.Popen)(
        [sys.executable, "-c", "import time; time.sleep(120)",
         "-m", "app.engine.worker", "--model-id", "m", "--port", str(port),
         "--model-path", str(bmodel),
         "--config-path", str(models / "m" / "config")],
        cwd=str(BASE), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        assert wait_for(lambda: procs.read_cmdline(decoy.pid)[1:3] == [
            "-c", "import time; time.sleep(120)"], timeout=10)
        mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
        mgr.refresh()
        assert await mgr.adopt() == []
        assert mgr.get("m").loaded is False
        assert decoy.poll() is None, "a process we cannot prove is ours must not be touched"
    finally:
        decoy.kill()
        decoy.wait(timeout=10)


@pytest.mark.asyncio
async def test_a_binary_that_is_not_the_interpreter_is_not_adopted(tmp_path, track):
    """The executable is the fact; the argv is only what the process claims.

    Here the command line is *exactly* right -- ``-m app.engine.worker``, this
    model, this cwd -- and the binary is not the interpreter this service runs
    workers with. A Python that is not ``sys.executable`` (another
    installation, another ABI) is not what a load would have started, so taking
    it over would mean driving a process this service cannot account for.
    """
    models = tmp_path / "models"
    make_model(models)
    bmodel = next((models / "m").glob("*.bmodel"))
    port = free_port()
    impostor = tmp_path / "bin" / "worker"
    impostor.parent.mkdir(parents=True)
    shutil.copy2(os.path.realpath(sys.executable), impostor)
    impostor.chmod(0o755)
    decoy = (track or subprocess.Popen)(
        [str(impostor), "-m", "app.engine.worker", "--model-id", "m",
         "--port", str(port), "--backend", "mock",
         "--model-path", str(bmodel), "--config-path", str(models / "m" / "config")],
        cwd=str(BASE), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        assert wait_for(lambda: procs.read_cmdline(decoy.pid)[1:3] == [
            "-m", "app.engine.worker"], timeout=10)
        mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
        mgr.refresh()
        assert await mgr.adopt() == []
        assert mgr.get("m").loaded is False
        assert decoy.poll() is None
    finally:
        decoy.kill()
        decoy.wait(timeout=10)


@pytest.mark.asyncio
async def test_a_worker_that_does_not_answer_health_is_a_conflict_not_loaded(
        tmp_path, track):
    """Right identity, wrong answer: refuse, do not adopt and do not respawn.

    A worker that is 90 s into mapping a 35B holds the NPU heap but is not
    serving yet. Reporting it loaded would route requests into a socket that
    hangs; reporting it idle would let a load put a second 20 GB allocation next
    to it. Neither is acceptable, so the model reports a conflict and a load is
    refused with 409 semantics.
    """
    models = tmp_path / "models"
    make_model(models)
    port = free_port()
    # A real worker process, but wedged before it can serve: SIGSTOP freezes it
    # after it starts, which is what "still loading" looks like from outside.
    survivor = spawn_worker(models, "m", port, track=track)
    assert wait_port(port)
    os.kill(survivor.pid, signal.SIGSTOP)
    try:
        mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
        mgr.refresh()
        adopted = await mgr.adopt()
        assert adopted == []
        info = mgr.get("m")
        assert info.loaded is False
        assert info.conflict, "a survivor that cannot serve must be reported"
        assert info.pid == survivor.pid
        assert mgr.worker_pids() == set(), "an unproven worker is not driven"

        # A load is refused instead of spawning a second worker.
        with pytest.raises(ModelConflict, match="健康检查"):
            await mgr.load("m")
        assert survivor.poll() is None
    finally:
        os.kill(survivor.pid, signal.SIGCONT)
        survivor.kill()
        survivor.wait(timeout=10)


@pytest.mark.asyncio
async def test_unload_clears_a_conflict_with_sigterm_only(tmp_path, track):
    """The one action an operator has: stop the survivor, gracefully.

    SIGKILL is replaced by a recorder, because a kill here is the mistake this
    test exists to prevent -- the process might be mid-prefill.
    """
    models = tmp_path / "models"
    make_model(models)
    port = free_port()
    survivor = spawn_worker(models, "m", port, track=track)
    assert wait_port(port)
    os.kill(survivor.pid, signal.SIGSTOP)
    try:
        mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
        mgr.refresh()
        await mgr.adopt()
        assert mgr.get("m").conflict

        os.kill(survivor.pid, signal.SIGCONT)
        info = await mgr.unload("m")
        assert info.conflict is None
        assert info.pid is None and info.loaded is False
        assert wait_for(lambda: survivor.poll() is not None, timeout=15)
    finally:
        if survivor.poll() is None:
            survivor.kill()
            survivor.wait(timeout=10)


@pytest.mark.asyncio
async def test_a_dead_worker_stops_reading_as_loaded(tmp_path):
    """`loaded` is a claim about a process, so it is re-derived, not remembered.

    Nothing reaps a worker: it is in its own session and its parent is the
    service. A worker that dies is therefore invisible until someone looks, and
    the look has to happen on ``refresh`` -- which is what ``GET /api/models``
    and every load/unload calls.
    """
    models = tmp_path / "models"
    make_model(models)
    mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()
    info = await mgr.load("m")
    assert info.loaded
    pid = info.pid
    os.kill(pid, signal.SIGKILL)
    assert wait_for(lambda: not procs.process_alive(pid), timeout=10)

    mgr.refresh()
    assert info.loaded is False
    assert info.pid is None and info.port is None
    assert "退出" in (info.load_error or "")
    # And a load works again -- the dead one is not remembered.
    again = await mgr.load("m")
    try:
        assert again.loaded and again.pid != pid
    finally:
        await mgr.unload_all()


@pytest.mark.asyncio
async def test_two_surviving_workers_for_one_model_are_refused(tmp_path, track):
    """Two pids that both look right is the case where guessing is worst.

    Whichever we picked, the other would keep its NPU allocation and no button
    would ever free it, so nothing is adopted and the conflict names both.
    """
    models = tmp_path / "models"
    make_model(models)
    p1, p2 = free_port(), free_port()
    a = spawn_worker(models, "m", p1, track=track)
    b = spawn_worker(models, "m", p2, track=track)
    try:
        assert wait_port(p1) and wait_port(p2)
        mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
        mgr.refresh()
        adopted = await mgr.adopt()
        assert adopted == []
        info = mgr.get("m")
        assert info.loaded is False
        assert str(a.pid) in info.conflict and str(b.pid) in info.conflict
        with pytest.raises(ModelConflict, match="多个"):
            await mgr.load("m")
    finally:
        for p in (a, b):
            p.kill()
            p.wait(timeout=10)


# -- a live second instance ------------------------------------------------
def test_a_live_second_instance_on_the_same_data_root_is_not_taken_over(tmp_path):
    """A survivor with a living owner is not a survivor.

    "The previous run died" and "another copy is running right now" look identical
    in ``/proc``, and treating the second as the first would have two managers
    drive one worker: one console would unload a model the other is serving, and
    a stop in either would signal a process the other still needs. So a live
    instance on the same data root makes recovery refuse and report.

    The rival here is faked as a ``ProcInfo``: starting a real second uvicorn
    would cost a port and ~10 MB of memory to prove one predicate, and the
    predicate is exactly what ``service_instances`` returns.
    """
    models = tmp_path / "models"
    make_model(models)
    port = free_port()
    survivor = spawn_worker(models, "m", port)
    assert wait_port(port) and worker_alive_on(port)
    try:
        mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs",
                           data_root=tmp_path / "root")
        mgr.refresh()
        rival = procs.ProcInfo(pid=4242, argv=[sys.executable, "-m", "app.main",
                                              "--data-root", str(tmp_path / "root")],
                               cwd=str(BASE), exe=sys.executable)
        assert procs.same_path(procs.arg_value(rival.argv, "--data-root"),
                              tmp_path / "root")

        original = procs.service_instances
        procs.service_instances = lambda root, **kw: [rival]
        try:
            assert asyncio.run(mgr.adopt()) == []
        finally:
            procs.service_instances = original
        info = mgr.get("m")
        assert info.loaded is False
        assert info.conflict and "另一个本服务实例" in info.conflict
        assert "4242" in info.conflict
        # The start is refused rather than racing the live instance.
        with pytest.raises(ModelConflict):
            asyncio.run(mgr.load("m"))
        assert survivor.poll() is None
    finally:
        survivor.kill()
        survivor.wait(timeout=10)


def test_recovery_asks_about_its_own_data_root(tmp_path):
    """Identified by data root, not by "a service process exists somewhere".

    A second instance serving another data root owns other processes; refusing
    recovery because it exists would leave two installations on one host
    permanently blind to their own workers. So the check must be asked about
    *this* root -- which is what this asserts, at the one place that decides it.
    """
    models = tmp_path / "models"
    make_model(models)
    mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs",
                       data_root=tmp_path / "root")
    mgr.refresh()
    asked: list = []

    def spy(root, **kwargs):
        asked.append(root)
        return []

    original = procs.service_instances
    procs.service_instances = spy
    try:
        asyncio.run(mgr.adopt())
    finally:
        procs.service_instances = original
    assert asked == [tmp_path / "root"], asked


def test_a_manager_without_a_data_root_skips_the_rival_check(tmp_path):
    """A dev checkout (``--models-dir``, no root) has nothing to compare.

    Guessing one from the models directory's parent would make unrelated
    services on the host look like rivals of each other, so the check is skipped
    when the install does not declare a root -- and adoption works normally.
    """
    models = tmp_path / "models"
    make_model(models)
    mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()
    called: list = []

    def spy(*args, **kwargs):  # pragma: no cover - must not be reached
        called.append(args)
        return []

    original = procs.service_instances
    procs.service_instances = spy
    try:
        asyncio.run(mgr.adopt())
    finally:
        procs.service_instances = original
    assert called == []
    assert mgr._data_root() is None


# -- HTTP surface ----------------------------------------------------------
@pytest.fixture()
def restarted_app(tmp_path):
    """The service as it comes up after a restart, around an abandoned worker."""
    from app.core.state import StateStore

    models = tmp_path / "models"
    make_model(models)
    StateStore(tmp_path / "root" / "state" / "state.json")  # noqa: B018 - layout only
    port = free_port()
    survivor = spawn_worker(models, "m", port)
    assert wait_port(port) and worker_alive_on(port)

    app = create_app(
        data_dir=tmp_path / "root" / "state", models_dir=models,
        backend_kind="mock", web_dir=tmp_path / "web",
        data_root=tmp_path / "root", service_port=18080,
        agent_specs=[],
    )
    try:
        yield app, survivor
    finally:
        if survivor.poll() is None:
            survivor.kill()
            survivor.wait(timeout=10)


def test_the_service_takes_a_surviving_worker_over_at_startup(restarted_app):
    """End to end: the lifespan hook is what makes recovery real.

    ``GET /api/models`` after a restart must say loaded -- with the pid of the
    process that was already running, and with a client registered, or the first
    completion request would find ``loaded`` and no RPC socket.
    """
    from fastapi.testclient import TestClient

    app, survivor = restarted_app
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        listed = {m["id"]: m for m in c.get("/api/models").json()["models"]}
        m = listed["m"]
        assert m["loaded"] is True
        assert m["pid"] == survivor.pid
        assert m["adopted"] is True
        assert m["conflict"] is None
        # The RPC client exists the instant `loaded` does; without it the first
        # request 500s with "no client for model".
        assert "m" in app.state.clients
        assert app.state.clients["m"].port == m["port"]
        # A load is idempotent against the adopted worker, not a second spawn.
        r = c.post("/api/models/m/load")
        assert r.status_code == 200, r.text
        assert r.json()["model"]["pid"] == survivor.pid
        # And unload still works through the HTTP path.
        r = c.post("/api/models/m/unload")
        assert r.status_code == 200, r.text
        assert r.json()["model"]["loaded"] is False
    assert wait_for(lambda: survivor.poll() is not None, timeout=15)


def test_an_adopted_worker_really_serves_completions(restarted_app):
    """Takeover is only real if inference works through the adopted socket.

    The failure this would catch: a manager that marks the model loaded and
    registers a client, but on a port that no worker is listening on (or with a
    client bound to the wrong port) -- ``GET /api/models`` would look right and
    every completion would fail.
    """
    from fastapi.testclient import TestClient

    app, survivor = restarted_app
    with TestClient(app) as c:
        c.post("/api/login", json={"password": "admin"})
        m = {x["id"]: x for x in c.get("/api/models").json()["models"]}["m"]
        key = c.post("/api/keys", json={"name": "k"}).json()["key"]
        r = c.post("/v1/chat/completions",
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": "m", "max_tokens": 4,
                         "messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["model"] == "m"
        assert body["choices"][0]["message"]["content"]
        # The token came from the process that was already running: no second
        # pid was spawned to answer it.
        assert survivor.poll() is None
        assert app.state.models.get("m").pid == survivor.pid


def test_a_conflicted_model_loads_with_409_and_is_not_respawned(tmp_path):
    """The console's view of a worker it cannot prove: refused, with the reason."""
    from fastapi.testclient import TestClient

    models = tmp_path / "models"
    make_model(models)
    port = free_port()
    survivor = spawn_worker(models, "m", port)
    assert wait_port(port)
    os.kill(survivor.pid, signal.SIGSTOP)
    try:
        app = create_app(
            data_dir=tmp_path / "root" / "state", models_dir=models,
            backend_kind="mock", web_dir=tmp_path / "web",
            data_root=tmp_path / "root", service_port=18080, agent_specs=[],
        )
        with TestClient(app) as c:
            c.post("/api/login", json={"password": "admin"})
            m = {x["id"]: x for x in c.get("/api/models").json()["models"]}["m"]
            assert m["loaded"] is False
            assert m["conflict"]
            r = c.post("/api/models/m/load")
            assert r.status_code == 409, r.text
            assert "worker" in r.json()["detail"]
            # Still exactly one worker process.
            assert survivor.poll() is None
    finally:
        os.kill(survivor.pid, signal.SIGCONT)
        survivor.kill()
        survivor.wait(timeout=10)


# -- adoption is a readiness decision, not a liveness one (MYS-2496) --------
@pytest.mark.asyncio
async def test_a_survivor_that_is_not_fully_initialised_is_not_adopted(
        tmp_path, track, monkeypatch):
    """A worker that answers health but not stats has not finished initialising.

    The socket accepting and the model serving are different facts. Adoption
    used to ask only the first (one health round trip), so a worker whose
    scheduler was not up could be taken over and would then fail every request.
    """
    models = tmp_path / "models"
    make_model(models)
    port = free_port()
    survivor = spawn_worker(models, "m", port, track=track)
    try:
        assert worker_alive_on(port)

        mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
        # `stats` is what proves the scheduler is running; make it fail the way
        # a half-initialised worker would.
        async def no_stats(port_, model_id_):
            return False

        monkeypatch.setattr(mgr, "_probe_worker", no_stats)
        mgr.refresh()
        assert await mgr.adopt() == []
        info = mgr.get("m")
        assert info.loaded is False, "an unproven worker must not read as loaded"
        assert info.conflict, "and the refusal must be visible to the operator"
        assert info.operation is None, "adoption must not leave a model 'loading'"
        assert mgr.worker_pids() == set()
        assert survivor.poll() is None, "an unproven process is not signalled"
    finally:
        survivor.kill()
        survivor.wait(timeout=10)


@pytest.mark.asyncio
async def test_adoption_publishes_loading_while_it_probes(tmp_path, track, monkeypatch):
    """The probe window must not read as `idle`, or a load spawns worker #2.

    `adopt` runs two round trips against a process that may be wedged. Leaving
    the model idle-looking for that long is the same bug the load path fixed:
    a click during it starts a second worker on the same bmodel.
    """
    import asyncio as _asyncio

    models = tmp_path / "models"
    make_model(models)
    port = free_port()
    survivor = spawn_worker(models, "m", port, track=track)
    try:
        assert worker_alive_on(port)
        mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
        mgr.refresh()

        seen: list[str | None] = []
        real = mgr._probe_capabilities

        async def slow_caps(port_, info_, settle_timeout=30.0):
            seen.append(info_.operation)
            await _asyncio.sleep(0.05)
            return await real(port_, info_, settle_timeout)

        monkeypatch.setattr(mgr, "_probe_capabilities", slow_caps)
        adopted = await mgr.adopt()
        assert [m.model_id for m in adopted] == ["m"]
        assert seen == ["loading"], f"the probe ran with operation={seen}"
        info = mgr.get("m")
        assert info.loaded is True and info.operation is None
        assert info.adopted is True
    finally:
        survivor.kill()
        survivor.wait(timeout=10)


@pytest.mark.asyncio
async def test_an_adopted_worker_reports_its_real_capabilities(tmp_path, track):
    """Adoption must read the survivor's capabilities, not reuse file-name guesses.

    A restart that adopted with `supports_vision`/`context_length` from the
    filename would serve with stale capabilities until the next real load.
    """
    models = tmp_path / "models"
    make_model(models)
    port = free_port()
    survivor = spawn_worker(models, "m", port, track=track,
                            extra=["--context-length", "777"])
    try:
        assert worker_alive_on(port)
        mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
        mgr.refresh()
        before = mgr.get("m")
        # The fixture's filename says seq2048; the worker says otherwise.
        assert before.context_length == 2048
        adopted = await mgr.adopt()
        assert [m.model_id for m in adopted] == ["m"]
        assert mgr.get("m").context_length == 777, (
            "the adopted worker's own answer must win over the file name")
    finally:
        survivor.kill()
        survivor.wait(timeout=10)
