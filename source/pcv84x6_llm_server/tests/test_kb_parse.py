"""Document parsing: txt/md encodings, PDF text layers, scanned pages, images.

Everything here runs on the checked-in fixtures under ``tests/data/kb/`` (see
``tools/kb/make_pdf_fixtures.py``), so the suite needs only ``pypdfium2`` -- no
LibreOffice, no CJK font, no OCR model. The OCR cases drive a fake recogniser
instead of a worker, which is what lets them assert *where* the boxes ended up
without an NPU in the loop.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.apps.kb.parse import (
    IMAGE_SUFFIXES,
    MAX_PDF_PAGES,
    OCR_MAX_EDGE,
    PREVIEW_EDGE,
    ParseError,
    OcrLine,
    decode_text,
    detect_kind,
    parse_image,
    parse_pdf,
    parse_text_document,
)

DATA = Path(__file__).resolve().parent / "data" / "kb"


def fixture(name: str) -> bytes:
    return (DATA / name).read_bytes()


def png_of(width: int = 300, height: int = 200, colour=(30, 120, 200)) -> bytes:
    """A solid PNG, built here so the test needs no image file on disk."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


# What a fake recogniser returns for one page: two lines, boxes in the pixels of
# the image it was handed (the OCR render, not the preview).
def fake_ocr(png: bytes) -> list[OcrLine]:
    from app.apps.kb.parse import _png_size

    width, height = _png_size(png)
    return [
        OcrLine(text="第一行识别结果",
                box=[[0.0, 0.0], [width / 2, 0.0], [width / 2, height / 4], [0.0, height / 4]]),
        OcrLine(text="第二行识别结果",
                box=[[0.0, height / 2], [width, height / 2],
                     [width, height * 0.75], [0.0, height * 0.75]]),
    ]


# -- kind detection ---------------------------------------------------------
@pytest.mark.parametrize("filename,expected", [
    ("a.txt", "txt"), ("a.md", "md"), ("a.markdown", "md"),
    ("a.pdf", "pdf"), ("a.PDF", "pdf"),
    ("a.png", "image"), ("a.jpg", "image"), ("a.jpeg", "image"),
    ("a.webp", "image"), ("a.bmp", "image"),
])
def test_kind_comes_from_the_suffix(filename, expected):
    assert detect_kind(filename, b"") == expected


def test_a_pdf_is_recognised_by_its_magic_even_without_a_suffix():
    """iOS and some curl invocations upload a bare file name."""
    assert detect_kind("upload", b"%PDF-1.7\n...") == "pdf"


def test_a_suffixless_utf8_file_is_treated_as_text():
    assert detect_kind("upload", "一段中文".encode()) == "txt"


def test_a_suffixless_binary_file_is_refused():
    with pytest.raises(ParseError) as excinfo:
        detect_kind("upload", b"\xff\xfe\x00\x01binary")
    assert "不支持的文件类型" in str(excinfo.value)


def test_an_unsupported_suffix_is_refused_with_the_list_of_accepted_ones():
    with pytest.raises(ParseError) as excinfo:
        detect_kind("a.docx", b"PK\x03\x04")
    message = str(excinfo.value)
    assert "txt" in message and "pdf" in message and "png" in message


# -- text encodings ---------------------------------------------------------
def test_utf8_text_is_read():
    assert decode_text("仓库盘点".encode("utf-8")) == "仓库盘点"


def test_gb18030_is_the_fallback():
    """Windows-authored Chinese files are the common case; the order matters."""
    assert decode_text("仓库盘点".encode("gb18030")) == "仓库盘点"


def test_a_utf8_bom_is_stripped():
    assert decode_text("﻿仓库盘点".encode("utf-8")) == "仓库盘点"


def test_bytes_that_are_neither_encoding_are_refused():
    with pytest.raises(ParseError) as excinfo:
        decode_text(b"\xff\xff\xff\xff")
    assert "UTF-8" in str(excinfo.value) and "GB18030" in str(excinfo.value)


