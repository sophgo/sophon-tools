#!/usr/bin/env python3
"""Screenshots and DOM checks for the per-kind model tabs and test panels.

MYS-2599: the model page is split into one tab per model family, and the
playground has a panel for every kind. This starts the real app on the mock
engine with one model of every kind loaded, then, at desktop and phone width in
both themes:

* model page -- five tabs; each shows only its kind's cards and catalogue rows;
  the loaded badge counts; an empty tab says what to do; no page overflow;
* playground -- each panel runs end to end against /api/test/* and renders its
  figure (similarity matrix, score bars, timeline, OCR boxes), the chat panel
  still answers, a failing request shows its error, long text does not
  overflow, and every similarity cell's number clears 4.5:1 on its own fill.

PaddleOCR-VL (`ocr_vl`) is not served by this tree yet (MYS-2591), so its panel
is driven through intercepted /api/models and /api/test/chat/completions
responses: what is checked is the console's half of the contract -- the OpenAI
vision request it sends and how it renders the stream.

    python3 web/acceptance/kind_panels_shots.py --out ./kind-shots
"""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import struct
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

WIDTHS = {"desktop": (1440, 1000), "phone": (390, 844)}
OCR_IMG = ROOT / "tests" / "data" / "ocr" / "img" / "ui_status.png"
LOAD = ["qwen3.6-35b-a3b-32k", "qwen3-embedding-0.6b", "bge-reranker-v2-m3",
        "qwen3-asr-0.6b", "ppocrv6-medium"]
#: tab -> (cards on disk, catalogue rows, loaded)
TABS = {"chat": (2, 4, 1), "embedding": (1, 1, 1), "rerank": (1, 1, 1),
        "asr": (1, 2, 1), "ocr": (1, 1, 1)}
VL_ID = "paddleocr-vl-1.5"
VL_ANSWER = ("系统状态 System Status\n\n| 项目 | 数值 |\n|---|---|\n"
             "| CPU 使用率 | 23% |\n| 内存占用 | 18.5 / 64 GB |\n| 服务状态 | running |\n")


def wav(seconds: float, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(9000 * math.sin(2 * math.pi * 330 * i / rate)))
            for i in range(int(seconds * rate))))
    return buf.getvalue()


def serve(port: int):
    import uvicorn

    from app.main import create_app
    from mock_server import seed

    root = Path(tempfile.mkdtemp(prefix="cv84x6-kinds-"))
    seed(root)
    app = create_app(data_root=root, backend_kind="mock", web_dir=ROOT / "web" / "dist",
                     context_length_override=32768, service_port=port, decode_delay_ms=4)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server


_RGB = re.compile(r"rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)")
_SRGB = re.compile(r"color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)")


def parse_color(css: str) -> tuple[float, float, float]:
    m = _RGB.search(css)
    if m:
        return tuple(float(x) / 255 for x in m.groups())  # type: ignore[return-value]
    m = _SRGB.search(css)
    if m:
        return tuple(float(x) for x in m.groups())  # type: ignore[return-value]
    raise ValueError(css)


