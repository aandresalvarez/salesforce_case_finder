"""The one part of the app that has to work after the app has stopped working.

Everything here runs in the window process, which is a `daemon=True` child of
the server and outlives it whenever the server does not exit cleanly. That is
not a hypothetical: killing the server leaves the window on screen, drawn and
dead, and six of them accumulated on one machine in an afternoon of testing.

So the asserts are about the two things that make this recoverable rather than
merely explained — that the replacement Case Finder is launched in a way that
outlives the window launching it, and that this window does not go until the
replacement is up — plus the surface the page can reach, which is small on
purpose and is the sort of thing that grows by accident.
"""

from __future__ import annotations

import itertools
import subprocess
import sys
from pathlib import Path

import pytest

from casefinder import window

# --------------------------------------------------------------------------
# What the page is allowed to ask for
# --------------------------------------------------------------------------


def test_the_page_can_only_ask_for_these_three_things():
    """pywebview exposes every public attribute of this object to JavaScript.

    Which makes the public surface a security boundary and not a matter of
    taste: anything added here without `_` becomes callable from the page. The
    list is short enough to read, so it is written down.
    """
    reachable = sorted(name for name in dir(window.WindowApi()) if not name.startswith("_"))

    assert reachable == ["close", "ready", "restart"]


def test_the_window_is_handed_the_bridge_and_not_a_copy_of_one(monkeypatch):
    """`js_api` has to be a live object in the window process to be any use.

    It gets there because `_window_args` runs in both processes and
    `native_mode._open_window` reads `app.native.window_args` in the window
    one — nothing is pickled. A `js_api` that arrived by pickle would be a
    different object talking to a dead server, which is the bug it exists for.
    """
    from casefinder import main

    api = main._window_args()["js_api"]

    assert isinstance(api, window.WindowApi)


# --------------------------------------------------------------------------
# Starting a replacement
# --------------------------------------------------------------------------


class _Fake:
    """Enough of `subprocess.Popen` to answer "is it still going?"."""

    def __init__(self, alive: bool = True) -> None:
        self.returncode = None if alive else 1

    def poll(self):
        return self.returncode


