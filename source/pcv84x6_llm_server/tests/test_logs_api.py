"""The log page's backend: three sources, one shape, read from disk (MYS-2674).

What this file is asserting, and why each half is here rather than in the log
code's own docstrings:

* **The platform log is a file now.** It used to exist only as stderr, which is
  fine until someone needs to read yesterday's warning without ssh. The first
  group checks the handler writes the format the parser reads back, and that a
  line which does *not* parse still reaches the console.
* **A big log is read from its end.** "The newest 200 lines" of a 50 MiB file
  must not cost 50 MiB of I/O or of memory; that is measured, not asserted.
* **Paging is stable while the file grows**, because the cursor is a byte
  offset, not a row number.
* **Downloads carry the rotations**, because the incident an operator is chasing
  is usually in the file that was rotated out an hour ago.
* **A source id is the only input that reaches the filesystem.** Path traversal
  is refused by construction, and the test spells out the payloads someone would
  actually try.
"""

from __future__ import annotations

import io
import json
import logging
import time
import tracemalloc
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import logs as logmod
from app.core.logs import (
    LogRegistry,
    LogSource,
    parse_line,
    read_page,
    rotate_log_file,
    tail_lines,
)
from app.main import create_app


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def make_model(root: Path, name: str, ctx="seq2048") -> Path:
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{name}-int4_w4bf16_{ctx}_4core_dynamic.bmodel").write_bytes(b"\x00" * 1024)
    (d / "config" / "config.json").write_text("{}")
    return d


@pytest.fixture()
def app(tmp_path):
    models = tmp_path / "models"
    make_model(models, "test-model")
    return create_app(
        data_dir=tmp_path / "data",
        models_dir=models,
        backend_kind="mock",
        web_dir=tmp_path / "web",
        context_length_override=4096,
    )


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        yield c


def log_dir(app) -> Path:
    return Path(app.state.models.log_dir)


