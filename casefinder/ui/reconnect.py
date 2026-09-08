"""What the window says when it loses the program behind it.

There are two connections in this application and they fail in completely
different ways. `shell.connection_screen` is the other one: Case Finder to
BigQuery, a credential or a permission problem, recoverable with Retry. This
file is the near one — the browser window to the local server that draws it —
and the distinction matters because a user watching a window go dead has no way
to tell them apart. The report that prompted this said "the app lost connection
with bigquery"; it had not. The websocket to 127.0.0.1 had gone, BigQuery was
never involved, and the notice on the screen said only "Connection lost."

That notice is NiceGUI's, `#popup` in its page template: two fixed strings in
the bottom-left corner, `pointer-events: none`, no elapsed time, no attempt
count, no advice, nothing to press. It is accurate and it is inert. Everything
below replaces it.

What is actually true underneath, because the advice has to match it:

* socket.io reconnects on its own, indefinitely, backing off to one attempt
  every five seconds. So a blip genuinely does heal without help, and saying
  "wait" is honest — as long as there is a server to heal towards.
* NiceGUI keeps a disconnected client for `reconnect_timeout` (3s by default)
  and then deletes its element tree. Reconnecting after that fails the
  handshake, and `nicegui.js` reloads the page. Also fine: page state lives in
  `ui/state.py`'s singleton, which is process-global, so the reload lands back where it was.
* If the server process is gone, none of that can ever succeed. In native mode
  the window is a `daemon=True` child of the server process, and a daemon child
  only dies with a parent that exits cleanly — kill the server and the window is
  orphaned, still on screen, still rendering the last thing it drew. And
  `main._free_port` picks a new port every launch, so the next Case Finder is
  not somewhere this window can find. Retrying forever is the wrong thing to
  promise here: this window is never coming back.

Distinguishing the healable case from the hopeless one is the whole job, and it
takes one HTTP request: ask the server for a static file. If it answers, the
socket is coming back and the right advice is to wait. If it refuses — which
loopback does instantly — or accepts and then goes on saying nothing, the
program is not going to serve this window again.

That used to be the end of it, and the notice could only tell the reader to
close the window and start Case Finder by hand. It does not have to: the window
process is alive even when the server is not, and pywebview's `js_api` reaches
it without going near the socket. So the hopeless reading gets two buttons that
work — Restart Case Finder and Close window — and the notice waits for the
replacement to say it is serving before it lets this window go, rather than
leaving the screen empty for the length of a cold start. `casefinder/window`
is the other half of that, and a browser, which has no second process, still
gets the sentence telling it what to do by hand.

The notice is deliberately not a modal that swallows the page. The scrim is
`pointer-events: none` and the card can be dismissed to a corner pill, because
the most likely thing someone wants from a dead window is to copy a name out of
the case still sitting behind it (D19) before they close it.
"""

from __future__ import annotations

import json

from nicegui import ui

# Milliseconds, and all three are compromises worth naming.
#
# `grace` is how long a disconnect has to last before it is worth mentioning.
# Long enough that a blink does not throw a dialog at someone mid-sentence,
# short enough that the window is never mysteriously dead. NiceGUI's own popup
# waits 2000ms; this is faster because it is about to say something useful.
#
# `probe` is how often the server is asked whether it is still there. It is one
# HEAD request to a static file on loopback, so once a second costs nothing and
# only runs while the socket is already down.
#
# `stopped_after` is how many consecutive refused probes are needed before the
# wording changes from "reconnecting" to "stopped". More than one, because a
# single failed request is not evidence of anything, and telling somebody their
# app has quit when it has not is worse than a second of hedging.
#
# `startWait` is how long a restart is given to produce a running Case Finder
# before the notice stops promising one. Much longer than the rest, because a
# cold start imports the world and opens a BigQuery client, and because the
# alternative to waiting is telling someone their app cannot be restarted while
# it is in the middle of starting.
TUNING = {"grace": 1200, "probe": 1000, "stoppedAfter": 3, "startWait": 40000}

# The path the probe asks for. A static route rather than a page route, and that
# is not an optimisation: every `@ui.page` path runs its page function on the
# server, so probing one would build a fresh client and re-run the BigQuery
# access check once a second for the length of the outage. NiceGUI registers
# this one unconditionally at startup and it touches nothing.
PROBE_PATH = "/favicon.ico"

