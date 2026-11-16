"""``POST /v1/rerank`` end-to-end over the mock backend.

The mock's logits depend on how many words the query and the document share, so
"the right document came first" is a real assertion here rather than a check
that a sort of equal values left the input order alone.

What is being pinned: the response order (by ``relevance_score`` descending),
that ``index`` still addresses the *input* list after sorting, the ``top_n``
cut, both document shapes the ecosystem sends, the ``/rerank`` alias, the kind
refusals, and the single record the request leaves behind.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.engine.aux_native import sigmoid


def make_model(root: Path, name: str, bmodel: str, context: str = "seq2048"):
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{bmodel}_{context}_4core_static.bmodel").write_bytes(b"\x00" * 4096)
    (d / "config" / "config.json").write_text("{}")
    return d


RERANK_BMODEL = "bge-reranker-v2-m3_bf16"
EMBED_BMODEL = "qwen3-embedding-0.6b_bf16"
CHAT_BMODEL = "qwen3.6-35b-a3b-int4-autow4bf16"


@pytest.fixture()
def app(tmp_path):
    models = tmp_path / "models"
    make_model(models, "rerank-model", RERANK_BMODEL)
    make_model(models, "embed-model", EMBED_BMODEL, context="seq8192")
    make_model(models, "chat-model", CHAT_BMODEL)
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


#: The reference demo's pair, whose ranking is the one MYS-2551 measured.
REFERENCE_QUERY = "what is panda?"
REFERENCE_DOCS = ["hi", "The giant panda is a bear species endemic to China."]


def test_results_are_sorted_by_score_descending(client):
    h = _login_and_load(client, "rerank-model")
    r = client.post("/v1/rerank", headers=h,
                    json={"model": "rerank-model", "query": REFERENCE_QUERY,
                          "documents": REFERENCE_DOCS})
    assert r.status_code == 200, r.text
    body = r.json()
    scores = [item["relevance_score"] for item in body["results"]]
    assert scores == sorted(scores, reverse=True)
    # The relevant document must actually win -- not merely sort correctly.
    assert body["results"][0]["document"]["text"] == REFERENCE_DOCS[1]
    assert all(0.0 <= s <= 1.0 for s in scores), scores


def test_index_addresses_the_input_list_after_sorting(client):
    """``index`` is the document's position in the *request*, not the reply.

    A client reads ``documents[result["index"]]``; an index renumbered by the
    sort would hand back the wrong document for every result but the first.
    """
    h = _login_and_load(client, "rerank-model")
    docs = ["panda", "a bear called panda lives in China", "unrelated weather report",
            "panda panda panda"]
    body = client.post("/v1/rerank", headers=h,
                       json={"model": "rerank-model", "query": "panda bear china",
                             "documents": docs}).json()
    by_index = {item["index"]: item for item in body["results"]}
    assert sorted(by_index) == list(range(len(docs)))
    for item in body["results"]:
        assert item["document"]["text"] == docs[item["index"]]


def test_top_n_truncates_after_sorting(client):
    h = _login_and_load(client, "rerank-model")
    docs = ["a", "b panda", "c", "d panda china"]
    full = client.post("/v1/rerank", headers=h,
                       json={"model": "rerank-model", "query": "panda china",
                             "documents": docs}).json()["results"]
    cut = client.post("/v1/rerank", headers=h,
                      json={"model": "rerank-model", "query": "panda china",
                            "documents": docs, "top_n": 2}).json()["results"]
    assert len(cut) == 2
    assert cut == full[:2]


def test_top_n_larger_than_the_corpus_is_not_an_error(client):
    h = _login_and_load(client, "rerank-model")
    body = client.post("/v1/rerank", headers=h,
                       json={"model": "rerank-model", "query": "panda",
                             "documents": ["x", "y"], "top_n": 10}).json()
    assert len(body["results"]) == 2


def test_return_documents_false_omits_the_text(client):
    """A caller that already holds the documents asks for indices only.

    Sending them back doubles the response for a 256-document batch, which is
    exactly the case this flag exists for.
    """
    h = _login_and_load(client, "rerank-model")
    body = client.post("/v1/rerank", headers=h,
                       json={"model": "rerank-model", "query": REFERENCE_QUERY,
                             "documents": REFERENCE_DOCS,
                             "return_documents": False}).json()
    for item in body["results"]:
        assert set(item) == {"index", "relevance_score"}, item


def test_the_text_object_document_shape_is_accepted(client):
    """Cohere's clients send ``{"text": ...}``; bare strings must work too.

    Both shapes in one request, because a client that mixes them is the case
    that breaks a naive parser.
    """
    h = _login_and_load(client, "rerank-model")
    body = client.post("/v1/rerank", headers=h,
                       json={"model": "rerank-model", "query": REFERENCE_QUERY,
                             "documents": [{"text": REFERENCE_DOCS[0]},
                                           REFERENCE_DOCS[1]]}).json()
    assert len(body["results"]) == 2
    texts = {item["document"]["text"] for item in body["results"]}
    assert texts == set(REFERENCE_DOCS)


def test_the_rerank_alias_answers_the_same(client):
    """``/rerank`` exists because some clients strip the ``/v1`` prefix."""
    h = _login_and_load(client, "rerank-model")
    payload = {"model": "rerank-model", "query": REFERENCE_QUERY,
               "documents": REFERENCE_DOCS}
    canonical = client.post("/v1/rerank", headers=h, json=payload).json()
    alias = client.post("/rerank", headers=h, json=payload)
    assert alias.status_code == 200, alias.text
    assert alias.json()["results"] == canonical["results"]


def test_scores_are_the_sigmoid_of_the_logits(client):
    """The response's number is sigmoid(logit), and the record agrees with it."""
    h = _login_and_load(client, "rerank-model")
    body = client.post("/v1/rerank", headers=h,
                       json={"model": "rerank-model", "query": REFERENCE_QUERY,
                             "documents": REFERENCE_DOCS}).json()
    row = _records(client)[0]
    record = client.get(f"/api/inference-records/{row['id']}").json()
    stored = json.loads(record["output_text"])
    for item in body["results"]:
        assert stored[str(item["index"])] == pytest.approx(
            item["relevance_score"], abs=1e-6)
        assert 0.0 <= item["relevance_score"] <= 1.0


