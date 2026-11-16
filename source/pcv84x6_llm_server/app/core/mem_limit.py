"""Per-model device-memory accounting and limits (MYS-2675).

Three numbers per model, and the relations between them are the whole subject:

* **static** -- what the model occupies the moment it finishes loading and
  before it serves anything: weights, neuron workspace, and the input/output
  buffers. It comes from ``bmrt_get_bmodel_info`` when the device is readable
  and from the file size otherwise (see ``static_bytes``).
* **used** -- static *plus* whatever the live sessions hold: KV per token, the
  linear-attention state, and the prefix cache. Only meaningful while loaded.
* **limit** -- the ceiling an operator set for this model, or the derived
  default.

The limit is enforced twice, and the two checks answer different questions:

* **at load** (``check_load``): would this model's static footprint exceed the
  limit? Refused as a 409 with both numbers, because a model that cannot even
  hold its weights has nothing to serve.
* **at run time** (``runtime_budget_bytes``): how much may sessions and the
  prefix cache take? ``limit - static`` if that is positive, else the value the
  engine would have used anyway. The chat and OCR-VL schedulers make this their
  ``kv_budget_bytes``, so an over-budget request queues instead of allocating.

The derived default (``default_limit_bytes``) is static + a runtime allowance
rounded up to 64 MiB; ``docs/model-settings.md`` has the reasoning and a table
of the numbers for every model this release ships.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

#: Rounding for the derived default. A limit that lands a few MiB under a round
#: number is worse than useless: an operator reading "7943 MiB" cannot tell
#: whether it is a measurement or an accident, and the margin a model needs is
#: not known to 1 MiB anyway.
DEFAULT_ROUND_BYTES = 64 * 1024 * 1024

#: Fraction of the runtime allowance added on top as headroom. 10% covers the
#: difference between the estimate and what a real session allocates: fragment
#: alignment inside the heap, the vision tower's scratch on an image request,
#: and the tokenizer's host-side buffers. Measured on `.157` (docs/model-settings.md
#: § "默认上限的推算"), the estimate lands within 3% of the observed peak.
RUNTIME_HEADROOM = 0.10

#: Default completion length a session is budgeted for. The OpenAI default the
#: service applies when a request omits ``max_tokens`` (``openai_api``), so the
#: allowance describes the request an ordinary client actually sends.
DEFAULT_MAX_TOKENS = 512

#: Prompt length the allowance assumes. Not ``context_length``: budgeting 128k
#: tokens of KV for every model would derive a 30 GiB "default limit" for the
#: 128k 35B that no request ever reaches, and the first thing an operator would
#: do is raise it. 2048 is the length a chat turn (system prompt + a few
#: exchanges) actually occupies, and it is the whole context of the smaller
#: builds. Longer prompts are admitted against the *device's* free memory by the
#: scheduler, which is the check that scales with context.
DEFAULT_PROMPT_TOKENS = 2048

#: Prefix-cache allowance in the derived default, in bytes. 256 MiB is a *policy
#: choice about the default limit*, not a copy of any setting (the service-wide
#: ``prefix_cache_max_mb`` this used to mirror was deleted in MYS-2785). The
#: reasoning is unchanged: the default should be sized for a cache that is
#: useful on a 2k-token chat turn, and a board with a 35B loaded typically ends
#: up with a few hundred MiB to spare. Deriving the default from the *runtime
#: budget* would be circular -- that budget is ``limit - static``, and the limit
#: is what this function computes.
DEFAULT_PREFIX_CACHE_BYTES = 256 * 1024 * 1024

#: Kinds whose sessions cost KV proportional to the prompt and completion, and
#: therefore whose runtime allowance is derived rather than measured.
KV_KINDS = ("chat", "ocr_vl")


class _Memory(ctypes.Structure):
    """``memory_t`` from libsophon's ``bmdef.h``."""

    _fields_ = [
        ("addr", ctypes.c_int64),      # -1: invalid
        ("size", ctypes.c_uint64),
        ("type", ctypes.c_int),        # 0 device, 1 host
        ("number", ctypes.c_int),
        ("reserved", ctypes.c_char * 124),
    ]


class _MemInfo(ctypes.Structure):
    """``mem_info_t``: the five regions a bmodel allocates."""

    _fields_ = [
        ("instruction_mem", _Memory),
        ("variable_instruction_mem", _Memory),
        ("neuron_mem", _Memory),
        ("coeff_mem", _Memory),
        ("io_mem", _Memory),
        ("reserved", _Memory * 4),
    ]


#: The regions that make up a bmodel's static device footprint, in the order the
#: doc explains them.
INFO_REGIONS = ("coeff_mem", "neuron_mem", "io_mem",
                "instruction_mem", "variable_instruction_mem")

