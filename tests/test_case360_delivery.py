"""Optional wheel entry and native package updates preserve existing work."""
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from casefinder import config
from casefinder.case360 import delivery, package, platforms


def download(folder, release_id="test-v1", platform="darwin-arm64"):
    files = {"build.json": b"{}", "python/placeholder": b"synthetic"}
    manifest = {"schema": "case360_private_release/1", "channel": "private-beta",
                "protocol": "case360.desktop/1", "release_id": release_id,
                "platform": platform, "files": {k: hashlib.sha256(v).hexdigest()
                                                for k, v in files.items()}}
    raw = json.dumps(manifest).encode()
    metadata = {"schema": "case360_wheel_installer/1", "platform": platform,
                "wheel": "casefinder.whl", "wheel_sha256": hashlib.sha256(b"wheel").hexdigest(),
                "manifest_sha256": hashlib.sha256(raw).hexdigest()}
    path = folder / (release_id + ".zip")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("pilot/installer.json", json.dumps(metadata))
        archive.writestr("pilot/casefinder.whl", b"wheel")
        archive.writestr("pilot/runtime/release.json", raw)
        for name, content in files.items():
            archive.writestr("pilot/runtime/" + name, content)
    return path


def test_wheel_offers_beta_without_enabling_runtime():
    assert config.CASE360_AVAILABLE
    assert not config.PRIVATE_BETA


def test_regular_wheel_beta_route_preserves_navigation_without_cloud_probe(render, monkeypatch):
    from casefinder import main

    monkeypatch.setattr(config, "CASE360_ENABLED", False)
    monkeypatch.setattr(main, "gated", lambda *_: pytest.fail("Installation must stay local"))
    tree = render(main.case360_route)
    assert all(label in tree.text for label in ["Search", "Lists", "SQL", "Settings"])
    assert "Install beta or update beta" in tree.button_labels()
    assert "Open beta" in tree.button_labels()
    assert "Maximum authorized budget" not in tree.text


def test_install_and_update_leave_existing_requests_and_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE360_DATA_ROOT", str(tmp_path / "private"))
    monkeypatch.setattr(platforms, "target", lambda: "darwin-arm64")
    first = delivery.install_archive(download(tmp_path))
    context = package.context_for(first, package.verify(first))
    value = json.loads(context.read_text())
    value.update(google_account="synthetic@example.edu", google_credentials="synthetic",
                 tester_budget_file="synthetic-budget.sqlite")
    context.write_text(json.dumps(value))
    request = context.parent / "runs/saved.json"
    request.parent.mkdir()
    request.write_text('{"answer":"Distinct patients"}')
    old_context = context.read_bytes()
    second = delivery.install_archive(download(tmp_path, "test-v2"))
    assert delivery.selected() == second
    assert context.read_bytes() == old_context
    assert request.read_text() == '{"answer":"Distinct patients"}'
    new_context = json.loads(package.context_for(second, package.verify(second)).read_text())
    assert new_context["google_account"] == value["google_account"]
    assert new_context["tester_budget_file"] == value["tester_budget_file"]
    assert first.exists()


def test_wrong_platform_refused_before_activation(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE360_DATA_ROOT", str(tmp_path / "private"))
    monkeypatch.setattr(platforms, "target", lambda: "windows-x64")
    with pytest.raises(ValueError, match="operating system"):
        delivery.install_archive(download(tmp_path))
    assert not (tmp_path / "private/active-release.json").exists()


def test_changed_payload_and_traversal_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE360_DATA_ROOT", str(tmp_path / "private"))
    monkeypatch.setattr(platforms, "target", lambda: "darwin-arm64")
    archive = download(tmp_path)
    with zipfile.ZipFile(archive, "a") as opened:
        opened.writestr("pilot/runtime/unlisted.py", "unexpected")
    with pytest.raises(ValueError, match="inventory"):
        delivery.install_archive(archive)
    with zipfile.ZipFile(archive, "a") as opened:
        opened.writestr("../../escape", "outside")
    with pytest.raises(ValueError, match="invalid file path"):
        delivery.install_archive(archive)


def test_windows_uses_bundled_python_for_google_without_shell():
    root = Path("C:/Synthetic path & space/runtime")
    command = platforms.google_command(root, windows=True)
    assert command == [str(root / "python/python.exe"), "-B",
                       str(root / "google-cloud-sdk/lib/gcloud.py")]
    assert platforms.node_path(root, windows=True) == root / "node/node.exe"


def test_dependency_alias_survives_relocation(tmp_path):
    source = tmp_path / "source"
    (source / "engine/pi_harness/node_modules").mkdir(parents=True)
    (source / "engine/pi_harness/node_modules/module.js").write_text("synthetic")
    links = {"engine/node_modules": "pi_harness/node_modules"}
    platforms.restore_links(source, links)
    target = tmp_path / "target"
    platforms.copy_payload(source, target, links)
    assert (target / "engine/node_modules").resolve() == target / "engine/pi_harness/node_modules"
    assert len(list(platforms.payload_files(target))) == 2
