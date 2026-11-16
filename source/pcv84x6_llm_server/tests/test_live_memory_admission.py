"""Live admission for a memory-limit raise, and the pending-budget ledger (MYS-2795).

The defect this pins is a *bypass*, not a wrong number: ``PUT
/api/models/{id}/settings`` pushed a bigger ``mem_limit_mb`` straight into the
running worker, and the worker sized its session/cache budget from
``device_budget_bytes`` -- a device reading taken at **load** time. Once any
other model has loaded or freed memory since, that number no longer describes
what the card can still promise, so a raise went through with **zero** device
checks (the reviewer's ``reproduce_live_raise.py``: free 1024 MiB, reserve
1024 MiB, budget 400 -> 1000 MiB, HTTP 200, ``device_memory`` called 0 times).

What the fix has to hold, and therefore what is asserted here:

* a raise is admitted against the **current** NPU free figure, less every
  loaded growing model's runtime budget, less the promises of operations that
  have been admitted but not yet realised, and must leave the configured floor;
* the arithmetic is **conservative**: a loaded model's already-used runtime
  bytes are *not* credited back, because ``runtime_bytes`` is a per-token
  estimate, not a physical allocation. Refusing a raise that would physically
  have fit is the accepted cost; admitting one that does not is not;
* a refusal is a 409 that changes nothing -- stored settings and the worker's
  budget both stay as they were -- and an unverifiable heap on a device backend
  is a 503 rather than a silent "space is fine";
* the promise taken at admission is handed over to the persisted state without
  a gap, and released on refusal, worker rejection, failure, and cancellation,
  so the ledger cannot leak and cannot be bypassed;
* loads and raises share **one** ledger and one short critical section, while
  the long part of a load stays unserialised: two different models must still
  load in parallel (``test_models.py`` pins that).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import monitor
from app.core.models import DeviceMemoryError, ModelManager
from app.core.state import ModelSettings
from app.main import create_app

MIB = 1 << 20
CHAT_BMODEL = "qwen3.6-35b-a3b-int4-autow4bf16"
BIG_ENOUGH = 256 * MIB
RESERVE_MB = 1024          # the default floor (CV84X6_NPU_RESERVE_MB unset)


def make_model(root: Path, name: str, bmodel: str = CHAT_BMODEL) -> Path:
    d = root / name
    (d / "config").mkdir(parents=True, exist_ok=True)
    with open(d / f"{bmodel}_seq2048_4core_static.bmodel", "wb") as fh:
        fh.truncate(BIG_ENOUGH)
    (d / "config" / "config.json").write_text("{}")
    return d


@pytest.fixture()
def models_dir(tmp_path: Path) -> Path:
    root = tmp_path / "models"
    make_model(root, "chat-a")
    make_model(root, "chat-b")
    # An auxiliary kind: its configured budget is not future allocation, so a
    # limit change on one must not be admitted against the heap at all.
    make_model(root, "embed-a", bmodel="qwen3-embedding-0.6b_bf16")
    return root


@pytest.fixture()
def app(tmp_path: Path, models_dir: Path):
    return create_app(data_dir=tmp_path / "data", models_dir=models_dir,
                      backend_kind="mock", web_dir=tmp_path / "web",
                      context_length_override=4096)


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        yield c


def load(client, *model_ids: str) -> None:
    for model_id in model_ids:
        r = client.post(f"/api/models/{model_id}/load")
        assert r.status_code == 200, r.text


def put(client, model_id: str, **body):
    return client.put(f"/api/models/{model_id}/settings", json=body)


def heap(free_mb: int, *, npu_total_mb: int = 26624) -> dict:
    """The two-heap reading ``monitor.device_memory`` returns on the board."""
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


@pytest.fixture()
def read(monkeypatch):
    """Set the device heap the admissions see; returns the setter."""
    def _set(free_mb: int) -> None:
        monkeypatch.setattr(monitor, "device_memory", lambda: heap(free_mb))
    return _set


def budget_mb(app, model_id: str) -> int:
    """The runtime budget in force for ``model_id``, in MiB."""
    mgr = app.state.models
    info = mgr.get(model_id)
    return mgr.runtime_budget_bytes(info) // MIB


def static_mb(app, model_id: str) -> int:
    mgr = app.state.models
    return mgr.static_bytes(mgr.get(model_id)) // MIB


def limit_for_budget(app, model_id: str, budget: int) -> int:
    """The ``mem_limit_mb`` that leaves exactly ``budget`` MiB of runtime room."""
    return static_mb(app, model_id) + budget


def limit_bytes_for_budget(app, model_id: str, budget: int) -> int:
    """The same figure in bytes, for the manager's own (byte-denominated) API."""
    return limit_for_budget(app, model_id, budget) * MIB


def pin_budget(app, model_id: str, budget: int) -> None:
    """Store a limit that leaves exactly ``budget`` MiB of runtime room.

    The manager's own tests need a *known* old budget to compute a claim from,
    and the derived default (384 MiB for this fixture) is not it. Written
    straight into the store: going through the API would itself be admitted.
    """
    app.state.store.set_model_settings(
        model_id, ModelSettings(mem_limit_mb=limit_for_budget(app, model_id, budget)))
    assert budget_mb(app, model_id) == budget


def pending(app) -> int:
    return len(app.state.models.device_promises)


