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

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

MISSING = "—"

# Also read by the case page, which marks each change of month in a long
# thread. Kept here beside `_day` so the two never drift into different
# spellings of the same month.
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


# Roughly four lines of the widest the description column ever gets. The CSS
# clamp decides where the text visually stops; this decides how much of it is
# worth sending, and keeps a list of case bodies from being a megabyte of
# markup the user never sees.
PREVIEW_CHARS = 260

# The mail client's attribution line for the message being quoted:
# `On Apr 23, 2026 at 4:57 PM Dana Whitfield (dana.whitfield@example.com) wrote:`
# — the shape, with a synthetic requester; this file is public and the corpus
# it describes is not.
# Nearly every case description in the corpus opens with one, which is why the
# first version of the description column showed a requester's email address on
# every row and told the reader nothing about any case. The length bound is
# what keeps this from eating a paragraph: a real attribution is a date, a
# name, and an address, and prose that happens to start with "On" and contain
# "wrote:" further along is left alone.
_ATTRIBUTION = re.compile(r"^On\b.{0,110}?\bwrote:\s*", re.IGNORECASE)


def strip_attribution(text: str, *, rounds: int = 2) -> str:
    """Drop leading quoted-reply headers, leaving the message itself.

    Twice by default, because a forwarded request arrives quoted inside a reply
    and the second attribution is the one in front of the actual text. Bounded
    rather than looped: three deep and it is a mail thread, not a request.

    Only ever strips when something is left behind. A body that is *nothing
    but* an attribution is a strange record, but returning empty for it would
    hide the only thing it has.
    """
    for _ in range(rounds):
        stripped = _ATTRIBUTION.sub("", text, count=1)
        if not stripped:
            break
        text = stripped
    return text


# Line breaks that arrived as text rather than as characters.
#
# The web intake form serialises itself into a case body as JSON, so every
# newline the requester typed is stored as the two characters `\` and `n` —
# `intake.py` decodes them when it recognises the payload, which is why a case
# page reads correctly. A search snippet is cut out of the middle of that same
# body with SUBSTR and never reaches the parser, so it arrived on screen as
# `...quality of care outcomes\n\nQuestion: Would like to request an update...`
# with the escapes showing, in prose that is otherwise perfectly readable.
#
# Only previews are treated this way. A snippet and a list description are one
# flowing line, so a break becomes a space; the full body on the case page is
# left exactly as the record has it, because someone acting on a case has to be
# able to see what it literally says — a body that really does contain a
# backslash and an `n`, such as pasted code, is then still telling the truth.
_ESCAPED_BREAK = re.compile(r"\\(?:r\\n|[rnt])")

# Field labels the intake path leaves at the front of a description. `Summary:`
# sits in front of very nearly every one, so the first nine characters of the
# Description column were identical on every row — in the one column FR-LIST-4
# refuses to let drop at narrow widths, which makes them the most expensive
# nine characters on the screen.
#
# An allowlist rather than a general `Word:` rule. A description opening
# `Question:` or `Availability:` is answering something, and the label is the
# only thing that says what; these three are the form's own field names and
# carry nothing the column heading does not already say.
_LEADING_LABEL = re.compile(r"^(?:Summary|Description|Subject)\s*:\s*", re.IGNORECASE)


def flatten(text: str) -> str:
    """One line of prose: escaped breaks to spaces, whitespace collapsed."""
    return " ".join(_ESCAPED_BREAK.sub(" ", text).split())


def strip_leading_label(text: str) -> str:
    """Drop a form field name from the front, if that is all it is.

    Only ever strips when something is left behind, for the same reason
    `strip_attribution` does: a description that is *nothing but* a label is a
    strange record, and showing an empty cell for it would be a worse answer
    than showing what is there.
    """
    stripped = _LEADING_LABEL.sub("", text, count=1).lstrip()
    return stripped or text


def preview(text: Any, limit: int = PREVIEW_CHARS) -> str:
    """Flatten a free-text field into one line for a table cell.

    Case descriptions are pasted email: an attribution line, header blocks,
    blank lines, quoted replies, a signature. Rendered verbatim in a table they
    are the whole row — and a two-line clamp on the raw text is no help either,
    because the two lines it keeps are `From:` and an empty one. Collapsing the
    whitespace and dropping the attribution is what makes the clamp show two
    lines about the case.

    The quote is only stripped when there is something behind it. A description
    that is *nothing but* an attribution line is a strange case, but showing an
    empty cell for it would be a worse answer than showing what is there.

    Deliberately not `show()`: an em dash for a missing description is noise in
    a column that is a preview rather than a fact.
    """
    cleaned = clean(text)
    if cleaned is None:
        return ""
    flattened = strip_leading_label(strip_attribution(flatten(str(cleaned))))
    if len(flattened) <= limit:
        return flattened
    return flattened[:limit].rstrip() + "…"


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
            # Flattened here rather than at the drawing site, so the dedupe in
            # `_distinct` compares what the reader will actually see.
            text=flatten(row.get("text") or ""),
        )


