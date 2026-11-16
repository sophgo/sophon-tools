"""The pipeline's arithmetic, driven directly instead of over HTTP.

Two things are worth testing this way. ``cosine_ranking`` is where the vector
stage's ordering comes from, and a stable sort is a property an HTTP-level test
only discovers by accident. And the stage-degradation matrix has nine
combinations; asserting them here means the API tests can stay about the API.

The fake request/worker below is deliberately minimal -- the point is the
control flow, not the transport, which ``tests/test_kb_api.py`` covers against
real mock workers.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.apps.kb.bm25 import Bm25Index
from app.apps.kb.retrieval import (
    QUERY_INSTRUCTION,
    RRF_K,
    SearchRequest,
    cosine_ranking,
    search,
)
from app.apps.kb.store import Kb


# -- cosine ranking ---------------------------------------------------------
def _unit(*values: float) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


def test_cosine_ranks_by_similarity():
    matrix = np.asarray([_unit(1, 0), _unit(0, 1), _unit(0.9, 0.1)], dtype="float32")
    ranked = cosine_ranking(_unit(1, 0), matrix, ["a", "b", "c"], limit=3)
    assert [cid for cid, _ in ranked] == ["a", "c", "b"]
    assert ranked[0][1] == pytest.approx(1.0, abs=1e-5)


def test_cosine_is_stable_for_equal_scores():
    """Equal similarity keeps chunk order -- ``argsort()[::-1]`` would reverse it."""
    matrix = np.asarray([_unit(1, 0)] * 4, dtype="float32")
    ranked = cosine_ranking(_unit(1, 0), matrix, ["a", "b", "c", "d"], limit=4)
    assert [cid for cid, _ in ranked] == ["a", "b", "c", "d"]


def test_cosine_normalises_the_query():
    """A query's magnitude must not change the ranking."""
    matrix = np.asarray([_unit(1, 1), _unit(1, 0)], dtype="float32")
    small = cosine_ranking([0.1, 0.1], matrix, ["a", "b"], limit=2)
    large = cosine_ranking([100.0, 100.0], matrix, ["a", "b"], limit=2)
    assert [cid for cid, _ in small] == [cid for cid, _ in large]


def test_cosine_honours_the_limit():
    matrix = np.asarray([_unit(1, i / 10 + 0.01) for i in range(10)], dtype="float32")
    assert len(cosine_ranking(_unit(1, 0), matrix,
                              [f"c{i}" for i in range(10)], limit=3)) == 3


def test_a_zero_query_vector_ranks_nothing():
    """All zeros is not "equally similar to everything"; it has no direction."""
    matrix = np.asarray([_unit(1, 0)], dtype="float32")
    assert cosine_ranking([0.0, 0.0], matrix, ["a"], limit=1) == []


def test_cosine_without_a_matrix_or_chunks_is_empty():
    assert cosine_ranking([1.0, 0.0], None, [], limit=5) == []
    assert cosine_ranking([1.0, 0.0], np.zeros((0, 2), dtype="float32"), [], limit=5) == []


# -- the pipeline -----------------------------------------------------------
CHUNKS = [
    {"id": "d1:0", "doc_id": "d1", "doc": {"id": "d1", "name": "制度.txt"},
     "page": None, "source": "text", "text": "仓库盘点由仓管员执行。", "boxes": []},
    {"id": "d2:0", "doc_id": "d2", "doc": {"id": "d2", "name": "差异.txt"},
     "page": 1, "source": "text", "text": "盘点差异率超过千分之五须由财务复核。", "boxes": []},
    {"id": "d3:0", "doc_id": "d3", "doc": {"id": "d3", "name": "其他.txt"},
     "page": 1, "source": "text", "text": "消防通道不得堆放物料。", "boxes": []},
]


class FakeInfo:
    def __init__(self, model_id: str, kind: str) -> None:
        self.model_id = model_id
        self.kind = kind
        self.loaded = True
        self.operation = None
        self.loaded_at = 1.0
        # Read by ``ModelManager.best_loaded``; the fake has nothing downloading.
        self.downloading = False
        self.last_used_at = None


