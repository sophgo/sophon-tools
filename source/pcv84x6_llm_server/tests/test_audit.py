"""The management audit trail: who changed what (MYS-2674).

The claims this file defends, in the order an incident would need them:

* every state-changing ``/api`` call appears, with the result the client got --
  including a failed login, which is the one row an operator reads after a
  break-in attempt;
* a *failed* operation is recorded as failed, not as the 200 it was not;
* **a password or a key never reaches the database.** The last group reads the
  SQLite file's raw bytes, not the columns: a column-level assertion would pass
  while the secret sat in a WAL frame or an index page.
* the trail survives the things that kill a process: a corrupt file, a full
  disk, a data-directory move;
* retention is enforced, and it is days only.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.audit import (
    RETENTION_DAYS_DEFAULT,
    RETENTION_DAYS_MAX,
    RETENTION_DAYS_MIN,
    AuditStore,
    parse_action,
    summarise,
)
from app.main import create_app


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def make_model(root: Path, name: str) -> Path:
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{name}-int4_w4bf16_seq2048_4core_dynamic.bmodel").write_bytes(b"\x00" * 1024)
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


def rows(client, **params) -> list[dict]:
    r = client.get("/api/audit", params={"limit": 200, **params})
    assert r.status_code == 200, r.text
    return r.json()["items"]


def by_path(client) -> dict[str, dict]:
    """The newest row per (method, path) -- what "did this get recorded" asks."""
    out: dict[str, dict] = {}
    for row in rows(client):
        out.setdefault(f"{row['method']} {row['path']}", row)
    return out


def audit_path(app) -> Path:
    return Path(app.state.audit.path)


# ---------------------------------------------------------------------------
# coverage: the operations the card names
# ---------------------------------------------------------------------------
def test_login_success_and_failure_are_both_recorded(client):
    client.post("/api/login", json={"password": "wrong-password"})
    entries = rows(client)
    logins = [row for row in entries if row["path"] == "/api/login"]
    assert len(logins) == 2, logins
    failure, success = logins[0], logins[1]      # newest first
    assert failure["ok"] is False and failure["result"] == "failure"
    assert failure["status"] == 401
    assert "失败" in failure["summary"]
    assert success["ok"] is True and success["status"] == 200
    assert success["actor_type"] == "console" and success["actor_name"] == "admin"


def test_load_a_model_is_recorded_with_its_target(client):
    assert client.post("/api/models/test-model/load").status_code == 200
    row = by_path(client)["POST /api/models/test-model/load"]
    assert row["ok"] is True and row["status"] == 200
    # The route parameter, not the path pattern: "which model" is the question.
    assert row["target"] == "test-model"
    assert row["duration_ms"] >= 0
    assert row["ip"] and row["user_agent"]


def test_a_failed_operation_is_recorded_as_a_failure(client):
    """A 404 on a model that does not exist is still a management attempt."""
    r = client.post("/api/models/no-such-model/load")
    assert r.status_code in (404, 400, 409)
    row = by_path(client)["POST /api/models/no-such-model/load"]
    assert row["ok"] is False and row["status"] == r.status_code
    assert row["target"] == "no-such-model"


def test_changing_settings_records_the_fields_that_changed(client):
    r = client.post("/api/settings", json={"max_queue": 9, "prefix_cache_ttl_min": 60})
    assert r.status_code == 200
    row = by_path(client)["POST /api/settings"]
    assert row["ok"] is True
    summary = row["summary"]
    assert "max_queue=9" in summary and "prefix_cache_ttl_min=60" in summary
    # Fields the request did not name are not invented into the summary.
    assert "max_concurrent_per_model" not in summary


def test_creating_and_deleting_a_key_never_records_the_key(client, app):
    created = client.post("/api/keys", json={"name": "审计测试"}).json()
    raw = created["key"]
    key_id = created["meta"]["id"]
    client.delete(f"/api/keys/{key_id}")

    create_row = by_path(client)["POST /api/keys"]
    assert create_row["ok"] is True
    assert "审计测试" in create_row["summary"]
    delete_row = by_path(client)[f"DELETE /api/keys/{key_id}"]
    assert delete_row["target"] == key_id

    # The key itself is a credential: it must not be in the trail in any form,
    # including the name-only summary, the actor of a later request, or a WAL
    # frame.
    blob = audit_path(app).read_bytes()
    assert raw.encode() not in blob
    assert raw.removeprefix("sk-").encode() not in blob


def test_logout_and_password_change_are_recorded(client):
    assert client.post("/api/logout").status_code == 200
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    assert client.post("/api/password", json={"password": "new-secret-1"}).status_code == 200

    paths = by_path(client)
    assert paths["POST /api/logout"]["ok"] is True
    changed = paths["POST /api/password"]
    assert changed["ok"] is True
    # The body *is* the new password. Nothing about it may be quoted.
    assert "new-secret-1" not in json.dumps(changed, ensure_ascii=False)
    assert "new-secret-1" not in changed["summary"]


def test_a_read_is_not_an_operation(client):
    before = len(rows(client))
    for _ in range(3):
        client.get("/api/models")
        client.get("/api/stats")
        client.get("/api/settings")
        client.get("/api/keys")
    assert len(rows(client)) == before


def test_inference_requests_are_not_in_the_management_audit(client):
    """``/v1`` belongs to the inference records: one row per token would drown
    the trail, which is why the middleware never looks at those paths."""
    key = client.post("/api/keys", json={"name": "inference"}).json()["key"]
    h = {"Authorization": f"Bearer {key}"}
    assert client.post("/api/models/test-model/load").status_code == 200
    before = len(rows(client))
    client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 4,
    })
    assert len(rows(client)) == before


def test_an_unauthenticated_write_is_still_recorded_as_a_refusal(client):
    """A rejected attempt is a management event too, and is attributed.

    Since MYS-2676 an API key *can* authenticate ``/api``, but only an
    ``admin``-scoped one; a key minted with the default scope is refused with a
    403 that names it. Either way the trail shows the refusal, attributed to the
    key that tried -- by id and name, never by the key itself.
    """
    created = client.post("/api/keys", json={"name": "脚本"}).json()
    raw = created["key"]
    fresh = TestClient(client.app)      # no console cookie
    r = fresh.post("/api/settings", headers={"Authorization": f"Bearer {raw}"},
                   json={"max_queue": 3})
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden_scope"
    row = by_path(client)["POST /api/settings"]
    assert row["ok"] is False and row["status"] == 403
    assert row["actor_type"] == "api_key"
    assert row["actor_name"] == "脚本"
    assert raw not in json.dumps(row, ensure_ascii=False)


def test_no_credential_at_all_is_a_401(client):
    """Without a cookie or a key the answer is still "who are you"."""
    fresh = TestClient(client.app)
    r = fresh.post("/api/settings", json={"max_queue": 3})
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"
    row = by_path(client)["POST /api/settings"]
    assert row["ok"] is False and row["status"] == 401
    assert row["actor_type"] == "anonymous"


# ---------------------------------------------------------------------------
# the secret never lands, byte for byte
# ---------------------------------------------------------------------------
def test_the_database_file_contains_no_password_and_no_key(client, app):
    """The claim is about the *file*, not the columns.

    A column assertion can pass while the secret sits in a WAL frame, an index
    page or an overflow page. This reads the whole database -- WAL and shared
    memory included -- and looks for the exact strings.
    """
    password = "Hunter2-very-secret"
    assert client.post("/api/password", json={"password": password}).status_code == 200
    assert client.post("/api/login", json={"password": password}).status_code == 200
    assert client.post("/api/login", json={"password": "not-the-password"}).status_code == 401
    key = client.post("/api/keys", json={"name": "secret-check"}).json()["key"]
    assert client.post("/api/models/test-model/load").status_code == 200

    path = audit_path(app)
    conn = sqlite3.connect(path)
    try:
        # Fold the WAL into the main file so the raw read below covers it too.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    blobs = [path.read_bytes()]
    for suffix in ("-wal", "-shm"):
        sibling = path.with_name(path.name + suffix)
        if sibling.exists():
            blobs.append(sibling.read_bytes())
    blob = b"".join(blobs)

    assert password.encode() not in blob
    assert key.encode() not in blob
    assert key.removeprefix("sk-").encode() not in blob
    # And the trail is still useful: the operations themselves are there.
    assert b"/api/password" in blob or b"/api/settings" in blob


def test_a_sensitive_field_name_never_contributes_a_value():
    """Second line of defence: even if a route's whitelist were wrong."""
    body = json.dumps({"name": "ok", "password": "leak-me",
                       "api_key": "sk-leak", "token": "t0ken"}).encode()
    text = summarise("/api/keys", "POST", None, 200, body)
    assert text is not None and "ok" in text
    for secret in ("leak-me", "sk-leak", "t0ken"):
        assert secret not in text


