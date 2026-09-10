"""What `casefinder --update` has to get right.

Two of these are the reason the module exists rather than a line of
documentation telling people to reinstall by hand:

  - the wheel is picked out of the release assets, not the lock file beside it;
  - `[ask]` survives the update, because an update that silently removes a
    screen is worse than no update.

Nothing here touches the network. `no_network` is autouse for the file, so a
test that forgets to install its own response fails loudly rather than reaching
api.github.com and becoming slow, flaky, and rate-limited — the same bargain
`no_warehouse` makes for BigQuery.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from casefinder import config, main, selfcheck, update


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("a test tried to contact GitHub")

    monkeypatch.setattr(urllib.request, "urlopen", explode)


@pytest.fixture
def installed(monkeypatch):
    """Pretend to be a wheel install rather than the checkout the suite runs in.

    Every test about updating is a test about the installed copy; the checkout
    branch returns before any of it happens.
    """
    monkeypatch.setattr(update, "running_from_checkout", lambda: False)


def _payload(tag="v2.2.0", assets=None):
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/{update.REPO}/releases/tag/{tag}",
        "assets": assets
        if assets is not None
        else [
            {"name": "requirements-lock.txt", "browser_download_url": "https://x/lock.txt"},
            {
                "name": "casefinder-2.2.0-py3-none-any.whl",
                "browser_download_url": f"https://github.com/{update.REPO}"
                f"/releases/download/{tag}/casefinder-2.2.0-py3-none-any.whl",
            },
        ],
    }


def _answers(monkeypatch, payload):
    """Make `urlopen` return `payload`, and record the request it was given."""
    seen = {}

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    def fake(request, timeout=None):
        seen["url"] = request.full_url
        seen["headers"] = request.headers
        seen["timeout"] = timeout
        return _Response(json.dumps(payload).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return seen


def _raises(monkeypatch, exc):
    def fake(request, timeout=None):
        raise exc

    monkeypatch.setattr(urllib.request, "urlopen", fake)


# --------------------------------------------------------------------------
# Reading the release
# --------------------------------------------------------------------------


def test_the_wheel_is_picked_out_of_the_assets(monkeypatch):
    """A release carries the lock file too, so the assets are filtered.

    Indexing `assets[0]` would hand `requirements-lock.txt` to
    `uv tool install`, which fails in a way that reads like a corrupt download.
    """
    _answers(monkeypatch, _payload())
    assert update.latest().wheel_url.endswith("casefinder-2.2.0-py3-none-any.whl")


def test_the_tag_loses_its_v_before_being_compared():
    """Tags are `v2.2.0`; `config.VERSION` is `2.2.0`. One of them has to give."""
    assert update.Release("2.2.0", "u", "p").version == "2.2.0"


def test_the_tag_prefix_is_stripped_when_reading(monkeypatch):
    _answers(monkeypatch, _payload(tag="v9.9.9"))
    assert update.latest().version == "9.9.9"


def test_a_release_with_no_wheel_is_an_error_not_an_empty_url(monkeypatch):
    _answers(monkeypatch, _payload(assets=[{"name": "notes.md", "browser_download_url": "u"}]))
    with pytest.raises(update.UpdateError, match="no wheel"):
        update.latest()


def test_an_asset_with_no_download_url_is_not_offered(monkeypatch):
    _answers(monkeypatch, _payload(assets=[{"name": "casefinder-2.2.0-py3-none-any.whl"}]))
    with pytest.raises(update.UpdateError, match="no wheel"):
        update.latest()


def test_an_unreachable_github_is_reported_rather_than_raised(monkeypatch):
    _raises(monkeypatch, urllib.error.URLError("no route to host"))
    with pytest.raises(update.UpdateError, match="could not reach GitHub"):
        update.latest()


def test_an_http_error_is_reported_the_same_way(monkeypatch):
    """`HTTPError` is a `URLError` is an `OSError`, which is why one clause
    catches all three — asserted so that narrowing it would fail here."""
    _raises(monkeypatch, urllib.error.HTTPError(update.LATEST_API, 404, "Not Found", {}, None))
    with pytest.raises(update.UpdateError, match="could not reach GitHub"):
        update.latest()


def test_a_response_that_is_not_json_is_reported(monkeypatch):
    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda request, timeout=None: _Response(b"<html>nope")
    )
    with pytest.raises(update.UpdateError, match="not JSON"):
        update.latest()


def test_the_request_is_unauthenticated_and_names_itself(monkeypatch):
    """No token: the wheel is a public asset and asking which one is newest must
    not need a credential a support laptop has no reason to hold."""
    seen = _answers(monkeypatch, _payload())
    update.latest()
    assert seen["url"] == update.LATEST_API
    assert "Authorization" not in seen["headers"]
    assert seen["headers"]["User-agent"] == f"casefinder/{config.VERSION}"


def test_the_check_asks_for_a_shorter_timeout_than_the_command(monkeypatch):
    """A stalled line inside `--check` is worse than a stalled `--update`: one
    is a command someone chose to wait for, the other is one line out of eight."""
    seen = _answers(monkeypatch, _payload())
    update.latest(timeout=update.CHECK_TIMEOUT)
    assert seen["timeout"] == update.CHECK_TIMEOUT
    assert update.CHECK_TIMEOUT < update.UPDATE_TIMEOUT


# --------------------------------------------------------------------------
# Comparing versions
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("candidate", "current", "newer"),
    [
        ("2.2.0", "2.1.0", True),
        ("2.1.0", "2.1.0", False),
        ("2.0.0", "2.1.0", False),
        # The one a string comparison gets wrong, and the one this project will
        # actually reach.
        ("2.10.0", "2.9.0", True),
        ("2.9.0", "2.10.0", False),
    ],
)
def test_versions_compare_numerically_not_as_text(candidate, current, newer):
    assert update.is_newer(candidate, current) is newer


def test_an_unparseable_version_never_counts_as_newer():
    """Being wrong this way costs one missed notice. Being wrong the other way
    is a machine that reports an update on every run for the rest of time."""
    assert update.is_newer("nightly", "2.1.0") is False
    assert update.is_newer("2.2.0", "whatever") is False


# --------------------------------------------------------------------------
# Which copy is this?
# --------------------------------------------------------------------------


def test_the_suite_itself_is_running_from_a_checkout():
    """Pins the detector against the one case that can be observed for real.

    Everything else about it is monkeypatched, so without this the function
    could be inverted and the suite would stay green.
    """
    assert update.running_from_checkout() is True


def test_a_checkout_is_told_to_pull_rather_than_overwritten(monkeypatch):
    """Handing a developer `uv tool install` would replace their work in
    progress with the last release."""
    called = []
    monkeypatch.setattr(update.subprocess, "run", lambda *a, **k: called.append(a))
    out = io.StringIO()

    assert update.run(out) == 0

    assert "git pull" in out.getvalue()
    assert not called, "a checkout was updated from a wheel"


def test_a_checkout_does_not_reach_the_network_at_all(monkeypatch):
    """`no_network` is autouse, so this passes only if `run` returns first."""
    assert update.run(io.StringIO()) == 0


# --------------------------------------------------------------------------
# Installing
# --------------------------------------------------------------------------


class _Uv:
    """Stands in for `uv`, and records the command line it was handed."""

    def __init__(self, returncode=0):
        self.returncode = returncode
        self.argv = None

    def __call__(self, argv, *args, **kwargs):
        self.argv = argv
        return type("Completed", (), {"returncode": self.returncode})()


@pytest.fixture
def uv(monkeypatch):
    fake = _Uv()
    monkeypatch.setattr(update.shutil, "which", lambda name: "/usr/local/bin/uv")
    monkeypatch.setattr(update.subprocess, "run", fake)
    return fake


def test_nothing_happens_when_this_is_already_the_newest(monkeypatch, installed, uv):
    _answers(monkeypatch, _payload(tag=f"v{config.VERSION}"))
    out = io.StringIO()

    assert update.run(out) == 0

    assert "Nothing newer" in out.getvalue()
    assert uv.argv is None, "uv was run to install the version already installed"


def test_a_build_ahead_of_every_release_is_not_told_it_is_the_newest(
    monkeypatch, installed, uv
):
    """The maintainer's own machine, between building a version and publishing
    it. `is_newer` is correctly False, so the wording has to be true of "there
    is nothing newer" and not of "this is the newest release" — which it is
    not, since it has not been released at all."""
    _answers(monkeypatch, _payload(tag="v0.0.1"))
    out = io.StringIO()

    assert update.run(out) == 0

    assert "Nothing newer than" in out.getvalue()
    assert uv.argv is None


def test_a_newer_release_is_installed_from_its_wheel_url(monkeypatch, installed, uv):
    _answers(monkeypatch, _payload())
    assert update.run(io.StringIO()) == 0
    assert uv.argv[1:4] == ["tool", "install", "--force"]
    assert uv.argv[4].endswith("casefinder-2.2.0-py3-none-any.whl")


def test_the_ask_extra_survives_an_update(monkeypatch, installed, uv):
    """Otherwise the first update quietly removes a screen."""
    monkeypatch.setattr(update, "_has_ask_extra", lambda: True)
    _answers(monkeypatch, _payload())

    update.run(io.StringIO())

    assert uv.argv[4].startswith("casefinder[ask] @ https://")


def test_without_the_extra_the_bare_url_is_installed(monkeypatch, installed, uv):
    monkeypatch.setattr(update, "_has_ask_extra", lambda: False)
    _answers(monkeypatch, _payload())

    update.run(io.StringIO())

    assert uv.argv[4].startswith("https://")


def test_the_extra_is_read_off_the_environment(monkeypatch):
    """`_has_ask_extra` is monkeypatched everywhere else, so its own answer is
    checked here — against this environment, where `ask` is a dev extra."""
    import importlib.util

    expected = importlib.util.find_spec("google.genai") is not None
    assert update._has_ask_extra() is expected


def test_a_missing_google_namespace_is_not_a_crash(monkeypatch):
    def explode(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(update.importlib.util, "find_spec", explode)
    assert update._has_ask_extra() is False


def test_no_uv_on_path_prints_the_command_instead_of_guessing(monkeypatch, installed):
    monkeypatch.setattr(update.shutil, "which", lambda name: None)
    _answers(monkeypatch, _payload())
    out = io.StringIO()

    assert update.run(out) == 1, "an update that did not happen must not report success"

    assert "uv tool install --force" in out.getvalue()


def test_a_failed_install_returns_the_exit_code_uv_gave(monkeypatch, installed):
    monkeypatch.setattr(update.shutil, "which", lambda name: "/usr/local/bin/uv")
    monkeypatch.setattr(update.subprocess, "run", _Uv(returncode=7))
    _answers(monkeypatch, _payload())

    assert update.run(io.StringIO()) == 7


def test_an_unreachable_github_fails_the_command_but_says_where_to_look(monkeypatch, installed):
    _raises(monkeypatch, urllib.error.URLError("offline"))
    out = io.StringIO()

    assert update.run(out) == 1
    assert update.RELEASES_PAGE in out.getvalue()


# --------------------------------------------------------------------------
# The line in `--check`
# --------------------------------------------------------------------------


def _update_check(monkeypatch):
    """Run `--check` with only the update check in it.

    Returns the exit code, that one line's status, and the whole output. The
    status is parsed out rather than grepped for, because the legend at the top
    of every run contains the words `FAILED` and `warn` — an `assert FAILED not
    in text` can never pass, and the first draft of this file duly failed on
    output that was correct.
    """
    monkeypatch.setattr(selfcheck, "CHECKS", (("update", selfcheck._check_update),))
    out = io.StringIO()
    code = selfcheck.run(out)
    text = out.getvalue()
    line = next(ln for ln in text.splitlines() if "] update" in ln)
    return code, line.split("[", 1)[1].split("]", 1)[0].strip(), text


def test_the_self_check_says_when_a_newer_release_exists(monkeypatch, installed):
    _answers(monkeypatch, _payload())
    code, status, text = _update_check(monkeypatch)

    assert "2.2.0" in text
    assert "casefinder --update" in text
    assert status == selfcheck.WARN
    assert code == 0, "being a version behind is not a broken machine"


def test_the_self_check_never_fails_on_an_unreachable_github(monkeypatch, installed):
    """A laptop that cannot reach github.com runs the app perfectly. A red line
    here would send someone chasing a problem they do not have."""
    _raises(monkeypatch, urllib.error.URLError("offline"))
    code, status, _ = _update_check(monkeypatch)

    assert status == selfcheck.WARN
    assert code == 0


def test_the_self_check_is_quiet_when_this_is_the_newest(monkeypatch, installed):
    _answers(monkeypatch, _payload(tag=f"v{config.VERSION}"))
    code, status, _ = _update_check(monkeypatch)

    assert status == selfcheck.OK
    assert code == 0


def test_the_update_check_can_be_switched_off(monkeypatch, installed):
    monkeypatch.setattr(config, "UPDATE_CHECK", False)
    code, status, text = _update_check(monkeypatch)

    assert code == 0
    assert status == selfcheck.OK
    assert "CASEFINDER_UPDATE_CHECK" in text


def test_the_update_check_skips_the_network_in_a_checkout(monkeypatch):
    """Not covered by the env var: a developer has it on. `no_network` is what
    makes this an assertion rather than a description."""
    code, status, text = _update_check(monkeypatch)

    assert code == 0
    assert status == selfcheck.OK
    assert "git pull" in text


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------


def test_the_update_flag_is_wired_to_the_module_and_returns_its_code(monkeypatch):
    monkeypatch.setattr(update, "run", lambda *a, **k: 5)
    assert main.cli(["--update"]) == 5


def test_the_usage_line_mentions_every_flag_that_exists(capsys):
    assert main.cli(["--nope"]) == 2
    usage = capsys.readouterr().out
    for flag in ("--check", "--update", "--version"):
        assert flag in usage
