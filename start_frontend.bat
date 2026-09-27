@echo off
setlocal enabledelayedexpansion
title Synesis Frontend Next.js Dev Server (:3000)

:: Always ensure working directory is frontend directory
cd /d "%~dp0frontend"

echo ==============================================================================
echo                         SYNESIS FRONTEND SERVER                               
echo                Next.js 14 + Tailwind CSS + Flow (Port 3000)                   
echo ==============================================================================
echo.

:: 1. Verify Node.js / npm
where npm >nul 2>&1
if !errorlevel! neq 0 (
    echo [ERROR] Node.js / npm was not found on PATH!
    echo Please install Node.js 18+ from https://nodejs.org/
    echo.
    pause
    exit /b 1
)

:: 2. Ensure dependencies are installed
if not exist "%~dp0frontend\node_modules" (
    echo [INFO] node_modules not found. Running npm install...
    call npm install
    if !errorlevel! neq 0 (
        echo [ERROR] npm install failed.
        pause
        exit /b 1
    )
)

:: 3. Check if port 3000 is occupied
netstat -ano | findstr /R /C:":3000 .*LISTENING" >nul 2>&1
if !errorlevel! equ 0 (
    echo [WARNING] Port 3000 is already in use by another process!
    echo Next.js will typically try port 3001 if 3000 is unavailable.
    echo.
)

echo Starting Next.js Dev Server on http://localhost:3000 ...
echo Press CTRL+C to stop the frontend server.
echo ==============================================================================
echo.

call npm run dev

if !errorlevel! neq 0 (
    echo.
    echo [ERROR] Frontend process exited with error code !errorlevel!.
)

echo.
pause
