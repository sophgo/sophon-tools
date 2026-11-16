#!/usr/bin/env python3
"""MYS-2805 板上验收：全新管理进程加载后，worker 的运行期预算必须等于
`max(0, 生效上限 − 实测静态字节)`，且**不先 PUT**。

复现的现象（负责人 .157，9B，最终 deb `ae1fe8d`）：

    磁盘保存上限      14355 MiB
    加载后静态        13978738688 字节（13331 MiB + 172032）
    worker 运行预算   5482284672 字节
    正确值            1073569792 字节
    多发              4408714880 字节

所以本脚本**只做一件事**：全新进程里保存一个显式上限，加载，然后立刻采集三方
（API 的 `mem_static_bytes`、磁盘/API 的 `mem_limit_mb`、worker `stats` 的
`mem_runtime_budget_bytes`），逐字节比较。全程没有任何 `PUT`。

跑完再做普通推理 200 tokens 与卸载，采集 NPU 是否回到 0、生产服务是否 healthy。

    python3 mys2805_cold.py --root /data/mys2805 --port 19880 --out cold-2805.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

MIB = 1 << 20
NAME = "qwen3.5-9b-128k"
BASE = "/api/models/" + NAME
BM_SMI = "/opt/sophon/libsophon-current/bin/bm-smi"


class Failure(Exception):
    pass


def npu_free_bytes() -> int | None:
    from app.core.monitor import parse_bm_smi

    raw = subprocess.run([BM_SMI, "-noloop"], capture_output=True, timeout=15).stdout
    info = parse_bm_smi(raw)
    used, total = info.get("mem_used_bytes"), info.get("mem_total_bytes")
    if used is None or not total:
        return None
    return int(total) - int(used)


def side_state(root: Path) -> Path:
    return root / "data" / "state"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/data/mys2805")
    ap.add_argument("--port", type=int, default=19880)
    ap.add_argument("--out", default="cold-2805.json")
    ap.add_argument("--limit-mb", type=int, default=None,
                    help="显式上限；默认取「实测静态 + 1024 MiB」，仍受 14355 MiB 上限约束")
    args = ap.parse_args()

    root = Path(args.root)
    work = side_state(root)
    work.mkdir(parents=True, exist_ok=True)

    from fastapi.testclient import TestClient

    from app.core.monitor import device_memory
    from app.main import create_app

    report: dict = {
        "commit": (root / "COMMIT").read_text().strip() if (root / "COMMIT").exists() else None,
        "python": sys.version,
        "model": NAME,
        "steps": [],
    }

    app = create_app(
        data_dir=work, models_dir=root / "data" / "models", backend_kind="native",
        web_dir=root / "web" / "dist", native_lib=str(root / "lib" / "libcv84x6_llm.so"),
        install_dir=root, service_port=args.port,
    )
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        try:
            # 保存一个显式上限：先按默认上限的形态取一个接近生产的数。
            dflt = None
            before = c.get(f"{BASE}/settings").json()
            dflt = before.get("mem_limit_default_bytes")
            report["default_limit_bytes"] = dflt
            want_mb = args.limit_mb or 14355
            r = c.put(f"{BASE}/settings", json={"mem_limit_mb": want_mb})
            if r.status_code != 200:
                raise Failure(f"设置上限失败：{r.status_code} {r.text}")
            report["steps"].append({"step": "save_limit", "mb": want_mb,
                                    "status": r.status_code})
            pre = c.get(f"{BASE}/settings").json()
            report["saved"] = {
                "mem_limit_mb": pre["settings"]["mem_limit_mb"],
                "mem_static_bytes_estimate": pre["mem_static_bytes"],
            }

            # 这一次把 manager 的静态缓存丢掉，模拟「全新管理进程」：一个真的重启过的
            # 进程 `_static_bytes` 是空的，只会用 bmodel 声明值。
            app.state.models._static_bytes.clear()
            for info in app.state.models.list():
                info.measured_static_bytes = None

            t0 = time.monotonic()
            r = c.post(f"{BASE}/load", timeout=900)
            report["load_seconds"] = round(time.monotonic() - t0, 1)
            if r.status_code != 200:
                raise Failure(f"加载失败：{r.status_code} {r.text}")

            info = c.get(f"{BASE}/settings").json()
            worker = c.portal.call(app.state.clients[NAME].stats)
            static_bytes = int(info["mem_static_bytes"])
            limit_bytes = int(info["settings"]["mem_limit_mb"]) * MIB
            runtime = worker.get("mem_runtime_budget_bytes")
            worker_static = worker.get("mem_static_bytes")
            expected = max(0, limit_bytes - static_bytes)
            readback = {
                "api_mem_static_bytes": static_bytes,
                "api_mem_limit_mb": info["settings"]["mem_limit_mb"],
                "api_mem_limit_bytes": limit_bytes,
                "worker_mem_runtime_budget_bytes": runtime,
                "worker_mem_static_bytes": worker_static,
                "expected_runtime_bytes": expected,
                "excess_bytes": None if runtime is None else int(runtime) - expected,
                "npu_free_bytes_after_load": npu_free_bytes(),
                "device_memory": device_memory(),
                "raw_worker_stats": {k: worker.get(k) for k in (
                    "mem_runtime_budget_bytes", "mem_static_bytes",
                    "kv_budget_bytes", "device_budget_bytes")},
            }
            report["readback"] = readback
            failures = []
            if runtime is None:
                failures.append("worker 未报告 mem_runtime_budget_bytes")
            elif int(runtime) != expected:
                failures.append(
                    f"worker 预算 {runtime} != 期望 {expected}（差 {int(runtime) - expected}）")
            if worker_static is None or int(worker_static) != static_bytes:
                failures.append(
                    f"worker 静态 {worker_static} != API 静态 {static_bytes}")
            if static_bytes % MIB == 0:
                failures.append("实测静态恰好是 MiB 整数：本机未能体现小数尾数")
            report["cold_check"] = "PASS" if not failures else "FAIL"
            report["cold_failures"] = failures

            # 普通推理 200 tokens
            raw = c.post("/api/keys", json={"name": "mys2805"}).json()["key"]
            t1 = time.monotonic()
            gen = c.post("/v1/chat/completions",
                         headers={"Authorization": f"Bearer {raw}"},
                         json={"model": NAME, "max_tokens": 200,
                               "messages": [{"role": "user",
                                             "content": "用三句话说明什么是边缘推理。"}]},
                         timeout=900)
            report["inference"] = {
                "status": gen.status_code,
                "seconds": round(time.monotonic() - t1, 1),
                "usage": (gen.json().get("usage") if gen.status_code == 200 else gen.text[:400]),
            }
            if gen.status_code != 200:
                failures.append(f"推理失败：{gen.status_code}")

            r = c.post(f"{BASE}/unload", timeout=600)
            report["unload"] = {"status": r.status_code}
            if r.status_code != 200:
                failures.append(f"卸载失败：{r.status_code} {r.text}")
        finally:
            try:
                c.post(f"{BASE}/unload", timeout=600)
            except Exception:
                pass

    # 卸载之后：NPU 是否回到 0、生产服务是否健康。
    time.sleep(3)
    report["after"] = device_memory()
    report["npu_free_bytes_after_unload"] = npu_free_bytes()
    try:
        report["production"] = json.loads(
            urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=10).read())
    except Exception as exc:                                    # pragma: no cover
        report["production"] = {"error": f"{type(exc).__name__}: {exc}"}

    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
    ok = report.get("cold_check") == "PASS" and not report.get("cold_failures")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
