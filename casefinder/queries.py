"""SQL builders.

Every function returns `(sql, params)`. The SQL string is assembled only from
values this module controls — table names from config, and the *number* of
placeholders. Anything typed by a user arrives as a bound parameter.

Search uses `STRPOS(LOWER(body), @term) > 0` rather than `LIKE '%term%'`. Two
reasons: STRPOS is a literal match, so a user typing `%` or `_` searches for
that character instead of accidentally matching everything; and it hands back
the match offset, which is what lets the results show the sentence the term
appeared in rather than just a row count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from google.cloud.bigquery import ArrayQueryParameter, ScalarQueryParameter

from . import config
from .config import Era

# How much text to show around a match, and how far to back up before it so the
# term lands mid-snippet with its lead-in visible.
SNIPPET_WIDTH = 280
SNIPPET_LEAD = 110
SNIPPETS_PER_CASE = 3


# --------------------------------------------------------------------------
# Parsing what the user typed
# --------------------------------------------------------------------------

_PHRASE = re.compile(r'"([^"]+)"')


def parse_terms(raw: str, limit: int = 6) -> list[str]:
    """Split a search box into literal terms that must *all* be present.

    `omop "date shift"` becomes ['omop', 'date shift'] — two terms ANDed, the
    quoted one kept whole. Lowercased here because the SQL compares against
    LOWER(body), and doing it once in Python keeps the comparison honest.
    """
    raw = (raw or "").strip()
    if not raw:
        return []

    phrases = [m.group(1).strip() for m in _PHRASE.finditer(raw)]
    remainder = _PHRASE.sub(" ", raw)
    words = [w for w in remainder.split() if w.strip()]

    terms: list[str] = []
    for term in phrases + words:
        term = term.strip().lower()
        # A single character matches nearly everything and costs a full scan to
        # prove it; drop rather than pretend it is a search.
        if len(term) >= 2 and term not in terms:
            terms.append(term)
    return terms[:limit]


@dataclass
class Filters:
    statuses: list[str] = field(default_factory=list)
    origin_classes: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None

    def clauses(self, alias: str = "c") -> tuple[list[str], list[Any]]:
        """Turn the filter selections into SQL fragments plus bound params."""
        sql: list[str] = []
        params: list[Any] = []
        if self.statuses:
            sql.append(f"{alias}.status IN UNNEST(@f_status)")
            params.append(ArrayQueryParameter("f_status", "STRING", self.statuses))
        if self.origin_classes:
            sql.append(f"{alias}.origin_class IN UNNEST(@f_origin)")
            params.append(
                ArrayQueryParameter("f_origin", "STRING", self.origin_classes)
            )
        if self.types:
            sql.append(f"{alias}.type IN UNNEST(@f_type)")
            params.append(ArrayQueryParameter("f_type", "STRING", self.types))
        if self.date_from:
            sql.append(f"{alias}.created_at >= @f_from")
            params.append(ScalarQueryParameter("f_from", "TIMESTAMP", _ts(self.date_from)))
        if self.date_to:
            # Inclusive of the chosen end date, hence the +1 day exclusive bound.
            sql.append(f"{alias}.created_at < TIMESTAMP_ADD(@f_to, INTERVAL 1 DAY)")
            params.append(ScalarQueryParameter("f_to", "TIMESTAMP", _ts(self.date_to)))
        return sql, params


def _ts(d: date) -> str:
    return f"{d.isoformat()} 00:00:00+00:00"


def _term_params(terms: list[str]) -> list[ScalarQueryParameter]:
    return [ScalarQueryParameter(f"t{i}", "STRING", t) for i, t in enumerate(terms)]


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

SORTS = {
    "relevance": "matching_turns DESC, created_at DESC",
    "newest": "created_at DESC",
    "oldest": "created_at ASC",
    "longest": "turn_count DESC, created_at DESC",
}


def search(
    era: Era,
    terms: list[str],
    filters: Filters,
    *,
    in_conversation: bool = True,
    in_fields: bool = True,
    sort: str = "relevance",
    limit: int = 100,
) -> tuple[str, list[Any]]:
    """Find cases whose conversation and/or case fields contain every term.

    A case qualifies if it matched in either place, but the two are tracked
    separately so the result can say which — "the phrase is in the subject line"
    and "the phrase is buried in reply four" are different findings.

    Matching turns are counted and collapsed to one row per case in a CTE
    *before* joining the case dimension. Joining first would return the case
    once per matching turn, and a 16-turn case would look like 16 cases.
    """
    if not terms:
        return _browse(era, filters, sort=sort, limit=limit)

    turns = era.table("fct_conversation_turn")
    cases = era.table("dim_case")
    params: list[Any] = _term_params(terms)

    body_pred = " AND ".join(
        f"STRPOS(LOWER(body_clean), @t{i}) > 0" for i in range(len(terms))
    )
    # Subject and description are searched as one blob so a term spanning the
    # boundary is not required to sit in a particular field.
    field_expr = "LOWER(CONCAT(IFNULL(subject,''), ' ', IFNULL(description,'')))"
    field_pred = " AND ".join(
        f"STRPOS({field_expr}, @t{i}) > 0" for i in range(len(terms))
    )

    ctes: list[str] = []

    if in_conversation:
        ctes.append(
            f"""matched_turns AS (
  SELECT
    case_id,
    turn_seq,
    actor_role,
    turn_ts,
    STRPOS(LOWER(body_clean), @t0) AS pos,
    body_clean
  FROM {turns}
  WHERE {body_pred}
),
turn_hits AS (
  SELECT
    case_id,
    COUNT(*) AS matching_turns,
    MIN(turn_ts) AS first_mention,
    ARRAY_AGG(
      STRUCT(
        turn_seq,
        actor_role,
        -- GREATEST keeps the 1-based start legal when the match is at the very
        -- beginning of the body; SUBSTR would otherwise count from the end.
        SUBSTR(body_clean, GREATEST(1, pos - {SNIPPET_LEAD}), {SNIPPET_WIDTH}) AS text
      )
      ORDER BY turn_seq
      LIMIT {SNIPPETS_PER_CASE}
    ) AS snippets
  FROM matched_turns
  GROUP BY case_id
)"""
        )
    else:
        ctes.append(
            """turn_hits AS (
  SELECT
    CAST(NULL AS STRING) AS case_id,
    0 AS matching_turns,
    CAST(NULL AS TIMESTAMP) AS first_mention,
    ARRAY<STRUCT<turn_seq INT64, actor_role STRING, text STRING>>[] AS snippets
  FROM UNNEST([]) AS _
)"""
        )

    if in_fields:
        ctes.append(
            f"""field_hits AS (
  SELECT case_id FROM {cases} WHERE {field_pred}
)"""
        )
    else:
        ctes.append(
            """field_hits AS (
  SELECT CAST(NULL AS STRING) AS case_id FROM UNNEST([]) AS _
)"""
        )

    where = ["(t.case_id IS NOT NULL OR f.case_id IS NOT NULL)"]
    fclauses, fparams = filters.clauses("c")
    where.extend(fclauses)
    params.extend(fparams)
    params.append(ScalarQueryParameter("row_limit", "INT64", limit))

    order = SORTS.get(sort, SORTS["relevance"])

    sql = f"""WITH
{",".join(chr(10) + c for c in ctes)}

