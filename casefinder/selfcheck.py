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


def _check_python() -> tuple[str, str, list[str]]:
    """Reported, not asserted. `requires-python` already refuses to install on
    anything older than 3.10, so a version test here could never fire; what is
    worth having in pasted output is which interpreter the app actually got."""
    version = ".".join(str(n) for n in sys.version_info[:3])
    return OK, f"Python {version} at {config.tilde(sys.executable)}", []


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
        reachable, message = False, f"{type(exc).__name__}: {exc}"
    if reachable:
        return OK, message, []
    return FAILED, "BigQuery is not reachable", message.strip().splitlines()


# Ordered so that a failure explains the failures under it: no gcloud means no
# credentials, and no credentials means no BigQuery. A reader who fixes the
# first line usually fixes the rest.
CHECKS = (
    ("python", _check_python),
    ("app", lambda: (OK, f"{config.APP_NAME} {config.VERSION} imports cleanly", [])),
    ("webview", _check_webview),
    ("presets", _check_views),
    ("gcloud", _check_gcloud),
    ("credentials", _check_adc),
    ("bigquery", _check_bigquery),
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
