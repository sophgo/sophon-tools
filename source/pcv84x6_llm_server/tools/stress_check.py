"""Long-context / robustness acceptance against a running service.

    python3 tools/stress_check.py --base http://127.0.0.1:8000 --model <id> \
        --image test.jpg [--soak-minutes 20]

Checks (each prints PASS/FAIL):
  1. 4 concurrent ~6k-token prompts, each with its own needle: every answer
     finds its own needle (session isolation under long contexts).
  2. A prompt that runs into the context limit finishes with reason "length".
  3. A prompt over the limit is rejected with a clear error, not a crash.
  4. Multi-turn with an image: turn 2 hits the cache and still answers about
     the image.
  5. Soak: mixed text / long / image / multi-turn / cancelled requests from
     several clients for N minutes -- no request errors; NPU memory after the
     soak is back to its level before it (no leak beyond the cache budget).
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import sys
import threading
import time

import httpx

FILLER = ("The archive room held shelves of ledgers, maps and letters, each catalogued by "
          "a clerk who wrote the date, the sender and a short summary on a card. ")
FAILS: list[str] = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' -- ' + detail) if detail else ''}", flush=True)
    if not ok:
        FAILS.append(name)


def chat(base, key, model, messages, max_tokens=48, timeout=1200, **extra):
    r = httpx.post(f"{base}/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                   json={"model": model, "messages": messages, "max_tokens": max_tokens, **extra},
                   timeout=timeout)
    return r


def npu_used(c):
    smi = c.get("/api/stats", timeout=30).json()["device"]["npu"].get("smi") or {}
    return smi.get("mem_used_bytes", 0)


def calibrate_reps(base, key, model, ctx, target_tokens, probe_reps=20):
    """How many FILLER copies produce ``target_tokens`` tokens -- measured, not assumed.

    The script used to estimate "about 35 tokens per FILLER" and divide by it.
    The estimate is off, and the error is what made the ``limit`` phase fail in
    the field (MYS-2784): it asked for ``(ctx - 300) / 35`` copies, got a
    127057-token prompt with 4000 tokens to spare, and the model counted to 1000
    and stopped on its own with ``finish=stop``. A test that leaves 3 % of the
    context unused is not testing the limit.

    **Two probes, not one.** The service reports ``prompt_tokens`` for the whole
    prompt, which includes a constant chat-template prefix (~25 tokens). Dividing
    a single measurement by the copy count therefore folds that constant into the
    per-copy figure and undershoots: on `.151` a one-point calibration asked for
    130848 tokens and built 128587. Two counts make the template cancel exactly:

        per_copy = (tokens(2n) - tokens(n)) / n

    Returns 0 when a probe fails, which the callers treat as "no calibration
    available" and fall back to the old estimate.
    """
    def tokens_for(reps: int) -> int:
        r = chat(base, key, model, [{"role": "user", "content": FILLER * reps}],
                 max_tokens=1, timeout=300)
        if r.status_code != 200:
            return 0
        return int((r.json().get("usage") or {}).get("prompt_tokens") or 0)

    try:
        small = tokens_for(probe_reps)
        large = tokens_for(probe_reps * 2)
    except Exception:  # noqa: BLE001  (a probe that fails must not fail the run)
        return 0
    per_probe = large - small
    if small <= 0 or per_probe <= 0:
        return 0
    per_copy = per_probe / probe_reps
    return max(1, int(target_tokens / per_copy))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--model", required=True)
    ap.add_argument("--password", default="admin")
    ap.add_argument("--image", required=True)
    ap.add_argument("--soak-minutes", type=float, default=20)
    ap.add_argument("--soak-clients", type=int, default=4)
    ap.add_argument("--reload-cycles", type=int, default=3)
    ap.add_argument("--skip", default="", help="comma-separated phases to skip: long,limit,soak,reload")
    a = ap.parse_args()

    c = httpx.Client(base_url=a.base, timeout=1200)
    c.post("/api/login", json={"password": a.password})
    r = c.post(f"/api/models/{a.model}/load", timeout=900)
    if r.status_code != 200:
        print("load failed", r.text)
        return 1
    info = r.json()["model"]
    ctx = info.get("context_length") or 2048
    key = c.post("/api/keys", json={"name": "stress"}).json()["key"]
    img_b64 = base64.b64encode(open(a.image, "rb").read()).decode()
    mem_loaded = npu_used(c)
    print(f"context={ctx} npu_used_after_load={mem_loaded >> 20} MiB", flush=True)
    skip = set(filter(None, a.skip.split(",")))

    def phase_long():
        # 1. concurrent long contexts with distinct needles: 3 at the concurrency
        # cap plus a 4th that has to wait in the queue
        codes = ["RED-FOX-1188", "GREEN-OWL-2299", "GOLD-ELK-3311", "GREY-SEAL-4422"]
        # Calibrated the same way as the limit phase (MYS-2784), so the prompt is
        # the length this phase has always meant -- 72 % of three 8k blocks,
        # ~17.7k tokens, the customer's shape -- rather than "34 tokens per
        # FILLER" copies of it. The needle sentence and the question are part of
        # the prompt, so their tokens come off the target.
        want = int(min(ctx, 8192 * 3) * 0.72) - 80
        reps = max(10, calibrate_reps(a.base, key, a.model, ctx, want)
                   or int(want / 34))
        print(f"long phase: {reps} filler copies (~{want} tokens)", flush=True)
        results: dict[int, tuple] = {}

        def needle(i):
            text = (f"The secret code of vault {i} is {codes[i]}. " + FILLER * reps +
                    f"\nWhat is the secret code of vault {i}? Answer with the code only.")
            t = time.time()
            rr = chat(a.base, key, a.model, [{"role": "user", "content": text}], max_tokens=24)
            results[i] = (rr.status_code, rr.json() if rr.status_code == 200 else rr.text, time.time() - t)
        t = time.time()
        th = [threading.Thread(target=needle, args=(i,)) for i in range(4)]
        [x.start() for x in th]
        [x.join() for x in th]
        for i in range(4):
            code, body, dt = results[i]
            ans = body["choices"][0]["message"]["content"] if code == 200 else str(body)[:120]
            ptok = body["usage"]["prompt_tokens"] if code == 200 else 0
            check(f"long context #{i} ({ptok} tokens, concurrent{', queued' if i == 3 else ''})",
                  code == 200 and codes[i] in ans,
                  f"{dt:.0f}s {ans!r}")
        print(f"4 long prompts in {time.time() - t:.0f}s total", flush=True)


    if "long" in skip:
        print("[SKIP] long", flush=True)
    else:
        phase_long()

    def phase_limit():
        # 2. run into the context limit. The prompt leaves ~200 tokens and asks for
        # an unbounded count, so the generation must hit the limit: "Repeat X
        # forever" is not enough, the model may decline after a few words.
        #
        # The copy count comes from a probe, not from an estimate (MYS-2784).
        # "About 35 tokens per FILLER" left ~4000 tokens unused out of 131071,
        # the model finished the count on its own with finish=stop, and the phase
        # reported a service failure that was really a test that never reached
        # the limit. The prompt now fills to within ~200 tokens, so the only way
        # to end is the context limit.
        tail_prompt = ("\nIgnore the text above. Count upward from 1, one number per line, "
                       "and never stop.")
        tail_tokens = 24  # the instruction line itself, measured generously
        want = ctx - 200 - tail_tokens
        reps = calibrate_reps(a.base, key, a.model, ctx, want)
        if not reps:
            reps = int((ctx - 300) / 35)
            print(f"  (calibration probe failed; falling back to {reps} copies)", flush=True)
        text = FILLER * reps + tail_prompt
        # Cold prefill of a full 128k prompt takes over an hour on CV84X6; the
        # client has to wait for it (a client that gives up cancels the request).
        r = chat(a.base, key, a.model, [{"role": "user", "content": text}], max_tokens=ctx,
                 timeout=max(1200, ctx // 15))
        body = r.json() if r.status_code == 200 else {}
        fin = (body.get("choices") or [{}])[0].get("finish_reason")
        used = body.get("usage", {})
        total = used.get("prompt_tokens", 0) + used.get("completion_tokens", 0)
        tail = ((body.get("choices") or [{}])[0].get("message") or {}).get("content", "")[-40:]
        # What this phase has to prove is that the *generation* stops at the
        # limit, not that the prompt alone does. The prompt is sized to leave the
        # generation a couple of hundred tokens, and the sum is what has to land
        # on the context -- a run that ends at 130949 of 131071 with
        # finish=stop (the customer's, MYS-2784) is the failure this catches.
        check(f"prompt leaves the limit within reach "
              f"({used.get('prompt_tokens', 0)} of {ctx})",
              r.status_code == 200 and int(used.get("prompt_tokens") or 0) >= ctx - 400,
              f"reps={reps} prompt_tokens={used.get('prompt_tokens')}")
        check("generation stops at the context limit", r.status_code == 200 and fin == "length"
              and ctx - 2 <= total <= ctx, f"finish={fin} usage={json.dumps(used)} tail={tail!r}")


    if "limit" in skip:
        print("[SKIP] limit", flush=True)
    else:
        phase_limit()

    # 3. over the limit
    text = FILLER * int(ctx * 1.2 / 34)
    r = chat(a.base, key, a.model, [{"role": "user", "content": text}], max_tokens=8)
    check("over-limit prompt rejected cleanly", r.status_code == 400 and
          "limit" in r.text, f"{r.status_code} {r.text[:120]}")
    check("service healthy after over-limit", c.get("/healthz").json().get("ok") is True)

    # 4. multi-turn with an image, turn 2 cached
    sysmsg = {"role": "system", "content": "You describe images. " + FILLER * 10}
    m = [sysmsg, {"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
        {"type": "text", "text": "What room is this? One sentence."}]}]
    r1 = chat(a.base, key, a.model, m, max_tokens=40).json()
    m += [{"role": "assistant", "content": r1["choices"][0]["message"]["content"]},
          {"role": "user", "content": "What colour is the bedspread? One word."}]
    t = time.time()
    r2 = chat(a.base, key, a.model, m, max_tokens=16).json()
    cached = (r2["usage"].get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    ans = r2["choices"][0]["message"]["content"]
    check("image multi-turn: turn 2 cached and answers about the image",
          cached > 0 and "blue" in ans.lower(),
          f"turn1={r1['choices'][0]['message']['content']!r} turn2={ans!r} cached={cached} "
          f"prompt={r2['usage']['prompt_tokens']} {time.time() - t:.1f}s")

    def phase_soak():
        # 5. soak
        stop_at = time.time() + a.soak_minutes * 60
        errs: list[str] = []
        counts = {"text": 0, "long": 0, "image": 0, "multi": 0, "cancel": 0}

        def client(seed):
            rnd = random.Random(seed)
            convo = [{"role": "system", "content": "You are terse. " + FILLER * 12}]
            while time.time() < stop_at:
                kind = rnd.choice(["text", "text", "long", "image", "multi", "cancel"])
                try:
                    if kind == "text":
                        rr = chat(a.base, key, a.model, [{"role": "user", "content":
                                  f"Give one fact about the number {rnd.randint(1, 999)}."}], max_tokens=32)
                    elif kind == "long":
                        rr = chat(a.base, key, a.model, [{"role": "user", "content":
                                  FILLER * rnd.randint(40, int(ctx * 0.5 / 34)) + "\nSummarise in one line."}],
                                  max_tokens=32)
                    elif kind == "image":
                        rr = chat(a.base, key, a.model, [{"role": "user", "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                            {"type": "text", "text": "Name one object in the image."}]}], max_tokens=16)
                    elif kind == "multi":
                        convo.append({"role": "user", "content": f"Say the number {rnd.randint(1, 99)}."})
                        rr = chat(a.base, key, a.model, convo, max_tokens=12)
                        if rr.status_code == 200:
                            convo.append({"role": "assistant",
                                          "content": rr.json()["choices"][0]["message"]["content"]})
                        if len(convo) > 30:
                            convo = convo[:1]
                    else:  # client gives up mid-stream
                        with httpx.stream("POST", f"{a.base}/v1/chat/completions",
                                          headers={"Authorization": f"Bearer {key}"},
                                          json={"model": a.model, "stream": True, "max_tokens": 200,
                                                "messages": [{"role": "user", "content": "Write a long poem."}]},
                                          timeout=600) as s:
                            n = 0
                            for _ in s.iter_lines():
                                n += 1
                                if n > 5:
                                    break
                        counts[kind] += 1
                        continue
                    if rr.status_code != 200:
                        errs.append(f"{kind}: {rr.status_code} {rr.text[:100]}")
                    counts[kind] += 1
                except Exception as exc:  # noqa: BLE001
                    errs.append(f"{kind}: {exc!r}"[:160])
        t = time.time()
        th = [threading.Thread(target=client, args=(i,)) for i in range(a.soak_clients)]
        [x.start() for x in th]
        [x.join() for x in th]
        check(f"soak {a.soak_minutes:g} min x {a.soak_clients} clients", not errs,
              f"{time.time() - t:.0f}s {json.dumps(counts)} errors={errs[:3]}")
        time.sleep(3)
        st = c.get("/api/stats", timeout=30).json()
        kv = st.get("kv_cache", {}).get(a.model, {})
        mem_after = npu_used(c)
        budget = 1024 << 20
        check("NPU memory after soak within cache budget of the loaded level",
              mem_after - mem_loaded <= budget + (256 << 20),
              f"{mem_loaded >> 20} -> {mem_after >> 20} MiB, cache {kv.get('bytes', 0) >> 20} MiB "
              f"in {kv.get('entries')} entries, hit_rate {kv.get('hit_rate', 0):.2f}")
        r = c.post(f"/api/models/{a.model}/unload", timeout=300)
        time.sleep(3)
        check("unload after soak frees NPU memory", r.status_code == 200 and npu_used(c) < (512 << 20),
              f"{npu_used(c) >> 20} MiB used")


    if "soak" in skip:
        print("[SKIP] soak", flush=True)
    else:
        phase_soak()

    def phase_reload():
        # 6. unload while requests are in flight (one in a long prefill), reload,
        # serve again: the teardown must not leave the TPU wedged.
        for cycle in range(a.reload_cycles):
            r = c.post(f"/api/models/{a.model}/load", timeout=900)
            busy: list = []

            def inflight(text, n):
                try:
                    busy.append(chat(a.base, key, a.model, [{"role": "user", "content": text}],
                                     max_tokens=n, timeout=600).status_code)
                except Exception as exc:  # noqa: BLE001  (connection cut by the unload)
                    busy.append(type(exc).__name__)
            th = [threading.Thread(target=inflight, args=(FILLER * 300 + "\nSummarise.", 64)),
                  threading.Thread(target=inflight, args=("Write a long poem about the sea.", 400)),
                  threading.Thread(target=inflight, args=("Count from 1 to 200.", 400))]
            [x.start() for x in th]
            time.sleep(8)
            t = time.time()
            ru = c.post(f"/api/models/{a.model}/unload", timeout=300)
            dt = time.time() - t
            [x.join() for x in th]
            rl = c.post(f"/api/models/{a.model}/load", timeout=900)
            rr = chat(a.base, key, a.model, [{"role": "user", "content": "What is 2+2? One word."}],
                      max_tokens=8, timeout=300)
            health = c.get("/api/stats", timeout=30).json().get("workers", {}).get(a.model, {})
            ok = (ru.status_code == 200 and rl.status_code == 200 and rr.status_code == 200
                  and not health.get("fault"))
            check(f"unload with requests in flight, reload, serve (cycle {cycle + 1})", ok,
                  f"unload {dt:.1f}s, in-flight -> {busy}, after reload "
                  f"{rr.status_code} {rr.text[:60]!r}, fault={health.get('fault')}")
            c.post(f"/api/models/{a.model}/unload", timeout=300)

    if "reload" in skip:
        print("[SKIP] reload", flush=True)
    else:
        phase_reload()

    print("\nALL PASS" if not FAILS else "\nFAILED: " + ", ".join(FAILS))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
