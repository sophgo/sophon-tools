import asyncio

import pytest

from app.core.models import ModelManager, discover_models, read_bmodel_meta
from pathlib import Path


def make_model(root: Path, name: str, bmodel="qwen3.5-8b-int4_w4bf16_seq2048_4core_dynamic.bmodel"):
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / bmodel).write_bytes(b"\x00" * 2048)
    (d / "config" / "config.json").write_text("{}")
    return d


def test_discover_finds_model_dirs_only(tmp_path):
    make_model(tmp_path, "m-a")
    (tmp_path / "not-a-model").mkdir()
    (tmp_path / "not-a-model" / "readme.txt").write_text("x")
    found = discover_models(tmp_path)
    assert [m.model_id for m in found] == ["m-a"]
    assert found[0].has_config is True
    assert found[0].size_bytes > 0


def test_context_length_parsed_from_filename(tmp_path):
    p = tmp_path / "x" / "a_seq8192_2core.bmodel"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"")
    assert read_bmodel_meta(p)["context_length"] == 8192


def test_vision_detected_from_filename(tmp_path):
    p = tmp_path / "x" / "qwen3-vl-8b_seq2048.bmodel"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"")
    assert read_bmodel_meta(p)["supports_vision"] is True


@pytest.mark.asyncio
async def test_load_and_unload_spawns_and_reaps_worker(tmp_path):
    make_model(tmp_path / "models", "m1")
    mgr = ModelManager(tmp_path / "models", max_loaded=2, log_dir=tmp_path / "logs")
    mgr.refresh()
    info = await mgr.load("m1")
    try:
        assert info.loaded is True
        assert info.pid and info.port
        # The worker really answers.
        reader, writer = await asyncio.open_connection("127.0.0.1", info.port)
        writer.write(b'{"op":"health"}\n'); await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=10)
        assert b'"ok": true' in line or b'"ok":true' in line
        writer.close()
    finally:
        info2 = await mgr.unload("m1")
        assert info2.loaded is False
        assert info2.pid is None


@pytest.mark.asyncio
async def test_loaded_limit_is_enforced(tmp_path):
    root = tmp_path / "models"
    make_model(root, "m1")
    make_model(root, "m2")
    mgr = ModelManager(root, max_loaded=1, log_dir=tmp_path / "logs")
    mgr.refresh()
    await mgr.load("m1")
    try:
        with pytest.raises(RuntimeError, match="上限（1 个）"):
            await mgr.load("m2")
    finally:
        await mgr.unload_all()


@pytest.mark.asyncio
async def test_two_models_run_in_parallel(tmp_path):
    root = tmp_path / "models"
    make_model(root, "m1")
    make_model(root, "m2")
    mgr = ModelManager(root, max_loaded=2, log_dir=tmp_path / "logs")
    mgr.refresh()
    try:
        a, b = await asyncio.gather(mgr.load("m1"), mgr.load("m2"))
        assert a.loaded and b.loaded
        assert a.port != b.port
        assert a.pid != b.pid
    finally:
        await mgr.unload_all()


@pytest.mark.asyncio
async def test_unknown_model_raises(tmp_path):
    mgr = ModelManager(tmp_path / "models", log_dir=tmp_path / "logs")
    mgr.refresh()
    with pytest.raises(KeyError):
        await mgr.load("nope")


def test_disk_usage_reports_models_bytes(tmp_path):
    root = tmp_path / "models"
    make_model(root, "m1")
    mgr = ModelManager(root, log_dir=tmp_path / "logs")
    mgr.refresh()
    d = mgr.disk_usage()
    assert d["total_bytes"] > 0
    assert d["models_bytes"] >= 2048


def test_bundled_config_stands_in_for_a_bare_bmodel_dir(tmp_path, monkeypatch):
    from app.core.models import ModelManager

    models = tmp_path / "models"
    (models / "q35").mkdir(parents=True)
    (models / "q35" / "x_seq2048_4core_dynamic.bmodel").write_bytes(b"\0" * 64)
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "tokenizer.json").write_text("{}")
    monkeypatch.setenv("CV84X6_DEFAULT_CONFIG", str(cfg))
    mgr = ModelManager(models, log_dir=tmp_path / "logs")
    (info,) = mgr.refresh()
    assert info.has_config


