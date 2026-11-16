"""Real (NPU) backends for the auxiliary models: embedding, rerank and ASR.

All three wrap the C ABI in ``aux_native`` plus, for the text models, HF
``tokenizers`` via ``aux_tok``. Each follows its reference pipeline step for
step:

* embedding -- tokenise each text on its own with truncation, run one forward,
  take the last row, truncate to ``dimensions``, L2-normalise;
* rerank -- encode the ``[[query, document]]`` pair right-padded to SEQLEN,
  derive XLM-R position ids, run one forward, return the raw logit;
* ASR -- decode and resample the audio, extract log-mel features, cut them into
  whole seconds, build the model's prompt, run the audio tower and the prefill,
  then greedily decode until ``<|im_end|>``; audio longer than one prompt can
  hold is cut into segments that are transcribed in order.

None builds a Scheduler or a prefix cache: the text models have no KV state to
schedule or to cache, and ASR's KV state is per request and explicitly cleared.
Serialisation is per worker (an ``asyncio.Lock`` around the NPU calls), and the
queue bound is the same ``max_queue`` the chat path uses, so an overloaded
worker answers ``busy`` -- which the HTTP layer turns into 429 -- rather than
piling up requests that will each block the single NPU anyway.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import os
import time
from dataclasses import dataclass
from typing import AsyncIterator, Sequence

from .aux_native import AsrEngine, EmbedEngine, RerankEngine
from .aux_tok import AuxTokenizer


class AuxBusy(RuntimeError):
    """The worker's queue is full; HTTP maps this to 429."""


class AuxRequestError(ValueError):
    """The input cannot be served as sent; HTTP maps this to 400.

    Separate from ``AuxNativeError`` (an engine failure, 503) because the two
    call for different client behaviour: fix the request, or retry later.
    """


