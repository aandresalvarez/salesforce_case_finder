"""Query-builder invariants — spec Q-INV-1 through Q-INV-5.

These tests care about the *shape* of what the builders return, not about rows.
A builder is a pure function from arguments to `(sql, params)`, so its contract
can be checked without credentials, and the properties checked here are the ones
that would otherwise fail in production rather than in review: a user's text
reaching the SQL string, a query with no LIMIT, a sort key taken from a click.
"""

from __future__ import annotations

import re

import pytest
from google.cloud.bigquery import ArrayQueryParameter, ScalarQueryParameter

from casefinder import config, queries
from casefinder.queries import Filters, TriageFilters

# Every builder that takes no case-specific argument, so it can be swept.
CORPUS_BUILDERS = (
    ("search", lambda era: queries.search(era, ["omop"], Filters())),
    ("browse", lambda era: queries.browse(era, Filters())),
    ("corpus_size", lambda era: queries.corpus_size(era)),
    ("facets", lambda era: queries.facets(era)),
    ("facets_extended", lambda era: queries.facets(era, extended=True)),
    ("freshness", lambda era: queries.warehouse_freshness(era)),
    ("triage_list", lambda era: queries.triage_list(era, TriageFilters())),
)

CASE_BUILDERS = (
    ("case_header", queries.case_header),
    ("case_timeline", queries.case_timeline),
    ("case_attachments", queries.case_attachments),
    ("comments_stream", queries.comments_stream),
    ("related_cases", queries.related_cases),
)


def _all(era):
    for name, build in CORPUS_BUILDERS:
        yield name, build(era)
    for name, build in CASE_BUILDERS:
        yield name, build(era, "CASE-056576")


# --------------------------------------------------------------------------
# Q-INV-3: builders are pure and return (sql, params)
# --------------------------------------------------------------------------


def test_every_builder_returns_sql_and_params(era):
    for name, result in _all(era):
        assert isinstance(result, tuple) and len(result) == 2, name
        sql, params = result
        assert isinstance(sql, str) and sql.strip(), name
        assert isinstance(params, list), name


def test_builders_are_deterministic(era):
    """Same arguments, same SQL — nothing reads a clock or a global."""
    for name, build in CORPUS_BUILDERS:
        assert build(era)[0] == build(era)[0], name


def test_builders_are_read_only(era):
    """Nothing the app generates can mutate, checked with the same guard the
    free-form SQL path uses."""
    from casefinder.bq import assert_read_only

    for name, (sql, _params) in _all(era):
        try:
            assert_read_only(sql)  # raises on anything that is not a single SELECT
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"{name}: {exc}")


# --------------------------------------------------------------------------
# Q-INV-1: user input travels as a bound parameter, never as SQL text
# --------------------------------------------------------------------------

INJECTION = "'; DROP TABLE dim_case; --"


def test_search_terms_never_reach_the_sql_string(era):
    sql, params = queries.search(era, ["omop", INJECTION.lower()], Filters())
    assert "DROP TABLE" not in sql
    assert INJECTION.lower() not in sql
    bound = [p.value for p in params if isinstance(p, ScalarQueryParameter)]
    assert INJECTION.lower() in bound


def test_case_number_is_bound_not_interpolated(era):
    for name, build in CASE_BUILDERS:
        sql, params = build(era, INJECTION)
        assert INJECTION not in sql, name
        values = [
            p.value for p in params if isinstance(p, ScalarQueryParameter)
        ]
        assert INJECTION in values, name


def test_filter_values_are_bound_arrays(era):
    filters = Filters(statuses=[INJECTION], types=["Data"])
    sql, params = queries.search(era, ["omop"], filters)
    assert INJECTION not in sql
    arrays = {p.name: p.values for p in params if isinstance(p, ArrayQueryParameter)}
    assert arrays["f_status"] == [INJECTION]


def test_triage_filter_values_are_bound_arrays(era):
    filters = TriageFilters(pis=[INJECTION], departments=["Medicine"])
    sql, params = queries.triage_list(era, filters)
    assert INJECTION not in sql
    arrays = {p.name: p.values for p in params if isinstance(p, ArrayQueryParameter)}
    assert arrays["f_pi"] == [INJECTION]
    assert arrays["f_dept"] == ["Medicine"]


def test_placeholder_count_matches_term_count(era):
    """The only thing user input may change about the SQL text is how many
    `@tN` placeholders appear in it."""
    for count in (1, 2, 5):
        terms = [f"term{i}" for i in range(count)]
        sql, params = queries.search(era, terms, Filters())
        placeholders = {int(m) for m in re.findall(r"@t(\d+)\b", sql)}
        assert placeholders == set(range(count))
        bound = {p.name for p in params if p.name.startswith("t")}
        assert bound == {f"t{i}" for i in range(count)}


# --------------------------------------------------------------------------
# Q-INV-4: sort keys come from an allowlist
# --------------------------------------------------------------------------


def test_unknown_sort_falls_back_rather_than_interpolating(era):
    malicious = "case_number; DROP TABLE x"
    sql, _params = queries.triage_list(era, TriageFilters(), sort=malicious)
    assert "DROP TABLE" not in sql
    assert queries.TRIAGE_SORTS[queries.DEFAULT_TRIAGE_SORT] in sql


@pytest.mark.parametrize("key", sorted(queries.TRIAGE_SORTS))
def test_every_allowlisted_sort_builds(era, key):
    sql, _params = queries.triage_list(era, TriageFilters(), sort=key)
    assert queries.TRIAGE_SORTS[key] in sql


