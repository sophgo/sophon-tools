"""``bin/cv84x6-mcp-stdio``: the bridge for clients that can only spawn a server.

Two halves are tested, and only one of them needs the network:

* the **pump** -- stdin lines in, POSTs out, responses back on stdout, with
  notifications and parse errors doing the right thing (a fake transport);
* the **round trip** against a real ``/mcp`` -- the service's own endpoint, in
  process, so the bridge is proved against the protocol it claims to speak rather
  than against a mock of it.

The bridge is a *script a client spawns*, so it is loaded by path rather than
imported: that is also the only way to catch a syntax error the service's own
imports would never touch, and a bridge that cannot start is indistinguishable
from a client that hangs.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

BRIDGE = Path(__file__).resolve().parent.parent / "bin" / "cv84x6-mcp-stdio"


def load_bridge():
    spec = importlib.util.spec_from_loader(
        "cv84x6_mcp_stdio",
        importlib.machinery.SourceFileLoader("cv84x6_mcp_stdio", str(BRIDGE)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bridge():
    return load_bridge()


def test_the_script_is_executable_and_has_a_shebang():
    """A client spawns it by filename; ``sh`` is not going to run Python for it."""
    assert BRIDGE.is_file()
    assert BRIDGE.stat().st_mode & 0o111, "not executable"
    assert BRIDGE.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3")


def test_it_runs_under_the_boards_python_3_10():
    """The release's interpreter is 3.10; a 3.11+ syntax would be a release bug."""
    proc = subprocess.run([sys.executable, str(BRIDGE), "--help"],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert "--url" in proc.stdout and "--api-key" in proc.stdout


def test_help_documents_the_environment_fallbacks():
    proc = subprocess.run([sys.executable, str(BRIDGE), "--help"],
                          capture_output=True, text=True, timeout=30)
    assert "CV84X6_MCP_URL" in proc.stdout
    assert "CV84X6_API_KEY" in proc.stdout


# ---------------------------------------------------------------------------
# the pump, with a fake transport
# ---------------------------------------------------------------------------
class FakeBridge:
    def __init__(self, responses: dict) -> None:
        self.responses = responses
        self.sent: list[dict] = []
        self.fail: Exception | None = None

    def post(self, message: dict):
        self.sent.append(message)
        if self.fail is not None:
            raise self.fail
        if message.get("id") is None:
            return None
        return self.responses.get(message["method"], {
            "jsonrpc": "2.0", "id": message["id"], "result": {}})


def test_initialize_goes_in_and_its_result_comes_out(bridge):
    fake = FakeBridge({"initialize": {
        "jsonrpc": "2.0", "id": 1,
        "result": {"protocolVersion": "2025-06-18",
                   "serverInfo": {"name": "cv84x6-llm-server", "version": "0"}}}})
    out = io.StringIO()
    bridge.serve(fake, stdin=io.StringIO(json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18"}}) + "\n"), stdout=out)
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert lines[0]["result"]["protocolVersion"] == "2025-06-18"
    assert fake.sent[0]["method"] == "initialize"


def test_a_notification_produces_no_output(bridge):
    """A stdio client matches replies to requests by id; an extra line breaks it."""
    fake = FakeBridge({})
    out = io.StringIO()
    bridge.serve(fake, stdin=io.StringIO(json.dumps({
        "jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"), stdout=out)
    assert out.getvalue() == ""
    assert len(fake.sent) == 1


def test_a_parse_error_is_reported_rather_than_swallowed(bridge):
    """Silence looks like a hang; the client has nothing else to go on."""
    out = io.StringIO()
    bridge.serve(FakeBridge({}), stdin=io.StringIO("{not json\n"), stdout=out)
    body = json.loads(out.getvalue())
    assert body["error"]["code"] == -32700


def test_a_batch_is_refused_with_a_message(bridge):
    fake = FakeBridge({})
    out = io.StringIO()
    bridge.serve(fake, stdin=io.StringIO('[{"jsonrpc":"2.0","id":1,"method":"ping"}]\n'),
                 stdout=out)
    body = json.loads(out.getvalue())
    assert body["error"]["code"] == -32600
    assert fake.sent == []


def test_a_non_object_line_is_a_request_error_not_a_crash(bridge):
    """``5`` is valid JSON and not a legal JSON-RPC message.

    The old pump called ``message.get`` on it and died with an AttributeError,
    taking the whole bridge (and the client's session) down over one bad line.
    """
    fake = FakeBridge({})
    out = io.StringIO()
    bridge.serve(fake, stdin=io.StringIO("5\n"), stdout=out)
    body = json.loads(out.getvalue())
    assert body["error"]["code"] == -32600
    assert fake.sent == []
    # And the pump is still alive: the next good line is answered.
    out2 = io.StringIO()
    bridge.serve(fake, stdin=io.StringIO(
        "\n".join(["5", json.dumps({"jsonrpc": "2.0", "id": 4, "method": "ping"})])
        + "\n"), stdout=out2)
    lines = [json.loads(line) for line in out2.getvalue().splitlines()]
    assert lines[0]["error"]["code"] == -32600
    assert lines[1]["id"] == 4


def test_a_json_scalar_and_a_null_are_both_refused(bridge):
    out = io.StringIO()
    bridge.serve(FakeBridge({}), stdin=io.StringIO('"ping"\nnull\n'), stdout=out)
    bodies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [b["error"]["code"] for b in bodies] == [-32600, -32600]


def test_blank_lines_are_ignored(bridge):
    fake = FakeBridge({})
    out = io.StringIO()
    bridge.serve(fake, stdin=io.StringIO("\n\n  \n"), stdout=out)
    assert out.getvalue() == ""
    assert fake.sent == []


def test_a_transport_failure_answers_the_request_with_an_error(bridge):
    fake = FakeBridge({})
    fake.fail = bridge.BridgeError("connection refused")
    out = io.StringIO()
    bridge.serve(fake, stdin=io.StringIO(json.dumps({
        "jsonrpc": "2.0", "id": 9, "method": "tools/list"}) + "\n"), stdout=out)
    body = json.loads(out.getvalue())
    assert body["id"] == 9
    assert body["error"]["code"] == -32603
    assert "connection refused" in body["error"]["message"]


def test_several_lines_are_answered_in_order(bridge):
    fake = FakeBridge({})
    out = io.StringIO()
    stdin = io.StringIO("\n".join(json.dumps(
        {"jsonrpc": "2.0", "id": n, "method": "ping"}) for n in (1, 2, 3)) + "\n")
    bridge.serve(fake, stdin=stdin, stdout=out)
    assert [json.loads(line)["id"] for line in out.getvalue().splitlines()] == [1, 2, 3]


# ---------------------------------------------------------------------------
# the round trip against the service's own /mcp
# ---------------------------------------------------------------------------
@pytest.fixture()
def live(tmp_path: Path):
    """A real app on a real port, plus the key its /mcp expects."""
    import socket

    import uvicorn

    models = tmp_path / "models"
    models.mkdir()
    app = create_app(data_dir=tmp_path / "data", models_dir=models,
                     backend_kind="mock", web_dir=tmp_path / "web",
                     context_length_override=4096)
    with TestClient(app) as admin:
        assert admin.post("/api/login", json={"password": "admin"}).status_code == 200
        raw = admin.post("/api/keys", json={"name": "stdio"}).json()["key"]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    import threading

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        import time

        time.sleep(0.02)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}/mcp", raw
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_the_bridge_completes_a_real_mcp_session(bridge, live):
    """initialize -> initialized -> tools/list, all through the bridge."""
    url, key = live
    stdin = io.StringIO("\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ]) + "\n")
    out = io.StringIO()
    bridge.serve(bridge.Bridge(url, key, 60.0), stdin=stdin, stdout=out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    # Two replies: the notification produced none.
    assert [r["id"] for r in replies] == [1, 2]
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    names = {t["name"] for t in replies[1]["result"]["tools"]}
    assert "kb_search" in names and "ocr_read" in names


def test_the_bridge_reports_a_bad_key_as_an_error_not_a_crash(bridge, live):
    url, _ = live
    out = io.StringIO()
    bridge.serve(bridge.Bridge(url, "sk-wrong", 30.0),
                 stdin=io.StringIO(json.dumps({
                     "jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"),
                 stdout=out)
    body = json.loads(out.getvalue())
    assert body["error"]["code"] == -32603
    assert "401" in body["error"]["message"]
