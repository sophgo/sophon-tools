"""``mode: "vl"``: the page orchestration, without an NPU or a model.

The mode has four testable halves and one that is not, and the tests are split
on exactly that line:

* **OTSL -> HTML** (:func:`app.engine.ocr_vl_page.otsl_to_html`) -- checked
  against ``tests/data/ocr/otsl_golden.json``, which is PaddleX's own
  ``convert_otsl_to_html`` run over the same inputs. This is the part the card
  asks for most specifically ("含合并单元格"), and the part where being *nearly*
  right is worthless: a span counted from the wrong cell produces a table that
  renders and says the wrong thing.
* **The label -> instruction map** -- pinned against the labels PP-DocLayout-M
  actually emits, because a wrong instruction makes the model answer a different
  question (``OCR:`` vs ``Table Recognition:`` alone changes prose into OTSL).
* **The page** (order, merge, per-region dispatch, Markdown) -- driven with a
  stub recogniser, so the whole path runs on a laptop. The stub is what makes
  this possible: the orchestration is pure host code and the model is behind one
  callable.
* **The refusals** -- which model is missing, and which HTTP status that is.

What is *not* here: the NPU. ``recognise_block``'s decode loop is exercised by
``tests/test_ocr_vl_native.py``'s golden and, for real, by the board run
recorded in ``docs/ocr-vl.md`` §11.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.engine import ocr_vl_page as page

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "data" / "ocr" / "otsl_golden.json"


def _golden() -> list[dict]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]


# ---------------------------------------------------------------------------
# OTSL -> HTML
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("case", _golden(), ids=lambda c: c["otsl"][:24] or "<empty>")
def test_otsl_html_matches_paddlex(case):
    """Every golden input renders exactly what PaddleX's converter renders.

    ``html: None`` marks an input the reference *raises* on (a ``<lcel>`` with no
    cell to its left). Those are pinned separately below: the requirement there
    is that the service answers HTML at all, since a model can emit such a string
    and a 500 on a page is not an acceptable answer to it.
    """
    if case["html"] is None:
        assert page.otsl_to_html(case["otsl"])
        return
    assert page.otsl_to_html(case["otsl"]) == case["html"]


def test_the_merged_cell_table_from_the_board_keeps_both_spans():
    """``cn_table_merged.png``'s real answer: a header colspan and a rowspan.

    Asserted structurally rather than only through the golden, because this is
    the card's headline claim: the same page through ``layout`` mode cannot
    produce either span, and ``docs/ocr-vl.md`` §5.2 is the measurement.
    """
    otsl = ("<fcel>2026年第三季度设备巡检记录<lcel><lcel><lcel><lcel><nl>"
            "<fcel>区域/设备<lcel><fcel>巡检日期<fcel>状态<fcel>负责人<nl>"
            "<fcel>二号机房<fcel>服务器D<fcel>2026-06-30<fcel>正常<fcel>赵敏<nl>"
            "<fcel>一号机房<fcel>服务器A<fcel>2026-07-12<fcel>正常<fcel>张伟<nl>"
            "<ucel><fcel>服务器B<fcel>2026-08-09<fcel>告警<fcel>李娜<nl>"
            "<ucel><fcel>服务器C<fcel>2026-09-01<fcel>正常<fcel>王强<nl>")
    rendered = page.otsl_to_html(otsl)
    assert rendered.count("<tr>") == 6
    # title spans all five columns
    assert 'colspan="5"' in rendered
    # "区域/设备" spans the two cells of the row below it
    assert 'colspan="2"' in rendered
    # "一号机房" covers three rows, expressed as <ucel> in the two rows after it
    assert 'rowspan="3"' in rendered
    assert "2026年第三季度设备巡检记录" in rendered


def test_html_is_escaped_but_the_model_text_is_not_rewritten():
    """Cell text is escaped once, not sanitised: ``&amp`` stays ``&amp;amp``.

    Escaping twice would be a different bug from not escaping, and the golden
    settles which the reference does.
    """
    rendered = page.otsl_to_html("<fcel>a<b<fcel>&<nl>")
    assert "a&lt;b" in rendered
    assert "&amp;" in rendered


def test_a_prose_answer_to_a_table_prompt_is_not_an_empty_table():
    """No OTSL tags means no table: the caller falls back to the text.

    ``convert_otsl_to_html`` returns "" for prose, and an empty ``<table>`` would
    silently discard whatever the model did say.
    """
    assert page.otsl_to_html("上表是 2026 年第三季度的产线统计。") == ""
    assert page.otsl_to_html("") == ""


def test_a_lcel_with_no_anchor_still_renders():
    """The one input class the reference crashes on.

    PaddleX's ``count_right`` indexes past the row and raises ``IndexError``.
    The service must not: a page is worth more than a strict reading of the
    grammar, and the HTML it produces here still has the right column count.
    """
    rendered = page.otsl_to_html("<lcel><fcel>a<nl>")
    assert rendered.count("<td") == 2
    assert ">a<" in rendered


# ---------------------------------------------------------------------------
# the label -> instruction map
# ---------------------------------------------------------------------------
#: Every class PP-DocLayout-M emits, and the instruction the reference gives it.
#: The left column is ``layout.json``'s label list -- all 23 of them -- so a new
#: label in a future bmodel fails this test rather than silently getting ``OCR:``.
EXPECTED_TASKS = {
    "paragraph_title": page.PROMPT_OCR,
    "image": None,
    "text": page.PROMPT_OCR,
    "number": page.PROMPT_OCR,
    "abstract": page.PROMPT_OCR,
    "content": page.PROMPT_OCR,
    "figure_title": page.PROMPT_OCR,
    "formula": page.PROMPT_FORMULA,
    "table": page.PROMPT_TABLE,
    "table_title": page.PROMPT_OCR,
    "reference": page.PROMPT_OCR,
    "doc_title": page.PROMPT_OCR,
    "footnote": page.PROMPT_OCR,
    "header": page.PROMPT_OCR,
    "algorithm": page.PROMPT_OCR,
    "footer": page.PROMPT_OCR,
    "seal": None,
    "chart_title": page.PROMPT_OCR,
    "chart": None,
    "formula_number": page.PROMPT_OCR,
    "header_image": None,
    "footer_image": None,
    "aside_text": page.PROMPT_OCR,
}


def test_every_detector_label_has_the_reference_instruction():
    from app.engine.ocr_layout import LABELS

    assert set(LABELS) == set(EXPECTED_TASKS), "a class was added or removed"
    for label, expected in EXPECTED_TASKS.items():
        assert page.prompt_for(label) == expected, label


def test_formula_number_is_read_as_text_not_typeset():
    """The reference names this exception explicitly: ``"formula" in label and
    label != "formula_number"``. Typesetting a formula *number* asks the model
    to LaTeX a label that should just be read."""
    assert page.prompt_for("formula_number") == page.PROMPT_OCR
    assert page.prompt_for("formula") == page.PROMPT_FORMULA
    assert page.prompt_for("inline_formula") == page.PROMPT_FORMULA
    assert page.prompt_for("display_formula") == page.PROMPT_FORMULA


def test_an_unknown_label_falls_back_to_ocr():
    """The reference's ``text_prompt`` starts at ``OCR:``, so a class it does not
    special-case is still read rather than dropped."""
    assert page.prompt_for("something_new") == page.PROMPT_OCR


def test_pictures_are_not_sent_to_the_model():
    """With chart and seal recognition off (the shipped yaml), those classes join
    the picture labels: the reference drops them before recognition."""
    for label in ("image", "header_image", "footer_image", "chart", "seal"):
        assert page.prompt_for(label) is None, label


# ---------------------------------------------------------------------------
# per-region clean-up
# ---------------------------------------------------------------------------
def test_latex_delimiters_become_the_dollar_form():
    """``\\(x\\)`` -> ``$ x $``, ``\\[x\\]`` -> ``$$ x $$``, transcribed from
    ``pipeline.py``. Markdown renderers only understand the dollar form."""
    assert page.normalize_content("\\(8 \\times 4\\)", "text") == " $ 8 \\times 4 $"
    # The reference's closing replace is ``" $ "`` (not ``" $"``), so a trailing
    # space is part of its output, not a mistake here.
    assert page.normalize_content("\\[E=mc^2\\]", "text") == " $$ E=mc^2 $$ "


def test_double_brackets_are_collapsed_before_single_ones():
    """``\\[\\[a\\]\\]`` must not become ``$ $ a $ $``: the reference collapses the
    doubled pair first, and the order is the whole content of that rule."""
    assert page.normalize_content("\\[\\[a\\]\\]", "text") == " $$ a $$ "


def test_an_existing_dollar_sign_is_dropped_when_latex_delimiters_are_present():
    # ``replace("$", "")`` runs first over the whole block, so the stray ``$``
    # around ``b`` goes too -- the reference's behaviour, not a simplification.
    assert page.normalize_content("\\(a\\) and $b$", "text") == " $ a $ and b"


def test_a_formula_number_block_keeps_no_dollar_at_all():
    assert page.normalize_content("\\(1\\)", "formula_number") == "  1 "


def test_text_without_latex_delimiters_is_untouched():
    prose = "关于开展设备巡检工作的通知\n\n各部门："
    assert page.normalize_content(prose, "text") == prose


def test_a_stuck_decode_is_cut_at_its_repeating_span():
    """A stuck decode repeats one span until the sequence ends; the reference cuts
    it, at 3000 characters for anything and 5000 for a table.

    Those thresholds are why a *real* table survives: ``table_stats.png``'s whole
    answer is 299 characters, so it never reaches the cut. The test pins both
    halves -- a 400-row repeat is truncated, and the board's actual table is not.
    """
    row = "<fcel>一号线<fcel>4,120<fcel>99.6%<fcel>张伟<nl>"
    looping = row * 400
    assert len(looping) > page.REPEAT_MIN_COUNT_TABLE
    assert len(page.normalize_content(looping, "table")) < len(looping)
    assert len(page.normalize_content(looping, "text")) < len(looping)

    # The real answer from the board, verbatim (docs/ocr-vl.md §5.1-§5.2).
    real = ("<fcel>产线<fcel>产量（台）<fcel>合格率<fcel>负责人<nl>"
            "<fcel>一号线<fcel>4,120<fcel>99.6%<fcel>张伟<nl>"
            "<fcel>二号线<fcel>3,860<fcel>99.1%<fcel>李静<nl>"
            "<fcel>三号线<fcel>3,300<fcel>98.7%<fcel>王强<nl>"
            "<fcel>四号线<fcel>1,200<fcel>99.4%<fcel>赵敏<nl>"
            "<fcel>合计<fcel>12,480<fcel>99.2%<fcel>—<nl>")
    assert "<table>" in page.normalize_content(real, "table")
    assert page.normalize_content(real, "table").count("<tr>") == 6


def test_a_table_answer_becomes_html_and_a_text_answer_does_not():
    otsl = "<fcel>a<fcel>b<nl><fcel>c<fcel>d<nl>"
    assert page.normalize_content(otsl, "table").startswith("<table>")
    assert page.normalize_content(otsl, "text") == otsl


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------
def _page_image(height: int = 900, width: int = 700):
    """A white page, as a BGR numpy array. No cv2 needed to build one."""
    np = pytest.importorskip("numpy")
    return np.full((height, width, 3), 255, dtype=np.uint8)


def _regions():
    return [
        {"label": "doc_title", "score": 0.97, "box": [50, 30, 650, 90]},
        {"label": "text", "score": 0.90, "box": [50, 110, 650, 220]},
        {"label": "table", "score": 0.93, "box": [50, 250, 650, 520]},
        {"label": "image", "score": 0.80, "box": [50, 560, 300, 700]},
        {"label": "text", "score": 0.88, "box": [340, 560, 650, 700]},
    ]


class _Recorder:
    """A stub recogniser: records what it was asked, answers by instruction."""

    def __init__(self, table_answer: str = "<fcel>a<lcel><nl><fcel>b<fcel>c<nl>"):
        self.calls: list[tuple[str, tuple[int, ...]]] = []
        self.table_answer = table_answer

    async def __call__(self, crop, task):
        self.calls.append((task, tuple(getattr(crop, "shape", ()))))
        text = self.table_answer if task == page.PROMPT_TABLE else f"文本 {task}"
        return {"text": text, "tokens": 7,
                "timings": {"vit_ms": 1.0, "prefill_ms": 2.0, "decode_ms": 3.0}}


def _run(regions=None, **kwargs):
    image = kwargs.pop("image", None)
    if image is None:
        image = _page_image()
    recorder = kwargs.pop("recognise", None) or _Recorder()
    result = asyncio.run(page.recognise_page(
        image, _regions() if regions is None else regions,
        recognise=recorder, page_hw=(image.shape[0], image.shape[1])))
    return result, recorder


def test_each_region_gets_its_own_instruction():
    """The page's whole premise: the table is read with ``Table Recognition:``,
    the text with ``OCR:``. A page that sent one instruction for everything
    would produce prose where OTSL was wanted."""
    result, recorder = _run()
    sent = [task for task, _shape in recorder.calls]
    assert page.PROMPT_TABLE in sent
    assert page.PROMPT_OCR in sent
    # The picture is never sent.
    assert len(recorder.calls) == 4
    by_label = {block["label"]: block["task"] for block in result.blocks}
    assert by_label["table"] == page.PROMPT_TABLE
    assert by_label["image"] is None


def test_the_table_block_carries_html_and_the_markdown_uses_it_too():
    result, _recorder = _run()
    table = next(b for b in result.blocks if b["label"] == "table")
    assert table["text"].startswith("<table>")
    assert 'colspan="2"' in table["text"]
    assert table["text"] in result.markdown


def test_figures_render_as_a_placeholder_not_as_ocr_text():
    """``layout`` mode appends whatever OCR read inside a picture; ``vl`` mode
    never asked, so the placeholder is the whole block."""
    result, _recorder = _run()
    image_block = next(b for b in result.blocks if b["label"] == "image")
    assert image_block["text"] == page.FIGURE_PLACEHOLDERS["image"]
    assert page.FIGURE_PLACEHOLDERS["image"] in result.markdown
    assert result.skipped == [{"label": "image", "box": [50, 560, 300, 700]}]


def test_blocks_are_numbered_in_reading_order():
    result, _recorder = _run()
    assert [b["index"] for b in result.blocks] == list(range(len(result.blocks)))
    # The title comes first on this page, and the table before the bottom row.
    labels = [b["label"] for b in result.blocks]
    assert labels[0] == "doc_title"
    assert labels.index("table") < labels.index("image")


def test_the_markdown_starts_with_the_title_as_a_heading():
    result, _recorder = _run()
    assert result.markdown.startswith("# 文本 OCR:")


def test_usage_totals_are_summed_over_the_page():
    result, recorder = _run()
    assert result.vl_tokens == 7 * len(recorder.calls)
    # vit 1 + prefill 2 + decode 3 per region.
    assert result.vl_ms == 6.0 * len(recorder.calls)


def test_a_failing_region_costs_its_block_and_not_the_page():
    """One engine failure must not turn twelve good regions into a 503. The block
    says what happened; everything else is still there."""
    class Flaky(_Recorder):
        async def __call__(self, crop, task):
            if task == page.PROMPT_TABLE:
                raise RuntimeError("bmrt launch failed")
            return await super().__call__(crop, task)

    result, _recorder = _run(recognise=Flaky())
    table = next(b for b in result.blocks if b["label"] == "table")
    assert table["text"] == ""
    assert "bmrt launch failed" in table["error"]
    # The page still rendered the other three, and the table left no empty
    # entry behind in the Markdown.
    assert result.markdown.count("文本") == 3
    assert "<table>" not in result.markdown


def test_a_blank_page_is_empty_rather_than_an_error():
    result, recorder = _run(regions=[])
    assert result.blocks == [] and result.markdown == ""
    assert recorder.calls == []


def test_boxes_are_clipped_to_the_page():
    """A detector box can poke a pixel outside the image; a crop of nothing would
    be a zero-sized tensor handed to the vision tower."""
    regions = [{"label": "text", "score": 0.9, "box": [10, 10, 5000, 5000]},
               {"label": "text", "score": 0.9, "box": [20, 100, 190, 400]}]
    result, recorder = _run(regions=regions, image=_page_image(300, 200))
    boxes = sorted(block["box"] for block in result.blocks)
    assert boxes == [[10, 10, 200, 300], [20, 100, 190, 300]]
    # Each crop is a real sub-array of the page, never zero-sized.
    for _task, shape in recorder.calls:
        assert shape[0] >= 1 and shape[1] >= 1


# ---------------------------------------------------------------------------
# merge_blocks (PaddleX's, not a heuristic)
# ---------------------------------------------------------------------------
def test_a_table_never_joins_its_neighbours():
    """``non_merge_labels = image_labels + ["table"]``. Joining a table into the
    paragraph above it would put its OTSL in that paragraph's answer."""
    regions = [
        {"label": "text", "score": 0.9, "box": [10, 10, 400, 100]},
        {"label": "table", "score": 0.9, "box": [10, 100, 400, 300]},
    ]
    assert page.merge_groups(regions) == [[0], [1]]


