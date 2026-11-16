"""Whole-page PaddleOCR-VL: PP-DocLayout-M -> per-region task prompt -> Markdown.

This is ``mode: "vl"`` of ``/v1/ocr``. A page image goes in; one Markdown page
comes out, where every region was recognised by PaddleOCR-VL-1.5 with the
instruction PaddleX's own pipeline gives that region's class, and a table's
content is **HTML with its merged cells restored**.

Four things live here, and each has a specific oracle:

* **The label -> instruction map** (:func:`prompt_for`) -- transcribed from
  ``paddlex/configs/pipelines/PaddleOCR-VL-1.5.yaml`` and the pipeline's
  ``_paddleocr_vl_collect_page_vlm_entries_core``. Not a heuristic: the model
  was trained with these exact strings, and ``OCR:`` versus ``Table
  Recognition:`` alone changes the answer from prose to OTSL.
* **OTSL -> HTML** (:func:`otsl_to_html`) -- a port of PaddleX's
  ``convert_otsl_to_html`` (``uilts.py``), including its row-padding rule and
  its ``<lcel>``/``<ucel>``/``<xcel>`` span arithmetic. ``tests/data/ocr/
  otsl_golden.json`` holds the same inputs put through PaddleX's own function,
  so the port is checked against the reference rather than against itself.
* **Per-region answer clean-up** (:func:`normalize_content`) -- the reference's
  post-VL steps: the repetitive-content truncation (a stuck decode repeats one
  row forever) and the ``\\(…\\)``/``\\[…\\]`` delimiters it rewrites into
  ``$…$``/``$$…$$``. Both are ``pipeline.py``'s, applied in its order.
* **Reading order and Markdown** -- :mod:`app.engine.ocr_layout` does both for
  ``mode: "layout"`` already (PaddleX's ``xycut_enhanced`` and its label ->
  format table), so a ``vl`` page reuses them instead of growing a second
  implementation that could order the same page differently.

**No model is loaded or reached for here.** This module is pure host code: the
one thing it cannot do itself -- run the VLM on a crop -- arrives as the
``recognise`` callable handed to :func:`recognise_page`. On the board that
callable is ``PaddleVlBackend.recognise_block``, which takes the engine's lock,
so a page queues behind chat requests exactly as another chat request would, and
no HTTP loopback is involved. In a test it is a lambda, which is what makes the
ordering, the prompt map and the OTSL conversion testable without an NPU.

**One non-obvious constraint, measured on the board** (``docs/ocr-vl.md`` §6.1):
PP-DocLayout-M and the 3.3 GB VL bmodel cannot be loaded into one process --
bmrt answers ``load_bmodel failed``. They live in two workers, which is why the
layout pass and the recognition passes are two RPCs to two models rather than
one worker doing both.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Sequence

from .ocr_layout import (
    FIGURE_PLACEHOLDERS,
    MARKDOWN_IGNORE_LABELS,
    _collapse_newlines,
    _normalize_newlines,
    order_regions,
)

# ---------------------------------------------------------------------------
# the label -> instruction map
# ---------------------------------------------------------------------------
#: The instruction the official pipeline gives each PP-DocLayout class.
#:
#: ``pipeline.py``'s ``_paddleocr_vl_collect_page_vlm_entries_core`` starts from
#: ``text_prompt = "OCR:"`` and overrides five cases: ``table``, ``chart`` (when
#: chart recognition is on -- it is off in the shipped yaml, and a chart is then
#: treated as an image), any label containing ``formula`` except
#: ``formula_number``, ``spotting`` and ``seal``. Everything else -- including
#: classes this service has never seen -- keeps ``OCR:``, which is why the map
#: below is a set of exceptions rather than a whitelist.
PROMPT_OCR = "OCR:"
PROMPT_TABLE = "Table Recognition:"
PROMPT_FORMULA = "Formula Recognition:"

#: Labels whose content is a picture, not text. The reference drops these before
#: recognition (``layout_prep_cfg["image_labels"]``: ``IMAGE_LABELS`` plus
#: ``chart`` and ``seal``, since both recognisers are off in the shipped yaml),
#: so a ``vl`` page emits a placeholder for them instead of asking the VLM to
#: read a photograph.
SKIP_LABELS = frozenset({"image", "header_image", "footer_image", "chart",
                         "seal"})


def prompt_for(label: str) -> str | None:
    """The instruction for a layout label, or ``None`` when the block is skipped.

    Mirrors the reference's branch order exactly, because the branches are not
    independent: ``formula_number`` contains "formula" and must *not* be typeset
    (the reference excludes it by name), while ``inline_formula`` and
    ``display_formula`` must be.
    """
    if label in SKIP_LABELS:
        return None
    if label == "table":
        return PROMPT_TABLE
    if "formula" in label and label != "formula_number":
        return PROMPT_FORMULA
    return PROMPT_OCR


# ---------------------------------------------------------------------------
# per-region answer clean-up
# ---------------------------------------------------------------------------
#: PaddleX's ``min_count`` for the repetition cut: 5000 characters for a table,
#: 50 for anything else. A table legitimately repeats ``<fcel>`` hundreds of
#: times, so the same threshold would truncate a good table.
REPEAT_MIN_COUNT_TABLE = 5000
REPEAT_MIN_COUNT_TEXT = 50


def _find_shortest_repeating_substring(s: str) -> str | None:
    """``uilts.find_shortest_repeating_substring``: the unit of ``ababab``."""
    for i in range(1, len(s) // 2 + 1):
        if len(s) % i:
            continue
        unit = s[:i]
        if unit * (len(s) // i) == s:
            return unit
    return None


def _find_repeating_suffix(s: str, min_len: int = 8,
                           min_repeats: int = 5):
    """``uilts.find_repeating_suffix``: ``(prefix, unit, count)`` or ``None``."""
    for i in range(len(s) // min_repeats, min_len - 1, -1):
        unit = s[-i:]
        if not s.endswith(unit * min_repeats):
            continue
        count = 0
        rest = s
        while rest.endswith(unit):
            rest = rest[:-i]
            count += 1
        return s[:len(s) - count * i], unit, count
    return None


def truncate_repetitive_content(content: str, *, min_count: int,
                                line_threshold: int = 10,
                                char_threshold: int = 10,
                                min_len: int = 10) -> str:
    """``uilts.truncate_repetitive_content``, transcribed.

    Why it exists: ``lm_head`` fuses the argmax and this service decodes
    greedily for up to the whole context, so a model that falls into a loop
    emits the same row until the sequence ends. Cutting the tail is what keeps
    one stuck region from turning a page into a wall of copies -- and it is the
    reference's own rule, so a truncated answer is comparable with its answer.
    """
    if len(content) < min_count:
        return content
    stripped = content.strip()
    if not stripped:
        return content

    # 1. phrase-level suffix repetition in a long single line
    if "\n" not in stripped and len(stripped) > 100:
        match = _find_repeating_suffix(stripped, min_len=8, min_repeats=5)
        if match:
            prefix, unit, count = match
            if len(unit) * count > len(stripped) * 0.5:
                return prefix

    # 2. the whole string is one short unit repeated
    if "\n" not in stripped and len(stripped) > min_len:
        unit = _find_shortest_repeating_substring(stripped)
        if unit and len(stripped) // len(unit) >= char_threshold:
            return unit

    # 3. one line repeated over and over, dominating the answer
    lines = [line.strip() for line in content.split("\n") if line.strip()]
    if len(lines) < line_threshold:
        return content
    counts: dict[str, int] = {}
    for line in lines:
        counts[line] = counts.get(line, 0) + 1
    common, count = max(counts.items(), key=lambda kv: kv[1])
    if count >= line_threshold and count / len(lines) >= 0.8:
        return common
    return content


#: ``(\(…\)|\[…\])`` pairs the reference rewrites. PaddleOCR-VL emits LaTeX in
#: both spellings; Markdown renderers only understand the dollar form, so the
#: reference normalises it rather than leaving a caller to guess. The double
#: brackets are collapsed *before* the single ones, in that order, because the
#: single-bracket replacement would otherwise consume half of ``\[\[``.
_FORMULA_PAIRS = (("\\(", "\\)"), ("\\[", "\\]"))


def normalize_content(text: str, label: str) -> str:
    """The reference's post-VL treatment of one region's answer.

    Order matters and is ``pipeline.py``'s: truncate first (so the delimiter
    rewrite runs on the text that is actually kept), then rewrite the formula
    delimiters, then convert a table's OTSL to HTML.
    """
    min_count = (REPEAT_MIN_COUNT_TABLE if label == "table"
                 else REPEAT_MIN_COUNT_TEXT)
    text = truncate_repetitive_content(text, min_count=min_count)
    if any(left in text and right in text for left, right in _FORMULA_PAIRS):
        text = text.replace("$", "")
        text = (text.replace("\\(", " $ ").replace("\\)", " $")
                .replace("\\[\\[", "\\[").replace("\\]\\]", "\\]")
                .replace("\\[", " $$ ").replace("\\]", " $$ "))
        if label == "formula_number":
            text = text.replace("$", "")
    if label == "table":
        html_table = otsl_to_html(text)
        if html_table:
            text = html_table
    return text


# ---------------------------------------------------------------------------
# OTSL -> HTML
# ---------------------------------------------------------------------------
#: The six OTSL tags. They are ordinary vocabulary entries in the model's
#: tokenizer (``added_tokens`` with ``special: false``), which is why they reach
#: here as text at all -- see ``PaddleVlBackend.tokenizer_decode``.
OTSL_NL = "<nl>"
OTSL_FCEL = "<fcel>"
OTSL_ECEL = "<ecel>"
OTSL_LCEL = "<lcel>"
OTSL_UCEL = "<ucel>"
OTSL_XCEL = "<xcel>"
OTSL_TAGS = (OTSL_NL, OTSL_FCEL, OTSL_ECEL, OTSL_LCEL, OTSL_UCEL, OTSL_XCEL)

_OTSL_TAG_RE = re.compile("|".join(re.escape(t) for t in OTSL_TAGS))
#: One cell-and-its-text, as ``uilts.OTSL_FIND_PATTERN`` reads it: a tag, then
#: everything up to the next tag. Used by the row padder.
_OTSL_CELL_RE = re.compile(
    f"(?:{ '|'.join(re.escape(t) for t in (OTSL_FCEL, OTSL_ECEL, OTSL_NL, OTSL_LCEL, OTSL_UCEL, OTSL_XCEL)) })"
    r".*?(?=(?:<fcel>|<ecel>|<nl>|<lcel>|<ucel>|<xcel>)|$)",
    re.DOTALL)


def _split_row_tokens(tokens: list[str]) -> list[list[str]]:
    """Group a tag stream into rows, one list of tags per ``<nl>``.

    ``uilts.otsl_parse_texts``'s ``itertools.groupby`` idiom, written out: a run
    of consecutive non-``<nl>`` tags is one row. Empty rows (two ``<nl>`` in a
    row) disappear, which is what the reference does and why a stray blank line
    in the answer costs nothing.
    """
    rows: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token == OTSL_NL:
            if current:
                rows.append(current)
                current = []
            continue
        current.append(token)
    if current:
        rows.append(current)
    return rows


def _pad_to_square(otsl: str) -> str:
    """``uilts.otsl_pad_to_sqr_v2``: give every row the same number of cells.

    A model's rows are not always the same width -- a truncated last row, or a
    row that leaned on an adjacent span, arrives short. The reference picks the
    width that minimises total ``|len - width|`` across rows (never narrower
    than the widest row's last ``<fcel>``, so it cannot cut a cell that carries
    text) and pads with ``<ecel>``. Reproducing the choice, rather than picking
    ``max``, is what makes the same answer produce the same HTML: on a ragged
    table the two differ, and the reference's HTML is the one the x86 comparison
    was made against.
    """
    if OTSL_NL not in otsl:
        return otsl + OTSL_NL
    rows = []
    for line in otsl.split(OTSL_NL):
        if not line:
            continue
        cells = _OTSL_CELL_RE.findall(line)
        if not cells:
            continue
        # The widest prefix ending in a text-bearing cell: a row may not be
        # padded narrower than that, or a cell with content would be dropped.
        min_len = 0
        for i, cell in enumerate(cells):
            if cell.startswith(OTSL_FCEL):
                min_len = i + 1
        rows.append({"cells": cells, "total": len(cells), "min": min_len})
    if not rows:
        return OTSL_NL

    global_min = max(row["min"] for row in rows)
    max_total = max(row["total"] for row in rows)
    best_width, best_cost = max(global_min, max_total), None
    for width in range(global_min, max(global_min, max_total) + 1):
        cost = sum(abs(row["total"] - width) for row in rows)
        if best_cost is None or cost < best_cost:
            best_cost, best_width = cost, width

    repaired = []
    for row in rows:
        cells = row["cells"]
        if len(cells) > best_width:
            cells = cells[:best_width]
        else:
            cells = cells + [OTSL_ECEL] * (best_width - len(cells))
        repaired.append("".join(cells))
    return OTSL_NL.join(repaired) + OTSL_NL


@dataclass
class _Cell:
    """One OTSL cell: its text and the span it occupies."""

    text: str
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1


def _count_span(rows: list[list[str]], row: int, col: int, start: int,
                horizontal: bool, tags: tuple[str, ...]) -> int:
    """How many cells a span covers, walking right (or down) from ``(row, col)``.

    ``uilts.otsl_parse_texts``'s ``count_right``/``count_down``: a span starts at
    ``start`` (``col + 1`` for a rightward walk, because the anchor cell itself
    is not counted) and extends while the cell is one of ``tags``, stopping at
    the row's end.
    """
    span = 0
    if horizontal:
        index = start
        while index < len(rows[row]) and rows[row][index] in tags:
            index += 1
            span += 1
        return span
    index = start
    while index < len(rows) and col < len(rows[index]) and rows[index][col] in tags:
        index += 1
        span += 1
    return span


def _parse_cells(padded: str) -> tuple[list[_Cell], list[list[str]]]:
    """``uilts.otsl_parse_texts``: tags + their text -> cells with spans.

    The text of a cell is whatever follows its tag; ``<ecel>`` and the span-only
    tags carry none. ``<lcel>``/``<xcel>`` mean "the cell to my left continues
    into me", ``<ucel>``/``<xcel>`` mean the same upward, and ``<xcel>`` does
    both -- which is exactly how a 2-D merged block is spelled.
    """
    tokens = _OTSL_TAG_RE.findall(padded)
    rows = _split_row_tokens(tokens)
    if not rows:
        return [], []

    # Interleave: the reference walks the *text* stream (tags and text pieces
    # together) so a cell's text follows its tag. Reconstructing that stream
    # from the padded string is what keeps the association exact.
    pieces = [piece for piece in re.split(
        "(" + "|".join(re.escape(t) for t in OTSL_TAGS) + ")", padded)
        if piece.strip()]
    # Re-pad the piece stream to the padded width: `_pad_to_square` may have
    # added trailing `<ecel>` that carry no text, and may have cut cells off the
    # end; both are already reflected in `rows`.
    texts: list[str] = []
    text_index = 0
    for row in rows:
        for tag in row:
            texts.append(tag)
            if text_index < len(pieces) and pieces[text_index] == tag:
                text_index += 1
                if (text_index < len(pieces)
                        and pieces[text_index] not in OTSL_TAGS):
                    texts.append(pieces[text_index])
                    text_index += 1
        texts.append(OTSL_NL)
        if text_index < len(pieces) and pieces[text_index] == OTSL_NL:
            text_index += 1

    cells: list[_Cell] = []
    row_index = col_index = 0
    for i, text in enumerate(texts):
        if text in (OTSL_FCEL, OTSL_ECEL):
            cell_text = ""
            offset = 1
            if text != OTSL_ECEL:
                cell_text = texts[i + 1] if i + 1 < len(texts) else ""
                offset = 2
            rowspan = colspan = 1
            next_right = texts[i + offset] if i + offset < len(texts) else ""
            next_below = ""
            if row_index + 1 < len(rows) and col_index < len(rows[row_index + 1]):
                next_below = rows[row_index + 1][col_index]
            if next_right in (OTSL_LCEL, OTSL_XCEL):
                colspan += _count_span(rows, row_index, col_index, col_index + 1,
                                       True, (OTSL_LCEL, OTSL_XCEL))
            if next_below in (OTSL_UCEL, OTSL_XCEL):
                rowspan += _count_span(rows, row_index, col_index, row_index + 1,
                                       False, (OTSL_UCEL, OTSL_XCEL))
            cells.append(_Cell(text=cell_text.strip(), row=row_index,
                               col=col_index, rowspan=rowspan, colspan=colspan))
        if text in OTSL_TAGS and text != OTSL_NL:
            col_index += 1
        elif text == OTSL_NL:
            row_index += 1
            col_index = 0
    return cells, rows


def otsl_to_html(otsl: str) -> str:
    """An OTSL table -> ``<table>`` HTML with ``rowspan``/``colspan`` restored.

    Returns ``""`` for input that holds no cells, which is what makes the caller
    fall back to the raw answer instead of replacing it with an empty table: a
    model that answered prose to a ``Table Recognition:`` prompt produces no
    ``<fcel>`` at all, and an empty table would silently discard its answer.

    The port is checked against PaddleX's own ``convert_otsl_to_html`` by
    ``tests/test_ocr_vl_page_mode.py``: ``tests/data/ocr/otsl_golden.json``
    records both the input and the reference's output, including the ragged and
    span-heavy cases where the padding rule actually decides the result. The
    output is byte-identical to the reference, whitespace included -- the HTML
    lands inside a Markdown page, where a stray two-space line ending would be a
    hard break, so a pretty-printed variant would not be interchangeable.
    """
    padded = _pad_to_square(otsl.strip())
    cells, rows = _parse_cells(padded)
    if not cells or not rows:
        return ""
    num_rows = len(rows)
    num_cols = max(len(row) for row in rows)

    # The grid the reference builds: every covered position maps to the cell
    # that owns it, so a rowspan's lower rows know to skip that column.
    grid: list[list[_Cell | None]] = [[None] * num_cols for _ in range(num_rows)]
    for cell in cells:
        for i in range(min(cell.row, num_rows), min(cell.row + cell.rowspan, num_rows)):
            for j in range(min(cell.col, num_cols),
                           min(cell.col + cell.colspan, num_cols)):
                grid[i][j] = cell

    body = []
    for i in range(num_rows):
        body.append("<tr>")
        for j in range(num_cols):
            cell = grid[i][j]
            if cell is None:
                # A position no cell covers -- a `<lcel>` with nothing to its
                # left, say. The reference still emits an empty `<td>` there,
                # because its grid is pre-filled with blank cells and an
                # uncovered slot is simply one of them. Dropping it would shift
                # every later column left by one.
                body.append("<td></td>")
                continue
            if cell.row != i or cell.col != j:
                continue
            attributes = ""
            if cell.rowspan > 1:
                attributes += f' rowspan="{cell.rowspan}"'
            if cell.colspan > 1:
                attributes += f' colspan="{cell.colspan}"'
            body.append(f"<td{attributes}>{html.escape(cell.text)}</td>")
        body.append("</tr>")
    return f"<table>{''.join(body)}</table>"


# ---------------------------------------------------------------------------
# the page's Markdown
# ---------------------------------------------------------------------------
def page_markdown(blocks: Sequence[dict]) -> str:
    """Ordered ``vl`` blocks -> the page's Markdown.

    Reuses ``ocr_layout``'s label -> format table -- a title is still ``#``, body
    text still keeps its paragraph breaks, and the same labels are still
    skipped -- because two modes that render the same page differently for no
    reason is a bug waiting to be reported. Exactly **two** rules differ, and
    both are the point of this mode:

    * a **table** is emitted as its HTML, verbatim. ``layout`` mode wraps the
      region's OCR lines in a "structure not restored" comment because it has no
      structure to give; here the model produced OTSL and
      :func:`otsl_to_html` turned it into ``rowspan``/``colspan``, so the comment
      would be false. A table whose answer never became HTML (the model replied
      with prose) falls back to the same plain text ``layout`` mode gives.
    * a **figure** is the placeholder alone. ``layout`` mode appends whatever
      OCR read inside the region; in ``vl`` mode the region was not recognised
      at all -- no VLM was asked -- so there is nothing to append, and the
      block's own text *is* the placeholder.

    Everything else is ``ocr_layout.to_markdown``'s joining rule: blocks are
    separated by one blank line and an empty block contributes nothing.
    """
    parts: list[str] = []
    for block in blocks:
        label = block["label"]
        if label in MARKDOWN_IGNORE_LABELS:
            continue
        text = (block.get("text") or "").strip()
        if label in FIGURE_PLACEHOLDERS:
            piece = FIGURE_PLACEHOLDERS.get(label, "[图片]")
        elif label == "table":
            piece = text if _is_html_table(text) else TABLE_TEXT_NOTE + text
        elif label == "doc_title":
            piece = _title_block(text, 1)
        elif label in ("paragraph_title", "abstract_title", "reference_title",
                       "content_title"):
            piece = _title_block(text, 2)
        elif label in ("formula", "display_formula", "inline_formula"):
            # The model's own LaTeX, already normalised to the dollar form by
            # ``normalize_content``; wrapping it again would double the fence.
            piece = text
        else:
            piece = _normalize_newlines(text)
        if piece.strip():
            parts.append(piece)
    return "\n\n".join(parts)


def _title_block(text: str, level: int) -> str:
    """``ocr_layout._title_block``: a heading, soft line breaks collapsed."""
    return _collapse_newlines(f"{'#' * level} {text}")


def _is_html_table(text: str) -> bool:
    return text.lstrip().startswith("<table") and text.rstrip().endswith("</table>")


#: What a table region gets when its answer was prose rather than OTSL. The same
#: wording ``layout`` mode uses, because the situation really is the same: text
#: with no structure recovered.
TABLE_TEXT_NOTE = "<!-- 表格：模型未输出表格结构，以下为纯文本 -->\n\n"


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------
#: ``merge_blocks``'s ``non_merge_labels``: ``layout_prep_cfg["image_labels"]``
#: (the picture labels) plus ``table``. A table never joins its neighbours, and
#: nothing joins a picture -- both are expressed by excluding them here.
MERGE_EXEMPT_LABELS = frozenset(SKIP_LABELS | {"table"})

#: ``merge_blocks.is_aligned``: two edges within this many pixels are "aligned".
MERGE_ALIGN_TOLERANCE_PX = 5

#: ``merge_blocks``'s aspect cut: a stacked group at 3:1 or taller is emitted as
#: separate blocks rather than merged into one crop.
MERGE_MAX_ASPECT = 3.0

#: The reference's default ``max_new_tokens`` for one region
#: (``_paddleocr_vl_run_vl_recognition_batches``). A table needs the room -- 40
#: rows is a few thousand OTSL tokens; everything else stops at its EOS long
#: before this.
MAX_NEW_TOKENS = 4096

#: The board's measured decode rate for this model (``docs/ocr-vl.md`` §6:
#: 13.5-13.8 ms/token on ``.157``). Used only to size timeouts, never to decide
#: anything about an answer.
DECODE_MS_PER_TOKEN = 13.6


#: The most tokens an answer can hold: the bmodel's SEQLEN (2048) minus the
#: prompt (797 for a 784-stage crop, measured in ``docs/ocr-vl.md`` §10.5) and
#: the one row the first generated token comes out of.
MAX_ANSWER_TOKENS = 2048 - 797 - 1


def region_timeout_s(max_new_tokens: int = MAX_NEW_TOKENS) -> float:
    """What one region's recognition may cost before it counts as wedged.

    ``max_new_tokens`` at the measured decode rate, plus 30 s for the vit and the
    prefill (786 ms measured for a 784-stage crop) and for a queue slot behind
    somebody else's request. Deliberately generous: a page is a long request, and
    timing out a table that is still producing cells would waste everything it
    had already done.
    """
    return max_new_tokens * DECODE_MS_PER_TOKEN / 1e3 + 30.0


def effective_max_new(max_new_tokens: int | None = None) -> int:
    """The per-region decode budget, clamped to what the model's context allows.

    A prompt is 797 tokens and the bmodel's SEQLEN is 2048, so an answer can be
    at most ~1250 tokens however large a budget a caller asks for. Clamping here
    rather than letting the engine stop at the context edge means the block comes
    back with ``length`` as its reason instead of an engine error -- and it is
    why :data:`MAX_NEW_TOKENS` (the reference's 4096) is a request, not a
    promise.
    """
    wanted = MAX_NEW_TOKENS if max_new_tokens is None else int(max_new_tokens)
    return max(1, min(wanted, MAX_ANSWER_TOKENS))


def page_timeout_s(regions: int, max_new_tokens: int = MAX_NEW_TOKENS) -> float:
    """A whole page's bound: per-region cost times regions, plus the layout pass.

    The layout pass runs on the other worker and is bounded separately, but it
    is serialised behind any OCR request in flight, so its own bound (a few
    seconds normally) is added rather than assumed to be free.
    """
    return region_timeout_s(max_new_tokens) * max(1, int(regions)) + 60.0


async def run_vl_page(ocr_client, vl_client, image_b64: str, req_id: str) -> dict:
    """A whole page through both models: layout, then recognition.

    The one place the two-worker dance lives, so ``/v1/ocr`` and the MCP tool
    cannot disagree about it. Takes *clients* rather than a request or a model
    name: the callers resolve their models differently (the route by HTTP code,
    the tool by a skipped stage's reason), and both then hand over something
    that can answer ``detect_page``/``ocr_page``.

    Returns the page in the API's response shape. An empty page -- a blank scan
    with no detected region -- is a valid answer with no blocks, not an error:
    ``to_markdown`` of nothing is "", and a caller that wanted "did this page
    have anything on it" can see that in ``blocks``.
    """
    detected = await ocr_client.detect_page(f"{req_id}-layout", image_b64)
    regions = detected.get("regions") or []
    base = {"mode": "vl", "text": "", "lines": [], "blocks": [],
            "width": int(detected.get("width") or 0),
            "height": int(detected.get("height") or 0),
            "det_ms": 0.0, "rec_ms": 0.0,
            "layout_ms": float(detected.get("layout_ms") or 0.0),
            "vl_ms": 0.0, "vl_tokens": 0}
    if not regions:
        return base
    page = await vl_client.ocr_page(f"{req_id}-vl", image_b64, regions)
    return {**base, **page, "det_ms": 0.0, "rec_ms": 0.0,
            "layout_ms": base["layout_ms"]}


def require_vl_model(request) -> str:
    """The loaded ``ocr_vl`` model a ``vl`` page will use, or a 409 saying which.

    A page needs **two** models: the OCR model's layout detector (PP-DocLayout-M)
    and PaddleOCR-VL-1.5 itself. They are two workers because the two bmodels
    cannot share a process (``docs/ocr-vl.md`` §6.1), and the VLM is not in
    ``AUX_KINDS`` -- it is 3.3 GB resident and an operator loads it deliberately,
    so it is refused rather than auto-loaded.

    Raising here rather than in the API keeps the message beside the reason and
    lets the MCP tool reuse it. The status is 409 (not 400): the request is
    well-formed and would work once an operator loads the model, which is exactly
    what 409 means on every other route of this service.
    """
    from fastapi import HTTPException

    info = request.app.state.models.best_loaded("ocr_vl")
    if info is None:
        raise HTTPException(
            status_code=409,
            detail='mode="vl" 需要两个模型同时加载：版面模型 PP-DocLayout-M（随 OCR 模型提供）'
                   "和 PaddleOCR-VL-1.5。现在 PaddleOCR-VL-1.5 没有加载，请在控制台的"
                   "「模型」页加载它；如果只想用版面 + PP-OCR（表格不还原结构），"
                   '可以改用 mode="layout"')
    return info.model_id


@dataclass
class PageResult:
    """What ``mode: "vl"`` returns, before the API shapes it."""

    markdown: str
    blocks: list[dict]
    width: int
    height: int
    layout_ms: float = 0.0
    vl_ms: float = 0.0
    vl_tokens: int = 0
    #: Regions the detector found but the VLM was not asked to read (a picture,
    #: a chart with recognition off). Reported so "12 boxes, 9 blocks" is not a
    #: mystery.
    skipped: list[dict] = field(default_factory=list)


def block_type(label: str) -> str:
    """The response's coarse ``type`` for a PP-DocLayout label.

    Delegates to the ``ocr`` backend's table so the two modes cannot classify
    the same label differently -- the response schemas are the same object.
    """
    from .ocr_ppocr import _block_type

    return _block_type(label)


def _clip(box: Sequence[int], width: int, height: int) -> list[int]:
    """A detected box, clamped to the page and never degenerate.

    The detector can return a box a pixel outside the image or an empty one;
    cropping the first is fine (numpy clamps) but an empty crop would be handed
    to the vision tower as a zero-sized image. A 1-pixel box is the smallest
    thing that still produces a tensor.
    """
    x1, y1, x2, y2 = (int(v) for v in box)
    x1 = max(0, min(x1, width - 1))
    y1 = max(0, min(y1, height - 1))
    x2 = max(x1 + 1, min(x2, width))
    y2 = max(y1 + 1, min(y2, height))
    return [x1, y1, x2, y2]


def _aligned(a: float, b: float) -> bool:
    """``uilts.merge_blocks.is_aligned``: the 5-pixel tolerance."""
    return abs(a - b) <= MERGE_ALIGN_TOLERANCE_PX


def _alignment(bbox, previous) -> str:
    """``uilts.merge_blocks.get_alignment``: left, right, else centre."""
    if _aligned(bbox[0], previous[0]):
        return "left"
    if _aligned(bbox[2], previous[2]):
        return "right"
    return "center"


def _overlaps_a_non_merge_block(regions: Sequence[dict], index: int,
                               previous: int) -> bool:
    """``uilts.merge_blocks.overlapwith_other_box``.

    Uses ``overlap_ratio``'s **union** mode, which is what the reference's
    ``calculate_overlap_ratio`` defaults to -- not the "smaller box" form
    ``ocr_layout``'s own ``overlap_ratio`` uses for its cross-layout test.
    """
    a, b = regions[index]["box"], regions[previous]["box"]
    hull = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
    for other_index, other in enumerate(regions):
        if other_index in (index, previous):
            continue
        if other["label"] not in MERGE_EXEMPT_LABELS:
            continue
        if _overlap_ratio_union(hull, other["box"]) > 0:
            return True
    return False


def _overlap_ratio_union(bbox1, bbox2) -> float:
    """``layout_parsing.utils.calculate_overlap_ratio(mode="union")``."""
    width = min(bbox1[2], bbox2[2]) - max(bbox1[0], bbox2[0])
    height = min(bbox1[3], bbox2[3]) - max(bbox1[1], bbox2[1])
    intersection = max(0, width) * max(0, height)
    area1 = max(0, bbox1[2] - bbox1[0]) * max(0, bbox1[3] - bbox1[1])
    area2 = max(0, bbox2[2] - bbox2[0]) * max(0, bbox2[3] - bbox2[1])
    union = area1 + area2 - intersection
    return intersection / union if union > 0 else 0.0


def merge_groups(regions: Sequence[dict]) -> list[list[int]]:
    """``uilts.merge_blocks``: which regions are read as one block.

    Ported because the *number* of regions in the response is one of the things
    the acceptance compares against the reference, and because the merge decides
    what the VLM is shown: a run of paragraphs recognised together keeps the
    reading context that recognising each on its own throws away.

    The rule is narrower than it looks and is not a general "join adjacent
    text". ``merge_blocks`` first splits the page into *mergeable* regions and
    *exempt* ones (:data:`MERGE_EXEMPT_LABELS` -- the picture labels and
    ``table``), then walks only the mergeable ones, comparing each with the
    previous **mergeable** region (not the previous region), and joins when:

    * ``is_cross`` -- two ``text`` blocks **side by side** on one line (right of
      each other, vertically overlapping, horizontal gap under 30 % of the
      wider one): halves of one sentence the detector split;
    * ``is_updown_align`` -- two ``text`` blocks **stacked**, sharing exactly one
      vertical edge (left *or* right, exclusive-or), the gap under half the
      taller one's height, and their hull covering an exempt region (a figure
      wedged between two paragraphs);
    * the group's stacked crop is not 3:1 or taller (``merge_blocks`` measures
      ``calc_merged_wh`` the same way).

    Returns index groups in page order, covering **every** region exactly once.
    An exempt region is its own single-member group, placed where it sits.
    """
    units: list[list[int]] = []
    for index, region in enumerate(regions):
        if (units and region["label"] not in MERGE_EXEMPT_LABELS
                and units[-1][0] is not None):
            previous_index = units[-1][-1]
            previous = regions[previous_index]
            if _joins(regions, region, previous, index, previous_index):
                units[-1].append(index)
                continue
        if region["label"] in MERGE_EXEMPT_LABELS:
            # A sentinel: nothing may join *into* an exempt unit. The reference
            # compares against the previous *mergeable* region, so an exempt one
            # breaks the run but never becomes a merge target.
            units.append([None, index])  # type: ignore[list-item]
        else:
            units.append([index])
    return [[i for i in unit if i is not None] for unit in units]


def _joins(regions: Sequence[dict], region: dict, previous: dict,
           index: int, previous_index: int) -> bool:
    """``merge_blocks``'s ``is_cross or is_updown_align``, plus the aspect cut."""
    bbox, previous_box = region["box"], previous["box"]
    label, previous_label = region["label"], previous["label"]
    # `calculate_projection_overlap_ratio(..., "horizontal")` is a fraction, so
    # "no overlap" is exactly 0 -- not `< some epsilon`.
    horizontal = _projection_overlap(bbox, previous_box, "horizontal")
    is_cross = (horizontal == 0 and label == "text"
                and label == previous_label
                and bbox[0] > previous_box[2]
                and bbox[1] < previous_box[3]
                and bbox[0] - previous_box[2]
                < max(previous_box[2] - previous_box[0], bbox[2] - bbox[0]) * 0.3)
    is_stacked = (horizontal > 0 and label == "text"
                  and label == previous_label
                  and bbox[3] >= previous_box[1]
                  and abs(bbox[1] - previous_box[3])
                  < max(previous_box[3] - previous_box[1],
                        bbox[3] - bbox[1]) * 0.5
                  and (_aligned(bbox[0], previous_box[0])
                       ^ _aligned(bbox[2], previous_box[2]))
                  and _overlaps_a_non_merge_block(regions, index, previous_index))
    return is_cross or is_stacked


