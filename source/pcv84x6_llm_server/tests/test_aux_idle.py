"""Idle auto-unload and on-demand auto-load for the auxiliary models (MYS-2657).

Two behaviours, and both are about *when* a model is resident rather than what
it computes:

* **unload when idle** -- an auxiliary model that has not been used for
  ``aux_idle_unload_min`` minutes is unloaded, giving the NPU and its system RAM
  back. Four conditions must all hold: a managed kind, a non-zero threshold, no
  operation in flight, and an idle worker.
* **load on demand** -- a request that names an auxiliary model which is on disk
  but unloaded loads it and carries on, instead of answering 409.

The mock backend is enough for the first half: an unload is a process kill, and
whether the worker was busy is a number the worker itself reports. For the second
half the tests drive the real mock workers, so a load happens for real and the
409/200 distinction is the real one.

Where time matters the threshold is set to a sub-minute equivalent by driving
``unload_idle`` directly with a back-dated ``last_used_mono``: the sweep is a
plain method, and sleeping for a minute per case would make this file the slowest
in the suite for no extra coverage. ``test_the_sweeper_unloads_on_its_own``
exercises the loop itself, with the interval shortened.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import models as models_mod
from app.core.state import Settings
from app.main import create_app

EMBED_BMODEL = "qwen3-embedding-0.6b_bf16"
RERANK_BMODEL = "bge-reranker-v2-m3_bf16"
ASR_BMODEL = "qwen3-asr-0.6b_bf16"
OCR_BMODEL = "ppocrv6-medium-det_f16_736_bm1684x2_static_20261103.bmodel"
CHAT_BMODEL = "qwen3.6-35b-a3b-int4-autow4bf16"


def make_model(root: Path, name: str, bmodel: str, context: str = "seq2048") -> Path:
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{bmodel}_{context}_4core_static.bmodel").write_bytes(b"\x00" * 4096)
    (d / "config" / "config.json").write_text("{}")
    return d


@pytest.fixture()
def models_dir(tmp_path: Path) -> Path:
    root = tmp_path / "models"
    make_model(root, "embed-model", EMBED_BMODEL)
    make_model(root, "rerank-model", RERANK_BMODEL, context="seq2048")
    make_model(root, "asr-model", ASR_BMODEL, context="seq1024")
    make_model(root, "ocr-model", OCR_BMODEL, context="736")
    make_model(root, "chat-model", CHAT_BMODEL, context="seq2048")
    return root


@pytest.fixture()
def app(tmp_path: Path, models_dir: Path):
    return turn_aux_on(create_app(
        data_dir=tmp_path / "data",
        models_dir=models_dir,
        backend_kind="mock",
        web_dir=tmp_path / "web",
        context_length_override=4096,
    ))


def turn_aux_on(app):
    """Opt in to idle unload (10 min) and on-demand loading, as an operator would.

    Both are off by default since v0.6.28; these tests are about how they behave
    once on. Saved to the store too, so an app restarted on the same data
    directory starts with them on as well.
    """
    st = app.state.store.settings
    st.aux_idle_unload_min, st.aux_auto_load = 10, True
    app.state.store.save()
    app.state.models.aux_idle_unload_min, app.state.models.aux_auto_load = 10, True
    return app


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        yield c


def load(client, *model_ids: str) -> None:
    for model_id in model_ids:
        r = client.post(f"/api/models/{model_id}/load")
        assert r.status_code == 200, r.text


def auth(client) -> dict:
    raw = client.post("/api/keys", json={"name": "pytest"}).json()["key"]
    return {"Authorization": f"Bearer {raw}"}


def model_of(client, model_id: str) -> dict:
    for m in client.get("/api/models").json()["models"]:
        if m["id"] == model_id:
            return m
    raise AssertionError(f"{model_id} is not listed")


def backdate(app, model_id: str, seconds: float) -> None:
    """Pretend the model was last used ``seconds`` ago.

    Both clocks move together: ``last_used_mono`` is what the sweep compares, and
    ``last_used_at`` is the epoch form the API reports. Moving only one would make
    ``idle_unload_at`` describe a model the sweep will not touch -- which is
    precisely the inconsistency the tests are here to rule out.
    """
    info = app.state.models.get(model_id)
    assert info is not None
    info.last_used_mono = time.monotonic() - seconds
    info.last_used_at = time.time() - seconds


def on_app_loop(app, coro, timeout: float = 60.0):
    """Run ``coro`` on the app's own event loop and return its result.

    Not ``asyncio.run``: the manager's locks, its worker processes and the RPC
    clients are all bound to the loop uvicorn/TestClient started, and a fresh
    loop refuses to await a future owned by another one ("attached to a different
    loop"). ``asyncio.run`` also cannot see the client's own threads.
    """
    import concurrent.futures

    loop = app.state.event_loop
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


def new_kb(client, name: str) -> str:
    r = client.post("/api/apps/kb", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["kb"]["id"]


def wait_indexed(client, kb: str, timeout: float = 60.0) -> list[dict]:
    """Poll /docs until the ingest job settles, then return the records."""
    deadline = time.monotonic() + timeout
    docs: list[dict] = []
    while time.monotonic() < deadline:
        docs = client.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
        if docs and all(d["status"] not in ("queued", "parsing", "ocr", "embedding")
                        for d in docs):
            return docs
        time.sleep(0.05)
    raise AssertionError(
        f"documents did not settle in {timeout}s: "
        f"{[(d['name'], d['status']) for d in docs]}")


def upload_text(client, kb: str, filename: str, text: str) -> list[dict]:
    r = client.post(f"/api/apps/kb/{kb}/docs",
                    files={"file": (filename, text.encode(), "text/plain")})
    assert r.status_code == 200, r.text
    return r.json()["docs"]


def sweep(app) -> list[str]:
    """Run one idle sweep on the app's own event loop."""
    return on_app_loop(app, app.state.models.unload_idle())


# ---------------------------------------------------------------------------
# settings: read, write, clamp
# ---------------------------------------------------------------------------
def test_both_features_are_off_by_default():
    """MYS-2293 (user, 11-06): idle unload and on-demand loading default off."""
    s = Settings()
    assert s.aux_idle_unload_min == 0
    assert s.aux_auto_load is False


@pytest.fixture()
def plain_client(tmp_path: Path, models_dir: Path):
    """An app with nothing opted in: what a fresh install starts with."""
    fresh = create_app(data_dir=tmp_path / "plain", models_dir=models_dir,
                       backend_kind="mock", web_dir=tmp_path / "web",
                       context_length_override=4096)
    with TestClient(fresh) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        yield c


def test_a_fresh_install_reports_both_off_and_never_sweeps(plain_client):
    s = plain_client.get("/api/settings").json()
    assert s["aux_idle_unload_min"] == 0
    assert s["aux_auto_load"] is False
    mgr = plain_client.app.state.models
    assert (mgr.aux_idle_unload_min, mgr.aux_auto_load) == (0, False)

    load(plain_client, "embed-model")
    assert model_of(plain_client, "embed-model")["idle_unload_at"] is None
    backdate(plain_client.app, "embed-model", 7 * 24 * 3600)
    assert sweep(plain_client.app) == []
    assert model_of(plain_client, "embed-model")["loaded"] is True


def test_a_fresh_install_answers_409_for_an_unloaded_model(plain_client):
    r = plain_client.post("/v1/embeddings", headers=auth(plain_client),
                          json={"model": "embed-model", "input": "盘点"})
    assert r.status_code == 409, r.text
    assert model_of(plain_client, "embed-model")["loaded"] is False


def _state_file(tmp_path: Path, settings: dict) -> Path:
    import json
    data = tmp_path / "migr"
    (data / "state").mkdir(parents=True, exist_ok=True)
    path = data / "state" / "state.json"
    path.write_text(json.dumps({"keys": [], "settings": settings, "usage": {}}))
    return path


def test_a_v0627_state_file_with_its_defaults_is_turned_off(tmp_path):
    """v0.6.27 saved its on-by-default values with every save; nobody chose them."""
    from app.core.state import StateStore
    path = _state_file(tmp_path, {"aux_idle_unload_min": 10, "aux_auto_load": True})
    st = StateStore(path).settings
    assert (st.aux_idle_unload_min, st.aux_auto_load) == (0, False)


@pytest.mark.parametrize("stored", [
    {"aux_idle_unload_min": 5, "aux_auto_load": True},     # operator changed it
    {"aux_idle_unload_min": 10, "aux_auto_load": False},   # operator changed it
    {"aux_idle_unload_min": 10, "aux_auto_load": True,     # chosen under the new
     "aux_defaults_rev": 1},                               # defaults: keep
])
def test_values_the_operator_chose_are_kept(tmp_path, stored):
    from app.core.state import StateStore
    st = StateStore(_state_file(tmp_path, stored)).settings
    assert (st.aux_idle_unload_min, st.aux_auto_load) == (
        stored["aux_idle_unload_min"], stored["aux_auto_load"])


def test_the_migration_runs_once(tmp_path):
    """After it, the operator turning both back on to 10 / true must stick."""
    from app.core.state import StateStore
    path = _state_file(tmp_path, {"aux_idle_unload_min": 10, "aux_auto_load": True})
    store = StateStore(path)
    store.settings.aux_idle_unload_min, store.settings.aux_auto_load = 10, True
    store.save()
    st = StateStore(path).settings
    assert (st.aux_idle_unload_min, st.aux_auto_load) == (10, True)


def test_settings_round_trip_through_the_api(client):
    r = client.post("/api/settings", json={"aux_idle_unload_min": 3, "aux_auto_load": False})
    assert r.status_code == 200, r.text
    body = r.json()["settings"]
    assert body["aux_idle_unload_min"] == 3
    assert body["aux_auto_load"] is False
    # And the limit the console needs for its field, like max_concurrency_limit.
    assert body["aux_idle_unload_limit_min"] == 1440

    fresh = client.get("/api/settings").json()
    assert fresh["aux_idle_unload_min"] == 3
    assert fresh["aux_auto_load"] is False


@pytest.mark.parametrize("given,want", [(-5, 0), (0, 0), (1440, 1440), (99999, 1440)])
def test_the_idle_threshold_is_clamped_not_refused(client, given, want):
    """Out of range is a typo or a stale spinner, not a reason to fail the save."""
    r = client.post("/api/settings", json={"aux_idle_unload_min": given})
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["aux_idle_unload_min"] == want


def test_a_non_integer_threshold_is_422(client):
    assert client.post("/api/settings",
                       json={"aux_idle_unload_min": "soon"}).status_code == 422


def test_a_saved_setting_reaches_the_manager(client, app):
    """Live, not at the next restart: the sweep reads the manager's own field."""
    client.post("/api/settings", json={"aux_idle_unload_min": 1, "aux_auto_load": False})
    assert app.state.models.aux_idle_unload_min == 1
    assert app.state.models.aux_auto_load is False


# ---------------------------------------------------------------------------
# the model fields the console reads
# ---------------------------------------------------------------------------
def test_every_model_reports_the_three_idle_fields(client):
    fields = {m["id"]: m for m in client.get("/api/models").json()["models"]}
    for model in fields.values():
        assert "last_used_at" in model
        assert "unloaded_reason" in model
        assert "idle_unload_at" in model
    # Not loaded, so nothing to count down to and nothing to remember.
    assert fields["embed-model"]["last_used_at"] is None
    assert fields["embed-model"]["unloaded_reason"] is None
    assert fields["embed-model"]["idle_unload_at"] is None


def test_a_loaded_aux_model_has_a_use_time_and_a_deadline(client):
    load(client, "embed-model")
    m = model_of(client, "embed-model")
    assert m["loaded"] is True
    assert m["last_used_at"] and m["last_used_at"] <= time.time()
    # 10 minutes by default, counted from the use time.
    assert m["idle_unload_at"] == pytest.approx(m["last_used_at"] + 600, abs=2)


def test_a_chat_model_never_gets_a_deadline(client):
    """A 35B takes tens of seconds to load and the agents depend on it."""
    load(client, "chat-model")
    m = model_of(client, "chat-model")
    assert m["loaded"] is True
    assert m["last_used_at"] is not None, "the use clock is still recorded"
    assert m["idle_unload_at"] is None, "but there is no deadline for it"


def test_zero_turns_the_deadline_off_everywhere(client):
    client.post("/api/settings", json={"aux_idle_unload_min": 0})
    load(client, "embed-model")
    assert model_of(client, "embed-model")["idle_unload_at"] is None


# ---------------------------------------------------------------------------
# unload when idle: the four conditions
# ---------------------------------------------------------------------------
def test_an_idle_aux_model_is_unloaded(client, app):
    load(client, "embed-model")
    backdate(app, "embed-model", 11 * 60)
    assert sweep(app) == ["embed-model"]
    m = model_of(client, "embed-model")
    assert m["loaded"] is False
    assert m["pid"] is None
    assert m["unloaded_reason"] == "idle", "the console says why it went"


def test_a_model_within_the_threshold_stays(client, app):
    load(client, "embed-model")
    backdate(app, "embed-model", 5 * 60)
    assert sweep(app) == []
    assert model_of(client, "embed-model")["loaded"] is True
    assert model_of(client, "embed-model")["unloaded_reason"] is None


def test_a_worker_with_a_request_in_flight_is_not_unloaded(client, app):
    """The one unload this feature must never do: killing a worker mid-NPU-call."""
    load(client, "embed-model")

    async def busy(model_id: str) -> int:
        return 1

    app.state.models.worker_inflight = busy
    backdate(app, "embed-model", 60 * 60)
    assert sweep(app) == []
    assert model_of(client, "embed-model")["loaded"] is True


def test_an_unanswerable_inflight_probe_is_treated_as_busy(client, app):
    """Cannot tell is not the same as idle: leave it for the next sweep."""
    load(client, "embed-model")

    async def unknown(model_id: str) -> int | None:
        return None

    app.state.models.worker_inflight = unknown
    backdate(app, "embed-model", 60 * 60)
    assert sweep(app) == []


def test_a_failing_inflight_probe_is_treated_as_busy(client, app):
    load(client, "embed-model")

    async def broken(model_id: str) -> int:
        raise OSError("socket closed")

    app.state.models.worker_inflight = broken
    backdate(app, "embed-model", 60 * 60)
    assert sweep(app) == []
    assert model_of(client, "embed-model")["loaded"] is True


def test_a_model_with_an_operation_in_flight_is_not_unloaded(client, app):
    """``operation`` covers load/unload; a download adds its own flag."""
    load(client, "embed-model")
    backdate(app, "embed-model", 60 * 60)
    info = app.state.models.get("embed-model")

    info.operation = models_mod.LOADING
    try:
        assert sweep(app) == []
    finally:
        info.operation = None

    info.operation = models_mod.UNLOADING
    try:
        assert sweep(app) == []
    finally:
        info.operation = None

    # The download flag comes from the download manager, read through the hook
    # on every access (``_sync_downloading``), so it is the hook that has to say
    # "still writing" here -- setting the attribute would be undone by the read.
    app.state.models.is_downloading = lambda model_id: model_id == "embed-model"
    try:
        assert sweep(app) == []
        assert info.loaded is True
    finally:
        app.state.models.is_downloading = lambda model_id: False


def test_a_chat_model_is_never_auto_unloaded(client, app):
    load(client, "chat-model")
    backdate(app, "chat-model", 24 * 60 * 60)
    assert sweep(app) == []
    assert model_of(client, "chat-model")["loaded"] is True


def test_threshold_zero_never_unloads(client, app):
    client.post("/api/settings", json={"aux_idle_unload_min": 0})
    load(client, "embed-model")
    backdate(app, "embed-model", 7 * 24 * 3600)
    assert sweep(app) == []
    assert model_of(client, "embed-model")["loaded"] is True


def test_a_manual_unload_clears_the_idle_reason(client, app):
    load(client, "embed-model")
    backdate(app, "embed-model", 11 * 60)
    assert sweep(app) == ["embed-model"]
    assert model_of(client, "embed-model")["unloaded_reason"] == "idle"
    # An operator does something with it: load, then unload by hand.
    load(client, "embed-model")
    assert model_of(client, "embed-model")["unloaded_reason"] is None, (
        "loading clears the marker -- it describes the previous residency")
    assert client.post("/api/models/embed-model/unload").status_code == 200
    assert model_of(client, "embed-model")["unloaded_reason"] is None


def test_a_request_resets_the_idle_clock(client, app):
    """Using a model through /v1 is a use, and must postpone its unload."""
    h = auth(client)
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "embed-model", "input": "hello"})
    assert r.status_code == 200, r.text
    first = model_of(client, "embed-model")["last_used_at"]
    time.sleep(0.05)
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "embed-model", "input": "again"})
    assert r.status_code == 200, r.text
    second = model_of(client, "embed-model")["last_used_at"]
    assert second > first, "the second request did not record a use"


