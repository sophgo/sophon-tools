"""OpenAI-compatible surface: /v1/chat/completions, /v1/models, /v1/embeddings stub."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import re
import struct
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from ..core.auth import require_api_key
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
from ..schemas import (
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    EmbeddingRequest,
    ModelCard,
    ModelList,
    OcrBlock,
    OcrLine,
    OcrRegionLine,
    OcrResponse,
    OcrUsage,
    RerankRequest,
    Usage,
)
from .tool_calls import (
    CompletionStream,
    ParsedCompletion,
    RawStream,
    IMAGE_PLACEHOLDER,
    flatten_content,
    parse_completion,
    render_messages,
    select_tools,
    validate_tools,
)

logger = logging.getLogger(__name__)

router = APIRouter()

#: Routes that must also answer *outside* ``/v1``. Cohere's and Jina's own
#: clients call ``POST /rerank``, and several RAG frameworks strip the version
#: prefix when a user configures a base URL without it. Mounted at the root in
#: app/main.py; the handlers are the same objects, so the two paths cannot drift.
alias_router = APIRouter()

MAX_STOP_STRINGS = 16

#: OpenAI's own limit for one embeddings request; over it is a 400, not a slow
#: request. Every text is a separate forward on the single NPU.
MAX_EMBED_INPUTS = 64

#: The rerank endpoints' limit. 256 pairs is what Cohere/Jina clients batch by
#: default, and each pair is a full SEQLEN-shaped forward here.
MAX_RERANK_DOCUMENTS = 256

#: Qwen3-Embedding's MRL range: below 32 the model was never trained to be
#: truncated that far, and above the hidden size truncation is a no-op.
MIN_EMBED_DIMENSIONS = 32


def _flatten_content(content) -> tuple[str, list[str]]:
    """flatten_content, with render failures reported as client errors."""
    try:
        return flatten_content(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def build_prompt(messages: list[ChatMessage],
                 enable_thinking: bool = False,
                 tools: list[dict] | None = None) -> tuple[str, list[str]]:
    """Render messages in the model's chat format (config/chat_template.jinja).

    Applied here rather than in the worker so the worker stays a pure
    tokenizer/inference box. The generation prompt matches the template: with
    thinking off (the default, as in the vendor demo) the assistant turn
    starts with an empty think block.
    """
    return render_messages(messages, tools=tools, enable_thinking=enable_thinking,
                           flatten=_flatten_content)


def _thinking(req: ChatCompletionRequest) -> bool:
    """Thinking is opt-in, via enable_thinking or chat_template_kwargs (vLLM style)."""
    if req.enable_thinking is not None:
        return bool(req.enable_thinking)
    return bool((req.chat_template_kwargs or {}).get("enable_thinking", False))


def _stop_list(stop) -> list[str]:
    if stop is None:
        return []
    return [stop] if isinstance(stop, str) else list(stop)


async def _resolve_model(request: Request, model_name: str, *,
                         expect: str | tuple[str, ...] = "chat"):
    """Map a requested model name to a *ready* worker and its RPC client.

    The admission gate for every inference route -- OpenAI and console alike.
    ``ModelManager.require_ready`` is the one place that decides, so the two
    surfaces cannot disagree: not loaded, mid-load, mid-unload and
    worker-exited all become 409 here, before a record is created and before
    anything reaches a worker (MYS-2496).

    ``expect`` is the kind this route serves -- a tuple where a route serves
    more than one (``/v1/chat/completions`` takes ``chat`` and ``ocr_vl``, which
    differ in what they are *for*, not in how they are called). A mismatch is a
    400 naming the route that *would* work, not a 404: the model exists and is
    loaded, the caller just called the wrong endpoint, and "not found" would
    send them looking for a missing download.

    An **auxiliary** model that is on disk but not loaded is loaded here rather
    than refused, unless the operator turned ``aux_auto_load`` off
    (docs/aux-models.md § 空闲自动卸载). The refusal codes are unchanged for
    everything else -- including a load that fails, which surfaces as the same
    409 the console's own Load button produces, because from the caller's side it
    is the same fact ("this model cannot be brought up right now").

    Every successful resolution records a use (``ModelManager.touch``), which is
    what the idle sweep measures. It happens *before* the client is handed back,
    so the model cannot be unloaded between the resolution and the request.
    """
    from ..core.models import ModelBusy, ModelNotLoaded, ModelUnavailable

    wanted = (expect,) if isinstance(expect, str) else tuple(expect)
    # The refusal names one route; with two accepted kinds the first is the one
    # the message is about (chat), and the model's own kind decides the rest.
    wanted_label = wanted[0]
    mgr = request.app.state.models
    # The kind is checked *before* any load. A request for an unloaded chat
    # model on /v1/embeddings must not spend a minute bringing a 35B up only to
    # answer 400 -- and the answer is the same either way, because the kind comes
    # from the bmodel's file name and does not change when the model loads.
    existing = mgr.get(model_name)
    if existing is not None and existing.kind not in wanted:
        raise HTTPException(status_code=400, detail=kind_mismatch_message(
            existing.model_id, existing.kind, wanted_label))
    try:
        info = await mgr.require_ready_or_load(model_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"model {model_name!r} not found")
    except ModelBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ModelNotLoaded as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ModelUnavailable as exc:
        # 503: it was serving, its worker died, and a reload fixes it. The code
        # this path produced before the readiness rework, kept deliberately.
        raise HTTPException(status_code=503, detail=str(exc))
    except RuntimeError as exc:
        # The on-demand load failed: NPU out of memory, a worker that never
        # became ready, a download still in flight. 409 with the load's own
        # message, which is what POST /api/models/{id}/load returns for the same
        # failure.
        raise HTTPException(status_code=409, detail=str(exc))
    mgr.touch(info.model_id)
    if info.kind not in wanted:
        raise HTTPException(status_code=400, detail=kind_mismatch_message(
            info.model_id, info.kind, wanted_label))
    client: WorkerClient | None = request.app.state.clients.get(model_name)
    if client is None:
        # `loaded` implies the client exists (on_loaded registers it inside the
        # load, before the flag is observable), so this is a bookkeeping bug --
        # but it must not become a 500 pointing at the worker.
        raise HTTPException(
            status_code=409,
            detail=f"model {model_name!r} has no worker client yet; reload it from the web console",
        )
    return info, client


#: How each kind is described in a refusal, and where it *is* served.
_KIND_ROUTE = {
    "chat": "/v1/chat/completions",
    "embedding": "/v1/embeddings",
    "rerank": "/v1/rerank",
    "asr": "/v1/audio/transcriptions",
    "ocr": "/v1/ocr",
    # ocr_vl answers the chat surface too; the entry exists so the refusal for
    # "you asked an OCR-VL model for embeddings" points at the right place.
    "ocr_vl": "/v1/chat/completions",
}

#: The kinds /v1/chat/completions serves. ``ocr_vl`` is a chat-*shaped* model --
#: same request, same stream, same usage -- and that is the whole point of the
#: interface (the official PaddleOCR client is an OpenAI client), but it is not
#: a general conversation model, so it is a separate kind everywhere the service
#: has to choose: agents, the knowledge base, and the default model.
CHAT_KINDS = ("chat", "ocr_vl")


def kind_mismatch_message(model_id: str, actual: str, wanted: str) -> str:
    """The 400 body for "right model, wrong endpoint", in the caller's terms."""
    return (f"{model_id} 是 {actual} 模型，请调用 {_KIND_ROUTE.get(actual, actual)}"
            f"（当前接口只服务 {wanted} 模型）")


