"""Per-model worker process.

One process per loaded model. The parent talks to it over a JSON-lines socket on
127.0.0.1, which buys two things a thread could not:

* unloading a model is ``kill``, so the NPU heap is genuinely returned;
* an inference crash takes down one model, not the whole management plane.

Protocol (one JSON object per line, both directions):

  -> {"op":"health"}
  <- {"op":"health","ok":true,"model":"...","loaded":true,"context_length":2048}

  -> {"op":"generate","req_id":"x","prompt":"...","images":["<b64>"],"params":{...}}
  <- {"op":"meta","req_id":"x","prompt_tokens":12,"cached_tokens":0}
  <- {"op":"delta","req_id":"x","text":"hello"}
  <- {"op":"done","req_id":"x","finish_reason":"stop","completion_tokens":9,
      "first_token_latency_s":0.5,"decode_tps":21.9}
  <- {"op":"error","req_id":"x","message":"..."}

Auxiliary models (``--kind embedding|rerank|asr|ocr``) serve two more ops and no
``generate`` at all:

  -> {"op":"embed","req_id":"x","texts":["a","b"],"dimensions":null}
  <- {"op":"embeddings","req_id":"x","vectors":[[...]],"tokens":[3,5]}

  -> {"op":"rerank","req_id":"x","query":"q","documents":["d1","d2"]}
  <- {"op":"scores","req_id":"x","logits":[1.2,-3.4],"tokens":[11,23]}

  -> {"op":"ocr","req_id":"x","image_b64":"<base64>"}
  <- {"op":"ocr_result","req_id":"x","text":"...","lines":[{"text","score",
      "box","width_tier"}],"det_ms":41.2,"rec_ms":88.5,"width":1240,"height":1754}

A transcription can also be streamed, one frame per segment:

  -> {"op":"transcribe_stream","req_id":"x","audio_b64":"<base64>",...}
  <- {"op":"meta","req_id":"x","duration":95.5,"segments_total":4,
      "segment_seconds":30,"language":"Chinese"}
  <- {"op":"segment","req_id":"x","id":0,"start":0.0,"end":30.0,"text":"…",
      "infer_ms":2400.0}
  <- {"op":"done","req_id":"x","text":"<the same text /v1 returns>",
      "language":"Chinese","duration":95.5,"prompt_tokens":…,
      "completion_tokens":…,"infer_seconds":5.2}
  <- {"op":"error","req_id":"x","kind":"…","message":"…"}     (instead of done)

Client disconnect (EOF) cancels every in-flight request on that connection.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import logging
import os
import signal
import sys
import time

from .aux_backend import AuxBusy, AuxRequestError
from .base import GenerateParams
from ..core.models import KINDS, is_vl_embedding
from .kv_pool import UNBOUNDED
from .mock import MockBackend
from .prefix_cache import PrefixCache
from .scheduler import (
    DEFAULT_DECODE_QUANTUM,
    MAX_DECODE_QUANTUM,
    Busy,
    Scheduler,
)

logger = logging.getLogger("worker")

#: Kinds that get the auxiliary worker (no scheduler, no prefix cache).
AUX_KINDS = ("embedding", "rerank", "asr", "ocr")

#: Kinds served by ``op: generate`` -- the ones that run a Scheduler. Their
#: difference is in what they are *for* (the API refuses to offer ``ocr_vl`` to
#: an agent), not in how a request reaches them.
GENERATE_KINDS = ("chat", "ocr_vl")


def build_backend(
    kind: str, model_id: str, model_path: str, config_path: str, dev_id: int,
    context_length: int = 2048, decode_delay_ms: float = 0.0,
    min_tokens: int = 24,
    snapshot_location: str = "device",
    tokenizer_path: str | None = None, lib_path: str | None = None,
    model_kind: str = "chat", max_queue: int = 16,
):
    """The backend for one worker.

    ``kind`` is the *engine* (mock / sail / native); ``model_kind`` is what the
    model can do (chat / embedding / rerank / asr). They are separate axes: an
    embedding model can run on the mock engine on a laptop or the native one on
    the board, and the worker wires the same ops either way.
    """
    if model_kind in AUX_KINDS:
        return _build_aux_backend(kind, model_kind, model_id, model_path,
                                  config_path, dev_id, lib_path, max_queue,
                                  context_length)
    if kind == "mock":
        from pathlib import Path

        from ..core.models import read_bmodel_meta

        if model_kind == "ocr_vl":
            from .mock import MockOcrVlBackend

            return MockOcrVlBackend(model_id, context_length=context_length)
        # The mock has no graphs to inspect; take vision from the file name the
        # way the model list does, so text-only fixtures stay text-only.
        vision = bool(model_path) and read_bmodel_meta(Path(model_path))["supports_vision"]
        return MockBackend(
            model_id,
            context_length=context_length,
            supports_vision=vision,
            # A knob for tests that need a request to stay in flight long enough
            # to observe scheduling or cancellation.
            decode_delay_per_token=decode_delay_ms / 1000.0,
            min_tokens=min_tokens,
        )
    if kind == "native":
        from .native import NativeBackend

        if model_kind == "ocr_vl":
            # One resident PaddleOCR-VL bmodel and its own C ABI: no vit pos
            # tables, no M-RoPE, no KV snapshots -- see app/engine/paddle_vl.py.
            from .paddle_vl import PaddleVlBackend

            return PaddleVlBackend(
                model_path,
                tokenizer_path or (config_path.rstrip("/") + "/tokenizer.json"),
                model_id,
                lib_path=lib_path,
                dev_id=dev_id,
            )
        return NativeBackend(
            model_path,
            tokenizer_path or (config_path.rstrip("/") + "/tokenizer.json"),
            model_id,
            lib_path=lib_path,
            dev_id=dev_id,
            # The constructor's store budget is only what ``PrefixCache`` adopts
            # before the worker has a runtime budget; ``UNBOUNDED`` leaves the
            # deciding to ``configure``, which sets the real ceiling (MYS-2785).
        )
    if kind == "sail":
        from .sail_backend import SailBackend

        return SailBackend(
            model_id, model_path, config_path, dev_id,
            snapshot_location=snapshot_location,
            # Same reasoning: the store's budget here is a *placement* rule, and
            # a fixed 1 GiB one would contradict the model's own ceiling.
            device_kv_budget=UNBOUNDED,
        )
    raise SystemExit(f"unknown backend kind: {kind}")


def _seq_len_of(model_path: str | None) -> int:
    """The SEQLEN encoded in a bmodel file name, or ``MOCK_SEQ_LEN``.

    Mock-only, and the same parse ``core.models.read_bmodel_meta`` does on the
    management plane -- duplicated here rather than imported because a worker
    must not import the manager (it would pull in the whole process tree).
    """
    from .mock import MOCK_SEQ_LEN

    for part in (model_path or "").rsplit("/", 1)[-1].lower().split("_"):
        if part.startswith("seq") and part[3:].isdigit():
            return int(part[3:]) or MOCK_SEQ_LEN
    return MOCK_SEQ_LEN


def _build_aux_backend(kind: str, model_kind: str, model_id: str,
                       model_path: str, config_path: str, dev_id: int,
                       lib_path: str | None, max_queue: int,
                       context_length: int):
    """Embedding / rerank / ASR / OCR backends, mock or native."""
    from pathlib import Path

    if kind == "mock":
        from .mock import MockAsrBackend, MockEmbedBackend, MockRerankBackend, MockOcrBackend

        if model_kind == "embedding":
            if is_vl_embedding(model_path):
                from .mock import MockVlEmbedBackend

                family = ("wemm_embedding" if Path(model_path).name.lower().startswith(("wemm-embedding", "wemm_embedding"))
                          else "qwen3_vl_embedding")
                return MockVlEmbedBackend(model_id, seq_len=_seq_len_of(model_path), family=family)
            # The mock uses the *bytes* of a text as its token ids, so the mock
            # bmodel's real width is irrelevant; the SEQLEN it enforces comes
            # from the bmodel file name (`..._seq512_...`), which is where the
            # real scan reads it too. MOCK_SEQ_LEN stands in for a file whose
            # name says nothing, which is every fixture written before MYS-2706.
            #
            # Honouring the name is what lets a test stand a seq512 build up and
            # watch ingest split an over-long chunk through the **real** refusal
            # path rather than a fake one.
            return MockEmbedBackend(model_id, seq_len=_seq_len_of(model_path))
        if model_kind == "asr":
            # Decodes the audio for real (so 415 and durations come from real
            # parsing) but invents the transcript; see MockAsrBackend.
            #
            # ``CV84X6_MOCK_ASR_SEGMENT_MS`` is the knob the console developer
            # uses: it makes each segment take that long, so the demo page's
            # progress bar and its "stop" button can be exercised on a laptop
            # against a stream that actually pauses. Unset -- the default --
            # means no delay at all, which is what every test wants.
            return MockAsrBackend(
                model_id,
                segment_delay_ms=float(
                    os.environ.get("CV84X6_MOCK_ASR_SEGMENT_MS") or 0.0),
                # The queue bound is the same one the real backend gets, so the
                # mock can exercise the 429 the streaming endpoint gives when
                # the worker is overloaded.
                max_queue=max_queue)
        if model_kind == "ocr":
            # Reads the image header for real (so a bad image is a real 400 and
            # the reported size is real) but invents the text.
            return MockOcrBackend(model_id)
        return MockRerankBackend(model_id)
    if kind == "native":
        from .aux_backend import AsrBackend, AuxEmbedBackend, AuxRerankBackend

        if model_kind == "asr":
            return AsrBackend(model_path, config_path, model_id, lib_path=lib_path,
                              dev_id=dev_id, max_queue=max_queue)
        if model_kind == "ocr":
            from .ocr_ppocr import OcrBackend

            return OcrBackend(model_path, config_path, model_id, lib_path=lib_path,
                              dev_id=dev_id, max_queue=max_queue)
        if model_kind == "embedding" and is_vl_embedding(model_path):
            from .vl_embed import VlEmbedBackend

            return VlEmbedBackend(model_path, config_path, model_id, lib_path=lib_path,
                                  dev_id=dev_id, max_queue=max_queue)
        cls = AuxEmbedBackend if model_kind == "embedding" else AuxRerankBackend
        return cls(model_path, config_path, model_id, lib_path=lib_path,
                   dev_id=dev_id, max_queue=max_queue)
    raise SystemExit(
        f"backend {kind!r} cannot serve a {model_kind} model "
        "(only mock and native implement the auxiliary engines)")


# Max size of one protocol line (a request with its base64 images).
STREAM_LIMIT = 64 * 1024 * 1024

#: The line limit for an ASR worker. A transcription request carries the whole
#: audio file base64-encoded, and the endpoint accepts 50 MiB: base64 is 4/3 of
#: the input, so that one line is up to 66.7 MiB -- already past the chat
#: path's 64 MiB bound, which would reject a *legal* upload with
#: ``Separator is found, but chunk is longer than limit`` from asyncio's reader
#: before any of our code saw it. Sized from the endpoint's own constant rather
#: than a second hard-coded number, so raising the upload cap cannot silently
#: leave the transport behind.
def _asr_stream_limit() -> int:
    from ..api.audio_upload import MAX_UPLOAD_BYTES

    # 4/3 for base64, plus the JSON envelope and the other fields.
    return (MAX_UPLOAD_BYTES * 4 // 3) + (1024 * 1024)


def stream_limit_for(model_kind: str) -> int:
    """The protocol line bound a worker of ``model_kind`` must read with.

    A function rather than an inline expression at the ``start_server`` call so
    the choice is testable: the bug this replaces was that ASR silently got the
    chat path's bound, and a test that only checks ``_asr_stream_limit()`` would
    not have noticed.
    """
    return _asr_stream_limit() if model_kind == "asr" else STREAM_LIMIT


async def handle_generate(sched: Scheduler, backend, msg: dict, write) -> None:
    req_id = msg["req_id"]
    params = GenerateParams(**msg.get("params", {}))
    try:
        images = [base64.b64decode(s, validate=True) for s in msg.get("images") or []]
        tokens = await backend.encode(msg.get("prompt", ""), images or None)
    except (ValueError, OSError) as exc:  # bad base64/image, too many placeholders, ...
        await write({"op": "error", "req_id": req_id, "message": str(exc),
                     "kind": "invalid_request"})
        return

    limit = getattr(backend, "max_prompt_length", backend.context_length - 1)
    if len(tokens) > limit:
        await write({
            "op": "error", "req_id": req_id, "kind": "invalid_request",
            "message": f"prompt is {len(tokens)} tokens, context limit is {limit}",
        })
        return

    prompt_len = len(tokens)
    reported = False
    state: dict = {}

    async def sink(text: str) -> None:
        nonlocal reported
        if not reported:
            reported = True
            # req.cached_tokens is final by the time the first token streams
            # (the scheduler resolves the prefix hit when it creates the
            # session), so the number the UI shows is the real one.
            await write({
                "op": "meta", "req_id": req_id,
                "prompt_tokens": prompt_len,
                "cached_tokens": state["req"].cached_tokens if "req" in state else 0,
            })
        try:
            await write({"op": "delta", "req_id": req_id, "text": text})
        except (ConnectionResetError, BrokenPipeError):
            # The client is gone. Flag the request so the scheduler stops
            # decoding it instead of generating into a closed socket until
            # max_tokens.
            sched.cancel(req_id)
            raise

    # enqueue() returns the Request before streaming starts, so sink() can read
    # the scheduler-resolved cached_tokens for its "meta" event.
    try:
        req = sched.enqueue(req_id, tokens, params, sink)
    except Busy as exc:
        await write({"op": "error", "req_id": req_id, "message": str(exc), "kind": "busy"})
        return
    state["req"] = req
    await sched.wait(req)

    if req.error:
        await write({"op": "error", "req_id": req_id, "message": req.error})
        return

    # Recompute latency/TPS from the request record rather than trusting the
    # streaming side, so the numbers in the UI match the request that ran.
    ftl = None
    if req.first_token_at is not None:
        ftl = req.first_token_at - req.started_at
    tps = None
    if req.generated and req.first_token_at and req.finished_at:
        span = req.finished_at - req.first_token_at
        if span > 0:
            tps = len(req.generated) / span

    await write({
        "op": "done", "req_id": req_id,
        "finish_reason": req.finish_reason,
        "prompt_tokens": prompt_len,
        "cached_tokens": req.cached_tokens,
        "completion_tokens": len(req.generated),
        "first_token_latency_s": ftl,
        "decode_tps": tps,
    })


async def handle_embed(backend, msg: dict, write) -> None:
    """``op: embed`` -> ``op: embeddings``. One vector per text, order preserved."""
    req_id = msg["req_id"]
    texts = msg.get("texts")
    dimensions = msg.get("dimensions")
    multimodal = "inputs" in msg
    if multimodal and not callable(getattr(backend, "embed_multimodal", None)):
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": "该模型不支持多模态 embedding 输入"})
        return
    if not multimodal and (not isinstance(texts, list) or not texts or
                           not all(isinstance(t, str) for t in texts)):
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": "texts 必须是非空字符串数组"})
        return
    if not multimodal and not all(texts):
        # An empty string is a *client* mistake, and the API refuses it with 400
        # before reaching here; the check stays because the RPC is the boundary
        # and a second caller must get the same answer.
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": "texts 不能包含空字符串"})
        return
    try:
        if multimodal:
            vectors, counts = await backend.embed_multimodal(
                msg["inputs"], dimensions, msg.get("instruction"))
        else:
            vectors, counts = await backend.embed(texts, dimensions)
    except AuxBusy as exc:
        await write({"op": "error", "req_id": req_id, "kind": "busy",
                     "message": str(exc)})
        return
    except AuxRequestError as exc:
        # The input cannot be served as sent (too long for the graph): a 400 at
        # the HTTP layer, not a 503 implying the model is broken.
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": str(exc)})
        return
    except Exception as exc:  # engine, tokenizer or conversion failure
        await write({"op": "error", "req_id": req_id, "kind": "server",
                     "message": f"{type(exc).__name__}: {exc}"})
        return
    await write({"op": "embeddings", "req_id": req_id,
                 "vectors": vectors, "tokens": counts})


async def handle_rerank(backend, msg: dict, write) -> None:
    """``op: rerank`` -> ``op: scores``. Raw logits, one per document."""
    req_id = msg["req_id"]
    query = msg.get("query")
    documents = msg.get("documents")
    if not isinstance(query, str) or not query:
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": "query 必须是非空字符串"})
        return
    if not isinstance(documents, list) or not documents or \
            not all(isinstance(d, str) and d for d in documents):
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": "documents 必须是非空字符串数组"})
        return
    try:
        logits, counts = await backend.rerank(query, documents)
    except AuxBusy as exc:
        await write({"op": "error", "req_id": req_id, "kind": "busy",
                     "message": str(exc)})
        return
    except AuxRequestError as exc:
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": str(exc)})
        return
    except Exception as exc:
        await write({"op": "error", "req_id": req_id, "kind": "server",
                     "message": f"{type(exc).__name__}: {exc}"})
        return
    await write({"op": "scores", "req_id": req_id,
                 "logits": logits, "tokens": counts})


async def _read_transcribe_request(msg: dict, write) -> tuple[bytes, str | None,
                                                             str | None, str] | None:
    """The four fields of a transcription request, or None after writing a 400.

    Shared by ``op: transcribe`` and ``op: transcribe_stream`` so the two cannot
    disagree about which malformed request they refuse, or with what message.
    """
    req_id = msg["req_id"]
    raw = msg.get("audio_b64")
    if not isinstance(raw, str) or not raw:
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": "audio_b64 必须是非空的 base64 字符串"})
        return None
    filename = msg.get("filename")
    if filename is not None and not isinstance(filename, str):
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": "filename 必须是字符串或 null"})
        return None
    language = msg.get("language")
    if language is not None and not isinstance(language, str):
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": "language 必须是字符串或 null"})
        return None
    prompt = msg.get("prompt") or ""
    if not isinstance(prompt, str):
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": "prompt 必须是字符串"})
        return None
    try:
        audio = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as exc:
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": f"音频不是合法的 base64：{exc}"})
        return None
    return audio, filename, language, prompt


def _transcribe_error(exc: BaseException) -> dict:
    """The ``kind`` a transcription failure carries to the API's status mapping."""
    from .asr_audio import UnsupportedAudio

    if isinstance(exc, UnsupportedAudio):
        # Not "the server is broken" and not "the request is malformed": the
        # audio is a format this device cannot decode. 415 is the code for that,
        # and the message names the formats that *are* decodable.
        return {"kind": "unsupported_audio", "message": str(exc)}
    if isinstance(exc, AuxBusy):
        return {"kind": "busy", "message": str(exc)}
    if isinstance(exc, AuxRequestError):
        return {"kind": "invalid_request", "message": str(exc)}
    return {"kind": "server", "message": f"{type(exc).__name__}: {exc}"}


