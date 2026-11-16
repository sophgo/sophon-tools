"""Deterministic fake backend.

Purpose: exercise every piece of the service that is not the NPU -- scheduling,
prefix caching, cancellation, HTTP, auth, stats, the UI -- on a laptop or on
x86 CI, with behaviour close enough to the real engine that bugs surface here
instead of on the board.

It is deliberately *not* a language model: it hashes the prompt to pick from a
fixed vocabulary, so the same prompt yields the same output every time, which is
what makes the tests meaningful.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import struct
import time
from typing import Sequence

from .base import EngineBackend, Session, Token
# The frame sequence and the joiner are the ASR contract, not an engine detail:
# the mock reuses them so a faked stream and a faked plain reply cannot disagree
# any more than the NPU ones can.
from .aux_backend import AsrStreaming as _AsrStreaming

# Enough distinct "words" that streaming and stop-string handling get a workout.
_VOCAB = [
    "the", "board", "runs", "an", "offline", "model", "on", "chip", "which",
    "decode", "token", "cache", "context", "session", "vision", "concurrent",
    "prefix", "layer", "heap", "tensor", "quantized", "schedule", "request",
    "and", "of", "to", "is", "in", "for", "with", "a", "this", "that",
]
_END_TOKEN = -1


class MockSession(Session):
    """Per-request decoding state: just the tokens fed so far."""

    def __init__(self, backend: "MockBackend") -> None:
        self._backend = backend
        self._tokens: list[Token] = []
        self._generated: list[Token] = []

    @property
    def token_len(self) -> int:
        return len(self._tokens)

    async def feed_prompt(self, tokens: Sequence[Token]) -> None:
        await asyncio.sleep(self._backend.prefill_delay_per_token * len(tokens))
        self._tokens.extend(tokens)

    async def step(self) -> Token:
        await asyncio.sleep(self._backend.decode_delay_per_token)
        # Deterministic walk over the vocabulary driven by the KV state, so two
        # sessions with the same prompt produce the same continuation and two
        # different prompts do not.
        h = hashlib.sha256(
            b",".join(str(t).encode() for t in self._tokens + self._generated)
        ).digest()
        n = len(self._generated)
        # Do not emit the stop token before ``min_tokens``: without this the
        # mock ends after a couple of tokens and every long-running behaviour
        # (cancellation, fair scheduling, max_tokens) becomes untestable.
        if n >= self._backend.min_tokens and h[0] % 8 == 0:
            token = _END_TOKEN
        else:
            token = h[1] % len(_VOCAB)
        self._generated.append(token)
        self._tokens.append(token)
        return token

    def decode(self, tokens: Sequence[Token]) -> str:
        out = []
        for t in tokens:
            if t == _END_TOKEN:
                continue
            out.append(_VOCAB[t])
        return " ".join(out)

    def is_stop_token(self, token: Token) -> bool:
        return token == _END_TOKEN

    async def snapshot(self, token_len: int) -> object:
        # Truncate to the requested prefix: see Session.snapshot's docstring.
        # The mock's KV *is* its token list, so keeping more than the prefix
        # would make a restored session start from the wrong position.
        return (list(self._tokens[:token_len]),)

    async def restore(self, snap: object) -> None:
        (tokens,) = snap  # type: ignore[misc]
        self._tokens = list(tokens)
        self._generated = []

    async def close(self) -> None:
        self._tokens.clear()
        self._generated.clear()


class MockBackend(EngineBackend):
    def __init__(
        self,
        model_id: str,
        context_length: int = 2048,
        supports_vision: bool = False,
        prefill_delay_per_token: float = 0.0,
        decode_delay_per_token: float = 0.0,
        min_tokens: int = 24,
    ) -> None:
        self._model_id = model_id
        self._context_length = context_length
        self._supports_vision = supports_vision
        self.prefill_delay_per_token = prefill_delay_per_token
        self.decode_delay_per_token = decode_delay_per_token
        # Lower bound on generation length before the stop token may appear.
        self.min_tokens = min_tokens

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def context_length(self) -> int:
        return self._context_length

    @property
    def supports_vision(self) -> bool:
        return self._supports_vision

    # Roughly one token per four characters, like a real BPE tokenizer. The
    # exact ratio does not matter; what matters is that token count *scales*
    # with input length, because prefill chunking, context-limit enforcement
    # and cache sizing are all length-dependent and would be untestable with a
    # fixed-size encoding.
    CHARS_PER_TOKEN = 4

    async def encode(self, text: str, images: Sequence[bytes] | None = None) -> list[Token]:
        raw = text.encode()
        n = max(1, (len(raw) + self.CHARS_PER_TOKEN - 1) // self.CHARS_PER_TOKEN)
        # Deterministic per position, and every character influences it, so two
        # different prompts never share a token prefix by accident.
        digest = hashlib.sha256(raw).digest()
        tokens = [16 + digest[i % len(digest)] % 16 for i in range(n)]
        if images:
            # Each image costs a fixed number of placeholder tokens, which is
            # what the real VLM does (one token per merged patch).
            tokens = [0] * (len(images) * 16) + tokens
        return tokens

    async def new_session(self) -> Session:
        return MockSession(self)

    async def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Auxiliary models (embedding / rerank)
# ---------------------------------------------------------------------------
#
# Same doctrine as MockBackend above: hash the input into the output, so the
# same text always yields the same numbers and different text never does. What
# these fakes *do* reproduce is the contract the API promises -- unit norm after
# MRL truncation, a padded SEQLEN-long pair encoding with XLM-R position ids,
# scores that rise with query/document overlap -- because that is what the host
# tests are about. Model quality is not testable here and is not attempted.

#: The mock's embedding width, matching Qwen3-Embedding-0.6B's hidden size so
#: the ``dimensions`` range rules are exercised against a realistic number.
MOCK_HIDDEN = 1024
#: The mock's embedding SEQLEN, matching the bmodel this service ships since
#: MYS-2696 (seq2048; it was 8192 before). The mock uses a text's *bytes* as its
#: token ids, so this number is not tied to a bmodel -- but it must match the
#: real one wherever a test asserts on the refusal, because that message quotes
#: this figure and the console shows it.
MOCK_SEQ_LEN = 2048
MOCK_RERANK_SEQ_LEN = 2048
#: The ASR bmodel's own numbers (0.6B and 1.7B are identical here): SEQLEN and
#: MAX_INPUT_LENGTH from the graphs, 13 audio tokens per second of audio. The
#: mock keeps them so segment-length arithmetic is exercised for real rather
#: than against a number invented for the fake.
MOCK_ASR_SEQ_LEN = 1024
MOCK_ASR_MAX_INPUT = 512
MOCK_ASR_TOKENS_PER_CHUNK = 13
MOCK_ASR_AUDIO_LENGTH = 100


def _digest_floats(seed: bytes, count: int) -> list[float]:
    """``count`` floats in [-1, 1) derived deterministically from ``seed``."""
    out: list[float] = []
    block = 0
    while len(out) < count:
        raw = hashlib.sha256(seed + block.to_bytes(4, "big")).digest()
        # 8 floats per 32-byte digest.
        for i in range(0, 32, 4):
            value = struct.unpack(">I", raw[i:i + 4])[0]
            out.append((value / 2**31) - 1.0)
        block += 1
    return out[:count]


def _normalise(vec: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm > 0 else list(vec)


class MockEmbedBackend:
    """Hashed pseudo-embeddings with the real pipeline's contract.

    ``encode`` is not a tokenizer: it turns each byte into an id, capped at
    ``seq_len``. It has to cap, because the API's over-length refusal is one of
    the behaviours under test and a fake that accepts anything would hide it.
    """

    kind = "embedding"

    def __init__(self, model_id: str, hidden: int = MOCK_HIDDEN,
                 seq_len: int = MOCK_SEQ_LEN) -> None:
        self._model_id = model_id
        self.hidden = hidden
        self.seq_len = seq_len

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def context_length(self) -> int:
        return self.seq_len

    def encode(self, texts: Sequence[str], instruction: str = "") -> list[list[int]]:
        out = []
        for text in texts:
            raw = (instruction + text).encode("utf-8")
            out.append([b % 251 + 1 for b in raw[: self.seq_len]])
        return out

    def input_tokens(self, text: str) -> int:
        """Untruncated length, matching the real backend's contract."""
        return len(text.encode("utf-8"))

    async def embed(self, texts: Sequence[str],
                    dimensions: int | None = None) -> tuple[list[list[float]], list[int]]:
        """(vectors, token counts) -- truncate before normalising, as the real path."""
        from .aux_backend import AuxRequestError

        dim = self.hidden if dimensions is None else int(dimensions)
        vectors: list[list[float]] = []
        counts: list[int] = []
        for text in texts:
            real_len = self.input_tokens(text)
            if real_len > self.seq_len:
                raise AuxRequestError(
                    f"输入编码后为 {real_len} 个 token，超过该模型上限 {self.seq_len}")
            ids = [b % 251 + 1 for b in text.encode("utf-8")[: self.seq_len]]
            seed = hashlib.sha256(b"embed:" + ",".join(str(t) for t in ids).encode()).digest()
            vectors.append(_normalise(_digest_floats(seed, self.hidden)[:dim]))
            counts.append(len(ids))
        return vectors, counts

    async def close(self) -> None:
        return None


