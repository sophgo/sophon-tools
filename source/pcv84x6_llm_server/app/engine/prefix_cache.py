"""Prefix KV cache.

Why this exists: prefill costs ~160-200 token/s on CV84X6, so a 1900-token
prompt spends ~9.7 s before the first output token. Agent workloads resend a
long, identical system prompt every turn; caching the KV of that prefix turns
those 9.7 s into ~0.4 s.

Design notes:

* Keys are *cumulative hashes* of the token prefix, so lookup is O(L) hash
  comparisons rather than O(L^2) slice hashing.
* ``put`` stores the state at the full prompt boundary; ``lookup`` returns the
  longest cached prefix that is a prefix of the incoming prompt.
* Eviction is LRU over a byte budget. A cache that never evicts would grow
  until the NPU heap is gone, which presents as an inference failure far away
  from the cause.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Sequence

from .base import Token

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    length: int
    snapshot: object
    last_used: float
    nbytes: int = 0
    hits: int = 0


@dataclass
class CacheStats:
    lookups: int = 0
    hits: int = 0
    tokens_reused: int = 0
    tokens_prompted: int = 0
    evictions: int = 0
    expirations: int = 0

    @property
    def hit_rate(self) -> float:
        """Fraction of prompt tokens served from cache.

        Token-weighted rather than request-weighted on purpose: it is the number
        that actually predicts how much prefill time was saved.
        """
        total = self.tokens_reused + self.tokens_prompted
        return (self.tokens_reused / total) if total else 0.0


_SEED = b"\x00" * 32


def cumulative_hashes(tokens: Sequence[Token]) -> list[bytes]:
    """h[i] = hash of tokens[:i]. h[0] is the empty prefix."""
    out = [_SEED]
    h = _SEED
    for t in tokens:
        h = hashlib.sha256(h + t.to_bytes(4, "little", signed=True)).digest()
        out.append(h)
    return out


def default_max_bytes() -> int:
    """Size the cache from what the box actually has.

    Snapshots live in *host* memory (the KV is copied out of the NPU heap), and
    CV84X6 exposes only ~2.5 GiB to Linux -- the rest belongs to the NPU. A
    fixed 512 MiB budget would be a fifth of system RAM there and could take the
    service down under load, so scale to the machine and stay well clear.
    """
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) * 1024
                    # Cap at 1/8 of available and never above 512 MiB.
                    return min(512 * 1024 * 1024, avail // 8)
    except (OSError, ValueError, IndexError):
        pass
    return 64 * 1024 * 1024


class PrefixCache:
    def __init__(self, max_entries: int = 32, max_bytes: int | None = None,
                 store=None, ttl_s: float = 0.0) -> None:
        self.max_entries = max_entries
        # Entries unused for longer than this are dropped (0 = never): a
        # snapshot pins NPU memory, so one nobody has reused for hours is cost
        # without benefit.
        self.ttl_s = ttl_s
        # When the snapshots live in NPU memory the host-RAM heuristic is the
        # wrong budget entirely, so take it from the store that owns them.
        #
        # That store figure is a *placement* budget, not the enforced ceiling:
        # the worker replaces ``max_bytes`` with the model's runtime budget as
        # soon as it has one (``worker.configure`` / ``apply_mem_limit``, MYS-2785).
        # Until then it only has to be generous enough not to refuse a snapshot
        # the scheduler will authorise anyway.
        if max_bytes is None and store is not None:
            max_bytes = store.budget
        self.max_bytes = default_max_bytes() if max_bytes is None else max_bytes
        self.store = store
        self._by_hash: dict[bytes, CacheEntry] = {}
        self._bytes = 0
        self.stats = CacheStats()

    # -- accounting -----------------------------------------------------
    def _entry_bytes(self, entry: CacheEntry) -> int:
        # Prefer the store's real measurement; fall back to a token-length
        # estimate only for stores that cannot report it.
        if entry.nbytes:
            return entry.nbytes
        return entry.length * 4096

    def __len__(self) -> int:
        return len(self._by_hash)

    @property
    def nbytes(self) -> int:
        return self._bytes

    # -- core -----------------------------------------------------------
    def set_limits(self, max_entries: int | None = None, max_bytes: int | None = None,
                   ttl_s: float | None = None) -> None:
        """Change limits at runtime (console settings); evicts to fit at once."""
        if max_entries is not None:
            self.max_entries = max(1, int(max_entries))
        if max_bytes is not None:
            self.max_bytes = max(0, int(max_bytes))
        if ttl_s is not None:
            self.ttl_s = max(0.0, float(ttl_s))
        self.expire()
        self._evict()

    def expire(self, now: float | None = None) -> int:
        """Drop entries idle for longer than ttl_s. Returns how many."""
        if not self.ttl_s:
            return 0
        now = time.time() if now is None else now
        stale = [k for k, e in self._by_hash.items() if now - e.last_used > self.ttl_s]
        for k in stale:
            entry = self._by_hash.pop(k)
            self._bytes -= self._entry_bytes(entry)
            self._release(entry)
            self.stats.expirations += 1
        if stale:
            logger.info("prefix cache expired %d idle entries (ttl %.0f s)", len(stale), self.ttl_s)
        return len(stale)

    def lookup(self, tokens: Sequence[Token]) -> tuple[int, object] | None:
        """Return ``(prefix_len, snapshot)`` for the longest cached prefix."""
        self.expire()
        self.stats.lookups += 1
        if not tokens:
            return None
        hashes = cumulative_hashes(tokens)
        # Walk longest-first so the first match is the best match.
        for i in range(len(tokens), 1, -1):
            entry = self._by_hash.get(hashes[i])
            if entry is not None and entry.length == i:
                entry.last_used = time.time()
                entry.hits += 1
                self.stats.hits += 1
                self.stats.tokens_reused += i
                return i, entry.snapshot
        return None

    def has(self, tokens: Sequence[Token]) -> bool:
        """True when exactly this prefix is cached (no stats, no LRU touch)."""
        if len(tokens) < 2:
            return False
        entry = self._by_hash.get(cumulative_hashes(tokens)[len(tokens)])
        return entry is not None and entry.length == len(tokens)

    def record_prompt_tokens(self, n: int) -> None:
        """Tokens that had to be prefilled for real (unhidden by the cache)."""
        self.stats.tokens_prompted += n

    def put(self, tokens: Sequence[Token], snapshot: object) -> None:
        if len(tokens) < 2 or self.max_bytes <= 0:
            self._release(CacheEntry(length=len(tokens), snapshot=snapshot, last_used=0))
            return  # too short to be worth a slot, or caching is switched off
        hashes = cumulative_hashes(tokens)
        key = hashes[len(tokens)]
        if key in self._by_hash:
            # Same prefix again: refresh instead of duplicating.
            old = self._by_hash.pop(key)
            self._bytes -= self._entry_bytes(old)
            self._release(old)
        entry = CacheEntry(length=len(tokens), snapshot=snapshot, last_used=time.time())
        entry.nbytes = getattr(snapshot, "nbytes", 0) or entry.length * 4096
        self._by_hash[key] = entry
        self._bytes += entry.nbytes
        self._evict()

    def _evict(self) -> None:
        while self._by_hash and (
            len(self._by_hash) > self.max_entries or self._bytes > self.max_bytes
        ):
            oldest_key = min(self._by_hash, key=lambda k: self._by_hash[k].last_used)
            evicted = self._by_hash.pop(oldest_key)
            logger.info("prefix cache evicts %d-token entry (%d entries / %d MiB, caps %d / %d MiB)",
                        evicted.length, len(self._by_hash) + 1, self._bytes >> 20,
                        self.max_entries, self.max_bytes >> 20)
            self._bytes -= self._entry_bytes(evicted)
            # Hand the KV back to the store, or NPU memory leaks one slot per
            # eviction until the next model reload.
            self._release(evicted)
            self.stats.evictions += 1

    def evict_one(self, exclude: object = None) -> bool:
        """Drop the least recently used entry (never the one holding
        ``exclude``, a snapshot about to be restored). Returns False when
        there is nothing left to drop. Used when live sessions need the NPU
        memory the cache is holding."""
        keys = [k for k, e in self._by_hash.items() if e.snapshot is not exclude]
        if not keys:
            return False
        oldest_key = min(keys, key=lambda k: self._by_hash[k].last_used)
        evicted = self._by_hash.pop(oldest_key)
        logger.info("prefix cache gives up a %d-token entry (%d MiB) to live sessions",
                    evicted.length, self._entry_bytes(evicted) >> 20)
        self._bytes -= self._entry_bytes(evicted)
        self._release(evicted)
        self.stats.evictions += 1
        return True

    def _release(self, entry: CacheEntry) -> None:
        """Give the snapshot's memory back.

        Without a store (no tiered KV pool configured) the snapshot still owns
        NPU memory, so it must release itself -- otherwise every evicted entry
        leaks device memory until the model is reloaded.
        """
        snap = entry.snapshot
        released = False
        if self.store is not None:
            try:
                self.store.release(snap)
                released = True
            except Exception:
                pass
        if not released:
            try:
                rel = getattr(snap, "release", None)
                if callable(rel):
                    rel()
            except Exception:
                pass

    def clear(self) -> None:
        for entry in list(self._by_hash.values()):
            self._release(entry)
        self._by_hash.clear()
        self._bytes = 0