def test_an_oversized_body_yields_no_summary_rather_than_a_guess():
    """A truncated JSON prefix is not parsed; the row simply has no summary."""
    body = b'{"name": "a", "padding": "' + b"x" * 100 + b'"'
    assert summarise("/api/keys", "POST", None, 200, body) is None


# ---------------------------------------------------------------------------
# querying and export
# ---------------------------------------------------------------------------
def _make_history(client) -> None:
    client.post("/api/settings", json={"max_queue": 4})
    client.post("/api/models/test-model/load")
    client.post("/api/models/test-model/unload")
    client.post("/api/keys", json={"name": "alpha"})
    client.post("/api/keys", json={"name": "beta"})
    client.post("/api/login", json={"password": "nope"})


def test_filters_narrow_by_actor_action_and_result(client):
    _make_history(client)

    assert {row["path"] for row in rows(client, action="/api/keys")} == {"/api/keys"}
    assert all(row["method"] == "POST" for row in rows(client, action="POST"))
    assert all(row["path"].startswith("/api/models")
               for row in rows(client, action="POST /api/models"))
    # A prefix matches the paths below it too.
    assert {row["path"] for row in rows(client, action="/api/models")} == {
        "/api/models/test-model/load", "/api/models/test-model/unload"}
    assert all(row["ok"] is False for row in rows(client, status="failure"))
    assert all(row["ok"] is True for row in rows(client, status="success"))
    # 成功/失败 are what the console's own filter sends.
    assert all(row["ok"] is False for row in rows(client, status="失败"))
    assert [row for row in rows(client, actor="admin")], "the console operator"
    assert rows(client, actor="nobody-at-all") == []
    assert [row for row in rows(client, q="alpha")]
    assert rows(client, q="no-such-text-anywhere") == []


