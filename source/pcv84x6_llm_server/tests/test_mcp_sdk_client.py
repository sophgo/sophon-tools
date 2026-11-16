"""The official ``mcp`` Python SDK as a client for this service's ``/mcp``.

Acceptance criterion #2 of the card, and the reason it is a real test rather than
a transcript: an implementation that only agrees with its own client proves
nothing. The SDK is the independent oracle -- it drives the handshake, validates
the ``tools/list`` payload against its own types, and parses ``tools/call``
results into ``CallToolResult``.

Two different targets, because they catch different bugs:

* **a mock endpoint** (in this file) exercises the protocol layer with no NPU and
  no models, so it runs on any host in the normal suite;
* **the real app**, driven through ``TestClient``'s ASGI transport, exercises the
  same handshake against the actual ASGI app -- that one is what proves the route
  ordering in ``app/main.py`` (the SPA catch-all would otherwise answer ``POST
  /mcp`` with HTML) and the real tool catalogue.

The SDK is **test-only**. It is in neither ``requirements.txt`` nor
``requirements-vendor.txt``: the release's dependency set is pinned for the
board's aarch64 Python 3.10, and this is a build-host check. The import is
skipped when it is absent so a minimal checkout still runs the suite.
"""

from __future__ import annotations

import contextlib
import inspect
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.mcp import server as mcp_server
from app.mcp import tools as mcp_tools
from app.main import create_app

ROOT = Path(__file__).resolve().parent.parent

mcp_sdk = pytest.importorskip("mcp", reason="the mcp SDK is a test-only dependency")


def _sdk_client():
    """The SDK's own streamable-HTTP client, across the versions that name it
    differently (``streamablehttp_client`` up to 1.x, ``streamable_http_client``
    from 2.x)."""
    from mcp.client import streamable_http as mod

    for name in ("streamablehttp_client", "streamable_http_client"):
        fn = getattr(mod, name, None)
        if fn is not None:
            return fn
    pytest.skip("this mcp SDK has no streamable-HTTP client")


def _field(obj, name: str, default=None):
    """The SDK's model field, under either naming convention.

    ``mcp`` 1.x models use camelCase (``protocolVersion``) and 2.x snake_case
    (``protocol_version``); a test that hard-codes one is a test that breaks on
    the other for no reason that concerns this service.
    """
    for candidate in (name, _snake(name), _camel(name)):
        if hasattr(obj, candidate):
            return getattr(obj, candidate)
    return default


def _snake(name: str) -> str:
    out = []
    for index, char in enumerate(name):
        if char.isupper() and index:
            out.append("_")
        out.append(char.lower())
    return "".join(out)


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


async def _drive(app, api_key: str, tool_calls: list[tuple[str, dict]]) -> dict:
    """One full session: initialize -> list -> the calls the test asked for.

    The HTTP client is the SDK's *own* (``mcp`` 2.x builds on ``httpx2``, 1.x on
    ``httpx``), because passing a client from the wrong stack is what makes this
    kind of test fail for a reason that has nothing to do with the endpoint. The
    transport is the SDK stack's ASGI transport, pointed at the app in process.
    """
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client

    g = create_mcp_http_client.__globals__
    transport_mod = g.get("httpx2") or g.get("httpx")
    transport = transport_mod.ASGITransport(app=app)

    def make_client(headers=None, timeout=None, auth=None):
        return transport_mod.AsyncClient(transport=transport, base_url="http://testserver",
                                         headers={**(headers or {}), "Authorization": f"Bearer {api_key}"},
                                         timeout=60.0, auth=auth)

    factory = _sdk_client()
    out: dict = {}
    # 2.x takes a ready client; 1.x takes a factory and opens the client itself.
    if "http_client" in inspect.signature(factory).parameters:
        client = make_client()
        opened = factory("http://testserver/mcp", http_client=client)
    else:
        client = contextlib.nullcontext()
        opened = factory("http://testserver/mcp", httpx_client_factory=make_client)
    async with client:
        async with opened as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                out["protocolVersion"] = _field(init, "protocol_version")
                out["serverInfo"] = _field(init, "server_info").model_dump()
                listed = await session.list_tools()
                out["tools"] = [t.name for t in listed.tools]
                out["schemas"] = {t.name: _field(t, "input_schema") or {}
                                  for t in listed.tools}
                results = {}
                for name, args in tool_calls:
                    result = await session.call_tool(name, args)
                    results[name] = {
                        "isError": bool(_field(result, "is_error")),
                        "text": "".join(getattr(c, "text", "") for c in result.content),
                        "structured": _field(result, "structured_content"),
                    }
                out["results"] = results
    return out


