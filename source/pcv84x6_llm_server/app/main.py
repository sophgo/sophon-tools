"""Service entry point.

One uvicorn process serves three things: the OpenAI API, the management API, and
the built front-end. Model inference lives in child processes (see
app/engine/worker.py) so that a model crash or an unload cannot take this process
with it.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .agents.manager import STATE_FILE, AgentManager
from .api import (admin_api, agent_proxy, agents_api, apps_api, asr_stream_api,
                  docs as api_docmeta, logs_api, mcp_api, openai_api)
from .apps.kb.ingest import Ingestor
from .apps.kb.store import KbStore
from .core.auth import AdminSessions, require_admin_docs
from .core.audit import DEFAULT_FILENAME as AUDIT_FILE, AuditMiddleware, AuditStore
from .core.downloader import DownloadManager
from .core.errors import install_error_handlers
from .core.inference_log import DEFAULT_FILENAME as INFERENCE_LOG_FILE, InferenceLogStore
from .core import logs as logmod
from .core.models import ModelManager
from .core.state import StateStore
from .core.storage import StorageManager, ensure_layout
from .core.vpp_reserve import VppReservation
from .core import monitor as _monitor

logger = logging.getLogger("cv84x6")

BASE = Path(__file__).resolve().parent.parent
MAX_BODY_BYTES = 48 * 1024 * 1024
# The service's own configuration file, read by systemd through EnvironmentFile=.
# A move rewrites this file; an install without it (a dev checkout) has nothing
# to persist to, which the storage job reports rather than failing.
DEFAULT_ENV_FILE = BASE / "etc" / "server.env"


class BodyLimit:
    """Refuse bodies over MAX_BODY_BYTES before reading them into memory.

    Base64 images make large bodies legitimate, but past this the request
    cannot fit a prompt anyway (the board has ~2.5 GiB of RAM). Plain ASGI on
    purpose: Starlette's BaseHTTPMiddleware (@app.middleware) wraps receive()
    and hides the client disconnect from handlers, so a non-streaming request
    whose client gave up would keep the NPU busy.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            for k, v in scope.get("headers", []):
                if k == b"content-length" and v.isdigit() and int(v) > MAX_BODY_BYTES:
                    resp = JSONResponse({"detail": f"request body over {MAX_BODY_BYTES >> 20} MiB"},
                                        status_code=413)
                    await resp(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def _register_client(app: FastAPI):
    """The ``ModelManager.on_loaded`` hook: bind an RPC client as part of a load.

    ``ModelManager.load`` publishes ``loaded: true`` only after the worker is
    fully initialised, and from that instant a request may use the model --
    ``/v1/chat/completions`` looks the client up by model id. Registering it
    only after ``load()`` returned left a window where the model read as loaded
    with no client behind it, which surfaced as a 500.
    """
    from .api.admin_api import register_client

    def hook(model_id: str, info) -> None:
        client = register_client(app, model_id, info.port)
        if client is not None:
            # Every inference call through this client is a use of the model:
            # the idle clock restarts at each batch of a long job, not only at
            # the request that started it.
            client.on_activity = lambda: app.state.models.touch(model_id)

    return hook


def _drop_client(app: FastAPI):
    """The ``ModelManager.on_unloading`` hook: destroy the RPC client mid-switch.

    Runs after the manager published ``operation: "unloading"`` and before it
    signals the worker, which is the only window where both halves of the
    unload are correct at once: the model is already refused by every inference
    route, so nothing new can use the socket, and closing it first is what lets
    the worker's shutdown finish in ~0.6 s instead of hitting the 120 s grace
    (see ``admin_api.unload_model``).
    """

    async def hook(model_id: str) -> None:
        from .api.admin_api import forget_client

        await forget_client(app, model_id)

    return hook


def create_app(
    data_dir: Path | None = None,
    models_dir: Path | None = None,
    backend_kind: str = "mock",
    web_dir: Path | None = None,
    max_loaded: int = 0,
    context_length_override: int | None = None,
    decode_delay_ms: float = 0.0,
    native_lib: str | None = None,
    data_root: Path | None = None,
    env_file: Path | None = None,
    install_dir: Path | None = None,
    agent_specs=None,
    service_port: int = 8000,
    public_origin: str | None = None,
) -> FastAPI:
    """Build the app.

    ``service_port`` is the port this service is reachable on *from the board*;
    an agent's config points its provider at ``127.0.0.1:<service_port>/v1``, so
    the console passes the real listen port rather than the default 8000.
    """
    # Two layouts, one meaning. --data-root is the documented one: state, models
    # and the other mutable trees all sit under it. --data-dir/--models-dir stay
    # supported for deployments installed before the split, and still win when
    # given explicitly, because that is what their systemd unit passes.
    env_root = os.environ.get("CV84X6_DATA_ROOT")
    requested_root = Path(data_root or env_root) if (data_root or env_root) else None
    if requested_root is not None:
        root = ensure_layout(requested_root)
        data_dir = Path(data_dir or root / "state")
        models_dir = Path(models_dir or root / "models")
    else:
        data_dir = Path(data_dir or os.environ.get("CV84X6_DATA", BASE / "data"))
        models_dir = Path(models_dir or os.environ.get("CV84X6_MODELS", BASE / "models"))
        # A legacy install knows nothing about a data root; the state directory's
        # parent is the closest thing to one, and moving data from there is a
        # supported (if unusual) thing to do from the console.
        root = data_dir.parent
    web_dir = Path(web_dir or os.environ.get("CV84X6_WEB", BASE / "web" / "dist"))
    data_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("CV84X6 LLM service %s starting", __version__)
        from .core import monitor
        monitor.prime()
        # Hold the multimedia reserve before any worker can be spawned, adopted
        # or autostarted: it works by occupying VPP, so a worker that allocates
        # first can take the space it was meant to leave (docs/device-memory.md
        # §4). Failure is logged, not fatal -- the service still runs, and the
        # stats payload says `acquired: false` with a reason.
        try:
            app.state.vpp_reserve.acquire()
        except Exception:  # pragma: no cover - never block startup on the reserve
            logger.exception("taking the VPP multimedia reserve failed")
        # Recorded so a job running in a worker thread can hand async work back
        # (the knowledge-base parser does this to reach the OCR worker client).
        app.state.event_loop = asyncio.get_running_loop()
        # Before anything can be queued: a document left mid-flight by the last
        # run is marked failed (with a Retry available) rather than reading as
        # "still indexing" forever.
        try:
            app.state.kb_ingestor.recover()
        except Exception:  # pragma: no cover - one bad library must not stop boot
            logger.exception("knowledge-base recovery failed")
        # Take over what a previous run left running BEFORE anything can start a
        # copy of it. Both managers keep their processes in memory only, so a
        # restart otherwise sees "nothing running" while a worker still holds the
        # NPU heap and an agent still holds its port -- and the next load or
        # autostart spawns a second one. Recovery is read-only against the board
        # (see app/core/procs.py): a process that cannot be proven to be ours is
        # left alone and reported.
        try:
            adopted_models = await app.state.models.adopt()
        except Exception:  # pragma: no cover - recovery must never block startup
            logger.exception("model process takeover failed; starting with nothing loaded")
            adopted_models = []
        if adopted_models:
            logger.info("took over %d running model worker(s): %s", len(adopted_models),
                        ", ".join(m.model_id for m in adopted_models))
        try:
            adopted_agents = await app.state.agents.adopt()
        except Exception:  # pragma: no cover
            logger.exception("agent process takeover failed")
            adopted_agents = []
        if adopted_agents:
            logger.info("took over %d running agent(s): %s", len(adopted_agents),
                        ", ".join(a["id"] for a in adopted_agents))
        # Agents after the manager exists and before the first request: an
        # autostart agent takes ~10 s to become healthy, which is fine at boot
        # and not fine inside a request. An agent already adopted above is
        # already up, so autostart leaves it alone.
        app.state.agents.autostart_task = asyncio.create_task(app.state.agents.autostart())
        # The idle sweep, after adoption so a worker inherited from a previous run
        # gets an idle clock too. Started here, stopped inside ``unload_all`` --
        # one owner for its lifetime, on the same shutdown path that reaps the
        # workers it would otherwise try to reap.
        app.state.models.start_idle_sweeper()
        yield
        # Agents first: they are clients of this service, so stopping them
        # before the models keeps their shutdown from seeing a dead provider.
        await app.state.agents.shutdown()
        # Reap every worker so no orphan keeps the NPU heap allocated.
        await app.state.downloads.shutdown()
        for client in list(app.state.clients.values()):
            await client.close()
        app.state.clients.clear()
        await app.state.models.unload_all()
        # After every worker is gone, so nothing can race the free and re-take
        # the VPP the reserve was protecting.
        app.state.vpp_reserve.release()
        # Last: any request that finished during the shutdown above still got its
        # record written before the file is closed.
        app.state.inference_log.close()
        # Both hold a file under the data directory; a restart reopens them.
        logmod.detach_platform_log()
        app.state.audit.close()
        logger.info("shut down")

    app = FastAPI(
        title="CV84X6 LLM Service", version=__version__,
        lifespan=lifespan,
        # The interactive documents are ours, not FastAPI's: they are served
        # from assets committed to this repository (app/static/docs/), because
        # the board is offline and Swagger UI's default page loads its JavaScript
        # and CSS from a CDN (MYS-2676). Both are behind the admin gate; see
        # _mount_admin_docs below.
        docs_url=None, redoc_url=None, openapi_url=None,
        description=(
            "离线 LLM 推理服务。两套接口：\n\n"
            "* `/v1/*` —— OpenAI 兼容的推理接口，用 `Authorization: Bearer <inference key>`。"
            "OpenAPI 见 `/v1/openapi.json`（本页的 `/api/openapi.json` 不含它，理由见 "
            "`docs/admin-api.md`）。\n"
            "* `/api/*` —— 管理接口，用控制台会话 cookie **或** "
            "`Authorization: Bearer <admin key>`。所有错误统一为 "
            "`{\"detail\": \"<中文说明>\", \"code\": \"<稳定错误码>\"}`。"
        ),
    )
    app.state.store = StateStore(data_dir / "state.json")
    # The inference audit log lives beside state.json so a data-directory move
    # carries it along with everything else. Created after the store because its
    # enabled flag and retention come from the settings the store just loaded.
    _initial = app.state.store.settings
    app.state.inference_log = InferenceLogStore(
        data_dir / INFERENCE_LOG_FILE,
        retention_count=_initial.inference_log_retention_count,
        retention_days=_initial.inference_log_retention_days,
        enabled=_initial.inference_logging_enabled,
        # A move parks the log (see stop_everything). It is normally reopened by
        # rebind, but a move that fails before the switch never reaches it, and
        # the log must not stay silent for the rest of the process's life.
        resume_when=lambda: not app.state.storage.busy,
    )
    app.state.sessions = AdminSessions.load_or_create(data_dir / "session.key")
    app.state.clients = {}
    # The platform log file, beside the worker logs it sits next to in the
    # console. stderr keeps its handler: the journal is the operator's safety
    # net when this file cannot be written, and the two are not in competition.
    # `create_app` is called several times in one process by the tests, so the
    # handler is replaced rather than stacked -- one writer per file.
    app.state.platform_log_path = log_dir / logmod.PLATFORM_LOG_NAME
    app.state.platform_log = logmod.install_platform_log(app.state.platform_log_path)
    # The management audit trail, in its own SQLite file rather than a table in
    # the inference records': different retention, different readers, and a
    # corrupt trail must not take the inference history with it.
    _audit_settings = app.state.store.settings
    app.state.audit = AuditStore(
        data_dir / AUDIT_FILE,
        retention_days=_audit_settings.audit_retention_days,
    )
    # Every log the page may open. The three paths arrive as callables so a
    # data-directory move is followed without rebuilding the registry.
    app.state.logs = logmod.LogRegistry(
        platform_path=lambda: app.state.platform_log_path,
        worker_dir=lambda: app.state.models.log_dir,
        agents_root=lambda: Path(app.state.agents.root),
        agent_specs=lambda: app.state.agents.specs.values(),
    )
    app.state.log_sizes = logmod.SourceCache()
    # The knowledge-base demo's storage and its serial ingestion queue. Both live
    # under the data root so a data-directory move carries them along --
    # ``apps`` is one of storage.PARTS, which is what puts it in the copy list.
    app.state.kb_store = KbStore(root / "apps" / "kb")
    app.state.kb_ingestor = Ingestor(app.state.kb_store)
    # BM25 indexes, keyed by library, invalidated whenever its chunk set changes.
    app.state.kb_bm25 = {}
    # Taken in `lifespan` (before any worker can exist) and released after the
    # last one is gone. Constructed here so `/api/stats` can report its state
    # even on a host where the block can never be taken.
    app.state.vpp_reserve = VppReservation()
    # The simulated backend has no device, so the device-memory and TPU-usage
    # fields would be permanently empty -- and the console's new cards could not
    # be built or tested off the board. Turning the simulation on here (not in
    # the module) keeps `monitor` purely a set of probes unless something asks
    # for the fake.
    _monitor.enable_mock(backend_kind == "mock")
    app.state.models = ModelManager(
        models_dir,
        backend_kind=backend_kind,
        # Only the command line sets a count limit (0 = none). The persisted
        # setting was never editable and only ever held the old default of 2.
        max_loaded=max_loaded,
        max_concurrent_per_model=app.state.store.settings.max_concurrent_per_model,
        log_dir=log_dir,
        context_length_override=context_length_override,
        decode_delay_ms=decode_delay_ms,
        native_lib=native_lib,
        # The root a second instance would have to share to be a rival for these
        # workers (see ModelManager.adopt). None for a legacy --data-dir install,
        # which has no root to compare.
        data_root=root if requested_root is not None else None,
    )
    st = app.state.store.settings
    app.state.models.cache_entries = st.prefix_cache_entries
    app.state.models.cache_ttl_min = st.prefix_cache_ttl_min
    app.state.models.max_queue = st.max_queue
    app.state.models.exact_tail = st.prefill_exact_tail
    app.state.models.aux_idle_unload_min = st.aux_idle_unload_min
    app.state.models.aux_auto_load = st.aux_auto_load
    #: Per-model overrides (MYS-2675). A callable rather than a copy so a
    #: ``PUT /api/models/{id}/settings`` is live on the next request without any
    #: synchronisation step -- the store is the single source of truth, and two
    #: copies is how an idle sweep and a save end up disagreeing.
    app.state.models.model_settings = app.state.store.get_model_settings
    #: The derived default memory limit budgets one session per concurrent slot.
    app.state.models.max_concurrent_for_limits = st.max_concurrent_per_model
    # The load publishes `loaded` the instant the worker is usable; the client
    # must exist by then or a request that arrives in that window gets a 500.
    app.state.models.on_loaded = _register_client(app)
    app.state.models.on_unloading = _drop_client(app)
    app.state.models.refresh()
    app.state.downloads = DownloadManager(models_dir, root / "downloads" / "models")
    # Read through app.state on every call: a storage move swaps the download
    # manager, and the hook must follow it.
    app.state.models.is_downloading = (
        lambda model_id: model_id in app.state.downloads.active_names())
    # The idle sweep's second question after "long enough idle": is the worker
    # actually serving something? Read through the RPC client each time, because
    # a client is replaced by every load and the answer is the *live* worker's.
    # ``None`` when there is no client to ask -- the manager treats that as busy.
    async def _inflight(model_id: str) -> int | None:
        client = app.state.clients.get(model_id)
        if client is None:
            return None
        stats = await client.stats()
        if not isinstance(stats, dict):
            return None
        value = stats.get("inflight")
        if value is None:
            return None
        # The API side's count covers a call already sent but not yet admitted
        # by the worker (its ``inflight`` is still 0 then).
        return max(int(getattr(client, "active", 0) or 0), int(value))

    app.state.models.worker_inflight = _inflight

    async def _stats(model_id: str) -> dict | None:
        """The worker's own ``stats`` reply, for the post-timeout reconciliation.

        Same seam and same reason as ``_inflight``: the manager owns the state
        machine but not the socket, and ``resolve_budget_after_unknown`` needs the
        worker's own view of its budget to decide whether a ``configure`` whose
        reply was lost actually took effect.
        """
        client = app.state.clients.get(model_id)
        if client is None:
            return None
        reply = await client.stats()
        return reply if isinstance(reply, dict) else None

    app.state.models.worker_stats = _stats
    # An update renames the bmodel in models/<id>/, so the manager's file list
    # for it is stale the moment the swap lands. Re-scan on install rather than
    # waiting for the next console poll: a load in that window would name a file
    # that has just been deleted.
    app.state.downloads.on_installed = lambda _model_id: app.state.models.refresh()

    app.state.agents = AgentManager(
        root,
        key_store=app.state.store,
        models=app.state.models,
        service_port=service_port,
        specs=agent_specs,
        public_origins=[public_origin] if public_origin else None,
    )
    # The proxy builds the upstream Origin from this rather than from the
    # request, so it must be the port the service really listens on.
    app.state.service_port = service_port

    def rebind(new_root: Path) -> None:
        """Point the live service at another data root after a move.

        The store and the session key are re-read from the new location (the
        copy carries the same content, so keys and the operator's cookie keep
        working), and the model manager is pointed at the new models tree in
        place -- it holds object identity across loads, and every worker has
        already been unloaded by the time this runs.
        """
        state_dir = Path(new_root) / "state"
        app.state.store = StateStore(state_dir / "state.json")
        app.state.sessions = AdminSessions.load_or_create(state_dir / "session.key")
        # The platform log moves with the data: the handler is re-installed on
        # the copy that just landed. `stop_everything` closed the old one before
        # the copy, so nothing is writing under the tree about to be deleted --
        # and without this the platform log would stay silent for the rest of the
        # process's life, which is the same failure `rebind` below prevents for
        # the inference records.
        app.state.platform_log_path = state_dir / "logs" / logmod.PLATFORM_LOG_NAME
        app.state.platform_log = logmod.rebind_platform_log(
            Path(new_root), app.state.platform_log_path)
        # The audit trail follows the data like the inference records do.
        audit = app.state.audit
        audit.rebind(state_dir / AUDIT_FILE)
        audit.configure(retention_days=app.state.store.settings.audit_retention_days)
        # Which log a source id points at just changed under it; the cached
        # sizes and mtimes describe files that no longer exist.
        app.state.log_sizes.clear()
        # The record log follows the data: repoint the live store at the copy
        # that just landed under the new root, and re-apply the settings the
        # store reloaded (the copy carries them, but a rebind must not leave the
        # log configured from the tree that is about to be deleted).
        log = app.state.inference_log
        log.rebind(state_dir / INFERENCE_LOG_FILE)
        log.configure(
            enabled=app.state.store.settings.inference_logging_enabled,
            retention_count=app.state.store.settings.inference_log_retention_count,
            retention_days=app.state.store.settings.inference_log_retention_days,
        )
        mgr = app.state.models
        mgr.models_root = Path(new_root) / "models"
        mgr.log_dir = state_dir / "logs"
        mgr.log_dir.mkdir(parents=True, exist_ok=True)
        mgr.models_root.mkdir(parents=True, exist_ok=True)
        st = app.state.store.settings
        mgr.max_concurrent_per_model = st.max_concurrent_per_model
        # The store object was just replaced, so the per-model settings hook has
        # to be repointed at the new one -- a closure over the old store would
        # keep answering from the tree that is about to be deleted (MYS-2675).
        mgr.model_settings = app.state.store.get_model_settings
        mgr.max_concurrent_for_limits = st.max_concurrent_per_model
        mgr.cache_entries = st.prefix_cache_entries
        mgr.cache_ttl_min = st.prefix_cache_ttl_min
        mgr.max_queue = st.max_queue
        mgr.exact_tail = st.prefill_exact_tail
        mgr.refresh()
        app.state.downloads = DownloadManager(
            mgr.models_root, Path(new_root) / "downloads" / "models")
        # Agents move with the data root, but their live processes hold open
        # files under the old one: repoint the manager, and let the move's
        # pre-stop hook below have already stopped them.
        agents = app.state.agents
        agents.data_root = Path(new_root)
        agents.root = Path(new_root) / "agents"
        agents.downloads = Path(new_root) / "downloads"
        agents.state_path = agents.root / STATE_FILE
        agents.root.mkdir(parents=True, exist_ok=True)
        agents.downloads.mkdir(parents=True, exist_ok=True)
        agents.save_state()
        # The demo apps' data moves with the root. The ingestor holds a store
        # object rather than a path, so it is repointed here -- and its in-memory
        # BM25 indexes are dropped, since they were built from chunk files that
        # are now somewhere else.
        app.state.kb_store = KbStore(Path(new_root) / "apps" / "kb")
        app.state.kb_ingestor.store = app.state.kb_store
        app.state.kb_bm25.clear()
        # `stop_everything` cancelled the queue worker before the copy, and
        # nothing would start it again: every document uploaded after the move
        # would sit in `queued` forever, and one that was mid-parse at the time
        # would read as "still processing" with no worker behind it. Restart the
        # worker and mark the interrupted records failed, exactly as a bot
        # restart does -- which is the same event from the operator's side.
        try:
            app.state.kb_ingestor.recover()
            app.state.kb_ingestor.start()
        except Exception:  # pragma: no cover - a move must not fail on this
            logger.exception("restarting the knowledge-base queue after the move failed")

    async def stop_everything() -> None:
        """Stop everything that writes under the old root before files move.

        A worker keeps its .bmodel file and its log fd open, and a download is
        streaming into models/ -- copying those bytes is harmless, but deleting
        the old tree underneath a live writer is not.
        """
        # The knowledge-base queue first: a document being indexed is writing
        # chunks and vectors under apps/, which is one of the trees about to be
        # copied. Whatever it was in the middle of is `failed` on the next start
        # (Ingestor.recover), which is the same outcome a restart has.
        await app.state.kb_ingestor.stop()
        await app.state.downloads.shutdown()
        await app.state.agents.shutdown()
        # Close the record log before anything else, so the copy starts with no
        # writer on it: a record that landed in the middle of the copy would go
        # into a database that the verification then finds "different" from the
        # source, and one that landed afterwards would be filed under a tree
        # that is about to be deleted. Nothing below writes a record; a request
        # that finishes during the move loses its row, which is the lesser evil
        # and is what the console reports as "记录库正在随数据目录迁移".
        app.state.inference_log.close()
        # Same reason as the records: the platform log's handler holds an fd
        # under the tree about to be copied and deleted, and the audit database
        # is a second writer under `state/`. Closing both here means the copy is
        # of files nobody is appending to; `rebind` puts them back on the new
        # root.
        logmod.detach_platform_log()
        app.state.audit.close()
        for mid, client in list(app.state.clients.items()):
            try:
                await client.close()
            except Exception:  # pragma: no cover - shutting down anyway
                logger.warning("closing the client for %s failed", mid)
        app.state.clients.clear()
        await app.state.models.unload_all()

    app.state.storage = StorageManager(
        root,
        state_dir=data_dir,
        models_dir=models_dir,
        env_file=env_file if env_file is not None else DEFAULT_ENV_FILE,
        install_dir=install_dir if install_dir is not None else BASE,
        # A legacy layout's root is the install prefix itself; deleting it would
        # take the program with it, so only a root this service owns is removed.
        allow_delete_old=requested_root is not None,
        pre_stop=stop_everything,
        post_switch=rebind,
    )

    # Local-host tooling (and the console itself) is same-origin, but AI agents
    # and SDKs often run from a different port; allow them without credentials
    # so CORS does not become a debugging trap.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(BodyLimit)

    # The management audit trail. Outermost of the two custom layers so it sees
    # the status BodyLimit produced as well (a refused 48 MiB upload is a
    # management event too). `add_middleware` prepends, so the last one added is
    # the outermost: audit is added after BodyLimit, therefore wraps it.
    app.add_middleware(
        AuditMiddleware, store_getter=lambda: app.state.audit)

    app.include_router(openai_api.router, prefix="/v1", tags=["openai"])
    # POST /rerank without the version prefix: Cohere/Jina clients call it
    # that way, and some RAG frameworks strip /v1 from a configured base URL.
    app.include_router(openai_api.alias_router, tags=["openai"])
    app.include_router(admin_api.router, prefix="/api")
    # The log page and the audit trail. Its own file rather than more routes in
    # admin_api: it touches two storage subsystems (files and a second database)
    # and nothing else in the management surface should have to know about them.
    app.include_router(logs_api.router, prefix="/api")
    app.include_router(agents_api.router, prefix="/api")
    # The demo apps' own APIs. Their paths carry the /api prefix themselves
    # (``/api/apps/kb``), so the mount is at the root and the record's `source`
    # is the path a client actually called.
    app.include_router(apps_api.router, prefix=apps_api.PREFIX)
    # The console's streaming ASR demo. Its own router rather than a route in
    # admin_api, so the upload-shaped SSE endpoint and its record keeping stay in
    # one file that nothing else touches.
    app.include_router(asr_stream_api.router, prefix="/api/apps")
    # The MCP endpoint the three built-in agents are preconfigured against. Its
    # own path (``/mcp``, no version prefix) is the one the protocol names, and
    # the router carries it itself because the same file also documents why GET
    # is 405. Registered before the SPA catch-all, which would otherwise answer
    # ``POST /mcp`` with an HTML page.
    app.include_router(mcp_api.router, tags=["mcp"])
    # No /api prefix: these paths are the agents' own UIs, and their own configs
    # name this prefix (OpenClaw's controlUi.basePath). Mounted before the SPA
    # fallback below, which would otherwise serve index.html for them.
    app.include_router(agent_proxy.router, tags=["agent-proxy"])

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "version": __version__, "loaded": app.state.models.loaded_count}

    # The interactive documents first: they are routes too, and they are
    # deliberately absent from their own schema (include_in_schema=False), which
    # is what tells the doc check below to skip them.
    _mount_admin_docs(app)
    # Every /api route's tag, summary, models and error codes, attached after all
    # the routers are in (see app/api/docs.py). Raises at startup if the table and
    # the routes disagree, which is what keeps the document from going stale.
    api_docmeta.apply(app)

    install_error_handlers(app)

    _mount_web(app, web_dir)
    return app


