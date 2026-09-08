"""Lean-UI acceptance tests — spec section 13.3, UX-T1 through UX-T7.

These are the tests that keep the design from eroding. Every rule here is one
that is easy to break by adding something reasonable: a Search button beside the
search box, an Open button on a row, a Save button in the list toolbar. None of
those would look wrong in a diff. They are wrong against the spec, and the only
way to keep them out is to assert on the rendered screen.

Each page is rendered into a throwaway NiceGUI client and the resulting element
tree is inspected. No browser, no screenshots — these are questions about what
exists on a screen, not about how it looks.
"""

from __future__ import annotations

import dataclasses

import pytest
import synthetic

from casefinder import ask, config
from casefinder.ui import (
    ask_page,
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

# Words that must never appear on a filled button anywhere in the app.
ADMIN_LABELS = {"Save", "Export", "Columns", "Refresh", "New view", "Apply", "Apply filters"}


def _menu_texts(tree) -> set[str]:
    """Labels that exist only behind a menu.

    A `ui.menu_item` puts its label on a child item-section rather than on
    itself, so the text and the "is it behind a menu" question are answered on
    the same element.
    """
    return {
        e.text
        for e in tree.of_type("ItemSection")
        if getattr(e, "text", "") and tree.is_inside(e, "Menu")
    }


@pytest.fixture
def list_page(render, warehouse):
    return render(lists.render)


@pytest.fixture
def search_idle(render, warehouse):
    return render(search.render)


@pytest.fixture
def search_results(render, warehouse):
    from casefinder.models import SearchHit

    warehouse.hits = [
        SearchHit.from_row(
            {
                "case_number": "CASE-056576",
                "subject": "Cohort extract request",
                "status": "Open",
                "turn_count": 4,
                "matching_turns": 2,
                "matched_case_fields": True,
                "total_matches": 2,
                "snippets": [{"turn_seq": 1, "actor_role": "customer", "text": "omop cohort"}],
            }
        )
    ]
    ui_state.state.search.text = "omop"
    ui_state.state.search.executed = True
    return render(search.render)


@pytest.fixture
def case_page(render, warehouse):
    from casefinder.models import Comment

    warehouse.comments = [
        Comment.from_row(
            {
                "turn_seq": 1,
                "turn_ts": None,
                "who": "Requester",
                "actor_role": "customer",
                "source_object": "EmailMessage",
                "direction": "inbound",
                "body": "Please extract the cohort.",
            }
        )
    ]
    return render(case_detail.render, "CASE-056576")


# --------------------------------------------------------------------------
# UX-T1 — at most one primary filled action per screen
# --------------------------------------------------------------------------


def _primaries(tree):
    return [b.text for b in tree.with_class("cf-primary")]


def test_the_list_has_no_primary_action(list_page):
    """A triage list is something you read. There is nothing to submit."""
    assert _primaries(list_page) == []


def test_search_has_no_primary_action(search_idle, search_results):
    assert _primaries(search_idle) == []
    assert _primaries(search_results) == []


def test_a_case_has_no_primary_action(case_page):
    """Copy summary is real but secondary — FR-CASE-6."""
    assert _primaries(case_page) == []
    assert "Copy summary" in case_page.button_labels()


def test_saved_views_has_no_primary_action(render, warehouse):
    assert _primaries(render(saved_views.render)) == []


def test_settings_has_no_primary_action(render, warehouse):
    assert _primaries(render(settings.render)) == []


def test_the_sql_page_has_exactly_one(render, warehouse):
    """FR-SQL-5. Run is filled; Check cost is a real secondary beside it,
    because a free-form query is the one case where the user cannot know what
    they are about to spend."""
    tree = render(sql_page.render)
    assert _primaries(tree) == ["Run"]
    assert "Check cost" in [b.text for b in tree.with_class("cf-secondary")]


def test_ask_has_at_most_one_before_and_after_generating(render, monkeypatch, warehouse):
    from casefinder import ask

    monkeypatch.setattr(ask, "available", lambda: True)
    monkeypatch.setattr(ask, "model_name", lambda: "gemini-2.5-flash")
    monkeypatch.setattr(ask_page.page, "sql", "", raising=False)

    before = render(ask_page.render)
    assert _primaries(before) == []

    monkeypatch.setattr(ask_page.page, "sql", "SELECT 1", raising=False)
    after = render(ask_page.render)
    assert _primaries(after) == ["Run query"]


def test_the_connection_screen_has_exactly_one(render):
    """One state, one action — FR-START-2. No setup dashboard."""
    tree = render(shell.connection_screen, "no credentials found")
    assert _primaries(tree) == ["Retry"]


def test_every_filled_button_came_from_the_primary_helper(list_page, case_page, search_idle):
    """The rule is enforceable only because `primary()` is the one way in.

    A page that reaches past it for a filled Quasar button would pass the count
    above while breaking the invariant, so the marker class is also the
    definition of what counts.
    """
    for tree in (list_page, case_page, search_idle):
        for button in tree.buttons():
            filled = button._props.get("unelevated") or button._props.get("push")
            assert not filled, f"{button.text!r} is filled without going through primary()"


# --------------------------------------------------------------------------
# UX-T2 — search has no Search button
# --------------------------------------------------------------------------


def test_there_is_no_search_button(search_idle, search_results):
    """A button beside a search box explains what the box already says."""
    for tree in (search_idle, search_results):
        assert not [
            label for label in tree.button_labels() if "search" in label.lower()
        ]


def test_enter_is_what_runs_a_search(search_idle):
    boxes = search_idle.of_type("Input")
    assert boxes, "the search box is missing"
    assert any("keydown.enter" in search_idle.handlers(box) for box in boxes)


def test_the_idle_screen_stays_sparse(search_idle):
    """FR-SEARCH-1: no tips card, no recent searches, no illustration."""
    assert search_idle.of_type("Card") == []
    assert "Search historical support cases" in search_idle.text
    assert "Recent" not in search_idle.text


# --------------------------------------------------------------------------
# UX-T3 — no Open button on a row
# --------------------------------------------------------------------------


def test_list_rows_have_no_open_button(list_page):
    """Nothing clickable inside a row but the row.

    Checked by ancestry rather than by label, because the rule is about the
    shape of the table and not about the word "Open" — a `visibility` icon
    button in the last column would break it just as thoroughly.
    """
    cells = [e for e in list_page.elements if getattr(e, "tag", None) == "td"]
    assert cells, "the table did not render"
    for button in list_page.buttons():
        inside_table = [
            a for a in list_page.ancestors(button) if getattr(a, "tag", None) in {"td", "tr"}
        ]
        assert not inside_table, f"{button.text!r} sits inside a table row"


def test_the_row_itself_is_the_navigation(list_page):
    rows = [e for e in list_page.elements if "cf-row" in e._classes]
    assert rows, "no clickable rows rendered"
    assert all(list_page.clickable(row) for row in rows)


def test_a_result_is_a_click_target_not_a_card_with_a_button(search_results):
    hits = [e for e in search_results.elements if "cf-row" in e._classes]
    assert hits
    assert all(search_results.clickable(hit) for hit in hits)
    assert "Open" not in search_results.button_labels()


def test_clicking_a_row_navigates_to_that_case(warehouse, monkeypatch):
    """The handler is checked directly, because the click target is a `tr`."""
    from casefinder.models import TriageRow

    went: list[str] = []
    monkeypatch.setattr(lists.ui.navigate, "to", lambda target, **k: went.append(target))
    row = TriageRow.from_row({"case_number": "CASE-056576", "total_matches": 1})
    lists._open_case(row)
    assert went == ["/case/CASE-056576"]


# --------------------------------------------------------------------------
# UX-T4 — the default case tab is Comments
# --------------------------------------------------------------------------


def test_a_case_opens_on_the_conversation(case_page):
    panels = case_page.of_type("TabPanels")
    assert panels, "the tabs did not render"
    assert panels[0].value == "Conversation"


def test_comments_and_messages_are_one_surface(case_page):
    """They were the same rows at two densities, and the second tab paid for
    its own scan of the body column to fetch two columns the first had left
    behind. One tab, one query, a density control inside it."""
    labels = [t._props.get("name") for t in case_page.of_type("Tab")]
    assert labels == ["Conversation", "Timeline", "Files"]
    assert "Messages" not in labels


def test_there_is_no_overview_tab(case_page):
    """FR-CASE-1 puts the metadata above the tabs, so an Overview tab would
    duplicate what is already on screen."""
    labels = [t._props.get("name") for t in case_page.of_type("Tab")]
    assert "Overview" not in labels


def test_only_the_comments_query_runs_when_a_case_opens(case_page, warehouse):
    """The cost half of UX-T4 — see the module docstring in case_detail.

    The timeline and the attachments are each a full scan of the body column.
    Building every panel eagerly is the ~590 MB path the spec's cost table
    calls out as the thing v2 replaced — and merging Messages into the
    conversation took one of those scans out of the application entirely.
    """
    assert "comments" in warehouse.calls
    assert "timeline" not in warehouse.calls
    assert "attachments" not in warehouse.calls


def test_selecting_a_tab_is_what_loads_it(render, warehouse):
    tree = render(case_detail.render, "CASE-056576")
    tabs = tree.of_type("Tabs")[0]
    before = list(warehouse.calls)
    tabs.value = "Timeline"
    assert "timeline" in warehouse.calls, "selecting Timeline did not load it"
    assert "attachments" not in warehouse.calls
    assert before != warehouse.calls


def test_a_tab_is_not_reloaded_when_it_is_revisited(render, warehouse):
    tree = render(case_detail.render, "CASE-056576")
    tabs = tree.of_type("Tabs")[0]
    tabs.value = "Timeline"
    tabs.value = "Conversation"
    tabs.value = "Timeline"
    assert warehouse.calls.count("timeline") == 1


# --------------------------------------------------------------------------
# UX-T5 — no permanent admin toolbar on the list
# --------------------------------------------------------------------------


def test_the_list_has_no_admin_buttons(list_page):
    for label in list_page.button_labels():
        assert label not in ADMIN_LABELS, f"{label!r} is a toolbar button"


def test_filters_apply_without_an_apply_button(list_page):
    """FR-LIST-6: a filter change re-runs the query on its own."""
    assert "Apply" not in list_page.text
    switches = list_page.of_type("Switch")
    assert switches, "the Open only toggle is missing"
    assert all(s._change_handlers for s in switches)
    for select in list_page.of_type("Select"):
        assert select._change_handlers, "a filter select has nothing to trigger"


def test_the_admin_actions_exist_but_live_in_the_overflow(list_page):
    """FR-LIST-2 removes the toolbar, not the features."""
    behind_a_menu = _menu_texts(list_page)
    assert "Save current view…" in behind_a_menu
    assert "Export metadata CSV" in behind_a_menu
    assert "Refresh from BigQuery" in behind_a_menu


# --------------------------------------------------------------------------
# UX-T6 — advanced controls are progressive
# --------------------------------------------------------------------------


def test_column_choice_export_and_save_are_not_all_on_screen_at_once(list_page):
    """All three exist. None of them is visible until the `…` is opened."""
    behind_a_menu = _menu_texts(list_page)
    for text in ("Save current view…", "Export metadata CSV", "Columns"):
        assert text in behind_a_menu, f"{text} is not behind the overflow"
        assert text not in list_page.button_labels()


def _inline_filter_controls(tree) -> list:
    inline = [e for e in tree.elements if "cf-filters-inline" in e._classes]
    assert inline, "the inline filter row is missing"
    return [
        e
        for e in tree.elements
        if type(e).__name__ in {"Select", "Switch"}
        and any("cf-filters-inline" in a._classes for a in tree.ancestors(e))
    ]


def test_only_the_priority_filters_are_inline(list_page):
    """FR-LIST-6 plus Owner — six, and not a seventh (D22).

    The spec says five. Owner was added because it was the one dimension with a
    column and a sort key but no way to filter on it, and because "whose is it"
    is the question a queue gets asked first. That is the argued exception, not
    an opening: past six the row stops being a row and becomes a control panel,
    which is what FR-LIST-7's disclosure exists to avoid.
    """
    assert len(_inline_filter_controls(list_page)) == 6


def test_the_owner_filter_is_the_first_dimension_in_the_row(list_page):
    """Next to `Open only`, because together they are "what is on my plate"."""
    controls = _inline_filter_controls(list_page)
    assert type(controls[0]).__name__ == "Switch"
    assert controls[1]._props.get("aria-label") == "Owner"


def test_the_owner_filter_offers_the_owners_the_warehouse_reported(list_page, warehouse):
    owner_select = next(
        e for e in list_page.of_type("Select") if e._props.get("aria-label") == "Owner"
    )
    # Quasar wants `{value, label}` pairs; the labels are what a user picks from.
    offered = [option["label"] for option in owner_select._props["options"]]
    assert offered == warehouse.facets.owners


def test_a_narrow_window_gets_one_disclosure_instead(list_page):
    collapsed = [e for e in list_page.elements if "cf-filters-collapsed" in e._classes]
    assert len(collapsed) == 1


def test_the_disclosure_carries_the_same_filters_as_the_row(list_page):
    """FR-LIST-7. The two copies are built by one function; prove they agree.

    A narrow window is not a reduced feature set — it is the same six controls
    behind a button. Owner in the row but not in the menu would mean the filter
    silently disappears when the window is resized.
    """
    inline = {
        e._props.get("aria-label")
        for e in _inline_filter_controls(list_page)
        if type(e).__name__ == "Select"
    }
    behind = {
        e._props.get("aria-label")
        for e in list_page.of_type("Select")
        if any("cf-filters-collapsed" in a._classes for a in list_page.ancestors(e))
    }
    assert "Owner" in inline
    assert inline == behind


# --------------------------------------------------------------------------
# D22 — the jump from a case to its owner's queue
# --------------------------------------------------------------------------


def test_a_case_page_offers_its_owner_as_a_queue(case_page, warehouse):
    """Standing on a case, "show me everything else this person has"."""
    assert f"Cases owned by {warehouse.header.owner}" in _menu_texts(case_page)


def test_the_owner_jump_is_a_filter_and_not_a_text_search(case_page, warehouse):
    """A text search for a name also finds cases that merely mention them.

    Owner is a field with a filter of its own, so the menu item says `Cases
    owned by`, not the `Search for` the PI and IRB items run.
    """
    behind_a_menu = _menu_texts(case_page)
    assert f"Search for {warehouse.header.owner}" not in behind_a_menu
    # The other two are still text searches — this is not a claim about them.
    assert f"Search for {warehouse.header.pi}" in behind_a_menu


def test_a_case_with_no_owner_offers_no_jump(render, warehouse):
    """An unassigned case would otherwise offer `Cases owned by `."""
    warehouse.header = dataclasses.replace(warehouse.header, owner="")
    tree = render(case_detail.render, "CASE-056576")
    assert not [t for t in _menu_texts(tree) if t.startswith("Cases owned by")]


def test_the_owner_jump_opens_that_persons_open_queue(monkeypatch):
    """Sets the filters through a view, and leaves for the list.

    Going through `_apply_view` rather than writing to `state.lists.filters` is
    the whole point: `lists.render` re-applies the default view whenever the
    column list is empty, which it is until Lists has been visited once. Hence
    the empty columns here — this is the cold-start case that a direct write
    would silently lose.
    """
    ui_state.state.lists.columns = ()
    ui_state.state.lists.offset = 300
    gone_to: list[str] = []
    monkeypatch.setattr(lists.ui.navigate, "to", lambda target: gone_to.append(target))
    lists.focus_on_owner(synthetic.OWNER)

    assert gone_to == ["/lists"]
    assert ui_state.state.lists.view_name == f"Cases owned by {synthetic.OWNER}"
    assert ui_state.state.lists.filters.owners == [synthetic.OWNER]
    assert ui_state.state.lists.filters.open_only is True
    assert ui_state.state.lists.filters.statuses == []
    assert ui_state.state.lists.offset == 0, "the old page number outlived its filter"
    assert ui_state.state.lists.columns, "a cold start would render no columns"


def test_the_schema_reference_on_the_sql_page_is_behind_a_disclosure(render, warehouse):
    tree = render(sql_page.render)
    expansions = tree.of_type("Expansion")
    assert any(e._props.get("label") == "Tables" for e in expansions)


# --------------------------------------------------------------------------
# UX-T7 — flat surfaces, no nested cards
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["list_page", "search_idle", "search_results", "case_page"])
def test_the_main_surfaces_are_not_card_dashboards(name, request):
    tree = request.getfixturevalue(name)
    cards = tree.of_type("Card")
    assert not cards, f"{name} renders {len(cards)} cards"


