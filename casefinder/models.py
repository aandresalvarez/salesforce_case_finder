"""Typed view models sitting between the query layer and the UI.

The query layer returns BigQuery rows as plain dicts. The UI should not reach
into those dicts by string key, because then a column rename in `queries.py`
becomes a silent blank in a table cell rather than an error. Everything the UI
renders is built here first, which gives one place to normalise the corpus's
particular flavours of "missing".

That normalisation matters more than it sounds. `dim_case` uses NULL for an
absent value, but the raw Salesforce Case object uses the empty string — 33,821
of 41,526 cases have `Project_Department__c = ''` rather than NULL. Treating
those as present would fill the triage list with blank cells that look like a
rendering bug, and would put an empty entry at the top of every filter dropdown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

MISSING = "—"

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _day(d: date | datetime) -> str:
    """`Aug 12, 2026`, built by hand.

    strftime's no-pad directive is spelled `%-d` on macOS and `%#d` on Windows,
    and the wrong one raises rather than degrading. This app ships to both, so
    it does not use either.
    """
    return f"{_MONTHS[d.month - 1]} {d.day}, {d.year}"


def _clock(t: datetime) -> str:
    hour = t.hour % 12 or 12
    return f"{hour}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def clean(value: Any) -> Any | None:
    """Collapse the corpus's several spellings of "no value" into None."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def show(value: Any) -> str:
    """Render a value for display, using an em dash where there is nothing."""
    cleaned = clean(value)
    if cleaned is None:
        return MISSING
    if isinstance(cleaned, datetime | date):
        return _day(cleaned)
    return str(cleaned)


def when(ts: datetime | None) -> str:
    """Timestamp for a comment or event header."""
    if ts is None:
        return MISSING
    return f"{_day(ts)} at {_clock(ts)}"


@dataclass(frozen=True)
class Snippet:
    turn_seq: int
    actor_role: str | None
    text: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Snippet:
        return cls(
            turn_seq=row.get("turn_seq") or 0,
            actor_role=clean(row.get("actor_role")),
            text=(row.get("text") or "").strip(),
        )


@dataclass(frozen=True)
class SearchHit:
    case_number: str
    subject: str | None
    status: str | None
    type: str | None
    origin_class: str | None
    created_at: datetime | None
    closed_at: datetime | None
    days_to_close: float | None
    turn_count: int
    matching_turns: int
    matched_case_fields: bool
    snippets: list[Snippet]
    total_matches: int

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> SearchHit:
        return cls(
            case_number=row["case_number"],
            subject=clean(row.get("subject")),
            status=clean(row.get("status")),
            type=clean(row.get("type")),
            origin_class=clean(row.get("origin_class")),
            created_at=row.get("created_at"),
            closed_at=row.get("closed_at"),
            days_to_close=row.get("days_to_close"),
            turn_count=row.get("turn_count") or 0,
            matching_turns=row.get("matching_turns") or 0,
            matched_case_fields=bool(row.get("matched_case_fields")),
            snippets=[Snippet.from_row(s) for s in (row.get("snippets") or [])],
            total_matches=row.get("total_matches") or 0,
        )

    @property
    def why_matched(self) -> str:
        """One plain sentence explaining why this case is in the results.

        "The phrase is in the subject line" and "the phrase is buried in reply
        four" are different findings, and the user should not have to work out
        which one they are looking at from a row of counts.
        """
        in_fields = self.matched_case_fields
        turns = self.matching_turns
        if in_fields and turns:
            plural = "s" if turns != 1 else ""
            return f"Matched the subject or description, and {turns} message{plural}."
        if in_fields:
            return "Matched the subject or description."
        if turns:
            return f"Matched {turns} message{'s' if turns != 1 else ''} in the conversation."
        return "Matched the current filters."


@dataclass(frozen=True)
class TriageRow:
    """One line of an operational list."""

    case_number: str
    subject: str | None
    owner: str | None
    status: str | None
    pi: str | None
    department: str | None
    irb: str | None
    funding: str | None
    description: str | None
    last_activity: datetime | None
    is_closed: bool
    total_matches: int

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> TriageRow:
        return cls(
            case_number=row["case_number"],
            subject=clean(row.get("subject")),
            owner=clean(row.get("owner")),
            status=clean(row.get("status")),
            pi=clean(row.get("pi")),
            department=clean(row.get("department")),
            irb=clean(row.get("irb")),
            funding=clean(row.get("funding")),
            description=clean(row.get("description")),
            last_activity=row.get("last_activity"),
            is_closed=bool(row.get("is_closed")),
            total_matches=row.get("total_matches") or 0,
        )


