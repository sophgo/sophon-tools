#!/usr/bin/env python3
"""Isolated repeat-probe through the *real* service stack (HTTP -> worker -> native).

``repeat_probe.py`` drives the native ``cv_vle_*`` C API directly. This one adds
the two layers production has and that script does not: the app's admin API, the
worker subprocess, and the ``VLEmbedder`` Python wrapper. It is the faithful
reproduction; ``repeat_probe.py`` is the reduction.

It creates a private data root (state, models) under ``--work-dir``, starts the
app on a free localhost port (never 8000), loads the model through the admin
API, then issues one serial matrix of ``/api/test/embeddings`` requests. Every
response's norm, non-zero count, status and worker timing is recorded. The
worker is drained and stopped in ``finally``; nothing outside ``--work-dir`` is
touched and no production port or model directory is used.

Images are synthesised from a fixed seed, so no customer data is involved.

Usage::

    python3 tools/vl_embed/repeat_probe_service.py \\
        --library /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \\
        --bmodel /data/.../wemm-...bmodel \\
        --config /opt/sophgo/cv84x6_llm_server/model-config/wemm_embedding \\
        --work-dir /tmp/mys2913/stack \\
        --output /tmp/mys2913/stack.json
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import httpx
import uvicorn
from app.main import create_app
from app.core.monitor import device_memory

# Reuse the PNG generator and the group plan so both probes run the same matrix.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from repeat_probe import GROUPS, plan, _size  # noqa: E402


def data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


async def run(a) -> dict:
    work = Path(a.work_dir).resolve()
    model_dir = work / "models" / a.model_id
    model_dir.mkdir(parents=True, exist_ok=True)
    bmodel = Path(a.bmodel).resolve()
    target = model_dir / bmodel.name
    if not target.exists():
        target.symlink_to(bmodel)
    elif target.resolve() != bmodel:
        raise SystemExit(f"{target} already points at a different bmodel")

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    app = create_app(data_root=work, backend_kind="native", native_lib=a.library,
                     install_dir=ROOT, web_dir=ROOT / "web/dist", agent_specs=[],
                     service_port=port)
    # The bundled config directory is what the release installs; the app resolves
    # it from the install dir, so point the model entry at it explicitly.
    config_dir = Path(a.config).resolve()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning", access_log=False))
    task = asyncio.create_task(server.serve())
    report = {"port": port, "work_dir": str(work), "groups": [],
              "device_memory": {}, "elapsed_s": None}
    started = time.perf_counter()
    small, large = _size(a.small), _size(a.large)
    try:
        while not server.started:
            if task.done():
                await task
            await asyncio.sleep(0.05)
        report["device_memory"]["before_load"] = device_memory()
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}",
                                     timeout=600) as c:
            (await c.post("/api/login", json={"password": "admin"})).raise_for_status()
            info = app.state.models.get(a.model_id)
            if info is None:
                raise SystemExit(f"model {a.model_id} not discovered under {model_dir}")
            # The app finds config next to the bmodel; link the bundled one so
            # the family/dimension contract is the release's, not a copy.
            link = model_dir / "config"
            if not link.exists():
                link.symlink_to(config_dir)
            (await c.post(f"/api/models/{a.model_id}/load")).raise_for_status()
            report["device_memory"]["loaded"] = device_memory()
            # /api/test/* is an admin surface: a plain inference key is answered
            # 403 on purpose ("you may not do this"). The console route the
            # operator used is this one, so the probe must use an admin key.
            key = (await c.post("/api/keys", json={"name": "mys2913-probe",
                                                   "scope": "admin"})).json()["key"]
            headers = {"Authorization": "Bearer " + key}

            for group in (GROUPS if a.group == "all" else [a.group]):
                result = {"group": group, "small": a.small, "large": a.large,
                          "calls": [], "faulted_at": None}
                for index, item in enumerate(plan(group, small, large)):
                    body = {"model": a.model_id, "input": []}
                    entry = {}
                    if item.get("png"):
                        entry["image"] = data_url(item["png"])
                        entry["text"] = ""
                    else:
                        entry["text"] = item.get("text", "")
                    body["input"] = [entry]
                    if a.dimensions:
                        body["dimensions"] = a.dimensions
                    if a.instruction:
                        body["instruction"] = a.instruction
                    began = time.perf_counter()
                    response = await c.post("/api/test/embeddings", json=body, headers=headers)
                    elapsed = round((time.perf_counter() - began) * 1000, 1)
                    record = {"index": index, "size": item.get("size"),
                              "kind": "image" if item.get("png") else "text",
                              "status": response.status_code, "http_ms": elapsed}
                    if response.status_code == 200:
                        payload = response.json()
                        vector = payload["data"][0]["embedding"]
                        record.update(
                            dim=len(vector),
                            norm=round(math.sqrt(sum(v * v for v in vector)), 9),
                            nonzero=sum(1 for v in vector if v != 0.0),
                            finite=all(math.isfinite(v) for v in vector),
                            head=[round(v, 6) for v in vector[:4]],
                            prompt_tokens=payload.get("usage", {}).get("prompt_tokens"),
                        )
                    else:
                        record["error"] = response.text[:400]
                    result["calls"].append(record)
                    if response.status_code != 200:
                        result["faulted_at"] = index
                        break
                report["groups"].append(result)
                if result["faulted_at"] is not None:
                    # The engine latches a fault; every later group would just
                    # report "reload required". Stop and say so.
                    report["stopped_after"] = group
                    break

            report["device_memory"]["after_matrix"] = device_memory()
            try:
                (await c.post(f"/api/models/{a.model_id}/unload")).raise_for_status()
            except httpx.HTTPError as exc:
                report["unload_error"] = str(exc)
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=120)
        except asyncio.TimeoutError:
            report["shutdown_timeout"] = True
        report["elapsed_s"] = round(time.perf_counter() - started, 1)
        report["device_memory"]["after_shutdown"] = device_memory()
    return report


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--library", required=True)
    p.add_argument("--bmodel", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--model-id", default="wemm-embedding-2b")
    p.add_argument("--work-dir", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--group", default="all")
    p.add_argument("--small", default="384x512", help="HxW pixels; 384x512 -> 204 tokens")
    p.add_argument("--large", default="192x1824", help="HxW pixels; 192x1824 -> 177 tokens")
    p.add_argument("--dimensions", type=int, default=None)
    p.add_argument("--instruction", default=None)
    a = p.parse_args()
    report = asyncio.run(run(a))
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    for group in report["groups"]:
        norms = " ".join(f"{c.get('norm', 'ERR')}" for c in group["calls"])
        status = " ".join(str(c["status"]) for c in group["calls"])
        verdict = "FAULT" if group["faulted_at"] is not None else "ok"
        print(f"[stack-probe] {group['group']:<16} {verdict:<5} status=[{status}] norms=[{norms}]",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