# Base rules first, then the state rules together at the bottom. Not only taste:
# every state rule reuses a selector from the block above it, so interleaving
# them puts a `display: none` in front of the rule that says what the thing
# looks like — and leaves a reader of this file two places to look for one
# element.
_CSS = """
#cf-outage { display: none; }
/* The scrim dims the page to say it is not listening, and passes every click
   and drag straight through to it anyway, so the case underneath can still be
   read from and copied out of. Only the card takes the pointer back. */
#cf-outage-scrim {
  position: fixed; inset: 0; z-index: 10001; pointer-events: none;
  background: rgba(246, 247, 249, .62);
}
#cf-outage-card {
  position: fixed; z-index: 10002; top: 16vh; left: 50%; transform: translateX(-50%);
  box-sizing: border-box; width: min(530px, calc(100vw - 48px));
  pointer-events: auto;
  background: var(--cf-surface, #ffffff);
  border: 1px solid var(--cf-line, #e3e5e9); border-radius: 8px;
  box-shadow: 0 10px 34px rgba(0, 0, 0, .14);
  padding: 19px 21px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
#cf-outage-title {
  margin: 0; font-size: 15px; font-weight: 600;
  color: var(--cf-ink, #1a1c1f);
}
#cf-outage-card p {
  margin: 9px 0 0 0; font-size: 12.5px; line-height: 1.55;
  color: var(--cf-muted, #6b7280);
}
#cf-outage-do { color: var(--cf-ink, #1a1c1f) !important; }
#cf-outage-do:empty { display: none; }
/* Wrapping rather than squeezing. Flex items shrink before they overflow, and
   the first thing a shrinking row does to "Restart Case Finder" is break it
   across two lines inside its own button, which reads as a mistake. Nothing in
   here shrinks; if the row runs out of space it moves down instead. */
#cf-outage-foot {
  display: flex; flex-wrap: wrap; align-items: center; gap: 9px; margin-top: 17px;
}
#cf-outage-clock {
  font-size: 11.5px; color: var(--cf-muted, #6b7280);
  font-variant-numeric: tabular-nums; white-space: nowrap; flex: none;
}
#cf-outage-spin {
  width: 12px; height: 12px; border-radius: 50%; flex: none;
  border: 2px solid var(--cf-line, #e3e5e9);
  border-top-color: var(--cf-accent, #2563eb);
  animation: cf-outage-turn 900ms linear infinite;
}
#cf-outage button {
  font: inherit; font-size: 12.5px; cursor: pointer; border-radius: 5px;
  padding: 4px 12px; background: var(--cf-surface, #ffffff);
  border: 1px solid var(--cf-line, #e3e5e9); color: var(--cf-ink, #1a1c1f);
  white-space: nowrap; flex: none;
}
#cf-outage button:hover { background: rgba(0, 0, 0, .045); }
/* Repeating the id after the type is not a tic: `#cf-outage button` is an id
   and a type, so a bare `#cf-outage-quiet` loses to it and Dismiss came out
   looking exactly as much of an offer as Reload. */
#cf-outage button#cf-outage-quiet {
  border-color: transparent; color: var(--cf-muted, #6b7280);
}
/* The one thing on a dead page that still does something, so it is the one
   thing that looks like it does. Same specificity trick as above, and it has
   to beat `#cf-outage button:hover` as well, which is why the hover feedback
   is a filter rather than another background. */
#cf-outage button#cf-outage-restart {
  background: var(--cf-accent, #2563eb); border-color: var(--cf-accent, #2563eb);
  color: #ffffff;
}
#cf-outage button#cf-outage-restart:hover { filter: brightness(1.08); }
/* Hidden until something has answered for them — see the bridge rules below. */
#cf-outage-restart, #cf-outage-quit { display: none; }
/* The far corner from the rail. NiceGUI put its notice bottom-left, which is
   where `Settings` is, and a reminder that the app is dead sitting on top of a
   destination is a worse thing to leave behind than one in empty space. */
#cf-outage-pill {
  position: fixed; z-index: 10002; bottom: 16px; right: 16px;
  pointer-events: auto; box-shadow: 0 2px 10px rgba(0, 0, 0, .12);
}
@keyframes cf-outage-turn { to { transform: rotate(360deg); } }

/* Reload is only ever an offer while there is something to reload towards. A
   reload against a server that is not there replaces this notice with WebKit's
   own blank failure page, which explains less than it does. */
#cf-outage:not([data-state="waiting"]) #cf-outage-reload { display: none; }
/* Nothing spins once there is nothing left to wait for. Starting is the
   exception: something is happening, and it takes long enough to need saying. */
#cf-outage[data-state="stopped"] #cf-outage-spin,
#cf-outage[data-state="unstartable"] #cf-outage-spin { display: none; }
/* The two buttons that need a live window process behind them. `data-bridge`
   is set only where `window.pywebview` actually answered, so a browser — where
   there is no second process and nothing to restart from here — falls back to
   the sentence that says to do it by hand. Doing this the other way round,
   showing the buttons and finding out on click, would put a dead button on the
   one screen whose whole purpose is that its buttons work. */
#cf-outage[data-bridge="1"][data-state="stopped"] #cf-outage-restart,
#cf-outage[data-bridge="1"][data-state="stopped"] #cf-outage-quit,
#cf-outage[data-bridge="1"][data-state="unstartable"] #cf-outage-restart,
#cf-outage[data-bridge="1"][data-state="unstartable"] #cf-outage-quit {
  display: inline-block;
}
/* Starting: nothing to press, because the next thing to happen is this window
   closing, and dismissing a notice that is about to take the page with it is
   an offer of something that is not true. */
#cf-outage[data-state="starting"] #cf-outage-quiet { display: none; }
/* Dismissed: the card gets out of the way of the text it is covering and
   leaves the pill behind, which puts it back. */
#cf-outage[data-dismissed="1"] #cf-outage-scrim,
#cf-outage[data-dismissed="1"] #cf-outage-card { display: none; }
#cf-outage:not([data-dismissed="1"]) #cf-outage-pill { display: none; }
#cf-outage[data-open="1"] { display: block; }
"""