def test_no_card_ever_contains_another_card(render, warehouse):
    """The dialog is allowed a card. A card inside it would be UX-INV-6."""
    for build in (lists.render, settings.render, sql_page.render):
        tree = render(build)
        for card in tree.of_type("Card"):
            assert not tree.is_inside(card, "Card")


def test_case_metadata_is_never_a_card(case_page):
    """UX-INV-6 and FR-CASE-2, which the rebuild had every opportunity to
    break: a rail full of label/value pairs is exactly where cards creep in.

    The metric strip itself is gone. Status, owner and age moved into the
    identity bar that follows the reader down a long thread, and repeating
    them in the rail would have been the redundancy this page was rebuilt to
    remove — so what is asserted now is where each fact lives, not that all of
    them live in one strip.
    """
    assert case_page.of_type("Card") == []
    text = case_page.text
    assert "Open" in text and synthetic.OWNER in text, "the identity bar lost its state"
    for attribute in ("PI", "Department", "IRB / protocol", "Funding"):
        assert attribute in text, f"the rail lost {attribute}"
    assert "Status" not in text, "status is in the bar; the rail repeats it"


# --------------------------------------------------------------------------
# Navigation — spec section 6.1
# --------------------------------------------------------------------------


def _rail_labels(tree) -> list[str]:
    return [
        label.text
        for label in tree.of_type("Label")
        if any("cf-nav" in a._classes for a in tree.ancestors(label))
    ]


