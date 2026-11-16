"""The console's 「日志」 page and the operation audit, over HTTP (MYS-2674).

Five routes, all behind the admin cookie (the same authority the rest of the
console uses; an API key is accepted too, because a script that already holds one
should not need a second credential to read logs it helped produce):

    GET /api/logs/sources              what logs exist, how big, how recent
    GET /api/logs/{source}             one page of structured lines
    GET /api/logs/{source}/download    filtered text, or a zip with the rotations
    GET /api/audit                     one page of audit rows
    GET /api/audit/export              the audit as CSV

None of these writes an audit record of its own: the page polls, and a row per
poll would bury the changes the audit exists to show.
"""

from __future__ import annotations

import io
import logging
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..core import logs as logmod
from ..core.auth import require_admin
from ..core.logs import LOG_LINES_DEFAULT, LOG_LINES_MAX, BadCursor, UnknownSource

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# shared plumbing
# ---------------------------------------------------------------------------
def _registry(request: Request) -> logmod.LogRegistry:
    return request.app.state.logs


def _store(request: Request):
    return request.app.state.audit


def _source(request: Request, source: str) -> logmod.LogSource:
    """Look the id up in the registry; refuse anything else.

    This is the whole path-traversal defence: ``source`` never becomes part of a
    path. It is compared against ids the registry built from the filesystem, so a
    ``../``, an absolute path or a symlink name matches nothing and becomes a 404
    without a single ``open``.
    """
    try:
        return _registry(request).resolve(source)
    except UnknownSource as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _time_param(value: str | None, name: str) -> float | None:
    """``since``/``until`` as epoch seconds.

    Three accepted forms, all of which an operator or a console actually sends:
    an epoch number, an ISO8601 timestamp (naive means local time, the same rule
    the log lines themselves follow), and a relative window (``-30m``, ``-2h``,
    ``-7d``).
    """
    if not value:
        return None
    text = value.strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return float(text)
    relative = re.fullmatch(r"-(\d+)([smhd])", text)
    if relative:
        amount = int(relative.group(1))
        unit = {"s": 1, "m": 60, "h": 3600, "d": 86400}[relative.group(2)]
        return time.time() - amount * unit
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{name} 需要 epoch 秒、ISO8601 时间或相对时间（如 -30m）") from exc
    return parsed.timestamp()


def _since_until(since: str | None, until: str | None) -> tuple[float | None, float | None]:
    start = _time_param(since, "since")
    end = _time_param(until, "until")
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=400, detail="since 晚于 until")
    return start, end


def _level_param(level: str | None) -> str | None:
    if not level:
        return None
    if logmod.level_threshold(level) is None:
        raise HTTPException(
            status_code=400,
            detail="level 只能是 " + ", ".join(logmod.LEVEL_ORDER) + " 之一"
                   "（也接受 warn/err/fatal）")
    return level


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------
@router.get("/logs/sources")
async def list_sources(request: Request, _=Depends(require_admin)):
    """Every log the page may open.

    A source that has never been written still appears, with ``size_bytes: 0``:
    "the worker log is empty" is information (the model has not run since the
    service started), while a source silently missing from the picker looks like
    a bug in the page.
    """
    registry = _registry(request)
    cache = request.app.state.log_sizes
    out = []
    for source in registry.sources():
        item = cache.describe(source)
        item["kind"] = source.kind
        item["updated_at_iso"] = (
            datetime.fromtimestamp(item["updated_at"]).astimezone().isoformat(
                timespec="seconds") if item["updated_at"] else None)
        out.append(item)
    return {"sources": out}


# ---------------------------------------------------------------------------
# reading one source
# ---------------------------------------------------------------------------
@router.get("/logs/{source}")
async def read_log(
    source: str,
    request: Request,
    since: str | None = None,
    until: str | None = None,
    level: str | None = None,
    q: str | None = None,
    limit: int = Query(LOG_LINES_DEFAULT, ge=1, le=LOG_LINES_MAX),
    cursor: str | None = None,
    _=Depends(require_admin),
):
    """One page of a log.

    Without a ``cursor`` this is "the newest N matching lines", read backwards
    from the file's end -- the case the page opens with, and the one that must
    not read a 50 MiB log to answer. With a ``cursor`` it continues from where the
    previous page stopped, so the console prepends older lines without ever
    asking for the whole file.

    Lines come back oldest-first so the console can render top-to-bottom; the
    cursor names "the line just before the first one returned", which is also
    what makes paging stable while the file is being appended to.
    """
    src = _source(request, source)
    start, end = _since_until(since, until)
    try:
        lines, next_cursor, has_more = logmod.read_page(
            src, since=start, until=end, level=_level_param(level), q=q,
            limit=limit, cursor=cursor)
    except BadCursor as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    specs = _registry(request).agent_specs()
    out = [line.as_dict() for line in logmod.with_redaction(src, specs, lines)]
    out.reverse()
    return {
        "source": src.id,
        "label": src.label,
        "lines": out,
        "cursor": next_cursor,
        "has_more": has_more,
        "limit": limit,
        "size_bytes": src.size_bytes(),
    }