def test_time_window_filters(client):
    _make_history(client)
    now = time.time()
    assert rows(client, since=now - 3600)
    assert rows(client, since=now + 3600) == []
    assert rows(client, until=now + 3600)
    assert rows(client, until=now - 3600) == []
    assert rows(client, since="-30m")


def test_paging_walks_the_history_once(client):
    _make_history(client)
    total = client.get("/api/audit").json()["total"]
    assert total >= 7
    seen: list[int] = []
    offset = 0
    while True:
        page = client.get("/api/audit", params={"limit": 2, "offset": offset}).json()
        seen.extend(row["id"] for row in page["items"])
        offset += 2
        if offset >= page["total"]:
            break
    assert len(seen) == total
    assert len(set(seen)) == total, "a page repeated a row"
    assert seen == sorted(seen, reverse=True), "newest first"


def test_the_csv_export_opens_in_excel(client):
    _make_history(client)
    r = client.get("/api/audit/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    raw = r.content
    # The BOM is what makes Excel read the Chinese headers as UTF-8.
    assert raw.startswith("﻿".encode("utf-8"))
    text = raw.decode("utf-8-sig")
    header = text.splitlines()[0]
    assert header.startswith("时间,") and "操作者" in header and "结果" in header
    body = text.splitlines()[1:]
    assert len(body) == client.get("/api/audit").json()["total"]
    assert any("成功" in line for line in body)

    # The export honours the same filters as the list.
    filtered = client.get("/api/audit/export", params={"action": "/api/keys"})
    keys_only = filtered.content.decode("utf-8-sig").splitlines()[1:]
    assert keys_only and all("/api/keys" in line for line in keys_only)


def test_parse_action_accepts_the_forms_an_operator_types():
    assert parse_action("POST /api/models") == ("POST", "/api/models")
    assert parse_action("/api/models POST") == ("POST", "/api/models")
    assert parse_action("DELETE") == ("DELETE", None)
    assert parse_action("/api/settings") == (None, "/api/settings")
    assert parse_action(None) == (None, None)
    assert parse_action("nonsense") == (None, None)


# ---------------------------------------------------------------------------
# retention
# ---------------------------------------------------------------------------
def _entry(store, *, ts: float, path: str = "/api/settings") -> dict:
    return {"ts": ts, "actor_type": "console", "actor_name": "admin",
            "ip": "127.0.0.1", "method": "POST", "path": path,
            "status": 200, "duration_ms": 1.0, "summary": "x"}


def older_than(store, seconds: float) -> int:
    """Rows older than ``seconds`` ago -- the retention tests' measuring stick.

    Counting beat the fixture's own login rows, which are also in the table;
    counting the *old* ones is what the retention rule is actually about.
    """
    with store._lock:
        conn = store._conn_or_open()
        return int(conn.execute("SELECT COUNT(*) FROM audit_records WHERE ts < ?",
                                (time.time() - seconds,)).fetchone()[0])


def test_retention_deletes_by_days(tmp_path):
    store = AuditStore(tmp_path / "audit.db", retention_days=30)
    now = time.time()
    try:
        # The insert itself prunes, so a backdated row is gone the moment it
        # lands: retention is a policy about the table, not about the row that
        # happens to be arriving.
        assert store.record(_entry(store, ts=now - 40 * 86400)) is True
        assert older_than(store, 31 * 86400) == 0, \
            "a 40-day-old row survived a 30-day retention"
        assert store.record(_entry(store, ts=now - 10 * 86400)) is True
        assert store.record(_entry(store, ts=now)) is True
        # The 10-day-old row is inside the window and stays; the 40-day-old one
        # is gone; the fresh one is there.
        assert older_than(store, 5 * 86400) == 1
        assert store.count() == 2
    finally:
        store.close()


def test_retention_is_clamped_to_the_documented_range(tmp_path):
    high = AuditStore(tmp_path / "high.db", retention_days=99999)
    try:
        assert high.retention_days == RETENTION_DAYS_MAX
    finally:
        high.close()
    low = AuditStore(tmp_path / "low.db", retention_days=1)
    try:
        assert low.retention_days == RETENTION_DAYS_MIN
    finally:
        low.close()
    # The setting's own clamp agrees with the store's, so a value accepted by
    # the API can never be one the store would quietly rewrite.
    from app.core.state import Settings
    assert Settings(audit_retention_days=1).clamp().audit_retention_days == RETENTION_DAYS_MIN
    assert Settings(audit_retention_days=99999).clamp().audit_retention_days == RETENTION_DAYS_MAX


def test_the_default_retention_is_180_days(app):
    assert app.state.store.settings.audit_retention_days == RETENTION_DAYS_DEFAULT == 180
    assert app.state.audit.retention_days == 180
    assert 30 <= RETENTION_DAYS_DEFAULT <= 3650


def test_changing_the_retention_applies_immediately(client, app):
    """Lowering it must prune now, not at the next management operation."""
    store = app.state.audit
    old = time.time() - 100 * 86400
    assert store.record(_entry(store, ts=old, path="/api/models/old/load")) is True
    assert older_than(store, 90 * 86400) == 1, "the seeded row should be there"

    r = client.post("/api/settings", json={"audit_retention_days": 60})
    assert r.status_code == 200
    assert r.json()["settings"]["audit_retention_days"] == 60
    assert store.retention_days == 60
    assert older_than(store, 90 * 86400) == 0, \
        "the 100-day-old row survived a 60-day retention"

    # And it is published, with its bounds, the way the other numeric settings
    # are -- the console's spinner should not restate the limits.
    view = client.get("/api/settings").json()
    assert view["audit_retention_days"] == 60
    assert view["audit_retention_days_min"] == 30
    assert view["audit_retention_days_max"] == 3650


def test_an_out_of_range_retention_is_clamped_not_refused(client, app):
    r = client.post("/api/settings", json={"audit_retention_days": 5})
    assert r.status_code == 200
    assert r.json()["settings"]["audit_retention_days"] == RETENTION_DAYS_MIN
    r = client.post("/api/settings", json={"audit_retention_days": 100000})
    assert r.json()["settings"]["audit_retention_days"] == RETENTION_DAYS_MAX
    # And the value survives a restart, like every other setting.
    assert app.state.store.settings.audit_retention_days == RETENTION_DAYS_MAX


# ---------------------------------------------------------------------------
# failure modes: the trail must never take the service with it
# ---------------------------------------------------------------------------
def test_a_database_that_cannot_be_opened_does_not_break_the_request(tmp_path):
    path = tmp_path / "audit.db"
    path.write_bytes(b"this is not a database, it is a text file" * 4)
    store = AuditStore(path)
    # ``record`` reports; it never raises into the request that triggered it.
    assert store.record(_entry(store, ts=time.time())) is False
    assert store.last_error
    assert store.dropped == 1
    store.close()


def test_the_status_route_reports_a_broken_trail(client, app):
    """A file that stopped being a database is reported, not raised.

    ``/api/audit`` answers 503 with the reason -- an empty 200 table would read
    as "nobody changed anything", which is the one thing a broken audit trail
    must never look like. Everything else keeps serving.
    """
    store = app.state.audit
    store._discard_connection()
    store.path.write_bytes(b"corrupt" * 100)
    store._open()
    assert store.last_error, "a corrupt file must leave a reason behind"

    r = client.get("/api/audit")
    assert r.status_code == 503
    assert "database" in r.json()["detail"].lower()
    # The service keeps serving: the audit being unreadable is a report, not a
    # 500 on unrelated pages.
    assert client.get("/api/models").status_code == 200


# ---------------------------------------------------------------------------
# a data-directory move carries the trail
# ---------------------------------------------------------------------------
def settle(client, timeout=30.0) -> dict:
    import time as _time
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        job = client.get("/api/storage/move").json()
        if job["state"] in ("done", "failed", "idle"):
            return job
        _time.sleep(0.05)
    raise AssertionError("the move did not finish")


def test_the_audit_and_the_platform_log_follow_a_data_directory_move(tmp_path):
    """Both live under ``state/``; a move that left them behind would silently
    start a second, empty trail in the new tree while the old one is deleted."""
    root = tmp_path / "data"
    models = root / "models"
    make_model(models, "test-model")
    app = create_app(data_root=root, backend_kind="mock",
                     web_dir=tmp_path / "web", context_length_override=4096)
    target = tmp_path / "moved"
    with TestClient(app) as client:
        assert client.post("/api/login", json={"password": "admin"}).status_code == 200
        assert client.post("/api/settings", json={"max_queue": 7}).status_code == 200
        import logging
        logging.getLogger("cv84x6.movetest").warning("迁移前的平台日志")
        app.state.platform_log.flush()
        assert client.get("/api/audit").json()["total"] >= 1

        assert client.post("/api/storage/move", json={"path": str(target)}).status_code == 202
        job = settle(client)
        assert job["state"] == "done", job

        # The trail is the one that was copied, not a fresh empty one.
        assert Path(app.state.audit.path) == target / "state" / "audit.db"
        paths = {row["path"] for row in client.get("/api/audit").json()["items"]}
        assert "/api/settings" in paths

        # The platform log continues in the new tree.
        assert Path(app.state.platform_log_path) == target / "state" / "logs" / "platform.log"
        logging.getLogger("cv84x6.movetest").warning("迁移后的平台日志")
        app.state.platform_log.flush()
        text = (target / "state" / "logs" / "platform.log").read_text(encoding="utf-8")
        assert "迁移后的平台日志" in text

        # And a new operation lands in the new file.
        before = client.get("/api/audit").json()["total"]
        assert client.post("/api/settings", json={"max_queue": 8}).status_code == 200
        assert client.get("/api/audit").json()["total"] == before + 1

        # The log page follows the move too.
        sources = {item["id"] for item in client.get("/api/logs/sources").json()["sources"]}
        assert "platform" in sources
        body = client.get("/api/logs/platform", params={"limit": 50}).json()
        assert any("迁移后的平台日志" in ln["message"] for ln in body["lines"])
