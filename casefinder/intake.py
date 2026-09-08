"""Read the intake-form payload that arrives inside a case body.

Most comments on a case are prose. Some are not: the web intake form serialises
itself into the comment as JSON, and what the reader gets is a single
seven-hundred-character line of `{"Field__c":"value",...}` with the actual
request buried in the middle of it. It is all there and none of it is legible.

The shape, with invented content:

    {"LastName":"Whitfield","FirstName":"Dana","Email":"d.w@example.com"}
    ~#~#~
    {"Subject":"...","Description":"On <date> ... wrote:\\n\\nSummary: ...",
     "IRB_Protocol__c":"TBD","Funding_status__c":"Funded - Grant"}

Two things make it worth parsing rather than pretty-printing. The payload is
several JSON objects joined by a `~#~#~` separator, so it is not valid JSON as
a whole and no generic formatter will touch it. And one field — `Description`
— holds the request itself as plain text with real newlines, which JSON escapes
into `\\n`; parsing is what turns those back into the paragraph breaks the
person who filled the form in actually typed.

Everything here is best-effort and reversible. `parse` returns None the moment
the text is not this shape, the caller falls back to showing the body verbatim,
and the raw payload is carried on the result so a reader can always get back to
the literal bytes. A support person acting on a case needs to be able to see
what the record really says, so the formatted view is an addition to that and
never a replacement for it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from .models import clean, strip_attribution

# Salesforce joins the form's payload objects with this. It is not a delimiter
# anyone chose to be parsed — it is what the integration happened to emit — so
# it is matched literally and nothing is inferred from a partial one.
SEPARATOR = "~#~#~"

# Below this many populated fields, restructuring buys nothing: a two-field
# object reads as well as one line of JSON and worse than the original if the
# original was never a form at all.
_MIN_FIELDS = 3

# The field holding the request itself, rendered as its own block rather than
# as a row in the grid. Salesforce spells it exactly this way on both objects.
_NARRATIVE_KEY = "Description"

# A value long enough that a two-column grid would give it one word per line.
_BLOCK_AT = 96

# What `_display` renders a boolean as, and the shortest value worth treating
# as an identifier. See `_identifying`.
_CLOSED_ANSWERS = frozenset({"yes", "no"})
_DISTINCTIVE_AT = 4

# Fields that route the request rather than describe it. Every one of them is a
# queue name, an integration id, or a link back into the system that produced
# the form — true, and never the reason anybody opened the case. They are not
# discarded, they move behind the `Original record` disclosure that already
# holds the payload verbatim.
#
# Matched on the Salesforce API name rather than the rendered label, because
# the API name is what the integration controls and the label is what this
# module decides.
_ROUTING = frozenset({
    "Original_Queue_Name__c",
    "Active_Queue__c",
    "CustomOrigin__c",
    "Custom_Origin__c",
    "Project_Record_ID__c",
    "REDCAP_StudyName__c",
    "REDCap_StudyName__c",
})

# Tokens whose conventional casing is not what a mechanical rule produces.
# Applied per word after the name is split, so `IRB_Protocol__c` reads
# `IRB protocol` rather than `Irb protocol`.
_ACRONYMS = {
    "id": "ID",
    "irb": "IRB",
    "pi": "PI",
    "url": "URL",
    "uri": "URI",
    "dicom": "DICOM",
    "mrn": "MRN",
    "omop": "OMOP",
    "phi": "PHI",
    "ehr": "EHR",
    "sql": "SQL",
    "csv": "CSV",
    "sunet": "SUNet",
    "redcap": "REDCap",
}

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_BLANK_RUN = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class Field:
    label: str
    value: str
    # Long or multi-line values get a row to themselves; a grid cell would
    # render them one word per line.
    block: bool
    # Set when the page already shows this value somewhere better, naming where.
    # The field is kept on the object and dropped by the renderer, so the
    # `Original record` disclosure is still the whole payload.
    echoes: str = ""
    # Set when the page shows something *different* for the same thing, naming
    # what it shows. The opposite of an echo, and the only part of a form worth
    # interrupting somebody for.
    conflicts: str = ""


@dataclass(frozen=True)
class Intake:
    fields: tuple[Field, ...]
    # The request as the requester typed it, newlines intact and the mail
    # client's attribution line removed. Empty when the payload had none.
    narrative: str
    # The payload exactly as it arrived, so the formatted view is never the
    # only way to see what the record says.
    raw: str


def label_for(name: str) -> str:
    """Turn a Salesforce API name into something a person would write.

    `Funding_status__c` becomes `Funding status`, `Project_Record_ID__c`
    becomes `Project record ID`, `ContactEmail` becomes `Contact email`.
    Sentence case rather than title case, to match the labels the rest of the
    app already uses.
    """
    stem = name[:-3] if name.endswith("__c") else name
    words = _CAMEL_BOUNDARY.sub(" ", stem.replace("_", " ")).split()
    if not words:
        return name

    shaped = []
    for word in words:
        fixed = _ACRONYMS.get(word.lower())
        if fixed is not None:
            shaped.append(fixed)
        elif word.isupper() and len(word) > 1:
            # Already an acronym the source spelled out; leave it alone rather
            # than lowercasing something like `NIH` into prose.
            shaped.append(word)
        else:
            shaped.append(word.lower())

    first = shaped[0]
    if first == first.lower() and first.lower() not in _ACRONYMS:
        first = first[:1].upper() + first[1:]
    return " ".join([first, *shaped[1:]])


def _display(value: Any) -> str:
    """One field's value as text, or empty for anything not worth a row.

    The form's booleans arrive three ways — as JSON `true`, as the string
    `"true"`, and as `" false"` with a leading space — because three different
    things wrote them. All three read as Yes or No, which is what the question
    they answer was asking.
    """
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if value is None:
        return ""
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list | dict):
        # Not something the form emits, but a nested value must not crash the
        # page; JSON is at least honest about what it is.
        return json.dumps(value, ensure_ascii=False)

    text = str(value).strip()
    lowered = text.lower()
    if lowered == "true":
        return "Yes"
    if lowered == "false":
        return "No"
    return text


def _tidy(text: str) -> str:
    """Normalise line endings and collapse runs of blank lines.

    The narrative is rendered with whitespace preserved, so `\\r\\n` would show
    as a stray glyph and a six-line gap between two paragraphs would be six
    lines of nothing on screen.
    """
    return _BLANK_RUN.sub("\n\n", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def _objects(text: str) -> list[dict[str, Any]] | None:
    """The payload's JSON objects, or None if it is not that shape.

    Every non-empty segment has to parse, and has to parse to an object. One
    segment of prose means the body is prose that happens to contain the
    separator, and the whole thing is left alone.
    """
    found: list[dict[str, Any]] = []
    for segment in text.split(SEPARATOR):
        segment = segment.strip()
        if not segment:
            continue
        if not (segment.startswith("{") and segment.endswith("}")):
            return None
        try:
            parsed = json.loads(segment)
        except ValueError:
            return None
        if not isinstance(parsed, dict):
            return None
        found.append(parsed)
    return found or None


def parse(text: Any) -> Intake | None:
    """The intake form inside a case body, or None if there is not one."""
    cleaned = clean(text)
    if cleaned is None:
        return None
    raw = str(cleaned)
    objects = _objects(raw)
    if objects is None:
        return None

    # First occurrence wins. The two objects overlap — both carry the
    # requester's address, for instance — and the earlier one is the more
    # specific of the two.
    merged: dict[str, Any] = {}
    for obj in objects:
        for key, value in obj.items():
            merged.setdefault(key, value)

    narrative = _tidy(strip_attribution(str(merged.pop(_NARRATIVE_KEY, "") or "")))

    fields = _dedupe(
        Field(
            label=label_for(key),
            value=shown,
            block="\n" in shown or len(shown) > _BLOCK_AT,
            echoes="the routing record" if key in _ROUTING else "",
        )
        for key, value in merged.items()
        if (shown := _display(value))
    )

    # Counted over every populated field, including the routing ones. This
    # decides whether the payload *is* a form, which is a question about its
    # shape; how much of it is worth drawing is a different question, asked
    # later and by the renderer.
    if len(fields) + bool(narrative) < _MIN_FIELDS:
        return None
    return Intake(fields=fields, narrative=narrative, raw=raw)


def _dedupe(fields: Iterable[Field]) -> tuple[Field, ...]:
    """Mark a field whose value another field on the same form already carries.

    The form asks for several things twice under different names — an address
    as `Email` and again as `ContactEmail`, a SUNet id on both objects, a
    department under three names — and the two queue fields arrive byte
    identical. Nobody typed them twice; the integration collects them from more
    than one place. The first spelling wins, on the same principle as the
    object merge above: earlier is more specific.
    """
    out: list[Field] = []
    seen: dict[str, str] = {}
    for field in fields:
        key = _comparable(field.value)
        if not _identifying(key):
            out.append(field)
            continue
        first = seen.get(key)
        if first is not None and not field.echoes:
            field = replace(field, echoes=first)
        elif first is None:
            seen[key] = field.label
        out.append(field)
    return tuple(out)


def _identifying(value: str) -> str | bool:
    """Whether two fields carrying this value are the same datum or a coincidence.

    An address, a SUNet id, a department name: carried twice, it is once. An
    answer drawn from a closed set is not — `DICOM: No` and `Is the requester
    the PI: No` are two different questions that happen to agree, and folding
    the second into the first would delete an answer rather than a repetition.

    So the bar is conservative in the safe direction. Failing to spot a
    duplicate shows one row too many; mistaking an answer for a duplicate
    removes something the record says, and nothing on screen would admit it.
    """
    return value not in _CLOSED_ANSWERS and len(value) >= _DISTINCTIVE_AT


def _comparable(value: str) -> str:
    """Two spellings of the same answer, reduced to one string.

    Case and surrounding space only. Nothing cleverer: `41288` and `IRB 41288`
    are not the same answer, and a rule loose enough to call them equal would
    hide the disagreement this exists to find.
    """
    return " ".join(value.split()).casefold()


def reconcile(form: Intake, shown: Mapping[str, str]) -> Intake:
    """Compare the form against what the page already says, field by field.

    `shown` maps a field label to the value the page displays for it — the case
    header's own subject, PI, department, funding and IRB. Three outcomes:

    * the same answer, and the field is marked as an echo. The case page showed
      the subject as its title and again in the form, the PI in the metadata
      grid and again in the form, and so on for nine values on a form of
      twenty-eight. Repetition on that scale stops reading as confirmation and
      starts reading as noise to skim past, which is how the tenth field —
      the one that differs — gets skimmed past too.
    * a different answer, and the field is marked as a conflict. This is the
      one worth the reader's attention: a requester who wrote `TBD` for the IRB
      protocol before the protocol existed leaves a form that disagrees with
      the record, and shown flat and far apart the two look like the page
      repeating itself rather than like a fact that changed.
    * nothing to compare against, and the field is left alone.
    """
    return replace(
        form,
        fields=tuple(_against(field, shown) for field in form.fields),
    )


def _against(field: Field, shown: Mapping[str, str]) -> Field:
    if field.echoes or field.conflicts:
        return field
    for label, value in shown.items():
        if not value or _comparable(label) != _comparable(field.label):
            continue
        if _comparable(value) == _comparable(field.value):
            return replace(field, echoes=label)
        return replace(field, conflicts=value)
    return field


# Labels the form's narrative is written under. The requester types into one
# box; the integration prefixes each answer, so what arrives is a single string
# with these words in it and nothing else marking the boundaries.
_SECTION = re.compile(
    r"^(Summary|Description|Question|Availability|Requested For|Contact E-?mail"
    r"|Phone|Appointment|Department|Is requestor the PI|Research|Plans to publish"
    r"|Funding|REDCap URL|Request submitted by)\s*:\s*",
    re.IGNORECASE | re.MULTILINE,
)

# Of those, the ones that are contact details or a restatement of the form's own
# fields. They are answered again in the grid and in the requester panel, so
# inside the request they are the same repetition this module exists to remove.
_NOT_THE_REQUEST = frozenset({
    "availability", "requested for", "contact email", "contact e-mail", "phone",
    "appointment", "department", "is requestor the pi", "research",
    "plans to publish", "funding", "redcap url", "request submitted by",
})

# What the form asks about the person asking. Shown once, beside the case,
# rather than as seven rows in the middle of the request.
_REQUESTER = ("First name", "Last name", "Email", "SUNet ID", "Phone", "Rank",
              "Department")


@dataclass(frozen=True)
class Requester:
    """Who filed the request, as the form recorded them."""

    name: str
    rows: tuple[tuple[str, str], ...]


def sections(narrative: str) -> tuple[tuple[str, str], ...]:
    """Split the narrative into the parts the requester actually wrote.

    `Summary`, `Description` and `Question` are three different answers to
    three different prompts, and running them together as one paragraph — which
    is how they arrive — buries the question, which is the part a support
    person is answering. Everything after them is contact detail the form
    already collected in its own fields.

    Returns the kept sections in the order they were written. Text before the
    first label is returned under an empty label, so a narrative with no labels
    at all comes back whole rather than empty.
    """
    marks = list(_SECTION.finditer(narrative))
    if not marks:
        text = narrative.strip()
        return ((("", text),) if text else ())

    out: list[tuple[str, str]] = []
    lead = narrative[: marks[0].start()].strip()
    if lead:
        out.append(("", lead))
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(narrative)
        label = mark.group(1)
        if label.casefold().replace("-", "") in _NOT_THE_REQUEST:
            continue
        body = narrative[mark.end() : end].strip()
        if body:
            out.append((label[:1].upper() + label[1:].lower(), body))
    return tuple(out)


def requester(form: Intake) -> Requester | None:
    """The person who filed the form, lifted out of it.

    Seven of the form's fields describe the requester rather than the request —
    a name split across two of them, an address, a telephone number, a rank.
    They belong beside the case, not in the middle of what was asked, and
    nothing is lost by moving them: `mark_requester` marks the originals so the
    grid stops drawing them.
    """
    have = {f.label: f.value for f in form.fields if f.value}
    name = " ".join(x for x in (have.get("First name"), have.get("Last name")) if x)
    rows = tuple(
        (label, have[label])
        for label in _REQUESTER
        if label in have and label not in ("First name", "Last name")
    )
    if not name and not rows:
        return None
    return Requester(name=name, rows=rows)


def mark_requester(form: Intake) -> Intake:
    """Fold the requester's own details out of the request grid."""
    return replace(
        form,
        fields=tuple(
            replace(f, echoes="the requester") if f.label in _REQUESTER and not f.echoes else f
            for f in form.fields
        ),
    )