class FakeClient:
    """Records what it was asked and answers deterministically."""

    def __init__(self, vectors: dict[str, list[float]], logits: dict[str, float]) -> None:
        self.vectors = vectors
        self.logits = logits
        self.embed_calls: list[list[str]] = []
        self.rerank_calls: list[tuple[str, list[str]]] = []

    async def embed(self, req_id, texts, dimensions=None):
        self.embed_calls.append(list(texts))
        return {"vectors": [self.vectors[t] for t in texts]}

    async def rerank(self, req_id, query, documents):
        self.rerank_calls.append((query, list(documents)))
        return {"logits": [self.logits[d] for d in documents]}


class FakeManager:
    """The manager as ``resolve_or_load`` sees it.

    ``load_for`` is the on-demand path's contract, and this fake has nothing to
    load -- every model it knows about is already loaded, which is what the
    pipeline tests want. It still implements the method rather than leaving it
    out, so a change to what the resolver calls is a change the fake has to
    acknowledge instead of a silent AttributeError at the first search.
    """

    def __init__(self, models: list[FakeInfo], clients: dict) -> None:
        self._models = models
        self._clients = clients
        self.touched: list[str] = []
        #: Set to a string to make ``load_for`` fail the way a real load would.
        self.load_error: str | None = None

    def list(self):
        return self._models

    def still_loaded(self, info):
        return True

    def touch(self, model_id):
        self.touched.append(model_id)

    def best_loaded(self, kind, preferred=None, family=None):
        ready = [m for m in self._models
                 if m.kind == kind and m.loaded and m.operation is None]
        if not ready:
            return None
        if preferred:
            for m in ready:
                if m.model_id == preferred:
                    return m
        if family:
            same = [m for m in ready
                    if getattr(m, "vector_family", "") == family]
            if same:
                same.sort(key=lambda m: m.loaded_at or 0.0, reverse=True)
                return same[0]
        ready.sort(key=lambda m: m.loaded_at or 0.0, reverse=True)
        return ready[0]

    def candidates_for(self, kind, family=None, preferred=None):
        return [m for m in self._models if m.kind == kind]

    async def load_for(self, kind, preferred=None, family=None):
        ready = self.best_loaded(kind, preferred, family=family)
        if ready is not None:
            return ready, None
        if not self.candidates_for(kind):
            return None, f"没有已下载的{kind}模型"
        return None, self.load_error or f"{kind}模型自动加载失败"


class FakeApp:
    def __init__(self, manager: FakeManager, clients: dict) -> None:
        self.state = type("S", (), {"models": manager, "clients": clients})()


class FakeRequest:
    def __init__(self, app: FakeApp) -> None:
        self.app = app


def make_request(*, embed: str | None, rerank: str | None) -> tuple[FakeRequest, dict]:
    models: list[FakeInfo] = []
    clients: dict = {}
    if embed:
        models.append(FakeInfo(embed, "embedding"))
        clients[embed] = FakeClient(
            {QUERY_INSTRUCTION + "盘点差异": [1.0, 0.0, 0.0]},
            {})
    if rerank:
        models.append(FakeInfo(rerank, "rerank"))
        clients[rerank] = FakeClient(
            {},
            # The reranker likes the second chunk best -- deliberately the
            # opposite of BM25's order, so "rerank decided" is observable.
            {"仓库盘点由仓管员执行。": -2.0,
             "盘点差异率超过千分之五须由财务复核。": 3.0,
             "消防通道不得堆放物料。": -5.0})
    return FakeRequest(FakeApp(FakeManager(models, clients), clients)), clients


def make_kb(model: str | None, dims: int = 3) -> Kb:
    return Kb(id="kb", name="库", created_at=0.0, embedding_model=model,
              dims=dims if model else 0)


def make_vectors() -> np.ndarray:
    return np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                      dtype="float32")


def build_index() -> Bm25Index:
    return Bm25Index.build(CHUNKS)


