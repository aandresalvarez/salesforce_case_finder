"""BigQuery access: one client, every query parameterized, every job capped.

Two rules hold everywhere in this module:

1. User input is never formatted into SQL text. It travels as a query
   parameter. The only thing user input can influence about the SQL *string* is
   how many `@t0, @t1, ...` placeholders appear in it.
2. Every job carries `maximum_bytes_billed`. If a query would scan more than the
   cap, BigQuery refuses to start it. A mistake then costs nothing rather than
   an unbounded amount.
3. Query text the app did not write is judged read-only by BigQuery's own
   parser, not by a regex over the text. See `assert_read_only` and
   `_assert_is_a_query` for why the regex alone was both too strict and, in
   principle, too weak.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from google.cloud import bigquery
from google.cloud.bigquery import ScalarQueryParameter

from . import config


class AuthError(RuntimeError):
    """Raised when there are no usable credentials, with how to fix it."""


class CostError(RuntimeError):
    """Raised when a query would scan more than the configured cap."""


class QueryTimeout(RuntimeError):
    """Raised when BigQuery cancelled a query for running past the time ceiling."""


_CLIENT: bigquery.Client | None = None
# Pages warm several independent queries at once (see `data.prefetch`), so the
# first request of the app's life can arrive on two threads at the same moment.
_CLIENT_LOCK = threading.Lock()


def get_client() -> bigquery.Client:
    """Return a cached BigQuery client built from Application Default Credentials.

    ADC means the app uses whoever is logged in on this machine. There is no
    service-account key to distribute, and BigQuery's own IAM decides what each
    person can see — the app grants nothing.
    """
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            try:
                _CLIENT = bigquery.Client(project=config.BILLING_PROJECT)
            except Exception as exc:
                raise AuthError(
                    "Could not find Google Cloud credentials.\n\n"
                    "Run this once in a terminal, then restart the app:\n\n"
                    "    gcloud auth application-default login\n"
                ) from exc
    return _CLIENT


def check_access() -> tuple[bool, str]:
    """Cheap probe used by the UI on startup to give a real error early.

    Reads one row from the case dimension. If credentials or grants are wrong
    the user finds out on the landing screen with instructions, instead of
    hitting a stack trace after typing a search.
    """
    era = config.ERAS[config.DEFAULT_ERA]
    try:
        client = get_client()
        job = client.query(
            f"SELECT case_number FROM {era.table('dim_case')} LIMIT 1",
            # Same two ceilings as every other job. A probe that can hang is a
            # startup screen that can hang, with no UI drawn yet to say why.
            job_config=bigquery.QueryJobConfig(
                maximum_bytes_billed=config.MAX_BYTES_BILLED,
                job_timeout_ms=config.QUERY_TIMEOUT_SECONDS * 1000,
            ),
        )
        list(job.result())
        return True, f"Connected to {config.PROJECT} as {_whoami(client)}"
    except AuthError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, (
            f"Connected, but the query failed:\n\n{exc}\n\n"
            "This usually means the account is authenticated but has not been "
            f"granted BigQuery access to {config.PROJECT}."
        )


def _whoami(client: bigquery.Client) -> str:
    """Best-effort display of the identity in use; never fatal.

    Only a service-account email is reported directly. User ADC credentials do
    not carry the address on the object, and the quota project that sits there
    instead is not an identity — showing it would tell the user they are signed
    in as something they are not.
    """
    creds = getattr(client, "_credentials", None)
    email = getattr(creds, "service_account_email", None)
    if isinstance(email, str) and email and "@" in email:
        return email
    return "your signed-in account"


@dataclass
class QueryResult:
    rows: list[dict[str, Any]]
    bytes_processed: int
    cache_hit: bool

    @property
    def usd(self) -> float:
        return (self.bytes_processed / 1024**4) * config.USD_PER_TIB

    @property
    def cost_note(self) -> str:
        if self.cache_hit:
            return "served from BigQuery's cache — free"
        mb = self.bytes_processed / 1024**2
        if self.usd < 0.01:
            return f"scanned {mb:,.0f} MB (under a cent)"
        return f"scanned {mb:,.0f} MB (~${self.usd:,.2f})"


def _job_config(
    params: Sequence[ScalarQueryParameter] | None, dry_run: bool = False
) -> bigquery.QueryJobConfig:
    cfg = bigquery.QueryJobConfig(
        query_parameters=list(params or []),
        use_query_cache=True,
    )
    # The cap must be left unset on a dry run rather than set to None: the
    # client serializes an explicit None as the string "None", which BigQuery
    # rejects as an invalid INT64. A dry run scans nothing, so it needs no cap.
    if dry_run:
        cfg.dry_run = True
    else:
        cfg.maximum_bytes_billed = config.MAX_BYTES_BILLED
        # The byte cap bounds what a query scans, not how long it runs — see the
        # note on QUERY_TIMEOUT_SECONDS. Both bounds are needed.
        cfg.job_timeout_ms = config.QUERY_TIMEOUT_SECONDS * 1000
    return cfg


@dataclass(frozen=True)
class DryRun:
    """What BigQuery says about a query it has planned but not run.

    Two answers come back from the same free round trip, and both are needed
    before free-form text is allowed to execute: how much it would scan, and
    what kind of statement BigQuery parsed it as.
    """

    bytes_processed: int
    statement_type: str | None


def dry_run(sql: str, params: Sequence[ScalarQueryParameter] | None = None) -> DryRun:
    """Plan a query without running it. Costs nothing and scans nothing.

    Safe to call on text that has not been proved read-only: a dry run parses
    and plans, and does not execute — which is what makes it usable as the
    read-only check rather than only as the cost check.
    """
    job = get_client().query(sql, job_config=_job_config(params, dry_run=True))
    return DryRun(
        bytes_processed=int(job.total_bytes_processed or 0),
        # `getattr` rather than attribute access: the field is populated by the
        # API, and a client old enough not to surface it should degrade to the
        # syntactic guard rather than crash.
        statement_type=getattr(job, "statement_type", None),
    )


def plan(sql: str, params: Sequence[ScalarQueryParameter] | None = None) -> DryRun:
    """Dry-run query text the app did not write, and refuse a non-query.

    The single entry point for untrusted SQL: one free round trip that answers
    both questions the caller has to ask before executing it. `run(preflight=)`
    and the SQL page's cost button both come through here, so neither can
    acquire the cost check without the read-only check.

    `dry_run` is the unguarded half and stays that way on purpose — it is how
    the app measures the cost of queries it wrote itself, where there is
    nothing to guard against. Nothing should reach it with text a user typed;
    that is what this function is for.
    """
    planned = dry_run(sql, params)
    _assert_is_a_query(planned.statement_type)
    return planned


def run(
    sql: str,
    params: Sequence[ScalarQueryParameter] | None = None,
    *,
    preflight: bool = False,
) -> QueryResult:
    """Execute a parameterized query and return plain Python rows.

    Rows come back as dicts rather than a DataFrame so that nothing depends on
    pandas extension dtypes for BigQuery's TIMESTAMP/NUMERIC types — a common
    source of install-time breakage on Windows.

    `preflight=True` dry-runs first and raises CostError before spending
    anything. Used for the free-form SQL and natural-language paths, where the
    query text is not one we wrote.
    """
    if preflight:
        # `plan` refuses a non-query before the cost is even considered. Both
        # outcomes stop the job, but "this is not a query" is the more specific
        # thing we know, and a mutation that happened to be large should not be
        # reported to the user as an expense.
        planned = plan(sql, params)
        if planned.bytes_processed > config.MAX_BYTES_BILLED:
            raise CostError(
                f"This query would scan {planned.bytes_processed / 1024**3:,.1f} GB, "
                f"over the {config.MAX_BYTES_BILLED / 1024**3:,.1f} GB safety cap. "
                "Narrow it with a date range or a more specific filter."
            )

    job = get_client().query(sql, job_config=_job_config(params))
    try:
        iterator = job.result()
    except Exception as exc:
        # BigQuery reports a `job_timeout_ms` expiry as a cancellation, which
        # reads to a user as "something went wrong" rather than "your query was
        # too slow". Translating it here is the only place that knows a ceiling
        # was set at all.
        if _looks_like_timeout(exc):
            raise QueryTimeout(
                f"That query ran for more than {config.QUERY_TIMEOUT_SECONDS} seconds "
                "and was stopped. It was not a lot of data to scan, so the cost "
                "guard did not catch it — a join that multiplies rows is the "
                "usual cause. Narrow it, or aggregate instead of selecting rows."
            ) from exc
        raise
    rows = [dict(row.items()) for row in iterator]
    return QueryResult(
        rows=rows,
        bytes_processed=int(job.total_bytes_processed or 0),
        cache_hit=bool(job.cache_hit),
    )


def _looks_like_timeout(exc: Exception) -> bool:
    """Did this failure come from the job timeout rather than from the query?

    Matched on the message because the client raises the same exception class
    for a job that was cancelled by a person, by an admin, or by the ceiling
    set in `_job_config`, and only the text distinguishes them.
    """
    text = str(exc).lower()
    return "timed out" in text or ("cancel" in text and "timeout" in text)


# --------------------------------------------------------------------------
# Read-only enforcement for query text the app did not write
# --------------------------------------------------------------------------
#
# Two checks, in this order, because they answer different questions:
#
#   `assert_read_only`   — syntactic, free, and runs before anything is sent.
#                          Its job is to refuse the obvious with a message that
#                          names the problem, without a round trip.
#   `_assert_is_a_query` — authoritative. BigQuery parses the statement during
#                          the dry run `run(preflight=True)` already pays for,
#                          and reports what it parsed. That verdict decides.
#
# The syntactic check used to be the only one, and scanning raw text for
# keywords cannot tell a statement from a string that merely contains its name.
# It refused `WHERE STRPOS(LOWER(body_clean), 'update') > 0` — a search for the
# word "update", which on a support-case corpus is an ordinary thing to want —
# and `status = 'Call scheduled'`, and any literal holding a semicolon. Worse
# for the Ask page, whose prompt tells the model to write exactly that shape:
# the app generated valid SQL and then refused its own output as a mutation.
#
# Blanking literals before the scan fixes those. Handing the final say to the
# parser is what stops the next such gap from mattering — and it closes one the
# regex never covered, since a multi-statement script reaches BigQuery as a
# single job whose statement type is SCRIPT rather than SELECT.

# Every one of these begins a statement in GoogleSQL and none of them is also
# the name of a function, which is the test for belonging here. `REPLACE` used
# to be on the list and is not a statement at all: it is a string function, and
# a modifier of `SELECT *`. It refused `SELECT REPLACE(body_clean, 'x', 'y')`
# and `SELECT * REPLACE (LOWER(status) AS status) FROM t`, neither of which
# blanking literals helps with, because the keyword is genuinely in the
# statement. `CREATE OR REPLACE ...` is still refused, on the `CREATE`.
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|"
    r"EXPORT|LOAD|CALL|BEGIN|COMMIT|ROLLBACK)\b",
    re.IGNORECASE,
)

# The characters that may precede a quote and still belong to the literal:
# `r` for raw, `b` for bytes, in either case and either order.
_STRING_PREFIX = "rbRB"


def assert_read_only(sql: str) -> None:
    """Reject anything that is not a single read, cheaply and before sending.

    The credentials the app runs under may well be able to write. Nothing in
    this app ever should, so mutations are refused here rather than relying on
    every user having read-only grants.

    This is a pre-filter, not the verdict — `_assert_is_a_query` has the last
    word once BigQuery has parsed the text. Keeping the cheap check means a
    pasted `DELETE FROM dim_case` is refused without a round trip to a
    warehouse holding a writable credential, and with a message naming the
    keyword rather than quoting a parser.
    """
    stripped = _scrub(sql).strip().rstrip(";").strip()
    if not stripped:
        raise ValueError("Empty query.")
    if ";" in stripped:
        raise ValueError("Only one statement at a time, please.")
    # Keyword before shape. Both rules refuse exactly the same set of queries in
    # either order, but the failure matrix in spec section 12 asks a mutation to
    # be told which keyword was the problem, and checking the SELECT prefix
    # first would answer `DELETE FROM dim_case` with "only SELECT is allowed" —
    # true, unhelpful, and the less specific of the two things we know.
    found = _FORBIDDEN.search(stripped)
    if found:
        raise ValueError(
            f"'{found.group(0).upper()}' is not allowed — this app is read-only."
        )
    if not re.match(r"^(SELECT|WITH)\b", stripped, re.IGNORECASE):
        raise ValueError("Only SELECT queries are allowed.")


def _assert_is_a_query(statement_type: str | None) -> None:
    """Refuse anything BigQuery did not parse as a query.

    `statement_type` comes back from the dry run, so this costs nothing and is
    exact where the keyword scan is an approximation: BigQuery is the only
    party here that actually parses SQL.

    `None` is not a failing verdict. It means the client did not report a type,
    and the syntactic guard has already passed by the time this runs — so an
    unavailable answer falls back to that rather than refusing a query for a
    reason nobody can see.
    """
    if statement_type is None or statement_type.upper() == "SELECT":
        return
    kind = statement_type.replace("_", " ").upper()
    raise ValueError(
        f"BigQuery reads that as a {kind} statement rather than a query — "
        "this app is read-only."
    )


def _scrub(sql: str) -> str:
    """Blank out comments, string literals and quoted identifiers in one pass.

    What comes back has the same statement *shape* and none of the content, so
    a keyword or a semicolon still visible in it is really part of the
    statement. Only ever used for inspection — the text sent to BigQuery is
    untouched.

    One pass rather than two regex passes, because comments and strings can
    each contain the other's opening marker and neither ordering is right.
    Stripping comments first cuts a legal one-line string that ends in a `--`
    into a statement and a comment; blanking strings first reads the apostrophe
    in `-- it's fine` as a quote and swallows the line after it. A scanner that
    takes whichever construct starts first has no such ordering to get wrong.

    An unterminated quote or backtick ends the scan: everything from it to the
    end of the input is emitted verbatim, so every keyword and separator after
    it stays visible to the checks. Continuing to scan would be worse than
    useless — a later `#` would be read as a comment and would hide the rest of
    the text, which is how `SELECT * FROM `t#a ; DROP TABLE u` slipped past.
    Text with an unbalanced quote is not valid SQL anyway; the only question is
    which way the guard fails on it, and this way is towards refusing.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ")
            continue
        # `#` is a line comment in GoogleSQL as well as `--`, and was not
        # handled before: `SELECT 1 # update later` was refused as an UPDATE.
        # Ended by either newline character, because a lone `\r` ends a line on
        # anything that came off a Windows editor via a clipboard.
        if sql.startswith("--", i) or sql[i] == "#":
            end = _end_of_line(sql, i)
            i = n if end == -1 else end
            out.append(" ")
            continue
        if sql[i] == "`":
            end = sql.find("`", i + 1)
            if end == -1:
                out.append(sql[i:])
                break
            out.append("``")
            i = end + 1
            continue
        if sql[i] in "'\"" or _looks_like_a_prefixed_string(sql, i):
            end = _end_of_string(sql, i)
            if end is None:
                out.append(sql[i:])
                break
            out.append("''")
            i = end
            continue
        out.append(sql[i])
        i += 1
    return "".join(out)


