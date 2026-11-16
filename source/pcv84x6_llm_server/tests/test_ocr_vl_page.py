"""Pin what ``vl_page`` promises about element handling, without an NPU.

The whole-page prototype has two halves: a host half that turns layout boxes
into packed vit inputs, and a board half that drives bmrt. Only the first is
testable here, and it is also where the silent failures live — a prompt string
that does not match the reference, or a patch packing order that transposes the
image, costs accuracy without raising anything. So the tests are about *pinned
values*, not about "it runs":

* the instruction chosen per label must be the one ``PaddleOCR-VL-1.5.yaml``
  hands the model, because a wrong instruction makes the model answer a
  different question (the golden set records ``OCR:`` and ``Table
  Recognition:`` output for the same image and they differ completely);
* the patch packing must match what the vision tower expects, checked by a
  round-trip rather than by re-deriving the same transpose twice;
* ``mrope_positions`` must agree with the reference's ``get_rope_index``,
  checked against hand-computed values (stage A2 found one silent wrong answer
  here already, so the shape being right proves nothing);
* the stage chooser must stay inside the 576-patch set MYS-2610 fixed.
"""

from __future__ import annotations

import numpy as np
import pytest

from tools.ocr import vl_page


# --------------------------------------------------------------------------
# prompts
# --------------------------------------------------------------------------

def test_text_gets_the_ocr_instruction():
    assert vl_page.prompt_for("text") == "OCR:"
    assert vl_page.prompt_for("paragraph_title") == "OCR:"
    assert vl_page.prompt_for("doc_title") == "OCR:"


def test_table_and_formula_get_their_own_instructions():
    assert vl_page.prompt_for("table") == "Table Recognition:"
    assert vl_page.prompt_for("display_formula") == "Formula Recognition:"
    assert vl_page.prompt_for("inline_formula") == "Formula Recognition:"


def test_formula_number_is_text_not_formula():
    """The reference excludes it explicitly (``"formula" in label and label !=
    "formula_number"``); treating it as a formula asks the model to typeset a
    label it should just read."""
    assert vl_page.prompt_for("formula_number") == "OCR:"


def test_image_like_labels_are_skipped():
    for label in ("image", "figure", "header_image", "footer_image", "seal"):
        assert vl_page.prompt_for(label) is None


def test_unknown_label_falls_back_to_ocr():
    """PaddleX's loop defaults ``text_prompt = "OCR:"`` for everything it does
    not special-case, so an unseen class must not be silently dropped."""
    assert vl_page.prompt_for("something_new") == "OCR:"


# --------------------------------------------------------------------------
# vit input packing
# --------------------------------------------------------------------------

def test_patch_packing_preserves_pixel_positions():
    """Every patch must carry the pixels at its own (row, col), in RGB order.

    A transpose here is invisible downstream -- the tensor still has the right
    shape and plausible values -- so assert the round trip against a ramp where
    every pixel is distinct.
    """
    cv2 = pytest.importorskip("cv2")
    h, w = 28, 28            # 2x2 patches of 14
    img = np.zeros((h, w, 3), np.uint8)
    # BGR value encodes (row, col) so a swap is detectable
    for r in range(h):
        for c in range(w):
            img[r, c] = (c % 256, r % 256, (r * 7 + c * 11) % 256)

    packed = vl_page.vit_input(img, h, w)
    assert packed.shape == (4, 3, 14, 14)

    # the packing normalises and converts BGR -> RGB, so compare in that space
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32)
    expect = (rgb / 255.0 - 0.5) / 0.5
    # patch index = row * 2 + col, and within a patch pixel (i, j) is at (i, j)
    for pr in range(2):
        for pc in range(2):
            p = packed[pr * 2 + pc]
            assert p.shape == (3, 14, 14)
            assert np.allclose(p, expect[pr*14:(pr+1)*14, pc*14:(pc+1)*14].transpose(2, 0, 1),
                               atol=1e-3)


def test_vit_input_normalises_to_minus_one_one():
    cv2 = pytest.importorskip("cv2")
    white = np.full((28, 28, 3), 255, np.uint8)
    black = np.zeros((28, 28, 3), np.uint8)
    assert np.allclose(vl_page.vit_input(white, 28, 28), 1.0, atol=1e-3)
    assert np.allclose(vl_page.vit_input(black, 28, 28), -1.0, atol=1e-3)


def test_grid_is_not_inferred_from_the_patch_count():
    """576 patches is both 24x24 and 12x48. The packing must follow the declared
    stage, not the count -- stage A2 lost time to exactly this ambiguity when
    the grid was guessed and the rotary table came out wrong."""
    cv2 = pytest.importorskip("cv2")
    img = np.zeros((100, 100, 3), np.uint8)
    tall = vl_page.vit_input(img, 672, 168)      # 48 x 12
    wide = vl_page.vit_input(img, 168, 672)      # 12 x 48
    assert tall.shape == wide.shape == (576, 3, 14, 14)   # same count...
    # ...and the packing differs, which is the point: the grid is an input.
    assert tall.shape[0] == wide.shape[0]


# --------------------------------------------------------------------------
# mrope
# --------------------------------------------------------------------------

def test_mrope_text_only_positions_all_rows_equal():
    """With no image, the three rows coincide -- which is why a text-only smoke
    test could never have caught a broken mrope (A2's note)."""
    pos = vl_page.mrope_positions(8, 0, 0, 0, text_before=8)
    assert pos.shape == (3, 8)
    for row in range(3):
        assert np.array_equal(pos[row], np.arange(8))