async def handle_transcribe(backend, msg: dict, write) -> None:
    """``op: transcribe`` -> ``op: transcript``.

    The audio travels base64 in the request. It is decoded here rather than in
    the API process because the ffmpeg and the mel front end live with the
    model: a second decoder in the management plane would be a second thing to
    keep in step with the bmodel.
    """
    req_id = msg["req_id"]
    request = await _read_transcribe_request(msg, write)
    if request is None:
        return
    audio, filename, language, prompt = request

    try:
        result = await backend.transcribe(audio, filename=filename,
                                          language=language, prompt=prompt)
    except Exception as exc:  # mapped by kind; see _transcribe_error
        await write({"op": "error", "req_id": req_id, **_transcribe_error(exc)})
        return

    await write({
        "op": "transcript", "req_id": req_id,
        "text": result.text,
        "language": result.language,
        "duration": result.duration,
        "segments": [{"id": i, "start": s.start, "end": s.end, "text": s.text}
                     for i, s in enumerate(result.segments)],
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "infer_seconds": result.infer_seconds,
    })


async def handle_transcribe_stream(backend, msg: dict, write) -> None:
    """``op: transcribe_stream`` -> ``meta`` / ``segment``* / ``done`` | ``error``.

    The frames mirror the chat path's (``meta`` first, then one per unit of
    progress, then a terminal frame), so the API's SSE relay is the same shape
    for both. Three orderings are contractual, and are what this function is
    arranged around:

    * every refusal that can be settled without the NPU -- an undecodable
      container, audio past the 30-minute cap, a language this model does not
      know -- is raised by the backend *before* its first frame and therefore
      becomes a lone ``error`` frame. The API relays that as a status code, so
      the client sees the same 415/400 the non-streaming endpoint gives instead
      of a 200 whose first event is an error;
    * ``meta`` is written before the first segment runs, which is the point of
      the endpoint: the UI learns the duration and the segment count while the
      engine is still idle;
    * ``done`` carries exactly the text ``op: transcribe`` would have returned,
      because both come from the same joiner.

    A client that hangs up stops the loop between segments: ``asyncio`` cancels
    this task when the connection closes, the segment in flight finishes anyway
    (see ``_run_uninterruptible``), and the ``async for`` simply does not
    advance. No ``done`` is written -- there is nobody to send it to -- and the
    connection handler's teardown is what records the cancellation.
    """
    req_id = msg["req_id"]
    request = await _read_transcribe_request(msg, write)
    if request is None:
        return
    audio, filename, language, prompt = request

    frames = backend.iter_transcribe(
        audio, filename=filename, language=language, prompt=prompt)
    try:
        while True:
            # The backend step and the socket write are separated on purpose:
            # the two fail for completely different reasons, and only the second
            # can mean "the peer is gone". Catching by exception *type* around
            # both (what this used to do) swallowed the backend's own OSErrors --
            # ENOSPC writing the ffmpeg temp file, EACCES starting the binary --
            # and left the API waiting for TRANSCRIBE_TIMEOUT_S instead of
            # reporting them.
            try:
                frame = await frames.__anext__()
            except StopAsyncIteration:
                return
            except Exception as exc:  # mapped by kind; see _transcribe_error
                # A backend refusal or engine failure: the client is still
                # listening, so it gets a terminal frame rather than a silent
                # close.
                logger.info("asr stream %s: failed: %s", req_id, exc)
                with contextlib.suppress(ConnectionError, OSError):
                    await write({"op": "error", "req_id": req_id,
                                 **_transcribe_error(exc)})
                return

            kind = frame.pop("type")
            if kind == "meta":
                logger.info("asr stream %s: %.1fs, %d segment(s) of %ds",
                            req_id, frame.get("duration") or 0.0,
                            int(frame.get("segments_total") or 0),
                            int(frame.get("segment_seconds") or 0))
            elif kind == "segment":
                # One line per segment, with times and a length rather than the
                # text: this is the record that answers "did anything run after
                # the client hung up?" -- the ids missing after the last line
                # before the disconnect are the segments that never started.
                logger.info("asr stream %s: segment %d [%.2f-%.2f] %.0f ms, %d chars",
                            req_id, int(frame.get("id") or 0),
                            float(frame.get("start") or 0.0),
                            float(frame.get("end") or 0.0),
                            float(frame.get("infer_ms") or 0.0),
                            len(frame.get("text") or ""))
            else:
                logger.info("asr stream %s: done, %.2fs total", req_id,
                            float(frame.get("infer_seconds") or 0.0))
            # Uncaught on purpose: a failure here is the peer having left, and
            # the connection handler's teardown is what stops the request.
            await write({"op": "done" if kind == "done" else kind,
                         "req_id": req_id, **frame})
    finally:
        # Releases the request's queue slot even on the early-return paths; an
        # abandoned generator would hold it until the garbage collector ran.
        await frames.aclose()


