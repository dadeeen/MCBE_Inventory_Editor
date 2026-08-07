"""Handlers for player-related API routes.

The Flask route registration stays in main.py; this module owns the request
body orchestration so the app entrypoint does not carry every player workflow.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .api_errors import add_exception_cleanup_details, error_payload
from .i18n import localize_message_record, t
from .service_errors import (
    PlayerImportPreviewStaleError,
    PlayerImportRecordRollbackError,
    PlayerImportRolledBackError,
    PlayerStateTransferPreviewStaleError,
    PlayerStateTransferRollbackError,
    PlayerStateTransferRolledBackError,
)


@dataclass(frozen=True)
class PlayerRouteDeps:
    app_config: Any
    service: Any
    jsonify: Callable[..., Any]
    api_error: Callable[..., Any]
    log_api_exception: Callable[[str, Exception], None]
    exception_text: Callable[[Exception], str]
    world_load_hints: Callable[[Exception], list[str]]
    json_string: Callable[..., str]
    json_bool: Callable[..., bool]
    ensure_valid_world_path: Callable[[str], Any]
    player_export_dir_for_world: Callable[[str], str]
    require_world_db_access_allowed: Callable[[], Any]
    world_db_access_gate: Callable[[], dict]
    db_access_block_response: Callable[[dict], Any]
    require_world_write_allowed: Callable[[], Any]
    require_server_guard_current: Callable[[dict], Any]
    require_final_world_write_allowed: Callable[[str], Any]
    presence_conflict_response: Callable[..., Any]
    audit_event: Callable[..., None]
    server_online_epoch: Callable[[], int]
    final_write_gate_blocked_error: type[Exception]


DOCKER_IMPORT_PATH_ERROR = "Spieler-Import ist im Docker-/LAN-Modus nur für .mcbe-player.zip-Dateien im Exportordner der geladenen Welt erlaubt."
PLAYER_LOADED_WHILE_SERVER_ONLINE_REASON = (
    "Nur ansehen: Der Bedrock-Server war online, als dieser Spieler geladen wurde. Stoppe den Server und lade den Spieler neu, um ihn zu bearbeiten."
)
_INTERNAL_GUARD_PREVIOUS_TOKEN = "_server_guard_previous_token"


def _path_is_relative_to(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def _public_guard_gate(gate: dict) -> dict:
    return {key: value for key, value in gate.items() if key != _INTERNAL_GUARD_PREVIOUS_TOKEN}


def _snapshot_guard_token(gate: dict, *, stale: bool) -> str:
    current = str(gate.get("server_guard_token") or "")
    if not stale:
        return current
    return str(gate.get(_INTERNAL_GUARD_PREVIOUS_TOKEN) or "")


def _validated_player_export_zip_path(export_zip: str, world_path: str, deps: PlayerRouteDeps) -> str:
    """Return a validated export ZIP path for preview/import workflows.

    Local mode intentionally keeps the existing user-selected local-file behavior.
    Docker/LAN mode is stricter because a browser can submit arbitrary container
    paths: both the preview and the actual import must be limited to the loaded
    world's player export folder.
    """

    if not getattr(deps.app_config, "is_docker", False):
        return export_zip
    deps.ensure_valid_world_path(world_path)
    allowed_dir = Path(deps.player_export_dir_for_world(world_path)).expanduser().resolve()
    candidate = Path(export_zip).expanduser().resolve()
    if not candidate.name.endswith(".mcbe-player.zip") or not _path_is_relative_to(candidate, allowed_dir):
        raise ValueError(DOCKER_IMPORT_PATH_ERROR)
    return str(candidate)


def list_players(data: dict, deps: PlayerRouteDeps):
    blocked = deps.require_world_db_access_allowed()
    if blocked:
        return blocked
    try:
        return deps.jsonify(deps.service.list_players(deps.json_string(data, "world_path")))
    except ValueError as exc:
        return deps.api_error(exc)
    except Exception as exc:
        deps.log_api_exception("players.list", exc)
        return deps.api_error(
            "Fehler beim Erkennen der Spieler.",
            500,
            details=deps.exception_text(exc),
            hints=deps.world_load_hints(exc),
        )


def load_player(data: dict, deps: PlayerRouteDeps):
    gate = deps.world_db_access_gate()
    if not gate.get("read_allowed", gate.get("allowed", False)):
        return deps.db_access_block_response(gate)
    try:
        result = deps.service.load_player(
            deps.json_string(data, "world_path"),
            deps.json_string(data, "player_key"),
        )
        current_epoch = int(gate.get("server_guard_epoch") or 0)
        current_guard_token = str(gate.get("server_guard_token") or "")
        status = gate.get("server_status") or {}
        current_status_revision = int(gate.get("server_status_revision") or status.get("server_status_revision") or 0)
        gate_config = gate.get("config") or {}
        require_server_offline = gate_config.get(
            "require_server_offline",
            deps.app_config.require_server_offline,
        )
        stale_at_load = (
            require_server_offline is True
            and not bool(getattr(deps.app_config, "read_only", False))
            and gate.get("override_active") is not True
            and status.get("status") == "online"
        )

        # A snapshot loaded while the server is online is stale for future writes.
        # Keep the current epoch separately for status rendering.
        player_epoch = max(0, current_epoch - 1) if stale_at_load else current_epoch
        player_guard_token = _snapshot_guard_token(gate, stale=stale_at_load)
        localized_status = localize_message_record(status)
        localized_gate = {
            **_public_guard_gate(gate),
            "reason": t(gate.get("reason") or ""),
            "server_status": localized_status,
            "server_status_revision": current_status_revision,
        }
        result.update(
            {
                "server_guard_epoch": current_epoch,
                "server_guard_token": current_guard_token,
                "server_status_revision": current_status_revision,
                "player_server_guard_epoch": player_epoch,
                "player_server_guard_token": player_guard_token,
                "server_guard_stale": stale_at_load,
                "server_status": localized_status,
                "write_gate": localized_gate,
            }
        )
        if stale_at_load:
            result["server_guard_stale_reason_key"] = PLAYER_LOADED_WHILE_SERVER_ONLINE_REASON
            result["server_guard_stale_reason"] = t(PLAYER_LOADED_WHILE_SERVER_ONLINE_REASON)
        return deps.jsonify(result)
    except ValueError as exc:
        return deps.api_error(exc)
    except Exception as exc:
        deps.log_api_exception("player.load", exc)
        return deps.api_error(
            "Fehler beim Laden des Spielers.",
            500,
            details=deps.exception_text(exc),
            hints=deps.world_load_hints(exc),
        )


def preview_player_state_transfer(data: dict, deps: PlayerRouteDeps):
    gate = deps.world_db_access_gate()
    if not gate.get("read_allowed", gate.get("allowed", False)):
        return deps.db_access_block_response(gate)
    try:
        world_path = deps.json_string(data, "world_path")
        source_player_key = deps.json_string(data, "source_player_key")
        target_player_key = deps.json_string(data, "target_player_key")
        result = deps.service.preview_player_state_transfer(world_path, source_player_key, target_player_key)
        status = gate.get("server_status") or {}
        stale = status.get("status") == "online" and deps.app_config.require_server_offline is True
        result["server_guard_epoch"] = max(0, int(gate.get("server_guard_epoch") or 0) - 1) if stale else int(gate.get("server_guard_epoch") or 0)
        result["server_guard_token"] = _snapshot_guard_token(gate, stale=stale)
        return deps.jsonify(result)
    except ValueError as exc:
        return deps.api_error(exc)
    except Exception as exc:
        deps.log_api_exception("player.state_transfer_preview", exc)
        return deps.api_error(t("Fehler beim Prüfen der Spielermigration: {error}", error=t(str(exc))), 500)


def transfer_player_state(data: dict, deps: PlayerRouteDeps):
    blocked = deps.require_world_write_allowed()
    if blocked:
        deps.audit_event(
            "player.state_transfer",
            "blocked",
            world_path=data.get("world_path"),
            player_key=data.get("target_player_key"),
            details={"reason": "write_gate"},
        )
        return blocked
    try:
        world_path = deps.json_string(data, "world_path")
        source_player_key = deps.json_string(data, "source_player_key")
        target_player_key = deps.json_string(data, "target_player_key")
        blocked = deps.require_server_guard_current(data)
        if blocked:
            deps.audit_event(
                "player.state_transfer",
                "blocked",
                world_path=world_path,
                player_key=target_player_key,
                details={"reason": "server_guard"},
            )
            return blocked
        conflict = deps.presence_conflict_response(data, world_path=world_path)
        if conflict:
            deps.audit_event(
                "player.state_transfer",
                "blocked",
                world_path=world_path,
                player_key=target_player_key,
                details={"reason": "presence_conflict"},
            )
            return conflict
        blocked = deps.require_world_write_allowed()
        if blocked:
            deps.audit_event(
                "player.state_transfer",
                "blocked",
                world_path=world_path,
                player_key=target_player_key,
                details={"reason": "write_gate_recheck"},
            )
            return blocked
        blocked = deps.require_server_guard_current(data)
        if blocked:
            deps.audit_event(
                "player.state_transfer",
                "blocked",
                world_path=world_path,
                player_key=target_player_key,
                details={"reason": "server_guard_recheck"},
            )
            return blocked
        deps.require_final_world_write_allowed("Spielermigration")
        result = deps.service.transfer_player_state(
            world_path,
            source_player_key,
            target_player_key,
            confirm_transfer=deps.json_bool(data, "confirm_transfer", False),
            transfer_token=data.get("transfer_token"),
            write_gate_check=lambda: deps.require_final_world_write_allowed("Spielermigration"),
        )
        deps.audit_event(
            "player.state_transfer",
            "success",
            world_path=world_path,
            player_key=target_player_key,
            details={
                "source_player_key": source_player_key,
                "backup_file": result.get("backup_file"),
                "direction": result.get("direction"),
                "source_deleted": False,
                "world_changed": True,
            },
        )
        return deps.jsonify(result)
    except PlayerStateTransferRolledBackError as exc:
        deps.log_api_exception("player.state_transfer.rolled_back", exc)
        deps.audit_event(
            "player.state_transfer",
            "failure",
            world_path=data.get("world_path"),
            player_key=data.get("target_player_key"),
            error=str(exc),
            details={"rolled_back": True, "backup_file": exc.backup_file},
        )
        payload = error_payload(
            t(
                "Spielermigration fehlgeschlagen; der vorherige Zielzustand wurde erfolgreich wiederhergestellt: {error}",
                error=t(str(exc.original_error)),
            ),
            code="player_state_transfer_rolled_back",
            details=t("Sicherungsbackup: {backup}", backup=Path(exc.backup_file).name) if exc.backup_file else None,
        )
        payload.update(
            {
                "write_committed": False,
                "rolled_back": True,
                "backup_file": Path(exc.backup_file).name if exc.backup_file else None,
            }
        )
        add_exception_cleanup_details(payload, exc)
        return deps.jsonify(payload), 500
    except PlayerStateTransferRollbackError as exc:
        deps.log_api_exception("player.state_transfer.rollback", exc)
        deps.audit_event(
            "player.state_transfer",
            "failure",
            world_path=data.get("world_path"),
            player_key=data.get("target_player_key"),
            error=str(exc),
        )
        payload = error_payload(
            t(
                "Spielermigration fehlgeschlagen und der vorherige Zielzustand konnte nicht vollständig wiederhergestellt werden: {error}",
                error=t(str(exc.original_error)),
            ),
            code="player_state_transfer_rollback_failed",
            details=exc.rollback_warning,
        )
        payload.update(
            {
                "write_committed": True,
                "rolled_back": False,
                "rollback_warning": exc.rollback_warning,
                "backup_file": Path(exc.backup_file).name if exc.backup_file else None,
            }
        )
        add_exception_cleanup_details(payload, exc)
        return deps.jsonify(payload), 500
    except PlayerStateTransferPreviewStaleError as exc:
        deps.audit_event(
            "player.state_transfer",
            "failure",
            world_path=data.get("world_path"),
            player_key=data.get("target_player_key"),
            error=str(exc),
        )
        payload = error_payload(str(exc), code="player_state_transfer_preview_stale")
        payload["preview_stale"] = True
        add_exception_cleanup_details(payload, exc)
        return deps.jsonify(payload), 409
    except deps.final_write_gate_blocked_error as exc:
        deps.audit_event(
            "player.state_transfer",
            "blocked",
            world_path=data.get("world_path"),
            player_key=data.get("target_player_key"),
            details={"reason": "final_write_gate"},
            error=str(exc),
        )
        payload = error_payload(str(exc), code="final_write_gate_blocked")
        payload["write_gate"] = exc.write_gate
        add_exception_cleanup_details(payload, exc)
        return deps.jsonify(payload), 409
    except ValueError as exc:
        deps.audit_event(
            "player.state_transfer",
            "failure",
            world_path=data.get("world_path"),
            player_key=data.get("target_player_key"),
            error=str(exc),
        )
        cleanup_warning = getattr(exc, "cleanup_warning", None)
        if cleanup_warning:
            payload = add_exception_cleanup_details(error_payload(str(exc), code="player_state_transfer_invalid"), exc)
            return deps.jsonify(payload), 400
        return deps.api_error(exc)
    except Exception as exc:
        deps.log_api_exception("player.state_transfer", exc)
        deps.audit_event(
            "player.state_transfer",
            "failure",
            world_path=data.get("world_path"),
            player_key=data.get("target_player_key"),
            error=str(exc),
        )
        cleanup_warning = getattr(exc, "cleanup_warning", None)
        if cleanup_warning:
            payload = add_exception_cleanup_details(
                error_payload(
                    "Fehler bei der Spielermigration: {error}",
                    code="player_state_transfer_failed",
                    params={"error": t(str(exc))},
                ),
                exc,
            )
            return deps.jsonify(payload), 500
        return deps.api_error(t("Fehler bei der Spielermigration: {error}", error=t(str(exc))), 500)


def save_player(data: dict, deps: PlayerRouteDeps):
    blocked = deps.require_world_write_allowed()
    if blocked:
        return blocked
    try:
        world_path = deps.json_string(data, "world_path")
        player_key = deps.json_string(data, "player_key")
        blocked = deps.require_server_guard_current(data)
        if blocked:
            deps.audit_event("player.save", "blocked", world_path=world_path, player_key=player_key, details={"reason": "server_guard"})
            return blocked
        conflict = deps.presence_conflict_response(data, world_path=world_path, player_key=player_key, same_player_only=True)
        if conflict:
            deps.audit_event("player.save", "blocked", world_path=world_path, player_key=player_key, details={"reason": "presence_conflict"})
            return conflict
        blocked = deps.require_world_write_allowed()
        if blocked:
            deps.audit_event(
                "player.save",
                "blocked",
                world_path=world_path,
                player_key=player_key,
                details={"reason": "write_gate_recheck"},
            )
            return blocked
        blocked = deps.require_server_guard_current(data)
        if blocked:
            deps.audit_event(
                "player.save",
                "blocked",
                world_path=world_path,
                player_key=player_key,
                details={"reason": "server_guard_recheck"},
            )
            return blocked
        result = deps.service.save_player(
            world_path,
            player_key,
            data.get("inventory"),
            data.get("stats", {}),
            ender_chest_list=data.get("ender_chest"),
            effects_list=data.get("effects"),
            abilities_dict=data.get("abilities"),
            base_revision=data.get("base_revision"),
            allow_create_inventory=deps.json_bool(data, "allow_create_inventory", False),
            allow_create_ender_chest=deps.json_bool(data, "allow_create_ender_chest", False),
            allow_create_effects=deps.json_bool(data, "allow_create_effects", False),
            allow_create_abilities=deps.json_bool(data, "allow_create_abilities", False),
            root_equipment_editable=deps.json_bool(data, "root_equipment_editable", False),
            pre_write_check=lambda: deps.require_final_world_write_allowed("Speichern"),
        )
        presence_conflict_confirmed = data.get("confirm_presence_conflict") in (True, 1, "1", "true", "yes", "ja", "on")
        # Ein Post-Write-Fehler (DB schließen, Backup-Pruning) nach committed Schreiben
        # muss als "bereits geschrieben" transportiert werden, damit die UI nicht erneut speichert.
        committed_write_failure = result.get("write_committed") is True and result.get("success") is False
        if committed_write_failure:
            result.update(
                error_payload(
                    result.get("error") or "Spieler wurde geschrieben, aber die Nachvalidierung ist fehlgeschlagen.",
                    code="player_post_write_validation_failed",
                )
            )
        deps.audit_event(
            "player.save",
            "partial" if committed_write_failure else "success",
            world_path=world_path,
            player_key=player_key,
            details={
                "backup_file": result.get("backup_file"),
                "has_ender_chest": "ender_chest" in data,
                "has_effects": "effects" in data,
                "has_abilities": "abilities" in data,
                "presence_conflict_confirmed": bool(presence_conflict_confirmed),
            },
        )
        response = deps.jsonify(result)
        return (response, 500) if committed_write_failure else response
    except deps.final_write_gate_blocked_error as exc:
        message = str(exc)
        deps.audit_event(
            "player.save",
            "blocked",
            world_path=data.get("world_path"),
            player_key=data.get("player_key"),
            details={"reason": "final_write_gate"},
            error=message,
        )
        payload = error_payload(message, code="final_write_gate_blocked")
        payload["write_gate"] = exc.write_gate
        add_exception_cleanup_details(payload, exc)
        return deps.jsonify(payload), 409
    except ValueError as exc:
        message = str(exc)
        status = 409 if message.startswith("Speichern abgelehnt:") else 400
        deps.audit_event("player.save", "failure", world_path=data.get("world_path"), player_key=data.get("player_key"), error=message)
        if getattr(exc, "cleanup_warning", None):
            return deps.jsonify(add_exception_cleanup_details(error_payload(message, code="player_save_failed"), exc)), status
        return deps.api_error(message, status)
    except Exception as exc:
        deps.log_api_exception("player.save", exc)
        deps.audit_event("player.save", "failure", world_path=data.get("world_path"), player_key=data.get("player_key"), error=str(exc))
        if getattr(exc, "cleanup_warning", None):
            payload = add_exception_cleanup_details(
                error_payload(
                    "Fehler beim Speichern des Spielers: {error}",
                    code="player_save_failed",
                    params={"error": t(str(exc))},
                ),
                exc,
            )
            return deps.jsonify(payload), 500
        return deps.api_error(t("Fehler beim Speichern des Spielers: {error}", error=t(str(exc))), 500)


def export_player(data: dict, deps: PlayerRouteDeps):
    blocked = deps.require_world_db_access_allowed()
    if blocked:
        return blocked
    try:
        world_path = deps.json_string(data, "world_path")
        player_key = deps.json_string(data, "player_key")
        result = deps.service.export_player(world_path, player_key)
        deps.audit_event("player.export", "success", world_path=world_path, player_key=player_key, details={"export_path": result.get("export_path")})
        return deps.jsonify(result)
    except ValueError as exc:
        deps.audit_event("player.export", "failure", world_path=data.get("world_path"), player_key=data.get("player_key"), error=str(exc))
        return deps.api_error(exc)
    except Exception as exc:
        deps.log_api_exception("player.export", exc)
        deps.audit_event("player.export", "failure", world_path=data.get("world_path"), player_key=data.get("player_key"), error=str(exc))
        return deps.api_error(t("Fehler beim Exportieren des Spielers: {error}", error=t(str(exc))), 500)


def import_player_preview(data: dict, deps: PlayerRouteDeps):
    try:
        export_zip = deps.json_string(data, "export_zip")
        world_path = deps.json_string(data, "world_path")
        if getattr(deps.app_config, "is_docker", False):
            export_zip = _validated_player_export_zip_path(export_zip, world_path, deps)
        return deps.jsonify(deps.service.preview_player_export(export_zip, world_path))
    except ValueError as exc:
        cleanup_warning = getattr(exc, "cleanup_warning", None)
        if cleanup_warning:
            payload = error_payload(str(exc), code="import_preview_invalid")
            payload["cleanup_warning"] = cleanup_warning
            snapshot_path = getattr(exc, "source_snapshot_path", None)
            if snapshot_path:
                payload["source_snapshot_path"] = snapshot_path
            return deps.jsonify(payload), 400
        return deps.api_error(exc)
    except Exception as exc:
        deps.log_api_exception("player.import_preview", exc)
        cleanup_warning = getattr(exc, "cleanup_warning", None)
        if cleanup_warning:
            payload = error_payload(
                "Fehler beim Lesen der Import-Vorschau: {error}",
                code="import_preview_failed",
                params={"error": t(str(exc))},
            )
            payload["cleanup_warning"] = cleanup_warning
            snapshot_path = getattr(exc, "source_snapshot_path", None)
            if snapshot_path:
                payload["source_snapshot_path"] = snapshot_path
            return deps.jsonify(payload), 500
        return deps.api_error(t("Fehler beim Lesen der Import-Vorschau: {error}", error=t(str(exc))), 500)


def import_player(data: dict, deps: PlayerRouteDeps):
    blocked = deps.require_world_write_allowed()
    if blocked:
        return blocked
    try:
        export_zip = deps.json_string(data, "export_zip")
        world_path = deps.json_string(data, "world_path")
        export_zip = _validated_player_export_zip_path(export_zip, world_path, deps)
        target_player_key = deps.json_string(data, "target_player_key")
        conflict = deps.presence_conflict_response(data, world_path=world_path, player_key=target_player_key, same_player_only=True)
        if conflict:
            deps.audit_event("player.import", "blocked", world_path=world_path, player_key=target_player_key, details={"reason": "presence_conflict"})
            return conflict
        blocked = deps.require_world_write_allowed()
        if blocked:
            deps.audit_event(
                "player.import",
                "blocked",
                world_path=world_path,
                player_key=target_player_key,
                details={"reason": "write_gate_recheck"},
            )
            return blocked
        import_as_exported_player = deps.json_bool(data, "import_as_exported_player", False)
        if deps.json_bool(data, "import_into_world_copy", False):
            raise ValueError(
                t(
                    "Import in eine automatisch erzeugte Weltkopie wird nicht mehr unterstützt. "
                    "Lade die Oberfläche neu und starte den durch ein verifiziertes Backup geschützten Direktimport erneut."
                )
            )
        import_token = data.get("import_token")
        if not isinstance(import_token, dict):
            raise PlayerImportPreviewStaleError("Spieler-Import abgelehnt: Die Import-Vorschau fehlt oder ist veraltet. Bitte Vorschau neu laden.")
        base_revision = None
        if not import_as_exported_player:
            base_revision = deps.json_string(data, "base_revision")
            if not base_revision:
                raise PlayerImportPreviewStaleError(
                    t("Spieler-Import abgelehnt: Der geladene Zielspielerstand fehlt oder ist veraltet. Lade den Zielspieler neu und prüfe den Import erneut."),
                    target_revision_stale=True,
                )
        # Letzter Gate-Check vor dem Service-Aufruf; der Callback wiederholt ihn
        # im Service unmittelbar vor allen schreibenden Import-Schritten.
        deps.require_final_world_write_allowed("Import")
        result = deps.service.import_player(
            export_zip,
            world_path,
            target_player_key,
            deps.json_bool(data, "confirm_overwrite", False),
            import_as_exported_player=import_as_exported_player,
            import_token=import_token,
            base_revision=base_revision,
            write_gate_check=lambda: deps.require_final_world_write_allowed("Import"),
        )
        deps.audit_event(
            "player.import",
            "success",
            world_path=world_path,
            player_key=target_player_key,
            details={
                "export_zip": export_zip,
                "created_new_player": result.get("created_new_player"),
                "backup_file": result.get("backup_file"),
                "post_write_validated": result.get("post_write_validated"),
            },
        )
        return deps.jsonify(result)
    except PlayerImportRolledBackError as exc:
        deps.log_api_exception("player.import.rolled_back", exc)
        deps.audit_event(
            "player.import",
            "failure",
            world_path=data.get("world_path"),
            player_key=data.get("target_player_key"),
            error=str(exc),
            details={"rolled_back": True, "backup_file": exc.backup_file},
        )
        payload = error_payload(
            t(
                "Spieler-Import fehlgeschlagen; der vorherige Zielzustand wurde erfolgreich wiederhergestellt: {error}",
                error=t(str(exc.original_error)),
            ),
            code="player_import_rolled_back",
            details=t("Sicherungsbackup: {backup}", backup=Path(exc.backup_file).name) if exc.backup_file else None,
        )
        payload.update(
            {
                "write_committed": False,
                "rolled_back": True,
                "backup_file": Path(exc.backup_file).name if exc.backup_file else None,
            }
        )
        add_exception_cleanup_details(payload, exc)
        return deps.jsonify(payload), 500
    except PlayerImportRecordRollbackError as exc:
        deps.log_api_exception("player.import.record_rollback", exc)
        deps.audit_event(
            "player.import",
            "failure",
            world_path=data.get("world_path"),
            player_key=data.get("target_player_key"),
            error=str(exc),
            details={"rolled_back": False, "backup_file": exc.backup_file},
        )
        payload = error_payload(
            t(
                "Spieler-Import fehlgeschlagen und der vorherige Zielzustand konnte nicht vollständig wiederhergestellt werden: {error}",
                error=t(str(exc.original_error)),
            ),
            code="player_import_rollback_failed",
            details=exc.rollback_warning,
        )
        payload.update(
            {
                "write_committed": True,
                "rolled_back": False,
                "rollback_warning": exc.rollback_warning,
                "backup_file": Path(exc.backup_file).name if exc.backup_file else None,
            }
        )
        add_exception_cleanup_details(payload, exc)
        return deps.jsonify(payload), 500
    except PlayerImportPreviewStaleError as exc:
        message = str(exc)
        deps.audit_event("player.import", "failure", world_path=data.get("world_path"), player_key=data.get("target_player_key"), error=message)
        payload = error_payload(message, code="import_preview_stale")
        target_revision_stale = bool(getattr(exc, "target_revision_stale", False))
        payload["preview_stale"] = not target_revision_stale
        if target_revision_stale:
            payload["target_revision_stale"] = True
        add_exception_cleanup_details(payload, exc)
        return deps.jsonify(payload), 409
    except deps.final_write_gate_blocked_error as exc:
        message = str(exc)
        deps.audit_event(
            "player.import",
            "blocked",
            world_path=data.get("world_path"),
            player_key=data.get("target_player_key"),
            details={"reason": "final_write_gate"},
            error=message,
        )
        payload = error_payload(message, code="final_write_gate_blocked")
        payload["write_gate"] = exc.write_gate
        add_exception_cleanup_details(payload, exc)
        return deps.jsonify(payload), 409
    except ValueError as exc:
        deps.audit_event("player.import", "failure", world_path=data.get("world_path"), player_key=data.get("target_player_key"), error=str(exc))
        cleanup_warning = getattr(exc, "cleanup_warning", None)
        if cleanup_warning:
            payload = add_exception_cleanup_details(error_payload(str(exc), code="player_import_invalid"), exc)
            return deps.jsonify(payload), 400
        return deps.api_error(exc)
    except Exception as exc:
        deps.log_api_exception("player.import", exc)
        deps.audit_event("player.import", "failure", world_path=data.get("world_path"), player_key=data.get("target_player_key"), error=str(exc))
        cleanup_warning = getattr(exc, "cleanup_warning", None)
        if cleanup_warning:
            payload = error_payload(
                "Fehler beim Importieren des Spielers: {error}",
                code="player_import_failed",
                params={"error": t(str(exc))},
            )
            add_exception_cleanup_details(payload, exc)
            return deps.jsonify(payload), 500
        return deps.api_error(t("Fehler beim Importieren des Spielers: {error}", error=t(str(exc))), 500)
