"""Builders for public app, item database, and runtime status snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcbe_editor import item_db_verification
from mcbe_editor.runtime_data import BUNDLED_ITEM_DB_RELATIVE_PATH


def public_app_config(
    app_config: Any,
    *,
    bind_host: str | None,
    bind_port: int | None,
    auth_enabled: bool,
    auth_username: str | None,
    setup_status: dict,
    distribution: dict,
    data_root_status: dict,
) -> dict:
    return {
        "mode": app_config.mode,
        "host": bind_host,
        "port": bind_port,
        "worlds_root": app_config.worlds_root,
        "server_name": app_config.server_name,
        "server_host": app_config.server_host,
        "server_port": app_config.server_port,
        "require_server_offline": app_config.require_server_offline,
        "allow_edit_while_online": app_config.allow_edit_while_online,
        "read_only": bool(getattr(app_config, "read_only", False)),
        "allowed_origins": list(app_config.allowed_origins),
        "data_root": app_config.data_root,
        "item_db_path": app_config.item_db_path,
        "update_cache_dir": app_config.update_cache_dir,
        "source_version_path": app_config.source_version_path,
        "source_version_history_path": app_config.source_version_history_path,
        "backup_root": app_config.backup_root,
        "max_backups_per_world": app_config.max_backups_per_world,
        "max_pre_restore_backups_per_world": getattr(app_config, "max_pre_restore_backups_per_world", 5),
        "settings_path": app_config.settings_path,
        "auth_enabled": auth_enabled,
        "auth_username": auth_username if auth_enabled else None,
        "setup": setup_status,
        "collaboration_guard_enabled": app_config.presence_conflict_guard_enabled,
        "distribution": distribution,
        "data_root_status": data_root_status,
    }


def read_json_dict(path_value: str | None) -> dict[str, Any]:
    if not path_value:
        return {}
    path = Path(path_value).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def read_json_list(path_value: str | None) -> list[Any]:
    if not path_value:
        return []
    path = Path(path_value).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return []
    return data if isinstance(data, list) else []


def source_version_history_entries(source_version_history_path: str | None, app_root: Path) -> list[dict]:
    path_value = source_version_history_path or str(app_root / "source_version_history.json")
    return [entry for entry in read_json_list(path_value) if isinstance(entry, dict)]


def paths_equal(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return str(left.absolute()) == str(right.absolute())


def item_db_status_snapshot(app_config: Any, item_data_module: Any, app_root: Path) -> dict:
    bundled_path = app_root / BUNDLED_ITEM_DB_RELATIVE_PATH
    source_path = Path(getattr(item_data_module, "ITEM_DB_SOURCE_PATH", bundled_path)).expanduser()
    configured_path = Path(app_config.item_db_path).expanduser() if app_config.item_db_path else bundled_path
    source_version = read_json_dict(app_config.source_version_path)
    bundled_source_version = read_json_dict(str(app_root / "source_version.json"))
    history = source_version_history_entries(app_config.source_version_history_path, app_root)
    try:
        stat = source_path.stat()
        file_info = {"exists": True, "size": stat.st_size, "mtime": stat.st_mtime}
    except OSError:
        file_info = {"exists": False, "size": 0, "mtime": None}
    verification = item_db_verification.item_db_verification_snapshot(source_version, source_path)

    has_source_metadata = bool(source_version)
    source_release = str(source_version.get("resource_pack_release") or "")
    generated_at = str(source_version.get("generated_at") or "")
    status = "ok" if has_source_metadata else "metadata-missing"
    message = (
        f"Quelle: {source_release} · erzeugt {generated_at}"
        if has_source_metadata
        else "Herkunft unbekannt: Die Datenbank ist vorhanden, aber ohne Quellmetadaten."
    )
    item_components = getattr(item_data_module, "ITEM_COMPONENTS", {})
    item_component_counts = {
        str(component): len(values)
        for component, values in item_components.items()
        if isinstance(values, dict)
    } if isinstance(item_components, dict) else {}
    return {
        "status": status,
        "message": message,
        "path": str(source_path),
        "configured_path": str(configured_path),
        "bundled_path": str(bundled_path),
        "is_bundled": paths_equal(source_path, bundled_path),
        "is_configured_persistent": paths_equal(source_path, configured_path),
        "schema_version": getattr(item_data_module, "ITEM_DB_SCHEMA_VERSION", None),
        "counts": {
            "items": len(getattr(item_data_module, "ITEMS", {})),
            "compat_item_aliases": len(getattr(item_data_module, "COMPAT_ITEM_ALIASES", {})),
            "block_items": len(getattr(item_data_module, "BLOCK_ITEM_IDS", {})),
            "effects": len(getattr(item_data_module, "EFFECTS", {})),
            "enchantments": len(getattr(item_data_module, "ENCHANTMENTS", {})),
            "enchantment_compatibility": len(getattr(item_data_module, "ENCHANTMENT_COMPATIBLE_SLOTS", {})),
            "item_components": sum(item_component_counts.values()),
        },
        "item_component_counts": item_component_counts,
        "enchantment_compatibility": {
            "schema_version": getattr(item_data_module, "ENCHANTMENT_COMPATIBILITY_SCHEMA_VERSION", None),
            "path": getattr(item_data_module, "ENCHANTMENT_COMPATIBILITY_SOURCE_PATH", None),
            "sources": getattr(item_data_module, "ENCHANTMENT_COMPATIBILITY_SOURCES", []),
        },
        "file": file_info,
        "source_version": source_version,
        "source_version_present": has_source_metadata,
        "verification": verification,
        # True while the shipped snapshot is still the active one. ``is_bundled``
        # cannot answer this: the bundled database is copied into the writable data
        # directory on first start, so it stops being "bundled" by path long before
        # any update runs.
        "matches_bundled_snapshot": bool(bundled_source_version) and source_version == bundled_source_version,
        "source_version_path": app_config.source_version_path,
        "source_version_history_path": app_config.source_version_history_path,
        "history_count": len(history),
    }


def runtime_status_snapshot(
    app_config: Any,
    *,
    version: str,
    distribution: dict,
    bind_host: str | None,
    bind_port: int | None,
    auth_enabled: bool,
    auth_username: str | None,
    stable_secret_key_configured: bool,
    uid_label: str,
    setup_status: dict,
    audit_log_status: dict,
    worlds_root_status: dict,
    data_root_status: dict,
    item_db_status: dict,
    write_gate_setup_status: dict,
    outbound_update_hosts: tuple[str, ...],
) -> dict:
    return {
        "version": version,
        "distribution": distribution,
        "mode": app_config.mode,
        "bind": {"host": bind_host, "port": bind_port},
        "auth": {
            "enabled": auth_enabled,
            "username": auth_username if auth_enabled else None,
            "stable_secret_key_configured": stable_secret_key_configured,
            "session_cookie_secure": app_config.session_cookie_secure,
        },
        "csrf": {"mode": "per-session" if auth_enabled else "process-global"},
        "runtime": {
            "uid": uid_label,
            "startup_security_report": app_config.startup_security_report,
            "dependency_audit": {
                "runtime": "disabled",
                "reason": "Build/CI signal; runtime must be able to start offline.",
                "visible_in": [
                    "python scripts/security_check.py --require-pip-audit",
                    "GitHub Actions Dependency audit",
                    "docker build --target dependency-audit .",
                ],
            },
            "outbound_network_check": {
                "enabled_on_startup": app_config.startup_network_check,
                "timeout_seconds": app_config.startup_network_check_timeout,
                "effect": "log-only",
                "hosts": list(outbound_update_hosts),
            },
            "fail_on_insecure_config": app_config.fail_on_insecure_config,
            "trust_proxy_headers": app_config.trust_proxy_headers,
            "collaboration_guard": {"enabled": app_config.presence_conflict_guard_enabled, "mode": "cooperative-presence"},
            "setup": setup_status,
            "audit_log": audit_log_status,
        },
        "paths": {
            "worlds_root": app_config.worlds_root,
            "worlds_root_status": worlds_root_status,
            "data_root": app_config.data_root,
            "backup_root": app_config.backup_root,
            "item_db_path": app_config.item_db_path,
            "setup_path": app_config.setup_path,
            "data_root_status": data_root_status,
        },
        "item_db": item_db_status,
        "write_gate": {
            "require_server_offline": app_config.require_server_offline,
            "allow_edit_while_online": app_config.allow_edit_while_online,
            "read_only": bool(getattr(app_config, "read_only", False)),
            "server": {"host": app_config.server_host, "port": app_config.server_port},
            "setup_status": write_gate_setup_status,
        },
    }
