"""Per-op agreement of a debug block_0 run on the board (run_dbg.py) with HF.

    python3 cmp_dbg.py b0_dbg_out.npz hf_l0.npz input.npz
The debug bmodel exposes linear_attn.out_proj.add (h1), the shared-expert and
the routed-expert outputs (add_outputs.py); HF's routed part is its MLP output
minus the shared expert, computed here from the same checkpoint run.
"""
import sys

import numpy as np

o = np.load(sys.argv[1])
h = np.load(sys.argv[2])
x = np.load(sys.argv[3])["input_states"][0]
P = "model.language_model.layers.0."


def c(a, b):
    a = a.reshape(a.shape[0], -1).astype(np.float64)
    b = b.reshape(b.shape[0], -1).astype(np.float64)
    v = (a * b).sum(-1) / (np.linalg.norm(a, axis=-1) * np.linalg.norm(b, axis=-1) + 1e-30)
    return f"mean {v.mean():.5f} median {np.median(v):.5f} min {v.min():.5f}"


k = {n.replace("_f32", ""): v[0] for n, v in o.items()}
h1 = k[P + "linear_attn.out_proj.add"]
print("h1 (linear attention + residual)", c(h1, x + h["out_proj"][0]))
shared = k[P + "mlp.shared_expert_gate_mul"]
routed = [v for n, v in k.items() if "experts_mlp_output" in n][0]
mlp_dev = k["output_states"] - h1
print("mlp total                       ", c(mlp_dev, h["mlp"][0]))
print("routed experts (dev vs HF-shared)", c(routed, h["mlp"][0] - shared))
print("layer output                    ", c(k["output_states"], h["layer"][0]))