# The markup is a fixed string with no interpolation anywhere in it. Section 9.5
# forbids putting body values through HTML, and the way to keep that easy to
# check is for the one hand-written `innerHTML` in the application to have no
# hole in it that a value could reach.
_MARKUP = """
<div id="cf-outage" data-state="waiting" aria-live="polite">
  <div id="cf-outage-scrim"></div>
  <div id="cf-outage-card" role="alertdialog" aria-labelledby="cf-outage-title">
    <h2 id="cf-outage-title"></h2>
    <p id="cf-outage-what"></p>
    <p id="cf-outage-do"></p>
    <div id="cf-outage-foot">
      <div id="cf-outage-spin"></div>
      <span id="cf-outage-clock"></span>
      <span style="flex:1"></span>
      <button type="button" id="cf-outage-quit">Close window</button>
      <button type="button" id="cf-outage-restart">Restart Case Finder</button>
      <button type="button" id="cf-outage-reload">Reload</button>
      <button type="button" id="cf-outage-quiet">Dismiss</button>
    </div>
  </div>
  <button type="button" id="cf-outage-pill"></button>
</div>
"""

# Every reading, in the words a person would use about their own machine.
#
# The first two are diagnoses — what the probe found — and the first sentence of
# each says which connection this is, because the one thing the original notice
# got wrong was letting the reader guess. The second two are outcomes of
# something the reader pressed, so they report rather than diagnose.
_WORDING = {
    "waiting": {
        "title": "Reconnecting to Case Finder",
        "what": (
            "This window lost its link to the Case Finder program running on "
            "your computer. It is not a BigQuery problem, and nothing you were "
            "looking at has been lost."
        ),
        "act": "Give it a few seconds. If it does not come back, this notice will say so.",
        "pill": "Reconnecting…",
    },
    "stopped": {
        # "stopped responding" rather than "quit", because the probe cannot tell
        # a process that has exited from one that is wedged and never answers,
        # and the remedy is the same for both.
        "title": "Case Finder has stopped responding",
        "what": (
            "The window is still here, but the program behind it is no longer "
            "answering, so nothing on this screen will do anything. This is "
            "not a BigQuery problem. Case Finder saves nothing to this "
            "computer, so there is nothing here to lose."
        ),
        "act": (
            "Close this window and start Case Finder again. Anything on the "
            "page behind this can still be selected and copied first."
        ),
        # What the same situation looks like when there is something that can
        # be pressed about it. Only the desktop window has the bridge that
        # makes those buttons work, so only the desktop window is promised
        # them; `act` above is what a browser is told, and it is still true.
        "actNative": (
            "Restart Case Finder below, or close the window. Anything on the "
            "page behind this can still be selected and copied first."
        ),
        "pill": "Case Finder is not responding",
    },
    "starting": {
        "title": "Starting Case Finder",
        "what": (
            "A new copy of Case Finder is opening. It takes a few seconds. "
            "This window stays where it is until the new one is ready, so "
            "nothing on the screen goes away before there is something to "
            "replace it."
        ),
        "act": "",
        "pill": "Starting Case Finder…",
    },
    "unstartable": {
        # Reached three ways: the launch itself failed, the new copy exited
        # before it served anything, or it took longer than `startWait`. The
        # wording covers all three because this window cannot tell them apart —
        # the program that would have explained is the one that is gone.
        "title": "Case Finder could not be restarted from here",
        "what": (
            "The new copy did not start. This window has no way to find out "
            "why, and nothing has been lost either way: Case Finder saves "
            "nothing to this computer."
        ),
        "act": (
            "Close this window and start Case Finder the way you normally do. "
            "Anything on the page behind this can still be selected and "
            "copied first."
        ),
        "pill": "Case Finder is not responding",
    },
}

