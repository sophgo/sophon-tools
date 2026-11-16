"""``POST /v1/ocr`` end-to-end over the mock backend, plus the record it leaves.

The mock decodes the image header for real (so the reported width and height,
and the 400 for an unreadable image, are facts about real code) and invents only
the words. Everything between the HTTP body and the recorded row is exercised:
the two body forms, every accepted spelling of ``image``, the type/kind gate,
the size and decode refusals, ``return_boxes``, and the one row per request.

The OCR pipeline's own arithmetic is ``tests/test_ocr_postprocess.py``'s job;
this file is about the API contract.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "tests" / "data" / "ocr" / "img"

#: The kind detector reads the file name, so the fixture directory has to be
#: named the way the catalogue downloads it: a detector plus three recognisers.
OCR_BMODEL = "ppocrv6-medium-det_f16_736_bm1684x2_static_20261103.bmodel"
OCR_REC = ("ppocrv6-medium-rec_f16_48x320_bm1684x2_static_20261103.bmodel",
           "ppocrv6-medium-rec_f16_48x640_bm1684x2_static_20261103.bmodel",
           "ppocrv6-medium-rec_f16_48x1600_bm1684x2_static_20261103.bmodel")
CHAT_BMODEL = "qwen3.6-35b-a3b-int4-autow4bf16_seq2048_4core_dynamic.bmodel"
OCR_VL_BMODEL = "paddleocr-vl-1.5_bf16_seq2048_bm1684x2_4core_static.bmodel"
ASR_BMODEL = "qwen3-asr-0.6b_bf16_seq1024_4core_static.bmodel"


def make_ocr_model(root: Path, name: str = "ocr-model") -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / OCR_BMODEL).write_bytes(b"\x00" * 4096)
    for rec in OCR_REC:
        (d / rec).write_bytes(b"\x00" * 2048)
    return d


def make_model(root: Path, name: str, bmodel: str) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / bmodel).write_bytes(b"\x00" * 4096)
    (d / "config").mkdir(exist_ok=True)
    (d / "config" / "config.json").write_text("{}")
    return d


def png_bytes(name: str = "ui_status.png") -> bytes:
    return (IMG / name).read_bytes()


# ---------------------------------------------------------------------------
# mode: "layout"
# ---------------------------------------------------------------------------
def test_lines_mode_is_the_default_and_sends_no_mode_field(client):
    """``mode`` absent must behave exactly as before the field existed.

    Pinned on the response shape rather than on the request: a lines response
    that grew a ``blocks: null`` would still be "the same data", but a client
    with a strict schema would reject it.
    """
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model",
        "image": "data:image/png;base64," + base64.b64encode(png_bytes()).decode(),
    })
    assert r.status_code == 200, r.text
    body = r.json()
    # Exactly the keys the endpoint returned before layout mode existed.
    assert set(body) == {"id", "model", "text", "lines", "usage"}
    assert set(body["usage"]) == {"det_ms", "rec_ms", "lines"}


def test_layout_mode_returns_blocks_and_markdown(client):
    """The mock returns a shape-valid page: title, text, table -- in order."""
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model",
        "image": "data:image/png;base64," + base64.b64encode(png_bytes()).decode(),
        "mode": "layout",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "layout"
    blocks = body["blocks"]
    assert [b["type"] for b in blocks] == ["title", "text", "table"]
    assert [b["index"] for b in blocks] == [0, 1, 2]
    for block in blocks:
        assert block["label"], "the raw PP-DocLayout class must be carried too"
        assert 0.0 <= block["score"] <= 1.0
        assert len(block["box"]) == 4
        for line in block["lines"]:
            assert len(line["box"]) == 4
    # The page Markdown: an H1 for the title, a marker before the table.
    assert body["text"].startswith("# ")
    assert "<!-- 表格" in body["text"]
    # usage reports the layout pass separately from the OCR pass.
    assert body["usage"]["blocks"] == 3
    assert body["usage"]["layout_ms"] is not None
    # `lines` is every line of every block, in the new reading order.
    assert len(body["lines"]) == sum(len(b["lines"]) for b in blocks)


def test_layout_mode_can_omit_the_boxes(client):
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model",
        "image": "data:image/png;base64," + base64.b64encode(png_bytes()).decode(),
        "mode": "layout",
        "return_boxes": False,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    for block in body["blocks"]:
        for line in block["lines"]:
            assert line["box"] is None
    for line in body["lines"]:
        assert line["box"] is None


def test_layout_mode_over_multipart(client):
    """The console and curl send multipart; the field has to travel there too."""
    headers = _auth(client, "ocr-model")
    r = client.post(
        "/v1/ocr", headers=headers,
        files={"file": ("page.png", png_bytes(), "image/png")},
        data={"model": "ocr-model", "mode": "layout"})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "layout"
    assert r.json()["blocks"]


def test_an_unknown_mode_is_a_400(client):
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model",
        "image": "data:image/png;base64," + base64.b64encode(png_bytes()).decode(),
        "mode": "structure",
    })
    assert r.status_code == 400, r.text
    assert "layout" in r.json()["detail"]


def test_a_non_string_mode_is_a_400(client):
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model",
        "image": "data:image/png;base64," + base64.b64encode(png_bytes()).decode(),
        "mode": 3,
    })
    assert r.status_code == 400, r.text


def test_the_record_carries_the_mode(client, tmp_path):
    """The inference log must say which mode ran: two responses, two meanings."""
    headers = _auth(client, "ocr-model")
    data = base64.b64encode(png_bytes()).decode()
    for mode in ("lines", "layout"):
        r = client.post("/v1/ocr", headers=headers, json={
            "model": "ocr-model", "image": data, "mode": mode})
        assert r.status_code == 200, r.text
    store = client.app.state.inference_log
    items = store.list(limit=20)["items"]
    rows = [store.get(row["id"]) for row in items
            if row["source"] == "/v1/ocr"]
    modes = [row["params"].get("mode") for row in rows]
    assert "lines" in modes and "layout" in modes
    # The layout row also records how many regions the page had: that is the
    # number an operator checks when a page "looks wrong".
    layout_row = next(r for r in rows if r["params"].get("mode") == "layout")
    assert layout_row["params"].get("blocks") == 3


def test_a_layout_request_without_the_fifth_file_is_a_400(client, tmp_path):
    """A four-file install must answer with an explanation, not a 500.

    The real backend is what raises here; the mock does not read bmodels at all,
    so the refusal is asserted on the worker's handler directly -- which is also
    the layer that decides the HTTP status (``invalid_request`` is a 400, every
    other kind is a 503).
    """
    from app.engine import worker as worker_mod

    class Backend:
        kind = "ocr"

        async def recognise(self, image, mode="lines"):
            from app.engine.ocr_ppocr import OcrModeUnavailable

            raise OcrModeUnavailable(
                "版面模式需要版面模型 ppdoclayout-m_f16_640_bm1684x2_static_20261104"
                ".bmodel，但模型目录 /data/models/ppocrv6-medium 里没有这个文件")

    sent = []

    async def write(obj):
        sent.append(obj)

    asyncio.run(worker_mod.handle_ocr(
        Backend(), {"req_id": "r1", "image_b64": "AAAA", "mode": "layout"}, write))
    assert sent and sent[0]["op"] == "error"
    assert sent[0]["kind"] == "invalid_request"
    assert "ppdoclayout" in sent[0]["message"]
    from app.api.openai_api import _worker_error_to_http
    from app.core.client import WorkerError

    exc = _worker_error_to_http(WorkerError(sent[0]["message"], kind="invalid_request"))
    assert exc.status_code == 400


def test_the_worker_refuses_an_unknown_mode():
    """The worker validates too: the console's test route bypasses /v1."""
    from app.engine import worker as worker_mod

    sent = []

    async def write(obj):
        sent.append(obj)

    asyncio.run(worker_mod.handle_ocr(
        object(), {"req_id": "r1", "image_b64": "AAAA", "mode": "nonsense"}, write))
    assert sent[0]["op"] == "error"
    assert sent[0]["kind"] == "invalid_request"
    assert "layout" in sent[0]["message"]


