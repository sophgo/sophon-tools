import asyncio
import sys
from pathlib import Path

import pytest

from app.core.downloader import DownloadManager, _safe_name, orphan_free_space


def test_safe_name_blocks_traversal():
    for bad in ("../etc", "..", "/abs/path", "a/../../b", ""):
        with pytest.raises(ValueError):
            _safe_name(bad)


def test_safe_name_keeps_reasonable_names():
    assert _safe_name("qwen3.5-35b-a3b") == "qwen3.5-35b-a3b"
    assert _safe_name("my model!") == "my-model"


def test_orphan_detection(tmp_path):
    (tmp_path / "a.part").write_bytes(b"x" * 100)
    d = tmp_path / "m"
    d.mkdir()
    (d / "b.part").write_bytes(b"y" * 50)
    r = orphan_free_space(tmp_path)
    assert r["bytes"] == 150
    assert len(r["files"]) == 2


@pytest.mark.asyncio
async def test_cancel_marks_job(tmp_path):
    mgr = DownloadManager(tmp_path, tmp_path / "staging")

    async def slow(job):
        job.state = "running"
        await asyncio.sleep(30)

    job = mgr.start_url("http://example.invalid/x.bmodel", "m")
    mgr._tasks[job.id] = asyncio.create_task(slow(job))
    await asyncio.sleep(0.05)
    assert mgr.cancel(job.id) is True
    assert job.state == "cancelled"
    await asyncio.sleep(0.05)


def test_disk_space_check_rejects_when_too_big(tmp_path):
    from app.core.downloader import check_space
    ok, why = check_space(tmp_path, 10 ** 18)
    assert ok is False
    assert "空间不足" in why


def test_disk_space_check_accepts_small(tmp_path):
    from app.core.downloader import check_space
    ok, _ = check_space(tmp_path, 1024)
    assert ok is True


async def test_dfss_refuses_when_the_catalog_size_does_not_fit(tmp_path):
    import pytest

    from app.core.downloader import DownloadManager

    dm = DownloadManager(tmp_path, tmp_path / "staging")
    with pytest.raises(ValueError):
        dm.start_dfss("open@sophgo.com:/x.bmodel", "big", expected_bytes=1 << 60)
    assert dm.list() == []


# -- the dfss runner -------------------------------------------------------
async def test_dfss_output_is_split_on_carriage_returns(tmp_path):
    """dfss redraws its progress bar with \\r; one huge "line" must not crash it.

    Found on the board (MYS-2373): the 78 MB opencode download failed with
    "Separator is not found, and chunk exceed the limit", because asyncio's
    readline() gives up after 64 KiB with no newline -- and dfss never emits one
    until the transfer is over.
    """
    from app.core import downloader as dl

    script = tmp_path / "fake_dfss.py"
    script.write_text(
        "import sys\n"
        "for i in range(0, 101):\n"
        "    sys.stdout.write(f'[1.{i} MiB] {i}% [====] 3 MiB/s')\n"
        "    sys.stdout.write('\\r')\n"
        "sys.stdout.write('INFO Download completed.\\n')\n"
    )
    lines: list[str] = []
    rc, tail = await dl._run_dfss_process(
        [sys.executable, str(script)], tmp_path, lines.append,
    )
    assert rc == 0
    assert any("100%" in line for line in lines)
    assert tail[-1].endswith("Download completed.")


def test_dfss_progress_reads_the_bar():
    from app.core.downloader import dfss_progress

    # 74.9 MiB at 45% of a 78 526 339-byte file: the percentage is the reliable
    # part, the byte count is what it has moved so far.
    done, pct = dfss_progress("[74.9 MiB]  45% [====] 12.30 MiB/s, ETA: 4s", 78526339)
    assert pct == 45.0
    assert done >= 78526339 * 0.45
    assert dfss_progress("18:55:57 INFO Download completed.", 1000) is None


async def test_dfss_file_lands_at_dest_and_scratch_is_removed(tmp_path, monkeypatch):
    from app.core import downloader as dl

    payload = b"x" * 4096

    async def fake_run(target, dest_dir, on_line=None):
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        (Path(dest_dir) / "pkg.tar.gz").write_bytes(payload)
        return 0, ["Download completed."]

    monkeypatch.setattr(dl, "run_dfss", fake_run)
    dest = tmp_path / "downloads" / "pkg.tar.gz"
    dest.parent.mkdir()
    await dl.download_dfss_file("open@sophgo.com:/a/pkg.tar.gz", dest)
    assert dest.read_bytes() == payload
    assert not (dest.parent / ".dfss-pkg.tar.gz").exists()


async def test_dfss_file_raises_with_the_failure_reason(tmp_path, monkeypatch):
    from app.core import downloader as dl

    async def fake_run(target, dest_dir, on_line=None):
        return 1, ["ERROR Cannot download /a/pkg.tar.gz from open@sophgo.com"]

    monkeypatch.setattr(dl, "run_dfss", fake_run)
    with pytest.raises(RuntimeError, match="dfss 退出码 1"):
        await dl.download_dfss_file(
            "open@sophgo.com:/a/pkg.tar.gz", tmp_path / "pkg.tar.gz",
        )


