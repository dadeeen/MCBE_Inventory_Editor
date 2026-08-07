#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/../.."

IMAGE_NAME="mcbe-inventory-editor:local"

echo "MCBE Inventory Editor - Docker-Image unter Linux bauen"
echo
echo "Image-Tag: ${IMAGE_NAME}"
echo "Build-Kontext: aktueller Projektordner"
echo

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker wurde nicht gefunden."
    echo "Bitte Docker Engine oder Docker Desktop für Linux installieren und starten."
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "Docker ist installiert, aber der Docker-Daemon antwortet nicht."
    echo "Bitte Docker starten oder deinen Benutzer zur docker-Gruppe hinzufügen."
    exit 1
fi

if [ ! -f "Dockerfile" ]; then
    echo "Dockerfile wurde im Projektordner nicht gefunden."
    exit 1
fi

echo "Baue Docker-Image..."
echo
docker build -t "${IMAGE_NAME}" .

echo
echo "Docker-Image wurde gebaut:"
docker image ls "${IMAGE_NAME}"
echo
echo "Nächster Schritt:"
echo "- docker-compose.example.yml nach docker-compose.yml kopieren,"
echo "  Weltordner und Serveradresse anpassen und dann starten mit:"
echo "  docker compose up -d"
