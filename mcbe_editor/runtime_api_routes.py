"""Handlers for runtime, world-presence, and diagnostics API routes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .i18n import localize_message_record, t
from .world import world_fingerprint

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeRouteDeps:
    app_config: Any
    service: Any
    world_presence: Any
    recent_log_handler: Any
    jsonify: Callable[..., Any]
    api_error: Callable[..., Any]
    log_api_exception: Callable[[str, Exception], None]
    json_string: Callable[..., str]
    json_bool: Callable[..., bool]
    ensure_valid_world_path: Callable[[str], None]
    check_server_status: Callable[[Any], dict]
    note_server_status: Callable[[dict], dict[str, object] | int]
    write_gate: Callable[..., dict]
    write_gate_setup_status: Callable[[Any], dict]
    worlds_root_status: Callable[[Any], dict]
    data_root_snapshot: Callable[[str | None], dict]
    distribution_snapshot: Callable[[], dict]
    auth_enabled: Callable[[], bool]
    is_authenticated: Callable[[], bool]
    require_world_db_access_allowed: Callable[[], Any]
    note_heartbeat: Callable[[], None]
    world_fingerprint: Callable[[str], str] = world_fingerprint


def _localized_server_status(status: dict | None) -> dict:
    return localize_message_record(status)


def _localized_write_gate(gate: dict | None) -> dict:
    source = gate or {}
    return {
        **source,
        "reason": t(source.get("reason") or ""),
        "server_status": _localized_server_status(source.get("server_status")),
    }


def server_status(deps: RuntimeRouteDeps):
    status = deps.check_server_status(deps.app_config)
    guard_observation = deps.note_server_status(status)
    if isinstance(guard_observation, dict):
        epoch = int(guard_observation.get("server_guard_epoch") or 0)
        guard_token = str(guard_observation.get("server_guard_token") or "")
    else:
        epoch = int(guard_observation or 0)
        guard_token = ""
    status_revision = int(status.get("server_status_revision") or 0)
    observation = {
        "server_guard_epoch": epoch,
        "server_guard_token": guard_token,
        "server_status_revision": status_revision,
    }
    gate = _localized_write_gate({**deps.write_gate(deps.app_config, status), **observation})
    return deps.jsonify(
        {
            "success": True,
            "server_status": gate["server_status"],
            "write_gate": gate,
            **observation,
        }
    )


def heartbeat(deps: RuntimeRouteDeps):
    deps.note_heartbeat()
    return deps.jsonify({"status": "alive"})


def _loaded_player_check(data: dict, world_path: str, deps: RuntimeRouteDeps) -> dict:
    """Notice when the page's loaded player changed outside the editor.

    The page sends the world fingerprint from loading (``fingerprint_baseline``)
    and the one the previous poll returned (``fingerprint_seen``). Once the world
    differs from the baseline and stayed the same since the previous poll, the
    program that changed it is likely done, and the player's stored revision
    is read for the page to compare.
    """

    baseline = data.get("fingerprint_baseline")
    player_key = data.get("player_key")
    if not isinstance(baseline, str) or not baseline or not isinstance(player_key, str) or not player_key:
        return {}
    try:
        fingerprint = deps.world_fingerprint(world_path)
    except OSError:
        return {}
    result: dict = {"world_fingerprint": fingerprint}
    if fingerprint == baseline or fingerprint != data.get("fingerprint_seen"):
        return result
    if deps.require_world_db_access_allowed() is not None:
        return result
    try:
        revision = deps.service.stored_player_revision(world_path, player_key)
    except Exception as exc:
        # A server still writing or a damaged world: the next poll tries again.
        LOGGER.info("Spielerstand konnte nicht geprüft werden: %s", exc)
        return result
    if revision is not None:
        result["player_revision"] = revision
    return result


def world_presence(data: dict, deps: RuntimeRouteDeps):
    try:
        world_path = deps.json_string(data, "world_path")
        deps.ensure_valid_world_path(world_path)
        result = deps.world_presence.touch(
            deps.json_string(data, "session_id"),
            world_path,
            player_key=data.get("player_key", ""),
            player_label=data.get("player_label", ""),
            dirty=deps.json_bool(data, "dirty", False),
        )
        return deps.jsonify({**result, **_loaded_player_check(data, world_path, deps)})
    except ValueError as exc:
        return deps.api_error(exc)
    except Exception as exc:
        deps.log_api_exception("world_presence", exc)
        return deps.api_error(t("Fehler beim Aktualisieren der Welt-Präsenz: {error}", error=t(str(exc))), 500)


def world_presence_leave(data: dict, deps: RuntimeRouteDeps):
    try:
        return deps.jsonify(deps.world_presence.leave(deps.json_string(data, "session_id")))
    except ValueError as exc:
        return deps.api_error(exc)
    except Exception as exc:
        deps.log_api_exception("world_presence_leave", exc)
        return deps.api_error(t("Fehler beim Entfernen der Welt-Präsenz: {error}", error=t(str(exc))), 500)


def diagnostics_status(deps: RuntimeRouteDeps):
    try:
        gate_setup = deps.write_gate_setup_status(deps.app_config)
        mount_status = deps.worlds_root_status(deps.app_config)
        gate = _localized_write_gate(deps.write_gate(deps.app_config))
        return deps.jsonify(
            {
                "success": True,
                "mode": deps.app_config.mode,
                "is_docker": deps.app_config.is_docker,
                "worlds_root": mount_status,
                "write_gate_setup": gate_setup,
                "write_gate": gate,
                "data_root": deps.data_root_snapshot(deps.app_config.data_root),
                "distribution": deps.distribution_snapshot(),
                "config": {
                    "world_scan_depth": deps.app_config.world_scan_depth,
                    "world_scan_max_dirs": deps.app_config.world_scan_max_dirs,
                    "backup_root": deps.app_config.backup_root,
                    "max_backups_per_world": deps.app_config.max_backups_per_world,
                    "max_pre_restore_backups_per_world": deps.app_config.max_pre_restore_backups_per_world,
                    "server_host": deps.app_config.server_host,
                    "server_port": deps.app_config.server_port,
                    "require_server_offline": deps.app_config.require_server_offline,
                    "allow_edit_while_online": deps.app_config.allow_edit_while_online,
                    "read_only": bool(getattr(deps.app_config, "read_only", False)),
                },
            }
        )
    except Exception as exc:
        deps.log_api_exception("diagnostics.status", exc)
        return deps.api_error(t("Diagnose konnte nicht erstellt werden: {error}", error=t(str(exc))), 500)


def recent_logs(args: Any, deps: RuntimeRouteDeps):
    if deps.app_config.is_docker and not deps.auth_enabled():
        return deps.api_error("Logeinsicht ist im Docker/LAN-Modus nur mit aktivierter Auth abrufbar.", 403)
    if deps.auth_enabled() and not deps.is_authenticated():
        return deps.api_error("Nicht angemeldet.", 401)
    try:
        limit = int(args.get("limit", "80"))
    except ValueError:
        limit = 80
    min_level = args.get("level", "INFO")
    return deps.jsonify({"success": True, "logs": deps.recent_log_handler.tail(limit, min_level=min_level)})


def world_compatibility(data: dict, deps: RuntimeRouteDeps):
    try:
        world_path = deps.json_string(data, "world_path")
        player_key = data.get("player_key")
        if player_key is not None:
            player_key = str(player_key).strip() or None
        if player_key:
            blocked = deps.require_world_db_access_allowed()
            if blocked:
                return blocked
        return deps.jsonify(deps.service.compatibility_report(world_path, player_key))
    except ValueError as exc:
        return deps.api_error(exc)
    except Exception as exc:
        deps.log_api_exception("world.compatibility", exc)
        return deps.api_error(t("Kompatibilitätsbericht konnte nicht erstellt werden: {error}", error=t(str(exc))), 500)
