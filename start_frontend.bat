@echo off
setlocal enabledelayedexpansion
title Synora Frontend Next.js Dev Server (:3002)

:: Always ensure working directory is frontend directory
cd /d "%~dp0frontend"

echo ==============================================================================
echo                         SYNORA FRONTEND SERVER                               
echo                Next.js 14 + Tailwind CSS + Flow (Port 3002)                   
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

:: 3. Kill stale synora_2 servers (old UI defaults to :3000 and must never
::    be what the browser lands on), then check if port 3002 is occupied.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -State Listen -LocalPort 3000,3001 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { $w = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $_) -ErrorAction SilentlyContinue; if ($w -and $w.CommandLine -match 'synora_2') { Stop-Process -Id $w.ParentProcessId -Force -ErrorAction SilentlyContinue; Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }"
netstat -ano | findstr /R /C:":3002 .*LISTENING" >nul 2>&1
if !errorlevel! equ 0 (
    echo [WARNING] Port 3002 is already in use by another process!
    echo Next.js will typically try port 3003 if 3002 is unavailable.
    echo.
)

echo Starting Next.js Dev Server on http://localhost:3002 ...
echo Press CTRL+C to stop the frontend server.
echo ==============================================================================
echo.

:: package.json pins "dev" to --port 3002 --hostname 127.0.0.1; never rely on
:: the Next.js default port (3000), which is what the stale clone serves.
call npm run dev

if !errorlevel! neq 0 (
    echo.
    echo [ERROR] Frontend process exited with error code !errorlevel!.
)

echo.
pause
