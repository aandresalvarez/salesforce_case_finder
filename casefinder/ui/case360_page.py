"""Prepare, confirm, authorize and inspect requests through the private controller."""

from __future__ import annotations

import asyncio
import json

from nicegui import ui

from ..case360 import session


def render_result(result: dict) -> None:
    ui.label("Execution: " + result["execution_status"]).classes("cf-h2")
    ui.label("Quality: " + result["quality_status"]).classes("cf-h2")
    if result.get("stop_reason"):
        ui.label("Stopped: " + str(result["stop_reason"]))
    ui.label("Experimental draft for human review.")
    if result.get("mode", "synthetic").startswith("synthetic"):
        ui.label("Synthetic evidence and responses.")
    ui.label("Judge evaluation has not been run.")
    if result.get("budget"):
        ui.code(json.dumps(result["budget"], indent=2), language="json")
    ui.label("Real provider calls: " + str(result["real_provider_calls"]))
    sections = (("Pending decisions", "pending_decisions"), ("Requirements", "requirements"),
                ("Evidence", "source_evidence"), ("SQL packages", "packages"),
                ("Checks", "validations"), ("Independent review", "reviews"),
                ("SDK verification", "sdk_attestation"))
    for title, key in sections:
        with ui.expansion(title).classes("w-full"):
            ui.code(json.dumps(result.get(key), ensure_ascii=False, indent=2), language="json")


