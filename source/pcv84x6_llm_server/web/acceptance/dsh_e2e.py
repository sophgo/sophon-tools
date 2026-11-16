#!/usr/bin/env python3
"""Acceptance harness: the real service + the real DSH spec + the real proxy.

What is real:
  * ``app.main.create_app`` with the shipped agent specs (so ``/agents/dsh/`` is
    served by ``app/api/agent_proxy.py`` exactly as on a board);
  * ``@deepseek-ai/dsh@0.2.1-rc.5`` booting its ``web`` profile, on the real
    private Node;
  * the spec's own install / write_config / command / token handoff code.

What is faked, and why:
  * the *model*: a scripted OpenAI-compatible endpoint that answers with a
    ``kb_search`` tool call on the first turn and prose after the tool result
    (a real 35B cannot be asked to call a tool on demand);
  * the *MCP server*: a stdlib Streamable-HTTP server exposing ``kb_search``, so
    the call is observable end to end.

The point of the exercise is the chain -- browser -> service proxy -> DSH ->
service /v1 -> tool call -> service proxy -> DSH -> MCP -> back -- not the model.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# the scripted model
# ---------------------------------------------------------------------------
class Model(BaseHTTPRequestHandler):
    """OpenAI-compatible ``/v1`` that calls ``mcp__cv84x6__kb_search`` once."""

    protocol_version = "HTTP/1.1"
    log_path: Path | None = None
    #: When this file exists, every ``/mcp`` POST is dropped. See ``Combined``.
    dead_flag: Path | None = None

    def _record(self, entry: dict) -> None:
        if self.log_path is not None:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._json(200, {"object": "list", "data": [
                {"id": "qwen3.6-35b-a3b-32k", "object": "model",
                 "created": 0, "owned_by": "cv84x6"}]})
        else:
            self._json(404, {})

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._json(404, {})
            return
        msgs = body.get("messages") or []
        self._record({
            "model": body.get("model"),
            "max_tokens": body.get("max_tokens"),
            "enable_thinking": body.get("enable_thinking"),
            "tools": [t.get("function", {}).get("name")
                      for t in (body.get("tools") or [])],
            "roles": [m.get("role") for m in msgs],
        })
        tool_results = [m for m in msgs if m.get("role") == "tool"]
        names = [t.get("function", {}).get("name") for t in (body.get("tools") or [])]
        want = "mcp__cv84x6__kb_search"

        if not tool_results and want in names:
            # First turn: ask for the tool.
            answer = {
                "role": "assistant", "content": "",
                "tool_calls": [{
                    "id": "call_kb_1", "type": "function",
                    "function": {"name": want,
                                 "arguments": json.dumps({"query": "盘点差异率"}, ensure_ascii=False)},
                }],
            }
            finish = "tool_calls"
        else:
            got = str(tool_results[-1].get("content"))[:300] if tool_results else ""
            answer = {"role": "assistant",
                      "content": ("已调用 kb_search。工具返回：" + got) if got
                                 else "你好，我是本机模型。"}
            finish = "stop"

        if not body.get("stream"):
            self._json(200, {
                "id": "c1", "object": "chat.completion", "created": int(time.time()),
                "model": body.get("model"),
                "choices": [{"index": 0, "message": answer, "finish_reason": finish}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10,
                          "total_tokens": 110},
            })
            return

        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "close")
        self.end_headers()

        def chunk(delta, fin=None):
            self.wfile.write(b"data: " + json.dumps({
                "id": "c1", "object": "chat.completion.chunk",
                "created": int(time.time()), "model": body.get("model"),
                "choices": [{"index": 0, "delta": delta, "finish_reason": fin}],
            }, ensure_ascii=False).encode() + b"\n\n")
            self.wfile.flush()

        if "tool_calls" in answer:
            chunk({"role": "assistant", "content": "",
                   "tool_calls": [{"index": 0, **answer["tool_calls"][0]}]})
        else:
            chunk({"role": "assistant", "content": ""})
            text = answer["content"]
            for i in range(0, len(text), 10):
                chunk({"content": text[i:i + 10]})
                time.sleep(0.01)
        chunk({}, finish)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


# ---------------------------------------------------------------------------
# the MCP server
# ---------------------------------------------------------------------------
class Mcp(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    log_path: Path | None = None
    #: When this file exists, every ``/mcp`` POST is dropped. See ``Combined``.
    dead_flag: Path | None = None

    def log_message(self, *a):
        pass

    def _mcp_json(self, code, obj, extra=None):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        msg = json.loads(self.rfile.read(n) or b"{}")
        method = msg.get("method")
        rid = msg.get("id")
        if Mcp.log_path is not None:
            with open(Mcp.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "method": method, "id": msg.get("id"),
                    "auth": self.headers.get("authorization"),
                    "name": (msg.get("params") or {}).get("name"),
                    "args": (msg.get("params") or {}).get("arguments"),
                }, ensure_ascii=False) + "\n")
        if rid is None:
            self.send_response(202)
            self.send_header("content-length", "0")
            self.end_headers()
            return
        if method == "initialize":
            self._mcp_json(200, {"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": msg["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "cv84x6-acceptance", "version": "1"}}},
                {"mcp-session-id": "acceptance-1"})
        elif method == "tools/list":
            self._mcp_json(200, {"jsonrpc": "2.0", "id": rid, "result": {"tools": [{
                "name": "kb_search",
                "description": "在本机知识库中检索",
                "inputSchema": {"type": "object",
                                "properties": {"query": {"type": "string"}},
                                "required": ["query"]},
            }]}})
        elif method == "tools/call":
            args = (msg.get("params") or {}).get("arguments") or {}
            self._mcp_json(200, {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": f"知识库命中：关于「{args.get('query', '')}」的记录 3 条"}],
                "isError": False}})
        else:
            self._mcp_json(200, {"jsonrpc": "2.0", "id": rid,
                             "error": {"code": -32601, "message": str(method)}})


def serve(handler, port: int) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Combined(Model, Mcp):
    """Both mocks on one port: ``/mcp`` goes to the MCP side, the rest to ``/v1``.

    One port because the shipped spec writes both URLs from a single
    ``service_port``. Splitting them would mean editing the generated config,
    which is exactly the code under test.

    ``Mcp.do_POST`` is called as an unbound function, so its ``self._mcp_json``
    resolves through this class' MRO -- which is why the MCP side's helper is
    named differently from ``Model._json`` (they have different signatures).
    """

    def do_GET(self):
        if self.path.rstrip("/").startswith("/mcp"):
            self.send_response(405)
            self.send_header("content-length", "0")
            self.end_headers()
            return
        Model.do_GET(self)

    def do_POST(self):
        if self.path.rstrip("/").startswith("/mcp"):
            # A flag file makes the MCP endpoint fail the way a broken one does
            # (connection closed mid-handshake), without stopping the service --
            # so the acceptance can prove the agent *reports* it while every
            # other part of the chain keeps working.
            if Mcp.dead_flag is not None and Mcp.dead_flag.exists():
                self.close_connection = True
                try:
                    self.connection.close()
                except OSError:
                    pass
                return
            Mcp.do_POST(self)
            return
        Model.do_POST(self)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18095,
                    help="the console/service port this process listens on")
    ap.add_argument("--root", default="/tmp/dsh-accept/root")
    ap.add_argument("--backend-port", type=int, default=18096,
                    help="the port the *agent* is told to use for /v1 and /mcp; "
                         "one mock serves both, so the spec's generated config is "
                         "used unmodified")
    ap.add_argument("--app-tree", default="/tmp/e2e-dsh-app",
                    help="the prebuilt DSH tree installed under agents/dsh/app")
    ap.add_argument("--node-dir",
                    default=os.environ.get(
                        "NODE_DIR",
                        "/home/zzt/workspace/openclaw-research/rt/node-v24.22.1-linux-x64"))
    args = ap.parse_args()

    # One mock, two paths: the real spec writes ``<service_port>/v1`` and
    # ``<service_port>/mcp``, so putting service_port here means DSH is
    # configured by the shipped code with nothing patched afterwards.
    serve(Combined, args.backend_port)

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    os.environ["CV84X6_BACKEND"] = "mock"

    # Seed one model directory, the same way the console's own acceptance does:
    # without a model in the list the spec writes no route at all, and DSH then
    # answers "session has no provider/model" -- which is correct behaviour but
    # proves nothing about the handoff this harness exists to exercise.
    from web.acceptance.mock_server import seed as seed_models

    seed_models(root)

    from app.main import create_app

    app = create_app(
        data_root=root,
        backend_kind="mock",
        web_dir=ROOT / "web" / "dist",
        decode_delay_ms=0,
        context_length_override=32768,
        service_port=args.backend_port,
    )

    # Point the DSH spec at what is on this machine instead of the board mirror.
    from app.agents import dsh as dsh_mod
    from app.agents.spec import Artifact, host_arch

    tree = Path(args.app_tree)
    arch = host_arch()
    payload = Path(root) / "payload"
    payload.mkdir(parents=True, exist_ok=True)
    agent_dir = app.state.agents.directory("dsh")
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "app").symlink_to(tree / "app", target_is_directory=True)
    (agent_dir / "workspace").mkdir(parents=True, exist_ok=True)

    import shutil
    node_src = Path(args.node_dir)
    node_dst = agent_dir / dsh_mod.SPEC.node_dir
    if not node_dst.exists():
        node_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(node_src, node_dst, symlinks=True)

    # Record what the mock saw, so the acceptance can prove the tool round trip.
    # Written to files rather than exposed as routes: the console's SPA catch-all
    # is registered inside ``create_app``, and a route added afterwards never
    # gets a chance to match.
    log_dir = Path(root) / "calls"
    log_dir.mkdir(parents=True, exist_ok=True)
    Model.log_path = log_dir / "model.jsonl"
    Mcp.log_path = log_dir / "mcp.jsonl"
    Mcp.dead_flag = Path(root) / "mcp.dead"
    Model.log_path.write_text("")
    Mcp.log_path.write_text("")
    print(f"call logs: {log_dir}", flush=True)

    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
