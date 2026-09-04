"""Paging and row density, on the lists and on search.

Both of these are the same problem seen from two ends: a screenful is finite.
Before this existed, opening the app drew 334 rows at once and each row was a
whole pasted email thread, so three cases filled the window and the page was
most of a megabyte of markup nobody read. Search had the quieter half of the
same defect: it said `334 results · showing first 100` and offered no way at
all to reach result 101.

Paging is done in SQL rather than by slicing a fetched window, for the reason
sorting already was: a window is not the result set, and `page 3 of 7` computed
over the first 500 rows of 41,526 is a lie. The tests here are mostly about the
two ways that goes wrong — a total that counts the page instead of the result,
and an offset that outlives the filter it was taken under.
"""

from __future__ import annotations

import pytest
import synthetic

from casefinder import config, data, models, queries
from casefinder.models import SearchHit
from casefinder.queries import TRIAGE_LIMIT, TRIAGE_PAGE_SIZE, Filters, TriageFilters
from casefinder.ui import lists, search
from casefinder.ui.components import pager as pager_ui
from casefinder.ui.shell import state

ERA = config.ERAS["current"]


# --------------------------------------------------------------------------
# The query
# --------------------------------------------------------------------------


def test_the_offset_is_a_parameter_like_every_other_value():
    """Q-INV-1. An offset is user input; it arrives from a click count."""
    sql, params = queries.triage_list(ERA, TriageFilters(), limit=50, offset=150)

    assert "OFFSET @row_offset" in sql
    assert "150" not in sql
    assert {p.name: p.value for p in params}["row_offset"] == 150


def test_a_negative_offset_cannot_be_asked_for():
    """BigQuery rejects a negative OFFSET, and the pager clamps — but the
    builder is the layer that has to hold, because it is the one with the
    contract."""
    _sql, params = queries.triage_list(ERA, TriageFilters(), offset=-10)

    assert {p.name: p.value for p in params}["row_offset"] == 0


def test_the_total_counts_the_result_and_not_the_page():
    """`COUNT(*) OVER ()` is evaluated before LIMIT and OFFSET.

    This is the whole basis for the range line. If the count were taken after
    the window, every page would report itself as the entire result and the
    Next arrow would never appear.
    """
    sql, _params = queries.triage_list(ERA, TriageFilters(), limit=50, offset=100)

    count_at = sql.index("COUNT(*) OVER ()")
    assert count_at < sql.index("LIMIT @row_limit")
    assert count_at < sql.index("OFFSET @row_offset")


def test_the_order_has_a_tiebreak_so_a_page_boundary_is_stable():
    """Paging asks the same query twice with different offsets. Without a total
    order, a case whose sort value ties with another can appear on both pages or
    on neither, depending on how the two runs happened to shuffle."""
    for sort in queries.TRIAGE_SORTS:
        sql, _ = queries.triage_list(ERA, TriageFilters(), sort=sort)
        order = sql[sql.index("ORDER BY") :]
        assert order.rstrip().endswith("LIMIT @row_limit OFFSET @row_offset")
        assert "c.case_number DESC" in order, sort


def test_each_page_is_cached_under_its_own_key(monkeypatch):
    """Going back to page 1 must not replay page 3 out of the cache."""
    from casefinder import bq, cache

    cache.clear_all()
    asked: list[int] = []

    def fake_run(sql, params):
        offset = {p.name: p.value for p in params}["row_offset"]
        asked.append(offset)
        return bq.QueryResult(rows=[], bytes_processed=0, cache_hit=False)

    monkeypatch.setattr(bq, "run", fake_run)
    for offset in (0, 50, 0, 50, 100):
        data.triage(ERA, TriageFilters(), sort="last_activity", descending=True, offset=offset)

    assert asked == [0, 50, 100]