class _Serialised:
    """One NPU, one call at a time, with a bounded queue.

    ``asyncio.Lock`` alone would let an unbounded number of callers wait; the
    counter makes the queue depth observable and refusable, which is what
    ``max_queue`` means everywhere else in this service.

    Two entry points, because a request is not always one NPU call. ``run`` is
    the whole request under the lock (embedding, rerank). ``slot`` + ``step`` is
    for ASR: the queue check happens once when the request is admitted, but the
    lock is taken per segment, so a 30-minute transcription does not hold the
    engine -- and, more importantly, so that it can stop *between* segments
    without leaving the lock held by a caller that is already gone.
    """

    def __init__(self, max_queue: int) -> None:
        self._lock = asyncio.Lock()
        self.max_queue = max(0, int(max_queue))
        self._waiting = 0

    @property
    def active(self) -> int:
        """Requests admitted and not yet finished -- this worker's ``inflight``.

        Every op holds exactly one slot for its whole duration (embed, rerank,
        transcribe, transcribe_stream, ocr), so this is the count the idle sweep
        needs: a non-zero value means the NPU is working for somebody and the
        model must not be unloaded. Read on the event loop, where it is also
        written, so no lock is needed.
        """
        return self._waiting

    @property
    def lock(self) -> asyncio.Lock:
        """The engine lock, for callers that manage it themselves (ASR)."""
        return self._lock

    @contextlib.asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Admission for one request; counted as queued until it finishes.

        Deliberately *not* the engine lock: an ASR request holds its slot for
        the whole file while taking the lock once per segment. Holding a slot is
        cheap, so the queue depth stays a count of requests rather than of NPU
        calls.
        """
        if self._waiting >= self.max_queue:
            raise AuxBusy(
                f"worker 队列已满（排队 {self._waiting}，上限 {self.max_queue}）；请稍后重试")
        self._waiting += 1
        try:
            yield
        finally:
            self._waiting -= 1

    async def run(self, fn, *args):
        async with self.slot():
            return await self.step(fn, *args)

    async def step(self, fn, *args):
        """One NPU call under the lock; the caller owns admission."""
        async with self._lock:
            # The NPU call is blocking C++; keep the event loop free so the
            # health/stats ops still answer while a request runs.
            return await asyncio.to_thread(fn, *args)


async def _run_uninterruptible(gate: _Serialised, fn, *args):
    """One NPU call that finishes even if the caller is cancelled.

    ``asyncio.to_thread`` cannot stop a thread: cancelling the call once it is
    running would release the engine lock while the NPU kept working, and the
    next request would enter the engine underneath it. A client that hangs up
    mid-segment therefore still waits out that segment -- which is the contract
    ("stop between segments, do not interrupt the NPU call") and the only one
    the ABI can honour.

    **Waiting for the lock is interruptible, running is not.** That split is the
    whole point: a request cancelled while it was still queued never had a
    segment in flight, so it must leave without running one -- otherwise a
    disconnected client would still occupy the NPU for one full segment and
    delay everyone behind it. Only after the lock is ours does the work become
    something that cannot be abandoned.
    """
    lock = gate.lock
    # Interruptible: a request cancelled while still queued never had a segment
    # in flight, so it leaves here without running one.
    await lock.acquire()
    task = asyncio.create_task(asyncio.to_thread(fn, *args))
    cancelled = False
    try:
        while not task.done():
            try:
                await asyncio.wait([task])
            except asyncio.CancelledError:
                # Still delivering the cancellation; the thread cannot be
                # stopped, so wait it out rather than dropping the lock early.
                cancelled = True
    finally:
        lock.release()
    if cancelled:
        # Retrieve the outcome anyway: a task whose exception is never read
        # logs "Task exception was never retrieved" at GC, which would make a
        # cancelled request look like a crash.
        with contextlib.suppress(BaseException):
            task.result()
        raise asyncio.CancelledError()
    return task.result()


def _default_lib_path() -> str:
    return os.environ.get("CV84X6_LLM_LIB") or os.path.join(
        os.path.dirname(__file__), "..", "..", "lib", "libcv84x6_llm.so")


#: Embedding / rerank requests a worker admits at once: one running, one
#: waiting. The NPU runs one forward at a time anyway, so a second concurrent
#: request never finishes sooner -- it only holds its inputs in memory and, when
#: requests interleaved text by text, made every caller slower. The board's RAM
#: is the scarce thing, so the rest are refused with 429 (``AuxBusy``) at once.
#: Applied as a ceiling on the service-wide ``max_queue``.
AUX_TEXT_MAX_QUEUE = 2


async def _run_whole(gate: _Serialised, fn, *args):
    """Admit one request and run all of its NPU work under one lock hold.

    One ``to_thread`` call for the whole batch, so requests are served first in,
    first out instead of interleaving per text, and a cancelled caller cannot
    release the engine while its batch is still on the NPU.
    """
    async with gate.slot():
        return await _run_uninterruptible(gate, fn, *args)


class AuxEmbedBackend:
    """Qwen3-Embedding on the NPU, behind the aux RPC surface."""

    kind = "embedding"
    supports_vision = False

    def __init__(self, model_path: str, config_dir: str, model_id: str,
                 lib_path: str | None = None, dev_id: int = 0,
                 max_queue: int = 16) -> None:
        self._model_id = model_id
        self._engine = EmbedEngine(model_path, lib_path or _default_lib_path(), dev_id)
        try:
            self._tok = AuxTokenizer(config_dir, self._engine.seq_len)
        except BaseException:
            self._engine.close()
            raise
        self._gate = _Serialised(min(max_queue, AUX_TEXT_MAX_QUEUE))
        # The mock reports the same two facts, so the HTTP layer never branches
        # on the backend kind.
        self.hidden = self._engine.hidden_size
        self.seq_len = self._engine.seq_len

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def max_prompt_length(self) -> int:
        return self.seq_len

    def input_tokens(self, text: str, instruction: str = "") -> int:
        """The real token count of ``instruction + text``, untruncated.

        The worker computes this, not the API process: the tokenizer lives with
        the model, and a byte-based estimate in the API would reject Chinese
        input that fits by a factor of five.
        """
        return self._tok.encode_single_full(instruction + text)[1]

    async def embed(self, texts: Sequence[str],
                    dimensions: int | None = None) -> tuple[list[list[float]], list[int]]:
        encoded: list[list[int]] = []
        for text in texts:
            ids, real_len = self._tok.encode_single_full(text)
            if real_len > self.seq_len:
                # Refused, not truncated: an embedding of a silently shortened
                # document describes a prefix and says nothing about it.
                raise AuxRequestError(
                    f"输入编码后为 {real_len} 个 token，超过该模型上限 {self.seq_len}")
            if not ids:
                raise AuxRequestError("输入编码后为 0 个 token")
            encoded.append(ids)
        # Every input is validated before the first NPU call, then the whole
        # batch runs as one engine hold (see ``_run_whole``).
        vectors = await _run_whole(self._gate, self._forward_all, encoded, dimensions)
        return vectors, [len(ids) for ids in encoded]

    def _forward_all(self, encoded: list[list[int]], dimensions: int | None):
        return [self._engine.forward(ids, dimensions) for ids in encoded]

    async def close(self) -> None:
        self._engine.close()


class AuxRerankBackend:
    """BGE-Reranker-v2-M3 on the NPU."""

    kind = "rerank"
    supports_vision = False

    def __init__(self, model_path: str, config_dir: str, model_id: str,
                 lib_path: str | None = None, dev_id: int = 0,
                 max_queue: int = 16) -> None:
        self._model_id = model_id
        self._engine = RerankEngine(model_path, lib_path or _default_lib_path(), dev_id)
        try:
            self._tok = AuxTokenizer(config_dir, self._engine.seq_len)
        except BaseException:
            self._engine.close()
            raise
        self._gate = _Serialised(min(max_queue, AUX_TEXT_MAX_QUEUE))
        self.hidden = self._engine.hidden_size
        self.seq_len = self._engine.seq_len

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def max_prompt_length(self) -> int:
        return self.seq_len

    async def rerank(self, query: str,
                     documents: Sequence[str]) -> tuple[list[float], list[int]]:
        pairs = []
        for document in documents:
            ids, mask, pos, real_len = self._tok.encode_pair_full(query, document)
            if real_len > self.seq_len:
                raise AuxRequestError(
                    f"query 与文档拼接后编码为 {real_len} 个 token，"
                    f"超过该模型上限 {self.seq_len}")
            pairs.append((ids, pos, mask))
        logits = await _run_whole(self._gate, self._forward_all, pairs)
        return logits, [self._tok.token_count(ids) for ids, _pos, _mask in pairs]

    def _forward_all(self, pairs):
        return [self._engine.forward(ids, pos, mask) for ids, pos, mask in pairs]

    async def close(self) -> None:
        self._engine.close()


# ---------------------------------------------------------------------------
# ASR
# ---------------------------------------------------------------------------
#: The most audio one request may carry: 30 minutes. The NPU runs at roughly 1x
#: real time, so this is already a 30-minute request; past it the honest answer
#: is a 400 rather than a request that outlives its client.
MAX_AUDIO_SECONDS = 30 * 60

#: Prompt tokens kept free for the transcript itself. The prefill graph takes
#: MAX_INPUT_LENGTH tokens and the KV cache SEQLEN; generation stops at the
#: cache edge, so a segment must leave room to emit anything at all. The
#: reference reserves 128 out of 2048; 8 does the same job at SEQLEN 1024, where
#: the prompt already uses most of the window.
RESERVED_OUTPUT_TOKENS = 8

#: Hard cap on one segment, independent of what MAX_INPUT_LENGTH allows. The
#: arithmetic gives 37 s at this build (512 - 15 - 8 = 489, / 13); 30 s keeps a
#: segment inside what the model transcribes reliably and bounds how long one
#: NPU call can block -- a 37 s segment at ~1x real time is already 37 s.
SEGMENT_CAP_SECONDS = 30

#: Below this the audio is treated as empty rather than transcribed: an
#: all-zero waveform is 20 ms of digital silence in a WAV header, and a
#: transcript of the room tone is not what the caller asked for.
MIN_AUDIO_SECONDS = 0.1


def segment_plan(duration: float, seconds: int) -> list[tuple[float, float]]:
    """The ``(start, end)`` windows a file of ``duration`` is cut into.

    One pure function of the duration and the segment length, shared by the real
    and the mock backend, and by the streaming and the non-streaming path. That
    sharing is the point: the segment count a client is told to expect in ``meta``
    (computed before any NPU work) is then the number of ``segment`` frames it
    really receives, and every position a window covers has one definition.

    ``seconds`` comes from ``segment_seconds``, which is prompt-dependent; a
    duration that is not a whole number of segments gets a shorter last one.
    """
    if duration <= 0 or seconds < 1:
        return []
    return [(offset, min(duration, offset + seconds))
            for offset in (float(i) * seconds
                           for i in range(math.ceil(duration / seconds)))]


@dataclass(frozen=True)
class TranscriptSegment:
    """One transcribed stretch of audio, with the times it covers."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    """One transcription: the joined text plus what produced it."""

    text: str
    language: str | None
    duration: float
    segments: list[TranscriptSegment]
    prompt_tokens: int
    completion_tokens: int
    #: Wall-clock seconds the worker spent, for the record's throughput figure.
    infer_seconds: float
    #: True when the audio was cut into more than one prompt.
    segmented: bool


#: When one ASR segment ends, as reported by ``iter_transcribe``: a ``meta``
#: frame describing the whole file, one ``segment`` frame per transcribed
#: stretch, then ``done``. The same four shapes the chat path streams, and the
#: same ones the SSE endpoint puts on the wire -- the worker and the API relay
#: them, they do not reinterpret them.
ASR_META = "meta"
ASR_SEGMENT = "segment"
ASR_DONE = "done"


class AsrStreaming:
    """The streaming transcription shared by the real and the mock backend.

    One generator, ``iter_transcribe``, produces the whole result as a sequence
    of frames; ``transcribe`` is that generator with the segments collected. The
    non-streaming reply is therefore not a second implementation of the
    streaming one -- it *is* the streaming one, which is what makes "the two
    agree word for word" a property of the code rather than a thing to keep
    testing into agreement.

    Subclasses provide ``_prepare`` (decode + validate, raising before any
    frame) and ``iter_segments`` (the per-segment work).
    """

    async def iter_transcribe(self, audio: bytes, filename: str | None = None,
                              language: str | None = None, prompt: str = ""
                              ) -> AsyncIterator[dict]:
        """Yield ``meta``, then one ``segment`` per stretch, then ``done``.

        ``meta`` is yielded after decoding and -- in the real backend -- before
        the first NPU call, so a client learns the duration and the segment count
        while the engine is still idle. Anything that can be refused without the
        NPU is raised from ``_prepare`` here, i.e. before any frame: the caller
        turns that into an HTTP status, not into a 200 whose first event is an
        error.

        The queue slot is taken *before* ``meta``, not around the segment loop.
        An overloaded worker has to answer 429 before the response is committed,
        and only the first frame can carry that: raising ``AuxBusy`` after
        ``meta`` would make the API emit 200 and then an ``error`` frame, which
        is exactly the "same status as the plain endpoint" contract this
        endpoint exists to keep. The slot is admission only -- it does not hold
        the engine, which is still taken one segment at a time.
        """
        started = time.monotonic()
        async with self._gate.slot():
            waveform, duration, canonical, seconds = await self._prepare(
                audio, filename, language, prompt)
            plan = segment_plan(duration, seconds)
            yield {"type": ASR_META, "duration": duration,
                   "segments_total": len(plan), "segment_seconds": seconds,
                   "language": canonical}
            raw: list[_RawSegment] = []
            async for index, segment in self.iter_segments(
                    waveform, duration, canonical, prompt, seconds):
                raw.append(segment)
                yield {"type": ASR_SEGMENT, "id": index,
                       "start": segment.start, "end": segment.end,
                       "text": segment.text, "infer_ms": segment.infer_ms}
            result = _summarise(raw, tok=self._language_tokens(),
                                forced_language=canonical, duration=duration,
                                started=started)
            yield {"type": ASR_DONE, "text": result.text,
                   "language": result.language, "duration": result.duration,
                   "prompt_tokens": result.prompt_tokens,
                   "completion_tokens": result.completion_tokens,
                   "infer_seconds": result.infer_seconds}

    def _language_tokens(self):
        """The tokenizer segments' preambles are read with, or None for none."""
        return None

    async def transcribe(self, audio: bytes, filename: str | None = None,
                         language: str | None = None,
                         prompt: str = "") -> Transcript:
        """``iter_transcribe`` with the segments collected into one result."""
        started = time.monotonic()
        async with self._gate.slot():
            waveform, duration, canonical, seconds = await self._prepare(
                audio, filename, language, prompt)
            raw = [segment async for _i, segment in
                   self.iter_segments(waveform, duration, canonical, prompt, seconds)]
        return _summarise(raw, tok=self._language_tokens(),
                          forced_language=canonical, duration=duration,
                          started=started)

    # -- provided by the subclass -----------------------------------------
    async def _prepare(self, audio: bytes, filename: str | None,
                       language: str | None, prompt: str):
        raise NotImplementedError

    def iter_segments(self, waveform, duration: float, language: str | None,
                      context: str, seconds: int) -> AsyncIterator[tuple[int, "_RawSegment"]]:
        raise NotImplementedError

    #: The worker's serialisation gate: admission (the queue bound) and the
    #: engine lock. A subclass sets it in ``__init__``.
    _gate: "_Serialised"


