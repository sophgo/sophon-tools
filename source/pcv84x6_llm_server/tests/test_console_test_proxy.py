"""The console's per-kind test routes (``/api/test/*``, MYS-2599).

The playground tests embedding, rerank, ASR and OCR models with the admin
cookie, not an API key. These routes call the ``/v1`` handlers themselves, so
what is pinned here is the part that is *theirs*:

* they require the admin session (and nothing else -- no bearer key);
* the response is the ``/v1`` response, byte for byte where the engine is
  deterministic, so the console shows what a client would get;
* the inference record says ``admin`` and names the console path as its
  source, so console traffic is distinguishable from API traffic;
* a model of the wrong kind is the same 400 the ``/v1`` route gives.
"""

from __future__ import annotations

import base64
import io
import math
import struct
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "tests" / "data" / "ocr" / "img"

BMODELS = {
    "embed-model": ["qwen3-embedding-0.6b_bf16_seq8192_4core_static.bmodel"],
    "rerank-model": ["bge-reranker-v2-m3_bf16_seq2048_4core_static.bmodel"],
    "asr-model": ["qwen3-asr-0.6b_bf16_seq1024_4core_static.bmodel"],
    "ocr-model": [
        "ppocrv6-medium-det_f16_736_bm1684x2_static_20261103.bmodel",
        "ppocrv6-medium-rec_f16_48x320_bm1684x2_static_20261103.bmodel",
        "ppocrv6-medium-rec_f16_48x640_bm1684x2_static_20261103.bmodel",
        "ppocrv6-medium-rec_f16_48x1600_bm1684x2_static_20261103.bmodel",
    ],
    "chat-model": ["qwen3.6-35b-a3b-int4-autow4bf16_seq2048_4core_dynamic.bmodel"],
}


def wav_bytes(seconds: float = 1.0, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(int(seconds * rate))))
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path):
    models = tmp_path / "models"
    for name, files in BMODELS.items():
        d = models / name
        (d / "config").mkdir(parents=True)
        (d / "config" / "config.json").write_text("{}")
        for f in files:
            (d / f).write_bytes(b"\x00" * 4096)
    app = create_app(data_dir=tmp_path / "data", models_dir=models,
                     backend_kind="mock", web_dir=tmp_path / "web",
                     context_length_override=4096)
    with TestClient(app) as c:
        yield c


def _admin(client, *model_ids) -> None:
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    for model_id in model_ids:
        r = client.post(f"/api/models/{model_id}/load")
        assert r.status_code == 200, r.text


def _key(client) -> dict:
    raw = client.post("/api/keys", json={"name": "pytest"}).json()["key"]
    return {"Authorization": f"Bearer {raw}"}


def _records(client) -> list[dict]:
    return client.get("/api/inference-records", params={"limit": 50}).json()["items"]


def _png() -> bytes:
    return (IMG / "ui_status.png").read_bytes()


@pytest.mark.parametrize("path", [
    "/api/test/embeddings", "/api/test/rerank", "/api/test/audio/transcriptions",
    "/api/test/ocr", "/api/test/chat/completions",
])
def test_every_route_requires_the_admin_session(client, path):
    """An *inference* key is not a console session: these routes are not a second,
    unauthenticated door to the models.

    Since MYS-2676 a key can authenticate ``/api``, but only one minted with
    ``scope: admin``. The default scope is refused with a 403 whose message
    names the scope -- deliberately different from the 401 a caller with no
    credential at all gets, because "you may not" and "I do not know you" call
    for different fixes.
    """
    _admin(client)
    headers = _key(client)
    client.post("/api/logout")
    client.cookies.clear()
    r = client.post(path, json={"model": "x"}, headers=headers)
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "forbidden_scope"
    # No credential at all is still the old answer.
    assert client.post(path, json={"model": "x"}).status_code == 401


