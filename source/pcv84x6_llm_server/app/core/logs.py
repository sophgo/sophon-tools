"""The three log sources behind the console's 「日志」 page (MYS-2674).

Three different things are called "a log" here, and the only reason this module
exists is that the console must be able to list, filter and download all three
through one shape:

* **platform** -- this service's own records, at ``state/logs/platform.log``. A
  rotating file *and* stderr: systemd's journal keeps collecting what it always
  did, and the console gets a file it can page through without shell access.
* **worker** -- one file per model, ``state/logs/worker-<model_id>.log``, written
  by the model's child process. Read where it already is; nothing moves.
* **agent** -- ``<data root>/agents/<id>/logs/agent.log``, written by an agent's
  own process. Also read where it is.

Two properties decide most of the code below, because getting either wrong
makes the page useless on a board that has been up for weeks:

* **A log is read from the disk, not held in memory.** A 50 MiB log must not be
  materialised to answer "the last 200 lines" -- that is what ``tail_lines``
  does, reading backwards in bounded blocks. Downloads stream from the file.
* **A line that does not parse is still a line.** A worker prints a traceback,
  or a native library prints ``bm_alloc_gmem failed`` with no timestamp at all;
  dropping those would hide exactly the output an operator came for. They come
  back with ``level: null`` and the raw text in ``message``.

Security boundary, spelled out because a route that takes a path is a path
traversal waiting to happen: a *source id* is the only user input that reaches
the filesystem, it is looked up in a registry built from the filesystem itself
(``sources()``), and an id that is not there is refused before any path is
built. ``resolve_source`` is the only function that turns an id into a path.
"""

from __future__ import annotations

import base64
import json
import logging
import logging.handlers
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Iterator

logger = logging.getLogger(__name__)

#: The platform log's filename under ``<data dir>/logs``.
PLATFORM_LOG_NAME = "platform.log"
#: Rotation for the platform log, and for a worker's: 10 MiB is a fortnight of a
#: quiet board and about a day of a busy one, which is the window an operator
#: actually scrolls through. The backups are what makes a download carry history
#: past the last rotation.
PLATFORM_LOG_MAX_BYTES = 10 * 1024 * 1024
PLATFORM_LOG_BACKUPS = 5
WORKER_LOG_MAX_BYTES = 10 * 1024 * 1024
WORKER_LOG_BACKUPS = 3

#: One rotated generation of a log: ``platform.log`` -> ``platform.log.1``.
_ROTATED_SUFFIX = re.compile(r"^\.(\d+)$")

#: ``2026-11-07 10:27:46,123 INFO cv84x6: message``. The format
#: ``install_platform_log`` installs, parsed back here. The date is local time
#: (an operator compares it with ``journalctl``, which is also local), which is
#: why ``since``/``until`` filters are applied to the parsed local timestamp.
_LOG_LINE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[ T]"
    r"(?P<time>\d{2}:\d{2}:\d{2})(?:[.,](?P<frac>\d{1,6}))?\s+"
    r"(?P<level>[A-Z]+)\s+"
    r"(?P<logger>[^\s:]+):\s?"
    r"(?P<message>.*)$"
)
_ISO_LINE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T"
    r"(?P<time>\d{2}:\d{2}:\d{2})(?:[.,](?P<frac>\d{1,6}))?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?\s+"
    r"(?P<level>[A-Z]+)\s+"
    r"(?P<logger>[^\s:]+):\s?"
    r"(?P<message>.*)$"
)

#: Levels the API accepts for ``level=``, mapped to what a line may say. A
#: filter names a threshold ("warning and above") rather than one exact word,
#: because that is the question an operator has ("什么出错了").
LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
#: Aliases an operator or a client library may send.
_LEVEL_ALIASES = {
    "WARN": "WARNING", "ERR": "ERROR", "FATAL": "CRITICAL", "CRIT": "CRITICAL",
    "NOTSET": "DEBUG", "TRACE": "DEBUG",
}

# Bounds on one read. ``LOG_LINES_MAX`` is what "the newest N lines" may ask
# for; the console's page size sits far below it, and a caller that wants
# everything downloads the file instead.
LOG_LINES_MAX = 5000
LOG_LINES_DEFAULT = 200
#: Bytes read per step when scanning backwards. Big enough that a normal line
#: is read once, small enough that a 50 MiB file costs a few hundred reads.
_TAIL_BLOCK = 64 * 1024
#: A single line is never longer than this when reading *forwards*; a log of
#: one enormous line (a stack trace without newlines) must not be loaded whole.
MAX_LINE_BYTES = 1024 * 1024