# ---------------------------------------------------------------------------
# the reviewer's reproduction
# ---------------------------------------------------------------------------
def test_the_reviewers_live_raise_repro_is_refused(client, app, read):
    """The exact numbers from ``reproduce_live_raise.py`` / ``live-raise-repro.json``.

    Loaded model, runtime budget 400 MiB; the management plane then reads NPU
    free 1024 MiB with the reserve also 1024 MiB; the operator asks for 1000 MiB.
    It used to answer 200 and hand the worker a 1000 MiB budget having consulted
    the device zero times.
    """
    load(client, "chat-a")
    assert put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400)).status_code == 200

    read(1024)
    worker = app.state.clients["chat-a"]
    sent: list[dict] = []
    original = worker.configure

    async def counting(**kwargs):
        sent.append(kwargs)
        return await original(**kwargs)

    worker.configure = counting
    before = client.get("/api/models/chat-a/settings").json()

    r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 1000))
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "NPU 显存余量不足" in detail
    assert r.json()["code"] == "device_memory_insufficient"

    # Nothing moved: no configure reached the worker, the stored setting is the
    # old one, and the budget the manager would report is still 400 MiB.
    assert sent == [], "a refused raise must not touch the worker's budget"
    after = client.get("/api/models/chat-a/settings").json()
    assert after["settings"] == before["settings"]
    assert after["effective"]["mem_limit_bytes"] == before["effective"]["mem_limit_bytes"]
    assert budget_mb(app, "chat-a") == 400
    # And the refusal did not leave a promise behind for someone else to trip on.
    assert pending(app) == 0


def test_a_raise_that_leaves_the_floor_is_allowed(client, app, read):
    """The smallest free figure that admits 400 -> 1000 is 2024 MiB.

    ``free - own old budget (400) - the increase (600) >= floor (1024)``. The
    model's own budget is committed, not free: `free` is what bmrt reports now and
    the sessions may still grow into that 400 MiB.
    """
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    read(400 + 600 + RESERVE_MB)
    r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 1000))
    assert r.status_code == 200, r.text
    assert r.json()["applied"]["mem_runtime_budget_bytes"] == 1000 * MIB
    assert budget_mb(app, "chat-a") == 1000
    # Persisted, and the ledger handed the promise over to the stored setting.
    assert client.get("/api/models/chat-a/settings").json()["settings"]["mem_limit_mb"] \
        == limit_for_budget(app, "chat-a", 1000)
    assert pending(app) == 0


def test_the_boundary_admits_exactly_the_reserve(client, app, read):
    """``left >= reserve``: exactly the floor left is admitted, one byte less is not.

    The raise is 400 -> 1000 MiB, so the claim is the 600 MiB increase **plus**
    the model's own committed 400 MiB budget; the boundary sits at
    ``400 + 600 + 1024 = 2024`` MiB free.
    """
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))

    def reading(free_bytes: int) -> dict:
        result = heap((600 + RESERVE_MB))
        result["heaps"][0]["free_bytes"] = free_bytes
        return result

    import app.core.monitor as mod
    original = mod.device_memory
    try:
        mod.device_memory = lambda: reading((400 + 600 + RESERVE_MB) * MIB)
        assert put(client, "chat-a", mem_limit_mb=limit_for_budget(
            app, "chat-a", 1000)).status_code == 200
        assert budget_mb(app, "chat-a") == 1000
        # Down again -- a reduction is never refused -- then one byte short.
        assert put(client, "chat-a", mem_limit_mb=limit_for_budget(
            app, "chat-a", 400)).status_code == 200
        mod.device_memory = lambda: reading((400 + 600 + RESERVE_MB) * MIB - 1)
        r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 1000))
    finally:
        mod.device_memory = original
    assert r.status_code == 409, r.text
    assert budget_mb(app, "chat-a") == 400


def test_resetting_to_the_default_is_admitted_the_same_way(client, app, read):
    """``null`` computes the derived default and goes through the same gate.

    An explicit 400 MiB budget raised to the derived 512 MiB is a raise like any
    other: 112 MiB of extra promise, and it has to leave the floor.
    """
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    # Read the derived default without the explicit override in the way.
    put(client, "chat-a", mem_limit_mb=None)
    derived = budget_mb(app, "chat-a")
    assert derived > 400, "the fixture needs a default above the explicit value"
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))

    # The claim is the increase, and the model's own old budget (400) stays
    # committed, so the boundary is ``400 + difference + reserve``.
    difference = derived - 400
    boundary = 400 + difference + RESERVE_MB
    read(boundary - 1)
    r = put(client, "chat-a", mem_limit_mb=None)
    assert r.status_code == 409, r.text
    assert client.get("/api/models/chat-a/settings").json()["settings"]["mem_limit_mb"] \
        == limit_for_budget(app, "chat-a", 400)
    assert budget_mb(app, "chat-a") == 400

    read(boundary)
    r = put(client, "chat-a", mem_limit_mb=None)
    assert r.status_code == 200, r.text
    assert budget_mb(app, "chat-a") == derived
    # And it really is the derived default, not a leftover explicit value.
    assert client.get("/api/models/chat-a/settings").json()["settings"]["mem_limit_mb"] is None


def test_a_reduction_is_never_refused_for_lack_of_headroom(client, app, read):
    """Lowering frees memory; the device has nothing to say about it."""
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 900))
    read(10)   # a card with nothing left
    r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    assert r.status_code == 200, r.text
    assert budget_mb(app, "chat-a") == 400


def test_an_unloaded_model_only_stores_its_setting(client, app, read, monkeypatch):
    """Admission happens at load time; a setting on an idle model is just saved."""
    calls: list[int] = []
    monkeypatch.setattr(monitor, "device_memory",
                        lambda: calls.append(1) or heap(0))
    r = put(client, "chat-a", mem_limit_mb=1024)
    assert r.status_code == 200, r.text
    assert app.state.store.get_model_settings("chat-a").mem_limit_mb == 1024
    assert calls == [], "an idle model's setting must not be admitted against the device"


