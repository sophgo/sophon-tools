"""The nine MCP tools, driven over the mock backend.

Every tool goes through the same path a real client's call takes: HTTP POST to
``/mcp``, the JSON-RPC dispatcher, the tool, and the knowledge-base or OCR code
the console's own routes use. The mock backend supplies real model *workers* (its
embeddings are hashed, its OCR invents words and its transcriber derives text
from the audio), so the assertions are about the contract -- which stage ran,
what the citation looks like, that the queued document becomes searchable, that an
inference record names the MCP caller -- and never about which document "should"
rank first.

Two things these tests check that the protocol file does not. First, that a tool
call's **inference records are attributed to the MCP surface**, not to the
console -- a requirement of the card, and easy to get silently wrong, because the
recording happens inside ``app/apps/kb/retrieval``, code this branch may not
change. Second, the resource-exhaustion edges: a ``pages`` range that used to
expand to two billion integers, an image that would decode to half a gigabyte,
and the concurrency bound on the two NPU-heavy tools.
"""

from __future__ import annotations

import io
import json
import math
import struct
import time
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.mcp import tools as mcp_tools

EMBED_BMODEL = "qwen3-embedding-0.6b_bf16"
RERANK_BMODEL = "bge-reranker-v2-m3_bf16"
ASR_BMODEL = "qwen3-asr-0.6b_bf16"
OCR_BMODEL = "ppocrv6-medium-det_f16_736_bm1684x2_static_20261103.bmodel"
OCR_REC = ("ppocrv6-medium-rec_f16_48x320_bm1684x2_static_20261103.bmodel",
           "ppocrv6-medium-rec_f16_48x640_bm1684x2_static_20261103.bmodel",
           "ppocrv6-medium-rec_f16_48x1600_bm1684x2_static_20261103.bmodel")
#: The VLM ``mode: "vl"`` needs as its second model.
OCR_VL_BMODEL = "paddleocr-vl-1.5_bf16_seq2048_bm1684x2_4core_static.bmodel"

ROOT = Path(__file__).resolve().parent.parent
OCR_IMG = ROOT / "tests" / "data" / "ocr" / "img"
KB_DATA = ROOT / "tests" / "data" / "kb"

SAMPLE_RATE = 16000


def make_model(root: Path, name: str, bmodel: str, context: str = "seq2048") -> Path:
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{bmodel}_{context}_4core_static.bmodel").write_bytes(b"\x00" * 4096)
    (d / "config" / "config.json").write_text("{}")
    return d


def make_ocr_model(root: Path) -> Path:
    d = root / "ocr-model"
    d.mkdir(parents=True)
    (d / OCR_BMODEL).write_bytes(b"\x00" * 4096)
    for rec in OCR_REC:
        (d / rec).write_bytes(b"\x00" * 2048)
    return d


def make_ocr_vl_model(root: Path) -> Path:
    d = root / "paddleocr-vl-1.5"
    d.mkdir(parents=True)
    (d / OCR_VL_BMODEL).write_bytes(b"\x00" * 4096)
    return d


def wav_bytes(seconds: float, rate: int = SAMPLE_RATE, freq: float = 440.0) -> bytes:
    """A mono 16-bit PCM WAV of ``seconds`` of a sine, as an agent would point at."""
    frames = int(round(seconds * rate))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate)))
            for i in range(frames)))
    return buf.getvalue()


@pytest.fixture()
def app(tmp_path: Path):
    models = tmp_path / "models"
    make_model(models, "embed-model", EMBED_BMODEL)
    make_model(models, "rerank-model", RERANK_BMODEL, context="seq2048")
    make_model(models, "asr-model", ASR_BMODEL, context="seq1024")
    make_ocr_model(models)
    make_ocr_vl_model(models)
    return turn_aux_on(create_app(data_dir=tmp_path / "data", models_dir=models,
                                  backend_kind="mock", web_dir=tmp_path / "web",
                                  context_length_override=4096))


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
        yield c


@pytest.fixture()
def headers(client):
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    raw = client.post("/api/keys", json={"name": "mcp-client"}).json()["key"]
    return {"Authorization": f"Bearer {raw}"}


def load(client, *model_ids: str) -> None:
    for model_id in model_ids:
        r = client.post(f"/api/models/{model_id}/load")
        assert r.status_code == 200, r.text


def call(client, headers, name: str, arguments: dict | None = None) -> dict:
    """One ``tools/call``, with the transport assertions every call shares."""
    r = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("id") == 7
    assert "error" not in body, body
    return body["result"]


def ok(client, headers, name: str, arguments: dict | None = None) -> tuple[str, dict]:
    result = call(client, headers, name, arguments)
    assert result["isError"] is False, result["content"][0]["text"]
    return result["content"][0]["text"], result.get("structuredContent") or {}


def fails(client, headers, name: str, arguments: dict | None = None) -> str:
    result = call(client, headers, name, arguments)
    assert result["isError"] is True, result
    return result["content"][0]["text"]


