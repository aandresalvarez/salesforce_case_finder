"""First offline route: explicit synthetic contract, real harness, separate quality."""

from __future__ import annotations

import asyncio
import json

from nicegui import ui

from ..case360 import session


def render_result(result: dict) -> None:
    ui.label("Execution: " + result["execution_status"]).classes("cf-h2")
    ui.label("Quality: " + result["quality_status"]).classes("cf-h2")
    ui.label("Experimental draft for human review. Synthetic evidence and responses.")
    ui.label("Real provider calls: " + str(result["real_provider_calls"]))
    sections = (("Pending decisions", "pending_decisions"), ("Requirements", "requirements"),
                ("Evidence", "source_evidence"), ("SQL packages", "packages"),
                ("Checks", "validations"), ("Independent review", "reviews"),
                ("SDK verification", "sdk_attestation"))
    for title, key in sections:
        with ui.expansion(title).classes("w-full"):
            ui.code(json.dumps(result.get(key), ensure_ascii=False, indent=2), language="json")


def render() -> None:
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
