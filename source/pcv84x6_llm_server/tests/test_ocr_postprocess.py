"""The OCR pipeline's post-processing, against the recorded NPU-side tensors.

``golden.json`` says what the pipeline *should* produce; ``postprocess.npz``
holds the det probability maps and rec softmax outputs an x86 onnxruntime run
produced from the same ONNX graphs the bmodels were compiled from. Feeding those
tensors to ``app/engine/ocr_ppocr`` is therefore a complete test of everything
between the NPU and the response -- resize/crop geometry, DB decode, unclip,
width-tier selection, CTC -- with no NPU and no bmodel.

Three properties are asserted, and they are different claims:

* **the boxes are the golden's**, to the pixel. The tolerance is zero because
  the arithmetic is deterministic: rounding differences here are not noise, they
  are a different rounding *rule*, and the acceptance criterion on the board is
  a 3 px budget for the bmodel's own numerical drift -- not for ours.
* **the text is the golden's**, exactly, for all 103 lines. f16 storage of the
  rec logits is what makes the fixture 7 MB instead of 543 MB, so
  ``test_rec_logits_survive_f16`` proves the quantisation is lossless for the
  decoder rather than assuming it.
* **the parameters come from the model's own config**, which is the one place
  the reference pipeline and sophon-demo disagree. ``test_ppocr_v6_thresholds``
  fails if somebody swaps in v4's constants.

What is *not* asserted here is agreement with the official ``paddleocr``
package; ``tests/test_ocr_assets.py`` owns that, because it needs the golden's
paddleocr block and a different normalisation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "ocr"
IMG = DATA / "img"
CONFIG = Path(__file__).resolve().parent.parent / "model-config" / "ppocr_v6"

np = pytest.importorskip("numpy")
pytest.importorskip("cv2", reason="the OCR pipeline needs OpenCV")
pytest.importorskip("pyclipper", reason="DB's unclip needs pyclipper")

from app.engine.ocr_ppocr import (  # noqa: E402
    OcrConfig,
    _order_clockwise,
    ctc_decode,
    crop_quad,
    det_input,
    det_postprocess,
    load_config,
    reading_order,
    rec_input,
    rec_width_for,
)


@pytest.fixture(scope="module")
def cfg() -> OcrConfig:
    return load_config(CONFIG)


@pytest.fixture(scope="module")
def golden() -> dict:
    return json.loads((DATA / "golden.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tensors() -> dict:
    path = DATA / "postprocess.npz"
    # Checked in, with its digest recorded in tests/data/PROVENANCE.md. A skip
    # here would let the whole tensor comparison vanish from a "passing" run.
    assert path.exists(), (
        f"{path} is missing; it is a checked-in fixture (see "
        f"tests/data/PROVENANCE.md)")
    with np.load(path) as archive:
        return {name: archive[name] for name in archive.files}


@pytest.fixture(scope="module")
def images() -> dict:
    import cv2

    out = {}
    for path in sorted(IMG.glob("*.png")):
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        assert bgr is not None, path
        out[path.name] = bgr
    return out


def _det_entry(golden, name):
    return next(e for e in golden["ppocr"]["det"]["images"] if e["image"] == name)


def _rec_entry(golden, name):
    return next(e for e in golden["ppocr"]["rec"]["images"] if e["image"] == name)


# ---------------------------------------------------------------------------
# the tensor fixture itself
# ---------------------------------------------------------------------------
def test_the_tensor_golden_covers_every_image_and_line(golden, tensors):
    """A fixture that lost a case would quietly shrink the test's reach."""
    images = {e["image"] for e in golden["ppocr"]["det"]["images"]}
    det = {name.split("/", 1)[1] for name in tensors if name.startswith("det/")}
    assert det == images, f"det tensors missing {images - det} / stale {det - images}"

    expected = {f"rec/{e['image']}/{i}"
                for e in golden["ppocr"]["rec"]["images"]
                for i in range(len(e["lines"]))}
    rec = {name for name in tensors if name.startswith("rec/")}
    assert rec == expected, (
        f"rec tensors missing {len(expected - rec)}, stale {len(rec - expected)}")


