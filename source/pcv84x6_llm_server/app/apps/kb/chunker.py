"""Splitting page text into retrieval-sized chunks.

The contract the app promises the console (and the numbers it draws) is:

* a chunk is at most :data:`TARGET_CHARS` characters **except** where a single
  sentence is longer than that, in which case the sentence is kept whole rather
  than cut mid-word -- an over-long chunk is a worse search result, but a
  sentence cut in half is a wrong one;
* that exception has a ceiling: no chunk exceeds :data:`MAX_CHUNK_CHARS`
  characters, and a sentence longer than that *is* cut mid-character. The
  ceiling exists because the embedding model refuses an input longer than its
  SEQLEN rather than truncating it (``app/engine/aux_backend.py``), so one
  pathological sentence -- typically CJK with no punctuation at all -- would
  otherwise fail the *whole document's* embedding and leave the library without
  that page. A chunk cut at a character boundary embeds to a worse vector than
  a whole sentence would; a document that cannot be indexed is worse still;
* adjacent chunks share about :data:`OVERLAP_CHARS` characters, taken at a
  sentence boundary so the overlap is readable text and not a fragment;
* a chunk never crosses a page, because ``page`` is what the console uses to
  show the source and a chunk spanning two pages has no single answer.

Splitting is by sentence, and sentences are found without a tokenizer or a
language model: an ideographic full stop, a full stop followed by whitespace, a
question/exclamation mark, or a line break. Line breaks count because OCR output
and PDF text both arrive line-by-line, and a line in a table is often a complete
record with no terminal punctuation at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Target chunk length, in characters. CJK is counted per character (a Chinese
#: character is roughly one token), and a Latin word counts per character too --
#: the design says characters, and mixing units would make the cap meaningless.
TARGET_CHARS = 400
#: How much text adjacent chunks share, before rounding to a sentence boundary.
OVERLAP_CHARS = 60
#: Hard ceiling on one chunk, in characters. A sentence longer than this is cut
#: mid-character; see the module docstring for why the exception has a limit.
#:
#: 1000 is measured against the embedding model's 2048-token SEQLEN rather than
#: assumed, and it is measured per script -- a character is not a token:
#:
#:     content                          tokens/min chars
#:     Latin prose                                   0.17
#:     Thai, Korean jamo                             0.4
#:     ordinary CJK, digits, emoji                   1.0
#:     rare CJK (U+9F98), ZWJ emoji sequences        2.0
#:     CJK Extension B, private-use codepoints       3.0
#:
#: So 1000 characters is comfortably inside 2048 for prose, CJK, digits and
#: emoji, and is **over** it for the last row (3000 tokens). That row is why
#: :meth:`app.apps.kb.ingest.Ingestor._embed_fitted` splits a chunk the embedding
#: worker refuses as over-long, and pools the pieces' vectors: a character cap alone
#: cannot express the limit, and one refused input fails a whole document.
#: ``tests/test_aux_tokenize.py`` pins the ratios with the real tokenizer.
MAX_CHUNK_CHARS = 1000

#: A sentence ends at one of these, and the terminator stays with the sentence.
#: ``\n`` is included deliberately: see the module docstring.
_SENTENCE_END = re.compile(r"[。！？；!?;]|\n|\.(?=\s|$)")

#: Runs of blank space collapse, but a single newline is kept: it is a sentence
#: boundary the splitter uses, and it is also what makes OCR line structure
#: visible in the stored chunk text.
_WHITESPACE = re.compile(r"[ \t　]+")


def normalise(text: str) -> str:
    """Collapse horizontal whitespace, keep line structure, trim the ends."""
    return _WHITESPACE.sub(" ", (text or "").replace("\r\n", "\n").replace("\r", "\n")).strip()


@dataclass
class Sentence:
    """One sentence and where it sits in the page's normalised text."""

    text: str
    start: int
    end: int


def split_sentences(text: str) -> list[Sentence]:
    """Cut ``text`` into sentences, preserving each one's character offsets."""
    out: list[Sentence] = []
    pos = 0
    for match in _SENTENCE_END.finditer(text):
        end = match.end()
        piece = text[pos:end]
        if piece.strip():
            out.append(Sentence(text=piece, start=pos, end=end))
        pos = end
    tail = text[pos:]
    if tail.strip():
        out.append(Sentence(text=tail, start=pos, end=len(text)))
    return out


@dataclass
class Chunk:
    """A piece of one page, ready to be indexed."""

    page: int | None
    source: str
    text: str
    char_start: int
    char_end: int
    #: Four-point boxes in the preview image's coordinate system, one per OCR
    #: line this chunk covers. Empty for text-layer chunks.
    boxes: list[list[list[float]]] = field(default_factory=list)


