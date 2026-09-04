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

set -euo pipefail

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
      *)     gcloud auth application-default login ;;
    esac
  else
    warn "run this before first use:  gcloud auth application-default login"
  fi
fi

# --------------------------------------------------------------------------
# 5. Self-check
# --------------------------------------------------------------------------
bold "5. Self-check"

# The webview backend is checked by importing it rather than by opening a
# window. Known limitation 13 is that native mode adds a platform-webview
# surface that did not exist in the browser build; on macOS that surface is the
# pyobjc bridge to WebKit, and if it imports here it will load at runtime.
uv run --frozen python - <<'PY'
import sys

failures = 0

try:
    from webview.platforms import cocoa  # noqa: F401
    print("  \033[32m✓\033[0m macOS webview backend available")
except Exception as exc:
    failures += 1
    print(f"  \033[31m✗\033[0m macOS webview backend unavailable: {type(exc).__name__}: {exc}")
    print("      The app can still run in a browser tab:  CASEFINDER_NATIVE=0 ./run-mac.sh")

from casefinder import config
print(f"  \033[32m✓\033[0m Case Finder {config.VERSION} imports cleanly")

try:
    from casefinder import bq
    ok, message = bq.check_access()
except Exception as exc:  # noqa: BLE001
    ok, message = False, str(exc)

if ok:
    print(f"  \033[32m✓\033[0m {message}")
else:
    failures += 1
    print("  \033[33m!\033[0m BigQuery is not reachable yet:")
    for line in message.strip().splitlines():
        print(f"      {line}")

sys.exit(1 if failures else 0)
PY
status=$?

echo
if [ "$status" -eq 0 ]; then
  bold "Ready. Start it with ./run-mac.sh"
else
  bold "Setup finished with warnings above. Fix those, then run ./run-mac.sh"
fi
exit "$status"
