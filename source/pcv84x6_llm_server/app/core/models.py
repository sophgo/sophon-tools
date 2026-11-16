"""Model discovery on disk and lifecycle of per-model worker processes."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from . import procs
from .procs import PopenLike

BASE = Path(__file__).resolve().parent.parent.parent

logger = logging.getLogger(__name__)

MODEL_EXTS = (".bmodel",)

#: What a model can do, decided from the bmodel it ships. The kind is a fact
#: about the *build*, not about the directory name an operator chose, so it is
#: read off the file the worker will load and written into the command line --
#: which makes it part of the worker's identity, the same way ``--model-id`` is.
#:
#: ``chat`` is the default because every build this service shipped before the
#: auxiliary models existed is one.
KINDS = ("chat", "embedding", "rerank", "asr", "ocr", "ocr_vl")

#: (bmodel file-name prefix, kind), matched against the lowercased name. The two
#: spellings of each name are listed because dfss and our own builds disagree on
#: separator style. No prefix is a prefix of another, so order does not matter.
KIND_PREFIXES: tuple[tuple[str, str], ...] = (
    ("wemm-embedding", "embedding"),
    ("wemm_embedding", "embedding"),
    ("qwen3-vl-embedding", "embedding"),
    ("qwen3_vl_embedding", "embedding"),
    ("qwen3-embedding", "embedding"),
    ("qwen3_embedding", "embedding"),
    ("bge-reranker", "rerank"),
    ("bge_reranker", "rerank"),
    ("qwen3-asr", "asr"),
    ("qwen3_asr", "asr"),
    # PP-OCRv6's builds are named ``ppocrv6-medium-det_…`` / ``-rec_…``. Both
    # spellings appear in the wild (our compiler emits the hyphenated one, the
    # vendor's demos use the underscore), and ``ppocr`` catches a future
    # ``ppocrv5``/``ppocr-vl`` build under the same family name.
    # PaddleOCR-VL is a *chat-shaped* OCR model: it answers
    # /v1/chat/completions with an image and a task prompt and returns OTSL, so
    # it is neither a ``chat`` model (it is not a general conversation model and
    # must not be offered to an agent) nor an ``ocr`` one (that kind is the
    # PP-OCR det+rec pair, which has its own /v1/ocr shape). Its own kind is
    # what keeps both of those true. Listed before the ``ppocr`` entries it does
    # not match anyway, because "paddleocr-vl" does not start with "ppocr" --
    # the ordering is for the reader, not the matcher.
    ("paddleocr-vl", "ocr_vl"),
    ("paddleocr_vl", "ocr_vl"),
    ("ppocrv6", "ocr"),
    ("ppocr", "ocr"),
    # The page segmenter that ``mode: "layout"`` needs. It is **not** named
    # ``ppocr…``: it is PP-DocLayout, a different model family that happens to
    # ship inside the same OCR model directory. Without this line the name falls
    # through to ``chat``, and because ``ppdoclayout-…`` sorts before
    # ``ppocrv6-medium-det_…`` it would be the file the kind is read *from* --
    # so adding the fifth file would silently turn the OCR model into a chat
    # model. ``tests/test_model_kind.py`` pins it.
    ("ppdoclayout", "ocr"),
    ("pp-doclayout", "ocr"),
)

#: The kinds the idle machinery manages when a model has no per-model entry of
#: its own: unloaded when unused, loaded on demand.
#:
#: Deliberately a whitelist rather than "everything but chat". ``chat`` is out
#: because a 35B takes tens of seconds to map into NPU memory and the agents
#: depend on it staying resident; ``ocr_vl`` is out for the same reason -- it is
#: a 2.27 GB bmodel that takes ~7 s to map and ~3.3 GB of NPU memory, and a page
#: of OCR is a burst of requests, so unloading it between them would spend the
#: saving on the next load. It is loaded and unloaded by hand like a chat model.
#: A new auxiliary kind must be added here knowingly -- an omission costs
#: memory, an accidental inclusion costs a minute on the next request.
#:
#: Since MYS-2675 this is the scope of the **global defaults only**. Any model,
#: chat included, can be put under the same machinery individually through
#: ``model_settings[<id>]``; ``effective_idle_minutes`` and
#: ``effective_auto_load`` are the two functions that decide which applies.
AUX_KINDS = ("embedding", "rerank", "asr", "ocr")

#: The kinds an agent may be configured with, and the kinds the knowledge base
#: may answer a question with.
#:
#: Only ``chat``: an agent and a knowledge-base answer are *conversations*, and
#: a model that only reads an image on request cannot hold one. PaddleOCR-VL
#: answers /v1/chat/completions all the same, which is exactly why this is a
#: separate whitelist rather than "anything the chat route accepts" -- getting
#: it wrong would put an OCR model in an agent's model menu, and, worst case,
#: make it the default model for every new agent.
AGENT_MODEL_KINDS = ("chat",)

#: How often the background task looks for idle auxiliary models. A minute-long
#: threshold cannot need a tighter poll, and this one is cheap: it reads three
#: in-memory fields per loaded model and asks the worker nothing unless a model
#: is already past its deadline.
IDLE_SWEEP_INTERVAL_S = 30.0

#: What each kind is called in a refusal an operator reads. Mirrors
#: ``app/apps/kb/models.py``'s table; duplicated rather than imported because the
#: manager must not depend on the knowledge-base app (it loads before it).
_KIND_LABEL = {
    "embedding": "向量（embedding）",
    "rerank": "精排（rerank）",
    "asr": "语音识别",
    "ocr": "OCR",
    "ocr_vl": "OCR-VL",
    "chat": "对话",
}

#: Where each kind's tokenizer/processor config lives inside the install tree.
#: A model directory that carries its own ``config/`` wins over this; the
#: bundled copy exists for the dfss case, where a download brings only the
#: .bmodel.
KIND_CONFIG_DIRS: dict[str, str] = {
    "chat": "qwen3_5",
    "embedding": "qwen3_embedding",
    "rerank": "bge_reranker_v2_m3",
    "asr": "qwen3_asr",
    # Not a tokenizer: this directory holds ppocr.json and the character
    # dictionary, and the OCR backend reads them from the config path its worker
    # is started with (see app/engine/ocr_ppocr.load_config).
    "ocr": "ppocr_v6",
    # The tokenizer, chat template and preprocessor config of PaddleOCR-VL. The
    # marker is tokenizer.json: the worker renders the prompt and tokenises with
    # this model's own vocabulary, both of which live in that file.
    "ocr_vl": "paddleocr_vl_1_5",
}


#: What an in-flight model operation is, as the console reports it.
#: ``None`` means idle; there is no other place this fact is stored.
ModelOperation = str | None
LOADING: ModelOperation = "loading"
UNLOADING: ModelOperation = "unloading"

#: How long a worker gets to exit after SIGTERM before it is SIGKILLed, and how
#: long the kill itself is waited for. Named because the second one is what an
#: operator sees as "卸载耗时 130 秒" (MYS-2784): 120 s + 10 s is the whole grace,
#: and a worker wedged in the driver reaches it every time. Module-level so a
#: test can shorten it without waiting two minutes to observe what is left
#: behind.
UNLOAD_GRACE_S = 120.0
KILL_GRACE_S = 10.0


class ModelBusy(RuntimeError):
    """A model operation refused because another one is in flight (HTTP 409).

    Distinct from the plain ``RuntimeError`` a limit or a memory check raises:
    both are 409, but this one means "try again in a moment", not "change the
    configuration".
    """


class ModelNotLoaded(RuntimeError):
    """The model is not serving: nothing is loaded, or the last load failed.

    The inference refusal an unloaded model gets (HTTP 409). Distinct from
    ``ModelBusy`` because the two call for different operator actions:
    ``busy`` means "retry in a moment", this one means "go to the console and
    load it".
    """


class ModelUnavailable(RuntimeError):
    """The model *was* loaded and its worker is gone (HTTP 503).

    Deliberately not a 409. ``loaded`` was true a moment ago and the request is
    well-formed against a model the client has every reason to believe is up --
    the service failed, not the caller. 503 is the retryable-after-a-reload
    answer, and it is what the pre-existing dead-worker path already produced
    from the RPC socket; keeping the code stable matters for clients that
    already special-case it.
    """


class ModelConflict(RuntimeError):
    """A worker this manager cannot account for already owns this model.

    The process looks like ours (right module, right model id, inside our models
    tree) but does not answer its health handshake -- still mapping weights, or
    wedged. Spawning a second worker would put two processes on one bmodel and
    two allocations on the NPU heap, so the load is refused instead. Its pid is
    reported so the operator can decide.
    """


# -- the four loading refusals that deserve their own error code (MYS-2676) ---
# The API answers all four with 409, and before MYS-2676 all four were a plain
# ``RuntimeError`` whose only machine-readable trace was the Chinese sentence.
# A script could not tell "retry in a moment" from "unload something" from
# "raise this model's limit". These subclasses carry the distinction to the error
# handler (app/core/errors.py) without changing a single status code or message,
# and they keep subclassing ``RuntimeError`` so every existing ``except
# RuntimeError`` still catches them.
class DeviceMemoryError(RuntimeError):
    """NPU/VPP device memory cannot hold this model (``device_memory_insufficient``)."""


class SystemMemoryError(RuntimeError):
    """System RAM is too low to spawn a worker (``system_memory_insufficient``)."""


class ModelMemLimitError(RuntimeError):
    """The model's own memory ceiling is below its static footprint
    (``model_mem_limit_exceeded``)."""


class LoadFailure(RuntimeError):
    """The worker was spawned and never became ready (``load_failed``)."""


class DeviceBudgetUnverifiable(RuntimeError):
    """A device backend could not read the NPU heap, so nothing may be promised.

    Raised only on the *runtime* raise path (MYS-2795). A load may proceed
    without a reading -- the engine refuses a model that does not fit, and a dev
    checkout has no bm-smi -- but raising a live model's budget hands it memory
    the engine will allocate the moment a request grows a session. If the
    management plane cannot see the heap it cannot claim there is room, and "no
    reading, so no objection" is exactly the bypass this exception closes. The
    API reports it as 503 (a subsystem is unavailable), not 409 (the state of
    the world says no), because retrying after bmlib comes back is the remedy.
    """


@dataclass
class ModelInfo:
    """A model directory on disk, whether or not it is currently loaded."""

    model_id: str
    path: str
    display_name: str
    #: chat | embedding | rerank | asr -- what this build can serve. Read from
    #: the bmodel file name (see ``kind_of_bmodel``), never configured: it is a
    #: property of the compiled graph, and every route refuses a mismatch.
    kind: str = "chat"
    size_bytes: int = 0
    bmodel_files: list[str] = field(default_factory=list)
    has_config: bool = False
    context_length: int | None = None
    supports_vision: bool = False
    #: Width of the model's output vector, for the kinds where that is a number
    #: a client asks about (embedding: the MRL truncation ceiling). Filled from
    #: the loaded worker, because it is a property of the compiled graphs.
    hidden_size: int | None = None
    #: Which **vector space** this model encodes into (see ``vector_family``).
    #: Only embedding models have one; everything else carries an empty string.
    #: Two entries with the same family produce comparable vectors even though
    #: they are different files -- that is what lets a seq512 build and a seq2048
    #: build serve one knowledge base (MYS-2706).
    vector_family: str = ""
    # Whether temperature/top_p/top_k can take effect (see EngineBackend). Set
    # from the loaded worker, since it depends on the bmodel's lm_head.
    supports_sampling: bool = True
    # Runtime state, filled in by ModelManager.
    loaded: bool = False
    port: int | None = None
    pid: int | None = None
    loaded_at: float | None = None
    load_error: str | None = None
    load_seconds: float | None = None
    # The operation in flight, or None. This is the only source of truth for
    # "is this model busy": a load that has spawned its worker but is still
    # waiting for readiness reports ``loading`` with ``loaded`` still false,
    # which is exactly what a page refreshed mid-load must show. It lives on
    # the manager's own object (never in the browser) so every client and every
    # reload sees the same answer.
    operation: ModelOperation = None
    operation_since: float | None = None
    #: Set when a worker that survived a restart could not be adopted: the model
    #: must not read as idle (that is how a load turns into a second worker), and
    #: must not read as loaded either. ``conflict`` carries the reason, ``pid``
    #: the process an operator would have to deal with.
    conflict: str | None = None
    #: True when this run attached to a worker an earlier run spawned.
    adopted: bool = False
    #: True while a download job is still writing into this model's directory.
    #: The .bmodel is incomplete, so loading and deleting are refused.
    downloading: bool = False
    #: Monotonic instant this model was last used -- at the completion of a load
    #: and on every request that resolves to it. Monotonic rather than wall clock
    #: because it only ever measures an interval, and the board's clock is stepped
    #: by NTP after an RTC-less boot (a negative interval would read as "idle
    #: forever"). ``last_used_at`` is the epoch-seconds form the API reports.
    last_used_mono: float | None = None
    last_used_at: float | None = None
    #: Why the model was last unloaded automatically, or None. Only ``"idle"``
    #: today. Cleared by a manual unload and by any load: the console shows it as
    #: "auto-unloaded after N minutes idle", which stops being true the moment an
    #: operator acts on the model.
    unloaded_reason: str | None = None
    #: Device bytes this model's *live sessions and prefix cache* hold, as the
    #: worker last reported them. Filled by ``admin_api`` from the worker's
    #: ``stats`` reply on every console poll that touches this model -- the
    #: worker is the only process that knows (it owns the KV and the cache), and
    #: the number moves with every request. None means "not reported yet"; 0 is
    #: a real answer (loaded, nothing running).
    runtime_bytes: int | None = None
    #: The static footprint the device actually showed during the last load of
    #: this model in this process (the heap difference across the spawn). It
    #: replaces ``bmrt_get_bmodel_info``'s estimate once known, because the
    #: estimate over-declares dynamic IO badly enough to derive a default limit
    #: larger than the whole board. None until this process has loaded the model.
    measured_static_bytes: int | None = None

    def public(self, *, idle_unload_at: float | None = None) -> dict:
        """The wire form.

        ``idle_unload_at`` is passed in rather than computed here: whether the
        model *will* be unloaded depends on the configured threshold, the
        worker's in-flight count and the model's kind -- three things the manager
        knows and this dataclass does not. Keeping the arithmetic out of here also
        means an "unloaded" model cannot accidentally report a future unload time.
        """
        return {
            "id": self.model_id,
            "display_name": self.display_name,
            "path": self.path,
            "kind": self.kind,
            "size_bytes": self.size_bytes,
            "bmodel_files": self.bmodel_files,
            "has_config": self.has_config,
            "context_length": self.context_length,
            "supports_vision": self.supports_vision,
            "hidden_size": self.hidden_size,
            # Which vector space an embedding model encodes into. Two builds with
            # the same value may serve one knowledge base; empty for every kind
            # that has no vectors (MYS-2706).
            "vector_family": self.vector_family,
            # False when the bmodel fuses argmax into lm_head, so the server can
            # only return the argmax. The console shows this instead of offering
            # sampling sliders that would do nothing.
            "supports_sampling": getattr(self, "supports_sampling", True),
            "loaded": self.loaded,
            "port": self.port,
            "pid": self.pid,
            "load_error": self.load_error,
            "load_seconds": self.load_seconds,
            "loaded_at": self.loaded_at,
            "operation": self.operation,
            "operation_since": self.operation_since,
            # Kept out of the load path: a conflict is a refusal, and the console
            # shows it next to the (disabled) load button.
            "conflict": self.conflict,
            "adopted": self.adopted,
            "downloading": self.downloading,
            # Idle management (docs/aux-models.md § 空闲自动卸载). All three are
            # additive: a console that knows nothing about them is unaffected.
            "last_used_at": self.last_used_at,
            "unloaded_reason": self.unloaded_reason,
            "idle_unload_at": idle_unload_at,
        }


@dataclass(frozen=True)
class WorkerIdentity:
    """The facts that make one worker process *this* model's worker.

    Recorded when a worker is spawned (and when one is adopted), then re-checked
    whenever the manager has to believe ``loaded`` without having just talked to
    the process: a worker that died, or a port that has been taken over by some
    other application, must stop reading as "loaded".
    """

    pid: int
    port: int
    started: float | None = None


def read_bmodel_meta(path: Path) -> dict:
    """Best-effort peek at a bmodel's metadata.

    The full parser lives in libsophon; here we only need the handful of fields
    the UI displays, and we must not import sail to get them (this runs on the
    management plane and must work even when no NPU driver is present).
    """
    meta = {"context_length": None, "supports_vision": False}
    name = path.name.lower()
    # bmodel filenames encode the useful facts: "…_seq2048_…_4core_dynamic_…"
    for part in name.split("_"):
        if part.startswith("seq") and part[3:].isdigit():
            meta["context_length"] = int(part[3:])
    meta["supports_vision"] = is_vl_embedding(name) or any(k in name for k in ("vl", "vit", "vision"))
    return meta


def vector_family(model_id: str, kind: str = "", declared: str | None = None) -> str:
    """Which vector space a model encodes into; ``""`` when it has none.

    Two embedding models with the same family produce vectors that can be
    compared with each other, so a knowledge base built with one can be appended
    to and searched with the other. Two *different files* qualify: seq512 and
    seq2048 are separately compiled static graphs of the same weights, and
    because padding is masked, the vectors agree to seven decimals
    (``docs/research/aux-dynamic-seq.md`` §7). Requiring the same model id would
    have forced a full rebuild to switch, for no gain in correctness.

    ``declared`` is the catalogue's own answer (``downloads.CATALOG``'s
    ``vector_family``). A model an operator dropped into ``models/`` by hand is
    not in the catalogue, and its family falls back to **its own id** -- the
    conservative answer: an unknown build is assumed to be its own space, which
    refuses a mix rather than silently writing vectors that cannot be compared.
    """
    if declared:
        return str(declared)
    return model_id if kind == "embedding" else ""


def same_vector_family(a: str | None, b: str | None) -> bool:
    """Whether two families may share one knowledge base.

    Empty on either side is *not* a match: a model with no family has no vectors
    to compare (and no embedding model is ever in that state, because
    ``vector_family`` gives every embedding model one).
    """
    return bool(a) and bool(b) and a == b


def catalogue_vector_family(model_id: str) -> str | None:
    """The ``vector_family`` the download catalogue declares for ``model_id``.

    Imported lazily rather than at module scope: ``models`` is loaded by every
    worker and by the management plane on a host where no download will ever
    happen, and ``downloader`` is a large module. There is no cycle to avoid --
    ``downloader`` imports nothing from here.
    """
    from .downloader import catalog_entry

    entry = catalog_entry(model_id)
    return (entry or {}).get("vector_family") or None


def kind_of_bmodel(name: str) -> str:
    """The kind of model a bmodel file is, from its name.

    The bmodel itself carries no such field, and the download name is fixed by
    whoever compiled it, so the file name is the only stable signal -- and it is
    a good one: every auxiliary build is named ``qwen3-embedding-*``,
    ``bge-reranker-*`` or ``qwen3-asr-*``. **Every chat build matches none of
    them**, which is what the fall-through says; there is deliberately no
    ``qwen3.5-*``/``qwen3.6-*`` prefix here, because there is no chat variant
    that has to be recognised to be classified -- only the auxiliary families
    need naming, and adding a chat prefix would be a rule with nothing to
    decide. (The old docstring claimed the 35B builds were recognised *as* 35B
    builds; they are not, and the dense Qwen3.5 9B/4B added in MYS-2754 are not
    either. Both fall through, which is the whole point.)
    """
    lowered = (name or "").lower()
    for prefix, kind in KIND_PREFIXES:
        if lowered.startswith(prefix):
            return kind
    return "chat"


def is_vl_embedding(name: str) -> bool:
    return Path(name).name.lower().startswith(("qwen3-vl-embedding", "qwen3_vl_embedding",
                                              "wemm-embedding", "wemm_embedding"))


#: The file that proves a config directory is usable, per kind. Every model so
#: far needed a tokenizer; OCR needs its own transform parameters and dictionary
#: instead, and has no tokenizer at all. Testing for the wrong one is not a
#: cosmetic difference: ``config_dir_for`` would fall through to a directory
#: that does not exist and the worker would be started with an empty
#: ``--config-path``.
KIND_CONFIG_MARKER: dict[str, str] = {
    "chat": "tokenizer.json",
    "embedding": "tokenizer.json",
    "rerank": "tokenizer.json",
    "asr": "tokenizer.json",
    "ocr": "ppocr.json",
    "ocr_vl": "tokenizer.json",
}


def config_marker_for(kind: str) -> str:
    """The file that makes a config directory usable for ``kind``."""
    return KIND_CONFIG_MARKER.get(kind, "tokenizer.json")


def discover_models(root: Path) -> list[ModelInfo]:
    """Scan ``root`` for model directories (a dir containing a .bmodel)."""
    out: list[ModelInfo] = []
    if not root.is_dir():
        return out
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        bmodels = [p for p in entry.rglob("*") if p.suffix in MODEL_EXTS]
        if not bmodels:
            continue
        # The first file is the one loaded. Prefer the plain dynamic build over a
        # _history_ one: the engine runs history bmodels on the fresh-prefill
        # path only, so the plain build is the tested configuration.
        bmodels.sort(key=lambda p: ("_history_" in p.name, p.name))
        size = sum(p.stat().st_size for p in entry.rglob("*") if p.is_file())
        # Prefer a top-level config dir; the demo layout is <model>/config/*.json
        has_config = (entry / "config" / "config.json").exists() or (
            entry / "config.json"
        ).exists()
        primary = bmodels[0]
        kind = kind_of_bmodel(primary.name)
        if kind == "ocr":
            # An OCR model is a directory of bmodels whose worker loads the
            # **detector** and finds the recognisers and (since layout mode) the
            # page segmenter beside it by name. Picking by sort order happens to
            # work for det-vs-rec (`-det` sorts before `-rec`) but is a
            # coincidence of spelling rather than a rule, and it breaks outright
            # once the directory also holds a `ppdoclayout-...` build, which
            # sorts before both. State the rule instead.
            detectors = [p for p in bmodels if "-det_" in p.name or "_det_" in p.name]
            if detectors:
                primary = sorted(detectors)[0]
            else:
                # No detector at all: an incomplete install. The kind must still
                # come from the OCR family rather than from whichever file sorts
                # first, or a hand-copied `anything.bmodel` beside the
                # recognisers would report `chat` and the model would be offered
                # to the wrong endpoint.
                ocr_names = [p for p in bmodels if kind_of_bmodel(p.name) == "ocr"]
                if ocr_names:
                    primary = sorted(ocr_names)[0]
        meta = read_bmodel_meta(primary)
        # The primary build goes first: ``_worker_cmdline`` loads
        # ``bmodel_files[0]``, and for OCR that has to be the detector, not
        # whichever name sorts first.
        ordered = [primary] + [p for p in bmodels if p is not primary]
        out.append(
            ModelInfo(
                model_id=entry.name,
                path=str(entry),
                display_name=entry.name,
                # The file that will actually be loaded decides, not any other
                # .bmodel lying beside it.
                kind=kind,
                size_bytes=size,
                bmodel_files=[str(p.relative_to(entry)) for p in ordered],
                has_config=has_config,
                context_length=meta["context_length"],
                supports_vision=meta["supports_vision"],
                # The catalogue says which builds share a vector space; any other
                # embedding build is its own family (see ``vector_family``).
                vector_family=vector_family(
                    entry.name, kind, catalogue_vector_family(entry.name)),
            )
        )
    return out


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


#: How long the post-load budget synchronisation may take. Not the 10 s a console
#: ``configure`` gets: this one runs while a load holds the lifecycle lock, so a
#: worker that does not answer costs the whole load, and the budget it carries is
#: the difference between publishing a model the operator can trust and one that
#: silently over-allocates. Two round trips are bounded by it (the configure and,
#: when the reply is missing, one stats read).
LOAD_BUDGET_SYNC_TIMEOUT_S = 15.0

# A model worker takes ~800 MB of host RAM (tokenizer, vision stack, buffers).
# Starting one into an exhausted system invites the OOM killer, and a worker
# killed in the middle of an NPU launch can hang the TPU until a reboot.
MIN_FREE_FOR_WORKER = 1024 * 1024 * 1024

#: Device-memory bytes an auxiliary model needs on top of its bmodel file,
#: before a load: runtime workspace and graph scratch the heap must also hold.
#: "Device memory" is NPU + VPP (docs/device-memory.md).
AUX_DEVICE_HEADROOM = 256 * 1024 * 1024
#: The name this constant had while only the NPU heap counted. Kept so an
#: out-of-tree caller does not break; new code should use the one above.
AUX_NPU_HEADROOM = AUX_DEVICE_HEADROOM

#: What one PaddleOCR-VL bmodel occupies once loaded, measured on `.157`
#: (2026-11-07, docs/device-memory.md §6): 2077 MB resident, i.e. 2.03 GiB --
#: not the 3.3 GB first estimated from the 2.27 GB file plus scratch, which
#: over-reserved by 1.2 GiB and refused loads that would have fit.
OCR_VL_DEVICE_BYTES = int(2077 * 1024 ** 2)
#: The old, over-stated figure. Kept as an alias for one release so anything
#: importing it keeps working; it now carries the measured value.
OCR_VL_NPU_BYTES = OCR_VL_DEVICE_BYTES

#: VPP heap bytes kept free for the board's multimedia stack (VPSS, the video
#: pipeline, the display path). This is not a number subtracted from a reading:
#: ``app.core.vpp_reserve`` holds a real block of VPP, so the heap statistics
#: bmrt allocates against already exclude it -- which is the only thing that
#: actually stops bmrt from taking the last byte. Overridable with
#: ``CV84X6_VPP_RESERVE_MB``; docs/device-memory.md §4 explains the default.
VPP_RESERVE_DEFAULT_BYTES = 256 * 1024 * 1024
VPP_RESERVE_ENV = "CV84X6_VPP_RESERVE_MB"

# The NPU headroom floor (MYS-2703) lives in ``mem_limit`` so the worker can read
# it without importing this module (worker.py: "a worker must not import the
# manager"); the load check here and the worker's runtime budget share it.
from .mem_limit import NPU_RESERVE_DEFAULT_BYTES, NPU_RESERVE_ENV, npu_reserve_bytes  # noqa: E402,F401

#: Model kinds whose device memory grows after the load (sessions, KV, prefix
#: cache), and therefore whose runtime budget the NPU reserve must hold back.
GROWING_KINDS = frozenset({"chat", "ocr_vl"})


@dataclass(frozen=True)
class BudgetPromise:
    """One model-configuration operation, and the device bytes it reserves.

    Two things live in this record and the second review of MYS-2801 is what
    separated them:

      * **the operation state** -- which limit a ``configure`` was trying to
        reach (``pending_limit_bytes``), which one it would leave behind
        (``previous_limit_bytes``), and how far the transaction got
        (``phase``). Every ``configure`` this service sends has one of these,
        *including* a reduction, a no-op and a change with the reserve switched
        off. Those reserve nothing but they can still be lost in flight, and
        without a record a retry cannot tell "the same request" from a different
        one and nothing can refuse a conflicting change.
      * **the bytes reserved** -- ``bytes``, the difference between the new and
        the old runtime budget for a raise, or the whole footprint for a load.
        It is **zero** for the operations above, which is why the ledger can
        hold an entry that reserves nothing; ``bytes`` never enters the state
        machine and the state machine never enters the arithmetic.

    Why a raise's promise is only the *difference*: the loaded model's existing
    budget is already committed by ``_committed_runtime_bytes``, and counting the
    whole new budget again would refuse a raise that fits.

    ``kind`` and ``model_id`` are carried for the refusal log line and for
    tests; they never enter the arithmetic.
    """

    #: ``load`` or ``raise``, for the log and for tests.
    kind: str
    model_id: str
    bytes: int
    #: Who took it. Kept in the tuple so a release can only ever remove its own
    #: entry, even when two admissions for the same model are briefly in flight.
    token: int
    #: Set when the operation's outcome on the **worker** is unknown -- the RPC
    #: timed out, the connection dropped, or the request was cancelled after the
    #: frame was written, so the management plane cannot tell "the worker
    #: refused" from "the worker applied it and the reply was lost". Such an
    #: operation must keep reserving whatever it reserved (possibly nothing) and
    #: must block further conflicting changes to that model until something
    #: confirms the two sides agree again. Never set for a plain refusal. See
    #: ``ModelManager.note_unresolved_promise``.
    unresolved: bool = False
    #: Which stored setting the operation was trying to reach, and which one it
    #: would have left behind. A delta alone cannot be recovered from: a retry
    #: has to know *what request* to repeat and *what state* to fall back to, and
    #: the settlement -- not an HTTP request that is already gone -- has to be
    #: able to finish it. Both are ``mem_limit`` values in bytes (the same figure
    #: a store entry's ``mem_limit_mb`` denotes), so a retry can compare like
    #: with like whether the operator sent a number or ``null``.
    pending_limit_bytes: int | None = None
    previous_limit_bytes: int | None = None
    #: How far the transaction got, for the log line and for the settlement.
    #: ``"sent"`` -- a ``configure`` is with the worker; ``"settling"`` -- its
    #: reply is in doubt and a read is deciding; ``"rollback_sent"`` -- the new
    #: limit was applied but could not be persisted, so the old one is being
    #: pushed back; ``"rollback_unknown"`` -- that rollback is in doubt too.
    #: Never a substitute for ``unresolved``: the phase says what was attempted,
    #: ``unresolved`` says whether the outcome is known.
    phase: str = "sent"

    @property
    def is_operation(self) -> bool:
        """Whether this entry is a model-configuration operation (not a load)."""
        return self.kind == "raise"


def mem_available_bytes() -> int | None:
    """MemAvailable from /proc/meminfo, or None where it cannot be read."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