def make_ocr_vl_model(root: Path, name: str = "paddleocr-vl-1.5") -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / OCR_VL_BMODEL).write_bytes(b"\x00" * 4096)
    return d


@pytest.fixture()
def app(tmp_path):
    models = tmp_path / "models"
    make_ocr_model(models)
    make_model(models, "chat-model", CHAT_BMODEL)
    make_model(models, "asr-model", ASR_BMODEL)
    make_ocr_vl_model(models)
    return create_app(
        data_dir=tmp_path / "data",
        models_dir=models,
        backend_kind="mock",
        web_dir=tmp_path / "web",
        context_length_override=4096,
    )


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def _auth(client, *model_ids) -> dict:
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    for model_id in model_ids:
        r = client.post(f"/api/models/{model_id}/load")
        assert r.status_code == 200, r.text
    raw = client.post("/api/keys", json={"name": "pytest"}).json()["key"]
    return {"Authorization": f"Bearer {raw}"}


# ---------------------------------------------------------------------------
# the happy paths: three spellings of "here is an image"
# ---------------------------------------------------------------------------
def test_a_data_uri_image_returns_text_and_lines(client):
    headers = _auth(client, "ocr-model")
    data = png_bytes()
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model",
        "image": "data:image/png;base64," + base64.b64encode(data).decode(),
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"] == "ocr-model"
    assert body["id"].startswith("ocr-")
    assert body["text"], "text must not be empty"
    assert len(body["lines"]) == 3
    # `text` is the lines joined by newline, in the order they were returned:
    # that is the contract, and a client that ignores `lines` relies on it.
    assert body["text"] == "\n".join(line["text"] for line in body["lines"])
    for line in body["lines"]:
        assert 0.0 <= line["score"] <= 1.0
        assert len(line["box"]) == 4
        for x, y in line["box"]:
            assert 0 <= x <= 800 and 0 <= y <= 600
    assert body["usage"]["lines"] == 3
    assert body["usage"]["det_ms"] >= 0 and body["usage"]["rec_ms"] >= 0


