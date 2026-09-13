@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

title MCBE Inventory Editor - Setup

echo MCBE Inventory Editor - local Windows setup
echo.
echo Transparency notes:
echo - The installation happens exclusively in the project folder .\.venv.
echo - No global Python packages are installed or updated.
echo - Dependencies are installed from the hash-checked lockfile.
echo - Compatible verified wheels are preferred; C++ builds require a compiler and SDK.
echo - Pip may store downloads in the user cache under AppData.
echo   That is only a download cache, not a global package installation.
echo.

set "PYTHON_CMD="

echo Creating/using the local virtual environment:
echo .\.venv
echo.

if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>nul
    if not errorlevel 1 (
        for %%V in (3.14 3.13 3.12) do (
            if not defined PYTHON_CMD (
                py -%%V scripts\windows_setup.py probe-wheel >nul 2>nul
                if not errorlevel 1 set "PYTHON_CMD=py -%%V"
            )
        )
    )

    if not defined PYTHON_CMD (
        where python >nul 2>nul
        if not errorlevel 1 (
            python scripts\windows_setup.py probe-wheel >nul 2>nul
            if not errorlevel 1 (
                set "PYTHON_CMD=python"
            )
        )
    )

    if not defined PYTHON_CMD (
        for %%V in (3.14 3.13 3.12) do (
            if not defined PYTHON_CMD (
                py -%%V scripts\windows_setup.py probe-build >nul 2>nul
                if not errorlevel 1 set "PYTHON_CMD=py -%%V"
            )
        )
        if not defined PYTHON_CMD (
            python scripts\windows_setup.py probe-build >nul 2>nul
            if not errorlevel 1 set "PYTHON_CMD=python"
        )
    )

    if not defined PYTHON_CMD (
        echo No usable Python 3.12, 3.13 or 3.14 installation was found.
        echo Use the runtime release ZIP with bundled wheels for Python 3.13/3.14 on Windows x64.
        echo A source checkout needs Python 3.12 or Microsoft C++ Build Tools with the Windows SDK.
        echo Install a supported Python from https://www.python.org/downloads/windows/
        echo Important: enable "Add Python to PATH" or the Python launcher during installation!
        pause
        exit /b 1
    )

    echo Using Python to create the virtual environment:
    !PYTHON_CMD! --version
    echo.
    echo Creating virtual environment...
    !PYTHON_CMD! -m venv .venv
    if errorlevel 1 (
        echo Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] < (3, 15) else 1)" >nul 2>nul
if errorlevel 1 (
    echo The existing virtual environment does not use a supported Python version.
    echo Please delete the .venv folder and run setup.bat again.
    echo Python 3.12, 3.13 and 3.14 are supported.
    pause
    exit /b 1
)

if not exist "requirements\bootstrap.lock" (
    echo The hash-checked lockfile requirements\bootstrap.lock is missing.
    echo The installation is aborted because pip cannot be bootstrapped reproducibly.
    pause
    exit /b 1
)

if not exist "requirements\runtime.lock" (
    echo The hash-checked lockfile requirements\runtime.lock is missing.
    echo The installation is aborted because an unlocked fallback would not be reproducible.
    pause
    exit /b 1
)

echo Checking prerequisites and installing hash-checked dependencies into .\.venv only ...
".venv\Scripts\python.exe" scripts\windows_setup.py install
if errorlevel 1 (
    echo Setup failed. See the prerequisite or installation error above.
    pause
    exit /b 1
)

echo.
echo Installed local environment:
".venv\Scripts\python.exe" --version
echo Pip and all locked runtime dependencies are available.
echo.
echo Setup complete.
pause
