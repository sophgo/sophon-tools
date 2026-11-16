"""``/api/apps/kb`` -- the knowledge-base demo's HTTP surface.

Auth is the console's admin session, exactly like ``/api/test/*``: the operator
has a cookie, not an API key, and minting one just to press a button in the demo
is the friction those routes exist to avoid.

The routes here are thin. Everything they do is resolve a path parameter, call
one function in :mod:`app.apps.kb`, and translate its exceptions into status
codes -- so the behaviour under test is the modules', not a second copy of it
living in an HTTP handler.

Field names are a contract with the console (the front end is written against
them), which is why the response builders spell every key out rather than
serialising a dataclass: a rename in Python must not silently rename a field the
UI reads.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..core.auth import require_admin
from . import audio_upload
from ..apps.kb import answer as kb_answer
from ..apps.kb import ingest as kb_ingest
from ..apps.kb import models as kb_models
from ..apps.kb import parse as kb_parse
from ..apps.kb import retrieval as kb_retrieval
from ..apps.kb.bm25 import Bm25Index
from ..apps.kb.store import (
    Kb, KbError, KbNotFound, KbStore, new_id, write_bytes_atomic,
)

logger = logging.getLogger(__name__)

router = APIRouter()

#: Path prefix the app is mounted under (see app/main.py). Kept in one place so
#: ``request.url.path`` -- which becomes the inference record's ``source`` --
#: and the routes cannot drift.
PREFIX = "/api/apps/kb"


def _store(request: Request) -> KbStore:
    store = getattr(request.app.state, "kb_store", None)
    if store is None:  # pragma: no cover - create_app always sets it
        raise HTTPException(status_code=503, detail="知识库应用未初始化")
    return store


def _ingestor(request: Request) -> kb_ingest.Ingestor:
    return request.app.state.kb_ingestor


def _bm25_cache(request: Request) -> dict:
    return request.app.state.kb_bm25


def _bm25_for(request: Request, kb_id: str, chunks: list[dict]) -> Bm25Index:
    """The library's BM25 index, rebuilt only when its chunk set changed.

    Keyed on the chunk count *and* the id of the last chunk: an upload appends,
    a delete removes, and a retry replaces one document's rows -- all of which
    change at least one of the two. Rebuilding on every search would be correct
    too, but it is O(library) per keystroke in the demo's UI.
    """
    cache = _bm25_cache(request)
    signature = (len(chunks), chunks[-1]["id"] if chunks else "")
    hit = cache.get(kb_id)
    if hit is not None and hit[0] == signature:
        return hit[1]
    index = Bm25Index.build(chunks)
    cache[kb_id] = (signature, index)
    return index


def _drop_bm25(request: Request, kb_id: str) -> None:
    _bm25_cache(request).pop(kb_id, None)


# -- request bodies ---------------------------------------------------------
class CreateKbBody(BaseModel):
    name: str = Field(default="", max_length=200)


class SearchBody(BaseModel):
    query: str
    top_k: int = 5
    candidates: int = 20
    use_bm25: bool = True
    use_vector: bool = True
    use_rerank: bool = True


class AnswerBody(BaseModel):
    query: str
    chunk_ids: list[str]
    model: str | None = None
    max_tokens: int = kb_answer.DEFAULT_MAX_TOKENS


# -- knowledge bases --------------------------------------------------------
@router.get("")
async def list_kbs(request: Request, _=Depends(require_admin)):
    """Every library, with its cached counts.

    The counts come from ``kb.json`` (kept in step by ``store.save_chunks``)
    rather than from parsing each library's ``chunks.jsonl``: at the 20 000-chunk
    cap that is a JSON parse of ~8 MB per library on every console refresh.

    A library written before those counters existed has neither field, and would
    report ``0/0`` for a library that is full of chunks -- which reads as "empty
    and fine" rather than "this build does not know". So a missing count is
    recomputed from the files once and written back; after that the cache is the
    cache again.
    """
    store = _store(request)
    return {"kbs": [_with_counts(store, kb).public() for kb in store.list_kbs()]}


def _with_counts(store: KbStore, kb: Kb) -> Kb:
    """Backfill ``doc_count``/``chunk_count`` for a library that predates them.

    ``0`` is a legitimate value (a freshly created library), so the test is the
    file's presence, not the number: ``save_chunks`` writes both fields on every
    write, which makes ``kb.json`` without them conclusive evidence of an older
    build.
    """
    path = store.kb_dir(kb.id) / "kb.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError):
        return kb
    if "doc_count" in data and "chunk_count" in data:
        return kb
    try:
        kb.chunk_count = len(store.load_chunks(kb.id))
        kb.doc_count = len(store.list_docs(kb.id))
        store.save_kb(kb)
    except KbError:  # pragma: no cover - one bad library must not fail the list
        logger.warning("could not recompute counts for %s", kb.id, exc_info=True)
    return kb


@router.post("")
async def create_kb(body: CreateKbBody, request: Request, _=Depends(require_admin)):
    store = _store(request)
    try:
        kb = store.create_kb(body.name)
    except KbError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"kb": kb.public()}


@router.delete("/{kb_id}")
async def delete_kb(kb_id: str, request: Request, _=Depends(require_admin)):
    store = _store(request)
    ingestor = _ingestor(request)
    try:
        store.delete_kb(kb_id)
    except KbNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"删除失败：{exc}") from None
    _drop_bm25(request, kb_id)
    # A queued job for a library that no longer exists must not resurrect a
    # directory or fail loudly; the worker's own not-found handling covers the
    # in-flight one, and this covers the queued ones.
    ingestor.forget(kb_id)
    return {"ok": True}


@router.post("/{kb_id}/reindex")
async def reindex(kb_id: str, request: Request, _=Depends(require_admin)):
    """Rebuild every vector in the library with the currently loaded model.

    The case this exists for: the library was built while one embedding model was
    loaded, and the operator has since switched models. The stored vectors are in
    the old model's space and cannot be compared with the new model's query
    vector, so the search stage refuses them (``skipped``). This re-embeds them.

    Refused synchronously when there is no model or nothing to redo -- an
    operator pressing the button should learn why immediately, not by watching a
    queue entry fail.
    """
    store = _store(request)
    ingestor = _ingestor(request)
    try:
        kb = store.load_kb(kb_id)
        chunks = store.load_chunks(kb_id)
    except KbNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except KbError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    # On demand, like the stages: pressing "Reindex" is an explicit ask to spend
    # NPU time on this library, so bringing its embedding model up is in scope.
    # Still a 409 when nothing can be brought up -- the button's whole contract is
    # "refuse immediately with a reason, do not queue a job that will fail".
    #
    # The family, not the id, is the preference: a rebuild into the same vector
    # space with a sibling build (seq512 for seq2048) is a legitimate migration,
    # while a rebuild across families is the operator's explicit choice anyway
    # -- which is exactly what this endpoint is for.
    family = kb_models.vector_family_of(request, kb.embedding_model)
    model = await kb_models.resolve_or_load(
        request, "embedding", preferred=kb.embedding_model, family=family or None)
    if not model:
        raise HTTPException(status_code=409,
                            detail=f"{model.reason}；无法重建向量索引")
    # "Chunks exist" is the only precondition. Requiring a `ready` document as
    # well locked the operator out of the one state that needs this most: a
    # rebuild that failed, or a restart in the middle of one, leaves every
    # document `failed` -- and Retry cannot fix them either, because the library
    # is still recorded against the old embedding model. Deleting the library was
    # the only exit.
    if not chunks:
        raise HTTPException(status_code=409, detail="知识库还没有可重建的切片")
    if ingestor.is_reindexing(kb_id):
        raise HTTPException(status_code=409, detail="该知识库正在重建索引，请等待当前任务完成")

    # Claimed before the job is queued: between submit and the worker picking it
    # up, an upload or a delete would otherwise change the chunk set the job is
    # about to rebuild, and the matrix it writes would not describe the file.
    ingestor.begin_reindex(kb_id)
    try:
        ingestor.submit(kb_ingest.Job(kb_id=kb_id, request=request))
    except Exception:  # pragma: no cover - submit only fails if the loop is gone
        ingestor.end_reindex(kb_id)
        raise
    return {"ok": True, "job": {
        # Documents with chunks: the ones this job will claim and end `ready`.
        "documents": len({c.get("doc_id") for c in chunks if c.get("doc_id")}),
        "chunks": len(chunks), "model": model.model_id}}


# -- documents --------------------------------------------------------------
def _doc_view(meta: dict) -> dict:
    """A document record in the shape the console reads.

    Every key is present even when its value is null: the front end renders a
    fixed set of columns, and a missing key there is an ``undefined`` in the
    middle of the table.
    """
    return {
        "id": meta.get("id"),
        "name": meta.get("name"),
        "type": meta.get("type") or "txt",
        "bytes": int(meta.get("bytes") or 0),
        "pages": int(meta.get("pages") or 0),
        "status": meta.get("status") or kb_ingest.QUEUED,
        "progress": meta.get("progress"),
        "error": meta.get("error"),
        "warnings": list(meta.get("warnings") or []),
        "chunks": int(meta.get("chunks") or 0),
        "text_pages": int(meta.get("text_pages") or 0),
        "ocr_pages": int(meta.get("ocr_pages") or 0),
        "created_at": meta.get("created_at"),
    }


@router.get("/{kb_id}/docs")
async def list_docs(kb_id: str, request: Request, _=Depends(require_admin)):
    store = _store(request)
    try:
        docs = store.list_docs(kb_id)
    except KbNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return {"docs": [_doc_view(meta) for meta in docs]}


@router.post("/{kb_id}/docs")
async def upload_docs(kb_id: str, request: Request, _=Depends(require_admin)):
    """Accept one or more files and queue them.

    Multipart, read by ``app/api/audio_upload.py`` -- the release does not vendor
    ``python-multipart``, and that reader enforces its cap while streaming rather
    than after buffering the body.
    """
    store = _store(request)
    ingestor = _ingestor(request)
    try:
        kb = store.load_kb(kb_id)
    except KbNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    _refuse_during_reindex(ingestor, kb_id)
    _refuse_when_rebuild_needed(kb)

    try:
        body = await audio_upload.read_body(request, limit=kb_parse.MAX_FILE_BYTES)
        parts = audio_upload.parse(body, request.headers.get("content-type"))
    except audio_upload.UploadTooLarge as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except audio_upload.MultipartError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    files = [part for part in parts if part.is_file]
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一个文件（字段名 file）")

    # Validate every part before creating anything. A body with one bad file is
    # refused as a whole: queueing the first two and then 400-ing on the third
    # would leave the console showing a rejection while two documents index, and
    # the operator has no way to tell which.
    accepted: list[tuple[str, bytes, str]] = []
    for part in files:
        if not part.data:
            raise HTTPException(
                status_code=400, detail=f"文件 {part.filename or part.name} 是空的")
        # The reader's cap covers the whole *request* plus its envelope slack, so
        # several files in one body could still each be under it while the
        # largest exceeds the per-file limit. Check each one.
        if len(part.data) > kb_parse.MAX_FILE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"文件 {part.filename} 有 {_mib(len(part.data))}，"
                       f"超过单个文件上限 {_mib(kb_parse.MAX_FILE_BYTES)}")
        kind = _kind_or_400(part.filename, part.data)
        _validate_or_400(kind, part.filename, part.data)
        accepted.append((part.filename or "", part.data, kind))

    created: list[dict] = []
    for filename, data, kind in accepted:
        doc_id = new_id()
        directory = store.docs_dir(kb_id) / doc_id
        (directory / "pages").mkdir(parents=True)
        # The original is written *now*, before this request returns, and the
        # job only carries the id. Two consequences, both required: a document
        # left `queued` by a restart can still be retried (its file is on disk,
        # not in a queue that died with the process), and the 50 MiB body is not
        # held in memory for however long the serial queue takes to reach it.
        write_bytes_atomic(directory / f"source{_suffix_for(filename, kind)}", data)
        meta = {
            "id": doc_id,
            "name": filename or f"doc.{kind}",
            "type": kind,
            "bytes": len(data),
            "pages": 0,
            "status": kb_ingest.QUEUED,
            "progress": {"stage": kb_ingest.QUEUED, "done": 0, "total": 1},
            "error": None,
            "warnings": [],
            "chunks": 0,
            "text_pages": 0,
            "ocr_pages": 0,
            "created_at": time.time(),
        }
        store.write_doc_meta(kb_id, doc_id, meta)
        ingestor.submit(kb_ingest.Job(kb_id=kb_id, doc_id=doc_id, request=request))
        created.append(_doc_view(meta))
    _bump_doc_count(store, kb_id)
    _drop_bm25(request, kb_id)
    return {"docs": created}


def _refuse_when_rebuild_needed(kb: Kb) -> None:
    """409 an upload into a library whose vectors are known to be unusable.

    While ``needs_reindex`` is set, ``_replace_rows`` writes the chunk rows and
    deliberately drops the vectors, so the document would be embedded for
    minutes and its vectors thrown away -- and then be labelled ``ready`` with
    no vector in the matrix. Refusing up front is both cheaper and honest: the
    operator's next move is the Rebuild button either way, and their file is
    still on disk when they come back to it.

    The failure that *created* the state is not the operator's fault, so the
    message says what to press rather than what went wrong.
    """
    if kb.needs_reindex:
        raise HTTPException(
            status_code=409,
            detail="该知识库的向量索引需要重建（与切片不一致）；请先点「重建索引」，"
                   "完成后再上传新文档")


def _refuse_during_reindex(ingestor: kb_ingest.Ingestor, kb_id: str) -> None:
    """409 for a mutation that would change the chunk set mid-rebuild.

    A reindex reads every chunk, embeds for minutes, then writes one matrix over
    all of them. An upload or a delete accepted during that window makes the
    matrix describe a chunk file that no longer exists -- the desync the
    ``needs_reindex`` flag has to clean up afterwards. Refusing is the cheaper
    answer, and the message says what to do.
    """
    if ingestor.is_reindexing(kb_id):
        raise HTTPException(status_code=409,
                            detail="该知识库正在重建索引，请等待任务完成后再修改文档")


def _validate_or_400(kind: str, filename: str | None, data: bytes) -> None:
    """Refuse at upload time anything the parse would reject anyway.

    The card asks for the cheap checks here rather than in the queue: a PDF's
    page count is known on open, a txt's encoding is one ``decode``, and an
    image's pixel dimensions come from its header. What cannot be checked here
    (the library's 20 000-chunk cap, which needs the text chunked) is enforced
    in ``ingest._process`` *before* embedding, so it never costs NPU time either.
    """
    try:
        kb_parse.validate_upload(kind, data)
    except kb_parse.ParseError as exc:
        label = f"{filename}：" if filename else ""
        raise HTTPException(status_code=400, detail=f"{label}{exc}") from None


def _suffix_for(filename: str | None, kind: str) -> str:
    """The suffix the upload is stored under, from its name or its family."""
    suffix = Path(filename or "").suffix.lower()
    allowed = (".txt", ".md", ".markdown", ".pdf") + kb_parse.IMAGE_SUFFIXES
    if suffix in allowed:
        return suffix
    return {"pdf": ".pdf", "md": ".md", "txt": ".txt", "image": ".png"}[kind]


def _bump_doc_count(store: KbStore, kb_id: str) -> None:
    """Keep ``kb.json``'s cached document count in step with the directory."""
    try:
        kb = store.load_kb(kb_id)
        kb.doc_count = len(store.list_docs(kb_id))
        store.save_kb(kb)
    except KbError:  # pragma: no cover - the library went away mid-request
        pass


def _kind_or_400(filename: str | None, data: bytes) -> str:
    try:
        return kb_parse.detect_kind(filename or "", data)
    except kb_parse.ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


def _mib(size: int) -> str:
    """A size a reader can act on: MiB when it is big, KiB when it is small."""
    if size >= 1 << 20:
        return f"{size / 2**20:.1f} MB"
    return f"{size / 1024:.1f} KB"


@router.delete("/{kb_id}/docs/{doc_id}")
async def delete_doc(kb_id: str, doc_id: str, request: Request, _=Depends(require_admin)):
    store = _store(request)
    ingestor = _ingestor(request)
    try:
        store.read_doc_meta(kb_id, doc_id)
    except KbNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    _refuse_during_reindex(ingestor, kb_id)
    # Drop the queued job, tell an in-flight one to stop at its next page, and
    # **wait for it to confirm**. The flag alone was not enough: the parser
    # checks it once per page, so between the request and the next boundary it
    # was still writing previews and ``meta.json`` into the directory this
    # route is about to remove -- which is how a delete came back as an
    # ``ENOTEMPTY`` 500, and how a document that had just been deleted got a
    # fresh ``meta.json`` written back. Waiting makes the delete deterministic;
    # the store's own "no directory, no write" rule is the second line.
    ingestor.forget(kb_id, doc_id)
    ingestor.request_stop(kb_id, doc_id)
    # One delete per document at a time. Two of them both passed the check
    # above, both waited out the parser's 30 s grace, and then raced for the
    # same directory: one removed it, the other found its ``rmtree`` target
    # gone and answered 500 for work that had already been done.
    async with _delete_lock(kb_id, doc_id):
        try:
            store.read_doc_meta(kb_id, doc_id)
        except KbNotFound:
            # The delete we were queued behind has just finished; the caller's
            # intent is satisfied twice over.
            return {"ok": True}
        await ingestor.await_stop(kb_id, doc_id)
        # The aggregate first: a crash between the two leaves an orphaned file
        # to be cleaned up, where the other order would leave rows pointing at a
        # document whose text is gone.
        async with ingestor.lock:
            _remove_rows(store, kb_id, doc_id)
        try:
            store.delete_doc(kb_id, doc_id)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"删除文件失败：{exc}") from None
    _bump_doc_count(store, kb_id)
    _drop_bm25(request, kb_id)
    return {"ok": True}


