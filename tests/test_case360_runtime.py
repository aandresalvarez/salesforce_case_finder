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


def test_explicit_context_does_not_inherit_legacy_overrides(tmp_path, monkeypatch):
    import json

    context = tmp_path / "context.json"
    context.write_text(json.dumps({"schema": "case360_runtime_context/1",
        "engine_root": str(tmp_path / "engine"), "runs_root": str(tmp_path / "runs"),
        "node_executable": str(tmp_path / "node")}))
    monkeypatch.setenv("CASE360_RUNTIME_CONTEXT", str(context))
    monkeypatch.setenv("CASE360_ENGINE_ROOT", "unrelated-legacy-root")
    monkeypatch.setenv("CASE360_NODE", "unrelated-legacy-node")
    runtime = discover()
    assert runtime.context_file == context
    assert runtime.engine_root == tmp_path / "engine"
    assert runtime.node == str(tmp_path / "node")


def test_context_requires_absolute_paths(tmp_path, monkeypatch):
    context = tmp_path / "context.json"
    context.write_text('{"schema":"case360_runtime_context/1","engine_root":"relative"}')
    monkeypatch.setenv("CASE360_RUNTIME_CONTEXT", str(context))
    with pytest.raises(RuntimeError, match="absolute"):
        discover()
