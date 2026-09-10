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
import subprocess
import sys
from pathlib import Path

import pytest

from casefinder import config, main, selfcheck, views

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
    selection, its minimum size, and the reconnect Restart button.
    """
    assert _pyproject()["project"]["scripts"]["casefinder"] == "casefinder.main:cli"


def test_version_is_declared_once():
    project = _pyproject()["project"]
    assert "version" not in project, "version is static again; it belongs in config.py"
    assert project["dynamic"] == ["version"]
    assert _pyproject()["tool"]["hatch"]["version"]["path"] == "casefinder/config.py"

    import casefinder

    assert casefinder.__version__ == config.VERSION


def test_the_version_flag_prints_and_exits_clean(capsys):
    assert main.cli(["--version"]) == 0
    assert config.VERSION in capsys.readouterr().out


def test_the_check_flag_runs_the_self_check_and_returns_its_code(monkeypatch):
    monkeypatch.setattr(selfcheck, "run", lambda *a, **k: 3)
    assert main.cli(["--check"]) == 3


def test_an_unknown_flag_is_refused_rather_than_launching_a_window(capsys):
    """A typo'd flag must not silently open the app and swallow the argument."""
    assert main.cli(["--wat"]) == 2
    assert "--wat" in capsys.readouterr().out


def test_launching_pins_the_main_module_before_running(monkeypatch):
    """Asserts the wiring, not the helper.

    A test that called `_pin_main_module` directly would pass with the call site
    deleted, which is the only way this can actually regress.
    """
    calls = []
    monkeypatch.setattr(main, "_pin_main_module", lambda: calls.append("pinned"))
    monkeypatch.setattr(main, "main", lambda: calls.append("ran"))
    assert main.cli([]) == 0
    assert calls == ["pinned", "ran"], "the window process will not get its window arguments"


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
