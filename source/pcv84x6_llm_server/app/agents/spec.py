"""One installable agent: what to fetch, how to configure and start it.

A spec is data plus four small behaviours. Nothing here knows about
supervision, HTTP or the console -- ``manager.AgentManager`` owns that -- so a
new agent is a new module with one ``AgentSpec`` subclass and no changes to the
lifecycle code.

Every agent is installed into one directory tree, and every byte it writes stays
there:

    <agent>/bin        the agent's own executables (what ``command`` names)
    <agent>/runtime    a private language runtime, when the agent needs one
    <agent>/app        the agent's application payload, when it is separate
    <agent>/home        HOME
    <agent>/config      XDG_CONFIG_HOME
    <agent>/data        XDG_DATA_HOME
    <agent>/cache       XDG_CACHE_HOME
    <agent>/state       XDG_STATE_HOME
    <agent>/tmp         TMPDIR
    <agent>/workspace   the working directory -- where the agent edits files
    <agent>/logs        agent.log (rotated to .1 past 10 MB)

That is the whole isolation story: point HOME/XDG/TMPDIR here and the agent
cannot touch the operator's real ``~``, ``/etc`` or ``/usr``.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

LAYERS = (
    "bin", "runtime", "app", "home", "config", "data", "cache", "state",
    "tmp", "workspace", "logs",
)

# Reported bytes during a download: (bytes so far, total if the server said).
ProgressFn = Callable[[int, "int | None"], None]

# The vendor's own distribution channel, and the only one that works on a board
# with no route to the internet. An artifact names it as
# ``dfss://open@sophgo.com:/tools/...``; the scheme is ours, the rest is exactly
# what ``python -m dfss --url=`` takes.
DFSS_SCHEME = "dfss://"

# Set to 1 to make every install use the dfss mirror only. It exists to prove
# the offline path on a board that *does* have a route, and to stop a customer
# site's install from quietly falling back to the internet.
OFFLINE_ENV = "CV84X6_AGENT_OFFLINE"

# A directory of pre-downloaded installers, looked up by file name before any
# URL is tried. Testing aid: it lets the install logic be exercised before an
# artifact is published to dfss.
ARTIFACT_DIR_ENV = "CV84X6_AGENT_ARTIFACT_DIR"


class AgentError(Exception):
    """A refusal or a failure worth explaining to the operator (HTTP 400)."""


def offline_only() -> bool:
    """Whether installs are restricted to the dfss mirror."""
    return os.environ.get(OFFLINE_ENV, "").strip() not in ("", "0", "false", "False")


def artifact_dir() -> Path | None:
    """The local override directory, when the operator set one."""
    raw = os.environ.get(ARTIFACT_DIR_ENV, "").strip()
    return Path(raw) if raw else None


# Fetches one artifact and returns a verified local path. Injected so a spec
# never has to know where downloads are staged, and so tests can hand it a file
# they built themselves.
FetchFn = Callable[["Artifact", str, ProgressFn], Awaitable[Path]]


def host_arch() -> str:
    """The arch key used in ``AgentSpec.artifacts``."""
    machine = platform.machine().lower()
    if machine in ("aarch64", "arm64"):
        return "arm64"
    if machine in ("x86_64", "amd64"):
        return "x64"
    return machine


@dataclass(frozen=True)
class Artifact:
    """One downloadable build of an agent for one architecture.

    ``urls`` is a preference list, tried in order: the dfss mirror first (it is
    the only one an offline board or a customer site can reach), upstream last.
    A URL that cannot be reached falls through to the next; a payload whose
    sha256 does not match is fatal, because that is a wrong or truncated file and
    trying another mirror would only hide it.

    Two schemes beyond http(s) are understood: ``dfss://open@sophgo.com:/path``
    pulls through the vendor's dfss tool, and a bare/``file://`` path is a
    local copy. ``CV84X6_AGENT_OFFLINE=1`` drops every non-dfss entry, and
    ``CV84X6_AGENT_ARTIFACT_DIR`` puts a local directory in front of the list.
    """

    urls: tuple[str, ...]
    sha256: str
    size: int | None = None

    def __post_init__(self) -> None:
        # Accept a bare string for the common one-URL case.
        if isinstance(self.urls, str):
            object.__setattr__(self, "urls", (self.urls,))

    @property
    def filename(self) -> str:
        """The last path segment of the preferred URL (used to keep the suffix).

        A dfss entry names the same file the upstream URL does, so stripping
        the scheme and the vendor's ``user@host:/dir/`` prefix leaves the name
        an archive tool and a checksum list both recognise.
        """
        return url_filename(self.urls[0])

    def sources(self) -> tuple[str, ...]:
        """The URLs to try, in order, for this process' environment.

        The artifact as written is dfss-first with upstream as the fallback;
        what the operator's environment says then narrows or prepends that:
        offline keeps only dfss entries, and an artifact directory is asked
        before anything on the network.
        """
        urls = self.urls
        if offline_only():
            urls = tuple(u for u in urls if is_dfss(u))
        extra = artifact_dir()
        if extra is not None:
            # Any of the artifact's own file names may be the one on disk -- the
            # dfss copy and the upstream copy are not always named alike -- and
            # only a file that is really there is offered: a missing path would
            # put a guaranteed failure in front of the real sources.
            for name in dict.fromkeys(url_filename(u) for u in self.urls):
                local = extra / name
                if local.is_file():
                    return (str(local),) + tuple(u for u in urls if u != str(local))
        return urls


def is_dfss(url: str) -> bool:
    return url.startswith(DFSS_SCHEME)


def dfss_target(url: str) -> str:
    """``dfss://open@sophgo.com:/tools/x`` -> ``open@sophgo.com:/tools/x``."""
    return url[len(DFSS_SCHEME):] if is_dfss(url) else url


