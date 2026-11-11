"""Synthetic review delivery and per-installation configuration boundaries."""
import hashlib
import io
import json
import zipfile

import pytest

from casefinder.case360 import preferences
from casefinder.ui.case360_result import bundle_zip, requirement_rows


def test_missing_fields_and_centers_stay_visible():
    result = {"contract": {"sources": [{"id": "CENTERS", "excerpt": "SHC, LPCH"}],
                           "requirements": [{"id": "R1", "statement": "Synthetic fields"}]},
              "field_matrix": [{"requirement_id": "R1", "site": "shc", "field": "synthetic",
                                "status": "OBSERVED", "candidates": []}]}
    rows = requirement_rows(result)
    assert [(r["center"], r["status"]) for r in rows] == [
        ("SHC", "OBSERVED"), ("LPCH", "NOT_VERIFIED")]
    assert all(r["grain"] == "Unconfirmed" for r in rows)


def bundle():
    files = {"README.md": "Experimental HOLD", "pending.json": "[]", "provenance.json": "{}"}
    return {"schema": "case360_review_bundle/1", "files": files, "manifest": {
        key: {"sha256": hashlib.sha256(value.encode()).hexdigest(), "bytes": len(value.encode())}
        for key, value in files.items()}}


def test_export_zip_preserves_selected_content_and_manifest():
    value = bundle()
    with zipfile.ZipFile(io.BytesIO(bundle_zip(value))) as archive:
        assert set(archive.namelist()) == {*value["files"], "manifest.json"}
        assert json.loads(archive.read("manifest.json")) == value["manifest"]


@pytest.mark.parametrize("change", ["content", "pending", "path"])
def test_export_rejects_tampering_and_path_escape(change):
    value = bundle()
    if change == "content":
        value["files"]["README.md"] += "changed"
    elif change == "pending":
        del value["files"]["pending.json"]
    else:
        value["files"]["../outside"] = "x"
    with pytest.raises(ValueError):
        bundle_zip(value)


def test_analyst_and_environment_are_local_editable_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE360_DATA_ROOT", str(tmp_path))
    assert preferences.read() == {"analyst": "", "environment": "", "runtime_context": ""}
    preferences.save("Synthetic analyst", "Synthetic workstation", str(tmp_path / "runtime.json"))
    assert preferences.read()["environment"] == "Synthetic workstation"
    preferences.save("Another synthetic analyst", "Another environment", "")
    assert preferences.read()["analyst"] == "Another synthetic analyst"
    assert (tmp_path / "analyst-profile.json").stat().st_mode & 0o777 == 0o600


def test_profile_refuses_relative_runtime_and_linked_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE360_DATA_ROOT", str(tmp_path))
    with pytest.raises(ValueError):
        preferences.save("", "", "relative.json")
    (tmp_path / "analyst-profile.json").symlink_to(tmp_path / "outside.json")
    with pytest.raises(ValueError):
        preferences.save("", "", "")
