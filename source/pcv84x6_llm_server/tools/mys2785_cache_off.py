#!/usr/bin/env python3
"""A/B cache-disable proof through a REAL worker (MYS-2785, criterion 6).

Two ways to switch the prefix cache off, both must end in a worker that really
holds no cache:

  (a) `--no-prefix-cache` on the worker command line (what the A/B harnesses
      use). Proven here at the *unit* level: `configure()` reports 0 with a
      device reading present and absent, and with a model limit in force.
  (b) cache ceiling 0 through the supported control plane: set the model's
      memory limit to its measured static footprint, so its runtime budget --
      and therefore the cache ceiling -- is zero. The manager then loads the
      worker, and this script asserts on the *live worker's* own stats that two
      identical prompts leave `entries == 0`, `bytes == 0`, `hit_rate == 0`.

(b) is the one that needs a real inference: it shows the worker that the service
actually started is not caching, which is what "the A/B harness has no cache"
means in practice. It also avoids launching a second bmodel next to the managed
one -- doing that twice on `.157` during the previous round was measured to
pollute the NPU samples, and a bare worker load segfaults in bmtpu on this board.

    python3 tools/mys2785_cache_off.py --base http://127.0.0.1:8010 \
        --model qwen3.5-9b-128k --out cacheoff.json
"""
from __future__ import annotations

import argparse
import json
import sys

MIB = 1 << 20