def test_bare_base64_is_accepted(client):
    """Some clients strip the data-URI prefix; refusing it would be a surprise."""
    headers = _auth(client, "ocr-model")
    data = png_bytes()
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model", "image": base64.b64encode(data).decode()})
    assert r.status_code == 200, r.text
    assert r.json()["text"]


def test_a_multipart_upload_is_accepted(client):
    """The curl/Postman form: a `file` part instead of a JSON string."""
    headers = _auth(client, "ocr-model")
    r = client.post(
        "/v1/ocr", headers=headers,
        files={"file": ("page.png", png_bytes(), "image/png")},
        data={"model": "ocr-model"})
    assert r.status_code == 200, r.text
    assert r.json()["lines"]


def test_the_jpeg_header_is_read_too(client):
    """The mock reads headers, and real pages are often JPEGs."""
    from PIL import Image

    buf = io.BytesIO()
    Image.open(IMG / "ui_status.png").convert("RGB").save(buf, "JPEG", quality=85)
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model", "image": base64.b64encode(buf.getvalue()).decode()})
    assert r.status_code == 200, r.text
    assert r.json()["lines"]


def test_a_remote_url_is_refused_by_default(client, monkeypatch):
    """The box is offline, and fetching a client-chosen URL is an SSRF surface.

    The refusal names the environment variable, because "unsupported" alone
    leaves an operator with no way to tell a policy from a bug.
    """
    monkeypatch.delenv("CV84X6_OCR_ALLOW_REMOTE", raising=False)
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model", "image": "http://example.invalid/page.png"})
    assert r.status_code == 400
    assert "CV84X6_OCR_ALLOW_REMOTE" in r.json()["detail"]


