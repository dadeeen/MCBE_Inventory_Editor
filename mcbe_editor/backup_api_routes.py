"""Handlers for backup and restore API routes."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .api_errors import error_payload
from .i18n import t
from .world import ensure_valid_world_path


class BackupSourceChangedError(ValueError):
    """Raised when the world changes while a manual backup is being created."""


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


def _source_snapshot(world_path: str) -> str:
    """Return a deterministic metadata snapshot of the world tree.

    The ZIP writer already validates CRCs and publishes atomically. This second
    invariant prevents a structurally valid but logically mixed archive from
    remaining visible when Minecraft, Bedrock Dedicated Server, cloud sync, or
    another process changes the source tree during the walk.
    """

    root_path = os.path.abspath(os.path.normpath(world_path))
    digest = hashlib.sha256()

    def add_entry(kind: str, path: str, info: os.stat_result) -> None:
        relative = os.path.relpath(path, root_path).replace(os.sep, "/")
        record = (
            kind,
            relative,
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )
        digest.update(repr(record).encode("utf-8", errors="surrogatepass"))
        digest.update(b"\n")

    try:
        root_info = os.stat(root_path, follow_symlinks=False)
        if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
            raise ValueError("Welt-Ordner ist kein regulärer Ordner.")
        add_entry("d", root_path, root_info)

        def raise_walk_error(error: OSError) -> None:
            # os.walk otherwise suppresses scandir failures and would produce an
            # incomplete snapshot that cannot reliably detect source changes.
            if isinstance(error, PermissionError):
                path = getattr(error, "filename", None) or root_path
                raise ValueError(
                    t(
                        "Backup abgebrochen: Ein Weltordner kann nicht durchsucht werden. "
                        "Pfad: {path}. Bitte Minecraft/Server, Cloud-Sync, Antivirus oder andere Tools schließen.",
                        path=path,
                    )
                ) from error
            raise error

        for current, dirs, files in os.walk(root_path, topdown=True, onerror=raise_walk_error, followlinks=False):
            dirs[:] = sorted(name for name in dirs if not os.path.islink(os.path.join(current, name)))
            files = sorted(files)

            for name in dirs:
                path = os.path.join(current, name)
                info = os.stat(path, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
                    add_entry("d", path, info)

            for name in files:
                path = os.path.join(current, name)
                info = os.stat(path, follow_symlinks=False)
                if stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode):
                    add_entry("f", path, info)
    except FileNotFoundError as exc:
        raise BackupSourceChangedError(
            "Backup abgebrochen: Die Welt wurde während der Sicherung verändert. Bitte Server vollständig stoppen und erneut versuchen."
        ) from exc
    except PermissionError as exc:
        path = getattr(exc, "filename", None) or root_path
        raise ValueError(
            t(
                "Backup abgebrochen: Eine Weltdatei kann nicht gelesen werden. Pfad: {path}. "
                "Bitte Minecraft/Server, Cloud-Sync, Antivirus oder andere Tools schließen.",
                path=path,
            )
        ) from exc

    return digest.hexdigest()


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
            error=t(str(exc)),
        )
    return None


def list_backups(data: dict, deps: BackupRouteDeps):
    try:
        return deps.jsonify(deps.service.list_backups(deps.json_string(data, "world_path")))
    except ValueError as exc:
        return deps.api_error(exc)
    except Exception as exc:
        deps.log_api_exception("backups.list", exc)
        return deps.api_error(t("Fehler beim Scannen der Backups: {error}", error=t(str(exc))), 500)


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
        cleanup_warning = _remove_rejected_backup(deps, str(world_path or ""), result)
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
        deps.audit_event("backup.create", "failure", world_path=world_path, error=str(exc))
        if cleanup_warning:
            payload = error_payload(str(exc), code="backup_verification_failed")
            payload["cleanup_warning"] = cleanup_warning
            return deps.jsonify(payload), 400
        return deps.api_error(exc)
    except Exception as exc:
        cleanup_warning = _remove_rejected_backup(deps, str(world_path or ""), result) if not backup_verified else None
        deps.log_api_exception("backup.create", exc)
        deps.audit_event("backup.create", "failure", world_path=world_path, error=str(exc))
        if cleanup_warning:
            payload = error_payload(
                "Backup konnte nicht erstellt werden: {error}",
                code="backup_create_failed",
                params={"error": t(str(exc))},
            )
            payload["cleanup_warning"] = cleanup_warning
            return deps.jsonify(payload), 500
        return deps.api_error(t("Backup konnte nicht erstellt werden: {error}", error=t(str(exc))), 500)


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
        return deps.api_error(t("Backup konnte nicht gelöscht werden: {error}", error=t(str(exc))), 500)


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
        return deps.api_error(t("Fehler bei der Restore-Vorschau: {error}", error=t(str(exc))), 500)


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
        pre_restore_backup = getattr(exc, "pre_restore_backup", None)
        if pre_restore_backup:
            payload["pre_restore_backup"] = pre_restore_backup
        cleanup_warning = getattr(exc, "cleanup_warning", None)
        if cleanup_warning:
            payload["cleanup_warning"] = cleanup_warning
        snapshot_path = getattr(exc, "source_snapshot_path", None)
        if snapshot_path:
            payload["source_snapshot_path"] = snapshot_path
        return deps.jsonify(payload), 409
    except ValueError as exc:
        message = str(exc)
        status = 409 if message.startswith("Restore abgelehnt:") else 400
        deps.audit_event("backup.restore", "failure", world_path=data.get("world_path"), details={"backup_file": data.get("backup_file")}, error=message)
        cleanup_warning = getattr(exc, "cleanup_warning", None)
        pre_restore_backup = getattr(exc, "pre_restore_backup", None)
        if cleanup_warning or pre_restore_backup:
            payload = error_payload(message, code="restore_rejected")
            if cleanup_warning:
                payload["cleanup_warning"] = cleanup_warning
            if pre_restore_backup:
                payload["pre_restore_backup"] = pre_restore_backup
            snapshot_path = getattr(exc, "source_snapshot_path", None)
            if snapshot_path:
                payload["source_snapshot_path"] = snapshot_path
            return deps.jsonify(payload), status
        return deps.api_error(message, status)
    except Exception as exc:
        deps.log_api_exception("backup.restore", exc)
        deps.audit_event("backup.restore", "failure", world_path=data.get("world_path"), details={"backup_file": data.get("backup_file")}, error=str(exc))
        cleanup_warning = getattr(exc, "cleanup_warning", None)
        pre_restore_backup = getattr(exc, "pre_restore_backup", None)
        if cleanup_warning or pre_restore_backup:
            payload = error_payload(
                "Fehler bei der Wiederherstellung: {error}",
                code="restore_failed",
                params={"error": t(str(exc))},
            )
            if cleanup_warning:
                payload["cleanup_warning"] = cleanup_warning
            if pre_restore_backup:
                payload["pre_restore_backup"] = pre_restore_backup
            snapshot_path = getattr(exc, "source_snapshot_path", None)
            if snapshot_path:
                payload["source_snapshot_path"] = snapshot_path
            return deps.jsonify(payload), 500
        return deps.api_error(t("Fehler bei der Wiederherstellung: {error}", error=t(str(exc))), 500)
