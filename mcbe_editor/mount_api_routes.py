"""Handlers for experimental mount API routes.

Route registration belongs in main.py.  This module validates request payloads
and delegates preview/write work to the mount domain helpers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import amulet_nbt as nbt

from .api_errors import add_exception_cleanup_details, error_payload
from .bedrock_nbt import load_player_nbt
from .db import close_db_preserving_active_exception
from .i18n import t
from .mount_placement import placement_safety_from_preview, refine_preview_placement
from .mount_write import (
    CREATE_MODE_SYNTHETIC_FULL,
    MOUNT_WRITE_LABELS,
    build_horse_mount_record,
    create_horse_mount_with_service,
    normalize_create_mode,
    validate_horse_mount_write,
)
from .mounts import OVERWORLD_DIMENSION_ID, build_mount_preview
from .players import decode_player_key


def _default_blocked_none(*_args, **_kwargs):
    return None


def _default_final_write_allowed(_action_label: str):
    return None


class _DefaultFinalWriteGateBlockedError(ValueError):
    write_gate = {}


def _default_server_guard_snapshot() -> dict[str, object]:
    return {"server_guard_epoch": 0, "server_guard_token": ""}


@dataclass(frozen=True)
class MountRouteDeps:
    service: Any
    jsonify: Callable[..., Any]
    api_error: Callable[..., Any]
    log_api_exception: Callable[[str, Exception], None]
    json_string: Callable[..., str]
    require_world_db_access_allowed: Callable[[], Any]
    audit_event: Callable[..., None]
    server_online_epoch: Callable[[], int]
    require_world_write_allowed: Callable[[], Any] = _default_blocked_none
    require_server_guard_current: Callable[[dict], Any] = _default_blocked_none
    require_final_world_write_allowed: Callable[[str], Any] = _default_final_write_allowed
    presence_conflict_response: Callable[..., Any] = _default_blocked_none
    final_write_gate_blocked_error: type[Exception] = _DefaultFinalWriteGateBlockedError
    world_db_access_gate: Callable[[], dict] | None = None
    db_access_block_response: Callable[[dict], Any] = _default_blocked_none
    server_guard_snapshot: Callable[[], dict[str, object]] = _default_server_guard_snapshot


def _tag_value(value: Any, fallback: Any = None) -> Any:
    if value is None:
        return fallback
    data = getattr(value, "py_data", None)
    if data is not None:
        return data
    data = getattr(value, "value", None)
    if data is not None and not callable(data):
        return data
    return fallback


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _read_float_list(player_tag: Any, tag_name: str, limit: int) -> list[float] | None:
    try:
        value = player_tag.get(tag_name)
    except AttributeError:
        return None
    if not isinstance(value, nbt.ListTag):
        return None
    result: list[float] = []
    for item in list(value)[:limit]:
        number = _finite_float(_tag_value(item))
        if number is None:
            return None
        result.append(number)
    return result if result else None


def _read_int_tag(player_tag: Any, *tag_names: str) -> int | None:
    for tag_name in tag_names:
        try:
            value = player_tag.get(tag_name)
        except AttributeError:
            continue
        if not isinstance(value, (nbt.ByteTag, nbt.ShortTag, nbt.IntTag, nbt.LongTag)):
            continue
        data = _tag_value(value)
        if isinstance(data, bool):
            continue
        try:
            return int(data)
        except (TypeError, ValueError):
            continue
    return None


def _enrich_mount_snapshot_from_player_nbt(deps: MountRouteDeps, world_path: str, encoded_player_key: str, player_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Read authoritative placement context directly from the current player NBT."""

    stats = player_snapshot.get("stats") if isinstance(player_snapshot.get("stats"), dict) else None
    if stats is None:
        raise ValueError("Spielerposition fehlt. Bitte Spieler neu laden.")
    db = None
    try:
        raw_player_key = decode_player_key(encoded_player_key)
        db = deps.service._open_db_readonly(world_path)
        player_bytes = deps.service._read_player(db, raw_player_key)
        player_tag = load_player_nbt(player_bytes).tag
        position = _read_float_list(player_tag, "Pos", 3)
        if position is None or len(position) != 3:
            raise ValueError("Spielerposition fehlt oder ist ungültig. Mount-Vorschau wurde sicherheitshalber abgebrochen.")
        rotation = _read_float_list(player_tag, "Rotation", 2)
        dimension_id = _read_int_tag(player_tag, "DimensionId", "dimension_id", "dimension")
        enriched_stats = {**stats, "pos": position}
        if rotation is not None:
            enriched_stats["rotation"] = rotation
        if dimension_id is not None:
            enriched_stats["dimension_id"] = dimension_id
        return {**player_snapshot, "stats": enriched_stats}
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Aktuelle Spielerposition konnte nicht sicher aus dem Player-NBT gelesen werden.") from exc
    finally:
        close_db_preserving_active_exception(db, context="Mount-Vorschau: Spielerposition laden")


