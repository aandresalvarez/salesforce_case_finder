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

from nicegui import ui

from ... import intake
from ..shell import LINE, register_css

_CSS = f"""
.cf-form {{
  border:1px solid {LINE}; border-radius:6px;
  padding:12px 14px; margin-top:6px;
}}
.cf-form-grid {{
  display:grid; grid-template-columns:repeat(auto-fill, minmax(240px, 1fr));
  gap:10px 22px;
}}
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
"""

# At import, not at first draw. A form is usually drawn from a timer callback
# behind `loading.while_loading`, which runs after the page's head has already
# been sent — registering there would serve `.cf-form` with nothing behind it.
register_css("intake_form", _CSS)


def render(form: intake.Intake) -> None:
    """The parsed form: field grid, then the request, then the original."""
    with ui.column().classes("w-full cf-form").style("gap:0"):
        if form.fields:
            with ui.element("div").classes("cf-form-grid w-full"):
                for field in form.fields:
                    _field(field)
        if form.narrative:
            if form.fields:
                ui.element("div").classes("cf-divider w-full").style("margin:12px 0 10px 0")
            ui.label("Request").classes("cf-metric-label")
            ui.label(form.narrative).classes("cf-form-text")
        _original(form.raw)


def _field(field: intake.Field) -> None:
    classes = "cf-form-wide" if field.block else ""
    with ui.column().classes(classes).style("gap:1px; min-width:0"):
        ui.label(field.label).classes("cf-metric-label")
        ui.label(field.value).style("font-size:13px; overflow-wrap:anywhere")


def _original(raw: str) -> None:
    with ui.expansion("Original record").classes("w-full cf-muted").props("dense").style(
        "margin-top:10px"
    ):
        ui.label(raw).classes("cf-form-raw")


def body(text: str | None, *, empty_text: str = "(empty)") -> None:
    """A case body: the parsed form when it is one, the text when it is not.

    Every caller that shows a body should come through here rather than
    deciding for itself, so a comment, a message and the case description all
    read the same way — and so a body that is *not* a form still reaches the
    plain path unchanged.
    """
    form = intake.parse(text)
    if form is None:
        ui.label(text or empty_text).classes("cf-body")
        return
    render(form)
