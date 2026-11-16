"""The data directory: its layout, its footprint, and moving it elsewhere.

Every mutable byte the service keeps -- models, keys/usage state, worker logs --
lives under one root (``/data/cv84x6_llm_server`` by default) so the operator can
put it on whichever disk has room and move it later from the console. The install
tree (``/opt/sophgo/cv84x6_llm_server``) holds only code and is replaced wholesale
on upgrade.

A move is a small state machine rather than a single ``shutil.move``: models must
be unloaded first, the copy must be verified, and the location must only switch
once both of those hold. Any failure before the switch leaves the service where
it was, with the configuration file untouched.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# The marker is what tells this service "this directory is mine to move or
# delete". Without it a purge could eat an unrelated tree, so it gates both.
MARKER_NAME = ".cv84x6-data"
MARKER_CONTENT = {"version": 1}

# What a data root holds. `agents` and `downloads` are created up front so a
# later feature (per-agent state, download staging) has somewhere to go without
# another migration.
#
# `apps` is the demo applications' data (app/apps/): knowledge bases and their
# vectors. It is a *part* rather than a subdirectory of another one because a
# move has to carry it -- a library left behind would read as "my vectors are
# gone" after a perfectly successful migration.
#
# `inbox` is the drop box the MCP tools may read from (app/mcp/paths.py). It is
# a part for the same reason `apps` is: an operator who parks a PDF there for an
# agent to OCR expects it to still be there after a data-directory move.
SUBDIRS = ("models", "state", "agents", "downloads", "apps", "inbox")
PARTS = SUBDIRS

# The single source of truth for where the data lives; systemd reads the file it
# sits in through EnvironmentFile=.
ENV_KEY = "CV84X6_DATA_DIR"

# Free space the target must have beyond the current footprint: the service
# keeps writing logs and a download may land while the copy runs.
SPACE_MARGIN_BYTES = 1 << 30

# Directory walks are metadata-only but on 20+ GB of models they are still the
# most expensive thing the overview page could do every two seconds.
SIZE_TTL_S = 30.0

# How many copy passes to try when verification finds a difference. State files
# can change mid-copy (a request lands and records usage); one extra pass picks
# those up without giving up on a genuinely broken copy.
COPY_ATTEMPTS = 2

FileSize = int


class StorageError(Exception):
    """A refusal or a failure worth explaining to the operator (HTTP 400)."""


class StorageBusy(Exception):
    """Another move is in flight (HTTP 409): one at a time, by design."""


# -- layout -----------------------------------------------------------------
def ensure_layout(root: Path) -> Path:
    """Create the data root and its subdirectories, and stamp the marker.

    Idempotent: an existing marker is left alone, so re-running the installer
    (or a restart) never disturbs the data.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for name in SUBDIRS:
        (root / name).mkdir(exist_ok=True)
    write_marker(root)
    return root


def write_marker(root: Path) -> None:
    marker = Path(root) / MARKER_NAME
    if marker.exists():
        return
    tmp = marker.with_name(MARKER_NAME + ".tmp")
    tmp.write_text(json.dumps(MARKER_CONTENT))
    os.replace(tmp, marker)


def has_marker(root: Path) -> bool:
    marker = Path(root) / MARKER_NAME
    if not marker.is_file():
        return False
    try:
        return bool(json.loads(marker.read_text()).get("version"))
    except (OSError, ValueError):
        return False


# -- measurement ------------------------------------------------------------
def walk_stats(path: Path) -> tuple[int, int]:
    """(file count, total bytes) below ``path``, never following symlinks.

    Symlinks count as one entry of their own length rather than as their target:
    a data root that links a model tree in from another disk must not be measured
    (or copied) as if the bytes were local.
    """
    files = 0
    total = 0
    stack = [Path(path)]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for entry in it:
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    else:
                        files += 1
                        total += st.st_size
        except OSError:
            continue
    return files, total


def dir_bytes(path: Path) -> int:
    return walk_stats(path)[1]


def _nearest_existing(path: Path) -> Path:
    p = Path(path)
    for _ in range(64):
        if p.exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    return Path("/")


