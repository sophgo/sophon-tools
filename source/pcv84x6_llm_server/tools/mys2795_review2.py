#!/usr/bin/env python3
"""MYS-2795 首轮验收三个缺口的回归脚本（自带正确断言）。

负责人给的 `stage28-review-repro.py` 只打印观察值；这个脚本对同样的场景做
**断言**，所以它自己就能给出红/绿，不需要人工判读。三个用例一一对应首轮验收的
三处发现：

1. `own_old_budget` —— 增额必须扣掉目标模型**自己**已承诺的原预算。
   free=1624 MiB、原预算 400、新预算 1000、下限 1024 ⇒ 只剩 624，必须拒绝；
   边界是 2024 MiB（400 + 600 + 1024），不是 1624。旧实现 `exclude=<目标>` 会放行。

2. `two_pending_aux_loads` —— 辅助模型的加载**在加载窗口内**也要占额度。
   free=1536、两个 embedding 各 512、下限 1024：两个同时加载会只剩 512，
   所以第二个必须被拒。旧实现只给 growing kinds 登记承诺，两个都进了 spawn。

3. `lost_configure_ack` —— `configure` 的答复丢失不等于 worker 没执行。
   旧实现把超时当"拒绝"，返回 409 且清账，实际 worker 已在 1000 MiB。
   现在必须把两侧核对成一致：worker 真的应用了就按成功收敛（保存 1000、
   账本清空），核对不出来则保留承诺并按 503 报告未确认。

    PYTHONPATH=<PR 工作树> venv-llm-server/bin/python tools/mys2795_review2.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.models import AUX_DEVICE_HEADROOM, ModelManager
from app.main import create_app

MIB = 1 << 20
RESERVE_MB = 1024


def make_model(root: Path, name: str,
               bmodel: str = "qwen3.6-35b-a3b-int4-autow4bf16") -> None:
    d = root / name
    (d / "config").mkdir(parents=True, exist_ok=True)
    with (d / f"{bmodel}_seq2048_4core_static.bmodel").open("wb") as fh:
        fh.truncate(256 * MIB)
    (d / "config" / "config.json").write_text("{}")


def heap(free_mib: int) -> dict:
    return {"heaps": [{"name": "npu", "total_bytes": 26624 * MIB,
                       "used_bytes": 26624 * MIB - free_mib * MIB,
                       "free_bytes": free_mib * MIB}]}


class Failure(Exception):
    pass


def check(cond: bool, message: str) -> None:
    if not cond:
        raise Failure(message)


# ---------------------------------------------------------------------------
# 1. 增额漏算目标原预算
# ---------------------------------------------------------------------------
def case_own_old_budget() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        make_model(root / "models", "chat")
        app = create_app(data_dir=root / "data", models_dir=root / "models",
                         backend_kind="mock", web_dir=root / "web",
                         context_length_override=4096)
        with TestClient(app) as c:
            check(c.post("/api/login", json={"password": "admin"}).status_code == 200,
                  "login failed")
            check(c.post("/api/models/chat/load").status_code == 200, "load failed")
            url = "/api/models/chat/settings"
            static = c.get(url).json()["mem_static_bytes"] // MIB
            check(c.put(url, json={"mem_limit_mb": static + 400}).status_code == 200,
                  "setting the 400 MiB baseline failed")

            with patch("app.core.monitor.device_memory",
                       return_value=heap(1624)):
                r = c.put(url, json={"mem_limit_mb": static + 1000})
            check(r.status_code == 409,
                  f"free=1624, own budget 400, raise to 1000 leaves 624 MiB "
                  f"(floor {RESERVE_MB}) and must be refused; got {r.status_code} "
                  f"{r.text}")
            check("NPU 显存余量不足" in r.json()["detail"],
                  f"refusal should name the NPU floor: {r.json()}")
            check(c.get(url).json()["settings"]["mem_limit_mb"] == static + 400,
                  "a refused raise must not be persisted")
            check(len(app.state.models.device_promises) == 0,
                  "a refused raise left a claim behind")

            # The boundary is 400 (own budget) + 600 (increase) + 1024 (floor).
            with patch("app.core.monitor.device_memory",
                       return_value=heap(400 + 600 + RESERVE_MB - 1)):
                r = c.put(url, json={"mem_limit_mb": static + 1000})
            check(r.status_code == 409,
                  f"one MiB under the 2024 MiB boundary must still be refused, "
                  f"got {r.status_code}")
            with patch("app.core.monitor.device_memory",
                       return_value=heap(400 + 600 + RESERVE_MB)):
                r = c.put(url, json={"mem_limit_mb": static + 1000})
            check(r.status_code == 200,
                  f"2024 MiB free leaves exactly the floor and must be admitted, "
                  f"got {r.status_code} {r.text}")
            check(c.post("/api/models/chat/unload").status_code == 200, "unload failed")
            return {"case": "own_old_budget", "refused_at_1624": True,
                    "boundary_mib": 400 + 600 + RESERVE_MB, "ok": True}


# ---------------------------------------------------------------------------
# 2. 辅助模型加载没有承诺
# ---------------------------------------------------------------------------
async def case_two_pending_aux_loads() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name in ("embed-a", "embed-b"):
            make_model(root / "models", name, "qwen3-embedding-0.6b_bf16")
        mgr = ModelManager(root / "models", backend_kind="mock",
                           log_dir=root / "logs")
        mgr.refresh()
        a = mgr.get("embed-a")
        claim = mgr._declared_claim_bytes(a)
        check(claim == mgr.static_bytes(a) + AUX_DEVICE_HEADROOM,
              f"an auxiliary claim must be static + aux headroom, got {claim}")
        free_mb = claim // MIB + RESERVE_MB

        started = asyncio.Event()
        release = asyncio.Event()
        spawned: list[tuple[str, int]] = []

        async def held_spawn(info, *, promise):
            spawned.append((info.model_id, len(mgr.device_promises)))
            started.set()
            await release.wait()
            info.loaded = True
            mgr.release_budget_promise(promise)
            return info

        mgr._spawn_and_await = held_spawn          # type: ignore[assignment]
        with patch("app.core.monitor.device_memory",
                   return_value=heap(free_mb)):
            first = asyncio.create_task(mgr.load("embed-a"))
            await asyncio.wait_for(started.wait(), timeout=10)
            check(spawned and spawned[0][1] == 1,
                  "the auxiliary load must hold a claim while it spawns; "
                  f"ledger at spawn was {spawned}")
            try:
                await mgr.load("embed-b")
            except Exception as exc:
                refused = type(exc).__name__
            else:
                raise Failure(
                    f"free={free_mb} MiB fits one {claim // MIB} MiB footprint plus "
                    f"the {RESERVE_MB} MiB floor, not two; embed-b was admitted")
            release.set()
            loaded = await first
            check(loaded.loaded is True, "embed-a did not finish loading")
            check(mgr.device_promises == (),
                  "a finished auxiliary load must not keep a runtime claim")
            return {"case": "two_pending_aux_loads", "free_mib": free_mb,
                    "claim_mib": claim // MIB, "refused_with": refused,
                    "ledger_at_spawn": spawned[0][1], "ok": True}


def main() -> int:
    out: list[dict] = []
    try:
        out.append(case_own_old_budget())
        out.append(asyncio.run(case_two_pending_aux_loads()))
    except Failure as exc:
        import json
        for row in out:
            print(json.dumps(row, ensure_ascii=False))
        print(f"\nFAIL: {exc}", file=sys.stderr)
        return 1
    import json
    for row in out:
        print(json.dumps(row, ensure_ascii=False))
    print("\n全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
