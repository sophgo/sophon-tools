"""``/api/apps/kb`` end to end over the mock backend.

Drives real model workers (the mock engine) so everything between an HTTP body
and the recorded row is exercised: session auth, the upload reader, the serial
ingestion queue, the embedding/rerank/chat RPCs, the hybrid pipeline and the SSE
answer.

What the mock cannot supply is *meaning*: its embeddings are hashed and its OCR
invents words. So the assertions are about the contract -- which stages ran,
which were skipped and why, that the ordering follows the stage that was allowed
to decide it, that the citations match the chunks the prompt numbered -- and
never about which document "should" be most relevant.
"""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

DATA = Path(__file__).resolve().parent / "data" / "kb"

EMBED_BMODEL = "qwen3-embedding-0.6b_bf16"
RERANK_BMODEL = "bge-reranker-v2-m3_bf16"
CHAT_BMODEL = "qwen3.6-35b-a3b-int4-autow4bf16"
OCR_BMODEL = "ppocrv6-medium-det_f16_736_bm1684x2_static_20261103.bmodel"


# -- fixtures ---------------------------------------------------------------
def make_model(root: Path, name: str, bmodel: str, context: str = "seq2048") -> Path:
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{bmodel}_{context}_4core_static.bmodel").write_bytes(b"\x00" * 4096)
    (d / "config" / "config.json").write_text("{}")
    return d


@pytest.fixture()
def models_dir(tmp_path: Path) -> Path:
    root = tmp_path / "models"
    make_model(root, "embed-model", EMBED_BMODEL)
    make_model(root, "rerank-model", RERANK_BMODEL, context="seq2048")
    make_model(root, "chat-model", CHAT_BMODEL, context="seq2048")
    make_model(root, "ocr-model", OCR_BMODEL, context="736")
    return root


@pytest.fixture()
def app(tmp_path: Path, models_dir: Path):
    return turn_aux_on(create_app(
        data_dir=tmp_path / "data",
        models_dir=models_dir,
        backend_kind="mock",
        web_dir=tmp_path / "web",
        context_length_override=4096,
    ))


def turn_aux_on(app):
    """Opt in to idle unload (10 min) and on-demand loading, as an operator would.

    Both are off by default since v0.6.28; these tests are about how they behave
    once on. Saved to the store too, so an app restarted on the same data
    directory starts with them on as well.
    """
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