_LIBMRT = "/opt/sophon/libsophon-current/lib/libbmrt.so"
_bmrt_cache: dict = {"tried": False, "lib": None}


def _bmrt():
    """libbmrt, or None where it is not installed (host tests, x86 CI).

    Loaded once. ``bmrt_get_bmodel_info`` parses the file and allocates nothing,
    so it is safe on the management plane -- but it still needs the vendor
    library, which a dev checkout does not have.
    """
    if _bmrt_cache["tried"]:
        return _bmrt_cache["lib"]
    _bmrt_cache["tried"] = True
    lib = None
    path = os.environ.get("CV84X6_LIBMRT") or _LIBMRT
    try:
        lib = ctypes.CDLL(path)
        lib.bmrt_get_bmodel_info.argtypes = [ctypes.c_char_p, ctypes.POINTER(_MemInfo)]
        lib.bmrt_get_bmodel_info.restype = ctypes.c_bool
    except (OSError, AttributeError):
        lib = None
    _bmrt_cache["lib"] = lib
    return lib


def reset_bmrt_cache() -> None:
    """Forget the loaded library. Tests only; production loads it once."""
    _bmrt_cache["tried"] = False
    _bmrt_cache["lib"] = None


def bmodel_info(path: str | Path) -> dict | None:
    """The static device/host split of one bmodel, or None when unreadable.

    ``device_bytes`` is what this file costs the NPU/VPP heaps once mapped:
    coefficient weights, the neuron workspace, and the I/O buffers -- the three
    regions `bm-smi` sees grow when a model loads. Instructions are host-side
    on this chip and excluded from the device figure, which is why they are
    reported separately rather than lumped in.
    """
    lib = _bmrt()
    if lib is None:
        return None
    info = _MemInfo()
    try:
        if not lib.bmrt_get_bmodel_info(str(path).encode(), ctypes.byref(info)):
            return None
    except (OSError, ValueError):
        return None
    regions = {}
    device = host = 0
    for name in INFO_REGIONS:
        region = getattr(info, name)
        size = int(region.size)
        regions[name] = {"size": size, "type": int(region.type),
                         "count": int(region.number)}
        if int(region.type) == 0:
            device += size
        else:
            host += size
    return {"device_bytes": device, "host_bytes": host, "regions": regions}


def estimate_static_bytes(info) -> int:
    """A pre-load estimate of ``info``'s static device footprint, in bytes.

    Every file the worker may map, because an OCR model is five bmodels and the
    worker loads the recogniser tiers lazily on the first request of each width
    -- a limit computed from the detector alone would be exceeded by the first
    page it recognises. ``bmrt_get_bmodel_info`` answers per file, so the sum is
    taken here.

    **IO is deliberately excluded from the estimate.** That is not an oversight:
    ``bmrt_get_bmodel_info`` reports ``io_mem`` as the sum of every net stage's
    ``io_size`` at its *maximum* shape, and for a dynamic/history build that
    overstates the memory the loaded engine actually holds by a wide margin.
    Measured on the new board (`.155`, 2026-11-07, docs/model-settings.md § 实测):

        model                 bmrt coeff+neuron+instr   bmrt io    loaded
        qwen3.6-35b 128k                20122 MiB    17971 MiB  22752 MiB
        qwen3-embedding-0.6b (seq2048)   1276 MiB      225 MiB   1465 MiB
        qwen3-embedding-0.6b (seq512)      ? MiB        ? MiB   1217 MiB
        qwen3-asr-0.6b                   1531 MiB      113 MiB   1639 MiB
        bge-reranker-v2-m3               1165 MiB        0 MiB   1136 MiB
        ppocrv6 det+layout                186 MiB        0 MiB    154 MiB

    The two embedding rows are the seq2048 build this release ships and the
    optional seq512 one (MYS-2706), measured the same way on `.157`. The
    footprint is dominated by the bf16 weights, which do not depend on SEQLEN:
    4x the sequence length (512 -> 2048) only moves the heap 1217 -> 1465 MiB
    (``docs/research/aux-dynamic-seq.md`` §6.1, ``tools/embed/seq512_bench.py``).
    Each model is its own worker process, so two resident builds cost the sum;
    the bench's lower "together" figure is an in-process reuse the service never
    sees. The 1344-vs-1600 difference in the derived
    defaults is just the smaller static figure, not a setting anybody maintains.

    Including the declared IO would derive a 55 GiB "default limit" for the 35B
    on a 34 GiB board. Without it the estimate lands within -13%..+2% of the
    loaded figure for every model this release ships, and the runtime allowance's
    10% headroom covers the shortfall -- so the derived default never refuses a
    configuration that works today.

    Falls back to the file sizes when libbmrt is unavailable (host tests, a
    checkout without the vendor library). For a bf16 build that is close (the
    weights are the file); for int4 it under-states, which only makes the default
    more permissive, and the *measured* value replaces it the first time the
    model loads.
    """
    paths = []
    for name in getattr(info, "bmodel_files", ()) or ():
        path = Path(info.path) / name
        if path.exists():
            paths.append(path)
    if not paths:
        # A directory whose files vanished between discovery and this call. The
        # recorded size is the best answer left, and refusing here would turn a
        # disk problem into a memory-limit refusal.
        return int(getattr(info, "size_bytes", 0) or 0)
    measured = 0
    measured_any = False
    files = 0
    for path in paths:
        got = bmodel_info(path)
        if got is not None:
            regions = got["regions"]
            measured += sum(
                int(regions[name]["size"]) for name in INFO_REGIONS
                if name != "io_mem" and regions[name]["type"] == 0)
            measured_any = True
        else:
            try:
                files += path.stat().st_size
            except OSError:
                pass
    return measured + files if measured_any else files


