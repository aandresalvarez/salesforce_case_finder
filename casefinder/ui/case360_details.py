"""Page large evidence records without discarding their complete contents."""
from __future__ import annotations

import json

from nicegui import ui

PAGE_CHARS = 12_000


def render_json(value: object, filename: str = "case360-details.json") -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    pages = max(1, (len(text) + PAGE_CHARS - 1) // PAGE_CHARS)
    page = 0
    code = ui.code(text[:PAGE_CHARS], language="json").classes("w-full")
    if pages == 1:
        return
    status = ui.label("")
    ui.label("Large record shown in pages. Download retains the complete JSON.")

    def show(offset: int) -> None:
        nonlocal page
        page = max(0, min(pages - 1, page + offset))
        code.content = text[page * PAGE_CHARS:(page + 1) * PAGE_CHARS]
        status.text = f"Page {page + 1} of {pages}"
        previous.set_enabled(page > 0)
        following.set_enabled(page + 1 < pages)

    with ui.row():
        previous = ui.button("Previous page", on_click=lambda: show(-1))
        following = ui.button("Next page", on_click=lambda: show(1))
        ui.button("Download complete JSON", on_click=lambda: ui.download(
            text.encode("utf-8"), filename, media_type="application/json"))
    show(0)
