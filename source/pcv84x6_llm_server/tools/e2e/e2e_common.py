"""Shared helpers for the v0.6.29 E2E run (MYS-2682) against the 10155 board.

The board's :8000 is reached through an SSH tunnel on 127.0.0.1:18155.
Results are appended to ledger.jsonl: one line per check, with the area, the
check id, PASS/FAIL/BLOCKED and the evidence that decided it.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import httpx

BASE = os.environ.get("E2E_BASE", "http://127.0.0.1:18155")
ROOT = Path(os.environ.get("E2E_WORKDIR") or Path(__file__).resolve().parent.parent)
ADMIN_KEY = (ROOT / "adminkey").read_text().strip()
INFER_KEY = (ROOT / "inferkey").read_text().strip()
LEDGER = ROOT / "ledger.jsonl"
# Wrapper that runs one shell command on the board over SSH (not in the repo: it holds the login).
S155 = os.environ.get("E2E_BOARD_SH", "/home/zzt/workspace/cv84x6-demo-run/s155n.sh")
# Board commands write the sudo password as __SUDO_PW__; it is filled in here, never stored in the repo.
SUDO_PW = os.environ.get("E2E_SUDO_PW", "")

admin = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {ADMIN_KEY}"}, timeout=600)
infer = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {INFER_KEY}"}, timeout=600)


def record(area: str, check: str, ok: bool | None, evidence: str, **extra) -> None:
    """ok: True=PASS, False=FAIL, None=BLOCKED."""
    verdict = "PASS" if ok else ("BLOCKED" if ok is None else "FAIL")
    row = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "area": area, "check": check,
           "verdict": verdict, "evidence": evidence, **extra}
    with LEDGER.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[{verdict}] {area} · {check} · {evidence}")


def board(cmd: str, timeout: int = 600) -> str:
    """Run a shell command on the board (non-interactive), return stdout+stderr."""
    cmd = cmd.replace("__SUDO_PW__", SUDO_PW)
    out = subprocess.run([S155, cmd], capture_output=True, text=True, timeout=timeout)
    lines = [l for l in (out.stdout + out.stderr).splitlines()
             if not any(w in l for w in ("Warning", "quantum", "store now", "upgraded"))]
    return "\n".join(lines)


def stats() -> dict:
    return admin.get("/api/stats").json()


def heaps() -> dict:
    dm = stats()["device"]["device_mem"]
    return {h["name"]: h["used_bytes"] >> 20 for h in dm["heaps"]}


def models() -> dict:
    return {m["id"]: m for m in admin.get("/api/models").json()["models"]}


def load(model_id: str, timeout: float = 600) -> tuple[int, float, str]:
    t0 = time.time()
    r = admin.post(f"/api/models/{model_id}/load", timeout=timeout)
    return r.status_code, time.time() - t0, r.text[:300]


def unload(model_id: str) -> tuple[int, str]:
    r = admin.post(f"/api/models/{model_id}/unload", timeout=300)
    return r.status_code, r.text[:200]
