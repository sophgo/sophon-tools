"""Per-model settings: idle unload, on-demand load, and a memory ceiling (MYS-2675).

Three things an operator can configure **per model**, each with a default that
is a different kind of thing:

* ``idle_unload_min`` / ``auto_load`` -- ``null`` follows the *global* setting,
  whose meaning is now "the value a model nobody configured uses". That default
  still applies only to ``AUX_KINDS``, which is what keeps every existing
  install behaving identically: turning the global switch on does not suddenly
  put a 35B under the idle machinery.
* ``mem_limit_mb`` -- ``null`` follows a figure **derived from the model**, and
  the default must be large enough that every case that works today keeps
  working. That is the property most of these tests exist to pin.

The service is driven through its HTTP surface here, like ``test_aux_idle.py``:
the settings are persisted state, the effective values are computed by the
manager, and what an operator sees is the JSON. The memory arithmetic itself is
unit-tested in ``test_mem_limit.py``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import mem_limit
from app.core.state import MEM_LIMIT_MB_MIN, ModelSettings, StateStore
from app.main import create_app

EMBED_BMODEL = "qwen3-embedding-0.6b_bf16"
RERANK_BMODEL = "bge-reranker-v2-m3_bf16"
CHAT_BMODEL = "qwen3.6-35b-a3b-int4-autow4bf16"


#: The fixture bmodel's size. On a host there is no libbmrt, so ``static_bytes``
#: falls back to the file size -- and the arithmetic assertions below need a
#: figure that is (a) not 0 MiB, or they would be vacuous, and (b) comfortably
#: above ``MEM_LIMIT_MB_MIN``, or "set a limit below the static footprint" could
#: not be constructed at all (the API floor is 64 MiB).
BIG_ENOUGH = 256 * 1024 * 1024


def make_model(root: Path, name: str, bmodel: str, context: str = "seq2048",
               size: int = BIG_ENOUGH) -> Path:
    d = root / name
    (d / "config").mkdir(parents=True)
    # Sparse: a 256 MiB fixture per model would otherwise cost a gigabyte of
    # writes per test, and nothing reads the contents.
    with open(d / f"{bmodel}_{context}_4core_static.bmodel", "wb") as fh:
        fh.truncate(size)
    (d / "config" / "config.json").write_text("{}")
    return d


@pytest.fixture()
def models_dir(tmp_path: Path) -> Path:
    root = tmp_path / "models"
    make_model(root, "embed-a", EMBED_BMODEL)
    make_model(root, "embed-b", EMBED_BMODEL)
    make_model(root, "rerank-model", RERANK_BMODEL, context="seq2048")
    make_model(root, "chat-model", CHAT_BMODEL, context="seq2048")
    return root


def build(tmp_path: Path, models_dir: Path, name: str = "data"):
    return create_app(data_dir=tmp_path / name, models_dir=models_dir,
                      backend_kind="mock", web_dir=tmp_path / "web",
                      context_length_override=4096)


@pytest.fixture()
def app(tmp_path: Path, models_dir: Path):
    """An app with the global auxiliary defaults on, as v0.6.27 shipped them.

    The global values being *on* is what makes the per-model tests meaningful:
    with them off, "the model was not unloaded" would be true for the trivial
    reason and would not exercise the fallback at all.
    """
    application = build(tmp_path, models_dir)
    st = application.state.store.settings
    st.aux_idle_unload_min, st.aux_auto_load = 10, True
    application.state.store.save()
    application.state.models.aux_idle_unload_min = st.aux_idle_unload_min
    application.state.models.aux_auto_load = st.aux_auto_load
    return application


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        yield c


def load(client, *model_ids: str) -> None:
    for model_id in model_ids:
        r = client.post(f"/api/models/{model_id}/load")
        assert r.status_code == 200, r.text


def model_of(client, model_id: str) -> dict:
    for m in client.get("/api/models").json()["models"]:
        if m["id"] == model_id:
            return m
    raise AssertionError(f"{model_id} is not listed")


def put_settings(client, model_id: str, **body):
    return client.put(f"/api/models/{model_id}/settings", json=body)


def backdate(app, model_id: str, seconds: float) -> None:
    info = app.state.models.get(model_id)
    assert info is not None
    info.last_used_mono = time.monotonic() - seconds
    info.last_used_at = time.time() - seconds


def sweep(app) -> list[str]:
    import asyncio

    return asyncio.run_coroutine_threadsafe(
        app.state.models.unload_idle(), app.state.event_loop).result(timeout=60)


# ---------------------------------------------------------------------------
# the shape of the settings
# ---------------------------------------------------------------------------
def test_every_model_reports_settings_effective_and_memory(client):
    """The three groups the console's card needs, on both list and detail."""
    for m in client.get("/api/models").json()["models"]:
        # What the operator stored: nulls mean "follow the default", not zero.
        assert m["settings"] == {"idle_unload_min": None, "auto_load": None,
                                 "mem_limit_mb": None}
        # What is in force. For an auxiliary kind that is the global default...
        expected_auto = m["kind"] == "embedding" or m["kind"] in ("rerank", "asr", "ocr")
        assert m["effective"]["auto_load"] is expected_auto
        assert m["effective"]["idle_unload_min"] == (10 if expected_auto else 0)
        # ...and for every model, a derived ceiling and its static footprint.
        assert m["mem_limit_default_bytes"] > 0
        assert m["effective"]["mem_limit_bytes"] == m["mem_limit_default_bytes"]
        assert m["mem_static_bytes"] > 0
        assert m["mem_used_bytes"] is None, "not loaded, so nothing is in use"


