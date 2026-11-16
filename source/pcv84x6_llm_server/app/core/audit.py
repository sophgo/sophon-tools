"""Who changed what, when, from where (MYS-2674): the management audit trail.

The inference log answers "what did the model say". This answers a different
question, the one an operator asks after an incident: **who changed this
setting, and when**. It is written by one ASGI middleware rather than by a line
in each of the thirty-odd ``/api`` handlers -- a trail that depends on every
handler remembering to write it has holes in it, and the holes are exactly the
endpoints someone forgot.

What is recorded, and what deliberately is not:

* **Every state-changing request under ``/api/``** -- POST, PUT, PATCH, DELETE
  -- plus a login attempt (success or failure) and a logout. ``/v1/*`` is not
  audited: those are inferences, and ``docs/inference-records.md`` owns them.
* **Reads are not audited.** ``GET /api/logs/*`` in particular: a log viewer
  polls, and one row per polled page would bury the changes it exists to show.
* **No request body, ever.** A whitelist pulls a handful of summary fields out
  of a bounded prefix of the body (a setting's name and its new value, a key's
  name, a download's name). A field whose *name* looks like a credential -- or
  that is a password by definition, like the login body -- never contributes a
  value, and values are length-capped. The test suite checks the database file
  byte for byte for the password and the minted key, not just the columns.
* **No key material.** The actor is an API key's id and name, never its hash or
  its text; a console session is recorded as ``admin``, never as the cookie.

Storage is a single SQLite file (``<data dir>/state/audit.db``) of its own, not
a table in the inference records' file: the two have different retention, write
rates and readers, and a corrupt audit trail must not take the inference history
with it. Retention is days only, 180 by default, configured as
``audit_retention_days`` (30-3650).

Structure and the field meanings are documented in ``docs/logs.md``.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_FILENAME = "audit.db"

#: Retention is days only. The bounds live in ``core.state`` (next to the
#: setting that carries them) and are re-exported here so this module can clamp
#: without importing the settings model; one definition, two readers.
from .state import (  # noqa: E402 - after the docstring, before first use
    AUDIT_RETENTION_DAYS_DEFAULT,
    AUDIT_RETENTION_DAYS_MAX,
    AUDIT_RETENTION_DAYS_MIN,
)

RETENTION_DAYS_MIN = AUDIT_RETENTION_DAYS_MIN
RETENTION_DAYS_MAX = AUDIT_RETENTION_DAYS_MAX
RETENTION_DAYS_DEFAULT = AUDIT_RETENTION_DAYS_DEFAULT

#: Methods that change state. GET/HEAD/OPTIONS are reads (or preflights) and are
#: not audited; a CORS preflight in the trail would be nothing but noise.
AUDITED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: How much of a request body the summary extractor may look at. A settings
#: save is a few hundred bytes; the cap is what keeps a 48 MiB image upload
#: from being buffered by a middleware that only wanted to read a field name.
BODY_PREFIX_BYTES = 64 * 1024

#: A summary is a line in a table, not a document.
SUMMARY_MAX_CHARS = 300
#: Paths and user agents are attacker-controlled; both are capped before they
#: reach the database.
PATH_MAX_CHARS = 512
UA_MAX_CHARS = 256

#: Any field whose name matches this never contributes a value to a summary.
#: A whitelist runs on top of it (``_summary_fields``), so this is the second
#: line of defence rather than the only one.
_SENSITIVE_NAME = re.compile(
    r"pass(word|wd)?|secret|token|api[_-]?key|authorization|cookie|credential|"
    r"private[_-]?key|signature",
    re.IGNORECASE,
)

#: Status columns: what a client received, and the same fact as a word. Both
#: are stored so a filter and an export never have to re-derive the rule.
OK_MAX_STATUS = 399

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL NOT NULL,          -- epoch seconds; also the sort key
    ts_iso      TEXT NOT NULL,          -- local ISO8601 with offset, as shown
    actor_type  TEXT,                   -- console | api_key | anonymous
    actor_id    TEXT,
    actor_name  TEXT,
    ip          TEXT,
    user_agent  TEXT,
    method      TEXT NOT NULL,
    path        TEXT NOT NULL,
    target      TEXT,                   -- the route parameter, e.g. a model id
    status      INTEGER NOT NULL,       -- HTTP status the client got
    ok          INTEGER NOT NULL,       -- 1 = success, 0 = failure
    duration_ms REAL,
    summary     TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_records (ts DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_audit_ok ON audit_records (ok, ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_records (actor_name, ts DESC);
"""

