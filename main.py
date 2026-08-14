import argparse
import atexit
import contextlib
import importlib
import logging
import math
import os
import secrets
import socket
import sys
import threading
import time
from collections import defaultdict, deque
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, Response, g, has_request_context, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

# This import must run before modules such as services and inventory import
# mcbe_editor.item_data and freeze its module-level catalog globals.
from mcbe_editor.runtime_bootstrap import APP_CONFIG, APP_ROOT, BUNDLED_ITEM_DB_JSON, PERSISTENT_ITEM_DB_PATH
from mcbe_editor import (
    audit_api_routes,
    api_errors,
    app_info_routes,
    auth_page_routes,
    backup_api_routes,
    gui_dialogs,
    http_response_handlers,
    i18n,
    icon_api_routes,
    item_db_api_routes,
    local_file_api_routes,
    mount_api_routes,
    player_api_routes,
    runtime_api_routes,
    scan_api_routes,
    status_snapshots,
    update_script_runner,
)
from mcbe_editor.audit import AuditLogger
from mcbe_editor.config import host_reaches_beyond_loopback
from mcbe_editor.db import register_runtime_leveldb_write_guard
from mcbe_editor.deployment import worlds_root_status, write_gate_setup_status
from mcbe_editor.distribution import data_root_snapshot, distribution_snapshot
from mcbe_editor.presence import WorldPresenceTracker
from mcbe_editor.server_guard import ServerGuardStore
from mcbe_editor.setup_state import FirstRunSetup, is_supported_password_hash
from mcbe_editor.world_locks import locked_operation

SETUP_STATE = FirstRunSetup(APP_CONFIG.setup_path)
if APP_CONFIG.auth_password_hash and not is_supported_password_hash(APP_CONFIG.auth_password_hash):
    raise RuntimeError("MCBE_AUTH_PASSWORD_HASH is not in a supported Werkzeug format (scrypt or PBKDF2).")
ICON_SETTINGS_PATH = str(Path(APP_CONFIG.data_root or "data") / "icon_sources.json")
RUNTIME_BIND_HOST = APP_CONFIG.host
RUNTIME_BIND_PORT = APP_CONFIG.port


class RecentLogHandler(logging.Handler):
    MAX_MESSAGE_CHARS = 4000

    def __init__(self, capacity: int = 200):
        super().__init__()
        self.records = deque(maxlen=capacity)
        self._lock = threading.RLock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if len(message) > self.MAX_MESSAGE_CHARS:
                message = message[: self.MAX_MESSAGE_CHARS] + "… [gekürzt]"
            entry = {
                "ts": self.formatter.formatTime(record, self.formatter.datefmt) if self.formatter else time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "level": record.levelname,
                "logger": record.name,
                "message": message,
            }
            if record.exc_info and self.formatter:
                entry["traceback"] = self.formatter.formatException(record.exc_info)[-4000:]
            with self._lock:
                self.records.append(entry)
        except Exception:
            self.handleError(record)

    def tail(self, limit: int = 80, *, min_level: str = "INFO") -> list[dict[str, str]]:
        level = getattr(logging, str(min_level).upper(), logging.INFO)
        with self._lock:
            rows = [entry for entry in self.records if getattr(logging, entry.get("level", "INFO"), logging.INFO) >= level]
        return rows[-max(1, min(int(limit or 80), 200)) :]


RECENT_LOG_HANDLER = RecentLogHandler()


def _configure_logging() -> logging.Logger:
    level_name = getattr(APP_CONFIG, "log_level", "INFO")
    level = getattr(logging, str(level_name).upper(), logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z")
    logging.basicConfig(
        level=level,
        format=formatter._fmt,
        datefmt=formatter.datefmt,
    )
    RECENT_LOG_HANDLER.setLevel(logging.INFO)
    RECENT_LOG_HANDLER.setFormatter(formatter)
    root_logger = logging.getLogger()
    if not any(handler is RECENT_LOG_HANDLER for handler in root_logger.handlers):
        root_logger.addHandler(RECENT_LOG_HANDLER)
    return logging.getLogger("mcbe_editor")


LOGGER = _configure_logging()


def _remote_addr() -> str:
    # Bei MCBE_TRUST_PROXY_HEADERS=true hat ProxyFix (x_for=1) request.remote_addr
    # bereits aus dem vom vertrauenswürdigen Proxy angehängten X-Forwarded-For-
    # Eintrag gesetzt. Forwarded-Header hier selbst zu parsen würde den linken,
    # Client-kontrollierten Eintrag verwenden und Rate-Limits (inkl. Login-
    # Brute-Force-Schutz) sowie Audit-Logs fälschbar machen.
    return request.remote_addr or "unknown"


def _runtime_uid_label() -> str:
    getuid = getattr(os, "getuid", None)
    if getuid is None:
        return "unknown"
    return str(getuid())


# Hosts used by in-app Item-DB and icon updates. Exclude the maintainer-only
# --check-wiki target from the runtime probe.
OUTBOUND_UPDATE_HOSTS = (
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "learn.microsoft.com",
)


def _probe_https_host(host: str, timeout: float) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, 443), timeout=timeout):
            return True, "ok"
    except OSError as exc:
        return False, f"{exc.__class__.__name__}: {exc}"


def _log_optional_outbound_network_check() -> None:
    if not APP_CONFIG.startup_network_check:
        LOGGER.info("startup outbound_network_check=disabled updates_require_outbound_https=true enable_with=MCBE_STARTUP_NETWORK_CHECK=true effect=log-only")
        return

    timeout = APP_CONFIG.startup_network_check_timeout
    LOGGER.info(
        "startup outbound_network_check=enabled hosts=%s timeout_seconds=%.1f effect=log-only app_start_continues=true",
        ",".join(OUTBOUND_UPDATE_HOSTS),
        timeout,
    )
    for host in OUTBOUND_UPDATE_HOSTS:
        ok, detail = _probe_https_host(host, timeout)
        if ok:
            LOGGER.info("outbound_network_check host=%s port=443 status=ok", host)
        else:
            LOGGER.warning(
                "outbound_network_check host=%s port=443 status=unreachable error=%s impact=item_db_or_icon_update_may_fail app_start_continues=true",
                host,
                detail,
            )


def log_startup_security_report(bind_host: str | None = None, bind_port: int | None = None) -> None:
    if not APP_CONFIG.startup_security_report:
        return
    host = bind_host if bind_host is not None else RUNTIME_BIND_HOST
    port = bind_port if bind_port is not None else RUNTIME_BIND_PORT
    auth_state = "enabled" if auth_enabled() else "disabled"
    csrf_state = "per-session" if auth_enabled() else "process-global"
    LOGGER.info(
        "startup version=%s mode=%s bind=%s:%s auth=%s csrf=%s user_uid=%s worlds_root=%s data_root=%s backups=%s",
        _get_version(),
        APP_CONFIG.mode,
        host,
        port,
        auth_state,
        csrf_state,
        _runtime_uid_label(),
        APP_CONFIG.worlds_root or "auto",
        APP_CONFIG.data_root or "local",
        APP_CONFIG.backup_root or "world-local",
    )
    dist = distribution_snapshot()
    data_status = data_root_snapshot(APP_CONFIG.data_root)
    LOGGER.info(
        "startup distribution kind=%s release_manifest=%s version=%s app_root=%s content_sha256=%s",
        dist.get("kind"),
        dist.get("release_manifest_present"),
        dist.get("project_version") or _get_version(),
        dist.get("app_root"),
        dist.get("content_sha256") or "not-available",
    )
    LOGGER.info(
        "startup data_root path=%s portable=%s writable=%s relative_to_app=%s",
        data_status.get("path") or "not-configured",
        data_status.get("portable"),
        data_status.get("writable"),
        data_status.get("relative_to_app_root") or "outside-app-root",
    )
    LOGGER.info(
        "startup write_gate require_server_offline=%s allow_edit_while_online=%s server=%s:%s allowed_origins=%s",
        APP_CONFIG.require_server_offline,
        APP_CONFIG.allow_edit_while_online,
        APP_CONFIG.server_host or "not-configured",
        APP_CONFIG.server_port,
        ",".join(APP_CONFIG.allowed_origins) or "same-origin-only",
    )
    if APP_CONFIG.allow_edit_while_online:
        LOGGER.warning(
            "MCBE_ALLOW_EDIT_WHILE_ONLINE is deprecated and has no effect anymore: "
            "a server detected as online always blocks write actions; for an unknown "
            "server status an explicit per-write confirmation is required instead."
        )
    mount_status = worlds_root_status(APP_CONFIG)
    log_fn = LOGGER.warning if mount_status.get("status") in {"missing", "symlink", "not-directory", "unreadable", "empty"} else LOGGER.info
    log_fn(
        "startup worlds_root root=%s status=%s bind_mount_required=%s contains_world_hint=%s message=%s",
        mount_status.get("root") or "not-configured",
        mount_status.get("status"),
        mount_status.get("bind_mount_required"),
        mount_status.get("contains_world_hint", "unknown"),
        mount_status.get("message"),
    )
    gate_setup = write_gate_setup_status(APP_CONFIG)
    if gate_setup.get("writes_blocked_without_server_host"):
        LOGGER.warning("startup write_gate status=%s message=%s", gate_setup.get("status"), gate_setup.get("message"))
    else:
        LOGGER.info("startup write_gate status=%s message=%s", gate_setup.get("status"), gate_setup.get("message"))
    LOGGER.info("startup dependency_audit runtime=disabled visibility=ci,security_check,docker_dependency_audit reason=avoid_startup_network_dependency")
    LOGGER.info(
        "startup audit_log enabled=%s path=%s max_bytes=%s",
        APP_CONFIG.audit_log_enabled,
        APP_CONFIG.audit_log_path or "not-configured",
        APP_CONFIG.audit_log_max_bytes,
    )
    LOGGER.info(
        "startup proxy_headers trust=%s collaboration_guard=%s",
        APP_CONFIG.trust_proxy_headers,
        "enabled" if APP_CONFIG.presence_conflict_guard_enabled else "disabled",
    )
    setup_status = public_setup_status()
    LOGGER.info(
        "startup setup required=%s completed=%s mode=%s auth_source=%s storage_available=%s",
        setup_status["required"],
        setup_status["completed"],
        setup_status["mode"],
        setup_status["auth_source"],
        setup_status["storage_available"],
    )
    if setup_status["required"]:
        LOGGER.warning("FIRST RUN SETUP required=true open_url=/setup choose=password-or-open app_start_continues=true")
    elif setup_status["auth_source"] == "first-run-open" and _wide_reachable(host):
        LOGGER.warning("SECURITY NOTICE first_run_open_mode=true risk_acknowledged=true. Anyone who can reach the app can edit player data.")
    _log_optional_outbound_network_check()
    if not auth_enabled() and _wide_reachable(host):
        if setup_status["required"]:
            LOGGER.info("security auth=disabled reason=first_run_setup_pending action=open_/setup")
        elif setup_status["auth_source"] == "first-run-open":
            LOGGER.warning("SECURITY NOTICE auth=disabled reason=user_acknowledged_open_mode scope=lan_or_docker")
        else:
            LOGGER.warning(
                "SECURITY WARNING auth=disabled while binding to %s. "
                "Do not expose this service to LAN/Internet without reverse-proxy auth, "
                "VPN, firewall rules, or first-run open acknowledgement.",
                host,
            )
    if APP_CONFIG.is_docker and not auth_enabled() and not setup_status["required"] and setup_status["auth_source"] != "first-run-open":
        LOGGER.warning("SECURITY WARNING docker_mode_without_auth=true. Enable password setup for LAN deployments.")
    if auth_enabled() and not (APP_CONFIG.secret_key_configured or SETUP_STATE.secret_key()):
        LOGGER.warning("SECURITY NOTICE auth is enabled but no stable session secret is configured; sessions are invalidated on every restart.")
    if auth_enabled() and not APP_CONFIG.session_cookie_secure:
        LOGGER.info("security session_cookie_secure=false. This is normal for plain HTTP/LAN; set MCBE_SESSION_COOKIE_SECURE=true behind HTTPS.")
    if APP_CONFIG.is_docker and _runtime_uid_label() == "0":
        LOGGER.warning("SECURITY WARNING container appears to run as root. Prefer the bundled non-root image/user.")


