"""The systemd unit's stop semantics: only the service process, never workers.

Why this is its own file: ``KillMode`` is the difference between "takeover
works" and "takeover can never work", and the failure is silent. Under
``KillMode=mixed`` systemd SIGKILLs the whole cgroup when the main process dies.
Workers are started in their own session precisely so they outlive the service
(``app/core/procs.py`` reattaches to them on the next start), so `mixed` made
every known survivor unreachable: a `kill -9` of the main process took the
workers with it within a second, and the restart found nothing to adopt.

The dangerous half is worse than the useless half. A worker killed by SIGKILL
while it is executing on the NPU leaves the core wedged: on the 10155 board that
showed up as 15 `wait api timeout` lines in dmesg, a TPU core pinned at 100 %,
and nothing short of `systemctl reboot --force --force` recovering it.

So the unit is checked as text, and the check is deliberately about the value
rather than about the comment above it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNIT = ROOT / "deploy" / "cv84x6-llm.service"


def _directive(name: str) -> str | None:
    """The unit's value for ``name``, ignoring comments and blank lines."""
    for line in UNIT.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        if stripped.startswith(f"{name}="):
            return stripped.split("=", 1)[1].strip()
    return None


def test_the_unit_exists_where_the_installer_expects_it():
    """``scripts/install.sh`` substitutes this file; a rename would break it."""
    assert UNIT.is_file(), f"{UNIT} is missing"
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert "deploy/cv84x6-llm.service" in install, (
        "install.sh no longer references the unit template it fills in")


def test_kill_mode_is_process_so_workers_survive_a_crash():
    """Only the main process is signalled.

    ``process`` is the whole point: workers keep running when the service dies,
    so the next start can adopt them instead of loading a second copy of the
    weights -- and a crash during inference does not SIGKILL a worker that is
    mid-launch, which is what wedges the TPU.
    """
    mode = _directive("KillMode")
    assert mode == "process", (
        f"KillMode={mode!r}; it must be 'process'. 'mixed' (the old value) "
        "SIGKILLs the workers, which both defeats takeover and can hang the TPU "
        "when a worker dies mid-inference")


def test_kill_mode_is_not_silently_left_at_systemds_default():
    """The default is ``control-group``, which is the same failure as ``mixed``.

    Stated separately because "the line is absent" also means "the workers get
    killed": an absent directive is not a neutral choice here.
    """
    assert _directive("KillMode") is not None, (
        "the unit sets no KillMode, so systemd's default (control-group) applies "
        "and every worker is SIGKILLed with the service")


def test_the_stop_timeout_covers_a_graceful_unload():
    """Long enough for the service's own shutdown to unload and exit.

    The service stops its workers one at a time (each unload is a SIGTERM plus a
    wait), and the worker's own grace is 120 s. A ``TimeoutStopSec`` shorter than
    that turns a slow-but-healthy stop into a SIGKILL of the main process, which
    is exactly the situation this unit is trying to avoid.
    """
    value = _directive("TimeoutStopSec")
    assert value is not None, "TimeoutStopSec must be stated explicitly"
    seconds = int(value.rstrip("s"))
    assert seconds >= 120, (
        f"TimeoutStopSec={seconds}s is below the worker's own 120 s grace; a "
        "slow unload would be SIGKILLed instead of waited for")


def test_the_unit_still_restarts_the_service():
    """Takeover only matters if the service comes back by itself."""
    assert _directive("Restart") == "on-failure", _directive("Restart")
    assert int(_directive("RestartSec").rstrip("s")) > 0


def test_the_unit_does_not_use_the_removed_mixed_value():
    """A regression guard with the old value spelled out.

    ``test_kill_mode_is_process_so_workers_survive_a_crash`` already fails on
    ``mixed``; this one names the old value so a future reader searching for it
    finds the reason it was removed rather than a bare "expected 'process'".
    """
    text = UNIT.read_text(encoding="utf-8")
    live = [line for line in text.splitlines()
            if line.strip().startswith("KillMode=")]
    assert live, "no KillMode directive at all"
    assert not re.search(r"KillMode\s*=\s*mixed", "\n".join(live)), (
        "KillMode=mixed is back; see this module's docstring for what it broke")