_INSERT_SQL = """
INSERT INTO audit_records (
    ts, ts_iso, actor_type, actor_id, actor_name, ip, user_agent,
    method, path, target, status, ok, duration_ms, summary
) VALUES (
    :ts, :ts_iso, :actor_type, :actor_id, :actor_name, :ip, :user_agent,
    :method, :path, :target, :status, :ok, :duration_ms, :summary
)
"""

_COLUMNS = ("id", "ts", "ts_iso", "actor_type", "actor_id", "actor_name", "ip",
            "user_agent", "method", "path", "target", "status", "ok",
            "duration_ms", "summary")

#: CSV column order and headers. Chinese because the file is opened in Excel by
#: the same operator who reads the console; the BOM in ``csv_chunks`` is what
#: makes those headers legible there instead of mojibake.
CSV_HEADERS = ("时间", "操作者类型", "操作者", "来源 IP", "方法", "路径", "目标",
               "结果", "状态码", "耗时(ms)", "摘要", "User-Agent")

EXPORT_CHUNK = 500


def local_iso(epoch: float) -> str:
    """The console's own timestamp form: local time with its UTC offset.

    Local because an operator compares it with ``journalctl`` and with their
    own clock; the offset because the board's timezone is not knowable from the
    file after it is copied off the board.
    """
    return datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# actor
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Actor:
    actor_type: str          # "console" | "api_key" | "anonymous"
    actor_id: str | None
    actor_name: str | None

    def as_dict(self) -> dict:
        return {"actor_type": self.actor_type, "actor_id": self.actor_id,
                "actor_name": self.actor_name}


ANONYMOUS = Actor("anonymous", None, None)
CONSOLE = Actor("console", None, "admin")


def resolve_actor(app_state, headers: dict[bytes, bytes], *,
                  path: str, status: int) -> Actor:
    """Who this request's credentials say it is, without touching the secret.

    The console cookie is verified (HMAC), not recorded; an API key is looked up
    by hash and reported by id and name. A login that *succeeded* has no cookie
    on the request -- the response sets it -- so it is attributed to the console
    operator, which is what "someone logged in as admin" means.
    """
    cookie_header = headers.get(b"cookie", b"").decode("latin-1")
    token = _cookie_value(cookie_header, _COOKIE_NAME)
    sessions = getattr(app_state, "sessions", None)
    if token and sessions is not None:
        try:
            if sessions.verify(token):
                return CONSOLE
        except Exception:  # pragma: no cover - a broken session is not a 500 here
            pass
    store = getattr(app_state, "store", None)
    raw = _bearer(headers)
    if raw and store is not None:
        try:
            key = store.find_key(raw)
        except Exception:  # pragma: no cover
            key = None
        if key is not None:
            return Actor("api_key", key.id, key.name)
    if path == "/api/login" and status < 400:
        return CONSOLE
    return ANONYMOUS


#: Duplicated rather than imported so this module keeps no import edge into
#: ``app.core.auth`` (which imports ``state``, which imports nothing here).
_COOKIE_NAME = "cv84x6_admin"


def _cookie_value(header: str, name: str) -> str:
    for part in header.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            value = value.strip()
            # A Set-Cookie value is quoted whenever it holds a character a
            # cookie cannot carry bare -- and this signed token ends in "=".
            # Starlette's own parser unquotes it, so a client that echoed the
            # header verbatim would otherwise never be recognised.
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1]
            return value
    return ""