def _group_aspect(regions: Sequence[dict], indices: Sequence[int]) -> float:
    """``calc_merged_wh``: the stacked crop's height / width."""
    boxes = [regions[index]["box"] for index in indices]
    width = max(box[2] - box[0] for box in boxes)
    height = sum(box[3] - box[1] for box in boxes)
    return (height / width) if width else float("inf")


def _projection_overlap(bbox1, bbox2, direction: str = "horizontal") -> float:
    """``layout_parsing.utils.calculate_projection_overlap_ratio``, union mode."""
    start, end = (0, 2) if direction == "horizontal" else (1, 3)
    intersection = min(bbox1[end], bbox2[end]) - max(bbox1[start], bbox2[start])
    if intersection <= 0:
        return 0.0
    union = max(bbox1[end], bbox2[end]) - min(bbox1[start], bbox2[start])
    return intersection / union if union > 0 else 0.0


def merge_regions(regions: Sequence[dict]) -> list[dict]:
    """Fold :func:`merge_groups`' groups into the region list a page renders.

    Two things happen to a group, and both are the reference's:

    * its members' crops are stacked into one image (:func:`_merge_crop`, which
      is ``uilts.merge_images``) and only the **first** member keeps that image
      -- the VLM reads the group once, and the rest of the group carries no
      content of its own (``block["img"] = None`` in ``merge_blocks``);
    * a group whose stacked image is 3:1 or taller is **not** merged at all:
      the reference emits its members separately in that case, because a tall
      strip of unrelated lines is not one text block.

    The returned dicts therefore carry ``crop`` (numpy, or ``None`` for a member
    whose content came from an earlier member of its group), ``group`` (the
    group's first index) and ``merged`` (how many regions the crop covers).
    """
    groups = merge_groups(regions)
    out: list[dict] = []
    for indices in groups:
        if len(indices) == 1:
            out.append({**regions[indices[0]], "group": indices[0], "merged": 1})
            continue
        boxes = [regions[i]["box"] for i in indices]
        width = max(box[2] - box[0] for box in boxes)
        height = sum(box[3] - box[1] for box in boxes)
        if width and height / width >= MERGE_MAX_ASPECT:
            # Too tall to be one block: keep the members apart, as the reference
            # does.
            for index in indices:
                out.append({**regions[index], "group": index, "merged": 1})
            continue
        aligns = _alignments_for(regions, indices)
        for position, index in enumerate(indices):
            out.append({**regions[index], "group": indices[0],
                        "merged": len(indices),
                        "merge_aligns": aligns if position == 0 else None})
    return out


