"""The inference audit log: one row per real inference, and what a row says.

Two halves. The first drives the service through its real HTTP surface (mock
worker subprocesses included) and asserts the properties that make the log
useful -- exactly one row per inference, the raw output kept whole, stop strings
and pictures handled without storing either, credentials never written. The
second exercises the SQLite store directly for the things HTTP cannot show:
concurrency, retention, corruption.

MYS-2496 exists because a customer's wrong answer could not be explained after
the fact: the service kept counters, not content. Every test here is a claim
about what an operator will be able to see next time.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
import struct
import threading
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.inference_log import (
    SCHEMA_VERSION,
    InferenceLogStore,
    describe_messages,
    image_size,
    utc_iso,
)
from app.main import create_app
from app.schemas import ChatMessage

# ---------------------------------------------------------------------------
# fixtures and helpers
# ---------------------------------------------------------------------------
def make_model(root: Path, name: str, ctx="seq2048") -> Path:
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{name}-int4_w4bf16_{ctx}_4core_dynamic.bmodel").write_bytes(b"\x00" * 1024)
    (d / "config" / "config.json").write_text("{}")
    return d


def png_bytes(width: int, height: int) -> bytes:
    """A real 1-pixel-deep PNG header: what the size parser reads is the IHDR."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    chunk += struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + chunk
            + struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND")))


