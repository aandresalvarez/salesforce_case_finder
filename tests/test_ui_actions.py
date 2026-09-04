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

import pytest

from casefinder import ask, config
from casefinder.ui import ask_page, case_detail, lists, search, settings, shell, sql_page

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
    shell.state.search.text = "omop"
    shell.state.search.executed = True
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
    assert _primaries(render(lists.render_saved_views)) == []


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


def test_a_case_opens_on_comments(case_page):
    panels = case_page.of_type("TabPanels")
    assert panels, "the tabs did not render"
    assert panels[0].value == "Comments"


def test_the_tab_order_puts_messages_second(case_page):
    labels = [t._props.get("name") for t in case_page.of_type("Tab")]
    assert labels == ["Comments", "Messages", "Timeline", "Files"]


def test_there_is_no_overview_tab(case_page):
    """FR-CASE-1 puts the metadata above the tabs, so an Overview tab would
    duplicate what is already on screen."""
    labels = [t._props.get("name") for t in case_page.of_type("Tab")]
    assert "Overview" not in labels


def test_only_the_comments_query_runs_when_a_case_opens(case_page, warehouse):
    """The cost half of UX-T4 — see the module docstring in case_detail.

    Messages, timeline, and attachments are each a full scan of the body
    column. Building all four panels eagerly is the ~590 MB path the spec's
    cost table calls out as the thing v2 replaced.
    """
    assert "comments" in warehouse.calls
    assert "messages" not in warehouse.calls
    assert "timeline" not in warehouse.calls
    assert "attachments" not in warehouse.calls


def test_selecting_a_tab_is_what_loads_it(render, warehouse):
    tree = render(case_detail.render, "CASE-056576")
    tabs = tree.of_type("Tabs")[0]
    before = list(warehouse.calls)
    tabs.value = "Messages"
    assert "messages" in warehouse.calls, "selecting Messages did not load it"
    assert "timeline" not in warehouse.calls
    assert before != warehouse.calls


def test_a_tab_is_not_reloaded_when_it_is_revisited(render, warehouse):
    tree = render(case_detail.render, "CASE-056576")
    tabs = tree.of_type("Tabs")[0]
    tabs.value = "Messages"
    tabs.value = "Comments"
    tabs.value = "Messages"
    assert warehouse.calls.count("messages") == 1


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


def test_only_the_five_priority_filters_are_inline(list_page):
    """FR-LIST-6. Anything past five turns the row into a control panel."""
    inline = [
        e
        for e in list_page.elements
        if "cf-filters-inline" in e._classes
    ]
    assert inline, "the inline filter row is missing"
    controls = [
        e
        for e in list_page.elements
        if type(e).__name__ in {"Select", "Switch"}
        and any("cf-filters-inline" in a._classes for a in list_page.ancestors(e))
    ]
    assert len(controls) == 5


def test_a_narrow_window_gets_one_disclosure_instead(list_page):
    collapsed = [e for e in list_page.elements if "cf-filters-collapsed" in e._classes]
    assert len(collapsed) == 1


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


def test_the_metric_strip_is_a_strip_not_five_cards(case_page):
    """FR-CASE-2 spells this one out."""
    assert case_page.of_type("Card") == []
    assert "Status" in case_page.text
    assert "Messages" in case_page.text


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
    Lists instead of a 404 that reads as a broken app. Asserting on the
    navigation rather than on a rendered page, since there is no page.
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
        "Lists",
        "Search",
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
    tree = render(case_detail._files, warehouse.header)
    assert "Box project folder" in tree.text


def test_the_files_tab_offers_no_upload_or_delete(render, warehouse):
    tree = render(case_detail._files, warehouse.header)
    for label in tree.button_labels():
        assert label.lower() not in {"upload", "delete", "preview", "download"}


def test_the_archive_era_says_attachments_were_not_retained(render, warehouse):
    shell.state.era_key = "archive"
    tree = render(case_detail._files, warehouse.header)
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