def _alignments_for(regions: Sequence[dict], indices: Sequence[int]) -> list[str]:
    """The per-step alignment for one group, recomputed for the crop builder."""
    aligns = []
    for left, right in zip(indices, indices[1:]):
        bbox, previous = regions[right]["box"], regions[left]["box"]
        horizontal = _projection_overlap(bbox, previous, "horizontal")
        is_cross = (horizontal == 0 and bbox[0] > previous[2]
                    and bbox[1] < previous[3])
        aligns.append("center" if is_cross else _alignment(bbox, previous))
    return aligns


def _merge_crop(crops: Sequence, aligns: Sequence[str]) -> object:
    """``uilts.merge_images``: stack crops vertically, honouring each alignment.

    The reference does this in PIL; OpenCV is already a dependency of this
    module's caller and does the same three operations. The offsets are computed
    for the whole group first, exactly as the reference does, because a later
    step's alignment shifts every image placed before it -- pasting one at a
    time with only the local offset would left-align a centred group.
    """
    import numpy as np

    heights = [crop.shape[0] for crop in crops]
    total_height = sum(heights)
    offsets = [0] * len(crops)
    merged_width = crops[0].shape[1]
    for i in range(1, len(crops)):
        step_width = max(merged_width, crops[i].shape[1])
        align = aligns[i - 1] if i - 1 < len(aligns) else "center"
        if align == "center":
            shift, own = (step_width - merged_width) // 2, (step_width - crops[i].shape[1]) // 2
        elif align == "right":
            shift, own = step_width - merged_width, step_width - crops[i].shape[1]
        else:
            shift, own = 0, 0
        for k in range(i):
            offsets[k] += shift
        offsets[i] = own
        merged_width = step_width

    canvas = np.full((total_height, merged_width, 3), 255, dtype=np.uint8)
    y = 0
    for i, crop in enumerate(crops):
        canvas[y:y + heights[i], offsets[i]:offsets[i] + crop.shape[1]] = crop
        y += heights[i]
    return canvas


