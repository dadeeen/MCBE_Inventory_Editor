@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

title MCBE Inventory Editor

if not exist ".venv\Scripts\python.exe" (
    echo .venv is missing. Please run setup.bat first.
    pause
    exit /b 1
)

set "MCBE_EDITOR_MODE=local"
set "MCBE_EDITOR_HOST=127.0.0.1"
set "MCBE_EDITOR_PORT=5000"
set "MCBE_OPEN_BROWSER=true"

".venv\Scripts\python.exe" main.py
if not "%errorlevel%"=="0" (
    echo.
    echo Failed to start the server.
    pause
    exit /b 1
)