def _annotate_preview_with_chunk_probe(deps: MountRouteDeps, world_path: str, preview: dict[str, Any]) -> dict[str, Any]:
    db = None
    result = preview
    try:
        db = deps.service._open_db_readonly(world_path)
        result = refine_preview_placement(db, preview)
    except Exception:
        result = preview
    finally:
        try:
            close_db_preserving_active_exception(db, context="Optionale Mount-Blockprüfung")
        except Exception:
            # Die Blockprüfung ist eine konservative Zusatzannotation. Auch ein
            # reiner Close-Fehler darf daher die eigentliche Vorschau nicht in
            # einen vollständigen API-Fehler verwandeln.
            result = preview
    return result


def _preview_from_request(data: dict, deps: MountRouteDeps):
    world_path = deps.json_string(data, "world_path")
    player_key = deps.json_string(data, "player_key")
    mount_type = deps.json_string(data, "mount_type", "minecraft:horse")
    player_snapshot = deps.service.load_player(world_path, player_key)
    player_snapshot = _enrich_mount_snapshot_from_player_nbt(deps, world_path, player_key, player_snapshot)
    result = build_mount_preview(
        player_snapshot,
        player_key,
        mount_type=mount_type,
        preferred_offset=data.get("preferred_offset"),
        placement_radius=data.get("placement_radius"),
    )
    result = _annotate_preview_with_chunk_probe(deps, world_path, result)
    guard = deps.server_guard_snapshot()
    result["server_guard_epoch"] = int(guard.get("server_guard_epoch") or deps.server_online_epoch())
    result["server_guard_token"] = str(guard.get("server_guard_token") or "")
    return world_path, player_key, result


def _require_overworld_context(preview: dict[str, Any]) -> None:
    dimension_id = preview.get("dimension_id")
    if isinstance(dimension_id, bool):
        return
    if isinstance(dimension_id, int) and dimension_id != OVERWORLD_DIMENSION_ID:
        raise ValueError("Mount-Create ist aktuell nur im Overworld-Kontext erlaubt. Wechsle vor dem Erzeugen in die Overworld.")


def _allow_unchecked_placement(data: dict[str, Any]) -> bool:
    return data.get("allow_unchecked_placement") is True


def _strict_boolean(data: dict[str, Any], key: str, default: bool = False) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} muss ein Boolean sein.")
    return value


def preview_mount(data: dict, deps: MountRouteDeps):
    gate = deps.world_db_access_gate() if deps.world_db_access_gate is not None else None
    if gate is not None:
        if not gate.get("read_allowed", gate.get("allowed", False)):
            return deps.db_access_block_response(gate)
    else:
        blocked = deps.require_world_db_access_allowed()
        if blocked:
            return blocked
    try:
        world_path, player_key, result = _preview_from_request(data, deps)
        if gate is not None:
            status = gate.get("server_status") or {}
            stale = status.get("status") == "online" and (gate.get("config") or {}).get("require_server_offline") is True
            epoch = int(gate.get("server_guard_epoch") or 0)
            result["server_guard_epoch"] = max(0, epoch - 1) if stale else epoch
            result["server_guard_token"] = str((gate.get("_server_guard_previous_token") or "") if stale else (gate.get("server_guard_token") or ""))
        placement_search = result.get("placement_search", {}) if isinstance(result.get("placement_search"), dict) else {}
        deps.audit_event(
            "mount.preview",
            "success",
            world_path=world_path,
            player_key=player_key,
            details={
                "mount_type": result.get("mount_type"),
                "selected_candidate_id": result.get("selected_candidate_id"),
                "create_available": result.get("create_available"),
                "placement_radius": placement_search.get("radius"),
                "prefers_view_direction": placement_search.get("prefers_view_direction"),
                "block_check": placement_search.get("block_check"),
                "vertical_search": placement_search.get("vertical_search"),
                "footprint_check": placement_search.get("footprint_check"),
                "radius_scan": placement_search.get("radius_scan"),
            },
        )
        return deps.jsonify(result)
    except ValueError as exc:
        deps.audit_event("mount.preview", "failure", world_path=data.get("world_path"), player_key=data.get("player_key"), error=str(exc))
        return deps.api_error(exc)
    except Exception as exc:
        deps.log_api_exception("mount.preview", exc)
        deps.audit_event("mount.preview", "failure", world_path=data.get("world_path"), player_key=data.get("player_key"), error=str(exc))
        return deps.api_error(f"Fehler beim Erzeugen der Mount-Vorschau: {exc}", 500)