def make_kb(client, name: str = "演示库") -> str:
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    r = client.post("/api/apps/kb", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["kb"]["id"]


def wait_ready(client, kb: str, timeout: float = 40.0) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        docs = client.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
        if docs and all(d["status"] not in ("queued", "parsing", "ocr", "embedding")
                        for d in docs):
            return docs
        time.sleep(0.05)
    raise AssertionError(f"documents did not settle: "
                         f"{[(d['name'], d['status']) for d in docs]}")


def seed(client, headers, kb_name: str = "演示库") -> str:
    """A library with two documents, built through the MCP tools themselves.

    Building it the way an agent would is the point: if ``kb_add_document``
    queues something the ingestor cannot index, the search tests below fail for
    the right reason instead of passing on a library the console made.
    """
    load(client, "embed-model")
    kb = make_kb(client, kb_name)
    for name, text in (
        ("制度.txt", "仓库盘点由仓管员在每个季度末执行。盘点前必须冻结出入库操作。"),
        ("差异.txt", "盘点差异率超过千分之五时必须由财务复核，并出具差异说明。"),
    ):
        ok(client, headers, "kb_add_document", {"kb": kb, "text": text, "name": name})
    wait_ready(client, kb)
    return kb


# ---------------------------------------------------------------------------
# kb_list / kb_create
# ---------------------------------------------------------------------------
def test_kb_list_is_empty_before_anything_exists(client, headers):
    text, structured = ok(client, headers, "kb_list")
    assert "还没有知识库" in text
    assert structured == {"kbs": []}


def test_kb_create_returns_a_library_kb_list_then_shows(client, headers):
    text, structured = ok(client, headers, "kb_create", {"name": "季度报告"})
    kb = structured["kb"]
    assert kb["name"] == "季度报告"
    assert kb["docs"] == 0 and kb["chunks"] == 0
    assert kb["embedding_model"] is None

    text, structured = ok(client, headers, "kb_list")
    assert "季度报告" in text
    assert [k["id"] for k in structured["kbs"]] == [kb["id"]]
    # The list says the library has no vectors, which is what tells an agent its
    # searches will be BM25-only until something is indexed.
    assert "未建向量索引" in text


def test_kb_create_refuses_an_empty_name(client, headers):
    message = fails(client, headers, "kb_create", {"name": "   "})
    assert "name" in message


# ---------------------------------------------------------------------------
# kb_search
# ---------------------------------------------------------------------------
def test_kb_search_returns_citations_in_the_agreed_shape(client, headers):
    kb = seed(client, headers)
    load(client, "rerank-model")
    text, structured = ok(client, headers, "kb_search", {"query": "盘点差异率", "kb": kb})
    results = structured["results"]
    assert results, text
    # ``[n] 文档名 第 p 页（相关度 x）`` then the passage -- the card's shape.
    first = results[0]
    assert text.startswith("检索「盘点差异率」")
    assert f"[1] {first['doc_name']}" in text
    assert "相关度" in text
    # Every returned passage's own text is in the reply: a citation with no
    # passage is not something a model can answer from.
    assert first["text"] in text
    for row in results:
        assert row["chunk_id"] and row["doc_name"] and row["text"]
        assert isinstance(row["scores"], dict)


def test_kb_search_says_which_stages_ran(client, headers):
    kb = seed(client, headers)
    # MYS-2657: with models on disk but not loaded, they are loaded on demand and
    # the reply reports what actually ran. ``stages`` is {kb_name: summary} -- the
    # one-line form an agent reads, naming each stage's name and status.
    text, structured = ok(client, headers, "kb_search", {"query": "盘点", "kb": kb})
    assert "执行：" in text
    summary = structured["stages"][structured["kbs"][0]["name"]]
    assert "vector" in summary and "rerank" in summary


def test_kb_search_with_auto_load_off_reports_the_skipped_stages(client, headers):
    """The half of the reply that says a stage did not run, on the path that still does."""
    kb = seed(client, headers)
    client.post("/api/settings", json={"aux_auto_load": False})
    for mid in ("embed-model", "rerank-model"):
        client.post(f"/api/models/{mid}/unload")
    text, structured = ok(client, headers, "kb_search", {"query": "盘点", "kb": kb})
    assert "跳过：" in text
    summary = structured["stages"][structured["kbs"][0]["name"]]
    assert "skipped" in summary or "跳过" in summary


def test_kb_search_without_a_kb_uses_the_only_library(client, headers):
    kb = seed(client, headers, "唯一的库")
    text, structured = ok(client, headers, "kb_search", {"query": "盘点"})
    assert structured["kbs"] == [{"id": kb, "name": "唯一的库"}]


def test_kb_search_without_a_kb_searches_every_library_and_labels_the_source(
        client, headers):
    first = seed(client, headers, "甲库")
    second = seed(client, headers, "乙库")
    text, structured = ok(client, headers, "kb_search", {"query": "盘点"})
    assert {k["id"] for k in structured["kbs"]} == {first, second}
    # Multiple libraries: each hit names the library it came from, or a reader
    # cannot tell where a passage lives.
    assert "甲库" in text and "乙库" in text
    # And the reply says the scores are not comparable across libraries, because
    # one may be a rerank sigmoid and the other an RRF score.
    assert "不能互相比较" in text


def test_a_multi_library_search_does_not_let_one_library_bury_the_other(
        client, headers):
    """Rank-interleaved, not score-merged.

    A reranked library's scores are sigmoids in 0..1; a library searched without
    a reranker falls back to RRF's ~0.016. A global descending sort therefore
    puts every row of the reranked library first and the other library disappears
    from a top-5 -- an artefact of two scales, not of relevance. Interleaving by
    rank keeps both represented.
    """
    load(client, "embed-model")
    big = make_kb(client, "大库")
    for index in range(4):
        ok(client, headers, "kb_add_document", {
            "kb": big, "name": f"盘点{index}.txt",
            "text": f"仓库盘点制度第 {index} 条：盘点差异率超过千分之五时必须复核。"})
    wait_ready(client, big)
    small = make_kb(client, "小库")
    ok(client, headers, "kb_add_document", {
        "kb": small, "name": "小库盘点.txt",
        "text": "仓库盘点制度补充说明：差异必须当日上报。"})
    wait_ready(client, small)

    text, structured = ok(client, headers, "kb_search",
                          {"query": "盘点差异率", "top_k": 4})
    sources = {row["kb"] for row in structured["results"]}
    assert sources == {"大库", "小库"}, [row["kb"] for row in structured["results"]]


def test_kb_search_refuses_an_ambiguous_or_unknown_library(client, headers):
    seed(client, headers, "甲库")
    seed(client, headers, "乙库")
    message = fails(client, headers, "kb_search", {"query": "盘点", "kb": "丙库"})
    assert "丙库" in message
    assert "甲库" in message  # the error lists what does exist


def test_kb_search_refuses_an_empty_query(client, headers):
    kb = seed(client, headers)
    assert "query" in fails(client, headers, "kb_search", {"query": "  ", "kb": kb})


def test_kb_search_caps_top_k(client, headers):
    kb = seed(client, headers)
    assert "top_k" in fails(client, headers, "kb_search",
                            {"query": "盘点", "kb": kb, "top_k": 21})
    assert "top_k" in fails(client, headers, "kb_search",
                            {"query": "盘点", "kb": kb, "top_k": 0})
    # 20 is allowed (the cap itself), and the reply honours it.
    text, structured = ok(client, headers, "kb_search",
                          {"query": "盘点", "kb": kb, "top_k": 20})
    assert len(structured["results"]) <= 20


def test_kb_search_on_an_empty_library_says_so(client, headers):
    load(client, "embed-model")
    kb = make_kb(client, "空库")
    text, structured = ok(client, headers, "kb_search", {"query": "盘点", "kb": kb})
    assert structured["results"] == []
    assert "没有检索到" in text


# ---------------------------------------------------------------------------
# kb_read
# ---------------------------------------------------------------------------
def test_kb_read_returns_the_chunk_and_its_neighbours(client, headers):
    kb = seed(client, headers)
    _, searched = ok(client, headers, "kb_search", {"query": "盘点差异率", "kb": kb})
    chunk_id = searched["results"][0]["chunk_id"]

    text, structured = ok(client, headers, "kb_read", {"chunk_id": chunk_id})
    window = structured["chunks"]
    assert chunk_id in [row["chunk_id"] for row in window]
    assert structured["chunk_id"] == chunk_id
    # The requested chunk is marked so a reader can find it in the window.
    assert "←" in text
    for row in window:
        assert row["kb"] == structured["kb"]


def test_kb_read_neighbors_is_bounded(client, headers):
    kb = seed(client, headers)
    _, searched = ok(client, headers, "kb_search", {"query": "盘点", "kb": kb})
    chunk_id = searched["results"][0]["chunk_id"]
    assert "neighbors" in fails(client, headers, "kb_read",
                                {"chunk_id": chunk_id, "neighbors": 4})
    # 0 means the chunk alone, and is a legitimate request.
    _, structured = ok(client, headers, "kb_read", {"chunk_id": chunk_id, "neighbors": 0})
    assert [r["chunk_id"] for r in structured["chunks"]] == [chunk_id]


def test_kb_read_suggests_re_searching_for_a_stale_id(client, headers):
    seed(client, headers)
    message = fails(client, headers, "kb_read", {"chunk_id": "0123456789abcdef:0"})
    assert "kb_search" in message


# ---------------------------------------------------------------------------
# kb_add_document / kb_document_status / kb_list_documents
# ---------------------------------------------------------------------------
def test_kb_add_document_from_text_returns_before_indexing_finishes(client, headers):
    load(client, "embed-model")
    kb = make_kb(client, "写入库")
    text, structured = ok(client, headers, "kb_add_document",
                          {"kb": kb, "text": "盘点制度：每季度一次。", "name": "制度.md"})
    assert structured["status"] == "queued"
    assert structured["doc_id"]
    assert structured["name"] == "制度.md"
    # The tool returned without waiting; the document exists and is in flight.
    assert "queued" in text
    docs = wait_ready(client, kb)
    assert docs[0]["status"] == "ready"
    assert docs[0]["chunks"] >= 1


def test_a_document_added_through_the_tool_is_searchable(client, headers):
    kb = seed(client, headers, "可检索库")
    ok(client, headers, "kb_add_document", {
        "kb": kb, "name": "补充.txt",
        "text": "消防通道每半年检查一次，堵塞必须当天清理。"})
    wait_ready(client, kb)
    text, structured = ok(client, headers, "kb_search",
                          {"query": "消防通道", "kb": kb})
    assert any("消防通道" in (row["text"] or "") for row in structured["results"]), text


def test_kb_add_document_refuses_both_sources_at_once(client, headers):
    load(client, "embed-model")
    kb = make_kb(client, "二选一库")
    message = fails(client, headers, "kb_add_document",
                    {"kb": kb, "path": "/tmp/x.png", "text": "hi", "name": "x.txt"})
    assert "path" in message and "text" in message


def test_kb_add_document_refuses_text_without_a_name(client, headers):
    load(client, "embed-model")
    kb = make_kb(client, "无名库")
    assert "name" in fails(client, headers, "kb_add_document",
                           {"kb": kb, "text": "内容"})


def test_kb_add_document_refuses_a_type_it_cannot_parse(client, headers):
    load(client, "embed-model")
    kb = make_kb(client, "类型库")
    message = fails(client, headers, "kb_add_document",
                    {"kb": kb, "text": "内容", "name": "report.docx"})
    assert ".docx" in message or "不支持" in message


def test_kb_document_status_reports_progress_and_then_ready(client, headers):
    load(client, "embed-model")
    kb = make_kb(client, "状态库")
    _, added = ok(client, headers, "kb_add_document",
                  {"kb": kb, "text": "盘点制度。", "name": "s.txt"})
    text, structured = ok(client, headers, "kb_document_status",
                          {"kb": kb, "doc_id": added["doc_id"]})
    assert structured["document"]["id"] == added["doc_id"]
    assert structured["document"]["status"] in ("queued", "parsing", "embedding", "ready")
    wait_ready(client, kb)
    text, structured = ok(client, headers, "kb_document_status",
                          {"kb": kb, "doc_id": added["doc_id"]})
    assert structured["document"]["status"] == "ready"
    assert "ready" in text


def test_kb_document_status_refuses_an_unknown_doc_id_with_a_way_forward(client, headers):
    load(client, "embed-model")
    kb = make_kb(client, "状态库")
    message = fails(client, headers, "kb_document_status",
                    {"kb": kb, "doc_id": "0" * 32})
    assert "kb_list_documents" in message


def test_kb_list_documents_lists_every_document_with_its_status(client, headers):
    kb = seed(client, headers, "清单库")
    text, structured = ok(client, headers, "kb_list_documents", {"kb": kb})
    names = {d["name"] for d in structured["documents"]}
    assert names == {"制度.txt", "差异.txt"}
    assert all(d["status"] == "ready" for d in structured["documents"])
    assert "制度.txt" in text


def test_a_library_that_does_not_exist_is_refused_by_every_tool_that_names_one(
        client, headers):
    load(client, "embed-model")
    make_kb(client, "存在的库")
    for name, args in (
        ("kb_list_documents", {"kb": "无此库"}),
        ("kb_add_document", {"kb": "无此库", "text": "x", "name": "x.txt"}),
        ("kb_document_status", {"kb": "无此库", "doc_id": "0" * 32}),
        ("kb_search", {"query": "x", "kb": "无此库"}),
    ):
        message = fails(client, headers, name, args)
        assert "无此库" in message, name


# ---------------------------------------------------------------------------
# ocr_read
# ---------------------------------------------------------------------------
def test_ocr_read_on_an_image_returns_the_lines(client, headers):
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "shot.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((OCR_IMG / "ui_status.png").read_bytes())

    text, structured = ok(client, headers, "ocr_read", {"path": str(target)})
    assert structured["kind"] == "image"
    assert structured["ocr"] is True
    assert structured["text"]
    assert structured["text"] in text
    assert "OCR" in text
    # The mock invents three lines; a real run would too, and either way the
    # text is the lines in reading order.
    assert len(structured["text"].splitlines()) >= 1


def test_ocr_read_without_an_ocr_model_says_so_instead_of_returning_nothing(
        client, headers):
    """MYS-2657: an unloaded OCR model is loaded instead of skipped.

    The old answer -- a sentence saying the model is missing -- is still the
    right answer when there is nothing on disk to load, or when the operator
    turned on-demand loading off. With it on (the fixture opts in), an agent calling
    ``ocr_read`` after an idle unload gets the text, not an instruction to go and
    press a button.
    """
    target = Path(client.app.state.agents.data_root) / "inbox" / "shot.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((OCR_IMG / "ui_status.png").read_bytes())
    text, structured = ok(client, headers, "ocr_read", {"path": str(target)})
    assert structured["ocr"] is True, "the model should have been loaded on demand"
    assert structured["text"] in text


def test_ocr_read_with_auto_load_off_says_the_model_is_missing(client, headers):
    """The sentence the previous test used to assert, on the path that still gives it."""
    client.post("/api/settings", json={"aux_auto_load": False})
    target = Path(client.app.state.agents.data_root) / "inbox" / "shot.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((OCR_IMG / "ui_status.png").read_bytes())
    text, structured = ok(client, headers, "ocr_read", {"path": str(target)})
    assert structured["ocr"] is False
    assert "OCR" in text and ("没有加载" in text or "未加载" in text)


def test_ocr_read_on_a_text_pdf_takes_the_text_layer_page_by_page(client, headers):
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "text.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((KB_DATA / "text.pdf").read_bytes())

    text, structured = ok(client, headers, "ocr_read", {"path": str(target)})
    assert structured["kind"] == "pdf"
    assert structured["total_pages"] == 2
    assert [p["page"] for p in structured["pages"]] == [1, 2]
    # A page with a text layer is labelled as such: the source of every page is
    # part of the answer.
    assert all(p["source"] == "text" for p in structured["pages"])
    assert "文字层" in text


def test_ocr_read_on_a_mixed_pdf_marks_which_pages_needed_ocr(client, headers):
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "mixed.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((KB_DATA / "mixed.pdf").read_bytes())
    text, structured = ok(client, headers, "ocr_read", {"path": str(target)})
    sources = {p["source"] for p in structured["pages"]}
    assert "ocr" in sources and "text" in sources, structured["pages"]
    assert "OCR" in text and "文字层" in text


def test_ocr_read_pages_argument_selects_a_range(client, headers):
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "text.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((KB_DATA / "text.pdf").read_bytes())
    _, structured = ok(client, headers, "ocr_read",
                       {"path": str(target), "pages": "2-2"})
    assert [p["page"] for p in structured["pages"]] == [2]


def test_a_non_contiguous_page_selection_keeps_the_original_page_numbers(client, headers):
    """``pages="1,2"`` on a 5-page document: the second page is 2, not 1+offset.

    The subset PDF is renumbered from 1, so a reader mapping back by "first page
    + index" would label the subset's page 2 as page 2 only by luck. The bug this
    pins: ``"1,5"`` used to report the fifth page as page 2, sending a reader
    checking a citation to the wrong page.
    """
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "five.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_five_page_pdf())

    text, structured = ok(client, headers, "ocr_read",
                          {"path": str(target), "pages": "1,5"})
    assert structured["total_pages"] == 5
    assert [p["page"] for p in structured["pages"]] == [1, 5]
    assert "1、5 页" in text


def test_a_contiguous_selection_is_described_as_a_range(client, headers):
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "five.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_five_page_pdf())
    text, structured = ok(client, headers, "ocr_read",
                          {"path": str(target), "pages": "2-4"})
    assert [p["page"] for p in structured["pages"]] == [2, 3, 4]
    assert "2–4 页" in text


def test_a_pdf_over_the_default_window_says_what_it_left_out(client, headers):
    """The default is the first 20 pages; a 30-page file must not look complete."""
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "thirty.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_blank_pdf(30))
    text, structured = ok(client, headers, "ocr_read", {"path": str(target)})
    assert structured["total_pages"] == 30
    assert [p["page"] for p in structured["pages"]] == list(range(1, 21))
    assert "默认只读前" in text and "pages" in text


def test_a_silently_clipped_page_range_says_so(client, headers):
    """The cap is stated, not applied behind the model's back."""
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "sixty.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_blank_pdf(60))
    text, structured = ok(client, headers, "ocr_read",
                          {"path": str(target), "pages": "1-60"})
    assert len(structured["pages"]) == mcp_tools.MAX_PDF_PAGES_PER_CALL
    assert "单次上限" in text or "上限" in text


def test_an_oversized_range_on_a_short_document_does_not_claim_clipping(
        client, headers):
    """Found on the board: ``pages="1-2000000000"`` on a 30-page file said
    "clipped to the first 50 pages, call again for the rest" -- but there was no
    rest, and the 50-page cap limited nothing. A false statement about what was
    read is worse than no statement."""
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "thirty2.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_blank_pdf(30))
    text, structured = ok(client, headers, "ocr_read",
                          {"path": str(target), "pages": "1-2000000000"})
    assert len(structured["pages"]) == 30
    assert "单次上限" not in text
    assert "本次读取 1–30 页" in text


def _blank_pdf(pages: int) -> bytes:
    """A PDF of ``pages`` blank pages, built with the vendored renderer."""
    import io

    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(200, 200)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _five_page_pdf() -> bytes:
    """Five pages of real text, so each page's text layer identifies it."""
    import io

    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument.new()
    for number in range(1, 6):
        doc.new_page(300, 300)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def test_ocr_read_refuses_a_page_range_outside_the_document(client, headers):
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "text.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((KB_DATA / "text.pdf").read_bytes())
    message = fails(client, headers, "ocr_read", {"path": str(target), "pages": "99"})
    assert "2" in message  # it says how many pages there really are


def test_ocr_read_refuses_an_unparseable_pages_argument(client, headers):
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "text.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((KB_DATA / "text.pdf").read_bytes())
    assert "pages" in fails(client, headers, "ocr_read",
                            {"path": str(target), "pages": "one-five"})


def test_ocr_read_refuses_a_text_file(client, headers):
    """``ocr_read`` is for images and PDFs; a .txt has no OCR to do."""
    target = Path(client.app.state.agents.data_root) / "inbox" / "notes.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("纯文本", encoding="utf-8")
    message = fails(client, headers, "ocr_read", {"path": str(target)})
    assert "图片" in message and "PDF" in message


def test_ocr_read_never_writes_to_a_knowledge_base(client, headers):
    """The card is explicit: this tool reads, it does not index."""
    load(client, "embed-model", "ocr-model")
    kb = make_kb(client, "不受影响的库")
    target = Path(client.app.state.agents.data_root) / "inbox" / "shot.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((OCR_IMG / "ui_status.png").read_bytes())
    ok(client, headers, "ocr_read", {"path": str(target)})
    docs = client.get(f"/api/apps/kb/{kb}/docs").json()["docs"]
    assert docs == []
    assert client.app.state.kb_store.load_chunks(kb) == []


# ---------------------------------------------------------------------------
# the inference records belong to the MCP caller, not the console
# ---------------------------------------------------------------------------
def test_a_search_records_its_inferences_as_mcp_calls(client, headers):
    """Embedding and rerank rows must say ``/mcp`` and name the calling key.

    The recording happens inside ``app/apps/kb/retrieval``, which serves the
    console too, so this is the property most likely to be silently lost.
    """
    kb = seed(client, headers, "记录库")
    load(client, "rerank-model")
    ok(client, headers, "kb_search", {"query": "盘点差异率", "kb": kb})

    rows = client.get("/api/inference-records", params={"limit": 100}).json()["items"]
    assert rows
    ours = [r for r in rows if r.get("actor_name") == "mcp-client"]
    assert ours, [r.get("actor_name") for r in rows]
    assert all(r["source"] == "/mcp" for r in ours)
    # And the console's own attribution is not polluted: no row from this call
    # may claim to be a console request.
    assert not [r for r in rows if r.get("source") == "/api/apps/kb"
                and r.get("actor_name") == "mcp-client"]


def test_an_ocr_call_records_one_row_per_page_as_mcp(client, headers):
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "shot.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((OCR_IMG / "ui_status.png").read_bytes())
    ok(client, headers, "ocr_read", {"path": str(target)})
    entries = client.get("/api/inference-records", params={"limit": 100}).json()["items"]
    ours = [r for r in entries if r.get("source") == "/mcp"]
    assert len(ours) >= 1
    assert all(r["actor_name"] == "mcp-client" for r in ours)


# ---------------------------------------------------------------------------
# ocr_read: the resource bounds
# ---------------------------------------------------------------------------
def test_a_huge_page_range_is_clipped_before_it_is_expanded(client, headers):
    """``pages="1-2000000000"`` is 11 characters and 2e9 integers.

    The old code expanded the range and then sliced to 50: seconds of CPU and
    gigabytes of RAM, on the event loop, from one tool call. Each range is now
    intersected with the document and the call budget before anything is
    materialised, so the cost is bounded by the page count, not the argument.
    """
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "text.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((KB_DATA / "text.pdf").read_bytes())

    started = time.monotonic()
    text, structured = ok(client, headers, "ocr_read",
                          {"path": str(target), "pages": "1-2000000000"})
    elapsed = time.monotonic() - started
    # Two pages in the document: the clip is total, and the read is the whole
    # document rather than the first 50 of a huge expansion.
    assert [p["page"] for p in structured["pages"]] == [1, 2]
    assert elapsed < 20.0, f"a clipped range took {elapsed:.1f}s"


def test_the_page_budget_is_spent_in_the_order_the_ranges_were_written():
    """First 50 pages *as asked*, not "the 50 lowest page numbers".

    ``"40-100,1-3"`` on a 100-page file: the first range takes the whole budget,
    so the answer is 40..89. Sorting the request and taking the lowest pages
    would silently answer a different question than the one that was asked.
    """
    selection = mcp_tools._parse_pages("40-100,1-3", total=100)
    assert selection == list(range(40, 90))
    assert len(selection) == mcp_tools.MAX_PDF_PAGES_PER_CALL
    # And a request that fits keeps every page it named, in ascending order.
    assert mcp_tools._parse_pages("40-45,1-3", total=100) == [
        1, 2, 3, 40, 41, 42, 43, 44, 45]


def test_a_page_range_past_the_last_page_is_refused_with_the_real_count():
    with pytest.raises(mcp_tools.ToolError) as exc:
        mcp_tools._parse_pages("99", total=2)
    assert "2" in str(exc.value)


def test_an_image_over_the_pixel_cap_is_refused_before_it_is_decoded(client, headers):
    """The upload route's own check, applied to the read path too.

    A 50 MiB PNG can be 170 Mpx; decoding it costs >500 MB of RGB. ``ocr_read``
    used to skip ``validate_upload`` entirely, so this was the one way into the
    image parser that bypassed the cap.
    """
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "huge.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_png_with_pixel_count(9000, 9000))  # 81 Mpx

    message = fails(client, headers, "ocr_read", {"path": str(target)})
    assert "Mpx" in message or "像素" in message, message


def test_a_document_over_the_upload_cap_is_refused_by_size_not_by_memory(
        client, headers, monkeypatch):
    """The 50 MiB cap is the read's own bound, so the refusal costs no more than
    ``limit + 1`` bytes of buffer."""
    from app.apps.kb import parse as kb_parse

    monkeypatch.setattr(kb_parse, "MAX_FILE_BYTES", 4096)
    target = Path(client.app.state.agents.data_root) / "inbox" / "big.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8192)
    message = fails(client, headers, "ocr_read", {"path": str(target)})
    assert "超过上限" in message


def test_ocr_read_refuses_a_path_outside_the_allowlist_without_naming_the_server(
        client, headers):
    message = fails(client, headers, "ocr_read", {"path": "/etc/passwd"})
    assert "不允许" in message
    # The roots are named relatively: a refusal is not a map of the box.
    assert str(client.app.state.agents.data_root) not in message


def _png_with_pixel_count(width: int, height: int) -> bytes:
    """A PNG whose *header* claims ``width x height`` but whose body is tiny.

    Enough for the pixel check (which reads the header and stops) without
    allocating a real 81-megapixel image in the test.
    """
    import binascii
    import zlib

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    # One row of the declared width, filtered with type 0.
    row = b"\x00" + b"\x00" * (width * 3)
    body = zlib.compress(row)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", body)
            + chunk(b"IEND", b""))


