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
        py -3.12 -c "import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] < (3, 13) else 1)" >nul 2>nul
        if not errorlevel 1 (
            set "PYTHON_CMD=py -3.12"
        )
    )

    if not defined PYTHON_CMD (
        where python >nul 2>nul
        if not errorlevel 1 (
            python -c "import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] < (3, 13) else 1)" >nul 2>nul
            if not errorlevel 1 (
                set "PYTHON_CMD=python"
            )
        )
    )

    if not defined PYTHON_CMD (
        echo Python 3.12 was not found.
        echo Please install Python 3.12 from https://www.python.org/downloads/
        echo If multiple Python versions are installed, Python 3.12 may only be available via the Python launcher ^(py -3.12^).
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

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] < (3, 13) else 1)" >nul 2>nul
if errorlevel 1 (
    echo The existing virtual environment does not use a supported Python version.
    echo Please delete the .venv folder and run setup.bat again.
    echo Python 3.12 is supported.
    pause
    exit /b 1
)

if not exist "requirements\runtime.lock" (
    echo The hash-checked lockfile requirements\runtime.lock is missing.
    echo The installation is aborted because an unlocked fallback would not be reproducible.
    pause
    exit /b 1
)

echo Checking the local pip installation...
".venv\Scripts\python.exe" -m pip --version >nul
if errorlevel 1 (
    echo Pip is not available in the virtual environment.
    pause
    exit /b 1
)

echo Installing hash-checked dependencies from requirements\runtime.lock into .\.venv only ...
".venv\Scripts\python.exe" -m pip install --require-hashes -r requirements\runtime.lock
if errorlevel 1 (
    echo Failed to install the dependencies.
    echo Note: Python 3.11, 3.13, and 3.14 are currently not approved for these dependencies; please use Python 3.12.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip check
if errorlevel 1 (
    echo pip check reports errors.
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
