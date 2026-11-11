"""One analyst conversation: request, observed progress, answers, reviewed SQL."""
from __future__ import annotations

import asyncio
import hashlib
import json

from nicegui import ui

from ..case360 import preferences, session
from ..case360.runtime import discover
from .case360_details import render_json

ERRORS = (RuntimeError, OSError, ValueError, TimeoutError)
PHASES = {
    "INTAKE": "Interpreting your request",
    "AUTHOR_EVIDENCE": "Finding sources and checking columns",
    "AUTHOR_GENERATION": "Building the SQL",
    "TARGETED_SOURCE_RESOLUTION": "Checking unresolved sources",
    "TARGETED_REPAIR": "Revising the SQL after review",
    "SAME_SESSION_REPAIR": "Revising the SQL after review",
    "WAITING_CLARIFICATION": "Waiting for your answers",
    "WAITING_FINAL_CLARIFICATION": "Review found unresolved decisions",
}
MODEL_PHASES = {
    "intake": "Interpreting the request",
    "evidence-1": "Finding sources",
    "evidence-2": "Verifying sources",
    "generate": "Generating SQL",
    "review": "Independent review",
    "final-review": "Final review",
}


def configured_cap() -> float:
    location = discover().context_file
    policy = json.loads(location.read_text())["authorization_policy"] if location else {}
    if not policy.get("live_enabled") or policy.get("max_paid_usd", 0) <= 0:
        raise ValueError("Set up your connection and budget in Beta settings to begin.")
    return float(policy["max_paid_usd"])


def active_request(value: str | None = None, *, save: bool = False) -> str | None:
    """Only remember a run ID; request content remains in the controller's private store."""
    key = hashlib.sha256(str(discover().runs_root).encode()).hexdigest()
    location = preferences.data_root() / "active-conversation.json"
    if save:
        preferences.atomic_json(location, {"installation": key, "run_id": value})
        return value
    if location.is_file():
        record = json.loads(location.read_text())
        if record.get("installation") == key:
            return record.get("run_id")
    return None


def progress_text(item: dict) -> str:
    kind = item.get("kind")
    if kind == "stage":
        return PHASES.get(item.get("stage"), "Processing the request")
    if kind == "model":
        return MODEL_PHASES.get(item.get("phase"), "Agent analysis and review")
    if kind == "sources_retrieved":
        return "Searched this installation's local source index"
    tool = {"inspect_table_schema": "BigQuery schema",
            "starr_prior_lookup": "Source index",
            "historical_sql_search": "Patterns and documentation"}.get(
                item.get("tool"), item.get("tool", "Source"))
    verb = "Consulting" if kind == "source_started" else "Response received from"
    return f"{verb} {tool}" + (f": {item['query']}" if item.get("query") else "")


def render_sources(preparation: dict) -> None:
    evidence = preparation.get("source_evidence") or {}
    if not isinstance(evidence, dict):
        return
    names = []
    for row in evidence.get("sources", []):
        names.append("BigQuery · " + str(row.get("table", "Candidate source")))
    for row in evidence.get("documentation", []):
        names.append("Epic · " + str(row.get("table_name", "Document")))
    for row in evidence.get("repository_documents", []):
        names.append("STARR · " + str(row.get("path", row.get("id", "Definition"))))
    with ui.expansion(f"Sources found · {len(names)}", value=bool(names)).classes("w-full"):
        ui.label("Evidence from the imported snapshot. Availability and meaning "
                 "are checked during analysis.").classes("text-sm text-slate-500")
        for name in names[:12]:
            ui.label(name).classes("text-sm break-all")
        if not names:
            ui.label("The initial search found no candidates; "
                     "the agent may broaden its search.")
        with ui.expansion("View full evidence and coverage").classes("w-full"):
            render_json({"resources": preparation.get("resources"), "evidence": evidence},
                        "case360-sources.json")


