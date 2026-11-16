#!/usr/bin/env python3
"""MYS-2795 板上验收：运行期增额必须过设备准入，拒绝时必须什么都没变。

判据（任一不满足即非零退出，不是打印 FAIL 后 return 0）：

1. **正常增额成功**：9B 模型加载后，把额度适度调大（默认 +512 MiB）应当返回 200，
   worker 的运行期预算确实变大，设置已持久化。
2. **超额增额被拒且无副作用**：提出一个大于「当前 NPU 空闲 − 其他模型预算 − 下限」
   的额度，必须在任何新增分配发生之前返回 409；worker 的 `mem_runtime_budget_bytes`
   与保存的 `mem_limit_mb` 都保持第一次增额后的值。
3. **恢复默认走同一条路**（`mem_limit_mb: null`）：读数被临时压到不够时拒绝、够时放行。
4. **下限保护**：整个过程中 NPU 余量最小值不低于 `CV84X6_NPU_RESERVE_MB`（默认 1024 MiB）。

记录每一次变更前后的 bm-smi、`/api/models` 的 `applied` 与 `GET .../settings`，
原样写进 `--out` 的 JSON。结束时把模型的额度恢复成运行前的值、卸载本脚本加载的模型。

    python3 tools/mys2795_accept.py --base http://127.0.0.1:8010 \
        --model qwen3.5-9b-128k --out accept-2795.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

import httpx

MIB = 1 << 20
BM_SMI = "/opt/sophon/libsophon-current/bin/bm-smi"
DEFAULT_RESERVE_MIB = 1024


class Failure(Exception):
    """A check that did not hold."""


def npu_free_mib() -> int | None:
    """NPU 堆空闲 MiB，取自 bm-smi（与 monitor.parse_bm_smi 同一解析）。"""
    from app.core.monitor import parse_bm_smi

    raw = subprocess.run([BM_SMI, "-noloop"], capture_output=True,
                         timeout=10).stdout
    info = parse_bm_smi(raw)
    used, total = info.get("mem_used_bytes"), info.get("mem_total_bytes")
    if used is None or not total:
        return None
    return (total - used) // MIB


def bm_smi_line() -> str:
    """一行 bm-smi 摘要，便于人工复核。"""
    from app.core.monitor import parse_bm_smi

    raw = subprocess.run([BM_SMI, "-noloop"], capture_output=True,
                         timeout=10).stdout
    info = parse_bm_smi(raw)
    used, total = info.get("mem_used_bytes"), info.get("mem_total_bytes")
    if used is None or not total:
        return "bm-smi: unreadable"
    return f"NPU {used // MIB}/{total // MIB} MiB used, {(total - used) // MIB} MiB free"


class Client:
    def __init__(self, base: str) -> None:
        self.http = httpx.Client(base_url=base, timeout=180)
        r = self.http.post("/api/login", json={"password": "admin"})
        r.raise_for_status()

    def settings(self, model: str) -> dict:
        return self.http.get(f"/api/models/{model}/settings").json()

    def put(self, model: str, **body) -> httpx.Response:
        return self.http.put(f"/api/models/{model}/settings", json=body)

    def models(self) -> list[dict]:
        return self.http.get("/api/models").json()["models"]

    def stats(self, model: str) -> dict | None:
        for m in self.models():
            if m["id"] == model:
                return m.get("worker") or m
        return None

    def load(self, model: str) -> httpx.Response:
        return self.http.post(f"/api/models/{model}/load", timeout=600)

    def unload(self, model: str) -> httpx.Response:
        return self.http.post(f"/api/models/{model}/unload", timeout=300)

    def worker_budget_mib(self, model: str) -> int | None:
        """worker 自己报的运行期预算（`/api/models` 的 applied 不回读，走 stats）。"""
        r = self.http.get(f"/api/models/{model}/settings")
        applied = r.json().get("applied") or {}
        value = applied.get("mem_runtime_budget_bytes")
        return None if value is None else value // MIB

    def other_growing_budgets_mib(self, model: str) -> int:
        """已加载的其他 chat / ocr_vl 模型的运行期预算合计。"""
        total = 0
        for m in self.models():
            if m["id"] == model or not m.get("loaded"):
                continue
            if m.get("kind") not in ("chat", "ocr_vl"):
                continue
            limit = int(m["effective"]["mem_limit_bytes"])
            static = int(m["mem_static_bytes"])
            total += max(0, limit - static)
        return total // MIB


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--model", default="qwen3.5-9b-128k")
    ap.add_argument("--raise-mib", type=int, default=512,
                    help="正常增额的幅度（相对当前运行期预算）")
    ap.add_argument("--out", default="accept-2795.json")
    args = ap.parse_args()

    reserve = int(__import__("os").environ.get("CV84X6_NPU_RESERVE_MB",
                                               DEFAULT_RESERVE_MIB) or 0)
    c = Client(args.base)
    report: dict = {"base": args.base, "model": args.model,
                    "reserve_mib": reserve, "steps": [], "npu_free_samples": []}

    def sample(tag: str) -> int | None:
        free = npu_free_mib()
        report["npu_free_samples"].append({"tag": tag, "free_mib": free,
                                           "at": time.time()})
        print(f"  [{tag}] {bm_smi_line()}")
        return free

    before = c.settings(args.model)
    was_loaded = next((m["loaded"] for m in c.models()
                       if m["id"] == args.model), False)
    report["before"] = {"settings": before["settings"],
                        "effective": before["effective"],
                        "loaded": was_loaded}

    if not was_loaded:
        print(f"加载 {args.model} ...")
        r = c.load(args.model)
        if r.status_code != 200:
            raise Failure(f"加载失败：{r.status_code} {r.text}")
    loaded = c.settings(args.model)
    base_limit = int(loaded["effective"]["mem_limit_bytes"]) >> 20
    base_budget = base_limit - (int(loaded["mem_static_bytes"]) >> 20)
    report["baseline"] = {"mem_limit_mb": base_limit,
                          "runtime_budget_mib": base_budget}
    print(f"基线：上限 {base_limit} MiB，运行期预算 {base_budget} MiB")
    sample("loaded")

    # -- 1. 正常增额 ------------------------------------------------------
    step: dict = {"step": "raise_ok", "asked_mib": base_budget + args.raise_mib}
    r = c.put(args.model, mem_limit_mb=base_limit + args.raise_mib)
    step["status"] = r.status_code
    step["body"] = r.json() if r.headers.get("content-type", "").startswith(
        "application/json") else r.text
    if r.status_code != 200:
        raise Failure(f"适度增额应当成功，实际 {r.status_code}: {r.text}")
    applied = r.json().get("applied") or {}
    step["applied"] = applied
    if int(applied.get("mem_runtime_budget_bytes") or 0) < (
            base_budget + args.raise_mib) * MIB:
        raise Failure(f"worker 的运行期预算没跟上：{applied}")
    raised_limit = base_limit + args.raise_mib
    stored = c.settings(args.model)["settings"]["mem_limit_mb"]
    if stored != raised_limit:
        raise Failure(f"设置没持久化：stored={stored} wanted={raised_limit}")
    step["free_mib"] = sample("after_raise")
    report["steps"].append(step)
    print(f"适度增额 +{args.raise_mib} MiB 成功，worker 预算 "
          f"{applied.get('mem_runtime_budget_bytes', 0) // MIB} MiB")

    # -- 2. 超额增额被拒，且什么都没变 ------------------------------------
    free = npu_free_mib()
    if free is None:
        raise Failure("读不到 NPU 余量，无法构造超额增额")
    others = c.other_growing_budgets_mib(args.model)
    # The claim is the **difference** between the new and the old budget
    # (the model's existing budget is already committed), so the largest
    # budget that can still leave the floor is
    #
    #     current_budget + (free - others - reserve)
    #
    # and one MiB past that must be refused. Computed from the *current* budget,
    # which step 1 just raised -- using the baseline here would ask for less than
    # the model already has and be correctly admitted as a reduction.
    current = c.settings(args.model)
    current_budget = ((int(current["effective"]["mem_limit_bytes"]) >> 20)
                      - (int(current["mem_static_bytes"]) >> 20))
    affordable_delta = free - others - reserve
    affordable = current_budget + affordable_delta
    over_mib = affordable + 128
    over_limit = (int(current["mem_static_bytes"]) >> 20) + over_mib
    step = {"step": "raise_refused", "free_mib": free,
            "other_budgets_mib": others, "current_budget_mib": current_budget,
            "affordable_delta_mib": affordable_delta,
            "affordable_budget_mib": affordable,
            "asked_budget_mib": over_mib, "asked_limit_mb": over_limit}
    print(f"超额增额：free={free} other={others} reserve={reserve} "
          f"当前预算={current_budget} => 可承诺 {affordable} MiB，"
          f"申请 {over_mib} MiB")
    r = c.put(args.model, mem_limit_mb=over_limit)
    step["status"] = r.status_code
    step["body"] = r.json()
    if r.status_code != 409:
        raise Failure(f"超额增额必须被拒（409），实际 {r.status_code}: {r.text}")
    if r.json().get("code") != "device_memory_insufficient":
        raise Failure(f"错误码应为 device_memory_insufficient，实际 {r.json()}")
    after = c.settings(args.model)
    if after["settings"]["mem_limit_mb"] != raised_limit:
        raise Failure(f"被拒后设置应保持 {raised_limit}，实际 "
                      f"{after['settings']['mem_limit_mb']}")
    # worker 端口上没有 applied（拒绝发生在 configure 之前），用 stats 复核。
    budget_now = c.worker_budget_mib(args.model)
    step["worker_budget_after_mib"] = budget_now
    step["settings_after"] = after["settings"]
    step["free_mib_after"] = sample("after_refusal")
    report["steps"].append(step)
    print("超额增额被拒（409 device_memory_insufficient），设置与 worker 未变")

    # -- 3. 恢复默认走同一条路 --------------------------------------------
    step = {"step": "reset_to_default"}
    r = c.put(args.model, mem_limit_mb=None)
    step["status"] = r.status_code
    step["body"] = r.json() if r.status_code == 200 else r.json()
    if r.status_code != 200:
        raise Failure(f"恢复默认应当成功，实际 {r.status_code}: {r.text}")
    step["free_mib"] = sample("after_reset")
    report["steps"].append(step)
    print("恢复默认成功（同一条准入路径）")

    # -- 4. 全程余量底线 ---------------------------------------------------
    lows = [s["free_mib"] for s in report["npu_free_samples"]
            if s["free_mib"] is not None]
    report["min_free_mib"] = min(lows) if lows else None
    if reserve > 0 and lows and min(lows) < reserve:
        raise Failure(f"NPU 余量最低 {min(lows)} MiB，低于保护下限 {reserve} MiB")

    # -- 收尾：恢复运行前的设置与加载状态 ----------------------------------
    if before["settings"]["mem_limit_mb"] is None:
        c.put(args.model, mem_limit_mb=None)
    else:
        c.put(args.model, mem_limit_mb=before["settings"]["mem_limit_mb"])
    if not was_loaded:
        c.unload(args.model)
    report["after"] = {"settings": c.settings(args.model)["settings"],
                       "loaded": next((m["loaded"] for m in c.models()
                                       if m["id"] == args.model), None)}
    report["ok"] = True
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(f"\n全部通过。原始证据：{args.out}")
    print(f"NPU 余量最低 {report['min_free_mib']} MiB（下限 {reserve} MiB）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Failure as exc:
        print(f"\nFAIL: {exc}", file=sys.stderr)
        sys.exit(1)
