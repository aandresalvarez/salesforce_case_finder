"""What a search *means* — spec FR-SEARCH-2, 3, 4 and section 9.5.

The rule the whole search page rests on is: terms are matched literally and must
all be present. Both halves matter. "Literally" is why the SQL uses STRPOS
rather than LIKE — a user typing `100%` is looking for that string, not asking
for a wildcard. "All present" is why the predicates are ANDed, which is the
opposite of most search boxes and needs to stay true as the builder changes.
"""

from __future__ import annotations

import html
import re

import pytest

from casefinder import queries
from casefinder.queries import Filters, parse_terms

# --------------------------------------------------------------------------
# Parsing the box
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("omop", ["omop"]),
        ("  omop  ", ["omop"]),
        ("OMOP", ["omop"]),
        ("omop cohort", ["omop", "cohort"]),
        ('"date shift"', ["date shift"]),
        ('omop "date shift"', ["date shift", "omop"]),
        ('"date shift" "chart review"', ["date shift", "chart review"]),
        # A single character matches nearly everything and costs a full scan to
        # prove it, so it is dropped rather than searched.
        ("a omop", ["omop"]),
        ("x", []),
        ("", []),
        ("   ", []),
        # Duplicates collapse; the query would AND a term with itself.
        ("omop omop", ["omop"]),
        ("OMOP omop", ["omop"]),
    ],
)
def test_parse_terms(raw, expected):
    assert parse_terms(raw) == expected


def test_terms_are_capped():
    """Each term is another full-column predicate, so the count is bounded."""
    assert len(parse_terms(" ".join(f"term{i}" for i in range(50)))) == 6
    assert len(parse_terms(" ".join(f"term{i}" for i in range(50)), limit=2)) == 2


def test_punctuation_is_kept_not_treated_as_syntax():
    """There is no query language here — `+`, `-` and `%` are just characters."""
    assert parse_terms("100%") == ["100%"]
    assert parse_terms("-omop") == ["-omop"]
    assert parse_terms("covid-19") == ["covid-19"]
    assert parse_terms("a+b") == ["a+b"]


# --------------------------------------------------------------------------
# What the SQL then does with them
# --------------------------------------------------------------------------


def test_terms_are_anded_not_ored(era):
    sql, _ = queries.search(era, ["omop", "cohort"], Filters())
    body = re.findall(r"STRPOS\(LOWER\(body_clean\), @t\d\) > 0(?: AND | OR |\n)", sql)
    assert body, "no body predicate found"
    assert not any("OR" in fragment for fragment in body)
    assert " AND " in sql


def test_matching_is_literal_not_wildcard(era):
    """STRPOS over LIKE — spec FR-SEARCH-2.

    With LIKE, a user searching for `100%` would match every case, and there
    would be no way to tell them why.
    """
    sql, _ = queries.search(era, ["100%"], Filters())
    assert "LIKE" not in sql.upper()
    assert "STRPOS" in sql


def test_comparison_is_case_folded_on_both_sides(era):
    """The column is lowered in SQL; the term is lowered in Python."""
    sql, params = queries.search(era, parse_terms("OMOP"), Filters())
    assert "LOWER(body_clean)" in sql
    assert [p.value for p in params if p.name == "t0"] == ["omop"]


def test_empty_search_becomes_a_browse(era):
    """No terms is not an error and not a full-text scan — it is a listing."""
    search_sql, _ = queries.search(era, [], Filters())
    browse_sql, _ = queries.browse(era, Filters())
    assert search_sql == browse_sql
    assert "body_clean" not in search_sql


def test_cases_are_counted_once_per_case_not_once_per_turn(era):
    """A 16-turn case matching 16 times is one result, not sixteen.

    The turn matches are aggregated in a CTE before the case dimension is
    joined; joining first is the classic way this query returns duplicates.
    """
    sql, _ = queries.search(era, ["omop"], Filters())
    assert "turn_hits AS (" in sql
    assert "GROUP BY case_id" in sql
    hits_cte = sql.split("turn_hits AS (")[1].split("),")[0]
    assert "COUNT(*) AS matching_turns" in hits_cte


def test_field_and_conversation_matches_are_tracked_separately(era):
    """So a result can say *why* it matched — spec FR-SEARCH-7."""
    sql, _ = queries.search(era, ["omop"], Filters())
    assert "matched_case_fields" in sql
    assert "matching_turns" in sql


def test_scope_switches_actually_change_the_query(era):
    conversation_only, _ = queries.search(
        era, ["omop"], Filters(), in_conversation=True, in_fields=False
    )
    fields_only, _ = queries.search(
        era, ["omop"], Filters(), in_conversation=False, in_fields=True
    )
    assert "body_clean" in conversation_only
    assert "body_clean" not in fields_only
    assert "subject" in fields_only


def test_total_is_counted_before_the_limit(era):
    """FR-SEARCH-9 shows "N results · showing first 50", so N cannot be the
    number of rows returned."""
    sql, _ = queries.search(era, ["omop"], Filters(), limit=50)
    assert "COUNT(*) OVER ()" in sql
    assert sql.index("COUNT(*) OVER ()") < sql.upper().rindex("LIMIT")


# --------------------------------------------------------------------------
# Snippets
# --------------------------------------------------------------------------


def test_snippet_window_cannot_start_before_the_string(era):
    """`GREATEST(1, pos - LEAD)` — SUBSTR with a non-positive start counts from
    the end of the string in BigQuery, which would show the wrong text."""
    sql, _ = queries.search(era, ["omop"], Filters())
    assert f"GREATEST(1, pos - {queries.SNIPPET_LEAD})" in sql


def test_snippets_are_bounded_per_case(era):
    sql, _ = queries.search(era, ["omop"], Filters())
    assert f"LIMIT {queries.SNIPPETS_PER_CASE}" in sql


# --------------------------------------------------------------------------
# Highlighting — spec section 9.5
# --------------------------------------------------------------------------


def _render(text: str, terms: list[str]) -> str:
    """The exact transformation `search._snippet` applies before `ui.html`."""
    safe = html.escape(text)
    for term in terms:
        if not term:
            continue
        pattern = re.compile(re.escape(html.escape(term)), re.IGNORECASE)
        safe = pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", safe)
    return safe


def test_snippet_html_is_escaped_before_it_is_highlighted():
    """Case bodies came in as email, so they are treated as hostile.

    Escaping first and adding `<mark>` after is the only order that works:
    highlighting first would have the escape step neutralise the app's own
    markup, and skipping the escape entirely would render the corpus's HTML.
    """
    hostile = '<script>alert("x")</script> mentions omop'
    out = _render(hostile, ["omop"])
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "<mark>omop</mark>" in out


def test_a_term_that_looks_like_markup_cannot_inject():
    out = _render("the tag <b> appears here", ["<b>"])
    assert "<b>" not in out.replace("<mark>", "").replace("</mark>", "")
    assert "&lt;b&gt;" in out


def test_highlighting_is_case_insensitive_but_preserves_the_text():
    out = _render("OMOP and omop", ["omop"])
    assert "<mark>OMOP</mark>" in out
    assert "<mark>omop</mark>" in out


def test_ampersands_survive_a_round_trip():
    assert _render("R&D", []) == "R&amp;D"
