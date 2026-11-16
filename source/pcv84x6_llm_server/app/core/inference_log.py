"""Per-inference audit records: one row per real model call, on disk.

Why this exists (MYS-2496): the service kept only cumulative counters, so when a
customer's answer came out wrong there was nothing left to look at. ``state.json``
could say eight requests had been served; it could not say what any of them asked
or answered. Every real inference now writes one row here -- the request, the
parameters, the raw output, how it finished -- so a bad answer can be explained
after the fact instead of being reproduced on a board that is in use.

The rules this module is built around, because they are what make the records
useful rather than merely present:

* **Exactly one row per inference.** A stream, a plain completion and the
  console's own dialog each write one row on exactly one terminal path --
  success, worker error, backend death, or client hang-up. ``RecordContext``
  carries the flag; a second ``finish`` is a no-op, not a second row.
* **The raw text, not the parsed view.** ``output_text`` is what the model
  produced (thinking tags and ``<tool_call>`` blocks intact), cut at the stop
  string exactly as the API reply was, so the two never disagree. The fields the
  client actually saw (``response_content``/``reasoning_content``/
  ``tool_calls``) sit beside it.
* **No credentials, no image bytes.** An API key is identified by id and name --
  its hash never leaves the process that already has it. Pictures are reduced to
  their dimensions; the base64 that carried them is dropped before the row is
  built. Message *text* is stored verbatim: rewriting what the user typed in
  order to look for pictures would make the record lie about the request.
* **A broken log never breaks inference.** Every failure is caught, remembered
  and reported through ``status()``; it is never raised into a request.

Storage is a single SQLite file (WAL) under the data directory, so ``--storage
move`` carries it along with everything else and an operator can copy it off the
board. Structure and field semantics are documented in
``docs/inference-records.md``.
"""

from __future__ import annotations

import base64
import json
import logging
import sqlite3
import struct
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

logger = logging.getLogger(__name__)

# Bumped when the columns or their meaning change; ``meta.schema_version`` is
# what a future migration keys on. Rows are never silently reinterpreted.
SCHEMA_VERSION = 1

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"

DEFAULT_FILENAME = "inference_records.sqlite3"

# How a record dropped because the data directory is being moved reads to an
# operator. Kept next to the exception class so the console, the tests and the
# docs cannot drift apart on the wording.
MOVING_MESSAGE = ("数据目录正在迁移，记录库已暂停写入；此期间的推理记录不会保存"
                  "（迁移结束后自动恢复）")


class InferenceLogMoving(RuntimeError):
    """A record was dropped because the log is parked for a data-directory move.

    Not a fault in the database: the file is fine, it is simply about to be
    copied to another disk. It is reported through ``last_error`` because the
    alternative -- staying silent -- makes an incomplete audit trail look
    complete, which is the one thing this log exists to prevent.
    """


# Ranges the settings page and ``Settings.clamp`` share.
RETENTION_COUNT_MIN, RETENTION_COUNT_MAX = 1, 100_000
RETENTION_DAYS_MIN, RETENTION_DAYS_MAX = 1, 3650

