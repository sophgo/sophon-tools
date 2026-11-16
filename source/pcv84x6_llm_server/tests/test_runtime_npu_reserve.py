"""The runtime budget must hold the same floor the load check does (MYS-2784).

MYS-2703 put a 1 GiB floor on the *load* path: a model may only be loaded if
the NPU heap still has ``CV84X6_NPU_RESERVE_MB`` free afterwards. That fixed the
configuration that wedged (six models, 280 MiB free), and it is still right.

It is not sufficient, because a chat model's footprint is not a constant. The
worker is handed a *runtime* budget -- the bytes its parked sessions and prefix
cache may take after the load -- and that budget used to be

    free-after-load - 512 MiB          (NPU_SAFETY_BYTES)

512 MiB is the value MYS-2703 measured as **already wedged** (`~280 MiB` and
`512 MiB` both wedged; `640 MiB` was the first clean point). So a load could
pass the 1 GiB admission check and then, the moment sessions parked, walk the
heap straight back down through the band the check exists to avoid.

Measured on `.151` (24 GiB NPU heap, 35B-A3B 128k, MYS-2784): the load left
1567 MiB free, the worker took a 1056 MiB budget, two 17.7k-token sessions ran
concurrently, and the heap went 1567 -> 1024 -> **327** -> **2 MiB** free. That
is below every point in the MYS-2703 sweep. The board did not wedge on the run
I could observe, but it was sitting in the interval that wedged in 7/8 of
MYS-2693's trials, and the customer's own capture shows the wedge at 121 s.

The rule these tests pin:

* the runtime budget is ``free-after-load - reserve`` with the *same* reserve
  the load check uses (``npu_reserve_bytes()``), not a second, smaller constant;
* the reserve is read from the worker's own environment, so one variable
  configures both halves -- a board that raises the floor for its own reasons
  gets both, and `0` turns both off;
* a per-model memory limit still bounds it from above: the reserve is a floor on
  headroom, not permission to exceed an operator's ceiling;
* the budget never goes negative, and zero stays a legitimate answer (the
  scheduler admits a lone session against it).
"""

from __future__ import annotations

import pytest

from app.engine.worker import (
    NPU_SAFETY_BYTES,
    npu_cache_cap,
    npu_kv_budget,
    npu_runtime_reserve_bytes,
)
from app.core.models import NPU_RESERVE_DEFAULT_BYTES, NPU_RESERVE_ENV

MIB = 1 << 20


class _Backend:
    """Just enough backend for the two budget functions."""

    def __init__(self, per_tok: int = 20480, session_state: int = 33423360) -> None:
        self.kv_bytes_per_token = per_tok
        self.session_state_bytes = session_state
        self.context_length = 131072


def _smi(monkeypatch, total_mb: int, used_mb: int) -> None:
    from app.core import monitor

    monkeypatch.setattr(monitor, "bm_smi_sample", lambda: {
        "mem_total_bytes": total_mb * MIB,
        "mem_used_bytes": used_mb * MIB,
    })


# ---------------------------------------------------------------------------
# the reserve itself
# ---------------------------------------------------------------------------
def test_the_runtime_reserve_is_the_load_time_reserve(monkeypatch):
    """One number configures both halves of the D7 guard.

    Two constants is how they drifted apart in the first place: the load path
    was raised to 1 GiB in MYS-2703 and the runtime path kept the 512 MiB it had
    been measured at. Reading the same variable makes that impossible.
    """
    monkeypatch.delenv(NPU_RESERVE_ENV, raising=False)
    assert npu_runtime_reserve_bytes() == NPU_RESERVE_DEFAULT_BYTES
    monkeypatch.setenv(NPU_RESERVE_ENV, "640")
    assert npu_runtime_reserve_bytes() == 640 * MIB
    # 0 is the documented "this board does not have this problem" switch.
    monkeypatch.setenv(NPU_RESERVE_ENV, "0")
    assert npu_runtime_reserve_bytes() == 0
    # A typo falls back to the default rather than raising: this is read on the
    # worker's start-up path, and refusing to boot a worker because an env var
    # is malformed would take a working model down.
    monkeypatch.setenv(NPU_RESERVE_ENV, "not-a-number")
    assert npu_runtime_reserve_bytes() == NPU_RESERVE_DEFAULT_BYTES


