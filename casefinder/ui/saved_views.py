"""The Saved Views screen — FR-LIST-9.

Its own page, reachable from the list's view selector rather than from the
rail. It lived inside `lists` and had no business being there: two screens in
one module, sharing an import list and nothing else.

What it manages is definitions, not data. Everything on this screen is a set of
filter and column choices; no case row, description or message text is written
to disk or read back from one — see the allowlist in `casefinder/views.py`.
"""

from __future__ import annotations

from nicegui import ui

from .. import config, views
from . import theme
from .components.actions import muted, overflow
from .state import state


def render() -> None:
    ui.label("Saved views").classes("cf-h1")
    muted("Filter definitions only. No case rows or message text is stored.")

    shared = [v for v in views.all_views() if v.shared]
    personal = [v for v in views.all_views() if not v.shared]

    _view_group("Shared presets", shared, deletable=False)
    _view_group("My views", personal, deletable=True)

    if not personal:
        muted(
            "Saving a view from the Lists overflow menu puts it here. "
            f"It is written to {config.personal_views_path()}."
        ).style("margin-top:14px")


def _view_group(title: str, group: list[views.SavedView], *, deletable: bool) -> None:
    if not group:
        return
    ui.label(title).classes("cf-h2").style("margin:22px 0 6px 0")
    for view in group:
        with ui.row().classes("w-full items-center justify-between cf-row").style(
            "gap:12px; padding:9px 4px; border-bottom:1px solid " + theme.LINE
        ):
            with ui.column().style("gap:1px; min-width:0; cursor:pointer").on(
                "click",
                lambda v=view: _open_view(v),
                js_handler=theme.CLICK_UNLESS_SELECTING,
            ):
                ui.label(view.name).style("font-size:13.5px")
                ui.label(view.description or view.summary).classes("cf-muted")
            with ui.row().classes("items-center").style("gap:2px"), overflow():
                ui.menu_item("Open", on_click=lambda v=view: _open_view(v))
                ui.menu_item("Copy definition", on_click=lambda v=view: _copy_definition(v))
                if deletable:
                    ui.separator()
                    ui.menu_item("Delete", on_click=lambda v=view: _delete_view(v))


def _open_view(view: views.SavedView) -> None:
    state.lists.apply(view)
    ui.navigate.to("/lists")


def _copy_definition(view: views.SavedView) -> None:
    """FR-LIST-11: sharing is handing the maintainer a definition, not a service."""
    ui.clipboard.write(view.share_text())
    ui.notify("View definition copied", type="positive")


def _delete_view(view: views.SavedView) -> None:
    if views.delete_personal(view.name):
        ui.notify(f"Deleted “{view.name}”", type="positive")
        ui.navigate.to("/views")
