"""History, explicit checkpoint recovery and confirmed local erasure."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from nicegui import ui

from ..case360 import session
from .case360_details import render_json

ERRORS = (RuntimeError, OSError, ValueError, TimeoutError)


def render_history(on_clear: Callable[[], None] | None = None) -> None:
    ui.label("Local history").classes("cf-h2")
    status = ui.label("Refresh history to inspect saved work.")
    selection = ui.select({}, multiple=True, value=[], label="Saved requests").classes("w-full")
    all_runs = ui.checkbox("All local history", value=False)
    resources = ui.checkbox("Also remove unused imported resources", value=False)
    ui.label('Removed resources must be prepared again. Resources used by retained '
             'work are protected.')
    panel = ui.column().classes("w-full")
    rows: list[dict] = []
    last_cleanup: dict = {}

    async def refresh() -> None:
        try:
            rows[:] = await session.history(session.client())
            selection.options = {
                r["run_id"]: (f"{r.get('created_at', '')} · revision {r['revision']} · "
                              f"{r['execution_status']} · {r['run_id']}") for r in rows}
            selection.value = [value for value in selection.value if value in selection.options]
            selection.update()
            status.text = (f"{len(rows)} saved requests. "
                           "Charged amounts and uncertain reservations survive cleanup.")
        except ERRORS as error:
            status.text = str(error)

    async def reconnect() -> None:
        try:
            await session.reconnect()
            await refresh()
        except ERRORS as error:
            status.text = str(error)

    async def inspect() -> None:
        panel.clear()
        try:
            if len(selection.value) != 1:
                raise ValueError("Select one saved request to open it.")
            run_id = selection.value[0]
            c = session.client()
            view = await c.request("get_run", run_id=run_id)
            result = await c.artifact(run_id, view["artifact"]) if view.get("artifact") else None
            with panel:
                ui.label(f"Execution: {view['execution_status']} · Quality: HOLD")
                if view.get("budget"):
                    ui.code(json.dumps(view["budget"], indent=2), language="json")
                if result and view.get("conversation"):
                    from .case360_conversation import active_request

                    def open_conversation() -> None:
                        active_request(run_id, save=True)
                        ui.navigate.to("/case360")

                    ui.button("Abrir conversación", on_click=open_conversation)
                if result:
                    from .case360_page import render_preparation, render_result

                    if "execution_status" in result:
                        render_result(result, run_id, view["artifact"])
                    else:
                        render_json(result, "case360-saved-request.json")
                        if view["mode"] == "request" and not view.get("conversation"):
                            with ui.expansion("Edit as a new revision"):
                                render_preparation(previous_run=run_id, draft=result["contract"])
                if (view["mode"] == "request"
                        and view["execution_status"] in {"FAILED", "INTERRUPTED", "COMPLETED"}):
                    ui.button("Check saved checkpoint", on_click=lambda: inspect_checkpoint(run_id))
        except ERRORS as error:
            status.text = str(error)

    async def inspect_checkpoint(run_id: str) -> None:
        try:
            proof = await session.client().request("prepare_resume", run_id=run_id)
            with panel:
                if not proof.get("can_resume"):
                    ui.label('Recovery blocked: saved evidence does not establish a '
                             'safe checkpoint. Prior charges remain recorded.')
                    return
                ui.label('Verified checkpoint. Previously generated SQL and '
                         'recorded charges will be reused.')
                ui.code(json.dumps(proof["budget"], indent=2), language="json")
                ui.button("Resume verified checkpoint",
                          on_click=lambda: resume(run_id, proof))
        except ERRORS as error:
            status.text = str(error)

    async def resume(run_id: str, proof: dict) -> None:
        try:
            c = session.client()
            view = await c.request("resume_run", {"checkpoint_sha256": proof["checkpoint_sha256"]},
                                   run_id=run_id, request_id="resume-" + proof["checkpoint_sha256"])
            while view["execution_status"] in {"STARTING", "RUNNING", "CANCEL_REQUESTED"}:
                status.text = "Resuming: " + view["phase"]
                await asyncio.sleep(0.25)
                view = await c.request("get_run", run_id=run_id)
            status.text = "Execution: " + view["execution_status"] + " · Quality: HOLD"
            await refresh()
        except ERRORS as error:
            status.text = str(error)

    async def stop_selected() -> None:
        try:
            c = session.client()
            for row in await session.history(c):
                if (all_runs.value or row["run_id"] in selection.value) and row["process_active"]:
                    await c.request("cancel_run", run_id=row["run_id"])
            await refresh()
            status.text += " Open a fresh cleanup preview after stopping."
        except ERRORS as error:
            status.text = str(error)

    async def apply_cleanup(plan: dict) -> None:
        try:
            result = await session.client().request("cleanup_data", {
                "cleanup_id": plan["id"], "plan_sha256": plan["plan_sha256"]})
            last_cleanup.clear()
            last_cleanup.update(plan)
            # Discard loaded content even when deletion is partial; the history
            # remains authoritative about which requests still exist.
            panel.clear()
            if on_clear is not None:
                on_clear()
            await refresh()
            with panel:
                ui.label("Cleanup: " + result["status"])
                for row in result["results"]:
                    ui.label(f"{row['id']}: {row['status']}"
                             + (" · " + row["code"] if row.get("code") else ""))
                ui.label('Technical accounting is retained, including uncertain '
                         'reservations. Deleted work cannot be resumed.')
                if any(row.get("requires_preparation") for row in result["results"]):
                    ui.label('Imported resources were removed. Prepare them again '
                             'before a new execution.')
                if result["status"] == "PARTIAL":
                    ui.button("Retry this cleanup",
                              on_click=lambda: apply_cleanup(last_cleanup.copy()))
                ui.label('Other open views may still display loaded content. Reload '
                         'them to clear it.')
        except ERRORS as error:
            status.text = str(error)

    async def preview_cleanup() -> None:
        try:
            plan = await session.client().request("prepare_cleanup", {
                "run_ids": [] if all_runs.value else selection.value.copy(),
                "all_runs": all_runs.value, "unused_resources": resources.value})
            with ui.dialog().props("persistent") as dialog, ui.card():
                ui.label("Confirmar limpieza de datos")
                ui.label(f"Requests: {len(plan['runs'])} · "
                         f"Resource snapshots: {len(plan['resources'])}")
                ui.label('Removes request text, sessions, evidence, SQL and '
                         'feedback. Deleted work cannot be resumed.')
                ui.label('Keeps technical accounting, charged amounts and uncertain '
                         'reservations. Exports outside the app, credentials and '
                         'source systems are unchanged.')
                for item in [*plan["runs"], *plan["resources"]]:
                    name = item.get("run_id", item.get("snapshot"))
                    detail = item.get("blocked")
                    if not detail:
                        detail = (f"{item['inventory']['files']} files · "
                                  f"{item['inventory']['bytes']} bytes")
                    ui.label(f"{name}: {detail}")
                ui.label('Blocked items will be retained. Stop active work and open '
                         'a new preview to include it.')
                ui.label('This removes local app content; it does not guarantee '
                         'physical erasure or delete backups.')

                async def confirm() -> None:
                    confirm_button.disable()
                    dialog.close()
                    await apply_cleanup(plan)

                ui.button("Cancelar", on_click=dialog.close)
                confirm_button = ui.button("Confirmar limpieza", on_click=confirm)
            dialog.open()
        except ERRORS as error:
            status.text = str(error)

    with ui.row():
        ui.button("Refresh history", on_click=refresh)
        ui.button("Reconnect local runtime", on_click=reconnect)
        ui.button("Open selected request", on_click=inspect)
        ui.button("Stop selected work", on_click=stop_selected)
        ui.button("Limpiar datos", on_click=preview_cleanup)
