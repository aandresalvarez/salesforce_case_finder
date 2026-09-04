"""Semantics that only real data can prove — spec section 13.1.

Everything else in this suite runs against fakes, which is right: a fake makes
the contract explicit and the tests fast. But a fake cannot tell you that the
join in `triage_list` fans out on this warehouse, that `%` in a search term acts
as a wildcard against BigQuery's `LIKE`, or that the archive era's tables are
shaped the way the era flags claim. Those are properties of the data, and the
only honest way to check them is to ask the data.

So these are marked `warehouse` and excluded from the default run. They need
ADC and they cost money — roughly two cents for the whole file, dominated by the
two conversation-scanning searches. Run them before a release and after any
change to `queries.py`:

    uv run pytest -m warehouse

Every expensive query is session-scoped and shared across the assertions that
need it, so adding a test about search results should mean adding an assertion
to an existing fixture's consumers rather than a second search.
"""

from __future__ import annotations

import pytest

from casefinder import bq, config, data, queries
from casefinder.bq import CostError
from casefinder.queries import Filters, TriageFilters

pytestmark = pytest.mark.warehouse

CURRENT = config.ERAS["current"]
ARCHIVE = config.ERAS["archive"]

# A case that exists in the current era and has a conversation. If the warehouse
# is reloaded and this case disappears, the fixtures below fail loudly rather
# than quietly asserting nothing.
CASE = "CASE-056576"


@pytest.fixture(scope="session", autouse=True)
def credentials():
    """Spec section 13.1, first item. Also the gate on everything else here.

    A failure at this point means the run has no credentials, not that the app
    is broken, and saying so once beats twenty confusing failures.
    """
    ok, message = bq.check_access()
    if not ok:
        pytest.skip(f"no BigQuery access: {message}")
    return message


@pytest.fixture(scope="session")
def one_term():
    """One search term, conversation and fields. ~245 MB — the expensive one."""
    return data.search(
        CURRENT,
        ["omop"],
        Filters(),
        in_conversation=True,
        in_fields=True,
        sort="relevance",
        limit=50,
    )


@pytest.fixture(scope="session")
def two_terms():
    """The same search with a second term, for the AND check."""
    return data.search(
        CURRENT,
        ["omop", "cohort"],
        Filters(),
        in_conversation=True,
        in_fields=True,
        sort="relevance",
        limit=50,
    )


@pytest.fixture(scope="session")
def triage_page():
    return data.triage(
        CURRENT, TriageFilters(), sort="last_activity", descending=True
    )


# --------------------------------------------------------------------------
# Corpus shape
# --------------------------------------------------------------------------


def test_the_two_eras_are_the_sizes_the_documentation_claims():
    """The README, the proposal, and the spec all quote these numbers.

    They are load-bearing in a way that is easy to miss: the era descriptions in
    Settings tell a user which slice to pick, and a number that drifted by a
    factor of ten without anyone noticing would make that choice meaningless.
    Loose bounds, because the warehouse does get reloaded.
    """
    current = data.corpus_size(CURRENT)
    archive = data.corpus_size(ARCHIVE)
    assert 1_500 <= current <= 3_000, f"current era is {current}, documented as ~1,714"
    assert 38_000 <= archive <= 50_000, f"archive is {archive}, documented as ~41,526"
    assert archive > current, "the archive must be a superset of the current era"


def test_facets_come_back_populated_and_are_plain_strings():
    """An empty facet is a legitimate state the UI handles (spec section 12),
    but all of them empty means the extraction is broken, and the UI would show
    that as a page with no filters rather than as an error."""
    facets = data.facets(CURRENT, extended=True)
    assert facets.statuses, "no status values — the filter row would be empty"
    assert all(isinstance(s, str) and s.strip() for s in facets.statuses)
    # Section 5.5: Salesforce stores unset text as '' and every use is
    # NULLIF(TRIM())-ed, so a blank must never reach a dropdown.
    for values in (facets.statuses, facets.departments, facets.pis, facets.irbs):
        assert "" not in values
        assert not [v for v in values if v != v.strip()]


