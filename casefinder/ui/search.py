"""Search — deliberately sparse.

FR-SEARCH-1 lists what the idle screen does not have: no tips card, no recent
searches, no illustration, and no Search button. UX-T2 makes the last one an
acceptance test: Enter is the only way to run a search, because a button beside
a search box is a button explaining what the box already means.

The one piece of real logic on this page is `_maybe_case_number`. Typing a case
number is the single most common thing a support user does, and FR-SEARCH-3
says it should land on the case rather than on a result list containing one
case.
"""

from __future__ import annotations

import html
import re

from nicegui import ui

from .. import config, data
from ..config import ERAS
from ..data import Page
from ..models import SearchHit, Snippet, show
from ..queries import SORTS, Filters, parse_terms
from . import shell
from .components import filters as filter_ui
from .components import loading
from .components import pager as pager_ui
from .components.empty_state import empty
from .shell import MUTED, muted, state

CASE_NUMBER = re.compile(r"^\s*(CASE-\d+)\s*$", re.IGNORECASE)

SORT_LABELS = {
    "relevance": "Most mentions",
    "newest": "Newest first",
    "oldest": "Oldest first",
    "longest": "Longest thread",
}

ROWS_PER_PAGE = (25, 50, 100)

# Spec FR-SEARCH-11: never retrieve more than this in one fetch, however the
# page size is set. It caps the fetch and not the result — paging past row 500
# is allowed, and is the point of paging. The cap is there so a single request
# cannot turn into a 41,526-row response; a reader walking to result 501 has
# asked for it a page at a time.
MAX_RETRIEVAL = 500


def render() -> None:
    search = state.search
    if not search.executed:
        _idle()
    else:
        _executed()


def _rerun() -> None:
    """Re-ask the question after something changed what the answer is.

    Everything that touches the terms, the scope, the filters, the sort or the
    era comes through here, and all of it clears the offset first. An offset is
    a position in one particular result: change the question and row 51 is a
    different row, so keeping it drops the reader into the middle of a result
    they have not seen the start of — or past the end of a shorter one, which
    reads as "no cases match". Paging is the one thing that moves the offset
    rather than clearing it.
    """
    state.search.offset = 0
    results.refresh()


def _input_box(centered: bool) -> None:
    def submit() -> None:
        raw = box.value or ""
        match = CASE_NUMBER.match(raw)
        if match:
            # FR-SEARCH-3: straight to the case, no intermediate button.
            ui.navigate.to(f"/case/{match.group(1).upper()}")
            return
        state.search.text = raw
        state.search.dismissed_boilerplate = False
        state.search.executed = True
        _rerun()
        if not centered:
            return
        ui.navigate.to("/search")

    box = (
        ui.input(placeholder="Search cases or type CASE-…", value=state.search.text)
        .props("outlined dense clearable autofocus")
        .style("width:100%; font-size:14px")
        .on("keydown.enter", submit)
    )


def _scope_and_filters() -> None:
    search = state.search

    def set_scope(fields: bool, conversation: bool) -> None:
        search.in_fields = fields
        search.in_conversation = conversation
        if search.executed:
            _rerun()
        else:
            idle_controls.refresh()

    def set_era(key: str) -> None:
        state.era_key = key
        if search.executed:
            _rerun()
        else:
            idle_controls.refresh()

    def set_status(values: list[str]) -> None:
        search.statuses = values
        _rerun()

    def set_type(values: list[str]) -> None:
        search.types = values
        _rerun()

    filter_ui.scope_control(search.in_fields, search.in_conversation, set_scope)

    facets = _facets()
    filter_ui.multi_select("Status", facets.statuses, search.statuses, set_status, width=150)
    filter_ui.multi_select("Type", facets.types, search.types, set_type, width=150)
    filter_ui.era_select(state.era_key, ERAS, set_era)


def _facets():
    from ..models import Facets

    try:
        return data.facets(state.era)
    except Exception:  # noqa: BLE001
        return Facets()


@ui.refreshable
def idle_controls() -> None:
    with ui.row().classes("items-center justify-center w-full").style(
        "gap:10px; flex-wrap:wrap; margin-top:16px"
    ):
        _scope_and_filters()


