"""BigQuery access: one client, every query parameterized, every job capped.

Two rules hold everywhere in this module:

1. User input is never formatted into SQL text. It travels as a query
   parameter. The only thing user input can influence about the SQL *string* is
   how many `@t0, @t1, ...` placeholders appear in it.
2. Every job carries `maximum_bytes_billed`. If a query would scan more than the
   cap, BigQuery refuses to start it. A mistake then costs nothing rather than
   an unbounded amount.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from google.cloud import bigquery
from google.cloud.bigquery import ScalarQueryParameter

from . import config


class AuthError(RuntimeError):
    """Raised when there are no usable credentials, with how to fix it."""


class CostError(RuntimeError):
    """Raised when a query would scan more than the configured cap."""


_CLIENT: bigquery.Client | None = None


def get_client() -> bigquery.Client:
    """Return a cached BigQuery client built from Application Default Credentials.

    ADC means the app uses whoever is logged in on this machine. There is no
    service-account key to distribute, and BigQuery's own IAM decides what each
    person can see — the app grants nothing.
    """
    global _CLIENT
    if _CLIENT is None:
        try:
            _CLIENT = bigquery.Client(project=config.BILLING_PROJECT)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
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
            job_config=bigquery.QueryJobConfig(
                maximum_bytes_billed=config.MAX_BYTES_BILLED
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
    return cfg


def estimate_bytes(sql: str, params: Sequence[ScalarQueryParameter] | None = None) -> int:
    """Return bytes a query would scan, without running it. Costs nothing."""
    job = get_client().query(sql, job_config=_job_config(params, dry_run=True))
    return int(job.total_bytes_processed or 0)


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
        planned = estimate_bytes(sql, params)
        if planned > config.MAX_BYTES_BILLED:
            raise CostError(
                f"This query would scan {planned / 1024**3:,.1f} GB, over the "
                f"{config.MAX_BYTES_BILLED / 1024**3:,.1f} GB safety cap. "
                "Narrow it with a date range or a more specific filter."
            )

    job = get_client().query(sql, job_config=_job_config(params))
    iterator = job.result()
    rows = [dict(row.items()) for row in iterator]
    return QueryResult(
        rows=rows,
        bytes_processed=int(job.total_bytes_processed or 0),
        cache_hit=bool(job.cache_hit),
    )


# --------------------------------------------------------------------------
# Read-only enforcement for query text the app did not write
# --------------------------------------------------------------------------

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|"
    r"REPLACE|EXPORT|LOAD|CALL|BEGIN|COMMIT|ROLLBACK)\b",
    re.IGNORECASE,
)


def assert_read_only(sql: str) -> None:
    """Reject anything that is not a single read.

    The credentials the app runs under may well be able to write. Nothing in
    this app ever should, so mutations are refused here rather than relying on
    every user having read-only grants.
    """
    stripped = _strip_sql_comments(sql).strip().rstrip(";").strip()
    if not stripped:
        raise ValueError("Empty query.")
    if ";" in stripped:
        raise ValueError("Only one statement at a time, please.")
    if not re.match(r"^(SELECT|WITH)\b", stripped, re.IGNORECASE):
        raise ValueError("Only SELECT queries are allowed.")
    found = _FORBIDDEN.search(stripped)
    if found:
        raise ValueError(
            f"'{found.group(0).upper()}' is not allowed — this app is read-only."
        )


def _strip_sql_comments(sql: str) -> str:
    """Remove comments so keywords cannot be smuggled past the check inside them."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql
