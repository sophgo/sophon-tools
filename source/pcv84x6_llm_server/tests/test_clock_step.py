"""A wall-clock step must not change who a process is (MYS-2293).

CV84X6 boards keep no RTC time across power-off: the clock starts from a stale
timestamp and systemd-timesyncd steps it forward by minutes once the board
reaches an NTP server. The kernel derives /proc/stat ``btime`` from the current
wall clock, so ``btime + start ticks`` moved with the step; the service then
decided its own freshly loaded worker was "gone", reported the model unloaded,
and left the worker holding the NPU (the next load failed in bm_alloc_gmem).

The tests simulate exactly that kernel behaviour: ``btime`` jumps, nothing else
changes.
"""

from __future__ import annotations

import builtins
import io
import os
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from app.core import procs
from app.main import create_app
from tests.test_operation_state import make_model, model_of

STEP_S = 360  # the step seen on the board: about six minutes forward


@pytest.fixture()
def clock_step(monkeypatch):
    """Return a function that steps the simulated wall clock forward."""
    real_open = builtins.open
    shift = {"s": 0}

    def fake_open(file, *args, **kwargs):
        if str(file) == "/proc/stat":
            with real_open(file, *args, **kwargs) as fh:
                text = fh.read()
            lines = []
            for line in text.splitlines():
                if line.startswith("btime "):
                    line = f"btime {int(line.split()[1]) + shift['s']}"
                lines.append(line)
            return io.StringIO("\n".join(lines) + "\n")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)

    def step(seconds: int = STEP_S) -> None:
        shift["s"] += seconds

    return step


def test_a_process_keeps_its_identity_across_a_clock_step(clock_step):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        started = procs.read_start_time(child.pid)
        assert started is not None
        clock_step()
        assert procs.read_start_time(child.pid) == started
        assert procs.process_alive(child.pid, started) is True
    finally:
        child.kill()
        child.wait()


def test_a_recycled_pid_is_still_told_apart():
    """The marker still distinguishes generations: a different start is refused."""
    started = procs.read_start_time(os.getpid())
    assert procs.process_alive(os.getpid(), started) is True
    assert procs.process_alive(os.getpid(), started - 5.0) is False


def test_start_time_epoch_is_for_display():
    # The full suite can already have run for >10 minutes by this point.
    # Use a fresh process so this checks epoch conversion, not suite duration.
    child = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
                             stdin=subprocess.PIPE)
    try:
        started = procs.read_start_time(child.pid)
        epoch = procs.start_time_epoch(started)
        assert epoch is not None and 0 <= time.time() - epoch < 600
    finally:
        child.communicate(timeout=10)
    assert procs.start_time_epoch(None) is None


def test_a_loaded_model_stays_loaded_across_a_clock_step(tmp_path, clock_step):
    """The board's failure end to end: load, step the clock, ask again."""
    models = tmp_path / "models"
    make_model(models, "m")
    app = create_app(data_dir=tmp_path / "data", models_dir=models, backend_kind="mock",
                     web_dir=tmp_path / "web", context_length_override=4096)
    with TestClient(app) as c:
        c.post("/api/login", json={"password": "admin"})
        assert c.post("/api/models/m/load").status_code == 200
        before = model_of(c)
        assert before["loaded"] is True and before["pid"]

        clock_step()

        after = model_of(c)
        assert after["loaded"] is True, after
        assert after["pid"] == before["pid"]
        assert after["load_error"] is None
        # Requests still reach the same worker.
        key = c.post("/api/keys", json={"name": "k"}).json()["key"]
        r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                   json={"model": "m", "messages": [{"role": "user", "content": "hi"}],
                         "max_tokens": 4})
        assert r.status_code == 200, r.text
        # A second load is the idempotent no-op, not a second worker.
        assert c.post("/api/models/m/load").status_code == 200
        assert model_of(c)["pid"] == before["pid"]