from mcbe_editor import item_data as item_data_module  # noqa: E402 - persistent item_db path is prepared before import


def _item_db_runtime_path() -> Path:
    configured = PERSISTENT_ITEM_DB_PATH or APP_CONFIG.item_db_path or getattr(item_data_module, "ITEM_DB_SOURCE_PATH", BUNDLED_ITEM_DB_JSON)
    return Path(configured).expanduser().resolve()


def _item_db_file_signature() -> tuple[int, int, int, int, int] | None:
    try:
        stat_info = _item_db_runtime_path().stat()
    except OSError:
        return None
    return (
        stat_info.st_dev,
        stat_info.st_ino,
        stat_info.st_size,
        stat_info.st_mtime_ns,
        stat_info.st_ctime_ns,
    )


def _item_db_operation_root() -> str:
    return str(_item_db_runtime_path().parent)


ICON_INDEX = {
    "success": True,
    "enabled": True,
    "icons": {},
    "display_icons": {},
    "_by_token": {},
    "count": 0,
    "display_count": 0,
    "roots": [],
    "warnings": [],
}
from mcbe_editor.backup import recover_interrupted_restores  # noqa: E402
from mcbe_editor.players import player_export_dir_for_world  # noqa: E402
from mcbe_editor.server_status import check_server_status, unknown_status_confirmation_from_payload, write_gate  # noqa: E402
from mcbe_editor.services import BedrockEditorService  # noqa: E402
from mcbe_editor.world import (  # noqa: E402
    get_configured_scan_roots,
    ensure_valid_world_path,
    get_minecraft_saves_dir,
)

app = Flask(__name__)


@app.context_processor
def _inject_i18n() -> dict:
    locale = i18n.resolve_locale(
        request.cookies.get(i18n.LOCALE_COOKIE_NAME),
        request.headers.get("Accept-Language"),
    )
    return {
        "app_locale": locale,
        "i18n_catalog": i18n.catalog_for(locale),
        "t": lambda text, **params: i18n.translate(text, locale, params),
    }


if APP_CONFIG.trust_proxy_headers:
    # Trust exactly one directly attached reverse proxy.  Keep disabled unless
    # the service is not reachable directly by arbitrary clients.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = APP_CONFIG.session_cookie_secure
app.secret_key = SETUP_STATE.secret_key() or APP_CONFIG.secret_key
editor_service = BedrockEditorService(item_data_module.ITEMS, item_data_module.ENCHANTMENTS)
_ITEM_DB_RUNTIME_SIGNATURE = _item_db_file_signature()

CSRF_TOKEN = secrets.token_urlsafe(32)
_SERVER_ONLINE_EPOCH_LOCK = threading.RLock()
_SERVER_ONLINE_EPOCH = 0
_SERVER_GUARD_STATE = ServerGuardStore(Path(APP_CONFIG.data_root or "data") / "server_guard_state.json")


def server_online_epoch() -> int:
    with _SERVER_ONLINE_EPOCH_LOCK:
        return _SERVER_ONLINE_EPOCH


def server_guard_snapshot() -> dict[str, object]:
    with _SERVER_ONLINE_EPOCH_LOCK:
        return {
            "server_guard_epoch": _SERVER_ONLINE_EPOCH,
            "server_guard_token": _SERVER_GUARD_STATE.current(),
        }


def server_guard_token() -> str:
    return str(server_guard_snapshot()["server_guard_token"])


def note_server_status(status: dict) -> dict[str, object]:
    global _SERVER_ONLINE_EPOCH
    with _SERVER_ONLINE_EPOCH_LOCK:
        online = status.get("status") == "online"
        observation = _SERVER_GUARD_STATE.observe(online=online)
        if online:
            _SERVER_ONLINE_EPOCH += 1
        return {
            "server_guard_epoch": _SERVER_ONLINE_EPOCH,
            "server_guard_token": observation.token,
            "_server_guard_previous_token": observation.previous_token,
        }


def with_server_guard_epoch(gate: dict) -> dict:
    return {**gate, **note_server_status(gate.get("server_status") or {})}


ALLOWED_ORIGINS = set(APP_CONFIG.allowed_origins)
AUDIT_LOG = AuditLogger(
    APP_CONFIG.audit_log_path,
    enabled=APP_CONFIG.audit_log_enabled,
    max_bytes=APP_CONFIG.audit_log_max_bytes,
)

_PERSISTENT_AUTH_AVAILABLE = bool(SETUP_STATE.password_hash())
_ENV_AUTH_AVAILABLE = bool(APP_CONFIG.auth_password_hash or APP_CONFIG.auth_password)
_WIDE_BIND = APP_CONFIG.is_docker or host_reaches_beyond_loopback(RUNTIME_BIND_HOST)


def _setup_storage_can_complete_auth(config=APP_CONFIG, setup_state=SETUP_STATE) -> bool:
    """Return whether the persistent setup page can resolve this auth state."""

    if not setup_state.storage_available:
        return False
    if config.auth_required and not setup_state.password_hash():
        return True
    return not setup_state.completed()


_SETUP_CAN_COMPLETE = _setup_storage_can_complete_auth()


def _wide_bind_has_unresolved_unwritable_setup(
    *,
    wide_bind: bool = _WIDE_BIND,
    env_auth_available: bool = _ENV_AUTH_AVAILABLE,
    persistent_auth_available: bool = _PERSISTENT_AUTH_AVAILABLE,
    setup_state=SETUP_STATE,
) -> bool:
    return bool(
        wide_bind and not env_auth_available and not persistent_auth_available and not setup_state.open_acknowledged() and not setup_state.storage_available
    )


if _wide_bind_has_unresolved_unwritable_setup():
    raise RuntimeError(
        "The service is reachable in LAN/Docker mode, but first-run setup is not complete "
        "and the persistent setup path is not writable. Check owner and write permissions of the data volume."
    )
if APP_CONFIG.auth_required and not (_ENV_AUTH_AVAILABLE or _PERSISTENT_AUTH_AVAILABLE or SETUP_STATE.storage_available):
    raise RuntimeError(
        "MCBE_AUTH_REQUIRED is enabled, but neither MCBE_AUTH_PASSWORD_HASH nor MCBE_AUTH_PASSWORD is set and no writable persistent setup path is available."
    )
