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
# Triage attributes (v2.1)
# --------------------------------------------------------------------------
#
# The modelled `dim_case` describes a case as a conversation. The attributes
# support staff actually triage on — who the PI is, which IRB protocol, which
# department, whether it is funded — were never modelled, so every operational
# query joins back to the raw Salesforce Case object on `case_id = Case.Id`.
# That join is 1:1 and complete: 1,721 of 1,721 current-era cases resolve.
#
# Each attribute is wrapped in NULLIF(TRIM(...), '') because Salesforce stores
# an unset text field as the empty string, not NULL. Without it, 33,821 of the
# 41,533 cases would report a department that renders as a blank cell, and
# every filter dropdown would open with an empty first entry.

_RAW_JOIN = f"LEFT JOIN `{config.CASE_TABLE}` rc ON rc.Id = c.case_id"

# The one triage attribute that does not come from the raw Case object. A case
# points at its owner by id, so the name lives in the User table and arrives
# through the join the operational queries already make — which is why this
# expression is only valid where `u` is in scope.
OWNER = "NULLIF(TRIM(u.Name), '')"

PI = "NULLIF(TRIM(rc.PI_Name__c), '')"
DEPARTMENT = "NULLIF(TRIM(rc.Project_Department__c), '')"
IRB = "NULLIF(TRIM(rc.IRB_Protocol__c), '')"
IRB_STATUS = "NULLIF(TRIM(rc.IRB_Status__c), '')"
FUNDING = "NULLIF(TRIM(rc.Funding_Status__c), '')"

# Spec section 5.5: last activity is the newest conversation turn, falling back
# to the record's own modification stamp for a case nobody has replied to.
LAST_ACTIVITY = "COALESCE(c.last_turn_at, c.last_modified_at)"


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

