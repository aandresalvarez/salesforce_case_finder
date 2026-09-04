"""Whether a case can actually be read: the wait, the body, and the columns.

Three complaints about the same screen, and they share a shape — the app had
the information and was not presenting it. Opening a case took about six
seconds behind a window that went blank, so the only feedback was the absence
of feedback. A comment body that was the serialised intake form rendered as one
seven-hundred-character line of JSON. And the description column, the only one
that says what a case is about, had been squeezed to 64px by columns that all
declared a fixed width while it declared none.

The tests here are structural, in the same style as `test_visual.py` and for
the same reason: what breaks is a spinner that is never replaced, a body that
takes the wrong reading, a column that silently disappears. All three can be
asserted on the element tree, and none of them need a browser.
"""

from __future__ import annotations

import asyncio

import pytest
import synthetic
from nicegui import ui

from casefinder.models import Comment
from casefinder.ui import case_detail, lists
from casefinder.ui.components import intake_form, loading
from casefinder.ui.components import table as table_ui

# --------------------------------------------------------------------------
# Saying that something is happening
# --------------------------------------------------------------------------


def test_the_placeholder_is_a_spinner_and_a_reason(render):
    tree = render(loading.placeholder, "Opening CASE-056576…")

    assert tree.of_type("Spinner")
    assert "Opening CASE-056576…" in tree.text


def test_with_no_event_loop_the_work_still_gets_done(render):
    """A spinner that can never be replaced is worse than a slow page.

    Deferring needs a loop to defer onto. Where there is not one — a page built
    synchronously, which is how these tests render them — `while_loading` has
    to fall back to doing the work now rather than scheduling it at nothing.
    """
    tree = render(
        loading.while_loading,
        "Loading…",
        lambda: "the answer",
        lambda value: ui.label(value),
        on_error=_unexpected,
    )

    assert "the answer" in tree.text
    assert not tree.of_type("Spinner")


def test_a_load_that_fails_leaves_an_error_and_not_a_spinner(render):
    seen: list[Exception] = []

    def boom():
        raise RuntimeError("the warehouse said no")

    tree = render(
        loading.while_loading,
        "Loading…",
        boom,
        lambda value: None,
        on_error=seen.append,
    )

    assert [str(exc) for exc in seen] == ["the warehouse said no"]
    assert not tree.of_type("Spinner")


def test_the_spinner_reaches_the_screen_before_the_query_starts(render, monkeypatch):
    """The bug this whole module exists for.

    Building a placeholder and then running the query in the same pass of the
    event loop sends the browser nothing until the query has already finished —
    the spinner is constructed, and the user sees the blank window it was meant
    to prevent. The work has to be scheduled for *after* the page function
    returns, which is what makes the placeholder observable here with `load`
    still not having been called.
    """
    scheduled: list = []
    started: list[str] = []
    monkeypatch.setattr(loading, "_can_defer", lambda: True)
    monkeypatch.setattr(
        loading.ui, "timer", lambda _interval, cb, **kw: scheduled.append(cb)
    )

    def load() -> str:
        started.append("load")
        return "the answer"

    tree = render(
        loading.while_loading,
        "Opening CASE-056576…",
        load,
        lambda value: ui.label(value),
        on_error=_unexpected,
    )

    assert tree.of_type("Spinner"), "no placeholder was drawn"
    assert "Opening CASE-056576…" in tree.text
    assert started == [], "the query ran before the placeholder could be sent"

    # And once the loop gets its turn, the placeholder is replaced rather than
    # accumulated alongside the result.
    with tree.client:
        asyncio.run(scheduled[0]())

    assert started == ["load"]
    assert "the answer" in tree.text
    assert not tree.of_type("Spinner")


def test_opening_a_case_says_which_case_it_is_opening(warehouse, monkeypatch):
    notes = _notes(monkeypatch)

    case_detail.render("case-056576")

    assert notes == ["Opening CASE-056576…"]