def test_det_maps_are_the_region_the_postprocess_reads(golden, tensors):
    """Not the padded 736x736 canvas: only [0:resize_h, 0:resize_w] holds signal.

    Recording the padded tensor would let a test pass while the crop indices
    were wrong, because the padding is all zeros and would score as "no text".
    """
    for entry in golden["ppocr"]["det"]["images"]:
        array = tensors[f"det/{entry['image']}"]
        # The golden records `resize` as [height, width] (see make_golden).
        resize_h, resize_w = entry["resize"]
        assert array.shape == (resize_h, resize_w), entry["image"]
        assert array.dtype == np.float32
        # A real map, not a constant: the whole point of the DB decode is that
        # it has structure.
        assert float(array.max()) > 0.5, f"{entry['image']}: map has no confident pixel"
        assert float(array.min()) >= 0.0


def test_rec_logits_survive_f16(tensors, cfg, golden):
    """The fixture stores rec outputs as f16; the decoder must not notice.

    Checked rather than assumed: 543 MB of f32 in a repository is not an option,
    and the claim "f16 is enough for argmax" is exactly the kind of claim that
    is true until a line sits on a decision boundary.
    """
    mismatches = []
    worst = 0.0
    for entry in golden["ppocr"]["rec"]["images"]:
        for index, line in enumerate(entry["lines"]):
            probs = tensors[f"rec/{entry['image']}/{index}"].astype(np.float32)
            text, score = ctc_decode(probs, cfg.labels)
            if text != line["text"]:
                mismatches.append((entry["image"], index, text, line["text"]))
            worst = max(worst, abs(score - line["confidence"]))
    assert not mismatches, f"{len(mismatches)} lines decode differently from f16"
    assert worst < 0.01, f"confidence drifts by {worst}"


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------
def test_det_boxes_match_the_golden_to_the_pixel(golden, tensors, cfg):
    """Boxes, box scores and count, for all seven images.

    Exact equality is the right bar: the pipeline is pure arithmetic on a fixed
    tensor, so anything else means this code and the golden generator disagree
    about a rule (a rounding direction, a clip bound, a coordinate scale). The
    board's 3 px budget is for the *bmodel's* numerics, not for this.
    """
    for entry in golden["ppocr"]["det"]["images"]:
        shape = (entry["size"][1], entry["size"][0], *entry["resize"])
        boxes, scores = det_postprocess(tensors[f"det/{entry['image']}"], shape, cfg)
        assert len(boxes) == entry["box_count"], (
            f"{entry['image']}: {len(boxes)} boxes, golden has {entry['box_count']}")
        got = np.asarray(boxes, dtype=np.float64)
        want = np.asarray(entry["boxes"], dtype=np.float64)
        assert got.shape == want.shape, entry["image"]
        delta = np.abs(got - want)
        assert float(delta.max()) == 0.0, (
            f"{entry['image']}: boxes differ by up to {delta.max():.3f} px")
        # The boxes above are exact; the *scores* are compared with slack, and
        # the reason is measurable rather than defensive: golden.json records
        # onnxruntime 1.16.3 (its `provenance` block), while the fixture beside
        # it was produced here under 1.31.1, and the two builds' convolution
        # kernels differ in the last few float bits. Recomputing the golden with
        # either version reproduces the boxes to the pixel and the scores to
        # ~3e-4, so that is the tolerance -- tight enough that a real change in
        # the score rule (a different mask, a different clip) still fails.
        assert np.allclose(scores, entry["box_scores"], atol=1e-3), (
            f"{entry['image']}: box scores differ by "
            f"{float(np.abs(np.array(scores) - np.array(entry['box_scores'])).max()):.2e}")


def test_det_postprocess_scales_back_to_the_source_image(golden, tensors, cfg):
    """Every box has to land inside the original image, not the 736 canvas.

    This is the failure a resize scale bug produces: boxes that look plausible
    but sit in padded coordinates, so the crops are blank and every line decodes
    empty. Asserted separately from equality so the *meaning* of the numbers is
    pinned even if the golden is regenerated.
    """
    for entry in golden["ppocr"]["det"]["images"]:
        src_w, src_h = entry["size"]
        shape = (src_h, src_w, *entry["resize"])
        boxes, _ = det_postprocess(tensors[f"det/{entry['image']}"], shape, cfg)
        for box in boxes:
            for x, y in box:
                assert 0.0 <= x <= src_w, f"{entry['image']}: x={x} outside 0..{src_w}"
                assert 0.0 <= y <= src_h, f"{entry['image']}: y={y} outside 0..{src_h}"
        # And the widest box must come close to the *source* width, which is
        # only true when the boxes were scaled back: a version that left them in
        # the resized canvas would stop at 736 or below.
        widest = max(max(p[0] for p in box) for box in boxes)
        assert widest > src_w * 0.5, (
            f"{entry['image']}: widest box reaches only x={widest} of {src_w}; "
            "the boxes look like they were never scaled back to the source")


