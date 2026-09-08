"""Session state — spec section 4.5.

What the reader has asked for, held between renders: the search they typed, the
list they are looking at, the era they picked. Nothing here is written to disk
and nothing here is a case row.

Its own module because every page reads it and the shell does not own it. It
outlives any one screen, which is precisely why it should not live inside the
one that happens to draw the navigation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import config, views
from ..config import ERAS, Era
from ..queries import TRIAGE_SORTS, TriageFilters


@dataclass
class SearchState:
    text: str = ""
    in_fields: bool = True
    in_conversation: bool = True
    sort: str = "relevance"
    rows_per_page: int = 25
    # Where in the result the reader is. Reset by anything that changes what
    # the result *is* — see `search._rerun`.
    offset: int = 0
    statuses: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    dismissed_boilerplate: bool = False
    executed: bool = False


@dataclass
class ListState:
    view_name: str = "Open Cases (weekly review)"
    filters: TriageFilters = field(default_factory=TriageFilters)
    sort: str = "last_activity"
    descending: bool = True
    columns: tuple[str, ...] = ()
    # Which page of the result the table is showing. Not persisted in a saved
    # view: a view is a question, and page 4 is not part of one.
    offset: int = 0

    def apply(self, view: views.SavedView) -> None:
        """Adopt a saved view: its filters, its order, its columns.

        A method rather than a helper on the Lists page, because two screens
        open a view — the list's own selector and the Saved Views screen — and
        the second one should not have to import the first to do it.

        The filter lists are copied rather than shared. A view is a definition
        that may be applied again later; editing a filter on screen must not
        rewrite the preset it came from.
        """
        self.view_name = view.name
        self.offset = 0
        self.filters = TriageFilters(
            open_only=view.filters.open_only,
            owners=list(view.filters.owners),
            statuses=list(view.filters.statuses),
            departments=list(view.filters.departments),
            pis=list(view.filters.pis),
            irbs=list(view.filters.irbs),
            funding=list(view.filters.funding),
        )
        # A hand-edited views file can name a sort column that no longer
        # exists, and an unknown key would silently order by nothing.
        self.sort = view.sort if view.sort in TRIAGE_SORTS else "last_activity"
        self.descending = view.descending
        self.columns = view.columns


@dataclass
class State:
    """In-process UI state. Nothing here is written to disk.

    A module-level singleton is correct for this application specifically: it
    is a single-user desktop window bound to loopback, so "the session" and
    "the process" are the same thing. It would be wrong in a hosted app.
    """

    era_key: str = config.DEFAULT_ERA
    search: SearchState = field(default_factory=SearchState)
    lists: ListState = field(default_factory=ListState)
    comments_newest_first: bool = False
    # Full reading or the compact index. What used to be the choice between
    # the Comments tab and the Messages tab, which was never a choice about
    # *what* to read — only about how densely.
    comments_compact: bool = False

    @property
    def era(self) -> Era:
        return ERAS[self.era_key]


state = State()
