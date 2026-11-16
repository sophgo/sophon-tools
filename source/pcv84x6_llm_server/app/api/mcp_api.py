"""``POST /mcp`` -- the MCP endpoint, mounted at the service's own origin.

Thin by design, like ``app/api/apps_api.py``: this file owns the HTTP shape (a
POST that answers JSON, a GET that refuses, a DELETE that refuses) and delegates
everything the protocol says to :mod:`app.mcp.server`, which in turn delegates
the tools to :mod:`app.mcp.tools`. No knowledge-base or OCR logic lives here.

Kept as its own module rather than folded into ``openai_api`` because the two
surfaces have different contracts: ``/v1`` mirrors OpenAI's error body, and MCP
speaks JSON-RPC with its own codes. Sharing a file would mean one exception
handler guessing which shape the caller wanted.
"""

from __future__ import annotations

from ..mcp.server import router  # noqa: F401 - re-exported as the module's router

__all__ = ["router"]
