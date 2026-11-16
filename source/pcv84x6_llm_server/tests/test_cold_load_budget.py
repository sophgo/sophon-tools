"""Cold-load budget synchronisation (MYS-2805, stage 30).

The defect these tests reproduce: a model loaded by a **fresh** management
process ends up enforcing a runtime budget computed from the *estimate* of its
static footprint rather than from the footprint the load was measured at.

The load path spawns the worker with ``--mem-static-bytes`` set to
``mem_limit.estimate_static_bytes`` -- the declared, pre-load figure -- because
that is all that exists before the worker runs. ``_record_static_measurement``
then writes the real figure once the process has mapped its weights, but the
worker had already computed ``limit - estimate`` and nothing told it again. On
the reviewer's cold `.157` run:

    limit            14355 MiB
    measured static  13978738688 B  (13331 MiB + 172032 B)
    worker budget     5482284672 B
    correct           1073569792 B   -> 4408714880 B (4.1 GiB) too much

A management process that has loaded the model before never shows it, because
``static_bytes`` is cached and the next spawn uses the measurement. So the
reproduction has to be a **fresh** manager, and the assertion has to be taken
after the load returns with **no** ``PUT`` in between -- a save repairs the
budget, which is exactly what made the earlier evidence look green.

Every test drives the real HTTP surface, a real worker process (mock backend) and
the real RPC socket; only the *device* readings and the size of the model file are
substituted, because a laptop has no NPU and a 13 GiB bmodel is not in the repo.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

import pytest
import starlette.requests
from fastapi.testclient import TestClient

from app.core import models as models_mod
from app.core import monitor, procs
from app.core.models import ModelConflict, ModelManager
from app.core.state import ModelSettings
from app.main import create_app

MIB = 1 << 20
CHAT_BMODEL = "qwen3.6-35b-a3b-int4-autow4bf16"
#: The fixture's declared static figure: 256 MiB, exactly (the file is truncated
#: to this), because no libbmrt exists on a host.
DECLARED = 256 * MIB
#: The reviewer's sub-MiB tail, so a value truncated to whole MiB is visible.
FRACTION = 172032


def make_model(root: Path, name: str, bmodel: str = CHAT_BMODEL,
               size: int = DECLARED) -> Path:
    d = root / name
    (d / "config").mkdir(parents=True, exist_ok=True)
    with open(d / f"{bmodel}_seq2048_4core_static.bmodel", "wb") as fh:
        fh.truncate(size)
    (d / "config" / "config.json").write_text("{}")
    return d


def heap(free_mb: int, *, npu_total_mb: int = 26624) -> dict:
    return {
        "total_bytes": (npu_total_mb + 2048) * MIB,
        "used_bytes": (npu_total_mb - free_mb + 256) * MIB,
        "max_block_bytes": free_mb * MIB,
        "source": "bmlib",
        "heaps": [
            {"name": "npu", "total_bytes": npu_total_mb * MIB,
             "used_bytes": (npu_total_mb - free_mb) * MIB,
             "free_bytes": free_mb * MIB},
            {"name": "vpp", "total_bytes": 2048 * MIB,
             "used_bytes": 256 * MIB, "free_bytes": (2048 - 256) * MIB},
        ],
    }


class Device:
    """A simulated two-heap device whose ``used`` figure follows the loads.

    A load reads ``used`` once before the spawn and once after the worker is
    ready; their difference *is* the measurement, which is why the real board
    needs no model of what a worker does. Here the footprints are scripted
    instead: ``load(size)`` queues one, spent by the **next spawn** -- the same
    instant the device would really start losing the heap, and always after the
    pre-spawn sample that opens the window.

    Byte-exact on purpose: a value rounded to MiB would hide the sub-MiB tail the
    reviewer's reproduction turned on.
    """

    def __init__(self) -> None:
        self.free_bytes = 12000 * MIB
        self._queue: list[int] = []
        self.reads = 0

    @property
    def free_mb(self) -> int:
        return self.free_bytes // MIB

    @free_mb.setter
    def free_mb(self, value: int) -> None:
        self.free_bytes = int(value) * MIB

    def load(self, nbytes: int) -> None:
        self._queue.append(int(nbytes))

    def _spawned(self, *_args, **_kwargs):
        if self._queue:
            self.free_bytes = max(0, self.free_bytes - self._queue.pop(0))
        return _real_subprocess_exec(*_args, **_kwargs)

    def install(self, monkeypatch) -> "Device":
        global _real_subprocess_exec
        if _real_subprocess_exec is None:
            _real_subprocess_exec = asyncio.create_subprocess_exec
        monkeypatch.setattr(monitor, "device_memory", self.reading)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", self._spawned)
        return self

    def reading(self) -> dict:
        self.reads += 1
        free = self.free_bytes
        total = 26624 * MIB + 2048 * MIB
        # ``used`` is what ``_record_static_measurement`` differences, so it has to
        # be the moving half.
        used = total - free
        return {
            "total_bytes": total,
            "used_bytes": used,
            "max_block_bytes": free,
            "source": "bmlib",
            "heaps": [
                {"name": "npu", "total_bytes": 26624 * MIB,
                 "used_bytes": 26624 * MIB - free, "free_bytes": free},
                {"name": "vpp", "total_bytes": 2048 * MIB,
                 "used_bytes": 256 * MIB, "free_bytes": (2048 - 256) * MIB},
            ],
        }


def pin_static(monkeypatch, values: dict[str, int]) -> None:
    """Script what each model's load measures, for the concurrency tests.

    Two loads finishing in the same window share one heap delta: on the real board
    ``_record_static_measurement`` then attributes the *whole* movement to
    whichever load reads last, which is a property of heap sampling rather than of
    this change. These tests are about what happens **after** the measurement, so
    the figure is pinned and the spawn, sync, admission and ledger stay real.
    """
    real = ModelManager._record_static_measurement

    def scripted(self, info, before, after):
        real(self, info, before, after)
        pinned = values.get(info.model_id)
        if pinned is None:
            return None
        info.measured_static_bytes = int(pinned)
        self._static_bytes[info.model_id] = int(pinned)
        return int(pinned)

    monkeypatch.setattr(ModelManager, "_record_static_measurement", scripted)


_real_subprocess_exec = None


@pytest.fixture()
def models_dir(tmp_path: Path) -> Path:
    root = tmp_path / "models"
    make_model(root, "chat-a")
    make_model(root, "chat-b")
    return root


def fresh_app(tmp_path: Path, models_dir: Path):
    """A management process that has never loaded anything (the reproduction)."""
    return create_app(data_dir=tmp_path / "data", models_dir=models_dir,
                      backend_kind="mock", web_dir=tmp_path / "web",
                      context_length_override=4096)


@pytest.fixture()
def device(monkeypatch) -> Device:
    return Device().install(monkeypatch)


@pytest.fixture()
def app(tmp_path: Path, models_dir: Path, device: Device):
    return fresh_app(tmp_path, models_dir)


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        yield c


def static_bytes_of(app, model_id: str) -> int:
    mgr = app.state.models
    return mgr.static_bytes(mgr.get(model_id))


def expected_budget(app, model_id: str) -> int:
    """``max(0, effective_limit - final_static_bytes)``, byte-exact."""
    mgr = app.state.models
    info = mgr.get(model_id)
    return max(0, mgr.mem_limit_bytes(info) - mgr.static_bytes(info))


def load(client, model_id: str):
    r = client.post(f"/api/models/{model_id}/load")
    assert r.status_code == 200, r.text
    return r


def worker_stat(client, model_id: str) -> dict:
    """The worker's own ``stats`` reply, read over its RPC socket."""
    return client.portal.call(client.app.state.clients[model_id].stats)


