"""What the window can still do once the program behind it has gone.

The native window is a process of its own — `mp.Process(target=_open_window,
daemon=True)` in NiceGUI's `native_mode.activate` — and it outlives the server
whenever the server does not exit cleanly. Measured, on this machine, with the
real entry point:

* Close the window: the server notices and exits. Clean.
* Close the terminal that launched it: SIGHUP goes to the whole process group,
  both processes go. Clean.
* Kill the server, or let it die of anything: **the window is re-parented to
  PID 1 and stays exactly where it was** — fully drawn, fully dead, every click
  landing on a socket with no other end.

That last state is what `ui/reconnect` puts a notice over, and until now the
notice could only ask the reader to close the window and start again by hand.
It does not have to. The window process is *alive*; only its parent is gone.

pywebview's `js_api` bridge runs from the page into this process directly —
page, WKWebView, window process — and never touches the websocket, so it works
in exactly the situation where nothing else does. That was measured too: a page
whose server had been killed went on calling into an object like this one once
a second, started a replacement Case Finder that outlived the window that
launched it, and shut itself down on request.

The object is put in place by `main._window_args`. That function runs in both
processes, but only the window process's copy is ever reached, because
`_open_window` reads `app.native.window_args` there — nothing here is pickled
and sent, which is what makes a live object work at all.

Nothing in this file goes near the corpus. It starts a process, watches a file
appear, and exits.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# How a restarted Case Finder is told where to report for duty. An environment
# variable because the two processes have nothing else in common: the window
# doing the restarting is not the new server's parent in any useful sense, and
# will be gone by the time anyone asks.
READY_ENV = "CASEFINDER_READY_FILE"

# The same thing `run-mac.sh` runs, minus uv. `sys.executable` in the window
# process is the virtualenv's interpreter, and the package imports from any
# working directory, so this does not depend on where the app was started from.
_LAUNCH = "casefinder.main"


class WindowApi:
    """The methods pywebview exposes to the page as `window.pywebview.api`.

    Everything public here is reachable from JavaScript, so there is nothing
    public here that should not be: three verbs, no arguments, no return value
    that says anything about the machine. `test_window` pins the list.

    Each call arrives on its own thread inside the window process. The state
    below is two attributes written by `restart` and read by `ready`, in that
    order, and a second restart while one is in flight only replaces a handle
    the reader has already stopped waiting on.
    """

    def __init__(self) -> None:
        self._child: subprocess.Popen[bytes] | None = None
        self._token: Path | None = None
        self._arrived = False

    def restart(self) -> str:
        """Start a fresh Case Finder. Returns "started" or "failed".

        Deliberately does not close this window. The new one takes several
        seconds to come up, and closing first would leave the screen empty for
        all of them — which looks precisely like the app vanishing, the thing
        the reader is already worried about. The page waits on `ready` and
        calls `close` itself.
        """
        # An attempt the reader has given up on — one that ran past the page's
        # deadline, say — leaves a directory nobody will look in again.
        # Pressing this button is the moment that becomes true of it.
        self._forget()
        # A private directory rather than a bare name in the temp folder: the
        # file's appearance is a signal that closes a window, and `mkdtemp` is
        # 0700, so no other account on the machine can send it.
        folder = Path(tempfile.mkdtemp(prefix="casefinder-restart-"))
        token = folder / "ready"
        try:
            self._child = subprocess.Popen(
                [sys.executable, "-m", _LAUNCH],
                env={**os.environ, READY_ENV: str(token)},
                # Its own session, so the new Case Finder is not attached to
                # this window's process group and does not inherit its fate.
                start_new_session=True,
                stdin=subprocess.DEVNULL,
            )
        except OSError:
            self._child = None
            _discard(folder)
            return "failed"
        self._token = token
        self._arrived = False
        return "started"

    def ready(self) -> str:
        """Whether the replacement is up: "waiting", "ready" or "gone".

        Reported rather than decided. The page is where the reader is, so the
        page is what gives up, shows the failure and offers the manual advice —
        this process only ever answers the question.
        """
        if self._child is None or self._token is None:
            return "gone"
        if self._arrived or self._token.exists():
            self._arrived = True
            _discard(self._token.parent)
            return "ready"
        if self._child.poll() is not None:
            # Exited without ever serving a page, so there is nothing coming.
            _discard(self._token.parent)
            return "gone"
        return "waiting"

    def close(self) -> str:
        """End this window. Does not return."""
        # Closing while a restart is still in flight is an ordinary thing to
        # do, and `os._exit` runs nothing on the way out, so the tidying is
        # here rather than in an `atexit` that would never fire.
        self._forget()
        _leave()
        return "closing"  # unreachable, and there to say so

    def _forget(self) -> None:
        """Drop a restart nobody is waiting on, and its directory with it."""
        if self._token is not None:
            _discard(self._token.parent)
        self._child = None
        self._token = None
        self._arrived = False


def ready_signal() -> Path | None:
    """Take the handshake path out of the environment, once.

    Popped rather than read because the native window process is spawned from
    this one with a copy of this environment, and a second process promising to
    report the same server twice is a confusing thing to leave lying around.
    """
    path = os.environ.pop(READY_ENV, None)
    return Path(path) if path else None


def announce(token: Path) -> None:
    """Say we are serving. A window somewhere is waiting to close on this."""
    # A window that has given up has already deleted the directory this lives
    # in, and one that was killed never will. Neither is a reason to fail a
    # startup that has otherwise gone fine.
    with contextlib.suppress(OSError):
        token.touch()


def _discard(folder: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)


def _leave() -> None:
    """End the window process, and the window with it.

    `webview.Window.destroy()` is the polite call and it is not enough. It
    dispatches `NSWindow.close` to the main thread and returns; the window goes
    off the screen and this process stays up with nothing to show — measured,
    both with the server alive and with it dead. What that leaves behind is an
    invisible copy of the app per close, which is the accumulation this file
    exists to stop rather than to cause.

    `os._exit` rather than `sys.exit` because the orderly shutdown `sys.exit`
    would begin is a negotiation with a parent process that has died: the
    multiprocessing queues it joins on exit have no reader left. There is
    nothing here worth waiting for. The window process holds no corpus data and
    writes nothing to disk (spec section 9.3), so there is nothing to flush but
    the streams below.
    """
    for stream in (sys.stdout, sys.stderr):
        # The terminal these were opened against may itself be gone.
        with contextlib.suppress(OSError, ValueError):
            stream.flush()
    os._exit(0)