SELECT
  c.case_number,
  c.subject,
  c.status,
  c.type,
  c.origin_class,
  c.created_at,
  DATE(c.created_at) AS created,
  c.closed_at,
  ROUND(c.hours_to_close / 24, 1) AS days_to_close,
  c.turn_count,
  IFNULL(t.matching_turns, 0) AS matching_turns,
  f.case_id IS NOT NULL AS matched_case_fields,
  IFNULL(t.snippets, ARRAY<STRUCT<turn_seq INT64, actor_role STRING, text STRING>>[]) AS snippets,
  -- Window functions are evaluated before LIMIT, so this is the true number of
  -- matching cases, not the size of the page being returned. The UI needs it
  -- both to say "showing 100 of 1,710" and to recognise a term that matches
  -- the whole corpus — a check that used the page size could never fire.
  COUNT(*) OVER () AS total_matches
FROM {cases} c
LEFT JOIN turn_hits  t ON t.case_id = c.case_id
LEFT JOIN field_hits f ON f.case_id = c.case_id
WHERE {' AND '.join(where)}
ORDER BY {order}
LIMIT @row_limit"""
    return sql, params


def _browse(
    era: Era, filters: Filters, *, sort: str = "newest", limit: int = 100
) -> tuple[str, list[Any]]:
    """No search term: just list cases matching the filters.

    Reads only the case dimension, so browsing never pays for a body scan.
    """
    cases = era.table("dim_case")
    where, params = filters.clauses("c")
    params.append(ScalarQueryParameter("row_limit", "INT64", limit))
    order = SORTS.get(sort if sort != "relevance" else "newest", SORTS["newest"])
    sql = f"""SELECT
  c.case_number,
  c.subject,
  c.status,
  c.type,
  c.origin_class,
  c.created_at,
  DATE(c.created_at) AS created,
  c.closed_at,
  ROUND(c.hours_to_close / 24, 1) AS days_to_close,
  c.turn_count,
  0 AS matching_turns,
  FALSE AS matched_case_fields,
  ARRAY<STRUCT<turn_seq INT64, actor_role STRING, text STRING>>[] AS snippets,
  COUNT(*) OVER () AS total_matches
