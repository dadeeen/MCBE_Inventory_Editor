import contextlib
import errno
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import stat
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from functools import wraps
from pathlib import Path, PurePosixPath

from .config import load_config
from .i18n import t
from .runtime_data import atomic_write_private_text
from .world import get_world_name
from .world_locks import locked_world

MAX_BACKUP_UNCOMPRESSED_MB = 1024
MAX_BACKUP_MEMBERS = 50000
MAX_BACKUP_BASENAME_LENGTH = 80
MAX_BACKUP_FILENAME_LENGTH = 180
BACKUP_DIR_HASH_LENGTH = 12
RESTORE_TOKEN_VERSION = 1
BACKUP_METADATA_VERSION = 1
BACKUP_KIND_AUTOMATIC = "automatic"
BACKUP_KIND_MANUAL = "manual"
BACKUP_KIND_PRE_RESTORE = "pre_restore"
BACKUP_KIND_LEGACY = "legacy"
BACKUP_KINDS = {
    BACKUP_KIND_AUTOMATIC,
    BACKUP_KIND_MANUAL,
    BACKUP_KIND_PRE_RESTORE,
    BACKUP_KIND_LEGACY,
}
RETENTION_ROLLING = "rolling"
RETENTION_PINNED = "pinned"
RETENTION_RECOVERY = "recovery"
BACKUP_KIND_LABELS = {
    BACKUP_KIND_AUTOMATIC: "Automatisch",
    BACKUP_KIND_MANUAL: "Manuell",
    BACKUP_KIND_PRE_RESTORE: "Vor Wiederherstellung",
    BACKUP_KIND_LEGACY: "Legacy",
}
STALE_BACKUP_ARTIFACT_SECONDS = 24 * 60 * 60
BACKUP_INTEGRITY_CACHE_FILENAME = ".backup_integrity_cache.json"
BACKUP_INTEGRITY_CACHE_VERSION = 1
RESTORE_TRANSACTION_VERSION = 1
RESTORE_TRANSACTION_RE = re.compile(r"^\.mcbe_restore_([0-9a-f]{16})\.json$")
BACKUP_FILENAME_METADATA_RE = re.compile(
    r"__(automatic|manual|pre_restore)__\d{8}T\d{6}Z__[0-9a-f]{16}\.zip$",
    re.IGNORECASE,
)

LOGGER = logging.getLogger(__name__)


def remove_backup_after_aborted_write(backup_file: str | None, operation_error: Exception, *, operation: str) -> None:
    """Remove a pre-write backup or attach a user-visible cleanup warning."""

    if not backup_file:
        return
    try:
        os.remove(backup_file)
    except FileNotFoundError:
        return
    except OSError as cleanup_exc:
        warning = t(
            "Ein zusätzliches Backup aus dem abgebrochenen Vorgang konnte nicht entfernt werden und blieb unter {path} zurück: {error}",
            path=backup_file,
            error=cleanup_exc,
        )
        existing = getattr(operation_error, "cleanup_warning", None)
        operation_error.cleanup_warning = f"{existing} {warning}" if existing else warning
        LOGGER.exception(
            "Zusätzliches Backup nach abgebrochenem Vorgang konnte nicht entfernt werden operation=%s path=%s",
            operation,
            backup_file,
        )


def _fsync_directory(path: str) -> None:
    """Best-effort durability barrier for directory entry changes."""

    if os.name == "nt" or not hasattr(os, "O_DIRECTORY"):
        return
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        os.fsync(fd)
    except OSError:
        # Some bind, network, and virtual filesystems do not support directory
        # fsync. The restore remains usable there, but durability is determined
        # by the backing filesystem.
        pass
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)


def _is_valid_world_directory(path: str) -> bool:
    try:
        return os.path.isdir(path) and not os.path.islink(path) and os.path.isdir(os.path.join(path, "db")) and not os.path.islink(os.path.join(path, "db"))
    except OSError:
        return False


def _valid_transaction_basename(value, *, prefix: str = "") -> bool:
    return (
        isinstance(value, str)
        and value not in {"", ".", ".."}
        and value == os.path.basename(value)
        and "\x00" not in value
        and (not prefix or value.startswith(prefix))
    )


def _write_restore_transaction(
    parent_dir: str,
    world_dir_name: str,
    rollback_dir: str,
    temp_restore_dir: str,
    transaction_id: str,
) -> str:
    journal_path = os.path.join(parent_dir, f".mcbe_restore_{transaction_id}.json")
    payload = {
        "schema_version": RESTORE_TRANSACTION_VERSION,
        "transaction_id": transaction_id,
        "world_dir_name": world_dir_name,
        "rollback_dir_name": os.path.basename(rollback_dir),
        "staging_dir_name": os.path.basename(temp_restore_dir),
        "created_at": datetime.now(UTC).isoformat(),
    }
    if os.path.lexists(journal_path):
        raise FileExistsError(f"Restore-Transaktionsmarker existiert bereits: {journal_path}")
    try:
        # Publish only a complete, fsynced JSON document. A hard stop before
        # os.replace can leave at most an ignored temporary file; the world swap
        # starts only after this function has returned successfully.
        atomic_write_private_text(
            Path(journal_path),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        )
        _fsync_directory(parent_dir)
    except BaseException as exc:
        # No world rename has happened yet, so a marker left by a failed journal
        # publication must not turn a harmless abort into manual recovery.
        try:
            os.remove(journal_path)
        except FileNotFoundError:
            pass
        except OSError as cleanup_exc:
            warning = t(
                "Der unvollständige Restore-Transaktionsmarker konnte nicht entfernt werden und blieb unter {path} zurück: {error}",
                path=journal_path,
                error=cleanup_exc,
            )
            existing = getattr(exc, "cleanup_warning", None)
            exc.cleanup_warning = f"{existing} {warning}" if existing else warning
            exc.transaction_journal_path = journal_path
            LOGGER.exception("Unvollständiger Restore-Transaktionsmarker konnte nicht entfernt werden: %s", journal_path)
        else:
            with contextlib.suppress(OSError):
                _fsync_directory(parent_dir)
        raise
    return journal_path


def _remove_restore_transaction(journal_path: str) -> None:
    os.remove(journal_path)
    _fsync_directory(os.path.dirname(journal_path))


def _load_restore_transaction(journal_path: str) -> dict:
    filename = os.path.basename(journal_path)
    match = RESTORE_TRANSACTION_RE.fullmatch(filename)
    if not match or os.path.islink(journal_path):
        raise ValueError("Ungültiger Restore-Transaktionsmarker.")
    with open(journal_path, encoding="utf-8") as journal:
        payload = json.load(journal)
    if not isinstance(payload, dict) or payload.get("schema_version") != RESTORE_TRANSACTION_VERSION:
        raise ValueError("Unbekannte Restore-Transaktionsversion.")
    transaction_id = payload.get("transaction_id")
    world_name = payload.get("world_dir_name")
    rollback_name = payload.get("rollback_dir_name")
    staging_name = payload.get("staging_dir_name")
    if transaction_id != match.group(1):
        raise ValueError("Restore-Transaktionskennung stimmt nicht überein.")
    if not _valid_transaction_basename(world_name):
        raise ValueError("Ungültiger Weltordner im Restore-Transaktionsmarker.")
    if not _valid_transaction_basename(rollback_name, prefix=f".{world_name}_rollback_") or not rollback_name.endswith(f"_{transaction_id}"):
        raise ValueError("Ungültiger Rollback-Ordner im Restore-Transaktionsmarker.")
    if not _valid_transaction_basename(staging_name, prefix=f".{world_name}_restoring_"):
        raise ValueError("Ungültiger Staging-Ordner im Restore-Transaktionsmarker.")
    return payload


