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
from casefinder.ui import case_detail, lists, saved_views
from casefinder.ui import state as ui_state
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

    for name in ("Timeline", "Files"):
        with tree.client:
            tabs.value = name

    # Two, not three: the conversation is prefetched and drawn without a
    # spinner, and Messages is no longer a tab of its own.
    assert notes == ["Building the timeline…", "Looking for files…"]


def test_the_first_screen_of_a_session_says_it_is_connecting(render, warehouse, monkeypatch):
    """The longest wait in the app, and the one with the least on the screen.

    The access probe is a BigQuery job, and on the first page of a session it
    is also where the client is constructed and the credentials discovered. It
    ran ahead of everything, so the window was empty for several seconds — no
    rail, no title, nothing to distinguish a slow start from a failed one.
    """
    from casefinder.ui import shell

    notes = _notes(monkeypatch)
    render(shell.gated, "search", lambda: None)

    assert notes[0] == "Connecting to BigQuery…"


@pytest.mark.parametrize(
    ("name", "note"),
    [
        ("open cases", "Loading open cases (weekly review)…"),
        ("search idle", "Loading filters…"),
        ("settings", "Checking the snapshot date…"),
    ],
)
def test_a_screen_that_queries_before_it_draws_says_so_first(
    name, note, render, warehouse, monkeypatch
):
    """The rule the case page established, applied to the rest of the app.

    Any screen that has to ask BigQuery something before it can draw has a
    blank window for as long as the round trip takes, and a round trip against
    this warehouse is one to five seconds. Which screens those are is not
    obvious from looking at them — Settings is a static page apart from one
    line reporting the snapshot date, and that line is a query.
    """
    from test_visual import SCREENS

    notes = _notes(monkeypatch)
    render(SCREENS[name])

    assert note in notes


def test_searching_again_waits_as_visibly_as_searching_the_first_time(
    render, warehouse, monkeypatch
):
    """The placeholder is inside the refreshable, not around it.

    Sorting, filtering, and turning the page all come back through
    `results.refresh()`, and every one of them is another query. Deferring the
    first search only would have put a spinner on the one wait the reader was
    expecting and none on the four they were not.
    """
    from casefinder.ui import search as search_ui

    shell_state = search_ui.state.search
    shell_state.text = "cohort"
    shell_state.executed = True
    tree = render(search_ui.render)

    # Installed after the first render, so anything captured here belongs to
    # the refresh. `results` is a module-level refreshable and re-runs for
    # every client that still holds one, hence a set rather than a list.
    notes = _notes(monkeypatch)
    with tree.client:
        search_ui.results.refresh()

    assert set(notes) == {"Searching…"}


# --------------------------------------------------------------------------
# Getting a name back out of a case
# --------------------------------------------------------------------------


def test_the_native_window_lets_text_be_selected():
    """Nothing in the application could be selected, and not because of its CSS.

    pywebview defaults `text_select` to False, and that appends
    `body { user-select: none }` to the document after the page's own head. No
    stylesheet in this repository could have caused it and no browser
    reproduces it, so the search for it starts and ends in the wrong place: the
    symptom is a case page where a requester's name can only be retyped, and
    the cause is one keyword argument to the window.

    The name is checked against pywebview's own signature as well as the value,
    because `window_args` is forwarded as `**kwargs` — a misspelling would not
    be a wrong setting, it would be a `TypeError` raised while opening the
    window, in the one mode no test here runs.
    """
    import inspect

    import webview

    from casefinder import main

    assert main._window_args()["text_select"] is True
    assert "text_select" in inspect.signature(webview.create_window).parameters


_ROW_SCREENS = ("open cases", "saved views", "search results", "case")

# The three places that switch selection off, all of them controls: the rail's
# destinations, the sort headers, and the search scope pill.
_UNSELECTABLE = (
    "casefinder.ui.shell",
    "casefinder.ui.components.table",
    "casefinder.ui.components.filters",
)


@pytest.mark.parametrize("module", _UNSELECTABLE)
def test_a_control_that_switches_selection_off_says_so_twice(module):
    """`user-select` on its own does nothing in the window this ships in.

    The native window is WebKit, which reads `-webkit-user-select`. Measured
    inside it, a rail chip declaring `user-select: none` computes to `text` —
    the declaration had never once had an effect, and nobody could tell,
    because pywebview was switching selection off for the whole document
    anyway. Turning that off is what makes these three rules load-bearing for
    the first time.
    """
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module(module))
    prefixed = source.count("-webkit-user-select")
    plain = source.count("user-select") - prefixed

    assert prefixed == plain, f"{module} declares selection off in only one spelling"


def test_no_body_text_opts_out_of_being_selected():
    """The four inline `user-select:text` overrides on the intake form are gone.

    They were the same bug diagnosed one label at a time — the form was the
    screen someone happened to be looking at, so the form was what got patched,
    and the fix stopped exactly at its edges. Content does not need to ask.
    """
    import inspect

    from casefinder.ui.components import intake_form

    assert "user-select" not in inspect.getsource(intake_form)


