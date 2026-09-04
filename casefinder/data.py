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

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from . import bq, cache, queries
from .config import Era
from .models import (
    Attachment,
    CaseHeader,
    Comment,
    Facets,
    Freshness,
    Message,
    RelatedCase,
    SearchHit,
    TimelineEvent,
    TriageRow,
)


@dataclass(frozen=True)
class Page:
    """Rows plus what it cost to get them, so the UI can stay quiet about cost
    until there is something worth saying."""

    rows: list[Any]
    bytes_processed: int
    cache_hit: bool
    total_matches: int = 0

    @property
    def cost_note(self) -> str:
        return bq.QueryResult(
            rows=[], bytes_processed=self.bytes_processed, cache_hit=self.cache_hit
        ).cost_note

    @property
    def is_trivial_cost(self) -> bool:
        """Under ~50 MB there is nothing useful to tell the user."""
        return self.cache_hit or self.bytes_processed < 50 * 1024**2


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

    return store.get_or_load(key, load)


# --------------------------------------------------------------------------
# Connection
# --------------------------------------------------------------------------


def check_access() -> tuple[bool, str]:
    return cache.results.get_or_load("access", bq.check_access)


def reset_connection() -> None:
    """Retry on the connection screen means "forget what you concluded"."""
    cache.clear_all()


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
) -> Page:
    key = cache.key(
        "triage",
        era.key,
        filters.open_only,
        filters.statuses,
        filters.departments,
        filters.pis,
        filters.irbs,
        filters.funding,
        sort,
        descending,
        limit,
    )
    return _run(
        key,
        lambda: queries.triage_list(
            era, filters, sort=sort, descending=descending, limit=limit
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
) -> Page:
    key = cache.key(
        "search",
        era.key,
        terms,
        filters.statuses,
        filters.types,
        filters.origin_classes,
        filters.date_from,
        filters.date_to,
        in_conversation,
        in_fields,
        sort,
        limit,
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


def comments(era: Era, case_number: str, *, newest_first: bool = False) -> list[Comment]:
    page = _run(
        cache.key("comments", era.key, case_number, newest_first),
        lambda: queries.comments_stream(era, case_number, newest_first=newest_first),
        Comment.from_row,
    )
    return page.rows


def messages(era: Era, case_number: str) -> list[Message]:
    page = _run(
        cache.key("messages", era.key, case_number),
        lambda: queries.case_messages(era, case_number),
        Message.from_row,
    )
    return page.rows


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

    Guarded twice over: `assert_read_only` refuses anything that is not a
    single SELECT, and `preflight` dry-runs for cost so an expensive mistake is
    refused before it is billed rather than after. Deliberately uncached — the
    user pressing Run means run it.
    """
    bq.assert_read_only(sql)
    return bq.run(sql, preflight=True)


def estimate_sql(sql: str) -> int:
    bq.assert_read_only(sql)
    return bq.estimate_bytes(sql)
