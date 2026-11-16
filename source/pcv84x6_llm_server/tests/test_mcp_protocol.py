"""``POST /mcp``: the MCP lifecycle, the JSON-RPC contract, and the auth gate.

The tools are ``test_mcp_tools.py``'s job; this file is about the wire. Three
things it deliberately does **not** assume:

* that a response is the shape this code happens to produce -- the assertions are
  what the MCP specification requires of this endpoint (a ``initialize`` result
  with a negotiated version and a tools capability, ``tools/list`` entries with
  ``name``/``description``/``inputSchema``, ``-32601`` for an unknown method),
  because that is what the three real clients check;
* that a notification gets a body -- the spec says 202 and no content;
* that errors are all JSON-RPC errors. A *tool* that fails is a normal result
  with ``isError``, and mixing the two would make a model unable to recover from
  "no such knowledge base".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.mcp import server as mcp_server
from app.mcp import tools as mcp_tools

EMBED_BMODEL = "qwen3-embedding-0.6b_bf16"


def make_model(root: Path, name: str, bmodel: str, context: str = "seq2048") -> Path:
    d = root / name
    (d / "config").mkdir(parents=True)
    (d / f"{bmodel}_{context}_4core_static.bmodel").write_bytes(b"\x00" * 4096)
    (d / "config" / "config.json").write_text("{}")
    return d


@pytest.fixture()
def app(tmp_path: Path):
    models = tmp_path / "models"
    make_model(models, "embed-model", EMBED_BMODEL)
    return create_app(data_dir=tmp_path / "data", models_dir=models,
                      backend_kind="mock", web_dir=tmp_path / "web",
                      context_length_override=4096)


@pytest.fixture()
def key(app):
    """A live API key, and the header that presents it."""
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        raw = c.post("/api/keys", json={"name": "mcp-client"}).json()["key"]
    return {"Authorization": f"Bearer {raw}"}


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def rpc(client, headers, method: str, params=None, rid=1):
    body = {"jsonrpc": "2.0", "method": method}
    if rid is not None:
        body["id"] = rid
    if params is not None:
        body["params"] = params
    return client.post("/mcp", headers=headers, json=body)


# ---------------------------------------------------------------------------
# the lifecycle
# ---------------------------------------------------------------------------
def test_initialize_negotiates_and_advertises_tools(client, key):
    r = rpc(client, key, "initialize", {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    result = body["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == mcp_server.SERVER_NAME
    assert result["serverInfo"]["version"]


def test_initialize_answers_a_client_that_asks_for_the_older_version(client, key):
    """2025-03-26 is compatible for this surface, so it is echoed back.

    Answering with a version the client did not ask for makes some clients hang
    up; the two differ in batching and SSE resumption, neither of which this
    endpoint does.
    """
    r = rpc(client, key, "initialize", {"protocolVersion": "2025-03-26"})
    assert r.json()["result"]["protocolVersion"] == "2025-03-26"


def test_initialize_falls_back_to_this_servers_version_for_an_unknown_one(client, key):
    r = rpc(client, key, "initialize", {"protocolVersion": "1999-01-01"})
    assert r.json()["result"]["protocolVersion"] == mcp_server.PROTOCOL_VERSION


def test_initialized_notification_is_accepted_with_no_body(client, key):
    r = rpc(client, key, "notifications/initialized", rid=None)
    assert r.status_code == 202
    assert not r.content


def test_ping_answers_an_empty_result(client, key):
    body = rpc(client, key, "ping").json()
    assert body == {"jsonrpc": "2.0", "id": 1, "result": {}}


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------
def test_tools_list_carries_the_whole_catalogue_with_schemas(client, key):
    body = rpc(client, key, "tools/list").json()
    tools = {t["name"]: t for t in body["result"]["tools"]}
    assert set(tools) == {
        "kb_list", "kb_create", "kb_search", "kb_read", "kb_list_documents",
        "kb_add_document", "kb_document_status", "ocr_read", "transcribe_audio",
    }
    for name, tool in tools.items():
        assert tool["description"].strip(), name
        assert tool["inputSchema"]["type"] == "object"
        # A tool whose schema says nothing about its arguments is a tool the
        # model has to guess at.
        if name not in ("kb_list",):
            assert tool["inputSchema"]["properties"], name
    # The caps are in the schema, not only in the prose: a client-side validator
    # reads them, and a model that asks for top_k=999 should be refused by the
    # schema before the service has to spend an embedding on it.
    assert tools["kb_search"]["inputSchema"]["properties"]["top_k"]["maximum"] == 20
    assert tools["kb_read"]["inputSchema"]["properties"]["neighbors"]["maximum"] == 3
    # No destructive tool: deletions are the console's job (the card is explicit
    # about this, and it is the one place a mistaken model does real damage).
    assert not any("delete" in name or "remove" in name for name in tools)


def test_no_question_answering_tool(client, key):
    """Answer generation belongs to the agent's own model, not to this service."""
    tools = {t["name"] for t in rpc(client, key, "tools/list").json()["result"]["tools"]}
    assert not any("answer" in name or "ask" in name or "chat" in name for name in tools)


