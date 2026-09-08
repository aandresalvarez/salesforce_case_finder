"""The screens in the visual regression set — spec section 13.4.

There are no image baselines here, and that is a deliberate choice rather than a
gap. Pixel baselines for a desktop app have to be captured per platform, and the
spec asks for macOS *and* Windows; a baseline that only one maintainer can
regenerate becomes a test everybody skips within a month. What actually breaks
in this application is structural — a screen that renders an error region
instead of content, a query that fires on page open, a heading that disappears
when a panel is refactored — and all of that can be asserted on the element tree
in a few milliseconds with no browser.

So: every screen in the regression list is rendered here, in both its populated
and its empty state, and checked for the things a screenshot would have caught.
Capturing the actual images stays a release step, listed in the README.
"""

from __future__ import annotations

import pytest
import synthetic

from casefinder.models import Attachment, Comment, RelatedCase, SearchHit, TimelineEvent
from casefinder.ui import (
    case_detail,
    lists,
    saved_views,
    search,
    settings,
    shell,
    sql_page,
    theme,
)
from casefinder.ui import state as ui_state

# --------------------------------------------------------------------------
# Populated screens
# --------------------------------------------------------------------------


def _populate(warehouse) -> None:
    warehouse.hits = [
        SearchHit.from_row(
            {
                "case_number": f"CASE-0565{n}",
                "subject": "Cohort extract request",
                "status": "Open",
                "turn_count": 6,
                "matching_turns": 2,
                "matched_case_fields": True,
                "total_matches": 2,
                "snippets": [
                    {"turn_seq": 1, "actor_role": "customer", "text": "an omop cohort"}
                ],
            }
        )
        for n in (76, 77)
    ]
    warehouse.comments = [
        Comment.from_row(
            {
                "turn_seq": n,
                "who": "Requester" if n % 2 else "Analyst",
                "direction": "inbound" if n % 2 else "outbound",
                "source_object": "EmailMessage",
                "body": f"Message body number {n}.",
            }
        )
        for n in range(1, 4)
    ]
    warehouse.messages = [
        Comment.from_row(
            {
                "turn_seq": n,
                "who": "Requester",
                "direction": "inbound",
                "subject": "Re: extract",
                "body": f"Message body number {n}.",
                "body_len": 22,
            }
        )
        for n in range(1, 4)
    ]
    warehouse.timeline = [
        TimelineEvent.from_row(
            {"seq": 1, "kind": "message", "what": "Email from requester", "who": "Requester"}
        ),
        TimelineEvent.from_row(
            {"seq": 2, "kind": "field change", "what": "Status", "detail": "New → Open"}
        ),
    ]
    warehouse.attachments = [
        Attachment.from_row(
            {"file_name": "cohort.csv", "mb": 1.5, "gcs_uri": "gs://bucket/cohort.csv"}
        )
    ]
    warehouse.related = [
        RelatedCase.from_row(
            {"case_number": "CASE-056500", "subject": "Earlier request", "same_pi": True}
        )
    ]


SCREENS = {
    "open cases": lambda: lists.render(),
    "saved views": lambda: saved_views.render(),
    "search idle": lambda: search.render(),
    "settings": lambda: settings.render(),
    "sql": lambda: sql_page.render(),
}


@pytest.mark.parametrize("name", sorted(SCREENS))
def test_every_screen_renders_content_rather_than_an_error(name, render, warehouse):
    _populate(warehouse)
    tree = render(SCREENS[name])
    assert not tree.with_class("cf-error"), f"{name} rendered an error region"
    assert tree.of_type("Label"), f"{name} rendered nothing"


@pytest.mark.parametrize("name", sorted(SCREENS))
def test_every_screen_has_exactly_one_page_title(name, render, warehouse):
    """One `cf-h1` is what makes a screen one task — UX-INV-4."""
    _populate(warehouse)
    tree = render(SCREENS[name])
    assert len(tree.with_class("cf-h1")) == 1


