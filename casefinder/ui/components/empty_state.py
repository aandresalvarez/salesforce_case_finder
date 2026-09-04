"""Empty and zero-result states.

Spec section 12 asks for a short explanation and at most two or three
suggestions, never a large error panel. The suggestions are rendered as text
links rather than buttons so a dead end does not become the most visually
prominent thing on the screen.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from nicegui import ui

from ..shell import ACCENT, MUTED


def empty(
    message: str,
    suggestions: Sequence[tuple[str, Callable[[], None]]] = (),
    *,
    icon: str = "search_off",
) -> None:
    with ui.column().classes("w-full items-center").style("gap:6px; padding:56px 0"):
        ui.icon(icon).style(f"font-size:26px; color:{MUTED}")
        ui.label(message).classes("cf-muted").style("max-width:440px; text-align:center")
        if suggestions:
            with ui.row().style("gap:14px; margin-top:6px"):
                for label, action in suggestions[:3]:
                    ui.label(label).style(
                        f"color:{ACCENT}; cursor:pointer; font-size:12.5px"
                    ).on("click", action)


def no_results(
    term_text: str,
    on_clear: Callable[[], None],
    on_switch_era: Callable[[], None],
) -> None:
    empty(
        f"No cases contain {term_text}. Terms are matched literally and must all "
        "be present.",
        [
            ("Clear filters", on_clear),
            ("Search the other era", on_switch_era),
        ],
    )


def unknown_case(case_number: str, era_label: str, on_switch_era: Callable[[], None]) -> None:
    """Spec FR-CASE-11: name the era, offer the one useful next action."""
    empty(
        f"{case_number} is not in {era_label}.",
        [("Look in the other era", on_switch_era)],
        icon="help_outline",
    )