# --------------------------------------------------------------------------
# The range line
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("offset", "shown", "total", "expected"),
    [
        (0, 0, 0, "No cases"),
        (0, 1, 1, "1 case"),
        (0, 50, 50, "50 cases"),
        (0, 50, 334, "1–50 of 334 cases"),
        (50, 50, 334, "51–100 of 334 cases"),
        (300, 34, 334, "301–334 of 334 cases"),
        (0, 50, 41526, "1–50 of 41,526 cases"),
    ],
)
def test_the_range_line_says_where_you_are(offset, shown, total, expected):
    """Stated as a range, not `page 4 of 7`. The question a triage queue gets
    asked is how much is left, and a page number makes the reader work it out."""
    assert pager_ui.range_label(offset, shown, total) == expected


def test_the_last_offset_lands_on_the_final_page_and_not_past_it():
    assert pager_ui._last_offset(334, 50) == 300
    # An exact multiple must not produce an empty page after the last one.
    assert pager_ui._last_offset(300, 50) == 250
    assert pager_ui._last_offset(0, 50) == 0


# --------------------------------------------------------------------------
# The page
# --------------------------------------------------------------------------


def test_the_list_asks_for_one_screen_rather_than_the_whole_result(render, warehouse):
    render(lists.render)

    assert warehouse.kwargs["triage"]["limit"] == TRIAGE_PAGE_SIZE
    assert warehouse.kwargs["triage"]["offset"] == 0


def test_the_list_states_the_size_of_the_result_it_is_a_page_of(render, warehouse):
    """The fake returns 2 rows and reports 119 matches."""
    tree = render(lists.render)

    assert "1–2 of 119 cases" in tree.text


def test_there_is_nothing_to_press_when_the_whole_result_fits(render, warehouse):
    warehouse.total = len(warehouse.rows)
    tree = render(lists.render)

    assert "2 cases" in tree.text
    assert not tree.with_class("cf-page")


def test_the_pager_is_repeated_under_the_table(render, warehouse):
    """Fifty rows is about three screens. A pager only at the top has to be
    scrolled back to at the moment the reader has finished the page and knows
    they want the next one — and both copies have to work, so the second is the
    same control and not a decoration."""
    tree = render(lists.render)

    assert len(tree.with_class("cf-page")) == 4
    following = tree.with_class("cf-page")[3]
    tree.press(following)
    assert state.lists.offset == TRIAGE_PAGE_SIZE


def test_a_single_page_of_results_ends_at_its_last_row(render, warehouse):
    """The bottom pager is drawn only when there is a next page to want.

    Asserted by counting the range line rather than the arrows, because a
    second pager over a one-page result renders no arrows either — what it
    renders is `2 cases` a second time, under a list that is already complete
    and has not changed since the top of the page said so.
    """
    warehouse.total = len(warehouse.rows)
    tree = render(lists.render)

    assert tree.texts().count("2 cases") == 1


def _arrows(tree):
    """The pair above the table.

    There is a second pair below it when the result runs to more than one page,
    and the two are the same control rendered twice, so the behaviour tests
    drive whichever comes first. `test_the_pager_is_repeated_under_the_table`
    is the one that cares there are two.
    """
    previous, following = tree.with_class("cf-page")[:2]
    return previous, following


def _page_at(render, offset: int):
    """Render the list already scrolled to `offset`.

    Two renders, not one, and the reason is worth stating: the first render of
    a fresh session has no columns yet, so it applies the default view — which
    resets the offset, because switching views is a new question and page 4 is
    not part of one. Setting the offset before that first render is setting it
    on a page that has not decided what it is showing yet.
    """
    render(lists.render)
    state.lists.offset = offset
    return render(lists.render)


def test_pressing_next_moves_the_window_and_re_asks_for_it(render, warehouse):
    """Pressed through the rendered control rather than by calling the
    callback, so an arrow that loses its handler fails here."""
    tree = render(lists.render)
    assert state.lists.offset == 0

    tree.press(_arrows(tree)[1])
    assert state.lists.offset == TRIAGE_PAGE_SIZE

    render(lists.render)
    assert warehouse.kwargs["triage"]["offset"] == TRIAGE_PAGE_SIZE


