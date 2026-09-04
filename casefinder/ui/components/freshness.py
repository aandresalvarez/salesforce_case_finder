"""Warehouse freshness: the `Data as of ...` line and the stale banner.

Spec section 5.6 requires every operational list to state its snapshot age, and
requires the warning to appear once at the top rather than on every row. That
"once" is the whole point — a warning repeated per row is scenery, and a triage
list that silently shows a case as open after Salesforce closed it is the most
likely way this application misleads someone.
"""

from __future__ import annotations

from nicegui import ui

from ...models import Freshness


def line(fresh: Freshness) -> None:
    """The always-present one-liner under a list title."""
    ui.label(fresh.label).classes("cf-muted")


def banner(fresh: Freshness) -> None:
    """Shown only past the staleness threshold. One per screen.

    Sized to its text rather than stretched across the window. A full-bleed
    amber bar is the loudest thing on a triage screen, and it is permanent —
    the snapshot is either stale or it is not, so it would be shouting on every
    page load for as long as the load schedule slips. Quiet status, stated
    once, is the rule this is under (UX-INV-5); the point is that the reader
    can find it when the dates look wrong, not that they cannot avoid it.
    """
    if not fresh.is_stale:
        return
    with ui.row().classes("cf-banner items-center").style(
        "gap:7px; margin:10px 0 2px 0; width:fit-content; max-width:100%"
    ):
        ui.icon("schedule").style("font-size:14px")
        ui.label(fresh.warning)
