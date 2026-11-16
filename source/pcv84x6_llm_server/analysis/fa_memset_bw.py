#!/usr/bin/env python3
"""38: What does one bm_memset_device_ext of 128 MiB actually cost?

MYS-2474's report priced the fresh-prefill FA clear at "2.50 GiB / 21.8 GB/s =
123 ms" and that number was carried into MYS-2477's acceptance target ("--100 ms
at 64 rows"). Measured two independent ways on the board, removing the clear
saves ~44 ms, not 123:

  * the A/B prefill wall time drops by 43 ms at every width (64/256/2048);
  * bmprof's own per-call CPU time for the 20 removed clears is 43.8 ms.

So the ~123 ms is not what the clear costs, and a 3x error in a premise is worth
locating before the number is quoted again. This probe measures the memset
itself, at the sizes the engine actually uses, so the per-call cost and the
bandwidth are a measurement rather than a division:

    python3 analysis/fa_memset_bw.py --model <bmodel> --sizes 64,1024,32768,131072

For each size it clears the same buffer `--iters` times (no sync in between --
the engine issues its clears back to back too) and reports ms per call and the
resulting GB/s. The point of the size sweep: bm_memset_device_ext is not a DMA
descriptor the driver batches, it is a call whose cost the driver pays on the
calling CPU, so small clears are latency-bound and large ones bandwidth-bound.
Averaging the two together produces a bandwidth that describes neither -- which
is exactly how 5.25 GiB / 258 ms became "21.8 GB/s" for a buffer that actually
clears at 61 GB/s.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import signal
import statistics
import sys
import time

WATCHDOG_SECS = 300


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--libsophon", default="/opt/sophon/libsophon-current/lib")
    ap.add_argument("--sizes", default="64,1024,32768,131072",
                    help="MiB per clear (comma separated)")
    ap.add_argument("--iters", type=int, default=20)
    a = ap.parse_args()

    signal.signal(signal.SIGALRM, lambda *_: os._exit(3))
    signal.alarm(WATCHDOG_SECS)

    ctypes.CDLL(os.path.join(a.libsophon, "libbmlib.so"), mode=ctypes.RTLD_GLOBAL)
    bmlib = ctypes.CDLL(os.path.join(a.libsophon, "libbmlib.so"))
    handle = ctypes.c_void_p()
    if bmlib.bm_dev_request(ctypes.byref(handle), 0) != 0:
        raise SystemExit("bm_dev_request failed")

    class Mem(ctypes.Structure):
        _fields_ = [("device_addr", ctypes.c_uint64),
                    ("size", ctypes.c_uint32),
                    ("flags", ctypes.c_uint32)]

    bmlib.bm_malloc_device_byte_heap_mask.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(Mem), ctypes.c_int, ctypes.c_uint]
    bmlib.bm_free_device.argtypes = [ctypes.c_void_p, Mem]
    memset = bmlib.bm_memset_device_ext
    memset.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, Mem]
    memset.restype = ctypes.c_int
    sync = bmlib.bm_thread_sync
    sync.argtypes = [ctypes.c_void_p]

    zero = ctypes.c_int(0)
    print(f"{'MiB':>8} {'ms/call':>9} {'spread':>16} {'GB/s':>7}")
    for mib in (int(x) for x in a.sizes.split(",") if x.strip()):
        bytes_ = mib << 20
        m = Mem()
        if bmlib.bm_malloc_device_byte_heap_mask(
                handle, ctypes.byref(m), 3, bytes_) != 0:
            print(f"{mib:>8} alloc failed (NPU heap)")
            continue
        try:
            # Warm the path, then time `iters` clears with one sync after them,
            # the way the engine issues them (activate() clears 20 in a row).
            memset(handle, ctypes.byref(zero), 1, m)
            sync(handle)
            per = []
            for _ in range(a.iters):
                t0 = time.perf_counter()
                memset(handle, ctypes.byref(zero), 1, m)
                per.append((time.perf_counter() - t0) * 1000)
            sync(handle)
            med = statistics.median(per)
            print(f"{mib:>8} {med:>9.3f} "
                  f"{min(per):>7.3f}-{max(per):<8.3f} {bytes_ / (med / 1000) / 1e9:>7.1f}")
        finally:
            bmlib.bm_free_device(handle, m)
    bmlib.bm_dev_free(handle)


main()
