"""The in-memory cache — findings #02, #03, #04 and #05.

Four properties, and each of them is a property of this module specifically
rather than of caching in general:

*Expiry deletes.* The application's whole data-retention policy is "quitting
the app", so an entry whose TTL has passed must actually leave memory rather
than merely stop being served. Everything that reaches `cache.results` is a
case body, a comment stream, or a search snippet.

*Memory is bounded.* A desktop window is open all day and every case opened
adds entries. Without a ceiling the process grows for as long as it runs.

*One key, one query.* Two clicks on the same case must cost one BigQuery job.

*A hit is reported as free.* The cache is invisible if the UI keeps quoting the
scan that filled it.
"""

from __future__ import annotations

import threading
import time

import pytest

from casefinder import cache


@pytest.fixture(autouse=True)
def clean_caches():
    cache.clear_all()
    yield
    cache.clear_all()


def counting(value="v"):
    """A loader that records how many times it actually ran."""
    calls: list[int] = []

    def load():
        calls.append(1)
        return value

    return load, calls


# --------------------------------------------------------------------------
# Expiry deletes rather than shadows — finding #02
# --------------------------------------------------------------------------


def test_an_expired_entry_is_removed_from_memory_not_just_refused():
    """The bug this replaces: `get_or_load` checked `expires_at` on read and
    left the stale entry in the dict forever. A body whose window closed hours
    ago was still resident, and reachable in a swap file or a crash dump."""
    store = cache.TTLCache(default_ttl=0, max_entries=10)
    store.get_or_load("phi", lambda: "a case body")
    assert len(store) == 1

    time.sleep(0.01)
    assert store.reap() == 1
    assert len(store) == 0
    assert store._entries == {}, "the value is still referenced"


def test_the_reaper_leaves_live_entries_alone():
    store = cache.TTLCache(default_ttl=60, max_entries=10)
    store.get_or_load("fresh", lambda: "keep me")
    assert store.reap() == 0
    assert store.get_or_load("fresh", lambda: "reloaded") == "keep me"


def test_reading_a_stale_key_drops_the_old_value_before_reloading():
    """Even if the reload fails, the expired value must already be gone."""
    store = cache.TTLCache(default_ttl=0, max_entries=10)
    store.get_or_load("k", lambda: "old")
    time.sleep(0.01)

    def explode():
        raise RuntimeError("warehouse unreachable")

    with pytest.raises(RuntimeError):
        store.get_or_load("k", explode)
    assert len(store) == 0