def _require_kind(info, wanted: str | tuple[str, ...]) -> None:
    """Refuse a model whose kind is not ``wanted`` (same 400 as the gate)."""
    accepted = (wanted,) if isinstance(wanted, str) else tuple(wanted)
    if info.kind not in accepted:
        raise HTTPException(status_code=400, detail=kind_mismatch_message(
            info.model_id, info.kind, accepted[0]))


@router.get("/models", response_model=ModelList)
async def list_models(request: Request, _: str = Depends(require_api_key)):
    """Only models that can serve *right now*.

    A model that is loading, unloading or whose load failed is deliberately
    absent: an OpenAI client discovers models here and then sends requests to
    one, so listing a model mid-load invites exactly the request this service
    is supposed to refuse. The console's ``/api/models`` is where the full
    state (``loaded``/``operation``/``load_error``) belongs.

    ``kind`` is what tells the client which endpoint to call: an embedding model
    listed without it would look like a chat model that answers 400.
    """
    mgr = request.app.state.models
    now = int(time.time())
    return ModelList(
        data=[
            ModelCard(id=m.model_id, created=now, kind=m.kind)
            for m in mgr.list()
            if m.loaded and m.operation is None and mgr.still_loaded(m)
        ]
    )


@router.get("/models/{model_id}")
async def get_model(model_id: str, request: Request, _: str = Depends(require_api_key)):
    mgr = request.app.state.models
    info = mgr.get(model_id)
    if info is None or not info.loaded or info.operation is not None:
        raise HTTPException(status_code=404, detail="model not found")
    return ModelCard(id=info.model_id, created=int(info.loaded_at or time.time()),
                     kind=info.kind)


def _params_from(req: ChatCompletionRequest) -> dict:
    """The sampling parameters as they will actually be applied.

    Defaults are resolved here rather than in the worker so the record states
    what the model really ran with -- "temperature 0.8 because none was sent" is
    a different story from "0.8 because the client asked for it".
    """
    return {
        # ``max_completion_tokens`` wins when both are sent: it is the field the
        # newer clients use, and OpenAI treats the two as the same limit.
        "max_tokens": req.max_completion_tokens or req.max_tokens or 512,
        "temperature": req.temperature if req.temperature is not None else 0.8,
        "top_p": req.top_p if req.top_p is not None else 0.8,
        "top_k": req.top_k or 50,
        "repetition_penalty": req.repetition_penalty or 1.1,
        "stop": _stop_list(req.stop),
        "seed": req.seed,
    }


