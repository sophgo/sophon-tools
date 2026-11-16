"""The nine MCP tools: knowledge base, OCR and transcription over the app code.

Design rule this file follows: **the tools describe, the app modules do.** A tool
resolves its arguments, calls one function that already exists for the console's
own features, and formats the answer for a language model. Nothing here
re-implements retrieval, parsing or ingestion -- a second copy of the hybrid
pipeline would drift from the one ``/api/apps/kb`` serves and the two surfaces
would slowly stop agreeing about the same library.

Three things are worth knowing before reading the code.

**Inference records are re-attributed, not re-written.** ``app/apps/kb/retrieval``
records every embedding, rerank and OCR call it makes, with ``source``
``/api/apps/kb`` and actor ``kb`` -- correct for a console request, wrong for an
MCP one. Rather than change those modules (MYS-2609 owns them) or duplicate their
calls, every tool hands the pipeline a *shim request* whose ``inference_log`` is a
thin proxy: records still happen one per inference, at the same points, but the
proxy overwrites ``source`` with ``/mcp`` and the actor with the caller's API key
name on the way to the store. The library modules never learn about MCP.

**The library pipeline wants a ``request``, so the shim has to be convincing.**
It is read for ``app.state.models`` (which model is loaded), ``app.state.clients``
(the worker RPC clients) and ``app.state.event_loop`` (the OCR bridge for the
parser's worker thread). All three are the live objects, not copies.

**Local paths go through** :mod:`app.mcp.paths` **before a byte is read.**
``ocr_read``, ``kb_add_document`` and ``transcribe_audio`` accept a path on this
board, which is the only way an agent's words can reach the filesystem; the
allowlist is applied on the resolved path so neither ``..`` nor a symlink can
step outside it, and the read happens on the descriptor that was checked.

**Nothing blocking runs on the event loop.** Reading a 50 MiB file, opening a
PDF to count its pages, decoding an image header, building a 20 000-chunk BM25
index and writing a document atomically are all CPU or disk work that would
stall every other request this service is serving -- including the token stream
of somebody's chat. Each of them is dispatched with ``asyncio.to_thread``, and
the two NPU-heavy tools (``ocr_read``, ``transcribe_audio``) additionally share
a small admission pool so a client cannot queue ten OCR passes behind each
other and exhaust the board.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time
import uuid
from pathlib import Path

from ..apps.kb import models as kb_models
from ..apps.kb import parse as kb_parse
from ..apps.kb import retrieval as kb_retrieval
from ..apps.kb.bm25 import Bm25Index
from ..apps.kb.ingest import Job, QUEUED
from ..apps.kb.store import KbError, KbNotFound, new_id, write_bytes_atomic
from ..api import audio_upload
from ..engine.asr_prompt import normalize_language
from ..core.inference_log import (
    STATUS_ERROR,
    STATUS_OK,
    actor_from_key_id,
    build_context,
)
from ..core.client import WorkerError
from .paths import LocalFile, PathRefused, read_local_file

logger = logging.getLogger(__name__)

#: The record identity of everything this surface triggers.
SOURCE = "/mcp"

#: The MCP contract's own limits (see the task card): ``top_k`` 5 by default and
#: never above 20; ``neighbors`` 1 by default and never above 3; a PDF read is
#: the first 20 pages unless asked otherwise and never more than 50.
DEFAULT_TOP_K = 5
MAX_TOP_K = 20
DEFAULT_NEIGHBORS = 1
MAX_NEIGHBORS = 3
DEFAULT_PDF_PAGES = 20
MAX_PDF_PAGES_PER_CALL = 50

#: How many ``ocr_read``/``transcribe_audio`` calls may be in flight at once.
#: Both drive the NPU through a worker that serialises its own work anyway, so
#: the pool is not a throughput knob -- it is a memory bound. A queued OCR call
#: holds its decoded image, and a queued transcription holds its audio and its
#: worker queue slot; ten of each is how a 2.6 GB board runs out. Over the limit
#: a call is refused with "busy, retry", which a model can act on.
MAX_HEAVY_CALLS = 2

#: Candidates the pipeline fuses and reranks. 20 is what the console's own
#: search uses; a larger ``top_k`` has to widen it or the pipeline would return
#: fewer rows than asked for.
DEFAULT_CANDIDATES = 20

#: Where a transcription's language comes from when the caller does not say.
#: ``None`` asks the model to detect it, which is what the endpoint does too.
DEFAULT_ASR_LANGUAGE = None


class ToolError(Exception):
    """A tool refused or failed. Reported to the model as ``isError`` content.

    Deliberately not a JSON-RPC error: per MCP, a *tool* that could not do its
    job is a normal result carrying ``isError: true``, while a malformed
    ``tools/call`` is a protocol error. A model that gets the former can try a
    different argument; one that gets the latter usually cannot.
    """


# -- admission for the two NPU-heavy tools -----------------------------------
class _HeavyPool:
    """At most ``limit`` OCR/transcription calls at once.

    Not a queue. A caller that finds every slot taken is answered "busy, try
    again" straight away, which a model can retry on and a human can understand;
    waiting instead would hold the caller's decoded image (or its audio) in
    memory for an unbounded time, which is the thing this pool exists to prevent.

    A counter rather than an ``asyncio.Semaphore`` because the refusal has to be
    *immediate*: the check and the increment happen in one event-loop step with
    no ``await`` between them, so no two callers can both see the last free slot.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._in_flight = 0

    @property
    def in_flight(self) -> int:
        return self._in_flight

    @contextlib.contextmanager
    def slot(self, what: str):
        if self._in_flight >= self.limit:
            raise ToolError(
                f"{what}正在处理其他请求（同时最多 {self.limit} 个），请稍后重试")
        self._in_flight += 1
        try:
            yield
        finally:
            self._in_flight -= 1


#: Shared by ``ocr_read`` and ``transcribe_audio``: both saturate the same NPU
#: and both hold a large buffer while they wait.
HEAVY = _HeavyPool(MAX_HEAVY_CALLS)


# -- the attributed-log shim -------------------------------------------------
class _AttributedLog:
    """The inference log as the knowledge-base pipeline sees it, re-attributed.

    ``RecordContext.finish`` calls ``store.record(entry)``; ``build_context``
    only reads ``store.enabled``. Both are provided here, so the pipeline's own
    recording points keep working -- one row per embedding, rerank and OCR call
    -- with the MCP surface's identity stamped on the row instead of the
    console's. A ``None`` store stays ``None``: logging off stays off.
    """

    def __init__(self, store, actor: dict) -> None:
        self._store = store
        self._actor = actor or {}

    @property
    def enabled(self) -> bool:
        return bool(self._store is not None and getattr(self._store, "enabled", False))

    def record(self, entry: dict) -> bool:
        if self._store is None:
            return False
        stamped = {
            **entry,
            "source": SOURCE,
            "actor_type": self._actor.get("actor_type"),
            "actor_id": self._actor.get("actor_id"),
            "actor_name": self._actor.get("actor_name"),
        }
        return self._store.record(stamped)


class _Bag:
    """An attribute bag: the shim's ``app`` and ``app.state``.

    ``fallback`` is how this stays honest with code written after this file: the
    knowledge-base modules read parameters of ``app.state`` that the shim does not
    know about (``kb_store``, ``kb_bm25`` -- the upload route reaches them through
    the same ``request``). Enumerating them here would mean a new module reading
    a new attribute breaks MCP tools only, silently; delegating to the live state
    means the shim reads whatever the real request would, with the one deliberate
    exception of ``inference_log``, which is set explicitly and therefore wins.
    """

    def __init__(self, fallback=None, **fields) -> None:
        self.__dict__["_fallback"] = fallback
        self.__dict__.update(fields)

    def __getattr__(self, name: str):
        fallback = self.__dict__.get("_fallback")
        if fallback is not None:
            try:
                return getattr(fallback, name)
            except AttributeError:
                pass
        raise AttributeError(name)


class _ShimRequest:
    """A stand-in for the FastAPI request the app modules expect.

    Everything the code these tools call reads lives on ``app.state``; the shim
    forwards every attribute it does not override to the live state object, and
    overrides exactly one -- ``inference_log``, which is the attributed proxy
    above. The shim therefore changes *identity*, not behaviour.
    """

    def __init__(self, real, actor: dict) -> None:
        state = real.app.state
        self.app = _Bag(state=_Bag(
            fallback=state,
            inference_log=_AttributedLog(getattr(state, "inference_log", None), actor),
        ))
        self._real = real

    @property
    def real(self):
        return self._real


def _actor(request, key_name: str) -> dict:
    """Who called, for the record: the API key's name, never the key itself.

    ``/v1``'s own helper, given the key id the auth dependency put on the
    request. With ``require_api_key`` off there is no key and the fallback is
    anonymous rather than ``admin``: this surface is not the console.
    """
    store = getattr(request.app.state, "store", None)
    key_id = getattr(request.state, "mcp_key_id", None)
    if key_id:
        return actor_from_key_id(store, key_id)
    return {"actor_type": "api_key", "actor_id": None, "actor_name": key_name or None}


