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
    "INTAKE": "Interpretando tu solicitud",
    "AUTHOR_EVIDENCE": "Buscando fuentes y comprobando columnas",
    "AUTHOR_GENERATION": "Construyendo el SQL",
    "TARGETED_SOURCE_RESOLUTION": "Comprobando fuentes pendientes",
    "TARGETED_REPAIR": "Corrigiendo el SQL con la revisión",
    "SAME_SESSION_REPAIR": "Corrigiendo el SQL con la revisión",
    "WAITING_CLARIFICATION": "Necesito tus respuestas para continuar",
    "WAITING_FINAL_CLARIFICATION": "La revisión encontró decisiones pendientes",
}
MODEL_PHASES = {
    "intake": "Interpretación de la petición",
    "evidence-1": "Búsqueda de fuentes",
    "evidence-2": "Verificación de fuentes",
    "generate": "Generación del SQL",
    "review": "Revisión independiente",
    "final-review": "Revisión final",
}


def configured_cap() -> float:
    location = discover().context_file
    policy = json.loads(location.read_text())["authorization_policy"] if location else {}
    if not policy.get("live_enabled") or policy.get("max_paid_usd", 0) <= 0:
        raise ValueError("Completa la conexión y el presupuesto en Ajustes para comenzar.")
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
        return PHASES.get(item.get("stage"), "Procesando la solicitud")
    if kind == "model":
        return MODEL_PHASES.get(item.get("phase"), "Análisis y revisión del agente")
    if kind == "sources_retrieved":
        return "Consulté el índice local de fuentes de esta instalación"
    tool = {"inspect_table_schema": "Esquema de BigQuery",
            "starr_prior_lookup": "Índice de fuentes",
            "historical_sql_search": "Patrones y documentación"}.get(
                item.get("tool"), item.get("tool", "Fuente"))
    verb = "Consultando" if kind == "source_started" else "Respuesta recibida de"
    return f"{verb} {tool}" + (f": {item['query']}" if item.get("query") else "")


def render_sources(preparation: dict) -> None:
    evidence = preparation.get("source_evidence") or {}
    if not isinstance(evidence, dict):
        return
    names = []
    for row in evidence.get("sources", []):
        names.append("BigQuery · " + str(row.get("table", "Fuente candidata")))
    for row in evidence.get("documentation", []):
        names.append("Epic · " + str(row.get("table_name", "Documento")))
    for row in evidence.get("repository_documents", []):
        names.append("STARR · " + str(row.get("path", row.get("id", "Definición"))))
    with ui.expansion(f"Fuentes encontradas · {len(names)}", value=bool(names)).classes("w-full"):
        ui.label("Evidencia del snapshot importado. La disponibilidad y el significado "
                 "se comprueban durante el análisis.").classes("text-sm text-slate-500")
        for name in names[:12]:
            ui.label(name).classes("text-sm break-all")
        if not names:
            ui.label("La búsqueda inicial no encontró candidatos; "
                     "el agente puede ampliar la búsqueda.")
        with ui.expansion("Ver evidencia y cobertura completas").classes("w-full"):
            render_json({"resources": preparation.get("resources"), "evidence": evidence},
                        "case360-fuentes.json")


