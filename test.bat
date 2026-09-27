@echo off
setlocal enabledelayedexpansion
title Synesis Automated Test Suite Runner

cd /d "%~dp0"

echo ==============================================================================
echo                         SYNESIS TEST SUITE RUNNER                             
echo       Running Full Automated Test Suite Across All Subsystems (Wave B)        
echo ==============================================================================
echo.

:: 1. Locate working Python executable
set "PYTHON_EXE="

if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else if exist "%~dp0venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
) else if defined LOCALAPPDATA if exist "%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe"
) else if exist "C:\Users\ratna\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" (
    set "PYTHON_EXE=C:\Users\ratna\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "delims=" %%I in ('where python') do (
            if not defined PYTHON_EXE (
                "%%I" --version >nul 2>&1
                if !errorlevel! equ 0 set "PYTHON_EXE=%%I"
            )
        )
    )
)

if not defined PYTHON_EXE (
    where py >nul 2>&1
    if !errorlevel! equ 0 (
        py -3 --version >nul 2>&1
        if !errorlevel! equ 0 set "PYTHON_EXE=py -3"
    )
)

if not defined PYTHON_EXE (
    echo [ERROR] Python was not found!
    echo Please ensure Python 3.11+ is installed.
    echo.
    pause
    exit /b 1
)

echo [OK] Using Python: !PYTHON_EXE!
echo.
echo Executing pytest backend/tests -v --durations=5 ...
echo ==============================================================================
echo.

"!PYTHON_EXE!" -m pytest backend/tests -v --durations=5

echo.
echo ==============================================================================
echo Test run complete.
echo ==============================================================================
echo.
pause
