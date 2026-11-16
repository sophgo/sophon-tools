"""OpenClaw: a Node agent platform with its own web Control UI.

OpenClaw is not one binary. It is an npm package that needs Node ``>=24.22.1``
(package.json ``engines``), and the board ships Node 22 which cannot be touched.
So installing it means two artifacts stacked in the agent's own tree:

    runtime/node   a private Node 24.22.1, checksummed against Node's
                   SHASUMS256.txt
    app            openclaw@2026.10.7, either unpacked from a prebuilt archive
                   (the offline path) or installed by that private npm

Nothing is installed globally and no system path is modified: ``PATH`` for the
child starts at ``runtime/node/bin``.

**Why a prebuilt app archive.** ``npm install openclaw@2026.10.7`` resolves 344
packages from the registry, which an offline board cannot reach. The archive on
dfss is exactly the ``app/`` tree that npm produces with this private Node, so
installing from it is unpacking one file. npm stays as the fallback for an
architecture without a prebuilt build (x64) and for when the archive cannot be
fetched. Measured on the board: 2 min 13 s for npm against seconds for the
archive.

Everything about the launch is measured against 2026.10.7 on a CV84X6 board
(arm64, 2026-10-26); the numbers behind each choice are in ``docs/DESIGN.md``
and repeated here where they decide code. Memory figures are what the agent
costs, never what some board holds -- that differs between boards.

* **Port 18790**, not OpenClaw's 18789, so an operator's own OpenClaw on the
  same board cannot collide with this one.
* **``gateway.controlUi.basePath = /agents/openclaw``** makes the whole UI
  (assets, XHR, WebSocket) live under the prefix our reverse proxy serves, so
  the browser only ever talks to this service's origin.
* **The Control UI refuses to be framed** (``X-Frame-Options: DENY`` plus
  ``frame-ancestors 'none'``), which is why ``app/api/agent_proxy.py`` exists:
  the proxy authenticates the console session and rewrites those two headers.
* **``compat.maxTokensField = max_tokens``** is not cosmetic. Left alone,
  OpenClaw sends ``max_completion_tokens``; this service reads ``max_tokens``
  and would silently fall back to its 512-token default, truncating every
  answer. Measured by capturing the request body with a mock /v1 server.
* **``compat.thinkingFormat = qwen``** tells OpenClaw this service returns the
  reasoning trace in ``reasoning_content`` (the DeepSeek/Qwen convention).
* **``contextWindow`` is mandatory**: without it OpenClaw assumes 200 000
  tokens and will happily build a prompt the model cannot take.
* **``NODE_OPTIONS`` is deliberately not set.** OpenClaw's ``worker-heap-flag.mjs``
  turns any ``--max-old-space-size`` in ``NODE_OPTIONS`` into
  ``--max-old-space-size=0`` for worker isolates, i.e. the flag removes the
  per-worker cap instead of tightening it. Measured: 768 MB, 384 MB and no flag
  all peak at the same ~950 MB tree PSS.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tarfile
from pathlib import Path

from .spec import (
    MCP_SERVER_NAME as MCP_NAME,
    AgentError,
    AgentSpec,
    Artifact,
    FetchFn,
    InstallContext,
    ProgressFn,
    key_from_mcp_entry,
    mcp_headers,
    mcp_url,
    merge_mcp_server,
)

logger = logging.getLogger(__name__)

VERSION = "2026.10.7"
NODE_VERSION = "24.22.1"

# 18789 is OpenClaw's own default; an operator may well have one there already.
DEFAULT_PORT = 18790

# The prefix the reverse proxy serves and the Control UI is told to live under.
BASE_PATH = "/agents/openclaw"

PROVIDER = "cv84x6"

# 30 minutes: one answer is decoded at roughly 20 tokens/s on this board, so a
# 6k-token reply is five minutes of continuous decoding plus tool round trips.
REQUEST_TIMEOUT_S = 1800

# 16384 output tokens is about 10-14 minutes of decoding; capped at half the
# context so the prompt keeps the other half.
MAX_OUTPUT_TOKENS = 16384

# 1.6 GB: the gateway's process tree settles around 1.4 GB idle and reaches
# ~1.5-1.9 GB once a conversation has run (measured on the board 2026-10-27). A
# lower floor lets it start into the OOM killer, which may pick the model worker
# instead -- and killing a worker in the middle of an NPU launch can hang the
# TPU until a reboot. How much free memory this board actually has at that
# moment is what the check reads; it is not a fixed capacity.
MEMORY_FLOOR_BYTES = 1600 * 1024 * 1024

# The vendor's dfss mirror, first in every list because an offline board (and a
# customer site) cannot reach nodejs.org or the npm registry at all.
DFSS_DIR = "open@sophgo.com:/tools/cv84x6_llm_server/agents"

# Node publishes a checksum list next to the tarballs; the tarball's own pin
# lives in NODE_ARTIFACTS and the fetched list is cross-checked against it, so a
# silently re-published release is caught either way. The list is read from dfss
# first and nodejs.org second, so the cross-check also works offline.
SHASUMS_FILENAME = f"node-v{NODE_VERSION}-SHASUMS256.txt"
# sha256 of the list itself (identical on dfss and nodejs.org, checked
# 2026-10-26). Pinning it is what makes "the listing was reachable" into "the
# listing is the one this release was tested against" -- otherwise a listing
# from whoever answered could vouch for any bytes.
SHASUMS_SHA256 = "fdfbffc969c0f604beff0124d409b33a43b53f5c681d6220f80023e0d6df9dc4"

# The listing as an Artifact, so it goes through the same fetcher as everything
# else: dfss first, nodejs.org as the fallback, local override directory before
# both, and nothing outside dfss when the operator asked for offline.
SHASUMS_ARTIFACT = Artifact(
    urls=(
        f"dfss://{DFSS_DIR}/{SHASUMS_FILENAME}",
        f"https://nodejs.org/dist/v{NODE_VERSION}/{SHASUMS_FILENAME}",
    ),
    sha256=SHASUMS_SHA256,
)

NODE_ARTIFACTS = {
    "arm64": Artifact(
        urls=(
            f"dfss://{DFSS_DIR}/node-v{NODE_VERSION}-linux-arm64.tar.xz",
            f"https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-linux-arm64.tar.xz",
        ),
        sha256="dbabf7a1cbf947e6059ffad2c27b80041db97dea1e553b62afdee7f13fca336e",
        size=30978868,
    ),
    "x64": Artifact(
        urls=(
            f"dfss://{DFSS_DIR}/node-v{NODE_VERSION}-linux-x64.tar.xz",
            f"https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-linux-x64.tar.xz",
        ),
        sha256="6c172a9ab6718f7b801fb5a7bd486af2ee5e32758086a04b84fcce2aa77095e6",
        size=32026916,
    ),
}

# The npm package itself: what to ask npm for when there is no prebuilt archive.
PACKAGE = f"openclaw@{VERSION}"

# Prebuilt ``app/`` trees per architecture, built by pushing the package through
# this board's private Node (docs/DESIGN.md has the build recipe). The archive's
# top-level directory is ``app/``, which is exactly the layer name below, so
# unpacking it needs no rewriting. An architecture missing here installs through
# npm instead -- x64 has no prebuilt build yet.
APP_ARTIFACTS = {
    "arm64": Artifact(
        # No upstream equivalent exists for this one; dfss is the only remote,
        # and CV84X6_AGENT_ARTIFACT_DIR is how it is supplied before publication.
        urls=(f"dfss://{DFSS_DIR}/openclaw-{VERSION}-app-linux-arm64.tar.gz",),
        sha256="b7f1aad9dabf50fe8117508ef2bc5a9e0fda2d0cb3e147ee5867dca265f712d5",
        size=164854736,
    ),
}


class OpenclawSpec(AgentSpec):
    id = "openclaw"
    name = "OpenClaw"
    version = VERSION
    default_port = DEFAULT_PORT
    artifacts = NODE_ARTIFACTS
    # Through the reverse proxy, which strips the agent's DENY headers.
    embeddable = True
    # The UI refuses framing and must stay on this service's origin, so it is
    # reached at /agents/openclaw/ rather than at the gateway's own port.
    proxied = True
    # Startup is measured at 36-46 s on the board (14 plugins load first).
    start_timeout = 180.0
    executable = "openclaw"
    # installed() checks <dir>/<payload_root>/<executable>: the .bin entry is what
    # npm creates for the package's "bin": {"openclaw": ...} field.
    payload_root = "app/node_modules/.bin"
    # The API key goes into openclaw.json, so sync can read it back from there.
    key_in_config = True
    memory_floor_bytes = MEMORY_FLOOR_BYTES
    # Observed on the board: the gateway created an empty ``/tmp/openclaw``
    # (mode 0700) while starting. TMPDIR is set to the agent's own tree, so this
    # is the one path that still escapes it -- removing it on uninstall is what
    # makes "nothing left outside the data root" true.
    scratch_paths = ("/tmp/openclaw",)
    # Measured on the board 2026-10-27: the gateway tree settles around 1.4 GB
    # idle and ~1.9 GB after a conversation; the start-up peak is ~1.5 GB. The
    # card reports that cost only. Whether it fits beside a model is not a fixed
    # fact about "the board" -- the memory check answers it from the real free
    # memory at start time, and the card must not pre-empt that with a capacity.
    card_note = "预估内存：空闲约 1.4 GB，对话后约 1.9 GB。"

    # -- paths -----------------------------------------------------------
    @property
    def node_dir(self) -> str:
        return "runtime/node"

    def config_path(self, directory: Path) -> Path:
        return Path(directory) / "config" / "openclaw.json"

    def node_bin(self, directory: Path) -> Path:
        return Path(directory) / self.node_dir / "bin" / "node"

    def npm_bin(self, directory: Path) -> Path:
        return Path(directory) / self.node_dir / "bin" / "npm"

    def package_entry(self, directory: Path) -> Path:
        """The CLI module, run through the private Node.

        The ``.bin/openclaw`` shim starts with ``#!/usr/bin/env node``; naming the
        interpreter explicitly means the agent starts even if ``PATH`` is ever
        lost, and it is what the package's own docs recommend for embedders.
        """
        return Path(directory) / "app" / "node_modules" / "openclaw" / "openclaw.mjs"

    # -- install ---------------------------------------------------------
    async def install(
        self, directory: Path, fetch: FetchFn, arch: str | None = None,
        progress: ProgressFn | None = None,
    ) -> None:
        """Private Node, then the app payload: one directory tree, two steps."""
        from .spec import host_arch

        arch = arch or host_arch()
        directory = Path(directory)
        artifact = self.artifacts.get(arch)
        if artifact is None:
            raise AgentError(f"没有适用于 {arch} 架构的 Node 运行时")

        report = progress or (lambda d, t: None)
        for name in ("bin", "runtime", "app", "home", "config", "data", "cache",
                     "state", "tmp", "workspace", "logs"):
            (directory / name).mkdir(parents=True, exist_ok=True)

        # 1. Node. Downloaded and sha256-verified by the manager's fetcher, then
        #    cross-checked against Node's own SHASUMS256.txt.
        node_archive = await fetch(artifact, f"node-{NODE_VERSION}-{arch}", report)
        await self._verify_against_shasums(fetch, arch, report)
        self._unpack_node(Path(node_archive), directory)
        node = self.node_bin(directory)
        if not os.access(node, os.X_OK):
            raise AgentError("Node 运行时解包后不可执行")
        report(artifact.size or 0, artifact.size or 0)

        # 2. The app payload. The prebuilt archive is the offline path and needs
        #    no network; npm is the fallback, and it is the only option for an
        #    architecture with no prebuilt build.
        if await self._install_prebuilt(directory, fetch, arch, report):
            return
        await self._npm_install(directory, report)

    async def _install_prebuilt(
        self, directory: Path, fetch: FetchFn, arch: str, progress: ProgressFn,
    ) -> bool:
        """Unpack the prebuilt ``app/`` tree; False when there is none to be had.

        A missing archive (no build for this arch, not yet on dfss, no route to
        it) means "fall back to npm", because npm produces the same tree. A
        *corrupt* archive stays fatal -- the fetcher raises a sha256 error for
        it, and swapping a tampered 165 MB payload for a hidden npm run would
        bury exactly the event worth reporting.
        """
        app_artifact = APP_ARTIFACTS.get(arch)
        if app_artifact is None or not app_artifact.sources():
            # No prebuilt build for this architecture (x64): npm is the way the
            # task card prescribes, and it is what the prebuilt archive replaces.
            return False
        try:
            archive = await fetch(app_artifact, f"openclaw-{VERSION}-app-{arch}", progress)
        except AgentError as exc:
            if _is_checksum_error(exc):
                raise
            logger.info("prebuilt OpenClaw app unavailable (%s); falling back to npm", exc)
            return False
        self._unpack_app(Path(archive), directory)
        progress(app_artifact.size or 0, app_artifact.size or 0)
        if not self.package_entry(directory).is_file():
            raise AgentError("预构建包解压后找不到 openclaw 入口，安装包可能不完整")
        return True

    def _unpack_app(self, archive: Path, directory: Path) -> None:
        """Unpack the prebuilt tree into ``app/``, refusing escapes.

        The archive's top level is already the layer name, so its contents are
        moved in as they are; only the usual tar guard applies.
        """
        target = Path(directory) / "app"
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        staging = Path(directory) / "tmp" / "unpack-app"
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        try:
            with tarfile.open(archive) as tf:
                root = staging.resolve()
                for member in tf.getmembers():
                    if not str((staging / member.name).resolve()).startswith(str(root)):
                        raise AgentError(f"预构建包内含越界路径：{member.name}")
                tf.extractall(staging)
            entries = list(staging.iterdir())
            # The archive names its top directory app/, which is the layer this
            # goes into; merge its contents rather than nesting app/app.
            if len(entries) == 1 and entries[0].is_dir() and entries[0].name == "app":
                shutil.move(str(entries[0]), str(target))
            else:
                target.mkdir(parents=True, exist_ok=True)
                for entry in entries:
                    shutil.move(str(entry), str(target / entry.name))
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        shim = target / "node_modules" / ".bin" / "openclaw"
        if shim.is_symlink() or shim.is_file():
            shim.chmod(0o755)

    async def _verify_against_shasums(
        self, fetch: FetchFn, arch: str, progress: ProgressFn,
    ) -> None:
        """Cross-check the tarball against Node's published checksum list.

        The pinned sha256 in ``artifacts`` is already enforced by the fetcher;
        this second check catches the case where upstream re-published the
        release and our pin is the stale one -- then the operator gets both
        digests and can decide, instead of a "corrupt download" guess.

        The listing comes from dfss first (an offline board cannot reach
        nodejs.org) and nodejs.org second, and it is pinned by its own sha256:
        an unverified listing could vouch for any bytes, which would make this
        check worse than useless. No listing anywhere is not fatal -- the
        tarball's own pin has already verified what matters.
        """
        artifact = self.artifacts[arch]
        try:
            path = await fetch(SHASUMS_ARTIFACT, f"node-{NODE_VERSION}-SHASUMS256", progress)
            listing = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # not published, no route, or a rewritten list
            logger.info("no verified SHASUMS256.txt for Node %s (%s)", NODE_VERSION, exc)
            return
        expected = _checksum_for(listing, artifact.filename)
        if expected and expected != artifact.sha256:
            raise AgentError(
                f"Node {NODE_VERSION} 的 SHA256SUMS256.txt 与内置校验值不一致："
                f"清单是 {expected}，代码内置 {artifact.sha256}；"
                "可能是上游重新发布了该版本，请核对后再安装"
            )

    def _unpack_node(self, archive: Path, directory: Path) -> None:
        """Put the runtime at ``runtime/node`` without its wrapper directory."""
        target = directory / self.node_dir
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True)
        staging = directory / "tmp" / "unpack-node"
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        try:
            with tarfile.open(archive) as tf:
                root = staging.resolve()
                for member in tf.getmembers():
                    if not str((staging / member.name).resolve()).startswith(str(root)):
                        raise AgentError(f"Node 安装包内含越界路径：{member.name}")
                tf.extractall(staging)
            entries = list(staging.iterdir())
            if len(entries) == 1 and entries[0].is_dir():
                # node-v24.22.1-linux-arm64/ is how the archive was built, not
                # part of the layout this spec names.
                for child in entries[0].iterdir():
                    shutil.move(str(child), str(target / child.name))
            else:
                for entry in entries:
                    shutil.move(str(entry), str(target / entry.name))
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    async def _npm_install(self, directory: Path, progress: ProgressFn) -> None:
        """``npm install --prefix app openclaw@<version>`` with the private npm."""
        npm = self.npm_bin(directory)
        if not npm.exists():
            raise AgentError("私有 Node 运行时里没有 npm")
        directory = Path(directory)
        app = directory / "app"
        if app.exists():
            shutil.rmtree(app, ignore_errors=True)
        app.mkdir(parents=True, exist_ok=True)
        for sub in ("cache/npm", "home", "tmp"):
            (directory / sub).mkdir(parents=True, exist_ok=True)

        env = dict(os.environ)
        env.update({
            # npm keeps its cache and its dotfiles here; HOME is what stops it
            # from writing to the operator's real ~/.npm and ~/.npmrc.
            "HOME": str(directory / "home"),
            "npm_config_cache": str(directory / "cache" / "npm"),
            "PATH": f"{directory / self.node_dir / 'bin'}{os.pathsep}{env.get('PATH', '')}",
            "TMPDIR": str(directory / "tmp"),
            # An offline board reaches a mirror or nothing; a long read timeout
            # beats a failed install on a slow link (measured 137 s for 344
            # packages on the board).
            "npm_config_fetch_timeout": "600000",
            "npm_config_fetch_retries": "5",
            "npm_config_fund": "false",
            "npm_config_update_notifier": "false",
            "npm_config_loglevel": "error",
        })
        cmd = [
            str(npm), "install", "--prefix", str(app), PACKAGE,
            "--omit=dev", "--no-audit", "--no-fund",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(directory),
            env={k: str(v) for k, v in env.items() if v is not None},
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output: list[str] = []

        async def pump() -> None:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip()
                if not line:
                    continue
                output.append(line)
                del output[:-40]
                # npm's progress is deliberately not byte-based; report it as a
                # moving message so the console does not look stuck for minutes.
                progress(0, None)
                if len(output) > 400:
                    del output[:200]

        await pump()
        code = await proc.wait()
        if code != 0:
            tail = " / ".join(output[-3:]) or f"exit={code}"
            raise AgentError(f"npm 安装 openclaw 失败（exit={code}）：{tail}")
        if not self.package_entry(directory).is_file():
            raise AgentError("npm 安装完成但找不到 openclaw 入口，安装包可能不完整")
        shim = directory / "app" / "node_modules" / ".bin" / "openclaw"
        if shim.exists():
            shim.chmod(0o755)

    # -- configuration ---------------------------------------------------
    def write_config(self, directory: Path, ctx: InstallContext) -> None:
        path = self.config_path(directory)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.build_config(directory, ctx), indent=2, ensure_ascii=False))
        path.chmod(0o600)

    def build_config(self, directory: Path, ctx: InstallContext) -> dict:
        """The ``openclaw.json`` this service generates.

        Field names follow OpenClaw 2026.10.7's own zod schema (validated with
        ``openclaw config validate``), not a guess from the docs.
        """
        d = Path(directory)
        port = int(ctx.port or DEFAULT_PORT)
        models = [m for m in ctx.models]
        default = ctx.default_model or (models[0].id if models else "")

        model_entries = []
        for choice in models:
            context = max(2048, int(choice.context or 0))
            inputs = ["text", "image"] if choice.vision else ["text"]
            model_entries.append({
                "id": choice.id,
                "name": choice.id,
                # This service returns the trace in reasoning_content, and the
                # model does think when asked; both are true of Qwen on
                # CV84X6 with the vendor chat template.
                "reasoning": True,
                "input": inputs,
                # Mandatory: OpenClaw assumes 200 000 when it is absent, which
                # would build prompts this model cannot accept.
                "contextWindow": context,
                "maxTokens": min(MAX_OUTPUT_TOKENS, max(256, context // 2)),
                "compat": {
                    # Without this OpenClaw sends max_completion_tokens and this
                    # service falls back to 512 output tokens.
                    "maxTokensField": "max_tokens",
                    "thinkingFormat": "qwen",
                    # Tools are supported by this service; saying so explicitly
                    # keeps OpenClaw from stripping tool definitions.
                    "supportsTools": True,
                },
            })

        return {
            "gateway": {
                "mode": "local",
                "port": port,
                "bind": "loopback",
                "auth": {"mode": "token", "token": ctx.secret},
                "controlUi": {
                    # The reverse proxy serves exactly this prefix, so the UI's
                    # own assets and WebSocket stay same-origin in the browser.
                    "basePath": BASE_PATH,
                    # Only the loopback origins are listed because the proxy
                    # rewrites Origin to one of them (it has already required an
                    # admin session); a browser-supplied origin is never trusted
                    # directly, so no board IP has to be baked into the config.
                    "allowedOrigins": _origins(ctx),
                },
            },
            "logging": {"file": str(d / "logs" / "openclaw.log")},
            "agents": {
                "defaults": {
                    "model": {"primary": f"{PROVIDER}/{default}" if default else ""},
                    "thinkingDefault": "low" if ctx.thinking else "off",
                    "workspace": str(d / "workspace"),
                },
            },
            "models": {
                "providers": {
                    PROVIDER: {
                        "baseUrl": f"http://127.0.0.1:{ctx.service_port}/v1",
                        "apiKey": ctx.api_key,
                        "api": "openai-completions",
                        "timeoutSeconds": REQUEST_TIMEOUT_S,
                        "models": model_entries,
                    },
                },
            },
            "mcp": {"servers": self._mcp_servers(d, ctx)},
        }

    # -- MCP -------------------------------------------------------------
    def _mcp_servers(self, directory: Path, ctx: InstallContext) -> dict:
        """``mcp.servers``: this service's server, plus whatever the operator added.

        OpenClaw 2026.10.7 **does** support remote MCP servers. The schema is
        ``mcp.servers[<name>] = {url, transport, headers, enabled}`` with
        ``transport`` one of ``stdio`` / ``sse`` / ``streamable-http`` (read from
        the package's own zod schema, ``McpServerSchema`` in
        ``dist/zod-schema.root-support-*.mjs``). It was checked against the
        installed gateway with ``openclaw mcp probe``, which connects and lists
        tools -- the evidence is in ``docs/mcp.md`` -- so no stdio bridge is
        needed for this agent.

        ``transport`` is mandatory here even though an ``url`` alone would imply
        SSE: this endpoint is Streamable HTTP and offers no SSE stream, and SSE
        is exactly what OpenClaw would pick by default.
        """
        entry = {
            "url": mcp_url(ctx.service_port),
            "transport": "streamable-http",
            "headers": mcp_headers(ctx.api_key),
            "enabled": True,
        }
        return merge_mcp_server(_existing_servers(self.config_path(directory)), entry)

    def existing_key(self, directory: Path) -> str:
        try:
            data = json.loads(self.config_path(directory).read_text())
        except (OSError, json.JSONDecodeError):
            return ""
        key = ((data.get("models") or {}).get("providers") or {}).get(PROVIDER, {}).get("apiKey", "")
        # The MCP entry carries the same key and is the only copy when the
        # provider block has no models (installed with nothing loaded).
        return key or key_from_mcp_entry(
            ((data.get("mcp") or {}).get("servers") or {}).get(MCP_NAME))

    # -- running ---------------------------------------------------------
    def env(self, directory: Path, secret: str = "") -> dict[str, str]:
        d = Path(directory)
        env = super().env(directory, secret)
        env.update({
            "PATH": f"{d / self.node_dir / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
            # OpenClaw's own three knobs for "everything lives here": the config
            # file, the state database, and where agents may edit files.
            "OPENCLAW_HOME": str(d / "home"),
            "OPENCLAW_STATE_DIR": str(d / "state"),
            "OPENCLAW_CONFIG_PATH": str(self.config_path(d)),
            "OPENCLAW_WORKSPACE_DIR": str(d / "workspace"),
            # Never hand a restart to a detached child: the manager owns the
            # process, and a reparented gateway would outlive a stop.
            "OPENCLAW_NO_RESPAWN": "1",
            # V8's compile cache makes the 14-plugin startup measurably faster
            # on a cold start; keep it in the agent's own tree.
            "NODE_COMPILE_CACHE": str(d / "cache" / "node"),
            # An offline board must not wait on update/metadata lookups.
            "OPENCLAW_NO_AUTO_UPDATE": "1",
            "OPENCLAW_DISABLE_BONJOUR": "1",
        })
        return env

    def command(self, directory: Path, port: int) -> list[str]:
        return [
            str(self.node_bin(directory)),
            str(self.package_entry(directory)),
            "gateway", "run", "--port", str(port), "--bind", "loopback",
        ]

    # -- HTTP ------------------------------------------------------------
    def health_url(self, port: int) -> str:
        return f"http://127.0.0.1:{port}/health"

    def web_url(self, host: str, port: int, secret: str) -> str:
        """The proxied Control UI, as a path on this service.

        Deliberately relative: the console itself is served from the service
        origin, so a path resolves to whatever host the operator's browser is
        already using -- no board IP has to be guessed, and the URL keeps
        working from another machine. The token rides in the fragment, which
        is what OpenClaw's UI reads for a one-click login and which never
        reaches a server log.
        """
        return f"{BASE_PATH}/#token={secret}"

    def web_credentials(self, secret: str) -> tuple[str, str]:
        # OpenClaw's token mode has no username; the card shows the token.
        return ("", secret)


def _origins(ctx: InstallContext) -> list[str]:
    """Origins the gateway accepts a WebSocket from.

    The proxy normalises ``Origin`` to loopback before forwarding (it has
    already required an admin session), so loopback is all that is needed; an
    operator-declared public origin is added when configured, which is what
    makes a direct, un-proxied visit work too.
    """
    out = [
        f"http://127.0.0.1:{ctx.service_port}",
        f"http://localhost:{ctx.service_port}",
    ]
    for origin in getattr(ctx, "public_origins", []) or []:
        origin = origin.strip().rstrip("/")
        if origin and origin not in out:
            out.append(origin)
    return out


def _existing_servers(path: Path) -> dict:
    """The ``mcp.servers`` map already on disk, so a sync keeps the operator's.

    A config this service wrote has the block it wrote last time, and one an
    operator edited may also hold servers they added themselves. Both are read
    for the same reason: only the entry named
    :data:`spec.MCP_SERVER_NAME` is ours to replace.
    """
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    servers = ((data.get("mcp") or {}).get("servers") if isinstance(data, dict) else None)
    return servers if isinstance(servers, dict) else {}


def _checksum_for(listing: str, filename: str) -> str:
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == filename:
            return parts[0].lower()
    return ""


def _is_checksum_error(exc: AgentError) -> bool:
    """Whether a fetch failure means "the bytes are wrong", not "unreachable"."""
    return "校验失败" in str(exc)


SPEC = OpenclawSpec()