@pytest.mark.parametrize(
    ("tab", "loader"),
    [
        ("Comments", "comments"),
        ("Timeline", "timeline"),
        ("Files", "attachments"),
    ],
)
def test_each_case_tab_renders(tab, loader, render, warehouse):
    """Screens 4, 5 and 6 of the regression set, plus Files.

    Selecting the tab has to be what builds it — a panel that renders empty
    because its loader never ran would still look fine to an assertion about
    error regions, so the call log is checked as well.
    """
    _populate(warehouse)
    tree = render(case_detail.render, "CASE-056576")
    tree.of_type("Tabs")[0].value = tab
    assert loader in warehouse.calls, f"the {tab} tab never asked for its data"
    assert not tree.with_class("cf-error"), f"the {tab} tab rendered an error"
    assert tree.text.strip()


def test_search_results_render(render, warehouse):
    _populate(warehouse)
    ui_state.state.search.text = "omop"
    ui_state.state.search.executed = True
    tree = render(search.render)
    assert "2 results" in tree.text
    assert not tree.with_class("cf-error")


def test_a_snippet_is_the_only_html_on_the_results_screen(render, warehouse):
    """Everything else is a label, so the corpus cannot render its own markup."""
    _populate(warehouse)
    ui_state.state.search.text = "omop"
    ui_state.state.search.executed = True
    tree = render(search.render)
    html_elements = tree.of_type("Html")
    assert html_elements
    for element in html_elements:
        assert "cf-snippet" in element._classes


# --------------------------------------------------------------------------
# Stylesheet delivery
# --------------------------------------------------------------------------


def _head_seen_by(tree) -> str:
    from nicegui import Client

    return Client.shared_head_html + tree.client._head_html


@pytest.mark.parametrize(
    ("component", "rule"),
    [
        ("table", "-webkit-line-clamp"),
        ("filters", ".cf-select .q-field__control"),
        ("intake_form", ".cf-form-grid"),
    ],
)
def test_a_component_stylesheet_reaches_every_page_and_not_just_the_first(
    component, rule, render, warehouse
):
    """The regression that made list descriptions render as whole case bodies.

    `ui.add_head_html` writes into the head of the *current* client, so the
    obvious way to install a component's CSS once — a module-level flag
    guarding the call — serves the rules to the first page load in the process
    and the class names to every one after it. The page then has `.cf-truncate`
    on an element and no `-webkit-line-clamp` anywhere, which looks exactly like
    a component that has no CSS at all.

    Rendering twice is the smallest thing that tells a shared stylesheet from a
    per-client one. Asserting only on the second load would pass against a
    stylesheet that reached nobody, so both are checked.
    """
    first = render(lists.render)
    second = render(lists.render)

    assert rule in _head_seen_by(first), f"{component} CSS missing on the first load"
    assert rule in _head_seen_by(second), f"{component} CSS missing on the second load"


@pytest.mark.parametrize(
    ("module", "rule"),
    [
        ("casefinder.ui.components.table", "-webkit-line-clamp"),
        ("casefinder.ui.components.filters", ".cf-select .q-field__control"),
        ("casefinder.ui.components.intake_form", ".cf-form-grid"),
    ],
)
def test_a_component_installs_its_stylesheet_at_import_and_not_at_first_draw(module, rule):
    """The second way of getting this wrong, and the reason for the first rule.

    A page's head is composed when its page function returns. Content behind
    `components/loading.py` is drawn from a timer callback *after* that, so a
    component registering its CSS the first time it draws registers it once the
    only head that would have carried it has already gone out — and the browser
    gets the class names with no rules, which is exactly the failure the shared
    stylesheet was introduced to fix. It is what made the intake form render as
    a plain stack of labels with no grid and no box around it.

    Re-importing with an empty registry is what makes this an assertion about
    the module rather than about whichever earlier test drew the component
    first. Both the registry and the accumulated head are put back afterwards,
    so the check leaves nothing behind for the next test to trip over.
    """
    import importlib

    from nicegui import Client

    from casefinder.ui import theme as theme_module

    names = set(theme_module._registered_css)
    head = Client.shared_head_html
    theme_module._registered_css.clear()
    try:
        importlib.reload(importlib.import_module(module))
        added = Client.shared_head_html[len(head) :]
        assert rule in added, f"{module} did not install its stylesheet on import"
    finally:
        theme_module._registered_css.clear()
        theme_module._registered_css.update(names)
        Client.shared_head_html = head


