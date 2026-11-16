"""The ingest-side split: a chunk too dense to embed is split, not lost.

``chunker.MAX_CHUNK_CHARS`` caps chunks in characters, but the embedding model
refuses in tokens, and the exchange rate depends on the script -- three tokens
per character for CJK Extension B and for private-use codepoints, one for
ordinary CJK, a sixth for Latin prose. So a character ceiling cannot by itself
guarantee that a chunk fits, and a refused request used to fail the embedding of
the whole *document*.

The host has no tokenizer, so the worker's refusal (``InputRefused``) is the
test. This file pins what ``Ingestor._embed_chunks`` / ``_embed_fitted`` do:

* a batch the worker accepts is sent once, exactly as before (all normal use);
* a refused batch is retried chunk by chunk, and only the refused chunk is split,
  into pieces the worker accepts;
* the pieces are folded back into one vector per chunk, unit length.

``tests/test_kb_api.py::test_a_dense_document_is_indexed_not_failed`` runs the
same case through the real app and the mock worker.
"""

from __future__ import annotations

import pytest

from app.apps.kb import ingest as ingest_mod
from app.apps.kb.chunker import Chunk
from app.apps.kb.retrieval import InputRefused

LIMIT = 2048


def _tokens(text: str) -> int:
    # "𠀀" (CJK Extension B) costs 3 tokens a character, everything else 1.
    return sum(3 if ch == "\U00020000" else 1 for ch in text)


class _Chunk(Chunk):
    pass


def test_pieces_fold_back_into_one_unit_vector_per_chunk():
    """``_pool_pieces`` averages a split chunk and leaves whole ones alone."""
    whole = [0.0, 1.0]
    a, b = [1.0, 0.0], [0.0, 1.0]
    out = ingest_mod._pool_pieces([whole, a, b], [1, 2])
    assert out[0] == whole, "a chunk that was not split must be returned verbatim"
    pooled = out[1]
    # The mean of two unit vectors, renormalised: still unit length, pointing
    # between its parts.
    assert len(pooled) == 2
    assert abs(sum(x * x for x in pooled) ** 0.5 - 1.0) < 1e-9
    assert abs(pooled[0] - pooled[1]) < 1e-12


def test_pooling_a_single_piece_group_is_the_identity():
    """No arithmetic on the normal path -- the guarantee the docstring makes."""
    vectors = [[0.6, 0.8], [0.0, 1.0]]
    assert ingest_mod._pool_pieces(vectors, [1, 1]) is vectors


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    """An ``Ingestor`` whose ``embed_passages`` refuses like the real worker."""
    from app.apps.kb.store import KbStore

    store = KbStore(tmp_path / "kb")
    kb = store.create_kb("稠密库")
    doc_id = "d" * 32
    (store.docs_dir(kb.id) / doc_id / "pages").mkdir(parents=True)
    store.write_doc_meta(kb.id, doc_id, {
        "id": doc_id, "name": "稠密.txt", "type": "txt", "bytes": 4,
        "status": "embedding", "created_at": 0.0})
    calls: list[list[int]] = []

    async def embed_passages(request, resolved, texts):
        sizes = [_tokens(t) for t in texts]
        calls.append(sizes)
        over = [n for n in sizes if n > LIMIT]
        if over:
            raise InputRefused(f"输入编码后为 {over[0]} 个 token，超过该模型上限 {LIMIT}")
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(ingest_mod, "embed_passages", embed_passages)
    ingestor = ingest_mod.Ingestor(store)
    job = ingest_mod.Job(kb_id=kb.id, doc_id=doc_id, store=store, request=None)
    return ingestor, job, calls


def _chunks(*texts: str) -> list[Chunk]:
    return [_Chunk(page=1, source="text", text=t, char_start=0, char_end=len(t)) for t in texts]


@pytest.mark.asyncio
async def test_a_batch_that_fits_is_sent_once_unchanged(harness):
    """The common path: one request for the batch, nothing split, nothing retried."""
    ingestor, job, calls = harness
    texts = ["仓库盘点要求：两人共同完成，并在盘点单上签字。" * 5] * 4
    vectors = await ingestor._embed_chunks(job, _chunks(*texts), None, total=4)
    assert len(vectors) == 4
    assert calls == [[_tokens(t) for t in texts]]


@pytest.mark.asyncio
async def test_a_dense_chunk_is_split_into_pieces_the_worker_accepts(harness):
    """A 3000-token chunk: refused whole, then embedded as accepted pieces, one vector out."""
    ingestor, job, calls = harness
    dense = "\U00020000" * 1000
    vectors = await ingestor._embed_chunks(job, _chunks(dense), None, total=1)
    assert len(vectors) == 1, "one chunk in, one vector out"
    accepted = [n for sizes in calls if all(x <= LIMIT for x in sizes) for n in sizes]
    assert sum(accepted) == _tokens(dense), "the pieces cover the chunk exactly"
    assert len(accepted) > 1


@pytest.mark.asyncio
async def test_only_the_refused_chunk_is_split(harness):
    """One dense chunk in a batch of four: the other three are embedded whole."""
    ingestor, job, calls = harness
    normal = "设备巡检记录。" * 20
    dense = "\U00020000" * 800                      # 2400 tokens
    vectors = await ingestor._embed_chunks(job, _chunks(normal, dense, normal, normal), None, total=4)
    assert len(vectors) == 4
    first, retries = calls[0], calls[1:]
    assert first == [_tokens(normal), 2400, _tokens(normal), _tokens(normal)], "the batch went once, whole"
    assert all(len(sizes) == 1 for sizes in retries), "the retry is chunk by chunk"
    sizes = [x[0] for x in retries]
    assert sizes.count(_tokens(normal)) == 3, "each ordinary chunk is retried once, whole"
    assert 2400 in sizes, "the dense chunk is tried whole first"
    dense_pieces = [n for n in sizes if n not in (_tokens(normal), 2400)]
    assert len(dense_pieces) > 1 and all(n <= LIMIT for n in dense_pieces)
    assert sum(dense_pieces) == 2400, "the pieces cover the dense chunk exactly"


@pytest.mark.asyncio
async def test_a_refusal_that_splitting_cannot_fix_still_fails(harness, monkeypatch):
    """A refusal that is not about length is not retried forever: it surfaces."""
    ingestor, job, _ = harness

    async def always_refuse(request, resolved, texts):
        raise InputRefused("输入编码后为 0 个 token")

    monkeypatch.setattr(ingest_mod, "embed_passages", always_refuse)
    with pytest.raises(InputRefused):
        await ingestor._embed_chunks(job, _chunks("abcdefgh" * 200), None, total=1)
