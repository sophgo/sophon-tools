"""MYS-2691 D7: replay the operation sequence that wedged the TPU on 2026-11-07.

The sequence, in the issue's order:

  1. load all six models;
  2. ``kill -9`` the main process -- once with a worker idle, once with a worker
     mid-inference;
  3. unload / load OCR five times;
  4. ten minutes of mixed load across all six models.

Run it on the board with the service already up and all models unloaded:

    PYTHONPATH=/opt/sophgo/cv84x6_llm_server/vendor python3.10 d7_replay.py [soak_minutes]

It prints one line per phase and, at the end, the dmesg counters that decide
whether the wedge happened (``wait api timeout`` / ``NPU fault`` / ``recursive
fault``) plus the ``systemctl reboot --force --force`` count, which is 0 unless a
phase had to be recovered from.
"""
from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
import sys
import threading
import time

import httpx

BASE = "http://127.0.0.1:8000"
KEY = open("/data/mys2691/adminkey").read().strip()
IMG = "/data/Qwen3VL/python_demo/contract.png"
MP3 = "/data/mys2691/zh.mp3"
MODELS = ["qwen3.6-35b-a3b-128k", "qwen3-embedding-0.6b", "bge-reranker-v2-m3",
          "qwen3-asr-0.6b", "ppocrv6-medium", "paddleocr-vl-1.5"]

admin = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {KEY}"},
                     timeout=900)
infer = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {KEY}"},
                     timeout=900)

b64 = base64.b64encode(open(IMG, "rb").read()).decode()
audio = open(MP3, "rb").read() if os.path.exists(MP3) else b""


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def heaps() -> dict:
    d = admin.get("/api/stats").json()["device"]["device_mem"]
    return {h["name"]: h["used_bytes"] >> 20 for h in d["heaps"]}


def dmesg_counts() -> dict:
    out = sh("sudo dmesg")
    return {
        "wait_api_timeout": out.count("wait api timeout"),
        "npu_fault": out.count("NPU fault"),
        "recursive_fault": out.count("recursive fault"),
        "bmlib_error": out.count("[bmlib_"),
        "lines": len(out.splitlines()),
    }


def model_state() -> dict:
    try:
        rows = admin.get("/api/models").json()["models"]
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:120]}
    return {m["id"]: {"loaded": m["loaded"], "adopted": m.get("adopted"),
                      "pid": m.get("pid")} for m in rows}


def main_pid() -> int:
    return int(sh("systemctl show -p MainPID --value cv84x6-llm") or 0)


def worker_pid(model: str) -> int:
    out = sh(f"pgrep -f 'app.engine.worker.*--model-id {model}'")
    return int(out.split()[0]) if out else 0


def alive(pid: int) -> bool:
    return pid > 0 and os.path.exists(f"/proc/{pid}")


def wait_up(timeout: float = 180) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if admin.get("/healthz", timeout=5).status_code == 200:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    return False


def phase(name: str) -> None:
    print(f"\n=== {name}  t={time.strftime('%H:%M:%S')}", flush=True)
    print("    heaps", heaps(), "dmesg", dmesg_counts(), flush=True)


def load_all() -> bool:
    for model in MODELS:
        t0 = time.time()
        r = admin.post(f"/api/models/{model}/load")
        print(f"    load {model}: {r.status_code} in {time.time() - t0:.1f}s",
              flush=True)
        if r.status_code != 200:
            print("    ", r.text[:200], flush=True)
            return False
    return True


def crash(kind: str) -> dict:
    """kill -9 the service; report whether its workers survived."""
    model = "qwen3.6-35b-a3b-128k" if kind == "busy" else "qwen3-embedding-0.6b"
    pid = worker_pid(model)
    busy_request = None
    if kind == "busy":
        def fire():
            try:
                infer.post("/v1/chat/completions", json={
                    "model": model, "max_tokens": 700,
                    "messages": [{"role": "user",
                                  "content": "写一篇八百字的散文，主题是秋天。"}]})
            except Exception:  # noqa: BLE001
                pass
        busy_request = threading.Thread(target=fire, daemon=True)
        busy_request.start()
        time.sleep(4)

    main = main_pid()
    print(f"    kill -9 main={main}; watching {kind} worker={pid}", flush=True)
    subprocess.run(f"sudo kill -9 {main}", shell=True)
    time.sleep(3)
    survived = alive(pid)
    print(f"    worker survived the crash: {survived}", flush=True)

    wait_up()
    time.sleep(8)
    state = model_state().get(model, {})
    print(f"    after restart: {state}", flush=True)
    return {"kind": kind, "worker": pid, "survived": survived, "state": state}


