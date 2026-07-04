@echo off
REM ============================================================
REM  SmartDocs Platform — Windows Startup Script
REM ============================================================
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
REM Remove trailing backslash
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM Try parent .venv first (OCRSoftware/.venv), then local .venv
set "VENV_DIR=%SCRIPT_DIR%\..\..\..\venv"
set "VENV_ACTIVATE=%VENV_DIR%\Scripts\activate.bat"

echo.
echo =================================================
echo   SmartDocs Platform -- Starting up
echo =================================================

REM ── Activate virtual environment ─────────────────────────
if exist "%VENV_ACTIVATE%" (
    echo   Activating venv: %VENV_DIR%
    call "%VENV_ACTIVATE%"
) else (
    set "VENV_ACTIVATE=%SCRIPT_DIR%\.venv\Scripts\activate.bat"
    if exist "!VENV_ACTIVATE!" (
        echo   Activating local venv
        call "!VENV_ACTIVATE!"
    ) else (
        echo   WARNING: No virtual environment found.
        echo   Create one with: python -m venv .venv
        echo   Then: .venv\Scripts\activate ^&^& pip install -r requirements.txt
        pause
        exit /b 1
    )
)

REM ── Copy .env if missing ──────────────────────────────────
if not exist "%SCRIPT_DIR%\.env" (
    if exist "%SCRIPT_DIR%\.env.example" (
        echo   Creating .env from .env.example
        copy "%SCRIPT_DIR%\.env.example" "%SCRIPT_DIR%\.env" >nul
    )
)

REM ── Install / upgrade dependencies ───────────────────────
if exist "%SCRIPT_DIR%\requirements.txt" (
    echo   Checking dependencies...
    pip install -q -r "%SCRIPT_DIR%\requirements.txt"
)

REM ── Start the app ─────────────────────────────────────────
echo   Launching SmartDocs Platform...
echo.
cd /d "%SCRIPT_DIR%"
python app.py

pause
