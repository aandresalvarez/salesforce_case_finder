"""What a query the app did not write may bring back, and how long it may hold
the window — D39.

The SQL and Ask pages are the two screens whose query nobody here wrote, and
until D39 they waited for it on the event loop and then drew whatever came
back. Both halves were measured failing on the real page, with BigQuery stubbed
out: a twenty-second query put up "Case Finder has stopped responding" at nine
seconds, and 41,533 rows became 290,000 elements, 1.4 GB, and a window that
reloaded itself in a loop.

The caps themselves are pinned in `test_bq.py`, beside the fake client they
need. These tests are about the pages: that they draw only what was kept, say
what was not, put a placeholder up instead of holding the loop, and never let
an answer land on a page that has since moved on.
"""

from __future__ import annotations

import asyncio

import pytest

from casefinder import ask, bq, data
from casefinder.ui import ask_page, sql_page
from casefinder.ui.components import loading

# Small enough that a capped table renders in milliseconds. The real values
# are pinned in `test_bq.py`; what matters here is what the page does with a
# result that hit them.
ROWS, CELLS = 20, 200


@pytest.fixture(autouse=True)
def small_caps(monkeypatch):
    monkeypatch.setattr(data, "FREE_FORM_ROWS", ROWS)
    monkeypatch.setattr(data, "FREE_FORM_CELLS", CELLS)


@pytest.fixture
def sql(monkeypatch) -> sql_page.SqlState:
    """The SQL page's state, fresh. It is module-level, so it outlives a render."""
    fresh = sql_page.SqlState()
    monkeypatch.setattr(sql_page, "page", fresh)
    return fresh


@pytest.fixture
def asking(monkeypatch) -> ask_page.AskState:
    """The Ask page with Vertex answering and a query already written."""
    monkeypatch.setattr(ask, "available", lambda: True)
    monkeypatch.setattr(ask, "model_name", lambda: "gemini-2.5-flash")
    monkeypatch.setattr(ask, "to_sql", lambda question, era: "SELECT 2")
    fresh = ask_page.AskState()
    fresh.question = "How many cases were opened each year?"
    fresh.sql = "SELECT created_year, COUNT(*) AS cases FROM t GROUP BY 1"
    monkeypatch.setattr(ask_page, "page", fresh)
    return fresh


@pytest.fixture
def deferred(monkeypatch) -> list:
    """Press buttons the way the running app does: the handler returns with
    its work scheduled, and the test decides when that work runs."""
    scheduled: list = []
    monkeypatch.setattr(loading, "_can_defer", lambda: True)
    monkeypatch.setattr(
        loading.background_tasks, "create", lambda work, **_: scheduled.append(work)
    )
    yield scheduled
    for work in scheduled:
        # One a test chose never to run is closed rather than left to warn.
        work.close()


def _warehouse(monkeypatch, *, total: int, columns: int = 3) -> list[str]:
    """Stand in for BigQuery: `total` rows exist, and `max_rows` come back.

    Patched at `bq.run` rather than `data.run_sql`, so the caps in between are
    the real ones. Returns the list of queries it was asked to run.
    """
    asked: list[str] = []

    def run(sql, params=None, *, preflight=False, max_rows=None):
        asked.append(sql)
        shown = total if max_rows is None else min(total, max_rows)
        rows = [{f"column_{i}": f"value {n}" for i in range(columns)} for n in range(shown)]
        return bq.QueryResult(rows=rows, bytes_processed=1024, cache_hit=False, total_rows=total)

    monkeypatch.setattr(bq, "run", run)
    return asked


def _button(tree, label: str):
    return next(b for b in tree.buttons() if b.text == label)


def _run_scheduled(tree, scheduled: list) -> None:
    assert len(scheduled) == 1, "a press should schedule exactly one piece of work"
    with tree.client:
        asyncio.run(scheduled.pop())


# --------------------------------------------------------------------------
# The SQL page
# --------------------------------------------------------------------------


def test_run_draws_only_what_was_kept_and_says_what_was_not(render, sql, monkeypatch):
    _warehouse(monkeypatch, total=41_533)
    tree = render(sql_page.render)

    tree.press(_button(tree, "Run"))

    assert len(tree.with_class("cf-row")) == ROWS
    assert f"First {ROWS} of 41,533 rows" in tree.text
    assert "Filter or aggregate to see the rest." in tree.text


def test_run_waits_on_a_worker_with_a_placeholder_up(render, sql, deferred, monkeypatch):
    """The other half of D39. A query run inside the click handler held the
    loop that answers the window, so a slow one read as a dead program."""
    asked = _warehouse(monkeypatch, total=2)
    tree = render(sql_page.render)

    tree.press(_button(tree, "Run"))

    assert asked == [], "BigQuery was asked before the handler gave the loop back"
    assert tree.of_type("Spinner")
    assert "Running the query…" in tree.text

    _run_scheduled(tree, deferred)

    assert len(asked) == 1
    assert "2 rows" in tree.text
    assert not tree.of_type("Spinner")
    assert not sql.running