def _idle() -> None:
    """FR-SEARCH-1. Nothing but the question and the box.

    This is now the first screen of the app (D17), which makes the order things
    appear in part of the design. The heading and the box are free, so they are
    drawn and focused straight away; the filter controls under them need the
    facet query, and someone who opened the app to type a case number should
    not wait on a list of departments to do it.
    """
    with ui.column().classes("w-full items-center").style("gap:0; padding-top:12vh"):
        ui.label("Search historical support cases").classes("cf-h1")
        with ui.element("div").style("width:min(560px, 100%); margin-top:16px"):
            _input_box(centered=True)
        # `_facets` rather than `data.facets`, so the load warms the cache the
        # controls read from and a facet query that fails still leaves a
        # usable search box with empty pickers under it.
        loading.while_loading(
            "Loading filters…",
            _facets,
            lambda _: idle_controls(),
            on_error=shell.error_region,
            center=True,
        )
        muted(
            f"{state.era.approx_cases:,} cases · terms are matched literally and "
            "must all be present"
        ).style("margin-top:18px")


def _executed() -> None:
    with ui.column().classes("w-full cf-reading").style("gap:0"):
        with ui.element("div").style("width:100%; max-width:620px"):
            _input_box(centered=False)
        with ui.row().classes("items-center w-full").style(
            "gap:10px; flex-wrap:wrap; margin-top:12px"
        ):
            _scope_and_filters()
        results()


def _filters() -> Filters:
    return Filters(statuses=list(state.search.statuses), types=list(state.search.types))


@ui.refreshable
def results() -> None:
    search = state.search
    terms = parse_terms(search.text)

    if search.text.strip() and not terms:
        # Spec section 12: inline validation, and no query is issued.
        with ui.row().classes("cf-note w-full").style("margin-top:14px"):
            ui.label("Search terms need at least two characters.")
        return

    # Deferred here, inside the refreshable, rather than around it. Everything
    # that changes the answer — new terms, a filter, a sort, the next page —
    # comes back through `refresh()`, and each of those is another round trip
    # against the conversation table. A spinner that only appeared on the first
    # search would be missing from every wait after it.
    loading.while_loading(
        "Searching…",
        lambda: _fetch(terms),
        lambda page: _found(terms, page),
        on_error=shell.error_region,
    )


def _ask(terms: list[str], offset: int) -> Page:
    search = state.search
    return data.search(
        state.era,
        terms,
        _filters(),
        in_conversation=search.in_conversation,
        in_fields=search.in_fields,
        sort=search.sort,
        limit=min(search.rows_per_page, MAX_RETRIEVAL),
        offset=offset,
    )


def _fetch(terms: list[str]) -> Page:
    """Every warehouse call the result needs, made off the event loop.

    The corpus size is in here and not left to `_boilerplate_warning` because
    that runs while the page is being drawn, and a round trip there is a round
    trip with nothing on the screen to say so. It goes out alongside the search
    rather than after it, so the two cost one wait between them.
    """
    search = state.search
    data.prefetch(
        lambda: _ask(terms, search.offset),
        lambda: data.corpus_size(state.era),
    )

    page = _ask(terms, search.offset)
    if not page.rows and search.offset:
        # Same fallback the lists page makes: a page past the end of a result
        # that moved is a first page, not an empty search.
        search.offset = 0
        page = _ask(terms, 0)
    return page


def _found(terms: list[str], page: Page) -> None:
    if not page.rows:
        quoted = " and ".join(f"“{t}”" for t in terms) if terms else "these filters"
        empty(
            f"No cases contain {quoted}.",
            [
                ("Search inside conversations", _enable_conversation),
                ("Clear filters", _clear_filters),
                ("Try the full archive", _switch_era),
            ],
        )
        return

    _boilerplate_warning(terms, page)

    with ui.row().classes("w-full items-center justify-between").style("margin:14px 0 4px 0"):
        with ui.row().classes("items-center").style("gap:10px"):
            muted(
                pager_ui.range_label(
                    state.search.offset, len(page.rows), page.total_matches, noun="result"
                )
            )
            if not page.is_trivial_cost:
                muted("· " + page.cost_note)
        _sort_control()

    for hit in page.rows:
        _result_card(hit)

    _rows_per_page(page)


