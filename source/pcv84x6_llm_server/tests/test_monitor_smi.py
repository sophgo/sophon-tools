"""Device memory (NPU + VPP) and TPU utilisation -- and the frequency, gone.

Three separate contracts, all measured on `.157` (docs/device-memory.md):

* **Device memory is both ion carveout heaps.** bmrt allocates through bmlib
  with a heap mask covering NPU and VPP, and spills into VPP by itself when NPU
  is full -- so a capacity question asked of the NPU heap alone gets the wrong
  answer, in the direction that refuses loads which would have worked.
* **A single block cannot span heaps.** Summing the two heaps is not enough to
  admit a load: 1.5 GiB free in each cannot take a 3 GiB bmodel.
* **TPU utilisation replaces the frequency.** The driver's `npu_usage` counters
  move (0 idle -> 90-96 during a 35B decode); the old code read a *frequency*
  from a sysfs node the DVFS driver no longer scales usefully, and its
  bm-smi fallback read a utilisation column as MHz.
"""

from __future__ import annotations

import ctypes
from pathlib import Path

import pytest

from app.core import monitor
from app.core.monitor import (
    SOURCE_BMLIB,
    SOURCE_ION,
    SOURCE_MOCK,
    SOURCE_NONE,
    SOURCE_SYSFS,
    device_memory,
    parse_bm_smi,
    tpu_usage,
)

DATA = Path(__file__).parent / "data"
IDLE_DUMP = (DATA / "bm_smi_noloop_cv84x6_idle.txt").read_bytes()

# A busy board's card row: the same line with tpuc at 100% (``100M``) instead of
# ``0M``, which is what made the old parser report "current 100 MHz" under load.
BUSY_DUMP = IDLE_DUMP.replace(b"Active\x1b[6C0M", b"Active\x1b[6C100M")

#: A real `npu_usage` dump from `.157`, idle and during a 35B decode.
IDLE_USAGE = """\
usage:0 avusage:2
core0 npu usage : 0        average: 0
core1 npu usage : 0        average: 0
core2 npu usage : 0        average: 0
core3 npu usage : 0        average: 0
"""
BUSY_USAGE = """\
usage:94 avusage:3
core0 npu usage : 100        average: 4
core1 npu usage : 94        average: 3
core2 npu usage : 94        average: 3
core3 npu usage : 94        average: 3
"""


@pytest.fixture(autouse=True)
def no_bmlib(monkeypatch):
    """No real libbmlib in a host test; each test opts in to what it needs."""
    monkeypatch.setattr(monitor, "_libmgr", {"tried": True, "lib": None})
    monkeypatch.setattr(monitor, "_SIMULATE",
                        {"on": False, "loaded_bytes": 0, "tick": 0})
    monkeypatch.setattr(monitor, "_smi_cache", (0.0, {}))
    monkeypatch.setattr(monitor, "NPU_USAGE", Path("/nonexistent/npu_usage"))
    monkeypatch.setattr(monitor, "NPU_USAGE_ENABLE",
                        Path("/nonexistent/npu_usage_enable"))
    monkeypatch.setattr(monitor, "ION_HEAPS", Path("/nonexistent/ion"))
    yield


def _fake_heaps(monkeypatch, heaps):
    """Make bmlib return ``[(name, total, used), ...]``."""
    monkeypatch.setattr(monitor, "_heaps_from_bmlib", lambda: [
        {"name": name, "total_bytes": total, "used_bytes": used,
         "free_bytes": total - used}
        for name, total, used in heaps])


# -- bm-smi: memory only, never a frequency ---------------------------------

def test_parses_real_cv84x6_dump():
    out = parse_bm_smi(IDLE_DUMP)
    # Captured on MYS-2282 (CV84X6, libsophon 0.4.15), idle TPU.
    assert out["tpu_min_clock_mhz"] == 25
    assert out["tpu_max_clock_mhz"] == 1000
    assert out["mem_total_bytes"] == 24320 * 1024 * 1024
    assert out["mem_used_bytes"] == 0


def test_the_card_row_m_value_is_utilisation_not_a_frequency():
    """``0M`` in the card row is tpuc; keeping it out of any frequency-shaped
    key is the whole fix -- a caller that wants a clock must get one elsewhere."""
    idle = parse_bm_smi(IDLE_DUMP)
    assert idle["tpu_util_percent"] == 0
    assert "tpu_clock_mhz" not in idle

    busy = parse_bm_smi(BUSY_DUMP)
    assert busy["tpu_util_percent"] == 100
    assert "tpu_clock_mhz" not in busy
    # Min/max are untouched by load; they are limits, not measurements.
    assert busy["tpu_min_clock_mhz"] == 25
    assert busy["tpu_max_clock_mhz"] == 1000


def test_garbage_yields_empty():
    assert parse_bm_smi(b"no card here") == {}