def test_the_rail_holds_the_destinations_and_settings(render, warehouse):
    """Nav rule 1 caps the rail at four destinations plus Settings. Ask is
    conditional, so the assertion is against the destination list rather than
    against a hardcoded five — but the ceiling is still asserted, because the
    rule the rail is protecting is "no more than four", not "however many".
    """
    tree = render(shell.rail, "lists")
    items = [e for e in tree.elements if "cf-nav" in e._classes]
    expected = [label for _, label, _, _ in shell.DESTINATIONS] + ["Settings"]

    assert len(shell.DESTINATIONS) <= 4
    assert len(items) == len(expected)
    assert _rail_labels(tree) == expected


def test_the_app_opens_on_search_and_lists_is_second(render, warehouse):
    """D17, and the order in the rail is the same fact as the landing page.

    `/` *is* Search rather than a redirect to it. A native window gets one page
    load to put something on the screen, and a bounce spends it on a round trip
    that draws nothing.
    """
    keys = [key for key, *_ in shell.DESTINATIONS]
    targets = {key: target for key, _, _, target in shell.DESTINATIONS}

    assert keys[:2] == ["search", "lists"]
    assert targets["search"] == "/"
    assert _rail_labels(render(shell.rail, "search"))[:2] == ["Search", "Lists"]