def _remove_restore_staging(path: str) -> None:
    if not os.path.lexists(path):
        return
    if os.path.islink(path) or not os.path.isdir(path):
        raise OSError(f"Restore-Staging ist kein regulärer Ordner: {path}")
    shutil.rmtree(path)


def recover_restore_transaction(journal_path: str, *, recovery_gate_check=None) -> dict:
    """Finish or roll back one journaled restore after an interrupted process."""

    journal_path = os.path.abspath(os.path.normpath(journal_path))
    parent_dir = os.path.dirname(journal_path)
    try:
        payload = _load_restore_transaction(journal_path)
    except FileNotFoundError:
        return {"status": "already-resolved"}
    world_path = os.path.join(parent_dir, payload["world_dir_name"])

    with locked_world(world_path):
        if not os.path.exists(journal_path):
            return {"status": "already-resolved", "world_path": world_path}
        payload = _load_restore_transaction(journal_path)
        locked_world_path = os.path.join(parent_dir, payload["world_dir_name"])
        if os.path.normcase(locked_world_path) != os.path.normcase(world_path):
            raise RuntimeError("Restore-Transaktionsziel wurde während der Prüfung verändert.")
        if recovery_gate_check is not None:
            gate = recovery_gate_check()
            if isinstance(gate, dict) and gate.get("allowed") is not True:
                return {
                    "status": "deferred-write-gate",
                    "world_path": world_path,
                    "journal_path": journal_path,
                    "reason": str(gate.get("reason") or "Schreibschutzprüfung blockiert die Wiederaufnahme."),
                }
        rollback_path = os.path.join(parent_dir, payload["rollback_dir_name"])
        staging_path = os.path.join(parent_dir, payload["staging_dir_name"])
        world_valid = _is_valid_world_directory(world_path)
        rollback_valid = _is_valid_world_directory(rollback_path)

        if not os.path.lexists(world_path) and rollback_valid:
            os.replace(rollback_path, world_path)
            _fsync_directory(parent_dir)
            _remove_restore_staging(staging_path)
            _remove_restore_transaction(journal_path)
            return {"status": "original-restored", "world_path": world_path}

        # A completed atomic swap consumes the staging directory.  If a valid
        # world and the original rollback exist while staging is still present,
        # the world may have been recreated externally after the first rename.
        # Never delete either candidate automatically in that ambiguous state.
        if world_valid and not os.path.lexists(staging_path):
            if os.path.lexists(rollback_path):
                if os.path.islink(rollback_path) or not os.path.isdir(rollback_path):
                    raise RuntimeError(f"Restore-Rollback ist kein regulärer Ordner: {rollback_path}")
                shutil.rmtree(rollback_path)
            _remove_restore_staging(staging_path)
            _fsync_directory(parent_dir)
            _remove_restore_transaction(journal_path)
            return {"status": "committed-cleaned", "world_path": world_path}

        # Without any rollback entry the swap never (net) happened: either the
        # process died before the first rename, or an interrupted recovery
        # already moved the original back and only its staging/journal cleanup
        # is missing.  The world directory is then the only world candidate and
        # staging merely mirrors a still-existing backup ZIP, so cleaning up is
        # safe and keeps re-running the recovery idempotent.
        if world_valid and not os.path.lexists(rollback_path):
            _remove_restore_staging(staging_path)
            _fsync_directory(parent_dir)
            _remove_restore_transaction(journal_path)
            return {"status": "not-started-cleaned", "world_path": world_path}

        raise RuntimeError(
            f"Unterbrochener Restore konnte nicht automatisch aufgelöst werden: Welt={world_path}, Rollback={rollback_path}, Staging={staging_path}. "
            "Keine der vorhandenen Weltkopien wurde gelöscht."
        )


def _restore_journals_below(root_path: str, *, max_depth: int, max_dirs: int) -> list[str]:
    root = os.path.abspath(os.path.normpath(root_path))
    journals = []
    if not os.path.isdir(root) or os.path.islink(root):
        return journals
    for checked, (current, dirs, files) in enumerate(os.walk(root, topdown=True, followlinks=False), start=1):
        depth = len(os.path.relpath(current, root).split(os.sep)) if current != root else 0
        dirs[:] = [
            name
            for name in dirs
            if depth < max_depth
            and name not in {"db", "backups", ".git", ".hg", ".svn", "__pycache__"}
            and not name.endswith("_backups")
            and not (name.startswith(".") and ("_restoring_" in name or "_rollback_" in name))
            and not os.path.islink(os.path.join(current, name))
        ]
        journals.extend(os.path.join(current, name) for name in files if RESTORE_TRANSACTION_RE.fullmatch(name))
        if checked >= max_dirs:
            break
    return journals


def recover_interrupted_restores(scan_roots, *, max_depth: int = 4, max_dirs: int = 2000, recovery_gate_check=None) -> list[dict]:
    """Recover journaled restores found inside configured world roots."""

    journal_paths = set()
    for value in scan_roots:
        root = os.path.abspath(os.path.normpath(os.fspath(value)))
        journal_paths.update(_restore_journals_below(root, max_depth=max_depth, max_dirs=max_dirs))
        # A configured path may point directly at one world. Its transaction
        # marker necessarily lives in the parent, so inspect only markers whose
        # declared target resolves exactly to that configured path.
        parent = os.path.dirname(root)
        if os.path.isdir(parent):
            with contextlib.suppress(OSError):
                for name in os.listdir(parent):
                    if RESTORE_TRANSACTION_RE.fullmatch(name):
                        candidate = os.path.join(parent, name)
                        with contextlib.suppress(OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
                            payload = _load_restore_transaction(candidate)
                            if os.path.normcase(os.path.join(parent, payload["world_dir_name"])) == os.path.normcase(root):
                                journal_paths.add(candidate)

    results = []
    for journal_path in sorted(journal_paths):
        try:
            results.append(recover_restore_transaction(journal_path, recovery_gate_check=recovery_gate_check))
        except Exception as exc:
            results.append({"status": "manual-recovery-required", "journal_path": journal_path, "error": str(exc)})
    return results


def _world_locked(function):
    @wraps(function)
    def wrapper(world_path, *args, **kwargs):
        with locked_world(world_path):
            return function(world_path, *args, **kwargs)

    return wrapper


class BackupRetentionError(OSError):
    """Report backup files that could not be removed during retention."""

    def __init__(self, failures):
        self.failures = tuple(failures)
        details = "; ".join(f"{os.path.basename(path)}: {exc}" for path, exc in self.failures)
        super().__init__(t("{count} alte Backup-Datei(en) konnten nicht gelöscht werden: {details}", count=len(self.failures), details=details))


def _safe_backup_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in name).strip()
    cleaned = cleaned[:MAX_BACKUP_BASENAME_LENGTH].rstrip(" ._-")
    return cleaned or "world"


