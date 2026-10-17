@echo off
setlocal enabledelayedexpansion
title Synora Local Agent (Vexa + Baileys for Render)
cd /d "%~dp0"

:: Local-agent mode: start ONLY the pieces that cannot run on Render
:: (Vexa Meet bot + WhatsApp Baileys bridge) on this laptop. Frontend,
:: backend API and database are the Render deployment for all users:
:: https://synora-frontend.onrender.com

set "PYTHON_EXE="
if exist "%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if !errorlevel! equ 0 set "PYTHON_EXE=python"
)

if not defined PYTHON_EXE (
    echo [ERROR] Python not found. Install Python 3.11+ or run scripts\start_local_agent.py manually.
    pause
    exit /b 1
)

"!PYTHON_EXE!" "%~dp0scripts\start_local_agent.py"
echo.
pause
exit /b 0