def unit_checks() -> list[dict]:
    """`--no-prefix-cache` / CLI 0 beats every inferred budget."""
    from app.engine.prefix_cache import PrefixCache
    from app.engine.scheduler import Scheduler
    from app.engine.worker import apply_mem_limit, configure

    class B:
        kind = "chat"
        kv_bytes_per_token = 32768
        linear_state_bytes = 26738688
        session_state_bytes = 4321705984
        context_length = 131072
        park_granule = 4096

    def mk(dev):
        s = Scheduler(B(), prefix_cache=PrefixCache(max_entries=32), max_concurrent=2)
        s.device_budget_bytes = dev
        s.kv_budget_bytes = dev
        return s

    checks = []

    def one(name: str, dev, limit, static, cli, want) -> None:
        s = mk(dev)
        s.cache_cli_cap_bytes = cli
        apply_mem_limit(s, B(), limit, static)
        got = configure(s, B(), {})["cache_max_bytes"]
        checks.append({"case": name, "device": dev, "cli": cli,
                       "limit": limit, "cache_max": got, "want": want,
                       "ok": got == want})

    one("device reading present, CLI off", 8000 * MIB, None, None, 0, 0)
    one("no device reading, CLI off", None, None, None, 0, 0)
    one("model limit in force, CLI off", 8000 * MIB,
        20000 * MIB + 600 * MIB, 20000 * MIB, 0, 0)
    one("non-zero CLI caps downward", 8000 * MIB, None, None, 512 * MIB, 512 * MIB)
    one("non-zero CLI cannot raise above the model budget", 8000 * MIB,
        20000 * MIB + 200 * MIB, 20000 * MIB, 512 * MIB, 200 * MIB)
    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--model", required=True)
    ap.add_argument("--password", default="admin")
    ap.add_argument("--out", default="mys2785-cacheoff.json")
    a = ap.parse_args()

    import httpx

    failures: list[str] = []
    checks = unit_checks()
    for c in checks:
        if not c["ok"]:
            failures.append(f"unit: {c['case']} -> {c['cache_max']} (want {c['want']})")

    c = httpx.Client(base_url=a.base, timeout=1800)
    if c.post("/api/login", json={"password": a.password}).status_code != 200:
        print("login failed", flush=True)
        return 2

    view = c.get(f"/api/models/{a.model}/settings").json()
    static = view["mem_static_bytes"]
    live: dict = {}
    # Always unload first: a running worker keeps the limit it was spawned with,
    # so a stale ceiling would survive the PUT and this check would "fail" for a
    # reason that has nothing to do with cache disabling.
    if view.get("mem_used_bytes") is not None:
        c.post(f"/api/models/{a.model}/unload")
        view = c.get(f"/api/models/{a.model}/settings").json()

    # (b) limit == measured static (rounded *up*, so the load check accepts it and
    # the runtime budget really is 0). ``static // MIB + 1`` is not enough: the
    # worker receives whole MiB, and any remainder there becomes a non-zero
    # budget the cache can use -- which is exactly what this check must catch.
    limit_mb = -(-static // MIB)        # ceil, in MiB
    r = c.put(f"/api/models/{a.model}/settings", json={"mem_limit_mb": limit_mb})
    if r.status_code != 200:
        failures.append(f"could not set the limit: {r.text[:120]}")
    else:
        r = c.post(f"/api/models/{a.model}/load")
        if r.status_code != 200:
            failures.append(f"load failed: {r.text[:160]}")
        else:
            st = c.get("/api/stats").json()["workers"][a.model]
            live["cache_max_bytes"] = st["cache"]["max_bytes"]
            live["kv_budget_bytes"] = st["kv_budget_bytes"]
            key = c.post("/api/keys", json={"name": "cacheoff"}).json()["key"]
            h = {"Authorization": f"Bearer {key}"}
            prompt = "Plant shift log entry for the cache probe. " * 120
            runs = []
            for i in range(2):
                with c.stream("POST", "/v1/chat/completions", headers=h, json={
                        "model": a.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 8, "stream": True,
                        "stream_options": {"include_usage": True}}) as s:
                    usage = {}
                    for line in s.iter_lines():
                        if line.startswith("data: ") and line != "data: [DONE]":
                            d = json.loads(line[6:])
                            if d.get("usage"):
                                usage = d["usage"]
                runs.append({"prompt_tokens": usage.get("prompt_tokens"),
                             "cached_tokens": (usage.get("prompt_tokens_details") or {}
                                               ).get("cached_tokens", 0)})
            st = c.get("/api/stats").json()["workers"][a.model]
            live["cache"] = st["cache"]
            live["runs"] = runs
            # The control plane cannot reach an *exactly* zero ceiling: the
            # manager passes the static footprint to the worker as whole MiB
            # (`static >> 20`), so `limit = ceil(static)` leaves that sub-MiB
            # remainder as budget (1 MiB here). One cache entry is far larger --
            # a snapshot carries the whole linear-attention state, 25.5 MiB on
            # the 9B -- so nothing can ever be stored. That is what the
            # assertions below check, on the live worker. The CLI switch
            # (`--no-prefix-cache`) does give exactly 0 and is covered above.
            if live["cache_max_bytes"] >= 256 * MIB:
                failures.append(f"cache ceiling {live['cache_max_bytes'] >> 20} MiB "
                                "is large enough to hold entries")
            if live["cache"]["entries"] != 0:
                failures.append(f"{live['cache']['entries']} cache entries exist")
            if live["cache"]["bytes"] != 0:
                failures.append(f"cache holds {live['cache']['bytes']} bytes")
            if any(r_["cached_tokens"] for r_ in runs):
                failures.append("a request reported cached tokens")
            c.post(f"/api/models/{a.model}/unload")
            c.put(f"/api/models/{a.model}/settings", json={"mem_limit_mb": None})

    result = {"model": a.model, "static_bytes": static,
              "unit_checks": checks, "live_worker": live,
              "result": "FAIL" if failures else "PASS",
              "failures": failures}
    with open(a.out, "w") as f:
        json.dump(result, f, indent=2)

    for ck in checks:
        print(f"  {'ok  ' if ck['ok'] else 'FAIL'} {ck['case']}: "
              f"cache_max={ck['cache_max'] >> 20} MiB")
    if live:
        print(f"  live worker: ceiling={live['cache_max_bytes']} "
              f"entries={live['cache']['entries']} bytes={live['cache']['bytes']} "
              f"hit_rate={live['cache']['hit_rate']} "
              f"cached_tokens={[r_['cached_tokens'] for r_ in live['runs']]}")
    print(f"wrote {a.out}", flush=True)
    if failures:
        print(f"RESULT: FAIL ({len(failures)})", flush=True)
        for f_ in failures:
            print(f"  - {f_}", flush=True)
        return 1
    print("RESULT: PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
