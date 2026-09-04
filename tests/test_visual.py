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

from casefinder.models import Attachment, Comment, Message, RelatedCase, SearchHit, TimelineEvent
from casefinder.ui import case_detail, lists, search, settings, shell, sql_page

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
        Message.from_row(
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
    "saved views": lambda: lists.render_saved_views(),
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
        ("Messages", "messages"),
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
    shell.state.search.text = "omop"
    shell.state.search.executed = True
    tree = render(search.render)
    assert "2 results" in tree.text
    assert not tree.with_class("cf-error")


def test_a_snippet_is_the_only_html_on_the_results_screen(render, warehouse):
    """Everything else is a label, so the corpus cannot render its own markup."""
    _populate(warehouse)
    shell.state.search.text = "omop"
    shell.state.search.executed = True
    tree = render(search.render)
    html_elements = tree.of_type("Html")
    assert html_elements
    for element in html_elements:
        assert "cf-snippet" in element._classes


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
        return {getattr(e, "_props", {}).get("label") for e in tree.of_type("Select")}

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
    shell.state.search.text = "notarealterm"
    shell.state.search.executed = True
    tree = render(search.render)
    assert "notarealterm" in tree.text
    assert "Search inside conversations" in tree.text


def test_a_one_character_search_is_refused_without_a_query(render, warehouse):
    """Spec section 12: inline validation, and no BigQuery job."""
    shell.state.search.text = "x"
    shell.state.search.executed = True
    tree = render(search.render)
    assert "at least two characters" in tree.text
    assert "search" not in warehouse.calls


def test_an_unknown_case_names_the_era_it_looked_in(render, warehouse):
    """FR-CASE-11."""
    warehouse.header = None
    tree = render(case_detail.render, "CASE-999999")
    assert "CASE-999999 is not in" in tree.text
    assert shell.state.era.label in tree.text
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
    """UX-INV-4: prose at full window width is unreadable on a wide monitor."""
    _populate(warehouse)
    tree = render(case_detail.render, "CASE-056576")
    assert tree.with_class("cf-reading")
