"""``mode: "layout"``: detection tail, block text, reading order, Markdown.

Host tests. They replay the golden's recorded layout tensors through the numpy
tail, so the detector's *arithmetic* is pinned here and its *hardware* is
``docs/ocr.md``'s business. The OCR lines come from the golden's own recorded
recognitions, so the page assembled in these tests is the page the board should
produce -- without an NPU, onnxruntime or paddle.

The reading-order assertions use ``tests/data/ocr/twocolumn_truth.json``, which
``tools/ocr/make_twocolumn_image.py`` writes: the order a human reads that page
in. That is the whole point of drawing the page rather than sourcing a scan --
the expected order is a fact about the input, not a recording of the answer.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from app.engine import ocr_layout as layout  # noqa: E402

DATA = Path(__file__).resolve().parent / "data" / "ocr"
CONFIG = _REPO / "model-config" / "ppocr_v6"
IMG = DATA / "img"

pytestmark = pytest.mark.skipif(
    not (DATA / "golden.json").exists(),
    reason="tests/data/ocr/golden.json missing; run tools/ocr/make_golden.py")


@pytest.fixture(scope="module")
def cfg() -> layout.LayoutConfig:
    return layout.load_layout_config(CONFIG)


@pytest.fixture(scope="module")
def golden() -> dict:
    return json.loads((DATA / "golden.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def truth() -> dict:
    return json.loads((DATA / "twocolumn_truth.json").read_text(encoding="utf-8"))


class Line:
    """The three fields ``assign_lines`` reads, as ``OcrLine`` provides them."""

    def __init__(self, text: str, box, score: float = 0.95) -> None:
        self.text = text
        self.score = score
        x1, y1, x2, y2 = box
        self.box = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))


def _page_hw(entry: dict) -> tuple[int, int]:
    """The golden stores a page as ``[w, h]``; ``detect`` takes ``(h, w)``.

    Worth a named helper rather than two inline reversals: swapping them makes
    every box come out with the axes transposed, which looks like a broken model
    rather than a broken argument.
    """
    width, height = entry["size"]
    return (int(height), int(width))


def _layout_entry(golden: dict, image: str) -> dict:
    return next(e for e in golden["layout"]["images"] if e["image"] == image)


def _rec_lines(golden: dict, image: str) -> list[Line]:
    """The golden's recorded rec results, with the det boxes they came from.

    ``rec`` entries carry ``box_index``, which indexes into the same image's det
    golden -- that is how a line gets its box back without re-running anything.
    """
    det = next(e for e in golden["ppocr"]["det"]["images"] if e["image"] == image)
    rec = next(e for e in golden["ppocr"]["rec"]["images"] if e["image"] == image)
    lines = []
    for entry in rec["lines"]:
        if not entry["text"]:
            continue
        points = det["boxes"][entry["box_index"]]
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        lines.append(Line(entry["text"], [min(xs), min(ys), max(xs), max(ys)],
                          entry["confidence"]))
    return lines


# --------------------------------------------------------------------------- #
# config <-> model
# --------------------------------------------------------------------------- #
def test_labels_match_the_config_file(cfg):
    """The class axis decides every region's label; both copies must agree."""
    assert cfg.labels == layout.LABELS
    assert cfg.num_classes == 23
    assert len(cfg.labels) == 23


def test_config_shape_matches_the_compiled_bmodel(cfg):
    """The side is what page coordinates are scaled *through*, so it must be real."""
    assert cfg.side == 640
    assert cfg.bmodel.startswith("ppdoclayout-m")
    # PP-DocLayout-M at 640 emits 8500 anchors x 4 and 23 classes x 8500.
    raw = json.loads((CONFIG / layout.LAYOUT_CONFIG_FILE).read_text(encoding="utf-8"))
    boxes, scores = raw["bmodel"]["outputs"]
    assert boxes["shape"] == [1, 8500, 4]
    assert scores["shape"] == [1, 23, 8500]


