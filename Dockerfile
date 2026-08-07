FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
COPY requirements/bootstrap.lock requirements/bootstrap.txt requirements/runtime.lock requirements/runtime.txt requirements/docker.lock requirements/docker.txt requirements/build-constraints.txt ./requirements/
ENV PIP_BUILD_CONSTRAINT=/app/requirements/build-constraints.txt
RUN python -m pip install --no-cache-dir --require-hashes -r requirements/bootstrap.lock \
 && python -m pip install --no-cache-dir --require-hashes -r requirements/docker.lock \
 && python -m pip check

FROM builder AS dependency-audit
COPY requirements/dev.lock requirements/dev.txt ./requirements/
COPY scripts/security_check.py scripts/security_check.py
RUN python -m pip install --no-cache-dir --require-hashes -r requirements/dev.lock \
 && python scripts/security_check.py --require-pip-audit

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    MCBE_EDITOR_MODE=docker \
    MCBE_EDITOR_HOST=0.0.0.0 \
    MCBE_EDITOR_PORT=8080 \
    MCBE_OPEN_BROWSER=false \
    MCBE_WORLDS_ROOT=/worlds \
    MCBE_WORLD_SCAN_DEPTH=3 \
    MCBE_DATA_ROOT=/data \
    MCBE_ITEM_DB_PATH=/data/item_db.json \
    MCBE_UPDATE_CACHE_DIR=/data/cache/item_update \
    MCBE_SOURCE_VERSION_PATH=/data/source_version.json \
    MCBE_SOURCE_VERSION_HISTORY_PATH=/data/source_version_history.json \
    MCBE_SETTINGS_PATH=/data/settings.json \
    MCBE_SETUP_PATH=/data/setup.json \
    MCBE_BACKUP_ROOT=/data/backups \
    MCBE_REQUIRE_SERVER_OFFLINE=true \
    MCBE_ALLOW_EDIT_WHILE_ONLINE=false \
    MCBE_STARTUP_NETWORK_CHECK=false \
    MCBE_STARTUP_NETWORK_CHECK_TIMEOUT=1.5 \
    MCBE_FAIL_ON_INSECURE_CONFIG=false \
    MCBE_AUDIT_LOG_ENABLED=true \
    MCBE_AUDIT_LOG_PATH=/data/audit/events.jsonl \
    MCBE_AUDIT_LOG_MAX_BYTES=5000000

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libstdc++6 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv
COPY main.py pyproject.toml ./
COPY mcbe_editor/ ./mcbe_editor/
COPY static/ ./static/
COPY templates/ ./templates/
COPY scripts/__init__.py scripts/update_db.py scripts/update_icons.py ./scripts/
RUN python -m mcbe_editor.distribution --write-manifest /app \
 && python -c "from mcbe_editor.distribution import distribution_snapshot; status = distribution_snapshot(); assert status['kind'] == 'release', status" \
 && mkdir -p /worlds /data/cache/item_update /data/backups /data/audit \
 && chown -R app:app /app /data /worlds \
 && python -m pip check

USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; port = int(os.environ.get('MCBE_EDITOR_PORT', '8080')); urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=2).read()" || exit 1

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${MCBE_EDITOR_PORT:-8080} --workers 1 --threads 4 --log-level info --error-logfile - main:app"]
