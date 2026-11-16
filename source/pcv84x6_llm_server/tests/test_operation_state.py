"""Operation state as the HTTP surface reports it (MYS-2388).

The console's lock used to be React state, so a page refresh threw it away: a
model mid-load looked idle and the button that killed the browser session was
simply gone. Every test here drives the API the way a second browser (or a
reload) does -- a fresh request, no shared client-side memory.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def make_model(root: Path, name: str, ctx="seq2048"):
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{name}_int4_w4bf16_{ctx}_4core_dynamic.bmodel").write_bytes(b"\x00" * 1024)
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
        c.post("/api/login", json={"password": "admin"})
        yield app, c


def model_of(c, model_id: str = "m") -> dict:
    models = {m["id"]: m for m in c.get("/api/models").json()["models"]}
    return models[model_id]


def hold_load(app, monkeypatch, *, ready_on: threading.Event | None = None):
    """Make the next load wait, and return the flag that releases it.

    The wait is a *polling* sleep rather than a blocking ``Event.wait()``: the
    app under TestClient runs on one event loop, so blocking that thread would
    also block the refresh requests these tests need to serve -- they would see
    a frozen service instead of a loading model.

    A ``threading.Event`` (not ``asyncio.Event``) because the release happens on
    the test's thread, and ``asyncio.Event`` is not thread-safe.
    """
    ready = ready_on or threading.Event()
    mgr = app.state.models

    async def slow_wait(port, timeout, proc):
        for _ in range(1500):  # 30 s ceiling, same as the real readiness wait
            if ready.is_set():
                return True
            await asyncio.sleep(0.02)
        return False

    monkeypatch.setattr(mgr, "_wait_ready", slow_wait)
    return ready


def wait_for_operation(c, op: str, timeout: float = 20.0) -> dict:
    """Poll GET /api/models until the model reports ``op``, as a reload would."""
    deadline = time.monotonic() + timeout
    seen: dict = {}
    while time.monotonic() < deadline:
        seen = model_of(c)
        if seen.get("operation") == op:
            return seen
        time.sleep(0.05)
    raise AssertionError(f"operation never became {op!r}; last seen {seen}")


def test_models_report_no_operation_when_idle(app_and_client):
    _, c = app_and_client
    m = model_of(c)
    assert m["loaded"] is False
    assert m["operation"] is None
    assert m["operation_since"] is None


def test_refresh_during_load_shows_loading_not_idle(app_and_client, monkeypatch):
    """The reported bug: reload the page mid-load and it read as unloaded."""
    app, c = app_and_client
    ready = hold_load(app, monkeypatch)

    result: dict = {}

    def do_load():
        result["r"] = c.post("/api/models/m/load")

    t = threading.Thread(target=do_load)
    t.start()
    try:
        # Poll from a different connection, the way a reloaded page would.
        seen = wait_for_operation(c, "loading")
        # This is the assertion the bug was about: a reloaded page must see a
        # locked, non-loadable model -- not `loaded: false, operation: null`.
        assert seen["loaded"] is False
        assert seen["operation_since"] is not None
        # `loading` is published *before* the spawn, so `pid` may still be null
        # on the very first poll; it must show up as soon as the process exists.
        for _ in range(300):
            if model_of(c)["pid"]:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("the worker pid never appeared during the load")
        still = model_of(c)
        assert still["operation"] == "loading", "the load ended before it settled"
        assert still["pid"], "a spawn-in-progress load must report its pid"
    finally:
        ready.set()
        t.join(timeout=40)

    assert result["r"].status_code == 200, result["r"].text
    done = model_of(c)
    assert done["loaded"] is True
    assert done["operation"] is None, "the lock must clear the moment the model is usable"
    assert done["operation_since"] is None


def test_failed_load_leaves_the_model_loadable_again(app_and_client, monkeypatch):
    """A failure must not leave the console locked in "loading" forever."""
    app, c = app_and_client
    async def never_ready(port, timeout, proc):
        return False

    monkeypatch.setattr(app.state.models, "_wait_ready", never_ready)

    r = c.post("/api/models/m/load")
    assert r.status_code == 409, r.text
    m = model_of(c)
    assert m["loaded"] is False
    assert m["operation"] is None
    assert m["load_error"], "the console shows this text; it must not be empty"
    # And a retry after the cause is fixed succeeds (nothing is stuck).
    monkeypatch.undo()
    assert c.post("/api/models/m/load").status_code == 200
    assert model_of(c)["loaded"] is True


def test_load_registers_the_client_before_the_model_reads_loaded(app_and_client):
    """A request that observes `loaded` must find a client, or /v1 answers 500.

    `/v1/chat/completions` looks the worker client up by model id. Registering
    it only after `load()` returned left a window in which the model read as
    loaded with no client behind it.
    """
    app, c = app_and_client
    original = app.state.models.on_loaded
    assert original is not None, "create_app must install the client-registration hook"

    fired: list[tuple] = []

    def checking_hook(model_id, info):
        # This is the exact instant `loaded` becomes observable to other
        # requests. The hook is what closes the window, so it must run from
        # inside the load and leave a client behind before it returns.
        fired.append((model_id, info.loaded))
        original(model_id, info)
        fired.append(model_id in app.state.clients)

    app.state.models.on_loaded = checking_hook
    assert c.post("/api/models/m/load").status_code == 200
    assert fired == [("m", True), True], fired
    assert "m" in app.state.clients
    # The OpenAI surface really works through that client.
    key = c.post("/api/keys", json={"name": "k"}).json()["key"]
    r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
               json={"model": "m", "messages": [{"role": "user", "content": "hi"}],
                     "max_tokens": 4})
    assert r.status_code == 200, r.text


def test_a_second_load_joins_instead_of_spawning_a_second_worker(app_and_client, monkeypatch):
    """Two browsers on "load" must produce one worker, not two."""
    app, c = app_and_client
    ready = hold_load(app, monkeypatch)
    spawned: list[int] = []
    real_spawn = asyncio.create_subprocess_exec

    async def counting_spawn(*a, **kw):
        proc = await real_spawn(*a, **kw)
        spawned.append(proc.pid)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", counting_spawn)
    results: list = []

    def one():
        results.append(c.post("/api/models/m/load"))

    first = threading.Thread(target=one)
    first.start()
    wait_for_operation(c, "loading")
    second = threading.Thread(target=one)
    second.start()
    time.sleep(0.6)  # give the second request time to reach the manager

    pid = app.state.models.get("m").pid
    ready.set()
    first.join(timeout=40)
    second.join(timeout=40)

    assert [r.status_code for r in results] == [200, 200], [r.text for r in results]
    assert len(spawned) == 1, f"a second click spawned another worker: {spawned}"
    assert app.state.models.get("m").pid == pid, "the second click replaced the worker"
    # One socket per model: the joiner must not have orphaned the first's.
    assert len(app.state.clients) == 1


def test_unload_while_loading_is_a_defined_conflict(app_and_client, monkeypatch):
    """409 with an explanation, and the in-flight load is left alone."""
    app, c = app_and_client
    ready = hold_load(app, monkeypatch)
    results: dict = {}

    def do_load():
        results["load"] = c.post("/api/models/m/load")

    t = threading.Thread(target=do_load)
    t.start()
    wait_for_operation(c, "loading")
    pid = app.state.models.get("m").pid

    r = c.post("/api/models/m/unload")
    assert r.status_code == 409, r.text
    assert "加载" in r.json()["detail"]
    # The refusal must not have touched the worker.
    assert app.state.models.get("m").pid == pid
    assert model_of(c)["operation"] == "loading"

    ready.set()
    t.join(timeout=40)
    assert results["load"].status_code == 200
    assert model_of(c)["loaded"] is True


def test_unload_then_load_is_clean(app_and_client):
    """The full cycle a reloading operator drives: load, unload, load again."""
    _, c = app_and_client
    assert c.post("/api/models/m/load").status_code == 200
    first = model_of(c)
    assert first["loaded"] is True and first["operation"] is None

    assert c.post("/api/models/m/unload").status_code == 200
    idle = model_of(c)
    assert idle["loaded"] is False and idle["operation"] is None
    assert idle["pid"] is None and idle["port"] is None

    assert c.post("/api/models/m/load").status_code == 200
    again = model_of(c)
    assert again["loaded"] is True and again["operation"] is None
    assert again["pid"] != first["pid"]


def test_unload_of_an_idle_model_is_not_an_error(app_and_client):
    """Polling clients repeat the call; a 200 with the idle state is the answer."""
    _, c = app_and_client
    r = c.post("/api/models/m/unload")
    assert r.status_code == 200, r.text
    assert r.json()["model"]["loaded"] is False
    assert r.json()["model"]["operation"] is None


def test_load_of_a_loaded_model_is_idempotent(app_and_client):
    _, c = app_and_client
    assert c.post("/api/models/m/load").status_code == 200
    pid = model_of(c)["pid"]
    r = c.post("/api/models/m/load")
    assert r.status_code == 200, r.text
    assert r.json()["model"]["pid"] == pid, "a second load restarted the worker"


def test_unknown_model_is_still_a_404(app_and_client):
    _, c = app_and_client
    assert c.post("/api/models/nope/load").status_code == 404
    assert c.post("/api/models/nope/unload").status_code == 404


def test_stats_carries_the_operation_so_one_poll_locks_the_console(app_and_client):
    """The overview polled /api/stats only; it must see the same operation."""
    app, c = app_and_client
    assert c.post("/api/models/m/load").status_code == 200
    st = c.get("/api/stats").json()
    (m,) = [x for x in st["models"] if x["id"] == "m"]
    assert m["operation"] is None and m["loaded"] is True


def test_unload_closes_the_worker_socket_before_signalling_it(app_and_client):
    """Unload must not wait for the 120 s grace and then SIGKILL the worker.

    The worker's shutdown waits for its connection handlers to finish, and a
    handler parked on a read from the console's RPC client never does. Closing
    the client first is what makes an unload take ~0.6 s instead of hitting the
    grace timeout -- and that timeout ends in SIGKILL, which the project
    forbids for a live NPU process because it can leave the TPU busy.

    Pinned as a test because the ordering looks arbitrary and is easy to
    "tidy": measured 120 s when the client was closed after the SIGTERM.
    """
    import time as _time

    app, c = app_and_client
    assert c.post("/api/models/m/load").status_code == 200
    assert "m" in app.state.clients

    t0 = _time.monotonic()
    assert c.post("/api/models/m/unload").status_code == 200
    elapsed = _time.monotonic() - t0
    assert elapsed < 10, (
        f"unload took {elapsed:.1f}s -- the worker hit its SIGTERM grace and was killed")
    assert "m" not in app.state.clients
    assert model_of(c)["loaded"] is False


def test_a_refused_unload_leaves_the_worker_and_its_socket_alone(app_and_client, monkeypatch):
    """The 409 path must not have closed the client on its way out."""
    app, c = app_and_client
    ready = hold_load(app, monkeypatch)
    results: dict = {}

    def do_load():
        results["load"] = c.post("/api/models/m/load")

    t = threading.Thread(target=do_load)
    t.start()
    try:
        wait_for_operation(c, "loading")
        assert c.post("/api/models/m/unload").status_code == 409
        # Still usable while it finishes loading.
        assert "m" in app.state.clients or app.state.models.get("m").operation == "loading"
    finally:
        ready.set()
        t.join(timeout=40)
    assert results["load"].status_code == 200
    assert model_of(c)["loaded"] is True
    assert "m" in app.state.clients


def test_delete_is_refused_while_a_model_is_loading(app_and_client, monkeypatch):
    """Deleting the directory mid-load pulls the .bmodel out from under the worker.

    Same class of bug as unloading mid-load: `loaded` is false the whole time,
    so a check on it alone lets the delete through.
    """
    app, c = app_and_client
    ready = hold_load(app, monkeypatch)
    results: dict = {}

    def do_load():
        results["load"] = c.post("/api/models/m/load")

    t = threading.Thread(target=do_load)
    t.start()
    try:
        wait_for_operation(c, "loading")
        r = c.delete("/api/models/m")
        assert r.status_code == 409, r.text
        assert "加载" in r.json()["detail"]
        # The model directory is still there, so the worker can finish.
        assert (Path(app.state.models.models_root) / "m").is_dir()
    finally:
        ready.set()
        t.join(timeout=40)
    assert results["load"].status_code == 200
    assert model_of(c)["loaded"] is True


def test_download_is_refused_for_a_model_in_use(app_and_client):
    """A download unpacks into models/<name>: never over a live worker.

    `name` is the directory name, so downloading "m" while m is loaded would
    write over the .bmodel a live worker is running from.
    """
    _, c = app_and_client
    assert c.post("/api/models/m/load").status_code == 200
    r = c.post("/api/downloads", json={
        "url": "http://127.0.0.1:1/nope.bmodel", "name": "m", "kind": "url"})
    assert r.status_code == 409, r.text
    assert "卸载" in r.json()["detail"]
    # A different name is still accepted (the guard is per model, not global).
    r = c.post("/api/downloads", json={
        "url": "http://127.0.0.1:1/other.bmodel", "name": "other", "kind": "url"})
    assert r.status_code == 200, r.text



def test_download_guard_checks_the_directory_the_job_will_write(app_and_client):
    """The job installs into models/<_safe_name(name)>: "m." and " m" land in
    models/m, so they must be refused while m is loaded, exactly like "m" --
    otherwise the install (which also removes other bmodels of the directory)
    runs under a live worker."""
    _, c = app_and_client
    assert c.post("/api/models/m/load").status_code == 200
    for alias in ("m.", "m-", " m"):
        r = c.post("/api/downloads", json={
            "url": "http://127.0.0.1:1/nope.bmodel", "name": alias, "kind": "url"})
        assert r.status_code == 409, (alias, r.text)
    # A name that cannot be a directory at all is a 400, not a 500.
    r = c.post("/api/downloads", json={
        "url": "http://127.0.0.1:1/nope.bmodel", "name": "../m", "kind": "url"})
    assert r.status_code == 400, r.text

def _fake_download(app, name: str, state: str = "running"):
    """Register a job writing into models/<name> without running a transfer."""
    from app.core.downloader import DownloadJob

    job = DownloadJob(id=f"job-{name}", kind="dfss", target="open@sophgo.com:/x.bmodel",
                      name=name, state=state)
    app.state.downloads.jobs[job.id] = job
    return job


def test_a_model_being_downloaded_cannot_be_loaded_or_deleted(app_and_client):
    """dfss writes the .bmodel into models/<name> in place: the model is on disk
    long before the file is complete, and loading it then maps a truncated file.
    """
    app, c = app_and_client
    job = _fake_download(app, "m")

    m = model_of(c)
    assert m["downloading"] is True
    r = c.post("/api/models/m/load")
    assert r.status_code == 409, r.text
    assert "下载" in r.json()["detail"]
    assert model_of(c)["loaded"] is False
    r = c.delete("/api/models/m")
    assert r.status_code == 409, r.text
    assert "取消下载" in r.json()["detail"]
    assert (app.state.models.models_root / "m").is_dir()
    # A second job into the same directory would interleave two writers.
    r = c.post("/api/downloads", json={
        "url": "http://127.0.0.1:1/m.bmodel", "name": "m", "kind": "url"})
    assert r.status_code == 409, r.text
    assert "已在下载中" in r.json()["detail"]
    # /api/stats carries the same flag (the overview reads models from it).
    dash = {x["id"]: x for x in c.get("/api/stats").json()["models"]}
    assert dash["m"]["downloading"] is True

    # The lock is the job's state, nothing else: once it ends, the model unlocks.
    job.state = "done"
    assert model_of(c)["downloading"] is False
    assert c.post("/api/models/m/load").status_code == 200
    assert model_of(c)["loaded"] is True


@pytest.mark.parametrize("final", ["error", "cancelled"])
def test_a_finished_download_job_no_longer_locks_the_model(app_and_client, final):
    app, c = app_and_client
    _fake_download(app, "m", state=final)
    assert model_of(c)["downloading"] is False
    assert c.post("/api/models/m/load").status_code == 200


def test_catalog_reports_a_downloading_model_as_not_installed(app_and_client, tmp_path):
    from app.core.downloader import CATALOG

    app, c = app_and_client
    cid = CATALOG[0]["id"]
    make_model(app.state.models.models_root, cid, ctx="seq131072")
    _fake_download(app, cid)
    c.get("/api/models")  # rescan, as the console does before reading the catalog
    row = {x["id"]: x for x in c.get("/api/catalog").json()["models"]}[cid]
    assert row["installed"] is False
    assert row["downloading"] is True
    app.state.downloads.jobs[f"job-{cid}"].state = "done"
    row = {x["id"]: x for x in c.get("/api/catalog").json()["models"]}[cid]
    assert row["installed"] is True
    assert row["downloading"] is False