def test_every_destination_in_the_rail_is_a_route_that_exists():
    """A rail entry pointing at an unregistered path is a dead menu item, and
    nothing else in the app would notice — the click just 404s."""
    from nicegui import Client

    from casefinder import main  # noqa: F401  (importing is what registers them)

    registered = set(Client.page_routes.values())
    targets = {target for *_, target in shell._ALL_DESTINATIONS} | {"/settings"}

    assert targets <= registered


def test_the_rail_chips_are_all_the_same_rectangle():
    """The selected background was as wide as its own label, so it read as a
    badge around a word rather than a row in a menu. The rail is a `ui.column`,
    and NiceGUI's `.nicegui-column` puts `align-items: flex-start` on it — the
    fix has to be on the chip, because nothing in this project's CSS is what
    made them content-width in the first place."""
    assert "align-self: stretch" in theme._CSS.split(".cf-nav {")[1].split("}")[0]


def test_pointing_at_the_selected_destination_does_not_recolour_it():
    """`.cf-nav:hover` is a class *and* a pseudo-class, so it outranks the
    single class `.cf-nav-active` and replaced the selection colour with the
    hover grey. The one item whose shading should never change was the only
    one that did."""
    assert ".cf-nav:not(.cf-nav-active):hover" in theme._CSS
    assert "\n.cf-nav:hover" not in theme._CSS