def _distinct(snippets: Iterable[Snippet]) -> list[Snippet]:
    """Drop snippets whose text repeats one already kept.

    Email quotes the message it replies to, so consecutive turns of a thread
    contain the same paragraph and the window cut around a match in it is
    byte-identical. The search page showed two snippets per hit and, for very
    nearly every hit in the corpus, they were the same two hundred characters
    printed twice — which reads as a rendering bug and costs a result card half
    its height for nothing.

    Deduplicated here rather than in SQL because `matching_turns` is a count of
    the turns that matched and must stay one: thirty-five messages did mention
    the term, even if they were quoting each other while doing it.
    """
    seen: set[str] = set()
    out: list[Snippet] = []
    for snippet in snippets:
        if snippet.text in seen:
            continue
        seen.add(snippet.text)
        out.append(snippet)
    return out


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
            snippets=_distinct(Snippet.from_row(s) for s in (row.get("snippets") or [])),
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

    def about(self) -> list[tuple[str, str]]:
        """What the rail carries: everything the identity bar does not, and
        nothing that has no value.

        Status, owner and age moved into the bar that follows the reader down a
        long thread, so repeating them here would be the redundancy this page
        was rebuilt to remove.

        The em dashes go too, which is a departure from FR-CASE-3. That rule is
        right for the grid it was written for: four attributes across a reading
        column, in fixed positions, where a blank cell and a missing row look
        different and a reader can tell "not recorded" from "not shown". A rail
        is one column with no fixed positions, so an unrecorded Type costs a
        whole line of a panel that also has to hold the related cases — and on
        this corpus Type and Reason are unrecorded on most cases. The values
        are still on the case; what is dropped is a row saying there is none.
        """
        return [
            (label, value)
            for label, value in self.extended()
            if label != "Owner" and value != MISSING
        ]

    def intake_echoes(self) -> dict[str, str]:
        """What this page already displays, keyed by the intake form's labels.

        The web form asks for several things the case record also carries, so
        a case page used to show its subject as the title and again in the
        form, its PI in the metadata and again in the form, and so on. Handed
        to `intake.reconcile`, this is what lets the form show only what the
        page has not said yet — and what lets the one field that *disagrees*
        stop looking like more of the same.

        Keys are the labels `intake.label_for` produces, not Salesforce API
        names: the comparison happens after parsing, on what a reader sees.
        Department appears three times on the form under three names.
        """
        return {
            "Subject": self.subject or "",
            "PI name": self.pi or "",
            "Funding status": self.funding or "",
            "Origin": self.origin or "",
            "IRB protocol": self.irb or "",
            "Department": self.department or "",
            "Stanford dept": self.department or "",
            "Project department": self.department or "",
        }

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
    subject: str | None = None
    body_len: int = 0

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
            subject=clean(row.get("subject")),
            body_len=row.get("body_len") or 0,
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


def without_repeats(entries: list[Comment]) -> list[Comment]:
    """Drop a turn that repeats the one before it, keeping the first.

    The integration copies some submissions onto the case twice — once as the
    email and once as the case comment — so a case can open with the same
    intake payload rendered twice in a row, by the same author, at the same
    minute. Two identical seven-hundred-character forms stacked on top of each
    other read as a rendering fault, and on a long thread they are two screens
    of scrolling that say one thing.

    Adjacent only, and on the exact body. A case where the same short reply
    genuinely recurs — "thanks", a week apart — keeps both, because the turns
    are not adjacent and the timestamps are not the same.
    """
    kept: list[Comment] = []
    for entry in entries:
        last = kept[-1] if kept else None
        if last is not None and last.body == entry.body and last.who == entry.who:
            continue
        kept.append(entry)
    return kept


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

    # How the list is grouped, strongest first. An IRB protocol is one study,
    # so two cases sharing one are two requests about the same work; a PI is a
    # person, whose cases are usually related and sometimes not; a department
    # on its own is a building. In a department the size of Anaesthesia the
    # third is barely a signal at all, which is why it is named as "only".
    STRENGTHS = (
        ("irb", "Same IRB protocol"),
        ("pi", "Same PI"),
        ("department", "Same department only"),
    )

    @property
    def strength(self) -> str:
        """The strongest thing this case has in common with the one on screen."""
        if self.same_irb:
            return "irb"
        if self.same_pi:
            return "pi"
        return "department"

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
    owners: list[str] = field(default_factory=list)
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
            owners=strings("owners"),
            departments=strings("departments"),
            pis=strings("pis"),
            irbs=strings("irbs"),
            min_date=row.get("min_date"),
            max_date=row.get("max_date"),
        )