def test_the_detail_route_adds_the_bounds_and_the_auto_load_note(client):
    body = client.get("/api/models/embed-a/settings").json()
    assert body["id"] == "embed-a"
    assert body["limits"]["idle_unload_min_max"] == 1440
    assert body["limits"]["mem_limit_mb_min"] == MEM_LIMIT_MB_MIN
    # A 35B takes tens of seconds, so the interface has to say so before an
    # operator turns on-demand loading on for one.
    assert "几十秒" in body["auto_load_note"]


def test_an_unknown_model_is_404_on_both_routes(client):
    assert client.get("/api/models/nope/settings").status_code == 404
    assert put_settings(client, "nope", auto_load=True).status_code == 404


# ---------------------------------------------------------------------------
# reading and writing, validation, null = follow the default
# ---------------------------------------------------------------------------
def test_a_setting_round_trips_and_persists(client, app):
    r = put_settings(client, "embed-a", idle_unload_min=1, auto_load=False,
                     mem_limit_mb=2048)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["settings"] == {"idle_unload_min": 1, "auto_load": False,
                                "mem_limit_mb": 2048}
    assert body["effective"]["idle_unload_min"] == 1
    assert body["effective"]["auto_load"] is False
    assert body["effective"]["mem_limit_bytes"] == 2048 * 1024 * 1024

    # On disk, and readable by a fresh store over the same file.
    path = app.state.store.path
    saved = json.loads(path.read_text())
    assert saved["model_settings"]["embed-a"]["idle_unload_min"] == 1
    assert saved["model_settings"]["embed-a"]["mem_limit_mb"] == 2048
    assert StateStore(path).get_model_settings("embed-a").mem_limit_mb == 2048


def test_null_resets_a_field_to_its_default(client):
    put_settings(client, "embed-a", idle_unload_min=1, mem_limit_mb=2048)
    r = put_settings(client, "embed-a", idle_unload_min=None, mem_limit_mb=None)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["settings"]["idle_unload_min"] is None
    assert body["settings"]["mem_limit_mb"] is None
    # Back to the global threshold and the derived ceiling.
    assert body["effective"]["idle_unload_min"] == 10
    assert body["effective"]["mem_limit_bytes"] == body["mem_limit_default_bytes"]