_JS = """
(function () {
  "use strict";

  var TUNING = __TUNING__;
  var PROBE_PATH = __PROBE_PATH__;
  var WORDING = __WORDING__;

  var node = null;      // the notice, built the first time one is needed
  var since = 0;        // when the socket went, ms, or 0 when all is well
  var attempts = 0;     // socket.io's own retry count
  var refused = 0;      // consecutive probes the server did not answer
  var shown = "";       // which reading is on the screen
  var forced = "";      // a reading the reader caused, which outranks the probe
  var bridge = null;    // window.pywebview.api, in the desktop window only
  var clock = null;
  var probe = null;
  var appear = null;
  var watch = null;     // the poll waiting for a restarted Case Finder
  var began = 0;        // when Restart was pressed, ms

  // What to say. The probe decides between the two diagnoses — the server not
  // answering a plain HTTP request is the whole difference between a socket
  // worth waiting for and a program that has quit — but once the reader has
  // pressed Restart, what happened to that is the more useful news.
  function reading() {
    if (forced) return forced;
    return refused >= TUNING.stoppedAfter ? "stopped" : "waiting";
  }

  // The bridge is pywebview's, and it is the only thing on this page that
  // still reaches running code once the server has gone: it goes to the
  // process drawing this window, not down the socket. `pywebviewready` is its
  // own event and may have fired long before this notice was needed, so the
  // check runs on the event and again whenever the notice is built.
  function findBridge() {
    if (!bridge) {
      if (!window.pywebview || !window.pywebview.api) return;
      if (typeof window.pywebview.api.restart !== "function") return;
      bridge = window.pywebview.api;
    }
    if (!node) return;
    node.dataset.bridge = "1";
    // The advice on screen was written for a reader without buttons. Repaint,
    // in case the bridge turned up after the notice did.
    shown = "";
    paint();
  }

  function build() {
    var host = document.createElement("div");
    host.innerHTML = __MARKUP__;
    node = host.firstElementChild;
    document.body.appendChild(node);
    node.querySelector("#cf-outage-reload").onclick = function () {
      window.location.reload();
    };
    node.querySelector("#cf-outage-quiet").onclick = function () {
      node.dataset.dismissed = "1";
    };
    node.querySelector("#cf-outage-pill").onclick = function () {
      delete node.dataset.dismissed;
    };
    node.querySelector("#cf-outage-restart").onclick = restart;
    node.querySelector("#cf-outage-quit").onclick = function () {
      if (bridge) bridge.close();
    };
    findBridge();
  }

  // Restarting is two steps, and the second one is the point of it. Closing
  // this window first would leave the screen empty for the several seconds a
  // cold start takes, which is indistinguishable from the app disappearing —
  // the thing the reader is already worried about. So: start one, watch for it
  // to say it is serving, and only then go.
  function restart() {
    if (!bridge) return;
    clearInterval(probe);
    began = Date.now();
    forced = "starting";
    paint();
    bridge.restart().then(function (answer) {
      if (answer !== "started") { lost(); return; }
      var until = Date.now() + TUNING.startWait;
      watch = setInterval(function () {
        if (Date.now() > until) { lost(); return; }
        bridge.ready().then(function (state) {
          if (state === "ready") { clearInterval(watch); bridge.close(); }
          else if (state === "gone") { lost(); }
        }, lost);
      }, TUNING.probe);
    }, lost);
  }

  function lost() {
    clearInterval(watch);
    forced = "unstartable";
    paint();
  }

  // The clock is the part that answers "is anything happening?". A number that
  // moves is the difference between waiting and wondering, and wondering was
  // the complaint.
  function paint() {
    if (!node || !since) return;
    var next = reading();
    if (next !== shown) {
      shown = next;
      var words = WORDING[next];
      node.dataset.state = next;
      node.querySelector("#cf-outage-title").textContent = words.title;
      node.querySelector("#cf-outage-what").textContent = words.what;
      // Only promise the buttons where the buttons exist.
      node.querySelector("#cf-outage-do").textContent =
        bridge && words.actNative ? words.actNative : words.act;
      node.querySelector("#cf-outage-pill").textContent = words.pill;
    }
    var seconds = Math.round((Date.now() - since) / 1000);
    var clockText = "Stopped " + seconds + "s ago";
    if (next === "waiting") {
      clockText = attempts > 0 ? "Attempt " + attempts + " · " + seconds + "s"
                               : "Reconnecting · " + seconds + "s";
    } else if (next === "starting") {
      // Counting from the press, not from the outage. What the reader wants to
      // know here is whether the thing they just asked for is taking long.
      clockText = "Starting · " + Math.round((Date.now() - began) / 1000) + "s";
    }
    node.querySelector("#cf-outage-clock").textContent = clockText;
  }

  function ask() {
    // `no-store` and a fresh query string: a cached 200 from before the server
    // went is the one answer that would make a dead one look alive.
    var url = (window.path_prefix || "") + PROBE_PATH + "?cf=" + Date.now();
    // A process that has exited refuses the connection at once. One that is
    // wedged — a blocked event loop — accepts it and then says nothing at all,
    // forever, and without a deadline that reads as a healthy server for as
    // long as it lasts. Not answering in time is an answer.
    var stop = new AbortController();
    var deadline = setTimeout(function () { stop.abort(); }, TUNING.probe * 2);
    fetch(url, { method: "HEAD", cache: "no-store", signal: stop.signal }).then(
      function (response) {
        clearTimeout(deadline);
        answered(response);
      },
      function () {
        clearTimeout(deadline);
        silent();
      }
    );
  }

  function answered(response) {
    if (!response.ok) {
      silent();
      return;
    }
    // A server answering on this port after we had called it stopped is a
    // different server than the one that drew this page, so there is no socket
    // to resume — only a page to fetch again.
    if (reading() === "stopped") {
      window.location.reload();
      return;
    }
    refused = 0;
    paint();
  }

  function silent() {
    refused += 1;
    paint();
  }

  function begin() {
    if (since) return;
    since = Date.now();
    attempts = 0;
    refused = 0;
    shown = "";
    forced = "";
    // Ask immediately as well as on the interval: if the program is gone,
    // loopback refuses at once and the notice can open already knowing it.
    ask();
    probe = setInterval(ask, TUNING.probe);
    appear = setTimeout(function () {
      if (!node) build();
      delete node.dataset.dismissed;
      node.dataset.open = "1";
      paint();
      clock = setInterval(paint, 1000);
    }, TUNING.grace);
  }

  function end() {
    if (!since) return;
    since = 0;
    clearTimeout(appear);
    clearInterval(probe);
    clearInterval(clock);
    clearInterval(watch);
    if (node) delete node.dataset.open;
    shown = "";
    forced = "";
  }

  function attach(socket) {
    // NiceGUI's own notice comes down only once ours is certain to go up, so
    // failing to attach leaves the inert one rather than nothing at all.
    var popup = document.getElementById("popup");
    if (popup) popup.style.display = "none";
    socket.on("disconnect", begin);
    socket.on("connect", end);
    if (socket.io) {
      socket.io.on("reconnect_attempt", function (n) {
        attempts = n;
        paint();
      });
    }
  }

  window.addEventListener("pywebviewready", findBridge);
  findBridge();

  // `window.socket` is created when Vue mounts, which is after this script has
  // run, and nothing announces it.
  var pending = setInterval(function () {
    if (!window.socket) return;
    clearInterval(pending);
    attach(window.socket);
  }, 50);
})();
"""


def head_html() -> str:
    """The stylesheet, the markup and the script, as one head fragment."""
    script = (
        _JS.replace("__TUNING__", json.dumps(TUNING))
        .replace("__PROBE_PATH__", json.dumps(PROBE_PATH))
        .replace("__WORDING__", json.dumps(_WORDING))
        .replace("__MARKUP__", json.dumps(_MARKUP))
    )
    return f"<style>{_CSS}</style>\n<script>{script}</script>"


_installed = False


def install() -> None:
    """Put the notice in the head of every page, once per process.

    Shared rather than per-client, and at startup rather than on first draw,
    for the reason `theme.register_css` spells out: a client's own head is
    composed when its page function returns, and this has to be in the document
    that gets served, not sent down the socket that is the thing at risk.
    """
    global _installed
    if _installed:
        return
    _installed = True
    ui.add_head_html(head_html(), shared=True)