# -- knowledge base helpers --------------------------------------------------
def _store(request):
    return request.app.state.kb_store


def _ingestor(request):
    return request.app.state.kb_ingestor


def _data_root(request) -> Path:
    """The live data root, which a data-directory move updates in place."""
    return Path(request.app.state.agents.data_root)


def _kbs(request) -> list:
    return _store(request).list_kbs()


def _describe_kb(kb) -> str:
    bits = [f"{kb.name}（id {kb.id}）", f"{kb.doc_count} 篇文档", f"{kb.chunk_count} 个片段"]
    if kb.embedding_model:
        bits.append(f"embedding {kb.embedding_model}")
    else:
        bits.append("未建向量索引")
    if kb.needs_reindex:
        bits.append("需要重建索引")
    return "，".join(bits)


def _pick_kb(request, wanted: str | None):
    """The library named by id or name, or the only one there is.

    ``kb`` is optional in ``kb_search`` alone -- "the library" is unambiguous
    when there is one. Every other tool needs an explicit target, because
    guessing which library to write into is not a guess worth making.
    """
    kbs = _kbs(request)
    if not kbs:
        raise ToolError("还没有知识库。可以先用 kb_create 建一个，再用 kb_add_document 添加文档。")
    text = (wanted or "").strip()
    if not text:
        if len(kbs) == 1:
            return kbs[0]
        raise ToolError(
            "有多个知识库，请用 kb 参数指定（id 或名称）："
            + "；".join(f"{kb.name}（{kb.id}）" for kb in kbs))
    for kb in kbs:
        if kb.id == text or kb.name == text:
            return kb
    lowered = text.lower()
    matches = [kb for kb in kbs if kb.name.lower() == lowered]
    if len(matches) == 1:
        return matches[0]
    raise ToolError(
        f"没有名为 {text!r} 的知识库。现有："
        + "；".join(f"{kb.name}（{kb.id}）" for kb in kbs))


def _bm25_for(request, kb_id: str, chunks: list[dict]) -> Bm25Index:
    """The library's BM25 index, cached exactly as the console's route caches it.

    Same cache, same signature: an upload, a delete or a retry changes the chunk
    count or the last chunk's id, and either way the index is rebuilt. Sharing
    the console's cache is deliberate -- two indexes over the same 20 000 chunks
    is twice the memory on a board that does not have it, and the console's
    invalidation then serves this surface too.

    Must be called from a thread (``Bm25Index.build`` is O(library)): see
    :func:`_load_library`.
    """
    cache = request.app.state.kb_bm25
    signature = (len(chunks), chunks[-1]["id"] if chunks else "")
    hit = cache.get(kb_id)
    if hit is not None and hit[0] == signature:
        return hit[1]
    index = Bm25Index.build(chunks)
    cache[kb_id] = (signature, index)
    return index


def _load_library(request, kb):
    """``(chunks, vectors, bm25)`` for a library, computed off the event loop.

    Every part of this is disk or CPU work that grows with the library: reading
    ``chunks.jsonl`` parses one JSON object per line, ``aligned_vectors`` loads a
    float matrix, and ``Bm25Index.build`` tokenises every chunk. On a 20 000-chunk
    library that is seconds, and doing it on the loop would stall every other
    request -- so the whole group is one ``to_thread`` and the caller gets the
    three objects it needs.

    The BM25 index still comes from the shared cache, so a second search pays
    only the ``load_chunks`` cost, which the console's route pays too.
    """
    store = _store(request)
    chunks = store.load_chunks(kb.id)
    # `aligned_vectors` flags a library whose matrix no longer lines up with the
    # chunk file, which is the durable signal the vector stage quotes.
    vectors = None if kb.needs_reindex else store.aligned_vectors(kb.id, chunks)
    return chunks, vectors, _bm25_for(request, kb.id, chunks)


def _chunk_view(chunk: dict, index: int, kb_name: str) -> dict:
    return {
        "chunk_id": chunk.get("id"),
        "doc_id": chunk.get("doc_id"),
        "doc_name": (chunk.get("doc") or {}).get("name"),
        "page": chunk.get("page"),
        "source": chunk.get("source"),
        "text": chunk.get("text"),
        "kb": kb_name,
        "position": index,
    }


def _citation(row: dict, rank: int, *, with_kb: str | None = None) -> str:
    """One result in the shape the card asks for: ``[n] 文档名 第 p 页（相关度 x）``.

    The relevance number is whatever decided the order -- the rerank score when
    the rerank stage ran, the RRF score otherwise -- so a reader comparing the
    list to the score is comparing the number that actually sorted it.
    """
    scores = row.get("scores") or {}
    score = scores.get("rerank")
    if score is None:
        score = scores.get("rrf")
    label = row.get("doc_name") or "（未命名文档）"
    page = row.get("page")
    where = f"{label} 第 {page} 页" if page else label
    if with_kb:
        where = f"[{with_kb}] {where}"
    shown = f"（相关度 {score:.3f}）" if isinstance(score, (int, float)) else ""
    # The chunk id is what kb_read takes. It is in structuredContent too, but a
    # model only sees the text content in most MCP clients -- without it here,
    # "use kb_read for more context" pointed at an id the model never saw.
    cid = row.get("chunk_id")
    ref = f"  chunk_id={cid}" if cid else ""
    return f"[{rank}] {where}{shown}{ref}\n{row.get('text') or ''}"


def _stages_summary(stages: dict) -> str:
    """Which stages ran and which were skipped, in one line the model can read."""
    ran: list[str] = []
    skipped: list[str] = []
    for name, stage in stages.items():
        status = stage.get("status")
        if status == "skipped":
            reason = stage.get("reason") or "未说明原因"
            skipped.append(f"{name}（{reason}）")
        else:
            ran.append(f"{name} {stage.get('ms', 0):.0f} ms")
    parts = []
    parts.append("执行：" + ("、".join(ran) if ran else "无"))
    if skipped:
        parts.append("跳过：" + "、".join(skipped))
    else:
        parts.append("跳过：无")
    return "；".join(parts)


async def _search_one(shim, kb, query: str, top_k: int, candidates: int):
    chunks, vectors, index = await asyncio.to_thread(_load_library, shim, kb)
    return await kb_retrieval.search(
        shim, kb=kb, chunks=chunks, bm25=index, vectors=vectors,
        req=kb_retrieval.SearchRequest(
            query=query, top_k=top_k, candidates=candidates,
            use_bm25=True, use_vector=True, use_rerank=True))


# -- the tools ---------------------------------------------------------------
async def kb_list(request, args: dict, ctx: dict) -> tuple[str, dict]:
    """Every library with the numbers an agent needs to choose one."""
    kbs = _kbs(request)
    if not kbs:
        return "还没有知识库。", {"kbs": []}
    lines = [f"共 {len(kbs)} 个知识库："]
    for kb in kbs:
        lines.append(f"- {_describe_kb(kb)}")
    return "\n".join(lines), {"kbs": [kb.public() for kb in kbs]}


async def kb_create(request, args: dict, ctx: dict) -> tuple[str, dict]:
    name = str(args.get("name") or "").strip()
    if not name:
        raise ToolError("name 不能为空")
    try:
        kb = _store(request).create_kb(name)
    except KbError as exc:
        raise ToolError(str(exc)) from None
    return (f"已创建知识库 {kb.name}（id {kb.id}）。"
            f"用 kb_add_document 添加文档，建库完成后就能用 kb_search 检索。",
            {"kb": kb.public()})


async def kb_search(request, args: dict, ctx: dict) -> tuple[str, dict]:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ToolError("query 不能为空")
    top_k = _bounded_int(args.get("top_k"), DEFAULT_TOP_K, 1, MAX_TOP_K, "top_k")
    candidates = max(DEFAULT_CANDIDATES, top_k)

    wanted = args.get("kb")
    kbs = _kbs(request)
    if not kbs:
        raise ToolError("还没有知识库。可以先用 kb_create 建一个，再用 kb_add_document 添加文档。")
    if (wanted or "").strip():
        targets = [_pick_kb(request, wanted)]
    else:
        # No library named: one library means "the library"; several means
        # search them all, because an agent asked a question, not a filing
        # question. Each hit is labelled with the library it came from.
        targets = kbs

    rows_by_kb: list[list[dict]] = []
    summaries: list[str] = []
    for kb in targets:
        try:
            result = await _search_one(ctx["shim"], kb, query, top_k, candidates)
        except KbNotFound:
            raise ToolError(f"知识库 {kb.name} 在检索时消失了，请重试") from None
        except KbError as exc:
            raise ToolError(f"{kb.name}：{exc}") from None
        public = result.public()
        rows_by_kb.append([{**row, "kb": kb.name, "kb_id": kb.id}
                           for row in public["results"]])
        summaries.append(f"{kb.name}：{_stages_summary(public['stages'])}")

    if not any(rows_by_kb):
        text = (f"没有检索到与「{query}」相关的片段。\n" + "\n".join(summaries))
        return text, {"query": query, "results": [],
                      "kbs": [{"id": kb.id, "name": kb.name} for kb in targets]}

    merged = _interleave(rows_by_kb)[:top_k]
    lines = [f"检索「{query}」共 {len(merged)} 条："]
    for rank, row in enumerate(merged, 1):
        label = row["kb"] if len(targets) > 1 else None
        lines.append(_citation(row, rank, with_kb=label))
    lines.append("")
    if len(targets) > 1:
        # Said out loud because the numbers are not comparable: one library may
        # have been reranked (a sigmoid, 0..1) while another fell back to RRF
        # (1/(60+rank), ~0.016). Sorting on those across libraries would claim an
        # order the scores do not support, so the merge keeps each library's own
        # order and interleaves by rank instead.
        lines.append("（多个知识库的结果按各自的排名交错排列；不同库的「相关度」"
                     "来自不同步骤，不能互相比较。）")
    lines.extend(summaries)
    lines.append("需要更多上下文时，用 kb_read 读取某个片段的相邻片段。")
    return "\n".join(lines), {
        "query": query,
        "results": [{
            "rank": rank,
            "chunk_id": row.get("chunk_id"),
            "doc_id": row.get("doc_id"),
            "doc_name": row.get("doc_name"),
            "page": row.get("page"),
            "source": row.get("source"),
            "text": row.get("text"),
            "kb": row.get("kb"),
            "kb_id": row.get("kb_id"),
            "scores": row.get("scores"),
        } for rank, row in enumerate(merged, 1)],
        "kbs": [{"id": kb.id, "name": kb.name} for kb in targets],
        "stages": dict(zip([kb.name for kb in targets], summaries)),
    }