async def handle_ocr(backend, msg: dict, write) -> None:
    """``op: ocr`` -> ``op: ocr_result``.

    The image travels base64 in the request and is decoded here rather than in
    the API process: OpenCV (the device's Sophon build) and the model's own
    transform parameters live with the model, and a second decoder in the
    management plane would be a second thing to keep in step with the bmodel.

    ``return_boxes`` is honoured by the worker rather than by the API, because
    the boxes are already there: dropping them on the way out is one filter, and
    doing it in the API would mean a second copy of the response shape.

    ``mode`` is validated here, not only at the API: the worker owns what the
    two modes mean, and the console's test route and the MCP bridge both reach
    this op without going through the ``/v1`` handler.
    """
    req_id = msg["req_id"]
    raw = msg.get("image_b64")
    if not isinstance(raw, str) or not raw:
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": "image_b64 必须是非空的 base64 字符串"})
        return
    try:
        image = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as exc:
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": f"图片不是合法的 base64：{exc}"})
        return

    from .ocr_ppocr import MODE_LINES, OcrModeUnavailable, _check_mode

    try:
        mode = _check_mode(msg.get("mode"))
    except AuxRequestError as exc:
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": str(exc)})
        return

    try:
        result = await backend.recognise(image, mode=mode)
    except OcrModeUnavailable as exc:
        # The model works but is a file short: a 400 naming the missing file,
        # not a 503 that would send the caller looking at the hardware.
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": str(exc)})
        return
    except AuxBusy as exc:
        await write({"op": "error", "req_id": req_id, "kind": "busy",
                     "message": str(exc)})
        return
    except AuxRequestError as exc:
        # The image cannot be served as sent (unreadable, too small): a 400.
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": str(exc)})
        return
    except Exception as exc:  # engine, OpenCV or conversion failure
        await write({"op": "error", "req_id": req_id, "kind": "server",
                     "message": f"{type(exc).__name__}: {exc}"})
        return

    payload = {
        "op": "ocr_result", "req_id": req_id,
        "mode": getattr(result, "mode", MODE_LINES) or MODE_LINES,
        "text": result.text,
        "lines": [_line_payload(line, result.mode)
                  for line in result.lines],
        "det_ms": result.det_ms,
        "rec_ms": result.rec_ms,
        "width": result.width,
        "height": result.height,
    }
    if payload["mode"] == "layout":
        payload["layout_ms"] = getattr(result, "layout_ms", 0.0)
        payload["blocks"] = [_block_payload(block) for block in result.blocks]
    await write(payload)