class AsrBackend(AsrStreaming):
    """Qwen3-ASR on the NPU, behind the aux RPC surface.

    One *segment* is one prompt: the template skeleton plus 13 tokens per second
    of audio has to fit MAX_INPUT_LENGTH, which is 38 s at this build's 512. Audio
    longer than that is cut into whole-second pieces (so every piece is a whole
    number of audio chunks) and transcribed in order, which is how the caller
    gets timestamps instead of an error.

    Generation is greedy and the history is cleared before every segment: the
    reference pipeline's per-file behaviour, with ``clear_history`` between
    files. Nothing carries across requests, so one client's transcript cannot
    depend on another's.
    """

    kind = "asr"
    supports_vision = False

    def __init__(self, model_path: str, config_dir: str, model_id: str,
                 lib_path: str | None = None, dev_id: int = 0,
                 max_queue: int = 16) -> None:
        from .asr_prompt import AsrTokenizer

        self._model_id = model_id
        self._config_dir = config_dir
        self._tok = AsrTokenizer.from_file(os.path.join(config_dir, "tokenizer.json"))
        self._engine = AsrEngine(
            model_path, lib_path or _default_lib_path(), dev_id,
            vocab_size=self._tok.tokenizer.get_vocab_size(),
            im_end_id=self._tok.im_end,
        )
        try:
            self._gate = _Serialised(max_queue)
            self.seq_len = self._engine.seq_len
            self.max_input_length = self._engine.max_input_length
            self.audio_length = self._engine.audio_length
            self.tokens_per_chunk = self._engine.tokens_per_chunk
            self.hidden = self._engine.hidden_size
        except BaseException:
            self._engine.close()
            raise

    # -- limits ----------------------------------------------------------
    def segment_seconds(self, language: str | None, context: str = "") -> int:
        """Longest audio one prompt can hold, in whole seconds.

        Derived from the prompt that will really be sent, not from a constant:
        the language suffix and a caller's context both cost tokens, and a
        segment that overflows MAX_INPUT_LENGTH is a hard engine failure rather
        than a shortened transcript. Capped at SEGMENT_CAP_SECONDS so a segment
        does not become one long NPU call.
        """
        from .asr_prompt import build_prompt

        ids, _ = build_prompt(self._tok, 1, language, context)
        skeleton = len(ids) - 1  # the one audio token is not skeleton
        per_chunk = self._engine.tokens_per_chunk
        budget = self.max_input_length - skeleton - RESERVED_OUTPUT_TOKENS
        seconds = budget // per_chunk
        if seconds < 1:
            raise AuxRequestError(
                f"提示词骨架（含语言与 {len(context)} 字上下文）占 {skeleton} token，"
                f"MAX_INPUT_LENGTH {self.max_input_length} 下已放不下任何音频")
        return int(min(seconds, SEGMENT_CAP_SECONDS))

    # -- properties the manager/API read ---------------------------------
    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def max_prompt_length(self) -> int:
        return self.max_input_length

    @property
    def context_length(self) -> int:
        """What /v1/models reports; an ASR model's "context" is its prompt window."""
        return self.max_input_length

    # -- the request ------------------------------------------------------
    async def _prepare(self, audio: bytes, filename: str | None,
                       language: str | None, prompt: str):
        """Decode and validate one upload; ``(waveform, duration, language, seconds)``.

        Raised from here -- i.e. before ``iter_transcribe`` yields ``meta`` -- so
        a refusal reaches the client as an HTTP status rather than as the first
        event of a 200 stream.
        """
        from .asr_audio import UnsupportedAudio, decode_audio
        from .asr_prompt import normalize_language

        # Refuse an unknown language before decoding: the client gets the list
        # of names instead of waiting for a 400 after a minute of transcription.
        canonical = normalize_language(language)
        try:
            # Off the event loop: ffmpeg and the numpy resampler take seconds on a
            # long upload, and the worker must keep answering health and stats
            # (the console polls them) while one request decodes.
            waveform, duration = await asyncio.to_thread(decode_audio, audio, filename)
        except UnsupportedAudio:
            raise
        except ValueError as exc:  # the decoder refusing a container shape
            raise UnsupportedAudio(str(exc)) from exc
        if duration > MAX_AUDIO_SECONDS:
            raise AuxRequestError(
                f"音频时长 {duration:.1f} 秒超过上限 {MAX_AUDIO_SECONDS // 60} 分钟")
        if duration < MIN_AUDIO_SECONDS:
            raise AuxRequestError(
                f"音频时长 {duration:.2f} 秒太短（至少 {MIN_AUDIO_SECONDS} 秒）")
        return waveform, duration, canonical, self.segment_seconds(canonical, prompt)

    def _language_tokens(self):
        return self._tok

    async def iter_segments(self, waveform, duration: float, language: str | None,
                            context: str, seconds: int
                            ) -> AsyncIterator[tuple[int, "_RawSegment"]]:
        """Yield ``(index, segment)`` in audio order, one NPU call per segment.

        The one place a waveform becomes text. Each segment is a separate
        acquisition of the engine lock, so:
        * a 30-minute file does not starve every other request on this model --
          a segment is the granularity at which one request owns the NPU;
        * a caller that gives up can stop the loop *between* segments, which is
          the cancellation contract this interface promises.

        The request's queue *slot* is already held by ``iter_transcribe`` (that
        is what makes an overloaded worker a 429 before the stream opens), so
        nothing here touches the queue counter.

        Whole seconds only: the extractor's chunk is 100 mel frames = 1 s, and
        the bmodel was compiled against features that are a whole number of
        chunks. The reference gets there by truncating the tail
        (``y[:(len(y)//sr)*sr]``); the last window here is padded with zeros to
        the next second instead, so the tail is transcribed rather than dropped.
        Padding happens in the *waveform* domain on purpose: a feature-domain
        zero is not silence (log-mel of zero power is -0.375, not 0), so padding
        after ``log_mel`` would feed the tower a step edge.
        """
        from .asr_audio import SAMPLE_RATE, log_mel

        window = seconds * SAMPLE_RATE
        for index, (start, end) in enumerate(segment_plan(duration, seconds)):
            offset = int(round(start * SAMPLE_RATE))
            piece = waveform[offset:offset + window]
            remainder = int(piece.size) % SAMPLE_RATE
            if remainder:
                piece = _pad_zeros(piece, SAMPLE_RATE - remainder)
            # The mel front end is numpy on the CPU, not the NPU: it needs no
            # lock. The tower/prefill/decode cycle below is one NPU call and
            # takes the lock exactly once per segment.
            feats = log_mel(piece)
            began = time.monotonic()
            text, tokens, pt, ct = await _run_uninterruptible(
                self._gate, self._run_prompt, feats, language, context)
            yield index, _RawSegment(
                start=start, end=end, text=text, tokens=tokens,
                prompt_tokens=pt, completion_tokens=ct,
                infer_ms=(time.monotonic() - began) * 1000.0)

    async def close(self) -> None:
        self._engine.close()

    def _run_prompt(self, feats, language: str | None,
                    context: str) -> tuple[str, list[int], int, int]:
        """One clear / audio / first / next… cycle.

        Returns ``(text, generated ids, prompt tokens, completion tokens)``.
        The ids come back so the caller can read the language the model stated
        without decoding the text twice.
        """
        from .asr_prompt import audio_token_count, build_prompt, chunk_features

        n_frames = int(feats.shape[1])
        n_audio_tokens = audio_token_count(n_frames, self.audio_length,
                                           self.tokens_per_chunk)
        ids, audio_bos = build_prompt(self._tok, n_audio_tokens, language, context)
        if len(ids) > self.max_input_length:
            raise AuxRequestError(
                f"提示词 {len(ids)} token 超过 MAX_INPUT_LENGTH {self.max_input_length}")
        chunks = chunk_features(feats, self.audio_length)
        if chunks.shape[0] * self.tokens_per_chunk != n_audio_tokens:
            raise AuxRequestError(
                f"特征 {n_frames} 帧切成 {chunks.shape[0]} 块，"
                f"与 {n_audio_tokens} 个 audio token 不一致")
        # The reference's audio_offset_list: chunk i's 13 tokens start right
        # after <|audio_start|>.
        offsets = [i * self.tokens_per_chunk + audio_bos + 1
                   for i in range(chunks.shape[0])]

        self._engine.clear()
        self._engine.forward_audio(chunks, offsets)
        token = self._engine.forward_first(ids)

        emitted: list[int] = []
        # The generation window: what the KV cache leaves after the prompt.
        limit = self.seq_len - len(ids) - 1
        while token != self._engine.im_end and len(emitted) < limit:
            emitted.append(token)
            token = self._engine.forward_next()
        return _parse_generated(self._tok, emitted), emitted, len(ids), len(emitted)


