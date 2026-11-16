"""The data directory: its footprint, its validation, and moving it.

The move runs as a background task inside the request loop, so the tests drive
it through the real HTTP surface and then wait for the job to settle -- that is
the only way to catch the ordering bugs (unload before copy, config file before
the in-memory switch) that a direct unit call would paper over.
"""

import asyncio
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import storage as storage_mod
from app.core.storage import (
    ENV_KEY,
    MARKER_NAME,
    PARTS,
    StorageError,
    StorageManager,
    ensure_layout,
    fs_usage,
    has_marker,
    walk_stats,
)
from app.main import create_app

GIB = 1 << 30


def test_every_part_has_a_live_path():
    """``PARTS`` and ``parts()`` must name the same set.

    They were two hand-written lists. Adding ``inbox`` to ``PARTS`` alone made
    the move's copy pass raise ``KeyError: 'inbox'`` on its first iteration, roll
    the whole migration back, and leave the operator with "数据目录迁移失败：
    KeyError: 'inbox'" -- a message that says nothing about what to do. The
    inventory now derives from ``PARTS``; this pins the two together so a future
    part cannot reintroduce the split.
    """
    mgr = StorageManager(Path("/tmp/x"), state_dir=Path("/legacy/state"),
                         models_dir=Path("/legacy/models"))
    assert set(mgr.parts()) == set(PARTS)


# -- fixtures ---------------------------------------------------------------
def make_data_root(root: Path) -> Path:
    """A data root in the layout the installer produces, with content in it."""
    ensure_layout(root)
    (root / "models" / "demo").mkdir(parents=True)
    (root / "models" / "demo" / "demo-seq2048.bmodel").write_bytes(b"\x00" * 4096)
    (root / "models" / "demo" / "config").mkdir()
    (root / "models" / "demo" / "config" / "config.json").write_text("{}")
    (root / "state" / "state.json").write_text('{"keys": []}')
    (root / "state" / "session.key").write_bytes(b"secret")
    (root / "state" / "logs").mkdir()
    (root / "state" / "logs" / "worker-demo.log").write_text("hello\n")
    (root / "agents").mkdir(exist_ok=True)
    (root / "downloads" / "partial.part").write_bytes(b"x" * 128)
    # A knowledge base: the demo app's data has to survive a move like any other
    # part, or a successful migration silently loses the vectors.
    (root / "apps" / "kb" / "abc").mkdir(parents=True)
    (root / "apps" / "kb" / "abc" / "chunks.jsonl").write_bytes(b'{"id": "x:0"}\n')
    return root


def env_file_for(tmp_path: Path, data_root: Path) -> Path:
    etc = tmp_path / "etc"
    etc.mkdir(exist_ok=True)
    path = etc / "server.env"
    path.write_text(
        "# written by scripts/install.sh\n"
        f"{ENV_KEY}={data_root}\n"
        "CV84X6_PORT=8000\n"
        "CV84X6_HOST=0.0.0.0\n"
    )
    return path


@pytest.fixture()
def app(tmp_path):
    root = make_data_root(tmp_path / "data")
    env = env_file_for(tmp_path, root)
    install = tmp_path / "opt" / "sophgo" / "cv84x6_llm_server"
    install.mkdir(parents=True)
    return create_app(
        data_root=root,
        env_file=env,
        install_dir=install,
        backend_kind="mock",
        web_dir=tmp_path / "web",
        context_length_override=4096,
    )


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        c.post("/api/login", json={"password": "admin"})
        yield c


def settle(client, timeout=20.0) -> dict:
    """Poll GET /api/storage/move until the job leaves the running states."""
    import time

    deadline = time.monotonic() + timeout
    seen = []
    while time.monotonic() < deadline:
        job = client.get("/api/storage/move").json()
        seen.append(job["state"])
        if job["state"] in ("done", "failed", "idle"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"move did not finish; states seen: {seen}")


# -- /api/storage -----------------------------------------------------------
def test_storage_requires_login(app):
    with TestClient(app) as c:
        assert c.get("/api/storage").status_code == 401