# ---------------------------------------------------------------------------
# source identity
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LogSource:
    """One readable log: what the API calls it, and where it really is."""

    id: str
    label: str
    path: Path
    kind: str          # "platform" | "worker" | "agent"
    #: Which agent spec this belongs to, for a log that must be redacted on its
    #: way out (DSH prints a launch token). None for the other kinds.
    agent_id: str | None = None

    def rotated(self) -> list[Path]:
        """This log's older generations, oldest first.

        ``platform.log.3`` is older than ``platform.log.1`` (logging.handlers
        renames ``.1`` to ``.2`` on each roll), so a download that concatenates
        them in this order reads as one continuous log.
        """
        out: list[tuple[int, Path]] = []
        parent, name = self.path.parent, self.path.name
        try:
            entries = list(parent.iterdir())
        except OSError:
            return []
        for entry in entries:
            if not entry.name.startswith(name):
                continue
            match = _ROTATED_SUFFIX.match(entry.name[len(name):])
            if match and entry.is_file():
                out.append((int(match.group(1)), entry))
        out.sort(key=lambda item: -item[0])
        return [path for _, path in out]

    def size_bytes(self) -> int:
        total = 0
        for path in [self.path, *self.rotated()]:
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total

    def updated_at(self) -> float | None:
        """The newest mtime across this log and its rotations, or None."""
        newest: float | None = None
        for path in [self.path, *self.rotated()]:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if newest is None or mtime > newest:
                newest = mtime
        return newest


# ---------------------------------------------------------------------------
# parsing one line
# ---------------------------------------------------------------------------
@dataclass
class LogLine:
    ts: str | None
    level: str | None
    logger: str | None
    message: str
    #: Epoch seconds when ``ts`` parsed, so filters compare numbers rather than
    #: strings. None for a line with no usable timestamp (kept, never dropped).
    epoch: float | None = field(default=None, repr=False)

    def as_dict(self) -> dict:
        return {"ts": self.ts, "level": self.level, "logger": self.logger,
                "message": self.message}


def _parse_timestamp(date: str, clock: str, frac: str | None,
                     tz: str | None) -> tuple[str, float | None]:
    """(ISO text for the line, epoch seconds or None) from the regex groups."""
    micro = (frac or "0").ljust(6, "0")[:6]
    if tz:
        suffix = "+00:00" if tz == "Z" else (
            tz if ":" in tz else f"{tz[:3]}:{tz[3:]}")
        iso = f"{date}T{clock}.{micro}{suffix}"
        try:
            epoch = datetime.fromisoformat(iso).timestamp()
        except ValueError:  # pragma: no cover - the regex already fixed the shape
            return iso, None
        return iso, epoch
    # No zone in the line: the file was written in local time (the format this
    # module installs uses ``asctime``), so it is parsed as local time. The
    # reported ``ts`` keeps the offset so a client never has to guess.
    naive = datetime.fromisoformat(f"{date}T{clock}.{micro}")
    epoch = naive.timestamp()
    return naive.astimezone().isoformat(timespec="microseconds"), epoch


def parse_line(raw: str) -> LogLine:
    """One line of any of the three sources, structured as far as it goes.

    Three shapes are recognised: this service's own ``asctime`` format, an
    ISO8601-with-zone line (a worker that logs in UTC), and anything else. The
    third case is not an error -- ``message`` carries the raw text and ``level``
    is null, which is how a traceback or a native library's output survives
    into the console.
    """
    text = raw.rstrip("\r\n")
    match = _ISO_LINE.match(text) or _LOG_LINE.match(text)
    if match is None:
        return LogLine(ts=None, level=None, logger=None, message=text)
    groups = match.groupdict()
    ts, epoch = _parse_timestamp(groups["date"], groups["time"],
                                 groups.get("frac"), groups.get("tz"))
    level = _normalise_level(groups["level"])
    return LogLine(ts=ts, level=level, logger=groups["logger"],
                   message=groups["message"], epoch=epoch)