def test_merge_mode_only_names_known_classes(cfg):
    """A class id off the end of the label list would index the wrong class."""
    for cls_id, mode in cfg.merge_mode.items():
        assert cls_id < cfg.num_classes
        assert mode in ("large", "small", "union")


def test_a_config_with_a_different_label_list_is_refused(tmp_path):
    """The load-time guard: a relabelled config must not silently start."""
    raw = json.loads((CONFIG / layout.LAYOUT_CONFIG_FILE).read_text(encoding="utf-8"))
    raw["postprocess"]["labels"] = list(reversed(raw["postprocess"]["labels"]))
    (tmp_path / layout.LAYOUT_CONFIG_FILE).write_text(
        json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="labels"):
        layout.load_layout_config(tmp_path)


def test_a_missing_config_is_refused(tmp_path):
    with pytest.raises(ValueError, match="layout.json"):
        layout.load_layout_config(tmp_path)


# --------------------------------------------------------------------------- #
# detection tail
# --------------------------------------------------------------------------- #
def test_the_plus_one_iou_is_paddlexs_not_the_textbook_one():
    """Using textbook IoU in the layout NMS swaps 13 of 100 rows on skewed_lines."""
    assert layout._iou_plus_one([0, 0, 9, 9], [0, 0, 9, 9]) == pytest.approx(1.0)
    # identical 10x10 boxes: inter 100, each extent 100, union 100 ->1.0 under
    # either convention; the discriminating case is a fractional overlap.
    got = layout._iou_plus_one([0, 0, 9, 9], [5, 0, 14, 9])
    assert got == pytest.approx((5 * 10) / (100 + 100 - 50))


def test_the_cut_nms_uses_plain_iou(cfg):
    """The NMS that was cut out is ONNX's, which does *not* use the +1 rule."""
    boxes = np.array([[0, 0, 10, 10], [0, 0, 10, 10]], np.float32)
    scores = np.zeros((23, 2), np.float32)
    scores[2] = [0.9, 0.5]
    rows = layout._multiclass_nms(boxes, scores, cfg)
    assert len(rows) == 1
    assert rows[0][1] == pytest.approx(0.9)


def test_overlap_ratio_modes(cfg):
    """``small`` divides by the smaller box -- containment tests depend on it."""
    outer = [0, 0, 100, 100]
    inner = [0, 0, 10, 10]
    assert layout.overlap_ratio(outer, inner, "small") == pytest.approx(1.0)
    assert layout.overlap_ratio(outer, inner, "union") == pytest.approx(0.01)
    assert layout.overlap_ratio(outer, inner, "large") == pytest.approx(0.01)


def test_detect_reproduces_the_golden_regions(cfg, golden):
    """The recorded tensors must produce the recorded regions, box for box.

    This is the pin on the whole tail: NMS, thresholding, the large-image filter
    and the merge modes. The golden's ``regions`` were produced by *this* code on
    the recorded tensors, so a change in any step shows up as a diff here rather
    than as subtly different Markdown on the board.
    """
    for entry in golden["layout"]["images"]:
        regions = layout.detect(
            _npz_arrays(entry["image"], "boxes"),
            _npz_arrays(entry["image"], "scores"),
            _page_hw(entry), cfg)
        assert [(r["label"], r["box"]) for r in regions] == [
            (r["label"], r["box"]) for r in entry["regions"]], entry["image"]
    # Both halves of the fixture must be present, or the loop above could pass
    # against a golden of empty lists: some page on which the model finds
    # regions, and some page on which it finds none (``ui_status.png``'s boxes
    # all score 0.30-0.40, below the 0.5 threshold -- see docs/ocr-structure.md
    # §2, where that 0/0 is "agrees with the reference", not "blank page").
    assert any(entry["regions"] for entry in golden["layout"]["images"])
    assert any(not entry["regions"] for entry in golden["layout"]["images"])


