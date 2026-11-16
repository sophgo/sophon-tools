"""OpenAI-compatible request/response models.

Field names and defaults deliberately mirror the OpenAI spec so existing SDKs
and agents work unchanged -- that compatibility is the product requirement, not
a nicety.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_serializer


class ContentPart(BaseModel):
    type: str
    text: str | None = None
    # OpenAI's image_url shape: {"type":"image_url","image_url":{"url":"data:..."}}
    image_url: dict[str, Any] | None = None


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[ContentPart] | None = None
    name: str | None = None
    # Function calling, in OpenAI's shapes: an assistant turn carries the calls
    # it made, a tool turn answers one of them by id.
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    # Qwen thinking mode: returned as its own field so agents can show or
    # discard the reasoning instead of parsing <think> out of the answer.
    reasoning_content: str | None = None

    @model_serializer(mode="wrap")
    def _omit_unset(self, handler):
        """Drop the tool/reasoning keys when they do not apply.

        `content: null` stays, because that is exactly what OpenAI sends for a
        turn that is nothing but tool calls.
        """
        data = handler(self)
        for key in ("tool_calls", "tool_call_id", "reasoning_content"):
            if data.get(key) is None:
                data.pop(key, None)
        return data


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    max_tokens: int | None = None
    # OpenAI's newer spelling of the same field. PaddleX's official client sends
    # this one (paddlex/inference/models/doc_vlm/predictor.py: use
    # ``max_completion_tokens`` for every backend except the local llama.cpp/MLX
    # ones), so a server that only read ``max_tokens`` would silently answer with
    # its own default length instead of the caller's.
    max_completion_tokens: int | None = None
    temperature: float | None = 0.8
    top_p: float | None = 0.8
    n: int = 1
    stream: bool = False
    stop: str | list[str] | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    seed: int | None = None
    # Non-standard but widely used by local servers; harmless to accept.
    top_k: int | None = 50
    repetition_penalty: float | None = None
    # Qwen thinking mode; off by default like the vendor demo.
    enable_thinking: bool | None = None
    chat_template_kwargs: dict[str, Any] | None = None
    # Function calling. Typed loosely and validated in the endpoint so a bad
    # shape is a 400 with a message ("each tool must have function.name"), not a
    # 422 pydantic dump.
    tools: list[Any] | None = None
    tool_choice: str | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_tokens_details: dict[str, int] | None = None


class ChatChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str | None = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatChoice]
    usage: Usage


class ModelCard(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "cv84x6"
    #: chat | embedding | rerank | asr. Clients that only speak the chat API use
    #: this to pick a model instead of discovering the mismatch from a 400.
    kind: str = "chat"


class ModelList(BaseModel):
    object: str = "list"
    data: list[ModelCard]


# ---------------------------------------------------------------------------
# Embeddings (OpenAI /v1/embeddings) and rerank (Jina/Cohere /v1/rerank)
# ---------------------------------------------------------------------------
class EmbeddingRequest(BaseModel):
    """OpenAI's shape, plus instruction and a multimodal input extension.

    ``input`` is typed loosely on purpose: OpenAI accepts a string, a list of
    strings, or a list of token ids, and the last one must be refused with a
    *helpful* 400 rather than a 422 from pydantic -- so the discrimination
    happens in the endpoint, where the message can say why.
    """

    model: str
    input: Any = Field(description="字符串或字符串数组，最多 64 条。Qwen3-VL-Embedding / WeMM-Embedding 还接受 "
                       "{text?: string, image?: JPEG/PNG base64 data URL} 及混合数组；"
                       "每条一张图片，单张最多 4 MiB，每批最多 16 张、合计 16 MiB。")
    encoding_format: Literal["float", "base64"] = "float"
    dimensions: int | None = Field(default=None, description="截断后重新 L2 归一化；"
                                  "Qwen3-Embedding 为 32–1024，Qwen3-VL-Embedding / WeMM-Embedding-2B 为 64–2048。")
    # Non-standard (vLLM and several local servers accept it): a prefix applied
    # to every input. Qwen3-Embedding is instruction-tuned -- a query without
    # its instruction embeds into a different space than the documents it is
    # compared against.
    # Qwen3-VL-Embedding uses this as the system instruction instead. Its
    # input additionally accepts {text?, image?: <JPEG/PNG data URL>} and
    # arrays mixing those objects with strings. MRL range: 64..2048.
    instruction: str | None = Field(default=None, description="可选任务指令。文本 embedding 拼在输入前；"
                                   "多模态 embedding 使用系统指令；Qwen3-VL 默认 Represent the user's input.，"
                                   "WeMM 默认不加系统指令。")


class EmbeddingData(BaseModel):
    object: str = "embedding"
    index: int
    # list[float] for encoding_format=float, str for base64. A union would make
    # pydantic coerce one into the other; the route builds the dict itself.
    embedding: Any


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: list[EmbeddingData]
    model: str
    usage: Usage


class RerankRequest(BaseModel):
    """Jina/Cohere rerank shape (OpenAI has no rerank endpoint).

    ``documents`` accepts both forms the ecosystem uses -- bare strings, and
    ``{"text": ...}`` objects -- because Dify and LangChain send the first while
    Cohere's own clients send the second.
    """

    model: str
    query: str
    documents: list[Any]
    top_n: int | None = None
    return_documents: bool = True


class RerankResult(BaseModel):
    index: int
    relevance_score: float
    document: dict | None = None


class RerankResponse(BaseModel):
    id: str
    model: str
    results: list[RerankResult]
    usage: Usage


# ---------------------------------------------------------------------------
# OCR (``POST /v1/ocr``; OpenAI has no such endpoint)
# ---------------------------------------------------------------------------
class OcrRequest(BaseModel):
    """The JSON form of an OCR request.

    ``image`` accepts the three spellings the ecosystem uses for "here is a
    picture": a ``data:image/…;base64,…`` URI (what OpenAI vision clients send),
    bare base64, or an ``http(s)`` URL. The URL is fetched by the *server*, which
    is why the endpoint refuses it unless the deployment says otherwise -- see
    ``OPENAI_API_OCR_ALLOW_REMOTE`` in docs/aux-models.md. Typed loosely and
    validated in the route so a wrong type is a 400 with a sentence rather than
    a pydantic dump naming a field the caller cannot map to their request.
    """

    model: str
    image: Any = None
    #: False omits each line's four-point box from the response, for callers that
    #: only want the text. The worker still computes them (they are what it
    #: cropped with); this only decides whether they are serialised.
    return_boxes: bool = True
    #: ``lines`` (the default) transcribes the image as a flat list of lines.
    #: ``layout`` segments the page into regions first and returns Markdown plus
    #: the regions in reading order; its response carries ``blocks``. Typed as a
    #: plain string so an unknown value is a 400 from the worker naming the two
    #: accepted modes, rather than a pydantic enum dump.
    mode: str = "lines"


class OcrLine(BaseModel):
    text: str
    score: float
    #: Four [x, y] points in source-image pixels, in PaddleOCR's order:
    #: top-left, top-right, bottom-right, bottom-left. Omitted when the request
    #: asked for ``return_boxes: false``.
    box: list[list[float]] | None = None


class OcrUsage(BaseModel):
    """OCR's own usage block: there are no tokens, so it reports the work done.

    Keeping OpenAI's ``prompt_tokens``/``completion_tokens`` here would be a
    fiction; a client that needs a token count can use the line count.

    In layout mode the same three fields are present -- ``det_ms`` and ``rec_ms``
    are the OCR pass, which is the same work ``lines`` mode does -- and
    ``blocks`` plus ``layout_ms`` are added rather than replacing them, so a
    client that reads ``usage.det_ms`` from either mode reads a real number.
    """

    det_ms: float
    rec_ms: float
    lines: int
    #: Layout mode: how many regions the page was segmented into.
    blocks: int | None = None
    #: Layout mode: the layout model's own forward pass, separately timed.
    layout_ms: float | None = None
    #: ``vl`` mode: the VLM's own time, summed over the page's regions (vit +
    #: prefill + decode). Kept apart from ``layout_ms`` because the two are the
    #: two halves of the page's cost and an operator tuning one needs them
    #: separated.
    vl_ms: float | None = None
    #: ``vl`` mode: how many tokens the VL model generated for the whole page.
    #: The honest "work done" number -- there is no affordable per-region token
    #: count in the response, and one total is what a caller budgeting a page
    #: actually needs.
    vl_tokens: int | None = None

    @model_serializer(mode="wrap")
    def _omit_vl_fields_outside_vl_mode(self, handler):
        """Drop the ``vl``-only fields when they were never set.

        ``layout`` mode's ``usage`` object must stay exactly what it was before
        this mode existed -- the card says the two older modes' responses are
        byte-identical, and a ``vl_ms: null`` beside ``layout_ms`` would be a new
        key in a response a strict client already validates.
        """
        data = handler(self)
        for name in ("vl_ms", "vl_tokens"):
            if data.get(name) is None:
                data.pop(name, None)
        return data


class OcrRegionLine(BaseModel):
    """One OCR line inside a layout region."""

    text: str
    score: float
    #: Four [x, y] points in source-image pixels, PP-OCR's order. Omitted when
    #: the request asked for ``return_boxes: false``, exactly as ``OcrLine`` is.
    box: list[list[float]] | None = None


class OcrBlock(BaseModel):
    """One layout region of a page, in reading order.

    ``label`` is PP-DocLayout's raw class (one of 23) and ``type`` is the coarse
    grouping the card's response shape lists. Both, because they answer
    different questions: a caller rendering Markdown wants the type, and a caller
    debugging "why is this a table" wants the label.

    ``task`` exists only in ``vl`` mode: it is the instruction the region's text
    was produced with. ``layout`` mode recognises nothing region by region (it
    runs PP-OCR once for the page), so the field is *absent* there rather than
    ``null`` -- ``layout`` responses must stay byte-identical to what they were
    before this mode existed, and a new ``null`` key would break a strict
    client's schema.
    """

    index: int
    type: str
    label: str
    score: float
    box: list[int]
    text: str
    lines: list[OcrRegionLine]
    #: ``vl`` mode: the prompt this block was recognised with (``OCR:``,
    #: ``Table Recognition:``, ``Formula Recognition:``), or ``None`` for a
    #: region the model was not asked to read (a picture).
    task: str | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_task(self, handler):
        """Drop ``task`` when it was never set, keeping ``layout`` unchanged."""
        data = handler(self)
        if self.task is None:
            data.pop("task", None)
        return data


class OcrLayoutUsage(BaseModel):
    """Layout mode's usage block: the per-stage times the card asks for."""

    layout_ms: float
    det_ms: float
    rec_ms: float
    blocks: int
    lines: int


class OcrResponse(BaseModel):
    id: str
    model: str
    #: ``lines`` or ``layout``. Echoed so a client that sent nothing can still
    #: tell which shape it got.
    mode: str = "lines"
    #: Every line's text, in reading order, joined by newlines. In layout mode
    #: this is the page's Markdown instead.
    text: str
    lines: list[OcrLine]
    usage: OcrUsage
    #: Layout mode only: the page's regions in reading order. Absent (``null``)
    #: for ``lines`` mode, which is what keeps that response byte-identical.
    blocks: list[OcrBlock] | None = None
