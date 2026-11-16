"""Segment-level streaming transcription for the console's ASR demo.

``POST /api/apps/asr/transcriptions/stream`` is ``/v1/audio/transcriptions`` with
the answer arriving a segment at a time, so a long recording shows progress
instead of a two-minute silence:

    data: {"type":"meta","duration":95.5,"segments_total":4,
           "segment_seconds":30,"language":null}

    data: {"type":"segment","id":0,"start":0.0,"end":30.0,"text":"…","infer_ms":2412.7}

    …

    data: {"type":"done","text":"<the /v1 text, verbatim>","language":"Chinese",
           "duration":95.5,"usage":{"prompt_tokens":…,"completion_tokens":…,
           "total_tokens":…},"infer_seconds":5.2}

What this module owns is the *relay*: the frames themselves come from the
worker, and the segment text from the one joiner both the streaming and the
plain transcription use. So "the segments match ``verbose_json`` word for word"
is not a property this file has to maintain -- it is a property of there being
one producer.

Three things shape the control flow, each for a reason worth stating:

* **Refusals are status codes, not frames.** Everything that can be settled
  before the NPU runs -- a malformed multipart body, a missing ``model``, an
  unknown language, a model that is not loaded or is the wrong kind -- is
  answered before the response starts. The audio-shaped refusals (415 for a
  container this device cannot decode, 400 for audio over 30 minutes) come from
  the worker *before* its first frame, so this handler consumes that first frame
  before committing to ``200``: a client gets the same status the plain endpoint
  would give, rather than a 200 whose only event is an error.
* **A disconnect stops between segments.** Starlette closes the response
  generator with ``GeneratorExit`` at its current ``yield``; this module then
  tells the worker to cancel, and the worker's segment loop does not advance.
  The segment already in flight finishes -- the NPU call is not interruptible --
  which is exactly the contract. The inference record is written as
  ``cancelled`` and says how many segments were finished.
* **Nothing is yielded after the client is gone.** An async generator that
  yields while closing raises ``RuntimeError: async generator ignored
  GeneratorExit``, replacing a clean hang-up with a traceback at the moment the
  shutdown path has the least room for noise. So the terminal paths are
  separate and none of them yields from a ``finally``.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..core.auth import require_admin
from ..core.client import WorkerClient, WorkerError
from ..core.inference_log import (
    STATUS_CANCELLED,
    STATUS_ERROR,
    STATUS_OK,
    RecordContext,
    actor_from_key_id,
    build_context,
    cancellation_error,
)

router = APIRouter()


def _frame(payload: dict) -> str:
    """One SSE frame. ``json.dumps`` with ``ensure_ascii=False`` so the Chinese
    transcript is readable in a terminal ``curl`` instead of a \\uXXXX soup."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _detail(exc: WorkerError) -> str:
    """The message an ``error`` frame carries: the worker's own, in Chinese.

    Not a rewrite of it: the worker's text names the actual reason ("ffmpeg 无法
    解码该音频…", "音频时长 1801.0 秒超过上限 30 分钟"), and paraphrasing here
    would make the streaming endpoint describe failures differently from the
    plain one.
    """
    return str(exc) or "转写失败"


class _Transcription:
    """One streamed transcription: its request context and what it produced.

    A small object rather than a closure full of ``nonlocal`` counters, because
    the record has to be written from two places (the stream's own end, and the
    route when the worker refuses before the first frame) and both need the same
    view of how far it got.
    """

    def __init__(self, client: WorkerClient, req_id: str, *, ctx: RecordContext | None,
                 store) -> None:
        self.client = client
        self.req_id = req_id
        self.ctx = ctx
        self.store = store
        self.recorded = False
        #: Segments whose text reached the client, which is what the record's
        #: ``cancelled`` row reports: "8 of 12" is the useful fact about a
        #: stream someone hung up on.
        self.segments_done = 0
        self.segments_total: int | None = None
        #: Every segment's text, joined as they arrive, so a cancelled request
        #: records what was actually transcribed before it stopped -- the same
        #: text the client received, not an empty row.
        self.parts: list[str] = []
        self.text = ""
        self.language: str | None = None
        self.duration: float | None = None
        self.infer_seconds: float | None = None
        self.usage: dict | None = None

    def record(self, status: str, *, error: BaseException | None = None,
               error_type: str | None = None, error_message: str | None = None) -> None:
        """Write the one row for this request (idempotent, like ``finish``)."""
        if self.ctx is None or self.recorded:
            return
        self.recorded = True
        params = dict(self.ctx.params or {})
        params["segments"] = self.segments_done
        if self.segments_total is not None:
            params["segments_total"] = self.segments_total
        if self.duration is not None:
            params["duration"] = self.duration
        self.ctx.params = params
        # A cancelled stream still produced text, so the row carries it: the
        # operator asking "what did we get before they hung up" gets an answer.
        partial = self.text or " ".join(self.parts)
        self.ctx.finish(
            status=status,
            output_text=partial,
            raw_output=partial,
            response_content=partial if status == STATUS_OK else None,
            prompt_tokens=(self.usage or {}).get("prompt_tokens"),
            completion_tokens=(self.usage or {}).get("completion_tokens"),
            error=error,
            error_type=error_type,
            error_message=error_message,
        )