@router.post("/chat/completions")
async def chat_completions(req: ChatCompletionRequest, request: Request, key_id: str = Depends(require_api_key)):
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")
    if req.n != 1:
        raise HTTPException(status_code=400, detail="only n=1 is supported")
    for field in ("max_tokens", "max_completion_tokens"):
        value = getattr(req, field)
        if value is not None and value < 1:
            raise HTTPException(status_code=400, detail=f"{field} must be at least 1")
    if len(_stop_list(req.stop)) > MAX_STOP_STRINGS:
        raise HTTPException(status_code=400,
                            detail=f"at most {MAX_STOP_STRINGS} stop strings are supported")
    try:
        tools = validate_tools(req.tools)
        offered = select_tools(tools, req.tool_choice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    info, client = await _resolve_model(request, req.model, expect=CHAT_KINDS)
    thinking = _thinking(req)
    ocr_vl = info.kind == "ocr_vl"
    if ocr_vl:
        # Function calling is a Qwen chat-template feature: PaddleOCR-VL's
        # template has no tools block, so accepting ``tools`` would render a
        # prompt that silently omits them. Refused the same way an embedding
        # model refuses a chat request -- a 400 that says what is wrong.
        if tools:
            raise HTTPException(
                status_code=400,
                detail=f"model {req.model!r} 是 OCR-VL 模型，不支持 tools；"
                       "它只按提示识别图片内容")
        prompt, images = _ocr_vl_prompt(req.messages)
    else:
        prompt, images = build_prompt(req.messages, enable_thinking=thinking,
                                      tools=offered)
    if images and not info.supports_vision:
        raise HTTPException(status_code=400, detail=f"model {req.model!r} does not accept images")
    if ocr_vl:
        # One image per request, stated before anything reaches the worker: a
        # second page would be scored against the prefill graph's fixed
        # single-image stage. The official pipeline already calls once per
        # element, so a caller sending two is a caller that mis-assembled it.
        if len(images) > 1:
            raise HTTPException(
                status_code=400,
                detail=f"这个模型一次只接受一张图片，收到 {len(images)} 张；"
                       "请把多页/多元素拆成多次请求")
        if not images:
            raise HTTPException(
                status_code=400,
                detail="这个模型需要一张图片：请在 user 消息里放一个 "
                       '{"type":"image_url"} 内容块')

    params = _params_from(req)
    req_id = uuid.uuid4().hex
    store = request.app.state.store
    key = next((k for k in store.keys if k.id == key_id), None) if key_id else None
    # The request is now a real inference: model resolved, prompt rendered, no
    # validation left that could refuse it. Everything above this line is a 4xx
    # that never reached the NPU and therefore never gets a record.
    ctx = build_context(
        request.app.state.inference_log,
        req_id=req_id,
        source=request.url.path,
        model=info.model_id,
        actor=actor_from_key_id(store, key_id),
        # enable_thinking is not a worker parameter (the template already
        # rendered the think block) but it is the single most useful thing to
        # know when reading a record back, so it belongs with the sampling
        # parameters. A copy: `params` goes to the worker as-is.
        params={**params, "enable_thinking": thinking},
        tools=tools,
        tool_choice=req.tool_choice,
        messages=req.messages,
        prompt=prompt,
    )

    if req.stream:
        return StreamingResponse(
            _stream(client, req, req_id, prompt, images, params, store, key,
                    thinking=thinking, tools=tools, ctx=ctx, info=info),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    text_parts: list[str] = []
    meta: dict = {}
    done: dict = {}

    async def collect() -> None:
        nonlocal meta, done
        async for evt in client.generate(req_id, prompt, params, images or None):
            if evt["op"] == "meta":
                meta = evt
            elif evt["op"] == "delta":
                text_parts.append(evt["text"])
            elif evt["op"] == "done":
                done = evt

    try:
        # A non-streaming client that gives up (timeout, Ctrl-C) must not keep
        # the NPU busy: a 128k-token prefill runs for over an hour. Poll for
        # the disconnect and cancel the request in the worker.
        job = asyncio.create_task(collect())
        while True:
            finished, _ = await asyncio.wait({job}, timeout=1.0)
            if finished:
                job.result()
                break
            if await request.is_disconnected():
                await client.cancel(req_id)
                job.cancel()
                raise HTTPException(status_code=499, detail="client disconnected")
    except WorkerError as exc:
        # A worker refusal is a finished inference attempt: it gets one record
        # saying what the model was asked and why it produced nothing.
        if ctx is not None:
            ctx.finish(status=STATUS_ERROR, error=exc,
                       output_text="".join(text_parts), raw_output="".join(text_parts),
                       prompt_tokens=meta.get("prompt_tokens"),
                       cached_tokens=meta.get("cached_tokens"))
        if exc.kind == "invalid_request":
            # The request cannot be served as sent (too long, bad image).
            raise HTTPException(status_code=400, detail=str(exc))
        if exc.kind == "busy":
            # All slots taken and the queue is full: retry later.
            raise HTTPException(status_code=429, detail=str(exc),
                                headers={"Retry-After": "5"})
        # 503: the model backend is unavailable, which is retryable once the
        # operator reloads it -- not a 500 implying a bug in this service.
        raise HTTPException(status_code=503, detail=str(exc))
    except HTTPException as exc:
        # 499: this handler hung up on the worker (see the poll above).
        if ctx is not None and exc.status_code == 499:
            etype, emsg = cancellation_error("non-streaming generation")
            ctx.finish(status=STATUS_CANCELLED, error_type=etype, error_message=emsg,
                       output_text="".join(text_parts),
                       prompt_tokens=meta.get("prompt_tokens"),
                       cached_tokens=meta.get("cached_tokens"))
        raise
    except (ConnectionError, OSError) as exc:
        # The worker died mid-generation; the text collected so far is exactly
        # what the client will not receive, and exactly what a debugger needs.
        if ctx is not None:
            ctx.finish(status=STATUS_ERROR, error=exc, output_text="".join(text_parts),
                       prompt_tokens=meta.get("prompt_tokens"),
                       cached_tokens=meta.get("cached_tokens"))
        raise

    raw_text = "".join(text_parts)
    text, finish_reason = _apply_stop_strings(raw_text, done.get("finish_reason", "stop"), params["stop"])
    parsed = _parse_answer(text, info, thinking, tools, finish_reason)

    pt = done.get("prompt_tokens", meta.get("prompt_tokens", 0))
    ct = done.get("completion_tokens", len(text_parts))
    cached = done.get("cached_tokens", meta.get("cached_tokens", 0))
    store.record_usage(key, pt, ct, cached_tokens=cached, decode_tps=done.get("decode_tps"))
    if ctx is not None:
        ctx.finish(
            status=STATUS_OK,
            finish_reason=parsed.finish_reason,
            output_text=text,
            raw_output=raw_text,
            response_content=parsed.content,
            reasoning_content=parsed.reasoning_content,
            tool_calls=parsed.tool_calls or None,
            prompt_tokens=pt,
            completion_tokens=ct,
            cached_tokens=cached,
            first_token_latency_s=done.get("first_token_latency_s"),
            decode_tps=done.get("decode_tps"),
            stop_hit=_stop_hit(raw_text, text, params["stop"]),
        )

    message = ChatMessage(role="assistant", content=parsed.content)
    message.reasoning_content = parsed.reasoning_content
    message.tool_calls = parsed.tool_calls or None
    return ChatCompletionResponse(
        id=f"chatcmpl-{req_id}",
        created=int(time.time()),
        model=req.model,
        choices=[ChatChoice(message=message, finish_reason=parsed.finish_reason)],
        usage=Usage(
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=pt + ct,
            prompt_tokens_details={"cached_tokens": cached} if cached else None,
        ),
    )


def _ocr_vl_prompt(messages: list[ChatMessage]) -> tuple[str, list[str]]:
    """The OCR-VL prompt, rendered with the model's own template.

    Kept here rather than in the worker for the same reason the Qwen prompt is:
    the worker stays a tokenizer/inference box, and a prompt rendered by the
    API is what the inference record shows. The template is
    ``model-config/paddleocr_vl_1_5/chat_template.jinja``; the rendering lives in
    ``app/engine/paddle_vl.py`` next to the engine that consumes it, and
    ``tests/test_ocr_vl_prompt.py`` compares it with jinja2's rendering of that
    file byte for byte.
    """
    from ..engine.paddle_vl import render_prompt

    try:
        return render_prompt(messages)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _parse_answer(text: str, info, thinking: bool,
                  tools: list[dict] | None, finish_reason: str):
    """The assistant message for ``text``, in the shape this model produces.

    Two shapes, and the difference matters:

    * a **chat** model answers in Qwen's format -- an optional think block and
      ``<tool_call>`` blocks, which are protocol rather than answer text, so they
      are parsed out here;
    * an **ocr_vl** model answers in OTSL: ``<fcel>``, ``<nl>``, ``<lcel>`` and
      friends are the *content*, and splitting the text on markers that belong
      to another model's protocol would corrupt it. It gets no thinking block
      and no tool parsing; the text is the answer, verbatim, including its
      leading and trailing whitespace (a Markdown table's newlines included).
    """
    if getattr(info, "kind", "chat") == "ocr_vl":
        return ParsedCompletion(content=text, finish_reason=finish_reason)
    return parse_completion(text, thinking=thinking, tools=tools,
                            finish_reason=finish_reason)


def _apply_stop_strings(text: str, finish_reason: str, stops: list[str]) -> tuple[str, str]:
    """Truncate at the first stop string, matching OpenAI's behaviour."""
    earliest = -1
    for s in stops:
        if not s:
            continue
        idx = text.find(s)
        if idx != -1 and (earliest == -1 or idx < earliest):
            earliest = idx
    if earliest != -1:
        return text[:earliest], "stop"
    return text, finish_reason


async def _stream(client, req, req_id, prompt, images, params, store, key,
                  thinking: bool = False, tools: list[dict] | None = None,
                  ctx: RecordContext | None = None, info=None):
    """SSE stream. Cancellation must reach the worker, or the NPU keeps decoding."""
    created = int(time.time())
    cid = f"chatcmpl-{req_id}"
    pt = ct = cached = 0
    tps = None
    ftl = None
    finish_reason = "stop"
    # What the model actually emitted, and the part of it the client is allowed
    # to see (stop string removed). Both are needed by the record: a generation
    # cut by a stop string and one that stopped on its own look identical
    # otherwise, and that difference is a common "why was the answer short?".
    raw_emitted = ""
    emitted = ""
    stopped_by: str | None = None
    recorded = False

    def record_ctx(**overrides) -> None:
        """Write the one record for this stream, whatever ended it."""
        nonlocal recorded
        if ctx is None or recorded:
            return
        recorded = True
        ctx.finish(
            prompt_tokens=pt, completion_tokens=ct, cached_tokens=cached,
            first_token_latency_s=ftl, decode_tps=tps, raw_output=raw_emitted, **overrides)

    def chunk(delta: dict, finish=None) -> str:
        payload = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": req.model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    try:
        yield chunk({"role": "assistant", "content": ""})
        # An OCR-VL answer is OTSL text, not a Qwen turn: it has no think block
        # and no <tool_call> protocol, so the splitter would hold back a tail it
        # mistook for a marker. ``raw`` passes text straight through.
        splitter = (RawStream() if getattr(info, "kind", "chat") == "ocr_vl"
                    else CompletionStream(thinking=thinking))
        stopped = False
        async for evt in client.generate(req_id, prompt, params, images or None):
            if evt["op"] == "meta":
                pt = evt.get("prompt_tokens", 0)
                cached = evt.get("cached_tokens", 0)
            elif evt["op"] == "delta":
                text = evt["text"]
                # Honour stop strings mid-stream: hold back text that might be
                # the start of a stop string, emit the rest, and stop cleanly.
                raw_candidate = raw_emitted + text
                candidate = emitted + text
                cut = _first_stop(candidate, params["stop"])
                accepted = candidate if cut is None else candidate[:cut]
                # Book-keeping first, yields second. A client that hangs up
                # right after receiving this chunk closes the generator at the
                # yield below; anything recorded after it would be lost, and the
                # lost delta is exactly the last thing the user saw.
                raw_emitted = raw_candidate
                pieces = splitter.feed(accepted[len(emitted):])
                emitted = accepted
                ct += 1
                if cut is not None:
                    stopped = True
                    stopped_by = _stop_at(candidate, cut, params["stop"])
                for name, piece in pieces:
                    yield chunk({name: piece})
                if stopped:
                    break
            elif evt["op"] == "done":
                pt = evt.get("prompt_tokens", pt)
                ct = evt.get("completion_tokens", ct)
                cached = evt.get("cached_tokens", cached)
                tps = evt.get("decode_tps")
                ftl = evt.get("first_token_latency_s")
                finish_reason = evt.get("finish_reason", "stop")
        for name, piece in splitter.finish():
            yield chunk({name: piece})
        parsed = _parse_answer(emitted, info, thinking, tools, finish_reason)
        # A tool call is protocol, not answer text: it is parsed from the whole
        # generation and sent as its own delta once decoding has finished.
        for i, call in enumerate(parsed.tool_calls):
            yield chunk({"tool_calls": [{
                "index": i, "id": call["id"], "type": "function",
                "function": call["function"],
            }]})
        if parsed.tool_calls:
            finish_reason = "tool_calls"
        elif stopped:
            finish_reason = "stop"
        yield chunk({}, finish=finish_reason)
        stop_usage = {
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": pt + ct,
        }
        if cached:
            stop_usage["prompt_tokens_details"] = {"cached_tokens": cached}
        yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': created, 'model': req.model, 'choices': [], 'usage': stop_usage})}\n\n"
        yield "data: [DONE]\n\n"
        store.record_usage(key, pt, ct, cached_tokens=cached, decode_tps=tps)
        record_ctx(status=STATUS_OK, finish_reason=finish_reason, output_text=emitted,
                   response_content=parsed.content,
                   reasoning_content=parsed.reasoning_content,
                   tool_calls=parsed.tool_calls or None, stop_hit=stopped_by)
    except (asyncio.CancelledError, GeneratorExit):
        # Client hung up: tell the worker to stop decoding this request.
        await client.cancel(req_id)
        # The partial answer is the evidence: half a sentence is often enough to
        # see which way a wrong answer was heading, and it is worthless if the
        # only row for the request says "cancelled" with no text.
        partial = _parse_answer(emitted, info, thinking, tools, "cancelled")
        etype, emsg = cancellation_error("streaming generation")
        record_ctx(status=STATUS_CANCELLED, finish_reason=None, output_text=emitted,
                   response_content=partial.content,
                   reasoning_content=partial.reasoning_content,
                   error_type=etype, error_message=emsg, stop_hit=stopped_by)
        raise
    except WorkerError as exc:
        etype = {"invalid_request": "invalid_request_error",
                 "busy": "rate_limit_error"}.get(exc.kind, "server_error")
        err = {"error": {"message": str(exc), "type": etype}}
        record_ctx(status=STATUS_ERROR, finish_reason=None, output_text=emitted,
                   error=exc, stop_hit=stopped_by)
        yield f"data: {json.dumps(err)}\n\n"
        yield "data: [DONE]\n\n"
    except (ConnectionError, OSError) as exc:
        # A backend dying mid-stream must still terminate the SSE cleanly, or the
        # client hangs waiting for a [DONE] that never comes.
        err = {"error": {"message": f"连接中断：{type(exc).__name__}", "type": "server_error"}}
        record_ctx(status=STATUS_ERROR, finish_reason=None, output_text=emitted,
                   error=exc, stop_hit=stopped_by)
        yield f"data: {json.dumps(err)}\n\n"
        yield "data: [DONE]\n\n"


def _stop_at(text: str, cut: int, stops: list[str]) -> str | None:
    """Which stop string produced the cut. Kept as evidence, not for control
    flow: with several configured stops, "which one fired" is the question."""
    for s in stops:
        if s and text.startswith(s, cut):
            return s
    return None


def _stop_hit(raw: str, final: str, stops: list[str]) -> str | None:
    """The stop string that truncated ``raw`` into ``final``, if any."""
    if final == raw:
        return None
    return _stop_at(raw, len(final), stops)


def _first_stop(text: str, stops: list[str]) -> int | None:
    best = None
    for s in stops:
        if not s:
            continue
        idx = text.find(s)
        if idx != -1 and (best is None or idx < best):
            best = idx
    return best


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------
def _coerce_embed_input(raw) -> list[str]:
    """OpenAI's ``input`` forms, reduced to the list of texts to embed.

    Every refusal is a 400 that says what to send instead. Token-id arrays are
    the interesting one: OpenAI accepts them, but this service tokenises
    server-side (the worker owns the model's tokenizer and never exposes it), so
    there is no honest way to serve pre-tokenised input -- and accepting it
    while quietly re-tokenising something else would be worse than saying no.
    """
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        if not raw:
            raise HTTPException(status_code=400, detail="input 不能是空数组")
        if len(raw) > MAX_EMBED_INPUTS:
            raise HTTPException(
                status_code=400,
                detail=f"一次最多 {MAX_EMBED_INPUTS} 条输入，收到 {len(raw)} 条")
        if all(isinstance(x, str) for x in raw):
            return list(raw)
        if all(isinstance(x, int) and not isinstance(x, bool) for x in raw) or \
                all(isinstance(x, list) for x in raw):
            raise HTTPException(
                status_code=400,
                detail="不支持预分词（token id）输入；请传入字符串或字符串数组，"
                       "由服务端使用模型自带的分词器编码")
        raise HTTPException(status_code=400, detail="input 必须是字符串或字符串数组")
    raise HTTPException(status_code=400, detail="input 必须是字符串或字符串数组")


def _encode_float32(vec: list[float]) -> str:
    """Little-endian float32, base64'd -- OpenAI's ``encoding_format: base64``."""
    return base64.b64encode(struct.pack(f"<{len(vec)}f", *vec)).decode("ascii")


@router.post("/embeddings")
async def embeddings(req: EmbeddingRequest, request: Request,
                     key_id: str = Depends(require_api_key)):
    """OpenAI-compatible ``POST /v1/embeddings``.

    One record per request (not per text), ``source`` = this path: a batch of 64
    texts is one inference as far as an operator is concerned, and 64 rows would
    bury the chat traffic it sits next to.
    """
    structured = isinstance(req.input, dict) or (
        isinstance(req.input, list) and any(isinstance(x, dict) for x in req.input))
    items = None
    if structured:
        from ..engine.vl_embed import validate_items

        try:
            items = validate_items(req.input if isinstance(req.input, list) else [req.input])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        texts = [item["text"] for item in items]
    else:
        texts = _coerce_embed_input(req.input)
    if not structured and any(not t for t in texts):
        raise HTTPException(status_code=400, detail="input 不能包含空字符串")
    instruction = req.instruction or ""

    info, client = await _resolve_model(request, req.model, expect="embedding")
    multimodal = bool(getattr(info, "supports_vision", False))
    if structured and not multimodal:
        raise HTTPException(status_code=400, detail="该模型只支持文本，请选择多模态 embedding 模型")
    # The hidden size is the ceiling for MRL truncation, and the worker is the
    # only one that knows it (it comes from the bmodel's graphs).
    hidden = int(getattr(info, "hidden_size", 0) or 0) or None
    if req.dimensions is not None:
        min_dimensions = 64 if multimodal else MIN_EMBED_DIMENSIONS
        if req.dimensions < min_dimensions:
            raise HTTPException(
                status_code=400,
                detail=f"dimensions 不能小于 {min_dimensions}")
        if hidden is not None and req.dimensions > hidden:
            raise HTTPException(
                status_code=400,
                detail=f"dimensions 不能大于模型的隐藏维度 {hidden}")
        if hidden is None:
            raise HTTPException(
                status_code=400,
                detail="该模型未报告隐藏维度，无法校验 dimensions；请不带 dimensions 调用")

    # The length limit is enforced by the worker, which owns the tokenizer.
    # Estimating it here from bytes would be wrong by ~5x for Chinese text
    # (2701 tokens for 13500 UTF-8 bytes) and would refuse inputs that fit; and
    # the worker refuses *before* running the graph rather than truncating, so
    # nothing silently embeds a prefix.

    req_id = uuid.uuid4().hex
    store = request.app.state.store
    key = next((k for k in store.keys if k.id == key_id), None) if key_id else None
    ctx = build_context(
        request.app.state.inference_log,
        req_id=req_id,
        source=request.url.path,
        model=info.model_id,
        actor=actor_from_key_id(store, key_id),
        params={"dimensions": req.dimensions,
                "encoding_format": req.encoding_format,
                **({"instruction": instruction} if instruction else {})},
        # The record's `messages` is the input itself, in the same shape the
        # chat path uses (one turn per text) so an operator reads it the same way.
        messages=[{"role": "user", "content": (
            ([{"type": "image_url", "image_url": {"url": item["image"]}}]
             if item.get("image") else []) + [{"type": "text", "text": item["text"]}])}
            for item in items] if items is not None else [
                {"role": "user", "content": text if multimodal else instruction + text}
                for text in texts],
    )

    try:
        if multimodal:
            reply = await client.embed_multimodal(
                req_id, items if items is not None else [{"text": t} for t in texts],
                req.dimensions, req.instruction)
        else:
            reply = await client.embed(
                req_id,
                [instruction + text for text in texts] if instruction else texts,
                req.dimensions,
            )
    except WorkerError as exc:
        if ctx is not None:
            ctx.finish(status=STATUS_ERROR, error=exc)
        raise _worker_error_to_http(exc)

    vectors = reply.get("vectors") or []
    counts = reply.get("tokens") or []
    if len(vectors) != len(texts):
        if ctx is not None:
            ctx.finish(status=STATUS_ERROR,
                       error_type="ProtocolError",
                       error_message=f"worker 返回 {len(vectors)} 个向量，请求了 {len(texts)} 条")
        raise HTTPException(status_code=503,
                            detail="worker 返回的向量数量与请求不一致；请重新加载该模型")

    dim = len(vectors[0]) if vectors else 0
    if req.encoding_format == "base64":
        data = [{"object": "embedding", "index": i, "embedding": _encode_float32(v)}
                for i, v in enumerate(vectors)]
    else:
        data = [{"object": "embedding", "index": i, "embedding": v}
                for i, v in enumerate(vectors)]

    total_tokens = sum(int(c) for c in counts)
    if ctx is not None:
        ctx.finish(status=STATUS_OK,
                   output_text=f"{len(vectors)} vectors x {dim} dims",
                   prompt_tokens=total_tokens,
                   completion_tokens=0)
    return {
        "object": "list",
        "data": data,
        "model": req.model,
        "usage": {"prompt_tokens": total_tokens, "total_tokens": total_tokens},
    }


# ---------------------------------------------------------------------------
# Rerank
# ---------------------------------------------------------------------------
def _coerce_documents(raw) -> list[str]:
    """Jina/Cohere ``documents``: bare strings, ``{"text": ...}``, or a mix."""
    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=400, detail="documents 必须是非空数组")
    if len(raw) > MAX_RERANK_DOCUMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"一次最多 {MAX_RERANK_DOCUMENTS} 条文档，收到 {len(raw)} 条")
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            out.append(item["text"])
        else:
            raise HTTPException(
                status_code=400,
                detail='documents 的每一项必须是字符串或 {"text": "..."} 对象')
    if any(not d for d in out):
        raise HTTPException(status_code=400, detail="documents 不能包含空字符串")
    return out


