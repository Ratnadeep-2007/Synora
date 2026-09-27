@echo off
setlocal enabledelayedexpansion
title Synora WhatsApp Baileys Bridge Daemon

:: Always ensure working directory is services/baileys-bridge directory
cd /d "%~dp0services\baileys-bridge"

echo ==============================================================================
echo                    SYNORA WHATSAPP BAILEYS BRIDGE DAEMON                      
echo           Lightweight Multi-Device WebSocket Bridge for Group Chats           
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
if not exist "node_modules" (
    echo [INFO] node_modules not found in baileys-bridge. Running npm install...
    call npm install
    if !errorlevel! neq 0 (
        echo [ERROR] npm install failed for Baileys bridge.
        pause
        exit /b 1
    )
)

echo Starting WhatsApp Baileys Bridge...
echo Target Backend: http://localhost:8000
echo.
echo If not already paired, a QR Code will appear below.
echo Scan it using WhatsApp on your phone (Linked Devices - Link a Device).
echo.
echo Press CTRL+C to stop the Baileys daemon.
echo ==============================================================================
echo.

call npm start

if !errorlevel! neq 0 (
    echo.
    echo [ERROR] Baileys bridge exited with error code !errorlevel!.
)

echo.
pause