def test_an_absent_field_is_left_alone(client):
    """A console that sends only the switch the operator moved patches one field."""
    put_settings(client, "embed-a", idle_unload_min=3, mem_limit_mb=2048)
    r = put_settings(client, "embed-a", auto_load=False)
    assert r.status_code == 200, r.text
    assert r.json()["settings"] == {"idle_unload_min": 3, "auto_load": False,
                                    "mem_limit_mb": 2048}


@pytest.mark.parametrize("body,why", [
    ({"idle_unload_min": -1}, "negative minutes"),
    ({"idle_unload_min": 1441}, "past the field's own bound"),
    ({"mem_limit_mb": 0}, "below the floor"),
    ({"mem_limit_mb": MEM_LIMIT_MB_MIN - 1}, "just below the floor"),
    ({"mem_limit_mb": 1024 * 1024 + 1}, "past the ceiling"),
])
def test_out_of_range_values_are_refused_not_clamped(client, body, why):
    """Unlike /api/settings, which clamps: a limit is a protection, not a spinner."""
    r = put_settings(client, "embed-a", **body)
    assert r.status_code == 400, f"{why}: {r.text}"
    # And nothing was stored.
    assert client.get("/api/models/embed-a/settings").json()["settings"] == {
        "idle_unload_min": None, "auto_load": None, "mem_limit_mb": None}


def test_a_bool_is_not_an_integer(client):
    r = put_settings(client, "embed-a", mem_limit_mb=True)
    assert r.status_code == 400, r.text


def test_a_non_integer_is_422(client):
    assert put_settings(client, "embed-a", mem_limit_mb="lots").status_code == 422


def test_a_settings_change_is_refused_while_an_operation_is_in_flight(client, app):
    """The limit is read at spawn; a change during a load applies to neither side."""
    from app.core import models as models_mod

    info = app.state.models.get("embed-a")
    info.operation = models_mod.LOADING
    try:
        assert put_settings(client, "embed-a", auto_load=True).status_code == 409
    finally:
        info.operation = None


# ---------------------------------------------------------------------------
# effective values: the per-model switch, and the kind scope of the default
# ---------------------------------------------------------------------------
def test_a_chat_model_ignores_the_global_default(client):
    """Unchanged behaviour: the global switches only ever covered AUX_KINDS."""
    load(client, "chat-model")
    m = model_of(client, "chat-model")
    assert m["effective"] == {"idle_unload_min": 0, "auto_load": False,
                              "mem_limit_bytes": m["mem_limit_default_bytes"]}
    assert m["idle_unload_at"] is None


def test_a_chat_model_can_be_put_under_idle_unload_individually(client, app):
    """The design's first fixed decision: any kind, chat included."""
    r = put_settings(client, "chat-model", idle_unload_min=1, auto_load=False)
    assert r.status_code == 200, r.text
    load(client, "chat-model")
    m = model_of(client, "chat-model")
    assert m["effective"]["idle_unload_min"] == 1
    assert m["idle_unload_at"] is not None

    backdate(app, "chat-model", 61)
    assert sweep(app) == ["chat-model"]
    assert model_of(client, "chat-model")["unloaded_reason"] == "idle"


def test_an_auxiliary_model_can_opt_out_of_the_global_default(client, app):
    """0 is a value, not "unset": it exempts this model while others stay on."""
    put_settings(client, "embed-a", idle_unload_min=0)
    load(client, "embed-a", "embed-b")
    backdate(app, "embed-a", 60 * 60)
    backdate(app, "embed-b", 60 * 60)
    assert sweep(app) == ["embed-b"], "only the one still on the default goes"
    assert model_of(client, "embed-a")["loaded"] is True


def test_only_the_configured_model_is_unloaded(client, app):
    """The card's promise: Embedding on 1 minute, Reranker off, one goes."""
    put_settings(client, "embed-a", idle_unload_min=1)
    put_settings(client, "rerank-model", idle_unload_min=0)
    load(client, "embed-a", "rerank-model")
    backdate(app, "embed-a", 61)
    backdate(app, "rerank-model", 61)
    assert sweep(app) == ["embed-a"]
    assert model_of(client, "embed-a")["loaded"] is False
    assert model_of(client, "rerank-model")["loaded"] is True


