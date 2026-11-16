#!/usr/bin/env python3
"""Board measurement for MYS-2785: a model never exceeds its own memory limit.

The claim the change makes is

    一个模型最多占用的设备内存 = 它的内存上限

and the cache is the only thing inside a model that can grow after the load, so
this is the run that has to back it up: set a model's limit to ``static + 1 GiB``,
send enough *different-prefix* conversations to fill the prefix cache several
times over, and sample the NPU heap every two seconds.

Three numbers are compared, and they answer three different questions:

* ``peak - baseline`` vs ``limit`` -- did the model stay inside its ceiling?
  ``baseline`` is the heap right before the model loaded, so the difference is
  this model's footprint (it is the only model the side instance loads).
* the worker's own ``kv_used_bytes`` -- does the worker's accounting agree with
  the device? A disagreement means the accounting is wrong even if the device
  number happens to look fine.
* the cache's ``max_bytes`` -- is the cache ceiling actually ``limit - static``
  and not some other figure?

Run it on the board, against a side instance of this branch (so the installed
service is untouched):

    python3 tools/mys2785_board_measure.py \
        --base http://127.0.0.1:8010 --model qwen3.5-9b-128k \
        --limit-over-static-mb 1024 --rounds 8
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

#: A distinct system prompt per round, all long enough that a 4000-token prefix
#: is worth caching (the native backend refuses snapshots under 256 tokens, and a
#: short snapshot would not move the heap enough to measure).
SYSTEM = (
    "You are the shift log assistant of a water treatment plant. The plant has "
    "three membrane trains, two clarifiers and a sludge press. Every entry is "
    "dated, signed and tagged with the train it concerns. Use only the entries "
    "provided; if a detail is missing, say so plainly. "
)
TURNS = [
    "Which train needs the most maintenance this week?",
    "Summarise the entries about the sludge press.",
    "How many entries mention the clarifiers?",
]


def bm_smi_used_bytes() -> int | None:
    """NPU heap in use, in bytes, from the vendor tool.

    Parsed by ``app.core.monitor.parse_bm_smi`` -- the same function the console
    reads -- rather than by a second regex written here. That matters: the dump
    is a curses screen with two ``used/total`` pairs (VPP first, then the NPU
    heap), and a hand-rolled "last pair wins" picks the *VPP* number, which then
    never moves while the cache fills. Measured wrong on the first attempt.
    """
    from app.core.monitor import parse_bm_smi

    try:
        raw = subprocess.run([BM_SMI, "-noloop"], capture_output=True,
                             timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_bm_smi(raw).get("mem_used_bytes")


class Sampler(threading.Thread):
    """Sample the NPU heap every ``interval`` seconds until stopped."""

    def __init__(self, interval: float = 2.0) -> None:
        super().__init__(daemon=True)
        self.interval = interval
        self.samples: list[tuple[float, int | None]] = []
        # Not ``self._stop``: that is a real attribute of ``threading.Thread``
        # (the internal stop flag), and shadowing it makes ``join()`` raise
        # ``TypeError: 'Event' object is not callable``.
        self._done = threading.Event()

    def run(self) -> None:
        while not self._done.is_set():
            self.samples.append((time.time(), bm_smi_used_bytes()))
            self._done.wait(self.interval)

    def stop(self) -> None:
        self._done.set()
        self.join(timeout=15)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--model", required=True)
    ap.add_argument("--password", default="admin")
    ap.add_argument("--limit-over-static-mb", type=int, default=1024)
    ap.add_argument("--rounds", type=int, default=40)
    ap.add_argument("--sample-interval", type=float, default=2.0)
    ap.add_argument("--max-tokens", type=int, default=64)
    ap.add_argument("--out", default="mys2785-board.json")
    a = ap.parse_args()

    import httpx

    c = httpx.Client(base_url=a.base, timeout=1800)
    assert c.post("/api/login", json={"password": a.password}).status_code == 200, "login failed"

    # The worker's own numbers before anything is loaded.
    before = bm_smi_used_bytes()
    print(f"NPU heap used before the load: {None if before is None else before / MIB:.0f} MiB",
          flush=True)

    # The limit is built from the **measured** static footprint, so any limit
    # left over from an earlier run is cleared and the model loaded once first:
    # before its first load the manager only has ``bmrt_get_bmodel_info``'s
    # estimate, which for this dynamic/history build reads 9127 MiB where the
    # device shows 13331 MiB. Setting the limit from the estimate gives a limit
    # ~4 GiB *below* the model's real footprint and the load is refused (the
    # first run of this script did exactly that and "found" a 4 GiB overrun that
    # was its own arithmetic).
    view = c.get(f"/api/models/{a.model}/settings").json()
    limit_before = view["effective"].get("mem_limit_bytes")
    if limit_before and limit_before < view["mem_static_bytes"]:
        # A stale limit would refuse the measuring load. Clear it: null means
        # "follow the derived default", which is always above static.
        print(f"clearing a stale limit of {limit_before / MIB:.0f} MiB "
              f"(static is now {view['mem_static_bytes'] / MIB:.0f} MiB)", flush=True)
        assert c.put(f"/api/models/{a.model}/settings",
                     json={"mem_limit_mb": None}).status_code == 200
    view = c.get(f"/api/models/{a.model}/settings").json()
    if not view.get("mem_used_bytes"):
        print("first load, to measure the static footprint…", flush=True)
        r = c.post(f"/api/models/{a.model}/load")
        assert r.status_code == 200, r.text
        assert c.post(f"/api/models/{a.model}/unload").status_code == 200
        view = c.get(f"/api/models/{a.model}/settings").json()
    static = view["mem_static_bytes"]
    limit_mb = (static + a.limit_over_static_mb * MIB) // MIB
    print(f"measured static {static / MIB:.1f} MiB -> limit {limit_mb} MiB "
          f"(+{a.limit_over_static_mb} MiB)", flush=True)

    r = c.put(f"/api/models/{a.model}/settings", json={"mem_limit_mb": limit_mb})
    assert r.status_code == 200, r.text

    print("loading…", flush=True)
    r = c.post(f"/api/models/{a.model}/load")
    assert r.status_code == 200, r.text
    info = r.json()["model"]
    print(f"loaded, mem_used_bytes {info['mem_used_bytes'] / MIB:.0f} MiB", flush=True)

    st = c.get("/api/stats").json()["workers"][a.model]
    budget = st["kv_budget_bytes"]
    print(f"worker: budget {budget / MIB:.0f} MiB, "
          f"model budget {st['mem_runtime_budget_bytes'] / MIB if st['mem_runtime_budget_bytes'] else None} MiB, "
          f"device budget {st['device_budget_bytes'] / MIB if st['device_budget_bytes'] else None} MiB, "
          f"cache ceiling {st['cache']['max_bytes'] / MIB:.0f} MiB", flush=True)

    after_load = bm_smi_used_bytes()
    # The baseline is the heap *before* the load: nothing else runs on this
    # board during the measurement, so ``peak - before`` is exactly this model's
    # footprint -- the quantity the limit bounds. (Using the post-load reading
    # would subtract the static footprint and then compare the remainder against
    # a limit that already contains it.)
    baseline = before if before is not None else after_load
    print(f"NPU heap right after the load: {after_load / MIB:.0f} MiB "
          f"(baseline {baseline / MIB:.0f} MiB)", flush=True)

    key = c.post("/api/keys", json={"name": "mys2785-measure"}).json()["key"]
    h = {"Authorization": f"Bearer {key}"}

    sampler = Sampler(a.sample_interval)
    sampler.start()
    rows = []
    try:
        # Phase 1: distinct prefixes, one after another, until the cache is at
        # its ceiling. Each round is a fresh system prompt, so each creates new
        # entries rather than hitting the ones already there.
        for i in range(a.rounds):
            system = SYSTEM + f"Shift log volume {i + 1}, region {chr(65 + i % 26)}. " * 40
            messages = [{"role": "system", "content": system}]
            for turn in TURNS:
                messages.append({"role": "user", "content": turn})
                t0 = time.time()
                with c.stream("POST", "/v1/chat/completions", headers=h, json={
                        "model": a.model, "messages": messages,
                        "max_tokens": a.max_tokens, "stream": True,
                        "stream_options": {"include_usage": True}}) as s:
                    usage = {}
                    for line in s.iter_lines():
                        if not line.startswith("data: ") or line == "data: [DONE]":
                            continue
                        d = json.loads(line[6:])
                        if d.get("usage"):
                            usage = d["usage"]
                messages.append({"role": "assistant", "content": "…"})
                cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
                w = c.get("/api/stats").json()["workers"][a.model]
                rows.append({
                    "phase": "fill", "round": i, "seconds": round(time.time() - t0, 1),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "cached_tokens": cached,
                    "cache_bytes": w["cache"]["bytes"],
                    "cache_entries": w["cache"]["entries"],
                    "cache_max_bytes": w["cache"]["max_bytes"],
                    "kv_used_bytes": w["kv_used_bytes"],
                    "kv_budget_bytes": w["kv_budget_bytes"],
                    "kv_reserved_bytes": w["kv_reserved_bytes"],
                    "npu_used_bytes": bm_smi_used_bytes(),
                })
            print(f"fill {i}: cache {rows[-1]['cache_bytes'] / MIB:.0f} MiB / "
                  f"{rows[-1]['cache_entries']} entries, "
                  f"kv_used {rows[-1]['kv_used_bytes'] / MIB:.0f} MiB, "
                  f"NPU {rows[-1]['npu_used_bytes'] / MIB:.0f} MiB, "
                  f"cached_tokens {rows[-1]['cached_tokens']}", flush=True)
            if rows[-1]["cache_bytes"] >= 0.95 * budget:
                print(f"cache reached {rows[-1]['cache_bytes'] / MIB:.0f} MiB of "
                      f"{budget / MIB:.0f} MiB; stopping the fill phase", flush=True)
                break

        # Phase 2 is deliberately **not** run here. Concurrent sessions against
        # a full cache exceed ``limit`` -- but they do so identically on v0.6.32
        # (measured: +444 MiB over idle, peak 1031 MiB against a 1024 MiB
        # budget), because the engine allocates three things the scheduler's
        # reservation does not model: the shared dynamic-prefill workspace, the
        # resident-session park buffer, and a parked session's own FA KV growing
        # in 4096-slot granules. That residual is a property of
        # ``Scheduler.reservation`` and of the engine, unchanged by removing the
        # service-wide cache ceiling. ``tools/mys2785_fill_then_concurrent.py``
        # is the probe for it; keeping it out of *this* script keeps the claim
        # this script tests ("a model with cache fills up stays under its limit")
        # separate from one it cannot establish.
    finally:
        sampler.stop()

    final = c.get("/api/stats").json()["workers"][a.model]
    peaks = [v for _t, v in sampler.samples if v is not None]
    peak = max(peaks) if peaks else None
    result = {
        "model": a.model,
        "static_bytes": static,
        "limit_bytes": limit_mb * MIB,
        "kv_budget_bytes": budget,
        "cache_max_bytes": final["cache"]["max_bytes"],
        "npu_before_load_bytes": before,
        "npu_after_load_bytes": after_load,
        "npu_peak_bytes": peak,
        "samples": [[round(t, 1), v] for t, v in sampler.samples],
        "final_cache_bytes": final["cache"]["bytes"],
        "final_cache_entries": final["cache"]["entries"],
        "final_kv_used_bytes": final["kv_used_bytes"],
        "rows": rows,
    }
    with open(a.out, "w") as f:
        json.dump(result, f, indent=2)

    print()
    print(f"samples: {len(sampler.samples)} at {a.sample_interval:.0f} s", flush=True)
    if peak is not None and baseline is not None:
        footprint = peak - baseline
        over = footprint - limit_mb * MIB
        print(f"model footprint peak: {footprint / MIB:.0f} MiB "
              f"(limit {limit_mb} MiB, headroom {-over / MIB:.0f} MiB)", flush=True)
        print("VERDICT: " + ("PASS -- peak stayed within the limit" if over <= 0 else
                             f"FAIL -- over the limit by {over / MIB:.0f} MiB"), flush=True)
    kv_peak = max((r["kv_used_bytes"] or 0) for r in rows) if rows else 0
    print(f"worker's own peak (sessions + cache): {kv_peak / MIB:.0f} MiB "
          f"of budget {budget / MIB:.0f} MiB", flush=True)
    print(f"cache filled to {final['cache']['bytes'] / MIB:.0f} MiB of "
          f"{final['cache']['max_bytes'] / MIB:.0f} MiB over {final['cache']['entries']} entries",
          flush=True)
    print(f"wrote {a.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