def test_dfss_reason_picks_the_error_not_the_banner():
    """Found on the board: the tail was the wrapper's banner, hiding the reason."""
    from app.core.downloader import dfss_reason

    tail = [
        "19:00:50 INFO  main.cpp:1380: Download attempt 2",
        "19:00:50 ERROR main.cpp:1383: Cannot download /tools/x/app.tar.gz from open@sophgo.com",
        "dfss python tool, version: v1.10.8",
        "Find architecture: linux-arm64",
        "Binary for architecture linux-arm64 ret: 65280",
    ]
    reason = dfss_reason(tail)
    assert "Cannot download" in reason
    assert "Binary for architecture" not in reason
    # Nothing that looks like an error: fall back to the tail rather than "".
    assert dfss_reason(["a", "b"]) == "a | b"
    assert dfss_reason([]) == "（无输出）"


async def test_dfss_job_reports_bytes_and_active_name(tmp_path, monkeypatch):
    """The job shows dfss' byte count, and its directory is "active" until done.

    Seen on the board: the bar read "25% · 0 B / 19.2 GiB" while dfss itself
    printed 4.92 GiB, because only the percentage was parsed.
    """
    from app.core import downloader as dl

    seen_active: list[set[str]] = []
    release = asyncio.Event()

    async def fake_ensure(on_line=None):
        return None

    async def fake_run(target, dest_dir, on_line, bootstrap=True):
        on_line("[4.92 GiB] 25% [=====>    ] 37.89 MiB/s, ETA: 6m 26s")
        await release.wait()
        (Path(dest_dir) / "x.bmodel").write_bytes(b"\0")
        return 0, ["INFO Download completed."]

    monkeypatch.setattr(dl, "ensure_dfss", fake_ensure)
    monkeypatch.setattr(dl, "run_dfss", fake_run)
    dm = DownloadManager(tmp_path, tmp_path / "staging")
    job = dm.start_dfss("open@sophgo.com:/x.bmodel", "m", expected_bytes=19 << 30)
    for _ in range(100):
        await asyncio.sleep(0.01)
        if job.percent_hint is not None:
            break
    seen_active.append(dm.active_names())
    assert job.percent == 25.0
    assert job.done_bytes == int(4.92 * (1 << 30))
    release.set()
    await dm._tasks[job.id]
    assert job.state == "done"
    assert seen_active == [{"m"}]
    assert dm.active_names() == set()


async def test_cancelling_dfss_stops_the_tool_it_spawned(tmp_path):
    """dfss runs its native downloader through ``sh -c``; a cancel must stop it.

    Seen on .151 with v0.6.17: cancel killed only the Python wrapper, the native
    downloader was reparented to init and kept writing the .bmodel.
    """
    import os

    from app.core import downloader as dl

    pidfile = tmp_path / "child.pid"
    script = tmp_path / "fake_dfss.py"
    # The wrapper starts a grandchild the way dfss does, then waits on it.
    script.write_text(
        "import subprocess, sys\n"
        f"p = subprocess.Popen(['sh', '-c', 'echo $$ > {pidfile}; exec sleep 60'])\n"
        "print('[1.0 MiB] 1% [>] 1 MiB/s', flush=True)\n"
        "p.wait()\n"
    )
    task = asyncio.create_task(dl._run_dfss_process([sys.executable, str(script)], tmp_path))
    for _ in range(200):
        await asyncio.sleep(0.02)
        if pidfile.exists() and pidfile.read_text().strip():
            break
    child = int(pidfile.read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(100):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.02)
    else:
        os.kill(child, 9)
        pytest.fail("the grandchild outlived the cancel")


async def test_cancel_and_wait_keeps_the_model_locked_until_the_task_stopped(tmp_path, monkeypatch):
    from app.core import downloader as dl

    stopped = asyncio.Event()
    seen: list[set[str]] = []

    async def fake_ensure(on_line=None):
        return None

    async def fake_run(target, dest_dir, on_line, bootstrap=True):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            seen.append(dm.active_names())  # still locked while the tool is stopped
            await asyncio.sleep(0.05)
            stopped.set()
            raise

    monkeypatch.setattr(dl, "ensure_dfss", fake_ensure)
    monkeypatch.setattr(dl, "run_dfss", fake_run)
    dm = DownloadManager(tmp_path, tmp_path / "staging")
    job = dm.start_dfss("open@sophgo.com:/x.bmodel", "m")
    await asyncio.sleep(0.05)
    assert await dm.cancel_and_wait(job.id) is True
    assert stopped.is_set()
    assert seen == [{"m"}]
    assert job.state == "cancelled" and dm.active_names() == set()
    assert await dm.cancel_and_wait(job.id) is False



# -- staging: a model appears in models/ only once its file is complete -------
def _fake_dfss(monkeypatch, behaviour):
    """Replace the dfss runner with ``behaviour(dest_dir)``, which returns rc."""
    from app.core import downloader as dl

    async def fake_ensure(on_line=None):
        return None

    async def fake_run(target, dest_dir, on_line, bootstrap=True):
        return await behaviour(Path(dest_dir)), ["tail"]

    monkeypatch.setattr(dl, "ensure_dfss", fake_ensure)
    monkeypatch.setattr(dl, "run_dfss", fake_run)


DFSS_URL = "open@sophgo.com:/tools/cv84x6_llm_server/model_seq32768.bmodel"


