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
set "MCBE_LOCAL_URL=http://%MCBE_EDITOR_HOST%:%MCBE_EDITOR_PORT%/"
set "MCBE_OPEN_BROWSER=false"
set "MCBE_REQUIRE_SERVER_OFFLINE=false"

start "MCBE Browser Launcher" /min powershell.exe -NoProfile -Command "$url=$env:MCBE_LOCAL_URL; $hostName=$env:MCBE_EDITOR_HOST; $port=[int]$env:MCBE_EDITOR_PORT; function Test-Ready { $client=New-Object Net.Sockets.TcpClient; try { $connect=$client.BeginConnect($hostName,$port,$null,$null); if (-not $connect.AsyncWaitHandle.WaitOne(700)) { return $false }; $client.EndConnect($connect); return $true } catch { return $false } finally { $client.Close() } }; Start-Sleep -Seconds 4; if (Test-Ready) { Start-Process $url; exit 0 }; Start-Sleep -Seconds 4; if (Test-Ready) { Start-Process $url; exit 0 }; Start-Process $url"

".venv\Scripts\python.exe" main.py
if errorlevel 1 (
    echo.
    echo Failed to start the server.
    pause
    exit /b 1
)
