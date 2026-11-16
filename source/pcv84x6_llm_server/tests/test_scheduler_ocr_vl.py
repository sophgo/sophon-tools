"""The two scheduler rules OCR-VL needs, asserted on the scheduler itself.

Both are stated as *backend capabilities* rather than as a branch on the model
id, so they are tested the same way: a stub backend that sets the flag, and the
scheduler's own behaviour.

* ``serial_only``: one KV cache means one session. The queue must still be the
  thing that grows (so a fourth caller gets 429, not a crash), which is what
  distinguishes "serial" from "broken".
* ``detects_loops``: a table repeats ``<fcel>value`` by design. The repetition
  cut exists for a greedy model that runs out of momentum; applied here it would
  end the answer in the middle of a table. The default must stay True, or every
  chat model loses the cut.
"""

from __future__ import annotations

import asyncio

import pytest

from app.engine.base import EngineBackend, GenerateParams, Session
from app.engine.scheduler import Busy, Scheduler


class _Session(Session):
    def __init__(self, tokens) -> None:
        self._tokens = list(tokens)
        self.closed = False

    @property
    def token_len(self) -> int:
        return len(self._tokens)

    async def feed_prompt(self, tokens) -> None:
        self._tokens.extend(tokens)

    async def step(self) -> int:
        # A token stream the repetition rule recognises: the same 6-token span
        # over and over, which is exactly what a table row looks like.
        self._tokens.append(7)
        return 7

    def decode(self, tokens) -> str:
        return "x"

    def is_stop_token(self, token: int) -> bool:
        return False

    async def snapshot(self, token_len: int) -> object:
        raise AssertionError("not used")

    async def restore(self, snap: object) -> None:
        raise AssertionError("not used")

    async def close(self) -> None:
        self.closed = True


class _Backend(EngineBackend):
    def __init__(self, *, serial_only: bool, detects_loops: bool,
                 answer_len: int = 200) -> None:
        self.serial_only = serial_only
        self.detects_loops = detects_loops
        self.answer_len = answer_len
        self.sessions = 0

    @property
    def model_id(self) -> str:
        return "stub"

    @property
    def context_length(self) -> int:
        return 2048

    @property
    def supports_vision(self) -> bool:
        return True

    async def encode(self, text, images=None):
        return [1, 2, 3]

    async def new_session(self) -> Session:
        self.sessions += 1
        return _Session([1, 2, 3])

    async def close(self) -> None:
        return None


async def _run(sched, req_id="r1", max_tokens=200):
    seen: list[str] = []

    async def sink(text: str) -> None:
        seen.append(text)

    req = sched.enqueue(req_id, [1, 2, 3], GenerateParams(max_tokens=max_tokens), sink)
    await sched.wait(req)
    return req, seen


def test_serial_only_forces_one_slot():
    """One KV cache: the scheduler must never admit a second session.

    Not a config knob -- ``max_concurrent=3`` from the console is exactly the
    setting this must override, because admitting three sessions would have
    three requests writing into one KV buffer.
    """
    sched = Scheduler(_Backend(serial_only=True, detects_loops=False), max_concurrent=3)
    assert sched.max_concurrent == 1


def test_a_backend_without_the_flag_keeps_its_slots():
    sched = Scheduler(_Backend(serial_only=False, detects_loops=True), max_concurrent=3)
    assert sched.max_concurrent == 3


def test_the_queue_still_bounds_a_serial_backend():
    """Serial is not unbounded: past max_queue the caller is refused (429).

    A backend that quietly accepted everything would hold every image in the
    worker's memory while they waited for the one KV cache.
    """
    sched = Scheduler(_Backend(serial_only=True, detects_loops=False),
                      max_concurrent=3, max_queue=1)
    assert sched.max_concurrent == 1
    sched.submit("a", [1], GenerateParams())
    sched.submit("b", [1], GenerateParams())
    with pytest.raises(Busy):
        sched.submit("c", [1], GenerateParams())


async def test_a_looping_answer_is_cut_by_default():
    sched = Scheduler(_Backend(serial_only=False, detects_loops=True))
    await sched.start()
    try:
        req, _ = await _run(sched)
    finally:
        await sched.stop()
    assert req.finish_reason == "stop"
    assert len(req.generated) < 200, "the repetition cut should have fired"


async def test_detects_loops_false_lets_a_repeating_table_finish():
    """The OCR-VL case: `<fcel>值` twenty times is content, not a stuck model."""
    backend = _Backend(serial_only=True, detects_loops=False)
    sched = Scheduler(backend)
    await sched.start()
    try:
        req, _ = await _run(sched)
    finally:
        await sched.stop()
    assert req.finish_reason == "length", (
        "without the cut the request runs to max_tokens, which is what a table needs")
    assert len(req.generated) == 200


async def test_two_requests_never_share_the_engine():
    """The one KV cache is the whole reason for `serial_only`.

    Two requests are in flight and both succeed, but the scheduler never has
    more than one *active* at a time -- so neither can be decoding while the
    other holds the cache. Their answers still have to be right, which is what
    makes "serial" different from "the second one silently won".
    """
    backend = _Backend(serial_only=True, detects_loops=False)
    sched = Scheduler(backend)
    peak = 0

    real_advance = sched._advance

    async def watched(req):
        nonlocal peak
        peak = max(peak, len(sched._active))
        await real_advance(req)

    sched._advance = watched
    await sched.start()
    try:
        seen: list[str] = []

        async def sink(text: str) -> None:
            seen.append(text)

        a = sched.enqueue("a", [1, 2, 3], GenerateParams(max_tokens=8), sink)
        b = sched.enqueue("b", [4, 5, 6], GenerateParams(max_tokens=8), sink)
        await asyncio.gather(sched.wait(a), sched.wait(b))
    finally:
        await sched.stop()
    assert peak == 1, "two sessions would be two writers into one KV cache"
    assert a.finish_reason == b.finish_reason == "length"
    assert backend.sessions == 2, "each request still gets its own session"
