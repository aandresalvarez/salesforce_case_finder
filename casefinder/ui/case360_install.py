"""Optional companion installation reached from the ordinary Case Finder wheel."""
from __future__ import annotations

import asyncio
import tarfile
import zipfile
from pathlib import Path

from nicegui import app, ui

from ..case360 import delivery
from .components.actions import muted, primary, secondary


def render_install() -> None:
    ui.label("Case 360 Beta").classes("cf-h1")
    muted("Describe a research request, clarify the scope, and review a SQL draft.")
    status = ui.label()
    status.props('role="status" aria-live="polite"')
    actions = ui.column().classes("w-full items-start")

    async def open_installed() -> None:
        toggle(False)
        status.text = "Checking the installed beta…"
        try:
            if not await asyncio.to_thread(delivery.open_beta):
                render_actions()
                return
            status.text = "Opening Case 360 Beta…"
        except (OSError, ValueError, KeyError):
            render_actions(repair=True)
        finally:
            toggle(True)

    async def install() -> None:
        toggle(False)
        try:
            if app.native.main_window is None:
                status.text = "Use the Case Finder desktop app to select the private pilot ZIP."
                return
            files = await app.native.main_window.create_file_dialog(
                allow_multiple=False, file_types=("Case Finder Beta (*.zip)",))
            if not files:
                return
            status.text = "Checking and installing the beta. This can take a few minutes…"
            await asyncio.to_thread(delivery.install_archive, Path(files[0]))
            render_actions()
            status.text = "Beta installed. Close any older beta window before opening it."
        except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile, tarfile.TarError):
            status.text = "Installation could not finish. Check that you selected the original " \
                "pilot ZIP for this computer. Your saved work has not been removed."
        finally:
            toggle(True)

    buttons: list[ui.button] = []

    def render_actions(*, repair: bool = False) -> None:
        try:
            installed = not repair and delivery.selected(verify_payload=False) is not None
        except (OSError, ValueError, KeyError):
            installed, repair = False, True
        actions.clear()
        buttons.clear()
        with actions:
            if installed:
                status.text = "Case 360 Beta is installed on this computer."
                buttons.append(primary("Open beta", open_installed))
                with ui.expansion("Manage beta installation").props("dense"):
                    buttons.append(secondary("Update from private ZIP", install))
            elif repair:
                status.text = "Case 360 Beta could not open. Choose the current private pilot ZIP."
                buttons.append(primary("Repair beta installation", install))
            else:
                status.text = "Install the private pilot ZIP to use Case 360 Beta."
                buttons.append(primary("Install beta", install))

    def toggle(enabled: bool) -> None:
        for button in buttons:
            button.set_enabled(enabled)

    render_actions()
