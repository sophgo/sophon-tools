#!/usr/bin/env python3
"""Load one bmodel and report what it costs the NPU heap, measured not declared.

``bmrt_get_bmodel_info`` is not usable for this: it reports ``io_mem`` as the sum
of every net stage's buffers at maximum shape, which over-states a build by
hundreds of MiB (docs/model-settings.md has the table). The honest figure is the
difference in the device heap before and after ``cv_embed_create`` (or
``cv_rerank_create`` with ``--kind rerank``) -- the same method
``app/core/monitor.py`` uses to publish ``device_memory()``.

    # on the board, with the service stopped or the model not loaded
    python3 mem_probe.py --lib lib/libcv84x6_llm.so --model x.bmodel

Prints peak and steady-state. Peak matters as much as steady: the loader
transiently holds both the file-backed weights and the device copy, and a board
that admits a model on its steady figure alone can fail the load.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys

MIB = 1024 * 1024

#: libsophon's heap-stat entry points, the same ones ``app/core/monitor.py``
#: uses. This chip's sysfs exposes only ``npu_usage``; the heap figures come
#: from libbmlib, which is why bm_dev_request appears here at all.
LIBSOPHON_LIB = "/opt/sophon/libsophon-current/lib"
BMLIB_NAMES = ("libbmlib.so", "libbmlib.so.0")


class _HeapStat(ctypes.Structure):
    """``bm_heap_stat_byte_t`` from libsophon's ``bmlib_runtime.h``.

    The leading ``heap_id`` is load-bearing: without it every field reads one
    slot early and ``mem_total`` comes back as the *used* figure, which looks
    plausible enough to be believed (it is the same order as the heap size).
    """

    _fields_ = [("heap_id", ctypes.c_uint),
                ("mem_total", ctypes.c_ulonglong),
                ("mem_avail", ctypes.c_ulonglong),
                ("mem_used", ctypes.c_ulonglong),
                ("mem_start_addr", ctypes.c_ulonglong)]


def device_memory() -> dict[str, dict]:
    """``{heap_index: {total, used}}`` through libbmlib."""
    lib = None
    for name in BMLIB_NAMES:
        try:
            lib = ctypes.CDLL(os.path.join(LIBSOPHON_LIB, name))
            break
        except OSError:
            continue
    if lib is None:
        return {}
    for fn, argtypes, restype in (
            ("bm_dev_request", [ctypes.POINTER(ctypes.c_void_p), ctypes.c_int], ctypes.c_int),
            ("bm_dev_free", [ctypes.c_void_p], None),
            ("bm_get_gmem_total_heap_num", [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)],
             ctypes.c_int),
            ("bm_get_gmem_heap_stat_byte_by_id",
             [ctypes.c_void_p, ctypes.POINTER(_HeapStat), ctypes.c_uint], ctypes.c_int)):
        try:
            getattr(lib, fn).argtypes = argtypes
            getattr(lib, fn).restype = restype
        except AttributeError:
            return {}
    handle = ctypes.c_void_p()
    if lib.bm_dev_request(ctypes.byref(handle), 0) != 0 or not handle:
        return {}
    try:
        num = ctypes.c_uint()
        if lib.bm_get_gmem_total_heap_num(handle, ctypes.byref(num)) != 0:
            return {}
        out = {}
        for index in range(num.value):
            stat = _HeapStat()
            if lib.bm_get_gmem_heap_stat_byte_by_id(
                    handle, ctypes.byref(stat), index) != 0:
                continue
            out[index] = {"total_bytes": int(stat.mem_total),
                          "used_bytes": int(stat.mem_used)}
        return out
    finally:
        lib.bm_dev_free(handle)


def total_used() -> int:
    return sum(h["used_bytes"] for h in device_memory().values())


class Lib:
    def __init__(self, path: str):
        self.lib = ctypes.CDLL(path)
        L = self.lib
        L.cv_embed_create.restype = ctypes.c_void_p
        L.cv_embed_create.argtypes = [ctypes.c_char_p, ctypes.c_int,
                                      ctypes.POINTER(ctypes.c_char_p)]
        L.cv_embed_destroy.argtypes = [ctypes.c_void_p]
        L.cv_embed_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                                    ctypes.POINTER(ctypes.c_int)]
        # Rerank is the same measurement on a different entry point, and it is
        # the model whose per-length builds differ most in heap (the block
        # graphs carry the attention mask, which grows with SEQLEN).
        L.cv_rerank_create.restype = ctypes.c_void_p
        L.cv_rerank_create.argtypes = [ctypes.c_char_p, ctypes.c_int,
                                       ctypes.POINTER(ctypes.c_char_p)]
        L.cv_rerank_destroy.argtypes = [ctypes.c_void_p]
        L.cv_rerank_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                                     ctypes.POINTER(ctypes.c_int)]

    def create(self, path: str, kind: str = "embed"):
        create = (self.lib.cv_embed_create if kind == "embed"
                  else self.lib.cv_rerank_create)
        info = (self.lib.cv_embed_info if kind == "embed"
                else self.lib.cv_rerank_info)
        err = ctypes.c_char_p()
        h = create(path.encode(), 0, ctypes.byref(err))
        if not h:
            raise RuntimeError("cv_%s_create: %s" %
                               (kind, err.value.decode() if err.value else "?"))
        seq = ctypes.c_int()
        hidden = ctypes.c_int()
        info(h, ctypes.byref(seq), ctypes.byref(hidden))
        return h, seq.value, hidden.value

    def destroy(self, h, kind: str = "embed") -> None:
        (self.lib.cv_embed_destroy if kind == "embed"
         else self.lib.cv_rerank_destroy)(h)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lib", required=True)
    ap.add_argument("--kind", choices=("embed", "rerank"), default="embed",
                    help="which engine to create (default: embed)")
    ap.add_argument("--model", action="append", required=True,
                    metavar="NAME=PATH", help="repeatable; each loaded in turn")
    ap.add_argument("--json")
    args = ap.parse_args(argv[1:])

    lib = Lib(args.lib)
    heaps_before = device_memory()
    before = sum(h["used_bytes"] for h in heaps_before.values())
    if not heaps_before:
        print("no libbmlib heap stats: cannot measure", file=sys.stderr)
        return 2
    print("== before: %.1f MiB used of %.1f MiB" % (
        before / MIB, sum(h["total_bytes"] for h in heaps_before.values()) / MIB))

    results = {}
    for spec in args.model:
        name, path = spec.split("=", 1)
        h, seq, hidden = lib.create(path, args.kind)
        loaded = total_used()
        delta = loaded - before
        results[name] = {
            "seq": seq, "hidden": hidden, "path": path,
            "loaded_bytes": loaded, "before_bytes": before, "delta_bytes": delta,
            "size_bytes": os.stat(path).st_size,
        }
        print("  %-8s seq=%-5d loaded %9.1f MiB  delta %8.1f MiB  file %8.1f MiB" % (
            name, seq, loaded / MIB, delta / MIB, os.stat(path).st_size / MIB))
        lib.destroy(h, args.kind)
        after = total_used()
        # `after - loaded` is negative when the model released its memory, so
        # report the magnitude as "released" rather than a sign the reader has
        # to invert.
        print("  %-8s after unload %.1f MiB (released %.1f MiB)" % (
            name, after / MIB, (loaded - after) / MIB))

    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=2)
        print("== wrote %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
