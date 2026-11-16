"""Fair, cancellable, one-worker-per-model request scheduler.

How the work is shared out. One decode step on CV84X6 is a single serial chain
of graph launches -- measured 33.4 ms/token at short context, 46.4 ms at 17k
(docs/research/decode-optimization.md §4) -- and the TPU has no slack inside it to run a
second session on. Running requests one-at-a-time would therefore serialise
clients, so this scheduler advances every live request round-robin and they all
stream concurrently.

Round-robin is not free: the engine keeps one session resident and parks the
others, and a switch copies 34.7 MB of linear-attention state per lane
(``Session::Impl::park``/``unpark``, §5.1). Advancing every request by exactly
one token pays that 34.7 MB per token per session, which is why concurrency
used to *lower* aggregate throughput: 2 sessions ran at 0.71x a single stream,
2048-token context at 0.69x. A bounded decode quantum amortises the switch: an
8-token slice measured 0.94x over the same two sessions (0.93x at 2048), with
the generated tokens byte-identical to the one-token-per-visit order. The
quantum is the knob; ``decode_quantum=1`` is the old behaviour.

Three properties matter and all are tested:

* **No starvation** -- a long request cannot block a short one behind it, and a
  quantum never lets one session hold the TPU past N tokens.
* **Prompt cancellation** -- a client that disconnects frees its KV immediately,
  mid-quantum included: every token yields to the event loop.
* **Prefill still interleaves** -- prefill hands the worker back after one
  chunk, whatever the quantum is.
"""

from __future__ import annotations

import asyncio
import codecs
import collections
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Sequence

from .base import EngineBackend, GenerateParams, Session, Token
from .prefix_cache import PrefixCache

# Prefill is chopped into chunks of this many tokens so that a long prompt does
# not monopolise the NPU for seconds while other sessions wait.
PREFILL_CHUNK = 256

# Tokens one request may decode before the round-robin moves on. 8 amortises the
# 34.7 MB park/unpark a switch costs (measured 0.71x -> 0.94x for two sessions,
# docs/research/decode-optimization.md §5.1) while keeping a slice ~270 ms long, so a
# disconnect still frees the session promptly. 1 is the old per-token rotation.
DEFAULT_DECODE_QUANTUM = 8
# Upper bound: past this a slice is seconds long and cancellation latency grows
# with it, with no throughput left to win (the switch tax is already paid once
# per slice at 8).
MAX_DECODE_QUANTUM = 32


# ``on_token`` receives decoded text; it is awaited so a slow client applies
# backpressure instead of buffering without bound.
TokenSink = Callable[[str], Awaitable[None]]


# Prompts this long get their last `exact_tail` tokens prefilled through the
# decode graphs. Shorter ones get at most SHORT_EXACT_TAIL: the full tail's
# replay (~40 ms per token) would multiply their few-second prefill.
EXACT_TAIL_MIN_PROMPT = 2048
# Prefill only runs 64-row multiples, so a short prompt with n % 64 < 8 used to
# reach the model almost entirely through the inaccurate prefill graphs, and
# 5/40 of such questions never started answering (MYS-2403, MYS-2405: every
# failure had 0-7 exact rows, none with 8+). 16 exact rows fixed them and left
# prompts that already had 16+ exact rows token-identical. The prefill head
# stays 64-aligned, so no new graph width is ever launched.
SHORT_EXACT_TAIL = 16


class Busy(RuntimeError):
    """The queue is full; the request was not accepted."""


@dataclass
class Request:
    req_id: str
    prompt_tokens: list[Token]
    params: GenerateParams
    session: Session | None = None
    state: str = "pending"  # pending | prefill | decode | done | error
    generated: list[Token] = field(default_factory=list)
    cached_tokens: int = 0
    first_token_at: float | None = None
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    finish_reason: str = "stop"
    error: str | None = None
    cancelled: bool = False
    prefill_pos: int = 0
    # Prompt offsets at which to snapshot the session for the prefix cache
    # (backends whose state can only be captured at the current length).
    snap_points: list[int] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)
    # Joins the bytes of consecutive tokens before they become text. A
    # byte-level tokenizer splits a character across tokens (a 3-byte CJK
    # character can arrive as 3 + 2 + 1 bytes over three ids), and a fragment
    # decoded on its own is U+FFFD forever. Feeding the bytes through an
    # incremental decoder keeps an incomplete tail pending until the rest
    # arrives (MYS-2496).
    utf8: codecs.IncrementalDecoder = field(
        default_factory=lambda: codecs.getincrementaldecoder("utf-8")(errors="replace"))
    on_token: TokenSink | None = None
    done_event: asyncio.Event | None = None

    @property
    def prompt_len(self) -> int:
        return len(self.prompt_tokens)


