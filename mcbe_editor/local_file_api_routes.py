"""Handlers for local folder/file picker API routes."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .api_errors import error_payload
from .i18n import t


@dataclass(frozen=True)
class LocalFileRouteDeps:
    app_config: Any
    service: Any
    jsonify: Callable[..., Any]
    api_error: Callable[..., Any]
    log_api_exception: Callable[[str, Exception], None]
    json_string: Callable[..., str]
    audit_event: Callable[..., None]
    ensure_valid_world_path: Callable[[str], Any]
    get_configured_scan_roots: Callable[..., list[dict]]
    get_minecraft_saves_dir: Callable[[], Any]
    player_export_dir_for_world: Callable[[str], Any]
    gui_picker_lock: Any
    select_folder: Callable[..., str | None]
    select_player_export: Callable[..., str | None]


def _open_folder_in_file_manager(path: str) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _openable_local_folder(path: str, deps: LocalFileRouteDeps) -> str:
    if deps.app_config.is_docker:
        raise ValueError("Ordner öffnen ist im Docker-/LAN-Modus deaktiviert. Kopiere stattdessen den Containerpfad.")
    if not path:
        raise ValueError("Kein Pfad angegeben.")
    candidate = Path(path).expanduser().resolve()
    if not candidate.exists():
        raise ValueError(f"Pfad existiert nicht: {candidate}")
    if not candidate.is_dir():
        raise ValueError("Nur Ordner können geöffnet werden.")

    # Prefer explicit world folders. This also protects against opening broad
    # arbitrary system paths through the browser API.
    try:
        deps.ensure_valid_world_path(str(candidate))
        return str(candidate)
    except ValueError:
        pass

    roots = deps.get_configured_scan_roots(include_disabled=True)
    for root in roots:
        root_path = root.get("path")
        if root_path:
            try:
                if Path(root_path).expanduser().resolve() == candidate:
                    return str(candidate)
            except OSError:
                continue
    raise ValueError("Dieser Ordner ist kein direkter Weltordner und kein bekannter Suchbereich.")


def _openable_backup_folder_for_world(world_path: str, deps: LocalFileRouteDeps) -> str:
    if deps.app_config.is_docker:
        raise ValueError("Backupordner öffnen ist im Docker-/LAN-Modus deaktiviert. Kopiere stattdessen den Containerpfad.")
    deps.ensure_valid_world_path(world_path)
    backup_dir = Path(deps.service.list_backups(world_path).get("backup_dir") or "").expanduser().resolve()
    if not backup_dir.exists():
        raise ValueError(f"Backupordner existiert noch nicht: {backup_dir}")
    if not backup_dir.is_dir():
        raise ValueError("Der konfigurierte Backup-Pfad ist kein Ordner.")
    return str(backup_dir)


def _player_export_dir_for_opening(world_path: str, deps: LocalFileRouteDeps) -> str:
    if deps.app_config.is_docker:
        raise ValueError("Exportordner öffnen ist im Docker-/LAN-Modus deaktiviert. Kopiere stattdessen den Containerpfad aus der Exportmeldung.")
    deps.ensure_valid_world_path(world_path)
    export_dir = Path(deps.player_export_dir_for_world(world_path)).expanduser().resolve()
    export_dir.mkdir(parents=True, exist_ok=True)
    if not export_dir.is_dir():
        raise ValueError("Der konfigurierte Export-Pfad ist kein Ordner.")
    return str(export_dir)


def open_backup_folder(data: dict, deps: LocalFileRouteDeps):
    try:
        path = _openable_backup_folder_for_world(deps.json_string(data, "world_path"), deps)
        _open_folder_in_file_manager(path)
        deps.audit_event("backup.folder_open", "success", world_path=data.get("world_path"), details={"path": path})
        return deps.jsonify({"success": True, "path": path})
    except ValueError as exc:
        return deps.api_error(str(exc), 400)
    except Exception as exc:
        deps.log_api_exception("backup.folder_open", exc)
        return deps.api_error(t("Backupordner konnte nicht geöffnet werden: {error}", error=t(str(exc))), 500)


def open_player_export_folder(data: dict, deps: LocalFileRouteDeps):
    try:
        path = _player_export_dir_for_opening(deps.json_string(data, "world_path"), deps)
        _open_folder_in_file_manager(path)
        deps.audit_event("player_export.folder_open", "success", world_path=data.get("world_path"), details={"path": path})
        return deps.jsonify({"success": True, "path": path})
    except ValueError as exc:
        return deps.api_error(str(exc), 400)
    except Exception as exc:
        deps.log_api_exception("player_export.folder_open", exc)
        return deps.api_error(t("Exportordner konnte nicht geöffnet werden: {error}", error=t(str(exc))), 500)


def open_folder(data: dict, deps: LocalFileRouteDeps):
    try:
        path = _openable_local_folder(deps.json_string(data, "path"), deps)
        _open_folder_in_file_manager(path)
        deps.audit_event("folder.open", "success", details={"path": path})
        return deps.jsonify({"success": True})
    except ValueError as exc:
        return deps.api_error(str(exc), 400)
    except Exception as exc:
        deps.log_api_exception("folder.open", exc)
        return deps.api_error(t("Ordner konnte nicht geöffnet werden: {error}", error=t(str(exc))), 500)


def pick_folder(deps: LocalFileRouteDeps):
    if deps.app_config.is_docker:
        return deps.api_error("Ordnerauswahl ist im Docker/LAN-Modus deaktiviert. Bitte /worlds-Bind-Mount oder manuellen Pfad verwenden.", 400)
    if not deps.gui_picker_lock.acquire(blocking=False):
        return deps.jsonify(error_payload("Ein Dateiauswahl-Dialog ist bereits geöffnet.", code="dialog_already_open")), 409
    try:
        initial_dir = str(deps.get_minecraft_saves_dir() or deps.app_config.worlds_root or "")
        path = deps.select_folder(initial_dir=initial_dir)
        if not path:
            return deps.jsonify(error_payload("Kein Ordner ausgewählt.", code="folder_selection_cancelled")), 400
        return deps.jsonify({"success": True, "path": path})
    except Exception as exc:
        deps.log_api_exception("folder.pick", exc)
        return deps.api_error(t("Fehler bei der Ordnerauswahl: {error}", error=t(str(exc))), 500)
    finally:
        deps.gui_picker_lock.release()


def pick_player_export(data: dict, deps: LocalFileRouteDeps):
    if deps.app_config.is_docker:
        return deps.api_error("Dateiauswahl ist im Docker/LAN-Modus deaktiviert. Bitte Pfad manuell eingeben oder Export in den Container mounten.", 400)
    if not deps.gui_picker_lock.acquire(blocking=False):
        return deps.jsonify(error_payload("Ein Dateiauswahl-Dialog ist bereits geöffnet.", code="dialog_already_open")), 409
    try:
        initial_dir = ""
        world_path = deps.json_string(data, "world_path")
        if world_path:
            deps.ensure_valid_world_path(world_path)
            initial_dir = deps.player_export_dir_for_world(world_path)
            os.makedirs(initial_dir, exist_ok=True)
        path = deps.select_player_export(initial_dir=initial_dir)
        if not path:
            return deps.jsonify(error_payload("Keine Datei ausgewählt.", code="file_selection_cancelled")), 400
        return deps.jsonify({"success": True, "path": path})
    except ValueError as exc:
        return deps.api_error(str(exc), 400)
    except Exception as exc:
        deps.log_api_exception("player_export.pick", exc)
        return deps.api_error(t("Fehler bei der Dateiauswahl: {error}", error=t(str(exc))), 500)
    finally:
        deps.gui_picker_lock.release()
