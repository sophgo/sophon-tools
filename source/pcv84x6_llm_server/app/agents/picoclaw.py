"""PicoClaw: a static Go agent whose launcher UI forks its own gateway.

PicoClaw's official release carries two statically linked binaries -- no Node,
no Python, no libc beyond the kernel:

    picoclaw-launcher   the web console: dashboard login, model/channel config,
                        an HTTP API, and the ``/pico/ws`` chat proxy
    picoclaw            the agent engine: the process that talks to the model

The launcher starts ``picoclaw gateway -E`` itself. Measured on the board, that
child inherits the launcher's process group, so the manager's existing
``start_new_session=True`` + group-signal stop already takes both. What is *not*
free is everything else about a two-process agent, and that is what this spec
adds -- one hook each, declared in ``AgentSpec``:

* ``after_start`` waits for the gateway to answer ``/health`` (a launcher that is
  up with a dead gateway looks perfectly healthy and simply never replies) and
  provisions the dashboard password with the agent's own secret.
* ``children_ports`` tells the port-conflict check that ``port + 1`` is taken
  too, so a second agent can never be given the gateway's port.
* ``leftovers`` finds a gateway whose launcher is gone.

Everything below was measured against 0.3.1: the arm64 release on the CV84X6
board and the x64 build of the same tag on the development host.

**Ports.** The launcher defaults to 18800 and the gateway to 18790 -- and 18790
is exactly what this project gives OpenClaw. So the launcher takes 14097 (14096
is opencode) and the gateway gets ``port + 1``, written into ``gateway.port``.
The launcher really does read that field: changing it in the config and
restarting moved the listening socket, checked with ``ss``. ``gateway.host`` is
``127.0.0.1`` because nothing outside this service has any business reaching it.

**Auth.** The dashboard is password-only -- bcrypt in
``$PICOCLAW_HOME/launcher-auth.db``, an HttpOnly session cookie, and no
bearer or URL-token login at all. So the proxy cannot log in on the operator's
behalf the way it does for opencode. Instead the manager *sets* the dashboard
password to the agent's own secret, using PicoClaw's own
``POST /api/auth/setup`` (public until a password exists), and the console shows
that secret on the card. The operator still has to type it once; the console's
admin login still gates the whole subtree.

**Chat transport.** The dashboard reaches the gateway over ``/pico/ws`` and
fetches attachments from ``/pico/media/<id>``, both on the launcher's own origin,
with the URL built from ``window.location.host``. Under ``/agents/picoclaw/``
those have to move inside the prefix, which is the shared proxy's
``prefix_root`` mode.

**Model requests.** ``model_name`` is the model id this service serves and
``model`` is ``openai/<id>``; measured with a mock ``/v1`` server, the id that
reaches the wire is the bare one (PicoClaw strips the prefix for the ``openai``
protocol), and ``max_tokens`` is the field this service reads.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import httpx

from ..core import procs
from .spec import (
    MCP_SERVER_NAME as MCP_NAME,
    AgentError,
    AgentSpec,
    Artifact,
    InstallContext,
    key_from_mcp_entry,
    mcp_headers,
    mcp_url,
    merge_mcp_server,
)

logger = logging.getLogger(__name__)

VERSION = "0.3.1"

# 14096 is this project's opencode. 18800 (the launcher's own default) and 18790
# (the gateway's) are both avoided for the same reason: an operator may well have
# a PicoClaw or an OpenClaw of their own on this board.
DEFAULT_PORT = 14097

# The prefix the shared reverse proxy serves this UI on.
BASE_PATH = "/agents/picoclaw"

PROVIDER = "openai"

# The vendor's dfss mirror, first in every list because an offline board (and a
# customer site) cannot reach github.com at all. The file is uploaded under a
# versioned name so it cannot collide with anything already there.
DFSS_DIR = "open@sophgo.com:/tools/cv84x6_llm_server/agents"

# Both archives are the official release assets: the two binaries plus LICENSE
# and README.md at the top level. The x64 build has its own checksum -- reusing
# the arm64 one would verify the wrong file and pass for nothing.
ARTIFACTS = {
    "arm64": Artifact(
        urls=(
            f"dfss://{DFSS_DIR}/picoclaw-{VERSION}-linux-arm64.tar.gz",
            "https://github.com/sipeed/picoclaw/releases/download/"
            f"v{VERSION}/picoclaw_Linux_arm64.tar.gz",
        ),
        sha256="e78ab0de05d000698ff8b32458e71cb3134e52e9eaf540e3323a72e9914de060",
        size=21933591,
    ),
    "x64": Artifact(
        urls=(
            f"dfss://{DFSS_DIR}/picoclaw-{VERSION}-linux-x64.tar.gz",
            "https://github.com/sipeed/picoclaw/releases/download/"
            f"v{VERSION}/picoclaw_Linux_x86_64.tar.gz",
        ),
        sha256="86f0fe84aa55279352edbe13adfca484a03bcf189e2030b25e34628089069c3f",
        size=23587053,
    ),
}

# The engine binary, named here because ``leftovers`` has to prove a surviving
# gateway is this agent's.
AGENT_BINARY = "picoclaw"

# 16384 output tokens is ~10-14 minutes of decoding at ~20 tok/s on this board;
# capped at half the context so the prompt keeps the other half.
MAX_OUTPUT_TOKENS = 16384

# PicoClaw's own default is 120 s, which is far too short here: one tool-using
# turn can legitimately spend five minutes in prefill plus decode.
REQUEST_TIMEOUT_S = 1800

# The dashboard's login has no username; PicoClaw refuses anything shorter.
MIN_PASSWORD_LEN = 8

# How long the forked gateway is given to answer after the launcher does.
# Measured: about a second on the board, once the model is loaded.
GATEWAY_TIMEOUT_S = 60.0


class PicoclawSpec(AgentSpec):
    id = "picoclaw"
    name = "PicoClaw"
    version = VERSION
    default_port = DEFAULT_PORT
    artifacts = ARTIFACTS
    # Served under /agents/picoclaw/, like the other two. The reason is
    # reachability rather than framing: on a customer site the board is reached
    # through one forwarded port, so :14097 is not an address a browser on
    # another subnet can resolve.
    embeddable = True
    proxied = True
    # The launcher is an origin-root SPA (Vite + TanStack Router): assets are
    # ``/assets/...``, the router reads ``location.pathname`` as a route, and the
    # chat socket is built from ``window.location.host``. Every one of those
    # leaves the prefix unless the proxy maps them.
    prefix_root = True
    # Measured: the launcher answers in ~0.3 s and its gateway follows within a
    # second. The rest of the budget is for a loaded board under I/O pressure.
    start_timeout = 120.0
    executable = "picoclaw-launcher"
    payload_root = "bin"
    # The API key lives in the config's model_list, so a sync reads it back from
    # there rather than rotating the operator's key.
    key_in_config = True
    # Measured on the board 2026-10-27 (10.42.0.242): the launcher + gateway
    # tree sits at 50-58 MB idle, and a conversation moved it to 55 MB. The card
    # rounds up to 55/60, because an estimate that reads low is the one that gets
    # an operator into trouble. The floor is sized so a start cannot invite the
    # OOM killer, not copied from upstream's "10-20 MB" claim.
    memory_floor_bytes = 120 * 1024 * 1024
    # The launcher keeps the dashboard password in a SQLite file under
    # PICOCLAW_HOME, which is inside this agent's own tree; nothing escapes it.
    # The card says one thing only: what the agent costs to run. Whether it fits
    # is the memory check's answer, against this board's real free memory -- a
    # fixed "the board has N GB" claim would be wrong on the next board.
    card_note = "预估内存：空闲约 55 MB，对话后约 60 MB。"

    # -- paths -----------------------------------------------------------
    def config_path(self, directory: Path) -> Path:
        """The app config the launcher and the gateway it forks both read."""
        return Path(directory) / "config" / "picoclaw.json"

    def home_dir(self, directory: Path) -> Path:
        """``PICOCLAW_HOME``: pid file, launcher auth DB, skills, launcher logs.

        Under ``data/`` on purpose rather than ``home/``: a reset wipes the
        agent's derived state, and the password store has to go with it --
        otherwise a reset's fresh secret would never be provisioned and the
        console would show a password PicoClaw no longer accepts.
        """
        return Path(directory) / "data" / "picoclaw"

    def launcher(self, directory: Path) -> Path:
        return Path(directory) / "bin" / "picoclaw-launcher"

    def binary(self, directory: Path) -> Path:
        return Path(directory) / "bin" / AGENT_BINARY

    def gateway_port(self, port: int) -> int:
        """The gateway's loopback port: one above the launcher's.

        Derived rather than stored so the config, the console's status and the
        port conflict check cannot disagree about it.
        """
        port = int(port or DEFAULT_PORT)
        if port >= 65535:  # pragma: no cover - a port that high never validates
            raise AgentError(f"端口 {port} 之后没有可用的 gateway 端口")
        return port + 1

    def gateway_health_url(self, port: int) -> str:
        return f"http://127.0.0.1:{self.gateway_port(port)}/health"

    # -- configuration ---------------------------------------------------
    def write_config(self, directory: Path, ctx: InstallContext) -> None:
        path = self.config_path(directory)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.build_config(directory, ctx), indent=2,
                                   ensure_ascii=False))
        path.chmod(0o600)
        # ``.security.yml`` WINS over this file for ``api_keys`` (measured: the
        # launcher's ``loadSecurityConfig`` merges the secure fields in *after*
        # parsing the config). Leaving a stale entry there makes a rotated key
        # invisible -- the file would still hold the revoked one, the agent's
        # requests would 401, and the config would look perfectly correct. The
        # model section is therefore dropped so this file is the only source
        # until the launcher migrates it again on its next load.
        _drop_security_models(path.parent)
        # The agent's tools may edit files, and this is the only tree they may
        # reach; it has to exist before the first turn runs.
        (Path(directory) / "workspace").mkdir(parents=True, exist_ok=True)

    def build_config(self, directory: Path, ctx: InstallContext) -> dict:
        """The ``picoclaw.json`` this service generates.

        Field names come from PicoClaw 0.3.1's own config structs
        (``pkg/config/config.go``), not from the docs, and the result is loaded
        by the real binary in the tests.
        """
        d = Path(directory)
        port = int(ctx.port or DEFAULT_PORT)
        default = ctx.default_model or (ctx.models[0].id if ctx.models else "")
        context = _context_of(ctx, default)
        thinking = bool(ctx.thinking)

        model_list = []
        for choice in ctx.models:
            entry = {
                # The alias the agent's default model names, and what the
                # dashboard lists. This service's model ids are used verbatim.
                "model_name": choice.id,
                # PicoClaw wants "<provider>/<model id>": the prefix chooses its
                # OpenAI-compatible client, and the bare id is what goes on the
                # wire (measured against a mock /v1).
                "model": f"{PROVIDER}/{choice.id}",
                "api_base": f"http://127.0.0.1:{ctx.service_port}/v1",
                "api_keys": [ctx.api_key] if ctx.api_key else [],
                # Without this PicoClaw's client picks the output field from the
                # model id; this service reads max_tokens and would otherwise
                # fall back to its small default.
                "max_tokens_field": "max_tokens",
                "request_timeout": REQUEST_TIMEOUT_S,
                # Thinking is opt-in here. PicoClaw maps "off" to
                # enable_thinking=false for a Qwen id, but has no "on" half for
                # this provider -- the service reads enable_thinking itself, so
                # turning it on is one explicit extra_body field.
                "thinking_level": "low" if thinking else "off",
            }
            if thinking:
                entry["extra_body"] = {"enable_thinking": True}
            model_list.append(entry)

        return {
            "version": 3,
            "agents": {
                "defaults": {
                    "workspace": str(d / "workspace"),
                    # The agent has file and exec tools. This is the boundary
                    # that keeps them inside its own tree.
                    "restrict_to_workspace": True,
                    "model_name": default,
                    # Mandatory on this board: without it PicoClaw assumes a
                    # context the model cannot take. Never a default -- always
                    # the loaded model's own 32768 or 131072.
                    "context_window": context,
                    "max_tokens": _max_tokens(context),
                    "max_tool_iterations": 20,
                },
            },
            "model_list": model_list,
            "tools": {"mcp": self._mcp_config(d, ctx)},
            "gateway": {
                # Loopback only. The console reaches the gateway through the
                # launcher, and the launcher through this service's proxy, so no
                # component of this agent is exposed to the LAN unauthenticated.
                "host": "127.0.0.1",
                "port": self.gateway_port(port),
                "hot_reload": False,
                "log_level": "info",
            },
        }

    # -- MCP -------------------------------------------------------------
    def _mcp_config(self, directory: Path, ctx: InstallContext) -> dict:
        """``tools.mcp``: this service's server, plus whatever the operator added.

        Two fields decide whether the block works at all, and both were read
        from PicoClaw 0.3.1's own config structs (``pkg/config/config.go``:
        ``ToolsConfig.MCP``, ``MCPConfig``, ``MCPServerConfig``) rather than from
        its docs:

        * ``enabled`` -- ``MCPConfig`` embeds ``ToolConfig``, and PicoClaw's
          ``DefaultConfig()`` sets it to **false**. Leaving it out means
          ``LoadFromMCPConfig`` logs "MCP integration is disabled" and the
          ``servers`` map below is never read.
        * ``type`` -- omitted, a server with a ``url`` is inferred as **sse**
          (``EffectiveMCPTransportType``). This endpoint is Streamable HTTP with
          no SSE stream, so ``streamable-http`` has to be stated explicitly; it
          is PicoClaw's alias for its ``http`` transport.

        Verified against the 0.3.1 binary with ``picoclaw mcp test <name>``,
        which connects, negotiates ``protocol=2025-06-18`` and lists the tools
        (``docs/mcp.md`` has the transcript).
        """
        entry = {
            "enabled": True,
            "type": "streamable-http",
            "url": mcp_url(ctx.service_port),
            "headers": mcp_headers(ctx.api_key),
        }
        servers = merge_mcp_server(_existing_servers(self.config_path(directory)), entry)
        return {"enabled": True, "servers": servers}

    def existing_key(self, directory: Path) -> str:
        """The API key already in this agent's config, wherever PicoClaw keeps it.

        Measured on the board: the launcher rewrites the config on load and
        *moves* ``api_keys`` out of it into a sibling ``.security.yml`` (mode
        0600), keyed ``model_list.<model_name>:<index>.api_keys``. So after the
        first start the plain ``picoclaw.json`` has no key at all, and a sync
        that only read that file would conclude the key was lost -- revoke the
        operator's key and issue a new one on every start. Both locations are
        therefore consulted, config first.
        """
        data = _read_json(self.config_path(directory))
        for entry in (data or {}).get("model_list") or []:
            keys = (entry or {}).get("api_keys") or []
            if keys:
                return str(keys[0])
        # Third location: the same key is in the MCP server's header, and it is
        # the only copy that survives when the model list is empty (an agent
        # installed while nothing was loaded) -- the launcher has moved
        # api_keys into .security.yml by then, where a config rewrite cannot
        # see it.
        mcp_key = key_from_mcp_entry(
            (((data or {}).get("tools") or {}).get("mcp") or {}).get("servers", {})
            .get(MCP_NAME))
        if mcp_key:
            return mcp_key
        return _security_key(Path(directory) / "config")

    # -- running ---------------------------------------------------------
    def env(self, directory: Path, secret: str = "") -> dict[str, str]:
        d = Path(directory)
        env = super().env(directory, secret)
        env.update({
            # Both processes read this file; the launcher passes it to the
            # gateway it forks.
            "PICOCLAW_CONFIG": str(self.config_path(d)),
            # The pid file, the launcher's auth DB, skills and its own logs.
            "PICOCLAW_HOME": str(self.home_dir(d)),
            # The launcher looks for the engine beside itself; naming it removes
            # any dependence on the working directory or PATH.
            "PICOCLAW_BINARY": str(self.binary(d)),
        })
        return env

    def command(self, directory: Path, port: int) -> list[str]:
        """Start the *launcher*; the gateway is its child.

        ``-console`` keeps it in the foreground with no system tray, which is
        what makes it a process this manager owns and can signal.
        ``-no-browser`` stops it from trying to open one on a headless board.
        The positional argument is the config file, which is how PicoClaw is
        told to use a config outside ``$PICOCLAW_HOME``.
        """
        return [
            str(self.launcher(directory)),
            "-console",
            "-no-browser",
            "--port", str(int(port)),
            str(self.config_path(directory)),
        ]

    def children_ports(self, directory: Path, port: int) -> tuple[int, ...]:
        """The gateway's loopback port, which the launcher forks onto."""
        return (self.gateway_port(port),)

    # -- HTTP ------------------------------------------------------------
    def health_url(self, port: int) -> str:
        """The launcher's one public endpoint.

        There is no ``/health`` on the launcher: ``/`` redirects to the login
        page until a dashboard session exists, and ``/api/gateway/status``
        requires one. ``/api/auth/status`` is deliberately public -- the login
        page needs it before anyone is logged in -- and answers 200 with JSON,
        which is exactly what a readiness probe is.
        """
        return f"http://127.0.0.1:{port}/api/auth/status"

    def web_url(self, host: str, port: int, secret: str) -> str:
        """The proxied dashboard, as a relative path on this service.

        Relative on purpose, like the other two: the console is served from the
        service origin, so the path resolves against whatever host the browser
        already used. There is no URL-token login to put in it -- the operator
        gets the password from the card and types it once at the login page the
        proxy serves inside the prefix.
        """
        return f"{BASE_PATH}/"

    def web_credentials(self, secret: str) -> tuple[str, str]:
        # Password-only dashboard: nothing to show in the username column.
        return ("", secret)

    # -- the two-process lifecycle ---------------------------------------
    async def after_start(self, directory: Path, ctx: InstallContext,
                          port: int) -> str:
        """Provision the dashboard password, then wait for the gateway.

        Runs while the manager still holds this agent's lock, after the launcher
        answered its probe. A failure here is a failed start -- the operator
        asked for a working agent, and a launcher nobody can log into is not one
        -- except for a missing gateway, which is reported as a warning because
        the launcher itself is genuinely up.
        """
        base = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=15.0),
                                     trust_env=False) as client:
            await self._provision_password(client, base, (ctx.secret or "").strip())
            return await self._wait_gateway(client, base, port)

    async def _provision_password(self, client: httpx.AsyncClient, base: str,
                                  secret: str) -> None:
        """Make the dashboard password equal the agent's secret.

        PicoClaw has no way to set this from a file, and re-implementing its
        bcrypt-in-SQLite store here would be a second copy of a vendor format.
        Its own ``POST /api/auth/setup`` is public exactly while no password
        exists, so first start is the one moment this needs no session -- and it
        is also the only time it should run: on a later start the store already
        holds the hash and the call would be refused as unauthenticated.
        """
        try:
            status = await client.get(f"{base}/api/auth/status")
            initialized = bool(status.json().get("initialized"))
        except (httpx.HTTPError, ValueError) as exc:
            raise AgentError(
                f"launcher 接口不可用（{exc.__class__.__name__}）") from exc
        if initialized:
            return
        if len(secret) < MIN_PASSWORD_LEN:
            raise AgentError(f"控制台密码至少需要 {MIN_PASSWORD_LEN} 个字符")
        try:
            r = await client.post(f"{base}/api/auth/setup",
                                  json={"password": secret, "confirm": secret})
        except httpx.HTTPError as exc:
            raise AgentError(
                f"写入控制台密码失败（{exc.__class__.__name__}）") from exc
        if r.status_code >= 400:
            raise AgentError(f"写入控制台密码失败：HTTP {r.status_code} {r.text[:160]}")
        logger.info("picoclaw: provisioned the dashboard password")

    async def _wait_gateway(self, client: httpx.AsyncClient, base: str,
                            port: int) -> str:
        """Wait for the gateway the launcher forks; report if it never came.

        A launcher with a dead gateway answers every request and looks perfectly
        healthy -- the dashboard simply never replies to a message. Turning that
        into a sentence at start time is the whole point of this wait.
        """
        url = self.gateway_health_url(port)
        deadline = time.monotonic() + GATEWAY_TIMEOUT_S
        while time.monotonic() < deadline:
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    return ""
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.4)
        detail = ""
        try:
            logs = await client.get(f"{base}/api/gateway/logs")
            if logs.status_code == 200:
                text = str(logs.json().get("logs") or "")[-400:]
                if text:
                    detail = f"；gateway 日志：{text}"
        except (httpx.HTTPError, ValueError):
            pass
        return (f"{self.name} 的 launcher 已启动，但 gateway 在 {GATEWAY_TIMEOUT_S:.0f} 秒内"
                f"没有通过 {url}（确认默认模型已加载）{detail}")

    def leftovers(self, directory: Path, port: int) -> list[int]:
        """Live gateways of this agent that a stop must also reap.

        Signalling the launcher's process group normally takes the gateway with
        it, since the launcher does not put its child in a new group. This
        covers the other case: the launcher is gone (crashed, or killed alone)
        and its gateway survived, still holding the model connection and the
        gateway port. Leaving it would make the next start fail on a busy port.

        Every candidate is proved: some token of its command line must resolve to
        *this* agent's own ``bin/picoclaw``, and the command line must carry the
        ``gateway`` subcommand. Checking the whole argv rather than ``exe`` alone
        is what covers a script -- a ``#!/usr/bin/env python3`` wrapper reports
        the interpreter as its ``exe`` and puts its own path in ``argv[1]`` --
        and the resolved-path comparison is what keeps a stranger out.
        """
        expected = self.binary(directory)
        found: list[int] = []
        try:
            candidates = procs.scan_processes()
        except Exception:  # pragma: no cover - /proc trouble means "cannot tell"
            return []
        for cand in candidates:
            if "gateway" not in cand.argv:
                continue
            names = [cand.exe or "", *cand.argv]
            if not any(_is_expected_binary(name, expected) for name in names):
                continue
            found.append(cand.pid)
        return found