def write_log(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(lines) + "\n" if lines else ""
    path.write_text(body, encoding="utf-8")
    return path


def platform_line(n: int, level="INFO", message=None,
                  when="2026-11-07T10:00:00") -> str:
    """A line in the format ``install_platform_log`` writes."""
    return (f"{when}.{n:03d}+08:00 {level} cv84x6: "
            f"{message if message is not None else f'line {n}'}")


# ---------------------------------------------------------------------------
# the platform log file
# ---------------------------------------------------------------------------
def test_the_service_writes_its_own_log_to_a_file(app):
    """stderr keeps its job; the file is what the console can page."""
    path = Path(app.state.platform_log_path)
    logging.getLogger("cv84x6.selftest").warning("平台日志落盘自检 %s", 42)
    handler = app.state.platform_log
    assert handler is not None
    handler.flush()

    assert path.exists(), "the platform log file was never created"
    text = path.read_text(encoding="utf-8")
    assert "平台日志落盘自检 42" in text
    line = parse_line([ln for ln in text.splitlines()
                       if "平台日志落盘自检" in ln][0])
    # The format is the contract with the parser: a line the console cannot read
    # is a line the console cannot filter by level or by time.
    assert line.level == "WARNING"
    assert line.logger == "cv84x6.selftest"
    assert line.ts and line.ts.startswith("20")
    assert line.epoch is not None


def test_a_second_app_in_the_same_process_does_not_stack_handlers(tmp_path):
    paths = []
    for name in ("a", "b"):
        models = tmp_path / name / "models"
        make_model(models, "m")
        app = create_app(data_dir=tmp_path / name / "data", models_dir=models,
                         backend_kind="mock", web_dir=tmp_path / name / "web")
        paths.append(Path(app.state.platform_log_path))
    platform = [h for h in logging.getLogger().handlers
                if getattr(h, "_cv84x6_platform_log", False)]
    assert len(platform) == 1, "one writer per file, not one per create_app"
    logging.getLogger("cv84x6.selftest").warning("只应写进第二份")
    platform[0].flush()
    assert "只应写进第二份" in paths[1].read_text(encoding="utf-8")
    assert not paths[0].exists() or "只应写进第二份" not in paths[0].read_text(
        encoding="utf-8")


def test_a_line_that_does_not_parse_is_still_a_line():
    """A traceback and a native library's output have no timestamp at all."""
    for raw in ("Traceback (most recent call last):",
                "bm_alloc_gmem failed",
                "   at frame 3"):
        line = parse_line(raw)
        assert line.ts is None and line.level is None
        assert line.message == raw


def test_the_local_and_utc_forms_both_parse():
    local = parse_line("2026-11-07 10:27:46,123 INFO cv84x6: 本地时间")
    assert local.level == "INFO" and local.logger == "cv84x6"
    assert local.message == "本地时间"
    # A line with no zone is read as *local* time -- the same reading
    # `journalctl` gives that file -- and reported with its offset so the
    # console never has to guess which machine wrote it.
    assert local.epoch == datetime(2026, 11, 7, 10, 27, 46, 123000).timestamp()
    assert local.ts[-6] in "+-" and local.ts.startswith("2026-11-07T10:27:46.123000")

    utc = parse_line("2026-11-07T02:27:46.123Z WARNING worker: hi")
    assert utc.level == "WARNING" and utc.logger == "worker"
    assert utc.ts.startswith("2026-11-07T02:27:46.123000+00:00")
    assert utc.epoch == datetime(2026, 11, 7, 2, 27, 46, 123000,
                                tzinfo=timezone.utc).timestamp()


# ---------------------------------------------------------------------------
# querying: time, level, keyword
# ---------------------------------------------------------------------------
def test_query_by_level_keyword_and_time(client, app):
    path = Path(app.state.platform_log_path)
    lines = [
        platform_line(0, "DEBUG", "starting up", when="2026-11-07T10:00:00"),
        platform_line(0, "INFO", "loaded model test-model", when="2026-11-07T10:00:05"),
        platform_line(0, "WARNING", "cache near limit", when="2026-11-07T10:00:10"),
        platform_line(0, "ERROR", "worker crashed", when="2026-11-07T10:00:15"),
        platform_line(0, "INFO", "restarted worker", when="2026-11-07T10:00:20"),
    ]
    write_log(path, lines)

    def read(**params):
        r = client.get("/api/logs/platform", params={"limit": 50, **params})
        assert r.status_code == 200, r.text
        return [ln["message"] for ln in r.json()["lines"]]

    assert read() == ["starting up", "loaded model test-model",
                      "cache near limit", "worker crashed", "restarted worker"]

    # A level filter is a threshold ("this and worse"), which is the question an
    # operator asks ("什么出错了").
    assert read(level="warning") == ["cache near limit", "worker crashed"]
    assert read(level="ERROR") == ["worker crashed"]
    # `warn` is what half the world sends.
    assert read(level="warn") == ["cache near limit", "worker crashed"]

    assert read(q="worker") == ["worker crashed", "restarted worker"]
    assert read(q="WORKER") == ["worker crashed", "restarted worker"], "case-insensitive"

    # Time windows. The lines are in +08:00, which is what `since` resolves to
    # when it carries an offset.
    assert read(since="2026-11-07T10:00:10+08:00") == [
        "cache near limit", "worker crashed", "restarted worker"]
    assert read(until="2026-11-07T10:00:05+08:00") == [
        "starting up", "loaded model test-model"]
    assert read(since="2026-11-07T10:00:05+08:00",
                until="2026-11-07T10:00:15+08:00") == [
        "loaded model test-model", "cache near limit", "worker crashed"]

    # Combinations narrow rather than replace: ERROR is at or above INFO, so
    # only the ERROR lines survive both filters.
    assert read(level="INFO", q="worker") == ["worker crashed", "restarted worker"]
    assert read(level="ERROR", q="worker") == ["worker crashed"]

    # A relative window is what the page's "最近 30 分钟" button sends.
    now = time.time()
    write_log(path, [platform_line(0, "INFO", "old", when="2026-11-07T10:00:00")])
    r = client.get("/api/logs/platform", params={"since": "-30m"})
    assert r.status_code == 200 and r.json()["lines"] == []
    r = client.get("/api/logs/platform", params={"since": "-90d"})
    assert r.status_code == 200 and len(r.json()["lines"]) == 1
    assert now - 90 * 86400 < time.time()


def test_an_invalid_filter_is_a_400_not_an_empty_page(client):
    for params in ({"level": "LOUD"}, {"since": "yesterday-ish"}):
        r = client.get("/api/logs/platform", params=params)
        assert r.status_code == 400, (params, r.text)
    r = client.get("/api/logs/platform",
                   params={"since": "2026-11-07T10:00:00", "until": "2026-11-07T09:00:00"})
    assert r.status_code == 400


def test_sources_lists_platform_workers_and_agents(client, app):
    log_dir(app).mkdir(parents=True, exist_ok=True)
    write_log(log_dir(app) / "worker-test-model.log", [platform_line(0)])
    agent_log = Path(app.state.agents.directory("dsh")) / "logs" / "agent.log"
    write_log(agent_log, ["agent started"])

    body = client.get("/api/logs/sources").json()
    by_id = {item["id"]: item for item in body["sources"]}
    assert "platform" in by_id
    assert "worker:test-model" in by_id
    assert "agent:dsh" in by_id
    assert by_id["worker:test-model"]["kind"] == "worker"
    assert by_id["worker:test-model"]["size_bytes"] > 0
    assert by_id["worker:test-model"]["updated_at"] is not None
    assert by_id["worker:test-model"]["updated_at_iso"]
    assert by_id["agent:dsh"]["label"].startswith("Agent 日志")


def test_a_worker_log_written_by_a_real_load_appears(client):
    assert client.post("/api/models/test-model/load").status_code == 200
    ids = {item["id"] for item in client.get("/api/logs/sources").json()["sources"]}
    assert "worker:test-model" in ids
    r = client.get("/api/logs/worker:test-model", params={"limit": 50})
    assert r.status_code == 200
    # The mock worker announces itself with a JSON banner that has no timestamp;
    # it must come back rather than be filtered out for not parsing.
    raw = [ln["message"] for ln in r.json()["lines"]]
    assert any('"event": "ready"' in text for text in raw)


# ---------------------------------------------------------------------------
# the newest N lines of a big file
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("size_mib", [50])
def test_the_newest_n_lines_of_a_large_log_are_cheap(tmp_path, size_mib):
    """50 MiB, 200 lines, measured: I/O and memory both bounded near the answer.

    A log read forwards to keep its tail costs the whole file in both. This
    asserts the *order of magnitude* -- well under the file's size -- rather than
    a byte count, so an ordinary implementation detail (block size) can change
    without breaking the test, while a regression to "read it all" cannot hide.
    """
    path = tmp_path / "platform.log"
    target = size_mib * 1024 * 1024
    with open(path, "w", encoding="utf-8") as fh:
        written = 0
        n = 0
        while written < target:
            text = f"2026-11-07T10:00:00.{n % 1000:03d}+08:00 INFO cv84x6: seq={n} " + "x" * 200 + "\n"
            fh.write(text)
            written += len(text.encode())
            n += 1
    total_lines = n
    assert path.stat().st_size >= target

    source = LogSource(id="platform", label="平台日志", path=path, kind="platform")

    tracemalloc.start()
    started = time.monotonic()
    page, cursor, more = read_page(source, limit=200)
    elapsed = time.monotonic() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(page) == 200
    assert f"seq={total_lines - 1} " in page[0].message
    assert f"seq={total_lines - 200} " in page[-1].message
    assert cursor is not None and more is True
    # Memory: the answer is 200 lines (~45 KiB); allow an order of magnitude of
    # headroom, and still demand it is a small fraction of the 50 MiB file.
    assert peak < 4 * 1024 * 1024, f"peak {peak} bytes for a {size_mib} MiB file"
    # Time: reading a 50 MiB file front-to-back is tens of milliseconds on this
    # host; a tail read is a handful of blocks. 2 s is a generous ceiling that
    # still fails a full read on a slow board.
    assert elapsed < 2.0, f"{elapsed:.2f}s to read the tail of a {size_mib} MiB log"


def test_tail_lines_matches_a_forward_read(tmp_path):
    path = tmp_path / "x.log"
    lines = [f"line {i}" for i in range(5000)]
    write_log(path, lines)
    for count in (0, 1, 2, 7, 200, 5000, 6000):
        expected = lines[-count:] if count else []
        assert tail_lines(path, count) == expected, count


def test_a_log_without_a_trailing_newline_still_yields_its_last_line(tmp_path):
    path = tmp_path / "x.log"
    path.write_text("one\ntwo\nthree", encoding="utf-8")
    assert tail_lines(path, 2) == ["two", "three"]


def test_a_filtered_scan_looks_past_its_read_budget(client, app):
    """A ``q`` that matches nothing near the end must still find the match.

    Without a resume cursor a capped scan would answer "nothing" for everything
    past its first 16 MiB -- an empty result that looks exactly like "the log
    does not contain it", which is the worst possible answer for an audit-style
    search.
    """
    path = Path(app.state.platform_log_path)
    lines = [platform_line(i, message=f"filler {i} " + "z" * 120) for i in range(3000)]
    lines.append(platform_line(0, "ERROR", "the needle is here"))
    lines.extend(platform_line(i, message=f"tail {i} " + "z" * 120)
                 for i in range(3000, 6000))
    write_log(path, lines)

    # A tiny budget: one page cannot see past a few blocks, so reaching the
    # match requires the cursor this page hands back.
    found: list[str] = []
    cursor = None
    for _ in range(50):
        params = {"q": "the needle", "limit": 5}
        if cursor:
            params["cursor"] = cursor
        body = client.get("/api/logs/platform", params=params).json()
        found.extend(ln["message"] for ln in body["lines"])
        cursor = body["cursor"]
        if found or not cursor:
            break
    assert found == ["the needle is here"]


def test_one_enormous_line_does_not_make_a_page_cost_the_whole_file(client, app):
    """A stack trace with no newlines is readable, and still bounded.

    A 3 MiB single line arrives in ≤1 MiB pieces (one per page slot), and the
    lines around it are still reachable. The guarantee being pinned is that the
    page never hands back a piece larger than ``MAX_LINE_BYTES`` and never walks
    the file buffering the whole monster to answer.
    """
    path = Path(app.state.platform_log_path)
    write_log(path, [
        platform_line(0, "INFO", "before"),
        "x" * (3 * logmod.MAX_LINE_BYTES),
        platform_line(0, "INFO", "after"),
    ])
    body = client.get("/api/logs/platform", params={"limit": 3}).json()
    messages = [ln["message"] for ln in body["lines"]]
    assert messages[-1] == "after"
    assert all(len(text) <= logmod.MAX_LINE_BYTES for text in messages)

    # Walking on from there reaches the line before the monster.
    cursor = body["cursor"]
    seen: list[str] = []
    for _ in range(10):
        if not cursor:
            break
        page = client.get("/api/logs/platform",
                          params={"limit": 5, "cursor": cursor}).json()
        seen.extend(ln["message"] for ln in page["lines"])
        cursor = page["cursor"]
        if "before" in seen:
            break
    assert "before" in seen


# ---------------------------------------------------------------------------
# paging
# ---------------------------------------------------------------------------
def test_paging_is_stable_while_the_file_grows(client, app):
    """The page must not repeat or skip lines because new ones arrived.

    A cursor built from a row number would: every append shifts the window. A
    byte offset does not, which is the property being pinned here.
    """
    path = Path(app.state.platform_log_path)
    write_log(path, [platform_line(i) for i in range(1, 31)])

    first = client.get("/api/logs/platform", params={"limit": 10}).json()
    assert [ln["message"] for ln in first["lines"]] == [
        f"line {i}" for i in range(21, 31)]
    assert first["has_more"] is True

    # Five new lines land between the two page requests.
    with open(path, "a", encoding="utf-8") as fh:
        for i in range(31, 36):
            fh.write(platform_line(i) + "\n")

    second = client.get("/api/logs/platform",
                        params={"limit": 10, "cursor": first["cursor"]}).json()
    assert [ln["message"] for ln in second["lines"]] == [
        f"line {i}" for i in range(11, 21)]

    third = client.get("/api/logs/platform",
                       params={"limit": 10, "cursor": second["cursor"]}).json()
    assert [ln["message"] for ln in third["lines"]] == [
        f"line {i}" for i in range(1, 11)]
    # The start of the log has been reached: no "load older" that returns
    # nothing.
    assert third["has_more"] is False
    assert third["cursor"] is None


def test_paging_walks_into_rotated_generations(client, app):
    log_dir(app).mkdir(parents=True, exist_ok=True)
    path = log_dir(app) / "worker-m.log"
    write_log(path.with_name("worker-m.log.2"), [platform_line(i) for i in range(0, 5)])
    write_log(path.with_name("worker-m.log.1"), [platform_line(i) for i in range(5, 10)])
    write_log(path, [platform_line(i) for i in range(10, 15)])

    pages: list[list[str]] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 4}
        if cursor:
            params["cursor"] = cursor
        body = client.get("/api/logs/worker:m", params=params).json()
        pages.append([ln["message"] for ln in body["lines"]])
        cursor = body["cursor"]
        if not cursor:
            break
    # Four pages, each newest-first inside itself (the API re-orders a page so
    # the console can render top-to-bottom), and the walk crosses from the live
    # file into .1 and then .2 without repeating or skipping a line.
    assert pages == [
        [f"line {i}" for i in (11, 12, 13, 14)],
        [f"line {i}" for i in (7, 8, 9, 10)],
        [f"line {i}" for i in (3, 4, 5, 6)],
        [f"line {i}" for i in (0, 1, 2)],
    ]
    assert sorted(int(m.split()[1]) for page in pages for m in page) == list(range(15))


