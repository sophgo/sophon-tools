"""Device-side KV snapshot pool.

The point of these tests: snapshots must consume NPU memory, not the ~2.5 GiB of
system RAM the board exposes to Linux, and a cache eviction must give that NPU
memory back rather than leaking one slot per eviction.
"""

from pathlib import Path

import pytest

from . import fake_sail


class FakeSession:
    """Minimal session exposing the store's expected surface."""

    def __init__(self, n_tokens: int = 4, n_tensors: int = 4, per_token: int = 100):
        self._n = n_tokens
        self._per_token = per_token
        self.tensors = [fake_sail.Tensor(None, [1, 1, per_token, 64], "bf16")
                        for _ in range(n_tensors)]

    def kv_tensors(self):
        return self.tensors

    def snapshot_plan(self, token_len):
        return [(t, i, token_len) for i, t in enumerate(self.tensors)]


def test_device_store_allocates_and_copies():
    from app.engine.kv_pool import DeviceSnapshotStore

    store = DeviceSnapshotStore(backend=None, budget=10 * 1024 * 1024)
    fake_sail.Tensor  # ensure module imported
    sess = FakeSession()
    # clone_tensor_prefix is the one backend hook the store needs.
    class Be:
        def clone_tensor_prefix(self, src, token_len):
            shape = list(src.shape)
            shape[-1] = token_len
            return fake_sail.Tensor(None, shape, src.dtype)

    store.backend = Be()
    snap = store.capture(sess, 4)
    assert snap is not None
    assert snap.token_len == 4
    assert snap.nbytes > 0
    assert store.used == snap.nbytes
    # The copy is recorded on the destination (that is how sync_d2d works).
    for dst in snap.tensors:
        assert dst.synced, "capture must copy device-to-device into the new slot"


def test_device_store_sizes_to_the_prefix_not_the_context():
    """Storing 4 tokens must not allocate room for the whole 64-token context."""
    from app.engine.kv_pool import DeviceSnapshotStore

    class Be:
        def clone_tensor_prefix(self, src, token_len):
            shape = list(src.shape)
            shape[-1] = token_len
            return fake_sail.Tensor(None, shape, src.dtype)

    store = DeviceSnapshotStore(backend=Be(), budget=10 * 1024 * 1024)
    sess = FakeSession(n_tokens=4, n_tensors=2, per_token=1)
    snap = store.capture(sess, 4)
    for t in snap.tensors:
        assert t.shape[-1] == 4, f"allocated {t.shape[-1]} slots for a 4-token prefix"


def test_device_store_respects_budget_and_returns_none():
    from app.engine.kv_pool import DeviceSnapshotStore

    class Be:
        def clone_tensor_prefix(self, src, token_len):
            shape = list(src.shape)
            shape[-1] = token_len
            return fake_sail.Tensor(None, shape, src.dtype)

    # 4 tensors x 4 tokens x 2 bytes = 32 bytes; budget 16 cannot fit it.
    store = DeviceSnapshotStore(backend=Be(), budget=16)
    assert store.capture(FakeSession(), 4) is None


def test_device_store_falls_back_on_allocation_failure():
    from app.engine.kv_pool import DeviceSnapshotStore

    class Be:
        def clone_tensor_prefix(self, src, token_len):
            raise MemoryError("NPU heap exhausted")

    store = DeviceSnapshotStore(backend=Be(), budget=10 * 1024 * 1024)
    assert store.capture(FakeSession(), 4) is None
    assert store.failures == 1
    assert store.used == 0, "a failed capture must not consume budget"


def test_release_returns_budget():
    from app.engine.kv_pool import DeviceSnapshotStore

    class Be:
        def clone_tensor_prefix(self, src, token_len):
            shape = list(src.shape)
            shape[-1] = token_len
            return fake_sail.Tensor(None, shape, src.dtype)

    store = DeviceSnapshotStore(backend=Be(), budget=10 * 1024 * 1024)
    sess = FakeSession()
    snap = store.capture(sess, 4)
    used = store.used
    assert used > 0
    store.release(snap)
    assert store.used == 0, "evicted snapshots must give their NPU memory back"


