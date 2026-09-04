"""Stop live corpus data from reaching a public repository.

This repository is public. The BigQuery corpus it queries is not: case bodies
are pasted email carrying requesters' names, personal and institutional email
addresses, study titles, IRB numbers, and the names of the support staff who
worked the case. The two facts are individually fine and jointly a leak.

The leak has a specific shape, and it is not carelessness. Diagnosing a
rendering bug means looking at what actually renders, so you sample a real row
— and then the natural thing to do is paste that sample into the comment
explaining the fix, or into the fixture that reproduces it. That is how a
requester's name and personal address ended up in `models.py` and three test
fixtures on 4 September 2026, and how a support owner's name reached a pushed
commit before that. Every one of those was written while doing careful work.

So the rule is: carry over the *shape*, never the string. When a live query
tells you what a column looks like, invent something with the same length,
punctuation and awkwardness, and put the invented version in the repo. The
cast of invented people lives in `tests/synthetic.py`; take a name from there
rather than making one up at the call site, so there is one obvious place to
look and no temptation to reach for a real one.

What this module enforces is the part a machine can settle: addresses and
filesystem paths, where "is this real?" is a question about a domain name or a
path prefix rather than about a person. Names are checked by the roster
convention and by review, because no regular expression can tell an invented
person from a real one — which is exactly why the roster exists.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# RFC 2606 §3 reserves example.com/.net/.org for documentation, and RFC 2606 §2
# reserves the .test/.example/.invalid/.localhost TLDs. `example.edu` is not in
# that RFC — EDUCAUSE holds it for the same purpose — and it is allowed here on
# purpose: this app's users are university staff, so a `.edu` in a fixture is
# what the real thing looks like, and a fixture that looks wrong gets quietly
# "corrected" towards a real address by the next person to touch it.
_DOC_DOMAINS = frozenset({"example.com", "example.net", "example.org", "example.edu"})
_DOC_TLDS = frozenset({"test", "example", "invalid", "localhost"})

# `loader@example.iam.gserviceaccount.com` and friends: Google mints these from
# a project id, and the ones in this repo are built on `example`. Matching the
# whole suffix rather than the bare domain keeps a real service account — whose
# id would be the live project — from slipping through.
_SERVICE_ACCOUNT_SUFFIX = ".iam.gserviceaccount.com"

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")

# A home directory names the person whose machine it is, and the tree under it
# is usually an employer's internal layout. Neither belongs in a public repo,
# even when the path is only quoted as provenance. `~` says the same thing.
_HOME_PATH = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\Users\\)(?!\w*[Nn]ame\b)\w[\w.-]*")

# Files whose content is not prose or source and would only produce noise.
_SKIP_SUFFIXES = frozenset({".lock", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf"})
_SKIP_NAMES = frozenset({"uv.lock"})

# The one file that has to contain what this module rejects: a guard whose
# counter-examples cannot be written down is a guard nobody can prove still
# works. Nothing else is exempt — not this module, which states its patterns as
# regex source rather than as examples, and not the roster, whose addresses are
# documentation domains and pass on their merits.
_SKIP_PATHS = frozenset({"tests/test_no_corpus_data.py"})


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    text: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}: {self.text}"


def _email_is_documentation(domain: str) -> bool:
    domain = domain.lower().rstrip(".")
    if domain in _DOC_DOMAINS:
        return True
    if domain.endswith(_SERVICE_ACCOUNT_SUFFIX):
        # `<name>@<project>.iam.gserviceaccount.com` — judge the project id.
        project = domain[: -len(_SERVICE_ACCOUNT_SUFFIX)]
        return project in _DOC_DOMAINS or project.split(".")[-1] in _DOC_TLDS
    return domain.split(".")[-1] in _DOC_TLDS


def scan_text(path: str, text: str) -> list[Finding]:
    """Every corpus-shaped string in one file's contents."""
    if path in _SKIP_PATHS:
        return []
    found: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in _EMAIL.finditer(line):
            if not _email_is_documentation(match.group(1)):
                found.append(
                    Finding(
                        path,
                        number,
                        "real-looking email address",
                        match.group(0),
                    )
                )
        for match in _HOME_PATH.finditer(line):
            found.append(Finding(path, number, "absolute home directory", match.group(0)))
    return found


def _readable(path: Path) -> bool:
    if path.name in _SKIP_NAMES or path.suffix.lower() in _SKIP_SUFFIXES:
        return False
    return path.is_file()


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _git(*args: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.split("\0") if line]


def tracked_files() -> list[str]:
    return _git("ls-files", "-z")


def staged_files() -> list[str]:
    return _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")


def scan(paths: list[str]) -> list[Finding]:
    found: list[Finding] = []
    for name in paths:
        path = REPO_ROOT / name
        if not _readable(path):
            continue
        text = _read(path)
        if text is not None:
            found.extend(scan_text(name, text))
    return found


def main(argv: list[str]) -> int:
    staged = "--staged" in argv
    findings = scan(staged_files() if staged else tracked_files())
    if not findings:
        return 0
    where = "staged for commit" if staged else "tracked in this repository"
    print(f"\nCorpus data {where}:\n", file=sys.stderr)
    for finding in findings:
        print(f"  {finding}", file=sys.stderr)
    print(
        "\nThis repository is public and the case corpus is not. Replace the value\n"
        "with a synthetic one — see tests/synthetic.py for the cast of invented\n"
        "people, and use example.com / example.edu for addresses and ~ for paths.\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
