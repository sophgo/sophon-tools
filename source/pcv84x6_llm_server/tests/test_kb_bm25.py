"""BM25 tokenisation, scoring and fusion.

The tokeniser is the part an operator can check by eye -- a Chinese query must
match Chinese text through bigrams, an English one through words -- so the tests
assert the tokens themselves, not just that *something* matched. The scoring
tests use the properties BM25 has by construction (a rarer term weighs more, a
longer document is penalised, a repeated query term does not multiply its own
weight) rather than pinning absolute numbers that a floating-point change would
break for no reason.
"""

from __future__ import annotations

import math

import pytest

from app.apps.kb.bm25 import Bm25Index, tokenize
from app.apps.kb.retrieval import RRF_K, rrf_fuse


# -- tokenisation -----------------------------------------------------------
def test_chinese_runs_become_overlapping_bigrams():
    assert tokenize("仓库盘点") == ["仓库", "库盘", "盘点"]


def test_a_single_chinese_character_stays_one_token():
    assert tokenize("仓") == ["仓"]


def test_latin_words_are_lowercased():
    assert tokenize("Warehouse Inventory") == ["warehouse", "inventory"]


def test_digits_are_words():
    assert tokenize("A-001 12 3.50") == ["a", "001", "12", "3", "50"]


def test_cjk_and_latin_run_side_by_side():
    """A mixed sentence tokenises both halves, in order."""
    assert tokenize("盘点 PID 控制") == ["盘点", "pid", "控制"]


def test_punctuation_and_space_are_separators():
    assert tokenize("盘点，核对；差异！") == ["盘点", "核对", "差异"]


def test_full_width_characters_are_normalised():
    """NFKC folds full-width Latin so a query typed in Chinese IME matches."""
    assert tokenize("ＰＩＤ") == ["pid"]


def test_an_empty_or_symbol_only_query_has_no_tokens():
    assert tokenize("") == []
    assert tokenize("   ，。！  ") == []


# -- scoring ----------------------------------------------------------------
def _chunks(*texts: str) -> list[dict]:
    return [{"id": f"d:{i}", "text": text} for i, text in enumerate(texts)]


def test_a_rarer_term_outweighs_a_common_one():
    """IDF in one assertion: "盘点" is everywhere, "失窃" is in one document."""
    index = Bm25Index.build(_chunks(
        "仓库盘点制度",
        "仓库盘点流程",
        "仓库盘点差异处理",
        "失窃与损耗的处理规定",
    ))
    assert index.idf["失窃"] > index.idf["仓库"]


def test_the_document_containing_the_query_term_ranks_first():
    index = Bm25Index.build(_chunks(
        "本章讲解仓库的日常管理。",
        "盘点差异率超过千分之五时必须由财务复核。",
        "本章讲解消防安全。",
    ))
    hits = index.search("差异 复核", limit=10)
    assert hits and hits[0][0] == "d:1"


def test_a_longer_document_is_penalised_for_the_same_term():
    """The ``b`` parameter: the same one hit in a long document scores lower."""
    short = "盘点"
    long_text = "盘点" + "无关内容" * 60
    index = Bm25Index.build(_chunks(short, long_text))
    scores = dict(index.search("盘点", limit=10))
    assert scores["d:0"] > scores["d:1"]


def test_a_repeated_query_term_does_not_multiply_its_weight():
    """Distinct terms only: "盘点 盘点" must rank exactly like "盘点"."""
    index = Bm25Index.build(_chunks("盘点制度", "其它内容"))
    once = index.search("盘点", limit=10)
    twice = index.search("盘点 盘点", limit=10)
    assert [cid for cid, _ in once] == [cid for cid, _ in twice]
    assert once[0][1] == pytest.approx(twice[0][1])


def test_an_unknown_term_scores_nothing():
    index = Bm25Index.build(_chunks("盘点制度", "差异处理"))
    assert index.search("完全不存在的词", limit=10) == []


def test_an_empty_query_returns_nothing():
    index = Bm25Index.build(_chunks("盘点制度"))
    assert index.search("", limit=10) == []
    assert index.search("，。", limit=10) == []


def test_the_limit_is_honoured():
    index = Bm25Index.build(_chunks(*[f"盘点 第{i}条" for i in range(20)]))
    assert len(index.search("盘点", limit=3)) == 3


def test_hits_are_ordered_by_score_descending():
    index = Bm25Index.build(_chunks(
        "盘点",
        "盘点 差异",
        "差异",
        "盘点 差异 复核",
    ))
    hits = index.search("盘点 差异 复核", limit=10)
    scores = [score for _, score in hits]
    assert scores == sorted(scores, reverse=True)


def test_equal_scores_keep_document_order():
    """A stable sort, so two identical requests cannot disagree."""
    index = Bm25Index.build(_chunks("盘点", "盘点", "盘点"))
    hits = index.search("盘点", limit=10)
    assert [cid for cid, _ in hits] == ["d:0", "d:1", "d:2"]


def test_the_idf_formula_matches_lucene():
    """Pinned because the constant is a decision, not an accident."""
    index = Bm25Index.build(_chunks("盘点", "盘点", "其它"))
    total, n = 3, 2
    assert index.idf["盘点"] == pytest.approx(math.log(1.0 + (total - n + 0.5) / (n + 0.5)))


def test_an_empty_index_can_still_be_searched():
    index = Bm25Index.build([])
    assert len(index) == 0
    assert index.search("盘点", limit=10) == []


# -- RRF --------------------------------------------------------------------
def test_rrf_adds_the_reciprocals_of_both_ranks():
    fused = dict(rrf_fuse([["a", "b"], ["b", "a"]]))
    assert fused["a"] == pytest.approx(1 / (RRF_K + 1) + 1 / (RRF_K + 2))
    assert fused["b"] == pytest.approx(fused["a"])


def test_rrf_puts_a_document_found_by_both_first():
    """The point of fusion: agreement between stages beats one strong hit."""
    fused = rrf_fuse([["bm25only", "both"], ["both", "vecOnly"]])
    assert fused[0][0] == "both"


def test_a_single_ranking_passes_through_in_order():
    fused = rrf_fuse([["c", "a", "b"]])
    assert [cid for cid, _ in fused] == ["c", "a", "b"]
    assert fused[0][1] > fused[1][1] > fused[2][1]


def test_rrf_scores_follow_the_published_formula():
    fused = dict(rrf_fuse([["x"], ["x"]]))
    assert fused["x"] == pytest.approx(2 / (RRF_K + 1))


def test_rrf_with_no_rankings_is_empty():
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []


def test_rrf_ties_are_broken_by_first_appearance():
    """Deterministic ordering, and BM25's order wins because it is listed first."""
    fused = rrf_fuse([["a"], ["b"]])
    assert [cid for cid, _ in fused] == ["a", "b"]
    assert fused[0][1] == pytest.approx(fused[1][1])
