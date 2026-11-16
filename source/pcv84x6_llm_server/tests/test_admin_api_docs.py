"""The management API's contract: auth scope, error shape, OpenAPI, document.

Five things this file holds to account (MYS-2676), in the order a reader needs
them:

1. **Route completeness.** Every ``/api`` operation in the built document has a
   tag from the vocabulary, a Chinese summary and description, a declared
   success response, and a documented error body. The check walks the *document*,
   not the decorators, because that is what Swagger and the generated markdown
   read -- a route whose annotations do not survive into the schema is
   undocumented however carefully it was written.
2. **The error shape.** ``{"detail", "code"}`` on every refusal, including 422,
   with special attention to the codes that let a script tell the various 409s
   apart.
3. **Key scope.** An ``admin`` key drives ``/api``; an ``inference`` key gets a
   403; a key minted before this change is ``inference``.
4. **CSRF.** A bearer request needs no ``Origin``; a cookie write from a foreign
   site is refused; a cookie navigation to ``/api/docs`` is not.
5. **The document it is generated into.** ``docs/admin-api.md`` regenerated now
   must equal the committed file, and the offline assets must be the ones this
   build was verified against.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.errors import CODE_STATUS, ERROR_CODES
from app.main import create_app

BASE = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def make_model(root: Path, name: str, ctx: str = "seq2048") -> Path:
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{name}-int4_w4bf16_{ctx}_4core_dynamic.bmodel").write_bytes(b"\x00" * 1024)
    (d / "config" / "config.json").write_text("{}")
    return d


@pytest.fixture()
def app(tmp_path):
    models = tmp_path / "models"
    make_model(models, "test-model")
    app = create_app(data_dir=tmp_path / "data", models_dir=models,
                     backend_kind="mock", web_dir=tmp_path / "web")
    yield app
    app.state.audit.close()
    app.state.inference_log.close()


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin_key(client) -> str:
    """A key that may drive ``/api``, minted through the console route."""
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    r = client.post("/api/keys", json={"name": "script", "scope": "admin"})
    assert r.status_code == 200, r.text
    assert r.json()["meta"]["scope"] == "admin"
    return r.json()["key"]


def bearer(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


# ---------------------------------------------------------------------------
# 1. route completeness
# ---------------------------------------------------------------------------
def _api_operations(spec: dict) -> list[tuple[str, str, dict]]:
    return [(method.upper(), path, operation)
            for path, operations in spec["paths"].items() if path.startswith("/api/")
            for method, operation in operations.items()]


def test_every_api_route_is_described(app):
    """The document, walked as a reader's tool would: nothing may be bare."""
    from app.api.api_docs import TAGS

    spec = app.openapi()
    tag_names = {entry["name"] for entry in TAGS}
    operations = _api_operations(spec)
    # A floor, not the exact number: this test is about *every* route being
    # described, and hard-coding sixty-four would fail on a legitimate addition
    # for the wrong reason. A route deleted by accident still fails below.
    assert len(operations) >= 60, f"only {len(operations)} /api operations"

    problems: list[str] = []
    for method, path, operation in operations:
        label = f"{method} {path}"
        tags = operation.get("tags") or []
        if len(tags) != 1 or tags[0] not in tag_names:
            problems.append(f"{label}: tags={tags!r} (want exactly one from {sorted(tag_names)})")
        summary = operation.get("summary") or ""
        if not summary.strip():
            problems.append(f"{label}: no summary")
        elif not any("一" <= ch <= "鿿" for ch in summary):
            problems.append(f"{label}: summary is not Chinese: {summary!r}")
        description = operation.get("description") or ""
        if len(description) < 20:
            problems.append(f"{label}: description too short ({len(description)} chars)")
        responses = operation.get("responses") or {}
        success = [code for code in responses if code.startswith("2")]
        if not success:
            problems.append(f"{label}: no success response")
        for code in success:
            entry = responses[code]
            if not (entry.get("content") or entry.get("description")):
                problems.append(f"{label}: {code} declares neither content nor description")
        if "401" not in responses and path != "/api/login":
            problems.append(f"{label}: no 401 (the auth dependency can always produce one)")
        if "error" in json.dumps(responses).lower() and "ErrorOut" not in json.dumps(responses):
            problems.append(f"{label}: an error response without the ErrorOut schema")
        if not operation.get("operationId"):
            problems.append(f"{label}: no operationId")
    assert not problems, "\n".join(problems)


