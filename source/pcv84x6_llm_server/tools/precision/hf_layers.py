"""HF per-layer outputs (residual stream after each decoder layer) for the
first N positions of the sweep text, for comparison with lc_rows --layers."""
import argparse
import os

import numpy as np
import torch
from tokenizers import Tokenizer

from hf_ref import load
from hf_hidden import TEXT  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--hf", required=True)
ap.add_argument("--n", type=int, default=512)
ap.add_argument("--out", required=True)
a = ap.parse_args()
torch.set_num_threads(18)
tok = Tokenizer.from_file(os.path.join(a.hf, "tokenizer.json"))
ids = tok.encode(TEXT * 400, add_special_tokens=False).ids[: a.n]
model = load(a.hf)
outs = {}
for i, layer in enumerate(model.model.layers):
    def hook(_m, _inp, out, i=i):
        t = out[0] if isinstance(out, tuple) else out
        outs[i] = t[0].float().numpy().astype(np.float32)
    layer.register_forward_hook(hook)
with torch.no_grad():
    model(input_ids=torch.tensor([ids]), use_cache=False, logits_to_keep=1)
np.savez(a.out, **{f"l{i}": v for i, v in outs.items()})
print("saved", len(outs), flush=True)