def test_a_model_without_an_entry_follows_the_global_threshold(client, app):
    load(client, "embed-b")
    backdate(app, "embed-b", 5 * 60)
    assert sweep(app) == []
    backdate(app, "embed-b", 11 * 60)
    assert sweep(app) == ["embed-b"]


# ---------------------------------------------------------------------------
# on-demand loading
# ---------------------------------------------------------------------------
def auth(client) -> dict:
    raw = client.post("/api/keys", json={"name": "pytest"}).json()["key"]
    return {"Authorization": f"Bearer {raw}"}


def test_auto_load_off_for_this_model_refuses_with_a_reason(client):
    put_settings(client, "embed-a", auto_load=False)
    r = client.post("/v1/embeddings", headers=auth(client),
                    json={"model": "embed-a", "input": "盘点"})
    assert r.status_code == 409, r.text
    assert "自动加载已关闭" in r.json()["detail"]


def test_auto_load_on_for_this_model_loads_it(client):
    """The global default is off in this fixture? No -- but the model's own wins."""
    put_settings(client, "embed-b", auto_load=False)
    put_settings(client, "embed-a", auto_load=True)
    r = client.post("/v1/embeddings", headers=auth(client),
                    json={"model": "embed-a", "input": "盘点"})
    assert r.status_code == 200, r.text
    assert model_of(client, "embed-a")["loaded"] is True


def test_a_chat_model_can_be_loaded_on_demand_individually(client):
    """Explicitly opting a chat model in is allowed, and costs a long first call."""
    put_settings(client, "chat-model", auto_load=True)
    r = client.post("/v1/chat/completions", headers=auth(client),
                    json={"model": "chat-model", "messages": [
                        {"role": "user", "content": "hi"}], "max_tokens": 8})
    assert r.status_code == 200, r.text
    assert model_of(client, "chat-model")["loaded"] is True


def test_kb_picks_a_candidate_whose_auto_load_is_on(client, app):
    """The one path that chooses a model itself: skip the ones opted out."""
    put_settings(client, "embed-a", auto_load=False)
    put_settings(client, "embed-b", auto_load=True)
    r = client.post("/api/apps/kb", json={"name": "自动加载选择"})
    assert r.status_code == 200, r.text
    kb = r.json()["kb"]["id"]
    client.post(f"/api/apps/kb/{kb}/docs",
                files={"file": ("a.txt", "盘点由仓管员执行。".encode(), "text/plain")})
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        docs = client.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
        if docs and all(d["status"] not in ("queued", "parsing", "ocr", "embedding")
                        for d in docs):
            break
        time.sleep(0.05)
    assert docs[0]["status"] == "ready", docs
    assert model_of(client, "embed-b")["loaded"] is True
    assert model_of(client, "embed-a")["loaded"] is False


# ---------------------------------------------------------------------------
# the memory ceiling
# ---------------------------------------------------------------------------
def test_a_limit_below_the_static_footprint_refuses_the_load(client, app):
    """A model that cannot hold its own weights has nothing to serve: 409 + both numbers."""
    info = app.state.models.get("embed-a")
    static_mb = app.state.models.static_bytes(info) // 2**20
    assert static_mb > 0

    # Stored directly: the API refuses a limit below the *current* footprint
    # only while loaded, and this model is not loaded yet.
    app.state.store.set_model_settings(
        "embed-a", ModelSettings(mem_limit_mb=MEM_LIMIT_MB_MIN))
    r = client.post("/api/models/embed-a/load")
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "静态占用" in detail and "上限" in detail
    assert model_of(client, "embed-a")["loaded"] is False


