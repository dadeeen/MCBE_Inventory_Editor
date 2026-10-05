"""Handlers for icon-related API routes."""

from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any

from .api_errors import error_payload
from .archive_errors import ZIP_READ_ERRORS
from .i18n import t
from .icon_diagnostics import warning_text
from .icons import (
    add_icon_source,
    clear_icon_cache,
    configured_icon_sources,
    icon_context_id,
    load_cached_icon_candidate,
    load_cached_icon_index,
    load_icon_sources,
    move_icon_source,
    remove_icon_source,
    scan_icons,
    set_icon_source_enabled,
)
from .resource_packs import select_world_packs
from .service_errors import public_error_text
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
_INTERNAL_ICON_INDEX_FIELDS = ("_by_token", "display_icons", "_context_id", "_warning_records", "_legacy_warnings")


def _public_icon_index(index: dict) -> dict:
    public = {key: value for key, value in index.items() if key not in _INTERNAL_ICON_INDEX_FIELDS}
    public["warnings"] = [warning_text(record) for record in index.get("_warning_records", index.get("warnings", []))]
    context = index.get("_context_id")
    if context:

        def with_context(entry):
            return {**entry, "url": f"{entry['url']}?context={context}"} if entry.get("url") else entry

        public["icons"] = {key: with_context(entry) for key, entry in index.get("icons", {}).items()}
        if "health" in index:
            public["health"] = {**index["health"], "sample": [with_context(entry) for entry in index["health"].get("sample", [])]}
    return public


def _requested_icon_context(data: dict, deps: IconRouteDeps) -> tuple[list[dict], list[str]]:
    """Bind an explicit world, or recover the latest context for legacy clients."""
    if "world_path" in data:
        world = deps.json_string(data, "world_path")
        selected = select_world_packs(world)
        return selected.sources, selected.warnings
    # Sources may have changed. Reuse only metadata for a new validated scan,
    # preferring the shared publication over a stale worker-local index.
    published = load_cached_icon_index(deps.settings_path, validate_sources=False)
    previous = published if published is not None else deps.get_icon_index()
    sources = [source for source in previous.get("sources", []) if isinstance(source, dict) and source.get("world")]
    return sources, []


def _selection_diagnostics(index: dict, warnings: list[str]) -> dict:
    if not warnings:
        return index
    # Selection errors belong to the request, not to a shared Vanilla index.
    combined = [*index.get("warnings", []), *warnings]
    return {
        **index,
        "warnings": combined,
        "_warning_records": [*index.get("_warning_records", index.get("warnings", [])), *warnings],
        "health": {**index.get("health", {}), "status": "warning", "warning_count": len(combined)},
    }


def _scan_and_store_icons(
    deps: IconRouteDeps,
    *,
    force: bool = False,
    extra_sources: list[dict] | None = None,
    selection_warnings: list[str] | None = None,
) -> dict:
    with _icon_operation(deps):
        if extra_sources is None:
            extra_sources, selection_warnings = _requested_icon_context({}, deps)
        sources = configured_icon_sources(deps.settings_path, extra_sources=extra_sources)
        context_id = icon_context_id(sources)
        index = scan_icons(
            settings_path=deps.settings_path,
            force=force,
            prepared_sources=sources,
            context_id=context_id,
        )
        deps.set_icon_index(index)
        return _selection_diagnostics(index, selection_warnings or [])


def _icon_extra_sources_from_world(world_path: str | None) -> list[dict]:
    return select_world_packs(world_path).sources


