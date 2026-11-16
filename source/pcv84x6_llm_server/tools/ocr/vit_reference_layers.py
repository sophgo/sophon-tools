#!/usr/bin/env python3
"""Dump HF's vision tower's intermediate tensors, for the layer-by-layer bisection.

Stage A2 asks *where* the compiled vit stops agreeing with the reference, not
merely *whether* it does. Answering that needs the reference to produce tensors
comparable to the ones ``model_runner.py --dump_all_tensors`` emits for the
compiled graph, so the two can be walked side by side and the first diverging
step named.

**Why hooks and not ``torch.fx``.** An fx trace of this tower fails twice: it
refuses the Python-level branch on ``pixel_values.dim()`` (``TraceError:
symbolically traced variables cannot be used as inputs to control flow``), and
with concrete arguments it dies inside ``einops.rearrange`` (``Tensor type
unknown to einops <class 'torch.fx.proxy.Proxy'>``). Forward hooks run the real
modules on real tensors and record what they return, so the values are the ones
the shipped weights actually produce.

**What is hooked, and why those boundaries.** Module hooks alone cannot see
inside a module, and two of the three remaining suspects live inside one:
the rotary table is built in ``PaddleOCREncoder.forward`` and the 2x2 merge is
four statements in ``Projector.forward``. Both are therefore recomputed here
from the model's own buffers/weights, exactly as the reference does it, and
recorded under the names the compiler uses. Everything else is at a module
boundary that already has a ``loc`` in the MLIR.

    python3 tools/ocr/vit_reference_layers.py --model-dir <hf dir> \\
        --input vitin.npz --grid 12,48 --out vit_ref_layers.npz

Needs torch + transformers (``venv-vlref`` on 13.24). Runs on x86; no NPU.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vit_reference import _load_module_package, _stub_torchvision  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True, type=Path)
    ap.add_argument("--input", required=True, type=Path,
                    help=".npz with input_states [P,3,14,14], the bmodel's own input")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--grid", required=True,
                    help="gh,gw of the patch grid (P = gh*gw)")
    args = ap.parse_args()

    _stub_torchvision()

    import torch
    from safetensors.torch import load_file

    model_dir = args.model_dir
    _load_module_package(str(model_dir))
    from _paddleocr_vl_ref import modeling_paddleocr_vl as modeling
    from _paddleocr_vl_ref.configuration_paddleocr_vl import PaddleOCRVLConfig

    cfg = PaddleOCRVLConfig.from_pretrained(str(model_dir))
    tower = modeling.PaddleOCRVisionModel(cfg.vision_config)
    sd = load_file(str(model_dir / "model.safetensors"))
    weights = {k[len("visual."):]: v for k, v in sd.items() if k.startswith("visual.")}
    missing, unexpected = tower.load_state_dict(weights, strict=False)
    if missing:
        print(f"missing keys ({len(missing)}): {missing[:4]}", file=sys.stderr)
    if unexpected:
        print(f"unexpected keys ({len(unexpected)}): {unexpected[:4]}", file=sys.stderr)
    tower.eval()

    gh, gw = (int(x) for x in args.grid.split(","))
    d = np.load(args.input)
    patches = d["input_states"]
    if patches.shape[0] != gh * gw:
        raise SystemExit(f"grid {gh}x{gw} != {patches.shape[0]} patches")
    pixel_values = torch.from_numpy(patches).float().unsqueeze(0)
    position_ids = torch.arange(gh * gw) % (gh * gw)

    captured: dict[str, np.ndarray] = {}

    def record(name: str, value) -> None:
        if isinstance(value, torch.Tensor):
            captured[name] = value.detach().float().cpu().numpy()

    # ---- module boundaries ------------------------------------------------- #
    # Names are the converter's locs, so a dump from either side keys the same.
    hooks = [
        ("visual.vision_model.embeddings.patch_embedding", "out"),
        ("visual.vision_model.encoder.layers", None),      # handled per layer
        ("visual.vision_model.post_layernorm", "out"),
    ]
    emb = tower.vision_model.embeddings
    enc = tower.vision_model.encoder

    emb.patch_embedding.register_forward_hook(
        lambda m, i, o: record("visual.vision_model.embeddings.patch_embedding", o))

    # The embeddings module adds the interpolated position table internally, so
    # the sum is the module output while the table itself is recomputed below.
    tower.vision_model.embeddings.register_forward_hook(
        lambda m, i, o: record("visual.vision_model.embeddings.position_embedding.add", o))

    for idx, layer in enumerate(enc.layers):
        layer.register_forward_hook(
            lambda m, i, o, idx=idx:
            record(f"visual.vision_model.encoder.layers.{idx}.mlp.add",
                   o[0] if isinstance(o, (tuple, list)) else o))
        # The four projections and the attention result are the finest
        # boundaries a hook can see; rope is applied between q_proj and the
        # matmul, so it is checked separately below.
        for proj in ("q_proj", "k_proj", "v_proj", "out_proj"):
            mod = getattr(layer.self_attn, proj)
            mod.register_forward_hook(
                lambda m, i, o, idx=idx, proj=proj:
                record(f"visual.vision_model.encoder.layers.{idx}.self_attn.{proj}", o))
        layer.layer_norm1.register_forward_hook(
            lambda m, i, o, idx=idx:
            record(f"visual.vision_model.encoder.layers.{idx}.layer_norm1", o))
        layer.layer_norm2.register_forward_hook(
            lambda m, i, o, idx=idx:
            record(f"visual.vision_model.encoder.layers.{idx}.layer_norm2", o))

    tower.vision_model.post_layernorm.register_forward_hook(
        lambda m, i, o: record("visual.vision_model.post_layernorm", o))

    with torch.no_grad():
        out = tower(pixel_values=pixel_values,
                    image_grid_thw=[(1, gh, gw)],
                    position_ids=position_ids,
                    interpolate_pos_encoding=True,
                    # use_rope and cu_seqlens are not optional here.
                    # ``PaddleOCREncoder.forward`` computes
                    # ``use_rope = (use_rope is True) and ...``, so leaving the
                    # flag at its False default makes ``rope_emb`` None and the
                    # attention falls into the *non-rope* branch: it would never
                    # apply the vision rotary at all. The shipped model calls
                    # the tower with ``use_rope=True, cu_seqlens=[0, numel]``
                    # (modeling_paddleocr_vl.py:2193-2205), and so must the
                    # reference -- a rope-less reference disagrees with any
                    # correct graph by construction.
                    use_rope=True,
                    cu_seqlens=torch.tensor([0, gh * gw], dtype=torch.int32))
    tower_feats = out.last_hidden_state

    # ---- the two things a hook cannot see -------------------------------- #
    # 1. The rotary table. Built in PaddleOCREncoder.forward from the grid; the
    #    converter builds the same thing in vision_rotary(). Recorded at the
    #    converter's shape [P, 72] (head_dim//2 * 2 frequencies, repeated).
    with torch.no_grad():
        image_pids = torch.arange(gh * gw) % (gh * gw)
        hids = image_pids // gw
        wids = image_pids % gw
        pids = torch.stack([hids, wids], dim=-1)
        rope_max = enc.rotary_pos_emb(int(pids.max()) + 1)
        rope = rope_max[pids].flatten(1).repeat(1, 2)
        record("visual.rotary_pos_emb.cos", rope.cos())
        record("visual.rotary_pos_emb.sin", rope.sin())

    # 2. The position table, interpolated to this grid. The bmodel holds it as a
    #    constant; recomputing it here is what makes the interpolation geometry
    #    (the align_corners vs half_pixel question) directly checkable.
    with torch.no_grad():
        pos_w = emb.position_embedding.weight.unsqueeze(0)
        dim = pos_w.shape[-1]
        side = int(round(pos_w.shape[1] ** 0.5))
        table = pos_w.reshape(1, side, side, dim).permute(0, 3, 1, 2)
        table = torch.nn.functional.interpolate(table, size=(gh, gw),
                                                mode="bilinear", align_corners=False)
        table = table.permute(0, 2, 3, 1).reshape(-1, dim)
        record("visual.vision_model.embeddings.position_embedding", table)

    # ---- the projector (the reference keeps it outside `visual`) ---------- #
    projector = modeling.Projector(cfg, cfg.vision_config)
    proj_weights = {k[len("mlp_AR."):]: v for k, v in sd.items() if k.startswith("mlp_AR.")}
    pmissing, _ = projector.load_state_dict(proj_weights, strict=False)
    if pmissing:
        raise SystemExit(f"projector weights missing: {pmissing}")
    projector.eval()

    projector.pre_norm.register_forward_hook(
        lambda m, i, o: record("mlp_AR.pre_norm", o))
    projector.linear_1.register_forward_hook(
        lambda m, i, o: record("mlp_AR.linear_1", o))
    projector.linear_2.register_forward_hook(
        lambda m, i, o: record("mlp_AR.linear_2", o))

    with torch.no_grad():
        # A LIST of one feature tensor, not the tensor itself: the shipped model
        # calls the tower with ``vision_return_embed_list=True``, which makes
        # ``last_hidden_state`` a list, and ``Projector.forward`` then takes its
        # list branch -- the one that merges with
        # ``rearrange("(t h p1 w p2) d -> (t h w) (p1 p2 d)")``. Passing a bare
        # tensor instead takes the *other* branch, whose flat ``view(-1, 4d)``
        # reorders the 2x2 blocks differently and would make a correct graph
        # look wrong.
        # Each list element is ``(numel, dim)`` -- the batch axis is dropped
        # along the list branch, which is why the rearrange pattern is 2-D.
        feats = projector([tower_feats.squeeze(0)], [(1, gh, gw)])
    record("mlp_AR.out", feats[0] if isinstance(feats, list) else feats)

    # The merge itself: (t h p1 w p2) d -> (t h w) (p1 p2 d). Recorded so the
    # converter's reshape/permute pair can be checked against the reference's
    # rearrange rather than against a description of it.
    #
    # ORDER MATTERS: the reference normalises first and merges second
    # (`hidden_states = self.pre_norm(image_features).view(-1, hidden_size)`
    # in Projector.forward). Merging the *un-normalised* tower output gives a
    # tensor with the right shape and the wrong values, so this recomputes it
    # from the projector's own pre_norm rather than from `tower_feats`.
    with torch.no_grad():
        from einops import rearrange
        normed = projector.pre_norm(tower_feats.squeeze(0))
        merged = rearrange(normed,
                           "(h p1 w p2) d -> (h w) (p1 p2 d)",
                           h=gh // 2, p1=2, w=gw // 2, p2=2)
        record("mlp_AR.reshape2", merged)

    np.savez(args.out, **captured)
    print(f"wrote {args.out}: {len(captured)} tensors (grid {gh}x{gw})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
