"""End-to-end check of a running service (release acceptance).

    python3 tools/e2e_check.py --base http://127.0.0.1:8000 --model qwen3.5-35b-a3b \
        [--image test.jpg] [--password admin] [--concurrency 4] [--burst 32]

Loads the model through the console API, mints an API key, then exercises
/v1/models, plain and streamed chat, an image request, thinking mode,
concurrent requests, a burst of parallel short requests, /api/stats, and
finally unloads the model and checks the NPU memory comes back. Prints one
line per check and exits non-zero on the first failure.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import threading
import time

import httpx

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' -- ' + detail) if detail else ''}", flush=True)
    if not ok:
        FAILS.append(name)


def chat(c: httpx.Client, key: str, model: str, content, max_tokens=48, **extra) -> dict:
    r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
               json={"model": model, "messages": [{"role": "user", "content": content}],
                     "max_tokens": max_tokens, **extra}, timeout=600)
    r.raise_for_status()
    return r.json()


def npu_mem_used(c: httpx.Client) -> int | None:
    smi = c.get("/api/stats", timeout=30).json()["device"]["npu"].get("smi") or {}
    return smi.get("mem_used_bytes")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--model", required=True)
    ap.add_argument("--password", default="admin")
    ap.add_argument("--image", default=None)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--burst", type=int, default=32)
    ap.add_argument("--keep-loaded", action="store_true")
    a = ap.parse_args()

    c = httpx.Client(base_url=a.base, timeout=60)
    check("healthz", c.get("/healthz").json().get("ok") is True)
    r = c.post("/api/login", json={"password": a.password})
    check("console login", r.status_code == 200, str(r.status_code))
    if r.status_code != 200:
        return 1

    mem0 = npu_mem_used(c)
    t = time.time()
    r = c.post(f"/api/models/{a.model}/load", timeout=600)
    check("load model", r.status_code == 200, f"{time.time() - t:.1f}s {r.text[:200]}")
    if r.status_code != 200:
        return 1
    mem1 = npu_mem_used(c)
    check("NPU memory grows on load", mem0 is None or (mem1 or 0) > (mem0 or 0),
          f"{(mem0 or 0) >> 20} -> {(mem1 or 0) >> 20} MiB")

    r = c.post("/api/keys", json={"name": "e2e"})
    key = r.json().get("key", "")
    check("create API key", r.status_code == 200 and key.startswith("sk-"))

    r = c.get("/v1/models", headers={"Authorization": f"Bearer {key}"})
    ids = [m["id"] for m in r.json().get("data", [])]
    check("/v1/models lists the model", a.model in ids, str(ids))
    r = c.get("/v1/models", headers={"Authorization": "Bearer sk-wrong"})
    check("bad key rejected", r.status_code == 401, str(r.status_code))

    out = chat(c, key, a.model, "What is the capital of France? Answer in one sentence.")
    text = out["choices"][0]["message"]["content"]
    check("text answer", "Paris" in text, repr(text))
    check("usage counted", out["usage"]["prompt_tokens"] > 0 and out["usage"]["completion_tokens"] > 0,
          json.dumps(out["usage"]))
    out2 = chat(c, key, a.model, "What is the capital of France? Answer in one sentence.")
    check("deterministic", out2["choices"][0]["message"]["content"] == text)

    # Streaming
    parts, done = [], False
    with c.stream("POST", "/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                  json={"model": a.model, "stream": True, "max_tokens": 32,
                        "messages": [{"role": "user", "content": "Count from 1 to 5."}]},
                  timeout=600) as s:
        for line in s.iter_lines():
            if not line.startswith("data: "):
                continue
            body = line[6:]
            if body == "[DONE]":
                done = True
                break
            choices = json.loads(body).get("choices") or []  # usage-only final chunk
            delta = choices[0].get("delta", {}).get("content") if choices else None
            if delta:
                parts.append(delta)
    streamed = "".join(parts)
    check("SSE stream", done and "3" in streamed and len(parts) > 3, repr(streamed[:80]))

    # Thinking mode: reasoning_content is a separate channel. A short generation
    # budget can end during reasoning, so an empty content field is legitimate.
    out = chat(c, key, a.model, "What is 17*23?", max_tokens=96, enable_thinking=True)
    message = out["choices"][0]["message"]
    check("thinking mode accepted", bool(message.get("reasoning_content") or message["content"]),
          f"reasoning={message.get('reasoning_content', '')[:80]!r} content={message['content'][:80]!r}")

    if a.image:
        b64 = base64.b64encode(open(a.image, "rb").read()).decode()
        t = time.time()
        out = chat(c, key, a.model, [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": "Describe this image in one sentence."}], max_tokens=64)
        text = out["choices"][0]["message"]["content"]
        check("image answer", len(text) > 20 and "!!!!" not in text,
              f"{time.time() - t:.1f}s prompt={out['usage']['prompt_tokens']} {text!r}")
        t = time.time()
        out = chat(c, key, a.model, [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": "What colour is the comforter on the bed?"}], max_tokens=24)
        check("second image request", len(out["choices"][0]["message"]["content"]) > 2,
              f"{time.time() - t:.1f}s {out['choices'][0]['message']['content']!r}")
        r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                   json={"model": a.model, "messages": [{"role": "user", "content": [
                       {"type": "image_url", "image_url": {"url": "http://example.com/x.jpg"}}]}]})
        check("remote image URL rejected", r.status_code == 400, str(r.status_code))

    # Concurrency: sessions are interleaved token by token and swap their state
    # in and out of the NPU, so the property to check is isolation -- every
    # concurrent answer must equal the same prompt answered alone. (Ground
    # truth is the model's business: the int4 35B answers "Toronto" for
    # Canada in the official demo too.)
    qs = [f"What is the capital of {x}? One word." for x in
          ("Japan", "Italy", "Germany", "Spain", "Egypt", "Canada", "Kenya", "Peru")]
    qs = (qs * ((a.concurrency // len(qs)) + 1))[: a.concurrency]
    solo = {q: chat(c, key, a.model, q, max_tokens=16)["choices"][0]["message"]["content"]
            for q in set(qs)}
    results: dict[int, str] = {}

    def one(i: int, q: str) -> None:
        cc = httpx.Client(base_url=a.base, timeout=600)
        try:
            results[i] = chat(cc, key, a.model, q, max_tokens=16)["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            results[i] = f"ERROR {exc}"
    t = time.time()
    th = [threading.Thread(target=one, args=(i, q)) for i, q in enumerate(qs)]
    [x.start() for x in th]
    [x.join() for x in th]
    wrong = [(q, solo[q], results.get(i)) for i, q in enumerate(qs) if results.get(i) != solo[q]]
    check(f"{a.concurrency} concurrent requests == the same prompts alone", not wrong,
          f"{time.time() - t:.1f}s answers={[results.get(i) for i in range(len(qs))]} wrong={wrong}")

    # Burst: more parallel requests than slots + queue. Each must get either an
    # answer or a 429 (queue full) -- never a 5xx or a hang -- and at least the
    # capacity must be served.
    errs: list[str] = []
    codes: list[int] = []
    lock = threading.Lock()

    def tiny() -> None:
        cc = httpx.Client(base_url=a.base, timeout=900)
        try:
            r1 = cc.get("/v1/models", headers={"Authorization": f"Bearer {key}"})
            if r1.status_code != 200:
                errs.append(f"models {r1.status_code}")
            rr = cc.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                         json={"model": a.model, "max_tokens": 4,
                               "messages": [{"role": "user", "content": "Say OK."}]})
            with lock:
                codes.append(rr.status_code)
            if rr.status_code not in (200, 429):
                errs.append(f"{rr.status_code} {rr.text[:80]}")
        except Exception as exc:  # noqa: BLE001
            errs.append(repr(exc)[:120])
    settings = c.get("/api/settings").json()
    capacity = settings.get("max_concurrent_per_model", 3) + settings.get("max_queue", 16)
    t = time.time()
    th = [threading.Thread(target=tiny) for _ in range(a.burst)]
    [x.start() for x in th]
    [x.join() for x in th]
    ok200 = codes.count(200)
    check(f"burst of {a.burst} parallel requests (capacity {capacity})",
          not errs and ok200 >= min(a.burst, capacity) and
          (a.burst <= capacity or codes.count(429) > 0),
          f"{time.time() - t:.1f}s 200={ok200} 429={codes.count(429)} errors={errs[:3]}")

    st = c.get("/api/stats", timeout=30).json()
    check("stats: usage totals", st["usage"]["completion_tokens"] > 0, json.dumps(
        {k: st["usage"][k] for k in ("prompt_tokens", "completion_tokens", "requests")}))
    smi = st["device"]["npu"].get("smi") or {}
    check("stats: bm-smi NPU memory", bool(smi.get("mem_total_bytes")), json.dumps(smi))
    kv = st.get("kv_cache", {}).get(a.model)
    # On by itself for history bmodels (snapshots need block_kv), off otherwise.
    check("stats: prefix cache state reported", isinstance(kv, dict) and "enabled" in kv,
          json.dumps(kv))

    r = c.post("/api/chat/stream", json={"model": a.model, "prompt": "Hi", "max_tokens": 8},
               timeout=600)
    check("console playground stream", r.status_code == 200 and "[DONE]" in r.text)

    if not a.keep_loaded:
        r = c.post(f"/api/models/{a.model}/unload", timeout=120)
        time.sleep(3)
        mem2 = npu_mem_used(c)
        check("unload releases NPU memory", r.status_code == 200 and (
            mem2 is None or mem1 is None or mem2 < mem1), f"{(mem1 or 0) >> 20} -> {(mem2 or 0) >> 20} MiB")

    print(f"\n{'ALL PASS' if not FAILS else 'FAILED: ' + ', '.join(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
