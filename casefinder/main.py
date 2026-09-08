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

from . import cache, config, window
from .ui import (
    ask_page,
    case_detail,
    lists,
    reconnect,
    saved_views,
    search,
    settings,
    sql_page,
)
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
def saved_views_route() -> None:
    gated("lists", saved_views.render)


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


def _window_args() -> dict[str, object]:
    """Arguments for the native window, separated so a test can read them.

    `text_select` is the one that is not self-explanatory. pywebview defaults
    it to False, and what that means is not a greyed-out menu item — it appends
    `body { user-select: none; cursor: default }` to the document *after* the
    page's own head, so no stylesheet in this repository can undo it and no
    browser reproduces it. The whole application was unselectable in the only
    mode anyone runs it in: the way to get a requester's name out of a case was
    Copy summary, which copies the entire case, or retyping it.

    The place to fix it is here rather than in CSS. Being a rule appended late
    to the head, it wins on source order against anything `ui.theme` writes,
    so a stylesheet could only argue with `!important` — and losing that
    argument is silent.

    `js_api` is the other one. It is the only part of the application that
    still works after the server has gone, because pywebview routes it into the
    window process instead of over the websocket — which is why the notice in
    `ui/reconnect` can offer a working Restart rather than instructions. The
    object is constructed here in both processes and used in neither this one
    nor by pickle: `native_mode._open_window` reads `app.native.window_args` in
    the window process, where a live object is what is wanted. See `window`.
    """
    return {
        "min_size": config.MIN_WINDOW_SIZE,
        "text_select": True,
        "js_api": window.WindowApi(),
    }


def main() -> None:
    # Before `ui.run`, because it writes into the head served with every page
    # and the first page is served the moment the server is up. It is also the
    # one part of the application that has to survive the socket going down, so
    # it cannot be something a page sends over that socket — see `ui/reconnect`.
    reconnect.install()
    # Expired entries hold case bodies until something deletes them, and an
    # idle window never asks for anything that would. Started here rather than
    # at import so that neither the tests nor the native window subprocess —
    # both of which import the package — quietly gain a thread.
    cache.start_reaper()
    # Read before the window process is spawned, so that process does not
    # inherit a promise only this one can keep. If we were started by a window
    # whose own server had died, that window is still on screen holding the
    # last thing it drew, waiting for this to say it is serving before it goes.
    token = window.ready_signal()
    if token is not None:
        # `on_connect` and not `on_startup`. Startup is uvicorn binding a
        # socket, which happens 0.55s in — measured — and several seconds
        # before the native window has drawn anything. The old window closes on
        # this signal, so the signal has to mean "there is a page on a screen",
        # and a client connecting is exactly that.
        app.on_connect(lambda: window.announce(token))
    app.native.window_args.update(_window_args())
    # `window_size` is passed only in native mode, and that is not tidiness.
    # NiceGUI reads a window size as a request for a window: `ui_run` sets
    # `native = True` whenever `window_size` is given, whatever the `native`
    # argument says. Passing it unconditionally meant `CASEFINDER_NATIVE=0`
    # still opened the platform webview — so the one documented escape hatch
    # for a machine whose webview is broken led straight back into it, which is
    # the failure it exists to route around. `test_window` pins this.
    sizing = {"window_size": config.WINDOW_SIZE} if config.NATIVE else {}
    ui.run(
        host=HOST,
        port=_free_port(),
        title=config.APP_NAME,
        native=config.NATIVE,
        reload=False,
        show=not config.NATIVE,
        favicon="🔎",
        dark=False,
        storage_secret=None,
        **sizing,
    )


# NiceGUI's native mode re-imports the module in the webview process, so the
# guard has to accept both spellings.
if __name__ in {"__main__", "__mp_main__"}:
    main()
