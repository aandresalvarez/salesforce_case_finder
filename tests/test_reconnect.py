"""What the window says when the program behind it goes away.

The report was "the app lost connection with bigquery", and it had not: the
websocket to 127.0.0.1 had gone and BigQuery was never in it. That misreading is
the bug as much as the silence is, so most of what is asserted here is about
words — which connection the notice names, whether it says what to do, whether
the thing it says while waiting is a promise it keeps.

The rest is about the two ways this can be quietly wrong. Probing a page route
instead of a static one would re-run the access check once a second for the
length of an outage, and hiding NiceGUI's own notice from a stylesheet would
leave a reader with nothing at all if the script never attached. Neither shows
up on a screen, and both are one careless edit away.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from casefinder.ui import reconnect

# --------------------------------------------------------------------------
# Saying which connection was lost
# --------------------------------------------------------------------------

READINGS = ("waiting", "stopped")


@pytest.mark.parametrize("reading", READINGS)
def test_the_notice_says_which_connection_this_is(reading):
    """Both readings rule BigQuery out by name.

    The window and the warehouse fail for unrelated reasons and are fixed in
    unrelated ways — `shell.connection_screen` is the other one, and its advice
    is `gcloud auth application-default login`, which would do nothing at all
    for this. A reader given "Connection lost" and left to guess guessed wrong,
    which is the entire reason this file exists.
    """
    words = reconnect._WORDING[reading]

    assert "BigQuery" in words["what"]
    assert "Case Finder" in words["title"] + words["what"]


def test_waiting_promises_the_notice_that_follows_it():
    """"Give it a few seconds" is only honest if something says when to stop.

    socket.io retries forever. Left alone it would say "reconnecting" for the
    rest of the afternoon, which is what it did.
    """
    assert reconnect._WORDING["waiting"]["act"]
    assert reconnect._WORDING["stopped"]["act"]


def test_the_stopped_reading_says_what_to_do_about_it():
    """And the only thing that works, because nothing else does.

    A dead server cannot be reconnected to, and `main._free_port` means the
    next one is not on this port either, so no amount of waiting or reloading
    recovers this window. Closing it and starting again is the whole remedy.
    """
    act = reconnect._WORDING["stopped"]["act"]

    assert "Close this window" in act
    assert "start Case Finder again" in act


def test_a_dead_window_can_still_be_read_from():
    """The scrim dims the page without taking the pointer away from it.

    Someone whose app has just quit very often wants one name out of the case
    still on the screen before they close it — which D19 made possible and a
    modal would take straight back.
    """
    scrim = reconnect._CSS.split("#cf-outage-scrim")[1].split("}")[0]
    card = reconnect._CSS.split("#cf-outage-card {")[1].split("}")[0]

    assert "pointer-events: none" in scrim
    assert "pointer-events: auto" in card
    assert "selected and copied" in reconnect._WORDING["stopped"]["act"]


# --------------------------------------------------------------------------
# Telling a socket worth waiting for from a program that has quit
# --------------------------------------------------------------------------


def test_the_probe_does_not_ask_for_a_page():
    """Every `@ui.page` path runs its page function on the server.

    So probing `location.href` — the obvious thing, and what NiceGUI's own
    `try_reconnect` does — would build a client and re-run the BigQuery access
    check once a second for as long as the outage lasted. The probe asks for a
    static file instead, and this is the test that keeps it that way.
    """
    from nicegui import app

    from casefinder import main  # noqa: F401  (importing registers the routes)

    pages = {getattr(route, "path", None) for route in app.routes}

    assert reconnect.PROBE_PATH not in pages


def test_a_probe_that_is_never_answered_counts_as_a_refusal():
    """A wedged server is the case that reads as a healthy one.

    An exited process refuses the connection and the verdict is immediate. A
    process whose event loop is blocked accepts it and then says nothing, so
    without a deadline on the request the notice would sit at "reconnecting"
    for as long as the wedge lasted — which is the behaviour being replaced.
    """
    ask = reconnect._JS.split("function ask(")[1].split("\n  }")[0]

    assert "AbortController" in ask
    assert "stop.abort()" in ask
    assert "signal: stop.signal" in ask


def test_the_verdict_arrives_in_a_few_seconds():
    """Long enough not to accuse a healthy server, short enough to be an answer.

    One refused request is not evidence of anything. Several seconds of them is,
    and the number below is how long a reader waits before the notice stops
    hedging and tells them to close the window.
    """
    assert reconnect.TUNING["stoppedAfter"] >= 2
    assert reconnect.TUNING["probe"] * reconnect.TUNING["stoppedAfter"] <= 5000


def test_the_notice_opens_sooner_than_the_one_it_replaces():
    """NiceGUI's popup waits 2000ms before fading in — `#popup` in nicegui.css.

    This one is allowed to be quicker because it is about to be useful. It is
    still not instant: a disconnect that heals inside the grace period should
    never have thrown a dialog at somebody mid-sentence.
    """
    assert 500 <= reconnect.TUNING["grace"] < 2000


def test_the_inert_notice_is_only_hidden_once_ours_is_working():
    """`#popup` is taken down by the script, and never by the stylesheet.

    A CSS rule applies whether or not the script that replaces it ever ran, so a
    syntax error in one browser would leave a reader with no notice at all
    rather than the plain one. Hiding it from `attach` makes the fallback
    conditional on the replacement.
    """
    assert "popup" not in reconnect._CSS

    attach = reconnect._JS.split("function attach(")[1].split("\n  }")[0]

    assert 'getElementById("popup")' in attach


# --------------------------------------------------------------------------
# Getting it into the page at all
# --------------------------------------------------------------------------


def test_the_notice_is_built_with_nothing_left_in_it():
    """The script is a template with four holes punched by `str.replace`.

    Rename one and the browser gets `__WORDING__` as a literal, which is a
    syntax error in the one file whose job is to work when nothing else does.
    """
    html = reconnect.head_html()

    assert "__" not in html
    for reading in READINGS:
        assert json.dumps(reconnect._WORDING[reading]["title"])[1:-1] in html


def test_starting_the_app_installs_the_notice(monkeypatch):
    """It has to be in the head the server sends, not in a page.

    A page's own head is composed when its page function returns and reaches the
    browser over the socket. This is the one thing that has to survive that
    socket going down, so it goes in the shared head before anything is served —
    and `main` is where that is arranged, which is what is checked here rather
    than that the function exists.
    """
    from nicegui import Client

    from casefinder import main

    monkeypatch.setattr(reconnect, "_installed", False)
    monkeypatch.setattr(Client, "shared_head_html", "")
    started: list[bool] = []
    monkeypatch.setattr(main.ui, "run", lambda **kwargs: started.append(True))

    main.main()

    assert started
    assert "cf-outage" in Client.shared_head_html


def test_installing_twice_leaves_one_notice(monkeypatch):
    """Shared head HTML accumulates; `register_css` learned this the same way."""
    from nicegui import Client

    monkeypatch.setattr(reconnect, "_installed", False)
    monkeypatch.setattr(Client, "shared_head_html", "")

    reconnect.install()
    reconnect.install()

    assert Client.shared_head_html.count(reconnect.head_html()) == 1


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_script_parses():
    """The one file here that no page test can reach.

    It runs in the browser, outside Vue, at a moment when the connection that
    every other test in this suite depends on is gone.
    """
    script = reconnect.head_html().split("<script>")[1].split("</script>")[0]
    check = subprocess.run(
        ["node", "--check", "-"], input=script, capture_output=True, text=True, check=False
    )

    assert check.returncode == 0, check.stderr
