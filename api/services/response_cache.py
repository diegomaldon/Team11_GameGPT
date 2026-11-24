"""ResponseCache: repeated recommend queries served from memory (TM11-73, REQ040).

A recommend call embeds, searches twice, checks ownership and waits on the LLM,
which is most of REQ040's 10 second budget. The same player asking the same
thing again usually gets the same answer, so it's kept here and served without
any of that work.

The key is (user, query, library fingerprint):

  query        whitespace collapsed and case folded, so "Cozy  games" and
               "cozy games" share an entry
  fingerprint  DeduplicationService.library_fingerprint: a hash of every row
               in the user's owned_games. Importing, syncing, adding or
               removing a game, or unlinking a platform changes it, so an
               answer computed against the old library is never served. No
               invalidation hook is needed in the import paths.

Entries also expire after CACHE_TTL_SECONDS, which bounds how stale an answer
can get when the catalogue or the model changes, and the least recently used
entry is dropped past CACHE_MAX_ENTRIES. A `ranking_degraded` outcome (TM11-72)
is never stored: the next try should get a real ranking. The cache is per
process; the API runs as one process on Render. Two identical requests that
arrive together both miss and both run the pipeline: there is no in-flight
de-duplication, so a double-click costs two LLM calls, not one.

Every lookup is logged as `recommend.cache` with whether it hit and the
running hit rate, never the query text.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Generic, Hashable, TypeVar
from uuid import UUID

log = logging.getLogger("gamegpt.cache")

CACHE_TTL_SECONDS = 600.0
CACHE_MAX_ENTRIES = 256
# Outcomes with one of these notice codes are transient and never cached.
UNCACHEABLE_NOTICES = frozenset({"ranking_degraded"})

V = TypeVar("V")


def normalise_query(query: str) -> str:
    return " ".join(query.split()).casefold()


def cache_key(user_id: UUID, query: str, library_fingerprint: str) -> tuple[str, str, str]:
    return (str(user_id), normalise_query(query), library_fingerprint)


@dataclass(frozen=True)
class CacheStats:
    lookups: int
    hits: int
    entries: int

    @property
    def hit_rate(self) -> float:
        return round(self.hits / self.lookups, 3) if self.lookups else 0.0


class ResponseCache(Generic[V]):
    """An LRU of values with a time to live. Not thread-safe; asyncio only."""

    def __init__(
        self,
        *,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        max_entries: int = CACHE_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0 or max_entries < 1:
            raise ValueError("ttl_seconds must be positive and max_entries at least 1")
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._entries: OrderedDict[Hashable, tuple[float, V]] = OrderedDict()
        self._lookups = 0
        self._hits = 0

    def get(self, key: Hashable) -> V | None:
        """The value for `key` if present and fresh, counting the lookup."""
        self._lookups += 1
        entry = self._entries.get(key)
        if entry is not None and self._clock() - entry[0] < self._ttl:
            self._entries.move_to_end(key)
            self._hits += 1
            return entry[1]
        if entry is not None:
            del self._entries[key]  # expired
        return None

    def put(self, key: Hashable, value: V) -> None:
        self._entries[key] = (self._clock(), value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()
        self._lookups = self._hits = 0

    def stats(self) -> CacheStats:
        return CacheStats(lookups=self._lookups, hits=self._hits, entries=len(self._entries))


def log_lookup(cache: ResponseCache, *, hit: bool, lookup_ms: float | None,
               cached: bool | None = None) -> None:
    """One `recommend.cache` line per recommend call, with the running hit rate.

    `lookup_ms` is the library fingerprint read; None when the cache was skipped.
    `cached` says whether a miss's result was stored.
    """
    s = cache.stats()
    log.info(
        "recommend.cache",
        extra={
            "cache_hit": hit,
            "cache_stored": cached,
            "lookup_ms": None if lookup_ms is None else round(lookup_ms, 1),
            "cache_lookups": s.lookups,
            "cache_hits": s.hits,
            "cache_hit_rate": s.hit_rate,
            "cache_entries": s.entries,
        },
    )