def _normalise_level(word: str) -> str:
    upper = word.upper()
    upper = _LEVEL_ALIASES.get(upper, upper)
    return upper if upper in LEVEL_ORDER else word


def level_threshold(level: str | None) -> int | None:
    """The minimum rank a line needs to pass ``level=``, or None for "any"."""
    if not level:
        return None
    upper = _LEVEL_ALIASES.get(level.strip().upper(), level.strip().upper())
    return LEVEL_ORDER.get(upper)


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def tail_lines(path: Path, count: int, *,
               block: int = _TAIL_BLOCK) -> list[str]:
    """The last ``count`` lines of a file, reading backwards in bounded blocks.

    This is the function the "newest N lines" endpoint is built on. Reading a
    50 MiB log forwards to keep its tail would cost 50 MiB of I/O and, worse, a
    list of every line; this costs one pass over the last ~``count`` lines plus
    at most one extra block, and memory never exceeds ``block`` bytes.

    A file that does not end in a newline still yields its last (partial) line:
    a worker that is mid-write has one, and hiding it would make "the newest
    line" lag by whatever the process has not flushed yet.
    """
    count = max(0, int(count))
    if count == 0:
        return []
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size == 0:
        return []
    chunks: list[bytes] = []
    newlines = 0
    with open(path, "rb") as fh:
        pos = size
        while pos > 0 and newlines <= count:
            step = min(block, pos)
            pos -= step
            fh.seek(pos)
            data = fh.read(step)
            chunks.append(data)
            newlines += data.count(b"\n")
        blob = b"".join(reversed(chunks))
    text = blob.decode("utf-8", "replace")
    # A leading partial line only counts as one when it is not the file's first
    # line (pos == 0 means the read reached the start, so it is complete).
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()          # the trailing newline terminates the last line
    if pos > 0 and lines:
        lines.pop(0)         # cut in half by the block boundary
    return [ln.rstrip("\r") for ln in lines[-count:]]


def iter_lines(path: Path, *, start: int = 0, stop: int | None = None,
               chunk: int = _TAIL_BLOCK) -> Iterator[str]:
    """Yield a file's lines in order, one bounded chunk at a time.

    ``start``/``stop`` are byte offsets: the download endpoint uses them to
    stream a range of a log without reading the file into memory. A line longer
    than ``MAX_LINE_BYTES`` is yielded in pieces rather than buffered whole.
    """
    try:
        fh = open(path, "rb")
    except OSError:
        return
    with fh:
        fh.seek(start)
        remaining = None if stop is None else max(0, stop - start)
        buffer = b""
        while True:
            want = chunk if remaining is None else min(chunk, remaining)
            if want == 0:
                break
            data = fh.read(want)
            if not data:
                break
            if remaining is not None:
                remaining -= len(data)
            buffer += data
            while True:
                nl = buffer.find(b"\n")
                if nl < 0:
                    break
                yield buffer[:nl].decode("utf-8", "replace").rstrip("\r")
                buffer = buffer[nl + 1:]
            if len(buffer) >= MAX_LINE_BYTES:
                yield buffer.decode("utf-8", "replace")
                buffer = b""
        if buffer:
            yield buffer.decode("utf-8", "replace").rstrip("\r")


def filtered_lines(source: LogSource, *,
                   since: float | None = None, until: float | None = None,
                   level: str | None = None, q: str | None = None,
                   rotated: bool = True) -> Iterator[LogLine]:
    """Every matching line of ``source``, oldest first, rotations included.

    Streams: the caller (the download endpoint) consumes one line at a time, so
    a filtered download of a large log never holds more than a line in memory.

    A line with no timestamp passes the time filter only when no time filter was
    asked for. There is no honest answer to "is this traceback after 10:00" when
    it carries no time, and silently including it would put unrelated output in
    a windowed view.
    """
    paths = ([*source.rotated(), source.path] if rotated else [source.path])
    threshold = level_threshold(level)
    needle = (q or "").lower()
    for path in paths:
        for raw in iter_lines(path):
            line = parse_line(raw)
            # Matched against the whole line, not just `message`: an operator
            # searching for "worker" means the logger too, and both readers
            # (`filtered_lines` here and `read_page`) must agree or a filtered
            # download would not match what the page showed.
            if needle and needle not in raw.lower():
                continue
            if threshold is not None:
                rank = LEVEL_ORDER.get(line.level or "", 0)
                if rank < threshold:
                    continue
            if since is not None or until is not None:
                if line.epoch is None:
                    continue
                if since is not None and line.epoch < since:
                    continue
                if until is not None and line.epoch > until:
                    continue
            yield line


