#!/usr/bin/env python3
"""End-to-end smoke test for the knowledge-base app, standard library only.

    python3 tools/kb_smoke.py --base http://127.0.0.1:8000 --password admin

It walks the whole pipeline the way the console will: create a library, upload
four kinds of file (a txt, a text PDF, a scanned PDF, an image), wait for the
queue to drain, run a hybrid search, and stream an answer. Everything it needs
it builds itself -- a multipart body by hand, a tiny PNG by hand -- so it runs on
the board, where there is no ``requests``, no Pillow and no ``curl --form``
helper worth depending on.

The PDFs come from ``tests/data/kb/`` (checked in; see
``tools/kb/make_pdf_fixtures.py``). Pass ``--pdf-dir`` to point it elsewhere.

Exit code is 0 only when every phase succeeded. Each phase prints what the API
returned, including every stage's status and timing, so the output is the
record of the run -- not a summary of it.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF_DIR = ROOT / "tests" / "data" / "kb"

#: A 320x200 PNG built here so the script needs no image library: a white page
#: with dark bars standing in for lines of text, so a real PP-OCR has edges to
#: find. Generated once with Pillow and pasted in as hex (583 bytes).
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000140000000c808020000001666affc00"
    "00020e4944415478daedddb111c4200c4541e3711ff45f1695e0905c0458d66e7e89"
    "67de88e85f9b735e404eb74f000206040c0818040c0818103020601030206040c020"
    "6040c080800101c3df3d3b3feebdfb82b06f8ce102832734206040c0808041c08080"
    "0101030206010367347fad022e30206040c0206040c08080010183800101030286ba"
    "ac52c2125e877481010183800101030206040c0206040c0818040c646595125c6040"
    "c0808041c08080010103020601030206040c8559a5e48bd2ad43bac0808041c08080"
    "010103020601030206040c0206b2b24a092e30206040c0206040c080800101838001"
    "01030286c2ac52c279e1154e17183ca1010103020601030206040c0818040c0818d8"
    "6595125c6040c0808041c08080010103020601030206040c8559a58425bc0ee90203"
    "020601030206040c0818040c081810300818c8ca2a25b8c080800101838001010302"
    "06040c0206040c08180ab34ac917a55b877481010183800101030206040c0206040c"
    "0818040c646595125c6040c0808041c08080010103020601030206040c8559a584f3"
    "c22b9c2e307842030206040c0206040c0818103008181030b0cb2a25b8c080800101"
    "83800101030206040c0206040c08180ab34a094b781dd20506040c0206040c081810"
    "3008181030206010309095554a7081010103020601030206040c0818040c08181030"
    "08181030206040c0206040c080800101c34fbc1936347d2f44ea550000000049454e"
    "44ae426082"
)


class Api:
    """A minimal client: cookie session, multipart, and SSE line reading."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, method: str, path: str, body: bytes | None = None,
                content_type: str | None = None, timeout: float = 120.0):
        request = urllib.request.Request(self.base + path, data=body, method=method)
        if content_type:
            request.add_header("Content-Type", content_type)
        try:
            return self.opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise SystemExit(f"FAIL {method} {path} -> {exc.code}\n{detail}") from None

    def json(self, method: str, path: str, payload=None, timeout: float = 300.0):
        body = None
        content_type = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            content_type = "application/json"
        with self.request(method, path, body, content_type, timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def multipart(files: list[tuple[str, bytes]]) -> tuple[bytes, str]:
    """A ``multipart/form-data`` body with one ``file`` part per entry."""
    boundary = f"----kbsmoke{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, data in files:
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'.encode())
        guessed = mimetypes.guess_type(name)[0] or "application/octet-stream"
        chunks.append(f"Content-Type: {guessed}\r\n\r\n".encode())
        chunks.append(data)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def wait_docs(api: Api, kb: str, timeout: float) -> list[dict]:
    """Poll until no document is queued or in flight."""
    deadline = time.monotonic() + timeout
    docs: list[dict] = []
    while time.monotonic() < deadline:
        docs = api.json("GET", f"/api/apps/kb/{kb}/docs")["docs"]
        busy = [d for d in docs
                if d["status"] in ("queued", "parsing", "ocr", "embedding")]
        if docs and not busy:
            return docs
        time.sleep(0.5)
    raise SystemExit(f"FAIL documents did not settle in {timeout}s: "
                     f"{[(d['name'], d['status']) for d in docs]}")


def stream_answer(api: Api, kb: str, query: str, chunk_ids: list[str],
                  max_tokens: int) -> dict:
    """POST /answer and read the SSE stream, returning what it produced."""
    body = json.dumps({"query": query, "chunk_ids": chunk_ids,
                       "max_tokens": max_tokens}, ensure_ascii=False).encode()
    text: list[str] = []
    frames = 0
    citations: list[dict] = []
    done = False
    with api.request("POST", f"/api/apps/kb/{kb}/answer", body,
                     "application/json") as response:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                done = True
                break
            frames += 1
            event = json.loads(payload)
            if event.get("type") == "citations":
                citations = event.get("items") or []
                continue
            for choice in event.get("choices") or []:
                piece = (choice.get("delta") or {}).get("content")
                if piece:
                    text.append(piece)
    return {"text": "".join(text), "frames": frames,
            "citations": citations, "done": done}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--password", default=os.environ.get("KB_SMOKE_PASSWORD", "admin"))
    parser.add_argument("--pdf-dir", default=str(DEFAULT_PDF_DIR))
    parser.add_argument("--query", default="盘点差异怎么处理")
    parser.add_argument("--keep", action="store_true",
                        help="leave the library behind instead of deleting it")
    parser.add_argument("--timeout", type=float, default=900.0,
                        help="how long to wait for the ingestion queue")
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--files", nargs="+", default=None,
                        help="use these files instead of the bundled fixtures "
                             "(the acceptance run on the board uses a real "
                             "document set). A .txt is still added so the "
                             "text-only path is always covered.")
    args = parser.parse_args()

    if args.files:
        chosen = [Path(p) for p in args.files]
        for path in chosen:
            if not path.is_file():
                return fail(f"no such file: {path}")
        documents = [(p.name, p.read_bytes()) for p in chosen]
    else:
        pdf_dir = Path(args.pdf_dir)
        for name in ("text.pdf", "scan.pdf"):
            if not (pdf_dir / name).is_file():
                return fail(f"missing fixture {pdf_dir / name}; "
                            "run tools/kb/make_pdf_fixtures.py on a host with "
                            "LibreOffice")
        documents = [
            ("文字版制度.pdf", (pdf_dir / "text.pdf").read_bytes()),
            ("扫描件.pdf", (pdf_dir / "scan.pdf").read_bytes()),
            ("截图.png", TINY_PNG),
        ]

    api = Api(args.base)
    phase("登录")
    api.json("POST", "/api/login", {"password": args.password})
    models = api.json("GET", "/api/models")["models"]
    ready = [m["id"] for m in models if m["loaded"] and m["operation"] is None]
    print(f"  已加载模型：{ready or '（无）'}")
    for kind in ("embedding", "rerank", "ocr", "chat"):
        have = [m["id"] for m in models if m["kind"] == kind and m["id"] in ready]
        print(f"  {kind:<10} {'✓ ' + have[0] if have else '× 未加载'}")

    phase("建库")
    library = api.json("POST", "/api/apps/kb",
                       {"name": f"冒烟测试 {time.strftime('%H:%M:%S')}"})["kb"]
    kb = library["id"]
    print(f"  kb_id = {kb}")

    phase("上传文件")
    # A txt is always included: it is the one input that needs neither a PDF
    # parser nor OCR, so a failure there means something more basic is wrong.
    text = ("仓库盘点由仓管员在每个季度末执行。盘点前必须冻结出入库操作，"
            "并打印盘点单分配到具体货位。盘点差异率超过千分之五时须由财务复核。").encode("utf-8")
    files = [("制度说明.txt", text)] + documents
    body, content_type = multipart(files)
    for name, data in files:
        print(f"  {name:<16} {len(data):>8} bytes")
    queued = api.request("POST", f"/api/apps/kb/{kb}/docs", body, content_type)
    with queued as response:
        created = json.loads(response.read().decode())["docs"]
    print(f"  入队 {len(created)} 个文档")

    phase("等待建库")
    started = time.monotonic()
    docs = wait_docs(api, kb, args.timeout)
    elapsed = time.monotonic() - started
    total_pages = sum(d["pages"] for d in docs)
    total_chunks = sum(d["chunks"] for d in docs)
    for doc in docs:
        print(f"  {doc['name']:<16} {doc['status']:<9} "
              f"页 {doc['pages']:>2}（文字 {doc['text_pages']} / OCR {doc['ocr_pages']:>2}） "
              f"切片 {doc['chunks']:>3}"
              + (f"  error={doc['error']}" if doc["error"] else ""))
        for warning in doc["warnings"]:
            print(f"      ! {warning}")
    print(f"  用时 {elapsed:.1f}s  {total_pages} 页  {total_chunks} 切片"
          + (f"  ({total_pages / elapsed * 60:.0f} 页/分钟, "
             f"{total_chunks / elapsed:.1f} 切片/秒)" if elapsed > 0 else ""))
    failed = [d for d in docs if d["status"] != "ready"]
    if failed:
        print(f"  警告：{len(failed)} 个文档未就绪")

    phase("混合检索")
    search = api.json("POST", f"/api/apps/kb/{kb}/search",
                      {"query": args.query, "top_k": 5, "candidates": 20})
    print(f"  query = {search['query']!r}")
    print(f"  models = {search['models']}")
    for name in ("bm25", "vector", "fusion", "rerank"):
        stage = search["stages"][name]
        note = f"  reason={stage['reason']}" if stage["reason"] else ""
        print(f"  {name:<7} {stage['status']:<8} {stage['ms']:>8.1f} ms  "
              f"{len(stage['hits'])} 条{note}")
    print(f"  total   {search['timings']['total_ms']:.1f} ms")
    for item in search["results"]:
        preview = (item["text"] or "").replace("\n", " ")[:60]
        print(f"  #{item['rank']} {item['doc_name']} 第{item['page']}页 "
              f"[{item['scores']}] {preview}…")
    if not search["results"]:
        return fail("检索没有返回任何结果")

    phase("生成回答")
    if not [m for m in models if m["kind"] == "chat" and m["id"] in ready]:
        # Not a failure: the design says the answer stage degrades to "检索结果
        # only" when no chat model is loaded, and the board cannot hold the 35B
        # and the auxiliary models at once. Say so instead of exiting non-zero.
        print("  跳过：未加载对话模型（/answer 会返回 409，这是设计的降级行为）")
    else:
        chunk_ids = [item["chunk_id"] for item in search["results"][:3]]
        answer = stream_answer(api, kb, args.query, chunk_ids, args.max_tokens)
        print(f"  citations = {answer['citations']}")
        print(f"  帧数 = {answer['frames']}  [DONE] = {answer['done']}")
        print(f"  回答：{answer['text'][:400]}")
        if not answer["done"]:
            return fail("SSE 流没有以 [DONE] 结束")

    if not args.keep:
        phase("清理")
        api.json("DELETE", f"/api/apps/kb/{kb}")
        print(f"  已删除知识库 {kb}")

    phase("结果")
    print("  PASS")
    return 0


def phase(title: str) -> None:
    print(f"\n== {title} ==")


def fail(message: str) -> int:
    print(f"\nFAIL: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