def test_a_txt_document_is_one_page_with_no_preview():
    doc = parse_text_document("第一段。\n\n第二段。".encode("utf-8"), "txt")
    assert doc.kind == "txt"
    assert len(doc.pages) == 1
    assert doc.pages[0].number is None
    assert doc.previews == {}
    assert doc.has_text


# -- PDFs -------------------------------------------------------------------
def test_a_text_pdf_yields_its_text_layer():
    doc = parse_pdf(fixture("text.pdf"))
    assert doc.kind == "pdf"
    assert len(doc.pages) == 2
    assert doc.text_pages == 2
    assert doc.ocr_pages == 0
    assert "仓库盘点" in doc.pages[0].text
    assert doc.pages[0].source == "text"


def test_every_page_gets_a_preview_png():
    doc = parse_pdf(fixture("text.pdf"))
    assert doc.preview_pages == [1, 2]
    for png in doc.previews.values():
        assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_preview_long_edge_is_capped():
    from app.apps.kb.parse import _png_size

    doc = parse_pdf(fixture("text.pdf"))
    width, height = _png_size(doc.previews[1])
    assert max(width, height) <= PREVIEW_EDGE


def test_a_scanned_page_without_ocr_is_recorded_as_a_warning():
    """No model is not a parse failure: the page is skipped *and said so*."""
    doc = parse_pdf(fixture("scan.pdf"), ocr=None)
    assert doc.pages[0].text == ""
    assert doc.pages[0].source == "ocr"
    assert doc.ocr_pages == 1
    assert not doc.has_text
    assert any("第 1 页" in w and "OCR" in w for w in doc.warnings)


def test_a_scanned_page_goes_through_ocr():
    calls: list[int] = []

    def ocr(png: bytes) -> list[OcrLine]:
        calls.append(len(png))
        return fake_ocr(png)

    doc = parse_pdf(fixture("scan.pdf"), ocr=ocr)
    assert len(calls) == 1
    assert doc.pages[0].source == "ocr"
    assert "第一行识别结果" in doc.pages[0].text
    assert doc.has_text


def test_ocr_boxes_are_scaled_into_the_preview_coordinates():
    """The boxes come back in the *preview's* pixels, not the OCR render's.

    The console draws them on the preview image, so a box left in the render's
    larger coordinate system would be off the page's bottom-right corner.
    """
    from app.apps.kb.parse import _png_size

    doc = parse_pdf(fixture("scan.pdf"), ocr=fake_ocr)
    preview_w, preview_h = _png_size(doc.previews[1])
    lines = doc.pages[0].lines
    assert lines
    widest = max(point[0] for line in lines for point in line.box)
    tallest = max(point[1] for line in lines for point in line.box)
    assert widest <= preview_w + 1, (widest, preview_w)
    assert tallest <= preview_h + 1, (tallest, preview_h)


def test_the_ocr_render_scale_is_capped_independently():
    """The image handed to PP-OCR is larger than the preview but still bounded."""
    from app.apps.kb.parse import _png_size

    seen: list[tuple[int, int]] = []

    def ocr(png: bytes) -> list[OcrLine]:
        seen.append(_png_size(png))
        return fake_ocr(png)

    parse_pdf(fixture("scan.pdf"), ocr=ocr)
    width, height = seen[0]
    assert max(width, height) <= OCR_MAX_EDGE


def test_a_mixed_pdf_uses_both_paths_in_one_document():
    """Page 1's text layer, page 2 through OCR -- the realistic report shape."""
    doc = parse_pdf(fixture("mixed.pdf"), ocr=fake_ocr)
    assert len(doc.pages) == 2
    assert doc.text_pages == 1
    assert doc.ocr_pages == 1
    assert "仓库盘点" in doc.pages[0].text
    assert "第一行识别结果" in doc.pages[1].text
    assert doc.pages[1].source == "ocr"