async def handle_detect_page(backend, msg: dict, write) -> None:
    """``op: detect_page`` -> ``op: detect_page_result``: the layout half of ``vl``.

    Deliberately separate from ``op: ocr`` rather than a third ``mode``: the
    answer has no text and no lines, only regions, and the caller is the API
    process driving the whole page, not a client asking for a transcription.
    (``MODE_VL`` is accepted by ``/v1/ocr`` but *not* by this op's
    ``_check_mode``: see ``ocr_ppocr.MODE_VL``.)

    The regions come back in the detector's order with their class scores; the
    reading order is decided later, by the code that has the whole page.

    ``OcrModeUnavailable`` -- a four-file install with no layout bmodel -- is
    answered as ``invalid_request``. Its operator action is "download one file",
    which is a 400's business; a 503 would send them to look at the hardware.
    """
    req_id = msg["req_id"]
    raw = msg.get("image_b64")
    if not isinstance(raw, str) or not raw:
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": "image_b64 必须是非空的 base64 字符串"})
        return
    try:
        image = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as exc:
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": f"图片不是合法的 base64：{exc}"})
        return
    from .ocr_ppocr import OcrModeUnavailable

    try:
        result = await backend.detect_page(image)
    except AuxBusy as exc:
        await write({"op": "error", "req_id": req_id, "kind": "busy",
                     "message": str(exc)})
        return
    except (AuxRequestError, OcrModeUnavailable) as exc:
        # ``OcrModeUnavailable`` is *not* an ``AuxRequestError`` (it is an
        # ``OcrUnavailable``, an engine-class error), but the operator's action
        # is the same as for a bad image: download the missing file. Reporting
        # it as ``server`` would be a 503 sending them to look at the hardware.
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": str(exc)})
        return
    except Exception as exc:
        await write({"op": "error", "req_id": req_id, "kind": "server",
                     "message": f"{type(exc).__name__}: {exc}"})
        return
    await write({"op": "detect_page_result", "req_id": req_id, **result})


async def handle_ocr_page(backend, msg: dict, write) -> None:
    """``op: ocr_page`` -> ``op: ocr_page_result``: one whole page through the VLM.

    This is ``mode: "vl"``'s second half. The regions were detected by the *OCR*
    model (``op: detect_page`` on the other worker) and arrive here as boxes;
    this worker crops them out of the page, asks the VLM to read each one with
    the instruction its class gets, and turns a table's OTSL into HTML.

    Why the page travels to the VLM worker rather than the crops: one message
    of one image plus a dozen boxes is smaller than a dozen cropped images, and
    the boxes are then applied to exactly the bytes the detector measured them
    against. Both workers decode with the same device OpenCV, so the crop lands
    on the same pixels either way.

    The orchestration itself is :func:`app.engine.ocr_vl_page.recognise_page`,
    which is pure host code -- so the ordering, the prompt map and the OTSL ->
    HTML conversion are all covered by tests that need no NPU.

    Errors are classified exactly as ``op: ocr``'s are, because the caller maps
    them to the same HTTP codes: an unusable image is ``invalid_request`` (400),
    a full queue is ``busy`` (429), and anything else is the engine's (503).
    """
    req_id = msg["req_id"]
    raw = msg.get("image_b64")
    if not isinstance(raw, str) or not raw:
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": "image_b64 必须是非空的 base64 字符串"})
        return
    try:
        image = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as exc:
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": f"图片不是合法的 base64：{exc}"})
        return
    regions = msg.get("regions")
    if not isinstance(regions, list):
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": "regions 必须是版面模型给出的区域数组"})
        return

    from .ocr_ppocr import OcrUnavailable
    from .ocr_vl_page import MAX_NEW_TOKENS, recognise_page

    try:
        # Decoding is the *backend's* job, not the worker's: OpenCV comes from
        # the device and the mock has none, so a worker that imported cv2 here
        # would make the whole ``vl`` path untestable off the board.
        bgr = await asyncio.to_thread(backend.decode_page, image)
        height, width = bgr.shape[:2]
        budget = int(msg.get("max_new_tokens") or MAX_NEW_TOKENS)

        async def recognise(crop, task):
            return await backend.recognise_block(crop, task,
                                                 max_new_tokens=budget)

        page = await recognise_page(bgr, regions, recognise=recognise,
                                    page_hw=(height, width))
    except AuxBusy as exc:
        await write({"op": "error", "req_id": req_id, "kind": "busy",
                     "message": str(exc)})
        return
    except (AuxRequestError, OcrUnavailable) as exc:
        await write({"op": "error", "req_id": req_id, "kind": "invalid_request",
                     "message": str(exc)})
        return
    except Exception as exc:  # engine, OpenCV or conversion failure
        await write({"op": "error", "req_id": req_id, "kind": "server",
                     "message": f"{type(exc).__name__}: {exc}"})
        return

    await write({
        "op": "ocr_page_result", "req_id": req_id, "mode": "vl",
        "text": page.markdown, "blocks": page.blocks,
        "width": page.width, "height": page.height,
        "vl_ms": page.vl_ms, "vl_tokens": page.vl_tokens,
        "skipped": page.skipped,
    })


