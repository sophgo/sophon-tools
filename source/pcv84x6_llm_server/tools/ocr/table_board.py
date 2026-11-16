#!/usr/bin/env python3
"""Drive the SLANet bmodel on the board and compare with the reference.

Runs **on the board**, like ``structure_board.py``: same ``.npz`` input the
host produced, same post-processing module, so the graph and the hardware are
the only variables.

    python3 table_board.py --bmodel slanet.bmodel --ref-dir ref --out t.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import table_postprocess as T  # noqa: E402


def warm(py: str, bmodel: Path, workdir: Path) -> None:
    """Absorb the first-launch-after-boot zero result (see structure_board)."""
    import subprocess
    proc = subprocess.run([sys.executable, py, "--bmodel", str(bmodel), "--json"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return
    meta = json.loads(proc.stdout)[0]["inputs"][0]
    np.save(workdir / "warm.npy", np.zeros(tuple(meta["dims"]), np.float32))
    subprocess.run([sys.executable, py, "--bmodel", str(bmodel),
                    "--input", f"{meta['name']}={workdir/'warm.npy'}",
                    "--out", str(workdir / "warm.npz")],
                   capture_output=True, text=True)


def run_bmodel(py: str, bmodel: Path, image: np.ndarray, workdir: Path) -> list:
    np.save(workdir / "in.npy", image)
    out = workdir / "out.npz"
    proc = subprocess.run([sys.executable, py, "--bmodel", str(bmodel),
                           "--input", f"x={workdir/'in.npy'}", "--out", str(out)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"board_npu failed:\n{proc.stdout}\n{proc.stderr}")
    d = np.load(out)
    return [d[k] for k in d.files]


def html_shape(html: str) -> dict:
    """Row/column counts plus the span attributes, which is what has to match.

    Comparing HTML strings directly would over-report: attribute order and
    whitespace are not part of the structure. Rows, cells per row and the set
    of (rowspan, colspan) values are.
    """
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows, self.row, self.cells, self.spans = 0, 0, [], []

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "tr":
                if self.row:
                    self.cells.append(self.row)
                self.rows += 1
                self.row = 0
            elif tag == "td":
                self.row += 1
                self.spans.append((a.get("rowspan"), a.get("colspan")))

        def close(self):
            super().close()
            if self.row:
                self.cells.append(self.row)
            self.row = 0

    p = P()
    p.feed(html)
    p.close()
    return {"rows": p.rows, "cells_per_row": p.cells, "spans": p.spans}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bmodel", required=True, type=Path)
    ap.add_argument("--ref-dir", required=True, type=Path)
    ap.add_argument("--chars-yml", required=True, type=Path)
    ap.add_argument("--board-npu", default="board_npu.py")
    ap.add_argument("--out", type=Path, default=Path("table.json"))
    ap.add_argument("--repeat", type=int, default=5)
    args = ap.parse_args()

    chars = T.load_chars(args.chars_yml)
    ref = json.loads((args.ref_dir / "slanet_reference.json").read_text())
    results = {}
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        warm(args.board_npu, args.bmodel, work)
        for npz in sorted((args.ref_dir).glob("SLANet_plus__*.npz")):
            stem = npz.name[len("SLANet_plus__"):-4]
            name = next(k for k in ref if k.rsplit(".", 1)[0] == stem)
            x = np.load(npz)["x"]
            padded = tuple(ref[name]["padded"])
            ori = tuple(ref[name]["ori"])

            times = []
            outs = None
            for _ in range(args.repeat):
                t0 = time.perf_counter()
                outs = run_bmodel(args.board_npu, args.bmodel, x, work)
                times.append((time.perf_counter() - t0) * 1000.0)

            html, cells, score = T.decode(outs[1][0], outs[0][0], chars,
                                          padded, ori)
            want = ref[name]["html"]
            same_html = html == want
            a, b = html_shape(html), html_shape(want)
            results[name] = {
                "identical_html": same_html,
                "structure_match": a == b,
                "rows": a["rows"], "ref_rows": b["rows"],
                "cells": len(cells), "ref_cells": len(ref[name]["cells"]),
                "score": round(score, 4),
                "median_ms": round(float(np.median(times)), 1),
                "html": html,
            }
            # Write the row out before printing: on this board a long-lived
            # ssh'd python loses its stdio when the PTY closes, and a run that
            # died mid-loop left an empty results file with rc=0.
            args.out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
            print(f"  {name:20s} html={'same' if same_html else 'DIFF'} "
                  f"struct={'same' if a==b else 'DIFF'} "
                  f"rows {a['rows']}/{b['rows']} cells {len(cells)}/{len(ref[name]['cells'])} "
                  f"score {score:.3f} {np.median(times):6.1f} ms", flush=True)

    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    ok = sum(1 for v in results.values() if v["identical_html"])
    print(f"SLANet: {ok}/{len(results)} images reproduce the reference HTML")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