def test_tiered_store_prefers_device_then_host():
    from app.engine.kv_pool import (
        DeviceSnapshotStore,
        HostSnapshotStore,
        TieredSnapshotStore,
    )

    class Be:
        def clone_tensor_prefix(self, src, token_len):
            shape = list(src.shape)
            shape[-1] = token_len
            return fake_sail.Tensor(None, shape, src.dtype)

    device = DeviceSnapshotStore(backend=Be(), budget=10 * 1024 * 1024)
    host = HostSnapshotStore(budget=10 * 1024 * 1024)
    tiered = TieredSnapshotStore(device, host)

    snap1 = tiered.capture(FakeSession(), 4)
    assert snap1.__class__.__name__ == "DeviceSnapshot"

    # Exhaust the device budget; the next capture must go to host, not fail.
    device.used = device.budget
    snap2 = tiered.capture(FakeSession(), 4)
    assert snap2.__class__.__name__ == "HostSnapshot"
    assert snap2.token_len == 4


def test_host_store_counts_bytes():
    from app.engine.kv_pool import HostSnapshotStore

    store = HostSnapshotStore(budget=10 * 1024 * 1024)
    snap = store.capture(FakeSession(), 4)
    assert snap.nbytes > 0
    assert store.used == snap.nbytes
    store.release(snap)
    assert store.used == 0


def test_cache_eviction_releases_to_the_store():
    """A cache that evicts without releasing leaks NPU memory one slot at a time."""
    from app.engine.kv_pool import DeviceSnapshotStore, HostSnapshotStore
    from app.engine.prefix_cache import PrefixCache

    store = HostSnapshotStore(budget=10 ** 9)
    cache = PrefixCache(max_entries=2, store=store)
    cache.put([1, 2, 3], store.capture(FakeSession(), 3))
    cache.put([4, 5, 6], store.capture(FakeSession(), 3))
    before = store.used
    assert before > 0
    cache.put([7, 8, 9], store.capture(FakeSession(), 3))   # forces one eviction
    assert cache.stats.evictions == 1
    assert store.used < before + 3 * 4 * 100, "evicted slot was not released"


def test_cache_budget_comes_from_the_store():
    """When KV lives in NPU memory, the host-RAM heuristic is the wrong budget."""
    from app.engine.kv_pool import HostSnapshotStore
    from app.engine.prefix_cache import PrefixCache

    store = HostSnapshotStore(budget=12345)
    cache = PrefixCache(store=store)
    assert cache.max_bytes == 12345


def test_cache_clear_releases_everything():
    from app.engine.kv_pool import HostSnapshotStore
    from app.engine.prefix_cache import PrefixCache

    store = HostSnapshotStore(budget=10 ** 9)
    cache = PrefixCache(store=store)
    for i in range(3):
        cache.put([i, i + 1, i + 2], store.capture(FakeSession(), 3))
    assert store.used > 0
    cache.clear()
    assert store.used == 0


def test_the_device_store_no_longer_imposes_its_own_ceiling():
    """MYS-2785: the cache ceiling is the model's budget, not a second number.

    The store used to default to 1 GiB, which was *the same* ceiling the removed
    global setting fed into ``PrefixCache.max_bytes``. With the cache now sized
    by the model's runtime budget, a store default would be a second, invisible
    limit: a snapshot the scheduler had just evicted entries to make room for
    would be refused by the store, and the cache would stop growing below the
    budget the operator can see.
    """
    from app.engine.kv_pool import UNBOUNDED, DeviceSnapshotStore

    assert DeviceSnapshotStore(backend=None).budget == UNBOUNDED
    # A caller that *does* want the old behaviour still gets it by saying so --
    # that is the path ``test_device_store_respects_budget_and_returns_none``
    # above exercises.
    assert DeviceSnapshotStore(backend=None, budget=1234).budget == 1234