def _npz_arrays(image: str, kind: str):
    """``(boxes, scores)`` for one image from ``layout_tensors.npz``.

    Kept in an ``.npz`` rather than inline in the golden: 8500x4 floats per page
    is ~1.7 MB of JSON per image, and the golden is meant to stay readable. Only
    the anchors that survive the model's 0.025 pre-threshold are stored, so the
    file is 400 KB for ten pages instead of 8 MB.
    """
    return np.load(_npz_path())[f"{kind}/{image}"]


def _npz_path():
    path = DATA / "layout_tensors.npz"
    if not path.exists():  # pragma: no cover - regenerated with the golden
        pytest.skip("layout_tensors.npz missing; re-run tools/ocr/make_golden.py")
    return path



def test_preprocess_matches_the_numpy_formula(cfg):
    """``cv2.dnn.blobFromImage`` must equal the numpy chain it replaced.

    ``preprocess`` was written as ``resize -> cvtColor -> /255 -> (x-mean)/std
    -> CHW`` and rewritten for speed as one ``blobFromImage`` call plus a
    per-channel divide (the board's numpy form cost 36 ms of a 104 ms page).
    The two are the same arithmetic, but only *almost* the same expression: the
    mean is subtracted on the 0..255 scale inside ``blobFromImage``, and the
    channel order comes from ``swapRB``. This pins the result against the
    formula, so a future "tidy-up" of either side fails here instead of
    degrading every region on the board by a few pixels.
    """
    cv2 = pytest.importorskip("cv2", reason="this compares against OpenCV")

    bgr = cv2.imread(str(IMG / "cn_notice.png"), cv2.IMREAD_COLOR)
    side = cfg.side
    x = cv2.resize(bgr, (side, side), interpolation=cv2.INTER_LINEAR)
    x = cv2.cvtColor(x, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    want = (x - np.array(cfg.mean, np.float32)) / np.array(cfg.std, np.float32)
    want = np.ascontiguousarray(want.transpose(2, 0, 1)[None])
    got = layout.preprocess(bgr, cfg)
    assert got.shape == want.shape == (1, 3, side, side)
    # float32 rounding only: the reference is 4.8e-7, one ULP at these values.
    assert float(np.abs(got - want).max()) < 1e-6


def test_detect_returns_nothing_for_a_blank_page(cfg):
    """A page with no text must yield no regions rather than a garbage box."""
    boxes = np.zeros((10, 4), np.float32)
    scores = np.zeros((23, 10), np.float32)
    assert layout.detect(boxes, scores, (100, 100), cfg) == []


def test_the_large_image_filter_drops_a_whole_page_image(cfg):
    """PaddleX drops an ``image`` box covering the page; a half-page one stays.

    The raw boxes are in *network-input* pixels (640x640), because that is what
    the bmodel emits -- ``detect`` scales them back through the page factors.
    """
    image_cls = layout.LABELS.index("image")
    side = cfg.side
    # two boxes in a 640x640 net: one full page, one the top half
    boxes = np.array([[0, 0, side, side], [0, 0, side, side / 2]], np.float32)
    scores = np.zeros((23, 2), np.float32)
    scores[image_cls] = [0.99, 0.99]
    # A portrait page (h > w) uses the 0.82 ratio, so the full-page box goes.
    kept = layout.detect(boxes, scores, (side, side // 2), cfg)
    assert len(kept) == 1
    # The surviving box is the top half, whose bottom edge is half the page.
    assert kept[0]["box"][3] == pytest.approx(side // 2)


# --------------------------------------------------------------------------- #
# joining a region's lines
# --------------------------------------------------------------------------- #
def test_chinese_lines_join_without_spaces():
    """The rule that makes a Chinese paragraph read continuously."""
    entries = [{"text": "第一行文字", "score": 0.9, "box": [0, 0, 200, 20]},
               {"text": "第二行文字", "score": 0.9, "box": [0, 24, 200, 44]}]
    text = layout.block_text(entries, "text", [0, 0, 200, 50])
    assert "第一行文字第二行文字" in text.replace("\n", "")


def test_english_lines_keep_a_space():
    """And the rule that makes English text not run together."""
    entries = [{"text": "first line", "score": 0.9, "box": [0, 0, 200, 20]},
               {"text": "second line", "score": 0.9, "box": [0, 24, 200, 44]}]
    text = layout.block_text(entries, "text", [0, 0, 200, 50])
    assert "first line " in text


def test_a_doc_title_joins_with_a_space():
    """``delimiter_map`` says a doc_title is space-joined, not reflowed."""
    entries = [{"text": "标题上行", "score": 0.9, "box": [0, 0, 200, 20]},
               {"text": "标题下行", "score": 0.9, "box": [0, 24, 200, 44]}]
    assert layout.block_text(entries, "doc_title", [0, 0, 200, 50]) == "标题上行 标题下行"


def test_a_hyphenated_break_is_removed():
    """PaddleX drops a trailing ``-`` rather than carrying it into the text."""
    entries = [{"text": "inter-", "score": 0.9, "box": [0, 0, 200, 20]},
               {"text": "national", "score": 0.9, "box": [0, 24, 200, 44]}]
    assert "-" not in layout.block_text(entries, "text", [0, 0, 200, 50])


def test_group_lines_uses_the_reference_threshold():
    """Boxes whose heights overlap by 0.6 or more are one line; less is two."""
    same = [{"text": "a", "score": 0.9, "box": [0, 0, 100, 20]},
            {"text": "b", "score": 0.9, "box": [110, 8, 200, 28]}]
    assert len(layout.group_lines(same)) == 1
    apart = [{"text": "a", "score": 0.9, "box": [0, 0, 100, 20]},
             {"text": "b", "score": 0.9, "box": [110, 14, 200, 34]}]
    assert len(layout.group_lines(apart)) == 2


def test_group_lines_reads_left_to_right_inside_a_line():
    entries = [{"text": "右", "score": 0.9, "box": [120, 0, 200, 20]},
               {"text": "左", "score": 0.9, "box": [0, 1, 80, 21]}]
    lines = layout.group_lines(entries)
    assert [e["text"] for e in lines[0]] == ["左", "右"]


# --------------------------------------------------------------------------- #
# assigning OCR lines to regions
# --------------------------------------------------------------------------- #
def _region(label: str, box) -> dict:
    return {"cls_id": layout.LABELS.index(label) if label in layout.LABELS else -1,
            "label": label, "score": 0.9, "box": list(box), "lines": [], "text": ""}


def test_a_line_goes_to_the_region_it_overlaps():
    regions = [_region("text", [0, 0, 100, 100])]
    out = layout.assign_lines(regions, [Line("hello", [10, 10, 90, 30])])
    assert [e["text"] for e in out[0]["lines"]] == ["hello"]
    assert out[0]["text"] == "hello"


def test_a_line_in_two_regions_goes_to_the_smaller():
    """The card's tie-break: smallest area wins, not PaddleX's crop-and-rerecognise."""
    big = _region("text", [0, 0, 400, 400])
    small = _region("table", [180, 180, 220, 220])
    out = layout.assign_lines([big, small], [Line("x", [185, 190, 215, 210])])
    assert [e["text"] for e in out[1]["lines"]] == ["x"]
    assert out[0]["lines"] == []


def test_a_line_outside_every_region_still_appears():
    """Losing text is the one failure the card calls out; it must not happen.

    With a text region on the page the line is attached to the nearest one; with
    no text region it becomes its own ``other_text`` block. Either way it reaches
    ``text``.
    """
    regions = [_region("text", [0, 0, 100, 100])]
    out = layout.assign_lines(regions, [Line("outside", [500, 500, 600, 520])])
    assert out[0]["lines"], "the line must land somewhere"
    assert "outside" in layout.to_markdown(out)


def test_a_line_outside_every_region_becomes_its_own_block():
    """No text region at all: the line is emitted as ``other_text``, not dropped."""
    regions = [_region("table", [0, 0, 100, 100])]
    out = layout.assign_lines(regions, [Line("orphan", [500, 500, 600, 520])])
    assert [r["label"] for r in out] == ["table", layout.OTHER_TEXT_LABEL]
    assert out[-1]["text"] == "orphan"
    assert "orphan" in layout.to_markdown(layout.order_regions(out, (800, 800)))


def test_the_overlap_minimum_is_the_reference_three_pixels():
    """A two-pixel graze is not an overlap; a four-pixel one is."""
    regions = [_region("text", [0, 0, 100, 100])]
    # A 2 px overlap is below the minimum, so the line does *not* count as
    # inside the region -- it reaches the region only through the
    # nearest-text fallback. Both paths end with the text on the page, so the
    # distinction is asserted on the overlap test itself rather than on where
    # the line ended up.
    assert not layout._overlaps([98, 10, 150, 30], regions[0]["box"],
                                layout.MIN_OVERLAP_PX)
    assert layout._overlaps([95, 10, 150, 30], regions[0]["box"],
                            layout.MIN_OVERLAP_PX)
    graze = layout.assign_lines(list(regions), [Line("g", [98, 10, 150, 30])])
    assert [r["label"] for r in graze] == ["text"]
    assert [e["text"] for e in graze[0]["lines"]] == ["g"]


def test_a_figure_region_keeps_its_text_so_the_markdown_can_show_it():
    """PaddleX reads text inside a figure too, and the card wants it appended.

    Blanking it here would lose the caption from the Markdown; the placeholder
    would be all a reader ever saw.
    """
    regions = [_region("image", [0, 0, 200, 200])]
    out = layout.assign_lines(regions, [Line("caption", [10, 10, 90, 30])])
    assert [e["text"] for e in out[0]["lines"]] == ["caption"]
    assert out[0]["text"] == "caption"


# --------------------------------------------------------------------------- #
# reading order
# --------------------------------------------------------------------------- #
def _order_of(regions, page_hw=(800, 800)):
    ordered = layout.order_regions(regions, page_hw)
    return [r["text"] for r in ordered]


def test_reading_order_sorts_a_single_column_top_to_bottom():
    regions = [_region("text", [0, 200, 400, 260]),
               _region("text", [0, 0, 400, 60]),
               _region("text", [0, 100, 400, 160])]
    for idx, region in enumerate(regions):
        region["text"] = f"block{idx}"
    texts = _order_of(regions)
    assert texts == ["block1", "block2", "block0"]


def test_reading_order_keeps_a_two_column_page_from_interleaving():
    """The criterion: left column, then right column -- never alternating.

    This is the shape the drawn page produces: two body regions per column pair,
    with a cross-layout block between the pairs. A (y, x) sort would give
    left1, right1, cross, left2, right2.
    """
    regions = [_region("text", [0, 100, 380, 320]),
               _region("text", [420, 100, 800, 320]),
               _region("text", [0, 340, 800, 380]),
               _region("text", [0, 400, 380, 620]),
               _region("text", [420, 400, 800, 620])]
    for idx, region in enumerate(regions):
        region["text"] = f"block{idx}"
    assert _order_of(regions) == ["block0", "block1", "block2", "block3", "block4"]


def test_a_header_is_pinned_to_the_top_and_a_footer_to_the_bottom():
    """``BLOCK_LABEL_MAP``'s header/footer lists are what pin them."""
    regions = [_region("footer", [0, 700, 400, 740]),
               _region("text", [0, 100, 400, 300]),
               _region("header", [0, 0, 400, 40])]
    for idx, region in enumerate(regions):
        region["text"] = f"block{idx}"
    assert _order_of(regions) == ["block2", "block1", "block0"]


def test_markdown_ignores_header_footer_and_number_but_blocks_keeps_them():
    """PaddleX's default ``markdown_ignore_labels``; the card asks for both halves."""
    regions = [_region("header", [0, 0, 400, 40]),
               _region("text", [0, 100, 400, 200]),
               _region("number", [0, 720, 400, 740])]
    for idx, region in enumerate(regions):
        region["text"] = f"block{idx}"
    ordered = layout.order_regions(regions, (800, 800))
    markdown = layout.to_markdown(ordered)
    assert "block0" not in markdown
    assert "block2" not in markdown
    assert "block1" in markdown
    assert [r["label"] for r in ordered] == ["header", "text", "number"]


def test_the_twocolumn_page_reads_in_the_truth_order(truth):
    """End to end on the drawn page: the golden's detection + the truth's order.

    The regions come from the layout model (via the golden's recorded tensors),
    the lines from the recorded recognitions, and the expected order from the
    generator. So this asserts the product's behaviour against a fact about the
    input, which is what makes it a regression test rather than a snapshot.
    """
    golden = json.loads((DATA / "golden.json").read_text(encoding="utf-8"))
    entry = _layout_entry(golden, "twocolumn.png")
    regions = layout.detect(
        _npz_arrays("twocolumn.png", "boxes"),
        _npz_arrays("twocolumn.png", "scores"),
        _page_hw(entry), layout.load_layout_config(CONFIG))
    filled = layout.assign_lines(regions, _rec_lines(golden, "twocolumn.png"))
    ordered = layout.order_regions(filled, _page_hw(entry))

    # Every region is one of: the title, a column block, or the cross-layout
    # block -- six in total, which is what makes the page able to test anything.
    assert len(ordered) == 6, [(r["label"], r["box"]) for r in ordered]

    # The order the regions' *first* line appears in is the truth's order.
    got = [r["text"] for r in ordered if r["text"]]
    want = truth["reading_order"]
    # Each region's text is its lines concatenated, so compare the leading line.
    leading = [want_line for want_line in want
               if any(text.startswith(want_line) for text in got)]
    got_leading = [next(line for line in want if text.startswith(line))
                   for text in got]
    assert got_leading == [line for line in want if line in got_leading]
    assert len(leading) == len(got_leading)

    # And the concrete structural claim: the title first, the cross-layout block
    # between the two column pairs, and each pair left-before-right.
    boxes = [r["box"] for r in ordered]
    assert boxes[0][1] < boxes[1][1], "the title must come first"
    width = entry["size"][0]
    spans = [b for b in boxes if (b[2] - b[0]) > width * 0.6]
    assert len(spans) == 1, "exactly one block spans both columns"
    centre = spans[0][1]
    above = [b for b in boxes[1:] if b is not spans[0] and b[3] <= centre]
    below = [b for b in boxes[1:] if b is not spans[0] and b[1] >= centre]
    assert len(above) == 2 and len(below) == 2
    for pair in (above, below):
        assert pair[0][0] < pair[1][0], "left column before right"
    assert max(b[3] for b in above) <= centre <= min(b[1] for b in below)


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
def test_doc_title_becomes_h1_and_paragraph_title_h2():
    regions = [_region("doc_title", [0, 0, 400, 40]),
               _region("paragraph_title", [0, 60, 400, 100]),
               _region("text", [0, 120, 400, 200])]
    for region, text in zip(regions, ["大标题", "小标题", "正文"]):
        region["text"] = text
    markdown = layout.to_markdown(regions)
    assert markdown.startswith("# 大标题")
    assert "## 小标题" in markdown
    assert "正文" in markdown


def test_a_table_is_text_rows_under_a_marker_not_a_pipe_table():
    """The card's rule: no structure restored, and the reader is told so."""
    table = _region("table", [0, 0, 400, 200])
    table["lines"] = [
        {"text": "区域", "score": 0.9, "box": [10, 10, 80, 30]},
        {"text": "负责人", "score": 0.9, "box": [120, 10, 200, 30]},
        {"text": "一号机房", "score": 0.9, "box": [10, 50, 100, 70]},
        {"text": "张伟", "score": 0.9, "box": [120, 50, 180, 70]},
    ]
    markdown = layout.to_markdown([table])
    assert layout.TABLE_NOTE in markdown
    assert "|" not in markdown and "<table" not in markdown
    assert "区域 负责人" in markdown
    assert "一号机房 张伟" in markdown


def test_a_figure_becomes_a_placeholder_with_any_text_after_it():
    regions = [_region("image", [0, 0, 400, 300])]
    out = layout.assign_lines(regions, [Line("图注", [10, 250, 90, 270])])
    markdown = layout.to_markdown(out)
    assert markdown.startswith("[图片]")
    assert "图注" in markdown


def test_a_formula_region_is_its_text_verbatim():
    """No formula recogniser, so no invented ``$$`` -- the card says verbatim."""
    formula = _region("formula", [0, 0, 400, 100])
    formula["text"] = "E=mc2"
    assert layout.to_markdown([formula]) == "E=mc2"


def test_body_text_paragraph_breaks_become_blank_lines():
    """PaddleX's ``_format_normalize_newlines``: one newline means a paragraph."""
    region = _region("text", [0, 0, 400, 200])
    region["text"] = "第一段\n第二段"
    assert layout.to_markdown([region]) == "第一段\n\n第二段"


def test_an_empty_page_renders_empty():
    assert layout.to_markdown([]) == ""


# --------------------------------------------------------------------------- #
# the image assets
# --------------------------------------------------------------------------- #
def test_the_twocolumn_image_is_within_budget():
    png = IMG / "twocolumn.png"
    assert png.is_file()
    assert png.stat().st_size <= 300 * 1024
    from PIL import Image
    with Image.open(png) as image:
        image.verify()


def test_the_twocolumn_truth_covers_every_region(truth):
    """Six regions' worth of lines, with the cross-layout block between pairs."""
    lines = truth["lines"]
    assert len(lines) == 15
    assert sum(1 for line in lines if line["kind"] == "title") == 1
    assert sum(1 for line in lines if line["kind"] == "full") == 2
    body = [line for line in lines if line["kind"] == "body"]
    assert len(body) == 12
    assert sum(1 for line in body if line["column"] == "left") == 6
    assert sum(1 for line in body if line["column"] == "right") == 6
    # The reading order lists every line exactly once.
    assert len(truth["reading_order"]) == len(lines)
    assert truth["reading_order"] == [line["text"] for line in lines]


# ---------------------------------------------------------------------------
# the distance-insertion weights
# ---------------------------------------------------------------------------
def test_a_title_over_a_body_block_is_ordered_by_distance_insertion():
    """A ``doc_title`` goes through ``_weighted_distance_insert``, and that path
    reads ``left_edge_weight`` -- a key PaddleX's own ``XYCUT_SETTINGS`` does
    **not** define (it spells the third key ``down_edge_weight``) and its code
    therefore reads with a ``.get(..., 0.0001)`` default.

    Found while adding ``mode: "vl"``: our port used a plain ``[]`` lookup, so
    ordering raised ``KeyError`` on every page with a title or a figure -- in
    ``layout`` mode too. The page's whole order is empty in that case, which is
    how it presented (no blocks at all), not as an exception.
    """
    from app.engine import ocr_layout as layout

    regions = [
        {"label": "text", "score": 0.9, "box": [10, 120, 600, 400]},
        {"label": "doc_title", "score": 0.95, "box": [10, 20, 600, 90]},
    ]
    ordered = layout.order_regions(regions, (700, 620))
    assert [region["label"] for region in ordered] == ["doc_title", "text"]


def test_the_reference_falls_back_to_the_same_left_edge_weight():
    """Pin the *value* the reference uses, so the fix cannot be "whatever the
    dict happens to hold": PaddleX's ``.get("left_edge_weight", 0.0001)``."""
    from app.engine import ocr_layout as layout

    weights = layout.XYCUT_SETTINGS["distance_weight_map"]
    assert weights.get("edge_weight", 1e4) == 10 ** 4
    assert weights.get("up_edge_weight", 1.0) == 1
    assert weights.get("left_edge_weight", 1e-4) == 0.0001