def test_a_blank_page_with_ocr_yields_no_text_and_a_warning():
    doc = parse_pdf(fixture("blank.pdf"), ocr=lambda png: [])
    assert not doc.has_text
    assert any("未识别出文字" in w for w in doc.warnings)


def test_a_pdf_with_more_pages_than_the_cap_is_refused(monkeypatch):
    """The cap is enforced from the document's page count, before rendering."""
    import app.apps.kb.parse as parse_mod

    monkeypatch.setattr(parse_mod, "MAX_PDF_PAGES", 1)
    with pytest.raises(ParseError) as excinfo:
        parse_pdf(fixture("text.pdf"))
    assert "超过上限" in str(excinfo.value)


def test_garbage_pdf_bytes_are_refused_not_crashed():
    with pytest.raises(ParseError) as excinfo:
        parse_pdf(b"%PDF-1.7\nthis is not a pdf")
    assert "无法打开" in str(excinfo.value)


def test_the_page_cap_is_the_designs_number():
    assert MAX_PDF_PAGES == 300


# -- images -----------------------------------------------------------------
def test_an_image_is_ocrd_and_gets_a_preview():
    seen: list[tuple[int, int]] = []

    def ocr(png: bytes) -> list[OcrLine]:
        from app.apps.kb.parse import _png_size

        seen.append(_png_size(png))
        return fake_ocr(png)

    doc = parse_image(png_of(600, 400), ocr=ocr)
    assert doc.kind == "image"
    assert doc.ocr_pages == 1
    assert doc.preview_pages == [1]
    assert "第一行识别结果" in doc.pages[0].text
    # The OCR input is the normalised original, not a downscale.
    assert seen == [(600, 400)]


def test_an_image_preview_is_downscaled_to_the_cap():
    from app.apps.kb.parse import _png_size

    doc = parse_image(png_of(3000, 1000), ocr=fake_ocr)
    width, height = _png_size(doc.previews[1])
    assert max(width, height) == PREVIEW_EDGE
    assert width == 1024 and height == round(1000 * (1024 / 3000))


def test_a_small_image_preview_is_not_upscaled():
    from app.apps.kb.parse import _png_size

    doc = parse_image(png_of(120, 90), ocr=fake_ocr)
    assert _png_size(doc.previews[1]) == (120, 90)


def test_an_image_box_lands_in_the_preview_coordinates():
    from app.apps.kb.parse import _png_size

    doc = parse_image(png_of(2000, 1000), ocr=fake_ocr)
    preview_w, preview_h = _png_size(doc.previews[1])
    for line in doc.pages[0].lines:
        for x, y in line.box:
            assert 0 <= x <= preview_w + 1
            assert 0 <= y <= preview_h + 1


def test_an_image_without_ocr_is_a_warning_not_a_failure():
    doc = parse_image(png_of(), ocr=None)
    assert doc.pages[0].text == ""
    assert any("OCR" in w for w in doc.warnings)
    # The preview still exists: the operator can see what was skipped.
    assert doc.previews


@pytest.mark.parametrize("suffix", IMAGE_SUFFIXES)
def test_every_accepted_image_format_decodes(suffix):
    """The list in parse.py is a promise; this is what keeps it honest."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (80, 60), (10, 200, 90)).save(
        buffer, format={"jpg": "JPEG", "jpeg": "JPEG"}.get(
            suffix.lstrip("."), suffix.lstrip(".").upper()))
    doc = parse_image(buffer.getvalue(), ocr=fake_ocr)
    assert doc.previews
    assert doc.pages[0].source == "ocr"


def test_undecodable_image_bytes_are_refused():
    with pytest.raises(ParseError) as excinfo:
        parse_image(b"not an image", ocr=fake_ocr)
    assert "无法解码" in str(excinfo.value)