# ---------------------------------------------------------------------------
# transcribe_audio
# ---------------------------------------------------------------------------
def _audio_fixture(client, name: str = "meeting.wav", seconds: float = 75.0) -> Path:
    target = Path(client.app.state.agents.data_root) / "inbox" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(wav_bytes(seconds))
    return target


def test_transcribe_audio_returns_the_text_and_the_timed_segments(client, headers):
    load(client, "asr-model")
    target = _audio_fixture(client)

    text, structured = ok(client, headers, "transcribe_audio", {"path": str(target)})
    assert structured["kind"] == "audio"
    assert structured["duration"] == pytest.approx(75.0, abs=0.05)
    assert structured["text"]
    # Three 30 s segments with contiguous timestamps -- the mock cuts audio the
    # way the real backend does, so this is the real segmentation contract.
    assert len(structured["segments"]) == 3
    for index, segment in enumerate(structured["segments"]):
        assert segment["text"]
        if index:
            assert segment["start"] == pytest.approx(
                structured["segments"][index - 1]["end"], abs=1e-6)
    assert structured["segments"][0]["start"] == 0.0
    # The model reads the whole text first, then the timed list.
    assert structured["text"] in text
    assert "[00:00–00:30]" in text
    assert "分段：" in text
    assert structured["usage"]["total_tokens"] > 0