def _interleave(ranked_lists: list[list[dict]]) -> list[dict]:
    """Rank-1 of every library, then rank-2 of every library, and so on.

    The reason this is not a global sort on score: the number that ordered one
    library's list is not the number that ordered another's. A reranked library
    ranks by ``sigmoid(logit)`` in 0..1 and a library with no reranker loaded
    falls back to RRF's ``1/(60+rank)``, around 0.016 -- so a global descending
    sort puts *every* reranked row above *every* RRF one, which is an artefact of
    two different scales, not a statement about relevance. Interleaving compares
    ranks, which do mean the same thing in both lists, and guarantees a small
    library is still represented in a top-5 that a large one would otherwise fill.
    """
    out: list[dict] = []
    depth = max((len(rows) for rows in ranked_lists), default=0)
    for index in range(depth):
        for rows in ranked_lists:
            if index < len(rows):
                out.append(rows[index])
    return out


async def kb_read(request, args: dict, ctx: dict) -> tuple[str, dict]:
    chunk_id = str(args.get("chunk_id") or "").strip()
    if not chunk_id:
        raise ToolError("chunk_id 不能为空")
    neighbors = _bounded_int(args.get("neighbors"), DEFAULT_NEIGHBORS, 0, MAX_NEIGHBORS,
                            "neighbors")
    store = _store(request)
    for kb in _kbs(request):
        chunks = await asyncio.to_thread(store.load_chunks, kb.id)
        index = next((i for i, c in enumerate(chunks) if c.get("id") == chunk_id), None)
        if index is None:
            continue
        # Neighbours are the chunks before and after *in the same document*. The
        # knowledge base keeps every document's chunks in one list, so a window
        # on that list crossed into the previous or next document (a one-chunk
        # note "neighboured" the last page of an unrelated PDF -- MYS-2682 E2E).
        doc_of = lambda c: c.get("doc_id") or str(c.get("id") or "").rsplit(":", 1)[0]
        same = [i for i, c in enumerate(chunks) if doc_of(c) == doc_of(chunks[index])]
        pos = same.index(index)
        window = [_chunk_view(chunks[i], i, kb.name)
                  for i in same[max(0, pos - neighbors):pos + neighbors + 1]]
        lines = [f"知识库 {kb.name} 中 {chunk_id} 及其前后各 {neighbors} 个片段："]
        for row in window:
            mark = " ←" if row["chunk_id"] == chunk_id else ""
            page = f"第 {row['page']} 页" if row["page"] else ""
            lines.append(f"\n--- {row['chunk_id']}{mark} {row['doc_name'] or ''} {page}".rstrip())
            lines.append(row["text"] or "")
        return "\n".join(lines), {"chunk_id": chunk_id, "kb": kb.name, "kb_id": kb.id,
                                  "chunks": window}
    raise ToolError(f"没有找到片段 {chunk_id}；它可能属于已被删除或重建的知识库。"
                    "用 kb_search 重新检索一次可以拿到当前有效的 chunk_id。")


async def kb_list_documents(request, args: dict, ctx: dict) -> tuple[str, dict]:
    kb = _pick_kb(request, args.get("kb"))
    try:
        docs = _store(request).list_docs(kb.id)
    except KbNotFound:
        raise ToolError(f"知识库 {kb.name} 不存在") from None
    if not docs:
        return f"知识库 {kb.name} 还没有文档。", {"kb": kb.public(), "documents": []}
    lines = [f"知识库 {kb.name} 共 {len(docs)} 篇文档："]
    for meta in docs:
        lines.append("- " + _doc_line(meta))
    return "\n".join(lines), {"kb": kb.public(), "documents": [_doc_view(m) for m in docs]}


def _doc_line(meta: dict) -> str:
    bits = [f"{meta.get('name') or '（未命名）'}", f"id {meta.get('id')}",
            f"状态 {meta.get('status')}"]
    if meta.get("chunks"):
        bits.append(f"{meta['chunks']} 个片段")
    if meta.get("status") == "failed" and meta.get("error"):
        bits.append(f"错误：{meta['error']}")
    return "，".join(bits)


def _doc_view(meta: dict) -> dict:
    return {
        "id": meta.get("id"),
        "name": meta.get("name"),
        "type": meta.get("type"),
        "bytes": int(meta.get("bytes") or 0),
        "pages": int(meta.get("pages") or 0),
        "status": meta.get("status"),
        "progress": meta.get("progress"),
        "error": meta.get("error"),
        "warnings": list(meta.get("warnings") or []),
        "chunks": int(meta.get("chunks") or 0),
        "created_at": meta.get("created_at"),
    }


async def kb_add_document(request, args: dict, ctx: dict) -> tuple[str, dict]:
    """Queue one document, from a local path or from text, and return at once.

    Returns the doc id and ``queued`` without waiting: a 300-page scan is minutes
    of NPU time, far past any client's tool-call timeout. ``kb_document_status``
    is how the model (or the person driving it) learns when it is ready.

    ``app/api/apps_api.py`` has no public "add these bytes as a document"
    function -- the upload route does it inline -- so the few steps that make a
    document are repeated here. They are the route's own steps in the route's
    own order (write the source file *before* queueing, so a restart leaves a
    retryable record rather than a queue entry pointing at nothing).
    """
    kb = _pick_kb(request, args.get("kb"))
    store = _store(request)
    ingestor = _ingestor(request)

    path_arg = str(args.get("path") or "").strip()
    text_arg = args.get("text")
    name_arg = str(args.get("name") or "").strip()
    if path_arg and text_arg is not None:
        raise ToolError("path 与 text 只能给一个：本地文件用 path，直接写内容用 text + name")
    if not path_arg and text_arg is None:
        raise ToolError("需要 path（设备本地文件）或 text + name 之一")

    if path_arg:
        read = await _read_path(request, path_arg)
        data = read.data
        filename = read.name
    else:
        if not name_arg:
            raise ToolError("用 text 添加文档时必须给 name（文档名）")
        text = text_arg if isinstance(text_arg, str) else str(text_arg)
        data = text.encode("utf-8")
        filename = name_arg
        if not data:
            raise ToolError("text 不能为空")

    try:
        # `validate_upload` decodes a header, opens a PDF's page tree or reads an
        # image's size: cheap per call, but not free, and this route is on the
        # event loop. It runs in a thread with the write below, which is the
        # other blocking step (up to 50 MiB + fsync).
        kind = await asyncio.to_thread(_check_uploadable, filename, data)
    except kb_parse.ParseError as exc:
        raise ToolError(f"{filename}：{exc}") from None
    if len(data) > kb_parse.MAX_FILE_BYTES:
        raise ToolError(f"{filename} 有 {len(data) / 2**20:.1f} MB，"
                        f"超过单个文件上限 {kb_parse.MAX_FILE_BYTES // 2**20} MB")
    if ingestor.is_reindexing(kb.id):
        raise ToolError(f"知识库 {kb.name} 正在重建索引，请等任务完成后再添加文档")

    doc_id = new_id()
    meta = {
        "id": doc_id,
        "name": filename,
        "type": kind,
        "bytes": len(data),
        "pages": 0,
        "status": QUEUED,
        "progress": {"stage": QUEUED, "done": 0, "total": 1},
        "error": None,
        "warnings": [],
        "chunks": 0,
        "text_pages": 0,
        "ocr_pages": 0,
        "created_at": time.time(),
    }
    await asyncio.to_thread(_write_document, store, kb.id, doc_id, filename, kind,
                            data, meta)
    # The shim, so the ingestion queue's own embedding calls are recorded as
    # this tool's inference (source /mcp, this key as the actor) rather than as
    # a console upload.
    ingestor.submit(Job(kb_id=kb.id, doc_id=doc_id, request=ctx["shim"]))
    _bump_doc_count(store, kb.id)
    # The chunk set is about to change, so the cached BM25 index is stale.
    request.app.state.kb_bm25.pop(kb.id, None)

    return (f"已加入 {filename}（文档 id {doc_id}，类型 {kind}，"
            f"{len(data) / 1024:.1f} KB），状态 {QUEUED}。"
            f"建库是后台任务，用 kb_document_status 查询进度。",
            {"kb": kb.public(), "doc_id": doc_id, "name": filename,
             "type": kind, "bytes": len(data), "status": QUEUED})


