"""Case metadata rendering: the metric strip and the extended attribute grid.

Spec FR-CASE-2 asks for "one quiet strip or inline group, not five independent
cards", and UX-INV-6 bans cards around metadata generally. Both are handled by
these two functions, so a page cannot reintroduce the card grid by accident.
"""

from __future__ import annotations

from collections.abc import Sequence

from nicegui import ui

from ...models import CaseHeader
from ..shell import LINE, MUTED
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


def header_block(header: CaseHeader, *, on_back) -> None:
    """Back link, title, case number — the top of a case page."""
    with ui.row().classes("items-center").style("gap:5px; cursor:pointer").on(
        "click", on_back
    ):
        ui.icon("arrow_back").style(f"font-size:14px; color:{MUTED}")
        ui.label("Back").classes("cf-muted")
    ui.label(header.subject or "(no subject)").classes("cf-h1").style("margin-top:10px")
    ui.label(header.case_number).classes("cf-casenum").style("margin-top:2px")


def description_block(text: str | None) -> None:
    """Spec FR-CASE-4: present but not dominant, collapsed when long.

    The description is the same warehouse text as a comment body and arrives in
    the same two shapes, so it goes through the same reader — a case whose
    description is the serialised intake form should not be the one place in
    the app that still shows it as JSON.
    """
    if not text:
        return
    long_text = len(text) > 420
    if long_text:
        with ui.expansion("Description").classes("w-full").style("margin-bottom:6px"):
            intake_form.body(text)
    else:
        with ui.column().classes("w-full").style("gap:2px; margin-bottom:10px"):
            ui.label("Description").classes("cf-metric-label")
            intake_form.body(text)
