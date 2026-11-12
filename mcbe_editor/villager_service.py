"""Snapshot reads and guarded, atomic changes for existing villagers."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import nbt, read_operation
from .backup import create_backup, prune_backups, remove_backup_after_aborted_write
from .backup_consistency import source_snapshot
from .bedrock_nbt import LOAD_KWARGS, SAVE_KWARGS
from .db import close_db_preserving_active_exception
from .i18n import t
from .path_safety import is_linklike
from .service_errors import WriteOutcomeUnknownError, log_error_detail
from .villager_career import CAREER_FIELDS
from .villagers import HealthChangePlan, _scan, prepare_villager_changes
from .world import ensure_valid_world_path, world_fingerprint
from .write_transaction import WritePlan, WriteState


class VillagerSnapshotStaleError(ValueError):
    pass


class VillagerSnapshotUnavailableError(VillagerSnapshotStaleError):
    pass


def _career_world_reason(world_path: str) -> str | None:
    """Only the career editor assumes vanilla behavior and trading rules."""

    def read_file(name: str, limit: int) -> bytes:
        path = Path(world_path) / name
        if is_linklike(path):
            raise ValueError("Linked world rules")
        with path.open("rb") as source:
            raw = source.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("World rules exceed supported size")
        return raw

    try:
        try:
            packs = json.loads(read_file("world_behavior_packs.json", 1024 * 1024).decode("utf-8-sig"))
        except FileNotFoundError:
            packs = []
        if not isinstance(packs, list):
            raise ValueError("Unknown behavior pack list")
        if packs:
            return t("Beruf und Handelsstufe bleiben bei aktiven Behavior-Packs geschützt, da diese das Dorfbewohnerverhalten ändern können.")
        raw = read_file("level.dat", 8 * 1024 * 1024)
        if len(raw) < 8 or int.from_bytes(raw[4:8], "little") != len(raw) - 8:
            raise ValueError("Unknown level.dat header")
        root = nbt.load(raw[8:], **LOAD_KWARGS).tag
        if not isinstance(root, nbt.CompoundTag):
            raise ValueError("Unknown level.dat root")
        experiments = root.get("experiments", nbt.CompoundTag())
        if not isinstance(experiments, nbt.CompoundTag):
            raise ValueError("Unknown experiments")
        rebalance = experiments.get("villager_trades_rebalance", nbt.ByteTag(0))
        if not isinstance(rebalance, nbt.ByteTag) or rebalance.py_data not in (0, 1):
            raise ValueError("Unknown trade rebalance setting")
        if rebalance.py_data:
            return t("Der experimentelle Dorfbewohner-Handelsausgleich wird für Berufs- und Stufenänderungen noch nicht unterstützt.")
    except (OSError, ValueError, TypeError, RecursionError):
        return t("Die Weltregeln für Dorfbewohner konnten nicht eindeutig gelesen werden. Beruf und Handelsstufe bleiben geschützt.")
    return None


def _career_world_projection(row: dict[str, Any], reason: str | None) -> dict[str, Any]:
    if not reason:
        return row
    career = {**row.get("career", {}), "editable": False, "reason": reason, "can_set_tier_on_profession_change": False}
    for field in ("profession", "tier"):
        career.update({f"{field}_editable": False, f"{field}_reason": reason})
    return {**row, "career": career, "career_editable": False}


def assert_career_world_allowed(world_path: str, *, changes: Any = None, previews: list[dict] | None = None) -> None:
    requests = [changes] if previews is None else [preview.get("changes") for preview in previews]
    if any(isinstance(change, dict) and "career" in change for change in requests):
        reason = _career_world_reason(world_path)
        if reason:
            raise ValueError(reason)


def _assert_revision(world_path: str, expected: Any) -> str:
    actual = world_fingerprint(world_path)
    if not isinstance(expected, str) or not expected or actual != expected:
        raise VillagerSnapshotStaleError(t("Die Welt wurde seit dem Dorfbewohner-Scan verändert. Bitte erneut scannen."))
    return actual


def _read(service: Any, world_path: str, work: Callable[[Any], Any], *, expected_revision: str | None = None) -> tuple[Any, str]:
    ensure_valid_world_path(world_path)
    with service._locked_world(world_path):
        revision = world_fingerprint(world_path) if expected_revision is None else _assert_revision(world_path, expected_revision)
        db = None
        try:
            read_operation.checkpoint("opening")
            db = service._open_db_readonly(world_path)
            result = work(db)
        finally:
            close_db_preserving_active_exception(db, context="Dorfbewohner lesen")
        _assert_revision(world_path, revision)
        read_operation.checkpoint("finishing")
        return result, revision


def scan(service: Any, world_path: str) -> dict[str, Any]:
    directory = service._villager_directory
    (snapshot, career_reason), revision = _read(service, world_path, lambda db: (directory.snapshot(db), _career_world_reason(world_path)))
    directory.remember_scan(world_path, revision, snapshot)
    result = snapshot.result()
    if career_reason:
        result["villagers"] = [_career_world_projection(row, career_reason) for row in result["villagers"]]
        result["summary"]["editable"] = sum(row["editable"] or row["inventory_editable"] or row["name_editable"] for row in result["villagers"])
    return {**result, "world_revision": revision}


def map_players(service: Any, world_path: str, world_revision: str) -> dict[str, Any]:
    def read_map(db: Any) -> list[dict[str, Any]]:
        return [
            {field: player[field] for field in ("player_key", "label", "position", "dimension")}
            for player in service._scan_players(db)
            if player.get("position") is not None and player.get("dimension") is not None
        ]

    # Player markers describe the saved positions at map-open time. They do not
    # authorize edits or need to share the older villager scan's revision.
    result, revision = _read(service, world_path, read_map)
    return {"map_players": result, "world_revision": revision, "snapshot_stale": revision != world_revision}


def detail(service: Any, world_path: str, identifier: str, revision: str, world_revision: str) -> dict[str, Any]:
    ensure_valid_world_path(world_path)
    cached = service._villager_directory.scanned_detail(world_path, world_revision, identifier, revision)
    if cached is not None:
        return _career_world_projection(cached, _career_world_reason(world_path))
    # An evicted or oversized scan can still be read from disk if the exact
    # original world revision remains available. Never substitute newer data.
    try:
        result, _ = _read(service, world_path, lambda db: service._villager_directory.detail(db, identifier, revision), expected_revision=world_revision)
    except VillagerSnapshotStaleError as exc:
        raise VillagerSnapshotUnavailableError(t("Die Details dieses Scanstands sind nicht mehr verfügbar. Bitte erneut scannen.")) from exc
    return _career_world_projection(result, _career_world_reason(world_path))


def snapshot_is_current(world_path: str, revision: str) -> bool:
    try:
        return world_fingerprint(world_path) == revision
    except OSError:
        return False


def preview(service: Any, world_path: str, world_revision: str, selection: Any, changes: Any) -> HealthChangePlan:
    def prepare(db):
        assert_career_world_allowed(world_path, changes=changes)
        return prepare_villager_changes(db, selection, changes)

    result, _ = _read(service, world_path, prepare, expected_revision=world_revision)
    return result


def plan_digest(plan: HealthChangePlan) -> str:
    """Bind the signed preview to the exact before/after bytes, including indexes."""
    digest = hashlib.sha256()
    for marker, entries in ((b"before", plan.before_records), (b"after", plan.writes)):
        digest.update(marker)
        for key, value in sorted(entries.items()):
            digest.update(len(key).to_bytes(8, "little"))
            digest.update(key)
            digest.update(len(value).to_bytes(8, "little"))
            digest.update(value)
    return digest.hexdigest()


def _assert_plan(plan: HealthChangePlan, expected: str) -> None:
    if plan_digest(plan) != expected:
        raise VillagerSnapshotStaleError(t("Die Dorfbewohner passen nicht mehr zur bestätigten Vorschau. Bitte erneut scannen."))


def prepare_workspace_changes(db: Any, previews: list[dict]) -> HealthChangePlan:
    """Revalidate signed previews against the original snapshot, then compose them.

    Health, names, supplies and careers touch disjoint top-level fields. Never apply a second
    stale actor blob over the first change, and never silently pick a winner
    when two previews edit the same field of the same actor.
    """
    writes, before, rows, fields = {}, {}, [], set()
    summary = {name: 0 for name in ("selected", "changed", "skipped", "unchanged")}
    # All previews describe this same open database view. Discover identities,
    # indexes and villagers once per validation phase, not once per preview.
    # The save path calls us again after acquiring the writer lock, with a new
    # scan; no discovery state is reused across that boundary.
    snapshot = _scan(db) if previews else None
    for preview in previews:
        plan = prepare_villager_changes(db, preview["selection"], preview["changes"], _snapshot=snapshot)
        _assert_plan(plan, preview["plan_digest"])
        patch_fields = (
            CAREER_FIELDS
            if "career" in plan.changes
            else {"ChestItems" if "inventory" in plan.changes else "CustomName" if "name" in plan.changes else "Attributes"}
        )
        for key, value in plan.before_records.items():
            if key in before and before[key] != value:
                raise VillagerSnapshotStaleError(t("Die Dorfbewohner-Vorschauen verwenden unterschiedliche Weltstände."))
            before[key] = value
        for key, value in plan.writes.items():
            if any((key, field) in fields for field in patch_fields):
                raise ValueError(t("Mehrere Vormerkungen ändern denselben Dorfbewohner-Bereich. Entferne zuerst die ältere Vormerkung."))
            fields.update((key, field) for field in patch_fields)
            if key in writes:
                combined = nbt.load(writes[key], **LOAD_KWARGS)
                patch = nbt.load(value, **LOAD_KWARGS)
                for field in sorted(patch_fields):
                    if field in patch.tag:
                        combined.tag[field] = patch.tag[field]
                    elif field in combined.tag:
                        del combined.tag[field]
                writes[key] = combined.save_to(**SAVE_KWARGS)
            else:
                writes[key] = value
        rows.extend(plan.rows)
        for name in summary:
            summary[name] += plan.summary[name]
    return HealthChangePlan(writes, before, rows, {}, summary)


def workspace_preview(service: Any, world_path: str, previews: list[dict]) -> HealthChangePlan:
    revision = previews[0]["world_revision"]
    if any(preview["world_revision"] != revision for preview in previews):
        raise VillagerSnapshotStaleError(t("Die Dorfbewohner-Vorschauen verwenden unterschiedliche Weltstände."))

    def prepare(db):
        assert_career_world_allowed(world_path, previews=previews)
        return prepare_workspace_changes(db, previews)

    plan, _ = _read(service, world_path, prepare, expected_revision=revision)
    return plan


def _validate_records(db: Any, plan: HealthChangePlan) -> dict[str, bool]:
    written = all(db.get(key) == value for key, value in plan.writes.items())
    untouched = all(db.get(key) == value for key, value in plan.before_records.items() if key not in plan.writes)
    return {"written_records_match": written, "untouched_records_match": untouched}


def _post_write_result(service: Any, world_path: str, db: Any, plan: HealthChangePlan, backup_file: str) -> dict[str, Any]:
    """Every failure after execute retains an explicit committed outcome."""
    checks: dict[str, bool] = {}
    errors = []
    try:
        checks.update(_validate_records(db, plan))
    except Exception as exc:
        log_error_detail("villagers.save validation", exc)
        errors.append(t("Die direkte Nachprüfung der Dorfbewohner ist fehlgeschlagen."))
    try:
        db.close()
    except Exception as exc:
        log_error_detail("villagers.save close", exc)
        errors.append(t("Die Datenbank konnte nach dem Schreiben nicht sauber geschlossen werden."))
    # The writer's own in-memory view is insufficient proof. Open a fresh,
    # genuinely read-only reader and check the committed bytes on disk as well.
    verify_db = None
    try:
        verify_db = service._open_db_readonly(world_path)
        persisted = _validate_records(verify_db, plan)
        checks.update({f"reopened_{name}": ok for name, ok in persisted.items()})
    except Exception as exc:
        log_error_detail("villagers.save reopen validation", exc)
        errors.append(t("Die gespeicherten Dorfbewohner konnten nicht erneut eingelesen werden."))
    finally:
        if verify_db is not None:
            try:
                verify_db.close()
            except Exception as exc:
                log_error_detail("villagers.save reopen close", exc)
                errors.append(t("Die Datenbank konnte nach der Nachprüfung nicht sauber geschlossen werden."))
    valid = len(checks) == 4 and all(checks.values()) and not errors
    if valid:
        try:
            prune_backups(world_path, keep_paths=[backup_file])
        except Exception as exc:
            log_error_detail("villagers.save backup pruning", exc)
            errors.append(t("Die Änderung wurde geprüft; ältere Backups konnten nicht bereinigt werden."))
    success = valid and not errors
    message = (
        t("Die Dorfbewohner wurden gespeichert und erneut geprüft.")
        if success
        else t(
            "Die Änderung wurde geschrieben, aber die Nachprüfung oder Nachbereitung ist fehlgeschlagen. Nicht erneut speichern; zuerst Welt und Backup prüfen."
        )
    )
    result = {
        "success": success,
        "write_committed": True,
        "reload_required": True,
        "validation_failed": not valid,
        "validation": {"ok": valid, "checks": checks, "errors": errors},
        "backup_file": os.path.basename(backup_file),
        "changed_count": plan.summary["changed"],
        "skipped_count": plan.summary["skipped"],
        "unchanged_count": plan.summary["unchanged"],
        "message": message,
    }
    if not success:
        result.update(error=message, error_phase="post_write", code="villager_post_write_failed")
    return result


def save(
    service: Any,
    world_path: str,
    *,
    world_revision: str,
    selection: Any,
    changes: Any,
    expected_plan_digest: str,
    pre_write_check: Callable[[], None],
    previews: list[dict] | None = None,
) -> dict[str, Any]:
    def prepare(db):
        assert_career_world_allowed(world_path, changes=changes, previews=previews)
        return prepare_workspace_changes(db, previews) if previews is not None else prepare_villager_changes(db, selection, changes)

    def write_precondition() -> None:
        # Metadata and pack rules are outside LevelDB's lock. The adapter may
        # run a slow final server gate, so validate again after that gate.
        _assert_revision(world_path, world_revision)
        assert_career_world_allowed(world_path, changes=changes, previews=previews)

    ensure_valid_world_path(world_path)
    with service._locked_world(world_path):
        db = None
        backup_file = None
        state = WriteState()
        try:
            _assert_revision(world_path, world_revision)
            db = service._open_db_readonly(world_path)
            plan = prepare(db)
            _assert_plan(plan, expected_plan_digest)
            db.close()
            db = None
            _assert_revision(world_path, world_revision)
            if not plan.writes:
                return {"success": True, "write_committed": False, "changed_count": 0, "message": t("Es sind keine Änderungen erforderlich.")}

            before_backup = source_snapshot(world_path)
            pre_write_check()
            backup_file = create_backup(world_path, prune_after=False)
            if source_snapshot(world_path) != before_backup:
                raise VillagerSnapshotStaleError(t("Die Welt wurde während der Sicherung verändert. Bitte erneut scannen."))
            _assert_revision(world_path, world_revision)
            pre_write_check()
            db = service._open_db(world_path)
            # Opening an existing database takes its lock without changing the
            # revision. Close the backup-to-lock race even when an external
            # write touched only records outside the selected villagers.
            _assert_revision(world_path, world_revision)
            # Rebuild while holding the actual LevelDB writer lock. This repeats
            # identity/index/field checks, rather than trusting a browser payload.
            fresh_plan = prepare(db)
            _assert_plan(fresh_plan, expected_plan_digest)
            pre_write_check()
            state.execute(db, WritePlan(fresh_plan.writes, precondition=write_precondition))
            try:
                result = _post_write_result(service, world_path, db, fresh_plan, backup_file)
                db = None
                return result
            except Exception as exc:
                log_error_detail("villagers.save post_write", exc)
                with contextlib.suppress(Exception):
                    db.close()
                db = None
                message = t("Die Änderung wurde geschrieben, aber die Nachbereitung ist fehlgeschlagen. Nicht erneut speichern; zuerst Welt und Backup prüfen.")
                return {
                    "success": False,
                    "write_committed": True,
                    "reload_required": True,
                    "error_phase": "post_write",
                    "validation_failed": True,
                    "code": "villager_post_write_failed",
                    "error": message,
                    "message": message,
                    "backup_file": os.path.basename(backup_file),
                }
        except Exception as exc:
            if backup_file and not state.attempted:
                remove_backup_after_aborted_write(backup_file, exc, operation="villagers.save")
            if state.outcome_unknown:
                raise WriteOutcomeUnknownError(exc, backup_file=backup_file) from exc
            raise
        finally:
            close_db_preserving_active_exception(db, context="Dorfbewohner speichern")