def _is_expected_binary(candidate: str, expected: Path) -> bool:
    """Whether ``candidate`` names this agent's engine binary.

    Checked against ``/proc/<pid>/exe`` for a real binary and against ``argv``
    for a wrapper: a ``#!/usr/bin/env python3`` stand-in, or any launcher script,
    reports the interpreter as its ``exe`` and puts its own path in ``argv[1]``.
    Both are only ever accepted when they resolve to *this* agent's own tree, so
    a stranger is never signalled.
    """
    if not candidate:
        return False
    if os.path.basename(candidate) != AGENT_BINARY:
        return False
    return procs.same_path(candidate, expected)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _existing_servers(path: Path) -> dict:
    """The ``tools.mcp.servers`` map already on disk, so a sync keeps the operator's.

    Read before our own entry is merged in: PicoClaw's UI can add servers, and a
    config rewrite that dropped them would delete work the operator did from the
    agent's own dashboard.
    """
    data = _read_json(Path(path))
    servers = ((data.get("tools") or {}).get("mcp") or {}).get("servers")
    return servers if isinstance(servers, dict) else {}


def _security_key(config_dir: Path) -> str:
    """The API key PicoClaw moved into ``.security.yml``, or "".

    The file is YAML and this service has no YAML parser in its runtime
    dependencies (it is deliberately vendor-light for this board). The one
    shape that matters is fixed and shallow, so it is read structurally rather
    than by pulling in a parser:

        model_list:
          <model name>:<index>:
            api_keys:
              - <key>

    A file that does not match that shape yields "", which makes the manager
    treat the key as missing -- the same conservative answer a corrupt config
    gets, and it is logged by the caller's normal "new key issued" path.
    """
    path = Path(config_dir) / ".security.yml"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    in_models = False
    in_keys = False
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if indent == 0:
            in_models = stripped.startswith("model_list:")
            in_keys = False
            continue
        if not in_models:
            continue
        if stripped.endswith("api_keys:") or stripped == "api_keys:":
            in_keys = True
            continue
        if in_keys:
            if stripped.startswith("- "):
                return stripped[2:].strip().strip("'\"")
            # Any other key at or above the api_keys level ends the list.
            in_keys = False
    return ""