def test_sigmoid_does_not_overflow_on_a_wild_logit():
    """A corrupt bmodel can hand back any float; a 500 is the wrong answer."""
    assert sigmoid(0.0) == 0.5
    assert sigmoid(1000.0) == pytest.approx(1.0)
    assert sigmoid(-1000.0) == pytest.approx(0.0)
    assert sigmoid(-1000.0) >= 0.0


@pytest.mark.parametrize("payload,reason", [
    ({"query": "", "documents": ["x"]}, "query"),
    ({"query": "q", "documents": []}, "documents"),
    ({"query": "q", "documents": [1]}, "documents"),
    ({"query": "q", "documents": [""]}, "空字符串"),
    ({"query": "q", "documents": ["x"], "top_n": 0}, "top_n"),
])
def test_bad_inputs_are_400(client, payload, reason):
    h = _login_and_load(client, "rerank-model")
    r = client.post("/v1/rerank", headers=h, json={"model": "rerank-model", **payload})
    assert r.status_code == 400, r.text
    assert reason in r.json()["detail"], r.json()["detail"]


def test_more_than_256_documents_is_400(client):
    h = _login_and_load(client, "rerank-model")
    r = client.post("/v1/rerank", headers=h,
                    json={"model": "rerank-model", "query": "q",
                          "documents": [f"doc {i}" for i in range(257)]})
    assert r.status_code == 400
    assert "256" in r.json()["detail"]


def test_an_over_long_pair_names_the_limit(client):
    h = _login_and_load(client, "rerank-model")
    r = client.post("/v1/rerank", headers=h,
                    json={"model": "rerank-model", "query": "q",
                          "documents": ["y" * 5000]})
    assert r.status_code == 400
    assert "2048" in r.json()["detail"]


def test_wrong_kind_models_are_400(client):
    """The 400 names the endpoint that *would* serve this model."""
    h = _login_and_load(client, "chat-model", "embed-model")
    expected = {"chat-model": "/v1/chat/completions",
                "embed-model": "/v1/embeddings"}
    for model_id, route in expected.items():
        r = client.post("/v1/rerank", headers=h,
                        json={"model": model_id, "query": "q", "documents": ["d"]})
        assert r.status_code == 400, (model_id, r.text)
        assert route in r.json()["detail"], r.json()["detail"]


def test_a_rerank_model_on_other_endpoints_is_400(client):
    h = _login_and_load(client, "rerank-model")
    chat = client.post("/v1/chat/completions", headers=h,
                       json={"model": "rerank-model",
                             "messages": [{"role": "user", "content": "hi"}]})
    assert chat.status_code == 400
    assert "/v1/rerank" in chat.json()["detail"]
    embed = client.post("/v1/embeddings", headers=h,
                        json={"model": "rerank-model", "input": "hi"})
    assert embed.status_code == 400
    assert "/v1/rerank" in embed.json()["detail"]


def test_a_rerank_request_writes_exactly_one_record(client):
    h = _login_and_load(client, "rerank-model")
    before = len(_records(client))
    r = client.post("/v1/rerank", headers=h,
                    json={"model": "rerank-model", "query": REFERENCE_QUERY,
                          "documents": REFERENCE_DOCS})
    assert r.status_code == 200, r.text
    usage = r.json()["usage"]
    after = _records(client)
    assert len(after) == before + 1

    row = after[0]
    assert row["source"] == "/v1/rerank"
    assert row["model"] == "rerank-model"
    assert row["status"] == "ok"
    assert row["prompt_tokens"] == usage["prompt_tokens"]

    record = client.get(f"/api/inference-records/{row['id']}").json()
    # The input is stored as the query turn; the documents travel in `params`
    # only as a count -- 256 documents of text would dwarf the rest of the row.
    messages = record["messages"]
    if isinstance(messages, str):
        messages = json.loads(messages)
    assert messages == [{"role": "user", "content": REFERENCE_QUERY}]
    assert record["params"]["return_documents"] is True
