#!/usr/bin/env python3
"""Isolated repeat-probe for the WeMM image-embedding zero-vector fault.

Runs a serial matrix of embedding requests against one freshly created native
encoder handle per group, records the vector norm / non-zero count / fault flag
/ timings of every call, and prints one JSON record per group.

The point is to find out *which* request pattern leaves the encoder returning a
zero vector (MYS-2913).  Nothing here talks to the service: it loads the same
``libcv84x6_llm.so`` the service uses through the public ``cv_vle_*`` C API, in
its own process, so the production worker is neither used nor disturbed.

Images are synthesised from a fixed seed, so no customer data is involved and
the run is repeatable.

Usage
-----
    # whole matrix, one subprocess (one encoder instance) per group
    python3 tools/vl_embed/repeat_probe.py --library /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \\
        --config /opt/sophgo/cv84x6_llm_server/model-config/wemm_embedding \\
        --model /data/cv84x6_llm_server/models/wemm-embedding-2b/<file>.bmodel \\
        --output /tmp/mys2913/repeat-probe.json

    # a single group in this process (used by the driver above)
    python3 tools/vl_embed/repeat_probe.py ... --group same-image --json-line

Groups
------
``text-repeat``        four identical text inputs (control)
``same-image``         the same image four times
``alt-size``           two image sizes alternating: A, B, A, B
``image-then-text``    image, then three text inputs
``text-then-image``    three text inputs, then the same image three times
``image-pair``         image A, image B, image A, image B with B > A in tokens

Every request is issued serially on one handle.  A faulted handle refuses
further work (the native engine requires a reload), so the group stops there and
records ``faulted_at``.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import ctypes as C
import json
import math
import os
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path


# ---------------------------------------------------------------------------
# deterministic synthetic PNG (no PIL on the board)
# ---------------------------------------------------------------------------
def _lcg(seed: int):
    state = seed & 0xFFFFFFFF

    def nxt() -> int:
        nonlocal state
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        return state

    return nxt


def make_png(h: int, w: int, seed: int) -> bytes:
    """An RGB PNG of ``h`` x ``w`` pixels, fixed given ``seed``."""
    nxt = _lcg(seed)
    rows = []
    for y in range(h):
        row = bytearray(b"\x00")  # filter type 0 (None)
        for x in range(w):
            v = nxt()
            row += bytes(((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# ---------------------------------------------------------------------------
# the native encoder, through the same C API the service uses
# ---------------------------------------------------------------------------
class Encoder:
    def __init__(self, library: str, model: str, config: str, device: int = 0):
        from tokenizers import Tokenizer

        manifest = json.loads((Path(config) / "embedding_config.json").read_text())
        if manifest.get("model_type") != "wemm_embedding":
            raise ValueError("--config must be a wemm_embedding config directory")
        self.tokenizer = Tokenizer.from_file(str(Path(config) / "tokenizer.json"))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.manifest = manifest

        self.lib = c = C.CDLL(library)
        ptr, integer, err_t = C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_char_p)
        c.cv_vle_create.argtypes = [C.c_char_p, C.c_int, err_t]
        c.cv_vle_create.restype = ptr
        c.cv_vle_destroy.argtypes = [ptr]
        c.cv_vle_destroy.restype = None
        c.cv_vle_fault.argtypes = [ptr]
        c.cv_vle_fault.restype = C.c_int
        c.cv_vle_info.argtypes = [ptr, integer, integer, integer]
        c.cv_vle_info.restype = C.c_int
        c.cv_vle_image_create_ex.argtypes = [C.c_char_p, C.c_int, C.c_int, C.c_int,
                                             C.c_int, integer, integer, err_t]
        c.cv_vle_image_create_ex.restype = ptr
        c.cv_vle_image_destroy.argtypes = [ptr]
        c.cv_vle_image_destroy.restype = None
        c.cv_vle_forward.argtypes = [ptr, integer, C.c_int, ptr, C.c_int, C.c_int,
                                     C.POINTER(C.c_float), C.POINTER(C.c_double), err_t]
        c.cv_vle_forward.restype = C.c_int

        err = C.c_char_p()
        started = time.perf_counter()
        self.handle = c.cv_vle_create(str(model).encode(), device, C.byref(err))
        if not self.handle:
            raise RuntimeError(err.value.decode() if err.value else "cv_vle_create failed")
        self.load_s = time.perf_counter() - started
        seq, hidden, patches = C.c_int(), C.c_int(), C.c_int()
        if c.cv_vle_info(self.handle, C.byref(seq), C.byref(hidden), C.byref(patches)):
            raise RuntimeError("cv_vle_info failed")
        self.seq, self.hidden, self.max_patches = seq.value, hidden.value, patches.value
        self.min_pixels = int(manifest.get("min_pixels", 65536))

    # -- prompt rendering, identical to app/engine/vl_embed_native.py ---------
    def render(self, text: str, image_tokens: int, instruction: str | None) -> str:
        image = ("<|vision_start|>" + "<|image_pad|>" * image_tokens + "<|vision_end|>"
                 if image_tokens else "")
        system = ("<|im_start|>system\n" + instruction.strip() + "<|im_end|>\n"
                  if instruction and instruction.strip() else "")
        return system + "<|im_start|>user\n" + (image + text).strip() + "<|im_end|>\n"

    @property
    def fault(self) -> bool:
        return bool(self.lib.cv_vle_fault(self.handle))

    def bucket(self, n: int) -> int:
        for rows in (128, 512, 1024, self.seq):
            if n <= rows:
                return rows
        return self.seq

    def encode(self, text: str = "", png: bytes | None = None,
               instruction: str | None = None, dimensions: int | None = None,
               keep_vector: bool = False) -> dict:
        dim = self.hidden if dimensions is None else dimensions
        image = None
        rec = {"kind": "image" if png else "text", "text_chars": len(text or ""),
               "png_bytes": len(png) if png else 0}
        try:
            image_tokens = 0
            if png is not None:
                err, gh, gw = C.c_char_p(), C.c_int(), C.c_int()
                image = self.lib.cv_vle_image_create_ex(png, len(png), self.max_patches,
                                                        self.min_pixels, 1,
                                                        C.byref(gh), C.byref(gw), C.byref(err))
                if not image:
                    rec.update(ok=False, error=err.value.decode() if err.value else "image_create failed")
                    return rec
                image_tokens = gh.value // 2 * (gw.value // 2)
                rec.update(grid_h=gh.value, grid_w=gw.value,
                           pixels=gh.value * 32 * gw.value * 32)
            prompt = self.render(text, image_tokens, instruction)
            ids = self.tokenizer.encode(prompt, add_special_tokens=True).ids
            rec.update(tokens=len(ids), image_tokens=image_tokens, bucket=self.bucket(len(ids)))
            if len(ids) > self.seq:
                rec.update(ok=False, error=f"{len(ids)} tokens exceed {self.seq}")
                return rec
            offset = 1 + ids.index(248053) if image_tokens else 0

            idarr = (C.c_int * len(ids))(*ids)
            out = (C.c_float * dim)()
            timings = (C.c_double * 3)()
            err = C.c_char_p()
            started = time.perf_counter()
            rc = self.lib.cv_vle_forward(self.handle, idarr, len(ids), image, offset, dim,
                                         out, timings, C.byref(err))
            rec["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
            rec["embedding_ms"] = round(timings[0], 1)
            rec["vision_ms"] = round(timings[1], 1)
            rec["encoder_ms"] = round(timings[2], 1)
            if rc:
                rec.update(ok=False, error=err.value.decode() if err.value else "forward failed")
            else:
                vec = list(out)
                norm = math.sqrt(sum(v * v for v in vec))
                nonzero = sum(1 for v in vec if v != 0.0)
                # A digest of the exact vector: identical input must produce an
                # identical one, so a differing digest across repeated calls is
                # itself the finding, independent of any tolerance.
                digest = hashlib.sha256(
                    struct.pack("<%df" % len(vec), *vec)).hexdigest()[:16]
                rec.update(ok=True, dim=dim, norm=round(norm, 9), nonzero=nonzero,
                           finite=all(math.isfinite(v) for v in vec),
                           vecsha=digest,
                           head=[round(v, 6) for v in vec[:4]])
                if keep_vector:
                    rec["vec"] = vec
            rec["faulted"] = self.fault
            return rec
        finally:
            if image:
                self.lib.cv_vle_image_destroy(image)

    def close(self):
        if getattr(self, "handle", None):
            self.lib.cv_vle_destroy(self.handle)
            self.handle = None


# ---------------------------------------------------------------------------
# groups
# ---------------------------------------------------------------------------
TEXT = "A photograph of a meal on a wooden table."
# Text long enough to select the 512- and 1024-token encoder graphs, so the
# bucket itself can be varied with no image in the request at all.
LONG_TEXT = " ".join(["The quick brown fox jumps over the lazy dog."] * 20)
LONGER_TEXT = " ".join(["The quick brown fox jumps over the lazy dog."] * 45)
# Production's failing calls carried 204 and 177 prompt tokens. With this
# tokenizer those totals are only reachable from non-square pages: 24x32 and
# 22x30 patch grids. The default matrix therefore uses non-square images --
# a square 512 image is 262 tokens and never lands on either figure.
DEFAULT_SMALL = (384, 512)     # h, w  -> 24x32 grid, 192 image tokens, 204 total
DEFAULT_LARGE = (352, 480)     # h, w  -> 22x30 grid, 165 image tokens, 177 total


def plan(group: str, small: tuple[int, int], large: tuple[int, int]) -> list[dict]:
    """The request sequence of one group; shown in the report as-is."""
    def page(hw: tuple[int, int], seed: int) -> dict:
        h, w = hw
        return {"png": make_png(h, w, seed), "size": f"{h}x{w}"}

    small_img = page(small, 20261116)
    large_img = page(large, 20261117)
    if group == "text-repeat":
        return [{"text": TEXT}] * 4
    if group == "same-image":
        return [small_img] * 4
    if group == "alt-size":
        return [small_img, large_img, small_img, large_img]
    if group == "image-then-text":
        return [small_img] + [{"text": TEXT}] * 3
    if group == "text-then-image":
        return [{"text": TEXT}] * 3 + [small_img] * 3
    if group == "image-pair":
        return [small_img, small_img, large_img, large_img]
    if group == "text-bucket-512":
        # Same bucket as the failing images, no image at all: isolates "the 512
        # graph is unstable" from "images break it".
        return [{"text": LONG_TEXT}] * 4
    if group == "text-bucket-1024":
        return [{"text": LONGER_TEXT}] * 4
    raise ValueError(f"unknown group {group!r}")


GROUPS = ["text-repeat", "same-image", "alt-size", "image-then-text",
          "text-then-image", "image-pair", "text-bucket-512", "text-bucket-1024"]


def run_group(args, group: str) -> dict:
    enc = Encoder(args.library, args.model, args.config)
    small = _size(args.small)
    large = _size(args.large)
    result = {"group": group, "load_s": round(enc.load_s, 2),
              "seq": enc.seq, "hidden": enc.hidden, "max_patches": enc.max_patches,
              "small": f"{small[0]}x{small[1]}", "large": f"{large[0]}x{large[1]}",
              "calls": [], "faulted_at": None}
    try:
        for index, item in enumerate(plan(group, small, large)):
            if enc.fault:
                result["faulted_at"] = index
                break
            rec = enc.encode(text=item.get("text", ""), png=item.get("png"),
                             instruction=args.instruction, dimensions=args.dimensions)
            rec["index"] = index
            rec["size"] = item.get("size")
            result["calls"].append(rec)
            if not rec.get("ok") or rec.get("faulted"):
                result["faulted_at"] = index
                break
    finally:
        enc.close()
    return result


def _size(text: str) -> tuple[int, int]:
    """``768x1024`` (h x w, as a page is described) -> (768, 1024)."""
    h, _, w = text.lower().partition("x")
    return int(h), int(w)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--library", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--group", default="all")
    p.add_argument("--small", default=f"{DEFAULT_SMALL[0]}x{DEFAULT_SMALL[1]}",
                   help="first image as HxW pixels (default 384x512 -> 204 tokens)")
    p.add_argument("--large", default=f"{DEFAULT_LARGE[0]}x{DEFAULT_LARGE[1]}",
                   help="second image as HxW pixels (default 352x480 -> 177 tokens)")
    p.add_argument("--dimensions", type=int, default=None)
    p.add_argument("--instruction", default=None)
    p.add_argument("--output")
    p.add_argument("--timeout", type=float, default=900.0,
                   help="per-group wall-clock limit in seconds (default 900)")
    p.add_argument("--json-line", action="store_true",
                   help=argparse.SUPPRESS)
    a = p.parse_args()
    if a.group != "all" and a.group not in GROUPS:
        p.error(f"--group must be one of {', '.join(GROUPS)} or all")

    if a.dimensions is not None and not 64 <= a.dimensions <= 4096:
        p.error("--dimensions out of range")

    if a.group != "all":
        result = run_group(a, a.group)
        line = json.dumps(result, ensure_ascii=False)
        if a.json_line:
            print(line)
        else:
            _report([result], a.output)
        return 0

    # One process per group: a faulted handle cannot be reused, and a fresh
    # process is the only way to be sure the next group starts clean.
    results = []
    for group in GROUPS:
        cmd = [sys.executable, str(Path(__file__).resolve()), "--library", a.library,
               "--model", a.model, "--config", a.config, "--group", group,
               "--small", a.small, "--large", a.large, "--json-line"]
        if a.dimensions is not None:
            cmd += ["--dimensions", str(a.dimensions)]
        if a.instruction:
            cmd += ["--instruction", a.instruction]
        print(f"[repeat-probe] group {group} ...", file=sys.stderr)
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=a.timeout)
        if done.returncode != 0:
            results.append({"group": group, "error": (done.stderr or "").strip()[-2000:]})
            print(f"[repeat-probe] group {group} FAILED rc={done.returncode}", file=sys.stderr)
            continue
        try:
            results.append(json.loads(done.stdout.strip().splitlines()[-1]))
        except (IndexError, json.JSONDecodeError):
            results.append({"group": group, "error": "unparseable output: " + done.stdout[-500:]})
    _report(results, a.output)
    return 0


def _report(results: list[dict], output: str | None) -> None:
    payload = json.dumps(results, ensure_ascii=False, indent=1)
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(payload + "\n")
    print(payload)
    # compact summary on stderr so a human reads the verdict, not the JSON
    for group in results:
        if "error" in group:
            print(f"[repeat-probe] {group['group']:<16} ERROR {group['error'][:120]}", file=sys.stderr)
            continue
        norms = " ".join("0" if c.get("norm") == 0.0 else f"{c.get('norm', float('nan')):.3f}"
                         for c in group["calls"])
        verdict = "FAULT" if group["faulted_at"] is not None else "ok"
        print(f"[repeat-probe] {group['group']:<16} {verdict:<5} norms=[{norms}]", file=sys.stderr)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