async def test_dfss_writes_into_staging_and_installs_only_on_success(tmp_path, monkeypatch):
    models, staging = tmp_path / "models", tmp_path / "downloads" / "models"
    models.mkdir()
    halfway = asyncio.Event()
    release = asyncio.Event()

    async def behaviour(dest_dir):
        (dest_dir / "model_seq32768.bmodel").write_bytes(b"half")
        (dest_dir / "dfss.log").write_text("noise")  # not part of the model
        halfway.set()
        await release.wait()
        (dest_dir / "model_seq32768.bmodel").write_bytes(b"whole")
        return 0

    _fake_dfss(monkeypatch, behaviour)
    dm = DownloadManager(models, staging)
    job = dm.start_dfss(DFSS_URL, "m")
    await asyncio.wait_for(halfway.wait(), 5)
    # Mid-download: nothing under models/, the bytes are in the job's staging.
    assert not (models / "m").exists()
    assert (staging / job.id / "model_seq32768.bmodel").read_bytes() == b"half"
    release.set()
    await dm._tasks[job.id]
    assert job.state == "done", job.message
    assert sorted(p.name for p in (models / "m").iterdir()) == ["model_seq32768.bmodel"]
    assert (models / "m" / "model_seq32768.bmodel").read_bytes() == b"whole"
    assert not (staging / job.id).exists()


@pytest.mark.parametrize("outcome", ["error", "missing", "cancelled"])
async def test_a_failed_or_cancelled_dfss_pull_leaves_nothing_loadable(tmp_path, monkeypatch, outcome):
    models, staging = tmp_path / "models", tmp_path / "downloads" / "models"
    models.mkdir()
    started = asyncio.Event()

    async def behaviour(dest_dir):
        if outcome != "missing":
            (dest_dir / "model_seq32768.bmodel").write_bytes(b"half")
        started.set()
        if outcome == "cancelled":
            await asyncio.sleep(60)
        return 1 if outcome == "error" else 0

    _fake_dfss(monkeypatch, behaviour)
    dm = DownloadManager(models, staging)
    job = dm.start_dfss(DFSS_URL, "m")
    await asyncio.wait_for(started.wait(), 5)
    if outcome == "cancelled":
        assert await dm.cancel_and_wait(job.id) is True
    else:
        await dm._tasks[job.id]
    assert job.state == ("cancelled" if outcome == "cancelled" else "error")
    if outcome == "missing":
        assert "未产出" in job.message
    assert not (models / "m").exists()
    assert not (staging / job.id).exists()


async def test_url_download_stages_then_installs(tmp_path, monkeypatch):
    import httpx

    models, staging = tmp_path / "models", tmp_path / "downloads" / "models"
    models.mkdir()
    payload = b"0" * 300_000
    seen_mid: list[bool] = []

    async def body():
        for i in range(0, len(payload), 100_000):
            seen_mid.append((models / "demo").exists())
            yield payload[i:i + 100_000]
            await asyncio.sleep(0)

    transport = httpx.MockTransport(lambda req: httpx.Response(
        200, headers={"content-length": str(len(payload))}, content=body()))
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))
    dm = DownloadManager(models, staging)
    job = dm.start_url("http://example.invalid/model_seq2048.bmodel", "demo")
    await dm._tasks[job.id]
    assert job.state == "done", job.message
    assert seen_mid and not any(seen_mid), "models/demo existed before the file was complete"
    assert (models / "demo" / "model_seq2048.bmodel").read_bytes() == payload
    assert not (staging / job.id).exists()
    assert list(models.glob("*.part")) == []


def test_stale_staging_from_an_earlier_run_is_removed(tmp_path):
    staging = tmp_path / "downloads" / "models"
    (staging / "deadjob").mkdir(parents=True)
    (staging / "deadjob" / "x.bmodel").write_bytes(b"half")
    (tmp_path / "models").mkdir()
    DownloadManager(tmp_path / "models", staging)
    assert list(staging.iterdir()) == []


def test_install_across_filesystems_never_exposes_a_partial_name(tmp_path, monkeypatch):
    """EXDEV fallback: copy under a .part name (ignored by the scanner), then rename."""
    import errno
    import os

    from app.core import downloader as dl
    from app.core.downloader import DownloadJob

    models, staging = tmp_path / "models", tmp_path / "downloads" / "models"
    models.mkdir()
    dm = DownloadManager(models, staging)
    job = DownloadJob(id="j", kind="url", target="http://x/m.bmodel", name="m")
    produced = dm.staging_dir(job) / "m.bmodel"
    produced.parent.mkdir(parents=True)
    produced.write_bytes(b"whole")
    real_replace = os.replace
    renames: list[str] = []

    def replace(src, dst):
        if Path(src) == produced:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        renames.append(Path(src).name)
        return real_replace(src, dst)

    monkeypatch.setattr(dl.os, "replace", replace)
    dest = dm._install(job, produced)
    assert dest == models / "m" / "m.bmodel" and dest.read_bytes() == b"whole"
    assert renames == ["m.bmodel.part"]
    assert not produced.exists()


# -- multi-file entries (a model made of several bmodels) ------------------
#: OCR's real shape: a detector plus three recogniser widths. The sizes are the
#: catalogue's, so the progress arithmetic is exercised with the numbers the
#: console will show rather than round test values.
OCR_FILES = [
    {"dfss": "open@sophgo.com:/tools/cv84x6_llm_server/ppocrv6-medium-det_f16_736_static.bmodel",
     "md5": "eb8e897f3ef318f9e829007f7287ea20", "size_bytes": 74915840},
    {"dfss": "open@sophgo.com:/tools/cv84x6_llm_server/ppocrv6-medium-rec_f16_48x320_static.bmodel",
     "md5": "2fb497f3d76ea80f0b1148a677895173", "size_bytes": 50884608},
]


