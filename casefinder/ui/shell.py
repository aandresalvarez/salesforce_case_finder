"""The application shell: theme, navigation rail, and the connection gate.

Two lean rules are enforced here rather than left to each page's discretion,
because a rule that lives in seven files is a rule that drifts:

`primary()` is the only way to make a filled button. Every other action helper
produces outline or text. UX-INV-1 caps a screen at one primary action, and
UX-T1 tests it by counting elements carrying the `cf-primary` marker class — so
a page that wants a second filled button has to reach for something that is
visibly named as the exception.

`layout()` owns the rail. Pages receive a content column and cannot add a
destination, which keeps navigation at the four the spec allows.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from nicegui import context, ui

from .. import config, data
from ..config import ERAS, Era
from ..queries import TriageFilters
from .components import loading

# --------------------------------------------------------------------------
# Visual language — spec section 3.3
# --------------------------------------------------------------------------

ACCENT = "#2563eb"
INK = "#1a1c1f"
MUTED = "#6b7280"
LINE = "#e3e5e9"
SURFACE = "#ffffff"
CANVAS = "#f6f7f9"

_CSS = f"""
:root {{
  --cf-accent: {ACCENT};
  --cf-ink: {INK};
  --cf-muted: {MUTED};
  --cf-line: {LINE};
  --cf-surface: {SURFACE};
  --cf-canvas: {CANVAS};
  /* The scrolling pane's own top padding. A variable rather than a number
     because the sticky table header has to cancel it exactly — see
     `.cf-table thead tr th`. Change it in one place or the header stops
     covering the strip it is supposed to cover. */
  --cf-pad-top: 26px;
}}
body {{
  background: var(--cf-canvas);
  color: var(--cf-ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 14px;
}}
.cf-rail {{
  width: 148px; min-width: 148px;
  background: var(--cf-canvas);
  border-right: 1px solid var(--cf-line);
  height: 100vh; position: sticky; top: 0;
  display: flex; flex-direction: column;
  padding: 14px 0;
}}
.cf-nav {{
  display: flex; align-items: center; gap: 9px;
  /* Every chip is the same rectangle: the rail's width less these margins.
     Without it each one is as wide as its own label — 88px behind `Lists`,
     101px behind `Search`, 109px behind `Settings` — because the rail is a
     `ui.column`, and NiceGUI's own `.nicegui-column` sets `align-items:
     flex-start` on it. Nothing in this file said so, which is why the
     selected item looked like a badge around a word rather than a row in a
     menu, and why the sizes had to be measured to be believed. */
  align-self: stretch;
  padding: 7px 16px; margin: 1px 8px;
  border-radius: 5px; cursor: pointer;
  color: var(--cf-ink); font-size: 13.5px;
  user-select: none;
}}
/* The `:not()` is load-bearing rather than tidy. `.cf-nav:hover` is a class
   and a pseudo-class, so it outranks the single class below it: pointing at
   the destination you are already on replaced its selection colour with the
   hover grey, and the one item whose shading should never change was the only
   one that did. */
.cf-nav:not(.cf-nav-active):hover {{ background: rgba(0,0,0,.045); }}
/* Selection is a subtle background, not a large button — nav rule 5. */
.cf-nav-active {{ background: rgba(37,99,235,.10); color: var(--cf-accent); font-weight: 550; }}
.cf-content {{
  flex: 1; min-width: 0; height: 100vh; overflow-y: auto;
  background: var(--cf-surface); padding: var(--cf-pad-top) 30px 60px 30px;
}}
.cf-reading {{ max-width: 1060px; }}
.cf-h1 {{ font-size: 21px; font-weight: 600; letter-spacing: -.01em; }}
.cf-h2 {{ font-size: 15px; font-weight: 600; }}
.cf-muted {{ color: var(--cf-muted); font-size: 12.5px; }}
.cf-divider {{ border-top: 1px solid var(--cf-line); }}
.cf-row {{ cursor: pointer; }}
.cf-row:hover {{ background: rgba(37,99,235,.045); }}
.cf-casenum {{ color: var(--cf-accent); font-variant-numeric: tabular-nums; font-weight: 550; }}
/* `overflow-wrap:anywhere` on both of these is a correctness fix, not a
   nicety. Case bodies are pasted email: REDCap URLs, and — because the
   requester's form was serialised into the message — unbroken runs of JSON
   with no space in them for hundreds of characters. A run like that is one
   word to the browser, so without this it overflows the column and the tail
   is clipped at the edge of the page. The user is not told; the text is just
   gone. */
.cf-snippet {{
  font-size: 12.5px; color: #374151; line-height: 1.55;
  border-left: 2px solid var(--cf-line); padding-left: 10px;
  overflow-wrap: anywhere;
}}
.cf-body {{
  white-space: pre-wrap; line-height: 1.6; font-size: 13.5px;
  overflow-wrap: anywhere;
}}
.cf-banner {{
  background: #fff8e6; border: 1px solid #f2dfae; color: #6b5312;
  border-radius: 5px; padding: 8px 12px; font-size: 12.5px;
}}
.cf-note {{
  background: #f3f6fb; border: 1px solid #dbe4f2; color: #33456b;
  border-radius: 5px; padding: 8px 12px; font-size: 12.5px;
}}
.cf-error {{
  background: #fdf3f3; border: 1px solid #f0d3d3; color: #8a2c2c;
  border-radius: 5px; padding: 10px 12px; font-size: 12.5px;
  white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, monospace;
}}
.cf-chip {{
  border: 1px solid var(--cf-line); border-radius: 999px;
  padding: 3px 11px; font-size: 12.5px; background: var(--cf-surface);
}}
.cf-mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px; }}
.cf-metric-label {{
  font-size: 11px; color: var(--cf-muted);
  text-transform: uppercase; letter-spacing: .04em;
}}
.cf-metric-value {{ font-size: 13.5px; }}
/* Compact tables — no zebra, 1px dividers, tabular figures. */
/* The header pins to the top of `.cf-content`, and the negative offset is what
   makes it pin to the top the reader can *see*. `top: 0` pins to the top of the
   pane's content box, which is `--cf-pad-top` below the top of the pane itself,
   so it left a 26px strip of open scrollport above the header: rows slid up
   through it in full view, and because a description is clamped to two lines,
   one line of a row would show above the header while its second line showed
   below. That reads as a rendering fault rather than as scrolling. Pulling the
   pin up by exactly the padding closes the strip.

   The padding is still wanted — it is the gap above the first row when the pane
   is scrolled to the top, and the header only rises into it once there is
   something to scroll under. */