def _status_icon_index(deps: IconRouteDeps, world_path: str | None) -> dict:
    sources, warnings = _requested_icon_context({} if world_path is None else {"world_path": world_path}, deps)
    # A worker-local index is not proof that the underlying pack files still
    # match. Only a validated publication or successful scan may supply icons.
    index = {"success": True, "enabled": True, "icons": {}, "_by_token": {}, "count": 0, "sources": [], "roots": [], "warnings": []}
    if deps.read_only:
        try:
            context = icon_context_id(configured_icon_sources(deps.settings_path, extra_sources=sources))
            cached = load_cached_icon_index(deps.settings_path, context_id=context)
            if cached is None:
                latest = load_cached_icon_index(deps.settings_path)
                if latest and (
                    latest.get("_context_id") == context or (latest.get("_context_id") is None and icon_context_id(latest.get("sources", [])) == context)
                ):
                    cached = latest
            if cached is not None:
                index = cached
                if cached.get("_legacy_warnings"):
                    warnings.append(t("Bitte Icons einmal mit Schreibzugriff neu scannen, um ältere Diagnosemeldungen in der gewählten Sprache anzuzeigen."))
            else:
                warnings.append(t("Kein gültiger Icon-Index vorhanden. Bitte die Icons einmal mit Schreibzugriff laden oder aktualisieren."))
        except Exception as exc:
            deps.log_api_exception("icons.status.cache", exc)
        deps.set_icon_index(index)
        return _selection_diagnostics(index, warnings)
    try:
        # scan_icons uses the shared source-signature cache, so this is cheap on
        # a hit and refreshes worker-local indexes after another worker changed
        # sources or published a Vanilla cache.
        index = _scan_and_store_icons(deps, extra_sources=sources, selection_warnings=warnings)
    except Exception as exc:
        deps.log_api_exception("icons.status", exc)
        deps.set_icon_index(index)
        return _selection_diagnostics(index, [*warnings, t("Icon-Index konnte nicht geladen werden. Bitte erneut laden oder Icons neu scannen.")])
    return index


def icons_status(deps: IconRouteDeps, *, world_path: str | None = None):
    try:
        return deps.jsonify(_public_icon_index(_status_icon_index(deps, world_path)))
    except ValueError as exc:
        return deps.api_error(str(exc), 400)


def icons_scan(data: dict, deps: IconRouteDeps):
    if deps.read_only:
        return deps.api_error("Icon-Scan ist im Read-Only-Modus deaktiviert.", 403)
    try:
        world = deps.json_string(data, "world_path")
        selected = select_world_packs(world)
        index = _scan_and_store_icons(deps, force=True, extra_sources=selected.sources, selection_warnings=selected.warnings)
        return deps.jsonify(_public_icon_index(index))
    except ValueError as exc:
        return deps.api_error(str(exc), 400)
    except Exception as exc:
        deps.log_api_exception("icons.scan", exc)
        return deps.api_error(t("Lokale Icons konnten nicht gescannt werden: {error}", error=public_error_text(exc)), 500)


def icons_vanilla_update(data: dict, deps: IconRouteDeps):
    try:
        with _icon_operation(deps):
            extra_sources, warnings = _requested_icon_context(data, deps)
            force = deps.json_bool(data, "force", False)
            # Normal updates always resolve the latest release.  The updater
            # itself reuses a validated ZIP automatically when it already
            # matches that release.
            returncode, output = deps.run_update_icons(force=force, use_cache=False)
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
                    clear_icon_cache(deps.settings_path)
                    index = _scan_and_store_icons(deps, force=True, extra_sources=extra_sources, selection_warnings=warnings)
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
                    "release_mode": "latest",
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
        return deps.api_error(t("Fehler beim Vanilla-Icon-Update: {error}", error=public_error_text(exc)), 500)


def icons_sources(deps: IconRouteDeps, *, world_path: str | None = None):
    try:
        with _icon_operation(deps):
            index = deps.get_icon_index() if world_path is None else _status_icon_index(deps, world_path)
            public = _public_icon_index(index)
            public["configured_sources"] = [
                {**source, "pack_error": warning_text(source["pack_error"])} if source.get("pack_error") else source
                for source in configured_icon_sources(deps.settings_path)
            ]
            public["manual_sources"] = load_icon_sources(deps.settings_path).get("sources", [])
            public["settings_path"] = deps.settings_path
            return deps.jsonify(public)
    except ValueError as exc:
        return deps.api_error(str(exc), 400)


