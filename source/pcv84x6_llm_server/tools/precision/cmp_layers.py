"""Per-layer agreement with HF: decode replay vs block prefill (lc_rows --layers)."""
import glob
import os
import re
import sys

import numpy as np

hf = np.load(sys.argv[1])
d = sys.argv[2]


def cos(x, y):
    return (x * y).sum(-1) / (np.linalg.norm(x, axis=-1) * np.linalg.norm(y, axis=-1) + 1e-30)


layers = sorted({int(re.search(r"_l(\d+)", f).group(1)) for f in glob.glob(os.path.join(d, "*_l*.npy"))})
print(f"{'layer':>5} {'kind':>6} {'replay':>8} {'block':>8} {'block_vs_replay':>16}")
for k in layers:
    y = hf[f"l{k}"].astype(np.float64)
    r = np.load(os.path.join(d, f"replay_l{k}.npy")).astype(np.float64)
    b = np.load(os.path.join(d, f"c512_l{k}.npy")).astype(np.float64)
    n = min(len(y), len(r), len(b))
    kind = "FA" if (k + 1) % 4 == 0 else "linear"
    print(f"{k:5d} {kind:>6} {cos(r[:n], y[:n]).mean():8.4f} {cos(b[:n], y[:n]).mean():8.4f} "
          f"{cos(b[:n], r[:n]).mean():16.4f}")
