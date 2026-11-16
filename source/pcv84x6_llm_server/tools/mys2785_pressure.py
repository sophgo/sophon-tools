#!/usr/bin/env python3
"""MYS-2785 验收第 3 条：高频并发提交/取消 + 内存压力 smoke。

调度改动会影响准入与让路，所以这不是功能测试而是压力测试：短时间内交替提交与
取消请求，让缓存持续增长、让会话不断被准入和换出，记录

* 请求结果分布（完成 / 取消 / 被拒 / 超时）；
* 每 N 秒的 NPU 余量，取整段的最小值；
* 是否出现错误或 worker fault。

判据按任务卡保持 1 GiB 保护目标：NPU 余量最小值不得低于 ``CV84X6_NPU_RESERVE_MB``
（默认 1024 MiB）。

    python3 tools/mys2785_pressure.py --base http://127.0.0.1:8010 \
        --model qwen3.5-9b-128k --seconds 120 --workers 6 --out pressure.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

MIB = 1 << 20
BM_SMI = "/opt/sophon/libsophon-current/bin/bm-smi"


def smi() -> dict:
    from app.core.monitor import parse_bm_smi
    try:
        raw = subprocess.run([BM_SMI, "-noloop"], capture_output=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_bm_smi(raw)


def consume_stream(response, cancel: bool) -> str:
    """Count a cancellation only after closing an unfinished content stream."""
    if response.status_code == 429:
        return "rejected"
    response.raise_for_status()
    content_frames = 0
    finish = None
    for line in response.iter_lines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        frame = json.loads(payload)
        if frame.get("error"):
            raise RuntimeError(f"SSE error: {frame['error']}")
        for choice in frame.get("choices", []):
            finish = choice.get("finish_reason") or finish
            if choice.get("delta", {}).get("content"):
                content_frames += 1
        if cancel and content_frames >= 3 and finish is None:
            return "cancelled"
    if finish not in ("stop", "length"):
        raise RuntimeError(f"stream ended without successful finish: {finish}")
    return "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--model", required=True)
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--cancel-fraction", type=float, default=0.4,
                    help="share of requests aborted mid-flight")
    ap.add_argument("--max-tokens", type=int, default=24)
    ap.add_argument("--out", default="mys2785-pressure.json")
    a = ap.parse_args()

    import httpx

    c = httpx.Client(base_url=a.base, timeout=600)
    c.post("/api/login", json={"password": "admin"})
    key = c.post("/api/keys", json={"name": "pressure"}).json()["key"]
    h = {"Authorization": f"Bearer {key}"}

    st0 = c.get("/api/stats").json()["workers"][a.model]
    print(f"budget {st0['kv_budget_bytes'] / MIB:.0f} MiB, "
          f"cache ceiling {st0['cache']['max_bytes'] / MIB:.0f} MiB", flush=True)
    reserve = int(__import__("os").environ.get("CV84X6_NPU_RESERVE_MB", "1024")) * MIB

    stop = threading.Event()
    samples: list[dict] = []

    def sampler() -> None:
        while not stop.is_set():
            s = smi()
            try:
                w = c.get("/api/stats").json()["workers"][a.model]
                samples.append({"t": time.time(), "used": s.get("mem_used_bytes"),
                                "total": s.get("mem_total_bytes"),
                                "cache": w["cache"]["bytes"], "entries": w["cache"]["entries"],
                                "inflight": w["inflight"], "queued": w["queued"],
                                "fault": w.get("fault")})
            except Exception as exc:
                samples.append({"t": time.time(), "error": repr(exc)})
            stop.wait(1.0)

    counts = {"ok": 0, "cancelled": 0, "rejected": 0, "timeout": 0, "error": 0}
    errors: list[str] = []
    lock = threading.Lock()

    def one(i: int) -> None:
        system = f"Pressure probe {i}. " + "Plant log entry. " * 60
        cancel = int((i + 1) * a.cancel_fraction) > int(i * a.cancel_fraction)
        try:
            with httpx.Client(base_url=a.base, timeout=180) as cc:
                with cc.stream("POST", "/v1/chat/completions", headers=h, json={
                        "model": a.model,
                        "messages": [{"role": "system", "content": system},
                                     {"role": "user", "content": "Summarise."}],
                        "max_tokens": a.max_tokens, "stream": True}) as s:
                    kind = consume_stream(s, cancel)
        except httpx.ReadTimeout:
            kind = "timeout"
        except Exception as exc:
            kind = "error"
            with lock:
                errors.append(f"{type(exc).__name__}: {exc}")
        with lock:
            counts[kind] += 1

    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    t0 = time.monotonic()
    submitted = 0
    try:
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            pending = set()
            while time.monotonic() - t0 < a.seconds:
                while len(pending) < a.workers and time.monotonic() - t0 < a.seconds:
                    pending.add(pool.submit(one, submitted))
                    submitted += 1
                _, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
    finally:
        time.sleep(3)                 # let the last streams finish
        stop.set()
        th.join(timeout=20)

    # A 429 is the designed refusal under load; count it separately from errors.
    rejected = 0
    st = c.get("/api/stats").json()["workers"][a.model]
    rejected = st.get("rejected_requests", 0)

    frees = [s["total"] - s["used"] for s in samples
             if s.get("used") and s.get("total")]
    min_free = min(frees) if frees else None
    result = {
        "submitted": submitted, "counts": counts,
        "worker_rejected_requests": rejected,
        "errors": errors,
        "min_free_bytes": min_free, "reserve_bytes": reserve,
        "fault": st.get("fault"),
        "final_cache_bytes": st["cache"]["bytes"],
        "final_entries": st["cache"]["entries"],
        "final_kv_used_bytes": st["kv_used_bytes"],
        "samples": samples,
    }

    print()
    print(f"submitted {submitted} over {a.seconds:.0f}s with {a.workers} workers: {counts}")
    print(f"worker-reported rejections (429): {rejected}")
    if min_free is not None:
        print(f"NPU free minimum: {min_free / MIB:.0f} MiB "
              f"({'PASS' if min_free >= reserve else 'FAIL'} vs "
              f"{reserve / MIB:.0f} MiB floor)")
    print(f"worker fault: {st.get('fault')}")
    if errors:
        print(f"errors ({len(errors)}): {errors[:5]}")

    # Criterion 7: a smoke that reported failures and exited 0 is what let the
    # previous round look green. Every unacceptable outcome is a non-zero exit.
    failures = []
    if any(s.get("error") or s.get("used") is None or not s.get("total") for s in samples):
        failures.append("invalid NPU sample")
    if a.cancel_fraction > 0 and not counts["cancelled"]:
        failures.append("no stream was actually cancelled")
    if not counts["ok"]:
        failures.append("no request completed successfully")
    if counts["error"] or counts["timeout"]:
        failures.append(f"{counts['error']} error(s), {counts['timeout']} timeout(s)")
    if errors:
        failures.append(f"{len(errors)} exception(s): {errors[0]}")
    if min_free is None:
        failures.append("no NPU free figure (bm-smi total missing)")
    elif min_free < reserve:
        failures.append(f"NPU free {min_free / MIB:.0f} MiB below the "
                        f"{reserve / MIB:.0f} MiB floor")
    if st.get("fault"):
        failures.append("worker reported fault")
    if submitted == 0:
        failures.append("no request was submitted")
    result["result"] = "FAIL" if failures else "PASS"
    result["failures"] = failures
    with open(a.out, "w") as f:
        json.dump(result, f, indent=2)
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
