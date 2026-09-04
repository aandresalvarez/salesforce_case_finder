"""Lists — the operational default, and the first thing the app shows.

The lean rules that shape this page (FR-LIST-2, UX-T5) are about what is *not*
here: no New view, Save, Export, Columns, or Refresh buttons in the toolbar, no
Apply button on the filters, and no Open button on a row. Everything the spec
calls secondary sits behind the single `…` menu, and navigation is the row.

There is exactly one primary button on this page, and it is inside the save
dialog — the list itself has none, because the list has no primary action.
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from .. import config, data, views
from ..models import TriageRow, show
from ..queries import TRIAGE_LIMIT, TRIAGE_SORTS, TriageFilters
from . import shell
from .components import filters as filter_ui
from .components import freshness as freshness_ui
from .components import table as table_ui
from .components.empty_state import empty
from .shell import MUTED, muted, overflow, primary, quiet, state

# Spec FR-LIST-4, in order. Description and funding are the two that give way
# when the window is narrow.
COLUMNS = {
    "case_number": table_ui.Column(
        "case_number", "Case", lambda r: r.case_number, width="118px"
    ),
    "owner": table_ui.Column("owner", "Owner", lambda r: show(r.owner), width="140px"),
    "status": table_ui.Column("status", "Status", lambda r: show(r.status), width="110px"),
    "pi": table_ui.Column("pi", "PI", lambda r: show(r.pi), width="140px"),
    "department": table_ui.Column(
        "department", "Department", lambda r: show(r.department), width="150px"
    ),
    "irb": table_ui.Column("irb", "IRB / protocol", lambda r: show(r.irb), width="120px"),
    "description": table_ui.Column(
        "description",
        "Description",
        lambda r: r.description or "",
        sortable=False,
        droppable=True,
    ),
    "last_activity": table_ui.Column(
        "last_activity",
        "Last activity",
        lambda r: show(r.last_activity),
        width="120px",
        numeric=True,
    ),
    "funding": table_ui.Column(
        "funding", "Funded", lambda r: show(r.funding), width="110px", droppable=True
    ),
}


def _apply_view(view: views.SavedView) -> None:
    state.lists.view_name = view.name
    state.lists.filters = TriageFilters(
        open_only=view.filters.open_only,
        statuses=list(view.filters.statuses),
        departments=list(view.filters.departments),
        pis=list(view.filters.pis),
        irbs=list(view.filters.irbs),
        funding=list(view.filters.funding),
    )
    state.lists.sort = view.sort if view.sort in TRIAGE_SORTS else "last_activity"
    state.lists.descending = view.descending
    state.lists.columns = view.columns


def _current_columns() -> list[table_ui.Column]:
    keys = state.lists.columns or views.DEFAULT_COLUMNS
    return [COLUMNS[k] for k in keys if k in COLUMNS]


def render() -> None:
    if not state.lists.columns:
        _apply_view(views.shared_views()[0])

    # The title needs freshness, the filter row needs facets, and the table
    # needs the list. None of the three depends on the others, so they go out
    # together and the page waits once instead of three times.
    data.prefetch(
        lambda: data.freshness(state.era, config.STALE_DAYS),
        lambda: data.facets(state.era, extended=True),
        _query,
    )

    _title_row()
    # Called, not refreshed: `refresh()` re-runs targets that already exist, and
    # on a fresh page load there are none, so the list would come up empty.
    body()


def _title_row() -> None:
    with ui.row().classes("w-full items-start justify-between").style("gap:12px"):
        with ui.column().style("gap:2px; min-width:0"):
            with ui.row().classes("items-center").style("gap:8px"):
                ui.label(state.lists.view_name).classes("cf-h1")
                _view_selector()
            header_meta()
        with ui.row().classes("items-center").style("gap:2px"):
            _overflow_menu()


@ui.refreshable
def header_meta() -> None:
    """Count and freshness under the title. Refreshed with the body."""
    try:
        fresh = data.freshness(state.era, config.STALE_DAYS)
    except Exception:  # noqa: BLE001
        return
    freshness_ui.line(fresh)


def _view_selector() -> None:
    """Preset switching lives under the title, not in a sub-navigation tree."""
    with ui.button(icon="expand_more").props("flat dense round").style(f"color:{MUTED}"):
        with ui.menu().props("auto-close"):
            available = views.all_views()
            shared = [v for v in available if v.shared]
            personal = [v for v in available if not v.shared]
            for group, label in ((shared, "Shared presets"), (personal, "My views")):
                if not group:
                    continue
                ui.label(label).classes("cf-metric-label").style("padding:6px 12px 2px 12px")
                for view in group:
                    with ui.menu_item(on_click=lambda v=view: _switch(v)):
                        with ui.column().style("gap:0"):
                            ui.label(view.name).style("font-size:13px")
                            ui.label(view.summary).classes("cf-muted")
            ui.separator()
            ui.menu_item("Manage saved views…", on_click=lambda: ui.navigate.to("/views"))


def _switch(view: views.SavedView) -> None:
    _apply_view(view)
    body.refresh()
    header_meta.refresh()


def _overflow_menu() -> None:
    """Every secondary operation, in one `…` — FR-LIST-2 / UX-T5 / UX-T6."""
    with overflow():
        ui.menu_item("Save current view…", on_click=_save_dialog)
        ui.menu_item("Export metadata CSV", on_click=_export_csv)
        with ui.menu_item("Columns"):
            with ui.item_section().props("side"):
                ui.icon("chevron_right")
            with ui.menu().props("anchor='top end' self='top start' auto-close=false"):
                _column_picker()
        ui.separator()
        ui.menu_item("Refresh from BigQuery", on_click=_hard_refresh)
        ui.menu_item("Saved views…", on_click=lambda: ui.navigate.to("/views"))


def _column_picker() -> None:
    current = set(state.lists.columns or views.DEFAULT_COLUMNS)

    def toggle(key: str, on: bool) -> None:
        # Rebuilt in canonical order so column order never depends on click order.
        picked = set(current)
        if on:
            picked.add(key)
        else:
            picked.discard(key)
        # The case number is the navigation target; a list without it is unusable.
        picked.add("case_number")
        state.lists.columns = tuple(k for k in views.ALL_COLUMNS if k in picked)
        body.refresh()

    with ui.column().classes("p-2").style("gap:2px"):
        for key in views.ALL_COLUMNS:
            ui.checkbox(
                COLUMNS[key].label,
                value=key in current,
                on_change=lambda e, k=key: toggle(k, bool(e.value)),
            ).props("dense").style("font-size:12.5px")


def _hard_refresh() -> None:
    from .. import cache

    cache.results.invalidate("triage")
    cache.results.invalidate("freshness")
    body.refresh()
    header_meta.refresh()
    ui.notify("Reloaded from BigQuery", type="positive")


def _save_dialog() -> None:
    """Spec FR-LIST-10: prompt for a name, nothing else."""
    with ui.dialog() as dialog, ui.card().style("min-width:340px"):
        ui.label("Save this view").classes("cf-h2")
        muted("Filters, sort, and columns only. No case data is written.")
        name = ui.input("Name", value=state.lists.view_name).props(
            "dense outlined autofocus"
        ).classes(
            "w-full"
        )

        def save() -> None:
            label = (name.value or "").strip()
            if not label:
                ui.notify("Give the view a name", type="warning")
                return
            view = views.SavedView(
                name=label,
                filters=state.lists.filters,
                sort=state.lists.sort,
                descending=state.lists.descending,
                columns=state.lists.columns or views.DEFAULT_COLUMNS,
            )
            path = views.save_personal(view)
            state.lists.view_name = label
            dialog.close()
            body.refresh()
            header_meta.refresh()
            ui.notify(f"Saved to {path.name}", type="positive")

        with ui.row().classes("w-full justify-end items-center").style("gap:8px; margin-top:12px"):
            quiet("Cancel", dialog.close)
            primary("Save", save)
    dialog.open()


def _export_csv() -> None:
    """Metadata only — spec FR-LIST-12. No bodies, no snippets, no descriptions."""
    import csv
    import io

    try:
        page = _query()
    except Exception as exc:  # noqa: BLE001
        ui.notify(f"Could not export: {exc}", type="negative")
        return

    # Description is excluded deliberately: it is free text written about a
    # research subject's data, and a CSV leaves the process.
    fields = [
        "case_number", "owner", "status", "pi",
        "department", "irb", "funding", "last_activity",
    ]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([COLUMNS[f].label for f in fields])
    for row in page.rows:
        writer.writerow([show(getattr(row, f)) if getattr(row, f) else "" for f in fields])

    name = state.lists.view_name.lower().replace(" ", "-").replace("/", "-")
    ui.download(buffer.getvalue().encode("utf-8"), f"{name}.csv")
    ui.notify(f"Exported {len(page.rows):,} rows (metadata only)", type="positive")


def _query():
    return data.triage(
        state.era,
        state.lists.filters,
        sort=state.lists.sort,
        descending=state.lists.descending,
        limit=TRIAGE_LIMIT,
    )


def _on_sort(key: str) -> None:
    if state.lists.sort == key:
        state.lists.descending = not state.lists.descending
    else:
        state.lists.sort = key
        state.lists.descending = True
    body.refresh()


def _filter_controls() -> None:
    """The five priority filters — FR-LIST-6. Rendered twice; see filters.py."""
    facets = _facets()
    current = state.lists.filters

    def rerun() -> None:
        body.refresh()
        header_meta.refresh()

    def set_open(value: bool) -> None:
        current.open_only = value
        rerun()

    def setter(attr: str) -> Callable[[list[str]], None]:
        def apply(values: list[str]) -> None:
            setattr(current, attr, values)
            rerun()

        return apply

    filter_ui.open_only_toggle(current.open_only, set_open)
    filter_ui.multi_select("Status", facets.statuses, current.statuses, setter("statuses"))
    filter_ui.multi_select(
        "Department", facets.departments, current.departments, setter("departments"), width=190
    )
    filter_ui.multi_select("PI", facets.pis, current.pis, setter("pis"))
    filter_ui.multi_select("IRB / protocol", facets.irbs, current.irbs, setter("irbs"), width=160)


def _facets():
    from ..models import Facets

    try:
        return data.facets(state.era, extended=True)
    except Exception:  # noqa: BLE001
        return Facets()


@ui.refreshable
def body() -> None:
    filter_ui.inline_row(_filter_controls, state.lists.filters.active_count)

    try:
        fresh = data.freshness(state.era, config.STALE_DAYS)
        freshness_ui.banner(fresh)
    except Exception:  # noqa: BLE001
        pass

    try:
        page = _query()
    except Exception as exc:  # noqa: BLE001
        shell.error_region(exc)
        return

    if not page.rows:
        empty(
            "No cases match these filters in this snapshot.",
            [("Clear filters", _clear_filters)],
            icon="inbox",
        )
        return

    with ui.row().classes("w-full items-center justify-between").style("margin:4px 0 8px 0"):
        muted(table_ui.result_count(len(page.rows), page.total_matches, noun="case"))
        if not page.is_trivial_cost:
            muted(page.cost_note)

    table_ui.data_table(
        _current_columns(),
        page.rows,
        on_row_click=_open_case,
        sort_key=state.lists.sort,
        descending=state.lists.descending,
        on_sort=_on_sort,
    )


def _clear_filters() -> None:
    state.lists.filters = TriageFilters(open_only=state.lists.filters.open_only)
    body.refresh()
    header_meta.refresh()


def _open_case(row: TriageRow) -> None:
    ui.navigate.to(f"/case/{row.case_number}")


# --------------------------------------------------------------------------
# Saved Views screen — FR-LIST-9, reachable from the selector, not the rail
# --------------------------------------------------------------------------


def render_saved_views() -> None:
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
            "gap:12px; padding:9px 4px; border-bottom:1px solid " + shell.LINE
        ):
            with ui.column().style("gap:1px; min-width:0; cursor:pointer").on(
                "click", lambda v=view: _open_view(v)
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
    _apply_view(view)
    ui.navigate.to("/")


def _copy_definition(view: views.SavedView) -> None:
    """FR-LIST-11: sharing is handing the maintainer a definition, not a service."""
    ui.clipboard.write(view.share_text())
    ui.notify("View definition copied", type="positive")


def _delete_view(view: views.SavedView) -> None:
    if views.delete_personal(view.name):
        ui.notify(f"Deleted “{view.name}”", type="positive")
        ui.navigate.to("/views")
