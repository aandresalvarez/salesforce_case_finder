"""SQL — the escape hatch, kept honest.

FR-SQL-3: every query typed here goes through `assert_read_only` and a dry run
before it executes. That is not because the user is untrusted — it is because
the ADC the app runs under probably *can* write, and a read-only app should not
depend on every analyst having read-only grants.

FR-SQL-5 makes this the one screen where a second prominent button is correct.
Run is primary; Check cost is a real secondary, because the whole point of a
free-form query box is that the person typing cannot know what their query will
scan until they ask.
"""

from __future__ import annotations

from nicegui import ui

from .. import bq, config, data
from ..models import show
from . import shell
from .components.table import Column, data_table
from .shell import CANVAS, muted, primary, quiet, secondary, state

STARTER = """-- Cases opened per year.
SELECT created_year, COUNT(*) AS cases
FROM `{project}.{dataset}.dim_case`
GROUP BY created_year
ORDER BY created_year
LIMIT 200"""


class SqlState:
    text: str = ""
    result: bq.QueryResult | None = None
    error: str = ""
    estimate: int | None = None


page = SqlState()


def render() -> None:
    with ui.column().classes("w-full").style("gap:0"):
        with ui.row().classes("w-full items-baseline justify-between"):
            with ui.column().style("gap:1px"):
                ui.label("SQL").classes("cf-h1")
                muted(
                    "Read-only. One SELECT at a time, capped at "
                    f"{config.MAX_BYTES_BILLED / 1024**3:,.0f} GB scanned per query."
                )
            _schema_hint()

        _editor()
        _actions()
        body()


def _schema_hint() -> None:
    """The table names, behind a disclosure — nobody needs them on screen twice."""
    era = state.era
    with ui.expansion("Tables").classes("cf-muted").style("max-width:420px"):
        names = ["dim_case", "fct_conversation_turn"]
        if era.has_history:
            names += ["case_history", "attachment_blob"]
        for name in names:
            ui.label(f"{config.PROJECT}.{era.dataset}.{name}").classes("cf-mono")
        ui.label(f"{config.PROJECT}.salesforce_raw.Case").classes("cf-mono")
        ui.label(f"{config.PROJECT}.salesforce_raw.User").classes("cf-mono")


def _editor() -> None:
    if not page.text:
        page.text = STARTER.format(project=config.PROJECT, dataset=state.era.dataset)

    editor = (
        ui.textarea(value=page.text)
        .props("outlined autogrow input-style=font-family:ui-monospace,Menlo,monospace")
        .classes("w-full cf-mono")
        .style(f"margin-top:16px; background:{CANVAS}")
    )
    editor.on_value_change(lambda event: _typed(event.value))
    # Ctrl/Cmd-Enter runs, because anyone reaching this page expects it to.
    editor.on("keydown.ctrl.enter", _run)
    editor.on("keydown.meta.enter", _run)


def _typed(value: str) -> None:
    page.text = value or ""
    # A stale estimate beside edited text is worse than no estimate. Only
    # redraw when there was one to invalidate — this fires on every keystroke.
    if page.estimate is not None:
        page.estimate = None
        cost_line.refresh()


def _actions() -> None:
    with ui.row().classes("w-full items-center").style(
        "gap:8px; margin-top:10px; flex-wrap:wrap"
    ):
        primary("Run", _run, icon="play_arrow")
        secondary("Check cost", _estimate, icon="calculate")
        quiet("Clear", _clear)
        ui.space()
        cost_line()
        muted("⌘↵ to run")


@ui.refreshable
def cost_line() -> None:
    if page.estimate is not None:
        muted(f"Would scan {page.estimate / 1024**2:,.1f} MB")


@ui.refreshable
def body() -> None:
    if page.error:
        with ui.column().classes("w-full").style("gap:6px; margin-top:16px"):
            ui.label(page.error.splitlines()[0]).classes("cf-h2")
            detail = "\n".join(page.error.splitlines()[1:]).strip()
            if detail:
                with ui.expansion("Details").classes("cf-muted"):
                    ui.label(detail).classes("cf-error")
        return

    result = page.result
    if result is None:
        return

    if not result.rows:
        muted("The query ran and returned no rows.").style("margin-top:18px")
        return

    with ui.row().classes("w-full items-center").style("gap:10px; margin:20px 0 4px 0"):
        muted(f"{len(result.rows):,} row{'s' if len(result.rows) != 1 else ''}")
        muted("· " + result.cost_note)
        ui.space()
        quiet("Copy as TSV", lambda: _copy_tsv(result), icon="content_copy")

    columns = [
        Column(name, name, lambda row, k=name: show(row.get(k)), sortable=False)
        for name in result.rows[0]
    ]
    data_table(columns, result.rows, on_row_click=lambda _row: None)


def _run() -> None:
    page.error = ""
    page.result = None
    try:
        page.result = data.run_sql(page.text)
    except Exception as exc:  # noqa: BLE001
        page.error = f"{shell.friendly(exc)}\n{type(exc).__name__}: {exc}"
    body.refresh()


def _estimate() -> None:
    page.error = ""
    try:
        page.estimate = data.estimate_sql(page.text)
    except Exception as exc:  # noqa: BLE001
        page.estimate = None
        page.error = f"{shell.friendly(exc)}\n{type(exc).__name__}: {exc}"
        cost_line.refresh()
        body.refresh()
        return
    cost_line.refresh()
    body.refresh()


def _clear() -> None:
    page.text = ""
    page.result = None
    page.error = ""
    page.estimate = None
    ui.navigate.reload()


def _copy_tsv(result: bq.QueryResult) -> None:
    """Clipboard, not a file.

    A free-form query can select body text, so its output may carry PHI. Writing
    it to disk would break the no-PHI-at-rest rule in spec section 9.3; putting
    it on the clipboard leaves the decision with the person who wrote the query.
    """
    headers = list(result.rows[0].keys())
    lines = ["\t".join(headers)]
    for row in result.rows:
        lines.append("\t".join(str(row.get(h, "")).replace("\t", " ") for h in headers))
    ui.clipboard.write("\n".join(lines))
    ui.notify(f"{len(result.rows):,} rows copied", type="positive")