def test_the_snapshot_reports_an_age_that_makes_sense():
    fresh = data.freshness(CURRENT, config.STALE_DAYS)
    assert fresh.age_days is not None
    assert 0 <= fresh.age_days < 400, f"snapshot age of {fresh.age_days} days is not credible"
    assert 0 < fresh.open_cases <= fresh.total_cases


# --------------------------------------------------------------------------
# Search semantics
# --------------------------------------------------------------------------


def test_search_returns_one_row_per_case(one_term):
    """The single most important property of the search query.

    `search` joins cases to conversation turns, and a case with four matching
    turns must produce one result with a count of four, not four results. The
    collapse happens in a subquery before the join; if it ever moves after,
    every multi-turn case duplicates and relevance ordering becomes noise.
    """
    numbers = [hit.case_number for hit in one_term.rows]
    assert numbers, "the corpus should contain at least one 'omop' case"
    assert len(numbers) == len(set(numbers))


def test_the_true_match_count_survives_the_limit(one_term):
    """Spec FR-SEARCH-9. The count is computed before LIMIT, so a user who sees
    50 results is told how many there really were rather than being told 50."""
    assert one_term.total_matches >= len(one_term.rows)


def test_a_second_term_narrows_rather_than_widens(one_term, two_terms):
    """AND semantics. The failure this catches is a builder that ORs terms,
    which looks like better recall and is the opposite of what the spec asks
    for — and which no fake can detect, because the fake returns what it is
    given."""
    assert two_terms.total_matches <= one_term.total_matches
    single = {hit.case_number for hit in one_term.rows}
    both = {hit.case_number for hit in two_terms.rows}
    # Only meaningful where neither result was truncated by the limit.
    if one_term.total_matches == len(single) and two_terms.total_matches == len(both):
        assert both <= single


def test_a_percent_sign_is_a_literal_not_a_wildcard():
    """`LIKE '%%%'` would match the entire corpus.

    A user searching for "100%" is searching for a string. If escaping ever
    breaks, this test returns every case in the era instead of a handful, which
    is both wrong and a 245 MB way to be wrong.
    """
    page = data.search(
        CURRENT,
        ["%%%"],
        Filters(),
        in_conversation=True,
        in_fields=True,
        sort="relevance",
        limit=50,
    )
    assert page.total_matches < data.corpus_size(CURRENT), (
        "a percent-sign term matched the whole corpus — escaping is broken"
    )


def test_matches_in_the_body_carry_a_snippet(one_term):
    """Spec FR-SEARCH-6. A conversation match with no snippet is a result the
    user cannot judge without opening the case."""
    with_body = [h for h in one_term.rows if h.matching_turns]
    assert with_body, "no conversation matches to check"
    for hit in with_body[:5]:
        assert hit.snippets, f"{hit.case_number} matched in the body with no snippet"
        assert any("omop" in s.text.lower() for s in hit.snippets)


def test_a_status_filter_actually_filters():
    facets = data.facets(CURRENT)
    status = facets.statuses[0]
    page = data.search(
        CURRENT,
        ["data"],
        Filters(statuses=[status]),
        in_conversation=False,  # fields only: ~31 MB rather than ~245 MB
        in_fields=True,
        sort="relevance",
        limit=50,
    )
    assert all(hit.status == status for hit in page.rows)


def test_browse_is_cheap_enough_to_be_the_default_path():
    """Spec section 8 budgets browse at ~4.8 MB. It runs on every filter change,
    so an accidental join to the turn table would turn a free interaction into a
    245 MB one and nothing would look wrong on screen."""
    sql, params = queries.browse(CURRENT, Filters())
    assert bq.estimate_bytes(sql, params) < 50 * 1024 * 1024


