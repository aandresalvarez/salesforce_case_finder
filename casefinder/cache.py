"""A TTL cache that lives in process memory and nowhere else.

This is the module that makes "no PHI intentionally persisted to disk" true in
practice rather than by intention. Case bodies, comment streams, and search
snippets all pass through here, so it deliberately offers no disk backend, no
serialisation hook, and no eviction-to-file path. Quitting the app is the whole
of the data-retention policy.

It also does real work for cost: repeating a search inside the TTL window costs
nothing, and changing one filter in a list does not re-scan the warehouse for
every keystroke.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from . import config

T = TypeVar("T")


@dataclass
class _Entry:
    value: Any
    expires_at: float


class TTLCache:
    """Small thread-safe cache. NiceGUI serves requests from a thread pool, so
    two clicks in quick succession can land in here concurrently."""

    def __init__(self, default_ttl: int) -> None:
        self._default_ttl = default_ttl
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get_or_load(self, key: str, load: Callable[[], T], *, ttl: int | None = None) -> T:
        """Return the cached value for `key`, computing it if absent or stale.

        The loader runs outside the lock. Holding it across a BigQuery round
        trip would serialise every query in the app behind the slowest one; the
        cost of a rare duplicate fetch is far lower than that.
        """
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.expires_at > now:
                self.hits += 1
                return entry.value
            self.misses += 1

        value = load()

        with self._lock:
            self._entries[key] = _Entry(
                value=value,
                expires_at=time.monotonic() + (ttl if ttl is not None else self._default_ttl),
            )
        return value

    def invalidate(self, prefix: str = "") -> int:
        """Drop cached entries. Empty prefix clears everything.

        Used by Retry on the connection screen, and by an explicit refresh —
        both cases where the user is telling us the cached answer is wrong.
        """
        with self._lock:
            keys = [k for k in self._entries if k.startswith(prefix)]
            for key in keys:
                del self._entries[key]
            return len(keys)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


def key(*parts: Any) -> str:
    """Build a stable cache key from query arguments.

    Lists are sorted so that picking two statuses in either order is one cache
    entry rather than two.
    """
    out: list[str] = []
    for part in parts:
        if isinstance(part, list | tuple | set):
            out.append("[" + ",".join(sorted(str(p) for p in part)) + "]")
        elif isinstance(part, dict):
            out.append("{" + ",".join(f"{k}={v}" for k, v in sorted(part.items())) + "}")
        else:
            out.append(str(part))
    return "|".join(out)


# Results carry PHI and expire on the short window; facets are low-sensitivity
# label lists that change on the warehouse's batch schedule, not the user's.
results = TTLCache(config.CACHE_TTL_SECONDS)
facets = TTLCache(config.FACET_CACHE_TTL_SECONDS)


def clear_all() -> None:
    results.invalidate()
    facets.invalidate()
