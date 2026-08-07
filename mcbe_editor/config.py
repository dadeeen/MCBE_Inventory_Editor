from __future__ import annotations

import ipaddress
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL_DATA_ROOT = APP_ROOT / "data"

_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "no", "n", "off"}

_LOOPBACK_HOSTNAMES = {"localhost"}


def host_reaches_beyond_loopback(host: str | None) -> bool:
    """Return True when a bind host can be reached from outside this machine."""

    normalized = (host or "").strip().strip("[]").lower()
    if not normalized or normalized in _LOOPBACK_HOSTNAMES:
        return False
    try:
        return not ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return True


def _host_for_origin(host: str) -> str:
    """Format a bind host for an HTTP Origin, including IPv6 brackets."""

    normalized = host.strip().strip("[]")
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return normalized
    if address.version == 6:
        return f"[{normalized}]"
    return normalized


def _env_bool(name: str, default: bool, *, strict: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    if strict:
        allowed = "true/false, 1/0, yes/no, on/off"
        raise RuntimeError(f"Ungültiger Boolean-Wert für {name}: {value!r}. Erlaubt: {allowed}.")
    return default


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_list(name: str) -> list[str]:
    value = os.environ.get(name, "")
    if not value:
        return []
    return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]


def _env_file_value(name: str) -> str | None:
    path = os.environ.get(name, "").strip()
    if not path:
        return None
    try:
        value = Path(path).expanduser().read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"{name} konnte nicht gelesen werden: {path}") from exc
    if not value:
        raise RuntimeError(f"{name} ist leer: {path}")
    return value


def _normalize_mode(value: str | None) -> str:
    mode = (value or "local").strip().lower()
    return "docker" if mode in {"docker", "lan", "container"} else "local"


@dataclass(frozen=True)
class AppConfig:
    mode: str
    host: str
    port: int
    open_browser: bool
    local_heartbeat_shutdown: bool
    worlds_root: str | None
    server_name: str
    server_host: str | None
    server_port: int
    require_server_offline: bool
    allow_edit_while_online: bool
    read_only: bool
    allowed_origins: tuple[str, ...]
    backup_root: str | None
    max_backups_per_world: int | None
    max_pre_restore_backups_per_world: int | None
    data_root: str | None
    item_db_path: str | None
    update_cache_dir: str | None
    source_version_path: str | None
    source_version_history_path: str | None
    settings_path: str | None
    setup_path: str | None
    world_scan_depth: int
    world_scan_max_dirs: int
    auth_required: bool
    auth_username: str
    auth_password_hash: str | None
    auth_password: str | None
    secret_key: str
    session_cookie_secure: bool
    secret_key_configured: bool
    log_level: str
    startup_security_report: bool
    startup_network_check: bool
    startup_network_check_timeout: float
    fail_on_insecure_config: bool
    trust_proxy_headers: bool
    presence_conflict_guard_enabled: bool
    audit_log_enabled: bool
    audit_log_path: str | None
    audit_log_max_bytes: int

    @property
    def is_docker(self) -> bool:
        return self.mode == "docker"

    @property
    def is_local(self) -> bool:
        return self.mode == "local"