@pytest.mark.parametrize("cls", [".cf-body", ".cf-snippet"])
def test_free_text_wraps_instead_of_running_off_the_page(cls, render, warehouse):
    """A case body is pasted email, and the requester's web form was serialised
    into it — hundreds of characters of JSON with no space anywhere in them,
    and REDCap URLs beside it. That is one word as far as the browser is
    concerned, so without `overflow-wrap` it overflows its column and the tail
    is clipped at the edge of the page with nothing to say it happened.

    Asserted on the stylesheet rather than on a rendered width because there is
    no layout engine here; what a browser test would add is a check that the
    rule is the right one, and what this catches is the rule going missing.
    """
    tree = render(theme.install)

    head = _head_seen_by(tree)
    assert cls in head, f"{cls} is not in the theme the page is served"
    block = head[head.index(cls) : head.index(cls) + 260]
    assert "overflow-wrap: anywhere" in block, f"{cls} can clip its text"


def _sticky_header_rule(tree) -> str:
    # The opening brace is part of the needle because the comment on
    # `--cf-pad-top` names this selector too, and a bare `index` finds the prose
    # rather than the rule.
    head = _head_seen_by(tree)
    start = head.index(".cf-table thead tr th {")
    return head[start : head.index("}", start)]


def test_the_pinned_header_covers_the_pane_it_is_pinned_to(render, warehouse):
    """A fifty-row list is scrolled, so the header has to stay put — and it has
    to stay put flush against the top of what the reader can see.

    `top: 0` pins to the top of the scrolling pane's *content* box, which sits
    one `--cf-pad-top` below the top of the pane itself. That left a strip of
    open scrollport above the header with rows sliding up through it in full
    view; because a description is clamped to two lines, one line of a row
    appeared above the header while its second line appeared below, which reads
    as a rendering fault rather than as scrolling.

    Both halves are asserted together because the fix is that they cancel: a
    padding changed without the offset re-opens the strip, and an offset changed
    without the padding drags the header off the top of the pane.
    """
    tree = render(theme.install)
    head = _head_seen_by(tree)

    assert "padding: var(--cf-pad-top)" in head, "the pane no longer pads from the variable"
    assert "calc(var(--cf-pad-top) * -1)" in _sticky_header_rule(tree), (
        "the pinned header does not cancel the pane's top padding"
    )


def test_the_pinned_header_keeps_its_rule(render, warehouse):
    """`border-collapse: collapse` hands a cell's borders to the table to draw,
    so the `border-bottom` of a sticky `th` stays behind while the cell floats
    above it. The pinned header lost its underline and the half-scrolled row
    beneath it was cut off against nothing. A shadow is painted by the cell and
    travels with it.
    """
    rule = _sticky_header_rule(render(theme.install))
    assert "box-shadow" in rule, "a pinned header has no rule under it"


# --------------------------------------------------------------------------
# Empty and error states — spec section 12
# --------------------------------------------------------------------------


def test_an_empty_list_explains_itself_and_offers_a_way_out(render, warehouse):
    warehouse.rows = []
    tree = render(lists.render)
    assert "No cases match these filters" in tree.text
    assert "Clear filters" in tree.text
    assert not tree.with_class("cf-error")


