"""Per-position agreement of lc_rows.py outputs with the HF reference.

    python3 cmp_rows.py --hf hf36_sweep --normw hf36_normw.npy rows/*.npy
"""
import argparse
import os

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf", required=True)
    ap.add_argument("--normw", required=True)
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()
    post = np.load(a.hf + "_post.npy").astype(np.float64)
    w = np.load(a.normw).astype(np.float64)
    print(f"{'run':>8} {'rows':>5} {'mean':>7} {'p10':>7} {'min':>7}   mean by 512-row block")
    for f in a.files:
        m = np.load(f).astype(np.float64)
        n = min(len(m), len(post))
        x = m[:n]
        x = x / np.sqrt((x * x).mean(-1, keepdims=True) + 1e-6) * (1.0 + w)
        y = post[:n]
        c = (x * y).sum(-1) / (np.linalg.norm(x, axis=-1) * np.linalg.norm(y, axis=-1) + 1e-30)
        blocks = " ".join(f"{c[i:i + 512].mean():.3f}" for i in range(0, n, 512))
        print(f"{os.path.basename(f)[:-4]:>8} {n:5d} {c.mean():7.4f} {np.percentile(c, 10):7.4f} "
              f"{c.min():7.4f}   {blocks}")


if __name__ == "__main__":
    main()
