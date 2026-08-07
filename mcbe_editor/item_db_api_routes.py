"""Handlers for item database status and update API routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from subprocess import TimeoutExpired
from typing import Any

from .i18n import t


@dataclass(frozen=True)
class ItemDbRouteDeps:
    source_version_history_path: str | None
    jsonify: Callable[..., Any]
    api_error: Callable[..., Any]
    log_api_exception: Callable[[str, Exception], None]
    json_bool: Callable[..., bool]
    run_update_db: Callable[..., tuple[int, str]]
    looks_like_network_failure: Callable[[str], bool]
    item_db_status_snapshot: Callable[[], dict]
    source_version_history_entries: Callable[[], list[dict]]
    reload_item_db_after_update: Callable[[], dict]
    audit_event: Callable[..., None]
    logger: Any


def _update_scope(data: dict) -> str | None:
    only = data.get("only")
    if only is not None and not isinstance(only, str):
        raise ValueError("Feld 'only' muss ein Textwert sein.")
    if isinstance(only, str):
        only = only.strip() or None
    if only not in (None, "items", "effects", "enchants"):
        raise ValueError("Ungültiger Update-Bereich. Erlaubt sind: items, effects, enchants.")
    return only


def update_db(data: dict, deps: ItemDbRouteDeps):
    try:
        dry_run = deps.json_bool(data, "dry_run", True)
        force = deps.json_bool(data, "force", False)
        only = _update_scope(data)
        use_cache = deps.json_bool(data, "use_cache", True)
        if not dry_run and not force:
            raise ValueError("Ein schreibendes Item-DB-Update erfordert eine ausdrückliche Bestätigung.")

        returncode, output = deps.run_update_db(
            dry_run=dry_run,
            force=force,
            only=only,
            use_cache=use_cache,
        )

        result = {
            "success": returncode == 0,
            "returncode": returncode,
            "output": output,
        }

        category = "ok"
        if returncode != 0:
            category = "network-or-dns" if deps.looks_like_network_failure(output) else "script-error"
            deps.logger.warning(
                "item_db_update failed returncode=%s category=%s dry_run=%s only=%s use_cache=%s app_continues=true",
                returncode,
                category,
                dry_run,
                only or "all",
                use_cache,
            )
            result["error"] = t(
                "Item-DB-Update konnte die Online-Quellen nicht erreichen." if category == "network-or-dns" else "Item-DB-Update ist fehlgeschlagen."
            )
            if category == "network-or-dns":
                result["hint"] = t(
                    "Der Container/App-Host hat vermutlich keinen funktionierenden DNS-/HTTPS-Ausgang. "
                    "Die App läuft weiter; nur das Item-DB-Update braucht Internet."
                )

        deps.audit_event(
            "item_db.update",
            "success" if returncode == 0 else "failure",
            details={
                "dry_run": dry_run,
                "force": force,
                "only": only or "all",
                "use_cache": use_cache,
                "returncode": returncode,
                "category": category,
            },
        )

        if returncode == 0 and not dry_run:
            result["update_committed"] = True
            try:
                result.update(deps.reload_item_db_after_update())
            except Exception as exc:
                deps.log_api_exception("item_db_reload_after_update", exc)
                result.update(
                    {
                        "reloaded": False,
                        "reload_warning": t(
                            "Die Item-Datenbank wurde aktualisiert, konnte aber im laufenden Server nicht neu geladen werden. Bitte die Anwendung neu starten."
                        ),
                    }
                )

        return deps.jsonify(result)
    except ValueError as exc:
        return deps.api_error(str(exc), 400)
    except TimeoutExpired:
        deps.logger.warning("item_db_update timeout seconds=180 app_continues=true")
        deps.audit_event("item_db.update", "failure", details={"category": "timeout", "timeout_seconds": 180})
        return deps.api_error("Timeout: Das Update-Skript läuft länger als 3 Minuten.")
    except Exception as exc:
        deps.log_api_exception("item_db_update", exc)
        return deps.api_error(t("Fehler beim Datenbank-Update: {error}", error=t(str(exc))), 500)


def item_db_status(deps: ItemDbRouteDeps):
    return deps.jsonify({"success": True, "item_db": deps.item_db_status_snapshot()})


def item_db_versions(deps: ItemDbRouteDeps):
    entries = deps.source_version_history_entries()
    return deps.jsonify(
        {
            "success": True,
            "entries": list(reversed(entries)),
            "count": len(entries),
            "path": deps.source_version_history_path,
        }
    )
