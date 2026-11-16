"""Turning an uploaded file into per-page text and preview images.

Four input families, one output shape (:class:`Page`)::

    txt / md      read as text; one page, ``page=None`` positions
    pdf           text layer per page; a page with (almost) no text is a scan
                  and goes to PP-OCR as a rendered image
    png/jpg/...   one page, entirely OCR

Two things are worth knowing before reading the code:

* **pypdfium2 is the only PDF parser.** It is Apache-2.0/BSD-3, ships an
  ``aarch64`` wheel, and does both halves this app needs -- the text layer and a
  rasteriser -- so the release vendors one dependency instead of two. It is
  imported lazily: a deployment with no PDFs never pays for it.
* **OCR is optional and its absence is recorded, not hidden.** A scanned page in
  a library built while PP-OCR is unloaded yields a page with no text and a
  warning naming the page. Silently dropping it would make "the answer is not in
  the documents" indistinguishable from "the text was never extracted".
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: A file this app will accept, and what family it belongs to.
TEXT_SUFFIXES = (".txt", ".md", ".markdown")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

#: The design's limits. Each is enforced where it is cheapest: size before the
#: body is buffered, pages when the PDF is opened, chunks after splitting.
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 300
MAX_CHUNKS_PER_KB = 20000
#: Above this many pixels an image is refused at upload rather than decoded.
#: 40 Mpx is ~8000x5000: a 50 MiB photo on this box is about that, and decoding
#: it costs ~120 MB of RGB plus a full re-encode before anything is indexed.
MAX_IMAGE_PIXELS = 40_000_000

#: A PDF page whose text layer, stripped of whitespace, is shorter than this is
#: a scan. 20 characters is the design's number: a real text page in any
#: language has far more, while a scan with a stamped page number has a handful.
SCAN_TEXT_THRESHOLD = 20

#: Render scales. The OCR pass wants detail (2x, capped on the long edge so a
#: A0 poster does not become a 100-megapixel image); the preview is for a human
#: looking at a ~700 px panel.
OCR_SCALE = 2.0
OCR_MAX_EDGE = 2048
PREVIEW_EDGE = 1024


class ParseError(Exception):
    """The upload cannot be parsed; the message goes to the caller as a 400."""


class Stopped(Exception):
    """The caller asked the parse to stop (its document was deleted).

    Not an error an operator sees: the ingestor drops the document directory and
    the record with it. It exists so a 300-page OCR pass can be abandoned at a
    page boundary instead of running to completion for a file nobody wants.
    """


@dataclass
class OcrLine:
    """One OCR line: its text and its box in the *preview* image's pixels."""

    text: str
    box: list[list[float]]


@dataclass
class Page:
    """One page of text, plus what is needed to show where it came from."""

    #: 1-based page number for PDFs; ``None`` for txt/md (which have no pages).
    number: int | None
    text: str
    #: ``"text"`` for a text layer, ``"ocr"`` when the text came from PP-OCR.
    source: str = "text"
    #: OCR lines with boxes scaled into the preview image's coordinates. Empty
    #: for a text layer.
    lines: list[OcrLine] = field(default_factory=list)


@dataclass
class ParsedDoc:
    """Everything a parse produces for one uploaded file."""

    kind: str                       # "txt" | "md" | "pdf" | "image"
    pages: list[Page]
    #: Page numbers (1-based) whose preview PNG exists, for the API's reporting.
    preview_pages: list[int] = field(default_factory=list)
    #: Human-readable problems that did not fail the document: a scanned page
    #: skipped because OCR was unavailable, a page that rendered empty.
    warnings: list[str] = field(default_factory=list)
    #: How many pages were scanned (needed OCR) -- reported by the API.
    ocr_pages: int = 0
    text_pages: int = 0
    #: Preview PNG bytes by page number, from a parse that was not given a
    #: ``write_preview`` hook. A parse *with* the hook writes each page as it is
    #: rendered and leaves this empty -- 300 A4 previews is a few hundred MB of
    #: PNG that the box this runs on does not have.
    previews: dict[int, bytes] = field(default_factory=dict)

    @property
    def has_text(self) -> bool:
        return any(page.text.strip() for page in self.pages)