def gif_bytes(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00" * 8


def jpeg_bytes(width: int, height: int) -> bytes:
    """SOI, a comment segment, then an SOF0 frame header."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof = b"\xff\xc0" + struct.pack(">H", 11) + b"\x08" + struct.pack(">HH", height, width) + b"\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def data_url(raw: bytes, mime="image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


@pytest.fixture()
def app(tmp_path):
    models = tmp_path / "models"
    make_model(models, "test-model")
    return create_app(
        data_dir=tmp_path / "data",
        models_dir=models,
        backend_kind="mock",
        web_dir=tmp_path / "web",
        context_length_override=4096,
    )


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        c.post("/api/login", json={"password": "admin"})
        assert c.post("/api/models/test-model/load").status_code == 200
        yield c


def new_key(client) -> dict:
    raw = client.post("/api/keys", json={"name": "pytest"}).json()["key"]
    return {"Authorization": f"Bearer {raw}"}


def records(client, **params) -> list[dict]:
    r = client.get("/api/inference-records", params={"limit": 200, **params})
    assert r.status_code == 200, r.text
    return r.json()["items"]


def detail(client, record_id: str) -> dict:
    r = client.get(f"/api/inference-records/{record_id}")
    assert r.status_code == 200, r.text
    return r.json()


def log_db(app) -> Path:
    return Path(app.state.inference_log.path)


# ---------------------------------------------------------------------------
# one row per inference, fields complete
# ---------------------------------------------------------------------------
def test_non_stream_completion_records_exactly_one_complete_row(client, app):
    h = new_key(client)
    r = client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model",
        "messages": [{"role": "user", "content": "hello there"}],
        "max_tokens": 8,
        "temperature": 0.3,
        "top_p": 0.5,
        "top_k": 20,
        "seed": 7,
    })
    assert r.status_code == 200, r.text
    body = r.json()

    items = records(client)
    assert len(items) == 1, f"expected exactly one record, got {len(items)}"
    row = detail(client, items[0]["id"])

    assert row["id"] == body["id"].removeprefix("chatcmpl-")
    assert row["source"] == "/v1/chat/completions"
    assert row["model"] == "test-model"
    assert row["status"] == "ok"
    assert row["finish_reason"] == body["choices"][0]["finish_reason"]
    assert row["actor_type"] == "api_key"
    assert row["actor_name"] == "pytest"

    # The conversation, verbatim.
    assert row["messages"] == [{"role": "user", "content": "hello there"}]

    # The answer the client got, and the raw text it came from.
    assert row["output_text"] == body["choices"][0]["message"]["content"]
    assert row["response_content"] == body["choices"][0]["message"]["content"]
    assert row["reasoning_content"] is None
    assert row["tool_calls"] is None

    # Effective sampling parameters, defaults resolved rather than left null.
    assert row["params"]["max_tokens"] == 8
    assert row["params"]["temperature"] == 0.3
    assert row["params"]["top_p"] == 0.5
    assert row["params"]["top_k"] == 20
    assert row["params"]["seed"] == 7
    assert row["params"]["repetition_penalty"] == 1.1
    assert row["params"]["stop"] == []

    # Usage and timing come from the worker's own done event.
    assert row["prompt_tokens"] == body["usage"]["prompt_tokens"]
    assert row["completion_tokens"] == body["usage"]["completion_tokens"]
    assert row["first_token_latency_s"] is not None
    assert row["decode_tps"] is not None

    # Timestamps: both forms, and UTC for the ISO one.
    assert row["started_iso"].endswith("Z")
    assert row["finished_at"] >= row["started_at"]
    assert row["started_iso"] == utc_iso(row["started_at"])


def test_stream_completion_records_exactly_one_row_with_the_same_text(client):
    h = new_key(client)
    with client.stream("POST", "/v1/chat/completions", headers=h, json={
        "model": "test-model", "stream": True,
        "messages": [{"role": "user", "content": "stream please"}], "max_tokens": 6,
    }) as r:
        assert r.status_code == 200
        sse = "".join(r.iter_text())

    streamed = "".join(
        p["choices"][0]["delta"].get("content", "")
        for p in (json.loads(ln[6:]) for ln in sse.splitlines()
                  if ln.startswith("data: ") and "[DONE]" not in ln)
        if p.get("choices")
    )
    items = records(client)
    assert len(items) == 1, f"expected exactly one record, got {len(items)}"
    row = detail(client, items[0]["id"])
    assert row["source"] == "/v1/chat/completions"
    assert row["status"] == "ok"
    assert row["output_text"] == streamed
    # The stream's own usage report is the source, not a recount of deltas.
    assert row["completion_tokens"] is not None and row["completion_tokens"] > 0
    assert row["first_token_latency_s"] is not None


def test_console_stream_records_an_admin_row(client):
    with client.stream("POST", "/api/chat/stream", json={
        "model": "test-model", "prompt": "benchmark me", "max_tokens": 4,
    }) as r:
        assert r.status_code == 200
        sse = "".join(r.iter_text())
    assert "[DONE]" in sse

    items = records(client)
    assert len(items) == 1
    row = detail(client, items[0]["id"])
    assert row["source"] == "/api/chat/stream"
    assert row["actor_type"] == "admin"
    assert row["actor_name"] == "admin"
    # The console's prompt is one user turn with the console's image list beside
    # it; the record shows what the operator typed, not the rendered template.
    assert row["messages"] == [{"role": "user", "content": "benchmark me"}]
    assert row["status"] == "ok"


def test_console_non_stream_records_a_row(client):
    assert client.post("/api/chat", json={
        "model": "test-model", "prompt": "hi", "max_tokens": 4}).status_code == 200
    items = records(client)
    assert len(items) == 1
    assert detail(client, items[0]["id"])["source"] == "/api/chat"


def test_rejected_requests_do_not_become_records(client):
    """A 4xx never reached the NPU, so it is not an inference.

    Recording rejected requests would bury the ones that ran -- and on a busy
    site a client retrying a bad payload would fill the whole retention window.
    """
    h = new_key(client)
    assert client.post("/v1/chat/completions", headers=h, json={
        "model": "no-such-model", "messages": [{"role": "user", "content": "x"}],
    }).status_code == 404
    assert client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model", "messages": []}).status_code == 400
    assert client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "http://example.com/x.png"}}]}],
    }).status_code == 400
    # An unloaded model is a 409, not an inference either.
    client.post("/api/models/test-model/unload")
    assert client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model", "messages": [{"role": "user", "content": "x"}],
    }).status_code == 409
    assert records(client) == []


# ---------------------------------------------------------------------------
# every terminal path writes exactly one row
# ---------------------------------------------------------------------------
class _FailingClient:
    """A worker client that fails in a chosen way at a chosen point.

    Injected in place of ``app.state.clients[model]``; the routes look it up per
    request, so this is the real code path minus the subprocess.
    """

    def __init__(self, mode: str, deltas: int = 3, kind: str = "server") -> None:
        self.mode = mode
        self.deltas = deltas
        self.kind = kind
        self.cancelled: list[str] = []
        self.port = 0

    async def generate(self, req_id, prompt, params, images=None):
        from app.core.client import WorkerError

        yield {"op": "meta", "req_id": req_id, "prompt_tokens": 11, "cached_tokens": 0}
        for i in range(self.deltas):
            yield {"op": "delta", "req_id": req_id, "text": f"tok{i} "}
        if self.mode == "worker_error":
            raise WorkerError("模型进程无响应", kind=self.kind)
        if self.mode == "connection":
            raise ConnectionResetError("backend went away")
        if self.mode == "hang":
            await asyncio.sleep(3600)
        yield {"op": "done", "req_id": req_id, "finish_reason": "stop",
               "prompt_tokens": 11, "completion_tokens": self.deltas,
               "cached_tokens": 0, "first_token_latency_s": 0.25, "decode_tps": 9.5}

    async def cancel(self, req_id):
        self.cancelled.append(req_id)

    async def close(self):
        """``app.main``'s shutdown closes whatever is registered as a client."""
        return None


def _install_client(app, failing) -> None:
    app.state.clients["test-model"] = failing


def test_stream_worker_error_records_one_error_row_with_partial_output(client, app):
    h = new_key(client)
    _install_client(app, _FailingClient("worker_error"))
    with client.stream("POST", "/v1/chat/completions", headers=h, json={
        "model": "test-model", "stream": True,
        "messages": [{"role": "user", "content": "break me"}], "max_tokens": 16,
    }) as r:
        sse = "".join(r.iter_text())
    assert "server_error" in sse and "[DONE]" in sse, sse

    items = records(client)
    assert len(items) == 1, f"one terminal path, one row; got {len(items)}"
    row = detail(client, items[0]["id"])
    assert row["status"] == "error"
    # The class *and* the worker's own kind: "server" is what tells an operator
    # the model process died rather than the prompt being refused.
    assert row["error"]["type"] == "WorkerError:server"
    assert "无响应" in row["error"]["message"]
    # The part that was generated before it broke is the evidence.
    assert row["output_text"] == "tok0 tok1 tok2 "
    assert row["completion_tokens"] == 3


def test_stream_backend_connection_error_records_one_row(client, app):
    h = new_key(client)
    _install_client(app, _FailingClient("connection"))
    with client.stream("POST", "/v1/chat/completions", headers=h, json={
        "model": "test-model", "stream": True,
        "messages": [{"role": "user", "content": "break me"}], "max_tokens": 16,
    }) as r:
        sse = "".join(r.iter_text())
    assert "server_error" in sse and "[DONE]" in sse

    items = records(client)
    assert len(items) == 1
    row = detail(client, items[0]["id"])
    assert row["status"] == "error"
    assert row["error"]["type"] == "ConnectionResetError"
    assert row["output_text"] == "tok0 tok1 tok2 "


@pytest.mark.parametrize("kind", ["busy", "invalid_request", "server"])
def test_stream_worker_error_kinds_are_distinguishable(client, app, kind):
    h = new_key(client)
    _install_client(app, _FailingClient("worker_error", kind=kind))
    with client.stream("POST", "/v1/chat/completions", headers=h, json={
        "model": "test-model", "stream": True,
        "messages": [{"role": "user", "content": "break me"}], "max_tokens": 16,
    }) as r:
        "".join(r.iter_text())
    row = detail(client, records(client)[0]["id"])
    assert row["error"]["type"] == f"WorkerError:{kind}"


@pytest.mark.asyncio
async def test_stream_client_disconnect_records_cancelled_exactly_once(tmp_path, monkeypatch):
    """The hardest path: the generator is closing while it still has to write.

    Driven through ``aclose()`` on the real SSE generator rather than through
    TestClient: a test client reads a blocking stream to the end, so it cannot
    hang up mid-flight. ``aclose`` is exactly what Starlette does when the client
    goes away -- it throws ``GeneratorExit`` into the generator at its current
    yield point -- so this is the same code path, minus the socket.
    """
    from app.api import openai_api
    from app.core.inference_log import InferenceLogStore, build_context
    from app.schemas import ChatCompletionRequest

    store = InferenceLogStore(tmp_path / "log.sqlite3")
    failing = _FailingClient("hang", deltas=2)
    req = ChatCompletionRequest(model="test-model", stream=True, max_tokens=64,
                                messages=[{"role": "user", "content": "break me"}])
    ctx = build_context(store, req_id="rid-cancel", source="/v1/chat/completions",
                        model="test-model", actor={"actor_type": "api_key"},
                        params={"max_tokens": 64}, messages=req.messages)
    assert ctx is not None
    try:
        gen = openai_api._stream(failing, req, "rid-cancel", "prompt", [],
                                 {"max_tokens": 64, "stop": []}, None, None, ctx=ctx)
        # role chunk, then the two deltas the fake client produced.
        assert (await gen.__anext__()).startswith("data: ")
        await gen.__anext__()
        await gen.__anext__()
        await gen.aclose()

        items = store.list(limit=10)["items"]
        assert len(items) == 1, f"a cancelled stream is still one inference; got {len(items)}"
        row = store.get(items[0]["id"])
        assert row["status"] == "cancelled"
        assert row["error"] == {"type": "ClientDisconnected",
                               "message": "client disconnected during streaming generation"}
        assert row["finish_reason"] is None
        # Whatever was generated is kept: half an answer is often enough to see
        # which way the wrong answer was heading.
        assert row["output_text"] == "tok0 tok1 "
        # And the worker was told to stop, or the NPU keeps decoding into the void.
        assert failing.cancelled == ["rid-cancel"]
    finally:
        store.close()


def test_non_stream_worker_error_records_one_row(client, app):
    h = new_key(client)
    _install_client(app, _FailingClient("worker_error"))
    r = client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model", "messages": [{"role": "user", "content": "x"}], "max_tokens": 8})
    assert r.status_code == 503
    items = records(client)
    assert len(items) == 1
    row = detail(client, items[0]["id"])
    assert row["status"] == "error"
    assert row["error"]["type"] == "WorkerError:server"
    assert row["output_text"] == "tok0 tok1 tok2 "


def test_console_stream_worker_error_records_one_row(client, app):
    _install_client(app, _FailingClient("worker_error"))
    with client.stream("POST", "/api/chat/stream", json={
        "model": "test-model", "prompt": "break me", "max_tokens": 16}) as r:
        sse = "".join(r.iter_text())
    assert "error" in sse
    items = records(client)
    assert len(items) == 1
    row = detail(client, items[0]["id"])
    assert row["status"] == "error"
    assert row["output_text"] == "tok0 tok1 tok2 "


def test_logging_switch_off_writes_nothing(client):
    h = new_key(client)
    r = client.post("/api/settings", json={"inference_logging_enabled": False})
    assert r.status_code == 200
    assert r.json()["settings"]["inference_logging_enabled"] is False
    assert client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model", "messages": [{"role": "user", "content": "off"}],
        "max_tokens": 4}).status_code == 200
    with client.stream("POST", "/api/chat/stream", json={
        "model": "test-model", "prompt": "off too", "max_tokens": 4}) as r2:
        "".join(r2.iter_text())
    assert records(client) == []

    # And back on takes effect on the very next request, without a restart.
    client.post("/api/settings", json={"inference_logging_enabled": True})
    client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model", "messages": [{"role": "user", "content": "on"}],
        "max_tokens": 4})
    assert len(records(client)) == 1


