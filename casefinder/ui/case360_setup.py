"""Analyst and installation settings are editable local configuration."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from nicegui import ui

from ..case360 import package, preferences, session


def render_setup() -> None:
    profile = preferences.read()
    with ui.expansion("Analyst and installation settings").classes("w-full"):
        ui.label("Configure this installation for any analyst. "
                 "No user or host is built into the app.")
        analyst = ui.input("Analyst label", value=profile["analyst"])
        environment = ui.input("Environment label", value=profile["environment"])
        context = ui.input("Runtime configuration file", value=profile["runtime_context"])
        ui.label("A packaged installation supplies its runtime automatically. "
                 "Use an explicit file only to select another prepared runtime.")
        status = ui.label("No credentials are stored in this profile.")
        detail = ui.column().classes("w-full")

        async def save() -> None:
            try:
                await session.prepare_reconfigure()
                preferences.save(analyst.value or "", environment.value or "", context.value or "")
                status.text = ("Profile saved. New requests use this configuration; "
                               "saved work is retained.")
            except (RuntimeError, OSError, ValueError, TimeoutError) as error:
                status.text = str(error)

        async def check() -> None:
            try:
                c = await session.reconnect()
                hello = await c.request("hello")
                health = await c.request("health")
                resources = await c.request("resource_status") if health["explicit_context"] else {}
                detail.clear()
                with detail:
                    ui.label("Runtime: " + hello["engine_version"])
                    ui.label("Ready" if health["ready"] else "Preparation required")
                    ui.code(json.dumps({"checks": health["checks"], "resources": resources},
                                       indent=2), language="json")
                status.text = "Local check completed. No model call or remote probe was made."
            except (RuntimeError, OSError, ValueError, TimeoutError) as error:
                status.text = str(error)

        ui.button("Save analyst settings", on_click=save)
        ui.button("Check local installation", on_click=check)
        render_resources()
        render_updates()
        render_pilot()


def render_resources() -> None:
    with ui.expansion("Resources and connection policy").classes("w-full"):
        ui.label("Import prepared documentation and metadata files. This step is local. "
                 "A snapshot records evidence used; it does not certify freshness.")
        fields = {name: ui.input(label) for name, label in (
            ("profile", "Source profile JSON"), ("metadata", "SHC and LPCH metadata JSON"),
            ("epic-export", "Epic documentation export JSON (optional)"),
            ("epic-index", "Epic documentation index JSON (optional)"),
            ("repository", "STARR repository metadata JSON (optional)"))}
        snapshot = ui.input("Resource snapshot SHA256")
        principal = ui.input("Expected Google account")
        cap = ui.number("Maximum authorized budget in USD (0 disables live)", value=0, min=0)
        route = ui.input("Verified route proof SHA256")
        ui.label("Saving a policy makes no remote call. Each request still needs connection "
                 "verification, a confirmed contract and explicit budget authorization.")
        status = ui.label("")

        async def import_resources() -> None:
            try:
                await session.prepare_reconfigure()
                from ..case360.runtime import discover

                runtime = discover()
                if not runtime.context_file:
                    raise ValueError("Select an installed runtime first.")
                context = json.loads(runtime.context_file.read_text())
                arguments = [context["python_executable"], "-B",
                             str(runtime.engine_root / "desktop_bridge/resources.py"),
                             "--root", context["resource_root"]]
                for key, element in fields.items():
                    if element.value:
                        arguments += ["--" + key, str(Path(element.value).expanduser().resolve())]
                process = await asyncio.create_subprocess_exec(
                    *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                output, _ = await asyncio.wait_for(process.communicate(), 120)
                if process.returncode:
                    raise ValueError("Resource import failed. Verify the prepared files "
                                     "and profile.")
                value = json.loads(output)
                snapshot.value = value.get("version", value.get("snapshot", ""))
                status.text = "Resources imported: " + output.decode()
            except (RuntimeError, OSError, ValueError, TimeoutError) as error:
                status.text = str(error)

        async def save_policy() -> None:
            try:
                await session.prepare_reconfigure()
                from ..case360.runtime import discover

                context = discover().context_file
                if context is None:
                    raise ValueError("Select an installed runtime first.")
                package.configure(context, snapshot.value or "", principal.value or "",
                                  float(cap.value or 0), route.value or "")
                status.text = "Policy saved. Existing request authorizations remain version-bound."
            except (RuntimeError, OSError, ValueError, TimeoutError) as error:
                status.text = str(error)

        ui.button("Import prepared resources", on_click=import_resources)
        ui.button("Save resource and connection policy", on_click=save_policy)


def render_updates() -> None:
    with ui.expansion("Private packages and rollback").classes("w-full"):
        ui.label("Use a package and manifest digest delivered through the private channel. "
                 "Previous versions and their requests are retained.")
        source = ui.input("Package Resources folder")
        checksum = ui.input("Manifest SHA256 from private delivery")
        versions = ui.select([str(p) for p in package.installed()], label="Installed version")
        status = ui.label("")

        async def install() -> None:
            try:
                target = await asyncio.to_thread(package.install, Path(source.value).expanduser(),
                                                checksum.value or "")
                versions.set_options([str(p) for p in package.installed()], value=str(target))
                status.text = "Package verified and installed. Select it to activate."
            except (OSError, ValueError, KeyError) as error:
                status.text = str(error)

        async def activate() -> None:
            try:
                await session.prepare_reconfigure()
                await asyncio.to_thread(package.activate, Path(versions.value))
                profile = preferences.read()
                preferences.save(profile["analyst"], profile["environment"], "")
                status.text = "Version selected. Close and reopen the app to use it. " \
                              "Earlier requests remain available by selecting their version."
            except (RuntimeError, OSError, ValueError, TypeError, TimeoutError) as error:
                status.text = str(error)

        ui.button("Install private package", on_click=install)
        ui.button("Activate selected version / rollback", on_click=activate)


def render_pilot() -> None:
    with ui.expansion("Pilot assessment").classes("w-full"):
        ui.label("Record the analyst's own assessment for this installation. "
                 "This does not certify another account or approve clinical SQL.")
        checks = {name: ui.checkbox(label) for name, label in (
            ("clean_install", "Installed with this analyst's account"),
            ("synthetic_journey", "Completed the synthetic journey"),
            ("recovery", "Verified interruption and recovery"),
            ("cleanup", "Verified retention and manual cleaning"))}
        decision = ui.select(["DEMO_ONLY", "BLOCKED", "LIMITED_PILOT"], value="DEMO_ONLY",
                             label="Pilot decision")
        notes = ui.textarea("Reasons, failures and remaining limitations")
        status = ui.label("")

        async def record() -> None:
            try:
                profile = preferences.read()
                if not profile["analyst"] or not profile["environment"]:
                    raise ValueError("Save the analyst and environment labels first.")
                client = session.client()
                history = await session.history(client)
                value = {"schema": "case360_pilot_assessment/1", "profile": profile,
                         "human_report": True, "independent_identity_verified": False,
                         "checks": {k: v.value for k, v in checks.items()},
                         "decision": decision.value, "notes": notes.value, "history": history}
                raw = json.dumps(value, ensure_ascii=False, indent=2).encode()
                name = "pilot-" + hashlib.sha256(raw).hexdigest() + ".json"
                preferences.atomic_json(preferences.data_root() / "pilot" / name, value)
                ui.download(raw, name, media_type="application/json")
                status.text = "Assessment recorded. Per-requirement corrections and time " \
                              "are recorded in each request's feedback."
            except (RuntimeError, OSError, ValueError, TimeoutError) as error:
                status.text = str(error)

        ui.button("Record and export pilot assessment", on_click=record)