def _split_long(sentence: Sentence, limit: int,
                hard_limit: int = MAX_CHUNK_CHARS) -> list[Sentence]:
    """Break a single over-long sentence, honouring the hard ceiling.

    The first loop is the pre-existing behaviour, unchanged: while the sentence
    is longer than :data:`TARGET_CHARS`, cut at the last whitespace inside the
    next ``limit`` characters, so Latin text breaks between words and every
    resulting piece is about ``limit`` long. It stops when there is no
    whitespace to break at -- CJK usually has none.

    What the second loop adds is the ceiling. Previously the remainder was kept
    whole no matter how long it was, which is how a single unpunctuated sentence
    made the embedding model refuse an entire document. Now anything over
    :data:`MAX_CHUNK_CHARS` is cut at that length, mid-character if it must be.
    A sentence at or below the ceiling is still kept whole, so the long-chunk
    exception survives everywhere it is safe.
    """
    if len(sentence.text) <= limit:
        return [sentence]
    out: list[Sentence] = []
    text = sentence.text
    start = 0

    def emit(end: int) -> None:
        out.append(Sentence(text=text[start:end], start=sentence.start + start,
                            end=sentence.start + end))

    while len(text) - start > limit:
        window = text[start:start + limit]
        cut = window.rfind(" ")
        if cut <= 0:
            # No break point in this window: leave the rest to the ceiling loop.
            break
        emit(start + cut + 1)
        start += cut + 1
    # Whatever is left exceeds `limit` (or the first loop found no break point).
    # Cut it into ceiling-sized pieces; the final piece is the tail.
    while len(text) - start > hard_limit:
        emit(start + hard_limit)
        start += hard_limit
    if start < len(text):
        out.append(Sentence(text=text[start:], start=sentence.start + start,
                            end=sentence.end))
    return out


def chunk_text(text: str, *, page: int | None, source: str,
               target: int = TARGET_CHARS, overlap: int = OVERLAP_CHARS,
               line_boxes: list[tuple[int, list[list[float]]]] | None = None) -> list[Chunk]:
    """Cut one page's ``text`` into chunks of about ``target`` characters.

    ``line_boxes`` maps a character offset in the **normalised** ``text`` to the
    OCR line's box, so a chunk that came from OCR can report the region of the
    page it covers. A chunk's boxes are those of every line it intersects. The
    caller is responsible for producing those offsets against the same string
    this function measures -- :func:`ocr_line_offsets` does it correctly; deriving
    them from the raw OCR output is what makes boxes land on the wrong lines.
    """
    text = normalise(text)
    if not text:
        return []
    sentences: list[Sentence] = []
    for sentence in split_sentences(text):
        sentences.extend(_split_long(sentence, target))

    boxes_at = sorted(line_boxes or [], key=lambda pair: pair[0])

    def boxes_between(start: int, end: int) -> list[list[list[float]]]:
        """Boxes of the lines overlapping ``[start, end)``.

        "Overlapping" is by *intersection*, which is what makes a chunk that ends
        exactly where a line ends stop there: the next line starts at ``end``,
        and ``offset < end`` is false. The tempting alternative -- letting a line
        own the span up to the next line's start -- silently appends the
        neighbour's box to every chunk that stops on a line boundary, which on a
        one-line-per-row table is every chunk.
        """
        if not boxes_at:
            return []
        picked: list[list[list[float]]] = []
        for i, (offset, box) in enumerate(boxes_at):
            # The line's own text runs to the next line's start, minus the
            # newline that separates them; a box covers its glyphs, not the gap.
            # Clamped because a caller can hand in offsets measured against a
            # different string (that is the bug this whole path exists to
            # avoid), and an out-of-range read here would be an IndexError in
            # the middle of a build rather than a merely wrong box.
            line_end = boxes_at[i + 1][0] if i + 1 < len(boxes_at) else len(text)
            line_end = min(line_end, len(text))
            offset = min(offset, len(text))
            while line_end > offset and text[line_end - 1] in " \t\n":
                line_end -= 1
            if offset < end and line_end > start:
                picked.append(box)
        return picked

    chunks: list[Chunk] = []
    start_idx = 0
    while start_idx < len(sentences):
        end_idx = start_idx
        length = 0
        while end_idx < len(sentences):
            candidate = length + len(sentences[end_idx].text)
            if end_idx > start_idx and candidate > target:
                break
            length = candidate
            end_idx += 1
        if end_idx == start_idx:  # pragma: no cover - _split_long prevents this
            end_idx = start_idx + 1
        # The reported range is the *stored* text's, not the raw sentence span:
        # `body` is stripped, so leading whitespace would otherwise put
        # `char_start` before the first character of `text`. The console slices
        # the page with these two numbers, and an off-by-two there selects the
        # tail of the previous line.
        body_start = sentences[start_idx].start
        body_end = sentences[end_idx - 1].end
        body = text[body_start:body_end]
        lead = len(body) - len(body.lstrip())
        body = body.strip()
        body_start += lead
        body_end = body_start + len(body)
        if body:
            chunks.append(Chunk(
                page=page, source=source, text=body,
                char_start=body_start, char_end=body_end,
                boxes=boxes_between(body_start, body_end),
            ))
        if end_idx >= len(sentences):
            break
        # The next chunk starts a little before this one ended: walk back over
        # whole sentences until the overlap is at least ``overlap`` characters.
        # ``s - 1 > start_idx`` is what guarantees progress -- an overlap larger
        # than the chunk itself would loop forever.
        s = end_idx
        shared = 0
        while s - 1 > start_idx and shared < overlap:
            s -= 1
            shared += len(sentences[s].text)
        start_idx = s
    return chunks