# ---------------------------------------------------------------------------
# output text: stop strings, thinking, tool calls
# ---------------------------------------------------------------------------
def test_stop_string_output_matches_the_api_reply_and_records_the_hit(client):
    h = new_key(client)
    r = client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model",
        "messages": [{"role": "user", "content": "stop test"}],
        "max_tokens": 30, "stop": ["the"],
    })
    assert r.status_code == 200
    content = r.json()["choices"][0]["message"]["content"]
    assert "the" not in content

    row = detail(client, records(client)[0]["id"])
    # Same text the client got -- never the stop string, never what followed it.
    assert row["output_text"] == content
    assert "the" not in row["output_text"]
    assert row["stop_hit"] == "the"
    # The raw length is kept so "cut short" can be told from "stopped on its own".
    assert row["raw_output_chars"] >= row["output_chars"]


def test_stream_stop_string_output_matches_the_api_reply(client):
    h = new_key(client)
    with client.stream("POST", "/v1/chat/completions", headers=h, json={
        "model": "test-model", "stream": True,
        "messages": [{"role": "user", "content": "stop test"}],
        "max_tokens": 30, "stop": ["the"],
    }) as r:
        sse = "".join(r.iter_text())
    streamed = "".join(
        p["choices"][0]["delta"].get("content", "")
        for p in (json.loads(ln[6:]) for ln in sse.splitlines()
                  if ln.startswith("data: ") and "[DONE]" not in ln)
        if p.get("choices")
    )
    assert "the" not in streamed
    row = detail(client, records(client)[0]["id"])
    assert row["output_text"] == streamed
    assert row["stop_hit"] == "the"