def test_an_auxiliary_models_budget_is_not_admitted_against_the_heap(client, app, read):
    """Native auxiliary engines allocate at load and never grow.

    Counting their configured budget would refuse a save on a board with plenty
    of room (the MYS-2703 RC board refused OCR at 2.5 GiB free for this reason).
    """
    load(client, "embed-a")
    read(10)
    r = put(client, "embed-a", mem_limit_mb=4096)
    assert r.status_code == 200, r.text
    assert app.state.store.get_model_settings("embed-a").mem_limit_mb == 4096


def test_the_floor_can_still_be_switched_off(client, app, read, monkeypatch):
    """``CV84X6_NPU_RESERVE_MB=0`` is the documented "this board is fine" switch."""
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    read(64)
    monkeypatch.setenv("CV84X6_NPU_RESERVE_MB", "0")
    r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 1000))
    assert r.status_code == 200, r.text
    assert budget_mb(app, "chat-a") == 1000


def test_a_device_backend_refuses_a_raise_it_cannot_verify(client, app, monkeypatch):
    """On a device backend an unreadable heap is a 503, not "space is fine".

    The mock backend keeps working without a device (every dev checkout and this
    suite), which is why the refusal is keyed on the backend rather than on the
    reading alone.
    """
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    app.state.models.backend_kind = "native"
    monkeypatch.setattr(monitor, "device_memory",
                        lambda: {"heaps": [], "total_bytes": 0, "used_bytes": 0,
                                 "free_bytes": 0, "max_block_bytes": 0,
                                 "source": "none"})
    r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 1000))
    assert r.status_code == 503, r.text
    assert r.json()["code"] == "service_unavailable"
    assert app.state.store.get_model_settings("chat-a").mem_limit_mb == \
        limit_for_budget(app, "chat-a", 400)
    assert budget_mb(app, "chat-a") == 400
    assert pending(app) == 0

    # The same reading on the mock backend is a dev checkout, not a device.
    app.state.models.backend_kind = "mock"
    r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 1000))
    assert r.status_code == 200, r.text


def test_a_worker_refusal_keeps_the_promise_out_of_the_ledger(client, app, read, monkeypatch):
    """The worker is the authority on a live reduction; its refusal releases too."""
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    read(4096)

    async def refuse(**kwargs):
        return {"error": "模型仍有运行中的请求，不能调低内存额度；请等请求结束后重试"}

    monkeypatch.setattr(app.state.clients["chat-a"], "configure", refuse)
    r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 1000))
    assert r.status_code == 409
    assert budget_mb(app, "chat-a") == 400
    assert pending(app) == 0


async def test_a_cancelled_raise_releases_its_promise(app, read):
    """A client that goes away mid-confidence must not hold memory forever."""
    mgr = app.state.models
    mgr.refresh()
    info = mgr.get("chat-a")
    info.loaded = True          # enough for admission; no worker needed
    pin_budget(app, "chat-a", 400)
    read(600 + RESERVE_MB)

    # Hold the budget lock so the admission is suspended *after* it started but
    # before it registers its claim: that is the window a cancelled request
    # occupies on the board (the client hangs up during the check), and it is
    # where a leaked promise would have to be released by the unwinding.
    await mgr._budget_lock.acquire()
    task = asyncio.create_task(mgr.admit_limit_raise(
        info, limit_bytes_for_budget(app, "chat-a", 1000)))
    await asyncio.sleep(0.05)
    assert not task.done(), "the admission did not wait for the budget lock"
    task.cancel()
    mgr._budget_lock.release()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert mgr.device_promises == (), "a cancelled admission left a promise behind"


# ---------------------------------------------------------------------------
# the ledger itself
# ---------------------------------------------------------------------------
async def test_an_admitted_promise_is_visible_to_the_next_admission(app, read):
    """Two admissions cannot both spend the same free bytes."""
    mgr = app.state.models
    mgr.refresh()
    a, b = mgr.get("chat-a"), mgr.get("chat-b")
    a.loaded = b.loaded = True
    pin_budget(app, "chat-a", 400)
    pin_budget(app, "chat-b", 400)
    a_budget = mgr.runtime_budget_bytes(a) // MIB
    b_budget = mgr.runtime_budget_bytes(b) // MIB
    # Both loaded models' budgets stay committed (a's 400 and b's 400), the first
    # raise adds 400, and the floor must survive: exactly one fits.
    read(a_budget + b_budget + 400 + RESERVE_MB)

    first = await mgr.admit_limit_raise(
        a, limit_bytes_for_budget(app, "chat-a", 800))
    assert first is not None
    # The second raise needs the same 400 MiB, which the ledger already holds.
    with pytest.raises(DeviceMemoryError):
        await mgr.admit_limit_raise(
            b, limit_bytes_for_budget(app, "chat-b", 800))
    mgr.release_budget_promise(first)
    assert mgr.device_promises == ()


async def test_a_loaded_models_used_bytes_are_not_credited_back(app, read):
    """The estimate is not a physical allocation, so it never buys a raise.

    ``runtime_bytes`` is derived from token counts; park rounding and the growth
    peak are not in it. Crediting it would admit a raise against memory the
    engine may already be holding, which is the one mistake this card must not
    make -- so a model reporting its whole budget as "used" still commits the
    whole budget, and the same raise is refused either way.
    """
    mgr = app.state.models
    mgr.refresh()
    a, b = mgr.get("chat-a"), mgr.get("chat-b")
    a.loaded = b.loaded = True
    pin_budget(app, "chat-a", 400)
    pin_budget(app, "chat-b", 400)
    b_budget = mgr.runtime_budget_bytes(b)

    async def admitted(free_mb: int) -> bool:
        read(free_mb)
        try:
            promise = await mgr.admit_limit_raise(
                a, limit_bytes_for_budget(app, "chat-a", 1000))
        except DeviceMemoryError:
            return False
        mgr.release_budget_promise(promise)
        return True

    # The raise is 400 -> 1000: the increase is 600 MiB, and both loaded models'
    # budgets stay committed (a's 400 counts too -- it is the model asking).
    a_budget = mgr.runtime_budget_bytes(a)
    boundary = (a_budget + b_budget) // MIB + 600 + RESERVE_MB
    b.runtime_bytes = 0
    assert not await admitted(boundary - 1), (
        "the 600 MiB claim plus the other model's budget must leave the floor")
    b.runtime_bytes = b_budget                      # "fully used" -- and ignored
    assert not await admitted(boundary - 1), (
        "a model's used bytes are an estimate, not credit")
    # Not a blanket refusal either: with the floor exactly left, it passes.
    assert await admitted(boundary)
    assert mgr.device_promises == ()