def load_config() -> AppConfig:
    mode = _normalize_mode(os.environ.get("MCBE_EDITOR_MODE"))
    default_host = "0.0.0.0" if mode == "docker" else "127.0.0.1"
    default_port = 8080 if mode == "docker" else 5000
    host = os.environ.get("MCBE_EDITOR_HOST", default_host).strip() or default_host
    port = _env_int("MCBE_EDITOR_PORT", default_port)
    open_browser = _env_bool("MCBE_OPEN_BROWSER", mode == "local")
    local_heartbeat_shutdown = _env_bool("MCBE_LOCAL_HEARTBEAT_SHUTDOWN", True, strict=True)

    worlds_root = os.environ.get("MCBE_WORLDS_ROOT")
    if worlds_root:
        worlds_root = str(Path(worlds_root).expanduser())
    elif mode == "docker":
        worlds_root = "/worlds"

    server_host = os.environ.get("MCBE_SERVER_HOST")
    if server_host:
        server_host = server_host.strip() or None

    require_server_offline = _env_bool("MCBE_REQUIRE_SERVER_OFFLINE", mode == "docker")
    allow_edit_while_online = _env_bool("MCBE_ALLOW_EDIT_WHILE_ONLINE", False)
    # Viewer deployments: block every mutating endpoint server-side.
    read_only = _env_bool("MCBE_READ_ONLY", False, strict=True)

    data_root = os.environ.get("MCBE_DATA_ROOT")
    if data_root:
        data_root = str(Path(data_root).expanduser())
    elif mode == "docker":
        data_root = "/data"
    else:
        # Portable local mode: keep app-owned state next to the release/source
        # tree, not in system locations or the user's profile. The release
        # builder and .gitignore exclude this directory.
        data_root = str(DEFAULT_LOCAL_DATA_ROOT)

    item_db_path = os.environ.get("MCBE_ITEM_DB_PATH")
    if item_db_path:
        item_db_path = str(Path(item_db_path).expanduser())
    elif data_root:
        item_db_path = str(Path(data_root) / "item_db.json")

    update_cache_dir = os.environ.get("MCBE_UPDATE_CACHE_DIR")
    if update_cache_dir:
        update_cache_dir = str(Path(update_cache_dir).expanduser())
    elif data_root:
        update_cache_dir = str(Path(data_root) / "cache" / "item_update")

    source_version_path = os.environ.get("MCBE_SOURCE_VERSION_PATH")
    if source_version_path:
        source_version_path = str(Path(source_version_path).expanduser())
    elif data_root:
        source_version_path = str(Path(data_root) / "source_version.json")

    source_version_history_path = os.environ.get("MCBE_SOURCE_VERSION_HISTORY_PATH")
    if source_version_history_path:
        source_version_history_path = str(Path(source_version_history_path).expanduser())
    elif data_root:
        source_version_history_path = str(Path(data_root) / "source_version_history.json")

    settings_path = os.environ.get("MCBE_SETTINGS_PATH")
    if settings_path:
        settings_path = str(Path(settings_path).expanduser())
    elif data_root:
        settings_path = str(Path(data_root) / "settings.json")

    setup_path = os.environ.get("MCBE_SETUP_PATH")
    if setup_path:
        setup_path = str(Path(setup_path).expanduser())
    elif data_root:
        setup_path = str(Path(data_root) / "setup.json")

    # The world browser may be pointed at a parent folder such as a mounted
    # Docker/NAS root or the modern Windows "Minecraft Bedrock" profile tree.
    # Keep the hard upper bound conservative, but default to the widest already
    # supported scan so level selection remains useful without extra env tuning.
    world_scan_depth = max(0, min(_env_int("MCBE_WORLD_SCAN_DEPTH", 4), 4))
    world_scan_max_dirs = max(100, min(_env_int("MCBE_WORLD_SCAN_MAX_DIRS", 2000), 20000))

    backup_root = os.environ.get("MCBE_BACKUP_ROOT")
    if backup_root:
        backup_root = str(Path(backup_root).expanduser())
    elif data_root:
        backup_root = str(Path(data_root) / "backups")

    max_backups_raw = os.environ.get("MCBE_MAX_BACKUPS_PER_WORLD", "").strip()
    max_backups_per_world = 20
    if max_backups_raw:
        try:
            parsed = int(max_backups_raw)
            # Values <= 0 deliberately disable pruning for users who want to
            # manage retention externally.  Invalid values fall back to the
            # safe bounded default instead of silently keeping unlimited ZIPs.
            max_backups_per_world = parsed if parsed > 0 else None
        except ValueError:
            max_backups_per_world = 20

    max_pre_restore_raw = os.environ.get("MCBE_MAX_PRE_RESTORE_BACKUPS_PER_WORLD", "").strip()
    max_pre_restore_backups_per_world = 5
    if max_pre_restore_raw:
        try:
            parsed = int(max_pre_restore_raw)
            max_pre_restore_backups_per_world = parsed if parsed > 0 else None
        except ValueError:
            max_pre_restore_backups_per_world = 5

    auth_password = os.environ.get("MCBE_AUTH_PASSWORD") or _env_file_value("MCBE_AUTH_PASSWORD_FILE")
    auth_password_hash = os.environ.get("MCBE_AUTH_PASSWORD_HASH") or _env_file_value("MCBE_AUTH_PASSWORD_HASH_FILE")
    if auth_password_hash is not None:
        auth_password_hash = auth_password_hash.strip() or None
    auth_required = _env_bool("MCBE_AUTH_REQUIRED", bool(auth_password or auth_password_hash), strict=True)
    auth_username = os.environ.get("MCBE_AUTH_USERNAME", "admin").strip() or "admin"
    secret_key = os.environ.get("MCBE_SECRET_KEY") or _env_file_value("MCBE_SECRET_KEY_FILE")
    secret_key_configured = bool(secret_key)
    if not secret_key:
        # Safe for local/no-auth use. For auth-enabled Docker deployments a stable
        # MCBE_SECRET_KEY should be configured so sessions survive restarts.
        secret_key = secrets.token_urlsafe(32)

    session_cookie_secure = _env_bool("MCBE_SESSION_COOKIE_SECURE", False)
    log_level = os.environ.get("MCBE_LOG_LEVEL", "INFO").strip().upper() or "INFO"
    startup_security_report = _env_bool("MCBE_STARTUP_SECURITY_REPORT", True)
    startup_network_check = _env_bool("MCBE_STARTUP_NETWORK_CHECK", False)
    startup_network_check_timeout = max(0.2, min(_env_float("MCBE_STARTUP_NETWORK_CHECK_TIMEOUT", 1.5), 10.0))
    fail_on_insecure_config = _env_bool("MCBE_FAIL_ON_INSECURE_CONFIG", False, strict=True)
    trust_proxy_headers = _env_bool("MCBE_TRUST_PROXY_HEADERS", False)
    presence_conflict_guard_enabled = _env_bool("MCBE_PRESENCE_CONFLICT_GUARD", True)

    audit_log_path = os.environ.get("MCBE_AUDIT_LOG_PATH")
    if audit_log_path:
        audit_log_path = str(Path(audit_log_path).expanduser())
    elif data_root:
        audit_log_path = str(Path(data_root) / "audit" / "events.jsonl")
    audit_log_enabled = _env_bool("MCBE_AUDIT_LOG_ENABLED", bool(audit_log_path and mode == "docker"))
    audit_log_max_bytes = max(100_000, min(_env_int("MCBE_AUDIT_LOG_MAX_BYTES", 5_000_000), 100_000_000))

    origins = set(_env_list("MCBE_ALLOWED_ORIGINS"))
    origins.add(f"http://127.0.0.1:{port}")
    origins.add(f"http://localhost:{port}")
    if host not in {"0.0.0.0", "::", ""}:
        origins.add(f"http://{_host_for_origin(host)}:{port}")

    return AppConfig(
        mode=mode,
        host=host,
        port=port,
        open_browser=open_browser,
        local_heartbeat_shutdown=local_heartbeat_shutdown,
        worlds_root=worlds_root,
        server_name=os.environ.get("MCBE_SERVER_NAME", "Bedrock Server").strip() or "Bedrock Server",
        server_host=server_host,
        server_port=_env_int("MCBE_SERVER_PORT", 19132),
        require_server_offline=require_server_offline,
        allow_edit_while_online=allow_edit_while_online,
        read_only=read_only,
        allowed_origins=tuple(sorted(origins)),
        backup_root=backup_root,
        max_backups_per_world=max_backups_per_world,
        max_pre_restore_backups_per_world=max_pre_restore_backups_per_world,
        data_root=data_root,
        item_db_path=item_db_path,
        update_cache_dir=update_cache_dir,
        source_version_path=source_version_path,
        source_version_history_path=source_version_history_path,
        settings_path=settings_path,
        setup_path=setup_path,
        world_scan_depth=world_scan_depth,
        world_scan_max_dirs=world_scan_max_dirs,
        auth_required=auth_required,
        auth_username=auth_username,
        auth_password_hash=auth_password_hash,
        auth_password=auth_password,
        secret_key=secret_key,
        session_cookie_secure=session_cookie_secure,
        secret_key_configured=secret_key_configured,
        log_level=log_level,
        startup_security_report=startup_security_report,
        startup_network_check=startup_network_check,
        startup_network_check_timeout=startup_network_check_timeout,
        fail_on_insecure_config=fail_on_insecure_config,
        trust_proxy_headers=trust_proxy_headers,
        presence_conflict_guard_enabled=presence_conflict_guard_enabled,
        audit_log_enabled=audit_log_enabled,
        audit_log_path=audit_log_path,
        audit_log_max_bytes=audit_log_max_bytes,
    )