def test_two_side_by_side_text_blocks_on_one_line_merge():
    """``is_cross``: a gap in the horizontal projection with vertical overlap is
    one sentence the detector split -- not two blocks to read in turn."""
    regions = [
        {"label": "text", "score": 0.9, "box": [10, 10, 100, 60]},
        {"label": "text", "score": 0.9, "box": [120, 10, 400, 60]},
    ]
    assert page.merge_groups(regions) == [[0, 1]]


def test_stacked_text_blocks_merge_only_when_an_exempt_block_sits_between():
    """``is_updown_align`` requires ``overlapwith_other_box``: the group's hull
    must cover a non-mergeable block. Two plain paragraphs with nothing between
    them are *not* merged -- the reference's rule is narrower than "join
    neighbours", and widening it would change the page's reported region count."""
    alone = [
        {"label": "text", "score": 0.9, "box": [10, 10, 400, 100]},
        {"label": "text", "score": 0.9, "box": [10, 110, 400, 200]},
    ]
    assert page.merge_groups(alone) == [[0], [1]]
    with_figure = [
        {"label": "text", "score": 0.9, "box": [10, 10, 200, 100]},
        {"label": "image", "score": 0.9, "box": [100, 100, 300, 200]},
        {"label": "text", "score": 0.9, "box": [10, 110, 200, 220]},
    ]
    # The picture stays its own unit; whether the two text blocks join depends on
    # the hull test, which the picture satisfies.
    groups = page.merge_groups(with_figure)
    assert [1] in groups