def render(*, run_id: str | None = None) -> None:
    state: dict = {"run_id": run_id, "busy": False, "last_seq": 0, "remaining": None,
                   "pending": None, "consent_cap": None}
    with ui.column().classes("w-full").style("max-width:900px;margin:0 auto;gap:20px"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("Case 360 Beta").style("font-size:20px;font-weight:650")
            with ui.row().classes("gap-4"):
                ui.link("History and clean data", "/case360/history")
                ui.link("Beta settings", "/case360/settings")
        ui.label("What data do you need?").style("font-size:32px;font-weight:600;margin-top:32px")
        ui.label("Describe your request in your own words. The agent will consult sources and "
                 "ask for any clarification needed before building the SQL.").classes(
                     "text-slate-600")
        request = ui.textarea("Your request", placeholder="Describe the population, the data "
                              "you need, and any conditions you already know.").props(
                                  "outlined autogrow").classes("w-full")
        status = ui.label("").classes("text-slate-600")
        consent = ui.label("").classes("text-sm text-slate-500")
        actions = ui.row().classes("items-center gap-3")
        activity = ui.column().classes("w-full").style("gap:8px")
        sources = ui.column().classes("w-full")
        dialogue = ui.column().classes("w-full")
        output = ui.column().classes("w-full")

        def busy(value: bool) -> None:
            state["busy"] = value
            request.set_enabled(not value and state["run_id"] is None)
            submit.set_enabled(not value and state["run_id"] is None)
            new.set_enabled(not value)
            cancel.set_visibility(value and state["run_id"] is not None)

        def show_progress(view: dict) -> None:
            items = view.get("progress", [])
            if items and items[-1]["seq"] != state["last_seq"]:
                state["last_seq"] = items[-1]["seq"]
                activity.clear()
                with activity:
                    ui.label("Agent activity").classes("font-medium")
                    for item in items[-6:]:
                        ui.label(progress_text(item)).classes("text-sm break-all")
                    with ui.expansion("View recorded activity").classes("w-full"):
                        for item in items:
                            ui.label(progress_text(item)).classes("text-sm break-all")
            budget = view.get("budget")
            if budget:
                total = budget["charged_or_reserved_usd"] + state.get("spent_before", 0)
                consent.text = (f"Request: ${total:.4f} USD "
                                f"used or reserved · ${budget['remaining_usd']:.2f} "
                                "remaining.")

        async def inspect(view: dict) -> None:
            c = session.client()
            while view["execution_status"] in {"STARTING", "RUNNING", "CANCEL_REQUESTED"}:
                busy(True)
                show_progress(view)
                status.text = (progress_text(view["progress"][-1]) if view.get("progress")
                               else "Starting analysis…")
                await asyncio.sleep(0.7)
                view = await c.request("get_run", run_id=state["run_id"])
            show_progress(view)
            result = await c.artifact(state["run_id"], view["artifact"])
            dialogue.clear()
            conversation = result.get("conversation", {})
            if conversation.get("answers"):
                with dialogue, ui.expansion("Your clarifications").classes("w-full"):
                    for answer in conversation["answers"]:
                        ui.label(answer["question"]).classes("font-medium")
                        ui.label(answer["text"])
            if conversation.get("waiting"):
                status.text = "Please clarify the following before the agent continues."
                state["remaining"] = result["budget"]["remaining_usd"]
                with dialogue:
                    if result.get("interpretation"):
                        ui.label(result["interpretation"]).classes("text-slate-700")
                    answers = {}
                    for question in result.get("questions", [])[:12]:
                        ui.label(question["text"]).classes("font-medium")
                        answers[question["id"]] = ui.textarea("Your answer").props(
                            "outlined autogrow maxlength=900").classes("w-full")
                    ui.label(f"Continuing uses the remaining budget: up to "
                             f"${state['remaining']:.2f} USD.").classes("text-sm text-slate-500")

                    async def answer() -> None:
                        if any(not (field.value or "").strip() for field in answers.values()):
                            status.text = "Answer each question. If you are unsure, say so."
                            return
                        next_button.disable()
                        await launch([{"question_id": key, "text": field.value}
                                      for key, field in answers.items()])
                        if not state["busy"]:
                            next_button.enable()

                    next_button = ui.button("Continue with my answers", on_click=answer)
            elif "execution_status" in result:
                status.text = ("SQL is ready for your review." if result.get("packages")
                               else "The analysis could not complete the SQL. Review the result.")
            else:
                status.text = "Request saved; analysis has not started yet."
                state["pending"] = view
                state["remaining"] = conversation.get("remaining_cap_usd")
                if not view.get("authorized"):
                    with dialogue:
                        retry = ui.button("Continue this request",
                                          on_click=lambda: retry_pending())
                        retry.props("no-caps")
            output.clear()
            if ("execution_status" in result
                    and (result.get("packages") or not conversation.get("waiting"))):
                from .case360_result import render_result

                with output:
                    render_result(result, state["run_id"], view["artifact"])

        async def launch(answers: list[dict] | None = None) -> None:
            if state["busy"]:
                return
            text = request.value or ""
            if answers is None and not text.strip():
                status.text = "Enter a request to begin."
                return
            if answers is None and (len(text) > 20000 or len(text.encode()) > 24000):
                status.text = "The request is too long. Use up to 20,000 characters and 24 KB."
                return
            busy(True)
            try:
                cap = (state["remaining"] if answers is not None
                       else min(configured_cap(), state["consent_cap"] or configured_cap()))
                c = session.client()
                status.text = "Searching this installation's resources for evidence…"
                prepared = await c.request("prepare_conversation", {
                    "text": "" if answers is not None else text,
                    "previous_run_id": state["run_id"] if answers is not None else None,
                    "answers": answers or []})
                state["run_id"] = prepared["run_id"]
                state["pending"] = prepared
                state["remaining"] = cap
                active_request(state["run_id"], save=True)
                state["last_seq"] = 0
                artifact = await c.artifact(state["run_id"], prepared["artifact"])
                state["spent_before"] = artifact.get("conversation", {}).get("spent_before_usd", 0)
                sources.clear()
                with sources:
                    render_sources(artifact)
                await start_prepared(prepared, cap)
            except ERRORS as error:
                status.text = "Could not continue: " + str(error)
                if state["pending"]:
                    dialogue.clear()
                    with dialogue:
                        ui.button("Retry connection", on_click=lambda: retry_pending())
            finally:
                busy(False)

        async def start_prepared(prepared: dict, cap: float) -> None:
            c = session.client()
            await c.request("confirm_contract", {
                "contract_sha256": prepared["contract_sha256"]}, run_id=state["run_id"])
            status.text = "Checking your connection and budget…"
            proof = await c.request("probe_run", run_id=state["run_id"])
            await c.request("authorize_run", {
                "contract_sha256": prepared["contract_sha256"],
                "preflight_sha256": proof["sha256"], "cap_usd": min(cap, proof["max_paid_usd"])},
                run_id=state["run_id"])
            state["pending"] = None
            view = await c.request("start_run", run_id=state["run_id"],
                                   request_id="start-" + state["run_id"])
            await inspect(view)

        async def retry_pending() -> None:
            if state["busy"] or not state["pending"]:
                return
            busy(True)
            try:
                await start_prepared(state["pending"], state["remaining"])
            except ERRORS as error:
                status.text = "Could not continue: " + str(error)
            finally:
                busy(False)

        async def stop() -> None:
            cancel.disable()
            try:
                await session.client().request("cancel_run", run_id=state["run_id"])
            except ERRORS as error:
                status.text = str(error)
            finally:
                cancel.enable()

        def reset() -> None:
            state.update(run_id=None, remaining=None, last_seq=0, pending=None)
            active_request(None, save=True)
            request.value = ""
            for panel in (activity, sources, dialogue, output):
                panel.clear()
            status.text = ""
            busy(False)
            show_cap()

        def show_cap() -> None:
            try:
                cap = configured_cap()
                state["consent_cap"] = cap
                consent.text = (f"By selecting Analyze, you authorize up to ${cap:g} USD for this "
                                "request, including clarification and review. "
                                "SQL is not executed.")
            except ERRORS as error:
                consent.text = str(error)

        with actions:
            submit = ui.button("Analyze request", on_click=lambda: launch()).props(
                "unelevated no-caps")
            cancel = ui.button("Stop", on_click=stop).props("flat no-caps")
            new = ui.button("New request", on_click=reset).props("flat no-caps")
        cancel.set_visibility(False)
        show_cap()

        async def restore() -> None:
            try:
                saved = run_id or active_request()
                if not saved:
                    return
                state["run_id"] = saved
                c = session.client()
                view = await c.request("get_run", run_id=saved)
                result = await c.artifact(saved, view["artifact"])
                conversation = result.get("conversation", {})
                state["spent_before"] = conversation.get("spent_before_usd", 0)
                request.value = conversation.get("original_text", "")
                if "execution_status" not in result:
                    sources.clear()
                    with sources:
                        render_sources(result)
                await inspect(view)
            except ERRORS as error:
                status.text = "Could not open the saved request: " + str(error)
            finally:
                busy(False)

        ui.timer(0.1, restore, once=True)