def test_a_second_run_while_one_is_on_its_way_starts_nothing(render, sql, deferred, monkeypatch):
    """The first is already billed; a second would only race it to the page."""
    _warehouse(monkeypatch, total=2)
    tree = render(sql_page.render)
    run = _button(tree, "Run")

    tree.press(run)
    tree.press(run)

    assert len(deferred) == 1


def test_an_answer_that_arrives_after_clear_is_dropped(render, sql, deferred, monkeypatch):
    """BigQuery finishes the query regardless. What must not happen is its
    rows appearing on a page the reader has just emptied."""
    _warehouse(monkeypatch, total=2)
    monkeypatch.setattr(sql_page.ui.navigate, "reload", lambda: None)
    tree = render(sql_page.render)

    tree.press(_button(tree, "Run"))
    tree.press(_button(tree, "Clear"))
    _run_scheduled(tree, deferred)

    assert sql.result is None
    assert not sql.running
    assert not tree.with_class("cf-row")


def test_an_estimate_that_fails_mid_run_does_not_hide_the_answer(
    render, sql, deferred, monkeypatch
):
    """Check cost stays pressable while a query runs, which it never was while
    Run held the loop. Its failure must not outrank the answer that follows."""

    def no_estimate(text):
        raise RuntimeError("the dry run failed")

    _warehouse(monkeypatch, total=2)
    monkeypatch.setattr(data, "estimate_sql", no_estimate)
    tree = render(sql_page.render)

    tree.press(_button(tree, "Run"))
    tree.press(_button(tree, "Check cost"))
    _run_scheduled(tree, deferred)

    assert "2 rows" in tree.text
    assert "BigQuery could not run that." not in tree.text


def test_a_query_that_fails_leaves_an_error_and_not_a_spinner(render, sql, deferred, monkeypatch):
    def refuse(sql, params=None, *, preflight=False, max_rows=None):
        raise RuntimeError("Syntax error: Unexpected keyword FROM at [1:8]")

    monkeypatch.setattr(bq, "run", refuse)
    tree = render(sql_page.render)

    tree.press(_button(tree, "Run"))
    _run_scheduled(tree, deferred)

    assert "BigQuery could not run that." in tree.text
    assert "Unexpected keyword FROM" in tree.text
    assert not tree.of_type("Spinner")
    assert not sql.running


def test_copy_as_tsv_copies_what_is_shown_and_says_so(render, sql, monkeypatch):
    """The clipboard gets the rows on the screen, and the notice does not let
    them pass for the whole answer."""
    written: list[str] = []
    told: list[str] = []
    monkeypatch.setattr(sql_page.ui.clipboard, "write", written.append)
    monkeypatch.setattr(sql_page.ui, "notify", lambda message, **_: told.append(message))
    _warehouse(monkeypatch, total=41_533)
    tree = render(sql_page.render)

    tree.press(_button(tree, "Run"))
    tree.press(_button(tree, "Copy as TSV"))

    assert len(written[0].splitlines()) == 1 + ROWS
    assert told == [f"First {ROWS} of 41,533 rows copied"]


# --------------------------------------------------------------------------
# The Ask page
# --------------------------------------------------------------------------


def test_ask_draws_only_the_rows_that_fit_and_says_why(render, asking, monkeypatch):
    """Model-written SQL is `SELECT *` often enough that the wide case is the
    one to check here: fewer rows, and the advice that fits."""
    _warehouse(monkeypatch, total=41_533, columns=80)
    tree = render(ask_page.render)

    tree.press(_button(tree, "Run query"))

    fits = CELLS // 80
    assert len(tree.with_class("cf-row")) == fits
    assert f"First {fits} of 41,533 rows" in tree.text
    assert "80 columns wide" in tree.text


def test_a_new_question_drops_the_answer_to_the_old_one(render, asking, deferred, monkeypatch):
    """A query that is still running when the reader asks something else is
    answering a question that is no longer on the screen."""
    _warehouse(monkeypatch, total=2)
    tree = render(ask_page.render)

    tree.press(_button(tree, "Run query"))
    assert "Running the query…" in tree.text
    assert "GROUP BY 1" in tree.text, "the query under review left the screen while it ran"

    example = next(e for e in tree.of_type("Label") if e.text == ask_page.EXAMPLES[0])
    tree.press(example)
    _run_scheduled(tree, deferred)

    assert asking.sql == "SELECT 2"
    assert asking.result is None
    assert not asking.running
    assert not tree.with_class("cf-row")
