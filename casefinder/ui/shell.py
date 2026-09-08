"""The application shell: the navigation rail, and the gate in front of it.

What is left here once the visual language, the action vocabulary, the session
state and the error region moved to modules of their own. Those four were each
needed by nearly every page and depended on nothing here, so importing the
navigation rail to get a colour was the shape of the problem.

What remains is one job: deciding what surrounds a page.

`layout()` owns the rail. Pages receive a content column and cannot add a
destination, which keeps navigation at the four the spec allows.

`gated()` owns the access probe, so a revoked credential produces the Connect
screen wherever the user happens to be rather than a stack trace inside a
table.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from nicegui import ui

from .. import config, data
from . import theme
from .components import loading
from .components.actions import primary
from .errors import error_region
from .theme import CANVAS, INK, MUTED, SURFACE

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
    theme.install()
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

    theme.install()
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

    theme.install()
    loading.while_loading(
        "Connecting to BigQuery…", data.check_access, draw, on_error=error_region, center=True
    )