def _fake_dfss_set(monkeypatch, payloads: dict, *, fail_on: str | None = None,
               md5_override: dict | None = None):
    """Make ``run_dfss`` write the named payloads into its working directory."""
    from app.core import downloader as dl
    import hashlib

    async def fake_ensure(on_line=None):
        return None

    async def fake_run(target, dest_dir, on_line=None, bootstrap=True):
        name = target.rstrip("/").rsplit("/", 1)[-1]
        if name == fail_on:
            return 1, [f"ERROR Cannot download {name} from open@sophgo.com"]
        body = payloads[name]
        if md5_override and name in md5_override:
            body = md5_override[name]
        Path(dest_dir, name).write_bytes(body)
        return 0, ["INFO Download completed."]

    monkeypatch.setattr(dl, "ensure_dfss", fake_ensure)
    monkeypatch.setattr(dl, "run_dfss", fake_run)
    return dl


async def test_a_multi_file_entry_installs_every_file(tmp_path, monkeypatch):
    """Two files in, two files in models/<id>/ -- and nothing left in staging."""
    payloads = {f["dfss"].rsplit("/", 1)[-1]: b"x" * 128 for f in OCR_FILES}
    # Give each payload the digest the catalogue declares, so the verification
    # step is exercised on its happy path rather than skipped.
    import hashlib
    for entry in OCR_FILES:
        name = entry["dfss"].rsplit("/", 1)[-1]
        entry_md5 = hashlib.md5(payloads[name]).hexdigest()
        entry["md5"] = entry_md5
    dl = _fake_dfss_set(monkeypatch, payloads)
    dm = DownloadManager(tmp_path, tmp_path / "staging")
    job = dm.start_dfss(OCR_FILES[0]["dfss"], "ppocrv6-medium", files=OCR_FILES)
    await dm._tasks[job.id]

    assert job.state == "done", job.message
    dest = tmp_path / "ppocrv6-medium"
    assert sorted(p.name for p in dest.iterdir()) == sorted(payloads)
    # The staging directory is gone: a failed or finished set leaves nothing
    # that could later look like a model.
    assert not (tmp_path / "staging" / job.id).exists()
    # And the job reports the count of files, which is what the console shows
    # instead of a bar that looks stuck for twenty minutes per file.
    assert job.public()["file_count"] == 2
    assert job.public()["files_done"] == 2


async def test_a_partial_failure_installs_nothing(tmp_path, monkeypatch):
    """The whole point of the set: no model directory until all of it is here.

    A directory holding the detector and two of three recognisers looks
    loadable to the scanner and is refused at load, which reads as a broken
    download rather than as one that never finished.
    """
    names = [f["dfss"].rsplit("/", 1)[-1] for f in OCR_FILES]
    payloads = {names[0]: b"a" * 64, names[1]: b"b" * 64}
    # Fix the digests so the first file verifies and only the second fails.
    import hashlib
    for entry in OCR_FILES:
        name = entry["dfss"].rsplit("/", 1)[-1]
        entry["md5"] = hashlib.md5(payloads[name]).hexdigest()
    dl = _fake_dfss_set(monkeypatch, payloads, fail_on=names[1])
    dm = DownloadManager(tmp_path, tmp_path / "staging")
    job = dm.start_dfss(OCR_FILES[0]["dfss"], "ppocrv6-medium", files=OCR_FILES)
    await dm._tasks[job.id]

    assert job.state == "error"
    assert "dfss 退出码 1" in job.message
    assert not (tmp_path / "ppocrv6-medium").exists(), (
        "a partial set must not create the model directory")
    assert not (tmp_path / "staging" / job.id).exists()
    assert dm.active_names() == set()


async def test_a_digest_mismatch_is_refused_and_nothing_is_installed(tmp_path, monkeypatch):
    """A truncated transfer is the failure the digest exists for.

    dfss reports success on a short read often enough that without this the
    symptom is `bmrt_load_bmodel failed (wrong chip or corrupt file?)` at load
    time -- which sends an operator to the board instead of to the download.
    """
    names = [f["dfss"].rsplit("/", 1)[-1] for f in OCR_FILES]
    payloads = {name: b"z" * 64 for name in names}
    # Declare a digest the payload will not have.
    import hashlib
    for entry in OCR_FILES:
        entry["md5"] = hashlib.md5(b"something else").hexdigest()
    dl = _fake_dfss_set(monkeypatch, payloads)
    dm = DownloadManager(tmp_path, tmp_path / "staging")
    job = dm.start_dfss(OCR_FILES[0]["dfss"], "ppocrv6-medium", files=OCR_FILES)
    await dm._tasks[job.id]

    assert job.state == "error"
    assert "md5 不匹配" in job.message
    assert names[0] in job.message, "the message names the file that failed"
    assert not (tmp_path / "ppocrv6-medium").exists()
    assert not (tmp_path / "staging" / job.id).exists()


async def test_a_single_file_job_still_works(tmp_path, monkeypatch):
    """The one-file path is the same code with a one-element list."""
    payloads = {"x.bmodel": b"\0" * 32}
    dl = _fake_dfss_set(monkeypatch, payloads)
    dm = DownloadManager(tmp_path, tmp_path / "staging")
    job = dm.start_dfss("open@sophgo.com:/x.bmodel", "m")
    await dm._tasks[job.id]
    assert job.state == "done"
    assert (tmp_path / "m" / "x.bmodel").read_bytes() == b"\0" * 32
    assert job.public()["file_count"] == 1


