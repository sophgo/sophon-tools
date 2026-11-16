"""Staged prefill for snapshotting backends, and Prompt.segment."""

import asyncio

import numpy as np
import pytest

from app.engine.base import GenerateParams
from app.engine.mock import MockBackend
from app.engine.native import NativeBackend, Prompt
from app.engine.scheduler import Scheduler


class _Tok:
    ids = {"<|im_start|>": 1, "<|im_end|>": 2, "<|image_pad|>": 9}

    def token_to_id(self, name):
        return self.ids.get(name)


def _planner():
    """NativeBackend.snapshot_points without loading a model."""
    be = object.__new__(NativeBackend)
    be._history = True
    be._tok = _Tok()
    be._image_pad_id = 9
    return be


def test_points_at_system_end_and_last_turn_aligned_to_64():
    # <|im_start|> system ... <|im_end|> \n (ends at 400), user turn, assistant at 700
    toks = [1] + [5] * 397 + [2, 7] + [1] + [5] * 298 + [2] + [1] + [5] * 10
    assert toks.index(2) + 2 == 400
    assert [i for i, t in enumerate(toks) if t == 1][-1] == 700
    # rounded down to the engine's 64-row prefill alignment
    assert _planner().snapshot_points(toks) == [384, 640]


def test_tiny_prefixes_are_not_snapshotted():
    # assistant turn starts at 12: under _MIN_SNAPSHOT_TOKENS
    toks = [1] + [5] * 8 + [2, 7] + [1] + [5] * 5
    assert _planner().snapshot_points(toks) == []


def test_short_chat_is_cut_exactly_at_the_last_turn():
    # A console chat: user turn, then the assistant turn at 40; 55 tokens in
    # all, so every row is replayed anyway and an exact cut costs nothing.
    toks = [1] + [5] * 37 + [2, 7] + [1] + [5] * 14
    assert len(toks) == 55
    assert _planner().snapshot_points(toks) == [40]


def test_short_cut_is_skipped_when_it_would_cost_a_prefill_block():
    # 100 tokens: unsplit, rows 0..63 go through one prefill block; cutting at
    # 50 would leave 50 + 50 rows, all replayed -- slower, so no cut.
    toks = [1] + [5] * 47 + [2, 7] + [1] + [5] * 49
    assert len(toks) == 100
    assert _planner().snapshot_points(toks) == []


def test_aligned_cuts_from_64_up():
    # assistant turn at 130 -> 128 (was dropped under the old 256 minimum)
    toks = [1] + [5] * 127 + [2, 7] + [1] + [5] * 20
    assert _planner().snapshot_points(toks) == [128]


def test_point_never_splits_an_image():
    # last assistant turn starts at 1000; image pads occupy 300..999
    toks = [1] + [5] * 298 + [8] + [9] * 700 + [1] + [5] * 5
    pts = _planner().snapshot_points(toks)
    assert pts  # moved before the image, not dropped
    for p in pts:
        assert not (300 < p <= 999)


def test_segment_keeps_positions_and_rebases_images():
    # pos3 is a flat [3, n] row-major int32 buffer, the layout the engine takes.
    pos = [i for _ in range(3) for i in range(30)]
    img = {"offset": 12, "patches": 16, "pixels": None}
    p = Prompt(list(range(30)), pos3=pos, images=[img])
    seg = p.segment(10, 30)
    assert list(seg) == list(range(10, 30))
    assert len(seg.pos3) == 3 * 20
    assert seg.pos3[0] == 10 and seg.pos3[20] == 10 and seg.pos3[40] == 10
    assert seg.images[0]["offset"] == 2
    assert p.segment(0, 10).images == []
    with pytest.raises(ValueError):
        p.segment(0, 14)  # would cut the image (rows 12..15)


def test_text_segment_gets_absolute_positions():
    seg = Prompt(list(range(40))).segment(16, 40)
    n = len(seg)  # 24
    # [3, n] row-major: each row is the same absolute position run.
    assert seg.pos3[0] == 16 and seg.pos3[n - 1] == 39
    assert seg.pos3[n] == 16 and seg.pos3[2 * n] == 16
    assert seg.pos3[3 * n - 1] == 39


class _Snapshotting(MockBackend):
    """Mock that only snapshots at the current length, like the engine."""

    def __init__(self, points):
        super().__init__("m", min_tokens=1)
        self._points = points
        self.feeds = []
        self.snaps = []

    @property
    def supports_chunked_prefill(self):
        return True

    @property
    def prefill_chunk(self):
        return 1000

    def snapshot_points(self, tokens):
        return self._points

    async def new_session(self):
        s = await super().new_session()
        be = self
        feed, snap = s.feed_prompt, s.snapshot

        async def spy_feed(tokens):
            be.feeds.append(len(tokens))
            await feed(tokens)

        async def spy_snap(n):
            assert n == s.token_len, "snapshot must be at the current length"
            be.snaps.append(n)
            return await snap(n)
        s.feed_prompt, s.snapshot = spy_feed, spy_snap
        return s


def _run(backend, tokens, repeat=1):
    async def go():
        sched = Scheduler(backend)
        await sched.start()

        async def sink(_):
            pass
        reqs = []
        try:
            for i in range(repeat):
                reqs.append(await sched.generate(f"r{i}", tokens, GenerateParams(max_tokens=2), sink))
        finally:
            await sched.stop()
        return reqs
    return asyncio.run(go())


def test_prefill_stops_at_points_and_snapshots_there():
    be = _Snapshotting([32, 64])
    _run(be, list(range(3, 83)))
    assert be.feeds == [32, 32, 16]
    assert be.snaps == [32, 64]


def test_second_request_resumes_from_the_longest_snapshot():
    be = _Snapshotting([32, 64])
    reqs = _run(be, list(range(3, 83)), repeat=2)
    assert be.feeds[3:] == [16]          # only the part after 64
    assert reqs[1].cached_tokens == 64
    assert be.snaps == [32, 64]          # nothing re-snapshotted