def test_pressing_previous_comes_back(render, warehouse):
    tree = _page_at(render, 2 * TRIAGE_PAGE_SIZE)

    tree.press(_arrows(tree)[0])

    assert state.lists.offset == TRIAGE_PAGE_SIZE


def test_next_stops_at_the_last_page_rather_than_walking_off_the_end(render, warehouse):
    """119 matches at 50 a page is three pages, and the last one starts at 100.

    Without the clamp, a second press asks BigQuery for offset 150, gets an
    empty result back, and the list has nothing to show for a page that exists.
    """
    warehouse.rows = warehouse.rows[:1]
    tree = _page_at(render, 100)

    tree.press(_arrows(tree)[1])

    assert state.lists.offset == 100


def test_the_previous_arrow_is_dead_on_the_first_page(render, warehouse):
    previous, following = _arrows(render(lists.render))

    assert previous._props.get("disable") is True, "Previous is pressable at offset 0"
    assert "disable" not in following._props, "Next is dead with 119 matches to page through"


def test_the_next_arrow_is_dead_on_the_last_page(render, warehouse):
    # A short final page: one row at offset 100 of a 101-case result.
    warehouse.rows = warehouse.rows[:1]
    warehouse.total = 101
    previous, following = _arrows(_page_at(render, 100))

    assert following._props.get("disable") is True, "Next is pressable at 101 of 101"
    assert "disable" not in previous._props


def test_narrowing_the_filters_puts_you_back_on_the_first_page(render, warehouse):
    """Page 4 of a 334-case result is nowhere at all in the 3-case result you
    get after picking a status, and asking BigQuery for that page returns no
    rows — which the screen would otherwise report as "no cases match".

    Driven through the control the page actually rendered rather than through a
    reconstructed callback, so re-wiring the filter row breaks this.
    """
    tree = render(lists.render)
    state.lists.offset = 150

    status = next(
        e for e in tree.of_type("Select") if e._props.get("label") == "Status"
    )
    with tree.client:
        status.set_value(["Open"])

    assert state.lists.filters.statuses == ["Open"]
    assert state.lists.offset == 0


def test_clearing_the_filters_puts_you_back_on_the_first_page(render, warehouse):
    render(lists.render)
    state.lists.offset = 150

    lists._clear_filters()

    assert state.lists.offset == 0


def test_a_new_sort_puts_you_back_on_the_first_page(render, warehouse):
    render(lists.render)
    state.lists.offset = 150

    lists._on_sort("owner")

    assert state.lists.offset == 0


def test_switching_view_puts_you_back_on_the_first_page(render, warehouse):
    from casefinder import views

    render(lists.render)
    state.lists.offset = 150

    lists._apply_view(views.shared_views()[0])

    assert state.lists.offset == 0


def test_an_offset_past_the_end_falls_back_rather_than_claiming_nothing_matches(
    render, warehouse
):
    """A snapshot reload can shrink a result under a page the user is already
    on. Every filter change resets the offset, so the only way to be stranded is
    for the data to move — and the honest answer is the first page, not "no
    cases match these filters"."""
    warehouse.stranded_past = 500
    tree = _page_at(render, 500)

    assert state.lists.offset == 0
    assert "No cases match" not in tree.text
    assert "CASE-056576" in tree.text


# --------------------------------------------------------------------------
# Export is not the page on screen
# --------------------------------------------------------------------------


def test_the_export_takes_the_whole_list_and_not_the_visible_page(
    render, warehouse, monkeypatch
):
    """The user asked for the view. Rows 151 to 200 of it is not an answer.

    Driven through `_export_csv` rather than through the query helper it is
    supposed to call, because the helper existing and the export using it are
    two different facts and only the second one matters.
    """
    written: list[bytes] = []
    monkeypatch.setattr(lists.ui, "download", lambda content, name: written.append(content))
    monkeypatch.setattr(lists.ui, "notify", lambda *a, **k: None)

    render(lists.render)
    state.lists.offset = 150
    lists._export_csv()

    assert written, "the export produced no file"
    assert warehouse.kwargs["triage"]["limit"] == TRIAGE_LIMIT
    assert warehouse.kwargs["triage"].get("offset", 0) == 0