async def test_two_raises_that_only_fit_one_at_a_time_admit_at_most_one(app, read):
    """A controllable barrier: both arrive, only one gets through.

    Two raises of 400 -> 900 MiB against the same free figure. Each fits on its
    own; together they do not. Without the ledger the second would read the same
    free figure, see nothing committed, and be admitted -- which is the oversell.

    The barrier sits *outside* the admission, so both coroutines reach it before
    either takes the budget lock: exactly the interleaving an event loop will not
    produce on its own.
    """
    mgr = app.state.models
    mgr.refresh()
    a, b = mgr.get("chat-a"), mgr.get("chat-b")
    a.loaded = b.loaded = True
    pin_budget(app, "chat-a", 400)
    pin_budget(app, "chat-b", 400)
    # Both raises are 400 -> 900: a 500 MiB increase each, on top of both
    # models' committed 400 MiB budgets.
    claim = 900 - 400
    committed = ((mgr.runtime_budget_bytes(a) + mgr.runtime_budget_bytes(b)) // MIB)
    assert committed == 800, committed
    # One fits exactly; the pair would leave the floor short by one claim.
    read(committed + claim + RESERVE_MB)

    barrier = asyncio.Barrier(2)
    results: list = []

    async def one(info) -> None:
        await barrier.wait()
        try:
            results.append(await mgr.admit_limit_raise(
                info, limit_bytes_for_budget(app, info.model_id, 900)))
        except DeviceMemoryError as exc:
            results.append(exc)

    await asyncio.gather(one(a), one(b))
    admitted = [r for r in results if r is not None and not isinstance(r, Exception)]
    refused = [r for r in results if isinstance(r, DeviceMemoryError)]
    assert len(admitted) == 1, results
    assert len(refused) == 1, results
    for promise in admitted:
        mgr.release_budget_promise(promise)
    assert mgr.device_promises == ()


async def test_two_raises_that_both_fit_both_succeed(app, read):
    """The ledger must not over-refuse: one MiB more and the pair fits."""
    mgr = app.state.models
    mgr.refresh()
    a, b = mgr.get("chat-a"), mgr.get("chat-b")
    a.loaded = b.loaded = True
    pin_budget(app, "chat-a", 400)
    pin_budget(app, "chat-b", 400)
    claim = 900 - 400
    committed = ((mgr.runtime_budget_bytes(a) + mgr.runtime_budget_bytes(b)) // MIB)
    read(committed + 2 * claim + RESERVE_MB)

    promises = await asyncio.gather(
        mgr.admit_limit_raise(a, limit_bytes_for_budget(app, "chat-a", 900)),
        mgr.admit_limit_raise(b, limit_bytes_for_budget(app, "chat-b", 900)))
    assert all(p is not None for p in promises), promises
    for promise in promises:
        mgr.release_budget_promise(promise)
    assert mgr.device_promises == ()


async def test_an_in_flight_load_holds_its_promise_until_it_finishes(tmp_path, read):
    """A load in flight is a commitment, not free memory.

    The spawn takes tens of seconds on the board; anything admitted during it
    would be admitted against memory the loading worker is about to take.
    """
    root = tmp_path / "models"
    make_model(root, "chat-a")
    make_model(root, "chat-b")
    mgr = ModelManager(root, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()
    footprint = (mgr.static_bytes(mgr.get("chat-b"))
                 + mgr.runtime_budget_bytes(mgr.get("chat-b"))) // MIB
    read(footprint + RESERVE_MB)

    loading = asyncio.create_task(mgr.load("chat-a"))
    # Wait until the load's promise is registered, then ask for the same money
    # for a second model.
    for _ in range(3000):
        if mgr.device_promises:
            break
        await asyncio.sleep(0.01)
    assert mgr.device_promises, "the load registered no promise"
    with pytest.raises(DeviceMemoryError):
        await mgr.load("chat-b")
    await loading
    assert mgr.get("chat-a").loaded is True
    assert mgr.device_promises == (), "a finished load left its promise behind"
    await mgr.unload_all()


async def test_a_failed_load_releases_its_promise(tmp_path, read, monkeypatch):
    """A load that dies in the spawn must not keep the memory reserved."""
    root = tmp_path / "models"
    make_model(root, "chat-a")
    mgr = ModelManager(root, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()
    read(8192)

    async def refuse(*args, **kwargs):
        raise OSError("no such binary")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse)

    with pytest.raises(Exception):
        await mgr.load("chat-a")
    assert mgr.device_promises == ()


async def test_a_promise_is_released_on_a_load_that_never_becomes_ready(tmp_path, read):
    """The 300 s readiness timeout path unwinds through the same release."""
    root = tmp_path / "models"
    make_model(root, "chat-a")
    mgr = ModelManager(root, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()
    read(8192)

    async def never_ready(port, timeout, proc):
        return False

    mgr._wait_ready = never_ready      # type: ignore[assignment]

    try:
        with pytest.raises(Exception):
            await mgr.load("chat-a")
        assert mgr.device_promises == ()
    finally:
        await mgr.unload_all()


# ---------------------------------------------------------------------------
# load and raise interleaved
# ---------------------------------------------------------------------------
async def test_a_raise_while_another_model_is_loading_is_refused(app, read):
    """The two paths share one ledger, so a load in flight blocks a raise.

    A load holds its promise for the whole spawn. A raise that only fits if that
    memory is counted as free must be refused, and it must be refused *while* the
    load is still running -- not after, when the device reading would say so
    anyway.
    """
    mgr = app.state.models
    mgr.refresh()
    a, b = mgr.get("chat-a"), mgr.get("chat-b")
    a.loaded = True
    # b's footprint is what the in-flight load will take.
    b_claim = (mgr.static_bytes(b) + mgr.runtime_budget_bytes(b)) // MIB
    a_budget = mgr.runtime_budget_bytes(a) // MIB
    read(b_claim + a_budget + RESERVE_MB)     # room for exactly one of them

    loading = asyncio.create_task(mgr.load("chat-b"))
    for _ in range(3000):
        if mgr.device_promises:
            break
        await asyncio.sleep(0.01)
    assert mgr.device_promises, "the load registered no promise"
    # The raise would need its own budget *plus* b's claim, which the load is
    # holding. Without the shared ledger it is admitted.
    with pytest.raises(DeviceMemoryError):
        await mgr.admit_limit_raise(a, a_budget * MIB + b_claim * MIB
                                    + RESERVE_MB * MIB + 1)
    await loading
    assert mgr.device_promises == (), "a finished load left its promise behind"
    assert mgr.get("chat-b").loaded is True
    await mgr.unload_all()


async def test_a_load_is_refused_while_a_raise_is_in_flight(client, app, read, monkeypatch):
    """The reverse order: a raise's promise is held across the worker handshake."""
    mgr = app.state.models
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    worker = app.state.clients["chat-a"]
    original = worker.configure
    seen: list[int] = []

    async def slow(**kwargs):
        # The promise must still be registered while this awaits: until the
        # setting is stored, the ledger is the only thing carrying the claim.
        seen.append(len(mgr.device_promises))
        await asyncio.sleep(0.5)
        return await original(**kwargs)

    monkeypatch.setattr(worker, "configure", slow)
    # Room for the raise's 500 MiB increase on top of chat-a's own committed
    # 400 MiB budget, with the floor left over -- and nothing like enough for
    # chat-b's whole footprint on top.
    read(400 + 500 + RESERVE_MB)
    b_claim = (mgr.static_bytes(mgr.get("chat-b"))
               + mgr.runtime_budget_bytes(mgr.get("chat-b"))) // MIB
    assert b_claim > 500, "otherwise the refusal below proves nothing"

    raising = asyncio.create_task(put_async(
        client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 900)))
    for _ in range(600):
        if mgr.device_promises:
            break
        await asyncio.sleep(0.01)
    assert mgr.device_promises, "the raise registered no promise"
    with pytest.raises(DeviceMemoryError):
        await mgr.load("chat-b")
    await raising

    assert seen and seen[0] == 1, "the promise must be held across the handshake"
    assert mgr.device_promises == ()
    assert budget_mb(app, "chat-a") == 900
    assert mgr.get("chat-b").loaded is False


def test_a_load_that_does_not_fit_is_refused_before_the_spawn(client, app, read, monkeypatch):
    """The pre-existing load check still runs, and still refuses. Pinned here because
    the admission moved inside a lock."""
    mgr = app.state.models
    client.post("/api/models/chat-a/unload")
    read(10)
    r = client.post("/api/models/chat-a/load")
    assert r.status_code == 409, r.text
    assert "NPU 显存余量不足" in r.json()["detail"]
    assert mgr.device_promises == ()


async def put_async(client, model_id: str, **body):
    """Run the sync TestClient call off the loop so it can overlap."""
    return await asyncio.to_thread(
        client.put, f"/api/models/{model_id}/settings", json=body)


# ---------------------------------------------------------------------------
# 首轮验收的三个缺口（`9d5d033` 的回归）
# ---------------------------------------------------------------------------
def test_the_models_own_budget_is_not_excluded_from_the_raise(client, app, read):
    """Severity-1 defect of the first review: the asker's own budget must count.

    ``free - own old budget - increase >= floor``. With 1624 MiB free, a 400 MiB
    budget raised to 1000 leaves 624 MiB -- inside the measured wedge band -- so
    it must be refused. The first version passed ``exclude=<the model asking>``
    and admitted it (HTTP 200, worker at 1000 MiB), which is the defect this pins.
    """
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    read(1624)
    r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 1000))
    assert r.status_code == 409, r.text
    assert "NPU 显存余量不足" in r.json()["detail"]
    assert budget_mb(app, "chat-a") == 400
    assert pending(app) == 0
    # And the boundary really is 2024, not 1624.
    read(400 + 600 + RESERVE_MB - 1)
    assert put(client, "chat-a",
               mem_limit_mb=limit_for_budget(app, "chat-a", 1000)).status_code == 409
    read(400 + 600 + RESERVE_MB)
    assert put(client, "chat-a",
               mem_limit_mb=limit_for_budget(app, "chat-a", 1000)).status_code == 200


def test_the_old_budget_counts_even_before_it_is_physically_allocated(app, read):
    """The budget is a promise, not a measurement.

    A raise is admitted against what the model *may* allocate, so a model whose
    sessions have not grown into its budget yet still holds that memory on the
    ledger. ``runtime_bytes == 0`` must change nothing.
    """
    mgr = app.state.models
    mgr.refresh()
    a = mgr.get("chat-a")
    a.loaded = True
    a.runtime_bytes = 0
    pin_budget(app, "chat-a", 400)
    read(1624)

    async def scenario() -> None:
        with pytest.raises(DeviceMemoryError):
            await mgr.admit_limit_raise(
                a, limit_bytes_for_budget(app, "chat-a", 1000))

    asyncio.run(scenario())
    assert mgr.device_promises == ()


async def test_two_auxiliary_loads_cannot_share_one_footprint(tmp_path, read):
    """Severity-2 defect of the first review: an auxiliary load needs a claim.

    "It does not grow after loading" is true and irrelevant -- it still allocates
    its whole footprint *while* loading, so two of them in flight at once must not
    both be admitted against the same free figure. 1536 MiB free, two 512 MiB
    footprints, a 1024 MiB floor: the pair would leave 512 MiB.

    The first spawn is held open deliberately, which is the only way to make the
    interleaving deterministic; the real thing is two consoles clicking load at
    the same second.
    """
    root = tmp_path / "models"
    make_model(root, "embed-a", bmodel="qwen3-embedding-0.6b_bf16")
    make_model(root, "embed-b", bmodel="qwen3-embedding-0.6b_bf16")
    mgr = ModelManager(root, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()
    a, b = mgr.get("embed-a"), mgr.get("embed-b")
    assert a.kind == "embedding" and b.kind == "embedding"
    claim_mb = mgr._declared_claim_bytes(a) // MIB
    assert claim_mb == mgr._declared_claim_bytes(b) // MIB, "fixtures must match"
    assert claim_mb > 0, "the fixture has no footprint; the subtraction is untested"
    # Room for exactly one claim plus the floor -- the pair cannot both fit.
    read(claim_mb + RESERVE_MB)

    started = asyncio.Event()
    release = asyncio.Event()
    ledger_at_spawn: list[int] = []

    async def held_spawn(info, *, promise):
        ledger_at_spawn.append(len(mgr.device_promises))
        started.set()
        await release.wait()
        info.loaded = True
        mgr.release_budget_promise(promise)
        return info

    mgr._spawn_and_await = held_spawn       # type: ignore[assignment]
    first = asyncio.create_task(mgr.load("embed-a"))
    await asyncio.wait_for(started.wait(), timeout=10)
    # The first load's claim is on the ledger while its spawn runs -- that is
    # what the second admission has to see.
    assert ledger_at_spawn == [1], ledger_at_spawn
    with pytest.raises(DeviceMemoryError):
        await mgr.load("embed-b")
    release.set()
    loaded = await first
    assert loaded.loaded is True
    assert mgr.device_promises == (), "the finished aux load kept its claim"


async def test_an_auxiliary_load_releases_its_claim_when_it_finishes(tmp_path, read):
    """Auxiliary claims are for the load window only -- nothing is left behind.

    Unlike a growing kind, an auxiliary engine allocates everything at load and
    never grows, so once it is loaded its footprint is described by ``loaded`` and
    the check's own static + headroom rule. Keeping a runtime claim as well would
    double-count it forever and refuse loads that fit today.
    """
    root = tmp_path / "models"
    make_model(root, "embed-a", bmodel="qwen3-embedding-0.6b_bf16")
    mgr = ModelManager(root, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()
    read(8192)

    seen: list[int] = []

    async def blocked_spawn(info, *, promise):
        seen.append(len(mgr.device_promises))
        info.loaded = True
        mgr.release_budget_promise(promise)
        return info

    mgr._spawn_and_await = blocked_spawn        # type: ignore[assignment]
    info = await mgr.load("embed-a")
    assert info.loaded is True
    assert seen == [1], "the claim must exist while the spawn runs"
    assert mgr.device_promises == (), (
        "an auxiliary load must not leave a runtime claim behind")


async def test_a_failed_auxiliary_load_releases_its_claim(tmp_path, read, monkeypatch):
    root = tmp_path / "models"
    make_model(root, "embed-a", bmodel="qwen3-embedding-0.6b_bf16")
    mgr = ModelManager(root, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()
    read(8192)

    async def refuse(*args, **kwargs):
        raise OSError("no such binary")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse)
    with pytest.raises(Exception):
        await mgr.load("embed-a")
    assert mgr.device_promises == ()


async def test_an_auxiliary_load_blocks_a_raise(app, read, tmp_path):
    """The reverse interleaving, with the auxiliary's claim as the blocker."""
    root = tmp_path / "models"
    make_model(root, "embed-a", bmodel="qwen3-embedding-0.6b_bf16")
    make_model(root, "chat-a")
    mgr = ModelManager(root, backend_kind="mock", log_dir=tmp_path / "logs",
                       context_length_override=4096)
    # A local store: ``pin_budget`` writes through the *app*'s, which this
    # manager does not consult.
    from app.core.state import ModelSettings
    entry = ModelSettings()
    records = {"chat-a": entry}
    mgr.model_settings = lambda mid: records.get(mid, ModelSettings())
    mgr.refresh()
    chat = mgr.get("chat-a")
    chat.loaded = True
    static_mb = mgr.static_bytes(chat) // MIB
    entry.mem_limit_mb = static_mb + 400
    assert mgr.runtime_budget_bytes(chat) // MIB == 400
    # Exactly enough for the raise and the floor **without** the loading
    # embedding's claim; one MiB less, because that claim is the whole point.
    read(mgr._declared_claim_bytes(mgr.get("embed-a")) // MIB
         + 400 + 500 + RESERVE_MB)

    loading = asyncio.create_task(mgr.load("embed-a"))
    for _ in range(600):
        if mgr.device_promises:
            break
        await asyncio.sleep(0.01)
    assert mgr.device_promises, "the auxiliary load registered no claim"
    # The raise needs 400 (its own budget) + 500 (the increase) + floor, and the
    # loading embedding is holding a claim on top of that.
    # Exactly these bytes would fit if the embedding were not loading; its claim
    # is what makes it not fit.
    with pytest.raises(DeviceMemoryError):
        await mgr.admit_limit_raise(chat, (static_mb + 901) * MIB)
    await loading
    assert mgr.device_promises == ()


# ---------------------------------------------------------------------------
# 确认丢失（首轮验收的第 3 个缺口）
# ---------------------------------------------------------------------------
def _lose_reply(worker, *, applied: bool = True):
    """Make ``configure`` behave like a reply lost after the worker answered.

    ``applied=True`` is the dangerous shape: the worker *did* apply the new
    budget and only the reply never arrived. The old code read that as a refusal
    and released the claim, so the API reported "409, nothing changed" while the
    worker ran at the new budget.
    """
    original = worker.configure
    calls: list[dict] = []

    async def lose_ack(**kwargs):
        calls.append(kwargs)
        if applied:
            await original(**kwargs)
        raise TimeoutError("injected: the reply was lost after the worker answered")

    worker.configure = lose_ack
    return calls, original


def test_a_lost_reply_that_was_applied_is_a_success_not_a_refusal(client, app, read):
    """The worker took the new budget; only the acknowledgement vanished.

    Reporting 409 there is a lie in the other direction from the original defect:
    the operator is told nothing changed while the model runs with more memory.
    The route settles it by reading the worker's own budget and stores the
    setting, so the file and the worker agree.
    """
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    read(8192)
    wanted = limit_for_budget(app, "chat-a", 1000)
    calls, original = _lose_reply(app.state.clients["chat-a"], applied=True)
    try:
        r = put(client, "chat-a", mem_limit_mb=wanted)
    finally:
        app.state.clients["chat-a"].configure = original
    assert calls, "the configure must actually have been sent"
    assert r.status_code == 200, r.text
    assert r.json()["applied"].get("settled_after_lost_reply") is True
    # The two sides agree: the stored setting describes what the worker runs.
    assert client.get("/api/models/chat-a/settings").json()["settings"][
        "mem_limit_mb"] == wanted
    assert budget_mb(app, "chat-a") == 1000
    assert pending(app) == 0, "a settled change must not leave a claim behind"


def test_a_lost_reply_that_was_not_applied_is_a_refusal(client, app, read):
    """The mirror case: nothing was applied, so nothing may be claimed or stored."""
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    read(8192)
    before = client.get("/api/models/chat-a/settings").json()["settings"]
    calls, original = _lose_reply(app.state.clients["chat-a"], applied=False)
    try:
        r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 1000))
    finally:
        app.state.clients["chat-a"].configure = original
    assert calls
    assert r.status_code == 409, r.text
    assert client.get("/api/models/chat-a/settings").json()["settings"] == before
    assert budget_mb(app, "chat-a") == 400
    assert pending(app) == 0, "the change did not happen, so the claim must go"


def test_an_unconfirmable_lost_reply_keeps_the_memory_reserved(client, app, read,
                                                               monkeypatch):
    """When the worker cannot be asked, the claim stays and says so.

    This is the case the review caught: the outcome is genuinely unknown, so the
    API must not answer "refused, nothing changed". The bytes stay reserved under
    an unresolved claim -- so a later load or raise cannot spend them -- and the
    status is 503, which is what "I could not find out" means.
    """
    load(client, "chat-a")
    original_limit = limit_for_budget(app, "chat-a", 400)
    put(client, "chat-a", mem_limit_mb=original_limit)
    read(8192)
    mgr = app.state.models
    calls, original = _lose_reply(app.state.clients["chat-a"], applied=True)

    async def cannot_tell(_model_id: str):
        return None

    monkeypatch.setattr(mgr, "worker_stats", cannot_tell)
    try:
        r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 1000))
    finally:
        app.state.clients["chat-a"].configure = original
    assert calls
    assert r.status_code == 503, r.text
    assert r.json()["code"] == "service_unavailable"
    # The stored setting did NOT move -- nobody could confirm it should.
    assert client.get("/api/models/chat-a/settings").json()["settings"][
        "mem_limit_mb"] == original_limit
    # But the memory is still reserved, because the worker may be holding it.
    unresolved = mgr.unresolved_promises("chat-a")
    assert len(unresolved) == 1, mgr.device_promises
    assert unresolved[0].bytes == (1000 - 400) * MIB


