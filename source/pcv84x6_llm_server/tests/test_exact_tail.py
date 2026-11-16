"""Prompts end with an exact tail: the scheduler asks the backend to run the
last `exact_tail` tokens of the final prefill piece through its decode graphs
(CV84X6: the prefill graphs' routed-expert MoE is inaccurate). Short prompts
get at most SHORT_EXACT_TAIL of them."""
import asyncio

from app.engine.base import GenerateParams
from app.engine.mock import MockBackend
from app.engine.scheduler import EXACT_TAIL_MIN_PROMPT, SHORT_EXACT_TAIL, Scheduler


class Recording(MockBackend):
    def __init__(self):
        super().__init__("m", context_length=8192)
        self.calls = []  # (exact_tail set before this feed, feed length)

    async def new_session(self):
        s = await super().new_session()
        feed = s.feed_prompt
        pending = {"tail": 0}

        def set_exact_tail(rows):
            pending["tail"] = rows

        async def spy(tokens):
            self.calls.append((pending["tail"], len(tokens)))
            pending["tail"] = 0
            await feed(tokens)
        s.set_exact_tail, s.feed_prompt = set_exact_tail, spy
        return s


def run(be, n, exact_tail):
    async def go():
        sched = Scheduler(be)
        sched.exact_tail = exact_tail
        await sched.start()

        async def sink(_):
            pass
        try:
            await sched.generate("r", list(range(3, 3 + n)), GenerateParams(max_tokens=1), sink)
        finally:
            await sched.stop()
    asyncio.run(go())


def test_long_prompt_sets_the_tail_on_its_last_piece_only():
    be = Recording()
    run(be, EXACT_TAIL_MIN_PROMPT + 500, 64)
    assert be.calls[-1][0] == 64
    assert all(t == 0 for t, _ in be.calls[:-1])
    assert sum(n for _, n in be.calls) == EXACT_TAIL_MIN_PROMPT + 500


def test_short_prompt_gets_the_short_tail():
    be = Recording()
    run(be, EXACT_TAIL_MIN_PROMPT - 1, 64)
    assert be.calls[-1][0] == SHORT_EXACT_TAIL
    assert all(t == 0 for t, _ in be.calls[:-1])


def test_short_tail_never_exceeds_the_setting():
    be = Recording()
    run(be, 67, 8)
    assert [t for t, _ in be.calls] == [8]


def test_tiny_prompt_still_gets_a_tail():
    be = Recording()
    run(be, 5, 64)
    assert be.calls == [(SHORT_EXACT_TAIL, 5)]


def test_tail_zero_disables_it_for_short_prompts():
    be = Recording()
    run(be, 67, 0)
    assert all(t == 0 for t, _ in be.calls)


def test_tail_zero_disables_it():
    be = Recording()
    run(be, EXACT_TAIL_MIN_PROMPT + 10, 0)
    assert all(t == 0 for t, _ in be.calls)
