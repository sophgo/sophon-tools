"""The hybrid retrieval pipeline: BM25 + vectors -> RRF -> rerank.

Every stage reports what it did, including ``skipped`` with a Chinese reason, and
how long it took. That is the point of the app -- an operator is looking at this
to see what each model contributes -- so a stage that did not run says why
rather than quietly vanishing from the response.

The degradation rules, straight from the design:

===============  ==============================================  ===============
model loaded     effect                                          when missing
===============  ==============================================  ===============
embedding        vector stage; also the *only* way a library    vector stage
                 built with a different model can be searched    ``skipped``
rerank           reranks the fused candidates                    order stays RRF
chat             streaming answer with citations                ``/answer`` 409
===============  ==============================================  ===============
BM25 is always available: it needs no model at all.

RRF is what makes the two rankings combinable without calibrating scores that
have no common scale -- BM25 is unbounded and cosine similarity is in [-1, 1], so
any linear combination would be a tuning exercise, while ``1/(60+rank)`` only
needs the ranks.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, field

from ...core.client import WorkerError
from ...core.inference_log import (
    STATUS_ERROR,
    STATUS_OK,
    build_context,
)
from . import models as model_resolve
from .bm25 import Bm25Index, tokenize

logger = logging.getLogger(__name__)

#: RRF's rank constant. 60 is the value from the original paper and the one
#: every hybrid-search implementation uses; it decides how quickly the weight of
#: a rank falls off.
RRF_K = 60

#: The Qwen3-Embedding retrieval instruction, character for character. Documents
#: are encoded without it (see docs/aux-models.md: the reference similarity
#: numbers move outside tolerance if a single word of this changes).
QUERY_INSTRUCTION = (
    "Instruct: Given a web search query, retrieve relevant passages "
    "that answer the query\nQuery: "
)

#: How long one embed round trip may take. A batch on the board is one forward
#: per text, so this bounds "the NPU is wedged", not normal work (the same
#: figure app/core/client.py uses).
EMBED_TIMEOUT_S = 300.0

#: Chunks per embed request during a build. Small on purpose: the worker serves
#: one request at a time, start to finish, so a batch is a block of time a
#: search typed meanwhile has to wait behind.
#:
#: 4 was chosen against the old static **seq8192** bmodel, which took ~2.8 s per
#: text: a 64-chunk batch held the engine for ~3 minutes, four kept a search's
#: wait to ~11 s. Since MYS-2696 the shipped bmodel is seq2048 and a text costs
#: ~0.29 s, so a batch of 4 is ~1.2 s and even 64 would be ~19 s.
#:
#: Kept at 4 anyway, deliberately. The reason for the small batch was never the
#: batch's *total* time — it is that the build must not monopolise the NPU for
#: long enough to starve an interactive search, and the *ratio* is unchanged:
#: one 64-chunk batch still costs 64 forwards whatever the model. What the
#: seq2048 build buys is that each of those forwards is 9.7x cheaper, so a
#: search waits ~1.2 s instead of ~11 s, and the whole build is 9.7x faster.
#: Raising the batch would spend that gain on holding the engine longer, and
#: would push a 4-chunk batch's request count down by nothing that matters
#: (the record-per-batch cost is host-side and small).
EMBED_BATCH = 4

#: How many candidates a search may ask for. The rerank endpoint refuses more
#: than 256 pairs; 100 is the demo's own ceiling, chosen to keep one search well
#: under a minute on the board (the rerank pass is ~6.5 s for 20 pairs).
MAX_CANDIDATES = 100

#: What this app's own inference records say about who called. The console's
#: cookie authenticated the request, and ``kb`` says which console feature spent
#: the NPU time -- the same convention ``/api/test/*`` uses for ``admin``.
RECORD_SOURCE = "/api/apps/kb"
RECORD_ACTOR = {"actor_type": "admin", "actor_id": None, "actor_name": "kb"}

#: The caps the ``/v1`` endpoints enforce, imported rather than restated: a
#: second copy here is a number that can drift from the one the endpoint refuses
#: on, and then a build would fail at the worker instead of at the limit.
#: ``openai_api`` is imported lazily so this module stays usable without FastAPI
#: (the pipeline's arithmetic tests drive it directly).
def _caps() -> tuple[int, int]:
    from ...api.openai_api import MAX_EMBED_INPUTS, MAX_RERANK_DOCUMENTS

    return MAX_EMBED_INPUTS, MAX_RERANK_DOCUMENTS


def _log_store(request):
    """The inference log, or ``None``.

    ``build_context`` already treats a missing store as "logging is off", but
    reading the attribute unguarded would turn "this app was driven without one"
    -- which is how the pipeline's own tests exercise it -- into an
    ``AttributeError`` in the middle of a search.
    """
    return getattr(getattr(request, "app", None), "state", None) and getattr(
        request.app.state, "inference_log", None)


class InputRefused(RuntimeError):
    """The embedding worker refused an input as invalid (``kind="invalid_request"``),
    typically because it encodes to more tokens than the model's SEQLEN.

    A ``RuntimeError`` like every other failure of :func:`embed_passages`, so
    existing callers are unaffected; the ingest path catches it specifically to
    split the offending chunk (``Ingestor._embed_fitted``).
    """


async def embed_passages(request, resolved, texts: list[str]) -> list[list[float]]:
    """Encode ``texts``, recorded as this app's inference.

    Why not call ``openai_api.embeddings`` (what ``/api/test/*`` proxies to)?
    Because these calls come from a *background job*, not from an HTTP request:
    that handler takes its ``source`` from ``request.url.path`` and its actor
    from the API key, so a build would be filed under whichever console page
    happened to queue it and as ``admin`` rather than ``kb``. The card asks for
    the record to name the console and ``kb``, so the context is built here with
    the same :func:`build_context` the handler uses, and the limits are the
    handler's own constants (``_caps``). Admission is ``ModelManager``'s, via the
    resolver, which is the same gate ``_resolve_model`` applies.
    """
    max_inputs, _ = _caps()
    if len(texts) > max_inputs:
        raise RuntimeError(f"一次最多 {max_inputs} 条输入，收到 {len(texts)} 条")

    req_id = f"kbe-{uuid.uuid4().hex}"
    ctx = build_context(
        _log_store(request),
        req_id=req_id,
        source=RECORD_SOURCE,
        model=resolved.model_id,
        actor=RECORD_ACTOR,
        params={"dimensions": None, "encoding_format": "float"},
        messages=[{"role": "user", "content": text} for text in texts],
    )
    try:
        reply = await resolved.client.embed(req_id, texts)
    except WorkerError as exc:
        if ctx is not None:
            ctx.finish(status=STATUS_ERROR, error=exc)
        if exc.kind == "invalid_request":
            raise InputRefused(_worker_message(exc)) from None
        raise RuntimeError(_worker_message(exc)) from None
    if ctx is not None:
        ctx.finish(status=STATUS_OK,
                   output_text=f"{len(reply.get('vectors') or [])} vectors",
                   prompt_tokens=sum(int(c) for c in reply.get("tokens") or []),
                   completion_tokens=0)
    vectors = reply.get("vectors") or []
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"embedding 返回 {len(vectors)} 个向量，请求了 {len(texts)} 条")
    return [[float(x) for x in v] for v in vectors]


async def rerank_documents(request, resolved, query: str,
                           documents: list[str]) -> list[float]:
    """Score every ``(query, document)`` pair, in the caller's order.

    Recorded and capped exactly like :func:`embed_passages` -- in particular the
    ``MAX_RERANK_DOCUMENTS`` ceiling the ``/v1/rerank`` endpoint refuses over,
    which this app used to bypass by calling the client directly. Scores are
    ``sigmoid(logit)``, the same presentation ``/v1/rerank`` returns, so a number
    quoted from a search result matches one quoted from the rerank test page.
    """
    _, max_documents = _caps()
    if len(documents) > max_documents:
        raise RuntimeError(
            f"一次最多 {max_documents} 条文档，收到 {len(documents)} 条")

    req_id = f"kbr-{uuid.uuid4().hex}"
    ctx = build_context(
        _log_store(request),
        req_id=req_id,
        source=RECORD_SOURCE,
        model=resolved.model_id,
        actor=RECORD_ACTOR,
        params={"top_n": None, "return_documents": False},
        messages=[{"role": "user", "content": query}],
    )
    try:
        reply = await resolved.client.rerank(req_id, query, documents)
    except WorkerError as exc:
        if ctx is not None:
            ctx.finish(status=STATUS_ERROR, error=exc)
        raise RuntimeError(_worker_message(exc)) from None
    logits = reply.get("logits") or []
    if len(logits) != len(documents):
        if ctx is not None:
            ctx.finish(status=STATUS_ERROR, error_type="ProtocolError",
                       error_message=f"worker 返回 {len(logits)} 个分数，请求了 {len(documents)} 条")
        raise RuntimeError(
            f"rerank 返回 {len(logits)} 个分数，请求了 {len(documents)} 条")
    scores = [_sigmoid(float(x)) for x in logits]
    if ctx is not None:
        ctx.finish(status=STATUS_OK,
                   output_text=json.dumps([round(s, 6) for s in scores]),
                   prompt_tokens=sum(int(c) for c in reply.get("tokens") or []),
                   completion_tokens=0)
    return scores


async def ocr_image(request, resolved, png: bytes, mode: str = "lines") -> dict:
    """OCR one rendered page, recorded as this app's inference.

    Unlike the other two this runs through a coroutine bridge from a worker
    thread (``ingest._ocr_lines_sync``), but it is scheduled back onto the event
    loop, so building the context here is safe.

    The image's bytes are described, never stored -- the audit log keeps
    dimensions and a byte count, exactly as ``/v1/ocr`` does, because a page
    image is the one thing an operator would not want in a log.

    ``mode`` is passed through unvalidated: the worker owns what the two modes
    mean, and a second copy of the rule here could drift from it.
    """
    req_id = f"kbo-{uuid.uuid4().hex}"
    ctx = build_context(
        _log_store(request),
        req_id=req_id,
        source=RECORD_SOURCE,
        model=resolved.model_id,
        actor=RECORD_ACTOR,
        params={"return_boxes": True, "mode": mode},
        messages=[{"role": "user", "content": json.dumps(
            {"image": {"bytes": len(png)}}, ensure_ascii=False)}],
    )
    try:
        reply = await resolved.client.ocr(
            req_id, base64.b64encode(png).decode("ascii"), mode=mode)
    except WorkerError as exc:
        if ctx is not None:
            ctx.finish(status=STATUS_ERROR, error=exc)
        raise RuntimeError(_worker_message(exc)) from None
    if ctx is not None:
        ctx.params = {**(ctx.params or {}),
                      "width": int(reply.get("width") or 0),
                      "height": int(reply.get("height") or 0),
                      "lines": len(reply.get("lines") or []),
                      **({"blocks": len(reply.get("blocks") or [])}
                         if reply.get("mode") == "layout" else {})}
        ctx.finish(status=STATUS_OK, output_text=reply.get("text") or "",
                   prompt_tokens=0, completion_tokens=0)
    return reply


def _worker_message(exc: "WorkerError") -> str:
    """The operator-facing wording for a worker refusal.

    ``/v1``'s own mapping (``_worker_error_to_http``) is HTTP-shaped; these calls
    have no HTTP response to shape, they have a ``skipped`` stage's reason, so
    only the message is reused and the status code is dropped.
    """
    return str(exc)


@dataclass
class Stage:
    """One pipeline stage's outcome, in the shape the API returns."""

    name: str
    status: str = "ok"
    reason: str | None = None
    ms: float = 0.0
    #: ``[{chunk_id, rank, score}]`` in rank order; rank is 1-based.
    hits: list[dict] = field(default_factory=list)

    def skip(self, reason: str, ms: float = 0.0) -> "Stage":
        self.status = "skipped"
        self.reason = reason
        self.ms = ms
        self.hits = []
        return self

    def public(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "ms": round(self.ms, 2),
            "hits": self.hits,
        }


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal rank fusion of several ranked id lists.

    ``score = sum over rankings of 1/(k + rank)``, rank 1-based. Ties are broken
    by the order the ids were first seen, which for our callers means BM25's
    order -- a deterministic and explainable tiebreak, where "whatever dict
    insertion order happened to be" would not be.
    """
    scores: dict[str, float] = {}
    order: dict[str, int] = {}
    for ranking in rankings:
        for position, chunk_id in enumerate(ranking):
            rank = position + 1
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
            order.setdefault(chunk_id, len(order))
    return sorted(scores.items(), key=lambda kv: (-kv[1], order[kv[0]]))


def cosine_ranking(query_vec, matrix, chunk_ids: list[str], limit: int) -> list[tuple[str, float]]:
    """Top ``limit`` chunks by cosine similarity.

    The stored vectors are unit length, so the dot product *is* the cosine; the
    query vector is normalised here rather than assumed. A zero query vector
    cannot be ranked against anything and produces an empty ranking rather than
    a list of zeros (which would be an arbitrary order dressed up as a score).
    """
    if matrix is None or not len(chunk_ids):
        return []
    norm = math.sqrt(sum(float(x) * float(x) for x in query_vec))
    if norm <= 0.0:
        return []
    inv = 1.0 / norm
    query = [float(x) * inv for x in query_vec]
    scores = matrix @ _as_array(query)
    # Descending, and **stable**: equal scores keep chunk order, so two identical
    # requests return the same list. Negating and asking for a stable sort is the
    # only way to get both -- ``argsort()[::-1]`` reverses ties, which would make
    # the order of equally-similar chunks depend on which came last in the file.
    order = (-_as_array(scores)).argsort(kind="stable")[:limit]
    return [(chunk_ids[int(i)], float(scores[int(i)])) for i in order]


def _as_array(values):
    import numpy as np

    return np.asarray(values, dtype="float32")


@dataclass
class SearchRequest:
    query: str
    top_k: int = 5
    candidates: int = 20
    use_bm25: bool = True
    use_vector: bool = True
    use_rerank: bool = True


@dataclass
class SearchResult:
    query: str
    models: dict
    stages: dict
    results: list[dict]
    total_ms: float

    def public(self) -> dict:
        return {
            "query": self.query,
            "models": self.models,
            "stages": {name: stage.public() for name, stage in self.stages.items()},
            "results": self.results,
            "timings": {"total_ms": round(self.total_ms, 2)},
        }


async def _embed_one(request, resolved, text: str) -> list[float]:
    """One query string through the embedding model, recorded like a build's."""
    vectors = await embed_passages(request, resolved, [text])
    if not vectors:
        raise RuntimeError("embedding worker 没有返回向量")
    return vectors[0]


def _sigmoid(x: float) -> float:
    """The API's presentation of a rerank logit, same as /v1/rerank's."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    exp = math.exp(x)
    return exp / (1.0 + exp)


async def search(request, *, kb, chunks: list[dict], bm25: Bm25Index,
                 vectors, req: SearchRequest) -> SearchResult:
    """Run the pipeline and return every stage's numbers.

    ``vectors`` is the library's ``vectors.npy`` array (or ``None``). ``chunks``
    are the chunk records in the same order as the array's rows.
    """
    started = time.monotonic()
    stages: dict[str, Stage] = {}
    by_id = {chunk["id"]: chunk for chunk in chunks}

    # -- BM25 ------------------------------------------------------------
    bm25_stage = Stage("bm25")
    bm25_ranking: list[tuple[str, float]] = []
    if not req.use_bm25:
        bm25_stage.skip("请求中关闭了 BM25")
    elif not tokenize(req.query):
        bm25_stage.skip("查询没有可检索的词（只有标点或空白）")
    else:
        t0 = time.monotonic()
        try:
            bm25_ranking = bm25.search(req.query, req.candidates)
            bm25_stage.hits = [
                {"chunk_id": cid, "rank": i + 1, "score": round(score, 6)}
                for i, (cid, score) in enumerate(bm25_ranking)
            ]
            if not bm25_ranking:
                bm25_stage.skip("BM25 没有命中任何切片")
        except Exception as exc:  # pragma: no cover - BM25 is pure python
            logger.exception("bm25 stage failed")
            bm25_stage.skip(f"BM25 检索出错：{exc}")
        bm25_stage.ms = (time.monotonic() - t0) * 1000.0
    stages["bm25"] = bm25_stage

    # -- vector ----------------------------------------------------------
    vector_stage = Stage("vector")
    vector_ranking: list[tuple[str, float]] = []
    #: Set inside the branch that runs the stage; ``None`` (the stage was
    #: switched off or had nothing to do) is reported as a null in ``models``.
    embed = None
    if not req.use_vector:
        vector_stage.skip("请求中关闭了向量检索")
    elif not chunks:
        vector_stage.skip("知识库还没有切片")
    elif getattr(kb, "needs_reindex", False):
        # The matrix was found not to line up with the chunks and was dropped.
        # Saying so beats "no vector file": the operator's next move is the
        # Reindex button, and the reason should name it.
        vector_stage.skip("向量索引与切片不一致，需要重建索引（库标记为需要重建）")
    elif kb.embedding_model is None or not kb.dims:
        vector_stage.skip("该知识库还没有用 embedding 模型建索引，只有 BM25 可用")
    elif vectors is None or len(vectors) != len(chunks):
        vector_stage.skip("该知识库没有可用的向量文件，请重建索引")
    else:
        # Resolved -- and, if nothing is loaded, loaded -- only now. The four
        # guards above are all "this stage cannot run", and an on-demand load
        # costs seconds and several hundred MB of NPU heap; spending that on a
        # stage switched off in the request, or on a library with no vector
        # file, would be the one case where the feature makes things worse.
        #
        # ``preferred`` is the library's own model: a search must compare the
        # query vector with vectors from the same space, and loading a
        # *different* embedding model here would silently produce the "维度/模型
        # 不一致" skip that the operator cannot act on.
        #
        # ``family`` is that model's *space*, and it is what makes a sibling
        # build an answer rather than a mismatch: the seq512 and seq2048 builds
        # are the same weights compiled at different lengths, and their vectors
        # agree to seven decimals, so a library built with one searches with the
        # other loaded (MYS-2706). A build from a *different* family still
        # resolves to the mismatch branch below, unchanged.
        family = model_resolve.vector_family_of(request, kb.embedding_model)
        embed = await model_resolve.resolve_or_load(
            request, "embedding", preferred=kb.embedding_model,
            family=family or None)
        if not embed:
            vector_stage.skip(f"{embed.reason}；向量检索已跳过，仅用 BM25")
        elif not model_resolve.same_space(family, embed):
            vector_stage.skip(
                f"当前加载的 embedding 模型是 {embed.model_id}，"
                f"与该库建索引时使用的 {kb.embedding_model} 不一致；"
                "向量空间不可比，已跳过向量检索（可用「重建索引」迁移到当前模型）")
        else:
            t0 = time.monotonic()
            try:
                query_vec = await _embed_one(request, embed, QUERY_INSTRUCTION + req.query)
                if len(query_vec) != int(kb.dims):
                    raise RuntimeError(
                        f"查询向量维度 {len(query_vec)} 与建库维度 {kb.dims} 不一致")
                vector_ranking = cosine_ranking(query_vec, vectors,
                                                [c["id"] for c in chunks], req.candidates)
                vector_stage.hits = [
                    {"chunk_id": cid, "rank": i + 1, "score": round(score, 6)}
                    for i, (cid, score) in enumerate(vector_ranking)
                ]
                if not vector_ranking:
                    vector_stage.skip("向量检索没有命中任何切片")
            except Exception as exc:
                logger.warning("vector stage failed: %s", exc)
                vector_ranking = []
                vector_stage.skip(f"向量检索失败：{exc}")
            vector_stage.ms = (time.monotonic() - t0) * 1000.0
    stages["vector"] = vector_stage

    # -- fusion ----------------------------------------------------------
    fusion_stage = Stage("fusion")
    t0 = time.monotonic()
    rankings = []
    if bm25_ranking:
        rankings.append([cid for cid, _ in bm25_ranking])
    if vector_ranking:
        rankings.append([cid for cid, _ in vector_ranking])
    fused = rrf_fuse(rankings)
    fusion_stage.hits = [
        {"chunk_id": cid, "rank": i + 1, "score": round(score, 6)}
        for i, (cid, score) in enumerate(fused[: req.candidates])
    ]
    if not rankings:
        fusion_stage.skip("BM25 与向量检索都没有结果，无法融合")
    elif len(rankings) == 1:
        fusion_stage.reason = ("只有 BM25 结果，RRF 退化为按 BM25 排序"
                               if bm25_ranking else "只有向量结果，RRF 退化为按向量排序")
    fusion_stage.ms = (time.monotonic() - t0) * 1000.0
    stages["fusion"] = fusion_stage

    # -- rerank ----------------------------------------------------------
    rerank_stage = Stage("rerank")
    rerank_scores: dict[str, float] = {}
    fused_candidates = fused[: req.candidates]
    rerank = None
    if not req.use_rerank:
        rerank_stage.skip("请求中关闭了精排")
    elif not fused_candidates:
        rerank_stage.skip("没有进入精排的候选")
    else:
        # Same reasoning as the vector stage: only load when the stage will
        # actually run. There is no "preferred" reranker -- any of them ranks the
        # same candidate list -- so the manager's own ordering decides.
        rerank = await model_resolve.resolve_or_load(request, "rerank")
        if not rerank:
            rerank_stage.skip(f"{rerank.reason}；按 RRF 顺序返回")
        else:
            t0 = time.monotonic()
            try:
                documents = [by_id[cid]["text"] for cid, _ in fused_candidates]
                scores = await rerank_documents(request, rerank, req.query, documents)
                scored = [(cid, score, score)
                          for (cid, _), score in zip(fused_candidates, scores)]
                # Sort by the score the API will show, not the raw logit: sigmoid is
                # monotonic, so the orders agree, but a reader comparing the response
                # to the ranking must not have to take that on trust.
                scored.sort(key=lambda row: -row[2])
                rerank_scores = {cid: score for cid, _, score in scored}
                rerank_stage.hits = [
                    {"chunk_id": cid, "rank": i + 1, "score": round(score, 6)}
                    for i, (cid, _, score) in enumerate(scored)
                ]
            except Exception as exc:
                logger.warning("rerank stage failed: %s", exc)
                rerank_stage.skip(f"精排失败：{exc}；按 RRF 顺序返回")
            rerank_stage.ms = (time.monotonic() - t0) * 1000.0
    stages["rerank"] = rerank_stage

    # -- the result list -------------------------------------------------
    bm25_scores = {cid: score for cid, score in bm25_ranking}
    bm25_rank = {cid: i + 1 for i, (cid, _) in enumerate(bm25_ranking)}
    vec_scores = {cid: score for cid, score in vector_ranking}
    vec_rank = {cid: i + 1 for i, (cid, _) in enumerate(vector_ranking)}
    rrf_scores = {cid: score for cid, score in fused}
    rrf_rank = {cid: i + 1 for i, (cid, _) in enumerate(fused)}

    if rerank_scores:
        ordered = [cid for cid, _ in sorted(rerank_scores.items(), key=lambda kv: -kv[1])]
    elif fused:
        ordered = [cid for cid, _ in fused]
    else:
        ordered = []

    results: list[dict] = []
    for position, cid in enumerate(ordered[: req.top_k]):
        chunk = by_id.get(cid)
        if chunk is None:  # pragma: no cover - ids come from `chunks`
            continue
        doc = chunk.get("doc") or {}
        results.append({
            "rank": position + 1,
            "chunk_id": cid,
            "doc_id": chunk.get("doc_id"),
            "doc_name": doc.get("name"),
            "page": chunk.get("page"),
            "source": chunk.get("source"),
            "text": chunk.get("text"),
            "boxes": chunk.get("boxes") or [],
            "scores": {
                "bm25": _round(bm25_scores.get(cid)),
                "bm25_rank": bm25_rank.get(cid),
                "vector": _round(vec_scores.get(cid)),
                "vector_rank": vec_rank.get(cid),
                "rrf": _round(rrf_scores.get(cid)),
                "rrf_rank": rrf_rank.get(cid),
                "rerank": _round(rerank_scores.get(cid)),
            },
        })

    return SearchResult(
        query=req.query,
        models={"embedding": embed.model_id if embed else None,
                "rerank": rerank.model_id if rerank else None},
        stages=stages,
        results=results,
        total_ms=(time.monotonic() - started) * 1000.0,
    )


def _round(value) -> float | None:
    return None if value is None else round(float(value), 6)
