"""Synthetic offline review: parent binding, no inherited checks, local startup."""
import hashlib

import pytest

from casefinder.ui.case360_sql_revisions import matching_validation, verified_revisions


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


def saved_check(record):
    request = {"configuration": {"dryRun": True, "query": {"query": record["sql"]}}}
    return {"schema": "case360_sql_validation_history/1", "records": [{
        "sequence": 1, "run_id": record.get("run_id"), "revision": record["revision"],
        "sql_sha256": record["sql_sha256"], "executed_queries": 0, "clinical_approval": False,
        "status": "PASS", "results": [{"sql_sha256": record["sql_sha256"], "request": request,
            "status": "PASS", "http_status": 200, "response": {"configuration": {"dryRun": True},
                "statistics": {"totalBytesProcessed": "100"}}}]}]}


def test_later_dry_run_overrides_display_without_rewriting_original():
    history, _, _ = fixture()
    record = history["records"][0]
    assert matching_validation(record, None) is None
    assert matching_validation(record, saved_check(record))["status"] == "PASS"
    assert record["dry_run_status"] == "NOT_RUN"


def test_dry_run_for_other_sql_never_applies_to_this_version():
    history, _, _ = fixture()
    record = history["records"][0]
    checked = saved_check(record)
    checked["records"][0]["results"][0]["sql_sha256"] = "e" * 64
    assert matching_validation(record, checked) is None


@pytest.mark.parametrize("change", ["not_dry", "mismatched_sql", "missing_response", "failed"])
def test_ui_rejects_forged_or_incomplete_passing_check(change):
    history, _, _ = fixture()
    record = history["records"][0]
    checked = saved_check(record)
    item = checked["records"][0]["results"][0]
    if change == "not_dry":
        item["request"]["configuration"]["dryRun"] = False
    elif change == "mismatched_sql":
        item["request"]["configuration"]["query"]["query"] = "SELECT 9"
    elif change == "missing_response":
        item["response"] = {}
    else:
        item["status"] = "FAILED"
    with pytest.raises(ValueError):
        matching_validation(record, checked)


def test_membership_question_requires_a_deliberate_choice_and_saves_its_index(render, monkeypatch):
    import asyncio
    from nicegui import core
    from casefinder.ui.case360_sql_revisions import render_membership_questions

    submitted = []

    async def submit(answers):
        submitted.append(answers)

    check = {"questions": [{"id": "boundary", "question": "Count a visit on the end date?",
                            "example": "A participant visits on the last day.",
                            "options": ["Include the last day.", "Exclude the last day."],
                            "option": None, "conflict": False}]}

    async def exercise():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        tree = render(render_membership_questions, check, submit)
        radio, = tree.of_type("Radio")
        assert radio.value is None
        button, = tree.buttons()
        tree.press(button)
        await asyncio.sleep(0)
        assert not submitted and "Choose an answer" in tree.text
        with tree.client:
            radio.value = 0
        tree.press(button)
        await asyncio.sleep(0)
        assert submitted == [[{"id": "boundary", "option": 0}]]

    asyncio.run(exercise())
