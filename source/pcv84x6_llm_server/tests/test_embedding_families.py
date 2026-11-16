"""Two Qwen3-Embedding builds, one vector space (MYS-2706).

The service now offers a second embedding build -- the same weights compiled at
``-s 512`` -- as an optional short-text档. A static graph computes its whole
compiled length on every forward, so seq512 is ~3.5x faster on a short text
(83 ms vs 291 ms at 484 tokens) while producing the *same* vector, because
padding is masked. Measured on `.157`: seq512 and seq2048 agree to seven
decimals on every text both accept (``docs/research/aux-dynamic-seq.md`` §7).

That equality is the whole reason ``vector_family`` exists. A knowledge base
records the id it was built with, and the checks around it used to compare
**ids**: built with ``qwen3-embedding-0.6b`` (seq2048), searched while
``qwen3-embedding-0.6b-seq512`` is loaded, the vector stage skipped with "向量
空间不可比" -- which is false, and which only a full rebuild could clear. The
comparison is now by family, and these tests pin both halves of it:

* same family -> interchangeable, for ingest and for search;
* different family -> still refused, with the same wording as before.

The length half is separate: a seq512 build *does* refuse a chunk a seq2048
build accepted, so ingest has to split it. That path already existed (PR #120,
``Ingestor._embed_fitted``); what these tests add is that it is reached through
the real app with the real refusal, at the shorter SEQLEN.

Nothing here asserts on *meaning*: the mock's embeddings are hashed. The
assertions are about which stage ran, which model served it, and what was
written down.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.models import (
    ModelInfo,
    ModelManager,
    catalogue_vector_family,
    discover_models,
    same_vector_family,
    vector_family,
)
from app.main import create_app

#: The bmodel names the catalogue's downloads land as. The two differ only in
#: the ``seq`` field, which is exactly the difference the family exists to see
#: past -- and the difference the mock worker reads its SEQLEN from.
LONG_ID = "qwen3-embedding-0.6b"
SHORT_ID = "qwen3-embedding-0.6b-seq512"
LONG_BMODEL = "qwen3-embedding-0.6b_bf16"
SHORT_BMODEL = "qwen3-embedding-0.6b_bf16"
OTHER_BMODEL = "qwen3-embedding-1.5b_bf16"
RERANK_BMODEL = "bge-reranker-v2-m3_bf16"


def make_model(root: Path, name: str, bmodel: str, context: str) -> Path:
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{bmodel}_{context}_4core_static.bmodel").write_bytes(b"\x00" * 4096)
    (d / "config" / "config.json").write_text("{}")
    return d


@pytest.fixture()
def models_dir(tmp_path: Path) -> Path:
    """Both shipped builds under the ids a download installs them as, plus a
    third embedding **model** -- a different one, not a different graph of this
    one. Its name still starts with ``qwen3-embedding-`` so the scan calls it an
    embedding model; what makes it a different family is that nothing declares a
    family for its id, and an undeclared embedding model is its own.

    The directory name matters, and that is not an accident of the fixture: a
    build installed by the console lands in ``models/<catalogue id>/``, and the
    family is what the *catalogue* declares for that id. A build somebody
    dropped in under a name of their own gets its own family (the conservative
    default, pinned separately below).
    """
    root = tmp_path / "models"
    make_model(root, LONG_ID, LONG_BMODEL, "seq2048")
    make_model(root, SHORT_ID, SHORT_BMODEL, "seq512")
    make_model(root, "embed-other", OTHER_BMODEL, "seq2048")
    make_model(root, "rerank-model", RERANK_BMODEL, "seq2048")
    return root


@pytest.fixture()
def app(tmp_path: Path, models_dir: Path):
    app = create_app(
        data_dir=tmp_path / "data",
        models_dir=models_dir,
        backend_kind="mock",
        web_dir=tmp_path / "web",
        context_length_override=4096,
    )
    # On-demand loading on, as an operator who lets the knowledge base bring its
    # model up would have it. Several tests unload a model and expect the other
    # build to be picked up rather than the stage skipped.
    st = app.state.store.settings
    st.aux_idle_unload_min, st.aux_auto_load = 10, True
    app.state.store.save()
    app.state.models.aux_idle_unload_min, app.state.models.aux_auto_load = 10, True
    return app


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        yield c


# -- helpers ---------------------------------------------------------------
def load(client, *model_ids: str) -> None:
    for model_id in model_ids:
        r = client.post(f"/api/models/{model_id}/load")
        assert r.status_code == 200, r.text


def unload(client, *model_ids: str) -> None:
    for model_id in model_ids:
        r = client.post(f"/api/models/{model_id}/unload")
        assert r.status_code == 200, r.text


def new_kb(client, name: str = "演示库") -> str:
    r = client.post("/api/apps/kb", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["kb"]["id"]


def upload(client, kb: str, filename: str, data: bytes) -> None:
    r = client.post(f"/api/apps/kb/{kb}/docs",
                    files={"file": (filename, data, "application/octet-stream")})
    assert r.status_code == 200, r.text


def wait_ready(client, kb: str, timeout: float = 60.0) -> list[dict]:
    import time

    deadline = time.monotonic() + timeout
    docs: list[dict] = []
    while time.monotonic() < deadline:
        docs = client.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
        if docs and all(d["status"] not in ("queued", "parsing", "ocr", "embedding")
                        for d in docs):
            return docs
        time.sleep(0.05)
    raise AssertionError(
        f"documents did not settle in {timeout}s: "
        f"{[(d['name'], d['status']) for d in docs]}")


def search(client, kb: str, query: str = "盘点") -> dict:
    r = client.post(f"/api/apps/kb/{kb}/search", json={"query": query})
    assert r.status_code == 200, r.text
    return r.json()


def listing(client) -> dict:
    return client.get("/api/apps/kb").json()["kbs"][0]


# -- the rule itself --------------------------------------------------------
def test_the_catalogue_declares_one_family_for_both_builds():
    """The field is what the rest of the file relies on, so it is pinned here.

    A catalogue entry that forgot ``vector_family`` would not fail loudly -- the
    model would quietly become its own family, and a library built with the other
    build would refuse it. That is the exact bug this feature removes, so the two
    entries are asserted together rather than one at a time.
    """
    long_family = catalogue_vector_family("qwen3-embedding-0.6b")
    short_family = catalogue_vector_family("qwen3-embedding-0.6b-seq512")
    assert long_family and short_family
    assert long_family == short_family == "qwen3-embedding-0.6b"
    # Everything else declares none, and an unknown id answers None.
    assert catalogue_vector_family("bge-reranker-v2-m3") is None
    assert catalogue_vector_family("not-a-model") is None


def test_a_model_with_no_declared_family_is_its_own():
    """The conservative default, and the reason it is conservative.

    An embedding build somebody dropped into ``models/`` by hand has no catalogue
    entry. Assuming it shares a family would mean writing vectors that cannot be
    compared into a library and never noticing; assuming it does not costs one
    rebuild. Non-embedding kinds have no vectors at all, so they get no family.
    """
    assert vector_family("hand-built-embed", "embedding") == "hand-built-embed"
    assert vector_family("hand-built-embed", "embedding", "declared") == "declared"
    assert vector_family("some-chat", "chat") == ""
    assert vector_family("some-rerank", "rerank") == ""
    assert not same_vector_family("", "")      # neither side has vectors
    assert not same_vector_family("a", "")
    assert same_vector_family("a", "a")


def test_the_scan_gives_both_builds_the_same_family(tmp_path: Path, models_dir: Path):
    """End to end from disk: the scan is where the family is actually assigned.

    ``qwen3-embedding-0.6b`` is the catalogue's id and takes the declared family;
    ``embed-short`` is not in the catalogue and still shares it, because the
    family is a property of the *model*, read off the bmodel name -- not of
    whichever directory it happens to sit in.
    """
    found = {m.model_id: m for m in discover_models(models_dir)}
    assert found[LONG_ID].vector_family == "qwen3-embedding-0.6b"
    assert found[SHORT_ID].vector_family == "qwen3-embedding-0.6b"
    assert found["embed-other"].vector_family == "embed-other"
    assert found["rerank-model"].vector_family == ""
    # The SEQLEN each worker will enforce, which is the other half of MYS-2706.
    assert found[LONG_ID].context_length == 2048
    assert found[SHORT_ID].context_length == 512


def test_the_family_reaches_the_models_api(client):
    """It has to be visible: an operator diagnosing a skipped vector stage reads
    ``/api/models``, and "these two are the same space" is not derivable from the
    ids or the file names."""
    models = {m["id"]: m for m in client.get("/api/models").json()["models"]}
    assert models[LONG_ID]["vector_family"] == "qwen3-embedding-0.6b"
    assert models[SHORT_ID]["vector_family"] == "qwen3-embedding-0.6b"
    assert models["embed-other"]["vector_family"] == "embed-other"
    assert models["rerank-model"]["vector_family"] == ""


# -- ingest ----------------------------------------------------------------
def test_a_library_built_with_seq2048_accepts_a_document_under_seq512(client):
    """The first half of "两档互通": append with the sibling loaded.

    Built with seq2048, the operator unloads it, loads seq512, and uploads
    another document. Before the family check this failed the document with
    "该知识库的向量由 qwen3-embedding-0.6b 建立，当前加载的是 embed-short" -- a
    rebuild demanded for a difference that is not one. Now it is `ready`, the
    matrix grew, and ``kb.embedding_model`` still records what built the library.
    """
    load(client, LONG_ID)
    kb = new_kb(client)
    upload(client, kb, "a.txt", "仓库盘点由仓管员执行。".encode())
    assert wait_ready(client, kb)[0]["status"] == "ready"
    assert listing(client)["embedding_model"] == LONG_ID
    rows_before = client.app.state.kb_store.load_vectors(kb).shape[0]

    unload(client, LONG_ID)
    load(client, SHORT_ID)
    upload(client, kb, "b.txt", "盘点差异率超过千分之五须由财务复核。".encode())
    docs = wait_ready(client, kb)
    assert all(d["status"] == "ready" for d in docs), docs

    matrix = client.app.state.kb_store.load_vectors(kb)
    assert matrix.shape[0] > rows_before, "the new document's rows were appended"
    # The recorded build does not move: the library's *own* history is the
    # seq2048 build, and a sibling that can read the same space does not rewrite
    # it. (Only a Reindex does, because that re-encodes every row.)
    assert listing(client)["embedding_model"] == LONG_ID


def test_a_library_built_with_seq512_accepts_a_document_under_seq2048(client):
    """The other direction, so the rule is not one-way by accident."""
    load(client, SHORT_ID)
    kb = new_kb(client)
    upload(client, kb, "a.txt", "仓库盘点由仓管员执行。".encode())
    assert wait_ready(client, kb)[0]["status"] == "ready"
    assert listing(client)["embedding_model"] == SHORT_ID

    unload(client, SHORT_ID)
    load(client, LONG_ID)
    upload(client, kb, "b.txt", "盘点差异率超过千分之五须由财务复核。".encode())
    assert all(d["status"] == "ready" for d in wait_ready(client, kb))
    assert listing(client)["embedding_model"] == SHORT_ID


def test_a_different_family_is_still_refused_with_the_same_wording(client):
    """The refusal this feature must not weaken.

    ``embed-other`` is a different model, so appending to a seq2048 library with
    it stays a `failed` document carrying the pre-existing message -- the test
    would be worthless if "same family" had been implemented as "any embedding
    model".
    """
    load(client, LONG_ID)
    kb = new_kb(client)
    upload(client, kb, "a.txt", "仓库盘点由仓管员执行。".encode())
    assert wait_ready(client, kb)[0]["status"] == "ready"

    unload(client, LONG_ID)
    load(client, "embed-other")
    upload(client, kb, "b.txt", "盘点差异率超过千分之五须由财务复核。".encode())
    docs = wait_ready(client, kb)
    failed = [d for d in docs if d["status"] == "failed"]
    assert len(failed) == 1, docs
    assert LONG_ID in failed[0]["error"]
    assert "embed-other" in failed[0]["error"]
    assert "重建索引" in failed[0]["error"]


# -- search ----------------------------------------------------------------
def test_a_seq2048_library_searches_under_a_loaded_seq512_build(client):
    """The acceptance criterion: only seq512 loaded, a seq2048 library still ranks.

    This is the deployment the档 exists for -- a board that keeps only the short
    build resident to save 248 MiB and halve the per-text cost -- so the vector
    stage must run, not skip. The stage's ``models`` entry names the model that
    actually served it, which is how the console shows it.
    """
    load(client, LONG_ID)
    kb = new_kb(client)
    upload(client, kb, "a.txt", "仓库盘点由仓管员在每个季度末执行。".encode())
    upload(client, kb, "b.txt", "盘点差异率超过千分之五须由财务复核。".encode())
    assert all(d["status"] == "ready" for d in wait_ready(client, kb))
    assert search(client, kb)["stages"]["vector"]["status"] == "ok"

    unload(client, LONG_ID)
    load(client, SHORT_ID)
    body = search(client, kb)
    assert body["stages"]["vector"]["status"] == "ok", body["stages"]["vector"]
    assert body["models"]["embedding"] == SHORT_ID


def test_a_different_family_still_skips_the_vector_stage(client):
    """And says exactly what it said before, naming both models and the rebuild."""
    load(client, LONG_ID)
    kb = new_kb(client)
    upload(client, kb, "a.txt", "仓库盘点由仓管员在每个季度末执行。".encode())
    assert wait_ready(client, kb)[0]["status"] == "ready"

    unload(client, LONG_ID)
    load(client, "embed-other")
    stage = search(client, kb)["stages"]["vector"]
    assert stage["status"] == "skipped", stage
    assert "embed-other" in stage["reason"]
    assert LONG_ID in stage["reason"]
    assert "重建索引" in stage["reason"]


def test_the_recorded_build_is_reloaded_in_preference_to_its_sibling(client):
    """Nothing loaded: the model the library records wins over its sibling.

    A sibling is an *acceptable* answer, not a preferred one -- re-encoding the
    query with the build the library was actually built with keeps the two sides
    of the comparison on one graph, and costs nothing when both are installed.
    """
    load(client, SHORT_ID)
    kb = new_kb(client)
    upload(client, kb, "a.txt", "仓库盘点由仓管员执行。".encode())
    assert wait_ready(client, kb)[0]["status"] == "ready"
    assert listing(client)["embedding_model"] == SHORT_ID
    unload(client, SHORT_ID)

    body = search(client, kb)
    assert body["stages"]["vector"]["status"] == "ok", body["stages"]["vector"]
    assert body["models"]["embedding"] == SHORT_ID, (
        "on-demand load must bring up the library's own build, not whichever "
        "sibling sorts first")


def test_reindex_onto_a_sibling_keeps_the_library_searchable(client):
    """``POST /reindex`` with only the sibling up records the sibling.

    Rebuilding is the documented way to migrate a library to another model, and
    it has to work *within* a family too: the vectors it writes are new, and the
    model it records has to be the one that wrote them -- otherwise the next
    search would compare seq512-written vectors against a recorded seq2048 and
    (correctly) see a mismatch.
    """
    load(client, LONG_ID)
    kb = new_kb(client)
    upload(client, kb, "a.txt", "仓库盘点由仓管员执行。".encode())
    assert wait_ready(client, kb)[0]["status"] == "ready"

    unload(client, LONG_ID)
    load(client, SHORT_ID)
    r = client.post(f"/api/apps/kb/{kb}/reindex")
    assert r.status_code == 200, r.text
    assert r.json()["job"]["model"] == SHORT_ID
    assert all(d["status"] == "ready" for d in wait_ready(client, kb))
    assert listing(client)["embedding_model"] == SHORT_ID
    assert search(client, kb)["stages"]["vector"]["status"] == "ok"


# -- the length half -------------------------------------------------------
def test_a_600_token_chunk_is_split_and_pooled_under_seq512(client):
    """Over the short build's SEQLEN: split, pooled, one vector, document ready.

    The mock counts a text's **UTF-8 bytes** as its tokens, so 600 ASCII
    characters is 600 tokens -- over 512 and under 2048. That is the case the
    seq512 档 creates and the seq2048 档 does not, and it must not fail the
    document: ``Ingestor._embed_fitted`` halves the chunk until the worker
    accepts each piece and pools the piece vectors back into one row
    (PR #120). Driven through the real app, the real worker and the real refusal
    -- the same shape as ``test_kb_api.py::test_a_dense_document_is_indexed_not_failed``.

    The chunker's 1000-character ceiling means this is the *chunk* the ingest
    path sees, so the split happens inside the embedding stage rather than in
    the chunker.
    """
    load(client, SHORT_ID)
    kb = new_kb(client)
    # One chunk (no sentence terminator, under MAX_CHUNK_CHARS), 600 mock tokens.
    text = ("ab" * 300).encode()
    assert len(text) == 600
    upload(client, kb, "dense.txt", text)

    docs = wait_ready(client, kb)
    assert docs[0]["status"] == "ready", docs[0]
    assert docs[0]["chunks"] == 1, "the chunker did not cut it; the embedder did"

    # One row per chunk, whatever the number of forward passes behind it.
    matrix = client.app.state.kb_store.load_vectors(kb)
    assert matrix.shape[0] == 1, matrix.shape
    # A pooled vector is a mean of unit vectors, renormalised: still unit length.
    norm = float((matrix[0] ** 2).sum() ** 0.5)
    assert abs(norm - 1.0) < 1e-4, norm

    body = search(client, kb)
    assert body["stages"]["vector"]["status"] == "ok", body["stages"]["vector"]


def test_the_same_600_token_chunk_is_one_forward_under_seq2048(client):
    """The control for the test above: no split, same document shape.

    Without it, "600 tokens is split under seq512" would pass just as well if the
    split path always ran, which would mean every ordinary chunk paying for
    halving and pooling.
    """
    load(client, LONG_ID)
    kb = new_kb(client)
    upload(client, kb, "dense.txt", ("ab" * 300).encode())
    docs = wait_ready(client, kb)
    assert docs[0]["status"] == "ready", docs[0]
    matrix = client.app.state.kb_store.load_vectors(kb)
    assert matrix.shape[0] == 1


def test_the_short_build_refuses_an_input_past_512(client):
    """``/v1/embeddings`` keeps obeying the model's own SEQLEN, per model.

    No automatic档 selection there (by design, MYS-2706 §4): the caller names a
    model, and an input past *that* model's length is a 400 quoting the number.
    """
    load(client, SHORT_ID)
    key = client.post("/api/keys", json={"name": "k"}).json()["key"]
    h = {"Authorization": f"Bearer {key}"}
    ok = client.post("/v1/embeddings", headers=h,
                     json={"model": SHORT_ID, "input": "a" * 512})
    assert ok.status_code == 200, ok.text
    r = client.post("/v1/embeddings", headers=h,
                    json={"model": SHORT_ID, "input": "a" * 513})
    assert r.status_code == 400, r.text
    assert "512" in r.json()["detail"], r.json()["detail"]


# -- resolution ordering ---------------------------------------------------
@pytest.mark.asyncio
async def test_load_for_prefers_the_family_then_the_recorded_model(tmp_path: Path,
                                                                    monkeypatch):
    """The ordering, on the manager itself rather than through HTTP.

    Three rules, and they are checked in one place because they only make sense
    together: the recorded model wins when it is loaded; within one family a
    loaded sibling is accepted; and a family with **no** candidate on disk falls
    back to the unfiltered list so the caller still gets a model and can report
    the mismatch honestly, instead of "没有已下载的模型" for a model that is
    plainly there.
    """
    root = tmp_path / "models"
    for model_id in ("long", "short", "other"):
        make_model(root, model_id, "qwen3-embedding-0.6b_bf16", "seq2048")
    mgr = ModelManager(root, backend_kind="mock", log_dir=tmp_path / "logs")
    mgr.refresh()

    def family_of(model_id: str) -> str:
        return "fam" if model_id in ("long", "short") else "other-fam"

    for info in mgr.list():
        info.vector_family = family_of(info.model_id)

    def mark_loaded(*model_ids: str) -> None:
        for info in mgr.list():
            info.loaded = info.model_id in model_ids
            info.loaded_at = 1.0 if info.loaded else None
            info.operation = None

    async def no_load(model_id):
        raise AssertionError(f"load({model_id}) should not have been attempted")

    monkeypatch.setattr(mgr, "load", no_load)

    # 1. The recorded model wins even though a sibling is newer.
    mark_loaded("short")
    mgr.get("short").loaded_at = 90.0
    info, reason = await mgr.load_for("embedding", preferred="long", family="fam")
    assert info is not None and info.model_id == "short", reason

    # 2. With the sibling unloaded, the family alone finds the recorded model
    #    among the candidates -- and no other family's model can be picked.
    mark_loaded()
    candidates = mgr.candidates_for("embedding", family="fam", preferred="long")
    assert [m.model_id for m in candidates] == ["long", "short"], (
        "preferred first, then the rest of the family; `other` excluded")

    # 3. A family with nothing on disk falls back rather than reporting empty.
    assert {m.model_id for m in mgr.candidates_for("embedding", family="absent")} == {
        "long", "short", "other"}