async def recognise_page(
    bgr,
    regions: Sequence[dict],
    *,
    recognise: Callable[[object, str], Awaitable[dict]],
    page_hw: tuple[int, int],
) -> PageResult:
    """Run the page: merge, order, recognise each region, render the Markdown.

    ``recognise(crop_bgr, task)`` is the ``ocr_vl`` backend's one-crop entry
    point. It takes the pixels, not an encoded image: the backend runs in this
    process, so a PNG round trip would only add a decode on the way back in. It
    also keeps this module free of OpenCV, which is what lets a test drive the
    whole page -- ordering, prompts, ``otsl_to_html``, the Markdown -- with a
    lambda on a laptop that has no Sophon OpenCV.

    A region whose recognition fails does not fail the page. The block comes
    back with its ``error`` set and no text, and the Markdown skips it: a page
    that lost one table is worth more to a caller than a 503, and the response
    says which region is missing rather than pretending the page had none.

    A merged group is recognised **once**, from the stacked crop, and its first
    member carries the answer. That is the reference's shape
    (``merge_blocks`` sets every later member's image to ``None``), and it is
    why the response can report more blocks than the VLM ran on.
    """
    import time

    height, width = page_hw
    ordered = order_regions(merge_regions(regions), (height, width))
    # Reading order decides which group is recognised in which order; the group
    # *id* survives the re-order because ``order_regions`` maps blocks back to
    # the region dicts it was given, and those carry it.
    by_group: dict[int, list[dict]] = {}
    for region in ordered:
        by_group.setdefault(region["group"], []).append(region)

    blocks_by_group: dict[int, list[dict]] = {}
    tokens = 0
    vit_ms = prefill_ms = decode_ms = 0.0

    for group_id, members in by_group.items():
        head = members[0]
        boxes = [_clip(member["box"], width, height) for member in members]
        label = head["label"]
        task = prompt_for(label)
        started = time.perf_counter()
        text, error = "", None
        timing: dict = {}

        if task is None:
            placeholder = FIGURE_PLACEHOLDERS.get(label, "[图片]")
            text = placeholder
        else:
            try:
                crop = _group_crop(bgr, boxes, head.get("merge_aligns"))
                reply = await recognise(crop, task)
                text = normalize_content(str(reply.get("text") or ""), label)
                timing = reply.get("timings") or {}
                tokens += int(reply.get("tokens") or 0)
            except Exception as exc:  # noqa: BLE001 - one region must not sink the page
                error = f"{type(exc).__name__}: {exc}"
        elapsed_ms = (time.perf_counter() - started) * 1e3
        vit_ms += float(timing.get("vit_ms") or 0.0)
        prefill_ms += float(timing.get("prefill_ms") or 0.0)
        decode_ms += float(timing.get("decode_ms") or 0.0)

        entries = []
        for position, (member, box) in enumerate(zip(members, boxes)):
            entry = {"index": 0, "type": block_type(member["label"]),
                     "label": member["label"],
                     "score": round(float(member["score"]), 6), "box": box,
                     # Only the group's head carries the answer; a follower's
                     # text would be a second copy of the same paragraph.
                     "text": text if position == 0 else "",
                     "task": task, "lines": [],
                     "ms": round(elapsed_ms, 2) if position == 0 else 0.0}
            if position == 0 and error:
                entry["error"] = error
            entries.append(entry)
        blocks_by_group[group_id] = entries

    # Renumber in reading order, and drop the followers from the Markdown: the
    # head's text already covers them.
    blocks: list[dict] = []
    rendered: list[dict] = []
    skipped: list[dict] = []
    for group_id, _members in by_group.items():
        for position, entry in enumerate(blocks_by_group[group_id]):
            entry["index"] = len(blocks)
            blocks.append(entry)
            if position == 0:
                if entry.get("text"):
                    rendered.append(entry)
                if entry.get("task") is None:
                    skipped.append({"label": entry["label"], "box": entry["box"]})

    return PageResult(
        markdown=page_markdown(rendered),
        blocks=blocks,
        width=width,
        height=height,
        vl_ms=round(vit_ms + prefill_ms + decode_ms, 2),
        vl_tokens=tokens,
        skipped=skipped,
    )


def _group_crop(bgr, boxes: Sequence[list[int]], aligns):
    """The pixels one group's recognition sees: one crop, or the merged stack."""
    crops = [bgr[y1:y2, x1:x2] for x1, y1, x2, y2 in boxes]
    if len(crops) == 1:
        return crops[0]
    return _merge_crop(crops, list(aligns or []))