@dataclass(frozen=True)
class CaseHeader:
    case_id: str
    case_number: str
    subject: str | None
    status: str | None
    origin: str | None
    type: str | None
    reason: str | None
    priority: str | None
    owner: str | None
    pi: str | None
    department: str | None
    irb: str | None
    irb_status: str | None
    funding: str | None
    created_at: datetime | None
    closed_at: datetime | None
    last_activity: datetime | None
    days_to_close: float | None
    turn_count: int
    customer_turn_count: int
    agent_turn_count: int
    attachments: int | None
    description: str | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> CaseHeader:
        return cls(
            case_id=row["case_id"],
            case_number=row["case_number"],
            subject=clean(row.get("subject")),
            status=clean(row.get("status")),
            origin=clean(row.get("origin")),
            type=clean(row.get("type")),
            reason=clean(row.get("reason")),
            priority=clean(row.get("priority")),
            owner=clean(row.get("owner")),
            pi=clean(row.get("pi")),
            department=clean(row.get("department")),
            irb=clean(row.get("irb")),
            irb_status=clean(row.get("irb_status")),
            funding=clean(row.get("funding")),
            created_at=row.get("created_at"),
            closed_at=row.get("closed_at"),
            last_activity=row.get("last_activity"),
            days_to_close=row.get("days_to_close"),
            turn_count=row.get("turn_count") or 0,
            customer_turn_count=row.get("customer_turn_count") or 0,
            agent_turn_count=row.get("agent_turn_count") or 0,
            attachments=row.get("attachments"),
            description=clean(row.get("description")),
        )

    @property
    def age_days(self) -> int | None:
        if self.created_at is None:
            return None
        end = self.closed_at or datetime.now(timezone.utc)
        return max(0, (end - self.created_at).days)

    def metrics(self) -> list[tuple[str, str]]:
        """The quiet strip under the title — spec FR-CASE-2.

        One flat group of label/value pairs, deliberately not five cards.
        """
        out: list[tuple[str, str]] = []
        if self.status:
            out.append(("Status", self.status))
        if self.created_at:
            out.append(("Opened", show(self.created_at)))
        age = self.age_days
        if age is not None:
            out.append(("Age", f"{age:,} days"))
        out.append(("Messages", f"{self.turn_count:,}"))
        if self.attachments:
            out.append(("Files", f"{self.attachments:,}"))
        return out

    def extended(self) -> list[tuple[str, str]]:
        """Always-visible metadata — spec FR-CASE-3. Missing renders as an em dash."""
        rows = [
            ("Owner", self.owner),
            ("Type", self.type),
            ("Reason", self.reason),
            ("Came in via", self.origin),
            ("PI", self.pi),
            ("Department", self.department),
            ("IRB / protocol", self.irb),
            ("Funding", self.funding),
        ]
        # IRB status is the one field the spec asks for only "when populated".
        if self.irb_status:
            rows.append(("IRB status", self.irb_status))
        return [(label, show(value)) for label, value in rows]


@dataclass(frozen=True)
class Comment:
    """One entry in the comments-first reading stream."""

    turn_seq: int
    ts: datetime | None
    who: str | None
    actor_role: str | None
    source: str | None
    direction: str | None
    body: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Comment:
        return cls(
            turn_seq=row.get("turn_seq") or 0,
            ts=row.get("turn_ts"),
            who=clean(row.get("who")),
            actor_role=clean(row.get("actor_role")),
            source=clean(row.get("source_object")),
            direction=clean(row.get("direction")),
            body=(row.get("body") or "").strip(),
        )

    @property
    def author(self) -> str:
        return self.who or "Unknown"

    @property
    def kind(self) -> str:
        """A short human label for where this entry came from."""
        if self.source == "CaseComment":
            return "internal note"
        if self.direction == "inbound":
            return "email from requester"
        if self.direction == "outbound":
            return "email to requester"
        return self.direction or "message"