def _line_payload(line, mode: str) -> dict:
    """One OCR line on the wire.

    ``width_tier`` is dropped in layout mode: it is a debugging detail of the
    *rec* pass, and a layout response can carry hundreds of lines -- the field
    would be most of the payload for something no layout caller can use.
    """
    entry = {"text": line.text, "score": line.score,
             "box": [[float(x), float(y)] for x, y in line.box]}
    if mode != "layout":
        entry["width_tier"] = line.width_tier
    return entry


def _block_payload(block: dict) -> dict:
    return {
        "index": block["index"],
        "type": block["type"],
        "label": block["label"],
        "score": block["score"],
        "box": block["box"],
        "text": block["text"],
        "lines": [{"text": line.text, "score": line.score,
                   "box": [[float(x), float(y)] for x, y in line.box]}
                  for line in block["lines"]],
    }


async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, sched, backend,
                model_id, ready: asyncio.Event | None = None):
    inflight: set[str] = set()
    model_kind = getattr(backend, "kind", "chat")

    async def write(obj: dict) -> None:
        writer.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())
        await writer.drain()

    tasks: set[asyncio.Task] = set()
    #: Streaming aux tasks by request id, so ``op: cancel`` can reach them.
    #: Chat requests are cancelled through the scheduler; an ASR stream has no
    #: scheduler to ask, so its task is what gets cancelled.
    streams: dict[str, asyncio.Task] = {}
    try:
        while True:
            line = await reader.readline()
            if not line:
                break  # parent went away: cancel everything below
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                await write({"op": "error", "message": "invalid json"})
                continue

            op = msg.get("op")
            if op == "health":
                # `loaded` is answered from the worker's own readiness, not from
                # the constant this used to be: the manager treats a health
                # reply as the readiness handshake, so a hard-coded True here
                # would let a worker that is still bringing its engine up vouch
                # for itself. `serve` is only ever reached after the banner
                # (see amain), but the flag makes that ordering a fact this
                # reply states rather than one the reader has to assume.
                is_ready = ready is None or ready.is_set()
                await write({
                    "op": "health", "req_id": msg.get("req_id", "__health__"),
                    "ok": True, "model": model_id, "loaded": is_ready,
                    "kind": model_kind,
                    "context_length": getattr(backend, "context_length",
                                              getattr(backend, "seq_len", 0)),
                    "hidden_size": getattr(backend, "hidden_size",
                                           getattr(backend, "hidden", None)),
                    "supports_vision": bool(getattr(backend, "supports_vision", False)),
                    "fault": bool(getattr(backend, "fault", False)),
                })
            elif op == "stats":
                # Echo req_id: the client multiplexes responses by it, so a reply
                # without one is unroutable and the caller times out.
                stats = sched.stats() if sched is not None else {
                    # Auxiliary workers have no scheduler. The readiness probe
                    # only requires `op: stats` and a dict, and the console reads
                    # these keys, so the shape stays the same with the counters
                    # that have no meaning here reported as zero -- except
                    # ``inflight``, which is real: the idle sweep will not unload
                    # a model whose worker is serving a request, and a constant 0
                    # there would let it unload one mid-embed.
                    "max_concurrent": 1,
                    "inflight": _aux_inflight(backend),
                    "queued": _aux_queued(backend),
                    # An auxiliary engine holds no cross-request KV, so its
                    # runtime footprint is the working buffer its one in-flight
                    # call needs -- reported per kind rather than invented here,
                    # and only while something is running (MYS-2675).
                    "kv_used_bytes": (_aux_runtime_bytes(backend)
                                      if _aux_inflight(backend) else 0),
                    "completed": 0, "cancelled": 0, "cache_entries": 0,
                    "cache_bytes": 0, "cache_hits": 0, "cache_misses": 0,
                }
                await write({"op": "stats", "req_id": msg.get("req_id", "__stats__"),
                             **stats, "kind": model_kind,
                             "fault": bool(getattr(backend, "fault", False))})
            elif op == "cancel":
                if sched is not None:
                    sched.cancel(msg.get("req_id", ""))
                else:
                    # An auxiliary worker has no scheduler. A streaming
                    # transcription is the one aux op with something to stop, so
                    # cancelling its task stops the loop at the next segment
                    # boundary -- the same place a client hang-up stops it.
                    task = streams.get(msg.get("req_id", ""))
                    if task is not None:
                        task.cancel()
            elif op == "configure":
                if sched is None:
                    await write({"op": "configure",
                                 "req_id": msg.get("req_id", "__configure__")})
                else:
                    applied = configure(sched, backend, msg)
                    await write({"op": "configure",
                                 "req_id": msg.get("req_id", "__configure__"),
                                 **applied})
            elif op == "generate":
                # Chat-shaped kinds: a 35B answers a conversation, and
                # PaddleOCR-VL answers one image plus a task prompt through the
                # same op (it is a separate kind because it is not a general
                # conversation model, not because it is called differently).
                if model_kind not in GENERATE_KINDS:
                    # The manager routes by kind, so this is a bug in the caller
                    # -- but answering it beats hanging up on the request.
                    await write({"op": "error", "req_id": msg.get("req_id", ""),
                                 "kind": "invalid_request",
                                 "message": f"这是一个 {model_kind} 模型，不支持 generate"})
                    continue
                rid = msg["req_id"]
                inflight.add(rid)
                t = asyncio.create_task(handle_generate(sched, backend, msg, write))
                tasks.add(t)
                t.add_done_callback(lambda _t, r=rid: (inflight.discard(r), tasks.discard(_t)))
            elif op in ("embed", "rerank", "transcribe", "transcribe_stream",
                        "ocr", "detect_page", "ocr_page"):
                # `detect_page` is the OCR model's layout half of mode "vl";
                # `ocr_page` is the VLM's recognition half. They live on
                # different workers because the two bmodels cannot share a
                # process (docs/ocr-vl.md §6.1), and this table is where that
                # split is stated.
                want = {"embed": "embedding", "rerank": "rerank",
                        "transcribe": "asr", "transcribe_stream": "asr",
                        "ocr": "ocr", "detect_page": "ocr",
                        "ocr_page": "ocr_vl"}[op]
                if model_kind != want:
                    await write({"op": "error", "req_id": msg.get("req_id", ""),
                                 "kind": "invalid_request",
                                 "message": f"这是一个 {model_kind} 模型，不支持 {op}"})
                    continue
                rid = msg.get("req_id", "")
                handler = {"embed": handle_embed, "rerank": handle_rerank,
                           "transcribe": handle_transcribe,
                           "transcribe_stream": handle_transcribe_stream,
                           "ocr": handle_ocr, "detect_page": handle_detect_page,
                           "ocr_page": handle_ocr_page}[op]
                # Streaming transcriptions join ``generate`` in the in-flight
                # set: they are the other op that can run for minutes, and a
                # worker shutdown has to know about them.
                if op == "transcribe_stream":
                    inflight.add(rid)
                t = asyncio.create_task(handler(backend, msg, write))
                tasks.add(t)
                if op == "transcribe_stream":
                    streams[rid] = t

                    def _done(_t, r=rid):
                        inflight.discard(r)
                        streams.pop(r, None)
                        tasks.discard(_t)

                    t.add_done_callback(_done)
                else:
                    t.add_done_callback(lambda _t: tasks.discard(_t))
            elif op == "shutdown":
                break
            else:
                await write({"op": "error", "message": f"unknown op {op}"})
    finally:
        if sched is not None:
            for rid in list(inflight):
                sched.cancel(rid)
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


MAX_CONCURRENCY = 3     # hard cap per model (MYSWY 2026-10-24)

#: The margin the *runtime* budget used to hold back, kept only so the docstring
#: and the tests can state what changed. It is **not** used any more: 512 MiB is
#: one of the values MYS-2703 measured as already wedged.
#:
#: MYS-2703 swept it: ~280 MiB wedged (136 s), 512 MiB wedged (135.8 s),
#: 640 MiB clean (12 min / 398 requests), 1024 MiB clean (12 min / 404). The load
#: path was given a 1 GiB floor as a result; the runtime path was not, and this
#: constant is what it kept using. See ``npu_runtime_reserve_bytes``.
NPU_SAFETY_BYTES = 512 << 20


