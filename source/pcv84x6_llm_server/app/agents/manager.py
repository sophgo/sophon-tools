"""Install, configure, supervise and report on the agents.

The manager owns every mutable fact about an agent: what is on disk, what is in
``agents.json``, and which process is running. The HTTP surface in
``app/api/agents_api.py`` is a thin translation of that state into JSON, so all
of the lifecycle rules live here and are testable without a browser.

Three rules shape the design:

* **One directory per agent.** Everything it writes -- config, data, cache,
  logs, its workspace -- sits under ``<data>/agents/<id>/``. Removing an agent
  is ``rm -rf`` on that directory and nothing escapes.
* **The process is the unit.** An agent runs as a child process in its own
  session (``start_new_session=True``) so a stop can signal the whole group; a
  crashed agent is restarted with backoff, but a flapping one is given up on
  rather than left to spin.
* **Memory is checked before, not after.** A model may already hold most of the
  system's RAM; starting an agent that cannot fit would push the model's pages
  out and slow inference to a crawl. Below ``MEMORY_FLOOR_BYTES`` of
  MemAvailable the start is refused with 409 -- against whatever this host
  actually has free, not a fixed capacity.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import httpx

from ..core import monitor, procs
from ..core.downloader import dfss_progress, download_dfss_file
from ..core.models import AGENT_MODEL_KINDS, ModelInfo
from ..core.procs import PopenLike
from ..core.storage import walk_stats
from .spec import (
    LAYERS,
    AgentError,
    AgentSpec,
    Artifact,
    InstallContext,
    ModelChoice,
    ProgressFn,
    dfss_target,
    is_dfss,
)

logger = logging.getLogger(__name__)

# A 35B model holds ~1.5 GB of system RAM. Below this much MemAvailable an
# agent start would mostly page the model out. The floor is a property of the
# agent (how much it costs), not of any board: the check compares it against the
# real MemAvailable, so a bigger board simply passes sooner.
MEMORY_FLOOR_BYTES = 400 * 1024 * 1024

# How many crashes within CRASH_WINDOW_S stop the automatic restarts.
MAX_CRASHES = 5
CRASH_WINDOW_S = 600.0

LOG_ROTATE_BYTES = 10 * 1024 * 1024

# SIGTERM, then this long for the group to go, then SIGKILL.
STOP_GRACE_S = 10.0

# A process that answered /health but died within this many seconds still counts
# as a crash: opencode binds its port before its state is loaded.
CRASH_GRACE_S = 30.0

# Sizes are walked on demand; a walk of a node_modules tree is not something to
# repeat every two seconds from the status poll.
SIZE_TTL_S = 30.0

STATE_FILE = "agents.json"

# Models the service can offer an agent when neither the loaded model nor the
# catalogue has a context length.
FALLBACK_CONTEXT = 32768


class AgentBusy(Exception):
    """A refusal caused by current state, not by a bad request (HTTP 409)."""


#: What an agent is doing right now, as the console reports it. ``None`` is
#: idle. Derived from the runtime/job the manager already tracks -- deliberately
#: not a second copy of that state, so the two cannot disagree.
#:
#:   installing   an install job is running (was `job.state = pending/running`)
#:   starting     the process was spawned and /health has not passed yet
#:   stopping     a stop is in progress
#:   restarting   a restart/port-change restart is in progress
#:   resetting    a reset is wiping config and reissuing keys
#:   uninstalling an uninstall is deleting the tree
#:   configuring  a sync_config / patch (settings write) is in progress
AgentOperation = str | None
AGENT_OPERATIONS = (
    "installing", "starting", "stopping", "restarting", "resetting",
    "uninstalling", "configuring",
)

_OPERATION_LABEL = {
    "installing": "安装",
    "starting": "启动",
    "stopping": "停止",
    "restarting": "重启",
    "resetting": "重置",
    "uninstalling": "卸载",
    "configuring": "应用配置",
}


class MemoryLow(AgentBusy):
    """Not enough free system memory to start another agent."""


class PortBusy(AgentBusy):
    """The requested port is already in use."""


@dataclass
class AgentState:
    """What ``agents.json`` remembers about one agent."""

    version: str = ""
    port: int = 0
    autostart: bool = False
    secret: str = ""
    key_id: str = ""
    default_model: str = ""
    thinking: bool = False

    def public(self) -> dict:
        # The secret is the agent's own server password; the console shows it
        # (that is how the operator logs in) so it is not a state-file-only
        # field, but the API key it points at never appears here.
        return asdict(self)


@dataclass
class Job:
    """An install running in the background, polled by the console."""

    agent_id: str
    state: str = "pending"          # pending | running | done | error
    done_bytes: int = 0
    total_bytes: int | None = None
    message: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    #: Files this install staged under ``downloads/``; removed when the job ends.
    staged: list[Path] = field(default_factory=list)

    @property
    def percent(self) -> float:
        if not self.total_bytes:
            return 0.0
        return min(100.0, 100.0 * self.done_bytes / self.total_bytes)

    def public(self) -> dict:
        d = asdict(self)
        d.pop("staged", None)  # bookkeeping for cleanup, not for the console
        d["percent"] = round(self.percent, 1)
        return d


@dataclass
class _Runtime:
    """Per-agent process bookkeeping that does not belong in agents.json."""

    status: str = "stopped"          # stopped | starting | running | failed
    proc: PopenLike | None = None
    task: asyncio.Task | None = None
    started_at: float = 0.0
    last_error: str = ""
    crashes: list[float] = field(default_factory=list)
    stopping: bool = False
    #: Set while a start() is waiting for health, so a crash during startup is
    #: reported to that caller instead of being retried behind its back.
    startup_error: str = ""
    #: Whether start() ever got a 200 from /health for this run. A process can
    #: bind its port and still be initialising, so the health check alone does
    #: not mean the agent is ready to survive a crash test.
    became_healthy: bool = False
    exit_code: int | None = None
    #: The operation in flight, or None. The supervisor never writes this --
    #: it is set and cleared by the methods that own a lifecycle step, so a
    #: crashed process does not leave "starting" stuck behind it.
    operation: AgentOperation = None
    operation_since: float | None = None
    #: True when this run attached to a process an earlier run spawned (see
    #: ``AgentManager.adopt``) instead of forking one.
    adopted: bool = False
    #: The generation of the adopted process: a recycled pid must not be mistaken
    #: for the agent that used to own it.
    adopted_start: float | None = None
    #: A surviving process that matched this agent but never passed its health
    #: check. Reported (so the port and the memory it holds are accounted for)
    #: and stoppable, but never "running": the console must not offer a UI that
    #: cannot answer. Kept apart from ``proc`` so the one predicate that means
    #: "the agent is up" stays true to its name.
    orphan_pid: int | None = None
    orphan_start: float | None = None


def _archive_suffix(name: str) -> str:
    low = name.lower()
    for suffix in (".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".tar"):
        if low.endswith(suffix):
            return suffix
    return ""


def _source_kind(url: str) -> str:
    """``dfss`` / ``http`` / ``local``, for a log line an operator can read."""
    if is_dfss(url):
        return "dfss"
    if url.startswith("file://"):
        return "local"
    return "local" if "://" not in url else "http"


class AgentManager:
    """The lifecycle of every agent, and the API's only source of truth.

    ``key_store`` is the service's ``StateStore`` (agent API keys live there so
    the key console lists them); ``models`` is the ``ModelManager``, read for
    the model list an agent's config offers.
    """

    def __init__(
        self,
        data_root: Path,
        key_store,
        models,
        *,
        service_port: int = 8000,
        specs: Iterable[AgentSpec] | None = None,
        memory_floor_bytes: int = MEMORY_FLOOR_BYTES,
        start_timeout_override: float | None = None,
        public_origins: Iterable[str] | None = None,
    ) -> None:
        self.data_root = Path(data_root)
        self.root = self.data_root / "agents"
        self.downloads = self.data_root / "downloads"
        self.state_path = self.root / STATE_FILE
        self.key_store = key_store
        self.models = models
        self.service_port = int(service_port)
        self.memory_floor_bytes = memory_floor_bytes
        self.start_timeout_override = start_timeout_override
        #: Origins an operator declared the service reachable on, passed to the
        #: agents whose config names browser origins (OpenClaw). Empty means
        #: "loopback only", which is what the proxy presents anyway.
        self.public_origins = [o for o in (public_origins or []) if o]
        # How long a process must live before it counts as "not a crash".
        self.crash_grace = CRASH_GRACE_S

        if specs is None:
            from . import dsh, openclaw, opencode, picoclaw
            # Order is the console's card order. DSH leads because the operator
            # asked for it there (MYS-2293); nothing about the four agents
            # themselves decides this, and the other three keep the order they
            # had.
            specs = [dsh.SPEC, picoclaw.SPEC, opencode.SPEC, openclaw.SPEC]
        specs = list(specs)
        self.specs: dict[str, AgentSpec] = {s.id: s for s in specs}
        if len(self.specs) != len(list(specs)):
            raise ValueError("two agent specs share an id")

        self.states: dict[str, AgentState] = {}
        self._runtime: dict[str, _Runtime] = {sid: _Runtime() for sid in self.specs}
        self._jobs: dict[str, Job] = {}
        self._locks: dict[str, asyncio.Lock] = {sid: asyncio.Lock() for sid in self.specs}
        self._sizes: dict[str, tuple[float, int]] = {}
        self._autostart_task: asyncio.Task | None = None

        self.root.mkdir(parents=True, exist_ok=True)
        self.downloads.mkdir(parents=True, exist_ok=True)
        self.load_state()

    # -- state file ------------------------------------------------------
    def load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text())
        except (OSError, json.JSONDecodeError):
            # A corrupt agents.json must not brick the console; the agents stay
            # installed on disk and are rediscovered by "installed" below.
            logger.warning("agents.json is unreadable, starting with defaults")
            return
        for agent_id, entry in (raw or {}).items():
            spec = self.specs.get(agent_id)
            if spec is None:
                continue  # an agent removed from this release keeps its files
            known = {k: v for k, v in (entry or {}).items() if k in AgentState.__annotations__}
            self.states[agent_id] = AgentState(**known)

    def save_state(self) -> None:
        payload = {k: asdict(v) for k, v in self.states.items()}
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        tmp.chmod(0o600)
        os.replace(tmp, self.state_path)  # atomic: the board loses power often

    def state(self, agent_id: str) -> AgentState:
        """The agent's state, created with a fresh port/secret on first use."""
        st = self.states.get(agent_id)
        if st is None:
            spec = self._spec(agent_id)
            st = AgentState(port=spec.default_port)
            self.states[agent_id] = st
        return st

    def _spec(self, agent_id: str) -> AgentSpec:
        spec = self.specs.get(agent_id)
        if spec is None:
            raise AgentError(f"未知的 agent：{agent_id}")
        return spec

    # -- operations ------------------------------------------------------
    def operation_of(self, agent_id: str) -> AgentOperation:
        """What this agent is doing, derived -- never stored twice.

        An install is reported from the job that is actually running it; every
        other step from the runtime the method that owns it set. Keeping the
        derivation in one place is what stops the console's lock and the
        manager's state from disagreeing after a page reload.
        """
        rt = self._runtime.get(agent_id)
        if rt is not None and rt.operation:
            return rt.operation
        job = self._jobs.get(agent_id)
        if job is not None and job.state in ("pending", "running"):
            return "installing"
        return None

    def _claim(self, agent_id: str, operation: str) -> None:
        """Mark ``operation`` in flight, refusing if another one already is.

        A second click -- or a second browser -- gets a 409 instead of queueing
        behind a 30 s health wait, which is what the console needs in order to
        keep its buttons honest. That is why callers run this BEFORE taking the
        agent's lock: the lock is held for the whole operation, so a check
        inside it would only ever refuse after the first caller had finished.
        """
        current = self.operation_of(agent_id)
        if current is not None:
            raise AgentBusy(
                f"{self.specs[agent_id].name} 正在{_OPERATION_LABEL[current]}，请稍后再操作")
        rt = self._runtime[agent_id]
        rt.operation = operation
        rt.operation_since = time.time()

    def _release(self, agent_id: str) -> None:
        rt = self._runtime[agent_id]
        rt.operation = None
        rt.operation_since = None

    # -- paths -----------------------------------------------------------
    def directory(self, agent_id: str) -> Path:
        return self.root / agent_id

    def installed(self, agent_id: str) -> bool:
        """Installed means the payload this release expects is on disk.

        Checking the executable rather than agents.json means a half-deleted
        directory reads as "not installed" instead of failing later at exec.
        """
        spec = self.specs.get(agent_id)
        if spec is None:
            return False
        exe = self.directory(agent_id) / (spec.payload_root or "bin") / (spec.executable or "")
        return bool(spec.executable) and exe.is_file()

    # -- install / uninstall / reset -------------------------------------
    async def install(self, agent_id: str) -> Job:
        """Start the install as a background job and return it.

        Two installs of the same agent cannot interleave, and an install must not
        race a start; both hold the agent's lock. The download itself runs in a
        task because 78 MB over a slow link must not sit inside the HTTP request.
        """
        spec = self._spec(agent_id)
        if self.installed(agent_id):
            raise AgentBusy(f"{spec.name} 已经安装，如需重装请先卸载")
        existing = self._jobs.get(agent_id)
        if existing is not None and existing.state in ("pending", "running"):
            return existing
        # `operation_of` already folds the job's own state into "installing", so
        # anything non-None here is a *different* lifecycle step: uninstalling
        # while an install is still unpacking would delete the tree under it.
        # The job runs in its own task (it cannot hold the HTTP request for a
        # 78 MB download), so this check is on the shared runtime rather than
        # on the agent's lock.
        current = self.operation_of(agent_id)
        if current is not None:
            raise AgentBusy(f"{spec.name} 正在{_OPERATION_LABEL[current]}，请稍后再安装")
        job = Job(agent_id=agent_id, state="running")
        self._jobs[agent_id] = job
        asyncio.create_task(self._install_job(spec, job))
        return job

    async def _install_job(self, spec: AgentSpec, job: Job) -> None:
        agent_id = spec.id
        async with self._locks[agent_id]:
            directory = self.directory(agent_id)
            try:
                directory.mkdir(parents=True, exist_ok=True)
                for name in LAYERS:
                    (directory / name).mkdir(parents=True, exist_ok=True)
                self._wipe_payload(agent_id)

                def progress(done: int, total: int | None) -> None:
                    job.done_bytes = done
                    if total:
                        job.total_bytes = total
                    job.message = f"正在下载 {done / 1048576:.1f} MiB"
                    job.state = "running"

                async def fetch(artifact: Artifact, name: str, report: ProgressFn) -> Path:
                    # Per-install wrapper so the job knows which files it staged
                    # and can delete exactly those when it ends.
                    path = await self._fetch(artifact, name, report)
                    job.staged.append(path)
                    return path

                await spec.install(directory, fetch, progress=progress)
                job.message = "正在生成配置"

                st = self.state(agent_id)
                if not st.secret:
                    st.secret = _new_secret()
                st.version = spec.version
                if not st.port:
                    st.port = spec.default_port
                # A key per agent, named after it, so the key console shows who
                # holds it. The plaintext goes into the agent's own config only.
                if not st.key_id or self._key_revoked(st.key_id):
                    raw, key = self.key_store.create_key(f"agent-{agent_id}")
                    st.key_id = key.id
                else:
                    raw = self._recover_key(agent_id)
                st.default_model = self._pick_default_model(agent_id)
                self.save_state()
                spec.write_config(directory, self._context(agent_id, raw))
                self._chmod_config(spec, directory)

                job.state = "done"
                job.message = f"{spec.name} {spec.version} 安装完成"
                self._bump_size(agent_id)
                logger.info("installed agent %s %s", agent_id, spec.version)
            except Exception as exc:  # the job reports failures, it does not raise them
                logger.exception("installing %s failed", agent_id)
                job.state = "error"
                job.message = str(exc) or exc.__class__.__name__
            finally:
                # The staged installers are worth nothing after this job: on
                # success the payload is unpacked, on failure it is unusable.
                # Left in place they were ~74 MB of the data root per attempt.
                self._clear_downloads(job)
                job.finished_at = time.time()

    def _clear_downloads(self, job: Job) -> None:
        """Delete this install's staged installers and any .part beside them."""
        paths: list[Path] = list(job.staged)
        for staged in job.staged:
            paths.extend(self.downloads.glob(staged.name + ".part"))
        removed = 0
        for path in paths:
            try:
                path.unlink(missing_ok=True)
                removed += 1
            except OSError as exc:  # pragma: no cover - a locked file is not fatal
                logger.warning("could not remove staged download %s: %s", path, exc)
        job.staged.clear()
        if removed:
            logger.info("agent %s: cleared %d staged download(s)", job.agent_id, removed)

    def _wipe_payload(self, agent_id: str) -> None:
        """Remove the previous payload but keep data, workspace and logs."""
        directory = self.directory(agent_id)
        for name in ("bin", "runtime", "app"):
            target = directory / name
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.exists():
                shutil.rmtree(target, ignore_errors=True)

    def _chmod_config(self, spec: AgentSpec, directory: Path) -> None:
        """The plaintext key lives in this file: 600, and nothing else."""
        path = spec.config_path(directory)
        if path.is_file():
            path.chmod(0o600)

    def _key_revoked(self, key_id: str) -> bool:
        for key in self.key_store.keys:
            if key.id == key_id:
                return key.revoked
        return True

    def _recover_key(self, agent_id: str) -> str:
        """The key already in the agent's config, or a fresh one.

        agents.json stores the key id, not the plaintext, so a config rewrite
        (sync, reset) has to take the key from the config it is replacing. If
        that file is gone the old key is revoked and a new one issued, which
        keeps "one live key per agent" true.
        """
        spec = self._spec(agent_id)
        st = self.state(agent_id)
        raw = spec.existing_key(self.directory(agent_id))
        if raw:
            return raw
        if not spec.key_in_config:
            # No config file holds the key, so there is nothing to recover and
            # nothing to rewrite: keep the key the install issued rather than
            # rotating it on every sync.
            return ""
        if st.key_id:
            self.key_store.revoke_key(st.key_id)
        raw, key = self.key_store.create_key(f"agent-{agent_id}")
        st.key_id = key.id
        return raw

    async def uninstall(self, agent_id: str) -> None:
        spec = self._spec(agent_id)
        self._claim(agent_id, "uninstalling")
        try:
            async with self._locks[agent_id]:
                await self._stop_locked(agent_id)
                await self._uninstall_locked(agent_id, spec)
        finally:
            # The runtime object was replaced with a fresh one by the uninstall
            # itself; clear whatever is there now so the invariant holds even on
            # the failure path.
            rt = self._runtime.get(agent_id)
            if rt is not None:
                rt.operation = None
                rt.operation_since = None

    async def _uninstall_locked(self, agent_id: str, spec: AgentSpec) -> None:
        st = self.states.pop(agent_id, None)
        if st is not None and st.key_id:
            self.key_store.revoke_key(st.key_id)
        self.save_state()
        shutil.rmtree(self.directory(agent_id), ignore_errors=True)
        # Anything the agent created outside its own tree. Only paths the
        # spec declared, so an uninstall can never be turned into a general
        # "delete this path" by a bad config value.
        for raw in getattr(spec, "scratch_paths", ()) or ():
            target = Path(raw)
            if not target.is_absolute():
                logger.warning("agent %s: ignoring relative scratch path %r", agent_id, raw)
                continue
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
                logger.info("agent %s: removed scratch directory %s", agent_id, target)
            elif target.exists():
                target.unlink(missing_ok=True)
                logger.info("agent %s: removed scratch file %s", agent_id, target)
        self._sizes.pop(agent_id, None)
        self._jobs.pop(agent_id, None)
        self._runtime[agent_id] = _Runtime()
        logger.info("uninstalled agent %s", agent_id)

    async def reset(self, agent_id: str) -> None:
        """Wipe runtime state, keep the payload, and issue a new key+secret.

        Deliberately keeps ``bin`` (78 MB to download again) and ``workspace``
        (the operator's files); everything the agent derives -- config, model
        data, cache, its own state -- goes.

        A spec may name files that must survive the wipe (``reset_keep``), and
        the reason is the same one that makes reset useful: derived state can be
        rebuilt from this service, a human's edits cannot. DSH's config file is
        also the file its own settings pages write, so the operator's rows in it
        are carried across and ``write_config`` then merges over them -- which
        replaces only the rows this service owns. Measured: without this, a reset
        deleted the plugins and MCP servers an operator had added from the UI.
        """
        spec = self._spec(agent_id)
        if not self.installed(agent_id):
            raise AgentError(f"{spec.name} 尚未安装")
        self._claim(agent_id, "resetting")
        try:
            async with self._locks[agent_id]:
                await self._stop_locked(agent_id)
                directory = self.directory(agent_id)
                kept = _carry_over(directory, getattr(spec, "reset_keep", ()))
                for name in ("config", "data", "state", "cache", "tmp"):
                    target = directory / name
                    if target.exists():
                        shutil.rmtree(target, ignore_errors=True)
                    target.mkdir(parents=True, exist_ok=True)
                _restore_over(directory, kept)
                st = self.state(agent_id)
                if st.key_id:
                    self.key_store.revoke_key(st.key_id)
                raw, key = self.key_store.create_key(f"agent-{agent_id}")
                st.key_id = key.id
                st.secret = _new_secret()
                self.save_state()
                spec.write_config(directory, self._context(agent_id, raw))
                self._chmod_config(spec, directory)
                self._bump_size(agent_id)
                self._runtime[agent_id] = _Runtime()
                logger.info("reset agent %s", agent_id)
        finally:
            rt = self._runtime.get(agent_id)
            if rt is not None:
                rt.operation = None
                rt.operation_since = None

    # -- model list / config ---------------------------------------------
    def model_choices(self) -> list[ModelChoice]:
        """The models an agent may be configured with, with their contexts.

        Two facts have to be right, and only one of them is always observable:

        * **Context** decides both the agent's context window and how much
          output it reserves: a loaded model reports it from its graphs, an
          unloaded one only has its file name (``_seq32768_``) and the
          catalogue to go on.
        * **Vision** is a property of the bmodel's graphs. A loaded worker
          reports it from ``/health``; an unloaded directory can only be judged
          by its file name, and that heuristic looks for ``vl``/``vit``/
          ``vision`` -- none of the four 35B builds has any of those in its
          name, so an installed-but-unloaded model reads as text-only and
          every agent is written a config saying so (opencode
          ``attachment:false``, OpenClaw ``input:["text"]``). The catalogue
          already knows these four are VLMs, so it is the fallback for exactly
          that case.
        """
        from ..core.downloader import CATALOG

        catalog = {c["id"]: c for c in CATALOG}
        out: list[ModelChoice] = []
        for info in self.models.list():
            # An embedding or rerank model cannot answer a chat turn, so it is
            # not a choice an agent may be configured with -- offering it would
            # write a config whose every request fails with a 400.
            #
            # An OCR-VL model *can* answer the chat surface, which is why it is
            # excluded explicitly rather than by the same test: it only knows
            # how to read one image on request, so an agent configured with it
            # would fail every text turn -- and, being the only model in the
            # list, could even become the default.
            if info.kind not in AGENT_MODEL_KINDS:
                continue
            ctx = None
            if info.loaded and info.context_length:
                ctx = int(info.context_length)
            entry = catalog.get(info.model_id) or {}
            if ctx is None:
                if entry.get("context"):
                    ctx = int(entry["context"])
            if ctx is None and info.context_length:
                ctx = int(info.context_length)
            out.append(ModelChoice(
                id=info.model_id,
                context=ctx or FALLBACK_CONTEXT,
                vision=self._model_vision(info, entry),
            ))
        return out

    @staticmethod
    def _model_vision(info: ModelInfo, catalog_entry: dict) -> bool:
        """Whether a model takes images, with the loaded truth ranked first.

        A loaded model's capability comes from its own graphs (the worker's
        ``/health``), so it outranks the catalogue: if a build turns out to
        have no vit graph, the agent must not be told otherwise. When the model
        is not loaded, ``supports_vision`` is only the file-name guess, and
        False there means "this name says nothing" rather than "no vision" --
        that is the case the catalogue fills in. A model the catalogue does not
        list keeps the local answer, which is all anyone knows about it.
        """
        if info.supports_vision:
            return True
        if info.loaded:
            return False
        return bool(catalog_entry.get("vision"))

    def _pick_default_model(self, agent_id: str) -> str:
        choices = self.model_choices()
        st = self.state(agent_id)
        ids = [c.id for c in choices]
        if st.default_model in ids:
            return st.default_model
        return ids[0] if ids else ""

    def _context(self, agent_id: str, api_key: str) -> InstallContext:
        st = self.state(agent_id)
        return InstallContext(
            service_port=self.service_port,
            api_key=api_key,
            models=self.model_choices(),
            default_model=self._pick_default_model(agent_id),
            thinking=st.thinking,
            secret=st.secret,
            port=st.port or self._spec(agent_id).default_port,
            public_origins=self.public_origins,
        )

    async def sync(self, agent_id: str) -> dict:
        """Rewrite the config from the console, reported as ``configuring``.

        Separate from ``sync_config`` because the start path also rewrites the
        config, and that one already holds the ``starting`` operation -- a claim
        there would refuse the start it is part of.
        """
        self._claim(agent_id, "configuring")
        try:
            async with self._locks[agent_id]:
                self.sync_config(agent_id)
        finally:
            self._release(agent_id)
        return self.status_one(agent_id)

    def sync_config(self, agent_id: str) -> None:
        """Rewrite the agent's config from the current model list and settings."""
        spec = self._spec(agent_id)
        if not self.installed(agent_id):
            raise AgentError(f"{spec.name} 尚未安装")
        raw = self._recover_key(agent_id)
        st = self.state(agent_id)
        st.default_model = self._pick_default_model(agent_id)
        self.save_state()
        spec.write_config(self.directory(agent_id), self._context(agent_id, raw))
        self._chmod_config(spec, self.directory(agent_id))

    # -- start / stop ----------------------------------------------------
    async def start(self, agent_id: str) -> dict:
        """Start the agent, reported as ``starting`` for the whole wait.

        The status dict is built AFTER the operation is released: reporting
        ``starting`` alongside ``running: true`` in one payload would leave the
        console reading two contradictory facts at once.
        """
        spec = self._spec(agent_id)
        self._claim(agent_id, "starting")
        try:
            async with self._locks[agent_id]:
                await self._start_locked(spec)
        finally:
            self._release(agent_id)
        return self.status_one(agent_id)

    async def _start_locked(self, spec: AgentSpec) -> dict:
        agent_id = spec.id
        if not self.installed(agent_id):
            raise AgentError(f"{spec.name} 尚未安装，请先安装")
        rt = self._runtime[agent_id]
        if rt.proc is not None and rt.proc.returncode is None:
            return self.status_one(agent_id)
        if rt.orphan_pid and procs.process_alive(rt.orphan_pid, rt.orphan_start):
            # A process from a previous run matched this agent but never answered
            # its health check. Starting a second copy would have the two fight
            # over the same port, so the start is refused with what to do about
            # it. This is the "refuse loudly, never spawn twice" rule.
            raise AgentBusy(
                f"{spec.name} 的原进程（pid {rt.orphan_pid}）仍在运行但没有通过健康检查，"
                "已拒绝重复启动；请先点「停止」结束它，再「启动」")
        rt.orphan_pid = None
        rt.orphan_start = None

        st = self.state(agent_id)
        self._check_memory(spec)
        self._check_port(agent_id, st.port)
        # Config is rewritten on every start: the model list may have changed
        # since the last run, and a stale model in the config is a start that
        # looks fine and then fails on the first request.
        self.sync_config(agent_id)

        rt.crashes.clear()
        rt.stopping = False
        rt.last_error = ""
        rt.startup_error = ""
        rt.became_healthy = False
        rt.status = "starting"
        rt.exit_code = None
        rt.task = asyncio.create_task(self._supervise(agent_id))
        timeout = self.start_timeout_override or spec.start_timeout
        ok = await self._wait_healthy(agent_id, timeout)
        if not ok:
            await self._stop_locked(agent_id, kill_only=True)
            detail = rt.startup_error or rt.last_error or "启动超时"
            raise AgentBusy(f"{spec.name} 启动失败：{detail}")
        rt.status = "running"
        rt.became_healthy = True
        # The agent answered its probe; anything it still owes is finished here,
        # while the lock is held and before "running" is reported. A two-process
        # agent is ready only when its children are, and an agent that needs a
        # credential provisioned is unusable until it has one -- reporting
        # either as running is the "started but nothing works" symptom.
        #
        # The key is read back from the config rather than claimed: sync_config
        # has just written it, and asking the manager for a key here would issue
        # a new one on the failure path, revoking a key the agent still holds.
        directory = self.directory(agent_id)
        try:
            warning = await spec.after_start(
                directory,
                self._context(agent_id, spec.existing_key(directory)),
                st.port,
            )
        except AgentError as exc:
            await self._stop_locked(agent_id, kill_only=True)
            raise AgentBusy(f"{spec.name} 启动失败：{exc}") from exc
        # The start is the one moment an agent's launch credential is both fresh
        # and known to be needed, so this is where a spec gets to persist it.
        # What it does NOT do is rewrite the log file: the manager hands that
        # file to the running agent as its own stdout, so the credential stays in
        # the file and is filtered at the route that serves it (``logs()`` ->
        # ``spec.public_log``). See AgentSpec.redact_from_log.
        try:
            spec.redact_from_log(directory)
        except Exception:  # pragma: no cover - redaction must not fail a start
            logger.exception("agent %s: log redaction failed", agent_id)
        if warning:
            rt.last_error = warning
        return self.status_one(agent_id)

    async def restart(self, agent_id: str) -> dict:
        spec = self._spec(agent_id)
        self._claim(agent_id, "restarting")
        try:
            async with self._locks[agent_id]:
                await self._stop_locked(agent_id)
                await self._start_locked(spec)
        finally:
            self._release(agent_id)
        return self.status_one(agent_id)

    async def stop(self, agent_id: str) -> dict:
        self._claim(agent_id, "stopping")
        try:
            async with self._locks[agent_id]:
                await self._stop_locked(agent_id)
        finally:
            self._release(agent_id)
        return self.status_one(agent_id)

    async def _stop_locked(self, agent_id: str, kill_only: bool = False) -> None:
        rt = self._runtime[agent_id]
        rt.stopping = True
        rt.status = "stopped"
        # A survivor that was found but never adopted is the only thing "stop"
        # can do anything about, so it is stopped by the same rules: SIGTERM to
        # its group, then SIGKILL after the grace. (An agent may be killed: a
        # hung one is exactly what this button is for.)
        if rt.orphan_pid:
            await _stop_orphan(agent_id, rt.orphan_pid, rt.orphan_start)
            rt.orphan_pid = None
            rt.orphan_start = None
            rt.last_error = ""
        proc = rt.proc
        if proc is not None and proc.returncode is None:
            _signal_group(proc, 15)
            try:
                await asyncio.wait_for(proc.wait(), timeout=STOP_GRACE_S)
            except asyncio.TimeoutError:
                logger.warning("agent %s ignored SIGTERM, killing", agent_id)
                _signal_group(proc, 9)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:  # pragma: no cover - kernel stuck
                    logger.error("agent %s did not die after SIGKILL", agent_id)
        task = rt.task
        rt.task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        rt.proc = None
        rt.adopted = False
        rt.adopted_start = None
        # A child of the agent that outlived the parent -- a PicoClaw gateway
        # whose launcher crashed. The group signal above normally takes it, so
        # finding one here means the child left the group; it still holds the
        # agent's port and its model connection, so a stop that left it behind
        # would make the next start fail on a busy port. The failed-start path
        # needs this as much as a plain stop: a launcher that died while its
        # gateway was coming up leaves exactly the same thing behind.
        await self._stop_leftovers(agent_id)
        if kill_only:
            rt.status = "stopped"

    async def _stop_leftovers(self, agent_id: str) -> None:
        """Stop child processes of this agent that a group signal missed.

        Only pids the spec can prove are this agent's own are signalled, by the
        same SIGTERM-then-SIGKILL schedule the parent gets. Nothing is guessed
        from a port being open: see ``AgentSpec.leftovers``.
        """
        spec = self._spec(agent_id)
        st = self.state(agent_id)
        try:
            pids = spec.leftovers(self.directory(agent_id),
                                  st.port or spec.default_port)
        except Exception:  # pragma: no cover - discovery must not block a stop
            logger.exception("agent %s: enumerating leftover processes failed", agent_id)
            return
        for pid in pids:
            logger.warning("agent %s: stopping leftover process pid %d", agent_id, pid)
            await _stop_orphan(agent_id, pid, procs.read_start_time(pid))

    # -- supervision -----------------------------------------------------
    async def _supervise(self, agent_id: str) -> None:
        """Run the agent, restarting it with backoff until it stays up.

        Each iteration is one process lifetime. A crash is a real one only when
        nobody asked for the stop (``rt.stopping``); more than MAX_CRASHES
        within CRASH_WINDOW_S means the agent is broken, not unlucky, so the
        loop gives up and the console shows "失败" with the reason.

        A process that dies within ``crash_grace`` seconds is treated as a crash
        even when it answered /health first: opencode binds its port before its
        state is loaded, so "healthy" and "alive" are not the same thing.
        """
        spec = self._spec(agent_id)
        rt = self._runtime[agent_id]
        while not rt.stopping:
            try:
                proc = await self._spawn(spec)
            except Exception as exc:
                if rt.status == "starting":
                    rt.startup_error = f"无法启动进程：{exc}"
                rt.status = "failed"
                rt.last_error = rt.startup_error or str(exc)
                logger.exception("spawning %s failed", agent_id)
                return

            started = time.time()
            rt.proc = proc
            rt.started_at = started
            rt.exit_code = None
            # A supervised process is this run's own child: whatever was adopted
            # before it (or whatever an earlier lifetime was) is stale now.
            rt.adopted = False
            rt.adopted_start = None
            rt.orphan_pid = None
            rt.orphan_start = None
            # A fresh lifetime clears the previous failure text; otherwise a
            # recovered agent keeps advertising the crash it already survived.
            rt.last_error = ""
            if rt.status != "starting":
                rt.status = "running"
            rc = await proc.wait()
            rt.exit_code = rc
            rt.proc = None
            if rt.stopping:
                return

            now = time.time()
            uptime = now - started
            reason = f"进程退出（exit={rc}），运行 {uptime:.0f} 秒"
            # Every death counts, healthy or not: an agent that cannot start at
            # all is exactly the one that must not be respawned forever while
            # start() waits for it.
            if uptime < self.crash_grace:
                rt.crashes = [t for t in rt.crashes if now - t < CRASH_WINDOW_S]
                rt.crashes.append(now)
            else:
                # It ran long enough that this is not a crash loop.
                rt.crashes = []
            if not rt.became_healthy:
                rt.startup_error = reason
            logger.warning("agent %s: %s", agent_id, reason)
            if len(rt.crashes) > MAX_CRASHES:
                rt.status = "failed"
                rt.last_error = (
                    f"10 分钟内崩溃 {len(rt.crashes)} 次，已停止自动重启"
                    f"（最后一次 exit={rc}）"
                )
                return
            delay = min(32, 2 ** len(rt.crashes)) if rt.crashes else 0
            if rt.became_healthy:
                rt.status = "running"
                rt.last_error = f"{reason}，{delay} 秒后重启"
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return

    async def _spawn(self, spec: AgentSpec) -> asyncio.subprocess.Process:
        agent_id = spec.id
        directory = self.directory(agent_id)
        (directory / "workspace").mkdir(parents=True, exist_ok=True)
        (directory / "logs").mkdir(parents=True, exist_ok=True)
        log_path = directory / "logs" / "agent.log"
        # Every launch goes through here -- a console start, a restart, and the
        # supervisor's own respawn after a crash -- so this is the one place that
        # can guarantee no credential from a previous lifetime survives into this
        # one. An agent that mints a token per process (DSH) would otherwise hand
        # the console a token its new process never issued: the proxy spends it,
        # gets 401, and the embedded page stays broken until the whole service is
        # restarted. Measured on the first stop/start.
        # Rotate first: the launch-line window starts at the log's size *after*
        # rotation, or a rotated (now short) file would hide this process' line.
        self._rotate_log(log_path)
        forget = getattr(spec, "forget_launch_url", None)
        if callable(forget):
            forget(directory)

        st = self.state(agent_id)
        env = dict(os.environ)
        env.update(spec.env(directory, st.secret))
        env.update({"PYTHONUNBUFFERED": "1"})

        cmd = spec.command(directory, st.port)
        env_list = {k: str(v) for k, v in env.items() if v is not None}

        log = open(log_path, "ab", buffering=0)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(directory / "workspace"),
                env=env_list,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                # Own session: a stop signals the whole group, so a shell
                # wrapper or a helper the agent forked cannot survive it.
                start_new_session=True,
            )
        finally:
            # The child holds the fd; the parent must not keep a handle that
            # would pin the file across a rotation.
            log.close()
        logger.info("agent %s started pid=%s port=%s", agent_id, proc.pid, st.port)
        return proc

    @staticmethod
    def _rotate_log(path: Path) -> None:
        try:
            if path.exists() and path.stat().st_size >= LOG_ROTATE_BYTES:
                os.replace(path, path.with_name(path.name + ".1"))
        except OSError:  # pragma: no cover - a rotating log must never block a start
            logger.warning("rotating %s failed", path)

    async def _wait_healthy(self, agent_id: str, timeout: float) -> bool:
        spec = self._spec(agent_id)
        rt = self._runtime[agent_id]
        st = self.state(agent_id)
        url = spec.health_url(st.port)
        auth = spec.health_auth(st.secret)
        # Monotonic: a forward clock step (NTP after boot) must not cut the
        # wait short and fail a start that is still on schedule.
        deadline = time.monotonic() + timeout
        async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
            while time.monotonic() < deadline:
                if rt.proc is None and rt.startup_error:
                    return False
                try:
                    r = await client.get(url, auth=auth)
                except httpx.HTTPError:
                    await asyncio.sleep(0.4)
                    continue
                if r.status_code == 200:
                    rt.status = "running"
                    return True
                await asyncio.sleep(0.4)
        rt.startup_error = rt.startup_error or f"健康检查 {url} 在 {timeout:.0f} 秒内未通过"
        return False

    # -- guards ----------------------------------------------------------
    def _check_memory(self, spec: AgentSpec | None = None) -> None:
        """Refuse the start when the board cannot hold this agent.

        The floor is per agent: the framework's default (``MEMORY_FLOOR_BYTES``)
        is sized for a single small binary, and OpenClaw declares its own ~1 GB.
        A single shared number would either let OpenClaw start into an OOM kill
        or lock out the agent that does fit.
        """
        floor = getattr(spec, "memory_floor_bytes", 0) or self.memory_floor_bytes
        mem = monitor.memory()
        available = mem.get("available_bytes")
        if available is None:
            return  # a host without /proc/meminfo is not this board; do not block
        if available < floor:
            name = getattr(spec, "name", "") or "agent"
            raise MemoryLow(
                f"系统可用内存仅 {available / 1048576:.0f} MB，"
                f"低于启动 {name} 所需的 {floor / 1048576:.0f} MB；"
                "请先卸载模型或停止其它 agent"
            )

    def _check_port(self, agent_id: str, port: int) -> None:
        if not (1 <= int(port) <= 65535):
            raise AgentError(f"端口 {port} 不合法")
        spec = self._spec(agent_id)
        # An agent that forks a server of its own owns more than the port on its
        # command line: PicoClaw's gateway listens one port up, and giving that
        # number to another agent would make the second one fail its start with
        # a bare EADDRINUSE on a port neither the console nor agents.json
        # mentions.
        mine = {int(port), *spec.children_ports(self.directory(agent_id), port)}
        for other, st in self.states.items():
            if other == agent_id:
                continue
            rt = self._runtime.get(other)
            if rt is None or rt.proc is None:
                continue
            other_spec = self._spec(other)
            other_port = st.port or other_spec.default_port
            theirs = {int(other_port),
                      *other_spec.children_ports(self.directory(other), other_port)}
            clash = mine & theirs
            if clash:
                raise PortBusy(
                    f"端口 {sorted(clash)[0]} 已被 {other_spec.name} 占用")
        for candidate in sorted(mine):
            if _port_in_use(candidate):
                raise PortBusy(f"端口 {candidate} 已被其它进程占用，请换一个")

    # -- settings --------------------------------------------------------
    async def patch(self, agent_id: str, changes: dict) -> dict:
        """Apply the console's settings.

        Port, default model and the thinking flag all end up in the config or on
        the command line, so changing any of them while the agent runs means a
        restart -- otherwise the console would show a value the running process
        does not use. A stopped agent just takes them at its next start.
        """
        spec = self._spec(agent_id)
        st = self.state(agent_id)
        self._claim(agent_id, "configuring")
        try:
            async with self._locks[agent_id]:
                return await self._patch_locked(agent_id, spec, st, changes)
        finally:
            self._release(agent_id)

    async def _patch_locked(self, agent_id: str, spec: AgentSpec, st: AgentState,
                            changes: dict) -> dict:
        up = self._is_up(agent_id)
        restart_needed = False
        if changes.get("port") is not None:
            port = int(changes["port"])
            if port != st.port:
                self._check_port(agent_id, port)
                st.port = port
                restart_needed = restart_needed or up
        if changes.get("autostart") is not None:
            st.autostart = bool(changes["autostart"])
        if changes.get("default_model") is not None:
            wanted = str(changes["default_model"])
            if wanted and wanted not in {c.id for c in self.model_choices()}:
                raise AgentError(f"模型 {wanted} 不存在")
            if wanted != st.default_model:
                st.default_model = wanted
                restart_needed = restart_needed or up
        if changes.get("thinking") is not None:
            if bool(changes["thinking"]) != st.thinking:
                st.thinking = bool(changes["thinking"])
                restart_needed = restart_needed or up
        self.save_state()
        if restart_needed and up and self.installed(agent_id):
            await self._stop_locked(agent_id)
            await self._start_locked(spec)
        elif self.installed(agent_id):
            # A stopped agent still has to *have* the new settings. Saving them
            # to agents.json alone leaves the config file describing the old
            # model, so the console shows one thing and the next start would run
            # the previous one -- measured on the board: a stopped OpenClaw kept
            # ``primary: ...128k`` while its state said ``32k``.
            self.sync_config(agent_id)
        return self.status_one(agent_id)

    def _is_up(self, agent_id: str) -> bool:
        rt = self._runtime[agent_id]
        if rt.proc is None:
            return False
        if rt.adopted:
            # We are not this process' parent, so ``returncode`` only learns
            # about its death when someone looks. Without this check an adopted
            # agent reads as running until the next stop, which is exactly the
            # state that makes the console offer a stop button for nothing.
            if procs.process_alive(rt.proc.pid, rt.adopted_start):
                return True
            self._reap_adopted(agent_id)
            return False
        return rt.proc.returncode is None

    def _reap_adopted(self, agent_id: str) -> None:
        """Notice that a process adopted at startup has since died.

        An adopted agent has no supervisor task -- there is no child to ``await``,
        so nothing would ever report its exit. Status polling is what notices,
        and it must correct the record rather than leave ``running`` behind: the
        console would otherwise show a running agent that answers nothing, and
        neither ``autostart`` nor the crash counter would ever see the death.

        Deliberately does NOT restart it. The supervisor's backoff exists to
        survive a flapping child; a process this run never forked is one whose
        failure mode we did not observe, so the operator is told and a start is
        left to them (or to the next boot's autostart).
        """
        rt = self._runtime[agent_id]
        pid = rt.proc.pid if rt.proc is not None else None
        logger.warning("adopted agent %s (pid %s) has exited", agent_id, pid)
        rt.proc = None
        rt.adopted = False
        rt.adopted_start = None
        rt.status = "stopped"
        rt.exit_code = rt.exit_code if rt.exit_code is not None else -1
        rt.last_error = (
            f"接管的进程（pid {pid}）已退出；如需继续运行请点「启动」")

    # -- adoption --------------------------------------------------------
    def _agent_identity(self, agent_id: str) -> dict:
        """What a candidate process must match to be *this* agent.

        Four facts, each of which rejection-tests a different mistake:

          * ``exe``      -- the binary really is the one the spec starts, so a
                            process that merely mentions it in ``argv`` (a shell,
                            an editor, this service) does not qualify;
          * ``cwd``      -- inside this agent's own directory, which is where
                            ``_spawn`` starts it and nowhere else does;
          * ``port``     -- the port in its command line is the one agents.json
                            says, so two installs of the same agent (a second
                            data root, an old checkout) do not collide;
          * ``argvs``    -- the tokens that make it this agent and not another
                            program with the same interpreter.

        ``argvs`` is a *subsequence* requirement rather than a set match: the
        agent's own `serve --port N` flags may be reordered or extended by its
        launcher, but the script/orchestrator tokens are what identify it.
        """
        spec = self._spec(agent_id)
        directory = self.directory(agent_id)
        st = self.state(agent_id)
        port = st.port or spec.default_port
        try:
            cmd = spec.command(directory, port)
        except Exception:  # pragma: no cover
            cmd = []
        exe = cmd[0] if cmd else ""
        # The identifying tokens are the command minus its option/value pairs:
        # the port is compared separately (it is per-agent state), and a bind
        # address or a flag value says nothing about *which* program this is.
        argvs: list[str] = []
        skip_value = False
        for tok in cmd[1:]:
            if skip_value:
                skip_value = False
                continue
            if tok.startswith("-"):
                skip_value = True
                continue
            argvs.append(tok)
        return {
            "exe": exe,
            "cwd": str(directory),
            "port": int(port),
            "argvs": argvs,
            "spec": spec,
        }

    def _match_survivor(self, agent_id: str, found: list[procs.ProcInfo],
                        claimed: set[int]) -> procs.ProcInfo | None:
        """The one process that is provably this agent's, or ``None``.

        Every clause rejects: a false positive here means signalling a stranger.
        """
        ident = self._agent_identity(agent_id)
        spec: AgentSpec = ident["spec"]
        matches: list[procs.ProcInfo] = []
        for cand in found:
            if cand.pid in claimed:
                continue  # already accounted for as another agent's
            if not procs.same_path(cand.exe, ident["exe"]):
                continue
            if not procs.is_under(cand.cwd, ident["cwd"]):
                continue
            if procs.arg_value(cand.argv, "--port") != str(ident["port"]):
                continue
            if not _contains_in_order(cand.argv, ident["argvs"]):
                continue
            matches.append(cand)
        if not matches:
            return None
        if len(matches) > 1:
            pids = ", ".join(str(m.pid) for m in matches)
            raise AgentBusy(
                f"{spec.name} 有多个匹配的存活进程（pid {pids}），无法安全接管；"
                "请人工确认后停止多余的进程")
        return matches[0]

    async def adopt(self) -> list[dict]:
        """Reattach to agents a previous run left running.

        Returns the status of every agent that is now running under this run's
        supervision. The rules, and why each exists:

        * Only ``agents.json``'s own port and directory are accepted, so an
          agent belonging to another data root is never touched.
        * The process must pass :meth:`_match_survivor` (exact executable, own
          cwd, own port, its own command tokens) -- "the port is open" is not
          evidence of anything and is never used as one.
        * The authenticated ``/health`` must answer, the same check
          :meth:`_wait_healthy` applies after a start. A process that fails it
          is an **orphan**: it is reported (``status: failed``, ``orphan_pid``,
          ``last_error``) and left alone -- not adopted, not killed, and not
          restarted, because a second copy on the same port cannot work either.
        * Nothing is spawned here. This runs before
          :meth:`autostart`, which then skips an agent that is already up
          precisely because it is up.
        * Nothing is adopted either while **another service instance on the same
          data root is alive** (``procs.service_instances``): those agents have a
          living owner, and two consoles driving one process would each report
          the other's stops as crashes. Each agent with a candidate is then
          reported as a conflict instead.
        """
        adopted: list[dict] = []
        try:
            rivals = procs.service_instances(self.data_root, exclude_pid=os.getpid())
        except Exception:  # pragma: no cover - /proc trouble means "cannot tell"
            rivals = []
        found = procs.scan_processes()
        claimed: set[int] = set()
        for agent_id in self.specs:
            if not self.installed(agent_id):
                continue
            rt = self._runtime[agent_id]
            if rt.proc is not None:
                continue  # this run already owns something for it
            try:
                cand = self._match_survivor(agent_id, found, claimed)
            except AgentBusy as exc:
                rt.status = "failed"
                rt.last_error = str(exc)
                logger.error("agent %s: %s", agent_id, exc)
                continue
            if cand is None:
                continue
            if rivals:
                pids = ", ".join(str(r.pid) for r in rivals)
                rt.status = "failed"
                rt.last_error = (
                    f"另一个本服务实例（pid {pids}）仍在使用同一个数据目录，"
                    f"pid {cand.pid} 归它管理；不会接管也不会重复启动")
                logger.error("agent %s: %s", agent_id, rt.last_error)
                continue
            claimed.add(cand.pid)
            st = self.state(agent_id)
            ok = await self._probe_health(agent_id, st.port or self._spec(agent_id).default_port)
            if not ok:
                rt.status = "failed"
                rt.last_error = (
                    f"接管失败：pid {cand.pid} 是本 agent 的进程（端口 "
                    f"{st.port}），但健康检查未通过；已保留进程不动，"
                    "不会重复启动。请点「停止」后再「启动」")
                logger.warning("agent %s: %s", agent_id, rt.last_error)
                # Still record the pid: "stop" must be able to reach it, and a
                # status that hides the process would make that impossible.
                rt.orphan_pid = cand.pid
                rt.orphan_start = cand.start_time
                continue
            rt.proc = procs.AdoptedProcess(cand.pid, allow_kill=True,
                                           start_time=cand.start_time)
            rt.adopted = True
            # An agent whose launch credential lives in its log kept it while
            # this service was down; taking it out now is what makes the promise
            # hold across a restart too, not only across a start.
            try:
                self._spec(agent_id).redact_from_log(self.directory(agent_id))
            except Exception:  # pragma: no cover - redaction must not fail adoption
                logger.exception("agent %s: log redaction failed", agent_id)
            rt.adopted_start = cand.start_time
            rt.status = "running"
            rt.became_healthy = True
            # start_time is boot-relative (an identity marker); the uptime
            # shown in the console needs it on the wall clock.
            rt.started_at = procs.start_time_epoch(cand.start_time) or time.time()
            rt.last_error = ""
            rt.exit_code = None
            logger.info("adopted agent %s: pid %d on port %d",
                        agent_id, cand.pid, st.port)
            adopted.append(self.status_one(agent_id))
        return adopted

    async def _probe_health(self, agent_id: str, port: int) -> bool:
        """The authenticated readiness check, against a process we did not start."""
        spec = self._spec(agent_id)
        st = self.state(agent_id)
        try:
            async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
                r = await client.get(spec.health_url(port), auth=spec.health_auth(st.secret))
        except httpx.HTTPError:
            return False
        return r.status_code == 200

    # -- reporting -------------------------------------------------------
    def status(self, host: str = "127.0.0.1") -> list[dict]:
        return [self.status_one(sid, host) for sid in self.specs]

    def status_one(self, agent_id: str, host: str = "127.0.0.1") -> dict:
        spec = self._spec(agent_id)
        st = self.state(agent_id)
        rt = self._runtime[agent_id]
        installed = self.installed(agent_id)
        up = self._is_up(agent_id)
        # A failure that is neither a crash nor a failed start: an agent that is
        # healthy and missing a subsystem it was configured with. Only asked of a
        # running agent with nothing more urgent to report -- before that there is
        # nothing to read, and the spec's own `after_start` warning already covers
        # the start itself.
        runtime_warning = ""
        if up and not rt.last_error:
            ask = getattr(spec, "runtime_warning", None)
            if callable(ask):
                try:
                    runtime_warning = ask(self.directory(agent_id))
                except Exception:  # noqa: BLE001 - a probe must not break the card
                    logger.exception("agent %s: runtime warning probe failed", agent_id)
        pid = rt.proc.pid if (up and rt.proc is not None) else None
        job = self._jobs.get(agent_id)
        operation = self.operation_of(agent_id)
        # `status` is the four-value summary the cards are built on; `operation`
        # is what it cannot express. They are folded here, together, so a
        # starting agent never reports "running": the process exists (the
        # supervisor spawned it) but it has not passed /health, and claiming
        # otherwise is what let the console offer "stop" on an agent that would
        # have refused every request.
        starting = operation == "starting"
        if not installed:
            status = "not_installed"
        elif up and not starting:
            status = "running"
        elif rt.status == "failed":
            status = "failed"
        else:
            status = "stopped"
        running = up and not starting
        if starting:
            pid = rt.proc.pid if rt.proc is not None else None
        else:
            pid = rt.proc.pid if (up and rt.proc is not None) else None
        # A survivor that matched this agent but never answered its health check
        # is reported as a pid with no health -- never as running, and never as
        # absent (its port and its memory are real, and "stop" is what clears it).
        orphan = rt.orphan_pid if rt.orphan_pid and procs.process_alive(
            rt.orphan_pid, rt.orphan_start) else None
        return {
            "id": agent_id,
            "name": spec.name,
            "version": st.version or spec.version,
            "latest_version": spec.version,
            "default_port": spec.default_port,
            "port": st.port or spec.default_port,
            "installed": installed,
            "status": status,
            "operation": operation,
            "operation_since": rt.operation_since,
            "busy": operation is not None,
            "operation_label": _OPERATION_LABEL.get(operation, ""),
            "running": running,
            "pid": pid if pid is not None else orphan,
            # True only when the agent answered this run's own health check --
            # an adopted process is healthy because ``adopt`` proved it; an
            # orphan is exactly the case where the port is open and the agent is
            # not answering.
            "health": up,
            "adopted": bool(rt.adopted and running),
            "orphan_pid": orphan,
            "rss_bytes": _rss_bytes(pid or orphan) if (pid or orphan) else 0,
            "disk_bytes": self._disk_bytes(agent_id) if installed else 0,
            "autostart": st.autostart,
            "default_model": st.default_model,
            "thinking": st.thinking,
            "embeddable": spec.embeddable,
            "proxied": spec.proxied,
            "card_note": getattr(spec, "card_note", ""),
            "memory_floor_bytes": getattr(spec, "memory_floor_bytes", 0) or self.memory_floor_bytes,
            "web_url": spec.web_url(host, st.port or spec.default_port, st.secret) if installed else "",
            "web": {
                # Shown on the card with a copy button: the agent has its own
                # login, and the operator should not have to dig for it.
                "username": spec.web_credentials(st.secret)[0],
                "password": spec.web_credentials(st.secret)[1],
            },
            "models": [{"id": c.id, "context": c.context, "vision": c.vision}
                       for c in self.model_choices()],
            # An agent that forks a server of its own owns a second port. The
            # console does not need to reach it, but an operator reading "端口
            # 14097 被谁占了" does.
            "child_ports": list(spec.children_ports(
                self.directory(agent_id), st.port or spec.default_port)),
            "started_at": rt.started_at or None,
            "uptime_s": round(time.time() - rt.started_at, 1) if running and rt.started_at else None,
            "exit_code": rt.exit_code,
            "last_error": rt.last_error or runtime_warning,
            "job": job.public() if job is not None else None,
        }

    def job(self, agent_id: str) -> dict | None:
        self._spec(agent_id)
        job = self._jobs.get(agent_id)
        return job.public() if job is not None else None

    def logs(self, agent_id: str, tail: int = 200) -> str:
        spec = self._spec(agent_id)
        path = self.directory(agent_id) / "logs" / "agent.log"
        if not path.is_file():
            return ""
        tail = max(1, min(5000, int(tail)))
        try:
            with open(path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                # ~200 bytes per line is a generous over-estimate; read a window
                # rather than the whole 10 MB into memory.
                start = max(0, size - tail * 240)
                fh.seek(start)
                data = fh.read()
        except OSError:
            return ""
        lines = data.decode("utf-8", "replace").splitlines()
        if start > 0 and lines:
            lines = lines[1:]  # the first line is probably cut in half
        # An agent that prints its own launch credential has it removed here as
        # well as in the file: this route is what the console shows, and a token
        # that reached it once is a token in a screenshot.
        return spec.public_log("\n".join(lines[-tail:]))

    def _disk_bytes(self, agent_id: str) -> int:
        ts, size = self._sizes.get(agent_id, (0.0, 0))
        if time.time() - ts < SIZE_TTL_S:
            return size
        return self._bump_size(agent_id)

    def _bump_size(self, agent_id: str) -> int:
        _, size = walk_stats(self.directory(agent_id))
        self._sizes[agent_id] = (time.time(), size)
        return size

    # -- service lifecycle -----------------------------------------------
    async def autostart(self) -> None:
        """Bring up the agents marked autostart. Failures are logged, not fatal.

        Run after :meth:`adopt`: an agent this run already reattached to is up,
        and ``start`` is a no-op for it -- so a restart never produces a second
        copy of an agent the previous run left running.
        """
        for agent_id in self.specs:
            st = self.states.get(agent_id)
            if not st or not st.autostart or not self.installed(agent_id):
                continue
            try:
                await self.start(agent_id)
            except Exception as exc:
                logger.warning("autostart of %s failed: %s", agent_id, exc)

    async def shutdown(self) -> None:
        """Stop every agent: SIGTERM to the group, then SIGKILL.

        Bypasses the operation guard: this runs when the service is going away,
        and an install or a start that happens to be in flight must not be able
        to keep a child process alive past the shutdown.
        """
        for agent_id in list(self.specs):
            try:
                async with self._locks[agent_id]:
                    await self._stop_locked(agent_id)
            except Exception:  # pragma: no cover - shutting down anyway
                logger.warning("stopping %s on shutdown failed", agent_id)

    # -- download --------------------------------------------------------
    async def _fetch(
        self, artifact: Artifact, name: str, progress: ProgressFn,
    ) -> Path:
        """Fetch one artifact, verifying its sha256, trying each source in order.

        Staged under ``<data>/downloads`` and only moved into place once the
        hash matches, so an interrupted download can never be mistaken for an
        installed payload. Sources are the dfss mirror, a local override
        directory, a ``file://`` path and finally upstream HTTP; every one that
        fails is remembered so the operator sees *why* each was rejected rather
        than a single opaque error.
        """
        suffix = _archive_suffix(artifact.filename)
        target = self.downloads / f"{name}{suffix}"
        if target.is_file() and _sha256(target) == artifact.sha256:
            progress(target.stat().st_size, target.stat().st_size)
            return target

        sources = artifact.sources()
        if not sources:
            raise AgentError(
                f"安装包下载失败：没有可用的下载地址（CV84X6_AGENT_OFFLINE 已开启，"
                f"{artifact.filename} 没有 dfss 源）"
            )

        errors: list[str] = []
        for url in sources:
            part = target.with_name(target.name + ".part")
            try:
                # Which source actually served an install is not cosmetic: the
                # whole point of the dfss mirror is that a board with no route
                # to the internet still works, and "it installed" alone cannot
                # tell an operator which of the two happened.
                logger.info("agent %s: fetching %s from %s", name, artifact.filename, url)
                if is_dfss(url):
                    await self._download_dfss(url, part, artifact, progress)
                elif url.startswith("file://"):
                    await self._copy_local(Path(url[7:]), part, progress)
                elif "://" not in url:
                    await self._copy_local(Path(url), part, progress)
                else:
                    await self._download_http(url, part, artifact.size, progress)
            except Exception as exc:
                logger.warning("agent %s: %s failed: %s", name, url, exc)
                errors.append(f"{url}: {exc}")
                part.unlink(missing_ok=True)
                continue
            digest = _sha256(part)
            if digest != artifact.sha256:
                part.unlink(missing_ok=True)
                raise AgentError(
                    f"安装包校验失败：{url} 的 sha256 是 {digest}，"
                    f"期望 {artifact.sha256}；已删除下载文件"
                )
            os.replace(part, target)
            logger.info("agent %s: %s served from %s (%d bytes, sha256 ok)",
                        name, artifact.filename, _source_kind(url), target.stat().st_size)
            return target
        raise AgentError("安装包下载失败：" + "；".join(errors or ["没有可用的下载地址"]))

    async def _download_dfss(
        self, url: str, dest: Path, artifact: Artifact, progress: ProgressFn,
    ) -> None:
        """One pull through the vendor's dfss tool.

        dfss reports a percentage and the bytes it has moved so far; the total
        comes from the artifact, which is what lets the console show MiB rather
        than a bar with no denominator.
        """
        total = artifact.size
        last = [0]

        def on_line(text: str) -> None:
            step = dfss_progress(text, total)
            if step is None:
                return
            done, _percent = step
            # dfss' bar is re-drawn in place, so the same number arrives many
            # times; only report real movement.
            if done >= last[0]:
                last[0] = done
                progress(done, total)

        await download_dfss_file(dfss_target(url), dest, on_line)
        if total:
            progress(total, total)

    async def _copy_local(self, src: Path, dest: Path, progress: ProgressFn) -> None:
        if not src.is_file():
            raise FileNotFoundError(f"本地安装包不存在：{src}")
        total = src.stat().st_size
        done = 0
        with open(src, "rb") as fin, open(dest, "wb") as fout:
            while True:
                chunk = fin.read(1 << 20)
                if not chunk:
                    break
                fout.write(chunk)
                done += len(chunk)
                progress(done, total)
                await asyncio.sleep(0)  # let the job's poller run

    async def _download_http(
        self, url: str, dest: Path, expected: int | None, progress: ProgressFn,
    ) -> None:
        done = 0
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=True, trust_env=False,
        ) as client:
            async with client.stream("GET", url) as r:
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code}")
                total = expected or _int_or_none(r.headers.get("content-length"))
                with open(dest, "wb") as fout:
                    async for chunk in r.aiter_bytes(1 << 20):
                        fout.write(chunk)
                        done += len(chunk)
                        progress(done, total)


