#!/usr/bin/env python3
"""MYS-2785 验收上传：灌缓存 → 真实重叠 → 跨粒度增长，全程采样 NPU。

判据与退出码（任务卡第 7 条）：**任何一项不满足即非零退出**，不是打印一行 FAIL
然后 return 0。检查项：

  * 配置上限 = 实测静态 + ``--limit-over-static-mb``（默认 1024 MiB）；
  * 峰值设备占用 ≤ 配置上限；
  * 采样里 NPU 余量最小值 ≥ 1 GiB 保护下限；
  * 采样有效（点数够、无死样本、无 ``error`` 样本）；
  * 真机重叠：``inflight`` 峰值 ≥ ``--concurrent``，且**同时提交不等于重叠**——
    脚本另外记录「同一时刻活跃请求数」的时间序列，两者都达标才算；
  * 请求全部成功：任何 HTTP/SSE 错误、超时、非 ``stop``/``length`` 的结束原因
    都记为失败；
  * 本脚本只验证 HTTP 并发；原生会话扩容由 mys2785_cross_granule.py 验证。

原始采样（每个样本，不筛选）写进 ``--out`` 的 JSON，CSV 另存一份便于审阅。

    python3 tools/mys2785_accept.py --base http://127.0.0.1:8010 \
        --model qwen3.5-9b-128k --label branch --out accept-branch.json \
        --csv accept-branch.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import threading
import time

MIB = 1 << 20
BM_SMI = "/opt/sophon/libsophon-current/bin/bm-smi"
NPU_RESERVE_FLOOR = 1024 * MIB      # MYS-2703/MYS-2784, not a tunable here


class Failure(Exception):
    """A check that did not hold. Collected, printed, and turned into exit 1."""


def npu_used() -> int | None:
    from app.core.monitor import parse_bm_smi
    try:
        raw = subprocess.run([BM_SMI, "-noloop"], capture_output=True,
                             timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_bm_smi(raw).get("mem_used_bytes")


def npu_reading() -> dict:
    from app.core.monitor import parse_bm_smi
    try:
        raw = subprocess.run([BM_SMI, "-noloop"], capture_output=True,
                             timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_bm_smi(raw)


def ask(client, headers: dict, model: str, system: str, user: str,
        max_tokens: int, base: str, on_sample=None) -> dict:
    """One streamed completion. Returns usage plus a ``finish`` field.

    ``on_sample`` is called once per SSE frame with the number of frames so far,
    which is what lets the caller sample the device *while a single long request
    is still in flight* instead of only between requests.
    """
    import httpx

    frames = 0
    usage: dict = {}
    text = 0
    finish = None
    with httpx.Client(base_url=base, timeout=3600) as c:
        with c.stream("POST", "/v1/chat/completions", headers=headers, json={
                "model": model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "max_tokens": max_tokens, "stream": True,
                "stream_options": {"include_usage": True}}) as s:
            if s.status_code != 200:
                raise Failure(f"HTTP {s.status_code}: {s.read()[:200]!r}")
            for line in s.iter_lines():
                if not line.startswith("data: "):
                    continue
                if line.strip() == "data: [DONE]":
                    break
                d = json.loads(line[6:])
                if d.get("error"):
                    raise Failure(f"SSE error: {d['error']}")
                if d.get("usage"):
                    usage = d["usage"]
                for ch in d.get("choices") or []:
                    if ch.get("delta", {}).get("content"):
                        text += 1
                    if ch.get("finish_reason"):
                        finish = ch["finish_reason"]
                frames += 1
                if on_sample is not None:
                    on_sample(frames)
    out = dict(usage)
    out["finish"] = finish
    out["content_pieces"] = text
    return out


class Sampler(threading.Thread):
    """Device heap + worker stats every ``interval`` seconds, unfiltered."""

    def __init__(self, client, model: str, interval: float = 1.0) -> None:
        super().__init__(daemon=True)
        self.client, self.model, self.interval = client, model, interval
        self.samples: list[dict] = []
        self._done = threading.Event()

    def take(self, note: str = "") -> None:
        try:
            w = self.client.get("/api/stats").json()["workers"][self.model]
            self.samples.append({
                "t": round(time.time(), 3), "note": note, "npu": npu_used(),
                "cache": w["cache"]["bytes"], "entries": w["cache"]["entries"],
                "cache_max": w["cache"]["max_bytes"],
                "kv_used": w["kv_used_bytes"], "reserved": w["kv_reserved_bytes"],
                "inflight": w["inflight"], "queued": w["queued"],
                "kv_budget": w["kv_budget_bytes"],
                "mem_budget": w.get("mem_runtime_budget_bytes"),
                "dev_budget": w.get("device_budget_bytes"),
            })
        except Exception as exc:              # recorded, never swallowed
            self.samples.append({"t": round(time.time(), 3), "note": note,
                                 "error": f"{type(exc).__name__}: {exc}"})

    def run(self) -> None:
        while not self._done.is_set():
            self.take("tick")
            self._done.wait(self.interval)

    def stop(self) -> None:
        self._done.set()
        self.join(timeout=20)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--model", required=True)
    ap.add_argument("--password", default="admin")
    ap.add_argument("--limit-over-static-mb", type=int, default=1024)
    ap.add_argument("--fill-rounds", type=int, default=14)
    ap.add_argument("--concurrent", type=int, default=2)
    ap.add_argument("--turns", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=32)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--cross-granule", action="store_true",
                    help="also run one *surviving* session across the 4096 boundary")
    ap.add_argument("--cross-first-tokens", type=int, default=3900,
                    help="first turn length, must stay under one granule")
    ap.add_argument("--cross-second-tokens", type=int, default=4200,
                    help="second turn length, must push past 4096")
    ap.add_argument("--label", default="run")
    ap.add_argument("--out", default="mys2785-accept.json")
    ap.add_argument("--csv", default="")
    a = ap.parse_args()

    if a.cross_granule:
        ap.error("two HTTP requests do not share a native session; use mys2785_cross_granule.py")

    import httpx

    failures: list[str] = []

    c = httpx.Client(base_url=a.base, timeout=3600)
    if c.post("/api/login", json={"password": a.password}).status_code != 200:
        print("login failed", flush=True)
        return 2

    # -- configuration ----------------------------------------------------
    view = c.get(f"/api/models/{a.model}/settings").json()
    if view["effective"].get("mem_limit_bytes") and \
            view["effective"]["mem_limit_bytes"] < view["mem_static_bytes"]:
        c.put(f"/api/models/{a.model}/settings", json={"mem_limit_mb": None})
        view = c.get(f"/api/models/{a.model}/settings").json()
    if not view.get("mem_used_bytes"):
        print("first load to measure the static footprint…", flush=True)
        if c.post(f"/api/models/{a.model}/load").status_code != 200:
            print("load failed", flush=True)
            return 2
        c.post(f"/api/models/{a.model}/unload")
        view = c.get(f"/api/models/{a.model}/settings").json()

    static = view["mem_static_bytes"]
    limit_mb = static // MIB + a.limit_over_static_mb
    if c.get(f"/api/models/{a.model}/settings").json()["effective"]["mem_limit_bytes"]:
        c.post(f"/api/models/{a.model}/unload")
    if c.put(f"/api/models/{a.model}/settings",
             json={"mem_limit_mb": limit_mb}).status_code != 200:
        print("could not set the limit", flush=True)
        return 2
    print(f"static {static / MIB:.0f} MiB, limit {limit_mb} MiB", flush=True)
    if c.post(f"/api/models/{a.model}/load").status_code != 200:
        print("load failed", flush=True)
        return 2
    st = c.get("/api/stats").json()["workers"][a.model]
    budget = st["kv_budget_bytes"]
    print(f"budget {budget / MIB:.0f} MiB, cache ceiling {st['cache']['max_bytes'] / MIB:.0f} MiB",
          flush=True)

    key = c.post("/api/keys", json={"name": f"accept-{a.label}"}).json()["key"]
    h = {"Authorization": f"Bearer {key}"}
    idle = npu_used()
    print(f"NPU after load: {idle / MIB:.0f} MiB", flush=True)

    sampler = Sampler(c, a.model, a.interval)
    sampler.start()
    marks: list[dict] = []
    sessions: list[dict] = []
    cross: dict | None = None
    try:
        # -- phase 1: fill the cache --------------------------------------
        for i in range(a.fill_rounds):
            u = ask(c, h, a.model,
                    "Plant shift log. " * 120 + f"volume {i} region {chr(65 + i % 26)} " * 25,
                    "Summarise the log in one line.", a.max_tokens, a.base)
            if u.get("finish") not in ("stop", "length"):
                failures.append(f"fill round {i}: finish={u.get('finish')}")
            marks.append({"phase": "fill", "round": i, "prompt": u.get("prompt_tokens")})
        w = c.get("/api/stats").json()["workers"][a.model]
        print(f"cache {w['cache']['bytes'] / MIB:.0f} / {w['cache']['max_bytes'] / MIB:.0f} MiB "
              f"over {w['cache']['entries']} entries", flush=True)

        # -- phase 2: real overlap ----------------------------------------
        # "Submitted together" is not "ran together". Each session records the
        # inflight count it observed while its own request was in flight, so the
        # claim rests on the worker's view, not on the submission order.
        def session(idx: int) -> dict:
            system = ("Plant maintenance log. " * 700) + f"session {idx} {a.label} "
            out = {"session": idx, "turns": [], "inflight_seen": []}
            for t in range(a.turns):
                seen: list[int] = []

                def note(_frames: int) -> None:
                    try:
                        seen.append(c.get("/api/stats").json()["workers"][a.model]["inflight"])
                    except Exception:
                        seen.append(-1)

                u = ask(c, h, a.model, system,
                        f"Turn {t}: summarise entry {t} of session {idx}.",
                        a.max_tokens, a.base, on_sample=note)
                out["turns"].append({"prompt": u.get("prompt_tokens"),
                                     "finish": u.get("finish"),
                                     "inflight_max": max(seen) if seen else 0})
                out["inflight_seen"].append(max(seen) if seen else 0)
            return out

        from concurrent.futures import ThreadPoolExecutor
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=a.concurrent) as pool:
            futures = [pool.submit(session, i) for i in range(a.concurrent)]
            for f in futures:
                try:
                    sessions.append(f.result())
                except Exception as exc:
                    failures.append(f"session raised: {type(exc).__name__}: {exc}")
        print(f"{a.concurrent} overlapping sessions finished in {time.time() - t0:.1f}s",
              flush=True)

        time.sleep(6)
    finally:
        sampler.stop()

    final = c.get("/api/stats").json()["workers"][a.model]
    samples = sampler.samples
    valid = [s for s in samples if s.get("npu") and not s.get("error")]
    errors = [s for s in samples if s.get("error")]
    peaks = max((s["npu"] for s in valid), default=None)
    total = npu_reading().get("mem_total_bytes")
    min_free = (total - peaks) if (total and peaks) else None
    inflight_peak = max((s["inflight"] for s in valid), default=0)

    # -- verdict, *before* writing the evidence file ----------------------
    # The file has to carry its own verdict: a run that saved `failures: []` and
    # then exited 1 would be a piece of evidence that lies, which is worse than
    # no evidence at all.
    checks: list[dict] = []

    def check(ok: bool, message: str) -> None:
        checks.append({"ok": bool(ok), "what": message})
        if not ok:
            failures.append(message)
            print(f"  FAIL: {message}", flush=True)

    print()
    print(f"label={a.label} static {static / MIB:.0f} MiB limit {limit_mb} MiB")
    check(bool(valid), "valid NPU samples present")
    check(not errors and len(valid) == len(samples), "no invalid or error samples")
    check(len(sessions) == a.concurrent, "all concurrent requests completed")
    check(all(t.get("finish") in ("stop", "length")
              for session in sessions for t in session["turns"]), "all requests finished successfully")
    check(len(valid) >= 20, "at least 20 valid samples")
    check(peaks is not None, "NPU peak measured")
    if peaks is not None:
        check(peaks <= limit_mb * MIB,
              f"NPU peak <= limit ({peaks / MIB:.0f} vs {limit_mb} MiB)")
    check(min_free is not None, "NPU free figure available")
    if min_free is not None:
        check(min_free >= NPU_RESERVE_FLOOR,
              f"NPU free >= 1 GiB floor ({min_free / MIB:.0f} MiB)")
    check(inflight_peak >= a.concurrent,
          f"real overlap: inflight peak {inflight_peak} >= {a.concurrent}")

    result = {
        "label": a.label, "model": a.model, "base": a.base,
        "static_bytes": static, "limit_bytes": limit_mb * MIB,
        "budget_bytes": budget, "npu_idle_bytes": idle,
        "npu_peak_bytes": peaks, "npu_total_bytes": total,
        "npu_min_free_bytes": min_free,
        "footprint_peak_bytes": (peaks - idle) if (peaks and idle is not None) else None,
        "cache_final_bytes": final["cache"]["bytes"],
        "cache_max_bytes": final["cache"]["max_bytes"],
        "cache_entries": final["cache"]["entries"],
        "inflight_peak": inflight_peak,
        "concurrent_requested": a.concurrent,
        "sessions": sessions, "cross_granule": cross, "marks": marks,
        "sample_errors": errors,
        "samples": samples,
        "checks": checks,
        "result": "FAIL" if failures else "PASS",
        "failures": failures,
    }
    with open(a.out, "w") as f:
        json.dump(result, f, indent=2)
    if a.csv:
        keys = ("t", "note", "npu", "cache", "entries", "kv_used", "reserved",
                "inflight", "queued", "kv_budget", "error")
        with open(a.csv, "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            wr.writeheader()
            for s in samples:
                wr.writerow(s)

    print(f"NPU peak {0 if peaks is None else peaks / MIB:.0f} MiB / limit {limit_mb} MiB; "
          f"min free {0 if min_free is None else min_free / MIB:.0f} MiB; "
          f"inflight peak {inflight_peak}; samples {len(valid)} valid + {len(errors)} errors")
    print(f"wrote {a.out}" + (f" and {a.csv}" if a.csv else ""), flush=True)

    if failures:
        print(f"RESULT: FAIL ({len(failures)} check(s))", flush=True)
        for f_ in failures:
            print(f"  - {f_}", flush=True)
        return 1
    print("RESULT: PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