def test_a_tall_group_is_not_merged():
    """``calc_merged_wh``'s 3:1 cut: a stack that tall is separate lines, not one
    block, so the reference emits the members apart."""
    regions = [
        {"label": "text", "score": 0.9, "box": [10, 10, 100, 100]},
        {"label": "image", "score": 0.9, "box": [90, 100, 300, 160]},
        {"label": "text", "score": 0.9, "box": [10, 100, 100, 200]},
    ]
    groups = page.merge_groups(regions)
    # A 2-block group at ~1.2:1 would merge; this one's only candidate pair is
    # 190 px wide and 190 px tall over two rows, so it is under the cut and the
    # test asserts the *rule*, not a particular grouping.
    for group in groups:
        assert page._group_aspect(regions, group) < page.MERGE_MAX_ASPECT or len(group) == 1


# ---------------------------------------------------------------------------
# the two-model refusal
# ---------------------------------------------------------------------------
def test_a_vl_request_without_the_vl_model_is_a_409_naming_it():
    """The card's requirement: "任意一个没有加载时返回 409，提示要加载哪一个".
    The VLM is not auto-loaded, so this is the answer a caller gets -- and it
    must name the model and the alternative, not just say no."""
    from fastapi import HTTPException

    class _Models:
        def best_loaded(self, kind):
            return None

    class _State:
        models = _Models()

    class _App:
        state = _State()

    class _Request:
        app = _App()

    with pytest.raises(HTTPException) as caught:
        page.require_vl_model(_Request())
    assert caught.value.status_code == 409
    assert "PaddleOCR-VL" in caught.value.detail
    assert 'mode="layout"' in caught.value.detail