# -- device memory ----------------------------------------------------------

def test_device_memory_is_both_heaps_summed(monkeypatch):
    _fake_heaps(monkeypatch, [("npu", 26624 << 20, 20000 << 20),
                              ("vpp", 2048 << 20, 1000 << 20)])
    out = device_memory()
    assert out["total_bytes"] == (26624 + 2048) << 20
    assert out["used_bytes"] == (20000 + 1000) << 20
    assert out["free_bytes"] == (6624 + 1048) << 20
    assert out["source"] == SOURCE_BMLIB
    assert [h["name"] for h in out["heaps"]] == ["npu", "vpp"]


def test_the_largest_block_is_bounded_by_one_heap_not_the_sum(monkeypatch):
    """A single allocation cannot span heaps, so the sum overstates what fits.

    This is the case that matters: 1.5 GiB free in each heap is 3 GiB of *free
    memory* and only 1.5 GiB of *allocatable* memory.
    """
    _fake_heaps(monkeypatch, [("npu", 26624 << 20, (26624 - 1536) << 20),
                              ("vpp", 2048 << 20, (2048 - 1536) << 20)])
    out = device_memory()
    assert out["free_bytes"] == 3072 << 20
    assert out["max_block_bytes"] == 1536 << 20


def test_an_unreadable_device_reports_none_rather_than_zero(monkeypatch):
    out = device_memory()
    assert out["heaps"] == []
    assert out["total_bytes"] == 0
    assert out["source"] == SOURCE_NONE
    # max() over nothing is 0, not an error: the admission check treats an empty
    # heap list as "no device to ask" and skips.
    assert out["max_block_bytes"] == 0


def test_ion_is_the_fallback_when_bmlib_is_missing(monkeypatch, tmp_path):
    """A board where libbmlib cannot be loaded still has the ion dump."""
    for name, total, used in (("npu", 100 << 20, 40 << 20),
                              ("vpp", 20 << 20, 5 << 20)):
        heap = tmp_path / f"cvi_{name}_heap_dump"
        heap.mkdir()
        (heap / "total_mem").write_text(str(total))
        (heap / "alloc_mem").write_text(str(used))
    monkeypatch.setattr(monitor, "ION_HEAPS", tmp_path)
    out = device_memory()
    assert out["source"] == SOURCE_ION
    assert out["total_bytes"] == 120 << 20
    assert out["used_bytes"] == 45 << 20
    assert {h["name"] for h in out["heaps"]} == {"npu", "vpp"}


def test_ion_heap_names_are_normalised(monkeypatch, tmp_path):
    """`cvi_npu_heap_dump` is the directory; `npu` is the heap."""
    heap = tmp_path / "cvi_npu_heap_dump"
    heap.mkdir()
    (heap / "total_mem").write_text("100")
    (heap / "alloc_mem").write_text("10")
    monkeypatch.setattr(monitor, "ION_HEAPS", tmp_path)
    assert "npu" in monitor.ion_heap_bytes()
    assert "cvi_npu_heap_dump" not in monitor.ion_heap_bytes()


def test_bmlib_is_preferred_over_ion(monkeypatch, tmp_path):
    heap = tmp_path / "cvi_npu_heap_dump"
    heap.mkdir()
    (heap / "total_mem").write_text("100")
    (heap / "alloc_mem").write_text("10")
    monkeypatch.setattr(monitor, "ION_HEAPS", tmp_path)
    _fake_heaps(monkeypatch, [("npu", 500, 100)])
    assert device_memory()["source"] == SOURCE_BMLIB


# -- TPU utilisation --------------------------------------------------------

def _usage_file(tmp_path, monkeypatch, text):
    path = tmp_path / "npu_usage"
    path.write_text(text)
    monkeypatch.setattr(monitor, "NPU_USAGE", path)


def test_idle_reports_zero(tmp_path, monkeypatch):
    _usage_file(tmp_path, monkeypatch, IDLE_USAGE)
    out = tpu_usage()
    assert out["percent"] == 0
    assert out["cores"] == [0, 0, 0, 0]
    assert out["source"] == SOURCE_SYSFS


def test_a_busy_board_reports_high_and_per_core(tmp_path, monkeypatch):
    """The numbers are from a real 35B decode on `.157` (docs/device-memory.md §5)."""
    _usage_file(tmp_path, monkeypatch, BUSY_USAGE)
    out = tpu_usage()
    assert out["percent"] == 94
    assert out["cores"] == [100, 94, 94, 94]
    # `avusage` is the since-enable average and must not be mistaken for the
    # current value -- reporting 3 while the TPU is at 94 % would be a lie.
    assert out["percent"] != 3


def test_utilisation_is_not_a_clock(tmp_path, monkeypatch):
    """The regression this replaced: no MHz anywhere in the payload."""
    _usage_file(tmp_path, monkeypatch, BUSY_USAGE)
    out = tpu_usage()
    assert not any("mhz" in key.lower() or "hz" in key.lower() for key in out)


