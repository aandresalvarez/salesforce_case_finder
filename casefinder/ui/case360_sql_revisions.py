"""Review imported SQL separately from the evidence attached to the engine result."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from nicegui import ui

from ..case360 import session


def verified_revisions(history: dict, result: dict, reference: dict) -> list[dict]:
    if history.get("schema") != "case360_sql_review_history/1":
        raise ValueError("Unsupported SQL revision history.")
    parents = {p.get("package_sha256") for p in result.get("packages", [])}
    records = history.get("records", [])
    for index, record in enumerate(records, 1):
        if (record.get("revision") != index
                or record.get("schema") != "case360_sql_review_revision/1"
                or hashlib.sha256(record["sql"].encode()).hexdigest() != record["sql_sha256"]
                or record.get("execution_status") != "NOT_EXECUTED"
                or record.get("dry_run_status") != "NOT_RUN"
                or record.get("inherited_validation") is not False):
            raise ValueError("The saved SQL revision failed its integrity check.")
    return [r for r in records if r["parent"]["artifact_sha256"] == reference["sha256"]
            and r["parent"]["package_sha256"] in parents]


def render_revision(record: dict) -> None:
    ui.label(record["label"]).classes("cf-h2")
    ui.label("Saved draft · Not executed · No dry run").classes("text-blue-800 font-medium")
    ui.label("Your original answers and V1 remain unchanged. The scope changes below apply "
             "only to this version. V1 checks and model reviews do not validate this draft.")
    with ui.expansion("Scope changes for this version", value=True).classes("w-full"):
        for change in record["scope_changes"]:
            ui.label("• " + change)
    with ui.tabs().classes("w-full") as tabs:
        ui.tab("SQL")
        ui.tab("Offline review")
        ui.tab("Provenance")
    with ui.tab_panels(tabs, value="SQL").classes("w-full"):
        with ui.tab_panel("SQL"):
            ui.label("Cohort query")
            ui.button("Download this SQL", on_click=lambda: ui.download.content(
                record["sql"], "cohort-review-revision.sql"))
            ui.code(record["sql"], language="sql").classes("w-full")
            for item in record.get("additional_sql", []):
                with ui.expansion(item["label"]).classes("w-full"):
                    ui.code(item["sql"], language="sql")
        with ui.tab_panel("Offline review"):
            ui.label("Reported static comparison only. Compilation and patient-level "
                     "equivalence have not been measured for this version.")
            ui.label(record["static_review"]).classes("whitespace-pre-wrap")
        with ui.tab_panel("Provenance"):
            ui.label("SQL SHA256: " + record["sql_sha256"])
            ui.code(json.dumps({"parent": record["parent"], "source": record["provenance"]},
                               indent=2), language="json")
    ui.button("Download version and provenance", on_click=lambda: ui.download.content(
        json.dumps(record, indent=2), "sql-review-revision.json")).props("flat")


def render_versions(result: dict, run_id: str, reference: dict,
                    original: Callable[[], None]) -> None:
    host = ui.column().classes("w-full")

    async def load() -> None:
        host.clear()
        try:
            client = session.client()
            view = await client.request("get_run", run_id=run_id)
            ref = view.get("sql_revisions_artifact")
            records = (verified_revisions(await client.artifact(run_id, ref), result, reference)
                       if ref else [])
        except (RuntimeError, ValueError, OSError, TimeoutError) as error:
            with host:
                ui.label("Could not load SQL versions: " + str(error))
                ui.button("Reload saved versions", on_click=load)
                original()
            return
        with host:
            if not records:
                original()
                return
            options = {0: "V1 · Original analysis and answers"}
            options.update({r["revision"]: r["label"] for r in records})
            selected = ui.select(options, value=records[-1]["revision"],
                                 label="Saved SQL version").classes("w-full")
            body = ui.column().classes("w-full")

            def show() -> None:
                body.clear()
                with body:
                    if selected.value == 0:
                        original()
                    else:
                        render_revision(next(r for r in records if r["revision"] == selected.value))
            selected.on_value_change(show)
            show()
    with host:
        ui.label("Loading saved SQL versions…")
    ui.timer(0, load, once=True)


def render_saved_review() -> None:
    from .case360_conversation import active_request
    from .case360_result import render_result

    ui.label("Saved SQL review").classes("cf-h1")
    with ui.row():
        ui.link("Request and saved answers", "/case360")
        ui.link("Request history", "/case360/history")
    ui.label("Opening this page only reads saved work. "
             "It does not analyze, dry run or execute SQL.")
    panel = ui.column().classes("w-full")

    async def load() -> None:
        panel.clear()
        try:
            run_id = active_request()
            if not run_id:
                raise ValueError("Open a saved request first.")
            client = session.client()
            view = await client.request("get_run", run_id=run_id)
            if not view.get("artifact"):
                raise ValueError("This request does not have a saved result yet.")
            result = await client.artifact(run_id, view["artifact"])
            with panel:
                render_result(result, run_id, view["artifact"])
        except (RuntimeError, ValueError, OSError, TimeoutError) as error:
            with panel:
                ui.label(str(error))
    ui.timer(0, load, once=True)
