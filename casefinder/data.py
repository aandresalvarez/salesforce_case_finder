"""The one seam the UI is allowed to call.

Pages do not touch `queries` or `bq` directly. They call a function here, which
builds SQL from a named builder, runs it through the cache, and hands back
typed models. Spec section 4.2 puts this rule as: the UI renders data and
dispatches actions; it does not construct SQL.

Keeping it in one module also means the caching policy is visible in one place
rather than scattered across seven pages, and every result that carries PHI
goes through a cache that only exists in memory.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import Any

from . import ask, bq, cache, queries
from .config import Era
from .models import (
    Attachment,
    CaseHeader,
    Comment,
    Facets,
    Freshness,
    RelatedCase,
    SearchHit,
    TimelineEvent,
    TriageRow,
    without_repeats,
)


@dataclass(frozen=True)
class Page:
    """Rows plus what it cost to get them, so the UI can stay quiet about cost
    until there is something worth saying.

    `bytes_processed` and `cache_hit` describe the query that produced these
    rows, at the moment it ran. `served_from_memory` describes *this* request,
    and the two are not the same thing once a Page is cached: the page is
    stored whole, so re-reading it replayed "scanned 245 MB" at a reader who
    had just been handed a value out of a dictionary. Every revisit inside the
    TTL window reported a cost that was not incurred, which overstates the
    spend and makes a working cache look like it is not there.
    """

    rows: list[Any]
    bytes_processed: int
    cache_hit: bool
    total_matches: int = 0
    served_from_memory: bool = False

    @property
    def cost_note(self) -> str:
        if self.served_from_memory:
            return "already loaded this session — free"
        return bq.QueryResult(
            rows=[], bytes_processed=self.bytes_processed, cache_hit=self.cache_hit
        ).cost_note

    @property
    def is_trivial_cost(self) -> bool:
        """Under ~50 MB there is nothing useful to tell the user."""
        return (
            self.served_from_memory
            or self.cache_hit
            or self.bytes_processed < 50 * 1024**2
        )


def _run(
    key: str,
    build: Callable[[], tuple[str, Sequence[Any]]],
    model: Callable[[dict], Any] | None,
    *,
    store: cache.TTLCache = cache.results,
) -> Page:
    def load() -> Page:
        sql, params = build()
        result = bq.run(sql, params)
        rows = [model(row) for row in result.rows] if model else result.rows
        total = result.rows[0].get("total_matches", len(rows)) if result.rows else 0
        return Page(
            rows=rows,
            bytes_processed=result.bytes_processed,
            cache_hit=result.cache_hit,
            total_matches=total or len(rows),
        )

    page, from_memory = store.load(key, load)
    # Marked on the way out rather than inside `load`, because the stored Page
    # is shared by every reader of this key and only this reader knows it did
    # not pay for it.
    return replace(page, served_from_memory=True) if from_memory else page


def _filters_key(filters: Any) -> str:
    """Every field of a filter dataclass, in declaration order.

    Derived rather than listed. `triage` used to spell its seven fields out by
    hand, under a comment explaining that a dimension missing from the list is
    not a stale entry but the wrong list under the right title — two owners
    sharing one key, and the second served the first one's rows. That is a
    correctness bug the code invited and a test had to stand guard over.
    Reading the dataclass removes the opportunity: a field added to
    `TriageFilters` or `Filters` is part of the key the moment it exists.
    """
    return cache.key(*dataclasses.astuple(filters))


# --------------------------------------------------------------------------
# Connection
# --------------------------------------------------------------------------


def check_access() -> tuple[bool, str]:
    return cache.results.get_or_load("access", bq.check_access)


def clear_caches() -> None:
    """Forget everything this process has concluded and cached.

    One function rather than a list of caches at each call site, so that a new
    cache is cleared by every button that says it clears the cache. The Vertex
    probe is in here for the same reason: it caches its failure for the life of
    the process, which is right for a page asking `available()` on every render
    and wrong as a permanent verdict — a project whose API was switched on a
    minute ago should not need a restart to be noticed.
    """
    cache.clear_all()
    ask.reset()


def reset_connection() -> None:
    """Retry on the connection screen means "forget what you concluded"."""
    clear_caches()


def prefetch(*loads: Callable[[], Any]) -> None:
    """Warm the cache for several independent loads at once.

    A BigQuery round trip on this warehouse costs about a second and a half,
    and almost none of that is scanning — it is job creation and polling. The
    Lists page needs three of them before it can draw anything, so asking one
    at a time made opening the app a six-second wait for two seconds of work.

    The bytes billed are identical either way: each load still runs exactly
    once, and every one of them is a cached function, so the caller's ordinary
    sequential calls that follow are cache hits. This buys latency and nothing
    else, which is why it is safe to use liberally and pointless to use on a
    load whose result the page might not need.

    Failures are swallowed on purpose. Each caller asks for the same value
    again through the normal path a moment later, and that is where the error
    belongs — raising here would report a failed query before the page that
    needed it had been drawn, and would attribute it to the wrong screen.
    """
    if not loads:
        return
    with ThreadPoolExecutor(max_workers=len(loads), thread_name_prefix="cf-prefetch") as pool:
        futures = [pool.submit(load) for load in loads]
    for future in futures:
        with suppress(Exception):
            future.result()


# --------------------------------------------------------------------------
# Lists
# --------------------------------------------------------------------------


def freshness(era: Era, stale_days: int) -> Freshness:
    def load() -> Freshness:
        sql, params = queries.warehouse_freshness(era)
        result = bq.run(sql, params)
        row = result.rows[0] if result.rows else {}
        return Freshness.from_row(row, stale_days)

    return cache.results.get_or_load(cache.key("freshness", era.key), load)


def triage(
    era: Era,
    filters: queries.TriageFilters,
    *,
    sort: str,
    descending: bool,
    limit: int = queries.TRIAGE_LIMIT,
    offset: int = 0,
) -> Page:
    key = cache.key(
        "triage", era.key, _filters_key(filters), sort, descending, limit, offset
    )
    return _run(
        key,
        lambda: queries.triage_list(
            era, filters, sort=sort, descending=descending, limit=limit, offset=offset
        ),
        TriageRow.from_row,
    )


def facets(era: Era, *, extended: bool = False) -> Facets:
    def load() -> Facets:
        sql, params = queries.facets(era, extended=extended)
        result = bq.run(sql, params)
        return Facets.from_row(result.rows[0] if result.rows else {})

    return cache.facets.get_or_load(cache.key("facets", era.key, extended), load)


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------


def search(
    era: Era,
    terms: list[str],
    filters: queries.Filters,
    *,
    in_conversation: bool,
    in_fields: bool,
    sort: str,
    limit: int,
    offset: int = 0,
) -> Page:
    key = cache.key(
        "search",
        era.key,
        terms,
        _filters_key(filters),
        in_conversation,
        in_fields,
        sort,
        limit,
        offset,
    )
    return _run(
        key,
        lambda: queries.search(
            era,
            terms,
            filters,
            in_conversation=in_conversation,
            in_fields=in_fields,
            sort=sort,
            limit=limit,
            offset=offset,
        ),
        SearchHit.from_row,
    )


def corpus_size(era: Era) -> int:
    def load() -> int:
        sql, params = queries.corpus_size(era)
        result = bq.run(sql, params)
        return int(result.rows[0]["n"]) if result.rows else 0

    return cache.facets.get_or_load(cache.key("corpus", era.key), load)


# --------------------------------------------------------------------------
# One case
# --------------------------------------------------------------------------


def case_header(era: Era, case_number: str) -> CaseHeader | None:
    page = _run(
        cache.key("header", era.key, case_number),
        lambda: queries.case_header(era, case_number),
        CaseHeader.from_row,
    )
    return page.rows[0] if page.rows else None


def comments(era: Era, case_number: str) -> list[Comment]:
    """The conversation, oldest first. Always.

    Reading order is a presentation choice and belongs to the page, which
    reverses the list it already has rather than asking the warehouse to sort
    the same rows the other way for another body-column scan. This used to take
    a `newest_first` flag that no caller could set, sitting in the cache key
    where it would have doubled the cached copies of every case.
    """
    page = _run(
        cache.key("comments", era.key, case_number),
        lambda: queries.comments_stream(era, case_number),
        Comment.from_row,
    )
    return without_repeats(page.rows)


def timeline(era: Era, case_number: str) -> list[TimelineEvent]:
    page = _run(
        cache.key("timeline", era.key, case_number),
        lambda: queries.case_timeline(era, case_number),
        TimelineEvent.from_row,
    )
    return page.rows


def attachments(era: Era, case_number: str) -> list[Attachment]:
    if not era.has_attachments:
        return []
    page = _run(
        cache.key("attachments", era.key, case_number),
        lambda: queries.case_attachments(era, case_number),
        Attachment.from_row,
    )
    return page.rows


def related(era: Era, case_number: str) -> list[RelatedCase]:
    page = _run(
        cache.key("related", era.key, case_number),
        lambda: queries.related_cases(era, case_number),
        RelatedCase.from_row,
    )
    return page.rows


# --------------------------------------------------------------------------
# Free-form SQL (user- or model-written)
# --------------------------------------------------------------------------


def run_sql(sql: str) -> bq.QueryResult:
    """Execute query text the app did not write.

    Guarded three times over: `assert_read_only` refuses the obvious without a
    round trip, the dry run inside `preflight` asks BigQuery's own parser
    whether this is a query at all, and the same dry run refuses an expensive
    mistake before it is billed rather than after. Deliberately uncached — the
    user pressing Run means run it.
    """
    bq.assert_read_only(sql)
    return bq.run(sql, preflight=True)


def estimate_sql(sql: str) -> int:
    """Bytes the query would scan, refusing a non-query on the same round trip."""
    bq.assert_read_only(sql)
    return bq.plan(sql).bytes_processed
