"""Turn ledger.jsonl into per-area Markdown tables for docs/e2e-0.6.29.md.

A check recorded more than once keeps its LAST verdict (re-judged checks say why
in their evidence); earlier verdicts are listed under 「复判记录」 so nothing is hidden.
"""
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "ledger.jsonl"
rows = [json.loads(l) for l in LEDGER.open()]
order = []
last = {}
history = collections.defaultdict(list)
for r in rows:
    key = (r["area"], r["check"].split("（复判")[0])
    if key not in last:
        order.append(key)
    history[key].append(r)
    last[key] = r

areas = collections.OrderedDict()
for key in order:
    areas.setdefault(key[0], []).append(last[key])


def esc(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


out = []
summary = []
for area, items in areas.items():
    c = collections.Counter(i["verdict"] for i in items)
    summary.append((area, c.get("PASS", 0), c.get("FAIL", 0), c.get("BLOCKED", 0), len(items)))
    out.append(f"\n#### {area}\n\n| 检查 | 结论 | 证据 |\n|---|---|---|")
    for i in items:
        ev = esc(i["evidence"])
        if len(ev) > 260:
            ev = ev[:257] + "…"
        out.append(f"| {esc(i['check'])} | {i['verdict']} | {ev} |")

head = ["| 大项 | 通过 | 失败 | 未完成 | 合计 |", "|---|---|---|---|---|"]
head += [f"| {a} | {p} | {f} | {b} | {t} |" for a, p, f, b, t in summary]
tot = [sum(x[i] for x in summary) for i in (1, 2, 3, 4)]
head.append(f"| **合计** | **{tot[0]}** | **{tot[1]}** | **{tot[2]}** | **{tot[3]}** |")

rejudged = [(k, h) for k, h in history.items() if h[0]["verdict"] != h[-1]["verdict"] or "复判" in h[-1]["check"]]
rj = ["\n#### 复判记录\n", "| 检查 | 首判 | 终判 | 原因 |", "|---|---|---|---|"]
for k, h in rejudged:
    rj.append(f"| {esc(k[0])} · {esc(k[1])} | {h[0]['verdict']} | {h[-1]['verdict']} | {esc(h[-1]['evidence'])[:200]} |")

Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "tables.md").write_text(
    "\n".join(head) + "\n" + "\n".join(out) + "\n" + "\n".join(rj) + "\n")
print("\n".join(head))