# Lengths of the repeating span to look for, and how many repeats to tolerate.
# A repeat has to be long enough to be a stuck generation rather than natural
# repetition ("the the", "\n\n</think>\n\n"). Spans below this cut good output.
_LOOP_MIN_SPAN = 6
_LOOP_REPEATS = 3


def _is_looping(tokens: list[int]) -> bool:
    """True when the tail of `tokens` is the same span repeated verbatim.

    Only the tail is examined, so a long generation that legitimately restates a
    phrase early on is not cut off.
    """
    n = len(tokens)
    for span in range(_LOOP_MIN_SPAN, 33):
        need = span * _LOOP_REPEATS
        if n < need:
            break
        tail = tokens[-need:]
        unit = tail[:span]
        if all(tail[i * span:(i + 1) * span] == unit for i in range(1, _LOOP_REPEATS)):
            return True
    return False


def clamp_decode_quantum(value: object) -> int:
    """Force a decode quantum into [1, MAX_DECODE_QUANTUM].

    Settings arrive from a console request, a CLI flag or a state file, so a
    bad value has to land in range rather than reach the loop: 0 would never
    advance a request and a huge number would hold the TPU for seconds. A bool
    is rejected rather than read as 0/1 -- ``true`` is a client mistake, not a
    request for per-token rotation.
    """
    if isinstance(value, bool):
        return DEFAULT_DECODE_QUANTUM
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_DECODE_QUANTUM
    return max(1, min(MAX_DECODE_QUANTUM, n))