def _worker_error_to_http(exc: WorkerError) -> HTTPException:
    if exc.kind == "invalid_request":
        return HTTPException(status_code=400, detail=str(exc))
    if exc.kind == "busy":
        return HTTPException(status_code=429, detail=str(exc),
                             headers={"Retry-After": "5"})
    return HTTPException(status_code=503, detail=str(exc))


@router.post("/rerank")
async def rerank(req: RerankRequest, request: Request,
                 key_id: str = Depends(require_api_key)):
    """``POST /v1/rerank`` (Jina/Cohere shape; OpenAI has no rerank endpoint).

    Scores are ``sigmoid(logit)``, so they land in [0, 1] and sort the same way
    the logits do. The worker returns raw logits: the sigmoid is the API's
    presentation of them, and keeping it here means the record's stored numbers
    and the response's agree by construction.
    """
    from ..engine.aux_native import sigmoid

    if not req.query:
        raise HTTPException(status_code=400, detail="query 不能为空")
    documents = _coerce_documents(req.documents)
    if req.top_n is not None and req.top_n < 1:
        raise HTTPException(status_code=400, detail="top_n 必须至少为 1")

    info, client = await _resolve_model(request, req.model, expect="rerank")
    # Length is the worker's call for the same reason as /v1/embeddings: it owns
    # the tokenizer, and each pair is one sequence, so it is the pair that has
    # to fit -- not the document alone.

    req_id = uuid.uuid4().hex
    store = request.app.state.store
    key = next((k for k in store.keys if k.id == key_id), None) if key_id else None
    ctx = build_context(
        request.app.state.inference_log,
        req_id=req_id,
        source=request.url.path,
        model=info.model_id,
        actor=actor_from_key_id(store, key_id),
        params={"top_n": req.top_n, "return_documents": req.return_documents},
        messages=[{"role": "user", "content": req.query}],
    )

    try:
        reply = await client.rerank(req_id, req.query, documents)
    except WorkerError as exc:
        if ctx is not None:
            ctx.finish(status=STATUS_ERROR, error=exc)
        raise _worker_error_to_http(exc)

    logits = reply.get("logits") or []
    counts = reply.get("tokens") or []
    if len(logits) != len(documents):
        if ctx is not None:
            ctx.finish(status=STATUS_ERROR, error_type="ProtocolError",
                       error_message=f"worker 返回 {len(logits)} 个分数，请求了 {len(documents)} 条")
        raise HTTPException(status_code=503,
                            detail="worker 返回的分数数量与请求不一致；请重新加载该模型")

    scored = [{"index": i, "relevance_score": sigmoid(float(logit))}
              for i, logit in enumerate(logits)]
    # Descending by score; the sort is stable, so equal scores keep their
    # original order rather than shuffling between identical requests.
    scored.sort(key=lambda r: r["relevance_score"], reverse=True)
    if req.top_n is not None:
        scored = scored[: req.top_n]
    if req.return_documents:
        for item in scored:
            item["document"] = {"text": documents[item["index"]]}

    total_tokens = sum(int(c) for c in counts)
    response_id = f"rerank-{req_id}"
    if ctx is not None:
        ctx.finish(status=STATUS_OK,
                   output_text=json.dumps(
                       {str(r["index"]): round(r["relevance_score"], 6) for r in scored}),
                   prompt_tokens=total_tokens,
                   completion_tokens=0)
    return {
        "id": response_id,
        "model": req.model,
        "results": scored,
        "usage": {"prompt_tokens": total_tokens, "total_tokens": total_tokens},
    }