def test_the_sweeper_unloads_on_its_own(client, app):
    """The loop, not just the method: the interval shortened for the test.

    The running loop sleeps the interval it read at the *start* of its sleep, so
    the sweeper is restarted after the interval is shortened -- otherwise the
    first pass is still 30 s away and this would only be testing the sleep.
    """
    load(client, "embed-model")
    backdate(app, "embed-model", 11 * 60)
    client.post("/api/settings", json={"aux_idle_unload_min": 1})

    async def drive() -> bool:
        mgr = app.state.models
        await mgr.stop_idle_sweeper()
        mgr.idle_sweep_interval_s = 0.05
        mgr.start_idle_sweeper()
        try:
            for _ in range(200):
                await asyncio.sleep(0.02)
                if not mgr.get("embed-model").loaded:
                    return True
            return False
        finally:
            await mgr.stop_idle_sweeper()

    assert on_app_loop(app, drive()) is True
    assert model_of(client, "embed-model")["unloaded_reason"] == "idle"


def test_the_sweeper_is_idempotent_and_stops(client, app):
    """Two starts must not mean two loops racing to unload the same model."""
    async def drive():
        mgr = app.state.models
        # The lifespan already started one; stopping it first means "first" below
        # is the task this test created.
        await mgr.stop_idle_sweeper()
        mgr.start_idle_sweeper()
        first = mgr._idle_task
        mgr.start_idle_sweeper()
        assert mgr._idle_task is first, "a second start must not create a second loop"
        await mgr.stop_idle_sweeper()
        assert mgr._idle_task is None
        await mgr.stop_idle_sweeper()  # safe when nothing is running

    on_app_loop(app, drive())


