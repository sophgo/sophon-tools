"""Which local files an MCP tool may read, how much of them, and how.

``ocr_read``, ``kb_add_document`` and ``transcribe_audio`` take a *path on this
board*, which makes them the only tools whose arguments name something outside
the service's own data. An agent that can be talked into reading ``/etc/shadow``
-- and a language model very much can be -- must find the argument refused
before any byte is read, so the check lives here rather than in each tool.

The rule is an allowlist of directories, evaluated on the **resolved** path:

* ``<data root>/agents/**``   each agent's own tree: workspace, data, uploads.
* ``<data root>/inbox/``      a general drop box for files an operator or a
                              script puts where an agent can be told to look.
* ``CV84X6_MCP_PATHS``        extra directories an operator declares in
                              ``server.env`` (``:``-separated, like ``PATH``).

Three properties matter, and each one is a bug this module is shaped around:

**``..`` and symlinks cannot escape.** The path is resolved (``realpath``, which
follows every link) *before* it is compared, so ``inbox/../../etc/passwd`` and a
link planted in a workspace both resolve to somewhere outside the roots and are
refused. A prefix test on the literal string is the classic hole: ``/data/agents``
is a prefix of ``/data/agents-old``, and a link passes the test and then hands
over its target. :func:`_is_within` therefore compares whole path components.

**Nothing is checked and then re-opened by name** (TOCTOU). :func:`read_local_file`
resolves, checks, and *opens* in one call, and reads from the returned file
descriptor, so a path that is swapped between the check and the read cannot be
used to reach a file the check refused. The open uses ``O_NOFOLLOW`` on the final
component, and the descriptor's own ``/proc/self/fd`` target is re-checked
against the roots for the same reason. ``O_NONBLOCK`` is set so opening a FIFO
cannot hang the check before ``fstat`` has a chance to refuse it.

**The size limit bounds the read, not just the ``stat``.** A file that grows
after it was measured must not be read past the cap: the descriptor is read for
at most ``limit + 1`` bytes, and one byte over is a refusal. That is what makes
"≤ 50 MiB" true of the memory this service actually spends.

Messages are written for the model that will read them: a typo says "no such
file" rather than blaming permissions, and a refusal names the allowed
directories by their *relative* names -- the server's absolute layout is not
something a tool call needs to learn.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from ..apps.kb import parse as kb_parse

#: Extra directories, colon-separated, named in ``server.env``. Read at call
#: time rather than at import: the service's environment is fixed for the life
#: of the process, but a test (and a future reload button) needs to change it.
PATHS_ENV = "CV84X6_MCP_PATHS"

#: The drop box every install has, relative to the data root.
INBOX_NAME = "inbox"

#: Where each agent keeps the files it was given. Declared as a pattern rather
#: than a list of agent ids so a new agent is covered the moment it is
#: installed: every agent lives under ``agents/<id>/`` and its workspace,
#: ``data/`` and downloaded media are all somewhere below that.
AGENTS_NAME = "agents"

#: How much is read per ``os.read`` call. Bounded so a 50 MiB file does not
#: become one 50 MiB allocation before the cap can be enforced.
_CHUNK = 1 << 20


class PathRefused(Exception):
    """The path is not one these tools may read. The message goes to the model."""


class LocalFile:
    """A file that passed the allowlist, already read (bounded) into memory."""

    __slots__ = ("path", "name", "data")

    def __init__(self, path: Path, name: str, data: bytes) -> None:
        #: The resolved path, for the reply's ``path`` field.
        self.path = path
        #: The file name, which decides the document's kind.
        self.name = name
        self.data = data

    def __len__(self) -> int:  # pragma: no cover - convenience
        return len(self.data)


def allowed_roots(data_root: Path) -> list[Path]:
    """Every directory a path argument may resolve into, already resolved.

    ``data_root`` is the service's data directory (``app.state.agents.data_root``
    -- the manager keeps it current across a data-directory move, which a
    captured path would not).
    """
    roots: list[Path] = []
    root = Path(data_root)
    for name in (AGENTS_NAME, INBOX_NAME):
        candidate = root / name
        # A root that does not exist yet is still listed: resolving it is cheap
        # and a file cannot be inside a directory that is not there anyway.
        roots.append(_resolve(candidate))
    for raw in (os.environ.get(PATHS_ENV) or "").split(os.pathsep):
        raw = raw.strip()
        if raw:
            roots.append(_resolve(Path(raw)))
    # Longest first, so an error message can name the most specific root.
    return sorted(set(roots), key=lambda p: len(str(p)), reverse=True)


def _resolve(path: Path) -> Path:
    """``realpath`` without requiring the path to exist (its parents must)."""
    return Path(os.path.realpath(path))


def read_local_file(raw: str, data_root: Path, *,
                    limit: int | None = None) -> LocalFile:
    """Open, check and read one file the tools are allowed to touch.

    Blocking: callers run this through ``asyncio.to_thread``. Everything between
    "which path is this" and "these are its bytes" happens here, against one
    file descriptor, so there is no window in which the checked name can be
    replaced by another file before it is read.
    """
    cap = kb_parse.MAX_FILE_BYTES if limit is None else int(limit)
    text = (raw or "").strip()
    if not text:
        raise PathRefused("path 不能为空")
    if "\x00" in text:
        raise PathRefused("path 含有空字节")
    path = Path(text)
    if not path.is_absolute():
        raise PathRefused(
            f"path 必须是绝对路径（收到 {text!r}）；"
            f"可读取的目录见 /mcp 的文档")
    resolved = _resolve(path)

    # Cheap, non-blocking shape checks before anything is opened: `os.stat`
    # follows links (there are none left after realpath) and never blocks on a
    # FIFO, so a wrong kind of file is refused without a descriptor.
    try:
        info = resolved.stat()
    except FileNotFoundError:
        raise PathRefused(f"文件不存在：{_label(resolved, data_root)}") from None
    except OSError as exc:
        raise PathRefused(f"无法访问该路径：{exc.strerror or '未知错误'}") from None
    if stat.S_ISDIR(info.st_mode):
        raise PathRefused(f"{_label(resolved, data_root)} 是目录，这里需要文件")
    if not stat.S_ISREG(info.st_mode):
        # A fifo or a device would block the read forever or stream something
        # unbounded; neither is a document.
        raise PathRefused(f"{_label(resolved, data_root)} 不是普通文件")

    _require_allowed(resolved, data_root)
    if info.st_size > cap:
        raise PathRefused(_too_big(info.st_size, cap))

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(resolved, flags)
    except FileNotFoundError:
        raise PathRefused(f"文件不存在：{_label(resolved, data_root)}") from None
    except OSError as exc:
        # ELOOP is the interesting one: the name became a link after it was
        # resolved. Everything else is reported without a traceback.
        raise PathRefused(
            f"{_label(resolved, data_root)} 无法打开：{exc.strerror or '未知错误'}") from None
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise PathRefused(f"{_label(resolved, data_root)} 不是普通文件")
        if opened.st_size > cap:
            raise PathRefused(_too_big(opened.st_size, cap))
        # The descriptor's own target, not the name we opened: if a directory
        # component was swapped for a link after `realpath`, this is where it
        # shows. `/proc` is Linux-only; its absence must not refuse a good file.
        actual = _fd_path(fd)
        if actual is not None:
            _require_allowed(actual, data_root)
        data = _read_bounded(fd, cap)
    finally:
        os.close(fd)

    return LocalFile(path=resolved, name=resolved.name, data=data)


def _read_bounded(fd: int, cap: int) -> bytes:
    """Read at most ``cap + 1`` bytes; one byte over the cap is a refusal.

    Reading ``cap + 1`` rather than ``cap`` is what makes the check exact: a
    file that grew past the limit after ``fstat`` is refused, not silently
    truncated into a document that looks complete.
    """
    chunks: list[bytes] = []
    total = 0
    while total <= cap:
        want = min(_CHUNK, cap + 1 - total)
        if want <= 0:
            break
        chunk = os.read(fd, want)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    data = b"".join(chunks)
    if len(data) > cap:
        raise PathRefused(_too_big(len(data), cap))
    return data


def _fd_path(fd: int) -> Path | None:
    """The real path behind an open descriptor, or None where that is unknown."""
    try:
        return Path(os.readlink(f"/proc/self/fd/{fd}"))
    except OSError:  # pragma: no cover - no /proc, or the link is gone
        return None


def _too_big(size: int, cap: int) -> str:
    return f"文件 {size / 2**20:.1f} MB，超过上限 {cap // 2**20} MB"


def _require_allowed(resolved: Path, data_root: Path) -> None:
    roots = allowed_roots(data_root)
    for root in roots:
        if _is_within(resolved, root):
            return
    # Relative names only: the model needs to know *where* it may look, not
    # what this server's absolute layout is.
    shown = "、".join(_root_label(root, data_root) for root in roots) or "（无）"
    raise PathRefused(
        f"不允许读取 {_label(resolved, data_root)}：只允许数据根目录下的 "
        f"agents/ 与 inbox/，以及 {PATHS_ENV} 中列出的目录（当前：{shown}）")


def _label(path: Path, data_root: Path) -> str:
    """How a path is named in a message: relative under the data root, else basename."""
    try:
        return str(path.relative_to(_resolve(Path(data_root))))
    except ValueError:
        return path.name or "该路径"


def _root_label(root: Path, data_root: Path) -> str:
    try:
        return str(root.relative_to(_resolve(Path(data_root)))) + "/"
    except ValueError:
        return (root.name or "该路径") + "/"


def _is_within(path: Path, root: Path) -> bool:
    """Whether ``path`` is ``root`` or below it, comparing whole components.

    ``str.startswith`` is not enough and is the usual bug: ``/data/agents-old``
    starts with ``/data/agents``. Both sides are already resolved here, so
    component-wise containment is the honest test.
    """
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
