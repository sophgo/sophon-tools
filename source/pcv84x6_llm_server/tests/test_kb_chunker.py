"""The chunker: length, overlap, page boundaries, and where the boxes land.

These are unit tests on purpose -- the chunker is where the app's numbers come
from (the console draws "400 字符/片，重叠 60"), so the arithmetic is worth
pinning without a worker, an HTTP client or a PDF in the way.
"""

from __future__ import annotations

import pytest

from app.apps.kb.chunker import (
    MAX_CHUNK_CHARS,
    OVERLAP_CHARS,
    TARGET_CHARS,
    chunk_text,
    normalise,
    split_sentences,
)


def test_a_short_page_is_one_chunk():
    chunks = chunk_text("这是一段很短的话。", page=1, source="text")
    assert len(chunks) == 1
    assert chunks[0].text == "这是一段很短的话。"
    assert chunks[0].page == 1
    assert chunks[0].source == "text"


def test_an_empty_page_produces_nothing():
    assert chunk_text("", page=1, source="text") == []
    assert chunk_text("   \n\n  ", page=1, source="text") == []


def test_chunks_are_bounded_by_the_target():
    """Every chunk but the last is at or under the target.

    "At or under" rather than "under": a page whose last sentences fit exactly
    must still produce a chunk, and the splitter never pads.
    """
    text = "".join(f"第{i}条规定了仓库管理的具体要求，包括物料摆放、标识与记录。" for i in range(60))
    chunks = chunk_text(text, page=1, source="text")
    assert len(chunks) > 3
    for chunk in chunks[:-1]:
        assert len(chunk.text) <= TARGET_CHARS, chunk.text


def test_a_single_over_long_sentence_is_not_cut_mid_character():
    """A sentence with no boundary inside it stays whole -- below the ceiling.

    The contract says an over-long chunk is better than a cut sentence: a
    sentence cut in half is a *wrong* search result, while a long one is merely
    a coarse one. Since MYS-2696 that exception has a ceiling
    (``MAX_CHUNK_CHARS``), which this test deliberately stays under: 800
    characters is twice the target and still uncut.
    """
    sentence = "仓" * (TARGET_CHARS * 2)
    assert len(sentence) < MAX_CHUNK_CHARS
    chunks = chunk_text(sentence, page=1, source="text")
    assert len(chunks) == 1
    assert chunks[0].text == sentence


def test_a_sentence_over_the_hard_ceiling_is_cut_into_bounded_pieces():
    """The ceiling is absolute: 3000 characters of CJK become 3 chunks of <= 1000.

    This is the MYS-2696 fix. Without it the whole sentence stayed one chunk, and
    because the embedding model refuses rather than truncates, one such sentence
    failed the embedding of the entire document.
    """
    sentence = "无" * 3000
    chunks = chunk_text(sentence, page=1, source="text")
    assert len(chunks) == 3
    for chunk in chunks:
        assert len(chunk.text) <= MAX_CHUNK_CHARS, len(chunk.text)
    # The pieces are contiguous and cover the sentence exactly: a hard cut must
    # not drop or duplicate a character.
    assert "".join(c.text for c in chunks) == sentence


def test_the_hard_ceiling_also_applies_when_a_break_point_exists():
    """A long sentence with whitespace breaks on words, and stays under the cap.

    The ceiling is not only a CJK fallback: a 3000-character Latin run whose
    spaces are sparse would otherwise produce pieces longer than the cap.
    """
    text = ("x" * 1500) + " tail " + ("y" * 1500)
    chunks = chunk_text(text, page=1, source="text")
    assert len(chunks) >= 3
    for chunk in chunks:
        assert len(chunk.text) <= MAX_CHUNK_CHARS, len(chunk.text)


def test_ordinary_sentences_are_unaffected_by_the_ceiling():
    """Text that never approaches the ceiling chunks exactly as it did.

    A regression guard for the fix: the ceiling must be a ceiling, not a new
    splitting rule that changes where normal pages break.
    """
    text = "".join(f"第{i}条 仓库盘点应当由两人共同完成，并在盘点单上签字确认。"
                   for i in range(40))
    chunks = chunk_text(text, page=1, source="text")
    assert len(chunks) >= 2
    # Every chunk but the last is still bounded by the *target*, which is the
    # promise the console draws; the ceiling never comes into it.
    for chunk in chunks[:-1]:
        assert len(chunk.text) <= TARGET_CHARS, len(chunk.text)


def test_adjacent_chunks_overlap():
    """Consecutive chunks share at least one sentence's worth of text.

    The overlap is taken at a sentence boundary, so the shared text is the whole
    sentence(s) that ended the previous chunk -- readable, never a fragment.
    """
    text = "".join(f"第{i}条 仓库盘点应当由两人共同完成，并在盘点单上签字确认。" for i in range(40))
    chunks = chunk_text(text, page=1, source="text")
    assert len(chunks) >= 2
    for previous, following in zip(chunks, chunks[1:]):
        # The overlap is bounded by OVERLAP_CHARS plus the length of one last
        # sentence, so this checks the shared prefix really exists.
        assert following.char_start < previous.char_end, (previous.char_end, following.char_start)
        shared = previous.text[-min(OVERLAP_CHARS, len(previous.text)):]
        assert shared[:10] in following.text, (shared[:40], following.text[:80])


