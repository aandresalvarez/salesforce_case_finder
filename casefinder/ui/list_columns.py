"""What a row of an operational list shows, and what it gives up when narrow.

The column catalogue, kept apart from the page that renders it. These are
measured values with arithmetic behind them — the widths, the drop order and
the thresholds in `components/table.py` are derived from each other — and that
is a different kind of thing to read than a page's control flow.
"""

from __future__ import annotations

from ..models import preview, show
from .components import table as table_ui

# Spec FR-LIST-4, in order. The description stays at every width and is
# truncated instead; Funded, then Department, then PI give way to keep it that
# way (D16).
#
# Every width here is honoured exactly rather than treated as a hint, because
# the table sets `table-layout:fixed` — see the note there for what that is
# protecting against. The consequence is that these numbers have to be measured
# rather than guessed: they add up to 922px, and Description gets the rest, so
# thirty pixels of generosity anywhere in this dict comes out of the only
# column that holds a sentence — and the drop thresholds in `table.py` are
# derived from these sums, so changing one means re-deriving those. Every
# column but the description is one line: these are identifiers and short
# labels, and a row that grows because one owner has a long name is the density
# problem in miniature.
COLUMNS = {
    "case_number": table_ui.Column(
        # A case number is the row's identifier and the thing people read out
        # to each other; it is the one column that must never ellipsise.
        "case_number", "Case", lambda r: r.case_number, width="118px", one_line=True
    ),
    "owner": table_ui.Column(
        "owner", "Owner", lambda r: show(r.owner), width="120px", one_line=True
    ),
    "status": table_ui.Column(
        "status", "Status", lambda r: show(r.status), width="92px", one_line=True
    ),
    "pi": table_ui.Column(
        "pi",
        "PI",
        lambda r: show(r.pi),
        width="124px",
        # Third to go, and the last one that does. Below this the window is at
        # its configured minimum and everything left is load-bearing.
        drop=3,
        one_line=True,
    ),
    "department": table_ui.Column(
        "department",
        "Department",
        lambda r: show(r.department),
        width="128px",
        # Second to go. It is the widest of the identifying columns and the most
        # redundant — a case with a PI usually implies its department, and
        # neither PI nor IRB can be inferred back from it.
        drop=2,
        one_line=True,
    ),
    "irb": table_ui.Column(
        # IRB values are five-digit protocol numbers, or `NA`, `QI`, `unknown`.
        # The header is the widest thing in the column, so it sets the width.
        "irb", "IRB / protocol", lambda r: show(r.irb), width="112px", one_line=True
    ),
    "description": table_ui.Column(
        "description",
        "Description",
        lambda r: preview(r.description),
        sortable=False,
        # Never drops. FR-LIST-4 says "truncated if width allows", which is an
        # instruction to keep it and shorten it; it used to drop alongside
        # Funded, so the one column that says what a case is about was the
        # first thing a narrow window took away.
        clamp=True,
        subdued=True,
    ),
    "last_activity": table_ui.Column(
        "last_activity",
        "Last activity",
        lambda r: show(r.last_activity),
        # Room for the header plus the sort arrow: this is the default sort, so
        # the arrow is normally present and the header clipped without it.
        width="124px",
        numeric=True,
        one_line=True,
    ),
    "funding": table_ui.Column(
        "funding",
        "Funded",
        lambda r: _funding(r.funding),
        width="104px",
        # The only column FR-LIST-4 allows to disappear at narrow widths.
        drop=1,
        one_line=True,
    ),
}

# What the `Funded` column shows, and why it is not what the warehouse stores.
#
# `Funding_Status__c` is a closed picklist. Counted over the whole current era —
# 888 Unfunded, 367 with nothing recorded, 332 Grant, 66 Departmental/Gift, 25
# Seeking Funding, 23 Funding Status Unknown, 16 Industry and 4 Federal, summing
# to all 1,721 cases — so the map below is exhaustive rather than a bucket that
# quietly loses a tail.
#
# The census used to carry a ninth entry: one case where somebody had typed a
# sentence into the field instead of picking from it. It is not in this corpus.
# The map is still a lookup rather than a bucket, and `_funding` still passes an
# unrecognised value through unchanged, because "closed picklist" describes the
# field's intent rather than a constraint the warehouse enforces.
#
# Two shortenings, for two different reasons.
#
# `Funded - ` is the header again. Under a column called `Funded`, every funded
# case read `Funded - …` at any width that left room for a description, and the
# prefix distinguished nothing.
#
# The rest is about fitting 104px. Three values did not, and truncation made
# two of them worse than blank: `Departmental/Gift` became `Department…`, which
# reads as a department name two columns away from the actual Department
# column, and `Funding Status Unknown` became `Funding Sta…`, an ellipsised
# copy of the header — on the one value whose entire meaning is that nothing is
# known. `Seeking Funding` merely lost its second word.
#
# Display only, and that boundary is load-bearing. The raw value is what the
# CSV exports, what the hover title carries, and what `TriageFilters.funding`
# matches on. Funding has no filter control yet (spec FR-LIST-6, pending
# SR-13); if it gains one, the control must offer these raw strings, because a
# label that does not match the value it filters on is a lie about the list.
_FUNDED_PREFIX = "Funded - "

_SHORT = {
    "Departmental/Gift": "Dept/Gift",
    "Seeking Funding": "Seeking",
    "Funding Status Unknown": "Unknown",
}


def _funding(value: str | None) -> str:
    text = show(value)
    if text.startswith(_FUNDED_PREFIX):
        text = text[len(_FUNDED_PREFIX) :]
    # Anything not in the picklist — one case types a sentence — is shown
    # exactly as stored, ellipsised by the cell with the full text on hover.
    return _SHORT.get(text, text)
