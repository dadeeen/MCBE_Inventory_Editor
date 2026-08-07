"""Handlers for world scanning and scan-path API routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcbe_editor.world import (
    add_scan_path,
    get_configured_scan_roots,
    get_minecraft_saves_candidates,
    get_minecraft_saves_dir,
    remove_scan_path,
    scan_minecraft_worlds_with_meta,
    set_scan_path_enabled,
)

from .i18n import t


@dataclass(frozen=True)
class ScanRouteDeps:
    settings_path: str | None
    data_root: str | None
    jsonify: Callable[..., Any]
    api_error: Callable[..., Any]
    log_api_exception: Callable[[str, Exception], None]
    json_string: Callable[..., str]
    json_bool: Callable[..., bool]
    audit_event: Callable[..., None]


def scan_worlds(deps: ScanRouteDeps):
    try:
        result = scan_minecraft_worlds_with_meta()
        return deps.jsonify({"success": True, **result})
    except Exception as exc:
        deps.log_api_exception("worlds.scan", exc)
        return deps.api_error(t("Fehler beim Scannen der Welten: {error}", error=t(str(exc))), 500)


def get_scan_paths(deps: ScanRouteDeps):
    roots = get_configured_scan_roots(include_disabled=True)
    active_paths = [root["path"] for root in roots if root.get("enabled", True)]
    default = get_minecraft_saves_dir()
    candidates = get_minecraft_saves_candidates(existing_only=False)
    extra = [root["path"] for root in roots if root.get("removable")]
    return deps.jsonify(
        {
            "success": True,
            "default_path": str(default) if default else None,
            "default_candidates": [str(path) for path in candidates[:6]],
            "scan_roots": roots,
            "extra_paths": extra,
            "all_paths": active_paths,
            "settings_path": deps.settings_path,
            "data_root": deps.data_root,
        }
    )


def add_scan_path_route(data: dict, deps: ScanRouteDeps):
    try:
        path = deps.json_string(data, "path")
        if not path:
            return deps.api_error("Kein Pfad angegeben.")
        add_scan_path(path)
        deps.audit_event("scan_path.add", "success", details={"path": path})
        return deps.jsonify({"success": True})
    except ValueError as exc:
        return deps.api_error(str(exc))
    except Exception as exc:
        deps.log_api_exception("scan_path.add", exc)
        return deps.api_error(t("Fehler beim Hinzufügen des Scan-Pfads: {error}", error=t(str(exc))), 500)


def remove_scan_path_route(data: dict, deps: ScanRouteDeps):
    try:
        path = deps.json_string(data, "path")
        if not path:
            return deps.api_error("Kein Pfad angegeben.")
        remove_scan_path(path)
        deps.audit_event("scan_path.remove", "success", details={"path": path})
        return deps.jsonify({"success": True})
    except ValueError as exc:
        return deps.api_error(str(exc))
    except Exception as exc:
        deps.log_api_exception("scan_path.remove", exc)
        return deps.api_error(t("Fehler beim Entfernen des Scan-Pfads: {error}", error=t(str(exc))), 500)


def set_scan_path_enabled_route(data: dict, deps: ScanRouteDeps):
    try:
        path = deps.json_string(data, "path")
        enabled = deps.json_bool(data, "enabled", True)
        if not path:
            return deps.api_error("Kein Pfad angegeben.")
        set_scan_path_enabled(path, enabled)
        deps.audit_event("scan_path.enable" if enabled else "scan_path.disable", "success", details={"path": path})
        return deps.jsonify({"success": True})
    except ValueError as exc:
        return deps.api_error(str(exc))
    except Exception as exc:
        deps.log_api_exception("scan_path.set_enabled", exc)
        return deps.api_error(t("Fehler beim Aktualisieren des Scan-Pfads: {error}", error=t(str(exc))), 500)