def create_mount(data: dict, deps: MountRouteDeps):
    blocked = deps.require_world_write_allowed()
    if blocked:
        return blocked
    try:
        world_path, player_key, preview = _preview_from_request(data, deps)
        create_mode = normalize_create_mode(data.get("create_mode") or CREATE_MODE_SYNTHETIC_FULL)
        horse_profile = data.get("horse_profile")
        mount_stats = data.get("mount_stats")
        tamed = _strict_boolean(data, "tamed")
        if not preview.get("create_available"):
            raise ValueError("Create ist für diesen Mount-Typ oder diese Dimension aktuell deaktiviert.")
        _require_overworld_context(preview)
        placement_safety = placement_safety_from_preview(preview)
        if placement_safety.get("safe_to_place") is False:
            raise ValueError(str(placement_safety.get("message") or "Das Mount kann an der gewählten Position nicht sicher platziert werden."))
        if placement_safety.get("safe_to_place") is None and not _allow_unchecked_placement(data):
            raise ValueError("Mount-Create abgelehnt: Die gewählte Position ist ungeprüft. Bestätige ungeprüfte Platzierung explizit und versuche es erneut.")
        blocked = deps.require_server_guard_current(data)
        if blocked:
            deps.audit_event("mount.create", "blocked", world_path=world_path, player_key=player_key, details={"reason": "server_guard"})
            return blocked
        conflict = deps.presence_conflict_response(data, world_path=world_path, player_key=player_key, same_player_only=False)
        if conflict:
            deps.audit_event("mount.create", "blocked", world_path=world_path, player_key=player_key, details={"reason": "presence_conflict"})
            return conflict
        blocked = deps.require_world_write_allowed()
        if blocked:
            deps.audit_event("mount.create", "blocked", world_path=world_path, player_key=player_key, details={"reason": "write_gate_recheck"})
            return blocked
        result = create_horse_mount_with_service(
            deps.service,
            world_path,
            player_key,
            preview,
            create_mode=create_mode,
            horse_profile=horse_profile,
            mount_stats=mount_stats,
            tamed=tamed,
            pre_write_check=lambda: deps.require_final_world_write_allowed("Mount erzeugen"),
        )
        result["placement_safety"] = placement_safety
        validation = result.get("post_create_validation") if isinstance(result.get("post_create_validation"), dict) else {}
        placement_search = preview.get("placement_search", {}) if isinstance(preview.get("placement_search"), dict) else {}
        validation_failed = result.get("validation_failed") is True
        if validation_failed:
            result.update(
                error_payload(
                    result.get("error") or "Mount wurde geschrieben, aber die Nachvalidierung ist fehlgeschlagen.",
                    code="mount_post_write_validation_failed",
                )
            )
        deps.audit_event(
            "mount.create",
            "partial" if validation_failed else "success",
            world_path=world_path,
            player_key=player_key,
            details={
                "mount_type": result.get("mount_type"),
                "backup_file": result.get("backup_file"),
                "actor_key_hex": result.get("actor_key_hex"),
                "digp_key_hex": result.get("digp_key_hex"),
                "create_mode_requested": result.get("create_mode_requested"),
                "create_mode_effective": result.get("create_mode_effective"),
                "template_identifier": result.get("template_identifier"),
                "horse_profile": result.get("horse_profile"),
                "mount_stats": result.get("mount_stats"),
                "tamed": result.get("tamed"),
                "post_create_validation_ok": validation.get("ok"),
                "placement_radius": placement_search.get("radius"),
                "prefers_view_direction": placement_search.get("prefers_view_direction"),
                "placement_safety_status": placement_safety.get("status"),
                "allow_unchecked_placement": _allow_unchecked_placement(data),
                "block_check": placement_safety.get("block_check"),
                "vertical_search": placement_search.get("vertical_search"),
                "footprint_check": placement_search.get("footprint_check"),
                "radius_scan": placement_search.get("radius_scan"),
            },
        )
        response = deps.jsonify(result)
        return (response, 500) if validation_failed else response
    except deps.final_write_gate_blocked_error as exc:
        message = str(exc)
        deps.audit_event(
            "mount.create",
            "blocked",
            world_path=data.get("world_path"),
            player_key=data.get("player_key"),
            details={"reason": "final_write_gate"},
            error=message,
        )
        payload = error_payload(message, code="final_write_gate_blocked")
        payload["write_gate"] = exc.write_gate
        add_exception_cleanup_details(payload, exc)
        return deps.jsonify(payload), 409
    except ValueError as exc:
        deps.audit_event("mount.create", "failure", world_path=data.get("world_path"), player_key=data.get("player_key"), error=str(exc))
        if getattr(exc, "cleanup_warning", None):
            return deps.jsonify(add_exception_cleanup_details(error_payload(str(exc), code="mount_create_failed"), exc)), 400
        return deps.api_error(exc)
    except Exception as exc:
        deps.log_api_exception("mount.create", exc)
        deps.audit_event("mount.create", "failure", world_path=data.get("world_path"), player_key=data.get("player_key"), error=str(exc))
        if getattr(exc, "cleanup_warning", None):
            payload = add_exception_cleanup_details(
                error_payload(
                    "Fehler beim experimentellen Erzeugen des Mounts: {error}",
                    code="mount_create_failed",
                    params={"error": t(str(exc))},
                ),
                exc,
            )
            return deps.jsonify(payload), 500
        return deps.api_error(f"Fehler beim experimentellen Erzeugen des Mounts: {exc}", 500)


