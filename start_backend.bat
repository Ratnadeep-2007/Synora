@echo off
setlocal enabledelayedexpansion
title Synora Backend API Server (:8000)

:: Always ensure working directory is repo root
cd /d "%~dp0"

echo ==============================================================================
echo                         SYNORA BACKEND SERVER                                
echo                FastAPI + SQLite + Event Pipeline (Port 8000)                  
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
    echo [ERROR] Python 3.11+ executable could not be found!
    echo Please install Python 3.11+ or activate your virtual environment.
    echo.
    pause
    exit /b 1
)

echo [OK] Using Python: !PYTHON_EXE!

:: 2. Check for required backend packages
"!PYTHON_EXE!" -c "import fastapi, uvicorn" >nul 2>&1
if !errorlevel! neq 0 (
    echo [WARNING] FastAPI or Uvicorn missing in Python environment.
    echo Installing backend dependencies from requirements.txt...
    "!PYTHON_EXE!" -m pip install -r backend\requirements.txt
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to install backend dependencies.
        pause
        exit /b 1
    )
)

:: 3. Check if port 8000 is already occupied
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul 2>&1
if !errorlevel! equ 0 (
    echo [WARNING] Port 8000 is already in use by another process!
    echo If this is an existing Synesis server, please close it first.
    echo.
)

echo.
echo Starting FastAPI on http://localhost:8000 ...
echo Interactive API documentation available at http://localhost:8000/docs
echo System Health available at http://localhost:8000/health
echo Operational Metrics available at http://localhost:8000/metrics
echo.
echo Press CTRL+C to stop the server.
echo ==============================================================================
echo.

"!PYTHON_EXE!" run_backend.py

if !errorlevel! neq 0 (
    echo.
    echo [ERROR] Backend process exited with error code !errorlevel!.
)

echo.
pause