@pytest.mark.asyncio
async def test_all_four_stages_run_when_both_models_are_loaded():
    request, _ = make_request(embed="emb", rerank="rr")
    result = await search(
        request, kb=make_kb("emb"), chunks=CHUNKS, bm25=build_index(),
        vectors=make_vectors(),
        req=SearchRequest(query="盘点差异", top_k=3, candidates=5))
    for name in ("bm25", "vector", "fusion", "rerank"):
        assert result.stages[name].status == "ok", (name, result.stages[name].reason)
    assert result.models == {"embedding": "emb", "rerank": "rr"}
    # Rerank decided the order: the chunk it scored highest leads.
    assert result.results[0]["chunk_id"] == "d2:0"
    assert result.results[0]["scores"]["rerank"] is not None


@pytest.mark.asyncio
async def test_bm25_alone_decides_when_both_models_are_missing():
    request, _ = make_request(embed=None, rerank=None)
    result = await search(
        request, kb=make_kb(None), chunks=CHUNKS, bm25=build_index(),
        vectors=None, req=SearchRequest(query="盘点差异"))
    assert result.stages["bm25"].status == "ok"
    assert result.stages["vector"].status == "skipped"
    assert result.stages["rerank"].status == "skipped"
    assert result.stages["fusion"].status == "ok"
    assert result.results[0]["chunk_id"] == "d2:0"  # BM25's own order gave this
    for item in result.results:
        assert item["scores"]["vector"] is None
        assert item["scores"]["rerank"] is None


@pytest.mark.asyncio
async def test_a_different_embedding_model_skips_the_vector_stage():
    request, _ = make_request(embed="other", rerank=None)
    result = await search(
        request, kb=make_kb("emb"), chunks=CHUNKS, bm25=build_index(),
        vectors=make_vectors(), req=SearchRequest(query="盘点差异"))
    stage = result.stages["vector"]
    assert stage.status == "skipped"
    assert "other" in stage.reason and "emb" in stage.reason
    # And the query was never embedded, so no NPU time was spent on a useless call.
    assert request.app.state.clients["other"].embed_calls == []


@pytest.mark.asyncio
async def test_a_library_with_no_recorded_model_skips_the_vector_stage():
    request, _ = make_request(embed="emb", rerank=None)
    result = await search(
        request, kb=make_kb(None), chunks=CHUNKS, bm25=build_index(),
        vectors=make_vectors(), req=SearchRequest(query="盘点差异"))
    assert result.stages["vector"].status == "skipped"
    assert "建索引" in result.stages["vector"].reason


@pytest.mark.asyncio
async def test_an_empty_library_skips_with_a_reason_per_stage():
    request, _ = make_request(embed="emb", rerank="rr")
    result = await search(
        request, kb=make_kb("emb"), chunks=[], bm25=Bm25Index.build([]),
        vectors=None, req=SearchRequest(query="盘点差异"))
    for name in ("vector", "fusion", "rerank"):
        assert result.stages[name].status == "skipped", name
        assert result.stages[name].reason
    assert result.results == []


@pytest.mark.asyncio
async def test_a_query_with_no_terms_skips_bm25_but_vectors_still_run():
    request, _ = make_request(embed="emb", rerank=None)
    request.app.state.clients["emb"].vectors[QUERY_INSTRUCTION + "，。"] = [0.0, 1.0, 0.0]
    result = await search(
        request, kb=make_kb("emb"), chunks=CHUNKS, bm25=build_index(),
        vectors=make_vectors(), req=SearchRequest(query="，。"))
    assert result.stages["bm25"].status == "skipped"
    assert "没有可检索的词" in result.stages["bm25"].reason
    assert result.stages["vector"].status == "ok"
    assert result.stages["fusion"].reason  # says RRF degenerated to one ranking


@pytest.mark.asyncio
async def test_the_fusion_stage_says_so_when_it_had_only_one_ranking():
    request, _ = make_request(embed=None, rerank=None)
    result = await search(
        request, kb=make_kb(None), chunks=CHUNKS, bm25=build_index(),
        vectors=None, req=SearchRequest(query="盘点差异"))
    assert result.stages["fusion"].status == "ok"
    assert "BM25" in result.stages["fusion"].reason