# ---------------------------------------------------------------------------
# load on demand: /v1 and /api/test
# ---------------------------------------------------------------------------
def test_an_unloaded_embedding_model_is_loaded_by_the_request(client):
    h = auth(client)
    assert model_of(client, "embed-model")["loaded"] is False
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "embed-model", "input": "hello world"})
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) == 1
    assert model_of(client, "embed-model")["loaded"] is True


def test_an_unloaded_rerank_model_is_loaded_by_the_request(client):
    h = auth(client)
    r = client.post("/v1/rerank", headers=h, json={
        "model": "rerank-model", "query": "盘亏", "documents": ["盘点差异"]})
    assert r.status_code == 200, r.text
    assert model_of(client, "rerank-model")["loaded"] is True


def test_the_console_test_proxies_load_on_demand_too(client):
    """/api/test/* is the same handler, so it inherits the behaviour."""
    r = client.post("/api/test/embeddings",
                    json={"model": "embed-model", "input": "console"})
    assert r.status_code == 200, r.text
    assert model_of(client, "embed-model")["loaded"] is True


def test_auto_load_off_answers_409_naming_the_setting(client):
    client.post("/api/settings", json={"aux_auto_load": False})
    h = auth(client)
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "embed-model", "input": "hi"})
    assert r.status_code == 409, r.text
    assert "自动加载已关闭" in r.json()["detail"]
    assert model_of(client, "embed-model")["loaded"] is False


