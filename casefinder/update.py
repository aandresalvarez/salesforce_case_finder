"""`casefinder --update`: find the newest release and install it over this one.

The app is handed out as a wheel attached to a GitHub release and installed with
`uv tool install <url>`. That URL names one exact version, and uv writes it into
the install receipt verbatim:

    requirements = [{ name = "casefinder", url = ".../casefinder-2.1.0-...whl" }]

So `uv tool upgrade casefinder` — the command anybody would reach for — resolves
that same pinned URL, finds it unchanged, and prints "Nothing to upgrade". It
will keep printing that on every machine in the team forever, however many
releases have happened since. That was measured rather than assumed: install
2.1.0 from the release URL, ask uv to upgrade it, read the answer.

There is no spelling of the install line that avoids this. A wheel's filename
has to carry a PEP 440 version for uv to install it at all, so there can be no
stable `casefinder-latest-py3-none-any.whl` for a permanent URL to point at, and
the alternative — a package index uv could actually resolve against — is a
server, which is the one thing this project deliberately does not have.

What is left is to ask GitHub which release is newest and install that. This
module is that, and nothing else. It is the only code in the app that contacts
anything other than BigQuery, so it stays small and it sends nothing: one
unauthenticated GET of a public release, a version comparison, and a subprocess.

Except on Windows, where there is no subprocess, only the command (D37).
Windows will not let a file be replaced while a program is using it, and during
`casefinder --update` the files uv has to replace are the ones running the
update. uv deletes the old environment file by file and stops at the first
refusal, so trying anyway can leave a working copy half-deleted. On Windows this
therefore finds the right release and Python and prints the one command that
installs it, to be run once Case Finder has exited.

The command names its Python, every time. Left to itself,
`uv tool install --force` rebuilds the environment on uv's default interpreter
rather than the one the environment had, and uv's default is the newest Python
on the machine — measured: a working install on 3.13 came back on 3.14 and no
longer started. The same flag is what repairs a copy that is already on a Python
the app does not run on, which is why `--update` still acts when nothing newer
has been released.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import ssl
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import certifi
from packaging.version import InvalidVersion, Version

from . import config

REPO = "aandresalvarez/salesforce_case_finder"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"

# Two timeouts, because there are two callers wanting opposite things.
# `--update` is a command somebody typed and is sitting in front of, so it can
# afford to wait for a slow network. The self-check's version line cannot: it is
# one line out of eight, and an unreachable github.com must not make the command
# the README tells people to run look like it has hung.
UPDATE_TIMEOUT = 15.0
CHECK_TIMEOUT = 3.0


class UpdateError(RuntimeError):
    """Anything between here and GitHub that did not work.

    Caught and printed as a line of text by every caller. Being unable to check
    for an update is not an application error — an offline laptop runs the app
    perfectly — so this never escapes as a traceback.
    """


@dataclass(frozen=True)
class Release:
    version: str
    wheel_url: str
    page_url: str


def _tls_context() -> ssl.SSLContext:
    """The platform's certificate store, with certifi's loaded into it.

    The platform's alone fails on a python.org build for macOS, which trusts
    nothing until someone runs the "Install Certificates" script that comes with
    it: every HTTPS request `urllib` makes fails verification. uv will build the
    tool on such a Python when it finds one, because it prefers a Python already
    on the machine to downloading another. certifi's alone would fail the other
    way — a managed Windows laptop behind a TLS-inspecting proxy trusts that
    proxy through the Windows store and nowhere else. One loaded into the other
    covers both.
    """
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return context


def latest(timeout: float = UPDATE_TIMEOUT) -> Release:
    """The newest published release, per GitHub.

    Unauthenticated, which is the point: the wheel is a public asset and asking
    which one is newest must not need a token that a support-team laptop has no
    reason to hold. The rate limit that comes with that (60/hour/IP) is far
    above one person occasionally checking.
    """
    request = urllib.request.Request(
        LATEST_API,
        headers={
            "Accept": "application/vnd.github+json",
            # GitHub rejects a request with no user agent. Naming the version
            # here is not telemetry — it is the same string already in the URL
            # of whichever wheel this machine downloaded.
            "User-Agent": f"casefinder/{config.VERSION}",
        },
    )
    try:
        # `OSError` and not the three separate names: `HTTPError` is a
        # `URLError` is an `OSError`, and so is the timeout.
        with urllib.request.urlopen(request, timeout=timeout, context=_tls_context()) as response:
            payload = json.load(response)
    except OSError as exc:
        raise UpdateError(f"could not reach GitHub ({type(exc).__name__}: {exc})") from exc
    except ValueError as exc:  # json.JSONDecodeError
        raise UpdateError(f"GitHub returned something that is not JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise UpdateError("GitHub returned an unexpected response")

    version = str(payload.get("tag_name") or "").removeprefix("v")
    # A release carries the lock file alongside the wheel, so the assets are
    # filtered rather than indexed. Handing `requirements-lock.txt` to
    # `uv tool install` would fail in a way that reads like a corrupt download.
    wheels = [
        str(asset.get("browser_download_url") or "")
        for asset in payload.get("assets") or []
        if str(asset.get("name") or "").endswith(".whl")
    ]
    wheels = [url for url in wheels if url]
    if not version or not wheels:
        raise UpdateError(f"the newest release has no wheel attached — see {RELEASES_PAGE}")
    return Release(version, wheels[0], str(payload.get("html_url") or RELEASES_PAGE))


def is_newer(candidate: str, current: str) -> bool:
    """Compare as versions, not as text.

    `"2.10.0" > "2.9.0"` is False as strings, and this project will reach a
    tenth patch release long before it reaches an interesting one. An
    unparseable version answers False: the cost of being wrong in that direction
    is one missed update notice, and in the other it is a machine that reports
    an update available on every single run, forever.
    """
    try:
        return Version(candidate) > Version(current)
    except InvalidVersion:
        return False


def _same(a: str, b: str) -> bool:
    try:
        return Version(a) == Version(b)
    except InvalidVersion:
        return False


def target_python() -> str:
    """The Python to install onto: this one, unless the app cannot run on it.

    Keeping the interpreter someone already has is the point of naming it — see
    the module docstring. Moving is only for a copy that is stranded on a Python
    outside `config.PYTHON_OLDEST`..`config.PYTHON_NEWEST`, and it moves to the
    newest one the app runs on, which is also the one with the longest support.
    """
    if config.python_supported():
        return config.python_label()
    return config.python_label(config.PYTHON_NEWEST)


def can_replace_itself() -> bool:
    """Can this process run the install that replaces its own files?

    Everywhere but Windows, yes: a POSIX system lets a file be unlinked while
    it is open, and the running process keeps its copy until it exits. Windows
    refuses — uv's own issue tracker has the error, `os error 32`, and the fix
    it asks for (astral-sh/uv#11930, #14520) is still open. One function so the
    decision is made once, for `run` and for `selfcheck` alike.
    """
    return os.name != "nt"


def wheel_url(version: str) -> str:
    """Where `release.sh` publishes the wheel for `version`.

    For the one case that cannot ask GitHub first: a copy that cannot start
    being told how to reinstall itself. It is its own version that it needs,
    and `tests/test_update.py` checks this against the URL the README gives.
    """
    return (
        f"https://github.com/{REPO}/releases/download/v{version}/"
        f"casefinder-{version}-py3-none-any.whl"
    )


def reinstall_line(wheel_url: str, python: str) -> str:
    """The install as a line a person can paste, `[ask]` and `--python` kept."""
    return f'uv tool install --force --python {python} "{requirement(wheel_url)}"'


def running_from_checkout() -> bool:
    """Is this the repository, or an installed copy?

    They need opposite advice — `git pull` against `uv tool install` — and
    telling a developer to overwrite their checkout with a wheel would replace
    the work in progress with the last release.

    `.exists()` rather than `.is_dir()` because a git worktree's `.git` is a
    file. `site-packages` has neither.
    """
    return (Path(__file__).resolve().parent.parent / ".git").exists()


def _has_ask_extra() -> bool:
    try:
        return importlib.util.find_spec("google.genai") is not None
    except (ImportError, ValueError):
        # No `google` namespace package at all, or one in a state find_spec
        # will not walk. Either way the extra is not installed.
        return False


def requirement(wheel_url: str) -> str:
    """What to hand `uv tool install`, extra included.

    `uv tool install --force <url>` installs the base package. A machine set up
    with `casefinder[ask]` would therefore lose the Ask tab on its first update
    — the app would start, everything would look normal, and one of its five
    screens would be gone. Whether the extra is present is a question the
    environment can be asked rather than something to remember, so it is asked.
    """
    if _has_ask_extra():
        return f"casefinder[ask] @ {wheel_url}"
    return wheel_url


def run(out=None) -> int:
    """Print what is available and, if it is newer, install it. Exit code out.

    0 means there is nothing to do or the update succeeded. 1 means the update
    was wanted and did not happen, and the reason is on the line above.

    A copy on a Python the app does not run on is reinstalled even when nothing
    newer exists: same version, supported Python. It cannot start, so this is
    the one command it still has — `casefinder` and `--check` both point here.
    """
    stream = sys.stdout if out is None else out

    def say(line: str = "") -> None:
        print(line, file=stream)

    say(f"{config.APP_NAME} {config.VERSION} — checking for a newer release")
    say()

    if running_from_checkout():
        here = Path(__file__).resolve().parent.parent
        say(f"  This is the source at {config.tilde(here)}, not an installed copy.")
        say("  Update it the way any clone is updated:")
        say("      git pull")
        say("      uv sync")
        return 0

    try:
        release = latest()
    except UpdateError as exc:
        say(f"  {exc}")
        say()
        say(f"  Releases are listed at {RELEASES_PAGE}")
        return 1

    newer = is_newer(release.version, config.VERSION)
    stranded = not config.python_supported()
    python = target_python()

    if not newer and not stranded:
        # "nothing newer has been released" rather than "this is the newest
        # release", because the two come apart on the maintainer's machine
        # between building a version and publishing it, and only one of them is
        # true in both cases.
        say(f"  Nothing newer than {config.VERSION} has been released.")
        return 0
    if not newer and not _same(release.version, config.VERSION):
        # Stranded, and ahead of every release: a build nobody has published,
        # which only happens on the maintainer's machine. Repairing it from the
        # newest release would quietly install an older version.
        say(f"  {config.VERSION} has not been released, so there is no release to reinstall.")
        say(f"  Reinstall it from the file it came from, with  --python {python}")
        return 1

    if newer:
        say(f"  installed {config.VERSION}  ·  available {release.version}")
    if stranded:
        say(f"  This copy is on Python {config.python_label()}, which Case Finder does not")
        say(f"  run on, so it is going onto Python {python}.")
    say()

    line = reinstall_line(release.wheel_url, python)
    if not can_replace_itself():
        # Returns 1 because the update has not happened yet, and saying 0 would
        # tell a script it had.
        say("  Windows cannot replace a program while it is running, so this last")
        say("  step is yours. Close Case Finder if it is open, then run:")
        say()
        say(f"      {line}")
        return 1

    wanted = requirement(release.wheel_url)
    uv = shutil.which("uv")
    if uv is None:
        # Installed some other way, or uv is not on this shell's PATH. Print
        # the command rather than guess at an installer that was never used.
        say("  uv is not on PATH, so this cannot install it for you. Run:")
        say(f"      {line}")
        return 1

    say(f"  installing {release.version} on Python {python} ...")
    # Output not captured: `uv tool install` reports what it is resolving and
    # downloading, and a silent thirty seconds is worse than a wall of text.
    completed = subprocess.run([uv, "tool", "install", "--force", "--python", python, wanted])
    if completed.returncode != 0:
        say()
        say(f"  That did not work. The release is at {release.page_url}")
        return completed.returncode

    say()
    if newer:
        say(f"  Updated to {release.version}. Start it with:  casefinder")
    else:
        say(f"  Reinstalled {release.version} on Python {python}. Start it with:  casefinder")
    return 0