async def test_the_disk_check_uses_the_whole_set(tmp_path, monkeypatch):
    """The space check must see the sum, not the first file.

    Admitting four bmodels on the detector's 75 MB would start a transfer that
    fills the disk part-way through the third file -- the most expensive failure
    mode this module exists to prevent.
    """
    files = [
        {"dfss": "open@sophgo.com:/a.bmodel", "size_bytes": 1 << 40},
        {"dfss": "open@sophgo.com:/b.bmodel", "size_bytes": 1 << 40},
    ]
    dm = DownloadManager(tmp_path, tmp_path / "staging")
    with pytest.raises(ValueError) as exc:
        dm.start_dfss(files[0]["dfss"], "big", files=files)
    assert "空间不足" in str(exc.value)
    assert dm.list() == []


async def test_a_multi_file_job_reports_which_file_is_running(tmp_path, monkeypatch):
    """The message names the file and its place in the set: "1/3", not a spinner."""
    from app.core import downloader as dl
    from pathlib import Path

    seen: list[str] = []

    async def fake_ensure(on_line=None):
        return None

    async def fake_run(target, dest_dir, on_line=None, bootstrap=True):
        name = target.rsplit("/", 1)[-1]
        seen.append(name)
        Path(dest_dir, name).write_bytes(b"\0")
        return 0, ["INFO Download completed."]

    monkeypatch.setattr(dl, "ensure_dfss", fake_ensure)
    monkeypatch.setattr(dl, "run_dfss", fake_run)
    files = [{"dfss": f"open@sophgo.com:/f{i}.bmodel", "size_bytes": 1}
             for i in range(3)]
    dm = DownloadManager(tmp_path, tmp_path / "staging")
    messages: list[str] = []
    job = dm.start_dfss(files[0]["dfss"], "m", files=files)
    original = job.public
    monkeypatch.setattr(job, "public", lambda: (messages.append(job.message),
                                                original())[1])
    await dm._tasks[job.id]
    assert seen == ["f0.bmodel", "f1.bmodel", "f2.bmodel"]
    assert job.state == "done"
    assert job.public()["files_done"] == 3


# -- the console's one-click path posts only url+name ----------------------
def test_a_catalogue_id_and_url_expand_to_the_whole_set():
    """The console has no field for a file set, so the API reconstructs one.

    A card click posts ``{url: entry["dfss"], name: entry["id"]}``. If that
    downloaded only the detector, the model directory would hold one of four
    bmodels and every load would fail with three missing names -- a one-click
    install that cannot work. The expansion is what makes the existing console
    correct without touching ``web/``.
    """
    from app.core.downloader import catalog_entry, catalog_files

    entry = catalog_entry("ppocrv6-medium")
    assert entry and entry.get("files")
    files = catalog_files("ppocrv6-medium", entry["dfss"])
    assert files is not None
    assert [f["dfss"] for f in files] == [f["dfss"] for f in entry["files"]]
    # And each carries its digest, so the download verifies every file.
    assert all(f["md5"] for f in files)


def test_the_manual_url_box_is_not_expanded():
    """Pasting a dfss URL must download exactly what was pasted.

    The operator chose a name and a URL; silently replacing one URL with four
    would be answering a different request.
    """
    from app.core.downloader import catalog_entry, catalog_files

    entry = catalog_entry("ppocrv6-medium")
    # Right name, wrong URL: an operator downloading one recogniser by hand.
    assert catalog_files(
        "ppocrv6-medium",
        "open@sophgo.com:/tools/cv84x6_llm_server/ppocrv6-medium-rec_f16_48x320_x.bmodel",
    ) is None
    # Right URL, different name: a copy under another id is a different model.
    assert catalog_files("my-ocr-copy", entry["dfss"]) is None
    # Not a catalogue id at all.
    assert catalog_files("whatever", entry["dfss"]) is None


def test_a_single_file_entry_is_expanded_so_its_tag_reaches_the_download():
    """The entry-level ``dflag`` only travels if the card click is expanded.

    Without this, a one-click download of a single-file model would send just
    ``{url, name}``, arrive with no ``dflag``, and quietly use the fixed URL --
    losing the whole upgrade mechanism for every model but OCR.
    """
    from app.core.downloader import catalog_entry, catalog_files

    entry = catalog_entry("qwen3-asr-0.6b")
    files = catalog_files("qwen3-asr-0.6b", entry["dfss"])
    assert files is not None and len(files) == 1
    assert files[0]["dflag"] == entry["dflag"]
    assert files[0]["dfss"] == entry["dfss"]
    assert files[0]["md5"] == entry["md5"]


