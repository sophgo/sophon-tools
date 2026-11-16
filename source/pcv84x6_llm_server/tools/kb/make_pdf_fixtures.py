"""Generate the PDF fixtures the knowledge-base tests read.

Run once and commit the output; the tests never call this. It lives here rather
than in ``tests/`` because it needs LibreOffice and a CJK font, which neither CI
nor the board has -- the whole point of committing the PDFs is that the test
suite needs only ``pypdfium2`` to read them.

    python3 tools/kb/make_pdf_fixtures.py

What it produces, under ``tests/data/kb/``:

``text.pdf``
    Two pages of Chinese prose with a real text layer. Long enough that the
    chunker makes several chunks per page, and that BM25 has something real to
    discriminate on.

``scan.pdf``
    The same idea *rasterised*: the pages are JPEGs with no text layer at all,
    so every page takes the OCR path. This is what a photocopied document looks
    like to a parser, and it is the case ``SCAN_TEXT_THRESHOLD`` exists for.

``mixed.pdf``
    Page 1 has a text layer, page 2 is a scan. The realistic case -- a
    born-digital report with a scanned appendix -- and the one that proves the
    two paths coexist inside a single document.

``blank.pdf``
    One empty page: a scan with nothing on it. Used for the "no text at all ->
    ``failed``" case.
"""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests" / "data" / "kb"

#: Two pages' worth of prose, in the register of the demo's subject matter.
#: Split into paragraphs so the chunker has real sentence boundaries to find.
TEXT_PAGES = [
    [
        ("第 1 章 仓库盘点制度", [
            "仓库盘点由仓管员在每个季度末执行。盘点开始前必须冻结出入库操作，"
            "打印盘点单并分配到具体货位。盘点单上应注明物料编码、批次号、账面数量与实盘数量四栏。",
            "盘点期间禁止任何形式的物料移动；确因生产急需必须出库的，由仓储主管书面批准"
            "并在盘点单上备注。未登记的移动一律按盘亏处理。",
            "盘点结束后，盘点单由仓管员与复核员双人签字，当日录入系统。"
            "签字后的盘点单保存三年，财务审计时可随时调阅。",
        ]),
        ("1.1 职责分工", [
            "仓储部负责组织盘点并保管盘点单。财务部负责复核差异并出具差异说明。"
            "质量部负责判定待处理物料的可用性。三个部门的职责不得互相替代。",
        ]),
    ],
    [
        ("第 2 章 差异处理", [
            "盘点差异率超过千分之五时，必须由财务部门复核。复核内容包括盘点方法是否正确、"
            "计量器具是否在校准有效期内、是否存在未及时入账的到货。",
            "差异原因分为记录错误、收发错误、损耗与失窃四类，分别由不同部门跟进。"
            "记录错误由录入人员更正；收发错误由仓储部追溯单据；损耗需附报废单；"
            "失窃必须报安全部门立案。",
        ]),
        ("2.1 复盘要求", [
            "差异说明经仓储主管签字确认后，应在下个季度盘点时重点复查该货位。"
            "连续两个季度出现同一货位差异的，由仓储部提交专项整改报告。",
        ]),
    ],
]

SCAN_PAGES = [
    [
        ("附件一 盘点作业指导书", [
            "作业指导书规定了盘点前的准备工作。第一步是清理货位，把散放的物料归位"
            "并贴上货位标签。第二步是核对货位卡与系统库存，发现不一致立即记录。",
            "第三步是准备盘点工具，包括手持终端、备用电池、纸质盘点单与封箱胶带。"
            "手持终端应在盘点前一天充满电并完成一次联网测试。",
        ]),
    ],
    [
        ("附件二 盘点异常处理", [
            "盘点过程中发现包装破损的物料，应当单独码放并拍照留证。"
            "破损物料在质量部判定前不得重新入库。",
            "发现无标签物料时，由质量部门协助识别，识别不出的按待处理物料入账。"
            "盘点区域在盘点完成前应设置隔离带，禁止无关人员进入。",
        ]),
    ],
]


def _html(pages) -> str:
    """One HTML document whose top-level ``div.page`` is one PDF page each.

    ``pages`` is a list of pages; each page is a list of ``(heading, paragraphs)``
    sections, so a page can carry more than one heading -- which is what makes
    the chunker's sentence splitting visible in the fixture.
    """
    body = ""
    for sections in pages:
        body += "<div class='page'>"
        for title, paragraphs in sections:
            body += f"<h1>{title}</h1>"
            body += "".join(f"<p>{text}</p>" for text in paragraphs)
        body += "</div>"
    return (
        "<html><head><meta charset='utf-8'><style>"
        "body{font-family:'Noto Sans CJK SC'; font-size:14pt; line-height:1.7}"
        "h1{font-size:20pt; margin:0 0 10pt 0} p{margin:0 0 12pt 0}"
        "div.page{page-break-after:always; break-after:page}div.page:last-child{page-break-after:auto; break-after:auto}"
        "</style></head><body>" + body + "</body></html>"
    )


