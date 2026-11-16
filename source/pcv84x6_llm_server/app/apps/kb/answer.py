"""Grounded generation: retrieved chunks in, a cited streaming answer out.

Two constraints shape this module.

**The frame format is ``/api/test/chat/completions``'s.** The console already
knows how to read OpenAI delta frames (it drives the dialog test page with the
same parser), so the answer stream reuses them verbatim and adds exactly one
frame the design specifies -- ``{"type": "citations", "items": [...]}`` -- before
``[DONE]``. A new format would have meant a second parser in the front end for no
gain.

**The answer must be attributable.** The chunks are numbered ``[1]…[n]`` in the
system prompt and the same numbering is sent back in the citations frame, so a
reader can map every ``[n]`` in the text to a chunk id without string matching.
The model is told to say so when the material is insufficient: a plausible
answer with no support in the retrieval is the one failure mode of a RAG demo
that looks like success.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass

from ...core.client import WorkerError
from ...core.inference_log import (
    STATUS_CANCELLED,
    STATUS_ERROR,
    STATUS_OK,
    build_context,
    cancellation_error,
)
from ...schemas import ChatMessage
from ...api.openai_api import build_prompt

logger = logging.getLogger(__name__)

#: The default completion budget. Long enough for a paragraph or two of grounded
#: prose, short enough that a 5-token/s board answers in a couple of minutes.
DEFAULT_MAX_TOKENS = 1024

#: How much of one chunk goes into the prompt. The reranker's limit is larger,
#: but a 400-character chunk is already about the target and five of them plus
#: the question leave room in any 2 k context.
MAX_CHUNK_CHARS_IN_PROMPT = 800

SYSTEM_TEMPLATE = """你是一个只依据给定资料回答问题的助手。

规则：
1. 只使用下面「资料」中的内容作答，不要使用你自己的知识，不要猜测。
2. 每个来自资料的结论后面用 [n] 标注出处，n 是资料的编号；可以同时标注多个，如 [1][3]。
3. 如果资料不足以回答，直接说明「资料中没有相关内容」，并指出还缺什么。
4. 用简体中文回答；资料是其他语言时也译成中文。
5. 不要复述这些规则，也不要输出资料原文之外的内容。

资料：
{passages}"""


@dataclass
class Passage:
    """One retrieved chunk as it appears in the prompt and in the citations."""

    number: int
    chunk_id: str
    doc_name: str
    page: int | None
    text: str

    def render(self) -> str:
        where = self.doc_name or "未命名文档"
        if self.page is not None:
            where += f" 第 {self.page} 页"
        body = self.text.strip()
        if len(body) > MAX_CHUNK_CHARS_IN_PROMPT:
            body = body[:MAX_CHUNK_CHARS_IN_PROMPT] + "…"
        return f"[{self.number}] （来源：{where}）\n{body}"


def build_passages(results: list[dict]) -> list[Passage]:
    """Number the search results 1..n in the order the caller sent them."""
    out: list[Passage] = []
    for i, item in enumerate(results):
        out.append(Passage(
            number=i + 1,
            chunk_id=item.get("chunk_id") or "",
            doc_name=item.get("doc_name") or "",
            page=item.get("page"),
            text=item.get("text") or "",
        ))
    return out


def render_prompt(query: str, passages: list[Passage]) -> tuple[str, list[str]]:
    """The chat prompt for a grounded answer, in the model's own chat format."""
    system = SYSTEM_TEMPLATE.format(
        passages="\n\n".join(p.render() for p in passages))
    messages = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=query),
    ]
    return build_prompt(messages, enable_thinking=False)