# ---------------------------------------------------------------------------
# against the real app
# ---------------------------------------------------------------------------
@pytest.fixture()
def app_and_key(tmp_path: Path):
    models = tmp_path / "models"
    (models / "embed-model" / "config").mkdir(parents=True)
    (models / "embed-model" / "qwen3-embedding-0.6b_bf16_seq8192_4core_static.bmodel"
     ).write_bytes(b"\x00" * 4096)
    (models / "embed-model" / "config" / "config.json").write_text("{}")
    app = create_app(data_dir=tmp_path / "data", models_dir=models,
                     backend_kind="mock", web_dir=tmp_path / "web",
                     context_length_override=4096)
    with TestClient(app) as admin:
        assert admin.post("/api/login", json={"password": "admin"}).status_code == 200
        raw = admin.post("/api/keys", json={"name": "mcp-sdk"}).json()["key"]
    return app, raw


async def test_the_official_sdk_completes_the_handshake_and_lists_the_tools(app_and_key):
    app, key = app_and_key
    out = await _drive(app, key, [])
    assert out["protocolVersion"] == mcp_server.PROTOCOL_VERSION
    assert out["serverInfo"]["name"] == mcp_server.SERVER_NAME
    assert set(out["tools"]) == set(mcp_tools.TOOLS)
    # The SDK keeps the schemas as it received them; a schema it could not parse
    # would have failed the session outright.
    assert out["schemas"]["kb_search"]["properties"]["query"]["type"] == "string"


async def test_the_official_sdk_can_call_a_tool(app_and_key):
    app, key = app_and_key
    out = await _drive(app, key, [("kb_list", {})])
    result = out["results"]["kb_list"]
    assert result["isError"] is False
    assert "知识库" in result["text"]
    assert result["structured"] == {"kbs": []}


async def test_the_official_sdk_sees_a_tool_error_as_a_result(app_and_key):
    """A tool failure must not surface to the SDK as a protocol exception."""
    app, key = app_and_key
    out = await _drive(app, key, [("kb_search", {"query": "x", "kb": "nope"})])
    assert out["results"]["kb_search"]["isError"] is True
    assert out["results"]["kb_search"]["text"].strip()


# ---------------------------------------------------------------------------
# the transcript for the delivery comment
# ---------------------------------------------------------------------------
async def test_print_a_transcript(app_and_key, capsys):
    """Not an assertion about behaviour: this is how the evidence is produced.

    It runs in the suite so the transcript in the delivery can never describe a
    build other than the one that passed.
    """
    app, key = app_and_key
    out = await _drive(app, key, [
        ("kb_list", {}),
        ("kb_create", {"name": "SDK 验证库"}),
        ("kb_search", {"query": "盘点", "top_k": 5}),
        ("ocr_read", {"path": "/etc/passwd"}),
        ("transcribe_audio", {"path": "/etc/passwd"}),
    ])
    lines = [
        f"initialize -> protocolVersion={out['protocolVersion']} "
        f"serverInfo={out['serverInfo']['name']} {out['serverInfo']['version']}",
        f"tools/list -> {len(out['tools'])} tools: {', '.join(sorted(out['tools']))}",
    ]
    for name, result in out["results"].items():
        text = result["text"].replace("\n", " ⏎ ")
        lines.append(f"tools/call {name} -> isError={result['isError']} :: {text[:200]}")
    print("\n".join(lines))
    assert out["results"]["ocr_read"]["isError"] is True  # /etc/passwd is refused
    assert "不允许" in out["results"]["ocr_read"]["text"]
    assert out["results"]["transcribe_audio"]["isError"] is True


