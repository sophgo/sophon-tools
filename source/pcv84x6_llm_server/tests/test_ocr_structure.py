#!/usr/bin/env python3
"""Unit tests for the structure pipeline's post-processing and page assembly.

These are host tests: they need numpy and, for the two older cases,
onnxruntime -- but not the board, not the bmodels, and not paddle. The
on-hardware numbers live in ``docs/ocr-structure.md``; what is pinned here is
the part that would silently go wrong on a re-export.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "tools" / "ocr"))

import layout_postprocess as post  # noqa: E402
import structure_page as page  # noqa: E402
import table_postprocess as tables  # noqa: E402

IMG_DIR = Path(__file__).resolve().parent / "data" / "ocr" / "img"


# --- layout post-processing -------------------------------------------------

def test_iou_uses_plus_one_convention():
    """PaddleX's ``iou`` adds 1 to the intersection and both extents.

    The convention is legacy (VOC-style) and easy to "fix" while tidying; doing
    so changes which boxes survive the layout NMS.
    """
    a = [0, 0, 10, 10]
    b = [0, 0, 10, 10]
    assert post.iou(a, b) == pytest.approx(1.0)
    # identical boxes of side 10: inter = 11*11, union = 11*11 + 11*11 - 11*11
    assert post.iou([0, 0, 9, 9], [0, 0, 9, 9]) == pytest.approx(1.0)
    # half-overlap, worked by hand with the +1 rule
    got = post.iou([0, 0, 9, 9], [5, 0, 14, 9])
    assert got == pytest.approx((5 * 10) / (100 + 100 - 50), rel=1e-6)


def test_multiclass_nms_uses_plain_iou():
    """The cut-out NMS is ONNX's, which does *not* use the +1 rule.

    Using PaddleX's ``iou`` inside it swapped 13 of 100 kept rows on one of the
    test images during the build, so the two conventions are pinned separately.
    """
    boxes = np.array([[0, 0, 10, 10], [0, 0, 10, 10]], np.float32)
    scores = np.array([[0.9, 0.5]], np.float32)      # one class, two anchors
    rows = post._multiclass_nms(boxes, scores)
    # Perfectly overlapping, so plain IoU = 1.0 > 0.6 -> one survives.
    assert len(rows) == 1
    assert rows[0][1] == pytest.approx(0.9)


def test_rescale_boxes_swaps_hw_correctly():
    """x/y scale by the width factor, y by the height factor."""
    boxes = np.array([[100.0, 200.0, 300.0, 400.0]], np.float32)
    sf = np.array([0.5, 0.25], np.float32)   # 2x vertical, 4x horizontal
    got = post.rescale_boxes(boxes, sf)
    assert got[0].tolist() == pytest.approx([400.0, 400.0, 1200.0, 800.0])


def test_label_list_matches_both_models():
    assert len(post.LABELS) == 23
    assert "table" in post.LABELS
    # the merge-mode table is keyed by this label space
    for cls in post.MERGE_MODE_STRUCTURE_V3:
        assert 0 <= cls < len(post.LABELS)


def test_merge_mode_drops_contained_boxes():
    """A "large" class box containing another is dropped."""
    # cls 0 (paragraph_title) is "large" in PP-StructureV3's config.
    rows = [
        {"cls_id": 0, "label": "paragraph_title", "score": 0.9,
         "coordinate": [0, 0, 100, 100], "order": 1},
        {"cls_id": 2, "label": "text", "score": 0.8,
         "coordinate": [10, 10, 90, 90], "order": 2},
    ]
    boxes = np.array([[r["cls_id"], r["score"], *r["coordinate"]] for r in rows],
                     np.float32)
    contains, contained = post.check_containment(boxes)
    assert contained[1] == 1 and contains[0] == 1


# --- table post-processing --------------------------------------------------

def _chars():
    return tables.load_chars(
        Path(__file__).resolve().parent / "data" / "ocr" / "slanet_inference.yml")


def test_table_dict_has_sentinels_and_merged_td():
    """50 classes = 48 dict entries + sos + eos, with ``<td>`` folded."""
    chars = _chars()
    assert len(chars) == 50
    assert chars[0] == "sos" and chars[-1] == "eos"
    # merge_no_span_structure replaces the bare <td> with the closed form
    assert "<td></td>" in chars
    assert "<td>" not in chars


def test_table_decode_stops_at_first_eos_only_after_index_zero():
    """Index 0 is sos: it is skipped, not treated as a terminator."""
    chars = _chars()
    eos, sos = chars.index("eos"), chars.index("sos")
    td = chars.index("<td></td>")
    probs = np.zeros((5, len(chars)), np.float32)
    probs[0, sos] = 1.0
    probs[1, td] = 1.0
    probs[2, eos] = 1.0
    probs[3, td] = 1.0          # must not appear
    probs[4, td] = 1.0
    html, cells, _score = tables.decode(probs, None, chars, (488, 488), (488, 488))
    assert html.count("<td></td>") == 1


def test_table_preprocess_pads_zero_in_normalised_space():
    """The pad value is 0 in *normalised* space.

    Three plausible routes and they decode differently (1 / 6 / 5 table rows on
    the merged test crop). This pins the one PaddleX's runner actually feeds,
    captured at PaddleStaticRunner.__call__: content normalised first, then a
    canvas of exact zeros. A "config-faithful" tidy-up to 127.5 regresses it.
    """
    cv2 = pytest.importorskip("cv2", reason="this compares against OpenCV")

    img = np.full((100, 200, 3), 255, np.uint8)
    x, padded, ori = tables.preprocess(img)
    assert x.shape == (1, 3, 488, 488)
    resized_h = padded[1]
    bottom = x[0, :, resized_h + 5, :]
    # exact zeros, not (0 - mean)/std
    assert np.allclose(bottom, 0.0), bottom[:, 0].tolist()
    # and the content region is normalised, not raw
    assert x[0, :, 0, 0].max() < 5.0


def test_cell_scales_uses_min_ratio():
    """``_get_bbox_scales`` for SLANet_plus divides by the smaller ratio."""
    # padded 400x300, original 800x300 -> ratio_w 0.5, ratio_h 1.0 -> min 0.5
    w_scale, h_scale = tables.cell_scales((400, 300), (800, 300))
    assert w_scale == pytest.approx(800) and h_scale == pytest.approx(600)


# --- page assembly ----------------------------------------------------------

def test_is_markdown_expressible_rejects_spans():
    assert page.is_markdown_expressible("<table><tr><td>a</td></tr></table>")
    assert not page.is_markdown_expressible(
        '<table><tr><td colspan="2">a</td></tr></table>')
    assert not page.is_markdown_expressible(
        '<table><tr><td rowspan="2">a</td></tr></table>')


def test_html_to_markdown_shape():
    md = page.html_to_markdown(
        "<table><tr><td>a</td><td>b</td></tr>"
        "<tr><td>1</td><td>2</td></tr></table>")
    lines = md.splitlines()
    assert lines[0] == "| a | b |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| 1 | 2 |"


def _page():
    return page.StructurePage(layout_run=None, table_run=None,
                              ocr_recognise=None, chars=[])


def test_fill_cells_matches_on_iou_then_distance():
    """PaddleX's rule: lowest (1-IoU, distance) wins.

    The line sits inside the left cell and merely touches the container, so
    IoU picks the left cell even though the container also contains it.
    """
    cells = [
        [0, 0, 100, 0, 100, 50, 0, 50],       # container, area 5000
        [0, 0, 50, 0, 50, 50, 0, 50],         # left  (area 2500)
        [50, 0, 100, 0, 100, 50, 50, 50],     # right (area 2500)
    ]
    lines = [("hello", 0.9, [(10, 10), (40, 10), (40, 40), (10, 40)])]
    filled = _page().fill_cells(None, cells, lines)
    assert filled[1] == "hello"
    assert filled[0] == "" and filled[2] == ""


def test_fill_cells_never_drops_text_outside_every_cell():
    """A line that touches no cell must still land somewhere.

    The previous implementation dropped such lines (`continue`), silently
    losing text -- review caught it as a departure from PaddleX, which assigns
    every OCR box to its nearest cell.
    """
    cells = [[0, 0, 100, 0, 100, 50, 0, 50]]
    # far below the only cell, overlapping nothing
    lines = [("outside", 0.9, [(10, 500), (90, 500), (90, 540), (10, 540)])]
    filled = _page().fill_cells(None, cells, lines)
    assert "outside" in filled[0], filled


def test_fill_cells_concatenates_multiple_lines_in_order():
    cells = [[0, 0, 200, 0, 200, 50, 0, 50]]
    lines = [("a", 0.9, [(5, 5), (40, 5), (40, 40), (5, 40)]),
             ("b", 0.9, [(60, 5), (100, 5), (100, 40), (60, 40)])]
    filled = _page().fill_cells(None, cells, lines)
    assert filled[0] == "a b"


def test_to_markdown_emits_html_for_merged_tables():
    blocks = {"blocks": [
        {"kind": "text", "text": "标题"},
        {"kind": "table", "html": '<table><tr><td colspan="2">x</td></tr></table>'},
        {"kind": "skip"},
    ]}
    md = page.to_markdown(blocks)
    assert "标题" in md
    assert "colspan" in md          # HTML, not a pipe table
    assert "---" not in md


def test_to_markdown_emits_pipe_table_when_expressible():
    blocks = {"blocks": [
        {"kind": "table",
         "html": "<table><tr><td>a</td><td>b</td></tr></table>"},
    ]}
    md = page.to_markdown(blocks)
    assert md.strip().splitlines()[0] == "| a | b |"


def test_table_images_exist_and_are_small():
    """The two generated Chinese tables, at the size budget the card sets."""
    for name in ("cn_table_merged.png", "cn_table_simple.png"):
        p = IMG_DIR / name
        assert p.is_file(), f"{name} missing"
        assert p.stat().st_size <= 300 * 1024, f"{name} over the 300 KB budget"


# --- SLANet unrolling -------------------------------------------------------

def _slanet_onnx():
    """The official export, if it has been fetched. Skipped otherwise.

    The weights are not in git (they go to dfss), so a checkout without them
    still has to pass the suite.
    """
    p = Path(os.environ.get("SLANET_ONNX", ""))
    if not p.is_file():
        pytest.skip("SLANET_ONNX not set to the official SLANet_plus.onnx")
    return p


def test_unroll_removes_the_loop_and_the_dynamic_trigger():
    """After unrolling there is no Loop and no OneHot left.

    Those are the two things that stop this model compiling: tpu-mlir cannot
    convert a Loop at all, and it lowers OneHot into a TPU_DYNAMIC subnet which
    wedges the NPU (verified with a two-node ArgMax+OneHot graph).
    """
    src = _slanet_onnx()
    onnx = pytest.importorskip("onnx")
    import slanet_unroll as unroll

    model = onnx.load(str(src))
    unroll.hoist_constants(model.graph)
    unroll.inline_captures(model.graph)
    unroll.unroll(model.graph, 8)
    unroll.replace_onehot_with_gather(model.graph)

    ops = {n.op_type for n in model.graph.node}
    assert "Loop" not in ops
    assert "OneHot" not in ops
    assert not any(n.op_type == "If" for n in model.graph.node)


def test_unroll_rejects_a_loop_whose_arity_does_not_match():
    """The 9-carried-input / 8-carried-output asymmetry must be caught.

    The shipped export drops the `done` flag from the Loop's outputs. If a
    future export changes the numbers again, the unroller has to fail loudly
    rather than wire the wrong tensors together.
    """
    src = _slanet_onnx()
    onnx = pytest.importorskip("onnx")
    import slanet_unroll as unroll

    model = onnx.load(str(src))
    loop = [n for n in model.graph.node if n.op_type == "Loop"][0]
    while len(loop.output) > 1:
        loop.output.pop()
    loop.output.pop()          # leave zero carried outputs
    with pytest.raises(SystemExit):
        unroll.unroll(model.graph, 4)


def test_reading_order_sorts_top_to_bottom_then_left_to_right():
    """PaddleX does not trust the detector's order; it re-sorts by row then column.

    The detector put the footer paragraph first and the title last on
    cn_notice.png, so without this the page reads backwards.
    """
    blocks = [
        {"box": [156, 983, 1019, 1085], "text": "footer"},
        {"box": [157, 92, 889, 152], "text": "title"},
        {"box": [154, 239, 287, 277], "text": "salutation"},
    ]
    order = [b["text"] for b in page.reading_order(blocks)]
    assert order == ["title", "salutation", "footer"]


def test_reading_order_keeps_same_row_left_to_right():
    blocks = [
        {"box": [500, 100, 700, 140], "text": "right"},
        {"box": [50, 104, 300, 144], "text": "left"},
    ]
    assert [b["text"] for b in page.reading_order(blocks)] == ["left", "right"]