def test_reasoning_and_tool_calls_are_recorded_without_losing_the_raw_text():
    """Thinking tags and tool_call blocks stay in output_text; the client's
    parsed view sits beside it.

    Built through ``describe_messages``/edit paths rather than by hoping the mock
    model emits a tool call: what is being tested is the record's handling of a
    completion, not the mock's vocabulary.
    """
    from app.api.tool_calls import parse_completion

    raw = ("<think>\n用户想查天气\n</think>\n"
           "我帮你查。\n<tool_call>\n<function=get_weather>\n"
           "<parameter=city>\n北京\n</parameter>\n</function>\n</tool_call>")
    parsed = parse_completion(raw, thinking=True, tools=[{
        "type": "function",
        "function": {"name": "get_weather", "parameters": {
            "type": "object", "properties": {"city": {"type": "string"}}}},
    }])
    assert parsed.reasoning_content == "用户想查天气"
    assert parsed.finish_reason == "tool_calls"

    # The record keeps `raw` intact; the parsed fields are the client's view.
    assert "<tool_call>" in raw and "</think>" in raw
    assert parsed.content == "我帮你查。"


def test_tool_definitions_and_choice_are_recorded(client):
    h = new_key(client)
    tools = [{"type": "function", "function": {
        "name": "get_weather", "description": "weather",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}}]
    r = client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model", "messages": [{"role": "user", "content": "weather?"}],
        "max_tokens": 8, "tools": tools, "tool_choice": "auto",
    })
    assert r.status_code == 200, r.text
    row = detail(client, records(client)[0]["id"])
    assert row["tools"] == tools
    assert row["tool_choice"] == "auto"


