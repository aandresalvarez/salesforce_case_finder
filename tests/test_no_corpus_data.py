"""The repository contains no live corpus data — see `tests/corpus_guard.py`.

A test rather than only a commit hook, because a hook is a local setting. It
lives in `.git/`, it does not survive a clone, and `git commit --no-verify`
turns it off. Whoever picks this repository up next gets the hook only if they
read the README and run one command; they get this by running the suite, which
they will do anyway, and CI gets it for free.

The hook is still worth having — it is the difference between finding this
before the commit and after — but it is the convenience and this is the gate.
"""

from __future__ import annotations

import corpus_guard
import pytest


def test_no_corpus_data_is_tracked_in_this_repository():
    findings = corpus_guard.scan(corpus_guard.tracked_files())
    assert not findings, "corpus data is tracked in a public repository:\n" + "\n".join(
        f"  {finding}" for finding in findings
    )


# --------------------------------------------------------------------------
# The guard itself, which is the part that can rot silently
# --------------------------------------------------------------------------
#
# A scanner that has stopped matching anything passes the test above on an
# empty repository just as happily as on a clean one, so what it catches is
# asserted directly. Each case below is a real leak in the shape it actually
# arrived in.


@pytest.mark.parametrize(
    ("text", "why"),
    [
        (
            "On Apr 23, 2026 at 4:57 PM A Requester (a.requester@gmail.com) wrote:",
            "a requester's personal address, pasted from a case body into a comment",
        ),
        (
            '"owner": "A Person",  # aperson@med.somewhere.edu',
            "an institutional address, which is what staff write from",
        ),
        (
            "The working copy came from /Users/someone/Documents/work/casefinder",
            "a home directory, which names the person whose machine it is",
        ),
        (
            r"C:\Users\someone\AppData\Roaming\CaseFinder",
            "the same thing on Windows",
        ),
        (
            "credentials = loader@som-rit-phi-starr-dev.iam.gserviceaccount.com",
            "a service account built on the live project id",
        ),
    ],
)
def test_the_guard_catches_what_actually_leaked(text, why):
    assert corpus_guard.scan_text("some_file.py", text), f"missed {why}"


@pytest.mark.parametrize(
    "text",
    [
        "requester = 'dana.whitfield@example.com'",
        "analyst = 'praman@example.edu'",
        "alias = 'support@example.edu'",
        "sa = 'loader@example.iam.gserviceaccount.com'",
        "docs = 'someone@service.example'",
        "path = '~/Documents/Astra/Workspaces/salesforce-cases'",
        "shared = str(Path.home() / 'Library' / 'Application Support')",
        "# The user's home directory is where personal views are written.",
    ],
    ids=[
        "documentation .com",
        "documentation .edu",
        "team alias",
        "service account on a documentation project",
        "reserved .example TLD",
        "a tilde instead of a home directory",
        "a home directory computed rather than written",
        "prose about home directories",
    ],
)
def test_the_guard_leaves_synthetic_values_alone(text):
    """A guard that cries wolf gets switched off, so the false-positive cases
    are held as tightly as the true-positive ones. The last two matter most:
    the app genuinely does write to the user's home directory, and code and
    prose that say so must not be mistaken for a pasted path.
    """
    assert not corpus_guard.scan_text("some_file.py", text)


def test_only_this_file_may_hold_the_counter_examples():
    """The cases above are exactly what the guard rejects, so this file has to
    be exempt from it — and the exemption has to be that one file, or it
    becomes the hole everything leaks through.

    Asserted both ways round: this file's own content passes under its own
    name, and the identical content fails under any other.
    """
    name = "tests/test_no_corpus_data.py"
    text = (corpus_guard.REPO_ROOT / name).read_text(encoding="utf-8")

    assert not corpus_guard.scan_text(name, text)
    assert corpus_guard.scan_text("casefinder/models.py", text), (
        "the exemption is not tied to the path, so any file could claim it"
    )


def test_the_roster_and_the_guard_pass_on_their_own_merits():
    """Neither is exempt, so neither may quote a real value while explaining
    why real values are forbidden.
    """
    for name in ("tests/corpus_guard.py", "tests/synthetic.py"):
        text = (corpus_guard.REPO_ROOT / name).read_text(encoding="utf-8")
        assert not corpus_guard.scan_text(name, text)