def upload(client, kb: str, filename: str, data: bytes) -> list[dict]:
    """POST one file, returning the queued document records."""
    r = client.post(
        f"/api/apps/kb/{kb}/docs",
        files={"file": (filename, data, "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    return r.json()["docs"]


def wait_ready(client, kb: str, timeout: float = 30.0) -> list[dict]:
    """Poll /docs until nothing is queued or in flight, then return the records."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        docs = client.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
        if docs and all(d["status"] not in ("queued", "parsing", "ocr", "embedding")
                        for d in docs):
            return docs
        time.sleep(0.05)
    raise AssertionError(
        f"documents did not settle in {timeout}s: "
        f"{[(d['name'], d['status']) for d in docs]}")


def search(client, kb: str, **body) -> dict:
    r = client.post(f"/api/apps/kb/{kb}/search", json={"query": "盘点", **body})
    assert r.status_code == 200, r.text
    return r.json()


def sse_frames(response) -> list:
    """The parsed ``data:`` payloads of an SSE response, ``[DONE]`` included."""
    out = []
    for line in response.text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):]
        out.append(payload if payload == "[DONE]" else json.loads(payload))
    return out


# -- knowledge bases --------------------------------------------------------
def test_the_routes_require_the_admin_session(app, client):
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/apps/kb").status_code == 401
        assert anonymous.post("/api/apps/kb", json={"name": "x"}).status_code == 401


def test_a_library_can_be_created_listed_and_deleted(client):
    kb = new_kb(client, "制度库")
    listing = client.get("/api/apps/kb").json()["kbs"]
    assert [entry["name"] for entry in listing] == ["制度库"]
    assert listing[0]["docs"] == 0
    assert listing[0]["chunks"] == 0
    assert listing[0]["embedding_model"] is None

    assert client.delete(f"/api/apps/kb/{kb}").status_code == 200
    assert client.get("/api/apps/kb").json()["kbs"] == []
    assert client.delete(f"/api/apps/kb/{kb}").status_code == 404


def test_an_empty_name_is_refused(client):
    assert client.post("/api/apps/kb", json={"name": "  "}).status_code == 400


def test_a_path_that_is_not_an_id_cannot_escape_the_data_root(client):
    """A ``kb_id`` is a uuid4 hex; anything else is a 404, not a path traversal."""
    assert client.get("/api/apps/kb/..%2f..%2fetc/docs").status_code == 404
    assert client.get("/api/apps/kb/not-an-id/docs").status_code == 404


# -- upload and ingestion ---------------------------------------------------
def test_a_txt_upload_is_queued_then_indexed(client):
    load(client, "embed-model")
    kb = new_kb(client)
    docs = upload(client, kb, "制度.txt",
                  "仓库盘点由仓管员执行。盘点前必须冻结出入库操作。".encode("utf-8"))
    assert len(docs) == 1
    assert docs[0]["status"] == "queued"
    assert docs[0]["type"] == "txt"

    settled = wait_ready(client, kb)
    assert settled[0]["status"] == "ready"
    assert settled[0]["chunks"] >= 1
    assert settled[0]["pages"] == 1
    assert settled[0]["text_pages"] == 1
    assert settled[0]["ocr_pages"] == 0

    listing = client.get("/api/apps/kb").json()["kbs"]
    assert listing[0]["chunks"] == settled[0]["chunks"]
    assert listing[0]["embedding_model"] == "embed-model"
    assert listing[0]["dims"] == 1024


def test_a_gb18030_upload_is_read_as_chinese(client):
    load(client, "embed-model")
    kb = new_kb(client)
    upload(client, kb, "旧系统导出.txt", "仓库盘点差异处理办法。".encode("gb18030"))
    settled = wait_ready(client, kb)
    assert settled[0]["status"] == "ready"
    chunks = client.get(f"/api/apps/kb/{kb}/docs/{settled[0]['id']}/chunks").json()
    assert "仓库盘点差异处理办法" in chunks["chunks"][0]["text"]


def test_a_binary_file_renamed_to_txt_is_refused_at_upload(client):
    """Undecodable text is a 400 from the POST, not a `failed` row later.

    The card asks for the cheap checks at upload time: a decode is one call, and
    a document that can never be read should not take a place in a serial queue
    whose progress an operator is watching. (The tests covering the same refusal
    from the queue's side are in ``test_kb_fixes.py``.)
    """
    kb = new_kb(client)
    r = client.post(f"/api/apps/kb/{kb}/docs",
                    files={"file": ("伪装.txt", b"\xff\xff\xff\xff\xff",
                                    "application/octet-stream")})
    assert r.status_code == 400
    assert "UTF-8" in r.json()["detail"] and "GB18030" in r.json()["detail"]
    assert client.get(f"/api/apps/kb/{kb}/docs").json()["docs"] == []


def test_an_unsupported_suffix_is_refused_at_upload_time(client):
    kb = new_kb(client)
    r = client.post(f"/api/apps/kb/{kb}/docs",
                    files={"file": ("报告.docx", b"PK\x03\x04", "application/octet-stream")})
    assert r.status_code == 400
    assert "不支持的文件类型" in r.json()["detail"]
    assert client.get(f"/api/apps/kb/{kb}/docs").json()["docs"] == []


def test_one_bad_file_refuses_the_whole_request(client):
    """A body is accepted or refused as a whole; nothing is half-queued."""
    kb = new_kb(client)
    r = client.post(
        f"/api/apps/kb/{kb}/docs",
        files=[
            ("file", ("好.txt", "第一份文档。".encode(), "text/plain")),
            ("file", ("坏.docx", b"PK\x03\x04", "application/octet-stream")),
        ],
    )
    assert r.status_code == 400
    assert "不支持的文件类型" in r.json()["detail"]
    assert client.get(f"/api/apps/kb/{kb}/docs").json()["docs"] == []


def test_an_empty_upload_is_refused(client):
    kb = new_kb(client)
    r = client.post(f"/api/apps/kb/{kb}/docs",
                    files={"file": ("空.txt", b"", "text/plain")})
    assert r.status_code == 400


def test_several_files_in_one_request_are_all_queued(client):
    load(client, "embed-model")
    kb = new_kb(client)
    r = client.post(
        f"/api/apps/kb/{kb}/docs",
        files=[
            ("file", ("一.txt", "第一份文档。".encode(), "text/plain")),
            ("file", ("二.md", "# 第二份\n\n内容。".encode(), "text/markdown")),
        ],
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["docs"]) == 2
    settled = wait_ready(client, kb)
    assert {d["status"] for d in settled} == {"ready"}
    assert {d["type"] for d in settled} == {"txt", "md"}


def test_an_md_upload_keeps_its_type(client):
    load(client, "embed-model")
    kb = new_kb(client)
    upload(client, kb, "说明.md", "# 标题\n\n正文内容。".encode())
    settled = wait_ready(client, kb)
    assert settled[0]["type"] == "md"


def test_an_oversized_upload_is_refused(client, monkeypatch):
    """The cap is 50 MiB, and it is enforced while reading, not after."""
    import app.apps.kb.parse as kb_parse

    monkeypatch.setattr(kb_parse, "MAX_FILE_BYTES", 1024)
    kb = new_kb(client)
    r = client.post(f"/api/apps/kb/{kb}/docs",
                    files={"file": ("大.txt", b"x" * 4096, "text/plain")})
    assert r.status_code == 400
    assert "超过单个文件上限" in r.json()["detail"]


# -- PDFs and OCR -----------------------------------------------------------
def test_a_text_pdf_is_parsed_and_gets_previews(client):
    load(client, "embed-model")
    kb = new_kb(client)
    upload(client, kb, "制度.pdf", (DATA / "text.pdf").read_bytes())
    settled = wait_ready(client, kb)
    doc = settled[0]
    assert doc["status"] == "ready"
    assert doc["type"] == "pdf"
    assert doc["pages"] == 2
    assert doc["text_pages"] == 2
    assert doc["ocr_pages"] == 0

    for page in (1, 2):
        r = client.get(f"/api/apps/kb/{kb}/docs/{doc['id']}/pages/{page}.png")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(f"/api/apps/kb/{kb}/docs/{doc['id']}/pages/3.png").status_code == 404


def test_a_scanned_pdf_goes_through_ocr_when_the_model_is_loaded(client):
    load(client, "embed-model", "ocr-model")
    kb = new_kb(client)
    upload(client, kb, "扫描件.pdf", (DATA / "scan.pdf").read_bytes())
    settled = wait_ready(client, kb)
    doc = settled[0]
    assert doc["status"] == "ready"
    assert doc["ocr_pages"] == 1
    assert doc["text_pages"] == 0
    chunks = client.get(f"/api/apps/kb/{kb}/docs/{doc['id']}/chunks").json()["chunks"]
    assert chunks and all(c["source"] == "ocr" for c in chunks)
    assert chunks[0]["boxes"], "an OCR chunk must carry the boxes it covers"


def test_a_scanned_pdf_without_ocr_fails_and_says_why(client):
    """No OCR *available* and no text is the one case that must be `failed`.

    Since MYS-2657 "no model loaded" no longer means "no model available": the
    ingest job loads one. The failure this test is about -- a scan with nothing to
    read it -- is reached by turning on-demand loading off, which is also what an
    operator with no OCR model on disk at all sees.
    """
    client.post("/api/settings", json={"aux_auto_load": False})
    kb = new_kb(client)
    upload(client, kb, "扫描件.pdf", (DATA / "scan.pdf").read_bytes())
    settled = wait_ready(client, kb)
    assert settled[0]["status"] == "failed"
    assert "OCR" in settled[0]["error"]
    assert any("第 1 页" in w for w in settled[0]["warnings"])


def test_an_image_is_ocrd(client):
    load(client, "embed-model", "ocr-model")
    kb = new_kb(client)
    # A PNG the mock can read: it parses the header for the reported size.
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), (200, 200, 200)).save(buffer, format="PNG")
    upload(client, kb, "截图.png", buffer.getvalue())
    settled = wait_ready(client, kb)
    assert settled[0]["type"] == "image"
    assert settled[0]["status"] == "ready"
    assert settled[0]["ocr_pages"] == 1


def test_a_mixed_pdf_records_both_page_counts(client):
    load(client, "embed-model", "ocr-model")
    kb = new_kb(client)
    upload(client, kb, "混合.pdf", (DATA / "mixed.pdf").read_bytes())
    settled = wait_ready(client, kb)
    assert settled[0]["status"] == "ready"
    assert settled[0]["text_pages"] == 1
    assert settled[0]["ocr_pages"] == 1
    chunks = client.get(f"/api/apps/kb/{kb}/docs/{settled[0]['id']}/chunks").json()["chunks"]
    sources = {c["source"] for c in chunks}
    assert sources == {"text", "ocr"}
    assert {c["page"] for c in chunks} == {1, 2}


def test_a_document_with_no_text_anywhere_is_failed(client):
    """A page with neither a text layer nor anything OCR can read is `failed`.

    On-demand loading has to be off for this to be observable on the mock: the
    mock OCR invents three lines for any image it can decode, so with an OCR model
    available a blank page would come back "ready" with fabricated text. On the
    board, real OCR returns no lines for a blank page and the document fails
    either way -- the mock is what makes the no-model case the honest one to test.
    """
    client.post("/api/settings", json={"aux_auto_load": False})
    kb = new_kb(client)
    upload(client, kb, "空白.pdf", (DATA / "blank.pdf").read_bytes())
    settled = wait_ready(client, kb)
    assert settled[0]["status"] == "failed"
    assert "没有提取到任何文字" in settled[0]["error"]
    assert settled[0]["chunks"] == 0


# -- search -----------------------------------------------------------------
def seed_library(client, kb: str) -> None:
    """Two documents, built with whatever embedding model is loaded.

    Callers load one first when they need a *vector* stage; the answer tests do
    not, because an answer only needs text -- and keeping the two concerns apart
    is what lets ``seed_library`` serve both.
    """
    if not any(m["loaded"] and m["kind"] == "embedding"
               for m in client.get("/api/models").json()["models"]):
        load(client, "embed-model")
    upload(client, kb, "制度.txt",
           "仓库盘点由仓管员在每个季度末执行。盘点前必须冻结出入库操作。".encode())
    upload(client, kb, "差异.txt",
           "盘点差异率超过千分之五时必须由财务复核，并出具差异说明。".encode())
    wait_ready(client, kb)


def test_search_reports_every_stage(client):
    load(client, "embed-model", "rerank-model")
    kb = new_kb(client)
    seed_library(client, kb)
    body = search(client, kb, query="盘点差异", top_k=3, candidates=10)
    assert set(body["stages"]) == {"bm25", "vector", "fusion", "rerank"}
    for name in ("bm25", "vector", "fusion", "rerank"):
        stage = body["stages"][name]
        assert stage["status"] in ("ok", "skipped")
        assert isinstance(stage["ms"], (int, float))
        if stage["status"] == "ok":
            assert stage["hits"]
            assert stage["reason"] is None
        else:
            assert stage["reason"], name
    assert body["models"] == {"embedding": "embed-model", "rerank": "rerank-model"}
    assert body["timings"]["total_ms"] >= 0


def test_search_results_carry_the_full_score_breakdown(client):
    load(client, "embed-model", "rerank-model")
    kb = new_kb(client)
    seed_library(client, kb)
    body = search(client, kb, query="盘点差异", top_k=3, candidates=10)
    assert body["results"]
    for item in body["results"]:
        assert set(item["scores"]) == {
            "bm25", "bm25_rank", "vector", "vector_rank",
            "rrf", "rrf_rank", "rerank"}
        for key in ("chunk_id", "doc_id", "doc_name", "page", "source", "text", "boxes"):
            assert key in item
    assert [item["rank"] for item in body["results"]] == list(
        range(1, len(body["results"]) + 1))


def test_without_an_embedding_model_a_document_fails_and_search_stays_bm25(client):
    """Building needs the model; searching does not.

    The design's rule is "建库需要 embedding", so a document that cannot get one
    is ``failed`` with a reason and a working Retry -- not ``ready`` with a silent
    hole where its vectors should be. Since MYS-2657 "cannot get one" means the
    model is not on disk or on-demand loading is off, not merely "not loaded": the
    job loads it. Both halves are checked here, because the difference matters to
    an operator -- the first is fixed by loading, the second by downloading.
    """
    load(client, "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)

    # Unloaded: the job loads it again, and the document is built.
    unload(client, "embed-model")
    upload(client, kb, "后来.txt", "新增的盘点要求。".encode())
    settled = wait_ready(client, kb)
    later = next(d for d in settled if d["name"] == "后来.txt")
    assert later["status"] == "ready", later
    assert later["chunks"] > 0

    # Not available at all: the document fails, with a reason naming the model.
    client.post("/api/settings", json={"aux_auto_load": False})
    unload(client, "embed-model")
    upload(client, kb, "再次.txt", "又一个盘点要求。".encode())
    settled = wait_ready(client, kb)
    again = next(d for d in settled if d["name"] == "再次.txt")
    assert again["status"] == "failed"
    assert "embedding" in again["error"]
    assert again["chunks"] == 0

    # And searching the built documents still works while the model is down.
    body = search(client, kb)
    assert body["stages"]["bm25"]["status"] == "ok"
    assert body["results"]
    assert body["stages"]["vector"]["status"] == "skipped"
    assert body["models"]["embedding"] is None
    for item in body["results"]:
        assert item["scores"]["vector_rank"] is None


def test_without_a_reranker_the_rrf_order_is_returned(client):
    client.post("/api/settings", json={"aux_auto_load": False})
    load(client, "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)
    body = search(client, kb)
    assert body["stages"]["rerank"]["status"] == "skipped"
    assert "rerank" in body["stages"]["rerank"]["reason"]
    rrf_ranks = [item["scores"]["rrf_rank"] for item in body["results"]]
    assert rrf_ranks == sorted(rrf_ranks)
    for item in body["results"]:
        assert item["scores"]["rerank"] is None


def test_an_embedding_model_mismatch_skips_the_vector_stage(client):
    """A library built with one model cannot be searched with another."""
    load(client, "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)
    unload(client, "embed-model")
    make_model(Path(client.app.state.models.models_root), "embed-other", EMBED_BMODEL)
    client.app.state.models.refresh()
    load(client, "embed-other")

    body = search(client, kb)
    stage = body["stages"]["vector"]
    assert stage["status"] == "skipped"
    assert "embed-other" in stage["reason"] and "embed-model" in stage["reason"]
    assert "重建索引" in stage["reason"]


def test_the_stage_switches_are_honoured(client):
    load(client, "embed-model", "rerank-model")
    kb = new_kb(client)
    seed_library(client, kb)
    body = search(client, kb, use_bm25=False, use_vector=False, use_rerank=False)
    assert body["stages"]["bm25"]["status"] == "skipped"
    assert body["stages"]["vector"]["status"] == "skipped"
    assert body["stages"]["rerank"]["status"] == "skipped"
    assert body["stages"]["fusion"]["status"] == "skipped"
    assert body["results"] == []


def test_only_bm25_leaves_the_vector_and_rerank_stages_off(client):
    load(client, "embed-model", "rerank-model")
    kb = new_kb(client)
    seed_library(client, kb)
    body = search(client, kb, use_vector=False, use_rerank=False)
    assert body["stages"]["bm25"]["status"] == "ok"
    assert body["stages"]["vector"]["status"] == "skipped"
    assert body["stages"]["rerank"]["status"] == "skipped"
    assert body["results"]


def test_top_k_larger_than_candidates_is_refused(client):
    kb = new_kb(client)
    r = client.post(f"/api/apps/kb/{kb}/search",
                    json={"query": "盘点", "top_k": 10, "candidates": 5})
    assert r.status_code == 400
    assert "candidates" in r.json()["detail"]


def test_an_empty_query_is_refused(client):
    kb = new_kb(client)
    r = client.post(f"/api/apps/kb/{kb}/search", json={"query": "   "})
    assert r.status_code == 400


def test_search_on_an_empty_library_degrades_rather_than_failing(client):
    kb = new_kb(client)
    body = search(client, kb)
    assert body["results"] == []
    assert body["stages"]["bm25"]["status"] == "skipped"


def test_reindex_rebuilds_vectors_with_the_current_model(client):
    load(client, "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)
    assert search(client, kb)["stages"]["vector"]["status"] == "ok"

    before = client.app.state.kb_store.load_vectors(kb).copy()

    r = client.post(f"/api/apps/kb/{kb}/reindex")
    assert r.status_code == 200, r.text
    assert r.json()["job"]["model"] == "embed-model"
    assert r.json()["job"]["documents"] == 2

    # Every document moves through the embedding stage together: a reindex spans
    # the library, so no document may read `ready` while its neighbours are being
    # redone. (This is also what catches the library-wide job writing progress to
    # an empty document id -- that fails the job, not just the label.)
    docs = wait_ready(client, kb)
    assert all(d["status"] == "ready" for d in docs)

    listing = client.get("/api/apps/kb").json()["kbs"][0]
    assert listing["embedding_model"] == "embed-model"
    # Same texts and same model, so the same vectors -- the matrix was rebuilt
    # in place, not merely relabelled.
    after = client.app.state.kb_store.load_vectors(kb)
    assert after.shape == before.shape
    import numpy as np

    assert np.allclose(after, before, atol=1e-6)
    assert search(client, kb)["stages"]["vector"]["status"] == "ok"


def test_reindex_without_an_embedding_model_is_a_409(client):
    """A 409 when no embedding model can be brought up, not when it is merely idle.

    MYS-2657: pressing Reindex loads the model on demand, so the refusal needs a
    model that cannot be loaded -- which is what turning on-demand loading off
    leaves.
    """
    kb = new_kb(client)
    seed_library(client, kb)
    client.post("/api/settings", json={"aux_auto_load": False})
    unload(client, "embed-model")
    r = client.post(f"/api/apps/kb/{kb}/reindex")
    assert r.status_code == 409
    assert "embedding" in r.json()["detail"]


def test_reindex_loads_its_embedding_model_on_demand(client):
    """The other half: idle is not unavailable, so the button works."""
    kb = new_kb(client)
    seed_library(client, kb)
    unload(client, "embed-model")
    r = client.post(f"/api/apps/kb/{kb}/reindex")
    assert r.status_code == 200, r.text
    assert any(m["id"] == "embed-model" and m["loaded"]
               for m in client.get("/api/models").json()["models"])


# -- answer -----------------------------------------------------------------
def ready_chunk_ids(client, kb: str) -> list[str]:
    docs = client.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
    out: list[str] = []
    for doc in docs:
        out.extend(c["id"] for c in
                   client.get(f"/api/apps/kb/{kb}/docs/{doc['id']}/chunks").json()["chunks"])
    return out


def test_answer_streams_deltas_citations_and_done(client):
    load(client, "chat-model")
    kb = new_kb(client)
    seed_library(client, kb)
    ids = ready_chunk_ids(client, kb)[:2]

    r = client.post(f"/api/apps/kb/{kb}/answer",
                    json={"query": "盘点前要做什么", "chunk_ids": ids, "max_tokens": 40})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    frames = sse_frames(r)

    assert frames[-1] == "[DONE]"
    citations = [f for f in frames if isinstance(f, dict) and f.get("type") == "citations"]
    assert len(citations) == 1
    assert [item["n"] for item in citations[0]["items"]] == [1, 2]
    assert [item["chunk_id"] for item in citations[0]["items"]] == ids

    deltas = [f for f in frames if isinstance(f, dict)
              and f.get("object") == "chat.completion.chunk"
              and f.get("choices") and f["choices"][0]["delta"].get("content")]
    assert deltas, "the answer produced no text"
    finish = [f for f in frames if isinstance(f, dict) and f.get("choices")
              and f["choices"][0].get("finish_reason")]
    assert finish, "the stream never reported a finish_reason"
    usage = [f for f in frames if isinstance(f, dict) and f.get("usage")]
    assert usage and usage[0]["usage"]["total_tokens"] >= 0


def test_answer_without_a_chat_model_is_a_409(client):
    kb = new_kb(client)
    seed_library(client, kb)
    ids = ready_chunk_ids(client, kb)[:1]
    r = client.post(f"/api/apps/kb/{kb}/answer",
                    json={"query": "盘点", "chunk_ids": ids})
    assert r.status_code == 409
    assert "对话" in r.json()["detail"]


def test_answer_with_an_unknown_chunk_id_is_refused(client):
    load(client, "chat-model")
    kb = new_kb(client)
    seed_library(client, kb)
    r = client.post(f"/api/apps/kb/{kb}/answer",
                    json={"query": "盘点", "chunk_ids": ["nope:0"]})
    assert r.status_code == 400


def test_answer_with_no_chunk_ids_is_refused(client):
    load(client, "chat-model")
    kb = new_kb(client)
    seed_library(client, kb)
    r = client.post(f"/api/apps/kb/{kb}/answer", json={"query": "盘点", "chunk_ids": []})
    assert r.status_code == 400


def test_answer_with_a_model_of_the_wrong_kind_is_refused(client):
    load(client, "chat-model", "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)
    ids = ready_chunk_ids(client, kb)[:1]
    r = client.post(f"/api/apps/kb/{kb}/answer",
                    json={"query": "盘点", "chunk_ids": ids, "model": "embed-model"})
    assert r.status_code == 409


# -- deletion and restart ---------------------------------------------------
def test_deleting_a_document_keeps_chunks_and_vectors_aligned(client):
    load(client, "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)
    docs = client.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
    assert client.delete(f"/api/apps/kb/{kb}/docs/{docs[0]['id']}").status_code == 200

    chunk_lines = (client.app.state.kb_store.root / kb / "chunks.jsonl").read_text()
    rows = [line for line in chunk_lines.splitlines() if line.strip()]
    vectors = client.app.state.kb_store.load_vectors(kb)
    assert vectors is not None
    assert len(rows) == len(vectors), (len(rows), len(vectors))
    assert all(json.loads(r)["doc_id"] != docs[0]["id"] for r in rows)

    body = search(client, kb)
    assert body["stages"]["vector"]["status"] == "ok"
    assert all(item["doc_id"] != docs[0]["id"] for item in body["results"])


def test_deleting_the_last_document_clears_the_librarys_model(client):
    load(client, "embed-model")
    kb = new_kb(client)
    upload(client, kb, "唯一.txt", "盘点制度。".encode())
    doc = wait_ready(client, kb)[0]
    client.delete(f"/api/apps/kb/{kb}/docs/{doc['id']}")
    listing = client.get("/api/apps/kb").json()["kbs"][0]
    assert listing["chunks"] == 0
    assert listing["embedding_model"] is None
    assert listing["dims"] == 0
    # A new document can then be indexed by whatever model is loaded.
    upload(client, kb, "新.txt", "新的盘点制度。".encode())
    assert wait_ready(client, kb)[0]["status"] == "ready"


def test_deleting_a_library_removes_its_files(client):
    load(client, "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)
    root = client.app.state.kb_store.root / kb
    assert root.is_dir()
    assert client.delete(f"/api/apps/kb/{kb}").status_code == 200
    assert not root.exists()


def test_a_restart_marks_interrupted_documents_failed_and_retry_recovers(
        client, tmp_path, models_dir):
    """The queue lives in memory, so a restart can only fail what was in flight."""
    load(client, "embed-model")
    kb = new_kb(client)
    upload(client, kb, "中断.txt", "仓库盘点的制度说明。".encode())
    # A dead process cannot race recovery with writes from its old worker.
    assert client.portal is not None
    client.portal.call(client.app.state.kb_ingestor.stop)
    doc = client.get(f"/api/apps/kb/{kb}/docs").json()["docs"][0]
    # Simulate a process that died mid-parse: the record still says "parsing".
    store = client.app.state.kb_store
    store.write_doc_meta(kb, doc["id"], {**doc, "status": "parsing",
                                        "progress": {"stage": "parsing", "done": 0,
                                                     "total": 1}})

    restarted = create_app(
        data_dir=tmp_path / "data", models_dir=models_dir,
        backend_kind="mock", web_dir=tmp_path / "web",
        context_length_override=4096)
    with TestClient(restarted) as fresh:
        assert fresh.post("/api/login", json={"password": "admin"}).status_code == 200
        docs = fresh.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
        assert docs[0]["status"] == "failed"
        assert docs[0]["error"] == "服务重启，处理中断"
        assert docs[0]["progress"] is None

        assert fresh.post(f"/api/apps/kb/{kb}/docs/{doc['id']}/retry").status_code == 200
        wait_ready(fresh, kb)
        docs = fresh.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
        assert docs[0]["status"] == "ready"
        assert docs[0]["chunks"] >= 1


def test_retry_of_a_ready_document_is_a_409(client):
    load(client, "embed-model")
    kb = new_kb(client)
    upload(client, kb, "制度.txt", "盘点制度。".encode())
    doc = wait_ready(client, kb)[0]
    r = client.post(f"/api/apps/kb/{kb}/docs/{doc['id']}/retry")
    assert r.status_code == 409


def test_a_document_uploaded_without_the_model_can_be_retried_after_loading(client):
    """The operator sequence: upload with no model available, load it, press Retry.

    Since MYS-2657 the middle step is only needed when the model was *not*
    available (on-demand loading off, or nothing on disk). With it on (the
    fixture opts in) the upload builds itself, which is the point of the feature.
    """
    load(client, "embed-model")
    kb = new_kb(client)
    upload(client, kb, "首个.txt", "仓库盘点的制度说明。".encode())
    wait_ready(client, kb)

    # On-demand load on: an upload with the model unloaded builds itself.
    unload(client, "embed-model")
    upload(client, kb, "自动.txt", "自动加载的说明。".encode())
    settled = wait_ready(client, kb)
    auto = next(d for d in settled if d["name"] == "自动.txt")
    assert auto["status"] == "ready", auto

    # On-demand load off: the document fails, and Retry fixes it once a model is up.
    client.post("/api/settings", json={"aux_auto_load": False})
    unload(client, "embed-model")
    upload(client, kb, "后续.txt", "差异处理的办法。".encode())
    settled = wait_ready(client, kb)
    later = next(d for d in settled if d["name"] == "后续.txt")
    assert later["status"] == "failed"
    assert "embedding" in later["error"]

    client.post("/api/settings", json={"aux_auto_load": True})
    load(client, "embed-model")
    assert client.post(f"/api/apps/kb/{kb}/docs/{later['id']}/retry").status_code == 200
    wait_ready(client, kb)
    docs = client.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
    assert all(d["status"] == "ready" for d in docs)

    # The matrix still has exactly one row per chunk, in order.
    rows = [line for line in
            (client.app.state.kb_store.root / kb / "chunks.jsonl").read_text().splitlines()
            if line.strip()]
    vectors = client.app.state.kb_store.load_vectors(kb)
    assert len(rows) == len(vectors)
    assert search(client, kb)["stages"]["vector"]["status"] == "ok"


def test_original_file_download_returns_the_bytes(client):
    load(client, "embed-model")
    kb = new_kb(client)
    payload = "仓库盘点的制度说明。".encode()
    upload(client, kb, "原件.txt", payload)
    doc = wait_ready(client, kb)[0]
    r = client.get(f"/api/apps/kb/{kb}/docs/{doc['id']}/file")
    assert r.status_code == 200
    assert r.content == payload


def test_a_dense_document_is_indexed_not_failed(client):
    """Through the real app and the mock worker: no token-count shortcut, no fakes.

    1000 characters of CJK Extension B is one chunk at the chunker's character
    ceiling, but 4000 mock tokens (the mock counts UTF-8 bytes) -- over its
    SEQLEN. The worker refuses it; ingest must split it and index the document,
    not fail it (MYS-2696 review: a guard that only ran with a fake handle).
    """
    load(client, "embed-model")
    kb = new_kb(client, "稠密")
    text = "".join(chr(0x20000 + i % 500) for i in range(1000))
    upload(client, kb, "dense.txt", text.encode())
    docs = wait_ready(client, kb)
    assert docs[0]["status"] == "ready", docs[0]
    assert docs[0]["chunks"] >= 1