def test_the_export_still_carries_no_description(render, warehouse, monkeypatch):
    """Paging changed which rows the export reads. It must not have changed
    which columns — a description is free text about a research subject's data
    and a CSV leaves the process (FR-LIST-12)."""
    written: list[bytes] = []
    monkeypatch.setattr(lists.ui, "download", lambda content, name: written.append(content))
    monkeypatch.setattr(lists.ui, "notify", lambda *a, **k: None)

    render(lists.render)
    lists._export_csv()

    text = written[0].decode("utf-8")
    assert "Description" not in text
    assert "Requesting an OMOP extract" not in text
    assert "CASE-056576" in text


# --------------------------------------------------------------------------
# Row density
# --------------------------------------------------------------------------


def test_a_pasted_email_thread_becomes_one_line():
    """What a case description actually is: headers, blank lines, a quoted
    reply. Left alone it renders as the whole row, and a two-line clamp on the
    raw text keeps `From:` and an empty line."""
    body = (
        "From: someone@example.edu\n"
        "Sent: Tuesday\n"
        "\n"
        "\n"
        "Hi — we need an OMOP extract for the retrospective study.\n"
    )

    assert models.preview(body) == (
        "From: someone@example.edu Sent: Tuesday Hi — we need an OMOP extract "
        "for the retrospective study."
    )


# The attribution lines these tests are about, built once from the roster in
# `tests/synthetic.py`. Written out here rather than inline because an
# attribution is the single most tempting thing in this file to paste from a
# real case body — it is fiddly to get right, and there is always one on screen
# while you are working on the description column. One definition, one place to
# be careful, and `synthetic.attribution` gets the shape right.
_FROM_REQUESTER = synthetic.attribution(
    synthetic.REQUESTER, synthetic.REQUESTER_EMAIL, "Apr 23, 2026 at 4:57 PM"
)
_FROM_RESEARCHER = synthetic.attribution(
    synthetic.RESEARCHER, synthetic.RESEARCHER_EMAIL, "Aug 4, 2026 at 10:39 AM"
)
_FROM_SUPPORT = synthetic.attribution(
    synthetic.SUPPORT_ALIAS, synthetic.SUPPORT_EMAIL, "Aug 1, 2026 at 9:00 AM"
)


def test_the_quoted_reply_header_is_not_the_preview():
    """What the description column showed on every row before this existed.

    Nearly every case description in the corpus opens with the mail client's
    attribution for the message being quoted, so the two visible lines were a
    date, a requester's name, and their email address — repeated fifty times
    down the page and saying nothing about any case.
    """
    body = (
        _FROM_REQUESTER
        + "\n\nSummary: Linkage of a cancer registry extract to identified OMOP records"
    )

    out = models.preview(body)

    assert out.startswith("Summary: Linkage of a cancer registry extract")
    assert "@" not in out


def test_a_forwarded_request_is_unwrapped_to_the_request():
    """A reply to a forward carries two attributions, and the second one is in
    front of the text that says what was asked for."""
    body = (
        _FROM_RESEARCHER
        + " "
        + _FROM_SUPPORT
        + " Summary: Bilirubin thresholds in late preterm infants"
    )

    assert models.preview(body).startswith("Summary: Bilirubin thresholds")


@pytest.mark.parametrize(
    "body",
    [
        _FROM_REQUESTER,
        (
            "On intake the requester listed three separate cohorts, a timeline, and "
            "an IRB that had not been approved yet, and the analyst who picked the "
            "ticket up the following quarter wrote: none of this is doable as asked."
        ),
    ],
    ids=["nothing behind it", "prose that starts with On"],
)
def test_text_that_only_looks_like_an_attribution_is_left_alone(body):
    """An empty cell is a worse answer than a quote header, and a sentence that
    happens to start with `On` and contain `wrote:` is somebody's actual
    description. The length bound on the pattern is what separates the two."""
    assert models.preview(body) == " ".join(body.split())


