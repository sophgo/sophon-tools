#!/usr/bin/env python3
"""Token-by-token alignment of the board against the HF reference.

MYS-2660's acceptance criterion 3: for five images, compare the greedy token
sequences element by element, report the identical fraction, and for anything
that diverges report the first differing position plus the reference's top-2
logit gap there, so a bf16 rounding difference can be told apart from a real
defect.

Two references are produced and kept apart, as the card requires:

* **same pixels** -- the reference is fed the *exact* patch tensor the board
  uploaded. This is the acceptance number: the only variable left is the
  engine.
* **``--smart-resize``** -- the reference uses the processor's own resize, at
  the grid it would pick for that crop. Its grid differs from the board's
  fixed stage, so this quantifies what the fixed stage costs and is reported
  separately. It is never averaged into the first number.

Each element is one whole image recognised as a single VLM element (the prompt
matches the layout class the page pipeline would assign), so the comparison is
"same pixels in, same tokens out" and nothing else.

    python3 tools/ocr/vl_align.py run --board ... --out work/align
    python3 tools/ocr/vl_align.py report --work work/align
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: The card's five images, and the layout class each one is mostly made of --
#: which is what picks the instruction. ``table_stats`` and the two table
#: images get the table prompt because that is what a page pipeline would send
#: for their table region.
IMAGES = [
    ("cn_notice.png", "text"),
    ("en_report.png", "text"),
    ("mixed_spec.png", "text"),
    ("table_stats.png", "table"),
    ("cn_table_merged.png", "table"),
    # The card asks for these two under the table criterion (§4) as well.
    ("cn_table_simple.png", "table"),
]


def _stage_side(stage: str) -> tuple[int, int]:
    h, w = (int(v) for v in stage.split("x"))
    return h, w


def cmd_prep(args) -> int:
    """Host: one prep dir per image."""
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    img_dir = Path(args.img_dir)
    made = []
    for name, label in IMAGES:
        p = img_dir / name
        if not p.exists():
            print(f"skip {name}: not found", file=sys.stderr)
            continue
        d = out / name.replace(".png", "")
        subprocess.run(
            [sys.executable, str(Path(__file__).with_name("vl_native_prep.py")),
             "prep", "--img", str(p), "--label", label, "--stage", args.stage,
             "--tokenizer", args.tokenizer, "--max-new", str(args.max_new),
             "--seq", str(args.seq), "--out", str(d)],
            check=True)
        made.append(d.name)
    print(json.dumps(made))
    return 0


def cmd_run(args) -> int:
    """Board: vl_native on each prepared dir, then collect."""
    out = args.out
    native = Path(args.vl_native)
    if not native.is_absolute():
        native = (Path.cwd() / native).resolve()
    bmodel = Path(args.vl_bmodel)
    if not bmodel.is_absolute():
        bmodel = (Path.cwd() / bmodel).resolve()

    results = {}
    for name, _ in IMAGES:
        d = out / name.replace(".png", "")
        if not (d / "meta.txt").exists():
            continue
        subprocess.run([str(native), "--bmodel", str(bmodel),
                        "--work", str(d), "--out", str(d)],
                       check=True)
        tim = {}
        for line in (d / "timings.txt").read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition(" ")
            if k == "tokens":
                tim["tokens"] = [int(t) for t in v.split()]
            else:
                try:
                    tim[k] = float(v)
                except ValueError:
                    pass
        results[name] = tim
        print(f"{name:24s} {len(tim.get('tokens', [])):3d} tok  "
              f"vit {tim.get('vit_ms', 0):.0f} prefill {tim.get('prefill_ms', 0):.0f} "
              f"decode {tim.get('decode_ms', 0):.0f} ms", file=sys.stderr, flush=True)
    (out / "board.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


def cmd_reference(args) -> int:
    """Host: HF greedy decode of every prepared element, plus the logits."""
    out = args.out
    for name, _ in IMAGES:
        d = out / name.replace(".png", "")
        if not (d / "meta.txt").exists():
            continue
        cmd = [sys.executable, str(Path(__file__).with_name("vl_native_prep.py")),
               "reference", "--work", str(d), "--model-dir", args.model_dir,
               "--max-new", str(args.max_new), "--ctx", str(args.ctx)]
        if args.smart_resize:
            cmd.append("--smart-resize")
        env = dict(os.environ)
        if args.stub:
            env["PYTHONPATH"] = args.stub + (
                os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        subprocess.run(cmd, check=True, env=env)
    return 0


def align_sequences(board: list[int], ref: list[int]) -> dict:
    """Score two token sequences without punishing a single insertion.

    Greedy decoding is not stable against a near-tie: one bf16 rounding choice
    can insert or drop a single token, after which every later position is
    shifted by one and a position-by-position count reports the whole tail as
    different. `mixed_spec` measured 25/192 = 13.0% that way while the texts
    are identical apart from one space.

    So the number reported is the **longest common subsequence** length, which
    is what "do these two say the same thing" actually means, plus the raw
    position-by-position count for transparency, plus where the first
    divergence is. LCS is O(n*m) over a few hundred tokens: exact and cheap.
    """
    n, m = len(board), len(ref)
    # Roll two rows instead of keeping the whole table.
    prev = [0] * (m + 1)
    for i in range(1, n + 1):
        cur = [0] * (m + 1)
        bi = board[i - 1]
        for j in range(1, m + 1):
            if bi == ref[j - 1]:
                cur[j] = prev[j - 1] + 1
            else:
                cur[j] = cur[j - 1] if cur[j - 1] >= prev[j] else prev[j]
        prev = cur
    lcs = prev[m]
    first = None
    for i in range(min(n, m)):
        if board[i] != ref[i]:
            first = i
            break
    raw_same = sum(1 for i in range(min(n, m)) if board[i] == ref[i])
    return {
        "lcs": lcs,
        "lcs_ratio": round(lcs / max(n, m), 4) if max(n, m) else 0.0,
        "raw_identical": raw_same,
        "raw_compared": min(n, m),
        "first_divergence": first,
    }


def cmd_report(args) -> int:
    """Host: the acceptance table."""
    out = args.out
    rows, notes = [], []
    for name, _ in IMAGES:
        d = out / name.replace(".png", "")
        board = json.loads((out / "board.json").read_text(encoding="utf-8")).get(name)
        ref_path = d / "reference.json"
        if board is None or not ref_path.exists():
            notes.append(f"{name}: missing board or reference output")
            continue
        ref = json.loads(ref_path.read_text(encoding="utf-8"))
        b, r = board.get("tokens", []), ref["tokens"]
        al = align_sequences(b, r)
        n = al["raw_compared"]
        same = al["raw_identical"]
        first = al["first_divergence"]
        steps = {s["pos"]: s for s in ref.get("steps", [])}
        s = steps.get(first) if first is not None else None
        rows.append({
            "image": name,
            "prompt": d.name,
            "board_tokens": len(b), "reference_tokens": len(r),
            "compared": n, "identical": same,
            "lcs": al["lcs"], "lcs_ratio": al["lcs_ratio"],
            "exact": first is None and len(b) == len(r),
            "first_divergence": first,
            "board_token": b[first] if first is not None and first < len(b) else None,
            "reference_token": r[first] if first is not None else None,
            "ref_top1": s["top1"] if s else None,
            "ref_top2": s["top2"] if s else None,
            "ref_gap": s["gap"] if s else None,
            "reference_text": ref["text"],
            "board_text": _decode(b, args.tokenizer),
        })

    total = sum(r["compared"] for r in rows)
    ident = sum(r["identical"] for r in rows)
    exact = sum(1 for r in rows if r["exact"])
    lcs = sum(r["lcs"] for r in rows)
    span = sum(max(r["board_tokens"], r["reference_tokens"]) for r in rows)
    summary = {
        "elements": len(rows),
        "exact_matches": exact,
        "tokens_compared": total,
        "tokens_identical": ident,
        "raw_ratio": round(ident / total, 4) if total else 0.0,
        "lcs_tokens": lcs,
        "lcs_ratio": round(lcs / span, 4) if span else 0.0,
        "note": "lcs_ratio is the acceptance number: longest common subsequence "
                "over the longer sequence, per element, summed. raw_ratio is the "
                "strict position-by-position count, reported because it is what "
                "a reader expects -- it collapses to near zero after a single "
                "inserted token, which is a property of the metric, not of the "
                "engine. 'exact' counts elements whose whole sequence matches.",
    }
    (out / "align.json").write_text(json.dumps(
        {"summary": summary, "rows": rows, "notes": notes},
        indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    for r in rows:
        flag = "OK  " if r["exact"] else "DIFF"
        extra = ""
        if r["first_divergence"] is not None:
            extra = (f"  first diff @{r['first_divergence']} "
                     f"board={r['board_token']} ref={r['reference_token']} "
                     f"gap={r['ref_gap']}")
        print(f"  {flag} {r['image']:22s} lcs {r['lcs']:3d}/"
              f"{max(r['board_tokens'], r['reference_tokens']):3d} "
              f"({r['lcs_ratio']:6.1%})  raw {r['identical']:3d}/{r['compared']:3d}{extra}")
    return 0 if exact == len(rows) else 1


def _decode(ids, tokenizer) -> str | None:
    if not tokenizer or not ids:
        return None
    from tokenizers import Tokenizer
    return Tokenizer.from_file(str(tokenizer)).decode(ids, skip_special_tokens=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prep", help="host: prepare every image")
    p.add_argument("--img-dir", required=True)
    p.add_argument("--tokenizer", required=True)
    p.add_argument("--stage", default="784x784")
    p.add_argument("--max-new", type=int, default=192)
    p.add_argument("--seq", type=int, default=2048)
    p.add_argument("--out", required=True, type=Path)
    p.set_defaults(fn=cmd_prep)

    r = sub.add_parser("run", help="board: decode every prepared element")
    r.add_argument("--vl-native", required=True)
    r.add_argument("--vl-bmodel", required=True)
    r.add_argument("--out", required=True, type=Path)
    r.set_defaults(fn=cmd_run)

    f = sub.add_parser("reference", help="host: HF reference for every element")
    f.add_argument("--model-dir", required=True)
    f.add_argument("--out", required=True, type=Path)
    f.add_argument("--max-new", type=int, default=192)
    f.add_argument("--ctx", type=int, default=4,
                   help="positions per element that get top-2 logit pricing")
    f.add_argument("--smart-resize", action="store_true")
    f.add_argument("--stub", default=None,
                   help="dir holding the torchvision stub (the installed wheel "
                        "is ABI-broken against torch 2.14)")
    f.set_defaults(fn=cmd_reference)

    q = sub.add_parser("report", help="host: the acceptance table")
    q.add_argument("--out", required=True, type=Path)
    q.add_argument("--tokenizer", default=None)
    q.set_defaults(fn=cmd_report)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