#: One lock per document being deleted. Dropped again as soon as nobody holds or
#: waits on it -- a board runs for months, so this must not grow with the number
#: of documents ever deleted.
_delete_locks: dict[tuple[str, str], tuple[asyncio.Lock, int]] = {}


@asynccontextmanager
async def _delete_lock(kb_id: str, doc_id: str):
    key = (kb_id, doc_id)
    lock, waiters = _delete_locks.get(key, (asyncio.Lock(), 0))
    _delete_locks[key] = (lock, waiters + 1)
    try:
        async with lock:
            yield
    finally:
        lock, waiters = _delete_locks.get(key, (lock, 1))
        if waiters <= 1:
            _delete_locks.pop(key, None)
        else:
            _delete_locks[key] = (lock, waiters - 1)


def _remove_rows(store: KbStore, kb_id: str, doc_id: str) -> None:
    """Drop one document's chunks and their vector rows, keeping the alignment.

    The matrix is filtered **only** when its row count matches the chunk count.
    When it does not, the library is already in the state ``needs_reindex``
    describes: the chunk rows still have to go (they are the truth, and the
    document is being deleted), but there is no row-per-chunk relationship left
    to preserve, so touching the matrix would be indexing into an array with
    indices derived from a different list -- which is how a delete used to
    produce a 500.
    """
    chunks = store.load_chunks(kb_id)
    keep_idx = [i for i, c in enumerate(chunks) if c.get("doc_id") != doc_id]
    if len(keep_idx) == len(chunks):
        return
    kb = store.load_kb(kb_id)
    matrix = None if kb.needs_reindex else store.load_vectors(kb_id)
    if matrix is not None:
        if len(matrix) != len(chunks):
            # Misaligned: the flag is the durable statement of that, and the
            # rebuild will produce a matrix from whatever chunks remain.
            store.mark_needs_reindex(kb_id)
            matrix = None
        elif keep_idx:
            store.save_vectors(kb_id, matrix[keep_idx])
        else:
            store.delete_vectors(kb_id)
    if not keep_idx:
        # Nothing left to have been vectorised: the library is back to the
        # state a brand-new one is in, and *everything* that described the old
        # build has to go with it -- not just the model name. A surviving
        # ``needs_reindex`` would keep the vector stage refusing and the console
        # offering a rebuild of a library with no chunks to rebuild.
        kb.embedding_model = None
        kb.dims = 0
        kb.needs_reindex = False
        store.save_kb(kb)
    store.save_chunks(kb_id, [chunks[i] for i in keep_idx],
                      doc_count=max(0, len(store.list_docs(kb_id)) - 1))