def test_a_repeated_snippet_is_shown_once():
    """Email quotes what it replies to, so consecutive turns of a thread carry
    the same paragraph and the window cut around a match in it comes back
    byte-identical. Every search result was printing the same two hundred
    characters twice."""
    hit = SearchHit.from_row(
        {
            "case_number": "CASE-056490",
            "snippets": [
                {"turn_seq": 1, "actor_role": "customer", "text": "does not exist in STARR-OMOP"},
                {"turn_seq": 2, "actor_role": "agent", "text": "does not exist in STARR-OMOP"},
                {"turn_seq": 3, "actor_role": "agent", "text": "the OMOP CDM release notes"},
            ],
        }
    )

    assert [s.text for s in hit.snippets] == [
        "does not exist in STARR-OMOP",
        "the OMOP CDM release notes",
    ]


def test_the_count_of_matching_messages_is_not_deduplicated():
    """Thirty-five messages did mention the term, even if they were quoting
    each other while doing it. The snippet list is a sample; `matching_turns`
    is a fact about the thread and the sentence under the subject reports it."""
    hit = SearchHit.from_row(
        {
            "case_number": "CASE-056490",
            "matching_turns": 35,
            "snippets": [{"turn_seq": n, "text": "same text"} for n in (1, 2, 3)],
        }
    )

    assert len(hit.snippets) == 1
    assert "35 messages" in hit.why_matched


@pytest.mark.parametrize(
    ("stored", "shown"),
    [
        ("Funded - Grant", "Grant"),
        ("Funded - Departmental/Gift", "Departmental/Gift"),
        ("Unfunded", "Unfunded"),
        ("Seeking Funding", "Seeking Funding"),
        ("asked about funding", "asked about funding"),
        (None, "—"),
    ],
)
def test_the_funded_column_does_not_repeat_its_own_header(stored, shown):
    """`Funded - Grant` under a column headed `Funded` spends nine characters
    saying `Funded` again, and at a width that leaves the description any room
    those were the only nine that fitted — four different values all rendered
    as `Funded - …`. The values nobody prefixed are left alone."""
    assert lists._funding(stored) == shown


def test_the_export_keeps_the_value_the_warehouse_stores(render, warehouse, monkeypatch):
    """Shortening a label is a decision about a 132px column. A CSV has no
    width, and `Grant` in a spreadsheet with no column header in sight is not
    the same fact as `Funded - Grant`."""
    from casefinder.models import TriageRow

    warehouse.rows = [
        TriageRow.from_row({"case_number": "CASE-056576", "funding": "Funded - Grant"})
    ]
    written: list[bytes] = []
    monkeypatch.setattr(lists.ui, "download", lambda content, name: written.append(content))
    monkeypatch.setattr(lists.ui, "notify", lambda *a, **k: None)

    render(lists.render)
    lists._export_csv()

    assert "Funded - Grant" in written[0].decode("utf-8")


def test_a_long_description_is_cut_before_it_is_sent():
    """The CSS clamp decides where text stops being visible; this decides how
    much is worth putting in the page at all. 500 rows of full case bodies is a
    megabyte of markup that is hidden the moment it arrives."""
    long = "word " * 500

    out = models.preview(long)

    assert len(out) <= models.PREVIEW_CHARS + 1
    assert out.endswith("…")


def test_a_missing_description_is_blank_rather_than_an_em_dash():
    """`show()` renders nothing-at-all as `—`, which is right for a fact and
    wrong for a preview: a column of em dashes is noise."""
    assert models.preview(None) == ""
    assert models.preview("   ") == ""


