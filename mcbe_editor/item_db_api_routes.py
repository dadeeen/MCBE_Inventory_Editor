"""Handlers for item database status and update API routes."""

from __future__ import annotations

import hmac
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any

from . import item_db_verification
from .i18n import t

_UPDATE_REVIEW_TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ItemDbRouteDeps:
    item_db_path: str | None
    source_version_path: str | None
    source_version_history_path: str | None
    update_cache_dir: str | None
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


def _expected_update_review_token(data: dict) -> str | None:
    value = data.get("expected_update_review_token")
    legacy_value = data.get("expected_release_cache_token")
    if value not in (None, "") and legacy_value not in (None, "") and value != legacy_value:
        raise ValueError("Die übermittelten Dry-Run-Prüfbelege widersprechen sich.")
    if value in (None, ""):
        value = legacy_value
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not _UPDATE_REVIEW_TOKEN_RE.fullmatch(value):
        raise ValueError("Der Dry-Run-Prüfbeleg ist ungültig.")
    return value


def update_review_snapshot(deps: ItemDbRouteDeps, only: str | None) -> dict:
    """Return a receipt for the exact cached sources and current base files."""

    if not all(
        (
            deps.update_cache_dir,
            deps.item_db_path,
            deps.source_version_path,
            deps.source_version_history_path,
        )
    ):
        return {}
    try:
        return item_db_verification.update_review_snapshot(
            update_cache_dir=Path(deps.update_cache_dir).expanduser(),
            item_db_path=Path(deps.item_db_path).expanduser(),
            source_version_path=Path(deps.source_version_path).expanduser(),
            source_version_history_path=Path(deps.source_version_history_path).expanduser(),
            scope=only,
        )
    except (OSError, item_db_verification.UpdateReviewError):
        return {}


def update_db(data: dict, deps: ItemDbRouteDeps):
    try:
        dry_run = deps.json_bool(data, "dry_run", True)
        force = deps.json_bool(data, "force", False)
        only = _update_scope(data)
        expected_review_token = _expected_update_review_token(data)
        if not dry_run and not force:
            raise ValueError("Ein schreibendes Item-DB-Update erfordert eine ausdrückliche Bestätigung.")
        if dry_run and expected_review_token:
            raise ValueError("Ein Dry-Run kann keinen früheren Prüfbeleg anwenden.")

        use_cache = False
        if expected_review_token:
            current_review = update_review_snapshot(deps, only)
            if not current_review or not hmac.compare_digest(expected_review_token, current_review["token"]):
                raise ValueError(
                    "Die im Dry-Run geprüften Quellen oder Ausgangsdaten haben sich geändert. Bitte den Dry-Run erneut ausführen."
                )
            use_cache = True

        returncode, output = deps.run_update_db(
            dry_run=dry_run,
            force=force,
            only=only,
            use_cache=use_cache,
            expected_review_token=expected_review_token,
        )

        result = {
            "success": returncode == 0,
            "returncode": returncode,
            "output": output,
        }
        resolved_review = update_review_snapshot(deps, only) if returncode == 0 else {}
        if dry_run and returncode == 0 and resolved_review:
            result.update(
                {
                    "update_review_token": resolved_review["token"],
                    # Compatibility alias for clients from before the receipt
                    # was expanded beyond the Resource-Pack cache.
                    "release_cache_token": resolved_review["token"],
                    "resource_pack_release": resolved_review["resource_pack_release"],
                }
            )

        receipt_failed = dry_run and returncode == 0 and not resolved_review
        if receipt_failed:
            result.update(
                {
                    "success": False,
                    "returncode": 1,
                    "error": t("Der Dry-Run konnte keinen sicheren Prüfbeleg erstellen. Bitte den Dry-Run erneut ausführen."),
                }
            )

        category = "ok"
        if receipt_failed:
            category = "review-receipt-error"
        elif returncode != 0:
            category = "network-or-dns" if deps.looks_like_network_failure(output) else "script-error"
        if category != "ok":
            deps.logger.warning(
                "item_db_update failed returncode=%s category=%s dry_run=%s only=%s release_mode=%s app_continues=true",
                result["returncode"],
                category,
                dry_run,
                only or "all",
                "reviewed-cache" if use_cache else "latest",
            )
            if not receipt_failed:
                result["error"] = t(
                    "Item-DB-Update konnte die Online-Quellen nicht erreichen."
                    if category == "network-or-dns"
                    else "Item-DB-Update ist fehlgeschlagen."
                )
            if category == "network-or-dns":
                result["hint"] = t(
                    "Der Container/App-Host hat vermutlich keinen funktionierenden DNS-/HTTPS-Ausgang. "
                    "Die App läuft weiter; nur das Item-DB-Update braucht Internet."
                )

        deps.audit_event(
            "item_db.update",
            "success" if result["success"] else "failure",
            details={
                "dry_run": dry_run,
                "force": force,
                "only": only or "all",
                "release_mode": "reviewed-cache" if use_cache else "latest",
                "resource_pack_release": resolved_review.get("resource_pack_release"),
                "returncode": result["returncode"],
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