def test_search_sort_is_allowlisted(era):
    sql, _params = queries.search(era, ["omop"], Filters(), sort="nonsense")
    assert "nonsense" not in sql


# --------------------------------------------------------------------------
# Bounded results
# --------------------------------------------------------------------------


def test_row_returning_builders_are_limited(era):
    """Every builder that can return many rows binds a row limit.

    The per-case builders are excluded: a case's own conversation is bounded by
    the case, and truncating it would silently hide the end of a thread.
    """
    unbounded_by_design = {"corpus_size", "facets", "facets_extended", "freshness"}
    per_case_full_read = {
        "case_header",
        "comments_stream",
        "case_timeline",
        "case_attachments",
    }

    for name, (sql, params) in _all(era):
        if name in unbounded_by_design or name in per_case_full_read:
            continue
        assert "LIMIT" in sql.upper(), name
        limits = [p for p in params if p.name in {"row_limit", "limit"}]
        assert limits, f"{name} has a LIMIT but does not bind it"


def test_triage_limit_is_bound_not_formatted(era):
    sql, params = queries.triage_list(era, TriageFilters(), limit=17)
    assert "LIMIT @row_limit" in sql
    assert "LIMIT 17" not in sql
    assert [p.value for p in params if p.name == "row_limit"] == [17]


# --------------------------------------------------------------------------
# Era shape — the archive has fewer tables
# --------------------------------------------------------------------------


def test_builders_reference_only_their_own_era(era):
    other = "salesforce_marts" if era.dataset == "salesforce_current" else "salesforce_current"
    for name, (sql, _params) in _all(era):
        assert other not in sql, f"{name} reaches into the other era's dataset"


def test_archive_timeline_omits_the_history_table(archive):
    sql, _params = queries.case_timeline(archive, "CASE-000001")
    assert "case_history" not in sql


def test_current_timeline_includes_history(current):
    sql, _params = queries.case_timeline(current, "CASE-056576")
    assert "case_history" in sql


def test_extended_facets_join_the_raw_case_object(era):
    plain, _ = queries.facets(era)
    extended, _ = queries.facets(era, extended=True)
    assert config.CASE_TABLE not in plain
    assert config.CASE_TABLE in extended


# --------------------------------------------------------------------------
# The empty-string problem — spec section 5.5
# --------------------------------------------------------------------------

TRIAGE_FIELDS = ("PI_Name__c", "Project_Department__c", "IRB_Protocol__c", "Funding_Status__c")


def test_raw_case_fields_are_always_null_normalised(era):
    """Salesforce stores an unset text field as '' rather than NULL.

    33,821 of 41,526 cases have `Project_Department__c = ''`. A bare reference
    would put a blank entry at the top of every filter dropdown and render as an
    empty cell that looks like a bug, so every use goes through NULLIF(TRIM()).
    """
    for name, (sql, _params) in _all(era):
        for column in TRIAGE_FIELDS:
            for match in re.finditer(rf"\brc\.{column}\b", sql):
                window = sql[max(0, match.start() - 40) : match.start()]
                assert "NULLIF(TRIM(" in window, f"{name}: bare rc.{column}"


def test_triage_join_is_a_left_join(era):
    """A case with no raw counterpart must still appear in the list."""
    sql, _params = queries.triage_list(era, TriageFilters())
    assert sql.count("LEFT JOIN") == 2  # the User table and the raw Case object
    assert "INNER JOIN" not in sql


# --------------------------------------------------------------------------
# The sweep only means something if it sweeps everything
# --------------------------------------------------------------------------


def test_the_sweep_covers_every_builder_in_the_module():
    """Every invariant in this file is checked by walking `_all`.

    Which makes the two tuples at the top load-bearing: a builder added to
    `queries.py` and not added there gets no parameterisation check, no LIMIT
    check, no era check, and nothing fails. The gap would be invisible — the
    suite would stay green while the new query was the only unguarded one in the
    codebase. So the module is enumerated here and compared against the lists.

    A builder that genuinely cannot be swept (one needing an argument the sweep
    has no way to invent) belongs in `_EXEMPT` with a reason, not left out.
    """
    import inspect

    _EXEMPT = {
        "parse_terms",  # returns terms, not (sql, params)
    }

    public = {
        name
        for name, obj in inspect.getmembers(queries, inspect.isfunction)
        if not name.startswith("_") and obj.__module__ == queries.__name__
    }
    swept = {name for name, _ in CORPUS_BUILDERS} | {name for name, _ in CASE_BUILDERS}
    # `warehouse_freshness` is swept under the shorter name the pages use for it.
    swept |= {"warehouse_freshness"}

    missing = public - swept - _EXEMPT
    assert not missing, f"builders with no invariant coverage: {sorted(missing)}"


def test_related_cases_rank_by_strength_before_recency(era):
    """Twenty-three related cases ordered by recency is a list nobody reads.

    The two sharing this case's IRB protocol — the two actually about the same
    study — sat below ten that merely share a department, with the reason
    printed at the end of each row rather than being the thing that ordered it.
    In a department the size of Anaesthesia, sharing one is barely a signal.
    """
    sql, _params = queries.related_cases(era, "CASE-1")

    order = sql.split("ORDER BY")[1]
    irb = order.index("a.irb IS NOT NULL")
    pi = order.index("a.pi IS NOT NULL")
    recency = order.index("last_activity")

    assert irb < pi < recency, "recency still outranks the relationship"