def npu_runtime_reserve_bytes() -> int:
    """Headroom the *runtime* session/cache budget must leave on the NPU heap.

    The same number the load check uses (``core.models._check_npu_reserve``),
    read from the same environment variable. Deliberately one source, because
    two constants is exactly how the hole this fixes opened: MYS-2703 raised the
    load floor to 1 GiB and the worker's own budget kept holding back 512 MiB,
    a figure the sweep had already shown to wedge.

    ``CV84X6_NPU_RESERVE_MB`` arrives from the manager's environment (workers are
    spawned by it, so they inherit it), and 0 disables the floor on both paths --
    a board without this failure mode can serve with the whole heap.
    """
    from ..core.mem_limit import npu_reserve_bytes

    return int(npu_reserve_bytes())


def _aux_gate(backend):
    """The auxiliary worker's admission gate, or None for a chat backend.

    Every aux backend (embedding, rerank, ASR, OCR) holds one ``_Serialised``,
    named ``_gate`` on all four. Reading it by name rather than by class keeps
    this working for a backend a test substitutes, which is the point: the
    ``inflight`` number below is what the idle sweep trusts.
    """
    return getattr(backend, "_gate", None)


def _aux_inflight(backend) -> int:
    """Requests this auxiliary worker is serving right now (0 if unknown)."""
    gate = _aux_gate(backend)
    return int(getattr(gate, "active", 0) or 0)


def _aux_queued(backend) -> int:
    """Requests admitted and waiting for the engine lock.

    ``inflight`` counts everything admitted, so a single request that is
    currently holding the NPU reports ``inflight: 1`` and this 0; two requests
    report 2 and 1. The console shows them separately, which is what makes "the
    model is busy" legible.
    """
    gate = _aux_gate(backend)
    lock = getattr(gate, "_lock", None)
    locked = bool(getattr(lock, "locked", lambda: False)())
    active = int(getattr(gate, "active", 0) or 0)
    # One admitted request is the one holding the lock; anything beyond that is
    # waiting behind it.
    return max(0, active - 1) if locked else 0


def _aux_runtime_bytes(backend) -> int:
    """Device bytes an auxiliary worker's in-flight call adds on top of its model.

    These engines hold no cross-request KV: one call is one forward through
    fixed graphs, so what a request costs is the working buffer the backend was
    built with -- ``worker_bytes`` when the backend states one, and the per-kind
    default from ``mem_limit`` otherwise. Reported only while something is
    running; the caller zeroes it when idle, which is the state the device is
    actually in between requests.
    """
    from ..core import mem_limit

    stated = getattr(backend, "worker_bytes", None)
    if stated is not None:
        return max(0, int(stated))
    return int(mem_limit.AUX_WORKING_BYTES.get(
        getattr(backend, "kind", ""), mem_limit.AUX_WORKING_BYTES["default"]))


def npu_cache_cap(backend, max_concurrent: int) -> int | None:
    """Bytes the prefix cache may take without starving sessions of NPU memory.

    Free NPU memory as bm-smi sees it right now (weights and resident state
    already counted), minus what the remaining concurrent sessions can still
    claim when they are parked, minus the D7 headroom floor. None when the board
    figures are unavailable (no bm-smi, mock backend).
    """
    per_session = int(getattr(backend, "session_state_bytes", 0) or 0)
    if not per_session:
        return None
    from ..core import monitor

    smi = monitor.bm_smi_sample()
    total, used = smi.get("mem_total_bytes"), smi.get("mem_used_bytes")
    if not total or used is None:
        return None
    return max(0, total - used - max_concurrent * per_session
               - npu_runtime_reserve_bytes())


def npu_kv_budget(backend) -> int | None:
    """NPU bytes parked sessions and the prefix cache may share.

    Sampled once the model is loaded (weights + the resident session's state
    already counted): free memory minus the D7 headroom floor
    (``npu_runtime_reserve_bytes``). The scheduler admits requests against it
    and the cache gives way to sessions, so nothing is reserved up front for
    sessions that may never come. None for engines that cannot report per-token
    KV (mock, pre-v0.5 library) or without bm-smi.

    The floor is the same one the load check applies, and that is the whole
    point (MYS-2784). Sessions grow into this budget *after* the load, so a
    budget that spends the floor walks the heap back into the band the load
    check exists to keep it out of: measured on `.151`, 1567 MiB free after the
    load, a 1056 MiB budget, two concurrent 17.7k sessions, and **2 MiB** free.

    Since MYS-2675 this is the *device* answer. A model with a configured memory
    limit gets a smaller figure -- see ``apply_mem_limit`` -- because its
    ceiling is the operator's number, not the whole card's free memory.
    """
    if not int(getattr(backend, "kv_bytes_per_token", 0) or 0):
        return None
    from ..core import monitor

    smi = monitor.bm_smi_sample()
    total, used = smi.get("mem_total_bytes"), smi.get("mem_used_bytes")
    if not total or used is None:
        return None
    return max(0, total - used - npu_runtime_reserve_bytes())


def apply_mem_limit(sched: Scheduler, backend, limit_bytes: int | None,
                    static_bytes: int | None = None) -> dict:
    """Trim the scheduler's session budget to this model's memory limit.

    ``limit_bytes`` is ``ModelManager.mem_limit_bytes`` for this model and
    ``static_bytes`` its measured static footprint; the manager passes both on
    the worker command line, where they are facts about the model rather than
    settings the worker could derive (the worker cannot parse its own bmodel's
    mem_info without a second libbmrt, and must not -- the management plane owns
    that number).

    The rule, and why it is a ``min`` rather than an assignment:

      * a limit makes the budget ``limit - static``: the sessions and the prefix
        cache may take what the ceiling leaves after the weights;
      * an unset limit (None -- a worker started by hand, or an older manager)
        leaves ``kv_budget_bytes`` exactly as ``npu_kv_budget`` computed it;
      * the device is still the hard ceiling, so the result is the smaller of
        the two. A limit *above* what the card can spare must not make the
        scheduler over-admit.

    Zero is a legitimate answer: it means the limit leaves no room for sessions
    on top of the weights, and ``Scheduler._fits`` already admits only a lone
    session against a zero budget. Nothing here refuses the load -- that is
    ``ModelManager._check_mem_limit``'s job, on static alone.

    **Recomputed, never accumulated.** The device reading is kept on the
    scheduler (``device_budget_bytes``) and each call starts from it rather than
    from the current, already-trimmed ``kv_budget_bytes``. Otherwise a limit
    applied twice would shrink the budget twice -- and, since MYS-2785, *raising*
    a limit through ``PUT /api/models/{id}/settings`` has to be able to give the
    cache its room back without a reload. That only works if the previous limit
    left no trace.

    Returns the applied numbers for the log and for ``stats``.
    """
    device = sched.device_budget_bytes
    wanted = (max(0, int(limit_bytes) - int(static_bytes or 0))
              if limit_bytes is not None and int(limit_bytes) > 0 else device)
    effective = wanted if device is None or wanted is None else min(wanted, device)
    previous = sched.kv_budget_bytes
    if (sched._active and effective is not None
            and (previous is None or effective < previous)):
        # A stats sample can lag both parked allocations and future growth.
        # Refuse in the worker's event loop, before changing any limits.
        return {"error": "模型仍有运行中的请求，不能调低内存额度；请等请求结束后重试"}
    if limit_bytes is None or int(limit_bytes) <= 0:
        sched.model_budget_bytes = None
        sched.model_static_bytes = None
        sched.kv_budget_bytes = device
        _trim_cache_to(sched)
        return {"mem_limit_bytes": None, "mem_static_bytes": static_bytes,
                "mem_runtime_budget_bytes": None, "kv_budget_bytes": sched.kv_budget_bytes}
    static = int(static_bytes or 0)
    from ..core import mem_limit as mem_mod

    wanted = mem_mod.runtime_budget_bytes(int(limit_bytes), static)
    sched.model_budget_bytes = wanted
    sched.model_static_bytes = static
    sched.kv_budget_bytes = wanted if device is None else min(wanted, device)
    _trim_cache_to(sched)
    return {"mem_limit_bytes": int(limit_bytes), "mem_static_bytes": static,
            "mem_runtime_budget_bytes": wanted,
            "kv_budget_bytes": sched.kv_budget_bytes}