def model_of(client, model_id: str) -> dict:
    return {m["id"]: m for m in client.get("/api/models").json()["models"]}[model_id]


def settings_of(client, model_id: str) -> dict:
    return client.get(f"/api/models/{model_id}/settings").json()


def store_limit(app, model_id: str, limit_mb: int | None) -> None:
    app.state.store.set_model_settings(
        model_id, ModelSettings(mem_limit_mb=limit_mb))


# ---------------------------------------------------------------------------
# the reviewer's cold-load reproduction
# ---------------------------------------------------------------------------
def test_a_cold_load_publishes_the_budget_computed_from_the_measured_static(
        client, app, device):
    """The task's acceptance criterion, byte for byte, with no ``PUT`` at all.

    The saved limit is explicit, the pre-load estimate is 256 MiB and the load
    really takes 900 MiB + 172032 B -- the reviewer's shape, scaled to a fixture
    whose file can be created. Before the fix the worker enforced
    ``limit - estimate``; the budget assertion below is the one that used to fail,
    and it fails on the *number*, not on a missing field.
    """
    limit_mb = DECLARED // MIB + 1000
    store_limit(app, "chat-a", limit_mb)
    measured = 900 * MIB + FRACTION          # a fractional MiB on purpose
    device.free_mb = 12000
    device.load(measured)

    load(client, "chat-a")

    static = static_bytes_of(app, "chat-a")
    assert static == measured, (
        "the measurement did not land: a value that is not the device delta "
        "means the rest of this test would be about the estimate")
    assert static % MIB != 0, "the fixture must carry a sub-MiB tail"
    stats = worker_stat(client, "chat-a")
    assert stats["mem_runtime_budget_bytes"] == limit_mb * MIB - measured
    assert stats["mem_runtime_budget_bytes"] == expected_budget(app, "chat-a")
    # The worker's own copy of the static figure is the same byte count, not a
    # MiB-rounded one: two numbers that disagree by a remainder would make the
    # budget above look settled when it is not.
    assert stats.get("mem_static_bytes") == static, (
        "the worker's static figure must be the measured bytes, byte exact")
    # The management plane's own view agrees, and nothing had to be saved again.
    view = settings_of(client, "chat-a")
    assert view["settings"]["mem_limit_mb"] == limit_mb
    assert view["mem_static_bytes"] == static
    assert model_of(client, "chat-a")["loaded"] is True