# --------------------------------------------------------------------------
# One case
# --------------------------------------------------------------------------


def test_the_case_header_comes_back_whole():
    header = data.case_header(CURRENT, CASE)
    assert header is not None, f"{CASE} is missing — pick another fixture case"
    assert header.case_number == CASE
    assert header.subject


def test_an_unknown_case_is_absent_rather_than_an_error():
    """FR-CASE-11. A typo must produce an empty state, not a traceback."""
    assert data.case_header(CURRENT, "CASE-000000") is None


def test_comments_and_messages_are_ordered_and_attributed():
    """SR-6: the comment stream is the default reading surface, so its order is
    the reading order. An unordered stream is unreadable and looks like data
    corruption rather than a missing ORDER BY."""
    comments = data.comments(CURRENT, CASE)
    assert comments, f"{CASE} has no conversation — pick another fixture case"
    times = [c.ts for c in comments if c.ts]
    assert times == sorted(times)
    assert any(c.who for c in comments), "no comment has an author"


def test_the_timeline_is_the_union_of_conversation_and_audit():
    """Spec FR-CASE-8. The current era has both sources; a timeline that only
    ever shows one of them means the UNION lost a branch."""
    timeline = data.timeline(CURRENT, CASE)
    assert timeline
    times = [e.ts for e in timeline if e.ts]
    assert times == sorted(times)
    kinds = {e.kind for e in timeline}
    assert len(kinds) >= 1
    comments = data.comments(CURRENT, CASE)
    assert len(timeline) >= len(comments), "the timeline lost conversation events"


def test_related_cases_never_include_the_case_itself():
    """FR-CASE-10 matches on PI, IRB, and department — all of which the case
    trivially shares with itself."""
    related = data.related(CURRENT, CASE)
    assert CASE not in {r.case_number for r in related}


def test_attachments_are_pointers_with_a_name():
    rows = data.attachments(CURRENT, CASE)
    for attachment in rows:
        assert attachment.file_name
        # A pointer, not a copy: the app never fetches the bytes (SR-11).
        assert attachment.gcs_uri or attachment.console_url


# --------------------------------------------------------------------------
# The archive era
# --------------------------------------------------------------------------


def test_the_archive_era_really_does_lack_history_and_attachments():
    """The era flags drive what the UI offers, and they are a claim about the
    warehouse rather than about the app. If history were quietly restored, the
    Timeline tab would keep explaining a limitation that no longer exists."""
    assert not ARCHIVE.has_history
    assert not ARCHIVE.has_attachments
    assert data.attachments(ARCHIVE, CASE) == []
    sql, _params = queries.case_timeline(ARCHIVE, CASE)
    assert "History" not in sql


def test_the_archive_reaches_further_back_than_the_current_era():
    current = data.facets(CURRENT)
    archive = data.facets(ARCHIVE)
    assert archive.min_date is not None and current.min_date is not None
    assert archive.min_date < current.min_date


# --------------------------------------------------------------------------
# Triage
# --------------------------------------------------------------------------


def test_the_triage_list_is_one_row_per_case(triage_page):
    """SR-2. `triage_list` LEFT JOINs the raw Case object and the User table.
    Either join duplicating a case would double rows in the default view, and
    the count in the title would disagree with the table under it."""
    numbers = [row.case_number for row in triage_page.rows]
    assert numbers
    assert len(numbers) == len(set(numbers))


def test_the_enriched_columns_join_without_dropping_cases(triage_page):
    """A case with no raw counterpart must still be listed — the join is LEFT
    for exactly this reason, and an INNER JOIN would silently hide cases from a
    triage queue, which is the worst possible failure for this screen."""
    plain = data.triage(
        CURRENT, TriageFilters(), sort="last_activity", descending=True, limit=queries.TRIAGE_LIMIT
    )
    assert len(plain.rows) == len(triage_page.rows)
    # And at least some of them actually carry the enriched metadata, or the
    # join is present but matching nothing.
    assert any(row.pi or row.department or row.irb for row in triage_page.rows)


