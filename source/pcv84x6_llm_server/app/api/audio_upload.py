"""A bounded ``multipart/form-data`` reader for the transcription upload.

Why this exists instead of ``request.form()``: starlette's parser needs the
``python-multipart`` package, which the release does not vendor (the board gets
no pip at install time, and this codebase avoids adding runtime dependencies for
one endpoint -- ``asr_audio.py`` hand-rolls WAV parsing for the same reason). It
also has no cap on a *file* part: ``max_part_size`` only bounds non-file fields,
so a 2 GB upload would be spooled to /tmp before anyone could refuse it.

So this reads the request body itself, with a hard byte cap, and parses it in
memory. Two consequences worth stating:

* the cap is enforced while reading, not after: the request is abandoned as soon
  as it exceeds ``limit`` rather than buffered and then rejected;
* the body must fit ``limit`` in memory. At 50 MB for an audio upload that is
  the intended trade -- the alternative is a temp file whose lifetime and
  cleanup this code would then own.

The parser is deliberately strict: it accepts the shapes OpenAI clients actually
send (one or more ``form-data`` parts, quoted or bare ``name``/``filename``,
an optional part ``Content-Type``) and raises :class:`MultipartError` on
anything else, including a body with no boundary or no terminating delimiter.
Being lenient here would mean guessing where a part ends, and a wrong guess
silently truncates or corrupts the audio.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: What one upload may be. OpenAI's own limit for /v1/audio/transcriptions is
#: 25 MB; this service accepts 50 because a 30-minute 16 kHz WAV is ~57 MB and
#: the task's contract says 50 MB -- so oversized input is refused by one clear
#: number rather than by an opaque OOM.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

#: Room for the part headers and the closing delimiter on top of the file.
_ENVELOPE_SLACK = 64 * 1024


class MultipartError(ValueError):
    """The body is not the multipart request this endpoint accepts."""


class UploadTooLarge(MultipartError):
    """The request body exceeds :data:`MAX_UPLOAD_BYTES`."""


@dataclass(frozen=True)
class Part:
    """One ``form-data`` part: a field value or a file."""

    name: str
    data: bytes
    filename: str | None = None

    @property
    def is_file(self) -> bool:
        return self.filename is not None


_PARAM = re.compile(r';\s*([A-Za-z0-9_.*-]+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^;\s]*))')
_UNQUOTE = re.compile(r"\\(.)")


def boundary_of(content_type: str | None) -> str:
    """The boundary parameter of a ``multipart/form-data`` Content-Type."""
    if not content_type:
        raise MultipartError("缺少 Content-Type")
    main, _, params = content_type.partition(";")
    if main.strip().lower() != "multipart/form-data":
        raise MultipartError(
            f"Content-Type 必须是 multipart/form-data，实际是 {main.strip() or '空'}")
    for key, quoted, bare in _PARAM.findall(";" + params):
        if key.lower() == "boundary":
            value = quoted if quoted else bare
            if not value:
                break
            return _UNQUOTE.sub(r"\1", value) if quoted else value
    raise MultipartError("Content-Type 缺少 boundary 参数")


def _header_params(value: str) -> tuple[str, str | None]:
    """``(name, filename)`` from a ``Content-Disposition`` header value."""
    name = None
    filename = None
    for key, quoted, bare in _PARAM.findall(";" + value.partition(";")[2]):
        raw = quoted if quoted else bare
        if quoted:
            raw = _UNQUOTE.sub(r"\1", raw)
        if key.lower() == "name":
            name = raw
        elif key.lower() == "filename":
            filename = raw
    if name is None:
        raise MultipartError("part 缺少 name 参数")
    return name, filename


def parse(body: bytes, content_type: str | None) -> list[Part]:
    """Every part of ``body``, in the order it appeared.

    Raises :class:`MultipartError` for anything this endpoint cannot read
    unambiguously; an empty list means the body had a valid but empty envelope.
    """
    boundary = boundary_of(content_type).encode("utf-8")
    if b"\r" in boundary or b"\n" in boundary:
        # A boundary with a line break in it would make the delimiter search
        # meaningless; RFC 2046 forbids it anyway.
        raise MultipartError("boundary 不能包含换行")
    delimiter = b"--" + boundary
    close = delimiter + b"--"

    start = body.find(delimiter)
    if start < 0:
        raise MultipartError("请求体里找不到第一个 boundary")
    # Anything before the first delimiter is a preamble, which RFC 2046 allows.

    parts: list[Part] = []
    pos = start
    while True:
        # The delimiter line ends with CRLF, or with "--" for the close.
        if body[pos:pos + len(close)] == close:
            return parts
        line_end = body.find(b"\r\n", pos)
        if line_end < 0:
            raise MultipartError("boundary 之后缺少 CRLF")
        tail = body[pos + len(delimiter):line_end]
        if tail.strip(b" \t"):
            raise MultipartError("boundary 行有多余内容")
        if body[line_end + 2:line_end + 4] == b"--":
            return parts  # close delimiter with trailing whitespace
        pos = line_end + 2

        header_end = body.find(b"\r\n\r\n", pos)
        if header_end < 0:
            raise MultipartError("part 头没有以空行结束")
        raw_headers = body[pos:header_end].decode("utf-8", "replace")
        name = filename = None
        for line in raw_headers.split("\r\n"):
            if not line:
                continue
            header, _, value = line.partition(":")
            if header.strip().lower() == "content-disposition":
                name, filename = _header_params(value)
        if name is None:
            raise MultipartError("part 缺少 Content-Disposition")
        data_start = header_end + 4

        # The part ends at CRLF + delimiter. A payload that happens to contain
        # that exact byte sequence would be split early -- which is why the
        # boundary is a long random token, and why this parser is documented as
        # strict rather than clever.
        next_marker = body.find(b"\r\n" + delimiter, data_start)
        if next_marker < 0:
            raise MultipartError("最后一个 part 之后缺少结束 boundary")
        parts.append(Part(name=name, data=body[data_start:next_marker],
                          filename=_safe_filename(filename)))
        pos = next_marker + 2


def _safe_filename(filename: str | None) -> str | None:
    """The basename of a client-supplied filename, or None.

    Only the basename survives: the value is used for a suffix and for the
    inference record, never to open a path, but a client sending
    ``../../etc/passwd`` should not see it echoed back as though it meant
    something.
    """
    if not filename:
        return None
    return filename.replace("\\", "/").rsplit("/", 1)[-1] or None


def fields(parts: list[Part]) -> tuple[dict[str, str], Part | None]:
    """``(text fields, first file part)``, refusing duplicates.

    A second file would have to be silently ignored or concatenated, and both
    are worse than saying the request is not one this endpoint serves.
    """
    values: dict[str, str] = {}
    file: Part | None = None
    for part in parts:
        if part.is_file:
            if file is not None:
                raise MultipartError(f"一次只能上传一个文件（收到 {file.name} 与 {part.name}）")
            file = part
            continue
        if part.name in values:
            raise MultipartError(f"字段 {part.name} 重复")
        values[part.name] = part.data.decode("utf-8", "replace")
    if file is not None and file.name != "file":
        raise MultipartError(f"文件字段必须叫 file，实际是 {file.name}")
    return values, file


async def read_body(request, limit: int | None = None) -> bytes:
    """The whole request body, or :class:`UploadTooLarge` once it passes ``limit``.

    ``Content-Length`` is checked first (the common case, refused before a byte
    is read), then the stream is counted as it arrives: a lying or absent
    length is not a way around the limit.

    ``limit`` defaults to :data:`MAX_UPLOAD_BYTES` *at call time* rather than at
    definition time, so a caller that lowers the module constant (a test, or an
    operator's config) actually changes the bound.
    """
    if limit is None:
        limit = MAX_UPLOAD_BYTES
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            size = int(declared)
        except ValueError:
            raise MultipartError(f"Content-Length 不是整数：{declared!r}") from None
        if size < 0:
            raise MultipartError("Content-Length 为负")
        if size > limit + _ENVELOPE_SLACK:
            raise UploadTooLarge(
                f"上传体积 {size / 2**20:.1f} MB 超过上限 {limit / 2**20:.0f} MB")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit + _ENVELOPE_SLACK:
            raise UploadTooLarge(
                f"上传体积超过上限 {limit / 2**20:.0f} MB")
        chunks.append(chunk)
    return b"".join(chunks)