@pytest.mark.asyncio
async def test_a_rerank_failure_falls_back_to_the_rrf_order():
    """A worker that refuses must not lose the answer the other stages produced."""
    request, clients = make_request(embed="emb", rerank="rr")

    async def boom(req_id, query, documents):
        raise RuntimeError("worker 挂了")

    clients["rr"].rerank = boom
    result = await search(
        request, kb=make_kb("emb"), chunks=CHUNKS, bm25=build_index(),
        vectors=make_vectors(), req=SearchRequest(query="盘点差异"))
    assert result.stages["rerank"].status == "skipped"
    assert "精排失败" in result.stages["rerank"].reason
    assert result.results
    rrf_ranks = [item["scores"]["rrf_rank"] for item in result.results]
    assert rrf_ranks == sorted(rrf_ranks)


@pytest.mark.asyncio
async def test_a_vector_dimension_mismatch_skips_the_stage():
    request, clients = make_request(embed="emb", rerank=None)
    clients["emb"].vectors[QUERY_INSTRUCTION + "盘点差异"] = [1.0, 0.0]  # 2, not 3
    result = await search(
        request, kb=make_kb("emb"), chunks=CHUNKS, bm25=build_index(),
        vectors=make_vectors(), req=SearchRequest(query="盘点差异"))
    assert result.stages["vector"].status == "skipped"
    assert "维度" in result.stages["vector"].reason


@pytest.mark.asyncio
async def test_top_k_truncates_the_result_list():
    request, _ = make_request(embed=None, rerank=None)
    result = await search(
        request, kb=make_kb(None), chunks=CHUNKS, bm25=build_index(),
        vectors=None, req=SearchRequest(query="盘点差异", top_k=1, candidates=5))
    assert len(result.results) == 1
    assert result.results[0]["rank"] == 1


@pytest.mark.asyncio
async def test_results_carry_the_document_name_and_page():
    request, _ = make_request(embed=None, rerank=None)
    result = await search(
        request, kb=make_kb(None), chunks=CHUNKS, bm25=build_index(),
        vectors=None, req=SearchRequest(query="盘点差异"))
    by_id = {item["chunk_id"]: item for item in result.results}
    assert by_id["d2:0"]["doc_name"] == "差异.txt"
    assert by_id["d2:0"]["page"] == 1
    assert by_id["d1:0"]["page"] is None


@pytest.mark.asyncio
async def test_the_enabled_switches_turn_stages_off_with_a_reason():
    request, _ = make_request(embed="emb", rerank="rr")
    result = await search(
        request, kb=make_kb("emb"), chunks=CHUNKS, bm25=build_index(),
        vectors=make_vectors(),
        req=SearchRequest(query="盘点差异", use_bm25=False, use_vector=False,
                          use_rerank=False))
    assert result.stages["bm25"].reason == "请求中关闭了 BM25"
    assert result.stages["vector"].reason == "请求中关闭了向量检索"
    assert result.stages["rerank"].reason == "请求中关闭了精排"
    assert result.results == []


def test_the_query_instruction_is_the_pinned_string():
    """One character here moves the reference similarity out of tolerance."""
    assert QUERY_INSTRUCTION == (
        "Instruct: Given a web search query, retrieve relevant passages "
        "that answer the query\nQuery: ")


def test_the_rrf_constant_is_the_published_one():
    assert RRF_K == 60


@pytest.mark.asyncio
async def test_the_result_shape_has_every_documented_key():
    """The console reads these names; a rename here must not silently rename them."""
    request, _ = make_request(embed=None, rerank=None)
    result = await search(
        request, kb=make_kb(None), chunks=CHUNKS, bm25=build_index(),
        vectors=None, req=SearchRequest(query="盘点差异"))
    body = result.public()
    assert set(body) == {"query", "models", "stages", "results", "timings"}
    assert set(body["timings"]) == {"total_ms"}
    for name in ("bm25", "vector", "fusion", "rerank"):
        assert set(body["stages"][name]) == {"status", "reason", "ms", "hits"}
    for item in body["results"]:
        assert set(item) == {"rank", "chunk_id", "doc_id", "doc_name", "page",
                             "source", "text", "boxes", "scores"}
        assert set(item["scores"]) == {
            "bm25", "bm25_rank", "vector", "vector_rank",
            "rrf", "rrf_rank", "rerank"}