def test_transcribe_audio_is_recorded_as_an_mcp_inference(client, headers):
    load(client, "asr-model")
    target = _audio_fixture(client)
    ok(client, headers, "transcribe_audio", {"path": str(target)})

    rows = client.get("/api/inference-records", params={"limit": 50}).json()["items"]
    ours = [r for r in rows if r.get("source") == "/mcp"]
    assert ours, [r.get("source") for r in rows]
    assert all(r["actor_name"] == "mcp-client" for r in ours)
    # The transcript is what was recorded, not an empty row.
    assert all(r["model"] == "asr-model" for r in ours)


def test_transcribe_audio_loads_the_asr_model_on_demand(client, headers):
    """MYS-2657: transcription is the point of the call, so the model is loaded.

    Preferring ``qwen3-asr-0.6b`` among *unloaded* candidates is the design's
    tie-break (faster and smaller); this fixture has only that one, which is the
    common case on the board.
    """
    target = _audio_fixture(client)
    text, structured = ok(client, headers, "transcribe_audio", {"path": str(target)})
    assert structured["model"] == "asr-model"
    assert structured["segments"], text


def test_transcribe_audio_with_auto_load_off_names_what_to_load(client, headers):
    """No model available is a sentence about which one to load."""
    client.post("/api/settings", json={"aux_auto_load": False})
    target = _audio_fixture(client)
    message = fails(client, headers, "transcribe_audio", {"path": str(target)})
    assert "未加载" in message or "自动加载已关闭" in message
    assert "qwen3-asr" in message


