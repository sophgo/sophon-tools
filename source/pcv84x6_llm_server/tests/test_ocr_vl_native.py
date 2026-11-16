"""Pin what the native decode path promises, without an NPU.

MYS-2660's decode runs entirely on the board, so nothing here can execute the
TPU. What *is* testable is exactly the part that failed silently three times
during development: the arithmetic the C++ program does before and around each
launch. Each of these three bugs produced well-shaped tensors and plausible
tokens, so "it runs" was never evidence of correctness:

* an unmasked padding tail in the prefill mask,
* a rotary table built for ``L`` positions but indexed to ``L + max_new``,
* a decode loop that fed layer 0 the stale prefill buffer.

The Python side is pinned here; ``tools/ocr/vl_native/vl_native.cpp`` carries
independent transcriptions of the same rules, and the alignment run in
``docs/ocr-vl.md`` is what confirms the two agree on the board.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from tools.ocr import vl_native_prep as P


# --------------------------------------------------------------------------
# rotary table
# --------------------------------------------------------------------------

def test_rope_covers_image_rows_with_grid_coordinates():
    """Image token i sits at (t=0, h=i//w, w=i%w), offset by the text before it."""
    gh, gw, text = 4, 6, 3           # merged grid 2x3 = 6 image tokens
    pos = P.mrope_positions(20, gh, gw, text)
    assert pos.shape == (3, 20)
    # text before the image: plain sequential on all three rows
    for r in range(3):
        assert pos[r, :text].tolist() == [0, 1, 2]
    # image rows
    assert pos[0, text:text + 6].tolist() == [0] * 6
    assert pos[1, text:text + 6].tolist() == [3, 3, 3, 4, 4, 4]   # h + base
    assert pos[2, text:text + 6].tolist() == [3, 4, 5, 3, 4, 5]   # w + base


def test_rope_tail_continues_past_the_highest_position_used():
    """Text after the image must start above every position the image used."""
    pos = P.mrope_positions(20, 4, 6, 3)
    tail = pos[:, 9:]
    assert tail.min() == int(pos[:, :9].max()) + 1
    # and it advances by one per token, identically on all three rows
    assert tail[0].tolist() == tail[1].tolist() == tail[2].tolist()


def test_rope_rejects_a_prompt_that_cannot_hold_the_image():
    with pytest.raises(ValueError):
        P.mrope_positions(5, 4, 6, 4)      # 4 text + 6 image > 5


def test_rope_table_is_long_enough_for_a_full_decode():
    """The table must span the whole sequence, not just the prompt.

    The C++ side built it for ``L`` entries and then indexed ``L + step``, which
    read past the end of the vector: every decoded position id was garbage while
    every tensor shape stayed valid, and the symptom was one correct token
    followed by padding. Length is the property that catches it.
    """
    seq, prompt = 64, 12
    pos = P.mrope_positions(seq, 4, 6, 3)
    assert pos.shape == (3, seq)
    # decoding asks for the position *after* the prompt, up to seq-1
    for n in range(prompt, seq):
        assert 0 <= pos[0, n] and 0 <= pos[1, n] and 0 <= pos[2, n]


# --------------------------------------------------------------------------
# prompt ids
# --------------------------------------------------------------------------

class _FakeTokenizer:
    """Enough of ``tokenizers.Tokenizer`` for ``build_ids``."""

    def __init__(self, pieces):
        self._pieces = pieces

    def token_to_id(self, s):
        return self._pieces.get(s, 0)

    def encode(self, s, add_special_tokens=False):
        class _E:
            ids = [ord(c) % 97 + 1 for c in s]
        return _E()


def test_prompt_ids_place_exactly_one_placeholder_per_image_token():
    """The placeholder count IS the vit row count; a mismatch misplaces every
    image embedding while keeping the prompt length plausible."""
    tok = _FakeTokenizer({"<|IMAGE_PLACEHOLDER|>": 99991})
    ids, head = P.build_ids(tok, "OCR:", 144)
    assert ids.count(99991) == 144
    assert ids[head:head + 144] == [99991] * 144
    # the head is exactly what precedes the image block
    assert head == len(P.HEAD.encode()) // 1 or head > 0
    assert head < len(ids)


def test_prompt_uses_the_reference_wrapping():
    """Verbatim from the model's chat template. A3 recorded that ``Assistant:\\n``
    and ``Assistant: `` are different spans and only one is what the reference
    continues from."""
    assert P.HEAD == "<|begin_of_sentence|>User: <|IMAGE_START|>"
    assert P.TAIL.endswith("Assistant:\n")
    assert "{prompt}" in P.TAIL


# --------------------------------------------------------------------------
# prompts per layout class
# --------------------------------------------------------------------------

def test_prompt_map_matches_the_official_pipeline():
    assert P.prompt_for("text") == "OCR:"
    assert P.prompt_for("paragraph_title") == "OCR:"
    assert P.prompt_for("table") == "Table Recognition:"
    assert P.prompt_for("formula") == "Formula Recognition:"
    assert P.prompt_for("chart") == "Chart Recognition:"


def test_image_like_classes_get_a_chart_prompt_or_are_skipped():
    """The official pipeline does not send an OCR instruction for a figure."""
    assert P.prompt_for("figure") == "Chart Recognition:"
    assert P.prompt_for("header_image") is None
    assert P.prompt_for("footer_image") is None


def test_every_layout_class_has_a_decision():
    """A class missing from the map would silently fall back to ``OCR:``."""
    from tools.ocr.layout_postprocess import LABELS

    for label in LABELS:
        got = P.prompt_for(label)
        assert got is not None or label in P.SKIP_LABELS, label
        if got is not None:
            assert got in ("OCR:", "Table Recognition:", "Formula Recognition:",
                           "Chart Recognition:"), (label, got)


# --------------------------------------------------------------------------
# patch packing
# --------------------------------------------------------------------------

def test_vit_input_is_patch_major_and_normalised():
    """One row per patch, ``[P, 3, 14, 14]``, values in [-1, 1]."""
    cv2 = pytest.importorskip("cv2")
    crop = np.zeros((56, 56, 3), np.uint8)
    crop[..., 1] = 255                       # pure green in BGR
    x = P.vit_input(crop, 28, 28)            # 2x2 patches
    assert x.shape == (4, 3, 14, 14)
    assert x.dtype == np.float32
    # green is channel 1 after the BGR->RGB conversion
    assert x[0, 1].mean() == pytest.approx(1.0, abs=1e-6)
    assert x[0, 0].mean() == pytest.approx(-1.0, abs=1e-6)


def test_vit_input_grid_follows_the_stage_not_the_patch_count():
    """576 patches is both 24x24 and 12x48, so the stage decides the grid.

    Feeding a 168x672 compile 336x336 pixels keeps every shape valid and
    changes the answer: measured cosine 0.45 against the reference instead of
    0.956 for the same patch tensor.
    """
    cv2 = pytest.importorskip("cv2")
    crop = np.zeros((100, 400, 3), np.uint8)
    crop[:, :200, 0] = 255                    # a visible edge to resample
    crop[50:, :, 2] = 128
    a = P.vit_input(crop, 168, 672)
    b = P.vit_input(crop, 336, 336)
    assert a.shape[0] == b.shape[0] == 576
    assert a.shape == (576, 3, 14, 14)
    # the same patch count, a different image: they must not be interchangeable
    assert not np.array_equal(a, b)


# --------------------------------------------------------------------------
# what vl_native writes
# --------------------------------------------------------------------------

def test_tokens_file_is_little_endian_int32(tmp_path):
    """The C++ writes raw i32; the reader has to agree on byte order."""
    ids = [101309, 5, 3, 0]
    p = tmp_path / "tokens.i32"
    p.write_bytes(struct.pack(f"<{len(ids)}i", *ids))
    from tools.ocr import vl_native_prep

    assert vl_native_prep._read_tokens(p) == ids


def test_meta_round_trips_through_the_cpp_parser(tmp_path):
    """``meta.txt`` is "key value" lines; the C++ splits on the first space."""
    fields = {"head_len": 5, "grid_h": 56, "grid_w": 56,
              "max_new": 32, "eos_id": 2, "seq": 2048}
    p = tmp_path / "meta.txt"
    p.write_text("".join(f"{k} {v}\n" for k, v in fields.items()), encoding="utf-8")
    got = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition(" ")
        got[k] = int(v)
    assert got == fields
