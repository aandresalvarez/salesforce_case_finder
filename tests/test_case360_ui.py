"""Synthetic presentation only: completion and quality remain independent."""

from casefinder import config, main
from casefinder.ui import case360_page
from casefinder.ui.shell import rail


def test_demo_has_explicit_prepare_confirm_start(render):
    tree = render(case360_page.render)
    assert "Prepare synthetic request" in tree.button_labels()
    assert "Confirm contract" in tree.button_labels()
    assert "Run synthetic demonstration" in tree.button_labels()
    assert "No credentials or paid calls" in tree.text
    assert "Run query" not in tree.button_labels()


def test_completed_hold_does_not_appear_approved(render):
    tree = render(lambda: case360_page.render_result({"execution_status": "COMPLETED",
        "quality_status": "HOLD", "real_provider_calls": 0,
        "pending_decisions": [{"question": "Which follow-up window?"}]}))
    assert "Execution: COMPLETED" in tree.text
    assert "Quality: HOLD" in tree.text
    assert "Which follow-up window?" in tree.text
    assert "Run query" not in tree.button_labels()


def test_beta_navigation_is_optional(render, monkeypatch):
    monkeypatch.setattr(config, "CASE360_ENABLED", False)
    assert "Case 360 Beta" not in render(lambda: rail("search")).text
    monkeypatch.setattr(config, "CASE360_ENABLED", True)
    assert "Case 360 Beta" in render(lambda: rail("case360")).text


def test_demo_route_does_not_probe_bigquery(render, monkeypatch):
    monkeypatch.setattr(config, "CASE360_ENABLED", True)
    tree = render(main.case360_route)
    assert "Offline preview" in tree.text