def test_an_empty_facet_renders_no_control_at_all(render, warehouse):
    """Spec section 12: do not render a dead control.

    The archive era has facets the current era does not, so a filter whose
    values come back empty is a normal condition rather than a fault. A select
    the user can open to find nothing in is worse than an absent one — it reads
    as a broken filter instead of an inapplicable one.
    """
    from casefinder.models import Facets

    def labels_of(tree):
        return {getattr(e, "_props", {}).get("aria-label") for e in tree.of_type("Select")}

    faceted = {"Status", "Department", "PI", "IRB / protocol"}
    # Anchored against the populated page, so the assertion below cannot pass by
    # the labels having merely been renamed.
    assert faceted <= labels_of(render(lists.render))

    warehouse.facets = Facets(statuses=[], types=[], departments=[], pis=[], irbs=[])
    tree = render(lists.render)
    assert not faceted & labels_of(tree)
    # The page itself still works — this is one missing control, not an error.
    assert not tree.with_class("cf-error")
    assert tree.with_class("cf-h1")


def test_no_search_results_names_the_terms(render, warehouse):
    warehouse.hits = []
    ui_state.state.search.text = "notarealterm"
    ui_state.state.search.executed = True
    tree = render(search.render)
    assert "notarealterm" in tree.text
    assert "Search inside conversations" in tree.text


def test_a_one_character_search_is_refused_without_a_query(render, warehouse):
    """Spec section 12: inline validation, and no BigQuery job."""
    ui_state.state.search.text = "x"
    ui_state.state.search.executed = True
    tree = render(search.render)
    assert "at least two characters" in tree.text
    assert "search" not in warehouse.calls


def test_an_unknown_case_names_the_era_it_looked_in(render, warehouse):
    """FR-CASE-11."""
    warehouse.header = None
    tree = render(case_detail.render, "CASE-999999")
    assert "CASE-999999 is not in" in tree.text
    assert ui_state.state.era.label in tree.text
    assert "Look in the other era" in tree.text
    # A typo should not spend a 237 MB conversation scan learning that the
    # case it named has no comments.
    assert "comments" not in warehouse.calls
    assert "related" not in warehouse.calls


def test_a_case_with_no_conversation_says_so(render, warehouse):
    warehouse.comments = []
    tree = render(case_detail.render, "CASE-056576")
    assert "no conversation recorded" in tree.text


def test_the_connection_screen_gives_the_command_to_run(render):
    tree = render(shell.connection_screen, "Could not find credentials")
    assert "gcloud auth application-default login" in tree.text
    assert "Could not find credentials" in tree.text


def test_a_failed_query_becomes_a_region_not_a_blank_page(render, warehouse, monkeypatch):
    from casefinder import data

    def explode(*args, **kwargs):
        raise RuntimeError("403 Access Denied")

    monkeypatch.setattr(data, "triage", explode)
    tree = render(lists.render)
    assert tree.with_class("cf-error")
    assert "BigQuery could not run that." in tree.text
    # The title survives, so the user still knows where they are.
    assert len(tree.with_class("cf-h1")) == 1


def test_a_gated_page_shows_the_connect_screen_instead(render, warehouse, monkeypatch):
    from casefinder import data

    monkeypatch.setattr(data, "check_access", lambda: (False, "no credentials"))
    tree = render(shell.gated, "lists", lists.render)
    assert "Connect to Google Cloud" in tree.text
    assert not tree.with_class("cf-rail"), "the rail should not frame the gate"


# --------------------------------------------------------------------------
# The shell itself
# --------------------------------------------------------------------------


def test_a_page_is_the_rail_plus_one_content_column(render, warehouse):
    tree = render(shell.gated, "lists", lists.render)
    assert len(tree.with_class("cf-rail")) == 1
    assert len(tree.with_class("cf-content")) == 1


def test_the_reading_surfaces_are_width_limited(render, warehouse):
    """UX-INV-4: prose at full window width is unreadable on a wide monitor.

    The case page carries the measure on its thread column rather than on the
    page, because the page is now two things — prose that has to stay narrow,
    and a rail that is chrome and does not.
    """
    _populate(warehouse)
    tree = render(case_detail.render, "CASE-056576")

    assert tree.with_class("cf-case-main"), "the thread column vanished"
    assert "max-width: 720px" in theme._CSS.replace("max-width:720px", "max-width: 720px")