def render_preparation() -> None:
    ui.label("Prepare a new request").classes("cf-h2")
    ui.label("Write one requirement per line. Wording and numbers are preserved for review.")
    request = ui.textarea("Requirements").classes("w-full")
    centers = ui.select(["SHC", "LPCH"], multiple=True, value=["SHC", "LPCH"],
                        label="Requested centers")
    external = ui.input("External case ID (optional)")
    inputs = ui.input("External input names (optional, comma-separated)")
    ui.label("External inputs remain unbound string lists; no values are collected here.")
    status = ui.label("Prepare and inspect the contract before confirming it.")
    panel = ui.column().classes("w-full")
    prepared: dict = {}
    previous: str | None = None
    preflight: dict = {}
    fields = (request, centers, external, inputs)

    def busy(value: bool) -> None:
        for element in (*fields, prepare_button, new_button):
            element.set_enabled(not value)

    def reset_execution() -> None:
        preflight.clear()
        for button in (probe_button, authorize_button, start_button, cancel_button):
            button.disable()
        cap.enable()


    async def prepare() -> None:
        nonlocal previous
        busy(True)
        reset_execution()
        confirm_button.disable()
        try:
            c = session.client()
            prepared.clear()
            prepared.update(await c.request("prepare_request", {
                "text": request.value or "", "centers": centers.value,
                "external_case_id": external.value or None,
                "external_inputs": [name.strip() for name in (inputs.value or "").split(",")
                                    if name.strip()], "previous_run_id": previous}))
            previous = prepared["run_id"]
            artifact = await c.artifact(prepared["run_id"], prepared["artifact"])
            panel.clear()
            with panel:
                ui.label(f"Contract revision {prepared['revision']} · Quality: HOLD")
                ui.code(json.dumps(artifact["contract"], ensure_ascii=False, indent=2),
                        language="json")
                for label, key in (("Resources and coverage", "resources"),
                                   ("Relevant evidence", "source_evidence"),
                                   ("Source comparison", "evidence_alignment"),
                                   ("Execution plan", "execution_plan")):
                    with ui.expansion(label).classes("w-full"):
                        ui.code(json.dumps(artifact[key], ensure_ascii=False, indent=2),
                                language="json")
            status.text = "Prepared locally. Review pending decisions and source coverage."
            confirm_button.enable()
        except (RuntimeError, OSError, ValueError, TimeoutError) as error:
            status.text = str(error)
        finally:
            busy(False)

    async def confirm() -> None:
        confirm_button.disable()
        busy(True)
        try:
            await session.client().request("confirm_contract", {
                "contract_sha256": prepared["contract_sha256"]}, run_id=prepared["run_id"])
            probe_button.enable()
            status.text = ("Contract confirmed. Check the configured connection before "
                           "authorizing a budget. No model request has been sent.")
        except (RuntimeError, OSError, TimeoutError) as error:
            status.text = str(error)
        finally:
            busy(False)

    async def probe() -> None:
        busy(True)
        probe_button.disable()
        authorize_button.disable()
        try:
            preflight.clear()
            preflight.update(await session.client().request("probe_run", run_id=prepared["run_id"]))
            status.text = (f"Verified identity: {preflight['principal']}. "
                           f"Installation limit: ${preflight['max_paid_usd']:g}. "
                           "Connection check expires after five minutes; no model call was made.")
            authorize_button.enable()
        except (RuntimeError, OSError, ValueError, TimeoutError) as error:
            status.text = str(error)
        finally:
            busy(False)
            probe_button.enable()

    async def authorize() -> None:
        busy(True)
        authorize_button.disable()
        probe_button.disable()
        try:
            view = await session.client().request("authorize_run", {
                "contract_sha256": prepared["contract_sha256"],
                "preflight_sha256": preflight["sha256"], "cap_usd": cap.value},
                run_id=prepared["run_id"])
            prepared.update(view)
            cap.disable()
            start_button.enable()
            status.text = (f"Authorized up to ${cap.value:g} for this contract and identity. "
                           "Start when ready. Changes require a new revision and authorization.")
        except (RuntimeError, OSError, ValueError, TimeoutError) as error:
            status.text = str(error)
            probe_button.enable()
        finally:
            busy(False)

    async def start_request() -> None:
        busy(True)
        start_button.disable()
        run_id = prepared["run_id"]
        try:
            c = session.client()
            view = await c.request("start_run", run_id=run_id, request_id="start-" + run_id)
            while view["execution_status"] == "RUNNING":
                cancel_button.enable()
                budget = view.get("budget")
                cost = (f" · Charged or reserved: ${budget['charged_or_reserved_usd']:.4f}"
                        f" · Remaining: ${budget['remaining_usd']:.4f}"
                        f" · Uncertain: ${budget['uncertain_reservation_usd']:.4f}"
                        if budget else " · Budget checkpoint unavailable")
                status.text = "Running: " + view["phase"] + cost
                await asyncio.sleep(0.25)
                view = await c.request("get_run", run_id=run_id)
            status.text = "Execution: " + view["execution_status"] + " · Quality: HOLD"
            if view.get("failure_code"):
                status.text += " · " + view["failure_code"]
            if view.get("artifact"):
                result = await c.artifact(run_id, view["artifact"])
                with panel:
                    if "execution_status" in result:
                        render_result(result)
                    elif view.get("budget"):
                        ui.code(json.dumps(view["budget"], indent=2), language="json")
            if view["execution_status"] == "INTERRUPTED":
                status.text += " · Uncertain reservations are retained."
        except (RuntimeError, OSError, ValueError, TimeoutError) as error:
            status.text = str(error)
        finally:
            cancel_button.disable()
            busy(False)

    async def cancel() -> None:
        cancel_button.disable()
        try:
            await session.client().request("cancel_run", run_id=prepared["run_id"])
        except (RuntimeError, OSError, TimeoutError) as error:
            status.text = str(error)

    def changed() -> None:
        confirm_button.disable()
        reset_execution()
        prepared.clear()
        status.text = "Prepare a new revision to include these changes."

    def new_request() -> None:
        nonlocal previous
        previous = None
        request.value = ""
        external.value = ""
        inputs.value = ""
        panel.clear()
        changed()

    with ui.row():
        prepare_button = ui.button("Prepare request", on_click=prepare)
        confirm_button = ui.button("Confirm request contract", on_click=confirm)
        new_button = ui.button("New request", on_click=new_request)
    cap = ui.number("Maximum spend (USD)", value=None, min=0.01, max=1000, precision=2)
    ui.label("Authorization covers drafting and review. Clinical SQL execution is disabled.")
    with ui.row():
        probe_button = ui.button("Check connection", on_click=probe)
        authorize_button = ui.button("Authorize this budget", on_click=authorize)
        start_button = ui.button("Start authorized request", on_click=start_request)
        cancel_button = ui.button("Cancel request", on_click=cancel)
    reset_execution()
    confirm_button.disable()
    for field in fields:
        field.on_value_change(changed)