def test_unresolved_memory_is_not_spendable_by_a_later_load(client, app, read,
                                                            monkeypatch):
    """The point of keeping the claim: no later admission may reuse those bytes."""
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    read(8192)
    mgr = app.state.models
    _calls, original = _lose_reply(app.state.clients["chat-a"], applied=True)

    async def cannot_tell(_model_id: str):
        return None

    monkeypatch.setattr(mgr, "worker_stats", cannot_tell)
    try:
        assert put(client, "chat-a",
                   mem_limit_mb=limit_for_budget(app, "chat-a", 1000)).status_code == 503
    finally:
        app.state.clients["chat-a"].configure = original
    held = mgr.unresolved_promises("chat-a")
    assert held and held[0].bytes == 600 * MIB

    # A second model's load now has to make room for that claim on top of what
    # chat-a already holds: its committed 400 MiB budget, the 600 MiB in doubt,
    # chat-b's own footprint, and the floor.
    other = mgr.get("chat-b")
    footprint = mgr._declared_claim_bytes(other) // MIB
    occupied = 400 + 600
    read(occupied + footprint + RESERVE_MB - 1)
    r = client.post("/api/models/chat-b/load")
    assert r.status_code == 409, r.text
    assert "NPU 显存余量不足" in r.json()["detail"]
    read(occupied + footprint + RESERVE_MB)
    assert client.post("/api/models/chat-b/load").status_code == 200
    client.post("/api/models/chat-b/unload")