def test_det_thresholds_come_from_the_model_not_from_v4(golden, cfg):
    """PP-OCRv6's own ``inference.yml`` values, not sophon-demo's v4 constants.

    The demo hardcodes 0.3/0.6/1.5 for v4; v6 ships 0.2/0.45/1.4. Using the
    demo's numbers drops the low-confidence boxes v6 deliberately emits, which
    reads as "the model got worse" rather than as a configuration mistake.
    """
    assert cfg.thresh == pytest.approx(0.2)
    assert cfg.box_thresh == pytest.approx(0.45)
    assert cfg.unclip_ratio == pytest.approx(1.4)
    assert cfg.max_candidates == 3000
    assert cfg.min_size == 3
    # And the config file is where they came from, not a default here.
    raw = json.loads((CONFIG / "ppocr.json").read_text(encoding="utf-8"))
    assert raw["det"]["postprocess"]["thresh"] == cfg.thresh


def test_a_lower_thresh_finds_more_boxes(golden, tensors, cfg):
    """The thresholds have to actually do something, or they are decoration.

    A weaker check than "the boxes match" but a different one: it proves the
    three numbers reach the contour stage rather than being parsed and dropped.
    """
    import dataclasses

    entry = _det_entry(golden, "table_stats.png")
    shape = (entry["size"][1], entry["size"][0], *entry["resize"])
    strict = dataclasses.replace(cfg, thresh=0.5, box_thresh=0.9)
    loose, _ = det_postprocess(tensors[f"det/{entry['image']}"], shape, cfg)
    tight, _ = det_postprocess(tensors[f"det/{entry['image']}"], shape, strict)
    assert len(tight) < len(loose), (
        f"raising the thresholds found {len(tight)} boxes, not fewer than {len(loose)}")


# ---------------------------------------------------------------------------
# cropping and width selection
# ---------------------------------------------------------------------------
def test_crops_are_perspective_warps_not_bounding_boxes(golden, images):
    """A skewed line's crop must be the line, not a tall rectangle around it.

    ``skewed_lines.png`` has a 7-degree line. Its axis-aligned bbox is several
    times the glyph height; warping yields something close to the text's own
    aspect. The golden recorded a bbox version reading
    ``库盘点WarehousenySt`` where the reference reads the whole line, so this is
    the difference between 81 % and 97.9 % agreement.
    """
    entry = _det_entry(golden, "skewed_lines.png")
    bgr = images["skewed_lines.png"]
    # The second box of this image is one of the skewed ones; find the one whose
    # bbox is most elongated so the test follows the data rather than an index.
    best = None
    for box in entry["boxes"]:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        bbox_ratio = (max(xs) - min(xs)) / max(1.0, max(ys) - min(ys))
        if best is None or bbox_ratio < best[0]:
            best = (bbox_ratio, box)
    _ratio, box = best
    crop = crop_quad(bgr, box)
    assert crop is not None
    h, w = crop.shape[:2]
    assert w > h, "a horizontal line's rectified crop is wider than it is tall"
    # The warp sizes the crop by the quadrilateral's own edge lengths, so the
    # aspect must match those -- not the bounding rectangle's.
    pts = _order_clockwise(box)
    expect_w = max(np.linalg.norm(pts[0] - pts[1]), np.linalg.norm(pts[2] - pts[3]))
    expect_h = max(np.linalg.norm(pts[0] - pts[3]), np.linalg.norm(pts[1] - pts[2]))
    assert w == int(expect_w) and h == int(expect_h)


def test_a_degenerate_box_is_refused_rather_than_cropped(images):
    """A zero-area box would make ``getPerspectiveTransform`` singular."""
    bgr = images["ui_status.png"]
    assert crop_quad(bgr, [[0, 0], [0, 0], [0, 0], [0, 0]]) is None
    assert crop_quad(bgr, [[5, 5], [5, 5], [6, 5], [6, 5]]) is None