def test_transcribe_audio_refuses_audio_over_thirty_minutes(client, headers):
    """The worker's own ceiling, reached before any NPU time is spent.

    The fixture is 8 kHz -- half the bytes of the 16 kHz default -- so 31 minutes
    stays under the 50 MiB file cap and the *duration* is what refuses it. That
    ordering is the point: size and length are separate limits, and a file that
    trips the second must not be reported as tripping the first.
    """
    load(client, "asr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "long.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(wav_bytes(31 * 60, rate=8000))
    assert target.stat().st_size < 50 * 1024 * 1024

    message = fails(client, headers, "transcribe_audio", {"path": str(target)})
    assert "30 分钟" in message or "30" in message, message
    assert "MB" not in message


def test_transcribe_audio_refuses_a_path_outside_the_allowlist(client, headers):
    load(client, "asr-model")
    message = fails(client, headers, "transcribe_audio", {"path": "/etc/passwd"})
    assert "不允许" in message


def test_transcribe_audio_refuses_a_file_that_is_not_audio(client, headers):
    load(client, "asr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "notes.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("纯文本", encoding="utf-8")
    message = fails(client, headers, "transcribe_audio", {"path": str(target)})
    assert "音频" in message


def test_transcribe_audio_asks_for_a_required_path(client, headers):
    assert "path" in fails(client, headers, "transcribe_audio", {})


def test_a_speechless_recording_reports_no_language_not_the_word_none():
    """The model answers ``language None`` on audio with no speech.

    Found on the board: a 220 Hz test tone came back with
    ``"language": "None"`` -- a *string*, because the worker reads the model's
    own preamble verbatim. A chat transcript saying the language is "None" is
    worse than one saying nothing.
    """
    assert mcp_tools._reported_language("None") is None
    assert mcp_tools._reported_language("none") is None
    assert mcp_tools._reported_language(" null ") is None
    assert mcp_tools._reported_language("") is None
    assert mcp_tools._reported_language(None) is None
    # A real answer is passed through, including the multi-language form.
    assert mcp_tools._reported_language("Chinese") == "Chinese"
    assert mcp_tools._reported_language("Chinese,English") == "Chinese,English"


async def _drain(frames):
    from app.mcp.tools import _collect_asr

    return await _collect_asr(_agen(frames))


async def _agen(items):
    for item in items:
        yield item


def test_collect_asr_normalises_the_language_and_keeps_the_segments():
    import asyncio

    frames = [
        {"op": "meta", "duration": 65.0, "segments_total": 3, "language": None},
        {"op": "segment", "id": 0, "start": 0.0, "end": 30.0, "text": "你好"},
        {"op": "segment", "id": 1, "start": 30.0, "end": 60.0, "text": "世界"},
        {"op": "done", "text": "你好 世界", "language": "None", "duration": 65.0,
         "prompt_tokens": 890, "completion_tokens": 9},
    ]
    out = asyncio.run(_drain(frames))
    assert out["language"] is None
    assert out["text"] == "你好 世界"
    assert [s["text"] for s in out["segments"]] == ["你好", "世界"]
    assert out["prompt_tokens"] == 890


def test_transcribe_audio_refuses_a_language_the_model_does_not_have(client, headers):
    load(client, "asr-model")
    target = _audio_fixture(client)
    message = fails(client, headers, "transcribe_audio",
                    {"path": str(target), "language": "Klingon"})
    assert "不支持的语言" in message
    # And a real one is accepted (echoed into the reply).
    _, structured = ok(client, headers, "transcribe_audio",
                       {"path": str(target), "language": "Chinese"})
    assert structured["language"] == "Chinese"


def test_transcribe_audio_refuses_undecodable_audio(client, headers):
    load(client, "asr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "broken.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"not a wav at all")
    message = fails(client, headers, "transcribe_audio", {"path": str(target)})
    assert "转写失败" in message or "音频" in message


# ---------------------------------------------------------------------------
# the blocking work is off the event loop
# ---------------------------------------------------------------------------
def test_the_library_load_runs_in_a_worker_thread():
    """``load_chunks`` + ``aligned_vectors`` + ``Bm25Index.build`` are O(library).

    A 20 000-chunk library is seconds of parsing and tokenising; on the event
    loop that is every other request stalled, including somebody's token stream.
    The tool must hand the whole group to ``asyncio.to_thread``.
    """
    import asyncio
    import threading

    from app.mcp import tools as tools_mod

    seen: list[str] = []

    class _Store:
        def load_chunks(self, kb_id):
            seen.append(threading.current_thread().name)
            return [{"id": "c1", "text": "盘点"}]

        def aligned_vectors(self, kb_id, chunks):
            return None

    class _Kb:
        id = "kb1"
        needs_reindex = False

    class _State:
        kb_bm25: dict = {}

    class _App:
        state = _State()

    class _Req:
        app = _App()

    original = tools_mod._store
    tools_mod._store = lambda request: _Store()
    try:
        chunks, vectors, index = asyncio.run(
            asyncio.to_thread(tools_mod._load_library, _Req(), _Kb()))
    finally:
        tools_mod._store = original
    assert seen and seen[0] != threading.main_thread().name
    assert chunks and vectors is None and index is not None


def test_the_page_count_never_expands_the_requested_range(monkeypatch):
    """A huge range must be clipped, not built and then sliced.

    The guard is structural: ``_parse_pages`` may not call ``range`` with an
    unbounded end. This pins it by giving it a range whose expansion would take
    minutes and asserting the answer is the document's own page window.
    """
    started = time.monotonic()
    pages = mcp_tools._parse_pages("1-999999999999", total=7)
    assert pages == list(range(1, 8))
    assert time.monotonic() - started < 1.0


# ---------------------------------------------------------------------------
# the concurrency bound on the two NPU-heavy tools
# ---------------------------------------------------------------------------
def test_the_heavy_pool_refuses_instead_of_queueing():
    """Three concurrent OCR calls on a two-slot pool: the third is told to retry.

    Tested on the pool itself rather than through two real concurrent calls --
    ``TestClient`` serialises them, so the HTTP-level version would pass whether
    or not the bound exists.
    """
    pool = mcp_tools._HeavyPool(2)
    with pool.slot("OCR "):
        with pool.slot("OCR "):
            with pytest.raises(mcp_tools.ToolError) as exc:
                with pool.slot("OCR "):
                    pass  # pragma: no cover - the refusal happens on entry
            assert "稍后重试" in str(exc.value)
    # Released: two more fit again.
    with pool.slot("OCR "):
        with pool.slot("OCR "):
            assert pool.in_flight == 2
    assert pool.in_flight == 0


def test_the_pool_releases_its_slot_when_the_tool_fails():
    pool = mcp_tools._HeavyPool(1)
    with pytest.raises(mcp_tools.ToolError):
        with pool.slot("OCR "):
            raise mcp_tools.ToolError("boom")
    assert pool.in_flight == 0
    with pool.slot("OCR "):  # a failure must not leak the slot
        assert pool.in_flight == 1


def test_the_shipped_pool_is_two(client):
    """The card's number, pinned: OCR and transcription share two slots."""
    assert mcp_tools.MAX_HEAVY_CALLS == 2


# ---------------------------------------------------------------------------
# ocr_read's mode argument
# ---------------------------------------------------------------------------
def test_ocr_read_on_an_image_in_layout_mode_returns_markdown(client, headers):
    """The image path, through the layout branch: Markdown, not lines."""
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "page.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((OCR_IMG / "cn_notice.png").read_bytes())
    text, structured = ok(client, headers, "ocr_read",
                          {"path": str(target), "mode": "layout"})
    assert structured["mode"] == "layout"
    assert structured["ocr"] is True
    page = structured["pages"][0]
    assert page["markdown"], page
    # The page's Markdown is what the tool returns, and it is headed as layout
    # so a reader can tell the two shapes apart in a transcript.
    assert "版面模式" in text
    assert page["markdown"] in text


def test_ocr_read_layout_mode_leaves_a_text_layer_page_alone(client, headers):
    """A digital page is better read from its layer; layout must not change it.

    Re-OCRing the page would replace an exact answer with an approximate one, so
    the mode only applies to scanned pages -- and the note says so, because a
    caller who chose layout *for* its structure would otherwise wonder why
    nothing changed.
    """
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "text.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((KB_DATA / "text.pdf").read_bytes())
    text, structured = ok(client, headers, "ocr_read",
                          {"path": str(target), "mode": "layout"})
    assert all(p["source"] == "text" for p in structured["pages"])
    assert all("markdown" not in p for p in structured["pages"])
    assert "版面模式" in text and "文字层" in text


def test_ocr_read_on_a_mixed_pdf_in_layout_mode_uses_layout_for_scanned_pages(
        client, headers):
    """The mixed document: text pages as they are, scanned pages as Markdown."""
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "mixed.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((KB_DATA / "mixed.pdf").read_bytes())
    text, structured = ok(client, headers, "ocr_read",
                          {"path": str(target), "mode": "layout"})
    scanned = [p for p in structured["pages"] if p["source"] == "ocr"]
    digital = [p for p in structured["pages"] if p["source"] == "text"]
    assert scanned and digital, structured["pages"]
    for page in scanned:
        assert page["markdown"], page
        assert "# " in page["markdown"], "the mock page starts with a title"
    for page in digital:
        assert "markdown" not in page


def test_ocr_read_rejects_an_unknown_mode(client, headers):
    """A wrong mode is the caller's mistake, said as one -- before any NPU work."""
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "page.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((OCR_IMG / "cn_notice.png").read_bytes())
    result = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "ocr_read",
                   "arguments": {"path": str(target), "mode": "structure"}}})
    body = result.json()["result"]
    assert body.get("isError") is True
    assert "layout" in body["content"][0]["text"]