def _suffix_for(filename: str, kind: str) -> str:
    """The suffix the source is stored under; same table the upload route uses."""
    suffix = Path(filename or "").suffix.lower()
    allowed = (".txt", ".md", ".markdown", ".pdf") + kb_parse.IMAGE_SUFFIXES
    if suffix in allowed:
        return suffix
    return {"pdf": ".pdf", "md": ".md", "txt": ".txt", "image": ".png"}[kind]


def _check_uploadable(filename: str, data: bytes) -> str:
    """The document's kind, after the upload route's own cheap refusals."""
    kind = kb_parse.detect_kind(filename, data)
    kb_parse.validate_upload(kind, data)
    return kind


def _write_document(store, kb_id: str, doc_id: str, filename: str, kind: str,
                    data: bytes, meta: dict) -> None:
    """Create the document directory, write the source, then the record.

    Order matters and is the upload route's: the source file first, so a restart
    between the two leaves a directory the ingestor can retry rather than a queue
    entry pointing at nothing. Blocking -- it writes up to 50 MiB and fsyncs.
    """
    directory = store.docs_dir(kb_id) / doc_id
    (directory / "pages").mkdir(parents=True)
    write_bytes_atomic(directory / f"source{_suffix_for(filename, kind)}", data)
    store.write_doc_meta(kb_id, doc_id, meta)


def _bump_doc_count(store, kb_id: str) -> None:
    try:
        kb = store.load_kb(kb_id)
        kb.doc_count = len(store.list_docs(kb_id))
        store.save_kb(kb)
    except KbError:  # pragma: no cover - the library went away mid-call
        pass


async def kb_document_status(request, args: dict, ctx: dict) -> tuple[str, dict]:
    kb = _pick_kb(request, args.get("kb"))
    doc_id = str(args.get("doc_id") or "").strip()
    if not doc_id:
        raise ToolError("doc_id 不能为空")
    try:
        meta = _store(request).read_doc_meta(kb.id, doc_id)
    except KbNotFound:
        raise ToolError(f"知识库 {kb.name} 里没有文档 {doc_id}；"
                        "用 kb_list_documents 查看当前的文档 id") from None
    view = _doc_view(meta)
    lines = [f"{view['name'] or doc_id}：状态 {view['status']}"]
    progress = view.get("progress")
    if progress:
        lines.append(f"进度 {progress.get('stage')} {progress.get('done')}/{progress.get('total')}")
    if view["chunks"]:
        lines.append(f"{view['chunks']} 个片段")
    if view.get("error"):
        lines.append(f"错误：{view['error']}")
    for warning in view["warnings"]:
        lines.append(f"提示：{warning}")
    if view["status"] == QUEUED or view["status"] in ("parsing", "ocr", "embedding"):
        lines.append("建库还没完成，稍后再查一次。")
    return "\n".join(lines), {"kb": kb.public(), "document": view}


async def ocr_read(request, args: dict, ctx: dict) -> tuple[str, dict]:
    """Text out of an image or a PDF, without touching any library.

    Images go through PP-OCR exactly as a scanned page does in the knowledge-base
    builder (same parser, same preprocessing, same reading order). A PDF is read
    page by page: a page with a text layer is returned as it is, and only a
    scanned page costs an OCR pass -- which is also why a PDF read is bounded by
    page count rather than by bytes.

    ``mode`` selects what a scanned page comes back as:

    * ``lines`` (the default) -- the page's lines, joined by newlines. Right for
      a screenshot, a crop, a single-column form.
    * ``layout`` -- the page segmented into title / paragraph / table / figure
      regions and rendered as Markdown, with the regions in reading order. Right
      for a whole document page, and the only mode that does not interleave a
      two-column page. It costs one extra NPU pass (~3 ms) per scanned page.
    * ``vl`` -- the same regions, but each one read by **PaddleOCR-VL-1.5**
      instead of PP-OCR, with the instruction its class gets. Right for a
      document whose tables and formulas matter: a table comes back as HTML with
      its merged cells, which PP-OCR cannot produce at all. Much slower (a page
      is one VLM answer per region, tens of seconds on this board) and it needs
      two models loaded, so it is opt-in per call.

    A page that *has* a text layer is returned from the layer in every mode: the
    layer is exact where OCR is approximate, and re-OCRing a digital PDF would
    throw away the better answer. So ``layout``/``vl`` on a digital PDF changes
    nothing, which the tool description says rather than leaving the caller to
    discover.

    The file is checked exactly as an upload is -- type, size, PDF page count and
    image pixel count -- because this tool decodes the same bytes the uploader
    would. Skipping that was a real hole: a 50 MiB PNG can be 170 Mpx, which
    decodes to more than half a gigabyte of RGB.

    Both the checks and the parse are off the event loop, and the whole call
    holds a slot in :data:`HEAVY` so two OCR passes are the most that can be
    running (and holding their image) at once.
    """
    path_arg = str(args.get("path") or "").strip()
    if not path_arg:
        raise ToolError("path 不能为空")
    mode = str(args.get("mode") or "lines").strip().lower()
    if mode not in ("lines", "layout", "vl"):
        raise ToolError(f'mode 只能是 "lines" / "layout" / "vl"（收到 {mode!r}）')
    with HEAVY.slot("OCR "):
        read, kind, total_pages = await _read_validated(request, path_arg)
        if kind in ("txt", "md"):
            raise ToolError("ocr_read 只处理图片和 PDF；纯文本文件可以直接读取，不需要 OCR")

        # On demand: an MCP caller asking to read a page is asking for the OCR
        # result, not for a lecture about which model is loaded. The load is
        # awaited here rather than inside the parse thread (see ``_OcrBridge``),
        # and the slot above is already held, so the heavy-work bound counts the
        # load too -- which is right: it holds the NPU for a couple of seconds.
        ocr_model = await kb_models.resolve_or_load(request, "ocr")
        ocr_available = bool(ocr_model)
        # ``vl`` needs the VLM too, and it is *not* auto-loaded: loading 3.3 GB
        # because a tool was called would be a surprise the operator pays for.
        # So a missing VLM is a refused call with a reason, not a silent
        # downgrade to ``layout`` -- the caller asked for table structure.
        vl_model = None
        if ocr_available and mode == "vl":
            vl_model = kb_models.resolve(request, "ocr_vl")
            if not vl_model:
                raise ToolError(
                    'mode="vl" 需要 PaddleOCR-VL 模型已加载（它不会被自动加载，'
                    f"因为要占 3.3 GB 显存）：{vl_model.reason}；"
                    '可以在控制台的「模型」页加载它，或改用 mode="layout"'
                    "（表格只给文字）")
        bridge = None
        if ocr_available:
            bridge = _OcrBridge(ctx, ocr_model, mode, _event_loop(request),
                                vl_model=vl_model)

        if kind == "image":
            return await _read_image(read, bridge, ocr_available, mode, bridge)
        return await _read_pdf(read, total_pages, bridge, ocr_available,
                               pages_arg=args.get("pages"), mode=mode)


def _event_loop(request):
    """The loop the worker client's socket lives on, for a thread-side bridge."""
    import asyncio as _asyncio

    loop = getattr(request.app.state, "event_loop", None)
    return loop if loop is not None else _asyncio.get_event_loop()


async def _read_image(read: LocalFile, run_ocr, ocr_available: bool,
                      mode: str = "lines", bridge=None):
    try:
        doc = await asyncio.to_thread(kb_parse.parse_image, read.data, ocr=run_ocr)
    except kb_parse.ParseError as exc:
        raise ToolError(str(exc)) from None
    page = doc.pages[0] if doc.pages else None
    text = (page.text if page else "") or ""
    if not ocr_available:
        message = ("图片里的文字需要 OCR 模型，但当前没有加载。"
                   "请在控制台的模型页加载 PP-OCR 后重试。")
        return message, {"path": str(read.path), "kind": "image", "ocr": False,
                         "text": "", "warnings": list(doc.warnings)}
    if mode in ("layout", "vl"):
        rendered = _layout_markdown(doc, bridge)
        if rendered:
            text = rendered
    if not text.strip():
        return ("OCR 没有识别出文字；图片可能没有清晰可辨的文本。",
                {"path": str(read.path), "kind": "image", "ocr": True, "text": "",
                 "mode": mode, "warnings": list(doc.warnings)})
    header = (f"{read.name}（图片，{'VL' if mode == 'vl' else '版面'}模式，Markdown）"
              if mode in ("layout", "vl")
              else f"{read.name}（图片，OCR）共 {len(text.splitlines())} 行：")
    return f"{header}\n{text}", {
        "path": str(read.path), "kind": "image", "ocr": True, "mode": mode,
        "pages": [{"page": 1, "source": "ocr", "text": text,
                   **({"markdown": text} if mode in ("layout", "vl") else {})}],
        "text": text,
        "warnings": list(doc.warnings),
    }