def test_storage_fields_match_statvfs(client, tmp_path):
    body = client.get("/api/storage").json()
    assert set(body) == {
        "data_dir", "fs_total_bytes", "fs_used_bytes", "fs_free_bytes",
        "dir_bytes", "parts",
    }
    # `apps` is the demo applications' data (knowledge bases and their
    # vectors); a move has to carry it, so it is a part like the others.
    # `inbox` is the MCP tools' drop box (app/mcp/paths.py) -- an operator's
    # parked PDF must survive a migration too.
    assert set(body["parts"]) == {"models", "agents", "state", "downloads", "apps",
                                  "inbox"}
    assert body["data_dir"] == str(tmp_path / "data")

    st = os.statvfs(str(tmp_path / "data"))
    assert body["fs_total_bytes"] == st.f_blocks * st.f_frsize
    assert body["fs_free_bytes"] == st.f_bavail * st.f_frsize
    assert body["fs_used_bytes"] == (st.f_blocks - st.f_bfree) * st.f_frsize
    # The footprint is the sum of the parts, and every part is really measured.
    assert body["dir_bytes"] == sum(body["parts"].values())
    assert body["parts"]["models"] == 4096 + len("{}")
    assert body["parts"]["downloads"] == 128
    assert body["parts"]["state"] > 0


def test_storage_sizes_are_cached(client, tmp_path):
    first = client.get("/api/storage").json()
    (tmp_path / "data" / "downloads" / "another.part").write_bytes(b"y" * 1024)
    cached = client.get("/api/storage").json()
    assert cached["parts"]["downloads"] == first["parts"]["downloads"]
    fresh = client.get("/api/storage?refresh=true").json()
    assert fresh["parts"]["downloads"] == first["parts"]["downloads"] + 1024


def test_walk_stats_does_not_follow_symlinks(tmp_path):
    root = tmp_path / "root"
    (root / "real").mkdir(parents=True)
    (root / "real" / "big.bin").write_bytes(b"\x00" * 5000)
    (root / "link").symlink_to(root / "real", target_is_directory=True)
    files, total = walk_stats(root)
    # real/big.bin plus the symlink itself; the 5000 bytes are counted once.
    assert files == 2
    assert total == 5000 + len(str(root / "real"))


# -- move: the happy path ---------------------------------------------------
def test_move_success(client, app, tmp_path):
    root = tmp_path / "data"
    target = tmp_path / "moved"
    r = client.post("/api/storage/move", json={"path": str(target)})
    assert r.status_code == 202, r.text
    job_id = r.json()["job"]
    assert job_id

    job = settle(client)
    assert job["state"] == "done", job
    assert job["id"] == job_id
    assert job["new"] == str(target)
    assert job["copied_bytes"] > 0
    assert job["total_bytes"] >= job["copied_bytes"] > 0

    # Content survived, and the layout is intact.
    assert (target / "models" / "demo" / "demo-seq2048.bmodel").read_bytes() == b"\x00" * 4096
    assert (target / "state" / "state.json").read_text() == '{"keys": []}'
    assert (target / "state" / "session.key").read_bytes() == b"secret"
    assert (target / "state" / "logs" / "worker-demo.log").read_text() == "hello\n"
    assert (target / "agents").is_dir()
    assert (target / "downloads" / "partial.part").read_bytes() == b"x" * 128
    assert (target / "apps" / "kb" / "abc" / "chunks.jsonl").read_bytes() == b'{"id": "x:0"}\n'
    # And the live app was repointed at the copy, not left on the deleted tree.
    assert app.state.kb_store.root == target / "apps" / "kb"

    # The old tree is gone -- it carried the marker, so it was ours to remove.
    assert not root.exists()

    # server.env now names the new place, and kept its other lines.
    env = (tmp_path / "etc" / "server.env").read_text()
    assert f"{ENV_KEY}={target}" in env
    assert f"{ENV_KEY}={root}\n" not in env
    assert "CV84X6_PORT=8000" in env

    # The running service reports the new root.
    assert client.get("/api/storage?refresh=true").json()["data_dir"] == str(target)
    assert app.state.storage.root == target
    assert app.state.models.models_root == target / "models"


def test_move_keeps_models_visible(client, app, tmp_path):
    assert [m["id"] for m in client.get("/api/models").json()["models"]] == ["demo"]
    assert client.post("/api/storage/move", json={"path": str(tmp_path / "moved")}).status_code == 202
    assert settle(client)["state"] == "done"
    # The manager is pointed at the new tree rather than replaced, so the model
    # list survives the move without a restart.
    assert [m["id"] for m in client.get("/api/models").json()["models"]] == ["demo"]
    assert app.state.models.models_root == tmp_path / "moved" / "models"