def static_bytes(info) -> int:
    """``estimate_static_bytes`` under its old name.

    Kept because the estimate is also the fallback wherever a measurement has
    not been taken; ``ModelManager.static_bytes`` is the accessor callers should
    use, since it prefers the measured value.
    """
    return estimate_static_bytes(info)


def runtime_allowance_bytes(info, *, max_concurrent: int, backend=None) -> int:
    """The runtime footprint the derived default budgets for ``info``, in bytes.

    What a session costs *after* the model is loaded, by kind:

    * ``chat`` / ``ocr_vl`` -- per session, ``linear_state_bytes +
      kv_bytes_per_token * (prompt + completion)``, times the concurrency the
      settings allow, plus one prefix cache's worth. The backend is asked when
      it is loaded; otherwise the per-kind constant below stands in, because the
      management plane must be able to answer "what is this model's default
      limit" for a model it has never loaded.
    * anything else (embedding / rerank / asr / ocr) -- a fixed working buffer.
      Those engines hold no cross-request KV: one call is one forward, so there
      is nothing to scale with concurrency.

    The result is multiplied by ``1 + RUNTIME_HEADROOM``.
    """
    kind = getattr(info, "kind", "chat")
    if kind in KV_KINDS:
        per_tok, linear = _session_cost(info, backend)
        tokens = prompt_completion_tokens(info)
        sessions = max(1, int(max_concurrent or 1))
        raw = (linear + per_tok * tokens) * sessions + DEFAULT_PREFIX_CACHE_BYTES
    else:
        raw = AUX_WORKING_BYTES.get(kind, AUX_WORKING_BYTES["default"])
    return int(raw * (1.0 + RUNTIME_HEADROOM))


#: Per-session KV cost used when the backend cannot be asked, as
#: ``(kv_bytes_per_token, linear_state_bytes)`` -- the two figures the engine
#: reports through ``llm_engine_kv_bytes_per_token`` / ``llm_engine_linear_state_bytes``.
#:
#: Read off the loaded engines on the new board (`.155`, 2026-11-07) rather than
#: derived on paper, because the layer mix is what decides them: the Qwen3.5/3.6
#: A3B build has 40 layers of which only 10 are full attention, so the per-token
#: KV is 20 KiB (10 layers x 1 KiB K + V), not the 2 MiB a "35B at bf16" guess
#: gives. The linear-attention layers hold a fixed 31.9 MiB per session instead.
_FALLBACK_SESSION = {
    "chat": (20480, 33423360),
    # PaddleOCR-VL: one session, KV allocated whole at 36 MiB, no per-token part.
    "ocr_vl": (0, 36 * 1024 * 1024),
}

#: Working buffers for the kinds whose engines hold no KV between requests.
#: Measured on `.155` as (loaded footprint - static estimate); the numbers here
#: are the observed deltas rounded up to 16 MiB.
AUX_WORKING_BYTES = {
    "embedding": 96 * 1024 * 1024,
    "rerank": 128 * 1024 * 1024,
    "asr": 192 * 1024 * 1024,
    "ocr": 160 * 1024 * 1024,
    "default": 128 * 1024 * 1024,
}


def _session_cost(info, backend=None) -> tuple[int, int]:
    """``(kv_bytes_per_token, linear_state_bytes)`` for one session.

    The live backend wins when there is one: it read the figures off the loaded
    graphs, and a rebuild with a different layer mix changes them. The fallback
    table is keyed by kind and exists so an unloaded model still has a number.
    """
    per_tok = int(getattr(backend, "kv_bytes_per_token", 0) or 0)
    linear = int(getattr(backend, "linear_state_bytes", 0) or 0)
    if per_tok or linear:
        return per_tok, linear
    return _FALLBACK_SESSION.get(getattr(info, "kind", "chat"), (0, 0))