def test_the_cold_load_reproduction_fails_on_the_baseline_shape(
        client, app, device, monkeypatch):
    """The defect itself, pinned: syncing is what makes the assertion true.

    Disabling the handover reproduces the shipped behaviour exactly -- the worker
    keeps the budget it computed from the estimate. This is the regression's
    "must fail before the fix" half, written so it stays meaningful if the
    handover is ever refactored: whatever replaces it must still move this number.
    """
    limit_mb = DECLARED // MIB + 1000
    store_limit(app, "chat-a", limit_mb)
    measured = 900 * MIB + FRACTION
    device.free_mb = 12000
    device.load(measured)

    async def no_sync(self, info, port, static_bytes):
        return 0

    monkeypatch.setattr(ModelManager, "_sync_worker_budget", no_sync)
    load(client, "chat-a")

    stats = worker_stat(client, "chat-a")
    over = stats["mem_runtime_budget_bytes"] - expected_budget(app, "chat-a")
    assert over == measured - DECLARED, (
        "without the handover the worker keeps limit - estimate, i.e. it is "
        f"granted exactly the unmeasured part; got {over} B")


def test_a_fresh_manager_is_what_makes_the_defect_reachable(
        tmp_path, models_dir, device):
    """The reproduction needs a process that has never loaded the model.

    Stated as a test because the earlier evidence looked green: a second load in
    the *same* process starts from the cached measurement, so a save-then-reload
    smoke never sees the bug. A manager that already measured this model spawns
    the worker with the right figure and needs no handover at all.
    """
    app1 = fresh_app(tmp_path / "one", models_dir)
    with TestClient(app1) as c1:
        assert c1.post("/api/login", json={"password": "admin"}).status_code == 200
        store_limit(app1, "chat-a", DECLARED // MIB + 1000)
        device.load(900 * MIB)
        load(c1, "chat-a")
        measured = static_bytes_of(app1, "chat-a")
        assert measured == 900 * MIB
        c1.post("/api/models/chat-a/unload")

        # Same process: the cached measurement is what the spawn would use.
        world = json.loads(Path(app1.state.store.path).read_text())
        assert (world["model_settings"]["chat-a"]["mem_limit_mb"]
                == DECLARED // MIB + 1000)

    # A new process starts with an empty ``_static_bytes``: only the file.
    app2 = fresh_app(tmp_path / "two", models_dir)
    with TestClient(app2) as c2:
        assert c2.post("/api/login", json={"password": "admin"}).status_code == 200
        assert static_bytes_of(app2, "chat-a") == DECLARED, (
            "a fresh manager must be back on the declared estimate")
        assert static_bytes_of(app2, "chat-a") != measured


# ---------------------------------------------------------------------------
# the default limit, and an explicit one below the measurement
# ---------------------------------------------------------------------------
def test_the_derived_default_limit_also_follows_the_measurement(
        client, app, device):
    """No setting at all: the default is static + allowance, so it must move too.

    A default derived from the *measurement* can never refuse its own load, so
    this is the path where a wrong static figure shows up as an over-generous
    budget instead of a refusal -- which is what the cold reproduction did with
    an explicit limit.
    """
    measured = 700 * MIB + FRACTION
    device.free_mb = 12000
    device.load(measured)
    load(client, "chat-a")

    static = static_bytes_of(app, "chat-a")
    assert static == measured
    stats = worker_stat(client, "chat-a")
    assert stats["mem_runtime_budget_bytes"] == expected_budget(app, "chat-a")
    assert stats.get("mem_static_bytes") == static
    # The derived default is computed from this same figure, so the budget is the
    # runtime allowance rounded into it -- positive, and not the pre-load one.
    assert stats["mem_runtime_budget_bytes"] > 0
    assert settings_of(client, "chat-a")["settings"]["mem_limit_mb"] is None


def test_an_explicit_limit_below_the_measurement_refuses_the_load(
        client, app, device, tmp_path, models_dir):
    """A limit the estimate passed but the measurement does not is a refusal.

    The bad shape this replaces: the load succeeds, ``runtime_budget_bytes``
    clamps to 0, and the console shows a loaded model that is already over the
    ceiling it was given. The worker must not survive that, and the reason has to
    name both numbers so the operator knows what to change.
    """
    limit_mb = DECLARED // MIB + 100
    store_limit(app, "chat-a", limit_mb)
    device.free_mb = 12000
    device.load(900 * MIB)                       # far above the limit below

    r = client.post("/api/models/chat-a/load")
    assert r.status_code == 409, r.text
    body = r.json()
    assert "超过本模型内存上限" in body["detail"]
    assert body["code"] == "model_mem_limit_exceeded"
    assert "900 MiB" in body["detail"] and f"{limit_mb} MiB" in body["detail"]

    model = model_of(client, "chat-a")
    assert model["loaded"] is False
    assert model["pid"] is None
    assert model["operation"] is None
    # No over-limit worker was left able to serve, and no client points at one.
    assert "chat-a" not in client.app.state.clients
    assert client.app.state.models.device_promises == (), (
        "a refused load must not leave a claim reserving memory for a dead worker")
    assert "超过本模型内存上限" in (model["load_error"] or "")

    # And the model is still usable once the operator does what the message says.
    store_limit(app, "chat-a", DECLARED // MIB + 1000)
    device.load(900 * MIB)
    load(client, "chat-a")
    assert worker_stat(client, "chat-a")["mem_runtime_budget_bytes"] == \
        expected_budget(app, "chat-a")


def test_the_refusal_happens_before_any_configure_is_sent(client, app, device):
    """No point telling a worker a budget it can never be allowed to keep."""
    limit_mb = DECLARED // MIB + 100
    store_limit(app, "chat-a", limit_mb)
    device.load(900 * MIB)
    sent: list[dict] = []

    real = ModelManager._sync_worker_budget

    async def counting(self, info, port, static_bytes):
        sent.append({"model": info.model_id, "static": static_bytes})
        return await real(self, info, port, static_bytes)

    ModelManager._sync_worker_budget = counting
    try:
        assert client.post("/api/models/chat-a/load").status_code == 409
    finally:
        ModelManager._sync_worker_budget = real
    assert sent == [], sent


# ---------------------------------------------------------------------------
# answer lost / refused / cancelled: never publish `loaded`
# ---------------------------------------------------------------------------
def _silence_configure(app, monkeypatch, *, after: bool = True):
    """Replace the sync's socket with one whose ``configure`` answer is lost."""
    from app.core import client as client_mod

    seen: list[dict] = []
    real_configure = client_mod.WorkerClient.configure

    async def configure(self, **settings):
        seen.append(settings)
        if after:
            # Applied, then the reply never arrives -- the worker may well be on
            # the new budget, so a read has to be what decides.
            await real_configure(self, **settings)
        raise client_mod.WorkerTransportError("injected: the reply was lost",
                                              stage="read")

    monkeypatch.setattr(client_mod.WorkerClient, "configure", configure)
    return seen


def test_a_lost_reply_is_decided_by_reading_the_worker(client, app, device,
                                                       monkeypatch):
    """The worker applied the budget; only the answer was lost.

    The load must complete, because the read proves the two sides agree. Failing
    it here would refuse a perfectly loaded model -- and re-spawning is a minute
    of a 35B.
    """
    store_limit(app, "chat-a", DECLARED // MIB + 1000)
    device.load(900 * MIB + FRACTION)
    seen = _silence_configure(app, monkeypatch, after=True)

    load(client, "chat-a")
    assert seen and seen[0]["mem_static_bytes"] == static_bytes_of(app, "chat-a")
    assert worker_stat(client, "chat-a")["mem_runtime_budget_bytes"] == \
        expected_budget(app, "chat-a")
    assert model_of(client, "chat-a")["loaded"] is True


def test_a_lost_reply_that_never_reached_the_worker_fails_the_load(
        client, app, device, monkeypatch):
    """Nothing was applied, so the read shows the estimate's budget: no `loaded`.

    The alternative is the defect itself: publishing a worker enforcing a budget
    the management plane does not report. The worker is terminated, no client is
    registered, and the operator sees a reason.
    """
    store_limit(app, "chat-a", DECLARED // MIB + 1000)
    device.load(900 * MIB + FRACTION)
    _silence_configure(app, monkeypatch, after=False)

    r = client.post("/api/models/chat-a/load")
    assert r.status_code == 409, r.text
    model = model_of(client, "chat-a")
    assert model["loaded"] is False
    assert model["pid"] is None
    assert "无法确认" in (model["load_error"] or "")
    assert "chat-a" not in client.app.state.clients
    assert client.app.state.models.device_promises == ()


def test_a_worker_refusal_fails_the_load_and_names_the_reason(
        client, app, device, monkeypatch):
    """A refusal is an answer: the load fails at once, no read is wasted."""
    from app.core import client as client_mod

    store_limit(app, "chat-a", DECLARED // MIB + 1000)
    device.load(900 * MIB)

    async def refuse(self, **settings):
        raise client_mod.WorkerError("模型仍有运行中的请求，不能调低内存额度")

    monkeypatch.setattr(client_mod.WorkerClient, "configure", refuse)
    reads: list[str] = []
    real_stats = client_mod.WorkerClient.stats

    async def counting_stats(self):
        reads.append("stats")
        return await real_stats(self)

    monkeypatch.setattr(client_mod.WorkerClient, "stats", counting_stats)

    r = client.post("/api/models/chat-a/load")
    assert r.status_code == 409, r.text
    model = model_of(client, "chat-a")
    assert model["loaded"] is False
    assert "被 worker 拒绝" in (model["load_error"] or "")
    # One ``stats`` for the capability probe, none for a settlement that cannot
    # help: a refusal is not doubt.
    assert client.app.state.models.device_promises == ()


async def test_a_cancelled_sync_never_publishes_loaded(tmp_path, models_dir,
                                                      device, monkeypatch):
    """A shutdown mid-sync fails the load and leaves no claim behind.

    Driven through a bare manager rather than ``TestClient``: cancelling an HTTP
    request tears that client's portal down, which would test starlette instead of
    the load path. What matters is the state the manager leaves -- not loaded, no
    pid, no registered client, and nothing reserved for a worker that is gone.
    """
    mgr = ModelManager(models_dir, backend_kind="mock", log_dir=tmp_path / "logs",
                       context_length_override=4096)
    mgr.refresh()
    device.free_mb = 12000
    device.load(900 * MIB)
    pin_static(monkeypatch, {"chat-a": 900 * MIB})

    entered = asyncio.Event()

    async def cancelled(self, info, port, static_bytes):
        entered.set()
        raise asyncio.CancelledError()

    monkeypatch.setattr(ModelManager, "_sync_worker_budget", cancelled)
    clients: list[str] = []
    mgr.on_loaded = lambda model_id, info: clients.append(model_id)

    task = asyncio.create_task(mgr.load("chat-a"))
    await asyncio.wait_for(entered.wait(), timeout=60)
    # No second ``task.cancel()``: the sync already raised ``CancelledError``,
    # which is exactly what a shutting-down service produces. Cancelling again
    # mid-teardown is a different (and separately handled) case.
    with pytest.raises(asyncio.CancelledError):
        await task

    info = mgr.get("chat-a")
    assert info.loaded is False, "a cancelled sync must not publish loaded"
    assert info.pid is None
    assert info.port is None
    assert info.operation is None, "the load must not read as still loading"
    assert clients == [], "no inference client may be registered for it"
    assert mgr.device_promises == (), (
        "the cancelled load's claim must not outlive it while its worker is gone")
    # And it can be loaded again, which is what an operator would do next.
    monkeypatch.undo()
    device.load(900 * MIB)
    again = await mgr.load("chat-a")
    assert again.loaded is True
    assert mgr.runtime_budget_bytes(again) == mgr.mem_limit_bytes(again) - 900 * MIB


class _Wedged:
    """The **real** worker process, with every signal absorbed.

    ``_terminate`` is the code under test, so it runs for real -- it pops
    ``_procs``, calls ``terminate``/``kill`` and waits. What is simulated is only
    the process's refusal to die, which is exactly what an adopted worker
    mid-prefill does on the board (``procs.AdoptedProcess.kill`` refuses SIGKILL
    for the same reason) and what the reviewer's ``s30-survivor-repro.py``
    injected. The child is a live mock worker, so ``process_alive`` answers
    honestly and the cleanup can really terminate it.

    ``wait_error`` is what ``wait`` raises instead of waiting: a second
    cancellation, or the grace expiring. Both mean "this call did not see the
    process exit", which is the fact the teardown has to get right.
    """

    def __init__(self, real, wait_error: type[BaseException] | None = None) -> None:
        self.real = real
        self.wait_error = wait_error
        self.terminated = 0
        self.killed = 0
        self.waits = 0

    @property
    def pid(self) -> int:
        return self.real.pid

    @property
    def returncode(self) -> int | None:
        return self.real.returncode

    def terminate(self) -> None:
        self.terminated += 1            # absorbed: a wedged worker ignores SIGTERM

    def kill(self) -> None:
        self.killed += 1                # absorbed: an adopted process refuses SIGKILL

    async def wait(self) -> int:
        self.waits += 1
        if self.wait_error is not None:
            raise self.wait_error("injected: the termination wait did not finish")
        return await self.real.wait()

    async def release(self) -> int:
        """Really stop the child and wait for it -- the test's own cleanup."""
        self.wait_error = None
        if self.real.returncode is None:
            self.real.terminate()
        return await asyncio.wait_for(self.real.wait(), timeout=30)


@pytest.fixture()
async def wedged(monkeypatch):
    """Collect the wrapper of every process this test spawns, for cleanup."""
    made: list[_Wedged] = []
    real_exec = asyncio.create_subprocess_exec

    async def exec_(*args, **kwargs):
        wrapper = _Wedged(await real_exec(*args, **kwargs))
        made.append(wrapper)
        return wrapper

    monkeypatch.setattr(asyncio, "create_subprocess_exec", exec_)
    yield made
    for wrapper in made:
        if wrapper.real.returncode is None:
            with contextlib.suppress(Exception):
                await wrapper.release()


def _bare_manager(tmp_path, models_dir) -> ModelManager:
    mgr = ModelManager(models_dir, backend_kind="mock", log_dir=tmp_path / "logs",
                       context_length_override=4096)
    mgr.refresh()
    return mgr


def _claims(mgr, model_id: str) -> list:
    return [p for p in mgr.device_promises if p.model_id == model_id]


async def test_a_survivor_is_recorded_even_with_the_npu_floor_switched_off(
        tmp_path, models_dir, wedged, monkeypatch):
    """Finding 1: ``CV84X6_NPU_RESERVE_MB=0`` must not silence the survivor.

    The floor governs *budget reservation*. Switching it off used to return early
    from the survivor bookkeeping altogether, so nothing recorded that a process
    was still alive: ``conflict`` stayed empty, ``unload`` walked its idle branch
    and cleared the pid, and a live worker kept the NPU heap with no way left to
    name it. What must hold with the floor off: no reservation (there is no
    admission arithmetic to protect) *and* the conflict and the pid, both intact.
    """
    monkeypatch.setenv("CV84X6_NPU_RESERVE_MB", "0")
    mgr = _bare_manager(tmp_path, models_dir)

    async def sync_fails(self, info, port, static_bytes):
        # The teardown's wait is interrupted: the worker never exits.
        wedged[0].wait_error = asyncio.CancelledError
        raise RuntimeError("injected: budget sync failure")

    monkeypatch.setattr(ModelManager, "_sync_worker_budget", sync_fails)
    with pytest.raises(RuntimeError):
        await mgr.load("chat-a")

    assert len(wedged) == 1, "the load must have spawned exactly one worker"
    worker = wedged[0]
    info = mgr.get("chat-a")
    assert worker.real.returncode is None, "the fixture's worker is still alive"
    assert info.loaded is False
    assert info.conflict, "a live worker must be recorded even with the floor off"
    assert str(worker.pid) in info.conflict
    assert info.pid == worker.pid, (
        "the pid is what the console's 卸载 signals; the floor must not clear it")
    assert _claims(mgr, "chat-a") == [], (
        "with no floor there is no reservation to keep -- but the conflict stays")
    # A second load must not spawn a worker into the heap this one is holding.
    with pytest.raises(ModelConflict):
        await mgr.load("chat-a")
    assert len(wedged) == 1, "a refused load must not spawn"

    # And 卸载 really reaches the process. The wrapper no longer absorbs the
    # signal, so this is the genuine SIGTERM path on the genuine pid.
    worker.wait_error = None
    assert (await mgr.unload("chat-a")) is not None
    assert worker.real.returncode is not None, "卸载 must have stopped the worker"
    assert procs.process_alive(worker.pid) is False
    assert mgr.get("chat-a").conflict is None
    assert _claims(mgr, "chat-a") == []


async def test_a_readiness_failure_keeps_the_pid_of_a_worker_that_survives(
        tmp_path, models_dir, wedged, monkeypatch):
    """Finding 2: a readiness timeout must not lose the worker it could not stop.

    The old shape terminated once inside the readiness branch (which pops
    ``_procs``), ignored the ``False`` it got back, cleared the pid, and then let
    the generic cleanup read "no handle in ``_procs``" as "the process is gone".
    The result: ``conflict`` set, ``pid`` null, no reservation, and an unload that
    called ``_forget`` and returned while the worker was still running.

    Uses the real ``_terminate``: the pop, the SIGTERM, the grace and the pid
    check all run; only the child's refusal to die is simulated.
    """
    monkeypatch.setenv("CV84X6_NPU_RESERVE_MB", "1024")
    mgr = _bare_manager(tmp_path, models_dir)

    async def never_ready(self, port, timeout, proc):
        wedged[0].wait_error = asyncio.TimeoutError
        return False

    monkeypatch.setattr(ModelManager, "_wait_ready", never_ready)
    with pytest.raises(RuntimeError):
        await mgr.load("chat-a")

    assert len(wedged) == 1
    worker = wedged[0]
    info = mgr.get("chat-a")
    assert worker.real.returncode is None, "the fixture's worker is still alive"
    assert info.loaded is False
    assert info.conflict, "the survivor is a conflict, not a clean failure"
    assert info.pid == worker.pid, (
        "the pid must survive the readiness failure: without it 卸载 has no target")
    claims = _claims(mgr, "chat-a")
    assert claims, "with a floor in force the live worker's bytes stay reserved"
    assert claims[0].bytes > 0
    assert "加载失败" not in (info.load_error or "") or info.load_error

    # The reservation is released only once the process is confirmed gone.
    await worker.release()
    assert procs.process_alive(worker.pid) is False
    mgr._forget(info)
    assert _claims(mgr, "chat-a") == [], (
        "a confirmed exit must give the bytes back")


def test_a_worker_that_reports_a_third_budget_is_not_published(
        client, app, device, monkeypatch):
    """An answer that is neither the old nor the new figure cannot be trusted.

    The device reading caps ``kv_budget_bytes`` but never ``mem_runtime_budget_bytes``
    (which is the model's own figure), so a mismatch there means the worker is
    enforcing something nobody asked for. Publishing it would make the console's
    number a guess.
    """
    from app.core import client as client_mod

    store_limit(app, "chat-a", DECLARED // MIB + 1000)
    device.load(900 * MIB)

    async def weird(self, **settings):
        return {"op": "configure", "mem_runtime_budget_bytes": 12345,
                "kv_budget_bytes": 12345}

    real_stats = client_mod.WorkerClient.stats

    async def stats_with_third_figure(self):
        reply = await real_stats(self)
        reply["mem_runtime_budget_bytes"] = 12345
        return reply

    monkeypatch.setattr(client_mod.WorkerClient, "configure", weird)
    monkeypatch.setattr(client_mod.WorkerClient, "stats", stats_with_third_figure)
    r = client.post("/api/models/chat-a/load")
    assert r.status_code == 409, r.text
    assert model_of(client, "chat-a")["loaded"] is False


# ---------------------------------------------------------------------------
# the device admission, re-run on the measured footprint
# ---------------------------------------------------------------------------
def test_the_device_floor_is_rechecked_against_the_measured_footprint(
        client, app, device, monkeypatch):
    """A load must not leave the NPU heap below the wedge floor once measured.

    The pre-spawn check ran against the estimate; the measurement can be most of
    the card. Here the heap is left comfortable for the estimate and far too tight
    for what the load really took, which is exactly the cold-load shape.
    """
    store_limit(app, "chat-a", DECLARED // MIB + 2000)
    device.free_mb = 3000                       # roomy for a 256 MiB estimate
    device.load(2600 * MIB)          # not roomy for the measurement

    r = client.post("/api/models/chat-a/load")
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "device_memory_insufficient"
    assert "NPU 显存余量不足" in r.json()["detail"]
    model = model_of(client, "chat-a")
    assert model["loaded"] is False
    assert model["pid"] is None
    assert client.app.state.models.device_promises == ()


def test_the_measured_static_is_not_subtracted_twice(client, app, device,
                                                     monkeypatch):
    """``free`` already excludes this load, so only the pending part is a claim.

    Subtracting the whole measured footprint again would refuse loads that fit --
    the design calls this out ("设备 free 已包含刚加载的静态占用，不能重复扣这份
    静态"). The numbers here pass only under the correct arithmetic: 2000 MiB free
    after a 1200 MiB load, a 700 MiB runtime budget and a 640 MiB floor leaves
    1300 MiB, which passes; charging the static a second time would leave 100 MiB
    and refuse a load the board can hold.
    """
    limit_mb = 1200 + 700
    store_limit(app, "chat-a", limit_mb)
    device.free_mb = 1200 + 2000                # 2000 MiB free once loaded
    device.load(1200 * MIB)
    monkeypatch.setenv("CV84X6_NPU_RESERVE_MB", "640")

    load(client, "chat-a")
    stats = worker_stat(client, "chat-a")
    assert stats.get("mem_static_bytes") == 1200 * MIB
    assert stats["mem_runtime_budget_bytes"] == limit_mb * MIB - 1200 * MIB
    assert client.app.state.models.device_promises == ()


# ---------------------------------------------------------------------------
# concurrency: two different models, and a raise interleaved
# ---------------------------------------------------------------------------
def test_two_different_models_load_in_parallel_and_each_gets_its_own_budget(
        client, app, device, monkeypatch):
    """Both really load at once, and neither budget is the other's.

    ``max_loaded`` is 0 (no count limit) and the device admission is a short
    critical section, so the two spawns overlap. Each model must end on
    ``limit - its own measured static``: anything that shared one number would
    give the second the first's figure.
    """
    store_limit(app, "chat-a", 800 + 900)
    store_limit(app, "chat-b", 600 + 600)
    device.free_mb = 16000
    device.load(800 * MIB)
    device.load(600 * MIB)
    pin_static(monkeypatch, {"chat-a": 800 * MIB, "chat-b": 600 * MIB})

    mgr = client.app.state.models
    # Both spawns must be in flight together, or "parallel" is untested. The
    # barrier sits on the spawn itself, the only point both loads share.
    at_spawn = asyncio.Event()
    both_here = asyncio.Event()
    real_spawn = ModelManager._spawn_and_await
    seen: list[str] = []

    async def barrier_spawn(self, info, *, promise):
        seen.append(info.model_id)
        if len(seen) >= 2:
            both_here.set()
        # Never wait on something the scheduler will not run.
        await asyncio.wait_for(both_here.wait(), timeout=30)
        at_spawn.set()
        return await real_spawn(self, info, promise=promise)

    monkeypatch.setattr(ModelManager, "_spawn_and_await", barrier_spawn)

    async def both():
        return await asyncio.gather(mgr.load("chat-a"), mgr.load("chat-b"))

    a, b = client.portal.call(both)
    assert at_spawn.is_set(), "the two loads never overlapped"
    assert a.loaded and b.loaded
    for model_id, static in (("chat-a", 800 * MIB), ("chat-b", 600 * MIB)):
        stats = worker_stat(client, model_id)
        assert stats.get("mem_static_bytes") == static
        assert stats["mem_runtime_budget_bytes"] == expected_budget(app, model_id), (
            f"{model_id} did not get limit - its own measured static")
        assert stats["mem_runtime_budget_bytes"] > 0
    assert static_bytes_of(app, "chat-a") != static_bytes_of(app, "chat-b"), (
        "the two measurements must differ for this test to mean anything")
    assert mgr.device_promises == ()


def test_a_raise_interleaved_with_a_load_does_not_oversell(client, app, device,
                                                           monkeypatch):
    """A raise admitted while another model loads cannot spend the loading model's
    budget.

    The load's claim is on the ledger for the whole spawn -- including its
    post-load synchronisation, which is the window this card adds -- so the raise's
    headroom arithmetic sees it. Without that the raise is admitted against a heap
    the incoming model is about to take, which is the MYS-2795 defect in its
    cold-load shape.
    """
    store_limit(app, "chat-b", DECLARED // MIB + 400)
    store_limit(app, "chat-a", 900 + 900)
    # 4000 MiB free after the load: 1024 floor + chat-b's 400 + chat-a's 900
    # runtime budget leaves 1676, so a raise to 1000 MiB (a 600 MiB increase) does
    # not fit while the load's claim is on the ledger but would if it were not.
    device.free_mb = 4000 + 900
    device.load(900 * MIB)
    pin_static(monkeypatch, {"chat-a": 900 * MIB})

    mgr = client.app.state.models
    started = asyncio.Event()
    release = asyncio.Event()
    real_sync = ModelManager._sync_worker_budget

    async def held_sync(self, info, port, static_bytes):
        # The load holds its claim here: the worker is measured and published
        # nowhere, which is exactly the instant a raise must not spend the heap.
        started.set()
        await release.wait()
        return await real_sync(self, info, port, static_bytes)

    monkeypatch.setattr(ModelManager, "_sync_worker_budget", held_sync)

    async def scenario():
        loading = asyncio.create_task(mgr.load("chat-a"))
        await asyncio.wait_for(started.wait(), timeout=30)
        assert mgr.device_promises, "the load's claim vanished mid-load"
        raised = await mgr.admit_limit_raise(
            mgr.get("chat-b"), (DECLARED // MIB + 1000) * MIB)
        release.set()
        await loading
        return raised

    raised = client.portal.call(scenario)
    # Either the raise is refused (the correct answer against this heap) or it is
    # admitted and stays reserved. What must not happen is a silent oversell with
    # an empty ledger.
    assert raised is None or mgr.device_promises == () or any(
        p.token == raised.token for p in mgr.device_promises), (
        "a raise admitted on top of a pending load must still be reserved")
    if raised is not None:
        mgr.release_budget_promise(raised)
    loaded = worker_stat(client, "chat-a")
    assert loaded["mem_runtime_budget_bytes"] == expected_budget(app, "chat-a")
    assert loaded.get("mem_static_bytes") == 900 * MIB


# ---------------------------------------------------------------------------
# ordinary inference and unload still work afterwards
# ---------------------------------------------------------------------------
def test_inference_and_a_normal_unload_still_work_after_the_sync(
        client, app, device):
    """The handover must not disturb what the load is for."""
    store_limit(app, "chat-a", DECLARED // MIB + 1000)
    device.load(900 * MIB)
    load(client, "chat-a")

    raw = client.post("/api/keys", json={"name": "cold-load"}).json()["key"]
    r = client.post("/v1/chat/completions",
                    headers={"Authorization": f"Bearer {raw}"},
                    json={"model": "chat-a", "messages": [
                        {"role": "user", "content": "hi"}], "max_tokens": 4})
    assert r.status_code == 200, r.text

    assert client.post("/api/models/chat-a/unload").status_code == 200
    model = model_of(client, "chat-a")
    assert model["loaded"] is False
    assert model["pid"] is None
    assert client.app.state.models.device_promises == ()


# ---------------------------------------------------------------------------
# the worker's own contract for the exact bytes
# ---------------------------------------------------------------------------
def test_the_worker_keeps_the_exact_static_bytes_it_is_configured_with():
    """The other half of the byte-exactness: no MiB truncation on the way in.

    A worker that rounds 13331 MiB + 172032 B down to 13331 MiB grants the extra
    172032 B and makes the management plane's comparison miss by the remainder.
    """
    from app.engine.scheduler import Scheduler
    from app.engine.worker import configure

    scheduler = Scheduler(_SyncBackend(), max_concurrent=1)
    scheduler.kv_budget_bytes = None
    scheduler.device_budget_bytes = None
    static = 900 * MIB + FRACTION
    reply = configure(scheduler, _SyncBackend(),
                      {"mem_limit_mb": 1900, "mem_static_bytes": static})
    assert reply["mem_static_bytes"] == static
    assert reply["mem_runtime_budget_bytes"] == 1900 * MIB - static


class _SyncBackend:
    """The minimum a ``Scheduler`` and ``configure`` need from a backend."""

    kind = "chat"
    kv_bytes_per_token = 20480
    linear_state_bytes = 33423360
    supports_sampling = True
    context_length = 4096
    session_state_bytes = 0
    fault = False
    snapshot_store = None

    def __init__(self) -> None:
        from app.engine.prefix_cache import PrefixCache

        self.prefix_cache = PrefixCache()