class _StagedMountDbView:
    def __init__(self, db):
        self.db = db
        self.writes: dict[bytes, bytes] = {}

    def get(self, key: bytes) -> bytes:
        if key in self.writes:
            return self.writes[key]
        return self.db.get(key)

    def iter_items(self):
        staged_keys = set(self.writes)
        for key, value in self.db.iter_items():
            if key not in staged_keys:
                yield key, value
        yield from self.writes.items()


def save_workspace(data: dict, deps: MountRouteDeps, player_deps):
    blocked = deps.require_world_write_allowed()
    if blocked:
        deps.audit_event(
            "workspace.save",
            "blocked",
            world_path=data.get("world_path"),
            player_key=data.get("player_key"),
            details={"reason": "write_gate"},
        )
        return blocked
    try:
        world_path = player_deps.json_string(data, "world_path")
        player_key = player_deps.json_string(data, "player_key")
        mounts = data.get("mounts")
        if not isinstance(mounts, list):
            raise ValueError("mounts muss eine Liste sein.")
        if len(mounts) > 32:
            raise ValueError("Pro Speichervorgang sind höchstens 32 Mounts erlaubt.")
        stats = data.get("stats")
        if mounts and isinstance(stats, dict) and ("pos" in stats or "dimension_id" in stats):
            raise ValueError(
                t(
                    "Standortänderung und Mount-Erzeugung können nicht gemeinsam gespeichert werden. "
                    "Speichere zuerst den neuen Spielerstandort, lade den Spieler neu und erstelle danach eine neue Mount-Vorschau."
                )
            )

        blocked = deps.require_server_guard_current(data)
        if blocked:
            deps.audit_event(
                "workspace.save",
                "blocked",
                world_path=world_path,
                player_key=player_key,
                details={"reason": "server_guard"},
            )
            return blocked
        conflict = deps.presence_conflict_response(data, world_path=world_path, player_key=player_key, same_player_only=False)
        if conflict:
            deps.audit_event(
                "workspace.save",
                "blocked",
                world_path=world_path,
                player_key=player_key,
                details={"reason": "presence_conflict"},
            )
            return conflict
        blocked = deps.require_world_write_allowed()
        if blocked:
            deps.audit_event(
                "workspace.save",
                "blocked",
                world_path=world_path,
                player_key=player_key,
                details={"reason": "write_gate_recheck"},
            )
            return blocked

        specs = []
        positions = set()
        for mount in mounts:
            if not isinstance(mount, dict):
                raise ValueError("Jeder Mount-Entwurf muss ein Objekt sein.")
            request_data = {**mount, "world_path": world_path, "player_key": player_key}
            _world_path, _player_key, preview = _preview_from_request(request_data, deps)
            if not preview.get("create_available"):
                raise ValueError("Create ist für diesen Mount-Typ oder diese Dimension aktuell deaktiviert.")
            _require_overworld_context(preview)
            placement_safety = placement_safety_from_preview(preview)
            if placement_safety.get("safe_to_place") is False:
                raise ValueError(str(placement_safety.get("message") or "Ein vorgemerkter Mount ist nicht sicher platzierbar."))
            if placement_safety.get("safe_to_place") is None and not _allow_unchecked_placement(request_data):
                raise ValueError(t("Speichern abgelehnt: Eine Mount-Position ist ungeprüft und nicht explizit bestätigt."))
            position = preview.get("selected_position") or {}
            position_key = tuple(round(float(position.get(axis)), 3) for axis in ("x", "y", "z"))
            if position_key in positions:
                raise ValueError(t("Speichern abgelehnt: Zwei Mounts verwenden dieselbe Position."))
            positions.add(position_key)
            specs.append(
                {
                    "preview": preview,
                    "placement_safety": placement_safety,
                    "create_mode": normalize_create_mode(mount.get("create_mode") or CREATE_MODE_SYNTHETIC_FULL),
                    "horse_profile": mount.get("horse_profile"),
                    "mount_stats": mount.get("mount_stats"),
                    "tamed": _strict_boolean(mount, "tamed"),
                }
            )

        def build_extra_batch(db, decoded_player_key):
            staged = _StagedMountDbView(db)
            player_tag = load_player_nbt(deps.service._read_player(db, decoded_player_key)).tag
            owner_unique_id = _tag_value(player_tag.get("UniqueID")) if "UniqueID" in player_tag else None
            records = []
            results = []
            for spec in specs:
                preview = spec["preview"]
                tamed = spec["tamed"]
                record = build_horse_mount_record(
                    staged,
                    preview.get("selected_position"),
                    create_mode=spec["create_mode"],
                    horse_profile=spec["horse_profile"],
                    mount_type=preview.get("mount_type"),
                    mount_stats=spec["mount_stats"],
                    tamed=tamed,
                    owner_unique_id=owner_unique_id if tamed else None,
                )
                staged.writes[record.actor_key] = record.actor_value
                staged.writes[record.digp_key] = record.digp_value
                records.append(record)
                results.append(
                    {
                        "mount_type": record.mount_type,
                        "mount_label": MOUNT_WRITE_LABELS[record.mount_type],
                        "selected_position": record.position,
                        "horse_profile": record.horse_profile,
                        "mount_stats": record.mount_stats,
                        "tamed": record.tamed,
                        "placement_safety": spec["placement_safety"],
                    }
                )
            return {"writes": staged.writes, "records": records, "result": {"mounts": results}}

        def validate_extra_batch(db, batch):
            for result, record in zip(batch["result"]["mounts"], batch["records"], strict=True):
                try:
                    validation = validate_horse_mount_write(
                        db,
                        record,
                        expected_digp_value=batch["writes"].get(record.digp_key),
                    )
                except Exception as exc:
                    # save_player hat den gemeinsamen Batch an dieser Stelle
                    # bereits committed. Die Ausnahme muss daher als
                    # Post-Write-Teilfehler bis zum Client transportiert werden.
                    validation = {
                        "ok": False,
                        "checks": {},
                        "details": {"exception_type": type(exc).__name__},
                        "errors": [t("Nachvalidierung konnte nicht abgeschlossen werden: {error}", error=t(str(exc)))],
                    }
                result["post_create_validation"] = validation
                if not validation["ok"]:
                    result["validation_warning"] = t("Mount wurde atomar geschrieben, konnte danach aber nicht vollständig bestätigt werden: ") + ", ".join(
                        validation["errors"]
                    )

        result = player_deps.service.save_player(
            world_path,
            player_key,
            data.get("inventory"),
            data.get("stats", {}),
            ender_chest_list=data.get("ender_chest"),
            effects_list=data.get("effects"),
            abilities_dict=data.get("abilities"),
            base_revision=data.get("base_revision"),
            allow_create_inventory=player_deps.json_bool(data, "allow_create_inventory", False),
            allow_create_ender_chest=player_deps.json_bool(data, "allow_create_ender_chest", False),
            allow_create_effects=player_deps.json_bool(data, "allow_create_effects", False),
            allow_create_abilities=player_deps.json_bool(data, "allow_create_abilities", False),
            root_equipment_editable=player_deps.json_bool(data, "root_equipment_editable", False),
            pre_write_check=lambda: deps.require_final_world_write_allowed("Workspace speichern"),
            extra_batch_builder=build_extra_batch if specs else None,
            extra_batch_validator=validate_extra_batch if specs else None,
        )
        workspace = result.get("workspace") or {"mounts": []}
        result["mounts"] = workspace.get("mounts", [])
        result["atomic_batch"] = bool(specs)
        failed_validations = []
        for mount in result["mounts"]:
            if not isinstance(mount, dict):
                continue
            validation = mount.get("post_create_validation")
            if not isinstance(validation, dict) or validation.get("ok") is not True:
                failed_validations.append(mount)
        # save_player kann bereits einen Post-Write-Fehler (DB schließen, Backup-Pruning,
        # Validator-Wrapper) signalisiert haben. Ein bestätigter Commit darf danach nie
        # mehr als sicher wiederholbarer Fehler an den Client gemeldet werden.
        committed_write_failure = result.get("write_committed") is True and result.get("success") is False
        committed_failure = bool(failed_validations) or committed_write_failure
        if committed_failure:
            message = result.get("error") or t(
                "Die Änderungen wurden geschrieben, aber mindestens ein Mount konnte danach nicht validiert werden. "
                "Nicht erneut speichern; stelle bei Zweifeln das angegebene Backup wieder her."
            )
            result.update(
                {
                    "write_committed": True,
                    "validation_failed": True,
                    **error_payload(message, code="workspace_post_write_validation_failed"),
                }
            )
        deps.audit_event(
            "workspace.save",
            "partial" if committed_failure else "success",
            world_path=world_path,
            player_key=player_key,
            details={"mount_count": len(specs), "backup_file": result.get("backup_file"), "atomic_batch": bool(specs)},
        )
        response = deps.jsonify(result)
        return (response, 500) if committed_failure else response
    except deps.final_write_gate_blocked_error as exc:
        deps.audit_event(
            "workspace.save",
            "blocked",
            world_path=data.get("world_path"),
            player_key=data.get("player_key"),
            details={"reason": "final_write_gate"},
            error=str(exc),
        )
        payload = error_payload(str(exc), code="final_write_gate_blocked")
        payload["write_gate"] = exc.write_gate
        add_exception_cleanup_details(payload, exc)
        return deps.jsonify(payload), 409
    except ValueError as exc:
        deps.audit_event(
            "workspace.save",
            "failure",
            world_path=data.get("world_path"),
            player_key=data.get("player_key"),
            error=str(exc),
        )
        if getattr(exc, "cleanup_warning", None):
            return deps.jsonify(add_exception_cleanup_details(error_payload(str(exc), code="workspace_save_failed"), exc)), 400
        return deps.api_error(exc)
    except Exception as exc:
        deps.log_api_exception("workspace.save", exc)
        deps.audit_event(
            "workspace.save",
            "failure",
            world_path=data.get("world_path"),
            player_key=data.get("player_key"),
            error=str(exc),
        )
        if getattr(exc, "cleanup_warning", None):
            payload = add_exception_cleanup_details(
                error_payload(
                    "Fehler beim gemeinsamen Speichern der Änderungen: {error}",
                    code="workspace_save_failed",
                    params={"error": t(str(exc))},
                ),
                exc,
            )
            return deps.jsonify(payload), 500
        return deps.api_error(t("Fehler beim gemeinsamen Speichern der Änderungen: {error}", error=exc), 500)