#: A content-security policy for the two document pages, narrow on purpose:
#: scripts and styles only from this origin (the bundles are ours), no frames, no
#: forms. It is the machine-checkable half of "offline": ReDoc's bundle paints a
#: Redocly logo from ``cdn.redoc.ly`` when it can load one, and this policy is
#: what stops that image from being fetched at all on a board with no network
#: (``tools/check_admin_docs_offline.py`` proves it does not even try).
_DOCS_CSP = {
    "Content-Security-Policy":
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

#: Where the offline interactive-document assets live. Committed on purpose: the
#: board has no network, and Swagger UI's stock page fetches its bundle and
#: stylesheet from a CDN. See app/static/docs/README.md for versions and licences.
DOCS_ASSETS = BASE / "app" / "static" / "docs"

#: The Swagger UI page. Everything it needs is a sibling asset, and the OpenAPI
#: document is behind the same admin gate as the page -- a script may pass an
#: `admin` bearer key and read the JSON directly.
_SWAGGER_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CV84X6 管理 API 文档</title>
<link rel="stylesheet" href="/api/docs/swagger-ui.css">
<style>
  /* The board's console is dark by default; a page that flashes white is a page
     an operator working at night notices. Only the chrome is restyled -- the
     operations' own typography is Swagger UI's. */
  body { margin: 0; background: #0f1419; }
  .topbar { display: none; }
  #swagger-ui .info .title, #swagger-ui .info p, #swagger-ui .info li,
  #swagger-ui .opblock-tag, #swagger-ui .model-title, #swagger-ui h4,
  #swagger-ui h5, #swagger-ui label, #swagger-ui .tab li { color: #e6edf3; }
  #swagger-ui .scheme-container, #swagger-ui .opblock-tag-section,
  #swagger-ui .opblock .opblock-summary, #swagger-ui .models {
    background: #161b22; color: #e6edf3;
  }
  #swagger-ui .opblock { border-color: #30363d; }
  #swagger-ui .opblock .opblock-summary-description { color: #9da7b3; }
  #swagger-nav { padding: 12px 20px; font: 13px/1.6 -apple-system, "Segoe UI", sans-serif;
                 color: #9da7b3; }
  #swagger-nav a { color: #58a6ff; text-decoration: none; }
</style>
</head>
<body>
<div id="swagger-nav">
  <strong style="color:#e6edf3">CV84X6 管理 API</strong> ·
  <a href="/api/redoc">ReDoc 版（适合通读）</a> ·
  <a href="/api/openapi.json">OpenAPI JSON</a> ·
  <a href="/v1/openapi.json">/v1 推理接口的 OpenAPI</a> ·
  离线可用，不依赖任何 CDN
</div>
<div id="swagger-ui"></div>
<script src="/api/docs/swagger-ui-bundle.js"></script>
<script src="/api/docs/swagger-ui-standalone-preset.js"></script>
<script>
window.ui = SwaggerUIBundle({
  url: '/api/openapi.json',
  dom_id: '#swagger-ui',
  deepLinking: true,
  // No "Authorize" dialog: this document describes /api only, whose credentials
  // are a console cookie or an admin key, and the bundle's OAuth flow would
  // offer a login form this service does not have. A caller sets the header
  // themselves (see docs/admin-api.md).
  presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
  plugins: [SwaggerUIBundle.plugins.DownloadUrl],
  layout: 'StandaloneLayout',
  docExpansion: 'list',
  defaultModelsExpandDepth: 1,
  tryItOutEnabled: false,
});
</script>
</body>
</html>
"""

#: The ReDoc page. ReDoc renders the same document as one continuous page with a
#: navigation rail, which is what a reader who wants to *understand* the API
#: wants; Swagger is for looking one operation up.
#:
#: The palette is set explicitly rather than left to ReDoc's default: this
#: service's console is dark, an operator reading the documents at night gets a
#: white flash otherwise, and -- the practical half -- ReDoc's light default puts
#: its section text in a colour that reads as washed out on a dark host page. The
#: theme object below is ReDoc's documented API for exactly this.
_REDOC_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CV84X6 管理 API 文档（ReDoc）</title>
<style>
  body { margin: 0; padding: 0; background: #0f1419; }
  #nav { padding: 12px 20px; font: 13px/1.6 -apple-system, "Segoe UI", sans-serif;
         color: #9da7b3; background: #161b22; border-bottom: 1px solid #30363d; }
  #nav a { color: #58a6ff; text-decoration: none; }
</style>
</head>
<body>
<div id="nav">
  <strong style="color:#e6edf3">CV84X6 管理 API</strong> ·
  <a href="/api/docs">Swagger 版（适合查单个接口）</a> ·
  <a href="/api/openapi.json">OpenAPI JSON</a> ·
  <a href="/v1/openapi.json">/v1 推理接口的 OpenAPI</a>
</div>
<redoc spec-url="/api/openapi.json" hide-download-button></redoc>
<script>
// ReDoc reads its theme from the `theme` attribute of the <redoc> element, and
// only once, at upgrade time -- so it is set before the bundle loads rather than
// in the markup, where a JSON-with-quotes attribute is easy to break.
document.querySelector('redoc').setAttribute('theme', JSON.stringify({
  colors: {
    primary: { main: '#58a6ff' },
    success: { main: '#3fb950' },
    warning: { main: '#d29922' },
    error: { main: '#f85149' },
    text: { primary: '#e6edf3', secondary: '#9da7b3' },
    border: { dark: '#30363d', light: '#21262d' },
    http: { get: '#58a6ff', post: '#3fb950', put: '#d29922',
            delete: '#f85149', patch: '#a371f7' },
  },
  typography: {
    fontSize: '15px', lineHeight: '1.6',
    fontFamily: '-apple-system, "Segoe UI", "Noto Sans CJK SC", sans-serif',
    headings: { fontFamily: '-apple-system, "Segoe UI", "Noto Sans CJK SC", sans-serif',
                fontWeight: '600' },
    code: { fontSize: '13px', fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
            color: '#79c0ff', backgroundColor: 'rgba(110,118,129,0.25)' },
  },
  sidebar: { backgroundColor: '#161b22', textColor: '#9da7b3',
             activeTextColor: '#58a6ff', width: '260px' },
  rightPanel: { backgroundColor: '#161b22', textColor: '#e6edf3' },
  schema: { nestedBackground: '#161b22', linesColor: '#30363d',
            typeNameColor: '#a371f7', typeTitleColor: '#e6edf3',
            requireLabelColor: '#f85149' },
  codeBlock: { backgroundColor: '#0d1117', color: '#e6edf3' },
}));
</script>
<script src="/api/docs/redoc.standalone.js"></script>
</body>
</html>
"""


def _mount_admin_docs(app: FastAPI) -> None:
    """``/api/docs``, ``/api/redoc``, ``/api/openapi.json`` and ``/api/docs/*``.

    Four routes, all behind :func:`app.core.auth.require_admin_docs` -- i.e. a
    console session or an ``admin`` API key. The assets themselves are gated too:
    a page that cannot be read without a session should not have its JavaScript
    served to an anonymous caller either, and the check is one function call.

    Registered as plain routes rather than FastAPI's built-in ``docs_url``: the
    built-in page hard-codes the CDN URLs, and it cannot be authenticated.

    **``/v1`` is documented separately** (``/v1/openapi.json``), not merged into
    this one. The two surfaces have different credentials (inference key vs
    admin), different error bodies (OpenAI's envelope vs ``{detail, code}``), and
    different audiences; one document with two tags would still need both
    explained on every operation and would put inference operations into a
    browser's "Authorize" flow that cannot express them. Reasons in full:
    ``docs/admin-api.md`` §「/v1 的文档」.
    """
    from fastapi import Depends

    gate = [Depends(require_admin_docs)]

    @app.get("/api/openapi.json", include_in_schema=False, dependencies=gate)
    async def admin_openapi():
        """The management half of the document.

        Filtered to ``/api/`` for the same reason ``/v1`` gets its own file: the
        page it feeds is titled "管理 API", and a reader looking up a management
        operation should not have to scroll past the inference routes and the
        agent proxy's catch-all to find it. The schemas (``components``) are kept
        whole, so a shared model is not redefined.
        """
        spec = app.openapi()
        keep = {p: item for p, item in spec["paths"].items() if p.startswith("/api/")}
        return JSONResponse({**spec, "paths": keep})

    @app.get("/v1/openapi.json", include_in_schema=False, dependencies=gate)
    async def inference_openapi():
        """The ``/v1`` half, as its own document.

        Built from the same app (so the two cannot describe different schemas)
        and then filtered to the versioned paths. ``POST /rerank``'s unversioned
        alias is not here because it is not in any document (it exists for
        clients that strip the version prefix, and is described in
        ``docs/admin-api.md`` instead).

        Auth is the admin gate rather than an API key: a browser opens this page
        to read it, and an inference key is exactly the credential this service
        hands to agents -- one of which should not be able to enumerate the
        surface.
        """
        spec = app.openapi()
        keep = {p: item for p, item in spec["paths"].items() if p.startswith("/v1/")}
        spec = {**spec, "paths": keep,
                "info": {**spec["info"], "title": "CV84X6 LLM Service — /v1 推理接口",
                         "description": "OpenAI 兼容接口。用 `Authorization: Bearer "
                                        "<inference key>` 调用；错误体遵循 OpenAI 的形状。"
                                        "另有一个不带版本前缀的 `POST /rerank` 别名，"
                                        "供会剥掉 `/v1` 的客户端使用，行为与本文件里的 "
                                        "`POST /v1/rerank` 完全相同。"}}
        spec.pop("tags", None)
        return JSONResponse(spec)

    @app.get("/api/docs", include_in_schema=False, dependencies=gate,
             response_class=HTMLResponse)
    async def swagger_ui():
        return HTMLResponse(_SWAGGER_HTML, headers=_DOCS_CSP)

    @app.get("/api/redoc", include_in_schema=False, dependencies=gate,
             response_class=HTMLResponse)
    async def redoc_ui():
        return HTMLResponse(_REDOC_HTML, headers=_DOCS_CSP)

    @app.get("/api/docs/{asset}", include_in_schema=False, dependencies=gate)
    async def docs_asset(asset: str):
        # A whitelist of the three committed files, rather than a StaticFiles
        # mount: no path traversal to reason about, no directory listing, and an
        # unknown name is a plain 404.
        allowed = {"swagger-ui.css": "text/css; charset=utf-8",
                   "swagger-ui-bundle.js": "application/javascript; charset=utf-8",
                   "swagger-ui-standalone-preset.js":
                       "application/javascript; charset=utf-8",
                   "redoc.standalone.js": "application/javascript; charset=utf-8"}
        media_type = allowed.get(asset)
        path = DOCS_ASSETS / asset if media_type else None
        if path is None or not path.is_file():
            # The `code` is spelled out rather than left to the exception handler:
            # this route returns a response instead of raising, and the contract
            # says every /api error body carries one.
            return JSONResponse(status_code=404,
                                content={"detail": "文档资源不存在", "code": "not_found"})
        return FileResponse(path, media_type=media_type,
                            headers={"Cache-Control": "public, max-age=86400"})


def _mount_web(app: FastAPI, web_dir: Path) -> None:
    """Serve the built SPA, with history fallback for client-side routes."""
    index = web_dir / "index.html"
    if (web_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=web_dir / "assets"), name="assets")

    @app.get("/")
    async def root():
        if index.exists():
            return FileResponse(index)
        return JSONResponse({
            "service": "cv84x6-llm",
            "version": __version__,
            "note": "web console is not built yet; run scripts/build_web.sh",
        })

    @app.get("/{path:path}")
    async def spa(path: str):
        # Never shadow the API namespaces.
        if path.startswith(("api/", "v1/")):
            return JSONResponse(status_code=404, content={"detail": "not found"})
        candidate = web_dir / path
        if candidate.is_file():
            return FileResponse(candidate)
        if index.exists():
            return FileResponse(index)
        return JSONResponse(status_code=404, content={"detail": "not found"})