def test_every_slow_tab_has_something_to_show_while_it_loads(render, warehouse, monkeypatch):
    """Comments is the exception, and deliberately so — `render` prefetched it,
    so a spinner there announces a cache hit."""
    notes = _notes(monkeypatch)
    tree = render(case_detail._tabs, warehouse.header)
    tabs = tree.of_type("Tabs")[0]

    for name in ("Messages", "Timeline", "Files"):
        with tree.client:
            tabs.value = name

    assert notes == ["Loading messages…", "Building the timeline…", "Looking for files…"]


def _notes(monkeypatch) -> list[str]:
    """Record the note each deferred load announces itself with.

    Asserting on the wiring rather than on a rendered spinner, because the test
    harness renders synchronously and so takes `while_loading`'s inline path —
    where there is correctly no spinner to find.
    """
    captured: list[str] = []
    original = loading.while_loading

    def spy(note, load, then, **kwargs):
        captured.append(note)
        return original(note, load, then, **kwargs)

    monkeypatch.setattr(loading, "while_loading", spy)
    return captured


def _unexpected(exc: Exception) -> None:
    raise AssertionError(f"unexpected failure: {exc}")


# --------------------------------------------------------------------------
# Reading a body
# --------------------------------------------------------------------------


def test_the_intake_form_reads_as_a_form_rather_than_as_json(render):
    tree = render(intake_form.body, synthetic.intake_payload())
    texts = tree.texts()

    assert "Funding status" in texts
    assert "IRB protocol" in texts
    # The failure mode being ruled out: the whole payload on one label. It is
    # still reachable — see the disclosure test below — but not what is read.
    blobs = [e for e in tree.of_type("Label") if e.text.startswith("{")]
    assert blobs and all(tree.is_inside(e, "Expansion") for e in blobs)


def test_a_body_that_is_prose_stays_prose(render):
    body = "Could you pull an OMOP cohort for the study we discussed? Thanks."
    tree = render(intake_form.body, body)

    assert body in tree.texts()
    assert not tree.with_class("cf-form")


def test_an_empty_body_says_so_rather_than_rendering_nothing(render):
    tree = render(intake_form.body, None)

    assert "(empty)" in tree.texts()


def test_the_original_record_is_always_one_click_away(render):
    """A formatted view is an interpretation. Someone acting on a case has to
    be able to check it against what the record literally says."""
    payload = synthetic.intake_payload()
    tree = render(intake_form.body, payload)

    expansions = [e for e in tree.of_type("Expansion") if e.text == "Original record"]
    assert len(expansions) == 1
    assert payload in tree.texts()


def test_no_part_of_a_body_is_rendered_as_markup(render):
    """Spec section 9.5. These are pasted email with a free-text box in the
    middle of them; every value goes through `ui.label`, which escapes."""
    payload = (
        '{"Subject":"<script>alert(1)</script>","Origin":"Web",'
        '"Description":"Ends with <b>bold</b> and an & ampersand."}'
    )
    tree = render(intake_form.body, payload)

    assert tree.of_type("Html", "Markdown") == []
    assert "<script>alert(1)</script>" in tree.texts()


def test_the_request_keeps_its_paragraphs_on_screen(render):
    """`pre-wrap` rather than the browser's default, which would collapse the
    line breaks the requester typed into one paragraph."""
    tree = render(intake_form.body, synthetic.intake_payload())

    (block,) = tree.with_class("cf-form-text")
    assert "\n\n" in block.text


def test_a_comment_that_is_a_form_is_read_as_one(render, warehouse):
    warehouse.comments = [
        Comment.from_row(
            {
                "turn_seq": 1,
                "who": "Requester",
                "direction": "inbound",
                "source_object": "EmailMessage",
                "body": synthetic.intake_payload(),
            }
        )
    ]
    tree = render(case_detail.comment_stream, warehouse.header)

    assert "Funding status" in tree.texts()


def test_a_description_that_is_a_form_is_read_the_same_way(render, warehouse):
    """The description is the same warehouse text in the same two shapes, so it
    must not be the one place left showing JSON."""
    from casefinder.ui.components import metadata as metadata_ui

    tree = render(metadata_ui.description_block, synthetic.intake_payload())

    assert "Funding status" in tree.texts()


# --------------------------------------------------------------------------
# Columns that fit
# --------------------------------------------------------------------------


