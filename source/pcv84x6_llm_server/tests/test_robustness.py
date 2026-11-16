"""Bad input to the OpenAI surface must get a clear 4xx, never a 500 or a hang."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_api import make_model


@pytest.fixture()
def api(tmp_path):
    models = tmp_path / "models"
    make_model(models, "m")
    app = create_app(data_dir=tmp_path / "data", models_dir=models, backend_kind="mock",
                     web_dir=tmp_path / "web", context_length_override=4096)
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        assert c.post("/api/models/m/load").status_code == 200
        key = c.post("/api/keys", json={"name": "t"}).json()["key"]
        yield c, {"Authorization": f"Bearer {key}"}
        c.post("/api/models/m/unload")


def post(c, h, body, **kw):
    return c.post("/v1/chat/completions", headers=h, json=body, **kw)


@pytest.mark.parametrize("body, code", [
    ({"model": "m", "messages": []}, 400),                                      # nothing to answer
    ({"model": "m", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 0}, 400),
    ({"model": "m", "messages": [{"role": "user", "content": "hi"}], "max_tokens": -5}, 400),
    ({"model": "m", "messages": [{"role": "user", "content": "hi"}], "n": 3}, 400),
    ({"model": "nope", "messages": [{"role": "user", "content": "hi"}]}, 404),
    ({"model": "m", "messages": [{"role": "robot", "content": "hi"}]}, 422),     # schema
    ({"model": "m"}, 422),
    ({"model": "m", "messages": [{"role": "user", "content": [
        {"type": "input_audio", "input_audio": {"data": "x"}}]}]}, 400),          # unsupported part
    ({"model": "m", "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,!!!notbase64"}}]}]}, 400),
    ({"model": "m", "messages": [{"role": "user", "content": "hi"}], "stop": ["x"] * 40}, 400),
])
def test_bad_requests_get_a_client_error(api, body, code):
    c, h = api
    r = post(c, h, body)
    assert r.status_code == code, (body, r.status_code, r.text)
    assert "detail" in r.json()


def test_not_json_is_a_client_error(api):
    c, h = api
    r = c.post("/v1/chat/completions", headers={**h, "Content-Type": "application/json"},
               content=b"{not json")
    assert r.status_code == 422


def test_oversized_body_is_refused(api):
    c, h = api
    huge = "a" * (65 * 1024 * 1024)
    r = post(c, h, {"model": "m", "messages": [{"role": "user", "content": huge}]})
    assert r.status_code == 413


def test_max_tokens_beyond_context_is_clamped_not_refused(api):
    c, h = api
    r = post(c, h, {"model": "m", "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 10 ** 9})
    assert r.status_code == 200, r.text


def test_service_still_answers_after_the_bad_requests(api):
    c, h = api
    for body in ({"model": "m", "messages": []}, {"model": "m"}):
        post(c, h, body)
    r = post(c, h, {"model": "m", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 4})
    assert r.status_code == 200


def test_every_v1_route_requires_a_key(api):
    c, _ = api
    assert c.get("/v1/models").status_code == 401
    assert post(c, {}, {"model": "m", "messages": [{"role": "user", "content": "hi"}]}).status_code == 401
    assert post(c, {"Authorization": "Bearer sk-wrong"},
                {"model": "m", "messages": [{"role": "user", "content": "hi"}]}).status_code == 401


def test_playground_rejects_malformed_messages(api):
    c, _ = api
    r = c.post("/api/chat/stream", json={"model": "m", "messages": [{"role": "robot", "content": 1}]})
    assert r.status_code == 400
