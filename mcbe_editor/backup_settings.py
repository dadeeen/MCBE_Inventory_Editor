"""Persistent installation-wide backup size policy with an operator override."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypedDict

from .config import load_config
from .i18n import t
from .runtime_data import atomic_write_private_text
from .world_locks import locked_operation

BACKUP_LIMIT_ENV = "MCBE_BACKUP_MAX_UNCOMPRESSED_MIB"
MAX_CONFIGURED_MIB = 1024 * 1024


class BackupSettings(TypedDict):
    max_uncompressed_mib: int
    source: str
    editable: bool


class BackupLimitError(ValueError):
    """The configured uncompressed size limit prevents a backup or restore."""


def _validated_limit(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_CONFIGURED_MIB:
        raise ValueError(t("Das Backup-Limit muss eine ganze Zahl zwischen 1 und {max} MiB sein.", max=MAX_CONFIGURED_MIB))
    return value


def _settings_path() -> Path:
    data_root = load_config().data_root
    if data_root is None:
        raise ValueError("Datenverzeichnis für Backup-Einstellungen fehlt.")
    return Path(data_root) / "backup_settings.json"


def get_backup_settings(*, default_mib: int = 1024) -> BackupSettings:
    configured = os.environ.get(BACKUP_LIMIT_ENV, "").strip()
    source = "default"
    limit = default_mib
    if configured:
        try:
            limit = _validated_limit(int(configured))
        except ValueError as exc:
            raise ValueError(t("Die Vorgabe {name} ist ungültig: {error}", name=BACKUP_LIMIT_ENV, error=str(exc))) from exc
        source = "environment"
    else:
        try:
            with _settings_path().open(encoding="utf-8") as handle:
                payload = json.loads(handle.read(8193))
            limit = _validated_limit(payload.get("max_uncompressed_mib") if isinstance(payload, dict) else None)
            source = "saved"
        except FileNotFoundError:
            pass
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise ValueError(t("Die gespeicherten Backup-Einstellungen sind ungültig. Bitte im Backup-Manager neu speichern.")) from exc
    return {
        "max_uncompressed_mib": limit,
        "source": source,
        "editable": source != "environment" and not load_config().read_only,
    }


def save_backup_settings(value: object) -> BackupSettings:
    value = _validated_limit(value)
    if os.environ.get(BACKUP_LIMIT_ENV, "").strip():
        raise PermissionError(t("Das Backup-Limit wird über {name} vom Betreiber vorgegeben.", name=BACKUP_LIMIT_ENV))
    if load_config().read_only:
        raise PermissionError(t("Read-Only-Modus: Backup-Einstellungen können nicht geändert werden."))
    path = _settings_path()
    with locked_operation("backup-settings", root=path.parent):
        atomic_write_private_text(path, json.dumps({"max_uncompressed_mib": value}, indent=2) + "\n")
    return get_backup_settings()