if APP_CONFIG.fail_on_insecure_config and _WIDE_BIND and not (_ENV_AUTH_AVAILABLE or _PERSISTENT_AUTH_AVAILABLE) and not _SETUP_CAN_COMPLETE:
    raise RuntimeError(
        "Insecure configuration blocked: MCBE_FAIL_ON_INSECURE_CONFIG=true, "
        "but auth is disabled and the service does not bind to loopback only. Enable auth or bind to 127.0.0.1."
    )


def _heartbeat_now() -> float:
    """Return a monotonic timestamp for elapsed heartbeat intervals."""
    return time.monotonic()


LAST_HEARTBEAT = _heartbeat_now()
HEARTBEAT_TIMEOUT = 15.0
_SAVING_COUNTER = 0
_SAVING_LOCK = threading.Lock()
_SERVICE_MUTATION_LOCK = threading.RLock()
_ITEM_DB_UPDATE_LOCK = threading.Lock()
_GUI_PICKER_LOCK = threading.Lock()
_SERVER = None
WORLD_PRESENCE = WorldPresenceTracker(ttl_seconds=45.0)
_BACKGROUND_TASKS_STARTED = False


def start_background_tasks() -> None:
    global _BACKGROUND_TASKS_STARTED
    if _BACKGROUND_TASKS_STARTED:
        return
    if not APP_CONFIG.read_only:
        try:
            recovery_roots = [root["path"] for root in get_configured_scan_roots(include_disabled=False) if root.get("path")]
            recovery_results = recover_interrupted_restores(
                recovery_roots,
                max_depth=APP_CONFIG.world_scan_depth,
                max_dirs=APP_CONFIG.world_scan_max_dirs,
                recovery_gate_check=lambda: write_gate(APP_CONFIG),
            )
        except Exception:
            recovery_results = []
            LOGGER.exception("startup restore_recovery status=scan-failed")
        for recovery in recovery_results:
            if recovery.get("status") == "original-restored":
                LOGGER.warning(
                    "startup restore_recovery status=original-restored world=%s",
                    recovery.get("world_path"),
                )
            elif recovery.get("status") == "committed-cleaned":
                LOGGER.info(
                    "startup restore_recovery status=committed-cleaned world=%s",
                    recovery.get("world_path"),
                )
            elif recovery.get("status") == "not-started-cleaned":
                LOGGER.info(
                    "startup restore_recovery status=not-started-cleaned world=%s",
                    recovery.get("world_path"),
                )
            elif recovery.get("status") == "manual-recovery-required":
                LOGGER.error(
                    "startup restore_recovery status=manual-recovery-required journal=%s error=%s",
                    recovery.get("journal_path"),
                    recovery.get("error"),
                )
            elif recovery.get("status") == "deferred-write-gate":
                LOGGER.warning(
                    "startup restore_recovery status=deferred-write-gate journal=%s reason=%s",
                    recovery.get("journal_path"),
                    recovery.get("reason"),
                )
    WORLD_PRESENCE.start_cleanup_thread()
    atexit.register(WORLD_PRESENCE.stop_cleanup_thread)
    _BACKGROUND_TASKS_STARTED = True


def _request_id() -> str:
    value = getattr(g, "request_id", None)
    if not value:
        value = secrets.token_hex(8)
        g.request_id = value
    return value


def _env_auth_credentials_configured() -> bool:
    return bool(APP_CONFIG.auth_password_hash or APP_CONFIG.auth_password)


def effective_auth_username() -> str:
    if _env_auth_credentials_configured():
        return APP_CONFIG.auth_username
    return SETUP_STATE.username(APP_CONFIG.auth_username)


def _current_username() -> str | None:
    if not auth_enabled():
        return None
    return effective_auth_username() if session.get("authenticated") is True else None


def audit_event(action: str, outcome: str = "success", **kwargs) -> None:
    try:
        AUDIT_LOG.record(
            action,
            outcome=outcome,
            remote=_remote_addr(),
            username=_current_username(),
            request_id=_request_id(),
            **kwargs,
        )
    except RuntimeError:
        raise
    except Exception:
        LOGGER.exception("audit_log write_failed action=%s outcome=%s", action, outcome)


@app.before_request
def assign_request_id():
    _request_id()
    return None


@app.after_request
def add_request_id_header(response):
    response.headers.setdefault("X-Request-ID", _request_id())
    return response


# Rate limiter
_RATE_LIMIT_WINDOW = 60.0
_RATE_LIMITS: dict = defaultdict(list)
_RATE_LOCK = threading.RLock()

# Limits: (max_requests, window_seconds) per endpoint group
_RATE_CONFIG: dict[str, tuple[int, float]] = {
    "mutate": (30, 60.0),  # 30 requests / 60s for mutating operations
    "read": (120, 60.0),  # 120 requests / 60s for reads
    "presence": (300, 60.0),  # lightweight browser-session presence pings
    "scan": (10, 60.0),  # 10 requests / 60s for expensive scans
    "auth": (8, 60.0),  # login attempts
    # Der Item-Browser lädt pro Item ein eigenes Icon (~2000 Items); Icons sind
    # billige, gecachte Reads und dürfen das normale Read-Limit nicht belegen.
    "icons": (1800, 60.0),
}


def _rate_limit_now() -> float:
    """Return a monotonic timestamp for rate-limit windows."""

    return time.monotonic()


def _clean_rate_limits():
    """Remove expired entries from the rate limit dict."""
    now = _rate_limit_now()
    with _RATE_LOCK:
        expired = []
        for key, timestamps in list(_RATE_LIMITS.items()):
            group = key[1] if isinstance(key, tuple) and len(key) > 1 else ""
            _max_requests, window = _RATE_CONFIG.get(group, (30, _RATE_LIMIT_WINDOW))
            if not timestamps or now - timestamps[-1] > window * 2:
                expired.append(key)
        for k in expired:
            del _RATE_LIMITS[k]


def rate_limit(group: str = "mutate"):
    """Decorator: limit requests per IP per endpoint group."""

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            max_req, window = _RATE_CONFIG.get(group, (30, 60.0))
            key = (_remote_addr(), group)
            now = _rate_limit_now()
            cutoff = now - window

            with _RATE_LOCK:
                timestamps = _RATE_LIMITS[key]
                _RATE_LIMITS[key] = [t for t in timestamps if t > cutoff]
                count = len(_RATE_LIMITS[key])
                if count >= max_req:
                    wait = max(1, math.ceil(window - (now - _RATE_LIMITS[key][0])))
                    LOGGER.warning("rate_limit exceeded group=%s remote=%s wait_seconds=%s", group, _remote_addr(), wait)
                    return api_error(
                        "Zu viele Anfragen. Bitte {wait}s warten.",
                        429,
                        code="rate_limited",
                        params={"wait": wait},
                    )
                _RATE_LIMITS[key].append(now)

            # Clean up periodically (roughly every 100 requests)
            if len(_RATE_LIMITS) > 100:
                _clean_rate_limits()

            return f(*args, **kwargs)

        wrapper._rate_limit_group = group
        return wrapper

    return decorator


def block_when_read_only(category: str = "app_write"):
    """Decorator: reject state-changing routes in MCBE_READ_ONLY deployments."""

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if APP_CONFIG.read_only:
                LOGGER.warning("read_only blocked endpoint=%s category=%s remote=%s", request.path, category, _remote_addr())
                audit_event(
                    "readonly.blocked",
                    "blocked",
                    details={
                        "category": category,
                        "endpoint": request.endpoint,
                        "method": request.method,
                        "path": request.path,
                    },
                )
                return api_error(
                    "Diese Instanz läuft im Read-Only-Modus (MCBE_READ_ONLY). Änderungen sind deaktiviert.",
                    403,
                    code="read_only",
                    extra={"read_only": True, "blocked_operation": "read_only", "category": category},
                )
            return f(*args, **kwargs)

        wrapper._readonly_block_category = category
        return wrapper

    return decorator


def auth_enabled() -> bool:
    return APP_CONFIG.auth_required or _env_auth_credentials_configured() or bool(SETUP_STATE.password_hash())


def _is_authenticated() -> bool:
    return not auth_enabled() or session.get("authenticated") is True


def _is_api_request() -> bool:
    return request.path.startswith("/api/")


def get_csrf_token() -> str:
    if not auth_enabled():
        return CSRF_TOKEN
    token = session.get("csrf_token")
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _valid_login(username: str, password: str) -> bool:
    if username != effective_auth_username():
        return False
    if APP_CONFIG.auth_password_hash:
        try:
            return check_password_hash(APP_CONFIG.auth_password_hash, password)
        except (TypeError, ValueError):
            LOGGER.error("auth invalid_password_hash source=environment")
            return False
    if APP_CONFIG.auth_password:
        return secrets.compare_digest(APP_CONFIG.auth_password, password)
    setup_hash = SETUP_STATE.password_hash()
    if setup_hash:
        try:
            return check_password_hash(setup_hash, password)
        except (TypeError, ValueError):
            LOGGER.error("auth invalid_password_hash source=first-run-setup")
            return False
    return False


def _auth_required_response():
    if _is_api_request():
        return api_error("Authentifizierung erforderlich.", 401, code="authentication_required")
    return redirect(url_for("login", next=request.full_path if request.query_string else request.path))


def _safe_redirect_target(target: str | None) -> str:
    fallback = url_for("index")
    if not isinstance(target, str):
        return fallback
    target = target.strip()
    if not target or "\\" in target or not target.startswith("/") or target.startswith("//"):
        return fallback
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return fallback
    return target


