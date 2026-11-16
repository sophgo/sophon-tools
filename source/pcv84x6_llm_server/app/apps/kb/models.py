"""Which auxiliary models this app may use right now.

Answers "is there a ready embedding/rerank/chat model, and which", *without*
raising when the answer is no -- a missing model is a skipped stage, not an
error.

Two resolutions, and the difference is the whole idle feature:

``resolve``
    Only an already-loaded model. Synchronous, and still the right call where a
    model cannot be brought up on demand (a chat model, or a stage that must not
    block a request for tens of seconds).

``resolve_or_load``
    Loads one when nothing of the kind is loaded and ``aux_auto_load`` permits.
    Asynchronous by necessity, and what the knowledge-base stages and the MCP
    tools use: an operator who left an embedding model to be auto-unloaded should
    not see the vector stage silently skip the next time they search.

``ModelManager.require_ready`` is still the admission rule. It is what these
helpers call once a model has been chosen, so an unload that starts between the
scan and the call is refused the same way any other inference would be -- and
every successful resolution is touched, which is what keeps the idle sweep from
unloading a model out from under the request that just revived it.
"""

from __future__ import annotations

import logging

from ...core.models import ModelBusy, ModelNotLoaded, ModelUnavailable

logger = logging.getLogger(__name__)

#: What each kind is called in a refusal. The API's own ``kind`` values are
#: jargon to the operator reading a skipped stage's reason; these are the words
#: the console and docs use.
_LABEL = {
    "embedding": "向量（embedding）",
    "rerank": "精排（rerank）",
    "chat": "对话",
    "ocr": "OCR",
    "ocr_vl": "OCR-VL",
    "asr": "语音识别",
}


def _ready_models(request, kind: str) -> list:
    """Every model of ``kind`` that is loaded and has no operation in flight.

    Sorted by ``loaded_at`` so the choice is stable: with two embedding models
    loaded the newest wins, which is what the operator last asked for.
    """
    manager = request.app.state.models
    try:
        models = manager.list()
    except Exception:  # pragma: no cover - the manager does not raise today
        logger.warning("listing models failed", exc_info=True)
        return []
    ready = [
        m for m in models
        if m.kind == kind and m.loaded and m.operation is None
        and manager.still_loaded(m)
    ]
    ready.sort(key=lambda m: (m.loaded_at or 0.0), reverse=True)
    return ready


class Resolved:
    """A ready model and its RPC client, or the reason there is none."""

    def __init__(self, info=None, client=None, reason: str | None = None) -> None:
        self.info = info
        self.client = client
        self.reason = reason

    def __bool__(self) -> bool:
        return self.info is not None and self.client is not None

    @property
    def model_id(self) -> str | None:
        return self.info.model_id if self.info is not None else None

    @property
    def vector_family(self) -> str:
        """The vector space this model encodes into (``""`` for non-embedding).

        Exposed here so the knowledge base's "is this the model my vectors were
        built with" check reads the *space*, not the file name: two builds of
        the same embedding model are interchangeable (MYS-2706).

        Falls back through ``core.models.vector_family`` -- an embedding model
        that declares no family is its own family -- so the rule is the same
        one ``discover_models`` applies, and a model object from somewhere else
        (a test double, an adopted worker) cannot answer differently.
        """
        if self.info is None:
            return ""
        from ...core.models import vector_family

        return vector_family(self.info.model_id, getattr(self.info, "kind", ""),
                             getattr(self.info, "vector_family", None))


def same_space(family: str | None, resolved) -> bool:
    """Whether ``resolved`` may encode into the vector space ``family``.

    The one place the knowledge base's "same space?" question is answered, so
    ingest, reindex and the vector stage cannot disagree about it. An empty
    ``family`` means the library records no model yet -- nothing to preserve, so
    anything is acceptable (that is a brand new library, not a mismatch).
    """
    family = family or ""
    if not family:
        return True
    return getattr(resolved, "vector_family", "") == family


def vector_family_of(request, model_id: str | None) -> str:
    """The vector family a recorded model id belongs to.

    A library records the id it was built with, and that build may since have
    been removed from disk -- the check still has to answer "is the model in
    front of me the same space". Order: the manager's own scan (authoritative
    for whatever is on disk), then the download catalogue (a build that is
    listed but not installed), then the id itself, which matches nothing else
    and therefore refuses the mix rather than assuming it is safe.
    """
    if not model_id:
        return ""
    manager = getattr(getattr(request, "app", None), "state", None)
    manager = getattr(manager, "models", None)
    info = None
    getter = getattr(manager, "get", None)
    if callable(getter):
        try:
            info = getter(model_id)
        except Exception:  # pragma: no cover - a fake manager with no lookup
            info = None
    if info is not None:
        family = getattr(info, "vector_family", "")
        if family:
            return family
    from ...core.models import catalogue_vector_family

    return catalogue_vector_family(model_id) or model_id