def test_ask_is_not_offered_unless_it_is_switched_on(render, warehouse):
    """The natural-language mode is off by default, and off means invisible:
    no destination, nothing in Settings naming a model. A feature that is
    merely disabled still invites the question of why it does not work.
    """
    assert config.ASK_ENABLED is False, "the default changed; the rest of this is moot"
    assert "Ask" not in _rail_labels(render(shell.rail, "lists"))
    assert "Vertex" not in render(settings.render).text


def test_the_ask_route_sends_you_home_rather_than_breaking(monkeypatch):
    """The route stays registered when the feature is off, because it outlives
    the setting: a bookmark, or a link copied while Ask was on, should land on
    the first screen instead of a 404 that reads as a broken app. Asserting on
    the navigation rather than on a rendered page, since there is no page.
    """
    from casefinder import main

    went_to: list[str] = []
    monkeypatch.setattr(main.ui.navigate, "to", lambda target: went_to.append(target))
    monkeypatch.setattr(main.config, "ASK_ENABLED", False)
    monkeypatch.setattr(
        main, "gated", lambda *a, **k: pytest.fail("the ask page rendered while switched off")
    )

    main.ask_route()
    assert went_to == ["/"]


def test_ask_is_offered_when_it_is_switched_on(render, warehouse, monkeypatch):
    monkeypatch.setattr(shell, "DESTINATIONS", shell._ALL_DESTINATIONS)
    monkeypatch.setattr(config, "ASK_ENABLED", True)
    monkeypatch.setattr(ask, "model_name", lambda: "gemini-2.5-flash")

    assert _rail_labels(render(shell.rail, "lists")) == [
        "Search",
        "Lists",
        "Ask",
        "SQL",
        "Settings",
    ]
    assert "Vertex AI" in render(settings.render).text