@pytest.mark.parametrize("name", _ROW_SCREENS)
def test_selecting_text_in_a_row_does_not_open_it(name, render, warehouse):
    """Selectable text makes every row-sized click target ambiguous.

    Press in the middle of a description, release at the end of it, and the
    browser reports a click on the row — which until now could only have meant
    "open this". Highlighting a name to copy it would navigate away and take
    the highlight with it, which is worse than not being able to select at all.

    The guard is client-side, so the event never leaves the browser and the row
    keeps its one handler instead of growing a second to undo the first.
    """
    from casefinder.ui import theme

    tree = _row_screen(name, warehouse, render)

    guarded = 0
    for element in tree.elements:
        for listener in element._event_listeners.values():
            if listener.type.split(".")[0] != "click":
                continue
            if listener.js_handler == theme.CLICK_UNLESS_SELECTING:
                guarded += 1
            elif "cf-row" in element._classes:
                raise AssertionError(f"{name}: a whole-row click target ignores selections")

    assert guarded, f"{name} has no row that stands down while text is selected"


def _row_screen(name: str, warehouse, render):
    """One of the screens whose rows *are* the navigation — UX-T3, no Open button.

    Built here rather than taken from `test_visual.SCREENS`, because two of the
    four are states of a screen rather than screens: search results only exist
    once a search has run, and a case only has related cases when the warehouse
    returns some.
    """
    from casefinder.models import RelatedCase, SearchHit
    from casefinder.ui import search as search_ui

    if name == "open cases":
        return render(lists.render)
    if name == "saved views":
        return render(saved_views.render)
    if name == "search results":
        warehouse.hits = [
            SearchHit.from_row(
                {
                    "case_number": "CASE-056576",
                    "subject": "Cohort extract request",
                    "status": "Open",
                    "turn_count": 6,
                    "matching_turns": 2,
                    "matched_case_fields": True,
                    "total_matches": 1,
                    "snippets": [
                        {"turn_seq": 1, "actor_role": "customer", "text": "an omop cohort"}
                    ],
                }
            )
        ]
        search_ui.state.search.text = "omop"
        search_ui.state.search.executed = True
        return render(search_ui.render)
    warehouse.related = [
        RelatedCase.from_row(
            {"case_number": "CASE-056500", "subject": "Earlier request", "same_pi": True}
        )
    ]
    return render(case_detail.render, "CASE-056576")


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
    line breaks the requester typed into one paragraph.

    Within a section now: the narrative is split under the prompts it was
    written against, and the breaks that matter are the ones inside an answer.
    """
    narrative = (
        "Summary: Registry linkage"
        "\\n\\nDescription: First paragraph."
        "\\n\\nStill the description, after a break."
        "\\n\\nQuestion: Is this feasible?"
    )
    tree = render(intake_form.body, synthetic.intake_payload(narrative=narrative))

    blocks = tree.with_class("cf-form-text")
    assert len(blocks) == 3, "the request was not split under its prompts"
    assert any("\n\n" in b.text for b in blocks), "a paragraph break was collapsed"


def test_the_request_is_split_under_the_prompts_it_answers(render):
    """Summary, Description and Question are three answers to three prompts,
    and they arrive as one string. Run together, the question is the part that
    disappears — and the question is what a support person is answering."""
    tree = render(intake_form.body, synthetic.intake_payload())

    labels = [e.text for e in tree.with_class("cf-metric-label")]
    assert "Summary" in labels and "Description" in labels and "Question" in labels


def test_the_contact_block_is_not_part_of_the_request(render):
    """`Requested For`, `Contact E-mail` and `Phone` are the form restating its
    own fields at the end of the narrative. They are the requester, and the
    requester is shown once, beside the case."""
    tree = render(intake_form.body, synthetic.intake_payload())

    labels = [e.text for e in tree.with_class("cf-metric-label")]
    assert "Requested for" not in labels and "Contact e-mail" not in labels
    assert "Availability" not in labels, "an empty prompt was drawn"


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


# --------------------------------------------------------------------------
# The rebuilt case page
# --------------------------------------------------------------------------


def _long_thread(warehouse, n: int = 60):
    """A case with more entries than anyone reads top to bottom."""
    import datetime as dt

    from casefinder.models import Comment

    warehouse.comments = [
        Comment.from_row(
            {
                "turn_seq": i,
                "turn_ts": dt.datetime(2026, 4 + i // 20, (i % 27) + 1, tzinfo=dt.timezone.utc),
                "who": synthetic.OWNER if i % 2 else synthetic.REQUESTER,
                "actor_role": "agent" if i % 2 else "customer",
                "direction": "outbound" if i % 2 else "inbound",
                "source_object": "EmailMessage",
                "subject": "Re: extract",
                "body": f"Reply number {i}.",
                "body_len": 16,
            }
        )
        for i in range(n)
    ]
    return warehouse


def test_a_long_thread_shows_both_ends_and_folds_the_middle(render, warehouse):
    """Oldest-first and flat optimises for reading a case from the beginning,
    which is the rarest thing anyone does with an active one. The opening says
    how it arrived and who picked it up; the tail is where the case is now."""
    _long_thread(warehouse, 60)

    tree = render(case_detail.comment_stream, warehouse.header)
    text = tree.text

    assert "Reply number 0." in text, "the opening is missing"
    assert "Reply number 59." in text, "the latest is missing"
    assert "Reply number 30." not in text, "the middle was not folded"
    folded = 60 - case_detail.THREAD_HEAD - case_detail.THREAD_TAIL
    assert f"{folded:,} earlier replies" in text


def test_a_short_thread_is_not_folded(render, warehouse):
    """A fold that hides fewer entries than it shows is one more control
    saying nothing."""
    _long_thread(warehouse, case_detail.FOLD_ABOVE)

    text = render(case_detail.comment_stream, warehouse.header).text

    assert "earlier replies" not in text
    assert "Reply number 0." in text and f"Reply number {case_detail.FOLD_ABOVE - 1}." in text


def test_the_months_are_marked(render, warehouse):
    """The cheapest orientation a long thread can be given: on a case that ran
    from April to September it turns a scroll position into a date."""
    _long_thread(warehouse, 60)

    text = render(case_detail.comment_stream, warehouse.header).text

    assert "Apr 2026" in text
    assert "Jun 2026" in text, "the tail did not say where it resumes"


def test_the_request_is_pinned_and_not_repeated_as_a_turn(render, warehouse):
    """The intake form arrives as the description *and* as the first turn — the
    same payload, stored twice by the integration, and the longest thing on the
    case. Pinned once, above the thread."""
    import datetime as dt

    from casefinder.models import CaseHeader, Comment

    payload = synthetic.intake_payload()
    warehouse.header = CaseHeader.from_row(
        {"case_id": "1", "case_number": "CASE-1", "subject": "Registry linkage",
         "description": payload, "status": "Open"}
    )
    warehouse.comments = [
        Comment.from_row({"turn_seq": 1, "turn_ts": dt.datetime(2026, 4, 23), "body": payload,
                          "who": synthetic.SUPPORT_ALIAS, "source_object": "EmailMessage"}),
        Comment.from_row(
            {"turn_seq": 2, "turn_ts": dt.datetime(2026, 4, 24), "who": synthetic.OWNER,
             "body": "Picking this up.", "source_object": "CaseComment"}
        ),
    ]

    tree = render(case_detail.comment_stream, warehouse.header)

    assert "The request" in tree.text, "the request is not pinned"
    assert "1 entries" in tree.text or "1 entry" in tree.text.replace("1 entries", "1 entry"), (
        "the turn repeating the request stayed in the thread"
    )
    assert "Picking this up." in tree.text


def test_the_conversation_reads_at_two_densities(render, warehouse):
    """What used to be the Messages tab, and its own scan of the body column."""
    _long_thread(warehouse, 6)

    full = render(case_detail.comment_stream, warehouse.header).text
    assert "Reply number 3." in full

    ui_state.state.comments_compact = True
    compact = render(case_detail.comment_stream, warehouse.header)
    assert "Re: extract" in compact.text, "the compact reading lost the subject"
    assert compact.with_class("cf-turn-line"), "the compact reading is not one line a turn"


def test_the_written_request_comes_before_the_ticked_boxes(render):
    """The narrative is the request; the fields that survive reconciliation are
    answers to checkbox prompts beside it. Leading with them buried the three
    paragraphs anybody actually opened the case to read."""
    tree = render(intake_form.body, synthetic.intake_payload())

    wanted = {"cf-form-text", "cf-form-grid"}
    order = [e for e in tree.elements if wanted & set(getattr(e, "_classes", []))]
    kinds = ["text" if "cf-form-text" in e._classes else "grid" for e in order]
    assert kinds, "the request drew neither prose nor fields"
    assert kinds.index("text") < kinds.index("grid"), "the checkboxes came first"


def test_the_pinned_request_says_who_filed_it_and_when(render, warehouse):
    """Lifting the submission out of the thread takes its author and timestamp
    with it, and those are the first things a reader checks against the replies
    below."""
    import datetime as dt

    from casefinder.models import CaseHeader, Comment

    warehouse.header = CaseHeader.from_row(
        {"case_id": "1", "case_number": "CASE-1", "subject": "Registry linkage",
         "status": "Open", "description": "On Apr 23, 2026 Dana wrote: see below."}
    )
    warehouse.comments = [
        Comment.from_row(
            {"turn_seq": 1, "who": synthetic.SUPPORT_ALIAS,
             "turn_ts": dt.datetime(2026, 4, 23, tzinfo=dt.timezone.utc),
             "body": synthetic.intake_payload()}
        ),
    ]

    text = render(case_detail.comment_stream, warehouse.header).text

    # The requester's own name, not the support alias the integration files
    # these submissions under.
    assert synthetic.REQUESTER in text
    assert "web intake" in text
    assert "Apr 23, 2026" in text