def _wide_reachable(bind_host: str | None = None) -> bool:
    host = RUNTIME_BIND_HOST if bind_host is None else bind_host
    return APP_CONFIG.is_docker or host_reaches_beyond_loopback(host)


def first_run_setup_required() -> bool:
    if _env_auth_credentials_configured():
        return False
    if not SETUP_STATE.storage_available:
        return False
    # Requiring authentication after open-mode setup reopens /setup until a
    # password is stored.
    if APP_CONFIG.auth_required and not SETUP_STATE.password_hash():
        return True
    if SETUP_STATE.completed():
        return False
    return _wide_reachable()


def _setup_auth_source() -> str:
    if _env_auth_credentials_configured():
        return "environment"
    if SETUP_STATE.password_hash():
        return "first-run-password"
    if SETUP_STATE.open_acknowledged():
        return "first-run-open"
    return "none"


def public_setup_status() -> dict:
    summary = SETUP_STATE.summary()
    return {
        "required": first_run_setup_required(),
        "completed": summary.completed,
        "mode": summary.mode,
        "auth_source": _setup_auth_source(),
        "storage_available": summary.enabled,
        "risk_acknowledged": SETUP_STATE.open_acknowledged(),
    }


def _setup_csrf_token() -> str:
    token = session.get("setup_csrf_token")
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        session["setup_csrf_token"] = token
    return token


def _check_setup_post_token() -> str | None:
    origin = request.headers.get("Origin", "").rstrip("/")
    same_origin = f"{request.scheme}://{request.host}".rstrip("/")
    if origin and origin != same_origin and origin not in ALLOWED_ORIGINS:
        LOGGER.warning("setup origin_rejected remote=%s origin=%s expected=%s", _remote_addr(), origin, same_origin)
        return i18n.t("Ungültiger Origin-Header.")
    token = request.form.get("_setup_token", "")
    expected = session.get("setup_csrf_token", "")
    if not token or not isinstance(expected, str) or not secrets.compare_digest(token, expected):
        LOGGER.warning("setup token_rejected remote=%s", _remote_addr())
        return i18n.t("Ungültiges Setup-Token. Bitte Seite neu laden.")
    return None


def _check_login_post_token() -> str | None:
    origin = request.headers.get("Origin", "").rstrip("/")
    same_origin = f"{request.scheme}://{request.host}".rstrip("/")
    if origin and origin != same_origin and origin not in ALLOWED_ORIGINS:
        LOGGER.warning("login origin_rejected remote=%s origin=%s expected=%s", _remote_addr(), origin, same_origin)
        return i18n.t("Ungültiger Origin-Header.")
    token = request.form.get("_csrf_token", "")
    expected = session.get("csrf_token", "")
    if not token or not isinstance(expected, str) or not secrets.compare_digest(token, expected):
        LOGGER.warning("login token_rejected remote=%s", _remote_addr())
        return i18n.t("Ungültiges Login-Token. Bitte Seite neu laden.")
    return None


@app.before_request
def require_first_run_setup():
    if not first_run_setup_required():
        return None
    if request.endpoint in {"healthz", "setup", "static"}:
        return None
    if _is_api_request():
        return api_error(
            "Ersteinrichtung erforderlich.",
            428,
            code="setup_required",
            extra={"setup_required": True, "setup_url": url_for("setup")},
        )
    return redirect(url_for("setup", next=request.full_path if request.query_string else request.path))


@app.before_request
def require_authentication():
    if not auth_enabled():
        return None
    if request.endpoint in {"healthz", "login", "setup", "static"}:
        return None
    if _is_authenticated():
        return None
    return _auth_required_response()


def _check_origin_and_token():
    origin = request.headers.get("Origin", "").rstrip("/")
    same_origin = f"{request.scheme}://{request.host}".rstrip("/")
    if origin and origin not in ALLOWED_ORIGINS and origin != same_origin:
        LOGGER.warning("csrf origin_rejected remote=%s origin=%s expected=%s", _remote_addr(), origin, same_origin)
        return api_error("Ungültiger Origin-Header.", 403, code="invalid_origin")
    token = request.headers.get("X-CSRF-Token", "") or request.form.get("_csrf_token", "")
    expected = get_csrf_token()
    if not token or not secrets.compare_digest(token, expected):
        LOGGER.warning("csrf token_rejected remote=%s path=%s", _remote_addr(), request.path)
        return api_error("Ungültiges CSRF-Token.", 403, code="invalid_csrf_token")
    return None


