"""The vit stage table has to agree with the reference's own resize rule.

Stage A's proposal is "compile the vision tower at several shapes and pick the
closest at runtime". That only means anything if the chooser reproduces the grid
the reference would have used for the same crop, so the resize is pinned against
the numbers already in ``tests/data/ocr/golden.json`` -- 42x58 for
``ui_status.png`` and 76x66 for ``table_stats.png``. If ``smart_resize`` here
drifted from the model's, those two would move and this file fails.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.ocr.vl_stages import (FACTOR, MAX_PIXELS, MIN_PIXELS, STAGES,
                                nearest_stage, smart_resize)

GOLDEN = Path(__file__).parent / "data" / "ocr" / "golden.json"


def _golden_grids() -> dict[str, tuple[int, int]]:
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    grids: dict[str, tuple[int, int]] = {}
    for case in data["paddleocr_vl"]["cases"]:
        t, h, w = case["image_grid_thw"][0]
        grids.setdefault(case["image"], (h, w))
    return grids


def test_smart_resize_reproduces_the_golden_grids():
    """The two recorded golden images resize to exactly the recorded grids."""
    # Image sizes, from tests/data/ocr/img (PIL reports (w, h)).
    sizes = {"ui_status.png": (800, 600), "table_stats.png": (1240, 1400)}
    grids = _golden_grids()
    for name, (w, h) in sizes.items():
        h_bar, w_bar = smart_resize(h, w)
        got = (h_bar // 14, w_bar // 14)
        assert got == grids[name], f"{name}: {got} != golden {grids[name]}"


def test_smart_resize_keeps_total_pixels_in_range():
    """Every stage the table compiles must be a legal resize result."""
    for height, width in ((600, 800), (1400, 1240), (336, 336), (112, 896)):
        h_bar, w_bar = smart_resize(height, width)
        total = h_bar * w_bar
        assert MIN_PIXELS <= total <= MAX_PIXELS
        assert h_bar % FACTOR == 0 and w_bar % FACTOR == 0


def test_every_stage_is_a_legal_resize():
    for stage in STAGES:
        assert stage.h % FACTOR == 0 and stage.w % FACTOR == 0, stage
        assert MIN_PIXELS <= stage.h * stage.w <= MAX_PIXELS, stage
        # patch count is what the bmodel's first input dim is
        assert stage.patches == (stage.h // 14) * (stage.w // 14)


def test_stage_chooser_matches_a_square_crop_exactly():
    """A 1:1 crop must land on a 1:1 stage, not merely a same-patch one."""
    stage, deviation = nearest_stage(336, 336)
    assert stage.aspect == pytest.approx(1.0)
    assert deviation == pytest.approx(1.0)


def test_stage_chooser_is_symmetric():
    """A transposed crop must pick the transposed stage."""
    wide, _ = nearest_stage(112, 448)
    tall, _ = nearest_stage(448, 112)
    assert (wide.h, wide.w) == (tall.w, tall.h)


def test_stage_chooser_prefers_aspect_over_patch_count():
    """Two stages with the same patches differ only by aspect; pick right.

    168x672 and 672x168 are both 576 patches, so patch count cannot choose
    between them -- the aspect ratio has to.
    """
    stage, deviation = nearest_stage(168, 672)
    assert (stage.h, stage.w) == (168, 672)
    assert deviation == pytest.approx(1.0)

    stage, deviation = nearest_stage(672, 168)
    assert (stage.h, stage.w) == (672, 168)
    assert deviation == pytest.approx(1.0)


def test_stages_cover_the_reference_grids_of_the_golden_images():
    """No golden image may be pushed onto a stage more than 1.4x off aspect.

    ``ui_status.png`` is the worst case in the current table: its reference grid
    is 42x58 (aspect 1.38) and the nearest stage is 1:1, a 1.38x squash. That is
    precisely what stage A has to report rather than hide, so the bound is
    asserted at the measured value.
    """
    for name, (w, h) in (("ui_status.png", (800, 600)),
                         ("table_stats.png", (1240, 1400))):
        stage, deviation = nearest_stage(h, w)
        assert deviation <= 1.4, f"{name} -> {stage} costs {deviation:.2f}x"
