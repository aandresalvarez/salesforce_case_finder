"""Analyst flow through real NiceGUI elements; private transport is a synthetic double."""
import asyncio

from nicegui import core

from casefinder.ui import case360_conversation as flow


def test_landing_has_one_text_field_and_no_configuration(render, monkeypatch):
    monkeypatch.setattr(flow, "configured_cap", lambda: 50)
    tree = render(flow.render)
    assert len(tree.of_type("Textarea")) == 1
    assert not tree.of_type("Select")
    assert not tree.of_type("Number")
    assert "Beta settings" in tree.text
    assert "$50 USD" in tree.text
    assert "Prepare request" not in tree.button_labels()
    assert "Check connection" not in tree.button_labels()


def test_blank_request_is_explained_without_protocol_call(render, monkeypatch):
    monkeypatch.setattr(flow, "configured_cap", lambda: 50)
    monkeypatch.setattr(flow.session, "client", lambda: (_ for _ in ()).throw(
        AssertionError("Blank input must not start the controller")))
    tree = render(flow.render)

    async def check():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        with tree.client:
            tree.press(next(b for b in tree.buttons() if b.text == "Analyze request"))
            await asyncio.sleep(0)
        assert "Enter a request" in tree.text

    asyncio.run(check())


def test_answer_is_sent_with_question_id_and_remaining_budget(render, monkeypatch):
    class Client:
        def __init__(self):
            self.calls = []
            self.round = 0
            self.started = False

        def view(self):
            return {"run_id": f"run-{self.round}", "contract_sha256": "a" * 64,
                    "execution_status": "COMPLETED" if self.started else "DRAFT",
                    "artifact": {"artifact_id": "result", "sha256": "b" * 64}}

        async def request(self, method, params=None, **kwargs):
            self.calls.append((method, params, kwargs))
            if method == "prepare_conversation":
                self.round += 1
                self.started = False
            if method == "probe_run":
                return {"sha256": "c" * 64, "max_paid_usd": 50}
            if method == "start_run":
                self.started = True
            return self.view()

        async def artifact(self, run_id, reference):
            conversation = {"waiting": self.round == 1, "original_text": "Synthetic request"}
            if not self.started:
                return {"resources": {}, "source_evidence": {"sources": []}}
            return {"conversation": conversation, "execution_status": "COMPLETED",
                    "quality_status": "HOLD", "interpretation": "I need a date.",
                    "questions": [{"id": "intake-year", "text": "Which year?"}],
                    "budget": {"cap_usd": 50, "charged_or_reserved_usd": 1,
                               "remaining_usd": 49, "uncertain_reservation_usd": 0},
                    "packages": [] if self.round == 1 else [{"version": 1,
                        "package": {"cohort": {"sql": "SELECT 2024 AS requested_year"}}}]}

    client = Client()
    monkeypatch.setattr(flow.session, "client", lambda: client)
    monkeypatch.setattr(flow, "configured_cap", lambda: 50)
    monkeypatch.setattr(flow, "active_request", lambda *a, **kw: None)
    tree = render(flow.render)

    async def check():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        with tree.client:
            tree.of_type("Textarea")[0].value = "Synthetic request"
            tree.press(next(b for b in tree.buttons() if b.text == "Analyze request"))
            await asyncio.sleep(0)
            assert "Which year?" in tree.text
            assert not any("SELECT" in str(e._props) for e in tree.of_type("Code"))
            tree.of_type("Textarea")[-1].value = "2024"
            tree.press(next(b for b in tree.buttons() if b.text == "Continue with my answers"))
            await asyncio.sleep(0)
        prepares = [p for m, p, _ in client.calls if m == "prepare_conversation"]
        assert prepares == [
            {"text": "Synthetic request", "previous_run_id": None, "answers": []},
            {"text": "", "previous_run_id": "run-1",
             "answers": [{"question_id": "intake-year", "text": "2024"}]}]
        assert [p["cap_usd"] for m, p, _ in client.calls if m == "authorize_run"] == [50, 49]
        assert "SQL is ready" in tree.text
        assert "SELECT 2024 AS requested_year" in tree.text

    asyncio.run(check())
