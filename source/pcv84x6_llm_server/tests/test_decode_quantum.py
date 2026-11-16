"""The decode quantum: N tokens per request per round-robin visit.

Why this exists (MYS-2468, docs/research/decode-optimization.md §5.1): one token per
visit makes the engine park/unpark 34.7 MB of linear-attention state on every
single token, so two concurrent sessions ran at 0.71x one stream. An 8-token
slice measured 0.94x (0.93x at 2048 context) with every generated token
identical. These tests pin the semantics the change must not break: the same
tokens, the same stop conditions, the same cancellation, and the same
per-token bookkeeping.
"""
import asyncio
import json

import pytest

from app.engine.base import GenerateParams
from app.engine.mock import MockBackend
from app.engine.prefix_cache import PrefixCache
from app.engine.scheduler import (
    DEFAULT_DECODE_QUANTUM,
    MAX_DECODE_QUANTUM,
    Scheduler,
    clamp_decode_quantum,
)


def params(**kw):
    base = dict(max_tokens=5, temperature=0.0, top_p=1.0, top_k=1)
    base.update(kw)
    return GenerateParams(**base)


async def _noop(_text):
    return None


async def run(prompt: str, max_tokens: int, quantum: int, *, context: int = 512,
              min_tokens: int = 24, delay: float = 0.0):
    """Run one request at a given quantum; return (request, streamed text, order)."""
    be = MockBackend("m", context_length=context, decode_delay_per_token=delay,
                     min_tokens=min_tokens)
    sched = Scheduler(be, decode_quantum=quantum)
    await sched.start()
    chunks: list[str] = []
    try:
        tokens = await be.encode(prompt)
        req = await sched.generate("r", tokens, params(max_tokens=max_tokens),
                                   lambda t: _collect(chunks, t))
        return req, chunks
    finally:
        await sched.stop()


async def _collect(bucket, text):
    bucket.append(text)


# -- configuration -----------------------------------------------------------

def test_default_quantum_is_eight():
    assert DEFAULT_DECODE_QUANTUM == 8
    assert MAX_DECODE_QUANTUM >= 8
    be = MockBackend("m")
    assert Scheduler(be).decode_quantum == 8


@pytest.mark.parametrize("given,want", [
    (1, 1), (8, 8), (32, 32),
    (0, 1),          # would never advance a request
    (-5, 1),         # same, from a bad console write
    (33, 32), (10 ** 6, 32),
])
def test_quantum_is_clamped_into_range(given, want):
    assert clamp_decode_quantum(given) == want
    sched = Scheduler(MockBackend("m"))
    sched.decode_quantum = given
    assert sched.decode_quantum == want


@pytest.mark.parametrize("given", ["eight", None, object()])
def test_non_numeric_quantum_falls_back_to_the_default(given):
    assert clamp_decode_quantum(given) == DEFAULT_DECODE_QUANTUM


@pytest.mark.parametrize("given,want", [(True, DEFAULT_DECODE_QUANTUM),
                                        (False, DEFAULT_DECODE_QUANTUM),
                                        ("6", 6), (3.9, 3)])
def test_int_like_values_are_converted(given, want):
    # A bool is a client mistake (``true`` is not "rotate every token"), but a
    # numeric string or a float from JSON is converted, not thrown away.
    assert clamp_decode_quantum(given) == want


def test_quantum_is_reported_in_stats():
    sched = Scheduler(MockBackend("m"), decode_quantum=4)
    assert sched.stats()["decode_quantum"] == 4


# -- output equivalence ------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("max_tokens", [1, 7, 8, 9, 32])
async def test_q8_streams_exactly_what_q1_streams(max_tokens):
    """The quantum must not move a single token or a single text chunk."""
    _, one = await run("the same prompt for both quanta", max_tokens, quantum=1)
    _, eight = await run("the same prompt for both quanta", max_tokens, quantum=8)
    assert one == eight
    assert len(one) > 0


@pytest.mark.asyncio
async def test_q8_records_one_decode_sample_and_one_count_per_token():
    req, chunks = await run("count every token", 12, quantum=8)
    assert len(req.generated) == 12
    # Text parts and streamed chunks both count tokens, not slices.
    assert len(req.text_parts) == 12
    assert len(chunks) == 12


