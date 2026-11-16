"""Hold part of the VPP heap back from bmrt, for the board's multimedia stack.

Why a *held block* and not a number in a config file: bmrt allocates through
bmlib, whose heap mask on this chip covers NPU *and* VPP, and its allocator
takes VPP happily -- measured on `.157`, docs/device-memory.md §2. Nothing in
bmrt's API says "leave VPP alone"; the only thing that shrinks what another
process can allocate is memory someone else already holds. A block allocated
here and kept for the process's lifetime does exactly that, for every worker at
once: heap statistics are device-wide, and a 256 MiB block held by the service
was observed to make a concurrent 1900 MiB VPP allocation fail while still
leaving a 1700 MiB one succeeding (docs/device-memory.md §4).

The consequence to be honest about: this is a *reservation by occupancy*, so a
worker that starts before the service has taken its block can still take the
space. ``app.main`` acquires it at startup, before any model can be loaded, and
``acquired`` in the stats payload says whether it is actually in force.

Environment: ``CV84X6_VPP_RESERVE_MB`` (default 256, 0 disables).
"""

from __future__ import annotations

import ctypes
import logging
import os
import threading

from . import monitor

logger = logging.getLogger(__name__)

#: VPP heap id in bmlib's numbering (``carveout_heap_id[1]``, the heap named
#: "vpp"). Mask bit 1, so mask value 2.
VPP_HEAP_MASK = 2

DEFAULT_RESERVE_BYTES = 256 * 1024 * 1024
RESERVE_ENV = "CV84X6_VPP_RESERVE_MB"


class _DeviceMem(ctypes.Structure):
    """``bm_device_mem_t`` (``struct bm_mem_desc``) from bmlib_runtime.h:112.

    Field order matters even though the struct is mostly passed back opaque:
    the union with ``device_addr`` comes *first*, then ``flags`` and ``size``.
    Reading ``size`` from the wrong offset returns the low 32 bits of the
    address, which is 0 for a block at a 4 GiB-aligned heap base -- the VPP heap
    on the 10155 board starts at 0x1f00000000 -- and made a successful
    reservation look like a failure.
    """

    _fields_ = [
        ("device_addr", ctypes.c_ulong),   # unsigned long on Linux (8 bytes, aarch64)
        ("reserved", ctypes.c_uint),
        ("dmabuf_fd", ctypes.c_int),
        ("flags", ctypes.c_uint),          # bm_mem_flags_t, a 32-bit bitfield union
        ("size", ctypes.c_uint),
    ]


def reserve_bytes_from_env() -> int:
    """The requested reservation, in bytes, from the environment."""
    raw = os.environ.get(RESERVE_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_RESERVE_BYTES
    try:
        return max(0, int(float(raw) * 1024 * 1024))
    except ValueError:
        logger.warning("%s=%r is not a number; using the %d MiB default",
                       RESERVE_ENV, raw, DEFAULT_RESERVE_BYTES >> 20)
        return DEFAULT_RESERVE_BYTES


class VppReservation:
    """A VPP block held for as long as this object lives.

    ``acquire()`` is idempotent and never raises: a board where the block
    cannot be taken still runs, it just says so (``acquired`` False and a
    ``reason``), because refusing to start the service over a multimedia
    reserve would be a worse failure than the reserve is worth.
    """

    def __init__(self, requested_bytes: int | None = None):
        self.requested_bytes = (reserve_bytes_from_env()
                                if requested_bytes is None else requested_bytes)
        self.held_bytes = 0
        self.acquired = False
        self.reason: str | None = None
        self._handle = None
        self._mem = None
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        with self._lock:
            if self.acquired or self._mem is not None:
                return self.acquired
            if self.requested_bytes <= 0:
                self.reason = "disabled"
                return False
            lib = monitor._bmlib()
            if lib is None:
                self.reason = "libbmlib not available"
                return False
            try:
                lib.bm_malloc_device_byte_heap_mask.argtypes = [
                    ctypes.c_void_p, ctypes.POINTER(_DeviceMem), ctypes.c_int,
                    ctypes.c_uint]
                lib.bm_malloc_device_byte_heap_mask.restype = ctypes.c_int
                lib.bm_free_device.argtypes = [ctypes.c_void_p, _DeviceMem]
                lib.bm_free_device.restype = None
            except AttributeError:
                self.reason = "libbmlib has no heap-mask allocator"
                return False

            handle = ctypes.c_void_p()
            if lib.bm_dev_request(ctypes.byref(handle), 0) != 0 or not handle:
                self.reason = "no device handle"
                return False
            mem = _DeviceMem()
            status = lib.bm_malloc_device_byte_heap_mask(
                handle, ctypes.byref(mem), VPP_HEAP_MASK,
                int(self.requested_bytes))
            if status != 0 or not mem.size:
                lib.bm_dev_free(handle)
                # Not fatal: the media stack may already be holding VPP, or the
                # board may have a smaller VPP heap than the request.
                self.reason = (f"could not allocate {self.requested_bytes >> 20} "
                               f"MiB of VPP (bm status {status})")
                logger.warning("VPP reserve not taken: %s", self.reason)
                return False
            self._handle = handle
            self._mem = mem
            self.held_bytes = int(self.requested_bytes)
            self.acquired = True
            self.reason = None
            logger.info("holding %d MiB of VPP for the multimedia stack "
                        "(addr 0x%x)", self.held_bytes >> 20, mem.device_addr)
            return True

    def release(self) -> None:
        with self._lock:
            if self._mem is None:
                return
            lib = monitor._bmlib()
            try:
                if lib is not None and self._handle:
                    lib.bm_free_device(self._handle, self._mem)
                    lib.bm_dev_free(self._handle)
            except Exception:  # pragma: no cover - release must never raise
                logger.exception("releasing the VPP reserve failed")
            finally:
                self._handle = None
                self._mem = None
                self.held_bytes = 0
                self.acquired = False

    def status(self) -> dict:
        return {
            "requested_bytes": self.requested_bytes,
            "held_bytes": self.held_bytes,
            "acquired": self.acquired,
            "reason": self.reason,
            "env": RESERVE_ENV,
        }
