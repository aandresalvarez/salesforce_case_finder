"""Analyst setup is an app workflow, not a compiled identity or a remote probe."""
import asyncio
import json
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


def test_resource_settings_reload_saved_policy_and_locations(render, tmp_path, monkeypatch):
    from casefinder.case360.runtime import Runtime

    version = "a" * 64
    folder = tmp_path / "resources" / version
    folder.mkdir(parents=True)
    for name in ("profile.json", "metadata.json", "epic.json", "starr.json"):
        (folder / name).write_text("{}")
    context = tmp_path / "context.json"
    context.write_text(json.dumps({"source_profile": version, "resource_root": str(folder.parent),
        "authorization_policy": {"max_paid_usd": 50, "expected_principal": "analyst@example.edu",
                                 "route_verification_sha256": "b" * 64}}))
    monkeypatch.setattr("casefinder.case360.runtime.discover",
                        lambda: Runtime(tmp_path, tmp_path, "node", context))
    tree = render(render_setup)
    inputs = {field.props["label"]: field.value for field in tree.of_type("Input", "Number")}
    assert inputs["Expected Google account"] == "analyst@example.edu"
    assert inputs["Maximum authorized budget in USD (0 disables live)"] == 50
    assert inputs["Resource snapshot SHA256"] == version
    assert inputs["Verified route proof SHA256"] == "b" * 64
    assert inputs["Epic documentation index JSON (optional)"] == str(folder / "epic.json")
    assert inputs["Prepared STARR repository index JSON (optional)"] == str(folder / "starr.json")
