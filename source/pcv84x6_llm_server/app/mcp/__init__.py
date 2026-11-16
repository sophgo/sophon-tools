"""The MCP surface: the JSON-RPC protocol and the tools behind it.

Two modules, one boundary:

* :mod:`app.mcp.server` speaks MCP Streamable HTTP -- JSON-RPC 2.0 over
  ``POST /mcp``, no SSE, no session state. It knows nothing about knowledge
  bases, OCR or audio.
* :mod:`app.mcp.tools` implements the nine tools and returns the
  ``content`` / ``structuredContent`` pair the protocol carries.

The split matters because the protocol is a wire contract and the tools are
application behaviour: a change to one must not be able to break the other.
"""