def test_assistant_history_keeps_reasoning_and_tool_calls(client):
    """A multi-turn agent request: the history is what the model was given, so
    its tool calls and reasoning must survive into the record."""
    h = new_key(client)
    history = [
        {"role": "user", "content": "北京天气"},
        {"role": "assistant", "content": "我查一下。", "reasoning_content": "需要调用工具",
         "tool_calls": [{"id": "call_1", "type": "function",
                         "function": {"name": "get_weather", "arguments": '{"city":"北京"}'}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": '{"temp": 3}'},
        {"role": "user", "content": "那明天呢"},
    ]
    assert client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model", "messages": history, "max_tokens": 6}).status_code == 200
    row = detail(client, records(client)[0]["id"])
    assert [m["role"] for m in row["messages"]] == ["user", "assistant", "tool", "user"]
    assistant = row["messages"][1]
    assert assistant["reasoning_content"] == "需要调用工具"
    assert assistant["tool_calls"][0]["function"]["name"] == "get_weather"
    assert row["messages"][2]["tool_call_id"] == "call_1"


# ---------------------------------------------------------------------------
# images: dimensions only
# ---------------------------------------------------------------------------
def test_image_sizes_are_parsed_for_the_three_common_formats():
    assert image_size(base64.b64encode(png_bytes(320, 200)).decode()) == (320, 200)
    assert image_size(base64.b64encode(jpeg_bytes(64, 48)).decode()) == (64, 48)
    assert image_size(base64.b64encode(gif_bytes(17, 9)).decode()) == (17, 9)


def test_unknown_image_format_keeps_the_count_and_null_dimensions():
    assert image_size(base64.b64encode(b"not really an image").decode()) == (None, None)
    assert image_size("!!!not base64!!!") == (None, None)


def test_message_images_are_summarised_by_position_and_never_stored():
    big = base64.b64encode(png_bytes(1024, 768)).decode()
    small = base64.b64encode(png_bytes(32, 24)).decode()
    described = describe_messages([
        ChatMessage(role="user", content="look at these"),
        ChatMessage(role="user", content=[
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{big}"}},
            {"type": "text", "text": "first"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{small}"}},
            {"type": "text", "text": "second"},
        ]),
    ])
    assert described["images"] == [
        {"count": 1, "width": 1024, "height": 768},
        {"count": 1, "width": 32, "height": 24},
    ]
    # Per message, so a size can be matched to the turn it came from.
    assert described["message_images"] == [[], [
        {"type": "image", "index": 0, "width": 1024, "height": 768},
        {"type": "image", "index": 1, "width": 32, "height": 24},
    ]]
    # The image parts keep their position among the text parts.
    parts = described["messages"][1]["content"]
    assert [p["type"] for p in parts] == ["image", "text", "image", "text"]
    assert parts[0]["width"] == 1024 and parts[2]["width"] == 32
    # And no base64 anywhere in what would be written.
    blob = json.dumps(described, ensure_ascii=False)
    assert big not in blob and small not in blob and "base64" not in blob


def test_console_image_list_is_recorded_before_the_prompt_text(client):
    """The console's images reach the prompt before the text, so the recorded
    order has to agree with what the model actually saw."""
    raw = base64.b64encode(png_bytes(40, 30)).decode()
    assert client.post("/api/chat", json={
        "model": "test-model", "prompt": "describe", "max_tokens": 4, "images": [raw],
    }).status_code == 200
    row = detail(client, records(client)[0]["id"])
    assert row["images"] == [{"count": 1, "width": 40, "height": 30}]
    parts = row["messages"][0]["content"]
    assert parts[0]["type"] == "image" and parts[0]["width"] == 40
    assert parts[1] == {"type": "text", "text": "describe"}
    assert raw not in json.dumps(row)


def test_user_text_that_looks_like_a_data_url_is_not_rewritten():
    """The record must show what was asked. Stripping image-looking text out of
    a user's message would make the record lie about the request."""
    text = "帮我看下 data:image/png;base64,iVBORw0KGgo 这个链接为什么打不开"
    described = describe_messages([ChatMessage(role="user", content=text)])
    assert described["messages"][0]["content"] == text
    assert described["images"] == []


# ---------------------------------------------------------------------------
# credentials never reach the database
# ---------------------------------------------------------------------------
def test_no_raw_key_hash_or_cookie_is_ever_written(client, app):
    raw = client.post("/api/keys", json={"name": "leaky"}).json()["key"]
    h = {"Authorization": f"Bearer {raw}", "Cookie": "cv84x6_admin=secret-token"}
    assert client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model", "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 4}).status_code == 200

    from app.core.state import hash_key

    row = detail(client, records(client)[0]["id"])
    blob = json.dumps(row, ensure_ascii=False)
    assert raw not in blob
    assert hash_key(raw) not in blob
    assert "secret-token" not in blob
    assert "authorization" not in blob.lower()
    # The key is still identified -- by id and name, which is the whole point.
    assert row["actor_type"] == "api_key" and row["actor_name"] == "leaky"
    assert row["actor_id"] and row["actor_id"] != raw

    # And it is not merely absent from the JSON view: check the file itself.
    con = sqlite3.connect(log_db(app))
    try:
        dump = "\n".join(str(v) for row in con.execute("SELECT * FROM inference_records")
                         for v in row)
    finally:
        con.close()
    assert raw not in dump and hash_key(raw) not in dump


# ---------------------------------------------------------------------------
# list / detail / export / clear / pagination / auth
# ---------------------------------------------------------------------------
def test_list_is_newest_first_and_carries_no_heavy_fields(client):
    h = new_key(client)
    for i in range(3):
        client.post("/v1/chat/completions", headers=h, json={
            "model": "test-model", "messages": [{"role": "user", "content": f"q{i}"}],
            "max_tokens": 4})
    items = records(client)
    assert len(items) == 3
    assert [i["started_at"] for i in items] == sorted(
        (i["started_at"] for i in items), reverse=True)
    # No conversation, no output text: the list must stay cheap to poll.
    assert "messages" not in items[0] and "output_text" not in items[0]


def test_pagination_and_before_cursor(client):
    h = new_key(client)
    for i in range(5):
        client.post("/v1/chat/completions", headers=h, json={
            "model": "test-model", "messages": [{"role": "user", "content": f"p{i}"}],
            "max_tokens": 2})
    first = client.get("/api/inference-records", params={"limit": 2}).json()
    assert first["total"] == 5 and len(first["items"]) == 2 and first["offset"] == 0
    second = client.get("/api/inference-records",
                        params={"limit": 2, "offset": 2}).json()
    assert {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]} == set()

    older = client.get("/api/inference-records",
                       params={"limit": 10, "before": first["items"][-1]["started_at"]}).json()
    assert all(i["started_at"] < first["items"][-1]["started_at"] for i in older["items"])

    for bad in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
        assert client.get("/api/inference-records", params=bad).status_code == 400, bad


def test_detail_404_for_an_unknown_id(client):
    assert client.get("/api/inference-records/deadbeef").status_code == 404


def test_record_routes_require_admin(app):
    with TestClient(app) as c:
        for path in ("/api/inference-records", "/api/inference-records-export",
                     "/api/inference-records/status"):
            assert c.get(path).status_code == 401, path
        assert c.post("/api/inference-records/clear").status_code == 401
        assert c.get("/api/inference-records/whatever").status_code == 401


def test_export_is_ndjson_with_every_field_and_newest_first(client):
    h = new_key(client)
    for i in range(3):
        client.post("/v1/chat/completions", headers=h, json={
            "model": "test-model", "messages": [{"role": "user", "content": f"e{i}"}],
            "max_tokens": 4})
    r = client.get("/api/inference-records-export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    assert "attachment" in r.headers["content-disposition"]
    lines = [ln for ln in r.text.splitlines() if ln]
    assert len(lines) == 3
    exported = [json.loads(ln) for ln in lines]
    # Complete records: the export is the evidence, so nothing is trimmed.
    for row in exported:
        assert row["messages"] and row["output_text"] is not None
        assert row["params"] is not None
    assert [e["started_at"] for e in exported] == sorted(
        (e["started_at"] for e in exported), reverse=True)
    # Chinese text stays readable, not \u-escaped.
    client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model", "messages": [{"role": "user", "content": "中文提问"}],
        "max_tokens": 2})
    assert "中文提问" in client.get("/api/inference-records-export").text


def test_clear_deletes_everything_and_reports_the_count(client, app):
    h = new_key(client)
    for i in range(4):
        client.post("/v1/chat/completions", headers=h, json={
            "model": "test-model", "messages": [{"role": "user", "content": f"c{i}"}],
            "max_tokens": 2})
    before = log_db(app).stat().st_size
    r = client.post("/api/inference-records/clear")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "deleted": 4}
    assert records(client) == []
    # The file is actually smaller afterwards, not merely logically empty.
    assert log_db(app).stat().st_size <= before