def icons_sources_add(data: dict, deps: IconRouteDeps):
    source = None
    try:
        path = deps.json_string(data, "path")
        with _icon_operation(deps):
            # Source mutations invalidate the shared cache. Capture its world
            # context first, under the same lock as the mutation and rescan.
            extra_sources, warnings = _requested_icon_context(data, deps)
            source = add_icon_source(deps.settings_path, path)
            index = _scan_and_store_icons(deps, force=True, extra_sources=extra_sources, selection_warnings=warnings)
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
        return deps.api_error(t("Icon-Quelle konnte nicht hinzugefügt werden: {error}", error=public_error_text(exc)), 500)


def icons_sources_remove(data: dict, deps: IconRouteDeps):
    settings_changed = False
    try:
        path = deps.json_string(data, "path")
        with _icon_operation(deps):
            extra_sources, warnings = _requested_icon_context(data, deps)
            remove_icon_source(deps.settings_path, path)
            settings_changed = True
            index = _scan_and_store_icons(deps, force=True, extra_sources=extra_sources, selection_warnings=warnings)
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
        return deps.api_error(t("Icon-Quelle konnte nicht entfernt werden: {error}", error=public_error_text(exc)), 500)


def icons_sources_set_enabled(data: dict, deps: IconRouteDeps):
    settings_changed = False
    enabled = None
    try:
        path = deps.json_string(data, "path")
        enabled = deps.json_bool(data, "enabled", True)
        with _icon_operation(deps):
            extra_sources, warnings = _requested_icon_context(data, deps)
            set_icon_source_enabled(deps.settings_path, path, enabled)
            settings_changed = True
            index = _scan_and_store_icons(deps, force=True, extra_sources=extra_sources, selection_warnings=warnings)
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
        return deps.api_error(t("Icon-Quelle konnte nicht aktualisiert werden: {error}", error=public_error_text(exc)), 500)


def icons_sources_move(data: dict, deps: IconRouteDeps):
    settings_changed = False
    try:
        path = deps.json_string(data, "path")
        direction = deps.json_string(data, "direction")
        with _icon_operation(deps):
            extra_sources, warnings = _requested_icon_context(data, deps)
            move_icon_source(deps.settings_path, path, direction)
            settings_changed = True
            index = _scan_and_store_icons(deps, force=True, extra_sources=extra_sources, selection_warnings=warnings)
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
        return deps.api_error(t("Icon-Quelle konnte nicht verschoben werden: {error}", error=public_error_text(exc)), 500)


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
        return deps.api_error(t("Fehler bei der Resource-Pack-Auswahl: {error}", error=public_error_text(exc)), 500)
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
        return deps.api_error(t("Fehler bei der Icon-Ordnerauswahl: {error}", error=public_error_text(exc)), 500)
    finally:
        deps.gui_picker_lock.release()


def icon_file(token: str, deps: IconRouteDeps, *, context_id: str | None = None):
    # Index replacement is atomic. Keep serving the previous immutable
    # candidate while a long-running update prepares the next index.
    index = deps.get_icon_index()
    candidate = index.get("_by_token", {}).get(token) if context_id is None or index.get("_context_id") == context_id else None
    if context_id is not None and candidate is None:
        try:
            candidate = load_cached_icon_candidate(deps.settings_path, context_id, token)
        except ValueError:
            return deps.api_error("Icon nicht gefunden.", 404)
        except OSError as exc:
            deps.log_api_exception("icons.file_context", exc)
    if not candidate and context_id is None and not deps.read_only:
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
    except (OSError, KeyError, *ZIP_READ_ERRORS) as exc:
        deps.log_api_exception("icons.file", exc)
        return deps.api_error(t("Icon konnte nicht gelesen werden: {error}", error=public_error_text(exc)), 404)
    if len(data) > 2 * 1024 * 1024:
        return deps.api_error("Icon ist zu groß oder die Icon-Quelle wurde seit dem Scan verändert. Bitte Icons neu scannen.", 413)
    mimetype = "image/webp" if candidate.suffix == ".webp" else "image/png"
    return deps.response(data, mimetype=mimetype, headers={"Cache-Control": "private, max-age=86400"})