def ocr_cycles(n: int = 5) -> bool:
    ok = True
    for i in range(n):
        admin.post("/api/models/ppocrv6-medium/load")
        r = admin.post("/v1/ocr", json={"model": "ppocrv6-medium", "image": b64,
                                        "mode": "layout"})
        admin.post("/api/models/ppocrv6-medium/unload")
        print(f"    ocr cycle {i}: {r.status_code}, heaps {heaps()}", flush=True)
        ok = ok and r.status_code == 200
    return ok


def mixed_load(minutes: float) -> dict:
    """Four agents' worth of traffic: 2 chat streams + embed + rerank + OCR + VL + ASR."""
    stop = time.time() + minutes * 60
    codes: dict[str, list] = {}

    def record(kind, code):
        codes.setdefault(kind, []).append(code)

    def loop(kind, fn, pause):
        c = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {KEY}"},
                         timeout=900)
        while time.time() < stop:
            try:
                record(kind, fn(c))
            except Exception as exc:  # noqa: BLE001
                record(kind, f"exc:{type(exc).__name__}")
            time.sleep(pause)

    def chat(c):
        return c.post("/v1/chat/completions", json={
            "model": "qwen3.6-35b-a3b-128k", "max_tokens": 128,
            "messages": [{"role": "user",
                          "content": "用两三句话解释设备巡检。"}]}).status_code

    def embed(c):
        return c.post("/v1/embeddings", json={
            "model": "qwen3-embedding-0.6b", "input": "巡检记录"}).status_code

    def rerank(c):
        return c.post("/v1/rerank", json={
            "model": "bge-reranker-v2-m3", "query": "合格率",
            "documents": ["合格率 99%", "无关内容"]}).status_code

    def ocr(c):
        return c.post("/v1/ocr", json={"model": "ppocrv6-medium",
                                       "image": b64}).status_code

    def vl(c):
        return c.post("/v1/chat/completions", json={
            "model": "paddleocr-vl-1.5", "max_tokens": 256,
            "messages": [{"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64," + b64}},
                {"type": "text", "text": "OCR:"}]}]}).status_code

    def asr(c):
        if not audio:
            return "no-audio-fixture"
        return c.post("/v1/audio/transcriptions", data={"model": "qwen3-asr-0.6b"},
                      files={"file": ("a.mp3", audio, "audio/mpeg")}).status_code

    threads = [threading.Thread(target=loop, args=a) for a in (
        ("chat", chat, 0.5), ("chat", chat, 0.5), ("embed", embed, 2),
        ("rerank", rerank, 2), ("ocr", ocr, 5), ("vl", vl, 5), ("asr", asr, 5))]

    for t in threads:
        t.start()
    while time.time() < stop:
        h = heaps()
        try:
            tpu = admin.get("/api/stats").json()["device"]["tpu_usage"]["percent"]
        except Exception:  # noqa: BLE001
            tpu = "?"
        print(f"    {time.strftime('%H:%M:%S')} heaps={h} tpu={tpu}", flush=True)
        time.sleep(30)
    for t in threads:
        t.join()

    summary = {k: {c: v.count(c) for c in set(v)} for k, v in codes.items()}
    print("    request outcomes:", json.dumps(summary), flush=True)
    return summary


def main() -> int:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0

    phase("start")
    phase("1. load six models")
    if not load_all():
        print("    a model failed to load; stopping here", flush=True)
        return 1
    print("    loaded:", model_state(), flush=True)

    phase("2a. kill -9 main, worker idle")
    crash("idle")
    phase("2b. kill -9 main, worker mid-inference")
    crash("busy")

    phase("3. OCR load/unload x5")
    ocr_cycles(5)

    phase(f"4. mixed load {minutes:.0f} min over six models")
    mixed_load(minutes)

    phase("final")
    print("    models:", model_state(), flush=True)
    print("    dmesg:", dmesg_counts(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