# The bare ``POST /rerank`` some clients call (see ``alias_router``). Same
# handler object, so the two paths share every rule including the record's
# ``source`` -- which is `request.url.path`, so a row from this path says
# "/rerank" and is still recognisably a rerank call.
alias_router.add_api_route(
    "/rerank", rerank, methods=["POST"], tags=["openai"],
    include_in_schema=False)


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------
#: OpenAI's ``response_format`` values. ``text``/``srt``/``vtt`` are plain-text
#: bodies rather than JSON, which is why the response is built by hand instead of
#: being a pydantic model.
RESPONSE_FORMATS = ("json", "text", "verbose_json", "srt", "vtt")

#: What an SRT/VTT cue needs. ``\n`` inside a cue is legal and common (a
#: subtitle line break), so it is passed through; anything else that would
#: break the cue format is normalised away.
_CUE_WHITESPACE = re.compile(r"[ \t]+")


def _srt_timestamp(seconds: float) -> str:
    """``HH:MM:SS,mmm`` -- SRT's comma, not a full stop."""
    ms = int(round(max(0.0, float(seconds)) * 1000.0))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _vtt_timestamp(seconds: float) -> str:
    """``HH:MM:SS.mmm`` -- WebVTT's full stop."""
    return _srt_timestamp(seconds).replace(",", ".")