/* The rule under the header is a shadow and not the `border-bottom` the cell
   already declares, because `border-collapse: collapse` hands its borders to
   the table to draw: the border stays with the table while the cell floats
   above it, so a pinned header lost its underline and the half-scrolled row
   beneath it was cut off against nothing. A shadow is painted by the cell and
   travels with it. At rest it lands on the same pixel as the border, in the
   same colour, so nothing about the resting header changes. */
.cf-table thead tr th {{
  position: sticky; top: calc(var(--cf-pad-top) * -1);
  z-index: 1; background: var(--cf-surface);
  box-shadow: 0 1px 0 var(--cf-line);
  font-size: 11.5px; text-transform: uppercase; letter-spacing: .04em;
  color: var(--cf-muted); font-weight: 600;
}}
.cf-table td {{ font-size: 13px; }}
"""


def theme() -> None:
    """Install the application stylesheet on this client, once.

    Once matters now that `gated` puts a placeholder on the screen before it
    knows which page it is drawing. The theme has to go in before that
    placeholder or the wait is rendered in Times New Roman on white; the page
    that follows then asks for it again, and without the guard every load
    would carry two copies of the same stylesheet.

    Per client rather than per process: unlike `register_css`, this is the
    client's own head, and `Client` objects do not outlive a page load.
    """
    client = context.client
    if getattr(client, "_cf_themed", False):
        return
    client._cf_themed = True
    ui.add_head_html(f"<style>{_CSS}</style>")
    ui.query("body").style(f"background:{CANVAS}")


_registered_css: set[str] = set()


def register_css(name: str, css: str) -> None:
    """Install a component's stylesheet once, for every client.

    Call this at module scope. Not as a convention — as the only moment that
    works, and this has now been got wrong twice in two different ways.

    `ui.add_head_html` writes into the head of the *current* client, so the
    first attempt — a module-level `_added` flag guarding a call to it — served
    the rules to the first page load in the process and the class names to
    every one after it. That is why list descriptions rendered as full,
    untruncated case bodies: `.cf-truncate` was on the element and its
    `-webkit-line-clamp` was in a stylesheet exactly one page load had ever
    seen. `shared=True` fixes that half, by putting the stylesheet in the head
    served to every client, which is what a component stylesheet is.

    The second way was registering on first draw. That is fine only while every
    draw happens inside the page function, because the head is composed when
    that function returns — and it stopped being true the moment slow content
    moved behind `components/loading.py`. A form drawn from a timer callback
    registers its CSS after the page has been sent, so the browser gets
    `.cf-form` with nothing behind it and the fields render as a plain stack.
    Import time is the only point guaranteed to be before any head is composed.

    `Client.shared_head_html` is a class attribute, so this needs no client and
    is safe to call while the module is being imported. The name is the dedupe
    key, because shared head HTML accumulates.
    """
    if name in _registered_css:
        return
    _registered_css.add(name)
    ui.add_head_html(f"<style>{css}</style>", shared=True)


# --------------------------------------------------------------------------
# Action helpers — the primary-button rule lives here
# --------------------------------------------------------------------------


def primary(label: str, on_click, *, icon: str | None = None) -> ui.button:
    """The one filled action a screen is allowed. See UX-INV-1."""
    return (
        ui.button(label, on_click=on_click, icon=icon)
        .props("unelevated no-caps dense")
        .classes("cf-primary")
        .style(f"background:{ACCENT}; color:white; padding:5px 16px; border-radius:5px")
    )


def secondary(label: str, on_click, *, icon: str | None = None) -> ui.button:
    return (
        ui.button(label, on_click=on_click, icon=icon)
        .props("outline no-caps dense")
        .classes("cf-secondary")
        .style(f"color:{INK}; padding:4px 12px; border-radius:5px")
    )


def quiet(label: str, on_click, *, icon: str | None = None) -> ui.button:
    return (
        ui.button(label, on_click=on_click, icon=icon)
        .props("flat no-caps dense")
        .classes("cf-quiet")
        .style(f"color:{MUTED}; padding:3px 8px")
    )


@contextmanager
def overflow(tooltip: str = "More actions") -> Iterator[None]:
    """The `…` menu. Everything the spec calls secondary lives behind this."""
    with ui.button(icon="more_horiz").props("flat dense round").classes("cf-overflow") as button:
        button.tooltip(tooltip)
        with ui.menu().props("auto-close").classes("text-sm"):
            yield


def muted(text: str) -> ui.label:
    return ui.label(text).classes("cf-muted")


# --------------------------------------------------------------------------
# Session state — spec section 4.5
# --------------------------------------------------------------------------


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

    @property
    def era(self) -> Era:
        return ERAS[self.era_key]


state = State()


# --------------------------------------------------------------------------
# Navigation rail
# --------------------------------------------------------------------------

# At most four primary destinations — nav rule 1. Settings is separate and
# anchored at the bottom; About lives inside it rather than beside it.
#
# Search is first, and `/` is Search rather than Lists — D17. The order here is
# the order in the rail, and the destination whose target is `/` is the one the
# app opens on, so those two facts are one line rather than two places to keep
# in agreement.
#
# Ask is conditional, which is the one place the rail is not a constant. The
# filter runs at import, so a destination is either in the rail for the life of
# the process or absent from it — the rail never changes shape under a reader
# mid-session, which is what nav rule 1 is really protecting.
_ALL_DESTINATIONS = (
    ("search", "Search", "search", "/"),
    ("lists", "Lists", "list_alt", "/lists"),
    ("ask", "Ask", "chat_bubble_outline", "/ask"),
    ("sql", "SQL", "code", "/sql"),
)

DESTINATIONS = tuple(
    item for item in _ALL_DESTINATIONS if item[0] != "ask" or config.ASK_ENABLED
)


def _nav_item(label: str, icon: str, target: str, active: bool) -> None:
    classes = "cf-nav cf-nav-active" if active else "cf-nav"
    with ui.element("div").classes(classes).on("click", lambda: ui.navigate.to(target)):
        ui.icon(icon).style("font-size:16px")
        ui.label(label)


def rail(active: str) -> None:
    with ui.column().classes("cf-rail").style("gap:0"):
        ui.label(config.APP_NAME).style(
            f"font-size:13.5px;font-weight:650;padding:2px 16px 16px 16px;color:{INK}"
        )
        for key, label, icon, target in DESTINATIONS:
            _nav_item(label, icon, target, active == key)
        ui.space()
        _nav_item("Settings", "settings", "/settings", active == "settings")


@contextmanager
def layout(active: str) -> Iterator[None]:
    """Render the shell and yield the content surface.

    Pages get a column to fill. They cannot add a navigation destination, which
    is how "exactly four primary destinations" stays true as pages are added.
    """
    theme()
    with ui.row().classes("w-full").style("gap:0; flex-wrap:nowrap"):
        rail(active)
        with ui.column().classes("cf-content").style("gap:0"):
            yield


# --------------------------------------------------------------------------
# Connection gate — spec FR-START-2
# --------------------------------------------------------------------------


def connection_screen(reason: str) -> None:
    """One centered state with one primary action. No setup dashboard."""

    def retry() -> None:
        data.reset_connection()
        ui.navigate.to("/")

    theme()
    with ui.column().classes("w-full items-center justify-center").style(
        "height:100vh; gap:0; background:" + SURFACE
    ):
        ui.icon("cloud_off").style(f"font-size:38px;color:{MUTED}")
        ui.label("Connect to Google Cloud").classes("cf-h1").style("margin-top:14px")
        ui.label(
            "Case Finder uses the Google Cloud credentials already on this "
            "computer. It has no login of its own."
        ).classes("cf-muted").style("max-width:390px;text-align:center;margin-top:8px")
        with ui.element("div").style("margin-top:18px"):
            primary("Retry", retry)
        with ui.expansion("Setup instructions").classes("cf-muted").style(
            "margin-top:18px; max-width:520px"
        ):
            ui.label("Run this once in a terminal, then press Retry:").classes("cf-muted")
            ui.label("gcloud auth application-default login").classes("cf-mono").style(
                f"background:{CANVAS};padding:7px 10px;border-radius:4px;margin-top:6px"
            )
            ui.label(
                "If that succeeds and this screen still appears, your account is "
                f"signed in but has not been granted BigQuery access to {config.PROJECT}."
            ).classes("cf-muted").style("margin-top:10px")
            ui.label(reason).classes("cf-error").style("margin-top:10px")


def gated(active: str, render) -> None:
    """Run a page behind the access probe.

    Every page uses this, so a revoked credential produces the Connect screen
    wherever the user happens to be rather than a stack trace inside a table.

    The probe is a BigQuery job, and on the first page of a session it is also
    where the client is constructed and the credentials discovered — several
    seconds, before which nothing at all has been drawn, not even the rail. So
    it waits like everything else that waits: `theme` first, because a spinner
    needs the stylesheet as much as a page does, and then the probe off the
    event loop behind a placeholder. It is cached for the process, so only the
    first page of a session pays it and only that one shows this.
    """

    def draw(access: tuple[bool, str]) -> None:
        ok, reason = access
        if not ok:
            connection_screen(reason)
            return
        with layout(active):
            render()

    theme()
    loading.while_loading(
        "Connecting to BigQuery…", data.check_access, draw, on_error=error_region, center=True
    )


def error_region(exc: Exception) -> None:
    """Compact error display with the raw text kept available — spec section 12."""
    with ui.column().classes("w-full").style("gap:6px; margin-top:10px"):
        ui.label(friendly(exc)).classes("cf-h2")
        with ui.expansion("Details").classes("cf-muted"):
            ui.label(f"{type(exc).__name__}: {exc}").classes("cf-error")


def friendly(exc: Exception) -> str:
    """One plain sentence for the top line of an error.

    `ValueError` is passed through verbatim because the read-only guard and the
    query builders raise it with text written for the user; anything else is a
    BigQuery or transport failure whose own message is not.
    """
    from ..bq import CostError, QueryTimeout

    if isinstance(exc, CostError):
        return "That query would scan more data than the safety cap allows."
    if isinstance(exc, QueryTimeout):
        return str(exc)
    if isinstance(exc, ValueError):
        return str(exc)
    return "BigQuery could not run that."
