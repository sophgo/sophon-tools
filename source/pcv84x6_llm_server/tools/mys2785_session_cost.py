#!/usr/bin/env python3
"""What does a parked session cost the NPU, really? (MYS-2785, second round)

The acceptance run showed the device ~78 MiB above what the worker accounts for
while two sessions are live, with both ``cache.bytes`` and ``kv_used_bytes`` under
budget. This isolates the per-session figure directly, because the candidates all
scale differently with prompt length:

* **park granularity** -- `round_up(tokens, 4096)` slots. Steps at 4096, 8192.
* **a growth step** -- old + new buffer alive together; a jump, not a slope.
* **a fixed per-session cost** -- constant in the prompt length.

Method: one session at a time, cache off (limit == static), so the only thing on
the heap is the session and its park buffer. Sample the device at 0.5 s and
record `peak - idle` beside the scheduler's own `reservation()` for the same
prompt. The difference is what the accounting misses, and how it moves with the
prompt length says which candidate it is.

    python3 tools/mys2785_session_cost.py --base http://127.0.0.1:8010 \
        --model qwen3.5-9b-128k --lengths 1200,2600,4800,9000 --out cost.json
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


def npu_used() -> int | None:
    from app.core.monitor import parse_bm_smi
    try:
        raw = subprocess.run([BM_SMI, "-noloop"], capture_output=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_bm_smi(raw).get("mem_used_bytes")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--model", required=True)
    ap.add_argument("--lengths", default="1200,2600,4800,9000")
    ap.add_argument("--max-tokens", type=int, default=32)
    ap.add_argument("--concurrent", type=int, default=1)
    ap.add_argument("--out", default="mys2785-session-cost.json")
    a = ap.parse_args()

    import httpx

    c = httpx.Client(base_url=a.base, timeout=3600)
    c.post("/api/login", json={"password": "admin"})

    view = c.get(f"/api/models/{a.model}/settings").json()
    static = view["mem_static_bytes"]
    # Cache off, so nothing but the session moves the heap.
    if view["effective"].get("mem_limit_bytes"):
        c.post(f"/api/models/{a.model}/unload")
        view = c.get(f"/api/models/{a.model}/settings").json()
    assert c.put(f"/api/models/{a.model}/settings",
                 json={"mem_limit_mb": static // MIB + 1}).status_code == 200
    assert c.post(f"/api/models/{a.model}/load").status_code == 200
    st = c.get("/api/stats").json()["workers"][a.model]
    print(f"cache ceiling {st['cache']['max_bytes'] / MIB:.0f} MiB "
          f"(cache is off for this probe)", flush=True)

    key = c.post("/api/keys", json={"name": "session-cost"}).json()["key"]
    h = {"Authorization": f"Bearer {key}"}
    rows = []

    for want in [int(x) for x in a.lengths.split(",") if x.strip()]:
        # ~3.5 chars/token for this text; the real count comes back in usage.
        system = "Plant log entry. " * max(1, want // 4)
        body = [{"role": "system", "content": system},
                {"role": "user", "content": "Summarise in one line."}]

        idle = npu_used()
        peak = idle
        stop = threading.Event()

        def sampler() -> None:
            nonlocal peak
            while not stop.is_set():
                v = npu_used()
                if v:
                    peak = max(peak, v)
                stop.wait(0.5)

        th = threading.Thread(target=sampler, daemon=True)
        th.start()

        def one(_i: int) -> dict:
            import httpx
            with httpx.Client(base_url=a.base, timeout=3600) as cc:
                with cc.stream("POST", "/v1/chat/completions", headers=h, json={
                        "model": a.model, "messages": body,
                        "max_tokens": a.max_tokens, "stream": True,
                        "stream_options": {"include_usage": True}}) as s:
                    usage = {}
                    for line in s.iter_lines():
                        if line.startswith("data: ") and line != "data: [DONE]":
                            d = json.loads(line[6:])
                            if d.get("usage"):
                                usage = d["usage"]
                    return usage

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=a.concurrent) as pool:
            usages = list(pool.map(one, range(a.concurrent)))
        usage = usages[0]
        time.sleep(4)
        stop.set()
        th.join(timeout=15)

        w = c.get("/api/stats").json()["workers"][a.model]
        tokens = usage.get("prompt_tokens") or 0
        row = {
            "prompt_tokens": tokens, "concurrent": a.concurrent,
            "reserved_bytes": w["kv_reserved_bytes"],
            "kv_used_bytes": w["kv_used_bytes"],
            "npu_idle_bytes": idle, "npu_peak_bytes": peak,
            "measured_bytes": (peak - idle) if (peak and idle) else None,
        }
        rows.append(row)
        if row["measured_bytes"] is not None:
            print(f"{tokens:6d} tok: device +{row['measured_bytes'] / MIB:7.1f} MiB, "
                  f"kv_used {row['kv_used_bytes'] / MIB:7.1f} MiB, "
                  f"gap {(row['measured_bytes'] - row['kv_used_bytes']) / MIB:7.1f} MiB",
                  flush=True)

    with open(a.out, "w") as f:
        json.dump({"static": static, "rows": rows}, f, indent=2)
    print(f"wrote {a.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
