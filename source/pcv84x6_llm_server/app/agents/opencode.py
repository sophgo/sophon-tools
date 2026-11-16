"""opencode: the open-source terminal agent, run as a local HTTP server.

opencode ships one self-contained binary (no Node runtime), serves its own web
UI on the port it is given, and speaks OpenAI-compatible chat to a provider
configured in ``opencode.json``. That makes it a single-artifact, single-process
agent: install is "unpack one file", and everything else is that config file.

Three things about it were measured rather than assumed (v1.19.4, 2026-10-26):

* **The provider is bundled.** ``@ai-sdk/openai-compatible`` is compiled into the
  binary, so an offline board does not need npm at runtime.
* **``?auth_token=<base64>`` logs the browser in.** It is
  ``base64("user:password")``, not the raw password, and it works on both the
  UI and the JSON API. Only the request that carries it is authenticated,
  though: every later asset/API call needs basic auth again.
* **The UI sends no ``X-Frame-Options``** (only a CSP without ``frame-ancestors``),
  so it could be framed directly.

So why is it proxied (``proxied = True``) rather than linked to its own port?
Reachability, not framing. On a customer site the board is reached through one
forwarded port, so ``http://<board>:14096`` is not an address the browser can
reach -- the iframe stayed blank and "打开" dead-ended. ``app/api/agent_proxy.py``
serves the UI on this service's origin under ``/agents/opencode/``, presents the
basic auth above on the caller's behalf, and rewrites the page for the prefix
(opencode is an origin-root app: ``/assets/...``, routes from
``location.pathname``, API base from ``location.origin``).
"""

from __future__ import annotations

import json
from pathlib import Path

from .spec import (
    MCP_SERVER_NAME as MCP_NAME,
    AgentSpec,
    Artifact,
    InstallContext,
    key_from_mcp_entry,
    mcp_headers,
    mcp_url,
    merge_mcp_server,
)

VERSION = "1.19.4"

# The vendor's dfss mirror. It comes first in every artifact's URL list because
# an offline board (and a customer site) cannot reach github.com at all; the
# GitHub release stays as the fallback for a machine that can.
DFSS_DIR = "open@sophgo.com:/tools/cv84x6_llm_server/agents"

# 78 MB, single executable named "opencode" at the archive root.
ARTIFACTS = {
    "arm64": Artifact(
        urls=(
            f"dfss://{DFSS_DIR}/opencode-{VERSION}-linux-arm64.tar.gz",
            "https://github.com/anomalyco/opencode/releases/download/"
            f"v{VERSION}/opencode-linux-arm64.tar.gz",
        ),
        sha256="8568230ccd847dc93e95b9f6894379077d3e014a16b48040743573e77c23e85f",
        size=78526339,
    ),
    "x64": Artifact(
        urls=(
            f"dfss://{DFSS_DIR}/opencode-{VERSION}-linux-x64.tar.gz",
            "https://github.com/anomalyco/opencode/releases/download/"
            f"v{VERSION}/opencode-linux-x64.tar.gz",
        ),
        sha256="849bd6b3d959a1d2ef200ed1634a51c79a45ca236aa26665d75debd694805cce",
        size=79667571,
    ),
}

# The provider entry's key. Anything the agent logs about the provider uses it,
# so it is a name the operator will recognise rather than "default".
PROVIDER = "cv84x6"

# 4096 is opencode's own default, which a user's other opencode may well hold.
DEFAULT_PORT = 14096

# The console path the proxy serves this UI on. Relative to the service origin
# on purpose -- see ``web_url``.
BASE_PATH = "/agents/opencode"

SERVER_USERNAME = "opencode"

# One prompt in, one file edit out -- 1800000 ms (30 min) is the task-card value
# and is what lets a 20 token/s model finish a 6k-token answer.
REQUEST_TIMEOUT_MS = 1800000

# The service is on the same board, so the model can only produce about 20-30
# tokens a second; 16384 output tokens is ~10-14 minutes of continuous decoding.
# Capped at half the context so the prompt keeps the other half.
MAX_OUTPUT_TOKENS = 16384