def test_width_tiers_match_the_golden_for_every_line(golden, cfg):
    """The tier each line ran at, derived from its crop, must be the golden's.

    This is the 640-is-not-enough decision made checkable: ``en_report.png`` has
    34.8:1 lines, and sending those to 640 decodes them as garbage while the
    text comparison above would then fail with no explanation of why.
    """
    for entry in golden["ppocr"]["rec"]["images"]:
        for line in entry["lines"]:
            w, h = line["crop_size"]
            assert rec_width_for(h, w, cfg) == line["width_tier"], (
                f"{entry['image']} line {line['box_index']}: "
                f"{w}x{h} chose a different tier")


@pytest.mark.parametrize("ratio,width", [
    (1.0, 320),     # a single glyph
    (4.0, 320),     # 4.0 x 1.15 = 4.6 <= 6.667
    (5.0, 320),     # 5.0 x 1.15 = 5.75 <= 6.667
    (5.9, 640),     # 5.9 x 1.15 = 6.79 > 6.667 -> the next tier up
    (6.0, 640),
    (11.0, 640),    # 11.0 x 1.15 = 12.65 <= 13.333
    (11.7, 1600),   # 11.7 x 1.15 = 13.46 > 13.333
    (34.8, 1600),   # en_report.png's widest line: clamped to the widest tier
    (100.0, 1600),  # absurd but must not raise or wrap
])
def test_width_selection_table(cfg, ratio, width):
    """Every tier, at and around its cut point, as a table.

    The cut points are ``max_ratio / squash_tolerance`` in aspect terms, so a
    tier's own ``max_ratio`` is where a line would land *without* the tolerance
    and everything just under it moves up. Spelling the boundaries out here
    means a change to either number is visible as a changed expected tier
    rather than as silent re-tiering.
    """
    crop_w = max(2, int(round(48 * ratio)))
    assert rec_width_for(48, crop_w, cfg) == width


def test_the_tolerance_pushes_borderline_lines_up_not_down(cfg):
    """What the 1.15 multiplier is for, stated as the behaviour it produces.

    It is applied *to* the line's ratio, so it makes lines land in the next tier
    sooner, never the narrower one: the point is to stop a ratio that is a
    hair over a cut point from paying twice the time steps for an invisible
    squash. Without it, a 6.667:1 line would choose 640; with it, 6.0:1 already
    does.
    """
    assert cfg.squash_tolerance > 1.0
    # 6.667:1 exactly -- the boundary -- goes to 1600 without the tolerance in
    # the way? No: 6.667 x 1.15 = 7.67 > 6.667, so 640.
    assert rec_width_for(48, int(round(48 * 6.667)), cfg) == 640
    # A ratio just under 320's capacity without the tolerance (6.0) is pushed
    # to 640 by it. That direction is the whole design.
    assert rec_width_for(48, int(round(48 * 6.0)), cfg) == 640
    # A comfortably short line still gets the narrow tier: the tolerance does
    # not push everything up.
    assert rec_width_for(48, int(round(48 * 4.0)), cfg) == 320


# ---------------------------------------------------------------------------
# recognition
# ---------------------------------------------------------------------------
def test_ctc_decode_matches_every_golden_line(golden, tensors, cfg):
    text_hits = 0
    total = 0
    for entry in golden["ppocr"]["rec"]["images"]:
        for index, line in enumerate(entry["lines"]):
            probs = tensors[f"rec/{entry['image']}/{index}"].astype(np.float32)
            text, score = ctc_decode(probs, cfg.labels)
            total += 1
            if text == line["text"]:
                text_hits += 1
            # Two small drifts, both measured: the fixture stores logits as f16
            # (top-1 is unchanged for all 103 lines, see
            # test_rec_logits_survive_f16) and golden.json's confidences came
            # from onnxruntime 1.16.3 rather than this host's 1.31.1. Together
            # they move a line's mean confidence by at most 2.2e-3; the bound is
            # wide enough to say "the same line" and nothing more.
            assert abs(score - line["confidence"]) < 0.01, (
                f"{entry['image']} line {index}: confidence {score} vs "
                f"{line['confidence']}")
    assert text_hits == total, f"{total - text_hits} of {total} lines decode differently"
    # The bar the acceptance criterion names, restated so a regression shows up
    # as a number rather than as "a test failed".
    assert text_hits / total >= 0.98


