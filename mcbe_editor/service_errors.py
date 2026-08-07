"""Stable service exception types that must survive module reloads."""

from __future__ import annotations

import os
from collections.abc import Iterable

from .i18n import t


def denied_write_actor() -> str:
    """Name the gatekeeper of a refused write without assuming Windows."""

    return t("Windows") if os.name == "nt" else t("Das Betriebssystem")


def denied_write_permission_hint() -> str:
    """Explain how to grant the missing write permission on this platform.

    The Docker image runs as a non-root user, so a refused write there is almost
    always a missing ACL for that UID on the mounted host directory. Windows
    advice about write protection and antivirus would send those users looking in
    the wrong place, so name the effective UID and point to the complete,
    inheritance-safe ACL procedure.
    """

    if os.name == "nt":
        return t("Prüfe Schreibschutz, Dateirechte und ob Antivirus/Cloud-Sync den Ordner blockiert.")
    # Resolve the POSIX-only APIs dynamically so one source type-checks on both
    # Windows and Linux instead of relying on platform-specific ignores.
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if not callable(getuid) or not callable(getgid):  # pragma: no cover - defensive non-NT/non-POSIX fallback
        return t("Prüfe die Schreibrechte des aktuellen Betriebssystem-Benutzers auf diesem Ordner.")
    uid = int(getuid())
    gid = int(getgid())
    return t(
        "Der Editor läuft als UID/GID {uid}/{gid} und braucht Schreibrechte auf diesem Ordner. "
        "Richte im Docker-Betrieb auf dem gemounteten Host-Ordner eine gezielte ACL einschließlich Default-ACL für neue Dateien ein. "
        "Details und vollständige Befehle stehen im README-Abschnitt 'Schreibrechte für Docker-Welten'.",
        uid=uid,
        gid=gid,
    )


class LevelDbPermissionError(PermissionError):
    """Expose a native LevelDB permission failure as a stable service error."""

    def __init__(self, *, operation: str, db_path: str) -> None:
        self.operation = operation
        self.db_path = db_path
        super().__init__(
            t(
                "LevelDB-Zugriff abgelehnt ({operation}): {actor} verweigert Zugriff auf die Welt-Datenbank. Datenbank: {db_path}. {hint}",
                operation=t(operation),
                actor=denied_write_actor(),
                db_path=db_path,
                hint=denied_write_permission_hint(),
            )
        )


class PlayerImportPreviewStaleError(ValueError):
    """Signal that an import must obtain a fresh preview token."""

    def __init__(self, message: str, *, target_revision_stale: bool = False) -> None:
        self.target_revision_stale = target_revision_stale
        super().__init__(message)


class PlayerStateTransferPreviewStaleError(ValueError):
    """Signal that a player-state transfer needs a fresh preview."""


class PlayerImportRolledBackError(RuntimeError):
    """Signal that a failed direct import restored the previous target record."""

    def __init__(self, original_error: Exception, *, backup_file: str | None = None) -> None:
        self.original_error = original_error
        self.backup_file = backup_file
        self.write_committed = False
        self.rolled_back = True
        super().__init__(str(original_error))


class PlayerImportRecordRollbackError(RuntimeError):
    """Signal that a failed direct import could not restore its target record."""

    def __init__(
        self,
        original_error: Exception,
        *,
        backup_file: str | None = None,
        rollback_failures: Iterable[tuple[str, Exception]] = (),
    ) -> None:
        self.original_error = original_error
        self.backup_file = backup_file
        self.rollback_failures = tuple(rollback_failures)
        self.write_committed = True
        self.rolled_back = False
        details = "; ".join(f"{label}: {exc}" for label, exc in self.rollback_failures)
        self.rollback_warning = t("Import-Rollback unvollständig: {details}", details=details)
        super().__init__(f"{original_error} {self.rollback_warning}")


class PlayerStateTransferRolledBackError(RuntimeError):
    """Signal that a failed state transfer restored the previous target record."""

    def __init__(self, original_error: Exception, *, backup_file: str | None = None) -> None:
        self.original_error = original_error
        self.backup_file = backup_file
        self.write_committed = False
        self.rolled_back = True
        super().__init__(str(original_error))


class PlayerStateTransferRollbackError(RuntimeError):
    """Signal that a failed state transfer could not restore its target record."""

    def __init__(
        self,
        original_error: Exception,
        *,
        backup_file: str | None = None,
        rollback_failures: Iterable[tuple[str, Exception]] = (),
    ) -> None:
        self.original_error = original_error
        self.backup_file = backup_file
        self.rollback_failures = tuple(rollback_failures)
        self.write_committed = True
        self.rolled_back = False
        details = "; ".join(f"{label}: {exc}" for label, exc in self.rollback_failures)
        self.rollback_warning = t("Migrations-Rollback unvollständig: {details}", details=details)
        super().__init__(f"{original_error} {self.rollback_warning}")
