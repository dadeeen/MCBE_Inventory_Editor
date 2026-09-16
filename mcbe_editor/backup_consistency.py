"""Shared source-stability checks for every complete world backup."""

from __future__ import annotations

import hashlib
import os
import stat

from .i18n import t


class BackupSourceChangedError(ValueError):
    """The source changed before a recovery archive could be accepted."""


def source_snapshot(world_path: str) -> str:
    """Return a deterministic metadata snapshot of the world tree.

    Detect changes during backup creation without opening the database. This
    compares metadata, not file contents, and does not make a running world an
    atomic snapshot. Minecraft and the server must still be stopped.
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