def answer_kind() -> str:
    """The kind the knowledge base answers a question with.

    ``chat`` and only ``chat``. Every resolution here takes a kind, and the
    answer stage's is written at one site -- ``app/api/apps_api.py`` -- so this
    exists to make the exclusion a *rule* rather than one call site's argument:
    PaddleOCR-VL answers /v1/chat/completions, so a caller that passed its kind
    would get an OCR of the question instead of an answer to it
    (``AGENT_MODEL_KINDS`` carries the same rule for agents).
    """
    from ...core.models import AGENT_MODEL_KINDS

    return AGENT_MODEL_KINDS[0]


def resolve(request, kind: str) -> Resolved:
    """The ready model of ``kind`` to use, or a reason none can be used.

    A worker whose socket cannot be found is treated as absent rather than as a
    failure: the model reads as loaded but nothing can reach it, and the stage
    that needs it should degrade exactly like an unloaded one.

    Loaded-only, and synchronous. Use ``resolve_or_load`` where bringing a model
    up is acceptable -- the knowledge-base stages and the MCP tools do; a chat
    model (tens of seconds to load) never does.
    """
    ready = _ready_models(request, kind)
    for info in ready:
        if request.app.state.clients.get(info.model_id) is None:
            continue
        resolved = _resolved_from(request, info, kind)
        if resolved:
            return resolved
    if ready:
        return Resolved(reason=f"{_LABEL.get(kind, kind)}模型已加载但没有可用的 worker 连接，"
                               "请重新加载")
    return Resolved(reason=f"未加载{_LABEL.get(kind, kind)}模型")


def _resolved_from(request, info, kind: str) -> Resolved:
    """The ``Resolved`` for a chosen ``info``, or the reason there is no client.

    The one place the client lookup and the kind re-check happen, so ``resolve``,
    ``resolve_named`` and ``resolve_or_load`` cannot disagree about what "ready"
    means.
    """
    manager = request.app.state.models
    if info.kind != kind:
        return Resolved(reason=(f"模型 {info.model_id} 是{_LABEL.get(info.kind, info.kind)}模型，"
                                f"不能用于{_LABEL.get(kind, kind)}阶段"))
    client = request.app.state.clients.get(info.model_id)
    if client is None:
        return Resolved(reason=f"模型 {info.model_id} 没有可用的 worker 连接，请重新加载")
    if hasattr(manager, "touch"):
        manager.touch(info.model_id)
    return Resolved(info=info, client=client)


async def resolve_or_load(request, kind: str, preferred: str | None = None,
                          family: str | None = None) -> Resolved:
    """The model of ``kind`` to use, loading one if none is loaded.

    ``preferred`` is the model the caller would rather have -- the knowledge base
    passes the model its vectors were built with, so a search keeps comparing
    vectors from the same space. ``family`` is *that model's* vector space, and
    passing it is what makes a sibling build an acceptable answer: the seq512 and
    seq2048 builds encode the same space, so a library recorded against one keeps
    searching when only the other is loaded (MYS-2706). A caller that leaves
    ``family`` out gets the pre-existing behaviour exactly.

    Both are preferences, not requirements: a library whose model is gone from
    disk still searches with whatever is available (and the vector stage then
    skips itself with a reason naming the mismatch, which is the honest answer).

    Never raises for "no model": the caller's contract is a skipped stage with a
    reason. A load that fails comes back as that reason, carrying the manager's
    own message (NPU memory, worker never ready).
    """
    manager = request.app.state.models
    info, reason = await manager.load_for(kind, preferred, family=family)
    if info is None:
        return Resolved(reason=reason)
    return _resolved_from(request, info, kind)


def resolve_named(request, kind: str, model_id: str | None) -> Resolved:
    """``model_id`` if it is ready and of ``kind``, else a reason.

    Used where the caller names the model -- ``/answer``'s optional ``model``.
    """
    if not model_id:
        return resolve(request, kind)
    manager = request.app.state.models
    try:
        info = manager.require_ready(model_id)
    except KeyError:
        return Resolved(reason=f"模型 {model_id} 不存在")
    except ModelBusy as exc:
        return Resolved(reason=str(exc))
    except ModelNotLoaded as exc:
        return Resolved(reason=str(exc))
    except ModelUnavailable as exc:
        return Resolved(reason=str(exc))
    return _resolved_from(request, info, kind)