def _trim_cache_to(sched: Scheduler) -> None:
    """Make the prefix cache's ceiling exactly the scheduler's budget, at once.

    The cache's own ceiling *is* the budget now (MYS-2785): sessions and the
    cache share it, and the cache is the elastic side. Assigning here rather than
    leaving it to the next ``configure`` keeps ``stats`` from reporting a ceiling
    the model cannot afford, and it is what makes a limit change visible
    immediately in both directions -- a raised limit must hand the cache its room
    back, which a shrink-only rule would never do.
    """
    budget = sched.kv_budget_bytes
    cache = sched.prefix_cache
    if budget is None or cache.max_bytes is None:
        return
    cache.set_limits(max_bytes=int(budget))


def configure(sched: Scheduler, backend, msg: dict) -> dict:
    """Apply console settings to a running worker; returns what took effect."""
    limit_applied = None
    if msg.get("mem_limit_mb") is not None:
        # Keep the measured footprint byte-exact. Truncating it to MiB grants
        # extra runtime memory and makes recovery mistake an applied budget for
        # a third value. Older clients may still send the MiB field.
        static = msg.get("mem_static_bytes")
        if static is None:
            static = int(msg.get("mem_static_mb") or 0) << 20
        limit_applied = apply_mem_limit(
            sched, backend, int(msg["mem_limit_mb"]) << 20,
            int(static))
        if "error" in limit_applied:
            return limit_applied
    if msg.get("max_concurrent") is not None:
        sched.max_concurrent = max(1, min(MAX_CONCURRENCY, int(msg["max_concurrent"])))
    if msg.get("max_queue") is not None:
        sched.max_queue = max(0, int(msg["max_queue"]))
    if msg.get("exact_tail") is not None:
        sched.exact_tail = max(0, int(msg["exact_tail"]))
    if msg.get("decode_quantum") is not None:
        # The setter clamps and only takes effect from the next slice, so a
        # reconfiguration never disturbs a request that is mid-generation.
        sched.decode_quantum = msg["decode_quantum"]
    # The prefix cache's byte ceiling **is** this model's runtime budget
    # (MYS-2785). There is no service-wide number to start from any more, and no
    # per-worker "configured bytes" either: the budget is `limit - static`
    # trimmed by what the device can spare, and the cache may use all of it when
    # no session wants it -- sessions keep priority through
    # ``Scheduler._fits`` / ``_cache_room_for``, which evict the cache to make
    # room.
    #
    # Then the two **operator instructions**, which are not fallbacks and must
    # beat the inferred budget:
    #
    #   * ``--no-prefix-cache`` / ``--device-kv-budget-mb 0``: switch the cache
    #     off. It has to win even when a device reading exists -- the first
    #     attempt at this change put the CLI value *below* the budget in the
    #     precedence order, so a harness that asked for no cache got the device's
    #     8000 MiB instead. "Off" is a decision; a bm-smi reading is a guess.
    #   * a non-zero ``--device-kv-budget-mb``: a cap on top of the budget, never
    #     a way around it (``min``), so it cannot make the cache exceed the model.
    cap = sched.kv_budget_bytes
    if cap is None:
        cap = npu_cache_cap(backend, sched.max_concurrent)
    cli_cap = sched.cache_cli_cap_bytes
    if cli_cap is not None:
        cap = cli_cap if cap is None else min(cli_cap, cap)
    ttl = msg.get("cache_ttl_min")
    sched.prefix_cache.set_limits(
        max_entries=msg.get("cache_entries"),
        max_bytes=cap,
        ttl_s=None if ttl is None else float(ttl) * 60,
    )
    return {"max_concurrent": sched.max_concurrent, "max_queue": sched.max_queue,
            "cache_max_bytes": sched.prefix_cache.max_bytes, "cache_npu_cap_bytes": cap,
            "kv_budget_bytes": sched.kv_budget_bytes,
            "mem_runtime_budget_bytes": sched.model_budget_bytes,
            "device_budget_bytes": sched.device_budget_bytes,
            "exact_tail": sched.exact_tail,
            "decode_quantum": sched.decode_quantum,
            "cache_ttl_s": sched.prefix_cache.ttl_s,
            "cache_entries": sched.prefix_cache.max_entries,
            **(limit_applied or {})}


async def _serve_aux(args, backend) -> int:
    """Serve an embedding/rerank worker: no scheduler, no cache, no sessions.

    Deliberately a separate function rather than a branch inside ``amain``'s
    body: an auxiliary worker skipping half of the chat setup is easier to read
    than one that builds a Scheduler it will never use, and the shutdown order
    differs too (there is nothing to drain, only the engine handle to free).
    """
    # Whether the engine is usable is answered by the banner below, exactly as
    # for a chat worker: the manager treats the first answered health probe as
    # "loaded", so the socket must not open before the weights are on the NPU.
    ready = asyncio.Event()
    ready.set()

    server = await asyncio.start_server(
        lambda r, w: serve(r, w, None, backend, args.model_id, ready),
        host="127.0.0.1", port=args.port,
        # A rerank request carries up to 256 documents, and a transcribe request
        # carries a whole audio file; both need the same generous bound, and ASR
        # needs more than the chat path's because 50 MiB of upload is 66.7 MiB of
        # base64 in one line (see stream_limit_for).
        limit=stream_limit_for(getattr(backend, "kind", "aux")),
    )
    logger.info("%s worker for %s listening on 127.0.0.1:%d",
                getattr(backend, "kind", "aux"), args.model_id, args.port)
    print(json.dumps({"event": "ready", "port": args.port,
                      "model": args.model_id, "kind": getattr(backend, "kind", "aux")}),
          flush=True)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    async with server:
        await stop.wait()

    logger.info("worker shutting down")
    await backend.close()
    logger.info("worker stopped cleanly")
    return 0


