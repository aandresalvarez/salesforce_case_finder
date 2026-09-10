#!/usr/bin/env bash
#
# Case Finder — build the wheel that gets handed to people.
#
# Run:  ./release.sh
# Out:  dist/casefinder-<version>-py3-none-any.whl
#       dist/requirements-lock.txt
#
# Neither file is committed (`dist/` is gitignored, and uv writes its own
# `dist/.gitignore` besides). They are attached to a release; this script is how
# they are produced so that two people producing them get the same thing.
#
# The gate below is the point of having a script at all. Hatchling packages the
# *working tree*, not the commit — so a wheel built over uncommitted edits ships
# code that is in nobody's repository. In this repository that is not merely
# untidy. The corpus guard runs on what git tracks, at commit time; an edit that
# has never been committed has never been scanned, and the wheel is the one
# artifact that leaves the machine. So: clean tree, or no build.

set -uo pipefail

cd "$(dirname "$0")"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; }

# --------------------------------------------------------------------------
# 1. A clean tree
# --------------------------------------------------------------------------
bold "1. Working tree"

# `--porcelain` covers staged, unstaged and untracked in one answer, which is
# the right granularity: an untracked file under `casefinder/` is exactly the
# case that ships unscanned. It is reported rather than stashed — a build script
# that moves someone's uncommitted work somewhere they did not ask for it is a
# worse problem than the one it solves.
dirty=$(git status --porcelain)
if [ -n "$dirty" ]; then
  fail "the working tree has changes, so the wheel would not match any commit:"
  printf '%s\n' "$dirty" | sed 's/^/      /'
  echo
  echo "  Commit them (the pre-commit hook scans them) or stash them yourself,"
  echo "  then run this again."
  exit 1
fi
ok "clean, at $(git rev-parse --short HEAD)"

# --------------------------------------------------------------------------
# 2. Lint and tests
# --------------------------------------------------------------------------
bold "2. Checks"

uv run --frozen ruff check . || { fail "lint failed"; exit 1; }
ok "ruff"

# The full suite, including the corpus guard and the packaging tests. The
# packaging tests are the ones that matter here: they are the only assertions
# about the wheel that run before the wheel exists.
uv run --frozen pytest -q || { fail "tests failed"; exit 1; }
ok "tests"

# --------------------------------------------------------------------------
# 3. Build
# --------------------------------------------------------------------------
bold "3. Build"

rm -rf dist
uv build --wheel || { fail "build failed"; exit 1; }

wheel=$(ls dist/*.whl 2>/dev/null | head -1)
if [ -z "$wheel" ]; then
  fail "no wheel was produced"
  exit 1
fi

# The presets are force-included rather than picked up as package data, and a
# wheel missing them installs and runs perfectly while quietly having no team
# views. Cheaper to assert here than to discover on someone's laptop.
#
# Listed once into a variable and matched with `case` rather than piped into
# `grep -q`. Under `pipefail` that pipeline reports failure even on a match:
# `grep -q` exits the moment it finds one, `unzip` writes into the closed pipe
# and dies of SIGPIPE, and the pipeline takes its status from that. Which is to
# say this check failed on a wheel that was correct, the first time it ran.
listing=$(unzip -l "$wheel")
case "$listing" in
  *"casefinder/views.json"*) ;;
  *)
    fail "views.json is not in the wheel — the team presets would be missing"
    exit 1
    ;;
esac
ok "$(basename "$wheel") ($(printf '%s\n' "$listing" | tail -1 | awk '{print $2}') files, presets included)"

# --------------------------------------------------------------------------
# 4. Lock file
# --------------------------------------------------------------------------
bold "4. Lock file"

# One file for both platforms: `uv export` writes environment markers, so the
# macOS-only and Windows-only pins carry their own conditions and pip installs
# the right subset on each. `--extra ask` so the optional feature's dependencies
# are pinned too — someone installing with `[ask]` is installing more, and a
# lock file that stops at the base install would not cover it.
# `--quiet` because without it `uv export` echoes all ninety lines to the
# terminal as well as writing them, which buries every other line this script
# prints.
uv export --frozen --no-emit-project --no-hashes --extra ask --quiet \
  -o dist/requirements-lock.txt || { fail "export failed"; exit 1; }
ok "requirements-lock.txt ($(grep -c '==' dist/requirements-lock.txt) pinned)"

echo
bold "Built:"
printf '  %s\n' dist/*
echo
# A release asset rather than a commit. A wheel in git history is permanent —
# every clone fetches every version ever committed, and a force-push does not
# remove it, which is the same reason the corpus rule says what it says.
version=$(uv run --frozen casefinder --version | awk '{print $NF}')
echo "Publish with:"
echo "  git tag v$version && git push origin v$version"
echo "  gh release create v$version dist/* --title \"Case Finder $version\""
