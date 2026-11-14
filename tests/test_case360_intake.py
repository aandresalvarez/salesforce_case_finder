"""Exercise intake through real NiceGUI handlers, without accounts or model calls."""

import asyncio
import copy

from nicegui import core

from casefinder.case360.client import BridgeError
from casefinder.case360.intake import SCOPE_LABELS, researcher_export
from casefinder.ui import case360_intake as flow


class IntakeClient:
    def __init__(self, *, analyzed=False, prepared=False, fail_save=False):
        self.calls = []
        self.analyzed = analyzed
        self.prepared = prepared
        self.fail_save = fail_save
        self.fail_probe = False
        self.authorized = False
        self.fail_start = False
        self.state = {
            "revision": 1,
            "original_text": "Synthetic study request.  \n",
            "reference_date": "2026-11-13",
            "sources": [],
            "decisions": [],
            "questions": [],
            "summary": None,
            "analysis": None,
        }
        if analyzed:
            self.state.update(
                questions=[
                    {
                        "id": "age",
                        "researcher_text": "When should age be measured?",
                        "analyst_text": "Confirm encounter_date for age at the index visit.",
                        "blocking": True,
                        "answer": "",
                        "status": "pending",
                    }
                ],
                summary={
                    "fields": dict.fromkeys(SCOPE_LABELS, "Explicit synthetic scope"),
                    "assumptions": [],
                    "source_refs": [],
                },
                analysis={"result_sha256": "a" * 64, "intake_revision": 1},
            )

    def view(self):
        return {
            "run_id": "synthetic",
            "phase": "PREPARED" if self.prepared else "INTAKE",
            "execution_status": "COMPLETED" if self.analyzed else "DRAFT",
            "contract_sha256": "a" * 64,
            "authorized": self.authorized,
            "artifact": {"artifact_id": "result"},
        }

    async def request(self, method, params=None, **kwargs):
        self.calls.append((method, copy.deepcopy(params)))
        if method == "intake_create":
            self.state["original_text"] = params["text"]
        if method == "intake_get":
            return {"artifact": {"artifact_id": "intake"}}
        if method == "intake_update":
            if self.fail_save:
                raise BridgeError("INTAKE_REVISION_CHANGED", "Saved revision changed")
            assert params["expected_revision"] == self.state["revision"]
            action, value = params["action"], params["value"]
            if action == "text":
                self.state["original_text"] = value["text"]
            if action == "answer":
                q = next(q for q in self.state["questions"] if q["id"] == value["question_id"])
                q.update(answer=value["text"], status=value["status"])
            if action == "scope":
                self.state["summary"].update(value)
            self.state["revision"] += 1
            return {"artifact": {"artifact_id": "intake"}}
        if method == "prepare_intake":
            if params["action"] == "build" and any(
                q["status"] == "pending" for q in self.state["questions"]
            ):
                raise BridgeError("CLARIFICATION_ANSWERS_REQUIRED", "Required decision missing")
            self.prepared = True
        if method == "probe_run":
            if self.fail_probe:
                raise BridgeError("PREFLIGHT_TIMEOUT", "Connection check timed out")
            return {"sha256": "b" * 64, "max_paid_usd": 50}
        if method == "authorize_run":
            self.authorized = True
        if method == "start_run":
            if self.fail_start:
                self.fail_start = False
                raise BridgeError("COMMAND_INTERRUPTED", "Start response interrupted")
            self.prepared = False
            self.analyzed = True
        return self.view()

    async def artifact(self, run_id, reference):
        if reference["artifact_id"] == "intake":
            return copy.deepcopy(self.state)
        return {
            "resources": {},
            "source_evidence": {},
            "scope_confirmation_required": self.analyzed,
            "budget": {"charged_or_reserved_usd": 1, "remaining_usd": 49},
        }


def setup(render, monkeypatch, client, *, saved=True):
    timers = []
    monkeypatch.setattr(flow.session, "client", lambda: client)
    monkeypatch.setattr(flow, "configured_cap", lambda: 50)
    monkeypatch.setattr(flow, "active_request", lambda *a, **kw: None)
    monkeypatch.setattr(flow.ui, "timer", lambda interval, callback, **kw: timers.append(callback))
    tree = render(lambda: flow.render(run_id="synthetic" if saved else None))
    return tree, timers[0]


def press(tree, label):
    tree.press(next(b for b in tree.buttons() if b.text == label))