def _boilerplate_warning(terms: list[str], page) -> None:
    """FR-SEARCH-8: a term matching most of the corpus is a footer, not a topic."""
    if state.search.dismissed_boilerplate or not terms:
        return
    try:
        corpus = data.corpus_size(state.era)
    except Exception:  # noqa: BLE001
        return
    if not corpus:
        return
    ratio = page.total_matches / corpus
    if ratio < config.BOILERPLATE_WARN_RATIO:
        return

    def dismiss() -> None:
        state.search.dismissed_boilerplate = True
        results.refresh()

    with ui.row().classes("cf-banner w-full items-center justify-between").style(
        "gap:10px; margin-top:14px"
    ):
        ui.label(f"These terms match {ratio:.0%} of all cases. {config.BOILERPLATE_NOTE}")
        ui.icon("close").style("cursor:pointer; font-size:15px").on("click", dismiss)


def _sort_control() -> None:
    def set_sort(value: str) -> None:
        state.search.sort = value
        _rerun()

    ui.select(
        {key: SORT_LABELS[key] for key in SORTS},
        value=state.search.sort,
        on_change=lambda e: set_sort(e.value),
    ).props("dense borderless options-dense").style(f"font-size:12.5px; color:{MUTED}")


def _rows_per_page(page) -> None:
    """FR-SEARCH-11: compact controls at the bottom, not a large slider.

    The spec offers pagination *or* a rows-per-page control; this has both,
    because on their own each one leaves a question unanswerable. Rows per page
    alone caps you at 100 of 334 with no way to reach 101. Paging alone makes
    someone scanning a long result turn six pages that could have been two.
    They are two different questions — how much at a time, and which part — so
    they are two controls, sitting together where the answer to both is needed.
    """
    if page.total_matches <= min(ROWS_PER_PAGE):
        return

    def set_size(value: int) -> None:
        state.search.rows_per_page = value
        # Row 30 is on a different page at 25 a page than at 100. Rather than
        # guess which one the reader meant, go back to the top, which is the
        # one place the answer is the same either way.
        _rerun()

    def set_offset(value: int) -> None:
        state.search.offset = value
        results.refresh()

    with ui.row().classes("w-full items-center justify-end").style(
        "gap:14px; margin-top:18px"
    ):
        pager_ui.pager(
            offset=state.search.offset,
            shown=len(page.rows),
            total=page.total_matches,
            page_size=state.search.rows_per_page,
            on_change=set_offset,
            noun="result",
        )
        with ui.row().classes("items-center").style("gap:6px"):
            muted("Rows")
            ui.select(
                list(ROWS_PER_PAGE),
                value=state.search.rows_per_page,
                on_change=lambda e: set_size(int(e.value)),
            ).props("dense borderless options-dense").style("font-size:12.5px")


def _result_card(hit: SearchHit) -> None:
    """A search result is one of the few things the spec allows to be a card.

    The whole thing is the click target — UX-INV-2 and UX-T3 forbid an Open
    button here.
    """
    with ui.column().classes("w-full cf-row").style(
        "gap:3px; padding:13px 12px; border-bottom:1px solid " + shell.LINE
    ).on(
        "click",
        lambda: ui.navigate.to(f"/case/{hit.case_number}"),
        js_handler=shell.CLICK_UNLESS_SELECTING,
    ):
        with ui.row().classes("w-full items-baseline justify-between").style("gap:12px"):
            ui.label(hit.case_number).classes("cf-casenum")
            with ui.row().classes("items-baseline").style("gap:10px"):
                if hit.status:
                    muted(hit.status)
                muted(show(hit.created_at))
        ui.label(hit.subject or "(no subject)").style("font-size:14px; font-weight:520")
        muted(hit.why_matched)
        for snippet in hit.snippets[:2]:
            _snippet(snippet, parse_terms(state.search.text))


def _snippet(snippet: Snippet, terms: list[str]) -> None:
    """Render a snippet with the matched terms marked.

    Spec section 9.5: escape first, then highlight. The body is warehouse text
    that originated in email, so it is treated as hostile — the only HTML that
    reaches the browser is the `<mark>` this function adds after escaping.
    """
    safe = html.escape(snippet.text)
    for term in terms:
        if not term:
            continue
        pattern = re.compile(re.escape(html.escape(term)), re.IGNORECASE)
        safe = pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", safe)
    ui.html(f"…{safe}…").classes("cf-snippet").style("margin-top:5px")


# -- empty-state actions ---------------------------------------------------


def _enable_conversation() -> None:
    state.search.in_conversation = True
    _rerun()


def _clear_filters() -> None:
    state.search.statuses = []
    state.search.types = []
    _rerun()


def _switch_era() -> None:
    state.era_key = "archive" if state.era_key == "current" else "current"
    _rerun()
