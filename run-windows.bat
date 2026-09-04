@echo off
REM Case Finder - Windows launcher. Spec section 11.3.
REM
REM   run-windows.bat                  native desktop window
REM   set CASEFINDER_NATIVE=0 && run-windows.bat
REM                                    browser tab, for a PC whose WebView2
REM                                    runtime will not start
REM
REM Double-clicking this file opens a console window that closes the instant
REM the app exits, which would hide a startup error completely. So a non-zero
REM exit holds the window open until the user has read it.

setlocal
cd /d "%~dp0"

where uv >nul 2>&1
if errorlevel 1 set "PATH=%USERPROFILE%\.local\bin;%PATH%"

where uv >nul 2>&1
if errorlevel 1 (
    echo Case Finder is not set up on this PC yet.
    echo Run install-windows.ps1 first:
    echo.
    echo     powershell -ExecutionPolicy Bypass -File .\install-windows.ps1
    echo.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo No .venv folder here. Run install-windows.ps1 first.
    echo.
    pause
    exit /b 1
)

REM --frozen so launching the app never silently re-resolves dependencies.
uv run --frozen python -m casefinder.main %*
set "STATUS=%ERRORLEVEL%"

if not "%STATUS%"=="0" (
    echo.
    echo Case Finder exited with code %STATUS%.
    echo The error is printed above. If the desktop window would not open, try
    echo a browser tab instead:
    echo.
    echo     set CASEFINDER_NATIVE=0 ^&^& run-windows.bat
    echo.
    pause
)

exit /b %STATUS%
