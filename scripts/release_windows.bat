@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0.."

set "PAUSE_AT_END=1"
set "REPLACE_EXISTING="

:parse_arguments
if "%~1"=="" goto :arguments_parsed
if /i "%~1"=="--no-pause" (
    set "PAUSE_AT_END="
    shift
    goto :parse_arguments
)
if /i "%~1"=="--replace-existing" (
    set "REPLACE_EXISTING=1"
    shift
    goto :parse_arguments
)
echo Unknown option.
echo Usage: scripts\release_windows.bat [--replace-existing] [--no-pause]
goto :failed

:arguments_parsed

if not exist ".venv\Scripts\python.exe" (
    echo The local Python environment is missing. Please run setup.bat first.
    goto :failed
)
set "PYTHON=.venv\Scripts\python.exe"

for /f "delims=" %%V in ('"%PYTHON%" main.py --version') do set "VERSION=%%V"
if not defined VERSION (
    echo The project version could not be read.
    goto :failed
)

where git >nul 2>nul
if errorlevel 1 (
    echo Git was not found. A release must correspond to a committed code state.
    goto :failed
)
git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
    echo The current directory is not a Git working tree.
    goto :failed
)
set "DIRTY_TREE="
for /f "delims=" %%G in ('git status --porcelain --untracked-files^=normal') do set "DIRTY_TREE=1"
if defined DIRTY_TREE (
    echo The git working tree still contains changes.
    echo Please review and commit the changes, then run this script again.
    goto :failed
)

set "RELEASE=dist\mcbe_inventory_editor_v%VERSION%_runtime.zip"
if exist "%RELEASE%" (
    if not defined REPLACE_EXISTING (
        echo %RELEASE% already exists.
        echo Use --replace-existing only for an unpublished local artifact.
        echo Otherwise bump the version in pyproject.toml first.
        goto :failed
    )
    git show-ref --verify --quiet "refs/tags/v%VERSION%"
    if not errorlevel 1 (
        echo The local version tag v%VERSION% already exists.
        echo A tagged release artifact must not be replaced. Use a new version.
        goto :failed
    )
    echo The existing local archive will be replaced only after full validation.
)

:choose_temporary_release
set "TEMP_RELEASE=dist\.mcbe_inventory_editor_v%VERSION%_runtime.%RANDOM%%RANDOM%.tmp.zip"
if exist "%TEMP_RELEASE%" goto :choose_temporary_release

if exist "RELEASE_MANIFEST.json" del /q "RELEASE_MANIFEST.json"

echo [1/10] Checking lockfiles
"%PYTHON%" scripts\compile_lockfiles.py --check || goto :failed
"%PYTHON%" scripts\check_lockfiles.py || goto :failed

echo [2/10] Checking Python code
"%PYTHON%" -m ruff check . || goto :failed
"%PYTHON%" -m mypy || goto :failed
"%PYTHON%" -m pip check || goto :failed

echo [3/10] Running smoke test
"%PYTHON%" scripts\smoke_check.py || goto :failed

echo [4/10] Running full test suite
"%PYTHON%" scripts\test_full.py -v || goto :failed
"%PYTHON%" scripts\coverage_check.py -q || goto :failed

echo [5/10] Running browser smoke tests
if not exist "node_modules\playwright\cli.js" (
    echo Playwright is missing. Run npm.cmd ci --ignore-scripts once.
    goto :failed
)
"%PYTHON%" scripts\browser_smoke.py || goto :failed

echo [6/10] Running dependency security check
"%PYTHON%" scripts\security_check.py --require-pip-audit || goto :failed

echo [7/10] Pre-checking runtime content
"%PYTHON%" scripts\release_check.py --path . || goto :failed

echo [8/10] Building runtime ZIP %VERSION%
"%PYTHON%" scripts\make_release_zip.py --output "%TEMP_RELEASE%" || goto :failed

echo [9/10] Validating runtime ZIP
"%PYTHON%" scripts\release_check.py --archive "%TEMP_RELEASE%" || goto :failed

echo [10/10] Finalizing runtime ZIP
"%PYTHON%" -c "import os; os.replace(r'%TEMP_RELEASE%', r'%RELEASE%')" || goto :failed
set "TEMP_RELEASE="
echo Clean runtime package created: %RELEASE%
if defined PAUSE_AT_END pause
exit /b 0

:failed
if defined TEMP_RELEASE if exist "%TEMP_RELEASE%" del /q "%TEMP_RELEASE%" >nul 2>nul
echo.
echo Runtime package build aborted. No valid new package was confirmed.
if defined PAUSE_AT_END pause
exit /b 1