def test_the_rail_folds_above_the_thread_before_it_squeezes_it(render, warehouse):
    """A 1024px window — the configured minimum — leaves the pane 784px, and
    784 less a 280px rail is not a reading measure. So below the breakpoint the
    rail stops being a margin and becomes a band above the thread, which is the
    same move the filter row makes at its own width."""
    css = theme._CSS
    assert ".cf-case-rail" in css and "@media (max-width: 1180px)" in css
    fold = css.split("@media (max-width: 1180px)")[1].split("\n}")[0]
    assert "flex: 1 1 100%" in fold and "order: 1" in fold


# --------------------------------------------------------------------------
# The filter chips
# --------------------------------------------------------------------------


def _chip_css() -> str:
    """The filter stylesheet with its comments removed.

    The comments here explain what the rules replaced, and quote the Quasar
    colours and selectors they replaced them with — so a test that scans the
    raw text finds the very strings it is asserting are gone.
    """
    import re

    from casefinder.ui.components import filters as filter_ui

    return re.sub(r"/\*.*?\*/", "", filter_ui._CSS, flags=re.DOTALL)


def _chip_rules() -> list[str]:
    """Every rule in the filter stylesheet that targets a chip's internals."""
    return [
        line.strip()
        for line in _chip_css().splitlines()
        if ".cf-select" in line and "q-field__" in line
    ]


def test_every_chip_rule_outranks_quasars_own():
    """The bug this prevents is invisible in a diff and invisible in review.

    Quasar's `.q-field--dense .q-field__control` is two classes, and its
    stylesheet is served after this one, so `.cf-select .q-field__control` —
    also two classes — lost every tie. The chip declared 30px and rendered at
    Quasar's 40px, while `.q-field__marginal`, which Quasar does not set for
    dense fields, kept the 30px it asked for: the clear and dropdown icons sat
    five pixels above the centre of a control that was supposed to hold them.

    Nothing errored, nothing looked obviously wrong in isolation, and the
    numbers in the file were simply not the numbers on the screen. Three
    classes wins the tie, so every one of these selectors leads with
    `.q-field`.
    """
    rules = _chip_rules()
    assert rules, "the chip stylesheet vanished"
    for rule in rules:
        assert rule.startswith(".q-field.cf-select"), (
            f"{rule!r} ties with Quasar's own rule and loses on source order"
        )


def test_the_text_box_is_the_size_of_the_chip_that_holds_it():
    """The chip was the right height and the text still sat low in it.

    Quasar's `.q-field--dense .q-field__native` carries `min-height:40px`, and
    the rule that styles the chip's text set font and colour but never touched
    it — so inside a 30px control the text box was still 40px, hanging ten
    pixels out of the bottom. Its own `align-items:center` then centred the
    label in that box rather than in the pill, putting every label in the row
    five pixels below centre: not obviously broken, just visibly sitting low.

    Sizing the control alone is not enough, which is the whole point of pinning
    it here.
    """
    css = _chip_css()
    for part in ("q-field__native", "q-field__control-container"):
        assert f".q-field.cf-select .{part}" in css, f"{part} is unconstrained"
    box = css.split(".q-field.cf-select .q-field__native,")[1].split("}")[0]
    assert "height:30px" in box and "min-height:30px" in box


def test_the_chip_takes_its_colours_from_the_palette():
    """Quasar paints an outlined field's border on `:before` and its focus ring
    on `:after`, so a `border` set on the control itself sits underneath both
    and is never seen. The row was outlined in `rgba(0,0,0,.24)` and focused in
    Quasar's blue — neither of which appears anywhere else in this app."""
    from casefinder.ui.theme import ACCENT, LINE

    css = _chip_css()
    assert f"q-field__control:before {{ border-color:{LINE}" in css
    assert "rgba(0, 0, 0, .24)" not in css and "rgba(0,0,0,.24)" not in css
    assert ACCENT in css, "the focus ring is not the application's accent"
    # And the ring is on the focused state, not on the element: colouring
    # `:after` outright painted a ring on every chip in the row at rest, which
    # read as five controls focused at once.
    assert ".q-field.cf-select.q-field--focused .q-field__control:after" in css