def _layout_markdown(doc, bridge) -> str:
    """The layout Markdown for a page, if the bridge recorded one.

    The parser's ``ocr`` hook is typed ``png -> list[OcrLine]``, so the Markdown
    cannot travel through its return value. The bridge keeps it beside the lines
    (see :class:`_OcrBridge`), keyed by the page it belongs to.
    """
    if bridge is None:
        return ""
    for page in doc.pages:
        rendered = bridge.markdown_for(page.number)
        if rendered:
            return rendered
    return ""


async def _read_pdf(read: LocalFile, total_pages: int, run_ocr, ocr_available: bool,
                    pages_arg, mode: str = "lines"):
    selection = _parse_pages(pages_arg, total_pages)
    subset = await asyncio.to_thread(_pdf_pages, read.data, selection)
    try:
        doc = await asyncio.to_thread(kb_parse.parse_pdf, subset, ocr=run_ocr)
    except kb_parse.ParseError as exc:
        raise ToolError(str(exc)) from None
    # The subset is renumbered 1..N, so its page *n* is the original's
    # ``selection[n-1]``. Not ``n + selection[0] - 1``: a request may name pages
    # that are not contiguous ("1,5"), and the offset form would label the
    # second page of that subset "page 2" when it is page 5. A reader checking a
    # citation against their own copy would then look at the wrong page.
    def original(number: int | None) -> int:
        index = (number or 1) - 1
        if 0 <= index < len(selection):
            return selection[index]
        return (number or 1) + selection[0] - 1

    sections: list[dict] = []
    blocks: list[str] = []
    # Pages this document OCR'd, in order: the bridge recorded one Markdown per
    # such page, and the subset's page numbers are contiguous, so counting the
    # scanned pages recovers which Markdown belongs where.
    scanned = 0
    for page in doc.pages:
        number = original(page.number)
        source = "OCR" if page.source == "ocr" else "文字层"
        text = (page.text or "").strip()
        markdown = ""
        if page.source == "ocr":
            scanned += 1
            if mode in ("layout", "vl") and run_ocr is not None:
                markdown = run_ocr.markdown_for(scanned)
                if markdown:
                    text = markdown
        if not text:
            if not ocr_available:
                body = ("本页没有文字层，需要 OCR；当前未加载 OCR 模型，无法识别。")
            else:
                body = "（本页没有提取到文字）"
        else:
            body = text
        blocks.append(f"## 第 {number} 页（{source}）\n{body}")
        sections.append({"page": number, "source": page.source,
                         "text": text, "empty": not text,
                         **({"markdown": markdown} if markdown else {})})
    read_note = (f"{read.name}：共 {total_pages} 页，本次读取 "
                 f"{_pages_label(selection)}。")
    if mode in ("layout", "vl"):
        # Said explicitly because a digital PDF is unaffected by the mode, and a
        # caller who chose layout for its structure would otherwise wonder why
        # the pages came back unchanged.
        what = "VL 逐区域识别" if mode == "vl" else "版面识别"
        read_note += (f"{'VL' if mode == 'vl' else '版面'}模式：有文字层的页仍直接取文字层，"
                      f"只有扫描页走{what}并输出 Markdown。")
    if len(selection) < total_pages and pages_arg in (None, ""):
        read_note += (f"（默认只读前 {DEFAULT_PDF_PAGES} 页；"
                      f"要读其他页请用 pages 指定）")
    elif pages_arg not in (None, "") and _asked_beyond_budget(pages_arg, total_pages):
        # The cap applies silently otherwise, and a model that asked for 300
        # pages would believe it read them all.
        read_note += (f"（本次按单次上限取了前 {MAX_PDF_PAGES_PER_CALL} 页；"
                      f"其余页请再调用一次并指定 pages）")
    if not ocr_available and doc.ocr_pages:
        read_note += f"\n注意：其中 {doc.ocr_pages} 页没有文字层，需要 OCR 模型，本次已跳过。"
    body = "\n\n".join(blocks) if blocks else "（没有内容）"
    return f"{read_note}\n\n{body}", {
        "path": str(read.path), "kind": "pdf", "ocr": ocr_available,
        "total_pages": total_pages, "pages": sections,
        "text_pages": doc.text_pages, "ocr_pages": doc.ocr_pages,
        "warnings": list(doc.warnings),
    }


def _asked_beyond_budget(spec, total_pages: int) -> bool:
    """Whether ``spec`` wants more pages than one call can return.

    True only when the request exceeds the cap *and* the document has pages the
    call did not read. ``pages="1-2000000000"`` on a 30-page file is asking for
    everything there is, and telling that caller "the rest needs another call"
    would be a lie -- the cap was not what limited the read.

    Range arithmetic on purpose: counting what a spec asks for must not become
    the very expansion ``_parse_pages`` was fixed to avoid.
    """
    wanted = 0
    for part in str(spec).replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        left, _, right = part.partition("-")
        try:
            start = int(left.strip())
            end = int(right.strip()) if right else start
        except ValueError:
            return False  # parse errors are `_parse_pages`'s to report
        wanted += abs(end - start) + 1
        if wanted > MAX_PDF_PAGES_PER_CALL:
            return total_pages > MAX_PDF_PAGES_PER_CALL
    return False


def _pages_label(pages: list[int]) -> str:
    """``1–5`` for a run, ``1、3、7–9`` when the request was not contiguous."""
    if not pages:
        return "0 页"
    runs: list[tuple[int, int]] = []
    start = prev = pages[0]
    for page in pages[1:]:
        if page == prev + 1:
            prev = page
            continue
        runs.append((start, prev))
        start = prev = page
    runs.append((start, prev))
    parts = [f"{a}" if a == b else f"{a}–{b}" for a, b in runs]
    return "、".join(parts) + " 页"


def _pdf_page_count(data: bytes) -> int:
    """How many pages a PDF has, from its page tree (no page is rendered)."""
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - the release always has it
        raise ToolError("这个版本不能读 PDF：vendor 里缺少 pypdfium2") from exc
    try:
        doc = pdfium.PdfDocument(data)
    except Exception as exc:
        raise ToolError(f"PDF 无法打开：{exc}") from None
    try:
        total = len(doc)
    finally:
        doc.close()
    if total < 1:
        raise ToolError("PDF 没有页面")
    return total


def _parse_pages(spec, total: int) -> list[int]:
    """The 1-based page numbers to read, from ``"1-5"``/``"3"``/``"1-5,8"``.

    Unspecified means the first :data:`DEFAULT_PDF_PAGES`, and either way the
    result is capped at :data:`MAX_PDF_PAGES_PER_CALL` pages and at the
    document's own length. The cap is stated in the message rather than silently
    applied: a model that asked for 300 pages should learn why it got 50.

    **Intervals are clipped before they are expanded.** ``pages="1-2000000000"``
    is eleven characters, and expanding it first would build two billion integers
    -- seconds of CPU and gigabytes of RAM, on the request thread. Each range is
    therefore intersected with ``[1, total]`` and only ``MAX_PDF_PAGES_PER_CALL``
    values are ever materialised: the budget is spent range by range, in the
    order the caller wrote them, so the pages that survive are the first ones
    asked for rather than an arbitrary slice of a huge expansion.
    """
    if spec is None or str(spec).strip() == "":
        return list(range(1, min(total, DEFAULT_PDF_PAGES) + 1))

    budget = MAX_PDF_PAGES_PER_CALL
    wanted: list[int] = []
    saw_any = False
    lowest: int | None = None
    for part in str(spec).replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        saw_any = True
        if "-" in part:
            left, _, right = part.partition("-")
            try:
                start, end = int(left.strip()), int(right.strip())
            except ValueError:
                raise ToolError(f"pages 写法看不懂：{spec!r}（示例 \"1-5\"）") from None
            if start > end:
                start, end = end, start
        else:
            try:
                start = end = int(part)
            except ValueError:
                raise ToolError(f"pages 写法看不懂：{spec!r}（示例 \"1-5\"）") from None
        if lowest is None or start < lowest:
            lowest = start
        # Clip to the document *and* to what is left of this call's budget
        # before a single integer is created.
        first = max(start, 1)
        last = min(end, total)
        if first > last or budget <= 0:
            continue
        take = min(last, first + budget - 1)
        wanted.extend(range(first, take + 1))
        budget -= take - first + 1

    if not saw_any:
        raise ToolError(f"pages 没有解析出任何页码：{spec!r}")
    if lowest is not None and lowest < 1:
        raise ToolError("页码从 1 开始")
    if lowest is not None and lowest > total:
        raise ToolError(f"PDF 只有 {total} 页，pages 从第 {lowest} 页开始")
    # At least one range starts inside the document (that is what ``lowest <=
    # total`` above guarantees), so ``wanted`` cannot be empty here.
    return sorted(set(wanted))


