"""User decisions through real NiceGUI callbacks; no private runtime or data."""
import asyncio
from unittest.mock import AsyncMock

from casefinder.case360 import session
from casefinder.ui import case360_close, case360_history


class SyntheticClient:
    def __init__(self):
        self.calls = []
        self.rows = [{"run_id": "run-synthetic", "revision": 1, "execution_status": "DRAFT",
                      "process_active": False, "created_at": "synthetic", "mode": "request"}]
        self.quiescing = False
        self.closed = False

    async def request(self, method, params=None, **kwargs):
        self.calls.append((method, params, kwargs))
        if method == "list_runs":
            return {"runs": self.rows.copy(), "total": len(self.rows)}
        if method == "prepare_cleanup":
            return {"id": "cleanup-synthetic", "plan_sha256": "a" * 64,
                    "runs": [{"run_id": "run-synthetic", "inventory": {"files": 3, "bytes": 42},
                              "blocked": None}], "resources": []}
        if method == "cleanup_data":
            self.rows.clear()
            return {"status": "PARTIAL", "results": [
                {"id": "run-synthetic", "status": "DELETED"},
                {"id": "snapshot-synthetic", "status": "BLOCKED", "code": "FILESYSTEM_ERROR"}]}
        if method == "cancel_run":
            self.rows[0]["process_active"] = False
            self.rows[0]["execution_status"] = "INTERRUPTED"
        return {}

    async def close(self):
        self.closed = True


def test_history_previews_and_cancels_without_erasing(render, monkeypatch):
    client = SyntheticClient()
    monkeypatch.setattr(session, "client", lambda: client)
    tree = render(case360_history.render_history)

    async def check():
        from nicegui import core

        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        tree.press(next(b for b in tree.buttons() if b.text == "Refresh history"))
        await asyncio.sleep(0)
        with tree.client:
            tree.of_type("Select")[0].value = ["run-synthetic"]
        tree.press(next(b for b in tree.buttons() if b.text == "Limpiar datos"))
        await asyncio.sleep(0)
        assert "Confirmar limpieza de datos" in tree.text
        assert "3 files · 42 bytes" in tree.text
        tree.press(next(b for b in tree.buttons() if b.text == "Cancelar"))
        await asyncio.sleep(0)
        assert not any(c[0] == "cleanup_data" for c in client.calls)
        assert client.rows

    asyncio.run(check())


def test_confirmation_uses_preview_scope_and_reports_partial_cleanup(render, monkeypatch):
    client = SyntheticClient()
    monkeypatch.setattr(session, "client", lambda: client)
    cleared = []
    tree = render(lambda: case360_history.render_history(on_clear=lambda: cleared.append(True)))

    async def check():
        from nicegui import core

        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        with tree.client:
            tree.of_type("Checkbox")[0].value = True
        tree.press(next(b for b in tree.buttons() if b.text == "Limpiar datos"))
        await asyncio.sleep(0)
        assert client.calls[-1][1] == {
            "run_ids": [], "all_runs": True, "unused_resources": False}
        tree.press(next(b for b in tree.buttons() if b.text == "Confirmar limpieza"))
        await asyncio.sleep(0)
        call = next(c for c in client.calls if c[0] == "cleanup_data")
        assert call[1] == {"cleanup_id": "cleanup-synthetic", "plan_sha256": "a" * 64}
        assert "Cleanup: PARTIAL" in tree.text
        assert "FILESYSTEM_ERROR" in tree.text
        assert "uncertain reservations" in tree.text
        assert "Retry this cleanup" in tree.button_labels()
        assert cleared == [True]

    asyncio.run(check())


def test_stop_before_close_verifies_process_exit_and_blocks_new_actions(monkeypatch):
    client = SyntheticClient()
    client.rows[0].update(process_active=True, execution_status="RUNNING")
    monkeypatch.setattr(session, "_client", client)
    monkeypatch.setattr(session, "_closing", False)

    async def check():
        active = await session.begin_close()
        assert len(active) == 1 and client.quiescing
        import pytest

        with pytest.raises(RuntimeError):
            session.client()
        session.return_to_app()
        assert session.client() is client and not client.quiescing
        await session.begin_close()
        await session.stop_for_close()
        assert client.closed
        assert any(c[0] == "cancel_run" for c in client.calls)

    asyncio.run(check())


def test_unverified_exit_keeps_window_open_and_client_available(monkeypatch):
    client = SyntheticClient()
    client.rows[0].update(process_active=True, execution_status="INTERRUPTED")
    monkeypatch.setattr(session, "_client", client)
    monkeypatch.setattr(session, "_closing", False)

    async def check():
        import pytest

        await session.begin_close()
        with pytest.raises(RuntimeError, match="could not be verified"):
            await session.stop_for_close()
        assert not client.closed
        session.return_to_app()
        assert session.client() is client

    asyncio.run(check())


def test_reconnect_is_explicit_and_does_not_retry_a_command(monkeypatch):
    old = SyntheticClient()
    old.closed = True
    new = SyntheticClient()
    new.open = AsyncMock()
    monkeypatch.setattr(session, "_client", old)
    monkeypatch.setattr(session, "_closing", False)
    monkeypatch.setattr(session, "discover", lambda: "synthetic")
    monkeypatch.setattr(session, "Client", lambda runtime: new)
    assert asyncio.run(session.reconnect()) is new
    new.open.assert_awaited_once()
    assert new.calls == []


def test_close_dialog_return_does_not_cancel_work(render, monkeypatch):
    monkeypatch.setattr(session, "begin_close", AsyncMock(return_value=[{}]))
    stop = AsyncMock()
    monkeypatch.setattr(session, "stop_for_close", stop)
    returned = []
    monkeypatch.setattr(session, "return_to_app", lambda: returned.append(True))
    callbacks = {}
    monkeypatch.setattr(case360_close.ui, "on",
                        lambda name, handler: callbacks.update({name: handler}))
    tree = render(case360_close.install)

    async def check():
        with tree.client:
            await callbacks["case360-close-request"]()
        assert "Stop and close" in tree.button_labels()
        tree.press(next(b for b in tree.buttons() if b.text == "Return to app"))
        assert returned == [True]
        stop.assert_not_awaited()

    asyncio.run(check())


def test_reopened_draft_preserves_text_and_centers(render):
    from casefinder.ui.case360_page import render_preparation

    contract = {"sources": [{"id": "REQUEST", "excerpt": "Synthetic orders age 1 to 18."},
                            {"id": "CENTERS", "excerpt": "Requested centers: LPCH."}],
                "excluded_case_ids": ["SYNTHETIC"], "external_inputs": [{"name": "cohort_ids"}]}
    tree = render(lambda: render_preparation(previous_run="run-synthetic", draft=contract))
    assert tree.of_type("Textarea")[0].value == "Synthetic orders age 1 to 18."
    assert tree.of_type("Select")[0].value == ["LPCH"]
    assert not next(b for b in tree.buttons() if b.text == "Start authorized request").enabled
