"""Case-local sources, shared questions and explicit scope confirmation."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

from nicegui import ui

from ..case360 import session
from ..case360.intake import SCOPE_LABELS, IntakeSession, researcher_export, researcher_text
from . import case360_style  # noqa: F401
from .case360_conversation import (
    ERRORS,
    active_request,
    configured_cap,
    progress_text,
    render_sources,
)
from .case360_details import render_json
from .case360_result import render_result

ERROR_TEXT = {
    "INTAKE_FROZEN": "This revision is ready to start. Retry to continue its saved inputs.",
    "UPLOAD_CAPACITY_REACHED": "This request has reached its attachment limit.",
    "INTAKE_REVISION_CHANGED": "This request changed in another view. Reopen it before editing.",
    "SOURCE_REVIEW_REQUIRED": "An attachment is unavailable. Open its source details.",
    "TRANSCRIPTION_REQUIRED": (
        "An attachment has no readable text. Open View source to add a transcription, "
        "or exclude it and attach a readable copy."
    ),
    "CLARIFICATION_ANSWERS_REQUIRED": "Answer the blocking questions before confirming the scope.",
    "DECISION_REVIEW_REQUIRED": "Accept or reject each proposed meeting decision first.",
    "SCOPE_UNAVAILABLE": "Analyze the updated sources before confirming the scope.",
    "SCOPE_ASSUMPTIONS_REQUIRE_EDIT": "Resolve the remaining assumptions in the scope summary.",
    "SCOPE_INCOMPLETE": "Complete each scope field; use Not applicable where appropriate.",
    "CONVERSATION_ALREADY_CONTINUED": (
        "A newer revision already continues this request. Open it from history."
    ),
}


def render(*, run_id: str | None = None) -> None:
    model: dict = {
        "busy": False,
        "intake": None,
        "result": None,
        "view": None,
        "audience": "Researcher",
        "remaining": None,
        "restoring": False,
    }
    with ui.column().classes("c360"):
        with ui.row().classes("c360-top"):
            with ui.row().classes("items-center gap-2"):
                ui.label("Case 360").classes("c360-brand")
                ui.label("BETA").classes("c360-beta")
            with ui.row().classes("c360-links"):
                ui.link("History and clean data", "/case360/history")
                ui.link("Beta settings", "/case360/settings")
        ui.label("What data do you need?").classes("c360-heading")
        ui.label(
            "Describe the study and add documents or meeting notes. The AI will read them, "
            "ask for clarification, and propose the scope before building SQL."
        ).classes("c360-subtitle")
        ui.label("Describe  →  Clarify  →  Confirm scope  →  Review SQL").classes(
            "c360-detail-note"
        )
        with ui.element("div").classes("c360-grid"):
            with ui.column().classes("c360-main"):
                with ui.column().classes("c360-card"):
                    request = (
                        ui.textarea(
                            "Your request",
                            placeholder="Describe the population, "
                            "data and conditions you already know.",
                        )
                        .props("outlined autogrow maxlength=20000")
                        .classes("w-full")
                    )
                    save_status = ui.label(
                        "Your original request and each revision stay in local history."
                    ).classes("c360-detail-note")
                    source_actions = ui.row().classes("items-start gap-3")
                    attachments = ui.column().classes("w-full gap-3")
                    actions = ui.row().classes("c360-actions")
                questions = ui.column().classes("w-full gap-3")
                decisions = ui.column().classes("w-full gap-3")
                scope = ui.column().classes("w-full gap-3")
                output = ui.column().classes("c360-output")
            with ui.column().classes("c360-side"):
                with ui.column().classes("c360-card"):
                    ui.label("REQUEST STATUS").classes("c360-eyebrow")
                    status = ui.label("Ready when you are.").props("role=status aria-live=polite")
                    budget = ui.label("").classes("c360-budget")
                    ui.label(
                        "SQL is drafted and checked with dry runs. It is not executed."
                    ).classes("c360-detail-note")
                activity = ui.column().classes("w-full")
                with ui.column().classes("c360-card"):
                    ui.label("SOURCES & EVIDENCE").classes("c360-eyebrow")
                    evidence = ui.column().classes("w-full")

    def controller() -> IntakeSession:
        if model["intake"] is None:
            model["intake"] = IntakeSession(
                session.client(), lambda value: active_request(value, save=True)
            )
        return model["intake"]

    def failure(error: Exception) -> None:
        status.text = ERROR_TEXT.get(getattr(error, "code", ""), str(error))
        save_status.text = "Check the message above. Your previously saved work is preserved."

    def busy(value: bool) -> None:
        model["busy"] = value
        frozen = bool(model["view"] and model["view"].get("phase") == "PREPARED")
        for control in [request, upload, notes_button]:
            control.set_enabled(not value and not frozen)
        for control in [analyze, new]:
            control.set_enabled(not value)
        for panel in [attachments, questions, decisions, scope]:
            if value or frozen:
                panel.props("inert")
            else:
                panel.props(remove="inert")
        stop_button.set_visibility(value)

    async def mutate(action: str, value: dict, refresh=True) -> bool:
        if model["busy"]:
            return False
        try:
            await controller().update(action, value, request.value or "")
            save_status.text = "Saved locally."
            if refresh:
                redraw()
            return True
        except ERRORS as error:
            failure(error)
            return False

    async def save_request() -> bool:
        if model["restoring"] or model["busy"]:
            return False
        if not model["intake"] and not (request.value or "").strip():
            return False
        if controller().state.get("original_text") != (request.value or ""):
            return await mutate("text", {"text": request.value or ""}, refresh=False)
        return True

    async def attach(event) -> None:
        if model["busy"]:
            return
        busy(True)
        try:
            data = event.content.read(20 * 1024 * 1024 + 1)
            kind = (
                "image"
                if Path(event.name).suffix.lower() in {".png", ".jpg", ".jpeg"}
                else "document"
            )
            await controller().upload(event.name, data, text=request.value or "", kind=kind)
            status.text = "Attachment saved. Select Analyze request for the AI to review it."
            redraw()
        except ERRORS as error:
            failure(error)
        finally:
            busy(False)

    def meeting_notes() -> None:
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl"):
            ui.label("Add meeting notes").classes("text-lg font-semibold")
            title = ui.input("Meeting title", value="Researcher intake").classes("w-full")
            date = ui.input("Meeting date (optional)").props("type=date")
            reference = ui.input("Source link (optional; content is not fetched)").classes("w-full")
            notes = (
                ui.textarea(
                    "Meeting notes",
                    placeholder="Paste the decisions, questions and "
                    "discussion. The agent will propose changes for you to review.",
                )
                .props("outlined autogrow maxlength=60000")
                .classes("w-full")
            )

            async def save() -> None:
                if model["busy"]:
                    return
                if not (notes.value or "").strip():
                    ui.notify("Paste the meeting notes first.")
                    return
                busy(True)
                try:
                    name = (title.value or "Meeting notes").replace("/", "-").replace("\\", "-")[
                        :150
                    ] + ".md"
                    await controller().upload(
                        name,
                        notes.value.encode(),
                        text=request.value or "",
                        kind="meeting",
                        date=date.value or "",
                        reference=reference.value or "",
                    )
                    dialog.close()
                    redraw()
                    status.text = (
                        "Meeting notes saved. Select Analyze request for the AI to read them "
                        "and propose scope decisions."
                    )
                except ERRORS as error:
                    failure(error)
                finally:
                    busy(False)

            ui.button("Save meeting notes", on_click=save)
            ui.button("Cancel", on_click=dialog.close).props("flat")
        dialog.open()

    async def preview(source: dict) -> None:
        try:
            c = controller()
            page = {"offset": 0, "next": 0}
            with ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl"):
                ui.label(source["name"]).classes("text-lg font-semibold")
                for warning in source.get("warnings", []):
                    ui.label(warning).classes("text-amber-800")
                if source["extension"] in {"png", "jpg", "jpeg"}:
                    raw = await c.original(source)
                    mime = "image/png" if source["extension"] == "png" else "image/jpeg"
                    ui.image(f"data:{mime};base64," + base64.b64encode(raw).decode()).classes(
                        "max-h-80 object-contain"
                    )
                extracted = ui.label("").classes("whitespace-pre-wrap text-sm w-full")
                position = ui.label("").classes("text-xs")

                async def load_page(offset: int) -> None:
                    result = await c.client.request(
                        "intake_source_read",
                        {
                            "source_id": source["id"],
                            "offset": offset,
                            "original": False,
                        },
                        run_id=c.run_id,
                    )
                    page.update(offset=offset, next=result["next_offset"])
                    extracted.text = result["text"] or "No text was extracted."
                    position.text = (
                        f"Characters {offset}–{result['next_offset']} "
                        f"of {result['total_characters']}"
                    )

                with ui.row():
                    ui.button(
                        "Previous text page",
                        on_click=lambda: load_page(max(0, page["offset"] - 12000)),
                    ).props("flat")
                    ui.button("Next text page", on_click=lambda: load_page(page["next"])).props(
                        "flat"
                    )
                transcript = (
                    ui.textarea(
                        "Corrected transcription (optional; replaces extracted text)",
                        value=source.get("transcription", ""),
                    )
                    .props("outlined autogrow maxlength=60000")
                    .classes("w-full")
                )
                ui.label(
                    "The AI reviews this source during analysis. You can optionally correct "
                    "the extracted text or exclude the source. Originals remain saved."
                ).classes("text-sm")

                async def reviewed(disposition: str) -> None:
                    if await mutate(
                        "source_review",
                        {
                            "source_id": source["id"],
                            "disposition": disposition,
                            "transcription": transcript.value or "",
                        },
                    ):
                        dialog.close()

                async def download() -> None:
                    ui.download(await c.original(source), source["name"])

                with ui.row():
                    ui.button("Save text and include", on_click=lambda: reviewed("reviewed"))
                    ui.button("Exclude from analysis", on_click=lambda: reviewed("excluded")).props(
                        "flat"
                    )
                    ui.button("Download original", on_click=download).props("flat")
                    ui.button("Close", on_click=dialog.close).props("flat")
                await load_page(0)
            dialog.open()
        except ERRORS as error:
            failure(error)

    def edit_question(question: dict | None = None) -> None:
        import uuid

        q = question or {"id": "analyst-" + uuid.uuid4().hex, "blocking": True}
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            ui.label("Edit question" if question else "Add a case-specific question").classes(
                "text-lg"
            )
            researcher = (
                ui.textarea("Researcher wording", value=q.get("researcher_text", ""))
                .props("outlined autogrow maxlength=2000")
                .classes("w-full")
            )
            analyst = (
                ui.textarea("Analyst details", value=q.get("analyst_text", ""))
                .props("outlined autogrow maxlength=2000")
                .classes("w-full")
            )
            blocking = ui.checkbox(
                "This decision is required before SQL", value=q.get("blocking", True)
            )

            async def save() -> None:
                if await mutate(
                    "question",
                    {
                        "id": q["id"],
                        "researcher_text": researcher.value or "",
                        "analyst_text": analyst.value or researcher.value or "",
                        "blocking": blocking.value,
                    },
                ):
                    dialog.close()

            ui.button("Save question", on_click=save)
            ui.button("Cancel", on_click=dialog.close).props("flat")
        dialog.open()

    def redraw() -> None:
        state = controller().state
        for panel in (attachments, questions, decisions, scope):
            panel.clear()
        with attachments:
            for source in state.get("sources", []):
                with ui.row().classes("w-full items-center justify-between border rounded-lg p-3"):
                    with ui.column().classes("gap-1"):
                        ui.label(source["name"]).classes("font-medium")
                        source_status = (
                            "Excluded from analysis"
                            if source["disposition"] == "excluded"
                            else "No readable text — add a transcription or readable copy"
                            if not source.get("transcription") and not source.get("segments")
                            else "Included in analysis"
                            if state.get("analysis") and not state.get("analysis_stale")
                            else "Included · AI will review"
                        )
                        ui.label(f"{source['kind'].title()} · {source_status}").classes("text-xs")
                        if source.get("warnings") and source["disposition"] != "excluded":
                            ui.label(
                                "Extraction has limitations. View source for details."
                            ).classes("text-xs text-amber-800")
                    ui.button("View source", on_click=lambda s=source: preview(s)).props(
                        "flat no-caps"
                    )
        with questions:
            if state.get("questions"):
                with ui.column().classes("c360-card"):
                    ui.label("Clarification questions").classes("c360-card-title")

                    def audience(event) -> None:
                        model["audience"] = event.value
                        redraw()

                    ui.toggle(
                        ["Researcher", "Analyst"], value=model["audience"], on_change=audience
                    )
                    for q in state["questions"]:
                        with ui.column().classes("c360-question"):
                            ui.label(
                                researcher_text(q)
                                if model["audience"] == "Researcher"
                                else q["analyst_text"]
                            ).classes("font-medium")
                            ui.label(
                                "Required decision" if q.get("blocking") else "Optional detail"
                            ).classes("text-xs")
                            ui.label(q.get("status", "pending").replace("_", " ").title()).classes(
                                "text-xs"
                            )

                            async def answer(event, question=q) -> None:
                                value = event.value or ""
                                await mutate(
                                    "answer",
                                    {
                                        "question_id": question["id"],
                                        "text": value,
                                        "status": "answered" if value.strip() else "pending",
                                    },
                                    refresh=False,
                                )

                            field = (
                                ui.textarea(
                                    "Your answer", value=q.get("answer", ""), on_change=answer
                                )
                                .props("outlined autogrow maxlength=900 debounce=500")
                                .classes("w-full")
                            )

                            async def not_applicable(question=q, answer_field=field) -> None:
                                await mutate(
                                    "answer",
                                    {
                                        "question_id": question["id"],
                                        "text": answer_field.value or "",
                                        "status": "not_applicable",
                                    },
                                )

                            async def keep_pending(question=q, answer_field=field) -> None:
                                await mutate(
                                    "answer",
                                    {
                                        "question_id": question["id"],
                                        "text": answer_field.value or "",
                                        "status": "pending",
                                    },
                                )

                            with ui.row():
                                ui.button(
                                    "Edit wording",
                                    on_click=lambda question=q: edit_question(question),
                                ).props("flat no-caps")
                                ui.button(
                                    "Not applicable (explain above)", on_click=not_applicable
                                ).props("flat no-caps")
                                ui.button("Keep pending", on_click=keep_pending).props(
                                    "flat no-caps"
                                )
                    ui.button(
                        "Export researcher questions",
                        on_click=lambda: ui.download(
                            researcher_export(controller().state).encode(),
                            "researcher-questions.md",
                        ),
                    ).props("flat no-caps")
            ui.button("Add a question", on_click=lambda: edit_question()).props("flat no-caps")
        with decisions:
            if state.get("decisions"):
                ui.label("Proposed decisions from your sources").classes("text-lg font-semibold")
                ui.label(
                    "Review the source quote. Proposed decisions require your acceptance."
                ).classes("c360-detail-note")
            for decision in state.get("decisions", []):
                with ui.column().classes("c360-card"):
                    ui.label(decision["kind"].title() + " · " + decision["status"]).classes(
                        "c360-eyebrow"
                    )
                    ui.label(decision["quote"]).classes("text-sm whitespace-pre-wrap")
                    source_name = next(
                        (s["name"] for s in state["sources"] if s["id"] == decision["source_id"]),
                        decision["source_id"],
                    )
                    ui.label(f"{source_name} · {decision['locator']}").classes("text-xs")
                    proposed = (
                        ui.textarea(
                            "Proposed scope decision",
                            value=decision.get("accepted_text", decision["text"]),
                        )
                        .props("outlined autogrow maxlength=1800")
                        .classes("w-full")
                    )

                    async def choose(status_value: str, d=decision, field=proposed) -> None:
                        await mutate(
                            "decision",
                            {"id": d["id"], "status": status_value, "text": field.value or ""},
                        )

                    with ui.row():
                        ui.button(
                            "Accept decision", on_click=lambda callback=choose: callback("accepted")
                        )
                        ui.button(
                            "Reject proposal", on_click=lambda callback=choose: callback("rejected")
                        ).props("flat")
        with scope:
            summary = state.get("summary")
            if summary:
                with ui.column().classes("c360-card"):
                    ui.label("Confirm the research scope").classes("c360-card-title")
                    ui.label(
                        f"Date reference: {state['reference_date']}. "
                        "Check the interval and boundaries below."
                    ).classes("c360-detail-note")
                    fields = {
                        key: ui.textarea(label, value=summary["fields"].get(key, ""))
                        .props("outlined autogrow maxlength=2000")
                        .classes("w-full")
                        for key, label in SCOPE_LABELS.items()
                    }
                    assumptions = (
                        ui.textarea(
                            "Unresolved assumptions (resolve these in the fields above)",
                            value="\n".join(summary.get("assumptions", [])),
                        )
                        .props("outlined autogrow")
                        .classes("w-full")
                    )
                    for ref in summary.get("source_refs", []):
                        ui.label(f"{ref['source_id']} · {ref['locator']}: {ref['quote']}").classes(
                            "text-xs"
                        )

                    async def save_scope() -> bool:
                        return await mutate(
                            "scope",
                            {
                                "fields": {k: f.value or "" for k, f in fields.items()},
                                "assumptions": [
                                    x.strip()
                                    for x in (assumptions.value or "").splitlines()
                                    if x.strip()
                                ],
                            },
                            refresh=False,
                        )

                    async def build() -> None:
                        if await save_scope():
                            await launch("build")

                    for field in [*fields.values(), assumptions]:
                        field.props("debounce=500")
                        field.on_value_change(save_scope)

                    plan = (model["result"] or {}).get("requirement_plan")
                    if plan:
                        with ui.expansion("Analyst details: candidate tables and mappings").classes(
                            "w-full"
                        ):
                            ui.label("Candidates require verification during SQL analysis.")
                            render_json(plan, "scope-candidate-mappings.json")

                    with ui.row():
                        ui.button("Save scope edits", on_click=save_scope).props("flat no-caps")
                        ui.button("Confirm summary and build SQL", on_click=build).props(
                            "unelevated no-caps"
                        )
                    if state.get("analysis_stale"):
                        ui.label(
                            "Sources or request text changed. Analyze again to update the summary."
                        ).classes("text-amber-800")
        analyze.text = (
            "Retry and continue"
            if model["view"] and model["view"].get("phase") == "PREPARED"
            else "Update scope analysis"
            if state.get("analysis")
            else "Analyze request"
        )
        result = model["result"] or {}
        analysis = state.get("analysis") or {}
        if result.get("packages") and state["revision"] > analysis.get(
            "intake_revision", state["revision"]
        ):
            output.clear()
            with output:
                ui.label(
                    "The scope has changed. Earlier SQL and checks remain in history; "
                    "confirm the updated scope to generate a new version."
                ).classes("c360-detail-note")
        busy(model["busy"])

    async def inspect(view: dict) -> None:
        c = controller()
        model["view"] = view
        while view["execution_status"] in {"STARTING", "RUNNING", "CANCEL_REQUESTED"}:
            progress = view.get("progress", [])
            status.text = progress_text(progress[-1]) if progress else "Starting analysis…"
            activity.clear()
            with activity:
                ui.label("AGENT ACTIVITY").classes("c360-eyebrow")
                for item in progress[-4:]:
                    ui.label(progress_text(item)).classes("c360-activity-item")
            await asyncio.sleep(0.7)
            view = await c.client.request("get_run", run_id=c.run_id)
        model["view"] = view
        result = await c.client.artifact(c.run_id, view["artifact"])
        model["result"] = result
        await c.load(c.run_id)
        model["restoring"] = True
        request.value = c.state["original_text"]
        model["restoring"] = False
        measured = result.get("budget")
        if measured:
            model["remaining"] = measured["remaining_usd"]
            spent = measured["charged_or_reserved_usd"] + result.get("conversation", {}).get(
                "spent_before_usd", 0
            )
            budget.text = (
                f"${spent:.2f} USD used or reserved · ${measured['remaining_usd']:.2f} remaining."
            )
        evidence.clear()
        with evidence:
            render_sources(result)
        output.clear()
        with output:
            if result.get("packages") or result.get("execution_status") == "FAILED":
                render_result(result, c.run_id, view["artifact"])
        redraw()
        status.text = (
            "Review the questions, proposed decisions and scope summary."
            if result.get("scope_confirmation_required")
            else "Analysis stopped. Saved sources and results remain available."
            if result.get("execution_status") == "FAILED"
            else "Review the saved result and any unresolved decisions."
            if result.get("execution_status")
            else "Request saved. Ready to analyze."
        )

    async def launch(action="analyze") -> None:
        if model["busy"]:
            return
        if not (request.value or "").strip():
            status.text = "Enter a request to begin."
            return
        pending = model["view"]
        if not (pending and pending.get("phase") == "PREPARED") and not await save_request():
            return
        busy(True)
        try:
            c = controller()
            cap = configured_cap() if model["remaining"] is None else model["remaining"]
            prepared = (
                await c.client.request("get_run", run_id=c.run_id)
                if pending and pending.get("phase") == "PREPARED"
                else await c.prepare(action)
            )
            model["view"] = prepared
            await start_prepared(prepared, cap)
        except ERRORS as error:
            failure(error)
            redraw()
        finally:
            busy(False)

    async def start_prepared(prepared: dict, cap: float) -> None:
        c = controller()
        if prepared.get("authorized"):
            view = await c.client.request(
                "start_run", run_id=c.run_id, request_id="start-" + c.run_id
            )
            await inspect(view)
            return
        await c.client.request(
            "confirm_contract", {"contract_sha256": prepared["contract_sha256"]}, run_id=c.run_id
        )
        status.text = "Checking your connection and remaining budget…"
        proof = await c.client.request("probe_run", run_id=c.run_id)
        authorization = await c.client.request(
            "authorize_run",
            {
                "contract_sha256": prepared["contract_sha256"],
                "preflight_sha256": proof["sha256"],
                "cap_usd": min(cap, proof["max_paid_usd"]),
            },
            run_id=c.run_id,
        )
        prepared.update(authorization)
        view = await c.client.request("start_run", run_id=c.run_id, request_id="start-" + c.run_id)
        await inspect(view)

    async def stop() -> None:
        try:
            await controller().client.request("cancel_run", run_id=controller().run_id)
        except ERRORS as error:
            failure(error)

    def reset() -> None:
        if model["busy"]:
            return
        active_request(None, save=True)
        ui.navigate.to("/case360")

    with source_actions:
        upload = (
            ui.upload(
                label="Attach files",
                on_upload=attach,
                auto_upload=True,
                max_file_size=20 * 1024 * 1024,
            )
            .props('accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg" flat bordered')
            .classes("max-w-xs")
        )
        notes_button = ui.button("Add meeting notes", on_click=meeting_notes).props("flat no-caps")
    with actions:
        analyze = ui.button("Analyze request", on_click=lambda: launch()).props(
            "unelevated no-caps"
        )
        stop_button = ui.button("Stop", on_click=stop).props("flat no-caps")
        new = ui.button("New request", on_click=reset).props("flat no-caps")
    stop_button.set_visibility(False)
    request.on("blur", save_request)
    request.props("debounce=500")
    request.on_value_change(save_request)
    try:
        budget.text = (
            f"Analyze and Build authorize work within ${configured_cap():g} USD per request, "
            "including subsequent revisions."
        )
    except ERRORS as error:
        budget.text = str(error)

    async def restore() -> None:
        model["restoring"] = True
        try:
            saved = run_id or active_request()
            if not saved:
                return
            c = controller()
            c.run_id = saved
            view = await c.client.request("get_run", run_id=saved)
            if view.get("process_active"):
                busy(True)
                await inspect(view)
            else:
                await c.load(saved)
                request.value = c.state["original_text"]
                await inspect(view)
        except ERRORS as error:
            failure(error)
        finally:
            model["restoring"] = False
            busy(False)

    ui.timer(0.1, restore, once=True)
