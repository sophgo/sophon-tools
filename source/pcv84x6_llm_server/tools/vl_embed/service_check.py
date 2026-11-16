#!/usr/bin/env python3
"""Run an isolated real HTTP/worker acceptance test; never touch port 8000.

Creates a private state/model directory, starts the app in the foreground,
then drains and stops every worker in a finally block. Native mode is default.
"""
import argparse
import asyncio
import base64
import collections
import hashlib
import json
import math
from pathlib import Path
import socket
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import httpx
import uvicorn
from app.main import create_app
from app.core.monitor import device_memory
from app.core.downloader import catalog_entry


async def run(a):
    blob = Path(a.image).read_bytes()
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif blob.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    else:
        raise ValueError("--image must be a JPEG or PNG")
    image = "data:" + mime + ";base64," + base64.b64encode(blob).decode()
    work = Path(a.work_dir).resolve()
    model_id = a.catalog_id or "vl-embedding"
    model_dir = work / "models" / model_id
    if a.catalog_id:
        if model_dir.exists():
            raise ValueError("catalogue acceptance requires a fresh model directory")
        if not catalog_entry(a.catalog_id):
            raise ValueError("unknown catalogue model")
    else:
        model_dir.mkdir(parents=True, exist_ok=True)
        for source, name in ((Path(a.bmodel).resolve(), Path(a.bmodel).name),
                             (Path(a.config).resolve(), "config")):
            target = model_dir / name
            if not target.exists():
                target.symlink_to(source)
            elif target.resolve() != source:
                raise ValueError(f"test directory already contains a different {name}")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    app = create_app(data_root=work, backend_kind=a.backend, native_lib=a.library,
                     install_dir=ROOT, web_dir=ROOT / "web/dist", agent_specs=[], service_port=port)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                          log_level="warning", access_log=False))
    server_task = asyncio.create_task(server.serve())
    checks = 0
    statuses = collections.Counter()
    latencies = []
    memory = {}
    started = time.perf_counter()
    inputs = ["A photograph of a meal.", {"image": image}, {"text": "A meal on a table.", "image": image}]
    config_dir = (ROOT / "model-config/wemm_embedding" if a.catalog_id == "wemm-embedding-2b"
                  else Path(a.config))
    manifest_file = config_dir / "embedding_config.json"
    wemm = manifest_file.exists() and json.loads(manifest_file.read_text()).get("model_type") == "wemm_embedding"
    download = None

    def check(condition, why):
        nonlocal checks
        checks += 1
        if not condition:
            raise AssertionError(why)

    try:
        while not server.started:
            if server_task.done():
                await server_task
            await asyncio.sleep(.05)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=300) as c:
            (await c.post("/api/login", json={"password": "admin"})).raise_for_status()
            key = (await c.post("/api/keys", json={"name": "vl-embedding-acceptance"})).json()["key"]
            inference_headers = {"Authorization": "Bearer " + key}
            if a.catalog_id:
                entry = catalog_entry(a.catalog_id)
                request = {"kind": "dfss", "name": model_id, "url": entry["dfss"],
                           "expected_bytes": entry["size_bytes"]}
                response = await c.post("/api/downloads", json=request)
                check(response.status_code == 200, response.text)
                job_id = response.json()["job"]["id"]
                deadline = time.monotonic() + a.download_timeout
                while True:
                    jobs = (await c.get("/api/downloads")).json()["jobs"]
                    job = next(j for j in jobs if j["id"] == job_id)
                    if job["state"] in ("done", "error", "cancelled"):
                        break
                    if time.monotonic() >= deadline:
                        await c.post(f"/api/downloads/{job_id}/cancel")
                        raise TimeoutError("dfss download deadline exceeded")
                    await asyncio.sleep(1)
                check(job["state"] == "done", job["message"])
                check("通过下载标签" in job["message"],
                      "download tag must work without URL fallback: " + job["message"])
                files = list(model_dir.glob("*.bmodel"))
                check(len(files) == 1 and not files[0].is_symlink(), "fresh downloaded bmodel")
                model = files[0]
                digests = {name: hashlib.new(name) for name in ("md5", "sha256")}
                with model.open("rb") as f:
                    for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
                        for digest in digests.values():
                            digest.update(chunk)
                distribution = json.loads((config_dir / "distribution.json").read_text())
                check(model.name == distribution["file"], "downloaded build name")
                check(model.stat().st_size == entry["size_bytes"], "downloaded size")
                check(digests["md5"].hexdigest() == entry["md5"], "downloaded md5")
                check(digests["sha256"].hexdigest() == distribution["sha256"], "downloaded sha256")
                # The UI rescans through this endpoint after the download. A
                # first install does not use the replacement-only callback.
                (await c.get("/api/models")).raise_for_status()
                info = app.state.models.get(model_id)
                check(info is not None and info.has_config, "downloaded model discovered with matching config")
                check(not (model_dir / "config").exists(), "no manually installed config")
                check(app.state.models.config_dir_for(info) == config_dir, "bundled matching config")
                download = {"job": job, "file": model.name, "bytes": model.stat().st_size,
                            "digests": {k: v.hexdigest() for k, v in digests.items()},
                            "config": str(config_dir.relative_to(ROOT)), "fresh": True}
            memory["before_load"] = device_memory()
            (await c.post(f"/api/models/{model_id}/load")).raise_for_status()

            async def embed(items, **extra):
                return await c.post("/v1/embeddings", json={"model": model_id, "input": items,
                                                           "dimensions": 128, **extra}, headers=inference_headers)

            baseline = await embed(inputs)
            check(baseline.status_code == 200, baseline.text)
            rows = baseline.json()["data"]
            memory["loaded"] = device_memory()
            check([r["index"] for r in rows] == [0, 1, 2], "batch order")
            for row in rows:
                vector = row["embedding"]
                check(len(vector) == 128 and abs(math.sqrt(sum(v*v for v in vector)) - 1) < 1e-5,
                      "finite unit vector with requested dimensions")
            check(len({tuple(r["embedding"]) for r in rows}) == 3, "modalities must not collapse")
            for index, item in enumerate(inputs):
                r = await embed(item)
                check(r.status_code == 200 and r.json()["data"][0]["embedding"] == rows[index]["embedding"],
                      "single/batch equivalence")
            encoded = await embed(inputs, encoding_format="base64")
            check(encoded.status_code == 200, encoded.text)
            for ref, row in zip(rows, encoded.json()["data"]):
                decoded = struct.unpack("<128f", base64.b64decode(row["embedding"]))
                check(max(abs(x-y) for x, y in zip(decoded, ref["embedding"])) < 1e-7, "float32 base64")
            for invalid in ({"image": "https://example.com/private"}, {"video": "a.mp4"},
                            ["valid first", "超长文本" * 4000], {"text": "x", "unknown": 1}):
                check((await embed(invalid)).status_code == 400, "invalid input must be 400")
            for dimension in (32, 2049):
                check((await embed("test", dimensions=dimension)).status_code == 400, "MRL bounds")
            first = await embed("cat", instruction="Retrieve images")
            second = await embed({"text": "cat"}, instruction="Retrieve images" if wemm else "Retrieve images.")
            check(first.status_code == second.status_code == 200 and first.json() == second.json(),
                  "instruction punctuation / input spelling")

            # 12 simultaneous HTTP registrations per wave, four waves. The
            # shared auxiliary queue is bounded: 429 is an expected admission
            # response; any successful request must retain its own vector.
            async def concurrent(index):
                before = time.perf_counter()
                r = await embed(inputs[index % 3])
                latencies.append((time.perf_counter() - before) * 1000)
                statuses[r.status_code] += 1
                check(r.status_code in (200, 429), f"concurrent status {r.status_code}: {r.text[:160]}")
                if r.status_code == 200:
                    check(r.json()["data"][0]["embedding"] == rows[index % 3]["embedding"], "cross-request isolation")

            for _ in range(4):
                await asyncio.gather(*(concurrent(i) for i in range(12)))
            check(statuses[200] >= 4, "concurrent requests make progress")
            memory["after_concurrent"] = device_memory()

            # A caller abandoning a full batch must not corrupt the
            # shared encoder or allow a second launch into its buffers.
            caller_timed_out = False
            try:
                await c.post("/v1/embeddings", json={"model": model_id, "input": [inputs[0]] * 64},
                             headers=inference_headers, timeout=.01)
            except httpx.TimeoutException:
                caller_timed_out = True
            check(caller_timed_out, "caller timeout was actually exercised")
            after = await embed(inputs[0])
            check(after.status_code == 200 and after.json()["data"][0]["embedding"] == rows[0]["embedding"],
                  "request after caller timeout")
            # Wait for the worker's accepted requests to drain through the
            # successful call above, then exercise actual unload/reload.
            unloaded = await c.post(f"/api/models/{model_id}/unload")
            check(unloaded.status_code == 200, unloaded.text)
            memory["after_unload"] = device_memory()
            if a.backend == "native":
                check(all(m["source"] == "bmlib" for m in memory.values()), "real device memory readings")
                check(memory["after_unload"]["used_bytes"] <= memory["before_load"]["used_bytes"] + 1024*1024,
                      "unload returns device memory to baseline")
            (await c.post(f"/api/models/{model_id}/load")).raise_for_status()
            reloaded = await embed(inputs[0])
            check(reloaded.status_code == 200 and reloaded.json()["data"][0]["embedding"] == rows[0]["embedding"],
                  "reload equivalence")
    finally:
        server.should_exit = True
        await server_task
    report = {"backend": a.backend, "checks_passed": checks, "concurrent_statuses": dict(statuses),
              "concurrent_requests": sum(statuses.values()), "latencies_ms": latencies,
              "device_memory": memory, "download": download,
              "elapsed_s": time.perf_counter() - started, "passed": True}
    Path(a.output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "latencies_ms"}), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--bmodel")
    source.add_argument("--catalog-id", choices=["wemm-embedding-2b"],
                        help="download through the real admin API into an empty directory")
    p.add_argument("--config", help="required with --bmodel; catalogue mode uses the bundled config")
    p.add_argument("--download-timeout", type=int, default=1800)
    p.add_argument("--library", required=True)
    p.add_argument("--work-dir", required=True)
    p.add_argument("--image", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--backend", choices=["native", "mock"], default="native")
    args = p.parse_args()
    if args.bmodel and not args.config:
        p.error("--config is required with --bmodel")
    if args.catalog_id and args.config:
        p.error("catalogue acceptance must use the installed bundled config")
    asyncio.run(run(args))