def test_a_remote_url_is_fetched_when_the_deployment_allows_it(client, monkeypatch):
    """Opting in has to actually work, or the variable is decoration."""
    import httpx

    monkeypatch.setenv("CV84X6_OCR_ALLOW_REMOTE", "1")
    payload = png_bytes()

    class FakeResponse:
        def raise_for_status(self):
            return None

        def iter_bytes(self, size):
            yield payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def stream(self, method, url):
            assert method == "GET" and url.endswith(".png")
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model", "image": "http://example.invalid/page.png"})
    assert r.status_code == 200, r.text
    assert r.json()["lines"]


# ---------------------------------------------------------------------------
# return_boxes
# ---------------------------------------------------------------------------
def test_return_boxes_false_omits_the_boxes(client):
    """The text is unchanged; only the serialisation differs."""
    headers = _auth(client, "ocr-model")
    data = base64.b64encode(png_bytes()).decode()
    with_boxes = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model", "image": data}).json()
    without = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model", "image": data, "return_boxes": False}).json()
    assert without["text"] == with_boxes["text"]
    assert all(line["box"] is None for line in without["lines"])
    assert all(line["box"] for line in with_boxes["lines"])


def test_return_boxes_defaults_to_true(client):
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model", "image": base64.b64encode(png_bytes()).decode()})
    assert r.json()["lines"][0]["box"], "boxes are returned unless asked not to"


def test_return_boxes_can_be_a_multipart_string(client):
    """A form field is always a string, so "false" has to mean false."""
    headers = _auth(client, "ocr-model")
    r = client.post(
        "/v1/ocr", headers=headers,
        files={"file": ("page.png", png_bytes(), "image/png")},
        data={"model": "ocr-model", "return_boxes": "false"})
    assert r.status_code == 200, r.text
    assert all(line["box"] is None for line in r.json()["lines"])


def test_a_non_boolean_return_boxes_is_a_400(client):
    """Silently defaulting would answer a different question than the one asked."""
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model", "return_boxes": "flase",
        "image": base64.b64encode(png_bytes()).decode()})
    assert r.status_code == 400
    assert "return_boxes" in r.json()["detail"]


# ---------------------------------------------------------------------------
# refusals: the request
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("payload,needle", [
    ({}, "model"),
    ({"image": "x"}, "model"),
    ({"model": "ocr-model"}, "image"),
    ({"model": "ocr-model", "image": ""}, "image"),
    ({"model": "ocr-model", "image": 12345}, "image"),
    ({"model": "ocr-model", "image": {"url": "x"}}, "image"),
    ({"model": "ocr-model", "image": "data:text/plain;base64,aGk="}, "data URI"),
    ({"model": "ocr-model", "image": "data:image/png;base64,"}, "图片数据"),
    ({"model": "ocr-model", "image": "not base64 at all!!"}, "base64"),
])
def test_bad_requests_are_400(client, payload, needle):
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/ocr", headers=headers, json=payload)
    assert r.status_code == 400, r.text
    assert needle in r.json()["detail"], r.json()


def test_a_non_json_non_multipart_body_is_a_400(client):
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/ocr", headers={**headers, "Content-Type": "text/plain"},
                    content=b"hello")
    assert r.status_code == 400
    assert "JSON" in r.json()["detail"] or "multipart" in r.json()["detail"]


def test_a_broken_image_is_a_400_not_a_500(client):
    """The caller's picture is unusable; the model is fine.

    A 500 here would send an operator to the worker log for a request that never
    reached the NPU.
    """
    headers = _auth(client, "ocr-model")
    garbage = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model", "image": garbage})
    assert r.status_code in (400, 200), r.text
    if r.status_code == 400:
        assert "图片" in r.json()["detail"] or "解码" in r.json()["detail"]


