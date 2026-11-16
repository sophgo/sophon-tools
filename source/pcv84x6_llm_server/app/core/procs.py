"""Discovering, proving and reattaching to processes a previous run left behind.

Both managers own child processes: ``ModelManager`` its per-model workers,
``AgentManager`` the agents. Every one of them is spawned with
``start_new_session=True`` so that a stop can signal the whole group -- and that
is exactly what makes them survive a restart of the service. A crash, an upgrade
or a ``systemctl restart`` takes the service process down and leaves the children
running, reparented to init: the new process holds no handle on them and
``/proc`` is its only way to find them. That is what the unit's
``KillMode=process`` exists for -- with systemd's default (or the ``mixed`` this
used to set) the workers would be SIGKILLed along with the service, so there
would never be a survivor to adopt, and a worker killed while it was executing
on the NPU can wedge the TPU until the board is rebooted.

A fresh manager that concludes "nothing is running" is wrong in a costly way. It
loads a second worker for a model that is already serving (two NPU heap
allocations, ~20 GB on this board), and it starts a second copy of an agent that
is already bound to its port. So the manager that comes up has to find those
processes, prove they are the ones it would have started itself, and reattach --
or refuse loudly, never treat them as idle.

Proving it is this module's job, and every rule here is a *rejection* rule:

* the command line must name the module or executable this service starts,
  from a path inside the tree this service owns;
* ``/proc/<pid>/cwd`` must be the directory this service starts it in;
* the executable must be the interpreter or binary the spec names, not merely a
  process with a similar ``argv``;
* ``/proc/<pid>/stat`` must not report a zombie.

An application-level health handshake (the worker's JSON ``health`` op, the
agent's authenticated ``/health``) is the last step, in the managers: passing
these checks means "this is ours", and the handshake means "it is still able to
serve". Neither alone is enough, which is why a candidate that fails the
handshake is reported as a conflict instead of being adopted *or* killed.

Nothing here signals a process: a pid we cannot prove we started is not ours to
signal, so the read-only helpers below are the only thing discovery uses.
``AdoptedProcess`` is the narrow ``PopenLike`` adapter that lets the managers
keep driving such a process (``wait``/``terminate``) through their existing code
paths; it deliberately has no way to reap one.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

#: What ``wait()`` reports for an adopted process. We did not fork it, so its
#: real exit status is not available to us -- only the fact that it is gone.
UNKNOWN_EXIT_CODE = -1

try:  # pragma: no cover - every Linux has it, but not every libc exposes it
    _CLOCK_TICKS = os.sysconf("SC_CLK_TCK")
except (AttributeError, ValueError):  # pragma: no cover
    _CLOCK_TICKS = 100


@dataclass
class ProcInfo:
    """One ``/proc/<pid>`` entry, read once.

    ``None`` in any field means the kernel refused or the entry vanished, which
    is a rejection reason rather than something to guess around: an unreadable
    ``cwd`` is how a process owned by another user looks, and adopting that
    would mean signalling a stranger.
    """

    pid: int
    argv: list[str]
    cwd: str | None = None
    exe: str | None = None
    start_time: float | None = None

    def __str__(self) -> str:
        return f"pid {self.pid} ({' '.join(self.argv[:3])})"


@runtime_checkable
class PopenLike(Protocol):
    """The part of ``asyncio.subprocess.Process`` the managers actually use.

    Narrow on purpose: the supervisors only need to know whether the process is
    still alive, how to signal it and how to await its death. ``AdoptedProcess``
    implements exactly this, so a reattached child and a freshly spawned one go
    through the same code path -- and a fake in a test does not have to pretend
    to be a real subprocess handle.
    """

    pid: int

    @property
    def returncode(self) -> int | None: ...

    def send_signal(self, sig: int) -> None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    async def wait(self) -> int: ...


# -- reading /proc ---------------------------------------------------------
def iter_pids() -> Iterator[int]:
    try:
        names = os.listdir("/proc")
    except OSError:  # pragma: no cover - no procfs: nothing to adopt anyway
        return
    for name in names:
        if name.isdigit():
            yield int(name)


def read_cmdline(pid: int) -> list[str]:
    """The process' argv, or ``[]`` when it cannot be read (kernel thread, gone)."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def _readlink(pid: int, name: str) -> str | None:
    try:
        target = os.readlink(f"/proc/{pid}/{name}")
    except OSError:
        return None
    # A binary that was replaced by an upgrade reads as "/path (deleted)"; the
    # path is still the identity we are matching, so drop the marker.
    suffix = " (deleted)"
    return target[: -len(suffix)] if target.endswith(suffix) else target


def read_cwd(pid: int) -> str | None:
    return _readlink(pid, "cwd")


def read_exe(pid: int) -> str | None:
    return _readlink(pid, "exe")