def iter_lines_backwards(path: Path, end: int | None = None, *,
                         block: int = _TAIL_BLOCK,
                         budget: "Budget | None" = None,
                         ) -> Iterator[tuple[int, str]]:
    """Yield ``(offset, line)`` from a file's end backwards, lazily, one block at
    a time.

    ``offset`` is the line's first byte. That is what a cursor is made of, and it
    is stable while the file only grows: a line's offset never changes, so a page
    fetched now and the page after it describe the same file even if a thousand
    lines landed in between. (A rotated file moves, which is why the cursor also
    names which file of the chain it was in -- see ``encode_cursor``.)

    ``end`` bounds the read (a cursor points into the middle); ``budget`` caps
    how many bytes may be read in total, so a filtered query that matches nothing
    still stops instead of walking a 50 MiB file to its start.

    Blank lines are skipped: a log viewer's "200 lines" means 200 lines of
    output, not 200 lines of which a fifth are separators.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return
    stop = size if end is None else max(0, min(int(end), size))
    if stop == 0:
        return
    with open(path, "rb") as fh:
        pos = stop
        carry = b""          # a record whose start is in an earlier (smaller) block
        while pos > 0:
            step = min(block, pos)
            if budget is not None and not budget.take(step):
                # The next block was refused, so the bytes from ``pos`` upwards
                # have not been read. Report that position: it is exactly where
                # a resumed read has to start (the cursor is exclusive, so the
                # refused block is still ahead of it).
                budget.resume = pos
                return
            pos -= step
            fh.seek(pos)
            data = fh.read(step)
            buf = data + carry
            index = len(buf)
            while index > 0:
                newline = buf.rfind(b"\n", 0, index)
                if newline < 0:
                    break
                start = newline + 1
                if start < index:
                    yield pos + start, buf[start:index].decode(
                        "utf-8", "replace").rstrip("\r")
                index = newline
            if index == 0:
                carry = b""
                continue
            if len(buf) >= MAX_LINE_BYTES:
                # One enormous line (a stack trace with no newline anywhere).
                # Emit what can be shown and stop growing the buffer; the rest of
                # that line is not read at all, which is the only way one bad
                # line cannot make a page cost the whole file.
                yield pos, buf[:MAX_LINE_BYTES].decode("utf-8", "replace")
                carry = b""
                continue
            # The head of this buffer continues into the previous block.
            carry = buf[:index]
        if carry:
            yield 0, carry.decode("utf-8", "replace").rstrip("\r")


class Budget:
    """A byte allowance for one request's read, so work is bounded."""

    def __init__(self, limit: int) -> None:
        self.remaining = max(0, int(limit))
        #: True once ``iter_lines_backwards`` refused a block: the reader
        #: stopped for lack of allowance, not because it reached the file's
        #: start. Distinguishing the two is what lets a page say "there is more"
        #: honestly.
        self.stopped = False
        #: The byte position the scan got down to before the allowance ran out.
        #: A page that matched nothing still has to say where to continue, or a
        #: filtered query over a busy log would silently report "nothing" for
        #: everything past the first 16 MiB.
        self.resume: int | None = None

    def take(self, want: int) -> bool:
        if self.remaining <= 0:
            self.stopped = True
            return False
        self.remaining -= want
        return True


#: How many bytes one API page may read while looking for matching lines. A page
#: that fills up before it finds ``limit`` lines still returns what it found,
#: with ``has_more`` set, so the client continues from the cursor instead of the
#: service walking a large log to its beginning. 16 MiB is ~200k lines.
SCAN_BUDGET_BYTES = 16 * 1024 * 1024