async def amain(args) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    backend = build_backend(
        args.backend, args.model_id, args.model_path, args.config_path, args.dev_id,
        context_length=args.context_length,
        decode_delay_ms=args.decode_delay_ms,
        min_tokens=args.mock_min_tokens,
        snapshot_location=args.snapshot_location,
        tokenizer_path=getattr(args, "tokenizer_path", None),
        lib_path=getattr(args, "native_lib", None),
        model_kind=getattr(args, "kind", "chat"),
        max_queue=args.max_queue,
    )

    if getattr(args, "kind", "chat") in AUX_KINDS:
        return await _serve_aux(args, backend)
    if getattr(args, "kind", "chat") not in GENERATE_KINDS:
        raise SystemExit(f"--kind {args.kind} has no worker path")

    store = getattr(backend, "snapshot_store", None)
    sched = Scheduler(
        backend,
        prefix_cache=PrefixCache(max_entries=args.cache_entries, store=store,
                                 ttl_s=args.cache_ttl_min * 60),
        max_concurrent=max(1, min(MAX_CONCURRENCY, args.max_concurrent)),
        max_queue=args.max_queue,
        decode_quantum=args.decode_quantum,
    )
    sched.exact_tail = max(0, args.exact_tail)
    if args.decode_quantum != sched.decode_quantum:
        logger.warning("decode quantum %d out of range, using %d",
                       args.decode_quantum, sched.decode_quantum)
    logger.info("decode quantum: %d token(s) per request per round-robin visit",
                sched.decode_quantum)
    sched.kv_budget_bytes = npu_kv_budget(backend)
    sched.device_budget_bytes = sched.kv_budget_bytes
    # Only a fallback now: the effective ceiling is the model's own budget (see
    # ``configure``), and this figure is consulted just when neither that nor the
    # device reading exists. ``0`` still means "cache off", which is what
    # ``tools/decode_quantum_*.py`` rely on.
    # The operator's cache instruction, recorded before ``configure`` reads it.
    # ``--no-prefix-cache`` is the explicit spelling; ``--device-kv-budget-mb 0``
    # is the one the A/B harnesses already use and keeps meaning "off" (it used
    # to mean that by accident, through a precedence bug -- see ``configure``).
    if args.no_prefix_cache:
        sched.cache_cli_cap_bytes = 0
    elif args.device_kv_budget_mb is not None:
        sched.cache_cli_cap_bytes = max(0, int(args.device_kv_budget_mb)) << 20
    if sched.kv_budget_bytes is not None:
        logger.info("NPU budget for parked sessions + prefix cache: %d MiB "
                    "(%d KiB per token of context)", sched.kv_budget_bytes >> 20,
                    backend.kv_bytes_per_token >> 10)
    # The per-model ceiling (MYS-2675), when the manager set one. Applied after
    # the device reading so the ``min`` inside ``apply_mem_limit`` has both
    # numbers; a model with no limit is untouched.
    applied_limit = apply_mem_limit(sched, backend, args.mem_limit_mb and
                                    args.mem_limit_mb * 1024 * 1024,
                                    args.mem_static_bytes if args.mem_static_bytes is not None
                                    else args.mem_static_mb * 1024 * 1024)
    if applied_limit["mem_limit_bytes"]:
        logger.info("memory limit for this model: %d MiB (static %d MiB), "
                    "sessions + prefix cache budget %d MiB",
                    applied_limit["mem_limit_bytes"] >> 20,
                    (applied_limit["mem_static_bytes"] or 0) >> 20,
                    (applied_limit["kv_budget_bytes"] or 0) >> 20)
    # The cache's ceiling is the budget the two lines above settled on -- this
    # model's ``limit - static``, or the device reading when no limit is
    # configured (MYS-2785). Nothing global enters into it. Called for every
    # generate worker, not only those with a snapshot store: a backend without
    # one still runs a PrefixCache (the mock does), and letting it keep the
    # constructor's host-RAM heuristic would be a second, silent ceiling.
    applied = configure(sched, backend, {"cache_ttl_min": args.cache_ttl_min,
                                        "cache_entries": args.cache_entries})
    logger.info("prefix cache ceiling: %s (model budget %s, device budget %s), "
                "ttl %.0f s, %d entries",
                "n/a" if applied["cache_max_bytes"] is None
                else f"{applied['cache_max_bytes'] >> 20} MiB",
                "none" if applied["mem_runtime_budget_bytes"] is None
                else f"{applied['mem_runtime_budget_bytes'] >> 20} MiB",
                "n/a" if applied["device_budget_bytes"] is None
                else f"{applied['device_budget_bytes'] >> 20} MiB",
                applied["cache_ttl_s"], applied["cache_entries"])
    await sched.start()
    # The manager treats the first answered health probe as "loaded", so the
    # vision import (GIL-heavy) has to finish before the socket opens.
    if hasattr(backend, "wait_warm"):
        await asyncio.to_thread(backend.wait_warm)

    # Set before ``start_server`` and before the banner, so every health reply
    # this process can ever answer already means "the engine is up".
    ready = asyncio.Event()
    ready.set()

    server = await asyncio.start_server(
        lambda r, w: serve(r, w, sched, backend, args.model_id, ready),
        host="127.0.0.1", port=args.port,
        # One request is one JSON line, and base64 images make it large: the
        # 64 KiB default rejects any real photo.
        limit=STREAM_LIMIT,
    )
    logger.info("worker for %s listening on 127.0.0.1:%d", args.model_id, args.port)
    # Tell the parent we are ready only after weights are in the NPU heap, so
    # the UI never shows a model as loaded before it can serve.
    print(json.dumps({"event": "ready", "port": args.port, "model": args.model_id}), flush=True)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    async with server:
        await stop.wait()

    logger.info("worker shutting down")
    # Order matters: sessions first (each close waits for its in-flight NPU
    # call), then the cached snapshots, then the engine. Freeing the engine
    # while a snapshot or a launch still refers to it is how a teardown leaves
    # the TPU busy for the next process.
    await sched.stop()
    sched.prefix_cache.clear()
    await backend.close()
    logger.info("worker stopped cleanly")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model-id", required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--backend", default="mock", choices=["mock", "sail", "native"])
    p.add_argument("--kind", default="chat", choices=list(KINDS),
                   help="what this model can do; part of the worker's identity, "
                        "since the manager's adoption matches on the command line")
    p.add_argument("--model-path", default="")
    p.add_argument("--config-path", default="")
    p.add_argument("--dev-id", type=int, default=0)
    p.add_argument("--max-concurrent", type=int, default=MAX_CONCURRENCY)
    p.add_argument("--max-queue", type=int, default=16)
    p.add_argument("--exact-tail", type=int, default=64,
                   help="prefill the last N tokens of long prompts through the decode graphs")
    p.add_argument("--decode-quantum", type=int, default=DEFAULT_DECODE_QUANTUM,
                   help="tokens one request decodes before the scheduler rotates to the "
                        f"next session (1-{MAX_DECODE_QUANTUM}, default "
                        f"{DEFAULT_DECODE_QUANTUM}); 1 restores per-token round-robin")
    p.add_argument("--cache-ttl-min", type=float, default=120,
                   help="drop prefix-cache entries unused for this long (0 = never)")
    p.add_argument("--context-length", type=int, default=2048,
                   help="mock backend only; the sail backend reads it from the bmodel")
    p.add_argument("--decode-delay-ms", type=float, default=0.0,
                   help="mock backend only: artificial per-token delay, for tests")
    p.add_argument("--cache-entries", type=int, default=32,
                   help="prefix cache slots")
    p.add_argument("--tokenizer-path", default=None,
                   help="tokenizer.json for the native backend")
    p.add_argument("--native-lib", default=None,
                   help="libcv84x6_llm.so path for the native backend")
    p.add_argument("--snapshot-location", default="device",
                   choices=["device", "host", "tiered"],
                   help="where prefix-cache KV lives: NPU memory (default), "
                        "system RAM, or device-first with host fallback")
    p.add_argument("--no-prefix-cache", action="store_true",
                   help="switch the prefix cache off for this worker, whatever "
                        "budget the model or the device would allow. The explicit "
                        "form of --device-kv-budget-mb 0, for A/B runs that must "
                        "not inherit a snapshot from an earlier run")
    p.add_argument("--device-kv-budget-mb", type=int, default=None,
                   help="deprecated (MYS-2785): the ceiling is the model's own "
                        "runtime budget. Still honoured as an operator cap: 0 "
                        "means 'cache off' (same as --no-prefix-cache), a "
                        "non-zero value lowers the ceiling and never raises it")
    p.add_argument("--mem-limit-mb", type=int, default=0,
                   help="this model's device-memory ceiling in MiB (MYS-2675); "
                        "0/absent = no per-model limit, budget from the device "
                        "reading alone")
    p.add_argument("--mem-static-mb", type=int, default=0,
                   help="the model's measured static device footprint in MiB, so "
                        "the worker can compute limit - static without parsing "
                        "the bmodel a second time")
    p.add_argument("--mem-static-bytes", type=int, default=None,
                   help="exact static footprint in bytes; overrides --mem-static-mb")
    p.add_argument("--mock-min-tokens", type=int, default=24,
                   help="mock backend only: tokens before the stop token may appear; "
                        "set very high to make a request end only via cancel/length")
    p.add_argument("--debug", action="store_true")
    return asyncio.run(amain(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