def _cue_text(text: str) -> str:
    """Cue body text: no blank lines (they end a cue early), no CRs."""
    lines = [(_CUE_WHITESPACE.sub(" ", line).strip()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def render_srt(segments: list[dict]) -> str:
    """SubRip: one numbered cue per segment, in order."""
    out = []
    for index, seg in enumerate(segments, 1):
        body = _cue_text(seg.get("text") or "") or " "
        out.append(f"{index}\n{_srt_timestamp(seg['start'])} --> "
                   f"{_srt_timestamp(seg['end'])}\n{body}\n")
    return "\n".join(out)


def render_vtt(segments: list[dict]) -> str:
    """WebVTT: the required header, then one cue per segment."""
    out = ["WEBVTT", ""]
    for seg in segments:
        body = _cue_text(seg.get("text") or "") or " "
        out.append(f"{_vtt_timestamp(seg['start'])} --> {_vtt_timestamp(seg['end'])}\n{body}\n")
    return "\n".join(out)


def _bounded_float(name: str, raw: str | None, default: float,
                   minimum: float = 0.0, maximum: float = 1.0) -> float:
    """A float form field, refused rather than clamped when out of range.

    Clamping would silently serve a request the client did not make; the value
    is accepted and ignored by this service (greedy decoding), so a caller who
    sends nonsense should hear about it.
    """
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{name} 必须是数字，收到 {raw!r}") from None
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise HTTPException(
            status_code=400,
            detail=f"{name} 必须在 {minimum} 到 {maximum} 之间，收到 {raw!r}")
    return value


@router.post("/audio/transcriptions")
async def transcriptions(request: Request, key_id: str = Depends(require_api_key)):
    """OpenAI-compatible ``POST /v1/audio/transcriptions``.

    ``multipart/form-data``; the fields are OpenAI's (``file``, ``model``,
    ``language``, ``prompt``, ``response_format``, ``temperature``).
    ``temperature`` is accepted and ignored -- this engine decodes greedily, and
    silently pretending to sample would make two identical requests disagree.

    The body is read and parsed by :mod:`app.api.audio_upload` rather than by
    starlette's form parser: the release does not vendor ``python-multipart``,
    and its ``max_part_size`` bounds only non-file fields.
    """
    from ..engine.asr_prompt import normalize_language
    from . import audio_upload

    try:
        body = await audio_upload.read_body(request)
        parts = audio_upload.parse(body, request.headers.get("content-type"))
        values, upload = audio_upload.fields(parts)
    except audio_upload.UploadTooLarge as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except audio_upload.MultipartError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    model_name = (values.get("model") or "").strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="model 是必填字段")
    if upload is None or not upload.data:
        raise HTTPException(status_code=400, detail="file 是必填字段，且不能为空")

    response_format = (values.get("response_format") or "json").strip().lower()
    if response_format not in RESPONSE_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"response_format 必须是 {' / '.join(RESPONSE_FORMATS)} 之一，"
                   f"收到 {response_format!r}")
    language = values.get("language")
    if language is not None:
        language = language.strip() or None
    if language is not None:
        # Validated here as well as in the worker: the worker's refusal would
        # arrive as a 400 anyway, but a client asking for a language this model
        # does not have should not first wait for an audio decode.
        try:
            normalize_language(language)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
    prompt = values.get("prompt") or ""
    # Accepted and ignored -- see the docstring. Validated anyway so a client
    # sending nonsense hears about it instead of having it silently dropped.
    temperature = _bounded_float("temperature", values.get("temperature"), 0.0)

    info, client = await _resolve_model(request, model_name, expect="asr")

    req_id = uuid.uuid4().hex
    store = request.app.state.store
    audio_format = (upload.filename or "").rsplit(".", 1)[-1].lower() if upload.filename else ""
    params: dict = {
        "response_format": response_format,
        "language": language,
        "temperature": temperature,
    }
    if prompt:
        params["prompt"] = prompt
    # The record's `messages` is the request as a client sees it, not an audio
    # blob: the bytes are deliberately not stored, so what is stored has to say
    # which file was sent and how big it was.
    ctx = build_context(
        request.app.state.inference_log,
        req_id=req_id,
        source=request.url.path,
        model=info.model_id,
        actor=actor_from_key_id(store, key_id),
        params=params,
        messages=[{"role": "user", "content": json.dumps({
            "filename": upload.filename,
            "format": audio_format,
            "language": language,
            "prompt": prompt,
            "bytes": len(upload.data),
        }, ensure_ascii=False)}],
    )

    try:
        reply = await client.transcribe(
            req_id,
            base64.b64encode(upload.data).decode("ascii"),
            filename=upload.filename,
            language=language,
            prompt=prompt,
        )
    except WorkerError as exc:
        if ctx is not None:
            ctx.finish(status=STATUS_ERROR, error=exc)
        if exc.kind == "unsupported_audio":
            # 415: the audio is a format this device cannot decode. Not a 400
            # (the request is well-formed) and not a 503 (the model is fine).
            raise HTTPException(status_code=415, detail=str(exc)) from None
        raise _worker_error_to_http(exc) from None

    text = reply.get("text") or ""
    segments = reply.get("segments") or []
    duration = float(reply.get("duration") or 0.0)
    detected = reply.get("language") or language
    prompt_tokens = int(reply.get("prompt_tokens") or 0)
    completion_tokens = int(reply.get("completion_tokens") or 0)

    if ctx is not None:
        # The record keeps the transcript and the facts a reader needs to judge
        # it: how long the audio was, which language the model settled on, and
        # how many segments it took. The audio itself is never stored.
        ctx.params = {**params, "duration": duration,
                      "language_detected": detected,
                      "segments": len(segments),
                      "format": audio_format}
        ctx.finish(status=STATUS_OK,
                   output_text=text,
                   prompt_tokens=prompt_tokens,
                   completion_tokens=completion_tokens)

    if response_format == "text":
        return PlainTextResponse(text)
    if response_format == "srt":
        return PlainTextResponse(render_srt(segments), media_type="application/x-subrip")
    if response_format == "vtt":
        return PlainTextResponse(render_vtt(segments), media_type="text/vtt")
    if response_format == "verbose_json":
        return {
            "task": "transcribe",
            "language": detected,
            "duration": round(duration, 3),
            "text": text,
            "segments": [
                {
                    "id": int(seg.get("id", index)),
                    "seek": 0,
                    "start": round(float(seg.get("start", 0.0)), 3),
                    "end": round(float(seg.get("end", 0.0)), 3),
                    "text": seg.get("text") or "",
                    "tokens": [],
                    "temperature": 0.0,
                    "avg_logprob": 0.0,
                    "compression_ratio": 1.0,
                    "no_speech_prob": 0.0,
                }
                for index, seg in enumerate(segments)
            ],
            "usage": {"prompt_tokens": prompt_tokens,
                      "completion_tokens": completion_tokens,
                      "total_tokens": prompt_tokens + completion_tokens},
        }
    return {"text": text}


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------
#: The largest image one request may carry. 20 MiB is the task's number, and it
#: is a bound on memory in *this* process too: the body arrives base64 (4/3 of
#: the bytes) and is decoded before it is handed to the worker.
MAX_OCR_IMAGE_BYTES = 20 * 1024 * 1024