def test_move_reports_idle_before_any_job(client):
    body = client.get("/api/storage/move").json()
    assert body["state"] == "idle"
    assert body["old"] == client.get("/api/storage").json()["data_dir"]


def test_move_preserves_symlinks(tmp_path):
    root = make_data_root(tmp_path / "data")
    (root / "models" / "linked").symlink_to(root / "models" / "demo", target_is_directory=True)
    mgr = StorageManager(root, env_file=None, install_dir=None, post_switch=None)
    target = tmp_path / "moved"

    async def go():
        mgr.start_move(str(target))
        await mgr._task

    asyncio.run(go())
    assert mgr.job.state == "done", mgr.job.message
    link = target / "models" / "linked"
    assert link.is_symlink()
    assert os.readlink(link) == str(root / "models" / "demo")


# -- move: validation -------------------------------------------------------
@pytest.mark.parametrize("path,reason", [
    ("relative/path", "必须是绝对路径"),
    ("", "请填写目标路径"),
])
def test_move_rejects_bad_paths(client, path, reason):
    r = client.post("/api/storage/move", json={"path": path})
    assert r.status_code == 400
    assert reason in r.json()["detail"]


def test_move_rejects_the_current_directory(client, tmp_path):
    r = client.post("/api/storage/move", json={"path": str(tmp_path / "data")})
    assert r.status_code == 400
    assert "当前数据目录" in r.json()["detail"]


@pytest.mark.parametrize("relative", ["inner", "a/b/c"])
def test_move_rejects_nested_target(client, tmp_path, relative):
    r = client.post("/api/storage/move", json={"path": str(tmp_path / "data" / relative)})
    assert r.status_code == 400
    assert "里面" in r.json()["detail"]


def test_move_rejects_target_that_contains_the_current_one(client, tmp_path):
    r = client.post("/api/storage/move", json={"path": str(tmp_path)})
    assert r.status_code == 400
    assert "包含" in r.json()["detail"]


def test_move_rejects_non_empty_directory(client, tmp_path):
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "someone-elses-file").write_text("do not touch")
    r = client.post("/api/storage/move", json={"path": str(busy)})
    assert r.status_code == 400
    assert "不是空的" in r.json()["detail"]
    assert (busy / "someone-elses-file").read_text() == "do not touch"


def test_move_rejects_a_file_as_target(client, tmp_path):
    f = tmp_path / "afile"
    f.write_text("x")
    r = client.post("/api/storage/move", json={"path": str(f)})
    assert r.status_code == 400
    assert "不是目录" in r.json()["detail"]


def test_move_rejects_install_dir(client, tmp_path):
    r = client.post("/api/storage/move",
                    json={"path": str(tmp_path / "opt" / "sophgo" / "cv84x6_llm_server" / "data")})
    assert r.status_code == 400
    assert "安装目录" in r.json()["detail"]


def test_move_rejects_insufficient_space(client, app, tmp_path, monkeypatch):
    real = fs_usage

    def small(path):
        got = real(path)
        if str(path).startswith(str(tmp_path / "small")):
            got = dict(got, free=1 * 1024 * 1024)   # 1 MiB: less than 1 GiB margin
        return got

    monkeypatch.setattr(storage_mod, "fs_usage", small)
    target = tmp_path / "small"
    r = client.post("/api/storage/move", json={"path": str(target)})
    assert r.status_code == 400
    assert "空间不足" in r.json()["detail"]
    # A target we created for the check is not left behind.
    assert not target.exists()
    assert client.get("/api/storage/move").json()["state"] == "idle"


def test_move_requires_the_margin_beyond_the_footprint(app, tmp_path, monkeypatch):
    """Exactly the footprint is not enough; the 1 GiB margin is on top."""
    mgr = app.state.storage
    need = mgr.info(refresh=True)["dir_bytes"]
    real = fs_usage
    monkeypatch.setattr(storage_mod, "fs_usage",
                        lambda p: dict(real(p), free=need + storage_mod.SPACE_MARGIN_BYTES - 1))
    with pytest.raises(StorageError, match="空间不足"):
        mgr.check_target(str(tmp_path / "tight"))
    monkeypatch.setattr(storage_mod, "fs_usage",
                        lambda p: dict(real(p), free=need + storage_mod.SPACE_MARGIN_BYTES))
    assert mgr.check_target(str(tmp_path / "tight")) == tmp_path / "tight"


