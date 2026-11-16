"""DSH (DeepSeek Harness): an npm agent whose ``web`` profile is its UI.

DSH is not a binary either. ``@deepseek-ai/dsh`` is a launcher that composes a
*profile* -- an ordered stack of bundle patch layers -- and boots one of them as
the application. The profile this spec installs is ``web``: the browser UI plus
the agent, served by DSH's own HTTP listener. There is no headless variant here
because the console embeds the page (MYS-2293: "dsh 同样需要启动一个 web").

Everything below was measured on 0.2.1-rc.5, on 13.24 (x64) and on the CV84X6
board (arm64); the commands that produced each fact are named where it decides
code.

**One artifact, one private Node.** DSH's launcher needs a Node from 22.19 up
(the ``libreoffice-kit`` packages declare ``engines.node >=22.19.0``, and the
board ships 22.22.2, so the board's own interpreter would do). It is still given
the same private Node 24.22.1 OpenClaw installs, for one reason that outranks
the saving: two agents on one board must not be able to break each other by
disagreeing about the interpreter, and the private runtime is already fetched,
verified and shared. The tree is a single prebuilt ``app/`` archive -- the same
shape OpenClaw's offline payload has -- so installation is one unpack with no
npm, no registry and no compilation.

**Port 14099**, not DSH's own 3080 and not any of 14096/14097/14098/18790, so a
second DSH of the operator's own cannot collide. Loopback only: the browser
reaches it through this service's proxy, and nothing else should.

**The UI is an origin-root SPA, reached only through the proxy.** Its index
names ``./assets/...`` relative to a ``<base href="./">``, its RPC transport
fetches ``api/<endpoint>`` and opens ``new WebSocket(...)`` against
``document.baseURI``, and it stores no route in the address bar. So it needs
``prefix_root`` (the proxy strips ``/agents/dsh`` on the way up and keeps the
browser inside the prefix), which is what makes the embedded page work from
another subnet through the board's one forwarded port.

**Authentication is a launch token, and it is the proxy's job to spend it.**
DSH prints one line at startup -- ``dsh web: http://127.0.0.1:14099/?token=<43
chars>`` -- and that URL is the only way in: presenting the token mints a
signed, HttpOnly session cookie and 303-redirects to ``./``; every other request
(API and WebSocket alike) needs the cookie, and DSH also checks Host and Origin.
The token must never reach the console, its log view, or ``/api/agents``, so the
spec reads it out of the agent's own log, keeps it in memory, and hands it to the
proxy through :meth:`~app.agents.spec.AgentSpec.upstream_launch_url`. The proxy
spends it on the browser's first request and DSH's own cookie then carries the
session.

**Host/Origin.** The proxy already rewrites both to the service's loopback
origin for every proxied agent; DSH's fence accepts a loopback ``Host``
outright, and it compares the ``Origin`` only against the ``Host`` it was given
-- so one rewrite satisfies both, with no ``--trusted-host`` to enumerate and no
board address baked into a config file that has to keep working on the next
board.

**Configuration replaces, and the file is shared, so only our keys are touched.**
A patch replaces the targeted row's whole ``config``; it does not merge. The
profile's own ``cordis.patch.yml`` is also the file DSH's settings pages write,
which rules out the two obvious designs:

* writing to ``$DSH_HOME/cordis.patch.yml`` instead would shadow the profile
  layer for every row we name, and DSH's settings editor refuses to save a value
  an outer layer overrides (``ConfigEditor.edit`` compares the composed result
  and throws "overridden by a home patch or command-line overlay"). The models
  page would break.
* rewriting the profile layer from nothing would delete the plugins, MCP servers
  and rows the operator added in the UI.

So this spec owns *parts*, not a file: :func:`_merge_patch` replaces the config
of the rows it manages, keeps every other row byte-for-byte, and keeps every
``insert:`` block that does not carry an id it inserted.

**The model route is a key inside the shipped row, not a row of our own.** DSH
ships one ``llm-pi-ai`` row and its plugin cannot be mounted twice -- measured:
a second row with the same plugin name is refused with
``LlmError: configurable provider "amazon-bedrock" is already declared``
(``dsh-llm-pi-ai``'s ``apply`` registers its built-in provider set once per
process). So ``providers.<our name>`` is merged into that row, leaving every
*other* provider the operator added from DSH's Models page in place. Measured
layer order (last wins): bundle patches, the profile patch,
``$DSH_HOME/cordis.patch.yml``, ``--patch``; nothing else is written, so there is
one file to reason about.

**A broken MCP server is loud, not silent.** DSH's plugin logger writes nowhere:
its one exporter only buffers warnings for a ``StartupError`` report, so a
``mcp-client`` that exhausts its retries says nothing at all. With
``failOnStartupError`` the entry's failure reaches stdout as
``dsh: warning: 1 entry did not activate`` plus the cause, which is what lets
:meth:`DshSpec.runtime_warning` tell the operator instead of leaving them with an
agent that answers every request and has no tools.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path

from .spec import (
    MCP_SERVER_NAME as MCP_NAME,
    AgentError,
    AgentSpec,
    Artifact,
    FetchFn,
    InstallContext,
    ProgressFn,
    mcp_headers,
    mcp_url,
)

logger = logging.getLogger(__name__)

VERSION = "0.2.1-rc.5"

# The private Node the payload runs on, shared with OpenClaw's install: same
# tarball, same checksum, same layer name (``runtime/node``).
NODE_VERSION = "24.22.1"

# 3080 is DSH's own default; a second DSH of the operator's own may hold it.
DEFAULT_PORT = 14099

# The prefix the reverse proxy serves this UI on.
BASE_PATH = "/agents/dsh"

# The provider name this service appears under in DSH's model picker, and the
# only key inside DSH's shipped ``llm-pi-ai`` row this service writes. A name an
# operator recognises, and the one the MCP entry also uses.
PROVIDER = "cv84x6"

# 30 minutes: one tool-using turn on this board is minutes of prefill plus
# decoding at ~20 tok/s, and DSH's own default idles a stream out after 5.
REQUEST_TIMEOUT_MS = 1_800_000
STREAM_IDLE_TIMEOUT_MS = 1_800_000

# 16384 output tokens is ~10-14 minutes of decoding; capped at half the context
# so the prompt keeps the other half.
MAX_OUTPUT_TOKENS = 16384

# Measured on the board 2026-11-05: the web profile settles at ~430 MB RSS idle
# and ~470 MB after a conversation, in one process (no forked children). The
# floor is that cost with room for a loaded model's pages, not a copy of the
# board's capacity -- the check reads the real MemAvailable.
MEMORY_FLOOR_BYTES = 640 * 1024 * 1024

# The vendor's dfss mirror, first in every list because an offline board (and a
# customer site) cannot reach the npm registry at all.
DFSS_DIR = "open@sophgo.com:/tools/cv84x6_llm_server/agents"

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

# The prebuilt ``app/`` tree: ``npm install --omit=dev @deepseek-ai/dsh@<ver>``
# run on the target architecture, so every native dependency (node-pty, koffi,
# sharp, the landlock addon) is the right build and nothing compiles on the
# board. The archive's top-level directory is ``app/``, the layer name below.
APP_ARTIFACTS = {
    "arm64": Artifact(
        urls=(f"dfss://{DFSS_DIR}/dsh-{VERSION}-app-linux-arm64.tar.gz",),
        sha256="5d2a9307036a19b5fcd003fc604cab9d9ec8a47f639266e2acfc42c4349be96f",
        size=160794220,
    ),
}

# Where the launch token is printed, and what it looks like. The whole point of
# this pattern is that it is the *only* place the credential appears: DSH prints
# it once, on stdout, before the server answers anything.
LAUNCH_LINE = re.compile(r"dsh web:\s*(http://\S+/?\?token=[A-Za-z0-9_-]+)")

# What the token looks like once it has been read and must not be shown again.
# A fixed marker rather than an empty string: the line still says a URL was
# printed, which is what an operator diagnosing a broken handoff needs to know.
REDACTED = "token=<redacted>"

# DSH's own way of saying a plugin failed to activate. Its logger writes nowhere
# (see the module docstring), so this line on stdout is the *only* signal that a
# plugin -- in practice the MCP client -- gave up.
ACTIVATION_WARNING = re.compile(r"^dsh: warning: (\d+) entr(?:y|ies) did not activate", re.M)

# The per-plugin detail that follows that warning, e.g.
# ``mcp-cv84x6 (@deepseek-ai/dsh-mcp-client): Error: mcp-client(cv84x6): ...``.
# Named so the operator is told *which* plugin, not merely that something broke.
ACTIVATION_DETAIL = re.compile(r"^(\S+) \((@deepseek-ai/\S+)\): ", re.M)

# How many attempts DSH's MCP client makes before giving up (measured from
# ``@deepseek-ai/dsh-mcp-client``'s own ``RECONNECT_DEFAULTS``: 10 attempts,
# 500 ms doubling to a 30 s ceiling, so roughly 2.5 minutes end to end).
MCP_GIVE_UP_ATTEMPTS = 10

# How much of the end of ``agent.log`` is searched for the launch line and the
# activation warning. DSH prints both within a second of each other at startup,
# and the manager rotates the file at 10 MB, so the tail is where they are.
_LOG_SCAN_BYTES = 256 * 1024

# How long ``after_start`` waits for the launch line. Readiness is DSH's PWA
# manifest, which a different plugin publishes, so the two are not ordered;
# measured at well under a second, and the budget is generous for a loaded board.
LAUNCH_WAIT_S = 15.0

# The profile DSH boots. Fixed: the console embeds a page, so the web profile is
# the only one that makes sense here.
PROFILE = "web"

# Where the agent's patch layer goes under DSH_HOME. ``profiles/<name>/`` is
# DSH's own layer and its settings pages rewrite it, so provisioning a profile
# means writing the two files DSH creates on first use.
PROFILE_FILES = ("package.json", "pnpm-workspace.yaml", "cordis.patch.yml")
PROFILE_BUNDLES = ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app"]

# The id of the row this spec writes its model route into. It is DSH's own
# shipped row: ``dsh-llm-pi-ai`` cannot be mounted twice -- a second row with the
# same plugin is refused with ``LlmError: configurable provider "amazon-bedrock"
# is already declared`` (measured; its ``apply`` registers the built-in provider
# set once per process). So this service contributes one *provider key* inside
# that row rather than a row of its own.
ROUTE_ROW = "llm-pi-ai"

# The ids this service owns in the profile patch, with the part of each it owns.
# A merge replaces exactly what is listed here and leaves every other byte of the
# file alone, which is what makes an operator's edits in DSH's own settings pages
# survive a reset or a sync.
#
# ``llm-pi-ai`` is the interesting one: this service owns only
# ``providers.cv84x6`` inside it, because the operator's own providers live in
# the same row and DSH's Models page writes them there. See :func:`_merge_patch`.
OWNED_ROWS = (
    "agent-default-model",
    "session-telemetry-otel",
    "sandbox-policy",
    "approval",
    "permission",
    "working-directory",
    "workspace-controller",
    "ui-settings-models",
    "mcp-" + MCP_NAME,
)

# Rows where this service owns one nested key rather than the whole ``config``.
# ``{row id: (key path, ...)}``. Everything else in such a row -- including every
# other top-level key -- is kept as the operator left it.
OWNED_KEYS: dict[str, tuple[str, ...]] = {
    ROUTE_ROW: ("providers", PROVIDER),
}

PATCH_HEADER = (
    "# This profile's own patch layer, applied after every bundle.\n"
    "#\n"
    "# The rows for the dsh agent's model route, MCP server and filesystem policy\n"
    "# are written by cv84x6-llm-server on every start and sync; every other row\n"
    "# here -- plugins, MCP servers and settings added from DSH's own pages -- is\n"
    "# left exactly as it is.\n"
)


class DshSpec(AgentSpec):
    id = "dsh"
    name = "DSH"
    version = VERSION
    default_port = DEFAULT_PORT
    artifacts = NODE_ARTIFACTS
    # Measured: the index carries no X-Frame-Options and no CSP
    # frame-ancestors, and the proxy serves it under this origin, so the page
    # frames as-is once the cookie exists.
    embeddable = True
    # The launcher binds loopback on a port no browser on another subnet can
    # reach; ``/agents/dsh/`` is the only address that works from a customer
    # site, and the token exchange has to happen server-side anyway.
    proxied = True
    # An origin-root app: ``./assets/...`` against ``<base href="./">``,
    # ``api/<endpoint>`` from ``document.baseURI``, and a WebSocket built the
    # same way. Served under a prefix, every one of those leaves it unless the
    # proxy strips the prefix and keeps the browser inside it.
    prefix_root = True
    # DSH's fence compares Origin against the request's own Host, so the proxy
    # has to send one authority in both headers (see ``_handoff_page``'s caller).
    origin_is_host = True
    # DSH gzips HTML above 1 KiB when the request says it accepts gzip, and this
    # proxy rewrites HTML -- a gzip stream cannot be prefix-rewritten without
    # decompressing it first (measured: ``zlib.error: incorrect header check``
    # and an empty page). Scoped to this agent: opencode is ``prefix_root`` too
    # and never compressed.
    identity_encoding = True
    # This agent's config file is DSH's own settings file, so a reset must not
    # take the operator's rows with it. The file is carried across the wipe and
    # merged again by ``write_config``.
    reset_keep = ("data/dsh/profiles/web/cordis.patch.yml",)
    # Measured on 13.24: the launcher answers its listener in ~20 s from a cold
    # start (307 packages of plugin code load first); a loaded board is slower.
    start_timeout = 180.0
    executable = "dsh"
    # installed() checks <dir>/app/node_modules/.bin/dsh, the shim npm creates
    # for the package's "bin": {"dsh": ...} field.
    payload_root = "app/node_modules/.bin"
    # The API key is written into the home patch, so a sync recovers it there.
    key_in_config = True
    memory_floor_bytes = MEMORY_FLOOR_BYTES
    # Measured on the bundle's own behaviour: DSH keeps its session logs,
    # storages and workspace records under $DSH_HOME (which this spec points at
    # <agent>/data/dsh), and its workspace defaults to the launch directory
    # (which the manager sets to <agent>/workspace). Nothing escapes.
    card_note = "预估内存：空闲约 430 MB，对话后约 470 MB。"

    def __init__(self, **overrides) -> None:
        super().__init__(**overrides)
        #: ``<agent dir> -> the launch URL of the process running *now*``.
        #:
        #: A token belongs to one process and dies with it, so this cache is only
        #: ever right for the current lifetime. It is therefore keyed on more than
        #: the directory: :meth:`launch_url` compares the log's own identity
        #: before trusting a remembered value, and :meth:`forget_launch_url` is
        #: called before every start. Keeping a stale entry is not a small bug --
        #: it makes ``/agents/dsh/`` answer 503 for good after the first restart,
        #: because the proxy would keep spending a token the new process never
        #: minted.
        self._launch_cache: dict[str, tuple[tuple[int, int, bytes], str]] = {}
        #: ``<agent dir> -> (log identity, activation warning)``, same idea for
        #: :meth:`runtime_warning`, which the console polls.
        self._warning_cache: dict[str, tuple[tuple[int, int, bytes], str]] = {}
        #: ``<agent dir> -> agent.log size at the moment this lifetime started``.
        #: What separates "this process reported a problem" from "an earlier
        #: process did", since the file is append-only across restarts.
        self._log_start: dict[str, int] = {}

    # -- paths -----------------------------------------------------------
    @property
    def node_dir(self) -> str:
        return "runtime/node"

    def node_bin(self, directory: Path) -> Path:
        return Path(directory) / self.node_dir / "bin" / "node"

    def package_entry(self, directory: Path) -> Path:
        """The launcher module, run through the private Node.

        The ``.bin/dsh`` shim starts with ``#!/usr/bin/env node``; naming the
        interpreter explicitly means the agent starts even if ``PATH`` is ever
        lost. Resolving the real path rather than the shim also keeps
        ``/proc/<pid>/exe`` stable for the manager's adoption check.
        """
        return (Path(directory) / "app" / "node_modules" / "@deepseek-ai"
                / "dsh" / "lib" / "bin.js")

    def dsh_home(self, directory: Path) -> Path:
        """``DSH_HOME``: profiles, sessions, storages, credentials.

        Under ``data/`` on purpose rather than ``home/``: a reset wipes the
        agent's derived state, and every one of these is derived -- the profile
        manifest, the signed-cookie secret and the session logs all have to go
        with it, or a reset would leave DSH holding a secret the console no
        longer knows and a config this service is about to replace.
        """
        return Path(directory) / "data" / "dsh"

    def profile_patch_path(self, directory: Path) -> Path:
        """The layer this service writes: ``profiles/web/cordis.patch.yml``.

        The same file DSH's settings pages write. It is shared by design -- see
        the module docstring -- so every write goes through :func:`_merge_patch`,
        which owns the rows this service manages and leaves the rest alone.
        """
        return self.dsh_home(directory) / "profiles" / PROFILE / "cordis.patch.yml"

    def config_path(self, directory: Path) -> Path:
        """What ``write_config`` writes, and where the key is read back from."""
        return self.profile_patch_path(directory)

    def workspace(self, directory: Path) -> Path:
        return Path(directory) / "workspace"

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

        node_archive = await fetch(artifact, f"node-{NODE_VERSION}-{arch}", report)
        _unpack_node(Path(node_archive), directory / self.node_dir,
                     directory / "tmp")
        node = self.node_bin(directory)
        if not os.access(node, os.X_OK):
            raise AgentError("Node 运行时解包后不可执行")
        report(artifact.size or 0, artifact.size or 0)

        app_artifact = APP_ARTIFACTS.get(arch)
        if app_artifact is None:
            raise AgentError(f"没有适用于 {arch} 架构的 DSH 安装包")
        archive = await fetch(app_artifact, f"dsh-{VERSION}-app-{arch}", report)
        _unpack_app(Path(archive), directory / "app", directory / "tmp")
        if not self.package_entry(directory).is_file():
            raise AgentError("预构建包解压后找不到 dsh 入口，安装包可能不完整")
        report(app_artifact.size or 0, app_artifact.size or 0)
        shim = directory / "app" / "node_modules" / ".bin" / "dsh"
        if shim.is_symlink() or shim.is_file():
            shim.chmod(0o755)

    # -- configuration ---------------------------------------------------
    def write_config(self, directory: Path, ctx: InstallContext) -> None:
        """Provision the profile and merge this service's rows into its patch."""
        self._write_profile(Path(directory))
        path = self.config_path(directory)
        path.parent.mkdir(parents=True, exist_ok=True)
        merged = _merge_patch(
            _read_text(path), self.build_blocks(directory, ctx), OWNED_ROWS,
            OWNED_KEYS)
        path.write_text(merged, encoding="utf-8")
        path.chmod(0o600)
        self.workspace(directory).mkdir(parents=True, exist_ok=True)

    def _write_profile(self, directory: Path) -> None:
        """Create ``profiles/web`` the way DSH's own first boot would.

        DSH auto-initializes a shipped profile when its directory has no
        ``package.json``, but it does that *after* the launcher has already read
        the layers -- so provisioning it here is what makes the very first start
        read our patch instead of writing a fresh empty one over nothing. The
        files are DSH's own three, and an existing one is never rewritten: the
        operator's bundle selection and edits are theirs.
        """
        profile = self.dsh_home(directory) / "profiles" / PROFILE
        profile.mkdir(parents=True, exist_ok=True)
        manifest = profile / "package.json"
        if not manifest.exists():
            manifest.write_text(json.dumps({
                "name": f"dsh-profile-{PROFILE}",
                "private": True,
                "dependencies": {},
                "dsh": {"profile": {"bundles": list(PROFILE_BUNDLES)}},
            }, indent=2) + "\n", encoding="utf-8")
        workspace = profile / "pnpm-workspace.yaml"
        if not workspace.exists():
            workspace.write_text(
                "packages:\n  - .\n\nnodeLinker: hoisted\nautoInstallPeers: false\n",
                encoding="utf-8")
        patch = profile / "cordis.patch.yml"
        if not patch.exists():
            patch.write_text(PATCH_HEADER + "[]\n", encoding="utf-8")

    def build_blocks(self, directory: Path, ctx: InstallContext) -> list[str]:
        """The patch blocks this service owns, as YAML text.

        A patch *replaces* the whole ``config`` of the row it names (measured:
        ``dsh --dump-config`` after a patch holding one key shows that key and
        nothing else), so every row here states all of its keys.
        """
        d = Path(directory)
        default = ctx.default_model or (ctx.models[0].id if ctx.models else "")
        thinking = bool(ctx.thinking)

        blocks = [
            _row("agent-default-model", self._default_model_config(default, thinking)),
        ]
        if ctx.models:
            blocks.append(_row(ROUTE_ROW, self._route_config(ctx)))
        # Telemetry: DSH's default mode ships feedback-triggered session logs to
        # its own OTLP collector. A board on a customer site has no route to it,
        # so the exporter would only ever time out; DISABLED constructs no
        # transport at all.
        blocks.append(_row("session-telemetry-otel", {"mode": "DISABLED"}))
        # The agent's own filesystem boundary. workspace-write lets the bash and
        # file tools work inside <agent>/workspace and refuses everything else,
        # which is the same promise the other three agents make.
        blocks.append(_row("sandbox-policy", {
            "mode": "workspace-write",
            "workspaceRoot": str(self.workspace(d)),
        }))
        # DSH's approval policy for a sandbox escalation ("may I write outside
        # the workspace?"). Nobody is watching a console-embedded page for a
        # prompt, so the answer is no: the tool fails and the model is told.
        blocks.append(_row("approval", {"policy": "never"}))
        # The Permissions selector bundles the two settings above into one named
        # mode, and it *refuses to start* when the composed pair matches none of
        # its presets -- measured: ``permission: composed sandbox and approval
        # defaults match no preset; configure defaultPreset explicitly``, which
        # arrives as a "1 entry did not activate" warning and a `/permission`
        # command that cannot be used. The shipped table pairs workspace-write
        # with ``ask``; pairing it with ``never`` needs the table restated.
        blocks.append(_row("permission", {
            "presets": {
                "workspace-write": {"sandbox": "workspace-write",
                                    "approval": "never"},
                "danger-full-access": {"sandbox": "danger-full-access",
                                       "approval": "never"},
            },
            "defaultPreset": "workspace-write",
        }))
        # Where a session without one starts. DSH's default is the launch
        # directory, which the manager already sets to <agent>/workspace -- but
        # naming it keeps the two from drifting if DSH changes that default.
        blocks.append(_row("working-directory",
                           {"defaultDirectory": str(self.workspace(d))}))
        # Where DSH puts its first workspace. Left alone it asks the desktop for
        # the system Documents folder -- ``xdg-user-dir DOCUMENTS``, which on a
        # board with no ``~/文档`` answers the home directory, and that is
        # rejected outright. The page then comes up with "Unable to create
        # default workspace. Use Choose workspace to select a folder" and no
        # message box can be sent until the operator picks a folder through a
        # native dialog. Measured on 13.24 and on the board.
        blocks.append(_row("workspace-controller", {
            "documentsDirectory": str(self.workspace(d)),
        }))
        # The first-run "sign in to DeepSeek or add an API Key" gate. This
        # service *is* the model provider and its key is already in the route
        # above, so there is nothing for the operator to paste -- and the gate
        # covers the composer until they do.
        blocks.append(_row("ui-settings-models", {"credentialOnboarding": False}))
        blocks.append(_insert_row(mcp_url(ctx.service_port), ctx.api_key))
        return blocks

    def build_config(self, directory: Path, ctx: InstallContext) -> str:
        """The complete patch document this service would write from scratch.

        Kept separate from ``write_config`` (which merges) because a test and a
        human both want to read what this spec generates without a file to
        compare against.
        """
        return PATCH_HEADER + "\n".join(self.build_blocks(directory, ctx))

    def _default_model_config(self, model: str, thinking: bool) -> dict:
        """Which route and model a fresh session starts on, and how it thinks.

        ``reasoningEffort`` has to be stated: DSH's own default is ``high``,
        and a model route that declares no reasoning levels refuses any effort
        but ``off`` (measured: ``UNSUPPORTED_REASONING_EFFORT: provider
        "cv84x6" model "..." does not support reasoning effort "off"`` came from
        *not* declaring them -- see ``_route_config``). Stating ``off`` makes
        the default explicit instead of left to a default that may change.
        """
        # ``provider``/``model`` are *required* fields of the row's own schema
        # (measured: ``$.provider missing required value`` -- and the failure is
        # not a warning, the row fails to activate and every consumer waiting on
        # ``agentDefaultModel`` stays pending, so the web UI never becomes
        # usable). An empty model list therefore still has to name the route;
        # the model id is then simply one no request can select, which is the
        # honest state of "installed while nothing is loaded".
        config: dict = {
            "provider": PROVIDER,
            "model": model,
            "reasoningEffort": "low" if thinking else "off",
        }
        return config

    def _route_config(self, ctx: InstallContext) -> dict:
        """The local OpenAI-compatible route under its own pi-ai row.

        Field names come from ``dsh-llm-pi-ai``'s own configuration schema, and
        the wire result was captured from a mock ``/v1``:

        * ``compat.maxTokensField: max_tokens`` is not cosmetic. pi-ai's
          default is ``max_completion_tokens``; this service reads
          ``max_tokens`` and would otherwise fall back to its 512-token default,
          truncating every answer. Measured: with the switch, the body carries
          ``max_tokens: 16384`` and no ``max_completion_tokens``.
        * ``reasoningEfforts`` is what turns thinking *off* on the wire. A
          model that declares none is reported as supporting only ``off``, and
          pi-ai translates that to *omitting* the parameter -- so a template
          whose default is to think keeps thinking. Declaring the levels with
          ``compat.thinkingFormat: qwen`` makes ``off`` an explicit
          ``enable_thinking: false``, measured in the captured body.
        * ``timeoutMs`` / ``streamIdleTimeoutMs``: this board decodes at about
          20 tokens/s, and pi-ai's 5-minute stream idle default would abort a
          long answer mid-flight.
        * ``input`` follows whether the model's own graphs take images, the same
          rule the other three agents get.
        """
        models = []
        for choice in ctx.models:
            context = max(2048, int(choice.context or 0))
            entry: dict = {
                "id": choice.id,
                "name": choice.id,
                "contextWindow": context,
                "maxTokens": min(MAX_OUTPUT_TOKENS, max(512, context // 2)),
                # pi-ai wants the offered levels and their wire spellings;
                # ``off`` is the one level that may leave the value empty, which
                # is what makes it "omit the effort, but say don't think".
                "reasoningEfforts": {"off": None, "low": "low", "high": "high"},
                "input": ["text", "image"] if choice.vision else ["text"],
            }
            models.append(entry)
        return {
            "providers": {
                PROVIDER: {
                    "displayName": "CV84X6 本机",
                    "api": "openai-completions",
                    "baseURL": f"http://127.0.0.1:{ctx.service_port}/v1",
                    # The key rides in a header rather than through
                    # ``apiKeyEnv``: an env reference would have to be exported
                    # into the agent's process, and this file is already 0600
                    # and already holds the key in the MCP block.
                    "headers": _bearer(ctx.api_key),
                    "models": models,
                    "compat": {
                        "maxTokensField": "max_tokens",
                        "thinkingFormat": "qwen",
                        # DSH's instructions (persona, runtime context, tool
                        # guidance) go out as a ``developer`` message whenever
                        # the model is a reasoning one, which every pi-ai route
                        # treats as "real OpenAI". This service's schema accepts
                        # ``system``/``user``/``assistant``/``tool`` only, so the
                        # first turn died with
                        # ``422 ... role: Input should be 'system', 'user',
                        # 'assistant' or 'tool'``. Measured on a loaded 35B.
                        "supportsDeveloperRole": False,
                    },
                    "timeoutMs": REQUEST_TIMEOUT_MS,
                    "streamIdleTimeoutMs": STREAM_IDLE_TIMEOUT_MS,
                },
            },
        }

    def existing_key(self, directory: Path) -> str:
        """The API key already in this service's own rows, or "".

        Read out of the MCP block first: that copy survives when no model is
        loaded (with an empty model list there is no route at all). Falling back
        to the route row is only for a file whose MCP row an operator removed.

        Scoped to *our* blocks, not "the first ``Authorization:`` in the file".
        The file is shared with DSH's own settings pages, so an operator's
        unrelated MCP server with its own bearer token sits in the same document
        -- reading that one would hand the wrong credential to every agent
        request and, worse, overwrite it on the next sync.
        """
        text = _read_text(self.config_path(directory))
        if not text:
            return ""
        for row_id, block in _block_index(_split_blocks(text)):
            if row_id not in ("mcp-" + MCP_NAME, ROUTE_ROW):
                continue
            key = _bearer_in(block)
            if key:
                return key
        return ""

    # -- running ---------------------------------------------------------
    def env(self, directory: Path, secret: str = "") -> dict[str, str]:
        d = Path(directory)
        env = super().env(directory, secret)
        env.update({
            "PATH": f"{d / self.node_dir / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
            # Everything DSH persists -- profiles, sessions, storages, the
            # cookie secret -- lives under here, and nowhere else.
            "DSH_HOME": str(self.dsh_home(d)),
            # An offline board must not spend its first turn on a network lookup.
            "npm_config_update_notifier": "false",
        })
        return env

    def command(self, directory: Path, port: int) -> list[str]:
        """Launcher flags first, then the web app's own.

        The order is mandatory, not stylistic: the launcher parses only its own
        options and hands *everything after the first token it does not
        recognise* to the profile's app. Putting ``--port`` first (the natural
        way to write it) makes ``--patch`` an app flag, and the app rejects it
        -- measured: ``error: unknown option '--patch'``.
        """
        return [
            str(self.node_bin(directory)),
            str(self.package_entry(directory)),
            "--profile", PROFILE,
            "--no-open",
            "--port", str(int(port)),
        ]

    # -- HTTP ------------------------------------------------------------
    def health_url(self, port: int) -> str:
        """The one endpoint DSH answers without a session.

        There is no ``/health``: every path under ``/`` and ``/api`` is behind
        the cookie and answers 401, which is exactly what a readiness probe must
        not accept as ready. ``/manifest.webmanifest`` is the web app's own PWA
        manifest -- public because a browser fetches it before anyone logs in --
        and it serves only once the plugin tree has settled, which is the thing
        worth waiting for. Measured: 200 on a booted instance, 404 before.
        """
        return f"http://127.0.0.1:{port}/manifest.webmanifest"

    def web_url(self, host: str, port: int, secret: str) -> str:
        """The proxied UI, as a relative path on this service.

        Relative like the other proxied agents: the console is served from the
        service origin, so this resolves against whatever host the browser
        already used. There is no credential in it -- the proxy spends the
        launch token on the first request.
        """
        return f"{BASE_PATH}/"

    def web_credentials(self, secret: str) -> tuple[str, str]:
        # Nothing for the operator to type or copy: the proxy logs the browser in.
        return ("", "")

    # -- the launch token ------------------------------------------------
    def forget_launch_url(self, directory: Path) -> None:
        """Start a new process lifetime: drop the old token, note where the log is.

        Called by the manager in ``_spawn``, which is the one place every launch
        goes through (a console start, a restart, and the supervisor's own
        respawn), so this is the exact moment a new lifetime begins.

        Three things, each fixing a measured failure:

        * the in-process cache of :meth:`launch_url`;
        * ``state/launch-url``, which exists so a *service* restart can adopt a
          still-running agent -- and which therefore survives an *agent* restart
          unless it is cleared here;
        * the log offset this lifetime starts at. ``agent.log`` is append-only,
          so everything above that offset belongs to *this* process and
          everything below it belongs to one that is gone.

        Without the first two the proxy kept spending the previous process'
        token after a restart: DSH answered 401, the handoff gave up, and
        ``/agents/dsh/`` stayed 503 until the whole service was restarted.
        Measured, and the reason the review asked for this.

        A service restart must still adopt, so this is *not* called from a
        constructor; only from a launch.
        """
        directory = Path(directory)
        self._launch_cache.pop(str(directory), None)
        self._log_start[str(directory)] = self._log_size(directory)
        try:
            _saved_url_path(directory).unlink(missing_ok=True)
        except OSError:  # pragma: no cover - a read-only state dir is the host's problem
            logger.warning("dsh: could not clear the saved launch URL")

    def launch_url(self, directory: Path) -> str:
        """The tokenized URL the process running *now* printed, or "".

        Two places, in the order they are trusted, because each covers a case the
        others cannot:

        1. **the agent's own log** -- where DSH prints it, and the authority on
           which process is current;
        2. **``state/launch-url``** (mode 0600) -- written when the line is read,
           so a *service* restart can still hand a running DSH's token over.
           Without it, adopting the still-running process after a restart leaves
           the page 401ing for good, which is exactly the "重启服务后能接管" case.

        Only the *last* match in the log is used: the supervisor restarts a
        crashed agent, and each process mints a fresh token, so an older line
        names a credential that no longer works.

        The answer is cached, but the cache is keyed on the log's
        ``(size, mtime, last launch line)`` as well as the directory: an agent
        that restarted has appended a new line, so the key changes and the old
        value cannot be served. That check is what makes the cache safe even if
        :meth:`forget_launch_url` is somehow missed, and it is cheap -- one
        ``stat`` and a 256 KiB tail read per call.
        """
        directory = Path(directory)
        found, key = self._scan_log(directory)
        cached = self._launch_cache.get(str(directory))
        if found and cached is not None and cached[0] == key:
            return cached[1]
        if found:
            self._launch_cache[str(directory)] = (key, found)
            return found
        if self._log_start.get(str(directory)) is not None:
            # Launched by us and not printed yet: nothing usable, and the saved
            # copy (cleared at launch) would only ever be a previous token.
            return ""
        # No line in the log (a rotated or truncated file): fall back to the
        # saved copy, which is the adoption-after-service-restart path.
        return _read_saved_url(directory)

    def _scan_log(self, directory: Path) -> tuple[str, tuple[int, int, bytes]]:
        """The last launch line in the log, plus the identity of what was read.

        ``("", (0, 0, b""))`` when the log cannot be read at all, so a caller can
        tell "no file" from "file with no line".
        """
        text, key, base = self._read_log_tail(Path(directory))
        # After a launch from this service, only what that process printed is
        # current: the previous process' line sits above it in the same
        # append-only file and names a token that no longer works. Without a
        # recorded start (a DSH adopted after a service restart) the whole tail
        # is searched and the last line wins.
        start = self._log_start.get(str(directory))
        if start is not None:
            text = text[max(0, start - base):]
        found = LAUNCH_LINE.findall(text)
        return (found[-1] if found else ""), key

    @staticmethod
    def _read_log_tail(directory: Path) -> tuple[str, tuple[int, int, bytes], int]:
        """The last ``_LOG_SCAN_BYTES`` of ``agent.log``, its identity, and where
        that tail starts in the file.

        The identity is ``(size, mtime_ns, digest of the tail)``: size and mtime
        alone notice an append, and the digest catches a rotating log replaced by
        a same-sized one within the same timestamp tick. The returned offset is
        what lets a caller subtract the tail's base from an absolute position.
        """
        path = Path(directory) / "logs" / "agent.log"
        try:
            stat = path.stat()
            with open(path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                start = max(0, size - _LOG_SCAN_BYTES)
                fh.seek(start)
                raw = fh.read()
        except OSError:
            return "", (0, 0, b""), 0
        return (raw.decode("utf-8", "replace"),
                (stat.st_size, stat.st_mtime_ns, _digest(raw)), start)

    @staticmethod
    def _log_size(directory: Path) -> int:
        """How much ``agent.log`` holds right now (0 when it does not exist)."""
        try:
            return (Path(directory) / "logs" / "agent.log").stat().st_size
        except OSError:
            return 0

    def upstream_launch_url(self, directory: Path, port: int) -> str | None:
        """What the proxy asks DSH for on the browser's first visit.

        DSH mints its cookie **only** for ``GET /`` carrying exactly one
        ``?token=`` and no session, answering 303 + ``Set-Cookie`` -- so the
        proxy's first request has to be that URL, not the page path the browser
        asked for.

        ``""`` (not ``None``) when no token has been printed yet: this agent
        *does* use a launch token, so "there is nothing to hand over" is a state
        to explain to the operator, not a reason to forward the request. ``None``
        is reserved for agents that never hand anything over -- see
        :meth:`AgentSpec.upstream_launch_url`.
        """
        url = self.launch_url(directory)
        if not url:
            return ""
        return _loopback(url, port)

    def redact_from_log(self, directory: Path) -> None:
        """Persist the launch URL so the handoff outlives the file's content.

        The credential is taken out of the *route* that serves logs
        (:meth:`public_log`), and kept in memory for the life of the process plus
        ``state/launch-url`` for the life of the installation.

        The file itself is deliberately left alone. An earlier version rewrote
        it in place, and that is unsafe by construction: the manager hands this
        exact file to the running agent as its stdout, so the agent holds its own
        offset into it. Rewriting a prefix and truncating discards whatever the
        agent wrote between the read and the truncate, and leaves the writer's
        offset past the new end -- measured: the log came back as just the
        (redacted) launch line, with every diagnostic after it gone. Losing the
        agent's own errors to hide a token from a file nobody serves is a bad
        trade; the endpoint filter is what the requirement actually asks for.
        """
        url = self.launch_url(directory)  # remember before anything rotates it
        if url:
            _save_url(Path(directory), url)

    def public_log(self, text: str) -> str:
        """``dsh web: http://...?token=<secret>`` with the secret removed.

        The shape is preserved so the operator can still see DSH printed a URL;
        only the credential becomes a fixed marker. Everything else a token
        could look like -- the cookie it mints is a different string and never
        appears in the log -- is left alone.
        """
        return LAUNCH_LINE.sub(
            lambda m: re.sub(r"token=[A-Za-z0-9_-]+", REDACTED, m.group(0)), text)

    # -- multi-process agents --------------------------------------------
    async def after_start(self, directory: Path, ctx: InstallContext,
                          port: int) -> str:
        """Wait for the launch line, then report what the start is missing.

        The listener can answer ``/manifest.webmanifest`` and still be useless in
        two different ways, and both are warnings rather than failed starts --
        the process is genuinely up, and a restart is the operator's call -- but
        neither may be silent:

        * **no launch token**: no browser can ever get a cookie, so the embedded
          page 401s forever;
        * **a plugin that did not activate**, in practice the MCP client: the
          agent answers every request and has no tools.

        The wait is what makes both deterministic. Readiness is the manifest,
        which DSH can serve a moment *before* it writes the launch line and the
        activation warning (they come from different plugins), and the manager
        redacts as soon as this hook returns -- so returning early would redact a
        log that has nothing to redact and then miss the token entirely.
        Measured on a cold start: the launch line lands within ~1 s of the
        manifest, and the activation warning lands within 40 ms of the launch
        line (it is printed while the loader settles, *before* the URL line).
        """
        url = ""
        for _ in range(int(LAUNCH_WAIT_S * 10)):
            url = self.launch_url(directory)
            if url:
                break
            await asyncio.sleep(0.1)
        # The activation warning is already on disk by the time the URL line is
        # (measured: 40 ms earlier), so a plugin failure needs no extra wait.
        trouble = self._activation_warning(Path(directory)) if url else ""
        if not url:
            return (f"{self.name} 已监听 {port}，但日志里没有找到带 token 的启动地址；"
                    "控制台内嵌页会一直 401。请查看日志后重启该 agent")
        return trouble

    def runtime_warning(self, directory: Path) -> str:
        """Tell the operator when a plugin gave up while the agent kept running.

        The failure this exists for: DSH's MCP client retries ten times over
        ~2.5 minutes and then unregisters its tools. Its own logger writes
        nowhere (see the module docstring), so without ``failOnStartupError``
        there is *no* signal anywhere -- the measured log for a boot with a dead
        ``/mcp`` was a single line. With it, DSH prints
        ``dsh: warning: 1 entry did not activate`` plus the plugin and the cause,
        which is what this reads.

        Called on every status poll, so it is cached on the log's identity: the
        answer cannot change without the agent writing something.
        """
        return self._activation_warning(Path(directory))

    def _activation_warning(self, directory: Path) -> str:
        """The activation failure of the *running* process, as a sentence, or "".

        Scoped to this lifetime by the offset :meth:`forget_launch_url` recorded,
        because ``agent.log`` is append-only across restarts: an older process'
        warning sits above the current one's output, and reporting it after a
        successful restart would be a permanent lie about an agent that is now
        fine.

        Cached per log identity because the console polls: the scan reads 256 KiB
        and re-runs the regexes, which is wasted work on an unchanged file.
        """
        text, key, base = self._read_log_tail(directory)
        hit = self._warning_cache.get(str(directory))
        if hit is not None and hit[0] == key:
            return hit[1]
        start = self._log_start.get(str(directory))
        window = text if start is None else text[max(0, start - base):]
        message = _activation_message(window)
        self._warning_cache[str(directory)] = (key, message)
        return message

    def leftovers(self, directory: Path, port: int) -> list[int]:
        """Live DSH launchers of this agent that a stop must also reap.

        The launcher loads the app in-process, so a plain group signal takes
        everything -- this covers the case where the process left its group (or
        a supervisor re-parented it) and still holds the port. Every candidate
        is proved: some token of its command line must resolve to *this* agent's
        own launcher module, which is what keeps a stranger out.
        """
        from ..core import procs

        expected = self.package_entry(directory)
        agent_dir = str(Path(directory))
        found: list[int] = []
        try:
            candidates = procs.scan_processes()
        except Exception:  # pragma: no cover - /proc trouble means "cannot tell"
            return []
        for cand in candidates:
            names = [cand.exe or "", *cand.argv]
            if not any(procs.same_path(name, expected) for name in names if name):
                continue
            if not procs.is_under(cand.cwd, agent_dir):
                continue
            if procs.arg_value(cand.argv, "--port") != str(int(port)):
                continue
            found.append(cand.pid)
        return found


# -- patch text ---------------------------------------------------------
def _merge_patch(existing: str, blocks: list[str], owned: tuple[str, ...],
                 owned_keys: dict[str, tuple[str, ...]] | None = None) -> str:
    """``existing`` with our parts replacing theirs, everything else kept.

    The card's rule -- "只改我们管理的键，保留用户在 DSH 设置页里改过的其他内容"
    -- has to hold against a file this service did *not* write: DSH's own
    settings pages save here, and an operator may have added plugins, MCP
    servers, or whole rows. So the patch is treated as a list of blocks, and
    only what is ours is replaced. Two kinds of ownership:

    * **a whole row** (``owned``): the block is replaced by the one this service
      generates. Every one of these rows is a row we address alone.
    * **one nested key of a shared row** (``owned_keys``): ``llm-pi-ai`` is DSH's
      own row *and* the row an operator's Models page writes, so replacing it
      wholesale would delete their providers. Only the named key path is merged
      into the existing block and every other line is kept. See
      :func:`_merge_row_key`.

    A block starts at a column-0 ``- `` line and runs to the next one. That is
    enough for this document because DSH's own template is a flat list of
    mappings, and a nested ``insert:`` list is indented under its parent. The
    parser is deliberately not a YAML parser: ``requirements.txt`` has none (it
    is kept vendor-light for the board) and this file's shape is fixed.

    Order is preserved where the old block was; new blocks go at the end, after
    anything the operator added. Insert blocks are handled as one block keyed by
    the ids they insert, so a second sync cannot append the MCP server twice.
    """
    owned_keys = owned_keys or {}
    old_blocks = _split_blocks(existing)
    ours = {row_id: text for row_id, text in _block_index(blocks)}
    out: list[str] = []
    written: set[str] = set()
    for row_id, text in _block_index(old_blocks):
        if row_id in owned:
            # One block per owned id. A file that somehow holds two copies of
            # ours is normalised rather than duplicated.
            if row_id in written:
                continue
            out.append(ours.get(row_id, ""))
            written.add(row_id)
        elif row_id in owned_keys and row_id in ours:
            if row_id in written:
                continue
            # Merge our key path into *their* block: the operator's other keys in
            # this same row survive, which is the whole point of doing it here.
            out.append(_merge_row_key(text, ours[row_id], owned_keys[row_id]))
            written.add(row_id)
        else:
            out.append(text)
    for row_id, text in _block_index(blocks):
        if row_id not in written:
            out.append(text)
    return PATCH_HEADER + "".join(out)


def _merge_row_key(their_block: str, our_block: str,
                   path: tuple[str, ...]) -> str:
    """``our_block``'s value at ``path`` inserted into ``their_block``.

    Only the *deepest* key of ``path`` is replaced. ``("providers", "cv84x6")``
    therefore swaps our provider inside DSH's ``providers:`` mapping and leaves
    every sibling provider -- the ones an operator added from the Models page --
    byte-for-byte. Replacing ``providers`` wholesale (the obvious reading of the
    same instruction) would delete exactly the content this merge exists to keep.

    Three cases, in order:

    1. the whole chain exists: splice our fragment in at the deepest key;
    2. some parent is missing: append the chain, since nothing of theirs can be
       lost by adding a key they never had;
    3. our own block does not carry the path (nothing to merge): return theirs
       unchanged -- never a half-rewritten row.

    Line surgery rather than YAML because the file's shape is fixed (see
    :func:`_merge_patch`).
    """
    lines = their_block.splitlines(keepends=True)
    ours = _key_block(our_block, path)
    if ours is None:
        return their_block
    if not _row_shape_ok(lines, path):
        # A shape the line splice cannot handle without risking invalid YAML
        # (flow style, block scalars, comments or odd indentation inside
        # ``config``, a ``config`` without the parent keys): write our row and
        # keep theirs, verbatim, as comments in it -- valid YAML, nothing lost.
        logger.warning("dsh: llm-pi-ai row has a shape that cannot be merged "
                       "line by line; replaced it and kept the original as comments")
        return _with_original_as_comments(our_block, their_block)
    replacement = ours.splitlines(keepends=True)
    if not replacement[-1].endswith("\n"):
        replacement[-1] += "\n"

    config_at = _find_key_line(lines, "config", 2)
    if config_at is None:
        # No config mapping at all: append ours, which states the whole chain.
        return _append_config(their_block, our_block)

    # Walk down to the parent of the deepest key. ``indent`` is where that
    # parent's children sit.
    indent = _indent_of(lines[config_at]) + 2
    for key in path[:-1]:
        at = _find_key_line(lines, key, indent)
        if at is None:
            return _append_config(their_block, our_block)
        indent = _indent_of(lines[at]) + 2

    if _find_key_line(lines, path[-1], indent) is None:
        # The parent exists but our key does not: append it after the parent's
        # last child, which is where a YAML reader would have written it.
        parent = path[-2] if len(path) > 1 else "config"
        at = _find_key_line(lines, parent, indent - 2)
        end = _children_end(lines, at, indent)
        if end > 0 and not lines[end - 1].endswith("\n"):
            lines[end - 1] += "\n"
        return "".join(lines[:end] + replacement + lines[end:])

    start, end = _key_span(lines, path[-1], indent)
    return "".join(lines[:start] + replacement + lines[end:])


_BLOCK_SCALAR = ("|", "|-", "|+", ">", ">-", ">+")


def _row_shape_ok(lines: list[str], path: tuple[str, ...]) -> bool:
    """Whether :func:`_merge_row_key`'s line splice is safe on this row.

    The splice assumes the block style DSH itself writes: two-space indents,
    ``config:`` at indent 2 with nothing after the colon, every parent on
    ``path`` present as a block mapping, and no comments or block scalars
    inside ``config`` (they break the span arithmetic). A row with no
    ``config`` at all is safe too: ours is appended whole.
    """
    configs = [i for i, line in enumerate(lines)
               if line.lstrip(" \t").startswith("config:")]
    if not configs:
        return True
    if len(configs) != 1:
        return False
    at = configs[0]
    if _indent_of(lines[at]) != 2 or lines[at].split(":", 1)[1].strip():
        return False
    for line in lines[at + 1:_children_end(lines, at, 4)]:
        stripped = line.strip()
        if not stripped:
            continue
        if "\t" in line[:len(line) - len(line.lstrip())] or _indent_of(line) % 2:
            return False
        if stripped.startswith("#") or stripped.endswith(_BLOCK_SCALAR):
            return False
    indent = 4
    for key in path[:-1]:
        parent = _find_key_line(lines, key, indent)
        if parent is None or lines[parent].split(":", 1)[1].strip():
            return False
        indent += 2
    return True


def _with_original_as_comments(our_block: str, their_block: str) -> str:
    """``our_block`` followed by ``their_block`` commented out, inside the row."""
    head = our_block if our_block.endswith("\n") else our_block + "\n"
    note = "  # [cv84x6] 原 llm-pi-ai 行无法逐行合并，已替换；原内容如下：\n"
    kept = "".join("  # " + line.rstrip("\n") + "\n"
                   for line in their_block.splitlines())
    return head + note + kept


def _children_end(lines: list[str], parent_at: int | None, indent: int) -> int:
    """Where a parent's child list ends, so a new child can be appended there."""
    at = parent_at
    if at is None:
        return len(lines)
    end = at + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and _indent_of(line) <= indent - 1:
            break
        end += 1
    return end


def _append_config(their_block: str, our_block: str) -> str:
    """``our_block``'s ``config:`` mapping appended to ``their_block``."""
    body = our_block.splitlines(keepends=True)
    at = _find_key_line(body, "config", 2)
    if at is None:  # pragma: no cover - our own generator always writes one
        return their_block
    head = their_block.splitlines(keepends=True)
    if head and not head[-1].endswith("\n"):
        head[-1] += "\n"
    return "".join(head + body[at:])


def _split_blocks(text: str) -> list[str]:
    """Split a patch document into its column-0 blocks, dropping comments."""
    blocks: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith("- ") or line.rstrip("\n") == "-":
            blocks.append(line)
        elif blocks and (line.startswith((" ", "\t")) or not line.strip()):
            blocks[-1] += line
        # A column-0 comment before the first block is dropped: the header is
        # this service's, and a stale one would accumulate on every sync.
    return [b if b.endswith("\n") else b + "\n" for b in blocks]


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _find_key_line(lines: list[str], key: str, indent: int) -> int | None:
    """Index of the ``<key>:`` line at exactly ``indent`` spaces, or ``None``.

    Exact indentation, not "at least": a nested ``providers:`` inside some other
    mapping must not be mistaken for the row's own.
    """
    for i, line in enumerate(lines):
        stripped = line.lstrip(" ")
        if _indent_of(line) != indent or not stripped.startswith(key + ":"):
            continue
        rest = stripped[len(key) + 1:].strip()
        # ``key: value`` and ``key:`` are both the key; ``keyish:`` is not.
        if rest == "" or not rest.startswith((":", "-")):
            return i
    return None


def _key_span(lines: list[str], key: str, indent: int) -> tuple[int, int]:
    """The half-open line range of ``<key>:`` at ``indent`` and its children.

    An empty range at the end of ``lines`` when the key is absent, so a caller
    can splice a replacement in without a special case.
    """
    start = _find_key_line(lines, key, indent)
    if start is None:
        return len(lines), len(lines)
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if not line.strip():
            end += 1
            continue
        if _indent_of(line) <= indent:
            break
        end += 1
    # Hand back trailing blank lines to the caller: they belong between blocks,
    # not to the key.
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return start, end


def _key_block(block: str, path: tuple[str, ...],
               key_indent: int = 2) -> str | None:
    """The text of ``block``'s value at ``path``, as a standalone fragment.

    ``path`` is walked from the row's ``config:`` mapping, so ``("providers",
    "cv84x6")`` returns those lines with their original indentation. ``None``
    when any step is missing -- the caller then leaves the operator's block
    alone rather than writing a partial row.

    ``key_indent`` is where the row's own mapping keys sit: a patch entry is a
    list item, so its keys are two spaces in from ``- `` (``- id: …`` then
    ``  config:``). Children of ``config:`` are two further in.
    """
    lines = block.splitlines(keepends=True)
    at = _find_key_line(lines, "config", key_indent)
    if at is None:
        return None
    indent = _indent_of(lines[at]) + 2
    start = end = at
    for key in path:
        start, end = _key_span(lines, key, indent)
        if start == end or start >= len(lines):
            return None
        indent = _indent_of(lines[start]) + 2
    return "".join(lines[start:end])


def _block_index(blocks: list[str]) -> list[tuple[str, str]]:
    """``(id, block)`` for each block, in order.

    A block that carries no id at column 0 (an ``insert:`` list) is keyed by the
    ids it inserts, so a second sync finds and replaces it instead of appending
    another copy. A block with neither is keyed by its own text, which keeps it
    and never matches one of ours.
    """
    out: list[tuple[str, str]] = []
    for block in blocks:
        if not block.strip():
            continue
        first = block.splitlines()[0]
        row_id = ""
        if first.startswith("- id:"):
            row_id = first.split(":", 1)[1].strip().strip("'\"")
        elif first.startswith("- insert:"):
            inside = re.findall(r"^\s*-\s+id:\s*(.+)$", block, re.MULTILINE)
            row_id = inside[0].strip().strip("'\"") if inside else ""
        out.append((row_id or block, block))
    return out


def _saved_url_path(directory: Path) -> Path:
    """Where the launch URL survives a service restart.

    Not the log: the point of redacting it is that support copies do not carry a
    credential. Not the config file either: this is runtime state, and a reset
    wipes ``state/`` -- which is the right lifecycle for a token.
    """
    return directory / "state" / "launch-url"


def _bearer_in(block: str) -> str:
    """The ``Bearer <key>`` value in one patch block, or "".

    Only a line inside this block, so a neighbouring row's credential can never
    be read as ours.
    """
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("authorization:"):
            continue
        value = stripped.split(":", 1)[1].strip().strip("'\"")
        if value.lower().startswith("bearer "):
            return value[7:].strip()
    return ""


def _digest(raw: bytes) -> bytes:
    """A short identity for a log tail, so a cache key can include its content."""
    import hashlib

    return hashlib.blake2b(raw, digest_size=16).digest()


def _activation_message(window: str) -> str:
    """A sentence for the plugin that failed to activate, or "".

    Two measured shapes, both on stdout (DSH's logger writes nowhere):

        dsh: warning: 1 entry did not activate
        mcp-cv84x6 (@deepseek-ai/dsh-mcp-client): Error: mcp-client(cv84x6): ...

    The count says something broke; the detail line says what. The advice is
    "重启" rather than "同步配置" because that is what was measured to work: a
    sync that writes the same bytes does not revive a failed entry, while a
    restart reconnects. See ``docs/agents-dsh.md``.

    ``window`` must already be narrowed to the *current* process lifetime: an
    older lifetime's warning would otherwise be reported for ever, even after a
    restart fixed the problem.
    """
    warning = ACTIVATION_WARNING.search(window)
    if warning is None:
        return ""
    detail = ACTIVATION_DETAIL.search(window[warning.end():])
    what = ""
    if detail is not None:
        row, plugin = detail.group(1), detail.group(2)
        if row.startswith("mcp-") or plugin == "@deepseek-ai/dsh-mcp-client":
            what = f"MCP 工具（{row}）没有连上"
        else:
            what = f"插件 {row} 没有加载"
    else:
        what = f"{warning.group(1)} 个插件没有加载"
    return (f"{what}：模型仍可对话，但这部分工具不可用。"
            "请确认本服务在运行后点「重启」该 agent。")


def _read_saved_url(directory: Path) -> str:
    try:
        text = _saved_url_path(directory).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return text if text.startswith("http") and "token=" in text else ""


def _save_url(directory: Path, url: str) -> None:
    path = _saved_url_path(directory)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(url + "\n", encoding="utf-8")
        path.chmod(0o600)
    except OSError:  # pragma: no cover - a read-only state dir is the host's problem
        logger.warning("dsh: could not save the launch URL to %s", path)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _yaml_str(value: str) -> str:
    """Quote a scalar so YAML reads back exactly the bytes it was given.

    Model ids are the only user-influenced value in this document and they may
    contain ``:``, ``#`` or a leading ``-``, so every scalar goes through here
    rather than being pasted. A straight single-quoted scalar escapes its own
    quote by doubling it; that covers everything a YAML flow scalar can hold.
    """
    return "'" + str(value).replace("'", "''") + "'"


def _yaml(value, indent: int = 0) -> list[str]:
    """Render the small subset of YAML this patch needs, as lines.

    Dicts, lists, strings, ints, bools and ``None`` -- the only shapes the
    generated patch uses. Anything else would be a bug in this module, so it
    raises instead of guessing.
    """
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return [pad + "{}"]
        out = []
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                out.append(f"{pad}{key}:")
                out.extend(_yaml(item, indent + 1))
            elif isinstance(item, dict):
                out.append(f"{pad}{key}: {{}}")
            elif isinstance(item, list):
                out.append(f"{pad}{key}: []")
            else:
                out.append(f"{pad}{key}: {_scalar(item)}")
        return out
    if isinstance(value, list):
        if not value:
            return [pad + "[]"]
        out = []
        for item in value:
            if isinstance(item, dict):
                body = _yaml(item, indent + 1)
                # "- key: v" for the first line of the mapping, indented under it
                out.append(pad + "- " + body[0].lstrip())
                out.extend(body[1:])
            else:
                out.append(f"{pad}- {_scalar(item)}")
        return out
    raise TypeError(f"unsupported patch value: {type(value).__name__}")


def _scalar(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return _yaml_str(value)


def _row(row_id: str, config: dict) -> str:
    """One id-targeted patch row."""
    lines = [f"- id: {_yaml_str(row_id)}", "  config:"]
    lines.extend(_yaml(config, 2))
    return "\n".join(lines) + "\n"


def _insert_row(url: str, api_key: str) -> str:
    """The MCP server, as a new row (there is no shipped one to patch).

    ``transport: streamable-http`` is mandatory: DSH's MCP client defaults a
    server with no transport to stdio, so an URL alone would try to spawn a
    program called after the URL. Measured against a mock ``/mcp``: DSH's client
    sends ``server/discover``, falls back to ``initialize`` with protocol
    ``2025-11-25``, and registers every tool as ``mcp__<serverName>__<name>``.

    ``failOnStartupError: true`` is what makes a broken connection *visible*.
    Measured: with the default (``false``) DSH's logger writes nowhere, so a
    server that never connects produces a single-line log and an agent with no
    tools and no complaint. With it, the failure reaches stdout as
    ``dsh: warning: 1 entry did not activate`` plus the cause, which
    :meth:`DshSpec.runtime_warning` turns into a sentence on the agent's card.
    It does *not* fail the start: the failed entry is not in the required set,
    and the agent keeps serving (``GET /manifest.webmanifest`` → 200, measured).

    The trade-off, measured and accepted: with the flag, a ``/mcp`` that is
    merely *late* (this service still starting) no longer self-heals, because
    DSH's own reconnect loop belongs to the entry that failed to activate. The
    agent card says "重启" for that reason -- see ``docs/agents-dsh.md`` §5.
    """
    entry = {
        "id": "mcp-" + MCP_NAME,
        "name": "@deepseek-ai/dsh-mcp-client",
        "config": {
            "serverName": MCP_NAME,
            "transport": "streamable-http",
            "url": url,
            "headers": _bearer(api_key),
            # Retry harder than DSH's default 10 attempts: a board's service and
            # its agent start within seconds of each other, and 10 attempts over
            # ~2.5 minutes is the window that lost the connection in practice.
            "reconnect": {"maxAttempts": 30},
            "failOnStartupError": True,
        },
    }
    return "- insert:\n" + "\n".join(_yaml([entry], 1)) + "\n"


def _bearer(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _loopback(url: str, port: int) -> str:
    """Point a printed URL at the port the manager is actually running on.

    DSH prints what it was told to bind, and the manager passes that port, so
    this normally changes nothing. It exists because the port *can* change
    (the console's port setting restarts the agent with a new one) and a stale
    URL from before the restart would send the proxy at a closed listener --
    which reads as "the agent is up but its page is 401".
    """
    match = re.match(r"^(https?://)(\[[^\]]+\]|[^/:]+)(?::(\d+))?(/.*)$", url)
    if not match:
        return url
    scheme, host, _printed, rest = match.groups()
    return f"{scheme}{host}:{int(port)}{rest}"


# -- unpacking ----------------------------------------------------------
def _unpack_node(archive: Path, target: Path, staging_root: Path) -> None:
    """Put the runtime at ``runtime/node`` without its wrapper directory."""
    import shutil
    import tarfile

    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    staging = Path(staging_root) / "unpack-node"
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
            # node-v24.22.1-linux-arm64/ is how the archive was built, not part
            # of the layout this spec names.
            for child in entries[0].iterdir():
                shutil.move(str(child), str(target / child.name))
        else:
            for entry in entries:
                shutil.move(str(entry), str(target / entry.name))
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _unpack_app(archive: Path, target: Path, staging_root: Path) -> None:
    """Unpack the prebuilt ``app/`` tree, refusing escapes.

    The archive's top level is already the layer name (``app/``), so its
    contents are moved in as they are; only the usual tar guard applies.
    """
    import shutil
    import tarfile

    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    staging = Path(staging_root) / "unpack-app"
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
        if len(entries) == 1 and entries[0].is_dir() and entries[0].name == "app":
            shutil.move(str(entries[0]), str(target))
        else:
            target.mkdir(parents=True, exist_ok=True)
            for entry in entries:
                shutil.move(str(entry), str(target / entry.name))
    finally:
        shutil.rmtree(staging, ignore_errors=True)


SPEC = DshSpec()