def test_ctc_decoding_collapses_repeats_and_drops_blank(cfg):
    """The three rules, on a hand-built sequence where each is visible.

    A decoder that skipped the repeat-collapse would emit ``aabb`` for the same
    model output; one that skipped the blank rule would insert whatever class 0
    stands for. Neither is detectable from clean real output, which is why this
    is synthetic.
    """
    classes = 5
    # Time steps: a a <blank> b b b <blank> a  ->  "aba"
    steps = [1, 1, 0, 2, 2, 2, 0, 1]
    probs = np.zeros((len(steps), classes), dtype=np.float32)
    for t, c in enumerate(steps):
        probs[t, c] = 0.9
        probs[t, (c + 1) % classes] = 0.1
    labels = ["<blank>", "a", "b", "c", " "]
    text, score = ctc_decode(probs, labels)
    assert text == "aba"
    # Confidence is the mean over the kept steps (three of them), not over all 8.
    assert score == pytest.approx(0.9)


def test_ctc_decoding_of_an_all_blank_sequence_is_empty(cfg):
    probs = np.zeros((10, 4), dtype=np.float32)
    probs[:, 0] = 1.0
    assert ctc_decode(probs, ["<blank>", "a", "b", " "]) == ("", 0.0)


def test_rec_input_pads_on_the_right_with_zeros(cfg):
    """Right padding, not centred, and zeros rather than a normalised value.

    A centred pad or a pad of ``-mean`` would shift every glyph relative to the
    reference; the recogniser is trained on zero-filled right padding.
    """
    import cv2

    crop = np.full((48, 48, 3), 200, dtype=np.uint8)
    width = 320
    tensor = rec_input(crop, width, cfg)
    assert tensor.shape == (1, 3, 48, width)
    # The resized content occupies the first 48 columns, normalised.
    expect = (200.0 - cfg.rec_mean) * cfg.rec_scale
    assert tensor[0, :, :, 0].mean() == pytest.approx(expect, abs=1e-4)
    assert tensor[0, :, :, width - 1].sum() == 0.0, "the pad must be zeros"


def test_det_input_does_not_upscale_a_small_image(cfg):
    """Shrink-only, as the reference does; two golden images are under 736."""
    bgr = np.full((400, 300, 3), 128, dtype=np.uint8)
    tensor, shape = det_input(bgr, cfg)
    src_h, src_w, resize_h, resize_w = shape
    assert (src_h, src_w) == (400, 300)
    assert (resize_h, resize_w) == (400, 300), "a small image must not be blown up"
    assert tensor.shape == (1, 3, cfg.det_input_side, cfg.det_input_side)
    # The unused region stays zero AFTER normalisation, not grey.
    assert tensor[0, :, -1, :].sum() == 0.0


def test_det_input_downscales_by_the_long_side(cfg):
    """A portrait page: the *height* is the long side, so height becomes 736."""
    bgr = np.full((1754, 1240, 3), 128, dtype=np.uint8)
    _tensor, shape = det_input(bgr, cfg)
    src_h, src_w, resize_h, resize_w = shape
    assert (src_h, src_w) == (1754, 1240)
    ratio = cfg.det_input_side / 1754
    assert resize_h == int(1754 * ratio) == cfg.det_input_side
    assert resize_w == int(1240 * ratio) == 520
    # A landscape page puts the *width* on 736 instead: the rule is the long
    # side, not a fixed axis.
    _t, wide = det_input(np.full((600, 1600, 3), 128, dtype=np.uint8), cfg)
    _sh, _sw, wh, ww = wide
    assert ww == cfg.det_input_side
    assert wh == int(600 * cfg.det_input_side / 1600)


# ---------------------------------------------------------------------------
# reading order
# ---------------------------------------------------------------------------
def test_reading_order_is_top_to_bottom_then_left_to_right():
    def box(x0, y0, x1, y1):
        return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))

    # Two visual lines, the second one's right cell slightly higher than its
    # left -- which is what a slanted photograph produces and what a strict y
    # sort would swap.
    boxes = [
        box(300, 102, 390, 118),   # 0: line A, right
        box(10, 100, 120, 116),    # 1: line A, left
        box(300, 142, 390, 158),   # 2: line B, right
        box(10, 140, 120, 156),    # 3: line B, left
    ]
    assert reading_order(boxes) == [1, 0, 3, 2]