def _drop_security_models(config_dir: Path) -> None:
    """Remove the ``model_list`` section from ``.security.yml``, if present.

    Line-based on purpose: the section is a fixed, shallow block at the top level
    (see ``_security_key``), and this service has no YAML parser in its runtime
    dependencies. Everything else in the file -- channel tokens, OAuth
    credentials -- is left byte-for-byte as PicoClaw wrote it, because those are
    the vendor's values, not this service's.

    A missing or unreadable file is not an error: before the launcher's first
    load there is no such file at all, which is the ordinary install case.
    """
    path = Path(config_dir) / ".security.yml"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except OSError:
        return
    kept: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if indent == 0 and stripped and not stripped.startswith("#"):
            skipping = stripped.startswith("model_list:")
        if not skipping:
            kept.append(line)
    if len(kept) == len(lines):
        return
    try:
        path.write_text("".join(kept), encoding="utf-8")
        path.chmod(0o600)
    except OSError:  # pragma: no cover - a read-only file is the launcher's problem
        logger.warning("picoclaw: could not clear model_list from %s", path)


def _context_of(ctx: InstallContext, model_id: str) -> int:
    """The context length of ``model_id``, from the list the manager sent."""
    for choice in ctx.models:
        if choice.id == model_id:
            return max(2048, int(choice.context or 0))
    if ctx.models:
        return max(2048, int(ctx.models[0].context or 0))
    return 32768


def _max_tokens(context: int) -> int:
    return min(MAX_OUTPUT_TOKENS, max(512, context // 2))


SPEC = PicoclawSpec()
