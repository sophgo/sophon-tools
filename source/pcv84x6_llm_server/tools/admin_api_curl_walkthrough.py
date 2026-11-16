#!/usr/bin/env python3
"""The acceptance walkthrough for the management API (MYS-2676), as real curl.

    python3 tools/admin_api_curl_walkthrough.py --port 18220

Starts the service with the mock backend on a free port, seeds two models, and
then drives **the documented interface with curl** exactly as a script would:
list models, load one, change a setting, mint a key, read the audit. Every step
prints the command and the response, and the script fails if a response is not
what the document says it should be.

Why this exists next to the pytest suite: the suite calls the app in-process, so
it cannot catch the things a real client hits -- the cookie jar, the header
spelling, an error body a shell script has to parse. This is the check that a
person can reproduce by pasting the commands.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

CURL = ["curl", "-sS", "--max-time", "60"]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def seed(root: Path) -> None:
    models = {
        "qwen3.6-35b-a3b-128k": (
            "qwen3.6-35b-a3b-128k-int4_w4bf16_seq131072_4core_dynamic.bmodel", "chat"),
        "qwen3-embedding-0.6b": (
            "qwen3-embedding-0.6b_bf16_seq8192_bm1684x2_4core_static.bmodel",
            "embedding"),
    }
    for model_id, (filename, _kind) in models.items():
        directory = root / "models" / model_id
        (directory / "config").mkdir(parents=True, exist_ok=True)
        (directory / "config" / "config.json").write_text("{}")
        (directory / filename).write_bytes(b"\x00" * (1 << 20))


def curl(*args: str) -> tuple[int, str]:
    """Run one curl and return (status, body) -- the status from ``-w``.

    ``-w '%{http_code}'`` is appended rather than parsing headers: a shell script
    does the same, and it is the spelled-out form of "what status did I get".
    """
    proc = subprocess.run([*CURL, "-w", "\n%{http_code}", *args],
                          capture_output=True, text=True, timeout=120)
    body, _, status = proc.stdout.rpartition("\n")
    return int(status or 0), body


def step(label: str, command: str, status: int, body: str, ok: bool) -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"\n[{mark}] {label}")
    print(f"  $ {command}")
    print(f"  -> HTTP {status}")
    pretty = body.strip()
    try:
        pretty = json.dumps(json.loads(pretty), ensure_ascii=False, indent=2)
        pretty = "\n".join("     " + line for line in pretty.splitlines()[:28])
    except ValueError:
        pretty = "     " + pretty[:800]
    print(pretty)
    return ok


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--keep", action="store_true", help="keep the data directory")
    args = parser.parse_args(argv)
    port = args.port or free_port()
    origin = f"http://127.0.0.1:{port}"
    root = Path(tempfile.mkdtemp(prefix="cv84x6-curl-"))
    seed(root)
    jar = root / "cookies.txt"
    failures = 0
    service = subprocess.Popen(
        [sys.executable, "-m", "app.main", "--backend", "mock", "--port", str(port),
         "--data-root", str(root), "--host", "127.0.0.1"],
        cwd=str(BASE), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                status, _ = curl(f"{origin}/healthz")
                if status == 200:
                    break
            except subprocess.SubprocessError:  # pragma: no cover
                pass
            time.sleep(0.3)
        else:
            print("the service never became healthy", file=sys.stderr)
            return 2
        print(f"service on {origin} (data root {root})")

        # -- 1. log in once, to mint an admin key ---------------------------
        status, body = curl("-c", str(jar), "-X", "POST", f"{origin}/api/login",
                            "-H", "Content-Type: application/json",
                            "-d", '{"password":"admin"}')
        failures += not step("登录（换会话 cookie）",
                             f"curl -c jar -X POST {origin}/api/login "
                             "-H 'Content-Type: application/json' "
                             "-d '{\"password\":\"admin\"}'",
                             status, body, status == 200)

        status, body = curl("-b", str(jar), "-X", "POST", f"{origin}/api/keys",
                            "-H", "Content-Type: application/json",
                            "-d", '{"name":"walkthrough","scope":"admin"}')
        key = ""
        try:
            key = json.loads(body)["key"]
        except (ValueError, KeyError):
            pass
        failures += not step("创建 admin key（脚本用的凭据）",
                             f"curl -b jar -X POST {origin}/api/keys "
                             "-H 'Content-Type: application/json' "
                             "-d '{\"name\":\"walkthrough\",\"scope\":\"admin\"}'",
                             status, body.replace(key, "sk-…") if key else body,
                             status == 200 and key.startswith("sk-"))
        if not key:
            print("cannot continue without a key", file=sys.stderr)
            return 1
        auth = ["-H", f"Authorization: Bearer {key}"]

        # From here on: no cookie jar, admin key only -- the way a script runs.
        # -- 2. list models --------------------------------------------------
        status, body = curl(*auth, f"{origin}/api/models")
        models = json.loads(body).get("models", []) if status == 200 else []
        failures += not step("列出模型（代码先启动这一步）",
                             f"curl -H 'Authorization: Bearer $KEY' {origin}/api/models",
                             status, body,
                             status == 200 and len(models) == 2)

        # -- 3. load ---------------------------------------------------------
        status, body = curl(*auth, "-X", "POST",
                            f"{origin}/api/models/qwen3.6-35b-a3b-128k/load")
        loaded = status == 200 and json.loads(body)["model"]["loaded"]
        failures += not step("加载模型",
                             f"curl -H 'Authorization: Bearer $KEY' -X POST "
                             f"{origin}/api/models/qwen3.6-35b-a3b-128k/load",
                             status, body, loaded)

        # -- 4. change a setting --------------------------------------------
        status, body = curl(*auth, "-X", "POST", f"{origin}/api/settings",
                            "-H", "Content-Type: application/json",
                            "-d", '{"max_queue":12,"aux_idle_unload_min":5}')
        settings = json.loads(body).get("settings", {}) if status == 200 else {}
        failures += not step("改设置（并推送给了刚加载的 worker）",
                             f"curl -H 'Authorization: Bearer $KEY' -X POST "
                             f"{origin}/api/settings -H 'Content-Type: application/json' "
                             "-d '{\"max_queue\":12,\"aux_idle_unload_min\":5}'",
                             status, body,
                             status == 200 and settings.get("max_queue") == 12)

        # -- 5. read the audit ----------------------------------------------
        status, body = curl(*auth, f"{origin}/api/audit?limit=10")
        rows = json.loads(body).get("items", []) if status == 200 else []
        actors = {row["actor_name"] for row in rows}
        failures += not step("查审计（操作者是 key 的名字）",
                             f"curl -H 'Authorization: Bearer $KEY' '{origin}/api/audit?limit=10'",
                             status, body,
                             status == 200 and "walkthrough" in actors
                             and any(row["path"] == "/api/settings" for row in rows))

        # -- 6. an inference key must be refused ----------------------------
        status, body = curl("-b", str(jar), "-X", "POST", f"{origin}/api/keys",
                            "-H", "Content-Type: application/json",
                            "-d", '{"name":"agent"}')
        inference_key = json.loads(body)["key"]
        status, body = curl("-H", f"Authorization: Bearer {inference_key}",
                            f"{origin}/api/models")
        code = json.loads(body).get("code") if status else None
        failures += not step("inference key 调 /api → 403 forbidden_scope",
                             f"curl -H 'Authorization: Bearer $INFERENCE_KEY' "
                             f"{origin}/api/models",
                             status, body, status == 403 and code == "forbidden_scope")

        # -- 7. that same key still drives /v1 ------------------------------
        status, body = curl("-H", f"Authorization: Bearer {inference_key}",
                            f"{origin}/v1/models")
        failures += not step("同一把 key 照常调 /v1",
                             f"curl -H 'Authorization: Bearer $INFERENCE_KEY' "
                             f"{origin}/v1/models",
                             status, body, status == 200)

        # -- 8. a documented refusal, with its code -------------------------
        status, body = curl(*auth, "-X", "POST", f"{origin}/api/models/nope/load")
        code = json.loads(body).get("code") if status else None
        failures += not step("不存在的模型 → 404 not_found",
                             f"curl -H 'Authorization: Bearer $KEY' -X POST "
                             f"{origin}/api/models/nope/load",
                             status, body, status == 404 and code == "not_found")

        # -- 9. the 409 codes a script branches on --------------------------
        status, body = curl(*auth, "-X", "POST",
                            f"{origin}/api/models/qwen3.6-35b-a3b-128k/load")
        status2, body2 = curl(*auth, "-X", "PUT",
                              f"{origin}/api/models/qwen3.6-35b-a3b-128k/settings",
                              "-H", "Content-Type: application/json",
                              "-d", '{"mem_limit_mb":1}')
        code2 = json.loads(body2).get("code") if status2 else None
        failures += not step("内存上限越界 → 400 bad_request",
                             f"curl -H 'Authorization: Bearer $KEY' -X PUT "
                             f"{origin}/api/models/qwen3.6-35b-a3b-128k/settings "
                             "-d '{\"mem_limit_mb\":1}'",
                             status2, body2, status2 == 400 and code2 == "bad_request")

        # -- 10. 422 in the same shape --------------------------------------
        status, body = curl(*auth, "-X", "POST", f"{origin}/api/settings",
                            "-H", "Content-Type: application/json",
                            "-d", '{"max_queue":"twelve"}')
        code = json.loads(body).get("code") if status else None
        failures += not step("校验错误 422 也是同一个错误体",
                             f"curl -H 'Authorization: Bearer $KEY' -X POST "
                             f"{origin}/api/settings "
                             "-H 'Content-Type: application/json' "
                             "-d '{\"max_queue\":\"twelve\"}'",
                             status, body,
                             status == 422 and code == "validation_error"
                             and isinstance(json.loads(body)["detail"], str))

        # -- 11. the documents the walkthrough came from --------------------
        status, body = curl(*auth, f"{origin}/api/openapi.json")
        paths = operations = 0
        if status == 200:
            spec = json.loads(body)
            paths = len(spec["paths"])
            # ``paths`` counts unique paths, not operations: several serve two
            # verbs, and it is the operations the document is about.
            operations = sum(len(item) for item in spec["paths"].values())
        failures += not step("管理 openapi.json（admin key 可读）",
                             f"curl -H 'Authorization: Bearer $KEY' "
                             f"{origin}/api/openapi.json",
                             status,
                             f'{{"{paths} 条路径, {operations} 个操作"}}',
                             status == 200 and operations >= 60)
        status, body = curl(f"{origin}/api/openapi.json")
        failures += not step("没有凭据读文档 → 401",
                             f"curl {origin}/api/openapi.json",
                             status, body, status == 401)
    finally:
        service.terminate()
        try:
            service.wait(timeout=20)
        except subprocess.TimeoutExpired:  # pragma: no cover
            service.kill()
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)
        else:
            print(f"kept {root}")

    print(f"\n{'ALL PASS' if not failures else f'{failures} FAILED'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
