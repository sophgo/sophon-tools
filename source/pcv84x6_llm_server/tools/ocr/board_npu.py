#!/usr/bin/env python3
"""Run one bmodel network on the board's NPU and dump its outputs as .npz.

Written for MYS-2591 stage A, where the question is "does the CV84X6 reproduce
what the reference produced for the same input", and the answer has to be a file
comparison rather than an eyeballed one. It is model-agnostic: it reads the
graph's own tensor shapes from bmrt and moves typed data in and out, so the
layout detector and the vision tower use the same driver.

Why not sophon-sail: ``.151`` has no ``sophon`` python module (libsophon ships
headers and ``libbmrt.so``, not the wheel), and installing one there would be a
board change this card does not need. bmrt's C API is the same library the
service's own native engine links against, so driving it through ctypes
reproduces what the product does.

**The ctypes structs below are transcriptions of the board's own headers**, not
guesses: ``bmdef.h`` for ``bm_net_info_t``/``bm_stage_info_t``/``bm_shape_t``/
``bm_tensor_t`` and ``bmlib_runtime.h`` for ``bm_mem_desc_t``. An earlier version
of this file used an invented layout and segfaulted on the first field access;
``bm_net_info_t`` in particular is not in the obvious order (``is_dynamic`` comes
second, and the tensor shapes live inside ``stages``, not at the top level).

    python3 tools/ocr/board_npu.py --bmodel m.bmodel --net 0 \\
        --input input_states=states.npy --input full_attn_mask=mask.npy \\
        --out out.npz

Runs on the board only; host-side prep and comparison are separate scripts.
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import sys
from pathlib import Path

import numpy as np

LIBSOPHON = "/opt/sophon/libsophon-0.4.15"
LIBBMRT = f"{LIBSOPHON}/lib/libbmrt.so"
LIBBMLIB = f"{LIBSOPHON}/lib/libbmlib.so"

#: bm_data_type_t -> numpy dtype, transcribed from bmdef.h's `bm_data_type_e`.
#: The enum is short and the values are NOT grouped by width (INT16/UINT16/UINT32
#: sit between UINT8 and BFLOAT16), so a "natural" ordering would silently
#: reinterpret memory: bf16=8 read as uint64 produced plausible-looking garbage
#: before this was corrected.
DTYPES = {0: np.float32,    # BM_FLOAT32
          1: np.float16,    # BM_FLOAT16
          2: np.int8,       # BM_INT8
          3: np.uint8,      # BM_UINT8
          4: np.int16,      # BM_INT16
          5: np.uint16,     # BM_UINT16
          6: np.int32,      # BM_INT32
          7: np.uint32,     # BM_UINT32
          8: np.uint16,     # BM_BFLOAT16 -- stored as raw 16-bit, converted below
          }

BM_MAX_DIMS_NUM = 8
NPU_HEAP_MASK = 3


class BmShape(C.Structure):
    _fields_ = [("num_dims", C.c_int), ("dims", C.c_int * BM_MAX_DIMS_NUM)]


class BmMemDevice(C.Structure):
    # bmlib_runtime.h, the `device` arm of bm_mem_desc's union. `unsigned long`
    # is 8 bytes on this 64-bit target.
    _fields_ = [("device_addr", C.c_ulong), ("reserved", C.c_uint32),
                ("dmabuf_fd", C.c_int)]


class BmMemSystem(C.Structure):
    _fields_ = [("system_addr", C.c_void_p), ("reserved0", C.c_uint32),
                ("reserved1", C.c_int)]


class BmMemDescUnion(C.Union):
    # The two arms are *structs inside the union*, not flat fields: flattening
    # them makes the union 8 bytes (max single member) instead of 16, and the
    # whole descriptor 16 instead of 24 -- which is a silent 8-byte shift for
    # every field after it and segfaults inside bmrt.
    _fields_ = [("device", BmMemDevice), ("system", BmMemSystem)]


class BmMemDesc(C.Structure):
    _fields_ = [("u", BmMemDescUnion), ("flags", C.c_uint32),
                ("size", C.c_uint32)]


class BmTensor(C.Structure):
    _fields_ = [("dtype", C.c_int), ("shape", BmShape),
                ("device_mem", BmMemDesc), ("st_mode", C.c_int)]


class BmStageInfo(C.Structure):
    _fields_ = [("input_shapes", C.POINTER(BmShape)),
                ("output_shapes", C.POINTER(BmShape)),
                ("input_mems", C.POINTER(BmMemDesc)),
                ("output_mems", C.POINTER(BmMemDesc))]


class BmNetInfo(C.Structure):
    _fields_ = [
        ("name", C.c_char_p),
        ("is_dynamic", C.c_bool),
        ("input_num", C.c_int),
        ("input_names", C.POINTER(C.c_char_p)),
        ("input_dtypes", C.POINTER(C.c_int)),
        ("input_scales", C.POINTER(C.c_float)),
        ("output_num", C.c_int),
        ("output_names", C.POINTER(C.c_char_p)),
        ("output_dtypes", C.POINTER(C.c_int)),
        ("output_scales", C.POINTER(C.c_float)),
        ("stage_num", C.c_int),
        ("stages", C.POINTER(BmStageInfo)),
        ("max_input_bytes", C.POINTER(C.c_size_t)),
        ("max_output_bytes", C.POINTER(C.c_size_t)),
        ("input_zero_point", C.POINTER(C.c_int)),
        ("output_zero_point", C.POINTER(C.c_int)),
        ("input_loc_devices", C.POINTER(C.c_int)),
        ("output_loc_devices", C.POINTER(C.c_int)),
        ("core_num", C.c_int),
        ("addr_mode", C.c_int32),
    ]


def load_libs():
    bmlib = C.CDLL(LIBBMLIB)
    bmrt = C.CDLL(LIBBMRT)

    bmrt.bmrt_create.restype = C.c_void_p
    bmrt.bmrt_create.argtypes = [C.c_void_p]
    bmrt.bmrt_load_bmodel.restype = C.c_bool
    bmrt.bmrt_load_bmodel.argtypes = [C.c_void_p, C.c_char_p]
    bmrt.bmrt_get_network_number.restype = C.c_int
    bmrt.bmrt_get_network_number.argtypes = [C.c_void_p]
    bmrt.bmrt_get_network_names.argtypes = [C.c_void_p,
                                            C.POINTER(C.POINTER(C.c_char_p))]
    bmrt.bmrt_get_network_info.restype = C.POINTER(BmNetInfo)
    bmrt.bmrt_get_network_info.argtypes = [C.c_void_p, C.c_char_p]
    bmrt.bmrt_launch_tensor_ex.restype = C.c_bool
    bmrt.bmrt_launch_tensor_ex.argtypes = [
        C.c_void_p, C.c_char_p, C.POINTER(BmTensor), C.c_int,
        C.POINTER(BmTensor), C.c_int, C.c_bool, C.c_bool]
    bmrt.bmrt_tensor_with_device.argtypes = [C.POINTER(BmTensor), BmMemDesc,
                                             C.c_int, BmShape]
    bmrt.bmrt_destroy.argtypes = [C.c_void_p]

    bmlib.bm_dev_request.restype = C.c_int
    bmlib.bm_dev_request.argtypes = [C.POINTER(C.c_void_p), C.c_int]
    bmlib.bm_malloc_device_byte_heap_mask.restype = C.c_int
    bmlib.bm_malloc_device_byte_heap_mask.argtypes = [
        C.c_void_p, C.POINTER(BmMemDesc), C.c_int, C.c_int]
    bmlib.bm_free_device.argtypes = [C.c_void_p, BmMemDesc]
    bmlib.bm_memcpy_s2d.argtypes = [C.c_void_p, BmMemDesc, C.c_void_p]
    bmlib.bm_memcpy_d2s.argtypes = [C.c_void_p, C.c_void_p, BmMemDesc]
    bmlib.bm_dev_free.argtypes = [C.c_void_p]
    # **Required after every launch.** bmruntime_interface.h on
    # bmrt_launch_tensor_ex: "After calling this API, inference on TPU is
    # launched. And the CPU program will not be blocked. bm_thread_sync should
    # be called to make sure inference finished." Without it the following
    # bm_memcpy_d2s reads the output buffer while the NPU is still writing, so
    # consecutive launches over the same input return *different* results --
    # measured on `.157` as the same all-zero input giving 0.8911 / 0.5435 /
    # 0.129 on three runs, which reads exactly like a broken model.
    bmlib.bm_thread_sync.argtypes = [C.c_void_p]
    bmlib.bm_thread_sync.restype = C.c_int
    return bmrt, bmlib


def bf16_to_f32(raw: np.ndarray) -> np.ndarray:
    """bf16 bit pattern -> float32, by shifting into the float32 exponent slot."""
    bits = raw.astype(np.uint32) << 16
    return bits.view(np.float32)


def shape_of(shape: BmShape) -> list[int]:
    return [int(shape.dims[i]) for i in range(shape.num_dims)]


def net_table(net: BmNetInfo) -> dict:
    stage = net.stages[0]
    inputs = [{"name": net.input_names[i].decode(),
               "dims": shape_of(stage.input_shapes[i]),
               "dtype": int(net.input_dtypes[i])}
              for i in range(net.input_num)]
    outputs = [{"name": net.output_names[i].decode(),
                "dims": shape_of(stage.output_shapes[i]),
                "dtype": int(net.output_dtypes[i])}
               for i in range(net.output_num)]
    return {"name": net.name.decode(), "inputs": inputs, "outputs": outputs,
            "is_dynamic": bool(net.is_dynamic), "stage_num": int(net.stage_num),
            "addr_mode": int(net.addr_mode)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bmodel", required=True, type=Path)
    ap.add_argument("--net", default=None,
                    help="network name or index; default: the first network")
    ap.add_argument("--input", action="append", default=[],
                    help="name=file.npy")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--devid", type=int, default=0)
    ap.add_argument("--json", action="store_true",
                    help="print every network's tensor table and exit")
    args = ap.parse_args()

    bmrt, bmlib = load_libs()
    handle = C.c_void_p()
    if bmlib.bm_dev_request(C.byref(handle), args.devid) != 0 or not handle:
        print("bm_dev_request failed", file=sys.stderr)
        return 1

    rt = bmrt.bmrt_create(handle)
    if not rt:
        print("bmrt_create failed", file=sys.stderr)
        return 1
    if not bmrt.bmrt_load_bmodel(rt, str(args.bmodel).encode()):
        print(f"bmrt_load_bmodel failed: {args.bmodel}", file=sys.stderr)
        return 1

    count = bmrt.bmrt_get_network_number(rt)
    names = C.POINTER(C.c_char_p)()
    bmrt.bmrt_get_network_names(rt, C.byref(names))
    net_names = [names[i].decode() for i in range(count)]

    if args.json:
        tables = [net_table(bmrt.bmrt_get_network_info(rt, n.encode()).contents)
                  for n in net_names]
        print(json.dumps(tables, indent=1))
        bmrt.bmrt_destroy(rt)
        bmlib.bm_dev_free(handle)
        return 0

    if args.net is None:
        chosen = net_names[0]
    elif args.net.isdigit() and int(args.net) < len(net_names):
        chosen = net_names[int(args.net)]
    else:
        chosen = args.net
    if chosen not in net_names:
        print(f"no network {chosen!r}; this bmodel has {len(net_names)}", file=sys.stderr)
        return 1
    info = bmrt.bmrt_get_network_info(rt, chosen.encode()).contents
    table = net_table(info)
    print(f"net {chosen}: {len(table['inputs'])} in, "
          f"{len(table['outputs'])} out, addr_mode={table['addr_mode']}",
          file=sys.stderr)

    feeds = {}
    for spec in args.input:
        name, _, path = spec.partition("=")
        feeds[name] = np.load(path)
    missing = [i["name"] for i in table["inputs"] if i["name"] not in feeds]
    if missing:
        print(f"missing inputs: {missing}", file=sys.stderr)
        return 1

    owned: list[BmMemDesc] = []

    def alloc(nbytes: int) -> BmMemDesc:
        mem = BmMemDesc()
        rc = bmlib.bm_malloc_device_byte_heap_mask(
            handle, C.byref(mem), NPU_HEAP_MASK, nbytes)
        if rc != 0:
            raise RuntimeError(f"bm_malloc_device_byte_heap_mask({nbytes}) rc={rc}")
        owned.append(mem)
        return mem

    def shape_of_dims(dims: list[int]) -> BmShape:
        return BmShape(len(dims), (C.c_int * BM_MAX_DIMS_NUM)(*dims))

    tin = (BmTensor * len(table["inputs"]))()
    tout = (BmTensor * len(table["outputs"]))()
    for i, meta in enumerate(table["inputs"]):
        arr = np.ascontiguousarray(feeds[meta["name"]].astype(DTYPES[meta["dtype"]]))
        if list(arr.shape) != meta["dims"]:
            print(f"input {meta['name']}: fed {list(arr.shape)} but the graph "
                  f"declares {meta['dims']}", file=sys.stderr)
            return 1
        mem = alloc(arr.nbytes)
        if bmlib.bm_memcpy_s2d(handle, mem, arr.ctypes.data) != 0:
            print(f"bm_memcpy_s2d({meta['name']}) failed", file=sys.stderr)
            return 1
        bmrt.bmrt_tensor_with_device(C.byref(tin[i]), mem, meta["dtype"],
                                     shape_of_dims(meta["dims"]))

    out_arrays = {}
    for i, meta in enumerate(table["outputs"]):
        arr = np.zeros(meta["dims"], dtype=DTYPES[meta["dtype"]])
        out_arrays[meta["name"]] = arr
        mem = alloc(arr.nbytes)
        bmrt.bmrt_tensor_with_device(C.byref(tout[i]), mem, meta["dtype"],
                                     shape_of_dims(meta["dims"]))

    ok = bmrt.bmrt_launch_tensor_ex(rt, chosen.encode(), tin, len(table["inputs"]),
                                    tout, len(table["outputs"]), True, False)
    if not ok:
        print("bmrt_launch_tensor_ex failed", file=sys.stderr)
        return 1
    # See load_libs(): the launch is asynchronous, so the outputs are only
    # valid after this. Skipping it silently yields torn results.
    rc = bmlib.bm_thread_sync(handle)
    if rc != 0:
        print(f"bm_thread_sync failed rc={rc}", file=sys.stderr)
        return 1

    for i, meta in enumerate(table["outputs"]):
        arr = out_arrays[meta["name"]]
        if bmlib.bm_memcpy_d2s(handle, arr.ctypes.data, tout[i].device_mem) != 0:
            print(f"bm_memcpy_d2s({meta['name']}) failed", file=sys.stderr)
            return 1
        if meta["dtype"] == 8:  # BM_BFLOAT16: widen here, not in every caller
            arr = bf16_to_f32(arr)
            out_arrays[meta["name"]] = arr
        print(f"out {meta['name']} {arr.shape} {arr.dtype} "
              f"min {arr.min():.4f} max {arr.max():.4f}", file=sys.stderr)

    if args.out is None:
        print("no --out given; outputs not saved", file=sys.stderr)
    else:
        np.savez(args.out, **out_arrays)
        print(f"wrote {args.out}", file=sys.stderr)

    for mem in owned:
        bmlib.bm_free_device(handle, mem)
    bmrt.bmrt_destroy(rt)
    bmlib.bm_dev_free(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
