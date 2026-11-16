"""Fresh testers must not borrow the developer's account or authorize hidden work."""

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from casefinder.case360 import onboarding, preferences, session
from casefinder.case360.runtime import Runtime


@pytest.fixture
def install(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", dict(os.environ))
    root = tmp_path / "package"
    resources = root / "pilot-resources"
    version = "a" * 64
    (resources / version).mkdir(parents=True)
    (resources / version / "profile.json").write_text("{}")
    (resources / "vertex_serving_route_verification.json").write_text("{}")
    (resources / "bootstrap.json").write_text(
        json.dumps(
            {"schema": "case360_pilot_bootstrap/1", "snapshot": version, "route_sha256": "b" * 64}
        )
    )
    (root / "google-cloud-sdk/bin").mkdir(parents=True)
    (root / "google-cloud-sdk/bin/gcloud").touch()
    private = tmp_path / "tester"
    monkeypatch.setenv("CASE360_DATA_ROOT", str(private))
    monkeypatch.setenv("CASE360_BUNDLE_ROOT", str(root))
    context = private / "context.json"
    preferences.atomic_json(
        context,
        {
            "resource_root": str(private / "resources"),
            "engine_root": str(root / "engine"),
            "runs_root": str(private / "runs"),
            "node_executable": str(root / "node/bin/node"),
            "source_profile": None,
            "authorization_policy": {"live_enabled": False, "max_paid_usd": 0},
        },
    )
    return root, context


def test_fresh_setup_is_local_and_cannot_fall_back_to_host_credentials(install, monkeypatch):
    root, context = install
    monkeypatch.setenv("CLOUDSDK_CONFIG", "/outside/host-google")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/outside/host-adc.json")
    monkeypatch.setenv("GOOGLE_CLOUD_API_KEY", "synthetic-must-not-inherit")
    onboarding.provision(root, context)
    saved = json.loads(context.read_text())
    assert saved["source_profile"] == "a" * 64
    assert saved["authorization_policy"] == {"live_enabled": False, "max_paid_usd": 0}
    assert "google_account" not in saved
    runtime = Runtime(root / "engine", context.parent / "runs", "node", context)
    env = runtime.environment()
    assert env["CLOUDSDK_CONFIG"] == str(context.parent / "google/pending")
    assert not Path(env["GOOGLE_APPLICATION_CREDENTIALS"]).exists()
    assert "GOOGLE_CLOUD_API_KEY" not in env
    assert "/outside" not in str(env)
    assert env["PATH"].startswith(str(root / "google-cloud-sdk/bin"))
    assert env["CLOUDSDK_CORE_DISABLE_FILE_LOGGING"] == "true"


def test_reopen_keeps_account_configuration_and_selected_resources(install):
    root, context = install
    onboarding.provision(root, context)
    saved = json.loads(context.read_text())
    saved.update(
        google_account="tester@example.edu",
        google_credentials=str(context.parent / "google/own"),
        source_profile="c" * 64,
    )
    preferences.atomic_json(context, saved)
    onboarding.provision(root, context)
    assert json.loads(context.read_text()) == saved


class Process:
    def __init__(self, code=0):
        self.returncode = None
        self.code = code
        self.terminated = False

    async def wait(self):
        self.returncode = self.code
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = -15


def test_own_browser_login_publishes_only_after_both_identities_match(install, monkeypatch):
    root, context = install
    onboarding.provision(root, context)
    calls = []

    async def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return Process()

    monkeypatch.setattr(onboarding.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(onboarding, "_capture", AsyncMock(return_value="synthetic-token"))
    verified = []
    monkeypatch.setattr(
        onboarding,
        "_verify_tokens",
        lambda directory, token, email: verified.append((directory, token, email)),
    )
    monkeypatch.setattr(session, "prepare_reconfigure", AsyncMock())
    asyncio.run(onboarding.sign_in("second-tester@example.edu", context))
    saved = json.loads(context.read_text())
    assert saved["google_account"] == "second-tester@example.edu"
    assert verified[0][2] == saved["google_account"]
    assert saved["authorization_policy"]["live_enabled"] is False
    assert "--update-adc" in calls[0][0] and "--force" in calls[0][0]
    assert calls[0][1]["stdout"] == asyncio.subprocess.DEVNULL
    assert calls[0][1]["stderr"] == asyncio.subprocess.DEVNULL
    assert calls[0][1]["env"]["CLOUDSDK_CONFIG"] == saved["google_credentials"]
    assert "synthetic-token" not in context.read_text()
    assert onboarding._login_process is None


@pytest.mark.parametrize("failure", ["cancel", "mismatch", "active_run"])
def test_failed_sign_in_never_replaces_saved_account_or_request(install, monkeypatch, failure):
    root, context = install
    onboarding.provision(root, context)
    before = context.read_bytes()
    request = context.parent / "request.json"
    request.write_text('{"answer":"keep this"}')
    spawn = AsyncMock(return_value=Process(1 if failure == "cancel" else 0))
    monkeypatch.setattr(onboarding.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(onboarding, "_capture", AsyncMock(return_value="synthetic-token"))

    def verify(*_):
        if failure == "mismatch":
            raise onboarding.SetupError("Account mismatch")

    monkeypatch.setattr(onboarding, "_verify_tokens", verify)
    monkeypatch.setattr(
        session,
        "prepare_reconfigure",
        AsyncMock(
            side_effect=RuntimeError("Stop active work") if failure == "active_run" else None
        ),
    )
    with pytest.raises((onboarding.SetupError, RuntimeError)):
        asyncio.run(onboarding.sign_in("tester@example.edu", context))
    assert context.read_bytes() == before
    assert request.read_text() == '{"answer":"keep this"}'


def test_budget_requires_own_sign_in_and_does_not_create_run_authorization(install):
    root, context = install
    onboarding.provision(root, context)
    with pytest.raises(onboarding.SetupError, match="Sign in"):
        onboarding.save_budget(context, 10)
    saved = json.loads(context.read_text())
    saved["google_account"] = "tester@example.edu"
    preferences.atomic_json(context, saved)
    onboarding.save_budget(context, 10)
    value = json.loads(context.read_text())
    assert value["authorization_policy"]["expected_principal"] == "tester@example.edu"
    assert value["authorization_policy"]["max_paid_usd"] == 10
    assert not (context.parent / "runs").exists()


def test_setup_ui_has_no_manual_resource_paths_or_terminal_login(render, install, monkeypatch):
    root, context = install
    from casefinder.ui import case360_welcome

    onboarding.provision(root, context)
    monkeypatch.setattr(
        case360_welcome, "discover", lambda: Runtime(root / "engine", root, "node", context)
    )
    tree = render(case360_welcome.render_welcome)
    assert {"Sign in with Google", "Check my access", "Save my settings"} <= set(
        tree.button_labels()
    )
    assert "gcloud" not in tree.text and "SHA256" not in tree.text
    assert "Your work email" in [x.props.get("label") for x in tree.of_type("Input")]
    assert next(x for x in tree.of_type("Number")).value == 0


def test_access_checks_never_execute_sql_or_call_a_model(install, monkeypatch):
    root, _ = install
    settings = onboarding.pilot(root)
    settings.update(bigquery_job_project="synthetic-jobs", vertex_project="synthetic-model")
    (root / "pilot-resources" / settings["snapshot"] / "profile.json").write_text(
        json.dumps(
            {
                "datasets": [{"dataset": "synthetic-project.dataset"}],
                "epic": {"dataset": "synthetic-project.epic"},
            }
        )
    )
    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return type(
            "Reply",
            (),
            {
                "status_code": 200,
                "json": lambda _: {
                    "permissions": ["aiplatform.endpoints.predict", "serviceusage.services.use"]
                },
            },
        )()

    monkeypatch.setattr("requests.get", request)
    monkeypatch.setattr("requests.post", request)
    assert all(c["passed"] for c in onboarding._access_probes(root, settings, "synthetic"))
    job = next(kwargs["json"] for url, kwargs in calls if url.endswith("/jobs"))
    assert job == {
        "configuration": {"dryRun": True, "query": {"query": "SELECT 1", "useLegacySql": False}}
    }
    assert not any("generateContent" in url or "aiplatform.googleapis" in url for url, _ in calls)


def test_token_identity_mismatch_is_rejected_without_exposing_tokens(install, monkeypatch):
    _, context = install
    credential = type(
        "Credential", (), {"token": "synthetic-adc-secret", "refresh": lambda *args: None}
    )()
    monkeypatch.setattr(
        "google.auth.load_credentials_from_file", lambda *a, **k: (credential, None)
    )
    seen = []

    def introspect(url, **kwargs):
        seen.append(kwargs["headers"]["Authorization"])
        return type(
            "Response",
            (),
            {
                "status_code": 200,
                "json": lambda _: {
                    "email": "wrong@example.edu",
                    "scope": "https://www.googleapis.com/auth/cloud-platform",
                },
            },
        )()

    monkeypatch.setattr("requests.post", introspect)
    with pytest.raises(onboarding.SetupError, match="different account") as caught:
        onboarding._verify_tokens(context.parent, "synthetic-cli-secret", "tester@example.edu")
    assert "secret" not in str(caught.value)
    assert seen == ["Bearer synthetic-cli-secret"]


def test_cancel_sign_in_terminates_process_without_selecting_account(install):
    _, context = install
    before = context.read_bytes()
    process = Process()
    onboarding._login_process = process
    try:
        asyncio.run(onboarding.cancel_login())
        assert process.terminated
        assert context.read_bytes() == before
    finally:
        onboarding._login_process = None


def test_google_storage_refuses_symlink_to_host_credentials(install, tmp_path):
    root, _ = install
    host = tmp_path / "host-credentials"
    host.mkdir()
    link = tmp_path / "borrowed"
    link.symlink_to(host)
    with pytest.raises(onboarding.SetupError, match="links"):
        onboarding.credential_environment(root, link)
