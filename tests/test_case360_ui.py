"""Synthetic presentation only: completion and quality remain independent."""

from casefinder import config, main
from casefinder.ui import case360_page
from casefinder.ui.shell import connection_screen, rail


def test_demo_has_explicit_prepare_confirm_start(render):
    tree = render(case360_page.render_demo)
    assert "Prepare synthetic request" in tree.button_labels()
    assert "Confirm contract" in tree.button_labels()
    assert "Run synthetic demonstration" in tree.button_labels()
    assert "No credentials or paid calls" in tree.text
    assert "Run query" not in tree.button_labels()


def test_completed_hold_does_not_appear_approved(render):
    tree = render(lambda: case360_page.render_result({"execution_status": "COMPLETED",
        "quality_status": "HOLD", "real_provider_calls": 0, "stop_reason": "PENDING_CRITERIA",
        "pending_decisions": [{"question": "Which follow-up window?"}]}))
    assert "Execution: COMPLETED" in tree.text
    assert "Quality: HOLD" in tree.text
    assert "Which follow-up window?" in tree.text
    assert "Stopped: PENDING_CRITERIA" in tree.text
    assert "Run query" not in tree.button_labels()


def test_beta_navigation_is_optional(render, monkeypatch):
    monkeypatch.setattr(config, "CASE360_ENABLED", False)
    assert "Case 360 Beta" not in render(lambda: rail("search")).text
    monkeypatch.setattr(config, "CASE360_ENABLED", True)
    assert "Case 360 Beta" in render(lambda: rail("case360")).text
    gate = render(connection_screen, "Synthetic offline account")
    assert any(link.text == "Open Case 360 Beta" and link._props.get("href") == "/case360"
               for link in gate.of_type("Link"))


def test_demo_route_does_not_probe_bigquery(render, monkeypatch):
    monkeypatch.setattr(config, "CASE360_ENABLED", True)
    tree = render(main.case360_route)
    assert "What data do you need?" in tree.text
    assert "Prepare request" not in tree.button_labels()


def test_request_form_preserves_explicit_centers_and_cannot_run_live(render):
    tree = render(case360_page.render_preparation)
    assert "Prepare request" in tree.button_labels()
    assert "Confirm request contract" in tree.button_labels()
    assert "New request" in tree.button_labels()
    assert "Run query" not in tree.button_labels()
    assert "Run" not in tree.button_labels()
    assert tree.of_type("Select")[0].value == ["SHC", "LPCH"]
    assert "unbound string lists" in tree.text
    confirm = next(b for b in tree.buttons() if b.text == "Confirm request contract")
    assert not confirm.enabled


def test_request_edit_invalidates_confirmation(render):
    tree = render(case360_page.render_preparation)
    confirm = next(b for b in tree.buttons() if b.text == "Confirm request contract")
    confirm.enable()
    with tree.client:
        tree.of_type("Textarea")[0].value = "Return synthetic surgery information."
    assert not confirm.enabled
    assert "Prepare a new revision" in tree.text


