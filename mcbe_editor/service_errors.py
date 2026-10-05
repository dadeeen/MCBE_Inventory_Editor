"""Stable service exception types that must survive module reloads."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable

from .i18n import t

LOGGER = logging.getLogger(__name__)

INTERNAL_ERROR_REASON = "interner Fehler, Details im Server-Log (Anfrage-ID {request_id})"
INTERNAL_ERROR_REASON_WITHOUT_ID = "interner Fehler, Details im Server-Log"
SYSTEM_ERROR_REASON = "Systemfehler „{reason}“, Details im Server-Log (Anfrage-ID {request_id})"
SYSTEM_ERROR_REASON_WITHOUT_ID = "Systemfehler „{reason}“, Details im Server-Log"


class UserFacingError(Exception):
    """Mark an error whose message the editor phrased for the user.

    Refusals are ValueErrors. Other failures carry this marker when their
    message explains the situation, for example a refused file permission or a
    restore that left the original world elsewhere. The text of every other
    exception can contain local paths or internals and stays in the server log.
    """


class UserFacingRuntimeError(UserFacingError, RuntimeError):
    """A runtime failure with a message phrased for the user."""


def current_request_id() -> str:
    """Return the ID of the active request, which the server log names as well."""

    try:
        from flask import g, has_request_context
    except ImportError:  # pragma: no cover - Flask is a runtime dependency
        return ""
    if not has_request_context():
        return ""
    return str(getattr(g, "request_id", "") or "")


def public_error_text(exc: BaseException) -> str:
    """Return what a client may read about an exception.

    The message of a refusal or of a UserFacingError is shown as it is. Any
    other exception gets a generic reason with the request ID under which the
    server log keeps its text and traceback. An operating system error keeps
    its description, such as a full disk or a file in use, but not the path.
    """

    if isinstance(exc, (ValueError, UserFacingError)):
        return t(str(exc))
    request_id = current_request_id()
    reason = str(exc.strerror or "").strip() if isinstance(exc, OSError) else ""
    if reason:
        if request_id:
            return t(SYSTEM_ERROR_REASON, reason=reason, request_id=request_id)
        return t(SYSTEM_ERROR_REASON_WITHOUT_ID, reason=reason)
    if request_id:
        return t(INTERNAL_ERROR_REASON, request_id=request_id)
    return t(INTERNAL_ERROR_REASON_WITHOUT_ID)


def log_error_detail(context: str, exc: BaseException) -> None:
    """Keep the text and traceback of an error in the server log."""

    LOGGER.error(
        "%s failed request_id=%s error=%s",
        context,
        current_request_id(),
        exc,
        exc_info=(type(exc), exc, exc.__traceback__),
    )


def step_failure_text(label: str, exc: BaseException, *, context: str) -> str:
    """Log a failed step and return "label: reason" as a client may read it."""

    log_error_detail(f"{context}: {label}", exc)
    return f"{label}: {public_error_text(exc)}"


def _rollback_failure_details(failures: tuple[tuple[str, Exception], ...]) -> str:
    return "; ".join(step_failure_text(label, failure, context="rollback") for label, failure in failures)


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


class LevelDbPermissionError(UserFacingError, PermissionError):
    """Expose a LevelDB filesystem permission failure as a stable service error."""

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


class LevelDbInUseError(ValueError):
    """Another process (or write session) holds the world database.

    A ValueError like the other refusals before any write: routes report its
    complete message as a refusal, not as a server error with a second prefix.
    """

    def __init__(self, *, db_path: str) -> None:
        self.db_path = db_path
        super().__init__(
            t(
                "Die Welt-Datenbank wird gerade von einem anderen Programm verwendet (z. B. Minecraft, einem Bedrock-Server "
                "oder einer weiteren Editor-Instanz). Schließe die Welt vollständig und versuche es erneut. Datenbank: {db_path}",
                db_path=db_path,
            )
        )


class LevelDbUncleanLogError(ValueError):
    """The newest write-ahead log ends in a record a crash left incomplete."""

    def __init__(self, *, db_path: str) -> None:
        self.db_path = db_path
        super().__init__(
            t(
                "Die Welt wurde nicht sauber geschlossen: Ihr Schreibprotokoll endet mit einem unvollständigen Eintrag. "
                "Lade die Welt einmal in Minecraft oder im Bedrock-Server und beende sie sauber, bevor du sie bearbeitest. "
                "Datenbank: {db_path}",
                db_path=db_path,
            )
        )


class WriteNotAttemptedError(ValueError):
    """A final gate refused the database call before any storage mutation."""


class WriteOutcomeUnknownError(UserFacingError, RuntimeError):
    """A database write raised without proving that its batch was rolled back."""

    def __init__(self, original_error: Exception, *, backup_file: str | None = None) -> None:
        self.original_error = original_error
        self.backup_file = backup_file
        super().__init__(t("Ob die Änderungen bereits geschrieben wurden, ist unbekannt. Nicht erneut speichern; Welt neu laden und Backup prüfen."))


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
        details = _rollback_failure_details(self.rollback_failures)
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
        details = _rollback_failure_details(self.rollback_failures)
        self.rollback_warning = t("Migrations-Rollback unvollständig: {details}", details=details)
        super().__init__(f"{original_error} {self.rollback_warning}")
