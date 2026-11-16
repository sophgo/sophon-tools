"""Management surface behind the admin cookie: models, keys, stats, logs."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..core import monitor
from ..core.auth import COOKIE_NAME, SESSION_TTL, require_admin
from ..core.client import WorkerClient, WorkerError, WorkerTransportError
from ..core.downloader import orphan_free_space
from ..core.errors import api_error
from ..core.models import (DeviceBudgetUnverifiable, DeviceMemoryError,
                           ModelBusy, ModelConflict)
from ..core.state import AUX_IDLE_UNLOAD_MAX_MIN, MEM_LIMIT_MB_MAX, MEM_LIMIT_MB_MIN
from ..schemas import ChatCompletionRequest, EmbeddingRequest, RerankRequest

logger = logging.getLogger(__name__)

router = APIRouter()


class LoginBody(BaseModel):
    password: str


class CreateKeyBody(BaseModel):
    name: str = ""
    #: ``inference`` (the default) drives /v1 only; ``admin`` may also drive every
    #: /api route with ``Authorization: Bearer <key>`` -- that is how a script
    #: manages this service without a browser session (MYS-2676). Kept as a plain
    #: ``str`` validated by the store: a ``Literal`` here would make an unknown
    #: scope a 422 from pydantic, while the console's own key page reads the
    #: refusal's ``detail`` and should get the message the store writes.
    scope: str = "inference"


class DownloadBody(BaseModel):
    url: str
    name: str
    kind: str = "url"          # "url" | "dfss"
    expected_bytes: int | None = None
    #: A model made of several bmodels (OCR) downloads as one job. Each entry
    #: is ``{"dfss", "md5", "size_bytes"}``; omitted means "just ``url``".
    files: list[dict] | None = None


class ChatBody(BaseModel):
    model: str
    prompt: str = ""
    max_tokens: int = 256
    temperature: float = 0.8
    images: list[str] = []          # raw base64, shown before the text
    enable_thinking: bool = False
    # Optional full conversation (OpenAI message shape, images as data URLs).
    # When given it replaces prompt/images, so the console can hold a
    # multi-turn chat -- which is also what lets it hit the prefix cache.
    messages: list[dict] | None = None


def _playground_messages(body: ChatBody) -> list:
    """The conversation this console request means, in OpenAI message terms.

    The console either sends a full ``messages`` list or a single prompt plus a
    list of already-encoded images; both are reduced to one message list so the
    prompt renderer and the audit record describe the same request.
    """
    from ..schemas import ChatMessage
    from .openai_api import IMAGE_PLACEHOLDER

    if body.messages:
        from pydantic import ValidationError

        try:
            return [ChatMessage(**m) for m in body.messages]
        except (ValidationError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"bad messages: {exc}") from exc
    text = IMAGE_PLACEHOLDER * len(body.images) + body.prompt
    return [ChatMessage(role="user", content=text)]


def _playground_request(body: ChatBody, ocr_vl: bool = False) -> tuple[str, list[str]]:
    """Render the console's request with the model's template: (prompt, images).

    ``ocr_vl`` picks PaddleOCR-VL's template instead of Qwen's. The two are not
    interchangeable: the OCR template is a different conversation format, and
    rendering it with Qwen's markers would produce a prompt the model never saw.
    """
    from .openai_api import _ocr_vl_prompt, build_prompt

    msgs = _playground_messages(body)
    if ocr_vl:
        prompt, images = _ocr_vl_prompt(msgs)
        return prompt, (list(body.images) if not body.messages else images)
    prompt, images = build_prompt(msgs, enable_thinking=body.enable_thinking)
    # The console's own image list lives outside the message text; the caller
    # hands it back so the record can order it with the message's own pictures.
    return prompt, (list(body.images) if not body.messages else images)


# -- session -------------------------------------------------------------
@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response):
    store = request.app.state.store
    if not store.verify_admin(body.password):
        # Constant-ish delay: a trivially fast reject is a brute-force oracle.
        await asyncio.sleep(0.4)
        raise HTTPException(status_code=401, detail="wrong password")
    token = request.app.state.sessions.issue()
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, samesite="lax", max_age=SESSION_TTL, path="/",
    )
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/session")
async def session(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    return {"authenticated": bool(token and request.app.state.sessions.verify(token))}


@router.post("/password")
async def change_password(request: Request, body: LoginBody, _=Depends(require_admin)):
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="password must be at least 6 characters")
    request.app.state.store.set_admin_password(body.password)
    return {"ok": True}


# -- resources / live stats ---------------------------------------------
@router.get("/stats")
async def stats(request: Request, _=Depends(require_admin)):
    app = request.app
    store = app.state.store
    mgr = app.state.models

    # On the simulated backend nothing allocates on the device, so without this
    # the console's device-memory card would sit at zero however many models are
    # loaded and no admission refusal would ever be reachable. The numbers stay
    # labelled `source: "mock"` (app/core/monitor.py).
    if mgr.backend_kind == "mock":
        monitor.set_mock_used(sum(m.size_bytes for m in mgr.list() if m.loaded))

    worker_stats = {}
    for info in mgr.list():
        # `operation` as well as `loaded`: during an unload the client is
        # already destroyed, and a stats poll that reached for it would either
        # recreate one behind the unload's back (see WorkerClient.close) or read
        # a socket that is on its way out. The console's own poll runs every few
        # seconds, so this window is hit in production, not just in tests.
        if not info.loaded or info.operation is not None:
            continue
        client: WorkerClient = app.state.clients.get(info.model_id)
        if client is None:
            continue
        try:
            worker_stats[info.model_id] = await asyncio.wait_for(client.stats(), timeout=3)
            got = worker_stats[info.model_id]
            if isinstance(got, dict):
                mgr.note_runtime_bytes(info.model_id, got.get("kv_used_bytes"))
        except Exception as exc:
            # A worker that cannot answer stats while its model still reads
            # ready is a reporting failure, not a reason to take it out of
            # service: the state machine's hard check is at initialisation.
            worker_stats[info.model_id] = {"error": str(exc)}

    return {
        "device": monitor.snapshot(),
        # The VPP block held for the multimedia stack. Not part of `snapshot()`
        # because it is the service's own doing, not a device reading -- but it
        # changes what `device.device_mem.free_bytes` means by ~256 MiB, so an
        # operator comparing our numbers with `bm-smi` needs to see it.
        "vpp_reserve": getattr(app.state, "vpp_reserve", None).status()
        if getattr(app.state, "vpp_reserve", None) is not None else None,
        "usage": {
            "prompt_tokens": store.usage.prompt_tokens,
            "completion_tokens": store.usage.completion_tokens,
            "cached_tokens": store.usage.cached_tokens,
            "requests": store.usage.requests,
            "tps_history": store.usage.tps_history[-120:],
            "cache_hit_rate": (
                store.usage.cached_tokens
                / (store.usage.cached_tokens + store.usage.prompt_tokens)
                if (store.usage.cached_tokens + store.usage.prompt_tokens) else 0.0
            ),
        },
        "models": [dict(_model_view(mgr, m), **_live_caps(m, worker_stats))
                   for m in mgr.list()],
        "max_loaded_models": mgr.max_loaded,
        # Where prefix-cache KV lives and how much is used. On this board NPU
        # memory is plentiful and system RAM is not, so this is what an operator
        # needs when deciding whether another model will fit.
        "kv_cache": {
            mid: (st.get("cache") or {})
            for mid, st in worker_stats.items()
            if isinstance(st, dict) and "cache" in st
        },
        "workers": worker_stats,
        "disk": mgr.disk_usage(),
    }


def _live_caps(info, worker_stats: dict) -> dict:
    """Overlay capabilities the worker reports at runtime.

    Whether sampling works depends on the bmodel's lm_head, which the worker
    only knows once the model is loaded. Reading it here (rather than caching it
    at load time) keeps the console honest even if the load-time probe raced the
    worker's readiness.
    """
    st = worker_stats.get(info.model_id)
    caps = {}
    if isinstance(st, dict):
        if "supports_sampling" in st:
            caps["supports_sampling"] = bool(st["supports_sampling"])
        # The idle sweep reads this too; showing it saves the operator from
        # guessing why a model past its deadline is still loaded.
        if "inflight" in st:
            caps["inflight"] = st["inflight"]
    return caps


def _model_view(mgr, info) -> dict:
    """``ModelInfo.public()`` with the per-model settings and memory filled in.

    Three groups of fields beyond the dataclass's own, and they answer three
    different questions the console's model card asks:

      * ``settings`` -- what the operator stored, verbatim, ``null`` included.
        A ``null`` is *not* the same as the effective value below it: null means
        "follow the default", and the console's switch should read "默认" rather
        than claiming the operator chose that number.
      * ``effective`` -- what is in force right now, so the card can render
        without re-implementing the fallback rules. ``idle_unload_min`` and
        ``auto_load`` are resolved; ``mem_limit_bytes`` is the limit in force.
      * ``mem_*_bytes`` -- the accounting behind the limit: the derived default,
        the static footprint, and (while loaded) what is actually in use.

    ``idle_unload_at`` needs the configured threshold and the model's kind, which
    the dataclass does not know, so it is computed here -- one helper rather than
    several call sites that could disagree. The console polls both
    ``/api/models`` and ``/api/stats``, and a countdown that differs between them
    is the kind of bug nobody reports and nobody can find.
    """
    stored = mgr.settings_for(info.model_id)
    view = info.public(idle_unload_at=mgr.idle_unload_at(info))
    view["settings"] = stored.to_json()
    view["effective"] = {
        "idle_unload_min": mgr.effective_idle_minutes(info),
        "auto_load": mgr.effective_auto_load(info),
        "mem_limit_bytes": mgr.mem_limit_bytes(info),
    }
    view["mem_limit_default_bytes"] = mgr.mem_limit_default_bytes(info)
    view["mem_static_bytes"] = mgr.static_bytes(info)
    # ``mem_used_bytes`` is the model's own live footprint, and only a loaded
    # model has one: reporting the static figure for an unloaded model would
    # read as "it is using memory" on the console's card.
    view["mem_used_bytes"] = (mgr.mem_used_bytes(info) if info.loaded else None)
    return view


# -- models --------------------------------------------------------------
def register_client(app, model_id: str, port: int | None) -> WorkerClient | None:
    """The console's RPC client for ``model_id``, reusing the live one.

    Called by ``ModelManager.on_loaded`` at the exact instant a worker becomes
    usable (see ``app.main``), and again by the load route for the idempotent
    "already loaded" path. Two browsers clicking "load" at the same moment must
    share one socket: a second client for the same port would orphan the first
    one's pump task on a worker nobody talks to.
    """
    if not port:
        return None
    existing: WorkerClient | None = app.state.clients.get(model_id)
    if existing is not None and getattr(existing, "port", None) == port:
        return existing
    if existing is not None:
        app.state.clients.pop(model_id, None)  # the worker it talked to is gone
    client = WorkerClient(port)
    app.state.clients[model_id] = client
    return client


async def forget_client(app, model_id: str) -> None:
    """Close and drop the RPC client for ``model_id``, if there is one.

    The console-side half of an unload, and it has to run *after* the manager
    published ``unloading`` and *before* the worker is signalled. Closing first
    is what makes an unload take ~0.6 s instead of hitting the worker's 120 s
    SIGTERM grace (the worker's shutdown waits for its connection handlers, and
    a handler parked on a read from this client never finishes) -- and a kill
    at that deadline is exactly what this project forbids for a live NPU
    process. Publishing the operation first is what keeps the socket from being
    closed under a request that still sees ``loaded: true``.
    """
    client: WorkerClient | None = app.state.clients.pop(model_id, None)
    if client is not None:
        await client.close()


@router.get("/models")
async def list_models(request: Request, _=Depends(require_admin)):
    app = request.app
    mgr = app.state.models
    mgr.refresh()
    # Overlay runtime capabilities for loaded models, so the console can hide
    # controls that would do nothing for this particular bmodel.
    out = []
    for m in mgr.list():
        caps = {}
        # Only a model that is settled and loaded can answer; during a load or
        # an unload its client is either absent or deliberately destroyed, and
        # this route is exactly what the console polls every 2 s while an
        # operation is in flight.
        if m.loaded and m.operation is None:
            client = app.state.clients.get(m.model_id)
            if client is not None:
                try:
                    st = await asyncio.wait_for(client.stats(), timeout=3)
                    if isinstance(st, dict):
                        if "supports_sampling" in st:
                            caps["supports_sampling"] = bool(st["supports_sampling"])
                        # The idle sweep's own input, shown as-is: an operator
                        # asking "why is it not being unloaded?" can read it.
                        if "inflight" in st:
                            caps["inflight"] = st["inflight"]
                        # What this model's sessions hold right now; the card's
                        # "占用" line and the load-time/limit comparison both
                        # read it (MYS-2675).
                        mgr.note_runtime_bytes(m.model_id, st.get("kv_used_bytes"))
                except Exception:
                    pass
        out.append(dict(_model_view(mgr, m), **caps))
    return {"models": out}


class ModelSettingsBody(BaseModel):
    """What ``PUT /api/models/{id}/settings`` accepts.

    Every field is optional **and nullable**, and the two mean different things,
    which is why they cannot share FastAPI's usual "absent leaves it alone":

      * absent -- leave this field alone (a console that sends only the switch
        the operator moved patches exactly that field);
      * ``null`` -- reset this field to its default (the global setting for the
        two idle switches, the derived figure for the memory limit).

    pydantic v2 distinguishes the two through ``model_fields_set``, which is what
    ``update_model_settings`` reads; a plain ``None`` default cannot tell them
    apart and would make resetting a field impossible.

    Bounds are **refused**, not clamped, unlike ``/api/settings``: there the
    value comes from a spinner and a stale number should not fail the save, but
    here a memory limit is the thing an operator uses to protect a board, and
    silently accepting 0 for "32 MiB" would defeat it. ``null`` is how you ask
    for the default; an out-of-range number is a mistake worth reporting.
    """

    idle_unload_min: int | None = None
    auto_load: bool | None = None
    mem_limit_mb: int | None = None


def _settings_view_for(mgr, info) -> dict:
    """The GET/PUT body for one model's settings (see ``_model_view``)."""
    return {
        "id": info.model_id,
        "kind": info.kind,
        "settings": mgr.settings_for(info.model_id).to_json(),
        "effective": {
            "idle_unload_min": mgr.effective_idle_minutes(info),
            "auto_load": mgr.effective_auto_load(info),
            "mem_limit_bytes": mgr.mem_limit_bytes(info),
        },
        "mem_limit_default_bytes": mgr.mem_limit_default_bytes(info),
        "mem_static_bytes": mgr.static_bytes(info),
        "mem_used_bytes": mgr.mem_used_bytes(info) if info.loaded else None,
        # The bounds this route enforces, published so a console field can use
        # them instead of restating them (the same rule ``/api/settings``
        # follows for ``aux_idle_unload_limit_min``).
        "limits": {
            "idle_unload_min_max": AUX_IDLE_UNLOAD_MAX_MIN,
            "mem_limit_mb_min": MEM_LIMIT_MB_MIN,
            "mem_limit_mb_max": MEM_LIMIT_MB_MAX,
        },
        # A 35B mapping 20 GB takes tens of seconds, and the console should say
        # so before an operator turns on-demand loading on for one.
        "auto_load_note": ("自动加载大模型需要几十秒；辅助模型通常几秒"),
    }