def require_csrf(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        resp = _check_origin_and_token()
        if resp:
            return resp
        return f(*args, **kwargs)

    return wrapper


def save_in_progress(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        global _SAVING_COUNTER
        with _SAVING_LOCK:
            _SAVING_COUNTER += 1
        try:
            return f(*args, **kwargs)
        finally:
            with _SAVING_LOCK:
                _SAVING_COUNTER -= 1

    return wrapper


def service_mutation_guard(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        # Serializes operations that mutate worlds or replace the global service
        # instance. Per-world locks live in mcbe_editor.world_locks and therefore
        # survive service-module reloads; this outer guard keeps service replacement
        # from racing with mutations that use the global editor_service instance.
        with _SERVICE_MUTATION_LOCK:
            return f(*args, **kwargs)

    return wrapper


def item_db_update_guard(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        # The updater reads and later rewrites the complete item database and
        # version history.  Keep the update process and subsequent module reload
        # in one dedicated critical section so parallel partial updates cannot
        # overwrite each other's newer categories.
        with _ITEM_DB_UPDATE_LOCK, locked_operation("item-db-update", root=_item_db_operation_root()):
            return f(*args, **kwargs)

    return wrapper


# Only a few endpoints mutate state; we protect those specifically.
# Read-only POST endpoints still use CSRF because they can expose local world metadata.


def check_heartbeat():
    global LAST_HEARTBEAT
    while True:
        time.sleep(2)
        if _heartbeat_now() - LAST_HEARTBEAT > HEARTBEAT_TIMEOUT:
            with _SAVING_LOCK:
                if _SAVING_COUNTER > 0:
                    LAST_HEARTBEAT = _heartbeat_now()
                    continue
            LOGGER.info("heartbeat timeout reached; shutting down local development server")
            if _SERVER:
                _SERVER.shutdown()
            break


def _exception_text(exc: Exception) -> str:
    detail = str(exc).strip()
    return detail or exc.__class__.__name__


def _world_load_hints(exc: Exception) -> list[str]:
    text = _exception_text(exc).lower()
    hints: list[str] = []
    if "minecraftworlds" in text or "sammelordner" in text or ("db" in text and "ordner" in text):
        hints.append("Du hast vermutlich einen Sammelordner gewählt. Wähle eine konkrete Welt, also den Ordner, der direkt den Unterordner 'db' enthält.")
    if "lock" in text or "locked" in text or "in use" in text or "leveldb" in text or exc.__class__.__name__.lower().endswith("leveldberror"):
        hints.extend(
            [
                "Schließe Minecraft/den Bedrock Dedicated Server vollständig; geöffnete Welten können die LevelDB sperren.",
                "Prüfe im Task-Manager, ob Minecraft oder bedrock_server.exe noch läuft, und versuche es danach erneut.",
            ]
        )
    if "amulet" in text or "module" in text or "import" in text:
        hints.append("Prüfe die lokale Installation mit setup.bat erneut. Die benötigten Python-Pakete müssen in .\\.venv vorhanden sein.")
    if "permission" in text or "zugriff" in text or "access" in text or "denied" in text:
        hints.append("Prüfe Dateirechte: Der Editor-Prozess muss den Weltordner und den db-Ordner lesen und zum Speichern schreiben können.")
    if "onedrive" in text or "network" in text or "nas" in text:
        hints.append("Falls die Welt auf OneDrive/NAS liegt: testweise lokal kopieren und die Kopie laden.")
    if not hints:
        hints.extend(
            [
                "Prüfe, ob der Pfad auf den direkten Minecraft-Bedrock-Weltordner zeigt.",
                "Schließe Minecraft bzw. den Server und versuche es erneut.",
                "Nutze 'Diagnose kopieren', falls die Ursache weiter unklar bleibt.",
            ]
        )
    # Keep output compact and deterministic.
    result = []
    for hint in hints:
        if hint not in result:
            result.append(hint)
    return result[:6]


def api_error(message, status=400, *, details=None, hints=None, code=None, params=None, extra=None):
    # Übersetzungs-Trichter: Statische deutsche Meldungen aus tieferen Schichten
    # werden hier per Katalog-Exact-Match übersetzt; parametrisierte Texte sind
    # an ihrer Quelle bereits via t() übersetzt und laufen unverändert durch.
    payload = api_errors.error_payload(
        message,
        code=code or api_errors.error_code_for_status(status),
        params=params,
        details=details,
        hints=hints,
        request_id=_request_id() if int(status) >= 500 else None,
    )
    if extra:
        payload.update(extra)
    return jsonify(payload), status


def log_api_exception(context: str, exc: Exception) -> None:
    LOGGER.exception(
        "%s failed request_id=%s remote=%s error=%s",
        context,
        _request_id(),
        _remote_addr(),
        exc,
    )


def _server_online_from_gate(gate: dict) -> bool:
    return (gate.get("server_status") or {}).get("status") == "online"


def _public_server_guard_gate(gate: dict) -> dict:
    return {key: value for key, value in gate.items() if not str(key).startswith("_server_guard_")}


def _localized_public_write_gate(gate: dict) -> dict:
    payload_gate = _public_server_guard_gate(gate)
    status = payload_gate.get("server_status")
    localized_gate = {
        **payload_gate,
        "reason": i18n.t(payload_gate.get("reason") or ""),
    }
    if isinstance(status, dict):
        localized_gate["server_status"] = i18n.localize_message_record(status)
    return localized_gate


class FinalWriteGateBlockedError(ValueError):
    def __init__(self, action_label: str, gate: dict):
        payload_gate = {
            **_localized_public_write_gate(gate),
            "allowed": False,
            "blocked_operation": "final_write_gate",
        }
        reason = payload_gate.get("reason") or i18n.t("Schreibaktion aus Sicherheitsgründen blockiert.")
        payload_gate["reason"] = reason
        self.action_label = action_label
        self.write_gate = payload_gate
        super().__init__(i18n.t("{label} abgelehnt: {reason}", label=i18n.t(action_label), reason=reason))


def write_block_response(gate: dict):
    LOGGER.warning("write_gate blocked reason=%s server_online=%s", gate.get("reason"), _server_online_from_gate(gate))
    reason_key = gate["reason"]
    payload_gate = _localized_public_write_gate(gate)
    return api_error(reason_key, 409, code="write_gate_blocked", extra={"write_gate": payload_gate})


def db_access_block_response(gate: dict):
    status = (gate.get("server_status") or {}).get("status")
    if status == "online":
        reason = "Server läuft noch. Bitte Server stoppen, bevor die Welt gelesen oder bearbeitet wird."
    elif status == "unknown":
        reason = "Serverstatus unbekannt. Weltzugriff aus Sicherheitsgründen blockiert."
    else:
        reason = gate.get("reason") or "Weltzugriff blockiert."
    reason_key = reason
    payload_gate = {
        **_localized_public_write_gate({**gate, "reason": reason_key}),
        "blocked_operation": "leveldb_access",
    }
    reason = payload_gate["reason"]
    LOGGER.warning("leveldb_access blocked reason=%s server_online=%s", reason, _server_online_from_gate(gate))
    return api_error(
        reason_key,
        409,
        code="leveldb_access_blocked",
        extra={"write_gate": payload_gate, "leveldb_access_gate": payload_gate},
    )


def _request_unknown_status_confirmed() -> bool:
    """Read the explicit unknown-server confirmation from the current request.

    Die Gate-Helfer laufen teils tief im Service-Stack (finaler LevelDB-Guard),
    wo kein Request-Payload durchgereicht wird. Deshalb liest die Web-Schicht
    das Flag hier zentral und übergibt es explizit an write_gate().
    """

    try:
        from flask import has_request_context
    except Exception:
        return False
    if not has_request_context():
        return False
    try:
        data = request.get_json(silent=True) if request.is_json else {}
    except Exception:
        data = {}
    return unknown_status_confirmation_from_payload(data)


def _request_write_gate() -> dict:
    return write_gate(APP_CONFIG, unknown_status_confirmed=_request_unknown_status_confirmed())


def require_world_write_allowed():
    gate = with_server_guard_epoch(_request_write_gate())
    if not gate["allowed"]:
        return write_block_response(gate)
    return None


def require_final_world_write_allowed(action_label: str):
    gate = with_server_guard_epoch(_request_write_gate())
    expected_guard_token = str(getattr(g, "expected_server_guard_token", "") or "") if has_request_context() else ""
    current_guard_token = str(gate.get("server_guard_token") or "")
    if gate["allowed"] and (not expected_guard_token or secrets.compare_digest(expected_guard_token, current_guard_token)):
        return
    if gate["allowed"]:
        gate = {
            **gate,
            "allowed": False,
            "reason": "Speichern abgelehnt: Der Bedrock-Serverzustand hat sich seit dem Laden dieses Spielers geändert. Bitte Spieler neu laden.",
            "blocked_operation": "server_guard",
        }
    LOGGER.warning(
        "final_write_gate blocked operation=%s reason=%s server_online=%s",
        action_label,
        gate.get("reason"),
        _server_online_from_gate(gate),
    )
    raise FinalWriteGateBlockedError(action_label, gate)


# Explizit registrieren, damit der finale LevelDB-Write-Guard auch greift,
# wenn die App nicht als Modul "main"/"__main__" läuft (z. B. WSGI-Wrapper).
register_runtime_leveldb_write_guard(require_final_world_write_allowed)


def world_db_access_gate() -> dict:
    """Return the exact read-gate observation for the current request.

    Player loads need the gate itself, not only a possible blocking response:
    the returned server epoch must describe the same ping that authorized the
    LevelDB read.  Keeping this as a value-returning helper avoids a second ping
    and removes timing races between the read check and the player snapshot.
    """

    return with_server_guard_epoch(_request_write_gate())


def require_world_db_access_allowed():
    gate = world_db_access_gate()
    # Read endpoints stay available in MCBE_READ_ONLY viewer mode; only the
    # normal server-online rules apply to LevelDB read access.
    if not gate.get("read_allowed", gate["allowed"]):
        return db_access_block_response(gate)
    return None


def require_server_guard_current(data: dict):
    # allow_edit_while_online darf den Epoch-Guard nicht mehr aushebeln: Das
    # write_gate ignoriert die veraltete Option bereits vollständig.
    if not APP_CONFIG.require_server_offline:
        return None
    current_guard = server_guard_snapshot()
    current_epoch = int(current_guard["server_guard_epoch"])
    current_token = str(current_guard["server_guard_token"])
    try:
        client_epoch = json_int(data, "server_guard_epoch", None)
        client_token = json_string(data, "server_guard_token")
    except ValueError as exc:
        return api_error(exc, 400)
    if client_token and secrets.compare_digest(client_token, current_token):
        if has_request_context():
            g.expected_server_guard_token = client_token
        return None
    if not client_token:
        reason_key = "Speichern abgelehnt: Der Serverstatus des geladenen Spielerstands fehlt. Bitte Spieler neu laden."
    else:
        reason_key = "Speichern abgelehnt: Der Bedrock-Serverzustand hat sich seit dem Laden dieses Spielers geändert. Bitte Spieler neu laden."
    gate = with_server_guard_epoch(_request_write_gate())
    payload_gate = {
        **_localized_public_write_gate({**gate, "reason": reason_key}),
        "allowed": False,
        "blocked_operation": "server_guard",
        "server_guard_epoch": int(gate.get("server_guard_epoch") or current_epoch),
        "server_guard_token": str(gate.get("server_guard_token") or current_token),
    }
    LOGGER.warning(
        "server_guard blocked client_epoch=%s current_epoch=%s client_token=%s remote=%s",
        client_epoch,
        current_epoch,
        "present" if client_token else "missing",
        _remote_addr(),
    )
    return api_error(
        reason_key,
        409,
        code="server_guard_stale",
        extra={"write_gate": payload_gate, "server_guard": payload_gate},
    )


def presence_conflict_response(data: dict, *, world_path: str, player_key: str = "", same_player_only: bool = False):
    if not APP_CONFIG.presence_conflict_guard_enabled:
        return None
    if json_bool(data, "confirm_presence_conflict", False):
        return None
    session_id = data.get("session_id")
    summary = WORLD_PRESENCE.conflict_summary(
        session_id if isinstance(session_id, str) else None,
        world_path,
        player_key=player_key,
        same_player_only=same_player_only,
    )
    if not summary.get("conflict"):
        return None
    if same_player_only:
        reason_key = "Eine andere Browser-Sitzung hat ungespeicherte Änderungen an diesem Spieler. Bitte abstimmen oder bewusst erneut speichern."
    else:
        reason_key = (
            "Eine andere Browser-Sitzung hat ungespeicherte Änderungen in dieser Welt. "
            "Bitte vor Migration, Restore oder Import abstimmen oder bewusst erneut ausführen."
        )
    LOGGER.warning(
        "presence_conflict blocked path=%s player=%s dirty_relevant_sessions=%s same_player_only=%s remote=%s",
        request.path,
        "set" if player_key else "unset",
        summary.get("dirty_relevant_sessions"),
        same_player_only,
        _remote_addr(),
    )
    return api_error(reason_key, 409, code="presence_conflict", extra={"presence_conflict": summary})


def public_app_config():
    enabled = auth_enabled()
    return status_snapshots.public_app_config(
        APP_CONFIG,
        bind_host=RUNTIME_BIND_HOST,
        bind_port=RUNTIME_BIND_PORT,
        auth_enabled=enabled,
        auth_username=effective_auth_username() if enabled else None,
        setup_status=public_setup_status(),
        distribution=distribution_snapshot(),
        data_root_status=data_root_snapshot(APP_CONFIG.data_root),
    )


def source_version_history_entries() -> list[dict]:
    return status_snapshots.source_version_history_entries(APP_CONFIG.source_version_history_path, APP_ROOT)


def item_db_status_snapshot() -> dict:
    return status_snapshots.item_db_status_snapshot(APP_CONFIG, item_data_module, APP_ROOT)


def runtime_status_snapshot() -> dict:
    enabled = auth_enabled()
    return status_snapshots.runtime_status_snapshot(
        APP_CONFIG,
        version=_get_version(),
        distribution=distribution_snapshot(),
        bind_host=RUNTIME_BIND_HOST,
        bind_port=RUNTIME_BIND_PORT,
        auth_enabled=enabled,
        auth_username=effective_auth_username() if enabled else None,
        stable_secret_key_configured=bool(APP_CONFIG.secret_key_configured or SETUP_STATE.secret_key()),
        uid_label=_runtime_uid_label(),
        setup_status=public_setup_status(),
        audit_log_status=AUDIT_LOG.status(),
        worlds_root_status=worlds_root_status(APP_CONFIG),
        data_root_status=data_root_snapshot(APP_CONFIG.data_root),
        item_db_status=item_db_status_snapshot(),
        write_gate_setup_status=write_gate_setup_status(APP_CONFIG),
        outbound_update_hosts=OUTBOUND_UPDATE_HOSTS,
    )


class InvalidJsonBodyError(ValueError):
    """Raised when an API request contains a non-object or malformed JSON body."""


def request_json_object() -> dict:
    """Return an object body while distinguishing empty from malformed JSON."""
    raw_body = request.get_data(cache=True)
    if not raw_body.strip():
        return {}
    if not request.is_json:
        raise InvalidJsonBodyError("Der Anfragekörper muss als JSON gesendet werden.")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise InvalidJsonBodyError("Der Anfragekörper muss ein gültiges JSON-Objekt sein.")
    return data


def json_string(data: dict, key: str, default: str = "") -> str:
    value = data.get(key, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"Feld '{key}' muss ein Textwert sein.")
    return value.strip()


def json_bool(data: dict, key: str, default: bool = False) -> bool:
    value = data.get(key, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "ja", "on"}:
            return True
        if normalized in {"0", "false", "no", "nein", "off"}:
            return False
    raise ValueError(f"Feld '{key}' muss ein boolescher Wert sein.")


def json_int(data: dict, key: str, default: int | None = None) -> int | None:
    value = data.get(key, default)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Feld '{key}' muss eine ganze Zahl sein.")
    return value


def run_update_db(dry_run=False, force=False, only=None, use_cache=False, expected_review_token=None):
    return update_script_runner.run_update_db(
        APP_ROOT,
        APP_CONFIG,
        dry_run=dry_run,
        force=force,
        only=only,
        use_cache=use_cache,
        expected_review_token=expected_review_token,
    )


def run_update_icons(force=False, use_cache=False):
    return update_script_runner.run_update_icons(
        APP_ROOT,
        APP_CONFIG,
        force=force,
        use_cache=use_cache,
    )


def _looks_like_network_failure(output: str) -> bool:
    return update_script_runner.looks_like_network_failure(output)


def reload_item_db_after_update() -> dict:
    with _SERVICE_MUTATION_LOCK:
        # Reload JSON item data and dependent modules so the running app picks up changes.
        import mcbe_editor.item_data as fresh_item_data_module
        import mcbe_editor.inventory as inventory_module
        import mcbe_editor.services as services_module

        fresh_item_data_module = importlib.reload(fresh_item_data_module)
        inventory_module._reload_inventory_core_data()
        importlib.reload(inventory_module)
        services_module = importlib.reload(services_module)

        global BedrockEditorService, _ITEM_DB_RUNTIME_SIGNATURE, editor_service, item_data_module
        item_data_module = fresh_item_data_module
        BedrockEditorService = services_module.BedrockEditorService
        editor_service = BedrockEditorService(item_data_module.ITEMS, item_data_module.ENCHANTMENTS)
        _ITEM_DB_RUNTIME_SIGNATURE = _item_db_file_signature()
        return {
            "reloaded": True,
            "item_db_path": APP_CONFIG.item_db_path or getattr(item_data_module, "ITEM_DB_SOURCE_PATH", "bundled"),
            "item_db": item_db_status_snapshot(),
        }


@app.before_request
def reload_item_db_after_external_worker_update():
    """Lazily refresh worker-local modules after another worker committed an update."""

    current_signature = _item_db_file_signature()
    if current_signature == _ITEM_DB_RUNTIME_SIGNATURE:
        return None
    with _ITEM_DB_UPDATE_LOCK, locked_operation("item-db-update", root=_item_db_operation_root()):
        if _item_db_file_signature() != _ITEM_DB_RUNTIME_SIGNATURE:
            reload_item_db_after_update()
    return None


def item_db_route_deps() -> item_db_api_routes.ItemDbRouteDeps:
    return item_db_api_routes.ItemDbRouteDeps(
        item_db_path=APP_CONFIG.item_db_path,
        source_version_path=APP_CONFIG.source_version_path,
        source_version_history_path=APP_CONFIG.source_version_history_path,
        update_cache_dir=APP_CONFIG.update_cache_dir,
        jsonify=jsonify,
        api_error=api_error,
        log_api_exception=log_api_exception,
        json_bool=json_bool,
        run_update_db=run_update_db,
        looks_like_network_failure=_looks_like_network_failure,
        item_db_status_snapshot=item_db_status_snapshot,
        source_version_history_entries=source_version_history_entries,
        reload_item_db_after_update=reload_item_db_after_update,
        audit_event=audit_event,
        logger=LOGGER,
    )


@app.route("/api/update_db", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("app_write")
@item_db_update_guard
def update_db():
    return item_db_api_routes.update_db(request_json_object(), item_db_route_deps())


def _run_gui_script(script, timeout=60):
    return gui_dialogs.run_gui_script(script, timeout=timeout)


def select_folder_via_gui(initial_dir: str | None = None):
    return gui_dialogs.select_folder(initial_dir=initial_dir)


def select_player_export_via_gui(initial_dir: str | None = None):
    return gui_dialogs.select_player_export(initial_dir=initial_dir)


def select_icon_pack_via_gui():
    return gui_dialogs.select_icon_pack()


def select_icon_folder_via_gui():
    return gui_dialogs.select_icon_folder()


def local_file_route_deps() -> local_file_api_routes.LocalFileRouteDeps:
    return local_file_api_routes.LocalFileRouteDeps(
        app_config=APP_CONFIG,
        service=editor_service,
        jsonify=jsonify,
        api_error=api_error,
        log_api_exception=log_api_exception,
        json_string=json_string,
        audit_event=audit_event,
        ensure_valid_world_path=ensure_valid_world_path,
        get_configured_scan_roots=get_configured_scan_roots,
        get_minecraft_saves_dir=get_minecraft_saves_dir,
        player_export_dir_for_world=player_export_dir_for_world,
        gui_picker_lock=_GUI_PICKER_LOCK,
        select_folder=select_folder_via_gui,
        select_player_export=select_player_export_via_gui,
    )


def scan_route_deps() -> scan_api_routes.ScanRouteDeps:
    return scan_api_routes.ScanRouteDeps(
        settings_path=APP_CONFIG.settings_path,
        data_root=APP_CONFIG.data_root,
        jsonify=jsonify,
        api_error=api_error,
        log_api_exception=log_api_exception,
        json_string=json_string,
        json_bool=json_bool,
        audit_event=audit_event,
    )


def set_app_secret_key(secret_key: str) -> None:
    app.secret_key = secret_key


def auth_page_deps() -> auth_page_routes.AuthPageDeps:
    return auth_page_routes.AuthPageDeps(
        app_config=APP_CONFIG,
        setup_state=SETUP_STATE,
        session=session,
        logger=LOGGER,
        render_template=render_template,
        redirect=redirect,
        url_for=url_for,
        first_run_setup_required=first_run_setup_required,
        auth_enabled=auth_enabled,
        check_setup_post_token=_check_setup_post_token,
        check_login_post_token=_check_login_post_token,
        setup_csrf_token=_setup_csrf_token,
        get_csrf_token=get_csrf_token,
        valid_login=_valid_login,
        safe_redirect_target=_safe_redirect_target,
        effective_auth_username=effective_auth_username,
        set_app_secret_key=set_app_secret_key,
        remote_addr=_remote_addr,
        audit_event=audit_event,
        runtime_bind_host=RUNTIME_BIND_HOST,
        runtime_bind_port=RUNTIME_BIND_PORT,
    )


def app_info_route_deps() -> app_info_routes.AppInfoRouteDeps:
    return app_info_routes.AppInfoRouteDeps(
        jsonify=jsonify,
        render_template=render_template,
        get_csrf_token=get_csrf_token,
        public_app_config=public_app_config,
        runtime_status_snapshot=runtime_status_snapshot,
        source_version_history_entries=source_version_history_entries,
    )


@app.route("/api/scan_worlds", methods=["GET"])
@rate_limit("scan")
def scan_worlds():
    return scan_api_routes.scan_worlds(scan_route_deps())


@app.route("/api/scan_paths", methods=["GET"])
def get_scan_paths():
    return scan_api_routes.get_scan_paths(scan_route_deps())


@app.route("/api/scan_paths/add", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("app_write")
def add_scan_path_route():
    return scan_api_routes.add_scan_path_route(request_json_object(), scan_route_deps())


@app.route("/api/scan_paths/remove", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("app_write")
def remove_scan_path_route():
    return scan_api_routes.remove_scan_path_route(request_json_object(), scan_route_deps())


@app.route("/api/scan_paths/set_enabled", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("app_write")
def set_scan_path_enabled_route():
    return scan_api_routes.set_scan_path_enabled_route(request_json_object(), scan_route_deps())


@app.route("/healthz", methods=["GET"])
def healthz():
    return app_info_routes.healthz(app_info_route_deps())


@app.route("/setup", methods=["GET", "POST"])
@rate_limit("auth")
def setup():
    return auth_page_routes.setup(request.method, request.form, auth_page_deps())


@app.route("/login", methods=["GET", "POST"])
@rate_limit("auth")
def login():
    return auth_page_routes.login(request.method, request.args, request.form, auth_page_deps())


@app.route("/logout", methods=["POST"])
@require_csrf
def logout():
    return auth_page_routes.logout(auth_page_deps())


@app.route("/")
def index():
    return app_info_routes.index(app_info_route_deps())


@app.route("/api/config", methods=["GET"])
def app_config_route():
    return app_info_routes.app_config(app_info_route_deps())


@app.route("/api/runtime_status", methods=["GET"])
@rate_limit("read")
def runtime_status_route():
    return app_info_routes.runtime_status(app_info_route_deps())


@app.route("/api/item-db/status", methods=["GET"])
@rate_limit("read")
def item_db_status_route():
    return item_db_api_routes.item_db_status(item_db_route_deps())


@app.route("/api/item-db/versions", methods=["GET"])
@rate_limit("read")
def item_db_versions_route():
    return item_db_api_routes.item_db_versions(item_db_route_deps())


def audit_route_deps() -> audit_api_routes.AuditRouteDeps:
    return audit_api_routes.AuditRouteDeps(
        audit_log=AUDIT_LOG,
        jsonify=jsonify,
        response=Response,
        api_error=api_error,
        auth_enabled=auth_enabled,
        is_authenticated=_is_authenticated,
        auth_required_response=_auth_required_response,
        wide_reachable=_wide_reachable,
    )


@app.route("/api/audit/events", methods=["GET"])
@rate_limit("read")
def audit_events_route():
    return audit_api_routes.audit_events(request.args, audit_route_deps())


@app.route("/api/audit/export", methods=["GET"])
@rate_limit("read")
def audit_export_route():
    return audit_api_routes.audit_export(request.args, audit_route_deps())


def get_icon_index() -> dict:
    return ICON_INDEX


def set_icon_index(index: dict) -> None:
    global ICON_INDEX
    ICON_INDEX = index


def known_item_ids():
    return item_data_module.ITEMS.keys()


def icon_route_deps() -> icon_api_routes.IconRouteDeps:
    return icon_api_routes.IconRouteDeps(
        settings_path=ICON_SETTINGS_PATH,
        data_root=APP_CONFIG.data_root,
        is_docker=APP_CONFIG.is_docker,
        read_only=APP_CONFIG.read_only,
        get_icon_index=get_icon_index,
        set_icon_index=set_icon_index,
        known_item_ids=known_item_ids,
        jsonify=jsonify,
        response=Response,
        api_error=api_error,
        log_api_exception=log_api_exception,
        json_string=json_string,
        json_bool=json_bool,
        run_update_icons=run_update_icons,
        looks_like_network_failure=_looks_like_network_failure,
        audit_event=audit_event,
        gui_picker_lock=_GUI_PICKER_LOCK,
        select_icon_pack=select_icon_pack_via_gui,
        select_icon_folder=select_icon_folder_via_gui,
    )


@app.route("/api/icons/status", methods=["GET"])
@rate_limit("read")
def icons_status_route():
    return icon_api_routes.icons_status(icon_route_deps())


@app.route("/api/icons/scan", methods=["POST"])
@rate_limit("scan")
@require_csrf
@block_when_read_only("app_write")
def icons_scan_route():
    return icon_api_routes.icons_scan(request_json_object(), icon_route_deps())


@app.route("/api/icons/vanilla/update", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("app_write")
def icons_vanilla_update_route():
    return icon_api_routes.icons_vanilla_update(request_json_object(), icon_route_deps())


@app.route("/api/icons/sources", methods=["GET"])
@rate_limit("read")
def icons_sources_route():
    return icon_api_routes.icons_sources(icon_route_deps())


@app.route("/api/icons/sources/add", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("app_write")
def icons_sources_add_route():
    return icon_api_routes.icons_sources_add(request_json_object(), icon_route_deps())


@app.route("/api/icons/sources/remove", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("app_write")
def icons_sources_remove_route():
    return icon_api_routes.icons_sources_remove(request_json_object(), icon_route_deps())


@app.route("/api/icons/sources/set_enabled", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("app_write")
def icons_sources_set_enabled_route():
    return icon_api_routes.icons_sources_set_enabled(request_json_object(), icon_route_deps())


@app.route("/api/icons/sources/move", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("app_write")
def icons_sources_move_route():
    return icon_api_routes.icons_sources_move(request_json_object(), icon_route_deps())


@app.route("/api/icons/pick_pack", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("local_file")
def icons_pick_pack_route():
    return icon_api_routes.icons_pick_pack(icon_route_deps())


@app.route("/api/icons/pick_folder", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("local_file")
def icons_pick_folder_route():
    return icon_api_routes.icons_pick_folder(icon_route_deps())


@app.route("/api/icons/<token>", methods=["GET"])
@rate_limit("icons")
def icon_file_route(token: str):
    return icon_api_routes.icon_file(token, icon_route_deps())


def note_heartbeat_received() -> None:
    global LAST_HEARTBEAT
    LAST_HEARTBEAT = _heartbeat_now()


def runtime_route_deps() -> runtime_api_routes.RuntimeRouteDeps:
    return runtime_api_routes.RuntimeRouteDeps(
        app_config=APP_CONFIG,
        service=editor_service,
        world_presence=WORLD_PRESENCE,
        recent_log_handler=RECENT_LOG_HANDLER,
        jsonify=jsonify,
        api_error=api_error,
        log_api_exception=log_api_exception,
        json_string=json_string,
        json_bool=json_bool,
        ensure_valid_world_path=ensure_valid_world_path,
        check_server_status=check_server_status,
        note_server_status=note_server_status,
        write_gate=write_gate,
        write_gate_setup_status=write_gate_setup_status,
        worlds_root_status=worlds_root_status,
        data_root_snapshot=data_root_snapshot,
        distribution_snapshot=distribution_snapshot,
        auth_enabled=auth_enabled,
        is_authenticated=_is_authenticated,
        require_world_db_access_allowed=require_world_db_access_allowed,
        note_heartbeat=note_heartbeat_received,
    )


@app.route("/api/server_status", methods=["GET"])
@rate_limit("read")
def server_status_route():
    return runtime_api_routes.server_status(runtime_route_deps())


@app.route("/api/heartbeat", methods=["POST"])
@require_csrf
def heartbeat():
    return runtime_api_routes.heartbeat(runtime_route_deps())


@app.route("/api/world/presence", methods=["POST"])
@rate_limit("presence")
@require_csrf
def world_presence():
    return runtime_api_routes.world_presence(request_json_object(), runtime_route_deps())


@app.route("/api/world/presence/leave", methods=["POST"])
@rate_limit("presence")
@require_csrf
def world_presence_leave():
    return runtime_api_routes.world_presence_leave(request_json_object(), runtime_route_deps())


@app.route("/api/diagnostics/status", methods=["GET"])
@rate_limit("read")
def diagnostics_status():
    return runtime_api_routes.diagnostics_status(runtime_route_deps())


@app.route("/api/logs/recent", methods=["GET"])
@rate_limit("read")
def recent_logs():
    return runtime_api_routes.recent_logs(request.args, runtime_route_deps())


@app.route("/api/world/compatibility", methods=["POST"])
@rate_limit("read")
@require_csrf
def world_compatibility():
    return runtime_api_routes.world_compatibility(request_json_object(), runtime_route_deps())


@app.route("/api/open_backup_folder", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("local_file")
def open_backup_folder_route():
    return local_file_api_routes.open_backup_folder(request_json_object(), local_file_route_deps())


@app.route("/api/open_player_export_folder", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("local_file")
def open_player_export_folder_route():
    return local_file_api_routes.open_player_export_folder(request_json_object(), local_file_route_deps())


@app.route("/api/open_folder", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("local_file")
def open_folder_route():
    return local_file_api_routes.open_folder(request_json_object(), local_file_route_deps())


@app.route("/api/pick_folder", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("local_file")
def pick_folder():
    return local_file_api_routes.pick_folder(local_file_route_deps())


@app.route("/api/pick_player_export", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("local_file")
def pick_player_export():
    return local_file_api_routes.pick_player_export(request_json_object(), local_file_route_deps())


def mount_route_deps() -> mount_api_routes.MountRouteDeps:
    return mount_api_routes.MountRouteDeps(
        service=editor_service,
        jsonify=jsonify,
        api_error=api_error,
        log_api_exception=log_api_exception,
        json_string=json_string,
        require_world_db_access_allowed=require_world_db_access_allowed,
        audit_event=audit_event,
        server_online_epoch=server_online_epoch,
        server_guard_snapshot=server_guard_snapshot,
        world_db_access_gate=world_db_access_gate,
        db_access_block_response=db_access_block_response,
        require_world_write_allowed=require_world_write_allowed,
        require_server_guard_current=require_server_guard_current,
        require_final_world_write_allowed=require_final_world_write_allowed,
        presence_conflict_response=presence_conflict_response,
        final_write_gate_blocked_error=FinalWriteGateBlockedError,
    )


def player_route_deps() -> player_api_routes.PlayerRouteDeps:
    return player_api_routes.PlayerRouteDeps(
        app_config=APP_CONFIG,
        service=editor_service,
        jsonify=jsonify,
        api_error=api_error,
        log_api_exception=log_api_exception,
        exception_text=_exception_text,
        world_load_hints=_world_load_hints,
        json_string=json_string,
        json_bool=json_bool,
        ensure_valid_world_path=ensure_valid_world_path,
        player_export_dir_for_world=player_export_dir_for_world,
        require_world_db_access_allowed=require_world_db_access_allowed,
        world_db_access_gate=world_db_access_gate,
        db_access_block_response=db_access_block_response,
        require_world_write_allowed=require_world_write_allowed,
        require_server_guard_current=require_server_guard_current,
        require_final_world_write_allowed=require_final_world_write_allowed,
        presence_conflict_response=presence_conflict_response,
        audit_event=audit_event,
        server_online_epoch=server_online_epoch,
        final_write_gate_blocked_error=FinalWriteGateBlockedError,
    )


def backup_route_deps() -> backup_api_routes.BackupRouteDeps:
    return backup_api_routes.BackupRouteDeps(
        service=editor_service,
        jsonify=jsonify,
        api_error=api_error,
        log_api_exception=log_api_exception,
        json_string=json_string,
        require_world_write_allowed=require_world_write_allowed,
        require_final_world_write_allowed=require_final_world_write_allowed,
        presence_conflict_response=presence_conflict_response,
        audit_event=audit_event,
        final_write_gate_blocked_error=FinalWriteGateBlockedError,
    )


@app.route("/api/players", methods=["POST"])
@rate_limit("read")
@require_csrf
def list_players():
    return player_api_routes.list_players(request_json_object(), player_route_deps())


@app.route("/api/player/load", methods=["POST"])
@rate_limit("read")
@require_csrf
def load_player():
    return player_api_routes.load_player(request_json_object(), player_route_deps())


@app.route("/api/player/state_transfer_preview", methods=["POST"])
@rate_limit("read")
@require_csrf
def player_state_transfer_preview():
    return player_api_routes.preview_player_state_transfer(request_json_object(), player_route_deps())


@app.route("/api/player/state_transfer", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("world_write")
@save_in_progress
@service_mutation_guard
def player_state_transfer():
    return player_api_routes.transfer_player_state(request_json_object(), player_route_deps())


@app.route("/api/mount/preview", methods=["POST"])
@rate_limit("read")
@require_csrf
def mount_preview():
    return mount_api_routes.preview_mount(request_json_object(), mount_route_deps())


@app.route("/api/mount/create", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("world_write")
@save_in_progress
@service_mutation_guard
def mount_create():
    return mount_api_routes.create_mount(request_json_object(), mount_route_deps())


@app.route("/api/player/save", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("world_write")
@save_in_progress
@service_mutation_guard
def save_player():
    return player_api_routes.save_player(request_json_object(), player_route_deps())


@app.route("/api/workspace/save", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("world_write")
@save_in_progress
@service_mutation_guard
def save_workspace():
    return mount_api_routes.save_workspace(request_json_object(), mount_route_deps(), player_route_deps())


@app.route("/api/player/export", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("app_write")
def export_player():
    return player_api_routes.export_player(request_json_object(), player_route_deps())


@app.route("/api/player/import_preview", methods=["POST"])
@rate_limit("read")
@require_csrf
def import_player_preview():
    return player_api_routes.import_player_preview(request_json_object(), player_route_deps())


@app.route("/api/player/import", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("world_write")
@save_in_progress
@service_mutation_guard
def import_player():
    return player_api_routes.import_player(request_json_object(), player_route_deps())


@app.route("/api/backups", methods=["POST"])
@rate_limit("read")
@require_csrf
def list_backups():
    return backup_api_routes.list_backups(request_json_object(), backup_route_deps())


@app.route("/api/backup/create", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("app_write")
@save_in_progress
def create_backup_route():
    return backup_api_routes.create_backup(request_json_object(), backup_route_deps())


@app.route("/api/backup/delete", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("app_write")
def delete_backup_route():
    return backup_api_routes.delete_backup(request_json_object(), backup_route_deps())


@app.route("/api/backup/restore_preview", methods=["POST"])
@rate_limit("read")
@require_csrf
def restore_backup_preview():
    return backup_api_routes.restore_backup_preview(request_json_object(), backup_route_deps())


@app.route("/api/restore_backup", methods=["POST"])
@rate_limit("mutate")
@require_csrf
@block_when_read_only("world_write")
@save_in_progress
@service_mutation_guard
def restore_backup():
    return backup_api_routes.restore_backup(request_json_object(), backup_route_deps())


# ─── Source Version History Route ────────────────────────────────────────────


def _get_version() -> str:
    try:
        import tomllib

        ver = tomllib.loads((Path(__file__).resolve().parent / "pyproject.toml").read_text())
        return ver["project"]["version"]
    except (tomllib.TOMLDecodeError, KeyError, FileNotFoundError):
        return "unknown"


@app.after_request
def add_security_headers(response):
    response = http_response_handlers.add_security_headers(response)
    if response.mimetype in {"application/json", "text/html"}:
        response = http_response_handlers.add_locale_vary_headers(response)
    return response


# Flask error handlers


@app.errorhandler(InvalidJsonBodyError)
def invalid_json_body(error):
    return api_error(str(error), 400)


@app.errorhandler(413)
def request_too_large(_e):
    return http_response_handlers.request_too_large(jsonify)


@app.errorhandler(404)
def not_found(_e):
    return http_response_handlers.not_found(jsonify)


@app.errorhandler(500)
def server_error(_e):
    return http_response_handlers.server_error(jsonify)


@app.route("/versions")
def versions():
    return app_info_routes.versions(app_info_route_deps())


if __name__ != "__main__":
    start_background_tasks()
    log_startup_security_report()


if __name__ == "__main__":
    import webbrowser

    from werkzeug.serving import make_server

    parser = argparse.ArgumentParser(description="MCBE Inventory Editor")
    parser.add_argument("--host", default=APP_CONFIG.host, help=f"Host (default: {APP_CONFIG.host})")
    parser.add_argument("--port", type=int, default=APP_CONFIG.port, help=f"Port (default: {APP_CONFIG.port})")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    parser.add_argument("--debug", action="store_true", help="enable Flask debug mode")
    parser.add_argument("--version", action="version", version=_get_version(), help="show the version")
    args = parser.parse_args()

    HOST = args.host
    PORT = args.port
    RUNTIME_BIND_HOST = HOST
    RUNTIME_BIND_PORT = PORT

    if APP_CONFIG.fail_on_insecure_config and _wide_reachable(HOST) and not (_ENV_AUTH_AVAILABLE or _PERSISTENT_AUTH_AVAILABLE) and not _SETUP_CAN_COMPLETE:
        LOGGER.error("Insecure configuration blocked: auth is disabled and the service does not bind to loopback only.")
        print("  Error: insecure configuration blocked. Enable auth or bind to 127.0.0.1.")
        sys.exit(1)

    # Dynamically add origin for the actual host:port so ALLOWED_ORIGINS stays in sync
    ALLOWED_ORIGINS.add(f"http://{HOST}:{PORT}")
    ALLOWED_ORIGINS.add(f"http://localhost:{PORT}")

    log_startup_security_report(HOST, PORT)
    start_background_tasks()

    try:
        app.debug = bool(args.debug)
        if args.debug:
            LOGGER.warning("debug mode enabled without Werkzeug debugger/reloader because the embedded server uses make_server")
        _SERVER = make_server(
            HOST,
            PORT,
            app,
            threaded=True,
        )
    except OSError as e:
        LOGGER.error("Port %s is already in use: %s", PORT, e.strerror)
        print(f"  Error: port {PORT} is already in use ({e.strerror}).")
        print(f"  Use another port: python main.py --port {PORT + 1}")
        sys.exit(1)

    LOGGER.info("local server ready url=http://%s:%s", HOST, PORT)
    print(f"  MCBE Inventory Editor — http://{HOST}:{PORT}")
    print("  Press Ctrl+C to stop")
    print()
    LAST_HEARTBEAT = _heartbeat_now()

    def open_browser_when_ready():
        import urllib.request

        browser_host = "127.0.0.1" if HOST in {"0.0.0.0", "::"} else HOST
        browser_url = f"http://{browser_host}:{PORT}/"
        ready_url = f"{browser_url}api/config"
        while True:
            try:
                with contextlib.closing(urllib.request.urlopen(ready_url, timeout=2)):
                    pass
                break
            except Exception:
                time.sleep(0.3)
        try:
            if sys.platform.startswith("win"):
                os.startfile(browser_url)
                LOGGER.info("opened browser via Windows shell url=%s", browser_url)
                return
            opened = webbrowser.open(browser_url, new=2)
            if opened:
                LOGGER.info("opened browser url=%s", browser_url)
            else:
                LOGGER.warning("browser auto-open returned false url=%s", browser_url)
        except Exception as exc:
            LOGGER.warning("browser auto-open failed url=%s error=%s", browser_url, exc)

    if APP_CONFIG.open_browser and not args.no_browser:
        threading.Thread(target=open_browser_when_ready, daemon=True).start()
    if APP_CONFIG.is_local and APP_CONFIG.local_heartbeat_shutdown:
        threading.Thread(target=check_heartbeat, daemon=True).start()
    try:
        _SERVER.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("server stopped by keyboard interrupt")
        print("  Server beendet.")
