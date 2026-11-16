"""Device resource sampling.

All paths here were verified on the CV84X6 board (see docs/BSP-NOTES refs in
docs/DESIGN.md). Every probe is defensive: a missing file yields ``None`` for
that field rather than an exception, because the dashboard must keep rendering
on a partially-supported kernel.

Two notions of "the accelerator's memory" live here and they are not the same:

* **device memory** -- both ion carveout heaps, NPU *and* VPP. The TPU reads
  and writes either, and bmlib's own allocator spills from one to the other, so
  this is the figure an operator needs when asking "will another model fit"
  (docs/device-memory.md).
* **NPU heap** -- heap 0 alone. Kept as a deprecated view for one release
  because the console still reads those fields; nothing here needs it.
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import time
from pathlib import Path

# Verified on CV84X6 / SDK 2.3:
#  - TPU utilisation needs `npu_usage_enable=1`, otherwise the driver prints a
#    message instead of numbers. We enable it opportunistically and never fail.
NPU_USAGE_ENABLE = Path("/sys/class/bm-tpu/bm-tpu0/device/npu_usage_enable")
NPU_USAGE = Path("/sys/class/bm-tpu/bm-tpu0/device/npu_usage")
ION_HEAPS = Path("/sys/kernel/debug/ion/heaps")
VPPINFO = Path("/proc/vppinfo")
VPUINFO = Path("/proc/soph/vpuinfo")
THERMAL = Path("/sys/class/thermal")
CLK_CPU = Path("/sys/kernel/debug/clk/clk_ap_ca55/clk_rate")

#: bmlib, the same library bmrt itself allocates through. Asking it for heap
#: statistics is what makes "device memory" and bmrt's own view agree; the ion
#: debugfs `alloc_mem` node is the same number by another route and is the
#: fallback when libbmlib cannot be loaded (host tests).
LIBSOPHON_LIB = "/opt/sophon/libsophon-current/lib"
BMLIB_NAMES = ("libbmlib.so", "libbmlib.so.1", "libbmlib.so.1.0")

#: The two ion carveout heaps that make up device memory, in the order bmrt
#: numbers them (bmlib's `carveout_heap_id[]`: [0] npu, [1] vpp).
DEVICE_HEAPS = ("npu", "vpp")


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def _read_int(path: Path) -> int | None:
    raw = _read(path)
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _safe_is_dir(path: Path) -> bool:
    """``is_dir`` that never raises.

    debugfs paths (``/sys/kernel/debug/...``) are typically 0700 root-only, so a
    stat on them raises PermissionError for an unprivileged service account. The
    bare ``.is_dir()`` this replaces sat outside any try block, which took the
    whole ``/api/stats`` down with a 500 and left the dashboard blank -- one
    unreadable probe must degrade to "no data", never to "no dashboard".
    """
    try:
        return path.is_dir()
    except OSError:
        return False


def _safe_iterdir(path: Path) -> list[Path]:
    try:
        return sorted(path.iterdir())
    except OSError:
        return []


def cpu_percent() -> float | None:
    """CPU busy fraction from /proc/stat, sampled against the previous call."""
    raw = _read(Path("/proc/stat"))
    if not raw:
        return None
    fields = raw.splitlines()[0].split()[1:]
    vals = [int(x) for x in fields[:8]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    total = sum(vals)
    prev = getattr(cpu_percent, "_prev", None)
    cpu_percent._prev = (idle, total)  # type: ignore[attr-defined]
    if prev is None:
        return None
    d_idle = idle - prev[0]
    d_total = total - prev[1]
    if d_total <= 0:
        return None
    return round(100.0 * (1.0 - d_idle / d_total), 1)


def memory() -> dict:
    raw = _read(Path("/proc/meminfo")) or ""
    info = {}
    for line in raw.splitlines():
        parts = line.split(":")
        if len(parts) == 2:
            info[parts[0]] = int(parts[1].strip().split()[0]) * 1024
    total = info.get("MemTotal")
    avail = info.get("MemAvailable")
    return {
        "total_bytes": total,
        "available_bytes": avail,
        "used_bytes": (total - avail) if (total and avail) else None,
    }


def load_average() -> list[float]:
    try:
        return [round(x, 2) for x in os.getloadavg()]
    except OSError:
        return []


def temperatures() -> list[dict]:
    out = []
    if not _safe_is_dir(THERMAL):
        return out
    try:
        zones = sorted(THERMAL.glob("thermal_zone*"))
    except OSError:
        return out
    for zone in zones:
        milli = _read_int(zone / "temp")
        if milli is None:
            continue
        out.append({
            "zone": zone.name,
            "name": (_read(zone / "type") or "").strip(),
            "celsius": round(milli / 1000.0, 1),
        })
    return out


BM_SMI = Path("/opt/sophon/libsophon-current/bin/bm-smi")
BM_SMI_LIB = LIBSOPHON_LIB
_SMI_TTL_S = 2.0
_smi_cache: tuple[float, dict] = (0.0, {})
_ANSI = re.compile(rb"\x1b(?:\[[0-9;?]*[A-Za-z]|[()][0-9A-Za-z]|[78=>])")

# Where each reading came from, so a client never has to guess whether a number
# is a heap total, a driver counter or our own accounting.
SOURCE_BMLIB = "bmlib"        # bm_get_gmem_heap_stat_byte_by_id
SOURCE_ION = "ion"            # /sys/kernel/debug/ion/cvi_*_heap_dump/alloc_mem
SOURCE_SYSFS = "sysfs"        # /sys/class/bm-tpu/.../npu_usage
SOURCE_MOCK = "mock"          # the simulated backend; nothing was read
SOURCE_NONE = "none"

#: The simulated backend (`--backend mock`) has no device, but the console is
#: developed against it and must get the same fields with plausible values --
#: otherwise every layout change is only testable on a board. `enable_mock()`
#: turns this on from `app.main`; the numbers it reports are invented and say so
#: through `source: "mock"`.
_SIMULATE: dict = {"on": False, "loaded_bytes": 0, "tick": 0}

#: Same shape as the board: a 26 GiB NPU heap and a 2 GiB VPP heap.
MOCK_HEAPS = (("npu", 26624 * 1024 * 1024), ("vpp", 2048 * 1024 * 1024))


def enable_mock(on: bool = True) -> None:
    """Report simulated device memory and TPU usage (mock backend only)."""
    _SIMULATE["on"] = bool(on)


def set_mock_used(bytes_used: int) -> None:
    """Make the simulated device memory track what the mock backend loaded.

    The console's admission view is only meaningful if a load visibly consumes
    something; the mock manager calls this with the sum of loaded bmodel sizes.
    """
    _SIMULATE["loaded_bytes"] = max(0, int(bytes_used))


def _simulated_device_memory() -> dict:
    """Invented, but in the board's proportions: NPU first, then VPP."""
    used = _SIMULATE["loaded_bytes"]
    heaps = []
    for name, total in MOCK_HEAPS:
        # Fill NPU first, then spill into VPP -- the order bmrt uses.
        npu_total = MOCK_HEAPS[0][1]
        if name == "npu":
            heap_used = min(used, total)
        else:
            heap_used = max(0, min(used - npu_total, total))
        heaps.append({
            "name": name,
            "total_bytes": total,
            "used_bytes": heap_used,
            "free_bytes": max(0, total - heap_used),
        })
    total = sum(h["total_bytes"] for h in heaps)
    used_total = sum(h["used_bytes"] for h in heaps)
    return {
        "total_bytes": total,
        "used_bytes": used_total,
        "free_bytes": max(0, total - used_total),
        "max_block_bytes": max((h["free_bytes"] for h in heaps), default=0),
        "heaps": heaps,
        "source": SOURCE_MOCK,
    }