def test_move_rejects_unwritable_target(client, tmp_path, monkeypatch):
    real_write = Path.write_bytes

    def deny(self, data):
        if ".cv84x6-probe-" in self.name:
            raise PermissionError(13, "Permission denied")
        return real_write(self, data)

    monkeypatch.setattr(Path, "write_bytes", deny)
    target = tmp_path / "readonly"
    r = client.post("/api/storage/move", json={"path": str(target)})
    assert r.status_code == 400
    assert "不可写" in r.json()["detail"]
    assert not target.exists()


# -- move: failures roll back ----------------------------------------------
def test_copy_failure_rolls_back(client, app, tmp_path, monkeypatch):
    root = tmp_path / "data"
    before_env = (tmp_path / "etc" / "server.env").read_text()
    real_copy2 = shutil.copy2
    calls = {"n": 0}

    def flaky(src, dst, *a, **kw):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise OSError(28, "No space left on device")
        return real_copy2(src, dst, *a, **kw)

    monkeypatch.setattr(storage_mod.shutil, "copy2", flaky)
    target = tmp_path / "moved"
    assert client.post("/api/storage/move", json={"path": str(target)}).status_code == 202
    job = settle(client)
    assert job["state"] == "failed"
    assert "No space left" in job["message"]

    # Nothing is left half-copied, and the configuration is untouched.
    assert not target.exists()          # we created it, so rollback removes it
    assert (tmp_path / "etc" / "server.env").read_text() == before_env
    # The service still points at the original place, with its data intact.
    assert (root / "models" / "demo" / "demo-seq2048.bmodel").exists()
    assert (root / "state" / "state.json").read_text() == '{"keys": []}'
    assert app.state.storage.root == root
    assert client.get("/api/storage").json()["data_dir"] == str(root)


def test_copy_failure_keeps_a_preexisting_empty_target_directory(client, tmp_path, monkeypatch):
    target = tmp_path / "moved"
    target.mkdir()                       # the operator made it, so it stays empty
    real_copy2 = shutil.copy2

    def flaky(src, dst, *a, **kw):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(storage_mod.shutil, "copy2", flaky)
    client.post("/api/storage/move", json={"path": str(target)})
    assert settle(client)["state"] == "failed"
    assert target.is_dir()
    assert list(target.iterdir()) == []


def test_verify_mismatch_fails_and_rolls_back(client, tmp_path, monkeypatch):
    """A copy that "succeeds" but loses bytes must not be switched to."""
    real_copy2 = shutil.copy2

    def dropping(src, dst, *a, **kw):
        # Copy the metadata but never the content.
        result = real_copy2(src, dst, *a, **kw)
        Path(dst).write_bytes(b"")
        return result

    monkeypatch.setattr(storage_mod.shutil, "copy2", dropping)
    target = tmp_path / "moved"
    client.post("/api/storage/move", json={"path": str(target)})
    job = settle(client)
    assert job["state"] == "failed"
    assert "校验" in job["message"]
    assert not target.exists()


def test_concurrent_move_returns_409(client, tmp_path, monkeypatch):
    gate = {"release": False}
    real_copy2 = shutil.copy2

    def slow(src, dst, *a, **kw):
        while not gate["release"]:
            import time
            time.sleep(0.01)
        return real_copy2(src, dst, *a, **kw)

    monkeypatch.setattr(storage_mod.shutil, "copy2", slow)
    first = client.post("/api/storage/move", json={"path": str(tmp_path / "moved")})
    assert first.status_code == 202

    second = client.post("/api/storage/move", json={"path": str(tmp_path / "moved2")})
    assert second.status_code == 409
    assert "进行" in second.json()["detail"]

    gate["release"] = True
    assert settle(client)["state"] == "done"
    # The second request never created its directory.
    assert not (tmp_path / "moved2").exists()