def url_filename(url: str) -> str:
    """The file name a URL or a bare local path ends with."""
    if is_dfss(url):
        # The dfss target has no scheme, so the last "/" is still the last path
        # separator; open@sophgo.com:/a/b.tar.gz -> b.tar.gz.
        return dfss_target(url).rstrip("/").rsplit("/", 1)[-1]
    if "://" in url:
        return url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    return Path(url).name


@dataclass
class ModelChoice:
    """One model the agent may use, as its config needs to describe it."""

    id: str
    context: int
    vision: bool = False


@dataclass
class InstallContext:
    """Everything a config file needs, gathered by the manager."""

    service_port: int
    api_key: str
    models: list[ModelChoice] = field(default_factory=list)
    default_model: str = ""
    thinking: bool = False
    #: The agent's own server secret (its UI/API login). OpenClaw wants it in
    #: ``openclaw.json`` rather than an environment variable.
    secret: str = ""
    #: The agent's own listen port. Most agents read it from the command line;
    #: OpenClaw also writes it into the config, where ``gateway.port`` decides.
    port: int = 0
    #: Externally reachable origins the operator declared, for agents that have
    #: to name them in their config. The proxy normalises Origin itself, so this
    #: is only for a direct, un-proxied visit.
    public_origins: list[str] = field(default_factory=list)


