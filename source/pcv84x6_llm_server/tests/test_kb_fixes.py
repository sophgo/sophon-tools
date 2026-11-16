"""The fixes from the first review round, each pinned by the bug it describes.

These are grouped by the failure they prevent rather than by the module they
live in, because that is how they were found: a review of the aggregate index's
lifecycle, read as "what happens if two things touch it at once, and what
happens if the box dies in between".

They run against the mock backend and real model workers, so the things that
matter here -- a queue that really is serial, an embedding RPC that really
happens -- are the real ones. What is stubbed is only what the test is *about*:
the barrier's timing, and a 100-page scan that would take minutes to OCR.
"""

from __future__ import annotations

import io
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.apps.kb import ingest as kb_ingest
from app.apps.kb.chunker import normalise
from app.main import create_app

# The `app`/`client`/`models_dir` fixtures are reused from the end-to-end suite
# rather than rebuilt: these tests drive the same mock workers, and a second copy
# of that setup would drift from it.
from .test_kb_api import (  # noqa: F401 - the fixtures, imported for pytest
    DATA,
    app,
    client,
    load,
    models_dir,
    new_kb,
    search,
    seed_library,
    unload,
    upload,
    wait_ready,
)


# -- 1/2: reindex must not race a delete, and must not launder failed docs ----
def test_a_mutation_during_reindex_is_refused_with_409(client):
    """The window a reindex opens is minutes long; a delete inside it is a 409.

    Without the barrier the job reads the chunk list, embeds for minutes, then
    writes a matrix built from rows a delete has since removed -- one row too
    many, permanently. The refusal is the cheap half of the fix; the re-check
    under the lock in ``Ingestor.reindex`` is the other.
    """
    load(client, "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)
    docs = client.get(f"/api/apps/kb/{kb}/docs").json()["docs"]

    ingestor = client.app.state.kb_ingestor
    # Hold the barrier the way a long job does, without waiting for one.
    ingestor.begin_reindex(kb)
    try:
        refused = client.delete(f"/api/apps/kb/{kb}/docs/{docs[0]['id']}")
        assert refused.status_code == 409
        assert "重建索引" in refused.json()["detail"]

        again = client.post(f"/api/apps/kb/{kb}/reindex")
        assert again.status_code == 409

        added = client.post(
            f"/api/apps/kb/{kb}/docs",
            files={"file": ("新.txt", "盘点制度。".encode(), "text/plain")})
        assert added.status_code == 409
    finally:
        ingestor.end_reindex(kb)

    # And once the job is over the same calls work again.
    assert client.delete(f"/api/apps/kb/{kb}/docs/{docs[0]['id']}").status_code == 200


def test_deleting_a_library_releases_a_queued_reindex_claim(client):
    """A claim must not outlive the job that made it.

    ``reindex`` releases its own claim in ``finally``, but a job dropped from
    the queue never runs. Without this the library would answer 409 to every
    mutation forever -- including for a *new* library, since the claim is keyed
    by id and ids are never reused, but the process would leak one entry per
    abandoned rebuild.
    """
    load(client, "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)
    ingestor = client.app.state.kb_ingestor

    ingestor.begin_reindex(kb)
    ingestor.submit(kb_ingest.Job(kb_id=kb, request=client.app.state))
    ingestor.forget(kb)
    assert not ingestor.is_reindexing(kb)


def test_reindex_leaves_failed_and_queued_documents_alone(client):
    """A rebuild re-embeds the library's chunks; it does not launder its records.

    A `failed` document has no chunks in the matrix, so a reindex that relabelled
    it `ready` would claim vectors that were never built and take away the Retry
    button that is the operator's only way to fix it.
    """
    load(client, "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)
    ready_doc = client.get(f"/api/apps/kb/{kb}/docs").json()["docs"][0]

    # One document that cannot be built: on-demand loading off, so an unloaded
    # model means "not available" (MYS-2657: with it on, the job loads the model
    # and there is nothing to fail).
    client.post("/api/settings", json={"aux_auto_load": False})
    unload(client, "embed-model")
    upload(client, kb, "后来.txt", "另一个盘点要求。".encode())
    settled = wait_ready(client, kb)
    failed_doc = next(d for d in settled if d["name"] == "后来.txt")
    assert failed_doc["status"] == "failed"

    client.post("/api/settings", json={"aux_auto_load": True})
    load(client, "embed-model")
    assert client.post(f"/api/apps/kb/{kb}/reindex").status_code == 200
    wait_ready(client, kb)

    after = {d["id"]: d for d in client.get(f"/api/apps/kb/{kb}/docs").json()["docs"]}
    assert after[ready_doc["id"]]["status"] == "ready"
    assert after[failed_doc["id"]]["status"] == "failed", \
        "a reindex must not mark a document it never embedded as ready"
    assert after[failed_doc["id"]]["error"]
    # And the Retry that failure advertises still works.
    assert client.post(
        f"/api/apps/kb/{kb}/docs/{failed_doc['id']}/retry").status_code == 200


# -- 3: a misaligned matrix is a durable state -------------------------------
def test_a_misaligned_matrix_is_flagged_and_never_appended_to(client):
    """The desync used to heal wrongly: the matrix was dropped, then the *next*
    upload appended only its own rows to a chunk file holding all of them.

    The flag is what makes the state durable -- the vector stage refuses, the
    API says ``needs_reindex``, and nothing writes a matrix until the rebuild.
    """
    load(client, "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)
    store = client.app.state.kb_store
    chunks = store.load_chunks(kb)
    vectors = store.load_vectors(kb)
    assert len(chunks) == len(vectors)

    # The state a crash between the two writes leaves behind: chunks written,
    # matrix one row short.
    store.save_vectors(kb, vectors[:-1])

    body = search(client, kb)
    stage = body["stages"]["vector"]
    assert stage["status"] == "skipped"
    assert "重建" in stage["reason"]
    listing = client.get("/api/apps/kb").json()["kbs"][0]
    assert listing["needs_reindex"] is True
    assert store.load_vectors(kb) is None, "the unusable matrix must be dropped"

    # An upload into a flagged library is refused rather than embedded and
    # thrown away (K3): the document would spend minutes being embedded, then be
    # labelled `ready` with no vector in the matrix. The file is still on disk,
    # so the operator can upload it again after the rebuild.
    refused = client.post(
        f"/api/apps/kb/{kb}/docs",
        files={"file": ("续.txt", "补充的盘点要求。".encode(), "text/plain")})
    assert refused.status_code == 409
    assert "重建索引" in refused.json()["detail"]
    assert store.load_vectors(kb) is None
    assert search(client, kb)["stages"]["vector"]["status"] == "skipped"
    assert client.get("/api/apps/kb").json()["kbs"][0]["needs_reindex"] is True

    # The rebuild is what clears it.
    assert client.post(f"/api/apps/kb/{kb}/reindex").status_code == 200
    wait_ready(client, kb)
    listing = client.get("/api/apps/kb").json()["kbs"][0]
    assert listing["needs_reindex"] is False
    assert search(client, kb)["stages"]["vector"]["status"] == "ok"
    chunks = store.load_chunks(kb)
    assert len(chunks) == len(store.load_vectors(kb))

    # And the upload the library refused goes through afterwards.
    upload(client, kb, "续.txt", "补充的盘点要求。".encode())
    wait_ready(client, kb)
    assert search(client, kb)["stages"]["vector"]["status"] == "ok"
    assert len(store.load_chunks(kb)) == len(store.load_vectors(kb))


def test_deleting_a_document_while_misaligned_does_not_500(client):
    """``_remove_rows`` indexed the matrix with chunk indices, unguarded."""
    load(client, "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)
    store = client.app.state.kb_store
    docs = client.get(f"/api/apps/kb/{kb}/docs").json()["docs"]

    # More rows than chunks: the shape that made `matrix[keep_idx]` overflow.
    store.save_vectors(kb, np.vstack([
        store.load_vectors(kb), np.zeros((5, store.load_vectors(kb).shape[1]),
                                        dtype="float32")]))

    assert client.delete(f"/api/apps/kb/{kb}/docs/{docs[0]['id']}").status_code == 200
    remaining = store.load_chunks(kb)
    assert all(c["doc_id"] != docs[0]["id"] for c in remaining)
    assert client.get("/api/apps/kb").json()["kbs"][0]["needs_reindex"] is True


# -- 5: a queued upload survives a restart ----------------------------------
def test_a_document_queued_at_restart_can_be_retried(client, tmp_path, models_dir):
    """The original is written by the POST, so a restart cannot lose it.

    Before, the bytes lived in the queue entry and landed on disk only when the
    worker reached them. A restart dropped the queue, and Retry then answered
    "原始文件不存在" -- with no way to recover short of re-uploading.
    """
    load(client, "embed-model")
    kb = new_kb(client)
    upload(client, kb, "排队中.txt", "仓库盘点的制度说明。".encode())
    doc = wait_ready(client, kb)[0]
    store = client.app.state.kb_store

    # `queued` is the state a restart leaves a document whose job never ran --
    # which is also every document when several were submitted at once.
    store.write_doc_meta(kb, doc["id"], {**doc, "status": "queued",
                                        "progress": {"stage": "queued", "done": 0,
                                                     "total": 1}})

    restarted = create_app(
        data_dir=tmp_path / "data", models_dir=models_dir,
        backend_kind="mock", web_dir=tmp_path / "web",
        context_length_override=4096)
    with TestClient(restarted) as fresh:
        assert fresh.post("/api/login", json={"password": "admin"}).status_code == 200
        assert fresh.get(f"/api/apps/kb/{kb}/docs").json()["docs"][0]["status"] == "failed"
        # The file was on disk all along, so the retry is a real one.
        r = fresh.post(f"/api/apps/kb/{kb}/docs/{doc['id']}/retry")
        assert r.status_code == 200, r.text
        wait_ready(fresh, kb)
        assert fresh.get(
            f"/api/apps/kb/{kb}/docs").json()["docs"][0]["status"] == "ready"


# -- 6: the queue restarts after a data-directory move ----------------------
@pytest.mark.asyncio
async def test_the_worker_is_running_after_a_data_move(tmp_path, models_dir):
    """``stop_everything`` cancelled the worker and nothing restarted it.

    So every document uploaded after a move sat in ``queued`` forever, with no
    worker behind it -- and one that was mid-parse read as "still processing".
    This drives the rebind hook the storage manager calls, and checks the two
    things it must do: revive the worker, and fail what the move interrupted.
    """
    app = create_app(
        data_dir=tmp_path / "data", models_dir=models_dir,
        backend_kind="mock", web_dir=tmp_path / "web",
        context_length_override=4096)
    ingestor = app.state.kb_ingestor
    store = app.state.kb_store
    kb = store.create_kb("搬迁库")
    doc_id = "a" * 32
    (store.docs_dir(kb.id) / doc_id / "pages").mkdir(parents=True)
    store.write_doc_meta(kb.id, doc_id, {
        "id": doc_id, "name": "半路.txt", "type": "txt", "bytes": 10,
        "status": "parsing", "progress": {"stage": "parsing", "done": 0, "total": 1},
        "created_at": time.time()})

    # What the move does to the queue before it copies.
    await ingestor.stop()
    assert ingestor._task is None

    # The parts the move copies: the KB store's root, as a whole.
    old_root = store.root
    moved_kb_root = tmp_path / "moved" / "apps" / "kb"
    moved_kb_root.parent.mkdir(parents=True)
    old_root.rename(moved_kb_root)

    # The hook storage calls once the copy is proven (`create_app`'s `rebind`).
    app.state.storage._post_switch(tmp_path / "moved")

    assert ingestor.store.root == moved_kb_root
    assert ingestor._task is not None and not ingestor._task.done(), \
        "the queue worker must be running again after the move"
    meta = ingestor.store.read_doc_meta(kb.id, doc_id)
    assert meta["status"] == "failed"
    assert meta["error"] == "服务重启，处理中断"
    await ingestor.stop()


# -- 7: cheap refusals happen at upload time --------------------------------
def test_a_pdf_over_the_page_limit_is_refused_at_upload(client):
    kb = new_kb(client)
    import pypdfium2 as pdfium

    buffer = io.BytesIO()
    document = pdfium.PdfDocument.new()
    for _ in range(4):
        document.new_page(200, 200)
    document.save(buffer)
    document.close()

    import app.apps.kb.parse as kb_parse
    original = kb_parse.MAX_PDF_PAGES
    kb_parse.MAX_PDF_PAGES = 2
    try:
        r = client.post(f"/api/apps/kb/{kb}/docs",
                        files={"file": ("大.pdf", buffer.getvalue(),
                                        "application/octet-stream")})
        assert r.status_code == 400
        assert "页" in r.json()["detail"]
    finally:
        kb_parse.MAX_PDF_PAGES = original
    assert client.get(f"/api/apps/kb/{kb}/docs").json()["docs"] == []


def test_a_pdf_that_cannot_be_opened_is_refused_at_upload(client):
    kb = new_kb(client)
    r = client.post(f"/api/apps/kb/{kb}/docs",
                    files={"file": ("坏.pdf", b"%PDF-1.7\nnot really",
                                    "application/octet-stream")})
    assert r.status_code == 400
    assert "PDF" in r.json()["detail"]


def test_undecodable_text_is_refused_at_upload(client):
    kb = new_kb(client)
    r = client.post(f"/api/apps/kb/{kb}/docs",
                    files={"file": ("伪装.txt", b"\xff\xff\xff\xff", "text/plain")})
    assert r.status_code == 400
    assert "UTF-8" in r.json()["detail"]
    assert client.get(f"/api/apps/kb/{kb}/docs").json()["docs"] == []


def test_an_image_that_cannot_be_decoded_is_refused_at_upload(client):
    kb = new_kb(client)
    r = client.post(f"/api/apps/kb/{kb}/docs",
                    files={"file": ("截图.png", b"\x89PNG\r\n\x1a\n garbage",
                                    "image/png")})
    assert r.status_code == 400
    assert "图片" in r.json()["detail"]


def test_an_image_over_the_pixel_cap_is_refused_at_upload(client, monkeypatch):
    """A 50 MiB photo is legal by size and lethal by pixel count on 2.6 GB."""
    import app.apps.kb.parse as kb_parse

    monkeypatch.setattr(kb_parse, "MAX_IMAGE_PIXELS", 1000 * 1000)
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (2000, 1000), (250, 250, 250)).save(buffer, format="PNG")
    kb = new_kb(client)
    r = client.post(f"/api/apps/kb/{kb}/docs",
                    files={"file": ("大图.png", buffer.getvalue(), "image/png")})
    assert r.status_code == 400
    assert "Mpx" in r.json()["detail"] or "像素" in r.json()["detail"]


# -- 8: auxiliary calls are recorded and bounded ----------------------------
def _records(client) -> list[dict]:
    r = client.get("/api/inference-records?limit=200")
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_a_library_build_records_every_embedding_call(client):
    """``embed_passages`` exists so a build is auditable like a console test."""
    load(client, "embed-model")
    kb = new_kb(client)
    before = len(_records(client))
    seed_library(client, kb)
    added = _records(client)[: len(_records(client)) - before]
    assert added, "an embedding batch must leave an inference record"
    for record in added:
        assert record["source"] == "/api/apps/kb"
        assert record["actor_name"] == "kb"
        assert record["model"] == "embed-model"


def test_a_search_records_the_query_embedding_and_the_rerank(client):
    load(client, "embed-model", "rerank-model")
    kb = new_kb(client)
    seed_library(client, kb)
    before = len(_records(client))
    search(client, kb)
    added = _records(client)[: len(_records(client)) - before]
    sources = {r["source"] for r in added}
    assert sources == {"/api/apps/kb"}
    assert {r["actor_name"] for r in added} == {"kb"}


def test_candidates_over_the_ceiling_is_a_400(client):
    kb = new_kb(client)
    r = client.post(f"/api/apps/kb/{kb}/search",
                    json={"query": "盘点", "top_k": 5, "candidates": 1000})
    assert r.status_code == 400
    assert "candidates" in r.json()["detail"]


# -- 10: OCR boxes belong to the chunk that reports them -------------------
def test_boxes_follow_the_chunk_when_lines_have_padding_and_repeats():
    """The regression this was written for.

    ``ingest`` used to derive each line's offset as ``len(text) + 1`` over the
    *raw* OCR output, while ``chunk_text`` measures ``char_start`` in the
    *normalised* page text. Trailing spaces and a repeated row -- both of which
    a real table produces -- make the two diverge, and a chunk then reports its
    neighbour's boxes.
    """
    from app.apps.kb.ingest import _chunks_for
    from app.apps.kb.parse import OcrLine, Page, ParsedDoc

    texts = ["  项目     金额  ", "A 100", "A 100", "合计 200  "]
    # One page, four OCR lines, with the boxes tagged so the test can tell which
    # line a chunk picked up.
    lines = [OcrLine(text=text, box=[[float(i), 0.0], [float(i) + 1, 0.0],
                                     [float(i) + 1, 1.0], [float(i), 1.0]])
             for i, text in enumerate(texts)]
    page = Page(number=1, text="\n".join(texts), source="ocr", lines=lines)
    doc = ParsedDoc(kind="pdf", pages=[page])

    chunks = _chunks_for(doc)
    assert chunks
    text = normalise(page.text)
    for chunk in chunks:
        # The chunk's reported range must select exactly its own body.
        assert text[chunk.char_start:chunk.char_end] == chunk.text
        # And its boxes must be the lines that range actually covers.
        expected = []
        cursor = 0
        for raw, line in zip(texts, lines):
            cleaned = normalise(raw)
            if not cleaned:
                continue
            start = text.find(cleaned, cursor)
            assert start >= 0
            end = start + len(cleaned)
            if start < chunk.char_end and end > chunk.char_start:
                expected.append(line.box)
            cursor = end
        assert chunk.boxes == expected, (chunk.text, chunk.boxes, expected)


def test_a_repeated_line_is_matched_in_reading_order():
    """Two identical rows must not both resolve to the first one."""
    from app.apps.kb.ingest import _pair_offsets_with_boxes
    from app.apps.kb.parse import OcrLine, Page

    texts = ["A 100", "A 100"]
    first = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    second = [[0.0, 2.0], [1.0, 2.0], [1.0, 3.0], [0.0, 3.0]]
    lines = [OcrLine(text=texts[0], box=first), OcrLine(text=texts[1], box=second)]
    page = Page(number=1, text="\n".join(texts), source="ocr", lines=lines)
    from app.apps.kb.ingest import _pair_offsets_with_boxes

    offsets = _pair_offsets_with_boxes(normalise(page.text), texts,
                                       {0: first, 1: second})
    assert [offset for offset, _ in offsets] == [0, 6], \
        "each occurrence must be matched at its own position, in reading order"


# -- 11: retry and delete while a document is being processed --------------
def test_retry_of_a_document_in_flight_is_a_409(client):
    load(client, "embed-model")
    kb = new_kb(client)
    upload(client, kb, "处理中.txt", "仓库盘点的制度说明。".encode())
    doc = wait_ready(client, kb)[0]
    store = client.app.state.kb_store
    store.write_doc_meta(kb, doc["id"], {
        **doc, "status": "parsing",
        "progress": {"stage": "parsing", "done": 0, "total": 1}})

    r = client.post(f"/api/apps/kb/{kb}/docs/{doc['id']}/retry")
    assert r.status_code == 409
    assert "处理中" in r.json()["detail"] or "parsing" in r.json()["detail"]


def test_progress_on_a_deleted_document_is_not_an_error(client):
    """The parse reports progress per page; the delete removes the record.

    That race is normal -- the stop flag ends the parse on the *next* page --
    so the write has to be a no-op rather than a raised ``KbNotFound`` that
    turns a successful delete into a traceback and a `failed` record for a
    document nobody can see. Found on the real device: deleting a 110-page scan
    at page 45 logged "indexing … failed" from inside the progress callback.
    """
    load(client, "embed-model")
    kb = new_kb(client)
    upload(client, kb, "删除中.txt", "仓库盘点。".encode())
    doc = wait_ready(client, kb)[0]
    ingestor = client.app.state.kb_ingestor

    # The record is gone, exactly as it is mid-delete.
    client.app.state.kb_store.delete_doc(kb, doc["id"])
    job = kb_ingest.Job(kb_id=kb, doc_id=doc["id"], request=client.app.state)
    assert ingestor._update(job, status="parsing") == {}
    ingestor._progress(job, "parsing", 3, 10)  # must not raise


def test_deleting_a_document_stops_a_long_parse(client, monkeypatch):
    """A delete must cut a 300-page OCR pass short, not wait for it.

    The parser polls a stop flag between pages. Without it the worker spent
    minutes on a file the operator had already removed, and the delete's own
    ``rmtree`` raced the parser's writes into the same directory.

    The page count is inflated so the parse is still running when the delete
    lands: the assertion is that the parser never reaches a page *after* the
    delete returned, which is what "stops at a page boundary" means.
    """
    load(client, "embed-model", "ocr-model")
    kb = new_kb(client)

    import app.apps.kb.parse as kb_parse

    reached: list[int] = []
    real_parse = kb_parse.parse_pdf

    def slow_parse(data, *, ocr=None, write_preview=None, on_page=None,
                   should_stop=None):
        def tracking(done, total, scanned):
            reached.append(done)
            if on_page is not None:
                on_page(done, total, scanned)
            # Hold each page long enough for the delete in the test to land.
            time.sleep(0.05)

        return real_parse(data, ocr=ocr, write_preview=write_preview,
                          on_page=tracking, should_stop=should_stop)

    monkeypatch.setattr(kb_parse, "parse_pdf", slow_parse)

    upload(client, kb, "多页.pdf", (DATA / "text.pdf").read_bytes())
    deadline = time.monotonic() + 10
    doc = None
    while time.monotonic() < deadline:
        docs = client.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
        if docs and docs[0]["status"] in ("parsing", "ocr"):
            doc = docs[0]
            break
        time.sleep(0.02)
    assert doc is not None, "the document never started parsing"

    at_delete = len(reached)
    assert client.delete(f"/api/apps/kb/{kb}/docs/{doc['id']}").status_code == 200
    # Whatever it was doing, it must not report another page afterwards.
    time.sleep(0.4)
    assert len(reached) <= at_delete + 1, (
        f"the parser kept going after the delete: pages {reached}")
    assert client.get(f"/api/apps/kb/{kb}/docs").json()["docs"] == []


def test_the_in_flight_flag_is_cleared_after_a_job(client):
    """The stop set must not leak into a later retry of the same document."""
    load(client, "embed-model")
    kb = new_kb(client)
    upload(client, kb, "制度.txt", "仓库盘点。".encode())
    wait_ready(client, kb)
    ingestor = client.app.state.kb_ingestor
    assert ingestor._cancelled == set()