def _pdf_pages(data: bytes, pages: list[int]) -> bytes:
    """A PDF containing only ``pages`` (1-based), in the order given.

    Parsing the whole document and throwing pages away would render every page's
    preview and, for a scan, run OCR over pages nobody asked for -- minutes of
    NPU time on a 300-page file. Cutting first is what makes the page limit a
    real limit.
    """
    import io

    import pypdfium2 as pdfium

    source = pdfium.PdfDocument(data)
    try:
        if len(pages) == len(source) and pages == list(range(1, len(source) + 1)):
            return data
        out = pdfium.PdfDocument.new()
        # pdfium refuses to import into a document with no pages at all, so a
        # scratch page is added and removed again.
        out.new_page(1, 1)
        del out[0]
        out.import_pages(source, pages=[p - 1 for p in pages])
        buffer = io.BytesIO()
        out.save(buffer)
        return buffer.getvalue()
    finally:
        source.close()


class _OcrBridge:
    """A synchronous OCR callable for the parser's worker thread.

    ``parse_pdf``/``parse_image`` run in a thread (they render and decode), and
    the worker client's socket lives on the event loop; an ``async`` callable
    there would be created and never awaited, and every scanned page would come
    back blank. Same bridge ``ingest._ocr_lines_sync`` uses, for the same reason.

    ``mode="layout"`` and ``mode="vl"`` also keep each page's Markdown, in call
    order: the parser hook is typed ``png -> list[OcrLine]``, so the Markdown --
    the whole reason to ask for layout -- cannot travel through its return
    value. ``markdown_for`` hands it back afterwards, indexed by the page the
    parse reported.

    ``vl`` also needs the VLM's own worker, so the bridge holds a second
    resolved model. A page in this mode produces no ``OcrLine`` objects at all
    (the VLM's output is a whole region, not line boxes), so the parser gets an
    empty list and the page's text comes entirely from ``markdown_for`` -- which
    is honest: the page has no per-line geometry to give.
    """

    def __init__(self, ctx: dict, ocr_model, mode: str, loop,
                 vl_model=None) -> None:
        self._ctx = ctx
        self._model = ocr_model
        self._mode = mode
        self._loop = loop
        self._vl_model = vl_model
        #: One entry per page this bridge OCR'd, in the order ``parse_pdf``
        #: visits them (page order). A page with a text layer never calls the
        #: hook, so this list is shorter than the document.
        self._markdown: list[str] = []

    def __call__(self, png: bytes):
        import asyncio as _asyncio

        from ..core.client import OCR_TIMEOUT_S

        future = _asyncio.run_coroutine_threadsafe(
            self._ocr_page(png), self._loop)
        return future.result(timeout=OCR_TIMEOUT_S + 30.0)

    async def _ocr_page(self, png: bytes):
        from ..apps.kb.retrieval import ocr_image

        if self._mode == "vl":
            reply = await _vl_page(self._ctx, self._model, self._vl_model, png)
            self._markdown.append(reply.get("text") or "")
            return []
        reply = await ocr_image(self._ctx["shim"], self._model, png,
                                mode=self._mode)
        lines: list[kb_parse.OcrLine] = []
        for line in reply.get("lines") or []:
            box = line.get("box")
            if not box:
                continue
            lines.append(kb_parse.OcrLine(
                text=line.get("text") or "",
                box=[[float(p[0]), float(p[1])] for p in box],
            ))
        if self._mode == "layout":
            self._markdown.append(reply.get("text") or "")
        return lines

    def markdown_for(self, position: int) -> str:
        """The Markdown of the ``position``-th page this bridge OCR'd (1-based)."""
        index = (position or 1) - 1
        if 0 <= index < len(self._markdown):
            return self._markdown[index]
        return ""


async def _vl_page(ctx: dict, ocr_model, vl_model, png: bytes) -> dict:
    """One scanned page through both models, recorded as this tool's inference.

    The record is built here rather than inside ``run_vl_page`` for the same
    reason ``ocr_image`` builds its own: the caller owns the attribution, and
    the shared helper stays free of the platform's logging shapes.

    ``vl_model`` is a :class:`Resolved`, so a client that went away between the
    resolution and this call is reported as the reason rather than as a
    ``NoneType`` error.
    """
    import uuid as _uuid

    from ..apps.kb.retrieval import RECORD_ACTOR, RECORD_SOURCE
    from ..core.inference_log import STATUS_ERROR, STATUS_OK, build_context
    from ..engine.ocr_vl_page import run_vl_page

    request = ctx["shim"]
    req_id = f"mcpvl-{_uuid.uuid4().hex}"
    log = build_context(
        request.app.state.inference_log,
        req_id=req_id,
        source=RECORD_SOURCE,
        model=ocr_model.model_id,
        actor=RECORD_ACTOR,
        params={"return_boxes": True, "mode": "vl",
                "vl_model": vl_model.model_id},
        messages=[{"role": "user", "content": json.dumps(
            {"image": {"bytes": len(png)}}, ensure_ascii=False)}],
    )
    try:
        reply = await run_vl_page(ocr_model.client, vl_model.client,
                                  base64.b64encode(png).decode("ascii"),
                                  req_id)
    except WorkerError as exc:
        if log is not None:
            log.finish(status=STATUS_ERROR, error=exc)
        raise RuntimeError(str(exc)) from None
    if log is not None:
        log.params = {**(log.params or {}),
                      "width": int(reply.get("width") or 0),
                      "height": int(reply.get("height") or 0),
                      "lines": 0, "blocks": len(reply.get("blocks") or []),
                      "vl_ms": reply.get("vl_ms"),
                      "vl_tokens": reply.get("vl_tokens")}
        log.finish(status=STATUS_OK, output_text=reply.get("text") or "",
                   prompt_tokens=0, completion_tokens=0)
    return reply


async def _ocr_lines(ctx: dict, ocr_model, png: bytes, mode: str = "lines"):
    """One page through the worker, recorded as this tool's inference."""
    from ..apps.kb.retrieval import ocr_image

    reply = await ocr_image(ctx["shim"], ocr_model, png, mode=mode)
    out: list[kb_parse.OcrLine] = []
    for line in reply.get("lines") or []:
        box = line.get("box")
        if not box:
            continue
        out.append(kb_parse.OcrLine(
            text=line.get("text") or "",
            box=[[float(p[0]), float(p[1])] for p in box],
        ))
    return out


async def _read_path(request, raw: str, *,
                     limit: int | None = None) -> LocalFile:
    """One allowlisted file, opened, checked and read in a worker thread.

    ``read_local_file`` does the whole job on one descriptor (see its docstring);
    this is the async wrapper that keeps that off the event loop and turns a
    refusal into the ``isError`` sentence the model reads.
    """
    try:
        return await asyncio.to_thread(
            read_local_file, raw, _data_root(request), limit=limit)
    except PathRefused as exc:
        raise ToolError(str(exc)) from None


async def _read_validated(request, raw: str, *,
                          limit: int | None = None) -> tuple[LocalFile, str, int]:
    """``(file, kind, pdf_page_count)``, checked exactly as an upload is.

    ``validate_upload`` is the same gate ``kb_add_document`` and the console's
    upload route use, so ``ocr_read`` cannot be the one path into the parsers
    that skips the type, size, PDF-page and image-pixel checks. It opens the PDF
    page tree (cheap: no page is rendered), which is also where the page count
    comes from, so the caller does not have to open the file a second time.
    """

    def work() -> tuple[LocalFile, str, int]:
        read = read_local_file(raw, _data_root(request), limit=limit)
        kind = kb_parse.detect_kind(read.name, read.data)
        kb_parse.validate_upload(kind, read.data)
        pages = _pdf_page_count(read.data) if kind == "pdf" else 0
        return read, kind, pages

    try:
        return await asyncio.to_thread(work)
    except PathRefused as exc:
        raise ToolError(str(exc)) from None
    except kb_parse.ParseError as exc:
        raise ToolError(str(exc)) from None


def _bounded_int(value, default: int, low: int, high: int, name: str) -> int:
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ToolError(f"{name} 必须是整数（收到 {value!r}）") from None
    if number < low:
        raise ToolError(f"{name} 不能小于 {low}")
    if number > high:
        raise ToolError(f"{name} 不能大于 {high}（收到 {number}）")
    return number


# -- the registry the protocol layer serves ----------------------------------
#: ``(handler, description, JSON schema)``. The order is the order
#: ``tools/list`` returns, which is the order an agent reads: look, then search,
#: then widen, then write.
TOOLS: dict[str, dict] = {}


def _tool(name: str, description: str, schema: dict):
    def register(fn):
        TOOLS[name] = {"name": name, "description": description,
                       "inputSchema": schema, "handler": fn}
        return fn

    return register


_EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}
_KB_ARG = {"type": "string",
           "description": "知识库的 id 或名称。只有一个知识库时可以省略。"}


