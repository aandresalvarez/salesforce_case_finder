"""Case detail — Comments first.

FR-CASE-1 and UX-T4: the page opens on Comments, because that is what support
staff actually read. Individual emails are one tab over, not the default.

Tabs load on first selection, and that is a cost decision rather than a UI
nicety. The conversation table is not clustered on `case_id` (known limitation
1), so every per-case query scans the whole body column: comments ~237 MB,
messages ~256 MB, timeline ~283 MB. NiceGUI builds all four tab panels when the
page renders, so the obvious implementation would run all four queries on open
— ~590 MB, exactly the "legacy four-query path" the spec's cost table calls out.
Building each panel's contents only when its tab is first shown brings opening a
case down to header + comments, which is what NFR-PERF-3 requires.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import ui

from .. import data, intake
from ..models import (
    _MONTHS,
    Attachment,
    CaseHeader,
    Comment,
    RelatedCase,
    TimelineEvent,
    show,
    when,
)
from . import errors, lists, theme
from .components import intake_form, loading
from .components import metadata as metadata_ui
from .components.actions import muted, overflow, quiet
from .components.empty_state import empty, unknown_case
from .components.table import Column, data_table
from .state import state
from .theme import ACCENT, LINE, MUTED

BOX_POLICY = (
    "Attachments are not migrated into Case Finder. Use the Box project folder "
    "for files and documents."
)

# The warehouse stores these lowercase; the UI says what they mean.
_DIRECTIONS = {
    "inbound": "from requester",
    "outbound": "to requester",
    "internal": "internal",
}


def render(case_number: str) -> None:
    case_number = case_number.upper()

    def load() -> CaseHeader | None:
        header = data.case_header(state.era, case_number)
        if header is None:
            return None
        # Only the two the page always draws, and only once the header has
        # proved the case exists — a mistyped case number should not spend a
        # 237 MB scan finding out that it has no comments.
        data.prefetch(
            lambda: data.comments(state.era, case_number),
            lambda: data.related(state.era, case_number),
        )
        return header

    def draw(header: CaseHeader | None) -> None:
        if header is None:
            unknown_case(case_number, state.era.label, lambda: _switch_era(case_number))
            return
        _page(header)

    loading.while_loading(
        f"Opening {case_number}…", load, draw, on_error=errors.error_region
    )


def _page(header: CaseHeader) -> None:
    """Identity above, conversation beside the facts about it.

    The old page was one column in the order the data arrives: title, metrics,
    every attribute, tabs, thread, related cases last. That put roughly five
    hundred pixels of chrome in front of the first thing anyone came to read,
    and left the related cases below a hundred and fifteen entries where
    nobody would ever meet them.

    Two columns instead, split on a single question: what is *in* the case
    goes in the main column, what is *about* the case goes in the rail. The
    rail does not scroll away, so a case's PI, its protocol and its related
    work stay reachable from anywhere in a long thread.
    """
    _identity_bar(header)
    with ui.row().classes("cf-case-cols w-full").style("gap:0"):
        with ui.column().classes("cf-case-main").style("gap:0"):
            _tabs(header)
        with ui.column().classes("cf-case-rail").style("gap:0"):
            _rail(header)


def _identity_bar(header: CaseHeader) -> None:
    """Case number, state and owner, at every scroll position.

    A hundred and fifteen entries is far enough that "which case is this"
    stops being obvious, and the answer used to be at the very top only.
    """
    with ui.row().classes("cf-case-id w-full items-center").style(
        "gap:10px; flex-wrap:wrap"
    ):
        with ui.row().classes("items-center").style("gap:4px; cursor:pointer").on(
            "click", ui.navigate.back
        ):
            ui.icon("arrow_back").style(f"font-size:14px; color:{MUTED}")
            ui.label("Back").classes("cf-muted")
        ui.label(header.case_number).classes("cf-casenum")
        # The only copy of the title on the page. It used to be here *and* as
        # a heading below, which on a wide window put the same sentence twice
        # within eighty pixels of itself. The sticky one wins: it is the one
        # still on screen at entry ninety.
        ui.label(header.subject or "(no subject)").classes("cf-case-id-title").tooltip(
            header.subject or "(no subject)"
        )
        ui.space()
        _state_pills(header)
        _actions(header)


def _state_pills(header: CaseHeader) -> None:
    """The three facts worth carrying everywhere. Everything else is in the rail."""
    age = header.age_days
    # An open case gets a dot. Status is the one of the three that is a state
    # rather than a fact, and a reader scanning between cases should not have
    # to read the word to see it — semantic colour, kept off the accent so it
    # does not compete with the things that are clickable.
    open_case = not (header.closed_at or (header.status or "").lower() == "closed")
    ui.label(header.status or "Status unknown").classes(
        "cf-chip" + (" cf-chip-open" if open_case else "")
    )
    for text in (header.owner, None if age is None else f"{age:,} days"):
        if text:
            ui.label(text).classes("cf-chip")


def _rail(header: CaseHeader) -> None:
    _rail_section("About", lambda: metadata_ui.pairs(header.about()))
    person = _requester(header)
    if person is not None:
        _rail_section("Requester", lambda: metadata_ui.person(person))
    _rail_section("Related", lambda: _related(header.case_number))


def _requester(header: CaseHeader) -> intake.Requester | None:
    """Who filed the case, for the rail.

    Reads the same cached conversation the thread does, so this costs nothing
    beyond the query the page has already made.
    """
    entries = data.comments(state.era, header.case_number)
    submission = _submission(header, entries)
    return intake.requester(submission) if submission else None


def _rail_section(title: str, build) -> None:
    """One titled block of the rail, and a failure that stays inside it.

    Caught so a rail that cannot draw does not take the conversation down with
    it — but reported, not swallowed. An earlier version of this had a `quiet`
    mode for the related-cases block, on the grounds that a case with no
    related work is the ordinary outcome; what it actually did was hide a
    `NameError` in this file behind an empty panel, and the only thing that
    noticed was a test asserting on something else entirely. The empty case is
    `_related`'s to say out loud, and it does.
    """
    with ui.column().classes("cf-rail-sec w-full").style("gap:0"):
        ui.label(title).classes("cf-rail-h")
        try:
            build()
        except Exception as exc:  # noqa: BLE001
            errors.error_region(exc)


def _actions(header: CaseHeader) -> None:
    """Copy summary is secondary — FR-CASE-6. Nothing here is a filled button."""
    with ui.row().classes("items-center").style("gap:2px; flex-wrap:nowrap"):
        quiet("Copy summary", lambda: _copy_summary(header), icon="content_copy")
        with overflow():
            ui.menu_item("Copy case number", on_click=lambda: _copy(header.case_number))
            if header.owner:
                # Not "Search for", which is the free-text search the other two
                # run: an owner is a field with a filter of its own, and a text
                # search for a name would also return every case that merely
                # mentions them in a message.
                ui.menu_item(
                    f"Cases owned by {header.owner}",
                    on_click=lambda: lists.focus_on_owner(header.owner),
                )
            if header.pi:
                ui.menu_item(
                    f"Search for {header.pi}", on_click=lambda: _search_for(header.pi)
                )
            if header.irb:
                ui.menu_item(
                    f"Search for {header.irb}", on_click=lambda: _search_for(header.irb)
                )


# --------------------------------------------------------------------------
# Tabs
# --------------------------------------------------------------------------

# No Overview tab: FR-CASE-1 puts the metadata above the tabs, so an Overview
# would be a tab showing what is already on screen.
# Comments and Messages were the same rows at two densities, which is not two
# tabs' worth of difference — and the second one paid for its own ~256 MB scan
# of the body column to fetch columns the first had already left behind. One
# surface, one query, a density control inside it.
TABS = ("Conversation", "Timeline", "Files")


def _tabs(header: CaseHeader) -> None:
    # Each tab is a load and a draw rather than one function, so the slow half
    # can go off the event loop behind a spinner. Conversation is the
    # exception: `render` prefetched it, so building it is a cache hit and a
    # spinner would be a flicker announcing nothing.
    number = header.case_number
    deferred: dict[str, tuple[str, Callable[[], Any], Callable[[Any], None]]] = {
        "Timeline": (
            "Building the timeline…",
            lambda: data.timeline(state.era, number),
            lambda rows: _timeline(rows, header.intake_echoes()),
        ),
        "Files": (
            "Looking for files…",
            lambda: data.attachments(state.era, number) if state.era.has_attachments else [],
            lambda rows: _files(rows),
        ),
    }

    def defer(name: str) -> None:
        note, load, draw = deferred[name]
        loading.while_loading(note, load, draw, on_error=errors.error_region)

    builders: dict[str, Callable[[], None]] = {
        "Conversation": lambda: comment_stream(header),
        **{name: (lambda n=name: defer(n)) for name in deferred},
    }

    with ui.tabs().props("dense no-caps align=left").classes("w-full").style(
        f"border-bottom:1px solid {LINE}"
    ) as tabs:
        for name in TABS:
            # The count rides on the tab rather than getting a rail section of
            # its own: the metric strip used to carry it, and reinstating it
            # beside a tab that says the same number is how the old page got
            # the way it was.
            if name == "Files" and header.attachments:
                ui.tab(name, label=f"Files · {header.attachments:,}")
            else:
                ui.tab(name)

    panels: dict[str, ui.column] = {}
    with ui.tab_panels(tabs, value=TABS[0]).classes("w-full").style(
        "background:transparent"
    ):
        for name in TABS:
            with ui.tab_panel(name).style("padding:14px 0"):
                panels[name] = ui.column().classes("w-full").style("gap:0")

    built: set[str] = set()

    def build(name: str) -> None:
        if name in built or name not in builders:
            return
        built.add(name)
        with panels[name]:
            try:
                builders[name]()
            except Exception as exc:  # noqa: BLE001
                errors.error_region(exc)

    # The default tab only. The other three wait for a click.
    build(TABS[0])
    tabs.on_value_change(lambda event: build(event.value))


# --------------------------------------------------------------------------
# Comments — the default tab
# --------------------------------------------------------------------------


# How much of a long thread is drawn without asking. The opening says how the
# request arrived and who picked it up; the tail is where the case actually is.
# Everything between them is what a mail thread makes of a conversation —
# mostly each reply quoting every reply before it — and it is the part nobody
# scrolls through, only past.
THREAD_HEAD = 3
THREAD_TAIL = 5

# Below this, the whole thread already fits and a fold is one more control
# saying nothing. Sized so the fold never hides fewer entries than it shows.
FOLD_ABOVE = THREAD_HEAD + THREAD_TAIL + 4


@ui.refreshable
def comment_stream(header: CaseHeader) -> None:
    """FR-CASE-5: one chronological stream, with a way through it.

    Always fetched oldest-first and reversed here. Asking the warehouse for the
    other order would re-scan the body column for rows already in hand.
    """
    shown = header.intake_echoes()
    entries = data.comments(state.era, header.case_number)
    submission = _submission(header, entries)
    if submission is None:
        metadata_ui.description_block(header.description, shown=shown)
    else:
        source = next(
            (e for e in entries if e.body.strip() == submission.raw.strip()), None
        )
        entries = [e for e in entries if e.body.strip() != submission.raw.strip()]
        intake_form.request(submission, byline=_byline(submission, source, header))
    if not entries:
        empty("This case has no conversation recorded.", icon="forum")
        return

    if state.comments_newest_first:
        entries = list(reversed(entries))

    _thread_bar(entries)
    if len(entries) <= FOLD_ABOVE:
        _turns(entries, shown)
        return

    # The two ends, and a count of what is between them. The same shape every
    # mail client settles on for the same reason.
    head, middle, tail = (
        entries[:THREAD_HEAD],
        entries[THREAD_HEAD:-THREAD_TAIL],
        entries[-THREAD_TAIL:],
    )
    _turns(head, shown)
    _fold(middle, shown)
    _turns(tail, shown)


def _byline(
    form: intake.Intake, source: Comment | None, header: CaseHeader
) -> str:
    """Who filed the request and when — the two facts a pinned block loses.

    Lifting the submission out of the thread takes its author and timestamp
    with it, and those are the first things a reader checks against the replies
    below. The requester's own name is used rather than the turn's author,
    because the integration files these under the support alias.
    """
    person = intake.requester(form)
    who = (person.name if person and person.name else None) or (
        source.author if source else ""
    )
    when = (source.ts if source else None) or header.created_at
    return " · ".join(x for x in (who, "web intake", show(when) if when else "") if x)


def _submission(header: CaseHeader, entries: list[Comment]) -> intake.Intake | None:
    """The submitted form, wherever the integration happened to file it.

    Not always the description. On a good many cases the description is pasted
    email and the form arrives as the first turn instead, so a version of this
    that only looked at the description left the request sitting where it had
    always been — as entry one of a hundred and fifteen, which is exactly the
    place it is least use.

    The first thing that parses wins, description first, because that is the
    order they were written in. Reconciled against the page and stripped of the
    requester's own details, both of which are shown better elsewhere.
    """
    for candidate in (header.description, *(entry.body for entry in entries)):
        form = intake.parse(candidate)
        if form is not None:
            return intake.mark_requester(
                intake.reconcile(form, header.intake_echoes())
            )
    return None


def _thread_bar(entries: list[Comment]) -> None:
    people = len({e.author for e in entries})
    with ui.row().classes("w-full items-center").style(
        "gap:10px; margin:18px 0 2px 0; flex-wrap:wrap"
    ):
        muted(
            f"{len(entries):,} entries · {people} "
            f"{'person' if people == 1 else 'people'}"
        )
        ui.space()
        _density_toggle()
        _order_toggle()


def _density_toggle() -> None:
    """What used to be the Messages tab.

    Compact is the same turns with the bodies clamped to a line — an index you
    scan rather than a thread you read. It was a second tab and a second query
    for columns the first query had already gone past.
    """

    def pick(compact: bool) -> None:
        state.comments_compact = compact
        comment_stream.refresh()

    with ui.row().classes("cf-seg").style("gap:0"):
        for compact, label in ((False, "Full"), (True, "Compact")):
            classes = "cf-seg-on" if state.comments_compact == compact else ""
            ui.label(label).classes(classes).on(
                "click", lambda c=compact: pick(c)
            )


def _fold(middle: list[Comment], shown: dict[str, str]) -> None:
    """The replies between the opening and the latest, behind their own count."""
    if not middle:
        return
    holder = ui.column().classes("w-full").style("gap:0")

    def unfold() -> None:
        holder.clear()
        with holder:
            _turns(middle, shown)

    with holder:
        with ui.row().classes("cf-fold w-full items-center").style("gap:8px").on(
            "click", unfold
        ):
            ui.icon("expand_more").style("font-size:16px")
            ui.label(
                f"{len(middle):,} earlier replies"
                + (f" · {_span(middle)}" if _span(middle) else "")
            )


def _span(entries: list[Comment]) -> str:
    stamps = [e.ts for e in entries if e.ts]
    if not stamps:
        return ""
    first, last = show(min(stamps)), show(max(stamps))
    return first if first == last else f"{first} to {last}"


def _turns(entries: list[Comment], shown: dict[str, str]) -> None:
    """Entries under the month they belong to.

    A separator every time the month changes, which on a case that ran from
    April to September is the difference between a scroll position and a date.
    Including the first, which costs one line and means every run carries its
    own date — the tail after a fold says where it resumes rather than
    inheriting a heading from the far side of the gap, and the opening says
    when the case arrived instead of leaving the first month unnamed.
    """
    seen = ""
    for entry in entries:
        month = _month(entry)
        if month != seen:
            seen = month
            with ui.row().classes("cf-monthmark w-full items-center").style("gap:10px"):
                ui.label(month or "Undated")
        _comment(entry, shown)


def _month(entry: Comment) -> str:
    return f"{_MONTHS[entry.ts.month - 1]} {entry.ts.year}" if entry.ts else ""


def _order_toggle() -> None:
    def flip() -> None:
        state.comments_newest_first = not state.comments_newest_first
        comment_stream.refresh()

    label = "Newest first" if state.comments_newest_first else "Oldest first"
    ui.label(label).classes("cf-muted").style("cursor:pointer").on(
        "click", flip
    ).tooltip("Reverse the order")


def _one_line(entry: Comment) -> str:
    """A turn as a single line, for the compact reading."""
    if intake.parse(entry.body):
        return "The submitted request form"
    return entry.subject or entry.body or "(empty)"


def _comment(entry: Comment, shown: dict[str, str] | None = None) -> None:
    with ui.column().classes("w-full cf-turn").style(
        f"gap:3px; padding:14px 0; border-bottom:1px solid {LINE}"
    ):
        with ui.row().classes("items-baseline").style("gap:8px; flex-wrap:wrap"):
            ui.label(entry.author).style("font-size:13px; font-weight:600")
            muted(entry.kind)
            muted("·")
            muted(when(entry.ts))
            if state.comments_compact and entry.body_len:
                ui.space()
                muted(f"{entry.body_len:,} chars")
        if state.comments_compact:
            # The index reading: one line each, subject first where there is
            # one, so a long thread can be scanned rather than read.
            ui.label(_one_line(entry)).classes("cf-turn-line")
            return
        # A subject titles a message. It does not title a serialised form —
        # the integration files those under names like `base64_encoded`, and
        # printing that above a parsed request is worse than printing nothing.
        if entry.subject and not intake.parse(entry.body):
            ui.label(entry.subject).classes("cf-muted")
        # Warehouse text that originated in email, and sometimes the intake
        # form serialised into it. `body` picks the reading for the shape it
        # actually has; either way it renders as labels, never as HTML — see
        # the escaping rule in spec section 9.5.
        intake_form.body(entry.body, shown=shown)


# --------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------


def _timeline(events: list[TimelineEvent], shown: dict[str, str] | None = None) -> None:
    """FR-CASE-8: conversation and audit interleaved, in one ordered list."""
    if not state.era.has_history:
        with ui.row().classes("cf-note w-full").style("margin-bottom:12px"):
            ui.label(
                "The audit trail was not retained for this era, so the timeline "
                "shows conversation events only."
            )

    if not events:
        empty("Nothing recorded on this case.", icon="timeline")
        return

    kinds = sorted({event.kind for event in events})
    chosen = {"kind": "All events"}
    rows = ui.column().classes("w-full").style("gap:0")

    def redraw() -> None:
        rows.clear()
        with rows:
            for event in events:
                if chosen["kind"] in ("All events", event.kind):
                    _timeline_row(event, shown)

    def pick(value: str) -> None:
        chosen["kind"] = value
        redraw()

    if len(kinds) > 1:
        ui.select(
            ["All events", *kinds],
            value="All events",
            on_change=lambda e: pick(e.value),
        ).props("dense borderless options-dense").style(
            f"font-size:12.5px; color:{MUTED}; margin-bottom:6px"
        )

    redraw()


def _timeline_row(event: TimelineEvent, shown: dict[str, str] | None = None) -> None:
    colour = ACCENT if event.is_message else MUTED
    with ui.row().classes("w-full").style("gap:12px; padding:9px 0; flex-wrap:nowrap"):
        ui.element("div").style(
            f"width:7px;height:7px;border-radius:50%;background:{colour};"
            "margin-top:6px;flex:none"
        )
        with ui.column().style("gap:1px; min-width:0"):
            with ui.row().classes("items-baseline").style("gap:8px; flex-wrap:wrap"):
                ui.label(event.what or event.kind).style(
                    "font-size:13px; font-weight:550"
                )
                if event.who:
                    muted(event.who)
                muted(when(event.ts))
            if event.detail:
                muted(event.detail)
            if event.body:
                # Through the same reader as everything else. This tab used to
                # print the serialised intake payload verbatim — the whole
                # form, as one unbroken line of JSON, as the most prominent
                # thing on the screen.
                intake_form.body(event.body, shown=shown).style("margin-top:4px")


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------


def _files(files: list[Attachment]) -> None:
    """FR-CASE-9: a table and one policy banner. No upload, preview, or delete."""
    with ui.row().classes("cf-note w-full items-center").style(
        "gap:8px; margin-bottom:12px"
    ):
        ui.icon("folder_shared").style("font-size:15px")
        ui.label(BOX_POLICY)

    if not state.era.has_attachments:
        muted("Attachment records were not retained for this era.")
        return

    if not files:
        muted("No files recorded on this case.")
        return

    data_table(
        [
            Column("file_name", "File", lambda a: a.file_name or "—", sortable=False),
            Column(
                "size",
                "Size",
                lambda a: a.size,
                width="110px",
                sortable=False,
                numeric=True,
            ),
            Column(
                "gcs_uri",
                "Pointer",
                lambda a: a.gcs_uri or "—",
                sortable=False,
                drop=1,
            ),
        ],
        files,
        on_row_click=lambda a: _copy_pointer(a.gcs_uri),
    )
    muted("Selecting a row copies its storage pointer.").style("margin-top:8px")


def _copy_pointer(uri: str | None) -> None:
    if not uri:
        return
    _copy(uri)
    ui.notify("Storage pointer copied", type="positive")


# --------------------------------------------------------------------------
# Related cases — FR-CASE-10
# --------------------------------------------------------------------------


def _related(case_number: str) -> None:
    """FR-CASE-10, grouped by how strong the relationship is.

    Twenty-three related cases ranked by recency is a list nobody reads: the
    two sharing this case's IRB protocol — the two actually about the same
    study — sat below ten that merely share a department, with the reason
    printed at the end of each row rather than being the thing that ordered it.

    So the reason becomes the structure. The strongest group is open, the
    weakest collapsed, and the counts are legible without expanding anything —
    which is most of what a reader wants from this panel in the first place.
    """
    matches = data.related(state.era, case_number)
    if not matches:
        muted("No other case shares this one's PI, protocol or department.")
        return

    for key, title in RelatedCase.STRENGTHS:
        group = [m for m in matches if m.strength == key]
        if not group:
            continue
        # Only the strongest group opens by default. A department in this
        # corpus can run to dozens of cases, and a panel that opens all of
        # them is the scroll this rail exists to end.
        with ui.expansion(f"{title} · {len(group)}", value=key == "irb").props(
            "dense"
        ).classes("cf-rel-group w-full"):
            for match in group:
                _related_row(match)


def _related_row(match: RelatedCase) -> None:
    with ui.column().classes("w-full cf-row cf-rel-row").style("gap:1px").on(
        "click",
        lambda _=None, m=match: ui.navigate.to(f"/case/{m.case_number}"),
        js_handler=theme.CLICK_UNLESS_SELECTING,
    ):
        with ui.row().classes("items-baseline w-full").style("gap:7px; flex-wrap:nowrap"):
            ui.label(match.case_number).classes("cf-casenum").style("flex:none")
            muted(show(match.last_activity)).style("margin-left:auto; flex:none")
        # The subject on its own line: a 280px rail has no room for a title
        # beside an identifier, and the title is the half that says what the
        # case is.
        ui.label(match.subject or "(no subject)").classes("cf-rel-subject")


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------


def _copy_summary(header: CaseHeader) -> None:
    """The handoff format from FR-CASE-6 / SR-9.

    Support staff paste this into ServiceNow and email. It is a clipboard write
    only — nothing reaches disk, so the PHI in the recent comments stays in the
    user's own paste buffer.
    """
    try:
        recent = data.comments(state.era, header.case_number)[-3:]
    except Exception:  # noqa: BLE001
        recent = []

    lines = [
        f"{header.case_number} | Status: {show(header.status)} "
        f"| PI: {show(header.pi)} | Dept: {show(header.department)} "
        f"| IRB: {show(header.irb)} | Funded: {show(header.funding)}",
        f"Opened: {show(header.created_at)} "
        f"| Last activity: {show(header.last_activity)}",
    ]
    if header.description:
        lines.append(f"Description: {header.description}")
    if recent:
        lines.append("Recent comments:")
        lines.extend(
            f"  [{when(entry.ts)} · {entry.author}] {entry.body}" for entry in recent
        )

    _copy("\n".join(lines))
    ui.notify("Case summary copied", type="positive")


def _copy(text: str) -> None:
    ui.clipboard.write(text)


def _search_for(term: str | None) -> None:
    if not term:
        return
    state.search.text = f'"{term}"'
    state.search.executed = True
    state.search.dismissed_boilerplate = False
    ui.navigate.to("/")


def _switch_era(case_number: str) -> None:
    state.era_key = "archive" if state.era_key == "current" else "current"
    ui.navigate.to(f"/case/{case_number}")
