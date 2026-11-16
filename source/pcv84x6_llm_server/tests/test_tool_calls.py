"""Function calling: template-exact rendering, output parsing, and the HTTP surface.

The rendering tests are a differential test against the model's own
``chat_template.jinja``: this service renders ChatML by hand (the worker has no
tokenizer chat template), and any byte it gets wrong costs a prefix-cache miss
on the board, so the template is the oracle.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.openai_api import build_prompt
from app.api.tool_calls import (
    CompletionStream,
    parse_completion,
    parse_tool_calls,
    render_messages,
    select_tools,
    validate_tools,
)
from app.main import create_app
from app.schemas import ChatMessage

try:
    import jinja2
except ImportError:  # pragma: no cover - dev-only dependency
    jinja2 = None

TEMPLATE = Path(__file__).parent / "data" / "qwen3_6_chat_template.jinja"
GENERATION_PROMPT = "<|im_start|>assistant\n"

requires_jinja2 = pytest.mark.skipif(
    jinja2 is None, reason="jinja2 is dev-only (requirements-dev.txt)")

WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}


# --------------------------------------------------------------------------
# Rendering: byte-for-byte against the model's chat template
# --------------------------------------------------------------------------
def _jinja_template():
    """The template as transformers renders it: same env options, same tojson."""
    def tojson(obj, ensure_ascii=False, indent=None, separators=None, sort_keys=False):
        return json.dumps(obj, ensure_ascii=ensure_ascii, indent=indent,
                          separators=separators, sort_keys=sort_keys)

    def raise_exception(message):
        raise ValueError(message)

    env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True,
                             extensions=["jinja2.ext.loopcontrols"])
    env.filters["tojson"] = tojson
    env.globals["raise_exception"] = raise_exception
    return env.from_string(TEMPLATE.read_text(encoding="utf-8"))


# Each case is (messages as plain dicts, tools). The template gets the dicts
# (that is what transformers passes it); the renderer gets ChatMessage objects.
RENDER_CASES = {
    "no-tools": ([
        {"role": "user", "content": "你好"},
    ], None),
    "system-no-tools": ([
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "你好"},
    ], None),
    "tools-with-system": ([
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "北京天气怎么样"},
    ], [WEATHER_TOOL]),
    "tools-without-system": ([
        {"role": "user", "content": "北京天气怎么样"},
    ], [WEATHER_TOOL]),
    "one-tool-call-empty-content": ([
        {"role": "user", "content": "北京天气怎么样"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"type": "function", "function": {"name": "get_weather",
                                              "arguments": {"city": "北京"}}}]},
        {"role": "tool", "content": "晴，25 度"},
    ], [WEATHER_TOOL]),
    "two-tool-calls-with-content": ([
        {"role": "user", "content": "北京和上海天气"},
        {"role": "assistant", "content": "我来查一下。", "tool_calls": [
            {"type": "function", "function": {"name": "get_weather",
                                              "arguments": {"city": "北京"}}},
            {"type": "function", "function": {"name": "get_weather",
                                              "arguments": {"city": "上海"}}}]},
        {"role": "tool", "content": "晴"},
        {"role": "tool", "content": "雨"},
    ], [WEATHER_TOOL]),
    "two-consecutive-tool-messages": ([
        {"role": "user", "content": "北京和上海天气"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"type": "function", "function": {"name": "get_weather",
                                              "arguments": {"city": "北京", "days": 3}}}]},
        {"role": "tool", "content": "晴"},
        {"role": "tool", "content": "雨"},
        {"role": "user", "content": "谢谢"},
    ], [WEATHER_TOOL]),
    "old-assistant-think-is-dropped": ([
        {"role": "user", "content": "第一个问题"},
        {"role": "assistant", "content": "旧思考</think>旧回答"},
        {"role": "user", "content": "第二个问题"},
        {"role": "assistant", "content": "新思考</think>新回答"},
        {"role": "user", "content": "第三个问题"},
    ], None),
    "assistant-reasoning-content": ([
        {"role": "user", "content": "第一个问题"},
        {"role": "assistant", "content": "答案", "reasoning_content": "因为……"},
        {"role": "user", "content": "第二个问题"},
    ], None),
}


@requires_jinja2
@pytest.mark.parametrize("name", sorted(RENDER_CASES))
@pytest.mark.parametrize("thinking", [False, True], ids=["thinking-off", "thinking-on"])
def test_rendering_matches_the_model_template(name, thinking):
    messages, tools = RENDER_CASES[name]
    expected = _jinja_template().render(
        messages=messages, tools=tools, add_generation_prompt=True,
        enable_thinking=thinking,
    )
    actual, images = render_messages(
        [ChatMessage(**m) for m in messages], tools=tools, enable_thinking=thinking)
    assert images == []
    assert actual == expected


def test_no_tools_keeps_the_v0_prompt_shape():
    """Regression guard: a request without tools must render exactly as before."""
    prompt, _ = build_prompt([ChatMessage(role="user", content="hi")])
    assert prompt == ("<|im_start|>user\nhi<|im_end|>\n"
                      "<|im_start|>assistant\n<think>\n\n</think>\n\n")


def test_a_tool_turn_only_extends_the_previous_prompt():
    """Prefix caching: turn N+1 must start with turn N's prompt.

    Tools go in the system block, so the cached prefix survives every turn of a
    tool conversation. If this breaks, every agent turn re-prefills the prompt.
    """
    first = [ChatMessage(role="system", content="You are helpful."),
             ChatMessage(role="user", content="北京天气怎么样")]
    second = first + [
        ChatMessage(role="assistant", content="", tool_calls=[
            {"type": "function", "function": {"name": "get_weather",
                                              "arguments": {"city": "北京"}}}]),
        ChatMessage(role="tool", content="晴，25 度", tool_call_id="call_x"),
    ]
    p1, _ = build_prompt(first, tools=[WEATHER_TOOL])
    p2, _ = build_prompt(second, tools=[WEATHER_TOOL])
    assert p1.endswith(GENERATION_PROMPT + "<think>\n\n</think>\n\n")
    assert p2.startswith(p1[: -len("<|im_start|>assistant\n<think>\n\n</think>\n\n")])


def test_multi_step_tool_conversation_renders_end_to_end():
    """The whole agent loop: ask, call, answer, ask again — all in one prompt."""
    messages = [
        ChatMessage(role="system", content="You are helpful."),
        ChatMessage(role="user", content="北京天气怎么样"),
        ChatMessage(role="assistant", content="", tool_calls=[
            {"type": "function", "function": {"name": "get_weather",
                                              "arguments": '{"city": "北京"}'}}]),
        ChatMessage(role="tool", content="晴，25 度", tool_call_id="call_abc"),
        ChatMessage(role="user", content="那上海呢"),
    ]
    prompt, _ = build_prompt(messages, tools=[WEATHER_TOOL])
    assert prompt.count("<tool_response>") == 1
    assert prompt.count("<|im_start|>user") == 3        # two questions + one tool turn
    assert "<function=get_weather>\n<parameter=city>\n北京\n</parameter>" in prompt
    assert prompt.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")


def test_system_message_must_come_first():
    with pytest.raises(ValueError, match="system message"):
        render_messages([ChatMessage(role="user", content="hi"),
                         ChatMessage(role="system", content="late")])


def test_json_string_arguments_render_like_a_dict():
    """OpenAI carries arguments as a JSON string; the template takes a dict."""
    as_dict = ChatMessage(role="assistant", content="", tool_calls=[
        {"type": "function", "function": {"name": "get_weather",
                                          "arguments": {"city": "北京", "days": 2}}}])
    as_string = ChatMessage(role="assistant", content="", tool_calls=[
        {"type": "function", "function": {"name": "get_weather",
                                          "arguments": '{"city": "北京", "days": 2}'}}])
    first = render_messages([ChatMessage(role="user", content="q"), as_dict],
                            tools=[WEATHER_TOOL])[0]
    second = render_messages([ChatMessage(role="user", content="q"), as_string],
                             tools=[WEATHER_TOOL])[0]
    assert first == second
    assert "<parameter=days>\n2\n</parameter>" in first


def test_an_empty_arguments_string_writes_no_parameters():
    message = ChatMessage(role="assistant", content="", tool_calls=[
        {"type": "function", "function": {"name": "get_time", "arguments": ""}}])
    prompt = render_messages([ChatMessage(role="user", content="q"), message],
                             tools=[WEATHER_TOOL])[0]
    assert "<function=get_time>\n</function>" in prompt


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def test_parse_a_single_call():
    text = ("<tool_call>\n<function=get_weather>\n<parameter=city>\n北京\n"
            "</parameter>\n</function>\n</tool_call>")
    calls = parse_tool_calls(text, [WEATHER_TOOL])
    assert len(calls) == 1
    call = calls[0]
    assert call["type"] == "function"
    assert call["function"]["name"] == "get_weather"
    assert json.loads(call["function"]["arguments"]) == {"city": "北京"}
    assert call["id"].startswith("call_") and len(call["id"]) == len("call_") + 24


def test_parse_two_calls_keeps_their_order():
    text = ("<tool_call>\n<function=get_weather>\n<parameter=city>\n北京\n</parameter>\n"
            "</function>\n</tool_call>\n"
            "<tool_call>\n<function=get_weather>\n<parameter=city>\n上海\n</parameter>\n"
            "</function>\n</tool_call>")
    calls = parse_tool_calls(text, [WEATHER_TOOL])
    assert [json.loads(c["function"]["arguments"])["city"] for c in calls] == ["北京", "上海"]
    assert calls[0]["id"] != calls[1]["id"]


def test_text_before_the_call_becomes_content():
    text = ("我查一下。\n<tool_call>\n<function=get_weather>\n<parameter=city>\n北京\n"
            "</parameter>\n</function>\n</tool_call>")
    parsed = parse_completion(text, tools=[WEATHER_TOOL])
    assert parsed.content == "我查一下。"
    assert parsed.finish_reason == "tool_calls"
    assert len(parsed.tool_calls) == 1
    assert parsed.reasoning_content is None


def test_call_only_has_no_content():
    text = ("<tool_call>\n<function=get_weather>\n<parameter=city>\n北京\n</parameter>\n"
            "</function>\n</tool_call>")
    assert parse_completion(text, tools=[WEATHER_TOOL]).content is None


def test_parameters_are_typed_like_the_tool_schema():
    tools = [{
        "type": "function",
        "function": {"name": "f", "parameters": {"type": "object", "properties": {
            "n": {"type": "integer"}, "x": {"type": "number"}, "b": {"type": "boolean"},
            "o": {"type": "object"}, "a": {"type": "array"}, "s": {"type": "string"},
        }}},
    }]
    text = ("<tool_call>\n<function=f>\n"
            "<parameter=n>\n3\n</parameter>\n"
            "<parameter=x>\n1.5\n</parameter>\n"
            "<parameter=b>\ntrue\n</parameter>\n"
            '<parameter=o>\n{"k": 1}\n</parameter>\n'
            "<parameter=a>\n[1, 2]\n</parameter>\n"
            "<parameter=s>\n42\n</parameter>\n"
            "<parameter=undeclared>\n7\n</parameter>\n"
            "</function>\n</tool_call>")
    args = json.loads(parse_tool_calls(text, tools)[0]["function"]["arguments"])
    assert args == {"n": 3, "x": 1.5, "b": True, "o": {"k": 1}, "a": [1, 2],
                    "s": "42",             # declared string: stays text
                    "undeclared": "7"}     # not in the schema: text, not guessed


def test_untyped_json_falls_back_to_the_raw_string():
    tools = [{"type": "function", "function": {"name": "f", "parameters": {
        "type": "object", "properties": {"n": {"type": "integer"}}}}}]
    text = ("<tool_call>\n<function=f>\n<parameter=n>\nnot a number\n</parameter>\n"
            "</function>\n</tool_call>")
    args = json.loads(parse_tool_calls(text, tools)[0]["function"]["arguments"])
    assert args == {"n": "not a number"}


def test_an_unclosed_call_returns_the_text_unchanged():
    text = ("北京今天晴。\n<tool_call>\n<function=get_weather>\n<parameter=city>\n北京")
    parsed = parse_completion(text, tools=[WEATHER_TOOL])
    assert parsed.tool_calls == []
    assert parsed.content == text
    assert parsed.finish_reason == "stop"


def test_thinking_and_a_call_are_split():
    text = ("用户想问天气。\n</think>\n我查一下。\n<tool_call>\n<function=get_weather>\n"
            "<parameter=city>\n北京\n</parameter>\n</function>\n</tool_call>")
    parsed = parse_completion(text, thinking=True, tools=[WEATHER_TOOL])
    assert parsed.reasoning_content == "用户想问天气。"
    assert parsed.content == "我查一下。"
    assert parsed.finish_reason == "tool_calls"


def test_thinking_that_never_closed_is_all_reasoning():
    parsed = parse_completion("想到一半就没了", thinking=True)
    assert parsed.reasoning_content == "想到一半就没了"
    assert parsed.content == ""
    assert parsed.tool_calls == []


def test_thinking_off_treats_everything_as_content():
    parsed = parse_completion("普通回答")
    assert parsed.reasoning_content is None
    assert parsed.content == "普通回答"


# --------------------------------------------------------------------------
# Streaming splitter
# --------------------------------------------------------------------------
def test_stream_never_leaks_a_partial_tool_call():
    """The marker arrives in pieces; content must never contain a fragment."""
    stream = CompletionStream(thinking=False)
    pieces, emitted = [], ""
    for delta in ["我查一", "下。<tool", "_call>\n<function=get_weather>\n",
                  "<parameter=city>\n北京\n</parameter>\n</function>\n</tool_call>"]:
        for kind, text in stream.feed(delta):
            pieces.append((kind, text))
            emitted += text
    for kind, text in stream.finish():
        pieces.append((kind, text))
        emitted += text
    assert emitted == "我查一下。"
    assert "<" not in emitted
    calls = parse_completion(stream.raw, tools=[WEATHER_TOOL]).tool_calls
    assert [json.loads(c["function"]["arguments"])["city"] for c in calls] == ["北京"]


def test_stream_holds_back_the_think_marker():
    stream = CompletionStream(thinking=True)
    pieces = []
    for delta in ["思考中</thi", "nk>\n\n答案"]:
        pieces.extend(stream.feed(delta))
    pieces.extend(stream.finish())
    assert pieces == [("reasoning_content", "思考中"),
                      ("content", "答案")]


def test_streamed_and_non_streamed_answers_agree():
    """A client that switches between stream and no-stream must see one answer."""
    text = "\n想一想。\n\n</think>\n\n\n北京晴。\n"
    stream = CompletionStream(thinking=True)
    pieces = []
    for i in range(0, len(text), 3):
        pieces.extend(stream.feed(text[i:i + 3]))
    pieces.extend(stream.finish())
    streamed = {kind: "".join(piece for k, piece in pieces if k == kind)
                for kind in ("reasoning_content", "content")}
    parsed = parse_completion(text, thinking=True)
    assert streamed["reasoning_content"] == parsed.reasoning_content
    assert streamed["content"] == parsed.content


# --------------------------------------------------------------------------
# HTTP surface, against a scripted backend
# --------------------------------------------------------------------------
class ScriptedClient:
    """Stands in for a worker: replays fixed pieces, records the prompt."""

    def __init__(self, pieces, finish_reason="stop"):
        self.pieces = pieces
        self.finish_reason = finish_reason
        self.prompts: list[str] = []
        self.cancelled: list[str] = []

    async def generate(self, req_id, prompt, params, images=None):
        self.prompts.append(prompt)
        yield {"op": "meta", "prompt_tokens": 42, "cached_tokens": 0}
        for piece in self.pieces:
            yield {"op": "delta", "text": piece}
        yield {"op": "done", "finish_reason": self.finish_reason,
               "prompt_tokens": 42, "completion_tokens": len(self.pieces),
               "cached_tokens": 0}

    async def cancel(self, req_id):
        self.cancelled.append(req_id)

    async def close(self):
        pass


def make_model(root: Path, name: str):
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{name}-int4_w4bf16_seq2048_4core_dynamic.bmodel").write_bytes(b"\x00" * 1024)
    (d / "config" / "config.json").write_text("{}")
    return d


@pytest.fixture()
def scripted(tmp_path):
    """(TestClient, api key, ScriptedClient) with the model marked loaded."""
    models = tmp_path / "models"
    make_model(models, "test-model")
    app = create_app(data_dir=tmp_path / "data", models_dir=models,
                     backend_kind="mock", web_dir=tmp_path / "web",
                     context_length_override=4096)
    fake = ScriptedClient(["placeholder"])
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        info = app.state.models.get("test-model")
        info.loaded = True          # no worker process: the client below is the backend
        app.state.clients["test-model"] = fake
        key = c.post("/api/keys", json={"name": "pytest"}).json()["key"]
        yield c, {"Authorization": f"Bearer {key}"}, fake


TOOL_CALL_TEXT = ("我查一下。\n<tool_call>\n<function=get_weather>\n<parameter=city>\n北京\n"
                  "</parameter>\n</function>\n</tool_call>")


def test_non_streaming_returns_tool_calls(scripted):
    client, headers, fake = scripted
    fake.pieces = ["我查一下。\n", "<tool_call>\n<function=get_weather>\n",
                   "<parameter=city>\n北京\n</parameter>\n</function>\n</tool_call>"]
    r = client.post("/v1/chat/completions", headers=headers, json={
        "model": "test-model",
        "messages": [{"role": "user", "content": "北京天气怎么样"}],
        "tools": [WEATHER_TOOL], "max_tokens": 64,
    })
    assert r.status_code == 200, r.text
    choice = r.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    message = choice["message"]
    assert message["content"] == "我查一下。"
    assert "reasoning_content" not in message      # thinking is off
    assert len(message["tool_calls"]) == 1
    assert message["tool_calls"][0]["function"]["name"] == "get_weather"
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {"city": "北京"}
    # The tools reached the prompt, so the model can actually see them.
    assert "You have access to the following functions" in fake.prompts[0]
    assert '"name": "get_weather"' in fake.prompts[0]


def test_non_streaming_reports_reasoning_content(scripted):
    client, headers, fake = scripted
    fake.pieces = ["先想一下。\n</think>\n北京晴。"]
    r = client.post("/v1/chat/completions", headers=headers, json={
        "model": "test-model",
        "messages": [{"role": "user", "content": "北京天气怎么样"}],
        "enable_thinking": True, "max_tokens": 64,
    })
    assert r.status_code == 200, r.text
    message = r.json()["choices"][0]["message"]
    assert message["reasoning_content"] == "先想一下。"
    assert message["content"] == "北京晴。"
    assert "tool_calls" not in message
    assert fake.prompts[0].endswith("<|im_start|>assistant\n<think>\n")


def test_streaming_sends_tool_calls_as_their_own_delta(scripted):
    client, headers, fake = scripted
    fake.pieces = ["我查", "一下。", "<tool", "_call>\n<function=get_weather>\n",
                   "<parameter=city>\n北京\n</parameter>\n</function>\n</tool_call>"]
    with client.stream("POST", "/v1/chat/completions", headers=headers, json={
        "model": "test-model",
        "messages": [{"role": "user", "content": "北京天气怎么样"}],
        "tools": [WEATHER_TOOL], "stream": True, "max_tokens": 64,
    }) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    chunks = [json.loads(line[6:]) for line in body.splitlines()
              if line.startswith("data: ") and "[DONE]" not in line]

    content = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"])
    assert content == "我查一下。"
    assert "<tool" not in content and "tool_call" not in content

    tool_chunks = [c for c in chunks if c["choices"]
                   and c["choices"][0]["delta"].get("tool_calls")]
    assert len(tool_chunks) == 1
    delta = tool_chunks[0]["choices"][0]["delta"]["tool_calls"][0]
    assert delta["index"] == 0 and delta["type"] == "function"
    assert delta["id"].startswith("call_")
    assert delta["function"]["name"] == "get_weather"
    assert json.loads(delta["function"]["arguments"]) == {"city": "北京"}

    finishes = [c["choices"][0]["finish_reason"] for c in chunks
                if c["choices"] and c["choices"][0]["finish_reason"]]
    assert finishes == ["tool_calls"]
    assert any(c.get("usage") for c in chunks)
    assert body.rstrip().endswith("data: [DONE]")


def test_streaming_reports_reasoning_content(scripted):
    client, headers, fake = scripted
    fake.pieces = ["先想", "一下。", "</think>", "\n北京晴。"]
    with client.stream("POST", "/v1/chat/completions", headers=headers, json={
        "model": "test-model",
        "messages": [{"role": "user", "content": "北京天气怎么样"}],
        "enable_thinking": True, "stream": True, "max_tokens": 64,
    }) as r:
        body = "".join(r.iter_text())
    chunks = [json.loads(line[6:]) for line in body.splitlines()
              if line.startswith("data: ") and "[DONE]" not in line]
    reasoning = "".join(c["choices"][0]["delta"].get("reasoning_content", "")
                        for c in chunks if c["choices"])
    content = "".join(c["choices"][0]["delta"].get("content", "")
                      for c in chunks if c["choices"])
    assert reasoning == "先想一下。"
    assert content == "北京晴。"
    assert "</think>" not in reasoning + content


def test_tool_choice_none_offers_no_tools(scripted):
    client, headers, fake = scripted
    fake.pieces = ["北京晴。"]
    r = client.post("/v1/chat/completions", headers=headers, json={
        "model": "test-model",
        "messages": [{"role": "user", "content": "北京天气怎么样"}],
        "tools": [WEATHER_TOOL], "tool_choice": "none", "max_tokens": 16,
    })
    assert r.status_code == 200, r.text
    assert "# Tools" not in fake.prompts[0]


def test_tool_choice_naming_a_function_offers_only_that_one(scripted):
    client, headers, fake = scripted
    other = {"type": "function", "function": {"name": "get_time", "parameters": {
        "type": "object", "properties": {}}}}
    r = client.post("/v1/chat/completions", headers=headers, json={
        "model": "test-model",
        "messages": [{"role": "user", "content": "现在几点"}],
        "tools": [WEATHER_TOOL, other],
        "tool_choice": {"type": "function", "function": {"name": "get_time"}},
        "max_tokens": 16,
    })
    assert r.status_code == 200, r.text
    assert '"name": "get_time"' in fake.prompts[0]
    assert '"name": "get_weather"' not in fake.prompts[0]


def test_malformed_tools_are_a_400(scripted):
    client, headers, _ = scripted
    for tools in ([{"type": "function", "function": {"description": "no name"}}],
                  [{"type": "not-a-function", "function": {"name": "f"}}],
                  ["nope"]):
        r = client.post("/v1/chat/completions", headers=headers, json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": tools,
        })
        assert r.status_code == 400, (tools, r.text)


def test_tool_choice_naming_an_unknown_function_is_a_400(scripted):
    client, headers, _ = scripted
    r = client.post("/v1/chat/completions", headers=headers, json={
        "model": "test-model",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [WEATHER_TOOL],
        "tool_choice": {"type": "function", "function": {"name": "does_not_exist"}},
    })
    assert r.status_code == 400
    assert "does_not_exist" in r.text


def test_validate_and_select_helpers():
    assert validate_tools(None) == []
    assert validate_tools([WEATHER_TOOL]) == [WEATHER_TOOL]
    with pytest.raises(ValueError):
        validate_tools([{"type": "function"}])
    assert select_tools([WEATHER_TOOL], None) == [WEATHER_TOOL]
    assert select_tools([WEATHER_TOOL], "auto") == [WEATHER_TOOL]
    assert select_tools([WEATHER_TOOL], "required") == [WEATHER_TOOL]
    assert select_tools([WEATHER_TOOL], "none") == []
    assert select_tools(None, "auto") == []