def test_prepare_confirm_and_revision_use_the_private_protocol(render, monkeypatch):
    import asyncio

    class Client:
        def __init__(self):
            self.calls = []
            self.revision = 0

        async def request(self, method, params, **kwargs):
            self.calls.append((method, params, kwargs))
            if method == "prepare_request":
                self.revision += 1
                return {"run_id": f"run-{self.revision}", "revision": self.revision,
                        "contract_sha256": "a" * 64, "artifact": {"artifact_id": "result"}}
            return {"confirmed": True}

        async def artifact(self, run_id, reference):
            return {"contract": {"pending_decisions": ["Synthetic pending criteria"]},
                    "resources": {"status": "NOT_CONFIGURED"}, "source_evidence": None,
                    "evidence_alignment": {}, "execution_plan": {"max_paid_usd": 0}}

    client = Client()
    monkeypatch.setattr(case360_page.session, "client", lambda: client)
    tree = render(case360_page.render_preparation)
    buttons = {b.text: b for b in tree.buttons()}
    text = tree.of_type("Textarea")[0]

    async def click(label):
        tree.press(buttons[label])
        await asyncio.sleep(0)

    async def check():
        from nicegui import core

        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        with tree.client:
            text.value = "Return synthetic orders ages 1 through 18 inclusive."
        await click("Prepare request")
        assert buttons["Confirm request contract"].enabled
        assert "Synthetic pending criteria" in tree.text
        await click("Confirm request contract")
        assert "Check the configured connection" in tree.text
        with tree.client:
            text.value = "Return synthetic surgery information."
        assert not buttons["Confirm request contract"].enabled
        await click("Prepare request")
        assert client.calls[-1][1]["previous_run_id"] == "run-1"
        assert client.calls[0][1]["centers"] == ["SHC", "LPCH"]
        assert client.calls[1][1]["contract_sha256"] == "a" * 64
        assert all(call[0] != "start_run" for call in client.calls)

    asyncio.run(check())


def test_paid_request_requires_connection_budget_approval_and_separate_start(render, monkeypatch):
    import asyncio

    from synthetic import REQUESTER_EMAIL

    class Client:
        def __init__(self):
            self.calls = []

        async def request(self, method, params=None, **kwargs):
            self.calls.append((method, params, kwargs))
            if method == "prepare_request":
                return {"run_id": "run-synthetic", "revision": 1,
                        "contract_sha256": "a" * 64, "artifact": {"artifact_id": "result"}}
            if method == "probe_run":
                return {"principal": REQUESTER_EMAIL, "max_paid_usd": 5, "sha256": "b" * 64}
            if method == "start_run":
                return {"execution_status": "COMPLETED", "artifact": {"artifact_id": "result"}}
            return {"authorized": method == "authorize_run", "confirmed": True}

        async def artifact(self, run_id, reference):
            if any(call[0] == "start_run" for call in self.calls):
                return {"mode": "request", "execution_status": "COMPLETED",
                        "quality_status": "HOLD", "real_provider_calls": 0}
            return {"contract": {}, "resources": {}, "source_evidence": {},
                    "evidence_alignment": {}, "execution_plan": {}}

    client = Client()
    monkeypatch.setattr(case360_page.session, "client", lambda: client)
    tree = render(case360_page.render_preparation)
    buttons = {b.text: b for b in tree.buttons()}

    async def click(label):
        tree.press(buttons[label])
        await asyncio.sleep(0)

    async def check():
        from nicegui import core

        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        assert not buttons["Check connection"].enabled
        assert not buttons["Authorize this budget"].enabled
        assert not buttons["Start authorized request"].enabled
        with tree.client:
            tree.of_type("Textarea")[0].value = "Return synthetic payer information."
        await click("Prepare request")
        await click("Confirm request contract")
        assert buttons["Check connection"].enabled
        assert not buttons["Start authorized request"].enabled
        await click("Check connection")
        assert REQUESTER_EMAIL in tree.text
        assert buttons["Authorize this budget"].enabled
        assert not buttons["Start authorized request"].enabled
        with tree.client:
            tree.of_type("Number")[0].value = 1.25
        await click("Authorize this budget")
        assert client.calls[-1][1] == {"contract_sha256": "a" * 64,
                                      "preflight_sha256": "b" * 64, "cap_usd": 1.25}
        assert not tree.of_type("Number")[0].enabled
        assert buttons["Start authorized request"].enabled
        assert not any(call[0] == "start_run" for call in client.calls)
        await click("Start authorized request")
        assert "Execution: COMPLETED" in tree.text
        assert "Quality: HOLD" in tree.text
        assert "Synthetic evidence and responses" not in tree.text
        with tree.client:
            tree.of_type("Textarea")[0].value = "Changed synthetic request."
        assert not buttons["Start authorized request"].enabled
        assert not buttons["Authorize this budget"].enabled

    asyncio.run(check())
