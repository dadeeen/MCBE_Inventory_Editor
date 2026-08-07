@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0\..\.."

title MCBE Inventory Editor - Export Docker image

set "IMAGE_NAME=mcbe-inventory-editor:local"
set "OUTPUT_DIR=dist\docker"
set "OUTPUT_FILE=%OUTPUT_DIR%\mcbe-inventory-editor_local.tar"
set "TEMP_FILE=%OUTPUT_FILE%.tmp"
set "NO_PAUSE=false"
if /I "%~1"=="--no-pause" set "NO_PAUSE=true"

echo MCBE Inventory Editor - export the local Docker image
echo.
echo Image tag: %IMAGE_NAME%
echo Target file: %OUTPUT_FILE%
echo.

where docker >nul 2>nul
if errorlevel 1 (
    echo Docker was not found.
    echo Please install Docker and start the Docker daemon.
    if not "%NO_PAUSE%"=="true" pause
    exit /b 1
)

docker info >nul 2>nul
if errorlevel 1 (
    echo Docker is installed, but the Docker daemon is not responding.
    echo Please start the Docker daemon and wait until Docker is ready.
    if not "%NO_PAUSE%"=="true" pause
    exit /b 1
)

docker buildx version >nul 2>nul
if errorlevel 1 (
    echo Docker Buildx was not found.
    echo Please update Docker Desktop and run this file again.
    if not "%NO_PAUSE%"=="true" pause
    exit /b 1
)

if not exist "Dockerfile" (
    echo Dockerfile was not found in the project folder.
    if not "%NO_PAUSE%"=="true" pause
    exit /b 1
)

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

if exist "%TEMP_FILE%" del /f /q "%TEMP_FILE%"

echo.
echo Building and exporting a fresh image directly as a TAR file...
echo The finished image is not loaded into Docker Desktop.
echo.

docker buildx build --tag "%IMAGE_NAME%" --output "type=docker,dest=%TEMP_FILE%" .
if errorlevel 1 (
    echo.
    echo Docker build or export failed.
    if exist "%TEMP_FILE%" del /f /q "%TEMP_FILE%"
    if not "%NO_PAUSE%"=="true" pause
    exit /b 1
)

move /Y "%TEMP_FILE%" "%OUTPUT_FILE%" >nul
if errorlevel 1 (
    echo.
    echo Could not overwrite the existing export file.
    echo Is the file perhaps still open?
    echo File: %OUTPUT_FILE%
    if not "%NO_PAUSE%"=="true" pause
    exit /b 1
)

echo.
echo Export complete:
echo %OUTPUT_FILE%
echo The finished image only exists in this TAR file; the BuildKit cache stays local for faster follow-up builds.
echo.
echo Next steps on another Docker host:
echo 1. Transfer the TAR file to the target host.
echo 2. Load the image there:
echo    docker load -i mcbe-inventory-editor_local.tar
echo 3. Update the existing Compose or container deployment with the local image.
echo Note: the target host's operating system and CPU architecture must match the image.
if not "%NO_PAUSE%"=="true" pause
exit /b 0