def test_the_ocr_read_schema_lists_the_three_modes(client, headers):
    """The schema is what an agent reads; an enum is what keeps it in bounds.

    Three modes since MYS-2664 added ``vl``. The *description* is where a model
    learns to pick one, so it must say what ``vl`` is for and what it costs --
    an agent that only sees the enum will choose the slow mode for a screenshot.
    """
    listing = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).json()
    tool = next(t for t in listing["result"]["tools"] if t["name"] == "ocr_read")
    mode = tool["inputSchema"]["properties"]["mode"]
    assert mode["enum"] == ["lines", "layout", "vl"]
    describe = tool["description"] + mode["description"]
    assert "layout" in describe
    assert "vl" in describe and "HTML" in describe
    # The two things that decide whether it is worth the wait are stated.
    assert "PaddleOCR-VL" in describe
    assert "慢" in describe


def test_ocr_read_without_a_mode_defaults_to_lines(client, headers):
    """Absent means lines: the tool's behaviour must not change under existing callers."""
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "page.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((OCR_IMG / "ui_status.png").read_bytes())
    text, structured = ok(client, headers, "ocr_read", {"path": str(target)})
    assert structured.get("mode") == "lines"
    assert "版面模式" not in text


def test_ocr_read_in_vl_mode_uses_the_vlm_and_returns_html_tables(client, headers):
    """``mode: "vl"``: two models, one page, and a table that is HTML.

    The mock's VL answer to ``Table Recognition:`` is OTSL, so this asserts the
    whole chain the card asks for: the region gets its own instruction, the
    answer is converted to HTML with spans, and the page's Markdown is what the
    tool returns.
    """
    load(client, "ocr-model", "paddleocr-vl-1.5")
    target = Path(client.app.state.agents.data_root) / "inbox" / "page.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((OCR_IMG / "cn_notice.png").read_bytes())

    text, structured = ok(client, headers, "ocr_read",
                          {"path": str(target), "mode": "vl"})
    assert structured["mode"] == "vl"
    assert structured["ocr"] is True
    markdown = structured["pages"][0]["markdown"]
    assert markdown
    # The mock page has a title, a body block and a table; the table's answer
    # is OTSL and must come back as a real table.
    assert "<table>" in markdown
    assert "<td>" in markdown
    # And the tool says which mode produced it, so a transcript is readable.
    assert "VL" in text


