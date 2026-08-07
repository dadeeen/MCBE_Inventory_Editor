"""Handlers for icon-related API routes."""

from __future__ import annotations

import contextlib
import json
import threading
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any

from .api_errors import error_payload
from .i18n import t
from .icons import (
    add_icon_source,
    configured_icon_sources,
    load_cached_icon_index,
    load_icon_sources,
    move_icon_source,
    remove_icon_source,
    scan_icons,
    set_icon_source_enabled,
    world_icon_roots,
)
from .world_locks import locked_operation

_ICON_OPERATION_LOCK = threading.RLock()


@contextlib.contextmanager
def _icon_operation(deps):
    root = getattr(deps, "data_root", None) or str(Path(deps.settings_path).expanduser().parent)
    with _ICON_OPERATION_LOCK, locked_operation("icon-operations", root=root):
        yield


@dataclass(frozen=True)
class IconRouteDeps:
    settings_path: str
    data_root: str | None
    is_docker: bool
    read_only: bool
    get_icon_index: Callable[[], dict]
    set_icon_index: Callable[[dict], None]
    known_item_ids: Callable[[], Iterable[str]]
    jsonify: Callable[..., Any]
    response: Callable[..., Any]
    api_error: Callable[..., Any]
    log_api_exception: Callable[[str, Exception], None]
    json_string: Callable[..., str]
    json_bool: Callable[..., bool]
    run_update_icons: Callable[..., tuple[int, str]]
    looks_like_network_failure: Callable[[str], bool]
    audit_event: Callable[..., None]
    gui_picker_lock: Any
    select_icon_pack: Callable[[], str | None]
    select_icon_folder: Callable[[], str | None]


# Interne Felder, die nicht über die HTTP-Schnittstelle gehen. ``_by_token`` ist
# der Server-Lookup für /api/icons/<token>. ``display_icons`` waren die
# Entity-Varianten-Vorschaubilder: der Slot-Badge dafür wurde entfernt, weil ein
# 18-px-Ausschnitt einer Entity-Textur praktisch nur als schwarzer Kasten
# ankommt. Extraktion und Cache laufen unverändert weiter, damit die
# Manifest-Schemaversion und die Icon-Caches der Nutzer gültig bleiben.
_INTERNAL_ICON_INDEX_FIELDS = ("_by_token", "display_icons")


def _public_icon_index(index: dict) -> dict:
    return {key: value for key, value in index.items() if key not in _INTERNAL_ICON_INDEX_FIELDS}


def _scan_and_store_icons(
    deps: IconRouteDeps,
    *,
    force: bool = False,
    extra_sources: list[dict] | None = None,
) -> dict:
    with _icon_operation(deps):
        index = scan_icons(
            deps.known_item_ids(),
            settings_path=deps.settings_path,
            force=force,
            extra_sources=extra_sources,
        )
        deps.set_icon_index(index)
        return index


def _icon_extra_sources_from_world(world_path: str | None) -> list[dict]:
    sources = []
    for root in world_icon_roots(world_path):
        sources.append(
            {
                "path": str(root),
                "enabled": True,
                "label": t("Aus gewählter Welt abgeleitete Resource Packs"),
                "auto": True,
                "world": True,
            }
        )
    return sources


def icons_status(deps: IconRouteDeps):
    index = deps.get_icon_index()
    if deps.read_only:
        try:
            cached = load_cached_icon_index(deps.settings_path)
            if cached is not None:
                index = cached
                deps.set_icon_index(index)
        except Exception as exc:
            deps.log_api_exception("icons.status.cache", exc)
        return deps.jsonify(_public_icon_index(index))
    try:
        # scan_icons uses the shared source-signature cache, so this is cheap on
        # a hit and refreshes worker-local indexes after another worker changed
        # sources or published a Vanilla cache.
        index = _scan_and_store_icons(deps)
    except Exception as exc:
        deps.log_api_exception("icons.status", exc)
        index = deps.get_icon_index()
    return deps.jsonify(_public_icon_index(index))


def icons_scan(data: dict, deps: IconRouteDeps):
    if deps.read_only:
        return deps.api_error("Icon-Scan ist im Read-Only-Modus deaktiviert.", 403)
    try:
        extra_sources = _icon_extra_sources_from_world(deps.json_string(data, "world_path"))
        index = _scan_and_store_icons(deps, force=True, extra_sources=extra_sources)
        return deps.jsonify(_public_icon_index(index))
    except ValueError as exc:
        return deps.api_error(str(exc), 400)
    except Exception as exc:
        deps.log_api_exception("icons.scan", exc)
        return deps.api_error(t("Lokale Icons konnten nicht gescannt werden: {error}", error=t(str(exc))), 500)