#: How many bytes of a name are safe in a Content-Disposition header. A model id
#: is user-supplied (it is a directory name), so it cannot be interpolated raw.
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _download_stem(source: logmod.LogSource) -> str:
    return _SAFE_NAME.sub("-", source.path.stem) or "log"


@router.get("/logs/{source}/download")
async def download_log(
    source: str,
    request: Request,
    since: str | None = None,
    until: str | None = None,
    level: str | None = None,
    q: str | None = None,
    _=Depends(require_admin),
):
    """The log as a file: filtered text, or every generation as one zip.

    No filter means "the whole history", which includes the rotations -- an
    operator who downloads ``platform.log`` wants the five backup generations
    too, or the file they get back is missing the incident they are chasing. That
    case is a zip because one log is six files. A filtered download is the
    matching lines alone and is served as plain text, which is what a text
    editor, ``grep`` and an attachment all expect.

    Everything streams: a 50 MiB log is never one in-memory string.
    """
    src = _source(request, source)
    start, end = _since_until(since, until)
    level = _level_param(level)
    specs = _registry(request).agent_specs()
    filtered = any(v is not None for v in (start, end, level, q))

    def text_body():
        for line in logmod.with_redaction(
                src, specs,
                logmod.filtered_lines(src, since=start, until=end, level=level, q=q)):
            if line.ts:
                yield f"{line.ts} {line.level or '-'} {line.logger or '-'}: {line.message}\n"
            else:
                yield line.message + "\n"

    name = _download_stem(src)
    if filtered:
        return StreamingResponse(
            text_body(), media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}.log"'})

    files = [path for path in [*src.rotated(), src.path] if path.is_file()]
    if not files or not any(path.stat().st_size for path in files):
        # Nothing has ever been written. An empty text file is a better answer
        # than a 404 (the source exists, it is simply empty) and better than a
        # zip holding one empty entry, which is what an operator would have to
        # open to find out nothing is there.
        return StreamingResponse(
            iter([b""]), media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}.log"'})

    def zip_body():
        stream = _ZipStream()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            # Oldest first, so the archive reads like the log it came from.
            for path in files:
                with archive.open(path.name, "w") as target:
                    for chunk in _chunks(path):
                        target.write(chunk)
                data = stream.take()
                if data:
                    yield data
        yield stream.take()

    return StreamingResponse(
        zip_body(), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})


def _chunks(path: Path, size: int = 256 * 1024):
    try:
        with open(path, "rb") as fh:
            while True:
                data = fh.read(size)
                if not data:
                    return
                yield data
    except OSError:  # pragma: no cover - a file that vanished mid-download
        return


class _ZipStream:
    """A write-only file object that hands its bytes back as they are produced.

    ``zipfile`` needs ``write`` and ``tell``; the missing ``seek`` is what makes
    it write the archive strictly forward (it records each entry's offset itself
    from the running position). Buffering here and draining between entries is
    what keeps a download's memory at one entry's data instead of the whole
    archive's.

    ``tell`` counts everything ever written, not the size of the current buffer:
    zipfile uses it as the offset in the archive, and resetting it on each drain
    would make every entry after the first point at the wrong bytes -- a zip that
    unzips to garbage rather than failing loudly.
    """

    def __init__(self) -> None:
        self._buffer = io.BytesIO()
        self._offset = 0

    def write(self, data) -> int:
        written = self._buffer.write(data)
        self._offset += written
        return written

    def tell(self) -> int:
        return self._offset

    def flush(self) -> None:
        return None

    def take(self) -> bytes:
        data = self._buffer.getvalue()
        self._buffer = io.BytesIO()
        return data


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------
def _audit_filters(since, until, actor, action, status, q) -> dict:
    start, end = _since_until(since, until)
    return {"since": start, "until": end, "actor": actor, "action": action,
            "status": status, "q": q}


@router.get("/audit")
async def list_audit(
    request: Request,
    since: str | None = None,
    until: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _=Depends(require_admin),
):
    """Operations, newest first. ``action`` is "METHOD /path/prefix"."""
    store = _store(request)
    filters = _audit_filters(since, until, actor, action, status, q)
    try:
        page = store.query(limit=limit, offset=offset, **filters)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    page["retention_days"] = store.retention_days
    # Non-zero means the trail has holes (a move, or a write that failed). The
    # console shows it; an audit page that reads "complete" while rows were
    # dropped would be worse than no page at all.
    page["dropped"] = store.dropped
    if store.last_error:
        page["last_error"] = store.last_error
    return page


@router.get("/audit/export")
async def export_audit(
    request: Request,
    since: str | None = None,
    until: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    status: str | None = None,
    q: str | None = None,
    _=Depends(require_admin),
):
    """The audit as CSV: UTF-8 with a BOM, so Excel opens it without mojibake."""
    store = _store(request)
    filters = _audit_filters(since, until, actor, action, status, q)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return StreamingResponse(
        store.csv_chunks(**filters), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="audit-{stamp}.csv"'})
