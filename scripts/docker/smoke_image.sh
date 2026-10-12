#!/usr/bin/env bash
# Check startup and graceful shutdown with the deployment's read-only root.
set -euo pipefail

image="${1:?Usage: smoke_image.sh IMAGE}"
container=""
cleanup() {
    if [[ -n "$container" ]]; then
        timeout 15 docker logs "$container" || true
        timeout 15 docker rm --force "$container" >/dev/null || true
    fi
}
trap cleanup EXIT

container="$(timeout 30 docker run --detach --read-only --network none \
    --tmpfs /tmp:rw,nosuid,nodev,size=64m \
    --tmpfs /data:rw,nosuid,nodev,size=64m,uid=10001,gid=10001 \
    --tmpfs /worlds:rw,nosuid,nodev,size=16m,uid=10001,gid=10001 \
    --env MCBE_STARTUP_NETWORK_CHECK=false "$image")"

ready=false
for _ in {1..30}; do
    if timeout 5 docker exec "$container" python -c \
        'import urllib.request; response = urllib.request.urlopen("http://127.0.0.1:8080/healthz", timeout=2); assert response.status == 200' \
        >/dev/null 2>&1; then
        ready=true
        break
    fi
    [[ "$(timeout 5 docker inspect --format '{{.State.Running}}' "$container")" == true ]] || break
    sleep 1
done
[[ "$ready" == true ]] || { echo "Container did not become ready." >&2; exit 1; }

timeout 5 docker exec "$container" python -c 'from pathlib import Path; assert not Path("/app/.gunicorn").exists()'
timeout 5 docker exec "$container" python -c 'import importlib.util; assert all(importlib.util.find_spec(name) is None for name in ("leveldb", "amulet_nbt", "numpy", "Cython"))'
timeout 5 docker exec "$container" python -c '
from pathlib import Path
from mcbe_editor.distribution import distribution_snapshot
root = Path("/app")
blocked_dirs = {"__pycache__", ".git", ".github", ".tmp", ".venv", "venv", "node_modules", "docs", "tests", "fixtures", "private"}
blocked_suffixes = {".pyc", ".pyo", ".log", ".jsonl", ".tmp", ".bak", ".orig", ".swp"}
unexpected = [
    path.relative_to(root).as_posix() for path in root.rglob("*")
    if blocked_dirs.intersection(path.relative_to(root).parts)
    or path.suffix in blocked_suffixes
    or (path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"))
]
assert not unexpected, f"Non-runtime artifacts in image: {unexpected[:20]}"
status = distribution_snapshot()
assert status["kind"] == "release", status
'
if timeout 10 docker logs "$container" 2>&1 | grep -F 'Control server error'; then
    echo "Gunicorn control socket failed on the read-only root." >&2
    exit 1
fi
timeout 20 docker stop --time 10 "$container" >/dev/null
[[ "$(timeout 5 docker inspect --format '{{.State.ExitCode}}' "$container")" == 0 ]]
echo "Runtime content, read-only container startup, HTTP health check and graceful shutdown passed."