# -- transcription -----------------------------------------------------------
#: The audio container family this tool accepts. Same list the upload route and
#: the worker's own decoder understand; an unknown suffix is refused before the
#: bytes reach a worker that would spend a decode on them.
AUDIO_SUFFIXES = (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus",
                  ".webm", ".mp4", ".amr", ".wma")


async def transcribe_audio(request, args: dict, ctx: dict) -> tuple[str, dict]:
    """A local audio file transcribed into text, with timestamps per segment.

    Limits are the transcription endpoint's own, not new numbers: ≤ 50 MiB (the
    same upload cap ``/v1/audio/transcriptions`` enforces) and ≤ 30 minutes of
    audio (the worker refuses longer before its first segment, so this check is
    a fast path to the same answer, not a second policy).

    ``iter_transcribe`` -- the segmented path ``#76`` introduced -- is what runs,
    with its frames collected rather than streamed: MCP has no server push here,
    and a tool call is a request/response. Using the streaming generator anyway
    (rather than ``transcribe``) means the text and the segments come from the
    one producer the streaming endpoint uses, so the two surfaces cannot drift.
    """
    path_arg = str(args.get("path") or "").strip()
    if not path_arg:
        raise ToolError("path 不能为空")
    language = args.get("language")
    if language is not None:
        language = str(language).strip() or None
    prompt = args.get("prompt") or ""
    if not isinstance(prompt, str):
        prompt = str(prompt)

    with HEAVY.slot("语音转写"):
        read = await _read_path(request, path_arg, limit=audio_upload.MAX_UPLOAD_BYTES)
        suffix = Path(read.name).suffix.lower()
        if suffix and suffix not in AUDIO_SUFFIXES:
            raise ToolError(
                f"{read.name} 不是支持的音频类型（支持 "
                + "、".join(s.lstrip(".") for s in AUDIO_SUFFIXES) + "）")
        # Validated here as well as in the worker: the worker's refusal would
        # arrive as a failed transcription, but a language this model does not
        # have should not first cost an audio decode.
        if language is not None:
            try:
                normalize_language(language)
            except ValueError as exc:
                raise ToolError(str(exc)) from None

        model = await _resolve_asr(request)
        info = model.info
        req_id = f"mcp-{uuid.uuid4().hex}"
        record = _asr_record(request, ctx, info, read, language, prompt)
        frames = model.client.stream_transcribe(
            req_id,
            base64.b64encode(read.data).decode("ascii"),
            filename=read.name,
            language=language,
            prompt=prompt,
        )
        try:
            collected = await _collect_asr(frames)
        except WorkerError as exc:
            _finish_asr(record, error=exc)
            raise ToolError(f"转写失败：{exc}") from None
        except asyncio.CancelledError:
            # Nothing was written for this request; tell the worker to stop so it
            # does not keep a queue slot for an answer nobody is waiting for.
            with contextlib.suppress(Exception):
                await asyncio.shield(model.client.cancel(req_id))
            _finish_asr(record, error=RuntimeError("客户端取消"))
            raise
        except Exception as exc:  # noqa: BLE001 - reported, not raised further
            _finish_asr(record, error=exc)
            raise ToolError(f"转写失败：{exc}") from None

    _finish_asr(record, text=collected["text"], duration=collected["duration"],
                language=collected["language"], segments=collected["segments"],
                prompt_tokens=collected["prompt_tokens"],
                completion_tokens=collected["completion_tokens"])
    return _format_transcript(read, info.model_id, collected)


async def _collect_asr(frames) -> dict:
    """Drain ``iter_transcribe``'s frames into one result.

    The frame shapes are the worker protocol's (``meta`` / ``segment`` / ``done``,
    or an ``error`` that ``stream_transcribe`` has already raised by the time it
    reaches here). ``done`` carries the joined text, which is the same string the
    non-streaming endpoint returns -- the joiner lives in the worker, so this is
    not a second implementation of it.

    ``language`` is passed through :func:`_reported_language` first: the worker
    reads the model's own ``language <Name><asr_text>`` preamble, and on audio
    with no speech the model answers the literal word ``None``, which would
    otherwise reach a chat transcript as the language ``"None"``.
    """
    out = {"text": "", "language": None, "duration": 0.0, "segments": [],
           "prompt_tokens": 0, "completion_tokens": 0}
    async for frame in frames:
        op = frame.get("op")
        if op == "meta":
            out["duration"] = float(frame.get("duration") or 0.0)
        elif op == "segment":
            out["segments"].append({
                "id": int(frame.get("id") or 0),
                "start": round(float(frame.get("start") or 0.0), 3),
                "end": round(float(frame.get("end") or 0.0), 3),
                "text": frame.get("text") or "",
            })
        elif op == "done":
            out["text"] = frame.get("text") or ""
            out["language"] = _reported_language(frame.get("language"))
            out["duration"] = float(frame.get("duration") or out["duration"])
            out["prompt_tokens"] = int(frame.get("prompt_tokens") or 0)
            out["completion_tokens"] = int(frame.get("completion_tokens") or 0)
    return out


#: What the model says when it decided the audio holds no speech. Read from its
#: preamble, so it arrives as a *string*: ``"None"``, ``"none"``, ``"null"``.
_NO_LANGUAGE = frozenset({"none", "null", "unknown", "n/a", ""})


def _reported_language(value):
    """The language to report, or None.

    A model that heard no speech answers ``language None`` and the worker, which
    reads that preamble verbatim, hands the string back. Reporting the language
    as ``"None"`` is worse than reporting nothing: a model reading the reply would
    treat it as a detected language name.
    """
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in _NO_LANGUAGE else text


def _format_transcript(read: LocalFile, model_id: str, collected: dict):
    """The model's text: the whole transcript first, then the timed segments.

    Whole text first because that is what a model quotes and reasons over; the
    segment table after it because that is what lets a reader go back to the
    recording, and what a citation needs. Times are ``[mm:ss–mm:ss]`` -- rounded
    to the second, since a transcript's own segment boundaries are whole seconds
    anyway and a tenth of one is noise in a chat reply.
    """
    text = (collected["text"] or "").strip()
    segments = collected["segments"]
    minutes = collected["duration"] / 60.0
    language = collected["language"] or "自动识别"
    header = (f"{read.name}（音频，{language}，{_clock(collected['duration'])}，"
              f"{len(segments)} 段，模型 {model_id}）：")
    if not text:
        body = "（没有识别出语音内容；音频可能是静音或只有噪声。）"
    else:
        body = text
    lines = [header, "", body]
    if segments:
        lines.append("")
        lines.append("分段：")
        for segment in segments:
            lines.append(f"[{_clock(segment['start'])}–{_clock(segment['end'])}] "
                         f"{segment['text']}")
    if minutes >= 25:
        # Close enough to the 30-minute ceiling that the next file of this length
        # may well be refused; saying so now beats a failure the model cannot
        # explain later.
        lines.append("")
        lines.append("（接近单次 30 分钟的转写上限，更长的音频请先切分。）")
    return "\n".join(lines), {
        "path": str(read.path),
        "kind": "audio",
        "model": model_id,
        "duration": round(collected["duration"], 3),
        "language": collected["language"],
        "text": text,
        "segments": segments,
        "usage": {
            "prompt_tokens": collected["prompt_tokens"],
            "completion_tokens": collected["completion_tokens"],
            "total_tokens": (collected["prompt_tokens"]
                             + collected["completion_tokens"]),
        },
    }


def _clock(seconds: float) -> str:
    """``mm:ss`` -- minutes are not capped at 60, an hour of audio needs 60:00."""
    total = max(0, int(round(float(seconds or 0.0))))
    return f"{total // 60:02d}:{total % 60:02d}"


async def _resolve_asr(request):
    """The ASR model to use, or a tool error naming what to load.

    On demand: transcription is the whole point of the call, so an unloaded ASR
    model is loaded rather than refused. Concurrent transcriptions share the one
    load (``ModelManager.load`` joins an in-flight load), which matters here
    because an agent may fan out several files at once.

    Which model: loaded ones prefer the most recently loaded (the operator's last
    explicit choice, so loading 1.7B last asks for 1.7B); choosing among
    *unloaded* ones prefers ``qwen3-asr-0.6b``, which is faster and smaller, and
    the design asks for that tie-break explicitly.
    """
    model = await kb_models.resolve_or_load(request, "asr")
    if model:
        return model
    reason = model.reason or "未加载语音识别模型"
    raise ToolError(
        f"{reason}。请先在控制台的模型页加载 qwen3-asr-0.6b 或 qwen3-asr-1.7b，再重试。")


def _asr_record(request, ctx: dict, info, read: LocalFile, language, prompt):
    """The inference record for this call, or None when logging is off.

    Built here rather than inside ``app/apps/kb`` because transcription is not a
    knowledge-base stage: this surface calls the worker directly, so it writes
    the row itself -- with the MCP identity (``source`` ``/mcp``, the caller's
    key as actor), exactly as the re-attributed knowledge-base rows are.
    """
    actor = ctx.get("actor") or {}
    return build_context(
        getattr(request.app.state, "inference_log", None),
        req_id=f"mcp-{uuid.uuid4().hex}",
        source=SOURCE,
        model=info.model_id,
        actor=actor,
        params={"language": language, "prompt": bool(prompt)},
        messages=[{"role": "user", "content": json.dumps({
            "filename": read.name,
            "bytes": len(read.data),
            "language": language,
            "prompt": prompt,
        }, ensure_ascii=False)}],
    )