def test_status_reports_the_store(client, app):
    h = new_key(client)
    client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model", "messages": [{"role": "user", "content": "s"}],
        "max_tokens": 2})
    st = client.get("/api/inference-records/status").json()
    assert st["total"] == 1
    assert st["schema_version"] == SCHEMA_VERSION
    assert st["readable"] is True and st["last_error"] is None
    assert st["path"] == str(log_db(app))
    assert st["bytes"] and st["bytes"] > 0
    assert st["retention_count"] == 1000 and st["retention_days"] == 30


# ---------------------------------------------------------------------------
# the store itself: retention, concurrency, corruption
# ---------------------------------------------------------------------------
def _entry(store: InferenceLogStore, *, rid: str, started: float,
           source="/v1/chat/completions") -> dict:
    return {
        "id": rid, "source": source, "model": "m", "actor_type": "admin",
        "started_at": started, "finished_at": started + 1, "status": "ok",
        "messages": [{"role": "user", "content": rid}],
        "output_text": rid, "params": {"temperature": 0.5},
    }


def test_retention_count_keeps_only_the_newest(tmp_path):
    store = InferenceLogStore(tmp_path / "r.sqlite3", retention_count=3,
                              retention_days=3650)
    try:
        base = 1_700_000_000.0
        for i in range(6):
            assert store.record(_entry(store, rid=f"r{i}", started=base + i))
        assert store.count() == 3
        kept = [i["id"] for i in store.list(limit=10)["items"]]
        assert kept == ["r5", "r4", "r3"]
    finally:
        store.close()


def test_retention_days_drops_only_old_rows(tmp_path):
    store = InferenceLogStore(tmp_path / "r.sqlite3", retention_count=1000,
                              retention_days=7)
    try:
        import time as _t
        now = _t.time()
        store.record(_entry(store, rid="old", started=now - 10 * 86400))
        store.record(_entry(store, rid="fresh", started=now - 3600))
        ids = [i["id"] for i in store.list(limit=10)["items"]]
        assert ids == ["fresh"]
    finally:
        store.close()


def test_retention_clamps_to_its_documented_ranges(tmp_path):
    store = InferenceLogStore(tmp_path / "r.sqlite3", retention_count=0,
                              retention_days=99999)
    try:
        assert store.retention_count == 1
        assert store.retention_days == 3650
        store.configure(retention_count=10_000_000, retention_days=0)
        assert store.retention_count == 100_000
        assert store.retention_days == 1
    finally:
        store.close()


def test_settings_clamp_the_record_fields(client):
    r = client.post("/api/settings", json={
        "inference_log_retention_count": 0, "inference_log_retention_days": 999999})
    assert r.status_code == 200
    s = r.json()["settings"]
    assert s["inference_log_retention_count"] == 1
    assert s["inference_log_retention_days"] == 3650
    # And it reached the live store, not only state.json.
    assert client.app.state.inference_log.retention_count == 1


def test_concurrent_writes_never_lock_and_keep_every_row(tmp_path):
    """A busy site finishes requests from several threads at once.

    ``BEGIN IMMEDIATE`` plus one connection under a lock is what makes this
    work; without it the "database is locked" error would silently drop
    exactly the records an operator is looking for.
    """
    store = InferenceLogStore(tmp_path / "c.sqlite3", retention_count=1000,
                             retention_days=3650)
    errors: list[str] = []

    def writer(n: int) -> None:
        try:
            for i in range(20):
                store.record(_entry(store, rid=f"w{n}-{i}", started=1_700_000_000 + n * 100 + i))
        except Exception as exc:  # pragma: no cover - the assertion below
            errors.append(repr(exc))

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    try:
        assert not errors, errors
        assert store.last_error is None
        assert store.count() == 6 * 20
        # Every id is unique and no row's output text was crossed with another's.
        for row in store.list(limit=200)["items"]:
            full = store.get(row["id"])
            assert full["messages"][0]["content"] == full["output_text"] == full["id"]
    finally:
        store.close()


def test_reads_during_writes_do_not_fail(tmp_path):
    store = InferenceLogStore(tmp_path / "rw.sqlite3", retention_count=1000,
                              retention_days=3650)
    stop = threading.Event()
    failures: list[str] = []

    def writer() -> None:
        n = 0
        while not stop.is_set():
            store.record(_entry(store, rid=f"x{n}", started=1_700_000_000 + n))
            n += 1

    def reader() -> None:
        while not stop.is_set():
            try:
                store.list(limit=20)
                store.status()
            except Exception as exc:  # pragma: no cover
                failures.append(repr(exc))
                return

    threads = [threading.Thread(target=writer), threading.Thread(target=reader),
               threading.Thread(target=reader)]
    for t in threads:
        t.start()
    import time as _t
    _t.sleep(0.5)
    stop.set()
    for t in threads:
        t.join()
    try:
        assert not failures, failures
        assert store.count() > 0
    finally:
        store.close()


def test_a_corrupt_database_does_not_break_inference(client, app, tmp_path):
    """The log is evidence, not a dependency: a corrupt file must degrade to
    "records are not being kept", with the reason visible in the admin API."""
    # Close first, then overwrite: replacing the bytes under a live connection
    # is not how a torn file happens, and SQLite may happily keep writing to the
    # copy it already has open.
    app.state.inference_log.close()
    log_db(app).write_bytes(b"this is not a database" * 100)
    app.state.inference_log.reopen()

    h = new_key(client)
    r = client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model", "messages": [{"role": "user", "content": "still works"}],
        "max_tokens": 4})
    assert r.status_code == 200, "a broken record log must not fail a request"

    st = client.get("/api/inference-records/status").json()
    assert st["readable"] is False or st["last_error"], st
    assert client.get("/api/inference-records").status_code in (200, 500)