@dataclass(frozen=True)
class _RawSegment:
    start: float
    end: float
    text: str
    #: Generated ids, kept so the language can be read off the same output.
    #: Empty for a backend that has no token stream to read (the mock).
    tokens: list[int]
    prompt_tokens: int
    completion_tokens: int
    #: Wall-clock milliseconds this segment's NPU call took, reported per frame
    #: so the console can show how the time was actually spent.
    infer_ms: float = 0.0


def _summarise(raw: Sequence["_RawSegment"], *, tok,
               forced_language: str | None, duration: float,
               started: float) -> Transcript:
    """Join transcribed segments into the one :class:`Transcript` a reply needs.

    The single joiner, used by both the streaming ``done`` frame and the
    non-streaming ``transcribe`` -- so the text a client sees cannot depend on
    which of the two it called.
    """
    return Transcript(
        text=_join_segments(raw),
        language=_transcript_language(tok, raw, forced_language),
        duration=duration,
        segments=[TranscriptSegment(start=s.start, end=s.end, text=s.text)
                  for s in raw],
        prompt_tokens=sum(s.prompt_tokens for s in raw),
        completion_tokens=sum(s.completion_tokens for s in raw),
        infer_seconds=time.monotonic() - started,
        segmented=len(raw) > 1,
    )