def contrast(a: str, b: str) -> float:
    def lum(c):
        lin = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for c_ in [c] for x in c_]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    la, lb = sorted([lum(parse_color(a)), lum(parse_color(b))], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8804)
    ap.add_argument("--out", default="./kind-shots")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="cv84x6-kind-files-"))
    (tmp / "speech.wav").write_bytes(wav(35.0))
    (tmp / "broken.mp3").write_bytes(b"this is not audio" * 64)

    server = serve(args.port)
    base = f"http://127.0.0.1:{args.port}"
    results: list[tuple[bool, str]] = []

    def check(cond: bool, what: str) -> None:
        results.append((bool(cond), what))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        def open_page(w: int, h: int, theme: str):
            ctx = browser.new_context(viewport={"width": w, "height": h})
            page = ctx.new_page()
            page.on("pageerror", lambda e: check(False, f"pageerror: {e}"))
            # The broken-audio case is a deliberate 415; Chromium logs every
            # failed fetch as a console error, so that one status is expected.
            page.on("console", lambda m: m.type == "error" and "status of 415" not in m.text
                    and check(False, f"console: {m.text}"))
            page.goto(base, wait_until="networkidle")
            page.fill('[data-testid="login-password"]', "admin")
            page.click('[data-testid="login-submit"]')
            page.wait_for_selector('[data-testid="nav"]')
            page.evaluate(
                "t => { localStorage.setItem('cv84x6.theme', t);"
                "document.documentElement.setAttribute('data-theme', t); }", theme)
            return ctx, page

        # Load one model of every kind through the API, as an operator would.
        ctx, page = open_page(1440, 1000, "light")
        for mid in LOAD:
            r = page.request.post(f"{base}/api/models/{mid}/load")
            check(r.ok, f"load {mid}: {r.status}")
        ctx.close()

        def overflow(page) -> int:
            return page.evaluate("document.documentElement.scrollWidth - window.innerWidth")

        for wname, (w, h) in WIDTHS.items():
            for theme in ("light", "dark"):
                tag = f"{wname}/{theme}"
                ctx, page = open_page(w, h, theme)

                # ---- model page ------------------------------------------------
                page.click('[data-testid="nav-models"]')
                page.wait_for_selector('[data-testid="model-tabs"]')
                check(page.locator('[data-testid^="model-tab-"][role="tab"]').count() == 5,
                      f"{tag} models: 5 tabs")
                for tab, (cards, rows, loaded) in TABS.items():
                    page.click(f'[data-testid="model-tab-{tab}"]')
                    page.wait_for_selector('[data-testid="model-grid"]')
                    page.wait_for_timeout(250)
                    n_cards = page.locator('[data-testid^="model-card-"]').count()
                    n_rows = page.locator('[data-testid^="catalog-row-"]').count()
                    badge = page.locator(f'[data-testid="model-tab-loaded-{tab}"]')
                    check(n_cards == cards, f"{tag} models/{tab}: {n_cards} cards (want {cards})")
                    check(n_rows == rows, f"{tag} models/{tab}: {n_rows} catalogue rows (want {rows})")
                    check(badge.count() == 1 and badge.inner_text().strip() == str(loaded),
                          f"{tag} models/{tab}: loaded badge {loaded}")
                    check(page.get_attribute(f'[data-testid="model-tab-{tab}"]', "aria-selected") == "true",
                          f"{tag} models/{tab}: aria-selected")
                    check(overflow(page) <= 0, f"{tag} models/{tab}: no horizontal overflow")
                    page.screenshot(path=str(out / f"models-{tab}-{wname}-{theme}.png"), full_page=True)

                # An empty tab: the list without its embedding model.
                def strip_embedding(route):
                    resp = route.fetch()
                    body = resp.json()
                    body["models"] = [m for m in body["models"] if m["kind"] != "embedding"]
                    route.fulfill(response=resp, json=body)
                page.route("**/api/models", strip_embedding)
                page.click('[data-testid="model-tab-chat"]')
                page.click('[data-testid="nav-overview"]')
                page.click('[data-testid="nav-models"]')
                page.click('[data-testid="model-tab-embedding"]')
                page.wait_for_selector('[data-testid="model-empty"]')
                check("还没有Embedding模型" in page.inner_text('[data-testid="model-empty"]'),
                      f"{tag} models/embedding: empty state names the kind")
                page.screenshot(path=str(out / f"models-empty-{wname}-{theme}.png"), full_page=True)
                page.unroute("**/api/models")
                page.click('[data-testid="model-tab-chat"]')

                # ---- playground ------------------------------------------------
                page.click('[data-testid="nav-playground"]')
                sel = '[data-testid="chat-model"]'
                page.wait_for_selector(sel)
                groups = page.eval_on_selector_all(f"{sel} optgroup", "gs => gs.map(g => g.label)")
                check(groups == ["大语言模型", "Embedding", "Reranker", "语音识别", "OCR"],
                      f"{tag} playground: picker groups {groups}")

                # chat: unchanged behaviour
                page.select_option(sel, "qwen3.6-35b-a3b-32k")
                page.wait_for_selector('[data-testid="panel-chat"] [data-testid="chat-input"]')
                page.fill('[data-testid="chat-input"]', "你好")
                page.click('[data-testid="chat-send"]')
                page.wait_for_selector('[data-testid="chat-send"]', timeout=20000)
                ans = page.locator('[data-testid="chat-msg-assistant"]').last.inner_text()
                check(len(ans.strip()) > 0, f"{tag} chat: answered")

                # embedding, with one long text
                page.select_option(sel, "qwen3-embedding-0.6b")
                page.wait_for_selector('[data-testid="embed-run"]')
                page.fill('[data-testid="embed-texts-3"]', "很长的一段文本，" * 120)
                page.click('[data-testid="embed-run"]')
                page.wait_for_selector('[data-testid="embed-matrix"]', timeout=20000)
                check(page.locator('[data-testid^="embed-cell-"]').count() == 16,
                      f"{tag} embedding: 4x4 matrix")
                check(page.locator('[data-testid="embed-best"]').count() == 1,
                      f"{tag} embedding: closest-pair headline")
                page.hover('[data-testid="embed-cell-0-1"]')
                check("T1 × T2" in page.inner_text('[data-testid="embed-tip"]'),
                      f"{tag} embedding: hover names the pair")
                worst = page.evaluate("""() => [...document.querySelectorAll('.simx-cell:not(.self)')]
                    .map(c => { const s = getComputedStyle(c); return [s.color, s.backgroundColor] })""")
                ratios = [contrast(fg, bg) for fg, bg in worst]
                check(min(ratios) >= 4.5, f"{tag} embedding: cell contrast min {min(ratios):.2f}")
                check(overflow(page) <= 0, f"{tag} embedding: no overflow with long text")
                page.screenshot(path=str(out / f"play-embedding-{wname}-{theme}.png"), full_page=True)

                # rerank, with one long document
                page.select_option(sel, "bge-reranker-v2-m3")
                page.wait_for_selector('[data-testid="rerank-run"]')
                page.fill('[data-testid="rerank-docs-2"]', "一段特别长的候选文档。" * 60)
                page.click('[data-testid="rerank-run"]')
                page.wait_for_selector('[data-testid="rerank-results"]', timeout=20000)
                vals = [float(x) for x in page.locator(".score-val").all_inner_texts()]
                check(len(vals) == 4 and vals == sorted(vals, reverse=True),
                      f"{tag} rerank: 4 rows, descending {vals}")
                check(overflow(page) <= 0, f"{tag} rerank: no overflow with long doc")
                page.screenshot(path=str(out / f"play-rerank-{wname}-{theme}.png"), full_page=True)

                # ASR: an error first, then a 35 s file (two segments)
                page.select_option(sel, "qwen3-asr-0.6b")
                page.wait_for_selector('[data-testid="asr-run"]')
                page.set_input_files('[data-testid="asr-file-input"]', str(tmp / "broken.mp3"))
                page.click('[data-testid="asr-run"]')
                page.wait_for_selector('[data-testid="panel-error"]', timeout=20000)
                check(len(page.inner_text('[data-testid="panel-error"]').strip()) > 0,
                      f"{tag} asr: undecodable audio shows the error")
                page.screenshot(path=str(out / f"play-asr-error-{wname}-{theme}.png"), full_page=True)
                page.set_input_files('[data-testid="asr-file-input"]', str(tmp / "speech.wav"))
                page.click('[data-testid="asr-run"]')
                page.wait_for_selector('[data-testid="asr-timeline"]', timeout=30000)
                segs = page.locator('[data-testid="asr-segments"] li').count()
                blocks = page.locator(".timeline-seg").count()
                check(segs >= 2 and segs == blocks, f"{tag} asr: {segs} segments, {blocks} blocks")
                check(page.locator('[data-testid="panel-error"]').count() == 0,
                      f"{tag} asr: error cleared on success")
                page.screenshot(path=str(out / f"play-asr-{wname}-{theme}.png"), full_page=True)

                # OCR
                page.select_option(sel, "ppocrv6-medium")
                page.wait_for_selector('[data-testid="ocr-run"]')
                page.set_input_files('[data-testid="ocr-file-input"]', str(OCR_IMG))
                page.click('[data-testid="ocr-run"]')
                page.wait_for_selector('[data-testid="ocr-lines"]', timeout=20000)
                page.wait_for_selector('[data-testid="ocr-boxes"]')
                n_lines = page.locator('[data-testid="ocr-lines"] li').count()
                n_boxes = page.locator('[data-testid="ocr-boxes"] polygon').count()
                check(n_lines > 0 and n_lines == n_boxes, f"{tag} ocr: {n_lines} lines, {n_boxes} boxes")
                page.hover('[data-testid="ocr-lines"] li >> nth=0')
                check(page.locator(".ocr-box.on").count() == 1, f"{tag} ocr: hover highlights its box")
                check(overflow(page) <= 0, f"{tag} ocr: no overflow")
                page.screenshot(path=str(out / f"play-ocr-{wname}-{theme}.png"), full_page=True)

                # OCR-VL, through intercepted responses (see the module docstring)
                sent: list[dict] = []

                def with_vl(route):
                    resp = route.fetch()
                    body = resp.json()
                    chat = next(m for m in body["models"] if m["id"] == "qwen3.6-35b-a3b-32k")
                    body["models"].append(dict(chat, id=VL_ID, display_name=VL_ID, kind="ocr_vl",
                                               supports_vision=True, context_length=2048))
                    route.fulfill(response=resp, json=body)

                def vl_stream(route):
                    sent.append(json.loads(route.request.post_data or "{}"))
                    frames = [{"choices": [{"delta": {"content": VL_ANSWER[i:i + 12]}}]}
                              for i in range(0, len(VL_ANSWER), 12)]
                    frames.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
                    frames.append({"choices": [], "usage": {"prompt_tokens": 2471, "completion_tokens": 58}})
                    body = "".join(f"data: {json.dumps(f, ensure_ascii=False)}\n\n" for f in frames)
                    route.fulfill(status=200, body=body + "data: [DONE]\n\n",
                                  headers={"content-type": "text/event-stream"})

                page.route("**/api/models", with_vl)
                page.route("**/api/test/chat/completions", vl_stream)
                page.click('[data-testid="nav-overview"]')
                page.click('[data-testid="nav-playground"]')
                page.wait_for_selector(sel)
                page.select_option(sel, VL_ID)
                page.wait_for_selector('[data-testid="vl-run"]')
                page.select_option('[data-testid="vl-task"]', "Table Recognition:")
                page.set_input_files('[data-testid="vl-file-input"]', str(OCR_IMG))
                page.click('[data-testid="vl-run"]')
                page.wait_for_selector('[data-testid="vl-text"] table', timeout=10000)
                content = sent[0]["messages"][0]["content"] if sent else []
                check(bool(sent) and sent[0].get("stream") is True
                      and content[0]["type"] == "image_url"
                      and content[0]["image_url"]["url"].startswith("data:image/png;base64,")
                      and content[1] == {"type": "text", "text": "Table Recognition:"},
                      f"{tag} ocr_vl: OpenAI vision request shape")
                check("58 输出" in page.inner_text('[data-testid="vl-meta"]'), f"{tag} ocr_vl: usage shown")
                page.screenshot(path=str(out / f"play-ocrvl-{wname}-{theme}.png"), full_page=True)
                page.unroute("**/api/models")
                page.unroute("**/api/test/chat/completions")
                ctx.close()

        browser.close()
    server.should_exit = True

    failed = [w for ok, w in results if not ok]
    for ok, what in results:
        print("PASS" if ok else "FAIL", what)
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    (out / "results.json").write_text(json.dumps(
        {"passed": len(results) - len(failed), "total": len(results),
         "results": [{"ok": ok, "check": w} for ok, w in results]}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