def test_restores_request_and_shared_answer_across_audience_views(render, monkeypatch):
    client = IntakeClient(analyzed=True)
    tree, restore = setup(render, monkeypatch, client)

    async def check():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        with tree.client:
            await restore()
            assert tree.of_type("Textarea")[0].value == "Synthetic study request.  \n"
            answer = next(f for f in tree.of_type("Textarea") if f._props["label"] == "Your answer")
            answer.value = "At the first qualifying visit"
            await asyncio.sleep(0)
            tree.of_type("Toggle")[0].value = "Analyst"
            await asyncio.sleep(0)
            assert "encounter_date" in tree.text
            assert (
                next(
                    f for f in tree.of_type("Textarea") if f._props["label"] == "Your answer"
                ).value
                == answer.value
            )
            tree.of_type("Toggle")[0].value = "Researcher"
            await asyncio.sleep(0)
            assert "encounter_date" not in tree.text
            assert "When should age be measured?" in tree.text
        assert client.state["questions"][0]["answer"] == "At the first qualifying visit"
        assert not any(m in {"authorize_run", "start_run"} for m, _ in client.calls)

    asyncio.run(check())


def test_blocking_answer_prevents_sql_and_saved_scope_build_uses_remaining_budget(
    render, monkeypatch
):
    client = IntakeClient(analyzed=True)
    tree, restore = setup(render, monkeypatch, client)

    async def check():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        with tree.client:
            await restore()
            press(tree, "Confirm summary and build SQL")
            await asyncio.sleep(0)
            assert "Answer the blocking questions" in tree.text
            assert not any(m == "authorize_run" for m, _ in client.calls)
            answer = next(f for f in tree.of_type("Textarea") if f._props["label"] == "Your answer")
            answer.value = "At the first qualifying visit"
            await asyncio.sleep(0)
            press(tree, "Confirm summary and build SQL")
            await asyncio.sleep(0)
        assert [p["cap_usd"] for m, p in client.calls if m == "authorize_run"] == [49]
        assert [p["action"] for m, p in client.calls if m == "prepare_intake"] == ["build", "build"]

    asyncio.run(check())


def test_failed_save_cannot_start_analysis(render, monkeypatch):
    client = IntakeClient(fail_save=True)
    tree, restore = setup(render, monkeypatch, client)

    async def check():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        with tree.client:
            await restore()
            tree.of_type("Textarea")[0].value = "New synthetic request"
            press(tree, "Analyze request")
            await asyncio.sleep(0)
        assert "changed in another view" in tree.text
        assert not any(m == "prepare_intake" for m, _ in client.calls)

    asyncio.run(check())


def test_analyze_starts_ai_review_of_pending_documents_and_meeting_notes(render, monkeypatch):
    client = IntakeClient()
    client.state["sources"] = [
        {"id": "source-" + kind, "name": kind + ".md", "kind": kind,
         "disposition": "pending", "extraction_status": "EXTRACTED", "segments": 1,
         "warnings": [], "transcription": ""}
        for kind in ["document", "meeting"]
    ]
    tree, restore = setup(render, monkeypatch, client)

    async def check():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        with tree.client:
            await restore()
            assert tree.text.count("Included · AI will review") == 2
            assert tree.button_labels().count("View source") == 2
            assert "Review source" not in tree.button_labels()
            press(tree, "Analyze request")
            await asyncio.sleep(0)
        assert [p["action"] for m, p in client.calls if m == "prepare_intake"] == ["analyze"]
        assert len([m for m, _ in client.calls if m == "start_run"]) == 1
        assert not any(
            m == "intake_update" and p["action"] == "source_review" for m, p in client.calls
        )
        assert all(s["disposition"] == "pending" for s in client.state["sources"])
        assert flow.progress_text({"kind": "model", "phase": "intake-source-lookup-1"}) == (
            "AI is reading your attachments and meeting notes"
        )

    asyncio.run(check())


def test_retry_uses_frozen_inputs_and_does_not_prepare_or_authorize_twice(render, monkeypatch):
    client = IntakeClient(prepared=True)
    client.fail_probe = True
    tree, restore = setup(render, monkeypatch, client)

    async def check():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        with tree.client:
            await restore()
            assert not tree.of_type("Textarea")[0].enabled
            press(tree, "Retry and continue")
            await asyncio.sleep(0)
            assert "Connection check timed out" in tree.text
            client.fail_probe = False
            press(tree, "Retry and continue")
            await asyncio.sleep(0)
        assert not any(m == "prepare_intake" for m, _ in client.calls)
        assert len([m for m, _ in client.calls if m == "authorize_run"]) == 1
        assert tree.of_type("Textarea")[0].value == "Synthetic study request.  \n"

    asyncio.run(check())


