"""``/v1/chat/completions`` serving an ``ocr_vl`` model, end to end.

Driven through real worker subprocesses on the mock engine, so everything between
the HTTP request and the answer is the production path: the API's validation,
the prompt rendering, the worker's tokenizer/engine seam, the scheduler (with
its one-at-a-time rule for this kind), the SSE relay, and the response shape.

The mock's answer is a fixed OTSL table, which is what makes the assertions
possible: ``<fcel>`` and ``<nl>`` are ordinary vocabulary entries and must
survive the whole path untouched. If any layer were to strip them as "special
tokens" or parse them as another model's protocol, the official PaddleOCR
client's OTSL -> HTML step would produce an empty table, so this is the property
that matters rather than the exact characters.
"""

from __future__ import annotations

import base64
import json
import struct
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.engine.mock import MockOcrVlBackend
from app.main import create_app


def _png(width: int = 64, height: int = 48) -> bytes:
    """A real, decodable PNG of a solid colour (no Pillow, no OpenCV).

    The mock's backend reads the header for the size and refuses what it cannot
    recognise, so a fake "image" would test a different refusal path than a real
    upload does.
    """

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + b"\x7f\x7f\x7f" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def _data_url(blob: bytes | None = None) -> str:
    return "data:image/png;base64," + base64.b64encode(blob or _png()).decode()


def _user(prompt: str = "Table Recognition:", images: int = 1) -> dict:
    content = [{"type": "image_url", "image_url": {"url": _data_url()}}
               for _ in range(images)]
    content.append({"type": "text", "text": prompt})
    return {"role": "user", "content": content}


@pytest.fixture()
def app(tmp_path):
    models = tmp_path / "models"
    d = models / "paddleocr-vl-1.5"
    d.mkdir(parents=True)
    (d / "paddleocr-vl-1.5_bf16_seq2048_bm1684x2_4core_static.bmodel").write_bytes(b"\x00" * 4096)
    return create_app(
        data_dir=tmp_path / "data",
        models_dir=models,
        backend_kind="mock",
        web_dir=tmp_path / "web",
        context_length_override=2048,
    )


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def key(client) -> dict:
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    raw = client.post("/api/keys", json={"name": "ocr-vl"}).json()["key"]
    assert client.post("/api/models/paddleocr-vl-1.5/load").status_code == 200
    return {"Authorization": f"Bearer {raw}"}


def _chat(client, key, **body):
    payload = {"model": "paddleocr-vl-1.5", "messages": [_user()],
               "max_tokens": 512}
    payload.update(body)
    return client.post("/v1/chat/completions", headers=key, json=payload)


# ---------------------------------------------------------------------------
# the happy path
# ---------------------------------------------------------------------------
def test_the_answer_is_the_otsl_table_verbatim(client, key):
    """``<fcel>`` and ``<nl>`` reach the client, in order, unchanged."""
    r = _chat(client, key)
    assert r.status_code == 200, r.text
    body = r.json()
    text = body["choices"][0]["message"]["content"]
    assert text.startswith("<fcel>产线<fcel>产量（台）")
    assert "<nl>" in text
    # Every cell marker the mock emitted is still there, in the same order.
    assert text.count("<fcel>") == MockOcrVlBackend.TABLE.count("<fcel>")
    assert text.count("<nl>") == MockOcrVlBackend.TABLE.count("<nl>")
    # ...and no reasoning was invented for a model that has no think block.
    assert "reasoning_content" not in body["choices"][0]["message"]


def test_usage_and_finish_reason_are_real_numbers(client, key):
    r = _chat(client, key)
    assert r.status_code == 200, r.text
    body = r.json()
    usage = body["usage"]
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    assert body["choices"][0]["finish_reason"] in ("stop", "length")
    assert body["object"] == "chat.completion"
    assert body["model"] == "paddleocr-vl-1.5"


def test_max_completion_tokens_is_the_same_limit_as_max_tokens(client, key):
    """PaddleX's official client sends this spelling, not ``max_tokens``."""
    r = _chat(client, key, max_tokens=None, max_completion_tokens=16)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["usage"]["completion_tokens"] == 16
    assert body["choices"][0]["finish_reason"] == "length"


def test_max_completion_tokens_wins_when_both_are_sent(client, key):
    r = _chat(client, key, max_tokens=64, max_completion_tokens=8)
    assert r.status_code == 200, r.text
    assert r.json()["usage"]["completion_tokens"] == 8