def detect_kind(filename: str, data: bytes) -> str:
    """The family of an upload, from its suffix and (for unknown names) magic.

    A browser reports ``.pdf`` reliably; the magic check is for the cases where
    it does not -- an upload named ``document`` with no suffix at all, which iOS
    and some curl invocations produce.

    An *unknown* suffix is a refusal, not a guess. ``.docx`` is a zip whose first
    four bytes are ASCII, so content-sniffing it would classify a Word document
    as plain text and store it under a ``.txt`` name -- which then parses as
    mojibake instead of saying "this app cannot read Word".
    """
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".pdf" or data[:5] == b"%PDF-":
        return "pdf"
    if suffix in TEXT_SUFFIXES:
        return "md" if suffix in (".md", ".markdown") else "txt"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix:
        raise ParseError(
            f"不支持的文件类型：{filename}。"
            "支持 txt、md、pdf、png、jpg、jpeg、webp、bmp")
    # No suffix: guess from the content, and refuse rather than store a file
    # this app cannot read.
    try:
        data.decode("utf-8")
        return "txt"
    except UnicodeDecodeError:
        pass
    raise ParseError(
        "不支持的文件类型：文件名没有扩展名，内容也不是文本。"
        "支持 txt、md、pdf、png、jpg、jpeg、webp、bmp")


def decode_text(data: bytes) -> str:
    """UTF-8, then GB18030. Anything else is the caller's 400.

    Windows-authored Chinese text is GB18030 far more often than anything else,
    and a byte sequence that decodes as neither is a binary file someone renamed
    to ``.txt`` -- there is no honest text to index.
    """
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ParseError("文件既不是 UTF-8 也不是 GB18030 编码，无法作为文本读取")


def validate_upload(kind: str, data: bytes) -> None:
    """Refuse, *at upload time*, everything that can be checked cheaply.

    The queue is serial and an operator watches it: a document that cannot be
    read should come back as a 400 from the POST rather than occupy the worker
    for a parse pass and then turn up as ``failed`` in a table. Three checks
    qualify as cheap:

    * txt/md -- can the bytes be decoded at all (UTF-8, then GB18030);
    * PDF -- does it open, and how many pages does it claim (pypdfium2 reads the
      page tree on open, so this costs no page rendering);
    * image -- does the header decode, and is it under the pixel cap.

    What is deliberately *not* here: the 20 000-chunk library cap. That needs
    the text chunked, which is the whole parse. It is enforced before embedding
    (see ``ingest._process``) so a refusal never costs NPU time.

    Raises :class:`ParseError`, whose message is the 400's body.
    """
    if kind in ("txt", "md"):
        decode_text(data)
        return
    if kind == "pdf":
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:  # pragma: no cover - the release always has it
            raise ParseError(
                "This build cannot read PDFs: pypdfium2 is missing from the "
                "release vendor directory (scripts/package.sh installs it)") from exc
        try:
            document = pdfium.PdfDocument(data)
        except Exception as exc:
            raise ParseError(f"PDF 无法打开：{exc}") from exc
        try:
            total = len(document)
        finally:
            document.close()
        if total < 1:
            raise ParseError("PDF 没有页面")
        if total > MAX_PDF_PAGES:
            raise ParseError(f"PDF 有 {total} 页，超过上限 {MAX_PDF_PAGES} 页")
        return
    if kind == "image":
        width, height = image_pixel_count(data)
        if width * height > MAX_IMAGE_PIXELS:
            raise ParseError(
                f"图片 {width}×{height} 有 {width * height / 1e6:.1f} Mpx，"
                f"超过上限 {MAX_IMAGE_PIXELS // 1_000_000} Mpx；"
                "请先缩小后再上传")


def parse_text_document(data: bytes, kind: str) -> ParsedDoc:
    """A txt/md upload: one page, no preview (there is nothing to draw)."""
    text = decode_text(data)
    return ParsedDoc(kind=kind, pages=[Page(number=None, text=text)], text_pages=1)


def _png_bytes(bitmap) -> bytes:
    """A rendered pdfium bitmap as PNG bytes."""
    buffer = io.BytesIO()
    bitmap.to_pil().save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def _render_scale(width: float, height: float, scale: float, max_edge: int) -> float:
    """``scale``, reduced so the long edge lands at or below ``max_edge``."""
    if width <= 0 or height <= 0:
        return scale
    longest = max(width, height) * scale
    if longest <= max_edge:
        return scale
    return scale * (max_edge / longest)