def test_a_failed_load_is_not_cached():
    """A transient failure must not be served for the rest of the TTL."""
    store = cache.TTLCache(default_ttl=60, max_entries=10)
    with pytest.raises(RuntimeError):
        store.get_or_load("k", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert store.get_or_load("k", lambda: "worked this time") == "worked this time"


def test_reap_all_sweeps_every_cache():
    cache.results.get_or_load("a", lambda: 1, ttl=0)
    cache.facets.get_or_load("b", lambda: 2, ttl=0)
    time.sleep(0.01)
    assert cache.reap_all() == 2
    assert len(cache.results) == 0
    assert len(cache.facets) == 0


def test_the_reaper_thread_starts_once_and_can_be_switched_off():
    """Started from `main`, not at import, so importing the package — which the
    window subprocess and the tests both do — spawns nothing."""
    cache.start_reaper(interval=0)
    assert cache._reaper is None, "an interval of 0 means no sweep"

    cache.start_reaper(interval=3600)
    first = cache._reaper
    assert first is not None and first.daemon
    cache.start_reaper(interval=3600)
    assert cache._reaper is first, "a second call started a second thread"


# --------------------------------------------------------------------------
# Memory is bounded — finding #02
# --------------------------------------------------------------------------


def test_entries_are_capped():
    store = cache.TTLCache(default_ttl=60, max_entries=3)
    for i in range(6):
        store.get_or_load(f"k{i}", lambda i=i: i)
    assert len(store) == 3
    assert store.evictions == 3


def test_the_least_recently_used_entry_is_the_one_that_goes():
    """Recency of *use*, not of insertion: the case someone keeps coming back
    to is the one worth keeping."""
    store = cache.TTLCache(default_ttl=60, max_entries=2)
    store.get_or_load("old", lambda: "old")
    store.get_or_load("new", lambda: "new")
    store.get_or_load("old", lambda: "reloaded")  # a hit, which refreshes it
    store.get_or_load("newest", lambda: "newest")

    reloaded, calls = counting("second time")
    assert store.get_or_load("old", reloaded) == "old", "the used entry was evicted"
    assert calls == []
    assert store.get_or_load("new", reloaded) == "second time", "the idle entry survived"


def test_the_configured_caps_are_in_force():
    from casefinder import config

    assert cache.results._max_entries == config.CACHE_MAX_ENTRIES
    assert cache.facets._max_entries == config.FACET_CACHE_MAX_ENTRIES


# --------------------------------------------------------------------------
# One key, one query — finding #05
# --------------------------------------------------------------------------


def test_concurrent_requests_for_one_key_make_one_call():
    """Two fast clicks on the same case used to be two 237 MB scans."""
    store = cache.TTLCache(default_ttl=60, max_entries=10)
    started = threading.Event()
    release = threading.Event()
    calls: list[int] = []

    def slow():
        calls.append(1)
        started.set()
        release.wait(2)
        return "rows"

    answers: list[str] = []
    threads = [
        threading.Thread(target=lambda: answers.append(store.get_or_load("k", slow)))
        for _ in range(4)
    ]
    threads[0].start()
    assert started.wait(2), "the first load never began"
    for thread in threads[1:]:
        thread.start()
    # Let the waiters reach the cache and find the load already claimed.
    time.sleep(0.05)
    release.set()
    for thread in threads:
        thread.join(2)

    assert calls == [1], "the same question was asked of BigQuery twice"
    assert answers == ["rows"] * 4
    assert store.coalesced == 3


def test_a_shared_load_shares_its_failure_too():
    store = cache.TTLCache(default_ttl=60, max_entries=10)
    started = threading.Event()
    release = threading.Event()

    def slow_failure():
        started.set()
        release.wait(2)
        raise RuntimeError("warehouse unreachable")

    errors: list[str] = []

    def wait_for_it():
        try:
            store.get_or_load("k", slow_failure)
        except RuntimeError as exc:
            errors.append(str(exc))

    first = threading.Thread(target=wait_for_it)
    first.start()
    assert started.wait(2)
    second = threading.Thread(target=wait_for_it)
    second.start()
    time.sleep(0.05)
    release.set()
    first.join(2)
    second.join(2)

    assert errors == ["warehouse unreachable"] * 2
    assert len(store) == 0
    # And the key is free again, rather than stuck claimed by a load that died.
    assert store.get_or_load("k", lambda: "recovered") == "recovered"


def test_different_keys_do_not_wait_on_each_other():
    """The loader runs outside the lock; a slow query must not stall the app."""
    store = cache.TTLCache(default_ttl=60, max_entries=10)
    release = threading.Event()
    done = threading.Event()

    slow = threading.Thread(
        target=lambda: store.get_or_load("slow", lambda: release.wait(2))
    )
    slow.start()
    time.sleep(0.05)
    threading.Thread(
        target=lambda: (store.get_or_load("fast", lambda: "quick"), done.set())
    ).start()
    assert done.wait(1), "an unrelated key waited on the slow one"
    release.set()
    slow.join(2)


# --------------------------------------------------------------------------
# Telling a hit from a load — finding #03
# --------------------------------------------------------------------------


def test_load_reports_where_the_value_came_from():
    store = cache.TTLCache(default_ttl=60, max_entries=10)
    assert store.load("k", lambda: "v") == ("v", False)
    assert store.load("k", lambda: "v") == ("v", True)


def test_a_coalesced_wait_is_not_reported_as_a_memory_hit():
    """The waiter shares a query that really did run, so its cost is real."""
    store = cache.TTLCache(default_ttl=60, max_entries=10)
    started = threading.Event()
    release = threading.Event()
    results: list[tuple[object, bool]] = []

    def slow():
        started.set()
        release.wait(2)
        return "rows"

    threading.Thread(target=lambda: store.load("k", slow)).start()
    assert started.wait(2)
    waiter = threading.Thread(target=lambda: results.append(store.load("k", slow)))
    waiter.start()
    time.sleep(0.05)
    release.set()
    waiter.join(2)
    assert results == [("rows", False)]


# --------------------------------------------------------------------------
# Invalidation and keys
# --------------------------------------------------------------------------


def test_an_invalidation_beats_a_load_that_was_already_running():
    """Pressing Refresh must not be answered with data fetched before it.

    The Lists page prefetches three queries on every draw, so a load in flight
    when the button is pressed is the ordinary case, not a rare one. Without an
    epoch the in-flight load simply refilled the cache it had just been told to
    empty, and the next caller was coalesced onto it.
    """
    store = cache.TTLCache(default_ttl=60, max_entries=10)
    started = threading.Event()
    release = threading.Event()
    answers: list[str] = []

    def slow_old_answer():
        started.set()
        release.wait(2)
        return "OLD"

    early = threading.Thread(target=lambda: answers.append(store.get_or_load("k", slow_old_answer)))
    early.start()
    assert started.wait(2)

    store.invalidate()  # the user pressed Refresh

    late, calls = counting("NEW")
    assert store.get_or_load("k", late) == "NEW", "joined the load being discarded"
    assert calls == [1]

    release.set()
    early.join(2)
    assert answers == ["OLD"], "the early caller still gets the answer it asked for"
    assert store.get_or_load("k", lambda: "unused") == "NEW", "the stale load refilled the cache"


def test_a_settled_key_is_always_released_even_if_storing_fails():
    """A caller blocked on a claim nobody resolves never comes back —
    `Future.result()` has no timeout — so the wake is in a `finally`."""
    store = cache.TTLCache(default_ttl=60, max_entries=10)

    class Exploding(dict):
        def __setitem__(self, key, value):
            raise MemoryError("no room")

    store._entries = Exploding()
    with pytest.raises(MemoryError):
        store.get_or_load("k", lambda: "v")
    # The key is free again rather than claimed by a load that died holding it.
    store._entries = cache.OrderedDict()
    assert store.get_or_load("k", lambda: "recovered") == "recovered"


def test_a_miss_is_counted_once_per_load_not_once_per_caller():
    """`misses` is the number of queries issued; `coalesced` is the number of
    callers who did not have to issue one."""
    store = cache.TTLCache(default_ttl=60, max_entries=10)
    started = threading.Event()
    release = threading.Event()

    def slow():
        started.set()
        release.wait(2)
        return "rows"

    threads = [threading.Thread(target=lambda: store.get_or_load("k", slow)) for _ in range(3)]
    threads[0].start()
    assert started.wait(2)
    for thread in threads[1:]:
        thread.start()
    time.sleep(0.05)
    release.set()
    for thread in threads:
        thread.join(2)

    assert (store.misses, store.coalesced, store.hits) == (1, 2, 0)


def test_invalidate_takes_a_prefix():
    store = cache.TTLCache(default_ttl=60, max_entries=10)
    store.get_or_load("triage|current|x", lambda: 1)
    store.get_or_load("search|current|x", lambda: 2)
    assert store.invalidate("triage") == 1
    assert len(store) == 1


def test_clear_all_empties_every_cache():
    cache.results.get_or_load("a", lambda: 1)
    cache.facets.get_or_load("b", lambda: 2)
    cache.clear_all()
    assert len(cache.results) == 0
    assert len(cache.facets) == 0


def test_a_key_does_not_depend_on_the_order_a_filter_was_picked_in():
    assert cache.key("triage", ["b", "a"]) == cache.key("triage", ["a", "b"])
    assert cache.key("triage", ["a"]) != cache.key("triage", ["a", "b"])


# --------------------------------------------------------------------------
# What the data layer does with a hit — findings #03, #04, #08
# --------------------------------------------------------------------------


def _fake_warehouse(monkeypatch, rows=(), bytes_processed=245 * 1024**2):
    """Answer every query from memory, and record the SQL that was asked for."""
    from casefinder import bq

    asked: list[str] = []

    def run(sql, params=None, *, preflight=False):
        asked.append(sql)
        return bq.QueryResult(
            rows=list(rows), bytes_processed=bytes_processed, cache_hit=False
        )

    monkeypatch.setattr(bq, "run", run)
    return asked


def test_a_cached_page_stops_quoting_a_scan_that_did_not_happen(monkeypatch):
    """Finding #03. The Page is stored whole, so re-reading it replayed
    `scanned 245 MB` at a reader who had just been handed a dictionary value —
    every revisit inside the TTL reporting money that was not spent."""
    from casefinder import data
    from casefinder.config import ERAS
    from casefinder.queries import TriageFilters

    _fake_warehouse(monkeypatch)

    def ask():
        return data.triage(
            ERAS["current"], TriageFilters(), sort="last_activity", descending=True
        )

    first = ask()
    assert first.served_from_memory is False
    assert "245 MB" in first.cost_note
    assert first.is_trivial_cost is False

    again = ask()
    assert again.served_from_memory is True
    assert "free" in again.cost_note
    assert "245 MB" not in again.cost_note
    assert again.is_trivial_cost is True, "the UI would still print a cost line"
    assert again.rows == first.rows


def test_the_stored_page_is_not_mutated_by_being_read(monkeypatch):
    """`served_from_memory` describes one request, not the shared value."""
    from casefinder import data
    from casefinder.config import ERAS
    from casefinder.queries import TriageFilters

    _fake_warehouse(monkeypatch)
    data.triage(ERAS["current"], TriageFilters(), sort="last_activity", descending=True)
    data.triage(ERAS["current"], TriageFilters(), sort="last_activity", descending=True)
    stored, _ = cache.results.load(
        next(iter(cache.results._entries)), lambda: None
    )
    assert stored.served_from_memory is False


@pytest.mark.parametrize("filter_class", ["Filters", "TriageFilters"])
def test_every_filter_field_reaches_the_key_by_construction(filter_class):
    """Finding #04. The key used to be transcribed field by field, and a
    forgotten line served one owner another owner's rows under the right title.
    Deriving it from the dataclass means a new field is in the key the moment
    it exists — so this walks the fields rather than naming them."""
    import dataclasses

    from casefinder import data, queries

    cls = getattr(queries, filter_class)
    default = cls()
    baseline = data._filters_key(default)
    for field in dataclasses.fields(cls):
        changed = dataclasses.replace(default, **{field.name: _other(field, default)})
        assert data._filters_key(changed) != baseline, (
            f"{filter_class}.{field.name} does not reach the cache key"
        )
        assert data._filters_key(changed) == data._filters_key(changed), "unstable key"


def _other(field, default):
    """Any value of the right shape that differs from the default."""
    import datetime

    current = getattr(default, field.name)
    if isinstance(current, bool):
        return not current
    if isinstance(current, list):
        return ["something"]
    return datetime.date(2020, 1, 1)


def test_reading_a_case_takes_no_ordering_argument(monkeypatch):
    """Finding #08. The flag no caller could set, sitting in the cache key
    where it would have doubled the cached copies of every conversation."""
    import inspect

    from casefinder import data, queries

    assert "newest_first" not in inspect.signature(data.comments).parameters
    assert "newest_first" not in inspect.signature(queries.comments_stream).parameters

    from casefinder.config import ERAS

    asked = _fake_warehouse(monkeypatch)
    data.comments(ERAS["current"], "CASE-1")
    data.comments(ERAS["current"], "CASE-1")
    assert len(asked) == 1, "one case, one scan of the body column"
    assert "ORDER BY t.turn_seq" in asked[0]
    assert "DESC" not in asked[0].split("ORDER BY t.turn_seq")[1]
