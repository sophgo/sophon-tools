"""``POST /v1/embeddings`` end-to-end over the mock backend.

Drives real worker subprocesses (the mock engine), so everything between the
HTTP body and the recorded row is exercised: the admission gate, the kind
check, the length refusal, the RPC, the base64 encoding and the one record the
request leaves behind.

The mock's vectors are hashed, not learned -- so nothing here asserts a
particular *direction*. What it asserts is the contract a client depends on:
one vector per input in order, unit norm after truncation, base64 that decodes
back to exactly the floats, and refusals that name the reason.
"""

from __future__ import annotations

import base64
import json
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def make_model(root: Path, name: str, bmodel: str, context: str = "seq2048"):
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{bmodel}_{context}_4core_static.bmodel").write_bytes(b"\x00" * 4096)
    (d / "config" / "config.json").write_text("{}")
    return d


#: The bmodel names the catalogue's downloads land as -- the same strings the
#: kind detector reads, so this test also covers the naming contract.
EMBED_BMODEL = "qwen3-embedding-0.6b_bf16"
CHAT_BMODEL = "qwen3.6-35b-a3b-int4-autow4bf16"


@pytest.fixture()
def app(tmp_path):
    models = tmp_path / "models"
    make_model(models, "embed-model", EMBED_BMODEL)
    make_model(models, "chat-model", CHAT_BMODEL, context="seq2048")
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
        yield c


def _login_and_load(client, *model_ids) -> dict:
    """Log in, load the models, and return a bearer header for the API."""
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    for model_id in model_ids:
        r = client.post(f"/api/models/{model_id}/load")
        assert r.status_code == 200, r.text
    raw = client.post("/api/keys", json={"name": "pytest"}).json()["key"]
    return {"Authorization": f"Bearer {raw}"}


def _records(client) -> list[dict]:
    r = client.get("/api/inference-records", params={"limit": 200})
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_single_input_returns_one_vector(client):
    h = _login_and_load(client, "embed-model")
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "embed-model", "input": "hello world"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["object"] == "list"
    assert body["model"] == "embed-model"
    assert len(body["data"]) == 1
    assert body["data"][0]["object"] == "embedding"
    assert body["data"][0]["index"] == 0
    vec = body["data"][0]["embedding"]
    assert isinstance(vec, list) and len(vec) == 1024
    assert body["usage"]["prompt_tokens"] > 0
    assert body["usage"]["total_tokens"] == body["usage"]["prompt_tokens"]


def test_multiple_inputs_keep_their_order(client):
    """`index` must address the input list, not the reply order.

    A client joins vectors back to its documents by index; getting this wrong is
    invisible in a single-input test and corrupts every batch.
    """
    h = _login_and_load(client, "embed-model")
    texts = ["first text", "second text", "third text", "fourth text"]
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "embed-model", "input": texts})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [d["index"] for d in body["data"]] == [0, 1, 2, 3]
    # Different text, different vector -- and the same text must reproduce, or
    # the index order would be unobservable.
    vecs = [d["embedding"] for d in body["data"]]
    assert len({tuple(round(x, 6) for x in v[:8]) for v in vecs}) == len(texts)

    single = client.post("/v1/embeddings", headers=h,
                         json={"model": "embed-model", "input": "third text"}).json()
    assert single["data"][0]["embedding"] == vecs[2]


def test_base64_output_decodes_to_the_same_floats(client):
    """OpenAI's ``encoding_format: base64`` is little-endian float32.

    Clients that ask for it to save bandwidth (every official SDK can) compare
    the decoded bytes against the float form; a big-endian pack or a float64
    pack would both "work" and both be wrong.
    """
    h = _login_and_load(client, "embed-model")
    payload = {"model": "embed-model", "input": ["alpha", "beta"]}
    floats = client.post("/v1/embeddings", headers=h,
                         json=payload).json()["data"]
    b64 = client.post("/v1/embeddings", headers=h,
                      json={**payload, "encoding_format": "base64"}).json()["data"]
    assert len(b64) == len(floats)
    for as_float, as_b64 in zip(floats, b64):
        raw = base64.b64decode(as_b64["embedding"])
        n = len(raw) // 4
        decoded = list(struct.unpack(f"<{n}f", raw))
        assert decoded == pytest.approx(as_float["embedding"], rel=0, abs=1e-6)
        assert len(decoded) == len(as_float["embedding"])


