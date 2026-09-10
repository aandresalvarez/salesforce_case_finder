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
# PowerShell 7.4 turned native-command exit codes into terminating errors under
# `Stop`. This script's last act is to run the self-check and then say what its
# result means, so on 7.4 a self-check that reported a problem would throw
# before the advice printed — the same trap `set -e` set for the mac installer.
# Exit codes are checked explicitly here instead; this keeps them codes.
$PSNativeCommandUseErrorActionPreference = $false
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
    # Read-Host has no non-interactive form: run this script from a scheduled
    # task or a pipe and it blocks forever on a prompt nobody can see. The mac
    # installer already guarded its equivalent with `[ -t 0 ]`; this is that.
    if ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
        $reply = Read-Host '    Sign in now? [Y/n]'
        if ($reply -match '^[Nn]') {
            Write-Warn "skipped - run 'gcloud auth application-default login' before first use"
        } else {
            # Cancelling the browser prompt exits non-zero, which is a choice
            # and not an error. The self-check below reports it either way.
            gcloud auth application-default login
            if ($LASTEXITCODE -ne 0) {
                Write-Warn 'sign-in did not complete - the self-check below will say so'
            }
        }
    } else {
        Write-Warn 'run this before first use:  gcloud auth application-default login'
    }
}

# ---------------------------------------------------------------------------
# 5. Self-check
# ---------------------------------------------------------------------------
Write-Head '5. Self-check'

# The checks themselves live in `casefinder/selfcheck.py` rather than here, so
# that they also exist on a machine that installed the app from a wheel and
# never saw this script. That matters most on Windows: the WebView2 Evergreen
# Runtime is the single most likely thing to be missing on an otherwise healthy
# machine, and the URL that fixes it used to exist only inside this file.
uv run --frozen casefinder --check
$status = $LASTEXITCODE

Write-Host ''
if ($status -eq 0) {
    Write-Host 'Ready. Start it with .\run-windows.bat' -ForegroundColor White
} else {
    Write-Host 'Setup finished with warnings above. Fix those, then run .\run-windows.bat' -ForegroundColor White
}
exit $status
