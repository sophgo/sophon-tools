#!/usr/bin/env python3
"""Search a seq2048-built library over HTTP while only the seq512 build is loaded.

This is the acceptance criterion as an operator would experience it -- not the
`kb_recheck.py` model-level comparison (which embeds the query twice in one
process), but the service's own `/api/apps/kb/<id>/search`, with only one build
resident. If the family rule is wrong, the vector stage says `skipped` here.

The library is a copy of the installed service's 284-chunk demo library, whose
`kb.json` records `qwen3-embedding-0.6b` -- the seq2048/seq8192 id, definitely
not the seq512 one.
"""

from __future__ import annotations

import http.cookiejar
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8031"
KB = "04fe72f7b7e54a1a8689b97c2f012cd0"
QUERIES = [
    "这段文档讲了什么？",
    "向量检索的候选数量怎么定？",
    "如何避免切片切断句子？",
    "what does the document say about chunk overlap?",
    "设备内存上限是怎么算出来的？",
    "今天的天气怎么样？",
]


def main() -> int:
    op = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    op.open(urllib.request.Request(
        BASE + "/api/login", data=json.dumps({"password": "admin"}).encode(),
        headers={"Content-Type": "application/json"})).read()
    loaded = [m["id"] for m in json.load(op.open(BASE + "/api/models"))["models"]
              if m["loaded"]]
    print("== loaded:", loaded)

    bad = 0
    for query in QUERIES:
        req = urllib.request.Request(
            f"{BASE}/api/apps/kb/{KB}/search",
            data=json.dumps({"query": query}).encode(),
            headers={"Content-Type": "application/json"})
        body = json.load(op.open(req, timeout=300))
        stage = body["stages"]["vector"]
        served = body["models"]["embedding"]
        top = [r["chunk_id"][:8] for r in body["results"][:3]]
        ok = stage["status"] == "ok"
        bad += 0 if ok else 1
        mark = "OK  " if ok else "FAIL"
        print(f"  {mark} vector={stage['status']:8s} served_by={served:30s} "
              f"top3={top}  {query[:24]}")
        if not ok:
            print(f"       reason: {stage['reason']}")
    print(f"== {len(QUERIES) - bad}/{len(QUERIES)} queries ran the vector stage")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
