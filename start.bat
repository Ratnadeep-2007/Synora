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
echo    [1] Start All Services (Backend + Frontend + WhatsApp Baileys) [DEFAULT]
echo    [2] Start Backend API Only (:8000)
echo    [3] Start Frontend UI Only (:3000)
echo    [4] Start WhatsApp Baileys Bridge Only
echo    [5] Run Full Test Suite (pytest)
echo    [6] Refresh Health and Port Status
echo    [0] Exit
echo ==============================================================================
echo.

choice /t 5 /d 1 /c 1234560 /m "Enter choice (auto-starts [1] in 5 seconds): "
set "SEL=%errorlevel%"

if "%SEL%"=="1" goto opt_all
if "%SEL%"=="2" goto opt_backend
if "%SEL%"=="3" goto opt_frontend
if "%SEL%"=="4" goto opt_baileys
if "%SEL%"=="5" goto opt_tests
if "%SEL%"=="6" goto menu
if "%SEL%"=="7" goto opt_exit
goto opt_all

:opt_all
echo.
echo ==============================================================================
echo [1/3] Launching Backend API in new window (http://localhost:8000)...
start "Synora Backend (API :8000)" cmd /k call "%~dp0start_backend.bat"

echo [2/3] Launching Frontend UI in new window (http://localhost:3000)...
start "Synora Frontend (UI :3000)" cmd /k call "%~dp0start_frontend.bat"

echo [3/3] Launching WhatsApp Baileys Bridge in new window...
start "Synora WhatsApp Baileys Bridge" cmd /k call "%~dp0start_baileys.bat"

echo.
echo ==============================================================================
echo                        SERVICES LAUNCHED SUCCESSFULLY                        
echo ==============================================================================
echo  - Frontend Web UI:          http://localhost:3000
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

:opt_exit
echo Exiting Synora Launcher.
exit /b 0