def test_an_unreadable_node_reports_none(tmp_path, monkeypatch):
    out = tpu_usage()
    assert out["percent"] is None
    assert out["cores"] == []
    assert out["source"] == SOURCE_NONE


def test_a_driver_that_says_enable_yourself_yields_nothing(tmp_path, monkeypatch):
    """Before `npu_usage_enable=1` the driver prints a sentence, not numbers."""
    _usage_file(tmp_path, monkeypatch, "Please, set [Usage enable] to 1\n")
    out = tpu_usage()
    assert out["percent"] is None
    assert out["cores"] == []


def test_the_enable_knob_is_written_only_when_it_is_not_already_on(tmp_path,
                                                                  monkeypatch):
    _usage_file(tmp_path, monkeypatch, IDLE_USAGE)
    knob = tmp_path / "npu_usage_enable"
    knob.write_text('"enable": 0')
    monkeypatch.setattr(monitor, "NPU_USAGE_ENABLE", knob)
    assert tpu_usage()["percent"] == 0
    assert knob.read_text() == "1"


def test_an_already_enabled_knob_is_not_rewritten(tmp_path, monkeypatch):
    """Writing it every 2 s from the stats poll would be a pointless ioctl."""
    _usage_file(tmp_path, monkeypatch, IDLE_USAGE)

    class _Refuses:
        def exists(self):
            return True

        def read_text(self):
            return '"enable": 1'

        def write_text(self, _):
            raise AssertionError("must not rewrite an enabled knob")

    monkeypatch.setattr(monitor, "NPU_USAGE_ENABLE", _Refuses())
    assert tpu_usage()["percent"] == 0


# -- the frequency is gone --------------------------------------------------

def test_the_frequency_probe_reports_nothing():
    """Kept for one release so old clients do not KeyError; it never invents a
    value, and it points at its replacement."""
    out = monitor.tpu_frequency()
    assert out["mhz"] is None
    assert out["source"] == SOURCE_NONE
    assert out["deprecated"] is True
    assert out["use"] == "tpu_usage"


def test_the_tpu_clock_register_is_no_longer_read():
    """`clocks()` used to carry `tpu_hz`; a permanently-empty field invites a
    client to render "0 GHz", so the key is gone."""
    assert "tpu_hz" not in monitor.clocks()


def test_the_snapshot_no_longer_carries_a_frequency_value(tmp_path, monkeypatch):
    _usage_file(tmp_path, monkeypatch, BUSY_USAGE)
    snap = monitor.snapshot()
    assert snap["tpu_freq"]["mhz"] is None
    assert "tpu_hz" not in snap["clocks"]
    # The new fields are present and populated.
    assert snap["tpu_usage"]["percent"] == 94
    assert "device_mem" in snap


# -- the simulated backend --------------------------------------------------

def test_mock_reports_both_heaps_and_a_moving_usage(monkeypatch):
    """The console is built against `--backend mock`; it needs both fields."""
    monkeypatch.setattr(monitor, "_SIMULATE",
                        {"on": True, "loaded_bytes": 0, "tick": 0})
    idle = monitor.device_memory()
    assert idle["source"] == SOURCE_MOCK
    assert {h["name"] for h in idle["heaps"]} == {"npu", "vpp"}
    assert idle["used_bytes"] == 0
    assert monitor.tpu_usage()["percent"] == 0

    monitor.set_mock_used(30000 << 20)   # past the 26 GiB NPU heap
    loaded = monitor.device_memory()
    npu = next(h for h in loaded["heaps"] if h["name"] == "npu")
    vpp = next(h for h in loaded["heaps"] if h["name"] == "vpp")
    assert npu["used_bytes"] == npu["total_bytes"]      # NPU fills first
    assert vpp["used_bytes"] > 0                        # then VPP
    assert loaded["max_block_bytes"] == vpp["free_bytes"]

    samples = [monitor.tpu_usage()["percent"] for _ in range(12)]
    assert len(set(samples)) > 1, "the mock's usage must actually vary"


def test_mock_usage_is_zero_when_nothing_is_loaded(monkeypatch):
    monkeypatch.setattr(monitor, "_SIMULATE",
                        {"on": True, "loaded_bytes": 0, "tick": 0})
    assert all(monitor.tpu_usage()["percent"] == 0 for _ in range(5))


def test_the_simulated_heaps_have_the_board_shape():
    """The mock exists so the console can be built off the board; a different
    shape would make the layout wrong in a way only the board would show."""
    npu_total = dict(monitor.MOCK_HEAPS)["npu"]
    vpp_total = dict(monitor.MOCK_HEAPS)["vpp"]
    assert npu_total == 26624 * 1024 * 1024   # `.157`, measured
    assert vpp_total == 2048 * 1024 * 1024