def icons_vanilla_update(data: dict, deps: IconRouteDeps):
    try:
        with _icon_operation(deps):
            use_cache = deps.json_bool(data, "use_cache", True)
            force = deps.json_bool(data, "force", False)
            returncode, output = deps.run_update_icons(force=force, use_cache=use_cache)
            manifest_path = Path(deps.data_root or "data").expanduser() / "icons" / "vanilla" / "manifest.json"
            manifest = {}
            if manifest_path.exists():
                with contextlib.suppress(OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
                    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        manifest = loaded
            result = {
                "success": returncode == 0,
                "returncode": returncode,
                "output": output,
                "manifest": manifest,
            }
            if returncode == 0:
                result["update_committed"] = True
                try:
                    index = _scan_and_store_icons(deps, force=True)
                    result.update(_public_icon_index(index))
                except Exception as exc:
                    deps.log_api_exception("icons.vanilla_update_rescan", exc)
                    result["scan_warning"] = t(
                        "Die Vanilla-Icons wurden aktualisiert, konnten aber nicht automatisch neu eingelesen werden. "
                        "Bitte Icons erneut scannen oder die Anwendung neu starten."
                    )
            else:
                result["error"] = t("Vanilla-Icons konnten nicht geladen werden.")
                result["category"] = "network-or-dns" if deps.looks_like_network_failure(output) else "script-error"
            deps.audit_event(
                "icons.vanilla_update",
                "partial" if returncode == 0 and "scan_warning" in result else ("success" if returncode == 0 else "failure"),
                details={
                    "use_cache": use_cache,
                    "force": force,
                    "returncode": returncode,
                    "index_refreshed": returncode == 0 and "scan_warning" not in result,
                },
            )
            return deps.jsonify(result)
    except TimeoutExpired:
        deps.audit_event("icons.vanilla_update", "failure", details={"category": "timeout", "timeout_seconds": 300})
        return deps.api_error("Timeout: Das Icon-Update läuft länger als 5 Minuten.")
    except ValueError as exc:
        return deps.api_error(str(exc), 400)
    except Exception as exc:
        deps.log_api_exception("icons.vanilla_update", exc)
        return deps.api_error(t("Fehler beim Vanilla-Icon-Update: {error}", error=t(str(exc))), 500)


def icons_sources(deps: IconRouteDeps):
    with _icon_operation(deps):
        public = _public_icon_index(deps.get_icon_index())
        public["configured_sources"] = configured_icon_sources(deps.settings_path)
        public["manual_sources"] = load_icon_sources(deps.settings_path).get("sources", [])
        public["settings_path"] = deps.settings_path
        return deps.jsonify(public)


def icons_sources_add(data: dict, deps: IconRouteDeps):
    source = None
    try:
        path = deps.json_string(data, "path")
        with _icon_operation(deps):
            source = add_icon_source(deps.settings_path, path)
            index = _scan_and_store_icons(deps, force=True)
        deps.audit_event("icons.source_add", "success", details={"path": source.get("path")})
        public = _public_icon_index(index)
        public["added_source"] = source
        return deps.jsonify(public)
    except ValueError as exc:
        deps.audit_event(
            "icons.source_add",
            "partial" if source is not None else "failure",
            details={"path": source.get("path") if source is not None else data.get("path"), "settings_changed": source is not None},
            error=str(exc),
        )
        return deps.api_error(str(exc), 400)
    except Exception as exc:
        deps.log_api_exception("icons.source_add", exc)
        deps.audit_event(
            "icons.source_add",
            "partial" if source is not None else "failure",
            details={"path": source.get("path") if source is not None else data.get("path"), "settings_changed": source is not None},
            error=str(exc),
        )
        return deps.api_error(t("Icon-Quelle konnte nicht hinzugefügt werden: {error}", error=t(str(exc))), 500)


def icons_sources_remove(data: dict, deps: IconRouteDeps):
    settings_changed = False
    try:
        path = deps.json_string(data, "path")
        with _icon_operation(deps):
            remove_icon_source(deps.settings_path, path)
            settings_changed = True
            index = _scan_and_store_icons(deps, force=True)
        deps.audit_event("icons.source_remove", "success", details={"path": path})
        return deps.jsonify(_public_icon_index(index))
    except ValueError as exc:
        deps.audit_event(
            "icons.source_remove",
            "partial" if settings_changed else "failure",
            details={"path": data.get("path"), "settings_changed": settings_changed},
            error=str(exc),
        )
        return deps.api_error(str(exc), 400)
    except Exception as exc:
        deps.log_api_exception("icons.source_remove", exc)
        deps.audit_event(
            "icons.source_remove",
            "partial" if settings_changed else "failure",
            details={"path": data.get("path"), "settings_changed": settings_changed},
            error=str(exc),
        )
        return deps.api_error(t("Icon-Quelle konnte nicht entfernt werden: {error}", error=t(str(exc))), 500)


def icons_sources_set_enabled(data: dict, deps: IconRouteDeps):
    settings_changed = False
    enabled = None
    try:
        path = deps.json_string(data, "path")
        enabled = deps.json_bool(data, "enabled", True)
        with _icon_operation(deps):
            set_icon_source_enabled(deps.settings_path, path, enabled)
            settings_changed = True
            index = _scan_and_store_icons(deps, force=True)
        deps.audit_event("icons.source_enable" if enabled else "icons.source_disable", "success", details={"path": path})
        return deps.jsonify(_public_icon_index(index))
    except ValueError as exc:
        action = "icons.source_set_enabled" if enabled is None else ("icons.source_enable" if enabled else "icons.source_disable")
        deps.audit_event(
            action,
            "partial" if settings_changed else "failure",
            details={"path": data.get("path"), "settings_changed": settings_changed},
            error=str(exc),
        )
        return deps.api_error(str(exc), 400)
    except Exception as exc:
        deps.log_api_exception("icons.source_set_enabled", exc)
        action = "icons.source_set_enabled" if enabled is None else ("icons.source_enable" if enabled else "icons.source_disable")
        deps.audit_event(
            action,
            "partial" if settings_changed else "failure",
            details={"path": data.get("path"), "settings_changed": settings_changed},
            error=str(exc),
        )
        return deps.api_error(t("Icon-Quelle konnte nicht aktualisiert werden: {error}", error=t(str(exc))), 500)


def icons_sources_move(data: dict, deps: IconRouteDeps):
    settings_changed = False
    try:
        path = deps.json_string(data, "path")
        direction = deps.json_string(data, "direction")
        with _icon_operation(deps):
            move_icon_source(deps.settings_path, path, direction)
            settings_changed = True
            index = _scan_and_store_icons(deps, force=True)
        deps.audit_event("icons.source_move", "success", details={"path": path, "direction": direction})
        return deps.jsonify(_public_icon_index(index))
    except ValueError as exc:
        deps.audit_event(
            "icons.source_move",
            "partial" if settings_changed else "failure",
            details={"path": data.get("path"), "direction": data.get("direction"), "settings_changed": settings_changed},
            error=str(exc),
        )
        return deps.api_error(str(exc), 400)
    except Exception as exc:
        deps.log_api_exception("icons.source_move", exc)
        deps.audit_event(
            "icons.source_move",
            "partial" if settings_changed else "failure",
            details={"path": data.get("path"), "direction": data.get("direction"), "settings_changed": settings_changed},
            error=str(exc),
        )
        return deps.api_error(t("Icon-Quelle konnte nicht verschoben werden: {error}", error=t(str(exc))), 500)


def icons_pick_pack(deps: IconRouteDeps):
    if deps.is_docker:
        return deps.api_error(
            "Dateiauswahl ist im Docker/LAN-Modus deaktiviert. Bitte Resource-Pack in den Container mounten und Pfad manuell hinzufügen.",
            400,
        )
    if not deps.gui_picker_lock.acquire(blocking=False):
        return deps.jsonify(error_payload("Ein Dateiauswahl-Dialog ist bereits geöffnet.", code="dialog_already_open")), 409
    try:
        path = deps.select_icon_pack()
        if not path:
            return deps.jsonify(error_payload("Keine Datei ausgewählt.", code="file_selection_cancelled")), 400
        return deps.jsonify({"success": True, "path": path})
    except Exception as exc:
        deps.log_api_exception("icons.pick_pack", exc)
        return deps.api_error(t("Fehler bei der Resource-Pack-Auswahl: {error}", error=t(str(exc))), 500)
    finally:
        deps.gui_picker_lock.release()


def icons_pick_folder(deps: IconRouteDeps):
    if deps.is_docker:
        return deps.api_error(
            "Ordnerauswahl ist im Docker/LAN-Modus deaktiviert. Bitte Resource-Pack in den Container mounten und Pfad manuell hinzufügen.",
            400,
        )
    if not deps.gui_picker_lock.acquire(blocking=False):
        return deps.jsonify(error_payload("Ein Dateiauswahl-Dialog ist bereits geöffnet.", code="dialog_already_open")), 409
    try:
        path = deps.select_icon_folder()
        if not path:
            return deps.jsonify(error_payload("Kein Ordner ausgewählt.", code="folder_selection_cancelled")), 400
        return deps.jsonify({"success": True, "path": path})
    except Exception as exc:
        deps.log_api_exception("icons.pick_folder", exc)
        return deps.api_error(t("Fehler bei der Icon-Ordnerauswahl: {error}", error=t(str(exc))), 500)
    finally:
        deps.gui_picker_lock.release()


def icon_file(token: str, deps: IconRouteDeps):
    # Index replacement is atomic. Keep serving the previous immutable
    # candidate while a long-running update prepares the next index.
    candidate = deps.get_icon_index().get("_by_token", {}).get(token)
    if not candidate and not deps.read_only:
        try:
            candidate = _scan_and_store_icons(deps).get("_by_token", {}).get(token)
        except Exception as exc:
            deps.log_api_exception("icons.file_refresh", exc)
    if not candidate:
        return deps.api_error("Icon nicht gefunden.", 404)
    try:
        data = candidate.read_bytes()
    except ValueError as exc:
        return deps.api_error(str(exc), 413)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        return deps.api_error(t("Icon konnte nicht gelesen werden: {error}", error=t(str(exc))), 404)
    if len(data) > 2 * 1024 * 1024:
        return deps.api_error("Icon ist zu groß oder die Icon-Quelle wurde seit dem Scan verändert. Bitte Icons neu scannen.", 413)
    mimetype = "image/webp" if candidate.suffix == ".webp" else "image/png"
    return deps.response(data, mimetype=mimetype, headers={"Cache-Control": "private, max-age=86400"})
