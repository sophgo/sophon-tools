#!/usr/bin/env python3
"""The vit stage table for PaddleOCR-VL-1.5 on CV84X6.

The reference vision tower has one positional grid baked in at compile time
(``gen_vit_mlir`` interpolates ``position_embedding`` to
``max_shape``), so a static bmodel can only accept one patch count. Stage A of
MYS-2591 asked whether that can be turned into a *set* of shapes that covers
real element crops: this file is the table and the chooser.

Two things are computed here and nowhere else:

* **The grid for a crop**, exactly as ``smart_resize`` would: 28 px multiples,
  total pixels inside [min_pixels, max_pixels], aspect preserved.
* **Which compiled grid to run it on.** A compiled grid whose own aspect ratio
  is far from the crop's would need the crop squashed into it, which is the
  accuracy loss stage A exists to measure. The chooser therefore scores by
  aspect-ratio deviation first and by area fit second.

Everything is integer arithmetic on multiples of 28 so the board and the host
reference cannot disagree about a rounding.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

#: From ``preprocessor_config.json``: patch 14, merge 2, so the resize factor is
#: 28 and the patch grid is (h/14, w/14) with h, w multiples of 28.
PATCH_SIZE = 14
MERGE_SIZE = 2
FACTOR = PATCH_SIZE * MERGE_SIZE

MIN_PIXELS = 112896   # 336 x 336
MAX_PIXELS = 1003520  # from the shipped preprocessor_config.json


@dataclass(frozen=True)
class Stage:
    """One compiled vit shape."""

    h: int          # resized image height in pixels
    w: int          # resized image width in pixels

    @property
    def grid(self) -> tuple[int, int]:
        return self.h // PATCH_SIZE, self.w // PATCH_SIZE

    @property
    def patches(self) -> int:
        """Patch count is what the bmodel's input tensor is shaped by."""
        gh, gw = self.grid
        return gh * gw

    @property
    def image_tokens(self) -> int:
        """After the 2x2 spatial merge the LLM sees patches/4 tokens."""
        return self.patches // (MERGE_SIZE * MERGE_SIZE)

    @property
    def aspect(self) -> float:
        return self.w / float(self.h)

    def __str__(self) -> str:
        gh, gw = self.grid
        return f"{self.h}x{self.w} (grid {gh}x{gw}, {self.patches} patches)"


#: The stage set. Chosen to cover the aspect ratios real layout elements take
#: on, at the area the reference would pick for each, rather than to cover
#: "every shape": each entry costs a full vit compile.
#:
#: 1:1 through 8:1 horizontally and vertically, plus an explicit small square
#: for short lines and a large square for full-page images. The extremes come
#: from the golden set: ``vertical_text.png`` needs a 1:1.4 crop of tall text,
#: ``en_report.png`` has body lines at 34.8:1 which go to PP-OCR, not the VLM.
STAGES: tuple[Stage, ...] = (
    Stage(336, 336),    # 576 patches   aspect 1.000
    Stage(252, 504),    # 648           aspect 2.000
    Stage(196, 588),    # 588           aspect 3.000
    Stage(168, 672),    # 576           aspect 4.000
    Stage(168, 840),    # 720           aspect 5.000
    Stage(140, 840),    # 600           aspect 6.000
    Stage(140, 980),    # 700           aspect 7.000
    Stage(140, 1120),   # 800           aspect 8.000
    Stage(504, 252),    # 648           aspect 0.500
    Stage(588, 196),    # 588           aspect 0.333
    Stage(672, 168),    # 576           aspect 0.250
    Stage(840, 168),    # 720           aspect 0.200
    Stage(840, 140),    # 600           aspect 0.167
    Stage(980, 140),    # 700           aspect 0.143
    Stage(1120, 140),   # 800           aspect 0.125
    Stage(1064, 924),   # 5016          aspect 0.868 -- the golden table's own grid
)


def smart_resize(height: int, width: int,
                 min_pixels: int = MIN_PIXELS,
                 max_pixels: int = MAX_PIXELS,
                 factor: int = FACTOR) -> tuple[int, int]:
    """Verbatim ``smart_resize`` from the model's own image processor."""
    if height < factor:
        width = round((width * factor) / height)
        height = factor
    if width < factor:
        height = round((height * factor) / width)
        width = factor
    if max(height, width) / min(height, width) > 200:
        raise ValueError(f"aspect ratio {max(height, width) / min(height, width):.0f}"
                         " exceeds the 200 the reference allows")
    h_bar = round(height / factor) * factor
    w_bar = round(width / factor) * factor
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = math.floor(height / beta / factor) * factor
        w_bar = math.floor(width / beta / factor) * factor
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = math.ceil(height * beta / factor) * factor
        w_bar = math.ceil(width * beta / factor) * factor
    return h_bar, w_bar


def nearest_stage(height: int, width: int,
                  stages: Sequence[Stage] = STAGES) -> tuple[Stage, float]:
    """Pick the compiled stage whose aspect ratio is closest to the crop's.

    Returns the stage and the squash factor it costs. Aspect ratio is the
    primary key on purpose: the grid has to be *the same grid* the reference
    would interpolate the positional embedding to, and a stage whose aspect is
    off by 20% shifts that interpolation by more than any area difference ever
    would. Ties break towards the stage needing less padding.
    """
    target = smart_resize(height, width)
    aspect = target[1] / float(target[0])
    patches = (target[0] // PATCH_SIZE) * (target[1] // PATCH_SIZE)
    best = None
    for stage in stages:
        # Squash is symmetric: running a WxH crop on an HxW stage costs the same.
        deviation = max(stage.aspect / aspect, aspect / stage.aspect)
        pad = abs(stage.patches - patches) / float(patches)
        key = (round(deviation, 6), pad)
        if best is None or key < best[0]:
            best = (key, stage, deviation, patches)
    assert best is not None
    return best[1], best[2]


def coverage(crops: Iterable[tuple[int, int]],
             stages: Sequence[Stage] = STAGES) -> list[dict]:
    """Report what each crop would cost, for the stage-A report's tables."""
    rows = []
    for h, w in crops:
        target = smart_resize(h, w)
        stage, deviation = nearest_stage(h, w, stages)
        rows.append({
            "crop": f"{w}x{h}",
            "reference_grid": f"{target[0] // PATCH_SIZE}x{target[1] // PATCH_SIZE}",
            "reference_patches": (target[0] // PATCH_SIZE) * (target[1] // PATCH_SIZE),
            "stage": str(stage),
            "aspect_deviation": round(deviation, 4),
            "padded_patches": stage.patches,
        })
    return rows


if __name__ == "__main__":
    print(f"{'crop':>12}  {'ref grid':>9}  {'patches':>7}  "
          f"{'stage':<38} {'dev':>6}  {'padded':>6}")
    golden = [(600, 800), (1400, 1240)]
    elements = [(336, 336), (112, 448), (112, 224), (56, 224), (448, 112),
                (224, 56), (224, 224), (112, 112), (896, 112), (112, 896)]
    for row in coverage(golden + elements):
        print(f"{row['crop']:>12}  {row['reference_grid']:>9}  "
              f"{row['reference_patches']:>7}  {row['stage']:<38} "
              f"{row['aspect_deviation']:>6}  {row['padded_patches']:>6}")