@pytest.mark.asyncio
async def test_decode_times_holds_one_sample_per_step():
    be = MockBackend("m", context_length=512)
    sched = Scheduler(be, decode_quantum=8)
    await sched.start()
    try:
        tokens = await be.encode("sample every step")
        await sched.generate("r", tokens, params(max_tokens=8), _noop)
        # One entry per real step() call: exactly the generated tokens.
        assert len(sched._decode_times) == sched.total_completion_tokens
        assert sched.stats()["completion_tokens"] == 8
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_first_token_timestamp_is_the_first_token_only():
    be = MockBackend("m", context_length=512, decode_delay_per_token=0.005,
                     min_tokens=10_000)
    sched = Scheduler(be, decode_quantum=8)
    await sched.start()
    try:
        tokens = await be.encode("when was the first token")
        req = sched.submit("r", tokens, params(max_tokens=8))
        await asyncio.sleep(0.001)
        assert req.first_token_at is None
        for _ in range(200):
            if req.state in ("done", "error"):
                break
            await asyncio.sleep(0.01)
        # Eight tokens at 5 ms each: a slice-wide timestamp would land a whole
        # slice after started_at, so bound it to about one step's worth.
        assert req.first_token_at - req.started_at < 0.05
        assert req.finish_reason == "length"
    finally:
        await sched.stop()


# -- rotation and yielding ---------------------------------------------------

@pytest.mark.asyncio
async def test_slices_stay_inside_one_quantum():
    """No request may hold the TPU for more than `quantum` tokens in a row."""
    be = MockBackend("m", context_length=4096, decode_delay_per_token=0.0)
    sched = Scheduler(be, max_concurrent=4, decode_quantum=8)
    await sched.start()
    try:
        order: list[str] = []

        async def one(name, text):
            tokens = await be.encode(text)
            return await sched.generate(name, tokens, params(max_tokens=24),
                                        lambda t: _mark(order, name))

        await asyncio.gather(*(one(f"c{i}", f"prompt {i}") for i in range(3)))
        # Each visit contributes at most `quantum` consecutive tokens.
        runs, current, count = [], None, 0
        for name in order:
            if name == current:
                count += 1
            else:
                if current is not None:
                    runs.append(count)
                current, count = name, 1
        runs.append(count)
        assert max(runs) <= sched.decode_quantum, f"slice longer than the quantum: {runs}"
        # And the rotation really happens: more than one visit per request.
        assert len(runs) > 3
    finally:
        await sched.stop()