def test_ocr_read_vl_without_the_vlm_refuses_and_says_which_model(client, headers):
    """The card's "任意一个没有加载时返回 409，提示要加载哪一个".

    Refused rather than silently downgraded: a caller who asked for ``vl`` wants
    the table structure ``layout`` cannot give, so answering with ``layout``
    would be answering a different question.
    """
    load(client, "ocr-model")
    target = Path(client.app.state.agents.data_root) / "inbox" / "page.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((OCR_IMG / "cn_notice.png").read_bytes())

    message = fails(client, headers, "ocr_read",
                    {"path": str(target), "mode": "vl"})
    assert "PaddleOCR-VL" in message
    assert "layout" in message


def test_ocr_read_refuses_an_unknown_mode():
    """The tool's own validation, which is what an agent's typo hits."""
    with pytest.raises(Exception) as caught:  # ToolError, asserted by message
        _mode_gate("structure")
    assert "lines" in str(caught.value) and "vl" in str(caught.value)


def _mode_gate(mode: str) -> None:
    """The three lines of ``ocr_read`` that validate ``mode``, isolated.

    Duplicating the rule here would be wrong; this calls the tool with a path
    that does not exist and relies on the mode check running first. If the check
    ever moves after the read, the error message changes and this test says so.
    """
    import asyncio as _asyncio

    async def call() -> None:
        class _Request:
            app = type("A", (), {"state": type("S", (), {})()})()

        await mcp_tools.ocr_read(_Request(), {"path": "/nonexistent", "mode": mode},
                                 {"shim": None, "actor": {}})

    _asyncio.run(call())


def test_kb_read_neighbours_stay_inside_the_document(client, headers):
    """Each seeded document is one chunk, so its window is itself alone.

    The window used to be taken from the knowledge base's flat chunk list, which
    made a one-chunk note "neighbour" the last chunk of an unrelated document
    (found on the board in the v0.6.29 E2E run, MYS-2682).
    """
    kb = seed(client, headers)
    _, searched = ok(client, headers, "kb_search", {"query": "盘点差异率", "kb": kb})
    for row in searched["results"]:
        _, structured = ok(client, headers, "kb_read", {"chunk_id": row["chunk_id"], "neighbors": 3})
        doc = row["chunk_id"].rsplit(":", 1)[0]
        assert {c["chunk_id"].rsplit(":", 1)[0] for c in structured["chunks"]} == {doc}


def test_kb_search_text_names_the_chunk_id_kb_read_needs(client, headers):
    """Most MCP clients hand the model only the text content, so the id kb_read
    takes has to be in it, not only in structuredContent."""
    kb = seed(client, headers)
    text, searched = ok(client, headers, "kb_search", {"query": "盘点", "kb": kb})
    for row in searched["results"]:
        assert f"chunk_id={row['chunk_id']}" in text