# ---------------------------------------------------------------------------
# the JSON-RPC contract
# ---------------------------------------------------------------------------
def test_unknown_method_is_minus_32601(client, key):
    body = rpc(client, key, "resources/list").json()
    assert body["error"]["code"] == mcp_server.METHOD_NOT_FOUND
    assert body["id"] == 1


def test_unknown_tool_is_a_protocol_error_not_a_tool_result(client, key):
    body = rpc(client, key, "tools/call", {"name": "rm_rf", "arguments": {}}).json()
    assert body["error"]["code"] == mcp_server.INVALID_PARAMS
    assert "result" not in body


def test_tools_call_without_a_name_is_minus_32602(client, key):
    body = rpc(client, key, "tools/call", {"arguments": {}}).json()
    assert body["error"]["code"] == mcp_server.INVALID_PARAMS


def test_tools_call_with_non_object_arguments_is_minus_32602(client, key):
    body = rpc(client, key, "tools/call", {"name": "kb_list", "arguments": []}).json()
    assert body["error"]["code"] == mcp_server.INVALID_PARAMS


def test_bad_json_is_minus_32700(client, key):
    r = client.post("/mcp", headers={**key, "content-type": "application/json"},
                    content=b"{not json")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == mcp_server.PARSE_ERROR


def test_a_batch_is_refused_as_minus_32600(client, key):
    """Batching was removed in 2025-06-18, the version this endpoint speaks."""
    r = client.post("/mcp", headers=key, json=[
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
    ])
    assert r.status_code == 400
    assert r.json()["error"]["code"] == mcp_server.INVALID_REQUEST


def test_an_empty_batch_is_minus_32600(client, key):
    r = client.post("/mcp", headers=key, json=[])
    assert r.status_code == 400
    assert r.json()["error"]["code"] == mcp_server.INVALID_REQUEST


def test_a_message_that_is_not_jsonrpc_2_is_minus_32600(client, key):
    body = client.post("/mcp", headers=key, json={"id": 1, "method": "ping"}).json()
    assert body["error"]["code"] == mcp_server.INVALID_REQUEST


def test_an_empty_body_is_refused(client, key):
    r = client.post("/mcp", headers={**key, "content-type": "application/json"},
                    content=b"")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == mcp_server.INVALID_REQUEST


def test_a_client_response_message_is_accepted_with_202(client, key):
    """``{"jsonrpc":"2.0","id":1,"result":…}`` is legal and is not an error.

    This server never issues requests, so it has nothing to match a response to --
    but per JSON-RPC a response is a valid message, and the spec's answer to
    "nothing to do" is 202 with no body. Answering -32600 told a client its
    perfectly well-formed message was malformed.
    """
    r = client.post("/mcp", headers=key,
                    json={"jsonrpc": "2.0", "id": 1, "result": {}})
    assert r.status_code == 202
    assert not r.content
    # An error response from the client is the same story.
    r = client.post("/mcp", headers=key, json={
        "jsonrpc": "2.0", "id": 2,
        "error": {"code": -32601, "message": "nope"}})
    assert r.status_code == 202


def test_an_object_with_neither_method_nor_id_is_still_minus_32600(client, key):
    """An empty message is a malformed *request*; a response with an id is not."""
    body = client.post("/mcp", headers=key, json={"jsonrpc": "2.0"}).json()
    assert body["error"]["code"] == mcp_server.INVALID_REQUEST


def test_a_parse_error_does_not_echo_the_document(client, key):
    """The decoder's message quotes the body; the reply must not."""
    r = client.post("/mcp", headers={**key, "content-type": "application/json"},
                    content=b'{"jsonrpc":"2.0","method":"ping","secret":"s3cr3t"')
    assert r.status_code == 400
    assert "s3cr3t" not in r.text


def test_get_mcp_is_405_because_there_is_no_stream(client, key):
    """No server-initiated SSE stream: this endpoint is stateless."""
    r = client.get("/mcp", headers=key)
    assert r.status_code == 405
    assert r.headers.get("allow") == "POST"


def test_delete_mcp_is_405_because_there_are_no_sessions(client, key):
    r = client.delete("/mcp", headers=key)
    assert r.status_code == 405


