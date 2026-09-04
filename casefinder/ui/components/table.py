"""The compact list table.

Hand-rolled rather than wrapped around a datagrid, for two reasons the spec
forces:

Sorting is server-side. A list is capped at 500 rows, so sorting the page in
the browser would order the wrong set — click "Owner" on a 500-row window of
1,714 open cases and a grid would sort those 500, not re-ask for the first 500
by owner. Header clicks therefore call back and re-run `triage_list`, which
means the header needs a real click handler rather than a grid's built-in.

UX-T3 forbids an Open button per row. Navigation is the row itself. Building
the rows here means there is no cell slot for a button to creep into later.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from nicegui import ui

from ..shell import ACCENT, LINE, MUTED


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    render: Callable[[Any], str]
    width: str = "auto"
    sortable: bool = True
    numeric: bool = False
    # Columns the spec allows to disappear before the others when space runs out.
    droppable: bool = False


_CSS = f"""
.cf-table {{ width:100%; border-collapse:collapse; }}
.cf-table th {{
  text-align:left; padding:7px 10px; border-bottom:1px solid {LINE};
  white-space:nowrap; user-select:none;
}}
.cf-table th.cf-sortable {{ cursor:pointer; }}
.cf-table th.cf-sortable:hover {{ color:{ACCENT}; }}
.cf-table td {{
  padding:7px 10px; border-bottom:1px solid {LINE};
  vertical-align:top; overflow-wrap:anywhere;
}}
.cf-table tbody tr:hover {{ background:rgba(37,99,235,.045); }}
.cf-truncate {{
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;
  overflow:hidden;
}}
@media (max-width: 1180px) {{ .cf-drop {{ display:none; }} }}
"""

_css_added = False


def _ensure_css() -> None:
    global _css_added
    if not _css_added:
        ui.add_head_html(f"<style>{_CSS}</style>")
        _css_added = True


def data_table(
    columns: Sequence[Column],
    rows: Sequence[Any],
    *,
    on_row_click: Callable[[Any], None],
    sort_key: str = "",
    descending: bool = True,
    on_sort: Callable[[str], None] | None = None,
) -> None:
    """A compact table whose rows are the navigation.

    `on_sort` receives the clicked column key; the caller decides whether that
    means "sort by this" or "reverse the current sort" and re-queries.
    """
    _ensure_css()
    with ui.element("table").classes("cf-table"):
        with ui.element("thead"), ui.element("tr"):
            for column in columns:
                classes = "cf-drop" if column.droppable else ""
                if column.sortable and on_sort is not None:
                    classes += " cf-sortable"
                cell = ui.element("th").classes(classes.strip())
                cell.style(
                    f"width:{column.width};"
                    "font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;"
                    f"color:{MUTED};font-weight:600;"
                )
                with cell:
                    with ui.row().style("gap:3px; align-items:center; flex-wrap:nowrap"):
                        ui.label(column.label)
                        # A single small arrow on the active column only.
                        if sort_key == column.key:
                            ui.icon(
                                "arrow_downward" if descending else "arrow_upward"
                            ).style(f"font-size:13px;color:{ACCENT}")
                if column.sortable and on_sort is not None:
                    cell.on("click", lambda _=None, k=column.key: on_sort(k))
        with ui.element("tbody"):
            for row in rows:
                line = ui.element("tr").classes("cf-row")
                line.on("click", lambda _=None, r=row: on_row_click(r))
                with line:
                    for column in columns:
                        cell = ui.element("td").classes("cf-drop" if column.droppable else "")
                        with cell:
                            text = column.render(row)
                            label = ui.label(text)
                            if column.key == "case_number":
                                label.classes("cf-casenum")
                            elif column.key == "description":
                                label.classes("cf-truncate").style(f"color:{MUTED}")
                            if column.numeric:
                                label.style("font-variant-numeric:tabular-nums")


def result_count(shown: int, total: int, *, noun: str = "result") -> str:
    """`N results`, and the truncation state, stated quietly — FR-SEARCH-9."""
    plural = "" if total == 1 else "s"
    if total > shown:
        return f"{total:,} {noun}{plural} · showing first {shown:,}"
    return f"{total:,} {noun}{plural}"