def test_about_is_not_a_destination(render, warehouse):
    tree = render(shell.rail, "lists")
    assert "About" not in tree.text


def test_about_lives_inside_settings(render, warehouse):
    tree = render(settings.render)
    assert "About" in tree.text
    assert f"Case Finder {settings.config.VERSION}" in tree.text


def test_the_active_destination_is_marked_quietly(render, warehouse):
    tree = render(shell.rail, "search")
    active = [e for e in tree.elements if "cf-nav-active" in e._classes]
    assert len(active) == 1


# --------------------------------------------------------------------------
# Freshness — spec section 5.6
# --------------------------------------------------------------------------


def test_a_fresh_snapshot_states_its_age_without_a_banner(list_page):
    assert "Data as of" in list_page.text
    assert not [e for e in list_page.elements if "cf-banner" in e._classes]


def test_a_stale_snapshot_warns_once_at_the_top(render, warehouse):
    warehouse.stale_days = 22
    tree = render(lists.render)
    banners = [e for e in tree.elements if "cf-banner" in e._classes]
    assert len(banners) == 1
    assert "22 days old" in tree.text


# --------------------------------------------------------------------------
# Copy summary — FR-CASE-6
# --------------------------------------------------------------------------


@pytest.fixture
def clipboard(monkeypatch):
    written: list[str] = []
    monkeypatch.setattr(case_detail.ui.clipboard, "write", lambda text: written.append(text))
    monkeypatch.setattr(case_detail.ui, "notify", lambda *a, **k: None)
    return written


def test_copy_summary_carries_the_case_number_and_triage_metadata(
    clipboard, warehouse, render
):
    from casefinder.models import Comment

    warehouse.comments = [
        Comment.from_row(
            {
                "turn_seq": i,
                "who": f"Person {i}",
                "body": f"comment {i}",
                "source_object": "CaseComment",
            }
        )
        for i in range(1, 6)
    ]
    case_detail._copy_summary(warehouse.header)

    text = clipboard[0]
    assert "CASE-056576" in text
    assert "Status: Open" in text
    assert "PI: Dr Example" in text
    assert "Dept: Medicine" in text
    assert "IRB: IRB-1234" in text
    assert "Funded: Funded" in text


def test_copy_summary_takes_the_last_three_comments_only(clipboard, warehouse):
    from casefinder.models import Comment

    warehouse.comments = [
        Comment.from_row({"turn_seq": i, "who": "P", "body": f"comment {i}"})
        for i in range(1, 6)
    ]
    case_detail._copy_summary(warehouse.header)
    text = clipboard[0]
    assert "comment 5" in text
    assert "comment 3" in text
    assert "comment 2" not in text


def test_copy_summary_never_touches_disk(clipboard, warehouse, tmp_path, monkeypatch):
    """FR-CASE-6 is a clipboard action. The summary contains comment bodies, so
    a file would be PHI at rest — spec section 9.3."""
    monkeypatch.chdir(tmp_path)
    case_detail._copy_summary(warehouse.header)
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------
# Files tab — FR-CASE-9
# --------------------------------------------------------------------------


def test_the_files_tab_states_the_box_policy(render, warehouse):
    tree = render(case_detail._files, warehouse.attachments)
    assert "Box project folder" in tree.text


def test_the_files_tab_offers_no_upload_or_delete(render, warehouse):
    tree = render(case_detail._files, warehouse.attachments)
    for label in tree.button_labels():
        assert label.lower() not in {"upload", "delete", "preview", "download"}


def test_the_archive_era_says_attachments_were_not_retained(render, warehouse):
    """Through the tab rather than through `_files`, because the tab is where
    the query now lives: `_files` draws rows it is handed and could not query
    if it wanted to, so calling it directly would assert nothing about cost.
    """
    ui_state.state.era_key = "archive"
    tree = render(case_detail._tabs, warehouse.header)
    tree.of_type("Tabs")[0].value = "Files"
    assert "not retained for this era" in tree.text
    assert "attachments" not in warehouse.calls


