#!/usr/bin/env bash
#
# Case Finder — macOS launcher. Spec section 11.2.
#
#   ./run-mac.sh                    native desktop window
#   CASEFINDER_NATIVE=0 ./run-mac.sh    browser tab, for a machine whose
#                                       platform webview will not start
#
# Any CASEFINDER_* variable set in the environment is passed through; see the
# configuration table in the README.

set -euo pipefail

cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
  printf '\033[31mCase Finder is not set up on this Mac yet.\033[0m\n'
  printf 'Run ./install-mac.sh first.\n'
  exit 1
fi

if [ ! -d .venv ]; then
  printf '\033[31mNo ./.venv here.\033[0m Run ./install-mac.sh first.\n'
  exit 1
fi

# --frozen so launching the app never silently re-resolves dependencies.
exec uv run --frozen python -m casefinder.main "$@"
