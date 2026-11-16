"""A tester-facing setup flow; advanced resource paths stay out of this screen."""

from __future__ import annotations

import json

from nicegui import ui

from ..case360 import onboarding, preferences, session
from ..case360.runtime import discover
from .components.actions import muted, primary, secondary


def render_welcome() -> None:
    runtime = discover()
    if not runtime.context_file:
        ui.label("Install the complete private tester package to begin.")
        return
    context_file = runtime.context_file
    context = json.loads(context_file.read_text())
    with ui.column().classes("w-full cf-reading").style("max-width:780px;gap:20px"):
        ui.label("Set up your beta").classes("cf-h1")
        muted("Use your own work account. Your requests and settings stay on this Mac.")
        with ui.card().classes("w-full").props("flat bordered"):
            ui.label("1. Sign in").classes("cf-h2")
            email = ui.input("Your work email", value=context.get("google_account", "")).classes(
                "w-full"
            )
            muted(
                "Complete your organization's Google sign-in in the browser, then return here."
            )
            identity = ui.label(
                "Signed in: " + context["google_account"]
                if context.get("google_account")
                else "Not signed in"
            )
            sign_status = ui.label("").props('role="status"')

            async def sign_in() -> None:
                sign.disable()
                email.disable()
                cancel.enable()
                sign_status.text = "Waiting for Google sign-in in your browser…"
                try:
                    await session.prepare_reconfigure()
                    await onboarding.sign_in((email.value or "").strip(), context_file)
                    identity.text = "Signed in: " + (email.value or "").strip()
                    sign_status.text = "Your account is verified. Check access below."
                except (onboarding.SetupError, RuntimeError) as error:
                    sign_status.text = str(error)
                except Exception:  # noqa: BLE001 - never expose provider credential diagnostics
                    sign_status.text = "Sign-in could not finish. Check your network and try again."
                finally:
                    sign.enable()
                    email.enable()
                    cancel.disable()

            with ui.row():
                sign = primary("Sign in with Google", sign_in)
                cancel = secondary("Cancel sign-in", onboarding.cancel_login)
                cancel.disable()
        with ui.card().classes("w-full").props("flat bordered"):
            ui.label("2. Check access").classes("cf-h2")
            muted(
                "Epic documentation, SHC/LPCH metadata and STARR definitions are included. "
                "This checks your account and runs a compilation probe. "
                "No model call or data query is executed."
            )
            access_status = ui.label("").props('role="status"')
            results = ui.column().classes("w-full")

            async def check() -> None:
                check_button.disable()
                access_status.text = "Checking your account and pilot resources…"
                results.clear()
                try:
                    checks = await onboarding.check_access(context_file)
                    with results:
                        for item in checks:
                            with ui.row().classes("items-center"):
                                ui.icon("check_circle" if item["passed"] else "error_outline")
                                ui.label(item["name"] + ": " + item["detail"])
                    access_status.text = (
                        "Access checks passed. Choose your budget below."
                        if all(c["passed"] for c in checks)
                        else "Some access is missing. Check VPN, then share the resource names "
                        "with your access administrator."
                    )
                except onboarding.SetupError as error:
                    access_status.text = str(error)
                except Exception:  # noqa: BLE001 - never expose provider credential diagnostics
                    access_status.text = (
                        "Could not check access. Connect to the Stanford VPN and try again."
                    )
                finally:
                    check_button.enable()

            check_button = secondary("Check my access", check)
        with ui.card().classes("w-full").props("flat bordered"):
            ui.label("3. Choose your request budget").classes("cf-h2")
            profile = preferences.read()
            analyst = ui.input("Your name or tester label", value=profile["analyst"])
            cap = ui.number(
                "Maximum USD per request",
                value=context.get("authorization_policy", {}).get("max_paid_usd", 0),
                min=0,
                max=1000,
            )
            muted(
                "Saving does not spend money. Analyze request authorizes work within this limit. "
                "Zero keeps live analysis disabled. SQL is validated with dry runs, not executed."
            )
            budget_status = ui.label("").props('role="status"')

            async def save() -> None:
                try:
                    await session.prepare_reconfigure()
                    onboarding.save_budget(context_file, float(cap.value or 0))
                    preferences.save(
                        analyst.value or "",
                        profile["environment"] or "Private Mac pilot",
                        profile["runtime_context"],
                    )
                    budget_status.text = (
                        "Settings saved. You can start a request."
                        if cap.value
                        else "Settings saved. Live analysis is disabled."
                    )
                    start.set_visibility(bool(cap.value))
                except (ValueError, RuntimeError) as error:
                    budget_status.text = str(error)

            secondary("Save my settings", save)
            start = ui.link("Start a request", "/case360")
            start.set_visibility(bool(context.get("authorization_policy", {}).get("live_enabled")))
        with ui.expansion("Help with setup").classes("w-full"):
            ui.label(
                "Use Apple Silicon and macOS 13 or later. Connect to Stanford VPN if required. "
                "Signing in does not grant data or model permissions. "
                "The pilot owner must grant them to your account."
            )
            ui.label(
                "If Google sign-in expires, return here and select Sign in with Google. "
                "Your requests, answers and remaining budgets are preserved."
            )
            ui.link("Advanced beta settings", "/case360/settings")