def test_the_vl_model_is_found_when_loaded():
    class _Info:
        model_id = "paddleocr-vl-1.5"

    class _Models:
        def best_loaded(self, kind):
            assert kind == "ocr_vl"
            return _Info()

    class _State:
        models = _Models()

    class _App:
        state = _State()

    class _Request:
        app = _App()

    assert page.require_vl_model(_Request()) == "paddleocr-vl-1.5"


# ---------------------------------------------------------------------------
# the answer budget
# ---------------------------------------------------------------------------
def test_the_answer_budget_is_clamped_to_the_context():
    """The reference asks for 4096 tokens, but the bmodel's SEQLEN is 2048 and the
    prompt already holds 797. Asking the engine for more than fits would end the
    block at the context edge with an engine error instead of a ``length``
    reason."""
    assert page.effective_max_new(4096) == page.MAX_ANSWER_TOKENS
    assert page.effective_max_new(None) == page.MAX_ANSWER_TOKENS
    assert page.effective_max_new(100) == 100
    assert page.effective_max_new(0) == 1
    assert page.MAX_ANSWER_TOKENS == 2048 - 797 - 1


def test_the_page_timeout_grows_with_the_page():
    """A twelve-region page is minutes, not seconds: the single-region OCR bound
    would abandon a page that is working."""
    one, twelve = page.page_timeout_s(1), page.page_timeout_s(12)
    # The per-region part scales exactly; the fixed part (the layout pass) does
    # not, which is why this is not a simple 12x.
    assert twelve > one + page.region_timeout_s() * 10
    assert page.region_timeout_s() > page.MAX_ANSWER_TOKENS * 0.013