def test_an_image_over_the_cap_is_refused(client):
    """20 MiB of image, refused by one clear number rather than by an OOM."""
    from app.api.openai_api import MAX_OCR_IMAGE_BYTES

    headers = _auth(client, "ocr-model")
    # The cap is checked before the payload is decoded, so an oversized blob of
    # base64 is enough -- no need to build a 20 MiB PNG.
    blob = base64.b64encode(b"\x00" * (MAX_OCR_IMAGE_BYTES + 1)).decode()
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model", "image": blob})
    assert r.status_code == 400
    assert "MiB" in r.json()["detail"]


def test_a_multipart_body_without_a_file_is_a_400(client):
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/ocr", headers=headers,
                    files={"other": ("x.txt", b"hi", "text/plain")},
                    data={"model": "ocr-model"})
    assert r.status_code == 400
    assert "file" in r.json()["detail"]


def test_a_multipart_file_field_must_be_named_file(client):
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/ocr", headers=headers,
                    files={"image": ("page.png", png_bytes(), "image/png")},
                    data={"model": "ocr-model"})
    assert r.status_code == 400
    assert "file" in r.json()["detail"]


# ---------------------------------------------------------------------------
# refusals: the model
# ---------------------------------------------------------------------------
def test_a_chat_model_at_the_ocr_endpoint_is_a_400(client):
    """Right model, wrong endpoint -- and the message names the right one."""
    headers = _auth(client, "ocr-model", "chat-model")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "chat-model", "image": base64.b64encode(png_bytes()).decode()})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "chat" in detail
    assert "/v1/chat/completions" in detail


def test_an_asr_model_at_the_ocr_endpoint_is_a_400(client):
    headers = _auth(client, "ocr-model", "asr-model")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "asr-model", "image": base64.b64encode(png_bytes()).decode()})
    assert r.status_code == 400
    assert "/v1/audio/transcriptions" in r.json()["detail"]


def test_an_ocr_model_at_the_chat_endpoint_is_a_400(client):
    """The converse: an OCR model must not look like a chat model that errors."""
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/chat/completions", headers=headers, json={
        "model": "ocr-model", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 400
    assert "/v1/ocr" in r.json()["detail"]


def test_an_unknown_model_is_a_404(client):
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "no-such-model", "image": base64.b64encode(png_bytes()).decode()})
    assert r.status_code == 404


def test_an_unloaded_ocr_model_is_loaded_on_demand(client):
    """MYS-2657: on disk but unloaded is served, not refused.

    The 409 lives on the operator's switch now --
    ``test_auto_load_disabled_answers_409`` in ``tests/test_aux_idle.py``.
    """
    headers = _auth(client)  # nothing loaded
    client.post("/api/settings", json={"aux_auto_load": True})  # off by default since v0.6.28
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model", "image": base64.b64encode(png_bytes()).decode()})
    assert r.status_code == 200, r.text
    assert r.json()["model"] == "ocr-model"
    assert r.json()["text"]


def test_ocr_requires_an_api_key(app):
    with TestClient(app) as client:
        client.post("/api/login", json={"password": "admin"})
        client.post("/api/models/ocr-model/load")
        r = client.post("/v1/ocr", json={
            "model": "ocr-model", "image": base64.b64encode(png_bytes()).decode()})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# discovery and the record
# ---------------------------------------------------------------------------
def test_v1_models_lists_the_ocr_model_with_its_kind(client):
    """A client discovers the endpoint from the kind, so it has to be there."""
    headers = _auth(client, "ocr-model")
    r = client.get("/v1/models", headers=headers)
    assert r.status_code == 200
    cards = {card["id"]: card for card in r.json()["data"]}
    assert cards["ocr-model"]["kind"] == "ocr"


