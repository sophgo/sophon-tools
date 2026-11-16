"""HF ground truth for lc_sweep: the final-norm input/output at every position
of the sweep prompt (one causal forward covers every width and prefix).

    python3 hf_hidden.py --hf /workspace/hf/Qwen3.6-35B-A3B-int4-AutoRound --n 4096 --out hf_sweep
"""
import argparse
import os

import numpy as np
import torch
from tokenizers import Tokenizer

from hf_ref import load

TEXT = ("In the spring of that year the river rose higher than anyone in the valley could "
        "remember. The miller moved his sacks to the loft, the baker baked through the night, "
        "and the children counted boats drifting past the church. ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf", required=True)
    ap.add_argument("--n", type=int, default=4096)
    ap.add_argument("--out", default="hf_sweep")
    ap.add_argument("--threads", type=int, default=18)
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    tok = Tokenizer.from_file(os.path.join(a.hf, "tokenizer.json"))
    ids = tok.encode(TEXT * 400, add_special_tokens=False).ids[: a.n]
    model = load(a.hf)
    got = {}

    def hook(_m, inp, out):
        got["pre"] = inp[0][0].float().numpy()
        got["post"] = out[0].float().numpy()

    model.model.norm.register_forward_hook(hook)
    with torch.no_grad():
        out = model(input_ids=torch.tensor([ids]), use_cache=False, logits_to_keep=a.n)
    np.save(a.out + "_pre.npy", got["pre"].astype(np.float32))
    np.save(a.out + "_post.npy", got["post"].astype(np.float32))
    np.save(a.out + "_argmax.npy", out.logits[0].argmax(-1).numpy().astype(np.int32))
    np.save(a.out + "_ids.npy", np.array(ids, dtype=np.int32))
    np.save(a.out + "_normw.npy", model.model.norm.weight.detach().float().numpy())
    print("saved", got["pre"].shape, flush=True)


if __name__ == "__main__":
    main()
