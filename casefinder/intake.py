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
from dataclasses import dataclass
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

    fields = tuple(
        Field(
            label=label_for(key),
            value=shown,
            block="\n" in shown or len(shown) > _BLOCK_AT,
        )
        for key, value in merged.items()
        if (shown := _display(value))
    )

    if len(fields) + bool(narrative) < _MIN_FIELDS:
        return None
    return Intake(fields=fields, narrative=narrative, raw=raw)