@router.post("/{kb_id}/docs/{doc_id}/retry")
async def retry_doc(kb_id: str, doc_id: str, request: Request, _=Depends(require_admin)):
    store = _store(request)
    ingestor = _ingestor(request)
    try:
        meta = store.read_doc_meta(kb_id, doc_id)
    except KbNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    _refuse_during_reindex(ingestor, kb_id)
    if meta.get("status") in kb_ingest.IN_FLIGHT:
        # Already queued or being worked on: re-submitting would put the same
        # document in the queue twice and run the whole parse twice.
        raise HTTPException(
            status_code=409,
            detail=f"文档当前状态是 {meta.get('status')}，正在处理中，请等待完成")
    if meta.get("status") != kb_ingest.FAILED:
        raise HTTPException(
            status_code=409,
            detail=f"文档当前状态是 {meta.get('status')}，只有失败的文档可以重试")
    if not _has_source(store, kb_id, doc_id):
        raise HTTPException(status_code=409, detail="原始文件不存在，无法重试；请重新上传")
    meta["status"] = kb_ingest.QUEUED
    meta["progress"] = {"stage": kb_ingest.QUEUED, "done": 0, "total": 1}
    meta["error"] = None
    store.write_doc_meta(kb_id, doc_id, meta)
    ingestor.submit(kb_ingest.Job(kb_id=kb_id, doc_id=doc_id, request=request))
    _drop_bm25(request, kb_id)
    return {"ok": True, "doc": _doc_view(meta)}


