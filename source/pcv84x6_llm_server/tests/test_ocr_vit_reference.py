"""Pin the two reference-side defects that made stage A blame the converter.

Stage A reported the compiled vit at cosine 0.369 against "the reference" and
concluded the converter had a long-standing structural bug. The converter was
fine. The reference tool had two errors, and each on its own is enough to make a
correct bmodel look broken:

1. **the vision rotary was never enabled.** ``PaddleOCREncoder.forward`` does
   ``use_rope = (use_rope is True) and ...``, so the default ``False`` selects
   the *non-rope* attention branch. No exception, no warning -- just a tower
   without positional rotation.
2. **the projector was called with a tensor, not a list.** The shipped model
   passes a list (``vision_return_embed_list=True``), which selects the 2x2 merge
   branch. The tensor branch uses a flat ``view(-1, 4*hidden)`` and groups the
   patches differently -- same output shape, cosine 0.75 against a correct graph.

Both are silent, so they are pinned here by source inspection: the tests assert
the *call sites* pass what the model needs, because that is the only thing that
distinguishes the two branches at this level.
"""

from __future__ import annotations

from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "ocr"


@pytest.mark.parametrize("name", ["vit_reference.py", "vit_reference_layers.py"])
def test_reference_enables_vision_rope(name):
    """The tower must be called with use_rope=True and a cu_seqlens.

    Without both, the encoder silently skips the vision rotary and the reference
    stops being a reference.
    """
    src = (TOOLS / name).read_text(encoding="utf-8")
    assert "use_rope=True" in src, (
        f"{name} does not enable the vision rotary; the encoder defaults to "
        "use_rope=False and then never applies it")
    assert "cu_seqlens" in src, (
        f"{name} does not pass cu_seqlens; use_rope without it raises, and "
        "omitting both silently disables rotary")


@pytest.mark.parametrize("name", ["vit_reference.py", "vit_reference_layers.py"])
def test_projector_is_called_with_a_list(name):
    """The 2x2 merge branch is only reachable through a list argument.

    ``vit_reference_layers.py`` passes a literal list; ``vit_reference.py``
    normalises the tower output into one first, so the test accepts either the
    literal call or the normalisation that feeds it.
    """
    src = (TOOLS / name).read_text(encoding="utf-8")
    assert "projector([" in src or "isinstance(feats, list)" in src, (
        f"{name} calls the projector without a list; the tensor branch merges "
        "the 2x2 blocks in a different order and disagrees with a correct graph")


@pytest.mark.parametrize("name", ["vit_reference.py", "vit_reference_layers.py"])
def test_grid_is_never_inferred_from_the_patch_count(name):
    """A square patch count does not name a square grid.

    576 patches is 24x24, 12x48 and 48x12 at once. The grid decides the rotary
    table and the 2x2 merge grouping, so a wrong guess leaves every tensor shape
    correct and only the values wrong -- 0.77 instead of 1.0 on an identical
    input. The tools must therefore take the grid explicitly.
    """
    src = (TOOLS / name).read_text(encoding="utf-8")
    assert "int(round(n ** 0.5))" not in src and "int(round(numel ** 0.5))" not in src, (
        f"{name} infers the grid from the patch count; pass it instead")


def test_reference_takes_the_tower_list_output():
    """The tower returns a list when cu_seqlens is set, and so does the projector."""
    src = (TOOLS / "vit_reference.py").read_text(encoding="utf-8")
    assert "isinstance(feats, list)" in src, (
        "the per-image branch returns a list of [P, hidden]; treating it as a "
        "tensor silently takes the projector's other merge branch")


def test_reference_layers_records_the_rope_tables():
    """The rotary table must be dumped, or 'is rope right' is unanswerable."""
    src = (TOOLS / "vit_reference_layers.py").read_text(encoding="utf-8")
    assert "visual.rotary_pos_emb.cos" in src
    assert "visual.rotary_pos_emb.sin" in src


def test_reference_layers_records_the_interpolated_position_table():
    """The position-embedding interpolation is the geometry the bmodel bakes in."""
    src = (TOOLS / "vit_reference_layers.py").read_text(encoding="utf-8")
    assert "align_corners=False" in src, (
        "the reference must interpolate the position table the way HF does; "
        "align_corners=True moves every sampled position")
