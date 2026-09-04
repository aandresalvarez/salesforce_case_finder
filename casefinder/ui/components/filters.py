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

from ..shell import LINE, MUTED, register_css

# The breakpoint below which the row gives up and becomes a disclosure.
NARROW_PX = 1180

_CSS = f"""
.cf-filters-inline {{ display:flex; }}
.cf-filters-collapsed {{ display:none; }}
@media (max-width: {NARROW_PX}px) {{
  .cf-filters-inline {{ display:none; }}
  .cf-filters-collapsed {{ display:block; }}
}}
.cf-select .q-field__control {{
  min-height:30px; height:30px; border-radius:999px;
  background:#fff; border:1px solid {LINE};
}}
.cf-select .q-field__native {{
  font-size:12.5px; padding:0; flex-wrap:nowrap;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}}
.cf-select .q-field__marginal {{ height:30px; }}
.cf-select .q-field__append {{ padding-left:2px; }}
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
    """
    if not options:
        return
    element = (
        ui.select(
            list(options),
            multiple=True,
            value=list(selected),
            label=label,
            on_change=lambda e: on_change(list(e.value or [])),
        )
        .props("dense outlined options-dense clearable")
        .classes("cf-select")
        .style(f"width:{width}px")
    )
    if selected:
        element.props(f'display-value="{summarise(label, selected)}"')
    element.tooltip(_tooltip(label, selected))


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
    if not selected:
        return f"Filter by {label.lower()}"
    return f"{label}: " + ", ".join(selected)


def open_only_toggle(value: bool, on_change: Callable[[bool], None]) -> None:
    ui.switch("Open only", value=value, on_change=lambda e: on_change(bool(e.value))).props(
        "dense"
    ).style("font-size:12.5px")


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
    ).props("dense outlined options-dense borderless").classes("cf-select").style(
        "width:230px"
    )
