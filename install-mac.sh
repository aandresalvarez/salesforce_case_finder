#!/usr/bin/env bash
#
# Case Finder — macOS setup. Spec section 11.2.
#
# Run once:  ./install-mac.sh
# Then:      ./run-mac.sh
#
# Nothing here needs admin rights and nothing is installed system-wide. `uv`
# goes into ~/.local/bin and the Python environment into ./.venv, so removing
# the app is deleting this folder.

# `-e` is deliberately absent. This script's last act is to run the self-check
# and then tell the user what its result means, and under `-e` a self-check that
# reported a problem killed the script on the spot — so the one run that most
# needed the closing advice was the only run that never printed it. The same
# applied to the sign-in step: cancelling the browser prompt aborted the whole
# install. Failures are checked where they happen instead.
set -uo pipefail

cd "$(dirname "$0")"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; }

# --------------------------------------------------------------------------
# 1. uv
# --------------------------------------------------------------------------
bold "1. Package manager"

if command -v uv >/dev/null 2>&1; then
  ok "uv $(uv --version | awk '{print $2}') is already installed"
else
  warn "uv not found — installing it into ~/.local/bin"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # The installer edits the shell profile, which does not affect a script that
  # is already running, so this session gets the path directly.
  export PATH="$HOME/.local/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    fail "uv installed but is not on PATH. Open a new terminal and re-run this script."
    exit 1
  fi
  ok "uv $(uv --version | awk '{print $2}') installed"
fi

# --------------------------------------------------------------------------
# 2. Python environment
# --------------------------------------------------------------------------
bold "2. Environment"

# --frozen installs exactly what uv.lock records. Without it a resolver run on
# a new machine can pick a different pywebview, which is the one dependency
# whose version decides whether the desktop window opens at all.
if [ -f uv.lock ]; then
  uv sync --frozen --extra ask
else
  uv sync --extra ask
fi
if [ $? -ne 0 ]; then
  fail "could not install dependencies — nothing below this point will work"
  exit 1
fi
ok "dependencies installed into ./.venv"

# --------------------------------------------------------------------------
# 3. Google Cloud SDK
# --------------------------------------------------------------------------
bold "3. Google Cloud"

if command -v gcloud >/dev/null 2>&1; then
  ok "$(gcloud version 2>/dev/null | head -1)"
else
  fail "gcloud is not installed."
  echo
  echo "  Case Finder signs in with the credentials already on this Mac, so it"
  echo "  needs the Google Cloud CLI. Install it with Homebrew:"
  echo
  echo "      brew install --cask google-cloud-sdk"
  echo
  echo "  or follow https://cloud.google.com/sdk/docs/install-sdk"
  echo "  Then re-run this script."
  exit 1
fi

# --------------------------------------------------------------------------
# 4. Application Default Credentials
# --------------------------------------------------------------------------
bold "4. Credentials"

# ADC, not a service-account key: the app ships no secret and every user reads
# exactly what BigQuery IAM already lets them read (spec section 9.1).
ADC="$HOME/.config/gcloud/application_default_credentials.json"

if [ -f "$ADC" ]; then
  ok "application default credentials are present"
else
  warn "no application default credentials on this machine"
  if [ -t 0 ]; then
    printf '    Sign in now? [Y/n] '
    read -r reply
    case "${reply:-y}" in
      [Nn]*) warn "skipped — run 'gcloud auth application-default login' before first use" ;;
      # Cancelling the browser prompt exits non-zero, which is a choice and not
      # an error. The self-check below reports it either way.
      *)     gcloud auth application-default login || \
               warn "sign-in did not complete — the self-check below will say so" ;;
    esac
  else
    warn "run this before first use:  gcloud auth application-default login"
  fi
fi

# --------------------------------------------------------------------------
# 5. Self-check
# --------------------------------------------------------------------------
bold "5. Self-check"

# The checks themselves live in `casefinder/selfcheck.py` rather than here, so
# that they also exist on a machine that installed the app from a wheel and
# never saw this script. It checks more than this heredoc used to — gcloud and
# the credentials file are re-tested at the end, and the packaged team presets
# are new — and it checks the webview the same way, by importing the backend
# rather than opening a window.
uv run --frozen casefinder --check
status=$?

echo
if [ "$status" -eq 0 ]; then
  bold "Ready. Start it with ./run-mac.sh"
else
  bold "Setup finished with warnings above. Fix those, then run ./run-mac.sh"
fi
exit "$status"