def test_move_again_after_a_finished_job(client, tmp_path, monkeypatch):
    """A failed job must release the lock, or the operator is stuck."""
    real_copy2 = shutil.copy2
    state = {"fail": True}

    def maybe_fail(src, dst, *a, **kw):
        if state["fail"]:
            raise OSError(5, "boom")
        return real_copy2(src, dst, *a, **kw)

    monkeypatch.setattr(storage_mod.shutil, "copy2", maybe_fail)
    client.post("/api/storage/move", json={"path": str(tmp_path / "first")})
    assert settle(client)["state"] == "failed"
    state["fail"] = False
    assert client.post("/api/storage/move", json={"path": str(tmp_path / "second")}).status_code == 202
    assert settle(client)["state"] == "done"


# -- the state file / env file corner cases --------------------------------
def test_move_without_env_file_switches_in_memory_only(tmp_path):
    root = make_data_root(tmp_path / "data")
    mgr = StorageManager(root, env_file=None)

    async def go():
        mgr.start_move(str(tmp_path / "moved"))
        await mgr._task

    asyncio.run(go())
    assert mgr.job.state == "done"
    assert mgr.root == tmp_path / "moved"
    assert "只切换了运行中的路径" in mgr.job.message


def test_move_with_missing_env_file_switches_in_memory_only(tmp_path):
    root = make_data_root(tmp_path / "data")
    mgr = StorageManager(root, env_file=tmp_path / "etc" / "nope.env")

    async def go():
        mgr.start_move(str(tmp_path / "moved"))
        await mgr._task

    asyncio.run(go())
    assert mgr.job.state == "done"
    assert not (tmp_path / "etc" / "nope.env").exists()


def test_env_file_is_written_atomically(tmp_path, monkeypatch):
    root = make_data_root(tmp_path / "data")
    env = env_file_for(tmp_path, root)
    mgr = StorageManager(root, env_file=env)
    target = tmp_path / "moved"

    seen = {}
    real_replace = os.replace

    def spy(src, dst):
        seen["tmp_existed"] = Path(src).exists()
        seen["src"] = str(src)
        return real_replace(src, dst)

    monkeypatch.setattr(storage_mod.os, "replace", spy)

    async def go():
        mgr.start_move(str(target))
        await mgr._task

    asyncio.run(go())
    assert mgr.job.state == "done", mgr.job.message
    assert seen.get("src", "").endswith(".tmp")
    assert not Path(seen["src"]).exists()          # renamed away, not left behind
    assert f"{ENV_KEY}={target}" in env.read_text()


def test_move_adds_the_key_when_the_env_file_lacks_it(tmp_path):
    root = make_data_root(tmp_path / "data")
    env = tmp_path / "server.env"
    env.write_text("CV84X6_PORT=8000\n")
    mgr = StorageManager(root, env_file=env)
    target = tmp_path / "moved"

    async def go():
        mgr.start_move(str(target))
        await mgr._task

    asyncio.run(go())
    text = env.read_text()
    assert f"{ENV_KEY}={target}" in text
    assert "CV84X6_PORT=8000" in text


# -- the marker -------------------------------------------------------------
def test_old_directory_without_marker_is_kept(tmp_path):
    root = make_data_root(tmp_path / "data")
    (root / MARKER_NAME).unlink()
    mgr = StorageManager(root, env_file=None)

    async def go():
        mgr.start_move(str(tmp_path / "moved"))
        await mgr._task

    asyncio.run(go())
    assert mgr.job.state == "done"
    assert root.is_dir()                 # not ours to delete
    assert (root / "models" / "demo" / "demo-seq2048.bmodel").exists()
    assert (tmp_path / "moved" / "models" / "demo" / "demo-seq2048.bmodel").exists()


def test_legacy_layout_never_deletes_its_root(tmp_path):
    """The pre-split layout's root is the install prefix: code lives in it."""
    prefix = tmp_path / "data" / "cv84x6-llm"
    (prefix / "data").mkdir(parents=True)
    (prefix / "data" / "state.json").write_text("{}")
    (prefix / "data" / "logs").mkdir()
    (prefix / "data" / "logs" / "worker.log").write_text("log\n")
    (prefix / "models").mkdir()
    (prefix / "models" / "demo.bmodel").write_bytes(b"\x00" * 16)
    (prefix / "app").mkdir()
    (prefix / "app" / "main.py").write_text("# program")
    # What create_app builds for a v0.5 install: root is the prefix, the state
    # directory is <prefix>/data, models are <prefix>/models.
    mgr = StorageManager(prefix, state_dir=prefix / "data", models_dir=prefix / "models",
                         env_file=None, allow_delete_old=False)
    target = tmp_path / "moved"

    async def go():
        mgr.start_move(str(target))
        await mgr._task

    asyncio.run(go())
    assert mgr.job.state == "done", mgr.job.message
    # Everything landed at the canonical place under the new root.
    assert (target / "state" / "state.json").read_text() == "{}"
    assert (target / "state" / "logs" / "worker.log").read_text() == "log\n"
    assert (target / "models" / "demo.bmodel").read_bytes() == b"\x00" * 16
    assert (target / "agents").is_dir()
    assert (target / "downloads").is_dir()
    # The program tree survives -- it is not data.
    assert (prefix / "app" / "main.py").exists()
    assert (prefix / "data" / "state.json").exists()