def test_chunks_never_cross_pages():
    """Each page is chunked on its own, so `page` is always meaningful."""
    page_one = "第一页的内容。" * 200
    page_two = "第二页的内容。" * 200
    first = chunk_text(page_one, page=1, source="text")
    second = chunk_text(page_two, page=2, source="text")
    assert {c.page for c in first} == {1}
    assert {c.page for c in second} == {2}
    # And the two sets of offsets are per-page, not cumulative.
    assert first[0].char_start == 0
    assert second[0].char_start == 0


def test_char_offsets_address_the_normalised_text():
    """``char_start``/``char_end`` must slice the page text back to the chunk."""
    text = normalise("第一句。第二句。\n第三句。")
    chunks = chunk_text(text, page=1, source="text")
    for chunk in chunks:
        assert text[chunk.char_start:chunk.char_end].strip() == chunk.text


def test_txt_documents_report_a_null_page():
    """txt/md have no pages, and the API promises `page: null` for them."""
    chunks = chunk_text("一段文字。", page=None, source="text")
    assert chunks[0].page is None


def test_sentences_split_on_cjk_and_western_punctuation():
    sentences = split_sentences("第一句。第二句！第三句？Done. Next one!")
    # Leading whitespace stays with its sentence: the offsets have to address
    # the page text exactly, so nothing may be dropped.
    texts = [s.text for s in sentences]
    assert "第一句。" in texts
    assert "第二句！" in texts
    assert "第三句？" in texts
    assert "Done." in texts
    assert "Next one!" in [t.strip() for t in texts]


def test_a_line_break_ends_a_sentence():
    """OCR and PDF text arrive line by line; a table row has no full stop."""
    sentences = split_sentences("物料编码 数量 单价\nA-001 12 3.50")
    assert len(sentences) == 2
    assert sentences[0].text == "物料编码 数量 单价\n"


def test_ocr_boxes_are_picked_by_character_range():
    """A chunk reports the boxes of every line it covers, and no others."""
    lines = ["第一行文字", "第二行文字", "第三行文字"]
    text = "\n".join(lines)
    # A box is four points, top-left first -- the same shape PP-OCR reports.
    boxes = [
        [[0.0, float(i * 10)], [100.0, float(i * 10)],
         [100.0, float(i * 10 + 8)], [0.0, float(i * 10 + 8)]]
        for i in range(3)
    ]
    offsets: list[tuple[int, list[list[float]]]] = []
    cursor = 0
    for line, box in zip(lines, boxes):
        offsets.append((cursor, box))
        cursor += len(line) + 1
    chunks = chunk_text(text, page=1, source="ocr", line_boxes=offsets)
    # One chunk covering everything: all three boxes.
    assert len(chunks) == 1
    assert len(chunks[0].boxes) == 3
    # The second line's box, i.e. the one starting at y=10.
    assert chunks[0].boxes[1][0] == [0.0, 10.0]


def test_box_selection_skips_lines_outside_the_chunk():
    lines = [f"第{i}行" * 40 for i in range(4)]
    text = "\n".join(lines)
    offsets: list[tuple[int, list[list[float]]]] = []
    cursor = 0
    for i, line in enumerate(lines):
        offsets.append((cursor, [[0.0, float(i)], [1.0, float(i)],
                                 [1.0, float(i + 1)], [0.0, float(i + 1)]]))
        cursor += len(line) + 1
    chunks = chunk_text(text, page=1, source="ocr", line_boxes=offsets,
                        target=200, overlap=20)
    assert len(chunks) > 1
    # Each chunk's boxes are a contiguous, non-empty run of the lines it covers.
    for chunk in chunks:
        assert chunk.boxes, chunk.text[:40]
        ys = [box[0][1] for box in chunk.boxes]  # the top-left point's y
        assert ys == sorted(ys)


def test_horizontal_whitespace_collapses_but_newlines_survive():
    assert normalise("a  \t b\nc") == "a b\nc"


@pytest.mark.parametrize("overlap", [0, 10, 60, 200])
def test_progress_is_made_at_every_overlap(overlap):
    """A pathological overlap must not loop forever.

    The loop's safety is "the next chunk starts strictly after the previous
    one's start"; without it an overlap larger than the chunk would repeat the
    same chunk indefinitely.
    """
    text = "短句。" * 300
    chunks = chunk_text(text, page=1, source="text", target=120, overlap=overlap)
    starts = [c.char_start for c in chunks]
    assert starts == sorted(set(starts))
    assert len(chunks) < 400
