import asyncio

import pytest

from app.engine.base import GenerateParams
from app.engine.mock import MockBackend
from app.engine.prefix_cache import PrefixCache
from app.engine.scheduler import Scheduler


def params(**kw):
    base = dict(max_tokens=5, temperature=0.0, top_p=1.0, top_k=1)
    base.update(kw)
    return GenerateParams(**base)


async def run_one(sched, text, max_tokens=4):
    tokens = await sched.backend.encode(text)
    got = []
    req = await sched.generate(
        f"r-{text[:6]}-{id(got)}", tokens, params(max_tokens=max_tokens),
        lambda t: _collect(got, t),
    )
    return req, got


async def _collect(bucket, text):
    bucket.append(text)


@pytest.mark.asyncio
async def test_single_request_completes():
    sched = Scheduler(MockBackend("m", context_length=512))
    await sched.start()
    try:
        req, got = await run_one(sched, "hello world")
        assert req.state == "done"
        assert req.finish_reason in ("stop", "length")
        assert req.first_token_at is not None
        assert len(req.generated) >= 1
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_concurrent_requests_all_progress_interleaved():
    """The core promise: N requests stream at once rather than queueing."""
    be = MockBackend("m", context_length=512, decode_delay_per_token=0.002)
    sched = Scheduler(be, max_concurrent=8)
    await sched.start()
    try:
        order = []
        async def one(name, text):
            tokens = await be.encode(text)
            def sink(t):
                order.append(name)
                return asyncio.sleep(0)
            return await sched.generate(name, tokens, params(max_tokens=32), sink)

        await asyncio.gather(*(one(f"c{i}", f"prompt number {i}") for i in range(4)))
        # All four must appear, and they must interleave: if the scheduler ran
        # requests to completion one at a time, the first quarter of the order
        # would contain a single name. The unit of rotation is the decode
        # quantum, so the window has to cover at least one slice per request --
        # MAX_DECODE_QUANTUM * 4 tokens is the worst case for four sessions.
        assert set(order) == {f"c{i}" for i in range(4)}
        window = min(len(order) // 4, sched.decode_quantum * 4)
        assert window >= sched.decode_quantum, (
            f"only {len(order)} tokens for four sessions: {order}")
        assert len(set(order[:window])) > 1, f"no interleaving: {order}"
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_cancel_frees_the_slot():
    be = MockBackend("m", context_length=512, decode_delay_per_token=0.01)
    sched = Scheduler(be, max_concurrent=1)
    await sched.start()
    try:
        tokens = await be.encode("a long running prompt")
        req = sched.submit("victim", tokens, params(max_tokens=1000))
        await asyncio.sleep(0.05)
        assert sched.cancel("victim") is True
        for _ in range(50):
            if req.state in ("done", "error"):
                break
            await asyncio.sleep(0.01)
        assert req.state == "done"
        assert req.finish_reason == "cancelled"
        assert sched.stats()["active"] == 0

        # The slot is genuinely free: a new request runs.
        req2, _ = await run_one(sched, "after cancel", max_tokens=2)
        assert req2.state == "done"
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_no_starvation_long_request_does_not_block_short():
    be = MockBackend("m", context_length=512, decode_delay_per_token=0.001)
    sched = Scheduler(be, max_concurrent=4)
    await sched.start()
    try:
        long_tokens = await be.encode("x" * 200)
        long_req = sched.submit("long", long_tokens, params(max_tokens=500))

        short_start = asyncio.get_event_loop().time()
        short_tokens = await be.encode("short")
        short_req = await sched.generate("short", short_tokens, params(max_tokens=3), _noop)
        short_elapsed = asyncio.get_event_loop().time() - short_start

        assert short_req.state == "done"
        assert short_elapsed < 1.0, "short request should not wait for the long one"
        assert long_req.state != "done", "the long one should still be running"
        sched.cancel("long")
    finally:
        await sched.stop()


async def _noop(_t):
    return None


@pytest.mark.asyncio
async def test_prefix_cache_is_used_on_repeat_prompt():
    be = MockBackend("m", context_length=512)
    sched = Scheduler(be, PrefixCache())
    await sched.start()
    try:
        prompt = "the same system prompt repeated verbatim"
        tokens = await be.encode(prompt)
        await sched.generate("a", tokens, params(max_tokens=2), _noop)
        stats1 = sched.stats()["cache"]
        # Second identical prompt: the prompt prefix should be reused.
        await sched.generate("b", tokens, params(max_tokens=2), _noop)
        stats2 = sched.stats()["cache"]
        assert stats2["tokens_reused"] > stats1["tokens_reused"], stats2
        assert stats2["hit_rate"] > 0
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_context_length_is_enforced():
    be = MockBackend("m", context_length=32)
    sched = Scheduler(be)
    await sched.start()
    try:
        tokens = await be.encode("padding " * 10)
        req = await sched.generate("ctx", tokens, params(max_tokens=10_000), _noop)
        assert req.finish_reason == "length", req.finish_reason
        assert req.session is None
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_unchunked_backend_gets_whole_prompt_in_one_call():
    """A backend that cannot extend a prompt must receive it in one feed_prompt.

    The SAIL prefill graph sizes its causal mask from the whole prompt, so
    chunking it would build the wrong mask.
    """
    from app.engine.base import EngineBackend, Session
    from app.engine.mock import MockBackend

    class NoChunkBackend(MockBackend):
        @property
        def supports_chunked_prefill(self) -> bool:
            return False

    be = NoChunkBackend("m", context_length=4096)
    calls = []
    orig = be.new_session

    async def new_session():
        sess = await orig()
        orig_feed = sess.feed_prompt

        async def feed(tokens):
            calls.append(len(tokens))
            await orig_feed(tokens)

        sess.feed_prompt = feed
        return sess

    be.new_session = new_session

    sched = Scheduler(be)
    await sched.start()
    try:
        # Long enough to exceed PREFILL_CHUNK (256) if chunking were used.
        tokens = await be.encode("word " * 900)
        assert len(tokens) > 256
        await sched.generate("one-shot", tokens, params(max_tokens=2), _noop)
        assert len(calls) == 1, f"expected a single prefill call, got {calls}"
        assert calls[0] == len(tokens)
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_snapshot_length_is_the_prompt_not_the_session():
    """The cache keys on the prompt, so it must snapshot exactly that many tokens.

    Regression: the scheduler used to let the session snapshot its *current*
    length, which by completion time includes every generated token. A hit then
    restored a longer context than the new request contained -- silent wrong
    output rather than an error.
    """
    from app.engine.mock import MockBackend

    be = MockBackend("m", context_length=4096)
    lengths: list[int] = []

    orig_new_session = be.new_session

    async def new_session():
        sess = await orig_new_session()
        orig_snapshot = sess.snapshot

        async def snapshot(token_len):
            lengths.append(token_len)
            return await orig_snapshot(token_len)

        sess.snapshot = snapshot
        return sess

    be.new_session = new_session

    sched = Scheduler(be, PrefixCache())
    await sched.start()
    try:
        # Must exceed the >=8-token threshold the cache requires before it stores anything.
        tokens = await be.encode("a reasonably long prompt worth caching in the prefix cache")
        prompt_len = len(tokens)
        req = await sched.generate("s1", tokens, params(max_tokens=4), _noop)
        assert lengths == [prompt_len], (
            f"snapshot took {lengths} tokens; the prompt is {prompt_len}"
        )
        # The session did generate, so a session-length snapshot would differ.
        assert len(req.generated) > 0
    finally:
        await sched.stop()


# ---------------------------------------------------------------------------
# stats: the idle sweep's and the memory card's inputs (MYS-2675)
# ---------------------------------------------------------------------------
async def test_stats_reports_inflight_under_the_name_the_sweep_asks_for():
    """Without this key every chat worker looked busy and could never be unloaded.

    ``ModelManager._worker_is_busy`` reads ``inflight`` because that is what an
    auxiliary worker reports. A scheduler with no such key answered ``None``,
    which the manager deliberately treats as "busy" (never kill a worker
    mid-call) -- so putting a chat model under idle unload silently did nothing.
    """
    be = MockBackend("m", context_length=512, decode_delay_per_token=0.01)
    sched = Scheduler(be, max_concurrent=2)
    idle = sched.stats()
    assert idle["inflight"] == 0, "an idle scheduler serves nothing"
    assert idle["inflight"] == idle["active"]

    await sched.start()
    try:
        done = asyncio.Event()

        async def sink(_t):
            return None

        async def kick():
            tokens = await be.encode("hello")
            await sched.generate("r1", tokens, params(max_tokens=40), sink)
            done.set()

        task = asyncio.create_task(kick())
        # Wait until it is actually running, then look.
        for _ in range(200):
            if sched.stats()["active"]:
                break
            await asyncio.sleep(0.01)
        running = sched.stats()
        assert running["inflight"] == 1
        done.set()
        task.cancel()
        with pytest.raises((asyncio.CancelledError, Exception)):
            await task
    finally:
        await sched.stop()


async def test_stats_reports_kv_used_bytes_and_it_moves():
    """What the sessions hold now, not what they could claim at full length."""
    be = MockBackend("m", context_length=512, decode_delay_per_token=0.002)
    be.kv_bytes_per_token = 1024
    be.linear_state_bytes = 4096
    sched = Scheduler(be, max_concurrent=1)
    assert sched.stats()["kv_used_bytes"] == 0

    await sched.start()
    try:
        seen = []

        async def sink(_t):
            seen.append(sched.stats()["kv_used_bytes"])

        tokens = await be.encode("hello world")
        await sched.generate("r1", tokens, params(max_tokens=6), sink)
        assert seen, "the sink ran"
        # A running session costs its linear state plus per-token KV at the
        # length it has reached -- strictly more than the state alone.
        assert all(v > be.linear_state_bytes for v in seen)
        # And it is back to nothing once the session is closed.
        assert sched.stats()["kv_used_bytes"] == 0
    finally:
        await sched.stop()
