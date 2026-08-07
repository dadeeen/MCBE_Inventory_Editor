@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0\..\.."

title MCBE Inventory Editor - Build Docker image

set "IMAGE_NAME=mcbe-inventory-editor:local"
set "NO_PAUSE=false"
if /I "%~1"=="--no-pause" set "NO_PAUSE=true"

echo MCBE Inventory Editor - build the Docker image on Windows
echo.
echo Image tag: %IMAGE_NAME%
echo Build context: current project folder
echo.

where docker >nul 2>nul
if errorlevel 1 (
    echo Docker was not found.
    echo Please install Docker, start the Docker daemon, and run this file again.
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

if not exist "Dockerfile" (
    echo Dockerfile was not found in the project folder.
    if not "%NO_PAUSE%"=="true" pause
    exit /b 1
)

echo Building Docker image...
echo.
docker build -t "%IMAGE_NAME%" .
if errorlevel 1 (
    echo.
    echo Docker build failed.
    if not "%NO_PAUSE%"=="true" pause
    exit /b 1
)

echo.
echo Docker image was built:
docker image ls "%IMAGE_NAME%"
echo.
echo Next step:
echo - For LAN/Docker operation, copy docker-compose.example.yml to docker-compose.yml,
echo   adjust the worlds folder and server address, then start with:
echo   docker compose up -d
echo.
if not "%NO_PAUSE%"=="true" pause
exit /b 0