def _contains_in_order(argv: list[str], needles: list[str]) -> bool:
    """Whether ``needles`` appear in ``argv`` in this order, ignoring gaps.

    Used instead of a set comparison because a launcher may insert or reorder its
    own flags; what identifies the program is the sequence of its non-flag
    tokens (the script it runs, its subcommand), not their exact positions.
    """
    if not needles:
        return True
    remaining = iter(argv)
    return all(any(tok == want for tok in remaining) for want in needles)


def _new_secret() -> str:
    import secrets
    return secrets.token_urlsafe(18)


def _carry_over(directory: Path, relatives: Iterable[str]) -> dict[str, bytes]:
    """Read the files a reset must preserve, as ``{relative path: bytes}``.

    Called *before* the wipe. Missing files are simply absent from the result,
    so a first reset on a fresh install costs nothing and never fails.

    Bytes rather than a copy on disk: the wipe removes whole layer directories,
    so a temporary copy would have to live outside the agent tree, and an
    in-memory read is one file either way (``reset_keep`` is for a config file,
    not for an installation).
    """
    kept: dict[str, bytes] = {}
    for relative in relatives:
        path = Path(directory) / relative
        try:
            kept[relative] = path.read_bytes()
        except OSError:
            continue
    return kept


def _restore_over(directory: Path, kept: dict[str, bytes]) -> None:
    """Put back what :func:`_carry_over` read, recreating parent directories."""
    for relative, data in kept.items():
        path = Path(directory) / relative
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError:  # pragma: no cover - a read-only tree is the host's problem
            logger.warning("could not restore %s across a reset", relative)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _port_in_use(port: int) -> bool:
    """Whether something already listens on ``port``.

    A connect attempt rather than a bind: SO_REUSEADDR (which asyncio sets)
    would let a bind succeed over a listening socket, and the point here is to
    find out who the client will actually reach.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.35)
        try:
            return s.connect_ex(("127.0.0.1", int(port))) == 0
        except OSError:
            return False


def _signal_group(proc: PopenLike, sig: int) -> None:
    """Signal the whole process group, falling back to the process itself."""
    procs.signal_group(proc.pid, sig)


async def _stop_orphan(agent_id: str, pid: int, start: float | None) -> None:
    """SIGTERM, then SIGKILL, a survivor this run did not adopt.

    ``await asyncio.sleep`` rather than ``time.sleep``: this runs on the event
    loop, and an agent that ignores SIGTERM would otherwise freeze the whole
    console -- including the status poll the operator is watching -- for the
    length of the grace period.
    """
    if not procs.process_alive(pid, start):
        return
    procs.signal_group(pid, 15)
    deadline = time.monotonic() + STOP_GRACE_S
    while time.monotonic() < deadline:
        if not procs.process_alive(pid, start):
            return
        await asyncio.sleep(0.05)
    logger.warning("agent %s: pid %d ignored SIGTERM, killing", agent_id, pid)
    procs.signal_group(pid, 9)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and procs.process_alive(pid, start):
        await asyncio.sleep(0.05)


def _rss_bytes(pid: int) -> int:
    """Resident memory of the agent's whole process tree, in bytes.

    The agent is not one process. OpenClaw's launcher forks a gateway child
    that does the real work: measured on the board the parent sits at ~59 MB
    while the tree holds ~1.4-1.9 GB. Reporting only the parent made the console
    say 59 MB while the machine was in fact nearly full, which is worse
    than saying nothing -- an operator checking "how much is this costing me"
    has to be able to trust the number.

    The tree is found by walking ``PPid`` over ``/proc`` rather than reading
    ``/proc/<pid>/task/<tid>/children``: that file needs CONFIG_PROC_CHILDREN
    and is absent on this board's kernel (measured 2026-10-26), where the walk
    below returned just the launcher's own 59 MB. Children are summed rather
    than de-duplicated by Pss because a start is a one-off call and the tree is
    small; the overcount from shared pages is a few MB against a GB.
    """
    parent_of: dict[int, int] = {}
    rss_of: dict[int, int] = {}
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return 0
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "status").read_text().splitlines()
        except (OSError, ValueError):
            continue
        ppid = -1
        rss = 0
        for line in fields:
            if line.startswith("PPid:"):
                ppid = int(line.split()[1])
            elif line.startswith("VmRSS:"):
                rss = int(line.split()[1]) * 1024
        if ppid < 0:
            continue
        try:
            parent_of[int(entry.name)] = ppid
        except ValueError:
            continue
        rss_of[int(entry.name)] = rss

    children: dict[int, list[int]] = {}
    for child, parent in parent_of.items():
        children.setdefault(parent, []).append(child)

    total = 0
    seen: set[int] = set()
    stack = [int(pid)]
    while stack and len(seen) < 2048:  # bound: a runaway fork must not hang status
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        total += rss_of.get(current, 0)
        stack.extend(children.get(current, ()))
    return total
