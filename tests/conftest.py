"""Shared fixtures.

The default run touches no network and needs no credentials. Tests that do hit
BigQuery are marked `warehouse` and excluded by `addopts`; run them with
`uv run pytest -m warehouse`.

The UI fixtures at the bottom render real NiceGUI pages into an isolated client
and hand back the element tree to assert against. That is enough for the lean-UI
acceptance tests in spec section 13.3, which are all questions about what is on
a screen — how many filled buttons, whether a row has an Open button, which tab
is selected — and none of which need a browser.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import synthetic

from casefinder.config import ERAS


@pytest.fixture(params=list(ERAS.values()), ids=list(ERAS))
def era(request):
    """Every query builder is exercised against both eras.

    The two datasets are not the same shape — the archive has no history or
    attachment tables — and a builder that quietly assumes the richer one is a
    runtime failure the moment a user switches eras.
    """
    return request.param


@pytest.fixture
def current():
    return ERAS["current"]


@pytest.fixture
def archive():
    return ERAS["archive"]


# --------------------------------------------------------------------------
# Rendering a page without a browser
# --------------------------------------------------------------------------


class Tree:
    """A rendered page, queryable by element type, CSS class, and text.

    Deliberately thin. The lean-UI rules are stated in terms of what a user can
    see, so the assertions read best when they are counts over the element tree
    rather than assertions about the code that produced it.
    """

    def __init__(self, client) -> None:
        self.client = client

    @property
    def elements(self) -> list[Any]:
        return list(self.client.elements.values())

    def of_type(self, *names: str) -> list[Any]:
        return [e for e in self.elements if type(e).__name__ in names]

    def with_class(self, name: str) -> list[Any]:
        return [e for e in self.elements if name in e._classes]

    def texts(self) -> list[str]:
        out = []
        for element in self.elements:
            text = getattr(element, "text", None)
            if isinstance(text, str) and text.strip():
                out.append(text)
            content = getattr(element, "content", None)
            if isinstance(content, str) and content.strip():
                out.append(content)
        return out

    @property
    def text(self) -> str:
        return "\n".join(self.texts())

    def buttons(self) -> list[Any]:
        return self.of_type("Button")

    def button_labels(self) -> list[str]:
        return [b.text for b in self.buttons() if getattr(b, "text", "")]

    def ancestors(self, element) -> Iterator[Any]:
        slot = element.parent_slot
        while slot is not None:
            yield slot.parent
            slot = slot.parent.parent_slot

    def is_inside(self, element, *type_names: str) -> bool:
        return any(type(a).__name__ in type_names for a in self.ancestors(element))

    def handlers(self, element) -> list[str]:
        return [listener.type for listener in element._event_listeners.values()]

    def clickable(self, element) -> bool:
        return any(h.split(".")[0] == "click" for h in self.handlers(element))

    def _listeners(self, element, event: str) -> list[Any]:
        found = [
            listener
            for listener in element._event_listeners.values()
            if listener.type.split(".")[0] == event
        ]
        assert found, f"{type(element).__name__} has no {event} handler"
        return found

    def press(self, element) -> None:
        """Fire an element's click handlers as the browser would.

        Calling the page's callback directly is the usual style here and it is
        fine for testing what the callback does. It is not fine for testing
        that a control is *wired to* it — a button rendered with no handler at
        all passes that test. This runs the listeners the element actually
        carries, inside its own client, so the wiring is part of what is
        asserted.
        """
        from nicegui.events import ClickEventArguments, handle_event

        with self.client:
            for listener in self._listeners(element, "click"):
                handle_event(
                    listener.handler,
                    ClickEventArguments(sender=element, client=self.client),
                )

    def fire(self, element, event: str) -> None:
        """`press` for the events that are not clicks — `keydown` for Enter.

        Kept separate rather than folded into `press` because the two hand the
        handler a different arguments object, and a handler that takes the
        event would silently get the wrong shape.
        """
        from nicegui.events import GenericEventArguments, handle_event

        with self.client:
            for listener in self._listeners(element, event):
                handle_event(
                    listener.handler,
                    GenericEventArguments(sender=element, client=self.client, args={}),
                )


@pytest.fixture
def render(no_warehouse, no_vertex) -> Callable[..., Tree]:
    """Render a page function into a throwaway client and return its tree."""
    from nicegui import Client
    from nicegui.page import page

    def _render(build: Callable[..., None], *args, **kwargs) -> Tree:
        client = Client(page("/"), request=None)
        with client:
            build(*args, **kwargs)
        return Tree(client)

    return _render


@pytest.fixture(autouse=True)
def fresh_ui_state():
    """Reset the UI singleton between tests.

    `shell.state` is a module-level object other modules imported by value, so
    it is reset in place rather than replaced — rebinding the name would leave
    every page holding the old one.
    """
    from casefinder.ui.shell import State, state

    saved = dict(state.__dict__)
    state.__dict__.update(State().__dict__)
    yield state
    state.__dict__.update(saved)


@pytest.fixture
def no_warehouse(monkeypatch):
    """Fail loudly if a page test reaches for BigQuery.

    Pulled in by `render` and `warehouse` rather than applied globally, because
    the tests in `test_bq.py` are about the client itself and need the real
    function to patch over.

    Every test that renders a page installs its own fakes. Without this, one
    that forgets would either hang on a network call or quietly pass because
    the page swallowed the exception into an error region.
    """
    from casefinder import bq

    def explode(*args, **kwargs):
        raise AssertionError("a test tried to contact BigQuery")

    monkeypatch.setattr(bq, "get_client", explode)


@pytest.fixture
def no_vertex(monkeypatch):
    """Keep the Ask probe off the network.

    `ask.available()` is honest about what it checks: it sends a real two-token
    prompt, because a model that constructs fine and 404s on first use is worse
    than no Ask tab at all. Settings and the Ask page both call it on render, so
    without this the suite makes a live Vertex call per test and its runtime
    goes from under a second to several.

    The failure is set directly rather than raised from a patched function, so
    the pages exercise the same "Vertex is unavailable" path a user with the API
    switched off would see.
    """
    from casefinder import ask

    monkeypatch.setattr(ask, "_CLIENT", None)
    monkeypatch.setattr(ask, "_MODEL_NAME", None)
    monkeypatch.setattr(ask, "_PROBE_FAILURE", "Vertex AI is not reachable from this test.")


# --------------------------------------------------------------------------
# A warehouse that is not there
# --------------------------------------------------------------------------

NOW = datetime(2026, 8, 12, 9, 30, tzinfo=timezone.utc)


def _page(rows, total=None):
    from casefinder.data import Page

    return Page(
        rows=list(rows),
        bytes_processed=1024,
        cache_hit=False,
        total_matches=total if total is not None else len(rows),
    )


def _triage_row(number: str, **over):
    from casefinder.models import TriageRow

    row = {
        "case_number": number,
        "subject": "Cohort extract request",
        "owner": synthetic.OWNER,
        "status": "Open",
        "pi": synthetic.PI,
        "department": "Medicine",
        "irb": "IRB-1234",
        "funding": "Funded",
        "description": "Requesting an OMOP extract for a retrospective study.",
        "last_activity": NOW - timedelta(days=2),
        "is_closed": False,
        "total_matches": 3,
    }
    row.update(over)
    return TriageRow.from_row(row)


def _header(number="CASE-056576", **over):
    from casefinder.models import CaseHeader

    row = {
        "case_id": "500XX",
        "case_number": number,
        "subject": "Cohort extract request",
        "status": "Open",
        "owner": synthetic.OWNER,
        "pi": synthetic.PI,
        "department": "Medicine",
        "irb": "IRB-1234",
        "funding": "Funded",
        "created_at": NOW - timedelta(days=30),
        "last_activity": NOW - timedelta(days=2),
        "turn_count": 4,
        "description": "Requesting an OMOP extract for a retrospective study.",
    }
    row.update(over)
    return CaseHeader.from_row(row)


class FakeWarehouse:
    """Stands in for `casefinder.data`, and records what was asked of it."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        # The last keyword arguments each method was called with, so a test can
        # ask what the page requested rather than only what it did with the
        # answer — which is the whole question for paging.
        self.kwargs: dict[str, dict[str, Any]] = {}
        self.rows = [_triage_row("CASE-056576"), _triage_row("CASE-056577")]
        # Deliberately larger than `rows`: a list page is a window onto a
        # result, and a fake where the two are equal cannot tell the range line
        # from a plain count.
        self.total = 119
        # Set to an offset past which the fake returns nothing, the way
        # BigQuery answers a page past the end of a result.
        self.stranded_past: int | None = None
        self.header: Any = _header()
        self.comments: list[Any] = []
        self.messages: list[Any] = []
        self.timeline: list[Any] = []
        self.attachments: list[Any] = []
        self.related: list[Any] = []
        self.hits: list[Any] = []
        # Search's equivalent of `total`. Left small enough that the default
        # fake is a result which fits on one page, because most of the search
        # tests are about a result card and not about paging; the paging tests
        # raise it. `stranded_past` is shared with `triage` — no test needs the
        # two to strand at different offsets, and one knob is one less thing to
        # get wrong.
        self.hit_total = 2
        self.stale_days = 2
        # Filled with a default in `install`, where `Facets` is importable. A
        # test that wants empty filter values replaces it afterwards; the stub
        # reads the attribute at call time rather than closing over the value.
        self.facets: Any = None

    def install(self, monkeypatch) -> FakeWarehouse:
        from casefinder import data
        from casefinder.models import Facets, Freshness

        def record(name, value):
            def call(*args, **kwargs):
                self.calls.append(name)
                self.kwargs[name] = kwargs
                return value() if callable(value) else value

            return call

        def paged(name, rows, total):
            """A stub that answers like a warehouse being paged through.

            The generic `record` stub returns the same page whatever it is
            asked for, which cannot distinguish a page that respects the offset
            from one that ignores it — and ignoring it is the bug. This one at
            least answers an offset past the end the way BigQuery does, with no
            rows rather than an error.
            """

            def call(*args, **kwargs):
                self.calls.append(name)
                self.kwargs[name] = kwargs
                offset = kwargs.get("offset", 0)
                if self.stranded_past is not None and offset >= self.stranded_past:
                    return _page([], total())
                return _page(rows(), total())

            return call

        monkeypatch.setattr(data, "check_access", record("access", (True, "Connected")))
        monkeypatch.setattr(
            data,
            "freshness",
            record(
                "freshness",
                # Relative to the real clock, because `age_days` compares
                # against `now()` and the staleness banner is what is under test.
                lambda: Freshness.from_row(
                    {
                        "newest": datetime.now(timezone.utc) - timedelta(days=self.stale_days),
                        "open_cases": 119,
                        "total_cases": 1714,
                    },
                    7,
                ),
            ),
        )
        monkeypatch.setattr(
            data, "triage", paged("triage", lambda: self.rows, lambda: self.total)
        )
        if self.facets is None:
            self.facets = Facets(
                statuses=["Open", "Closed"],
                types=["Data"],
                departments=["Medicine"],
                pis=[synthetic.PI],
                irbs=["IRB-1234"],
            )
        monkeypatch.setattr(data, "facets", record("facets", lambda: self.facets))
        monkeypatch.setattr(
            data, "search", paged("search", lambda: self.hits, lambda: self.hit_total)
        )
        monkeypatch.setattr(data, "corpus_size", record("corpus_size", 1714))
        monkeypatch.setattr(data, "case_header", record("case_header", lambda: self.header))
        monkeypatch.setattr(data, "comments", record("comments", lambda: self.comments))
        monkeypatch.setattr(data, "messages", record("messages", lambda: self.messages))
        monkeypatch.setattr(data, "timeline", record("timeline", lambda: self.timeline))
        monkeypatch.setattr(
            data, "attachments", record("attachments", lambda: self.attachments)
        )
        monkeypatch.setattr(data, "related", record("related", lambda: self.related))
        return self


@pytest.fixture
def warehouse(monkeypatch, no_warehouse) -> FakeWarehouse:
    return FakeWarehouse().install(monkeypatch)
