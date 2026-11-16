#!/usr/bin/env python3
"""Contrast audit over the pairs the console actually renders.

Every text/background combination is read out of the live page in Chromium
(computed `color` against the first opaque ancestor background), then checked
with the Refactoring UI skill's own `check_contrast.py` — 4.5:1 for normal text,
3:1 for text at 18px or above (§5.6).

Usage:
    python3 web/acceptance/contrast_audit.py --base http://127.0.0.1:8802
    python3 web/acceptance/contrast_audit.py --json out.json --matrix out.json

Exit code 1 if any pair fails, so this can gate a change.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# Reuse the skill's implementation rather than re-deriving the WCAG formula.
SKILL = Path("/home/zzt/workspace/refactoring-ui-skill/skills/refactoring-ui/scripts")
if SKILL.exists():
    sys.path.insert(0, str(SKILL))
from check_contrast import contrast_ratio  # noqa: E402

PAGES = ["overview", "models", "agents", "playground", "keys", "settings", "docs"]

# Every text-bearing element and the first opaque colour behind it. Elements
# with no text (rules, bars, chart strokes) are not text-contrast findings; their
# non-text minimum is reported separately.
PAIRS_JS = r"""
() => {
  const parse = (s) => {
    const m = s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map((x) => parseFloat(x));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const hex = (c) => '#' + [c.r, c.g, c.b]
    .map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
  // Composite a translucent colour over an opaque one.
  const over = (fg, bg) => ({
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a),
    a: 1,
  });
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    const text = [...el.childNodes]
      .filter((n) => n.nodeType === 3)
      .map((n) => n.textContent.trim())
      .join(' ')
      .trim();
    if (!text) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) continue;
    const fg0 = parse(cs.color);
    if (!fg0) continue;
    // Walk up to the first opaque background, compositing as we go.
    let stack = [];
    let node = el;
    let base = null;
    while (node) {
      const bg = parse(getComputedStyle(node).backgroundColor);
      if (bg && bg.a > 0) {
        stack.push(bg);
        if (bg.a >= 0.999) { base = bg; break; }
      }
      node = node.parentElement;
    }
    if (!base) base = { r: 255, g: 255, b: 255, a: 1 };
    // Composite from the bottom of the stack upward.
    let bg = base;
    for (const layer of stack.slice(0, -1).reverse()) bg = over(layer, bg);
    const fg = fg0.a >= 0.999 ? fg0 : over(fg0, bg);
    out.push({
      fg: hex(fg), bg: hex(bg),
      fontSize: parseFloat(cs.fontSize),
      weight: cs.fontWeight,
      cls: typeof el.className === 'string' ? el.className : '',
      tag: el.tagName.toLowerCase(),
      page: document.querySelector('[aria-current="page"]')?.textContent?.trim() ?? '',
      sample: text.slice(0, 28),
    });
  }
  return out;
}
"""


def collect(base: str, password: str, theme: str, width: int, height: int,
            load_models: bool = False) -> list[dict]:
    rows: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": width, "height": height})
        page = ctx.new_page()
        page.goto(base, wait_until="networkidle")
        page.fill('[data-testid="login-password"]', password)
        page.click('[data-testid="login-submit"]')
        page.wait_for_selector('[data-testid="nav"]')
        if load_models:
            # Load the mock models so the states that only exist once something
            # is serving are covered too: the 在线 pill, the 卸载 outline, the
            # chat turn, a fresh API key. These are where --accent appears as a
            # fill, which is the pairing with the least headroom.
            page.evaluate(
                """async () => {
                     const r = await fetch('/api/models');
                     const j = await r.json();
                     for (const m of j.models) {
                       await fetch(`/api/models/${encodeURIComponent(m.id)}/load`,
                                   { method: 'POST' });
                     }
                   }""")
            page.wait_for_timeout(2500)
        page.evaluate(
            "t => { localStorage.setItem('cv84x6.theme', t);"
            "document.documentElement.setAttribute('data-theme', t);"
            "document.documentElement.style.colorScheme = t; }",
            theme,
        )
        for p in PAGES:
            page.click(f'[data-testid="nav-{p}"]')
            page.wait_for_timeout(1500)
            for row in page.evaluate(PAIRS_JS):
                row["page"] = p
                row["theme"] = theme
                rows.append(row)
        browser.close()
    return rows


def dedupe(rows: list[dict]) -> list[dict]:
    """One row per (theme, fg, bg, size, weight). The same pair repeated 200
    times on one page is one finding, not 200 (§13)."""
    seen: dict[tuple, dict] = {}
    for r in rows:
        key = (r["theme"], r["fg"], r["bg"], round(r["fontSize"], 2), r["weight"])
        if key not in seen:
            seen[key] = dict(r, count=0, pages=set())
        seen[key]["count"] += 1
        seen[key]["pages"].add(r["page"])
    return list(seen.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8802")
    ap.add_argument("--password", default="admin")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--json", default="")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--load", action="store_true",
                    help="load the mock models first, to cover the served states")
    a = ap.parse_args()

    rows: list[dict] = []
    for theme in ("light", "dark"):
        rows += collect(a.base, a.password, theme, a.width, a.height, a.load)
    uniq = dedupe(rows)

    checked, failed = 0, []
    for r in uniq:
        # WCAG: 18.66px+ or 14px+ at 700 counts as large text (3:1).
        large = r["fontSize"] >= 18.66 or (
            r["fontSize"] >= 14 and int(r["weight"]) >= 700)
        need = 3.0 if large else 4.5
        ratio = contrast_ratio(r["fg"], r["bg"])
        r["ratio"] = round(ratio, 2)
        r["need"] = need
        r["large"] = large
        checked += 1
        if ratio < need:
            failed.append(r)

    if not a.quiet:
        print(f"== contrast ({checked} distinct text/background pairs, "
              f"both themes, {a.width}px) ==")
        for theme in ("light", "dark"):
            sub = sorted([r for r in uniq if r["theme"] == theme],
                         key=lambda r: r["ratio"])
            worst = sub[:6]
            print(f"\n  {theme}: {len(sub)} pairs, worst first")
            for r in worst:
                mark = "FAIL" if r["ratio"] < r["need"] else "ok  "
                print(f"    {mark} {r['ratio']:>5.2f}:1 (need {r['need']:g}) "
                      f"{r['fg']} on {r['bg']}  {r['fontSize']:g}px/w{r['weight']} "
                      f"{r['tag']}.{r['cls'][:24]}  {r['sample']!r}")

    if failed:
        print(f"\n!! {len(failed)} pair(s) below WCAG AA:")
        for r in failed:
            print(f"   {r['theme']}: {r['ratio']}:1 < {r['need']:g} "
                  f"{r['fg']} on {r['bg']} {r['fontSize']:g}px "
                  f"pages={sorted(r['pages'])} cls=.{r['cls'][:30]} {r['sample']!r}")
    else:
        print(f"\nALL PASS — {checked} pairs meet WCAG AA in both themes")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump([{k: (sorted(v) if isinstance(v, set) else v)
                        for k, v in r.items()} for r in uniq], f,
                      ensure_ascii=False, indent=1)
        print(f"raw -> {a.json}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