def render() -> None:
    ui.label("Case 360 Beta").classes("cf-h1")
    ui.label("Preparation uses local resources and makes no paid calls.")
    ui.label("Requests and evidence are retained locally. "
             "Manual cleanup is planned for the history view.")
    render_preparation()
    with ui.expansion("Synthetic demonstration"):
        render_demo()


def render_demo() -> None:
    ui.label("Case 360 Beta · Offline preview").classes("cf-h1")
    ui.label("Synthetic demonstration only. No credentials or paid calls are used.")
    ui.label("This preview retains local runs; history, cleanup and recovery are later phases.")
    upper = ui.number("Synthetic upper bound", value=10, min=2, max=100, precision=0)
    status = ui.label("Prepare a synthetic contract to begin.").classes("cf-muted")
    actions = ui.row()
    contract_panel = ui.column().classes("w-full").style("max-height:420px;overflow:auto")
    result_panel = ui.column().classes("w-full")
    prepared: dict = {}

    async def prepare() -> None:
        prepare_button.disable()
        confirm_button.disable()
        start_button.disable()
        try:
            if (not isinstance(upper.value, int | float) or upper.value != int(upper.value)
                    or not 2 <= upper.value <= 100):
                raise ValueError("Choose a whole-number synthetic bound between 2 and 100.")
            c = session.client()
            check = await c.request("health")
            if not check["ready"]:
                status.text = "Local runtime needs preparation: " + ", ".join(
                    k for k, ok in check["checks"].items() if not ok)
                return
            prepared.clear()
            prepared.update(await c.request("prepare_run", {
                "mode": "synthetic", "upper_bound": int(upper.value)}))
            contract_panel.clear()
            result_panel.clear()
            with contract_panel:
                ui.label("Confirm this exact contract before starting.")
                ui.code(json.dumps(prepared["contract"], ensure_ascii=False, indent=2),
                        language="json")
            status.text = "Contract ready for review. The follow-up window remains pending."
            confirm_button.enable()
        except (RuntimeError, OSError, ValueError, TimeoutError) as error:
            status.text = str(error)
        finally:
            prepare_button.enable()

    async def confirm() -> None:
        confirm_button.disable()
        try:
            await session.client().request("confirm_contract", {
                "contract_sha256": prepared["contract_sha256"]}, run_id=prepared["run_id"])
            start_button.enable()
            status.text = "Contract confirmed. Ready to start the synthetic run."
        except (RuntimeError, OSError, TimeoutError) as error:
            status.text = str(error)

    async def start() -> None:
        start_button.disable()
        prepare_button.disable()
        upper.disable()
        run_id = prepared["run_id"]
        try:
            c = session.client()
            view = await c.request("start_run", run_id=run_id, request_id="start-" + run_id)
            while view["execution_status"] == "RUNNING":
                status.text = "Running: " + view["phase"]
                await asyncio.sleep(0.25)
                view = await c.request("get_run", run_id=run_id)
            status.text = "Execution: " + view["execution_status"] + " · Quality: HOLD"
            if view.get("artifact"):
                result = await c.artifact(run_id, view["artifact"])
                result_panel.clear()
                with result_panel:
                    render_result(result)
        except (RuntimeError, OSError, ValueError, TimeoutError) as error:
            status.text = str(error)
        finally:
            prepare_button.enable()
            upper.enable()

    with actions:
        prepare_button = ui.button("Prepare synthetic request", on_click=prepare)
        confirm_button = ui.button("Confirm contract", on_click=confirm)
        start_button = ui.button("Run synthetic demonstration", on_click=start)
    confirm_button.disable()
    start_button.disable()

    def changed() -> None:
        confirm_button.disable()
        start_button.disable()
        prepared.clear()
        status.text = "Prepare a new contract for the changed synthetic bound."

    upper.on_value_change(changed)