def test_plain_bmodel_preferred_over_history(tmp_path):
    from app.core.models import discover_models

    d = tmp_path / "q35"
    d.mkdir()
    (d / "a_seq2048_4core_history_dynamic_1.bmodel").write_bytes(b"\0")
    (d / "b_seq2048_4core_dynamic_2.bmodel").write_bytes(b"\0")
    (info,) = discover_models(tmp_path)
    assert info.bmodel_files[0] == "b_seq2048_4core_dynamic_2.bmodel"


def test_refresh_during_load_keeps_the_loading_object(tmp_path):
    """GET /api/models during a load used to swap the ModelInfo under load()."""
    import asyncio

    from app.core.models import ModelManager

    models = tmp_path / "models"
    (models / "m" / "config").mkdir(parents=True)
    (models / "m" / "m-seq2048-4core.bmodel").write_bytes(b"\0" * 64)
    (models / "m" / "config" / "config.json").write_text("{}")

    async def run():
        mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
        mgr.refresh()
        before = mgr.get("m")
        task = asyncio.create_task(mgr.load("m"))
        for _ in range(20):          # refresh repeatedly while the worker starts
            await asyncio.sleep(0.05)
            mgr.refresh()
        info = await task
        try:
            assert info is before is mgr.get("m")
            assert mgr.get("m").loaded and mgr.get("m").port
        finally:
            await mgr.unload("m")

    asyncio.run(run())


def test_native_load_is_refused_when_ram_is_short(tmp_path, monkeypatch):
    """A worker started into an exhausted system invites the OOM killer."""
    import asyncio
    from app.core import models as m

    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "model.bmodel").write_bytes(b"0")
    mgr = m.ModelManager(tmp_path, backend_kind="native")
    mgr.refresh()
    monkeypatch.setattr(m, "mem_available_bytes", lambda: 300 * 1024 * 1024)
    with pytest.raises(RuntimeError, match="可用内存"):
        asyncio.run(mgr.load("x"))


# -- operation state (MYS-2388) --------------------------------------------
# The console must be able to answer "is this model busy?" from the backend
# alone, because a page refresh throws away every piece of client-side state.

def test_idle_model_reports_no_operation(tmp_path):
    make_model(tmp_path / "models", "m")
    mgr = ModelManager(tmp_path / "models", log_dir=tmp_path / "logs")
    (info,) = mgr.refresh()
    pub = info.public()
    assert pub["operation"] is None
    assert pub["operation_since"] is None
    assert pub["loaded"] is False