FROM {cases} c
{('WHERE ' + ' AND '.join(where)) if where else ''}
ORDER BY {order}
LIMIT @row_limit"""
    return sql, params


def corpus_size(era: Era) -> tuple[str, list[Any]]:
    """Total case count, used to detect a term that matches everything."""
    return f"SELECT COUNT(*) AS n FROM {era.table('dim_case')}", []


def facets(era: Era) -> tuple[str, list[Any]]:
    """Distinct values for the filter dropdowns, in one pass over dim_case."""
    cases = era.table("dim_case")
    sql = f"""SELECT
  ARRAY_AGG(DISTINCT status IGNORE NULLS ORDER BY status) AS statuses,
  ARRAY_AGG(DISTINCT origin_class IGNORE NULLS ORDER BY origin_class) AS origin_classes,
  ARRAY_AGG(DISTINCT type IGNORE NULLS ORDER BY type) AS types,
  MIN(DATE(created_at)) AS min_date,
  MAX(DATE(created_at)) AS max_date
FROM {cases}"""
    return sql, []


# --------------------------------------------------------------------------
# One case
# --------------------------------------------------------------------------


def case_header(era: Era, case_number: str) -> tuple[str, list[Any]]:
    """The panel at the top of a case page."""
    cases = era.table("dim_case")
    attach_expr = (
        f"(SELECT COUNT(*) FROM {era.table('attachment_blob')} a "
        "WHERE a.case_id = c.case_id)"
        if era.has_attachments
        else "CAST(NULL AS INT64)"
    )
    sql = f"""SELECT
  c.case_id,
  c.case_number,
  c.subject,
  c.status,
  c.origin,
  c.type,
  c.reason,
  c.priority,
  u.Name AS owner,
  c.created_at,
  c.closed_at,
  ROUND(c.hours_to_close / 24, 1) AS days_to_close,
  c.turn_count,
  c.customer_turn_count,
  c.agent_turn_count,
  {attach_expr} AS attachments,
  c.description
