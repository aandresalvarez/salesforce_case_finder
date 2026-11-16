"""Two-step onboarding with explicit identity, access and ready states."""

from __future__ import annotations

import json

from nicegui import ui

from ..case360 import onboarding, session
from ..case360.runtime import discover
from .components.actions import muted, primary, secondary


def render_welcome() -> None:
    runtime = discover()
    if not runtime.context_file:
        ui.label("Install the complete private tester package to begin.")
        return
    context_file = runtime.context_file
    context = json.loads(context_file.read_text())
    signed = bool(context.get("google_account"))
    ready = onboarding.access_ready(context)
    busy = False
    signing = False

    with ui.column().classes("w-full cf-reading").style("max-width:820px;gap:16px"):
        with ui.column().style("gap:8px"):
            ui.label("WELCOME TO CASE 360").style(
                "color:#4263b4;font-size:12px;letter-spacing:.1em;font-weight:700"
            )
            ui.label("Set up your beta").classes("cf-h1")
            muted("Two steps to get started. Your requests and settings stay on this computer.")
        with (
            ui.card()
            .classes("w-full")
            .props("flat bordered")
            .style("padding:20px;border-radius:14px;gap:12px")
        ):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("1. Sign in").classes("cf-h2")
                sign_badge = ui.badge(
                    "Signed in" if signed else "Not signed in",
                    color="positive" if signed else "grey-7",
                )
            identity = ui.label(
                "Signed in: " + context["google_account"] if signed else "Connect your work account"
            ).style("font-weight:600")
            email = (
                ui.input("Your work email", value=context.get("google_account", ""))
                .classes("w-full")
                .props("dense outlined")
            )
            muted(
                "Google/Stanford verifies your account in the browser. "
                "Return here after signing in."
            )
            sign_status = ui.label(
                "Account connected. Next, check your access."
                if signed
                else "Sign in to connect your account."
            ).props('role="status" aria-live="polite"')

            async def sign_in() -> None:
                nonlocal signed, ready, busy, signing
                busy, ready, signing = True, False, True
                refresh()
                sign_badge.set_text("Signing in…")
                sign_badge.props("color=blue")
                sign_status.text = (
                    "Checking saved sign-in. Complete Google/Stanford sign-in if a browser opens…"
                )
                cancel.enable()
                try:
                    await session.prepare_reconfigure()
                    await onboarding.sign_in((email.value or "").strip(), context_file)
                    signed = True
                    identity.text = (
                        "Signed in: " + json.loads(context_file.read_text())["google_account"]
                    )
                    sign_status.text = "Account verified. Next, select Check my access."
                    access_status.text = "Ready to check your data and model permissions."
                except (onboarding.SetupError, RuntimeError) as error:
                    signed = bool(json.loads(context_file.read_text()).get("google_account"))
                    sign_status.text = str(error)
                except Exception:  # noqa: BLE001 - never expose credential diagnostics
                    sign_status.text = "Sign-in could not finish. Check your network and try again."
                finally:
                    busy = signing = False
                    cancel.disable()
                    refresh()

            with ui.row():
                sign = secondary("Change account" if signed else "Sign in with Google", sign_in)
                cancel = secondary("Cancel sign-in", onboarding.cancel_login)
                cancel.disable()
                cancel.set_visibility(False)
        with (
            ui.card()
            .classes("w-full")
            .props("flat bordered")
            .style("padding:20px;border-radius:14px;gap:12px")
        ):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("2. Check access").classes("cf-h2")
                access_badge = ui.badge(
                    "Ready" if ready else "Not checked", color="positive" if ready else "grey-7"
                )
            muted(
                "Check your access to Epic documentation, SHC/LPCH metadata, STARR and the model "
                "project. No paid model call or data query is executed."
            )
            access_status = ui.label(
                "Access checks passed. You're ready to continue."
                if ready
                else "Select Check my access to verify your permissions."
                if signed
                else "Sign in first, then check your access."
            ).props('role="status" aria-live="polite"')
            with ui.expansion("Access check details").classes("w-full"):
                results = ui.column().classes("w-full")
                with results:
                    for item in context.get("setup_access", {}).get("checks", []) if ready else []:
                        ui.label(item["name"] + ": " + item["detail"])

            async def check() -> None:
                nonlocal ready, busy
                busy, ready = True, False
                refresh()
                access_badge.set_text("Checking…")
                access_badge.props("color=blue")
                access_status.text = (
                    "Checking identity and permissions. This may take up to a minute…"
                )
                results.clear()
                try:
                    checks = await onboarding.check_access(context_file)
                    with results:
                        for item in checks:
                            with ui.row().classes("items-center"):
                                ui.icon(
                                    "check_circle" if item["passed"] else "error_outline",
                                    color="positive" if item["passed"] else "negative",
                                )
                                ui.label(item["name"] + ": " + item["detail"])
                    ready = onboarding.access_ready(json.loads(context_file.read_text()))
                    access_status.text = (
                        "Access checks passed. You're ready to continue."
                        if ready
                        else "Some access is missing. Check VPN and review the details below."
                    )
                except onboarding.SetupError as error:
                    access_status.text = str(error)
                except Exception:  # noqa: BLE001 - never expose credential diagnostics
                    access_status.text = (
                        "Could not check access. Connect to Stanford VPN and try again."
                    )
                finally:
                    busy = False
                    refresh()

            check_button = secondary("Check my access", check)
        with ui.column().classes("w-full").style("gap:12px"):
            continue_status = ui.label("Complete both steps to start working.").props(
                'role="status"'
            )

            async def continue_setup() -> None:
                nonlocal busy, ready
                busy = True
                refresh()
                try:
                    await session.prepare_reconfigure()
                    onboarding.complete_setup(context_file)
                    ui.navigate.to("/case360")
                except (ValueError, RuntimeError, OSError) as error:
                    ready = onboarding.access_ready(json.loads(context_file.read_text()))
                    continue_status.text = str(error)
                finally:
                    busy = False
                    refresh(update_message=False)

            start = primary("Continue to Case 360", continue_setup)
            start.props("icon=arrow_forward")
            muted(
                "Pilot budget is already configured. You can change limits in Beta settings. "
                "Continuing does not start a paid request."
            )
            ui.link("Beta settings", "/case360/settings")

        def refresh(update_message: bool = True) -> None:
            sign.set_text("Change account" if signed else "Sign in with Google")
            sign.set_enabled(not busy)
            email.set_enabled(not busy)
            cancel.set_visibility(signing)
            check_button.set_enabled(signed and not busy)
            start.set_enabled(signed and ready and not busy)
            sign_badge.set_text("Signed in" if signed else "Not signed in")
            sign_badge.props("color=positive" if signed else "color=grey-7")
            access_badge.set_text("Ready" if ready else "Not checked")
            access_badge.props("color=positive" if ready else "color=grey-7")
            if update_message:
                continue_status.text = (
                    "You're ready. Continue to describe your first request."
                    if ready
                    else "Complete both steps to start working."
                )

        refresh()
        with ui.expansion("Help with setup").classes("w-full"):
            ui.label(
                "Use Windows x64 or a supported Mac. "
                "Connect to Stanford VPN if required. "
                "Signing in does not grant data or model permissions; the pilot owner must grant "
                "them to your account."
            )
            ui.label(
                "If sign-in expires, return here to reconnect. "
                "Your saved work and budget usage are "
                "preserved. Model availability is checked on your first request."
            )