# ---------------------------------------------------------------------------
# the acceptance transcript: kb_search and ocr_read through the real SDK
# ---------------------------------------------------------------------------
async def test_the_sdk_drives_kb_search_and_ocr_read_on_real_files(tmp_path: Path):
    """Acceptance criterion #2, end to end: a library, a search, an OCR read.

    Everything here is the ``mcp`` SDK talking to the real ASGI app: the seed
    (a document added through the tools), the search, and an OCR pass over the
    repository's own test image. The mock backend supplies the workers, so what
    is proved is the tool contract and the protocol, not the NPU.
    """
    import shutil

    models = tmp_path / "models"
    for name, bmodel, context in (
            ("embed-model", "qwen3-embedding-0.6b_bf16", "seq8192"),
            ("ocr-model", None, None)):
        d = models / name
        (d / "config").mkdir(parents=True)
        (d / "config" / "config.json").write_text("{}")
        if bmodel:
            (d / f"{bmodel}_{context}_4core_static.bmodel").write_bytes(b"\x00" * 4096)
    (models / "ocr-model" / "ppocrv6-medium-det_f16_736_bm1684x2_static_20261103.bmodel"
     ).write_bytes(b"\x00" * 4096)
    for rec in ("ppocrv6-medium-rec_f16_48x320_bm1684x2_static_20261103.bmodel",
                "ppocrv6-medium-rec_f16_48x640_bm1684x2_static_20261103.bmodel",
                "ppocrv6-medium-rec_f16_48x1600_bm1684x2_static_20261103.bmodel"):
        (models / "ocr-model" / rec).write_bytes(b"\x00" * 2048)

    app = create_app(data_dir=tmp_path / "data", models_dir=models,
                     backend_kind="mock", web_dir=tmp_path / "web",
                     context_length_override=4096)
    # The app's lifespan is what starts the model workers, so everything below --
    # including the SDK session -- has to run inside it.
    with TestClient(app) as admin:
        assert admin.post("/api/login", json={"password": "admin"}).status_code == 200
        raw = admin.post("/api/keys", json={"name": "sdk-acceptance"}).json()["key"]
        for model_id in ("embed-model", "ocr-model"):
            assert admin.post(f"/api/models/{model_id}/load").status_code == 200
        kb = admin.post("/api/apps/kb", json={"name": "验收库"}).json()["kb"]["id"]

        data_root = Path(app.state.agents.data_root)
        (data_root / "inbox").mkdir(parents=True, exist_ok=True)
        image = data_root / "inbox" / "ui_status.png"
        shutil.copyfile(ROOT / "tests" / "data" / "ocr" / "img" / "ui_status.png", image)
        source = data_root / "inbox" / "盘点制度.txt"
        source.write_text("盘点差异率超过千分之五时必须由财务复核。", encoding="utf-8")

        out = await _drive(app, raw, [
            ("kb_add_document", {"kb": kb, "path": str(source)}),
            ("ocr_read", {"path": str(image)}),
        ])
        assert out["results"]["kb_add_document"]["isError"] is False
        # The document is queued, so wait for it and then search: that is the
        # retrieval path end to end, seeded entirely through the tools.
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            docs = app.state.kb_store.list_docs(kb)
            if docs and all(d["status"] not in ("queued", "parsing", "ocr", "embedding")
                            for d in docs):
                break
            time.sleep(0.05)

        searched = await _drive(app, raw, [("kb_search", {"query": "盘点差异率", "kb": kb})])
        assert searched["results"]["kb_search"]["isError"] is False
        text = searched["results"]["kb_search"]["text"]
        assert "盘点" in text
        assert out["results"]["ocr_read"]["isError"] is False
        assert out["results"]["ocr_read"]["structured"]["ocr"] is True
        assert out["results"]["ocr_read"]["structured"]["text"]

    print("kb_search ->", text.replace("\n", " ⏎ ")[:300])
    print("ocr_read  ->",
          out["results"]["ocr_read"]["text"].replace("\n", " ⏎ ")[:300])
