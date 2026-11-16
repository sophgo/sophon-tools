"""Prefix-cache acceptance against a running service (history bmodel loaded).

    python3 tools/cache_e2e.py --base http://127.0.0.1:8000 --model <id>

An agent-style conversation: a long system prompt, then three turns, each
resending the full history. Prints prompt / cached tokens and first-token
latency per turn, then a second conversation with the same system prompt.
Checks: from turn 2 on, cached_tokens > 0; the cached answer equals the answer
of a cold run of the same messages on a cache-free request (different system
prefix byte -> forced miss is not available, so the check is that turn 1 of
conversation B, which hits only the system prompt, answers like turn 1 of A).
"""
import argparse
import json
import sys
import time

import httpx

SYSTEM = ("You are the archive assistant of the Harbour Museum. " +
          "The archive holds ledgers, maps, letters and photographs, each catalogued "
          "with a date, a sender and a short summary. " * 60 +
          "Answer briefly and precisely.")
TURNS = ["Name three kinds of items the archive holds.",
         "Which detail does every catalogue card record first?",
         "Summarise our conversation in one sentence."]


def ask(c, key, model, messages):
    t = time.time()
    first = None
    text = []
    usage = {}
    with c.stream("POST", "/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                  json={"model": model, "messages": messages, "max_tokens": 64, "stream": True,
                        "stream_options": {"include_usage": True}}, timeout=900) as s:
        for line in s.iter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            d = json.loads(line[6:])
            if d.get("usage"):
                usage = d["usage"]
            for ch in d.get("choices") or []:
                piece = ch.get("delta", {}).get("content")
                if piece:
                    if first is None:
                        first = time.time()
                    text.append(piece)
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    return "".join(text), usage.get("prompt_tokens", 0), cached, (first or time.time()) - t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--model", required=True)
    ap.add_argument("--password", default="admin")
    a = ap.parse_args()
    c = httpx.Client(base_url=a.base, timeout=900)
    c.post("/api/login", json={"password": a.password})
    r = c.post(f"/api/models/{a.model}/load", timeout=900)
    if r.status_code != 200:
        print("load failed", r.text)
        return 1
    key = c.post("/api/keys", json={"name": "cache-e2e"}).json()["key"]
    fails = 0

    msgs = [{"role": "system", "content": SYSTEM}]
    answers = []
    for i, q in enumerate(TURNS):
        msgs.append({"role": "user", "content": q})
        ans, ptok, cached, ftl = ask(c, key, a.model, msgs)
        msgs.append({"role": "assistant", "content": ans})
        answers.append(ans)
        ok = cached > 0 if i > 0 else True
        fails += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] A turn {i + 1}: prompt={ptok} cached={cached} "
              f"FTL={ftl:.2f}s -> {ans!r}", flush=True)

    ans, ptok, cached, ftl = ask(c, key, a.model, [{"role": "system", "content": SYSTEM},
                                                    {"role": "user", "content": TURNS[0]}])
    ok = cached > 0 and ans == answers[0]
    fails += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] B turn 1 (shared system prompt): prompt={ptok} "
          f"cached={cached} FTL={ftl:.2f}s same-as-A={ans == answers[0]}", flush=True)

    st = c.get("/api/stats").json()
    print("kv_cache:", json.dumps(st.get("kv_cache")), flush=True)
    print("ALL PASS" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