class AgentSpec:
    """An agent this service can install and run.

    Subclasses fill in the class attributes and override the methods whose
    default is not right for them (``write_config``, ``command``,
    ``health_url``, ...). The defaults are deliberately the "plain HTTP server
    with no config file" case, which is also what the tests' fake agent is.

    A plain class rather than a dataclass on purpose: a spec is a module-level
    singleton whose identity is its class, and a dataclass' generated
    ``__init__`` would shadow every subclass's attributes with field defaults.
    Pass keyword arguments to get a variant of one (tests do this).
    """

    id: str = ""
    name: str = ""
    version: str = ""
    default_port: int = 0
    artifacts: dict[str, "Artifact"] = {}
    #: Whether a browser may frame this agent's page. Per-agent because it is a
    #: measured property of the agent, not a policy of the console.
    embeddable: bool = False
    #: Whether this service reverse-proxies the agent's UI on its own origin
    #: (``/agents/<id>/``) instead of linking to the agent's own port. An agent
    #: that says ``proxied`` is reached only through the proxy, which is also
    #: what makes an agent that refuses framing (``X-Frame-Options: DENY``)
    #: embeddable at all -- and, for an agent on a board reached through one
    #: forwarded port, what makes its UI reachable from another subnet.
    proxied: bool = False
    #: How the proxy should map this agent's URLs onto ``/agents/<id>/``:
    #:
    #: * ``False`` (default) -- the agent is configured to serve itself *under*
    #:   the prefix (OpenClaw's ``controlUi.basePath``), so the path is forwarded
    #:   unchanged.
    #: * ``True`` -- the agent is an origin-root app that knows nothing about the
    #:   prefix: the proxy strips it on the way up and rewrites the HTML/CSS/JS
    #:   it returns so the browser never leaves ``/agents/<id>/``.
    #:
    #: Measured, not a preference: an origin-root app served under a prefix sends
    #: the browser to ``/assets/...`` and API calls to ``/``, which is the exact
    #: failure this module fixes.
    prefix_root: bool = False
    #: Whether this agent's browser fence compares ``Origin`` against the
    #: request's own ``Host`` (rather than against a configured allow-list).
    #: Only DSH does: its connection carrier rejects any request whose Origin
    #: names a different authority, so the proxy has to present one authority in
    #: both headers. OpenClaw keeps ``False`` -- it validates Origin against
    #: ``controlUi.allowedOrigins``, which this service fills with its own
    #: origin, so presenting the agent's authority there would be a 403.
    origin_is_host: bool = False
    #: How much free system memory this agent needs before a start is allowed.
    #: Per-agent because the footprint differs by an order of magnitude: a
    #: single binary needs ~60 MB, a Node platform with 14 plugins ~1 GB.
    memory_floor_bytes: int = 0
    #: One line the console shows on the agent's card, for a caveat an operator
    #: can only learn by reading this spec otherwise (measured memory footprint,
    #: what the install downloads). Empty means the card says nothing extra.
    card_note: str = ""
    #: How long ``start`` waits for the health endpoint before giving up.
    start_timeout: float = 90.0
    #: The name of the agent's executable once unpacked, under ``payload_root``
    #: ("opencode" -> bin/opencode). Also what ``installed()`` checks for.
    executable: str = ""
    #: Whether an archive's contents land after unpacking: ``"bin"`` keeps the
    #: payload under bin/; ``""`` merges the archive's top-level directories by
    #: name into the layers, which is how an agent shipping a private runtime
    #: plus an app in one archive is installed.
    payload_root: str = "bin"
    #: Whether this agent's config file carries the service API key. When it
    #: does, the plaintext lives only there and ``existing_key`` reads it back;
    #: when it does not, there is nothing to rewrite and a config sync must not
    #: rotate the operator's key for no reason.
    key_in_config: bool = True
    #: Absolute paths outside the agent directory that this agent may create and
    #: that an uninstall must therefore clean up. Empty for an agent that keeps
    #: everything under its own tree. OpenClaw is the measured exception: its
    #: gateway created ``/tmp/openclaw`` (mode 0700, empty) while starting on the
    #: board, so leaving it behind would break the promise that an uninstall
    #: leaves nothing outside the data root.
    scratch_paths: tuple[str, ...] = ()
    #: Files under the agent directory that a *reset* must carry across the wipe,
    #: as paths relative to that directory.
    #:
    #: A reset wipes ``data/``, which is right for everything the agent derives
    #: -- sessions, caches, its own state -- and wrong for a config file the
    #: agent's own settings pages write, because those hold the operator's own
    #: edits. DSH is the case: ``profiles/web/cordis.patch.yml`` is the file its
    #: Models/Plugins pages save to, so it is copied out before the wipe and
    #: back after it, and ``write_config`` then merges over it (replacing only
    #: the rows this service owns).
    reset_keep: tuple[str, ...] = ()
    #: Whether the proxy must ask this agent for an *unencoded* response body.
    #:
    #: Only an agent whose HTML/CSS/JS this proxy rewrites needs it: a rewritten
    #: body has to be decoded and re-emitted, and a gzip stream makes that
    #: impossible without decompressing it first. DSH compresses HTML above
    #: 1 KiB when the request says it accepts gzip. Per-agent rather than
    #: implied by ``prefix_root`` because opencode is ``prefix_root`` too and
    #: never compressed, so asking it for ``identity`` would cost bandwidth for
    #: nothing.
    identity_encoding: bool = False

    def __init__(self, **overrides) -> None:
        for key, value in overrides.items():
            if not hasattr(type(self), key):
                raise TypeError(f"{type(self).__name__} has no field {key!r}")
            setattr(self, key, value)
        if isinstance(self.artifacts, dict):
            # A subclass may hand in a bare string URL for the one-URL case.
            self.artifacts = {
                arch: (Artifact(urls=art) if isinstance(art, str) else art)
                for arch, art in self.artifacts.items()
            }

    # -- install ---------------------------------------------------------
    async def install(
        self, directory: Path, fetch: FetchFn, arch: str | None = None,
        progress: ProgressFn | None = None,
    ) -> None:
        """Download, verify and unpack this agent into ``directory``.

        The caller creates the layers and clears any previous payload; this only
        has to put the bytes where ``command`` expects them.
        """
        arch = arch or host_arch()
        artifact = self.artifacts.get(arch)
        if artifact is None:
            raise AgentError(f"没有适用于 {arch} 架构的安装包")
        directory = Path(directory)
        for name in LAYERS:
            (directory / name).mkdir(parents=True, exist_ok=True)

        local = await fetch(artifact, f"{self.id}-{self.version}-{arch}", progress or (lambda d, t: None))
        self._unpack(Path(local), directory)
        self._chmod(directory)

    def _unpack(self, archive: Path, directory: Path) -> None:
        staging = directory / "tmp" / f"unpack-{self.id}"
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)

        name = archive.name.lower()
        if name.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".tar")):
            with tarfile.open(archive) as tf:
                # Refuse entries that would land outside the agent tree. tarfile
                # also accepts absolute paths, which is exactly the accident
                # this guards against.
                for member in tf.getmembers():
                    target = (staging / member.name).resolve()
                    if not str(target).startswith(str(staging.resolve())):
                        raise AgentError(f"安装包内含越界路径：{member.name}")
                tf.extractall(staging)
        else:
            shutil.copy2(archive, staging / (self.executable or archive.name))

        entries = list(staging.iterdir())
        # A wrapper directory (node-v24.0.0-linux-arm64/, opencode-v1.19.4/) is
        # an artifact of how the archive was made, not part of the layout.
        if len(entries) == 1 and entries[0].is_dir() and entries[0].name not in LAYERS:
            entries = list(entries[0].iterdir())

        if self.payload_root:
            dest = directory / self.payload_root
            dest.mkdir(parents=True, exist_ok=True)
            for entry in entries:
                # An archive that already names its directory "bin/" means the
                # same thing payload_root does; merge rather than nest.
                if entry.is_dir() and entry.name == self.payload_root:
                    for child in entry.iterdir():
                        self._move_into(child, dest)
                else:
                    self._move_into(entry, dest)
        else:
            for entry in entries:
                layer = entry.name if entry.name in LAYERS else "bin"
                dest = directory / layer
                dest.mkdir(parents=True, exist_ok=True)
                self._move_into(entry, dest)
        shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _move_into(entry: Path, dest: Path) -> None:
        target = dest / entry.name
        if target.is_dir() and entry.is_dir():
            # Merge rather than replace: bin/ and runtime/ from a previous
            # version may already be there and are cleared by the caller.
            shutil.copytree(entry, target, dirs_exist_ok=True, symlinks=True)
        else:
            if target.exists() or target.is_symlink():
                target.unlink()
            shutil.move(str(entry), str(target))

    def _chmod(self, directory: Path) -> None:
        """Make the payload's executables executable and nothing else writable.

        tar preserves modes, but an archive built on a filesystem without the
        executable bit (or a ``raw`` artifact) would otherwise arrive as 0644
        and fail at exec time with a bare EACCES.
        """
        bin_dir = directory / (self.payload_root or "bin")
        if self.executable and bin_dir.is_dir():
            exe = bin_dir / self.executable
            if exe.is_file():
                exe.chmod(0o755)

    # -- configuration ---------------------------------------------------
    def config_path(self, directory: Path) -> Path:
        """The file ``write_config`` writes; also where the key is read back."""
        return Path(directory) / "config" / f"{self.id}.json"

    def write_config(self, directory: Path, ctx: InstallContext) -> None:
        """Write the agent's config file. The default agent needs none."""
        return None

    def existing_key(self, directory: Path) -> str:
        """The API key already in this agent's config, or "".

        The key's plaintext lives only in the agent's own config (agents.json
        keeps the id), so a rewrite of that config has to recover it from
        itself instead of from the manager's state.
        """
        return ""

    # -- running ---------------------------------------------------------
    def command(self, directory: Path, port: int) -> list[str]:
        raise AgentError(f"{self.name} 没有定义启动命令")

    def env(self, directory: Path, secret: str = "") -> dict[str, str]:
        """The environment that keeps the agent inside its own directory.

        ``secret`` is the agent's own server password (not the API key); agents
        that authenticate their own HTTP surface put it in here.
        """
        d = Path(directory)
        return {
            "HOME": str(d / "home"),
            "XDG_CONFIG_HOME": str(d / "config"),
            "XDG_DATA_HOME": str(d / "data"),
            "XDG_CACHE_HOME": str(d / "cache"),
            "XDG_STATE_HOME": str(d / "state"),
            "TMPDIR": str(d / "tmp"),
        }

    def health_url(self, port: int) -> str:
        return f"http://127.0.0.1:{port}/health"

    def health_auth(self, secret: str) -> tuple[str, str] | None:
        """Basic-auth credentials for the health probe, when the agent needs them."""
        return None

    def web_url(self, host: str, port: int, secret: str) -> str:
        return f"http://{host}:{port}/"

    def web_credentials(self, secret: str) -> tuple[str, str]:
        """What the console shows next to the "open" button."""
        return ("", secret)

    # -- multi-process agents --------------------------------------------
    async def after_start(self, directory: Path, ctx: "InstallContext",
                          port: int) -> str:
        """Finish a start, for an agent whose readiness is more than /health.

        Called by the manager once ``health_url`` answers and before the start
        is reported, so it still holds the agent's lock. Returns a warning to
        show as ``last_error`` (the start itself succeeded) or "".

        Two kinds of agent need this: one that must be given a credential
        before its UI is usable at all, and one that forks a second process the
        health endpoint says nothing about. Both are "the process is up but not
        yet the thing the operator asked for" -- exactly the gap this hook
        closes. The default agent has neither.
        """
        return ""

    def children_ports(self, directory: Path, port: int) -> tuple[int, ...]:
        """Ports an agent's own child processes listen on, besides its own.

        The manager's port-conflict check only knows the port it passes on the
        command line. An agent that forks a server of its own -- PicoClaw's
        gateway is one -- would then be free to collide with another agent's
        port, and the two would fight over the same loopback address.
        """
        return ()

    def leftovers(self, directory: Path, port: int) -> list[int]:
        """Live processes belonging to this agent that a stop must also reap.

        Only needed when the agent forks children. The manager signals the
        process *group* it created, which normally takes the children with it;
        this covers the case where the parent is gone and a child survived, or
        where the child was reparented out of that group. Each pid must be
        proved to be this agent's own -- see the implementation's own rules.
        """
        return []


    def upstream_basic_auth(self, secret: str) -> tuple[str, str] | None:
        """Credentials the reverse proxy presents to this agent's own server.

        ``None`` for an agent whose proxied requests carry the caller's own
        session (OpenClaw's token rides in the fragment/cookie). opencode is the
        exception: it authenticates every request individually, so the proxy
        speaks its basic auth on behalf of the console admin it has already
        authenticated.
        """
        return None

    def upstream_launch_url(self, directory: Path, port: int) -> str | None:
        """The URL the proxy must ask for before it can serve the browser's page.

        ``None`` -- the default -- means this agent needs no such handoff, and
        the proxy must forward the browser's request untouched. It is ``None``
        rather than ``""`` on purpose: an empty string means "this agent does
        use a launch token, but it has not printed one yet", which the proxy
        answers with an explanation instead of an upstream 401.

        DSH is the only implementation: its page is reachable only with a
        session cookie that one tokenized startup URL mints, so the proxy's
        first request has to be that URL rather than the path the browser asked
        for.
        """
        return None

    def runtime_warning(self, directory: Path) -> str:
        """Something an operator must be told about a *running* agent.

        Folded into the card's ``last_error`` line by the manager, which is the
        only place the console shows a sentence like this. It exists because
        some failures are neither a crash nor a failed start: DSH's MCP client
        can give up reconnecting while the agent itself is perfectly healthy,
        and the measured result is an agent that answers every request and
        silently has no tools.

        Must be cheap enough to call on every status poll: an implementation
        that reads a file keys its cache on the file's size and mtime.
        """
        return ""

    def public_log(self, text: str) -> str:
        """The agent's log with anything that must not leave the board removed.

        ``GET /api/agents/<id>/logs`` returns this verbatim, so a credential the
        agent prints for its own startup -- DSH's launch token is exactly one --
        would otherwise be readable by anyone with a console session. An agent
        that prints no secret needs nothing here.
        """
        return text

    def redact_from_log(self, directory: Path) -> None:
        """Persist whatever a credential needs to outlive the log's content.

        Called once the agent is up, at the moment its launch credential is both
        fresh and known to be needed. Agents whose credential rides in their own
        config need nothing here.

        It is *not* "rewrite the log file without the secret", despite the name:
        the manager hands this exact file to the running agent as its stdout, so
        rewriting it truncates whatever the agent wrote between the read and the
        write. Measured on DSH's first version -- the log came back as only the
        redacted launch line. The route that serves logs filters it instead
        (:meth:`public_log`).
        """
        return None


