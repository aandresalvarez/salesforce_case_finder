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
import uuid
from pathlib import Path

from . import package, preferences


class SetupError(ValueError):
    """A message safe to show without provider diagnostics or credentials."""


_login_process: asyncio.subprocess.Process | None = None
_login_lock = asyncio.Lock()
_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


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
    names = ("HOME", "USER", "TMPDIR", "LANG", "LC_ALL", "SSL_CERT_FILE")
    return {
        **{k: os.environ[k] for k in names if k in os.environ},
        "PATH": str(root / "google-cloud-sdk/bin") + ":/usr/bin:/bin:/usr/sbin:/sbin",
        "CLOUDSDK_CONFIG": str(directory),
        "GOOGLE_APPLICATION_CREDENTIALS": str(directory / "application_default_credentials.json"),
        "CLOUDSDK_PYTHON": str(root / "python/bin/python3.13"),
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
    if _login_process is not None and _login_process.returncode is None:
        _login_process.terminate()
        try:
            await asyncio.wait_for(_login_process.wait(), 5)
        except TimeoutError:
            _login_process.kill()
            await _login_process.wait()


async def _capture(root: Path, directory: Path, *arguments: str) -> str:
    process = await asyncio.create_subprocess_exec(
        str(root / "google-cloud-sdk/bin/gcloud"),
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
        if identity.get("email", "").lower() != expected.lower() or not set(_SCOPES).issubset(
            identity.get("scope", "").split()
        ):
            raise SetupError(
                "Google returned a different account. Sign in with the email you entered."
            )


async def sign_in(email: str, context_file: Path) -> None:
    global _login_process
    email = email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise SetupError("Enter your own work email address.")
    if _login_lock.locked():
        raise SetupError("A sign-in is already open. Finish or cancel it first.")
    root = bundle_root()
    if root is None or not (root / "google-cloud-sdk/bin/gcloud").is_file():
        raise SetupError("Install the tester package that includes Google sign-in.")
    directory = preferences.data_root() / "google" / uuid.uuid4().hex
    async with _login_lock:
        try:
            _login_process = await asyncio.create_subprocess_exec(
                str(root / "google-cloud-sdk/bin/gcloud"),
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
            # The old account/context remains selected until both new credentials match.
            context = json.loads(context_file.read_text())
            old = context.get("authorization_policy", {})
            if old.get("expected_principal", "").lower() != email.lower():
                context["authorization_policy"] = {"live_enabled": False, "max_paid_usd": 0}
            context["google_credentials"] = str(directory)
            context["google_account"] = email
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
    root = bundle_root()
    settings = pilot(root)
    if root is None or not settings or not context.get("google_account"):
        raise SetupError("Sign in with your own Google account first.")
    directory = Path(context["google_credentials"])
    token = await _capture(root, directory, "auth", "print-access-token")
    await asyncio.to_thread(_verify_tokens, directory, token, context["google_account"])
    return await asyncio.to_thread(_access_probes, root, settings, token)


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
