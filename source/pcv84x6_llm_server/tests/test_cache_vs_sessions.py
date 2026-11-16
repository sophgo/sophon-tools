"""Live sessions must win the NPU budget over the prefix cache (MYS-2784).

``_fits`` is the admission arithmetic: it compares what the running sessions
could claim plus the cache's current bytes against ``kv_budget_bytes``, and evicts
cache entries until the sum fits. That is correct at *admission* and it was the
only place the sum was ever checked.

The prefix cache then grew behind it. ``PrefixCache.put`` enforces only its own
``max_bytes``, which is set to the whole budget -- so the sequence

    admit a session  (needs 378, cache 0, budget 1056 -> fits)
    finish a request (cache put, 376 MiB)
    admit a session  (_fits sees 378 + 376 = 754 < 1056, and evicts nothing)

looked fine, right up until two long sessions finished inside the same scheduler
pass and put two snapshots. Measured on `.151` (MYS-2784): reservations 757 MiB
plus cache 753 MiB against a 1056 MiB budget -- 1510 MiB claimed from a budget
that was itself free-minus-1024 -- and the heap went to **2 MiB free**.

So the invariant these tests pin is the one that was missing:

    prefix_cache.nbytes + sum(reservation(a) for a in active) <= kv_budget_bytes

after every admission *and* after every cache insertion. The cache is the
elastic side of that sum; sessions are not.
"""

from __future__ import annotations

import asyncio

import pytest

from app.engine.base import GenerateParams, Session
from app.engine.prefix_cache import PrefixCache
from app.engine.scheduler import Scheduler

MIB = 1 << 20


class _Sess(Session):
    """A session whose KV costs a fixed number of bytes per prompt token."""

    def __init__(self, backend, per_tok: int) -> None:
        self._b = backend
        self._n = 0
        self._per_tok = per_tok

    @property
    def token_len(self) -> int:
        return self._n

    async def feed_prompt(self, tokens) -> None:
        self._n += len(tokens)

    async def step(self) -> int:
        self._n += 1
        await asyncio.sleep(0)
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
        return _Snap(token_len, self._per_tok * token_len)

    async def restore(self, snap) -> None:
        self._n = snap.token_len


class _Snap:
    def __init__(self, token_len: int, nbytes: int) -> None:
        self.token_len = token_len
        self.nbytes = nbytes


class _Backend:
    """A chat backend with explicit, large per-token KV so MiBs are readable."""

    def __init__(self, per_tok: int = 20480, linear: int = 33423360) -> None:
        self.kv_bytes_per_token = per_tok
        self.linear_state_bytes = linear
        self.session_state_bytes = linear
        self.context_length = 131072
        self.kind = "chat"
        self.kv_snapshots_verified = True
        # The scheduler asks before chunking; a non-chunking backend would need
        # the whole 17k prompt in one call, which is not the case under test.
        self.supports_chunked_prefill = True
        self.prefill_chunk = 2048

    async def encode(self, text: str) -> list[int]:
        # One token per character: the tests below count tokens to size KV.
        return list(range(len(text)))

    async def new_session(self) -> Session:
        return _Sess(self, self.kv_bytes_per_token)

    async def close(self) -> None:
        return None


def _params(max_tokens: int = 8) -> GenerateParams:
    return GenerateParams(max_tokens=max_tokens)


async def _drain(sched: Scheduler, text: str) -> object:
    tokens = await sched.backend.encode(text)
    return await sched.generate(
        f"r{id(text)}{len(sched._active)}", tokens, _params(), lambda t: asyncio.sleep(0))


def _claimed(sched: Scheduler) -> int:
    return sched.used_bytes()


