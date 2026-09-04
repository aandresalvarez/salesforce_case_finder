"""Ask — a question in, SQL out, and nothing runs without a second click.

Two things make this safe enough to ship (spec section 9.2 and FR-ASK-4):

Nothing from the corpus is sent to Vertex. The prompt is the user's question
plus a static schema description; no case row, body, subject, or search result
ever leaves the machine. That is what keeps a PHI corpus and a hosted model in
the same application.

The generated SQL is shown before it runs. The model writes a query, the user
reads it, and only then is there a Run button — which is also the one primary
action on this screen. Auto-running model output against a warehouse is how a
plausible-looking query with a wrong join silently returns a wrong answer.
"""

from __future__ import annotations

from nicegui import ui

from .. import ask, data
from ..config import ERAS
from . import shell
from .components import filters as filter_ui
from .components.table import Column, data_table
from .shell import muted, primary, quiet, secondary, state

EXAMPLES = (
    "How many cases were opened each year?",
    "Which owners closed the most cases in 2024?",
    "What are the ten longest email threads?",
)


class AskState:
    """Page-local state. Deliberately not on `shell.state`.

    A generated query is a scratchpad, not a session preference: leaving the
    page should not preserve a half-reviewed query to be run later out of
    context.
    """

    question: str = ""
    sql: str = ""
    error: str = ""
    result = None
    ran_sql: str = ""


page = AskState()


def render() -> None:
    with ui.column().classes("w-full cf-reading").style("gap:0"):
        ui.label("Ask a question").classes("cf-h1")
        muted(
            "Gemini writes the query; you read it before it runs. Your question "
            "and the table layout are all that is sent — no case data."
        )

        if not ask.available():
            _unavailable()
            return

        _question_box()
        body()


def _unavailable() -> None:
    """FR-ASK-1: say why, once, and point at the tab that still works."""
    reason = ask.why_unavailable()
    with ui.column().classes("w-full").style("gap:8px; margin-top:20px"):
        with ui.row().classes("cf-note w-full"):
            ui.label(
                "Natural-language mode is switched off because Vertex AI is not "
                "available to this project."
            )
        with ui.expansion("Details").classes("cf-muted"):
            ui.label(reason).classes("cf-error")
        with ui.row().style("margin-top:4px"):
            secondary("Write SQL instead", lambda: ui.navigate.to("/sql"), icon="code")


def _question_box() -> None:
    def submit() -> None:
        page.question = box.value or ""
        _generate()

    with ui.row().classes("w-full items-center").style(
        "gap:8px; margin-top:18px; flex-wrap:nowrap"
    ):
        box = (
            ui.input(placeholder="Ask about the cases…", value=page.question)
            .props("outlined dense clearable autofocus")
            .style("flex:1; font-size:14px")
            .on("keydown.enter", submit)
        )
        filter_ui.era_select(state.era_key, ERAS, _set_era)

    with ui.row().classes("items-center").style("gap:14px; margin-top:8px; flex-wrap:wrap"):
        muted("Try:")
        for example in EXAMPLES:
            ui.label(example).classes("cf-muted").style(
                "cursor:pointer; text-decoration:underline dotted"
            ).on("click", lambda _=None, text=example: _use_example(text))


def _use_example(text: str) -> None:
    page.question = text
    _generate()


def _set_era(key: str) -> None:
    state.era_key = key
    # The schema differs between eras, so a query written against the other one
    # may not even parse here.
    page.sql = ""
    page.result = None
    body.refresh()


def _generate() -> None:
    page.sql = ""
    page.result = None
    page.error = ""
    if not page.question.strip():
        body.refresh()
        return
    try:
        page.sql = ask.to_sql(page.question, state.era)
    except Exception as exc:  # noqa: BLE001
        page.error = str(exc)
    body.refresh()


@ui.refreshable
def body() -> None:
    if page.error:
        with ui.row().classes("cf-note w-full").style("margin-top:18px"):
            ui.label(page.error)
        return
    if not page.sql:
        return

    ui.label("Generated query").classes("cf-h2").style("margin:22px 0 6px 0")
    ui.code(page.sql, language="sql").classes("w-full").style("font-size:12.5px")

    with ui.row().classes("w-full items-center").style(
        "gap:8px; margin-top:12px; flex-wrap:wrap"
    ):
        # The single filled button on this screen — UX-INV-1.
        primary("Run query", _run, icon="play_arrow")
        quiet("Check cost", _estimate, icon="calculate")
        quiet("Edit in SQL", _hand_off, icon="code")
        ui.space()
        if ask.model_name():
            muted(ask.model_name())

    _results()


def _results() -> None:
    if page.result is None:
        return
    result = page.result
    rows = result.rows
    if not rows:
        muted("The query ran and returned no rows.").style("margin-top:18px")
        return

    with ui.row().classes("w-full items-center").style("gap:10px; margin:20px 0 4px 0"):
        muted(f"{len(rows):,} row{'s' if len(rows) != 1 else ''}")
        muted("· " + result.cost_note)

    columns = [
        Column(name, name, lambda row, k=name: _cell(row.get(k)), sortable=False)
        for name in rows[0]
    ]
    # Model-written SQL returns arbitrary shapes, so rows are plain dicts and
    # there is nothing to navigate to — clicking a row does nothing.
    data_table(columns, rows, on_row_click=lambda _row: None)


def _cell(value) -> str:
    from ..models import show

    return show(value)


def _run() -> None:
    page.error = ""
    page.result = None
    try:
        page.result = data.run_sql(page.sql)
        page.ran_sql = page.sql
    except Exception as exc:  # noqa: BLE001
        page.error = shell.friendly(exc) + f"\n\n{type(exc).__name__}: {exc}"
    body.refresh()


def _estimate() -> None:
    try:
        size = data.estimate_sql(page.sql)
    except Exception as exc:  # noqa: BLE001
        ui.notify(shell.friendly(exc), type="warning")
        return
    ui.notify(f"This query would scan {size / 1024**2:,.1f} MB", type="info")


def _hand_off() -> None:
    """Move the query to the SQL page rather than growing an editor here."""
    from . import sql_page

    sql_page.page.text = page.sql
    ui.navigate.to("/sql")
