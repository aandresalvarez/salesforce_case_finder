"""Entry point: routes, then a native window.

Two security properties are set here and nowhere else, so there is one place to
check them (spec section 9.6):

The server binds to 127.0.0.1. A PHI corpus on a laptop must not be reachable
from the network the laptop is on, and NiceGUI's default host would make it so.

There is no on-air / tunnel option in this file. `ui.run(on_air=...)` would
proxy the window through a third-party relay, which is exactly the wrong thing
for this data, so the argument never appears — not even set to False, because a
False that someone can flip is a switch.

`reload=False` matters too: the reloader re-executes the module in a child
process, which would open a second window and a second BigQuery client.
"""

from __future__ import annotations

import socket

from nicegui import app, ui

from . import config
from .ui import ask_page, case_detail, lists, search, settings, sql_page
from .ui.shell import gated

HOST = "127.0.0.1"


@ui.page("/")
def index() -> None:
    # Search, not Lists — D17. The rail's Search entry points here rather than
    # at `/search`, so the landing page and the destination are one page and
    # not two that happen to render the same thing.
    gated("search", search.render)


@ui.page("/search")
def search_page() -> None:
    # Kept because it was the search URL for the whole of v1 and costs one
    # line. Nothing inside the app navigates here.
    gated("search", search.render)


@ui.page("/lists")
def lists_page() -> None:
    gated("lists", lists.render)


@ui.page("/views")
def saved_views() -> None:
    gated("lists", lists.render_saved_views)


@ui.page("/case/{case_number}")
def case_page(case_number: str) -> None:
    gated("lists", lambda: case_detail.render(case_number))


@ui.page("/ask")
def ask_route() -> None:
    # Registered either way, and a redirect rather than a 404, because the
    # route outlives the setting: a bookmark or an old link from a session when
    # Ask was on should land on Search instead of on an error page that makes
    # the app look broken.
    if not config.ASK_ENABLED:
        ui.navigate.to("/")
        return
    gated("ask", ask_page.render)


@ui.page("/sql")
def sql_route() -> None:
    gated("sql", sql_page.render)


@ui.page("/settings")
def settings_route() -> None:
    gated("settings", settings.render)


def _free_port() -> int:
    """Ask the OS for an unused loopback port.

    A fixed port collides with whatever else the user is running and makes the
    app's local URL guessable by anything else on the machine.
    """
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        return int(probe.getsockname()[1])


def main() -> None:
    app.native.window_args["min_size"] = config.MIN_WINDOW_SIZE
    ui.run(
        host=HOST,
        port=_free_port(),
        title=config.APP_NAME,
        native=config.NATIVE,
        reload=False,
        show=not config.NATIVE,
        window_size=config.WINDOW_SIZE,
        favicon="🔎",
        dark=False,
        storage_secret=None,
    )


# NiceGUI's native mode re-imports the module in the webview process, so the
# guard has to accept both spellings.
if __name__ in {"__main__", "__mp_main__"}:
    main()