@pytest.mark.asyncio
async def test_the_cache_yields_before_a_second_session_is_admitted():
    """The second session's admission must not be paid for out of the floor.

    Two 17.7k-token prompts parked at their full ``prompt + max_tokens`` claim
    ~378 MiB each at this backend's KV size. The cache has 376 MiB from the
    first request. Budget is 1056 MiB in the measured case; here it is set just
    above the two reservations so the cache is the only thing that can give.
    """
    be = _Backend()
    sched = Scheduler(be, prefix_cache=PrefixCache(max_entries=32),
                      max_concurrent=2)
    sched.kv_budget_bytes = 800 * MIB
    await sched.start()
    try:
        first = await _drain(sched, "a" * 17000)  # leaves a 348 MiB snapshot
        assert first.state == "done"
        cached = sched.prefix_cache.nbytes
        assert cached > 300 * MIB, "the fixture must actually fill the cache"

        # Second session: its reservation plus the cache exceeds the budget, so
        # the cache has to be trimmed before it may run.
        second = await _drain(sched, "b" * 17000)
        assert second.state == "done"
        # The invariant: what the budget advertises is what can be claimed.
        assert sched.used_bytes() <= sched.kv_budget_bytes
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_the_mid_prefill_snapshot_honours_the_budget_too():
    """There are two places the scheduler fills the cache, not one.

    ``_advance`` snapshots at each ``snapshot_points`` boundary *during* prefill
    -- that is the path the 35B takes, because its backend has ``snapshot_points``
    and ``_finish`` therefore skips the post-generation snapshot entirely. So a
    gate only on ``_finish`` leaves the path that actually runs in the field wide
    open, which is what the first version of this fix did: on `.151` the heap
    still fell to 1190 MiB with ``cache + reservations`` over budget.

    The measurement that matters is the same invariant, sampled at every ``put``:
    cache + live reservations must fit the budget.
    """
    be = _Backend()
    # The boundary has to land on a chunk edge: ``_advance`` cuts the prefill at
    # the next snap point, so a point off the 2048-token grid is skipped over.
    be.snapshot_points = lambda tokens: [2048] if len(tokens) > 2048 else []
    sched = Scheduler(be, prefix_cache=PrefixCache(max_entries=32), max_concurrent=3)
    # Sized so the parked sessions alone fit but the mid-prefill snapshot does
    # not: three sessions claim ~364 MiB each (1092), and the 40 MiB snapshot
    # would make 1132 against 1120. The measured board case is the same shape at
    # scale -- 757 MiB of reservations, a 376 MiB snapshot, a 1056 MiB budget.
    sched.kv_budget_bytes = 1120 * MIB

    # ``_cache_room_for`` is the gate itself: count the calls, and assert both
    # that it was consulted on the mid-prefill path and that it said no.
    asked: list[int] = []
    room = sched._cache_room_for

    def spy_room(n):
        asked.append(n)
        return room(n)

    sched._cache_room_for = spy_room
    observed: list[tuple[int, int, int]] = []
    put = sched.prefix_cache.put

    def spy(tokens, snapshot):
        put(tokens, snapshot)
        reserved = sum(sched.reservation(a) for a in sched._active)
        observed.append((sched.prefix_cache.nbytes, reserved, sched.kv_budget_bytes))

    sched.prefix_cache.put = spy
    await sched.start()
    try:
        await asyncio.gather(
            _drain(sched, "f" * 17000),
            _drain(sched, "g" * 17000),
            _drain(sched, "h" * 17000),
        )
    finally:
        await sched.stop()
    assert 2048 in asked, (
        "the mid-prefill snapshot never consulted the budget gate; this test "
        "would pass whether or not the gate exists")
    over = [(c, r, b) for c, r, b in observed if c + r > b]
    assert not over, (
        f"mid-prefill cache insert exceeded the budget "
        f"({over[0][0] >> 20} + {over[0][1] >> 20} > {over[0][2] >> 20} MiB)")
    # And the insert was refused, not merely followed by an eviction that would
    # have been too late (the snapshot has already allocated device memory by
    # the time ``put`` runs).
    assert not observed, (
        "the mid-prefill snapshot was inserted even though it did not fit beside "
        "the live sessions")


@pytest.mark.asyncio
async def test_a_cache_insert_while_sessions_run_does_not_overshoot_the_budget():
    """The 1510-vs-1056 MiB overshoot, in miniature.

    The order inside ``_finish`` is load-bearing: a finishing request snapshots
    and ``put``s *before* it leaves ``_active``. So at the moment of the insert
    its own reservation still counts, and so does every session parked behind
    it. ``PrefixCache.put`` knows only its own ``max_bytes`` -- which is the whole
    budget -- so it happily adds a snapshot on top of reservations that already
    spent it.

    Reproduced on `.151` (MYS-2784): two 17.7k sessions parked (757 MiB of
    reservations), two 376 MiB snapshots put, budget 1056 MiB -> 1510 MiB claimed
    and the heap at 2 MiB free. The assertion below is that sum, sampled inside
    every ``put``.
    """
    be = _Backend()
    sched = Scheduler(be, prefix_cache=PrefixCache(max_entries=32), max_concurrent=3)
    sched.kv_budget_bytes = 1200 * MIB
    observed: list[tuple[int, int, int]] = []
    put = sched.prefix_cache.put

    def spy(tokens, snapshot):
        put(tokens, snapshot)
        # What the budget is being asked to cover at this instant.
        reserved = sum(sched.reservation(a) for a in sched._active)
        observed.append((sched.prefix_cache.nbytes, reserved, sched.kv_budget_bytes))

    sched.prefix_cache.put = spy
    await sched.start()
    try:
        # Three long prompts. Each completion snapshot is ~348 MiB, and with
        # three parked sessions the reservations alone are most of the budget.
        await asyncio.gather(
            _drain(sched, "c" * 17000),
            _drain(sched, "d" * 17000),
            _drain(sched, "e" * 17000),
        )
    finally:
        await sched.stop()
    assert observed, "no cache insert happened; the fixture proves nothing"
    over = [(cache, resv, budget) for cache, resv, budget in observed
            if cache + resv > budget]
    assert not over, (
        "prefix cache + live reservations exceeded the NPU budget "
        f"({over[0][0] >> 20} + {over[0][1] >> 20} > {over[0][2] >> 20} MiB); "
        "the cache has to give way to sessions on insertion, not only on admission")