def _stat_fields(pid: int) -> list[str] | None:
    """``/proc/<pid>/stat`` split *after* the ``(comm)`` field.

    Splitting on whitespace is wrong here: the comm field is the executable name
    in parentheses and may itself contain spaces (``python3 -m`` and friends),
    which shifts every later field.
    """
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(errors="replace")
    except OSError:
        return None
    end = raw.rfind(")")
    if end < 0:
        return None
    return raw[end + 2 :].split()


def process_state(pid: int) -> str | None:
    fields = _stat_fields(pid)
    return fields[0] if fields else None


def read_start_time(pid: int) -> float | None:
    """When the process started, in seconds since boot.

    Used as a generation marker: a recycled pid belongs to a different process,
    and comparing start times is what keeps "is pid 4242 still my worker?" from
    answering yes for an unrelated process that inherited the number.

    Deliberately not an epoch time. ``btime + ticks`` looks like one, but the
    kernel derives ``btime`` from the current wall clock, so every process's
    "start time" moves when NTP steps the clock. CV84X6 boards keep no RTC time
    across power-off and step the clock by minutes once they reach an NTP
    server; the service then failed this comparison for its own worker, reported
    the model unloaded and left the worker holding the NPU (MYS-2293). The tick
    count is fixed for the life of the process.
    """
    fields = _stat_fields(pid)
    if not fields or len(fields) < 20:
        return None
    try:
        ticks = int(fields[19])  # field 22 of stat, 20 fields past "(comm) S"
    except (ValueError, IndexError):
        return None
    return ticks / _CLOCK_TICKS


