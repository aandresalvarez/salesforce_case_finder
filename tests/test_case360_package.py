"""Private installs preserve old evidence and refuse modified payloads."""
import hashlib
import json

import pytest

from casefinder.case360 import package


def release(root, version="synthetic-v1"):
    root.mkdir()
    (root / "build.json").write_text("{}")
    value = {"schema": "case360_private_release/1", "channel": "private-beta",
             "protocol": "case360.desktop/1", "release_id": version,
             "files": {"build.json": hashlib.sha256(b"{}").hexdigest()}}
    raw = json.dumps(value).encode()
    (root / "release.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def test_side_by_side_update_and_rollback_keep_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE360_DATA_ROOT", str(tmp_path / "private"))
    first = tmp_path / "first"
    one = package.install(first, release(first))
    package.activate(one)
    context = package.context_for(one, package.verify(one))
    run = context.parent / "runs" / "synthetic-request.json"
    run.parent.mkdir()
    run.write_text("Synthetic saved work")
    second = tmp_path / "second"
    two = package.install(second, release(second, "synthetic-v2"))
    package.activate(two)
    assert run.read_text() == "Synthetic saved work"
    package.activate(one)
    assert json.loads((tmp_path / "private/active-release.json").read_text())["root"] == str(one)
    assert len(package.installed()) == 2
    assert json.loads(context.read_text())["authorization_policy"]["live_enabled"] is False


@pytest.mark.parametrize("mutation", ["modified", "added", "symlink", "wrong_digest"])
def test_package_tampering_is_refused(tmp_path, mutation):
    root = tmp_path / "release"
    expected = release(root)
    if mutation == "modified":
        (root / "build.json").write_text("changed")
    elif mutation == "added":
        (root / "unreviewed.txt").write_text("extra")
    elif mutation == "symlink":
        (root / "escape").symlink_to(tmp_path)
    else:
        expected = "0" * 64
    with pytest.raises(ValueError):
        package.verify(root, expected)


def test_connection_settings_are_explicit_and_do_not_authorize_a_run(tmp_path):
    from synthetic import REQUESTER_EMAIL

    context = tmp_path / "context.json"
    context.write_text(json.dumps({"schema": "case360_runtime_context/1"}))
    package.configure(context, "a" * 64, REQUESTER_EMAIL, 5, "b" * 64)
    saved = json.loads(context.read_text())
    assert saved["authorization_policy"]["expected_principal"] == REQUESTER_EMAIL
    assert "run_id" not in saved
    with pytest.raises(ValueError):
        package.configure(context, "", REQUESTER_EMAIL, 5, "b" * 64)
    package.configure(context, "a" * 64, "", 0, "")
    assert json.loads(context.read_text())["authorization_policy"]["live_enabled"] is False