def test_embeddings_match_the_v1_response_and_record_as_console(client):
    _admin(client, "embed-model")
    body = {"model": "embed-model", "input": ["你好", "hello world"]}
    console = client.post("/api/test/embeddings", json=body)
    assert console.status_code == 200, console.text
    api = client.post("/v1/embeddings", json=body, headers=_key(client))
    assert api.status_code == 200, api.text
    assert console.json()["data"] == api.json()["data"]

    rows = _records(client)
    by_source = {r["source"]: r for r in rows}
    assert by_source["/api/test/embeddings"]["actor_type"] == "admin"
    assert by_source["/v1/embeddings"]["actor_type"] == "api_key"


def test_rerank_returns_sorted_results(client):
    _admin(client, "rerank-model")
    r = client.post("/api/test/rerank", json={
        "model": "rerank-model", "query": "NPU 内存",
        "documents": ["NPU 内存不足时排队", "天气晴", "加载模型占用 NPU 内存"]})
    assert r.status_code == 200, r.text
    scores = [x["relevance_score"] for x in r.json()["results"]]
    assert scores == sorted(scores, reverse=True)
    assert {x["index"] for x in r.json()["results"]} == {0, 1, 2}
    assert _records(client)[0]["source"] == "/api/test/rerank"


def test_transcription_accepts_the_multipart_upload(client):
    _admin(client, "asr-model")
    r = client.post("/api/test/audio/transcriptions",
                    files={"file": ("a.wav", wav_bytes(2.0), "audio/wav")},
                    data={"model": "asr-model", "response_format": "verbose_json"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["duration"] == pytest.approx(2.0, abs=0.01)
    assert body["segments"], body
    row = _records(client)[0]
    assert (row["source"], row["actor_type"]) == ("/api/test/audio/transcriptions", "admin")


@pytest.mark.parametrize("form", ["json", "multipart"])
def test_ocr_accepts_both_body_forms(client, form):
    _admin(client, "ocr-model")
    if form == "json":
        uri = "data:image/png;base64," + base64.b64encode(_png()).decode()
        r = client.post("/api/test/ocr", json={"model": "ocr-model", "image": uri})
    else:
        r = client.post("/api/test/ocr", files={"file": ("p.png", _png(), "image/png")},
                        data={"model": "ocr-model"})
    assert r.status_code == 200, r.text
    lines = r.json()["lines"]
    assert lines and all(len(x["box"]) == 4 for x in lines)
    assert _records(client)[0]["source"] == "/api/test/ocr"


def test_chat_completions_streams_for_a_chat_model(client):
    _admin(client, "chat-model")
    r = client.post("/api/test/chat/completions", json={
        "model": "chat-model", "stream": True, "max_tokens": 8,
        "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200, r.text
    assert "data: [DONE]" in r.text
    row = _records(client)[0]
    assert (row["source"], row["actor_type"]) == ("/api/test/chat/completions", "admin")


@pytest.mark.parametrize("path,body", [
    ("/api/test/embeddings", {"model": "rerank-model", "input": "x"}),
    ("/api/test/rerank", {"model": "embed-model", "query": "q", "documents": ["d"]}),
    ("/api/test/ocr", {"model": "embed-model", "image": "aGVsbG8="}),
])
def test_a_model_of_the_wrong_kind_is_the_v1_400(client, path, body):
    _admin(client, "embed-model", "rerank-model")
    r = client.post(path, json=body)
    assert r.status_code == 400, r.text
    assert "请调用" in r.json()["detail"]


def test_a_model_that_is_not_loaded_is_loaded_on_demand(client):
    """The proxies call the /v1 handlers, so they inherit on-demand loading.

    MYS-2657: an auxiliary model that is on disk but unloaded is brought up
    rather than refused. The 409 lives on the operator's switch now --
    ``test_auto_load_disabled_answers_409`` in ``tests/test_aux_idle.py``.
    """
    _admin(client)
    client.post("/api/settings", json={"aux_auto_load": True})  # off by default since v0.6.28
    r = client.post("/api/test/embeddings", json={"model": "embed-model", "input": "x"})
    assert r.status_code == 200, r.text
    assert r.json()["data"][0]["embedding"]
