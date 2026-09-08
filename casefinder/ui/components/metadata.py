"""Case metadata rendering: the metric strip and the extended attribute grid.

Spec FR-CASE-2 asks for "one quiet strip or inline group, not five independent
cards", and UX-INV-6 bans cards around metadata generally. Both are handled by
these two functions, so a page cannot reintroduce the card grid by accident.
"""

from __future__ import annotations

from collections.abc import Sequence

from nicegui import ui

from ... import intake
from ...models import CaseHeader
from ..theme import LINE, MUTED
from . import intake_form


def metric_strip(pairs: Sequence[tuple[str, str]]) -> None:
    """Flat run of label/value pairs separated by dividers, not cards."""
    with ui.row().classes("items-center").style("gap:0; flex-wrap:wrap; margin:12px 0"):
        for index, (label, value) in enumerate(pairs):
            if index:
                ui.element("div").style(
                    f"width:1px; height:22px; background:{LINE}; margin:0 16px"
                )
            with ui.column().style("gap:1px"):
                ui.label(label).classes("cf-metric-label")
                ui.label(value).classes("cf-metric-value")


def attribute_grid(pairs: Sequence[tuple[str, str]], *, columns: int = 4) -> None:
    """Extended metadata — spec FR-CASE-3. Missing values arrive as em dashes."""
    with ui.grid(columns=columns).classes("w-full").style("gap:14px 26px; margin-bottom:4px"):
        for label, value in pairs:
            with ui.column().style("gap:1px; min-width:0"):
                ui.label(label).classes("cf-metric-label")
                ui.label(value).style("font-size:13px; overflow-wrap:anywhere")


def pairs(rows: Sequence[tuple[str, str]]) -> None:
    """Label over value, down a column. The rail's whole vocabulary.

    Not `attribute_grid`: that lays four across a reading column, and a 280px
    rail has room for one. Same pairs, same type, one track — which is also
    what keeps UX-INV-6 true, since neither draws a card around anything.
    """
    with ui.column().classes("w-full").style("gap:11px"):
        for label, value in rows:
            with ui.column().style("gap:1px; min-width:0"):
                ui.label(label).classes("cf-metric-label")
                ui.label(value).style("font-size:12.5px; overflow-wrap:anywhere")


def person(who: intake.Requester) -> None:
    """The requester, in the rail. Name first, then how to reach them."""
    with ui.column().classes("w-full").style("gap:9px"):
        if who.name:
            ui.label(who.name).style("font-size:13px; font-weight:600")
        for label, value in who.rows:
            with ui.column().style("gap:1px; min-width:0"):
                ui.label(label).classes("cf-metric-label")
                ui.label(value).style("font-size:12.5px; overflow-wrap:anywhere")


def header_block(header: CaseHeader, *, on_back) -> None:
    """Back link, title, case number — the top of a case page."""
    with ui.row().classes("items-center").style("gap:5px; cursor:pointer").on(
        "click", on_back
    ):
        ui.icon("arrow_back").style(f"font-size:14px; color:{MUTED}")
        ui.label("Back").classes("cf-muted")
    ui.label(header.subject or "(no subject)").classes("cf-h1").style("margin-top:10px")
    ui.label(header.case_number).classes("cf-casenum").style("margin-top:2px")


def description_block(text: str | None, *, shown=None) -> None:
    """The request, above the thread it started.

    Two shapes, and the difference matters. A submitted form *is* the request:
    it is the only copy on the page now that the turn repeating it has gone,
    and burying it in a collapsed disclosure headed `Description` hides the one
    thing a reader most often opens the case for. A pasted email is prose that
    may run to any length, and FR-CASE-4 asks for it to be present without
    dominating — so that one keeps the disclosure.
    """
    if not text:
        return
    if intake.parse(text) is not None:
        with ui.column().classes("w-full cf-request").style("gap:2px"):
            ui.label("The request").classes("cf-request-h")
            intake_form.body(text, shown=shown)
        return
    if len(text) > 420:
        with ui.expansion("Description").classes("w-full").style("margin-bottom:6px"):
            intake_form.body(text, shown=shown)
        return
    with ui.column().classes("w-full").style("gap:2px; margin-bottom:10px"):
        ui.label("Description").classes("cf-metric-label")
        intake_form.body(text, shown=shown)
