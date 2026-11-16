"""The second review round (K3): the states a library could not get out of.

Every case here was reachable in a release and each one left the operator with
no way forward short of deleting the library: a document stuck reading
``ocr`` after a data-directory move, a rebuild refused because a rebuild had
failed, a delete answering 500 because the parser re-created the directory it
was removing. They are grouped in one file because they share the shape "two
things touch the library at once, or one of them is interrupted" -- the same
shape as ``test_kb_fixes``, one round later.

The mock backend and real model workers are reused from the end-to-end suite;
what is stubbed is only the timing a test is *about*.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.apps.kb import ingest as kb_ingest
from app.apps.kb.store import KbStore
from app.main import create_app

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


# -- 1: a data-directory move must not leave a document claiming to be in flight
@pytest.mark.asyncio
async def test_a_parse_still_running_across_a_move_cannot_write_to_the_new_root(
        tmp_path, models_dir):
    """The bug: ``stop()`` cancelled the asyncio task, not the ``to_thread`` work.

    A parse is a thread. Cancelling the task that awaits it leaves the thread
    running, still calling ``store.write_doc_meta`` per page -- and the move
    repointed ``Ingestor.store`` at the *new* root before ``recover`` ran, so the
    thread's next page write overwrote ``failed`` with ``ocr``. Retry then
    answered 409 ("正在处理中") for as long as the operator was willing to press
    it, and the document never finished because nothing was working on it.
    """
    kb_app = create_app(
        data_dir=tmp_path / "data", models_dir=models_dir,
        backend_kind="mock", web_dir=tmp_path / "web",
        context_length_override=4096)
    ingestor = kb_app.state.kb_ingestor
    store = kb_app.state.kb_store
    kb = store.create_kb("搬迁库")
    doc_id = "b" * 32
    (store.docs_dir(kb.id) / doc_id / "pages").mkdir(parents=True)
    store.write_doc_meta(kb.id, doc_id, {
        "id": doc_id, "name": "半路.txt", "type": "txt", "bytes": 10,
        "status": "ocr", "progress": {"stage": "ocr", "done": 4, "total": 9},
        "created_at": time.time()})

    # A job holding the *old* store, the way a running parse does. Its next
    # progress write must land on the library it started with -- and once that
    # library has moved away, must not be re-pointed at the new root.
    job = kb_ingest.Job(kb_id=kb.id, doc_id=doc_id, store=store)

    old_root = store.root
    moved_root = tmp_path / "moved" / "apps" / "kb"
    moved_root.parent.mkdir(parents=True)
    old_root.rename(moved_root)

    # The move's rebind: a new store on the new root, exactly what `rebind` does.
    ingestor.store = KbStore(moved_root)
    ingestor.recover()
    assert ingestor.store.read_doc_meta(kb.id, doc_id)["status"] == "failed"

    # The thread's next page lands *after* all of that.
    ingestor._progress(job, "ocr", 5, 9)

    meta = ingestor.store.read_doc_meta(kb.id, doc_id)
    assert meta["status"] == "failed", \
        "a parse from before the move wrote into the moved library"
    assert meta["error"] == "服务重启，处理中断"
    assert meta["progress"] is None
    await ingestor.stop()


@pytest.mark.asyncio
async def test_stop_waits_for_the_parse_thread_to_reach_a_page_boundary(
        tmp_path, models_dir):
    """``stop`` must not return while the parse thread is still writing.

    That is the other half of the move bug: even with the store pinned, a
    shutdown that returns immediately lets the copy begin while a thread has the
    old tree open and is still creating files in it. The stop flag ends the parse
    at the next page; this checks ``stop`` waits for that and not merely for the
    task.
    """
    kb_app = create_app(
        data_dir=tmp_path / "data", models_dir=models_dir,
        backend_kind="mock", web_dir=tmp_path / "web",
        context_length_override=4096)
    ingestor = kb_app.state.kb_ingestor
    store = kb_app.state.kb_store
    kb = store.create_kb("停止库")
    doc_id = "c" * 32
    (store.docs_dir(kb.id) / doc_id / "pages").mkdir(parents=True)
    store.write_doc_meta(kb.id, doc_id, {
        "id": doc_id, "name": "慢.pdf", "type": "pdf", "bytes": 10,
        "status": "parsing", "created_at": time.time()})
    (store.docs_dir(kb.id) / doc_id / "source.pdf").write_bytes(
        (DATA / "text.pdf").read_bytes())

    job = kb_ingest.Job(kb_id=kb.id, doc_id=doc_id, store=store, request=None)
    reached: list[int] = []
    released = threading.Event()

    def slow_parse(*args, **kwargs):
        # Stands in for a parser mid-document: it notices the stop flag only when
        # it comes back for the next page.
        for page in range(1, 40):
            reached.append(page)
            if kwargs.get("should_stop") and kwargs["should_stop"]():
                from app.apps.kb import parse as kb_parse

                raise kb_parse.Stopped("文档已被删除，处理中止")
            time.sleep(0.03)
        released.set()
        from app.apps.kb.parse import ParsedDoc

        return ParsedDoc(kind="pdf")

    import app.apps.kb.ingest as ingest_mod

    real_parse = ingest_mod.doc_parse.parse_pdf
    ingest_mod.doc_parse.parse_pdf = slow_parse
    try:
        ingestor.start()
        ingestor.submit(job)
        deadline = time.monotonic() + 5
        while not ingestor._parsing and time.monotonic() < deadline:
            await __import__("asyncio").sleep(0.01)
        assert ingestor._parsing, "the parse thread was never registered"

        await ingestor.stop()
        # ``stop`` returned only once the thread had left the document, so
        # nothing is writing under the library any more.
        assert not ingestor._parsing
        assert not released.is_set(), "the parse ran to the end instead of stopping"
        assert reached and max(reached) < 40
    finally:
        ingest_mod.doc_parse.parse_pdf = real_parse


# -- 2: a rebuild must be able to rescue a library a rebuild broke ------------
def test_reindex_recovers_a_library_whose_documents_all_failed(client):
    """A failed rebuild (or a restart during one) left the library unrecoverable.

    Every document read ``failed``, ``POST /reindex`` refused with "还没有可重建
    的文档", and Retry could not help: the library is still recorded against the
    old embedding model, so the document fails again at the model check. The only
    exit was deleting the library.
    """
    load(client, "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)
    store = client.app.state.kb_store
    docs = client.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
    assert docs

    # The state a rebuild interrupted half-way leaves: chunks on disk, no matrix,
    # the flag set, every document failed -- and the library still naming the
    # model the failed attempt was migrating away from.
    store.delete_vectors(kb)
    store.set_index_flag(kb, needs_reindex=True, embedding_model="old-embed")
    for meta in docs:
        meta["status"] = "failed"
        meta["error"] = "服务重启，处理中断"
        meta["progress"] = None
        store.write_doc_meta(kb, meta["id"], meta)

    r = client.post(f"/api/apps/kb/{kb}/reindex")
    assert r.status_code == 200, r.text
    assert r.json()["job"]["documents"] == len(docs)

    settled = wait_ready(client, kb)
    assert all(d["status"] == "ready" for d in settled), \
        [(d["name"], d["status"], d["error"]) for d in settled]
    listing = client.get("/api/apps/kb").json()["kbs"][0]
    assert listing["needs_reindex"] is False
    assert listing["embedding_model"] == "embed-model"
    vectors = store.load_vectors(kb)
    assert vectors is not None and len(vectors) == listing["chunks"]
    assert search(client, kb)["stages"]["vector"]["status"] == "ok"


def test_reindex_of_a_library_with_no_chunks_alone_is_still_refused(client):
    """The relaxation is "chunks, not `ready` documents" -- an empty library stays a 409."""
    load(client, "embed-model")
    kb = new_kb(client)
    r = client.post(f"/api/apps/kb/{kb}/reindex")
    assert r.status_code == 409
    assert "切片" in r.json()["detail"]


def test_reindex_does_not_launder_a_document_with_no_chunks(client):
    """The other half: only documents the chunk file actually contains are claimed.

    A document that failed before it was chunked has nothing to rebuild, so
    relabelling it ``ready`` would claim vectors that do not exist and take away
    the Retry that is the only way to fix it.
    """
    load(client, "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)
    store = client.app.state.kb_store

    # A record with no chunks in the file: an upload that failed at parse time.
    empty_id = "d" * 32
    (store.docs_dir(kb) / empty_id / "pages").mkdir(parents=True)
    (store.docs_dir(kb) / empty_id / "source.txt").write_bytes(b"x")
    store.write_doc_meta(kb, empty_id, {
        "id": empty_id, "name": "空.txt", "type": "txt", "bytes": 1,
        "status": "failed", "error": "没有提取到任何文字",
        "created_at": time.time()})

    assert client.post(f"/api/apps/kb/{kb}/reindex").status_code == 200
    wait_ready(client, kb)
    after = {d["id"]: d for d in client.get(f"/api/apps/kb/{kb}/docs").json()["docs"]}
    assert after[empty_id]["status"] == "failed"
    assert after[empty_id]["error"] == "没有提取到任何文字"
    assert all(after[i]["status"] == "ready"
               for i in after if i != empty_id)


# -- 3: delete must be deterministic against a running parse -----------------
def test_a_delete_waits_for_the_parse_to_confirm_before_removing_anything(
        client, monkeypatch):
    """``request_stop`` only *asks*; the parser answers at its next page.

    The flag alone was the whole fix in the first round, and it is not enough:
    between the request and the next page boundary -- a render plus an OCR round
    trip -- the thread still writes previews into ``pages/``, so ``rmtree`` can
    list the directory, then find a new file in it, and fail with ENOTEMPTY
    (returned as a 500). The store's "no directory, no write" rule closes the
    "written back after the delete" half, but not this one: the directory exists
    while the delete is walking it.

    So the delete has to wait for the parser's confirmation, not for its flag.
    The assertion is on the ordering itself -- at the moment the directory is
    removed, no parse thread for that document is running.
    """
    load(client, "embed-model", "ocr-model")
    kb = new_kb(client)

    import app.apps.kb.parse as kb_parse

    real_parse = kb_parse.parse_pdf
    parse_exited = threading.Event()

    def slow_parse(data, *, ocr=None, write_preview=None, on_page=None,
                   should_stop=None):
        def tracking(done, total, scanned):
            if on_page is not None:
                on_page(done, total, scanned)
            time.sleep(0.05)

        try:
            return real_parse(data, ocr=ocr, write_preview=write_preview,
                              on_page=tracking, should_stop=should_stop)
        finally:
            parse_exited.set()

    monkeypatch.setattr(kb_parse, "parse_pdf", slow_parse)
    store = client.app.state.kb_store
    still_parsing: list[bool] = []
    real_delete_doc = store.delete_doc

    def tracking_delete(kb_id, doc_id):
        # The one observation that separates "asked to stop" from "stopped".
        still_parsing.append(bool(client.app.state.kb_ingestor._parsing))
        return real_delete_doc(kb_id, doc_id)

    monkeypatch.setattr(store, "delete_doc", tracking_delete)

    doc = upload(client, kb, "删除中.pdf", (DATA / "text.pdf").read_bytes())[0]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        docs = client.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
        if docs and docs[0]["status"] in ("parsing", "ocr"):
            break
        time.sleep(0.01)

    r = client.delete(f"/api/apps/kb/{kb}/docs/{doc['id']}")
    assert r.status_code == 200, r.text
    assert still_parsing == [False], \
        "the document directory was removed while its parser was still running"
    assert not (store.docs_dir(kb) / doc["id"]).exists()
    assert client.get(f"/api/apps/kb/{kb}/docs").json()["docs"] == []


@pytest.mark.asyncio
async def test_a_delete_during_the_embed_stage_stops_at_the_next_batch(tmp_path):
    """Embedding 20 000 chunks is minutes of NPU time; a delete must not wait it out.

    The page-boundary check covered the parse only. A document deleted while it
    was being embedded ran every remaining batch first -- minutes of inference
    for a file whose rows the delete (which had already returned) had removed.
    """
    from app.apps.kb import ingest as ingest_mod
    from app.apps.kb.chunker import Chunk
    from app.apps.kb.retrieval import EMBED_BATCH

    store = KbStore(tmp_path / "kb")
    kb = store.create_kb("嵌入库")
    doc_id = "f" * 32
    (store.docs_dir(kb.id) / doc_id / "pages").mkdir(parents=True)
    store.write_doc_meta(kb.id, doc_id, {
        "id": doc_id, "name": "长.txt", "type": "txt", "bytes": 4,
        "status": "embedding", "created_at": time.time()})

    batches: list[int] = []

    async def counting_embed(request, resolved, texts):
        batches.append(len(texts))
        return [[0.0, 1.0] for _ in texts]

    class _FakeEmbed:
        model_id = "embed-model"

    ingestor = ingest_mod.Ingestor(store)
    job = ingest_mod.Job(kb_id=kb.id, doc_id=doc_id, store=store, request=None)
    chunks = [Chunk(page=1, source="text", text=f"盘点要求 {i}", char_start=0,
                    char_end=1) for i in range(EMBED_BATCH * 3)]

    real_embed = ingest_mod.embed_passages
    ingest_mod.embed_passages = counting_embed
    try:
        # Nothing deleted yet: the first batch runs (that is the control).
        job_ok = ingest_mod.Job(kb_id=kb.id, doc_id=doc_id, store=store,
                                request=None)
        vectors = await ingestor._embed_chunks(job_ok, chunks[:EMBED_BATCH],
                                              _FakeEmbed(), total=EMBED_BATCH)
        assert len(vectors) == EMBED_BATCH and len(batches) == 1

        # Deleted: the very next batch boundary must give up.
        ingestor.request_stop(kb.id, doc_id)
        with pytest.raises(Exception) as caught:
            await ingestor._embed_chunks(job, chunks, _FakeEmbed(), total=len(chunks))
        assert type(caught.value).__name__ == "Stopped", caught.value
        assert len(batches) == 1, \
            f"it kept embedding after the delete: {batches}"
    finally:
        ingest_mod.embed_passages = real_embed


def test_repeated_deletes_during_parsing_all_succeed_and_leave_nothing(
        client, monkeypatch):
    """Three deletes in a row, each landing mid-parse: 200 each time, no residue."""
    load(client, "embed-model", "ocr-model")
    kb = new_kb(client)

    import app.apps.kb.parse as kb_parse

    real_parse = kb_parse.parse_pdf

    def slow_parse(data, *, ocr=None, write_preview=None, on_page=None,
                   should_stop=None):
        def tracking(done, total, scanned):
            if on_page is not None:
                on_page(done, total, scanned)
            time.sleep(0.05)

        return real_parse(data, ocr=ocr, write_preview=write_preview,
                          on_page=tracking, should_stop=should_stop)

    monkeypatch.setattr(kb_parse, "parse_pdf", slow_parse)
    store = client.app.state.kb_store
    pdf = (DATA / "text.pdf").read_bytes()

    for attempt in range(3):
        doc = upload(client, kb, f"删除中{attempt}.pdf", pdf)[0]
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            docs = client.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
            here = [d for d in docs if d["id"] == doc["id"]]
            if here and here[0]["status"] in ("parsing", "ocr"):
                break
            time.sleep(0.01)
        r = client.delete(f"/api/apps/kb/{kb}/docs/{doc['id']}")
        assert r.status_code == 200, r.text
        assert not (store.docs_dir(kb) / doc["id"]).exists(), \
            "the delete left the document directory behind"

    assert client.get(f"/api/apps/kb/{kb}/docs").json()["docs"] == []


def test_a_write_to_a_deleted_document_does_not_recreate_its_directory(client):
    """The store-level rule that makes the delete deterministic on its own.

    Even if a parse outlives its delete (a wedged NPU, a thread that has not
    reached the flag yet), the write must be a no-op: creating the parent
    directory on demand is what resurrected the document and broke ``rmtree``.
    """
    kb = new_kb(client)
    store = client.app.state.kb_store
    doc_id = "e" * 32
    (store.docs_dir(kb) / doc_id / "pages").mkdir(parents=True)
    meta = {"id": doc_id, "name": "x.txt", "type": "txt", "bytes": 1,
            "status": "parsing", "created_at": time.time()}
    assert store.write_doc_meta(kb, doc_id, meta) is True

    store.delete_doc(kb, doc_id)
    assert store.write_doc_meta(kb, doc_id, {**meta, "status": "ready"}) is False
    assert store.write_preview(kb, doc_id, 1, b"\x89PNG\r\n\x1a\n") is False
    assert not (store.docs_dir(kb) / doc_id).exists()


# -- 4: the flagged-state ordering ------------------------------------------
def test_mark_needs_reindex_flags_before_it_drops_the_matrix(client):
    """A crash between the two steps must never leave chunks with no flag.

    The old order dropped ``vectors.npy`` and then wrote the flag, so a failure
    in between -- the exact window a crash lands in -- left the library with
    chunks, no matrix and no flag. Nothing detects that state: a missing file
    reads as "never built", and the next upload appends its own rows to nothing.
    """
    load(client, "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)
    store = client.app.state.kb_store

    real_flag = store.set_index_flag
    calls: list[str] = []

    def exploding_flag(kb_id, **kwargs):
        calls.append("flag")
        if kwargs.get("needs_reindex"):
            raise RuntimeError("die between the two writes")
        return real_flag(kb_id, **kwargs)

    real_delete = store.delete_vectors

    def tracking_delete(kb_id):
        calls.append("delete")
        return real_delete(kb_id)

    store.set_index_flag = exploding_flag
    store.delete_vectors = tracking_delete
    try:
        with pytest.raises(RuntimeError):
            store.mark_needs_reindex(kb)
    finally:
        store.set_index_flag = real_flag
        store.delete_vectors = real_delete

    assert calls == ["flag"], (
        "the matrix was dropped before the flag was written: " + repr(calls))
    # And the intermediate state is one the rest of the app can read: still a
    # misaligned matrix, so the next load re-detects and re-flags it.
    assert store.load_vectors(kb) is not None


def test_chunks_without_a_matrix_are_treated_as_needing_a_rebuild(client):
    """A library with chunks and no ``vectors.npy`` is a desync, not a new library.

    That is the state the old ordering could leave behind (or a hand-deleted
    file). ``aligned_vectors`` used to answer "never built" and hand back
    ``None``, so ``_replace_rows`` wrote a matrix holding only the *next*
    document's rows beside a chunk file holding everyone's.
    """
    load(client, "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)
    store = client.app.state.kb_store
    store.delete_vectors(kb)

    assert store.aligned_vectors(kb, store.load_chunks(kb)) is None
    assert store.load_kb(kb).needs_reindex is True

    # An empty library is the ordinary "not built yet" case and is not flagged.
    blank = new_kb(client, "空库")
    assert store.aligned_vectors(blank, store.load_chunks(blank)) is None
    assert store.load_kb(blank).needs_reindex is False


# -- 6: the leftovers -------------------------------------------------------
def test_deleting_the_last_document_clears_the_rebuild_flag(client):
    """Chunks, model *and* flag go together, or the library stays stuck.

    A surviving ``needs_reindex`` keeps the vector stage refusing and the console
    offering to rebuild a library that has nothing to rebuild -- which answers
    409 because there are no chunks. Clearing it with the model is what returns
    the library to the state a new one is in.
    """
    load(client, "embed-model")
    kb = new_kb(client)
    upload(client, kb, "唯一.txt", "盘点制度。".encode())
    doc = wait_ready(client, kb)[0]
    store = client.app.state.kb_store
    store.set_index_flag(kb, needs_reindex=True)

    assert client.delete(f"/api/apps/kb/{kb}/docs/{doc['id']}").status_code == 200
    listing = client.get("/api/apps/kb").json()["kbs"][0]
    assert listing["needs_reindex"] is False
    assert listing["embedding_model"] is None
    assert listing["chunks"] == 0 and listing["docs"] == 0
    # The library is usable again: a new document indexes normally.
    upload(client, kb, "新.txt", "新的盘点制度。".encode())
    assert wait_ready(client, kb)[0]["status"] == "ready"


def test_upload_into_a_flagged_library_is_refused_before_it_embeds(client):
    """Embedding a document whose vectors are then discarded is wasted NPU time.

    While ``needs_reindex`` is set, ``_replace_rows`` writes the chunk rows and
    deliberately writes no matrix -- so the document would spend minutes being
    embedded, be labelled ``ready``, and have no vector. Refusing up front costs
    one request and says what to press instead.
    """
    load(client, "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)
    store = client.app.state.kb_store
    # A matrix one row short is the crash state; reading it flags the library.
    store.save_vectors(kb, store.load_vectors(kb)[:-1])
    search(client, kb)
    assert store.load_kb(kb).needs_reindex is True

    r = client.post(f"/api/apps/kb/{kb}/docs",
                    files={"file": ("新.txt", "补充要求。".encode(), "text/plain")})
    assert r.status_code == 409
    assert "重建索引" in r.json()["detail"]
    assert client.get(f"/api/apps/kb/{kb}/docs").json()["docs"], \
        "the refusal must not have removed the library's documents"


def test_a_library_from_an_older_build_reports_its_real_counts(client):
    """``kb.json`` without the cached counters showed 0/0 for a full library.

    The fields were added with the cache, so their absence is conclusive
    evidence of an older build -- and a genuine zero is written *as* zero, which
    is why the test is on the key rather than on the number.
    """
    load(client, "embed-model")
    kb = new_kb(client)
    seed_library(client, kb)

    path = client.app.state.kb_store.root / kb / "kb.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["doc_count"]
    del data["chunk_count"]
    path.write_text(json.dumps(data), encoding="utf-8")

    listing = next(item for item in client.get("/api/apps/kb").json()["kbs"]
                   if item["id"] == kb)
    assert listing["docs"] == 2
    assert listing["chunks"] > 0
    # Recomputed once and written back, so the next refresh is a directory read.
    assert "chunk_count" in json.loads(path.read_text(encoding="utf-8"))


# -- K3 round two: the shutdown stop flag must outlive ``stop()`` --------------
@pytest.mark.asyncio
async def test_a_parse_still_stops_after_the_wait_expires(
        tmp_path, models_dir, monkeypatch):
    """A page that takes longer than ``STOP_GRACE_S`` must not un-ask the parse.

    ``task.cancel()`` makes the worker's ``finally`` run at once, and that
    ``finally`` used to be the one clearing the stop flag -- so by the time
    ``stop()``'s 30 s wait ended and reset ``_stopping``, ``should_stop()`` was
    ``False`` again and a page that had not returned yet ran the rest of the
    document into the old root. The move copies that root: the extra pages land
    in the copy after it was made, and verification fails.

    The flag is per-thread now and only the thread's own ``finally`` clears it.
    """
    kb_app = create_app(
        data_dir=tmp_path / "data", models_dir=models_dir,
        backend_kind="mock", web_dir=tmp_path / "web",
        context_length_override=4096)
    ingestor = kb_app.state.kb_ingestor
    store = kb_app.state.kb_store
    kb = store.create_kb("超时库")
    doc_id = "1" * 32
    (store.docs_dir(kb.id) / doc_id / "pages").mkdir(parents=True)
    store.write_doc_meta(kb.id, doc_id, {
        "id": doc_id, "name": "超时.pdf", "type": "pdf", "bytes": 10,
        "status": "parsing", "created_at": time.time()})
    (store.docs_dir(kb.id) / doc_id / "source.pdf").write_bytes(
        (DATA / "text.pdf").read_bytes())

    job = kb_ingest.Job(kb_id=kb.id, doc_id=doc_id, store=store, request=None)
    reached: list[int] = []

    def slow_parse(*args, **kwargs):
        # Page 2 is the one that outlasts the grace period; page 3 is where the
        # flag has to still be readable.
        for page in range(1, 20):
            reached.append(page)
            if page == 2:
                time.sleep(0.4)
            if kwargs.get("should_stop") and kwargs["should_stop"]():
                from app.apps.kb import parse as kb_parse

                raise kb_parse.Stopped("文档已停止处理")
            time.sleep(0.02)
        from app.apps.kb.parse import ParsedDoc

        return ParsedDoc(kind="pdf")

    import app.apps.kb.ingest as ingest_mod

    real_parse = ingest_mod.doc_parse.parse_pdf
    ingest_mod.doc_parse.parse_pdf = slow_parse
    # The grace period is the thing under test, so it is the one thing shortened:
    # ``stop`` gives up waiting at 0.1 s, well before page 2 returns.
    monkeypatch.setattr(ingest_mod, "STOP_GRACE_S", 0.1)
    try:
        ingestor.start()
        ingestor.submit(job)
        deadline = time.monotonic() + 5
        while not ingestor._parsing and time.monotonic() < deadline:
            await __import__("asyncio").sleep(0.01)
        await ingestor.stop()
        # ``stop`` has returned while the thread is still inside page 2.
        assert ingestor._parsing, "the test did not get past the grace period"

        deadline = time.monotonic() + 5
        while ingestor._parsing and time.monotonic() < deadline:
            await __import__("asyncio").sleep(0.02)
        assert not ingestor._parsing, "the thread never gave up"
        assert max(reached) < 20, \
            f"the parse ran on after the wait expired: reached page {max(reached)}"
        assert max(reached) <= 3, \
            f"it kept going past the first page boundary after the flag: {reached}"
    finally:
        ingest_mod.doc_parse.parse_pdf = real_parse


@pytest.mark.asyncio
async def test_stop_drops_queued_jobs_instead_of_letting_them_run_old(tmp_path):
    """A queued job carries the old store; after a move it must not run at all.

    ``stop`` only ever cancelled the in-flight job. Everything behind it stayed
    queued, and once the worker restarted it ran against the old root: minutes
    of NPU time on a tree the move was about to delete, and a document whose
    ``save_chunks`` re-created a directory the move had already removed.
    """
    store = KbStore(tmp_path / "kb")
    kb = store.create_kb("排队库")
    ingestor = kb_ingest.Ingestor(store)

    jobs = [kb_ingest.Job(kb_id=kb.id, doc_id=str(i) * 32, store=store)
            for i in range(1, 4)]
    for job in jobs:
        ingestor._queue.put_nowait(job)
    assert ingestor.busy

    await ingestor.stop()
    assert ingestor._queue.empty(), "queued jobs survived the shutdown"
    assert not ingestor.busy


class _HaltingFlag:
    """Stands in for ``_halted`` and lands a page boundary on every add.

    Each ``add`` costs one key of ``_parsing``, which is exactly what the parse
    thread's ``finally`` does when it reaches its next page -- only here it is
    deterministic rather than a race. Against a live ``for`` over the set that
    is a "Set changed size during iteration" on the second key; against
    ``list(...)`` it is a snapshot and nothing changes under the loop.
    """

    def __init__(self, parsing: set) -> None:
        self.parsing = parsing
        self.added: list = []

    def add(self, key) -> None:
        self.added.append(key)
        self.parsing.discard(key)

    def discard(self, key) -> None:
        pass

    def __contains__(self, key) -> bool:
        return key in self.added


@pytest.mark.asyncio
async def test_stop_survives_a_thread_leaving_the_parsing_set_mid_iteration(
        tmp_path, monkeypatch):
    """Iterating ``_parsing`` live is a "Set changed size during iteration".

    The worker thread discards its key from that same set in its own
    ``finally``. A page boundary landing inside ``stop``'s loop is a shutdown
    that raises instead of stopping -- and the move then proceeds with a parse
    thread it never asked to stop. ``list(...)`` is a single C-level snapshot.
    """
    store = KbStore(tmp_path / "kb")
    kb = store.create_kb("并发库")
    ingestor = kb_ingest.Ingestor(store)

    keys = {(kb.id, f"{i:032d}") for i in range(50)}
    ingestor._parsing.update(keys)
    flag = _HaltingFlag(ingestor._parsing)
    monkeypatch.setattr(ingestor, "_halted", flag)

    await ingestor.stop()  # must not raise RuntimeError
    assert len(flag.added) == len(keys), \
        f"stop did not ask every running parse to give up: {len(flag.added)}"


# -- K3 round two: two deletes of one document -------------------------------
@pytest.mark.asyncio
async def test_two_deletes_of_one_document_are_both_successes(tmp_path):
    """The second delete lands during the first one's wait and must not 500.

    Both requests pass the "does it exist" check, both ask the parser to stop,
    and then both reach ``rmtree``: the loser found the directory already gone
    and answered 500 -- for work that had in fact been done twice.
    """
    from app.apps.kb.store import KbStore as _Store

    store = _Store(tmp_path / "kb")
    kb = store.create_kb("并发删除库")
    doc_id = "2" * 32
    (store.docs_dir(kb.id) / doc_id / "pages").mkdir(parents=True)
    store.write_doc_meta(kb.id, doc_id, {
        "id": doc_id, "name": "x.txt", "type": "txt", "bytes": 1,
        "status": "ready", "created_at": time.time()})

    store.delete_doc(kb.id, doc_id)
    # The loser of the race: the same call, one instant later.
    store.delete_doc(kb.id, doc_id)
    assert not (store.docs_dir(kb.id) / doc_id).exists()


def _long_pdf(pages: int = 10) -> bytes:
    """``text.pdf`` repeated, so the parse takes long enough to overlap two deletes."""
    import io

    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument.new()
    source = pdfium.PdfDocument(str(DATA / "text.pdf"))
    for _ in range(pages):
        doc.import_pages(source, pages=[0])
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def test_a_second_delete_inside_the_first_ones_wait_answers_200(
        app, models_dir, tmp_path):
    """Two deletes of the same document, the second landing during the wait.

    The first asks the parser to stop and waits up to ``STOP_GRACE_S``; the
    second arrives in that window, passes the same "does it exist" check, and
    used to reach ``rmtree`` after the first had removed the directory -- a
    ``FileNotFoundError`` 500 for a document that was, by then, deleted.
    Deleting twice is a success both times.

    Driven over real HTTP rather than ``TestClient``: the whole point is that
    the two requests are in ``await_stop`` at once, and ``TestClient`` serialises
    them -- against it the second delete always arrives after the first one has
    returned, which is the case that already worked.
    """
    import asyncio
    import socket

    import httpx
    import uvicorn

    import app.apps.kb.parse as kb_parse

    real_parse = kb_parse.parse_pdf

    def slow_parse(data, *, ocr=None, write_preview=None, on_page=None,
                   should_stop=None):
        def tracking(done, total, scanned):
            if on_page is not None:
                on_page(done, total, scanned)
            time.sleep(0.05)

        return real_parse(data, ocr=ocr, write_preview=write_preview,
                          on_page=tracking, should_stop=should_stop)

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "the test server never came up"

    base = f"http://127.0.0.1:{port}"
    kb_parse.parse_pdf = slow_parse
    # Two ``rmtree`` calls walking one directory is its own failure (the second
    # lists files the first is deleting, and can come back ENOTEMPTY). The
    # idempotent store makes the *answer* right; serialising the call makes the
    # operation right, and this is what sees the difference.
    store = app.state.kb_store
    real_delete_doc = store.delete_doc
    removals: list[tuple[str, str]] = []

    def counting_delete(kb_id, doc_id):
        removals.append((kb_id, doc_id))
        return real_delete_doc(kb_id, doc_id)

    store.delete_doc = counting_delete
    try:
        async def scenario() -> tuple[int, int, list[dict]]:
            async with httpx.AsyncClient(base_url=base, timeout=60) as c:
                r = await c.post("/api/login", json={"password": "admin"})
                assert r.status_code == 200
                for model_id in ("embed-model", "ocr-model"):
                    r = await c.post(f"/api/models/{model_id}/load")
                    assert r.status_code == 200, r.text
                r = await c.post("/api/apps/kb", json={"name": "并发删除库"})
                kb = r.json()["kb"]["id"]
                r = await c.post(
                    f"/api/apps/kb/{kb}/docs",
                    files={"file": ("并发删除.pdf", _long_pdf(),
                                    "application/octet-stream")})
                assert r.status_code == 200, r.text
                doc = r.json()["docs"][0]

                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    docs = (await c.get(f"/api/apps/kb/{kb}/docs")).json()["docs"]
                    here = [d for d in docs if d["id"] == doc["id"]]
                    if here and here[0]["status"] in ("parsing", "ocr"):
                        break
                    await asyncio.sleep(0.01)

                # Both in flight at once: the first is inside ``await_stop``
                # when the second is issued.
                async def one_delete():
                    return await c.delete(f"/api/apps/kb/{kb}/docs/{doc['id']}")

                first = asyncio.create_task(one_delete())
                await asyncio.sleep(0.05)
                second = asyncio.create_task(one_delete())
                return ((await first).status_code, (await second).status_code,
                        (await c.get(f"/api/apps/kb/{kb}/docs")).json()["docs"])

        statuses = asyncio.run(scenario())
    finally:
        store.delete_doc = real_delete_doc
        kb_parse.parse_pdf = real_parse
        server.should_exit = True
        thread.join(timeout=10)

    assert statuses[0] == 200, statuses
    assert statuses[1] == 200, statuses
    assert statuses[2] == [], statuses[2]
    assert len(removals) == 1, \
        f"the directory was removed {len(removals)} times by two deletes: {removals}"