def _has_source(store: KbStore, kb_id: str, doc_id: str) -> bool:
    try:
        path = store.source_file(kb_id, doc_id)
    except KbNotFound:
        return False
    return path.stat().st_size > 0


@router.get("/{kb_id}/docs/{doc_id}/chunks")
async def list_doc_chunks(kb_id: str, doc_id: str, request: Request,
                          _=Depends(require_admin)):
    store = _store(request)
    try:
        store.read_doc_meta(kb_id, doc_id)
    except KbNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    chunks = [c for c in store.load_chunks(kb_id) if c.get("doc_id") == doc_id]
    return {"chunks": [{
        "id": c.get("id"),
        "page": c.get("page"),
        "source": c.get("source"),
        "text": c.get("text"),
        "char_start": c.get("char_start"),
        "char_end": c.get("char_end"),
        "boxes": c.get("boxes") or [],
    } for c in chunks]}


@router.get("/{kb_id}/docs/{doc_id}/pages/{page}.png")
async def doc_page_png(kb_id: str, doc_id: str, page: int, request: Request,
                       _=Depends(require_admin)):
    store = _store(request)
    try:
        path = store.page_png(kb_id, doc_id, page)
    except KbNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return FileResponse(path, media_type="image/png")


@router.get("/{kb_id}/docs/{doc_id}/file")
async def doc_file(kb_id: str, doc_id: str, request: Request,
                   _=Depends(require_admin)):
    store = _store(request)
    try:
        path = store.source_file(kb_id, doc_id)
        meta = store.read_doc_meta(kb_id, doc_id)
    except KbNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return FileResponse(path, filename=meta.get("name") or path.name,
                        media_type="application/octet-stream")


