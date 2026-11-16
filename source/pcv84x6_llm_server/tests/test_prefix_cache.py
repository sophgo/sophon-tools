import pytest

from app.engine.prefix_cache import PrefixCache, cumulative_hashes


def test_cumulative_hashes_distinct_and_prefix_stable():
    a = cumulative_hashes([1, 2, 3])
    b = cumulative_hashes([1, 2, 3, 4])
    assert len(a) == 4 and len(b) == 5
    assert a[:4] == b[:4], "a longer prompt must share the shorter prefix hashes"
    assert len(set(a)) == len(a)


def test_lookup_misses_on_empty_and_unknown():
    c = PrefixCache()
    assert c.lookup([]) is None
    assert c.lookup([1, 2, 3]) is None


def test_put_then_lookup_returns_longest_prefix():
    c = PrefixCache()
    c.put([1, 2, 3, 4], "snap-4")
    c.put([1, 2], "snap-2")
    hit = c.lookup([1, 2, 3, 4, 5, 6])
    assert hit is not None
    n, snap = hit
    assert n == 4 and snap == "snap-4", "must pick the longest matching prefix"


def test_lookup_rejects_non_prefix():
    c = PrefixCache()
    c.put([1, 2, 3], "s")
    assert c.lookup([9, 9, 9]) is None


def test_same_prompt_does_not_duplicate():
    c = PrefixCache()
    c.put([1, 2, 3], "s1")
    c.put([1, 2, 3], "s2")
    assert len(c) == 1


def test_lru_eviction_respects_entry_cap():
    c = PrefixCache(max_entries=2)
    c.put([1, 2], "a")
    c.put([3, 4], "b")
    c.put([5, 6], "c")
    assert len(c) == 2
    assert c.stats.evictions == 1


def test_hit_rate_is_token_weighted():
    c = PrefixCache()
    c.put([1, 2, 3, 4], "s")
    c.lookup([1, 2, 3, 4, 5])          # 4 reused
    c.record_prompt_tokens(6)          # 6 had to be prefilled
    assert c.stats.tokens_reused == 4
    assert c.stats.hit_rate == pytest.approx(4 / 10)


def test_short_prompts_are_not_cached():
    c = PrefixCache()
    c.put([1], "s")
    assert len(c) == 0, "a 1-token prompt is not worth a slot"


def test_default_budget_scales_to_available_memory():
    """On the board (2.5 GiB visible) the budget must not be a fixed 512 MiB."""
    from app.engine.prefix_cache import default_max_bytes
    n = default_max_bytes()
    assert n > 0
    assert n <= 512 * 1024 * 1024


def test_default_cache_uses_scaled_budget():
    from app.engine.prefix_cache import PrefixCache, default_max_bytes
    assert PrefixCache().max_bytes == default_max_bytes()


def test_scheduler_keeps_the_cache_it_was_given():
    """An empty cache is falsy (len 0); the scheduler must not swap it out."""
    from app.engine.mock import MockBackend
    from app.engine.scheduler import Scheduler

    pc = PrefixCache(max_entries=3, max_bytes=123)
    assert len(pc) == 0
    assert Scheduler(MockBackend("m"), prefix_cache=pc).prefix_cache is pc


class _Snap:
    def __init__(self, n):
        self.nbytes = n
        self.released = False

    def release(self):
        self.released = True


def test_idle_entries_expire_and_release_their_memory():
    pc = PrefixCache(max_entries=8, max_bytes=1 << 30, ttl_s=60)
    a, b = _Snap(10), _Snap(10)
    pc.put([1, 2, 3], a)
    pc.put([1, 2, 3, 4], b)
    pc._by_hash[cumulative_hashes([1, 2, 3])[3]].last_used -= 120
    assert pc.expire() == 1 and a.released and not b.released
    assert len(pc) == 1 and pc.nbytes == 10 and pc.stats.expirations == 1


def test_lowering_the_budget_at_runtime_evicts_at_once():
    pc = PrefixCache(max_entries=8, max_bytes=1 << 30)
    snaps = [_Snap(100) for _ in range(4)]
    for i, s in enumerate(snaps):
        pc.put(list(range(i + 3)), s)
    pc.set_limits(max_bytes=250)
    assert pc.nbytes <= 250 and sum(s.released for s in snaps) == 2


def test_zero_budget_disables_caching_without_leaking():
    pc = PrefixCache(max_entries=8, max_bytes=0)
    s = _Snap(100)
    pc.put([1, 2, 3], s)
    assert len(pc) == 0 and s.released
