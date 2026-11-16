"""The inference record of a multimodal embedding request.

An image-only input reaches the recorder as ``{"text": "", "image": ...}``
(``validate_items`` fills the omitted text). The record is built through the
same ``flatten_content`` the prompt renderer uses, and that reader refuses a
text part whose text is falsy -- so recording the empty text as a part made the
whole message walk raise and lose the image with it. On the board that was one
traceback per picture-only request ("content part type 'text' is not
supported"), and the record had no description of the request at all.

These tests pin the fix at the boundary where it belongs -- the record's content
construction -- and pin that the reader still refuses genuinely illegal parts, so
the fix cannot be "make flatten_content permissive".
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.openai_api import _embed_record_content
from app.api.tool_calls import flatten_content
from app.core.inference_log import describe_messages
from app.main import create_app

PNG = "data:image/png;base64," + base64.b64encode(
    (Path(__file__).parent / "vision_fixtures/tiny.png").read_bytes()).decode()
# tiny.png is 7x5; the recorder reports the decoded size, not the base64 length.
SIZE = {"width": 7, "height": 5}


@pytest.fixture()
def client(tmp_path):
    """A logged-in console session, plus a bearer header for the inference route.

    The key is passed per call rather than set on the client: an inference-scoped
    key on every request would (correctly) be refused by the /api console routes,
    which the tests below use to read the record back.
    """
    models = tmp_path / "models"
    d = models / "wemm"
    (d / "config").mkdir(parents=True)
    (d / "wemm-embedding-2b_w8bf16_seq2048_cv84x6.bmodel").write_bytes(b"fake")
    (d / "config" / "config.json").write_text("{}")
    app = create_app(data_dir=tmp_path / "state", models_dir=models,
                     backend_kind="mock", web_dir=tmp_path / "web")
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        assert c.post("/api/models/wemm/load").status_code == 200
        key = c.post("/api/keys", json={"name": "pytest"}).json()["key"]
        yield c, {"Authorization": f"Bearer {key}"}


def _record_for(client, items) -> dict:
    c, headers = client
    response = c.post("/v1/embeddings", headers=headers,
                      json={"model": "wemm", "input": items, "dimensions": 64})
    assert response.status_code == 200, response.text
    records = c.get("/api/inference-records", params={"limit": 5}).json()["items"]
    assert records, "the request left no record"
    return c.get(f"/api/inference-records/{records[0]['id']}").json()


# -- the construction boundary ------------------------------------------------

def test_image_only_item_records_the_image_and_no_empty_text():
    parts = _embed_record_content({"text": "", "image": PNG})
    assert parts == [{"type": "image_url", "image_url": {"url": PNG}}]


def test_text_only_item_records_the_text():
    assert _embed_record_content({"text": "一只猫"}) == [{"type": "text", "text": "一只猫"}]


def test_mixed_item_keeps_both_in_order():
    assert _embed_record_content({"text": "一只猫", "image": PNG}) == [
        {"type": "image_url", "image_url": {"url": PNG}},
        {"type": "text", "text": "一只猫"},
    ]


def test_the_recorded_parts_are_readable_by_the_recorder():
    """The regression itself: what we emit must survive the recorder's reader.

    An image part renders as the template's placeholder; a real text part comes
    back verbatim. Before the fix the image-only item emitted an empty text part
    and this raised ``ValueError: content part type 'text' is not supported``.
    """
    for item, expected_images in (
            ({"text": "", "image": PNG}, 1),
            ({"text": "一只猫"}, 0),
            ({"text": "一只猫", "image": PNG}, 1)):
        text, images = flatten_content(_embed_record_content(item))
        assert len(images) == expected_images
        assert (item.get("text") or "") in text


def test_illegal_parts_are_still_refused():
    """The fix must not turn the reader into a permissive one.

    An unsupported part type, and a text part that is present but falsy, are
    both still errors -- the HTTP layer maps them to a 400 rather than
    answering a different question.
    """
    with pytest.raises(ValueError, match="not supported"):
        flatten_content([{"type": "audio", "audio": {"data": "x"}}])
    with pytest.raises(ValueError, match="not supported"):
        flatten_content([{"type": "text", "text": ""}])
    with pytest.raises(ValueError, match="not supported"):
        flatten_content([{"type": "image_url"}])


def test_describe_messages_survives_an_image_only_turn():
    """End to end through the recorder: the image is described, nothing raises."""
    described = describe_messages([
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": PNG}}]}])
    assert described["images"] == [{"count": 1, **SIZE}]
    assert described["messages"][0]["content"] == [
        {"type": "image", "index": 0, **SIZE}]


# -- over HTTP ----------------------------------------------------------------

def test_picture_only_request_leaves_a_record_with_the_image(client):
    record = _record_for(client, [{"image": PNG}])
    assert record["status"] == "ok"
    content = record["messages"][0]["content"]
    assert [p["type"] for p in content] == ["image"]
    assert record["images"] == [{"count": 1, **SIZE}]


def test_mixed_batch_records_each_item_faithfully(client):
    record = _record_for(client, ["一只猫", {"image": PNG},
                                  {"text": "一只猫", "image": PNG}])
    assert record["status"] == "ok"
    contents = [m["content"] for m in record["messages"]]
    # Text-only turns record their text (as a part list once images are in play).
    assert contents[0] == [{"type": "text", "text": "一只猫"}]
    assert [p["type"] for p in contents[1]] == ["image"]
    assert [p["type"] for p in contents[2]] == ["image", "text"]
    assert contents[2][1]["text"] == "一只猫"
    assert record["images"] == [{"count": 2, **SIZE}]


def test_an_illegal_request_is_still_refused_and_leaves_no_record(client):
    c, headers = client
    before = c.get("/api/inference-records", params={"limit": 200}).json()["total"]
    response = c.post("/v1/embeddings", headers=headers,
                      json={"model": "wemm", "input": [{"text": "x", "video": "y"}]})
    assert response.status_code == 400
    assert "text" in response.json()["detail"]
    after = c.get("/api/inference-records", params={"limit": 200}).json()["total"]
    assert after == before