def test_the_description_cell_is_a_preview_and_the_others_are_one_line():
    """Density is a property of the column definitions, so it is asserted
    there — a row whose height depends on its content is the defect."""
    description = lists.COLUMNS["description"]
    assert description.clamp and description.subdued and not description.one_line

    for key, column in lists.COLUMNS.items():
        if key == "description":
            continue
        assert column.one_line, f"{key} may wrap and push the row taller"
        assert column.width != "auto", f"{key} has no width to be held to"


def test_a_clipped_cell_can_still_be_read(render, warehouse):
    """`table-layout:fixed` buys a row that does not grow, and charges for it in
    department names that end in an ellipsis. The full value is on the cell as a
    `title`, so hovering answers the question without opening the case.

    A native attribute rather than `ui.tooltip`, which is a Quasar component:
    fifty rows of eight columns would be four hundred more elements to say what
    an attribute says.
    """
    from casefinder.models import TriageRow

    warehouse.rows = [
        TriageRow.from_row(
            {
                "case_number": "CASE-056576",
                "department": "Anesthesiology, Perioperative and Pain Medicine",
                "status": "Open",
            }
        )
    ]
    tree = render(lists.render)

    titles = [e._props["title"] for e in tree.of_type("Label") if "title" in e._props]
    assert "Anesthesiology, Perioperative and Pain Medicine" in titles
    # `Open` is not clipped by any column, and a tooltip repeating a word that
    # is fully on screen is markup for nothing.
    assert "Open" not in titles


def test_a_quote_in_a_cell_does_not_eat_its_tooltip(render, warehouse):
    """NiceGUI parses props out of a string, so a double quote inside the value
    ends it early and the rest is read as more props — the title is lost and a
    junk attribute appears in its place. Case descriptions arrive with the
    intake form serialised into them as JSON, so quotes are the common case."""
    from casefinder.models import TriageRow

    warehouse.rows = [
        TriageRow.from_row(
            {"case_number": "CASE-056576", "department": 'Medicine — "Cardiovascular" unit'}
        )
    ]
    tree = render(lists.render)

    titles = [e._props["title"] for e in tree.of_type("Label") if "title" in e._props]
    assert "Medicine — ”Cardiovascular” unit" in titles
    keys = {key for e in tree.of_type("Label") for key in e._props}
    assert "Medicine" not in keys, "the props parser split the value into attributes"


def test_the_list_row_carries_a_preview_and_not_the_body(render, warehouse):
    from casefinder.models import TriageRow

    warehouse.rows = [
        TriageRow.from_row(
            {
                "case_number": "CASE-056576",
                "description": "First line.\n\n" + ("filler text " * 200),
                "total_matches": 1,
            }
        )
    ]
    tree = render(lists.render)

    cells = [e.text for e in tree.with_class("cf-truncate")]
    assert cells, "the description column rendered without its clamp"
    assert all(len(text) <= models.PREVIEW_CHARS + 1 for text in cells)
    assert "\n" not in "".join(cells)


# --------------------------------------------------------------------------
# Search is paged on the same terms
# --------------------------------------------------------------------------


def test_a_search_offset_is_a_parameter_too():
    sql, params = queries.search(ERA, ["omop"], Filters(), limit=25, offset=75)

    assert "OFFSET @row_offset" in sql
    assert {p.name: p.value for p in params}["row_offset"] == 75


def test_every_search_sort_has_a_tiebreak():
    """This was already broken before anything here paged.

    `Rows per page` shipped, so a reader could already go from 25 to 100 — two
    LIMITs over the same partial order — and lose a case that had been on
    screen. Adding OFFSET made it reachable more often; it did not create it.
    """
    for sort in queries.SORTS:
        sql, _ = queries.search(ERA, ["omop"], Filters(), sort=sort)
        order = sql[sql.index("ORDER BY") :]
        assert "c.case_number DESC" in order, sort