def test_a_failed_auto_load_answers_409_with_the_reason(client, app, monkeypatch):
    """The same refusal the console's Load button produces, same message."""
    async def refuse(model_id: str):
        raise RuntimeError("设备内存不足：需要 1.5 GiB，当前只剩 0.2 GiB")

    monkeypatch.setattr(app.state.models, "load", refuse)
    h = auth(client)
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "embed-model", "input": "hi"})
    assert r.status_code == 409, r.text
    assert "设备内存不足" in r.json()["detail"]


def test_concurrent_requests_for_one_unloaded_model_load_it_once(tmp_path):
    """Three callers, one worker: ``load`` joins an in-flight load.

    A real uvicorn on a random port, not ``TestClient``: the latter serialises
    requests through one portal, so the second request would always start after
    the first one returned -- exactly the ordering in which the bug cannot
    happen.

    The count is of *workers spawned*, not of ``load()`` calls: each request
    legitimately calls ``load``, and the property under test is that only one of
    them gets past the in-flight check to spawn a process. Three workers on one
    bmodel is the failure this rules out (three allocations on the NPU heap).
    """
    import socket
    import threading
    import uvicorn
    import httpx

    models = tmp_path / "models"
    make_model(models, "embed-model", EMBED_BMODEL)
    app = turn_aux_on(create_app(data_dir=tmp_path / "data", models_dir=models,
                                 backend_kind="mock", web_dir=tmp_path / "web",
                                 context_length_override=4096))

    spawns: list[str] = []
    loads: list[str] = []
    original_spawn = asyncio.create_subprocess_exec
    original_load = app.state.models._load_locked

    async def counting_spawn(*args, **kwargs):
        spawns.append(str(args[0]))
        return await original_spawn(*args, **kwargs)

    async def counting_load(info):
        loads.append(info.model_id)
        return await original_load(info)

    asyncio.create_subprocess_exec = counting_spawn
    app.state.models._load_locked = counting_load

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not server.started:
            time.sleep(0.02)
        assert server.started, "uvicorn did not start"

        with httpx.Client(base_url=base, timeout=120) as http:
            assert http.post("/api/login", json={"password": "admin"}).status_code == 200
            key = http.post("/api/keys", json={"name": "race"}).json()["key"]
            headers = {"Authorization": f"Bearer {key}"}

            async def fire_all() -> list[int]:
                async with httpx.AsyncClient(base_url=base, timeout=120) as ac:
                    replies = await asyncio.gather(*[
                        ac.post("/v1/embeddings", headers=headers,
                                json={"model": "embed-model", "input": f"text {i}"})
                        for i in range(3)])
                    return [r.status_code for r in replies]

        codes = asyncio.run(fire_all())
        assert codes == [200, 200, 200], codes
        # All three asked; exactly one spawned a worker. ``_load_locked`` runs
        # under the per-model lock, so more than one call means the join in
        # ``load`` did not hold.
        assert len(spawns) == 1, f"spawned {len(spawns)} workers"
        assert len(loads) == 1, f"_load_locked ran {len(loads)} times"
        # One worker, and it is the model under test (not a stray from another
        # fixture sharing the process).
        assert loads == ["embed-model"]
    finally:
        asyncio.create_subprocess_exec = original_spawn
        server.should_exit = True
        thread.join(timeout=30)


