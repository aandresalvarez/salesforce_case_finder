"""The visual language: one stylesheet, and the two ways it reaches a page.

Split out of `shell` because it is the one thing here that every module needs
and nothing here depends on. A component asking for a colour should not have to
import the navigation rail to get it.

Two installers, and the difference between them has been got wrong twice, so it
is worth stating plainly:

`install()` writes the application stylesheet into *this client's* head, once
per page load. `register_css()` writes a component's stylesheet into the head
served to *every* client, at import time — see its docstring for why nothing
later than import works.
"""

from __future__ import annotations

from nicegui import context, ui

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
  /* A destination is a control, so dragging across one should not highlight
     its label. Both spellings: the window this ships in is WebKit, which reads
     the prefixed longhand, and until the page became selectable at all the
     unprefixed one here was never doing anything. */
  -webkit-user-select: none; user-select: none;
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

/* --- the case page: identity, two columns, and a readable thread --- */
/* The bar pins to the top of the scrolling pane, and the negative offset is
   what makes it pin to the top the reader can see — the same arithmetic the
   sticky table header does, against the same variable. */
.cf-case-id {{
  position: sticky; top: calc(var(--cf-pad-top) * -1); z-index: 2;
  background: var(--cf-surface); border-bottom: 1px solid var(--cf-line);
  box-shadow: 0 1px 0 var(--cf-line);
  padding: 9px 0; margin-bottom: 4px;
}}
.cf-case-id-title {{
  font-size: 13px; min-width: 0; flex: 1 1 200px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.cf-case-cols {{ display: flex; align-items: flex-start; flex-wrap: nowrap; }}
/* The reading measure lives on the thread rather than on the page, because the
   page is now two things: prose that has to stay narrow, and a rail that is
   chrome and does not. */
.cf-case-main {{ flex: 1 1 auto; min-width: 0; max-width: 720px; padding: 14px 0 40px; }}
.cf-case-rail {{
  flex: 0 0 280px; width: 280px; align-self: stretch;
  border-left: 1px solid var(--cf-line);
  margin-left: 28px; padding: 20px 0 40px 22px;
  position: sticky; top: 34px;
}}
.cf-rail-sec {{
  padding-bottom: 18px; margin-bottom: 18px;
  border-bottom: 1px solid var(--cf-line);
}}
.cf-rail-sec:last-child {{ border-bottom: 0; margin-bottom: 0; padding-bottom: 0; }}
.cf-rail-h {{
  font-size: 11px; font-weight: 600; letter-spacing: .05em;
  text-transform: uppercase; color: var(--cf-muted); margin-bottom: 9px;
}}
/* Under this width the rail stops being a margin and starts being a second
   column competing with the prose — a 1024px window leaves the pane 784px, and
   784 less a 280px rail is not a reading measure. It folds above the thread
   instead, which is the same move the filter row makes at its own breakpoint. */
@media (max-width: 1180px) {{
  .cf-case-cols {{ flex-wrap: wrap; }}
  .cf-case-main {{ flex: 1 1 100%; max-width: 100%; order: 2; }}
  .cf-case-rail {{
    flex: 1 1 100%; width: 100%; position: static;
    border-left: 0; border-bottom: 1px solid var(--cf-line);
    margin-left: 0; padding: 4px 0 16px 0; order: 1;
  }}
  .cf-rail-sec {{ padding-bottom: 14px; margin-bottom: 14px; }}
}}

/* A month is the cheapest orientation a long thread can be given: on a case
   that ran from April to September it turns a scroll position into a date. */
.cf-monthmark {{
  font-size: 11px; letter-spacing: .05em; text-transform: uppercase;
  color: var(--cf-muted); margin: 18px 0 2px 0;
}}
.cf-monthmark::after {{ content: ""; flex: 1; height: 1px; background: var(--cf-line); }}
.cf-fold {{
  border: 1px dashed var(--cf-line); border-radius: 6px; background: var(--cf-canvas);
  padding: 9px 14px; margin: 12px 0; cursor: pointer;
  font-size: 12.5px; color: var(--cf-accent);
}}
.cf-fold:hover {{ background: #eef2f8; }}
/* The compact reading: one line a turn, which is what the Messages tab was. */
.cf-turn-line {{
  font-size: 13px; color: #374151;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.cf-seg {{
  display: flex; border: 1px solid var(--cf-line); border-radius: 999px; overflow: hidden;
}}
.cf-seg > * {{
  padding: 2px 11px; font-size: 11.5px; cursor: pointer; color: var(--cf-muted);
  -webkit-user-select: none; user-select: none;
}}
.cf-seg > .cf-seg-on {{
  background: rgba(37,99,235,.10); color: var(--cf-accent); font-weight: 550;
}}
/* Related cases, grouped by strength. Two lines a row rather than a table:
   at 280px a case number and a title cannot share a line, and the title is
   the half that says what the case is about. */
.cf-rel-group .q-item {{ padding: 2px 0; min-height: 26px; }}
.cf-rel-group .q-item__label {{ font-size: 12px; color: var(--cf-muted); }}
.cf-rel-group .q-expansion-item__content {{ padding: 2px 0 6px 0; }}
.cf-rel-row {{ padding: 5px 0; border-bottom: 1px solid var(--cf-line); }}
.cf-rel-row:last-child {{ border-bottom: 0; }}
/* The request, pinned. Lifted off the page just enough to read as the thing
   the case is about rather than as the first entry of its thread. */
.cf-request {{
  border: 1px solid var(--cf-line); border-radius: 6px;
  padding: 13px 16px; margin: 4px 0 2px 0; background: #fbfcfe;
}}
.cf-request-h {{ font-size: 12.5px; font-weight: 600; }}
/* The request already has a frame. The form inside it does not need a second
   one — two nested borders read as two objects, and this is one. */
.cf-request .cf-form {{ border: 0; padding: 0; margin-top: 8px; }}
.cf-chip-open::before {{
  content: ""; display: inline-block; width: 6px; height: 6px;
  border-radius: 50%; background: #2f8f5b; margin-right: 6px;
  vertical-align: middle;
}}
.cf-rel-subject {{
  font-size: 12.5px; line-height: 1.35;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}}
"""

# For the click handler of a region that navigates but also holds text someone
# might want to take: a list row, a search result, a related case.
#
# Selecting text is a click. Press in the middle of a description, release at
# the end of it, and the browser sends `click` to the enclosing row exactly as
# if the row had been tapped — so highlighting a name to copy it would open the
# case instead, and lose the highlight on the way out. Every one of these
# regions was written when nothing on the page was selectable, which is why
# none of them thought about it.
#
# `emit` is NiceGUI's client-side call into the Python handler, and a
# `js_handler` that declines to call it drops the event in the browser. The row
# keeps its one handler rather than growing a second one to undo the first.
#
# The check is about this gesture, not about the page's history: a press
# collapses whatever was selected before `click` is dispatched, so a plain
# click always sees an empty selection.
CLICK_UNLESS_SELECTING = "(...args) => { if (!window.getSelection().toString()) emit(...args) }"


def install() -> None:
    """Install the application stylesheet on this client, once.

    Once matters now that `shell.gated` puts a placeholder on the screen before it
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