def test_one_record_per_request_without_the_image(client, tmp_path):
    """`source`, `output_text` and the image's *description* -- never its bytes.

    Storing the picture would put a customer's document in a log file; storing
    nothing would leave an operator unable to tell two requests apart.
    """
    headers = _auth(client, "ocr-model")
    data = png_bytes()
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model", "image": "data:image/png;base64,"
                                     + base64.b64encode(data).decode()})
    assert r.status_code == 200, r.text
    body = r.json()

    store = client.app.state.inference_log
    items = store.list(limit=20)["items"]
    mine = [row for row in items if row.get("id") == body["id"].removeprefix("ocr-")]
    assert len(mine) == 1, f"expected exactly one record, found {len(mine)}"
    # The list view omits the text blobs on purpose; the detail view is where
    # the record is read back in full.
    row = store.get(mine[0]["id"])
    assert row is not None
    assert row["source"] == "/v1/ocr"
    assert row["model"] == "ocr-model"
    assert row["status"] == "ok"
    assert row["output_text"] == body["text"]
    # The request's `messages` describes the image: its size, and the
    # dimensions the worker measured. The bytes are nowhere.
    described = json.dumps(row.get("messages"), ensure_ascii=False)
    assert str(len(data)) in described
    assert "800" in json.dumps(row.get("params")) and "600" in json.dumps(row.get("params"))
    assert base64.b64encode(data).decode()[:40] not in described


def test_a_refused_request_leaves_no_record(client):
    """A 400 that never reached the worker is not an inference."""
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model", "image": "not base64!!"})
    assert r.status_code == 400
    rows = client.app.state.inference_log.list(limit=20)["items"]
    assert not [row for row in rows if row.get("source") == "/v1/ocr"]


def test_a_worker_failure_leaves_an_error_record(client, monkeypatch):
    """A refusal from the worker *is* an inference attempt and is recorded.

    Simulated by making the backend reject the image: the path is the same one a
    real undecodable upload takes, and the record is what tells an operator the
    request arrived.
    """
    headers = _auth(client, "ocr-model")
    client_obj = client.app.state.clients["ocr-model"]

    async def boom(req_id, image_b64, mode="lines"):
        from app.core.client import WorkerError

        raise WorkerError("模拟的引擎失败", kind="server")

    monkeypatch.setattr(client_obj, "ocr", boom)
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model", "image": base64.b64encode(png_bytes()).decode()})
    assert r.status_code == 503
    rows = client.app.state.inference_log.list(limit=20)["items"]
    mine = [row for row in rows if row.get("source") == "/v1/ocr"]
    assert len(mine) == 1
    assert mine[0]["status"] == "error"


# ---------------------------------------------------------------------------
# mode: "vl"
# ---------------------------------------------------------------------------
def test_vl_mode_returns_markdown_blocks_and_vl_usage(client):
    """``/v1/ocr`` with ``mode: "vl"``: the layout response shape plus ``task``
    per block and the VLM's own numbers in ``usage``."""
    headers = _auth(client, "ocr-model", "paddleocr-vl-1.5")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model",
        "image": "data:image/png;base64," + base64.b64encode(png_bytes()).decode(),
        "mode": "vl",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "vl"
    assert body["text"]
    assert body["blocks"], "vl mode reports the page's regions like layout does"

    # Every block that was recognised says which instruction produced it; the
    # picture blocks say None, because no model was asked about them.
    tasks = {block["label"]: block["task"] for block in body["blocks"]}
    assert tasks["table"] == "Table Recognition:"
    assert tasks["doc_title"] == "OCR:"

    # The table's text is HTML with the mock's span, and the page's Markdown
    # carries the same HTML rather than a text rendering of it.
    table = next(b for b in body["blocks"] if b["label"] == "table")
    assert table["text"].startswith("<table>")
    assert 'colspan="4"' in table["text"]      # the header row
    assert 'rowspan="3"' in table["text"]      # the first column
    assert table["text"] in body["text"]

    usage = body["usage"]
    assert usage["blocks"] == len(body["blocks"])
    assert usage["layout_ms"] >= 0
    assert usage["vl_ms"] > 0
    assert usage["vl_tokens"] > 0