def prompt_completion_tokens(info) -> int:
    """Tokens one session is budgeted for: the default prompt + completion.

    Capped by the model's own context, because a 2048-token prompt plus a
    512-token completion does not fit a 2048-token model and budgeting for it
    would over-state that model's needs by 25%.
    """
    context = int(getattr(info, "context_length", 0) or 0)
    want = DEFAULT_PROMPT_TOKENS + DEFAULT_MAX_TOKENS
    return min(want, context) if context else want


def default_limit_bytes(info, *, max_concurrent: int = 1, backend=None,
                        static: int | None = None) -> int:
    """The derived default limit for ``info``: static + runtime, rounded up.

    Static comes from the bmodel itself, so the default is per model without
    anybody maintaining a table; the runtime half scales with the concurrency
    setting, so raising ``max_concurrent_per_model`` raises every model's default
    by what the extra sessions need -- which is the honest answer, since they do
    take that memory.

    **Self-consistent by construction**, and that property is load-bearing: the
    default is derived from the *same* static figure the load-time check compares
    against, so a default limit can never refuse a load. That matters because the
    static figure is an estimate until the model has been loaded once (a `int4`
    build's file understates its weights by ~15%), and a default derived from any
    *other* number would turn "the first load worked" into "the second one is
    refused" for a model nobody configured. The default therefore moves the first
    time a model is loaded -- from estimate to measurement -- and settles.
    """
    base = static_bytes(info) if static is None else int(static)
    total = base + runtime_allowance_bytes(
        info, max_concurrent=max_concurrent, backend=backend)
    return round_up(total)


def round_up(value: int, unit: int = DEFAULT_ROUND_BYTES) -> int:
    """``value`` rounded up to the next multiple of ``unit`` (never 0)."""
    if value <= 0:
        return unit
    return ((int(value) + unit - 1) // unit) * unit


def runtime_budget_bytes(limit_bytes: int, static: int) -> int:
    """Bytes sessions and the prefix cache may share under ``limit_bytes``.

    ``limit - static``, floored at zero. Zero is a real answer, not an error:
    it means the limit leaves nothing for sessions, and the scheduler's own
    ``_fits`` already treats a zero budget as "admit nothing that needs KV"
    (a lone session still fits, because it is the one the static figure was
    measured against).
    """
    return max(0, int(limit_bytes) - int(static))


#: NPU heap that must stay free for the chip to keep working (MYS-2703).
#:
#: Not a performance margin: below roughly half a gigabyte of free NPU heap the
#: TPU wedges. Measured on 10155 with the load held constant (five models,
#: ``chat`` x2, a ballast process taking the difference, so only the free figure
#: varied):
#:
#:     free NPU    result
#:     ~280 MiB    wedge in 126-136 s, 0 requests completed   (5 runs)
#:      512 MiB    wedge at 135.8 s, 0 requests completed
#:      640 MiB    12 min clean, 398/398
#:     1024 MiB    12 min clean, 404/404
#:
#: The wedge is not an application failure the request can survive: the driver
#: stops receiving completions (`recvmsg_cnt` freezes, `using_flag` stays
#: `0xa5a5`) and only a reboot clears it. So this is a floor on *headroom*, not
#: on the sum of what is loaded -- see ``_check_npu_reserve``.
#:
#: 1024 MiB is deliberately above the measured boundary (between 512 and 640).
#: The sweep is 12 min per point, and the pre-existing evidence for this failure
#: is that a clean 20 min does not imply a clean few hours (MYS-2693 R17: 130
#: clean minutes, then a wedge), so a floor set at the exact cliff has no margin
#: for the slow path. Overridable with ``CV84X6_NPU_RESERVE_MB``; 0 disables the
#: check, which is what a board without this failure mode would want.
NPU_RESERVE_DEFAULT_BYTES = 1024 * 1024 * 1024
NPU_RESERVE_ENV = "CV84X6_NPU_RESERVE_MB"


def npu_reserve_bytes() -> int:
    """The configured NPU headroom floor, in bytes (0 disables the check)."""
    raw = os.environ.get(NPU_RESERVE_ENV)
    if raw is None or not raw.strip():
        return NPU_RESERVE_DEFAULT_BYTES
    try:
        mb = int(raw.strip())
    except ValueError:
        return NPU_RESERVE_DEFAULT_BYTES
    return max(0, mb) * 1024 * 1024
