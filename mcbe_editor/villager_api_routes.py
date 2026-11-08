"""HTTP contracts for the world-scoped villager workspace."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from itsdangerous import BadData, URLSafeTimedSerializer

from . import villager_service
from .api_errors import add_exception_cleanup_details, error_payload, uncertain_write_payload
from .i18n import t
from .leveldb_readonly import WorldChangedWhileReadingError
from .read_operation import ReadStoppedError
from .service_errors import WriteOutcomeUnknownError, current_request_id, public_error_text
from .villager_preferences import VillagerPreferences, VillagerPreferencesStaleError
from .world import ensure_valid_world_path
from .world_locks import lock_key

PREVIEW_MAX_AGE = 600
MAX_PREVIEW_TOKEN_LENGTH = 512 * 1024
MAX_SELECTION = 1000


class VillagerPreviewStaleError(ValueError):
    pass


@dataclass(frozen=True)
class VillagerRouteDeps:
    service: Any
    preferences: VillagerPreferences
    secret_key: str | bytes
    session_identity: Callable[[], str]
    jsonify: Callable[..., Any]
    api_error: Callable[..., Any]
    log_api_exception: Callable[[str, Exception], None]
    json_string: Callable[..., str]
    world_db_access_gate: Callable[[], dict]
    db_access_block_response: Callable[[dict], Any]
    require_world_write_allowed: Callable[[], Any]
    require_server_guard_current: Callable[[dict], Any]
    require_final_world_write_allowed: Callable[[str], None]
    presence_conflict_response: Callable[..., Any]
    final_write_gate_blocked_error: type[Exception]
    audit_event: Callable[..., None]


def _owner(deps: VillagerRouteDeps) -> str:
    return hashlib.sha256(deps.session_identity().encode()).hexdigest()


def _serializer(deps: VillagerRouteDeps) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(deps.secret_key, salt="mcbe-villager-health-preview-v1")


def _selection(data: dict) -> list[dict[str, str]]:
    selection = data.get("selection")
    if not isinstance(selection, list) or not 1 <= len(selection) <= MAX_SELECTION:
        raise ValueError(t("Wähle zwischen 1 und 1000 Dorfbewohner für eine Änderung aus."))
    result = []
    seen = set()
    for item in selection:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("revision"), str):
            raise ValueError(t("Die Auswahl benötigt Dorfbewohner-IDs und Datensatzrevisionen."))
        identifier, revision = item["id"], item["revision"]
        if not identifier or len(identifier) > 512 or len(revision) != 64 or any(char not in "0123456789abcdef" for char in revision):
            raise ValueError(t("Ungültige Dorfbewohner-ID oder Datensatzrevision."))
        if identifier in seen:
            raise ValueError(t("Die Auswahl enthält einen Dorfbewohner mehrfach."))
        seen.add(identifier)
        result.append({"id": identifier, "revision": revision})
    return result


def _read_gate(deps: VillagerRouteDeps) -> tuple[dict, Any]:
    gate = deps.world_db_access_gate()
    blocked = None if gate.get("read_allowed", gate.get("allowed", False)) else deps.db_access_block_response(gate)
    return gate, blocked


def _guard_from_gate(gate: dict) -> dict[str, Any]:
    status = gate.get("server_status") or {}
    stale = status.get("status") == "online" and (gate.get("config") or {}).get("require_server_offline") is True
    epoch = int(gate.get("server_guard_epoch") or 0)
    return {
        "server_guard_epoch": max(0, epoch - 1) if stale else epoch,
        "server_guard_token": str((gate.get("_server_guard_previous_token") or "") if stale else (gate.get("server_guard_token") or "")),
    }


def _audit(deps: VillagerRouteDeps, action: str, outcome: str, **kwargs: Any) -> None:
    # Logging must not turn a committed write into an apparently retryable error.
    try:
        deps.audit_event(action, outcome, **kwargs)
    except Exception as exc:
        deps.log_api_exception(f"{action}.audit", exc)


def _run(action: str, data: dict, deps: VillagerRouteDeps, work: Callable[[], Any]) -> Any:
    try:
        return work()
    except ReadStoppedError:
        raise
    except WriteOutcomeUnknownError as exc:
        deps.log_api_exception(action, exc)
        _audit(deps, action, "uncertain", world_path=data.get("world_path"))
        return deps.jsonify(uncertain_write_payload(exc)), 500
    except deps.final_write_gate_blocked_error as exc:
        payload = error_payload(exc, code="final_write_gate_blocked")
        payload["write_gate"] = getattr(exc, "write_gate", {})
        add_exception_cleanup_details(payload, exc)
        return deps.jsonify(payload), 409
    except (villager_service.VillagerSnapshotStaleError, VillagerPreviewStaleError, VillagerPreferencesStaleError, WorldChangedWhileReadingError) as exc:
        code = "villager_snapshot_stale"
        if isinstance(exc, VillagerPreviewStaleError):
            code = "villager_preview_stale"
        elif isinstance(exc, VillagerPreferencesStaleError):
            code = "villager_preferences_stale"
        elif isinstance(exc, WorldChangedWhileReadingError):
            code = "world_changed_while_reading"
        payload = add_exception_cleanup_details(error_payload(exc, code=code), exc)
        payload["reload_required"] = True
        return deps.jsonify(payload), 409
    except ValueError as exc:
        return deps.jsonify(add_exception_cleanup_details(error_payload(exc, code="villager_request_invalid"), exc)), 400
    except Exception as exc:
        deps.log_api_exception(action, exc)
        return deps.jsonify(
            add_exception_cleanup_details(
                error_payload(
                    "Die Dorfbewohner-Anfrage konnte nicht abgeschlossen werden.",
                    code="villager_request_failed",
                    details=public_error_text(exc),
                    request_id=current_request_id() or None,
                ),
                exc,
            )
        ), 500


def scan_villagers(data: dict, deps: VillagerRouteDeps) -> Any:
    def work():
        gate, blocked = _read_gate(deps)
        if blocked is not None:
            return blocked
        world_path = deps.json_string(data, "world_path")
        result = villager_service.scan(deps.service, world_path)
        result.update(success=True, preferences=deps.preferences.read(world_path), **_guard_from_gate(gate))
        return deps.jsonify(result)

    return _run("villagers.scan", data, deps, work)


def villager_detail(data: dict, deps: VillagerRouteDeps) -> Any:
    def work():
        _, blocked = _read_gate(deps)
        if blocked is not None:
            return blocked
        world_path = deps.json_string(data, "world_path")
        identifier = deps.json_string(data, "id")
        revision = deps.json_string(data, "revision")
        world_revision = deps.json_string(data, "world_revision")
        if not revision or not world_revision:
            raise ValueError(t("Bitte die Dorfbewohner vor dem Öffnen der Details scannen."))
        result = villager_service.detail(deps.service, world_path, identifier, revision, world_revision)
        return deps.jsonify({"success": True, "villager": result})

    return _run("villagers.detail", data, deps, work)


def preview_villagers(data: dict, deps: VillagerRouteDeps) -> Any:
    def work():
        _, blocked = _read_gate(deps)
        if blocked is not None:
            return blocked
        blocked = deps.require_server_guard_current(data)
        if blocked is not None:
            return blocked
        world_path = deps.json_string(data, "world_path")
        revision = deps.json_string(data, "world_revision")
        selection = _selection(data)
        plan = villager_service.preview(deps.service, world_path, revision, selection, data.get("changes"))
        guard = {
            "server_guard_epoch": data.get("server_guard_epoch"),
            "server_guard_token": data.get("server_guard_token", ""),
        }
        payload = {
            "owner": _owner(deps),
            "world": lock_key(world_path),
            "world_revision": revision,
            "selection": selection,
            "changes": plan.changes,
            "plan_digest": villager_service.plan_digest(plan),
            **guard,
        }
        token = _serializer(deps).dumps(payload) if plan.writes else None
        return deps.jsonify(
            {
                "success": True,
                "rows": [{**row, "label": row.get("name") or row["id"]} for row in plan.rows],
                "change_count": plan.summary["changed"],
                "skipped_count": plan.summary["skipped"],
                "unchanged_count": plan.summary["unchanged"],
                "preview_token": token,
                "expires_in": PREVIEW_MAX_AGE,
                "world_revision": revision,
            }
        )

    return _run("villagers.preview", data, deps, work)


def _load_preview(data: dict, deps: VillagerRouteDeps, world_path: str) -> dict:
    token = data.get("preview_token")
    message = t("Die Änderungsvorschau ist ungültig oder abgelaufen. Bitte eine neue Vorschau erstellen.")
    if not isinstance(token, str) or not token or len(token) > MAX_PREVIEW_TOKEN_LENGTH:
        raise VillagerPreviewStaleError(message)
    try:
        payload = _serializer(deps).loads(token, max_age=PREVIEW_MAX_AGE)
    except BadData as exc:
        raise VillagerPreviewStaleError(message) from exc
    if not isinstance(payload, dict) or payload.get("owner") != _owner(deps) or payload.get("world") != lock_key(world_path):
        raise VillagerPreviewStaleError(message)
    return payload


def load_workspace_previews(data: dict, deps: VillagerRouteDeps, world_path: str) -> tuple[list[dict], Any]:
    tokens = data.get("villager_previews", [])
    if not isinstance(tokens, list) or len(tokens) > 64:
        raise ValueError(t("Pro Speichervorgang sind höchstens 64 Dorfbewohner-Vorschauen erlaubt."))
    previews = []
    for token in tokens:
        payload = _load_preview({"preview_token": token}, deps, world_path)
        blocked = deps.require_server_guard_current(payload)
        if blocked is not None:
            return [], blocked
        previews.append(payload)
    if sum(len(preview["selection"]) for preview in previews) > MAX_SELECTION:
        raise ValueError(t("Pro Speichervorgang sind höchstens 1000 Dorfbewohner-Auswahlen erlaubt."))
    return previews, None


def save_villagers(data: dict, deps: VillagerRouteDeps) -> Any:
    def work():
        blocked = deps.require_world_write_allowed()
        if blocked is not None:
            return blocked
        world_path = deps.json_string(data, "world_path")
        ensure_valid_world_path(world_path)
        payload = _load_preview(data, deps, world_path)
        # The preview's guard is authoritative, never a newer client-supplied
        # token that could accidentally bless an old selection after a restart.
        blocked = deps.require_server_guard_current(payload)
        if blocked is not None:
            return blocked
        blocked = deps.presence_conflict_response(data, world_path=world_path, same_player_only=False)
        if blocked is not None:
            return blocked
        result = villager_service.save(
            deps.service,
            world_path,
            world_revision=payload["world_revision"],
            selection=payload["selection"],
            changes=payload["changes"],
            expected_plan_digest=payload["plan_digest"],
            pre_write_check=lambda: deps.require_final_world_write_allowed("Dorfbewohner speichern"),
        )
        _audit(
            deps,
            "villagers.save",
            "success" if result["success"] else "partial",
            world_path=world_path,
            details={
                "changed_count": result.get("changed_count"),
                "backup_file": result.get("backup_file"),
                "write_committed": result.get("write_committed"),
                "validation_failed": result.get("validation_failed", False),
            },
        )
        return deps.jsonify(result), 200 if result["success"] else 500

    return _run("villagers.save", data, deps, work)


def save_preferences(data: dict, deps: VillagerRouteDeps) -> Any:
    def work():
        world_path = deps.json_string(data, "world_path")
        ensure_valid_world_path(world_path)
        result = deps.preferences.save(world_path, revision=data.get("revision"), aliases=data.get("aliases"), regions=data.get("regions"))
        return deps.jsonify({"success": True, "preferences": result})

    return _run("villagers.preferences", data, deps, work)