async def _open_stream(client: WorkerClient, req_id: str, audio_b64: str,
                       filename: str | None, language: str | None,
                       prompt: str) -> AsyncIterator[dict]:
    """The worker's frames for one request, as an async iterator.

    Wrapped in a function so the route can start it, pull exactly one frame, and
    hand the same iterator to the response body: the first frame is consumed
    before ``200`` is committed, and nothing is re-requested afterwards.
    """
    async for frame in client.stream_transcribe(
            req_id, audio_b64, filename=filename, language=language, prompt=prompt):
        yield frame


async def _relay(job: _Transcription, frames: AsyncIterator[dict],
                 first: dict) -> AsyncIterator[str]:
    """Turn worker frames into SSE, recording how the request ended.

    ``first`` is the frame the route already pulled (always the ``meta``: any
    error would have been turned into a status code). It is emitted here rather
    than in the route so the body starts with it on the wire.
    """
    try:
        yield _sse(job, first)
        async for frame in frames:
            yield _sse(job, frame)
    except WorkerError as exc:
        # The worker refused or died mid-stream. The client is still listening,
        # so it gets a terminal ``error`` frame and the connection closes --
        # which is the contract this endpoint documents for a failure after the
        # stream has begun.
        job.record(STATUS_ERROR, error=exc)
        yield _frame({"type": "error", "detail": _detail(exc)})
    except (asyncio.CancelledError, GeneratorExit):
        # The client is gone. Record *first*: after a disconnect Starlette keeps
        # cancelling the request's scope, so anything awaited below can raise
        # CancelledError again -- and if that happened before ``record``, the row
        # for this request would never be written at all. Writing is synchronous
        # (SQLite on the event loop, as everywhere else in this service), so it
        # cannot be interrupted; the cancel notification is the part that is
        # allowed to be dropped.
        etype, emsg = cancellation_error("ASR 流式转写")
        job.record(STATUS_CANCELLED, error_type=etype, error_message=emsg)
        # Stop the worker at the next segment boundary; get out without touching
        # the socket again (see the module docstring).
        with contextlib.suppress(BaseException):
            await asyncio.shield(job.client.cancel(job.req_id))
        raise
    except (ConnectionError, OSError) as exc:
        job.record(STATUS_ERROR, error=exc)
        yield _frame({"type": "error",
                      "detail": f"连接中断：{type(exc).__name__}"})
    else:
        job.record(STATUS_OK)


def _sse(job: _Transcription, frame: dict) -> str:
    """One worker frame, rewritten into the documented response shape.

    Times are rounded to three decimals, which is the precision
    ``/v1/audio/transcriptions``'s ``verbose_json`` reports. Without that the two
    would differ in the last float digit on every segment end -- a difference
    nobody can see but everybody's comparison script would report, and "the
    streamed segment is the verbose_json segment" should be an exact statement.
    """
    op = frame.get("op")
    if op == "meta":
        job.segments_total = int(frame.get("segments_total") or 0)
        job.duration = float(frame.get("duration") or 0.0)
        return _frame({
            "type": "meta",
            "duration": round(job.duration, 3),
            "segments_total": job.segments_total,
            "segment_seconds": int(frame.get("segment_seconds") or 0),
            "language": frame.get("language"),
        })
    if op == "segment":
        job.segments_done += 1
        text = frame.get("text") or ""
        job.parts.append(text)
        return _frame({
            "type": "segment",
            "id": int(frame.get("id") or 0),
            "start": round(float(frame.get("start") or 0.0), 3),
            "end": round(float(frame.get("end") or 0.0), 3),
            "text": text,
            "infer_ms": round(float(frame.get("infer_ms") or 0.0), 1),
        })
    if op == "done":
        job.text = frame.get("text") or ""
        job.language = frame.get("language")
        job.duration = float(frame.get("duration") or 0.0)
        job.infer_seconds = float(frame.get("infer_seconds") or 0.0)
        prompt_tokens = int(frame.get("prompt_tokens") or 0)
        completion_tokens = int(frame.get("completion_tokens") or 0)
        job.usage = {"prompt_tokens": prompt_tokens,
                     "completion_tokens": completion_tokens,
                     "total_tokens": prompt_tokens + completion_tokens}
        return _frame({
            "type": "done",
            "text": job.text,
            "language": job.language,
            "duration": round(job.duration, 3),
            "usage": job.usage,
            "infer_seconds": round(job.infer_seconds, 3),
        })
    # An op this endpoint does not know about: report it rather than emitting a
    # frame the console cannot render.
    return _frame({"type": "error", "detail": f"worker 返回了未知事件 {op!r}"})