#: Fetching an http(s) image means the server issues a request the client chose,
#: which is an SSRF surface. This box is offline by design, so it is off by
#: default; a deployment that wants it sets the environment variable and owns
#: the consequences (docs/aux-models.md says so).
OCR_REMOTE_ENV = "CV84X6_OCR_ALLOW_REMOTE"

#: Timeout for that fetch, when it is allowed at all: long enough for a LAN
#: share, short enough that a black-holed address cannot pin a request.
OCR_REMOTE_TIMEOUT_S = 20.0

_DATA_IMAGE = re.compile(r"^data:(?P<mime>image/[^;,]+)?;base64,(?P<data>.*)$",
                         re.DOTALL)


def _ocr_image_bytes(raw) -> bytes:
    """The image's bytes, from whichever of the three accepted forms was sent.

    Every refusal is a 400 that says what to send instead, because the four
    inputs a client could have meant (data URI, bare base64, URL, and "oops a
    dict") produce four different mistakes and one generic message would hide
    which was made.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(
            status_code=400,
            detail="image 必须是非空字符串：data:image/...;base64,... 或纯 base64")
    value = raw.strip()
    match = _DATA_IMAGE.match(value)
    if match:
        value = match.group("data")
        if not value:
            raise HTTPException(status_code=400, detail="data URI 里没有图片数据")
    elif value.startswith(("http://", "https://")):
        return _ocr_fetch_remote(value)
    elif value.startswith("data:"):
        raise HTTPException(
            status_code=400,
            detail="image 的 data URI 必须是 data:image/<类型>;base64,<数据> 形式")
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"image 不是合法的 base64（data URI 需写成 data:image/png;base64,...）：{exc}"
        ) from None
    if not data:
        raise HTTPException(status_code=400, detail="image 解码后为空")
    if len(data) > MAX_OCR_IMAGE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"图片 {len(data) / 2**20:.1f} MiB，超过上限 "
                   f"{MAX_OCR_IMAGE_BYTES // 2**20} MiB")
    return data


def _ocr_fetch_remote(url: str) -> bytes:
    """Fetch an http(s) image, refusing unless the deployment allowed it.

    Synchronous on purpose: this runs in a route that has not reached the worker
    yet, and ``httpx``'s sync client keeps the 20 s timeout honest without
    spawning a loop-local task whose cancellation would have to be reasoned
    about separately. The image is capped while streaming rather than after, so
    a 4 GB URL cannot be buffered first.
    """
    if os.environ.get(OCR_REMOTE_ENV, "").strip() not in ("1", "true", "yes", "on"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持远程图片 URL（本机默认离线）。请把图片以 base64 或 "
                   f"data:image/...;base64,... 形式发送；运维确认需要时可设置 "
                   f"{OCR_REMOTE_ENV}=1 允许服务端拉取")
    import httpx

    try:
        with httpx.Client(timeout=OCR_REMOTE_TIMEOUT_S, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                buffer = bytearray()
                for chunk in response.iter_bytes(1 << 20):
                    buffer.extend(chunk)
                    if len(buffer) > MAX_OCR_IMAGE_BYTES:
                        raise HTTPException(
                            status_code=400,
                            detail=f"图片超过上限 {MAX_OCR_IMAGE_BYTES // 2**20} MiB")
    except HTTPException:
        raise
    except Exception as exc:  # httpx's own errors, a bad URL, a timeout
        raise HTTPException(
            status_code=400,
            detail=f"无法获取图片 URL：{type(exc).__name__}: {exc}") from None
    if not buffer:
        raise HTTPException(status_code=400, detail="图片 URL 返回了空内容")
    return bytes(buffer)


@router.post("/ocr")
async def ocr(request: Request, key_id: str = Depends(require_api_key)):
    """``POST /v1/ocr``: one image in, its text and lines out.

    OpenAI has no OCR endpoint, so this is our own shape -- but the auth, the
    error codes and the ``model`` field are the same as every other ``/v1``
    route, so a client that already talks to this service needs no new rules.

    Two body forms, because both are what clients actually send:

    * JSON (``{"model", "image", "return_boxes"}``), for programmatic callers;
    * ``multipart/form-data`` with a ``file`` part (plus ``model`` and
      ``return_boxes`` as fields), for the curl/Postman/UI case where sending a
      file is easier than base64-ing it.

    The body is read by :mod:`app.api.audio_upload`, the same bounded reader the
    transcription endpoint uses: the release does not vendor
    ``python-multipart``, and the image cap has to be enforced while reading
    rather than after buffering.
    """
    from . import audio_upload

    content_type = (request.headers.get("content-type") or "").lower()
    is_multipart = content_type.startswith("multipart/form-data")

    if is_multipart:
        try:
            body = await audio_upload.read_body(request, limit=MAX_OCR_IMAGE_BYTES)
            parts = audio_upload.parse(body, request.headers.get("content-type"))
            values, upload = audio_upload.fields(parts)
        except audio_upload.UploadTooLarge as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except audio_upload.MultipartError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        model_name = (values.get("model") or "").strip()
        if not model_name:
            raise HTTPException(status_code=400, detail="model 是必填字段")
        if upload is None or not upload.data:
            raise HTTPException(status_code=400, detail="file 是必填字段，且不能为空")
        if len(upload.data) > MAX_OCR_IMAGE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"图片 {len(upload.data) / 2**20:.1f} MiB，超过上限 "
                       f"{MAX_OCR_IMAGE_BYTES // 2**20} MiB")
        image = upload.data
        return_boxes = _bounded_bool("return_boxes", values.get("return_boxes"), True)
        mode = (values.get("mode") or "").strip() or "lines"
        filename = upload.filename
    else:
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(
                status_code=400,
                detail='请求体必须是 JSON（{"model", "image"}）或 multipart/form-data'
                       "（file 字段）") from None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="请求体必须是一个 JSON 对象")
        model_name = str(payload.get("model") or "").strip()
        if not model_name:
            raise HTTPException(status_code=400, detail="model 是必填字段")
        raw = payload.get("image")
        image = _ocr_image_bytes(raw)
        return_boxes = _bounded_bool("return_boxes", payload.get("return_boxes"), True)
        raw_mode = payload.get("mode")
        if raw_mode is not None and not isinstance(raw_mode, str):
            raise HTTPException(
                status_code=400,
                detail='mode 必须是字符串 "lines" / "layout" / "vl"'
                       f"（收到 {type(raw_mode).__name__}）")
        mode = (raw_mode or "").strip() or "lines"
        filename = None

    # The mode is validated by the worker, which is where its meaning lives;
    # doing it here too would be a second copy of the rule that could drift.
    # What is checked here is only that it is one of the three, so an obviously
    # wrong value is a 400 without a round trip.
    mode = mode.lower()
    if mode not in ("lines", "layout", "vl"):
        raise HTTPException(
            status_code=400,
            detail=f'mode 只能是 "lines" / "layout" / "vl"（收到 {mode!r}）')

    info, client = await _resolve_model(request, model_name, expect="ocr")

    # A ``vl`` page needs a second model, and the check happens before anything
    # is recorded or computed: the layout pass is 400 ms of NPU that would
    # otherwise be spent on a page destined for a 409 -- and the caller's
    # question ("which model do I load?") is answered by that refusal rather
    # than by a record of a request that never ran.
    vl_model_id = None
    if mode == "vl":
        from ..engine.ocr_vl_page import require_vl_model

        vl_model_id = require_vl_model(request)

    req_id = uuid.uuid4().hex
    store = request.app.state.store
    key = next((k for k in store.keys if k.id == key_id), None) if key_id else None
    # The record's `messages` describes the image without storing it: the bytes
    # are the one thing a debugger can reconstruct, and a page image is exactly
    # what an operator would not want in a log. The size is what makes the row
    # identifiable ("the 1240x1754 one I just sent").
    ctx = build_context(
        request.app.state.inference_log,
        req_id=req_id,
        source=request.url.path,
        model=info.model_id,
        actor=actor_from_key_id(store, key_id),
        params={"return_boxes": return_boxes, "mode": mode,
                **({"filename": filename} if filename else {}),
                # A ``vl`` page is served by two models; the row names the one
                # that is not the route's own so "which VLM read this" is
                # answerable from the log alone.
                **({"vl_model": vl_model_id} if vl_model_id else {})},
        messages=[{"role": "user", "content": json.dumps(
            {"image": {"bytes": len(image)},
             **({"filename": filename} if filename else {})},
            ensure_ascii=False)}],
    )

    encoded = base64.b64encode(image).decode("ascii")
    try:
        if mode == "vl":
            reply = await _ocr_vl_page(request, vl_model_id, client, req_id,
                                       encoded)
        else:
            reply = await client.ocr(req_id, encoded, mode=mode)
    except WorkerError as exc:
        if ctx is not None:
            ctx.finish(status=STATUS_ERROR, error=exc)
        raise _worker_error_to_http(exc) from None

    text = reply.get("text") or ""
    raw_lines = reply.get("lines") or []
    lines = [_ocr_line(entry, return_boxes) for entry in raw_lines]
    det_ms = float(reply.get("det_ms") or 0.0)
    rec_ms = float(reply.get("rec_ms") or 0.0)
    reply_mode = reply.get("mode") or mode

    blocks = None
    usage = OcrUsage(det_ms=round(det_ms, 2), rec_ms=round(rec_ms, 2),
                     lines=len(lines))
    if reply_mode in ("layout", "vl"):
        raw_blocks = reply.get("blocks") or []
        blocks = [OcrBlock(
            index=int(entry.get("index") or 0),
            type=str(entry.get("type") or "text"),
            label=str(entry.get("label") or "text"),
            score=round(float(entry.get("score") or 0.0), 6),
            box=[int(v) for v in (entry.get("box") or [0, 0, 0, 0])],
            text=entry.get("text") or "",
            lines=[_ocr_region_line(e, return_boxes)
                   for e in (entry.get("lines") or [])],
            task=entry.get("task"),
        ) for entry in raw_blocks]
        usage = OcrUsage(
            det_ms=round(det_ms, 2), rec_ms=round(rec_ms, 2), lines=len(lines),
            blocks=len(blocks),
            layout_ms=round(float(reply.get("layout_ms") or 0.0), 2),
            **({"vl_ms": round(float(reply.get("vl_ms") or 0.0), 2),
                "vl_tokens": int(reply.get("vl_tokens") or 0)}
               if reply_mode == "vl" else {}),
        )

    if ctx is not None:
        # The image's own dimensions go in `params` rather than `messages`: the
        # worker measured them (it decoded the picture), and they are the first
        # thing to check when the boxes look wrong.
        ctx.params = {**(ctx.params or {}),
                      "width": int(reply.get("width") or 0),
                      "height": int(reply.get("height") or 0),
                      "lines": len(lines),
                      **({"blocks": len(blocks)} if blocks is not None else {})}
        ctx.finish(status=STATUS_OK, output_text=text,
                   prompt_tokens=0, completion_tokens=0)

    response = OcrResponse(
        id=f"ocr-{req_id}",
        model=model_name,
        mode=reply_mode,
        text=text,
        lines=lines,
        usage=usage,
        blocks=blocks,
    )
    if reply_mode in ("layout", "vl"):
        return response
    # ``lines`` stays the exact shape it had before layout mode existed: no
    # ``mode``/``blocks`` keys and no layout-only usage fields, so a client with
    # a strict schema keeps validating.
    return JSONResponse(response.model_dump(
        exclude={"mode": True, "blocks": True,
                 "usage": {"blocks", "layout_ms", "vl_ms", "vl_tokens"}}))


async def _ocr_vl_page(request: Request, vl_model_id: str,
                       ocr_client: WorkerClient, req_id: str,
                       image_b64: str) -> dict:
    """``mode: "vl"``: layout on the OCR model, recognition on the VLM.

    Two models, two workers, and no HTTP loopback: the API process is the client
    of both, so a page costs two socket round trips and the VLM's own queueing
    (``serial_only``) is what serialises it against chat requests.

    **The two models are loaded by different rules, and that difference is the
    reason this refusal exists.** The OCR model went through
    ``_resolve_model``'s admission gate, which treats an auxiliary model as
    loadable on demand (subject to ``aux_auto_load``). The VLM is **not** an
    auxiliary kind -- it is 3.3 GB resident and an operator loads it
    deliberately, exactly like a chat model -- so a missing one is a 409 naming
    it rather than two minutes of loading on a page request. ``require_vl_model``
    already ran in the route, before the layout pass, for the same reason the
    layout pass is not free: 400 ms of NPU for a page destined for a 409 is
    wasted work, and the caller's real question ("which model do I load?") is
    answered by the refusal itself.
    """
    vl_client = request.app.state.clients.get(vl_model_id)
    if vl_client is None:
        raise HTTPException(
            status_code=409,
            detail=f"PaddleOCR-VL 模型 {vl_model_id} 已加载但没有可用的 worker 连接；"
                   "请在控制台卸载后重新加载")
    from ..engine.ocr_vl_page import run_vl_page

    return await run_vl_page(ocr_client, vl_client, image_b64, req_id)


def _ocr_line(entry: dict, return_boxes: bool) -> OcrLine:
    """One worker line -> the response's line.

    ``return_boxes: false`` blanks the box rather than dropping the key, which is
    the shape this endpoint has always returned for lines mode; a client that
    deserialises into a fixed struct keeps working.
    """
    box = entry.get("box")
    return OcrLine(
        text=entry.get("text") or "",
        score=float(entry.get("score") or 0.0),
        box=([[float(p[0]), float(p[1])] for p in box]
             if return_boxes and box else None),
    )


def _ocr_region_line(entry: dict, return_boxes: bool) -> OcrRegionLine:
    box = entry.get("box")
    return OcrRegionLine(
        text=entry.get("text") or "",
        score=float(entry.get("score") or 0.0),
        box=([[float(p[0]), float(p[1])] for p in box]
             if return_boxes and box else None),
    )


def _bounded_bool(name: str, raw, default: bool) -> bool:
    """A boolean that may arrive as JSON ``true``, ``"true"`` or ``"1"``.

    A multipart field is always a string; a JSON body may be a real boolean. An
    unparseable value is refused rather than defaulted: silently ignoring
    ``return_boxes: "flase"`` would answer a different question than the one
    asked, and the caller would only find out from a missing field.
    """
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return bool(raw)
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    raise HTTPException(
        status_code=400,
        detail=f"{name} 必须是布尔值（true/false），收到 {raw!r}")
