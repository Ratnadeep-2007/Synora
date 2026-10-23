@echo off
setlocal enabledelayedexpansion
title Synora Platform Launcher

:: Ensure working directory is script directory
cd /d "%~dp0"

:: Handle CLI arguments if provided (e.g. start.bat backend, start.bat test, start.bat baileys)
if /i "%~1"=="backend" goto opt_backend
if /i "%~1"=="frontend" goto opt_frontend
if /i "%~1"=="baileys" goto opt_baileys
if /i "%~1"=="whatsapp" goto opt_baileys
if /i "%~1"=="test" goto opt_tests
if /i "%~1"=="tests" goto opt_tests
if /i "%~1"=="all" goto opt_all
if /i "%~1"=="both" goto opt_all
if /i "%~1"=="core" goto opt_core
if /i "%~1"=="backendfrontend" goto opt_core
if /i "%~1"=="bf" goto opt_core
if /i "%~1"=="agent" goto opt_agent

:menu
cls
echo ==============================================================================
echo                         SYNORA PLATFORM LAUNCHER                              
echo       Project Intelligence and Living Architecture Platform (Excalidraw)      
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

netstat -ano | findstr /R /C:":3002 .*LISTENING" >nul 2>&1
if !errorlevel! equ 0 (
    echo  [!] Port 3002 is currently in use (Frontend already running or port occupied)
) else (
    echo  [OK] Port 3002 is available for Frontend.
)

echo.
echo ==============================================================================
echo  Please select an option:
echo.
echo    [1] Start All Services (Backend + Frontend + WhatsApp Baileys) [DEFAULT]
echo    [2] Start Backend API Only (:8000)
echo    [3] Start Frontend UI Only (:3002)
echo    [4] Start WhatsApp Baileys Bridge Only
echo    [5] Run Full Test Suite (pytest)
echo    [6] Refresh Health and Port Status
echo    [7] Start Backend + Frontend ONLY (:8000 + :3002, no Baileys, no workers)
echo    [8] Local Agent Mode (Vexa + Baileys only, app from Render)
echo    [0] Exit
echo ==============================================================================
echo.

choice /t 5 /d 1 /c 123456780 /m "Enter choice (auto-starts [1] in 5 seconds): "
set "SEL=%errorlevel%"

if "%SEL%"=="1" goto opt_all
if "%SEL%"=="2" goto opt_backend
if "%SEL%"=="3" goto opt_frontend
if "%SEL%"=="4" goto opt_baileys
if "%SEL%"=="5" goto opt_tests
if "%SEL%"=="6" goto menu
if "%SEL%"=="7" goto opt_core
if "%SEL%"=="8" goto opt_agent
if "%SEL%"=="9" goto opt_exit
goto opt_all

:opt_all
echo.
call :kill_stale_clones
echo ==============================================================================
echo [1/3] Launching Backend API in new window (http://localhost:8000)...
start "Synora Backend (API :8000)" cmd /k call "%~dp0start_backend.bat"

echo [2/3] Launching Frontend UI in new window (http://localhost:3002)...
start "Synora Frontend (UI :3002)" cmd /k call "%~dp0start_frontend.bat"

echo [3/3] Launching WhatsApp Baileys Bridge in new window...
start "Synora WhatsApp Baileys Bridge" cmd /k call "%~dp0start_baileys.bat"

echo.
echo ==============================================================================
echo                        SERVICES LAUNCHED SUCCESSFULLY                        
echo ==============================================================================
echo  - Frontend Web UI:          http://localhost:3002
echo  - Backend API and Docs:     http://localhost:8000/docs
echo  - System Health:            http://localhost:8000/health
echo  - WhatsApp Baileys Bridge:  Running in dedicated window (QR code prompt)
echo ==============================================================================
echo.
echo Dedicated terminal windows have been opened for Backend, Frontend, and Baileys.
echo To link WhatsApp, scan the QR code in the Baileys window with your phone.
echo To terminate a service, press CTRL+C in its dedicated window.
echo.
pause
exit /b 0

:opt_core
echo.
call :kill_stale_clones
echo ==============================================================================
echo [1/2] Launching Backend API in new window (http://localhost:8000)...
start "Synora Backend (API :8000)" cmd /k call "%~dp0start_backend.bat"

echo [2/2] Launching Frontend UI in new window (http://localhost:3002)...
start "Synora Frontend (UI :3002)" cmd /k call "%~dp0start_frontend.bat"

echo.
echo ==============================================================================
echo              BACKEND + FRONTEND LAUNCHED (no Baileys, no workers)
echo ==============================================================================
echo  - Frontend Web UI:          http://localhost:3002
echo  - Backend API and Docs:     http://localhost:8000/docs
echo  - System Health:            http://localhost:8000/health
echo ==============================================================================
echo.
echo Dedicated terminal windows have been opened for Backend and Frontend only.
echo WhatsApp Baileys and background workers were NOT started (they run on Render).
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

:opt_baileys
echo.
echo Launching WhatsApp Baileys Bridge in this console...
call "%~dp0start_baileys.bat"
goto menu

:opt_tests
echo.
echo Launching test suite in this console...
call "%~dp0test.bat"
goto menu

:opt_agent
echo.
echo Starting Local Agent Mode (Vexa + Baileys on this laptop, app on Render)...
call "%~dp0start_agent.bat"
goto menu

:opt_exit
echo Exiting Synora Launcher.
exit /b 0

:kill_stale_clones
:: The stale synora_2 clone serves its old UI on :3000 (Next default) and can
:: also hold :8000 with an outdated backend. Kill any listener whose owning
:: process was launched from synora_2 so this launcher only ever serves the
:: current UI on :3002 against the current backend on :8000.
echo [Cleanup] Stopping stale synora_2 servers on :3000/:3001/:3002/:8000 if present...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -State Listen -LocalPort 3000,3001,3002,8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { $w = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $_) -ErrorAction SilentlyContinue; if ($w -and $w.CommandLine -match 'synora_2') { Stop-Process -Id $w.ParentProcessId -Force -ErrorAction SilentlyContinue; Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }"
exit /b 0
