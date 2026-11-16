"""The prefix cache is bounded by its own model's memory limit, not by a global
setting (MYS-2785).

Before this change there were *two* ceilings on the cache and they disagreed:

* the service-wide ``prefix_cache_max_mb`` (2048 MiB by default), passed to every
  worker as ``--device-kv-budget-mb`` and used as the cache's own byte limit;
* the model's runtime budget (``limit - static``), which the scheduler enforced
  on the sum of sessions + cache.

So a model whose limit left 300 MiB of runtime budget still had a cache willing
to take 2 GiB, and "how much may this model occupy" could not be answered from
the model's settings. The task's rule is the one an operator can compute:

    一个模型最多占用的设备内存 = 它的内存上限
    整板最多占用             = 已加载模型的内存上限之和

which only holds if the cache's only byte ceiling is ``limit - static``.

What these tests pin:

1. the setting is gone from the state file and the API surface, but a stale
   value (and a stale client posting it) is accepted and ignored;
2. the worker's cache ceiling is ``limit - static`` and follows the limit in both
   directions -- raising it gives the cache its room back without a reload;
3. sessions + cache never exceed that ceiling, so the model's live footprint
   stays under its limit while the cache is filled to the top.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.state import LEGACY_SETTING_FIELDS, Settings, StateStore
from app.engine.prefix_cache import PrefixCache
from app.engine.scheduler import Scheduler
from app.engine.worker import apply_mem_limit, configure

MIB = 1 << 20


# ---------------------------------------------------------------------------
# 1. the setting itself
# ---------------------------------------------------------------------------
def test_the_setting_no_longer_exists():
    """Not "defaults to something harmless" -- absent, so nothing can read it."""
    assert "prefix_cache_max_mb" not in Settings.__annotations__
    assert "prefix_cache_max_mb" in LEGACY_SETTING_FIELDS
    # The two settings that were *not* part of this decision are untouched.
    assert "prefix_cache_entries" in Settings.__annotations__
    assert "prefix_cache_ttl_min" in Settings.__annotations__


def test_an_old_state_file_ignores_its_2048_and_drops_it_on_save(tmp_path):
    """A board upgrading from v0.6.32 keeps its cache **on**, with no ceiling.

    Two things are asserted, and the second is the one that is easy to get
    wrong: the stale value must not merely be unread, it must not be *written
    back*. Otherwise every later ``GET /api/settings`` (and every support bundle
    built from state.json) keeps advertising a setting that does nothing.
    """
    p = tmp_path / "state.json"
    p.write_text(json.dumps({
        "settings": {"prefix_cache_entries": 16, "prefix_cache_ttl_min": 45,
                     "prefix_cache_max_mb": 2048},
        "usage": {},
    }))
    store = StateStore(p)
    assert store.settings.prefix_cache_entries == 16     # kept
    assert store.settings.prefix_cache_ttl_min == 45     # kept
    assert not hasattr(store.settings, "prefix_cache_max_mb")
    store.save()
    written = json.loads(p.read_text())["settings"]
    assert "prefix_cache_max_mb" not in written


def test_the_settings_api_still_reports_the_two_surviving_cache_fields(tmp_path):
    """The view is generated from ``_SETTING_FIELDS``; a deletion there is silent.

    Pinned as a pair rather than one field so removing the wrong tuple entry
    fails here instead of shrinking the console's settings page unnoticed.
    """
    from app.api.admin_api import _settings_view

    view = _settings_view(Settings())
    assert "prefix_cache_max_mb" not in view
    assert view["prefix_cache_entries"] == 32
    assert view["prefix_cache_ttl_min"] == 120


# ---------------------------------------------------------------------------
# 2. the worker's ceiling
# ---------------------------------------------------------------------------
class _Backend:
    """A chat backend with the board's real per-session numbers.

    Taken from the 35B on `.155`: 20 KiB of KV per token, 31.9 MiB of linear
    state. The absolute values matter less than their ratio to the limits below,
    which are chosen so a few sessions and a few snapshots visibly compete.
    """

    kind = "chat"
    kv_bytes_per_token = 20480
    linear_state_bytes = 33423360
    session_state_bytes = 33423360
    context_length = 131072

    def close(self) -> None:
        return None


def _fresh_sched(max_concurrent: int = 2) -> Scheduler:
    """A scheduler in the state ``amain`` leaves it in before ``configure``."""
    sched = Scheduler(_Backend(), prefix_cache=PrefixCache(max_entries=32),
                      max_concurrent=max_concurrent)
    # What bm-smi reported after the load: room to spare, so the *model's* limit
    # is what binds. A test that left this None would pass even if the limit were
    # ignored, because there would be no other number to compare against.
    sched.device_budget_bytes = 8000 * MIB
    sched.kv_budget_bytes = sched.device_budget_bytes
    return sched


def test_the_cache_ceiling_is_the_model_budget_not_a_global_number():
    sched = _fresh_sched()
    static = 20000 * MIB
    limit = static + 700 * MIB
    apply_mem_limit(sched, _Backend(), limit, static)
    applied = configure(sched, _Backend(), {"cache_entries": 32, "cache_ttl_min": 60})

    assert applied["mem_runtime_budget_bytes"] == 700 * MIB
    assert applied["cache_max_bytes"] == 700 * MIB, (
        "the cache ceiling must be limit - static; anything larger lets the "
        "model hold more than its own limit")
    # And the same number the scheduler admits sessions against, so the two
    # ceilings cannot drift apart.
    assert applied["kv_budget_bytes"] == 700 * MIB


def test_raising_the_limit_raises_the_cache_ceiling_without_a_reload():
    """``PUT /api/models/{id}/settings`` on a loaded model must be able to grow.

    This is the reason ``apply_mem_limit`` recomputes from the device reading
    instead of ``min``-ing into the current value: with the old accumulate-in-
    place form the second call could only ever shrink, so an operator who raised
    a limit would see the cache stay at the smaller figure until they unloaded
    the model -- which the docs say is not required.
    """
    backend = _Backend()
    sched = _fresh_sched()
    static = 20000 * MIB

    apply_mem_limit(sched, backend, static + 400 * MIB, static)
    small = configure(sched, backend, {})["cache_max_bytes"]
    apply_mem_limit(sched, backend, static + 900 * MIB, static)
    large = configure(sched, backend, {})["cache_max_bytes"]

    assert small == 400 * MIB
    assert large == 900 * MIB, "raising the limit did not give the cache its room back"


def test_lowering_the_limit_shrinks_the_cache_at_once():
    """A lower limit must trim the cache now, not at the next request.

    ``stats`` reports ``cache.max_bytes`` as "the ceiling"; leaving it at the old
    value after a save would show an operator a number the scheduler no longer
    honours.
    """
    backend = _Backend()
    sched = _fresh_sched()
    static = 20000 * MIB
    apply_mem_limit(sched, backend, static + 900 * MIB, static)
    configure(sched, backend, {})
    assert sched.prefix_cache.max_bytes == 900 * MIB

    apply_mem_limit(sched, backend, static + 200 * MIB, static)
    assert sched.prefix_cache.max_bytes == 200 * MIB, (
        "the cache ceiling did not follow the lowered limit")


def test_live_budget_reduction_is_refused_without_mutation():
    from app.engine.base import GenerateParams
    from app.engine.scheduler import Request

    sched = _fresh_sched()
    backend = sched.backend
    static = 20000 * MIB
    configure(sched, backend, {"mem_limit_mb": 20900, "mem_static_mb": 20000})
    sched._active.append(Request("live", [1] * 4097, GenerateParams(max_tokens=100)))
    previous = (sched.kv_budget_bytes, sched.prefix_cache.max_bytes, sched.max_concurrent)
    reply = configure(sched, backend, {"mem_limit_mb": 20200,
                                     "mem_static_mb": 20000, "max_concurrent": 3})
    assert "error" in reply
    assert (sched.kv_budget_bytes, sched.prefix_cache.max_bytes, sched.max_concurrent) == previous
    # Raising is safe while work is running; reducing is safe once it drains.
    assert "error" not in configure(sched, backend, {"mem_limit_mb": 21000,
                                                   "mem_static_mb": 20000})
    sched._active.clear()
    assert "error" not in configure(sched, backend, {"mem_limit_mb": 20200,
                                                   "mem_static_mb": 20000})
    assert sched.kv_budget_bytes == 200 * MIB


def test_the_device_reading_still_caps_a_limit_larger_than_the_card():
    """A limit above what the NPU can spare must not make the cache over-allocate.

    MYS-2675's rule survives this change: the limit is one ceiling, the device is
    the other, and the smaller wins. Without it a typo in ``mem_limit_mb`` (or a
    card with other models on it) would let the cache walk into memory that is
    not there.
    """
    backend = _Backend()
    sched = _fresh_sched()
    sched.device_budget_bytes = 500 * MIB   # a nearly full card
    sched.kv_budget_bytes = 500 * MIB
    static = 20000 * MIB
    apply_mem_limit(sched, backend, static + 4000 * MIB, static)
    applied = configure(sched, backend, {})

    assert applied["mem_runtime_budget_bytes"] == 4000 * MIB
    assert applied["kv_budget_bytes"] == 500 * MIB
    assert applied["cache_max_bytes"] == 500 * MIB


def test_a_worker_without_a_limit_falls_back_to_the_device_reading():
    """No limit is a real configuration (a hand-started worker, mock backend).

    Then the device figure is the only ceiling there is -- and it must still be
    one, or a worker with no limit would cache without bound.
    """
    backend = _Backend()
    sched = _fresh_sched()
    applied = apply_mem_limit(sched, backend, None, None)
    assert applied["mem_runtime_budget_bytes"] is None
    assert configure(sched, backend, {})["cache_max_bytes"] == 8000 * MIB


def test_a_zero_limit_switches_the_cache_off():
    """0 is how an operator turns the cache off for one model."""
    backend = _Backend()
    sched = _fresh_sched()
    static = 20000 * MIB
    apply_mem_limit(sched, backend, static, static)   # limit == static
    assert configure(sched, backend, {})["cache_max_bytes"] == 0


def test_the_cli_cache_switch_beats_the_inferred_budget():
    """The first acceptance round's regression, exactly as reported.

    ``tools/decode_quantum_ab.py`` / ``decode_quantum_smoke.py`` start a worker by
    hand with ``--device-kv-budget-mb 0`` so a second run of the same prompt
    cannot restore a snapshot and skew the measured prefill cost. The first
    attempt at this change put that value *below* the device reading in the
    precedence order, so a harness asking for no cache got the device's figure
    instead (the reviewer's repro: "device budget 8000 MiB, CLI 0, cache still
    8000 MiB"). An explicit instruction has to beat an inferred number.

    Both readings are covered, because that is where the bug lived: with a device
    reading, without one, and with a model limit in force.
    """
    backend = _Backend()
    static = 20000 * MIB

    # (a) device reading present, no model limit: OFF wins over 8000 MiB.
    sched = _fresh_sched()
    sched.kv_budget_bytes = sched.device_budget_bytes = 8000 * MIB
    sched.cache_cli_cap_bytes = 0
    apply_mem_limit(sched, backend, None, None)
    applied = configure(sched, backend, {})
    assert sched.device_budget_bytes == 8000 * MIB
    assert applied["cache_max_bytes"] == 0, (
        "a CLI cache-off was overridden by the device budget -- the reported bug")

    # (b) no device reading either (a host, a board without bm-smi).
    sched = _fresh_sched()
    sched.kv_budget_bytes = sched.device_budget_bytes = None
    sched.cache_cli_cap_bytes = 0
    apply_mem_limit(sched, backend, None, None)
    assert configure(sched, backend, {})["cache_max_bytes"] == 0

    # (c) a model limit in force: still off, not the model's budget.
    sched = _fresh_sched()
    sched.cache_cli_cap_bytes = 0
    apply_mem_limit(sched, backend, static + 600 * MIB, static)
    assert configure(sched, backend, {})["cache_max_bytes"] == 0


def test_a_non_zero_cli_budget_lowers_the_ceiling_and_never_raises_it():
    """The deprecated flag's other half: a cap, not a way around the model.

    ``--device-kv-budget-mb 512`` on a model whose budget is 600 MiB must give
    512; on a model whose budget is 200 MiB it must still give 200, because the
    task's rule is that nothing outside the model's own limit can raise what the
    model may occupy.
    """
    backend = _Backend()
    static = 20000 * MIB

    sched = _fresh_sched()
    sched.cache_cli_cap_bytes = 512 * MIB
    apply_mem_limit(sched, backend, static + 600 * MIB, static)
    assert configure(sched, backend, {})["cache_max_bytes"] == 512 * MIB

    sched = _fresh_sched()
    sched.cache_cli_cap_bytes = 512 * MIB
    apply_mem_limit(sched, backend, static + 200 * MIB, static)
    assert configure(sched, backend, {})["cache_max_bytes"] == 200 * MIB, (
        "the deprecated flag raised the cache above the model's own budget")


# ---------------------------------------------------------------------------
# 3. the invariant, with the cache filled to its ceiling
# ---------------------------------------------------------------------------
class _Snap:
    def __init__(self, token_len: int, nbytes: int) -> None:
        self.token_len = token_len
        self.nbytes = nbytes


class _Sess:
    """A session whose KV is ``nbytes`` for ``token_len`` tokens."""

    def __init__(self, backend, nbytes: int) -> None:
        self._be = backend
        self._n = 0
        self._bytes = nbytes

    @property
    def token_len(self) -> int:
        return self._n

    async def feed_prompt(self, tokens) -> None:
        self._n += len(tokens)

    async def step(self) -> int:
        self._n += 1
        return 1

    def decode(self, tokens) -> str:
        return "x"

    def decode_bytes(self, tokens) -> bytes:
        return b"x"

    def is_stop_token(self, token) -> bool:
        return False

    async def close(self) -> None:
        return None

    async def snapshot(self, token_len: int):
        return _Snap(token_len, self._bytes)

    async def restore(self, snap) -> None:
        self._n = snap.token_len


class _SessionBackend(_Backend):
    """The chat backend above, with sessions that cost what the tests say."""

    per_session = 120 * MIB
    supports_chunked_prefill = True
    prefill_chunk = 2048
    kv_snapshots_verified = True

    async def encode(self, text: str) -> list[int]:
        # Distinct ids per prompt, or every prompt would hash to the same cache
        # key and the fixture would only ever hold one entry.
        seed = sum(map(ord, text[:8])) or 1
        return [(seed + i) % 4096 for i in range(len(text))]

    async def new_session(self):
        return _Sess(self, self.per_session)


@pytest.mark.asyncio
async def test_a_full_cache_never_pushes_the_model_past_its_limit():
    """The acceptance criterion, in miniature: fill the cache, stay under the cap.

    Four prompts are sent through a real scheduler whose budget is the model's
    ``limit - static``. At every cache insertion the sum of what the live
    sessions claim and what the cache holds is checked against that budget --
    which is the definition of "this model does not exceed its limit", since the
    limit is ``static + budget`` and the static half is already on the device.

    The fixture would be meaningless if the cache never filled, so the test also
    asserts the cache ended up holding something substantial.
    """
    from app.engine.base import GenerateParams

    backend = _SessionBackend()
    sched = Scheduler(backend, prefix_cache=PrefixCache(max_entries=32),
                      max_concurrent=2)
    static = 20000 * MIB
    sched.device_budget_bytes = 8000 * MIB
    sched.kv_budget_bytes = sched.device_budget_bytes
    limit = static + 700 * MIB
    apply_mem_limit(sched, backend, limit, static)
    configure(sched, backend, {"cache_entries": 32, "cache_ttl_min": 0})
    budget = sched.kv_budget_bytes
    assert budget == 700 * MIB

    seen: list[tuple[int, int]] = []
    put = sched.prefix_cache.put

    def spy(tokens, snapshot):
        put(tokens, snapshot)
        live = sum(sched.reservation(a) for a in sched._active)
        seen.append((sched.prefix_cache.nbytes, live))

    sched.prefix_cache.put = spy

    await sched.start()
    try:
        for i in range(4):
            tokens = await backend.encode(f"p{i}" * 4000)
            await sched.generate(f"r{i}", tokens, GenerateParams(max_tokens=8),
                                 lambda _t: asyncio_sleep())
    finally:
        await sched.stop()

    assert seen, "no cache insert happened; the fixture proves nothing"
    total = seen[-1][0]
    assert total >= 200 * MIB, (
        f"the cache only reached {total >> 20} MiB, so the ceiling was never "
        "tested -- raise the budget or the prompt length")
    over = [(cache, live) for cache, live in seen if cache + live > budget]
    assert not over, (
        f"the model is over its own limit: cache {over[0][0] >> 20} MiB + "
        f"sessions {over[0][1] >> 20} MiB > budget {budget >> 20} MiB")
    # The model's live footprint, as the console computes it, stays under the
    # operator's number.
    assert sched.used_bytes() <= budget


async def asyncio_sleep():
    import asyncio
    await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# 4. real overlap: concurrent sessions, and the engine's actual allocation
# ---------------------------------------------------------------------------
class _ParkBackend(_SessionBackend):
    """The 9B's own numbers, including the engine's park granularity.

    ``park_granule`` is what makes this class worth having: with it, the
    reservation must charge the granule-rounded buffer the engine really
    allocates, not the raw token count. The first acceptance round's board run
    went 37 MiB over the limit precisely because ``reservation()`` used the raw
    count (measured: two 3627-token sessions, 32 KiB/token).
    """

    kv_bytes_per_token = 32768        # 32 KiB/token (32 layers, all FA)
    linear_state_bytes = 26738688     # 25.5 MiB
    session_state_bytes = 4321705984
    context_length = 131072
    park_granule = 4096


class _GrowingSession(_Sess):
    """A session that records how many tokens it has fed, like the real one."""

    def __init__(self, backend, nbytes: int) -> None:
        super().__init__(backend, nbytes)
        self.fed = 0

    async def feed_prompt(self, tokens) -> None:
        self.fed += len(tokens)
        self._n += len(tokens)


class _OverlapBackend(_ParkBackend):
    """Sessions that hold the NPU for a while, so requests really overlap."""

    kv_snapshots_verified = True
    supports_chunked_prefill = True
    prefill_chunk = 2048

    async def new_session(self):
        return _GrowingSession(self, 0)


@pytest.mark.asyncio
async def test_two_sessions_really_overlap_and_stay_within_the_budget():
    """The concurrency test the first round was missing.

    The earlier version awaited each request in turn, so ``max_concurrent=2``
    never produced two live sessions and the test proved nothing about
    concurrency. This one submits both *before* either finishes and asserts the
    peak number of simultaneously active requests is 2 -- a fixture guard, so the
    invariant below is never checked against a serial run that trivially holds.
    """
    from app.engine.base import GenerateParams

    backend = _OverlapBackend()
    sched = Scheduler(backend, prefix_cache=PrefixCache(max_entries=32),
                      max_concurrent=2)
    static = 20000 * MIB
    sched.device_budget_bytes = 8000 * MIB
    sched.kv_budget_bytes = sched.device_budget_bytes
    apply_mem_limit(sched, backend, static + 700 * MIB, static)
    configure(sched, backend, {"cache_entries": 32, "cache_ttl_min": 0})
    budget = sched.kv_budget_bytes
    assert budget == 700 * MIB

    peak_active = 0
    worst: list[tuple[int, int]] = []
    put = sched.prefix_cache.put

    def spy(tokens, snapshot):
        put(tokens, snapshot)
        live = sum(sched.reservation(a) for a in sched._active)
        worst.append((sched.prefix_cache.nbytes, live))

    sched.prefix_cache.put = spy

    async def one(i: int):
        nonlocal peak_active
        tokens = await backend.encode(f"overlap{i}" * 400)
        return await sched.generate(f"r{i}", tokens, GenerateParams(max_tokens=8),
                                    lambda _t: asyncio_sleep())

    await sched.start()
    try:
        # Prime the cache with one short request so a later insert competes with
        # live sessions rather than starting from empty.
        await one(0)
        tasks = [asyncio.ensure_future(one(i)) for i in (1, 2)]
        while not all(t.done() for t in tasks):
            peak_active = max(peak_active, len(sched._active))
            await asyncio.sleep(0)
        await asyncio.gather(*tasks)
        peak_active = max(peak_active, len(sched._active))
    finally:
        await sched.stop()

    assert peak_active == 2, (
        f"only {peak_active} request(s) were ever live at once; this test would "
        "pass without ever exercising concurrency")
    for cache, live in worst:
        assert cache + live <= budget, (
            f"cache {cache >> 20} MiB + live sessions {live >> 20} MiB exceeded "
            f"the {budget >> 20} MiB budget")
    assert sched.used_bytes() <= budget


def test_the_reservation_charges_the_granule_the_engine_allocates():
    """``ensure_park`` allocates ``round_up(tokens, 4096)`` slots, not ``tokens``.

    This is a number-for-number check against the board finding: on the 9B
    (32 KiB/token) a 3627-token session is parked in 4096 slots, i.e. 128 MiB of
    FA KV rather than 113 MiB. Two such sessions under-reserve by ~30 MiB, which
    is the direction and order of the 37 MiB the first board run went over.
    """
    from app.engine.base import GenerateParams

    backend = _ParkBackend()
    sched = Scheduler(backend, prefix_cache=PrefixCache(max_entries=1),
                      max_concurrent=2)
    tokens = [1] * 3627
    req = sched.submit("r", tokens, GenerateParams(max_tokens=0))
    got = sched.reservation(req)
    sched.cancel("r")

    kv = backend.kv_bytes_per_token
    lin = backend.linear_state_bytes
    raw = lin + kv * 3627
    expected = lin + kv * 4096          # one granule, rounded up
    assert got == expected, f"reservation {got} != granule-rounded {expected}"
    assert got > raw, "the reservation did not cover the rounding"
    assert (got - raw) == pytest.approx(kv * (4096 - 3627))
    # Even a short session is charged a whole granule, because that is what the
    # engine allocates for it: ``ensure_park`` rounds the first park up too.
    req2 = sched.submit("r2", [1] * 2048, GenerateParams(max_tokens=0))
    assert sched.reservation(req2) == lin + kv * 4096
    sched.cancel("r2")


def test_a_backend_without_a_granule_is_charged_its_raw_length():
    """Mock / sail / an old engine library: unchanged behaviour, no inflation."""
    from app.engine.base import GenerateParams

    backend = _Backend()                # no park_granule attribute
    sched = Scheduler(backend, prefix_cache=PrefixCache(max_entries=1))
    req = sched.submit("r", [1] * 3000, GenerateParams(max_tokens=0))
    assert sched.reservation(req) == (backend.linear_state_bytes
                                      + backend.kv_bytes_per_token * 3000)
    sched.cancel("r")


@pytest.mark.parametrize("needs,expected_peak", [
    ([4096], 4096),
    ([4096, 4097], 12288),
    ([4096, 8193], 16384),
    ([8192, 8193], 20480),
    ([4096, 8193, 12289], 32768),
    ([126976, 126977, 131072], 258048),
])
def test_growing_a_park_buffer_does_not_exceed_the_session_reservation(needs, expected_peak):
    """Replay successive park calls, including allocation before freeing old KV.

    These are histories, not repeated fresh allocations at the final length.
    The explicit peaks come from ensure_park's old/new buffer lifetimes.
    """
    backend = _ParkBackend()
    sched = Scheduler(backend, prefix_cache=PrefixCache(max_entries=1))
    cap, peak = 0, 0
    for need in needs:
        if need > cap:
            new = max(need, cap + cap // 2)
            new = min(backend.context_length, ((new + 4095) // 4096) * 4096)
            peak = max(peak, cap + new)
            cap = new
        assert sched._parked_slots(need) >= peak
    assert peak == expected_peak


def test_park_reservation_bounds_every_growth_history_in_a_small_context():
    """Enumerate all distinct allocation histories, including skipped lengths.

    A small granule/context makes exhaustive coverage possible, including a
    context that ends partway through a granule. The oracle models allocations
    across calls; it does not use the scheduler's upper-bound formula.
    """
    for context in (17, 20):
        backend = _ParkBackend()
        backend.park_granule = 4
        backend.context_length = context
        sched = Scheduler(backend)
        histories = {(0, 0)}  # (allocated slots, highest old+new seen)
        for need in range(1, context + 1):
            next_histories = set()
            for cap, peak in histories:
                if need > cap:
                    new = max(need, cap + cap // 2)
                    new = min(context, ((new + 3) // 4) * 4)
                    cap, peak = new, max(peak, cap + new)
                assert sched._parked_slots(need) >= peak, (context, need, cap, peak)
                next_histories.add((cap, peak))
            histories |= next_histories


def test_the_reviewers_repro_script_passes():
    """The attached repro, kept as a test so it cannot regress again.

    It is the reviewer's own fixture (`review-136-cache-disable.py`): set the
    device budget to 8000 MiB, the CLI cache value to 0, and assert that
    ``configure`` reports 0 rather than 8000. Kept here verbatim in effect
    because the review's acceptance criterion is "this script passes".
    """
    sched = _fresh_sched()
    backend = _Backend()
    sched.cache_fallback_bytes = 0      # the old name; also exercised on purpose
    apply_mem_limit(sched, backend, None, None)
    applied = configure(sched, backend, {})
    assert sched.device_budget_bytes >> 20 == 8000
    assert applied["cache_max_bytes"] == 0, (
        "A/B harness requested cache OFF but cache remains enabled")


def test_a_snapshot_is_charged_its_linear_state_too():
    """``Session::snapshot`` allocates the whole linear state, not just FA KV.

    For every layer it allocates ``len * kv_bytes`` (full attention) or
    ``mem_size(state_a) + mem_size(state_b)`` (linear attention), so a snapshot
    carries the linear state regardless of how short its prefix is. Charging only
    ``per_tok * tokens`` under-estimated every entry by 25.5 MiB on the 9B, which
    is what let a filled cache plus two live sessions sit 21 MiB over the model's
    limit in the second acceptance round.
    """
    backend = _ParkBackend()
    sched = Scheduler(backend, prefix_cache=PrefixCache(max_entries=1))

    for tokens in (512, 2835, 17000):
        got = sched._snapshot_bytes(tokens)
        assert got == backend.linear_state_bytes + backend.kv_bytes_per_token * tokens, (
            f"{tokens} tokens: snapshot charged {got}, "
            "which omits the linear-attention state the engine allocates")
    # A backend with no per-token KV keeps the deliberately-large fallback, so
    # the correction cannot make an unknown backend under-reserve.
    class _NoKv(_Backend):
        kv_bytes_per_token = 0
    assert Scheduler(_NoKv())._snapshot_bytes(1000) == 1000 * 4096
