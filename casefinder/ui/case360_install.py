"""Open the selected companion from navigation and manage its package in Settings."""
from __future__ import annotations

import asyncio
import tarfile
import zipfile
from pathlib import Path

from nicegui import app, ui

from ..case360 import delivery
from .components.actions import primary

PACKAGE_SETTINGS = "/settings/case360"


def render_launch() -> None:
    ui.label("Case 360 Beta").classes("cf-h1")
    status = ui.label("Opening Case 360 Beta…").props('role="status" aria-live="polite"')
    settings = ui.link("Go to Case 360 Beta settings", PACKAGE_SETTINGS)
    settings.set_visibility(False)
    attempted = False

    async def launch() -> None:
        nonlocal attempted
        # Reconnecting this page must not launch another companion window.
        if attempted:
            return
        attempted = True
        try:
            result = await asyncio.to_thread(delivery.open_beta)
            if result:
                status.text = {
                    "opened": "Case 360 Beta is opening in a separate window.",
                    "starting": "Case 360 Beta is starting.",
                    "focused": "Returned to your open Case 360 Beta window.",
                    "already_open": "Case 360 Beta is already open. Select it in the Dock.",
                }[result]
                return
            status.text = "Install Case 360 Beta from Settings to get started."
        except (OSError, ValueError, KeyError):
            status.text = "Case 360 Beta could not open. Check its installation in Settings."
        settings.set_visibility(True)

    ui.context.client.on_connect(launch)


def render_install() -> None:
    ui.label("Case 360 Beta installation").classes("cf-h1")
    status = ui.label().props('role="status" aria-live="polite"')

    def refresh() -> None:
        try:
            installed = delivery.selected(verify_payload=False) is not None
        except (OSError, ValueError, KeyError):
            status.text = "Select the current private pilot ZIP to repair the installation."
            choose.text = "Repair from private ZIP"
            return
        if installed:
            status.text = "Case 360 Beta is installed. Use a new private pilot ZIP to update it."
            choose.text = "Update from private ZIP"
        else:
            status.text = "Choose the private pilot ZIP supplied by the pilot owner."
            choose.text = "Install from private ZIP"

    async def install() -> None:
        choose.disable()
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
            refresh()
            status.text = "Beta installed. Use Case 360 Beta in the menu to open it."
        except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile, tarfile.TarError):
            status.text = (
                "Installation could not finish. Select the original pilot ZIP for this computer."
            )
        finally:
            choose.enable()

    choose = primary("Install from private ZIP", install)
    refresh()
