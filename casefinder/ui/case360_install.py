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
    muted("Case Finder keeps your Search, Lists, SQL and settings. The beta uses its own "
          "saved requests and your work account.")
    status = ui.label("Open your installed beta, or install the private pilot download.")
    status.props('role="status" aria-live="polite"')

    async def open_installed() -> None:
        toggle(False)
        status.text = "Checking the installed beta…"
        try:
            root = await asyncio.to_thread(delivery.selected)
            if root is None:
                status.text = "Get the pilot ZIP from the pilot owner, then select Install beta."
                return
            await asyncio.to_thread(delivery.open_beta, root)
            status.text = "The beta window is opening. Complete the two setup steps there."
        except (OSError, ValueError, KeyError):
            status.text = "The installed beta could not open. Install the current pilot ZIP again."
        finally:
            toggle(True)

    async def install() -> None:
        if app.native.main_window is None:
            status.text = "Open the Case Finder desktop app to choose a pilot ZIP, or use the " \
                "installer included in your download."
            return
        files = await app.native.main_window.create_file_dialog(
            allow_multiple=False, file_types=("Case Finder Beta (*.zip)",))
        if not files:
            return
        toggle(False)
        status.text = "Checking and installing the beta. This can take a few minutes…"
        try:
            await asyncio.to_thread(delivery.install_archive, Path(files[0]))
            status.text = "Beta installed. Close any older beta window, then select Open beta. " \
                "Your requests and settings are preserved."
        except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile, tarfile.TarError):
            status.text = "Installation could not finish. Check that you selected the original " \
                "pilot ZIP for this computer. Your saved work has not been removed."
        finally:
            toggle(True)

    with ui.row():
        open_button = primary("Open beta", open_installed)
        install_button = secondary("Install beta or update beta", install)

    def toggle(enabled: bool) -> None:
        open_button.set_enabled(enabled)
        install_button.set_enabled(enabled)

    muted("Use the private ZIP supplied by the pilot owner. Updating Case Finder makes this "
          "option available; the ZIP includes the beta's tools and documentation.")