@pytest.fixture
def launches(monkeypatch, tmp_path):
    """Capture the launch instead of performing it.

    `mkdtemp` is redirected as well as `Popen`. A test that leaves handshake
    directories in the machine's own temp folder is doing precisely the thing
    the last few tests in this file exist to stop — sixteen of them turned up
    there before anyone thought to look.
    """
    calls: list[dict] = []
    made = itertools.count()

    def fake_mkdtemp(prefix=""):
        folder = tmp_path / f"{prefix}{next(made)}"
        folder.mkdir(mode=0o700)
        return str(folder)

    monkeypatch.setattr(window.tempfile, "mkdtemp", fake_mkdtemp)

    def fake_popen(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        return _Fake()

    monkeypatch.setattr(window.subprocess, "Popen", fake_popen)
    return calls


def test_the_replacement_is_started_the_same_way_the_first_one_was(launches):
    """This interpreter, this module. Not `run-mac.sh`, which needs uv and a
    working directory, and not a path worked out from `__file__`: the window
    process is already running the right interpreter and the package imports
    from anywhere, so the shortest correct thing is the most portable one.
    """
    assert window.WindowApi().restart() == "started"

    assert launches[0]["argv"] == [sys.executable, "-m", "casefinder.main"]


def test_the_replacement_outlives_the_window_that_starts_it(launches):
    """Its own session, because this window is about to exit.

    Left in this process group the new Case Finder would share the fate of the
    one being replaced — including whatever killed the server in the first
    place, if that was aimed at the group.
    """
    window.WindowApi().restart()

    assert launches[0]["start_new_session"] is True
    assert launches[0]["stdin"] is subprocess.DEVNULL


def test_the_replacement_is_told_where_to_report(launches):
    """The handshake is an environment variable and a file that does not exist.

    It has to be absent at launch: the whole signal is its appearance. A path
    that already existed would read as an instant success and close this window
    before the new one had drawn anything.
    """
    window.WindowApi().restart()

    token = Path(launches[0]["env"][window.READY_ENV])

    assert not token.exists()
    assert token.parent.exists(), "the private directory should be waiting for it"


def test_a_launch_that_cannot_happen_says_so(monkeypatch):
    """And leaves nothing behind. The page turns this into the advice to do it
    by hand, which is the same advice as before this file existed."""

    def refuse(argv, **kwargs):
        raise OSError("no")

    monkeypatch.setattr(window.subprocess, "Popen", refuse)
    api = window.WindowApi()

    assert api.restart() == "failed"
    assert api.ready() == "gone"


# --------------------------------------------------------------------------
# Waiting for it
# --------------------------------------------------------------------------


def test_the_window_stays_until_the_new_one_is_serving(launches):
    """The reason the handshake exists at all.

    Closing on the launch would blank the screen for the several seconds a cold
    start takes — importing the world, opening a BigQuery client — and a screen
    that goes empty after you press Restart looks exactly like the app dying
    again, which is what the reader was already afraid of.
    """
    api = window.WindowApi()
    api.restart()

    assert api.ready() == "waiting"

    Path(launches[0]["env"][window.READY_ENV]).touch()

    assert api.ready() == "ready"


def test_a_replacement_that_dies_is_not_waited_for(monkeypatch):
    """A process that exited without ever serving is never going to serve."""
    monkeypatch.setattr(window.subprocess, "Popen", lambda argv, **kw: _Fake(alive=False))
    api = window.WindowApi()
    api.restart()

    assert api.ready() == "gone"


def test_the_handshake_directory_does_not_outlive_the_handshake(launches):
    """Whichever way it ends. `/tmp` is shared and this runs on someone's laptop."""
    api = window.WindowApi()
    api.restart()
    token = Path(launches[0]["env"][window.READY_ENV])
    token.touch()

    assert api.ready() == "ready"
    assert not token.parent.exists()

    # And the answer does not change once the evidence has been cleaned up.
    assert api.ready() == "ready"


def test_nobody_else_on_the_machine_can_send_the_signal(monkeypatch):
    """The file's appearance closes a window, so who may create it matters.

    `mkdtemp` is 0700. A predictable name composed straight in the shared temp
    folder would let any other account on the machine close this window early —
    a nuisance rather than a disclosure, but a free one to rule out. The real
    `mkdtemp` runs here, so this is the only test in the file that makes a
    directory outside `tmp_path`, and it takes it away again the way the
    application does.
    """
    monkeypatch.setattr(window.subprocess, "Popen", lambda argv, **kw: _Fake())
    api = window.WindowApi()
    api.restart()
    folder = api._token.parent
    try:
        assert folder.stat().st_mode & 0o077 == 0
    finally:
        api._forget()

    assert not folder.exists()


def test_a_restart_still_in_flight_is_cleaned_up_when_the_window_goes(launches, monkeypatch):
    """`close` is `os._exit`, which runs no `atexit` and no `finally`.

    So anything that needs tidying has to be tidied on the way in, and pressing
    Close while a restart is still starting is an entirely ordinary thing to
    do.
    """
    monkeypatch.setattr(window.os, "_exit", lambda code: None)
    api = window.WindowApi()
    api.restart()
    folder = Path(launches[0]["env"][window.READY_ENV]).parent

    assert folder.exists()

    api.close()

    assert not folder.exists()


def test_pressing_restart_twice_does_not_leave_the_first_one_behind(launches):
    """Nobody is waiting on the first attempt any more; the button said so."""
    api = window.WindowApi()
    api.restart()
    first = Path(launches[0]["env"][window.READY_ENV]).parent
    api.restart()

    assert not first.exists()
    assert Path(launches[1]["env"][window.READY_ENV]).parent.exists()


# --------------------------------------------------------------------------
# The two ends of the handshake
# --------------------------------------------------------------------------


def test_a_started_case_finder_reports_for_duty(tmp_path, monkeypatch):
    token = tmp_path / "ready"
    monkeypatch.setenv(window.READY_ENV, str(token))

    signal = window.ready_signal()
    assert signal == token

    window.announce(signal)
    assert token.exists()


def test_the_promise_is_not_inherited_by_the_window_process(monkeypatch):
    """`ready_signal` pops, and `main` calls it before the window is spawned.

    The native window process is spawned with a copy of the server's
    environment. Left in place, it would register a startup hook of its own for
    a server it is not — harmless today, and exactly the kind of thing that
    stops being harmless later.
    """
    monkeypatch.setenv(window.READY_ENV, "/nowhere")

    window.ready_signal()

    assert window.READY_ENV not in window.os.environ
    assert window.ready_signal() is None


def test_reporting_for_duty_never_fails_a_startup(tmp_path):
    """The window that asked may have given up and deleted the directory."""
    window.announce(tmp_path / "gone" / "ready")


# --------------------------------------------------------------------------
# Leaving
# --------------------------------------------------------------------------


def test_closing_ends_the_process_rather_than_just_the_window(monkeypatch):
    """`window.destroy()` is the polite call and it is not enough.

    Measured both ways: it dispatches `NSWindow.close`, the window leaves the
    screen, and the process stays up with nothing to show. What that leaves is
    an invisible copy of the app per close — the accumulation this is supposed
    to end.
    """
    left: list[int] = []
    monkeypatch.setattr(window.os, "_exit", left.append)

    window.WindowApi().close()

    assert left == [0]