def test_a_zero_length_limit_is_a_400(client, key):
    assert _chat(client, key, max_completion_tokens=0).status_code == 400


def test_stop_truncates_the_answer(client, key):
    r = _chat(client, key, stop=["<nl>"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert "<nl>" not in body["choices"][0]["message"]["content"]
    assert body["choices"][0]["finish_reason"] == "stop"


def test_the_model_is_listed_by_v1_models_with_its_kind(client, key):
    """A client discovers models here; the kind is how it knows the endpoint."""
    listed = client.get("/v1/models", headers=key).json()["data"]
    entry = next(m for m in listed if m["id"] == "paddleocr-vl-1.5")
    assert entry["kind"] == "ocr_vl"


# ---------------------------------------------------------------------------
# request validation
# ---------------------------------------------------------------------------
def test_two_images_is_a_400_that_says_why(client, key):
    r = _chat(client, key, messages=[_user(images=2)])
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "一张图片" in detail
    assert "2" in detail


def test_no_image_is_a_400(client, key):
    r = _chat(client, key, messages=[{"role": "user", "content": "OCR:"}])
    assert r.status_code == 400, r.text
    assert "图片" in r.json()["detail"]


def test_tools_are_refused_rather_than_silently_dropped(client, key):
    """The template has no tools block; rendering it anyway would answer a
    different question than the one asked."""
    r = _chat(client, key, tools=[{"type": "function", "function": {
        "name": "lookup", "parameters": {"type": "object", "properties": {}}}}])
    assert r.status_code == 400, r.text
    assert "tools" in r.json()["detail"]


def test_a_remote_image_url_is_refused(client, key):
    """This box is offline by design; a fetch would be an SSRF surface."""
    r = _chat(client, key, messages=[{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
        {"type": "text", "text": "OCR:"},
    ]}])
    assert r.status_code == 400


def test_a_broken_png_is_a_400_not_a_500(client, key):
    """The image reaches the worker's decoder, which refuses it as a client
    error -- the same 400 the auxiliary OCR endpoint gives."""
    r = _chat(client, key, messages=[{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,"
                                                    + base64.b64encode(b"junk").decode()}},
        {"type": "text", "text": "OCR:"},
    ]}])
    assert r.status_code == 400, r.text


def test_an_embedding_model_cannot_be_asked_to_do_ocr_vl(client, key):
    """Right model, wrong endpoint is still a 400 naming the right one."""
    r = _chat(client, key, model="paddleocr-vl-1.5")
    assert r.status_code == 200        # sanity: the model itself works
    r = client.post("/v1/embeddings", headers=key,
                    json={"model": "paddleocr-vl-1.5", "input": "x"})
    assert r.status_code == 400, r.text
    assert "/v1/chat/completions" in r.json()["detail"]


# ---------------------------------------------------------------------------
# streaming
# ---------------------------------------------------------------------------
def _sse_events(text: str) -> list[dict | str]:
    out: list[dict | str] = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):]
        out.append(payload if payload == "[DONE]" else json.loads(payload))
    return out


def test_streaming_delivers_the_same_text_as_the_plain_call(client, key):
    plain = _chat(client, key).json()["choices"][0]["message"]["content"]

    r = _chat(client, key, stream=True)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(r.text)
    assert events[-1] == "[DONE]"

    chunks = [e for e in events if isinstance(e, dict) and e["choices"]]
    # The first chunk announces the role, exactly as OpenAI's does.
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    streamed = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks)
    assert streamed == plain

    finish = [c["choices"][0]["finish_reason"] for c in chunks if c["choices"][0].get("finish_reason")]
    assert finish and finish[-1] in ("stop", "length")

    # usage arrives in its own frame, the way the OpenAI clients read it.
    usage = [e for e in events if isinstance(e, dict) and e.get("usage")]
    assert usage and usage[-1]["usage"]["total_tokens"] > 0


def test_streaming_keeps_the_otsl_markers_split_across_chunks(client, key):
    """The markers arrive a character at a time in the mock, so this is the
    pathological case for a streamer that holds back a tail it thinks might
    become ``</think>`` or ``<tool_call>``."""
    r = _chat(client, key, stream=True)
    events = _sse_events(r.text)
    chunks = [e for e in events if isinstance(e, dict) and e["choices"]]
    streamed = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks)
    assert streamed.startswith("<fcel>")
    assert streamed.count("<fcel>") == MockOcrVlBackend.TABLE.count("<fcel>")
