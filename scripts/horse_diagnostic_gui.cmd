@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
    echo Die lokale Python-Umgebung fehlt. Bitte zuerst setup.bat ausführen.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "scripts\horse_diagnostic_gui.py"
if errorlevel 1 (
    echo.
    echo Die Mount-Diagnose wurde mit einem Fehler beendet.
    pause
    exit /b 1
)

exit /b 0