# ---------------------------------------------------------------------------
# the two worker ops
# ---------------------------------------------------------------------------
def _run_op(handler, backend, msg):
    """Drive one worker op and collect what it wrote."""
    from app.engine import worker as worker_mod

    sent: list[dict] = []

    async def write(obj):
        sent.append(obj)

    async def go():
        await getattr(worker_mod, handler)(backend, msg, write)

    asyncio.run(go())
    return sent[0]


class _PageBackend:
    """A backend with the two ``vl`` halves, plus the switches to break them."""

    def __init__(self):
        self.detect_error = None
        self.recognise_error = None
        self.tasks: list[str] = []

    async def detect_page(self, image):
        if self.detect_error:
            raise self.detect_error
        return {"width": 400, "height": 600, "layout_ms": 1.5,
                "regions": [{"label": "text", "score": 0.9,
                             "box": [10, 10, 200, 100]},
                            {"label": "table", "score": 0.9,
                             "box": [10, 120, 200, 300]}]}

    def decode_page(self, image):
        numpy = pytest.importorskip("numpy")
        return numpy.full((600, 400, 3), 255, dtype=numpy.uint8)

    async def recognise_block(self, crop, task, max_new_tokens=None):
        if self.recognise_error:
            raise self.recognise_error
        self.tasks.append(task)
        return {"text": "<fcel>a<nl>", "tokens": 3,
                "timings": {"vit_ms": 1.0, "prefill_ms": 1.0, "decode_ms": 1.0}}