# -- the MCP server every agent is preconfigured against ---------------------
#: The name this service's MCP server has in each agent's config. One name, one
#: meaning: an operator reading ``opencode.json`` and ``picoclaw.json`` sees the
#: same entry, and a sync can find the record it owns by name alone. It is *not*
#: a prefix match on anything else, which is what keeps a user's own server
#: called ``cv84x6-notes`` untouched.
MCP_SERVER_NAME = "cv84x6"

#: Where the MCP endpoint lives on this service. Loopback on purpose: the agent
#: runs on the same board, and the endpoint authenticates with an API key, so
#: there is no reason to route it through the LAN or the proxy.
MCP_PATH = "/mcp"


def mcp_url(service_port: int) -> str:
    return f"http://127.0.0.1:{int(service_port)}{MCP_PATH}"


def mcp_headers(api_key: str) -> dict[str, str]:
    """The header the MCP client presents. Absent key, absent header."""
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def merge_mcp_server(existing: dict | None, entry: dict) -> dict:
    """``existing`` with our one server replaced, everything else kept.

    The rule the card sets -- "a user's other MCP servers must not be
    overwritten" -- has to survive a config this service did *not* write: an
    operator may have added a filesystem server from the agent's own UI, and a
    sync that rebuilt the block from nothing would delete it. So the block is
    copied, our own entry replaced wholesale (so a rotated key really replaces
    the old one), and every other key left exactly as it was.
    """
    out = dict(existing or {})
    out[MCP_SERVER_NAME] = entry
    return out


def key_from_mcp_entry(entry) -> str:
    """The API key inside one MCP server entry's headers, or "".

    The key a config holds in *two* places -- the provider block and the MCP
    header -- must be recoverable from either. That matters on the one path where
    the provider block cannot supply it: an agent installed while no model is
    loaded has an empty ``model_list``/``models`` and therefore no key there, and
    ``AgentManager._recover_key`` would revoke and reissue the key on every sync
    (leaving the agent's MCP calls on a dead credential until the next write).
    """
    if not isinstance(entry, dict):
        return ""
    headers = entry.get("headers")
    if not isinstance(headers, dict):
        return ""
    for name, value in headers.items():
        if str(name).lower() == "authorization" and isinstance(value, str):
            text = value.strip()
            if text.lower().startswith("bearer "):
                return text[7:].strip()
            return text
    return ""
