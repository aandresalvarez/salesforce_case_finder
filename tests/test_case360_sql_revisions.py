"""Synthetic offline review: parent binding, no inherited checks, local startup."""
import hashlib

import pytest

from casefinder.ui.case360_sql_revisions import verified_revisions


def fixture():
    ref = {"sha256": "a" * 64}
    result = {"packages": [{"package_sha256": "b" * 64}], "validations": ["old PASS"]}
    record = {"schema": "case360_sql_review_revision/1", "revision": 1, "sql": "SELECT 2",
              "sql_sha256": hashlib.sha256(b"SELECT 2").hexdigest(),
              "execution_status": "NOT_EXECUTED", "dry_run_status": "NOT_RUN",
              "inherited_validation": False,
              "parent": {"artifact_sha256": ref["sha256"], "package_sha256": "b" * 64}}
    return {"schema": "case360_sql_review_history/1", "records": [record]}, result, ref


def test_revisions_are_bound_to_the_original_result():
    history, result, ref = fixture()
    assert len(verified_revisions(history, result, ref)) == 1
    assert verified_revisions(history, result, {"sha256": "c" * 64}) == []
    assert result["validations"] == ["old PASS"]


@pytest.mark.parametrize("change", [{"sql": "changed"}, {"inherited_validation": True},
                                    {"execution_status": "COMPLETED"},
                                    {"dry_run_status": "PASS"}])
def test_unverified_or_falsely_validated_revision_is_rejected(change):
    history, result, ref = fixture()
    history["records"][0].update(change)
    with pytest.raises(ValueError):
        verified_revisions(history, result, ref)


def test_review_launch_skips_search_but_preserves_navigation(monkeypatch):
    from casefinder import main

    actions = []
    monkeypatch.setattr(main.config, "CASE360_ENABLED", True)
    monkeypatch.setattr(main, "_review_pending", True)
    monkeypatch.setattr(main.ui.navigate, "to", lambda url: actions.append(url))
    monkeypatch.setattr(main, "gated", lambda name, render: actions.append(name))
    main.index()
    assert actions == ["/case360/review"]
    main.index()
    assert actions == ["/case360/review", "search"]