def parse_pdf(data: bytes, *, ocr=None, write_preview=None,
              on_page=None, should_stop=None) -> ParsedDoc:
    """Every page's text layer; scanned pages go to ``ocr`` when it is given.

    ``ocr`` is a callable ``(png_bytes) -> list[OcrLine]`` (boxes in the *rendered
    image's* pixels) or ``None``. When it is ``None`` and a page needs it, the
    page is recorded as a warning instead of failing the document.

    ``write_preview`` is a callable ``(page_number, png_bytes) -> None``. Given
    one, each preview is handed over as soon as it is rendered and nothing is
    kept in memory; without one the bytes accumulate in ``ParsedDoc.previews``
    (which is what the unit tests and small documents use).

    ``on_page(done, total, scanned)`` is called after each page (``scanned`` is
    how many of the pages so far needed OCR, so the caller can show ``ocr`` only
    for a document that is actually being OCRd); ``should_stop()`` is called
    before each one: a 300-page OCR pass is minutes of NPU time, and a delete has
    to be able to stop it at a page boundary.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - the release always has it
        raise ParseError(
            "This build cannot read PDFs: pypdfium2 is missing from the release "
            "vendor directory (scripts/package.sh installs it)") from exc

    try:
        document = pdfium.PdfDocument(data)
    except Exception as exc:
        raise ParseError(f"PDF 无法打开：{exc}") from exc

    doc = ParsedDoc(kind="pdf", pages=[])
    try:
        total = len(document)
        if total > MAX_PDF_PAGES:
            raise ParseError(
                f"PDF 有 {total} 页，超过上限 {MAX_PDF_PAGES} 页")
        for index in range(total):
            if should_stop is not None and should_stop():
                raise Stopped("文档已被删除，处理中止")
            number = index + 1
            page = document[index]
            try:
                text = _page_text(page)
                width, height = page.get_size()
                # Every page gets a preview, whether text or scan: the console
                # shows the source image either way.
                preview = _render_png(page, width, height, PREVIEW_EDGE)
                if write_preview is not None:
                    write_preview(number, preview)
                else:
                    doc.previews[number] = preview
                doc.preview_pages.append(number)

                if len(text.strip()) >= SCAN_TEXT_THRESHOLD:
                    doc.pages.append(Page(number=number, text=text, source="text"))
                    doc.text_pages += 1
                    continue

                doc.ocr_pages += 1
                if ocr is None:
                    doc.pages.append(Page(number=number, text="", source="ocr"))
                    doc.warnings.append(
                        f"第 {number} 页没有文字层，需要 OCR；当前未加载 OCR 模型，本页已跳过")
                    continue
                ocr_bytes = _render_png(page, width, height, OCR_MAX_EDGE,
                                        scale=OCR_SCALE)
                lines = ocr(ocr_bytes)
                doc.pages.append(Page(
                    number=number,
                    text="\n".join(line.text for line in lines),
                    source="ocr",
                    lines=_scale_lines(lines, ocr_bytes, preview),
                ))
                if not lines:
                    doc.warnings.append(f"第 {number} 页 OCR 未识别出文字")
            finally:
                page.close()
                if on_page is not None:
                    on_page(number, total, doc.ocr_pages)
    finally:
        document.close()
    return doc


def _page_text(page) -> str:
    """The page's text layer, line by line.

    ``get_text_range`` returns the whole page; keeping its newlines is what lets
    the chunker see table rows and headings as separate sentences.
    """
    try:
        textpage = page.get_textpage()
    except Exception:  # pragma: no cover - a PDF with no text objects at all
        return ""
    try:
        return textpage.get_text_range() or ""
    finally:
        textpage.close()


def _render_png(page, width: float, height: float, max_edge: int,
                scale: float = 1.0) -> bytes:
    """Render a page to PNG with its long edge at or below ``max_edge``."""
    factor = _render_scale(width, height, scale, max_edge)
    bitmap = page.render(scale=factor)
    try:
        return _png_bytes(bitmap)
    finally:
        bitmap.close()


def _scale_lines(lines: list[OcrLine], ocr_png: bytes, preview_png: bytes) -> list[OcrLine]:
    """Map OCR boxes from the OCR render's pixels into the preview's pixels.

    The two images are the same page at different scales, so one ratio is exact.
    Reading the ratio from the images rather than recomputing it from the scales
    keeps the boxes correct even if the renderer clamps a size.
    """
    ocr_w, ocr_h = _png_size(ocr_png)
    prev_w, prev_h = _png_size(preview_png)
    if not ocr_w or not ocr_h or not prev_w or not prev_h:
        return lines
    sx, sy = prev_w / ocr_w, prev_h / ocr_h
    return [
        OcrLine(text=line.text,
                box=[[point[0] * sx, point[1] * sy] for point in line.box])
        for line in lines
    ]


def _png_size(data: bytes) -> tuple[int, int]:
    """(width, height) of a PNG, from its IHDR -- no decoder needed."""
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        return (0, 0)
    return (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))


def parse_image(data: bytes, *, ocr, write_preview=None) -> ParsedDoc:
    """A picture: OCR it, and make the preview a downscaled copy of the original.

    The image is normalised to PNG first. The OCR backend reads PNG/JPEG/BMP/WebP
    through OpenCV on the board, but the preview has to be a PNG for the browser
    route, and re-encoding once means the two are the same pixels.

    The picture is scaled to :data:`OCR_MAX_EDGE` on its long edge before it is
    handed to OCR, exactly as a PDF page is: a 12 Mpx phone photo is a ~36 MB
    RGB array to decode and a much larger one inside the detector, and on a
    2.6 GB board that is the difference between a page and an OOM. The boxes
    come back in *that* image's pixels and are scaled into the preview's, which
    is the coordinate system the console draws in.
    """
    normalised, width, height = _normalise_image(data)
    preview = _downscale_png(normalised, PREVIEW_EDGE)
    if write_preview is not None:
        write_preview(1, preview)
    ocr_input = _downscale_png(normalised, OCR_MAX_EDGE)
    ocr_w, ocr_h = _png_size(ocr_input)

    doc = ParsedDoc(kind="image", pages=[])
    if write_preview is None:
        doc.previews[1] = preview
    doc.preview_pages.append(1)
    doc.ocr_pages = 1

    lines = ocr(ocr_input) if ocr is not None else []
    if ocr is None:
        doc.pages.append(Page(number=1, text="", source="ocr"))
        doc.warnings.append("图片需要 OCR；当前未加载 OCR 模型，已跳过")
        return doc
    prev_w, prev_h = _png_size(preview)
    # Both images are the same picture at different sizes, so one ratio is exact
    # even when the OCR copy is the smaller of the two.
    sx = (prev_w / ocr_w) if ocr_w else 1.0
    sy = (prev_h / ocr_h) if ocr_h else 1.0
    scaled = [OcrLine(text=line.text,
                      box=[[p[0] * sx, p[1] * sy] for p in line.box])
              for line in lines]
    doc.pages.append(Page(number=1, text="\n".join(line.text for line in lines),
                          source="ocr", lines=scaled))
    if not lines:
        doc.warnings.append("OCR 未识别出文字")
    return doc


def _normalise_image(data: bytes) -> tuple[bytes, int, int]:
    """Re-encode any accepted image as PNG; returns ``(png, width, height)``."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - the release always has it
        raise ParseError(
            "This build cannot read images: Pillow is missing from the release "
            "vendor directory (scripts/package.sh installs it)") from exc

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            rgb = image.convert("RGB")
    except Exception as exc:
        raise ParseError(f"图片无法解码：{exc}") from exc
    buffer = io.BytesIO()
    rgb.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue(), rgb.width, rgb.height


def image_pixel_count(data: bytes) -> tuple[int, int]:
    """``(width, height)`` of an image, decoded only as far as its header.

    Used by the upload route to enforce :data:`MAX_IMAGE_PIXELS` *before* the
    file is queued: ``Image.open`` reads the header and stops, so a 40 Mpx
    refusal costs a few kilobytes of work rather than a full decode at the head
    of a serial queue the operator is watching.
    """
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - the release always has it
        raise ParseError("This build cannot read images (Pillow missing)") from exc
    try:
        with Image.open(io.BytesIO(data)) as image:
            return image.size
    except Exception as exc:
        raise ParseError(f"图片无法解码：{exc}") from exc


def _downscale_png(png: bytes, max_edge: int) -> bytes:
    """A PNG whose long edge is at most ``max_edge``; unchanged when smaller."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise ParseError("This build cannot resize images (Pillow missing)") from exc
    with Image.open(io.BytesIO(png)) as image:
        image.load()
        width, height = image.size
        longest = max(width, height)
        if longest <= max_edge:
            return png
        factor = max_edge / longest
        resized = image.convert("RGB").resize(
            (max(1, round(width * factor)), max(1, round(height * factor))),
            Image.LANCZOS)
    buffer = io.BytesIO()
    resized.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()