def _simulated_tpu_usage() -> dict:
    """A utilisation that actually moves, so a chart can be built against it.

    Idle near zero, then a slow rise and fall while anything is loaded -- the
    shape the board shows during decode (docs/device-memory.md §5) without
    pretending the values are measurements.
    """
    _SIMULATE["tick"] += 1
    loaded = _SIMULATE["loaded_bytes"] > 0
    if not loaded:
        percent = 0.0
        cores = [0.0, 0.0, 0.0, 0.0]
    else:
        # Triangle wave over 20 ticks, 20-95 %, same on every core.
        phase = _SIMULATE["tick"] % 20
        percent = round(20.0 + 75.0 * (phase if phase <= 10 else 20 - phase) / 10.0, 1)
        cores = [percent] * 4
    return {"percent": percent, "cores": cores, "source": SOURCE_MOCK}


def parse_bm_smi(raw: bytes) -> dict:
    """Pull the card's NPU memory out of a ``bm-smi -noloop`` dump.

    Layout per libsophon bm-smi/src/bm_smi_display.cpp, second card line:
    ``| 12V maxP boardP minclk maxclk fan | busid status curclk tpuc used/total``.
    On CV84X6 SoC the power/voltage fields print N/A, so the memory is all
    there is. The dump is a curses screen with the separating spaces partly
    replaced by cursor moves, hence matching by shape, not by column.

    **The ``0M``/``100M`` column is not a clock.** It is ``tpuc``, TPU
    utilisation in percent (``bm_smi_tpuc_to_str``), which is why the console
    used to show "current 0 MHz" on an idle board. Nor is the ``25M/1000M``
    pair a reading -- those are the DVFS limits. No frequency is read from here
    at all any more; see ``tpu_usage()``.

    The ``usedMB/totalMB`` pair is the **NPU heap only** (26624 MB on this
    board), not device memory: VPP is a separate heap this display does not
    cover. ``device_memory()`` is the figure to use for capacity questions.
    """
    text = _ANSI.sub(b"", raw).decode("utf-8", "replace")
    out: dict = {}
    m = re.search(r"(\d+)M\s+(\d+)M\s+\S+\|[^|]*?(\d+)M", text)
    if m:
        out["tpu_min_clock_mhz"] = int(m.group(1))
        out["tpu_max_clock_mhz"] = int(m.group(2))
        # Kept for the card row's utilisation column; never a frequency.
        out["tpu_util_percent"] = int(m.group(3))
    # The card's "usedMB/totalMB" has the largest total; smaller pairs are
    # other memory partitions.
    mem = re.findall(r"(\d+)\s*MB\s*/\s*(\d+)", text)
    if mem:
        used, total = max(mem, key=lambda t: int(t[1]))
        out["mem_used_bytes"] = int(used) * 1024 * 1024
        out["mem_total_bytes"] = int(total) * 1024 * 1024
    return out