class Scheduler:
    """Drives many sessions over one set of weights."""

    def __init__(
        self,
        backend: EngineBackend,
        prefix_cache: PrefixCache | None = None,
        max_concurrent: int = 3,
        max_queue: int = 16,
        decode_quantum: int = DEFAULT_DECODE_QUANTUM,
    ) -> None:
        self.backend = backend
        # Not `prefix_cache or ...`: an empty PrefixCache has len 0 and is falsy,
        # which silently replaced the configured cache (and its NPU budget).
        self.prefix_cache = prefix_cache if prefix_cache is not None else PrefixCache()
        self.max_concurrent = max_concurrent
        # Requests waiting for a slot. Past this the worker refuses (HTTP 429)
        # instead of letting a backlog grow without bound behind 3 slots.
        self.max_queue = max_queue
        # A backend with one KV cache (PaddleOCR-VL) cannot hold two sessions,
        # so it runs one at a time whatever the slot count says. The queue is
        # the only thing that grows, which is the same contract a caller sees
        # when max_concurrent is 1 -- it just cannot be configured away.
        if getattr(backend, "serial_only", False):
            self.max_concurrent = 1
        self.rejected_requests = 0
        self._last_expire = 0.0
        # NPU bytes live sessions and the prefix cache may share (free memory
        # after the model loaded, minus a margin); set by the worker. None =
        # unknown, admit by slot count alone.
        self.kv_budget_bytes: int | None = None
        #: The *device* reading the figure above started from, kept when a
        #: per-model memory limit trims it down (MYS-2785). Both are the same
        #: quality of number -- "bytes this worker may put on the NPU heap beyond
        #: the weights" -- and only ``kv_budget_bytes`` is enforced; the pair is
        #: reported so the console can say which ceiling bound the cache, and so
        #: raising a limit can raise the budget back without reloading.
        self.device_budget_bytes: int | None = None
        #: The per-model ceiling's own figure (``limit - static``), or None when
        #: no limit is in force. Not enforced directly -- ``kv_budget_bytes`` is
        #: the minimum of this and ``device_budget_bytes`` -- but reported, and
        #: it is what the prefix cache is capped at now that the service-wide
        #: byte ceiling is gone (MYS-2785).
        self.model_budget_bytes: int | None = None
        #: The static footprint ``model_budget_bytes`` was computed against, byte
        #: exact. Reported so the two sides of ``limit - static`` can be compared
        #: without a second RPC: a load that measured its model after the worker
        #: started (MYS-2805) has to prove the worker ended up on the *same* figure
        #: the management plane reports, and a MiB-truncated copy on either side
        #: would make the budget look settled when it is a remainder off.
        self.model_static_bytes: int | None = None
        #: An **operator instruction** that caps the cache independently of any
        #: budget: ``--device-kv-budget-mb`` (the A/B harnesses' switch) or the
        #: explicit ``--no-prefix-cache`` (MYS-2785). Its precedence differs from
        #: the budgets above, which is why it is its own field rather than a
        #: fallback -- see ``worker.configure``: ``0`` means **off** and must
        #: win even when a device reading exists, while a non-zero value is a
        #: ``min`` on top of the model's budget and can never raise it.
        #: None = no instruction.
        self.cache_cli_cap_bytes: int | None = None
        self.memory_waits = 0
        self._memory_blocked = False
        # Tokens at the end of a long prompt prefilled through the decode
        # graphs (backends with Session.set_exact_tail); set by the worker.
        self.exact_tail = 0
        self._decode_quantum = clamp_decode_quantum(decode_quantum)
        if hasattr(backend, "oom_relief"):
            backend.oom_relief = self._relieve

        self._queue: collections.deque[Request] = collections.deque()
        self._active: list[Request] = []
        self._pending: dict[str, Request] = {}
        self._wakeup = asyncio.Event()
        self._shutdown = False
        self._task: asyncio.Task | None = None

        # Counters surfaced to the UI.
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_requests = 0
        self.failed_requests = 0
        self.cancelled_requests = 0
        self._decode_times: collections.deque[float] = collections.deque(maxlen=64)

    # -- lifecycle ------------------------------------------------------
    @property
    def cache_fallback_bytes(self) -> int | None:
        """Old name of ``cache_cli_cap_bytes``, kept as an alias.

        The first attempt at this change called the field ``cache_fallback_bytes``
        and gave it *fallback* precedence, which is the bug the reviewer's repro
        caught. The name is wrong for what the value now does -- an operator
        instruction that outranks the inferred budget -- so the field was renamed;
        the alias stays so a script written against that intermediate commit (the
        attached repro included) keeps working.
        """
        return self.cache_cli_cap_bytes

    @cache_fallback_bytes.setter
    def cache_fallback_bytes(self, value: int | None) -> None:
        self.cache_cli_cap_bytes = value

    @property
    def decode_quantum(self) -> int:
        """Tokens a request decodes per round-robin visit (1..32)."""
        return self._decode_quantum

    @decode_quantum.setter
    def decode_quantum(self, value: object) -> None:
        # A console reconfiguration must not disturb requests already running:
        # the loop reads this attribute at the top of every slice, so the new
        # value simply applies from the next visit on.
        self._decode_quantum = clamp_decode_quantum(value)

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="scheduler")

    async def stop(self) -> None:
        self._shutdown = True
        self._wakeup.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        for req in list(self._active) + list(self._pending.values()):
            if req.session is not None:
                await req.session.close()
        self._active.clear()
        self._pending.clear()
        self._queue.clear()

    # -- public API -----------------------------------------------------
    def submit(self, req_id: str, prompt_tokens: Sequence[Token], params: GenerateParams) -> Request:
        # Capacity = running slots + waiting room; a request passes through the
        # queue on its way to a slot, so the queue alone is not the measure.
        if len(self._active) + len(self._queue) >= self.max_concurrent + self.max_queue:
            self.rejected_requests += 1
            raise Busy(f"{len(self._active)} requests running and {len(self._queue)} queued; "
                       "try again later")
        # Keep a list subclass as-is: the native backend's Prompt carries the
        # image inputs and M-RoPE positions alongside the ids.
        tokens = prompt_tokens if isinstance(prompt_tokens, list) else list(prompt_tokens)
        req = Request(req_id=req_id, prompt_tokens=tokens, params=params)
        self._pending[req_id] = req
        self._queue.append(req)
        self.total_requests += 1
        self._wakeup.set()
        return req

    def cancel(self, req_id: str) -> bool:
        req = self._pending.get(req_id)
        if req is None:
            return False
        req.cancelled = True
        self._wakeup.set()
        return True

    # -- NPU memory --------------------------------------------------------
    def reservation(self, req: Request) -> int:
        """Reserve linear state plus the FA park-buffer allocation peak.

        Native parking rounds capacity to granules and grows by at least 1.5x,
        allocating the replacement before freeing the old buffer. The bound
        includes both buffers; it can exceed the final resident allocation.
        Backends without ``park_granule`` retain their raw-token calculation.
        """
        per_tok = int(getattr(self.backend, "kv_bytes_per_token", 0) or 0)
        if not per_tok:
            return 0
        tokens = min(self.backend.context_length, req.prompt_len + int(req.params.max_tokens))
        return int(getattr(self.backend, "linear_state_bytes", 0) or 0) \
            + per_tok * self._parked_slots(tokens)

    def _parked_slots(self, tokens: int) -> int:
        """Bound FA slots across all park/growth histories up to ``tokens``.

        ``ensure_park`` grows only when old_cap < need <= tokens. Before that
        growth, old_cap is a granule multiple (a context-capped buffer cannot
        grow again). Its largest possible value is therefore the last multiple
        strictly below tokens. Both new_cap and old_cap + new_cap increase with
        old_cap and need, so evaluating those two maxima bounds every history,
        including skipped lengths and the allocation-before-free transient.
        """
        granule = int(getattr(self.backend, "park_granule", 0) or 0)
        seq = int(getattr(self.backend, "context_length", 0) or 0)
        need = min(tokens, seq) if seq else int(tokens)
        if granule <= 0 or need <= 0:
            return int(need)

        old = ((need - 1) // granule) * granule
        want = max(need, old + old // 2)
        new = ((want + granule - 1) // granule) * granule
        if seq:
            new = min(new, seq)
        return old + new

    def _fits(self, req: Request) -> bool:
        """Whether ``req`` can join the running sessions without risking an NPU
        allocation failure mid-generation. A lone session never parks, so it
        always fits; the prefix cache gives way to sessions."""
        budget = self.kv_budget_bytes
        if budget is None or not self._active or not self.reservation(req):
            return True
        need = self.reservation(req) + sum(self.reservation(a) for a in self._active)
        if need > budget:
            return False
        self._make_cache_room(need)
        return True

    def _make_cache_room(self, need: int) -> None:
        """Evict cache entries until ``need`` bytes of reservations fit.

        One spelling of the invariant, used by both the admission path and the
        cache-insertion path -- they were two, and only one of them existed.
        """
        budget = self.kv_budget_bytes
        if budget is None:
            return
        while need + self.prefix_cache.nbytes > budget and self.prefix_cache.evict_one():
            pass

    def _snapshot_bytes(self, tokens: int) -> int:
        """Device bytes a snapshot covering ``tokens`` will allocate.

        **The linear-attention state is part of it.** ``Session::snapshot``
        allocates, for every layer, ``len * kv_bytes`` for a full-attention layer
        and ``mem_size(state_a) + mem_size(state_b)`` for a linear one -- i.e. a
        snapshot carries the whole linear state no matter how short the prefix.
        Counting only ``per_tok * tokens`` under-charged every entry by that
        figure (25.5 MiB on the 9B, 31.9 MiB on the 35B), which is the residual
        the second acceptance round still measured after the park-granule fix.

        A backend that states nothing falls back to ``tokens * 4096``, which errs
        large and is therefore safe.
        """
        per_tok = int(getattr(self.backend, "kv_bytes_per_token", 0) or 0)
        if per_tok:
            linear = int(getattr(self.backend, "linear_state_bytes", 0) or 0)
            return linear + per_tok * int(tokens)
        return int(tokens) * 4096

    def _cache_room_for(self, prompt_len: int) -> bool:
        """Whether a snapshot of ``prompt_len`` fits beside the live sessions.

        The cache had no such check: ``PrefixCache.put`` enforces its own
        ``max_bytes``, which is the *whole* budget, so a snapshot arriving while
        sessions were parked was added on top of reservations that had already
        spent it. That is the measured defect (MYS-2784): 757 MiB of
        reservations plus 753 MiB of cache against a 1056 MiB budget, heap at
        2 MiB free.

        Checked **before** the snapshot is taken, not after it is inserted, for a
        reason that only shows on the board: ``NativeSession.snapshot`` is what
        allocates the device memory, so trimming after the insert would evict a
        different entry to pay for one that had already been charged to the heap.

        Evicting to make room is the same trade ``_fits`` makes, and the same
        priority order: sessions are live work, the cache is an optimisation.
        Returns False -- skip the insert -- when even an empty cache would not
        have room, which is the honest answer near the floor.
        """
        budget = self.kv_budget_bytes
        if budget is None or not self._active:
            return True
        need = sum(self.reservation(a) for a in self._active)
        want = self._snapshot_bytes(prompt_len)
        if need + want > budget:
            return False
        while need + want + self.prefix_cache.nbytes > budget and self.prefix_cache.evict_one():
            pass
        return need + want + self.prefix_cache.nbytes <= budget

    def _relieve(self, keep: object = None) -> bool:
        """An engine call ran out of NPU memory: drop one cache entry."""
        return self.prefix_cache.evict_one(exclude=keep)

    def used_bytes(self) -> int:
        """Device bytes the live sessions and the prefix cache hold *now*.

        Not ``kv_reserved_bytes``: that is the admission figure -- what each
        running request could claim at its full ``prompt + max_tokens`` -- and
        reporting it as "used" would show a session at its ceiling from its first
        token. This is the same per-session arithmetic at the length the session
        actually reached, plus the cache's own bytes.

        Approximate by construction: ``token_len`` comes from the backend and
        includes the tokens decoded so far, which is what the KV holds. A backend
        without per-token KV (PaddleOCR-VL allocates its KV whole) reports its
        fixed state instead, which is why the per-session term falls back to the
        backend's ``session_state_bytes`` when ``kv_bytes_per_token`` is 0.
        """
        per_tok = int(getattr(self.backend, "kv_bytes_per_token", 0) or 0)
        state = int(getattr(self.backend, "linear_state_bytes", 0) or 0)
        total = 0
        for req in self._active:
            session = req.session
            if session is not None and per_tok:
                total += state + per_tok * int(getattr(session, "token_len", 0) or 0)
            else:
                # No per-token KV (one KV cache allocated whole), or a request
                # that has not built its session yet: the fixed figure is the
                # honest answer for what this session costs.
                total += int(getattr(self.backend, "session_state_bytes", 0) or 0)
        return total + int(self.prefix_cache.nbytes)

    def stats(self) -> dict:
        avg_decode = (
            sum(self._decode_times) / len(self._decode_times) if self._decode_times else 0.0
        )
        return {
            "active": len(self._active),
            # The idle sweep's own question, under the name it asks it by. For a
            # chat worker the answer is "how many sessions are running", which
            # ``active`` already is -- but the sweep reads ``inflight`` because
            # that is what an auxiliary worker reports, and without this key the
            # sweep treated every chat model as busy, so a chat model an
            # operator put under idle unload could never actually be unloaded
            # (MYS-2675). Queued requests do not count: they hold no session and
            # the head of the queue is waiting for a slot, not for the NPU.
            "inflight": len(self._active),
            "queued": len(self._queue),
            "max_concurrent": self.max_concurrent,
            "max_queue": self.max_queue,
            "decode_quantum": self._decode_quantum,
            "rejected_requests": self.rejected_requests,
            "kv_budget_bytes": self.kv_budget_bytes,
            # The two ceilings that produced the figure above, so the console can
            # say *why* the cache stopped where it did: the model's own runtime
            # budget (``limit - static``) and what the device can spare. The
            # effective value is their minimum, and either may be null (no limit
            # configured / no bm-smi).
            "mem_runtime_budget_bytes": self.model_budget_bytes,
            "mem_static_bytes": self.model_static_bytes,
            "device_budget_bytes": self.device_budget_bytes,
            "kv_reserved_bytes": sum(self.reservation(a) for a in self._active),
            # What the live sessions and the prefix cache are holding right now,
            # which is what a per-model memory limit is about (MYS-2675). The
            # reservation is the *admission* figure (prompt + max_tokens); this
            # is the same arithmetic at the sessions' current lengths, so a card
            # showing "used" does not report room a request has not taken yet.
            "kv_used_bytes": self.used_bytes(),
            "waiting_for_memory": self._memory_blocked,
            "memory_waits": self.memory_waits,
            "supports_sampling": getattr(self.backend, "supports_sampling", True),
            "total_requests": self.total_requests,
            "failed_requests": self.failed_requests,
            "cancelled_requests": self.cancelled_requests,
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "avg_decode_tps": (1.0 / avg_decode) if avg_decode else 0.0,
            "cache": {
                "entries": len(self.prefix_cache),
                "location": getattr(getattr(self.backend, "snapshot_store", None), "kind", "n/a"),
                "enabled": bool(getattr(self.backend, "kv_snapshots_verified", True)),
                "bytes": self.prefix_cache.nbytes,
                "max_bytes": self.prefix_cache.max_bytes,
                "max_entries": self.prefix_cache.max_entries,
                "ttl_s": self.prefix_cache.ttl_s,
                "expirations": self.prefix_cache.stats.expirations,
                "hit_rate": self.prefix_cache.stats.hit_rate,
                "tokens_reused": self.prefix_cache.stats.tokens_reused,
                "tokens_prompted": self.prefix_cache.stats.tokens_prompted,
                "evictions": self.prefix_cache.stats.evictions,
            },
        }

    # -- the loop -------------------------------------------------------
    async def _run(self) -> None:
        while not self._shutdown:
            now = time.monotonic()
            if now - self._last_expire > 10:
                self._last_expire = now
                self.prefix_cache.expire()
            self._admit()
            progressed = False
            # Round-robin over active sessions: a bounded slice each, then
            # loop. The slice is one token when `decode_quantum` is 1 (a full
            # park/unpark per token) and 8 by default, which amortises the
            # switch while still handing the worker back every few tokens.
            for req in list(self._active):
                if req.cancelled:
                    await self._finish(req, reason="cancelled")
                    continue
                try:
                    await self._advance(req)
                    progressed = True
                except Exception as exc:  # a backend failure must not kill the loop
                    # A dying client surfaces as a write error from the token
                    # sink. That is a cancellation, not an inference failure --
                    # counting it as an error would make the dashboard blame the
                    # model for the browser tab being closed.
                    if req.cancelled or isinstance(
                        exc, (ConnectionResetError, BrokenPipeError, asyncio.CancelledError)
                    ):
                        await self._finish(req, reason="cancelled")
                        continue
                    req.error = f"{type(exc).__name__}: {exc}"
                    self.failed_requests += 1
                    await self._finish(req, reason="error")
            if not progressed:
                self._wakeup.clear()
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=0.05)
                except asyncio.TimeoutError:
                    pass

    def _admit(self) -> None:
        # Deliberately plain: admit up to max_concurrent, nothing else.
        #
        # I tried adding a "one prefill at a time" guard here for backends that
        # cannot chunk prefill, on the theory that concurrent prefills convoy.
        # Measured with 4x400-token prompts: 2.49 s with the guard, 2.48 s
        # without. It made no difference, because the round-robin loop already
        # lets only one session progress per iteration and each prefill is a
        # single blocking call -- so the queue is serial regardless. Kept absent
        # rather than kept as unearned complexity; the real fix for prefill
        # latency is chunking, which SAIL cannot do.
        #
        # Plus NPU memory: on long-context models a parked session's KV is the
        # scarce resource, so the head of the queue waits (FIFO, no skipping)
        # until the running sessions leave room for it.
        blocked = False
        while self._queue and len(self._active) < self.max_concurrent:
            req = self._queue[0]
            if req.cancelled:
                self._queue.popleft()
                self._pending.pop(req.req_id, None)
                self.cancelled_requests += 1
                continue
            if not self._fits(req):
                if not self._memory_blocked:
                    self.memory_waits += 1
                blocked = True
                break
            self._queue.popleft()
            self._active.append(req)
        self._memory_blocked = blocked

    async def _advance(self, req: Request) -> None:
        if req.session is None:
            factory = getattr(self.backend, "new_session_for", None)
            # A backend that carries per-prompt state outside the token list
            # (the OCR-VL engine's image tensor and vit head offset) builds its
            # session from the prompt it was given. Asking the backend beats
            # putting the image inside the token list: the prefix cache hashes
            # that list, and two images of the same size must never be able to
            # collide on it.
            req.session = (await factory(req.prompt_tokens) if factory is not None
                           else await self.backend.new_session())
            req.state = "prefill"
            # Try the prefix cache before paying for prefill. Backends that
            # snapshot during prefill (snapshot_points) need at least one token
            # left to prefill, since the first output comes from that step.
            planner = getattr(self.backend, "snapshot_points", None)
            cacheable = bool(getattr(self.backend, "kv_snapshots_verified", True))
            if planner is not None and cacheable:
                req.snap_points = list(planner(req.prompt_tokens))
                hit = self.prefix_cache.lookup(req.prompt_tokens[:-1])
            else:
                hit = self.prefix_cache.lookup(req.prompt_tokens)
            if hit is not None:
                prefix_len, snap = hit
                await req.session.restore(snap)
                req.cached_tokens = prefix_len
                req.state = "prefill"
            req.prefill_pos = req.cached_tokens

        if req.state == "prefill":
            pos = req.prefill_pos
            total = req.prompt_len
            if pos < total:
                # A backend that cannot extend an existing prompt must get the
                # remainder in one call; chunking it would corrupt the mask.
                limit = (getattr(self.backend, "prefill_chunk", PREFILL_CHUNK)
                         if self.backend.supports_chunked_prefill else total)
                end = min(total, pos + limit)
                nxt = [p for p in req.snap_points if pos < p < end]
                if nxt:
                    end = nxt[0]
                if pos == 0 and end >= total:
                    chunk = req.prompt_tokens  # whole prompt, extras intact
                elif hasattr(req.prompt_tokens, "segment"):
                    chunk = req.prompt_tokens.segment(pos, end)  # keeps positions/images
                else:
                    chunk = req.prompt_tokens[pos:end]
                if (end >= total and self.exact_tail
                        and hasattr(req.session, "set_exact_tail")):
                    req.session.set_exact_tail(
                        self.exact_tail if total >= EXACT_TAIL_MIN_PROMPT
                        else min(self.exact_tail, SHORT_EXACT_TAIL))
                await req.session.feed_prompt(chunk)
                req.prefill_pos = pos + len(chunk)
                self.prefix_cache.record_prompt_tokens(len(chunk))
                if req.prefill_pos in req.snap_points and req.prefill_pos < total:
                    prefix = req.prompt_tokens[: req.prefill_pos]
                    # Same gate as the post-generation snapshot, and it has to be
                    # here too: this site fires *while* the prompt is being
                    # prefilled, so the session's own reservation is live and the
                    # cache is competing with the request that is filling it.
                    if not self.prefix_cache.has(prefix) \
                            and self._cache_room_for(req.prefill_pos):
                        try:
                            snap = await req.session.snapshot(req.prefill_pos)
                            self.prefix_cache.put(prefix, snap)
                        except Exception:
                            pass  # the cache is an optimisation; never fail the request
                if req.prefill_pos >= total:
                    self.total_prompt_tokens += total
                    req.state = "decode"
                return

        # Decode: up to `decode_quantum` tokens before handing the TPU back to
        # the other sessions. Every token goes through the same step -> decode
        # -> on_token -> count -> stop/length/loop/context path it always did;
        # nothing is batched, so a token's value never depends on the slice
        # length. `decode_quantum == 1` is exactly the old per-token rotation.
        for _ in range(self._decode_quantum):
            if not await self._decode_one(req):
                return
            # Hand the event loop back after every single token. This is what
            # lets a disconnect (which calls cancel() from the sink or from the
            # connection's finally block) land mid-slice, and keeps the other
            # sessions' sinks and prefills running. Without it a slice would be
            # an uninterruptible synchronous loop of N NPU steps.
            await asyncio.sleep(0)

    async def _decode_one(self, req: Request) -> bool:
        """Advance ``req`` by one token. False once the request has finished.

        One real ``step()`` per call on purpose: ``_decode_times`` must hold one
        sample per token, so the reported decode rate stays a per-token number
        and a slice is not mistaken for a single fast step.
        """
        # A cancel can arrive between two tokens of a slice; stop before paying
        # for another NPU step and let _run finish the request. This is the
        # whole cancellation granularity: a cancel never waits for the rest of
        # the slice, only for the one step that was already in flight.
        if req.cancelled:
            return False
        t0 = time.monotonic()
        token = await req.session.step()
        dt = time.monotonic() - t0
        # One sample per real step: this deque is the per-token decode-rate
        # reading behind avg_decode_tps, and a slice must not look like one
        # slow-then-fast sample.
        self._decode_times.append(dt)
        if req.first_token_at is None:
            # Time to first token is the first token only, however many tokens
            # this request decodes per visit.
            req.first_token_at = time.monotonic()

        text = req.utf8.decode(req.session.decode_bytes([token]))
        if text and req.on_token is not None:
            await req.on_token(text)
        req.text_parts.append(text)
        self.total_completion_tokens += 1

        if req.session.is_stop_token(token):
            await self._finish(req, reason="stop")
            return False
        req.generated.append(token)
        if len(req.generated) >= req.params.max_tokens:
            await self._finish(req, reason="length")
            return False
        # A greedy bmodel loops once it runs out of momentum: with argmax fused
        # into lm_head there is no distribution to sample from, so the same span
        # repeats verbatim. Cutting the generation at that point is better than
        # streaming it to the user; the finish_reason says why.
        #
        # Opt-out for models whose output repeats on purpose: PaddleOCR-VL
        # writes every table cell as `<fcel>value`, twenty rows of it, and the
        # heuristic would end the answer in the middle of the table.
        if getattr(self.backend, "detects_loops", True) and _is_looping(req.generated):
            await self._finish(req, reason="stop")
            return False
        # Context exhausted: stop cleanly rather than let the backend overrun.
        if req.session.token_len >= self.backend.context_length - 1:
            await self._finish(req, reason="length")
            return False
        return True

    async def _finish(self, req: Request, reason: str) -> None:
        # Flush whatever the incremental decoder is still holding. A generation
        # cut mid-character (max_tokens landing inside a 3-byte CJK character)
        # leaves 1-2 bytes pending; final=True is what turns them into the one
        # U+FFFD that honestly represents them, rather than dropping them and
        # handing the client a silently shorter string. A normal stop has
        # nothing pending, so this is a no-op there.
        tail = req.utf8.decode(b"", final=True)
        if tail:
            req.text_parts.append(tail)
            # Only the reasons that mean "the client is still there and expects
            # its last characters" get the tail. On cancel or error the sink is
            # whatever failed, and a dead socket must not make the cache work
            # below fail too.
            if reason in ("stop", "length") and req.on_token is not None:
                try:
                    await req.on_token(tail)
                except Exception:
                    pass
        req.finish_reason = reason
        req.finished_at = time.monotonic()
        if reason == "cancelled":
            self.cancelled_requests += 1
        if req.session is not None:
            # Cache the KV of the *prompt* so the next request with the same
            # prefix skips it. Only worth it if the prompt was long enough.
            # Only store KV when the backend can prove restore reproduces the
            # straight run. An unverified snapshot would make a later request
            # resume from state that never produced this answer.
            cacheable = getattr(self.backend, "kv_snapshots_verified", True)
            # Backends that snapshot during prefill have already done so; at
            # this point their state covers the generated tokens too.
            if hasattr(self.backend, "snapshot_points"):
                cacheable = False
            if cacheable and reason != "error" and req.prompt_len >= 8 \
                    and req.cached_tokens < req.prompt_len \
                    and self._cache_room_for(req.prompt_len):
                try:
                    # Snapshot exactly the prompt length: the cache key is the
                    # prompt prefix, so storing more KV than that would make the
                    # hit restore a longer context than the request asked for.
                    snap = await req.session.snapshot(req.prompt_len)
                    self.prefix_cache.put(req.prompt_tokens[: req.prompt_len], snap)
                except Exception:
                    pass
            await req.session.close()
            req.session = None
        if req in self._active:
            self._active.remove(req)
        self._pending.pop(req.req_id, None)
        req.state = "done" if reason != "error" else "error"
        if req.done_event is not None:
            req.done_event.set()

    # -- helpers used by the worker --------------------------------------
    def enqueue(
        self, req_id: str, prompt_tokens: Sequence[Token], params: GenerateParams,
        on_token: TokenSink,
    ) -> Request:
        """Submit a request and return immediately.

        The worker uses this (rather than :meth:`generate`) because it needs the
        ``Request`` object in hand *before* streaming starts: ``cached_tokens``
        is only final once the scheduler has resolved the prefix hit, and the
        first ``meta`` event must report the real number.
        """
        done = asyncio.Event()
        req = self.submit(req_id, prompt_tokens, params)
        req.on_token = on_token
        req.done_event = done
        self._wakeup.set()
        return req

    async def wait(self, req: Request) -> Request:
        """Block until ``req`` finishes. Requires :meth:`enqueue` to have run."""
        if req.done_event is None:
            raise RuntimeError("request was not created via enqueue()")
        await req.done_event.wait()
        return req

    async def generate(
        self, req_id: str, prompt_tokens: Sequence[Token], params: GenerateParams, on_token: TokenSink
    ) -> Request:
        """Submit and wait. Convenience wrapper for single-request callers."""
        return await self.wait(self.enqueue(req_id, prompt_tokens, params, on_token))
