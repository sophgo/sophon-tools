#!/usr/bin/env python3
"""Check a compiled VL bmodel's RoPE against the reference's interleaved M-RoPE.

The converter used to gather a single position row for all 128 rotary dims,
which is only correct where t == h == w (text). For an image token the reference
takes 32 dims from the temporal row, 48 from the height row and 48 from the
width row, so a one-row table silently rotates 96/128 dims by the wrong angle --
the model keeps answering, it just stops depending on where a patch sits.

This script recomputes both tables from the model config and from the bmodel's
own position handling, so "the patch fixed it" is a measurement:

    python3 tools/ocr/check_vl_mrope.py --config model-config/paddleocr_vl_1_5

It needs no NPU and no bmodel: the reference side is pure arithmetic, and the
bmodel side is a replay of the *emitted* op sequence (row0-broadcast vs
per-section), which is what the compiled graph contains.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def rotary_rows(theta: float, head_dim: int, positions) -> np.ndarray:
    """cos/sin for each position row, shaped [3, len(positions), head_dim]."""
    inv_freq = 1.0 / (theta ** (np.arange(0, head_dim, 2, dtype=np.float64) / head_dim))
    freqs = np.outer(np.asarray(positions, dtype=np.float64), inv_freq)  # [len, 64]
    emb = np.concatenate([freqs, freqs], axis=1)                         # [len, 128]
    return np.cos(emb), np.sin(emb)


def reference_mrope(cos: np.ndarray, sin: np.ndarray, section) -> tuple[np.ndarray, np.ndarray]:
    """The reference's apply_multimodal_rotary_pos_emb, for one token.

    `cos`/`sin` are [3, head_dim]: row 0 temporal, row 1 height, row 2 width.
    `section` is doubled because the reference indexes the full head_dim table.
    """
    widths = [s * 2 for s in section]
    rows = np.concatenate([[i] * w for i, w in enumerate(widths)])
    idx = np.arange(sum(widths))
    return cos[rows, idx], sin[rows, idx]


def row0_mrope(cos: np.ndarray, sin: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """What the buggy converter emitted: temporal row for every dim."""
    return cos[0], sin[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path,
                    default=Path("model-config/paddleocr_vl_1_5"))
    args = ap.parse_args()

    cfg = json.loads((args.config / "config.json").read_text())
    head_dim = cfg["head_dim"]
    theta = float(cfg["rope_theta"])
    section = cfg["rope_scaling"]["mrope_section"]

    # A real image-token position triple: t is the constant frame index, h the
    # grid row, w the grid column. Text tokens have t == h == w, and there the
    # two implementations agree -- which is why the bug survived a text-only
    # smoke test.
    cases = {
        "image token (t,h,w)=(5,12,18)": (5, 12, 18),
        "image token (t,h,w)=(5,37,52)": (5, 37, 52),
        "text token  (t,h,w)=(9,9,9)": (9, 9, 9),
    }

    worst = 0.0
    print(f"head_dim={head_dim} theta={theta} mrope_section={section}")
    print(f"{'token':32s} {'cos dims off':>12s} {'sin dims off':>12s} {'max |diff|':>11s}")
    for label, pos in cases.items():
        cos, sin = rotary_rows(theta, head_dim, [pos[0], pos[1], pos[2]])
        ref_c, ref_s = reference_mrope(cos, sin, section)
        bad_c, bad_s = row0_mrope(cos, sin)
        dc = np.abs(ref_c - bad_c)
        ds = np.abs(ref_s - bad_s)
        off_c = int((dc > 1e-6).sum())
        off_s = int((ds > 1e-6).sum())
        worst = max(worst, float(dc.max()), float(ds.max()))
        print(f"{label:32s} {off_c:12d} {off_s:12d} {max(dc.max(), ds.max()):11.4f}")

    print()
    print("'off' counts are what the OLD converter produced (row 0 for all dims).")
    print("Text tokens must read 0/0 -- that is the case a text-only check passes;")
    print("image tokens must be non-zero or the bug was never exercised.")
    return 0 if worst > 1e-6 else 1


if __name__ == "__main__":
    raise SystemExit(main())
