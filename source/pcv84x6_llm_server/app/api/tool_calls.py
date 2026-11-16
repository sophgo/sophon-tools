"""Qwen function calling: chat-template rendering and output parsing.

Rendering has to match the model's own ``chat_template.jinja`` byte for byte.
The board's prefix cache keys on the prompt token prefix, so one stray space in
a tool block turns every follow-up turn of an agent conversation into a full
re-prefill. ``tests/test_tool_calls.py`` renders the same template with jinja2
and compares the two, which is what keeps this hand-written renderer honest;
the template copy it uses is ``tests/data/qwen3_6_chat_template.jinja``.

Parsing lives here as well: the ``<tool_call>`` format is defined by that
template, not by the HTTP layer. Everything in this module is a pure function
or a detokenizer-side state machine, so it is testable without an NPU.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

IMAGE_PLACEHOLDER = "<|vision_start|><|image_pad|><|vision_end|>"

THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"
TOOL_CALL_OPEN = "<tool_call>"
TOOL_CALL_CLOSE = "</tool_call>"

# The two opening lines of the tool system message, verbatim from the template.
_TOOLS_HEADER = "# Tools\n\nYou have access to the following functions:\n\n<tools>"

# The fixed instructions block the template appends after </tools>, including
# its example. Copied verbatim; the rendering test compares it byte for byte.
_TOOLS_INSTRUCTIONS = (
    "\n\nIf you choose to call a function ONLY reply in the following format with NO suffix:"
    "\n\n<tool_call>\n<function=example_function_name>\n"
    "<parameter=example_parameter_1>\nvalue_1\n</parameter>\n"
    "<parameter=example_parameter_2>\nThis is the value for the second parameter\n"
    "that can span\nmultiple lines\n</parameter>\n</function>\n</tool_call>"
    "\n\n<IMPORTANT>\nReminder:\n"
    "- Function calls MUST follow the specified format: an inner <function=...></function> "
    "block must be nested within <tool_call></tool_call> XML tags\n"
    "- Required parameters MUST be specified\n"
    "- You may provide optional reasoning for your function call in natural language "
    "BEFORE the function call, but NOT after\n"
    "- If there is no function call available, answer the question like normal with your "
    "current knowledge and do not tell the user about function calls\n"
    "</IMPORTANT>"
)

_DATA_URL = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.*)$", re.DOTALL)
_FUNCTION_RE = re.compile(r"<function=(.+?)>")
_PARAMETER_RE = re.compile(r"<parameter=(.+?)>\n?(.*?)\n?</parameter>", re.DOTALL)


# --------------------------------------------------------------------------
# Request content
# --------------------------------------------------------------------------
def _part_field(part: Any, name: str) -> Any:
    """Read a content part field from either a pydantic model or a plain dict."""
    if isinstance(part, dict):
        return part.get(name)
    return getattr(part, name, None)


def flatten_content(content: Any) -> tuple[str, list[str]]:
    """Turn OpenAI's content shape into (text, [base64 images]).

    Each image part becomes IMAGE_PLACEHOLDER at its position in the text, as
    the Qwen chat template renders {"type": "image"}; the worker expands the
    single <|image_pad|> to the image's row count.

    Raises ValueError for anything that cannot be rendered faithfully; the HTTP
    layer turns that into a 400 rather than answering a different question.
    """
    if content is None:
        return "", []
    if isinstance(content, str):
        return content, []
    texts: list[str] = []
    images: list[str] = []
    for part in content:
        ptype = _part_field(part, "type")
        if ptype == "text" and _part_field(part, "text"):
            texts.append(_part_field(part, "text"))
        elif ptype == "image_url" and _part_field(part, "image_url"):
            url = (_part_field(part, "image_url") or {}).get("url", "")
            m = _DATA_URL.match(url)
            if m:
                images.append(m.group("data"))
                texts.append(IMAGE_PLACEHOLDER)
            elif url.startswith("http"):
                # Remote URLs are a server-side fetch (SSRF surface). This box is
                # offline by design, so reject rather than fetch.
                raise ValueError(
                    "remote image URLs are not supported on this offline device; "
                    "send the image as a base64 data: URL"
                )
            else:
                raise ValueError("unsupported image_url")
        else:
            # Silently dropping a part (audio, file, ...) would answer a
            # different question than the one asked.
            raise ValueError(f"content part type {ptype!r} is not supported")
    # Placeholders join without a separator, like the template; text parts are
    # newline-separated as before.
    out = ""
    for t in texts:
        if out and t != IMAGE_PLACEHOLDER and not out.endswith(IMAGE_PLACEHOLDER):
            out += "\n"
        out += t
    return out, images


def validate_tools(tools: Any) -> list[dict]:
    """Check the OpenAI ``tools`` shape; raises ValueError for anything else."""
    if tools is None:
        return []
    if not isinstance(tools, list):
        raise ValueError("tools must be a list")
    for tool in tools:
        if not isinstance(tool, dict):
            raise ValueError("each tool must be an object")
        if tool.get("type") != "function":
            raise ValueError('each tool must have "type": "function"')
        fn = tool.get("function")
        if not isinstance(fn, dict) or not isinstance(fn.get("name"), str) or not fn["name"]:
            raise ValueError('each tool must have function.name')
    return tools


def select_tools(tools: Sequence[dict] | None, tool_choice: Any) -> list[dict]:
    """Which tools the prompt advertises, given ``tool_choice``.

    Not a decoding constraint: the engine has no grammar-limited sampling, so
    "required" only means "offer every tool", and a named function narrows the
    list to that one. "none" advertises nothing, which is what tells the model
    to answer rather than call.
    """
    tools = list(tools or [])
    if not tools or tool_choice == "none":
        return []
    if tool_choice is None or tool_choice in ("auto", "required"):
        return tools
    if isinstance(tool_choice, dict):
        fn = tool_choice.get("function") if isinstance(tool_choice.get("function"), dict) else tool_choice
        name = fn.get("name")
        chosen = [t for t in tools if (t.get("function") or {}).get("name") == name]
        if not chosen:
            raise ValueError(f"tool_choice names {name!r}, which is not in tools")
        return chosen
    raise ValueError(f"unsupported tool_choice {tool_choice!r}")


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
def _assistant_block(message: Any, content: str, keep_thinking: bool) -> str:
    """One assistant turn: optional think block, content, tool calls."""
    reasoning = getattr(message, "reasoning_content", None)
    if not isinstance(reasoning, str):
        reasoning = ""
        if THINK_CLOSE in content:
            # Same split the template does: everything before </think> is the
            # reasoning, everything after is the answer.
            reasoning = content.split(THINK_CLOSE)[0].rstrip("\n").split(THINK_OPEN)[-1].lstrip("\n")
            content = content.split(THINK_CLOSE)[-1].lstrip("\n")
    reasoning = reasoning.strip()

    out = "<|im_start|>assistant\n"
    if keep_thinking:
        out += f"{THINK_OPEN}\n{reasoning}\n{THINK_CLOSE}\n\n"
    out += content

    tool_calls = getattr(message, "tool_calls", None)
    for i, call in enumerate(tool_calls or []):
        fn = call.get("function") if isinstance(call, dict) and isinstance(call.get("function"), dict) else call
        name = fn.get("name", "")
        if i == 0:
            out += "\n\n" if content.strip() else ""
            out += f"{TOOL_CALL_OPEN}\n<function={name}>\n"
        else:
            out += f"\n{TOOL_CALL_OPEN}\n<function={name}>\n"
        arguments = fn.get("arguments")
        if isinstance(arguments, str):
            # OpenAI carries arguments as a JSON string.
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except ValueError:
                arguments = {}
        for key, value in (arguments or {}).items():
            out += f"<parameter={key}>\n"
            out += value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            out += "\n</parameter>\n"
        out += f"</function>\n{TOOL_CALL_CLOSE}"
    return out + "<|im_end|>\n"


def render_messages(
    messages: Sequence[Any],
    tools: Sequence[dict] | None = None,
    enable_thinking: bool = False,
    flatten: Callable[[Any], tuple[str, list[str]]] | None = None,
) -> tuple[str, list[str]]:
    """Render a conversation in the model's chat format; returns (prompt, images).

    Mirrors ``Qwen3.6``'s chat_template.jinja, including its two quirks that the
    tests pin down: consecutive ``tool`` messages collapse into one user turn,
    and reasoning is kept only for assistant turns after the last real question
    (``last_query_index``), because keeping every old think block would grow the
    prompt without adding anything the model can use.
    """
    flatten = flatten or flatten_content
    if not messages:
        raise ValueError("messages must not be empty")

    # Flatten once: the content is needed both for last_query_index and the loop.
    texts: list[str] = []
    images: list[str] = []
    for m in messages:
        text, imgs = flatten(m.content)
        texts.append(text)
        images.extend(imgs)

    out = ""
    if tools:
        out += "<|im_start|>system\n" + _TOOLS_HEADER
        for tool in tools:
            out += "\n" + json.dumps(tool, ensure_ascii=False)
        out += "\n</tools>" + _TOOLS_INSTRUCTIONS
        if messages[0].role == "system":
            system = texts[0].strip()
            if system:
                out += "\n\n" + system
        out += "<|im_end|>\n"
    elif messages[0].role == "system":
        out += "<|im_start|>system\n" + texts[0].strip() + "<|im_end|>\n"

    # last_query_index: the newest user message that is a real question, i.e.
    # not a <tool_response> block.
    last_query_index = len(messages) - 1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role != "user":
            continue
        text = texts[i].strip()
        if not (text.startswith("<tool_response>") and text.endswith("</tool_response>")):
            last_query_index = i
            break
    else:
        raise ValueError("no user query found in messages")

    for i, m in enumerate(messages):
        text = texts[i].strip()
        if m.role == "system":
            if i != 0:
                # The template raises here; rendering it anyway would put the
                # system prompt in a place the model never saw in training.
                raise ValueError("system message must be at the beginning")
        elif m.role == "user":
            out += f"<|im_start|>user\n{text}<|im_end|>\n"
        elif m.role == "assistant":
            out += _assistant_block(m, text, keep_thinking=i > last_query_index)
        elif m.role == "tool":
            # Consecutive tool results share one user turn, each inside its own
            # <tool_response> wrapper.
            if i == 0 or messages[i - 1].role != "tool":
                out += "<|im_start|>user"
            out += f"\n<tool_response>\n{text}\n</tool_response>"
            if i == len(messages) - 1 or messages[i + 1].role != "tool":
                out += "<|im_end|>\n"
        else:
            raise ValueError(f"unsupported message role {m.role!r}")

    out += "<|im_start|>assistant\n"
    out += f"{THINK_OPEN}\n" if enable_thinking else f"{THINK_OPEN}\n\n{THINK_CLOSE}\n\n"
    return out, images


class RawStream:
    """SSE splitter for a model whose output is plain text, markers and all.

    ``CompletionStream`` exists to separate Qwen's reasoning and tool-call
    protocol from the answer. A model that has neither -- PaddleOCR-VL writes
    OTSL, where ``<fcel>`` and ``<nl>`` *are* the content -- would have its tail
    held back on the chance it becomes a marker it never writes, and its
    whitespace stripped. This passes every accepted delta through unchanged and
    has nothing to flush.
    """

    def __init__(self) -> None:
        self.raw = ""

    def feed(self, text: str) -> list[tuple[str, str]]:
        self.raw += text
        return [("content", text)] if text else []

    def finish(self) -> list[tuple[str, str]]:
        return []


# --------------------------------------------------------------------------
# Parsing the model's output
# --------------------------------------------------------------------------
@dataclass
class ParsedCompletion:
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str = "stop"


def _schema_types(tools: Sequence[dict] | None) -> dict[str, dict[str, str]]:
    """function name -> {parameter name -> JSON Schema type}."""
    out: dict[str, dict[str, str]] = {}
    for tool in tools or []:
        fn = tool.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        props = (fn.get("parameters") or {}).get("properties") or {}
        types: dict[str, str] = {}
        for key, spec in props.items():
            kind = (spec or {}).get("type") if isinstance(spec, dict) else None
            if isinstance(kind, list):
                kind = next((k for k in kind if k != "null"), None)
            if isinstance(kind, str):
                types[key] = kind
        out[name] = types
    return out


def _convert(value: str, kind: str | None) -> Any:
    """Type a parsed parameter the way the tool's JSON Schema declares it.

    The model writes every parameter as text; an agent passing "3" where the
    schema says integer is a protocol error, so decode it here. A value that
    does not parse stays a string rather than failing the whole call.
    """
    if kind in (None, "string"):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return value


def parse_tool_calls(text: str, tools: Sequence[dict] | None = None) -> list[dict]:
    """Extract ``<tool_call>`` blocks from an assistant message.

    Returns [] when nothing parses: an unclosed or malformed call must reach the
    user as plain text, not as a 500 and not as a silently dropped answer.
    """
    if TOOL_CALL_OPEN not in text:
        return []
    if text.count(TOOL_CALL_OPEN) != text.count(TOOL_CALL_CLOSE):
        return []
    types = _schema_types(tools)
    calls: list[dict] = []
    for block in re.findall(
        re.escape(TOOL_CALL_OPEN) + "(.*?)" + re.escape(TOOL_CALL_CLOSE), text, re.DOTALL
    ):
        m = _FUNCTION_RE.search(block)
        if not m:
            return []
        name = m.group(1).strip()
        arguments: dict[str, Any] = {}
        param_types = types.get(name, {})
        for key, value in _PARAMETER_RE.findall(block[m.end():]):
            key = key.strip()
            arguments[key] = _convert(value, param_types.get(key))
        calls.append({
            "id": "call_" + secrets.token_hex(12),
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
        })
    return calls


def split_thinking(text: str, thinking: bool) -> tuple[str | None, str]:
    """Split raw model output into (reasoning, body)."""
    if not thinking:
        return None, text
    idx = text.find(THINK_CLOSE)
    if idx == -1:
        # Ran out of tokens (or the model never closed its think block): what we
        # have is all reasoning, and there is no answer yet.
        reasoning = text.strip()
        if reasoning.startswith(THINK_OPEN):
            reasoning = reasoning[len(THINK_OPEN):].strip()
        return (reasoning or None), ""
    reasoning = text[:idx].strip()
    if reasoning.startswith(THINK_OPEN):
        reasoning = reasoning[len(THINK_OPEN):].strip()
    return (reasoning or None), text[idx + len(THINK_CLOSE):]


def parse_completion(
    text: str,
    thinking: bool = False,
    tools: Sequence[dict] | None = None,
    finish_reason: str = "stop",
) -> ParsedCompletion:
    """Turn a finished generation into the OpenAI assistant message fields."""
    reasoning, body = split_thinking(text, thinking)
    calls = parse_tool_calls(body, tools)
    if calls:
        first = body.find(TOOL_CALL_OPEN)
        content = body[:first].strip() or None
        finish_reason = "tool_calls"
    elif thinking:
        content = body.strip()
    else:
        content = body
    return ParsedCompletion(content=content, reasoning_content=reasoning,
                            tool_calls=calls, finish_reason=finish_reason)


def _pending_prefix(text: str, marker: str) -> int:
    """Length of the suffix of ``text`` that may still become ``marker``."""
    for n in range(min(len(text), len(marker) - 1), 0, -1):
        if text.endswith(marker[:n]):
            return n
    return 0


class CompletionStream:
    """SSE splitter: raw model text in, reasoning/content pieces out.

    Two things make this stateful. The ``</think>`` and ``<tool_call>`` markers
    arrive spread over many deltas, so a tail that could still become one is
    held back instead of being sent as content and then retracted (impossible in
    SSE). And once a tool call starts, the rest of the call is protocol, not
    answer text, so it is parsed at the end rather than streamed.
    """

    def __init__(self, thinking: bool) -> None:
        self._reasoning_phase = thinking
        self._buf = ""
        self._in_tool = False
        # Whitespace around the reasoning and the answer is formatting, not
        # content: the non-streaming path strips it, so the stream holds it back
        # instead of sending something that cannot be retracted.
        self._reasoning_open = not thinking
        self._body_open = not thinking
        # A thinking answer is reported stripped, so its trailing whitespace is
        # dropped; without thinking the v0 contract is to pass the text through.
        self._strip_answer = thinking
        # Everything accepted from the backend, for the final parse.
        self.raw = ""

    @staticmethod
    def _open(started: bool, text: str) -> tuple[bool, str]:
        """Drop leading whitespace until the first visible character."""
        if started or not text:
            return started, text
        text = text.lstrip()
        return bool(text), text

    def _open_body(self, text: str) -> str:
        self._body_open, text = self._open(self._body_open, text)
        return text

    def feed(self, text: str) -> list[tuple[str, str]]:
        self.raw += text
        if self._in_tool:
            return []
        self._buf += text
        pieces: list[tuple[str, str]] = []
        if self._reasoning_phase:
            idx = self._buf.find(THINK_CLOSE)
            if idx == -1:
                hold = _pending_prefix(self._buf, THINK_CLOSE)
                head = self._buf[:len(self._buf) - hold]
                self._reasoning_open, head = self._open(self._reasoning_open, head)
                emit = head.rstrip()
                # A trailing newline may still be followed by more reasoning, so
                # it stays buffered rather than being sent as its own delta.
                self._buf = head[len(emit):] + self._buf[len(self._buf) - hold:]
                if emit:
                    pieces.append(("reasoning_content", emit))
                return pieces
            self._reasoning_open, reasoning = self._open(self._reasoning_open, self._buf[:idx])
            reasoning = reasoning.rstrip()
            self._buf = self._buf[idx + len(THINK_CLOSE):]
            self._reasoning_phase = False
            if reasoning:
                pieces.append(("reasoning_content", reasoning))
        idx = self._buf.find(TOOL_CALL_OPEN)
        if idx != -1:
            # Text before the call is the answer; the call itself is protocol.
            emit = self._open_body(self._buf[:idx]).rstrip() if self._strip_answer \
                else self._open_body(self._buf[:idx])
            if emit:
                pieces.append(("content", emit))
            self._in_tool = True
            self._buf = ""
            return pieces
        hold = _pending_prefix(self._buf, TOOL_CALL_OPEN)
        after = self._buf[len(self._buf) - hold:]
        self._body_open, head = self._open(self._body_open, self._buf[:len(self._buf) - hold])
        # Trailing whitespace stays buffered: it may be the start of a marker, or
        # of more answer, and SSE cannot take a delta back.
        emit = head.rstrip()
        self._buf = head[len(emit):] + after
        if emit:
            pieces.append(("content", emit))
        return pieces

    def finish(self) -> list[tuple[str, str]]:
        """Flush the tail: a partial marker that never completed is plain text."""
        if self._in_tool or not self._buf:
            return []
        out = []
        if self._reasoning_phase:
            if tail := self._open(self._reasoning_open, self._buf)[1].rstrip():
                out.append(("reasoning_content", tail))
        elif (tail := self._open_body(self._buf)):
            if self._strip_answer:
                tail = tail.rstrip()
            if tail:
                out.append(("content", tail))
        self._buf = ""
        return out