# Every one of these ends in the case number, and none of them is a total order
# without it. `created_at DESC` alone leaves every case created in the same
# second free to come back in any order, which BigQuery is entitled to vary
# between two runs of the same query — so a case can sit on two pages at once,
# or on none, and raising Rows per page from 25 to 50 can lose one that was
# visible before. A LIMIT over a partial order is a lottery whether or not
# anybody is paging through it.
_TIEBREAK = "c.case_number DESC"
SORTS = {
    "relevance": f"matching_turns DESC, created_at DESC, {_TIEBREAK}",
    "newest": f"created_at DESC, {_TIEBREAK}",
    "oldest": f"created_at ASC, {_TIEBREAK}",
    "longest": f"turn_count DESC, created_at DESC, {_TIEBREAK}",
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
    offset: int = 0,
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
        return browse(era, filters, sort=sort, limit=limit, offset=offset)

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
    params.append(ScalarQueryParameter("row_offset", "INT64", max(0, offset)))

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
LIMIT @row_limit OFFSET @row_offset"""
    return sql, params


def browse(
    era: Era, filters: Filters, *, sort: str = "newest", limit: int = 100, offset: int = 0
) -> tuple[str, list[Any]]:
    """No search term: just list cases matching the filters.

    Reads only the case dimension, so browsing never pays for a body scan.
    """
    cases = era.table("dim_case")
    where, params = filters.clauses("c")
    params.append(ScalarQueryParameter("row_limit", "INT64", limit))
    params.append(ScalarQueryParameter("row_offset", "INT64", max(0, offset)))
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
LIMIT @row_limit OFFSET @row_offset"""
    return sql, params


def corpus_size(era: Era) -> tuple[str, list[Any]]:
    """Total case count, used to detect a term that matches everything."""
    return f"SELECT COUNT(*) AS n FROM {era.table('dim_case')}", []


# PI and department lists run to the high hundreds. A dropdown that long is
# already unusable, and pulling all of it into the client buys nothing.
FACET_LIMIT = 500


def facets(era: Era, *, extended: bool = False) -> tuple[str, list[Any]]:
    """Distinct values for the filter dropdowns, in one pass over dim_case.

    `extended=True` also returns the triage dimensions (owner, department, PI,
    IRB), which requires the raw-Case join and, for the owner, the User join.
    Search only needs the cheap set, so it stays the default — spec section 7.3
    lists this builder as reading `dim_case`, and that remains true unless a
    list view asks for more.
    """
    cases = era.table("dim_case")
    if not extended:
        return (
            f"""SELECT
  ARRAY_AGG(DISTINCT status IGNORE NULLS ORDER BY status) AS statuses,
  ARRAY_AGG(DISTINCT origin_class IGNORE NULLS ORDER BY origin_class) AS origin_classes,
  ARRAY_AGG(DISTINCT type IGNORE NULLS ORDER BY type) AS types,
  MIN(DATE(created_at)) AS min_date,
  MAX(DATE(created_at)) AS max_date
FROM {cases}""",
            [],
        )

    sql = f"""WITH enriched AS (
  SELECT
    c.status,
    c.origin_class,
    c.type,
    c.created_at,
    {OWNER} AS owner,
    {DEPARTMENT} AS department,
    {PI} AS pi,
    {IRB} AS irb
  FROM {cases} c
  LEFT JOIN `{config.USER_TABLE}` u ON u.Id = c.owner_id
  {_RAW_JOIN}
)
SELECT
  ARRAY_AGG(DISTINCT status IGNORE NULLS ORDER BY status) AS statuses,
  ARRAY_AGG(DISTINCT origin_class IGNORE NULLS ORDER BY origin_class) AS origin_classes,
  ARRAY_AGG(DISTINCT type IGNORE NULLS ORDER BY type) AS types,
  ARRAY_AGG(DISTINCT owner IGNORE NULLS ORDER BY owner LIMIT {FACET_LIMIT}) AS owners,
  ARRAY_AGG(DISTINCT department IGNORE NULLS ORDER BY department
            LIMIT {FACET_LIMIT}) AS departments,
  ARRAY_AGG(DISTINCT pi IGNORE NULLS ORDER BY pi LIMIT {FACET_LIMIT}) AS pis,
  ARRAY_AGG(DISTINCT irb IGNORE NULLS ORDER BY irb LIMIT {FACET_LIMIT}) AS irbs,
  MIN(DATE(created_at)) AS min_date,
  MAX(DATE(created_at)) AS max_date
FROM enriched"""
    return sql, []


def warehouse_freshness(era: Era) -> tuple[str, list[Any]]:
    """How far behind live Salesforce this snapshot is, plus the open count.

    Every operational list has to state this. A stale snapshot showing a closed
    case as open is the single most likely way this app misleads someone.
    """
    sql = f"""SELECT
  MAX(last_modified_at) AS newest,
  COUNTIF(NOT is_closed) AS open_cases,
  COUNT(*) AS total_cases
FROM {era.table('dim_case')}"""
    return sql, []


# --------------------------------------------------------------------------
# One case
# --------------------------------------------------------------------------


def case_header(era: Era, case_number: str) -> tuple[str, list[Any]]:
    """The panel at the top of a case page.

    Extended in v2.1 with the triage attributes (PI, IRB protocol, department,
    funding) that only exist on the raw Case object — see `_RAW_JOIN`.
    """
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
  {OWNER} AS owner,
  {PI} AS pi,
  {DEPARTMENT} AS department,
  {IRB} AS irb,
  {IRB_STATUS} AS irb_status,
  {FUNDING} AS funding,
  c.created_at,
  c.closed_at,
  {LAST_ACTIVITY} AS last_activity,
  ROUND(c.hours_to_close / 24, 1) AS days_to_close,
  c.turn_count,
  c.customer_turn_count,
  c.agent_turn_count,
  {attach_expr} AS attachments,
  c.description
FROM {cases} c
LEFT JOIN `{config.USER_TABLE}` u ON u.Id = c.owner_id
{_RAW_JOIN}
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


# --------------------------------------------------------------------------
# Reading a case (v2.1)
# --------------------------------------------------------------------------
#
# v1 had a single `case_transcript`. v2.1 splits it in two because the spec
# asks for two different readings of the same rows: Comments is a flat stream
# meant to be read top to bottom (FR-CASE-5), Messages is a compact index that
# expands one row at a time (FR-CASE-7). Same source, different shape.
#
# "Comments" is a UX word, not a table. `Case.Comments` is empty in this corpus
# — every row of it — so the comment stream is built from conversation turns:
# CaseComment rows (internal notes) and the email traffic copied onto the case.


def _turn_source(era: Era) -> str:
    """The FROM/JOIN block shared by every per-case turn query.

    The User join is load-bearing rather than cosmetic: CaseComment rows carry
    only `actor_user_id`, so without it every internal note — the larger half
    of the corpus at 12,878 turns — is authored by nobody.
    """
    return f"""FROM {era.table('fct_conversation_turn')} t
JOIN {era.table('dim_case')} c ON c.case_id = t.case_id
LEFT JOIN `{config.USER_TABLE}` u ON u.Id = t.actor_user_id
WHERE c.case_number = @case_number"""


def comments_stream(era: Era, case_number: str) -> tuple[str, list[Any]]:
    """The default case reading: one flat chronological stream of the thread.

    Always oldest first. The page offers the other order and produces it by
    reversing the rows it already holds — asking the warehouse for them the
    other way round would re-scan the body column to reorder rows that are
    already in memory.

    Carries the subject and the body length as well, which `case_messages`
    used to fetch separately. They were the only two columns that made a
    "message" different from a "comment": same table, same rows, same order,
    read twice. A reader switching to the compact reading now pays nothing,
    where the second tab cost another ~256 MB scan of the body column.
    """
    sql = f"""SELECT
  t.turn_seq,
  t.turn_ts,
  t.actor_role,
  t.direction,
  t.source_object,
  COALESCE(t.actor_name, u.Name, t.actor_email) AS who,
  t.subject,
  t.body_clean AS body,
  t.body_clean_len AS body_len
{_turn_source(era)}
ORDER BY t.turn_seq"""
    return sql, [ScalarQueryParameter("case_number", "STRING", case_number)]


RELATED_LIMIT = 50


def related_cases(
    era: Era, case_number: str, *, limit: int = RELATED_LIMIT
) -> tuple[str, list[Any]]:
    """Other cases sharing this one's PI, IRB protocol, or department.

    The anchor's three attributes are read once into a single-row CTE and cross
    joined, so the comparison happens inside BigQuery rather than costing a
    second round trip to fetch the values first.

    Each dimension is guarded with an explicit IS NOT NULL. Without it a case
    with no recorded PI would match on `pi = pi` being NULL — which is not a
    match, but is also not an exclusion, and the guard makes the intent legible
    rather than depending on three-valued logic to do the right thing quietly.
    """
    cases = era.table("dim_case")
    sql = f"""WITH anchor AS (
  SELECT {PI} AS pi, {IRB} AS irb, {DEPARTMENT} AS department
  FROM {cases} c
  {_RAW_JOIN}
  WHERE c.case_number = @case_number
  LIMIT 1
)
SELECT
  c.case_number,
  c.subject,
  c.status,
  {LAST_ACTIVITY} AS last_activity,
  a.pi IS NOT NULL AND {PI} = a.pi AS same_pi,
  a.irb IS NOT NULL AND {IRB} = a.irb AS same_irb,
  a.department IS NOT NULL AND {DEPARTMENT} = a.department AS same_department
FROM {cases} c
{_RAW_JOIN}
CROSS JOIN anchor a
WHERE c.case_number != @case_number
  AND (
    (a.pi IS NOT NULL AND {PI} = a.pi)
    OR (a.irb IS NOT NULL AND {IRB} = a.irb)
    OR (a.department IS NOT NULL AND {DEPARTMENT} = a.department)
  )
-- Strength before recency. A case sharing this one's IRB protocol is working
-- on the same study; one sharing only its department is in the same building.
-- Ordering by recency put ten of the second above two of the first, and the
-- reason was a label at the end of the row rather than the thing that ranked
-- it — so the strongest matches in a 23-case list were the hardest to find.
ORDER BY
  (a.irb IS NOT NULL AND {IRB} = a.irb) DESC,
  (a.pi IS NOT NULL AND {PI} = a.pi) DESC,
  last_activity DESC NULLS LAST
LIMIT @row_limit"""
    return sql, [
        ScalarQueryParameter("case_number", "STRING", case_number),
        ScalarQueryParameter("row_limit", "INT64", limit),
    ]


# --------------------------------------------------------------------------
# Operational lists (v2.1)
# --------------------------------------------------------------------------

# The ceiling on a single fetch. Only the CSV export asks for this many now;
# the screen asks a page at a time.
TRIAGE_LIMIT = 500

# One screen of rows. A triage list is read top-down, so the cost of a page
# turn (one ~31 MB job, cached for the TTL) buys a page that renders in a
# webview instead of 500 rows of DOM the user scrolls past once.
TRIAGE_PAGE_SIZE = 50

# Sort keys are an allowlist mapped to SQL, never the clicked column name
# interpolated into the query. A header click is user input like any other.
TRIAGE_SORTS = {
    "case_number": "c.case_number",
    "owner": "owner",
    "status": "c.status",
    "pi": "pi",
    "department": "department",
    "irb": "irb",
    "funding": "funding",
    "last_activity": "last_activity",
    "created_at": "c.created_at",
}

DEFAULT_TRIAGE_SORT = "last_activity"


@dataclass
class TriageFilters:
    """The five priority filters from spec FR-LIST-6, plus funding and owner.

    `open_only` defaults on because the landing view is a triage queue, not an
    archive browse.

    `owners` is the one dimension the spec does not name — D22. It is listed
    first among them, here and in the filter row, because "whose is it" is the
    question a queue gets asked before "what state is it in".
    """

    open_only: bool = True
    owners: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    pis: list[str] = field(default_factory=list)
    irbs: list[str] = field(default_factory=list)
    funding: list[str] = field(default_factory=list)

    def clauses(self) -> tuple[list[str], list[Any]]:
        sql: list[str] = []
        params: list[Any] = []
        if self.open_only:
            sql.append("NOT c.is_closed")
        if self.owners:
            sql.append(f"{OWNER} IN UNNEST(@f_owner)")
            params.append(ArrayQueryParameter("f_owner", "STRING", self.owners))
        if self.statuses:
            sql.append("c.status IN UNNEST(@f_status)")
            params.append(ArrayQueryParameter("f_status", "STRING", self.statuses))
        if self.departments:
            sql.append(f"{DEPARTMENT} IN UNNEST(@f_dept)")
            params.append(ArrayQueryParameter("f_dept", "STRING", self.departments))
        if self.pis:
            sql.append(f"{PI} IN UNNEST(@f_pi)")
            params.append(ArrayQueryParameter("f_pi", "STRING", self.pis))
        if self.irbs:
            sql.append(f"{IRB} IN UNNEST(@f_irb)")
            params.append(ArrayQueryParameter("f_irb", "STRING", self.irbs))
        if self.funding:
            sql.append(f"{FUNDING} IN UNNEST(@f_funding)")
            params.append(ArrayQueryParameter("f_funding", "STRING", self.funding))
        return sql, params

    @property
    def active_count(self) -> int:
        """How many filters are narrowing the list, for the collapsed chip label."""
        return sum(
            1
            for value in (
                self.owners,
                self.statuses,
                self.departments,
                self.pis,
                self.irbs,
                self.funding,
            )
            if value
        )


def triage_list(
    era: Era,
    filters: TriageFilters | None = None,
    *,
    sort: str = DEFAULT_TRIAGE_SORT,
    descending: bool = True,
    limit: int = TRIAGE_LIMIT,
    offset: int = 0,
) -> tuple[str, list[Any]]:
    """One row per case for the operational lists.

    Reads only the case dimension and the raw Case/User objects — no body
    scan — so a triage list costs roughly 31 MB rather than the 245 MB a
    conversation search does.

    Paging is done here rather than by slicing a fetched window, for the same
    reason sorting is: a window is not the result set. `total_matches` comes
    from `COUNT(*) OVER ()`, which is evaluated before `LIMIT` and `OFFSET`, so
    it counts every matching case and not the page — which is what makes
    "page 3 of 7" mean anything.
    """
    filters = filters or TriageFilters()
    cases = era.table("dim_case")
    where, params = filters.clauses()
    params.append(ScalarQueryParameter("row_limit", "INT64", limit))
    params.append(ScalarQueryParameter("row_offset", "INT64", max(0, offset)))

    column = TRIAGE_SORTS.get(sort, TRIAGE_SORTS[DEFAULT_TRIAGE_SORT])
    direction = "DESC" if descending else "ASC"

    sql = f"""SELECT
  c.case_number,
  c.subject,
  {OWNER} AS owner,
  c.status,
  c.is_closed,
  {PI} AS pi,
  {DEPARTMENT} AS department,
  {IRB} AS irb,
  {FUNDING} AS funding,
  c.description,
  {LAST_ACTIVITY} AS last_activity,
  COUNT(*) OVER () AS total_matches
FROM {cases} c
LEFT JOIN `{config.USER_TABLE}` u ON u.Id = c.owner_id
{_RAW_JOIN}
{('WHERE ' + ' AND '.join(where)) if where else ''}
ORDER BY {column} {direction} NULLS LAST, c.case_number DESC
LIMIT @row_limit OFFSET @row_offset"""
    return sql, params