class MockVlEmbedBackend(MockEmbedBackend):
    """Protocol fixture only; these hashed vectors make no accuracy claim."""

    supports_vision = True

    def __init__(self, model_id, seq_len=2048, family="qwen3_vl_embedding"):
        super().__init__(model_id, hidden=2048, seq_len=seq_len)
        self.family = family

    async def embed_multimodal(self, items, dimensions=None, instruction=None):
        from .aux_backend import AuxRequestError
        from .vl_embed import validate_items
        from .vl_embed_native import render_prompt

        try:
            items = validate_items(items)
            if dimensions is not None and not 64 <= dimensions <= self.hidden:
                raise ValueError("dimensions 必须在 64–2048 之间")
            prompts = []
            for item in items:
                # Hash image bytes into the fake content instead of feeding a
                # base64 file through the mock's byte-count length limit.
                text = item["text"]
                if "image" in item:
                    text += " image:" + hashlib.sha256(item["image"].encode()).hexdigest()
                prompts.append(render_prompt(text, instruction=instruction, family=self.family))
            return await super().embed(prompts, dimensions)
        except ValueError as exc:
            raise AuxRequestError(str(exc)) from exc

    async def embed(self, texts, dimensions=None):
        return await self.embed_multimodal(list(texts), dimensions)