def test_a_limit_below_the_current_footprint_is_400_while_loaded(client, app):
    load(client, "embed-a")
    info = app.state.models.get("embed-a")
    used_mb = app.state.models.mem_used_bytes(info) // 2**20
    too_small = max(MEM_LIMIT_MB_MIN, used_mb // 2)
    assert too_small < used_mb

    r = put_settings(client, "embed-a", mem_limit_mb=too_small)
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "当前占用" in detail and "上限" in detail
    # And the stored value is unchanged.
    assert client.get("/api/models/embed-a/settings").json()["settings"][
        "mem_limit_mb"] is None


def test_a_limit_at_the_current_footprint_is_accepted(client, app):
    """The boundary: not smaller than what is held, so it is a legal save."""
    load(client, "embed-a")
    info = app.state.models.get("embed-a")
    used_mb = -(-app.state.models.mem_used_bytes(info) // 2**20)  # ceil
    r = put_settings(client, "embed-a", mem_limit_mb=max(used_mb, MEM_LIMIT_MB_MIN))
    assert r.status_code == 200, r.text


def test_the_default_limit_admits_every_model_that_loads_today(client):
    """The derived default must never be the reason a working load is refused."""
    for m in client.get("/api/models").json()["models"]:
        assert m["mem_static_bytes"] <= m["mem_limit_default_bytes"], (
            f"{m['id']}: static {m['mem_static_bytes']} > default "
            f"{m['mem_limit_default_bytes']} would refuse a load nobody configured")
        # And the runtime half is a positive number, so sessions have room.
        assert (m["mem_limit_default_bytes"] - m["mem_static_bytes"]) > 0


def test_the_effective_limit_reaches_the_worker_which_budgets_against_it(client, app):
    """A running worker's session budget is trimmed to limit - static."""
    load(client, "chat-model")
    info = app.state.models.get("chat-model")
    static = app.state.models.static_bytes(info)
    limit_mb = (static >> 20) + 64
    r = put_settings(client, "chat-model", mem_limit_mb=limit_mb)
    assert r.status_code == 200, r.text
    applied = r.json()["applied"]
    assert applied is not None, "a loaded model is reconfigured, not restarted"
    assert "error" not in applied, applied
    # 64 MiB of room minus the 10%.., so the budget is the limit minus static
    # capped by what the device would have allowed anyway.
    budget = app.state.models.runtime_budget_bytes(info)
    assert budget <= limit_mb * 1024 * 1024 - static + 1


@pytest.mark.parametrize("reset", [False, True])
def test_worker_refusal_does_not_persist_model_limit(client, app, monkeypatch, reset):
    load(client, "chat-model")
    assert put_settings(client, "chat-model", mem_limit_mb=2048).status_code == 200
    worker = app.state.clients["chat-model"]

    async def refuse(**kwargs):
        return {"error": "live requests prevent lowering the memory budget"}

    monkeypatch.setattr(worker, "configure", refuse)
    response = put_settings(client, "chat-model", mem_limit_mb=None if reset else 1024)
    assert response.status_code == 409
    assert app.state.store.get_model_settings("chat-model").mem_limit_mb == 2048
    assert StateStore(app.state.store.path).get_model_settings("chat-model").mem_limit_mb == 2048


def test_a_lower_limit_queues_requests_instead_of_over_admitting(client, app):
    """Run time: the scheduler's budget is the ceiling, and the head of the queue waits.

    Driven through ``ModelManager.runtime_budget_bytes`` -- the number the
    worker is started (and reconfigured) with -- rather than through a real
    session, because what the scheduler does with that number is
    ``test_memory_admission.py``'s subject and already pinned there. What this
    card adds is that the number itself follows the limit.
    """
    load(client, "chat-model")
    info = app.state.models.get("chat-model")
    static = app.state.models.static_bytes(info)

    # A limit with 64 MiB of room above the weights leaves exactly that much for
    # sessions and cache -- not the device's several gigabytes.
    put_settings(client, "chat-model", mem_limit_mb=(static >> 20) + 64)
    budget = app.state.models.runtime_budget_bytes(info)
    assert budget <= 64 * 1024 * 1024

    # One full-context session needs far more than that, so it is exactly the
    # request ``_fits`` holds at the head of the queue.
    per_tok, linear = mem_limit._FALLBACK_SESSION["chat"]
    one_session = linear + per_tok * info.context_length
    assert one_session > budget, (
        f"a full-context session ({one_session} B) must not fit a {budget} B budget")

    # Raising the limit gives the room back, without a reload.
    put_settings(client, "chat-model", mem_limit_mb=None)
    assert app.state.models.runtime_budget_bytes(info) > budget


# ---------------------------------------------------------------------------
# deleting a model
# ---------------------------------------------------------------------------
def test_deleting_a_model_forgets_its_settings(client, app, models_dir):
    put_settings(client, "embed-a", idle_unload_min=2, mem_limit_mb=2048)
    r = client.delete("/api/models/embed-a")
    assert r.status_code == 200, r.text
    assert app.state.store.get_model_settings("embed-a").is_default()
    assert "embed-a" not in json.loads(
        (Path(app.state.store.path)).read_text())["model_settings"]


def test_a_recreated_model_starts_from_the_defaults(client, app, models_dir):
    put_settings(client, "embed-a", idle_unload_min=2, mem_limit_mb=2048)
    assert client.delete("/api/models/embed-a").status_code == 200
    make_model(models_dir, "embed-a", EMBED_BMODEL)
    client.get("/api/models")
    body = client.get("/api/models/embed-a/settings").json()
    assert body["settings"] == {"idle_unload_min": None, "auto_load": None,
                                "mem_limit_mb": None}


# ---------------------------------------------------------------------------
# upgrading from an older state file
# ---------------------------------------------------------------------------
def test_an_old_state_file_upgrades_to_unchanged_behaviour(tmp_path, models_dir):
    """No `model_settings` at all -- every model follows the defaults, as before."""
    data = tmp_path / "old" / "state"
    data.mkdir(parents=True)
    (data / "state.json").write_text(json.dumps({
        "keys": [],
        "settings": {"aux_idle_unload_min": 0, "aux_auto_load": False,
                     "aux_defaults_rev": 1},
        "usage": {},
    }))
    app = create_app(data_dir=data, models_dir=models_dir, backend_kind="mock",
                     web_dir=tmp_path / "web", context_length_override=4096)
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        for m in c.get("/api/models").json()["models"]:
            assert m["settings"] == {"idle_unload_min": None, "auto_load": None,
                                     "mem_limit_mb": None}
            if m["kind"] == "chat":
                assert m["effective"]["idle_unload_min"] == 0
                assert m["effective"]["auto_load"] is False


def test_a_v0627_global_on_state_file_still_migrates(tmp_path, models_dir):
    """The v0.6.27 migration is untouched by this card."""
    data = tmp_path / "old27" / "state"
    data.mkdir(parents=True)
    (data / "state.json").write_text(json.dumps({
        "keys": [],
        "settings": {"aux_idle_unload_min": 10, "aux_auto_load": True},
        "usage": {},
    }))
    app = create_app(data_dir=data, models_dir=models_dir, backend_kind="mock",
                     web_dir=tmp_path / "web", context_length_override=4096)
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        embed = [m for m in c.get("/api/models").json()["models"]
                 if m["kind"] == "embedding"][0]
        assert embed["effective"]["idle_unload_min"] == 0
        assert embed["effective"]["auto_load"] is False


@pytest.mark.parametrize("raw", [
    {"idle_unload_min": "soon", "auto_load": "yes", "mem_limit_mb": -5},
    {"idle_unload_min": 99999, "mem_limit_mb": 1},
    [],
    "nonsense",
])
def test_a_hand_edited_entry_degrades_to_the_defaults(tmp_path, raw):
    """A bad field must not brick the boot: it falls back to null."""
    parsed = ModelSettings.from_json(raw)
    assert parsed is None or parsed.is_default() or (
        0 <= (parsed.idle_unload_min or 0) <= 1440)


def test_a_partly_bad_entry_keeps_the_good_fields():
    parsed = ModelSettings.from_json(
        {"idle_unload_min": "soon", "auto_load": True, "mem_limit_mb": 512})
    assert parsed is not None
    assert parsed.idle_unload_min is None, "the bad field fell back to the default"
    assert parsed.auto_load is True
    assert parsed.mem_limit_mb == 512


# ---------------------------------------------------------------------------
# static footprint: the larger of measured and declared
# ---------------------------------------------------------------------------
def test_the_static_figure_is_the_larger_of_measured_and_declared(app):
    """A lazily-loaded model must not be measured by what its first load maps.

    PP-OCRv6's worker maps the detector at startup and each recogniser tier on
    the first request of that width. A load-time delta of 154 MiB therefore
    describes "detector + layout", while a page of narrow text also needs a
    recogniser -- so the declared footprint (all five files) has to win.
    """
    info = app.state.models.get("embed-a")
    declared = app.state.models.static_bytes(info)
    assert declared > 0

    # A measurement *smaller* than the declared footprint must not lower it.
    info.measured_static_bytes = declared // 2
    app.state.models.forget_static_bytes("embed-a")
    info.measured_static_bytes = declared // 2
    assert app.state.models.static_bytes(info) == declared

    # A measurement larger than it (the 35B case) replaces it.
    app.state.models.forget_static_bytes("embed-a")
    info.measured_static_bytes = declared * 2
    assert app.state.models.static_bytes(info) == declared * 2


def test_a_load_records_its_device_delta(app):
    """The delta is stored, and is what the default is then derived from."""
    info = app.state.models.get("embed-a")
    declared = app.state.models.static_bytes(info)
    huge = declared * 3
    app.state.models._record_static_measurement(info, 1000, 1000 + huge)
    assert info.measured_static_bytes == huge
    assert app.state.models.static_bytes(info) == huge


def test_an_implausible_delta_is_discarded(app):
    """Another worker's allocation landing in the window must not be attributed."""
    info = app.state.models.get("embed-a")
    declared = app.state.models.static_bytes(info)
    # 100x the file size is another process's memory, not this model's.
    app.state.models._record_static_measurement(info, 0, declared * 100)
    assert info.measured_static_bytes is None


def test_a_small_128k_models_resident_kv_is_not_mistaken_for_noise(app):
    """Qwen3.5-4B w4 on .157: a 3833 MiB file that holds 8651 MiB once loaded.

    The 128k history KV is allocated at load and is the same order as the
    weights. The old 2x + 512 MiB plausibility bound discarded the measurement,
    so the NPU reserve counted the model at its file-size estimate -- half its
    real footprint, the unsafe direction for D7.
    """
    info = app.state.models.get("embed-a")
    info.size_bytes = 4019560448
    app.state.models.forget_static_bytes("embed-a")
    delta = 8651 << 20
    assert app.state.models._record_static_measurement(info, 0, delta) == delta
    assert app.state.models.static_bytes(info) >= delta


def test_a_negative_delta_is_discarded(app):
    info = app.state.models.get("embed-a")
    app.state.models._record_static_measurement(info, 5000, 1000)
    assert info.measured_static_bytes is None


def test_no_device_reading_means_no_measurement(app):
    """A host or the mock backend: the estimate stands, nothing is invented."""
    info = app.state.models.get("embed-a")
    app.state.models._record_static_measurement(info, None, 1234)
    assert info.measured_static_bytes is None


def test_the_default_follows_the_static_figure_so_it_can_never_refuse_a_load(app):
    """The property the whole scheme rests on.

    The default is derived from the same static figure the load-time check
    compares against, so there is no model for which "the default refuses the
    load" is possible -- whatever the static figure turns out to be.
    """
    for info in app.state.models.list():
        static = app.state.models.static_bytes(info)
        assert app.state.models.mem_limit_default_bytes(info) >= static
        info.measured_static_bytes = static * 2
        app.state.models.forget_static_bytes(info.model_id)
        info.measured_static_bytes = static * 2
        grown = app.state.models.static_bytes(info)
        assert app.state.models.mem_limit_default_bytes(info) >= grown


# ---------------------------------------------------------------------------
# a running worker's stats feed mem_used_bytes
# ---------------------------------------------------------------------------
def test_the_worker_runtime_reading_reaches_mem_used_bytes(client, app):
    """``mem_used_bytes`` = static + whatever the worker last reported.

    The worker owns the sessions and the cache, so the management plane cannot
    compute this itself; it records what ``stats`` said and reports the sum.
    """
    load(client, "embed-a")
    info = app.state.models.get("embed-a")
    static = app.state.models.static_bytes(info)
    client.get("/api/models")  # one poll, so the runtime figure is recorded
    before = model_of(client, "embed-a")["mem_used_bytes"]
    assert before is not None and before >= static

    # Pretend the worker reported a session; the next poll must add it.
    app.state.models.note_runtime_bytes("embed-a", 32 * 1024 * 1024)
    info = app.state.models.get("embed-a")
    assert app.state.models.mem_used_bytes(info) >= static + 32 * 1024 * 1024


# ---------------------------------------------------------------------------
# on-demand loading vs the three states that must keep their own refusal
# ---------------------------------------------------------------------------
def test_a_load_the_operator_started_is_not_joined_by_a_request(client, app):
    """A model with auto_load off reports "loading", it does not wait on a load.

    The distinction is what makes ``auto_load`` mean anything: joining an
    in-flight load is for a load the caller would have triggered itself (the
    three-requests / one-worker case). A load the operator clicked is not, and a
    request that arrives during it must keep answering "加载中" -- the answer
    every inference route gave before this feature existed
    (``test_model_readiness.py`` pins it).
    """
    from app.core import models as models_mod

    info = app.state.models.get("chat-model")
    info.operation = models_mod.LOADING
    try:
        r = client.post("/v1/chat/completions", headers=auth(client),
                        json={"model": "chat-model", "max_tokens": 4,
                              "messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 409, r.text
        assert "加载中" in r.json()["detail"]
    finally:
        info.operation = None


def test_a_failed_load_is_reported_not_retried(client, app):
    """A retry would repeat a 60 s failure; the recorded reason is the answer."""
    info = app.state.models.get("embed-a")
    info.load_error = "设备内存不足，加载失败"
    try:
        r = client.post("/v1/embeddings", headers=auth(client),
                        json={"model": "embed-a", "input": "hi"})
        assert r.status_code == 409, r.text
        assert "last load failed" in r.json()["detail"]
        assert "设备内存不足" in r.json()["detail"]
    finally:
        info.load_error = None


def test_an_unload_in_flight_is_not_joined(client, app):
    from app.core import models as models_mod

    info = app.state.models.get("embed-a")
    info.operation = models_mod.UNLOADING
    try:
        r = client.post("/v1/embeddings", headers=auth(client),
                        json={"model": "embed-a", "input": "hi"})
        assert r.status_code == 409, r.text
        assert "卸载中" in r.json()["detail"]
    finally:
        info.operation = None


def test_three_requests_joining_one_on_demand_load_all_succeed(client, app):
    """The dedup the design asks for, on a model whose auto_load is on."""
    import asyncio
    import threading

    put_settings(client, "embed-a", auto_load=True)
    app.state.models.aux_auto_load = False  # so only the per-model value is on
    put_settings(client, "embed-b", auto_load=False)

    codes: list[int] = []
    lock = threading.Lock()

    def one():
        r = client.post("/v1/embeddings", headers=auth(client),
                        json={"model": "embed-a", "input": "盘点"})
        with lock:
            codes.append(r.status_code)

    threads = [threading.Thread(target=one) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codes == [200, 200, 200], codes
    assert app.state.models.get("embed-a").loaded is True