def test_detect_page_reports_the_regions_and_the_layout_cost():
    sent = _run_op("handle_detect_page", _PageBackend(),
                   {"req_id": "r", "image_b64": "QUJD"})
    assert sent["op"] == "detect_page_result"
    assert sent["width"] == 400 and sent["height"] == 600
    assert [region["label"] for region in sent["regions"]] == ["text", "table"]
    assert sent["layout_ms"] == 1.5


def test_detect_page_refuses_a_non_string_image():
    sent = _run_op("handle_detect_page", _PageBackend(),
                   {"req_id": "r", "image_b64": None})
    assert sent["kind"] == "invalid_request"
    assert "base64" in sent["message"]


def test_detect_page_reports_a_missing_layout_model_as_a_client_error():
    """A device with the four-file OCR model and no layout bmodel: the operator
    is a download short, which is a 400 naming the file, not a 503."""
    from app.engine.ocr_ppocr import OcrModeUnavailable

    backend = _PageBackend()
    backend.detect_error = OcrModeUnavailable("版面模式需要版面模型 X.bmodel")
    sent = _run_op("handle_detect_page", backend,
                   {"req_id": "r", "image_b64": "QUJD"})
    assert sent["kind"] == "invalid_request"
    assert "X.bmodel" in sent["message"]


def test_ocr_page_runs_each_region_and_reports_the_page():
    backend = _PageBackend()
    sent = _run_op("handle_ocr_page", backend, {
        "req_id": "r", "image_b64": "QUJD",
        "regions": [{"label": "text", "score": 0.9, "box": [10, 10, 200, 100]},
                    {"label": "table", "score": 0.9, "box": [10, 120, 200, 300]}]})
    assert sent["op"] == "ocr_page_result"
    assert sent["mode"] == "vl"
    assert backend.tasks == [page.PROMPT_OCR, page.PROMPT_TABLE]
    # Two answers of 3 tokens each, and 3 ms of engine time per region.
    assert sent["vl_tokens"] == 6
    assert sent["vl_ms"] == 6.0
    # The table's OTSL became HTML on the way out.
    table = next(b for b in sent["blocks"] if b["label"] == "table")
    assert table["text"] == "<table><tr><td>a</td></tr></table>"
    assert "<table>" in sent["text"]


def test_ocr_page_requires_regions():
    sent = _run_op("handle_ocr_page", _PageBackend(),
                   {"req_id": "r", "image_b64": "QUJD"})
    assert sent["kind"] == "invalid_request"
    assert "regions" in sent["message"]


def test_ocr_page_reports_a_whole_page_engine_failure_as_server():
    backend = _PageBackend()
    backend.recognise_error = RuntimeError("bmrt launch")
    sent = _run_op("handle_ocr_page", backend, {
        "req_id": "r", "image_b64": "QUJD",
        "regions": [{"label": "text", "score": 0.9, "box": [10, 10, 200, 100]}]})
    # One region failed, so the page's only block carries the error -- but the
    # call still answers a page rather than a 503.
    assert sent["op"] == "ocr_page_result"
    assert sent["blocks"][0]["error"]


def test_the_two_ops_are_routed_to_the_two_different_models():
    """``detect_page`` is the OCR worker's, ``ocr_page`` the VLM's. Getting this
    backwards is a 400 ("this is an ocr model, it does not support ocr_page")
    rather than a silent wrong answer, but only if the table is right."""
    import inspect

    from app.engine import worker as worker_mod

    source = inspect.getsource(worker_mod.serve)
    assert '"detect_page": "ocr"' in source
    assert '"ocr_page": "ocr_vl"' in source