class ModelManager:
    """Owns the worker processes.

    Loading spawns ``python -m app.engine.worker``; unloading terminates it.
    Killing the process is what actually returns the NPU heap, which is why
    models are processes and not threads.
    """

    def __init__(
        self,
        models_root: Path,
        backend_kind: str = "mock",
        max_loaded: int = 0,
        max_concurrent_per_model: int = 8,
        log_dir: Path | None = None,
        context_length_override: int | None = None,
        decode_delay_ms: float = 0.0,
        native_lib: str | None = None,
        data_root: Path | None = None,
    ) -> None:
        self.models_root = Path(models_root)
        #: The data root the whole service is installed under, when there is one.
        #: Used only to recognise *another instance of this service* (see
        #: ``adopt``); a dev checkout that passes --models-dir has none, and
        #: then the check simply cannot fire.
        self.data_root = Path(data_root) if data_root else None
        # Tokenizer/processor config used when a model dir has no config/ of its
        # own (a dfss download brings only the .bmodel). One directory per model
        # kind, because the auxiliary models do not share Qwen3.5's vocabulary:
        # ``default_config`` is the chat default, ``default_config_for(kind)``
        # the per-kind lookup.
        self.model_config_root = Path(os.environ.get(
            "CV84X6_MODEL_CONFIG_ROOT", BASE / "model-config"))
        self.default_config = Path(os.environ.get(
            "CV84X6_DEFAULT_CONFIG", BASE / "model-config" / "qwen3_5"))
        self.backend_kind = backend_kind
        self.native_lib = native_lib
        self.max_loaded = max_loaded
        self.max_concurrent_per_model = max_concurrent_per_model
        self.log_dir = Path(log_dir) if log_dir else Path("logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.context_length_override = context_length_override
        self.cache_entries = 32
        self.cache_ttl_min = 120
        self.max_queue = 16
        self.exact_tail = 64
        # Mock-backend only: without it the fake decoder finishes a request in
        # microseconds and concurrency behaviour is unobservable.
        self.decode_delay_ms = decode_delay_ms
        self._models: dict[str, ModelInfo] = {}
        self._procs: dict[str, PopenLike] = {}
        #: The worker identity each loaded model is bound to at its port, so a
        #: GET can tell "still mine" from "someone else took that port".
        self._workers: dict[str, WorkerIdentity] = {}
        # Serialises a load against an unload of the same model, and stops a
        # second caller from spawning a duplicate worker. One lock for the
        # whole lifecycle (not the old one that was held for the entire 60 s
        # load) so `GET /api/models` and the conflict checks stay responsive
        # while a model is loading.
        self._lifecycle: dict[str, asyncio.Lock] = {}
        #: The short critical section every **device-budget** admission runs in:
        #: loads and runtime raises alike (MYS-2795). Deliberately not the
        #: per-model lifecycle lock -- that one is held for the whole 60 s a load
        #: takes, so reusing it here would serialise every load against every
        #: other model's load, which the contract forbids. What is serialised is
        #: only "read the heap, check it, register the promise", which contains no
        #: await, so the lock is never contended for long.
        self._budget_lock = asyncio.Lock()
        #: Promises taken by admissions that have not finished yet, as a tuple so
        #: reading it never races a mutation (a replacement is atomic under the
        #: lock, and the object is immutable).
        #:
        #: Release is the *default*: every path that takes a promise wraps the
        #: work in ``try/finally`` and drops it, and a success drops it a moment
        #: earlier -- at the instant the commitment becomes visible in
        #: ``loaded`` (a load) or in the stored setting (a raise). That ordering
        #: is what makes an exception, a cancellation, a worker refusal or a
        #: timeout impossible to leak through: there is no branch that has to
        #: remember to release.
        self.device_promises: tuple[BudgetPromise, ...] = ()
        self._promise_token = 0
        # Set while a load is in flight, so a joiner can await the same outcome
        # instead of starting a second worker. A Future rather than the loading
        # task: the task a caller runs in is the whole HTTP request, whose
        # result is a Response, not this model's ModelInfo.
        self._loads: dict[str, asyncio.Future] = {}
        #: Called with (model_id, info) at the exact moment a worker becomes
        #: usable. The HTTP layer installs the RPC client here, because
        #: ``loaded`` is observable to every request from that instant on --
        #: registering the client after ``load()`` returns left a window in
        #: which a request saw ``loaded: true`` and no client (a 500 from
        #: /v1/chat/completions). Left None in tests that drive the manager
        #: directly.
        self.on_loaded: Callable[[str, ModelInfo], None] | None = None
        #: Awaited with the model id once an unload has been **published** as
        #: ``unloading`` and before the worker is signalled. The HTTP layer
        #: closes and forgets the RPC client here, which is what keeps the
        #: socket-then-SIGTERM order (see the unload route) while making the
        #: switch visible: from the moment this runs, every request sees
        #: ``operation: "unloading"`` instead of a loaded model whose client has
        #: just been destroyed.
        self.on_unloading: Callable[[str], Awaitable[None]] | None = None
        #: Answers "is a download still writing this model's directory?". Set by
        #: the app to the download manager; None (tests driving the manager
        #: directly) means nothing is downloading.
        self.is_downloading: Callable[[str], bool] | None = None
        #: Answers "how many requests is this worker serving right now?". Set by
        #: the app to an RPC stats call; None (tests driving the manager
        #: directly) means "cannot tell", which the idle sweep must treat as
        #: busy-looking rather than idle -- see ``_worker_is_busy``.
        self.worker_inflight: Callable[[str], Awaitable[int | None]] | None = None
        #: Answers "what does this worker's ``stats`` say right now?" -- installed
        #: by the app as an RPC call, the same seam ``worker_inflight`` uses. Read
        #: by ``resolve_budget_after_unknown`` to find out whether a ``configure``
        #: whose reply was lost actually took effect. None (tests driving the
        #: manager directly) means the question cannot be answered, which is the
        #: conservative "unknown" answer rather than a guess.
        self.worker_stats: Callable[[str], Awaitable[dict | None]] | None = None
        #: Minutes of idleness before an auxiliary model is unloaded. 0 = never.
        #: Mirrors the persisted setting; the app keeps them in step (see
        #: ``admin_api.update_settings``).
        #:
        #: Since MYS-2675 this is the **default** for models without their own
        #: entry, and it only ever applies where the global defaults apply at
        #: all (``AUX_KINDS``). ``effective_idle_minutes`` is the accessor
        #: everything else uses; this field is its fallback, not its answer.
        self.aux_idle_unload_min = 0
        #: Whether an auxiliary model is loaded on demand. The default for
        #: models without their own entry; see ``effective_auto_load``.
        self.aux_auto_load = False
        #: Per-model overrides, keyed by model id. The app installs a callable
        #: that reads ``StateStore.model_settings`` rather than a snapshot, so a
        #: ``PUT /api/models/{id}/settings`` takes effect on the next request
        #: without anything having to copy it in here. None (tests driving the
        #: manager directly) means "no model has an entry", which is exactly the
        #: pre-MYS-2675 behaviour.
        self.model_settings: Callable[[str], object] | None = None
        #: How many sessions a model's derived default memory limit budgets for.
        #: Kept in step with ``max_concurrent_per_model`` by the same setter the
        #: worker is configured with (``admin_api.update_settings``), because the
        #: default limit is a function of it.
        self.max_concurrent_for_limits = 1
        #: Static device bytes per model id, measured once per process. The
        #: bmodel cannot change under a running service (an update is refused
        #: while loaded and re-scans the model), and parsing a 20 GB file on
        #: every ``GET /api/models`` would make the console unusable.
        self._static_bytes: dict[str, int] = {}
        #: The idle-unload background task, if one is running. Owned here rather
        #: than by the app so ``unload_all`` (service shutdown) can stop it from
        #: inside the manager's own lifecycle.
        self._idle_task: asyncio.Task | None = None
        #: Seconds between sweeps. An instance attribute rather than the module
        #: constant so a test can shorten it without waiting 30 s per case; the
        #: loop reads it on every pass, so a change applies to the next one.
        self.idle_sweep_interval_s = IDLE_SWEEP_INTERVAL_S

    # -- discovery -------------------------------------------------------
    def default_config_for(self, kind: str) -> Path:
        """The bundled config directory for ``kind`` (may not exist).

        One per kind because the tokenizers differ: Qwen3.5's chat vocabulary
        cannot tokenise for an XLM-R reranker. ``CV84X6_DEFAULT_CONFIG`` still
        overrides the *chat* default, which is what a dev checkout passes.
        """
        if kind == "chat":
            return self.default_config
        sub = KIND_CONFIG_DIRS.get(kind)
        return self.model_config_root / sub if sub else self.default_config

    def config_dir_for(self, info: ModelInfo) -> Path:
        """The config directory ``info``'s worker is started with.

        A model directory that carries its own ``config/`` wins -- that is the
        vendor demo layout, and it is the authoritative copy. Only when it has
        none (a dfss download brings just the .bmodel) does the bundled per-kind
        config stand in.

        "Carries its own" means the *kind's* marker file is there, not
        ``tokenizer.json``: an OCR model has no tokenizer, and testing for one
        would fall through to a bundled directory for every kind's layout.
        """
        marker = config_marker_for(info.kind)
        own = Path(info.path) / "config"
        if (own / marker).exists():
            return own
        if info.kind == "embedding" and any(is_vl_embedding(p) for p in info.bmodel_files):
            # This is a different tokenizer/prompt contract from Qwen3-Embedding.
            # Never fall through to its bundled text-only configuration.
            family = ("wemm_embedding" if any(Path(p).name.lower().startswith(("wemm-embedding", "wemm_embedding"))
                                             for p in info.bmodel_files) else "qwen3_vl_embedding")
            bundled = self.model_config_root / family
            return bundled if (bundled / "embedding_config.json").exists() else own
        bundled = self.default_config_for(info.kind)
        if (bundled / marker).exists():
            return bundled
        return own

    def refresh(self) -> list[ModelInfo]:
        found = {m.model_id: m for m in discover_models(self.models_root)}
        for m in found.values():
            # load() falls back to the bundled config of this model's own kind.
            if (self.config_dir_for(m) / config_marker_for(m.kind)).exists():
                m.has_config = True
        # Update known models IN PLACE. load() holds a reference to its
        # ModelInfo across the 60+ s it waits for the worker; replacing the
        # object here (a GET /api/models during a load) made load() mark a
        # stale copy as loaded, so the model looked unloaded and settings never
        # reached it.
        for mid, new in found.items():
            old = self._models.get(mid)
            if old is None:
                self._models[mid] = new
                continue
            old.path = new.path
            old.display_name = new.display_name
            old.size_bytes = new.size_bytes
            old.bmodel_files = new.bmodel_files
            old.has_config = new.has_config
            if not old.loaded and old.pid is None and old.operation is None:
                # Not running: capabilities still come from the file name.
                old.kind = new.kind
                old.context_length = new.context_length
                old.supports_vision = new.supports_vision
                old.vector_family = new.vector_family
        # Forget models whose directory disappeared, but only once unloaded and
        # idle: dropping the object mid-unload would leave the operation
        # reporting on an entry nobody can see any more, and dropping a
        # conflicted one would hide the process that still holds the NPU heap.
        for mid in list(self._models):
            m = self._models[mid]
            if mid not in found and not m.loaded and m.pid is None and m.operation is None:
                del self._models[mid]
        self.reconcile()
        return self.list()

    def reconcile(self) -> list[ModelInfo]:
        """Correct ``loaded`` for workers that are no longer there.

        ``refresh`` runs on every ``GET /api/models`` and on the way into every
        load/unload, which makes it the one place guaranteed to see a worker that
        died between two requests. Nothing else would: the worker is in its own
        session with no reaper in this process, so its death is only ever
        visible as a ``/proc`` ``ESRCH``.
        """
        dropped: list[ModelInfo] = []
        for info in self._models.values():
            if not info.loaded or info.operation is not None:
                continue
            if self.still_loaded(info):
                continue
            logger.warning("worker for %s (pid %s) is gone; reporting it unloaded",
                           info.model_id, info.pid)
            self._forget(info)
            info.load_error = info.load_error or "模型进程已退出；请重新加载"
            dropped.append(info)
        return dropped

    def list(self) -> list[ModelInfo]:
        models = [self._models[k] for k in sorted(self._models)]
        for m in models:
            self._sync_downloading(m)
        return models

    def get(self, model_id: str) -> ModelInfo | None:
        info = self._models.get(model_id)
        if info is not None:
            self._sync_downloading(info)
        return info

    # -- per-model settings (MYS-2675) ------------------------------------
    #
    # Three questions, each with a per-model answer that falls back to a
    # default. The defaults are *not* the same kind of thing:
    #
    #   * idle minutes and auto-load fall back to the **global** settings,
    #     which now mean "the value for a model nobody configured";
    #   * the memory limit falls back to a figure **derived from the model
    #     itself** (static footprint + a runtime allowance), because a global
    #     byte count would be wrong for every model but one.
    #
    # The global fallback applies only to ``AUX_KINDS``. That is what keeps
    # every pre-existing installation behaving identically: an operator who
    # turned the global switches on in v0.6.27 still gets them on for exactly
    # the four auxiliary kinds, and chat stays out until somebody says so for
    # that model by name.
    def _entry(self, model_id: str):
        """``ModelSettings`` for ``model_id``, or None when it has no entry."""
        probe = self.model_settings
        return probe(model_id) if probe is not None else None

    def settings_for(self, model_id: str):
        """The stored overrides for ``model_id`` (an all-None entry if none)."""
        from .state import ModelSettings

        return self._entry(model_id) or ModelSettings()

    def effective_idle_minutes(self, info: ModelInfo) -> int:
        """Minutes of idleness before ``info`` is unloaded; 0 = never.

        The model's own value when it has one -- for **any** kind, chat
        included -- and the global default otherwise, but only for the kinds the
        global default has ever applied to.
        """
        entry = self._entry(info.model_id)
        if entry is not None and entry.idle_unload_min is not None:
            return int(entry.idle_unload_min)
        if info.kind not in AUX_KINDS:
            return 0
        return int(self.aux_idle_unload_min or 0)

    def effective_auto_load(self, info: ModelInfo) -> bool:
        """Whether an unloaded ``info`` is loaded on demand rather than refused.

        Same two-step rule as ``effective_idle_minutes``, including the
        AUX_KINDS scope for the global default. Turning this on for a chat model
        is allowed and is what the design asks for, but the interface says it
        costs tens of seconds on the first request.
        """
        entry = self._entry(info.model_id)
        if entry is not None and entry.auto_load is not None:
            return bool(entry.auto_load)
        if info.kind not in AUX_KINDS:
            return False
        return bool(self.aux_auto_load)

    def static_bytes(self, info: ModelInfo) -> int:
        """Static device footprint of ``info``: the larger of measured and declared.

        Two sources, and taking the **larger** rather than preferring either is
        the point:

          * **measured** -- the heap difference across this process's last load of
            the model (``_record_static_measurement``). This is what the device
            really allocated, and for a dynamic/history build it is the only
            honest figure: ``bmrt_get_bmodel_info`` declares 17.9 GB of dynamic
            IO for the 35B that the loaded engine never holds.
          * **declared** -- ``bmrt_get_bmodel_info`` (weights + neuron +
            instructions, no IO) or the file size. This is what the model *may*
            map, which matters for a model whose worker loads some of its files
            lazily: PP-OCRv6's worker maps the detector at startup and each
            recogniser tier on the first request of that width, so a load-time
            delta of 154 MiB describes "detector + layout" while a page of
            narrow text also needs a recogniser. Taking the smaller number there
            would let a page blow through the ceiling the operator set.

        Measured wins for the 35B (22752 > 20123), the embedding (2605 > 2265)
        and ASR (1640 > 1531); declared wins for OCR (327 > 154) and the
        reranker (1165 > 1136, by 29 MiB of instruction memory the heap reading
        does not separate). Both directions are conservative: the figure is never
        smaller than what the device showed, and never smaller than what the
        files claim.

        A directory whose files went away falls back to the recorded size.
        Cached per process; a download that replaces the bmodel clears it through
        ``forget_static_bytes``.
        """
        from . import mem_limit

        key = info.model_id
        cached = self._static_bytes.get(key)
        if cached is not None:
            return cached
        declared = int(mem_limit.estimate_static_bytes(info))
        measured = int(getattr(info, "measured_static_bytes", None) or 0)
        value = max(declared, measured)
        self._static_bytes[key] = value
        return value

    def forget_static_bytes(self, model_id: str) -> None:
        """Drop the cached figure for ``model_id`` (a download replaced it)."""
        self._static_bytes.pop(model_id, None)
        info = self._models.get(model_id)
        if info is not None:
            info.runtime_bytes = None
            info.measured_static_bytes = None

    def _device_used_bytes(self) -> int | None:
        """Device bytes in use across both heaps, or None where unreadable.

        Only used to take the load-time difference, so a host or the mock
        backend answering None simply means "no measurement this time" and the
        estimate stands. Deliberately not cached and not reported: the card-wide
        figure belongs to ``/api/stats``, and duplicating it here would give the
        console two numbers to disagree about.
        """
        from . import monitor

        try:
            return int(monitor.device_memory()["used_bytes"])
        except Exception:  # pragma: no cover - a probe must never fail a load
            return None

    def _record_static_measurement(self, info: ModelInfo, before: int | None,
                                   after: int | None) -> int | None:
        """Store the device delta a load produced, if it was observable.

        ``before`` and ``after`` are the summed device-heap readings from
        ``monitor.device_memory()`` around the spawn. The delta is this model's
        static footprint plus anything else that moved in the window -- another
        worker loading, a download, the multimedia stack -- so it is only
        trusted when it is plausible:

          * both readings exist (no device, no measurement: a host, the mock);
          * the delta is positive (a negative one means something else freed
            memory at the same time, and the number would be worse than the
            estimate);
          * the delta is not absurdly larger than the file, which would mean
            another process's allocation got attributed here. 3x + 1 GiB is a
            deliberately loose bound, and loose is the safe direction: a load
            also allocates its resident KV/state, which for a small 128k chat
            model is the same order as its weights (Qwen3.5-4B w4: 3833 MiB file,
            8651 MiB on the device -- the old 2x + 512 MiB bound discarded that,
            and the NPU reserve then counted the model at half its real size).
            Wrongly accepting a large delta only overstates the footprint, which
            refuses more; wrongly discarding one understates it, which is what
            the D7 reserve cannot afford.

        Returns the value stored, or None when the measurement was discarded.
        """
        if before is None or after is None:
            return None
        delta = int(after) - int(before)
        estimate = int(info.size_bytes or 0)
        if delta <= 0:
            return None
        if estimate and delta > 3 * estimate + (1 << 30):
            return None
        info.measured_static_bytes = delta
        # ``max``, not assignment: the new measurement replaces whichever figure
        # was there before only when it is the larger one. See ``static_bytes``
        # for why the larger of measured and declared is the answer.
        from . import mem_limit

        self._static_bytes[info.model_id] = max(
            delta, int(mem_limit.estimate_static_bytes(info)))
        return delta

    def mem_limit_default_bytes(self, info: ModelInfo) -> int:
        """The derived default limit for ``info``, in bytes.

        Passes the *manager's* static figure rather than letting ``mem_limit``
        recompute it, so the default and the load-time check use one number. See
        ``mem_limit.default_limit_bytes`` for why that consistency is required.
        """
        from . import mem_limit

        return mem_limit.default_limit_bytes(
            info, max_concurrent=self.max_concurrent_for_limits,
            static=self.static_bytes(info))

    def mem_limit_bytes(self, info: ModelInfo) -> int:
        """The limit in force for ``info``: its own, or the derived default."""
        entry = self._entry(info.model_id)
        if entry is not None and entry.mem_limit_mb is not None:
            return int(entry.mem_limit_mb) * 1024 * 1024
        return self.mem_limit_default_bytes(info)

    def mem_used_bytes(self, info: ModelInfo) -> int:
        """What ``info`` is actually holding right now.

        Static, plus the live session state and prefix cache the worker reports.
        The manager cannot read those itself -- they live in the worker process
        -- so ``memory_usage`` is installed by the app as an RPC call (the same
        seam ``worker_inflight`` uses for the idle sweep). Without it the answer
        is the static footprint, which is the floor rather than a guess: a loaded
        model holds at least its weights.

        Deliberately *not* a device reading. ``/api/stats`` already carries the
        card's used/free; this number is the model's share, and subtracting two
        device samples taken at different moments would attribute other people's
        allocations to this model.
        """
        return int(self.static_bytes(info)) + int(info.runtime_bytes or 0)

    def note_runtime_bytes(self, model_id: str, value: object) -> None:
        """Record what the worker says its live sessions + cache are holding.

        Called from the two places that poll a worker's ``stats`` (``/api/models``
        and ``/api/stats``). A missing or unparsable number leaves the previous
        value alone rather than resetting to zero: an older worker library does
        not report it, and "0 bytes" would read as "nothing running" while a
        request is in fact in flight.
        """
        info = self._models.get(model_id)
        if info is None:
            return
        try:
            info.runtime_bytes = max(0, int(value))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return

    def runtime_budget_bytes(self, info: ModelInfo) -> int:
        """Bytes ``info``'s sessions and prefix cache may share under its limit."""
        from . import mem_limit

        return mem_limit.runtime_budget_bytes(
            self.mem_limit_bytes(info), self.static_bytes(info))

    def _check_mem_limit(self, info: ModelInfo) -> None:
        """Refuse a load whose **static** footprint exceeds the model's limit.

        Called from ``_load_locked`` before anything is spawned. Static, not
        total: the runtime half is what the scheduler budgets at request time,
        and a limit set below the static footprint is the one case where the
        model could never serve anything at all -- so it is a 409 that says
        both numbers, not a load that succeeds and then refuses every request.

        A limit at or below zero cannot happen through the API (``PUT`` refuses
        it) but can through a hand-edited state file; treating it as "no limit"
        is the safe reading, since the alternative is a model no operator can
        load and no message that explains why.
        """
        limit = self.mem_limit_bytes(info)
        if limit <= 0:
            return
        static = self.static_bytes(info)
        if static <= limit:
            return
        raise ModelMemLimitError(
            f"模型 {info.model_id} 的静态占用 {static / 2**20:.0f} MiB 超过本模型内存"
            f"上限 {limit / 2**20:.0f} MiB，无法加载；请调大该模型的内存上限"
            f"（默认 {self.mem_limit_default_bytes(info) / 2**20:.0f} MiB）")


    def _sync_downloading(self, info: ModelInfo) -> bool:
        """Refresh ``info.downloading`` from the download manager and return it.

        Read on every access rather than pushed by the downloader: a job that
        ends, fails or is cancelled then unlocks the model on the next request
        with no extra bookkeeping.
        """
        probe = self.is_downloading
        info.downloading = bool(probe and probe(info.model_id))
        return info.downloading

    def require_ready(self, model_id: str) -> ModelInfo:
        """``model_id`` if it may serve a request right now, else raise.

        The single admission rule every inference route uses, so the OpenAI
        surface and the console cannot drift apart. Three refusals, all of them
        409s at the HTTP layer but three different operator situations:

          * ``KeyError`` -- no such model directory;
          * ``ModelBusy`` -- a load or unload is in flight. A model mid-load has
            ``loaded: false``, but the reverse is not the only danger: an unload
            publishes ``unloading`` *before* it destroys the RPC client, and a
            request that slips through that window would find ``loaded: true``
            and no socket;
          * ``ModelNotLoaded`` -- idle, or its last load failed.

        ``loaded`` alone is not enough, which is exactly the bug this replaces:
        the manager used to publish ``loaded`` before the capability probe, so a
        request could be dispatched to a worker whose engine was still unusable.
        """
        info = self._models.get(model_id)
        if info is None:
            raise KeyError(f"model {model_id!r} not found")
        if info.operation == LOADING:
            raise ModelBusy(f"模型 {model_id} 正在加载中，请等待加载完成后再请求")
        if info.operation == UNLOADING:
            raise ModelBusy(f"模型 {model_id} 正在卸载中，请稍后再请求")
        if not info.loaded:
            detail = f"model {model_id!r} is not loaded; load it from the web console first"
            if info.load_error:
                detail = f"{detail} (last load failed: {info.load_error})"
            raise ModelNotLoaded(detail)
        if not self.still_loaded(info):
            # The flag outlived its process: correct it here rather than routing
            # the request into a dead socket (the refresh that would have caught
            # this may not have run yet). The RPC socket's own failure is
            # reported as a 503; so is this, since the request was made against
            # a model the client had every reason to believe was up.
            self._forget(info)
            info.load_error = "模型进程已退出；请重新加载"
            raise ModelUnavailable(
                f"模型进程已退出（model {model_id!r}）；"
                "请在「模型」页卸载后重新加载")
        return info

    async def require_ready_or_load(self, model_id: str) -> ModelInfo:
        """``require_ready``, but load the model first if it is idle on disk.

        The on-demand half of the idle feature: a model that was auto-unloaded
        (or never loaded in this run) is brought back rather than refused, so a
        caller that named the model never learns it was unloaded. The model's
        own ``auto_load`` (else the global default for an auxiliary kind) turns
        it off, and a model with neither is never loaded here -- a request for
        a chat model that is down is an operator decision, not a few seconds.

        What is refused, and how, matches the manual path exactly:

          * a model mid-**unload** is ``ModelBusy`` (409) -- the same answer the
            manual load gives, because the worker is being torn down;
          * a model mid-**load** joins that load **when this model is loaded on
            demand**. That is the deduplication the design asks for: three
            requests arriving together for one unloaded model start one worker
            and all three are served from it, instead of two of them getting a
            409 while the model was in fact coming up. A load the *operator*
            started is not joined -- that request did not ask for the load, and
            waiting a minute on somebody else's click is worse than the "加载中"
            it has always reported;
          * a model whose last load **failed** is reported, not retried: the
            recorded reason is the answer, and reproducing a 35B's failure
            costs a minute;
          * a load that fails raises the same ``RuntimeError`` (409) the console
            shows, with the same NPU message;
          * ``loaded`` is only trusted after this method has read it -- the
            touch below is what keeps the sweep from unloading the model while
            the request it just revived is still running.

        Concurrent callers do not multiply the load: ``load`` joins an in-flight
        load through ``_loads``, so three simultaneous requests for the same
        unloaded model start exactly one worker.
        """
        info = self._models.get(model_id)
        if info is not None and not info.loaded:
            auto = self.effective_auto_load(info)
            if info.operation == UNLOADING:
                # The worker is being torn down. The manual load gives the same
                # 409, and joining would be joining a teardown.
                return self.require_ready(model_id)
            if info.operation != LOADING:
                # Not in flight. A recorded failure is reported rather than
                # retried: a 35B's failure costs 60 s to reproduce, and the
                # operator's next step is to read why, not to wait again -- the
                # console has a Load button for the deliberate retry.
                if info.load_error is not None:
                    return self.require_ready(model_id)
                if not auto:
                    # The refusal the caller would have got without this
                    # feature, rather than "auto load is off": the operator's
                    # situation is still "the model is not loaded".
                    raise ModelNotLoaded(
                        f"model {model_id!r} is not loaded; "
                        "按需自动加载已关闭（设置里的「辅助模型自动卸载」，"
                        "或该模型没单独开启），请在控制台加载后再试")
            elif not auto:
                # A load is in flight and this model is *not* one this service
                # loads on demand -- so the load was the operator's, and the
                # request reports the state it found rather than waiting on a
                # minute-long operation it did not start. This is the same
                # answer every inference route gave before the feature existed
                # ("加载中"), and it keeps the distinction meaningful: joining is
                # for a load the caller would have triggered itself.
                return self.require_ready(model_id)
            # ``load`` owns the rest: joining an in-flight load, the download
            # guard, the memory admission check, and a conflict with a survivor
            # this service cannot prove it owns.
            await self.load(model_id)
        return self.require_ready(model_id)

    def best_loaded(self, kind: str, preferred: str | None = None,
                    family: str | None = None) -> ModelInfo | None:
        """The loaded, settled model of ``kind`` a caller should use, or None.

        Ordering, which is the whole content of this method:

          1. ``preferred`` when it is loaded and of this kind -- the knowledge
             base records the model its vectors were built with, and reusing it
             is what keeps a search's vector space comparable;
          2. ``family``, when given and **different** from what ``preferred``
             already covers: another *loaded* build of the same vector family.
             The seq512 and seq2048 builds are interchangeable (MYS-2706), so a
             library recorded against one must keep working when only the other
             is up instead of skipping its vector stage;
          3. otherwise the most recently *loaded* model of the kind, which is the
             operator's last explicit choice (loading 1.7B after 0.6B asks for
             1.7B).

        Steps 1 and 2 are the same rule applied twice -- "the caller's space
        first, then anything in that space" -- and step 3 is the pre-existing
        behaviour, kept because a *non-embedding* caller (and an embedding caller
        with nothing recorded) has no space to prefer.

        Kept here rather than in ``app/apps/kb/models.py`` so the load-on-demand
        path and the plain resolution path rank identically: two orderings would
        pick different models for the same library depending on whether anything
        happened to be loaded.
        """
        ready = [m for m in self._models.values()
                 if m.kind == kind and m.loaded and m.operation is None
                 and not m.downloading and self.still_loaded(m)]
        if not ready:
            return None
        if preferred:
            for m in ready:
                if m.model_id == preferred:
                    return m
        if family:
            same = [m for m in ready if getattr(m, "vector_family", "") == family]
            if same:
                same.sort(key=lambda m: (m.loaded_at or 0.0), reverse=True)
                return same[0]
        ready.sort(key=lambda m: (m.loaded_at or 0.0), reverse=True)
        return ready[0]

    def candidates_for(self, kind: str, family: str | None = None,
                       preferred: str | None = None) -> list[ModelInfo]:
        """Every downloaded model of ``kind`` that could be loaded, best first.

        "Downloaded" excludes a directory whose download is still running (the
        .bmodel is truncated, and a worker mapping it fails at best) and one that
        is in conflict with a survivor this service cannot prove it owns.

        ``family`` restricts the list to one vector space. That is what makes an
        on-demand load *correct* for the knowledge base: loading "some embedding
        model" when the library needs a particular space is how a build turns
        into a mismatch the operator can only fix with a full reindex. A family
        with no candidates at all falls back to the unfiltered list -- the caller
        then resolves something and the mismatch check says so honestly, which
        beats "nothing is downloaded" for a model that is in fact on disk.

        ``preferred`` sorts that model first, so a library recorded against one
        build re-loads *that* build when both are installed and neither is up.

        Ordering is the tie-break the design asks for: ASR prefers
        ``qwen3-asr-0.6b`` (faster and smaller than the 1.7B, and both are the
        same model family), everything else prefers the most recently used, then
        the name so the answer is stable across processes.
        """
        found = [m for m in self._models.values()
                 if m.kind == kind and not m.downloading and not m.conflict]
        if family:
            same = [m for m in found
                    if getattr(m, "vector_family", "") == family or m.model_id == preferred]
            if same:
                found = same
        found.sort(key=lambda m: (
            # The caller's own model first: it is the space the library's
            # existing rows are in.
            0 if (preferred and m.model_id == preferred) else 1,
            # ASR: the 0.6B first. A name match, not a size comparison, because
            # the kind is decided from the file name and "0.6b" is in it.
            0 if (kind == "asr" and "0.6b" in m.model_id.lower()) else 1,
            -(m.last_used_at or 0.0),
            m.model_id,
        ))
        return found

    async def load_for(self, kind: str, preferred: str | None = None,
                       family: str | None = None
                       ) -> tuple[ModelInfo | None, str | None]:
        """A model of ``kind`` to use, loading one if its auto-load permits.

        Returns ``(info, None)`` on success and ``(None, reason)`` when no model
        of this kind can be used -- where ``reason`` is the sentence a skipped
        knowledge-base stage shows. The two failure shapes are deliberately
        distinct: "nothing is downloaded" is a normal, permanent answer, while
        "the load failed" carries the load's own message (NPU out of memory, or
        a worker that never became ready).

        ``family`` is the vector space the caller needs (see ``vector_family``).
        It restricts both what counts as already usable and what may be loaded:
        a library built against seq2048 must not have an idle seq512 brought up
        for it *outside* its space, and -- the reason this exists -- must have
        the seq512 build brought up when that is the family it asks for. The
        knowledge base passes the family of the model its vectors were built
        with, so "the recorded build is gone but a sibling is installed" resolves
        instead of skipping the vector stage.

        Auto-load is decided per **candidate**: this is the one path that picks
        a model itself rather than being handed one, so it takes the first
        candidate whose effective ``auto_load`` is on. Candidates that are off
        are skipped rather than aborting the stage, because an operator who
        enabled one embedding model and not another means "use the enabled one".
        """
        ready = self.best_loaded(kind, preferred, family=family)
        if ready is not None:
            return ready, None
        candidates = self.candidates_for(kind, family=family, preferred=preferred)
        if not candidates:
            return None, f"没有已下载的{_KIND_LABEL.get(kind, kind)}模型"
        allowed = [m for m in candidates if self.effective_auto_load(m)]
        if not allowed:
            return None, (f"{_KIND_LABEL.get(kind, kind)}模型未加载"
                          "（按需自动加载已关闭）")
        # The caller's model first, then the first by ``candidates_for``'s
        # ordering -- which already puts it first, so this only spells out the
        # rule for the fallback case.
        target = allowed[0]
        if preferred:
            for m in allowed:
                if m.model_id == preferred:
                    target = m
                    break
        try:
            await self.load(target.model_id)
        except (ModelBusy, KeyError) as exc:
            return None, f"{_KIND_LABEL.get(kind, kind)}模型自动加载失败：{exc}"
        except Exception as exc:
            logger.warning("on-demand load of %s failed: %s", target.model_id, exc)
            return None, (f"{_KIND_LABEL.get(kind, kind)}模型 {target.model_id} "
                          f"自动加载失败：{exc}")
        return target, None

    @property
    def loaded_count(self) -> int:
        return sum(1 for m in self._models.values() if m.loaded)

    @property
    def loaded_chat_count(self) -> int:
        """Loaded chat models -- the number ``max_loaded`` (when set) is about.

        The limit exists because each chat model claims a large, roughly fixed
        slice of device memory (a 35B takes 20 GB). Auxiliary models take orders
        of magnitude less and are admitted against measured free device memory
        instead (``_check_npu_admission``), so counting them here would make
        loading a reranker next to a chat model look like exceeding the limit.
        """
        return sum(1 for m in self._models.values() if m.loaded and m.kind == "chat")

    @property
    def loaded_heavy_count(self) -> int:
        """Loaded models admitted the way a chat model is.

        ``chat`` and ``ocr_vl`` both map a multi-gigabyte bmodel and take tens of
        seconds to load, and neither is managed by the idle machinery; they are
        the two kinds whose count a memory budget has to include.
        """
        return sum(1 for m in self._models.values()
                   if m.loaded and m.kind in ("chat", "ocr_vl"))

    # -- adoption --------------------------------------------------------
    def worker_pids(self) -> set[int]:
        """Pids this manager is currently driving (spawned or adopted)."""
        return {p.pid for p in self._procs.values()}

    def _data_root(self) -> Path | None:
        """The data root this service is installed under, when it knows one.

        Only a ``--data-root`` install has one; a dev checkout that passes
        ``--models-dir`` deliberately does not, and then the "another instance
        owns these" check cannot fire at all -- which is the honest answer, since
        without a shared root there is no way to tell two instances apart.
        """
        return self.data_root

    def _describe_worker(self, info: ModelInfo) -> WorkerIdentity | None:
        ident = self._workers.get(info.model_id)
        if ident is not None:
            return ident
        if info.pid and info.port:
            return WorkerIdentity(pid=info.pid, port=info.port)
        return None

    def still_loaded(self, info: ModelInfo) -> bool:
        """Whether ``loaded`` is still true of the real world.

        ``loaded`` is a statement about a process, so it has to be re-derived
        from that process rather than remembered: a worker that crashed, or one
        whose port was taken by another application after it died, otherwise
        keeps a model reading as loaded and a request routed into a stranger.
        """
        if not info.loaded:
            return False
        ident = self._describe_worker(info)
        if ident is None:
            return True  # nothing recorded to contradict it (a hand-built info)
        return procs.process_alive(ident.pid, ident.started)

    def _worker_cmdline(self, info: ModelInfo, port: int) -> list[str]:
        """The argv a worker for ``info`` is spawned with (see ``_load_locked``).

        Also the exact shape ``_match_survivor`` looks for, so the two cannot
        drift: a worker this service would have started is by definition one the
        discovery recognises.

        ``--kind`` is part of that identity. Adoption compares the model id and
        the models root, and a worker started for an embedding build serves a
        different RPC surface than a chat one; spelling the kind out on the
        command line means a survivor states which one it is instead of the new
        manager assuming it matches today's file name.
        """
        config_dir = self.config_dir_for(info)
        return [
            sys.executable, "-m", "app.engine.worker",
            "--model-id", info.model_id,
            "--port", str(port),
            "--backend", self.backend_kind,
            "--kind", info.kind,
            "--model-path",
            str(Path(info.path) / info.bmodel_files[0]) if info.bmodel_files else "",
            "--config-path", str(config_dir),
        ]

    def _match_survivor(self, info: ModelInfo, found: list[procs.ProcInfo]) -> procs.ProcInfo | None:
        """The one live process that is provably a worker for ``info``, if any.

        Every clause is a rejection rule, because the cost of a false positive is
        signalling a process this service did not start:

          * argv's first two arguments are exactly ``-m app.engine.worker``. Not
            "somewhere in the command line": a shell, a ``grep`` or an editor can
            contain that string, and only a process *run as* the module is a
            candidate;
          * its ``--model-id`` is this model's;
          * when it states a ``--kind``, that kind is this model's too. A
            survivor from before the auxiliary models existed has no
            ``--kind`` at all and is a chat worker, which is what it is taken
            to be;
          * the model path it was given is inside this manager's models root, so
            a worker belonging to another checkout with another data root is not
            mistaken for ours;
          * its working directory is this service's own tree (the one cwd
            ``_load_locked`` starts it in);
          * its executable is a Python interpreter, not merely a process whose
            argv starts with one.

        More than one match is itself a conflict: we cannot tell which one holds
        the NPU heap, and picking one would leave the other unmanaged.
        """
        matches: list[procs.ProcInfo] = []
        for cand in found:
            argv = cand.argv
            if argv[1:3] != ["-m", "app.engine.worker"]:
                continue
            if procs.arg_value(argv, "--model-id") != info.model_id:
                continue
            stated = procs.arg_value(argv, "--kind")
            if stated is not None and stated != info.kind:
                # It serves a different RPC surface (embed/rerank vs generate).
                # Adopting it would route chat requests into a worker that has
                # no generate op, so it is not this model's worker at all.
                continue
            model_path = procs.arg_value(argv, "--model-path") or ""
            if not procs.is_under(model_path, self.models_root):
                continue
            if not procs.is_under(cand.cwd, BASE):
                continue
            if not procs.looks_like_python(cand.exe):
                continue
            matches.append(cand)
        if not matches:
            return None
        if len(matches) > 1:
            pids = ", ".join(str(m.pid) for m in matches)
            raise ModelConflict(
                f"模型 {info.model_id} 有多个存活 worker 进程（pid {pids}），"
                "无法安全判断哪个持有 NPU 内存；请人工确认后停止多余的进程")
        return matches[0]

    async def adopt(self) -> list[ModelInfo]:
        """Reattach to workers a previous run of this service left behind.

        Returns the models that are now loaded. A survivor that answers its
        health handshake is adopted as a full worker: ``loaded``, its pid and
        port, an ``AdoptedProcess`` in ``_procs`` so unload drives it through the
        normal path, and ``on_loaded`` fired so the RPC client exists before any
        request can route to it.

        A survivor that does not answer is recorded as a **conflict**: the model
        reports neither loaded nor idle, ``load`` refuses with ``ModelConflict``
        instead of spawning a second process, and ``unload`` terminates exactly
        that pid (SIGTERM -- never SIGKILL: it may be mid-prefill).

        Discovery is skipped entirely when this manager already owns processes,
        so a test or a re-entrant call cannot adopt a worker it spawned itself.

        It is also refused when **another service instance serving this data
        root is still alive**: those workers have a living owner, and two
        managers driving one process would fight over it (see
        ``procs.service_instances``). That case is reported as a conflict on
        every model that has a candidate, never adopted.
        """
        if self._procs:
            return self.list()
        if not self._models:
            self.refresh()
        # A second instance on the same data root owns these workers. Say so and
        # adopt nothing: the point of takeover is to take over from a *dead*
        # owner, and taking over from a live one would leave two consoles
        # driving one process.
        root = self._data_root()
        try:
            rivals = procs.service_instances(root) if root else []
        except Exception:  # pragma: no cover - /proc trouble means "cannot tell"
            rivals = []
        found = procs.scan_processes()
        if rivals:
            pids = ", ".join(str(r.pid) for r in rivals)
            for info in self.list():
                if info.loaded or info.conflict:
                    continue
                if self._match_survivor(info, found) is None:
                    continue
                info.conflict = (
                    f"另一个本服务实例（pid {pids}）仍在使用同一个数据目录，"
                    f"模型 {info.model_id} 的 worker 归它管理；不会接管也不会重复启动")
                logger.error("%s", info.conflict)
            return []
        adopted: list[ModelInfo] = []
        for info in self.list():
            if info.loaded or info.conflict:
                continue
            try:
                cand = self._match_survivor(info, found)
            except ModelConflict as exc:
                info.conflict = str(exc)
                info.pid = None
                logger.error("%s", exc)
                continue
            if cand is None:
                continue
            port = procs.arg_value(cand.argv, "--port")
            port = int(port) if port and port.isdigit() else None
            if port is None:
                info.conflict = (
                    f"pid {cand.pid} 看起来是 {info.model_id} 的 worker，但命令行里没有合法端口，"
                    "无法确认可服务；请人工处理")
                info.pid = cand.pid
                self._remember_suspect(info, cand, None)
                logger.error("model %s: %s", info.model_id, info.conflict)
                continue
            # Publish "loading" while the survivor is probed, exactly as a fresh
            # load does. Adoption is not instant (two round trips to a process
            # that may be wedged), and a model that reads idle in that window
            # could be loaded -- spawning a second worker next to this one.
            self._begin(info, LOADING)
            try:
                healthy = await self._probe_worker(port, info.model_id)
                if not healthy:
                    info.conflict = (
                        f"pid {cand.pid} 是 {info.model_id} 的 worker，但端口 {port} 没有通过"
                        "健康检查（可能仍在加载或已卡死）；不会重复启动，可点「卸载」结束它")
                    info.pid = cand.pid
                    self._remember_suspect(info, cand, port)
                    logger.warning("model %s: %s", info.model_id, info.conflict)
                    continue
                # Read the survivor's capabilities before publishing `loaded`:
                # a restart must not serve with file-name guesses while the
                # worker knows better, and a worker that cannot answer stats is
                # not initialised enough to take over.
                try:
                    await self._probe_capabilities(port, info)
                except Exception as exc:
                    info.conflict = (
                        f"pid {cand.pid} 是 {info.model_id} 的 worker，但能力探测失败"
                        f"（{type(exc).__name__}: {exc}）；可能仍在初始化，"
                        "不会重复启动，可点「卸载」结束它")
                    info.pid = cand.pid
                    self._remember_suspect(info, cand, port)
                    logger.warning("model %s: %s", info.model_id, info.conflict)
                    continue
                self._register_adopted(info, cand, port)
            finally:
                self._end(info)
            adopted.append(info)
            logger.info("adopted worker for %s: pid %d on port %d",
                        info.model_id, cand.pid, port)
        return adopted

    def _remember_suspect(self, info: ModelInfo, cand: procs.ProcInfo,
                          port: int | None) -> None:
        """Record the generation of a survivor we refuse to adopt.

        Its pid is what an operator (and ``unload``) will signal, so its start
        time is kept: a pid recycled between discovery and the click would
        otherwise make the stop hit a stranger. ``port`` is None when the
        command line did not name a usable one, which is itself a reason not to
        believe the process can serve.
        """
        self._workers[info.model_id] = WorkerIdentity(
            pid=cand.pid, port=port or 0, started=cand.start_time)

    def _register_adopted(self, info: ModelInfo, cand: procs.ProcInfo, port: int) -> None:
        info.loaded = True
        info.adopted = True
        info.pid = cand.pid
        info.port = port
        info.load_error = None
        info.conflict = None
        info.loaded_at = info.loaded_at or time.time()
        # The idle clock starts at adoption. A worker inherited from a previous
        # run has no recorded use, and "no recorded use" must not mean "never
        # unloaded" -- that is how an adopted embedding model outlives every
        # request for the rest of the process's life.
        self.touch(info.model_id)
        self._workers[info.model_id] = WorkerIdentity(
            pid=cand.pid, port=port, started=cand.start_time)
        self._procs[info.model_id] = procs.AdoptedProcess(
            cand.pid, allow_kill=False, start_time=cand.start_time)
        if self.on_loaded is not None:
            self.on_loaded(info.model_id, info)

    async def _probe_worker(self, port: int, model_id: str) -> bool:
        """Whether a survivor on ``port`` has *finished* initialising as this model.

        A listening socket only proves a process opened it. Adoption needs more:
        the worker must name this model (the reply is what distinguishes our
        worker from a worker for another model that happens to hold the port, or
        from any other JSON-lines service), must not disclaim being loaded, and
        must answer ``stats`` -- a live scheduler, not just an accept loop. A
        worker that is still mapping weights answers nothing and is a conflict,
        which is the behaviour the takeover contract promises.
        """
        from .client import WorkerClient

        client = WorkerClient(port)
        try:
            await asyncio.wait_for(client.connect(), timeout=2.0)
            health = await asyncio.wait_for(client.health(), timeout=5.0)
            if not isinstance(health, dict) or not health.get("ok"):
                return False
            if health.get("model") not in (None, model_id):
                return False
            if health.get("loaded") is False:
                # Explicitly not ready: an unfinished initialisation. Do not
                # adopt it; the caller records a conflict.
                return False
            stats = await asyncio.wait_for(client.stats(), timeout=5.0)
            return isinstance(stats, dict) and stats.get("op") == "stats"
        except (OSError, asyncio.TimeoutError, ValueError):
            return False
        except Exception:  # a WorkerError from a stranger on the port
            return False
        finally:
            with contextlib.suppress(Exception):
                await client.close()

    # -- lifecycle -------------------------------------------------------
    def lock_for(self, model_id: str) -> asyncio.Lock:
        """The per-model lifecycle lock, created on first use.

        One lock per model rather than one for the manager: two models may load
        at the same time (``max_loaded`` is 2), and holding a manager-wide lock
        across a 60 s load would serialise them -- and freeze the conflict
        checks for every other model while it ran.
        """
        lock = self._lifecycle.get(model_id)
        if lock is None:
            lock = asyncio.Lock()
            self._lifecycle[model_id] = lock
        return lock

    def _begin(self, info: ModelInfo, operation: ModelOperation) -> None:
        info.operation = operation
        info.operation_since = time.time()

    def _end(self, info: ModelInfo) -> None:
        info.operation = None
        info.operation_since = None

    async def load(self, model_id: str) -> ModelInfo:
        """Load ``model_id``, or join the load already in flight for it.

        The operation field is published *before* the worker is spawned, so a
        console that reloads the page during the 60+ s a 35B takes sees
        ``operation: "loading"`` with ``loaded: false`` -- the same answer for
        every client, and the one that keeps the buttons disabled.

        Concurrency rules, all observable through ``GET /api/models``:
          * a second load of a model already loading awaits the first one
            instead of spawning a duplicate worker;
          * a load of a loaded model is a no-op (idempotent 200);
          * an unload racing a load is refused with ModelBusy (HTTP 409).
        """
        info = self._models.get(model_id)
        if info is None:
            raise KeyError(f"model {model_id!r} not found on disk")
        if info.loaded and self.still_loaded(info):
            # Idempotent: nothing to do, no second worker. The touch is still
            # right -- the caller asked for this model now, and "loaded already"
            # is not a reason to unload it out from under them a minute later.
            self.touch(model_id)
            info.unloaded_reason = None
            return info
        if info.loaded:
            # The worker behind ``loaded`` is gone. Saying "already loaded" would
            # route requests into a dead socket, so the state is corrected first
            # and the load carries on as a fresh one.
            self._forget(info)
        if self._sync_downloading(info):
            # The .bmodel is still being written. A worker mapping a truncated
            # file fails at best; at worst it hands the NPU garbage weights.
            raise ModelBusy(f"模型 {model_id} 正在下载，下载完成后才能加载")
        if info.conflict:
            # A worker this service cannot prove it can use already owns this
            # model. Starting a second one is the failure mode this whole path
            # exists to prevent.
            raise ModelConflict(info.conflict)
        if info.operation == UNLOADING:
            # Checked before taking the lock: an unload can hold it for the
            # 120 s SIGTERM grace, and a caller should be told immediately
            # rather than after a two-minute wait.
            raise ModelBusy(f"模型 {model_id} 正在卸载，请稍后再加载")

        # Join a load already in flight instead of queueing behind it and then
        # spawning a second worker: the joiner gets the same ModelInfo, or the
        # same error the first caller saw.
        pending = self._loads.get(model_id)
        if pending is not None and not pending.done():
            return await asyncio.shield(pending)

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._loads[model_id] = future
        # `shield` only protects the inner awaitable; cancelling this caller
        # (a browser that closed the tab) must not abort a load another client
        # is still waiting on, so the future is resolved by the try/finally.
        try:
            async with self.lock_for(model_id):
                # Re-check under the lock: another request may have finished
                # (or started) while we waited.
                if info.loaded and self.still_loaded(info):
                    result = info
                else:
                    if info.loaded:
                        self._forget(info)
                    if info.conflict:
                        raise ModelConflict(info.conflict)
                    if info.operation == UNLOADING:
                        raise ModelBusy(f"模型 {model_id} 正在卸载，请稍后再加载")
                    # 0 (the default) means no count limit: chat models are
                    # bounded by the NPU heap itself, and the operator decides.
                    if self.max_loaded and self.loaded_heavy_count >= self.max_loaded:
                        raise ModelBusy(
                            f"已达到同时在线的大语言模型上限（{self.max_loaded} 个），"
                            "请先卸载一个再加载"
                        )
                    result = await self._load_locked(info)
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
            # Nobody may be listening (the caller itself is unwinding); the
            # exception is retrieved below to keep asyncio quiet.
            future.exception()
            raise
        finally:
            self._loads.pop(model_id, None)
        if not future.done():
            future.set_result(result)
        return result

    def _fail_load(self, info: ModelInfo, message: str) -> None:
        """Put a model back to idle after a failed load, with the reason kept.

        Every clause is load-bearing for the console: ``loaded`` false so
        requests cannot route into a half-initialised worker, ``load_error``
        set so the operator sees why, and pid/port cleared so the next attempt
        is allowed. The ``operation`` is ended by the caller's ``finally``.
        """
        info.loaded = False
        info.loaded_at = None
        info.port = None
        info.load_error = message

    async def _probe_capabilities(self, port: int, info: ModelInfo,
                                  settle_timeout: float = 30.0) -> None:
        """Confirm the worker finished initialising and read its capabilities.

        Raises on anything less than a fully initialised worker: a socket that
        accepts but does not answer, a ``health`` that does not name this model,
        a ``health`` that reports itself not loaded, or a ``stats`` that fails.
        The caller treats that as a load failure -- which is the point. The
        previous version swallowed every exception here and kept the optimistic
        file-name capabilities, so a model could read as loaded while its
        engine was still unusable, and requests went into it.

        Connection failures are retried until ``settle_timeout``: "the process
        answered once" and "the port is connectable" are separate facts (the
        readiness poll uses its own short-lived connection), and a listener that
        is not accepting yet is a not-ready worker, not a broken one. Everything
        else -- a wrong model id, a not-loaded health, a stats that errors --
        fails immediately, because waiting cannot fix any of it.

        A *later* stats failure is not this: once a model is ready, one slow
        ``stats`` call must not take it out of service (the console reads stats
        on every poll). This is the initialisation gate only.
        """
        from .client import WorkerClient

        deadline = time.monotonic() + settle_timeout
        while True:
            probe = WorkerClient(port)
            try:
                await asyncio.wait_for(probe.connect(), timeout=5)
            except (OSError, asyncio.TimeoutError) as exc:
                with contextlib.suppress(Exception):
                    await probe.close()
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"worker 的端口 {port} 在 {int(settle_timeout)} 秒内无法连接（{exc}）") from exc
                await asyncio.sleep(0.2)
                continue
            try:
                # stats first: it is what proves the scheduler loop is up (the
                # reply is assembled from live scheduler state, not a constant).
                caps = await asyncio.wait_for(probe.stats(), timeout=10)
                if not isinstance(caps, dict) or caps.get("op") != "stats":
                    raise RuntimeError(f"worker 的 stats 回复不是有效对象：{caps!r}")
                health = await asyncio.wait_for(probe.health(), timeout=5)
                if not isinstance(health, dict):
                    raise RuntimeError(f"worker 的 health 回复不是有效对象：{health!r}")
                if health.get("model") not in (None, info.model_id):
                    raise RuntimeError(
                        f"端口 {port} 上的 worker 属于模型 {health.get('model')!r}，"
                        f"不是 {info.model_id!r}")
                if not health.get("ok") or health.get("loaded") is False:
                    raise RuntimeError(
                        f"worker 的 health 未报告就绪：{health!r}")
                # Only now are the values trustworthy enough to publish.
                if "supports_sampling" in caps:
                    info.supports_sampling = bool(caps["supports_sampling"])
                # Vision and context come from the loaded graphs; the filename
                # heuristic in discover_models cannot tell (35B has a vit graph
                # but no "vl" in its name).
                if "supports_vision" in health:
                    info.supports_vision = bool(health["supports_vision"])
                if health.get("context_length"):
                    info.context_length = int(health["context_length"])
                # The worker's own kind outranks the file-name guess: it was
                # started with --kind, so it knows which surface it serves.
                stated = health.get("kind")
                if stated in KINDS:
                    info.kind = stated
                if health.get("hidden_size"):
                    info.hidden_size = int(health["hidden_size"])
                return
            finally:
                with contextlib.suppress(Exception):
                    await probe.close()

    def _npu_oom_hint(self, model_id: str) -> str | None:
        """A plain reason when the worker's last load died allocating NPU memory.

        With no count limit on chat models, "the NPU is full" is the expected
        way a too-big load fails, and ``bm_alloc_gmem failed`` in a log is not
        something an operator should have to read to find that out.
        """
        path = self.log_dir / f"worker-{model_id}.log"
        try:
            with open(path, "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - 16384))
                tail = fh.read().decode("utf-8", "replace")
        except OSError:
            return None
        if "bm_alloc_gmem" in tail or "BM_ERR_NOMEM" in tail:
            return "设备内存不足，加载失败：请先在「模型」页卸载其他模型，再加载这个模型"
        return None

    def _check_npu_admission(self, info: ModelInfo) -> None:
        """Refuse an auxiliary model device memory cannot hold.

        "Device memory" is both ion carveout heaps, NPU + VPP: bmrt allocates
        from either (`m_neuron_heap_mask` defaults to 7, which bmlib maps to
        heaps 0 and 1 on this chip), and it spills into VPP by itself when NPU
        runs out -- measured on `.157`, docs/device-memory.md §2-3. So the
        question is not "does the NPU heap have room" but "do the two heaps
        together have room, and can each single block fit in one of them".

        Chat models have no such check: their footprint is set by the bmodel's
        context (the 128k 35B takes ~22.8 GiB once loaded) rather than its file
        size, so a file-size pre-check would either refuse the build this
        service exists to serve or admit one that cannot fit. A chat load that
        runs out of memory fails in the worker and is reported as such
        (``_npu_oom_hint``). Auxiliary models are admitted on top of whatever is
        loaded, so the only honest guard is the device's own free memory -- a
        reranker suddenly loaded next to a 128k 35B fails inside bmrt with an
        opaque ``bm_alloc_gmem failed``, or worse, evicts nothing and reports a
        bogus load. Checking here turns that into a 409 that names the numbers.

        VPP is not entirely available: ``app.core.vpp_reserve`` holds a block of
        it (256 MiB by default) for the multimedia stack, so the heap statistics
        read here already exclude that block -- no subtraction happens in this
        function, and what it compares against is what bmrt will actually get.
        On a baseboard without a video pipeline the reserve is still the right
        default: it costs VPP capacity and says so in the refusal message, while
        under-reserving breaks a camera instead, far from the load that did it.

        Skipped when no heap can be read (host tests, mock backend, a board
        whose ion node is root-only and whose bmlib is absent): there is no
        device to ask, and inventing a refusal would break every dev checkout.
        """
        if info.kind == "chat":
            return
        if info.kind == "ocr_vl":
            # 2.03 GiB resident, measured on `.157` (docs/device-memory.md §6).
            # The auxiliary file-size rule below understates it: the file is
            # 2.27 GB and the KV cache, workspace and graph scratch take the
            # rest, so it is admitted on a measured figure rather than on a
            # number derived from `ls`.
            bmodel_bytes = sum(
                (Path(info.path) / name).stat().st_size
                for name in info.bmodel_files
                if (Path(info.path) / name).exists())
            resident = OCR_VL_DEVICE_BYTES
            need = resident + AUX_DEVICE_HEADROOM
        else:
            # Every bmodel the worker may map, not just the first: an OCR model
            # is four files (det + three rec tiers) and the worker loads the rec
            # tiers lazily, so admitting it on the det file alone would
            # understate the ask by two thirds and turn the refusal into a
            # `bm_alloc_gmem failed` part-way through the first request.
            bmodel_bytes = 0
            for name in info.bmodel_files:
                path = Path(info.path) / name
                if path.exists():
                    bmodel_bytes += path.stat().st_size
            need = bmodel_bytes + AUX_DEVICE_HEADROOM
        # The largest single block this load is known to ask for. bmrt splits a
        # bmodel into coeff/neuron/io allocations, so the true figure is smaller
        # than the total, but a block can never span heaps: admitting on the sum
        # alone would allow a 3 GiB model onto a board with 1.5 GiB free in each
        # heap, which fails at load time with the opaque bmrt error.
        largest_block = max(bmodel_bytes, resident if info.kind == "ocr_vl" else 0)

        from . import monitor

        device = monitor.device_memory()
        if not device["heaps"]:
            return
        # No subtraction: the reserve is a block someone holds, so `free_bytes`
        # here is already what bmrt can allocate (see the docstring).
        usable = {h["name"]: h["free_bytes"] for h in device["heaps"]}
        free = sum(usable.values())
        max_block = max(usable.values(), default=0)

        def where() -> str:
            return "，".join(f"{name.upper()} 剩 {size / 2**30:.1f} GiB"
                            for name, size in usable.items())

        if free < need:
            raise DeviceMemoryError(
                f"设备内存不足：{info.model_id} 需要 "
                + (f"{resident / 2**30:.1f} GiB（装载后常驻）"
                   if info.kind == "ocr_vl" else
                   f"{bmodel_bytes / 2**30:.1f} GiB（模型文件）")
                + f" + {AUX_DEVICE_HEADROOM / 2**30:.1f} GiB（运行余量）= "
                f"{need / 2**30:.1f} GiB，当前设备内存只剩 {free / 2**30:.1f} GiB"
                f"（{where()}）；请先卸载其他模型再加载")
        if info.kind != "ocr_vl" and max_block < largest_block:
            raise DeviceMemoryError(
                f"设备内存不足：{info.model_id} 的模型文件 {largest_block / 2**30:.1f} GiB "
                "需要一块连续内存，而单个堆的最大空闲块只有 "
                f"{max_block / 2**30:.1f} GiB（{where()}）；"
                "单次分配不能跨堆，请先卸载其他模型再加载")

    def _check_npu_reserve(self, info: ModelInfo) -> None:
        """Refuse a load that would leave the NPU heap below the wedge floor.

        Separate from ``_check_npu_admission`` on purpose, in both what it asks
        and whom it applies to.

        * **What:** that function asks "does this model fit in what is free". This
          one asks "how much is left *after* it fits" -- and refuses if that is
          less than ``npu_reserve_bytes()``. A configuration can pass the first
          check comfortably and still wedge, which is exactly what the 6-model
          board did: everything fit into 30440 MiB of 30720, and the board still
          died in two minutes (MYS-2703). "Fits" and "survives" are different
          questions.
        * **Whom:** ``_check_npu_admission`` returns early for chat, because a
          chat bmodel's footprint cannot be derived from its file size. This
          check needs the incoming model's footprint too -- but for chat that
          figure already exists as ``static_bytes`` (measured across the last
          load, which is how the 35B's 22752 MiB is known), so the same rule
          applies to chat, which is where the failure was actually observed.

        The floor is a property of the chip, not of the workload: with the load
        held constant (five models, ``chat`` x2, a ballast taking the difference)
        the board wedges at 280 MiB and 512 MiB free and runs clean at 640 MiB
        and 1024 MiB. See ``NPU_RESERVE_DEFAULT_BYTES`` for the table.

        Only the **NPU** heap is compared. VPP is not where this failure lives:
        in every MYS-2693 capture VPP sat at its 256 MiB startup reserve, never
        holding a model, while the NPU heap was at 30440/30720.

        Skipped when the heap cannot be read (host tests, mock backend), when the
        operator set the floor to 0, or when this model's own footprint is
        unknown (a build never loaded here, with no declaration to fall back on):
        there is no number to subtract, and inventing a refusal would break every
        dev checkout.
        """
        reserve = npu_reserve_bytes()
        if reserve <= 0:
            return
        # Only the heap named ``npu`` is the subject; a reading that lists some
        # other heap must not be mistaken for "zero NPU free".
        free = self._npu_free_bytes()
        if free is None:
            return
        # The footprint is what this load will take out of the free figure. Using
        # the free figure alone would ask "is there room right now", which is the
        # question `_check_npu_admission` already answers -- and on the board it
        # answered "yes" for every one of the six models that then wedged it.
        #
        # The footprint is the model's *limit* (static + runtime budget), not its
        # static figure: the 35B's sessions and prefix cache grow after the load
        # by up to its runtime budget (462 MiB at the default limit), and a floor
        # checked only against static would let a board pass at 1024 MiB free
        # and then drift to ~560 MiB -- inside the measured wedge band (512 MiB
        # wedged, 640 MiB was clean).
        #
        # Only the kinds that *grow* after loading count their runtime budget:
        # chat (sessions + prefix cache) and, conservatively, ocr_vl. The native
        # auxiliary engines (embedding, rerank, asr, ocr) allocate everything at
        # load and never grow -- measured: embedding holds the same heap after
        # requests as right after load -- so their "runtime budget" is a
        # configuration figure, not future allocation. Counting it refused OCR
        # on the RC board with 2.5 GiB free (35B + embedding + rerank + asr).
        #
        # ``_declared_claim_bytes`` is the one place that rule lives, so the
        # figure this check subtracts and the claim the admission registers
        # (``_load_locked``) can never describe different memory.
        footprint = self._declared_claim_bytes(info)
        # For the same reason, what the growing models already loaded may still
        # take is already spoken for: their remaining runtime budget is not free
        # for this load, even though the device reports it as free now.
        # ``_headroom_left`` subtracts that sum and the in-flight promises; this
        # check passes its own claim so the two paths share one arithmetic
        # (MYS-2795).
        left = self._headroom_left(free, int(footprint))
        if left >= reserve:
            return
        loaded = ", ".join(sorted(m.model_id for m in self._models.values() if m.loaded))
        raise DeviceMemoryError(
            f"NPU 显存余量不足：加载 {info.model_id}（约 "
            f"{footprint / 2**20:.0f} MiB）后 NPU 只剩 {left / 2**20:.0f} MiB，"
            f"低于安全下限 {reserve / 2**20:.0f} MiB。"
            f"NPU 堆几乎占满时 TPU 会卡死（驱动停止收完成中断，只能重启板子），"
            f"所以这个下限是硬性的。"
            + (f"当前已加载：{loaded}。" if loaded else "")
            + "请先卸载一个模型再加载，或调低 CV84X6_NPU_RESERVE_MB（0 = 关闭此检查）")

    # -- device budget admission (MYS-2795) ------------------------------
    #
    # One arithmetic, three callers: a load, a runtime raise, and the read-only
    # check above (which now delegates so the two cannot drift). The question all
    # three ask is
    #
    #     NPU free now − (what is already promised) − (what the operation will
    #     take that is not already counted) − (the floor) >= 0
    #
    # where "already promised" is the loaded growing models' remaining runtime
    # budgets *plus* the admissions in flight (``device_promises``). It lives in
    # one place because the defect this replaces was a second, weaker copy of it
    # on the settings path.

    def _committed_runtime_bytes(self) -> int:
        """Runtime budget already spoken for by loaded growing models.

        Conservative on purpose: the whole budget is subtracted, not the part the
        model has not used yet. ``runtime_bytes`` is a per-token *estimate* -- it
        excludes park rounding and the old-plus-new buffer peak of a growth -- so
        crediting the "used" part back would admit an operation against memory the
        engine may already hold. A raise that physically fits may therefore be
        refused; docs/model-settings.md tells the operator to unload first.

        **Every loaded growing model counts, the one asking included.** Its budget
        is a promise the device reading cannot vouch for: ``free`` is what bmrt
        reports *now*, and a model whose sessions have not grown yet still may.
        Leaving the asker out and subtracting only the increase spends the same
        bytes twice -- the defect the first review of this card caught, where
        400 -> 1000 MiB was admitted against 1624 MiB free with a 1024 MiB floor
        and would have left 624. The boundary is therefore
        ``free - all growing budgets - delta >= reserve``, i.e. 2024 MiB free for
        that raise, not 1624.

        A load never has this problem: ``load`` calls ``_forget`` first when the
        previous worker is gone, so the incoming model is not in this sum at all,
        and its whole footprint is the claim instead.
        """
        total = 0
        for m in self._models.values():
            if m.loaded and m.kind in GROWING_KINDS:
                total += self.runtime_budget_bytes(m)
        return total

    def _headroom_left(self, npu_free_bytes: int, claim_bytes: int) -> int:
        """Bytes the NPU heap would have left after ``claim_bytes`` is taken.

        ``claim_bytes`` is the operation's **new** claim and nothing more: the
        whole declared footprint for a load (``_declared_claim_bytes``), or only
        the increase for a raise -- because for a raise the model's *existing*
        budget is already inside ``_committed_runtime_bytes``, and for a load the
        model is not loaded yet, so it is not.

        Two further subtractions, both of which the defect this replaces was
        missing:

        * ``_committed_runtime_bytes`` -- what loaded growing models may still
          allocate, which the device reports as free today;
        * ``device_promises`` -- admissions that have been granted but not yet
          realised (a load mid-spawn, a raise mid-handshake). This is also what
          makes a **pending auxiliary load** visible: it has no runtime budget to
          commit afterwards, but it needs its footprint reserved before the spawn
          all the same.
        """
        pending = sum(p.bytes for p in self.device_promises)
        return (int(npu_free_bytes) - int(claim_bytes)
                - self._committed_runtime_bytes() - pending)

    def _npu_free_bytes(self) -> int | None:
        """The NPU heap's free figure, or None where no reading exists."""
        from . import monitor

        heaps = {h["name"]: h for h in monitor.device_memory().get("heaps", [])}
        npu = heaps.get("npu")
        return None if npu is None else int(npu["free_bytes"])

    def _reading_is_required(self) -> bool:
        """Whether an unreadable heap must refuse rather than be ignored.

        A device backend has a heap; if it cannot be read, the management plane
        knows nothing about the card and must not promise memory on it. The mock
        backend is a dev checkout or this test suite -- it has no device to be
        wrong about, and refusing there would make every laptop and CI run
        unusable. Same distinction ``_check_npu_admission`` draws, but inverted in
        its consequence: a load may proceed without a reading (the engine will
        refuse what does not fit), a *raise* hands out memory in advance.
        """
        return self.backend_kind != "mock"

    def _take_budget_promise(self, kind: str, model_id: str, nbytes: int,
                             *, pending_limit_bytes: int | None = None,
                             previous_limit_bytes: int | None = None) -> BudgetPromise:
        """Register a promise. Caller holds ``_budget_lock``."""
        self._promise_token += 1
        promise = BudgetPromise(kind=kind, model_id=model_id,
                                bytes=int(nbytes), token=self._promise_token,
                                pending_limit_bytes=pending_limit_bytes,
                                previous_limit_bytes=previous_limit_bytes)
        self.device_promises = self.device_promises + (promise,)
        return promise

    def release_budget_promise(self, promise: BudgetPromise | None) -> None:
        """Drop a promise. Idempotent, so a double release is harmless.

        Called from ``finally`` blocks, which means it can run while a cancelled
        task is unwinding -- so it must not await. Replacing the tuple is a single
        atomic assignment, so a concurrent reader in ``_headroom_left`` sees either
        the old or the new ledger and never a half-edited one.

        **Only call this when the claim is really gone.** For a load that is a
        plain fact (the worker's memory went back with the process). For a limit
        change it is not: a ``configure`` that timed out or lost its connection
        may still have been applied, and dropping the claim then would report
        "refused, nothing changed" while the worker runs at the new budget. That
        case goes through ``note_unresolved_promise`` instead.
        """
        if promise is None:
            return
        self.device_promises = tuple(
            p for p in self.device_promises if p.token != promise.token)

    def note_unresolved_promise(self, promise: BudgetPromise,
                                *,
                                pending_limit_bytes: int | None = None,
                                previous_limit_bytes: int | None = None,
                                phase: str | None = None,
                                reserved_bytes: int | None = None
                                ) -> BudgetPromise:
        """Mark an operation as *possibly applied on the worker* and keep its bytes.

        The third review finding. ``PUT`` used to wrap its ``configure`` in a
        ``finally`` that released the claim on every exit path, so a timeout or a
        dropped connection -- where the worker may well have applied the new
        budget -- produced "409, nothing changed" with the old setting stored, the
        worker at the new budget, and an empty ledger. Three claims about the
        world, all wrong, and the memory the worker is really holding free for the
        next admission.

        Keeping the entry is the conservative answer: whatever it reserved stays
        reserved against every later admission -- which for a reduction, a no-op
        or a reserve-off change is **nothing**, and that is fine, because the
        entry's other job is the operation state a retry and a conflict check
        need. It is released by ``settle_unresolved`` or a confirmed exit --
        never by a ``finally``.

        ``pending_limit_bytes``/``previous_limit_bytes`` carry the *operation
        itself*: the memory limit this configure was reaching for and the one it
        would leave behind. Without them nothing -- not a retried save, not an
        unload, not a later reader of the field -- can tell what transaction the
        entry belongs to.

        ``phase`` records how far it got (``sent``/``settling``/``rollback_sent``/
        ``rollback_unknown``). ``reserved_bytes`` overrides the reservation when
        the caller knows better than the original entry (a retry of a reduction
        reserves nothing even though the entry it replaces may have reserved a
        raise's delta).

        Must not await (it can run while a cancelled task unwinds), so it mutates
        the ledger by replacement like every other writer. The replacement is
        returned so the caller can keep a handle on what the ledger now holds.
        """
        if promise is None:
            return promise
        replacement = BudgetPromise(
            kind=promise.kind, model_id=promise.model_id,
            bytes=(int(reserved_bytes) if reserved_bytes is not None
                   else promise.bytes),
            token=promise.token, unresolved=True,
            pending_limit_bytes=(pending_limit_bytes if pending_limit_bytes is not None
                           else promise.pending_limit_bytes),
            previous_limit_bytes=(previous_limit_bytes if previous_limit_bytes is not None
                            else promise.previous_limit_bytes),
            phase=(phase if phase is not None else promise.phase))
        self.device_promises = tuple(
            replacement if p.token == promise.token else p
            for p in self.device_promises)
        return replacement

    def unresolved_promises(self, model_id: str | None = None
                            ) -> tuple[BudgetPromise, ...]:
        """Claims whose outcome on the worker is unknown (optionally for one model)."""
        return tuple(p for p in self.device_promises
                     if p.unresolved and (model_id is None or p.model_id == model_id))

    def resolve_unresolved_promises(self, model_id: str) -> int:
        """Forget the unresolved claims for ``model_id``; returns how many went.

        Called only after a **read** has shown the worker's effective budget and
        the stored setting agree -- at which point the memory is accounted for by
        the stored setting (a raise that took effect) or by neither side (one that
        did not), and the extra reservation would only over-refuse.
        """
        stale = self.unresolved_promises(model_id)
        if not stale:
            return 0
        tokens = {p.token for p in stale}
        self.device_promises = tuple(
            p for p in self.device_promises if p.token not in tokens)
        return len(stale)

    def unresolved_message(self, model_id: str) -> str:
        """The 409 detail for a change that must wait for one in doubt."""
        stale = self.unresolved_promises(model_id)
        held = (f"{stale[0].bytes / 2**20:.0f} MiB" if stale else "对应额度")
        return (
            f"模型 {model_id} 上一次内存额度调整的结果未确认：worker 可能已经应用了新额度，"
            f"但答复在途中丢失（{held} 仍按已占用保守记账）。"
            "请先重试上一次保存（相同的额度会先核对 worker 的实际状态），"
            "或先卸载该模型；在确认之前不会按未确认的读数继续调整。")

    def raise_if_budget_unresolved(self, model_id: str) -> None:
        """Refuse a new limit change while ``model_id``'s last one is in doubt.

        A second **different** raise admitted on top of an unresolved one would be
        checked against a device reading that does not describe the worker's real
        budget, so the arithmetic itself would be meaningless. Retrying the same
        save is different, and the route settles that first instead of refusing it
        (MYS-2801) -- this method is what a *different* change hits.
        """
        if self.unresolved_promises(model_id):
            raise ModelBusy(self.unresolved_message(model_id))

    # -- settling a limit change whose outcome is in doubt (MYS-2801) ------
    #
    # Two things this fixes over the MYS-2795 shape:
    #
    #  * **it is reachable.** ``raise_if_budget_unresolved`` used to be an
    #    unconditional 409 on every new change to the model, so the "retry the
    #    same save" its own message named was refused too, and the only other
    #    remedy -- unload -- also refused. The doubt could only be cleared by
    #    restarting the process. A retry now settles first (``settle_unresolved``)
    #    and only a *different* change waits (409) -- the operator's retry, or
    #    the background job, is what makes the ledger converge.
    #  * **it is completable without the HTTP request that started it.** A claim
    #    carries the limit it was reaching for and the one it would leave behind,
    #    so the settlement is a function of the worker's reading and the store,
    #    not of a request object that is already gone.

    def pending_settlement(self, model_id: str) -> BudgetPromise | None:
        """The unresolved claim for ``model_id``, or None."""
        stale = self.unresolved_promises(model_id)
        return stale[0] if stale else None

    def same_budget_request(self, promise: BudgetPromise, limit_bytes: int) -> bool:
        """Whether ``limit_bytes`` asks for what ``promise`` was already asking.

        The retry test. Both sides are a **memory limit** in bytes, so ``null``
        (the derived default) and an explicit number that derives to the same
        budget compare equal -- which is what the console sends when the operator
        retries without touching the field.
        """
        if promise.pending_limit_bytes is None:
            return False
        return int(promise.pending_limit_bytes) == int(limit_bytes)

    async def settle_unresolved(self, info: ModelInfo,
                                promise: BudgetPromise) -> tuple[str, int | None]:
        """Settle one unresolved operation against the worker's own reading.

        Returns the settled state plus the budget the worker reported, which is
        also what the record is left in:

          * ``"applied"`` -- the worker holds the new limit. The stored setting is
            NOT touched here: ``model_id``'s settings are the caller's to write,
            because only the caller knows whether the operator is retrying the
            same change or looking at it. The caller stores, then calls
            ``finish_operation``.
          * ``"unchanged"`` -- the worker is still on the old limit. The change
            never happened, so the record is dropped: the stored setting and the
            worker agree, and there is nothing to reserve.
          * ``"unknown"`` -- still cannot tell. The record stays, unresolved, and
            keeps whatever it reserved.

        A **zero-byte** operation is settled by exactly the same comparison: the
        record tells us which limit the ``configure`` was reaching for, and that
        is all the read needs. This is why the record and the reservation are
        separate fields -- there is no separate code path for "nothing to
        reserve", which is where the second review found ``None`` being
        dereferenced.

        Never re-sends ``configure``: a second write on top of an unknown first
        one could produce a third state. Reading is how this converges.
        """
        if info.kind not in GROWING_KINDS:
            # An auxiliary engine has no scheduler, so its worker's ``configure``
            # carries no budget at all -- there is nothing it *could* have
            # applied, and nothing to read back. That is a known outcome, not an
            # unknown one: the limit is a load-time check, so the record's only
            # remaining job is to let the caller store the setting.
            return "applied", None
        verdict, actual = await self.probe_worker_budget(
            info, promise.pending_limit_bytes,
            previous_limit_bytes=promise.previous_limit_bytes)
        if verdict == "unchanged":
            # The worker is on the old limit, so the change never happened: the
            # stored setting and the worker agree and nothing needs reserving.
            self.finish_operation(promise)
        # ``applied`` and ``unknown`` both leave the record in place: in the first
        # case because the caller must store the new setting before releasing it
        # (otherwise there is an instant in which the memory is promised by
        # neither side), in the second because it may still be held.
        return verdict, actual

    async def admit_limit_raise(self, info: ModelInfo, limit_bytes: int
                                ) -> BudgetPromise | None:
        """Admit a live raise of ``info``'s memory limit, or raise.

        Returns the promise the caller must release once the new limit is
        stored, or ``None`` when nothing had to be promised: a reduction frees
        memory, and a model whose kind does not grow has no runtime allocation
        to admit.

        **A caller that is about to send a ``configure`` must not use this.**
        ``None`` here means "no bytes to reserve", not "no operation": a
        reduction, a no-op and a reserve-off change are real transactions that
        can lose their reply. ``begin_limit_change`` is the entry point for
        those -- it always returns a record. This method stays for the admission
        arithmetic itself and for the tests that drive it directly.

        The lock is held only for the read-and-register, never across the worker
        round trip: the promise is what makes that safe, because it keeps the
        memory reserved while the RPC is in flight.

        Caller holds ``info``'s lifecycle lock, so the "old budget" read here
        cannot change under it -- see ``app/api/admin_api.update_model_settings``
        for the ordering (lifecycle first, budget lock inside).
        """
        if info.kind not in GROWING_KINDS:
            # No cross-request KV: an auxiliary engine allocated everything at
            # load. Its limit is a load-time check, and there is no runtime
            # allocation to promise (docs/model-settings.md, MYS-2703 RC board).
            return None
        from . import mem_limit

        old_budget = self.runtime_budget_bytes(info)
        old_limit_bytes = self.mem_limit_bytes(info)
        new_budget = mem_limit.runtime_budget_bytes(limit_bytes, self.static_bytes(info))
        delta = int(new_budget) - int(old_budget)
        if delta <= 0:
            # A reduction (or a no-op) never needs headroom. The worker still has
            # the last word -- it refuses a live reduction while requests run.
            return None
        reserve = npu_reserve_bytes()
        if reserve <= 0:
            # The operator switched the floor off: there is nothing to protect
            # and no number to check against, which is the documented meaning of
            # CV84X6_NPU_RESERVE_MB=0.
            return None
        async with self._budget_lock:
            free = self._npu_free_bytes()
            if free is None:
                if self._reading_is_required():
                    raise DeviceBudgetUnverifiable(
                        "无法读取 NPU 堆余量，不能确认增额是否安全；"
                        "请稍后重试（设备内存读数不可用时不放行运行期增额）")
                return None
            # The model's own **existing** budget stays in the committed sum --
            # it is a promise `free` does not vouch for -- and only the increase
            # is added on top. Subtracting the whole new budget instead would
            # double-count the old half; excluding the model instead (the first
            # review's finding) would spend it twice.
            left = self._headroom_left(free, delta)
            if left < reserve:
                raise DeviceMemoryError(
                    f"NPU 显存余量不足：把 {info.model_id} 的运行期预算从 "
                    f"{old_budget / 2**20:.0f} MiB 调到 {new_budget / 2**20:.0f} MiB"
                    f"（增 {delta / 2**20:.0f} MiB）后 NPU 只剩 "
                    f"{left / 2**20:.0f} MiB，低于安全下限 {reserve / 2**20:.0f} MiB。"
                    "运行期预算会真的分配出去，所以这条检查照常执行。"
                    "如确实需要更大的额度，请先卸载其他模型再调整；"
                    "运行期已用的估算字节不作为可抵扣的物理内存。")
            logger.info(
                "admitted a %d MiB runtime raise for %s (NPU free %d MiB, "
                "committed %d MiB incl. its own old budget, %d promise(s) in "
                "flight, %d MiB would be left)",
                delta // 2**20, info.model_id, free // 2**20,
                self._committed_runtime_bytes() // 2**20,
                len(self.device_promises), left // 2**20)
            return self._take_budget_promise(
                "raise", info.model_id, delta,
                pending_limit_bytes=limit_bytes, previous_limit_bytes=old_limit_bytes)

    async def begin_limit_change(self, info: ModelInfo, limit_bytes: int
                                 ) -> BudgetPromise:
        """Open a model-configuration operation and reserve what it needs.

        The entry point every sent ``configure`` goes through (MYS-2801, second
        review). It differs from ``admit_limit_raise`` in exactly one way, and
        that difference is the whole finding: **it always returns a record**.
        ``admit_limit_raise`` answers "how much must be reserved", which is zero
        for a reduction, a no-op, a reserve-off change and a model that does not
        grow -- so a caller that used it had no operation state to settle when
        one of those lost its reply, and dereferenced ``None`` instead.

        Reserved bytes are the raise's delta (or zero), while the record carries
        the limit being reached for, the one being left behind, and the phase.
        Nothing here can fail on the "no bytes" paths: there is no device reading
        to take when nothing is being handed out.

        Caller holds ``info``'s lifecycle lock -- see
        ``app/api/admin_api.update_model_settings`` for the ordering.
        """
        old_limit_bytes = self.mem_limit_bytes(info)
        promise = await self.admit_limit_raise(info, limit_bytes)
        if promise is not None:
            # ``admit_limit_raise`` already recorded both limits and the real
            # reservation; the entry just needs to say what it is.
            return self._replace_operation(promise, phase="sent")
        # Nothing to reserve -- but the operation is still real, and still has to
        # be visible to a conflict check and to a retry if its reply is lost.
        async with self._budget_lock:
            return self._take_budget_promise(
                "raise", info.model_id, 0,
                pending_limit_bytes=limit_bytes,
                previous_limit_bytes=old_limit_bytes)

    def _replace_operation(self, promise: BudgetPromise, **changes
                           ) -> BudgetPromise:
        """Return the ledger's copy of ``promise`` with ``changes`` applied."""
        token = promise.token
        wanted = None
        for p in self.device_promises:
            if p.token == token:
                fields = {
                    "kind": p.kind, "model_id": p.model_id, "bytes": p.bytes,
                    "token": p.token, "unresolved": p.unresolved,
                    "pending_limit_bytes": p.pending_limit_bytes,
                    "previous_limit_bytes": p.previous_limit_bytes,
                    "phase": p.phase,
                }
                fields.update(changes)
                wanted = BudgetPromise(**fields)
                break
        if wanted is None:
            # Not on the ledger (already settled by a concurrent path): describe
            # the same operation without pretending to have published it.
            fields = {
                "kind": promise.kind, "model_id": promise.model_id,
                "bytes": promise.bytes, "token": promise.token,
                "unresolved": promise.unresolved,
                "pending_limit_bytes": promise.pending_limit_bytes,
                "previous_limit_bytes": promise.previous_limit_bytes,
                "phase": promise.phase,
            }
            fields.update(changes)
            return BudgetPromise(**fields)
        self.device_promises = tuple(
            wanted if p.token == token else p for p in self.device_promises)
        return wanted

    def finish_operation(self, promise: BudgetPromise | None) -> None:
        """Drop a configuration operation whose outcome is settled.

        Called on success (the setting now carries the memory, so the record has
        nothing left to say) and on a definite refusal (nothing was applied, and
        the operation is over). Never called while the outcome is in doubt.
        ``bytes`` may be zero; dropping a zero-byte record is still the point.
        """
        self.release_budget_promise(promise)

    def configuration_operations(self, model_id: str) -> tuple[BudgetPromise, ...]:
        """Every configuration operation recorded for ``model_id``.

        Not just the unresolved subset (MYS-2801, second review). An operation
        whose reply arrived, or whose outcome was already settled, is still a
        record of something this service sent to that worker; a confirmed exit
        has to clear all of them, not only the doubtful ones, or the next load
        inherits an entry nobody can settle.
        """
        return tuple(p for p in self.device_promises
                     if p.is_operation and p.model_id == model_id)

    def clear_configuration_operations(self, model_id: str) -> int:
        """Drop every configuration operation recorded for ``model_id``.

        The confirmed-exit path (MYS-2801, second review). ``unresolved_promises``
        is the *doubtful* subset; an operation is cleared when the worker it was
        sent to is gone, whether or not its outcome was ever in doubt. Anything
        left behind reserves memory for a process that no longer exists and gives
        the next load an operation state it can neither retry nor settle.

        Returns how many went, for the log line and for tests.
        """
        gone = {p.token for p in self.configuration_operations(model_id)}
        if not gone:
            return 0
        self.device_promises = tuple(
            p for p in self.device_promises if p.token not in gone)
        return len(gone)

    def clear_load_claims(self, model_id: str) -> int:
        """Drop load reservations for a model whose worker is confirmed gone.

        The sibling of ``clear_configuration_operations`` for the other half of
        the ledger, and needed since MYS-2805: a load that failed around a worker
        which would not exit keeps its footprint reserved (see
        ``_record_survivor``), so that entry has to be dropped at the same moment
        its process is proven gone -- otherwise it reserves memory for the rest of
        the service's life and refuses loads that fit.

        Deliberately *not* folded into ``clear_configuration_operations``: that one
        is also called from the settings path for a model that is merely idle,
        where a survivor's claim is still describing a live process.

        Returns how many went.
        """
        gone = {p.token for p in self.device_promises
                if p.model_id == model_id and not p.is_operation}
        if not gone:
            return 0
        self.device_promises = tuple(
            p for p in self.device_promises if p.token not in gone)
        return len(gone)

    async def resolve_budget_after_unknown(self, info: ModelInfo,
                                           limit_bytes: int | None = None
                                           ) -> str:
        """Find out what the worker really did after an inconclusive ``configure``.

        Called when the RPC timed out, the connection dropped, or this request was
        cancelled mid-call -- three situations in which "the worker refused" and
        "the worker applied it and the reply was lost" are indistinguishable from
        here. Guessing either way is wrong: assume refused and the ledger forgets
        memory the worker holds; assume applied and the stored setting may promise
        memory nobody has.

        So ask. ``stats`` reports the worker's effective budget
        (``kv_budget_bytes``, which ``apply_mem_limit`` sets from
        ``limit - static`` and the device ceiling), and the answer decides:

          * the worker is at the **new** budget -> the change took effect, so
            store it: the setting becomes the record and the claim can go. Returns
            ``"applied"``.
          * the worker is still at the **old** budget -> it never applied it (or
            a live-reduction guard refused it), so nothing changed and the claim
            can go. Returns ``"unchanged"``.
          * the read fails, or reports neither figure (an engine with no
            scheduler, a worker that died mid-call) -> ``"unknown"``. The claim
            then stays on the ledger, marked unresolved, and later admissions keep
            counting it.

        ``limit_bytes`` is the runtime budget the ``configure`` was reaching for,
        and defaults to the *stored* setting (MYS-2801). A retry passes the value
        it is about to save instead: the request that lost its reply deliberately
        did **not** store anything, so the stored setting still describes the
        state before the change, and asking about it would compare the worker
        against the wrong side.

        Deliberately does **not** re-send ``configure``: a second write whose first
        outcome is unknown could apply a third state on top. Reading is how this
        converges.
        """
        verdict, _actual = await self.probe_worker_budget(info, limit_bytes)
        return verdict

    async def probe_worker_budget(self, info: ModelInfo,
                                  limit_bytes: int | None = None, *,
                                  previous_limit_bytes: int | None = None
                                  ) -> tuple[str, int | None]:
        """:meth:`resolve_budget_after_unknown`, also returning what it read.

        The figure is what the settlement needs to tell "still on the old budget"
        from a third value it cannot act on, and the caller stores it in the
        log line rather than making a second read.
        """
        probe = self.worker_stats
        if probe is None:
            return "unknown", None
        try:
            stats = await asyncio.wait_for(probe(info.model_id), timeout=5)
        except Exception:
            return "unknown", None
        if not isinstance(stats, dict):
            return "unknown", None
        return self._classify_worker_budget(
            info, stats, limit_bytes, previous_limit_bytes=previous_limit_bytes)

    def _classify_worker_budget(self, info: ModelInfo, stats: dict,
                                limit_bytes: int | None = None, *,
                                previous_limit_bytes: int | None = None
                                ) -> tuple[str, int | None]:
        """What a worker ``stats`` reply says about the limit change in doubt.

        ``limit_bytes`` is a **memory limit** -- the same figure a store entry's
        ``mem_limit_mb`` denotes -- and defaults to the one in force. It is
        converted to the runtime budget the worker is expected to enforce, which
        is what ``mem_runtime_budget_bytes`` reports; comparing the reported
        runtime budget against a raw limit is the units mistake that made a
        settled change look like a third, uninterpretable value.

        ``previous_limit_bytes`` is the limit the operation started from. It has
        to be passed explicitly by anything settling a *recorded* operation: the
        stored setting may have moved since (a failed save rolls it back, a retry
        writes it), so reading "the limit in force" now can describe neither side
        of the transaction being settled.
        """
        applied = stats.get("mem_runtime_budget_bytes")
        effective = stats.get("kv_budget_bytes")
        if applied is None and effective is None:
            # Nothing to compare against: an engine that never had a budget, or a
            # worker too old/damaged to report one. Cannot confirm anything.
            return "unknown", None
        from . import mem_limit

        static = self.static_bytes(info)
        target = mem_limit.runtime_budget_bytes(
            self.mem_limit_bytes(info) if limit_bytes is None else int(limit_bytes),
            static)
        old = (self.runtime_budget_bytes(info) if previous_limit_bytes is None
               else mem_limit.runtime_budget_bytes(int(previous_limit_bytes), static))
        # ``kv_budget_bytes`` is the min of the model budget and the device
        # reading, so compare against whichever the worker reported, preferring
        # the model budget when it reports both (it is the figure the request set).
        actual = applied if applied is not None else effective
        if int(actual) == int(target):
            return "applied", int(actual)
        if int(actual) == int(old):
            return "unchanged", int(actual)
        # Some third figure: the worker is enforcing something neither side asked
        # for (a device ceiling below the request, most likely). Not ours to
        # interpret -- stay conservative.
        return "unknown", int(actual)

    async def _commit_load_budget(self, info: ModelInfo,
                                  promise: BudgetPromise | None,
                                  static_bytes: int) -> BudgetPromise | None:
        """Re-admit a finished load against the footprint it actually took.

        The load was admitted on ``_declared_claim_bytes`` -- an **estimate** of
        the static figure, taken before the worker existed. For a dynamic 35B
        build that estimate is up to 18 GiB below what the load really maps (see
        ``mem_limit.estimate_static_bytes``), so the claim that was checked
        against the device understates the memory this process now holds. The
        measurement exists by the time this runs (``_record_static_measurement``
        has just written it), and this call is what turns the admission into
        arithmetic on the *final* number.

        What is re-checked is only the part the device reading cannot vouch for.
        ``free`` was read after the worker finished loading, so it **already
        excludes** this model's static bytes; subtracting them again would count
        the same memory twice and refuse loads that fit (the design's explicit
        "不能重复扣这份静态"). For a growing kind the remaining commitment is its
        runtime budget -- what sessions and the prefix cache may still take, which
        is exactly the figure ``_committed_runtime_bytes`` counts once ``loaded``
        is published. An auxiliary engine never grows (``GROWING_KINDS``), so it
        has nothing left to promise and keeps the plain "free already covers it"
        reading the load check uses.

        The claim keeps its **token**, only its ``bytes`` change, so the caller's
        single release path still owns it: an exception or a cancellation between
        here and the published ``loaded`` cannot strand a second entry.

        Called with the model still unpublished. ``_committed_runtime_bytes``
        therefore does not count it yet, which is why this one figure -- not the
        whole footprint -- is the claim here.
        """
        if promise is None or npu_reserve_bytes() <= 0:
            # No claim means no admission to correct: the operator switched the
            # floor off, or this is a host with no readable heap. Nothing to
            # re-check against and nothing to reserve.
            return promise
        from . import mem_limit

        if info.kind in GROWING_KINDS:
            pending_commit = int(mem_limit.runtime_budget_bytes(
                self.mem_limit_bytes(info), int(static_bytes)))
        else:
            pending_commit = 0
        async with self._budget_lock:
            free = self._npu_free_bytes()
            if free is None:
                if self._reading_is_required():
                    # The check the load passed cannot be repeated on the number
                    # that matters, and the worker is alive holding the memory.
                    # Failing here unwinds through the load's own failure path,
                    # which terminates the process -- never "loaded, over budget".
                    raise DeviceBudgetUnverifiable(
                        f"模型 {info.model_id} 加载后实测静态占用 "
                        f"{int(static_bytes) / 2**20:.0f} MiB，但读不到 NPU 堆余量，"
                        "无法确认加载后仍留有安全余量；已按加载失败处理")
                return promise
            # This load's own estimate is excluded from the pending sum, not
            # subtracted twice: the claim below *replaces* it. Same arithmetic as
            # ``_headroom_left``, with the not-yet-restated entry taken out.
            others = sum(p.bytes for p in self.device_promises
                         if p.token != promise.token)
            left = (int(free) - pending_commit
                    - self._committed_runtime_bytes() - others)
            reserve = npu_reserve_bytes()
            if left < reserve:
                raise DeviceMemoryError(
                    f"NPU 显存余量不足：{info.model_id} 加载后实测静态占用 "
                    f"{int(static_bytes) / 2**20:.0f} MiB（加载前估算 "
                    f"{promise.bytes / 2**20:.0f} MiB 的一部分），其运行期预算 "
                    f"{pending_commit / 2**20:.0f} MiB 核算后 NPU 只剩 "
                    f"{left / 2**20:.0f} MiB，低于安全下限 {reserve / 2**20:.0f} MiB。"
                    "这条余量是硬性的（NPU 堆几乎占满时 TPU 会卡死），"
                    "已按加载失败处理并结束该 worker；请调低该模型的内存上限，"
                    "或换成静态占用更小的构建")
            logger.info(
                "load of %s admitted on its measured footprint: %d MiB static, "
                "%d MiB runtime budget still to be promised (NPU free %d MiB, "
                "%d MiB committed elsewhere, %d MiB floor)",
                info.model_id, int(static_bytes) // 2**20, pending_commit // 2**20,
                int(free) // 2**20,
                (self._committed_runtime_bytes() + others) // 2**20,
                reserve // 2**20)
            return self._restate_budget_promise(promise, pending_commit)

    def _restate_budget_promise(self, promise: BudgetPromise,
                                nbytes: int) -> BudgetPromise:
        """Replace a promise's reservation, keeping its token and identity.

        Caller holds ``_budget_lock``. A replacement rather than a release and a
        new entry: the token is what every ``finally`` in the load path releases,
        so keeping it means the promise cannot be dropped twice or forgotten
        while its bytes change under a completed measurement.
        """
        replacement = BudgetPromise(
            kind=promise.kind, model_id=promise.model_id, bytes=int(nbytes),
            token=promise.token, unresolved=promise.unresolved,
            pending_limit_bytes=promise.pending_limit_bytes,
            previous_limit_bytes=promise.previous_limit_bytes,
            phase=promise.phase)
        self.device_promises = tuple(
            replacement if p.token == promise.token else p
            for p in self.device_promises)
        return replacement

    def _check_final_mem_limit(self, info: ModelInfo, static_bytes: int) -> None:
        """Refuse a load whose **measured** static footprint exceeds the limit.

        ``_check_mem_limit`` runs before the spawn and can only compare against
        the estimate; for a dynamic 35B build the estimate is up to 18 GiB below
        what ``bmrt`` then maps. Discovering that only afterwards must not end in
        "loaded, runtime budget 0": that publishes a model sitting above the
        ceiling the operator set, with a number that hides it. The load is
        refused instead, and the caller's failure path terminates the worker --
        no over-limit process is left able to serve.

        A *derived* default can never trip this: ``mem_limit_default_bytes`` is
        computed from this same static figure. Only an explicit setting can, and
        the message says both numbers plus the remedy.
        """
        limit = self.mem_limit_bytes(info)
        if limit <= 0 or int(static_bytes) <= limit:
            return
        raise ModelMemLimitError(
            f"模型 {info.model_id} 实测静态占用 {int(static_bytes)} 字节"
            f"（约 {int(static_bytes) / 2**20:.0f} MiB）超过本模型内存上限 "
            f"{limit / 2**20:.0f} MiB，无法加载；已卸载该 worker，"
            f"请把该模型的内存上限调到至少 {int(static_bytes) / 2**20:.0f} MiB"
            f"（或改为默认值 {self.mem_limit_default_bytes(info) / 2**20:.0f} MiB）")

    async def _load_locked(self, info: ModelInfo) -> ModelInfo:
        """Spawn the worker and wait until it is *fully* initialised.

        "Loaded" is published at one instant and only after every prerequisite
        is proven: process spawned, readiness handshake answered, capability
        probe (stats + health with this model's id) returned, and -- since
        MYS-2805 -- the worker reconfigured and confirmed against the static
        footprint the load was measured at. Until then the model reads
        ``operation: "loading", loaded: false``, and the inference routes refuse
        it with 409 rather than dispatching into a worker that is still mapping
        weights (MYS-2496).

        Caller holds the lock.
        """
        model_id = info.model_id
        if self.backend_kind == "native":
            avail = mem_available_bytes()
            if avail is not None and avail < MIN_FREE_FOR_WORKER:
                raise SystemMemoryError(
                    f"系统可用内存仅 {avail >> 20} MB，加载模型需要至少 "
                    f"{MIN_FREE_FOR_WORKER >> 20} MB（worker 约 800 MB）；"
                    "请先停止占用内存的 agent（如 OpenClaw）")
        # Before anything else: a limit below the model's own static footprint
        # can never be satisfied, and discovering that after a 60 s spawn would
        # waste the load and report a worse error (bm_alloc_gmem failed).
        self._check_mem_limit(info)
        self._check_npu_admission(info)
        # The device-budget admission: check, then *register the claim in the same
        # critical section* (MYS-2795). Registering is what makes the tens of
        # seconds between here and a ready worker visible to every other
        # admission -- a raise or a second load that arrives mid-spawn would
        # otherwise be admitted against memory this load is about to take. The
        # lock is released before anything is spawned, so two different models
        # still load in parallel.
        #
        # **Every** kind that has an NPU footprint registers one, auxiliary
        # included. "An auxiliary engine does not grow after it loads" is true and
        # irrelevant: it still needs its whole footprint *during* the load, so two
        # concurrent embedding loads admitted against the same free figure
        # oversell by one of them (the first review's second finding: 1536 MiB
        # free, two 512 MiB loads, both admitted, 512 MiB left against a 1024 MiB
        # floor). The amount differs by kind and comes from the same place the
        # check does -- see ``_declared_claim_bytes``.
        promise: BudgetPromise | None = None
        async with self._budget_lock:
            # Last, so a model that plainly does not fit gets the more specific
            # message. This one is about the chip surviving, not about this model.
            self._check_npu_reserve(info)
            if npu_reserve_bytes() > 0:
                promise = self._take_budget_promise(
                    "load", model_id, self._declared_claim_bytes(info))

        try:
            loaded = await self._spawn_and_await(info, promise=promise)
        finally:
            # Every failure path -- refused spawn, never-ready worker, cancellation
            # from a shutting-down service, a timeout -- lands here. A success
            # releases it too, because by then ``loaded`` and the recorded static
            # footprint carry the commitment (see ``_spawn_and_await``).
            self.release_budget_promise(promise)
        return loaded

    def _declared_claim_bytes(self, info: ModelInfo,
                              *, static: int | None = None) -> int:
        """The bytes a load reserves until it finishes: its declared footprint.

        The **same** figure ``_check_npu_reserve`` compares against, taken from
        the same per-kind rule, so a claim can never describe different memory
        than the check that granted it:

          * a growing kind (chat / ocr_vl) + its runtime budget, because sessions
            and the prefix cache will grow into it after the load;
          * an auxiliary kind + ``AUX_DEVICE_HEADROOM``, because that is the
            working space its engine allocates at load time.

        ``static`` overrides the static figure for the *second* reading of this
        rule: once the load has been measured, ``_commit_load_budget`` asks the
        same question about what the worker really took instead of what it was
        expected to take. Passing ``info``'s live figures is the only way that
        answer stays in step with the runtime budget the worker was just handed.

        Rounded **up** to whole MiB, so a later admission's arithmetic cannot hand
        out the sub-MiB remainder.
        """
        static_bytes = self.static_bytes(info) if static is None else int(static)
        if info.kind in GROWING_KINDS:
            from . import mem_limit

            runtime = mem_limit.runtime_budget_bytes(
                self.mem_limit_bytes(info), static_bytes)
            footprint = static_bytes + runtime
        else:
            footprint = static_bytes + AUX_DEVICE_HEADROOM
        return -(-int(footprint) // (1024 * 1024)) * (1024 * 1024)

    async def _sync_worker_budget(self, info: ModelInfo, port: int,
                                  static_bytes: int) -> int:
        """Push the final static figure to a just-loaded worker, and confirm it.

        The worker was started with ``--mem-static-bytes`` set to the figure known
        *before* it ran -- ``mem_limit.estimate_static_bytes``, which for a dynamic
        build is the declared, pre-load number. Once the process has mapped its
        weights the device has a better answer, and ``limit - static`` computed
        from the estimate grants the scheduler memory the model does not have.
        Measured on the reviewer's cold `.157` run: 14355 MiB limit, 13331 MiB
        measured static, and a worker budget of 5482284672 B instead of
        1073569792 B -- 4.1 GiB over, with no way for the operator to see it.

        Why a reconfiguration rather than a restart with better flags: the load is
        what produces the measurement, so there is no earlier moment at which the
        final number exists. Why before ``loaded`` is published: from the instant
        the model is visible a request may arrive, and it must meet the budget the
        management plane reports, not the one the estimate produced. Two clients
        reading the console and the worker therefore never disagree.

        Confirmation is required, not assumed. A refusal, a reply that reports a
        different budget, a lost reply, a timeout or a cancellation all fail the
        load -- the caller terminates the worker -- because publishing a model
        whose budget nobody can confirm is the defect this method exists to close.
        A lost reply is not treated as a refusal: the worker may well have applied
        it, so one bounded ``stats`` read decides. Only that read can rescue it.

        Returns the budget the worker confirmed enforcing (which is what the
        management plane computes from the same two numbers).
        """
        from . import mem_limit
        from .client import WorkerClient, WorkerError, WorkerTransportError

        if info.kind not in GROWING_KINDS:
            # An auxiliary engine has no scheduler and no cross-request KV: its
            # limit is a load-time check, its worker answers ``configure`` with no
            # budget fields at all, and there is nothing to confirm. The static
            # figure it was started with only fed ``--mem-limit-mb`` bookkeeping.
            return 0
        limit_bytes = self.mem_limit_bytes(info)
        if limit_bytes <= 0:
            # No limit in force (only reachable from a hand-edited state file):
            # the worker keeps the device-derived budget it started with, which is
            # what ``mem_limit_bytes`` reports as "no ceiling" anyway.
            return 0
        # The worker receives whole MiB, so the budget it can enforce is derived
        # from the MiB value. Comparing against the unrounded limit would report a
        # mismatch of the sub-MiB remainder and fail every load.
        sent_limit = (int(limit_bytes) >> 20) << 20
        expected = int(mem_limit.runtime_budget_bytes(sent_limit, int(static_bytes)))

        client = WorkerClient(port)
        try:
            try:
                reply = await asyncio.wait_for(
                    client.configure(mem_limit_mb=sent_limit >> 20,
                                     mem_static_bytes=int(static_bytes)),
                    timeout=LOAD_BUDGET_SYNC_TIMEOUT_S)
            except WorkerTransportError as exc:
                # Not a refusal: the worker may have applied the budget and lost
                # the answer. One bounded read decides (below).
                logger.warning(
                    "synchronising %s's budget after load got no reply (%s); "
                    "reading the worker's own figure", info.model_id, exc)
                reply = None
            except (asyncio.TimeoutError, TimeoutError, OSError) as exc:
                logger.warning(
                    "synchronising %s's budget after load timed out (%s: %s); "
                    "reading the worker's own figure", info.model_id,
                    type(exc).__name__, exc)
                reply = None
            except WorkerError as exc:
                # The worker answered, and said no. That is a refusal.
                raise LoadFailure(
                    f"模型 {info.model_id} 加载后按实测静态占用 "
                    f"{int(static_bytes)} 字节同步内存额度被 worker 拒绝：{exc}"
                    "；已按加载失败处理") from exc
            if isinstance(reply, dict) and "error" in reply:
                raise LoadFailure(
                    f"模型 {info.model_id} 加载后按实测静态占用 "
                    f"{int(static_bytes)} 字节同步内存额度被 worker 拒绝："
                    f"{reply.get('error')}；已按加载失败处理")
            if not (isinstance(reply, dict) and self._budget_confirmed(reply, expected)):
                # Ask the worker what it is really enforcing. Also the path for a
                # reply that arrived but carried a different figure -- a third
                # value means the worker is not on the budget this load computed,
                # and which of the two is right cannot be guessed from here.
                reply = await self._read_worker_budget(
                    info, port, expected=expected)
                if reply is None:
                    raise LoadFailure(
                        f"模型 {info.model_id} 加载后无法确认 worker 的内存预算："
                        f"已按实测静态占用 {int(static_bytes)} 字节下发 "
                        f"{expected / 2**20:.0f} MiB 的运行期额度，但 worker 没有答复，"
                        "重读也没有得到可用读数；已按加载失败处理，未发布 loaded")
            logger.info(
                "synchronised %s's budget after load: static %d B, limit %d MiB, "
                "runtime budget %d B confirmed by the worker",
                info.model_id, int(static_bytes), sent_limit >> 20, expected)
            return expected
        finally:
            with contextlib.suppress(Exception):
                await client.close()

    @staticmethod
    def _budget_confirmed(reply: dict, expected: int) -> bool:
        """Whether a ``configure``/``stats`` reply reports ``expected``.

        ``mem_runtime_budget_bytes`` is the model's own figure -- ``limit -
        static``, exactly what was asked for -- and is the one to compare.
        ``kv_budget_bytes`` is the *minimum* of that and the device reading, so it
        is legitimately smaller and must not be used as the confirmation: doing so
        would fail every load on a board whose free heap is below the configured
        limit, which is most of them.
        """
        applied = reply.get("mem_runtime_budget_bytes")
        return applied is not None and int(applied) == int(expected)

    async def _read_worker_budget(self, info: ModelInfo, port: int,
                                  *, expected: int) -> dict | None:
        """One bounded ``stats`` read; the reply when it confirms ``expected``."""
        from .client import WorkerClient

        client = WorkerClient(port)
        try:
            try:
                stats = await asyncio.wait_for(
                    client.stats(), timeout=LOAD_BUDGET_SYNC_TIMEOUT_S)
            except Exception:
                return None
            if not isinstance(stats, dict) or not self._budget_confirmed(stats, expected):
                seen = (stats or {}).get("mem_runtime_budget_bytes") if isinstance(stats, dict) else None
                logger.error(
                    "model %s: worker reports %s B as its runtime budget after the "
                    "post-load synchronisation, expected %d B",
                    info.model_id, seen, expected)
                return None
            return stats
        finally:
            with contextlib.suppress(Exception):
                await client.close()

    async def _spawn_and_await(self, info: ModelInfo,
                               *, promise: BudgetPromise | None) -> ModelInfo:
        """The long half of a load: spawn, handshake, probe, synchronise, publish.

        Split out of ``_load_locked`` so the admission (check + promise, under the
        budget lock, no awaits that matter) is visibly separate from the work that
        takes tens of seconds. Nothing here holds ``_budget_lock`` across an
        await.

        The last stage before ``loaded`` is published is the **budget handover**
        (MYS-2805): the worker was spawned with the *estimated* static figure, so
        once the load has been measured it is reconfigured with the final static
        byte count and the final effective limit, and the device admission is
        re-run on what the load really took. Only then is the model made visible.
        Until that point it reads ``loading``; a synchronisation that is refused,
        times out, loses its reply or is cancelled fails the load and terminates
        the worker, instead of publishing a budget nobody confirmed.

        On success the promise is handed over to the state that now carries it --
        ``info.loaded`` plus the static measurement -- before this returns, so
        there is no instant in which the memory is promised by neither side.
        """
        model_id = info.model_id
        port = _free_port()
        log_path = self.log_dir / f"worker-{model_id}.log"
        # Rotate here, before the open: this is the only moment nothing holds an
        # fd to the file, and a worker that has been loaded and unloaded for
        # weeks would otherwise write one unbounded file (MYS-2674). The policy
        # (10 MiB x 3) lives with the reader that has to understand the
        # generations -- app/core/logs.py -- so the console's log page and the
        # rotation cannot disagree about what ".1" means.
        from .logs import WORKER_LOG_BACKUPS, WORKER_LOG_MAX_BYTES, rotate_log_file
        rotate_log_file(log_path, max_bytes=WORKER_LOG_MAX_BYTES,
                        backups=WORKER_LOG_BACKUPS)
        log_file = open(log_path, "ab", buffering=0)
        # The identity half of the command line comes from ``_worker_cmdline``
        # (the same helper discovery matches on), the tuning flags are added
        # here: they are this run's settings, not part of what makes the process
        # recognisable as this model's worker.
        cmd = self._worker_cmdline(info, port)
        cmd += [
            "--max-concurrent", str(self.max_concurrent_per_model),
            "--cache-entries", str(self.cache_entries),
            "--cache-ttl-min", str(self.cache_ttl_min),
            "--max-queue", str(self.max_queue),
            "--exact-tail", str(self.exact_tail),
            "--decode-delay-ms", str(self.decode_delay_ms),
        ]
        # The per-model memory ceiling, when one is in force (MYS-2675). Sent as
        # two facts because the worker cannot derive either: the limit is an
        # operator setting held by the management plane, and the static figure
        # comes from `bmrt_get_bmodel_info`, which the manager already ran.
        #
        # Only chat and ocr_vl have a scheduleable runtime budget; the other
        # kinds hold no cross-request KV, so an auxiliary worker collapses its
        # single slot to whatever the limit leaves and the buffer check is at
        # load time only (see `_check_mem_limit`). Sending the flags anyway is
        # harmless -- `apply_mem_limit` only ever lowers a budget -- and it means
        # a future kind cannot inherit "no limit" by being forgotten here.
        limit_mb = self.mem_limit_bytes(info) // (1024 * 1024)
        if limit_mb > 0:
            cmd += ["--mem-limit-mb", str(limit_mb),
                    "--mem-static-bytes", str(self.static_bytes(info))]
        if self.context_length_override:
            cmd += ["--context-length", str(self.context_length_override)]
        if self.backend_kind == "native" and self.native_lib:
            cmd += ["--native-lib", str(self.native_lib)]

        # Monotonic: the board's clock can be stepped by minutes mid-load (NTP
        # after an RTC-less boot), which made a 70 s load report 434 s.
        t0 = time.monotonic()
        # Publish "loading" before the spawn, inside the same event-loop step:
        # a GET /api/models served between the spawn and the first await would
        # otherwise show a bare pid with no operation, which the console reads
        # as "unloaded".
        self._begin(info, LOADING)
        info.load_error = None
        info.load_seconds = None
        # Device memory before the spawn, so the static footprint can be
        # *measured* rather than only estimated. Read here (outside any await)
        # rather than inside the worker: this process already knows how to query
        # both heaps, and doing it once per load is what turns the estimate into
        # a fact -- see ``_record_static_measurement``.
        device_before = self._device_used_bytes()
        # Whether this load ever got a worker process of its own. The failure
        # teardown needs it because "``_procs`` has no entry" is *not* the same
        # fact as "the worker exited": ``_terminate`` pops the handle before it
        # waits, so a second reader that only looks at the dict would call a
        # surviving process gone (MYS-2805 review).
        spawned = False
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=log_file, stderr=log_file, cwd=str(BASE),
                # New session: killing the worker must not take the manager with it.
                start_new_session=True,
            )
            spawned = True
            self._procs[model_id] = proc
            info.pid = proc.pid
            info.port = port
            info.adopted = False
            info.conflict = None
            self._workers[model_id] = WorkerIdentity(
                pid=proc.pid, port=port, started=procs.read_start_time(proc.pid))

            # Wait for the ready banner rather than sleeping a fixed time: model
            # load is 60+ s for the 35B, and a fixed sleep would either be far
            # too long or race the load.
            ready = await self._wait_ready(port, timeout=300, proc=proc)
            if not ready:
                # An empty log is a real case (a worker that hangs before it
                # prints anything), and "load_error: ''" tells the operator
                # nothing -- so say what happened instead of showing a blank.
                #
                # No teardown here: the ``except`` below is the one place that
                # terminates a failed load. Doing it twice is how the second
                # attempt mistook the already-popped handle for a confirmed exit
                # (MYS-2805 review finding 2).
                tail = self._read_log_tail(log_path)
                self._fail_load(info, tail or (
                    f"worker 在 {int(time.monotonic() - t0)} 秒内没有就绪"
                    f"（退出码 {proc.returncode}，日志 {log_path} 无输出）"))
                raise LoadFailure(
                    f"模型 {model_id} 的 worker 未能就绪："
                    f"{info.load_error or '见 worker 日志'}")

            # The socket answers, but the engine may still be unusable. Prove it
            # before `loaded` becomes observable: a model that reads as loaded
            # while its capabilities are unconfirmed is exactly the state that
            # let requests into a half-initialised worker.
            await self._confirm_initialised(port, info)

            # What the device showed this model cost, recorded **before** the
            # worker is told its budget: everything below reads the final static
            # figure, and `_check_mem_limit` / the derived default both depend on
            # it being the measurement rather than the estimate (for a dynamic
            # 35B build the two differ by up to 18 GiB,
            # mem_limit.estimate_static_bytes has the table).
            self._record_static_measurement(info, device_before, self._device_used_bytes())
            final_static = self.static_bytes(info)

            # The worker came up on the pre-load estimate (its command line), and
            # for a build whose estimate is below what it really maps that left it
            # enforcing `limit - estimate` -- 4.1 GiB too much on the reviewer's
            # 9B cold load. Nothing has read ``loaded`` yet and no client exists,
            # so synchronising here is invisible to callers: an operator who
            # loads and then reads the settings sees one consistent answer, with
            # no extra save needed.
            #
            # Order matters: the measured figure can exceed an explicit limit, and
            # the load must fail in that case rather than publish a worker whose
            # budget has been clamped to zero. Checking first means the refusal
            # message names both numbers without a configure ever being sent.
            #
            # Every failure here is recorded on the model as well as raised: the
            # console's ``load_error`` is what an operator reads, and "加载失败；
            # 详见 worker 日志" would hide a refusal this specific.
            try:
                self._check_final_mem_limit(info, final_static)
                await self._sync_worker_budget(info, port, final_static)
                # The load is re-admitted on the footprint it really took, and the
                # claim is restated to what is still to be promised. This is the
                # last thing that can refuse, and it happens while the model is
                # still unpublished, so a refusal unwinds through the failure path
                # below and terminates the worker.
                promise = await self._commit_load_budget(info, promise, final_static)
            except asyncio.CancelledError:
                self._fail_load(info, "加载被取消（服务正在停止）")
                raise
            except BaseException as exc:
                self._fail_load(info, str(exc) or "加载后同步内存额度失败")
                raise

            # Everything is proven. Publish `loaded` and hand the client over in
            # one event-loop step: from this statement on a request may use the
            # model, so the RPC client must already exist.
            info.loaded = True
            info.loaded_at = time.time()
            info.load_seconds = round(time.monotonic() - t0, 1)
            info.load_error = None
            # A freshly loaded model starts its idle clock now, and the auto
            # unload reason belongs to the *previous* residency: "自动卸载后又被
            # 加载" is a loaded model, not an idle one.
            self.touch(model_id)
            info.unloaded_reason = None
            # Register the RPC client before anything else can observe
            # ``loaded``: from here on a request may legitimately use this
            # model, and /v1/chat/completions looks the client up by id.
            if self.on_loaded is not None:
                self.on_loaded(model_id, info)
            # The claim is now backed by ``loaded`` plus the recorded static
            # footprint, which is what every later admission reads. Releasing it
            # here -- rather than only in the caller's ``finally`` -- is what
            # keeps the ledger from holding a claim on memory that is already
            # visible in the device's `used` figure, i.e. from double-counting
            # it against every other admission for the rest of the load call.
            self.release_budget_promise(promise)
        except BaseException:
            # Any failure -- a refused spawn, a missing binary, a cancellation
            # from a shutting-down service -- must leave the model looking
            # unloaded and idle, never "loading forever". Without this, a page
            # refreshed after a failed load kept the load button disabled until
            # the service restarted.
            #
            # **One** teardown, here, and it is the only one: no branch above
            # terminates the worker itself. Two half-teardowns cannot agree about
            # whether the process is gone (the first pops ``_procs`` before it
            # waits, so the second sees "no handle"), and the state they leave is
            # a live worker nobody can reach (MYS-2805 review finding 2).
            await self._teardown_failed_load(info, spawned=spawned, port=port)
            # `_fail_load` keeps a reason already recorded by the branches above;
            # this only fills in the ones that failed earlier.
            hint = self._npu_oom_hint(model_id)
            if hint:
                info.load_error = hint
            elif info.load_error is None:
                info.load_error = "加载失败；详见 worker 日志"
            self._end(info)
            raise
        finally:
            # The child owns the fd now; the parent must not pin the log file.
            with contextlib.suppress(Exception):
                log_file.close()

        # The capability probe is done, so the operation can end: a client that
        # saw `loaded` while `operation` was still set would keep its controls
        # disabled for no reason.
        self._end(info)
        logger.info("loaded %s on port %d in %.1fs", model_id, port, info.load_seconds)
        return info

    @staticmethod
    def _absorb_cancellation() -> None:
        """Consume one pending cancellation for the current task.

        Used on the load's failure path, where the teardown must run to completion
        even though the task is already unwinding from a ``CancelledError``:
        ``_terminate`` awaits a 120 s grace, and a cancellation delivered during it
        would abandon the wait with the process still alive and nobody owning it.

        ``uncancel`` only clears the *request*; the original exception keeps
        propagating out of the ``except`` block that called this, so the caller
        still sees exactly what it saw before.
        """
        task = asyncio.current_task()
        if task is not None and hasattr(task, "uncancel"):
            with contextlib.suppress(Exception):
                task.uncancel()

    async def _teardown_failed_load(self, info: ModelInfo, *,
                                    spawned: bool, port: int | None) -> bool:
        """End a failed load's worker, and record the truth about whether it did.

        The single owner of "what happened to the process this load started"
        (MYS-2805 review). Everything a failure needs follows from one fact --
        **confirmed exit or not** -- and this is the only place that fact is
        established:

          * the worker is running ``_terminate`` at all, which is why ``spawned``
            is passed in rather than inferred. ``_terminate`` pops ``_procs``
            *before* it waits, so "no entry in ``_procs``" cannot answer this
            question; a second reader that used it as the answer called a live
            process gone (review finding 2: the readiness branch terminated once,
            then the generic cleanup saw the popped handle and cleared the pid).
          * whether the process is really gone is decided by the **pid** (plus its
            recorded generation), not by the handle's report. A wait that was
            interrupted has no verdict, and a handle that reports an exit can
            still be describing a session this manager never owned.

        On a confirmed exit every trace goes: ``pid``/``port``/``conflict`` and
        any survivor claim, because there is nothing left holding the memory. On
        a survivor they all stay -- ``conflict`` says so in words, ``pid`` plus the
        recorded generation is what ``unload`` needs to signal (**whatever the NPU
        floor is set to**: the floor governs budget reservation, never whether a
        live process is recorded), and, when a floor is in force, a reservation
        keeps the bytes it holds out of every later admission.

        Cancellation is absorbed for the duration of the bounded teardown: the
        task is already unwinding, and abandoning the SIGTERM wait halfway is what
        leaves a process alive with nobody owning it. Detaching the teardown to a
        background task is deliberately not an option for the same reason.

        Returns whether the exit was confirmed.
        """
        self._absorb_cancellation()
        if not spawned:
            # Nothing was ever forked (a refused spawn, a missing binary), so
            # there is no process to be wrong about.
            self._clear_failed_load_identity(info)
            return True
        # ``_terminate`` pops the handle before it waits, so its presence in
        # ``_procs`` after this call is *not* evidence about the process -- which
        # is the mistake this method exists to remove. The survivor is recorded
        # by pid (plus the generation in ``_workers``), and ``unload`` reaches it
        # through ``_terminate_conflict``'s pid-based SIGTERM.
        try:
            stopped = await self._terminate(info.model_id)
        except asyncio.CancelledError:
            # A second cancellation during the grace. The wait never finished, so
            # this call has no verdict of its own -- the pid check below decides.
            self._absorb_cancellation()
            stopped = False
        except Exception as exc:                       # pragma: no cover - defensive
            logger.error("model %s: terminating the failed load's worker raised "
                         "%s: %s", info.model_id, type(exc).__name__, exc)
            stopped = False
        # The pid is the authority, not the handle's opinion of itself. A handle
        # whose ``wait`` was abandoned reports nothing, and one that says "gone"
        # can still be describing a session this manager never owned. Both
        # directions are corrected here, because the cost of a false "gone" is a
        # second worker spawned into occupied heap.
        gone = self._worker_confirmed_gone(info)
        if stopped and not gone:
            logger.error("model %s: the worker handle reported an exit but pid %s "
                         "is still alive; treating it as a survivor",
                         info.model_id, info.pid)
        if gone:
            self._clear_failed_load_identity(info)
            return True
        self._record_survivor(info, port=port)
        return False

    def _worker_confirmed_gone(self, info: ModelInfo) -> bool:
        """Whether the model's recorded worker really is not running any more.

        The corroboration on top of ``_terminate``'s verdict: that method reports
        what *its* handle saw, and a pid recorded from a command-line match (an
        adopted or conflicted process) can outlive the handle. ``process_alive``
        is generation-checked, so a recycled pid does not read as a survivor.
        """
        pid, started = info.pid, None
        ident = self._workers.get(info.model_id)
        if ident is not None:
            started = ident.started
            pid = ident.pid or pid
        if not pid:
            return True
        return not procs.process_alive(pid, started)

    def _clear_failed_load_identity(self, info: ModelInfo) -> None:
        """Forget a failed load's process: nothing is left holding the memory."""
        info.loaded = False
        info.loaded_at = None
        info.pid = None
        info.port = None
        info.conflict = None
        self._workers.pop(info.model_id, None)
        self.clear_load_claims(info.model_id)

    def _record_survivor(self, info: ModelInfo, *, port: int | None) -> None:
        """Record a failed load whose worker is still alive, and reserve its bytes.

        Reached only from ``_teardown_failed_load`` when the exit was not
        confirmed. Three things have to survive, and they are separate on purpose:

          * **the conflict** -- what makes ``load`` refuse to spawn a second worker
            into occupied heap (``ModelConflict``) and what makes ``unload`` take
            the conflict path at all. It is recorded **whatever the NPU floor is**:
            ``CV84X6_NPU_RESERVE_MB=0`` turns off budget reservation, and the
            review found that switching it off also silenced this marker, so a live
            worker was left unreachable and ``unload`` walked the idle branch and
            cleared its pid (finding 1).
          * **the pid and its generation** -- already on ``info`` and in
            ``_workers``; ``unload`` signals them through ``_terminate_conflict``.
            They are *not* cleared here, and nothing downstream may clear them
            while the process lives.
          * **the reservation**, only when a floor is in force. With no floor there
            is no admission arithmetic to protect, so no claim is manufactured --
            but the model still records that a worker is alive.
        """
        info.loaded = False
        info.loaded_at = None
        info.conflict = (
            f"加载 {info.model_id} 失败后 worker（pid {info.pid or '未知'}，"
            f"端口 {port}）仍在运行且未能确认退出；"
            + ("它占用的设备内存保持记账，" if npu_reserve_bytes() > 0 else "")
            + "请人工处理后重新加载，或点「卸载」再试一次")
        if npu_reserve_bytes() <= 0:
            return
        # One synchronous append, the same atomic tuple replacement every other
        # writer uses, so a concurrent admission reading ``_headroom_left`` sees
        # either the ledger before or after this entry -- never a half-edited one.
        # The budget lock is not taken: this runs on the load's unwinding path,
        # where awaiting anything is what would strand the state, and the entry's
        # bytes are computed from figures this load already owns.
        static = self.static_bytes(info)
        self._take_budget_promise(
            "load", info.model_id,
            self._declared_claim_bytes(info, static=static))

    async def _confirm_initialised(self, port: int, info: ModelInfo) -> None:
        """Raise unless the worker behind ``port`` has finished initialising.

        The single gate between "the process answered" and "publish ``loaded``".
        Two stages, both required: the readiness handshake (``_wait_ready``) has
        already passed, and this is the capability probe -- ``stats`` for a live
        scheduler, ``health`` for this model's id and its own ``loaded`` claim.

        Separated from ``_probe_capabilities`` so a test can replace the whole
        gate with one function and still drive every observable state
        transition: the failure paths must unwind identically whether the load
        died in the handshake or in the probe.
        """
        try:
            await self._probe_capabilities(port, info)
        except asyncio.CancelledError:
            # A shutdown, not a failure of the model: unwind the same way (the
            # caller's handler cleans up) but do not overwrite the reason.
            self._fail_load(info, "加载被取消（服务正在停止）")
            raise
        except Exception as exc:
            self._fail_load(info, f"能力探测失败：{type(exc).__name__}: {exc}")
            # Re-raise as a RuntimeError with the same prefix the console shows,
            # so the 409 body an operator reads and the `load_error` it can see
            # in `/api/models` say the same thing.
            raise RuntimeError(
                f"模型 {info.model_id} 的能力探测失败：{type(exc).__name__}: {exc}") from exc

    async def _wait_ready(self, port: int, timeout: float, proc) -> bool:
        """Poll the worker's health op until it says it is ready.

        ``ok: true`` alone is not readiness: the reply must also not disclaim
        being loaded, which is how a worker that opens its socket before its
        engine is usable looks. Whether it is *this* model's worker is checked
        by the capability probe that follows (``_probe_capabilities``); here the
        process is the one we just spawned, so the port is ours by construction.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.returncode is not None:
                return False
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", port), timeout=1.0
                )
                writer.write(b'{"op":"health"}\n')
                await writer.drain()
                line = await asyncio.wait_for(reader.readline(), timeout=5.0)
                writer.close()
                reply = json.loads(line)
                if reply.get("ok") and reply.get("loaded") is not False:
                    return True
            except (OSError, asyncio.TimeoutError, json.JSONDecodeError):
                await asyncio.sleep(0.5)
        return False

    def _read_log_tail(self, path: Path, n: int = 20) -> str:
        try:
            lines = path.read_text(errors="replace").splitlines()
            return "\n".join(lines[-n:])
        except OSError:
            return ""

    async def raise_if_unloadable(self, model_id: str) -> None:
        """The conflict check half of ``unload``, on its own.

        The route needs it before it closes the RPC client: a refusal must not
        have touched the worker's socket, and closing the client is also what
        lets the worker's shutdown finish promptly (see the route).
        """
        info = self._models.get(model_id)
        if info is None:
            raise KeyError(model_id)
        if info.operation == LOADING:
            raise ModelBusy(f"模型 {model_id} 正在加载中，请等待加载完成后再卸载")
        if info.operation == UNLOADING:
            raise ModelBusy(f"模型 {model_id} 正在卸载中")

    def _forget(self, info: ModelInfo) -> None:
        """Drop every runtime fact about a model whose worker is gone.

        ``loaded``/``pid``/``port`` describe one process, so they are cleared
        together -- an object left half-cleared is what lets a UI show a port
        that no process holds. The identity goes with them; the operation is the
        caller's to end.

        **Every** configuration operation for this model goes with the process,
        not only the doubtful ones (MYS-2801, second review). ``_forget`` runs
        only where the process is provably gone -- a confirmed unload, a reaped
        worker, a reconciled one -- and an operation record means "something this
        service sent to *that* worker". With no worker there is nothing left to
        be in doubt about, and no record can be settled or acted on again:
        keeping it would leave a reservation nothing can release and an operation
        state the next load inherits. A *surviving* process never reaches here,
        which is why the failed-unload case keeps its records.
        """
        self.clear_configuration_operations(info.model_id)
        self.clear_load_claims(info.model_id)
        self._procs.pop(info.model_id, None)
        self._workers.pop(info.model_id, None)
        info.loaded = False
        info.adopted = False
        info.pid = None
        info.port = None
        info.loaded_at = None
        info.conflict = None
        # The idle clock measured a residency that no longer exists. Keeping it
        # would make the next load look idle as of the *previous* run, and the
        # next sweep would unload it one interval after it came up.
        info.last_used_mono = None
        info.last_used_at = None

    async def unload(self, model_id: str, *,
                     if_unused_since: float | None = None) -> ModelInfo:
        """Unload ``model_id``, refusing while its load is still in flight.

        Refusing rather than killing a half-loaded worker is deliberate: the
        process may be minutes into mapping weights into NPU memory, and
        tearing it down there is how the TPU is left busy.

        The conflict check happens BEFORE the lock is taken. A load holds that
        lock for its whole 60+ s, so an unload that waited for it would block
        for minutes only to be told "no" -- and, worse, would then stop a
        model the operator had been told was busy loading.

        A model left in **conflict** by a restart is unloadable even though it
        is not "loaded": the only thing an operator can do about a worker that
        does not answer is stop it, and this is the button that does that.
        """
        await self.raise_if_unloadable(model_id)
        info = self._models[model_id]
        async with self.lock_for(model_id):
            # Re-check: the state may have changed while we waited for the
            # lock (another unload finished, or a load started and finished).
            if info.operation == LOADING:
                raise ModelBusy(f"模型 {model_id} 正在加载中，请等待加载完成后再卸载")
            if info.operation == UNLOADING:
                raise ModelBusy(f"模型 {model_id} 正在卸载中")
            if if_unused_since is not None and info.last_used_mono != if_unused_since:
                # The idle sweep's guard: used since it decided, so not idle.
                raise ModelBusy(f"模型 {model_id} 刚被使用，取消自动卸载")
            if not info.loaded and model_id not in self._procs and not info.conflict:
                # Nothing running: unload is idempotent, and reporting the
                # current (idle) state is what a poller needs.
                self._end(info)
                info.pid = None
                info.port = None
                info.loaded_at = None
                return info
            if not info.loaded and model_id not in self._procs:
                # A conflict: a survivor we refused to adopt. Terminating the
                # exact pid -- and only SIGTERM -- is the whole point.
                await self._terminate_conflict(info)
                return info
            self._begin(info, UNLOADING)
            try:
                # After `unloading` is published and before the signal: the HTTP
                # layer closes and forgets the RPC client here. Both orders are
                # load-bearing. The socket must close before SIGTERM (the
                # worker's shutdown waits on its connection handlers, so the
                # other order costs the 120 s grace and ends in a SIGKILL of a
                # live NPU process), and the switch must be visible first, or a
                # request arriving between the close and the state change finds
                # a model that reads loaded with no client behind it.
                if self.on_unloading is not None:
                    with contextlib.suppress(Exception):
                        await self.on_unloading(model_id)
                stopped = await self._terminate(model_id)
                # A worker that survived the grace is **not** forgotten. The
                # customer's reload failure (MYS-2784) is exactly this: the
                # unload reported success, ``_forget`` cleared the ``conflict``
                # ``_terminate`` had just recorded, and the next load spawned a
                # second worker into a heap the survivor was still holding, which
                # then failed with ``bmrt_load_bmodel failed (wrong chip or
                # corrupt file?)``. Keeping ``conflict`` makes the load refuse
                # with the pid named, and leaves "卸载" able to reach that pid.
                if stopped:
                    self._forget(info)
                info.load_seconds = None
                info.load_error = None
                # A manual unload clears the idle marker: the model is idle
                # because somebody asked for it, not because a timer expired
                # (``unload_idle`` sets it back afterwards, once, for its own
                # unloads only).
                info.unloaded_reason = None
            finally:
                self._end(info)
            return info

    async def _terminate_conflict(self, info: ModelInfo) -> None:
        """SIGTERM the worker recorded as a conflict, and clear the record.

        Not adopted into ``_procs`` for a reason: adoption is what allows the
        normal 120 s grace plus a SIGKILL fallback, and this process may be
        mid-prefill -- a kill there is what wedges the TPU. So the signal is
        sent to the pid we proved belongs to this model, the wait is bounded,
        and a process that survives is reported rather than escalated.
        """
        pid = info.pid
        # The generation recorded at discovery, so a recycled pid cannot make
        # this signal a stranger.
        started = self._workers.get(info.model_id)
        started = started.started if started is not None else None
        self._begin(info, UNLOADING)
        try:
            if pid and procs.process_alive(pid, started):
                logger.info("unload of conflicted model %s: SIGTERM -> pid %d",
                            info.model_id, pid)
                procs.signal_group(pid, 15)
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline and procs.process_alive(pid, started):
                    await asyncio.sleep(0.2)
                if procs.process_alive(pid, started):
                    info.conflict = (
                        f"pid {pid} 在收到 SIGTERM 后 120 秒仍未退出；"
                        "为避免卡死 NPU 不会强杀，请人工处理")
                    logger.error("model %s: %s", info.model_id, info.conflict)
                    return
            self._forget(info)
            info.load_seconds = None
            info.load_error = None
        finally:
            self._end(info)

    async def _terminate(self, model_id: str) -> bool:
        """SIGTERM the worker and wait for it; SIGKILL only a process we own.

        The grace is long because a worker 2048 tokens deep into a 32k prefill
        takes ~25 s to unwind, and killing it mid-launch is what leaves the TPU
        busy. An **adopted** worker may refuse SIGKILL (see ``AdoptedProcess``):
        we did not fork it, so its exit status is invisible to us and a kill at
        the wrong moment is unrecoverable. A refusal is therefore bounded and
        reported, never awaited forever.

        Returns True when the worker is gone, False when it survived every
        signal this manager is allowed to send. The caller has to know: an
        unload that leaves a process holding the NPU heap must not be reported
        as a clean one, or the next load starts a second worker on top of it
        (MYS-2784).
        """
        proc = self._procs.pop(model_id, None)
        if proc is None:
            return True
        if proc.returncode is not None:
            return True
        try:
            proc.terminate()  # SIGTERM: worker closes sessions, frees NPU heap
            # Long enough for an in-flight prefill chunk to finish (2048
            # tokens deep in a 32k context take ~25 s): killing a process
            # mid-launch can leave the TPU busy for the next one.
            await asyncio.wait_for(proc.wait(), timeout=UNLOAD_GRACE_S)
            return True
        except asyncio.TimeoutError:
            # A wedged worker must not wedge the manager.
            proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), timeout=KILL_GRACE_S)
                return True
            except asyncio.TimeoutError:
                info = self._models.get(model_id)
                if info is not None:
                    info.conflict = (
                        f"pid {proc.pid} 收到 SIGTERM 后 {UNLOAD_GRACE_S:.0f} 秒仍未退出；"
                        "它是接管来的进程，不会强杀（可能卡死 NPU），请人工处理")
                    info.loaded = False
                    info.port = None
                    info.loaded_at = None
                logger.error("model %s: worker pid %s survived SIGTERM and is not "
                             "killable from here", model_id, proc.pid)
                return False

    # -- idle management (docs/aux-models.md § 空闲自动卸载) -----------------
    #
    # An auxiliary model holds the NPU heap and several hundred MB of system RAM
    # for as long as it is loaded, and an operator typically loads one to try it
    # once. These three methods give that memory back without the operator
    # having to remember: ``touch`` records use, ``idle_unload_at`` answers when
    # a model would go, and ``unload_idle`` (driven by ``start_idle_sweeper``)
    # actually does it.
    def touch(self, model_id: str) -> None:
        """Record that ``model_id`` was just used.

        Called at the completion of a load and on every request that resolves to
        the model. Cheap and synchronous on purpose: it runs on the inference
        path before any await, so a concurrent sweep either sees the new
        timestamp or the request has not started yet -- there is no window in
        which a request is being served by a model the sweep believes is idle.
        """
        info = self._models.get(model_id)
        if info is None:
            return
        info.last_used_mono = time.monotonic()
        info.last_used_at = time.time()

    def idle_seconds(self, info: ModelInfo) -> float | None:
        """How long ``info`` has been idle, or None for a model idle never touches.

        None covers three cases the caller must not conflate with "idle for 0 s":
        a model with no idle threshold in force (its own or, for an auxiliary
        kind, the global default), an unloaded model, and one that has no
        recorded use (a model adopted from a previous run before this feature
        existed -- it is loaded, so its idle clock starts now rather than at an
        invented past instant).
        """
        if self.effective_idle_minutes(info) <= 0 or not info.loaded:
            return None
        if info.last_used_mono is None:
            return None
        return max(0.0, time.monotonic() - info.last_used_mono)

    def idle_unload_at(self, info: ModelInfo) -> float | None:
        """Epoch seconds at which ``info`` would be auto-unloaded, or None.

        None when the effective threshold is 0, when the model is not loaded, or
        when an operation is in flight -- the last because an operation is
        precisely when the deadline does not apply and a countdown shown in the
        console would be a lie.

        "Effective" means the model's own setting, or the global default for the
        kinds that default has ever covered (``effective_idle_minutes``) -- so a
        chat model an operator configured individually gets a countdown, and one
        left alone still reports None.
        """
        minutes = self.effective_idle_minutes(info)
        if minutes <= 0 or info.operation is not None:
            return None
        idle = self.idle_seconds(info)
        if idle is None or info.last_used_at is None:
            return None
        deadline = info.last_used_at + minutes * 60.0
        # Already past it (the sweep is up to one interval behind): report "now"
        # rather than a time in the past, so the console shows "about to go"
        # instead of a countdown that has already run out.
        return deadline if deadline > time.time() else time.time()

    async def _worker_is_busy(self, model_id: str) -> bool:
        """Whether ``model_id``'s worker is serving, or cannot prove it is not.

        The asymmetry is deliberate. An unload that fires mid-request kills a
        worker with a call on the NPU, which is the one thing this project does
        not do lightly; an unload that does not fire costs another 30 s of
        residency. So "cannot tell" answers True and the sweep simply tries
        again next interval.
        """
        probe = self.worker_inflight
        if probe is None:
            # No probe installed: only a test driving the manager directly gets
            # here, and there is no worker to be serving anything.
            return False
        try:
            count = await asyncio.wait_for(probe(model_id), timeout=3.0)
        except Exception:
            logger.debug("idle sweep: inflight probe for %s failed; treating as busy",
                         model_id, exc_info=True)
            return True
        if count is None:
            return True
        return count > 0

    async def unload_idle(self) -> list[str]:
        """Unload every model that has been idle past *its own* threshold.

        The four conditions are all required, and each rules out a different
        wrong unload:

          * the model's **effective** threshold (its own setting, else the
            global default for an auxiliary kind) is non-zero -- 0 means "never",
            not "immediately";
          * the model is settled and loaded -- no operation in flight (load,
            unload, download, update), which is what ``operation`` plus
            ``downloading`` say;
          * the worker reports no in-flight request;
          * it has actually been idle that long.

        The threshold is read per model, from inside the loop: reading one
        number before the loop would apply whichever model happened to be
        checked first, and a model with a 1-minute threshold beside one with an
        hour would then be unloaded on the other's schedule. A model whose own
        entry says 0 is skipped even when the global default is on, which is how
        an operator exempts one auxiliary model.

        Returns the ids actually unloaded, for the log and for the tests.
        """
        unloaded: list[str] = []
        # ``list()`` refreshes ``downloading`` on every entry, so the check below
        # reads the download manager's current answer rather than a copy that a
        # job started since the last poll left behind.
        for info in self.list():
            if info.operation is not None or info.downloading:
                continue
            minutes = self.effective_idle_minutes(info)
            if minutes <= 0:
                continue
            threshold = minutes * 60.0
            idle = self.idle_seconds(info)
            if idle is None or idle < threshold:
                continue
            if not self.still_loaded(info):
                # A dead worker reads as loaded until something reconciles it;
                # ``refresh``/``reconcile`` will report it, and unloading a pid
                # that is gone would invent an "idle unload" for a crash.
                continue
            # Snapshot before the probe: the probe awaits an RPC, and a request
            # resolving meanwhile touches the model. ``unload`` re-checks this
            # value under the model lock, in the same step that publishes
            # "unloading", so nothing that used the model after the snapshot is
            # unloaded from under it.
            since = info.last_used_mono
            if await self._worker_is_busy(info.model_id):
                continue
            idle = self.idle_seconds(info)
            if idle is None or idle < threshold or info.last_used_mono != since:
                continue
            logger.info("模型 %s 空闲 %d 分钟，自动卸载", info.model_id, int(idle // 60))
            try:
                await self.unload(info.model_id, if_unused_since=since)
            except (ModelBusy, KeyError) as exc:
                # Started serving (or vanished) between the check and the call:
                # both are "leave it alone", not failures.
                logger.info("idle unload of %s skipped: %s", info.model_id, exc)
                continue
            except Exception:
                logger.exception("idle unload of %s failed", info.model_id)
                continue
            info.unloaded_reason = "idle"
            unloaded.append(info.model_id)
        return unloaded

    async def _idle_sweeper(self) -> None:
        """The background loop. Cancelled by ``stop_idle_sweeper``."""
        while True:
            try:
                await asyncio.sleep(self.idle_sweep_interval_s)
            except asyncio.CancelledError:
                raise
            try:
                await self.unload_idle()
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - the sweep must not die
                logger.exception("idle unload sweep failed")

    def start_idle_sweeper(self) -> None:
        """Start the background sweep, if it is not already running.

        Idempotent: a test that builds two apps in one process, or a service
        that restarts the sweep after a settings change, must not end up with two
        loops unloading the same model.
        """
        if self._idle_task is not None and not self._idle_task.done():
            return
        self._idle_task = asyncio.get_running_loop().create_task(self._idle_sweeper())

    async def stop_idle_sweeper(self) -> None:
        """Stop and await the sweep. Safe to call when nothing is running."""
        task, self._idle_task = self._idle_task, None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    async def unload_all(self) -> None:
        """Stop every worker, including one still loading (service shutdown).

        This is the one path allowed to interrupt a load: the process is going
        away, and leaving a half-loaded worker behind would keep the NPU heap
        allocated across the restart.

        Deliberately does NOT take the per-model lock. That lock is held for the
        whole of a load (a minute or more), so a shutdown that queued behind it
        would delay the stop for no reason and then find the model it was
        supposed to reap had just finished loading. Terminating the process
        directly is enough: a load waiting on readiness sees ``returncode`` set,
        gives up, and unwinds through its own failure path.
        """
        # First, so a sweep cannot publish an unload while the shutdown runs and
        # then race the ``_forget`` below over the same ModelInfo.
        await self.stop_idle_sweeper()
        for mid in list(self._procs):
            try:
                await self._terminate(mid)
            except Exception:
                logger.exception("failed to unload %s", mid)
        # Whatever the race, nothing this run owns is running once this returns
        # -- and a model left claiming `loaded` would make the next boot's UI lie.
        #
        # A *conflicted* survivor is deliberately left alone: it was not adopted
        # because it never answered, so SIGTERM here could interrupt a worker
        # that is 90 s into mapping a 35B into NPU memory. It stays recorded and
        # stays refused-or-unloadable, which is the honest state.
        for info in self._models.values():
            if info.conflict:
                info.loaded = False
                info.adopted = False
                info.port = None
                info.loaded_at = None
                self._end(info)
                continue
            self._forget(info)
            self._end(info)

    def worker_stats(self, model_id: str) -> dict | None:
        return None  # filled in by the caller via an RPC; kept for interface symmetry

    # -- disk ------------------------------------------------------------
    def disk_usage(self) -> dict:
        total, used, free = shutil.disk_usage(self.models_root)
        models_bytes = sum(m.size_bytes for m in self._models.values())
        return {
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "models_bytes": models_bytes,
            "models_root": str(self.models_root),
        }