def _ws_impl() -> str | None:
    """The WebSocket library uvicorn should use, or None when there is none.

    The agent proxy is the reason this matters: an agent's Control UI is a live
    WebSocket client, and without an implementation uvicorn answers the upgrade
    with a 404 and the embedded page loads but never connects. Returning None
    keeps the service startable on a host that only serves the HTTP API.
    """
    for name in ("websockets", "wsproto"):
        try:
            __import__(name)
            return name
        except ImportError:
            continue
    logger.warning(
        "no WebSocket implementation installed: the agent proxy UI will not work. "
        "Install websockets (it is in requirements-vendor.txt) and restart."
    )
    return None


def _default_lib() -> str:
    """The release ships lib/; a source checkout builds into native/build/."""
    for cand in (BASE / "lib" / "libcv84x6_llm.so",
                 BASE / "native" / "build" / "libcv84x6_llm.so"):
        if cand.exists():
            return str(cand)
    return str(BASE / "lib" / "libcv84x6_llm.so")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--backend", default=os.environ.get("CV84X6_BACKEND", "mock"),
                   choices=["mock", "sail", "native"])
    p.add_argument("--data-dir", default=None)
    p.add_argument("--models-dir", default=None)
    p.add_argument("--data-root", default=os.environ.get("CV84X6_DATA_ROOT") or None,
                   help="everything mutable lives here: state/, models/, agents/, "
                        "downloads/. Equivalent to --data-dir DIR/state "
                        "--models-dir DIR/models; an explicit --data-dir/--models-dir "
                        "still wins.")
    p.add_argument("--env-file", default=os.environ.get("CV84X6_ENV_FILE") or None,
                   help="KEY=VALUE config read by systemd; a data-directory move "
                        "rewrites CV84X6_DATA_DIR in it. Default etc/server.env.")
    p.add_argument("--install-dir", default=None,
                   help="the program tree; a data directory may never be moved "
                        "into it. Default: the directory above app/.")
    p.add_argument("--max-loaded", type=int,
                   default=int(os.environ.get("CV84X6_MAX_LOADED") or 0),
                   help="at most this many chat models loaded at once; 0 = no limit "
                        "(default; CV84X6_MAX_LOADED in server.env)")
    p.add_argument("--context-length", type=int, default=None,
                   help="mock backend only")
    p.add_argument("--native-lib", default=os.environ.get("CV84X6_LLM_LIB") or _default_lib(),
        help="path to libcv84x6_llm.so (native backend)")
    p.add_argument("--public-origin", default=os.environ.get("CV84X6_PUBLIC_ORIGIN") or None,
        help="the origin operators reach this console on (e.g. "
             "http://172.26.166.96:18080). Passed to agents whose config names "
             "browser origins, so a direct visit to their own port works too; "
             "the /agents/<id>/ proxy does not need it.")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    import uvicorn

    app = create_app(
        data_dir=args.data_dir,
        models_dir=args.models_dir,
        backend_kind=args.backend,
        max_loaded=args.max_loaded,
        context_length_override=args.context_length,
        native_lib=args.native_lib,
        data_root=Path(args.data_root) if args.data_root else None,
        env_file=Path(args.env_file) if args.env_file else None,
        install_dir=Path(args.install_dir) if args.install_dir else None,
        service_port=args.port,
        public_origin=args.public_origin,
    )
    # Bounded graceful shutdown: an in-flight request (a long prefill can run
    # for an hour) must not keep a stop/restart waiting; the lifespan shutdown
    # that follows still stops each worker in order.
    uvicorn.run(app, host=args.host, port=args.port, log_level="debug" if args.debug else "info",
                timeout_graceful_shutdown=15,
                # The agent proxy forwards WebSockets; uvicorn only speaks them
                # when an implementation is importable, and pinning it here means
                # a board that has both websockets and wsproto does not silently
                # pick a different one than the one we vendor and test.
                ws=_ws_impl())
    return 0


if __name__ == "__main__":
    sys.exit(main())