def test_an_unloaded_chat_model_is_still_refused(client):
    """The line the design draws: auxiliary models load on demand, chat does not."""
    h = auth(client)
    r = client.post("/v1/chat/completions", headers=h, json={
        "model": "chat-model",
        "messages": [{"role": "user", "content": "hi"}], "max_tokens": 4})
    assert r.status_code == 409, r.text
    assert model_of(client, "chat-model")["loaded"] is False


def test_a_kind_mismatch_does_not_load_anything(client):
    """Wrong endpoint for an unloaded model is 400, and stays cheap."""
    h = auth(client)
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "chat-model", "input": "hi"})
    assert r.status_code == 400, r.text
    assert "/v1/chat/completions" in r.json()["detail"]
    assert model_of(client, "chat-model")["loaded"] is False


# ---------------------------------------------------------------------------
# load on demand: knowledge base and MCP
# ---------------------------------------------------------------------------
def test_a_knowledge_base_search_loads_both_aux_models(client):
    """Vector and rerank stages run with nothing preloaded.

    What it proves is the whole chain: the resolver loads what it needs, the
    stages stop skipping, and the search still returns a reranked result.
    """
    kb = new_kb(client, "空闲测试")
    upload_text(client, kb, "制度.txt",
                "仓库盘点由仓管员执行。盘点差异率超过千分之五须由财务复核。"
                "消防通道不得堆放物料。")
    docs = wait_indexed(client, kb)
    assert docs[0]["status"] == "ready", docs
    assert model_of(client, "embed-model")["loaded"] is True, "建库时应自动加载"
    assert model_of(client, "rerank-model")["loaded"] is False, "建库不需要精排"

    # Unload both, as an idle sweep would have done overnight.
    for mid in ("embed-model", "rerank-model"):
        client.post(f"/api/models/{mid}/unload")
    assert model_of(client, "embed-model")["loaded"] is False

    r = client.post(f"/api/apps/kb/{kb}/search", json={"query": "盘点差异", "top_k": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    for stage in ("bm25", "vector", "fusion", "rerank"):
        assert body["stages"][stage]["status"] == "ok", (stage, body["stages"][stage])
    assert model_of(client, "embed-model")["loaded"] is True
    assert model_of(client, "rerank-model")["loaded"] is True


def test_auto_load_off_skips_the_stages_with_a_reason(client):
    kb = new_kb(client, "关闭自动加载")
    upload_text(client, kb, "a.txt", "仓库盘点由仓管员执行。盘点差异率须由财务复核。")
    assert wait_indexed(client, kb)[0]["status"] == "ready"

    client.post("/api/settings", json={"aux_auto_load": False})
    client.post("/api/models/embed-model/unload")
    client.post("/api/models/rerank-model/unload")

    r = client.post(f"/api/apps/kb/{kb}/search", json={"query": "盘点", "top_k": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stages"]["bm25"]["status"] == "ok"
    assert body["stages"]["vector"]["status"] == "skipped"
    assert "自动加载已关闭" in body["stages"]["vector"]["reason"]
    assert body["stages"]["rerank"]["status"] == "skipped"


def test_mcp_ocr_read_loads_the_ocr_model(client):
    """``ocr_read`` on an image with no OCR model loaded."""
    source = Path(__file__).resolve().parent / "data" / "ocr" / "img" / "ui_status.png"
    if not source.exists():  # pragma: no cover - the fixture set is checked elsewhere
        pytest.skip("no OCR image fixture available")
    load(client, "chat-model")  # an agent always has a chat model up
    client.post("/api/models/ocr-model/unload")
    assert model_of(client, "ocr-model")["loaded"] is False

    target = Path(client.app.state.agents.data_root) / "inbox" / "shot.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())

    raw = client.post("/api/keys", json={"name": "mcp"}).json()["key"]
    r = client.post("/mcp", headers={"Authorization": f"Bearer {raw}"}, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "ocr_read", "arguments": {"path": str(target)}}})
    assert r.status_code == 200, r.text
    payload = r.json()
    assert "error" not in payload, payload
    structured = payload["result"].get("structuredContent") or {}
    assert structured.get("ocr") is True, payload["result"]
    assert model_of(client, "ocr-model")["loaded"] is True


# ---------------------------------------------------------------------------
# the worker's real inflight count, which the sweep depends on
# ---------------------------------------------------------------------------
def test_the_aux_worker_reports_its_own_inflight_count(client, app):
    """A constant 0 would let the sweep unload a model that is mid-request."""
    load(client, "embed-model")

    async def read() -> dict:
        return await app.state.clients["embed-model"].stats()

    stats = on_app_loop(app, read())
    assert stats["op"] == "stats"
    assert stats["inflight"] == 0, "idle worker"
    assert "queued" in stats


def test_the_gate_counts_admitted_requests():
    """The number the worker reports, asserted on the object that produces it.

    ``inflight`` reads ``_Serialised.active``, which every auxiliary backend
    holds as ``_gate``. Driving the gate here is what makes the count checkable
    without putting a second request into a worker that serves one at a time.
    """
    from app.engine import aux_backend

    gate = aux_backend._Serialised(max_queue=2)
    assert gate.active == 0

    async def observe() -> list[int]:
        seen: list[int] = []

        async def holder():
            async with gate.slot():
                seen.append(gate.active)
                await asyncio.sleep(0.05)

        task = asyncio.create_task(holder())
        await asyncio.sleep(0.01)
        seen.append(gate.active)
        await task
        seen.append(gate.active)
        return seen

    assert asyncio.run(observe()) == [1, 1, 0]


# ---------------------------------------------------------------------------
# lead review: the probe window and long jobs
# ---------------------------------------------------------------------------
def test_a_request_during_the_busy_probe_cancels_the_unload(client, app):
    """The sweep's probe is an RPC; a request that resolves while it is in flight
    touches the model, and the unload must not go ahead on the stale decision."""
    load(client, "embed-model")
    mgr = app.state.models

    async def probe_while_a_request_arrives(model_id: str) -> int:
        mgr.touch(model_id)  # the request resolved during the probe
        return 0             # ...but the worker has not admitted it yet

    mgr.worker_inflight = probe_while_a_request_arrives
    backdate(app, "embed-model", 60 * 60)
    assert sweep(app) == []
    assert model_of(client, "embed-model")["loaded"] is True


def test_unload_refuses_when_used_since_the_snapshot(client, app):
    load(client, "embed-model")
    mgr = app.state.models
    since = mgr.get("embed-model").last_used_mono
    mgr.touch("embed-model")
    from app.core.models import ModelBusy

    with pytest.raises(ModelBusy):
        on_app_loop(app, mgr.unload("embed-model", if_unused_since=since))
    assert model_of(client, "embed-model")["loaded"] is True


def test_every_inference_call_marks_the_model_used(client, app):
    """A long job (library build, multi-page OCR) is many calls; each one must
    restart the idle clock, not only the request that started the job."""
    load(client, "embed-model")
    backdate(app, "embed-model", 60 * 60)
    rpc = app.state.clients["embed-model"]
    assert rpc.on_activity is not None
    on_app_loop(app, rpc.embed("rid-1", ["hello"]))
    info = app.state.models.get("embed-model")
    assert time.monotonic() - info.last_used_mono < 30
    assert rpc.active == 0


def test_the_api_side_count_makes_the_worker_look_busy(client, app):
    load(client, "embed-model")
    rpc = app.state.clients["embed-model"]
    rpc.active = 1  # a call sent but not yet admitted by the worker
    try:
        backdate(app, "embed-model", 60 * 60)
        assert sweep(app) == []
    finally:
        rpc.active = 0