async def stream_answer(request, *, client, model_id: str, query: str,
                        passages: list[Passage], max_tokens: int):
    """An SSE generator: OpenAI delta frames, a citations frame, then ``[DONE]``.

    Cancellation reaches the worker. Starlette throws ``GeneratorExit`` into this
    generator when the browser goes away, and the only correct response is to
    cancel the request on the worker before yielding anything else -- a 35B
    decoding into a socket nobody reads keeps the NPU busy for minutes.
    """
    req_id = uuid.uuid4().hex
    prompt, images = render_prompt(query, passages)
    params = {
        "max_tokens": max_tokens,
        # The engine decodes greedily; the field is sent because the worker
        # protocol has it, and set to 0 so a future sampler cannot make the demo
        # irreproducible.
        "temperature": 0.0,
        "stop": [],
    }
    created = int(time.time())
    cid = f"chatcmpl-{req_id}"
    ctx = build_context(
        request.app.state.inference_log,
        req_id=req_id,
        source=request.url.path,
        model=model_id,
        # The design's actor for this app: the console's cookie authenticated
        # the request, and "kb" says which console feature spent the NPU time.
        actor={"actor_type": "admin", "actor_id": None, "actor_name": "kb"},
        params={**params, "enable_thinking": False, "passages": len(passages)},
        messages=[{"role": "system", "content": SYSTEM_TEMPLATE.split("\n")[0]},
                  {"role": "user", "content": query}],
        prompt=prompt,
    )
    emitted: list[str] = []
    done: dict = {}
    recorded = False

    def record(status: str, **extra) -> None:
        nonlocal recorded
        if ctx is None or recorded:
            return
        recorded = True
        ctx.finish(status=status, output_text="".join(emitted),
                   raw_output="".join(emitted),
                   response_content="".join(emitted) if status == STATUS_OK else None,
                   prompt_tokens=done.get("prompt_tokens"),
                   completion_tokens=done.get("completion_tokens"),
                   cached_tokens=done.get("cached_tokens"),
                   first_token_latency_s=done.get("first_token_latency_s"),
                   decode_tps=done.get("decode_tps"),
                   finish_reason=done.get("finish_reason") if status == STATUS_OK else None,
                   **extra)

    def chunk(delta: dict, finish=None) -> str:
        payload = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_id,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    try:
        # The citations frame goes first, not last. The console shows the source
        # panel while the answer is still streaming, and a client that gives up
        # midway would otherwise never learn which chunks the text was grounded
        # in -- the one piece of the response that explains it.
        yield chunk({"role": "assistant", "content": ""})
        yield f"data: {json.dumps({'type': 'citations', 'items': [{'n': p.number, 'chunk_id': p.chunk_id, 'doc_name': p.doc_name, 'page': p.page} for p in passages]}, ensure_ascii=False)}\n\n"
        async for evt in client.generate(req_id, prompt, params, images or None):
            if evt["op"] == "delta":
                emitted.append(evt["text"])
                yield chunk({"content": evt["text"]})
            elif evt["op"] == "done":
                done = evt
        finish_reason = done.get("finish_reason") or "stop"
        yield chunk({}, finish=finish_reason)
        usage = {
            "prompt_tokens": done.get("prompt_tokens", 0),
            "completion_tokens": done.get("completion_tokens", 0),
            "total_tokens": done.get("prompt_tokens", 0) + done.get("completion_tokens", 0),
        }
        yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': created, 'model': model_id, 'choices': [], 'usage': usage})}\n\n"
        yield "data: [DONE]\n\n"
        record(STATUS_OK)
    except (asyncio.CancelledError, GeneratorExit):
        await client.cancel(req_id)
        etype, emsg = cancellation_error("kb answer")
        record(STATUS_CANCELLED, error_type=etype, error_message=emsg)
        raise
    except WorkerError as exc:
        record(STATUS_ERROR, error=exc)
        err = {"error": {"message": str(exc), "type": "server_error"}}
        yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
    except (ConnectionError, OSError) as exc:
        record(STATUS_ERROR, error=exc)
        err = {"error": {"message": f"连接中断：{type(exc).__name__}",
                         "type": "server_error"}}
        yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
