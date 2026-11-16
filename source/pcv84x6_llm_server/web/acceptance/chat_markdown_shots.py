#!/usr/bin/env python3
"""Screenshots and DOM checks for Markdown / emoji rendering on the chat page.

Runs against web/acceptance/mock_server.py. The model's answer is not left to
the mock engine: /api/chat/stream is intercepted and replayed with fixed
answers, so the screenshots always show the same headings, lists, code, table,
emoji and think block.

    python3 web/acceptance/mock_server.py --port 8802 --decode-delay-ms 0
    python3 web/acceptance/chat_markdown_shots.py --base http://127.0.0.1:8802 --out ./md-shots
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

WIDTHS = {"desktop": (1440, 1000), "phone": (390, 844)}

# The reply in the field screenshot that started this (MYS-2496), now with the
# emoji intact, followed by the remaining block types.
ANSWER_LIST = (
    "前面的几个字符是：**🤖💬**\n\n"
    "如果您是想让我继续帮您写具体的公文，请告诉我：\n"
    "1. **公文类型**（如：通知、请示、函、纪要等）\n"
    "2. **发文单位**\n"
    "3. **主送单位**\n"
    "4. **具体事由**（例如：关于春节放假的通知）\n\n"
    "我会为您生成一份格式规范、语言得体的公文。😊👍"
)
ANSWER_RICH = (
    "<think>\n用户要一个对比表和示例代码，先列要点再给表格。\n</think>\n\n"
    "## 两种部署方式对比 🚀\n\n"
    "| 方式 | 内存 | 首字延迟 |\n|---|---:|---:|\n"
    "| 单会话 | 2.5 GiB | 0.8 s |\n| 多会话 | 3.1 GiB | 1.2 s |\n\n"
    "> 注意：多会话会共享前缀缓存。\n\n"
    "- 行内代码：`max_tokens=512`\n- 链接：[项目主页](https://github.com/)\n"
    "  - 嵌套项 ✅\n\n"
    "```python\ndef hello(name: str) -> str:\n    return f\"你好，{name} 👋\"\n```\n\n"
    "<img src=x onerror=alert(1)> 原始 HTML 不会执行。"
)


def sse(text: str) -> str:
    # Split into small deltas, the way the real stream arrives.
    out = [f"data: {json.dumps({'text': text[i:i + 7]}, ensure_ascii=False)}\n\n"
           for i in range(0, len(text), 7)]
    out.append("data: " + json.dumps({
        "done": True, "prompt_tokens": 937, "completion_tokens": 115,
        "cached_tokens": 320, "decode_tps": 29.1, "first_token_latency_s": 4.19,
    }) + "\n\n")
    out.append("data: [DONE]\n\n")
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8802")
    ap.add_argument("--out", default="./md-shots")
    ap.add_argument("--password", default="admin")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    answers = [ANSWER_LIST, ANSWER_RICH]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for wname, (w, h) in WIDTHS.items():
            for theme in ("light", "dark"):
                ctx = browser.new_context(viewport={"width": w, "height": h})
                page = ctx.new_page()
                page.on("pageerror", lambda e: errors.append(f"pageerror:{e}"))
                page.on("dialog", lambda d: (errors.append(f"dialog fired: {d.message}"), d.dismiss()))
                served = iter(answers * 2)
                page.route("**/api/chat/stream", lambda r: r.fulfill(
                    status=200, content_type="text/event-stream", body=sse(next(served))))
                page.goto(args.base, wait_until="networkidle")
                page.fill('[data-testid="login-password"]', args.password)
                page.click('[data-testid="login-submit"]')
                page.wait_for_selector('[data-testid="nav"]')
                page.evaluate("""async () => {
                    const j = await (await fetch('/api/models')).json()
                    for (const m of j.models) if (!m.loaded)
                        await fetch(`/api/models/${encodeURIComponent(m.id)}/load`, {method: 'POST'})
                }""")
                page.evaluate(
                    "t => { localStorage.setItem('cv84x6.theme', t);"
                    "document.documentElement.setAttribute('data-theme', t); }", theme)
                page.wait_for_timeout(1500)
                page.click('[data-testid="nav-playground"]')
                page.wait_for_selector('[data-testid="chat-input"]', timeout=15000)
                for q in ("前面的几个字符是什么？", "给我一个对比表和示例代码"):
                    page.fill('[data-testid="chat-input"]', q)
                    page.click('[data-testid="chat-send"]')
                    page.wait_for_selector('[data-testid="chat-send"]', timeout=15000)
                    page.wait_for_timeout(300)

                dom = page.evaluate("""() => {
                    const bodies = [...document.querySelectorAll('[data-testid="chat-msg-assistant"] .md-body')]
                    const b = bodies[1]
                    return {
                      n: bodies.length,
                      strong: bodies[0]?.querySelector('strong')?.textContent,
                      ol: bodies[0]?.querySelectorAll('ol > li').length,
                      table: !!b?.querySelector('table'), h2: !!b?.querySelector('h2'),
                      pre: !!b?.querySelector('pre code'), think: !!b?.querySelector('details.think'),
                      thinkOpen: b?.querySelector('details.think')?.open,
                      img: document.querySelectorAll('.chat-log .md img').length,
                      link: b?.querySelector('a')?.getAttribute('target'),
                      stars: bodies[0]?.textContent.includes('**'),
                    }
                }""")
                want = {"n": 2, "strong": "🤖💬", "ol": 4, "table": True, "h2": True, "pre": True,
                        "think": True, "thinkOpen": False, "img": 0, "link": "_blank", "stars": False}
                for k, v in want.items():
                    if dom.get(k) != v:
                        errors.append(f"{wname}/{theme}: {k}={dom.get(k)!r}, want {v!r}")

                log = page.locator('[data-testid="chat-log"]')
                log.evaluate("e => e.style.maxHeight = 'none'")
                log.screenshot(path=str(out / f"chat-md-{wname}-{theme}.png"))
                page.locator('[data-testid="chat-raw-toggle"]').first.click()
                raw = page.locator('[data-testid="chat-raw"]').first.text_content() or ""
                if "**公文类型**" not in raw:
                    errors.append(f"{wname}/{theme}: raw view lost the source text")
                log.screenshot(path=str(out / f"chat-raw-{wname}-{theme}.png"))
                m = page.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
                if m[0] > m[1] + 1:
                    errors.append(f"{wname}/{theme}: horizontal overflow {m}")
                ctx.close()
        browser.close()

    print(f"screenshots in {out}")
    if errors:
        print("ISSUES:")
        for e in errors:
            print("  " + e)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
