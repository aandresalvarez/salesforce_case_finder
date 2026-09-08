"""A TTL cache that lives in process memory and nowhere else.

This is the module that makes "no PHI intentionally persisted to disk" true in
practice rather than by intention. Case bodies, comment streams, and search
snippets all pass through here, so it deliberately offers no disk backend, no
serialisation hook, and no eviction-to-file path. Quitting the app is the whole
of the data-retention policy.

It also does real work for cost: repeating a search inside the TTL window costs
nothing, and changing one filter in a list does not re-scan the warehouse for
every keystroke.

Three properties are enforced here rather than left to callers:

*Expiry deletes.* An entry past its TTL is removed, by the reaper on a timer as
well as on the next read of its key. It used to be only shadowed — checked on
read and otherwise left in the dict forever — so a case body whose window had
closed hours earlier was still resident, and reachable in a swap file or a
crash dump. For an application whose retention policy is the process lifetime,
"will not be served" and "has been deleted" are different promises, and this
module is where the second one is kept.

*Memory is bounded.* Entries are capped and evicted least-recently-used first,
so a long day of opening cases cannot grow the process without limit. The cap
counts entries rather than bytes: measuring a Python object graph is both
expensive and unreliable, and a predictable ceiling that is occasionally
generous beats an accurate one nobody can reason about.

*One key, one query.* A load in flight is shared, so two clicks on the same
case, or a prefetch racing the page that follows it, cost one BigQuery job
rather than two — without letting an invalidation be undone by a query that
was already running when it happened. See `_epoch`.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, TypeVar

from . import config

T = TypeVar("T")


@dataclass
class _Entry:
    value: Any
    expires_at: float


@dataclass
class _Claim:
    """One thread's claim on a key while it loads the value for it.

    `epoch` is what the claim was made in, so a load that an invalidation
    overtook can be told from one that is still current.
    """

    epoch: int
    future: Future = field(default_factory=Future)


class TTLCache:
    """Small thread-safe cache. NiceGUI serves requests from a thread pool, so
    two clicks in quick succession can land in here concurrently."""

    def __init__(self, default_ttl: int, *, max_entries: int) -> None:
        self._default_ttl = default_ttl
        self._max_entries = max(1, max_entries)
        # Ordered by recency of use, so eviction has a least-recently-used end
        # to take from without a second structure to keep in step.
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        # Keys with a load already running, and the claim its result will
        # arrive on. Separate from `_entries` because an in-flight load has no
        # value yet and must not be mistaken for a miss.
        self._loading: dict[str, _Claim] = {}
        # Bumped by every invalidation. A load carries the epoch it began in,
        # and a load from an earlier epoch neither stores its result nor is
        # joined by a new caller — because the user pressing Refresh means the
        # answer already in flight is one of the answers they are discarding.
        # Without this, "Reloaded from BigQuery" could be answered with data
        # fetched before the button was pressed: `lists._warm` prefetches three
        # queries on every draw, so a load in flight is the ordinary case.
        self._epoch = 0
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.coalesced = 0
        self.evictions = 0
        self.reaped = 0

    def get_or_load(self, key: str, load: Callable[[], T], *, ttl: int | None = None) -> T:
        """Return the cached value for `key`, computing it if absent or stale."""
        return self.load(key, load, ttl=ttl)[0]

    def load(
        self, key: str, load: Callable[[], T], *, ttl: int | None = None
    ) -> tuple[T, bool]:
        """The value, and whether it came from memory rather than from `load`.

        Callers that report cost to the user need the second half: replaying
        the bytes a query scanned an hour ago, every time its cached answer is
        shown again, tells the user they are spending money they are not.

        The loader runs outside the lock. Holding it across a BigQuery round
        trip would serialise every query in the app behind the slowest one.
        What the lock does hold is the *claim* on the key, so a second caller
        that arrives mid-load waits for the first one's answer instead of
        starting an identical job — the cost of a duplicate fetch was never
        worth paying, only worth not paying for with a stalled UI.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                if entry.expires_at > time.monotonic():
                    self._entries.move_to_end(key)
                    self.hits += 1
                    return entry.value, True
                # Stale. Delete it now rather than leaving it to be overwritten:
                # if this load fails, the value should already be gone.
                del self._entries[key]
            running = self._loading.get(key)
            if running is not None and running.epoch == self._epoch:
                self.coalesced += 1
            else:
                # No load running, or one that began before an invalidation and
                # whose answer is therefore already discarded. Either way this
                # caller starts its own, and replaces the claim so that anyone
                # arriving after it joins the new load rather than the old one.
                running = None
                self.misses += 1
                claim = _Claim(epoch=self._epoch)
                self._loading[key] = claim

        if running is not None:
            # Someone else is already asking this exact question. Their answer
            # is ours, and their failure is ours too.
            return running.future.result(), False

        try:
            value = load()
        except BaseException as exc:
            self._settle(key, claim, exception=exc)
            raise
        self._settle(
            key, claim, value=value, ttl=ttl if ttl is not None else self._default_ttl
        )
        return value, False

    def _settle(
        self,
        key: str,
        claim: _Claim,
        *,
        value: Any = None,
        exception: BaseException | None = None,
        ttl: int = 0,
    ) -> None:
        """Store the result, release the key, and wake anyone waiting on it.

        Releasing and waking are in a `finally` because both have to happen
        whatever storing did. A caller left blocked on a claim nobody resolves
        never comes back — `Future.result()` has no timeout — and a claim left
        in place after a failed store is answered from a resolved future
        forever, so the key would never reload.
        """
        try:
            with self._lock:
                # Only a load from the current epoch may store its value. An
                # older one still answers its own callers — its rows were real
                # when it asked — but it does not refill a cache that has since
                # been told to forget.
                if exception is None and claim.epoch == self._epoch:
                    self._entries[key] = _Entry(
                        value=value, expires_at=time.monotonic() + ttl
                    )
                    self._entries.move_to_end(key)
                    self._evict()
        finally:
            with self._lock:
                # Identity, not equality: a newer claim may already have taken
                # the key, and popping it would strand that load's waiters.
                if self._loading.get(key) is claim:
                    del self._loading[key]
            if exception is not None:
                claim.future.set_exception(exception)
            else:
                claim.future.set_result(value)

    def reap(self) -> int:
        """Delete every expired entry. Returns how many went.

        Called on a timer as well as opportunistically, because an idle app is
        exactly the case where nothing else would ever remove them.
        """
        now = time.monotonic()
        with self._lock:
            dead = [key for key, entry in self._entries.items() if entry.expires_at <= now]
            for key in dead:
                del self._entries[key]
            self.reaped += len(dead)
        return len(dead)

    def invalidate(self, prefix: str = "") -> int:
        """Drop cached entries. Empty prefix clears everything.

        Used by Retry on the connection screen, and by an explicit refresh —
        both cases where the user is telling us the cached answer is wrong.
        """
        with self._lock:
            # Before the entries, and unconditionally: a load already in flight
            # for a matching key must not be allowed to store the answer it is
            # about to return, and a caller arriving next must not join it.
            self._epoch += 1
            keys = [k for k in self._entries if k.startswith(prefix)]
            for key in keys:
                del self._entries[key]
            return len(keys)

    def _evict(self) -> None:
        """Drop least-recently-used entries until the cap is met. Lock held."""
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
            self.evictions += 1

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
results = TTLCache(config.CACHE_TTL_SECONDS, max_entries=config.CACHE_MAX_ENTRIES)
facets = TTLCache(config.FACET_CACHE_TTL_SECONDS, max_entries=config.FACET_CACHE_MAX_ENTRIES)

_CACHES = (results, facets)


def clear_all() -> None:
    for cache in _CACHES:
        cache.invalidate()


def reap_all() -> int:
    return sum(cache.reap() for cache in _CACHES)


_reaper: threading.Thread | None = None
_reaper_lock = threading.Lock()


def start_reaper(interval: int | None = None) -> None:
    """Begin deleting expired entries on a timer, once per process.

    Started explicitly from `main` rather than at import, so that importing the
    package does not silently spawn a thread — which matters for the tests, and
    for anything that reaches for `casefinder.config` without running the app.
    The native window is a second process that does run `main`, and so does get
    a reaper of its own; it sweeps a cache that is always empty, because the
    window process never queries the warehouse.

    A daemon thread rather than a NiceGUI timer, because it has to keep running
    while nothing is on screen — an idle window is the whole case it exists
    for.
    """
    global _reaper
    seconds = interval if interval is not None else config.CACHE_REAP_SECONDS
    if seconds <= 0:
        return
    with _reaper_lock:
        if _reaper is not None and _reaper.is_alive():
            return

        def sweep() -> None:
            while True:
                time.sleep(seconds)
                reap_all()

        _reaper = threading.Thread(target=sweep, name="cf-cache-reaper", daemon=True)
        _reaper.start()
