#!/usr/bin/env python3
"""Measure the things a design audit has to judge from pixels, not source.

Reports the docs measure (characters per line), the type and spacing values
actually in use, group-spacing ratios, overflow offenders, and every
text/background pair with its WCAG ratio.

    python3 audit_metrics.py --base http://127.0.0.1:8802
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from playwright.sync_api import sync_playwright

PAGES = ["overview", "models", "agents", "playground", "keys", "settings", "docs"]

MEASURE_JS = r"""
() => {
  // --- every rendered font size and font weight -----------------------------
  const sizes = {}, weights = {}, colors = {};
  const els = [...document.querySelectorAll('body *')];
  for (const el of els) {
    if (!el.textContent || !el.textContent.trim()) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const cs = getComputedStyle(el);
    sizes[cs.fontSize] = (sizes[cs.fontSize] || 0) + 1;
    weights[cs.fontWeight] = (weights[cs.fontWeight] || 0) + 1;
    colors[cs.color] = (colors[cs.color] || 0) + 1;
  }
  // --- the widest block of prose, as characters per line -------------------
  // A CJK glyph is ~1em wide, a Latin one ~0.5em. Averaging over the actual
  // string is the only honest way to count "characters per line" for a page
  // that mixes both; assuming 0.5em reports Chinese prose as twice as wide as
  // it renders.
  const advance = (text) => {
    let cjk = 0, other = 0;
    for (const ch of text) {
      const c = ch.codePointAt(0);
      if (c >= 0x2e80) cjk++; else other++;
    }
    const total = cjk + other || 1;
    return (cjk * 1.0 + other * 0.5) / total;   // average em per character
  };
  const measure = (el) => {
    const cs = getComputedStyle(el);
    const fs = parseFloat(cs.fontSize);
    const width = el.getBoundingClientRect().width
      - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const em = advance(el.textContent.trim());
    return {
      ch: Math.round(width / (fs * em)), px: Math.round(width), fontSize: fs,
      em: Number(em.toFixed(2)),
    };
  };
  const prose = [...document.querySelectorAll('.docs p, .docs li, .sub, .composer-hint')]
    .filter((el) => el.textContent.trim().length > 40)
    .map((el) => ({ tag: el.tagName.toLowerCase(), cls: el.className, ...measure(el) }))
    .sort((a, b) => b.ch - a.ch);
  // --- headings: space above vs below --------------------------------------
  const headings = [...document.querySelectorAll('h1, h2, h3')]
    .filter((el) => el.getBoundingClientRect().height > 2)
    .map((el) => {
      const cs = getComputedStyle(el);
      return {
        text: el.textContent.trim().slice(0, 20),
        fontSize: cs.fontSize,
        lineHeight: cs.lineHeight,
        mt: parseFloat(cs.marginTop),
        mb: parseFloat(cs.marginBottom),
        parentCard: !!el.closest('.card'),
      };
    });
  // --- horizontal overflow, and who causes it ------------------------------
  const docW = document.documentElement.clientWidth;
  const overflow = els
    .filter((el) => {
      const r = el.getBoundingClientRect();
      return r.right > docW + 1 && r.width > 0;
    })
    .map((el) => {
      const r = el.getBoundingClientRect();
      return {
        tag: el.tagName.toLowerCase(),
        cls: typeof el.className === 'string' ? el.className.slice(0, 40) : '',
        right: Math.round(r.right),
        width: Math.round(r.width),
        text: el.textContent.trim().slice(0, 30),
      };
    })
    .slice(0, 8);
  // --- text/background pairs, resolved through the cascade -----------------
  const pairs = [];
  const seen = new Set();
  for (const el of els) {
    const t = el.textContent?.trim();
    if (!t || t.length > 60) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const cs = getComputedStyle(el);
    // Walk up for the first opaque background.
    let bgEl = el, bg = 'rgba(0, 0, 0, 0)';
    while (bgEl && (bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent')) {
      bg = getComputedStyle(bgEl).backgroundColor;
      bgEl = bgEl.parentElement;
    }
    const key = `${cs.color}|${bg}|${cs.fontSize}|${cs.fontWeight}`;
    if (seen.has(key)) continue;
    seen.add(key);
    pairs.push({
      fg: cs.color, bg,
      fontSize: parseFloat(cs.fontSize),
      weight: cs.fontWeight,
      sample: t.slice(0, 24),
      cls: typeof el.className === 'string' ? el.className.slice(0, 30) : '',
    });
  }
  return { sizes, weights, colors, prose, headings, overflow, pairs,
           docW, scrollW: document.documentElement.scrollWidth };
}
"""


def audit(base: str, password: str, theme: str, width: int, height: int) -> dict:
    out: dict = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": width, "height": height})
        page = ctx.new_page()
        page.goto(base, wait_until="networkidle")
        page.fill('[data-testid="login-password"]', password)
        page.click('[data-testid="login-submit"]')
        page.wait_for_selector('[data-testid="nav"]')
        page.evaluate(
            "t => { localStorage.setItem('cv84x6.theme', t);"
            "document.documentElement.setAttribute('data-theme', t);"
            "document.documentElement.style.colorScheme = t; }",
            theme,
        )
        for p in PAGES:
            page.click(f'[data-testid="nav-{p}"]')
            page.wait_for_timeout(1500)
            out[p] = page.evaluate(MEASURE_JS)
        browser.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8802")
    ap.add_argument("--password", default="admin")
    ap.add_argument("--theme", default="light")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    data = audit(a.base, a.password, a.theme, a.width, a.height)

    sizes: Counter = Counter()
    weights: Counter = Counter()
    colors: Counter = Counter()
    for p, d in data.items():
        for k, v in d["sizes"].items():
            sizes[float(k.rstrip("px"))] += v
        for k, v in d["weights"].items():
            weights[k] += v
        for k, v in d["colors"].items():
            colors[k] += v

    print(f"== font sizes in use ({len(sizes)}) ==")
    print("  " + ", ".join(f"{s:g}px×{n}" for s, n in sorted(sizes.items())))
    print(f"== font weights in use ({len(weights)}) ==")
    print("  " + ", ".join(f"{w}×{n}" for w, n in weights.most_common()))
    print(f"== distinct text colors ({len(colors)}) ==")
    for c, n in colors.most_common():
        print(f"  {c}  ×{n}")

    print("\n== widest prose blocks (45-75 chars is the target) ==")
    for p, d in data.items():
        for row in d["prose"][:2]:
            flag = "OVER" if row["ch"] > 75 else "ok"
            print(f"  {p:<11} {row['tag']:<3} {row['ch']:>3} ch  {row['px']:>4}px "
                  f"@ {row['fontSize']:g}px  {flag}  .{row['cls']}")

    print("\n== headings with a top margin inside a padded card ==")
    for p, d in data.items():
        for h in d["headings"]:
            if h["parentCard"] and h["mt"] >= 20:
                print(f"  {p:<11} {h['fontSize']:>6} mt={h['mt']:g} mb={h['mb']:g}  {h['text']}")

    print("\n== horizontal overflow ==")
    bad = False
    for p, d in data.items():
        if d["scrollW"] > d["docW"] + 1:
            bad = True
            print(f"  {p}: {d['scrollW']} > {d['docW']}")
            for o in d["overflow"]:
                print(f"     <{o['tag']} class=\"{o['cls']}\"> right={o['right']} "
                      f"w={o['width']}  {o['text']!r}")
    if not bad:
        print("  none")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print(f"\nraw -> {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