# --------------------------------------------------------------------------
# Ask — FR-ASK-4
# --------------------------------------------------------------------------


def test_ask_shows_the_query_before_there_is_anything_to_run(render, monkeypatch, warehouse):
    """Generating and running are two separate clicks, deliberately."""
    from casefinder import ask

    monkeypatch.setattr(ask, "available", lambda: True)
    monkeypatch.setattr(ask, "model_name", lambda: "gemini-2.5-flash")
    monkeypatch.setattr(ask, "to_sql", lambda question, era: "SELECT 1")
    ask_page.page.sql = ""
    ask_page.page.result = None
    ask_page.page.error = ""

    tree = render(ask_page.render)
    assert "Run query" not in tree.button_labels(), "a query ran before it was written"

    ask_page.page.sql = "SELECT created_year, COUNT(*) FROM t GROUP BY 1"
    reviewed = render(ask_page.render)
    assert "Run query" in reviewed.button_labels()
    assert "GROUP BY 1" in reviewed.text


def test_ask_points_at_the_sql_page_when_vertex_is_off(render, monkeypatch, warehouse):
    from casefinder import ask

    monkeypatch.setattr(ask, "available", lambda: False)
    monkeypatch.setattr(ask, "why_unavailable", lambda: "Vertex AI API is not enabled")
    tree = render(ask_page.render)
    assert "Write SQL instead" in tree.button_labels()
    assert _primaries(tree) == []


def test_refresh_from_bigquery_refreshes_the_filter_values_too(monkeypatch, warehouse):
    """Finding #06. Facets live in their own cache on a much longer window, so
    leaving them out meant a user who had explicitly asked for fresh data could
    still be choosing from an hour-old list of owners — and the one thing an
    explicit refresh must not do is refresh only part of the screen."""
    from casefinder import cache

    cache.results.get_or_load("triage|current|x", lambda: "stale rows")
    cache.results.get_or_load("freshness|current", lambda: "stale date")
    cache.facets.get_or_load("facets|current|True", lambda: "stale owners")

    reloaded: list[str] = []
    monkeypatch.setattr(lists.ui, "notify", lambda *a, **k: None)
    monkeypatch.setattr(lists.ui.navigate, "reload", lambda: reloaded.append("reload"))

    lists._hard_refresh()

    assert len(cache.results) == 0
    assert len(cache.facets) == 0, "the filter dropdowns kept their old values"
    # And the redraw goes back through `render`, which puts a spinner up and
    # issues the three now-uncached queries concurrently, rather than freezing
    # the window on them one at a time.
    assert reloaded == ["reload"]


def test_clearing_the_cache_also_forgets_the_vertex_probe(monkeypatch):
    """Finding #07. The probe failure is cached for the life of the process,
    which is right as a cache and wrong as a verdict — a project whose Vertex
    API was switched on a minute ago should not need a restart to be noticed."""
    from casefinder import cache, data

    forgotten: list[str] = []
    monkeypatch.setattr(ask, "reset", lambda: forgotten.append("probe"))
    cache.results.get_or_load("anything", lambda: 1)

    data.clear_caches()

    assert forgotten == ["probe"]
    assert len(cache.results) == 0


def test_every_registered_page_actually_draws(render, warehouse):
    """A route whose handler cannot run is invisible until someone clicks it.

    `/views` was briefly exactly that: the page function had the same name as
    the module it calls, so the name in its body resolved to the function
    rather than to the screen, and the route raised the moment it was opened.
    Nothing else in the application would have noticed — the rail does not
    point at it, and the tests rendered the screen directly rather than through
    its route.
    """
    import inspect

    from nicegui import Client

    from casefinder import main  # noqa: F401  (importing is what registers them)

    routes = {path: func for func, path in Client.page_routes.items()}
    assert "/views" in routes and "/case/{case_number}" in routes

    for path, func in sorted(routes.items()):
        arguments = ["CASE-056576"] * len(inspect.signature(func).parameters)
        tree = render(func, *arguments)
        assert tree.elements, f"{path} drew nothing at all"