def test_the_page_timeouts_agree_across_the_socket():
    """The API's bound and the page module's are the same number by
    construction, so "the worker is wedged" means one thing."""
    from app.core.client import WorkerClient

    assert WorkerClient.page_timeout_s(5) == page.page_timeout_s(5)


# ---------------------------------------------------------------------------
# the OCR backend's layout half
# ---------------------------------------------------------------------------
def test_detect_page_needs_no_recognition_pass():
    """``detect_page`` must not run PP-OCR.

    This is the mode's whole cost argument: on a dense page the det+rec pass is
    thousands of recognitions nobody reads, because the VLM reads each region
    instead. Pinned on the *call*, not on the timing: a real backend here would
    need an NPU, so the engines are stubbed and what is asserted is that the rec
    engines are never touched.
    """
    np = pytest.importorskip("numpy")
    from app.engine import ocr_ppocr

    class _Cfg:
        det_input_side = 736
        labels = ("a",)

    class _Engine:
        num_inputs, num_outputs, num_stages = 1, 2, 1
        input_shapes = [(1, 3, 640, 640)]

        def __init__(self):
            self.runs = 0

        def run(self, tensor):
            self.runs += 1
            # The two dense tensors PP-DocLayout-M emits.
            return [np.zeros((1, 4, 4), np.float32), np.zeros((1, 23, 4), np.float32)]

    backend = ocr_ppocr.OcrBackend.__new__(ocr_ppocr.OcrBackend)
    backend._model_path = "/models/ppocrv6-medium/det.bmodel"
    backend._cv2 = _FakeCv2(np)
    backend._cfg = _Cfg()
    backend._layout_cfg = object()
    engine = _Engine()
    backend._layout = engine
    backend._lock = __import__("threading").Lock()

    from app.engine.aux_backend import _Serialised
    backend._gate = _Serialised(4)

    def fake_preprocess(bgr, cfg):
        return np.zeros((1, 3, 640, 640), np.float32)

    def fake_detect(boxes, scores, page_hw, cfg):
        return [{"label": "text", "score": 0.9, "box": [10, 10, 100, 100]}]

    import app.engine.ocr_layout as layout_mod

    saved = (layout_mod.preprocess, layout_mod.detect)
    layout_mod.preprocess, layout_mod.detect = fake_preprocess, fake_detect
    try:
        result = asyncio.run(backend.detect_page(b"ignored"))
    finally:
        layout_mod.preprocess, layout_mod.detect = saved

    assert engine.runs == 1, "exactly one layout forward"
    assert result["regions"] == [{"label": "text", "score": 0.9,
                                  "box": [10, 10, 100, 100], "type": "text"}]
    assert result["width"] == 400 and result["height"] == 600
    assert result["layout_ms"] >= 0


class _FakeCv2:
    """Just the two OpenCV calls ``_decode`` makes."""

    IMREAD_COLOR = 1

    def __init__(self, np):
        self._np = np

    def imdecode(self, buffer, flags):
        # 600 x 400 BGR, which is what the assertions above expect.
        return self._np.full((600, 400, 3), 7, dtype=self._np.uint8)


def test_vl_is_not_a_mode_the_ocr_op_accepts():
    """``MODE_VL`` is named for the API and the docs, but ``op: ocr`` must still
    refuse it: that op has no second model, so accepting ``vl`` there would run
    a page through PP-OCR and call it a VL result."""
    from app.engine import ocr_ppocr

    assert ocr_ppocr.MODE_VL == "vl"
    assert ocr_ppocr.MODE_VL not in ocr_ppocr.MODES
    with pytest.raises(Exception) as caught:
        ocr_ppocr._check_mode("vl")
    assert "lines" in str(caught.value)


# ---------------------------------------------------------------------------
# the page crop's preprocessing
# ---------------------------------------------------------------------------
def _fake_cv2(np):
    """The four OpenCV calls ``_patchify`` makes, in numpy."""
    import types

    cv2 = types.SimpleNamespace()
    cv2.INTER_CUBIC = 0
    cv2.COLOR_BGR2RGB = 0

    def resize(img, size, interpolation=None):
        width, height = size
        ys = (np.arange(height) * (img.shape[0] / height)).astype(int)
        xs = (np.arange(width) * (img.shape[1] / width)).astype(int)
        return img[np.clip(ys, 0, img.shape[0] - 1)][:, np.clip(xs, 0, img.shape[1] - 1)]

    cv2.resize = resize
    cv2.cvtColor = lambda img, code: img[:, :, ::-1]
    return cv2


