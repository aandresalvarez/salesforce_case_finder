"""One analyst conversation: request, observed progress, answers, reviewed SQL."""
from __future__ import annotations

import asyncio
import hashlib
import json

from nicegui import ui

from ..case360 import preferences, session
from ..case360.runtime import discover
from . import case360_style  # noqa: F401  # Register before the page head is sent.
from .case360_details import render_json

ERRORS = (RuntimeError, OSError, ValueError, TimeoutError)
CONNECTION_ERRORS = {
    "PREFLIGHT_FAILED", "PREFLIGHT_TIMEOUT", "BIGQUERY_PREFLIGHT_FAILED",
    "CREDENTIAL_UNVERIFIED", "PREFLIGHT_EXPIRED",
}
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
        if str(item.get("phase", "")).startswith("author-lookup-"):
            return "Reading relevant sources and updating the query plan"
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
    if isinstance(evidence, list):
        for observation in evidence:
            if observation.get("tool") == "source_map_lookup":
                for part in observation.get("result", {}).get("content", []):
                    if part.get("type") == "text":
                        try:
                            evidence = json.loads(part["text"])
                        except (ValueError, KeyError):
                            continue
                        break
                if isinstance(evidence, dict):
                    break
    if not isinstance(evidence, dict):
        return
    names = []
    for row in evidence.get("sources", []):
        names.append("BigQuery · " + str(row.get("table", "Candidate source")))
    for row in evidence.get("documentation", []):
        names.append("Epic · " + str(row.get("table_name", "Document")))
    for row in evidence.get("repository_documents", []):
        names.append("STARR · " + str(row.get("path", row.get("id", "Definition"))))
    with ui.expansion(f"Source candidates · {len(names)}", value=False).classes("w-full"):
        ui.label("Evidence from the imported snapshot. Availability and meaning "
                 "are checked during analysis.").classes("c360-detail-note")
        for name in names[:12]:
            ui.label(name).classes("c360-source-name")
        if not names:
            ui.label("The initial search found no candidates; "
                     "the agent may broaden its search.")
        with ui.expansion("View full evidence and coverage").classes("w-full"):
            render_json({"resources": preparation.get("resources"), "evidence": evidence},
                        "case360-sources.json")