def test_marker_gates_the_layout_marker_content(tmp_path):
    root = tmp_path / "data"
    ensure_layout(root)
    assert has_marker(root)
    assert (root / MARKER_NAME).read_text() == '{"version": 1}'
    # A blank or foreign marker does not authorise a delete.
    (root / MARKER_NAME).write_text("{}")
    assert not has_marker(root)
    (root / MARKER_NAME).write_text("not json")
    assert not has_marker(root)


# -- data root wiring in main.py -------------------------------------------
def test_data_root_creates_the_layout(tmp_path):
    root = tmp_path / "cv84x6_llm_server"
    app = create_app(data_root=root, backend_kind="mock", web_dir=tmp_path / "web")
    assert app.state.storage.root == root
    for name in ("models", "state", "agents", "downloads", "apps", "inbox"):
        assert (root / name).is_dir(), name
    assert has_marker(root)
    assert app.state.store.path == root / "state" / "state.json"


def test_legacy_flags_still_win(tmp_path):
    """A v0.5 systemd unit passes --data-dir/--models-dir and must keep working."""
    app = create_app(data_dir=tmp_path / "legacy" / "data",
                     models_dir=tmp_path / "legacy" / "models",
                     backend_kind="mock", web_dir=tmp_path / "web")
    assert app.state.store.path == tmp_path / "legacy" / "data" / "state.json"
    assert app.state.models.models_root == tmp_path / "legacy" / "models"
    # No data root was invented, so nothing is ever deleted on a move.
    assert app.state.storage.allow_delete_old is False


def test_api_keys_survive_a_move(client, app, tmp_path):
    """The whole point of moving data instead of reinstalling: keys keep working."""
    raw = client.post("/api/keys", json={"name": "before"}).json()["key"]
    assert client.get("/v1/models", headers={"Authorization": f"Bearer {raw}"}).status_code == 200

    client.post("/api/storage/move", json={"path": str(tmp_path / "moved")})
    assert settle(client)["state"] == "done"

    r = client.get("/v1/models", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200, r.text
    # And the store now lives in the new tree.
    assert app.state.store.path == tmp_path / "moved" / "state" / "state.json"
    assert raw not in (tmp_path / "moved" / "state" / "state.json").read_text()


def test_move_stops_downloads_before_copying(client, app, tmp_path, monkeypatch):
    """A download writing into models/ must be cancelled before the copy.

    Otherwise it keeps streaming into a tree that is about to be deleted, and
    the copy measures a moving target.
    """
    order: list[str] = []
    real_copy2 = shutil.copy2

    async def fake_shutdown():
        order.append("downloads-stopped")

    def spy_copy2(src, dst, *a, **kw):
        order.append("copy")
        return real_copy2(src, dst, *a, **kw)

    monkeypatch.setattr(app.state.downloads, "shutdown", fake_shutdown)
    monkeypatch.setattr(storage_mod.shutil, "copy2", spy_copy2)

    client.post("/api/storage/move", json={"path": str(tmp_path / "moved")})
    assert settle(client)["state"] == "done"
    assert order[0] == "downloads-stopped"
    assert "copy" in order


def test_failure_after_the_switch_never_deletes_the_only_copy(tmp_path, monkeypatch):
    """A failure in the final cleanup must not wipe the new tree.

    Past the switch the new directory holds the only complete copy: the old one
    may already be partly deleted. Clearing the target then would destroy the
    data this whole job exists to protect.
    """
    root = make_data_root(tmp_path / "data")
    target = tmp_path / "moved"
    mgr = StorageManager(root, env_file=None)

    real_rmtree = shutil.rmtree

    def failing_rmtree(path, *a, **kw):
        # The old-tree removal is the one that fails; rollback's own use of
        # rmtree must keep working, so fail only on the old root.
        if str(path) == str(root):
            raise OSError(5, "device busy")
        return real_rmtree(path, *a, **kw)

    monkeypatch.setattr(storage_mod.shutil, "rmtree", failing_rmtree)

    async def go():
        mgr.start_move(str(target))
        await mgr._task

    asyncio.run(go())
    assert mgr.job.state == "failed"
    # The copy is intact and usable, and the report says where it is.
    assert (target / "models" / "demo" / "demo-seq2048.bmodel").read_bytes() == b"\x00" * 4096
    assert (target / "state" / "state.json").read_text() == '{"keys": []}'
    assert "未完全删除" in mgr.job.message


# -- the inference record log travels with the data (MYS-2496) -------------
def _serve_and_record(client, prompt: str) -> str:
    """Run one inference and return the record id it produced."""
    if "demo" not in [m["id"] for m in client.get("/api/models").json()["models"]
                      if m["loaded"]]:
        assert client.post("/api/models/demo/load").status_code == 200
    raw = client.post("/api/keys", json={"name": "mover"}).json()["key"]
    r = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {raw}"},
                    json={"model": "demo", "max_tokens": 4,
                          "messages": [{"role": "user", "content": prompt}]})
    assert r.status_code == 200, r.text
    return r.json()["id"].removeprefix("chatcmpl-")


