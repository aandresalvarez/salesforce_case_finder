"""What has to be true for the built wheel to be the app.

Everything here is about the gap between running from a checkout and running
from an installed package, which is a gap that does not show up in any other
test because every other test runs from a checkout. Three of these failures are
silent in the worst way — the app starts, draws, and is quietly missing a
feature — so they are asserted rather than trusted:

  - the shared presets resolve inside the package, not beside it;
  - the console script pins `__main__` so the native window process gets its
    window arguments;
  - nothing untracked can ride along inside the package directory.

That last one is a PHI control and not hygiene. Hatchling picks the files it
packages by asking git what is ignored, while `corpus_guard` scans what git is
tracking. An untracked scratch file under `casefinder/` sits in the hole between
those two questions: it ships in the wheel, and neither the guard nor the
pre-commit hook can see it. Under the old checkout-only model nothing was ever
shipped, so this is an exposure the wheel creates.
"""

from __future__ import annotations

import multiprocessing.spawn as spawn
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.specifiers import SpecifierSet

from casefinder import bq, cli, config, main, selfcheck, update, views

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "casefinder"


def _pyproject() -> dict:
    """`tomllib` arrived in 3.11 and this app installs on 3.10, so the handful
    of structural assertions that read pyproject skip on an older interpreter
    rather than failing. Nothing behavioural in this file depends on it."""
    tomllib = pytest.importorskip("tomllib", reason="reading pyproject.toml needs Python 3.11+")
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# The shared presets have to be inside the package
# --------------------------------------------------------------------------


def test_the_views_file_resolves_inside_the_package():
    """`parent`, not `parent.parent`.

    The two are the same directory in a checkout and different in an installed
    wheel, where the package's parent is `site-packages`. This is the assertion
    that tells them apart without building anything.
    """
    resolved = config._resolve_views_path()
    assert resolved.parent.name == "casefinder"
    assert resolved.name == "views.json"
    assert resolved.is_file(), f"{resolved} does not exist — the presets are not packaged"


def test_the_packaged_presets_are_actually_loaded():
    """Distinguishes "loaded the file" from "silently fell back to the built-ins".

    `views.shared_views` treats an unreadable file as "no views" and returns
    `builtin_views()` without saying so, so asserting that any presets came back
    would pass just as happily with the file deleted. `Unassigned queues` is the
    one preset that exists in the file and not in the code, which makes it the
    only assertion here that can fail for the reason this test is about.
    """
    names = {view.name for view in views.shared_views()}
    builtin = {view.name for view in views.builtin_views()}
    assert "Unassigned queues" in names, (
        "the packaged views.json was not read — shared_views fell back to the built-ins"
    )
    assert "Unassigned queues" not in builtin, (
        "this test's canary is now also a built-in, so it can no longer detect a fallback"
    )


def test_the_views_path_can_still_be_pointed_elsewhere(tmp_path):
    """FR: a team can override the presets without a new release."""
    elsewhere = tmp_path / "team.json"
    elsewhere.write_text("{}", encoding="utf-8")
    assert config._resolve_views_path(str(elsewhere)) == elsewhere


