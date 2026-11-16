"""A model accepts inference only after it is completely ready (MYS-2496).

The defect this pins: ``ModelManager._load_locked`` published ``loaded: true``
and registered the RPC client *before* it probed the worker's capabilities, and
swallowed any probe failure. Two consequences, both reachable in production:

* a model read as loaded while the engine was unready, so the OpenAI surface and
  the console dispatched inferences into a half-initialised worker -- the kind of
  path that produces a wrong answer rather than an error;
* a capability that came back wrong or not at all was kept as the file-name
  guess, and nothing in ``/api/models`` said so.

Every test here drives the **real** HTTP surface and the real manager. Only the
initialisation step itself is replaced (``_confirm_initialised``), because that
is the one thing a laptop cannot do: ``stats`` and ``health`` from a real NPU
worker. Everything the fix is about -- what a request may do while that step is
in flight, what the state machine looks like when it fails, whether a record was
written -- is exercised as written.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.models import ModelBusy, ModelManager, ModelNotLoaded
from app.main import create_app


def make_model(root: Path, name: str = "m") -> Path:
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{name}_int4_w4bf16_seq2048_4core_dynamic.bmodel").write_bytes(b"\x00" * 1024)
    (d / "config" / "config.json").write_text("{}")
    return d


@pytest.fixture()
def app_and_client(tmp_path):
    models = tmp_path / "models"
    make_model(models, "m")
    app = create_app(
        data_dir=tmp_path / "data", models_dir=models, backend_kind="mock",
        web_dir=tmp_path / "web", context_length_override=4096,
    )
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        yield app, c


def model_of(c, model_id: str = "m") -> dict:
    return {m["id"]: m for m in c.get("/api/models").json()["models"]}[model_id]


def record_count(app) -> int:
    return app.state.inference_log.count()


def wait_for(predicate, timeout: float = 30.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def hold_initialisation(app, *, ready_on: threading.Event | None = None,
                        fail_with: BaseException | str | None = None):
    """Replace the capability probe with one the test controls.

    ``ready_on`` gates *success*: the load sits in ``loading`` until the test
    sets the event. ``fail_with`` raises immediately instead -- which is the
    capability-failure path.

    The seam is ``_probe_capabilities``, not ``_confirm_initialised``: the
    latter is the code under test (it is what records ``load_error`` and
    unwinds), so replacing it would test the mock instead of the fix.

    A ``threading.Event`` because the release happens on the test's thread while
    the app's event loop serves the polling requests -- an ``asyncio.Event`` is
    not thread-safe, and a blocking wait would freeze the service these tests
    need responsive.
    """
    ready = ready_on or threading.Event()
    mgr = app.state.models

    async def probe(port, info, settle_timeout=30.0):
        if fail_with is not None:
            raise fail_with if isinstance(fail_with, BaseException) else RuntimeError(fail_with)
        for _ in range(1500):  # 30 s ceiling, same as the real readiness wait
            if ready.is_set():
                return
            await asyncio.sleep(0.02)
        raise RuntimeError("能力探测超时（测试门控）")

    mgr._probe_capabilities = probe
    return ready


def start_load(c, model_id: str = "m") -> tuple[threading.Thread, dict]:
    """Kick off a load from another thread, the way a second browser would."""
    result: dict = {}

    def run():
        result["r"] = c.post(f"/api/models/{model_id}/load")

    t = threading.Thread(target=run)
    t.start()
    return t, result


def wait_loading(c, model_id: str = "m", timeout: float = 30.0,
                 with_pid: bool = False) -> dict:
    """Poll until the model reports ``operation == "loading"``.

    ``loading`` is published before the worker is spawned, so a caller that
    asserts on the process (``with_pid``) must also wait for the pid: reading the
    first ``loading`` snapshot raced the spawn and failed ~2 runs in 5.
    """
    deadline = time.monotonic() + timeout
    seen: dict = {}
    while time.monotonic() < deadline:
        seen = model_of(c, model_id)
        if seen.get("operation") == "loading" and (seen.get("pid") or not with_pid):
            return seen
        time.sleep(0.02)
    raise AssertionError(f"the load never published `loading`; last seen {seen}")


# ---------------------------------------------------------------------------
# the reported defect: inference admitted while the model is not ready
# ---------------------------------------------------------------------------
def test_no_inference_is_admitted_while_capabilities_are_unconfirmed(
        app_and_client, monkeypatch):
    """The whole point: `loading` must refuse every inference path, and write
    no record.

    Before the fix ``loaded`` was already true here, the client already
    registered, and all three routes would have dispatched into a worker whose
    capabilities had not been read -- with an inference record created for each.
    """
    app, c = app_and_client
    ready = hold_initialisation(app)
    key = c.post("/api/keys", json={"name": "k"}).json()["key"]
    auth = {"Authorization": f"Bearer {key}"}
    body = {"model": "m", "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 4}
    before = record_count(app)

    t, result = start_load(c)
    try:
        seen = wait_loading(c, with_pid=True)
        # The state a console reload must show.
        assert seen["loaded"] is False, seen
        assert seen["operation_since"] is not None
        assert seen["pid"], "the process exists while the model is not usable"
        assert "m" not in app.state.clients, (
            "a client must not exist for a model that is not ready")

        # Non-streaming OpenAI.
        r = c.post("/v1/chat/completions", headers=auth, json=body)
        assert r.status_code == 409, (r.status_code, r.text)
        assert "加载中" in r.json()["detail"]

        # Streaming OpenAI: a 409, not a half-open SSE stream.
        r = c.post("/v1/chat/completions", headers=auth, json={**body, "stream": True})
        assert r.status_code == 409, (r.status_code, r.text)

        # The console's two paths.
        r = c.post("/api/chat", json={"model": "m", "prompt": "hi", "max_tokens": 4})
        assert r.status_code == 409, (r.status_code, r.text)
        r = c.post("/api/chat/stream", json={"model": "m", "prompt": "hi",
                                             "max_tokens": 4})
        assert r.status_code == 409, (r.status_code, r.text)

        # Not one of those refusals reached the model.
        assert record_count(app) == before, (
            "a refused inference must not produce a record")
        # And /v1/models does not advertise a model that cannot serve.
        listed = c.get("/v1/models", headers=auth).json()["data"]
        assert [m["id"] for m in listed] == []

        # Still loading: the refusals changed nothing.
        assert model_of(c)["operation"] == "loading"
    finally:
        ready.set()
        t.join(timeout=60)

    assert result["r"].status_code == 200, result["r"].text
    done = model_of(c)
    assert done["loaded"] is True and done["operation"] is None
    assert "m" in app.state.clients
    # Now the same request succeeds, and produces exactly one record.
    r = c.post("/v1/chat/completions", headers=auth, json=body)
    assert r.status_code == 200, r.text
    assert record_count(app) == before + 1


def test_a_capability_failure_leaves_the_model_unloaded_and_idle(
        app_and_client):
    """The probe failing is a failed load: no `loaded`, no client, error shown.

    The pre-fix version swallowed the probe's exception and kept the model
    loaded with file-name capabilities -- a model that would serve with an
    engine nobody had confirmed.
    """
    app, c = app_and_client
    hold_initialisation(app, fail_with=RuntimeError("stats 无响应"))
    before = record_count(app)

    r = c.post("/api/models/m/load")
    assert r.status_code == 409, (r.status_code, r.text)
    assert "能力探测" in r.json()["detail"]

    m = model_of(c)
    assert m["loaded"] is False
    assert m["operation"] is None, "a failed probe must not leave the console locked"
    assert m["pid"] is None and m["port"] is None, "the worker was cleaned up"
    assert m["load_error"], "the operator needs the reason"
    assert "能力探测失败" in m["load_error"]
    assert "m" not in app.state.clients, "no client may survive a failed load"
    assert app.state.models.worker_pids() == set(), "the worker process is gone"
    assert record_count(app) == before

    # And the model is loadable again once the cause is fixed.
    app.state.models._probe_capabilities = (
        lambda port, info, settle_timeout=30.0: asyncio.sleep(0))
    r = c.post("/api/models/m/load")
    assert r.status_code == 200, r.text
    assert model_of(c)["loaded"] is True


def test_a_cancelled_initialisation_unwinds_to_idle(app_and_client):
    """Cancelling mid-probe (a shutdown) must not leave a loaded ghost."""
    app, c = app_and_client
    hold_initialisation(app, fail_with=asyncio.CancelledError())

    # Cancelling an in-flight request cancels the TestClient's own portal call,
    # so the exception surfaces there rather than as a status code. What the fix
    # is responsible for is the state left behind, which is read below.
    with contextlib.suppress(BaseException):
        c.post("/api/models/m/load")
    m = model_of(c)
    assert m["loaded"] is False and m["operation"] is None
    assert m["pid"] is None and m["port"] is None
    assert "m" not in app.state.clients


def test_a_worker_that_exits_during_initialisation_is_cleaned_up(
        app_and_client, monkeypatch):
    """Worker death between the handshake and the probe: not loaded, not stuck."""
    import app.core.models as models_mod

    app, c = app_and_client
    mgr = app.state.models
    real_spawn = asyncio.create_subprocess_exec
    spawned: list = []

    async def counting_spawn(*a, **kw):
        proc = await real_spawn(*a, **kw)
        spawned.append(proc)
        return proc

    async def die_then_probe(port, info):
        # The process the load just spawned goes away, exactly as an OOM kill
        # would look to the manager: returncode set, socket closed.
        proc = spawned[0]
        proc.kill()
        await proc.wait()
        raise RuntimeError("worker exited during initialisation")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", counting_spawn)
    monkeypatch.setattr(mgr, "_confirm_initialised", die_then_probe)

    r = c.post("/api/models/m/load")
    assert r.status_code == 409, (r.status_code, r.text)
    m = model_of(c)
    assert m["loaded"] is False and m["operation"] is None
    assert m["pid"] is None and m["port"] is None
    assert m["load_error"]
    assert "m" not in app.state.clients
    # No hang: the request returned, and the service is still serving.
    assert c.get("/healthz").status_code == 200
    assert models_mod.LOADING  # the constant the state machine publishes


def test_concurrent_loads_join_one_worker_and_publish_once(app_and_client,
                                                           monkeypatch):
    """Two clicks, one worker, and `loaded` flipped exactly once.

    Joining is only correct if the joiners see the same fully-probed model: the
    old code published `loaded` early, so a joiner could return a model that
    was still being probed while the first caller probed it.
    """
    app, c = app_and_client
    ready = hold_initialisation(app)
    spawned: list[int] = []
    real_spawn = asyncio.create_subprocess_exec

    async def counting_spawn(*a, **kw):
        proc = await real_spawn(*a, **kw)
        spawned.append(proc.pid)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", counting_spawn)

    results: list = []
    lock = threading.Lock()

    def one():
        r = c.post("/api/models/m/load")
        with lock:
            results.append(r)

    threads = [threading.Thread(target=one) for _ in range(3)]
    for t in threads:
        t.start()
    try:
        wait_loading(c)
    finally:
        ready.set()
        for t in threads:
            t.join(timeout=60)

    assert len(spawned) == 1, f"expected one worker, spawned {spawned}"
    assert [r.status_code for r in results] == [200, 200, 200], [
        (r.status_code, r.text) for r in results]
    done = model_of(c)
    assert done["loaded"] is True and done["operation"] is None
    assert done["pid"] == spawned[0]


# ---------------------------------------------------------------------------
# the switch: unload must not expose a loaded model without a client
# ---------------------------------------------------------------------------
def test_requests_are_refused_while_a_model_is_unloading(app_and_client,
                                                         monkeypatch):
    """`unloading` is published before the client is destroyed, and it refuses.

    The race this closes: the route used to pop and close the client *before*
    `mgr.unload` set `operation`, so a request arriving in that window found
    `loaded: true` and no socket.
    """
    app, c = app_and_client
    assert c.post("/api/models/m/load").status_code == 200
    key = c.post("/api/keys", json={"name": "k"}).json()["key"]
    auth = {"Authorization": f"Bearer {key}"}

    mgr = app.state.models
    gate = threading.Event()

    async def slow_terminate(model_id):
        # Hold the unload inside `unloading`, after the client is gone.
        while not gate.is_set():
            await asyncio.sleep(0.02)
        await original_terminate(model_id)

    original_terminate = mgr._terminate
    monkeypatch.setattr(mgr, "_terminate", slow_terminate)

    result: dict = {}

    def run():
        try:
            result["r"] = c.post("/api/models/m/unload")
        except BaseException as exc:  # surfaced below, never swallowed
            result["error"] = exc

    t = threading.Thread(target=run)
    t.start()
    try:
        assert wait_for(lambda: model_of(c)["operation"] == "unloading"), \
            "the unload never published `unloading`"
        # The client is already gone -- that is the ordering under test.
        assert "m" not in app.state.clients
        r = c.post("/v1/chat/completions", headers=auth, json={
            "model": "m", "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 4})
        assert r.status_code == 409, (r.status_code, r.text)
        assert "卸载" in r.json()["detail"]
        r = c.post("/api/chat", json={"model": "m", "prompt": "hi", "max_tokens": 4})
        assert r.status_code == 409, (r.status_code, r.text)
        assert c.get("/v1/models", headers=auth).json()["data"] == []
    finally:
        gate.set()
        t.join(timeout=60)

    assert "error" not in result, result.get("error")
    assert result["r"].status_code == 200, result["r"].text
    assert model_of(c)["loaded"] is False


def test_require_ready_is_the_one_admission_rule(app_and_client):
    """The manager answers, not each route: three refusals, three meanings."""
    app, c = app_and_client
    mgr: ModelManager = app.state.models

    with pytest.raises(KeyError):
        mgr.require_ready("nope")

    with pytest.raises(ModelNotLoaded, match="not loaded"):
        mgr.require_ready("m")

    info = mgr.get("m")
    info.operation = "loading"
    with pytest.raises(ModelBusy, match="加载中"):
        mgr.require_ready("m")
    info.operation = "unloading"
    with pytest.raises(ModelBusy, match="卸载中"):
        mgr.require_ready("m")
    info.operation = None

    assert c.post("/api/models/m/load").status_code == 200
    assert mgr.require_ready("m") is info


def test_a_load_error_is_reported_in_the_refusal(app_and_client):
    """The 409 tells the client why, including the last failure."""
    app, c = app_and_client
    hold_initialisation(app, fail_with=RuntimeError("vision 初始化失败"))
    assert c.post("/api/models/m/load").status_code == 409
    key = c.post("/api/keys", json={"name": "k"}).json()["key"]
    r = c.post("/v1/chat/completions",
               headers={"Authorization": f"Bearer {key}"},
               json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 409, r.text
    assert "last load failed" in r.json()["detail"]
    assert "vision 初始化失败" in r.json()["detail"]