def test_dimensions_truncates_and_keeps_the_norm_at_one(client):
    """MRL truncation happens *before* normalisation.

    Doing it the other way round leaves a vector whose norm is <1, and an
    embedding client that assumes unit length (cosine = dot product) then gets
    silently wrong similarities.
    """
    h = _login_and_load(client, "embed-model")
    for dim in (32, 128, 256, 1024):
        r = client.post("/v1/embeddings", headers=h,
                        json={"model": "embed-model", "input": "truncate me",
                              "dimensions": dim})
        assert r.status_code == 200, r.text
        vec = r.json()["data"][0]["embedding"]
        assert len(vec) == dim
        norm = sum(x * x for x in vec) ** 0.5
        assert norm == pytest.approx(1.0, abs=1e-5), f"dim={dim} norm={norm}"


def test_a_truncated_vector_is_the_prefix_of_the_full_one(client):
    """MRL truncation may not permute or rescale the components.

    The full-width vector's first `dim` values, renormalised, are the
    `dim`-dimensional embedding -- that is what "Matryoshka" means, and a client
    that stores full vectors and truncates locally must agree with one that asks
    the server for 256 dimensions.
    """
    h = _login_and_load(client, "embed-model")
    text = "matryoshka representation learning"
    full = client.post("/v1/embeddings", headers=h,
                       json={"model": "embed-model", "input": text}).json()["data"][0]["embedding"]
    short = client.post("/v1/embeddings", headers=h,
                        json={"model": "embed-model", "input": text, "dimensions": 64}
                        ).json()["data"][0]["embedding"]
    prefix = full[:64]
    scale = sum(x * x for x in prefix) ** 0.5
    assert short == pytest.approx([x / scale for x in prefix], abs=1e-6)


def test_instruction_prefix_changes_the_vector(client):
    """The non-standard ``instruction`` field is applied, not accepted and ignored."""
    h = _login_and_load(client, "embed-model")
    plain = client.post("/v1/embeddings", headers=h,
                        json={"model": "embed-model", "input": "what is deep learning"}
                        ).json()["data"][0]["embedding"]
    steered = client.post("/v1/embeddings", headers=h,
                          json={"model": "embed-model", "input": "what is deep learning",
                                "instruction": "Instruct: retrieve passages\nQuery: "}
                          ).json()["data"][0]["embedding"]
    assert plain != steered


@pytest.mark.parametrize("payload,reason", [
    ({"input": "x", "dimensions": 16}, "dimensions"),
    ({"input": "x", "dimensions": 1025}, "dimensions"),
    ({"input": ""}, "空字符串"),
    ({"input": ["ok", ""]}, "空字符串"),
    ({"input": []}, "空数组"),
    ({"input": [1, 2, 3]}, "token"),
])
def test_bad_inputs_are_400(client, payload, reason):
    h = _login_and_load(client, "embed-model")
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "embed-model", **payload})
    assert r.status_code == 400, r.text
    assert reason in r.json()["detail"], r.json()["detail"]


def test_more_than_64_inputs_is_400(client):
    h = _login_and_load(client, "embed-model")
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "embed-model",
                          "input": [f"text {i}" for i in range(65)]})
    assert r.status_code == 400
    assert "64" in r.json()["detail"]


def test_an_over_long_input_names_the_limit(client):
    """Refused before the inference, with the number the model actually has.

    A truncated embedding of a long document is worse than an error: the vector
    silently describes the first N tokens, and there is nothing in the response
    that says so.
    """
    h = _login_and_load(client, "embed-model")
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "embed-model", "input": "x" * 90_000})
    assert r.status_code == 400
    assert "2048" in r.json()["detail"], r.json()["detail"]


def test_chat_model_on_the_embeddings_endpoint_is_400(client):
    h = _login_and_load(client, "chat-model")
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "chat-model", "input": "hi"})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "chat" in detail and "/v1/chat/completions" in detail


def test_embedding_model_on_the_chat_endpoint_is_400(client):
    h = _login_and_load(client, "embed-model")
    r = client.post("/v1/chat/completions", headers=h,
                    json={"model": "embed-model",
                          "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "embedding" in detail and "/v1/embeddings" in detail


def test_embedding_model_on_the_console_chat_route_is_400(client):
    """The console's own routes are chat-only too."""
    h = _login_and_load(client, "embed-model")  # logs in
    assert h  # login happened above
    r = client.post("/api/chat", json={"model": "embed-model", "prompt": "hi"})
    assert r.status_code == 400
    assert "/v1/embeddings" in r.json()["detail"]


def test_an_unloaded_model_is_loaded_on_demand(client):
    """Since the idle feature (MYS-2657): on disk but not loaded is served.

    The alternative -- a 409 telling the caller to go and press Load -- is what
    this test used to assert. Auto-unloading makes that answer unacceptable: a
    model that was resident an hour ago would start refusing requests nobody
    changed anything to deserve.

    ``test_auto_load_disabled_answers_409`` in ``tests/test_aux_idle.py`` covers
    the operator who turned it off.
    """
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    client.post("/api/settings", json={"aux_auto_load": True})  # off by default since v0.6.28
    raw = client.post("/api/keys", json={"name": "k"}).json()["key"]
    h = {"Authorization": f"Bearer {raw}"}
    before = len(_records(client))
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "embed-model", "input": "hi"})
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) == 1
    # The load happened inside the request, and it left the model resident.
    models = {m["id"]: m for m in client.get("/api/models").json()["models"]}
    assert models["embed-model"]["loaded"] is True
    # And the request itself is still one record, not a load plus a request.
    assert len(_records(client)) == before + 1


