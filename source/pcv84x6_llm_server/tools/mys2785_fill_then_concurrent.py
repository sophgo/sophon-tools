#!/usr/bin/env python3
"""Fill the cache, then run concurrent sessions: attribute the heap peak.

**This is the probe for a residual MYS-2785 does not fix, kept because the
measurement would otherwise be lost.** ``mys2785_board_measure.py`` shows the
cache filling to its ceiling and the heap staying inside the model's limit. Add
two long prompts on top of that full cache and the heap goes ~300-450 MiB above
``static + budget`` -- and it does so *identically on v0.6.32* (measured on
`.157`: peak 14392 MiB against a 14355 MiB limit, ``kv_used`` 1031 MiB against a
1024 MiB budget). So it is a property of ``Scheduler.reservation`` and the
engine, not of the byte ceiling this task removed: the reservation charges a
session its linear state plus KV per token, while the engine also allocates the
shared dynamic-prefill workspace, the resident-session park buffer (in 4096-slot
granules), and each parked session's own FA KV.

At every 0.5 s sample it records the device heap *and* the worker's own breakdown
(``cache.bytes``, ``kv_used_bytes``, ``kv_reserved_bytes``, ``inflight``), so the
peak can be compared with what the scheduler believed. That separates:

* the **cache** -- ``cache.bytes`` is near its ceiling at the peak;
* the **sessions** -- ``cache.bytes`` is already evicted but the heap is high;
* the **park/prefill machinery** -- ``cache + kv_used`` is well under the budget
  while the device is over it, i.e. the engine holds memory the accounting does
  not name.

Runs against whichever service ``--base`` names, so v0.6.32 can be the control
for this branch. ``--skip-fill`` measures the concurrent phase from an empty
cache instead.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time

MIB = 1 << 20
BM_SMI = "/opt/sophon/libsophon-current/bin/bm-smi"


def npu() -> int | None:
    from app.core.monitor import parse_bm_smi
    try:
        raw = subprocess.run([BM_SMI, "-noloop"], capture_output=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_bm_smi(raw).get("mem_used_bytes")


def ask(c, headers: dict, model: str, system: str, max_tokens: int = 32) -> dict:
    with c.stream("POST", "/v1/chat/completions", headers=headers, json={
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": "Summarise in one line."}],
            "max_tokens": max_tokens, "stream": True,
            "stream_options": {"include_usage": True}}) as s:
        usage = {}
        for line in s.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                d = json.loads(line[6:])
                if d.get("usage"):
                    usage = d["usage"]
    return usage


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--model", required=True)
    ap.add_argument("--limit-over-static-mb", type=int, default=1024)
    ap.add_argument("--fill-rounds", type=int, default=14)
    ap.add_argument("--concurrent", type=int, default=2)
    ap.add_argument("--skip-fill", action="store_true")
    ap.add_argument("--out", default="mys2785-fill-then-concurrent.json")
    a = ap.parse_args()

    import httpx

    c = httpx.Client(base_url=a.base, timeout=1800)
    c.post("/api/login", json={"password": "admin"})
    view = c.get(f"/api/models/{a.model}/settings").json()
    static = view["mem_static_bytes"]
    limit_mb = static // MIB + a.limit_over_static_mb
    if view["effective"].get("mem_limit_bytes"):
        c.post(f"/api/models/{a.model}/unload")
    assert c.put(f"/api/models/{a.model}/settings",
                 json={"mem_limit_mb": limit_mb}).status_code == 200
    assert c.post(f"/api/models/{a.model}/load").status_code == 200
    st = c.get("/api/stats").json()["workers"][a.model]
    budget = st["kv_budget_bytes"]
    print(f"static {static / MIB:.0f} MiB, limit {limit_mb} MiB, budget {budget / MIB:.0f} MiB",
          flush=True)
    key = c.post("/api/keys", json={"name": "fillconc"}).json()["key"]
    h = {"Authorization": f"Bearer {key}"}

    if not a.skip_fill:
        print("filling the cache…", flush=True)
        for i in range(a.fill_rounds):
            ask(c, h, a.model,
                "Plant log entry. " * 130 + f"volume {i} region {chr(65 + i % 26)} " * 20)
        w = c.get("/api/stats").json()["workers"][a.model]
        print(f"cache {w['cache']['bytes'] / MIB:.0f} / "
              f"{w['cache']['max_bytes'] / MIB:.0f} MiB over {w['cache']['entries']} entries",
              flush=True)

    idle = npu()
    samples: list[dict] = []
    stop = threading.Event()

    def sampler() -> None:
        while not stop.is_set():
            w = c.get("/api/stats").json()["workers"][a.model]
            samples.append({
                "t": time.time(), "npu": npu(),
                "cache": w["cache"]["bytes"], "entries": w["cache"]["entries"],
                "kv_used": w["kv_used_bytes"], "reserved": w["kv_reserved_bytes"],
                "inflight": w["inflight"], "waiting": w["waiting_for_memory"],
            })
            stop.wait(0.5)

    def one(i: int) -> dict:
        system = ("Plant log entry. " * 900) + f"concurrent probe {i}"
        with httpx.Client(base_url=a.base, timeout=1800) as cc:
            return ask(cc, h, a.model, system)

    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=a.concurrent) as pool:
        toks = list(pool.map(one, range(a.concurrent)))
    time.sleep(6)
    stop.set()
    th.join(timeout=15)

    peak_s = max(samples, key=lambda s: s["npu"] or 0)
    peak = peak_s["npu"]
    print()
    t0 = samples[0]["t"]
    for s in samples:
        over = (s["npu"] or 0) > limit_mb * MIB
        print(f"{s['t'] - t0:6.1f}s NPU {(s['npu'] or 0) / MIB:8.0f} "
              f"cache {s['cache'] / MIB:6.0f} kv_used {s['kv_used'] / MIB:7.0f} "
              f"reserved {s['reserved'] / MIB:5.0f} inflight {s['inflight']}"
              + ("  OVER LIMIT" if over else ""), flush=True)
    print()
    print(f"prompt tokens {[t.get('prompt_tokens') for t in toks]}", flush=True)
    print(f"idle {idle / MIB:.0f} MiB, peak {peak / MIB:.0f} MiB "
          f"(+{(peak - idle) / MIB:.0f} over idle, limit is "
          f"{limit_mb - static / MIB:.0f} MiB above static)", flush=True)
    print(f"at the peak: cache {peak_s['cache'] / MIB:.0f} MiB, "
          f"kv_used {peak_s['kv_used'] / MIB:.0f} MiB, "
          f"accounted {max(peak_s['cache'], peak_s['kv_used']) / MIB:.0f} MiB "
          f"of a {budget / MIB:.0f} MiB budget", flush=True)
    with open(a.out, "w") as f:
        json.dump({"static": static, "limit_mb": limit_mb, "budget": budget,
                   "idle": idle, "samples": samples,
                   "prompt_tokens": [t.get("prompt_tokens") for t in toks]}, f, indent=2)
    print(f"wrote {a.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
