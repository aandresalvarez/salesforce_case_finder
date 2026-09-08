"""Filter controls.

Two rules from the spec shape everything here:

FR-LIST-6 / UX-INV-2 — filters apply on change. There is no Apply button, so
every control calls back immediately and the caller re-runs its query. Selects
fire once per choice, so they need no debounce; only free text does, and that
is what `Debounce` is for.

FR-LIST-7 — one compact row at normal widths, collapsing to a single `Filters`
disclosure with an active count when the window is too narrow. The controls are
built by one function and rendered twice, inline and inside a menu, with CSS
deciding which is visible. Both write to the same state object and trigger the
same refresh, so the two copies cannot disagree.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from nicegui import ui

from ..theme import ACCENT, LINE, MUTED, SURFACE, register_css

# The breakpoint below which the row gives up and becomes a disclosure.
#
# Measured rather than chosen. With Owner added (D22) the six controls occupy
# 958px plus five 10px gaps, and the pane a page gets is the viewport less 240
# — the rail and the main pane's own padding. So the row needs a 1248px window
# and wraps onto a second line below that: at 1260 it is one line of 1020, at
# 1220 it is two lines of 980. A wrapped row is worse than the disclosure it
# was meant to avoid, so the breakpoint moved up with the control that caused
# it. The default window is 1280, which clears it by 32px.
NARROW_PX = 1260

_CSS = f"""
.cf-filters-inline {{ display:flex; }}
.cf-filters-collapsed {{ display:none; }}
@media (max-width: {NARROW_PX}px) {{
  .cf-filters-inline {{ display:none; }}
  .cf-filters-collapsed {{ display:block; }}
}}

/* The filter chips.
   Every selector here is `.q-field.cf-select` rather than `.cf-select`, and
   that is not decoration. Quasar's own `.q-field--dense .q-field__control`
   carries two classes, exactly as `.cf-select .q-field__control` did, and its
   stylesheet is served after this one — so the previous rules lost every tie.
   The declared 30px chip rendered at Quasar's 40px, while
   `.q-field__marginal` (which Quasar does not set for dense) kept the 30px it
   asked for, leaving the clear and dropdown icons 5px above the centre of a
   control they were supposed to fill. Three classes wins the tie honestly. */
.q-field.cf-select .q-field__control,
.q-field.cf-select .q-field__marginal {{ height:30px; min-height:30px; }}
.q-field.cf-select .q-field__control {{
  border-radius:999px; background:{SURFACE}; padding:0 8px 0 16px;
}}
/* The text box has to be told the height too, not just the control.
   Quasar's `.q-field--dense .q-field__native` carries `min-height:40px`, and
   the rule below sets font and colour but never touched it — so inside a 30px
   chip the native box was still 40px, hanging 10px out of the bottom of the
   control. Its own `align-items:center` then centred the label in *that* box,
   which put the text five pixels below the middle of the pill: not obviously
   broken, just sitting low in every chip in the row. */
.q-field.cf-select .q-field__native,
.q-field.cf-select .q-field__control-container {{
  height:30px; min-height:30px;
}}
/* Quasar draws an outlined field's border on `:before` and its focus ring on
   `:after`, so the `border` this used to set on the control itself sat
   underneath both and was never seen: the row was outlined in
   `rgba(0,0,0,.24)` and focused in Quasar's blue, neither of which is a colour
   this application uses anywhere else. Colour the pseudo-elements instead. */