def encode_cursor(source: LogSource, files: list[Path], index: int, offset: int) -> str:
    """The opaque position of "the line just before this one" in a source.

    Carries the source id (a cursor from one log is refused by another), the
    file's *name* (an index would silently point at a different generation after
    a rotation) and the byte offset.
    """
    payload = json.dumps({"s": source.id, "f": files[index].name, "o": int(offset)},
                         separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(source: LogSource, cursor: str) -> tuple[str, int]:
    """``(file name, offset)`` from a cursor; ``BadCursor`` if it is not one."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if payload.get("s") != source.id:
            raise BadCursor(cursor)
        return str(payload["f"]), int(payload["o"])
    except BadCursor:
        raise
    except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise BadCursor(cursor) from exc


class BadCursor(ValueError):
    """The cursor is not one this source issued (HTTP 400)."""

    def __init__(self, cursor: str) -> None:
        super().__init__(f"无效的翻页游标：{cursor[:32]}")
        self.cursor = cursor


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def read_page(source: LogSource, *, since: float | None = None,
              until: float | None = None, level: str | None = None,
              q: str | None = None, limit: int = LOG_LINES_DEFAULT,
              cursor: str | None = None,
              budget_bytes: int = SCAN_BUDGET_BYTES,
              ) -> tuple[list[LogLine], str | None, bool]:
    """One page of a source, newest line first: ``(lines, next_cursor, has_more)``.

    Paginates by byte position rather than by row number, which is the only way
    the answer stays stable while the file is being written: new lines arrive at
    the end and do not shift anything already returned. ``next_cursor`` is None
    when there is nothing older to fetch (so the console's "load older" button
    is offered exactly when it would do something); ``has_more`` is the same fact
    in boolean form.
    """
    limit = max(1, min(LOG_LINES_MAX, int(limit)))
    files = [*source.rotated(), source.path]
    if not files[0].parent.is_dir():
        return [], None, False
    start_index = len(files) - 1
    start_offset: int | None = None
    if cursor:
        name, offset = decode_cursor(source, cursor)
        names = [p.name for p in files]
        if name not in names:
            # The generation this cursor named has been rotated out of
            # existence. Say so by ending the walk rather than silently
            # returning the newest lines again, which would look like a loop.
            return [], None, False
        start_index = names.index(name)
        start_offset = offset

    threshold = level_threshold(level)
    needle = (q or "").lower()
    budget = Budget(budget_bytes)
    out: list[LogLine] = []
    next_cursor: str | None = None
    position: tuple[int, int] | None = None    # (file index, offset) of `next_cursor`
    cut = False
    for index in range(start_index, -1, -1):
        end = start_offset if index == start_index else None
        for offset, raw in iter_lines_backwards(files[index], end, budget=budget):
            line = parse_line(raw)
            if needle and needle not in raw.lower():
                continue
            if threshold is not None and LEVEL_ORDER.get(line.level or "", 0) < threshold:
                continue
            if since is not None or until is not None:
                if line.epoch is None:
                    continue
                if since is not None and line.epoch < since:
                    continue
                if until is not None and line.epoch > until:
                    continue
            out.append(line)
            next_cursor = encode_cursor(source, files, index, offset)
            position = (index, offset)
            if len(out) >= limit:
                cut = True
                break
        if cut:
            break
        if budget.stopped:
            # Out of allowance before the page filled: there is more to read,
            # but reading it now would make this request unbounded. The cursor
            # resumes from the last line returned, or -- when nothing matched --
            # from where the scan stopped, which is the only way a filtered
            # query can look past its first 16 MiB.
            if position is None and budget.resume is not None:
                resume = min(budget.resume, _size(files[index]))
                next_cursor = encode_cursor(source, files, index, resume)
                position = (index, max(1, resume))
            cut = True
            break
    if position is not None and position == (0, 0):
        # The page ended exactly at the first byte of the oldest generation;
        # there is nothing older, and a cursor that returns nothing is a button
        # that does nothing.
        cut = False
    if not cut:
        next_cursor = None
    return out, next_cursor, next_cursor is not None


# ---------------------------------------------------------------------------
# the registry
# ---------------------------------------------------------------------------
def rotate_log_file(path: Path, *, max_bytes: int, backups: int) -> bool:
    """Roll ``path`` to ``path.1`` (shifting older generations) when it is full.

    Called at the moment a writer is about to open the file in append mode, which
    is the only safe moment to rename it: nothing holds an fd to it yet. Returns
    whether anything was rotated -- useful to a test, and harmless otherwise.

    Worker logs live where they always have (the model manager names the path),
    so this is a rename in place rather than a second logging configuration: the
    child process keeps writing whatever it writes, and what it wrote yesterday
    is a separate file the page can still read.
    """
    try:
        path = Path(path)
        if not path.exists() or path.stat().st_size < max_bytes:
            return False
        for index in range(backups - 1, 0, -1):
            older = path.with_name(f"{path.name}.{index}")
            if older.exists():
                os.replace(older, path.with_name(f"{path.name}.{index + 1}"))
        os.replace(path, path.with_name(path.name + ".1"))
        return True
    except OSError:  # pragma: no cover - rotation must never block a load
        logger.warning("rotating %s failed", path)
        return False


class LogRegistry:
    """Every log source the page may show, derived from the filesystem.

    Rebuilt on each call rather than cached: a model that was just loaded has a
    new worker log and an agent that was installed has a new directory, and a
    cached list would keep the page showing yesterday's set. The walk is over
    two directories' immediate children, which is cheap enough to do per
    request and is why there is no invalidation to get wrong.
    """

    def __init__(self, *, platform_path: Callable[[], Path],
                 worker_dir: Callable[[], Path],
                 agents_root: Callable[[], Path],
                 agent_specs: Callable[[], Iterable] | None = None) -> None:
        # All three are callables so a data-directory move is picked up without
        # rebuilding this object (see app/main.py's rebind).
        self._platform_path = platform_path
        self._worker_dir = worker_dir
        self._agents_root = agents_root
        self._agent_specs = agent_specs

    # -- platform --------------------------------------------------------
    @property
    def platform_path(self) -> Path:
        return self._platform_path()

    def rotate_worker_log(self, model_id: str) -> None:
        """Rotate ``worker-<id>.log`` before a worker opens it in append mode."""
        rotate_log_file(self._worker_dir() / f"worker-{model_id}.log",
                        max_bytes=WORKER_LOG_MAX_BYTES,
                        backups=WORKER_LOG_BACKUPS)
    # -- discovery -------------------------------------------------------
    def agent_specs(self) -> dict[str, object]:
        if self._agent_specs is None:
            return {}
        return {spec.id: spec for spec in self._agent_specs()}

    def sources(self) -> list[LogSource]:
        """Every source that exists right now, platform first."""
        out: list[LogSource] = [LogSource(
            id="platform", label="平台日志", path=self.platform_path,
            kind="platform")]
        worker_dir = self._worker_dir()
        try:
            names = sorted(p.name for p in worker_dir.iterdir())
        except OSError:
            names = []
        seen: set[str] = set()
        for name in names:
            if not name.startswith("worker-"):
                continue
            # ``worker-<model>.log`` and its generations ``.log.1``. The model id
            # itself may contain dots, so the suffix is stripped from the *end*.
            base = name[len("worker-"):]
            if not base.endswith(".log"):
                stem, _, generation = base.rpartition(".log.")
                if not (stem and generation.isdigit()):
                    continue
                base = stem + ".log"
            model_id = base[: -len(".log")]
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            out.append(LogSource(
                id=f"worker:{model_id}", label=f"推理服务日志 · {model_id}",
                path=worker_dir / f"worker-{model_id}.log", kind="worker"))
        specs = self.agent_specs()
        for agent_id in specs:
            path = self._agents_root() / agent_id / "logs" / "agent.log"
            if not path.parent.is_dir():
                continue
            out.append(LogSource(
                id=f"agent:{agent_id}", label=f"Agent 日志 · {specs[agent_id].name}",
                path=path, kind="agent", agent_id=agent_id))
        return out

    def get(self, source_id: str) -> LogSource | None:
        for source in self.sources():
            if source.id == source_id:
                return source
        return None

    def resolve(self, source_id: str) -> LogSource:
        """The source named by ``source_id``, or ``UnknownSource``.

        The single place an untrusted string becomes a path. It matches against
        a list built from the filesystem, so ``../``, an absolute path or a
        symlink name cannot reach anything that list does not already contain.
        """
        source = self.get(source_id)
        if source is None:
            raise UnknownSource(source_id)
        return source


class UnknownSource(LookupError):
    """The requested log source does not exist (HTTP 404)."""

    def __init__(self, source_id: str) -> None:
        super().__init__(f"未知的日志来源：{source_id}")
        self.source_id = source_id


# ---------------------------------------------------------------------------
# the platform log file
# ---------------------------------------------------------------------------
class _IsoLocalFormatter(logging.Formatter):
    """``2026-11-07T10:27:46.123+08:00 INFO cv84x6: message``.

    ISO8601 with the local offset: an operator here reads local time, and the
    offset keeps the line unambiguous when the file is read on another machine
    (or after the board's clock is stepped by NTP). The format is named in one
    place because ``parse_line`` reads it back -- changing one without the other
    would turn every line into "unparseable", which is valid output and a
    useless page.
    """

    def formatTime(self, record, datefmt=None):  # noqa: N802 - logging's name
        return datetime.fromtimestamp(record.created).astimezone().isoformat(
            timespec="milliseconds")


#: Marks the handler this module installed, so a second ``create_app`` (a test
#: process builds many) replaces it instead of stacking a duplicate writer on
#: the same file.
_HANDLER_ATTR = "_cv84x6_platform_log"


def install_platform_log(path: Path, *,
                         max_bytes: int = PLATFORM_LOG_MAX_BYTES,
                         backups: int = PLATFORM_LOG_BACKUPS,
                         level: int = logging.DEBUG) -> logging.Handler | None:
    """Attach the rotating file handler to the root logger.

    stderr stays untouched: systemd's journal is the operator's safety net when
    this file cannot be written (a full disk, a moved data directory), and the
    two are not in competition. A handler that cannot open its file is reported
    and skipped -- a service that refuses to start because it cannot write a log
    would be a worse failure than a missing log.
    """
    root = logging.getLogger()
    detach_platform_log()
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8",
            delay=True)
    except OSError as exc:
        logger.warning("platform log file unavailable (%s); stderr only", exc)
        return None
    handler.setFormatter(_IsoLocalFormatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.setLevel(level)
    setattr(handler, _HANDLER_ATTR, True)
    root.addHandler(handler)
    return handler


def detach_platform_log() -> None:
    """Remove a previously installed platform log handler, closing its file."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_ATTR, False):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # pragma: no cover - closing a dead file
                pass


def rebind_platform_log(old: Path, new: Path, *,
                        max_bytes: int = PLATFORM_LOG_MAX_BYTES,
                        backups: int = PLATFORM_LOG_BACKUPS) -> logging.Handler | None:
    """Point the platform log at ``new`` after a data-directory move.

    The handler is closed *before* the copy (``detach_platform_log`` from the
    move's stop hook), so by the time the switch happens the file under the old
    root has no writer. Re-installing here means the platform log continues in
    the new tree on the next record instead of vanishing for the rest of the
    process's life -- the same failure mode the inference log's ``rebind``
    exists to prevent.
    """
    del old  # kept in the signature so callers read as "move this to there"
    return install_platform_log(new, max_bytes=max_bytes, backups=backups)


def with_redaction(source: LogSource, specs: dict[str, object],
                   lines: Iterable[LogLine]) -> Iterator[LogLine]:
    """Apply the source's own secret filter to each line before it leaves.

    An agent that prints a launch credential (DSH) has a ``public_log`` that
    removes it, and ``GET /api/agents/<id>/logs`` already applies it. A log page
    that served the same file unfiltered would hand out the token that route
    spends effort hiding, so the filter goes on the stream, once.
    """
    spec = specs.get(source.agent_id) if source.agent_id else None
    redact = getattr(spec, "public_log", None)
    if not callable(redact):
        for line in lines:
            yield line
        return
    for line in lines:
        line.message = redact(line.message)
        yield line


def utc_now() -> float:
    return time.time()


class SourceCache:
    """``size_bytes``/``updated_at`` per source with a short TTL.

    The console polls ``GET /api/logs/sources`` while the page is open, and each
    answer stats every log and every rotation. A 2 s cache keeps a poll loop
    from walking the directory 30 times a minute while still showing a log that
    just grew.
    """

    def __init__(self, ttl: float = 2.0) -> None:
        self.ttl = ttl
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str], tuple[float, int, float | None]] = {}

    def describe(self, source: LogSource) -> dict:
        key = (source.id, str(source.path))
        now = time.monotonic()
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None and now - hit[0] < self.ttl:
                _, size, updated = hit
            else:
                size, updated = source.size_bytes(), source.updated_at()
                self._entries[key] = (now, size, updated)
        return {"id": source.id, "label": source.label, "size_bytes": size,
                "updated_at": updated}

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