def render(*, run_id: str | None = None) -> None:
    state: dict = {"run_id": run_id, "busy": False, "last_seq": 0, "remaining": None,
                   "pending": None, "consent_cap": None, "continue_controls": []}
    with ui.column().classes("c360"):
        with ui.row().classes("c360-top"):
            with ui.row().classes("items-center gap-2"):
                ui.label("Case 360").classes("c360-brand")
                ui.label("BETA").classes("c360-beta")
            with ui.row().classes("c360-links"):
                ui.link("History and clean data", "/case360/history")
                ui.link("Beta settings", "/case360/settings")
        heading = ui.label("What data do you need?").classes("c360-heading")
        subtitle = ui.label("Describe your request in your own words. The agent will consult "
                            "sources and ask for any clarification needed before building "
                            "the SQL.").classes("c360-subtitle")
        steps = []
        with ui.element("div").classes("c360-steps"):
            for index, title in enumerate(("Describe", "Clarify", "Review SQL"), 1):
                with ui.element("div").classes("c360-step") as step:
                    ui.label(str(index)).classes("c360-step-number")
                    ui.label(title)
                steps.append(step)
        with ui.element("div").classes("c360-grid"):
            with ui.column().classes("c360-main"):
                with ui.column().classes("c360-card"):
                    ui.label("YOUR REQUEST").classes("c360-eyebrow")
                    request = ui.textarea("Your request", placeholder="Describe the population, "
                        "the data you need, and any conditions you already know.").props(
                            "outlined autogrow").classes("w-full")
                    saved_text = ui.label("").classes("text-sm whitespace-pre-wrap leading-relaxed")
                    saved_text.set_visibility(False)
                    actions = ui.row().classes("c360-actions")
                dialogue = ui.column().classes("c360-dialogue")
                output = ui.column().classes("c360-output")
            with ui.column().classes("c360-side"):
                with ui.column().classes("c360-card"):
                    ui.label("REQUEST STATUS").classes("c360-eyebrow")
                    with ui.row().classes("c360-status-row"):
                        spinner = ui.spinner(size="18px")
                        spinner.set_visibility(False)
                        status = ui.label("Ready when you are.").classes("c360-status").props(
                            'role=status aria-live=polite')
                    consent = ui.label("").classes("c360-budget")
                activity = ui.column().classes("w-full").style("gap:8px")
                with ui.column().classes("c360-card"):
                    ui.label("SOURCES & EVIDENCE").classes("c360-eyebrow")
                    ui.label("Candidates are checked during analysis.").classes("c360-detail-note")
                    sources = ui.column().classes("w-full")

        def stage(index: int) -> None:
            for number, step in enumerate(steps):
                step.classes(add="c360-step-active" if number == index else "",
                             remove="c360-step-active" if number != index else "")
        stage(0)

        def show_failure(error: Exception) -> None:
            code = getattr(error, "code", None)
            if code == "FREEZE_REQUEST_FAILED":
                status.text = ("This beta could not prepare the run. Your request is saved. "
                               "Update or repair the beta before continuing; "
                               "retrying the connection will not fix this error.")
            else:
                status.text = "Could not continue: " + str(error)
            dialogue.clear()
            with dialogue:
                if state["pending"] and (code in CONNECTION_ERRORS or
                        (isinstance(error, TimeoutError) and state.get("step") == "connection")):
                    ui.label("This rechecks your connection, then continues the request "
                             "within the budget shown above.")
                    ui.button("Retry and continue", on_click=lambda: retry_pending())
                else:
                    ui.link("Open beta settings", "/case360/settings")

        def busy(value: bool) -> None:
            state["busy"] = value
            request.set_enabled(not value and state["run_id"] is None)
            submit.set_enabled(not value and state["run_id"] is None)
            submit.set_visibility(state["run_id"] is None)
            request.set_visibility(state["run_id"] is None)
            saved_text.text = request.value or ""
            saved_text.set_visibility(state["run_id"] is not None)
            new.set_enabled(not value)
            cancel.set_visibility(value and state["run_id"] is not None)
            spinner.set_visibility(value)
            for control in state["continue_controls"]:
                if not control.is_deleted:
                    control.set_enabled(not value)

        def show_progress(view: dict) -> None:
            items = view.get("progress", [])
            if items and items[-1]["seq"] != state["last_seq"]:
                state["last_seq"] = items[-1]["seq"]
                activity.clear()
                with activity:
                    ui.label("AGENT ACTIVITY").classes("c360-eyebrow")
                    recent = list(dict.fromkeys(progress_text(item) for item in items[-6:]))
                    for text in recent[-3:]:
                        ui.label(text).classes("c360-activity-item")
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
            if result.get("continuation_recovery", {}).get("available"):
                stage(1)
                heading.text = "Continue building your query"
                subtitle.text = ("Your request and answers are saved. "
                                 "The agent will read relevant sources as needed.")
                status.text = "Ready to resume from your saved interpretation."
                state["remaining"] = result["budget"]["remaining_usd"]
                show_progress({"budget": result["budget"]})
                with dialogue, ui.column().classes("c360-card"):
                    ui.label("Your progress is saved").classes("c360-card-title")
                    ui.label("The previous attempt stopped because its source context was too "
                             "large. This version reads sources on demand and reuses the "
                             "completed interpretation.").classes("c360-detail-note")
                    with ui.expansion("How the agent understood your request"):
                        ui.label(result.get("interpretation", "")).classes(
                            "text-sm leading-relaxed")
                    ui.label(f"Continue within your remaining "
                             f"${state['remaining']:.2f} USD budget.").classes("c360-detail-note")
                    resume_button = ui.button("Continue from saved progress", icon="arrow_forward",
                                              on_click=lambda: launch([])).props(
                                                  "unelevated no-caps")
                    state["continue_controls"].append(resume_button)
            elif conversation.get("waiting"):
                stage(1)
                heading.text = "Let's clarify your request"
                subtitle.text = ("Answer the questions below. The agent will use your choices "
                                 "to find the right sources and build the SQL.")
                status.text = "Please clarify the following before the agent continues."
                state["remaining"] = result["budget"]["remaining_usd"]
                show_progress({"budget": result["budget"]})
                with dialogue, ui.column().classes("c360-card"):
                    count = len(result.get("questions", [])[:12])
                    ui.label("A few details before we build your SQL").classes("c360-card-title")
                    ui.label(f"{count} questions · Your answers stay with this request.").classes(
                        "c360-detail-note")
                    if result.get("clarification_recovery"):
                        ui.label("Your questions were recovered from the saved model response. "
                                 "No new model call was needed.").classes("c360-note")
                    if result.get("interpretation"):
                        with ui.expansion("How the agent understood your request"):
                            ui.label(result["interpretation"]).classes("text-sm leading-relaxed")
                    answers = {}
                    for index, question in enumerate(result.get("questions", [])[:12], 1):
                        with ui.column().classes("c360-question"):
                            ui.label(f"QUESTION {index} OF {count}").classes("c360-question-count")
                            ui.label(question["text"]).classes("c360-question-title")
                            answers[question["id"]] = ui.textarea(f"Answer {index}",
                                placeholder="Type your answer, or say what is unclear.").props(
                                "outlined autogrow maxlength=900").classes("w-full")

                    async def answer() -> None:
                        if any(not (field.value or "").strip() for field in answers.values()):
                            status.text = "Answer each question. If you are unsure, say so."
                            return
                        next_button.disable()
                        await launch([{"question_id": key, "text": field.value}
                                      for key, field in answers.items()])
                        if not state["busy"]:
                            next_button.enable()

                    with ui.column().classes("c360-continue"):
                        ui.label(f"Continue within your remaining "
                                 f"${state['remaining']:.2f} USD budget.").classes(
                                     "c360-detail-note")
                        next_button = ui.button("Continue with my answers", icon="arrow_forward",
                                                on_click=answer).props("unelevated no-caps")
                        state["continue_controls"].append(next_button)
            elif "execution_status" in result:
                stage(2 if result.get("packages") else 1)
                validations = result.get("validations", [])
                compiled = bool(validations and validations[-1].get("objective", {}).get("dry", {}).get("valid"))
                if result["execution_status"] != "COMPLETED":
                    status.text = "Analysis stopped. Your request and saved work are preserved."
                elif result.get("packages") and compiled:
                    status.text = "SQL passed compilation and is ready for your review."
                else:
                    status.text = "SQL still needs corrections. Review the checks below."
            else:
                status.text = "Request saved; analysis has not started yet."
                state["pending"] = view
                state["remaining"] = conversation.get("remaining_cap_usd")
                if not view.get("authorized"):
                    with dialogue, ui.column().classes("c360-card"):
                        retry = ui.button("Continue this request",
                                          on_click=lambda: retry_pending())
                        retry.props("no-caps")
                        state["continue_controls"].append(retry)
            output.clear()
            if ("execution_status" in result
                    and not result.get("continuation_recovery", {}).get("available")
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
                show_failure(error)
            finally:
                busy(False)

        async def start_prepared(prepared: dict, cap: float) -> None:
            c = session.client()
            await c.request("confirm_contract", {
                "contract_sha256": prepared["contract_sha256"]}, run_id=state["run_id"])
            status.text = "Checking your connection and budget…"
            state["step"] = "connection"
            proof = await c.request("probe_run", run_id=state["run_id"])
            state["step"] = "authorization"
            status.text = "Connection verified. Preparing the analysis…"
            await c.request("authorize_run", {
                "contract_sha256": prepared["contract_sha256"],
                "preflight_sha256": proof["sha256"], "cap_usd": min(cap, proof["max_paid_usd"])},
                run_id=state["run_id"])
            state["pending"] = None
            state["step"] = "start"
            status.text = "Starting the agent…"
            dialogue.clear()
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
                show_failure(error)
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
            heading.text = "What data do you need?"
            subtitle.text = ("Describe your request in your own words. The agent will consult "
                             "sources and ask for clarification before building the SQL.")
            stage(0)
            busy(False)
            show_cap()

        def show_cap() -> None:
            try:
                cap = configured_cap()
                state["consent_cap"] = cap
                consent.text = (f"By selecting Analyze or Continue, you authorize up to ${cap:g} "
                                "USD for this "
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
                sources.clear()
                with sources:
                    render_sources(result)
                await inspect(view)
            except ERRORS as error:
                status.text = "Could not open the saved request: " + str(error)
            finally:
                busy(False)

        ui.timer(0.1, restore, once=True)