# -- search and answer ------------------------------------------------------
@router.post("/{kb_id}/search")
async def search(kb_id: str, body: SearchBody, request: Request,
                 _=Depends(require_admin)):
    store = _store(request)
    try:
        kb = store.load_kb(kb_id)
        chunks = store.load_chunks(kb_id)
        # `aligned_vectors` is what makes a desync durable: it flags the library
        # (`needs_reindex`) the first time the two files are seen to disagree, so
        # a later upload cannot append to a matrix known to be wrong.
        vectors = None if kb.needs_reindex else store.aligned_vectors(kb_id, chunks)
    except KbNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except KbError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    query = (body.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空")
    if body.top_k < 1:
        raise HTTPException(status_code=400, detail="top_k 必须至少为 1")
    if body.candidates < 1:
        raise HTTPException(status_code=400, detail="candidates 必须至少为 1")
    if body.candidates > kb_retrieval.MAX_CANDIDATES:
        # The rerank endpoint refuses more than 256 pairs, and one search on the
        # board is ~6.5 s of reranking for 20. Past a hundred the demo stops
        # answering inside a page's patience, so the ceiling is stated rather
        # than discovered as a timeout.
        raise HTTPException(
            status_code=400,
            detail=f"candidates 不能超过 {kb_retrieval.MAX_CANDIDATES}"
                   f"（收到 {body.candidates}）")
    if body.top_k > body.candidates:
        # Not a refusal of the request's *intent*, but the pipeline can only
        # return `candidates` items, so a larger top_k would silently return
        # fewer than asked. Raising candidates is the fix, and saying so is
        # better than returning 3 results for top_k=5.
        raise HTTPException(
            status_code=400,
            detail=f"top_k（{body.top_k}）不能大于 candidates（{body.candidates}）")

    index = _bm25_for(request, kb_id, chunks)
    try:
        result = await kb_retrieval.search(
            request, kb=kb, chunks=chunks, bm25=index, vectors=vectors,
            req=kb_retrieval.SearchRequest(
                query=query, top_k=body.top_k, candidates=body.candidates,
                use_bm25=body.use_bm25, use_vector=body.use_vector,
                use_rerank=body.use_rerank))
    except Exception as exc:  # pragma: no cover - every stage already degrades
        logger.exception("kb search failed")
        raise HTTPException(status_code=500, detail=f"检索失败：{exc}") from None
    return result.public()


@router.post("/{kb_id}/answer")
async def answer(kb_id: str, body: AnswerBody, request: Request,
                 _=Depends(require_admin)):
    """Stream a grounded answer over the chunks the search returned."""
    store = _store(request)
    try:
        chunks = store.load_chunks(kb_id)
        store.load_kb(kb_id)
    except KbNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    query = (body.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空")
    if body.max_tokens < 1:
        raise HTTPException(status_code=400, detail="max_tokens 必须至少为 1")

    by_id = {c["id"]: c for c in chunks}
    missing = [cid for cid in body.chunk_ids if cid not in by_id]
    if missing:
        raise HTTPException(status_code=400,
                            detail=f"切片不存在：{', '.join(missing[:5])}")
    if not body.chunk_ids:
        raise HTTPException(status_code=400, detail="chunk_ids 不能为空")

    # ``answer_kind()`` is ``chat``: the answer stage holds a conversation, and
    # an OCR-VL model cannot (it answers the same route, which is why this is
    # stated rather than left to whichever kind a caller typed).
    resolved = kb_models.resolve_named(request, kb_models.answer_kind(), body.model)
    if not resolved:
        raise HTTPException(status_code=409, detail=f"{resolved.reason}；无法生成回答")

    results = [{
        "chunk_id": cid,
        "doc_name": (by_id[cid].get("doc") or {}).get("name"),
        "page": by_id[cid].get("page"),
        "text": by_id[cid].get("text"),
    } for cid in body.chunk_ids]
    passages = kb_answer.build_passages(results)

    return StreamingResponse(
        kb_answer.stream_answer(
            request, client=resolved.client, model_id=resolved.model_id,
            query=query, passages=passages, max_tokens=body.max_tokens),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
