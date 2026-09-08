"""Configuration: projects, dataset "eras", and cost guardrails.

Everything the app needs to know about where the data lives is here, so that
pointing it at a different project or dataset is a one-line change rather than a
search-and-replace through the SQL.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Case Finder"
VERSION = "2.1.0"


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


# The project that is billed for queries and that holds the datasets. Both can
# be overridden by environment variable so a different site can reuse the app
# without editing code.
PROJECT = os.environ.get("CASEFINDER_PROJECT", "som-rit-phi-starr-dev")
BILLING_PROJECT = os.environ.get("CASEFINDER_BILLING_PROJECT", PROJECT)

# Salesforce's own User object, used to resolve the author of internal notes.
# CaseComment rows carry only actor_user_id, so without this join every internal
# note is authored by nobody.
USER_TABLE = f"{PROJECT}.salesforce_raw.User"

# The raw Case object. The modelled `dim_case` carries the conversation-shaped
# fields; the triage attributes support staff actually filter on — PI, IRB
# protocol, department, funding status — only exist on the raw object, so
# operational lists have to join back to it.
CASE_TABLE = f"{PROJECT}.salesforce_raw.Case"

# Hard ceiling on bytes billed per query. BigQuery kills the job rather than
# running it, so a runaway query costs nothing instead of a surprise. The
# heaviest legitimate query (full-text search over every conversation body)
# scans ~220 MB, so 4 GB is roughly 18x headroom.
MAX_BYTES_BILLED = int(os.environ.get("CASEFINDER_MAX_BYTES", 4 * 1024**3))

# Wall-clock ceiling per job, which is a different guarantee from the byte cap
# and not implied by it. Bytes billed measures input scanned; it says nothing
# about how long a query runs. `SELECT t.*, c.* FROM turns CROSS JOIN cases`
# scans 275 MB — comfortably under the cap, priced at a fraction of a cent by a
# dry run — and then materialises eleven billion rows. The byte cap lets it
# start, and a desktop app with no timeout waits for it forever with no way for
# the user to stop it.
#
# This is `job_timeout_ms`, so BigQuery cancels the job server-side. A
# client-side timeout would return control to the UI while leaving the query
# running and billing.
QUERY_TIMEOUT_SECONDS = int(os.environ.get("CASEFINDER_QUERY_TIMEOUT", 120))

# Cost per byte scanned, used only to show an estimate in the UI.
# BigQuery on-demand pricing is $6.25 per TiB at time of writing.
USD_PER_TIB = float(os.environ.get("CASEFINDER_USD_PER_TIB", 6.25))

# How long search results stay cached in the local process. Re-running the same
# search inside this window costs nothing and returns instantly.
CACHE_TTL_SECONDS = int(os.environ.get("CASEFINDER_CACHE_TTL", 900))

# Whether the natural-language mode is offered at all. Off by default: the
# feature is built and tested, but sending anything to a model is a decision a
# site makes deliberately rather than one it discovers already made. With this
# off there is no Ask destination, `/ask` redirects to Lists, and Settings does
# not name Vertex — so nothing in the interface invites a question that would
# reach a model.
#
# It gates the surface, not the safety. `ask.py` still sends only the question
# and a static schema, never case data, because a flag someone can flip must
# not be the thing standing between a corpus and a third party.
ASK_ENABLED = _flag("CASEFINDER_ASK", False)

# Vertex AI region for the optional natural-language mode.
VERTEX_LOCATION = os.environ.get("CASEFINDER_VERTEX_LOCATION", "us-central1")

# Which Gemini model to use, tried in order until one answers. Google retires
# model versions on its own schedule and availability differs per project and
# region, so a single hardcoded name is a guaranteed future outage. Setting
# CASEFINDER_VERTEX_MODEL pins one explicitly and skips the search.
VERTEX_MODEL = os.environ.get("CASEFINDER_VERTEX_MODEL")
VERTEX_MODEL_CANDIDATES = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-1.5-flash-002",
]


@dataclass(frozen=True)
class Era:
    """One searchable slice of the archive.

    The two slices are not the same shape. `salesforce_current` is a set of
    views over the post-2022 era and carries the full picture: conversation,
    audit history and attachments. `salesforce_marts` is the underlying pair of
    tables covering every case ever, but it has no history and no attachment
    tables. The UI reads `has_history` / `has_attachments` and simply omits
    those panels rather than showing an error.
    """

    key: str
    label: str
    dataset: str
    blurb: str
    has_history: bool
    has_attachments: bool
    approx_cases: int

    def table(self, name: str) -> str:
        return f"`{PROJECT}.{self.dataset}.{name}`"


ERAS: dict[str, Era] = {
    "current": Era(
        key="current",
        label="2022 onward (full detail)",
        dataset="salesforce_current",
        blurb=(
            "1,714 cases from 2022 onward. Includes the audit trail and file "
            "attachments as well as the conversation."
        ),
        has_history=True,
        has_attachments=True,
        approx_cases=1714,
    ),
    "archive": Era(
        key="archive",
        label="Everything ever (conversation only)",
        dataset="salesforce_marts",
        blurb=(
            "All 41,526 cases back to the beginning. Conversation and case "
            "fields only — the audit trail and attachments were not retained "
            "for the older era."
        ),
        has_history=False,
        has_attachments=False,
        approx_cases=41526,
    ),
}

DEFAULT_ERA = "current"

# A term that appears in nearly every case is not a search result, it is an
# email footer. Above this share of the corpus the UI says so out loud.
BOILERPLATE_WARN_RATIO = 0.5
BOILERPLATE_NOTE = (
    "Terms like “redcap” and “irb” sit in the email footer on almost every "
    "case, so the match count is not telling you anything."
)

# --------------------------------------------------------------------------
# v2.1 additions
# --------------------------------------------------------------------------

# The warehouse is batch-loaded, so a list can show a case as open after it was
# closed in live Salesforce. Past this age the lists say so in a banner rather
# than letting the user assume they are looking at today.
STALE_DAYS = int(os.environ.get("CASEFINDER_STALE_DAYS", 7))

# Facet values change far more slowly than case rows and carry no PHI, so they
# get their own longer cache window.
FACET_CACHE_TTL_SECONDS = int(os.environ.get("CASEFINDER_FACET_CACHE_TTL", 3600))

# How many entries each cache may hold before the least recently used is
# dropped. A ceiling on entries rather than on bytes: sizing a Python object
# graph is expensive and inaccurate, and a predictable limit is worth more here
# than a precise one. 150 result entries is a long day of searching and opening
# cases; the largest single entry is one case's whole conversation.
CACHE_MAX_ENTRIES = int(os.environ.get("CASEFINDER_CACHE_MAX_ENTRIES", 150))
FACET_CACHE_MAX_ENTRIES = int(os.environ.get("CASEFINDER_FACET_CACHE_MAX_ENTRIES", 32))

# How often expired entries are actually deleted rather than merely refused.
# The TTL decides what may be served; this decides how long a value that may no
# longer be served stays in memory, which for a PHI corpus is the number that
# matters. Set to 0 to disable the sweep.
CACHE_REAP_SECONDS = int(os.environ.get("CASEFINDER_CACHE_REAP_SECONDS", 60))

# Native desktop window vs. plain browser tab. Native is the product; the
# browser path exists so that a machine with a broken platform webview can
# still be supported.
NATIVE = _flag("CASEFINDER_NATIVE", True)

WINDOW_SIZE = (1280, 800)
MIN_WINDOW_SIZE = (1024, 700)

# Shared team presets ship with the app and are read-only from the UI.
VIEWS_PATH = Path(
    os.environ.get("CASEFINDER_VIEWS_PATH", Path(__file__).resolve().parent.parent / "views.json")
)


def personal_views_path() -> Path:
    """Where one user's own saved views live.

    Definitions only — filters, sort, and column choices. Never rows, bodies,
    snippets, or descriptions; see the saved-view rule in spec section 9.3.
    """
    override = os.environ.get("CASEFINDER_PERSONAL_VIEWS_PATH")
    if override:
        return Path(override)
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "CaseFinder"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home())) / "CaseFinder"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "casefinder"
    return base / "personal_views.json"