class _HeapStat(ctypes.Structure):
    """``bm_heap_stat_byte_t`` from bmlib_runtime.h."""

    _fields_ = [
        ("heap_id", ctypes.c_uint),
        ("mem_total", ctypes.c_ulonglong),
        ("mem_avail", ctypes.c_ulonglong),
        ("mem_used", ctypes.c_ulonglong),
        ("mem_start_addr", ctypes.c_ulonglong),
    ]


_libmgr: dict = {"tried": False, "lib": None}


def _bmlib():
    """libbmlib, or None where it is not installed (host tests, mock backend).

    Loaded once and cached. Opening a bm handle is cheap and touches no
    allocation, so each ``device_memory()`` call can request its own; it is
    freed in a ``finally`` so a sampler running every two seconds does not leak
    descriptors.
    """
    if _libmgr["tried"]:
        return _libmgr["lib"]
    _libmgr["tried"] = True
    lib = None
    for name in BMLIB_NAMES:
        try:
            lib = ctypes.CDLL(os.path.join(LIBSOPHON_LIB, name))
            break
        except OSError:
            continue
    if lib is not None:
        try:
            lib.bm_dev_request.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_int]
            lib.bm_dev_request.restype = ctypes.c_int
            lib.bm_dev_free.argtypes = [ctypes.c_void_p]
            lib.bm_get_gmem_total_heap_num.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
            lib.bm_get_gmem_total_heap_num.restype = ctypes.c_int
            lib.bm_get_gmem_heap_stat_byte_by_id.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(_HeapStat), ctypes.c_uint]
            lib.bm_get_gmem_heap_stat_byte_by_id.restype = ctypes.c_int
        except AttributeError:  # a bmlib without the heap API
            lib = None
    _libmgr["lib"] = lib
    return lib


def reset_bmlib_cache() -> None:
    """Forget the loaded library. Tests only; production loads it once."""
    _libmgr["tried"] = False
    _libmgr["lib"] = None


def _heaps_from_bmlib() -> list[dict]:
    lib = _bmlib()
    if lib is None:
        return []
    handle = ctypes.c_void_p()
    if lib.bm_dev_request(ctypes.byref(handle), 0) != 0 or not handle:
        return []
    try:
        num = ctypes.c_uint()
        if lib.bm_get_gmem_total_heap_num(handle, ctypes.byref(num)) != 0:
            return []
        out = []
        for index in range(min(num.value, len(DEVICE_HEAPS))):
            stat = _HeapStat()
            if lib.bm_get_gmem_heap_stat_byte_by_id(
                    handle, ctypes.byref(stat), index) != 0:
                continue
            out.append({
                "name": DEVICE_HEAPS[index],
                "total_bytes": int(stat.mem_total),
                "used_bytes": int(stat.mem_used),
                "free_bytes": int(stat.mem_avail),
            })
        return out
    finally:
        lib.bm_dev_free(handle)


def _heaps_from_ion() -> list[dict]:
    """The same two numbers from the ion debugfs dump, as a fallback.

    ``alloc_mem`` is what is allocated; ``total_mem`` is the carveout size. The
    node is 0700 root-only on a default install, so this usually yields nothing
    for the service account -- it exists so a board where bmlib is missing can
    still report, rather than so it can be preferred.
    """
    out = []
    for name in DEVICE_HEAPS:
        heap = ION_HEAPS / f"cvi_{name}_heap_dump"
        total = _read_int(heap / "total_mem")
        used = _read_int(heap / "alloc_mem")
        if total is None and used is None:
            continue
        total = total or 0
        used = used or 0
        out.append({"name": name, "total_bytes": total, "used_bytes": used,
                    "free_bytes": max(0, total - used)})
    return out


def device_memory() -> dict:
    """NPU + VPP: the memory the TPU can hold models and activations in.

    ``total_bytes``/``used_bytes``/``free_bytes`` are the two heaps summed;
    ``heaps`` breaks them out because they are not interchangeable for one
    allocation -- a single block must fit inside one heap, so the largest block
    that can still be allocated is bounded by the freer heap, not by the sum.
    ``max_block_bytes`` states that bound so the admission check does not have
    to re-derive it (docs/device-memory.md).

    ``source`` is ``bmlib`` when libbmlib answered and ``ion`` when only the
    debugfs dump did; ``mock`` on the simulated backend; ``none`` with empty
    heaps means no device was readable.
    """
    if _SIMULATE["on"]:
        return _simulated_device_memory()
    heaps = _heaps_from_bmlib()
    source = SOURCE_BMLIB
    if not heaps:
        heaps = _heaps_from_ion()
        source = SOURCE_ION if heaps else SOURCE_NONE
    total = sum(h["total_bytes"] for h in heaps)
    used = sum(h["used_bytes"] for h in heaps)
    return {
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": max(0, total - used),
        # A single allocation cannot span heaps.
        "max_block_bytes": max((h["free_bytes"] for h in heaps), default=0),
        "heaps": heaps,
        "source": source,
    }


def tpu_frequency() -> dict:
    """Deprecated: the frequency is no longer read, and this always says so.

    Kept for one release because ``snapshot()["tpu_freq"]`` was a documented
    field; ``mhz`` is always ``None`` and ``source`` always ``none``. Use
    ``tpu_usage()``. See docs/device-memory.md.
    """
    return {"mhz": None, "source": SOURCE_NONE, "unit": "MHz",
            "deprecated": True, "use": "tpu_usage"}


def _parse_npu_usage(text: str) -> tuple[float | None, list[float]]:
    """``usage:N avusage:M`` plus per-core lines -> (total, cores).

    ``usage`` is a sliding-window percentage the driver recomputes every
    ``npu_usage_interval`` ms (500 by default, covering ~25 s); it is an
    instantaneous-ish figure, not a lifetime average. ``avusage`` is the
    since-enable average and is deliberately not reported as "usage".
    """
    total: float | None = None
    cores: list[float] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("usage:") and total is None:
            for field in line.split():
                if field.startswith("usage:"):
                    try:
                        total = float(field.split(":", 1)[1])
                    except ValueError:
                        pass
        elif "npu usage" in line and ":" in line:
            try:
                cores.append(float(line.split(":")[1].strip().split()[0]))
            except (ValueError, IndexError):
                pass
    return total, cores


def tpu_usage() -> dict:
    """TPU utilisation in percent, per core, from the driver's own counters.

    Measured on `.157` (2026-11-07, docs/device-memory.md §5): idle reports
    ``usage:0``, a 35B decode of 222 tokens climbs to 90-96 and returns to 0
    within a second of the last token. The counter is the driver's read of the
    TPU-busy flag, so it is real utilisation -- no engine-side accounting is
    needed, and none is mixed in here.

    ``percent`` is the driver's card-wide ``usage``; ``cores`` is the same
    quantity per TPU core (4 on CV84X6). Everything is ``None``/empty when the
    node is unreadable, e.g. before the driver created it or on a host.
    """
    if _SIMULATE["on"]:
        return _simulated_tpu_usage()
    # The driver gates the counters behind this knob; setting it is idempotent
    # and it is already 1 on a board whose bmssm has booted. A non-root service
    # account gets EACCES and simply reports what the node says.
    try:
        if NPU_USAGE_ENABLE.exists() and _read(NPU_USAGE_ENABLE) not in ('"enable": 1',):
            NPU_USAGE_ENABLE.write_text("1")
    except OSError:
        pass

    text = _read(NPU_USAGE)
    total, cores = (None, [])
    if text:
        total, cores = _parse_npu_usage(text)
    source = SOURCE_SYSFS if (total is not None or cores) else SOURCE_NONE
    return {"percent": total, "cores": cores, "source": source}