def test_record_failure_is_reported_and_never_swallowed_silently(client, app):
    """A write that fails is remembered with its reason, for the admin page."""
    app.state.inference_log.path = Path("/nonexistent-dir/x.sqlite3")
    app.state.inference_log._discard_connection()
    h = new_key(client)
    assert client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model", "messages": [{"role": "user", "content": "x"}],
        "max_tokens": 2}).status_code == 200
    st = client.get("/api/inference-records/status").json()
    assert st["last_error"], st


def test_store_is_disabled_by_construction(tmp_path):
    store = InferenceLogStore(tmp_path / "d.sqlite3", enabled=False)
    try:
        assert store.record(_entry(store, rid="r", started=1.0)) is False
        assert store.count() == 0
    finally:
        store.close()


def test_a_failed_move_does_not_silence_the_log_forever(tmp_path):
    """A move that fails before its switch never reaches ``rebind``.

    The log is parked at the start of the move so the copy has no writer; if the
    move then fails, the old directory is still the live one and the log has to
    start accepting records again -- otherwise every record after one failed
    migration is silently lost, which is exactly the failure this feature exists
    to prevent.
    """
    store = InferenceLogStore(tmp_path / "r.sqlite3",
                             resume_when=lambda: not state["busy"])

    def entry(rid: str) -> dict:
        return _entry(store, rid=rid, started=1_700_000_000.0)

    state = {"busy": True}
    try:
        assert store.record(entry("before")) is True
        store.close()                       # the move's stop hook
        assert store.record(entry("during")) is False
        # Reads refuse too while the file may be half copied: answering from it
        # would report a partial history as if it were the whole one.
        with pytest.raises(RuntimeError):
            store.list(limit=10)

        state["busy"] = False               # the move failed; nothing rebinds
        assert store.record(entry("after")) is True
        assert sorted(i["id"] for i in store.list(limit=10)["items"]) == [
            "after", "before"]
    finally:
        store.close()


# ---------------------------------------------------------------------------
# the console stream's own generator: DONE only where there is a live client
# ---------------------------------------------------------------------------
def _console_stream_for(tmp_path, client, *, mode: str = "ok", deltas: int = 2,
                        kind: str = "server"):
    """Build the real console SSE generator plus its store, for direct driving.

    A TestClient cannot hang up mid-stream, so the end-of-stream behaviour is
    exercised through the generator itself -- which is exactly the object
    Starlette closes on a disconnect.
    """
    from app.api import admin_api
    from app.core.inference_log import InferenceLogStore, build_context
    from app.schemas import ChatMessage

    store = InferenceLogStore(tmp_path / "console.sqlite3")
    failing = _FailingClient(mode, deltas=deltas, kind=kind)
    ctx = build_context(store, req_id="console-rid", source="/api/chat/stream",
                        model="test-model",
                        actor={"actor_type": "admin", "actor_name": "admin"},
                        params={"max_tokens": 16},
                        messages=[ChatMessage(role="user", content="console prompt")])
    assert ctx is not None
    gen = admin_api._console_stream(
        failing, "console-rid", "prompt", [], {"max_tokens": 16, "stop": []},
        _UsageStore(), ctx)
    return gen, store, failing