def test_the_description_never_gives_way(render, warehouse):
    """FR-LIST-4 says "truncated if width allows", which is an instruction to
    keep the column and shorten it. It used to drop first."""
    assert lists.COLUMNS["description"].drop == 0

    tree = render(lists.render)
    headers = [e for e in tree.of_type("Label") if e.text == "Description"]
    assert headers, "the description column is not on the list"
    assert not any("cf-drop" in c for e in headers for c in e._classes)


def test_the_columns_give_way_in_the_stated_order():
    dropping = sorted(
        ((column.drop, key) for key, column in lists.COLUMNS.items() if column.drop),
    )

    assert dropping == [(1, "funding"), (2, "department"), (3, "pi")]


def _fixed_width(hidden: set[str]) -> int:
    return sum(
        int(column.width.removesuffix("px"))
        for key, column in lists.COLUMNS.items()
        if key not in hidden and column.width.endswith("px")
    )


def test_the_description_is_never_squeezed_to_nothing():
    """The failure that made this a cascade rather than one drop.

    Under `table-layout:fixed` the description gets whatever the declared
    widths leave, and at a 1024px window — the configured minimum — they left
    exactly nothing. Not an ellipsis, not a wrapped line: a column zero pixels
    wide, with its header still in the table and its content simply absent.

    So the thresholds are arithmetic, not taste, and this re-derives them from
    the columns rather than trusting the three numbers in `table.py`. The width
    that matters in each regime is the narrowest one still in it: one pixel
    above the next threshold, or the narrowest container a supported window can
    produce for the last.
    """
    from casefinder import config

    narrowest = config.MIN_WINDOW_SIZE[0] - table_ui.PANE_CHROME
    hidden: set[str] = set()
    for step in (0, *table_ui.DROP_STEPS):
        # Step 0 is the full table: `drop=0` means "never", not "at step zero".
        if step:
            hidden |= {key for key, column in lists.COLUMNS.items() if column.drop == step}
        container = table_ui.DROP_AT.get(step + 1, narrowest - 1) + 1
        left = container - _fixed_width(hidden)
        assert left >= table_ui.DESCRIPTION_FLOOR, (
            f"at a {container}px table with {sorted(hidden)} hidden, "
            f"the description gets {left}px"
        )


def test_the_last_drop_step_is_enough_for_the_smallest_window_allowed():
    """A fourth step is only unnecessary while the window cannot get smaller."""
    from casefinder import config

    narrowest = config.MIN_WINDOW_SIZE[0] - table_ui.PANE_CHROME

    assert narrowest <= table_ui.DROP_AT[max(table_ui.DROP_STEPS)]


def test_a_column_cannot_ask_to_drop_at_a_width_nothing_matches():
    """The quiet failure this guards: a step with no rule never fires, so the
    column simply stays and the narrow layout is broken with no error."""
    column = table_ui.Column("x", "X", lambda r: "", drop=max(table_ui.DROP_STEPS) + 1)

    with pytest.raises(ValueError, match="no rule"):
        table_ui._drop_class(column)


@pytest.mark.parametrize("step", table_ui.DROP_STEPS)
def test_every_drop_step_has_a_rule_behind_it(step):
    column = table_ui.Column("x", "X", lambda r: "", drop=step)

    assert table_ui._drop_class(column) == f"cf-drop-{step}"
    assert f".cf-drop-{step}" in table_ui._CSS


def test_the_widths_are_measured_against_the_table_and_not_the_window():
    """A `@media` rule here measured the viewport, which is 240px wider than
    the table the columns are actually in, so it never fired at any size a
    person would use."""
    assert "container-type:inline-size" in table_ui._CSS
    assert "@media" not in table_ui._CSS


def test_the_table_wrapper_does_not_become_a_scroll_container():
    """`container-type: inline-size` is safe next to the sticky header; an
    `overflow` on the same wrapper would not be — setting one axis to anything
    but `visible` computes the other to `auto`, and the new scrollport would
    take the header's `position: sticky` with it."""
    wrapper = table_ui._CSS.split(".cf-table-wrap")[1].split("}")[0]

    assert "overflow" not in wrapper
