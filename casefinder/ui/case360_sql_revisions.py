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


def matching_validation(record: dict, history: dict | None) -> dict | None:
    if not history:
        return None
    if history.get("schema") != "case360_sql_validation_history/1":
        raise ValueError("Unsupported dry-run history.")
    sqls = [record["sql"], *(q["sql"] for q in record.get("additional_sql", []))]
    hashes = [hashlib.sha256(sql.encode()).hexdigest() for sql in sqls]
    matches = [v for v in history.get("records", [])
               if v.get("run_id") == record.get("run_id")
               and v.get("revision") == record["revision"]
               and v.get("sql_sha256") == record["sql_sha256"]]
    for value in sorted(matches, key=lambda v: v["sequence"], reverse=True):
        results = value.get("results", [])
        if [r.get("sql_sha256") for r in results] != hashes:
            continue
        if value.get("executed_queries") != 0 or value.get("clinical_approval") is not False:
            raise ValueError("Invalid saved dry-run evidence.")
        for item, sql in zip(results, sqls, strict=True):
            if (item.get("request", {}).get("configuration", {}).get("dryRun") is not True
                    or item["request"]["configuration"].get("query", {}).get("query") != sql):
                raise ValueError("The dry run does not match this SQL.")
            if item.get("status") == "PASS":
                response = item.get("response", {})
                if (item.get("http_status") != 200
                        or response.get("configuration", {}).get("dryRun") is not True
                        or not response.get("statistics")
                        or response.get("status", {}).get("errorResult")):
                    raise ValueError("Incomplete dry-run confirmation.")
        if (value.get("status") == "PASS") != all(r.get("status") == "PASS" for r in results):
            raise ValueError("Inconsistent dry-run result.")
        return value
    return None


def render_revision(record: dict, run_id: str | None = None,
                    validation_history: dict | None = None) -> None:
    ui.label(record["label"]).classes("cf-h2")
    history = {"value": validation_history}

    @ui.refreshable
    def checks() -> None:
        value = matching_validation(record, history["value"])
        status = "Dry run passed" if value and value["status"] == "PASS" else (
            "Dry run needs attention" if value else "No dry run yet")
        ui.label("Saved draft · SQL not executed · " + status).classes(
            "text-blue-800 font-medium")
        if value:
            ui.label("Checked: " + value["checked_at"])
            for item in value["results"]:
                detail = (f"Estimated scan: {int(item['estimated_bytes']) / 1e9:.2f} GB"
                          if item.get("estimated_bytes") is not None else "")
                ui.label(f"{item['label']}: {item['status']} {detail}")
                if item.get("error"):
                    ui.label(item["error"]).classes("text-red-800")
        ui.label("A dry run checks compilation and estimates data scanned. "
                 "It does not execute SQL or establish clinical correctness.")
    checks()
    action_status = ui.label("").props("role=status aria-live=polite")

    async def validate() -> None:
        validate_button.disable()
        action_status.text = "Checking this version with BigQuery… SQL will not execute."
        try:
            client = session.client()
            saved = await client.request("validate_sql_revision", {
                "revision": record["revision"], "sql_sha256": record["sql_sha256"]},
                run_id=run_id)
            history["value"] = await client.artifact(run_id, saved["artifact"])
            checks.refresh()
            action_status.text = "Dry-run result saved for this version."
        except (RuntimeError, ValueError, OSError, TimeoutError) as error:
            action_status.text = str(error)
        finally:
            validate_button.enable()
    if run_id:
        validate_button = ui.button("Validate SQL (dry run)", on_click=validate)

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
            ui.label("Original static review, recorded before later dry runs. "
                     "Patient-level equivalence has not been measured.")
            ui.label(record["static_review"]).classes("whitespace-pre-wrap")
        with ui.tab_panel("Provenance"):
            ui.label("SQL SHA256: " + record["sql_sha256"])
            ui.code(json.dumps({"parent": record["parent"], "source": record["provenance"]},
                               indent=2), language="json")
    ui.button("Download version and provenance", on_click=lambda: ui.download.content(
        json.dumps({"revision": record,
                    "validation": matching_validation(record, history["value"])},
                   indent=2), "sql-review-revision.json")).props("flat")


def render_membership_decisions(decisions: list[dict]) -> None:
    for decision in decisions:
        ui.label(decision["rule"]).classes("font-medium")
        if decision["basis"] == "app_answer":
            ui.label("Saved from the answer in this review.").classes("c360-detail-note")
        for ref in decision.get("citations", []):
            ui.label(f'{ref.get("name") or ref["source_id"]} · {ref["locator"]} — {ref["quote"]}').classes("c360-detail-note")


def render_membership_questions(check: dict, submit) -> None:
    ui.label("One more decision about who qualifies").classes("cf-h2")
    fields = {}
    for question in check["questions"]:
        if question["option"] is not None:
            continue
        ui.label(question["question"]).classes("font-medium")
        ui.label(question["example"])
        if question["conflict"]:
            ui.label("Your study sources give different answers.")
            for ref in question["citations"]:
                ui.label(f'{ref.get("name") or ref["source_id"]} · {ref["quote"]}')
        fields[question["id"]] = ui.radio(dict(enumerate(question["options"])), value=None)
    status = ui.label("").props("role=status aria-live=polite")

    async def save() -> None:
        if any(field.value is None for field in fields.values()):
            status.text = "Choose an answer to each open question."
            return
        button.disable()
        try:
            await submit([{"id": key, "option": int(field.value)} for key, field in fields.items()])
        except (RuntimeError, ValueError, OSError, TimeoutError) as error:
            status.text = str(error)
            button.enable()

    button = ui.button("Save decision and continue", on_click=save).props("unelevated no-caps")


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
            checks_ref = view.get("sql_validations_artifact")
            validations = (await client.artifact(run_id, checks_ref)) if checks_ref else None
            version = records[-1]["revision"] if records else 0
            params = {"revision": version, "artifact_sha256": reference["sha256"],
                      "token": None, "answers": []}
            check = {"status": "none"}
            if result.get("packages") and "review_membership" in getattr(client, "capabilities", ()):
                check = await client.request("review_membership", params, run_id=run_id)
                if check["status"] == "documented":
                    check = await client.request("review_membership", {**params, "token": check["token"]},
                                                 run_id=run_id)
                if check.get("revision", version) != version:
                    await load()
                    return
        except (RuntimeError, ValueError, OSError, TimeoutError) as error:
            with host:
                ui.label("Could not load SQL versions: " + str(error))
                ui.button("Reload saved versions", on_click=load)
                original()
            return
        with host:
            if check["status"] == "pending":
                async def submit(answers: list[dict]) -> None:
                    await client.request("review_membership",
                                         {**params, "token": check["token"], "answers": answers},
                                         run_id=run_id)
                    await load()
                render_membership_questions(check, submit)
            elif check["status"] in {"applied", "author_ready"}:
                ui.label("Saved study decisions").classes("cf-h2")
                render_membership_decisions(check["decisions"])
                if check["status"] == "author_ready":
                    ui.link("Continue with the SQL author", "/case360")
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
                        render_revision(next(r for r in records if r["revision"] == selected.value),
                                        run_id, validations)
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
