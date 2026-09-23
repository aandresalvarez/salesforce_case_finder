"""`casefinder --check`: does this machine have what the app needs?

This used to be two heredocs, one inside each installer script. That was fine
while the only way to get the app was to clone it and run the installer, and it
stops being fine the moment the app is installed from a wheel: the installers
are not shipped, so the knowledge inside them — above all the WebView2 runtime
URL, which appears nowhere else in the product — would leave with them.

So it lives here, in the package, reachable as a command on any machine the app
is installed on. The installers now call it instead of carrying their own copy.

What it deliberately does not do is open a window. A check that opened one would
be a better check and a worse tool: it cannot run over SSH, it cannot run in the
terminal a user has just been asked to paste output from, and it leaves a window
on screen that someone then has to close. Importing the platform backend is what
the installers already did, and it is what distinguishes "the runtime is
missing" — the failure this exists to catch — from a window that opens grey.

The output is designed to be pasted into a support request, which is why every
path goes through `config.tilde`. A pasted absolute path names the person whose
machine it is, and that is not something to ask a user to send.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
from pathlib import Path

from . import config

OK = "ok"
FAILED = "FAILED"
WARN = "warn"

# The Windows webview runtime is the one prerequisite that is routinely absent
# on an otherwise healthy machine: pywebview draws through Microsoft Edge
# WebView2, which ships with Windows 11 and current Windows 10 but not with
# older images. Known limitation 13 is about this surface.
WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
GCLOUD_INSTALL_URL = "https://cloud.google.com/sdk/docs/install-sdk"


def check_python() -> tuple[str, str, list[str]]:
    """Which interpreter the app got, and whether it runs on it.

    This used to be reported and not asserted, on the grounds that
    `requires-python` refuses an unsupported Python at install time, so a test
    here could never fire. That holds for pip. It does not hold for uv
    installing a wheel from a URL, which is how the app is installed: uv does
    not enforce the field there, and on a machine with no Python it downloads
    the newest, which is one the app does not run on (D37). So it fires.

    Public because `cli` prints the same words when it refuses to start, and
    one wording is easier to keep true than two.
    """
    version = ".".join(str(n) for n in sys.version_info[:3])
    where = f"Python {version} at {config.tilde(sys.executable)}"
    if config.python_supported():
        return OK, where, []

    from . import update

    oldest = config.python_label(config.PYTHON_OLDEST)
    newest = config.python_label(config.PYTHON_NEWEST)
    if update.running_from_checkout():
        remedy = [f"Rebuild the environment on Python {newest}:", f"    uv sync --python {newest}"]
    elif update.can_replace_itself():
        remedy = [f"Move this copy onto Python {newest}:", "    casefinder --update"]
    else:
        # Straight to the command, because on Windows `--update` would only
        # print it: a stranded copy is spared a step, and needs no network to
        # be told it — it is its own version it is reinstalling.
        line = update.reinstall_line(update.wheel_url(config.VERSION), newest)
        remedy = [f"Move this copy onto Python {newest}:", f"    {line}"]
    return FAILED, f"{where} — Case Finder runs on {oldest} to {newest}", remedy


def _check_app() -> tuple[str, str, list[str]]:
    """Import the application, NiceGUI and all.

    This used to be a line that could only say yes. `--check` was dispatched
    from inside `main`, so by the time it ran the import had already succeeded
    — and when the import failed, the whole command failed with it, as a
    traceback, which is what a machine on Python 3.14 got. The flags are now
    read before anything imports the UI (see `cli`), so this is where an
    application that cannot import finds out, as a line of output.
    """
    try:
        importlib.import_module(f"{__package__}.main")
    except Exception as exc:  # noqa: BLE001 — any import failure is the answer
        return FAILED, f"the app does not import: {type(exc).__name__}: {exc}", []
    return OK, f"{config.APP_NAME} {config.VERSION} imports cleanly", []


def _check_webview() -> tuple[str, str, list[str]]:
    """Import the platform backend rather than open a window. See module docs."""
    if sys.platform == "darwin":
        module, label = "webview.platforms.cocoa", "macOS WebKit"
        remedy = []
    elif os.name == "nt":
        module, label = "webview.platforms.winforms", "Windows WebView2"
        remedy = [
            "Install the Microsoft Edge WebView2 Evergreen Runtime:",
            f"    {WEBVIEW2_URL}",
        ]
    else:
        module, label = "webview.platforms.gtk", "GTK"
        remedy = []

    try:
        importlib.import_module(module)
    except Exception as exc:  # noqa: BLE001 — any import failure is the answer
        return (
            FAILED,
            f"{label} webview backend unavailable: {type(exc).__name__}: {exc}",
            [
                *remedy,
                "Until then the app still runs in a browser tab:",
                "    CASEFINDER_NATIVE=0 casefinder"
                if os.name != "nt"
                else "    $env:CASEFINDER_NATIVE=0; casefinder",
            ],
        )
    return OK, f"{label} webview backend available", []


def _check_views() -> tuple[str, str, list[str]]:
    """Are the shared presets actually packaged?

    Worth a line of its own because the failure is silent: `views.shared_views`
    treats an unreadable file as "use the built-ins", so a wheel built without
    this file starts up perfectly and is simply missing presets nobody thinks
    to look for.
    """
    path = config.VIEWS_PATH
    if not path.is_file():
        return WARN, f"team presets not found at {config.tilde(path)} — using built-ins only", []
    return OK, f"team presets at {config.tilde(path)}", []


def _check_gcloud() -> tuple[str, str, list[str]]:
    found = shutil.which("gcloud")
    if not found:
        return (
            FAILED,
            "the Google Cloud CLI (gcloud) is not installed",
            [
                "Case Finder signs in with the credentials already on this",
                "machine, so it needs the CLI that holds them:",
                f"    {GCLOUD_INSTALL_URL}",
            ],
        )
    return OK, f"gcloud at {config.tilde(found)}", []


def _adc_path() -> Path:
    """Where the Google libraries look for application default credentials."""
    override = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if override:
        return Path(override)
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / "gcloud"
    return Path.home() / ".config" / "gcloud"


def _check_adc() -> tuple[str, str, list[str]]:
    # ADC, not a service-account key: the app ships no secret, and every user
    # reads exactly what BigQuery IAM already lets them read (spec section 9.1).
    path = _adc_path()
    if path.is_dir():
        path = path / "application_default_credentials.json"
    if not path.is_file():
        return (
            FAILED,
            "no application default credentials on this machine",
            ["Sign in once:", "    gcloud auth application-default login"],
        )
    return OK, f"application default credentials at {config.tilde(path)}", []


def _check_bigquery() -> tuple[str, str, list[str]]:
    """The only check that costs anything: one row out of the case dimension."""
    try:
        from . import bq

        reachable, message = bq.check_access()
    except Exception as exc:  # noqa: BLE001 — reported, never raised at a user
        # Returned here rather than folded into `message`: if the import is
        # what failed, there is no `bq` below to ask about the VPN.
        return FAILED, "BigQuery is not reachable", [f"{type(exc).__name__}: {exc}"]
    if reachable:
        return OK, message, []
    if bq.blocked_off_vpn(message):
        # "VPC Service Controls" kept in the line because it is the phrase the
        # README tells people to look for, and the one a support request will
        # quote.
        return (
            FAILED,
            "not on the VPN — BigQuery refused this computer (VPC Service Controls)",
            message.strip().splitlines(),
        )
    return FAILED, "BigQuery is not reachable", message.strip().splitlines()


def _check_update() -> tuple[str, str, list[str]]:
    """Is there a newer release than the one running?

    Here because `casefinder --update` is a command nobody runs unprompted.
    Without a line that mentions it, a team installs 2.1.0 once and stays on it
    until somebody happens to send another email — which is the situation the
    whole release-asset arrangement exists to end.

    Never `FAILED`, in any branch. Being one version behind is not a broken
    machine, and neither is a laptop that cannot reach github.com; both still
    run the app against the warehouse perfectly. A red line here would send
    someone chasing a problem they do not have.
    """
    from . import update

    if update.running_from_checkout():
        # Short-circuits before the network call, so working in the repository
        # never involves one.
        return OK, f"{config.VERSION} from a checkout — `git pull` to update", []
    if not config.UPDATE_CHECK:
        return OK, f"{config.VERSION} (CASEFINDER_UPDATE_CHECK is off)", []
    try:
        release = update.latest(timeout=update.CHECK_TIMEOUT)
    except update.UpdateError as exc:
        return WARN, f"could not check for a newer release — {exc}", []
    if update.is_newer(release.version, config.VERSION):
        return (
            WARN,
            f"{release.version} has been released — this is {config.VERSION}",
            ["Update in place:", "    casefinder --update"],
        )
    return OK, f"nothing newer than {config.VERSION} has been released", []


# Ordered so that a failure explains the failures under it: an unsupported
# Python means the app does not import, no gcloud means no credentials, and no
# credentials means no BigQuery. A reader who fixes the first line usually fixes
# the rest.
#
# `update` sits last despite being a fact about the app rather than the machine,
# because it is the only check that can sit there waiting on a timeout, and a
# list that stalls at its end reads better than one that stalls in its middle.
CHECKS = (
    ("python", check_python),
    ("app", _check_app),
    ("webview", _check_webview),
    ("presets", _check_views),
    ("gcloud", _check_gcloud),
    ("credentials", _check_adc),
    ("bigquery", _check_bigquery),
    ("update", _check_update),
)


def run(out=None) -> int:
    """Print one line per check. Returns the process exit code.

    0 means every check passed. 1 means at least one `FAILED`. A `warn` is
    something the app works without, and does not change the exit code.
    """
    stream = sys.stdout if out is None else out
    print(f"{config.APP_NAME} {config.VERSION} — checking this machine", file=stream)
    print(f"  {OK} = ready · {WARN} = works without it · {FAILED} = fix this\n", file=stream)

    failures = 0
    for name, check in CHECKS:
        try:
            status, message, remedy = check()
        except Exception as exc:  # noqa: BLE001 — one bad check must not hide the rest
            status, message, remedy = FAILED, f"check raised {type(exc).__name__}: {exc}", []
        if status == FAILED:
            failures += 1
        print(f"  [{status:>6}] {name:<12} {message}", file=stream)
        for line in remedy:
            print(f"                          {line}", file=stream)

    print(file=stream)
    if failures:
        print(f"{failures} check(s) need attention. Fix those and run this again.", file=stream)
    else:
        print("Ready. Start it with:  casefinder", file=stream)
    return 1 if failures else 0