def test_a_chip_says_which_dimension_it_filters_without_a_floating_label(render, warehouse):
    """The chip carries no Quasar `label`, because a floating one is what made
    an empty control and a filled one two different widgets: Quasar lifts the
    label into the border and stacks the value beneath it, and a 30px pill with
    a 999px radius has nowhere to put it — it landed on the curve.

    So the dimension has to survive somewhere else, and it does: in the text
    when nothing is chosen, and in the accessible name always.
    """
    tree = render(lists.render)

    chips = [e for e in tree.of_type("Select") if "cf-select" in e._classes]
    assert chips, "the filter row drew no chips"
    for chip in chips:
        assert not chip._props.get("label"), "the floating label came back"
        assert chip._props.get("aria-label"), "the chip has no accessible name"
        assert chip._props.get("display-value"), "a closed chip would read empty"


def test_a_chip_with_a_choice_is_marked_as_carrying_one(render, warehouse):
    """An active filter should be visible in the row, the way the rail shows
    which destination you are on — that is what replaced the floating label."""
    # Applied as a view, which is how every path in the app sets a filter:
    # `lists.render` re-applies the default view whenever the column list is
    # empty, so filters written straight onto the state are wiped on a cold
    # render — the same trap `focus_on_owner` documents.
    from casefinder import views
    from casefinder.queries import TriageFilters

    ui_state.state.lists.apply(
        views.SavedView(name="One owner", filters=TriageFilters(owners=[synthetic.OWNER]))
    )
    tree = render(lists.render)

    owner = next(
        e for e in tree.of_type("Select") if e._props.get("aria-label") == "Owner"
    )
    assert "cf-select-on" in owner._classes
    assert owner._props["display-value"] == synthetic.OWNER

    status = next(
        e for e in tree.of_type("Select") if e._props.get("aria-label") == "Status"
    )
    assert "cf-select-on" not in status._classes
    assert status._props["display-value"] == "Status", "an idle chip lost its name"


def test_the_tooltip_opens_away_from_the_menu(render, warehouse):
    """A tooltip under a control that opens its menu directly underneath lands
    on the menu's first option. It did: `Filter by pi` sat on top of the first
    PI in the list, which in this corpus is a whole study title."""
    tree = render(lists.render)

    # By text, because the page carries other tooltips — the overflow menu and
    # the pager arrows — and those hang below their controls quite correctly.
    tooltips = [
        e
        for e in tree.elements
        if type(e).__name__ == "Tooltip"
        and str(getattr(e, "text", "")).startswith("Filter by ")
    ]
    assert tooltips, "the chips lost their tooltips"
    for tip in tooltips:
        assert tip._props.get("self") == "bottom middle", "the tooltip hangs below"
        assert tip._props.get("anchor") == "top middle"


def test_the_tooltip_does_not_lowercase_an_acronym():
    """`Filter by pi` and `Filter by irb / protocol`. The two labels that are
    acronyms are exactly the two a mechanical `.lower()` gets wrong."""
    from casefinder.ui.components.filters import _tooltip

    assert _tooltip("PI", []) == "Filter by PI"
    assert _tooltip("IRB / protocol", []) == "Filter by IRB / protocol"
    assert _tooltip("Owner", ["Archana Bhat"]) == "Owner: Archana Bhat"


def test_the_menu_is_capped_so_a_long_option_cannot_widen_it():
    """One PI in this corpus is a study title, so a 170px chip opened a 438px
    menu that escaped the content area. Capped and wrapped rather than
    ellipsised: the reader is choosing between these and has to tell them
    apart."""
    css = _chip_css()
    assert ".cf-select-menu {" in css and "max-width:340px" in css
    assert "white-space:normal" in css, "a long option would be clipped instead"