def _bearer(headers: dict[bytes, bytes]) -> str:
    raw = headers.get(b"authorization", b"").decode("latin-1")
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return headers.get(b"api-key", b"").decode("latin-1").strip()


# ---------------------------------------------------------------------------
# summary extraction
# ---------------------------------------------------------------------------
#: A whitelist per route *shape*: which body fields may appear in a summary.
#: Anything not named here never reaches the database, including every field on
#: every route this table does not mention -- the default is "no summary", not
#: "everything".
_BODY_FIELDS: dict[str, tuple[str, ...]] = {
    "/api/settings": (),        # filled in from the settings model, see below
    # ``scope`` is quoted because minting an admin key is the one key operation
    # whose consequence is a new credential that can change the board; "created a
    # key" alone would not tell an auditor what it was created *for* (MYS-2676).
    "/api/keys": ("name", "scope"),
    "/api/downloads": ("name", "kind"),
}


def _settings_fields() -> tuple[str, ...]:
    """The settings names a summary may quote, from the one place they live.

    Imported lazily: ``admin_api`` pulls in the model manager and the engine
    adapters, which a middleware running on every login has no business
    importing at module load. A field added to the settings save is therefore
    summarised without touching this file, which is the point.
    """
    try:
        from ..api.admin_api import _SETTING_FIELDS
    except Exception:  # pragma: no cover - import cycle guard
        return ()
    return tuple(_SETTING_FIELDS)


def summarise(path: str, method: str, target: str | None, status: int,
              body: bytes | None) -> str | None:
    """One short line saying what was asked for -- from a whitelist, never raw.

    Route *templates* are matched by prefix, so ``/api/models/<id>/load`` is
    recognised without this module having to know every model id in existence.
    """
    if path == "/api/login":
        return "登录成功" if status < 400 else "登录失败（口令不正确或未授权）"
    if path == "/api/logout":
        return "退出登录"
    if path == "/api/password":
        # The body is the new password. Nothing about it may be quoted, not
        # even its length.
        return "修改管理员登录口令"
    fields = _BODY_FIELDS.get(path)
    if fields == ():  # settings: the whitelist is the settings model's fields
        fields = _settings_fields()
    if fields:
        return _fields_summary(path, body, fields)
    if path == "/api/inference-records/clear":
        return "清空推理记录"
    if path.endswith("/revoke") and path.startswith("/api/keys/"):
        return "吊销 API key"
    return None


def _fields_summary(path: str, body: bytes | None, fields: Iterable[str]) -> str | None:
    payload = _json_prefix(body)
    if not isinstance(payload, dict):
        return None
    allowed = set(fields)
    parts: list[str] = []
    for name in sorted(allowed):
        if name not in payload:
            continue
        if _SENSITIVE_NAME.search(name):  # belt and braces; whitelist already ran
            continue
        value = _short_value(payload[name])
        parts.append(f"{name}={value}")
    if not parts:
        return None
    text = ", ".join(parts)
    return text if len(text) <= SUMMARY_MAX_CHARS else text[:SUMMARY_MAX_CHARS] + "…"


def _json_prefix(body: bytes | None):
    """Parse the buffered body prefix, tolerating a truncated one.

    A body longer than ``BODY_PREFIX_BYTES`` cannot be parsed as JSON. The
    extractor then finds nothing and the row simply has no summary, which is the
    honest outcome: guessing at half a document would put invented values in an
    audit trail.
    """
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except (ValueError, UnicodeDecodeError):
        return None


def _short_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"
    if isinstance(value, str):
        text = value if len(value) <= 64 else value[:64] + "…"
        # A newline in a summary would break the one-row-per-change reading.
        return json.dumps(text, ensure_ascii=False)
    if isinstance(value, (list, dict)):
        return f"<{type(value).__name__} {len(value)}>"
    return "<value>"


