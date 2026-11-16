"""Long-context models: NPU memory, not slot count, limits concurrency.

A parked session costs linear state + KV per token of prompt + max_tokens; the
scheduler admits against the NPU budget, the prefix cache gives way to live
sessions, and an engine call that still runs out of memory frees cache entries
and retries.
"""
import asyncio

import pytest

from app.engine.base import GenerateParams
from app.engine.mock import MockBackend
from app.engine.native import NativeSession
from app.engine.prefix_cache import PrefixCache
from app.engine.scheduler import Scheduler

PER_TOKEN = 1000


def backend():
    be = MockBackend("m", context_length=4096, decode_delay_per_token=0.002)
    be.kv_bytes_per_token = PER_TOKEN
    be.linear_state_bytes = 0
    return be


class Snap:
    def __init__(self, nbytes):
        self.nbytes = nbytes
        self.released = False

    def release(self):
        self.released = True


async def _noop(_text):
    return None


async def run_many(sched, prompts, max_tokens):
    peak = 0

    async def one(i, text):
        nonlocal peak
        tokens = await sched.backend.encode(text)

        async def sink(_t):
            nonlocal peak
            peak = max(peak, len(sched._active))
        return await sched.generate(f"r{i}", tokens, GenerateParams(max_tokens=max_tokens), sink)

    reqs = await asyncio.gather(*(one(i, t) for i, t in enumerate(prompts)))
    return reqs, peak


@pytest.mark.asyncio
async def test_budget_caps_concurrency_below_the_slot_count():
    be = backend()
    sched = Scheduler(be, max_concurrent=3)
    prompts = [f"prompt number {i} with some words" for i in range(3)]
    tokens = await be.encode(prompts[0])
    one = PER_TOKEN * (len(tokens) + 8)
    sched.kv_budget_bytes = 2 * one + one // 2  # room for two, not three
    await sched.start()
    try:
        reqs, peak = await run_many(sched, prompts, max_tokens=8)
        assert all(r.state == "done" for r in reqs)
        assert peak == 2
        assert sched.memory_waits >= 1
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_without_budget_all_slots_are_used():
    be = backend()
    sched = Scheduler(be, max_concurrent=3)
    await sched.start()
    try:
        reqs, peak = await run_many(sched, [f"prompt {i} words" for i in range(3)], max_tokens=8)
        assert all(r.state == "done" for r in reqs)
        assert peak == 3
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_a_request_bigger_than_the_budget_still_runs_alone():
    be = backend()
    sched = Scheduler(be, max_concurrent=3)
    sched.kv_budget_bytes = 10  # far below any reservation
    await sched.start()
    try:
        reqs, peak = await run_many(sched, ["first long one", "second long one"], max_tokens=6)
        assert all(r.state == "done" for r in reqs)
        assert peak == 1
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_reservation_is_capped_at_the_context():
    be = backend()
    sched = Scheduler(be)
    tokens = await be.encode("hello there")
    req = sched.submit("r", tokens, GenerateParams(max_tokens=10 ** 9))
    assert sched.reservation(req) == PER_TOKEN * be.context_length
    sched.cancel("r")


@pytest.mark.asyncio
async def test_cache_gives_way_to_a_session_that_fits_the_budget():
    be = backend()
    cache = PrefixCache(max_entries=8, max_bytes=10 ** 9)
    sched = Scheduler(be, prefix_cache=cache, max_concurrent=3)
    prompts = ["alpha beta gamma 1", "alpha beta gamma 2"]
    tokens = await be.encode(prompts[0])
    one = PER_TOKEN * (len(tokens) + 8)
    sched.kv_budget_bytes = 2 * one + 100
    snaps = [Snap(one), Snap(one)]
    cache.put([1, 2, 3, 4], snaps[0])
    cache.put([5, 6, 7, 8], snaps[1])
    await sched.start()
    try:
        reqs, peak = await run_many(sched, prompts, max_tokens=8)
        assert all(r.state == "done" for r in reqs)
        assert peak == 2
        assert all(s.released for s in snaps)  # both evicted to make room
    finally:
        await sched.stop()


def test_evict_one_never_drops_the_snapshot_being_restored():
    cache = PrefixCache(max_entries=8, max_bytes=10 ** 9)
    keep, other = Snap(10), Snap(10)
    cache.put([1, 2, 3], keep)
    cache.put([4, 5, 6], other)
    assert cache.evict_one(exclude=keep) is True
    assert other.released and not keep.released
    assert cache.evict_one(exclude=keep) is False
    assert len(cache) == 1


@pytest.mark.asyncio
async def test_native_call_frees_cache_and_retries_on_npu_oom():
    calls = []

    class FakeBackend:
        _lib = None

        def __init__(self):
            self.freed = 0

        def oom_relief(self, keep):
            if self.freed >= 2:
                return False
            self.freed += 1
            return True

    be = FakeBackend()
    sess = NativeSession(be, 1)

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("NPU heap exhausted parking a session (8192 tokens)")
        return 7

    assert await sess._call(flaky) == 7
    assert be.freed == 2

    calls.clear()
    be.freed = 2  # nothing left to free: the error surfaces

    def always():
        raise RuntimeError("NPU heap exhausted parking a session (8192 tokens)")

    with pytest.raises(RuntimeError, match="heap exhausted"):
        await sess._call(always)

    def other():
        raise RuntimeError("NPU fault: sync timed out")

    with pytest.raises(RuntimeError, match="fault"):
        await sess._call(other)
