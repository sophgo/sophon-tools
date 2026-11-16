"""MYS-2691 D7 phase 4, corrected: all SIX models loaded while the load runs.

The first run left OCR unloaded at the end of phase 3, so every /v1/ocr in the
mixed-load phase was a 409 -- five models under load, not six. This reloads
everything it can and asserts each model answers 200 before starting the clock,
so "six models" is a fact about the run rather than an assumption.

    PYTHONPATH=/opt/sophgo/cv84x6_llm_server/vendor python3.10 d7_six.py [minutes]
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import time

import httpx

BASE = "http://127.0.0.1:8000"
KEY = open("/data/mys2691/adminkey").read().strip()
IMG = "/data/mys2691/page.png"
MP3 = "/data/mys2691/zh.mp3"
MODELS = ["qwen3.6-35b-a3b-128k", "qwen3-embedding-0.6b", "bge-reranker-v2-m3",
          "qwen3-asr-0.6b", "ppocrv6-medium", "paddleocr-vl-1.5"]

admin = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {KEY}"},
                     timeout=900)
infer = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {KEY}"},
                     timeout=900)
b64 = base64.b64encode(open(IMG, "rb").read()).decode()
audio = open(MP3, "rb").read()


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def heaps() -> dict:
    d = admin.get("/api/stats").json()["device"]["device_mem"]
    return {h["name"]: h["used_bytes"] >> 20 for h in d["heaps"]}


def dmesg_counts() -> dict:
    out = sh("sudo dmesg")
    return {"wait_api_timeout": out.count("wait api timeout"),
            "npu_fault": out.count("NPU fault"),
            "recursive_fault": out.count("recursive fault"),
            "bmlib_error": out.count("[bmlib_")}


def loaded() -> dict:
    return {m["id"]: m["loaded"] for m in admin.get("/api/models").json()["models"]}


def ensure_loaded() -> bool:
    for model in MODELS:
        if not loaded().get(model):
            r = admin.post(f"/api/models/{model}/load")
            print(f"    load {model}: {r.status_code}", flush=True)
            if r.status_code != 200:
                print("    ", r.text[:200], flush=True)
                return False
    return all(loaded().get(m) for m in MODELS)


def probe() -> dict:
    """One call per model, so 'six models answer' is proven before the clock."""
    def code(fn):
        try:
            return fn(infer)
        except Exception as exc:  # noqa: BLE001
            return f"exc:{type(exc).__name__}"

    return {
        "chat": code(lambda c: c.post("/v1/chat/completions", json={
            "model": "qwen3.6-35b-a3b-128k", "max_tokens": 24,
            "messages": [{"role": "user", "content": "你好"}]}).status_code),
        "embed": code(lambda c: c.post("/v1/embeddings", json={
            "model": "qwen3-embedding-0.6b", "input": "巡检"}).status_code),
        "rerank": code(lambda c: c.post("/v1/rerank", json={
            "model": "bge-reranker-v2-m3", "query": "合格率",
            "documents": ["合格率 99%", "无关"]}).status_code),
        "ocr": code(lambda c: c.post("/v1/ocr", json={
            "model": "ppocrv6-medium", "image": b64}).status_code),
        "vl": code(lambda c: c.post("/v1/chat/completions", json={
            "model": "paddleocr-vl-1.5", "max_tokens": 64,
            "messages": [{"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64," + b64}},
                {"type": "text", "text": "OCR:"}]}]}).status_code),
        "asr": code(lambda c: c.post("/v1/audio/transcriptions",
                                     data={"model": "qwen3-asr-0.6b"},
                                     files={"file": ("a.mp3", audio, "audio/mpeg")}).status_code),
    }


def main() -> int:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    print("=== ensure six models loaded", flush=True)
    if not ensure_loaded():
        print("    could not load all six; aborting", flush=True)
        return 1
    print("    loaded:", loaded(), flush=True)
    print("    heaps:", heaps(), flush=True)

    before = probe()
    print("    probe (one call per model):", json.dumps(before), flush=True)
    if any(not (isinstance(v, int) and v == 200) for v in before.values()):
        print("    a model did not answer 200 before the run; aborting so the "
              "result cannot be read as six models under load", flush=True)
        return 1

    stop = time.time() + minutes * 60
    codes: dict[str, list] = {}

    def loop(kind, fn, pause):
        c = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {KEY}"},
                         timeout=900)
        while time.time() < stop:
            try:
                codes.setdefault(kind, []).append(fn(c))
            except Exception as exc:  # noqa: BLE001
                codes.setdefault(kind, []).append(f"exc:{type(exc).__name__}")
            time.sleep(pause)

    def chat_a(c):
        return c.post("/v1/chat/completions", json={
            "model": "qwen3.6-35b-a3b-128k", "max_tokens": 128,
            "messages": [{"role": "user",
                          "content": "用两三句话解释设备巡检。"}]}).status_code

    def chat_b(c):
        return c.post("/v1/chat/completions", json={
            "model": "qwen3.6-35b-a3b-128k", "max_tokens": 128,
            "messages": [{"role": "user",
                          "content": "总结一下今天的巡检结果。"}]}).status_code

    def embed(c):
        return c.post("/v1/embeddings", json={
            "model": "qwen3-embedding-0.6b", "input": "巡检记录"}).status_code

    def rerank(c):
        return c.post("/v1/rerank", json={
            "model": "bge-reranker-v2-m3", "query": "合格率",
            "documents": ["合格率 99%", "无关内容"]}).status_code

    def ocr(c):
        return c.post("/v1/ocr", json={
            "model": "ppocrv6-medium", "image": b64}).status_code

    def vl(c):
        return c.post("/v1/chat/completions", json={
            "model": "paddleocr-vl-1.5", "max_tokens": 256,
            "messages": [{"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64," + b64}},
                {"type": "text", "text": "OCR:"}]}]}).status_code

    def asr(c):
        return c.post("/v1/audio/transcriptions",
                      data={"model": "qwen3-asr-0.6b"},
                      files={"file": ("a.mp3", audio, "audio/mpeg")}).status_code

    threads = [threading.Thread(target=loop, args=a) for a in (
        ("chat", chat_a, 0.5), ("chat", chat_b, 0.5),
        ("embed", embed, 2), ("rerank", rerank, 2),
        ("ocr", ocr, 5), ("vl", vl, 5), ("asr", asr, 5))]

    for t in threads:
        t.start()
    while time.time() < stop:
        try:
            tpu = admin.get("/api/stats").json()["device"]["tpu_usage"]["percent"]
        except Exception:  # noqa: BLE001
            tpu = "?"
        print(f"    {time.strftime('%H:%M:%S')} heaps={heaps()} tpu={tpu} "
              f"dmesg={dmesg_counts()}", flush=True)
        time.sleep(30)
    for t in threads:
        t.join()

    summary = {k: sorted({str(x) for x in v}) for k, v in codes.items()}
    print("    request outcomes:", json.dumps(summary), flush=True)
    print("    heaps:", heaps(), flush=True)
    print("    dmesg:", dmesg_counts(), flush=True)
    print("    still loaded:", loaded(), flush=True)
    bad = {k: v for k, v in summary.items() if v != ["200"]}
    print("    non-200 kinds:", json.dumps(bad), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
