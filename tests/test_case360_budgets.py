"""Lifetime budgets keep usage across account changes, erasure and upgrades."""

import json
import sqlite3

import pytest

from casefinder.case360 import budgets


def test_defaults_settings_and_independent_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE360_DATA_ROOT", str(tmp_path))
    assert budgets.ensure("one@example.edu") == {
        "total_usd": 500,
        "request_usd": 50,
        "used_usd": 0,
        "remaining_usd": 500,
    }
    budgets.save("one@example.edu", 700, 25)
    assert budgets.ensure("ONE@example.edu")["total_usd"] == 700
    assert budgets.ensure("two@example.edu")["total_usd"] == 500
    budgets.save("one@example.edu", 700, 0)
    assert budgets.ensure("one@example.edu")["request_usd"] == 0
    for total, request in [(float("nan"), 1), (1, 2), (-1, 0), (500, float("inf"))]:
        with pytest.raises(ValueError):
            budgets.save("one@example.edu", total, request)


def test_history_import_deduplicates_resumes_and_retains_erased_accounting(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE360_DATA_ROOT", str(tmp_path))
    installation = tmp_path / "installations/old-release"
    run = installation / "runs/request-1"
    (run / "evidence").mkdir(parents=True)
    (run / "execution").mkdir()
    (run / "attempts/one").mkdir(parents=True)
    (installation / "context.json").write_text(json.dumps({"runs_root": str(run.parent)}))
    (run / "evidence/authorization.json").write_text(json.dumps({"principal": "one@example.edu"}))
    row = {
        "session_id": "s",
        "body_sha256": "a" * 64,
        "at": "now",
        "attempt": 1,
        "charge_pico": 30 * 10**12,
        "charge_basis": "full_reservation_uncertain",
    }
    (run / "execution/case_state.json").write_text(json.dumps({"ledger": [row]}))
    row.update(charge_pico=4 * 10**12, charge_basis="provider_usage_before_credit")
    (run / "attempts/one/case_state.json").write_text(json.dumps({"ledger": [row]}))
    db = sqlite3.connect(run.parent / "controller.sqlite")
    db.execute("CREATE TABLE accounting(data TEXT)")
    db.execute(
        "INSERT INTO accounting VALUES(?)",
        (
            json.dumps(
                {
                    "approval": {"principal_sha256": budgets.account_key("one@example.edu")},
                    "ledger": [dict(row, id="erased-call", charge_pico=2 * 10**12)],
                }
            ),
        ),
    )
    db.commit()
    db.close()
    assert budgets.ensure("one@example.edu")["used_usd"] == 6
    assert budgets.ensure("one@example.edu")["used_usd"] == 6
    with pytest.raises(ValueError, match="already charged"):
        budgets.save("one@example.edu", 5, 1)
    # Reopening another release or clearing clinical content does not reset usage.
    import shutil

    shutil.rmtree(installation)
    assert budgets.ensure("one@example.edu")["remaining_usd"] == 494
    assert budgets.ensure("two@example.edu")["used_usd"] == 0
