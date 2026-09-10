#!/usr/bin/env bash
#
# Case Finder — build the wheel that gets handed to people, and publish it.
#
# Run:  ./release.sh              build and verify, publish nothing
#       ./release.sh --publish    the same, then tag and publish to GitHub
#
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
#
# Publishing lives behind a flag on this same script rather than in one of its
# own, so that the gate and the upload cannot come apart: there is no way to
# push a wheel to GitHub that did not just pass every check above it.

set -uo pipefail

cd "$(dirname "$0")"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; }

publish=0
for arg in "$@"; do
  case "$arg" in
    --publish) publish=1 ;;
    -h|--help)
      sed -n '3,7p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      fail "unrecognised option: $arg"
      echo "  usage: ./release.sh [--publish]"
      exit 2
      ;;
  esac
done

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

# Asked of the app rather than parsed out of the filename or `config.py`, so it
# is the version the built artifact actually reports.
version=$(uv run --frozen casefinder --version | awk '{print $NF}')
if [ -z "$version" ]; then
  fail "could not read the version out of the app"
  exit 1
fi
ok "version $version"

# The README and the proposal both print the install line, URL and all, and that
# URL names a version. Nothing regenerates them, so they go stale silently: the
# release succeeds, the page looks right, and the command people copy installs
# the version before this one. Checked here rather than rewritten, because a
# build script that edits tracked files has just invalidated the clean tree it
# insisted on two stages ago.
stale=$(grep -oh 'releases/download/v[^/]*/' README.md PROPOSAL.md 2>/dev/null \
        | grep -v "releases/download/v$version/" | sort -u)
if [ -n "$stale" ]; then
  fail "the docs still hand out an older version:"
  printf '%s\n' "$stale" | sed 's/^/      /'
  echo "      expected releases/download/v$version/"
  exit 1
fi
ok "README and PROPOSAL point at v$version"

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

if [ "$publish" -eq 0 ]; then
  echo "Nothing published. To tag this build and put it on GitHub:"
  echo "  ./release.sh --publish"
  exit 0
fi

# --------------------------------------------------------------------------
# 5. Publish
# --------------------------------------------------------------------------
#
# A release asset rather than a commit. A wheel in git history is permanent —
# every clone fetches every version ever committed, and a force-push does not
# remove it, which is the same reason the corpus rule says what it says.
bold "5. Publish"

tag="v$version"

command -v gh >/dev/null 2>&1 || {
  fail "the GitHub CLI is not installed — https://cli.github.com"
  exit 1
}
gh auth status >/dev/null 2>&1 || {
  fail "gh is not signed in — run: gh auth login"
  exit 1
}

git fetch --quiet origin || { fail "could not reach origin"; exit 1; }

# Refuse, never move. A pushed tag is a tag somebody may already have installed
# from, and re-pointing it changes what a URL means — which is the one thing a
# download URL must never do. So the way to publish again is to be a new
# version, not to overwrite an old one.
taken=""
git rev-parse -q --verify "refs/tags/$tag" >/dev/null 2>&1 && taken="locally"
git ls-remote --exit-code --tags origin "$tag" >/dev/null 2>&1 && taken="on origin"
if [ -n "$taken" ]; then
  fail "$tag already exists $taken"
  echo "  A release is a new version, not a moved tag. Bump VERSION in"
  echo "  casefinder/config.py, commit, and run this again."
  exit 1
fi

# The commit has to be on origin before a tag points at it, or the release names
# a commit nobody else can fetch.
branch=$(git branch --show-current)
if [ "$(git rev-parse HEAD)" != "$(git rev-parse "origin/$branch" 2>/dev/null)" ]; then
  fail "HEAD is not on origin/$branch, so the release would point at a commit nobody can fetch"
  echo "  git push origin $branch"
  exit 1
fi
ok "gh signed in · $tag is free · HEAD is on origin/$branch"

slug=$(gh repo view --json nameWithOwner -q .nameWithOwner) || {
  fail "could not work out which repository this is"
  exit 1
}
asset_url="https://github.com/$slug/releases/download/$tag/$(basename "$wheel")"

git tag -a "$tag" -m "Case Finder $version" || { fail "could not create $tag"; exit 1; }
git push --quiet origin "$tag" || {
  fail "could not push $tag"
  # Undo the local half, so a second run is not blocked by this run's leftovers.
  git tag -d "$tag" >/dev/null 2>&1
  exit 1
}
ok "tagged $tag and pushed it"

# `--generate-notes` appends the commit log under whatever `--notes` says, so
# the install instructions lead and the changelog follows. The access paragraph
# is repeated on every release on purpose: it is the first question anyone asks
# about a tool that reads a PHI corpus, and a release page is read by people who
# have not read the README.
notes="Install on macOS or Windows — or update a copy that is already installed:

\`\`\`
uv tool install --force \"$asset_url\"
casefinder --check
\`\`\`

An installed copy can also update itself in place: \`casefinder --update\`.

**Access.** Case Finder runs under your own Google credentials and ships no
service-account key. Installing it grants nothing: if you cannot query the
dataset today, this does not change that."

gh release create "$tag" "$wheel" dist/requirements-lock.txt \
  --title "Case Finder $version" \
  --notes "$notes" \
  --generate-notes || { fail "gh release create failed"; exit 1; }
ok "published $tag"

# --------------------------------------------------------------------------
# 6. The published link
# --------------------------------------------------------------------------
#
# Everything above proves the wheel is right. This proves the *link* is right,
# which is a different claim and the one the README makes. curl carries none of
# gh's credentials, so it fetches the asset exactly as a teammate will.
bold "6. The published link"

code=""
for _ in 1 2 3; do
  code=$(curl -sIL -o /dev/null -w '%{http_code}' --max-time 30 "$asset_url")
  [ "$code" = "200" ] && break
  sleep 2
done
if [ "$code" != "200" ]; then
  fail "the wheel is not publicly downloadable — HTTP $code from $asset_url"
  exit 1
fi
ok "downloads unauthenticated (HTTP 200)"

# And this proves it installs. A throwaway tool directory, so whatever is on
# this machine is untouched either way.
sandbox=$(mktemp -d)
UV_TOOL_DIR="$sandbox/tools" UV_TOOL_BIN_DIR="$sandbox/bin" \
  uv tool install --quiet "$asset_url" >/dev/null 2>&1
reported=$("$sandbox/bin/casefinder" --version 2>/dev/null | awk '{print $NF}')
rm -rf "$sandbox"
if [ "$reported" != "$version" ]; then
  fail "installing from the published URL reported '$reported', expected '$version'"
  exit 1
fi
ok "installs from the URL and reports $version"

echo
bold "Released $tag"
echo "  https://github.com/$slug/releases/tag/$tag"
echo
echo "Send the team this line:"
echo "  uv tool install --force \"$asset_url\""
echo
echo "Anyone already on an older version only needs:"
echo "  casefinder --update"