# Export and list reads page through the table in chunks so a 100k-row export
# never materialises as one in-memory list.
EXPORT_CHUNK = 200

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inference_records (
    id                  TEXT PRIMARY KEY,   -- == request_id; one row per inference
    source              TEXT NOT NULL,      -- the endpoint path that was called
    model               TEXT,
    actor_type          TEXT,               -- api_key | admin | anonymous
    actor_id            TEXT,
    actor_name          TEXT,
    started_at          REAL NOT NULL,      -- epoch seconds (also the sort key)
    finished_at         REAL NOT NULL,
    started_iso         TEXT NOT NULL,
    finished_iso        TEXT NOT NULL,
    status              TEXT NOT NULL,      -- ok | error | cancelled
    finish_reason       TEXT,
    error_type          TEXT,
    error_message       TEXT,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    cached_tokens       INTEGER,
    first_token_latency_s REAL,
    decode_tps          REAL,
    params              TEXT,               -- effective sampling params, JSON
    tools               TEXT,               -- JSON, as sent
    tool_choice         TEXT,               -- JSON, as sent
    messages            TEXT,               -- JSON, full text per message
    images              TEXT,               -- JSON, ordered {count,width,height}
    message_images      TEXT,               -- JSON, per-message {index,width,height}
    output_text         TEXT,               -- raw generation, stop-truncated
    response_content    TEXT,               -- what the client saw as content
    reasoning_content   TEXT,
    tool_calls          TEXT,               -- JSON, as returned
    output_chars        INTEGER,
    raw_output_chars    INTEGER,
    stop_hit            TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_started
    ON inference_records (started_at DESC);
"""

# The columns a list row needs: everything except the heavy JSON/text blobs.
_SUMMARY_COLUMNS = (
    "id", "source", "model", "actor_type", "actor_id", "actor_name",
    "started_at", "finished_at", "started_iso", "finished_iso", "status",
    "finish_reason", "error_type", "error_message", "prompt_tokens",
    "completion_tokens", "cached_tokens", "first_token_latency_s", "decode_tps",
    "output_chars", "raw_output_chars", "stop_hit",
)
_SUMMARY_SQL = (
    "SELECT id, source, model, actor_type, actor_id, actor_name,"
    " started_at, finished_at, started_iso, finished_iso, status, finish_reason,"
    " error_type, error_message, prompt_tokens, completion_tokens, cached_tokens,"
    " first_token_latency_s, decode_tps, output_chars, raw_output_chars, stop_hit"
    " FROM inference_records"
)

_JSON_COLUMNS = ("params", "tools", "tool_choice", "messages", "images",
                 "message_images", "tool_calls")

_INSERT_SQL = """
INSERT OR REPLACE INTO inference_records (
    id, source, model, actor_type, actor_id, actor_name,
    started_at, finished_at, started_iso, finished_iso, status, finish_reason,
    error_type, error_message, prompt_tokens, completion_tokens, cached_tokens,
    first_token_latency_s, decode_tps, params, tools, tool_choice, messages,
    images, message_images, output_text, response_content, reasoning_content,
    tool_calls, output_chars, raw_output_chars, stop_hit
) VALUES (
    :id, :source, :model, :actor_type, :actor_id, :actor_name,
    :started_at, :finished_at, :started_iso, :finished_iso, :status,
    :finish_reason, :error_type, :error_message, :prompt_tokens,
    :completion_tokens, :cached_tokens, :first_token_latency_s, :decode_tps,
    :params, :tools, :tool_choice, :messages, :images, :message_images,
    :output_text, :response_content, :reasoning_content, :tool_calls,
    :output_chars, :raw_output_chars, :stop_hit
)
"""


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------
def utc_iso(epoch: float) -> str:
    """UTC ISO8601 with milliseconds and a ``Z``, the form an operator can paste
    into ``journalctl --since`` beside the access log."""
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Images: dimensions only, never the bytes
# ---------------------------------------------------------------------------
def _png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    if data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def _gif_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 10 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    width, height = struct.unpack("<HH", data[6:10])
    return int(width), int(height)


# JPEG start-of-frame markers carry the dimensions. C4 (DHT), C8 (JPG) and CC
# (DAC) sit in the same numeric range but are not frames.
_JPEG_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
             0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or not data.startswith(b"\xff\xd8"):
        return None
    i = 2
    n = len(data)
    while i + 3 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8,) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            i += 2
            continue
        if marker in (0xD9, 0xDA):  # end of image / start of scan: no frame yet
            return None
        if i + 4 > n:
            return None
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in _JPEG_SOF:
            if i + 9 > n:
                return None
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            return int(width), int(height)
        i += 2 + length
    return None


def image_size(raw: str | bytes) -> tuple[int | None, int | None]:
    """(width, height) of a base64 image, or (None, None) when unreadable.

    Deliberately standard-library only: the board ships no Pillow, and this runs
    on the management plane. An unknown format is not an error -- the picture is
    still counted, it just has no dimensions.
    """
    try:
        data = raw if isinstance(raw, bytes) else base64.b64decode(raw, validate=False)
    except (ValueError, TypeError):
        return None, None
    for reader in (_png_size, _jpeg_size, _gif_size):
        try:
            got = reader(data)
        except struct.error:
            got = None
        if got is not None:
            return got
    return None, None


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
def _part_field(part: Any, name: str) -> Any:
    """Read a content-part field from either a pydantic model or a plain dict."""
    if isinstance(part, dict):
        return part.get(name)
    return getattr(part, name, None)


def _message_field(message: Any, name: str) -> Any:
    if isinstance(message, dict):
        return message.get(name)
    return getattr(message, name, None)


def _image_meta(raw_b64: str, index: int) -> dict:
    """One picture's identity in the record: where it was and how big it is.

    ``type`` is carried so a message's content list can be read as a normal
    OpenAI parts list -- the image part simply has no bytes and no URL.
    """
    width, height = image_size(raw_b64)
    return {"type": "image", "index": index, "width": width, "height": height}


def describe_messages(
    messages: Sequence[Any],
    extra_images: Sequence[str] | None = None,
) -> dict:
    """The recordable form of a request's messages: full text, no image bytes.

    Returns ``{"messages": [...], "images": [...], "message_images": [...]}``:

    * ``messages`` keeps each turn's role, text, tool calls and reasoning; an
      image part is replaced in place by ``{"type": "image", index, width,
      height}`` so the position of the picture inside the turn survives.
    * ``images`` is the ordered summary ``[{count, width, height}]`` (consecutive
      pictures of the same size grouped) for a quick "how big was this input".
    * ``message_images`` is per message, so a size can be matched back to the
      turn it came from rather than only to a global total.

    ``extra_images`` are base64 pictures the caller carries outside the message
    list (the console's ``images`` field, rendered before the prompt text); they
    attach to the last message and are recorded in the same order they appear in
    the prompt.
    """
    from ..api.tool_calls import flatten_content

    recorded: list[dict] = []
    groups: list[dict] = []
    per_message: list[list[dict]] = []
    # Image indices are global across the request: "the second picture" must
    # mean the same thing in `images`, `message_images` and a message's own
    # content list, or the three cannot be cross-referenced.
    counter = {"next": 0}

    def image_metas(images: Sequence[str]) -> list[dict]:
        metas = []
        for raw in images:
            metas.append(_image_meta(raw, counter["next"]))
            counter["next"] += 1
        return metas

    def add_sizes(metas: list[dict]) -> None:
        for meta in metas:
            if (groups and groups[-1]["width"] == meta["width"]
                    and groups[-1]["height"] == meta["height"]):
                groups[-1]["count"] += 1
            else:
                groups.append({"count": 1, "width": meta["width"],
                               "height": meta["height"]})

    for pos, message in enumerate(messages):
        role = _message_field(message, "role")
        content = _message_field(message, "content")
        # flatten_content is the same reader the prompt renderer used, so the
        # images counted here are exactly the ones that reached the model.
        _, images = flatten_content(content)
        own = image_metas(images)

        is_last = pos == len(messages) - 1
        extra = image_metas(extra_images) if (extra_images and is_last) else []
        # The console hands its pictures separately and the template renders them
        # before the text, so they come first in the request's order too.
        metas = extra + own

        if metas:
            parts: list[dict] = list(metas)
            if isinstance(content, str):
                if content:
                    parts.append({"type": "text", "text": content})
                recorded_content: Any = parts
            else:
                recorded_content = [dict(m) for m in extra]
                seen = 0
                for part in content or []:
                    ptype = _part_field(part, "type")
                    if ptype == "text":
                        recorded_content.append(
                            {"type": "text", "text": _part_field(part, "text")})
                    elif ptype == "image_url":
                        recorded_content.append(dict(own[seen]))
                        seen += 1
                    else:  # pragma: no cover - flatten_content already refused it
                        recorded_content.append({"type": str(ptype)})
        else:
            recorded_content = content if isinstance(content, str) or content is None \
                else [_record_part(p) for p in content]

        entry: dict[str, Any] = {"role": role, "content": recorded_content}
        for key in ("name", "tool_call_id", "reasoning_content"):
            value = _message_field(message, key)
            if value is not None:
                entry[key] = value
        tool_calls = _message_field(message, "tool_calls")
        if tool_calls:
            entry["tool_calls"] = tool_calls
        recorded.append(entry)
        per_message.append(metas)
        add_sizes(metas)

    return {"messages": recorded, "images": groups, "message_images": per_message}


def _record_part(part: Any) -> dict:
    ptype = _part_field(part, "type")
    if ptype == "text":
        return {"type": "text", "text": _part_field(part, "text")}
    return {"type": str(ptype)}


def actor_from_key_id(store: Any, key_id: str | None) -> dict:
    """Who made the call, without ever touching the key material.

    ``api_key`` records the key's id and name so an operator can tell two
    clients apart; the raw key and its hash stay in ``state.json``. The console
    has no key at all, so it records ``admin``. Cookies and session tokens are
    never part of a record.
    """
    if not key_id:
        return {"actor_type": "admin", "actor_id": None, "actor_name": "admin"}
    key = next((k for k in getattr(store, "keys", []) if k.id == key_id), None)
    if key is None:
        return {"actor_type": "api_key", "actor_id": key_id, "actor_name": None}
    return {"actor_type": "api_key", "actor_id": key.id, "actor_name": key.name}


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------
class InferenceLogStore:
    """One SQLite file holding every inference record.

    Thread-safe by one lock around a single connection created with
    ``check_same_thread=False``: the request handlers (event loop), the move
    job's worker thread and the export's writer all go through it. Writes are
    ``BEGIN IMMEDIATE`` so the read-modify-write of the retention delete cannot
    interleave with another writer, and readers only ever take a shared lock, so
    a list request during a write waits rather than failing with "database is
    locked".

    The store is deliberately not allowed to raise into a request: ``record``
    reports failure through ``status()`` instead.
    """

    def __init__(self, path: str | Path, *, retention_count: int = 1000,
                 retention_days: int = 30, enabled: bool = True,
                 resume_when: Callable[[], bool] | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.enabled = bool(enabled)
        self.retention_count = _clamp(retention_count, RETENTION_COUNT_MIN,
                                      RETENTION_COUNT_MAX)
        self.retention_days = _clamp(retention_days, RETENTION_DAYS_MIN,
                                     RETENTION_DAYS_MAX)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        # True between close() and the next open: set while a data-directory
        # move copies the file, so a request that finishes late cannot write
        # into the tree that is being copied (and then deleted).
        self._closed = False
        # Asked before re-opening a parked log: "is whatever parked me finished?".
        # A move that fails before its switch never reaches rebind, and without
        # this the log would stay silent for the rest of the process's life.
        self._resume_when = resume_when
        # Last write failure, surfaced by status() so the admin page can say why
        # an empty list may be a broken log rather than an idle service.
        self.last_error: str | None = None
        self.last_error_at: float | None = None
        self._open()

    # -- lifecycle -------------------------------------------------------
    def _open(self) -> None:
        """(Re)open the file. Never raises.

        A database that cannot be opened -- corrupt bytes, a lost directory, a
        full disk -- must leave the service serving and the failure visible in
        ``status()``, not take a request down with it. ``last_error`` is how the
        console tells "no records yet" from "records are being lost".
        """
        with self._lock:
            if self._conn is not None:
                return
            self._closed = False
            try:
                conn = sqlite3.connect(str(self.path), check_same_thread=False,
                                       timeout=10.0, isolation_level=None)
                conn.row_factory = sqlite3.Row
                # WAL: a reader (the console listing records) never blocks the
                # writer that is finishing a request. NORMAL sync is the usual
                # WAL trade: a crash can lose the last transaction or two of
                # audit trail, but the database itself stays consistent, and
                # fsyncing every token would slow the NPU path down for records
                # nobody has asked for yet.
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA busy_timeout=10000")
                conn.executescript(_SCHEMA)
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
            except (sqlite3.Error, OSError) as exc:
                self._note_error(exc)
                try:
                    conn.close()
                except (sqlite3.Error, UnboundLocalError):  # pragma: no cover
                    pass
                return
            self._conn = conn

    def _note_error(self, exc: BaseException) -> None:
        message = f"{type(exc).__name__}: {exc}"
        with self._lock:
            if message != self.last_error:
                # Once per distinct message: a log that has become unwritable
                # must not fill the journal with one warning per record.
                logger.warning("an inference record could not be stored: %s", message)
            self.last_error = message
            self.last_error_at = time.time()

    def _clear_moving_notice(self) -> None:
        """Drop the "parked for a move" notice once the log is live again.

        Only that one: a genuine database error recorded before the move is
        worth keeping until a write actually succeeds, which is what clears it.
        """
        prefix = type(InferenceLogMoving(MOVING_MESSAGE)).__name__
        with self._lock:
            if (self.last_error or "").startswith(prefix):
                self.last_error = None
                self.last_error_at = None

    def close(self) -> None:
        """Release the file so it can be moved or copied without a live writer.

        Called by ``stop_everything`` *before* the models are unloaded, so the
        data-directory move copies a database nobody is writing to. Until
        ``reopen``/``rebind`` puts it back, writes are dropped rather than
        re-opening the old path behind the move's back.
        """
        with self._lock:
            self._closed = True
            conn, self._conn = self._conn, None
            if conn is None:
                return
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:  # pragma: no cover - best effort on shutdown
                pass
            try:
                conn.close()
            except sqlite3.Error:  # pragma: no cover
                pass

    def reopen(self) -> None:
        """Open again after ``close`` (the store survives a move in place)."""
        with self._lock:
            self._closed = False
            self._open()
        if self._conn is not None:
            # The log is live again, so the "records are being dropped while the
            # data directory moves" notice no longer describes the world.
            self._clear_moving_notice()

    def _resume(self) -> None:
        """Reopen a parked log only if nobody else already did.

        Called from ``record`` when ``resume_when`` says the move is over. The
        lock matters: two requests finishing at the same moment must not each
        open a connection and leave one of them orphaned.
        """
        with self._lock:
            if not self._closed or self._conn is not None:
                return
            self._closed = False
            self._open()
        if self._conn is not None:
            # A failed move left the old directory live: the "parked" notice is
            # stale the moment the next record is accepted.
            self._clear_moving_notice()

    def rebind(self, path: str | Path) -> None:
        """Point at another file, e.g. after the data directory moved."""
        new_path = Path(path)
        with self._lock:
            self.close()
            self.path = new_path
        self.reopen()

    def configure(self, *, enabled: bool | None = None,
                  retention_count: int | None = None,
                  retention_days: int | None = None) -> None:
        """Apply new settings; a save takes effect on the next request."""
        with self._lock:
            if enabled is not None:
                self.enabled = bool(enabled)
            if retention_count is not None:
                self.retention_count = _clamp(retention_count, RETENTION_COUNT_MIN,
                                              RETENTION_COUNT_MAX)
            if retention_days is not None:
                self.retention_days = _clamp(retention_days, RETENTION_DAYS_MIN,
                                             RETENTION_DAYS_MAX)

    # -- writing ---------------------------------------------------------
    def record(self, entry: dict) -> bool:
        """Insert one record and apply retention. Never raises.

        Returns True when the row was stored. A failure leaves the previous
        ``last_error`` in place for the admin page and is logged once per
        distinct message: a database that has become unwritable must not fill
        the journal with one traceback per token.
        """
        if not self.enabled:
            return False
        if self._closed:
            # Parked for a data-directory move. Re-opening ``self.path`` here
            # would write into the tree the move is copying or deleting -- unless
            # the move is over (it failed before its switch), in which case the
            # file is live again and staying silent would lose records for good.
            if self._resume_when is None or self._resume_when():
                self._resume()
            if self._closed:
                # A record really was dropped here. Saying nothing would leave
                # the console showing "0 条，一切正常" while the audit trail has a
                # hole in it, so this is reported exactly like a write failure --
                # with its own type, so "the log is parked" is not mistaken for
                # "the database is broken".
                self._note_error(InferenceLogMoving(MOVING_MESSAGE))
                return False
        row = _row_for(entry)
        try:
            with self._lock:
                conn = self._conn_or_open()
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.execute(_INSERT_SQL, row)
                    self._prune(conn, row["started_at"])
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                # Only a successful write proves the log is healthy again, so
                # the previous notice (including "parked for a move") goes here
                # rather than on reopen alone.
                self.last_error = None
                self.last_error_at = None
            return True
        except Exception as exc:  # noqa: BLE001 - the log must never fail a request
            self._note_error(exc)
            # A connection that failed mid-transaction can be left unusable;
            # dropping it means the next request tries a fresh one instead of
            # inheriting the breakage.
            self._discard_connection()
            return False

    def _prune(self, conn: sqlite3.Connection, now: float) -> None:
        """Count and date retention, in the same transaction as the insert.

        Both rules apply, so "the newest 1000" can still be trimmed to "the last
        30 days": whichever keeps fewer rows wins, which is what an operator
        setting both expects.
        """
        if self.retention_count > 0:
            conn.execute(
                "DELETE FROM inference_records WHERE id NOT IN ("
                " SELECT id FROM inference_records"
                " ORDER BY started_at DESC, id DESC LIMIT ?)",
                (self.retention_count,),
            )
        if self.retention_days > 0:
            cutoff = now - self.retention_days * 86400
            conn.execute("DELETE FROM inference_records WHERE started_at < ?",
                         (cutoff,))

    def _conn_or_open(self) -> sqlite3.Connection:
        if self._conn is None:
            if self._closed:
                # Parked for a data-directory move: the file may be half copied
                # by now, so neither reading nor writing it would tell the truth.
                raise RuntimeError("推理记录库正在随数据目录迁移，请稍后重试")
            self._open()
        if self._conn is None:
            # ``_open`` refused: a corrupt file or an unwritable directory. Raise
            # the reason so callers report it instead of misreading "no rows".
            raise RuntimeError(self.last_error or "推理记录库无法打开")
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
    def count(self) -> int:
        with self._lock:
            conn = self._conn_or_open()
            return int(conn.execute(
                "SELECT COUNT(*) FROM inference_records").fetchone()[0])

    def list(self, limit: int = 100, offset: int = 0,
             before: float | None = None) -> dict:
        """A page of records, newest first, without the heavy text blobs.

        ``before`` is an exclusive epoch upper bound, which is what the console
        needs to page backwards through history without the offsets shifting
        under a live write.
        """
        limit = _clamp(limit, 1, 200)
        offset = max(0, int(offset))
        where, args = "", []
        if before is not None:
            where = " WHERE started_at < ?"
            args.append(float(before))
        with self._lock:
            conn = self._conn_or_open()
            total = int(conn.execute(
                "SELECT COUNT(*) FROM inference_records" + where, args).fetchone()[0])
            rows = conn.execute(
                _SUMMARY_SQL + where +
                " ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
        return {
            "items": [_summary(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def get(self, record_id: str) -> dict | None:
        with self._lock:
            conn = self._conn_or_open()
            row = conn.execute(
                "SELECT * FROM inference_records WHERE id = ?", (record_id,)
            ).fetchone()
        return _detail(row) if row is not None else None

    def iter_all(self, chunk: int = EXPORT_CHUNK) -> Iterator[dict]:
        """Every record, newest first, one page at a time.

        Streamed rather than returned as a list: the export route pipes this
        straight into the response, so a 100k-record export must not be built as
        one in-memory array.
        """
        offset = 0
        while True:
            with self._lock:
                conn = self._conn_or_open()
                rows = conn.execute(
                    "SELECT * FROM inference_records"
                    " ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?",
                    (chunk, offset),
                ).fetchall()
            if not rows:
                return
            for row in rows:
                yield _detail(row)
            if len(rows) < chunk:
                return
            offset += chunk

    def export_lines(self, chunk: int = EXPORT_CHUNK) -> Iterator[str]:
        """NDJSON, one complete record per line, UTF-8, newest first."""
        for record in self.iter_all(chunk=chunk):
            yield json.dumps(record, ensure_ascii=False) + "\n"

    def clear(self) -> int:
        """Delete every record and shrink the file. Returns how many went."""
        with self._lock:
            conn = self._conn_or_open()
            conn.execute("BEGIN IMMEDIATE")
            try:
                removed = int(conn.execute(
                    "SELECT COUNT(*) FROM inference_records").fetchone()[0])
                conn.execute("DELETE FROM inference_records")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            # VACUUM cannot run inside a transaction; it is what actually gives
            # the pages back to the filesystem -- DELETE only marks them free.
            try:
                conn.execute("VACUUM")
            except sqlite3.Error as exc:  # pragma: no cover - disk full, etc.
                logger.warning("VACUUM after clearing inference records failed: %s", exc)
            return removed

    # -- diagnostics -----------------------------------------------------
    def status(self) -> dict:
        """What the admin page reports about the log itself.

        ``readable`` is False when the database cannot be opened at all (a
        corrupt file, a full disk); ``last_error`` carries the reason a write
        failed most recently, including a record dropped while the data
        directory was being moved. ``moving`` tells the two apart: a parked log
        is doing what it was designed to do, a broken one is losing evidence.
        The service keeps serving either way.
        """
        with self._lock:
            moving = self._closed and self._conn is None
            last_error, last_error_at = self.last_error, self.last_error_at
        out = {
            "path": str(self.path),
            "enabled": self.enabled,
            "total": 0,
            "bytes": None,
            "schema_version": SCHEMA_VERSION,
            "retention_count": self.retention_count,
            "retention_days": self.retention_days,
            "readable": True,
            "moving": moving,
            "last_error": last_error,
            "last_error_at": last_error_at,
        }
        try:
            # While the file is parked for a move, count it through a read-only
            # connection: the copier only reads, so this is safe, and it keeps
            # the page from painting a healthy-but-paused log as broken. A read
            # that fails mid-copy leaves `total` unknown (0) without flipping
            # `readable` -- `moving` already explains the pause, and calling a
            # database the operator is not allowed to touch right now "unreadable"
            # would send them looking for a corruption that is not there.
            out["total"] = self._count_readonly() if moving else self.count()
            for suffix in ("", "-wal", "-shm"):
                candidate = self.path.with_name(self.path.name + suffix) \
                    if suffix else self.path
                try:
                    out["bytes"] = (out["bytes"] or 0) + candidate.stat().st_size
                except OSError:
                    pass
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            out["readable"] = False
            out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    def _count_readonly(self) -> int:
        """Row count without touching the store's (closed) connection."""
        try:
            conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True,
                                   check_same_thread=False, timeout=5.0)
        except sqlite3.Error:  # pragma: no cover - nothing to read
            return 0
        try:
            return int(conn.execute(
                "SELECT COUNT(*) FROM inference_records").fetchone()[0])
        except sqlite3.Error:
            # Mid-copy, or no file yet: the count is simply not knowable.
            return 0
        finally:
            conn.close()


def _clamp(value: Any, low: int, high: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return low
    return max(low, min(high, n))


def _row_for(entry: dict) -> dict:
    """Flatten a ``RecordContext``-built entry into SQLite's scalar columns."""
    params = entry.get("params")
    tools = entry.get("tools")
    tool_choice = entry.get("tool_choice")
    row = {
        "id": entry["id"],
        "source": entry.get("source") or "",
        "model": entry.get("model"),
        "actor_type": entry.get("actor_type"),
        "actor_id": entry.get("actor_id"),
        "actor_name": entry.get("actor_name"),
        "started_at": float(entry.get("started_at") or 0.0),
        "finished_at": float(entry.get("finished_at") or 0.0),
        "status": entry.get("status") or STATUS_OK,
        "finish_reason": entry.get("finish_reason"),
        "error_type": entry.get("error_type"),
        "error_message": entry.get("error_message"),
        "prompt_tokens": entry.get("prompt_tokens"),
        "completion_tokens": entry.get("completion_tokens"),
        "cached_tokens": entry.get("cached_tokens"),
        "first_token_latency_s": entry.get("first_token_latency_s"),
        "decode_tps": entry.get("decode_tps"),
        "output_text": entry.get("output_text"),
        "response_content": entry.get("response_content"),
        "reasoning_content": entry.get("reasoning_content"),
        "output_chars": entry.get("output_chars"),
        "raw_output_chars": entry.get("raw_output_chars"),
        "stop_hit": entry.get("stop_hit"),
    }
    row["started_iso"] = entry.get("started_iso") or utc_iso(row["started_at"])
    row["finished_iso"] = entry.get("finished_iso") or utc_iso(row["finished_at"])
    row["params"] = _dump(params)
    row["tools"] = _dump(tools)
    row["tool_choice"] = _dump(tool_choice)
    row["messages"] = _dump(entry.get("messages"))
    row["images"] = _dump(entry.get("images"))
    row["message_images"] = _dump(entry.get("message_images"))
    row["tool_calls"] = _dump(entry.get("tool_calls"))
    return row


def _dump(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps(str(value), ensure_ascii=False)


def _load(value: Any) -> Any:
    if value is None or value == "":
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _summary(row: sqlite3.Row) -> dict:
    return {name: row[name] for name in _SUMMARY_COLUMNS if name in row.keys()}


def _detail(row: sqlite3.Row) -> dict:
    record = {k: row[k] for k in row.keys() if k not in _JSON_COLUMNS}
    for name in _JSON_COLUMNS:
        if name in row.keys():
            record[name] = _load(row[name])
    # The list and the detail page agree on the shape of `error`.
    record["error"] = (
        {"type": record.get("error_type"), "message": record.get("error_message")}
        if record.get("error_type") or record.get("error_message") else None
    )
    return record


# ---------------------------------------------------------------------------
# The per-request context
# ---------------------------------------------------------------------------
@dataclass
class RecordContext:
    """Everything one inference will be judged by, assembled as it runs.

    Created only once the request is known to be a real inference -- model
    resolved and prompt rendered -- so a 400 from validation or a 404 from an
    unknown model never produces a record: nothing ran on the NPU, and a row per
    rejected request would bury the ones that did run.

    ``finish`` is idempotent. Streaming paths and cancellation both reach it
    from more than one place in the control flow; the second call must not add a
    second row (that would make "exactly one record per inference" false exactly
    when an operator is looking at a broken stream).
    """

    store: InferenceLogStore
    req_id: str
    source: str
    model: str | None = None
    actor_type: str | None = None
    actor_id: str | None = None
    actor_name: str | None = None
    started_at: float = field(default_factory=time.time)
    params: dict | None = None
    tools: list | None = None
    tool_choice: Any = None
    messages: list | None = None
    images: list | None = None
    message_images: list | None = None
    # The prompt the model was actually given. Kept for the raw/final diff but
    # not stored: it is a render of `messages`, which is already recorded.
    prompt: str | None = None
    finished: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # -- finish ----------------------------------------------------------
    def finish(
        self,
        *,
        status: str = STATUS_OK,
        finish_reason: str | None = None,
        output_text: str | None = None,
        raw_output: str | None = None,
        response_content: str | None = None,
        reasoning_content: str | None = None,
        tool_calls: list | None = None,
        error: BaseException | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        cached_tokens: int | None = None,
        first_token_latency_s: float | None = None,
        decode_tps: float | None = None,
        stop_hit: str | None = None,
        finished_at: float | None = None,
    ) -> bool:
        """Write the one row for this inference. Returns True when stored.

        ``output_text`` is the text as the API's semantics define it (stop string
        already removed); ``raw_output`` is what the model emitted before that
        cut. Both are kept so a truncation can be told apart from a model that
        simply stopped -- without them the two look identical in the record.
        """
        with self._lock:
            if self.finished:
                return False
            self.finished = True
        now = finished_at if finished_at is not None else time.time()
        if error is not None and not error_type:
            error_type, error_message = classify_error(error)
        entry = {
            "id": self.req_id,
            "source": self.source,
            "model": self.model,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "actor_name": self.actor_name,
            "started_at": self.started_at,
            "finished_at": now,
            "started_iso": utc_iso(self.started_at),
            "finished_iso": utc_iso(now),
            "status": status,
            "finish_reason": finish_reason,
            "error_type": error_type,
            "error_message": error_message,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cached_tokens": cached_tokens,
            "first_token_latency_s": first_token_latency_s,
            "decode_tps": decode_tps,
            "params": self.params,
            "tools": self.tools,
            "tool_choice": self.tool_choice,
            "messages": self.messages,
            "images": self.images,
            "message_images": self.message_images,
            "output_text": output_text,
            "response_content": response_content,
            "reasoning_content": reasoning_content,
            "tool_calls": tool_calls,
            "output_chars": len(output_text) if output_text is not None else None,
            "raw_output_chars": len(raw_output) if raw_output is not None else None,
            "stop_hit": stop_hit,
        }
        return self.store.record(entry)


def classify_error(exc: BaseException) -> tuple[str, str]:
    """(type, message) for a failure, specific enough to debug from.

    A record saying only "error" would be worth nothing six weeks later; the
    worker's own kind (``invalid_request``, ``busy``, ``server``) and the
    exception class are what an operator needs to tell "the prompt was too long"
    from "the model process died".
    """
    from .client import WorkerError

    if isinstance(exc, WorkerError):
        kind = getattr(exc, "kind", "server") or "server"
        return f"WorkerError:{kind}", str(exc)
    if isinstance(exc, TimeoutError):
        return "TimeoutError", str(exc) or "timed out"
    return type(exc).__name__, str(exc) or type(exc).__name__


def cancellation_error(where: str) -> tuple[str, str]:
    """The error pair a client hang-up records.

    Named for the reason rather than the exception: ``CancelledError`` and
    ``GeneratorExit`` both mean "the client is gone", and the operator wants to
    know that, not which of the two asyncio raised.
    """
    return "ClientDisconnected", f"client disconnected during {where}"


def build_context(
    store: InferenceLogStore | None,
    *,
    req_id: str,
    source: str,
    model: str | None,
    actor: dict | None = None,
    params: dict | None = None,
    tools: Sequence[dict] | None = None,
    tool_choice: Any = None,
    messages: Sequence[Any] | None = None,
    extra_images: Sequence[str] | None = None,
    prompt: str | None = None,
) -> RecordContext | None:
    """Create a request's record context, or None when logging is off.

    The enabled check happens here, once, at the moment the inference begins:
    turning the switch off mid-request still drops that row (``record`` re-checks)
    but an operator who has it off pays nothing for the message walk below,
    which for a 128k-token agent conversation is real work.
    """
    if store is None or not store.enabled:
        return None
    try:
        described = describe_messages(messages or [], extra_images=extra_images)
    except Exception:  # noqa: BLE001 - building a record must never fail a request
        # The prompt already rendered, so this should not happen; if a message
        # shape ever slips through, keep the request and record what is left
        # rather than turning a served answer into a 500.
        logger.exception("could not describe the request messages for the record")
        described = {"messages": None, "images": None, "message_images": None}
    actor = actor or {}
    return RecordContext(
        store=store,
        req_id=req_id,
        source=source,
        model=model,
        actor_type=actor.get("actor_type"),
        actor_id=actor.get("actor_id"),
        actor_name=actor.get("actor_name"),
        params=params,
        tools=list(tools) if tools else None,
        tool_choice=tool_choice,
        messages=described["messages"],
        images=described["images"],
        message_images=described["message_images"],
        prompt=prompt,
    )