def _finish_asr(record, *, text: str = "", duration: float = 0.0,
                language=None, segments=None, prompt_tokens: int = 0,
                completion_tokens: int = 0, error: BaseException | None = None) -> None:
    """Write the one row, however this call ended."""
    if record is None:
        return
    if error is not None:
        record.finish(status=STATUS_ERROR, error=error)
        return
    record.params = {**(record.params or {}),
                     "duration": round(duration, 3),
                     "language_detected": language,
                     "segments": len(segments or [])}
    record.finish(status=STATUS_OK, output_text=text,
                  prompt_tokens=prompt_tokens or None,
                  completion_tokens=completion_tokens or None)




_tool("kb_list",
      "列出全部知识库：id、名称、文档数、片段数、建索引用的 embedding 模型、是否需要重建索引。"
      "不确定该查哪个知识库，或想确认某个库是否可用时先调用它。",
      _EMPTY)(kb_list)

_tool("kb_create",
      "新建一个空知识库。建好后用 kb_add_document 添加文档；建库完成前该库只能靠文件名检索。",
      {"type": "object",
       "properties": {"name": {"type": "string", "description": "知识库名称，1-100 个字符。"}},
       "required": ["name"], "additionalProperties": False})(kb_create)

_tool("kb_search",
      "在知识库中检索与 query 相关的片段，返回带出处（文档名、页码、相关度）的原文。"
      "需要查资料、回答与文档有关的问题时先调用它，不要凭记忆回答。"
      "结果会说明哪些检索步骤执行了、哪些被跳过（例如没有加载 embedding 模型时只有 BM25）。",
      {"type": "object",
       "properties": {
           "query": {"type": "string", "description": "检索词或问题。"},
           "kb": _KB_ARG,
           "top_k": {"type": "integer", "minimum": 1, "maximum": MAX_TOP_K,
                     "default": DEFAULT_TOP_K,
                     "description": f"返回几条，默认 {DEFAULT_TOP_K}，最多 {MAX_TOP_K}。"},
       },
       "required": ["query"], "additionalProperties": False})(kb_search)

_tool("kb_read",
      f"读取某个片段以及它前后相邻的片段，用来扩大上下文。"
      f"chunk_id 来自 kb_search 的结果；neighbors 默认 {DEFAULT_NEIGHBORS}，最多 {MAX_NEIGHBORS}。",
      {"type": "object",
       "properties": {
           "chunk_id": {"type": "string", "description": "kb_search 返回的 chunk_id。"},
           "neighbors": {"type": "integer", "minimum": 0, "maximum": MAX_NEIGHBORS,
                         "default": DEFAULT_NEIGHBORS,
                         "description": "前后各取几个片段。"},
       },
       "required": ["chunk_id"], "additionalProperties": False})(kb_read)

_tool("kb_list_documents",
      "列出知识库里的文档及其建库状态（排队中/解析中/OCR/向量化/就绪/失败）。"
      "想知道库里有哪些文件、或确认某篇文档是否建好时用它。",
      {"type": "object",
       "properties": {"kb": _KB_ARG},
       "required": ["kb"], "additionalProperties": False})(kb_list_documents)

_tool("kb_add_document",
      "往知识库添加一篇文档，立即返回 doc id 和排队状态，不等建库完成。"
      "两种来源二选一：path 指向设备上的本地文件（txt/md/pdf/png/jpg 等），"
      "或 text + name 直接写入一段文字。建库进度用 kb_document_status 查询。",
      {"type": "object",
       "properties": {
           "kb": _KB_ARG,
           "path": {"type": "string",
                    "description": "设备本地文件的绝对路径，须在允许的目录内。"},
           "text": {"type": "string", "description": "直接写入的文字内容。"},
           "name": {"type": "string", "description": "用 text 时的文档名，例如 notes.md。"},
       },
       "required": ["kb"], "additionalProperties": False})(kb_add_document)

_tool("kb_document_status",
      "查询一篇文档的建库状态、进度和错误信息。kb_add_document 之后用它确认什么时候可以检索。",
      {"type": "object",
       "properties": {
           "kb": _KB_ARG,
           "doc_id": {"type": "string", "description": "kb_add_document 返回的 doc id。"},
       },
       "required": ["kb", "doc_id"], "additionalProperties": False})(kb_document_status)

_tool("ocr_read",
      "识别图片或 PDF 里的文字，不写入任何知识库。"
      "mode=\"lines\"（默认）按阅读顺序返回一行行文字，适合截图、裁剪图、单列表单；"
      "mode=\"layout\" 先用版面模型把整页分成标题/段落/表格/图片等区域，"
      "再按阅读顺序输出整页 Markdown（含标题层级），适合整页文档、双栏排版、"
      "需要保留标题与段落结构时。表格区域只输出文字，不还原表格结构。"
      "mode=\"vl\" 同样是整页分区 + Markdown，但每个区域交给 PaddleOCR-VL 识别："
      "表格输出 HTML（含合并单元格），公式输出 LaTeX，文字更准；"
      "代价是慢很多（每页一个区域一次 VL 推理，通常几十秒），"
      "并且要求 PaddleOCR-VL 模型已加载。含表格、公式、扫描质量差的文档用它，"
      "普通文字页用 layout 就够。"
      "PDF 逐页返回：有文字层的页在三种模式下都直接取文字层，只有扫描页走 OCR；"
      "每页都会标明来源（文字层 / OCR）。"
      f"pages 用于指定 PDF 页范围（如 \"1-5\"），默认前 {DEFAULT_PDF_PAGES} 页，"
      f"单次最多 {MAX_PDF_PAGES_PER_CALL} 页。"
      "处理用户提供的截图、扫描件、PDF 里的大段文字时优先调用这个工具，而不是猜测内容。",
      {"type": "object",
       "properties": {
           "path": {"type": "string",
                    "description": "设备本地图片或 PDF 的绝对路径，须在允许的目录内。"},
           "mode": {"type": "string", "enum": ["lines", "layout", "vl"],
                    "description": "lines（默认）= 逐行文字；"
                                   "layout = 版面模式，分区后输出整页 Markdown，"
                                   "适合整页文档与双栏页，表格只给文字；"
                                   "vl = 版面 + PaddleOCR-VL 逐区域识别，"
                                   "表格输出 HTML（含合并单元格）、公式输出 LaTeX，"
                                   "比 layout 慢、更准，需要 PaddleOCR-VL 已加载。"},
           "pages": {"type": "string",
                     "description": "PDF 页范围，例如 \"1-5\"；默认前 "
                                    f"{DEFAULT_PDF_PAGES} 页。"},
       },
       "required": ["path"], "additionalProperties": False})(ocr_read)

_tool("transcribe_audio",
      "把设备上的音频文件转写成文字，返回全文和带时间戳的分段，不写入任何知识库。"
      "用户给的录音、会议音频、语音消息里有关键信息时优先调用它，而不是让用户自己复述。"
      "单次最长 30 分钟、文件 ≤ 50 MB；接近上限时请先切分。",
      {"type": "object",
       "properties": {
           "path": {"type": "string",
                    "description": "设备本地音频文件的绝对路径，须在允许的目录内。"},
           "language": {"type": "string",
                        "description": "音频语言（如 Chinese、English）；省略则自动识别。"},
           "prompt": {"type": "string",
                      "description": "可选提示，用于提示专有名词或上下文。"},
       },
       "required": ["path"], "additionalProperties": False})(transcribe_audio)



def tool_specs() -> list[dict]:
    """The ``tools/list`` payload."""
    return [{"name": t["name"], "description": t["description"],
             "inputSchema": t["inputSchema"]} for t in TOOLS.values()]


async def call_tool(request, name: str, arguments: dict, *, key_name: str = "") -> dict:
    """Run one tool and shape its answer for the protocol layer.

    Success and tool-level failure both come back as a normal result; only an
    unknown tool name is a protocol error, and that is raised as
    :class:`ToolError`'s opposite -- see ``server.py``.
    """
    entry = TOOLS.get(name)
    if entry is None:
        raise KeyError(name)
    actor = _actor(request, key_name)
    ctx = {"shim": _ShimRequest(request, actor), "actor": actor}
    try:
        text, structured = await entry["handler"](request, arguments or {}, ctx)
    except ToolError as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    except (KbError, kb_parse.ParseError) as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    except Exception:  # noqa: BLE001 - a tool crash must not kill the service
        # The traceback belongs in the log. The model gets a sentence: an
        # exception class plus its message is this box's internals, and it is
        # exactly what a tool result must not carry back into a chat transcript.
        logger.exception("mcp tool %s failed", name)
        return {"content": [{"type": "text",
                             "text": f"工具 {name} 执行失败，详情见服务日志"}],
                "isError": True}
    result = {"content": [{"type": "text", "text": text}], "isError": False}
    if structured:
        result["structuredContent"] = structured
    return result