def test_a_second_change_is_refused_while_one_is_unresolved(client, app, read,
                                                             monkeypatch):
    """Nothing can be checked against a device reading while the worker's real
    budget is in doubt, so a second change is refused until it is settled."""
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    read(8192)
    mgr = app.state.models
    _calls, original = _lose_reply(app.state.clients["chat-a"], applied=True)

    async def cannot_tell(_model_id: str):
        return None

    monkeypatch.setattr(mgr, "worker_stats", cannot_tell)
    try:
        assert put(client, "chat-a",
                   mem_limit_mb=limit_for_budget(app, "chat-a", 1000)).status_code == 503
        # A different model's setting is still fine -- only this one is in doubt.
        assert put(client, "chat-b", mem_limit_mb=1024).status_code == 200
        r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 1200))
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "model_busy"
        assert "未确认" in r.json()["detail"]
    finally:
        app.state.clients["chat-a"].configure = original


def test_retrying_the_same_save_settles_the_doubt(client, app, read, monkeypatch):
    """The remedy the message names actually works, and the claim is released.

    A retry reads the worker's real budget first (that is what settles it), so it
    must succeed and must not leave the memory reserved twice.
    """
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    read(8192)
    mgr = app.state.models
    _calls, original = _lose_reply(app.state.clients["chat-a"], applied=True)

    async def cannot_tell(_model_id: str):
        return None

    real_stats = mgr.worker_stats
    monkeypatch.setattr(mgr, "worker_stats", cannot_tell)
    target = limit_for_budget(app, "chat-a", 1000)
    try:
        assert put(client, "chat-a", mem_limit_mb=target).status_code == 503
    finally:
        app.state.clients["chat-a"].configure = original
        mgr.worker_stats = real_stats       # the worker is reachable again
    assert mgr.unresolved_promises("chat-a")

    # The retry: the worker is reachable again, and it is already at the target
    # budget (the lost reply's change did land). Settling must recognise that and
    # not merely succeed by accident.
    verdict = asyncio.run(mgr.resolve_budget_after_unknown(
        mgr.get("chat-a"), limit_bytes_for_budget(app, "chat-a", 1000)))
    assert verdict == "applied", verdict
    assert mgr.resolve_unresolved_promises("chat-a") == 1
    assert mgr.device_promises == ()