def bm_smi_sample() -> dict:
    """The vendor tool's card row, cached for a moment.

    Only used for the NPU-heap memory pair (the deprecated view); TPU
    utilisation comes from ``tpu_usage()``, which needs no subprocess.
    ``-noloop`` prints one screen and exits.
    """
    global _smi_cache
    now = time.monotonic()
    if now - _smi_cache[0] < _SMI_TTL_S:
        return _smi_cache[1]
    out: dict = {}
    if BM_SMI.exists():
        env = dict(os.environ)
        env["LD_LIBRARY_PATH"] = BM_SMI_LIB + (
            ":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
        try:
            raw = subprocess.run([str(BM_SMI), "-noloop"], capture_output=True,
                                 timeout=5, env=env).stdout
            out = parse_bm_smi(raw)
        except (OSError, subprocess.SubprocessError):
            out = {}
    _smi_cache = (now, out)
    return out


def npu_usage() -> dict:
    """Deprecated NPU-heap view, kept for one release.

    The console's "NPU 显存" card reads ``smi``/``heap``; ``device_memory()`` is
    what should replace it. ``total_percent``/``cores`` duplicate
    ``tpu_usage()`` and are marked deprecated here rather than removed so an
    older console keeps working.
    """
    return {
        "total_percent": tpu_usage()["percent"],
        "cores": tpu_usage()["cores"],
        "heap": ion_heap_bytes(),
        "smi": bm_smi_sample(),
        "deprecated": True,
        "use": "device_mem",
    }


def ion_heap_bytes() -> dict[str, dict]:
    """Raw per-heap totals from the ion debugfs dump, keyed by heap name."""
    out: dict[str, dict] = {}
    if not _safe_is_dir(ION_HEAPS):
        return out
    for heap in _safe_iterdir(ION_HEAPS):
        if not _safe_is_dir(heap) or not heap.name.startswith("cvi_"):
            continue
        total = _read_int(heap / "total_mem")
        alloc = _read_int(heap / "alloc_mem")
        if total is not None or alloc is not None:
            # "cvi_npu_heap_dump" -> "npu"
            name = heap.name[len("cvi_"):-len("_heap_dump")]
            out[name] = {"total_bytes": total, "alloc_bytes": alloc}
    return out


def vpu_usage() -> float | None:
    text = _read(VPUINFO)
    if not text:
        return None
    for line in text.splitlines():
        if "enc" in line.lower() and "%" in line:
            try:
                return float(line.split(":")[1].strip().split()[0].rstrip("%"))
            except (ValueError, IndexError):
                return None
    return None


def clocks() -> dict:
    """Raw CPU clock register, for callers that want Hz.

    ``tpu_hz`` used to be here; the TPU frequency is not read any more (see
    ``tpu_usage()``), so the key is gone rather than always ``None`` -- a field
    that never has a value invites a client to render "0 GHz".
    """
    return {
        "cpu_hz": _read_int(CLK_CPU),
    }


def disk(path: str = "/data") -> dict:
    try:
        st = os.statvfs(path)
    except OSError:
        return {}
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    return {
        "path": path,
        "total_bytes": total,
        "free_bytes": free,
        "used_bytes": total - free,
    }


def prime() -> None:
    """Take one CPU sample at startup.

    cpu_percent needs two reads to compute a delta; without priming, the first
    dashboard render always shows "—", which reads as "the probe is broken".
    """
    cpu_percent()


def snapshot() -> dict:
    return {
        "ts": time.time(),
        "cpu_percent": cpu_percent(),
        "load_average": load_average(),
        "memory": memory(),
        "temperatures": temperatures(),
        # Device memory = NPU + VPP. This is the field capacity questions
        # should be asked of (docs/device-memory.md).
        "device_mem": device_memory(),
        # TPU utilisation, the replacement for the frequency.
        "tpu_usage": tpu_usage(),
        # Deprecated for one release; the console still reads both. `npu` is
        # the NPU heap alone, `tpu_freq` is always empty.
        "npu": npu_usage(),
        "tpu_freq": tpu_frequency(),
        "vpu_percent": vpu_usage(),
        "clocks": clocks(),
        "disk": disk(),
    }