def render(*, run_id: str | None = None) -> None:
    state: dict = {"run_id": run_id, "busy": False, "last_seq": 0, "remaining": None,
                   "pending": None, "consent_cap": None}
    with ui.column().classes("w-full").style("max-width:900px;margin:0 auto;gap:20px"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("Case 360").style("font-size:20px;font-weight:650")
            with ui.row().classes("gap-4"):
                ui.link("Historial y limpiar datos", "/case360/history")
                ui.link("Ajustes", "/settings")
        ui.label("¿Qué datos necesitas?").style("font-size:32px;font-weight:600;margin-top:32px")
        ui.label("Describe tu petición con tus palabras. Consultaré las fuentes y te "
                 "preguntaré lo necesario antes de construir el SQL.").classes("text-slate-600")
        request = ui.textarea("Tu petición", placeholder="Describe la población, los datos "
                              "que necesitas y cualquier condición que ya conozcas.").props(
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
                    ui.label("Actividad del agente").classes("font-medium")
                    for item in items[-6:]:
                        ui.label(progress_text(item)).classes("text-sm break-all")
                    with ui.expansion("Ver actividad registrada").classes("w-full"):
                        for item in items:
                            ui.label(progress_text(item)).classes("text-sm break-all")
            budget = view.get("budget")
            if budget:
                total = budget["charged_or_reserved_usd"] + state.get("spent_before", 0)
                consent.text = (f"Solicitud: ${total:.4f} USD "
                                f"usados o reservados · ${budget['remaining_usd']:.2f} "
                                "disponibles.")

        async def inspect(view: dict) -> None:
            c = session.client()
            while view["execution_status"] in {"STARTING", "RUNNING", "CANCEL_REQUESTED"}:
                busy(True)
                show_progress(view)
                status.text = (progress_text(view["progress"][-1]) if view.get("progress")
                               else "Iniciando el análisis…")
                await asyncio.sleep(0.7)
                view = await c.request("get_run", run_id=state["run_id"])
            show_progress(view)
            result = await c.artifact(state["run_id"], view["artifact"])
            dialogue.clear()
            conversation = result.get("conversation", {})
            if conversation.get("answers"):
                with dialogue, ui.expansion("Tus aclaraciones").classes("w-full"):
                    for answer in conversation["answers"]:
                        ui.label(answer["question"]).classes("font-medium")
                        ui.label(answer["text"])
            if conversation.get("waiting"):
                status.text = "Necesito aclarar lo siguiente antes de continuar."
                state["remaining"] = result["budget"]["remaining_usd"]
                with dialogue:
                    if result.get("interpretation"):
                        ui.label(result["interpretation"]).classes("text-slate-700")
                    answers = {}
                    for question in result.get("questions", [])[:12]:
                        ui.label(question["text"]).classes("font-medium")
                        answers[question["id"]] = ui.textarea("Tu respuesta").props(
                            "outlined autogrow maxlength=900").classes("w-full")
                    ui.label(f"Continuar usa el presupuesto restante: hasta "
                             f"${state['remaining']:.2f} USD.").classes("text-sm text-slate-500")

                    async def answer() -> None:
                        if any(not (field.value or "").strip() for field in answers.values()):
                            status.text = "Responde cada pregunta. Si no lo sabes, indícalo."
                            return
                        next_button.disable()
                        await launch([{"question_id": key, "text": field.value}
                                      for key, field in answers.items()])
                        if not state["busy"]:
                            next_button.enable()

                    next_button = ui.button("Continuar con mis respuestas", on_click=answer)
            elif "execution_status" in result:
                status.text = ("SQL preparado para tu revisión." if result.get("packages")
                               else "El análisis no pudo completar el SQL. Revisa el resultado.")
            else:
                status.text = "Solicitud guardada; todavía no se ha iniciado el análisis."
                state["pending"] = view
                state["remaining"] = conversation.get("remaining_cap_usd")
                if not view.get("authorized"):
                    with dialogue:
                        retry = ui.button("Continuar esta solicitud",
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
                status.text = "Escribe una petición para comenzar."
                return
            if answers is None and (len(text) > 20000 or len(text.encode()) > 24000):
                status.text = "La petición es demasiado larga. Usa hasta 20.000 caracteres y 24 KB."
                return
            busy(True)
            try:
                cap = (state["remaining"] if answers is not None
                       else min(configured_cap(), state["consent_cap"] or configured_cap()))
                c = session.client()
                status.text = "Buscando evidencia en los recursos de esta instalación…"
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
                status.text = "No pude continuar: " + str(error)
                if state["pending"]:
                    dialogue.clear()
                    with dialogue:
                        ui.button("Reintentar conexión", on_click=lambda: retry_pending())
            finally:
                busy(False)

        async def start_prepared(prepared: dict, cap: float) -> None:
            c = session.client()
            await c.request("confirm_contract", {
                "contract_sha256": prepared["contract_sha256"]}, run_id=state["run_id"])
            status.text = "Comprobando tu conexión y el presupuesto…"
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
                status.text = "No pude continuar: " + str(error)
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
                consent.text = (f"Al pulsar Analizar autorizas hasta ${cap:g} USD para esta "
                                "solicitud, incluidas aclaraciones y revisión. "
                                "El SQL no se ejecuta.")
            except ERRORS as error:
                consent.text = str(error)

        with actions:
            submit = ui.button("Analizar solicitud", on_click=lambda: launch()).props(
                "unelevated no-caps")
            cancel = ui.button("Detener", on_click=stop).props("flat no-caps")
            new = ui.button("Nueva solicitud", on_click=reset).props("flat no-caps")
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
                status.text = "No pude abrir la solicitud guardada: " + str(error)
            finally:
                busy(False)

        ui.timer(0.1, restore, once=True)
