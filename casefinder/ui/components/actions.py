"""The action vocabulary: the only ways this application makes a button.

`primary()` is the one that matters. Every other helper here produces outline
or text, so UX-INV-1 — at most one filled action per screen — is enforced by
what is available rather than by review. UX-T1 counts elements carrying the
`cf-primary` marker class, which means a page wanting a second filled button
has to reach for something visibly named as the exception.

Kept alongside the other reusable pieces rather than in `shell`, because that
is what these are: a page needs a button far more often than it needs the
navigation rail, and it should not import one to get the other.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from nicegui import ui

from ..theme import ACCENT, INK, MUTED

# --------------------------------------------------------------------------
# Action helpers — the primary-button rule lives here
# --------------------------------------------------------------------------


def primary(label: str, on_click, *, icon: str | None = None) -> ui.button:
    """The one filled action a screen is allowed. See UX-INV-1."""
    return (
        ui.button(label, on_click=on_click, icon=icon)
        .props("unelevated no-caps dense")
        .classes("cf-primary")
        .style(f"background:{ACCENT}; color:white; padding:5px 16px; border-radius:5px")
    )


def secondary(label: str, on_click, *, icon: str | None = None) -> ui.button:
    return (
        ui.button(label, on_click=on_click, icon=icon)
        .props("outline no-caps dense")
        .classes("cf-secondary")
        .style(f"color:{INK}; padding:4px 12px; border-radius:5px")
    )


def quiet(label: str, on_click, *, icon: str | None = None) -> ui.button:
    return (
        ui.button(label, on_click=on_click, icon=icon)
        .props("flat no-caps dense")
        .classes("cf-quiet")
        .style(f"color:{MUTED}; padding:3px 8px")
    )


@contextmanager
def overflow(tooltip: str = "More actions") -> Iterator[None]:
    """The `…` menu. Everything the spec calls secondary lives behind this."""
    with ui.button(icon="more_horiz").props("flat dense round").classes("cf-overflow") as button:
        button.tooltip(tooltip)
        with ui.menu().props("auto-close").classes("text-sm"):
            yield


def muted(text: str) -> ui.label:
    return ui.label(text).classes("cf-muted")