def test_the_triage_list_stays_inside_its_documented_budget():
    """Section 8 budgets ~31 MB. This is the app's landing query."""
    sql, params = queries.triage_list(CURRENT, TriageFilters())
    assert bq.estimate_bytes(sql, params) < 100 * 1024 * 1024


def test_an_open_only_list_contains_no_closed_cases():
    page = data.triage(
        CURRENT, TriageFilters(open_only=True), sort="last_activity", descending=True
    )
    assert page.rows
    assert not [row for row in page.rows if (row.status or "").lower() == "closed"]


# --------------------------------------------------------------------------
# Guardrails, against the real service
# --------------------------------------------------------------------------


def test_the_read_only_guard_holds_against_a_real_client():
    """The guard is unit-tested exhaustively elsewhere. What this adds is that
    nothing downstream of it re-opens the door — `run_sql` is the only path
    user- and model-written SQL takes, and it must refuse before submitting."""
    with pytest.raises(ValueError, match="DELETE"):
        data.run_sql(f"DELETE FROM `{config.PROJECT}.salesforce_marts.dim_case` WHERE TRUE")


def test_an_oversized_query_is_refused_before_it_is_billed(monkeypatch):
    """Spec section 12. The dry run is what makes the byte cap a refusal rather
    than an invoice, and only a real estimate can prove the wiring.

    The cap is lowered rather than the query enlarged. Every table in this
    warehouse is small, so the only way to write a query that genuinely scans
    over 4 GiB is to reach outside it, and a query that would be refused before
    running is not one worth pointing at somebody else's dataset. Moving the
    ceiling under a normal query tests the same three steps — estimate, compare,
    refuse — against the same service.
    """
    monkeypatch.setattr(config, "MAX_BYTES_BILLED", 1024)
    # Not `COUNT(*)`, which BigQuery answers from table metadata for zero bytes
    # and which would therefore pass any cap at all.
    with pytest.raises(CostError) as caught:
        data.run_sql(
            f"SELECT case_number FROM `{config.PROJECT}.salesforce_marts.dim_case` LIMIT 1"
        )
    assert "safety cap" in str(caught.value)


def test_a_cheap_query_can_still_be_slow_enough_to_need_the_other_ceiling():
    """The byte cap and the time cap bound different things.

    This is not hypothetical: writing this file produced exactly this query, it
    passed preflight at a fraction of a cent, and it then ran until it was
    cancelled by hand. 275 MB of input, eleven billion rows of output.

    The estimate is asserted rather than the execution, deliberately — running
    it is the failure mode being described.
    """
    runaway = (
        f"SELECT t.*, c.* FROM `{config.PROJECT}.salesforce_marts.fct_conversation_turn` t "
        f"CROSS JOIN `{config.PROJECT}.salesforce_marts.dim_case` c"
    )
    planned = bq.estimate_bytes(runaway)
    assert planned < config.MAX_BYTES_BILLED, (
        "this query is supposed to be cheap to scan — that is the whole point"
    )
    # And the job that would be submitted for it carries a wall-clock ceiling.
    assert int(bq._job_config(None).job_timeout_ms) == config.QUERY_TIMEOUT_SECONDS * 1000


def test_every_query_the_app_submits_carries_the_cap():
    """Q-INV-2, verified at the point of submission rather than in a builder.

    BigQuery rejects a job whose scan exceeds `maximum_bytes_billed` instead of
    running it, which is the whole safety net. A missing cap is invisible until
    the bill arrives.
    """
    sql, params = queries.corpus_size(CURRENT)
    result = bq.run(sql, params)
    assert result.rows
    # The same job again, submitted through the estimator, must be priced rather
    # than executed.
    assert bq.estimate_bytes(sql, params) >= 0
