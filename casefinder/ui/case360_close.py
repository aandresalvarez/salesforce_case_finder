"""Offer Return or Stop and close; never approve native exit before process proof."""
from nicegui import ui

from ..case360 import session


def install() -> None:
    pending = False

    async def ask_close() -> None:
        nonlocal pending
        if pending:
            return
        pending = True
        with ui.dialog().props("persistent") as dialog, ui.card():
            ui.label("Close Case Finder")
            status = ui.label("Checking active work…")

            def return_to_app() -> None:
                nonlocal pending
                session.return_to_app()
                pending = False
                dialog.close()

            async def stop_and_close() -> None:
                stop.disable()
                back.disable()
                try:
                    await session.stop_for_close()
                    status.text = "Owned processes stopped. Closing…"
                    ui.run_javascript(
                        "window.case360CloseApproved = true; window.pywebview.api.close();"
                    )
                except (RuntimeError, OSError, ValueError, TimeoutError) as error:
                    status.text = str(error)
                    back.enable()

            back = ui.button("Return to app", on_click=return_to_app)
            stop = ui.button("Stop and close", on_click=stop_and_close)
            stop.disable()
        dialog.open()
        try:
            active = await session.begin_close()
            if active:
                status.text = ("Work is active. Closing stops it and preserves recorded charges "
                               "and uncertain reservations. Resume requires a verified checkpoint.")
                stop.enable()
            else:
                await stop_and_close()
        except (RuntimeError, OSError, ValueError, TimeoutError) as error:
            status.text = str(error)

    ui.on("case360-close-request", ask_close)