def test_reading_order_is_row_major_across_columns():
    """Two cells at the same height read left-to-right, then the next row.

    This is a deliberate choice, not an oversight: the sort groups by vertical
    centre and then orders within a group by x, which is what PaddleOCR's own
    layout sort does and what a *table* needs -- ``table_stats.png`` is one of
    the golden images, and its rows are only meaningful together. The cost is
    that two-column prose interleaves; detecting columns reliably needs a layout
    model, which this model pair does not have (it has no direction classifier
    either, see model-config/ppocr_v6/README.md), and is documented as a
    limitation of ``/v1/ocr``.

    The alternative -- sorting strictly by y -- is worse on both: it splits a
    table row into fragments whenever one cell sits a few pixels higher.
    """
    def box(x0, y0, x1, y1):
        return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))

    boxes = []
    for i in range(3):
        boxes.append(box(10, 100 + i * 20, 200, 116 + i * 20))    # even: left
        boxes.append(box(400, 104 + i * 20, 600, 120 + i * 20))   # odd: right
    assert reading_order(boxes) == [0, 1, 2, 3, 4, 5], (
        "rows must read left-to-right, and rows must stay in order")


def test_reading_order_tolerates_a_row_that_is_not_level():
    """A photographed table's cells are never at exactly the same y.

    Half a line height of slack is what keeps them in one row; without it every
    scan would read down the left column and then down the right, which is the
    failure mode a strict y sort has.
    """
    def box(x0, y0, x1, y1):
        return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))

    boxes = [
        box(10, 100, 200, 116),    # 0: row 1, left
        box(400, 108, 600, 124),   # 1: row 1, right (8 px lower)
        box(10, 140, 200, 156),    # 2: row 2, left
    ]
    assert reading_order(boxes) == [0, 1, 2]


def test_reading_order_of_an_empty_page_is_empty():
    assert reading_order([]) == []


# ---------------------------------------------------------------------------
# the whole pipeline, wired the way the backend wires it
# ---------------------------------------------------------------------------
class _RecordedGraph:
    """A stand-in for a ``NetEngine`` that returns one recorded tensor.

    The output keeps the **real** shape -- ``(1, 1, side, side)`` for det,
    ``(1, T, C)`` for rec -- because that is where the first board run failed:
    the backend sliced ``[0][0]`` off the 4-D det output, leaving a rank-3
    array, and Sophon's OpenCV then rejected it inside ``findContours`` with a
    ``copyMakeBorder ... _src.dims() <= 2`` assertion that named nothing
    recognisable. A fixture returning a 2-D array would have hidden it, which is
    the whole reason this one does not.
    """

    num_inputs = 1

    def __init__(self, out_shape, payload: np.ndarray) -> None:
        self.input_shapes = [(1, 3, out_shape[-2] if len(out_shape) == 4 else 48,
                              out_shape[-1])]
        self._shape = out_shape
        self._payload = payload
        self.calls = 0

    def run(self, _tensor, *_args):
        self.calls += 1
        return [self._payload.reshape(self._shape).astype(np.float32)]