def test_a_catalogue_card_click_downloads_every_file(tmp_path, monkeypatch):
    """End to end through the route, as the console drives it."""
    import hashlib

    from fastapi.testclient import TestClient

    from app.core import downloader as dl
    from app.main import create_app

    entry = dl.catalog_entry("ppocrv6-medium")
    names = [f["dfss"].rsplit("/", 1)[-1] for f in entry["files"]]
    # The digests are the real catalogue ones; make the payloads match them so
    # the verification passes. (Real bmodels are hundreds of MB; the digest is
    # over whatever bytes arrived.)
    payloads = {name: f"body-{i}".encode() for i, name in enumerate(names)}
    fixed = []
    for f, name in zip(entry["files"], names):
        fixed.append({**f, "md5": hashlib.md5(payloads[name]).hexdigest()})
    # CATALOG is a list of dicts, so the entry is replaced by index; the
    # try/finally restores it whatever the test does.
    index = dl.CATALOG.index(entry)
    original = dl.CATALOG[index]
    dl.CATALOG[index] = {**entry, "files": fixed}

    async def fake_ensure(on_line=None, **_kw):
        return None

    async def fake_run(target, dest_dir, on_line=None, bootstrap=True):
        from pathlib import Path

        name = target.rsplit("/", 1)[-1]
        Path(dest_dir, name).write_bytes(payloads[name])
        return 0, ["INFO Download completed."]

    monkeypatch.setattr(dl, "ensure_dfss", fake_ensure)
    monkeypatch.setattr(dl, "run_dfss", fake_run)

    app = create_app(data_dir=tmp_path / "data", models_dir=tmp_path / "models",
                     backend_kind="mock", web_dir=tmp_path / "web")
    try:
        _run_card_click(app, tmp_path, entry, names)
    finally:
        dl.CATALOG[index] = original


def _run_card_click(app, tmp_path, entry, names) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        assert client.post("/api/login", json={"password": "admin"}).status_code == 200
        r = client.post("/api/downloads", json={
            "url": entry["dfss"], "name": "ppocrv6-medium", "kind": "dfss",
            "expected_bytes": entry["size_bytes"]})
        assert r.status_code == 200, r.text
        job_id = r.json()["job"]["id"]
        jobs = {}
        for _ in range(500):
            jobs = {j["id"]: j for j in client.get("/api/downloads").json()["jobs"]}
            if jobs[job_id]["state"] in ("done", "error", "cancelled"):
                break
            import time as _time
            _time.sleep(0.02)
        assert jobs[job_id]["state"] == "done", jobs[job_id]["message"]
        assert jobs[job_id]["file_count"] == len(names)
        assert sorted(p.name for p in (tmp_path / "models" / "ppocrv6-medium").iterdir()) \
            == sorted(names)


async def test_a_url_set_downloads_and_installs_together(tmp_path, monkeypatch):
    """The http path carries a file set too, for sites with no dfss route.

    Without it an OCR model fetched by URL arrives as its detector alone -- a
    directory that scans as a model and is refused at load with three missing
    names. That is the case the URL transport exists for (an artifact server on
    the customer's own network), so the set has to work here as well.
    """
    import hashlib

    from app.core import downloader as dl

    names = ["a-det.bmodel", "a-rec320.bmodel"]
    payloads = {names[0]: b"det" * 100, names[1]: b"rec" * 100}
    files = [{"url": f"http://example.invalid/{name}", "size_bytes": len(payloads[name]),
              "md5": hashlib.md5(payloads[name]).hexdigest()} for name in names]

    class _Chunks:
        def __init__(self, body):
            self._body = body
            self.headers = {"content-length": str(len(body))}

        def raise_for_status(self):
            return None

        async def aiter_bytes(self, size):
            for i in range(0, len(self._body), size):
                yield self._body[i:i + size]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url):
            assert method == "GET"
            return _Chunks(payloads[url.rsplit("/", 1)[-1]])

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    dm = DownloadManager(tmp_path, tmp_path / "staging")
    job = dm.start_url(files[0]["url"], "a", files=files)
    await dm._tasks[job.id]
    assert job.state == "done", job.message
    dest = tmp_path / "a"
    assert sorted(p.name for p in dest.iterdir()) == sorted(names)
    for name in names:
        assert (dest / name).read_bytes() == payloads[name]
    assert job.public()["file_count"] == 2 and job.public()["files_done"] == 2
    assert not (tmp_path / "staging" / job.id).exists()


async def test_a_url_set_with_a_bad_digest_installs_nothing(tmp_path, monkeypatch):
    """Same rule as the dfss path: the model appears only when all of it is here."""
    from app.core import downloader as dl

    names = ["b-det.bmodel", "b-rec320.bmodel"]
    files = [{"url": f"http://example.invalid/{name}", "size_bytes": 4,
              "md5": "0" * 32} for name in names]

    class _Chunks:
        headers = {"content-length": "4"}

        def raise_for_status(self):
            return None

        async def aiter_bytes(self, size):
            yield b"data"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url):
            return _Chunks()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    dm = DownloadManager(tmp_path, tmp_path / "staging")
    job = dm.start_url(files[0]["url"], "b", files=files)
    await dm._tasks[job.id]
    assert job.state == "error"
    assert "md5 不匹配" in job.message
    assert not (tmp_path / "b").exists()


# -- URL downloads share the upgrade rules (K3) -----------------------------
class _StaticChunks:
    def __init__(self, body: bytes):
        self._body = body
        self.headers = {"content-length": str(len(body))}

    def raise_for_status(self):
        return None

    async def aiter_bytes(self, size):
        yield self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _StaticClient:
    payloads: dict = {}

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url):
        return _StaticChunks(self.payloads[url.rsplit("/", 1)[-1]])


