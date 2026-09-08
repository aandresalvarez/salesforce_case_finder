"""Render an intake-form payload as a form instead of as JSON.

The parsing lives in `casefinder/intake.py`; this is only the drawing. Two
rules it follows that are worth stating, because both are easy to lose in a
later edit:

Nothing is rendered as HTML. Every value goes through `ui.label`, which escapes
— these bodies are pasted email and the intake form has a free-text box, so
treating any of it as markup is the injection in spec section 9.5 with extra
steps.

The original is always one click away. A formatted view is an interpretation,
and someone acting on a case has to be able to check it against what the record
literally says.
"""

from __future__ import annotations

from collections.abc import Mapping

from nicegui import ui

from ... import intake
from ...models import preview
from ..theme import LINE, MUTED, register_css

_CSS = f"""
.cf-form {{
  border:1px solid {LINE}; border-radius:6px;
  padding:12px 14px; margin-top:6px;
}}
.cf-form-grid {{
  display:grid; grid-template-columns:repeat(auto-fill, minmax(240px, 1fr));
  gap:10px 22px;
}}
/* Space between the answers, so `Summary` does not read as a caption on the
   paragraph above it. */
.cf-form-part + .cf-form-part {{ margin-top: 11px; }}
/* A long value spans the grid rather than wrapping inside one 240px cell,
   where a URL or a sentence would come out one word per line. */
.cf-form-wide {{ grid-column:1 / -1; }}
/* The request itself, with the line breaks the requester typed. `pre-wrap`
   rather than `pre`: the form's own newlines are meaningful, its line
   *lengths* are whatever the person's textarea happened to be. */
.cf-form-text {{
  white-space:pre-wrap; overflow-wrap:anywhere;
  font-size:13px; line-height:1.55; margin-top:2px;
}}
.cf-form-raw {{
  white-space:pre-wrap; overflow-wrap:anywhere;
  font-family:ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size:11.5px; line-height:1.5;
}}
/* What was folded, said once and quietly. A count rather than the fields
   themselves: the reader needs to know nothing was thrown away, not to read
   the thing that was already read. */
.cf-form-folded {{
  grid-column:1 / -1; font-size:11.5px; color:{MUTED}; margin-top:10px;
}}
.cf-form-conflict {{
  display:flex; align-items:center; font-size:11.5px; color:#8a5a12;
  background:#fdf6e6; border:1px solid #f0e2be; border-radius:4px;
  padding:1px 7px; margin-top:3px; width:fit-content;
}}
"""

# At import, not at first draw. A form is usually drawn from a timer callback
# behind `loading.while_loading`, which runs after the page's head has already
# been sent — registering there would serve `.cf-form` with nothing behind it.
# Room for a short identifier or a couple of words. Past that the flag is
# wider than the field it belongs to.
_FLAG_CHARS = 44

register_css("intake_form", _CSS)


def request(form: intake.Intake, *, byline: str = "") -> None:
    """The submitted request, pinned above the thread it started.

    The only copy on the page: the turn carrying the same payload is dropped,
    and the requester's own details have moved to the rail. What is left is
    what somebody asked for, under the prompts they answered.
    """
    with ui.column().classes("w-full cf-request").style("gap:2px"):
        with ui.row().classes("items-baseline").style("gap:8px; flex-wrap:wrap"):
            ui.label("The request").classes("cf-request-h")
            if byline:
                ui.label(byline).classes("cf-muted")
        render(form)


def render(form: intake.Intake) -> None:
    """The parsed form: field grid, then the request, then the original.

    Only the fields that say something are drawn. A field the page already
    shows elsewhere is folded away with a count — see `intake.reconcile` for
    what counts as already shown — and the payload stays whole behind
    `Original record`, which is what makes the folding safe to do at all.
    """
    visible = [f for f in form.fields if not f.echoes]
    folded = len(form.fields) - len(visible)
    parts = intake.sections(form.narrative) if form.narrative else ()
    with ui.column().classes("w-full cf-form").style("gap:0"):
        # What was written, before what was ticked. The narrative is the
        # request; the fields that survive reconciliation are answers to
        # checkbox prompts beside it, and leading with them buried the three
        # paragraphs anybody actually opened the case to read.
        for label, text in parts:
            with ui.column().classes("cf-form-part w-full").style("gap:1px"):
                if label:
                    ui.label(label).classes("cf-metric-label")
                ui.label(text).classes("cf-form-text")
        if visible:
            if parts:
                ui.element("div").classes("cf-divider w-full").style("margin:14px 0 11px 0")
            with ui.element("div").classes("cf-form-grid w-full"):
                for field in visible:
                    _field(field)
        if folded:
            ui.label(
                f"{folded} field{'s' if folded != 1 else ''} the case already "
                "shows, and its routing, are in the original record below."
            ).classes("cf-form-folded")
        _original(form.raw)


def _field(field: intake.Field) -> None:
    classes = "cf-form-wide" if field.block else ""
    with ui.column().classes(classes).style("gap:1px; min-width:0"):
        ui.label(field.label).classes("cf-metric-label")
        ui.label(field.value).style("font-size:13px; overflow-wrap:anywhere")
        if field.conflicts:
            # The one thing on a form worth interrupting a reader for: the
            # requester answered this before the answer existed, and the case
            # has since been given a different one.
            # Clamped, because the flag annotates a field and must not
            # outgrow it: a case subject can run to a full sentence, and three
            # wrapped lines of amber under a one-word answer reads as the
            # error rather than as a note about it. The whole value is on hover.
            with ui.row().classes("cf-form-conflict").style("gap:5px") as flag:
                ui.icon("error_outline").style("font-size:13px")
                ui.label(f"the case says {preview(field.conflicts, _FLAG_CHARS)}")
            flag.tooltip(f"the case says {field.conflicts}")


def _original(raw: str) -> None:
    with ui.expansion("Original record").classes("w-full cf-muted").props("dense").style(
        "margin-top:10px"
    ):
        ui.label(raw).classes("cf-form-raw")


def body(
    text: str | None,
    *,
    empty_text: str = "(empty)",
    shown: Mapping[str, str] | None = None,
) -> None:
    """A case body: the parsed form when it is one, the text when it is not.

    Every caller that shows a body comes through here rather than deciding for
    itself, so a comment, a message, a timeline entry and the case description
    all read the same way — and so a body that is *not* a form still reaches
    the plain path unchanged. The timeline used not to, and printed the whole
    serialised payload as the most prominent thing on that tab.

    `shown` is what the page already displays, keyed by the form's own labels;
    the fields that repeat it are folded away. Without it the form is drawn
    whole, which is right for any caller that has no case header to compare
    against.
    """
    form = intake.parse(text)
    if form is None:
        ui.label(text or empty_text).classes("cf-body")
        return
    render(intake.reconcile(form, shown) if shown else form)