def test_related_cases_are_grouped_by_strength_in_the_rail(render, warehouse):
    """FR-CASE-10, moved off the bottom of the page. Twenty-three of them below
    a hundred and fifteen entries is a footer nobody reaches; in the rail they
    are reachable from anywhere in the thread, and grouped so the two about the
    same study are not below ten that share a building."""
    from casefinder.models import RelatedCase

    warehouse.related = [
        RelatedCase.from_row(
            {"case_number": "CASE-1", "subject": "Same study", "same_irb": True, "same_pi": True}
        ),
        RelatedCase.from_row(
            {"case_number": "CASE-2", "subject": "Same person", "same_pi": True}
        ),
        RelatedCase.from_row(
            {"case_number": "CASE-3", "subject": "Same building", "same_department": True}
        ),
    ]

    tree = render(case_detail.render, "CASE-056576")
    text = tree.text

    assert "Same IRB protocol · 1" in text
    assert "Same PI · 1" in text
    assert "Same department only · 1" in text
    assert tree.with_class("cf-case-rail"), "the rail is gone"


def test_only_the_strongest_group_of_related_cases_opens_itself(render, warehouse):
    """A department in this corpus can run to dozens of cases, and a panel that
    opens all of them is the scroll the rail exists to end."""
    from casefinder.models import RelatedCase

    warehouse.related = [
        RelatedCase.from_row({"case_number": "CASE-1", "subject": "a", "same_irb": True}),
        RelatedCase.from_row({"case_number": "CASE-2", "subject": "b", "same_department": True}),
    ]

    tree = render(case_detail.render, "CASE-056576")
    groups = [e for e in tree.of_type("Expansion") if "cf-rel-group" in e._classes]

    assert len(groups) == 2
    assert groups[0].value is True, "the strongest group is collapsed"
    assert groups[1].value is False, "the weakest group opens itself"


def test_the_request_is_pinned_wherever_the_integration_filed_it(render, warehouse):
    """Not always the description. On a good many cases the description is
    pasted email and the form arrives as the first turn instead — and a version
    of this that only looked at the description left the request sitting where
    it is least use: entry one of a hundred and fifteen."""
    import datetime as dt

    from casefinder.models import CaseHeader, Comment

    payload = synthetic.intake_payload()
    warehouse.header = CaseHeader.from_row(
        {"case_id": "1", "case_number": "CASE-1", "subject": "Registry linkage",
         "status": "Open", "description": "On Apr 23, 2026 Dana wrote: see below."}
    )
    warehouse.comments = [
        Comment.from_row({"turn_seq": 1, "turn_ts": dt.datetime(2026, 4, 23),
                          "who": synthetic.SUPPORT_ALIAS, "body": payload}),
        Comment.from_row({"turn_seq": 2, "turn_ts": dt.datetime(2026, 4, 24),
                          "who": synthetic.OWNER, "body": "Picking this up."}),
    ]

    text = render(case_detail.comment_stream, warehouse.header).text

    assert "The request" in text, "the form was not lifted out of the thread"
    assert "1 entries" in text, "the turn carrying it stayed in the thread"


def test_the_requester_is_shown_beside_the_case_not_inside_the_request(render, warehouse):
    """Seven of the form's fields describe the person rather than the request.
    They belong beside the case; nothing is lost, because the grid stops
    drawing them once they are."""
    from casefinder.models import CaseHeader

    warehouse.header = CaseHeader.from_row(
        {"case_id": "1", "case_number": "CASE-1", "subject": "Registry linkage",
         "status": "Open", "description": synthetic.intake_payload()}
    )

    tree = render(case_detail.render, "CASE-1")
    text = tree.text

    assert "Requester" in text and synthetic.REQUESTER in text
    labels = [e.text for e in tree.with_class("cf-metric-label")]
    assert "Last name" not in labels, "the requester is still in the request grid"
    assert "Email" in labels, "the requester panel lost the address"


def test_the_rail_leaves_out_what_the_case_has_no_value_for(render, warehouse):
    """A rail is one column with no fixed positions, so an unrecorded Type
    costs a whole line of a panel that also has to hold the related cases —
    and on this corpus Type and Reason are unrecorded on most cases."""
    from casefinder.models import MISSING, CaseHeader

    warehouse.header = CaseHeader.from_row(
        {"case_id": "1", "case_number": "CASE-1", "subject": "x", "status": "Open",
         "pi": synthetic.PI, "type": None, "reason": None}
    )

    about = warehouse.header.about()

    assert ("PI", synthetic.PI) in about
    assert not [row for row in about if row[1] == MISSING], "an empty row took rail space"
    assert not [row for row in about if row[0] == "Owner"], "the bar already says the owner"
