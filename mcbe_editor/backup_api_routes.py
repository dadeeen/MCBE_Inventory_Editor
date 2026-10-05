"""Handlers for backup and restore API routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .api_errors import add_exception_cleanup_details, error_payload
from .backup_consistency import BackupSourceChangedError
from .backup_consistency import source_snapshot as _source_snapshot
from .backup_settings import get_backup_settings, save_backup_settings
from .i18n import t
from .restore_recovery import recovery_command
from .service_errors import public_error_text
from .world import ensure_valid_world_path

# Startup recovery stays deferred while the server status is unknown, so the
# message names the recovery command for the world. The cause can name the
# folder that holds the original world.
RESTORE_OUTCOME_UNKNOWN = (
    "Wiederherstellung unterbrochen. Nicht erneut wiederherstellen oder speichern. Minecraft und Server schließen, "
    "im Anwendungsordner „{command}“ ausführen und danach die Welt neu laden. Ursache: {error}"
)


@dataclass(frozen=True)
class BackupRouteDeps:
    service: Any
    jsonify: Callable[..., Any]
    api_error: Callable[..., Any]
    log_api_exception: Callable[[str, Exception], None]
    json_string: Callable[..., str]
    require_world_write_allowed: Callable[[], Any]
    require_final_world_write_allowed: Callable[[str], Any]
    presence_conflict_response: Callable[..., Any]
    audit_event: Callable[..., None]
    final_write_gate_blocked_error: type[Exception]


def _remove_rejected_backup(deps: BackupRouteDeps, world_path: str, result: dict | None) -> str | None:
    backup_file = result.get("backup_file") if isinstance(result, dict) else None
    if not backup_file:
        return None
    try:
        deps.service.delete_backup(world_path, backup_file)
    except Exception as exc:  # noqa: BLE001 - cleanup failure must reach the user
        deps.log_api_exception("backup.create.cleanup", exc)
        return t(
            "Das verworfene Backup konnte nicht automatisch entfernt werden: {file}. Bitte lösche es manuell. Fehler: {error}",
            file=backup_file,
            error=public_error_text(exc),
        )
    return None


def backup_settings(data: dict | None, deps: BackupRouteDeps):
    try:
        if data is None:
            settings = get_backup_settings()
        else:
            settings = save_backup_settings(data.get("max_uncompressed_mib"))
            deps.audit_event("backup.settings", "success", details={"max_uncompressed_mib": settings["max_uncompressed_mib"]})
        return deps.jsonify({"success": True, "settings": settings})
    except PermissionError as exc:
        return deps.api_error(exc, 403)
    except ValueError as exc:
        return deps.api_error(exc)
    except OSError as exc:
        deps.log_api_exception("backup.settings", exc)
        return deps.api_error(t("Backup-Einstellungen konnten nicht gelesen oder gespeichert werden."), 500)


def list_backups(data: dict, deps: BackupRouteDeps):
    try:
        return deps.jsonify(deps.service.list_backups(deps.json_string(data, "world_path")))
    except ValueError as exc:
        return deps.api_error(exc)
    except Exception as exc:
        deps.log_api_exception("backups.list", exc)
        return deps.api_error(t("Fehler beim Scannen der Backups: {error}", error=public_error_text(exc)), 500)


def create_backup(data: dict, deps: BackupRouteDeps):
    blocked = deps.require_world_write_allowed()
    if blocked:
        return blocked

    world_path = data.get("world_path")
    result = None
    backup_verified = False
    try:
        world_path = deps.json_string(data, "world_path")
        ensure_valid_world_path(world_path)
        before = _source_snapshot(world_path)

        # Re-check after the potentially long directory snapshot and immediately
        # before the service starts reading files into the archive.
        deps.require_final_world_write_allowed("Manuelles Backup")
        result = deps.service.create_manual_backup(world_path)

        # A server can start while the ZIP is being written. Never keep the
        # archive unless the gate and source metadata are still stable afterwards.
        deps.require_final_world_write_allowed("Manuelles Backup")
        after = _source_snapshot(world_path)
        deps.require_final_world_write_allowed("Manuelles Backup")
        if before != after:
            raise BackupSourceChangedError(
                "Backup verworfen: Die Welt wurde während der Sicherung verändert. Bitte Server vollständig stoppen und erneut versuchen."
            )

        # Only failures before this point invalidate the just-created archive.
        # Audit/logging failures after successful verification must not destroy a
        # valid backup merely because response bookkeeping failed.
        backup_verified = True
        deps.audit_event("backup.create", "success", world_path=world_path, details={"backup_file": result.get("backup_file")})
        return deps.jsonify(result)
    except deps.final_write_gate_blocked_error as exc:
        cleanup_warning = _remove_rejected_backup(deps, str(world_path or ""), result)
        message = str(exc)
        deps.audit_event(
            "backup.create",
            "blocked",
            world_path=world_path,
            details={"backup_file": result.get("backup_file") if isinstance(result, dict) else None, "reason": "final_write_gate"},
            error=message,
        )
        payload = error_payload(message, code="final_write_gate_blocked")
        payload["write_gate"] = exc.write_gate
        if cleanup_warning:
            payload["cleanup_warning"] = cleanup_warning
        return deps.jsonify(payload), 409
    except BackupSourceChangedError as exc:
        cleanup_warning = _remove_rejected_backup(deps, str(world_path or ""), result) or getattr(exc, "cleanup_warning", None)
        message = str(exc)
        deps.audit_event(
            "backup.create",
            "blocked",
            world_path=world_path,
            details={"backup_file": result.get("backup_file") if isinstance(result, dict) else None, "reason": "source_changed"},
            error=message,
        )
        payload = error_payload(message, code="backup_source_changed")
        if cleanup_warning:
            payload["cleanup_warning"] = cleanup_warning
        return deps.jsonify(payload), 409
    except ValueError as exc:
        cleanup_warning = _remove_rejected_backup(deps, str(world_path or ""), result) if not backup_verified else None
        cleanup_warning = cleanup_warning or getattr(exc, "cleanup_warning", None)
        deps.audit_event("backup.create", "failure", world_path=world_path, error=str(exc))
        if cleanup_warning:
            payload = error_payload(str(exc), code="backup_verification_failed")
            payload["cleanup_warning"] = cleanup_warning
            return deps.jsonify(payload), 400
        return deps.api_error(exc)
    except Exception as exc:
        cleanup_warning = _remove_rejected_backup(deps, str(world_path or ""), result) if not backup_verified else None
        cleanup_warning = cleanup_warning or getattr(exc, "cleanup_warning", None)
        deps.log_api_exception("backup.create", exc)
        deps.audit_event("backup.create", "failure", world_path=world_path, error=str(exc))
        if cleanup_warning:
            payload = error_payload(
                "Backup konnte nicht erstellt werden: {error}",
                code="backup_create_failed",
                params={"error": public_error_text(exc)},
            )
            payload["cleanup_warning"] = cleanup_warning
            return deps.jsonify(payload), 500
        return deps.api_error(t("Backup konnte nicht erstellt werden: {error}", error=public_error_text(exc)), 500)


def delete_backup(data: dict, deps: BackupRouteDeps):
    try:
        world_path = deps.json_string(data, "world_path")
        backup_file = deps.json_string(data, "backup_file")
        result = deps.service.delete_backup(world_path, backup_file)
        deps.audit_event("backup.delete", "success", world_path=world_path, details={"backup_file": backup_file})
        return deps.jsonify(result)
    except FileNotFoundError as exc:
        deps.audit_event("backup.delete", "failure", world_path=data.get("world_path"), details={"backup_file": data.get("backup_file")}, error=str(exc))
        return deps.api_error(exc, 404)
    except ValueError as exc:
        deps.audit_event("backup.delete", "failure", world_path=data.get("world_path"), details={"backup_file": data.get("backup_file")}, error=str(exc))
        return deps.api_error(exc)
    except Exception as exc:
        deps.log_api_exception("backup.delete", exc)
        deps.audit_event("backup.delete", "failure", world_path=data.get("world_path"), details={"backup_file": data.get("backup_file")}, error=str(exc))
        return deps.api_error(t("Backup konnte nicht gelöscht werden: {error}", error=public_error_text(exc)), 500)


def restore_backup_preview(data: dict, deps: BackupRouteDeps):
    try:
        world_path = deps.json_string(data, "world_path")
        backup_file = deps.json_string(data, "backup_file")
        result = deps.service.preview_backup_restore(world_path, backup_file)
        return deps.jsonify(result)
    except ValueError as exc:
        return deps.api_error(exc)
    except Exception as exc:
        deps.log_api_exception("backup.restore_preview", exc)
        return deps.api_error(t("Fehler bei der Restore-Vorschau: {error}", error=public_error_text(exc)), 500)


def _restore_outcome_unknown(data: dict, deps: BackupRouteDeps, exc: Exception):
    deps.log_api_exception("backup.restore", exc)
    deps.audit_event(
        "backup.restore",
        "failure",
        world_path=data.get("world_path"),
        details={"backup_file": data.get("backup_file"), "write_outcome_unknown": True},
        error=str(exc),
    )
    command = recovery_command(str(data["world_path"]), "--confirm-server-stopped")
    payload = error_payload(
        RESTORE_OUTCOME_UNKNOWN,
        code="restore_outcome_unknown",
        params={"command": command, "error": public_error_text(exc)},
    )
    payload.update(write_outcome_unknown=True, reload_required=True)
    return deps.jsonify(add_exception_cleanup_details(payload, exc)), 500


def restore_backup(data: dict, deps: BackupRouteDeps):
    blocked = deps.require_world_write_allowed()
    if blocked:
        return blocked
    try:
        world_path = deps.json_string(data, "world_path")
        backup_file = deps.json_string(data, "backup_file")
        backup_token = data.get("backup_token")
        if not isinstance(backup_token, dict):
            raise ValueError("Restore abgelehnt: Die Restore-Vorschau fehlt oder ist veraltet. Bitte Vorschau neu laden.")
        conflict = deps.presence_conflict_response(data, world_path=world_path, same_player_only=False)
        if conflict:
            deps.audit_event("backup.restore", "blocked", world_path=world_path, details={"backup_file": backup_file, "reason": "presence_conflict"})
            return conflict
        blocked = deps.require_world_write_allowed()
        if blocked:
            deps.audit_event(
                "backup.restore",
                "blocked",
                world_path=world_path,
                details={"backup_file": backup_file, "reason": "write_gate_recheck"},
            )
            return blocked
        result = deps.service.restore_backup(
            world_path,
            backup_file,
            backup_token=backup_token,
            pre_restore_check=lambda: deps.require_final_world_write_allowed("Restore"),
        )
        deps.audit_event(
            "backup.restore",
            "success",
            world_path=world_path,
            details={"backup_file": backup_file, "pre_restore_backup": result.get("pre_restore_backup")},
        )
        return deps.jsonify(result)
    except deps.final_write_gate_blocked_error as exc:
        message = str(exc)
        deps.audit_event(
            "backup.restore",
            "blocked",
            world_path=data.get("world_path"),
            details={"backup_file": data.get("backup_file"), "reason": "final_write_gate"},
            error=message,
        )
        payload = error_payload(message, code="final_write_gate_blocked")
        payload["write_gate"] = exc.write_gate
        return deps.jsonify(add_exception_cleanup_details(payload, exc)), 409
    except ValueError as exc:
        if getattr(exc, "write_outcome_unknown", False) is True:
            return _restore_outcome_unknown(data, deps, exc)
        message = str(exc)
        status = 409 if message.startswith("Restore abgelehnt:") else 400
        deps.audit_event("backup.restore", "failure", world_path=data.get("world_path"), details={"backup_file": data.get("backup_file")}, error=message)
        recovery_details = add_exception_cleanup_details({}, exc)
        if recovery_details:
            payload = error_payload(exc, code="restore_rejected")
            payload.update(recovery_details)
            return deps.jsonify(payload), status
        return deps.api_error(exc, status)
    except Exception as exc:
        if getattr(exc, "write_outcome_unknown", False) is True:
            return _restore_outcome_unknown(data, deps, exc)
        deps.log_api_exception("backup.restore", exc)
        deps.audit_event("backup.restore", "failure", world_path=data.get("world_path"), details={"backup_file": data.get("backup_file")}, error=str(exc))
        recovery_details = add_exception_cleanup_details({}, exc)
        if recovery_details:
            payload = error_payload(
                "Fehler bei der Wiederherstellung: {error}",
                code="restore_failed",
                params={"error": public_error_text(exc)},
            )
            payload.update(recovery_details)
            return deps.jsonify(payload), 500
        return deps.api_error(t("Fehler bei der Wiederherstellung: {error}", error=public_error_text(exc)), 500)