async def test_a_url_download_onto_an_installed_model_replaces_the_old_build(
        tmp_path, monkeypatch):
    """The URL path used to install beside the old file, leaving two builds.

    ``discover_models`` picks a bmodel by name, so the loader kept taking the
    older one, while the job reported the download as done. The dfss and update
    paths already went through ``_install_set``; this is the same operation and
    must behave the same way.
    """
    import hashlib

    import httpx

    models, staging = tmp_path / "models", tmp_path / "downloads" / "models"
    (models / "demo").mkdir(parents=True)
    (models / "demo" / "demo-old_seq2048.bmodel").write_bytes(b"old build")

    payload = b"new build"
    _StaticClient.payloads = {"demo-new_seq2048.bmodel": payload}
    monkeypatch.setattr(httpx, "AsyncClient", _StaticClient)

    dm = DownloadManager(models, staging)
    job = dm.start_url(
        "http://example.invalid/demo-new_seq2048.bmodel", "demo",
        files=[{"url": "http://example.invalid/demo-new_seq2048.bmodel",
                "size_bytes": len(payload),
                "md5": hashlib.md5(payload).hexdigest()}])
    await dm._tasks[job.id]

    assert job.state == "done", job.message
    assert "已替换旧文件" in job.message
    assert sorted(p.name for p in (models / "demo").iterdir()) == [
        "demo-new_seq2048.bmodel"]
    assert (models / "demo" / "demo-new_seq2048.bmodel").read_bytes() == payload


async def test_a_failed_install_rolls_back_the_files_already_replaced(
        tmp_path, monkeypatch):
    """A multi-file install that dies half way must leave the directory as it was.

    Before, each file was renamed into place as it was moved, so a set that
    failed on its third file left the directory holding a mix of the new build
    and the old one -- which scans as a model and is refused at load for the
    file that never landed, with the previous build already gone.
    """
    import errno
    import os

    from app.core import downloader as dl
    from app.core.downloader import DownloadJob

    models, staging = tmp_path / "models", tmp_path / "downloads" / "models"
    dest = models / "ocr"
    dest.mkdir(parents=True)
    (dest / "a-det.bmodel").write_bytes(b"old det")
    (dest / "a-rec.bmodel").write_bytes(b"old rec")

    dm = DownloadManager(models, staging)
    job = DownloadJob(id="j", kind="url", target="http://x", name="ocr")
    fetched = []
    for name, body in (("a-det.bmodel", b"new det"), ("a-rec.bmodel", b"new rec")):
        path = dm.staging_dir(job) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        fetched.append(path)

    real_replace = os.replace

    def replace(src, dst):
        # Die on the *second* file's swap into place, i.e. after the first new
        # file has already replaced its old build.
        if str(src).endswith("a-rec.bmodel.part"):
            raise OSError(errno.EIO, "Input/output error")
        return real_replace(src, dst)

    monkeypatch.setattr(dl.os, "replace", replace)
    with pytest.raises(OSError):
        dm._install_set(job, fetched)
    monkeypatch.setattr(dl.os, "replace", real_replace)

    assert (dest / "a-det.bmodel").read_bytes() == b"old det", \
        "the first new file was not rolled back"
    assert (dest / "a-rec.bmodel").read_bytes() == b"old rec"
    assert sorted(p.name for p in dest.iterdir()) == ["a-det.bmodel", "a-rec.bmodel"], \
        [p.name for p in dest.iterdir()]


async def test_install_leaves_no_part_or_bak_files_behind(tmp_path):
    """Neither a successful nor a rolled-back install may litter models/<id>/."""
    from app.core.downloader import DownloadJob

    models, staging = tmp_path / "models", tmp_path / "downloads" / "models"
    dest = models / "m"
    dest.mkdir(parents=True)
    (dest / "x-det.bmodel").write_bytes(b"old")

    dm = DownloadManager(models, staging)
    job = DownloadJob(id="j", kind="url", target="http://x", name="m")
    fetched = []
    for name, body in (("x-det.bmodel", b"new det"), ("x-rec.bmodel", b"new rec")):
        path = dm.staging_dir(job) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        fetched.append(path)

    dm._install_set(job, fetched)
    assert sorted(p.name for p in dest.iterdir()) == [
        "x-det.bmodel", "x-rec.bmodel"]
    assert (dest / "x-det.bmodel").read_bytes() == b"new det"


# -- K3 round two: an install must be a rename, and must not stop the world ----
async def test_a_same_filesystem_install_renames_instead_of_copying(
        tmp_path, monkeypatch):
    """Copying the staged file doubles the peak footprint of every install.

    Staging lives under the data root, i.e. the same filesystem as ``models/``,
    so a rename puts the file in place with no second copy. The copy also ran
    inline on the event loop: on a 20 GB bmodel that was minutes during which
    ``/healthz`` and every inference stream were frozen -- and ``check_space``
    had only reserved one copy, so a legitimate upgrade failed on a disk that
    had room for it.
    """
    from app.core import downloader as dl
    from app.core.downloader import DownloadJob

    models, staging = tmp_path / "models", tmp_path / "downloads" / "models"
    dm = DownloadManager(models, staging)
    job = DownloadJob(id="j", kind="url", target="http://x", name="ocr")
    fetched = []
    for name, body in (("a-det.bmodel", b"new det"), ("a-rec.bmodel", b"new rec")):
        path = dm.staging_dir(job) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        fetched.append(path)

    copies: list[tuple[str, str]] = []
    real_copy = dl.shutil.copyfile

    def counting_copy(src, dst, **kw):
        copies.append((str(src), str(dst)))
        return real_copy(src, dst, **kw)

    monkeypatch.setattr(dl.shutil, "copyfile", counting_copy)
    dm._install_set(job, fetched)
    assert copies == [], f"the install copied instead of renaming: {copies}"
    assert sorted(p.name for p in (models / "ocr").iterdir()) == [
        "a-det.bmodel", "a-rec.bmodel"]