@router.get("/models/{model_id}/settings")
async def get_model_settings(model_id: str, request: Request, _=Depends(require_admin)):
    mgr = request.app.state.models
    mgr.refresh()
    info = mgr.get(model_id)
    if info is None:
        raise HTTPException(status_code=404, detail="model not found on disk")
    return _settings_view_for(mgr, info)


@router.put("/models/{model_id}/settings")
async def update_model_settings(model_id: str, body: ModelSettingsBody,
                                request: Request, _=Depends(require_admin)):
    """Change one model's overrides. Takes effect on the next request.

    Two refusals beyond the field bounds, and each protects a different thing:

    * a ``mem_limit_mb`` below what the model is **currently holding** is a 400
      naming both numbers. Accepting it would leave a model running over its own
      ceiling with no way to enforce it -- the alternative, unloading it, would
      make a settings save silently kill a live model, and the operator can do
      that deliberately with the unload button.
    * a model mid-load or mid-unload is a 409: the limit is read at spawn time,
      so a change during one would apply to neither the worker coming up nor the
      one going down, and the card would show a number nothing is enforcing.

    Everything else applies immediately: the idle sweep and the on-demand path
    read the effective values per request, so no worker restart is needed (and
    none happens -- a limit that only affects the runtime budget reaches a
    running worker through ``configure``).

    **A raise is admitted against the device, under the same ledger a load uses
    (MYS-2795).** It used to be pushed straight at the worker, which sized the
    budget from a device reading taken at *load* time -- so once anything else
    had loaded or freed memory, a raise could promise more than the card had and
    the NPU reserve was never consulted (the reviewer's repro: free 1024 MiB,
    reserve 1024 MiB, 400 -> 1000 MiB, HTTP 200, zero device reads).

    Two locks, always in this order:

      1. the model's **lifecycle** lock, so a load or unload cannot be happening
         at the same time -- a change during one would apply to neither the
         worker coming up nor the one going down (the pre-existing 409 above
         catches the published states; the lock also catches the instant before
         the operation is published);
      2. the **budget** lock, held only for "read the heap, check it, register
         the claim", never across the worker handshake.

    State and the old configuration are re-read *inside* the lifecycle lock: this
    request may have waited behind a load that changed both. The claim is then
    released on every exit -- refusal, worker rejection, timeout, cancellation --
    and handed over only once the new limit is persisted, so there is no instant
    in which the memory is promised by neither the ledger nor the stored setting.

    **A change whose outcome was lost is recoverable three ways (MYS-2801)**, and
    none of them is a restart. A ``configure`` that timed out, hit a dead socket
    or lost its reply leaves the memory reserved under a claim marked unresolved,
    which keeps it out of every later admission:

      * **retry the same save** -- this route settles against the worker's own
        budget first. Already applied: the setting is stored and the answer is 200
        with ``applied.settled_after_lost_reply``. Still on the old budget: 409,
        nothing changed. Unreadable: 503 and the claim stays;
      * **a different change** -- refused with 409 ``model_busy`` until the doubt
        is settled, because the admission arithmetic would be run against a
        device reading that does not describe the worker;
      * **unload the model** -- once the process is confirmed gone the claim is
        dropped with it (a surviving or failed unload keeps it: that worker is
        exactly what the claim is about).

    A cancelled request marks its claim unresolved synchronously and then settles
    it inline, inside this request's lifecycle lock -- there is no detached task
    writing settings after the lock is released.
    """
    app = request.app
    mgr = app.state.models
    store = app.state.store
    mgr.refresh()
    info = mgr.get(model_id)
    if info is None:
        raise HTTPException(status_code=404, detail="model not found on disk")
    # Checked **before** taking the lifecycle lock, which is what keeps this
    # request from waiting out a 60 s load only to be told no: the answer is
    # already known, and the console can act on it now. Re-checked inside the
    # lock, where the answer may have changed while waiting.
    if info.operation is not None:
        raise HTTPException(
            status_code=409,
            detail=f"模型 {model_id} 正在加载或卸载，请完成后再改设置")

    async with mgr.lock_for(model_id):
        # Re-read: this request may have queued behind a load or unload that
        # finished while it waited, and both the operation and the stored
        # settings may have moved. Everything below is decided from these.
        mgr.refresh()
        info = mgr.get(model_id)
        if info is None:
            raise HTTPException(status_code=404, detail="model not found on disk")
        if info.operation is not None:
            raise HTTPException(
                status_code=409,
                detail=f"模型 {model_id} 正在加载或卸载，请完成后再改设置")

        sent = body.model_fields_set
        entry = mgr.settings_for(model_id)

        for field in ("idle_unload_min", "auto_load", "mem_limit_mb"):
            if field not in sent:
                continue
            value = getattr(body, field)
            if field == "idle_unload_min" and value is not None:
                if isinstance(value, bool) or not 0 <= int(value) <= AUX_IDLE_UNLOAD_MAX_MIN:
                    raise HTTPException(
                        status_code=400,
                        detail=f"idle_unload_min 必须是 0-{AUX_IDLE_UNLOAD_MAX_MIN} "
                               f"之间的整数或 null（0 表示不自动卸载），收到 {value!r}")
                value = int(value)
            if field == "mem_limit_mb" and value is not None:
                if isinstance(value, bool) or not MEM_LIMIT_MB_MIN <= int(value) <= MEM_LIMIT_MB_MAX:
                    raise HTTPException(
                        status_code=400,
                        detail=f"mem_limit_mb 必须是 {MEM_LIMIT_MB_MIN}-{MEM_LIMIT_MB_MAX} "
                               f"之间的整数或 null（null 表示用推算的默认值），收到 {value!r}")
                value = int(value)
            setattr(entry, field, value)

        if body.mem_limit_mb is not None and "mem_limit_mb" in sent and info.loaded:
            used = mgr.mem_used_bytes(info)
            wanted = int(body.mem_limit_mb) * 1024 * 1024
            if wanted < used:
                raise HTTPException(
                    status_code=400,
                    detail=f"模型 {model_id} 当前占用 {used / 2**20:.0f} MiB"
                           f"（静态 {mgr.static_bytes(info) / 2**20:.0f} MiB + "
                           f"运行期 {int(info.runtime_bytes or 0) / 2**20:.0f} MiB），"
                           f"不能把上限改为更小的 {wanted / 2**20:.0f} MiB；"
                           "请先卸载该模型，或把上限设到不低于当前占用")

        applied = None
        if info.loaded and "mem_limit_mb" in sent:
            wanted = (int(entry.mem_limit_mb) << 20 if entry.mem_limit_mb is not None
                      else mgr.mem_limit_default_bytes(info))
            return await _change_mem_limit(request, model_id, info, entry, wanted)

        store.set_model_settings(model_id, entry)
        return dict(_settings_view_for(mgr, info), applied=applied)


