"""Readable evidence and SQL views; a completed execution is never an approval."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile

from nicegui import ui

from ..case360 import preferences, session
from .case360_details import render_json


def requirement_rows(result: dict) -> list[dict]:
    contract = result.get("contract", {})
    requirements = contract.get("requirements", result.get("requirements", []))
    sources = {r["id"]: r for r in contract.get("sources", [])}
    centers_text = sources.get("CENTERS", {}).get("excerpt", "")
    centers = [c for c in ("SHC", "LPCH") if c in centers_text] or ["Unspecified"]
    matrix = result.get("field_matrix", [])
    rows = []
    for requirement in requirements:
        matches = [r for r in matrix if r.get("requirement_id") == requirement["id"]]
        for center in centers:
            selected = [r for r in matches if str(r.get("site", "")).upper() == center]
            if not selected:
                selected = [{"field": None, "status": "NOT_VERIFIED", "candidates": []}]
            for field in selected:
                candidates = field.get("candidates", [])
                rows.append({"key": str(len(rows)), "requirement": requirement["id"],
                    "statement": requirement["statement"],
                    "field": field.get("field") or "Not specified",
                    "center": center, "status": field.get("status", "NOT_VERIFIED"),
                    "sources": (", ".join(r.get("table", "") for r in candidates)
                                or "Not established"),
                    "grain": field.get("grain") or "Unconfirmed", "detail": field,
                    "citations": requirement.get("source_refs", [])})
        for field in matches:
            if field.get("kind") in {"contract_clause", "interpreted_contract_clause"}:
                rows.append({"key": str(len(rows)), "requirement": requirement["id"],
                    "statement": requirement["statement"],
                    "field": field.get("field") or "Contract clause",
                    "center": "Applicability unconfirmed", "status": field.get("status"),
                    "sources": "See clause evidence", "grain": field.get("grain") or "Unconfirmed",
                    "detail": field, "citations": requirement.get("source_refs", [])})
    return rows


def bundle_zip(bundle: dict) -> bytes:
    if bundle.get("schema") != "case360_review_bundle/1":
        raise ValueError("Unsupported export bundle.")
    if not {"README.md", "provenance.json", "pending.json"} <= bundle["files"].keys():
        raise ValueError("The export is missing provenance or pending decisions.")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in bundle["files"].items():
            if (name.startswith(("/", "\\")) or "\\" in name or ":" in name
                    or any(part in {"", ".", ".."} for part in name.split("/"))):
                raise ValueError("Unsafe export filename.")
            raw = content.encode("utf-8")
            expected = bundle["manifest"].get(name, {})
            if expected != {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}:
                raise ValueError("Export content changed.")
            archive.writestr(name, raw)
        archive.writestr("manifest.json", json.dumps(bundle["manifest"], indent=2))
    return output.getvalue()


def _json(value: object) -> None:
    render_json(value)


def render_result(result: dict, run_id: str | None = None, reference: dict | None = None) -> None:
    ui.label("Execution: " + result["execution_status"]).classes("cf-h2")
    ui.label("Quality: " + result["quality_status"]).classes("cf-h2")
    ui.label("Experimental draft for human review. Compilation is not approval.")
    if result.get("stop_reason"):
        ui.label("Stopped: " + str(result["stop_reason"]))
    if result.get("mode", "synthetic").startswith("synthetic"):
        ui.label("Synthetic evidence and responses.")
    ui.label("Judge evaluation has not been run.")
    ui.label("Real provider calls: " + str(result.get("real_provider_calls", 0)))
    with ui.tabs().classes("w-full") as tabs:
        for title in ("Requirements", "Evidence", "SQL", "Checks", "Review", "Pending", "Cost"):
            ui.tab(title)
    with ui.tab_panels(tabs, value="Requirements").classes("w-full"):
        with ui.tab_panel("Requirements"):
            ui.label("Observed schema is not confirmed meaning or complete coverage.")
            rows = requirement_rows(result)
            columns = [{"name": k, "label": k.title(), "field": k, "align": "left"}
                       for k in ("requirement", "field", "center", "status", "sources", "grain")]
            table = ui.table(columns=columns, rows=rows, row_key="key",
                             selection="single", pagination=12).classes("w-full")
            detail = ui.column().classes("w-full")

            def selected() -> None:
                detail.clear()
                if table.selected:
                    row = table.selected[0]
                    with detail:
                        ui.label(row["statement"])
                        ui.label("Contract citations")
                        _json(row["citations"])
                        ui.label("Source observations, columns, keys and dependencies")
                        _json(row["detail"])
            table.on("selection", selected)
            with ui.expansion("Contract and plan").classes("w-full"):
                _json(result.get("contract"))
                _json(result.get("requirement_plan"))
        with ui.tab_panel("Evidence"):
            ui.label("Snapshots identify the evidence used; they do not certify freshness.")
            evidence = result.get("source_evidence", [])
            if isinstance(evidence, dict):
                evidence = [{"tool": key, "result": value} for key, value in evidence.items()]
            for index, observation in enumerate(evidence):
                with ui.expansion(f"{index + 1}. {observation.get('tool', 'Source evidence')}"):
                    _json(observation)
            if not evidence:
                ui.label("No source evidence recorded.")
        with ui.tab_panel("SQL"):
            ui.label("Draft SQL. Export for review; execution is not offered here.")
            for package in result.get("packages", []):
                with ui.expansion(f"Package {package.get('version', '')}", value=True):
                    ui.label("Package SHA256: " + str(package.get("package_sha256", "Unavailable")))
                    cohort = package.get("package", {}).get("cohort", {}).get("sql")
                    if cohort:
                        ui.label("Cohort")
                        ui.code(cohort, language="sql")
                    for delivery in package.get("deliveries", []):
                        ui.label(str(delivery.get("domain_id", delivery.get("id", "Delivery"))))
                        ui.code(delivery.get("sql", delivery.get("sql_template", "")),
                                language="sql")
                    _json(package.get("unresolved_requirements", []))
        with ui.tab_panel("Checks"):
            ui.label("Compilation, semantic tests and coverage are separate evidence.")
            for index, validation in enumerate(result.get("validations", [])):
                with ui.expansion(f"Validation {index + 1}", value=True):
                    for label, key in (("Compilation / dry run", "compile"),
                                       ("Semantic checks and counterexamples", "semantic")):
                        ui.label(label)
                        _json(validation.get(key, {"cohort": validation.get("cohort_check"),
                              "deliveries": validation.get("domain_checks")}
                              if key == "compile" else None))
                    with ui.expansion("Complete check record"):
                        _json(validation)
        with ui.tab_panel("Review"):
            ui.label("Independent reviewer opinion; human approval is still required.")
            _json(result.get("reviews", []))
            _json(result.get("correctness_verdict"))
        with ui.tab_panel("Pending"):
            _json(result.get("pending_decisions", []))
            _json(result.get("unresolved_obligations", []))
        with ui.tab_panel("Cost"):
            if result.get("ledger_is_synthetic"):
                ui.label("Simulated ledger; these are not newly incurred expenses.")
            _json(result.get("budget"))
            _json(result.get("ledger", []))
            with ui.expansion("Runtime and SDK verification"):
                _json(result.get("runtime_identity"))
                _json(result.get("sdk_attestation"))
    if run_id and reference:
        render_delivery_actions(result, run_id, reference)


def render_delivery_actions(result: dict, run_id: str, reference: dict) -> None:
    profile = preferences.read()
    status = ui.label("Feedback is versioned and does not change the reviewer's original notes.")
    revision = 0
    with ui.expansion("Analyst feedback").classes("w-full"):
        analyst = ui.input("Analyst", value=profile["analyst"])
        environment = ui.input("Environment / installation", value=profile["environment"])
        useful = ui.select({"unset": "Not assessed", "yes": "Useful", "no": "Not useful"},
                           value="unset", label="Usefulness")
        options = {r["id"]: r["statement"] for r in result["contract"]["requirements"]}
        requirements = ui.select(options,
                                 multiple=True, value=[], label="Affected requirements")
        category = ui.select(["general", "missing_source", "incorrect_source", "omission",
                              "semantic_failure"], value="general", label="Feedback category")
        proposal = ui.textarea("Analyst correction or proposal").classes("w-full")
        minutes = ui.number("Correction time (minutes, optional)", min=0, value=None)
        notes = ui.column().classes("w-full")

        async def refresh_feedback() -> None:
            nonlocal revision
            try:
                c = session.client()
                view = await c.request("list_feedback", run_id=run_id)
                history = await c.artifact(run_id, view["artifact"])
                revision = view["revision"]
                notes.clear()
                with notes:
                    _json(history)
                save_button.enable()
            except (RuntimeError, ValueError, OSError, TimeoutError) as error:
                status.text = str(error)

        async def save() -> None:
            save_button.disable()
            try:
                c = session.client()
                selected = await c.request("get_run", run_id=run_id)
                await c.request("save_feedback", {
                    "artifact_sha256": reference["sha256"],
                    "contract_sha256": selected["contract_sha256"],
                    "expected_revision": revision, "analyst": analyst.value,
                    "environment": environment.value,
                    "useful": {"unset": None, "yes": True, "no": False}[useful.value],
                    "requirement_ids": requirements.value, "category": category.value,
                    "proposal": proposal.value or "", "correction_minutes": minutes.value},
                    run_id=run_id)
                await refresh_feedback()
                status.text = "Feedback saved as a new revision. Original reviews are unchanged."
            except (RuntimeError, ValueError, OSError, TimeoutError) as error:
                status.text = str(error)
                save_button.enable()

        ui.button("Load feedback history", on_click=refresh_feedback)
        save_button = ui.button("Save feedback revision", on_click=save)
        save_button.disable()
    with ui.expansion("Export selected review package").classes("w-full"):
        sections = ui.select(["contract", "plan", "requirements", "sql", "sources", "checks",
                              "reviews", "feedback", "accounting"], multiple=True,
                             value=["contract", "requirements", "sql", "checks", "reviews"],
                             label="Include in export").classes("w-full")
        ui.label("Summary, provenance and pending decisions are always included. "
                 "Full prompts, raw traces and credentials are excluded.")
        ui.label("Sources may include selected private evidence. Choose them explicitly.")

        async def export() -> None:
            try:
                c = session.client()
                view = await c.request("get_run", run_id=run_id)
                response = await c.request("create_export", {"artifact_sha256": reference["sha256"],
                    "contract_sha256": view["contract_sha256"], "sections": sections.value},
                    run_id=run_id)
                bundle = await c.artifact(run_id, response["artifact"])
                ui.download(bundle_zip(bundle), filename=response["filename"],
                            media_type="application/zip")
                status.text = ("Selected review package exported with provenance "
                               "and pending decisions.")
            except (RuntimeError, ValueError, OSError, TimeoutError) as error:
                status.text = str(error)
        ui.button("Export selected package", on_click=export)