async def _mark(order, name):
    order.append(name)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_other_sessions_run_during_a_slice():
    """A quantum must not starve the others, only stretch their turn spacing."""
    be = MockBackend("m", context_length=512, decode_delay_per_token=0.0)
    sched = Scheduler(be, max_concurrent=4, decode_quantum=8)
    await sched.start()
    try:
        order: list[str] = []

        async def one(name, text):
            tokens = await be.encode(text)
            return await sched.generate(name, tokens, params(max_tokens=16),
                                        lambda t: _mark(order, name))

        await asyncio.gather(*(one(f"c{i}", f"prompt number {i}") for i in range(2)))
        first_half = order[: len(order) // 2]
        assert set(first_half) == {"c0", "c1"}, order
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_prefill_still_hands_over_inside_a_quantum_window():
    """Prefill is one chunk per visit whatever the quantum is, so a long prompt
    cannot make a decoding session wait for a whole slice's worth of prefill."""
    be = MockBackend("m", context_length=8192, prefill_delay_per_token=0.0005)
    sched = Scheduler(be, max_concurrent=4, decode_quantum=8)
    await sched.start()
    try:
        chords: list[str] = []

        async def decoder():
            tokens = await be.encode("short decoder prompt")
            return await sched.generate("dec", tokens, params(max_tokens=40),
                                        lambda t: _mark(chords, "dec"))

        dec = asyncio.create_task(decoder())
        await asyncio.sleep(0.01)
        long_tokens = await be.encode("pad " * 1500)  # > PREFILL_CHUNK
        pre = asyncio.create_task(
            sched.generate("pre", long_tokens, params(max_tokens=2),
                           lambda t: _mark(chords, "pre"))
        )
        await asyncio.gather(dec, pre)
        # The decoder kept streaming while the prompt was being fed in chunks.
        between = chords[: chords.index("pre")] if "pre" in chords else chords
        assert between.count("dec") > sched.decode_quantum, (
            "the decoder stalled for the whole prefill instead of interleaving")
    finally:
        await sched.stop()


# -- stop conditions ---------------------------------------------------------

@pytest.mark.asyncio
async def test_length_stops_inside_a_slice_and_never_overruns():
    """max_tokens=3 with a quantum of 8 must emit 3 tokens, not 8."""
    req, chunks = await run("stop at three", 3, quantum=8, min_tokens=10_000)
    assert req.finish_reason == "length"
    assert len(req.generated) == 3
    assert len(chunks) == 3


@pytest.mark.asyncio
async def test_stop_token_stops_inside_a_slice():
    """The mock emits its stop token from token 0 with min_tokens=0."""
    be = MockBackend("m", context_length=512, min_tokens=0)
    sched = Scheduler(be, decode_quantum=8)
    await sched.start()
    try:
        tokens = await be.encode("stop immediately")
        chunks: list[str] = []
        req = await sched.generate("r", tokens, params(max_tokens=64),
                                   lambda t: _collect(chunks, t))
        assert req.finish_reason == "stop"
        # The stop token itself is counted (as before) but not appended to
        # `generated` and not streamed, and the slice did not run past it.
        assert sched.stats()["completion_tokens"] == len(req.generated) + 1
        assert len(chunks) == len(req.generated)
        assert len(req.generated) < 64
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_context_limit_stops_inside_a_slice():
    be = MockBackend("m", context_length=32, min_tokens=10_000)
    sched = Scheduler(be, decode_quantum=8)
    await sched.start()
    try:
        tokens = await be.encode("padding " * 10)
        req = await sched.generate("ctx", tokens, params(max_tokens=10_000), _noop)
        assert req.finish_reason == "length"
        assert req.session is None
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_loop_detection_stops_inside_a_slice():
    """A backend stuck on one span must be cut, not decoded for the whole slice."""
    be = MockBackend("m", context_length=2048)
    sched = Scheduler(be, decode_quantum=16)
    await sched.start()
    try:
        tokens = await be.encode("loop forever")
        req = await sched.generate("r", tokens, params(max_tokens=1000), _noop)
        # Whichever reason fires first, the request ends well before the slice
        # count would allow if the checks only ran once per slice.
        assert req.finish_reason in ("stop", "length")
        assert len(req.generated) < 1000
    finally:
        await sched.stop()


# -- cancellation ------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_mid_slice_stops_the_stream_immediately():
    """Cancelling during a slice: no token after the cancel reaches the client."""
    be = MockBackend("m", context_length=4096, decode_delay_per_token=0.01,
                     min_tokens=10_000)
    sched = Scheduler(be, max_concurrent=1, decode_quantum=32)
    await sched.start()
    seen: list[float] = []
    cancelled_at: list[float] = []
    try:
        tokens = await be.encode("a prompt that keeps going")
        req = sched.submit("victim", tokens, params(max_tokens=1000))

        async def sink(_text):
            seen.append(asyncio.get_running_loop().time())
            if len(seen) == 5:
                assert sched.cancel("victim") is True
                cancelled_at.append(asyncio.get_running_loop().time())

        req.on_token = sink
        for _ in range(200):
            if req.state in ("done", "error"):
                break
            await asyncio.sleep(0.01)
        assert req.finish_reason == "cancelled"
        assert req.state == "done"
        # At most the token whose step was already in flight may have been
        # produced after the cancel; a whole remaining slice would be many more.
        assert len(seen) - 5 <= 1, f"{len(seen) - 5} tokens streamed after the cancel"
        assert req.session is None
        assert sched.stats()["active"] == 0
        assert sched.stats()["cancelled_requests"] == 1
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_cancel_between_slices_works_with_big_quantum():
    """A big quantum must still let a cancel land: every token yields."""
    be = MockBackend("m", context_length=4096, decode_delay_per_token=0.005,
                     min_tokens=10_000)
    sched = Scheduler(be, max_concurrent=2, decode_quantum=32)
    await sched.start()
    try:
        tokens = await be.encode("long runner")
        req = sched.submit("long", tokens, params(max_tokens=10_000))
        await asyncio.sleep(0.06)  # ~12 tokens in, mid-slice
        assert req.state == "decode"
        assert sched.cancel("long") is True
        for _ in range(100):
            if req.state in ("done", "error"):
                break
            await asyncio.sleep(0.01)
        assert req.finish_reason == "cancelled"
        assert sched.stats()["active"] == 0
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_a_sink_that_raises_cancels_mid_slice():
    """A dead client surfaces as a write error from the sink, mid-slice too."""
    be = MockBackend("m", context_length=512, decode_delay_per_token=0.001,
                     min_tokens=10_000)
    sched = Scheduler(be, max_concurrent=1, decode_quantum=32)
    await sched.start()
    delivered = []

    async def broken_sink(text):
        delivered.append(text)
        if len(delivered) == 3:
            raise ConnectionResetError("client went away")

    try:
        tokens = await be.encode("broken client")
        req = sched.submit("brk", tokens, params(max_tokens=1000))
        req.on_token = broken_sink
        for _ in range(100):
            if req.state in ("done", "error"):
                break
            await asyncio.sleep(0.01)
        assert req.finish_reason == "cancelled"
        assert req.error is None, "a disconnect is not an inference failure"
        # Nothing is written after the sink raised.
        assert len(delivered) == 3
        assert sched.stats()["failed_requests"] == 0
    finally:
        await sched.stop()


# -- interaction with the other features -------------------------------------

@pytest.mark.asyncio
async def test_single_request_is_unaffected_by_the_quantum():
    """One active session never rotates, so the quantum must not change a thing."""
    five_q1, chunks_q1 = await run("solo request", 20, quantum=1)
    five_q8, chunks_q8 = await run("solo request", 20, quantum=8)
    assert chunks_q1 == chunks_q8
    assert five_q1.finish_reason == five_q8.finish_reason
    assert len(five_q1.generated) == len(five_q8.generated)


@pytest.mark.asyncio
async def test_prefix_cache_still_hits_with_a_quantum():
    be = MockBackend("m", context_length=4096)
    sched = Scheduler(be, PrefixCache(), decode_quantum=8)
    await sched.start()
    try:
        prompt = "the same system prompt repeated verbatim"
        tokens = await be.encode(prompt)
        await sched.generate("a", tokens, params(max_tokens=4), _noop)
        before = sched.stats()["cache"]["tokens_reused"]
        req = await sched.generate("b", tokens, params(max_tokens=4), _noop)
        after = sched.stats()["cache"]["tokens_reused"]
        assert req.cached_tokens > 0
        assert after > before
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_snapshot_length_is_still_the_prompt_under_a_quantum():
    be = MockBackend("m", context_length=4096)
    lengths: list[int] = []
    orig = be.new_session

    async def new_session():
        sess = await orig()
        orig_snap = sess.snapshot

        async def snapshot(token_len):
            lengths.append(token_len)
            return await orig_snap(token_len)

        sess.snapshot = snapshot
        return sess

    be.new_session = new_session
    sched = Scheduler(be, PrefixCache(), decode_quantum=8)
    await sched.start()
    try:
        tokens = await be.encode("a long enough prompt to be worth caching indeed")
        prompt_len = len(tokens)
        req = await sched.generate("s", tokens, params(max_tokens=8), _noop)
        assert lengths == [prompt_len]
        assert len(req.generated) == 8
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_reconfiguring_the_quantum_does_not_disturb_running_requests():
    """A settings push applies from the next slice, not to the one in flight."""
    be = MockBackend("m", context_length=512, decode_delay_per_token=0.005,
                     min_tokens=10_000)
    sched = Scheduler(be, max_concurrent=2, decode_quantum=8)
    await sched.start()
    try:
        tokens = await be.encode("running request")
        req = sched.submit("r", tokens, params(max_tokens=40))
        await asyncio.sleep(0.02)
        assert req.state == "decode"
        done_before = len(req.generated)

        sched.decode_quantum = 1
        assert sched.decode_quantum == 1

        for _ in range(300):
            if req.state in ("done", "error"):
                break
            await asyncio.sleep(0.01)
        assert req.state == "done"
        assert len(req.generated) == 40  # no token lost or repeated
        assert len(req.generated) > done_before
        assert sched.stats()["decode_quantum"] == 1
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_quantum_one_reproduces_the_old_rotation():
    """q=1 is a strict fallback: one token per visit, one visit per loop."""
    be = MockBackend("m", context_length=512)
    sched = Scheduler(be, max_concurrent=4, decode_quantum=1)
    await sched.start()
    try:
        order: list[str] = []

        async def one(name, text):
            tokens = await be.encode(text)
            return await sched.generate(name, tokens, params(max_tokens=12),
                                        lambda t: _mark(order, name))

        await asyncio.gather(*(one(f"c{i}", f"prompt number {i}") for i in range(3)))
        # No two consecutive tokens may come from the same request.
        assert all(order[i] != order[i + 1] for i in range(len(order) - 1)), order
    finally:
        await sched.stop()


# -- worker configuration surface -------------------------------------------
#
# The quantum is reachable three ways and all three have to agree: the CLI flag
# the model manager passes, the console's `configure` op, and the stats reply
# the console reads back.

async def _spawn_worker(port: int, *extra: str):
    proc = await asyncio.create_subprocess_exec(
        "python3", "-m", "app.engine.worker",
        "--model-id", "m", "--port", str(port), "--backend", "mock",
        "--context-length", "4096", *extra,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    line = await asyncio.wait_for(proc.stdout.readline(), timeout=20)
    assert json.loads(line)["event"] == "ready"
    return proc


async def _stop_worker(proc):
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=10)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()


async def _rpc(reader, writer, obj):
    writer.write((json.dumps(obj) + "\n").encode())
    await writer.drain()
    return json.loads(await asyncio.wait_for(reader.readline(), timeout=20))


@pytest.mark.asyncio
async def test_worker_cli_flag_reaches_the_scheduler():
    port = 18961
    proc = await _spawn_worker(port, "--decode-quantum", "3")
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        stats = await _rpc(reader, writer, {"op": "stats"})
        assert stats["decode_quantum"] == 3
        writer.close()
    finally:
        await _stop_worker(proc)


@pytest.mark.asyncio
async def test_worker_defaults_to_eight_without_the_flag():
    port = 18962
    proc = await _spawn_worker(port)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        assert (await _rpc(reader, writer, {"op": "stats"}))["decode_quantum"] == 8
        writer.close()
    finally:
        await _stop_worker(proc)


@pytest.mark.asyncio
@pytest.mark.parametrize("given,want", [("0", 1), ("-4", 1), ("999", MAX_DECODE_QUANTUM),
                                        ("1", 1)])
async def test_worker_clamps_an_out_of_range_flag(given, want):
    port = 18963
    proc = await _spawn_worker(port, "--decode-quantum", given)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        assert (await _rpc(reader, writer, {"op": "stats"}))["decode_quantum"] == want
        writer.close()
    finally:
        await _stop_worker(proc)


@pytest.mark.asyncio
async def test_configure_op_sets_the_quantum_and_reports_it():
    port = 18964
    proc = await _spawn_worker(port)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        applied = await _rpc(reader, writer, {"op": "configure", "decode_quantum": 4})
        assert applied["decode_quantum"] == 4
        assert (await _rpc(reader, writer, {"op": "stats"}))["decode_quantum"] == 4

        # Out of range through the console path too: clamped, not stored as-is.
        clamped = await _rpc(reader, writer, {"op": "configure", "decode_quantum": 500})
        assert clamped["decode_quantum"] == MAX_DECODE_QUANTUM

        # And back to the old behaviour.
        back = await _rpc(reader, writer, {"op": "configure", "decode_quantum": 1})
        assert back["decode_quantum"] == 1
        writer.close()
    finally:
        await _stop_worker(proc)


@pytest.mark.asyncio
async def test_configure_without_the_field_leaves_the_quantum_alone():
    port = 18965
    proc = await _spawn_worker(port, "--decode-quantum", "6")
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        applied = await _rpc(reader, writer, {"op": "configure", "max_queue": 9})
        assert applied["decode_quantum"] == 6
        writer.close()
    finally:
        await _stop_worker(proc)


@pytest.mark.asyncio
async def test_a_live_reconfiguration_keeps_the_request_correct():
    """Flip the quantum while a request is streaming: same text, same length."""
    port = 18966
    proc = await _spawn_worker(port, "--decode-quantum", "8", "--mock-min-tokens", "1000")
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write((json.dumps({
            "op": "generate", "req_id": "live", "prompt": "stream while reconfiguring",
            "params": {"max_tokens": 24},
        }) + "\n").encode())
        await writer.drain()

        deltas: list[str] = []
        reconfigured = False
        done = None
        while done is None:
            msg = json.loads(await asyncio.wait_for(reader.readline(), timeout=20))
            if msg["op"] == "delta":
                deltas.append(msg["text"])
                if len(deltas) == 3 and not reconfigured:
                    reconfigured = True
                    writer.write((json.dumps({
                        "op": "configure", "decode_quantum": 1,
                    }) + "\n").encode())
                    await writer.drain()
            elif msg["op"] in ("done", "error"):
                done = msg
        assert reconfigured
        assert done["op"] == "done", done
        assert done["completion_tokens"] == len(deltas) == 24
        assert done["finish_reason"] == "length"
        writer.close()
    finally:
        await _stop_worker(proc)
