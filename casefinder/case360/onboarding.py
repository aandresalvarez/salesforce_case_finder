"""Private pilot setup: included resources and an isolated, user-owned Google login.

No developer credentials, ambient gcloud configuration or paid model calls are
used here. The browser owns password/MFA entry; the app never collects them.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from . import package, platforms, preferences


class SetupError(ValueError):
    """A message safe to show without provider diagnostics or credentials."""


_login_process: asyncio.subprocess.Process | None = None
_login_lock = asyncio.Lock()
_login_cancelled = False
_CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
# A cloud-only refreshed token may omit the email needed for identity checks.
_SCOPES = [_CLOUD_SCOPE, "https://www.googleapis.com/auth/userinfo.email"]


def bundle_root() -> Path | None:
    raw = os.environ.get("CASE360_BUNDLE_ROOT")
    return Path(raw).resolve(strict=True) if raw else None


def pilot(root: Path | None = None) -> dict | None:
    root = root or bundle_root()
    file = root / "pilot-resources/bootstrap.json" if root else None
    if not file or not file.is_file():
        return None
    value = json.loads(file.read_text())
    if (
        value.get("schema") != "case360_pilot_bootstrap/1"
        or not re.fullmatch(r"[a-f0-9]{64}", value.get("snapshot", ""))
        or not re.fullmatch(r"[a-f0-9]{64}", value.get("route_sha256", ""))
    ):
        raise SetupError("The private pilot resources are incompatible. Reinstall this beta.")
    return value


def provision(root: Path, context_file: Path) -> None:
    """Called only after release inventory verification; never replaces a selection."""
    settings = pilot(root)
    if not settings:
        return
    context = json.loads(context_file.read_text())
    source = root / "pilot-resources"
    resources = Path(context["resource_root"])
    resources.mkdir(parents=True, exist_ok=True, mode=0o700)
    if resources.resolve() != resources:
        raise SetupError("Resource storage must not contain links.")
    snapshot = settings["snapshot"]
    target = resources / snapshot
    if not target.exists():
        temporary = resources / (".setup-" + uuid.uuid4().hex)
        shutil.copytree(source / snapshot, temporary)
        temporary.rename(target)
    route_name = "vertex_serving_route_verification.json"
    route = resources / route_name
    if not route.exists():
        route.write_bytes((source / route_name).read_bytes())
        route.chmod(0o600)
    if not context.get("source_profile"):
        context["source_profile"] = snapshot
    # Missing explicit ADC must fail closed instead of falling back to a host account.
    if "google_credentials" not in context:
        context["google_credentials"] = str(preferences.data_root() / "google/pending")
    preferences.atomic_json(context_file, context)


def credential_environment(root: Path, directory: Path) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not directory.is_absolute() or directory.resolve() != directory:
        raise SetupError("Google sign-in storage must not contain links.")
    directory.chmod(0o700)
    names = ("HOME", "USER", "TMPDIR", "LANG", "LC_ALL", "SSL_CERT_FILE",
             "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE",
             "LOCALAPPDATA", "APPDATA", "TEMP", "TMP")
    return {
        **{k: os.environ[k] for k in names if k in os.environ},
        "PATH": os.pathsep.join([str(root / "google-cloud-sdk/bin"),
            str(Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "System32")]
            if os.name == "nt" else [str(root / "google-cloud-sdk/bin"),
                                    "/usr/bin", "/bin", "/usr/sbin", "/sbin"]),
        "CLOUDSDK_CONFIG": str(directory),
        "GOOGLE_APPLICATION_CREDENTIALS": str(directory / "application_default_credentials.json"),
        "CLOUDSDK_PYTHON": str(platforms.python_path(root)),
        "CLOUDSDK_PYTHON_SITEPACKAGES": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "CLOUDSDK_CORE_DISABLE_USAGE_REPORTING": "true",
        "CLOUDSDK_CORE_DISABLE_FILE_LOGGING": "true",
        "CLOUDSDK_COMPONENT_MANAGER_DISABLE_UPDATE_CHECK": "true",
    }


def runtime_environment(context: dict, root: Path) -> dict[str, str]:
    directory = context.get("google_credentials")
    return credential_environment(root, Path(directory)) if directory else {}


async def cancel_login() -> None:
    global _login_cancelled
    _login_cancelled = True
    if _login_process is not None and _login_process.returncode is None:
        _login_process.terminate()
        try:
            await asyncio.wait_for(_login_process.wait(), 5)
        except TimeoutError:
            _login_process.kill()
            await _login_process.wait()


async def _capture(root: Path, directory: Path, *arguments: str) -> str:
    process = await asyncio.create_subprocess_exec(
        *platforms.google_command(root),
        *arguments,
        env=credential_environment(root, directory),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        raw, _ = await asyncio.wait_for(process.communicate(), 40)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    if process.returncode:
        raise SetupError("Google sign-in needs renewal. Select Sign in with Google and try again.")
    return raw.decode().strip()


def _verify_tokens(directory: Path, cli_token: str, expected: str) -> None:
    import google.auth
    import requests
    from google.auth.transport.requests import Request

    credentials, _ = google.auth.load_credentials_from_file(
        str(directory / "application_default_credentials.json"), scopes=_SCOPES
    )
    credentials.refresh(Request())
    for token in (cli_token, credentials.token):
        response = requests.post(
            "https://oauth2.googleapis.com/tokeninfo",
            headers={"Authorization": "Bearer " + token},
            timeout=15,
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise SetupError("Google could not verify this sign-in. Sign in again.")
        identity = response.json()
        actual = identity.get("email")
        if not isinstance(actual, str) or not actual:
            raise SetupError("Google did not return your account email. Sign in again.")
        if actual.lower() != expected.lower():
            raise SetupError(
                "Google returned a different account. Sign in with the email you entered."
            )
        if _CLOUD_SCOPE not in str(identity.get("scope", "")).split():
            raise SetupError(
                "Google Cloud access was not authorized. Sign in again and allow "
                "the requested Google Cloud access."
            )


async def _saved_sign_in(root: Path, email: str) -> Path | None:
    """Recover a completed browser grant only after verifying both identities.

    Search only this app's private stores, never the host's gcloud/ADC location.
    A failed verification cannot select an account or change the saved policy.
    """
    parent = preferences.data_root() / "google"
    if not parent.is_dir():
        return None
    candidates = [p for p in parent.iterdir()
                  if re.fullmatch(r"[a-f0-9]{32}", p.name) and not p.is_symlink()
                  and p.is_dir() and all((p / name).is_file() and not (p / name).is_symlink()
                    for name in ("credentials.db", "application_default_credentials.json"))]
    for directory in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
        if _login_cancelled:
            raise SetupError("Sign-in was cancelled. Your previous account is unchanged.")
        try:
            token = await _capture(root, directory, "auth", "print-access-token")
            await asyncio.to_thread(_verify_tokens, directory, token, email)
            return directory
        except Exception:  # noqa: BLE001 - no provider diagnostics or secrets leave this probe
            continue
    return None


async def sign_in(email: str, context_file: Path) -> None:
    global _login_process, _login_cancelled
    email = email.strip().lower()
    if email.startswith("-") or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise SetupError("Enter your own work email address.")
    if _login_lock.locked():
        raise SetupError("A sign-in is already open. Finish or cancel it first.")
    root = bundle_root()
    if root is None or not Path(platforms.google_command(root)[-1]).is_file():
        raise SetupError("Install the tester package that includes Google sign-in.")
    async with _login_lock:
        _login_cancelled = False
        try:
            directory = await _saved_sign_in(root, email)
            if _login_cancelled:
                raise SetupError("Sign-in was cancelled. Your previous account is unchanged.")
            if directory is None:
                directory = preferences.data_root() / "google" / uuid.uuid4().hex
                _login_process = await asyncio.create_subprocess_exec(
                    *platforms.google_command(root),
                    "auth",
                    "login",
                    email,
                    "--update-adc",
                    "--force",
                    "--quiet",
                    "--brief",
                    env=credential_environment(root, directory),
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                code = await asyncio.wait_for(_login_process.wait(), 600)
                if code:
                    raise SetupError(
                        "Sign-in was cancelled or could not complete. Your saved work is unchanged."
                    )
                token = await _capture(root, directory, "auth", "print-access-token")
                await asyncio.to_thread(_verify_tokens, directory, token, email)
            from . import session

            await session.prepare_reconfigure()
            if _login_cancelled:
                raise SetupError("Sign-in was cancelled. Your previous account is unchanged.")
            # The old account/context remains selected until both new credentials match.
            context = json.loads(context_file.read_text())
            old = context.get("authorization_policy", {})
            if old.get("expected_principal", "").lower() != email.lower():
                context["authorization_policy"] = {"live_enabled": False, "max_paid_usd": 0}
            context["google_credentials"] = str(directory)
            context["google_account"] = email
            context.pop("setup_access", None)
            preferences.atomic_json(context_file, context)
            # Original Case Finder's client is initialized lazily after first-run setup.
            os.environ.update(credential_environment(root, directory))
            from .. import bq, cache

            with bq._CLIENT_LOCK:
                if bq._CLIENT is not None:
                    bq._CLIENT.close()
                    bq._CLIENT = None
            cache.clear_all()
        except TimeoutError:
            await cancel_login()
            raise SetupError(
                "Sign-in timed out. Select Sign in with Google to try again."
            ) from None
        except asyncio.CancelledError:
            await cancel_login()
            raise
        finally:
            _login_process = None


def save_budget(context_file: Path, cap: float) -> None:
    context = json.loads(context_file.read_text())
    settings = pilot()
    if not settings or not context.get("google_account"):
        raise SetupError("Sign in with your own Google account first.")
    package.configure(
        context_file,
        context["source_profile"],
        context["google_account"],
        cap,
        settings["route_sha256"],
    )


async def check_access(context_file: Path) -> list[dict]:
    context = json.loads(context_file.read_text())
    context.pop("setup_access", None)
    preferences.atomic_json(context_file, context)
    root = bundle_root()
    settings = pilot(root)
    if root is None or not settings or not context.get("google_account"):
        raise SetupError("Sign in with your own Google account first.")
    directory = Path(context["google_credentials"])
    token = await _capture(root, directory, "auth", "print-access-token")
    await asyncio.to_thread(_verify_tokens, directory, token, context["google_account"])
    checks = await asyncio.to_thread(_access_probes, root, settings, token)
    current = json.loads(context_file.read_text())
    if (
        _access_binding(current) == _access_binding(context)
        and checks
        and all(c["passed"] for c in checks)
    ):
        current["setup_access"] = {
            "binding": _access_binding(context),
            "checked_at": time.time(),
            "checks": checks,
        }
        preferences.atomic_json(context_file, current)
    return checks


def _access_binding(context: dict) -> list:
    return [context.get(k) for k in ("google_account", "google_credentials", "source_profile")]


def access_ready(context: dict) -> bool:
    proof = context.get("setup_access", {})
    checks = proof.get("checks", [])
    age = time.time() - proof.get("checked_at", 0)
    return bool(
        context.get("google_account")
        and checks
        and all(c["passed"] for c in checks)
        and proof.get("binding") == _access_binding(context)
        and 0 <= age < 3600
    )


def complete_setup(context_file: Path) -> None:
    from . import budgets

    context = json.loads(context_file.read_text())
    if not access_ready(context):
        raise SetupError("Select Check my access to finish setup.")
    cap = context.get("authorization_policy", {}).get("max_paid_usd", 0)
    settings = budgets.ensure(context["google_account"], cap or budgets.DEFAULT_REQUEST)
    save_budget(context_file, settings["request_usd"])
    profile = preferences.read()
    preferences.save(
        profile["analyst"] or context["google_account"],
        profile["environment"] or "Private pilot",
        profile["runtime_context"],
    )


def _access_probes(root: Path, settings: dict, token: str) -> list[dict]:
    import requests

    profile = json.loads(
        (root / "pilot-resources" / settings["snapshot"] / "profile.json").read_text()
    )
    headers = {"Authorization": "Bearer " + token}
    checks = []
    datasets = [r["dataset"] for r in profile["datasets"]] + [profile["epic"]["dataset"]]
    for dataset in datasets:
        project, name = dataset.split(".")
        response = requests.get(
            f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets/{name}",
            headers=headers,
            timeout=20,
            allow_redirects=False,
        )
        checks.append(
            {
                "name": dataset,
                "passed": response.status_code == 200,
                "detail": "Dataset access"
                if response.status_code == 200
                else "Access unavailable. Check Stanford VPN and your dataset permissions.",
            }
        )
    response = requests.post(
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{settings['bigquery_job_project']}/jobs",
        headers=headers,
        json={
            "configuration": {"dryRun": True, "query": {"query": "SELECT 1", "useLegacySql": False}}
        },
        timeout=20,
        allow_redirects=False,
    )
    checks.append(
        {
            "name": "BigQuery dry run",
            "passed": response.status_code == 200,
            "detail": "Dry run only; no query executed."
            if response.status_code == 200
            else "Your account needs permission to create BigQuery jobs in the pilot project.",
        }
    )
    wanted = ["aiplatform.endpoints.predict", "serviceusage.services.use"]
    response = requests.post(
        f"https://cloudresourcemanager.googleapis.com/v1/projects/{settings['vertex_project']}:testIamPermissions",
        headers=headers,
        json={"permissions": wanted},
        timeout=20,
        allow_redirects=False,
    )
    granted = response.json().get("permissions", []) if response.status_code == 200 else []
    checks.append(
        {
            "name": "Model project permissions",
            "passed": set(wanted) <= set(granted),
            "detail": "Project permissions checked. "
            "Model availability is checked on your first request."
            if set(wanted) <= set(granted)
            else "Your account needs Vertex AI and quota access to the pilot project.",
        }
    )
    return checks