def test_the_default_runtime_reserve_is_above_the_measured_cliff():
    """Not 512 MiB: that figure is in the measured *wedged* band.

    MYS-2703 swept the floor and found 280 MiB and 512 MiB wedged, 640 MiB and
    1024 MiB clean. `NPU_SAFETY_BYTES` is therefore exactly the wrong default
    for this, which is what made the runtime path the hole.
    """
    assert NPU_SAFETY_BYTES == 512 * MIB  # the old constant, kept for the record
    assert NPU_RESERVE_DEFAULT_BYTES > NPU_SAFETY_BYTES
    assert NPU_RESERVE_DEFAULT_BYTES > 640 * MIB


# ---------------------------------------------------------------------------
# the budget the scheduler admits against
# ---------------------------------------------------------------------------
def test_the_session_budget_holds_back_the_reserve(monkeypatch):
    """Free after load minus the reserve -- the room sessions may actually take."""
    monkeypatch.delenv(NPU_RESERVE_ENV, raising=False)
    # .151 after loading the 35B: 25501368320 total, 23857410048 used.
    _smi(monkeypatch, total_mb=24320, used_mb=22752)
    got = npu_kv_budget(_Backend())
    assert got == (24320 - 22752) * MIB - NPU_RESERVE_DEFAULT_BYTES
    assert got == (1568 - 1024) * MIB


def test_the_old_constant_would_have_handed_out_the_wedged_band(monkeypatch):
    """The regression, stated as a number.

    This is what the worker used to compute, and why two concurrent 17.7k
    sessions could walk the heap to 2 MiB free: 1568 - 512 = 1056 MiB of budget
    on a heap that then had 1024 MiB of real headroom before the floor.
    """
    monkeypatch.delenv(NPU_RESERVE_ENV, raising=False)
    _smi(monkeypatch, total_mb=24320, used_mb=22752)
    old = (24320 - 22752) * MIB - NPU_SAFETY_BYTES
    new = npu_kv_budget(_Backend())
    assert old == 1056 * MIB
    assert new == 544 * MIB
    assert old - new == NPU_RESERVE_DEFAULT_BYTES - NPU_SAFETY_BYTES


def test_a_heap_that_cannot_afford_the_reserve_gives_no_budget(monkeypatch):
    """Zero, never negative: ``_fits`` admits a lone session against a zero
    budget, and a negative one would make even that arithmetic nonsense."""
    monkeypatch.delenv(NPU_RESERVE_ENV, raising=False)
    _smi(monkeypatch, total_mb=24320, used_mb=24320 - 200)  # 200 MiB free
    assert npu_kv_budget(_Backend()) == 0


def test_the_reserve_can_be_disabled_for_a_board_without_the_failure(monkeypatch):
    monkeypatch.setenv(NPU_RESERVE_ENV, "0")
    _smi(monkeypatch, total_mb=24320, used_mb=22752)
    assert npu_kv_budget(_Backend()) == 1568 * MIB


def test_the_cache_cap_holds_back_the_reserve_too(monkeypatch):
    """The cache cap and the session budget must not disagree.

    ``npu_cache_cap`` is the fallback used when a worker has no per-model limit;
    it reserved ``max_concurrent * session_state + NPU_SAFETY_BYTES``. Leaving it
    on the old constant would let the prefix cache fill the headroom the floor
    is meant to keep, which is the same bug by the other door.
    """
    monkeypatch.delenv(NPU_RESERVE_ENV, raising=False)
    _smi(monkeypatch, total_mb=24320, used_mb=22752)
    backend = _Backend()
    got = npu_cache_cap(backend, max_concurrent=2)
    assert got == (1568 * MIB - 2 * backend.session_state_bytes
                   - NPU_RESERVE_DEFAULT_BYTES)


def test_a_backend_without_per_token_kv_has_no_budget(monkeypatch):
    """Mock and pre-v0.5 libraries: no answer rather than a wrong one."""
    monkeypatch.delenv(NPU_RESERVE_ENV, raising=False)
    _smi(monkeypatch, total_mb=24320, used_mb=22752)
    assert npu_kv_budget(_Backend(per_tok=0, session_state=0)) is None
    assert npu_cache_cap(_Backend(per_tok=0, session_state=0), 2) is None
