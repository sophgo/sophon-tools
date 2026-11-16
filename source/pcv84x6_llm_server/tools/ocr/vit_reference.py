#!/usr/bin/env python3
"""Reference vision-tower features for one resized crop.

Stage A's alignment question is narrow: given *the same* resized image, does the
compiled vit stage reproduce what the reference vision tower produces? Answering
it needs the tower only -- not the 1.9 GB language model, not a generation --
so this loads ``PaddleOCRVisionModel`` from the model directory and runs one
forward.

Two things about this host make the harness non-obvious, both handled here:

* **torchvision is ABI-broken** against the installed torch (``operator
  torchvision::nms does not exist``), and ``transformers`` imports it at module
  import time. The tower uses none of it, so a minimal stand-in is registered
  before ``transformers`` loads. ``InterpolationMode`` is the one symbol
  ``transformers.image_utils`` imports eagerly.
* **the vision tower owns the 2x2 merge MLP as a separate module** (``mlp_AR``)
  rather than as a child of ``visual``, so both prefixes are loaded.

    python3 tools/ocr/vit_reference.py --model-dir <hf dir> \\
        --image tests/data/ocr/img/ui_status.png --height 168 --width 672 \\
        --out /tmp/vit_ref.npz
"""

from __future__ import annotations

import argparse
import enum
import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

import numpy as np


def _stub_torchvision() -> None:
    """Make ``import torchvision`` resolve to an empty stand-in."""

    class InterpolationMode(enum.IntEnum):
        NEAREST = 0
        NEAREST_EXACT = 1
        BILINEAR = 2
        BICUBIC = 3
        BOX = 4
        HAMMING = 5
        LANCZOS = 6

    root = types.ModuleType("torchvision")
    root.__spec__ = importlib.machinery.ModuleSpec("torchvision", None)
    root.__version__ = "0.0.0"
    transforms = types.ModuleType("torchvision.transforms")
    transforms.__spec__ = importlib.machinery.ModuleSpec("torchvision.transforms", None)
    transforms.InterpolationMode = InterpolationMode
    root.transforms = transforms
    sys.modules["torchvision"] = root
    sys.modules["torchvision.transforms"] = transforms
    for name in ("ops", "models", "io", "utils", "datasets", "extension"):
        mod = types.ModuleType(f"torchvision.{name}")
        mod.__spec__ = importlib.machinery.ModuleSpec(f"torchvision.{name}", None)
        setattr(root, name, mod)
        sys.modules[f"torchvision.{name}"] = mod


def pack_patches(rgb: np.ndarray, height: int, width: int):
    """``[H,W,3]`` uint8 -> ``[P, 3*14*14]`` float32, the tower's input layout.

    This mirrors ``image_processing_paddleocr_vl.py``: resize with BICUBIC,
    rescale by 1/255, normalise by mean=std=0.5, then rearrange
    ``(C, H, Ph, W, Pw) -> (H, W, C, Ph, Pw)`` so each row is one patch.
    """
    import torch
    from PIL import Image

    img = Image.fromarray(rgb).resize((width, height), Image.BICUBIC)
    x = np.asarray(img, dtype=np.float32) / 255.0
    x = (x - 0.5) / 0.5
    gh, gw = height // 14, width // 14
    # (H, W, C) -> (P, C, 14, 14): the tower's patch_embedding is a Conv with
    # kernel = stride = 14 and expects one patch per batch row.
    x = x.reshape(gh, 14, gw, 14, 3).transpose(0, 2, 4, 1, 3).reshape(gh * gw, 3, 14, 14)
    # The model's forward switches on pixel_values.dim(): the 5-D branch is the
    # per-patch form, [batch, patches, C, 14, 14], which is also what the
    # bmodel's [576, 3, 14, 14] input corresponds to.
    pixel_values = torch.from_numpy(x).float().unsqueeze(0)
    grid = torch.tensor([[1, gh, gw]], dtype=torch.long)
    return pixel_values, grid