def _pad_zeros(waveform, count: int):
    """Append ``count`` zero samples to a float32 waveform."""
    import numpy as np

    return np.concatenate([waveform, np.zeros(count, dtype=np.float32)])


def _join_segments(segments: Sequence["_RawSegment"]) -> str:
    """Concatenate segment texts in order, one space between them.

    The model emits no leading or trailing space of its own, and cutting audio
    between words leaves two pieces that must not run together.
    """
    return " ".join(text for text in (s.text.strip() for s in segments) if text)


def _transcript_language(tok, segments: Sequence["_RawSegment"],
                         forced: str | None) -> str | None:
    """The language to report for a whole file, across all its segments.

    Three cases, in the order the answer becomes less certain:

    * the caller forced a language -- that is what the model was told to use and
      exactly what the reference reports (``parse_asr_output`` returns
      ``user_language`` verbatim), so it wins even if a segment's preamble
      disagrees;
    * otherwise the segments' own preambles, merged the way the reference's
      ``merge_languages`` does: in order, duplicates dropped, comma-joined, so a
      file that switches language says so ("Chinese,English") instead of
      reporting whichever segment happened to come first;
    * nothing stated at all -- ``None``, not a guess.

    Reading only ``segments[0]`` (the obvious version) would mislabel every
    multi-language file by its first 30 seconds.

    ``tok`` may be None for a backend whose segments carry no token ids (the
    mock): nothing can then be read off a preamble, so the answer is the forced
    language when there is one and ``None`` otherwise -- the same rule, with the
    middle case simply having no evidence to weigh.
    """
    if forced:
        return forced
    if tok is None:
        return None
    seen: list[str] = []
    for segment in segments:
        name = _detected_language(tok, segment.tokens)
        if name and (not seen or seen[-1] != name):
            seen.append(name)
    return ",".join(seen) if seen else None