# ---------------------------------------------------------------------------
# Origin
# ---------------------------------------------------------------------------
def test_a_cross_origin_request_is_refused_with_403(client, key):
    """A page on another origin must not be able to drive this endpoint.

    With ``require_api_key`` off -- the default on a trusted single-board
    deployment -- this check is the only thing between a malicious web page and
    the board's NPU (and, through ``kb_add_document``, the agents' files).
    """
    r = client.post("/mcp", headers={**key, "Origin": "https://evil.example"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 403
    assert "跨源" in r.json()["error"]["message"]


def test_a_null_origin_is_refused(client, key):
    """``Origin: null`` is what a sandboxed frame or a ``file://`` page sends."""
    r = client.post("/mcp", headers={**key, "Origin": "null"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 403


def test_a_loopback_origin_is_allowed(client, key):
    """All three bundled agents dial 127.0.0.1 and are not browsers anyway."""
    for origin in ("http://127.0.0.1:8000", "http://localhost:3000"):
        r = client.post("/mcp", headers={**key, "Origin": origin},
                        json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert r.status_code == 200, (origin, r.text)


def test_a_same_origin_request_is_allowed(client, key):
    """The console's own page, served from the board's LAN address."""
    r = client.post("/mcp",
                    headers={**key, "Origin": "http://10.43.0.157:8000",
                             "Host": "10.43.0.157:8000"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 200, r.text


def test_a_declared_origin_is_allowed(client, key, monkeypatch):
    monkeypatch.setenv(mcp_server.ORIGINS_ENV, "https://console.example; https://b.example")
    r = client.post("/mcp", headers={**key, "Origin": "https://console.example"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 200, r.text


def test_a_request_without_an_origin_is_allowed(client, key):
    """Every non-browser client: the agents, the stdio bridge, curl, the SDK."""
    assert rpc(client, key, "ping").status_code == 200


def test_the_origin_check_holds_with_api_key_auth_off(tmp_path: Path):
    """The whole point: on a deployment with no keys, Origin is the only gate.

    ``require_api_key`` is off by editing the stored setting rather than through
    the API -- the console deliberately has no button for it, and this test is
    about the endpoint's behaviour in that state, not about how it got there.
    """
    models = tmp_path / "models"
    make_model(models, "embed-model", EMBED_BMODEL)
    app = create_app(data_dir=tmp_path / "data", models_dir=models,
                     backend_kind="mock", web_dir=tmp_path / "web",
                     context_length_override=4096)
    with TestClient(app) as c:
        app.state.store.settings.require_api_key = False
        # No key, no Origin: served.
        assert c.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 200
        # No key, hostile Origin: refused anyway.
        r = c.post("/mcp", headers={"Origin": "https://evil.example"},
                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------
def test_a_request_without_a_key_is_401(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401


def test_a_request_with_a_wrong_key_is_401(client):
    r = client.post("/mcp", headers={"Authorization": "Bearer sk-not-a-key"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401


def test_get_without_a_key_is_still_refused(client):
    """Nothing is served to an unauthenticated caller, but the refusal for GET is
    the method's own 405: the route has no auth dependency because it never
    reaches a tool. The information leaked is which verbs exist, which the
    probe could learn from any HTTP server.
    """
    assert client.get("/mcp").status_code == 405


def test_a_revoked_key_stops_working(client, key):
    # Signing in is the console's own gate; the key is revoked through it.
    assert client.post("/api/login", json={"password": "admin"}).status_code == 200
    key_id = client.app.state.store.keys[-1].id
    assert client.post(f"/api/keys/{key_id}/revoke").status_code == 200
    assert rpc(client, key, "tools/list").status_code == 401


# ---------------------------------------------------------------------------
# the tool result shape
# ---------------------------------------------------------------------------
def test_a_successful_call_returns_content_text_and_structured_content(client, key):
    body = rpc(client, key, "tools/call", {"name": "kb_list", "arguments": {}}).json()
    result = body["result"]
    assert result["isError"] is False
    assert result["content"][0]["type"] == "text"
    assert "知识库" in result["content"][0]["text"]
    assert result["structuredContent"] == {"kbs": []}


def test_a_failing_tool_is_an_is_error_result_not_a_protocol_error(client, key):
    """The model can act on the first and cannot act on the second."""
    body = rpc(client, key, "tools/call",
               {"name": "kb_read", "arguments": {"chunk_id": "nope"}}).json()
    assert "error" not in body
    result = body["result"]
    assert result["isError"] is True
    assert "chunk_id" in result["content"][0]["text"] or "片段" in result["content"][0]["text"]


def test_every_tool_survives_being_called_with_no_arguments(client, key):
    """A model that omits required arguments deserves a message, not a traceback.

    ``kb_list`` takes none and succeeds; every other tool needs a target and is
    refused with a sentence naming what is missing.
    """
    for name, spec in mcp_tools.TOOLS.items():
        body = rpc(client, key, "tools/call", {"name": name, "arguments": {}}).json()
        assert "error" not in body, name
        expected = name == "kb_list"
        assert body["result"]["isError"] is not expected, name
        assert body["result"]["content"][0]["text"].strip(), name
