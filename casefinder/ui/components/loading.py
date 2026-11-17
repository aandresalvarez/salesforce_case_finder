"""Say that a slow thing is happening, and keep the window alive while it does.

Opening a case costs a BigQuery round trip against an unclustered body column
(known limitation 1): about two seconds, sometimes more, during which the old
page had already gone and the new one had not arrived. A desktop window that
goes blank for two seconds does not look busy, it looks broken, and the second
click that produces is another 237 MB scan.

`while_loading` exists because drawing a spinner is not enough on its own. A
NiceGUI page function runs in the event loop, so a synchronous query inside one
blocks the loop *before* the spinner it just created has been flushed to the
browser: the placeholder is built, and then nothing is sent until the query it
was meant to cover has already finished. The work has to move off the loop for
the placeholder to reach the screen at all, which is what `run.io_bound` is
for.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from nicegui import background_tasks, run, ui


def _can_defer() -> bool:
    """Whether there is an event loop to hand the slow work to.

    Inside the running app there always is. Outside one — a page built
    synchronously, which is how the tests render them — there is not, and a
    placeholder scheduled against a loop that will never run is a spinner
    forever.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def placeholder(note: str, *, center: bool = False) -> None:
    """A spinner and a line saying what is being waited for.

    Left-aligned by default, because it stands in for content that will be
    left-aligned and a spinner that moves when the content arrives is a second
    thing happening. `center` is for the one screen whose content is centred —
    the idle search page, where a left-aligned spinner under a centred box
    reads as a layout fault rather than as a wait.
    """
    justify = " justify-center" if center else ""
    with ui.row().classes("w-full items-center" + justify).style("gap:10px; padding:26px 0"):
        ui.spinner(size="1.4rem")
        ui.label(note).classes("cf-muted")


def while_loading(
    note: str,
    load: Callable[[], Any],
    then: Callable[[Any], None],
    *,
    on_error: Callable[[Exception], None],
    center: bool = False,
) -> ui.column:
    """Show `note` with a spinner, run `load` off the event loop, draw `then`.

    Returns the container, which holds the placeholder until the load finishes
    and its result afterwards. `load` must not touch the UI — it is running in
    a worker thread, with no slot context and no client.
    """
    container = ui.column().classes("w-full").style("gap:0")

    if not _can_defer():
        # Nothing to defer onto, so deferring would leave a spinner that never
        # stops. Do the work now and hand back the finished page: slower to
        # first paint, which is the correct trade against never painting.
        with container:
            try:
                then(load())
            except Exception as exc:  # noqa: BLE001
                container.clear()
                on_error(exc)
        return container

    with container:
        placeholder(note, center=center)

    async def run_it() -> None:
        try:
            result = await run.io_bound(load)
        except Exception as exc:  # noqa: BLE001
            container.clear()
            with container:
                on_error(exc)
            return
        container.clear()
        with container:
            then(result)

    # A timer rather than a background task, because the page function has to
    # return before anything it built is sent. `once` with a delay of zero
    # fires on the next pass of the loop, which is after that flush.
    ui.timer(0, run_it, once=True)
    return container


def in_background(
    load: Callable[[], Any],
    then: Callable[[Any], None],
    *,
    on_error: Callable[[Exception], None],
) -> None:
    """`while_loading` for work a click starts rather than a page (D39).

    A button's handler runs on the event loop just as a page function does, so
    a query inside one holds the loop for as long as BigQuery takes — and the
    loop is also what answers the window. Measured on the SQL page: a query
    that took twenty seconds dropped the window's connection at five, and at
    nine the window said Case Finder had stopped responding (D20), while Case
    Finder was only waiting for an answer.

    `load` runs on a worker thread and must not touch the UI; `then` and
    `on_error` run back on the loop and may. Unlike `while_loading` this draws
    no placeholder: a handler has no container of its own to put one in, so
    the caller draws it where the answer will go.

    A background task rather than `while_loading`'s timer: a click arrives
    over a connection that is already open, so there is no first flush to wait
    for. Inline when there is no event loop, for the same reason as
    `while_loading` — that is how the tests press buttons.
    """
    if not _can_defer():
        try:
            result = load()
        except Exception as exc:  # noqa: BLE001
            on_error(exc)
            return
        then(result)
        return

    async def run_it() -> None:
        try:
            result = await run.io_bound(load)
        except Exception as exc:  # noqa: BLE001
            on_error(exc)
            return
        then(result)

    background_tasks.create(run_it(), name="casefinder: in background")
