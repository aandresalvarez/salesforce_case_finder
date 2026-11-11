"""Large synthetic evidence stays readable without a huge native WebKit message."""
import json

from nicegui import ui

from casefinder.ui.case360_details import PAGE_CHARS, render_json


def test_large_evidence_pages_preserve_every_character_and_complete_download(render, monkeypatch):
    value = {"description": "Synthetic documentación λ " * 1400, "tail": "FINAL DETAIL"}
    full = json.dumps(value, ensure_ascii=False, indent=2)
    downloaded = []
    monkeypatch.setattr(ui, "download", lambda *args, **kwargs: downloaded.append((args, kwargs)))
    tree = render(lambda: render_json(value, "synthetic-evidence.json"))
    code = tree.of_type("Code")[0]
    buttons = {button.text: button for button in tree.buttons()}
    pieces = [code.content]
    for _ in range(1, (len(full) + PAGE_CHARS - 1) // PAGE_CHARS):
        tree.press(buttons["Next page"])
        pieces.append(code.content)
    assert all(len(piece) <= PAGE_CHARS for piece in pieces)
    assert "".join(pieces) == full
    assert "FINAL DETAIL" in code.content
    tree.press(buttons["Previous page"])
    assert code.content == pieces[-2]
    tree.press(buttons["Download complete JSON"])
    assert json.loads(downloaded[0][0][0]) == value
    assert downloaded[0][0][1] == "synthetic-evidence.json"
    assert downloaded[0][1]["media_type"] == "application/json"


def test_small_records_need_no_paging_controls(render):
    value = {"pending": ["Synthetic unresolved decision"]}
    tree = render(lambda: render_json(value))
    assert json.loads(tree.of_type("Code")[0].content) == value
    assert "Next page" not in tree.button_labels()
