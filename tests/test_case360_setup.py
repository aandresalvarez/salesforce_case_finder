"""Analyst setup is an app workflow, not a compiled identity or a remote probe."""
import asyncio
from unittest.mock import AsyncMock

from casefinder import config, main
from casefinder.case360 import preferences, session
from casefinder.ui.case360_setup import render_setup


def test_setup_saves_another_analyst_and_environment(render, tmp_path, monkeypatch):
    from synthetic import OWNER

    monkeypatch.setenv("CASE360_DATA_ROOT", str(tmp_path))
    prepare = AsyncMock()
    monkeypatch.setattr(session, "prepare_reconfigure", prepare)
    tree = render(render_setup)

    async def check():
        from nicegui import core

        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        with tree.client:
            fields = {field.props["label"]: field for field in tree.of_type("Input")}
            fields["Analyst label"].value = OWNER
            fields["Environment label"].value = "Isolated workstation"
        tree.press(next(b for b in tree.buttons() if b.text == "Save analyst settings"))
        await asyncio.sleep(0)
        assert prepare.await_count == 1
        assert preferences.read()["analyst"] == OWNER
        assert preferences.read()["environment"] == "Isolated workstation"

    asyncio.run(check())


def test_beta_home_and_settings_are_local_before_cloud_configuration(render, monkeypatch):
    monkeypatch.setattr(config, "PRIVATE_BETA", True)
    monkeypatch.setattr(config, "CASE360_ENABLED", True)
    monkeypatch.setattr(main, "gated", lambda *_: (_ for _ in ()).throw(
        AssertionError("A beta landing page must not make a cloud access probe")))
    assert "Offline preview" in render(main.index).text
    settings = render(main.settings_route)
    assert "Save analyst settings" in settings.button_labels()
    assert "Record and export pilot assessment" in settings.button_labels()
    assert "Activate selected version / rollback" in settings.button_labels()


def test_settings_refuse_switch_while_owned_work_is_active(monkeypatch):
    client = type("SyntheticClient", (), {"quiescing": False})()
    monkeypatch.setattr(session, "_client", client)
    monkeypatch.setattr(session, "history", AsyncMock(return_value=[{"process_active": True}]))
    closed = AsyncMock()
    monkeypatch.setattr(session, "stop_for_close", closed)

    async def check():
        try:
            await session.prepare_reconfigure()
        except RuntimeError as error:
            assert "Stop active work" in str(error)
        else:
            raise AssertionError("Active work was hidden by a configuration switch")
        assert not session._closing and not client.quiescing
        closed.assert_not_awaited()

    asyncio.run(check())