.q-field.cf-select .q-field__control:before {{ border-color:{LINE}; }}
.q-field.cf-select:hover .q-field__control:before {{ border-color:#c9cdd4; }}
/* `:after` is transparent until Quasar adds `q-field--focused`, so the colour
   belongs on the focused state and not on the element: setting it outright
   painted an accent ring on every chip in the row at rest, which read as five
   controls all focused at once. */
.q-field.cf-select.q-field--focused .q-field__control:after {{
  border-width:1px; border-color:{ACCENT};
}}
.q-field.cf-select .q-field__native {{
  font-size:12.5px; padding:0; flex-wrap:nowrap; color:{MUTED};
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}}
.q-field.cf-select .q-field__append {{ padding-left:2px; }}
.q-field.cf-select .q-field__append .q-icon {{ font-size:16px; color:{MUTED}; }}

/* A chip with something chosen says so, the way the rail says which
   destination you are on. This replaces the floating label, which is what made
   an empty chip and a filled one two different shapes: Quasar lifts the label
   into the border on focus, and there is nowhere for it to go in a 30px pill
   with a 999px radius, so it landed on the curve. */
.q-field.cf-select-on .q-field__control {{ background:rgba(37,99,235,.06); }}
.q-field.cf-select-on .q-field__control:before {{ border-color:{ACCENT}; }}
.q-field.cf-select-on .q-field__native {{ color:{ACCENT}; font-weight:550; }}
.q-field.cf-select-on .q-field__append .q-icon {{ color:{ACCENT}; }}

/* The menu. Left to itself it is as wide as its widest option, and one PI in
   this corpus is a whole study title — so a 170px chip opened a 438px menu
   that escaped the content area. Capped and wrapped instead of ellipsised,
   because the reader is choosing between these and needs to tell them apart. */
.cf-select-menu {{ max-width:340px; }}
.cf-select-menu .q-item {{ min-height:30px; padding:3px 12px; }}
.cf-select-menu .q-item__label {{
  font-size:12.5px; line-height:1.35; white-space:normal; overflow-wrap:anywhere;
}}

/* The one control in this row that is not a chip. Quasar paints a switch in
   its own primary, which is a different blue from the accent every other
   control in the row now uses — two blues side by side read as two states. */
.cf-open-only .q-toggle__inner--truthy .q-toggle__track {{
  background:{ACCENT}; opacity:.4;
}}
.cf-open-only .q-toggle__inner--truthy .q-toggle__thumb:after {{ background:{ACCENT}; }}
"""

register_css("filters", _CSS)


class Debounce:
    """Delay a callback until typing pauses — spec NFR-PERF-2.

    Without this, a filter bound to a text field issues one BigQuery job per
    keystroke.
    """

    def __init__(self, action: Callable[[], None], seconds: float = 0.35) -> None:
        self._action = action
        self._seconds = seconds
        self._timer: ui.timer | None = None

    def trigger(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = ui.timer(self._seconds, self._fire, once=True)

    def _fire(self) -> None:
        self._timer = None
        self._action()


def multi_select(
    label: str,
    options: Sequence[str],
    selected: list[str],
    on_change: Callable[[list[str]], None],
    *,
    width: int = 170,
) -> None:
    """A compact multi-select chip.

    An empty facet renders nothing at all rather than a dead control the user
    can open to find nothing in — spec section 12.

    The chip carries no Quasar `label`. It used to, and that is what made an
    empty control and a filled one look like two different widgets: with a
    value chosen, Quasar lifts the label into the border and stacks the value
    under it, which needs vertical room a 30px pill does not have. What the
    chip shows instead is the dimension when nothing is chosen and the choice
    when something is — one line either way — with the dimension still carried
    by the accent treatment, the tooltip, and the accessible name.
    """
    if not options:
        return
    element = (
        ui.select(
            list(options),
            multiple=True,
            value=list(selected),
            on_change=lambda e: on_change(list(e.value or [])),
        )
        .props(
            'dense outlined options-dense clearable clear-icon="close" '
            'popup-content-class="cf-select-menu"'
        )
        .props(f'display-value="{_chip_text(label, selected)}"')
        # The label is gone from the surface, so it has to stay in the name.
        .props(f'aria-label="{label}"')
        .classes("cf-select" + (" cf-select-on" if selected else ""))
        .style(f"width:{width}px")
    )
    with element:
        # Above the chip, not below it. A tooltip under a control that opens a
        # menu under itself lands on the menu's first option — which is exactly
        # what it did, hiding the first PI in the list behind `Filter by pi`.
        # The delay keeps it from firing at all on the way to a click.
        ui.tooltip(_tooltip(label, selected)).props(
            'anchor="top middle" self="bottom middle" :delay="500"'
        )


def _chip_text(label: str, selected: Sequence[str]) -> str:
    """What the chip reads when closed: the dimension, or the choice."""
    return summarise(label, selected) if selected else label


def summarise(label: str, selected: Sequence[str]) -> str:
    """What a filter control says about itself once something is chosen.

    Quasar's default is every value, comma-joined, inside a 170px control — so
    picking `Data Queue` showed `Data Q…` and picking two things showed neither
    of them. One value is worth spelling out; past that a count is honest about
    the fact that the control cannot show them, and the tooltip has the list.
    """
    if len(selected) == 1:
        # Quotes would terminate the Quasar prop; a value containing one is not
        # worth a quoting scheme when dropping it changes nothing that matters.
        return selected[0].replace('"', "")
    return f"{label} · {len(selected)}"


def _tooltip(label: str, selected: Sequence[str]) -> str:
    """The label is used as written. Lowercasing it read `Filter by pi` and
    `Filter by irb / protocol` — the two labels that are acronyms are the two
    a mechanical rule gets wrong."""
    if not selected:
        return f"Filter by {label}"
    return f"{label}: " + ", ".join(selected)


def open_only_toggle(value: bool, on_change: Callable[[bool], None]) -> None:
    ui.switch(
        "Open only", value=value, on_change=lambda e: on_change(bool(e.value))
    ).props("dense").classes("cf-open-only").style("font-size:12.5px")


def inline_row(build: Callable[[], None], active_count: int) -> None:
    """Render `build` twice: as a wide compact row, and behind a narrow disclosure."""
    with ui.row().classes("cf-filters-inline items-center w-full").style(
        "gap:10px; flex-wrap:wrap; margin:12px 0 6px 0"
    ):
        build()
    with ui.element("div").classes("cf-filters-collapsed").style("margin:12px 0 6px 0"):
        label = f"Filters ({active_count})" if active_count else "Filters"
        with ui.button(label, icon="tune").props("outline no-caps dense").style(
            f"color:{MUTED}"
        ), ui.menu().classes("p-3"), ui.column().style("gap:10px; min-width:240px"):
            build()


def scope_control(
    in_fields: bool,
    in_conversation: bool,
    on_change: Callable[[bool, bool], None],
) -> None:
    """Search scope — spec FR-SEARCH-5.

    One segmented control that reads as a single decision. Both options may be
    on; turning off the last one turns the other back on, because a search
    scoped to nothing has no meaningful result and silently returning zero rows
    would look like a data problem.
    """

    def toggle(which: str, value: bool) -> None:
        fields, conversation = in_fields, in_conversation
        if which == "fields":
            fields = value
            conversation = conversation or not fields
        else:
            conversation = value
            fields = fields or not conversation
        on_change(fields, conversation)

    pill = f"gap:0; border:1px solid {LINE}; border-radius:999px; overflow:hidden"
    with ui.row().style(pill):
        for key, label, active in (
            ("fields", "Subject & description", in_fields),
            ("conversation", "Inside conversation", in_conversation),
        ):
            # Prefixed as well as plain: the scope pill is a control, and the
            # native window is WebKit, which reads the prefixed longhand.
            style = (
                "padding:5px 14px; font-size:12.5px; cursor:pointer;"
                "-webkit-user-select:none; user-select:none;"
            )
            if active:
                style += " background:rgba(37,99,235,.10); color:#2563eb; font-weight:550;"
            ui.label(label).style(style).on(
                "click", lambda k=key, a=active: toggle(k, not a)
            )


def era_select(era_key: str, options: dict, on_change: Callable[[str], None]) -> None:
    """Era picker. Controls what content exists, not what a query costs."""
    ui.select(
        {key: era.label for key, era in options.items()},
        value=era_key,
        on_change=lambda e: on_change(e.value),
    ).props(
        # No `borderless`: it was passed alongside `outlined`, which is the
        # prop that decides, so it never did anything.
        'dense outlined options-dense popup-content-class="cf-select-menu"'
    ).classes("cf-select").style("width:230px")