@dataclass(frozen=True)
class Message:
    turn_seq: int
    ts: datetime | None
    who: str | None
    actor_role: str | None
    direction: str | None
    source: str | None
    subject: str | None
    body: str
    body_len: int

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Message:
        return cls(
            turn_seq=row.get("turn_seq") or 0,
            ts=row.get("turn_ts"),
            who=clean(row.get("who")),
            actor_role=clean(row.get("actor_role")),
            direction=clean(row.get("direction")),
            source=clean(row.get("source_object")),
            subject=clean(row.get("subject")),
            body=(row.get("body") or "").strip(),
            body_len=row.get("body_len") or 0,
        )


@dataclass(frozen=True)
class TimelineEvent:
    seq: int
    ts: datetime | None
    kind: str
    what: str | None
    who: str | None
    detail: str | None
    body: str | None
    body_len: int | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> TimelineEvent:
        return cls(
            seq=row.get("seq") or 0,
            ts=row.get("ts"),
            kind=row.get("kind") or "event",
            what=clean(row.get("what")),
            who=clean(row.get("who")),
            detail=clean(row.get("detail")),
            body=clean(row.get("body")),
            body_len=row.get("body_len"),
        )

    @property
    def is_message(self) -> bool:
        return self.kind == "message"


@dataclass(frozen=True)
class Attachment:
    file_name: str | None
    mb: float | None
    gcs_uri: str | None
    console_url: str | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Attachment:
        return cls(
            file_name=clean(row.get("file_name")),
            mb=row.get("mb"),
            gcs_uri=clean(row.get("gcs_uri")),
            console_url=clean(row.get("console_url")),
        )

    @property
    def size(self) -> str:
        if self.mb is None:
            return MISSING
        if self.mb < 1:
            return f"{self.mb * 1024:,.0f} KB"
        return f"{self.mb:,.1f} MB"


@dataclass(frozen=True)
class RelatedCase:
    case_number: str
    subject: str | None
    status: str | None
    last_activity: datetime | None
    same_pi: bool
    same_irb: bool
    same_department: bool

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> RelatedCase:
        return cls(
            case_number=row["case_number"],
            subject=clean(row.get("subject")),
            status=clean(row.get("status")),
            last_activity=row.get("last_activity"),
            same_pi=bool(row.get("same_pi")),
            same_irb=bool(row.get("same_irb")),
            same_department=bool(row.get("same_department")),
        )

    @property
    def why(self) -> str:
        reasons = []
        if self.same_pi:
            reasons.append("same PI")
        if self.same_irb:
            reasons.append("same IRB")
        if self.same_department:
            reasons.append("same department")
        return ", ".join(reasons) or "related"


@dataclass(frozen=True)
class Freshness:
    """How far behind live Salesforce the warehouse snapshot is."""

    newest: datetime | None
    open_cases: int
    total_cases: int
    stale_days: int

    @classmethod
    def from_row(cls, row: dict[str, Any], stale_days: int) -> Freshness:
        return cls(
            newest=row.get("newest"),
            open_cases=row.get("open_cases") or 0,
            total_cases=row.get("total_cases") or 0,
            stale_days=stale_days,
        )

    @property
    def age_days(self) -> int | None:
        if self.newest is None:
            return None
        return max(0, (datetime.now(timezone.utc) - self.newest).days)

    @property
    def is_stale(self) -> bool:
        age = self.age_days
        return age is not None and age > self.stale_days

    @property
    def label(self) -> str:
        """The `Data as of ...` line every operational list must carry."""
        if self.newest is None:
            return "Warehouse freshness unknown"
        age = self.age_days or 0
        return f"Data as of {show(self.newest)} · {age:,} day{'s' if age != 1 else ''} old"

    @property
    def warning(self) -> str:
        return (
            f"This snapshot is {self.age_days:,} days old. A case may show as open "
            "here after it was closed in Salesforce."
        )


@dataclass
class Facets:
    """Values available to the filter controls, plus the corpus date bounds."""

    statuses: list[str] = field(default_factory=list)
    origin_classes: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    pis: list[str] = field(default_factory=list)
    irbs: list[str] = field(default_factory=list)
    min_date: date | None = None
    max_date: date | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Facets:
        def strings(key: str) -> list[str]:
            return [v for v in (row.get(key) or []) if clean(v) is not None]

        return cls(
            statuses=strings("statuses"),
            origin_classes=strings("origin_classes"),
            types=strings("types"),
            departments=strings("departments"),
            pis=strings("pis"),
            irbs=strings("irbs"),
            min_date=row.get("min_date"),
            max_date=row.get("max_date"),
        )