class MockRerankBackend:
    """Hashed logits where a document sharing words with the query scores higher.

    A constant logit would make the sort-order assertions vacuous -- any order is
    a valid sort of equal values -- so relevance depends on the input: shared
    words push the logit up, and a deterministic jitter keeps distinct documents
    from tying. That is enough for "the first document really was ranked first"
    to mean something.
    """

    kind = "rerank"

    def __init__(self, model_id: str, seq_len: int = MOCK_RERANK_SEQ_LEN) -> None:
        self._model_id = model_id
        self.seq_len = seq_len
        self.hidden = MOCK_HIDDEN

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def context_length(self) -> int:
        return self.seq_len

    def token_count(self, query: str, document: str) -> int:
        """Stand-in for the pair encoding's real length (query + doc + specials)."""
        return min(self.seq_len, len(query.encode()) + len(document.encode()) + 4)

    def logit(self, query: str, document: str) -> float:
        q_words = {w for w in query.lower().split() if w}
        d_words = {w for w in document.lower().split() if w}
        overlap = len(q_words & d_words)
        seed = hashlib.sha256(("rerank:" + query + "\x00" + document).encode()).digest()
        return overlap - 4.0 + _digest_floats(seed, 1)[0]

    async def rerank(self, query: str,
                     documents: Sequence[str]) -> tuple[list[float], list[int]]:
        """(logits, token counts), one per document, order preserved."""
        from .aux_backend import AuxRequestError

        counts = [self.token_count(query, d) for d in documents]
        for count, doc in zip(counts, documents):
            # `token_count` caps at seq_len, so measure the raw length instead.
            real_len = len(query.encode()) + len(doc.encode()) + 4
            if real_len > self.seq_len:
                raise AuxRequestError(
                    f"query 与文档拼接后编码为 {real_len} 个 token，"
                    f"超过该模型上限 {self.seq_len}")
        return [self.logit(query, d) for d in documents], counts

    async def close(self) -> None:
        return None


