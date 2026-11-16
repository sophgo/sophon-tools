"""A worker that survives SIGTERM must not read as "unloaded" (MYS-2784).

The customer's third failure (MYS-2784, .151 with 0.6.30) went like this: an
unload of the 35B took 130 s, the platform log said the worker was not stopped by
SIGTERM, the next two loads failed with ``bmrt_load_bmodel failed (wrong chip or
corrupt file?)``, and the API then answered 409 because the model was not loaded.

130 s is the unload grace exactly (120 s SIGTERM + 10 s SIGKILL), and the reason
it was reached is the D7 wedge: the worker's NPU session was stuck in
``bmdrv_thread_sync_api`` and nothing it could do would return. That part is
fixed by holding the headroom floor (``app/engine/worker.py``).

What this file is about is the second half: what the *manager* does when the
grace runs out. ``_terminate`` records a ``conflict`` saying the pid survived --
and then ``unload`` calls ``_forget`` on the next line, which clears
``conflict`` along with ``loaded``/``pid``/``port``. So the model read as cleanly
unloaded while a process was still holding 22 GiB of NPU heap, and the next load
happily spawned a second worker into that hole. ``bmrt_load_bmodel failed`` is
what the second worker sees when it cannot map its weights.

The rule these tests pin: a survivor is reported, not forgotten. The model must
stay in ``conflict`` with the surviving pid recorded, so that

* the next load is refused with the survivor named, instead of starting a second
  worker (``ModelConflict``);
* the operator still has a button that can reach that pid (``unload`` re-runs
  the conflict termination), instead of a model that reads idle with a stranger
  holding the heap.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core import procs
from app.core.models import KILL_GRACE_S, UNLOAD_GRACE_S, ModelConflict, ModelManager


class _Proc:
    """A worker process that never returns from ``wait()``.

    Stands in for the wedged worker: 130 s is exactly ``UNLOAD_GRACE_S + KILL_
    GRACE_S``, and the only property that matters to ``_terminate`` is that
    neither wait ever completes.
    """

    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self.returncode = None
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        # A real SIGKILL always ends the process; this one refuses so the
        # survivor path stays reachable at a millisecond grace.
        self.returncode = None

    async def wait(self) -> int:
        await asyncio.sleep(3600)
        return 0


def _manager(tmp_path) -> ModelManager:
    models = tmp_path / "models"
    d = models / "chat"
    d.mkdir(parents=True)
    with open(d / "chat.bmodel", "wb") as f:
        f.truncate(1024)
    mgr = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()
    return mgr


@pytest.fixture(autouse=True)
def short_grace(monkeypatch):
    """The 120 s + 10 s grace is the customer's 130 s; do not wait it out."""
    monkeypatch.setattr("app.core.models.UNLOAD_GRACE_S", 0.01)
    monkeypatch.setattr("app.core.models.KILL_GRACE_S", 0.01)


@pytest.mark.asyncio
async def test_the_grace_is_the_number_the_customer_reported():
    """130 s = 120 s SIGTERM + 10 s SIGKILL, which is what "卸载耗时 130 秒" was."""
    assert UNLOAD_GRACE_S + KILL_GRACE_S == 130


@pytest.mark.asyncio
async def test_a_survivor_keeps_the_model_in_conflict(tmp_path, monkeypatch):
    """``_forget`` must not erase the reason ``_terminate`` just recorded."""
    monkeypatch.setattr(procs, "process_alive", lambda pid, started=None: True)
    mgr = _manager(tmp_path)
    info = mgr.get("chat")
    info.loaded = True
    info.pid = 4242
    info.port = 12345
    proc = _Proc()
    mgr._procs["chat"] = proc

    await mgr.unload("chat")

    assert proc.terminated and proc.killed, "the grace and the kill must both run"
    # The load must be refused, naming the pid, rather than spawning a second
    # worker into a heap the survivor still holds.
    assert info.conflict, "a worker that survived the grace is a conflict, not an unload"
    assert "4242" in info.conflict
    with pytest.raises(ModelConflict):
        await mgr.load("chat")


@pytest.mark.asyncio
async def test_a_clean_stop_leaves_no_conflict(tmp_path, monkeypatch):
    """The other half: do not manufacture a conflict for a worker that exited."""
    monkeypatch.setattr(procs, "process_alive", lambda pid, started=None: True)
    mgr = _manager(tmp_path)
    info = mgr.get("chat")
    info.loaded = True
    info.pid = 4242
    info.port = 12345

    class _Polite(_Proc):
        async def wait(self) -> int:
            self.returncode = 0
            return 0

    mgr._procs["chat"] = _Polite()
    await mgr.unload("chat")

    assert not info.conflict
    assert not info.loaded
    assert info.pid is None


@pytest.mark.asyncio
async def test_a_clean_stop_leaves_no_conflict(tmp_path, monkeypatch):
    """The other half: do not manufacture a conflict for a worker that exited."""
    monkeypatch.setattr(procs, "process_alive", lambda pid, started=None: True)
    mgr = _manager(tmp_path)
    info = mgr.get("chat")
    info.loaded = True
    info.pid = 4242
    info.port = 12345

    class _Polite(_Proc):
        async def wait(self) -> int:
            self.returncode = 0
            return 0

    mgr._procs["chat"] = _Polite()
    await mgr.unload("chat")

    assert not info.conflict
    assert not info.loaded
    assert info.pid is None