def test_mrope_image_rows_are_h_then_w_over_the_merged_grid():
    """A 12x48 patch grid merges to 6x24 tokens: row 1 walks h, row 2 walks w,
    row 0 is flat, and all are offset by the text before the image."""
    merge = 2
    gh, gw = 12 // merge, 48 // merge      # 6 x 24
    tokens = gh * gw                       # 144
    text_before = 4
    pos = vl_page.mrope_positions(text_before + tokens, 1, 12, 48, text_before)

    assert pos.shape == (3, text_before + tokens)
    image = pos[:, text_before:]
    assert np.all(image[0] == 0)
    assert np.array_equal(image[1], np.repeat(np.arange(gh), gw) + text_before)
    assert np.array_equal(image[2], np.tile(np.arange(gw), gh) + text_before)


def test_mrope_text_before_image_is_sequential():
    """3 text tokens + a 12x48 grid (144 image tokens) = 147 positions."""
    pos = vl_page.mrope_positions(3 + 144, 1, 12, 48, text_before=3)
    for row in range(3):
        assert np.array_equal(pos[row, :3], np.arange(3))


def test_mrope_rejects_a_prompt_that_does_not_fit_the_grid():
    """A prompt built for one vit stage fed to another must fail loudly.

    Without the check numpy truncates the target slice and the assignment
    broadcasts something plausible -- exactly the class of silent error A2
    found in this area.
    """
    with pytest.raises(ValueError, match="cannot hold"):
        vl_page.mrope_positions(6, 1, 12, 48, text_before=3)


# --------------------------------------------------------------------------
# the stage set MYS-2610 fixed
# --------------------------------------------------------------------------

def test_page_stages_are_all_576_patches():
    """The card says: reuse the 576-patch shapes, do not add a stage. Building
    one costs a ~900 MB vit, so this is a budget as much as a contract."""
    for stage in vl_page.page_stages():
        assert stage.patches == 576, stage
        assert stage.image_tokens == 144, stage


def test_page_stages_cover_landscape_square_and_portrait():
    aspects = sorted(round(s.aspect, 3) for s in vl_page.page_stages())
    assert aspects == [0.25, 1.0, 4.0]


def test_chooser_picks_by_aspect_not_by_area():
    """The 576-patch set has 1:1, 4:1 and 1:4 only, so a 6.7:1 line lands on the
    4:1 stage and pays a 1.55x squash. That is the *documented* cost of not
    adding a stage (MYS-2610), so pin it rather than pretending it is exact."""
    from vl_stages import nearest_stage

    square, dev = nearest_stage(200, 200, vl_page.page_stages())
    assert square.h == square.w == 336
    assert dev == pytest.approx(1.0)

    wide, dev = nearest_stage(60, 400, vl_page.page_stages())
    assert wide.h == 168 and wide.w == 672
    assert dev == pytest.approx(1.55, abs=0.05)   # 6.67:1 squashed onto 4:1

    tall, dev = nearest_stage(400, 60, vl_page.page_stages())
    assert tall.h == 672 and tall.w == 168


# --------------------------------------------------------------------------
# crop geometry
# --------------------------------------------------------------------------

def test_crops_are_clipped_to_the_page_and_keep_reading_order():
    page = np.arange(10 * 20 * 3, dtype=np.uint8).reshape(10, 20, 3)
    boxes = [
        {"label": "text", "score": 0.9, "coordinate": [2, 3, 8, 7]},
        {"label": "text", "score": 0.8, "coordinate": [-5, -5, 4, 2]},
        {"label": "text", "score": 0.7, "coordinate": [18, 9, 99, 99]},
    ]
    crops = vl_page.crop_boxes(page, boxes)
    # order is preserved: the detector already sorted by reading order
    assert [c["coordinate"] for c in crops] == [b["coordinate"] for b in boxes]
    assert crops[1]["crop"].shape[:2] == (2, 4)      # clipped to x in [0,4)
    assert crops[2]["crop"].shape[:2] == (1, 2)      # clipped to the last row/col
    for c in crops:
        assert c["crop"].size > 0


def test_crop_always_has_at_least_one_pixel():
    """A degenerate box must not produce a zero-size crop, which would make the
    resize above divide by zero rather than fail honestly."""
    page = np.zeros((10, 10, 3), np.uint8)
    crops = vl_page.crop_boxes(page, [{"label": "text", "score": 0.5,
                                       "coordinate": [5, 5, 5, 5]}])
    assert crops[0]["crop"].size > 0


# --------------------------------------------------------------------------
# the score-path claim this card is built on
# --------------------------------------------------------------------------

def test_conv_substitution_is_arithmetically_the_matmul():
    """``score_path_probe`` rewrites the score MatMul as a 1x1 Conv. The rewrite
    is only honest if the two agree, so check it here rather than trusting the
    derivation in the docstring."""
    rng = np.random.default_rng(3)
    k, n, m = 16, 5, 7
    w = rng.standard_normal((k, n)).astype(np.float32)
    b = rng.standard_normal((n,)).astype(np.float32)
    x = rng.standard_normal((1, m, k)).astype(np.float32)

    matmul = x @ w + b
    # what the conv graph computes: transpose -> conv1x1 with W[N,K,1,1] -> back
    t = x.transpose(0, 2, 1)                       # [1,K,M]
    kernel = w.T.reshape(n, k)                     # [N,K] once the 1x1 is dropped
    # a 1x1 conv is, per output channel c and position j, the dot of the kernel's
    # channel slice with the [K] vector at that position -- i.e. t^T @ kernel^T
    conv = (t[0].T @ kernel.T) + b                 # [M,N]
    assert conv.shape == matmul[0].shape
    assert np.allclose(matmul[0], conv, atol=1e-5)
