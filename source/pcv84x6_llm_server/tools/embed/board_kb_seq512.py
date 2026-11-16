#!/usr/bin/env python3
"""Build a knowledge base on the seq512 build and measure what it costs.

Two figures, and the second is the one that decides whether the short档 suits a
corpus:

* **end-to-end build time** measured through ``/api/apps/kb`` -- queue, parser,
  chunker, HTTP round trips and every forward included, i.e. what an operator
  waits for;
* **how many chunks the 512-token limit actually splits**, computed with the
  model's own tokenizer over the chunk set the service wrote. A chunk over the
  limit costs several forwards (halved, pooled), so this ratio is what turns the
  per-text win into a per-library number -- and it is not predictable from
  character counts: repeated CJK merges in the tokenizer, so 1000 characters of
  ordinary Chinese can be 501 tokens while a rarer script is 3000.

Run with the side instance up (``board_seq512_side.sh``) and the seq512 build
loaded or loadable.
"""

from __future__ import annotations

import http.cookiejar
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8031"

#: One opener for the whole run, with a cookie jar. The console session is a
#: cookie, and ``urllib.request.urlopen`` keeps no state between calls -- the
#: failure mode is a bare 401 on the second request, which looks like auth being
#: broken rather than like a missing jar.
_OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

LIB = "/opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so"
CONFIG = "/opt/sophgo/cv84x6_llm_server/model-config/qwen3_embedding"

#: A corpus of ordinary Chinese prose, one paragraph per chunk after the
#: chunker's ~400-character target, **plus** a run of long unpunctuated CJK at
#: the chunker's 1000-character ceiling. Both halves are needed: the first is
#: what a real library sees (and it fits the 512-token limit comfortably), the
#: second is the case the limit actually splits. Reporting only the first would
#: make the split ratio look like 0% and hide the cost; reporting only the
#: second would overstate it.
PARA = (
    "库房管理制度第{n}条：物料入库应当核对品名、规格、数量与送货单是否一致，"
    "发现短缺或破损应当在当日填写异常单并通知采购与质检。上架时按库位号顺序摆放，"
    "标识朝外，同类物料不得混放，通道宽度不得小于一米二。"
    "出库遵循先进先出原则，单据保留备查；每月末盘点一次，盘点结果由两人签字确认后归档。"
)

#: No punctuation at all, so the chunker's 1000-character hard ceiling is what
#: cuts it -- the exact shape that goes over 512 tokens in ordinary CJK.
LONG_CJK = ("盘点差异处理流程要求当日核对当日上报并在三个工作日内完成复核和归档" * 40)


def post(path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with _OPENER.open(req, timeout=60) as r:
        return json.loads(r.read())


def get(path: str):
    with _OPENER.open(BASE + path, timeout=60) as r:
        return json.loads(r.read())


def upload(kb: str, name: str, payload: bytes) -> None:
    boundary = "----mys2706"
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
    body = head + payload + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{BASE}/api/apps/kb/{kb}/docs", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with _OPENER.open(req, timeout=120) as r:
        r.read()


def chunker_chunks(kb: str) -> list[dict]:
    """The chunk set the service wrote for ``kb``."""
    root = Path("/data/mys2706/side/data/apps/kb") / kb / "chunks.jsonl"
    return [json.loads(line) for line in
            root.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: list[str]) -> int:
    docs = int(argv[1]) if len(argv) > 1 else 4
    model = argv[2] if len(argv) > 2 else "qwen3-embedding-0.6b-seq512"

    # ~410 characters of prose per paragraph (one chunk each) plus one long
    # unpunctuated block per document, so the corpus has both shapes.
    prose = "\n".join(PARA.format(n=i) for i in range(60 * docs))
    payload = (prose + "\n" + ("\n".join([LONG_CJK] * docs))).encode()

    post("/api/login", {"password": "admin"})
    kb = post("/api/apps/kb", {"name": "seq512 计时"})["kb"]["id"]
    t0 = time.monotonic()
    upload(kb, "policies.txt", payload)

    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        docs_now = get(f"/api/apps/kb/{kb}/docs")["docs"]
        if docs_now and all(d["status"] not in ("queued", "parsing", "ocr", "embedding")
                            for d in docs_now):
            break
        time.sleep(0.5)
    elapsed = time.monotonic() - t0
    ready = [d for d in docs_now if d["status"] == "ready"]
    print(f"== built {len(ready)}/{len(docs_now)} document(s) in {elapsed:.1f} s "
          f"with {model}")
    for d in docs_now:
        print(f"   {d['name']}: {d['status']}, {d['chunks']} chunk(s), "
              f"error={d['error']}")
    if not ready:
        return 1

    chunks = chunker_chunks(kb)
    print(f"== {len(chunks)} chunks written")

    # -- how many of them the 512-token limit splits -----------------------
    #
    # Two figures, and they mean different things:
    #   * "over 512" is a property of the *corpus* -- chunks a seq512 build
    #     cannot do in one forward, whatever model built this library;
    #   * "split in this build" is what the ingest path actually did, which is
    #     zero when the build under test is seq2048. Computing only the first
    #     would report a seq2048 baseline as if it had split 7 chunks.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cmp_models import Lib  # noqa: E402

    # Only the *tokenizer* is opened, never a model: the service already holds
    # one on the NPU, and creating a second copy would both perturb the heap and
    # race the load. Token counting needs nothing but ``tokenizer.json``.
    lib = Lib(LIB)
    tok = lib.open_tokenizer(str(Path(CONFIG) / "tokenizer.json"))
    #: The SEQLEN the build under test enforces, read from its own id the same
    #: way the service reads it from the bmodel name.
    seq = int(model.rsplit("seq", 1)[1]) if "seq" in model else 2048
    lengths = [len(lib.encode(tok, c["text"])) for c in chunks]
    over_512 = [n for n in lengths if n > 512]
    over_this = [n for n in lengths if n > seq]
    print(f"== token lengths: median {statistics.median(lengths):.0f}, "
          f"max {max(lengths)}")
    print(f"== over 512: {len(over_512)}/{len(chunks)} "
          f"({100.0 * len(over_512) / len(chunks):.1f}%) -- corpus property")
    print(f"== split in this build (limit {seq}): {len(over_this)}/{len(chunks)} "
          f"({100.0 * len(over_this) / len(chunks):.1f}%) -- {model}")
    for c, n in zip(chunks, lengths):
        if n > 512:
            print(f"   {n:4d} tok, {len(c['text']):4d} chars -- "
                  f"{c['text'][:32]!r}…")
    # The library must read back as built by the model that built it.
    listing = next(k for k in get("/api/apps/kb")["kbs"] if k["id"] == kb)
    print(f"== kb records embedding_model={listing['embedding_model']!r} "
          f"dims={listing['dims']} chunks={listing['chunks']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
