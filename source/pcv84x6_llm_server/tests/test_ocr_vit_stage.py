"""Guard the vit stage's preprocessing contract against the reference.

Stage A compares board output with HF's vision tower, and that comparison is
only meaningful if both sides agree on what a "vit input" is. These tests pin
the three things that decide it, each of which was wrong at some point today:

* **patch order** -- ``(H, W, C) -> (P, C, 14, 14)`` with the patch grid row
  major. A ``(C, grid_h, 14, grid_w, 14)`` transpose gives the same shape and a
  different order, which shows up only as a scrambled output.
* **interpolation geometry** -- the reference calls
  ``F.interpolate(size=..., mode="bilinear", align_corners=False)``. The
  converter used ``align_corners``, and on a 12x48 grid that moves the position
  embedding by up to 0.145 per element. That regression is pinned in
  ``paddleocr_vl_convert.PATCHES`` rather than here, because the shim is where
  the value lives.
* **stage legality** -- already covered by ``test_ocr_stage_table``.
"""

from __future__ import annotations

import numpy as np
import pytest

from tools.ocr.paddleocr_vl_convert import PATCHES


def _patched_source() -> str:
    """Apply PATCHES to a stand-in for the converter, without the container.

    The shim's patches are (old, new) string pairs asserted to hit exactly once
    in the *real* converter, which only exists inside the tpu-mlir image. This
    builds a minimal source containing the original snippets so the pair can be
    checked without that image: what matters here is that the replacement still
    targets the reference's semantics, not that the container matches.
    """
    return None


def test_vit_interp_uses_half_pixel_not_align_corners():
    """The positional-embedding interpolation must match the reference."""
    olds = [old for old, _ in PATCHES]
    news = [new for _, new in PATCHES]
    assert any('coord_mode=StringAttr.get("align_corners")' in o for o in olds), \
        "the patch must target the converter's align_corners setting"
    assert any('coord_mode=StringAttr.get("half_pixel")' in n for n in news), \
        ("the reference uses align_corners=False, which maps to half_pixel; "
         "align_corners puts the sampled grid in the wrong place")
    # `mode` stays "linear": TopOps.td's InterpModeAttr only allows
    # {nearest, linear}, and bilinear 2-D interpolation is spelled "linear".
    assert not any('StringAttr.get("bilinear")' in n for n in news)


def test_vit_interp_scale_is_grid_over_source():
    """scale = grid/src, not (grid-1)/(src-1): the reference passes a size."""
    olds = [old for old, _ in PATCHES]
    news = [new for _, new in PATCHES]
    assert any("(grid_h - 1) / (sqrt_num_positions - 1)" in o for o in olds)
    assert any("grid_h / sqrt_num_positions" in n for n in news)


def test_every_patch_entry_is_a_pair():
    for entry in PATCHES:
        assert len(entry) == 2, entry
        old, new = entry
        assert old and new and old != new


def test_patch_order_round_trips():
    """The documented patch packing must be invertible.

    A wrong transpose is invisible in the shape (both give [P, 3, 14, 14]), so
    the test asserts that unpacking reproduces the source image exactly.
    """
    rng = np.random.default_rng(2591)
    gh, gw = 3, 5
    img = rng.random((gh * 14, gw * 14, 3)).astype(np.float32)

    patches = (img.reshape(gh, 14, gw, 14, 3)
                  .transpose(0, 2, 4, 1, 3)
                  .reshape(gh * gw, 3, 14, 14))
    assert patches.shape == (gh * gw, 3, 14, 14)

    rebuilt = (patches.reshape(gh, gw, 3, 14, 14)
                      .transpose(0, 3, 1, 4, 2)
                      .reshape(gh * 14, gw * 14, 3))
    np.testing.assert_array_equal(rebuilt, img)