def _detected_language(tok, tokens: Sequence[int]) -> str | None:
    """The language name the model stated, or None when it stated none.

    The reference prompt ends with ``language <Name><asr_text>`` and the model
    repeats that back before the transcript, so the name is in the output. It is
    read from the decoded text rather than the ids because the name may be
    several tokens (``Chinese`` is one, ``Portuguese`` is not).
    """
    if not tokens:
        return None
    text = tok.decode(list(tokens))
    marker = "<asr_text>"
    head = text.split(marker, 1)[0] if marker in text else text
    head = head.strip()
    if not head.lower().startswith("language "):
        return None
    name = head[len("language "):].strip()
    return name or None


def _parse_generated(tok, tokens: Sequence[int]) -> str:
    """The reference pipeline's decode rule, applied to the whole sequence.

    pipeline.py decodes token by token and clears its buffer when it sees
    ``<asr_text>``, so what it prints is exactly the text after the last marker.
    Doing it on the whole sequence is the same rule: everything before
    ``<asr_text>`` is the model's ``language …`` preamble, which the API reports
    in its own field instead of leaving in the transcript.

    A partial UTF-8 character is dropped rather than emitted as U+FFFD, which is
    what the reference's ``if "�" not in word`` check does.
    """
    if not tokens:
        return ""
    text = tok.decode(list(tokens))
    marker = "<asr_text>"
    if marker in text:
        text = text.rsplit(marker, 1)[1]
    elif text.lstrip().lower().startswith("language "):
        # A preamble with no marker (a truncated generation): drop the preamble
        # line and keep whatever followed it.
        text = text.split("\n", 1)[1] if "\n" in text else ""
    return text.strip()
