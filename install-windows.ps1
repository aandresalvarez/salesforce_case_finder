<#
    Case Finder — Windows setup. Spec section 11.3.

    Run once, from a normal (non-elevated) PowerShell prompt:

        powershell -ExecutionPolicy Bypass -File .\install-windows.ps1

    Then:  .\run-windows.bat

    Nothing here needs administrator rights. `uv` goes into the user profile
    and the Python environment into .\.venv, so uninstalling is deleting this
    folder.
#>

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

function Write-Head($text) { Write-Host "`n$text" -ForegroundColor White }
function Write-Ok($text)   { Write-Host "  [ok]   $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "  [warn] $text" -ForegroundColor Yellow }
function Write-Fail($text) { Write-Host "  [fail] $text" -ForegroundColor Red }

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

# ---------------------------------------------------------------------------
# 1. uv
# ---------------------------------------------------------------------------
Write-Head '1. Package manager'

if (Test-Command 'uv') {
    Write-Ok "uv $((uv --version) -split ' ' | Select-Object -Index 1) is already installed"
} else {
    Write-Warn 'uv not found - installing it into the user profile'
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    # The installer updates the user PATH, which does not reach a process that
    # is already running, so this session gets the directory directly.
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    if (-not (Test-Command 'uv')) {
        Write-Fail 'uv installed but is not on PATH. Open a new PowerShell window and re-run this script.'
        exit 1
    }
    Write-Ok 'uv installed'
}

# ---------------------------------------------------------------------------
# 2. Python environment
# ---------------------------------------------------------------------------
Write-Head '2. Environment'

# --frozen installs exactly what uv.lock records. Without it a resolver run on
# a new machine can pick a different pywebview, which is the one dependency
# whose version decides whether the desktop window opens at all.
if (Test-Path 'uv.lock') {
    uv sync --frozen --extra ask
} else {
    uv sync --extra ask
}
if ($LASTEXITCODE -ne 0) { Write-Fail 'uv sync failed'; exit 1 }
Write-Ok 'dependencies installed into .\.venv'

# ---------------------------------------------------------------------------
# 3. Google Cloud SDK
# ---------------------------------------------------------------------------
Write-Head '3. Google Cloud'

if (Test-Command 'gcloud') {
    Write-Ok 'gcloud is installed'
} else {
    Write-Fail 'gcloud is not installed.'
    Write-Host ''
    Write-Host '  Case Finder signs in with the credentials already on this PC, so it'
    Write-Host '  needs the Google Cloud CLI. Install it from:'
    Write-Host ''
    Write-Host '      https://cloud.google.com/sdk/docs/install-sdk#windows'
    Write-Host ''
    Write-Host '  Then open a new PowerShell window and re-run this script.'
    exit 1
}

# ---------------------------------------------------------------------------
# 4. Application Default Credentials
# ---------------------------------------------------------------------------
Write-Head '4. Credentials'

# ADC, not a service-account key: the app ships no secret and every user reads
# exactly what BigQuery IAM already lets them read (spec section 9.1).
$adc = Join-Path $env:APPDATA 'gcloud\application_default_credentials.json'

if (Test-Path $adc) {
    Write-Ok 'application default credentials are present'
} else {
    Write-Warn 'no application default credentials on this machine'
    $reply = Read-Host '    Sign in now? [Y/n]'
    if ($reply -match '^[Nn]') {
        Write-Warn "skipped - run 'gcloud auth application-default login' before first use"
    } else {
        gcloud auth application-default login
    }
}

# ---------------------------------------------------------------------------
# 5. Self-check
# ---------------------------------------------------------------------------
Write-Head '5. Self-check'

# The webview runtime is the part of a Windows install most likely to be
# missing, and it fails at window-open time rather than at install time — which
# is exactly the failure the spec asks this script to catch early. On Windows
# pywebview draws through Microsoft Edge WebView2, which ships with Windows 11
# and current Windows 10 but not with older images.
$check = @'
import sys

failures = 0

try:
    from webview.platforms import winforms  # noqa: F401
    print("  [ok]   Windows WebView2 backend available")
except Exception as exc:
    failures += 1
    print(f"  [fail] Windows WebView2 backend unavailable: {type(exc).__name__}: {exc}")
    print("         Install the Microsoft Edge WebView2 Evergreen Runtime:")
    print("         https://developer.microsoft.com/microsoft-edge/webview2/")
    print("         Until then the app still runs in a browser tab:")
    print("             set CASEFINDER_NATIVE=0 && run-windows.bat")

from casefinder import config
print(f"  [ok]   Case Finder {config.VERSION} imports cleanly")

try:
    from casefinder import bq
    ok, message = bq.check_access()
except Exception as exc:  # noqa: BLE001
    ok, message = False, str(exc)

if ok:
    print(f"  [ok]   {message}")
else:
    failures += 1
    print("  [warn] BigQuery is not reachable yet:")
    for line in message.strip().splitlines():
        print(f"         {line}")

sys.exit(1 if failures else 0)
'@

$check | uv run --frozen python -
$status = $LASTEXITCODE

Write-Host ''
if ($status -eq 0) {
    Write-Host 'Ready. Start it with .\run-windows.bat' -ForegroundColor White
} else {
    Write-Host 'Setup finished with warnings above. Fix those, then run .\run-windows.bat' -ForegroundColor White
}
exit $status