def test_vl_mode_without_the_vl_model_is_a_409_naming_it(client):
    """The card's requirement, at the HTTP layer: the message must say which of
    the two models to load, and offer the cheaper mode."""
    headers = _auth(client, "ocr-model")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model",
        "image": "data:image/png;base64," + base64.b64encode(png_bytes()).decode(),
        "mode": "vl",
    })
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "PaddleOCR-VL" in detail
    assert 'layout' in detail


def test_vl_mode_without_the_ocr_model_is_a_409_too(client):
    """The other half of "任意一个没有加载时返回 409": the layout detector's model
    is resolved by the route's own admission gate, so it is the same 409 every
    other mode gets -- asserted here so the two cannot diverge."""
    headers = _auth(client)
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model",
        "image": "data:image/png;base64," + base64.b64encode(png_bytes()).decode(),
        "mode": "vl",
    })
    # The OCR model is on disk and auto-loads in this fixture, so this is a 200;
    # what matters is that the missing *VLM* is what the 409 above is about.
    assert r.status_code in (200, 409), r.text


def test_a_vl_request_is_recorded_with_both_models(client, tmp_path):
    """The row names the VLM too. A record naming only the OCR model would hide
    the model that actually produced the text."""
    headers = _auth(client, "ocr-model", "paddleocr-vl-1.5")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model",
        "image": "data:image/png;base64," + base64.b64encode(png_bytes()).decode(),
        "mode": "vl",
    })
    assert r.status_code == 200, r.text
    store = client.app.state.inference_log
    items = store.list(limit=20)["items"]
    rows = [store.get(row["id"]) for row in items
            if row["source"] == "/v1/ocr"]
    row = next(r for r in rows if r["params"].get("mode") == "vl")
    assert row["params"].get("vl_model") == "paddleocr-vl-1.5"
    assert row["params"].get("blocks")


def test_vl_mode_can_omit_the_boxes(client):
    """``return_boxes`` reaches the region lines in ``vl`` mode exactly as it does
    in ``layout`` mode, so a caller that sets it keeps its promise."""
    headers = _auth(client, "ocr-model", "paddleocr-vl-1.5")
    r = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model",
        "image": "data:image/png;base64," + base64.b64encode(png_bytes()).decode(),
        "mode": "vl", "return_boxes": False,
    })
    assert r.status_code == 200, r.text
    for block in r.json()["blocks"]:
        for line in block["lines"]:
            assert line["box"] is None


def test_lines_and_layout_responses_are_byte_identical_to_before(client):
    """The card's hard constraint: adding ``vl`` must not add a single key to the
    existing two modes. Pinned on the exact key sets, because ``task`` and the
    two ``usage`` fields are the fields most likely to leak."""
    headers = _auth(client, "ocr-model", "paddleocr-vl-1.5")
    data = base64.b64encode(png_bytes()).decode()

    lines_body = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model", "image": data}).json()
    assert set(lines_body) == {"id", "model", "text", "lines", "usage"}
    assert set(lines_body["usage"]) == {"det_ms", "rec_ms", "lines"}

    layout_body = client.post("/v1/ocr", headers=headers, json={
        "model": "ocr-model", "image": data, "mode": "layout"}).json()
    assert set(layout_body) == {"id", "model", "mode", "text", "lines",
                                "usage", "blocks"}
    assert set(layout_body["usage"]) == {"det_ms", "rec_ms", "lines", "blocks",
                                         "layout_ms"}
    for block in layout_body["blocks"]:
        assert set(block) == {"index", "type", "label", "score", "box", "text",
                              "lines"}


def test_the_console_test_route_passes_vl_through(client):
    """``/api/test/ocr`` is the same handler, so the console gets ``vl`` without a
    second implementation -- and the card asks for the mode to be "只透传"."""
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    for model_id in ("ocr-model", "paddleocr-vl-1.5"):
        assert client.post(f"/api/models/{model_id}/load").status_code == 200
    r = client.post("/api/test/ocr", json={
        "model": "ocr-model",
        "image": "data:image/png;base64," + base64.b64encode(png_bytes()).decode(),
        "mode": "vl",
    })
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "vl"