@pytest.mark.asyncio
async def test_get_models_reports_loading_before_the_worker_is_ready(tmp_path, monkeypatch):
    """A slow load must be visible as `loading` while `loaded` is still false.

    This is the refresh bug: the console's only "busy" was local React state,
    so reloading during the 60+ s a 35B takes showed an idle, loadable model and
    a second click spawned a second worker.
    """
    from app.core import models as m

    root = tmp_path / "models"
    make_model(root, "m")
    mgr = ModelManager(root, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()

    ready = asyncio.Event()

    async def slow_wait(port, timeout, proc):
        await ready.wait()
        return True

    monkeypatch.setattr(mgr, "_wait_ready", slow_wait)

    task = asyncio.create_task(mgr.load("m"))
    # Let load() reach the readiness wait.
    for _ in range(200):
        await asyncio.sleep(0.01)
        if mgr.get("m").operation == "loading":
            break
    else:
        raise AssertionError("load() never published the loading operation")

    mid = mgr.get("m")
    pub = mid.public()
    assert pub["operation"] == "loading", pub
    assert pub["loaded"] is False, "a worker that is not ready must not read as loaded"
    assert pub["pid"], "the process exists even though the model is not usable yet"
    assert pub["operation_since"] is not None
    # A refresh in the middle of the load must not disturb the in-flight load.
    mgr.refresh()
    assert mgr.get("m").operation == "loading"
    assert mgr.get("m") is mid

    ready.set()
    info = await task
    assert info is mid
    assert info.loaded is True
    assert info.operation is None, "the operation must clear once the model is usable"
    assert info.operation_since is None
    await mgr.unload_all()


@pytest.mark.asyncio
async def test_failed_load_clears_the_operation_and_the_process(tmp_path, monkeypatch):
    """A load that fails must not leave the console locked in "loading"."""
    from app.core import models as m

    root = tmp_path / "models"
    make_model(root, "m")
    mgr = ModelManager(root, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()

    async def never_ready(port, timeout, proc):
        return False

    monkeypatch.setattr(mgr, "_wait_ready", never_ready)

    with pytest.raises(RuntimeError):
        await mgr.load("m")

    info = mgr.get("m")
    assert info.loaded is False
    assert info.operation is None, "a failed load must leave the model idle, not loading"
    assert info.pid is None
    assert info.port is None
    assert info.load_error, "the operator needs the worker tail to see why it failed"
    # And the next attempt is allowed -- nothing is stuck.
    monkeypatch.undo()
    info2 = await mgr.load("m")
    try:
        assert info2.loaded is True
    finally:
        await mgr.unload_all()


@pytest.mark.asyncio
async def test_failure_while_spawning_clears_the_operation(tmp_path, monkeypatch):
    """A refused spawn (no interpreter, no permission) must unwind cleanly."""
    root = tmp_path / "models"
    make_model(root, "m")
    mgr = ModelManager(root, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()

    async def boom(*a, **kw):
        raise OSError("cannot execute worker")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    with pytest.raises(OSError):
        await mgr.load("m")
    info = mgr.get("m")
    assert info.operation is None
    assert info.loaded is False and info.pid is None and info.port is None


@pytest.mark.asyncio
async def test_concurrent_loads_spawn_exactly_one_worker(tmp_path, monkeypatch):
    """Two clients clicking "load" must share one load, not start two workers.

    Before this, the second caller waited on the manager-wide lock and then
    spawned its own worker: two processes, two NPU allocations, and the first
    one leaked because only the second pid was remembered.
    """
    root = tmp_path / "models"
    make_model(root, "m")
    mgr = ModelManager(root, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()

    spawned: list[int] = []
    real_spawn = asyncio.create_subprocess_exec

    async def counting_spawn(*a, **kw):
        proc = await real_spawn(*a, **kw)
        spawned.append(proc.pid)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", counting_spawn)

    a, b = await asyncio.gather(mgr.load("m"), mgr.load("m"))
    try:
        assert len(spawned) == 1, f"expected one worker, spawned {spawned}"
        assert a is b is mgr.get("m")
        assert a.loaded is True
    finally:
        await mgr.unload_all()


@pytest.mark.asyncio
async def test_load_of_a_loaded_model_is_idempotent(tmp_path):
    root = tmp_path / "models"
    make_model(root, "m")
    mgr = ModelManager(root, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()
    first = await mgr.load("m")
    try:
        again = await mgr.load("m")
        assert again is first
        assert again.loaded is True
        assert again.operation is None
    finally:
        await mgr.unload_all()


@pytest.mark.asyncio
async def test_unload_is_refused_while_a_load_is_in_flight(tmp_path, monkeypatch):
    """Refused rather than killing a half-loaded worker.

    A worker that is minutes into mapping weights into NPU memory must not be
    torn down: that is how the TPU is left busy for the next load.
    """
    from app.core.models import ModelBusy

    root = tmp_path / "models"
    make_model(root, "m")
    mgr = ModelManager(root, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()

    ready = asyncio.Event()

    async def slow_wait(port, timeout, proc):
        await ready.wait()
        return True

    monkeypatch.setattr(mgr, "_wait_ready", slow_wait)
    task = asyncio.create_task(mgr.load("m"))
    for _ in range(200):
        await asyncio.sleep(0.01)
        if mgr.get("m").operation == "loading":
            break

    with pytest.raises(ModelBusy, match="加载中"):
        await mgr.unload("m")
    # The load is untouched by the refusal.
    ready.set()
    info = await task
    assert info.loaded is True
    await mgr.unload_all()


@pytest.mark.asyncio
async def test_unload_is_idempotent_for_an_idle_model(tmp_path):
    """Polling clients call unload on an already-idle model; that is not an error."""
    root = tmp_path / "models"
    make_model(root, "m")
    mgr = ModelManager(root, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()
    info = await mgr.unload("m")
    assert info.loaded is False and info.operation is None
    with pytest.raises(KeyError):
        await mgr.unload("nope")


@pytest.mark.asyncio
async def test_two_different_models_still_load_in_parallel(tmp_path):
    """Per-model locks: one model's 60 s load must not block the other's."""
    root = tmp_path / "models"
    make_model(root, "m1")
    make_model(root, "m2")
    mgr = ModelManager(root, max_loaded=2, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()
    t0 = asyncio.get_running_loop().time()
    a, b = await asyncio.gather(mgr.load("m1"), mgr.load("m2"))
    elapsed = asyncio.get_running_loop().time() - t0
    try:
        assert a.loaded and b.loaded and a.port != b.port
        assert elapsed < 20, f"the two loads serialised ({elapsed:.1f}s)"
    finally:
        await mgr.unload_all()