def test_researcher_export_projects_only_public_wording():
    state = {
        "questions": [
            {
                "id": "private_table",
                "researcher_text": "Which care locations?",
                "analyst_text": "project.dataset.private_table",
                "answer": "Private",
            },
            {"researcher_text": "Use private_table?"},
        ]
    }
    result = researcher_export(state)
    assert "Which care locations?" in result
    assert "private_table" not in result
    assert "Private" not in result


def suggested_client():
    client = IntakeClient(analyzed=True)
    client.state["questions"][0]["suggestions"] = [{
        "answer": "At the first qualifying visit.",
        "rationale": "This keeps one consistent index event per participant.",
        "analyst_rationale": "Verify pat_enc.contact_date against the live schema.",
        "basis": "inference", "recommended": True,
        "source_refs": [{"source_id": "REQUEST", "locator": "request",
                         "quote": "Synthetic study request."}],
    }]
    return client


def test_suggestion_is_optional_editable_shared_and_never_applied_on_render(render, monkeypatch):
    client = suggested_client()
    client.state["questions"][0]["answer"] = "My unfinished answer"
    tree, restore = setup(render, monkeypatch, client)

    async def check():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        with tree.client:
            await restore()
            assert "Recommended answer" in tree.text
            assert "AI inference — requires your decision" in tree.text
            assert "pat_enc" not in tree.text
            assert client.state["questions"][0]["answer"] == "My unfinished answer"
            assert client.state["questions"][0]["status"] == "pending"
            assert not any(m == "intake_update" for m, _ in client.calls)
            press(tree, "Use this answer")
            await asyncio.sleep(0)
            assert client.state["questions"][0]["answer"] == "At the first qualifying visit."
            assert client.state["questions"][0]["status"] == "answered"
            field = next(f for f in tree.of_type("Textarea") if f._props["label"] == "Your answer")
            field.value = "At the first qualifying visit after enrollment."
            await asyncio.sleep(0)
            tree.of_type("Toggle")[0].value = "Analyst"
            await asyncio.sleep(0)
            assert "pat_enc.contact_date" in tree.text
            assert client.state["questions"][0]["answer"].endswith("after enrollment.")
        assert not any(
            m in {"prepare_intake", "authorize_run", "start_run"} for m, _ in client.calls
        )

    asyncio.run(check())


def test_stale_suggestions_cannot_replace_an_answer(render, monkeypatch):
    client = suggested_client()
    tree, restore = setup(render, monkeypatch, client)

    async def check():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        with tree.client:
            await restore()
            client.state["analysis_stale"] = True
            # Exercise the real stale-state path after a normal source-changing action.
            tree.of_type("Textarea")[0].value = "Changed study request"
            await asyncio.sleep(0)
            press(tree, "Use this answer")
            await asyncio.sleep(0)
        assert client.state["questions"][0]["answer"] == ""
        assert "Update scope analysis" in tree.text

    asyncio.run(check())


def test_export_includes_plain_suggestions_without_analyst_details_or_saved_answers():
    client = suggested_client()
    client.state["questions"][0]["answer"] = "Private answer"
    exported = researcher_export(client.state)
    assert "At the first qualifying visit." in exported
    assert "AI inference" in exported
    assert "pat_enc" not in exported and "Private answer" not in exported
    client.state["analysis_stale"] = True
    assert "At the first qualifying visit." not in researcher_export(client.state)


def test_retry_after_authorization_does_not_authorize_again(render, monkeypatch):
    client = IntakeClient(prepared=True)
    client.fail_start = True
    tree, restore = setup(render, monkeypatch, client)

    async def check():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        with tree.client:
            await restore()
            press(tree, "Retry and continue")
            await asyncio.sleep(0)
            assert "Start response interrupted" in tree.text
            press(tree, "Retry and continue")
            await asyncio.sleep(0)
        assert len([m for m, _ in client.calls if m == "authorize_run"]) == 1
        assert len([m for m, _ in client.calls if m == "start_run"]) == 2
        assert tree.of_type("Textarea")[0].value == "Synthetic study request.  \n"

    asyncio.run(check())