def test_response_models_are_declared_for_json_routes(app):
    """A JSON route must name a model, not just "object".

    Streaming and download routes are the documented exception: their body is not
    JSON, so they declare a media type instead -- which is exactly what this test
    accepts for them.
    """
    spec = app.openapi()
    bare = []
    for method, path, operation in _api_operations(spec):
        responses = operation.get("responses") or {}
        success = next((responses[c] for c in responses if c.startswith("2")), {})
        content = success.get("content") or {}
        if not content:
            continue                      # 204-style; nothing to model
        if "application/json" not in content:
            continue                      # SSE / download: media type is the doc
        schema = content["application/json"].get("schema") or {}
        if not schema:
            bare.append(f"{method} {path}: application/json with no schema")
    assert not bare, "\n".join(bare)


def test_operation_ids_are_unique_and_stable(app):
    spec = app.openapi()
    ids = [op["operationId"] for _m, _p, op in _api_operations(spec)]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"duplicate operationIds: {duplicates}"
    # Stable: derived from tag + method + path, so a rename is the only thing
    # that changes one -- which is what a generated client needs.
    assert "models_post_model_load" in ids


def test_the_document_does_not_describe_only_admin_paths(app):
    """Guard the filter ``/api/openapi.json`` applies: adding /v1 later must be
    a conscious act, not a side effect of a merge."""
    from app.api.docs import api_route_count

    spec = app.openapi()
    assert api_route_count(app) == len(_api_operations(spec))
    assert not [p for p in spec["paths"] if p.startswith("/api/") and p == "/api"]


# ---------------------------------------------------------------------------
# 2. the error shape
# ---------------------------------------------------------------------------
def test_a_401_carries_detail_and_code(client):
    r = client.get("/api/models")
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "unauthorized"
    assert body["detail"] == "admin login required"     # unchanged for the console


def test_a_404_carries_the_code(client):
    client.post("/api/login", json={"password": "admin"})
    r = client.get("/api/inference-records/nope")
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"
    assert r.json()["detail"] == "记录不存在"