# ---------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------
class AuditStore:
    """One SQLite file of management operations.

    Shaped like ``InferenceLogStore`` on purpose -- one lock around one
    connection, WAL so a reader never blocks the writer, ``close``/``reopen``/
    ``rebind`` for a data-directory move -- because an operator debugging one of
    them should not have to learn a second set of rules. What differs is the
    contract with the request: ``record`` is called from a middleware, so it
    must never raise and must never wait long.
    """

    def __init__(self, path: str | Path, *, retention_days: int = RETENTION_DAYS_DEFAULT,
                 enabled: bool = True) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.enabled = bool(enabled)
        self.retention_days = _clamp(retention_days, RETENTION_DAYS_MIN,
                                     RETENTION_DAYS_MAX)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        # Set while a data-directory move copies the file; writes are dropped
        # (and counted) rather than written into a tree about to be deleted.
        self._closed = False
        self.last_error: str | None = None
        #: Rows lost to a move or to a write failure. Surfaced so "the trail is
        #: complete" is never claimed by an empty table.
        self.dropped = 0
        self._open()

    # -- lifecycle -------------------------------------------------------
    def _open(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            self._closed = False
            conn = None
            try:
                conn = sqlite3.connect(str(self.path), check_same_thread=False,
                                       timeout=10.0, isolation_level=None)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA busy_timeout=10000")
                conn.executescript(_SCHEMA)
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    ("schema_version", str(SCHEMA_VERSION)))
            except (sqlite3.Error, OSError) as exc:
                self._note_error(exc)
                if conn is not None:
                    try:
                        conn.close()
                    except sqlite3.Error:  # pragma: no cover
                        pass
                return
            self._conn = conn

    def _note_error(self, exc: BaseException) -> None:
        message = f"{type(exc).__name__}: {exc}"
        with self._lock:
            if message != self.last_error:
                logger.warning("an audit record could not be stored: %s", message)
            self.last_error = message

    def close(self) -> None:
        """Release the file so a data-directory move copies it with no writer."""
        with self._lock:
            self._closed = True
            conn, self._conn = self._conn, None
            if conn is None:
                return
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:  # pragma: no cover - best effort
                pass
            try:
                conn.close()
            except sqlite3.Error:  # pragma: no cover
                pass

    def reopen(self) -> None:
        with self._lock:
            self._closed = False
            self._open()

    def rebind(self, path: str | Path) -> None:
        new_path = Path(path)
        with self._lock:
            self.close()
            self.path = new_path
        self.reopen()

    def configure(self, *, retention_days: int | None = None,
                  enabled: bool | None = None) -> None:
        with self._lock:
            if retention_days is not None:
                self.retention_days = _clamp(retention_days, RETENTION_DAYS_MIN,
                                             RETENTION_DAYS_MAX)
            if enabled is not None:
                self.enabled = bool(enabled)

    # -- writing ---------------------------------------------------------
    def record(self, entry: dict) -> bool:
        """Store one operation. Never raises, never fails a request."""
        if not self.enabled:
            return False
        if self._closed:
            # Parked for a move. Writes are dropped and counted: a row written
            # here would land in the tree the copy is reading or deleting.
            self.dropped += 1
            return False
        row = _row_for(entry)
        try:
            with self._lock:
                conn = self._conn_or_open()
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.execute(_INSERT_SQL, row)
                    self._prune(conn, time.time())
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                self.last_error = None
            return True
        except Exception as exc:  # noqa: BLE001 - the trail must never 500 a request
            self.dropped += 1
            self._note_error(exc)
            self._discard_connection()
            return False

    def _prune(self, conn: sqlite3.Connection, now: float) -> None:
        """Drop rows older than the retention window.

        Anchored on ``now`` (the request's clock), not on the row's own
        timestamp: a row being written today with a *backdated* timestamp -- a
        clock step, or a test seeding history -- would otherwise sit in the table
        forever, because every later insert prunes relative to a time that has
        already moved past it. The window is one fixed policy for the table.
        """
        cutoff = now - self.retention_days * 86400
        conn.execute("DELETE FROM audit_records WHERE ts < ?", (cutoff,))

    def prune_now(self) -> int:
        """Apply retention outside a write (used after the setting changes)."""
        with self._lock:
            conn = self._conn_or_open()
            conn.execute("BEGIN IMMEDIATE")
            try:
                cutoff = time.time() - self.retention_days * 86400
                removed = conn.execute(
                    "DELETE FROM audit_records WHERE ts < ?", (cutoff,)).rowcount
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return max(0, int(removed or 0))

    def _conn_or_open(self) -> sqlite3.Connection:
        if self._conn is None:
            if self._closed:
                raise RuntimeError("审计库正在随数据目录迁移")
            self._open()
        if self._conn is None:
            raise RuntimeError(self.last_error or "审计库无法打开")
        return self._conn

    def _discard_connection(self) -> None:
        with self._lock:
            conn, self._conn = self._conn, None
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:  # pragma: no cover
                    pass

    # -- reading ---------------------------------------------------------
    def query(self, *, since: float | None = None, until: float | None = None,
              actor: str | None = None, action: str | None = None,
              status: str | None = None, q: str | None = None,
              limit: int = 50, offset: int = 0) -> dict:
        """A page of operations, newest first.

        ``action`` is "方法 + 路径前缀" in one string -- ``"POST /api/models"``,
        ``"POST"``, ``"/api/settings"`` -- because that is how an operator
        thinks about it ("谁动过模型"), and splitting a single parameter is what
        keeps the query string from growing one field per axis.
        """
        limit = _clamp(limit, 1, 500)
        offset = max(0, int(offset))
        where, args = _where(since=since, until=until, actor=actor,
                             action=action, status=status, q=q)
        with self._lock:
            conn = self._conn_or_open()
            total = int(conn.execute(
                "SELECT COUNT(*) FROM audit_records" + where, args).fetchone()[0])
            rows = conn.execute(
                "SELECT " + ", ".join(_COLUMNS) + " FROM audit_records" + where +
                " ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
                (*args, limit, offset)).fetchall()
        return {"items": [_as_dict(r) for r in rows], "total": total,
                "limit": limit, "offset": offset}

    def iter_all(self, *, since: float | None = None, until: float | None = None,
                 actor: str | None = None, action: str | None = None,
                 status: str | None = None, q: str | None = None,
                 chunk: int = EXPORT_CHUNK) -> Iterator[dict]:
        """Every matching row, one bounded page at a time, newest first."""
        where, args = _where(since=since, until=until, actor=actor,
                             action=action, status=status, q=q)
        offset = 0
        while True:
            with self._lock:
                conn = self._conn_or_open()
                rows = conn.execute(
                    "SELECT " + ", ".join(_COLUMNS) + " FROM audit_records" + where +
                    " ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
                    (*args, chunk, offset)).fetchall()
            if not rows:
                return
            for row in rows:
                yield _as_dict(row)
            if len(rows) < chunk:
                return
            offset += chunk

    def csv_chunks(self, **filters) -> Iterator[str]:
        """The export as CSV text: a UTF-8 BOM, then a header, then rows.

        The BOM is not decoration: without it Excel on a Chinese Windows reads
        the file as GBK and every header and summary is mojibake. Rows are
        streamed, so a year of audit records does not become one string.
        """
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n")
        yield "﻿"
        writer.writerow(CSV_HEADERS)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for index, row in enumerate(self.iter_all(**filters)):
            writer.writerow(_csv_row(row))
            if index % EXPORT_CHUNK == EXPORT_CHUNK - 1:
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)
        remaining = buffer.getvalue()
        if remaining:
            yield remaining

    def count(self) -> int:
        with self._lock:
            conn = self._conn_or_open()
            return int(conn.execute("SELECT COUNT(*) FROM audit_records").fetchone()[0])


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------
def _row_for(entry: dict) -> dict:
    ts = float(entry.get("ts") or time.time())
    status = int(entry.get("status") or 0)
    return {
        "ts": ts,
        "ts_iso": entry.get("ts_iso") or local_iso(ts),
        "actor_type": _cut(entry.get("actor_type"), 32),
        "actor_id": _cut(entry.get("actor_id"), 64),
        "actor_name": _cut(entry.get("actor_name"), 128),
        "ip": _cut(entry.get("ip"), 64),
        "user_agent": _cut(entry.get("user_agent"), UA_MAX_CHARS),
        "method": _cut(entry.get("method"), 16) or "",
        "path": _cut(entry.get("path"), PATH_MAX_CHARS) or "",
        "target": _cut(entry.get("target"), 128),
        "status": status,
        "ok": 1 if status and status <= OK_MAX_STATUS else 0,
        "duration_ms": round(float(entry.get("duration_ms") or 0.0), 1),
        "summary": _cut(entry.get("summary"), SUMMARY_MAX_CHARS),
    }


