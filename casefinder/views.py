"""Saved views: filter definitions on disk, never case data.

This is the only module in the application that writes to disk, which makes it
the only place the "no PHI at rest" rule can be broken. So the rule is enforced
structurally rather than by care: `_PERSISTABLE` is an allowlist of keys, and
`SavedView.to_json` builds its output by walking that allowlist. A field cannot
end up in the file by being added to the dataclass — someone has to add it here
on purpose, next to the comment saying what the test is.

The distinction that matters: "cases where department = Cardiology" is a
definition and is safe to persist. The 40 cases that came back are results, and
are not. Persisting the first is the entire feature; persisting the second
would put PHI in a JSON file in the user's home directory.

Two tiers, both plain files:
  - shared presets ship with the app in `views.json` and are read-only here;
  - personal views live in the user's own config directory.
There is no server. Sharing a personal view means handing its JSON to the
maintainer, who puts it in the shared file.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config
from .queries import TriageFilters

# Keys that may be written to disk. Everything else is dropped on save and
# ignored on load.
#
# The test for adding one: could this value contain text a requester or a
# clinician typed? A status is a picklist value. A department is an org unit. A
# case description is free text written about a research subject's data, and so
# is anything derived from one — a snippet, a summary, a result row.
#
# `owners` passes that test the same way `pis` does. A case owner is a
# Salesforce User — a member of the support team, picked from a list, and
# already on screen in a column and in the metadata-only CSV. It is a person's
# name, which is why it is called out here rather than waved through, but it is
# not a research subject and not text anyone typed into a case.
_PERSISTABLE = (
    "open_only",
    "owners",
    "statuses",
    "departments",
    "pis",
    "irbs",
    "funding",
    "sort",
    "descending",
    "columns",
)

# Filter dimensions that may be persisted at all. Spec section 9.3 requires a
# way to withdraw one if it is later judged too sensitive for local disk: drop
# it from this tuple and existing files stop honouring it on load.
_PERSISTABLE_FILTERS = ("owners", "statuses", "departments", "pis", "irbs", "funding")

ALL_COLUMNS = (
    "case_number",
    "owner",
    "status",
    "pi",
    "department",
    "irb",
    "description",
    "last_activity",
    "funding",
)

# Spec FR-LIST-4. Funding is last because it is the first to be dropped at
# narrow widths.
DEFAULT_COLUMNS = ALL_COLUMNS


@dataclass
class SavedView:
    name: str
    filters: TriageFilters = field(default_factory=TriageFilters)
    sort: str = "last_activity"
    descending: bool = True
    columns: tuple[str, ...] = DEFAULT_COLUMNS
    shared: bool = False
    description: str = ""
    builtin: bool = False

    # -- serialisation ----------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        """Definition only. Built by walking the allowlist, not the dataclass."""
        source: dict[str, Any] = {
            "open_only": self.filters.open_only,
            "owners": list(self.filters.owners),
            "statuses": list(self.filters.statuses),
            "departments": list(self.filters.departments),
            "pis": list(self.filters.pis),
            "irbs": list(self.filters.irbs),
            "funding": list(self.filters.funding),
            "sort": self.sort,
            "descending": self.descending,
            "columns": list(self.columns),
        }
        payload = {"name": self.name}
        if self.description:
            payload["description"] = self.description
        for key in _PERSISTABLE:
            value = source.get(key)
            # Skip empty filter lists so a saved file stays readable by hand.
            if isinstance(value, list) and not value:
                continue
            payload[key] = value
        return payload

    @classmethod
    def from_json(cls, raw: dict[str, Any], *, shared: bool = False) -> SavedView:
        def strings(key: str) -> list[str]:
            if key not in _PERSISTABLE_FILTERS:
                return []
            value = raw.get(key) or []
            if not isinstance(value, list):
                return []
            return [str(v) for v in value if isinstance(v, str | int | float) and str(v).strip()]

        # A hand-edited file can name a column that no longer exists, so the
        # saved list is filtered against the real ones rather than trusted.
        columns = raw.get("columns")
        picked = (
            tuple(c for c in columns if c in ALL_COLUMNS)
            if isinstance(columns, list)
            else ()
        )

        return cls(
            name=str(raw.get("name") or "Untitled view"),
            description=str(raw.get("description") or ""),
            filters=TriageFilters(
                open_only=bool(raw.get("open_only", True)),
                owners=strings("owners"),
                statuses=strings("statuses"),
                departments=strings("departments"),
                pis=strings("pis"),
                irbs=strings("irbs"),
                funding=strings("funding"),
            ),
            sort=str(raw.get("sort") or "last_activity"),
            descending=bool(raw.get("descending", True)),
            columns=picked or DEFAULT_COLUMNS,
            shared=shared,
            builtin=bool(raw.get("builtin", False)),
        )

    def share_text(self) -> str:
        """The definition as pasteable JSON, for handing to the maintainer."""
        return json.dumps(self.to_json(), indent=2)

    @property
    def summary(self) -> str:
        """One line describing what this view narrows to."""
        parts: list[str] = ["Open only" if self.filters.open_only else "All statuses"]
        for label, values in (
            ("owner", self.filters.owners),
            ("status", self.filters.statuses),
            ("dept", self.filters.departments),
            ("PI", self.filters.pis),
            ("IRB", self.filters.irbs),
            ("funding", self.filters.funding),
        ):
            if values:
                shown = ", ".join(values[:2])
                if len(values) > 2:
                    shown += f" +{len(values) - 2}"
                parts.append(f"{label}: {shown}")
        return " · ".join(parts)


# --------------------------------------------------------------------------
# Built-in presets
# --------------------------------------------------------------------------
#
# These exist in code as well as in views.json so the app still has its landing
# view if the shared file is missing, unreadable, or edited into invalidity.

OPEN_CASES = SavedView(
    name="Open Cases (weekly review)",
    description="Everything not closed, most recently active first.",
    filters=TriageFilters(open_only=True),
    shared=True,
    builtin=True,
)

# Spec FR-LIST-8 names this preset; the warehouse does not. Nothing in the
# corpus is called "Data Broker" — not a status, not an owner, not a queue. The
# closest thing is the `Data Queue` status, which is what this filters on, and
# it currently holds three cases. That is either the right list and the queue is
# genuinely that small, or the real definition lives in a Salesforce list view
# that was never modelled. Spec SR-13 puts the answer with the data team; until
# then the description says so on screen rather than in a code comment nobody
# reads, so a user seeing three rows knows it is a question and not a bug.
DATA_BROKER = SavedView(
    name="Data Broker Triage",
    description="Provisional: cases in the Data Queue status. Definition pending confirmation.",
    filters=TriageFilters(open_only=True, statuses=["Data Queue"]),
    sort="created_at",
    descending=False,
    shared=True,
    builtin=True,
)


def builtin_views() -> list[SavedView]:
    return [OPEN_CASES, DATA_BROKER]


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------


def _read(path: Path) -> list[dict[str, Any]]:
    """Read a views file, treating any problem with it as "no views".

    A malformed shared file must not stop the application from starting; the
    user still gets the built-in presets and a working Lists page.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(raw, dict):
        raw = raw.get("views", [])
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def shared_views() -> list[SavedView]:
    """Team presets shipped with the app. Read-only from the UI."""
    found = [SavedView.from_json(item, shared=True) for item in _read(config.VIEWS_PATH)]
    if not found:
        return builtin_views()
    names = {view.name for view in found}
    return found + [v for v in builtin_views() if v.name not in names]


def personal_views() -> list[SavedView]:
    return [SavedView.from_json(item) for item in _read(config.personal_views_path())]


def all_views() -> list[SavedView]:
    """Shared first, personal second — spec FR-LIST-9."""
    return shared_views() + personal_views()


def find(name: str) -> SavedView | None:
    for view in all_views():
        if view.name == name:
            return view
    return None


def save_personal(view: SavedView) -> Path:
    """Write one personal view, replacing any existing view of the same name."""
    path = config.personal_views_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = [v for v in personal_views() if v.name != view.name]
    _write(path, [*existing, view])
    return path


def delete_personal(name: str) -> bool:
    path = config.personal_views_path()
    remaining = [v for v in personal_views() if v.name != name]
    if len(remaining) == len(personal_views()):
        return False
    _write(path, remaining)
    return True


def _write(path: Path, views: Iterable[SavedView]) -> None:
    payload = {
        "_comment": (
            "Case Finder saved views. Filter definitions only — this file must "
            "never contain case rows, message bodies, snippets, or descriptions."
        ),
        "views": [view.to_json() for view in views],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written via a temp file so an interrupted save cannot truncate the
    # existing views into an empty file.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