FROM {cases} c
LEFT JOIN `{config.USER_TABLE}` u ON u.Id = c.owner_id
WHERE c.case_number = @case_number"""
    return sql, [ScalarQueryParameter("case_number", "STRING", case_number)]


def case_timeline(era: Era, case_number: str) -> tuple[str, list[Any]]:
    """Conversation and audit trail interleaved chronologically.

    The two halves share nothing but a case id and a timestamp, so they are
    UNIONed into a common shape rather than joined — there is no key pairing an
    email to a status change, so any join condition would invent a relationship.

    For the full archive there is no audit trail at all, so the query collapses
    to just the conversation half.
    """
    turns = era.table("fct_conversation_turn")
    cases = era.table("dim_case")
    user = f"`{config.USER_TABLE}`"

    conversation = f"""conversation AS (
  SELECT
    t.turn_ts AS ts,
    'message' AS kind,
    CONCAT(t.actor_role, ' ', t.direction) AS what,
    -- CaseComment rows carry only actor_user_id, so without this join every
    -- internal note is authored by nobody.
    COALESCE(t.actor_name, u.Name, t.actor_email) AS who,
    t.subject AS detail,
    t.body_clean AS body,
    t.body_clean_len AS body_len
  FROM {turns} t
  JOIN {cases} c ON c.case_id = t.case_id
  LEFT JOIN {user} u ON u.Id = t.actor_user_id
  WHERE c.case_number = @case_number
)"""

    if not era.has_history:
        sql = f"""WITH {conversation}
SELECT ROW_NUMBER() OVER (ORDER BY ts) AS seq, ts, kind, what, who, detail, body_len, body
FROM conversation
ORDER BY seq"""
        return sql, [ScalarQueryParameter("case_number", "STRING", case_number)]

    history = era.table("case_history")
    sql = f"""WITH {conversation},

audit AS (
  SELECT
    h.event_ts AS ts,
    'event' AS kind,
    h.event AS what,
    h.changed_by AS who,
    -- Description edits and the created/closed markers carry no values; say so
    -- rather than rendering "NULL -> NULL" and letting it read as data loss.
    IF(h.old_value IS NULL AND h.new_value IS NULL,
       '(values not retained by Salesforce)',
       CONCAT(IFNULL(h.old_value, '(blank)'), '  ->  ', IFNULL(h.new_value, '(blank)')))
      AS detail,
    CAST(NULL AS STRING) AS body,
    CAST(NULL AS INT64) AS body_len
  FROM {history} h
  WHERE h.case_number = @case_number
)

SELECT
  ROW_NUMBER() OVER (ORDER BY ts, kind) AS seq,
  ts, kind, what, who, detail, body_len, body
FROM (SELECT * FROM conversation UNION ALL SELECT * FROM audit)
ORDER BY seq"""
    return sql, [ScalarQueryParameter("case_number", "STRING", case_number)]


def case_attachments(era: Era, case_number: str) -> tuple[str, list[Any]]:
    sql = f"""SELECT file_name, mb, gcs_uri, console_url
FROM {era.table('attachment_blob')}
WHERE case_number = @case_number
ORDER BY bytes DESC"""
    return sql, [ScalarQueryParameter("case_number", "STRING", case_number)]


def case_transcript(era: Era, case_number: str) -> tuple[str, list[Any]]:
    """The whole thread as one ordered list of turns, for reading top to bottom."""
    turns = era.table("fct_conversation_turn")
    cases = era.table("dim_case")
    sql = f"""SELECT
  t.turn_seq,
  t.turn_ts,
  t.actor_role,
  t.direction,
  COALESCE(t.actor_name, u.Name, t.actor_email) AS who,
  t.subject,
  t.body_clean AS body
FROM {turns} t
JOIN {cases} c ON c.case_id = t.case_id
LEFT JOIN `{config.USER_TABLE}` u ON u.Id = t.actor_user_id
WHERE c.case_number = @case_number
ORDER BY t.turn_seq"""
    return sql, [ScalarQueryParameter("case_number", "STRING", case_number)]
