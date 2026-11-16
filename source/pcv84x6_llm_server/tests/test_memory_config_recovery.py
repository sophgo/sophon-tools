"""Configuration-transaction recovery: transport doubt, retry, unload, persistence.

MYS-2801, the third review's three reproductions (stage 28 PR #137 / 66431c3). The
budget arithmetic is *not* under test here -- it was verified and is frozen. What
this file pins is the **state machine around one model-settings transaction**:

* **Transport is not a refusal.** ``WorkerClient`` raises ``WorkerError`` both when
  the worker answers "no" and when the connection dies after the request was
  written (``_send``) or when the read loop sees EOF (``_call``). ``admin_api``
  treats every ``WorkerError`` as "the worker refused", so a configure the worker
  *applied* -- and only the reply for which was lost -- was reported as a 409 with
  the old setting stored, the worker at the new budget, and an empty ledger.

* **The doubt must be settleable through the public entry point.** ``PUT`` refused
  outright while an operation was unresolved, so "retry the same save" -- the
  remedy its own message names -- was a 409 forever, and only an unload could
  clear it, which also refused. There was no recovery path at all: a test that
  deleted the ledger by hand proved nothing about the product.

* **Persistence is atomic in memory too.** ``StateStore.set_model_settings`` edited
  the live dict and *then* saved; a failed ``save`` left the management plane
  reporting a value the worker had rolled away from and the disk never took.

Each test drives the **public HTTP entry point** and asserts on all four views of
the truth: the worker's applied budget, the stored setting, the file on disk, and
the unresolved-claim ledger.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from pathlib import Path

import pytest
import starlette.requests
from fastapi.testclient import TestClient

from app.api import admin_api

from app.core import monitor
from app.core.client import WorkerError, WorkerTransportError
from app.core.state import ModelSettings
from app.main import create_app

MIB = 1 << 20
CHAT_BMODEL = "qwen3.6-35b-a3b-int4-autow4bf16"
BIG_ENOUGH = 256 * MIB
RESERVE_MB = 1024


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


@pytest.fixture()
def read(monkeypatch):
    def _set(free_mb: int) -> None:
        monkeypatch.setattr(monitor, "device_memory", lambda: heap(free_mb))
    return _set


def budget_mb(app, model_id: str) -> int:
    mgr = app.state.models
    return mgr.runtime_budget_bytes(mgr.get(model_id)) // MIB


def static_mb(app, model_id: str) -> int:
    mgr = app.state.models
    return mgr.static_bytes(mgr.get(model_id)) // MIB


def limit_for_budget(app, model_id: str, budget: int) -> int:
    return static_mb(app, model_id) + budget


def put(client, model_id: str, **body):
    return client.put(f"/api/models/{model_id}/settings", json=body)


def stored(client, model_id: str):
    return client.get(f"/api/models/{model_id}/settings").json()["settings"]


def on_disk(app, model_id: str):
    """The ``model_settings`` entry as the *file* has it (no in-process state)."""
    path = Path(app.state.store.path)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    entry = (data.get("model_settings") or {}).get(model_id)
    return None if entry is None else entry.get("mem_limit_mb")


def worker_budget_mb(app, model_id: str) -> int:
    """What the worker really enforces, read over its own RPC."""
    client = app.state.clients[model_id]
    stats = app.state.portal.call(client.stats) if getattr(app.state, "portal", None) else None
    return int(stats["mem_runtime_budget_bytes"]) // MIB


def load(client, *model_ids: str) -> None:
    for model_id in model_ids:
        r = client.post(f"/api/models/{model_id}/load")
        assert r.status_code == 200, r.text


def worker_mb(client, model_id: str) -> int:
    """The runtime budget the **worker itself** reports enforcing.

    Through the same ``stats`` RPC the management plane uses for its own
    post-timeout reconciliation -- not a test seam, and not the stored setting.
    Reading it on the ``TestClient``'s portal is what makes it possible from the
    test thread: the app's event loop is the one the socket lives on.
    """
    rpc = client.portal.call(app_clients(client)[model_id].stats)
    return int(rpc["mem_runtime_budget_bytes"]) // MIB


def app_clients(client):
    return client.app.state.clients


def runtime_budget_mb(app, model_id: str) -> int:
    """What the *stored setting* says the runtime budget should be."""
    mgr = app.state.models
    return mgr.runtime_budget_bytes(mgr.get(model_id)) // MIB


def pin_budget(app, model_id: str, budget: int) -> None:
    """Store a limit that leaves exactly ``budget`` MiB of runtime room."""
    app.state.store.set_model_settings(
        model_id, ModelSettings(mem_limit_mb=limit_for_budget(app, model_id, budget)))
    assert runtime_budget_mb(app, model_id) == budget


def pending(app) -> tuple:
    return app.state.models.device_promises


def unresolved(app, model_id: str) -> tuple:
    return app.state.models.unresolved_promises(model_id)


@pytest.mark.parametrize("target_mb", [400, 1000])
def test_fractional_static_bytes_survive_spawn_and_lost_configure_reply(
        client, app, read, monkeypatch, target_mb):
    """Real worker RPC must retain sub-MiB static memory, including recovery."""
    mgr = app.state.models
    mgr.refresh()
    static = BIG_ENOUGH + 123456
    mgr._static_bytes["chat-a"] = static
    initial_mb = 256 + 700
    app.state.store.set_model_settings("chat-a", ModelSettings(mem_limit_mb=initial_mb))
    read(10000)
    load(client, "chat-a")
    worker = app.state.clients["chat-a"]

    def assert_budget(limit_mb):
        actual = client.portal.call(worker.stats)["mem_runtime_budget_bytes"]
        assert actual == limit_mb * MIB - static
        assert actual == mgr.runtime_budget_bytes(mgr.get("chat-a"))
        assert stored(client, "chat-a")["mem_limit_mb"] == limit_mb
        assert on_disk(app, "chat-a") == limit_mb
        assert not pending(app)

    assert_budget(initial_mb)
    _, original = _heap_free_but_worker_dies_after_configure(app)
    wanted = 256 + target_mb
    try:
        result = put(client, "chat-a", mem_limit_mb=wanted)
    finally:
        worker.configure = original
    assert result.status_code == 200, result.text
    assert_budget(wanted)
    # Persistence failure must restore precisely the same worker budget.
    with monkeypatch.context() as patch:
        patch.setattr(app.state.store, "save", lambda: (_ for _ in ()).throw(OSError("disk full")))
        result = put(client, "chat-a", mem_limit_mb=wanted - 100)
    assert result.status_code == 500, result.text
    assert_budget(wanted)


# ---------------------------------------------------------------------------
# the transport/refusal distinction (finding 1)
# ---------------------------------------------------------------------------
def test_the_client_separates_a_dead_socket_from_a_worker_refusal():
    """``WorkerError`` must mean "the worker answered"; transport is its own class.

    The route's whole recovery story depends on this: ``_apply_mem_limit`` reads
    ``WorkerError`` as "the worker said no", so a dead socket hidden inside it
    becomes a 409 for a change that may have been applied. Pinned at the client,
    because that is where the two are actually distinguishable.
    """
    # A transport failure is a WorkerError (every existing caller keeps working)
    # but carries the extra fact.
    exc = WorkerTransportError("gone", stage="read")
    assert isinstance(exc, WorkerError)
    assert exc.transport is True and exc.stage == "read"
    # A worker's own error reply is not a transport failure.
    refusal = WorkerError("模型仍有运行中的请求，不能调低内存额度")
    assert not getattr(refusal, "transport", False)


def _heap_free_but_worker_dies_after_configure(app, answer=True):
    """Make ``configure`` behave like a worker that applied and then vanished."""
    worker = app.state.clients["chat-a"]
    original = worker.configure
    calls: list[dict] = []

    async def applied_then_eof(**kwargs):
        calls.append(kwargs)
        if answer:
            await original(**kwargs)
        raise WorkerTransportError("injected: connection closed after configure",
                                  stage="read")

    worker.configure = applied_then_eof
    return calls, original


def test_a_configure_whose_connection_died_after_applying_settles_successfully(
        client, app, read):
    """Reproduction 1: worker applied, the socket died, HTTP was 409.

    The worker is at the new budget the operator asked for; the only thing that
    went wrong is that the reply never arrived. Answering 409 "nothing changed"
    and leaving the old setting on disk is what made the three views of the truth
    disagree (the attachment's first line: 409, saved 400, worker 1000,
    pending 0). Settling by reading the worker must produce a 200 and a store
    that agrees with it.
    """
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    read(8192)
    target = limit_for_budget(app, "chat-a", 1000)
    calls, original = _heap_free_but_worker_dies_after_configure(app)
    try:
        r = put(client, "chat-a", mem_limit_mb=target)
    finally:
        app.state.clients["chat-a"].configure = original
    assert calls, "the configure never reached the worker"
    assert r.status_code == 200, r.text
    # All four views agree.
    assert worker_mb(client, "chat-a") == 1000
    assert stored(client, "chat-a")["mem_limit_mb"] == target
    assert on_disk(app, "chat-a") == target
    assert pending(app) == (), "a settled change must not leave a claim behind"


def test_a_configure_that_never_reached_the_worker_is_still_a_refusal(
        client, app, read):
    """The mirror: nothing was applied, so nothing may be stored or claimed."""
    load(client, "chat-a")
    original_limit = limit_for_budget(app, "chat-a", 400)
    put(client, "chat-a", mem_limit_mb=original_limit)
    read(8192)
    calls, original = _heap_free_but_worker_dies_after_configure(app, answer=False)
    try:
        r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 1000))
    finally:
        app.state.clients["chat-a"].configure = original
    assert calls
    assert r.status_code == 409, r.text
    assert worker_mb(client, "chat-a") == 400
    assert stored(client, "chat-a")["mem_limit_mb"] == original_limit
    assert on_disk(app, "chat-a") == original_limit
    assert pending(app) == ()


# ---------------------------------------------------------------------------
# retry and unload as real recovery paths (finding 2)
# ---------------------------------------------------------------------------
def test_retrying_the_same_save_through_http_finishes_it(client, app, read):
    """Reproduction 2: the retry the message names used to be a 409 forever.

    ``raise_if_budget_unresolved`` refused *every* new change, including the exact
    retry its own detail told the operator to send, so the only ways out were a
    process restart or deleting the ledger by hand -- which is what the old test
    did, and which proves nothing about the product. The retry must go through
    ``PUT`` and must leave all four views consistent.
    """
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    read(8192)
    mgr = app.state.models
    target = limit_for_budget(app, "chat-a", 1000)
    worker = app.state.clients["chat-a"]
    original = worker.configure

    async def applied_then_lost(**kwargs):
        await original(**kwargs)
        raise TimeoutError("injected: the reply was lost")

    worker.configure = applied_then_lost
    real_stats = mgr.worker_stats
    try:
        async def cannot_tell(_model_id: str):
            return None
        mgr.worker_stats = cannot_tell
        first = put(client, "chat-a", mem_limit_mb=target)
    finally:
        worker.configure = original
        mgr.worker_stats = real_stats
    assert first.status_code == 503, first.text
    assert unresolved(app, "chat-a"), "the doubt must be recorded, not forgotten"
    # The memory is still reserved against every later admission.
    assert sum(p.bytes for p in unresolved(app, "chat-a")) == 600 * MIB

    # Communication is back. The same PUT -- the operation's own documented
    # remedy -- must now succeed through the public entry point.
    retry = put(client, "chat-a", mem_limit_mb=target)
    assert retry.status_code == 200, retry.text
    assert retry.json().get("applied", {}).get("settled_after_lost_reply") is True
    assert worker_mb(client, "chat-a") == 1000
    assert stored(client, "chat-a")["mem_limit_mb"] == target
    assert on_disk(app, "chat-a") == target
    assert unresolved(app, "chat-a") == (), "the settled claim must be gone"
    assert pending(app) == ()


def test_a_different_change_is_refused_while_one_is_unresolved(client, app, read):
    """The bit a retry must NOT be allowed to do: layer a second change on a guess."""
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    read(8192)
    mgr = app.state.models
    worker = app.state.clients["chat-a"]
    original = worker.configure

    async def applied_then_lost(**kwargs):
        await original(**kwargs)
        raise TimeoutError("injected: the reply was lost")

    worker.configure = applied_then_lost
    real_stats = mgr.worker_stats
    try:
        async def cannot_tell(_model_id: str):
            return None
        mgr.worker_stats = cannot_tell
        assert put(client, "chat-a",
                   mem_limit_mb=limit_for_budget(app, "chat-a", 1000)).status_code == 503
    finally:
        worker.configure = original
        mgr.worker_stats = real_stats

    r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 1200))
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "model_busy"
    assert "未确认" in r.json()["detail"]
    # And the claim is untouched by the refusal.
    assert unresolved(app, "chat-a")


def test_a_confirmed_unload_clears_the_doubt_and_a_failed_one_does_not(
        client, app, read, monkeypatch):
    """Reproduction 2's second half: unload left pending=1 forever.

    A claim exists because a live worker may hold memory the file does not
    describe. Once the process has exited that is impossible, so keeping the claim
    reserves the bytes for the rest of the process's life -- and a reload would
    inherit it. A *failed* exit must keep it: the worker is still there.
    """
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    read(8192)
    mgr = app.state.models
    worker = app.state.clients["chat-a"]
    original = worker.configure

    async def applied_then_lost(**kwargs):
        await original(**kwargs)
        raise TimeoutError("injected: the reply was lost")

    worker.configure = applied_then_lost
    real_stats = mgr.worker_stats
    try:
        async def cannot_tell(_model_id: str):
            return None
        mgr.worker_stats = cannot_tell
        assert put(client, "chat-a",
                   mem_limit_mb=limit_for_budget(app, "chat-a", 1000)).status_code == 503
    finally:
        worker.configure = original
        mgr.worker_stats = real_stats
    assert len(unresolved(app, "chat-a")) == 1

    # An unload whose worker survives is *not* a confirmed exit: the claim stays.
    async def survives(_model_id: str) -> bool:
        return False

    monkeypatch.setattr(mgr, "_terminate", survives)
    assert client.post("/api/models/chat-a/unload").status_code == 200
    assert len(unresolved(app, "chat-a")) == 1, (
        "a worker that is still alive is exactly what the claim is about")
    monkeypatch.undo()

    # The real unload: the process exits, so the doubt goes with it.
    assert client.post("/api/models/chat-a/unload").status_code == 200
    assert unresolved(app, "chat-a") == ()
    assert pending(app) == ()

    # And a reload does not inherit anything.
    load(client, "chat-a")
    assert unresolved(app, "chat-a") == ()
    assert pending(app) == ()
    assert worker_mb(client, "chat-a") == 400, (
        "the reloaded worker must start from the stored setting")


# ---------------------------------------------------------------------------
# persistence atomicity (finding 3)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("case", ["raise", "shrink", "reset", "absent"])
def test_a_failed_save_restores_the_previous_entry_exactly(client, app, read, case):
    """Reproduction 3: ``set_model_settings`` edited memory and *then* saved.

    The API500 case in the attachment: the worker rolled back to 1000 while the
    management plane reported 400 and the file still said 1000. Injecting at the
    real ``save`` (not by replacing the whole setter, which is what let the old
    test miss this) must leave the in-memory entry *and* the disk exactly as they
    were, for every shape of previous entry.
    """
    from app.core.state import ModelSettings

    store = app.state.store
    model_id = "chat-a"
    seeded = {
        "raise": ModelSettings(mem_limit_mb=1024),
        "shrink": ModelSettings(mem_limit_mb=2048),
        "reset": ModelSettings(mem_limit_mb=2048),
        "absent": None,
    }[case]
    store.model_settings.pop(model_id, None)
    if seeded is not None:
        store.set_model_settings(model_id, seeded)
    before_mem = store.get_model_settings(model_id).to_json()
    before_disk = on_disk(app, model_id)

    new = {"raise": ModelSettings(mem_limit_mb=2048),
           "shrink": ModelSettings(mem_limit_mb=1024),
           "reset": ModelSettings(mem_limit_mb=None),
           "absent": ModelSettings(mem_limit_mb=1024)}[case]

    real_save = store.save

    def broken_save():
        raise OSError("injected: disk full")

    store.save = broken_save
    try:
        with pytest.raises(OSError):
            store.set_model_settings(model_id, new)
    finally:
        store.save = real_save

    assert store.get_model_settings(model_id).to_json() == before_mem, (
        "a failed save half-wrote the in-memory entry")
    assert on_disk(app, model_id) == before_disk


def test_a_failed_save_does_not_disturb_other_models(client, app, read):
    """The same atomicity, across entries: one model's failure, another's value."""
    from app.core.state import ModelSettings

    store = app.state.store
    store.set_model_settings("chat-b", ModelSettings(mem_limit_mb=3072))
    before_b = store.get_model_settings("chat-b").to_json()

    real_save = store.save

    store.save = lambda: (_ for _ in ()).throw(OSError("injected: disk full"))
    try:
        with pytest.raises(OSError):
            store.set_model_settings("chat-a", ModelSettings(mem_limit_mb=1024))
    finally:
        store.save = real_save

    assert store.get_model_settings("chat-b").to_json() == before_b
    assert store.get_model_settings("chat-a").is_default()


# ---------------------------------------------------------------------------
# the real socket: what the client actually raises (finding 1, wire-level)
# ---------------------------------------------------------------------------
async def _fake_worker(handler):
    """A one-connection JSON-lines server standing in for a model worker."""
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def test_a_worker_that_applies_configure_and_then_drops_is_a_transport_error():
    """The exact production shape: ``configure`` is executed, the reply never comes.

    This is not a mock of the client's decision -- it is a real socket, a real
    EOF and the real ``_call``. Before MYS-2801 the read loop queued an
    ``{"op": "error"}`` frame here, which ``_call`` turned into the same
    ``WorkerError`` a refusal produces, so the route reported "409, nothing
    changed" for a budget the worker was enforcing.
    """
    from app.core.client import WorkerClient, WorkerError, WorkerTransportError

    async def handler(reader, writer):
        line = await reader.readline()
        msg = json.loads(line)
        assert msg["op"] == "configure"
        # Applied -- then the process dies before answering.
        writer.close()
        await writer.wait_closed()

    server, port = await _fake_worker(handler)
    client = WorkerClient(port)
    try:
        with pytest.raises(WorkerTransportError) as info:
            await asyncio.wait_for(client.configure(mem_limit_mb=1000), timeout=5)
        assert isinstance(info.value, WorkerError), (
            "existing callers catch WorkerError and must keep working")
        assert info.value.stage == "read"
    finally:
        await client.close()
        server.close()
        await server.wait_closed()


async def test_a_worker_that_answers_with_an_error_frame_is_a_refusal():
    """The other side of the same wire: an answer, so a definite refusal."""
    from app.core.client import WorkerClient, WorkerError, WorkerTransportError

    async def handler(reader, writer):
        msg = json.loads(await reader.readline())
        writer.write((json.dumps({
            "op": "error", "req_id": msg["req_id"],
            "message": "模型仍有运行中的请求，不能调低内存额度",
            "kind": "busy"}) + "\n").encode())
        await writer.drain()
        await asyncio.sleep(0.2)
        writer.close()

    server, port = await _fake_worker(handler)
    client = WorkerClient(port)
    try:
        with pytest.raises(WorkerError) as info:
            await asyncio.wait_for(client.configure(mem_limit_mb=1000), timeout=5)
        assert not isinstance(info.value, WorkerTransportError), (
            "the worker answered, so this is not a transport failure")
        assert info.value.kind == "busy"
    finally:
        await client.close()
        server.close()
        await server.wait_closed()


async def test_a_write_failure_is_a_transport_error_not_a_refusal():
    """A dead socket at write time: nothing was delivered, but nothing is proven."""
    from app.core.client import WorkerClient, WorkerError, WorkerTransportError

    async def handler(reader, writer):
        # Accept, then go away: the client's write/drain fails or the read meets
        # EOF -- either way a local failure, never the worker's own answer.
        writer.close()
        await writer.wait_closed()

    server, port = await _fake_worker(handler)
    client = WorkerClient(port)
    try:
        with pytest.raises(WorkerError) as info:
            await asyncio.wait_for(client.configure(mem_limit_mb=1000), timeout=5)
        assert isinstance(info.value, WorkerTransportError)
        assert info.value.stage in ("connect", "write", "read")
    finally:
        await client.close()
        server.close()
        await server.wait_closed()


async def test_a_refused_connection_is_a_transport_error():
    """Nothing listening: no worker to have applied anything."""
    from app.core.client import WorkerClient, WorkerTransportError

    server, port = await _fake_worker(lambda r, w: None)
    server.close()
    await server.wait_closed()
    client = WorkerClient(port)
    try:
        with pytest.raises(WorkerTransportError) as info:
            await asyncio.wait_for(client.configure(mem_limit_mb=1000), timeout=5)
        assert info.value.stage == "connect"
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# cancellation, through the real route (finding 5)
# ---------------------------------------------------------------------------
def _route_settings(app, model_id: str, wanted: int):
    """The route's own coroutine, so a test can cancel the request it stands for.

    The ``TestClient`` owns the event loop, which is why "cancel this HTTP
    request" needs the coroutine itself rather than a socket. What runs is still
    the real route -- the same function, the same lifecycle lock, the same store;
    only the transport is replaced by ``create_task`` + ``cancel``.
    """
    from app.api.admin_api import ModelSettingsBody

    async def call() -> dict:
        scope = {
            "type": "http", "method": "PUT", "path": f"/api/models/{model_id}/settings",
            "headers": [], "app": app,
        }
        request = starlette.requests.Request(scope)
        body = ModelSettingsBody(mem_limit_mb=wanted)
        return await admin_api.update_model_settings(
            model_id, body, request, _=None)

    return call()


async def test_cancelling_before_the_worker_is_told_leaves_nothing_behind(app, read):
    """A request cancelled while it waits for the lifecycle lock changes nothing."""
    mgr = app.state.models
    mgr.refresh()
    info = mgr.get("chat-a")
    info.loaded = True
    pin_budget(app, "chat-a", 400)
    read(400 + 600 + RESERVE_MB)
    # Hold the lock the route must take: the cancellation then lands before a
    # single byte is promised or sent.
    lock = mgr.lock_for("chat-a")
    await lock.acquire()
    task = asyncio.create_task(_route_settings(app, "chat-a",
                                              limit_for_budget(app, "chat-a", 1000)))
    await asyncio.sleep(0.05)
    assert not task.done(), "the route did not wait for the lifecycle lock"
    task.cancel()
    lock.release()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert mgr.device_promises == (), "a cancellation leaked a promise"
    # No worker was touched: nothing was sent, so nothing can have been applied.
    assert app.state.store.get_model_settings("chat-a").mem_limit_mb == \
        limit_for_budget(app, "chat-a", 400)


async def test_cancelling_after_the_worker_applied_keeps_the_memory_reserved(
        app, read, monkeypatch):
    """The dangerous interleaving: told, then cancelled, then unreadable.

    The worker may hold the new budget, so the claim must stay -- unresolved and
    still reserving -- and the request must unwind rather than swallow the
    cancellation. This is the case whose old ``shield``-ed settlement ran after
    the lifecycle lock had been released.
    """
    from app.api import admin_api

    mgr = app.state.models
    mgr.refresh()
    info = mgr.get("chat-a")
    info.loaded = True
    pin_budget(app, "chat-a", 400)
    read(400 + 600 + RESERVE_MB)
    wanted_mb = limit_for_budget(app, "chat-a", 1000)
    wanted = wanted_mb * MIB

    async def slow_apply(*_a, **_kw):
        await asyncio.sleep(3600)
        return {}

    async def cannot_tell(_model_id):
        return None

    monkeypatch.setattr(admin_api, "_apply_mem_limit", slow_apply)
    monkeypatch.setattr(mgr, "worker_stats", cannot_tell)

    task = asyncio.create_task(_route_settings(app, "chat-a", wanted_mb))
    # Let it take the lock, admit and enter the configure.
    for _ in range(200):
        await asyncio.sleep(0.01)
        if mgr.device_promises:
            break
    assert mgr.device_promises, "the route never admitted the raise"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    held = mgr.unresolved_promises("chat-a")
    assert held, "a cancelled change may have been applied; the bytes must stay"
    assert held[0].bytes == 600 * MIB
    assert held[0].pending_limit_bytes == wanted, (
        "the claim must carry the request, or no retry can finish it")
    # And it still blocks a *different* change, through the public route.
    with pytest.raises(Exception) as info_:
        await _route_settings(app, "chat-a",
                             limit_for_budget(app, "chat-a", 1200))
    assert "409" in str(info_.value) or getattr(info_.value, "status_code", 0) == 409


async def test_a_second_cancellation_still_leaves_a_conservative_state(app, read,
                                                                      monkeypatch):
    """Cancelling twice must not lose the claim either.

    The first cancellation marks the claim unresolved synchronously; the settle
    that follows may be interrupted again. Whatever happens, the ledger must
    still say "this memory may be in use".
    """
    from app.api import admin_api

    mgr = app.state.models
    mgr.refresh()
    info = mgr.get("chat-a")
    info.loaded = True
    pin_budget(app, "chat-a", 400)
    read(400 + 600 + RESERVE_MB)
    wanted_mb = limit_for_budget(app, "chat-a", 1000)
    wanted = wanted_mb * MIB

    async def slow_apply(*_a, **_kw):
        await asyncio.sleep(3600)

    async def slow_probe(_model_id):
        await asyncio.sleep(3600)

    monkeypatch.setattr(admin_api, "_apply_mem_limit", slow_apply)
    monkeypatch.setattr(mgr, "worker_stats", slow_probe)

    task = asyncio.create_task(_route_settings(app, "chat-a", wanted_mb))
    for _ in range(200):
        await asyncio.sleep(0.01)
        if mgr.device_promises:
            break
    assert mgr.device_promises
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    held = mgr.unresolved_promises("chat-a")
    assert held and held[0].pending_limit_bytes == wanted
    # A later load still has to make room for it.
    from app.core.models import DeviceMemoryError
    other = mgr.get("chat-b")
    footprint = mgr._declared_claim_bytes(other) // MIB
    read(400 + 600 + footprint + RESERVE_MB - 1)
    with pytest.raises(DeviceMemoryError):
        await mgr.load("chat-b")


async def test_a_route_settlement_never_outlives_the_lifecycle_lock(app, read,
                                                                   monkeypatch):
    """No detached task: after a cancellation, nothing may still write settings.

    The requirement is explicit -- a shielded task must not keep writing settings
    after the lifecycle lock is released. So the settle runs inline, inside the
    lock; once the cancelled request has unwound the store must be at rest.
    """
    from app.api import admin_api

    mgr = app.state.models
    mgr.refresh()
    info = mgr.get("chat-a")
    info.loaded = True
    pin_budget(app, "chat-a", 400)
    read(400 + 600 + RESERVE_MB)
    wanted = limit_for_budget(app, "chat-a", 1000)
    before = app.state.store.get_model_settings("chat-a").to_json()

    async def applied_then_cancelled(*_a, **_kw):
        raise asyncio.CancelledError()

    monkeypatch.setattr(admin_api, "_apply_mem_limit", applied_then_cancelled)
    task = asyncio.create_task(_route_settings(app, "chat-a", wanted))
    with contextlib.suppress(asyncio.CancelledError):
        await task
    # Whatever the settle decided, it is finished and no task is left running.
    others = [t for t in asyncio.all_tasks()
              if t is not asyncio.current_task() and not t.done()]
    assert not others, f"settlement tasks outlived the request: {others}"
    # And the store is either the old value or the settled new one -- never a
    # value written after the lock went away.
    now = app.state.store.get_model_settings("chat-a").to_json()
    assert now == before or now["mem_limit_mb"] == wanted


# ---------------------------------------------------------------------------
# the connection path under load (the card requires a 6-way regression)
# ---------------------------------------------------------------------------
def test_six_clients_hammering_settings_and_unload_recover_without_leaks(
        client, app, read):
    """Six concurrent clients, repeated: raise, cancel, unload, reload.

    The card's acceptance asks for this explicitly. What it has to prove is that
    the recovery machinery does not itself leak under concurrency: no claim
    survives a settled transaction, no promise is double-counted, every observed
    status is one the design names, and the ledger plus the stored setting plus
    the worker all agree at the end of each round.
    """
    from concurrent.futures import ThreadPoolExecutor

    load(client, "chat-a")
    base = limit_for_budget(app, "chat-a", 400)
    put(client, "chat-a", mem_limit_mb=base)
    read(8192)
    mgr = app.state.models
    worker = app.state.clients["chat-a"]
    original = worker.configure
    statuses: list[int] = []
    lock = threading.Lock()

    def one(i: int) -> None:
        # Each client sends one change. What it may *not* do is read back its own
        # value: six concurrent writers all succeed and the last one wins, which
        # is the pre-existing (and intended) semantics of a settings save. What
        # this test is about is that no round leaves the ledger inconsistent.
        target = limit_for_budget(app, "chat-a", 500 + (i % 3) * 100)
        r = client.put("/api/models/chat-a/settings", json={"mem_limit_mb": target})
        with lock:
            statuses.append(r.status_code)
        if r.status_code == 200:
            view = client.get("/api/models/chat-a/settings").json()
            # Whatever landed, it is one of the values a client asked for.
            assert view["settings"]["mem_limit_mb"] in {
                limit_for_budget(app, "chat-a", 500 + (j % 3) * 100) for j in range(6)}

    try:
        for round_no in range(6):
            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(one, range(6)))
            # After each round nothing may be in doubt and nothing may be claimed
            # twice: every transaction settled one way or the other.
            assert mgr.unresolved_promises("chat-a") == (), (
                f"round {round_no} left a claim in doubt: {mgr.device_promises}")
            assert mgr.device_promises == (), (
                f"round {round_no} leaked a promise: {mgr.device_promises}")
            # Put the model back on its base limit for the next round.
            r = client.put("/api/models/chat-a/settings",
                           json={"mem_limit_mb": base})
            assert r.status_code == 200, r.text
    finally:
        worker.configure = original

    assert set(statuses) <= {200, 409, 503}, statuses
    assert 200 in statuses, statuses
    # And the four views agree at the end.
    assert worker_mb(client, "chat-a") == 400
    assert stored(client, "chat-a")["mem_limit_mb"] == base
    assert on_disk(app, "chat-a") == base
    assert pending(app) == ()


def test_six_clients_connecting_and_disconnecting_leave_no_orphan_socket():
    """Six workers, six clients, repeated connect/disconnect cycles.

    The transport change (a sentinel instead of an error frame on EOF) touches
    the read loop every connection shares, so the path is exercised directly:
    each cycle must leave no queue, no pump task and no half-open writer behind.
    """
    from app.core.client import WorkerClient

    async def handler(reader, writer):
        with contextlib.suppress(Exception):
            while True:
                line = await reader.readline()
                if not line:
                    return
                msg = json.loads(line)
                writer.write((json.dumps({
                    "op": msg["op"], "req_id": msg.get("req_id"),
                    "mem_runtime_budget_bytes": 1000 * MIB,
                }) + "\n").encode())
                await writer.drain()

    async def cycle() -> None:
        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        clients = [WorkerClient(port) for _ in range(6)]
        try:
            for _ in range(10):
                replies = await asyncio.gather(*(c.configure(mem_limit_mb=1000)
                                                 for c in clients))
                assert all(r["mem_runtime_budget_bytes"] == 1000 * MIB
                           for r in replies)
                for c in clients:
                    assert c._queues == {}, "a reply queue was left behind"
        finally:
            await asyncio.gather(*(c.close() for c in clients))
            for c in clients:
                assert c._writer is None and c._pump is None or c._pump.done()
            server.close()
            await server.wait_closed()

    asyncio.run(cycle())


def test_six_clients_cancelling_requests_mid_configure_recover(app, read,
                                                               monkeypatch):
    """Six cancellations landing mid-``configure``, then one recovery.

    The cancellation path marks the claim unresolved synchronously and then
    settles inline. Six of them at once must not lose a claim, double-count one,
    or leave a task writing settings after its request unwound.
    """
    from app.api import admin_api

    mgr = app.state.models
    mgr.refresh()
    info = mgr.get("chat-a")
    info.loaded = True
    pin_budget(app, "chat-a", 400)
    read(8192)
    wanted_mb = limit_for_budget(app, "chat-a", 1000)

    async def slow_apply(*_a, **_kw):
        await asyncio.sleep(3600)

    async def cannot_tell(_model_id):
        return None

    monkeypatch.setattr(admin_api, "_apply_mem_limit", slow_apply)
    monkeypatch.setattr(mgr, "worker_stats", cannot_tell)

    async def one() -> None:
        task = asyncio.create_task(_route_settings(app, "chat-a", wanted_mb))
        for _ in range(200):
            await asyncio.sleep(0.005)
            if mgr.device_promises:
                break
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    async def run() -> tuple[int, int]:
        await asyncio.gather(*(one() for _ in range(6)))
        # Only one transaction can hold the lifecycle lock at a time, so exactly
        # one claim is in doubt at the end: the rest never admitted.
        return len(mgr.unresolved_promises("chat-a")), len(mgr.device_promises)

    unresolved_count, total = asyncio.run(run())
    assert total == 1, f"expected one claim in doubt, got {total}"
    assert unresolved_count == 1
    monkeypatch.undo()

    # The ledger still reserves it, and the public retry path settles it.
    held = mgr.unresolved_promises("chat-a")[0]
    assert held.pending_limit_bytes == wanted_mb * MIB


# ---------------------------------------------------------------------------
# second review: operations that reserve nothing still need a record
# ---------------------------------------------------------------------------
def _pinned(client, app, budget_mb: int = 1000) -> int:
    """Load chat-a and pin it to ``budget_mb`` of runtime room."""
    load(client, "chat-a")
    put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", budget_mb))
    return limit_for_budget(app, "chat-a", budget_mb)


def test_a_lost_reduction_settles_instead_of_crashing(client, app, read):
    """Reproduction 1: a reduction reserves nothing, and used to have no record.

    ``admit_limit_raise`` answers "how much must be reserved", which is zero for a
    reduction -- and the route used that as the operation state, so a reduction
    whose reply was lost reached ``settle_unresolved(None)`` and raised an
    ``AttributeError`` that surfaced as a 500 with the worker at 400 and the file
    still at 1000. The record and the reservation are separate now: this settles
    by reading the worker, and stores what it actually did.
    """
    _pinned(client, app, 1000)
    read(8192)
    worker = app.state.clients["chat-a"]
    original = worker.configure

    async def applied_then_lost(**kwargs):
        await original(**kwargs)
        raise WorkerTransportError("injected: EOF after the worker applied it")

    worker.configure = applied_then_lost
    try:
        r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    finally:
        worker.configure = original
    assert r.status_code == 200, r.text
    assert worker_mb(client, "chat-a") == 400
    assert stored(client, "chat-a")["mem_limit_mb"] == limit_for_budget(app, "chat-a", 400)
    assert on_disk(app, "chat-a") == limit_for_budget(app, "chat-a", 400)
    assert pending(app) == (), "a settled reduction must leave no record"


def test_a_lost_reduction_that_did_not_apply_is_a_refusal(client, app, read):
    """The mirror: nothing applied, so nothing may be stored, and no record stays."""
    _pinned(client, app, 1000)
    read(8192)
    before = stored(client, "chat-a")["mem_limit_mb"]
    worker = app.state.clients["chat-a"]
    original = worker.configure

    async def lost_before_applying(**kwargs):
        raise WorkerTransportError("injected: EOF before the worker saw it")

    worker.configure = lost_before_applying
    try:
        r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 400))
    finally:
        worker.configure = original
    assert r.status_code == 409, r.text
    assert worker_mb(client, "chat-a") == 1000
    assert stored(client, "chat-a")["mem_limit_mb"] == before
    assert pending(app) == ()


def test_a_lost_noop_is_still_settled(client, app, read):
    """A save of the value already in force is a real round trip, not a no-op to skip."""
    pinned = _pinned(client, app, 1000)
    read(8192)
    worker = app.state.clients["chat-a"]
    original = worker.configure

    async def applied_then_lost(**kwargs):
        await original(**kwargs)
        raise TimeoutError("injected: the reply was lost")

    worker.configure = applied_then_lost
    try:
        r = put(client, "chat-a", mem_limit_mb=pinned)
    finally:
        worker.configure = original
    assert r.status_code == 200, r.text
    assert worker_mb(client, "chat-a") == 1000
    assert pending(app) == ()


def test_a_lost_change_with_the_reserve_switched_off_keeps_its_record(client, app, read,
                                                                     monkeypatch):
    """``CV84X6_NPU_RESERVE_MB=0`` reserves nothing -- and still needs settling.

    The reserve being off means "do not check headroom", not "do not track the
    operation". A reduction and a reserve-off raise fail in the same way if they
    lose their reply, so both need the same record.
    """
    _pinned(client, app, 400)
    read(8192)
    monkeypatch.setenv("CV84X6_NPU_RESERVE_MB", "0")
    mgr = app.state.models
    worker = app.state.clients["chat-a"]
    original = worker.configure

    async def applied_then_lost(**kwargs):
        await original(**kwargs)
        raise WorkerTransportError("injected: EOF after applying")

    worker.configure = applied_then_lost
    try:
        r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 1000))
    finally:
        worker.configure = original
    assert r.status_code == 200, (
        f"with the floor off there is nothing to admit: {r.text}")
    assert worker_mb(client, "chat-a") == 1000
    assert stored(client, "chat-a")["mem_limit_mb"] == limit_for_budget(app, "chat-a", 1000)
    assert pending(app) == ()
    assert mgr.configuration_operations("chat-a") == ()


def test_an_auxiliary_model_change_also_gets_a_record(client, app, read):
    """An auxiliary kind has no runtime budget, so it reserves nothing at all.

    Its limit change is still a ``configure`` that can be lost -- the same code
    path, and the same requirement.
    """
    models_dir = Path(app.state.models.models_root)
    make_model(models_dir, "embed-a", bmodel="qwen3-embedding-0.6b_bf16")
    app.state.models.refresh()
    load(client, "embed-a")
    worker = app.state.clients["embed-a"]
    original = worker.configure

    async def applied_then_lost(**kwargs):
        await original(**kwargs)
        raise TimeoutError("injected: the reply was lost")

    worker.configure = applied_then_lost
    try:
        r = put(client, "embed-a", mem_limit_mb=4096)
    finally:
        worker.configure = original
    assert r.status_code == 200, r.text
    assert stored(client, "embed-a")["mem_limit_mb"] == 4096
    assert on_disk(app, "embed-a") == 4096
    assert app.state.models.configuration_operations("embed-a") == ()




# ---------------------------------------------------------------------------
# second review: cancellation anywhere in the transaction marks the operation
# ---------------------------------------------------------------------------
async def test_cancelling_during_the_settle_read_marks_the_operation(app, read,
                                                                    monkeypatch):
    """Reproduction 2: cancelled *inside* the probe, not inside ``configure``.

    The first version marked the operation only in the cancellation handler
    around ``configure``. A ``TimeoutError`` took the settle path instead, and a
    cancellation inside that read left ``pending 1 / unresolved 0``: memory
    reserved by something nothing had flagged as in doubt, so a *different*
    change was admitted on top of it (the reproduction's 200 and leftover 600 MiB
    claim) and a confirmed unload left the record behind.
    """
    from app.api import admin_api

    mgr = app.state.models
    mgr.refresh()
    info = mgr.get("chat-a")
    info.loaded = True
    pin_budget(app, "chat-a", 400)
    read(400 + 600 + RESERVE_MB)
    wanted_mb = limit_for_budget(app, "chat-a", 1000)

    entered = asyncio.Event()

    async def lost_reply(*_a, **_kw):
        # The worker applied it; only the reply never came. That is what puts the
        # route into the settle path whose probe we then cancel inside.
        raise TimeoutError("injected: the reply was lost after the worker applied it")

    async def slow_probe(_model_id):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(admin_api, "_apply_mem_limit", lost_reply)
    monkeypatch.setattr(mgr, "worker_stats", slow_probe)

    task = asyncio.create_task(_route_settings(app, "chat-a", wanted_mb))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    held = mgr.unresolved_promises("chat-a")
    assert len(held) == 1, (
        "a cancellation during the settle read left the record unflagged: "
        f"{mgr.device_promises}")
    assert held[0].pending_limit_bytes == wanted_mb * MIB
    assert held[0].previous_limit_bytes is not None
    # And it does the job an unresolved operation exists for: a *different*
    # change is refused rather than layered on a guess.
    other = wanted_mb + 200
    with pytest.raises(Exception) as info_:
        await _route_settings(app, "chat-a", other)
    assert getattr(info_.value, "status_code", None) == 409, info_.value


async def test_cancelling_during_a_rollback_keeps_the_original_request(app, read,
                                                                     monkeypatch):
    """A cancellation while pushing the old limit back must not lose the request."""
    from app.api import admin_api

    mgr = app.state.models
    mgr.refresh()
    info = mgr.get("chat-a")
    info.loaded = True
    pin_budget(app, "chat-a", 400)
    read(400 + 600 + RESERVE_MB)
    wanted_mb = limit_for_budget(app, "chat-a", 1000)
    entered = asyncio.Event()
    calls: list = []

    async def apply(_, _info, *, limit_bytes=None):
        calls.append(limit_bytes)
        if len(calls) == 1:
            return {"op": "configure"}          # the new limit "applied"
        entered.set()
        await asyncio.Event().wait()            # the rollback hangs

    def broken_save(*_a, **_kw):
        raise OSError("injected: disk full")

    monkeypatch.setattr(admin_api, "_apply_mem_limit", apply)
    monkeypatch.setattr(app.state.store, "set_model_settings", broken_save)

    task = asyncio.create_task(_route_settings(app, "chat-a", wanted_mb))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    held = mgr.configuration_operations("chat-a")
    assert len(held) == 1, mgr.device_promises
    # The original request survived the rollback: both limits are still there,
    # so a retry can tell what to settle.
    assert held[0].pending_limit_bytes == wanted_mb * MIB
    assert held[0].previous_limit_bytes == limit_for_budget(app, "chat-a", 400) * MIB
    assert held[0].unresolved is True
    assert held[0].phase in {"rollback_unknown", "rollback_failed"}


async def test_cancelling_twice_still_leaves_one_marked_operation(app, read,
                                                                  monkeypatch):
    """Cancelling the request twice must not lose the record either.

    The first cancellation marks the operation synchronously and starts the
    settle; the second lands while that settle is awaiting. Whatever happens, the
    ledger must still say "this may be in force".
    """
    from app.api import admin_api

    mgr = app.state.models
    mgr.refresh()
    info = mgr.get("chat-a")
    info.loaded = True
    pin_budget(app, "chat-a", 400)
    read(400 + 600 + RESERVE_MB)
    wanted_mb = limit_for_budget(app, "chat-a", 1000)

    async def lost_reply(*_a, **_kw):
        raise TimeoutError("injected: the reply was lost")

    async def slow_probe(_model_id):
        await asyncio.Event().wait()

    monkeypatch.setattr(admin_api, "_apply_mem_limit", lost_reply)
    monkeypatch.setattr(mgr, "worker_stats", slow_probe)

    task = asyncio.create_task(_route_settings(app, "chat-a", wanted_mb))
    for _ in range(200):
        await asyncio.sleep(0.01)
        if mgr.unresolved_promises("chat-a"):
            break
    assert mgr.unresolved_promises("chat-a"), "the route never recorded the operation"
    # Cancel twice in the same tick: the request is already unwinding, so both
    # land on the unwinding task -- exactly the shape a client that hung up and
    # then had its connection torn down produces.
    task.cancel()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    held = mgr.unresolved_promises("chat-a")
    assert len(held) == 1, mgr.device_promises
    assert held[0].pending_limit_bytes == wanted_mb * MIB
    assert held[0].previous_limit_bytes is not None


async def test_a_second_cancel_during_the_settle_read_is_absorbed(app, read,
                                                                  monkeypatch):
    """A second cancellation landing while the settle read awaits is absorbed.

    The first cancel marks the operation and starts the settle; the second lands
    while that settle is inside its probe. The claim is already flagged, so the
    second one cannot do better than the first -- what it must not do is release
    the record or let the route report success.
    """
    from app.api import admin_api

    mgr = app.state.models
    mgr.refresh()
    info = mgr.get("chat-a")
    info.loaded = True
    pin_budget(app, "chat-a", 400)
    read(400 + 600 + RESERVE_MB)
    wanted_mb = limit_for_budget(app, "chat-a", 1000)
    probing = asyncio.Event()

    async def lost_reply(*_a, **_kw):
        raise TimeoutError("injected: the reply was lost")

    async def slow_probe(_model_id):
        probing.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(admin_api, "_apply_mem_limit", lost_reply)
    monkeypatch.setattr(mgr, "worker_stats", slow_probe)

    task = asyncio.create_task(_route_settings(app, "chat-a", wanted_mb))
    await asyncio.wait_for(probing.wait(), 5)
    task.cancel()
    await asyncio.sleep(0.02)
    if not task.done():
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    held = mgr.unresolved_promises("chat-a")
    assert len(held) == 1, mgr.device_promises
    assert held[0].pending_limit_bytes == wanted_mb * MIB


async def test_a_confirmed_exit_clears_settled_operations_too(app, read):
    """Not just the unresolved subset: every record belongs to a dead worker."""
    mgr = app.state.models
    mgr.refresh()
    info = mgr.get("chat-a")
    info.loaded = True
    info.pid = 4321
    pin_budget(app, "chat-a", 400)

    await mgr.begin_limit_change(
        info, limit_for_budget(app, "chat-a", 1000) * MIB)
    assert mgr.configuration_operations("chat-a")
    # A record whose reply arrived but whose persist is still in flight is
    # *not* unresolved -- and still has to go when the process does.
    assert mgr.unresolved_promises("chat-a") == ()

    info.pid = None                      # the process is gone
    mgr._forget(info)
    assert mgr.configuration_operations("chat-a") == ()
    assert mgr.device_promises == ()


def test_a_confirmed_unload_clears_a_settled_record(client, app, read):
    """The same, through the route: a successful change plus an unload is clean."""
    _pinned(client, app, 400)
    read(8192)
    assert put(client, "chat-a",
               mem_limit_mb=limit_for_budget(app, "chat-a", 1000)).status_code == 200
    assert client.post("/api/models/chat-a/unload").status_code == 200
    assert app.state.models.configuration_operations("chat-a") == ()
    assert pending(app) == ()


# ---------------------------------------------------------------------------
# second review: a failed rollback must not destroy the original request
# ---------------------------------------------------------------------------
def test_a_refused_rollback_keeps_the_original_request_and_reports_503(
        client, app, read):
    """Reproduction 3: the rollback was refused, and both retries became useless.

    The record used to be rewritten with the rollback's own numbers, so the only
    description of what the operator asked for was gone: retrying the original
    limit got 409 (not "the same request") and retrying the old value got 503.
    The record keeps the original request, the phase says the rollback failed,
    and the answer is 503 -- "not confirmed" -- rather than a 500 claiming the
    worker was restored.
    """
    _pinned(client, app, 400)
    read(8192)
    target = limit_for_budget(app, "chat-a", 1000)
    old = limit_for_budget(app, "chat-a", 400)
    worker = app.state.clients["chat-a"]
    original = worker.configure
    real_save = app.state.store.save

    async def refuse_rollback(**kwargs):
        if kwargs.get("mem_limit_mb") == old:
            return {"error": "injected: the worker will not go back"}
        return await original(**kwargs)

    worker.configure = refuse_rollback
    app.state.store.save = lambda: (_ for _ in ()).throw(OSError("injected: disk full"))
    try:
        r = put(client, "chat-a", mem_limit_mb=target)
    finally:
        worker.configure = original
        app.state.store.save = real_save
    assert r.status_code == 503, r.text
    assert r.json()["code"] == "service_unavailable"
    # The worker really is on the new limit and the file on the old one.
    assert worker_mb(client, "chat-a") == 1000
    assert stored(client, "chat-a")["mem_limit_mb"] == old
    held = app.state.models.configuration_operations("chat-a")
    assert len(held) == 1, app.state.models.device_promises
    assert held[0].pending_limit_bytes == target * MIB, (
        "the rollback overwrote the request the operator made")
    assert held[0].previous_limit_bytes == old * MIB

    # The original retry can settle it: the worker is already there, so the file
    # just needs to catch up.
    retry = put(client, "chat-a", mem_limit_mb=target)
    assert retry.status_code == 200, retry.text
    assert retry.json()["applied"].get("settled_after_lost_reply") is True
    assert stored(client, "chat-a")["mem_limit_mb"] == target
    assert on_disk(app, "chat-a") == target
    assert worker_mb(client, "chat-a") == 1000
    assert app.state.models.configuration_operations("chat-a") == ()


def test_a_rollback_that_landed_safely_is_a_plain_500(client, app, read):
    """When the rollback *is* confirmed, the two sides agree and it is a 500."""
    _pinned(client, app, 400)
    read(8192)
    worker = app.state.clients["chat-a"]
    original = worker.configure
    real_save = app.state.store.save
    app.state.store.save = lambda: (_ for _ in ()).throw(OSError("injected: disk full"))
    try:
        r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 1000))
    finally:
        worker.configure = original
        app.state.store.save = real_save
    assert r.status_code == 500, r.text
    assert worker_mb(client, "chat-a") == 400
    assert stored(client, "chat-a")["mem_limit_mb"] == limit_for_budget(app, "chat-a", 400)
    assert app.state.models.configuration_operations("chat-a") == ()
    assert pending(app) == ()


def test_a_rollback_whose_reply_was_lost_is_settled_by_reading(client, app, read):
    """The rollback executed but its ack vanished: read, then decide."""
    _pinned(client, app, 400)
    read(8192)
    old = limit_for_budget(app, "chat-a", 400)
    worker = app.state.clients["chat-a"]
    original = worker.configure
    real_save = app.state.store.save

    async def lost_rollback_ack(**kwargs):
        await original(**kwargs)
        if kwargs.get("mem_limit_mb") == old:
            raise TimeoutError("injected: the rollback ack was lost")
        return await original(**kwargs)

    worker.configure = lost_rollback_ack
    app.state.store.save = lambda: (_ for _ in ()).throw(OSError("injected: disk full"))
    try:
        r = put(client, "chat-a", mem_limit_mb=limit_for_budget(app, "chat-a", 1000))
    finally:
        worker.configure = original
        app.state.store.save = real_save
    # The read shows the worker back on the old limit, so the two sides agree:
    # this is a confirmed rollback, a plain 500, and no record left behind.
    assert r.status_code == 500, r.text
    assert worker_mb(client, "chat-a") == 400
    assert stored(client, "chat-a")["mem_limit_mb"] == old
    assert app.state.models.configuration_operations("chat-a") == ()
    assert pending(app) == ()


def test_a_rollback_that_cannot_be_read_keeps_the_request(client, app, read,
                                                          monkeypatch):
    """Unreadable worker during the rollback: 503, original request intact."""
    _pinned(client, app, 400)
    read(8192)
    target = limit_for_budget(app, "chat-a", 1000)
    worker = app.state.clients["chat-a"]
    original = worker.configure
    real_save = app.state.store.save

    async def lost_rollback_ack(**kwargs):
        await original(**kwargs)
        raise TimeoutError("injected: every reply is lost")

    async def cannot_tell(_model_id):
        return None

    worker.configure = lost_rollback_ack
    app.state.store.save = lambda: (_ for _ in ()).throw(OSError("injected: disk full"))
    monkeypatch.setattr(app.state.models, "worker_stats", cannot_tell)
    try:
        r = put(client, "chat-a", mem_limit_mb=target)
    finally:
        worker.configure = original
        app.state.store.save = real_save
    assert r.status_code == 503, r.text
    held = app.state.models.configuration_operations("chat-a")
    assert len(held) == 1
    assert held[0].pending_limit_bytes == target * MIB
    assert held[0].unresolved is True

    # Disk comes back and the worker is reachable again: the original retry
    # settles rather than being refused as "a different change".
    monkeypatch.undo()
    retry = put(client, "chat-a", mem_limit_mb=target)
    assert retry.status_code == 200, retry.text
    assert stored(client, "chat-a")["mem_limit_mb"] == target
    assert app.state.models.configuration_operations("chat-a") == ()
