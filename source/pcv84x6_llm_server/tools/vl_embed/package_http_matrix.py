#!/usr/bin/env python3
"""The bucket/switch matrix over the *installed package's* HTTP path.

``fix_acceptance.py`` drives the encoder through the ``cv_vle_*`` C API. That
proves the engine; it does not prove the package. Between the two sit the
worker process, the RPC, prompt rendering, the image decoder, the HTTP layer and
the scheduler, and the field failure was reported through HTTP by a user.

So this script runs the same matrix a second way: it starts the **extracted
candidate package** -- its own ``app/``, its own ``vendor/``, its own
``lib/libcv84x6_llm.so`` -- on a private loopback port with a private data
directory, and drives it over real HTTP. Nothing here touches the production
service on 8000.

What it checks, per shape:

* every request succeeds, returns a finite non-zero vector of the requested
  width, and reports the token count the server actually used;
* the same input repeated back to back returns the **same bytes**;
* the same input issued again after other shapes (a bucket switch, an image
  size change, image -> text -> image) returns the **same bytes** as its
  baseline;
* all four compiled buckets are reached, and each is recorded with the shape
  that reached it.

Usage::

    python3 tools/vl_embed/package_http_matrix.py \\
        --package-root /data/mys2914/pkg/opt/sophgo/cv84x6_llm_server \\
        --model /data/.../wemm-embedding-2b_....bmodel \\
        --work-dir /data/mys2914/http-matrix-work \\
        --image-dir /data/mys2914/ref/coco64 \\
        --out /data/mys2914/package-http-matrix.json

Exit codes: 0 every gate held; 1 a gate failed; 2 setup problem (missing file,
port unavailable) -- never conflated with a finding.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import math
import socket
import struct
import sys
import time
from pathlib import Path

# The script must import the PACKAGE's app, not a source tree. --package-root is
# prepended to sys.path before anything from app/ is imported, and the vendor
# directory is added the same way the packaged launcher does it.
PACKAGE_ROOT: Path | None = None


def _load_package(root: Path):
    global PACKAGE_ROOT
    PACKAGE_ROOT = root.resolve()
    for entry in (str(PACKAGE_ROOT), str(PACKAGE_ROOT / "vendor")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    import httpx
    import uvicorn
    from app.main import create_app
    return httpx, uvicorn, create_app


# The same shapes the C-API matrix uses, so the two reports line up one to one.
SHORT_EN = "A photograph of a meal on a wooden table."
SHORT_ZH = "一只猫趴在窗台上晒太阳。"
_SENTENCE = "The quick brown fox jumps over the lazy dog."
LONG_512 = " ".join([_SENTENCE] * 20)
LONG_1024 = " ".join([_SENTENCE] * 70)
LONG_2048 = " ".join([_SENTENCE] * 190)

MRL_WIDTHS = (64, 128, 256, 512, 1024, 2048)
REQUIRED_BUCKETS = (128, 512, 1024, 2048)
DIMENSIONS = 256


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _digest(vec) -> str:
    return hashlib.sha256(struct.pack("<%df" % len(vec), *vec)).hexdigest()[:16]


def _norm(vec) -> float:
    return math.sqrt(sum(x * x for x in vec))


def _cosine(a, b) -> float:
    na, nb = _norm(a), _norm(b)
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else float("nan")


def _png(h: int, w: int, seed: int) -> bytes:
    """Deterministic PNG, same generator family as repeat_probe.make_png."""
    import zlib
    state = seed & 0xFFFFFFFF

    def nxt() -> int:
        nonlocal state
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        return state

    rows = []
    for _y in range(h):
        row = bytearray(b"\x00")
        for _x in range(w):
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


def _data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


async def run(a) -> int:
    root = a.package_root.resolve()
    library = root / "lib" / "libcv84x6_llm.so"
    for required in (library, root / "app", root / "vendor"):
        if not required.exists():
            print(f"missing package component: {required}", file=sys.stderr)
            return 2

    httpx, uvicorn, create_app = _load_package(root)

    work = a.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    model_id = a.model_id
    model_dir = work / "models" / model_id
    model_dir.mkdir(parents=True, exist_ok=True)
    for source, name in ((a.model.resolve(), a.model.name),
                         (root / "model-config" / "wemm_embedding", "config")):
        target = model_dir / name
        if not target.exists():
            target.symlink_to(source)
        elif target.resolve() != source.resolve():
            print(f"{target} already points somewhere else", file=sys.stderr)
            return 2

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    app = create_app(data_root=work, backend_kind="native", native_lib=str(library),
                     install_dir=root, web_dir=root / "web" / "dist",
                     agent_specs=[], service_port=port)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning", access_log=False))
    task = asyncio.create_task(server.serve())

    report: dict = {
        "package_root": str(root),
        "package_library": str(library),
        "package_library_sha256": _sha(library),
        "model": str(a.model),
        "model_sha256": _sha(a.model),
        "port": port,
        "shapes": [], "revisits": [], "buckets_seen": [],
        "failures": [], "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    checks = 0

    def check(cond, why):
        nonlocal checks
        checks += 1
        if not cond:
            report["failures"].append(why)
        return cond

    try:
        base = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient(base_url=base, timeout=600) as c:
            for _ in range(240):
                try:
                    if (await c.get("/api/health")).status_code < 500:
                        break
                except Exception:  # noqa: BLE001 - still starting
                    pass
                await asyncio.sleep(0.5)
            check((await c.post("/api/login", json={"password": "admin"})).status_code == 200,
                  "console login failed")
            loaded = await c.post(f"/api/models/{model_id}/load")
            if not check(loaded.status_code == 200, f"model load: {loaded.status_code} {loaded.text[:300]}"):
                raise SystemExit
            key = (await c.post("/api/keys", json={"name": "mys2914-http"})).json()["key"]
            headers = {"Authorization": f"Bearer {key}"}

            images = {
                "img-384x512": _png(384, 512, 20261116),
                "img-512x384": _png(512, 384, 20261117),
                "img-256x256": _png(256, 256, 20261118),
                "img-352x480": _png(352, 480, 20261119),
                "img-max-1280x1024": _png(1280, 1024, 20261120),
            }
            shapes = [
                ("short-en", {"text": SHORT_EN}),
                ("short-zh", {"text": SHORT_ZH}),
                ("image", {"png": images["img-384x512"]}),
                ("image-alt", {"png": images["img-512x384"]}),
                ("image-square", {"png": images["img-256x256"]}),
                ("image+text", {"text": SHORT_EN, "png": images["img-352x480"]}),
                ("image-max", {"png": images["img-max-1280x1024"]}),
                ("long-512", {"text": LONG_512}),
                ("long-1024", {"text": LONG_1024}),
                ("long-2048", {"text": LONG_2048}),
            ]
            baseline: dict[str, list] = {}

            async def embed(item) -> tuple[dict, list | None]:
                # The HTTP body speaks OpenAI's multimodal shape: text and a
                # data: URL, never raw bytes. The C-API matrix passes bytes
                # straight to the engine, so this conversion is one of the
                # things only the HTTP path can get wrong.
                entry: dict = {}
                if item.get("text"):
                    entry["text"] = item["text"]
                if item.get("png"):
                    entry["image"] = _data_url(item["png"])
                body: dict = {"model": model_id, "input": [entry],
                              "dimensions": DIMENSIONS}
                r = await c.post("/v1/embeddings", headers=headers, json=body)
                if r.status_code != 200:
                    return {"status": r.status_code, "error": r.text[:300]}, None
                payload = r.json()
                vec = payload["data"][0]["embedding"]
                usage = payload.get("usage") or {}
                return {"status": 200, "tokens": usage.get("prompt_tokens"),
                        "vector": vec}, vec

            def record(name, where, vec, meta):
                if vec is None:
                    report["failures"].append(f"{where}: {meta.get('error')}")
                    return
                check(len(vec) == DIMENSIONS, f"{where}: width {len(vec)} != {DIMENSIONS}")
                check(all(math.isfinite(x) for x in vec), f"{where}: non-finite component")
                check(_norm(vec) > 0, f"{where}: zero vector")
                ref = baseline.get(name)
                if ref is None:
                    baseline[name] = vec
                    return
                if vec == ref:
                    return
                report["failures"].append(
                    f"{where}: vector differs from the baseline for the same input "
                    f"(cosine {_cosine(ref, vec):.9f})")

            for name, item in shapes:
                vectors, digests, tokens = [], [], []
                entry = {"shape": name, "calls": 0, "bucket": None}
                for index in range(a.per_shape):
                    meta, vec = await embed(item)
                    entry["calls"] += 1
                    if entry["bucket"] is None:
                        entry["bucket"] = _bucket_of(meta.get("tokens"))
                        if entry["bucket"] not in report["buckets_seen"]:
                            report["buckets_seen"].append(entry["bucket"])
                    if vec is not None:
                        tokens.append(meta.get("tokens"))
                        digests.append(_digest(vec))
                        vectors.append(vec)
                    record(name, f"{name}[{index}]", vec, meta)
                entry["tokens"] = tokens[0] if tokens else None
                entry["distinct_digests"] = len(set(digests))
                entry["digest"] = digests[0] if digests else None
                entry["norm"] = round(_norm(vectors[0]), 9) if vectors else None
                if entry["distinct_digests"] > 1:
                    report["failures"].append(
                        f"{name}: {entry['distinct_digests']} distinct vectors over "
                        f"{entry['calls']} identical HTTP requests")
                report["shapes"].append(entry)

                # Switch equality: re-issue every earlier shape now that other
                # shapes (other buckets, other image sizes) have run in between.
                if name in ("image-max", "long-1024"):
                    for earlier, earlier_item in shapes[:shapes.index((name, item))]:
                        meta, vec = await embed(earlier_item)
                        ok = vec is not None and earlier in baseline and vec == baseline[earlier]
                        report["revisits"].append({
                            "shape": earlier, "after": name,
                            "tokens": meta.get("tokens"),
                            "bucket": _bucket_of(meta.get("tokens")),
                            "matches_baseline": ok,
                        })
                        if vec is None:
                            report["failures"].append(
                                f"revisit {earlier} after {name}: {meta.get('error')}")
                        elif earlier not in baseline:
                            report["failures"].append(
                                f"revisit {earlier} after {name}: no baseline")
                        elif not ok:
                            report["failures"].append(
                                f"revisit {earlier} after {name}: vector differs from "
                                f"baseline (cosine {_cosine(baseline[earlier], vec):.9f})")

            missing = [b for b in REQUIRED_BUCKETS if b not in report["buckets_seen"]]
            if missing:
                report["failures"].append(
                    f"buckets never reached over HTTP: {missing} "
                    f"(saw {report['buckets_seen']})")
            if not report["revisits"]:
                report["failures"].append("no revisit was issued over HTTP")
    finally:
        # Unload before stopping the server, and do it on the failure path too:
        # a run that crashed mid-matrix must not leave the model resident and
        # NPU memory held. `should_exit` alone stops the HTTP server, not the
        # worker process that owns the device allocation.
        try:
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}",
                                         timeout=120) as c:
                await c.post("/api/login", json={"password": "admin"})
                await c.post(f"/api/models/{model_id}/unload")
        except Exception as exc:  # noqa: BLE001 - teardown must not mask the verdict
            report["failures"].append(f"teardown unload failed: {exc}")
        server.should_exit = True
        await task

    report["checks"] = checks
    report["passed"] = not report["failures"]
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")

    print(f"package library: {report['package_library_sha256']}")
    print(f"buckets reached: {report['buckets_seen']}")
    for shape in report["shapes"]:
        print(f"  {shape['shape']:<14} tokens={shape['tokens']} bucket={shape['bucket']} "
              f"n={shape['calls']} distinct={shape['distinct_digests']} "
              f"norm={shape['norm']}")
    print(f"revisits: {len(report['revisits'])}, "
          f"all matched: {all(r['matches_baseline'] for r in report['revisits'])}")
    if report["failures"]:
        print(f"FAILED ({len(report['failures'])}):", file=sys.stderr)
        for item in report["failures"]:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print(f"PASS ({checks} checks)")
    return 0


def _bucket_of(tokens) -> int | None:
    """The compiled bucket the server selected, from the token count it reports."""
    if not isinstance(tokens, int):
        return None
    for rows in REQUIRED_BUCKETS:
        if tokens <= rows:
            return rows
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--package-root", type=Path, required=True,
                   help="extracted package root (the directory holding app/, lib/, vendor/)")
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--model-id", default="wemm-embedding-2b")
    p.add_argument("--work-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--per-shape", type=int, default=3)
    p.add_argument("--image-dir", type=Path,
                   help="unused by the matrix itself; recorded for context")
    a = p.parse_args()
    return asyncio.run(run(a))


if __name__ == "__main__":
    sys.exit(main())
