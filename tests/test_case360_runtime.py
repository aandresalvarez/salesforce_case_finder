from pathlib import Path

import pytest

from casefinder.case360.runtime import Runtime, discover


def test_runtime_uses_argument_list_and_isolates_environment(tmp_path, monkeypatch):
    (tmp_path / "desktop_bridge").mkdir()
    (tmp_path / "desktop_bridge/worker.mjs").touch()
    loader = tmp_path / "pi_harness/node_modules/tsx/dist/loader.mjs"
    loader.parent.mkdir(parents=True)
    loader.touch()
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "synthetic-secret-file")
    monkeypatch.setenv("CASEFINDER_VERTEX_MODEL", "synthetic-ask-model")
    runtime = Runtime(tmp_path, tmp_path / "run space", "node")
    assert runtime.command()[-1] == str(tmp_path / "run space")
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in runtime.environment()
    assert "CASEFINDER_VERTEX_MODEL" not in runtime.environment()


def test_inherited_node_options_are_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("NODE_OPTIONS", "--require synthetic.js")
    with pytest.raises(RuntimeError, match="NODE_OPTIONS"):
        Runtime(tmp_path, tmp_path, "node").command()


def test_missing_runtime_is_actionable(monkeypatch):
    monkeypatch.delenv("CASE360_ENGINE_ROOT", raising=False)
    with pytest.raises(RuntimeError, match="runtime location"):
        discover()


def test_runtime_paths_remain_local(tmp_path):
    with pytest.raises(FileNotFoundError):
        Runtime(Path(tmp_path / "missing"), tmp_path, "node").command()