async def _change_mem_limit(request: Request, model_id: str, info, entry,
                            wanted: int) -> dict:
    """Apply one ``mem_limit_mb`` change to a loaded model, and settle it.

    Called with the model's lifecycle lock already held -- the whole transaction
    (settle any previous doubt, record the operation, push, persist, finish) is
    inside it, so no second change can interleave and no new configuration can be
    layered on top of an operation whose outcome is unknown.

    Three review rounds shaped this, and the second round found three gaps left
    by the first:

      * **every sent ``configure`` has a record, including a zero-byte one.** A
        reduction, a no-op, a reserve-off change and an auxiliary model all
        reserve nothing, and the first version used "how much to reserve" as the
        operation state -- so a lost reduction had no record to settle and the
        code dereferenced ``None``. ``begin_limit_change`` always returns a
        record; ``bytes`` is zero when there is nothing to reserve. The two are
        separate fields on purpose.
      * **the record exists before the first await that can be cancelled.** A
        cancellation lands wherever the coroutine happens to be, not only inside
        ``configure``: during the settle read, during the persist, during a
        rollback. Marking the operation first, in one synchronous step, and only
        then doing interruptible work is what makes every one of those reachable.
      * **a failed rollback keeps the original request.** Overwriting the record
        with the rollback's own numbers destroyed the only description of what
        the operator asked for, so neither retry could settle anything.

    The exit is chosen by what is **known**, never by whether an exception
    happened.
    """
    mgr = request.app.state.models
    store = request.app.state.store
    old_limit_bytes = mgr.mem_limit_bytes(info)

    # A record is only meaningful while a worker might be holding what it
    # describes. If the model is not loaded -- its process is gone, or it never
    # came up -- nothing can be read to settle it and nothing can still be
    # holding it, so the entry is stale by construction.
    if not (info.loaded and info.pid is not None):
        mgr.clear_configuration_operations(model_id)

    previous = mgr.pending_settlement(model_id)
    if previous is not None:
        if not mgr.same_budget_request(previous, wanted):
            raise api_error(409, "model_busy", mgr.unresolved_message(model_id))
        settled, actual = await mgr.settle_unresolved(info, previous)
        if settled == "applied":
            # The worker holds the limit this retry is asking for. The file is
            # the only thing still behind, so finish the transaction it started.
            store.set_model_settings(model_id, entry)
            mgr.finish_operation(mgr.pending_settlement(model_id) or previous)
            logger.info(
                "settled %s's unpaid limit change on retry: worker and store both "
                "at a %d MiB limit", model_id, wanted // 2**20)
            return dict(_settings_view_for(mgr, info),
                        applied={"settled_after_lost_reply": True})
        if settled == "unknown":
            raise api_error(503, "service_unavailable",
                            _unsettled_detail(model_id, actual, previous))

    # The record comes first: everything below can be cancelled, and a
    # cancellation must never be able to reach a state where the frame may have
    # been written and nothing says so.
    try:
        operation = await mgr.begin_limit_change(info, wanted)
    except DeviceBudgetUnverifiable as exc:
        raise api_error(503, "service_unavailable", str(exc)) from None
    except DeviceMemoryError as exc:
        # Same code and status a refused *load* produces: the operator's remedy is
        # the same (unload something first), and the console already renders that
        # code as "设备内存不足".
        raise api_error(409, "device_memory_insufficient", str(exc)) from None

    return await _commit_mem_limit(
        request, model_id, info, entry, operation,
        old_limit_bytes=old_limit_bytes)


#: Outcomes of ``configure`` that say nothing about whether the worker applied it.
#: A timeout, a dropped connection, an EOF or a cancelled request all mean "the
#: reply did not arrive", which is not the same as "the change did not happen" --
#: the request may already have been executed. A worker *refusal*
#: (``{"error": ...}``) is different: that says it did not. So is
#: :class:`WorkerTransportError`, which names the case explicitly rather than
#: relying on a message string (MYS-2801).
_INDETERMINATE_CONFIGURE = (asyncio.TimeoutError, TimeoutError, OSError,
                            ConnectionError, asyncio.CancelledError,
                            WorkerTransportError)


async def _commit_mem_limit(request: Request, model_id: str, info, entry,
                            operation, *,
                            old_limit_bytes: int) -> dict:
    """Push the limit, persist it, and settle the record -- or say why not.

    The record (``operation``) already exists and already carries the limit being
    reached for and the one being left behind. Every interruptible step below
    therefore has somewhere to say "this may have been applied" -- which is the
    MYS-2801 second-review fix: the first version marked the operation inside the
    cancellation handler of ``configure`` alone, so a cancellation during the
    settle read left a reservation that nothing had marked as in doubt.

    The claim is kept only where the facts support releasing it. Everywhere else
    it stays -- marked unresolved, still carrying the original request -- so later
    loads and raises cannot spend that memory, and a retry or a confirmed unload
    can finish it.
    """
    mgr = request.app.state.models
    store = request.app.state.store
    wanted = operation.pending_limit_bytes
    try:
        reply = await _apply_mem_limit(request, info, limit_bytes=wanted)
    except asyncio.CancelledError:
        _mark_in_doubt(mgr, operation, phase="sent")
        raise
    except _INDETERMINATE_CONFIGURE:
        return await _settle_unknown(request, model_id, info, entry, operation,
                                     phase="settling")
    else:
        if reply is None or "error" in reply:
            reason = (reply or {}).get("error") or "模型 worker 不可用，请稍后重试"
            mgr.finish_operation(operation)
            raise HTTPException(status_code=409, detail=reason)
        try:
            store.set_model_settings(model_id, entry)
        except Exception as exc:
            # The worker took the new limit and the file did not. Put the worker
            # back; whether the claim may go depends on that being confirmed.
            settled = await _roll_back_limit(
                request, model_id, info, operation, exc=exc,
                old_limit_bytes=old_limit_bytes)
            if not settled:
                raise api_error(
                    503, "service_unavailable",
                    f"模型 {model_id} 的新内存额度已推送到 worker，但保存设置失败"
                    f"（{exc}）；把 worker 恢复到原额度也没有得到确认。"
                    "原请求仍记录在案：worker 可能在新额度上，请在磁盘恢复后"
                    "重试同样的保存以核对，或卸载该模型（进程退出即归还）") from exc
            raise HTTPException(
                status_code=500,
                detail=f"新的内存额度已推送到 worker，但保存设置失败：{exc}；"
                       "已把 worker 恢复到原额度") from exc
        mgr.finish_operation(operation)
        return dict(_settings_view_for(mgr, info), applied=reply)


def _mark_in_doubt(mgr, operation, *, phase: str,
                   reserved_bytes: int | None = None):
    """Flag ``operation`` as possibly applied. Synchronous, so it always runs.

    Called from ``except`` blocks whose task may already be unwinding: no awaits,
    no allocation, one tuple replacement. For a zero-byte operation this reserves
    nothing and still records the doubt, which is what the conflict check and the
    retry path read.
    """
    return mgr.note_unresolved_promise(
        operation, phase=phase, reserved_bytes=reserved_bytes)


def _unsettled_detail(model_id: str, actual: int | None,
                      operation=None) -> str:
    """The 503 message for a change that could not be confirmed either way."""
    seen = (f"读到的运行期额度是 {actual / 2**20:.0f} MiB，既不是新的也不是原来的"
            if actual is not None else "当前读不到它的实际额度")
    wanted = ""
    if operation is not None and operation.pending_limit_bytes is not None:
        wanted = (f"待核对的目标是 {operation.pending_limit_bytes / 2**20:.0f} MiB"
                  f"（原 {operation.previous_limit_bytes / 2**20:.0f} MiB）。"
                  if operation.previous_limit_bytes is not None else "")
    return (f"模型 {model_id} 的内存额度调整结果未确认：worker 可能已应用新额度，"
            f"但答复在途中丢失，且{seen}。{wanted}"
            "这次变更仍记录在案，后续加载与增额不能使用相关额度；"
            "请重试同一次保存以核对，或卸载该模型（进程退出即归还）")


def _settlement_refusal(verdict: str, model_id: str,
                        actual: int | None = None,
                        operation=None) -> HTTPException:
    """The exception a lost-reply settlement raises, given what the read showed."""
    if verdict == "unchanged":
        return api_error(
            409, "model_busy",
            f"模型 {model_id} 的内存额度没有改变：worker 在答复丢失后仍运行在原来的额度上。"
            "原设置与 worker 状态一致，可以重试")
    return api_error(503, "service_unavailable",
                     _unsettled_detail(model_id, actual, operation))


async def _settle_unknown(request: Request, model_id: str, info, entry,
                          operation, *, phase: str) -> dict:
    """Reconcile after a ``configure`` whose outcome is unknown.

    The record is flagged **before** the read is awaited (``phase`` says how far
    the transaction got), so being cancelled *during* the read leaves the truth
    in the ledger rather than in a local variable that is about to disappear.
    This is the second review's finding 2: the old shape awaited the probe
    directly inside the timeout handler, so a cancellation there left
    ``pending 1 / unresolved 0`` -- reserved memory that no retry would settle and
    that allowed a conflicting change through.

    On ``applied`` the setting is stored here and the record dropped; on
    ``unchanged`` the record goes and the caller reports the refusal; on
    ``unknown`` it stays, unresolved, still carrying the original request.
    """
    mgr = request.app.state.models
    store = request.app.state.store
    in_doubt = _mark_in_doubt(mgr, operation, phase=phase)
    verdict, actual = await mgr.settle_unresolved(info, in_doubt)
    if verdict == "applied":
        try:
            store.set_model_settings(model_id, entry)
        except Exception:
            # Cannot record it, so keep the record: the worker holds memory the
            # file does not describe, and the whole point is that this is not
            # forgotten.
            _mark_in_doubt(mgr, in_doubt, phase="settling")
            raise _settlement_refusal("unknown", model_id, actual, in_doubt) from None
        mgr.finish_operation(mgr.pending_settlement(model_id) or in_doubt)
        # The write *did* succeed -- only its reply was lost, and the read
        # confirmed it. Reporting an error here would be as wrong as reporting
        # success for a change that never happened.
        return dict(_settings_view_for(mgr, info),
                    applied={"settled_after_lost_reply": True})
    if verdict == "unchanged":
        raise _settlement_refusal("unchanged", model_id, actual, in_doubt) from None
    # Still nothing definite: keep the record -- it names the model, the request
    # and the phase -- so the next admission cannot spend its bytes and a later
    # retry can finish it.
    _mark_in_doubt(mgr, in_doubt, phase=phase)
    raise _settlement_refusal("unknown", model_id, actual, in_doubt) from None


async def _roll_back_limit(request: Request, model_id: str, info, operation, *,
                           old_limit_bytes: int,
                           exc: BaseException) -> bool:
    """Put a worker back to the old limit after persisting the new one failed.

    Returns whether the rollback is **confirmed**. The expensive mistake this
    replaces (second review, finding 3) was rewriting the record with the
    rollback's own numbers: the record is the only description of what the
    operator asked for, so overwriting it left neither retry able to settle --
    retrying the original request got a 409 and retrying the old value got a 503,
    with the worker still on the new limit. The operation keeps its
    ``pending_limit_bytes``/``previous_limit_bytes``; only the phase moves.

    The claim is released only where the rollback is *confirmed*:

    * the worker answered and is back on the old limit -> release, and the caller
      reports the persistence failure as a plain 500;
    * the rollback was refused, its reply was lost, or it could not be sent ->
      keep the record unresolved (the caller answers 503). A refused rollback
      means the worker is still on the **new** limit while the file says the old
      one, which is precisely the state a retry of the original request can
      settle once the disk works again.
    """
    mgr = request.app.state.models
    logger.warning("persisting %s's new memory limit failed (%s: %s); rolling the "
                   "worker back to a %d MiB limit", model_id, type(exc).__name__,
                   exc, old_limit_bytes // 2**20)
    try:
        reply = await _apply_mem_limit(request, info, limit_bytes=old_limit_bytes)
    except asyncio.CancelledError:
        # The rollback may or may not have reached the worker. Keep the original
        # request and say the rollback is in doubt -- do not claim either side.
        _mark_in_doubt(mgr, operation, phase="rollback_unknown")
        raise
    except _INDETERMINATE_CONFIGURE:
        return await _confirm_rollback(mgr, info, operation,
                                       old_limit_bytes=old_limit_bytes)
    if reply is not None and "error" not in reply:
        # Confirmed by the worker's own answer. The file and the worker agree.
        mgr.finish_operation(operation)
        return True
    # The worker answered and refused the rollback: it is still on the new limit
    # while the file has the old one.
    _mark_in_doubt(mgr, operation, phase="rollback_refused")
    return False


async def _confirm_rollback(mgr, info, operation, *, old_limit_bytes: int) -> bool:
    """Read the worker to find out whether an inconclusive rollback landed."""
    in_doubt = _mark_in_doubt(mgr, operation, phase="rollback_unknown")
    verdict, _actual = await mgr.probe_worker_budget(
        info, operation.pending_limit_bytes,
        previous_limit_bytes=old_limit_bytes)
    if verdict == "unchanged":
        # Back on the old limit: released, the two sides agree again.
        mgr.finish_operation(in_doubt)
        return True
    # Still on the new limit, or unreadable: the record stays, and it still
    # describes the operator's original request so a retry can settle it.
    _mark_in_doubt(mgr, in_doubt, phase="rollback_failed")
    return False


async def _apply_mem_limit(request: Request, info, *, limit_bytes: int | None = None) -> dict | None:
    """Push a new limit to a running worker; a refusal comes back in the reply.

    Three outcomes, and the difference matters to the caller (MYS-2795):

      * **None** -- there is no worker to talk to. Nothing was sent, so nothing
        can have been applied;
      * **{"error": ...}** -- the worker *answered* and refused. It answered, so
        the change did not take effect;
      * **an exception** -- timed out, dropped, or cancelled. This is the one that
        used to be flattened into ``{"error": ...}`` and then read as a refusal,
        which is how "409, nothing changed" got reported while the worker ran at
        the new budget. It propagates now, and the caller settles it by asking the
        worker what it actually did.

    A ``WorkerError`` is not in that third class *when it came from the worker's
    own error reply*: that is the worker answering, so it means refused, and it
    is returned as such. :class:`WorkerTransportError` -- a dead socket, a failed
    write, an EOF with a reply outstanding -- looks identical to callers that
    catch the base class, so it is re-raised here instead of being flattened into
    a refusal (MYS-2801).
    """
    client: WorkerClient | None = request.app.state.clients.get(info.model_id)
    if client is None:
        return None
    mgr = request.app.state.models
    try:
        return await asyncio.wait_for(
            client.configure(mem_limit_mb=(mgr.mem_limit_bytes(info) if limit_bytes is None
                                           else limit_bytes) >> 20,
                             mem_static_bytes=mgr.static_bytes(info)),
            timeout=10)
    except WorkerTransportError:
        # Not a refusal: the worker may have applied it. The caller settles this
        # by reading the worker's own budget.
        raise
    except WorkerError as exc:      # the worker answered, and said no
        return {"error": str(exc)}


@router.post("/models/{model_id}/load")
async def load_model(model_id: str, request: Request, _=Depends(require_admin)):
    app = request.app
    mgr = app.state.models
    mgr.refresh()
    try:
        info = await mgr.load(model_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="model not found on disk")
    except ModelBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ModelConflict as exc:
        # A worker that survived a restart and cannot be proven healthy already
        # owns this model. 409 rather than 500: the request is refused because
        # of the state of the world, and the console shows the detail.
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    register_client(app, model_id, info.port)
    return {"ok": True, "model": _model_view(mgr, info)}


@router.post("/models/{model_id}/unload")
async def unload_model(model_id: str, request: Request, _=Depends(require_admin)):
    app = request.app
    mgr = app.state.models
    # Refuse before touching the client: a 409 must leave the worker and its
    # socket exactly as they were.
    info = mgr.get(model_id)
    if info is None:
        raise HTTPException(status_code=404, detail="model not found")
    try:
        await mgr.raise_if_unloadable(model_id)
    except ModelBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    # The client is closed by ``ModelManager.on_unloading``, from inside the
    # unload, once ``operation: "unloading"`` is published and before the
    # SIGTERM. Doing it here instead would either close the socket before the
    # state switch (a request in between reads loaded with no client) or after
    # the signal (the 120 s grace and a SIGKILL -- see ``forget_client``).
    try:
        info = await mgr.unload(model_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="model not found")
    except ModelBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True, "model": _model_view(mgr, info)}


@router.get("/models/{model_id}/log")
async def model_log(model_id: str, request: Request, lines: int = 200, _=Depends(require_admin)):
    path = request.app.state.models.log_dir / f"worker-{model_id}.log"
    if not path.exists():
        return {"log": ""}
    text = path.read_text(errors="replace").splitlines()
    return {"log": "\n".join(text[-lines:])}


# -- downloads -----------------------------------------------------------
@router.post("/downloads")
async def start_download(body: DownloadBody, request: Request, _=Depends(require_admin)):
    from ..core.downloader import _safe_name

    dm = request.app.state.downloads
    mgr = request.app.state.models
    # The job writes to models/<_safe_name(name)>, so the guards below must ask
    # about that directory, not the raw name: "qwen3-4b." would otherwise pass
    # both checks and still install -- and replace bmodels -- under a loaded
    # "qwen3-4b".
    try:
        name = _safe_name(body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    body = body.model_copy(update={"name": name})
    # The download unpacks into models/<name>, which is the directory a loaded
    # or loading model is running out of. Overwriting it mid-load corrupts the
    # weights under a live worker -- and a running model's files cannot be
    # replaced at all without the worker noticing.
    target = mgr.get(body.name)
    if target is not None and (target.loaded or target.operation is not None):
        raise HTTPException(
            status_code=409,
            detail=f"模型 {target.model_id} 正在运行或正在加载卸载，请先卸载后再重新下载")
    # Two jobs writing the same directory interleave into one corrupt file.
    if body.name in dm.active_names():
        raise HTTPException(
            status_code=409, detail=f"模型 {body.name} 已在下载中，请等待完成或先取消")
    try:
        if body.kind == "dfss":
            from ..core.downloader import catalog_files

            files = body.files
            if not files:
                # A catalogue card posts only url+name (the console has no field
                # for a file set and this stage may not change web/). Expanding
                # it here is what keeps "one click" from installing a fragment:
                # see downloader.catalog_files for the exact conditions.
                files = catalog_files(body.name, body.url)
            job = dm.start_dfss(body.url, body.name, body.expected_bytes,
                                files=files)
        elif body.kind == "url":
            # A customer site with no dfss route downloads a multi-file model
            # this way; without `files` an OCR model would arrive as its
            # detector alone and be refused at load.
            job = dm.start_url(body.url, body.name, body.expected_bytes,
                               files=body.files)
        else:
            raise HTTPException(status_code=400, detail="kind must be 'url' or 'dfss'")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job": job.public()}


@router.get("/catalog")
async def model_catalog(request: Request, _=Depends(require_admin)):
    """Models this release supports, for one-click dfss download.

    Each **installed** entry that has a download tag also carries
    ``latest_file`` / ``update_available``: whether the file on disk is still the
    one the tag points at (see ``downloader.update_status``). That is the whole
    no-touch upgrade mechanism -- repointing a tag on the server makes every
    board report "有新版本" without a new service release.

    The tag index costs one dfss download, so it is cached for ten minutes and
    refreshed **in the background**: this route answers from the cache and the
    next poll picks the result up. An offline board gets no update information
    rather than a slow or broken catalogue page.
    """
    from ..core.downloader import CATALOG, update_status

    mgr = request.app.state.models
    dm = request.app.state.downloads
    on_disk = {m.model_id: m for m in mgr.list()}
    active = dm.active_names()
    # Kick off a refresh when the cache is stale, then use whatever is cached.
    # Never `await` it here: the board's route to dfss can be down, and this is
    # the page an operator opens to find that out.
    dm.flags.schedule_refresh()

    out = []
    for m in CATALOG:
        row = dict(m, installed=m["id"] in on_disk and m["id"] not in active,
                   downloading=m["id"] in active)
        info = on_disk.get(m["id"])
        if row["installed"] and info is not None:
            status = update_status(m, Path(info.path), dm.flags)
            if status is not None:
                row.update(status)
        out.append(row)
    return {"models": out}


@router.post("/models/{model_id}/update")
async def update_model(model_id: str, request: Request, _=Depends(require_admin)):
    """Download the tagged latest build and swap it in for the installed one.

    Refused with 409 while the model is loaded, loading or unloading -- the same
    rule as a re-download, and for the same reason: the file is mapped by a live
    worker. Deleting the old bmodel under it and dropping a new one in would
    corrupt the running model rather than upgrade it.

    Takes the download lock (the job name is the model id), so a second click,
    a load or a delete all see "downloading" and are refused until the swap
    finishes. On failure the installed build is untouched.
    """
    from ..core.downloader import catalog_entry

    mgr = request.app.state.models
    dm = request.app.state.downloads
    info = mgr.get(model_id)
    if info is None:
        raise HTTPException(status_code=404, detail="model not found on disk")
    if info.loaded or info.operation is not None:
        raise HTTPException(
            status_code=409,
            detail=f"模型 {model_id} 正在运行或正在加载卸载，请先卸载后再更新")
    if model_id in dm.active_names():
        raise HTTPException(
            status_code=409, detail=f"模型 {model_id} 已在下载中，请等待完成或先取消")
    entry = catalog_entry(model_id)
    if entry is None:
        raise HTTPException(
            status_code=400, detail=f"模型 {model_id} 不在本版本的下载目录中，无法更新")
    try:
        job = dm.start_update(entry)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job": job.public()}


@router.get("/downloads")
async def list_downloads(request: Request, _=Depends(require_admin)):
    dm = request.app.state.downloads
    return {
        "jobs": dm.list(),
        "orphans": orphan_free_space(request.app.state.models.models_root),
    }


@router.post("/downloads/{job_id}/cancel")
async def cancel_download(job_id: str, request: Request, _=Depends(require_admin)):
    if not await request.app.state.downloads.cancel_and_wait(job_id):
        raise HTTPException(status_code=404, detail="job not found or already finished")
    return {"ok": True}


@router.delete("/models/{model_id}")
async def delete_model(model_id: str, request: Request, _=Depends(require_admin)):
    """Remove a model from disk. Refuses while it is loaded or loading.

    ``operation`` is checked as well as ``loaded``: a worker that is still
    mapping its .bmodel is just as much "in use" as a ready one, and deleting
    the file underneath it is the same mistake as unloading it mid-load.
    """
    mgr = request.app.state.models
    info = mgr.get(model_id)
    if info is None:
        raise HTTPException(status_code=404, detail="model not found")
    if info.loaded:
        raise HTTPException(status_code=409, detail="模型正在运行，请先卸载再删除")
    if info.operation is not None:
        raise HTTPException(status_code=409, detail="模型正在加载或卸载，请完成后再删除")
    if info.downloading:
        # Removing the directory under dfss leaves the job writing into a path
        # that no longer exists; cancelling the job is the supported way out.
        raise HTTPException(status_code=409, detail="模型正在下载，请先取消下载再删除")
    target = Path(info.path).resolve()
    root = mgr.models_root.resolve()
    # Guard against a symlink or a crafted id pointing outside the models tree.
    if root not in target.parents and target != root:
        raise HTTPException(status_code=400, detail="refusing to delete outside the models directory")
    shutil.rmtree(target)
    # The overrides go with the model (MYS-2675). Leaving them behind would
    # silently apply this model's idle threshold and memory limit to a
    # *different* model later downloaded under the same directory name.
    request.app.state.store.forget_model_settings(model_id)
    mgr.forget_static_bytes(model_id)
    mgr.refresh()
    return {"ok": True}


# -- keys ----------------------------------------------------------------
@router.get("/keys")
async def list_keys(request: Request, _=Depends(require_admin)):
    return {"keys": [k.public() for k in request.app.state.store.keys]}


@router.post("/keys")
async def create_key(body: CreateKeyBody, request: Request, _=Depends(require_admin)):
    try:
        raw, key = request.app.state.store.create_key(
            body.name or "unnamed", scope=body.scope)
    except ValueError as exc:
        raise api_error(400, "bad_request", str(exc)) from None
    # The raw key is returned exactly once; only its hash is stored.
    return {"key": raw, "meta": key.public()}


@router.delete("/keys/{key_id}")
async def delete_key(key_id: str, request: Request, _=Depends(require_admin)):
    if not request.app.state.store.delete_key(key_id):
        raise HTTPException(status_code=404, detail="key not found")
    return {"ok": True}


@router.post("/keys/{key_id}/revoke")
async def revoke_key(key_id: str, request: Request, _=Depends(require_admin)):
    if not request.app.state.store.revoke_key(key_id):
        raise HTTPException(status_code=404, detail="key not found")
    return {"ok": True}


_SETTING_FIELDS = ("max_concurrent_per_model", "prefix_cache_entries",
                   "prefix_cache_ttl_min", "max_queue", "prefill_exact_tail",
                   "inference_logging_enabled", "inference_log_retention_count",
                   "inference_log_retention_days", "aux_idle_unload_min", "aux_auto_load",
                   "audit_retention_days")


def _settings_view(s) -> dict:
    from ..core.state import (AUX_IDLE_UNLOAD_MAX_MIN, MAX_CONCURRENCY,
                              AUDIT_RETENTION_DAYS_MAX, AUDIT_RETENTION_DAYS_MIN)

    return {
        "max_concurrent_per_model": s.max_concurrent_per_model,
        "max_concurrency_limit": MAX_CONCURRENCY,
        "prefix_cache_entries": s.prefix_cache_entries,
        "prefix_cache_ttl_min": s.prefix_cache_ttl_min,
        "max_queue": s.max_queue,
        "prefill_exact_tail": s.prefill_exact_tail,
        "require_api_key": s.require_api_key,
        "inference_logging_enabled": s.inference_logging_enabled,
        "inference_log_retention_count": s.inference_log_retention_count,
        "inference_log_retention_days": s.inference_log_retention_days,
        # Idle management of the auxiliary models. ``_limit`` is the field's
        # upper bound, published the same way ``max_concurrency_limit`` is so the
        # console's spinner does not restate it.
        "aux_idle_unload_min": s.aux_idle_unload_min,
        "aux_idle_unload_limit_min": AUX_IDLE_UNLOAD_MAX_MIN,
        "aux_auto_load": s.aux_auto_load,
        # Management audit retention (MYS-2674). `_limit_*` are the field's
        # bounds, published the same way the two above are.
        "audit_retention_days": s.audit_retention_days,
        "audit_retention_days_min": AUDIT_RETENTION_DAYS_MIN,
        "audit_retention_days_max": AUDIT_RETENTION_DAYS_MAX,
    }


@router.get("/settings")
async def get_settings(request: Request, _=Depends(require_admin)):
    return _settings_view(request.app.state.store.settings)


class SettingsBody(BaseModel):
    max_concurrent_per_model: int | None = None
    prefix_cache_entries: int | None = None
    #: **Accepted and ignored since v0.6.34** (MYS-2785). The service-wide cache
    #: byte ceiling is gone: each model's prefix cache is bounded by that model's
    #: own memory limit (``mem_limit_mb``), which is what makes "this model may
    #: occupy at most its limit" answerable. Kept in the body so an older console
    #: (or a script written against v0.6.32) gets a 200 and a no-op instead of a
    #: 422; ``GET /api/settings`` no longer returns the field. See
    #: ``docs/model-settings.md`` and ``docs/admin-api.md``.
    prefix_cache_max_mb: int | None = Field(
        default=None, ge=0, le=16384,
        deprecated=True,
        description="自 v0.6.34 起无效（总上限已删除）：接受但忽略，"
                    "每个模型的前缀缓存改由该模型自己的内存上限约束",
    )
    prefix_cache_ttl_min: int | None = None
    max_queue: int | None = None
    prefill_exact_tail: int | None = None
    inference_logging_enabled: bool | None = None
    inference_log_retention_count: int | None = None
    inference_log_retention_days: int | None = None
    #: 0-1440; 0 = never auto-unload. Out-of-range values are clamped, not
    #: refused, which is what every other field here does -- the console's
    #: spinner can produce a stale number and the operator should not have to
    #: fight it.
    aux_idle_unload_min: int | None = None
    aux_auto_load: bool | None = None
    #: How long management operations are kept (30-3650 days). Clamped like the
    #: rest: an out-of-range value is corrected, not refused.
    audit_retention_days: int | None = None


@router.post("/settings")
async def update_settings(body: SettingsBody, request: Request, _=Depends(require_admin)):
    """Persist the settings and apply them to every loaded model at once.

    Values are clamped to their valid ranges (concurrency is capped at 3).
    Each loaded worker reports what took effect; the cache ceiling there is the
    model's own runtime budget (``limit - static``), not a service-wide number
    (MYS-2785), so changing a global setting cannot shrink it any more.

    ``prefix_cache_max_mb`` in the body is accepted and ignored -- see
    ``SettingsBody``. It is deliberately *not* an error: a console built before
    v0.6.34 posts the whole settings form, and a 422 would make every save from
    it fail after an upgrade.
    """
    store = request.app.state.store
    mgr = request.app.state.models
    with store._lock:
        s = store.settings
        for f in _SETTING_FIELDS:
            v = getattr(body, f)
            if v is not None:
                setattr(s, f, v)
        s.clamp()
        store.save()
    mgr.max_concurrent_per_model = s.max_concurrent_per_model
    # The derived default memory limit budgets one session per concurrent slot,
    # so it has to follow the concurrency setting (MYS-2675). Changing it does
    # not disturb a model already loaded -- that model keeps the limit it was
    # given until it is next loaded or its settings are saved -- and the console
    # shows the derived figure per model, so the two cannot silently disagree.
    mgr.max_concurrent_for_limits = s.max_concurrent_per_model
    mgr.cache_entries = s.prefix_cache_entries
    mgr.cache_ttl_min = s.prefix_cache_ttl_min
    mgr.max_queue = s.max_queue
    mgr.exact_tail = s.prefill_exact_tail
    # Live, like every other setting: the sweep reads these on each pass, so a
    # new threshold applies to the next check (within 30 s) rather than at the
    # next restart. Turning it to 0 does not need to stop the task -- a sweep
    # with a zero threshold returns immediately, which is cheaper than a
    # start/stop dance that could race a shutdown.
    mgr.aux_idle_unload_min = s.aux_idle_unload_min
    mgr.aux_auto_load = s.aux_auto_load
    # Applied to the live store, not just to state.json: the switch has to take
    # effect on the next request, not after a restart.
    request.app.state.inference_log.configure(
        enabled=s.inference_logging_enabled,
        retention_count=s.inference_log_retention_count,
        retention_days=s.inference_log_retention_days,
    )
    # Live, like the switch above: a shorter retention takes effect now, so an
    # operator who lowers it to the minimum sees the old rows go rather than
    # waiting for the next management operation to prune them.
    request.app.state.audit.configure(retention_days=s.audit_retention_days)
    try:
        request.app.state.audit.prune_now()
    except Exception as exc:  # caller decides whether the save can proceed
        logger.warning("pruning the audit trail failed: %s", exc)
    applied = {}
    for info in mgr.list():
        # Same rule as the stats poll: a model mid-operation has no client to
        # configure, and reaching for one would resurrect a closed socket.
        client = (request.app.state.clients.get(info.model_id)
                  if info.loaded and info.operation is None else None)
        if client is None:
            continue
        try:
            applied[info.model_id] = await asyncio.wait_for(client.configure(
                max_concurrent=s.max_concurrent_per_model, max_queue=s.max_queue,
                cache_entries=s.prefix_cache_entries,
                cache_ttl_min=s.prefix_cache_ttl_min,
                exact_tail=s.prefill_exact_tail), timeout=10)
        except Exception as exc:  # caller decides whether the save can proceed
            applied[info.model_id] = {"error": str(exc)}
    return {"settings": _settings_view(s), "applied": applied}


# -- data directory ------------------------------------------------------
class MoveBody(BaseModel):
    path: str


@router.get("/storage")
async def storage_info(request: Request, refresh: bool = False, _=Depends(require_admin)):
    """Footprint of the data directory and the filesystem it sits on.

    ``refresh=true`` skips the 30 s size cache; the overview page polls the
    cached form, the settings page asks for a fresh walk after a move.
    """
    return request.app.state.storage.info(refresh=refresh)


@router.post("/storage/move", status_code=202)
async def storage_move(body: MoveBody, request: Request, _=Depends(require_admin)):
    """Validate now, then move in the background; poll GET /api/storage/move.

    The validation walks the current data tree to size it, which on 20 GB of
    models takes real time -- in the request's thread, not the event loop.
    """
    from ..core.storage import StorageBusy, StorageError

    mgr = request.app.state.storage
    if mgr.busy:
        raise HTTPException(status_code=409, detail="已有搬迁任务在进行")
    try:
        target = await asyncio.to_thread(mgr.check_target, body.path)
        job = mgr.start_move(body.path, target)
    except StorageBusy as exc:  # a second request won the race
        raise HTTPException(status_code=409, detail=str(exc))
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job": job.id}


@router.get("/storage/move")
async def storage_move_status(request: Request, _=Depends(require_admin)):
    return request.app.state.storage.job_view()


# -- inference records ---------------------------------------------------
# Every inference this service actually ran, for after-the-fact debugging of a
# bad answer (MYS-2496). Reads are admin-only for the obvious reason: the rows
# contain customers' conversations.
def _log(request: Request):
    return request.app.state.inference_log


@router.get("/inference-records")
async def list_inference_records(request: Request, limit: int = 50, offset: int = 0,
                                 before: float | None = None,
                                 _=Depends(require_admin)):
    """A page of record summaries, newest first.

    The heavy fields (messages, output text) are only in the detail route: a
    list of 200 records each carrying a 128k-token conversation would be tens of
    megabytes on every poll of the console page.
    """
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    try:
        return _log(request).list(limit=limit, offset=offset, before=before)
    except Exception as exc:  # noqa: BLE001 - a broken log is reported, not fatal
        raise HTTPException(status_code=500, detail=f"记录库不可读：{exc}")


@router.get("/inference-records/status")
async def inference_records_status(request: Request, _=Depends(require_admin)):
    """Whether the log is readable, how big it is, and the last write failure.

    Its own route rather than part of ``/settings``: an operator asking "why is
    the list empty" needs to see that the database is unwritable, and that fact
    is not a setting.
    """
    return _log(request).status()


@router.get("/inference-records-export")
async def export_inference_records(request: Request, _=Depends(require_admin)):
    """NDJSON, one complete record per line, newest first, streamed.

    A sibling of the list path rather than ``/inference-records/export``, so no
    record id can ever collide with it. The generator reads the table in pages,
    so exporting 100k records does not build one huge in-memory string.
    """
    log = _log(request)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    filename = f"inference-records-{stamp}.ndjson"
    return StreamingResponse(
        log.export_lines(),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/inference-records/clear")
async def clear_inference_records(request: Request, _=Depends(require_admin)):
    """Delete every record and give the disk space back."""
    try:
        removed = _log(request).clear()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"清空失败：{exc}")
    return {"ok": True, "deleted": removed}


@router.get("/inference-records/{record_id}")
async def get_inference_record(record_id: str, request: Request, _=Depends(require_admin)):
    record = _log(request).get(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return record


# -- playground ----------------------------------------------------------
def _playground_params(body: ChatBody) -> dict:
    """The console's effective sampling parameters.

    Only what this endpoint really sends to the worker: the console has no
    top_p/top_k/repetition_penalty controls, and recording them as ``null``
    would read as "unknown" rather than "not applicable to this endpoint".
    """
    return {
        "max_tokens": body.max_tokens,
        "temperature": body.temperature,
        "stop": [],
        "enable_thinking": body.enable_thinking,
    }


def _console_context(request: Request, body: ChatBody, *, req_id: str,
                     model: str, prompt: str):
    """A record context for console traffic (admin actor, no API key).

    The recorded messages are the console's *input*, not the rendered prompt: a
    plain prompt is one user turn with the attached pictures listed beside it,
    which is what the operator typed and what a reviewer needs to see.
    """
    from ..core.inference_log import build_context
    from ..schemas import ChatMessage

    if body.messages:
        messages: list = _playground_messages(body)
        extra = None
    else:
        messages = [ChatMessage(role="user", content=body.prompt)]
        extra = list(body.images)
    return build_context(
        request.app.state.inference_log,
        req_id=req_id,
        source=request.url.path,
        model=model,
        actor={"actor_type": "admin", "actor_id": None, "actor_name": "admin"},
        params=_playground_params(body),
        messages=messages,
        extra_images=extra,
        prompt=prompt,
    )


async def _console_stream(client, req_id: str, prompt: str, images: list[str],
                          params: dict, store, ctx) -> AsyncIterator[str]:
    """The console's SSE body for one inference.

    Extracted from the route so it can be driven directly by a test: the
    interesting behaviour is what happens at the *end* of the stream, and a test
    client cannot hang up mid-flight.

    The rule that shapes the control flow: **once the client is gone, yield
    nothing**. Starlette closes this generator with ``GeneratorExit`` thrown at
    its current yield point, and an async generator that yields again while
    closing raises ``RuntimeError: async generator ignored GeneratorExit`` --
    which would replace a clean disconnect with a noisy traceback at exactly the
    moment the shutdown path has the least room for noise, and write to a socket
    whose peer is gone. So ``[DONE]`` is not sent from a shared ``finally``:
    each terminal path sends it (or deliberately does not) on its own, and the
    closing paths only record and re-raise.
    """
    from ..core.inference_log import (
        STATUS_CANCELLED, STATUS_ERROR, STATUS_OK, cancellation_error,
    )

    done: dict = {}
    emitted: list[str] = []
    recorded = False

    def record(status: str, **extra) -> None:
        nonlocal recorded
        if ctx is None or recorded:
            return
        recorded = True
        ctx.finish(
            status=status,
            output_text="".join(emitted),
            raw_output="".join(emitted),
            response_content="".join(emitted) if status == STATUS_OK else None,
            prompt_tokens=done.get("prompt_tokens"),
            completion_tokens=done.get("completion_tokens"),
            cached_tokens=done.get("cached_tokens"),
            first_token_latency_s=done.get("first_token_latency_s"),
            decode_tps=done.get("decode_tps"),
            finish_reason=done.get("finish_reason") if status == STATUS_OK else None,
            **extra,
        )

    def count_usage() -> None:
        # Count console traffic in the same totals as API traffic: the operator
        # benchmarking a model from the UI expects the numbers on the overview
        # page to move, and a separate counter would make the dashboard lie
        # about how much work the box has done.
        if done:
            store.record_usage(
                None,
                done.get("prompt_tokens", 0),
                done.get("completion_tokens", 0),
                cached_tokens=done.get("cached_tokens", 0),
                decode_tps=done.get("decode_tps"),
            )

    try:
        async for evt in client.generate(req_id, prompt, params, images or None):
            if evt["op"] == "delta":
                emitted.append(evt["text"])
                yield f"data: {json.dumps({'text': evt['text']})}\n\n"
            elif evt["op"] == "done":
                done = evt
                yield f"data: {json.dumps({'done': True, **{k: evt.get(k) for k in ('prompt_tokens','completion_tokens','cached_tokens','first_token_latency_s','decode_tps','finish_reason')}})}\n\n"
    except WorkerError as exc:
        # The worker refused or died: the client is still there and still needs a
        # terminating frame, so this path reports the error *and* closes cleanly.
        record(STATUS_ERROR, error=exc)
        count_usage()
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        yield "data: [DONE]\n\n"
        return
    except (asyncio.CancelledError, GeneratorExit):
        # The client is gone. Record what was generated, then get out without
        # touching the socket again.
        etype, emsg = cancellation_error("console stream")
        record(STATUS_CANCELLED, error_type=etype, error_message=emsg)
        count_usage()
        raise
    except (ConnectionError, OSError) as exc:
        # The backend died mid-stream. The client is still listening, so it gets
        # the same clean close as a normal end -- it is the API that failed, not
        # the connection to the browser.
        record(STATUS_ERROR, error=exc)
        count_usage()
        yield f"data: {json.dumps({'error': f'连接中断：{type(exc).__name__}'})}\n\n"
        yield "data: [DONE]\n\n"
        return
    record(STATUS_OK)
    count_usage()
    yield "data: [DONE]\n\n"


@router.post("/chat/stream")
async def playground_chat_stream(body: ChatBody, request: Request, _=Depends(require_admin)):
    """SSE variant for the built-in dialog.

    Separate from /v1/chat/completions because the console authenticates with a
    cookie, not a bearer key: reusing the OpenAI route would force the operator
    to mint a key just to click "send" in the UI.
    """
    from .openai_api import CHAT_KINDS, _resolve_model

    import uuid

    # Both console chat routes are chat-only: an embedding model has no
    # generate op, and a 400 naming /v1/embeddings is a better answer than the
    # worker's "unknown op".
    info, client = await _resolve_model(request, body.model, expect=CHAT_KINDS)
    params = {"max_tokens": body.max_tokens, "temperature": body.temperature, "stop": []}

    store = request.app.state.store

    prompt, images = _playground_request(body, ocr_vl=info.kind == "ocr_vl")

    req_id = uuid.uuid4().hex
    # Created when the request is dispatched, at the instant the inference
    # starts: everything above is validation, which never reaches the NPU.
    ctx = _console_context(request, body, req_id=req_id, model=info.model_id,
                           prompt=prompt)

    return StreamingResponse(
        _console_stream(client, req_id, prompt, images, params, store, ctx),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat")
async def playground_chat(body: ChatBody, request: Request, _=Depends(require_admin)):
    """Same path as /v1/chat/completions, for the built-in test dialog.

    Kept separate so the console can drive a model without minting an API key.
    """
    from ..core.inference_log import STATUS_ERROR, STATUS_OK
    from .openai_api import CHAT_KINDS, _resolve_model

    # Both console chat routes are chat-only: an embedding model has no
    # generate op, and a 400 naming /v1/embeddings is a better answer than the
    # worker's "unknown op".
    info, client = await _resolve_model(request, body.model, expect=CHAT_KINDS)
    import uuid

    req_id = uuid.uuid4().hex
    prompt, images = _playground_request(body, ocr_vl=info.kind == "ocr_vl")
    ctx = _console_context(request, body, req_id=req_id, model=info.model_id,
                           prompt=prompt)
    text_parts: list[str] = []
    done: dict = {}
    try:
        async for evt in client.generate(
            req_id, prompt,
            {"max_tokens": body.max_tokens, "temperature": body.temperature, "stop": []},
            images or None,
        ):
            if evt["op"] == "delta":
                text_parts.append(evt["text"])
            elif evt["op"] == "done":
                done = evt
    except WorkerError as exc:
        if ctx is not None:
            ctx.finish(status=STATUS_ERROR, error=exc, output_text="".join(text_parts),
                       raw_output="".join(text_parts),
                       prompt_tokens=done.get("prompt_tokens"))
        raise HTTPException(status_code=500, detail=str(exc))
    except (ConnectionError, OSError) as exc:
        if ctx is not None:
            ctx.finish(status=STATUS_ERROR, error=exc, output_text="".join(text_parts),
                       raw_output="".join(text_parts))
        raise
    text = "".join(text_parts)
    if ctx is not None:
        ctx.finish(status=STATUS_OK, output_text=text, raw_output=text,
                   response_content=text, finish_reason=done.get("finish_reason"),
                   prompt_tokens=done.get("prompt_tokens"),
                   completion_tokens=done.get("completion_tokens"),
                   cached_tokens=done.get("cached_tokens"),
                   first_token_latency_s=done.get("first_token_latency_s"),
                   decode_tps=done.get("decode_tps"))
    return {
        "text": text,
        "prompt_tokens": done.get("prompt_tokens", 0),
        "completion_tokens": done.get("completion_tokens", 0),
        "cached_tokens": done.get("cached_tokens", 0),
        "first_token_latency_s": done.get("first_token_latency_s"),
        "decode_tps": done.get("decode_tps"),
        "finish_reason": done.get("finish_reason"),
    }


# -- console test proxies (MYS-2599) ------------------------------------
# The playground tests every model kind, and every kind but chat is only served
# under /v1, behind an API key. The console has an admin cookie, not a key, and
# making the operator mint one to press "test" is what /api/chat* was written
# to avoid. These routes are that same exemption for the other kinds.
#
# They call the /v1 handler objects themselves rather than re-implementing
# them, so validation, limits, error codes and response shapes cannot drift
# between what the console shows and what a client gets. Two things differ,
# both by construction: the caller is the admin (``key_id=""`` records actor
# ``admin``, as the console chat does), and the record's ``source`` is this
# path (it is ``request.url.path``), so console traffic stays distinguishable
# from API traffic in the inference records.


@router.post("/test/embeddings")
async def console_embeddings(body: EmbeddingRequest, request: Request,
                             _=Depends(require_admin)):
    from . import openai_api

    return await openai_api.embeddings(body, request, key_id="")


@router.post("/test/rerank")
async def console_rerank(body: RerankRequest, request: Request,
                         _=Depends(require_admin)):
    from . import openai_api

    return await openai_api.rerank(body, request, key_id="")


@router.post("/test/audio/transcriptions")
async def console_transcriptions(request: Request, _=Depends(require_admin)):
    """multipart, read by the /v1 handler from the request itself."""
    from . import openai_api

    return await openai_api.transcriptions(request, key_id="")


@router.post("/test/ocr")
async def console_ocr(request: Request, _=Depends(require_admin)):
    """JSON or multipart, read by the /v1 handler from the request itself."""
    from . import openai_api

    return await openai_api.ocr(request, key_id="")


@router.post("/test/chat/completions")
async def console_chat_completions(body: ChatCompletionRequest, request: Request,
                                   _=Depends(require_admin)):
    """The OpenAI chat route, for kinds /api/chat* does not serve.

    /api/chat/stream is chat-only by contract (it renders the console's own
    prompt shape). A vision-OCR model is driven with OpenAI's vision message
    format through /v1/chat/completions, so the console calls that handler and
    gets exactly the kind rules it applies.
    """
    from . import openai_api

    return await openai_api.chat_completions(body, request, key_id="")