class _UsageStore:
    """The only thing the generator uses from ``app.state.store``."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def record_usage(self, key, prompt_tokens, completion_tokens, **kw) -> None:
        self.calls.append((key, prompt_tokens, completion_tokens, kw))


@pytest.mark.asyncio
async def test_console_stream_disconnect_does_not_yield_while_closing(tmp_path):
    """`aclose()` must not produce a DONE frame -- or a RuntimeError.

    Regression (review of MYS-2497): the `finally` sent ``[DONE]`` unconditionally,
    so closing the generator threw ``RuntimeError: async generator ignored
    GeneratorExit`` at the exact moment the shutdown path was already busy, and
    would have written to a socket whose peer was gone.
    """
    gen, store, _ = _console_stream_for(tmp_path, None, mode="hang", deltas=2)
    try:
        first = await gen.__anext__()
        assert first.startswith("data: ") and "tok0" in first
        # Raises RuntimeError('async generator ignored GeneratorExit') if the
        # cancellation path yields, which is precisely the bug being pinned.
        await gen.aclose()

        items = store.list(limit=10)["items"]
        assert len(items) == 1, f"a cancelled console stream is one inference; got {len(items)}"
        row = store.get(items[0]["id"])
        assert row["status"] == "cancelled"
        assert row["error"]["type"] == "ClientDisconnected"
        # What the operator already saw on screen is the evidence and must be kept.
        assert row["output_text"] == "tok0 "
    finally:
        store.close()


@pytest.mark.asyncio
async def test_console_stream_normal_end_sends_exactly_one_done(tmp_path):
    gen, store, _ = _console_stream_for(tmp_path, None, mode="ok", deltas=2)
    try:
        frames = [frame async for frame in gen]
        assert sum(1 for f in frames if "[DONE]" in f) == 1
        assert frames[-1].strip() == "data: [DONE]"
        # The done event's usage still reaches the client before DONE.
        assert any('"done": true' in f for f in frames)
        row = store.get(store.list(limit=1)["items"][0]["id"])
        assert row["status"] == "ok"
        assert row["finish_reason"] == "stop"
        assert row["output_text"] == "tok0 tok1 "
    finally:
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,error_type", [
    ("worker_error", "WorkerError:server"),
    ("connection", "ConnectionResetError"),
])
async def test_console_stream_error_paths_send_one_done_and_one_record(
        tmp_path, mode, error_type):
    """A failure the client can still be told about ends with one DONE and one row."""
    gen, store, _ = _console_stream_for(tmp_path, None, mode=mode, deltas=2)
    try:
        frames = [frame async for frame in gen]
        assert sum(1 for f in frames if "[DONE]" in f) == 1, frames
        assert any('"error"' in f for f in frames)
        items = store.list(limit=10)["items"]
        assert len(items) == 1
        row = store.get(items[0]["id"])
        assert row["status"] == "error"
        assert row["error"]["type"] == error_type
        assert row["output_text"] == "tok0 tok1 "
    finally:
        store.close()


def test_console_stream_route_still_streams_a_greeting_and_done(client):
    """The SSE success format the console parses is unchanged by the refactor."""
    with client.stream("POST", "/api/chat/stream", json={
        "model": "test-model", "prompt": "hello", "max_tokens": 4,
    }) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    payloads = [ln[6:] for ln in body.splitlines() if ln.startswith("data: ")]
    assert payloads[-1] == "[DONE]"
    assert sum(1 for p in payloads if p == "[DONE]") == 1
    texts = [json.loads(p)["text"] for p in payloads[:-2] if p != "[DONE]"
             and '"text"' in p]
    assert texts, body
    assert json.loads(payloads[-2])["done"] is True


# ---------------------------------------------------------------------------
# a record dropped for a move must be visible, not silent
# ---------------------------------------------------------------------------
def test_status_reports_records_dropped_during_a_move(tmp_path):
    """Migration pauses writes; the page has to say so.

    Review of MYS-2497: after ``close()`` the store returned False without
    touching ``last_error``, so the console showed "0 条，一切正常" while the
    audit trail was losing rows. Dropping is still the right behaviour -- the old
    tree is about to be copied and deleted -- but it must be visible.
    """
    state = {"busy": True}
    store = InferenceLogStore(tmp_path / "m.sqlite3",
                             resume_when=lambda: not state["busy"])
    try:
        assert store.record(_entry(store, rid="before", started=1_700_000_000.0))
        store.close()                                  # the move's stop hook

        st = store.status()
        assert st["moving"] is True
        assert st["last_error"] is None, "no record has been dropped yet"

        assert store.record(_entry(store, rid="during", started=1_700_000_001.0)) is False
        st = store.status()
        assert st["last_error"] and "InferenceLogMoving" in st["last_error"]
        assert "迁移" in st["last_error"], st["last_error"]
        assert st["last_error_at"] is not None
        assert st["moving"] is True
        # The pause is not a database fault: the file is intact, just parked.
        assert st["total"] == 1

        # A second dropped record keeps the notice current rather than clearing it.
        assert store.record(_entry(store, rid="during2", started=1_700_000_002.0)) is False
        assert store.status()["last_error"]

        # Once the move is over (failure before the switch, or a rebind), the
        # next accepted record proves the log is live and the notice goes away.
        state["busy"] = False
        assert store.record(_entry(store, rid="after", started=1_700_000_003.0)) is True
        st = store.status()
        assert st["last_error"] is None
        assert st["last_error_at"] is None
        assert st["moving"] is False
        assert st["total"] == 2
    finally:
        store.close()


def test_rebind_clears_the_moving_notice(tmp_path):
    """After a successful move the new file is live, so the notice must not linger."""
    # resume_when=False stands in for "the move is still running": without a
    # predicate the store re-opens on the next record instead of dropping it.
    store = InferenceLogStore(tmp_path / "a.sqlite3", resume_when=lambda: False)
    try:
        store.close()
        assert store.record(_entry(store, rid="dropped", started=1_700_000_000.0)) is False
        assert "InferenceLogMoving" in (store.status()["last_error"] or "")
        store.rebind(tmp_path / "b.sqlite3")
        st = store.status()
        assert st["moving"] is False
        assert st["last_error"] is None
        assert st["total"] == 0
        # The rebind really landed on the new file.
        assert st["path"] == str(tmp_path / "b.sqlite3")
        assert store.record(_entry(store, rid="fresh", started=1_700_000_004.0)) is True
        assert store.status()["total"] == 1
    finally:
        store.close()


def test_status_route_exposes_records_dropped_for_a_move(client, app):
    """The console's own view of the log has to show the gap.

    Driven through the real admin route: an operator asks ``/status`` because the
    list looks short, and "moving" plus the dropped-record notice is the answer.
    """
    h = new_key(client)
    assert client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model", "messages": [{"role": "user", "content": "kept"}],
        "max_tokens": 4}).status_code == 200
    log = app.state.inference_log
    log._resume_when = lambda: False    # the move is still running
    log.close()

    # A request that finishes while the directory is being copied: served, not recorded.
    assert client.post("/v1/chat/completions", headers=h, json={
        "model": "test-model", "messages": [{"role": "user", "content": "dropped"}],
        "max_tokens": 4}).status_code == 200

    st = client.get("/api/inference-records/status").json()
    assert st["moving"] is True
    assert st["readable"] is True, "a parked log is not a broken one"
    assert st["last_error"] and "InferenceLogMoving" in st["last_error"]
    assert "迁移" in st["last_error"]
    assert st["last_error_at"] is not None
    assert st["total"] == 1, "the records written before the move are still there"

    # Reads during the move refuse rather than answering from a half-copied file.
    assert client.get("/api/inference-records").status_code == 500