def test_the_backend_turns_its_graph_output_into_boxes_and_lines(
        golden, tensors, images, cfg, monkeypatch):
    """``OcrBackend._recognise_sync`` end to end, with recorded tensors.

    Everything else in this file tests the pieces; this tests the wiring, and
    the wiring is where the board broke. It runs the real ``OcrBackend`` -- real
    config load, real det pre/post, real crop, real tier choice, real CTC -- with
    the two ``NetEngine``s replaced by the golden's tensors.
    """
    from app.engine import ocr_ppocr

    name = "ui_status.png"
    det_tensor = tensors[f"det/{name}"]
    det_golden = next(e for e in golden["ppocr"]["det"]["images"] if e["image"] == name)
    rec_golden = next(e for e in golden["ppocr"]["rec"]["images"] if e["image"] == name)
    side = cfg.det_input_side

    # One rec graph per tier, each returning the golden logits for the line that
    # will ask for it. The backend creates them lazily by width, so the mapping
    # has to be by width -- which is also what proves the tier selection reached
    # the right engine.
    by_tier: dict[int, list[np.ndarray]] = {}
    for index, line in enumerate(rec_golden["lines"]):
        by_tier.setdefault(line["width_tier"], []).append(
            tensors[f"rec/{name}/{index}"])
    queues = {tier: list(payloads) for tier, payloads in by_tier.items()}

    # A full 736 canvas with the recorded map in its top-left corner: the
    # backend crops it through `shape`, so the padding must be present for the
    # crop to be exercised.
    padded = np.zeros((1, 1, side, side), dtype=np.float32)
    padded[0, 0, :det_tensor.shape[0], :det_tensor.shape[1]] = det_tensor

    backend = ocr_ppocr.OcrBackend.__new__(ocr_ppocr.OcrBackend)
    backend._model_id = "ppocrv6-medium"
    backend._config_dir = str(CONFIG)
    backend._lib_path = "unused"
    backend._dev_id = 0
    backend._gate = None
    import threading
    backend._lock = threading.Lock()
    backend._cv2 = __import__("cv2")
    backend._pyclipper = __import__("pyclipper")
    backend._cfg = cfg
    backend._det = _RecordedGraph((1, 1, side, side), padded)
    backend._rec = {}

    def fake_rec_engine(width: int):
        payload = queues[width].pop(0)
        shape = (1, payload.shape[0], payload.shape[1])
        return _RecordedGraph(shape, payload)

    backend._rec_paths = {tier: Path(f"/nonexistent/{tier}.bmodel")
                          for tier in by_tier}
    monkeypatch.setattr(backend, "_rec_engine", fake_rec_engine)

    result = backend._recognise_sync((IMG / name).read_bytes())

    assert len(result.lines) == len(rec_golden["lines"]), (
        f"{len(result.lines)} lines from {len(rec_golden['lines'])} golden lines; "
        "a difference here means the det map was mis-sliced or the boxes mis-scaled")
    assert (result.width, result.height) == tuple(det_golden["size"]), (
        "the reported image size must come from the decoded image")
    assert result.det_ms >= 0 and result.rec_ms >= 0
    # Every golden line appears, with its box in source coordinates.
    want = sorted(line["text"] for line in rec_golden["lines"] if line["text"])
    got = sorted(line.text for line in result.lines if line.text)
    assert got == want, f"text differs: {got[:3]} vs {want[:3]}"
    for line in result.lines:
        assert len(line.box) == 4
        for x, y in line.box:
            assert 0 <= x <= result.width and 0 <= y <= result.height
    # And `text` is the lines joined, which the API relies on.
    assert result.text == "\n".join(line.text for line in result.lines)


def test_a_det_output_that_cannot_become_a_probability_map_is_refused(cfg):
    """A shape with no 1-wide leading axes says so, naming the shape.

    The backend peels unit axes off the front until it has a rank-2 map, which
    is what [1, 1, H, W], [1, H, W] and [H, W] all reduce to. A graph that
    reported a batch of two -- [2, 1, H, W] -- cannot be reduced that way, and
    silently taking ``[0]`` would answer for one image while claiming to have
    served another. That is the case pinned here.
    """
    from app.engine import ocr_ppocr
    from app.engine.aux_native import AuxNativeError

    backend = ocr_ppocr.OcrBackend.__new__(ocr_ppocr.OcrBackend)
    backend._model_id = "x"
    backend._cfg = cfg
    backend._gate = None
    import threading
    backend._lock = threading.Lock()
    backend._cv2 = __import__("cv2")
    backend._pyclipper = __import__("pyclipper")
    backend._rec = {}
    backend._rec_paths = {}
    # A batch of two: the leading axis is not 1, so it is not a unit axis to
    # peel and the map cannot be recovered.
    backend._det = _RecordedGraph((2, 1, 8, 8), np.zeros(2 * 1 * 8 * 8, dtype=np.float32))

    with pytest.raises(AuxNativeError) as exc:
        backend._recognise_sync((IMG / "ui_status.png").read_bytes())
    assert "二维概率图" in str(exc.value)
    # And the message carries the shape, so the reader can tell which graph.
    assert "(2, 1, 8, 8)" in str(exc.value)


@pytest.mark.parametrize("shape", [(1, 1, 8, 8), (1, 8, 8), (8, 8)])
def test_every_legitimate_det_rank_reduces_to_the_same_map(cfg, shape):
    """The three shapes a real build may report all end up as one HxW map.

    A single-graph det bmodel has always been [1,1,H,W], but tpu-mlir drops unit
    axes for some shapes and a future build may too; the backend accepts all
    three, so the reduction is pinned rather than assumed.
    """
    from app.engine import ocr_ppocr

    payload = np.arange(64, dtype=np.float32).reshape(8, 8)
    backend = ocr_ppocr.OcrBackend.__new__(ocr_ppocr.OcrBackend)
    backend._det = _RecordedGraph(shape, payload.reshape(shape))

    out = backend._det.run(None)[0]
    while out.ndim > 2:
        out = out[0]
    assert out.shape == (8, 8)
    assert np.array_equal(out, payload)