def test_unknown_model_is_404(client):
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    raw = client.post("/api/keys", json={"name": "k"}).json()["key"]
    r = client.post("/v1/embeddings",
                    headers={"Authorization": f"Bearer {raw}"},
                    json={"model": "no-such-model", "input": "hi"})
    assert r.status_code == 404


def test_an_embeddings_request_writes_exactly_one_record(client):
    """One row per request, with the input, the shape and the token count.

    Per *request*, not per text: a batch of 64 is one inference as far as the
    audit trail is concerned, and 64 rows would bury the chat traffic beside it.
    """
    h = _login_and_load(client, "embed-model")
    before = len(_records(client))
    texts = ["record one", "record two", "record three"]
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "embed-model", "input": texts, "dimensions": 128})
    assert r.status_code == 200, r.text
    usage = r.json()["usage"]
    after = _records(client)
    assert len(after) == before + 1, after

    row = after[0]
    assert row["source"] == "/v1/embeddings"
    assert row["model"] == "embed-model"
    assert row["status"] == "ok"
    assert row["prompt_tokens"] == usage["prompt_tokens"]

    record = client.get(f"/api/inference-records/{row['id']}").json()
    assert record["output_text"] == f"3 vectors x 128 dims"
    stored = record["messages"]
    if isinstance(stored, str):
        stored = json.loads(stored)
    assert [m["content"] for m in stored] == texts
    assert record["params"]["dimensions"] == 128


def test_v1_models_lists_the_kind(client):
    """A client discovers which endpoint to call from here."""
    h = _login_and_load(client, "embed-model", "chat-model")
    kinds = {m["id"]: m["kind"] for m in client.get("/v1/models", headers=h).json()["data"]}
    assert kinds["embed-model"] == "embedding"
    assert kinds["chat-model"] == "chat"
    assert client.get("/v1/models/embed-model", headers=h).json()["kind"] == "embedding"


def test_long_chinese_input_is_accepted_up_to_the_real_token_limit(client):
    """Chinese under the limit is served, not refused by a length heuristic.

    The API process has no tokenizer, so any check it made could only
    approximate -- and a byte-based one over-estimates Chinese by ~3x, refusing
    input that fits. The worker owns the tokenizer and is the only place the
    real number exists, which is why the limit is enforced there; this pins
    that the API does not second-guess it.

    The number is the mock's, and the mock counts a text's UTF-8 *bytes* as its
    tokens (see ``MockEmbedBackend``). At the shipped seq2048 that means the
    Chinese that fits is smaller than it was at seq8192: the case below is ~680
    "tokens", comfortably inside the limit.
    """
    h = _login_and_load(client, "embed-model")
    text = "深度学习是机器学习的一个子集。" * 15
    assert len(text.encode()) < 2048, "the fixture must fit the mock's limit"
    assert len(text.encode()) > 512, "and be long enough to matter"
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "embed-model", "input": text})
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) == 1


def test_an_over_long_chinese_input_still_names_the_limit(client):
    """The refusal survives the move into the worker, with the real number.

    The figure is the shipped bmodel's: 2048 since MYS-2696 (8192 before), and
    the message quotes it so an operator can find the ceiling without reading
    the bmodel.
    """
    h = _login_and_load(client, "embed-model")
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "embed-model", "input": "深" * 12000})
    assert r.status_code == 400
    assert "2048" in r.json()["detail"], r.json()["detail"]
    assert "8192" not in r.json()["detail"], (
        "the message still quotes the old SEQLEN")


def test_an_input_at_the_seq2048_limit_is_accepted_and_one_past_it_refused(client):
    """The boundary itself, not just 'some long input is refused'.

    A limit that is off by one either refuses the longest input the bmodel
    accepts or accepts one it cannot run, and both look like working software
    until a document lands exactly on it.
    """
    h = _login_and_load(client, "embed-model")
    ok = "a" * 2048
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "embed-model", "input": ok})
    assert r.status_code == 200, r.text
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": "embed-model", "input": ok + "a"})
    assert r.status_code == 400, r.text
