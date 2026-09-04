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

from ..shell import ACCENT, LINE, MUTED, register_css


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
    # How a cell handles text that does not fit. `one_line` clips it with an
    # ellipsis, `clamp` keeps the first two lines. Both default off: a table
    # rendering arbitrary SQL results has no idea what is in its cells, and
    # silently hiding output there would be worse than a tall row.
    one_line: bool = False
    clamp: bool = False
    subdued: bool = False


# `table-layout:fixed` is load-bearing rather than cosmetic. Under the default
# auto layout a browser sizes each column to its content, so one case whose
# description is a pasted email thread drags every other column narrow — which
# is exactly what happened: `Last activity` and `Funded` were crushed against
# the right edge while `Description` took two fifths of the table. Fixed layout
# makes the declared widths authoritative and gives the leftover to the one
# column that asked for `auto`, so a row's height stops depending on its
# content and the header stops depending on the row.
_CSS = f"""
.cf-table {{ width:100%; border-collapse:collapse; table-layout:fixed; }}
.cf-table th {{
  text-align:left; padding:7px 10px; border-bottom:1px solid {LINE};
  white-space:nowrap; user-select:none;
  overflow:hidden; text-overflow:ellipsis;
}}
.cf-table th.cf-sortable {{ cursor:pointer; }}
.cf-table th.cf-sortable:hover {{ color:{ACCENT}; }}
.cf-table td {{
  padding:8px 10px; border-bottom:1px solid {LINE};
  vertical-align:top; overflow-wrap:anywhere; line-height:1.45;
}}
.cf-table tbody tr:hover {{ background:rgba(37,99,235,.045); }}
/* One line for the identifying columns: a wrapped owner name pushes the row
   to two lines and undoes the density the rest of this file is for. */
.cf-cell-1 {{ white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.cf-truncate {{
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;
  overflow:hidden;
}}
@media (max-width: 1180px) {{ .cf-drop {{ display:none; }} }}
"""

# Above this length a cell gets its full text as a `title`, so hovering it
# shows what the ellipsis took. A character count rather than a measurement,
# because the table has no layout engine to ask and the cost of guessing wrong
# is a tooltip on a cell that did not need one. The narrowest column that ever
# truncates is around this many characters wide; below it nothing is hidden and
# the attribute would be markup repeating what is already on the screen.
_TITLE_AT = 15


def _ensure_css() -> None:
    register_css("table", _CSS)


def _quotable(text: str) -> str:
    """Make a string safe to pass through NiceGUI's props parser.

    `props('title="…"')` is parsed with a regex, and a double quote inside the
    value ends it early: the parser then reads the rest as more props and
    silently produces something like `{'the': True}` — no title, and a stray
    attribute on the element. Case descriptions are full of quotes, because the
    intake form arrives serialised as JSON inside the message body, so this is
    the common path rather than the odd one.

    Nothing is escaped away, only swapped: a tooltip is read, not parsed, and a
    typographic quote says the same thing to the person hovering the cell.
    """
    return text.replace('"', "”")


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
                            if column.one_line:
                                label.classes("cf-cell-1")
                            if column.clamp:
                                label.classes("cf-truncate")
                            if (column.one_line or column.clamp) and len(text) > _TITLE_AT:
                                # The browser's own tooltip rather than a
                                # `ui.tooltip`, which is a Quasar component and
                                # would be four hundred more elements on a
                                # fifty-row page to say what an attribute says.
                                label.props(f'title="{_quotable(text)}"')
                            if column.subdued:
                                label.style(f"color:{MUTED}")
                            if column.numeric:
                                label.style("font-variant-numeric:tabular-nums")