def test_the_views_file_is_not_hidden_from_the_build():
    """`.gitignore` has a bare `data/` that matches at any depth.

    Hatchling honours VCS ignores, so `casefinder/data/views.json` would build
    green and ship nothing. That is why the file is at `casefinder/views.json`,
    and this is the test that fails if someone tidies it into a subdirectory.
    """
    result = subprocess.run(
        ["git", "check-ignore", "casefinder/views.json"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "casefinder/views.json is gitignored — it will not be packaged"


def test_the_build_is_told_to_include_the_presets():
    wheel = _pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel.get("force-include", {}).get("casefinder/views.json"), (
        "the wheel target no longer force-includes views.json"
    )


# --------------------------------------------------------------------------
# Nothing untracked may ride along inside the package
# --------------------------------------------------------------------------


def test_every_file_in_the_package_is_tracked_by_git():
    """The hole between what hatchling ships and what the corpus guard scans.

    See the module docstring. `__pycache__` is excluded because it is generated
    and gitignored, which means hatchling drops it too.
    """
    tracked = set(
        subprocess.run(
            ["git", "ls-files", "-z", "casefinder"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split("\0")
    )
    on_disk = {
        str(path.relative_to(REPO))
        for path in PACKAGE.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    untracked = sorted(on_disk - tracked)
    assert not untracked, (
        "these files are inside the package and unknown to git, so they would ship "
        "in the wheel while the corpus guard cannot see them — `git add` them, or "
        "move them out of the package:\n  " + "\n  ".join(untracked)
    )


# --------------------------------------------------------------------------
# The console script
# --------------------------------------------------------------------------


def test_the_console_script_points_at_cli_not_main():
    """Structural, because reverting this breaks nothing that any test observes.

    `main` reads no argv and does no pinning, both on purpose. Pointed at
    `main`, the entry point still launches a window — one that is missing text
    selection, its minimum size, and the reconnect Restart button. Pointed at a
    `cli` inside `main`, every flag imports NiceGUI first, and on a Python where
    NiceGUI cannot import, `--check` and `--update` die with it (D37).
    """
    assert _pyproject()["project"]["scripts"]["casefinder"] == "casefinder.cli:cli"


def test_version_is_declared_once():
    project = _pyproject()["project"]
    assert "version" not in project, "version is static again; it belongs in config.py"
    assert project["dynamic"] == ["version"]
    assert _pyproject()["tool"]["hatch"]["version"]["path"] == "casefinder/config.py"

    import casefinder

    assert casefinder.__version__ == config.VERSION


def test_the_version_flag_prints_and_exits_clean(capsys):
    assert cli.cli(["--version"]) == 0
    assert config.VERSION in capsys.readouterr().out


def test_the_check_flag_runs_the_self_check_and_returns_its_code(monkeypatch):
    monkeypatch.setattr(selfcheck, "run", lambda *a, **k: 3)
    assert cli.cli(["--check"]) == 3


def test_an_unknown_flag_is_refused_rather_than_launching_a_window(capsys):
    """A typo'd flag must not silently open the app and swallow the argument."""
    assert cli.cli(["--wat"]) == 2
    assert "--wat" in capsys.readouterr().out


def test_launching_pins_the_main_module_before_running(monkeypatch):
    """Asserts the wiring, not the helper.

    A test that called `_pin_main_module` directly would pass with the call site
    deleted, which is the only way this can actually regress.
    """
    calls = []
    monkeypatch.setattr(main, "_pin_main_module", lambda: calls.append("pinned"))
    monkeypatch.setattr(main, "main", lambda: calls.append("ran"))
    assert cli.cli([]) == 0
    assert calls == ["pinned", "ran"], "the window process will not get its window arguments"


# The runner for the two subprocess tests below. They are subprocesses because
# this process imported NiceGUI long ago, so "was it imported?" and "can it be
# made to fail?" are only answerable in a fresh interpreter. The check list is
# cut down to the two lines under test: a full `--check` would query BigQuery
# from outside every fixture that exists to stop exactly that.
_RUN_CLI = """
import sys
from casefinder import cli, selfcheck
selfcheck.CHECKS = tuple(c for c in selfcheck.CHECKS if c[0] in {"python", "app"})
code = cli.cli(sys.argv[1:])
print("NICEGUI-LOADED" if "nicegui" in sys.modules else "NICEGUI-ABSENT")
sys.exit(code)
"""


def _run_cli(*args, pythonpath=None):
    env = dict(os.environ)
    if pythonpath is not None:
        env["PYTHONPATH"] = str(pythonpath)
    return subprocess.run(
        [sys.executable, "-c", _RUN_CLI, *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("flag", ["--version", "--update", "--nope"])
def test_no_flag_but_check_imports_the_ui(flag):
    """`--update` returns early here, from a checkout, before any network."""
    result = _run_cli(flag)
    assert "Traceback" not in result.stderr, result.stderr
    assert "NICEGUI-ABSENT" in result.stdout, f"{flag} imported NiceGUI"


def test_a_ui_that_cannot_import_is_a_line_in_check_not_a_traceback(tmp_path):
    """The Python 3.14 failure, reproduced on whatever Python runs the suite.

    A `nicegui` that raises what `vbuild` raised is put ahead of the real one.
    `--version` must not notice, and `--check` must say so on its `app` line
    and exit 1 — rather than print a traceback, which is what it did on 3.14
    while it was still dispatched from inside `main`.
    """
    fake = tmp_path / "nicegui"
    fake.mkdir()
    (fake / "__init__.py").write_text(
        "raise AttributeError(\"module 'pkgutil' has no attribute 'find_loader'\")\n",
        encoding="utf-8",
    )

    version = _run_cli("--version", pythonpath=tmp_path)
    assert version.returncode == 0, version.stderr
    assert config.VERSION in version.stdout

    check = _run_cli("--check", pythonpath=tmp_path)
    assert "Traceback" not in check.stdout + check.stderr, check.stderr
    assert check.returncode == 1
    app_line = next(line for line in check.stdout.splitlines() if "] app" in line)
    assert selfcheck.FAILED in app_line and "find_loader" in app_line


def test_an_unsupported_python_is_refused_before_the_ui_is_imported(monkeypatch, capsys):
    """What `casefinder` prints on 3.14 instead of a traceback out of `vbuild`."""
    ran = []
    monkeypatch.setattr(config, "python_supported", lambda version=None: False)
    monkeypatch.setattr(update, "running_from_checkout", lambda: False)
    monkeypatch.setattr(update, "can_replace_itself", lambda: True)
    monkeypatch.setattr(main, "main", lambda: ran.append("main"))

    assert cli.cli([]) == 1

    out = capsys.readouterr().out
    assert "cannot start" in out
    assert "casefinder --update" in out, "refused to start without saying what fixes it"
    assert ran == [], "the window was launched on a Python the app does not run on"


# --------------------------------------------------------------------------
# Which Pythons the app runs on
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "supported"),
    [((3, 9), False), ((3, 10), True), ((3, 13), True), ((3, 14), False), ((4, 0), False)],
)
def test_the_supported_pythons(version, supported):
    """3.14 is out because every NiceGUI 2.x imports `vbuild` (D37)."""
    assert config.python_supported(version) is supported


def test_requires_python_says_what_config_says():
    """Two statements of one fact. The metadata is what pip and `uv sync`
    honour; `config` is what the app checks, because `uv tool install <url>`
    does not honour the metadata at all."""
    spec = SpecifierSet(_pyproject()["project"]["requires-python"])
    for minor in range(6, 20):
        assert (f"3.{minor}.0" in spec) is config.python_supported((3, minor)), f"3.{minor}"


def test_the_python_check_fails_outside_the_range_and_names_the_fix(monkeypatch):
    monkeypatch.setattr(config, "python_supported", lambda version=None: False)
    newest = config.python_label(config.PYTHON_NEWEST)

    monkeypatch.setattr(update, "running_from_checkout", lambda: False)
    monkeypatch.setattr(update, "can_replace_itself", lambda: True)
    status, _, remedy = selfcheck.check_python()
    assert status == selfcheck.FAILED
    assert "casefinder --update" in "\n".join(remedy)

    monkeypatch.setattr(update, "running_from_checkout", lambda: True)
    status, _, remedy = selfcheck.check_python()
    assert status == selfcheck.FAILED
    assert f"uv sync --python {newest}" in "\n".join(remedy), "a checkout was sent to --update"


def test_the_python_check_passes_on_this_python():
    status, message, remedy = selfcheck.check_python()
    assert status == selfcheck.OK
    assert remedy == []
    assert config.tilde(sys.executable) in message


def test_the_app_check_reports_an_import_failure_as_a_line(monkeypatch):
    def fails(name):
        raise AttributeError("module 'pkgutil' has no attribute 'find_loader'")

    monkeypatch.setattr(selfcheck.importlib, "import_module", fails)
    status, message, _ = selfcheck._check_app()
    assert status == selfcheck.FAILED
    assert "find_loader" in message


def test_the_app_check_passes_when_the_app_imports():
    assert selfcheck._check_app()[0] == selfcheck.OK


def test_every_install_line_handed_to_people_names_the_python():
    """uv picks the newest Python it can find when not told, and on a machine
    with none it downloads the newest — which the app does not run on. So every
    install line a person is given carries `--python`, and this is what stops
    the next edit to the README from quietly dropping it.

    `release.sh` spells it `--python $python`, read out of `config` when the
    release is cut. It also installs without it once, on purpose, to prove that
    a copy which ended up on the wrong Python can repair itself; that line says
    so.
    """
    newest = config.python_label(config.PYTHON_NEWEST)
    pinned = re.compile(rf'--python (?:{re.escape(newest)}\b|"?\$python"?)')
    lines = []
    for name in ("README.md", "PROPOSAL.md", "release.sh"):
        for number, line in enumerate((REPO / name).read_text(encoding="utf-8").splitlines(), 1):
            installs_the_app = "uv tool install" in line and (
                ".whl" in line or "asset_url" in line or "wanted" in line
            )
            if installs_the_app and "unpinned on purpose" not in line:
                lines.append((f"{name}:{number}", line))
    assert len(lines) >= 5, "the install lines moved; this test is no longer looking at them"
    missing = [where for where, line in lines if not pinned.search(line)]
    assert not missing, f"these install lines leave the Python to uv: {missing}"


# --------------------------------------------------------------------------
# Pinning `__main__`, which is the whole reason the console script needs a
# wrapper at all
# --------------------------------------------------------------------------


class _FakeMain:
    """Stands in for `sys.modules['__main__']`; a console script has no spec."""

    __spec__ = None
    __file__ = "/somewhere/bin/casefinder"


def test_pinning_switches_spawn_from_by_path_to_by_name(monkeypatch):
    """The actual mechanism, asserted against `multiprocessing` rather than described.

    Without a spec, spawn records the *path* of the console-script shim and the
    child re-runs it under `__mp_main__` — the shim's own `__main__` guard is
    false, `main()` never runs there, and `app.native.window_args` stays empty.
    """
    fake = _FakeMain()
    monkeypatch.setitem(sys.modules, "__main__", fake)

    before = spawn.get_preparation_data("probe")
    assert "init_main_from_path" in before

    main._pin_main_module()

    after = spawn.get_preparation_data("probe")
    assert after.get("init_main_from_name") == "casefinder.main"
    assert "init_main_from_path" not in after


def test_pinning_leaves_an_existing_spec_alone(monkeypatch):
    """Run as `python -m casefinder.main` there is already a correct spec, and
    under pytest there is pytest's. Neither may be overwritten."""
    import importlib.util

    fake = _FakeMain()
    fake.__spec__ = importlib.util.find_spec("casefinder.config")
    monkeypatch.setitem(sys.modules, "__main__", fake)

    main._pin_main_module()

    assert fake.__spec__.name == "casefinder.config"


def test_main_itself_never_pins(monkeypatch):
    """`test_window` and `test_reconnect` call `main()` under pytest's own
    `__main__`. If pinning moved into `main`, they would rewrite it mid-suite."""
    fake = _FakeMain()
    monkeypatch.setitem(sys.modules, "__main__", fake)
    monkeypatch.setattr(main.ui, "run", lambda **kwargs: None)
    monkeypatch.setattr(main.cache, "start_reaper", lambda: None)
    monkeypatch.setattr(main.window, "ready_signal", lambda: None)

    main.main()

    assert fake.__spec__ is None


# --------------------------------------------------------------------------
# Paths shown to a user
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (str(Path.home()), "~"),
        (str(Path.home() / ".config" / "gcloud"), f"~{Path('/.config/gcloud')}"),
        ("/usr/local/bin/gcloud", "/usr/local/bin/gcloud"),
    ],
)
def test_paths_shown_to_a_user_collapse_the_home_directory(raw, expected):
    """`corpus_guard` rejects an absolute home path, and both the Settings page
    and `--check` output are things people paste into support requests."""
    assert config.tilde(raw) == expected


def test_the_self_check_reports_every_check_and_a_legend(capsys, monkeypatch):
    monkeypatch.setattr(selfcheck, "_check_bigquery", lambda: (selfcheck.OK, "connected", []))
    monkeypatch.setattr(selfcheck, "CHECKS", (("bigquery", selfcheck._check_bigquery),))

    assert selfcheck.run() == 0

    out = capsys.readouterr().out
    assert "ok = ready" in out and "FAILED = fix this" in out, "no legend to read the output by"
    assert "bigquery" in out


def test_the_bigquery_line_names_the_vpn_when_that_is_the_cause(monkeypatch):
    """"VPC Service Controls" stays in the line: it is what the README tells
    people to look for, and what a support request will quote."""
    reason = f"{bq.OFF_VPN}\n\nBigQuery said: 403 VPC Service Controls: Request refused"
    monkeypatch.setattr(bq, "check_access", lambda: (False, reason))

    status, message, remedy = selfcheck._check_bigquery()

    assert status == selfcheck.FAILED
    assert "VPN" in message and "VPC Service Controls" in message
    assert bq.OFF_VPN in remedy


def test_a_probe_that_raises_is_a_line_not_a_crash(monkeypatch):
    """The failure branch returns before the VPN question is asked of `bq`."""

    def explodes():
        raise ImportError("no module named google")

    monkeypatch.setattr(bq, "check_access", explodes)

    status, _, remedy = selfcheck._check_bigquery()

    assert status == selfcheck.FAILED
    assert remedy == ["ImportError: no module named google"]


def test_the_self_check_exit_code_follows_the_failures(monkeypatch):
    monkeypatch.setattr(
        selfcheck, "CHECKS", (("thing", lambda: (selfcheck.FAILED, "broken", ["fix it"])),)
    )
    assert selfcheck.run() == 1

    monkeypatch.setattr(
        selfcheck, "CHECKS", (("thing", lambda: (selfcheck.WARN, "missing", [])),)
    )
    assert selfcheck.run() == 0, "a warn is something the app works without"


def test_a_check_that_raises_is_reported_rather_than_ending_the_run(capsys, monkeypatch):
    def explodes():
        raise RuntimeError("no")

    monkeypatch.setattr(
        selfcheck,
        "CHECKS",
        (("bad", explodes), ("good", lambda: (selfcheck.OK, "fine", []))),
    )
    assert selfcheck.run() == 1
    out = capsys.readouterr().out
    assert "RuntimeError" in out
    assert "fine" in out, "one bad check hid the rest"
