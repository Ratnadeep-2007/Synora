@echo off
setlocal enabledelayedexpansion
title Synesis Platform Launcher (Wave B)

:: Ensure working directory is script directory
cd /d "%~dp0"

:: Handle CLI arguments if provided (e.g. start.bat backend, start.bat test)
if /i "%~1"=="backend" goto opt_backend
if /i "%~1"=="frontend" goto opt_frontend
if /i "%~1"=="test" goto opt_tests
if /i "%~1"=="tests" goto opt_tests
if /i "%~1"=="all" goto opt_both
if /i "%~1"=="both" goto opt_both

:menu
cls
echo ==============================================================================
echo                         SYNESIS PLATFORM LAUNCHER                            
echo          Project Intelligence and AI Workforce Platform (Wave B)            
echo ==============================================================================
echo.
echo  Checking system environment:

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

if defined PYTHON_EXE (
    echo  [OK] Python interpreter found: !PYTHON_EXE!
) else (
    echo  [!!] Python not found! (Please install Python 3.11+)
)

:: 2. Check npm
where npm >nul 2>&1
if !errorlevel! equ 0 (
    echo  [OK] Node.js and npm found on PATH.
) else (
    echo  [!!] npm not found! (Please install Node.js 18+)
)

:: 3. Check active ports
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul 2>&1
if !errorlevel! equ 0 (
    echo  [!] Port 8000 is currently in use (Backend already running or port occupied)
) else (
    echo  [OK] Port 8000 is available for Backend.
)

netstat -ano | findstr /R /C:":3000 .*LISTENING" >nul 2>&1
if !errorlevel! equ 0 (
    echo  [!] Port 3000 is currently in use (Frontend already running or port occupied)
) else (
    echo  [OK] Port 3000 is available for Frontend.
)

echo.
echo ==============================================================================
echo  Please select an option:
echo.
echo    [1] Start Both Services (Backend + Frontend in separate windows) [DEFAULT]
echo    [2] Start Backend API Only (:8000)
echo    [3] Start Frontend UI Only (:3000)
echo    [4] Run Full Test Suite (pytest - 138 tests)
echo    [5] Refresh Health and Port Status
echo    [0] Exit
echo ==============================================================================
echo.

choice /t 5 /d 1 /c 123450 /m "Enter choice (auto-starts [1] in 5 seconds): "
set "SEL=%errorlevel%"

if "%SEL%"=="1" goto opt_both
if "%SEL%"=="2" goto opt_backend
if "%SEL%"=="3" goto opt_frontend
if "%SEL%"=="4" goto opt_tests
if "%SEL%"=="5" goto menu
if "%SEL%"=="6" goto opt_exit
goto opt_both

:opt_both
echo.
echo ==============================================================================
echo [1/2] Launching Backend API in new window (http://localhost:8000)...
start "Synesis Backend (API :8000)" cmd /k call "%~dp0start_backend.bat"

echo [2/2] Launching Frontend UI in new window (http://localhost:3000)...
start "Synesis Frontend (UI :3000)" cmd /k call "%~dp0start_frontend.bat"

echo.
echo ==============================================================================
echo                        SERVICES LAUNCHED SUCCESSFULLY                        
echo ==============================================================================
echo  - Frontend Web UI:       http://localhost:3000
echo  - Backend API and Docs:  http://localhost:8000/docs
echo  - System Health:         http://localhost:8000/health
echo  - Operational Metrics:   http://localhost:8000/metrics
echo ==============================================================================
echo.
echo Dedicated terminal windows have been opened for Backend and Frontend.
echo You can inspect logs, errors, and live requests in those windows.
echo To terminate a service, press CTRL+C in its dedicated window.
echo.
pause
exit /b 0

:opt_backend
echo.
echo Launching Backend server in this console...
call "%~dp0start_backend.bat"
goto menu

:opt_frontend
echo.
echo Launching Frontend server in this console...
call "%~dp0start_frontend.bat"
goto menu

:opt_tests
echo.
echo Launching test suite in this console...
call "%~dp0test.bat"
goto menu

:opt_exit
echo Exiting Synesis Launcher.
exit /b 0