def _hit(number: str) -> SearchHit:
    return SearchHit.from_row(
        {
            "case_number": number,
            "subject": "Cohort extract request",
            "status": "Open",
            "turn_count": 4,
            "matching_turns": 2,
            "matched_case_fields": True,
            "snippets": [{"turn_seq": 1, "actor_role": "customer", "text": "omop cohort"}],
        }
    )


@pytest.fixture
def searched(render, warehouse):
    """A search that has been run and has more results than fit on a page.

    334 of them, which is what the corpus actually returns for a common term,
    and the number the old screen used to report as `showing first 100`.
    """
    warehouse.hits = [_hit(f"CASE-05657{n}") for n in range(3)]
    warehouse.hit_total = 334
    state.search.text = "omop"
    state.search.executed = True

    def _go():
        return render(search.render)

    _go.warehouse = warehouse
    return _go


def test_search_states_where_you_are_rather_than_that_it_gave_up(searched):
    """FR-SEARCH-9's truncation state, said in a form that has a next page."""
    tree = searched()

    assert "1–3 of 334 results" in tree.text
    assert "showing first" not in tree.text


def test_search_can_reach_the_hundred_and_first_result(searched, warehouse):
    tree = searched()

    tree.press(_arrows(tree)[1])

    assert state.search.offset == state.search.rows_per_page
    searched()
    assert warehouse.kwargs["search"]["offset"] == state.search.rows_per_page


def test_the_search_fetch_stays_capped_however_the_page_is_sized(searched, warehouse):
    """FR-SEARCH-11 caps one retrieval, not the result.

    Paging past row 500 is the point of paging; asking for 500 rows in a single
    response is the thing the cap is for. Every size the control offers has to
    sit under it and has to reach the query — a fourth option of 1,000 added to
    the tuple would fail here rather than at the warehouse.
    """
    assert max(search.ROWS_PER_PAGE) <= search.MAX_RETRIEVAL

    for size in search.ROWS_PER_PAGE:
        state.search.rows_per_page = size
        searched()
        assert warehouse.kwargs["search"]["limit"] == size


def test_a_search_with_one_page_of_results_has_nothing_to_press(searched, warehouse):
    warehouse.hit_total = len(warehouse.hits)
    tree = searched()

    assert "3 results" in tree.text
    assert not tree.with_class("cf-page")


@pytest.mark.parametrize(
    ("what", "find", "value"),
    [
        ("a status filter", lambda t: _select(t, label="Status"), ["Open"]),
        ("a different sort", lambda t: _select(t, value="relevance"), "newest"),
        ("a different page size", lambda t: _select(t, value=25), 50),
    ],
    ids=["status", "sort", "page size"],
)
def test_changing_the_question_puts_you_back_on_the_first_page(
    searched, what, find, value
):
    """Result 51 under one sort is a different case under another, and under a
    narrower filter it may not exist. Every control that changes what the
    result *is* clears the offset; the two arrows are the only things that
    move it.

    Driven through the rendered controls, so a handler that stops going through
    `_rerun` fails here rather than in review.
    """
    tree = searched()
    state.search.offset = 100

    with tree.client:
        find(tree).set_value(value)

    assert state.search.offset == 0, what


def test_a_new_search_puts_you_back_on_the_first_page(searched):
    """Enter in the box, not the callback behind it."""
    tree = searched()
    state.search.offset = 100

    box = tree.of_type("Input")[0]
    box.value = "cohort"
    tree.fire(box, "keydown")

    assert state.search.text == "cohort"
    assert state.search.offset == 0


def test_a_stranded_search_offset_falls_back_rather_than_saying_no_matches(
    searched, warehouse
):
    warehouse.stranded_past = 100
    state.search.offset = 100

    tree = searched()

    assert state.search.offset == 0
    assert "No cases contain" not in tree.text
    assert "CASE-056570" in tree.text


def _select(tree, *, label=None, value=None):
    for element in tree.of_type("Select"):
        if label is not None and element._props.get("label") == label:
            return element
        if value is not None and element.value == value:
            return element
    raise AssertionError(f"no Select with label={label!r} value={value!r}")