def test_persisting_failure_rolls_the_worker_back(client, app, read, monkeypatch):
    """The worker applied it and the file did not: put the worker back.

    Leaving the worker at a budget the file does not describe is the same
    disagreement as a lost reply, only caused by the disk. The route rolls back,
    then reports 500 -- and only releases the claim once the rollback is
    confirmed.
    """
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    read(8192)
    store = app.state.store
    target = limit_for_budget(app, "chat-a", 1000)

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(store, "set_model_settings", broken)
    r = put(client, "chat-a", mem_limit_mb=target)
    monkeypatch.undo()
    assert r.status_code == 500, r.text
    assert "保存设置失败" in r.json()["detail"]
    # The worker was rolled back, so it agrees with the (unchanged) stored value.
    assert budget_mb(app, "chat-a") == 400
    assert client.get("/api/models/chat-a/settings").json()["settings"][
        "mem_limit_mb"] == limit_for_budget(app, "chat-a", 400)
    assert pending(app) == 0


def test_a_worker_refusal_is_still_a_plain_409(client, app, read, monkeypatch):
    """A worker that *answers* "no" is a definite refusal -- no settling needed."""
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    read(8192)
    mgr = app.state.models

    async def refuse(**kwargs):
        return {"error": "模型仍有运行中的请求，不能调低内存额度；请等请求结束后重试"}

    monkeypatch.setattr(app.state.clients["chat-a"], "configure", refuse)
    r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 1000))
    assert r.status_code == 409, r.text
    assert r.json()["code"] != "service_unavailable"
    assert mgr.unresolved_promises("chat-a") == ()
    assert pending(app) == 0