def test_a_422_is_reshaped_into_the_same_body(client):
    client.post("/api/login", json={"password": "admin"})
    r = client.post("/api/settings", json={"max_queue": "not-a-number"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"
    # Chinese field name + reason, not pydantic's English list.
    assert "max_queue" in body["detail"]
    assert "整数" in body["detail"]
    assert isinstance(body["detail"], str)


def test_a_422_names_the_field_and_counts_the_rest(client):
    client.post("/api/login", json={"password": "admin"})
    r = client.post("/api/settings",
                    json={"max_queue": "x", "prefix_cache_entries": "y"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "另有 1 处问题" in detail


def test_a_validation_error_on_a_list_body_is_still_one_sentence(client):
    client.post("/api/login", json={"password": "admin"})
    r = client.post("/api/downloads", json={"name": "x"})   # url is required
    assert r.status_code == 422
    assert "url" in r.json()["detail"] and "必填" in r.json()["detail"]


@pytest.mark.parametrize("detail,code", [
    ("设备内存不足：qwen3 需要 3.0 GiB", "device_memory_insufficient"),
    ("系统可用内存仅 120 MB，加载模型需要至少 800 MB", "system_memory_insufficient"),
    ("模型 x 的静态占用 900 MiB 超过本模型内存上限 512 MiB，无法加载", "model_mem_limit_exceeded"),
    ("模型 x 正在加载中，请等待加载完成后再请求", "model_busy"),
    ("模型 x 正在卸载，请稍后再加载", "model_busy"),
    ("模型 x 正在下载，下载完成后才能加载", "model_busy"),
    ("模型 x 已在下载中，请等待完成或先取消", "download_busy"),
    ("无法安全判断哪个持有 NPU 内存；请人工确认后停止多余的进程", "model_conflict"),
    ("已有搬迁任务在进行", "storage_busy"),
])
def test_a_state_refusal_gets_its_own_code(detail, code):
    """The point of the code vocabulary: a script can tell the 409s apart.

    Both the message matching *and* the explicit classes are covered -- the
    matcher is what makes the forty pre-existing ``RuntimeError`` sites useful
    without touching the loading path.
    """
    from app.core.errors import classify

    assert classify(detail, 409) == code


def test_the_loading_path_raises_the_documented_classes():
    """The three refusals a long load produces are their own classes.

    Checking the types (not only the messages) is what stops a later reword from
    silently degrading the code to a generic ``conflict``: the class survives a
    message change, and ``classify`` is the fallback for the sites that still
    raise a bare ``RuntimeError``.
    """
    from app.core import models

    for name in ("DeviceMemoryError", "SystemMemoryError", "ModelMemLimitError"):
        cls = getattr(models, name)
        assert issubclass(cls, RuntimeError)
    source = (BASE / "app" / "core" / "models.py").read_text(encoding="utf-8")
    assert "raise DeviceMemoryError(" in source
    assert "raise SystemMemoryError(" in source
    assert "raise ModelMemLimitError(" in source


def test_a_403_is_distinguishable_from_a_401(client, admin_key):
    """``forbidden_scope`` is a 403, so a script knows to mint a new key rather
    than to log in again."""
    client.cookies.clear()
    inference = TestClient(client.app)
    with inference:
        inference.post("/api/login", json={"password": "admin"})
        raw = inference.post("/api/keys", json={"name": "agent"}).json()["key"]
        inference.post("/api/logout")
        inference.cookies.clear()
        r = inference.get("/api/models", headers=bearer(raw))
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden_scope"
    assert "admin" in r.json()["detail"]


def test_an_unknown_bearer_key_is_a_401_not_a_403(client):
    r = client.get("/api/models", headers=bearer("sk-not-a-key"))
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


def test_every_documented_code_is_reachable_in_the_table():
    """The table is the document: a code the server can emit must be in it."""
    documented = {row.code for row in ERROR_CODES}
    for name in ("model_busy", "not_found", "device_memory_insufficient",
                 "validation_error", "queue_full", "load_failed"):
        assert name in documented
    statuses = {row.status for row in ERROR_CODES}
    assert statuses <= {400, 401, 403, 404, 405, 409, 413, 415, 422, 429,
                        499, 500, 503}


# ---------------------------------------------------------------------------
# 3. key scope
# ---------------------------------------------------------------------------
def test_an_admin_key_drives_the_management_api(client, admin_key):
    client.cookies.clear()
    r = client.get("/api/models", headers=bearer(admin_key))
    assert r.status_code == 200
    assert [m["id"] for m in r.json()["models"]] == ["test-model"]

    r = client.post("/api/models/test-model/load", headers=bearer(admin_key))
    assert r.status_code == 200, r.text
    assert r.json()["model"]["loaded"] is True

    r = client.post("/api/settings", headers=bearer(admin_key), json={"max_queue": 5})
    assert r.status_code == 200
    assert r.json()["settings"]["max_queue"] == 5

    r = client.post("/api/keys", headers=bearer(admin_key),
                    json={"name": "second", "scope": "admin"})
    assert r.status_code == 200 and r.json()["meta"]["scope"] == "admin"


def test_an_inference_key_is_refused_on_the_management_api(client, admin_key):
    client.cookies.clear()
    raw = client.post("/api/keys", headers=bearer(admin_key),
                      json={"name": "agent"}).json()["key"]
    r = client.get("/api/models", headers=bearer(raw))
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden_scope"
    # And it still works where it is supposed to.
    assert client.get("/v1/models", headers=bearer(raw)).status_code == 200
    assert client.get("/v1/models", headers=bearer(admin_key)).status_code == 200


def test_a_key_without_a_scope_is_an_inference_key(tmp_path):
    """The compatibility promise: a state file from before this change loads.

    Written by hand the way the old build wrote it -- no ``scope`` key at all --
    because that file is what a customer's board actually has after an upgrade.
    """
    from app.core.state import StateStore, hash_key

    data = tmp_path / "state"
    data.mkdir()
    (data / "state.json").write_text(json.dumps({
        "keys": [{"id": "abc123", "name": "old", "key_hash": hash_key("sk-old"),
                  "prefix": "sk-old…", "created_at": 1.0}],
        "settings": {},
        "usage": {},
    }))
    store = StateStore(data / "state.json")
    key = store.find_key("sk-old")
    assert key is not None
    assert key.scope == "inference"


def test_an_unknown_scope_in_the_file_reads_as_inference(tmp_path):
    """A hand-edited or downgraded file must not grant management rights."""
    from app.core.state import StateStore, hash_key

    data = tmp_path / "state"
    data.mkdir()
    (data / "state.json").write_text(json.dumps({
        "keys": [{"id": "abc", "name": "x", "key_hash": hash_key("sk-x"),
                  "prefix": "sk-x…", "created_at": 1.0, "scope": "root"}],
        "settings": {}, "usage": {},
    }))
    store = StateStore(data / "state.json")
    assert store.find_key("sk-x").scope == "inference"


def test_the_scope_survives_a_restart(client, admin_key, app):
    """A minted admin key keeps its scope after the state file is re-read."""
    from app.core.state import StateStore

    client.cookies.clear()
    assert client.get("/api/models", headers=bearer(admin_key)).status_code == 200
    store = StateStore(Path(app.state.store.path))
    match = [k for k in store.keys if k.name == "script"]
    assert len(match) == 1 and match[0].scope == "admin"


def test_an_unknown_scope_is_a_400_not_a_422(client, admin_key):
    """The console shows ``detail`` -- so the refusal must be a handler error
    with a sentence in it, not pydantic's field dump."""
    r = client.post("/api/keys", headers=bearer(admin_key),
                    json={"name": "x", "scope": "superuser"})
    assert r.status_code == 400
    assert r.json()["code"] == "bad_request"
    assert "scope" in r.json()["detail"]


def test_the_audit_shows_the_keys_name_and_its_scope(client, admin_key):
    client.cookies.clear()
    client.post("/api/keys", headers=bearer(admin_key),
                json={"name": "部署脚本", "scope": "admin"})
    client.post("/api/login", json={"password": "admin"})
    rows = client.get("/api/audit", params={"action": "POST /api/keys"}).json()["items"]
    row = next(r for r in rows if r["summary"] and "部署脚本" in r["summary"])
    assert row["actor_type"] == "api_key"
    assert row["actor_name"] == "script"
    assert 'scope="admin"' in row["summary"]


# ---------------------------------------------------------------------------
# 4. CSRF
# ---------------------------------------------------------------------------
def test_a_bearer_request_needs_no_origin(client, admin_key):
    """A script sends no Origin, and a foreign one is irrelevant: the browser
    never attaches a bearer token by itself, so there is nothing to forge."""
    client.cookies.clear()
    r = client.post("/api/settings", headers=bearer(admin_key), json={"max_queue": 7})
    assert r.status_code == 200
    r = client.post("/api/settings",
                    headers={**bearer(admin_key), "Origin": "https://evil.example"},
                    json={"max_queue": 8})
    assert r.status_code == 200
    assert r.json()["settings"]["max_queue"] == 8


def test_a_cookie_write_from_a_foreign_origin_is_refused(client):
    client.post("/api/login", json={"password": "admin"})
    r = client.post("/api/settings", headers={"Origin": "https://evil.example"},
                    json={"max_queue": 1})
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden_scope"
    assert "evil.example" in r.json()["detail"]
    # Nothing was written.
    assert client.get("/api/settings").json()["max_queue"] != 1


@pytest.mark.parametrize("origin", [None, "", "http://testserver", "http://127.0.0.1:8000"])
def test_a_cookie_write_from_this_origin_is_allowed(client, origin):
    """Including no Origin at all: curl with a cookie jar is a legitimate
    caller, and ``SameSite=Lax`` already covers the browser case."""
    client.post("/api/login", json={"password": "admin"})
    headers = {} if origin is None else {"Origin": origin}
    r = client.post("/api/settings", headers=headers, json={"max_queue": 6})
    assert r.status_code == 200, r.text


def test_a_null_origin_is_refused(client):
    """What a sandboxed frame or a ``file://`` document sends."""
    client.post("/api/login", json={"password": "admin"})
    r = client.post("/api/settings", headers={"Origin": "null"}, json={"max_queue": 2})
    assert r.status_code == 403


def test_a_read_needs_no_origin(client):
    """The console polls with no Origin of its own; requiring one on a GET would
    break it, and a cross-origin read cannot be read back by the other page."""
    client.post("/api/login", json={"password": "admin"})
    r = client.get("/api/models", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200


def test_the_declared_origin_env_is_honoured(client, monkeypatch):
    """A console reached through a forwarded LAN address names it there."""
    monkeypatch.setenv("CV84X6_MCP_ORIGINS", "http://10.43.0.157:8000")
    client.post("/api/login", json={"password": "admin"})
    r = client.post("/api/settings",
                    headers={"Origin": "http://10.43.0.157:8000"},
                    json={"max_queue": 3})
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# 5. the interactive documents
# ---------------------------------------------------------------------------
def test_the_docs_are_refused_without_a_credential(client):
    for path in ("/api/docs", "/api/redoc", "/api/openapi.json",
                 "/api/docs/swagger-ui.css", "/api/docs/swagger-ui-bundle.js",
                 "/api/docs/redoc.standalone.js"):
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json()["code"] == "unauthorized"
    # ``/v1/openapi.json`` has no /api prefix, so its 401 keeps the OpenAI-shaped
    # body the /v1 surface uses everywhere else -- stated here so a later
    # "unify the error shapes" change has to argue with this test.
    r = client.get("/v1/openapi.json")
    assert r.status_code == 401
    assert "code" not in r.json()


def test_an_inference_key_cannot_read_the_docs(client, admin_key):
    client.cookies.clear()
    raw = client.post("/api/keys", headers=bearer(admin_key),
                      json={"name": "agent"}).json()["key"]
    r = client.get("/api/openapi.json", headers=bearer(raw))
    assert r.status_code == 403


def test_the_docs_open_with_a_session_cookie(client):
    client.post("/api/login", json={"password": "admin"})
    for path in ("/api/docs", "/api/redoc"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith("text/html")
        assert "/api/openapi.json" in r.text
    r = client.get("/api/openapi.json")
    assert r.status_code == 200
    assert r.json()["openapi"].startswith("3.")
    assert r.headers["content-type"].startswith("application/json")


def test_the_docs_pages_load_no_remote_asset(client):
    """The whole reason the bundles are committed: a board with no network.

    Every ``src``/``href`` in the two pages must be a path on this service. A
    single CDN URL here is a blank page on a customer's board, and it is the
    kind of thing a reviewer's browser (which *does* have a network) hides.
    """
    import re

    client.post("/api/login", json={"password": "admin"})
    for page in ("/api/docs", "/api/redoc"):
        html = client.get(page).text
        urls = re.findall(r'(?:src|href)="([^"]+)"', html)
        assert urls, page
        for url in urls:
            assert url.startswith("/"), f"{page} loads a remote asset: {url}"
            # And each one really is served.
            assert client.get(url).status_code == 200, f"{page}: {url}"


def test_the_docs_assets_are_the_verified_ones():
    """Digest + size of the committed bundles, so a truncated copy is loud.

    The sha256 table is what makes ``app/static/docs`` a build input rather than
    an opaque blob: a partial download or an accidental edit fails here instead
    of painting a blank page on a board.
    """
    from app.core.admin_docs import VENDORED_ASSETS, verify

    assert verify() == []
    assert len(VENDORED_ASSETS) == 4
    assert all(asset.bytes > 100_000 for asset in VENDORED_ASSETS)


def test_the_served_asset_whitelist_matches_the_vendored_set(client, app):
    from fastapi.routing import APIRoute

    from app.core.admin_docs import SERVED

    loaded = {path for route in app.router.routes
              if (path := getattr(route, "path", "")).startswith("/api/docs/")}
    assert loaded - {"/api/docs/{asset}"} == set()
    client.post("/api/login", json={"password": "admin"})
    for name in SERVED:
        assert client.get(f"/api/docs/{name}").status_code == 200, name
    assert client.get("/api/docs/../app/main.py").status_code == 404
    assert client.get("/api/docs/nope.js").status_code == 404


def test_the_v1_document_is_separate_and_complete(client):
    client.post("/api/login", json={"password": "admin"})
    spec = client.get("/v1/openapi.json").json()
    assert set(spec["paths"]) == {
        "/v1/models", "/v1/models/{model_id}", "/v1/chat/completions",
        "/v1/embeddings", "/v1/rerank", "/v1/audio/transcriptions", "/v1/ocr",
    }
    admin = client.get("/api/openapi.json").json()
    assert not [p for p in admin["paths"] if p.startswith("/v1/")]
    # Same component schemas, because both come from the same app: the two
    # documents cannot describe the same model differently.
    assert set(spec["components"]["schemas"]) == set(admin["components"]["schemas"])


# ---------------------------------------------------------------------------
# 6. the generated document
# ---------------------------------------------------------------------------
def test_the_document_is_in_sync_with_the_code():
    """Regenerate in memory and compare with the committed file.

    This is the check that makes ``docs/admin-api.md`` a document rather than a
    snapshot: change a summary, a field or an error code and this fails until the
    file is regenerated.
    """
    import importlib.util

    path = BASE / "tools" / "gen_admin_api_doc.py"
    spec = importlib.util.spec_from_file_location("gen_admin_api_doc", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected = module.generate()
    committed = module.OUT.read_text(encoding="utf-8")
    assert committed == expected, (
        "docs/admin-api.md is out of date: run python3 tools/gen_admin_api_doc.py")


def test_the_document_covers_every_route_and_the_error_table():
    text = (BASE / "docs" / "admin-api.md").read_text(encoding="utf-8")
    assert "## 认证" in text and "## 错误码" in text
    assert "## 分页与时间格式" in text and "## /v1 的文档" in text
    from app.core.errors import ERROR_CODES

    for row in ERROR_CODES:
        assert f"`{row.code}`" in text, row.code
    # Every operation has a section of its own.
    for method, path, _op in _api_operations(
            __import__("tools.gen_admin_api_doc", fromlist=["x"]).build_spec()):
        assert f"#### `{method} {path}`" in text, f"{method} {path}"


def test_the_document_has_a_curl_example_per_operation():
    import re

    text = (BASE / "docs" / "admin-api.md").read_text(encoding="utf-8")
    details = text.split("## 接口详情", 1)[1].split("## 数据模型", 1)[0]
    # An operation heading, then the next heading of either kind ends its body.
    blocks = re.split(r"\n(?=#{3,4} )", details)[1:]
    operations = [b for b in blocks if b.startswith("#### `")]
    assert len(operations) > 60, len(operations)
    for block in operations:
        assert "```bash" in block, block[:120]


def test_the_docs_index_links_to_the_new_document():
    """A document nobody links to is a document nobody reads."""
    index = (BASE / "docs" / "README.md").read_text(encoding="utf-8")
    assert "admin-api.md" in index