def _html_to_pdf(pages, workdir: Path, name: str) -> bytes:
    source = workdir / f"{name}.html"
    source.write_text(_html(pages), encoding="utf-8")
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(workdir),
         str(source)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    return (workdir / f"{name}.pdf").read_bytes()


def _rasterise(pdf_bytes: bytes) -> bytes:
    """Every page as a JPEG on a fresh page: the pixels without the text objects.

    This is exactly what a scan is to a parser, and it is also how ppocr sees a
    page -- the same rendering path, from the same library.
    """
    import pypdfium2 as pdfium

    source = pdfium.PdfDocument(pdf_bytes)
    out = pdfium.PdfDocument.new()
    try:
        for index in range(len(source)):
            page = source[index]
            width, height = page.get_size()
            bitmap = page.render(scale=2.0)
            buffer = io.BytesIO()
            bitmap.to_pil().save(buffer, format="JPEG", quality=85)
            bitmap.close()
            page.close()

            target = out.new_page(width, height)
            image = pdfium.PdfImage.new(out)
            image.load_jpeg(io.BytesIO(buffer.getvalue()), inline=True)
            image.set_matrix(pdfium.PdfMatrix().scale(width, height))
            target.insert_obj(image)
            target.gen_content()
            target.close()
        buffer = io.BytesIO()
        out.save(buffer)
        return buffer.getvalue()
    finally:
        out.close()
        source.close()


def _slice(pdf_bytes: bytes, pages: list[int]) -> bytes:
    """A PDF containing only ``pages`` of ``pdf_bytes``."""
    import pypdfium2 as pdfium

    source = pdfium.PdfDocument(pdf_bytes)
    out = pdfium.PdfDocument.new()
    try:
        out.import_pages(source, pages=pages)
        buffer = io.BytesIO()
        out.save(buffer)
        return buffer.getvalue()
    finally:
        out.close()
        source.close()


def _concat(parts: list[bytes]) -> bytes:
    """Several one-page PDFs merged into one, page by page.

    ``import_pages`` is the only way pdfium can bring a page from another
    document, and it will not take two documents' worth in one call -- so the
    inputs are sliced to one page each first and appended one at a time.
    """
    import pypdfium2 as pdfium

    out = pdfium.PdfDocument.new()
    try:
        for part in parts:
            source = pdfium.PdfDocument(part)
            try:
                out.import_pages(source, pages=list(range(len(source))))
            finally:
                source.close()
        buffer = io.BytesIO()
        out.save(buffer)
        return buffer.getvalue()
    finally:
        out.close()


def _blank_pdf() -> bytes:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument.new()
    try:
        doc.new_page(595, 842)
        buffer = io.BytesIO()
        doc.save(buffer)
        return buffer.getvalue()
    finally:
        doc.close()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        text_pdf = _html_to_pdf(TEXT_PAGES, workdir, "text")
        scan_pdf = _rasterise(_html_to_pdf(SCAN_PAGES, workdir, "scan"))
        mixed_pdf = _concat([_slice(text_pdf, [0]), _slice(scan_pdf, [0])])
        blank_pdf = _blank_pdf()

        for name, data in (("text.pdf", text_pdf), ("scan.pdf", scan_pdf),
                           ("mixed.pdf", mixed_pdf), ("blank.pdf", blank_pdf)):
            (OUT / name).write_bytes(data)
            print(f"{name:<12} {len(data):>7} bytes")

    # Sanity: verify the properties the tests depend on rather than trusting
    # the toolchain to have done what the names claim.
    sys.path.insert(0, str(ROOT))
    from app.apps.kb.parse import parse_pdf

    ok = True
    for name, want in (("text.pdf", "text"), ("scan.pdf", "scan"),
                       ("mixed.pdf", "mixed"), ("blank.pdf", "scan")):
        doc = parse_pdf((OUT / name).read_bytes())
        lengths = [(p.number, len(p.text.strip())) for p in doc.pages]
        print(f"  {name}: {len(doc.pages)} page(s), text lengths {lengths}")
        has = [n for n, length in lengths if length]
        if want == "text" and not has:
            print(f"  ERROR: {name} lost its text layer", file=sys.stderr)
            ok = False
        if want == "scan" and has:
            print(f"  ERROR: {name} still has text", file=sys.stderr)
            ok = False
        if want == "mixed" and has != [1]:
            print(f"  ERROR: {name} should have text on page 1 only, got {has}",
                  file=sys.stderr)
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