@router.post("/asr/transcriptions/stream")
async def stream_transcription(request: Request, _=Depends(require_admin)):
    """``POST /api/apps/asr/transcriptions/stream`` -- SSE, one frame per segment.

    Admin session auth, and the request is the same ``multipart/form-data`` the
    console's ``/api/test/audio/transcriptions`` takes (``model``, ``file``,
    optional ``language``, ``prompt``), read by the same bounded parser: a 50 MB
    upload cap that is enforced while reading, and the same 400 for anything the
    parser cannot read unambiguously.
    """
    from ..engine.asr_prompt import normalize_language
    from . import audio_upload
    from .openai_api import _resolve_model

    try:
        body = await audio_upload.read_body(request)
        parts = audio_upload.parse(body, request.headers.get("content-type"))
        values, upload = audio_upload.fields(parts)
    except audio_upload.UploadTooLarge as exc:
        # The plain endpoint maps this to 400, and so does this one: keeping the
        # shared parser's code identical is worth more than the arguable
        # correctness of 413 here, because a client that switches endpoints must
        # not have to handle a different status for the same condition.
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except audio_upload.MultipartError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    model_name = (values.get("model") or "").strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="model 是必填字段")
    if upload is None or not upload.data:
        raise HTTPException(status_code=400, detail="file 是必填字段，且不能为空")

    language = values.get("language")
    if language is not None:
        language = language.strip() or None
    if language is not None:
        # Validated here as well as in the worker, for the same reason the plain
        # endpoint does it: a client asking for a language this model does not
        # have should not first wait for an audio decode.
        try:
            normalize_language(language)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
    prompt = values.get("prompt") or ""

    info, client = await _resolve_model(request, model_name, expect="asr")

    req_id = uuid.uuid4().hex
    audio_b64 = base64.b64encode(upload.data).decode("ascii")
    audio_format = (upload.filename or "").rsplit(".", 1)[-1].lower() if upload.filename else ""
    params: dict = {"language": language}
    if prompt:
        params["prompt"] = prompt
    ctx = build_context(
        request.app.state.inference_log,
        req_id=req_id,
        source=request.url.path,
        model=info.model_id,
        actor=actor_from_key_id(request.app.state.store, ""),
        params=params,
        # The same description the plain endpoint records: what was uploaded,
        # never the audio itself.
        messages=[{"role": "user", "content": json.dumps({
            "filename": upload.filename,
            "format": audio_format,
            "language": language,
            "prompt": prompt,
            "bytes": len(upload.data),
        }, ensure_ascii=False)}],
    )
    job = _Transcription(client, req_id, ctx=ctx, store=request.app.state.store)

    frames = _open_stream(client, req_id, audio_b64, upload.filename, language, prompt)
    # Pull the first frame here, before the response is committed: it is either
    # ``meta`` -- so the status is 200 and the body starts with it -- or the
    # worker's refusal, which has to reach the client as the status code the
    # plain endpoint would have used (415 for an undecodable container, 400 for
    # audio past the cap, 429 for a full queue).
    try:
        first = await frames.__anext__()
    except StopAsyncIteration:  # pragma: no cover - a worker always frames
        raise HTTPException(status_code=503, detail="worker 没有返回任何事件") from None
    except WorkerError as exc:
        job.record(STATUS_ERROR, error=exc)
        if exc.kind == "unsupported_audio":
            raise HTTPException(status_code=415, detail=str(exc)) from None
        if exc.kind == "invalid_request":
            raise HTTPException(status_code=400, detail=str(exc)) from None
        if exc.kind == "busy":
            raise HTTPException(status_code=429, detail=str(exc),
                                headers={"Retry-After": "5"}) from None
        raise HTTPException(status_code=503, detail=str(exc)) from None

    return StreamingResponse(
        _relay(job, frames, first),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