class OpencodeSpec(AgentSpec):
    id = "opencode"
    name = "opencode"
    version = VERSION
    default_port = DEFAULT_PORT
    artifacts = ARTIFACTS
    # Measured: no X-Frame-Options, and ?auth_token= satisfies the UI's own
    # login, so a full-height iframe stays logged in.
    embeddable = True
    # Reached only through this service's ``/agents/opencode/``. opencode's UI
    # *can* be framed directly, so the reason is not framing but reachability:
    # on a customer site the board is reached as one forwarded port, and a link
    # to :14096 is a host/port that does not exist for the browser. Proxying is
    # what makes "打开" and the iframe work from another subnet.
    proxied = True
    # opencode is built to be served from an origin's root (``/assets/...``,
    # routes parsed from ``location.pathname``, API base = ``location.origin``),
    # so the proxy has to strip the prefix on the way up and rewrite the page on
    # the way down. See ``app/api/agent_proxy.py``.
    prefix_root = True
    start_timeout = 120.0
    executable = "opencode"
    payload_root = "bin"
    # Measured on the board 2026-10-27: ~219 MB idle, ~390 MB after a
    # tool-using conversation (write a file, run it). The card reports that cost
    # and nothing else -- whether it fits is the memory check's answer.
    card_note = "预估内存：空闲约 220 MB，用过工具后约 390 MB。"

    # -- paths -----------------------------------------------------------
    def config_path(self, directory: Path) -> Path:
        return Path(directory) / "config" / "opencode" / "opencode.json"

    def env(self, directory: Path, secret: str = "") -> dict[str, str]:
        d = Path(directory)
        env = super().env(directory, secret)
        env.update({
            "OPENCODE_CONFIG": str(self.config_path(d)),
            # Each of these stops opencode from reaching for the network at
            # startup: an update check, a model-catalogue fetch and an LSP
            # download are all wasted minutes on an offline board (and the
            # first two fail loudly).
            "OPENCODE_DISABLE_AUTOUPDATE": "1",
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
            "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
            "OPENCODE_DISABLE_CLAUDE_CODE": "1",
            # The agent's own server auth. Its UI and API both require it.
            "OPENCODE_SERVER_USERNAME": SERVER_USERNAME,
            "OPENCODE_SERVER_PASSWORD": secret,
            # Every tool is pre-approved: the model is local, the workspace is
            # the agent's own directory, and a prompt waiting for a human to
            # click "allow" has nobody to click it on a headless board.
            "OPENCODE_PERMISSION": json.dumps({"edit": "allow", "bash": "allow"}),
        })
        return env

    def command(self, directory: Path, port: int) -> list[str]:
        return [
            str(Path(directory) / "bin" / "opencode"),
            # Loopback only: the console reaches it through the same-origin
            # proxy above, so a LAN-wide bind exposed an agent that may edit
            # files and run shell commands behind nothing but basic auth (found
            # on the board in the v0.6.29 E2E run, MYS-2682).
            "serve", "--port", str(port), "--hostname", "127.0.0.1",
        ]

    # -- configuration ---------------------------------------------------
    def write_config(self, directory: Path, ctx: InstallContext) -> None:
        path = self.config_path(directory)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.build_config(ctx, directory), indent=2,
                                   ensure_ascii=False))
        path.chmod(0o600)

    def build_config(self, ctx: InstallContext, directory: Path | None = None) -> dict:
        """The ``opencode.json`` this service generates.

        Every model gets ``tool_call`` (the whole point of driving opencode at
        local models), ``reasoning`` and an ``interleaved`` field so
        ``reasoning_content`` from this service lands in opencode's reasoning
        channel rather than being dropped, and the two variants so the operator
        can flip thinking per session from the UI.

        ``directory`` is optional only so the tests can build the config without
        a tree; ``write_config`` always passes it, and it is what lets the MCP
        block keep the servers an operator added from opencode's own UI.
        """
        models: dict[str, dict] = {}
        for choice in ctx.models:
            context = max(1024, int(choice.context or 0))
            models[choice.id] = {
                "name": choice.id,
                "reasoning": True,
                "tool_call": True,
                "attachment": bool(choice.vision),
                # This service returns the thinking trace in reasoning_content,
                # following the DeepSeek/Qwen convention; telling opencode the
                # field name is what makes it show up as reasoning.
                "interleaved": {"field": "reasoning_content"},
                "limit": {
                    "context": context,
                    "output": min(MAX_OUTPUT_TOKENS, context // 2),
                },
                "options": {"enable_thinking": bool(ctx.thinking)},
                "variants": {
                    "think": {"enable_thinking": True},
                    "nothink": {"enable_thinking": False},
                },
            }

        provider: dict = {
            "npm": "@ai-sdk/openai-compatible",
            "name": "CV84X6 本地推理",
            "options": {
                "baseURL": f"http://127.0.0.1:{ctx.service_port}/v1",
                "apiKey": ctx.api_key,
                "timeout": REQUEST_TIMEOUT_MS,
            },
            "models": models,
        }
        default = ctx.default_model or (ctx.models[0].id if ctx.models else "")
        config = {
            "$schema": "https://opencode.ai/config.json",
            "autoupdate": False,
            "share": "disabled",
            # opencode expects "provider/model"; the service's model ids have no
            # slash, so the provider key is the prefix.
            "model": f"{PROVIDER}/{default}" if default else "",
            "small_model": f"{PROVIDER}/{default}" if default else "",
            "provider": {PROVIDER: provider},
        }
        mcp = self._mcp_block(directory, ctx)
        if mcp:
            config["mcp"] = mcp
        return config

    # -- MCP -------------------------------------------------------------
    def _mcp_block(self, directory: Path | None, ctx: InstallContext) -> dict:
        """The ``mcp`` map: this service's server, plus whatever the operator added.

        opencode 1.19.4's schema is
        ``mcp[<name>] = {type: "remote", url, headers, enabled}`` -- read from
        the binary's own zod definitions (``ConfigV2.MCP.Remote``) and confirmed
        against the running server with ``opencode mcp list``, which reports
        ``✓ connected`` and is the evidence recorded in ``docs/mcp.md``.

        ``type: "remote"`` with a plain ``http(s)`` URL is opencode's streamable
        HTTP client; it opens with ``POST /mcp`` and sends
        ``Accept: application/json, text/event-stream``. It *does* try a
        ``GET /mcp`` first for a server-initiated stream and carries on when that
        is refused, which is why the endpoint can answer 405 there.
        """
        entry = {
            "type": "remote",
            "url": mcp_url(ctx.service_port),
            "headers": mcp_headers(ctx.api_key),
            "enabled": True,
        }
        return merge_mcp_server(self._existing_mcp(directory), entry)

    def _existing_mcp(self, directory: Path | None) -> dict:
        """The ``mcp`` block already on disk, so a sync keeps the operator's servers.

        An unreadable or missing file is an empty block: a first install has
        nothing to preserve, and a corrupt config is about to be replaced
        anyway. ``directory`` is None only from a caller that built the config
        without a tree (the tests of the model entries), which has no file to
        read.
        """
        if directory is None:
            return {}
        try:
            data = json.loads(self.config_path(directory).read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        mcp = data.get("mcp") if isinstance(data, dict) else None
        return mcp if isinstance(mcp, dict) else {}

    # -- key / HTTP ------------------------------------------------------
    def existing_key(self, directory: Path) -> str:
        try:
            data = json.loads(self.config_path(directory).read_text())
        except (OSError, json.JSONDecodeError):
            return ""
        key = ((data.get("provider") or {}).get(PROVIDER) or {}).get("options", {}).get("apiKey", "")
        # The MCP entry carries the same key, and is the only copy when the
        # provider block has no models (an agent installed with nothing loaded).
        return key or key_from_mcp_entry(((data.get("mcp") or {}).get(MCP_NAME)))

    # -- HTTP ------------------------------------------------------------
    def health_url(self, port: int) -> str:
        return f"http://127.0.0.1:{port}/global/health"

    def health_auth(self, secret: str) -> tuple[str, str] | None:
        return (SERVER_USERNAME, secret)

    def web_url(self, host: str, port: int, secret: str) -> str:
        """The console's own path for this agent's UI, not the agent's port.

        Deliberately relative, like OpenClaw's: the console is served from the
        service origin, so a path resolves to whatever host the browser is
        already using. A link to ``http://<host>:14096`` would leave that origin
        entirely -- and on a customer site, where only the service's port is
        forwarded, it would not resolve at all. That URL is exactly the bug this
        replaces.

        The agent's own login is not in the URL: the proxy authenticates the
        console admin session and presents the agent's basic-auth credentials
        upstream, so the embedded page and a directly-opened tab both arrive
        logged in without a token in the address bar or a second login prompt.
        """
        return f"{BASE_PATH}/"

    def web_credentials(self, secret: str) -> tuple[str, str]:
        """What the card shows: the operator may also open the agent directly.

        The password is the agent's own server password (opencode's
        ``OPENCODE_SERVER_PASSWORD``), which the proxy uses upstream and which a
        direct visit to the agent's port would ask for.
        """
        return (SERVER_USERNAME, secret)

    def upstream_basic_auth(self, secret: str) -> tuple[str, str] | None:
        """The credentials the proxy presents to the agent's own server.

        Less of a convenience than it looks: opencode 1.19.4 authenticates every
        request except the one carrying ``?auth_token=``, so without this the
        first asset request from an already-"logged-in" page is a 401 and the
        embedded frame is a blank rectangle.
        """
        return (SERVER_USERNAME, secret) if secret else None


SPEC = OpencodeSpec()