def _retention_class_for_kind(kind: str) -> str:
    if kind == BACKUP_KIND_MANUAL:
        return RETENTION_PINNED
    if kind == BACKUP_KIND_PRE_RESTORE:
        return RETENTION_RECOVERY
    return RETENTION_ROLLING


def _normalize_backup_kind(kind: str) -> str:
    if kind not in BACKUP_KINDS - {BACKUP_KIND_LEGACY}:
        raise ValueError(f"Unbekannte Backup-Art: {kind}")
    return kind


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _metadata_created_at(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _utc_datetime_from_timestamp(timestamp) -> datetime | None:
    """Convert a POSIX timestamp without relying on the platform C runtime.

    Windows can store NTFS mtimes before 1970 even though
    ``datetime.fromtimestamp`` rejects them. POSIX arithmetic keeps those valid
    filesystem values available to the language-neutral API fields.
    """

    try:
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=float(timestamp))
    except (OverflowError, TypeError, ValueError):
        return None


def _backup_display_datetime(dt: datetime | None) -> str:
    if dt is None:
        return t("unbekannt")
    try:
        displayed = dt.astimezone()
    except (OSError, OverflowError, ValueError):
        # Windows local-time conversion has a narrower range than NTFS. The
        # ISO field remains UTC and authoritative; keep the legacy display
        # fallback usable instead of failing the complete backup response.
        displayed = dt
    try:
        return displayed.strftime("%d.%m.%Y %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return t("unbekannt")


def _parse_created_at(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _backup_metadata(world_path: str, *, kind: str, created_at: datetime, restore_source: str | None = None) -> dict:
    metadata = {
        "schema_version": BACKUP_METADATA_VERSION,
        "kind": kind,
        "retention_class": _retention_class_for_kind(kind),
        "created_at": _metadata_created_at(created_at),
        "world_id": _restore_world_id(world_path),
        "world_name": get_world_name(world_path),
    }
    if restore_source:
        metadata["restore_source"] = os.path.basename(restore_source)
    return metadata


def _metadata_comment(metadata: dict) -> bytes:
    encoded = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(encoded) > 65_535:
        raise ValueError("Backup-Metadaten sind zu groß.")
    return encoded


def _metadata_from_filename(filename: str) -> dict | None:
    match = BACKUP_FILENAME_METADATA_RE.search(filename)
    if match is None:
        return None
    kind = match.group(1).lower()
    return {
        "schema_version": BACKUP_METADATA_VERSION,
        "kind": kind,
        "retention_class": _retention_class_for_kind(kind),
    }


def _read_backup_metadata(zipf: zipfile.ZipFile, filename: str) -> dict:
    metadata = None
    if zipf.comment:
        try:
            candidate = json.loads(zipf.comment.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            candidate = None
        if isinstance(candidate, dict):
            kind = candidate.get("kind")
            created_at = _parse_created_at(candidate.get("created_at"))
            if candidate.get("schema_version") == BACKUP_METADATA_VERSION and kind in BACKUP_KINDS - {BACKUP_KIND_LEGACY}:
                metadata = {
                    **candidate,
                    "kind": kind,
                    "retention_class": _retention_class_for_kind(kind),
                    "_trusted_complete": True,
                }
                if created_at is not None:
                    metadata["created_at"] = _metadata_created_at(created_at)
                else:
                    metadata.pop("created_at", None)
    if metadata is None:
        metadata = _metadata_from_filename(filename)
    if metadata is None:
        metadata = {
            "schema_version": 0,
            "kind": BACKUP_KIND_LEGACY,
            "retention_class": RETENTION_ROLLING,
        }
    metadata.setdefault("_trusted_complete", False)
    return metadata


def _is_path_inside_or_same(path: str | os.PathLike, root: str | os.PathLike) -> bool:
    try:
        # Resolve symlinks as well as ``..`` segments.  A backup root that looks
        # outside the world but is a symlink back into it would otherwise be
        # deleted during restore together with the world directory.
        normalized_path = os.path.normcase(os.path.realpath(os.path.abspath(os.path.normpath(path))))
        normalized_root = os.path.normcase(os.path.realpath(os.path.abspath(os.path.normpath(root))))
        return os.path.commonpath([normalized_root, normalized_path]) == normalized_root
    except (OSError, ValueError):
        return False


def _world_backup_id(world_path: str | os.PathLike) -> str:
    """Return a stable-enough, path-based ID to isolate equal world folder names."""

    normalized = os.path.normcase(os.path.realpath(os.path.abspath(os.path.normpath(world_path))))
    return hashlib.sha256(normalized.encode("utf-8", errors="surrogatepass")).hexdigest()[:BACKUP_DIR_HASH_LENGTH]


def get_backups_dir(world_path):
    config = load_config()
    world_dir_name = os.path.basename(os.path.normpath(world_path))
    if config.backup_root:
        # In Docker/LAN setups many worlds can share a folder name, for example
        # /worlds/server1/world and /worlds/server2/world.  A basename-only
        # backup directory would mix those backups and could allow restoring the
        # wrong world.  Keep the human-readable folder name, but isolate it with
        # a short hash of the normalized real world path.
        backup_dir_name = f"{_safe_backup_name(world_dir_name)}_{_world_backup_id(world_path)}"
        return os.path.join(os.path.abspath(os.path.normpath(config.backup_root)), backup_dir_name)
    parent_dir = os.path.dirname(os.path.normpath(world_path))
    return os.path.join(parent_dir, f"{world_dir_name}_backups")


def ensure_safe_backup_location(world_path):
    """Return the backup directory and reject dangerous in-world locations."""

    backups_dir = os.path.abspath(os.path.normpath(get_backups_dir(world_path)))
    world_dir = os.path.abspath(os.path.normpath(world_path))
    if _is_path_inside_or_same(backups_dir, world_dir):
        raise ValueError(
            "Backup-Ordner darf nicht innerhalb des Weltordners liegen. "
            "Bitte MCBE_BACKUP_ROOT auf einen externen Ordner setzen, sonst können "
            "Backups beim Restore mit gelöscht werden."
        )
    return backups_dir


def _retention_limits() -> dict[str, int | None]:
    config = load_config()
    return {
        RETENTION_ROLLING: config.max_backups_per_world,
        RETENTION_RECOVERY: config.max_pre_restore_backups_per_world,
        RETENTION_PINNED: None,
    }


def _normalized_path(path: str | os.PathLike) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(path)))


def _cleanup_stale_backup_artifacts(backups_dir: str, *, now: float | None = None) -> None:
    """Best-effort cleanup for abandoned temporary files older than one day."""

    if not os.path.isdir(backups_dir):
        return
    cutoff = (datetime.now().timestamp() if now is None else now) - STALE_BACKUP_ARTIFACT_SECONDS
    candidates = []
    try:
        candidates.extend(os.path.join(backups_dir, name) for name in os.listdir(backups_dir) if name.startswith(".mcbe_backup_") and name.endswith(".part"))
    except OSError:
        return
    restore_sources = os.path.join(backups_dir, ".restore_sources")
    if os.path.isdir(restore_sources) and not os.path.islink(restore_sources):
        with contextlib.suppress(OSError):
            candidates.extend(
                os.path.join(restore_sources, name) for name in os.listdir(restore_sources) if name.startswith("restore_source_") and name.endswith(".zip")
            )
    for path in candidates:
        try:
            stat_info = os.stat(path, follow_symlinks=False)
            if stat.S_ISREG(stat_info.st_mode) and stat_info.st_mtime < cutoff:
                os.remove(path)
        except OSError:
            continue


def _load_integrity_cache(backups_dir: str) -> dict:
    path = os.path.join(backups_dir, BACKUP_INTEGRITY_CACHE_FILENAME)
    try:
        with open(path, encoding="utf-8") as cache_file:
            payload = json.load(cache_file)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("schema_version") != BACKUP_INTEGRITY_CACHE_VERSION or not isinstance(payload.get("entries"), dict):
        return {}
    return payload["entries"]


def _write_integrity_cache(backups_dir: str, entries: dict) -> None:
    path = os.path.join(backups_dir, BACKUP_INTEGRITY_CACHE_FILENAME)
    fd = None
    temp_path = None
    try:
        fd, temp_path = tempfile.mkstemp(prefix=".backup_integrity_cache_", suffix=".tmp", dir=backups_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as cache_file:
            fd = None
            json.dump(
                {
                    "schema_version": BACKUP_INTEGRITY_CACHE_VERSION,
                    "entries": entries,
                },
                cache_file,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            cache_file.flush()
            os.fsync(cache_file.fileno())
        os.replace(temp_path, path)
        temp_path = None
    except OSError:
        LOGGER.warning("Backup-Integritätscache konnte nicht aktualisiert werden: %s", path, exc_info=True)
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        if temp_path is not None:
            with contextlib.suppress(OSError):
                os.remove(temp_path)


def _cached_integrity_is_valid(path: str, stat_info: os.stat_result, cache: dict, cache_dirty: list[bool]) -> bool:
    filename = os.path.basename(path)
    record = cache.get(filename)
    if (
        isinstance(record, dict)
        and record.get("size_bytes") == stat_info.st_size
        and record.get("mtime_ns") == stat_info.st_mtime_ns
        and record.get("ctime_ns") == stat_info.st_ctime_ns
    ):
        return record.get("crc_ok") is True
    try:
        _verify_zip_integrity(path)
        crc_ok = True
    except ValueError:
        crc_ok = False
    cache[filename] = {
        "size_bytes": stat_info.st_size,
        "mtime_ns": stat_info.st_mtime_ns,
        "ctime_ns": stat_info.st_ctime_ns,
        "crc_ok": crc_ok,
    }
    cache_dirty[0] = True
    return crc_ok


def _seed_verified_integrity_cache(backups_dir: str, path: str) -> None:
    """Record a just-verified published archive without reading it again."""

    try:
        stat_info = os.stat(path, follow_symlinks=False)
    except OSError:
        return
    cache = _load_integrity_cache(backups_dir)
    cache[os.path.basename(path)] = {
        "size_bytes": stat_info.st_size,
        "mtime_ns": stat_info.st_mtime_ns,
        "ctime_ns": stat_info.st_ctime_ns,
        "crc_ok": True,
    }
    _write_integrity_cache(backups_dir, cache)


@_world_locked
def prune_backups(world_path, keep_paths=None, *, retention_classes=None):
    limits = _retention_limits()
    target_classes = set(retention_classes or (RETENTION_ROLLING, RETENTION_RECOVERY))
    target_classes &= {RETENTION_ROLLING, RETENTION_RECOVERY}
    if not target_classes or all(limits[retention_class] is None for retention_class in target_classes):
        return
    backups_dir = ensure_safe_backup_location(world_path)
    if not os.path.isdir(backups_dir):
        return
    _cleanup_stale_backup_artifacts(backups_dir)
    keep = {_normalized_path(path) for path in (keep_paths or []) if path}
    integrity_cache = _load_integrity_cache(backups_dir)
    cache_dirty = [False]
    entries_by_class: dict[str, list[tuple[float, str]]] = {retention_class: [] for retention_class in target_classes}
    for filename in os.listdir(backups_dir):
        if not filename.lower().endswith(".zip"):
            continue
        file_path = os.path.join(backups_dir, filename)
        descriptor = _backup_file_descriptor(file_path, integrity_cache=integrity_cache, cache_dirty=cache_dirty)
        if descriptor is None:
            continue
        retention_class = descriptor["retention_class"]
        if retention_class not in target_classes:
            continue
        entries_by_class[retention_class].append((descriptor["sort_timestamp"], file_path))

    delete_candidates = []
    for retention_class, entries in entries_by_class.items():
        max_count = limits[retention_class]
        if max_count is None:
            continue
        entries.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        protected_entries = [entry for entry in entries if _normalized_path(entry[1]) in keep]
        unprotected_entries = [entry for entry in entries if _normalized_path(entry[1]) not in keep]
        kept_count = len(protected_entries)
        for _created_at, file_path in unprotected_entries:
            if kept_count < max_count:
                kept_count += 1
            else:
                delete_candidates.append(file_path)

    failures = []
    for old_file in delete_candidates:
        try:
            os.remove(old_file)
            if integrity_cache.pop(os.path.basename(old_file), None) is not None:
                cache_dirty[0] = True
        except OSError as exc:
            failures.append((old_file, exc))
    if cache_dirty[0]:
        _write_integrity_cache(backups_dir, integrity_cache)
    if failures:
        raise BackupRetentionError(failures)


def _verify_zip_integrity(zip_path):
    """Verify all member CRCs of a ZIP archive; raise ValueError on corruption."""

    try:
        with zipfile.ZipFile(zip_path, "r") as zipf:
            bad_member = zipf.testzip()
    except zipfile.BadZipFile as exc:
        raise ValueError("Backup-Datei ist keine gültige ZIP-Datei oder ist beschädigt.") from exc
    except OSError as exc:
        raise ValueError(t("Backup-Datei kann nicht gelesen werden: {error}", error=exc)) from exc
    if bad_member is not None:
        raise ValueError(t("Backup-Datei ist beschädigt (CRC-Fehler): {member}", member=bad_member))


def _ignore_symlink_names(directory, names):
    return [name for name in names if os.path.islink(os.path.join(directory, name))]


def _raise_walk_error(exc):
    if isinstance(exc, PermissionError):
        path = getattr(exc, "filename", None) or t("unbekannt")
        raise ValueError(
            t(
                "Backup abgebrochen: Ein Weltordner kann nicht durchsucht werden. "
                "Pfad: {path}. Bitte Minecraft/Server, Cloud-Sync, Antivirus oder andere Tools schließen.",
                path=path,
            )
        ) from exc
    raise exc


def _backup_target_path(backups_dir: str, display_name: str, timestamp: str, kind: str) -> str:
    """Return a high-entropy final name without creating a visible ZIP placeholder."""

    for _attempt in range(32):
        suffix = f"__{kind}__{timestamp}__{secrets.token_hex(8)}.zip"
        max_display_length = max(1, MAX_BACKUP_FILENAME_LENGTH - len(suffix))
        safe_display_name = _safe_backup_name(display_name)[:max_display_length].rstrip(" ._-") or "world"
        path = os.path.join(
            backups_dir,
            f"{safe_display_name}{suffix}",
        )
        if not os.path.lexists(path):
            return path
    raise RuntimeError("Kein freier Dateiname für das Backup verfügbar.")


def _publish_archive_no_clobber(temp_path: str, target_path: str) -> bool:
    """Publish one completed archive without replacing an existing target.

    A hard link gives POSIX and Windows local filesystems an atomic no-clobber
    publish.  Some mounted filesystems do not support hard links; there we copy
    into an exclusively created target.  Listing and retention reject incomplete
    ZIP files, so even a process crash during that fallback cannot turn a partial
    file into a usable backup.
    """

    try:
        os.link(temp_path, target_path)
    except FileExistsError:
        return False
    except OSError as exc:
        unsupported = {errno.EPERM, errno.EXDEV}
        for name in ("ENOTSUP", "EOPNOTSUPP"):
            value = getattr(errno, name, None)
            if value is not None:
                unsupported.add(value)
        if exc.errno not in unsupported:
            raise
        try:
            fd = os.open(target_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return False
        try:
            with os.fdopen(fd, "wb") as target, open(temp_path, "rb") as source:
                shutil.copyfileobj(source, target, length=1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
            _verify_zip_integrity(target_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(target_path)
            raise
    with contextlib.suppress(OSError):
        os.remove(temp_path)
    return True


def _backup_file_descriptor(path: str, *, integrity_cache=None, cache_dirty=None) -> dict | None:
    """Read cheap listing/retention metadata without streaming all ZIP members."""

    try:
        stat_info = os.stat(path, follow_symlinks=False)
        if os.path.islink(path) or not stat.S_ISREG(stat_info.st_mode) or stat_info.st_size <= 0:
            return None
        with zipfile.ZipFile(path, "r") as zipf:
            # Parsing the central directory proves that publication completed.
            # CRC validation remains mandatory after creation and before restore,
            # but is intentionally not repeated for every list/retention scan.
            zipf.infolist()
            metadata = _read_backup_metadata(zipf, os.path.basename(path))
        if integrity_cache is not None and cache_dirty is not None:
            # Every archive, including one carrying valid-looking metadata, must
            # have passed a complete CRC scan. App-created backups seed this
            # cache immediately after their verified atomic publication; copied
            # or changed archives are scanned once and then reused by identity.
            if not _cached_integrity_is_valid(path, stat_info, integrity_cache, cache_dirty):
                return None
        else:
            _verify_zip_integrity(path)
    except (OSError, ValueError, zipfile.BadZipFile):
        return None

    created_at = _parse_created_at(metadata.get("created_at"))
    sort_timestamp = created_at.timestamp() if created_at is not None else stat_info.st_mtime
    return {
        "path": path,
        "filename": os.path.basename(path),
        "size_bytes": stat_info.st_size,
        "mtime": stat_info.st_mtime,
        "created_at": created_at,
        "sort_timestamp": sort_timestamp,
        "kind": metadata["kind"],
        "kind_label": BACKUP_KIND_LABELS[metadata["kind"]],
        "retention_class": metadata["retention_class"],
        "restore_source": metadata.get("restore_source"),
        "schema_version": metadata.get("schema_version", 0),
    }


def _is_complete_backup_file(path: str) -> bool:
    return _backup_file_descriptor(path) is not None


@_world_locked
def create_backup(world_path, *, prune_after=True, backup_kind=BACKUP_KIND_AUTOMATIC, restore_source=None):
    if not os.path.exists(world_path):
        raise FileNotFoundError("Welt-Ordner existiert nicht.")

    backup_kind = _normalize_backup_kind(backup_kind)
    backups_dir = ensure_safe_backup_location(world_path)
    os.makedirs(backups_dir, exist_ok=True)
    _cleanup_stale_backup_artifacts(backups_dir)

    created_at = _utc_now()
    timestamp = created_at.strftime("%Y%m%dT%H%M%SZ")
    display_name = _safe_backup_name(get_world_name(world_path))
    metadata = _backup_metadata(
        world_path,
        kind=backup_kind,
        created_at=created_at,
        restore_source=restore_source,
    )
    backups_dir_normalized = os.path.normpath(os.path.abspath(backups_dir))

    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".mcbe_backup_", suffix=".part", dir=backups_dir)
        os.close(fd)
    except PermissionError as exc:
        raise ValueError(f"Backup abgebrochen: Der Backup-Ordner ist nicht beschreibbar. Pfad: {backups_dir}.") from exc

    backup_zip_path = None
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(world_path, onerror=_raise_walk_error):
                root_abs = os.path.normpath(os.path.abspath(root))
                if _is_path_inside_or_same(root_abs, backups_dir_normalized):
                    dirs[:] = []
                    continue
                dirs[:] = [
                    d for d in dirs if not os.path.islink(os.path.join(root, d)) and not _is_path_inside_or_same(os.path.join(root, d), backups_dir_normalized)
                ]
                for dirname in dirs:
                    dir_path = os.path.join(root, dirname)
                    arcname = os.path.relpath(dir_path, world_path).replace(os.sep, "/").rstrip("/") + "/"
                    try:
                        zipf.write(dir_path, arcname)
                    except PermissionError as exc:
                        raise ValueError(
                            t(
                                "Backup abgebrochen: Ein Weltordner kann nicht gelesen werden. "
                                "Pfad: {path}. Bitte Minecraft/Server, Cloud-Sync, Antivirus oder andere Tools schließen.",
                                path=dir_path,
                            )
                        ) from exc
                    except FileNotFoundError as exc:
                        raise ValueError(
                            "Backup abgebrochen: Weltordner ist während der Sicherung verschwunden. "
                            "Bitte Minecraft/Server vollständig stoppen und erneut speichern."
                        ) from exc
                for file in files:
                    file_path = os.path.join(root, file)
                    if os.path.islink(file_path) or _is_path_inside_or_same(file_path, backups_dir_normalized):
                        continue
                    arcname = os.path.relpath(file_path, world_path)
                    try:
                        zipf.write(file_path, arcname)
                    except PermissionError as exc:
                        raise ValueError(
                            t(
                                "Backup abgebrochen: Eine Weltdatei kann nicht gelesen werden. "
                                "Pfad: {path}. Bitte Minecraft/Server, Cloud-Sync, Antivirus oder andere Tools schließen.",
                                path=file_path,
                            )
                        ) from exc
                    except FileNotFoundError as exc:
                        raise ValueError(
                            "Backup abgebrochen: Weltdatei ist während der Sicherung verschwunden. "
                            "Bitte Minecraft/Server vollständig stoppen und erneut speichern."
                        ) from exc
            zipf.comment = _metadata_comment(metadata)

        _verify_zip_integrity(tmp_path)
        for _attempt in range(32):
            candidate = _backup_target_path(backups_dir, display_name, timestamp, backup_kind)
            try:
                published = _publish_archive_no_clobber(tmp_path, candidate)
            except PermissionError as exc:
                raise ValueError(f"Backup abgebrochen: Die fertige Backup-ZIP kann nicht im Backup-Ordner abgelegt werden. Pfad: {candidate}.") from exc
            if published:
                backup_zip_path = candidate
                break
        if backup_zip_path is None:
            raise RuntimeError("Backup konnte nicht kollisionsfrei veröffentlicht werden.")
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            LOGGER.exception("Temporäre Backup-Datei konnte nach einem Fehler nicht entfernt werden: %s", tmp_path)
        raise

    _seed_verified_integrity_cache(backups_dir, backup_zip_path)

    if prune_after:
        retention_class = _retention_class_for_kind(backup_kind)
        if retention_class != RETENTION_PINNED:
            prune_backups(world_path, keep_paths=[backup_zip_path], retention_classes=[retention_class])
    return backup_zip_path


def _validate_backup_path_for_world(world_path, backup_path):
    backups_dir = os.path.abspath(ensure_safe_backup_location(world_path))
    candidate = os.path.abspath(os.path.normpath(backup_path))
    if os.path.commonpath([backups_dir, candidate]) != backups_dir:
        raise ValueError("Backup-Datei liegt außerhalb des Backup-Ordners.")
    if not candidate.lower().endswith(".zip"):
        raise ValueError("Backup-Datei muss eine ZIP-Datei sein.")
    if os.path.islink(candidate):
        raise ValueError("Backup-Datei darf kein Symlink sein.")
    real_candidate = os.path.realpath(candidate)
    real_backups_dir = os.path.realpath(backups_dir)
    if os.path.commonpath([real_backups_dir, real_candidate]) != real_backups_dir:
        raise ValueError("Backup-Datei liegt real außerhalb des Backup-Ordners.")
    return candidate


def resolve_backup_path(world_path, backup_file):
    if not isinstance(backup_file, str) or not backup_file:
        raise ValueError("Ungültiger Backup-Dateiname.")
    # Treat both POSIX and Windows separators as path separators on every host.
    # Otherwise ``..\outside.zip`` is a plain filename on Linux and can bypass
    # the basename check while still being interpreted as traversal by Windows
    # clients/tools.
    if any(sep in backup_file for sep in ("/", "\\")) or backup_file in {".", ".."}:
        raise ValueError("Ungültiger Backup-Dateiname.")

    backups_dir = os.path.abspath(ensure_safe_backup_location(world_path))
    return _validate_backup_path_for_world(world_path, os.path.join(backups_dir, backup_file))


@_world_locked
def delete_backup(world_path, backup_file):
    backup_path = resolve_backup_path(world_path, backup_file)
    try:
        stat_info = os.stat(backup_path, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise FileNotFoundError("Backup-Datei existiert nicht.") from exc
    if not stat.S_ISREG(stat_info.st_mode):
        raise ValueError("Backup-Datei ist keine reguläre Datei.")
    os.remove(backup_path)
    backups_dir = ensure_safe_backup_location(world_path)
    integrity_cache = _load_integrity_cache(backups_dir)
    if integrity_cache.pop(os.path.basename(backup_path), None) is not None:
        _write_integrity_cache(backups_dir, integrity_cache)
    return backup_path


def _restore_world_id(world_path):
    normalized = os.path.normcase(os.path.realpath(os.path.abspath(os.path.normpath(world_path))))
    return hashlib.sha256(normalized.encode("utf-8", errors="surrogatepass")).hexdigest()


def _restore_token(world_path, backup_path, *, size_bytes, sha256):
    return {
        "version": RESTORE_TOKEN_VERSION,
        "world_id": _restore_world_id(world_path),
        "filename": os.path.basename(backup_path),
        "size_bytes": size_bytes,
        "sha256": sha256,
    }


def _validated_restore_token(token):
    if not isinstance(token, dict):
        raise ValueError("Restore abgelehnt: Die Restore-Vorschau fehlt oder ist veraltet. Bitte Vorschau neu laden.")
    version = token.get("version")
    world_id = token.get("world_id")
    filename = token.get("filename")
    size_bytes = token.get("size_bytes")
    sha256 = token.get("sha256")
    if version != RESTORE_TOKEN_VERSION:
        raise ValueError("Restore abgelehnt: Die Restore-Vorschau hat ein unbekanntes Format. Bitte Vorschau neu laden.")
    if not isinstance(world_id, str) or len(world_id) != 64 or any(ch not in "0123456789abcdef" for ch in world_id):
        raise ValueError("Restore abgelehnt: Die Restore-Vorschau ist ungültig. Bitte Vorschau neu laden.")
    if not isinstance(filename, str) or not filename:
        raise ValueError("Restore abgelehnt: Die Restore-Vorschau ist ungültig. Bitte Vorschau neu laden.")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
        raise ValueError("Restore abgelehnt: Die Restore-Vorschau ist ungültig. Bitte Vorschau neu laden.")
    if not isinstance(sha256, str) or len(sha256) != 64 or any(ch not in "0123456789abcdef" for ch in sha256):
        raise ValueError("Restore abgelehnt: Die Restore-Vorschau ist ungültig. Bitte Vorschau neu laden.")
    return {
        "version": version,
        "world_id": world_id,
        "filename": filename,
        "size_bytes": size_bytes,
        "sha256": sha256,
    }


@_world_locked
def snapshot_backup_for_restore(world_path, backup_path, *, expected_token=None):
    """Copy the selected backup to a private immutable restore source.

    The source is opened once after path validation.  Later restore work reads
    only the private snapshot, so replacing the user-visible ZIP while the
    pre-restore backup is being created cannot change what gets restored.
    """

    source_path = _validate_backup_path_for_world(world_path, backup_path)
    normalized_token = _validated_restore_token(expected_token) if expected_token is not None else None
    if normalized_token is not None:
        if not secrets.compare_digest(normalized_token["world_id"], _restore_world_id(world_path)):
            raise ValueError("Restore abgelehnt: Die ausgewählte Welt wurde seit der Vorschau gewechselt. Bitte Vorschau neu laden.")
        if normalized_token["filename"] != os.path.basename(source_path):
            raise ValueError("Restore abgelehnt: Das ausgewählte Backup stimmt nicht mehr mit der Vorschau überein. Bitte Vorschau neu laden.")
    source_stat = os.stat(source_path, follow_symlinks=False)
    if not stat.S_ISREG(source_stat.st_mode):
        raise ValueError("Backup-Datei ist keine reguläre Datei.")
    backups_dir = os.path.abspath(ensure_safe_backup_location(world_path))
    snapshot_dir = os.path.join(backups_dir, ".restore_sources")
    os.makedirs(snapshot_dir, exist_ok=True)
    if os.path.islink(snapshot_dir) or not _is_path_inside_or_same(snapshot_dir, backups_dir):
        raise ValueError("Temporärer Restore-Ordner ist unsicher.")
    fd, snapshot_path = tempfile.mkstemp(prefix="restore_source_", suffix=".zip", dir=snapshot_dir)
    try:
        with open(source_path, "rb") as source, os.fdopen(fd, "wb") as snapshot:
            # fdopen owns and closes the descriptor from this point onward.
            # Invalidate our raw handle before any operation in the with-body can
            # fail, so cleanup can never close a descriptor number reused elsewhere.
            fd = -1
            if not os.path.samestat(source_stat, os.fstat(source.fileno())):
                raise ValueError("Backup-Datei wurde während der Restore-Vorbereitung ersetzt.")
            digest = hashlib.sha256()
            size_bytes = 0
            while chunk := source.read(1024 * 1024):
                snapshot.write(chunk)
                digest.update(chunk)
                size_bytes += len(chunk)
            snapshot.flush()
            os.fsync(snapshot.fileno())
        actual_token = _restore_token(
            world_path,
            source_path,
            size_bytes=size_bytes,
            sha256=digest.hexdigest(),
        )
        if normalized_token is not None and (
            normalized_token["size_bytes"] != actual_token["size_bytes"] or not secrets.compare_digest(normalized_token["sha256"], actual_token["sha256"])
        ):
            raise ValueError("Restore abgelehnt: Die Backup-Datei wurde seit der Vorschau verändert. Bitte Vorschau neu laden.")
        _verify_zip_integrity(snapshot_path)
        return snapshot_path
    except Exception as exc:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        try:
            os.remove(snapshot_path)
        except OSError as cleanup_exc:
            warning = t("Temporärer Restore-Snapshot konnte nicht entfernt werden: {path} ({error})", path=snapshot_path, error=cleanup_exc)
            existing = getattr(exc, "cleanup_warning", None)
            exc.cleanup_warning = f"{existing} {warning}" if existing else warning
            exc.source_snapshot_path = snapshot_path
            LOGGER.exception("Temporärer Restore-Snapshot konnte nach einem Fehler nicht entfernt werden: %s", snapshot_path)
        raise


def _safe_zip_member_name(name: str) -> str:
    if not name or "\0" in name or "\\" in name:
        raise ValueError(f"Unsicherer Pfad im Backup: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"Unsicherer Pfad im Backup: {name}")
    return str(path)


def validate_zip_members(zipf, target_dir):
    target_dir = os.path.abspath(target_dir)
    total_uncompressed = 0
    seen_names = set()
    for i, member in enumerate(zipf.infolist()):
        if i >= MAX_BACKUP_MEMBERS:
            raise ValueError(t("Backup enthält zu viele Dateien (max {limit}).", limit=MAX_BACKUP_MEMBERS))
        safe_name = _safe_zip_member_name(member.filename)
        if member.flag_bits & 0x1:
            raise ValueError("Verschlüsselte Backup-ZIP-Einträge werden nicht unterstützt.")
        member_target = os.path.abspath(os.path.join(target_dir, *PurePosixPath(safe_name).parts))
        if os.path.commonpath([target_dir, member_target]) != target_dir:
            raise ValueError(f"Unsicherer Pfad im Backup: {member.filename}")
        norm_name = os.path.normcase(os.path.normpath(safe_name))
        if norm_name in seen_names:
            raise ValueError(f"Doppelter Eintrag im Backup: {member.filename}")
        seen_names.add(norm_name)
        total_uncompressed += member.file_size
        if total_uncompressed > MAX_BACKUP_UNCOMPRESSED_MB * 1024 * 1024:
            raise ValueError(t("Backup überschreitet maximal {limit} MB unkomprimiert.", limit=MAX_BACKUP_UNCOMPRESSED_MB))


def safe_extract_zip(zipf, target_dir):
    validate_zip_members(zipf, target_dir)
    target_dir = os.path.abspath(target_dir)
    for member in zipf.infolist():
        safe_name = _safe_zip_member_name(member.filename)
        target_path = os.path.abspath(os.path.join(target_dir, *PurePosixPath(safe_name).parts))
        if member.is_dir():
            os.makedirs(target_path, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with zipf.open(member, "r") as src, open(target_path, "wb") as dst:
            shutil.copyfileobj(src, dst)


@_world_locked
def list_backups(world_path):
    backups_dir = ensure_safe_backup_location(world_path)
    backups_list = []

    if os.path.exists(backups_dir):
        _cleanup_stale_backup_artifacts(backups_dir)
        integrity_cache = _load_integrity_cache(backups_dir)
        cache_dirty = [False]
        for file in os.listdir(backups_dir):
            if not file.lower().endswith(".zip"):
                continue
            file_path = os.path.join(backups_dir, file)
            descriptor = _backup_file_descriptor(file_path, integrity_cache=integrity_cache, cache_dirty=cache_dirty)
            if descriptor is None:
                continue
            created_at = descriptor["created_at"]
            modified_at = _utc_datetime_from_timestamp(descriptor["mtime"])
            display_datetime = _backup_display_datetime(created_at or modified_at)
            backups_list.append(
                {
                    "filename": file,
                    "size_mb": round(descriptor["size_bytes"] / (1024 * 1024), 2),
                    "date": display_datetime,
                    "created_at": _metadata_created_at(created_at) if created_at is not None else None,
                    "modified_at": _metadata_created_at(modified_at) if modified_at is not None else None,
                    "kind": descriptor["kind"],
                    "kind_label": descriptor["kind_label"],
                    "retention_class": descriptor["retention_class"],
                    "restore_source": descriptor["restore_source"],
                    "sort_timestamp": descriptor["sort_timestamp"],
                }
            )
        if cache_dirty[0]:
            _write_integrity_cache(backups_dir, integrity_cache)

    backups_list.sort(key=lambda x: (x["sort_timestamp"], x["filename"]), reverse=True)
    for entry in backups_list:
        entry.pop("sort_timestamp", None)
    return backups_list


@_world_locked
def preview_backup(world_path, backup_file):
    """Return a safe, non-mutating preview for a restore candidate."""
    backup_zip_path = resolve_backup_path(world_path, backup_file)
    if not os.path.exists(backup_zip_path):
        raise FileNotFoundError("Backup-Datei existiert nicht.")

    stat_info = os.stat(backup_zip_path, follow_symlinks=False)
    if not stat.S_ISREG(stat_info.st_mode):
        raise ValueError("Backup-Datei ist keine reguläre Datei.")
    try:
        with open(backup_zip_path, "rb") as source:
            if not os.path.samestat(stat_info, os.fstat(source.fileno())):
                raise ValueError("Backup-Datei wurde während der Vorschau ersetzt.")
            digest = hashlib.sha256()
            size_bytes = 0
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size_bytes += len(chunk)
            source.seek(0)
            # Die Vorschau ist die Sicherheitsentscheidung vor der Bestätigung.
            # Deshalb muss sie denselben vollständigen CRC-Check wie der eigentliche
            # Restore durchführen und nicht nur die wenigen angezeigten Mitglieder
            # lesen. Das offene Handle bindet die Prüfung an dieselbe Dateiidentität.
            _verify_zip_integrity(source)
            source.seek(0)
            with zipfile.ZipFile(source, "r") as zipf:
                metadata = _read_backup_metadata(zipf, os.path.basename(backup_zip_path))
                validate_zip_members(zipf, world_path)
                infos = zipf.infolist()
                file_count = sum(1 for member in infos if not member.is_dir())
                dir_count = sum(1 for member in infos if member.is_dir())
                total_uncompressed = sum(member.file_size for member in infos)
                top_level = sorted({PurePosixPath(member.filename).parts[0] for member in infos if PurePosixPath(member.filename).parts})[:20]
                has_db = any(member.filename == "db/" or member.filename.startswith("db/") for member in infos)
                levelname = None
                for candidate in ("levelname.txt", "world_icon.jpeg"):
                    if candidate in zipf.namelist():
                        if candidate == "levelname.txt":
                            try:
                                with zipf.open(candidate, "r") as levelname_file:
                                    levelname = levelname_file.read(2048).decode("utf-8", errors="replace").strip()[:160]
                            except (OSError, UnicodeDecodeError):
                                levelname = None
                        break
    except zipfile.BadZipFile as exc:
        raise ValueError("Backup-Datei ist keine gültige ZIP-Datei oder ist beschädigt.") from exc

    created_at = _parse_created_at(metadata.get("created_at"))
    modified_at = _utc_datetime_from_timestamp(stat_info.st_mtime)
    displayed_timestamp = _backup_display_datetime(created_at or modified_at)

    return {
        "success": True,
        "backup_token": _restore_token(
            world_path,
            backup_zip_path,
            size_bytes=size_bytes,
            sha256=digest.hexdigest(),
        ),
        "backup": {
            "filename": os.path.basename(backup_zip_path),
            "size_mb": round(stat_info.st_size / (1024 * 1024), 2),
            "modified": displayed_timestamp,
            "created_at": _metadata_created_at(created_at) if created_at is not None else None,
            "modified_at": _metadata_created_at(modified_at) if modified_at is not None else None,
            "kind": metadata["kind"],
            "kind_label": BACKUP_KIND_LABELS[metadata["kind"]],
            "retention_class": metadata["retention_class"],
            "restore_source": metadata.get("restore_source"),
            "uncompressed_mb": round(total_uncompressed / (1024 * 1024), 2),
            "file_count": file_count,
            "dir_count": dir_count,
            "has_db": has_db,
            "levelname": levelname,
            "top_level_entries": top_level,
        },
        "target_world": {
            "name": get_world_name(world_path),
            "folder": os.path.basename(os.path.normpath(world_path)),
        },
        "effects": [
            "Aktuelle Welt wird vor dem Restore automatisch erneut gesichert.",
            "Dateien der Zielwelt werden durch den Backup-Inhalt ersetzt.",
            "Ungespeicherte UI-Änderungen gehen verloren.",
        ],
    }


@_world_locked
def restore_backup(world_path, backup_file, *, resolved_backup_path=None, pre_restore_check=None):
    # Service-level restore first resolves the selected backup, then creates a
    # pre-restore safety backup.  Accepting that pre-resolved path avoids a
    # second filename lookup afterwards, so an external file swap cannot make us
    # restore a different ZIP with the same basename between those two steps.
    backup_zip_path = (
        _validate_backup_path_for_world(world_path, resolved_backup_path) if resolved_backup_path is not None else resolve_backup_path(world_path, backup_file)
    )
    if not os.path.exists(backup_zip_path):
        raise FileNotFoundError("Backup-Datei existiert nicht.")

    parent_dir = os.path.dirname(os.path.normpath(world_path))
    world_dir_name = os.path.basename(os.path.normpath(world_path))
    transaction_id = secrets.token_hex(8)
    temp_restore_dir = tempfile.mkdtemp(prefix=f".{world_dir_name}_restoring_", dir=parent_dir)
    rollback_dir = os.path.join(
        parent_dir,
        f".{world_dir_name}_rollback_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S-%f')}_{transaction_id}",
    )
    transaction_journal = None
    transaction_resolved = False
    cleanup_warnings = []
    restore_committed = False
    operation_error = None

    try:
        _verify_zip_integrity(backup_zip_path)
        try:
            with zipfile.ZipFile(backup_zip_path, "r") as zipf:
                safe_extract_zip(zipf, temp_restore_dir)
        except zipfile.BadZipFile as exc:
            raise ValueError("Backup-Datei ist keine gültige ZIP-Datei oder ist beschädigt.") from exc

        if not os.path.isdir(os.path.join(temp_restore_dir, "db")):
            raise ValueError("Backup enthält keinen gültigen Bedrock-db-Ordner.")

        if pre_restore_check:
            pre_restore_check()
        transaction_journal = _write_restore_transaction(
            parent_dir,
            world_dir_name,
            rollback_dir,
            temp_restore_dir,
            transaction_id,
        )
        try:
            os.replace(world_path, rollback_dir)
            _fsync_directory(parent_dir)
        except Exception:
            # A failing os.replace leaves the original world in place, but the
            # following directory fsync can fail after the rename completed.
            # Only discard the journal when the filesystem still proves that
            # no rollback state was created.
            transaction_resolved = os.path.lexists(world_path) and not os.path.lexists(rollback_dir)
            raise
        try:
            os.replace(temp_restore_dir, world_path)
            _fsync_directory(parent_dir)
            restore_committed = True
            transaction_resolved = True
        except Exception as exc:
            if not os.path.exists(world_path):
                try:
                    os.replace(rollback_dir, world_path)
                    _fsync_directory(parent_dir)
                    transaction_resolved = True
                except OSError as rollback_exc:
                    raise RuntimeError(
                        t(
                            "Restore fehlgeschlagen. Die Originalwelt wurde nicht gelöscht, konnte aber nicht automatisch zurückgeschoben werden: {path}",
                            path=rollback_dir,
                        )
                    ) from rollback_exc
            raise exc

        try:
            shutil.rmtree(rollback_dir)
            _fsync_directory(parent_dir)
        except OSError as exc:
            cleanup_warnings.append(
                t("Die vorherige Weltkopie konnte nicht entfernt werden und blieb unter {path} zurück: {error}", path=rollback_dir, error=exc)
            )
            LOGGER.exception("Rollback-Verzeichnis blieb nach erfolgreichem Restore zurück: %s", rollback_dir)
    except Exception as exc:
        operation_error = exc
        raise
    finally:
        unresolved_transaction = bool(transaction_journal and not transaction_resolved)
        if os.path.exists(temp_restore_dir) and not unresolved_transaction:
            try:
                shutil.rmtree(temp_restore_dir)
            except OSError as exc:
                warning = t(
                    "Der temporäre Restore-Ordner konnte nicht entfernt werden und blieb unter {path} zurück: {error}", path=temp_restore_dir, error=exc
                )
                if restore_committed:
                    cleanup_warnings.append(warning)
                    LOGGER.exception("Temporärer Restore-Ordner blieb nach erfolgreichem Restore zurück: %s", temp_restore_dir)
                else:
                    if operation_error is not None:
                        existing = getattr(operation_error, "cleanup_warning", None)
                        operation_error.cleanup_warning = f"{existing} {warning}" if existing else warning
                        operation_error.temp_restore_path = temp_restore_dir
                    LOGGER.exception("Temporärer Restore-Ordner konnte nach fehlgeschlagenem Restore nicht entfernt werden: %s", temp_restore_dir)
        elif os.path.exists(temp_restore_dir) and unresolved_transaction:
            warning = t(
                "Die Restore-Transaktion ist noch nicht eindeutig abgeschlossen. "
                "Der Staging-Ordner bleibt für die sichere Wiederaufnahme beim nächsten beschreibbaren Start erhalten: {path}",
                path=temp_restore_dir,
            )
            if operation_error is not None:
                existing = getattr(operation_error, "cleanup_warning", None)
                operation_error.cleanup_warning = f"{existing} {warning}" if existing else warning
                operation_error.temp_restore_path = temp_restore_dir
            LOGGER.warning("Restore-Staging bleibt für die Transaktionswiederaufnahme erhalten: %s", temp_restore_dir)

        if transaction_journal and transaction_resolved and os.path.exists(transaction_journal):
            try:
                _remove_restore_transaction(transaction_journal)
            except OSError as exc:
                warning = t(
                    "Der Restore-Transaktionsmarker konnte nicht entfernt werden und wird beim nächsten Start erneut geprüft: {path}: {error}",
                    path=transaction_journal,
                    error=exc,
                )
                if restore_committed:
                    cleanup_warnings.append(warning)
                elif operation_error is not None:
                    existing = getattr(operation_error, "cleanup_warning", None)
                    operation_error.cleanup_warning = f"{existing} {warning}" if existing else warning
                LOGGER.exception("Restore-Transaktionsmarker konnte nicht entfernt werden: %s", transaction_journal)

    return cleanup_warnings
