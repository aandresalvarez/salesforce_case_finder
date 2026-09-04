"""Configuration: projects, dataset "eras", and cost guardrails.

Everything the app needs to know about where the data lives is here, so that
pointing it at a different project or dataset is a one-line change rather than a
search-and-replace through the SQL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# The project that is billed for queries and that holds the datasets. Both can
# be overridden by environment variable so a different site can reuse the app
# without editing code.
PROJECT = os.environ.get("CASEFINDER_PROJECT", "som-rit-phi-starr-dev")
BILLING_PROJECT = os.environ.get("CASEFINDER_BILLING_PROJECT", PROJECT)

# Salesforce's own User object, used to resolve the author of internal notes.
# CaseComment rows carry only actor_user_id, so without this join every internal
# note is authored by nobody.
USER_TABLE = f"{PROJECT}.salesforce_raw.User"

# Hard ceiling on bytes billed per query. BigQuery kills the job rather than
# running it, so a runaway query costs nothing instead of a surprise. The
# heaviest legitimate query (full-text search over every conversation body)
# scans ~220 MB, so 4 GB is roughly 18x headroom.
MAX_BYTES_BILLED = int(os.environ.get("CASEFINDER_MAX_BYTES", 4 * 1024**3))

# Cost per byte scanned, used only to show an estimate in the UI.
# BigQuery on-demand pricing is $6.25 per TiB at time of writing.
USD_PER_TIB = float(os.environ.get("CASEFINDER_USD_PER_TIB", 6.25))

# How long search results stay cached in the local process. Re-running the same
# search inside this window costs nothing and returns instantly.
CACHE_TTL_SECONDS = int(os.environ.get("CASEFINDER_CACHE_TTL", 900))

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