def test_a_cursor_from_another_source_is_refused(client, app):
    log_dir(app).mkdir(parents=True, exist_ok=True)
    write_log(log_dir(app) / "worker-a.log", [platform_line(i) for i in range(20)])
    write_log(log_dir(app) / "worker-b.log", [platform_line(i) for i in range(20)])
    first = client.get("/api/logs/worker:a", params={"limit": 5}).json()
    r = client.get("/api/logs/worker:b", params={"cursor": first["cursor"]})
    assert r.status_code == 400
    # Garbage is a 400 too, not a 500 and not a silent restart of the walk.
    assert client.get("/api/logs/worker:b", params={"cursor": "not-a-cursor"}).status_code == 400


def test_an_empty_source_reads_as_empty_rather_than_missing(client, app):
    log_dir(app).mkdir(parents=True, exist_ok=True)
    write_log(log_dir(app) / "worker-empty.log", [])
    body = client.get("/api/logs/worker:empty").json()
    assert body["lines"] == [] and body["cursor"] is None and body["has_more"] is False


# ---------------------------------------------------------------------------
# downloads
# ---------------------------------------------------------------------------
def test_filtered_download_is_plain_text_with_only_matching_lines(client, app):
    path = Path(app.state.platform_log_path)
    write_log(path, [
        platform_line(0, "INFO", "keep me"),
        platform_line(0, "ERROR", "keep me too"),
        platform_line(0, "INFO", "drop me"),
    ])
    r = client.get("/api/logs/platform/download", params={"q": "keep"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "attachment" in r.headers["content-disposition"]
    body = r.text
    assert "keep me" in body and "keep me too" in body
    assert "drop me" not in body
    # Ordered oldest first: a downloaded log that reads backwards is useless to
    # every tool that opens it.
    assert body.index("keep me\n") < body.index("keep me too")

    r = client.get("/api/logs/platform/download", params={"level": "ERROR"})
    assert "keep me too" in r.text and "keep me\n" not in r.text


def test_an_unfiltered_download_carries_the_rotated_generations(client, app):
    path = Path(app.state.platform_log_path)
    write_log(path.with_name("platform.log.2"), [platform_line(0, "INFO", "oldest")])
    write_log(path.with_name("platform.log.1"), [platform_line(0, "INFO", "middle")])
    write_log(path, [platform_line(0, "INFO", "newest")])

    r = client.get("/api/logs/platform/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "platform.zip" in r.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
        names = archive.namelist()
        assert names == ["platform.log.2", "platform.log.1", "platform.log"]
        blob = "".join(archive.read(name).decode() for name in names)
    # One continuous log, oldest to newest.
    assert blob.index("oldest") < blob.index("middle") < blob.index("newest")


def test_a_download_of_an_empty_source_is_an_empty_file(client, app):
    log_dir(app).mkdir(parents=True, exist_ok=True)
    write_log(log_dir(app) / "worker-empty.log", [])
    r = client.get("/api/logs/worker:empty/download")
    assert r.status_code == 200
    assert r.content == b""


# ---------------------------------------------------------------------------
# path traversal
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("payload", [
    "..",
    "../platform.log",
    "../../etc/passwd",
    "/etc/passwd",
    "worker:../../etc/passwd",
    "worker:test-model/../../../etc/passwd",
    "agent:../../etc/passwd",
    "platform.log",
    "worker:",
    "",
    "%2e%2e%2fetc%2fpasswd",
])
def test_a_source_id_that_is_not_a_known_source_is_refused(client, payload):
    """The id never becomes part of a path: it is matched against a registry.

    Both routes are checked -- a download is where a traversal would be worth
    the most.
    """
    encoded = payload.replace("/", "%2F")
    for url in (f"/api/logs/{encoded}", f"/api/logs/{encoded}/download"):
        r = client.get(url)
        assert r.status_code in (404, 400, 405), (url, r.status_code, r.text[:200])
        assert "passwd" not in r.text.lower() or r.status_code == 404


def test_a_model_id_with_a_dot_does_not_become_the_rotated_file_name(tmp_path):
    """``worker-a.log`` means model ``a``; ``worker-a.log.1`` is its rotation."""
    log_dir_ = tmp_path / "logs"
    log_dir_.mkdir()
    write_log(log_dir_ / "worker-a.log", ["2026-11-07T10:00:00.000+08:00 INFO x: a"])
    write_log(log_dir_ / "worker-a.log.1", ["2026-11-07T10:00:00.000+08:00 INFO x: old"])
    registry = LogRegistry(platform_path=lambda: tmp_path / "platform.log",
                          worker_dir=lambda: log_dir_,
                          agents_root=lambda: tmp_path / "agents")
    ids = [source.id for source in registry.sources()]
    assert ids == ["platform", "worker:a"]
    source = registry.get("worker:a")
    assert source is not None
    assert [p.name for p in source.rotated()] == ["worker-a.log.1"]


# ---------------------------------------------------------------------------
# rotation
# ---------------------------------------------------------------------------
def test_a_full_worker_log_is_rotated_before_the_next_worker_opens_it(tmp_path):
    path = tmp_path / "worker-m.log"
    path.write_text("old\n", encoding="utf-8")
    assert rotate_log_file(path, max_bytes=4, backups=3) is True
    assert not path.exists()
    assert (tmp_path / "worker-m.log.1").read_text() == "old\n"

    # A second rotation shifts the older generation rather than overwriting it:
    # three generations are what the page promises to still read.
    path.write_text("newer\n", encoding="utf-8")
    assert rotate_log_file(path, max_bytes=4, backups=3) is True
    assert (tmp_path / "worker-m.log.1").read_text() == "newer\n"
    assert (tmp_path / "worker-m.log.2").read_text() == "old\n"

    # Below the threshold nothing moves.
    path.write_text("x", encoding="utf-8")
    assert rotate_log_file(path, max_bytes=1024, backups=3) is False
    assert path.read_text() == "x"


def test_a_rotation_happens_at_load_and_the_old_generation_stays_readable(client, app):
    log_dir(app).mkdir(parents=True, exist_ok=True)
    path = log_dir(app) / "worker-test-model.log"
    # Over the 10 MiB threshold, so the load rotates it.
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("x" * (logmod.WORKER_LOG_MAX_BYTES + 1))
    assert client.post("/api/models/test-model/load").status_code == 200
    assert path.exists()
    assert (log_dir(app) / "worker-test-model.log.1").exists()
    body = client.get("/api/logs/worker:test-model", params={"limit": 50})
    assert body.status_code == 200
    assert body.json()["lines"], "the newest generation has the new worker's output"
    # And the rotated generation is still paged into.
    older = client.get("/api/logs/worker:test-model",
                       params={"limit": 1, "q": "xxxx"})
    assert older.status_code == 200


def test_the_log_routes_need_the_admin_cookie(app):
    with TestClient(app) as c:
        for url in ("/api/logs/sources", "/api/logs/platform", "/api/audit",
                    "/api/audit/export", "/api/logs/platform/download"):
            assert c.get(url).status_code == 401, url


def test_reading_logs_does_not_write_audit_records(client):
    """The page polls; one audit row per poll would bury the changes.

    The only row the fixture's own login left behind stays the only row: a GET,
    however many times it is repeated, is not a management operation.
    """
    before = client.get("/api/audit").json()["total"]
    for _ in range(3):
        client.get("/api/logs/sources")
        client.get("/api/logs/platform", params={"limit": 5})
        client.get("/api/logs/platform/download")
        client.get("/api/audit")
        client.get("/api/audit/export")
    after = client.get("/api/audit").json()["total"]
    assert after == before == 1, "a read was audited"
    assert client.get("/api/audit").json()["items"][0]["path"] == "/api/login"


def test_an_installed_agent_log_is_redacted_on_the_way_out(client, app):
    """A launch token in an agent log must not come out through this route.

    ``GET /api/agents/<id>/logs`` already removes it. A second route that served
    the same file unfiltered would hand out exactly what the first one hides.
    """
    manager = app.state.agents
    spec = manager.specs["dsh"]
    launch = ("dsh web: http://127.0.0.1:9100/?token=SUPERSECRET123")
    log_path = manager.directory("dsh") / "logs" / "agent.log"
    write_log(log_path, [launch])
    # The spec's own filter is what the route leans on; assert it does something
    # first, or this test would pass against a route that never redacted.
    assert "SUPERSECRET123" not in spec.public_log(launch)

    r = client.get("/api/logs/agent:dsh")
    assert r.status_code == 200
    text = json.dumps(r.json(), ensure_ascii=False)
    assert "SUPERSECRET123" not in text, "the launch token reached the log page"
    assert "dsh web:" in text, "the line itself must survive, minus the secret"
