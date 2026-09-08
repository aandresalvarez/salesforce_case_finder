"""Lists — the operational default, one click from wherever you are.

It is not the first thing the app shows any more; Search is (D17). What it
still is, is the screen a support person spends the day on, and the only one
that answers "what is on my plate" rather than "where is that one case".

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
from ..queries import TRIAGE_LIMIT, TRIAGE_PAGE_SIZE, TriageFilters
from . import errors
from .components import filters as filter_ui
from .components import freshness as freshness_ui
from .components import loading
from .components import pager as pager_ui
from .components import table as table_ui
from .components.actions import muted, overflow, primary, quiet
from .components.empty_state import empty
from .list_columns import COLUMNS
from .state import state
from .theme import MUTED


def focus_on_owner(owner: str) -> None:
    """Open the list as one person's queue. The jump from a case page (D22).

    Built as a view rather than by writing to `state.lists.filters` directly,
    because `render` re-applies the default view whenever the column list is
    empty — which it is until Lists has been visited once. Setting the filters
    by hand would work on the second visit of a session and silently do nothing
    on the first.

    `open_only` stays on for the same reason it is the default: the question is
    what this person is carrying, not everything they have ever touched. The
    toggle is on screen for anyone who meant the second thing.
    """
    state.lists.apply(
        views.SavedView(
            name=f"Cases owned by {owner}",
            filters=TriageFilters(open_only=True, owners=[owner]),
        )
    )
    ui.navigate.to("/lists")


def _current_columns() -> list[table_ui.Column]:
    keys = state.lists.columns or views.DEFAULT_COLUMNS
    return [COLUMNS[k] for k in keys if k in COLUMNS]


def render() -> None:
    if not state.lists.columns:
        state.lists.apply(views.shared_views()[0])

    loading.while_loading(
        f"Loading {state.lists.view_name.lower()}…",
        _warm,
        lambda _: _page(),
        on_error=errors.error_region,
    )


def _warm() -> None:
    """Every query the page needs, off the event loop and all at once.

    The title needs freshness, the filter row needs facets, and the table needs
    the list. None of the three depends on the others, so they go out together
    and the page waits once instead of three times.

    Nothing is returned. `prefetch` fills the cache and swallows what fails, so
    `_page` asks for each value again through the ordinary path — which is a
    cache hit, or the same failure reported by the part of the page that wanted
    it rather than by the whole screen.
    """
    data.prefetch(
        lambda: data.freshness(state.era, config.STALE_DAYS),
        lambda: data.facets(state.era, extended=True),
        _query,
    )


def _page() -> None:
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
    state.lists.apply(view)
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
    """Everything this screen shows, re-read from the warehouse.

    Including the facets, which live in their own cache on a much longer
    window. Leaving them out meant a user who explicitly asked for fresh data
    could still be choosing from an hour-old list of owners and departments —
    and the one thing an explicit refresh must not do is refresh only some of
    what is on the screen.
    """
    from .. import cache

    cache.results.invalidate("triage")
    cache.results.invalidate("freshness")
    cache.facets.invalidate()
    ui.notify("Reloaded from BigQuery", type="positive")
    # A reload rather than `body.refresh()`, because refreshing redraws on the
    # event loop and `body` asks the warehouse three times while it does. With
    # the caches just emptied every one of those is a miss, so the window would
    # freeze — with no spinner, since the placeholder is installed by `render` —
    # for the whole of the extended-facet query, which has an hour-long TTL
    # precisely because it is slow. Reloading re-enters `render`, which says
    # what it is waiting for and issues the three concurrently.
    ui.navigate.reload()


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
        page = _whole_list()
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
    note = f"Exported {len(page.rows):,} rows (metadata only)"
    if page.total_matches > len(page.rows):
        note += f" — the first {TRIAGE_LIMIT:,} of {page.total_matches:,} matches"
    ui.notify(note, type="positive")


def _query():
    """The page the table is showing."""
    return data.triage(
        state.era,
        state.lists.filters,
        sort=state.lists.sort,
        descending=state.lists.descending,
        limit=TRIAGE_PAGE_SIZE,
        offset=state.lists.offset,
    )


def _whole_list():
    """Every matching row up to the fetch ceiling, for the export.

    An export of what happens to be on screen is a footgun: the user asked for
    the view, not for rows 51 to 100 of it.
    """
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
    # A different order is a different first page.
    state.lists.offset = 0
    body.refresh()


def _on_page(offset: int) -> None:
    state.lists.offset = offset
    body.refresh()


def _filter_controls() -> None:
    """The priority filters — FR-LIST-6 plus Owner (D22). Twice; see filters.py."""
    facets = _facets()
    current = state.lists.filters

    def rerun() -> None:
        # Narrowing the list invalidates where you were in it — staying on
        # page 4 of a result that now has two pages shows nothing at all.
        state.lists.offset = 0
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
    # Owner sits first among the dimensions, next to the Open only toggle. The
    # two together are "what is on my plate", which is the question this page
    # exists for; everything after them narrows an answer that already exists.
    filter_ui.multi_select("Owner", facets.owners, current.owners, setter("owners"))
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
        if not page.rows and state.lists.offset:
            # The result shrank out from under a page we were already past —
            # a fresh snapshot or an expired cache entry, since every filter
            # change resets the offset itself. Fall back to the top rather
            # than reporting that nothing matches, which would be false.
            state.lists.offset = 0
            page = _query()
    except Exception as exc:  # noqa: BLE001
        errors.error_region(exc)
        return

    if not page.rows:
        empty(
            "No cases match these filters in this snapshot.",
            [("Clear filters", _clear_filters)],
            icon="inbox",
        )
        return

    with ui.row().classes("w-full items-center justify-between").style("margin:4px 0 8px 0"):
        _pager(page)
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

    if page.total_matches > TRIAGE_PAGE_SIZE:
        # Repeated under the table. Fifty rows is about three screens, so a
        # pager only at the top is one the reader has to scroll back up to
        # reach — at the exact moment they have finished the page and know they
        # want the next one. Drawn only when there is a next page to want, so a
        # short list still ends at its last row.
        with ui.row().classes("w-full justify-end").style("margin-top:12px"):
            _pager(page)


def _pager(page) -> None:
    pager_ui.pager(
        offset=state.lists.offset,
        shown=len(page.rows),
        total=page.total_matches,
        page_size=TRIAGE_PAGE_SIZE,
        on_change=_on_page,
    )


def _clear_filters() -> None:
    state.lists.filters = TriageFilters(open_only=state.lists.filters.open_only)
    state.lists.offset = 0
    body.refresh()
    header_meta.refresh()


def _open_case(row: TriageRow) -> None:
    ui.navigate.to(f"/case/{row.case_number}")