def fs_usage(path: Path) -> dict:
    """Used/available/total for the filesystem holding ``path``.

    ``free`` is what an unprivileged process may write (f_bavail), which is the
    number that decides whether a move fits.
    """
    st = os.statvfs(str(_nearest_existing(Path(path))))
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    return {"total": total, "used": used, "free": free}


class SizeCache:
    """Caches directory sizes for ``ttl`` seconds, keyed by path."""

    def __init__(self, ttl: float = SIZE_TTL_S) -> None:
        self.ttl = ttl
        self._entries: dict[str, tuple[float, int]] = {}

    def measure(self, path: Path, *, refresh: bool = False) -> int:
        key = str(path)
        now = time.monotonic()
        if not refresh:
            hit = self._entries.get(key)
            if hit is not None and now - hit[0] < self.ttl:
                return hit[1]
        value = dir_bytes(path) if Path(path).exists() else 0
        self._entries[key] = (now, value)
        return value

    def invalidate(self) -> None:
        self._entries.clear()


# -- the move job -----------------------------------------------------------
@dataclass
class MoveJob:
    id: str
    old: str
    new: str
    state: str = "idle"
    copied_bytes: int = 0
    total_bytes: int = 0
    message: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    # Whether the target directory itself was created by this job; rollback
    # removes it again, but an operator-provided empty directory stays.
    created_target: bool = False

    def public(self) -> dict:
        return {
            "id": self.id,
            "state": self.state,
            "copied_bytes": self.copied_bytes,
            "total_bytes": self.total_bytes,
            "message": self.message,
            "old": self.old,
            "new": self.new,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class StorageManager:
    """Owns the data root's location and the one move job at a time.

    The application-specific parts -- unloading models before the copy, swapping
    the live store afterwards -- arrive as callbacks, so this class can be tested
    against a bare temporary tree.
    """

    def __init__(
        self,
        root: Path,
        *,
        state_dir: Path | None = None,
        models_dir: Path | None = None,
        env_file: Path | None = None,
        install_dir: Path | None = None,
        allow_delete_old: bool = True,
        pre_stop: Callable[[], Awaitable[None]] | None = None,
        post_switch: Callable[[Path], None] | None = None,
    ) -> None:
        self.root = Path(root)
        self.state_dir = Path(state_dir) if state_dir else self.root / "state"
        self.models_dir = Path(models_dir) if models_dir else self.root / "models"
        self.env_file = Path(env_file) if env_file else None
        self.install_dir = Path(install_dir) if install_dir else None
        # A legacy layout's "root" is the install prefix, which holds code as
        # well as data: never delete it, marker or not.
        self.allow_delete_old = allow_delete_old
        self._pre_stop = pre_stop
        self._post_switch = post_switch
        self._sizes = SizeCache()
        self.job: MoveJob | None = None
        self._task: asyncio.Task | None = None
        # Set by check_target so start_move can record whether the target
        # directory was ours to remove again on rollback.
        self._created_target = False

    # -- paths -----------------------------------------------------------
    def parts(self) -> dict[str, Path]:
        """Where each part lives right now.

        Deliberately the live paths rather than ``root/<name>``: a deployment
        installed before the split keeps its state in ``<prefix>/data`` and its
        models in ``<prefix>/models``, and both have to be found where they
        actually are before they can be carried to the new layout.

        Built from :data:`PARTS` rather than spelled out, so a part added to the
        list is found by the move's copy and verify passes without a second edit
        here. (It was spelled out, and adding ``inbox`` to ``PARTS`` alone left
        this dict without it: the move then raised ``KeyError: 'inbox'`` mid-copy
        and rolled back.) Only the two legacy-moved parts need overriding.
        """
        roots = {name: self.root / name for name in PARTS}
        roots["models"] = self.models_dir
        roots["state"] = self.state_dir
        return roots

    @staticmethod
    def layout(root: Path) -> dict[str, Path]:
        """The canonical layout a data root has after a move or an install."""
        return {name: Path(root) / name for name in PARTS}

    def part_path(self, name: str) -> Path:
        return self.parts()[name]

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    # -- reporting -------------------------------------------------------
    def info(self, *, refresh: bool = False) -> dict:
        """Footprint report for GET /api/storage.

        ``dir_bytes`` is the sum of the four parts rather than a second walk of
        the root: a legacy deployment keeps its models outside the root, and a
        figure that disagreed with the breakdown beside it would be worse than
        no figure at all.
        """
        fs = fs_usage(self.root)
        parts = {
            name: self._sizes.measure(path, refresh=refresh)
            for name, path in self.parts().items()
        }
        return {
            "data_dir": str(self.root),
            "fs_total_bytes": fs["total"],
            "fs_used_bytes": fs["used"],
            "fs_free_bytes": fs["free"],
            "dir_bytes": sum(parts.values()),
            "parts": parts,
        }

    def job_view(self) -> dict:
        if self.job is None:
            return MoveJob(id="", old=str(self.root), new="", state="idle").public()
        return self.job.public()

    # -- validation ------------------------------------------------------
    def check_target(self, raw: str) -> Path:
        """Refuse anything that would lose data or write somewhere absurd.

        Runs synchronously in the request so the operator gets a plain 400 with
        the reason instead of having to watch a job fail.
        """
        if not raw or not str(raw).strip():
            raise StorageError("请填写目标路径")
        target = Path(str(raw).strip()).expanduser()
        if not target.is_absolute():
            raise StorageError("必须是绝对路径")
        target = Path(os.path.abspath(target))

        old = Path(os.path.abspath(self.root))
        try:
            new_r = target.resolve()
            old_r = old.resolve()
        except OSError:  # pragma: no cover - resolve() rarely fails now
            new_r, old_r = target, old

        if new_r == old_r:
            raise StorageError("目标就是当前数据目录")
        if old_r in new_r.parents:
            raise StorageError("目标不能在当前数据目录里面")
        if new_r in old_r.parents:
            raise StorageError("目标不能包含当前数据目录")
        if self.install_dir is not None:
            inst = Path(os.path.abspath(self.install_dir)).resolve()
            if new_r == inst or inst in new_r.parents:
                raise StorageError(f"目标不能在安装目录 {inst} 内")
        if self.env_file is not None:
            env_r = Path(os.path.abspath(self.env_file)).resolve()
            if new_r == env_r or env_r in new_r.parents:
                raise StorageError("目标不能包含服务配置文件")

        created = False
        if new_r.exists():
            if not new_r.is_dir():
                raise StorageError("目标已存在且不是目录")
            if any(new_r.iterdir()):
                raise StorageError("目标目录不是空的")
        else:
            try:
                new_r.mkdir(parents=True)
                created = True
            except OSError as exc:
                raise StorageError(f"无法创建目标目录：{exc}") from exc
        self._created_target = created

        # Writability is proved, not assumed: mkdir may succeed on a read-only
        # mount inherited from a parent, and ACLs can still deny the file.
        probe = new_r / f".cv84x6-probe-{uuid.uuid4().hex[:8]}"
        try:
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as exc:
            if created:
                _rmdir_if_empty(new_r)
            raise StorageError(f"目标目录不可写：{exc}") from exc

        need = self.footprint() + SPACE_MARGIN_BYTES
        free = fs_usage(new_r)["free"]
        if free < need:
            if created:
                _rmdir_if_empty(new_r)
            raise StorageError(
                f"目标文件系统可用空间不足：需要 {_fmt(need)}，可用 {_fmt(free)}"
            )
        return new_r

    def footprint(self, *, refresh: bool = True) -> int:
        """Total bytes under every part, measured now unless cached."""
        return sum(self._sizes.measure(p, refresh=refresh) for p in self.parts().values())

    # -- the job ---------------------------------------------------------
    def start_move(self, raw: str, target: Path | None = None) -> MoveJob:
        """Begin a move. ``target`` may be passed in when a caller validated it
        from a worker thread (the walk of a 20 GB tree must not block the loop)."""
        if self.busy:
            raise StorageBusy("已有搬迁任务在进行")
        target = Path(target) if target is not None else self.check_target(raw)
        job = MoveJob(id=uuid.uuid4().hex, old=str(self.root), new=str(target),
                      state="checking", created_target=self._created_target)
        self.job = job
        self._task = asyncio.ensure_future(self._run(job, target))
        return job

    async def _run(self, job: MoveJob, target: Path) -> None:
        old = Path(self.root)
        old_parts = self.parts()
        dest = self.layout(target)
        old_state, old_models = self.state_dir, self.models_dir
        env_before = _read_bytes(self.env_file)
        try:
            job.total_bytes = sum(dir_bytes(p) for p in old_parts.values() if p.exists())

            # 1-2. Get the service off the data: worker processes hold model
            # files and log fds under the old root; agents get their hook when
            # they exist.
            job.state = "stopping"
            if self._pre_stop is not None:
                await self._pre_stop()

            # 3-4. Copy, then prove the copy.
            job.state = "copying"
            await asyncio.to_thread(self._copy_parts, old_parts, dest, job)
            job.state = "verifying"
            mismatch = await asyncio.to_thread(self._verify_parts, old_parts, dest)
            for _ in range(COPY_ATTEMPTS - 1):
                if mismatch is None:
                    break
                job.message = f"校验发现差异，重新复制：{mismatch}"
                job.state = "copying"
                job.copied_bytes = 0
                await asyncio.to_thread(self._copy_parts, old_parts, dest, job)
                job.state = "verifying"
                mismatch = await asyncio.to_thread(self._verify_parts, old_parts, dest)
            if mismatch is not None:
                raise StorageError(f"复制校验失败：{mismatch}")

            # 5. Point the configuration at the new place. Written before the
            # in-memory switch so a crash in between comes back up on the new
            # path, where the data already is.
            env_written = self._write_env(target)

            # 6. Switch the running service over.
            job.state = "switching"
            self.root = target
            self.state_dir = target / "state"
            self.models_dir = target / "models"
            if self._post_switch is not None:
                self._post_switch(target)
            self._sizes.invalidate()
            if not env_written:
                job.message = ("配置文件中没有数据目录这一项（开发环境），"
                               "只切换了运行中的路径，重启后会回到原路径")

            # 7. Drop the old copy, but only a directory this service owns.
            if self.allow_delete_old and has_marker(old):
                # The new tree is live now; it needs the marker too, or the next
                # move would refuse to clean up after itself.
                await asyncio.to_thread(write_marker, target)
                skipped = [str(p) for p in old_parts.values() if p.exists()]
                await asyncio.to_thread(shutil.rmtree, old, True)
                leftovers = [p for p in skipped if Path(p).exists()]
                if leftovers:
                    # A part parked outside the root (legacy <prefix>/data with
                    # its models elsewhere) cannot be removed with it.
                    job.message = _join(job.message,
                                        "旧数据目录已删除；这些目录不在其中，未删除：" +
                                        "、".join(leftovers))
                else:
                    job.message = _join(job.message, f"已删除旧目录 {old}")
            else:
                job.message = _join(job.message, f"旧目录 {old} 未删除（无标记文件）")
            job.state = "done"
        except asyncio.CancelledError:  # pragma: no cover - no cancel path yet
            if self.root != target:      # nothing has switched: safe to clear
                await asyncio.to_thread(self._rollback, job, target)
            job.state = "failed"
            job.message = "任务被取消"
            raise
        except Exception as exc:  # noqa: BLE001 - reported to the operator
            logger.exception("data directory move failed")
            switched = self.root == target
            # Only clear the target while the old tree is still the live one.
            # Past the switch the new tree may hold the only copy of the data --
            # wiping it because the final cleanup failed would destroy exactly
            # what this job exists to protect.
            if not switched:
                await asyncio.to_thread(self._rollback, job, target)
            if switched:  # switched already: put the service back where it was
                self.root = old
                self.state_dir, self.models_dir = old_state, old_models
                if self._post_switch is not None:
                    try:
                        self._post_switch(old)
                    except Exception:  # pragma: no cover - the report matters more
                        logger.exception("restoring the old data root failed")
            if env_before is not None:
                _restore(self.env_file, env_before)
            job.state = "failed"
            job.message = str(exc) if isinstance(exc, StorageError) else f"{type(exc).__name__}: {exc}"
            if switched and old.exists():
                job.message = _join(job.message,
                                    f"数据已复制到 {target}；旧目录 {old} 未完全删除，请手工确认后清理")
        finally:
            job.finished_at = time.time()
            self._sizes.invalidate()

    # -- copy / verify / rollback ---------------------------------------
    def _copy_parts(self, old_parts: dict[str, Path], dest: dict[str, Path],
                    job: MoveJob) -> None:
        """Copy every part under its name in the new layout; symlinks stay symlinks."""
        for name in PARTS:
            src = old_parts[name]
            if not src.exists():
                dest[name].mkdir(parents=True, exist_ok=True)
                continue
            _copy_tree(src, dest[name], job)

    def _verify_parts(self, old_parts: dict[str, Path], dest: dict[str, Path]) -> str | None:
        for name in PARTS:
            src = old_parts[name]
            expected = walk_stats(src) if src.exists() else (0, 0)
            got = walk_stats(dest[name])
            if expected != got:
                return (f"{name}：源 {expected[0]} 个文件/{expected[1]} 字节，"
                        f"副本 {got[0]} 个文件/{got[1]} 字节")
        return None

    def _rollback(self, job: MoveJob, target: Path) -> None:
        """Leave the target as we found it: empty, never half-filled."""
        dest = self.layout(target)
        for child in [dest[name] for name in PARTS if dest[name].exists()]:
            shutil.rmtree(child, ignore_errors=True)
        if job.created_target:
            _rmdir_if_empty(Path(target))

    # -- configuration file ---------------------------------------------
    def _write_env(self, new_root: Path) -> bool:
        """Rewrite the data-directory line of server.env. False = not there.

        Temp file plus rename: a power cut either leaves the old file or the new
        one, never a truncated one that would strand the service at boot.
        """
        path = self.env_file
        if path is None or not Path(path).exists():
            return False
        try:
            text = Path(path).read_text()
        except OSError as exc:
            raise StorageError(f"配置文件不可读：{exc}") from exc
        out: list[str] = []
        replaced = False
        for line in text.splitlines():
            if line.strip().startswith(ENV_KEY + "="):
                out.append(f"{ENV_KEY}={new_root}")
                replaced = True
            else:
                out.append(line)
        if not replaced:
            out.append(f"{ENV_KEY}={new_root}")
        tmp = Path(str(path) + ".tmp")
        try:
            tmp.write_text("\n".join(out) + "\n")
            os.replace(tmp, path)
        except OSError as exc:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise StorageError(f"配置文件写入失败：{exc}") from exc
        return True


# -- helpers ----------------------------------------------------------------
def _copy_tree(src: Path, dst: Path, job: MoveJob) -> None:
    """Copy ``src`` into ``dst``, preserving symlinks, updating progress.

    ``shutil.copy2`` is called through the module attribute on purpose: tests
    swap it to make a copy fail halfway.
    """
    stack = [(Path(src), Path(dst))]
    while stack:
        s, d = stack.pop()
        d.mkdir(parents=True, exist_ok=True)
        with os.scandir(s) as it:
            entries = list(it)
        for entry in entries:
            sp = Path(entry.path)
            dp = d / entry.name
            if entry.is_symlink():
                link = os.readlink(sp)
                if dp.is_symlink() or dp.exists():
                    dp.unlink()
                os.symlink(link, dp)
                job.copied_bytes += entry.stat(follow_symlinks=False).st_size
            elif entry.is_dir(follow_symlinks=False):
                stack.append((sp, dp))
            elif entry.is_file(follow_symlinks=False):
                shutil.copy2(sp, dp)
                job.copied_bytes += entry.stat(follow_symlinks=False).st_size
            # Sockets and FIFOs have no content to carry over.


def _rmdir_if_empty(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


def _read_bytes(path: Path | None) -> bytes | None:
    if path is None:
        return None
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def _restore(path: Path | None, content: bytes) -> None:
    if path is None:  # pragma: no cover - guarded by the caller
        return
    try:
        tmp = Path(str(path) + ".restore")
        tmp.write_bytes(content)
        os.replace(tmp, path)
    except OSError:  # pragma: no cover - best effort
        logger.warning("could not restore %s", path)


def _join(a: str, b: str) -> str:
    return f"{a}；{b}" if a else b


def _fmt(n: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    v = float(n)
    for u in units:
        if v < 1024 or u == units[-1]:
            return f"{v:.1f} {u}"
        v /= 1024
    return f"{v:.1f} TiB"  # pragma: no cover