class MockAsrBackend(_AsrStreaming):
    """A transcriber whose output is derived from the audio, not understood.

    Same doctrine as the two fakes above: reproduce the *contract* the API
    promises -- one transcript, segments with contiguous timestamps, the
    language the caller forced, token counts that add up -- and nothing about
    what the audio says. Three things it deliberately does for real:

    * it decodes the audio with the same front end the board uses
      (``asr_audio.decode_audio``), so a 415 for an undecodable container and
      the duration the response reports come from real parsing;
    * it cuts long audio into the same whole-second segments the real backend
      computes from MAX_INPUT_LENGTH and the 13 tokens/s ratio, so the
      segmentation path is under test at its real boundaries;
    * its fake transcript is a hash of the audio, so the same file always yields
      the same text and two different files do not -- which is what makes "the
      segments are in order and cover the file" checkable.

    It inherits the real backend's frame sequence and joiner, so a streamed mock
    reply and a plain one cannot disagree -- the same guarantee the NPU path has,
    obtained the same way.

    ``segment_delay_ms`` is the one thing the real backend does not have: a
    configurable pause per segment, so the console developer can watch a stream
    arrive and can hang up in the middle of one. Zero by default -- a test that
    wants speed gets speed, and every other assertion is unaffected by it.
    """

    kind = "asr"
    supports_vision = False

    def __init__(self, model_id: str, max_input: int = MOCK_ASR_MAX_INPUT,
                 seq_len: int = MOCK_ASR_SEQ_LEN,
                 tokens_per_chunk: int = MOCK_ASR_TOKENS_PER_CHUNK,
                 segment_delay_ms: float = 0.0,
                 max_queue: int = 16) -> None:
        from .aux_backend import (AuxRequestError, RESERVED_OUTPUT_TOKENS,
                                  SEGMENT_CAP_SECONDS, _Serialised)

        self._model_id = model_id
        self.seq_len = seq_len
        self.max_input_length = max_input
        self.audio_length = MOCK_ASR_AUDIO_LENGTH
        self.tokens_per_chunk = tokens_per_chunk
        self.hidden = MOCK_HIDDEN
        # The console uses this to make the demo's progress visible; it is a
        # property of the fake, so it defaults to "no pause at all".
        self.segment_delay_ms = max(0.0, float(segment_delay_ms))
        # The real backend's gate, so the queue bound (and the 429 it produces)
        # behaves identically on the mock. Nothing on the mock takes the engine
        # lock -- there is no engine -- but the slot is what ``iter_transcribe``
        # acquires, and a fake without one could not exercise the refusal.
        self._gate = _Serialised(max_queue)
        # Bound here so the module-level name below is the one the arithmetic
        # uses; the two classes must not drift on where a segment ends.
        self._reserved = RESERVED_OUTPUT_TOKENS
        self._segment_cap = SEGMENT_CAP_SECONDS
        self._request_error = AuxRequestError

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def context_length(self) -> int:
        return self.max_input_length

    @property
    def max_prompt_length(self) -> int:
        return self.max_input_length

    def segment_seconds(self, language: str | None, context: str = "") -> int:
        """The real backend's arithmetic, with the real constants.

        The skeleton is the 15 tokens the reference template, its special
        tokens and an (empty) language slot come to; a context or a non-empty
        language costs extra, approximated the way the real prompt would grow.
        Deliberately the same formula as ``AsrBackend.segment_seconds`` so the
        two cannot disagree about where a segment boundary lands.
        """
        skeleton = 15 + (len(context.encode("utf-8")) // 4 if context else 0)
        if language:
            skeleton += 2
        seconds = (self.max_input_length - skeleton - self._reserved) // self.tokens_per_chunk
        if seconds < 1:
            raise self._request_error(
                f"提示词骨架占 {skeleton} token，MAX_INPUT_LENGTH {self.max_input_length} "
                "下已放不下任何音频")
        return int(min(seconds, self._segment_cap))

    # ``segment_plan`` and the constants below are the real backend's, imported
    # rather than re-derived: the number of segments in ``meta`` and the ones
    # actually streamed have to be the same fact, so there is one implementation.
    def segment_plan(self, duration: float, seconds: int) -> list[tuple[float, float]]:
        from .aux_backend import segment_plan

        return segment_plan(duration, seconds)

    async def _prepare(self, audio: bytes, filename: str | None,
                       language: str | None, prompt: str):
        """Decode and validate, exactly as ``AsrBackend._prepare`` does."""
        from .asr_audio import UnsupportedAudio, decode_audio
        from .asr_prompt import normalize_language
        from .aux_backend import MAX_AUDIO_SECONDS, MIN_AUDIO_SECONDS

        canonical = normalize_language(language)
        try:
            waveform, duration = decode_audio(audio, filename)
        except UnsupportedAudio:
            raise
        except ValueError as exc:
            raise UnsupportedAudio(str(exc)) from exc
        if duration > MAX_AUDIO_SECONDS:
            raise self._request_error(
                f"音频时长 {duration:.1f} 秒超过上限 {MAX_AUDIO_SECONDS // 60} 分钟")
        if duration < MIN_AUDIO_SECONDS:
            raise self._request_error(
                f"音频时长 {duration:.2f} 秒太短（至少 {MIN_AUDIO_SECONDS} 秒）")
        return waveform, duration, canonical, self.segment_seconds(canonical, prompt)

    async def iter_segments(self, waveform, duration: float, language: str | None,
                            context: str, seconds: int):
        """``(index, segment)`` pairs, with the real backend's timing shape.

        The pause is per segment and *before* the segment is produced, so a
        client that hangs up during the stream sees exactly what it would on the
        board: nothing new starts, and the segment already running finishes.
        """
        from .aux_backend import segment_plan

        digest = hashlib.sha256(waveform.tobytes()).hexdigest()
        for index, (start, end) in enumerate(segment_plan(duration, seconds)):
            if self.segment_delay_ms:
                await asyncio.sleep(self.segment_delay_ms / 1000.0)
            text = self._segment_text(digest, index)
            yield index, _MockSegment(
                start=round(start, 3), end=round(end, 3), text=text,
                prompt_tokens=15 + int(round((end - start) * self.tokens_per_chunk)),
                completion_tokens=len(text.split()),
                infer_ms=self.segment_delay_ms or _MOCK_INFER_MS)

    def _segment_text(self, digest: str, index: int) -> str:
        """A short pseudo-sentence that is stable for (audio, segment)."""
        seed = hashlib.sha256(f"asr:{digest}:{index}".encode()).digest()
        words = [b"board", b"runs", b"offline", b"model", b"on", b"chip",
                 b"audio", b"segment", b"transcript", b"token"]
        picks = [words[seed[i] % len(words)].decode() for i in range(4)]
        return f"segment {index}: " + " ".join(picks)

    async def close(self) -> None:
        return None


#: The mock reports its own per-segment cost. Kept at a fixed, plausible number
#: rather than timed: a test that asserts on ``infer_ms`` must not be measuring
#: how busy the CI machine was, and the field's contract is "how long this
#: segment took", which for a fake with a configured pause *is* the pause.
_MOCK_INFER_MS = 1.0


class _MockSegment:
    """What ``MockAsrBackend.iter_segments`` yields: a segment and its cost."""

    __slots__ = ("start", "end", "text", "prompt_tokens", "completion_tokens",
                 "infer_ms")

    def __init__(self, *, start: float, end: float, text: str,
                 prompt_tokens: int, completion_tokens: int,
                 infer_ms: float = _MOCK_INFER_MS) -> None:
        self.start = start
        self.end = end
        self.text = text
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.infer_ms = infer_ms


class MockOcrBackend:
    """A recogniser whose output is derived from the image, not read from it.

    Same doctrine as the other mock auxiliary backends: reproduce the *contract*
    -- decode the image for real (so "bad image" is a real 400 and the width and
    height in the response are real), return lines with boxes inside the image,
    scores in [0, 1], and a ``text`` that is the lines joined by newline in the
    order they were returned -- and nothing about what the image says.

    The image's size is read from its header with numpy-free code (PNG and JPEG
    only) so the mock needs no OpenCV: a host test driving ``backend=mock`` must
    not require the device SDK.

    ``mode="layout"`` returns a *shape-valid* layout response -- three regions
    with types, boxes, per-region lines and a Markdown ``text`` -- so the
    console's layout UI can be built and exercised on a laptop. Which regions it
    invents is fixed (a title, a body block, a table), because a mock whose
    shape varies per image makes a UI that works on one picture break on the
    next for no reason the developer can see.
    """

    kind = "ocr"
    supports_vision = False

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def context_length(self) -> int:
        return 736

    async def recognise(self, image: bytes, mode: str = "lines"):
        from .aux_backend import AuxRequestError
        from .ocr_ppocr import OcrLine, OcrResult, _check_mode

        mode = _check_mode(mode)
        width, height = _mock_image_size(image)
        if width < 2 or height < 2:
            raise AuxRequestError(f"图片太小：{width}x{height}")
        digest = hashlib.sha256(image).hexdigest()
        # Three lines, deterministic in the image's bytes, laid out top to
        # bottom so reading_order has something real to order.
        texts = [f"line-{digest[i * 4:(i + 1) * 4]}" for i in range(3)]
        step = height // 4
        lines = []
        for i, text in enumerate(texts):
            y0 = step * (i + 1) * 0.5
            y1 = y0 + step * 0.5
            x0 = width * 0.1
            x1 = width * 0.9
            lines.append(OcrLine(
                text=text,
                score=round(0.90 + i * 0.01, 4),
                box=((x0, y0), (x1, y0), (x1, y1), (x0, y1)),
                width_tier=320))
        if mode == "layout":
            return _mock_layout_result(texts, lines, width, height)
        return OcrResult(text="\n".join(line.text for line in lines), lines=lines,
                         det_ms=1.0, rec_ms=2.0, width=width, height=height,
                         mode=mode)

    async def detect_page(self, image: bytes) -> dict:
        """``mode: "vl"``'s layout half: the same three regions as ``layout``.

        Deliberately the *same* three regions ``_mock_layout_result`` invents (a
        title, a body block, a table), because the console developer drives both
        modes and two mocks that disagreed about the page would make every UI
        difference look like a bug in the UI.

        Unlike the real backend this does not decode the image with OpenCV -- the
        mock has to run on a laptop with no Sophon SDK -- so the header is read
        for the size and the boxes are fractions of it.
        """
        from .aux_backend import AuxRequestError

        width, height = _mock_image_size(image)
        if width < 2 or height < 2:
            raise AuxRequestError(f"图片太小：{width}x{height}")
        return {"width": width, "height": height, "layout_ms": 0.5,
                "regions": _mock_page_regions(width, height)}

    async def close(self) -> None:
        return None


def _mock_page_regions(width: int, height: int) -> list[dict]:
    """The three regions both mocks agree on, in detection-output shape."""
    margin = max(2, int(width * 0.05))
    third = height // 3
    return [
        {"label": "doc_title", "type": "title", "score": 0.9,
         "box": [margin, margin, width - margin, third - margin]},
        {"label": "text", "type": "text", "score": 0.9,
         "box": [margin, third, width - margin, 2 * third - margin]},
        {"label": "table", "type": "table", "score": 0.9,
         "box": [margin, 2 * third, width - margin, height - margin]},
    ]


def _mock_layout_result(texts, lines, width: int, height: int):
    """A layout response whose *shape* is real and whose content is invented."""
    from .ocr_ppocr import OcrResult

    margin = max(2, int(width * 0.05))
    third = height // 3
    regions = [
        ("doc_title", "title", [margin, margin, width - margin, third - margin],
         lines[0:1]),
        ("text", "text", [margin, third, width - margin, 2 * third - margin],
         lines[1:2]),
        # A table's text is rendered as rows; one invented line is enough for a
        # UI to show the marker and the row.
        ("table", "table", [margin, 2 * third, width - margin, height - margin],
         lines[2:3]),
    ]
    blocks = []
    flat = []
    for index, (label, kind, box, region_lines) in enumerate(regions):
        flat.extend(region_lines)
        blocks.append({
            "index": index, "type": kind, "label": label, "score": 0.9,
            "box": box,
            "text": "\n".join(line.text for line in region_lines),
            "lines": region_lines,
        })
    markdown = "\n\n".join(
        [f"# {blocks[0]['text']}", blocks[1]["text"],
         "<!-- 表格：仅文字，未还原结构 -->\n\n" + blocks[2]["text"]])
    return OcrResult(text=markdown, lines=flat, det_ms=1.0, rec_ms=2.0,
                     width=width, height=height, mode="layout",
                     blocks=tuple(blocks), layout_ms=0.5)


class MockOcrVlBackend:
    """PaddleOCR-VL's *contract* without its weights.

    The model answers the ordinary chat surface, so this is an ``EngineBackend``
    like ``MockBackend`` rather than an auxiliary one: the scheduler, the SSE
    relay, stop strings, ``usage`` and ``finish_reason`` are all exercised
    through the same code the board runs.

    What it fakes is the *answer*: a fixed OTSL table followed by a paragraph of
    ordinary text, chosen so the console developer has something with both
    structures to lay out (``<fcel>`` cells, ``<nl>`` rows, a ``<lcel>`` span)
    and so the tests can assert on text that must survive the whole path
    unchanged -- the OTSL markers are ordinary vocabulary entries and must not
    be stripped as special tokens anywhere.

    The image is decoded for real (through ``_mock_image_size``, header only), so
    a corrupt upload is a real 400 and the reported image size is real. Token
    counts are derived from the prompt and the answer rather than from a
    tokenizer, which the mock does not have.

    ``kind = "ocr_vl"`` and ``serial_only = True`` mirror the real backend: the
    mock exists so the *service* can be exercised end to end, and a mock that
    admitted three concurrent sessions would hide the queueing the real model
    imposes.
    """

    kind = "ocr_vl"
    serial_only = True
    detects_loops = False

    #: The fixed answer. Deliberately not a language model: the same prompt
    #: yields the same output, which is what makes a test assertion meaningful.
    TABLE = (
        "<fcel>产线<fcel>产量（台）<fcel>合格率<fcel>负责人<nl>"
        "<fcel>一号线<fcel>4,120<fcel>99.6%<fcel>张伟<nl>"
        "<fcel>二号线<fcel>3,860<fcel>99.1%<fcel>李静<nl>"
        "<fcel>三号线<fcel>3,300<fcel>98.7%<fcel>王强<nl>"
        "<fcel>合计<fcel>11,280<fcel>99.1%<fcel>—<nl>"
    )
    PROSE = (
        "上表是 2026 年第三季度的产线统计。一号线产量最高，"
        "三条产线的合格率都在 98% 以上。"
    )

    #: The answer a *page* region gets from ``recognise_block``. Same shape as
    #: :data:`TABLE` plus the two things a page-mode UI has to be able to draw
    #: and the chat answer never needed: a header row spanning all four columns
    #: and a first column spanning three rows. Kept separate from :data:`TABLE`
    #: so the chat surface's pinned answer does not change under it.
    PAGE_TABLE = (
        "<fcel>2026年第三季度产线统计<lcel><lcel><lcel><nl>"
        "<fcel>厂房<fcel>产线<fcel>产量（台）<fcel>合格率<nl>"
        "<fcel>一号厂房<fcel>一号线<fcel>4,120<fcel>99.6%<nl>"
        "<ucel><fcel>二号线<fcel>3,860<fcel>99.1%<nl>"
        "<ucel><fcel>三号线<fcel>3,300<fcel>98.7%<nl>"
    )

    def __init__(self, model_id: str, context_length: int = 2048,
                 answer: str | None = None,
                 decode_delay_per_token: float = 0.0) -> None:
        self._model_id = model_id
        self._context_length = context_length
        #: The whole answer, one character per "token". Overridable so a test
        #: can drive stop strings, max_tokens and streaming without depending on
        #: this text.
        self._answer = self.TABLE + self.PROSE if answer is None else answer
        self.decode_delay_per_token = decode_delay_per_token

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def context_length(self) -> int:
        return self._context_length

    @property
    def supports_vision(self) -> bool:
        return True

    @property
    def supports_sampling(self) -> bool:
        # The bmodel's lm_head fuses the argmax: no temperature, no top_p.
        return False

    @property
    def supports_chunked_prefill(self) -> bool:
        return False

    @property
    def kv_snapshots_verified(self) -> bool:
        return False

    async def encode(self, text: str,
                     images: Sequence[bytes] | None = None) -> list[Token]:
        """One token id per character, and the image is validated for real."""
        blobs = list(images or [])
        if len(blobs) > 1:
            raise ValueError(
                "这个模型一次只接受一张图片：请把多页拆成多次请求"
                "（PaddleOCR 的产线本来就是逐元素调用）")
        if blobs:
            width, height = _mock_image_size(blobs[0])
            if width < 2 or height < 2:
                raise ValueError(f"图片太小：{width}x{height}")
        return _MockVlPrompt(_char_ids(text), has_image=bool(blobs))

    async def new_session_for(self, prompt) -> "Session":
        return _MockVlSession(self, getattr(prompt, "has_image", False))

    async def new_session(self) -> "Session":
        return _MockVlSession(self, has_image=True)

    def decode_page(self, image: bytes):
        """The page as a synthetic BGR array, sized from the PNG/JPEG header.

        The mock has no OpenCV by design (a host test must not need the device
        SDK), so it cannot *decode* the pixels -- but ``mode: "vl"`` crops
        regions out of the page, and the crop has to exist for the path to run.
        A blank array of the image's real size is enough: ``recognise_block``
        answers from the instruction, not from the pixels, and the *geometry*
        (which region, how big) is what this mode's orchestration is judged on.
        """
        import numpy as np

        from .aux_backend import AuxRequestError

        width, height = _mock_image_size(image)
        if width < 2 or height < 2:
            raise AuxRequestError(f"图片太小：{width}x{height}")
        return np.full((height, width, 3), 255, dtype=np.uint8)

    async def recognise_block(self, crop_bgr, task: str,
                              max_new_tokens: int | None = None) -> dict:
        """``mode: "vl"``'s recognition half: the fixed answer, per task.

        A table task gets :data:`PAGE_TABLE` and everything else gets :data:`PROSE`,
        so a mock page has one real OTSL table and real prose around it -- which
        is what the console developer needs to exercise the Markdown, and what
        makes ``otsl_to_html`` run on the page path in a test.

        The crop is *not* inspected. That is the mock's contract everywhere
        else: it reproduces the shape, and the shape is what the service's own
        code is judged on. It does check the crop is a numpy array of pixels,
        because a caller that passed an encoded image would otherwise get a
        plausible answer from a code path the board would refuse.
        """
        if getattr(crop_bgr, "ndim", 0) != 3:
            raise ValueError("recognise_block expects a decoded BGR crop, not bytes")
        answer = self.PAGE_TABLE if task.startswith("Table") else self.PROSE
        # Counted in characters, like every other token number the mock reports
        # (it has no tokenizer). Says nothing about the board's real counts.
        return {"text": answer, "tokens": len(answer),
                "timings": {"vit_ms": 1.0, "prefill_ms": 2.0, "decode_ms": 3.0}}

    async def close(self) -> None:
        return None


class _MockVlPrompt(list):
    """Prompt ids plus whether the request carried an image."""

    def __init__(self, tokens, has_image: bool) -> None:
        super().__init__(tokens)
        self.has_image = has_image


def _char_ids(text: str) -> list[int]:
    """Stable ids for a string, one per character (the mock has no tokenizer)."""
    return [0x100 + (ord(ch) & 0xFFFF) for ch in text]


class _MockVlSession:
    """Feeds the fixed answer out one character at a time."""

    def __init__(self, backend: MockOcrVlBackend, has_image: bool) -> None:
        self._backend = backend
        self._has_image = has_image
        self._fed = 0
        self._pos = 0
        self._answer = list(backend._answer)

    @property
    def token_len(self) -> int:
        return self._fed + self._pos

    async def feed_prompt(self, tokens: Sequence[Token]) -> None:
        if not self._has_image:
            # The real engine has no image-free path (the template always emits
            # an image block), and answering anyway would hide a caller's bug.
            raise ValueError("this model needs an image")
        self._fed += len(tokens)

    async def step(self) -> Token:
        await asyncio.sleep(self._backend.decode_delay_per_token)
        if self._pos >= len(self._answer):
            return _END_TOKEN
        tok = _MOCK_VL_ANSWER_BASE + self._pos
        self._pos += 1
        return tok

    def decode(self, tokens: Sequence[Token]) -> str:
        out = []
        for t in tokens:
            if t == _END_TOKEN:
                continue
            if _MOCK_VL_ANSWER_BASE <= t < _MOCK_VL_ANSWER_BASE + len(self._answer):
                out.append(self._answer[t - _MOCK_VL_ANSWER_BASE])
        return "".join(out)

    def decode_bytes(self, tokens: Sequence[Token]) -> bytes:
        # The real backend's tokenizer is a ByteFallback sequence, so the
        # scheduler joins raw bytes rather than per-token text. The mock carries
        # ordinary characters, so the base implementation is exact -- but it has
        # to be here, because the scheduler calls it unconditionally.
        return self.decode(tokens).encode("utf-8")

    def is_stop_token(self, token: Token) -> bool:
        return token == _END_TOKEN

    async def snapshot(self, token_len: int) -> object:
        raise RuntimeError("the mock VL backend does not snapshot")

    async def restore(self, snap: object) -> None:
        raise RuntimeError("the mock VL backend does not snapshot")

    async def close(self) -> None:
        self._pos = len(self._answer)


#: Ids the mock VL answer uses. Far above the character ids ``_char_ids``
#: produces, so a prompt id can never be mistaken for an answer position.
_MOCK_VL_ANSWER_BASE = 0x400000


def _mock_image_size(image: bytes) -> tuple[int, int]:
    """(width, height) from a PNG/JPEG header, or raise AuxRequestError.

    A header-only reader rather than a decoder: the mock's job is the API's
    contract, and the two numbers it needs are in the first 32 bytes. Anything
    it cannot recognise is refused exactly as the real backend refuses an image
    OpenCV cannot decode.
    """
    if image[:8] == b"\x89PNG\r\n\x1a\n" and len(image) >= 24:
        width = int.from_bytes(image[16:20], "big")
        height = int.from_bytes(image[20:24], "big")
        return width, height
    if image[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(image):
            if image[i] != 0xFF:
                i += 1
                continue
            marker = image[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                height = int.from_bytes(image[i + 5:i + 7], "big")
                width = int.from_bytes(image[i + 7:i + 9], "big")
                return width, height
            length = int.from_bytes(image[i + 2:i + 4], "big")
            if length < 2:
                break
            i += 2 + length
    from .aux_backend import AuxRequestError

    raise AuxRequestError(
        "无法解码这张图片；支持 PNG/JPEG/BMP/WebP 等 OpenCV 能读的格式")
