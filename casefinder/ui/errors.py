"""How a page reports a failure — spec section 12.

Compact by rule: one plain sentence, with the raw text one disclosure away. A
failed query must not blank a window or fill it with a stack trace, and six
different pages must not each decide what that looks like.
"""

from __future__ import annotations

from nicegui import ui


def error_region(exc: Exception) -> None:
    """Compact error display with the raw text kept available."""
    with ui.column().classes("w-full").style("gap:6px; margin-top:10px"):
        ui.label(friendly(exc)).classes("cf-h2")
        with ui.expansion("Details").classes("cf-muted"):
            ui.label(f"{type(exc).__name__}: {exc}").classes("cf-error")


def friendly(exc: Exception) -> str:
    """One plain sentence for the top line of an error.

    `ValueError` is passed through verbatim because the read-only guard and the
    query builders raise it with text written for the user; anything else is a
    BigQuery or transport failure whose own message is not.
    """
    from ..bq import CostError, QueryTimeout

    if isinstance(exc, CostError):
        return "That query would scan more data than the safety cap allows."
    if isinstance(exc, QueryTimeout):
        return str(exc)
    if isinstance(exc, ValueError):
        return str(exc)
    return "BigQuery could not run that."