async def test_a_cancelled_raise_after_the_worker_was_told_stays_reserved(app, read):
    """A cancelled PUT whose ``configure`` was already sent must not free the bytes.

    The request is unwinding, so nothing downstream can be trusted to run -- but
    the worker may already hold the new budget. The route marks the claim
    unresolved **before** any await, so the memory stays reserved however the
    cancellation plays out. This drives the same two calls the route makes, in the
    same order, with the settle step never completing.
    """
    mgr = app.state.models
    mgr.refresh()
    info = mgr.get("chat-a")
    info.loaded = True
    pin_budget(app, "chat-a", 400)
    read(400 + 600 + RESERVE_MB)

    promise = await mgr.admit_limit_raise(
        info, limit_bytes_for_budget(app, "chat-a", 1000))
    assert promise is not None
    assert mgr.device_promises == (promise,)

    async def settle_forever() -> None:
        # What the route awaits after the synchronous note: it never returns,
        # because the worker cannot be reached.
        await asyncio.Event().wait()

    async def route_body() -> None:
        try:
            await settle_forever()
        except asyncio.CancelledError:
            mgr.note_unresolved_promise(promise)     # synchronous, before any await
            raise

    task = asyncio.create_task(route_body())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # The memory is still reserved, and it is marked as in doubt.
    assert mgr.unresolved_promises("chat-a"), mgr.device_promises
    assert mgr.unresolved_promises("chat-a")[0].bytes == 600 * MIB
    # And it is not spendable: a load that would fit without it is refused.
    other = mgr.get("chat-b")
    footprint = mgr._declared_claim_bytes(other) // MIB
    read(400 + 600 + footprint + RESERVE_MB - 1)
    with pytest.raises(DeviceMemoryError):
        await mgr.load("chat-b")
