#!/usr/bin/env python3
"""Record the reference VLM preprocessing output, so the C++ port can be checked.

Image preprocessing is pure host software -- decode, `smart_resize`, Pillow's
bicubic resize, normalise, patchify -- so this needs no board and no NPU. Any
workstation with the reference stack can regenerate the expected values.

    tools/gen_vision_golden.py <model config dir> [out.json]

The reference is whatever the service actually calls today
(`app/engine/native.py`: qwen_vl_utils.process_vision_info ->
Qwen2VLImageProcessor with do_resize=False), so the expected values cannot
drift from the behaviour being replaced.

Needs: torch, torchvision, transformers, pillow, qwen_vl_utils.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys

import numpy as np
from PIL import Image

# Constants the service uses (kept in step with app/engine/native.py).
PATCH_SIZE = 16
SPATIAL_MERGE = 2
TEMPORAL_PATCH_SIZE = 2
GRID_PER_SIDE = 48
MIN_PIXELS = 4 * 32 * 32


def fixtures(directory: str) -> list[str]:
    """Deterministic images covering the awkward paths.

    Written once and reused: the goldens must be reproducible from the same
    bytes, so these are generated from a fixed seed rather than downloaded.
    """
    os.makedirs(directory, exist_ok=True)
    rng = np.random.default_rng(424242)

    def save(arr, name, **kw):
        Image.fromarray(arr, "RGB").save(os.path.join(directory, name), **kw)

    # Smooth gradient: shows up any coefficient error in the resampler.
    g = np.zeros((97, 131, 3), np.uint8)
    g[:, :, 0] = np.linspace(0, 255, 131, dtype=np.uint8)[None, :]
    g[:, :, 1] = np.linspace(0, 255, 97, dtype=np.uint8)[:, None]
    g[:, :, 2] = (np.arange(131)[None, :] * 5 + np.arange(97)[:, None] * 3) % 256
    save(g, "gradient.png")

    # Noise: defeats any smoothing shortcut.
    save(rng.integers(0, 256, (53, 67, 3), dtype=np.uint8), "noise.png")
    # JPEG: exercises the decoder, and a non-integer down-scale.
    save(rng.integers(0, 256, (120, 160, 3), dtype=np.uint8), "photo.jpg", quality=88)
    # Palette and RGBA: both must flatten to RGB exactly as Pillow does.
    Image.fromarray(rng.integers(0, 256, (40, 40, 3), dtype=np.uint8), "RGB") \
        .convert("P").save(os.path.join(directory, "palette.png"))
    rgba = np.dstack([rng.integers(0, 256, (48, 48, 3), dtype=np.uint8),
                      np.full((48, 48), 160, np.uint8)])
    Image.fromarray(rgba, "RGBA").save(os.path.join(directory, "rgba.png"))
    # Extreme aspect ratio, and an image smaller than one patch grid cell.
    save(rng.integers(0, 256, (20, 800, 3), dtype=np.uint8), "wide.png")
    Image.new("RGB", (7, 5), (12, 200, 90)).save(os.path.join(directory, "tiny.png"))
    # Greyscale.
    Image.fromarray(rng.integers(0, 256, (101, 149, 3), dtype=np.uint8), "RGB") \
        .convert("L").save(os.path.join(directory, "gray.png"))

    return sorted(os.listdir(directory))


def reference_one(cfg_dir: str, path: str, max_pixels: int,
                  min_pixels: int = MIN_PIXELS, rgba_white_background: bool = False):
    """Exactly what app/engine/native.py does, minus the NPU."""
    from qwen_vl_utils import process_vision_info
    from transformers import AutoProcessor

    img = Image.open(path)
    if not rgba_white_background:
        img = img.convert("RGB")
    content = [{"type": "image", "image": img,
                "min_pixels": min_pixels, "max_pixels": max_pixels}]
    pil_images, _, _ = process_vision_info(
        [{"role": "user", "content": content}],
        image_patch_size=PATCH_SIZE, return_video_kwargs=True)
    proc = AutoProcessor.from_pretrained(cfg_dir, trust_remote_code=True)
    inputs = proc(text=["<|vision_start|><|image_pad|><|vision_end|>"],
                  images=pil_images, do_resize=False, return_tensors="pt")
    pv = inputs.pixel_values.float().numpy()
    return {
        "grid_thw": [int(v) for v in inputs.image_grid_thw[0].tolist()],
        "input_ids": [int(v) for v in inputs.input_ids[0].tolist()],
        "resized_wh": [int(pil_images[0].width), int(pil_images[0].height)],
        "pixel_values": pv,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config_dir")
    ap.add_argument("out", nargs="?", default="tests/vision_golden.json")
    ap.add_argument("--fixtures", default="tests/vision_fixtures")
    ap.add_argument("--reuse-fixtures", action="store_true",
                    help="read the checked-in image bytes without regenerating them")
    ap.add_argument("--max-pixels", type=int, default=256 * PATCH_SIZE * PATCH_SIZE)
    ap.add_argument("--min-pixels", type=int, default=MIN_PIXELS)
    ap.add_argument("--rgba-white-background", action="store_true",
                    help="WeMM's direct qwen_vl_utils image entry composites RGBA onto white")
    ap.add_argument("--fused-normalize", action="store_true",
                    help="label Torchvision fused rescale/normalize output (VL embedding)")
    args = ap.parse_args()

    import PIL
    import qwen_vl_utils
    import torch
    import transformers

    names = sorted(os.listdir(args.fixtures)) if args.reuse_fixtures else fixtures(args.fixtures)
    cases = []
    for name in names:
        path = os.path.join(args.fixtures, name)
        ref = reference_one(args.config_dir, path, args.max_pixels,
                            args.min_pixels, args.rgba_white_background)
        pv = ref["pixel_values"]
        cases.append({
            "name": name,
            "source_wh": list(Image.open(path).size),
            "grid_thw": ref["grid_thw"],
            "resized_wh": ref["resized_wh"],
            "patches": int(np.prod(ref["grid_thw"])),
            "shape": list(pv.shape),
            # Exact float32 bits: the comparison is bitwise, not "close enough".
            "pixel_values_b64": base64.b64encode(
                np.ascontiguousarray(pv, dtype="<f4").tobytes()).decode(),
        })

    # Pillow's resampler on its own, so a resize bug is distinguishable from a
    # pipeline bug. Ratios include up-, down- and 1:1 scaling.
    resize_cases = []
    src_path = os.path.join(args.fixtures, "gradient.png")
    src = np.asarray(Image.open(src_path).convert("RGB"))
    for tw, th in [(37, 23), (160, 100), (640, 400), (13, 41), (1, 1), (262, 194)]:
        out = np.asarray(Image.fromarray(src).resize((tw, th)))
        resize_cases.append({
            "src": "gradient.png",
            "dst": [tw, th],
            "b64": base64.b64encode(
                np.ascontiguousarray(out, dtype=np.uint8).tobytes()).decode(),
        })

    # smart_resize on its own: it decides the patch count, so it is worth
    # pinning separately from the pixels.

    payload = {
        "generated_by": "tools/gen_vision_golden.py",
        "versions": {
            "transformers": transformers.__version__,
            "torch": torch.__version__,
            "pillow": PIL.__version__,
            "qwen_vl_utils": getattr(qwen_vl_utils, "__version__", "unknown"),
            "numpy": np.__version__,
        },
        "config": {
            "patch_size": PATCH_SIZE,
            "spatial_merge": SPATIAL_MERGE,
            "temporal_patch_size": TEMPORAL_PATCH_SIZE,
            "grid_per_side": GRID_PER_SIDE,
            "min_pixels": args.min_pixels,
            "max_pixels": args.max_pixels,
            "fused_normalize": args.fused_normalize,
            "rgba_white_background": args.rgba_white_background,
        },
        "resize_cases": resize_cases,
        "cases": cases,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f)
        f.write("\n")
    print(f"wrote {args.out}: {len(cases)} images, {len(resize_cases)} resize cases")
    for c in cases:
        print(f"  {c['name']:14} {c['source_wh'][0]}x{c['source_wh'][1]}"
              f" -> resized {c['resized_wh'][0]}x{c['resized_wh'][1]}"
              f" grid {c['grid_thw']} patch_vec {c['shape'][-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
