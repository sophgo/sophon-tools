"""HF layer-0 intermediates on given embeddings (input to block_0).

    python3 hf_l0.py --hf <AutoRound checkpoint> --input in2048.npz --out hf_l0.npz
"""
import argparse

import numpy as np
import torch
import torch.nn.functional as F

from hf_ref import load

ap = argparse.ArgumentParser()
ap.add_argument("--hf", required=True)
ap.add_argument("--input", required=True, help="npz with input_states [1, L, hidden]")
ap.add_argument("--out", required=True)
a = ap.parse_args()
torch.set_num_threads(18)
model = load(a.hf)
lay = model.model.layers[0]
la = lay.linear_attn
x = torch.tensor(np.load(a.input)["input_states"]).to(torch.bfloat16)
out = {}


def keep(name):
    def h(_m, inp, o):
        out[name] = (o[0] if isinstance(o, tuple) else o).float().numpy()
        if inp:
            out[name + ".in"] = inp[0].float().numpy()
    return h


for name, mod in [("input_layernorm", lay.input_layernorm), ("in_proj_a", la.in_proj_a),
                  ("in_proj_b", la.in_proj_b), ("norm", la.norm), ("out_proj", la.out_proj),
                  ("post_attention_layernorm", lay.post_attention_layernorm), ("mlp", lay.mlp)]:
    mod.register_forward_hook(keep(name))
with torch.no_grad():
    pos = torch.arange(x.shape[1])[None]
    y = lay(x, position_embeddings=model.model.rotary_emb(x, pos), attention_mask=None,
            position_ids=pos)
    out["layer"] = (y[0] if isinstance(y, tuple) else y).float().numpy()
np.savez(a.out, **out)
print("saved", sorted(out), flush=True)