def _end_of_line(sql: str, start: int) -> int:
    """Index of the next line break of either kind, or -1."""
    breaks = [sql.find(ch, start) for ch in ("\n", "\r")]
    found = [i for i in breaks if i != -1]
    return min(found) if found else -1


def _looks_like_a_prefixed_string(sql: str, i: int) -> bool:
    """Whether a literal with an r/b prefix starts here, e.g. `r'...'`."""
    j = i
    while j < i + 2 and j < len(sql) and sql[j] in _STRING_PREFIX:
        j += 1
    return j > i and j < len(sql) and sql[j] in "'\""


def _end_of_string(sql: str, start: int) -> int | None:
    """Index just past the string literal beginning at `start`, or None.

    Triple quotes are tested before single ones, so a triple-quoted literal
    containing a lone quote is read as one literal rather than as an empty one
    followed by loose text. A backslash escapes the next character unless the
    literal is raw, which is exactly when BigQuery says it does not.
    """
    i = start
    while i < start + 2 and i < len(sql) and sql[i] in _STRING_PREFIX:
        i += 1
    if i >= len(sql) or sql[i] not in "'\"":
        return None
    raw = "r" in sql[start:i].lower()
    quote = sql[i]
    delimiter = quote * 3 if sql.startswith(quote * 3, i) else quote
    j = i + len(delimiter)
    while j < len(sql):
        if sql[j] == "\\" and not raw:
            j += 2
            continue
        if len(delimiter) == 1 and sql[j] in "\n\r":
            return None  # a singly-quoted literal cannot span lines
        if sql.startswith(delimiter, j):
            return j + len(delimiter)
        j += 1
    return None  # unterminated