def _cut(value, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[:limit]


def _as_dict(row: sqlite3.Row) -> dict:
    data = {key: row[key] for key in _COLUMNS}
    data["ok"] = bool(data["ok"])
    data["result"] = "success" if data["ok"] else "failure"
    return data


def _csv_row(row: dict) -> tuple:
    return (
        row["ts_iso"],
        {"console": "控制台", "api_key": "API key"}.get(
            row["actor_type"], row["actor_type"] or ""),
        row["actor_name"] or "",
        row["ip"] or "",
        row["method"],
        row["path"],
        row["target"] or "",
        "成功" if row["ok"] else "失败",
        row["status"],
        f"{row['duration_ms']:.1f}",
        row["summary"] or "",
        row["user_agent"] or "",
    )


def _where(*, since, until, actor, action, status, q) -> tuple[str, list]:
    clauses: list[str] = []
    args: list = []
    if since is not None:
        clauses.append("ts >= ?")
        args.append(float(since))
    if until is not None:
        clauses.append("ts <= ?")
        args.append(float(until))
    if actor:
        # Matches the display name or the key's id: an operator knows the name,
        # a script knows the id, and both mean the same actor here.
        clauses.append("(actor_name LIKE ? ESCAPE '\\' OR actor_id = ?)")
        args.extend([f"%{_escape_like(actor)}%", actor])
    method, prefix = parse_action(action)
    if method:
        clauses.append("method = ?")
        args.append(method)
    if prefix:
        # A prefix means "this path and everything below it", so
        # ``/api/models`` also matches ``/api/models/x/load``. String
        # comparison rather than LIKE, so ``_`` in a path is literal.
        clauses.append("(path = ? OR substr(path, 1, ?) = ?)")
        args.extend([prefix, len(prefix) + 1, prefix + "/"])
    if status:
        wanted = _status_flag(status)
        if wanted is not None:
            clauses.append("ok = ?")
            args.append(wanted)
    if q:
        clauses.append(
            "(path LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\'"
            " OR actor_name LIKE ? ESCAPE '\\' OR target LIKE ? ESCAPE '\\')")
        pattern = f"%{_escape_like(q)}%"
        args.extend([pattern] * 4)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", args


def parse_action(action: str | None) -> tuple[str | None, str | None]:
    """``"POST /api/models"`` -> (``"POST"``, ``"/api/models"``).

    A bare method, a bare prefix, or both, in either order of convenience --
    anything else is ignored rather than refused, so a typo narrows nothing
    instead of returning a 400 the console cannot explain.
    """
    if not action:
        return None, None
    method = None
    prefix = None
    for token in action.split():
        upper = token.upper()
        if method is None and upper in (AUDITED_METHODS | {"GET", "HEAD", "OPTIONS"}):
            method = upper
        elif prefix is None and token.startswith("/"):
            prefix = token
    return method, prefix


def _status_flag(status: str) -> int | None:
    text = status.strip().lower()
    if text in ("success", "ok", "1", "true", "成功"):
        return 1
    if text in ("failure", "failed", "error", "0", "false", "失败"):
        return 0
    return None


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _clamp(value: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = low
    return max(low, min(high, number))


def utc_iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# the middleware
# ---------------------------------------------------------------------------
#: Route parameters that name the thing acted on, in priority order. The first
#: one present in a matched route is the row's ``target``: "which model" is the
#: question this column answers, and a path like
#: ``/api/models/mymodel/load`` carries it only as a parameter.
_TARGET_PARAMS = ("model_id", "key_id", "agent_id", "job_id", "record_id")


class AuditMiddleware:
    """Write one row per state-changing ``/api`` request.

    Plain ASGI rather than Starlette's ``BaseHTTPMiddleware``, for the same
    reason ``BodyLimit`` is: that wrapper changes how the request body is read
    and hides client disconnects from handlers. This middleware only *observes*
    -- it passes ``receive`` through a wrapper that copies the first few KiB as
    they go by (so a 48 MiB upload is never buffered) and watches the response
    start for the status code.

    Two rules keep it out of the way of the thing it measures:

    * it never raises into the request (a full disk must not break a settings
      save), and
    * it never blocks on the body: the copy is best-effort, and a request that
      the handler never reads simply yields no summary.
    """

    def __init__(self, app, *, store_getter, enabled: bool = True) -> None:
        self.app = app
        self._store = store_getter
        self.enabled = enabled

    @property
    def store(self):
        return self._store()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not self._is_audited(scope):
            await self.app(scope, receive, send)
            return

        started = time.monotonic()
        captured = bytearray()

        async def receive_spy():
            message = await receive()
            if message.get("type") == "http.request" and len(captured) < BODY_PREFIX_BYTES:
                body = message.get("body") or b""
                room = BODY_PREFIX_BYTES - len(captured)
                captured.extend(body[:room])
            return message

        status = {"code": 500}

        async def send_spy(message):
            if message.get("type") == "http.response.start":
                status["code"] = int(message.get("status", 500))
            await send(message)

        try:
            await self.app(scope, receive_spy, send_spy)
        finally:
            self._write(scope, status["code"], bytes(captured),
                        time.monotonic() - started)

    # -- what to audit ---------------------------------------------------
    @staticmethod
    def _is_audited(scope) -> bool:
        path = scope.get("path") or ""
        if not path.startswith("/api/"):
            # /v1/* is inference (see docs/inference-records.md); every other
            # path is the SPA or an agent's own UI.
            return False
        return (scope.get("method") or "").upper() in AUDITED_METHODS

    def _write(self, scope, status: int, body: bytes, duration: float) -> None:
        store = self.store
        if store is None or not getattr(store, "enabled", False):
            return
        try:
            headers = {k.lower(): v for k, v in scope.get("headers") or []}
            path = scope.get("path") or ""
            params = scope.get("path_params") or {}
            target = next((str(params[name]) for name in _TARGET_PARAMS
                           if params.get(name) is not None), None)
            client = scope.get("client") or (None, None)
            actor = resolve_actor(scope.get("app").state, headers,
                                  path=path, status=status)
            store.record({
                "ts": time.time(),
                "actor_type": actor.actor_type,
                "actor_id": actor.actor_id,
                "actor_name": actor.actor_name,
                # The socket peer, not X-Forwarded-For: a header a client can
                # set is not evidence of where the request came from, and an
                # audit trail that can be forged by its subject is worse than
                # one that says "loopback" behind a proxy.
                "ip": client[0] if client else None,
                "user_agent": headers.get(b"user-agent", b"").decode("latin-1"),
                "method": (scope.get("method") or "").upper(),
                "path": path,
                "target": target,
                "status": status,
                "duration_ms": duration * 1000.0,
                "summary": summarise(path, scope.get("method") or "", target,
                                     status, body),
            })
        except Exception:  # noqa: BLE001 - auditing must never fail a request
            logger.exception("could not write an audit record")
