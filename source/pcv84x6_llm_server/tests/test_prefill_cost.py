"""What losing chunked prefill actually costs, measured.

The SAIL backend must prefill a prompt in one blocking call, so during that call
the worker's scheduler loop cannot advance any other session. This measures the
stall a concurrent decoder sees, under both kinds of backend, using the mock's
configurable delays scaled to the board's measured rates (prefill ~190 tok/s,
decode ~22 tok/s).
"""

import asyncio

import pytest

from app.engine.base import GenerateParams
from app.engine.mock import MockBackend
from app.engine.scheduler import PREFILL_CHUNK, Scheduler

# Measured on the CV84X6 board: prefill ~190 token/s, decode ~22 token/s.
PREFILL_S = 1 / 190
DECODE_S = 1 / 22


class NoChunkBackend(MockBackend):
    """Behaves like SAIL: feed_prompt blocks for the whole prompt."""

    @property
    def supports_chunked_prefill(self) -> bool:
        return False


def params(**kw):
    base = dict(max_tokens=40, temperature=0.0, top_p=1.0, top_k=1)
    base.update(kw)
    return GenerateParams(**base)


async def measure_max_stall(backend, prompt_tokens: int) -> float:
    """Longest gap between two consecutive steps of an already-decoding request.

    That gap is what a user sees as a freeze: the stream stops while another
    request's prefill runs.
    """
    sched = Scheduler(backend, max_concurrent=4)
    await sched.start()
    try:
        short = await backend.encode("short prompt")
        # Start a long prompt first so its prefill collides with the decoder.
        long_ids = (await backend.encode("pad " * 2000))[:prompt_tokens]

        stalls: list[float] = []
        loop = asyncio.get_running_loop()

        async def decoding_sink(_text):
            now = loop.time()
            if stalls:
                stalls.append(now - stalls[-1])
            else:
                stalls.append(now)
            stalls[-1] = now

        # Run a decoder that will be mid-stream when the long prefill lands.
        dec = asyncio.create_task(
            sched.generate("decoder", short, params(max_tokens=40), decoding_sink)
        )
        await asyncio.sleep(DECODE_S * 3)          # let it get going
        pre = asyncio.create_task(
            sched.generate("long", long_ids, params(max_tokens=2),
                           lambda t: asyncio.sleep(0))
        )
        await asyncio.gather(dec, pre)
        # Deltas between successive token arrivals.
        deltas = [stalls[i] - stalls[i - 1] for i in range(1, len(stalls))]
        return max(deltas) if deltas else 0.0
    finally:
        await sched.stop()


@pytest.mark.asyncio
async def test_chunked_prefill_keeps_other_sessions_flowing():
    chunked = MockBackend("m", context_length=8192,
                          prefill_delay_per_token=PREFILL_S,
                          decode_delay_per_token=DECODE_S)
    stall = await measure_max_stall(chunked, prompt_tokens=800)
    # With 256-token chunks the worst stall is about one chunk of prefill.
    one_chunk = PREFILL_CHUNK * PREFILL_S
    assert stall < one_chunk * 3, f"chunked prefill stalled a decoder for {stall:.2f}s"


@pytest.mark.asyncio
async def test_unchunked_prefill_stalls_the_whole_worker():
    """Documents the real cost: the decoder freezes for the entire prefill."""
    plain = NoChunkBackend("m", context_length=8192,
                           prefill_delay_per_token=PREFILL_S,
                           decode_delay_per_token=DECODE_S)
    stall = await measure_max_stall(plain, prompt_tokens=800)
    whole_prefill = 800 * PREFILL_S          # ~4.2 s at the board's rate
    assert stall > whole_prefill * 0.6, (
        f"expected a ~{whole_prefill:.1f}s stall without chunking, saw {stall:.2f}s"
    )