def _load_module_package(path: str) -> None:
    """Register ``path`` as a package so its relative imports resolve."""
    import importlib

    name = "_paddleocr_vl_ref"
    if name in sys.modules:
        return
    # The directory has no __init__.py (it is a HuggingFace ``trust_remote_code``
    # directory, not an installed package), so a namespace-style package is
    # registered by hand: __path__ is all the import system needs for the
    # relative imports inside the model files to resolve.
    pkg = types.ModuleType(name)
    pkg.__path__ = [path]
    pkg.__spec__ = importlib.machinery.ModuleSpec(name, None, is_package=True)
    pkg.__spec__.submodule_search_locations = [path]
    sys.modules[name] = pkg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True, type=Path)
    ap.add_argument("--image", type=Path,
                    help="source image; packed to patches here unless --patches is given")
    ap.add_argument("--patches", type=Path,
                    help="a .npy/.npz holding exactly the tensor the bmodel takes "
                         "([P,3,14,14] float32). Use this to compare against a "
                         "board run that already fixed its pixels: packing the "
                         "image again here would resample it and turn a valid "
                         "comparison into a spurious mismatch.")
    ap.add_argument("--height", type=int)
    ap.add_argument("--width", type=int)
    ap.add_argument("--grid", default=None,
                    help="gh,gw of the patch grid. Required with --patches when "
                         "the stage is non-square and has a square patch count: "
                         "576 patches is both 24x24 and 12x48, and guessing "
                         "wrong changes the rotary table and the 2x2 merge "
                         "grouping while leaving every tensor shape intact.")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    if args.patches is None and (args.image is None or args.height is None
                                 or args.width is None):
        ap.error("give either --patches, or --image with --height and --width")

    _stub_torchvision()

    import torch
    from PIL import Image
    from safetensors.torch import load_file

    model_dir = args.model_dir
    sys.path.insert(0, str(model_dir.parent))

    # The model directory is a package whose modules import each other
    # relatively (`from .configuration_paddleocr_vl import ...`), so it has to
    # be loaded *as* a package rather than as a loose file.
    _load_module_package(str(model_dir))
    from _paddleocr_vl_ref import modeling_paddleocr_vl as modeling

    from _paddleocr_vl_ref.configuration_paddleocr_vl import PaddleOCRVLConfig
    cfg = PaddleOCRVLConfig.from_pretrained(str(model_dir))
    tower = modeling.PaddleOCRVisionModel(cfg.vision_config)

    sd = load_file(str(model_dir / "model.safetensors"))
    weights = {}
    for prefix in ("visual.",):
        for key, value in sd.items():
            if key.startswith(prefix):
                weights[key[len(prefix):]] = value
    missing, unexpected = tower.load_state_dict(weights, strict=False)
    if missing:
        print(f"missing keys ({len(missing)}): {missing[:4]}", file=sys.stderr)
    if unexpected:
        print(f"unexpected keys ({len(unexpected)}): {unexpected[:4]}", file=sys.stderr)

    tower.eval()
    if args.patches is not None:
        # Exactly the bmodel's own input: no resampling, no normalisation, no
        # chance of the two sides disagreeing about preprocessing.
        raw = np.load(args.patches)
        arr = raw["input_states"] if hasattr(raw, "files") else raw
        arr = np.asarray(arr, dtype=np.float32)
        if arr.ndim != 4 or arr.shape[1:] != (3, 14, 14):
            raise SystemExit(f"--patches must be [P,3,14,14], got {arr.shape}")
        # The patch count does NOT determine the grid: 576 patches is 24x24,
        # 12x48 and 48x12 all at once, and the grid decides both the rotary
        # table and how the 2x2 merge groups tokens. Every tensor would still
        # have the right shape, so a wrong guess here shows up only as a wrong
        # answer (cosine 0.77 instead of 1.0 on an identical input).
        n = arr.shape[0]
        if args.grid:
            gh, gw = (int(x) for x in args.grid.split(","))
        elif args.height and args.width:
            gh, gw = args.height // 14, args.width // 14
        else:
            raise SystemExit(
                f"{n} patches does not name a grid; pass --grid gh,gw (e.g. "
                "--grid 12,48 for the 168x672 stage)")
        if gh * gw != n:
            raise SystemExit(f"grid {gh}x{gw} does not match {n} patches")
        grid = torch.tensor([[1, gh, gw]], dtype=torch.long)
        pixel_values = torch.from_numpy(arr).float().unsqueeze(0)
    else:
        rgb = np.asarray(Image.open(args.image).convert("RGB"))
        pixel_values, grid = pack_patches(rgb, args.height, args.width)
    # The LM builds vision position ids as arange(numel) % (h*w), exactly the
    # flattened grid coordinates the tower's rotary embedding expects; passing
    # them is not optional (the patch embedding asserts on them).
    numel = int(grid.prod())
    siglip_position_ids = torch.arange(numel) % int(grid[0, 1] * grid[0, 2])
    with torch.no_grad():
        # use_rope and cu_seqlens are NOT optional, and leaving them out is a
        # silent wrong answer rather than an error: ``PaddleOCREncoder.forward``
        # computes ``use_rope = (use_rope is True) and ...``, so the default
        # False makes ``rope_emb`` None and the attention takes its *non-rope*
        # branch. The tower then never applies the vision rotary at all. The
        # shipped model calls it with use_rope=True and cu_seqlens=[0, numel]
        # (modeling_paddleocr_vl.py:2193-2205); so must this.
        #
        # This cost stage A a wrong root cause: the reference was rope-less
        # while the bmodel uses rope, so the two could not agree, and the 0.369
        # cosine was read as a converter defect. With rope enabled the same
        # bmodel agrees with this reference at 0.99996.
        out = tower(pixel_values=pixel_values, image_grid_thw=[tuple(grid[0].tolist())],
                    position_ids=siglip_position_ids,
                    interpolate_pos_encoding=True,
                    use_rope=True,
                    cu_seqlens=torch.tensor([0, numel], dtype=torch.int32),
                    # Passed to match the shipped call. It does not change the
                    # output shape here: with cu_seqlens set, the tower always
                    # takes the per-image branch and `last_hidden_state` comes
                    # back as a LIST, whatever this flag says
                    # (modeling_paddleocr_vl.py:1682-1688).
                    return_pooler_output=False)
    # The tower returns a BaseModelOutputWithPooling; `last_hidden_state` is the
    # merged, projected sequence the LM consumes (after mlp_AR).
    #
    # With cu_seqlens set the encoder takes its per-image branch, so this is a
    # LIST of [P, hidden] tensors, one per image -- which is also why the
    # projector below takes a list. Unwrapping it to a tensor here would take
    # the projector's other branch and merge the 2x2 blocks in a different
    # order (cosine ~0.77 against a correct graph, shape unchanged).
    feats = getattr(out, "last_hidden_state", None)
    if feats is None:
        feats = out[0] if isinstance(out, (tuple, list)) else out
    if not isinstance(feats, list):
        feats = [feats.squeeze(0)]

    # The bmodel's vit graph ends *after* the 2x2 merge projector (`mlp_AR`),
    # which the reference keeps on the LM side. Applying it here is what makes
    # the two tensors comparable; skipping it would compare 1152-dim tower
    # output against 1024-dim merged output and look like a huge mismatch.
    from _paddleocr_vl_ref.configuration_paddleocr_vl import PaddleOCRVisionConfig
    # Projector(text_config, vision_config): it owns pre_norm at the tower's
    # hidden size and projects to the LM's hidden size.
    projector = modeling.Projector(cfg, cfg.vision_config)
    proj_weights = {k[len("mlp_AR."):]: v for k, v in sd.items()
                    if k.startswith("mlp_AR.")}
    pmissing, punexpected = projector.load_state_dict(proj_weights, strict=True)
    if pmissing:
        print(f"projector missing keys: {pmissing}", file=sys.stderr)
    projector.eval()
    with torch.no_grad():
        # A LIST of one tensor, because that is what the shipped model passes:
        # with `vision_return_embed_list=True` the tower returns a list, and
        # `Projector.forward` then takes its list branch, which merges 2x2 blocks
        # with `rearrange("(t h p1 w p2) d -> (t h w) (p1 p2 d)")`. Passing a
        # bare tensor instead takes the *other* branch, whose flat
        # `view(-1, 4*hidden)` groups tokens differently -- same shape, different
        # values, cosine 0.75 against a correct graph. Stage A2 hit exactly this
        # and read it as another converter defect.
        feats = projector(feats, [tuple(grid[0].tolist())])[0]
    # The list branch already returns [(patches/4), text_hidden] in the merged
    # order; the bmodel declares [1, patches/4, text_hidden], so only the batch
    # axis is added here.
    if feats.dim() == 2:
        feats = feats.unsqueeze(0)
    print(f"reference features {tuple(feats.shape)}  (bmodel declares "
          f"[1, patches/4, text_hidden_size])", file=sys.stderr)

    np.savez(args.out, features=feats.float().numpy(),
             pixel_values=pixel_values.numpy(), grid=grid.numpy())
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