async def test_an_install_that_must_copy_uses_exdev_only_and_still_lands(
        tmp_path, monkeypatch):
    """A staging tree on another mount is the one case that may copy."""
    import errno
    import os

    from app.core import downloader as dl
    from app.core.downloader import DownloadJob

    models, staging = tmp_path / "models", tmp_path / "downloads" / "models"
    dm = DownloadManager(models, staging)
    job = DownloadJob(id="j", kind="url", target="http://x", name="m")
    fetched = []
    for name, body in (("a.bmodel", b"new a"), ("b.bmodel", b"new b")):
        path = dm.staging_dir(job) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        fetched.append(path)

    real_replace = os.replace

    def replace(src, dst):
        if ".part" in str(dst) and str(src).endswith(".bmodel"):
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real_replace(src, dst)

    monkeypatch.setattr(dl.os, "replace", replace)
    dm._install_set(job, fetched)
    monkeypatch.setattr(dl.os, "replace", real_replace)

    assert (models / "m" / "a.bmodel").read_bytes() == b"new a"
    assert (models / "m" / "b.bmodel").read_bytes() == b"new b"


async def test_the_event_loop_stays_responsive_while_a_set_is_installed(
        tmp_path, monkeypatch):
    """``_install_set`` in the async paths must not block the loop.

    An install is filesystem work over gigabytes. Done inline in ``_run_url``,
    ``_run_update`` and ``_run_dfss`` it froze the whole API -- ``/healthz`` and
    running inference streams included -- for the length of the copy. The three
    call sites therefore route it through ``asyncio.to_thread``; this drives the
    URL route and checks the hand-off is made, and that the loop keeps ticking
    while a deliberately slow install runs.
    """
    import asyncio
    import hashlib
    import time

    import httpx

    from app.core import downloader as dl

    models, staging = tmp_path / "models", tmp_path / "downloads" / "models"
    models.mkdir()
    payload = b"new build"
    _StaticClient.payloads = {"demo-new_seq2048.bmodel": payload}
    monkeypatch.setattr(httpx, "AsyncClient", _StaticClient)

    dm = DownloadManager(models, staging)
    ticks: list[int] = []
    handed_off = 0
    real_to_thread = asyncio.to_thread

    def spy(func, *args, **kwargs):
        nonlocal handed_off
        if getattr(func, "__name__", "") == "_install_set":
            handed_off += 1
        return real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(dl.asyncio, "to_thread", spy)

    real_install_all = dm._install_all

    def slow_install(job, fetched):
        # Stands in for the seconds a real set takes to cross the filesystem.
        time.sleep(0.25)
        return real_install_all(job, fetched)

    monkeypatch.setattr(dm, "_install_all", slow_install)

    async def ticker():
        for i in range(40):
            ticks.append(i)
            await asyncio.sleep(0.01)

    watch = asyncio.create_task(ticker())
    job = dm.start_url(
        "http://example.invalid/demo-new_seq2048.bmodel", "demo",
        files=[{"url": "http://example.invalid/demo-new_seq2048.bmodel",
                "size_bytes": len(payload),
                "md5": hashlib.md5(payload).hexdigest()}])
    await dm._tasks[job.id]
    await watch

    assert job.state == "done", job.message
    assert handed_off == 1, \
        "the install ran on the event loop instead of a worker thread"
    assert len(ticks) >= 30, \
        f"the event loop was blocked during the install: {len(ticks)} ticks"


async def test_a_crashed_install_has_its_bak_restored_at_startup(tmp_path):
    """Killed between "move aside" and "rename into place", the model is gone.

    The only copy of the previous build is sitting as ``.bak`` beside a
    destination that does not exist. Nothing loads a ``.bak``, so the model has
    to be put back before the first scan.
    """
    models = tmp_path / "models"
    (models / "ocr").mkdir(parents=True)
    (models / "ocr" / "a-det.bmodel.bak").write_bytes(b"old det")
    (models / "ocr" / "a-rec.bmodel").write_bytes(b"new rec")
    (models / "ocr" / "a-rec.bmodel.bak").write_bytes(b"old rec")

    DownloadManager(models, tmp_path / "downloads" / "models")

    assert (models / "ocr" / "a-det.bmodel").read_bytes() == b"old det"
    assert not (models / "ocr" / "a-det.bmodel.bak").exists()
    # The one whose destination exists is a leftover duplicate, not a rescue.
    assert (models / "ocr" / "a-rec.bmodel").read_bytes() == b"new rec"
    assert (models / "ocr" / "a-rec.bmodel.bak").exists()


def test_orphan_free_space_does_not_offer_to_delete_the_only_copy(tmp_path):
    """A ``.bak`` with no destination is the build; it must not read as waste."""
    models = tmp_path / "models"
    (models / "ocr").mkdir(parents=True)
    (models / "ocr" / "a-det.bmodel.bak").write_bytes(b"only copy")
    (models / "ocr" / "a-rec.bmodel.bak").write_bytes(b"duplicate")
    (models / "ocr" / "a-rec.bmodel").write_bytes(b"installed")
    (models / "ocr" / "x.bmodel.part").write_bytes(b"half")

    report = orphan_free_space(models)
    names = [Path(p).name for p in report["files"]]
    assert sorted(names) == ["a-rec.bmodel.bak", "x.bmodel.part"], names
    assert report["bytes"] == len(b"duplicate") + len(b"half")
    assert [Path(p).name for p in report["recoverable"]] == ["a-det.bmodel.bak"]