def start_time_epoch(start_since_boot: float | None) -> float | None:
    """A ``read_start_time`` value as an epoch second, for display only.

    Computed against the clock as it reads now, so it is right for showing an
    uptime and wrong for comparing two readings across a clock step -- which is
    why identity checks never use it.
    """
    if start_since_boot is None:
        return None
    try:
        with open("/proc/uptime") as fh:
            uptime = float(fh.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return time.time() - (uptime - start_since_boot)


def process_alive(pid: int | None, expected_start: float | None = None) -> bool:
    """Whether ``pid`` is a live, non-zombie process -- optionally of one generation.

    A zombie is "dead" here on purpose: its parent never reaped it, so it holds
    no resources and cannot serve a request, and reporting it as running is the
    same lie as reporting a missing pid as running.
    """
    if not pid or pid <= 0:
        return False
    state = process_state(pid)
    if state is None or state in ("Z", "X", "x"):
        return False
    if expected_start is not None:
        started = read_start_time(pid)
        if started is None or abs(started - expected_start) > 1.0:
            return False
    return True


def read_environ(pid: int) -> dict[str, str] | None:
    """The process' environment, or ``None`` when it is not readable.

    ``None`` is not a rejection: on a hardened host ``/proc/<pid>/environ`` is
    root-only, and refusing every adoption because of that would make takeover
    depend on a sysctl. It is used as corroboration when it *is* readable.
    """
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return None
    env: dict[str, str] = {}
    for entry in raw.split(b"\0"):
        if b"=" not in entry:
            continue
        key, _, value = entry.partition(b"=")
        env[key.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
    return env


def same_path(a: str | os.PathLike | None, b: str | os.PathLike | None) -> bool:
    """Whether two paths name the same file, following symlinks on both sides."""
    if not a or not b:
        return False
    try:
        return Path(os.path.realpath(str(a))) == Path(os.path.realpath(str(b)))
    except (OSError, ValueError):
        return False


SERVICE_MODULE = ("-m", "app.main")


def service_instances(root: str | os.PathLike, *,
                      exclude_pid: int | None = None) -> list[ProcInfo]:
    """Other live copies of THIS service serving the same data root.

    Needed because "a previous run left processes behind" and "another copy is
    running right now" look identical from ``/proc`` and must not be treated the
    same way. Adopting a worker whose real owner is alive would have two
    managers driving one process: the console of one would report a model the
    other unloads, and a stop in either would signal a process the other is
    still using. So the caller refuses instead -- see ``ModelManager.adopt``
    and ``AgentManager.adopt``.

    Matched on the module plus the resolved data root (the ``--data-root``
    argument, or ``CV84X6_DATA_ROOT`` when the flag is absent), so a second
    instance on a different data root is correctly *not* a conflict: it owns
    different processes.
    """
    out: list[ProcInfo] = []
    for cand in scan_processes():
        if cand.pid == exclude_pid or cand.pid == os.getpid():
            continue
        if cand.argv[1:3] != list(SERVICE_MODULE):
            continue
        declared = arg_value(cand.argv, "--data-root")
        if declared is None:
            env = read_environ(cand.pid) or {}
            declared = env.get("CV84X6_DATA_ROOT") or ""
        if declared and same_path(declared, root):
            out.append(cand)
    return out


def scan_processes(pids: Iterator[int] | None = None) -> list[ProcInfo]:
    """Every process on the host that has a command line, with what we need.

    Four small reads per pid. On this board that is a few milliseconds, which is
    why the startup recovery may run it; nothing on a request path does.

    The scan inherently relies on ``/proc`` being mounted, so every read here
    degrades to "no evidence" rather than raising: nothing is adopted, and each
    manager reports what it cannot account for.
    """
    out: list[ProcInfo] = []
    for pid in pids if pids is not None else iter_pids():
        if pid == os.getpid():
            continue
        argv = read_cmdline(pid)
        if not argv:
            continue
        out.append(ProcInfo(
            pid=pid,
            argv=argv,
            cwd=read_cwd(pid),
            exe=read_exe(pid),
            start_time=read_start_time(pid),
        ))
    return out


def is_under(path: str | os.PathLike | None, root: str | os.PathLike) -> bool:
    """Whether ``path`` really lives in ``root``, following symlinks both ways.

    ``resolve``-based rather than a string prefix: a symlinked data root would
    otherwise make a perfectly legitimate worker look foreign, and a link
    pointing out of the tree would make a foreign one look legitimate.
    """
    if not path:
        return False
    try:
        target = Path(os.path.realpath(str(path)))
        base = Path(os.path.realpath(str(root)))
    except (OSError, ValueError):
        return False
    return target == base or base in target.parents


def arg_value(argv: list[str], flag: str) -> str | None:
    """The token after ``flag``, or ``None`` when the flag is absent."""
    try:
        index = argv.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(argv):
        return None
    return argv[index + 1]


def looks_like_python(path: str | None) -> bool:
    """Whether ``path`` is a Python interpreter, not merely something with a
    command line that mentions one."""
    if not path:
        return False
    return Path(path).name.split(".")[0].startswith("python")


def signal_group(pid: int, sig: int) -> None:
    """Send ``sig`` to the group led by ``pid``, falling back to the process.

    Two guards, both about not killing the wrong thing:

    * ``pid <= 0`` is refused outright. ``kill(0, sig)`` and ``kill(-1, sig)``
      are not "a process" -- they mean *this process group* / *every process we
      may signal* -- so one bad pid would take this service down with it.
    * a pid whose group is *our* group (a process that was not started with
      ``start_new_session``, or a recycled pid) is signalled as a bare process,
      never with ``killpg``.
    """
    if not pid or int(pid) <= 0:
        logger.error("refusing to signal pid %r: not a process id", pid)
        return
    pid = int(pid)
    try:
        pgid = os.getpgid(pid)
    except OSError:
        pgid = None
    try:
        if pgid is not None and pgid != os.getpgrp():
            os.killpg(pgid, sig)
        else:
            os.kill(pid, sig)
    except ProcessLookupError:
        pass


class AdoptedProcess:
    """A live process this manager reattached to instead of spawning.

    Implements :class:`PopenLike` so the load/unload and start/stop paths keep
    working unchanged, with two deliberate limitations:

    * its exit status is unknown (``wait`` returns ``UNKNOWN_EXIT_CODE``) --
      we are not its parent, so nobody hands us a ``waitpid`` status;
    * ``kill`` can be refused. A model worker holds NPU memory, and force-killing
      one mid-prefill is what leaves the TPU busy until a reboot, so the model
      manager's adopted handles refuse SIGKILL and report the refusal instead.
      An agent may be killed (``allow_kill``), because a hung agent is exactly
      what "stop" is for.
    """

    adopted = True

    def __init__(self, pid: int, *, allow_kill: bool = False,
                 start_time: float | None = None) -> None:
        self.pid = int(pid)
        self.allow_kill = bool(allow_kill)
        #: The generation this handle is bound to (see ``read_start_time``).
        self.start_time = start_time if start_time is not None else read_start_time(pid)
        self._returncode: int | None = None

    @property
    def returncode(self) -> int | None:
        if self._returncode is None and not process_alive(self.pid, self.start_time):
            self._returncode = UNKNOWN_EXIT_CODE
        return self._returncode

    def send_signal(self, sig: int) -> None:
        if self.returncode is not None:
            return
        signal_group(self.pid, sig)

    def terminate(self) -> None:  # SIGTERM, the graceful one
        self.send_signal(signal.SIGTERM)

    def kill(self) -> None:
        if not self.allow_kill:
            logger.error(
                "refusing to SIGKILL pid %d: this process was adopted after a restart, "
                "not spawned by this run (a mid-prefill kill can wedge the NPU)", self.pid)
            return
        self.send_signal(signal.SIGKILL)

    async def wait(self, poll_s: float = 0.2) -> int:
        while process_alive(self.pid, self.start_time):
            await asyncio.sleep(poll_s)
        self._returncode = UNKNOWN_EXIT_CODE
        return self._returncode