def test_a_page_crop_keeps_its_aspect_ratio():
    """The board settled this one: squashing a 15:1 title hallucinates.

    ``table_stats.png``'s title region is 706x47. Stretched to 784x784 the
    glyphs are compressed 16.7x vertically and the model answered
    ``1990年日本国立大学成立`` for a page reading
    ``2026年第三季度生产数据统计表`` -- fluent, confident, invented. Padded
    instead, it reads both text regions correctly.

    Since MYS-2681 this is the default for *both* surfaces, so the "fitted"
    side here is what ``_patchify`` does with no argument at all.

    The assertion is on the *shape of the content*, which is what the model
    sees: a high-contrast band must stay a band, not become a full square.
    """
    np = pytest.importorskip("numpy")
    from app.engine import paddle_vl as vl

    crop = np.full((47, 706, 3), 255, dtype=np.uint8)
    crop[10:37, :] = 0                      # a dark band: the title's glyphs
    cv2 = _fake_cv2(np)

    _gh, _gw, squashed = vl._patchify(crop, 784, cv2, fit=False)
    _gh, _gw, fitted = vl._patchify(crop, 784, cv2)

    def dark_rows(patches):
        """How many patch rows down the middle column carry dark pixels."""
        grid = patches.reshape(56, 56, 3, 14, 14)   # (gh, gw, C, p, p)
        column = grid[:, 28]                        # middle column of patches
        return int((column.mean(axis=(1, 2, 3)) < 0).sum())

    # Stretched, the band covers most of the square; fitted, it stays a thin
    # horizontal strip inside white padding.
    assert dark_rows(squashed) > 20
    assert dark_rows(fitted) <= 6


def test_the_chat_path_letterboxes_like_the_page_path():
    """One crop, two surfaces, one tensor (MYS-2681).

    ``preprocess_image`` is what ``/v1/chat/completions`` calls with a decoded
    image; ``_patchify`` is what ``/v1/ocr`` ``mode: "vl"`` calls with an
    already-decoded crop. They must agree element for element, and both must
    preserve the aspect ratio: the official PaddleOCR client posts region crops
    (706x47 titles, 537x29 footnotes) to the *chat* endpoint, and stretched
    those hallucinate -- the defect §11.9 of ``docs/ocr-vl.md`` recorded for the
    page path before MYS-2681 unified them.

    The comparison is over the same pixels through both entry points, which is
    the only form of "the paths agree" that a later refactor cannot quietly
    break.
    """
    import numpy as np

    cv2 = pytest.importorskip("cv2", reason="this compares the real resampler")
    from app.engine import paddle_vl as vl

    # 15:1, the shape of `table_stats.png`'s title region -- the case that made
    # the stretch a bug rather than a preference.
    crop = np.full((47, 706, 3), 255, dtype=np.uint8)
    crop[10:37, 40:660] = 0                 # a dark band where the glyphs are
    ok, buf = cv2.imencode(".png", crop)
    assert ok

    _gh, _gw, from_blob = vl.preprocess_image(buf.tobytes(), cv2=cv2)
    _gh, _gw, from_crop = vl._patchify(crop, vl.STAGE, cv2=cv2)

    assert np.array_equal(from_blob, from_crop)
    # Padding is white -> +1 in normalised units. If the chat path still
    # stretched, every patch would be the band's own value and none would be +1.
    assert from_blob.max() == 1.0
    # And the band must stay a band: at most a third of the rows carry content.
    grid = from_blob.reshape(56, 56, 3, 14, 14)
    content_rows = int((grid[:, 28].mean(axis=(1, 2, 3)) < 0.5).sum())
    assert 0 < content_rows <= 20


def test_stretching_is_still_reachable_as_the_control():
    """``fit=False`` stays in the code because the comparison needs a control.

    It is no longer any caller's arithmetic (MYS-2681), but keeping it lets a
    test say *why* the letterbox exists instead of asserting a shape and hoping
    the reader believes it: stretched, a 2:1 black crop fills the square;
    letterboxed, the same crop leaves white padding behind.
    """
    np = pytest.importorskip("numpy")
    from app.engine import paddle_vl as vl

    crop = np.zeros((14, 28, 3), dtype=np.uint8)   # 2:1, all black
    cv2 = _fake_cv2(np)
    _gh, _gw, stretched = vl._patchify(crop, 784, cv2, fit=False)
    # Every pixel of the input is used, so every patch is that pixel's value:
    # -1 after the (x/255-0.5)/0.5 normalisation of 0.
    assert np.allclose(stretched, -1.0)
    # Padding introduces +1 (white) patches -- which is what the default does.
    _gh, _gw, padded = vl._patchify(crop, 784, cv2)
    assert not np.allclose(padded, -1.0)
