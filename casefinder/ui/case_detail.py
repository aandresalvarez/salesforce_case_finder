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

from .. import data
from ..models import (
    Attachment,
    CaseHeader,
    Comment,
    Message,
    TimelineEvent,
    show,
    when,
)
from . import lists, shell
from .components import intake_form, loading
from .components import metadata as metadata_ui
from .components.empty_state import empty, unknown_case
from .components.table import Column, data_table
from .shell import ACCENT, LINE, MUTED, muted, overflow, quiet, state

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
        f"Opening {case_number}…", load, draw, on_error=shell.error_region
    )


def _page(header: CaseHeader) -> None:
    with ui.column().classes("w-full cf-reading").style("gap:0"):
        with ui.row().classes("w-full items-start justify-between").style("gap:16px"):
            with ui.column().style("gap:0; min-width:0"):
                metadata_ui.header_block(header, on_back=ui.navigate.back)
            _actions(header)

        metadata_ui.metric_strip(header.metrics())
        ui.element("div").classes("cf-divider w-full")
        with ui.element("div").style("margin:14px 0 16px 0"):
            metadata_ui.attribute_grid(header.extended())
        ui.element("div").classes("cf-divider w-full")

        _tabs(header)
        _related(header.case_number)


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
TABS = ("Comments", "Messages", "Timeline", "Files")


def _tabs(header: CaseHeader) -> None:
    # Each tab is a load and a draw rather than one function, so the slow half
    # can go off the event loop behind a spinner. Comments is the exception:
    # `render` prefetched it, so building it is a cache hit and a spinner would
    # be a flicker announcing nothing.
    number = header.case_number
    deferred: dict[str, tuple[str, Callable[[], Any], Callable[[Any], None]]] = {
        "Messages": (
            "Loading messages…",
            lambda: data.messages(state.era, number),
            lambda rows: _messages(rows),
        ),
        "Timeline": (
            "Building the timeline…",
            lambda: data.timeline(state.era, number),
            lambda rows: _timeline(rows),
        ),
        "Files": (
            "Looking for files…",
            lambda: data.attachments(state.era, number) if state.era.has_attachments else [],
            lambda rows: _files(rows),
        ),
    }

    def defer(name: str) -> None:
        note, load, draw = deferred[name]
        loading.while_loading(note, load, draw, on_error=shell.error_region)

    builders: dict[str, Callable[[], None]] = {
        "Comments": lambda: comment_stream(header),
        **{name: (lambda n=name: defer(n)) for name in deferred},
    }

    with ui.tabs().props("dense no-caps align=left").classes("w-full").style(
        f"border-bottom:1px solid {LINE}"
    ) as tabs:
        for name in TABS:
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
                shell.error_region(exc)

    # The default tab only. The other three wait for a click.
    build(TABS[0])
    tabs.on_value_change(lambda event: build(event.value))


# --------------------------------------------------------------------------
# Comments — the default tab
# --------------------------------------------------------------------------


@ui.refreshable
def comment_stream(header: CaseHeader) -> None:
    """FR-CASE-5: a flat chronological stream, no expander per entry."""
    metadata_ui.description_block(header.description)

    # Always fetched oldest-first and reversed here. Asking the warehouse for
    # the other order would re-scan the body column for rows already in hand.
    entries = data.comments(state.era, header.case_number)
    if not entries:
        empty("This case has no conversation recorded.", icon="forum")
        return

    if state.comments_newest_first:
        entries = list(reversed(entries))

    with ui.row().classes("w-full items-center justify-between").style(
        "margin-bottom:2px"
    ):
        muted(f"{len(entries):,} entries")
        _order_toggle()

    for entry in entries:
        _comment(entry)


def _order_toggle() -> None:
    def flip() -> None:
        state.comments_newest_first = not state.comments_newest_first
        comment_stream.refresh()

    label = "Newest first" if state.comments_newest_first else "Oldest first"
    ui.label(label).classes("cf-muted").style("cursor:pointer").on(
        "click", flip
    ).tooltip("Reverse the order")


def _comment(entry: Comment) -> None:
    with ui.column().classes("w-full").style(
        f"gap:3px; padding:14px 0; border-bottom:1px solid {LINE}"
    ):
        with ui.row().classes("items-baseline").style("gap:8px; flex-wrap:wrap"):
            ui.label(entry.author).style("font-size:13px; font-weight:600")
            muted(entry.kind)
            muted("·")
            muted(when(entry.ts))
        # Warehouse text that originated in email, and sometimes the intake
        # form serialised into it. `body` picks the reading for the shape it
        # actually has; either way it renders as labels, never as HTML — see
        # the escaping rule in spec section 9.5.
        intake_form.body(entry.body)


# --------------------------------------------------------------------------
# Messages
# --------------------------------------------------------------------------


def _messages(messages: list[Message]) -> None:
    """FR-CASE-7: a compact index; a row expands in place."""
    if not messages:
        empty("No individual messages on this case.", icon="mail_outline")
        return

    muted(f"{len(messages):,} messages · select one to read it")
    for message in messages:
        _message_row(message)


def _message_row(message: Message) -> None:
    with ui.expansion().classes("w-full").props("dense") as panel:
        with panel.add_slot("header"):
            with ui.row().classes("w-full items-baseline").style(
                "gap:10px; flex-wrap:wrap"
            ):
                ui.label(f"#{message.turn_seq}").classes("cf-muted").style(
                    "font-variant-numeric:tabular-nums"
                )
                ui.label(message.who or "Unknown").style(
                    "font-size:13px; font-weight:550"
                )
                muted(_DIRECTIONS.get(message.direction or "", message.direction or ""))
                muted(when(message.ts))
                ui.space()
                muted(f"{message.body_len:,} chars")
        if message.subject:
            ui.label(message.subject).classes("cf-muted").style("margin-bottom:6px")
        intake_form.body(message.body)


# --------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------


def _timeline(events: list[TimelineEvent]) -> None:
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
                    _timeline_row(event)

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


def _timeline_row(event: TimelineEvent) -> None:
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
                ui.label(event.body).classes("cf-body").style("margin-top:4px")


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
    """Shown only when there are matches.

    `related_cases` returns nothing when the case has no PI, IRB, or department
    recorded, so an empty section is the ordinary outcome for a sparsely
    populated case rather than a failure worth reporting.
    """
    try:
        matches = data.related(state.era, case_number)
    except Exception:  # noqa: BLE001
        return
    if not matches:
        return

    ui.label("Related cases").classes("cf-h2").style("margin:26px 0 2px 0")
    muted("Same PI, IRB protocol, or department")
    for match in matches:
        with ui.row().classes("w-full items-baseline cf-row").style(
            f"gap:10px; padding:7px 4px; border-bottom:1px solid {LINE};"
            "flex-wrap:nowrap"
        ).on(
            "click",
            lambda _=None, m=match: ui.navigate.to(f"/case/{m.case_number}"),
            js_handler=shell.CLICK_UNLESS_SELECTING,
        ):
            ui.label(match.case_number).classes("cf-casenum")
            ui.label(match.subject or "(no subject)").style(
                "font-size:13px; min-width:0; overflow:hidden;"
                "text-overflow:ellipsis; white-space:nowrap"
            )
            ui.space()
            muted(match.why)
            muted(show(match.last_activity))


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