def test_record_log_is_served_from_the_state_dir(client, app, tmp_path):
    rid = _serve_and_record(client, "before the move")
    log_path = tmp_path / "data" / "state" / "inference_records.sqlite3"
    assert log_path.exists()
    assert app.state.inference_log.path == log_path
    assert client.get(f"/api/inference-records/{rid}").status_code == 200


def test_record_log_moves_with_the_data_directory(client, app, tmp_path):
    """The records are evidence on a customer site: a move must not lose them,
    and the next request must land in the new file, not the deleted old one.

    The copy is the StorageManager's ordinary whole-tree copy; what this pins
    down is that the log's connection goes with it -- closed before the copy
    (a live writer would tear the file), reopened on the new path (otherwise the
    service would keep answering from a database that is about to be deleted).
    """
    rid = _serve_and_record(client, "before the move")
    old_path = tmp_path / "data" / "state" / "inference_records.sqlite3"

    assert client.post("/api/storage/move",
                       json={"path": str(tmp_path / "moved")}).status_code == 202
    job = settle(client)
    assert job["state"] == "done", job

    new_path = tmp_path / "moved" / "state" / "inference_records.sqlite3"
    assert new_path.exists(), "the record database did not travel with the data"
    assert not old_path.exists()
    assert app.state.inference_log.path == new_path

    # The old record survived the move and is still readable through the API.
    row = client.get(f"/api/inference-records/{rid}").json()
    assert row["messages"] == [{"role": "user", "content": "before the move"}]

    # And a new inference is written to the new file.
    rid2 = _serve_and_record(client, "after the move")
    assert rid2 != rid
    ids = [r["id"] for r in client.get("/api/inference-records").json()["items"]]
    assert set(ids) == {rid, rid2}


def test_no_record_is_written_into_the_old_tree_during_a_move(client, app, tmp_path):
    """A request that finishes between the stop and the switch must not write.

    The log is closed at the start of the move; re-opening the old path behind
    the move's back would put a record into a tree that is then deleted -- the
    record would be lost and the copy certified as complete while changing.
    """
    rid = _serve_and_record(client, "before the move")
    log = app.state.inference_log
    old_path = tmp_path / "data" / "state" / "inference_records.sqlite3"

    assert client.post("/api/storage/move",
                       json={"path": str(tmp_path / "moved")}).status_code == 202
    job = settle(client)
    assert job["state"] == "done", job

    # The live store followed the data, and its connection is open on the new
    # file -- not merely its `path` attribute.
    assert log.path == tmp_path / "moved" / "state" / "inference_records.sqlite3"
    assert log._conn is not None
    # The old tree is gone, so a record written there would have been lost. The
    # record made before the move is still readable, which is the observable
    # proof that the copy carried a consistent database.
    assert client.get(f"/api/inference-records/{rid}").status_code == 200
    assert not old_path.parent.exists()
