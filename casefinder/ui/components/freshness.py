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
    """Shown only past the staleness threshold. One per screen."""
    if not fresh.is_stale:
        return
    with ui.row().classes("cf-banner w-full items-center").style(
        "gap:8px; margin:10px 0 2px 0"
    ):
        ui.icon("schedule").style("font-size:15px")
        ui.label(fresh.warning)
