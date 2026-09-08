"""Paging for the operational lists.

Paging is navigation, not an action, so this contributes no primary button —
UX-INV-1 caps a screen at one filled button and a list has no primary action at
all. It is two flat icon buttons and a line of text stating where you are.

The range line is always drawn and the buttons appear only when there is more
than one page, which is the same progressive-disclosure rule the filters follow
(UX-INV-3): a control that can only be pressed to no effect is a control that
should not be there.
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from ..theme import MUTED


def range_label(offset: int, shown: int, total: int, *, noun: str = "case") -> str:
    """`1–50 of 334 cases`, or just the count when it all fits on one page.

    Stated as a range rather than a page number because the question a triage
    list gets asked is "how much is left", and `Page 3 of 7` makes the reader
    do arithmetic to answer it.
    """
    plural = "" if total == 1 else "s"
    if shown == 0:
        return f"No {noun}s"
    if total <= shown and offset == 0:
        return f"{total:,} {noun}{plural}"
    first = offset + 1
    last = offset + shown
    return f"{first:,}–{last:,} of {total:,} {noun}{plural}"


def pager(
    *,
    offset: int,
    shown: int,
    total: int,
    page_size: int,
    on_change: Callable[[int], None],
    noun: str = "case",
) -> None:
    """The range line and, if there is anywhere to go, the two arrows."""
    with ui.row().classes("items-center").style("gap:2px"):
        ui.label(range_label(offset, shown, total, noun=noun)).classes("cf-muted")
        if total <= page_size:
            return

        def step(delta: int) -> None:
            # Clamped here rather than trusted from the caller, so the page can
            # never ask BigQuery for an offset past the end of the result and
            # get back an empty list that looks like "no cases match".
            on_change(max(0, min(offset + delta * page_size, _last_offset(total, page_size))))

        _arrow("chevron_left", offset > 0, lambda: step(-1), "Previous page")
        _arrow(
            "chevron_right",
            offset + shown < total,
            lambda: step(1),
            "Next page",
        )


def _last_offset(total: int, page_size: int) -> int:
    if total <= 0:
        return 0
    return ((total - 1) // page_size) * page_size


def _arrow(icon: str, enabled: bool, on_click: Callable[[], None], tip: str) -> None:
    button = (
        ui.button(icon=icon, on_click=lambda: on_click())
        .props("flat dense round")
        .classes("cf-page")
        .style(f"color:{MUTED}")
    )
    if enabled:
        button.tooltip(tip)
    else:
        # Kept in place and disabled rather than removed: an arrow that vanishes
        # at the last page shifts the other one under the cursor, and the next
        # click lands on the wrong control.
        button.props("disable")
