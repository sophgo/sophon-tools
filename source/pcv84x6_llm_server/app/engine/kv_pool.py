"""Where prefix-cache KV snapshots live.

Two stores, same contract:

* :class:`HostSnapshotStore` -- copy KV into host numpy arrays. Simple, but each
  snapshot costs system RAM, and CV84X6 exposes only ~2.5 GiB to Linux (the rest
  of the 31 GiB is NPU heap). That is the wrong budget to spend on a cache.
* :class:`DeviceSnapshotStore` -- copy KV into *NPU* memory with device-to-device
  transfers. Costs the 23.75 GiB heap instead, and restoring is D2D rather than
  a host round trip.

The device store is budgeted and fails soft: if an allocation does not fit it
returns ``None`` and the caller falls back to the host store, so a cache miss
never turns into a failed request.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: The device store's old default budget. No longer used by the service (the
#: cache ceiling is the model's runtime budget now -- see ``UNBOUNDED``), kept
#: because it is the value ``tests/test_kv_pool.py`` exercises the budgeted path
#: with and an out-of-tree caller may still import it.
DEFAULT_DEVICE_BUDGET = 1024 * 1024 * 1024  # 1 GiB of the NPU heap
DEFAULT_HOST_BUDGET = 128 * 1024 * 1024     # 128 MiB of system RAM

#: Budget for a store that only *tracks* its usage and leaves the deciding to
#: somebody else. ``PrefixCache.max_bytes`` never exceeds the scheduler's runtime
#: budget (``limit - static``), so a store-level ceiling is either dead code or,
#: worse, a second limit that disagrees with the enforced one. The native store
#: already works this way -- history snapshots are allocated by the engine and
#: measured afterwards -- and this constant lets the sail device store say the
#: same thing instead of carrying the old 1 GiB figure (MYS-2785).
UNBOUNDED = 1 << 62


@dataclass
class DeviceSnapshot:
    """KV held in NPU memory, sized to the tokens it actually covers.

    Sizing to the snapshot length rather than the full context matters: the 35B
    model needs ~40 KiB per token per K/V plane set, so a full 2048-token
    context would waste ~84 MiB per cache slot to store perhaps 300 tokens.
    """

    token_len: int
    nbytes: int
    tensors: list


@dataclass
class HostSnapshot:
    token_len: int
    nbytes: int
    arrays: list


class HostSnapshotStore:
    """Snapshot KV into host memory."""

    kind = "host"

    def __init__(self, budget: int = DEFAULT_HOST_BUDGET) -> None:
        self.budget = budget
        self.used = 0

    @property
    def full(self) -> bool:
        return self.used >= self.budget

    def capture(self, session, token_len: int):
        arrays = []
        for t in session.kv_tensors():
            fn = getattr(t, "asnumpy", None)
            arrays.append(fn() if fn is not None else t)
        nbytes = sum(getattr(a, "nbytes", 0) for a in arrays)
        self.used += nbytes
        return HostSnapshot(token_len=token_len, nbytes=nbytes, arrays=arrays)

    def apply(self, session, snap: HostSnapshot) -> None:
        tensors = session.kv_tensors()
        for t, arr in zip(tensors, snap.arrays):
            t.update_data(arr)

    def release(self, snap) -> None:
        self.used = max(0, self.used - getattr(snap, "nbytes", 0))

    def stats(self) -> dict:
        return {"kind": self.kind, "used_bytes": self.used, "budget_bytes": self.budget}


class DeviceSnapshotStore:
    """Snapshot KV into NPU memory via device-to-device copies.

    The ``budget`` is a *safety net*, not the policy: it used to be the 1 GiB
    default or the service-wide cache setting, and it was the reason a model
    could keep caching after its own memory limit said stop (MYS-2785). The
    enforced ceiling is ``PrefixCache.max_bytes``, which the worker sets to the
    scheduler's runtime budget, so a store handed that number and then checked
    against it again only ever sees ``used == budget`` -- it refuses the very
    snapshot the cache just made room for. Default is therefore ``UNBOUNDED``;
    ``tests/test_kv_pool.py`` still covers the budgeted behaviour for callers
    that do pass one.
    """

    kind = "device"

    def __init__(self, backend, budget: int = UNBOUNDED) -> None:
        self.backend = backend
        self.budget = budget
        self.used = 0
        self.allocations = 0
        self.failures = 0

    @property
    def full(self) -> bool:
        return self.used >= self.budget

    def capture(self, session, token_len: int):
        """Allocate NPU slots and copy the first ``token_len`` tokens into them.

        Returns ``None`` when the budget is exhausted or the device refuses the
        allocation; the caller then falls back to host memory.
        """
        if self.full:
            return None
        plan = session.snapshot_plan(token_len)
        # Plan counts are *elements*; the budget is in bytes. Comparing one to
        # the other silently lets a snapshot overrun the budget by the dtype
        # width (2x for bf16), which is exactly how an OOM slips through.
        est = sum(n * self._element_size(src) for (src, _idx, n) in plan)
        if self.used + est > self.budget:
            return None
        try:
            tensors = []
            for src, _idx, _n in plan:
                tensors.append(self.backend.clone_tensor_prefix(src, token_len))
            for (src, _idx, n), dst in zip(plan, tensors):
                dst.sync_d2d(src, 0, 0, n)
        except Exception as exc:  # device OOM, driver refusal, ...
            self.failures += 1
            logger.warning("device KV snapshot failed, falling back to host: %s", exc)
            return None
        self.used += est
        self.allocations += 1
        return DeviceSnapshot(token_len=token_len, nbytes=est, tensors=tensors)

    @staticmethod
    def _element_size(tensor) -> int:
        """Bytes per element of a KV tensor."""
        dtype = getattr(tensor, "dtype", "bf16")
        # bf16/fp16 are 2 bytes, fp32/int32 are 4. Match sail's dtype enum names
        # and tolerate plain strings so tests need no fake enum.
        name = str(dtype).upper()
        if "FLOAT32" in name or "INT32" in name or name in ("F32", "I32"):
            return 4
        return 2

    def apply(self, session, snap: DeviceSnapshot) -> None:
        plan = session.snapshot_plan(snap.token_len)
        for (dst, _idx, n), src in zip(plan, snap.tensors):
            dst.sync_d2d(src, 0, 0, n)

    def release(self, snap) -> None:
        self.used = max(0, self.used - getattr(snap, "nbytes", 0))
        # Dropping the references frees the NPU tensors; there is no explicit
        # free in the sail API.
        if isinstance(snap, DeviceSnapshot):
            snap.tensors.clear()

    def stats(self) -> dict:
        return {
            "kind": self.kind,
            "used_bytes": self.used,
            "budget_bytes": self.budget,
            "allocations": self.allocations,
            "failures": self.failures,
        }


class TieredSnapshotStore:
    """Prefer NPU memory; fall back to host when the device budget is spent.

    This is the default. It keeps snapshots off system RAM while still degrading
    gracefully on a board that already has the full 35B model resident.
    """

    kind = "tiered"

    def __init__(self, device: DeviceSnapshotStore, host: HostSnapshotStore) -> None:
        self.device = device
        self.host = host

    @property
    def budget(self) -> int:
        return self.device.budget + self.host.budget

    def capture(self, session, token_len: int):
        snap = self.device.capture(session, token_len)
        if snap is not None:
            return snap
        return self.host.capture(session, token_len)

    def apply(self, session, snap) -> None:
        store = self.device if isinstance(snap, DeviceSnapshot) else self.host
        store.apply(session, snap)

    def release(self, snap) -> None:
        store = self.device if isinstance(snap, DeviceSnapshot) else self.host
        store.release(snap)

    def stats(self) -> dict:
        return {
            "kind": self.kind,
            "device": self.device.stats(),
            "host_used_bytes": self.host.used,
            "host_budget_bytes": self.host.budget,
        }
