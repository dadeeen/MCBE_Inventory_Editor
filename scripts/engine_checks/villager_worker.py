"""Isolated production-service writes and independent native villager oracles."""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import sys
import zipfile
from copy import deepcopy
from pathlib import Path

from .protocol import ProbeError
from .villager_profile import edit_groups, expected_snapshots, validate_case_plan

STABLE_FIELDS = ("identifier", "Variant", "MarkVariant", "Tags", "Armor", "Mainhand", "Offhand", "TradeTier", "TradeExperience", "Offers")
HEALTH_FIELDS = {"Current", "Max", "DefaultMax"}
STATE_FORMAT = "mcbe-villager-state-v1"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProbeError(message)


def _digest(tag) -> str:
    return hashlib.sha256(tag.save_to()).hexdigest()


def health_attribute(root):
    from mcbe_editor import nbt

    attributes = root.get("Attributes")
    require(isinstance(attributes, nbt.ListTag), "Villager Attributes is not a native list")
    matching = [
        attribute
        for attribute in attributes
        if isinstance(attribute, nbt.CompoundTag) and isinstance(attribute.get("Name"), nbt.StringTag) and attribute["Name"].py_data == "minecraft:health"
    ]
    require(len(matching) == 1, "Missing or duplicate native villager health attribute")
    return matching[0]


def health_snapshot(root) -> dict:
    """Read sparse engine fields; malformed present fields never become defaults."""
    from mcbe_editor import nbt

    attribute = health_attribute(root)
    current_key = "Current" if "Current" in attribute else "Base"
    maximum_key = "Max" if "Max" in attribute else "DefaultMax"
    for key in {current_key, maximum_key, "Base"} | ({"DefaultMax"} if "DefaultMax" in attribute else set()):
        value = attribute.get(key)
        require(isinstance(value, nbt.FloatTag) and math.isfinite(value.py_data), "Invalid typed native villager health: " + key)
    return {"current": attribute[current_key].py_data, "maximum": attribute[maximum_key].py_data}


def inventory_snapshot(root) -> list:
    from mcbe_editor import nbt

    chest = root.get("ChestItems")
    require(
        isinstance(chest, nbt.ListTag) and chest.list_data_type == nbt.CompoundTag.tag_id and len(chest) == 8, "Native villager inventory needs eight slots"
    )
    items = []
    for slot, item in enumerate(chest):
        require(isinstance(item, nbt.CompoundTag), "Malformed native supply item")
        require(isinstance(item.get("Slot"), nbt.ByteTag) and item["Slot"].py_data == slot, "Duplicated, missing or reordered native supply slot")
        require(isinstance(item.get("Name"), nbt.StringTag) and isinstance(item.get("Count"), nbt.ByteTag), "Wrong native supply identity/count type")
        require(isinstance(item.get("Damage"), nbt.ShortTag) and item["Damage"].py_data == 0, "Unexpected native supply Damage")
        require(isinstance(item.get("WasPickedUp"), nbt.ByteTag) and item["WasPickedUp"].py_data in (0, 1), "Unexpected native supply pickup bookkeeping")
        name, count = item["Name"].py_data, item["Count"].py_data
        require((name == "" and count == 0) or (name != "" and 1 <= count <= 64), "Invalid native supply identity/count")
        items.append(None if name == "" else {"name": name, "count": count})
    return items


def find_actors(records: dict[bytes, bytes], cases: list[dict], *, tagged: bool = False) -> dict:
    from mcbe_editor import nbt
    from mcbe_editor.bedrock_nbt import load_player_nbt

    expected = {case["name"] for case in cases}
    found = {}
    indexes = {key: raw for key, raw in records.items() if key.startswith(b"digp")}
    for key, raw in records.items():
        if not key.startswith(b"actorprefix"):
            continue
        root = load_player_nbt(raw).tag
        if tagged:
            # Name-editing cases require independent test tags. Never fall back
            # to CustomName when a required tag disappears.
            tags = root.get("Tags")
            if not isinstance(tags, nbt.ListTag):
                continue
            matches = [tag.py_data for tag in tags if isinstance(tag, nbt.StringTag) and tag.py_data in expected]
            if not matches:
                continue
            require(len(matches) == 1, "Ambiguous native villager test tag")
            name = matches[0]
        else:
            # The natural-village client profile retains its fixed fixture
            # names and does not add tags to naturally generated villagers.
            name_tag = root.get("CustomName")
            if not isinstance(name_tag, nbt.StringTag) or name_tag.py_data not in expected:
                continue
            name = name_tag.py_data
        require(name not in found, "Duplicate native villager test identity")
        require(
            isinstance(root.get("identifier"), nbt.StringTag) and root["identifier"].py_data in {"minecraft:villager", "minecraft:villager_v2"},
            "Wrong actor type",
        )
        require(isinstance(root.get("UniqueID"), nbt.LongTag), "Missing typed native actor identity")
        require(len(key) == len(b"actorprefix") + 8, "Unexpected native actor storage key")
        matches = [index for index, raw in indexes.items() for offset in range(0, len(raw), 8) if raw[offset : offset + 8] == key[-8:]]
        require(len(matches) == 1, "Native villager lacks one unambiguous actor index reference")
        position = root.get("Pos")
        require(
            isinstance(position, nbt.ListTag)
            and len(position) == 3
            and all(isinstance(value, nbt.FloatTag) and math.isfinite(value.py_data) for value in position),
            "Malformed native villager position",
        )
        chunk = (math.floor(position[0].py_data / 16), math.floor(position[2].py_data / 16))
        reference = matches[0]
        require(len(reference) in (12, 16) and len(indexes[reference]) % 8 == 0, "Malformed native villager actor index")
        dimension = struct.unpack("<i", reference[12:])[0] if len(reference) == 16 else 0
        require(dimension == 0 and struct.unpack("<ii", reference[4:12]) == chunk, "Native villager actor index disagrees with Overworld position")
        for field in ("DimensionId", "dimension_id", "dimension"):
            if field in root:
                require(isinstance(root[field], nbt.IntTag) and root[field].py_data == 0, "Native villager left its planned dimension")
        components = root.get("internalComponents")
        if components is not None:
            require(isinstance(components, nbt.CompoundTag), "Malformed native actor components")
            component = components.get("EntityStorageKeyComponent")
            if component is not None:
                require(
                    isinstance(component, nbt.CompoundTag) and isinstance(component.get("StorageKey"), nbt.StringTag), "Malformed native actor storage identity"
                )
                storage_key = component["StorageKey"]
                raw_key = storage_key._raw if storage_key._raw is not None else nbt.utf8_escape_encoder(storage_key.py_data)
                require(raw_key == key[-8:], "Native actor storage identity changed")
        found[name] = (key, root)
    require(found.keys() == expected, "Missing persisted native villager")
    require(len({root["UniqueID"].py_data for _, root in found.values()}) == len(found), "Duplicated native villager identity")
    return found


def actor_baseline(key: bytes, root) -> dict:
    attribute = health_attribute(root)
    return {
        "key": key.hex(),
        "unique_id": str(root["UniqueID"].py_data),
        "chunk": [math.floor(root["Pos"][0].py_data / 16), math.floor(root["Pos"][2].py_data / 16)],
        "stable": {field: _digest(root[field]) if field in root else None for field in STABLE_FIELDS},
        "health_fixed": {field: _digest(value) for field, value in attribute.items() if field not in HEALTH_FIELDS},
        "other_attributes": [_digest(value) for value in root["Attributes"] if value is not attribute],
    }


def verify_records(records: dict, cases: list[dict], expected: dict, baselines: dict | None = None, *, initialize_offers: bool = False) -> dict:
    """Check a fixed independent expectation, never copy actual values into it."""
    validate_case_plan(cases)
    require(set(expected) == {case["name"] for case in cases}, "Incomplete villager disk expectation")
    found = find_actors(records, cases, tagged=True)
    require(baselines is None or set(baselines) == set(found), "Incomplete native actor baseline")
    actual_baselines, initialization_changes = {}, []
    for name, (key, root) in found.items():
        from mcbe_editor import nbt

        name_tag = root.get("CustomName")
        require(name_tag is None or isinstance(name_tag, nbt.StringTag), "Invalid native villager name type")
        actual = {**health_snapshot(root), "items": inventory_snapshot(root), "name": name_tag.py_data if name_tag is not None else ""}
        require(actual == expected[name], "Saved villager name/health/supplies differ: " + name)
        attribute = health_attribute(root)
        if "DefaultMax" in attribute:
            require(attribute["DefaultMax"].py_data == expected[name]["maximum"], "Saved DefaultMax differs from planned health maximum")
        baseline = actor_baseline(key, root)
        if baselines is not None:
            previous = baselines[name]
            require(baseline["key"] == previous["key"] and baseline["unique_id"] == previous["unique_id"], "Engine changed villager identity")
            expected_baseline = deepcopy(previous)
            if initialize_offers and baseline["stable"]["Offers"] != previous["stable"]["Offers"]:
                initialization_changes.append(
                    {"case": name, "field": "Offers", "before_sha256": previous["stable"]["Offers"], "after_sha256": baseline["stable"]["Offers"]}
                )
                expected_baseline["stable"]["Offers"] = baseline["stable"]["Offers"]
            require(baseline == expected_baseline, "Engine changed untouched villager data: " + name)
        actual_baselines[name] = baseline
    return {"status": "pass", "cases": len(found), "baselines": actual_baselines, "initialization_changes": initialization_changes}


def verify_write_preservation(before: dict, after: dict, cases: list[dict], selected: list[dict], changes: dict, *, tagged: bool = False) -> None:
    """Compare frozen pre-write bytes independently of the production write plan."""
    old, new = find_actors(before, cases, tagged=tagged), find_actors(after, cases, tagged=tagged)
    chosen = {case["name"] for case in selected}
    changed_keys = {old[name][0] for name in chosen}
    require(before.keys() == after.keys(), "Villager writer changed database keys")
    require(all(after[key] == raw for key, raw in before.items() if key not in changed_keys), "Villager writer changed an unrelated record or actor index")
    for name in chosen:
        key, original = old[name]
        new_key, updated = new[name]
        require(key == new_key and before[key] != after[key], "Planned villager write did not change its original actor")
        field = "ChestItems" if "inventory" in changes else "CustomName" if "name" in changes else "Attributes"
        require(set(original) - {field} == set(updated) - {field}, "Villager writer changed unrelated actor field names")
        require(all(original[key].save_to() == updated[key].save_to() for key in original if key != field), "Villager writer changed an unrelated actor field")
        if field == "ChestItems":
            slots = {patch["slot"] for patch in changes["inventory"]}
            for slot in range(8):
                old_item, new_item = original[field][slot], updated[field][slot]
                require(old_item["WasPickedUp"].save_to() == new_item["WasPickedUp"].save_to(), "Writer changed supply pickup bookkeeping")
                if slot not in slots:
                    require(old_item.save_to() == new_item.save_to(), "Writer changed an untouched supply slot")
        elif field == "Attributes":
            require(len(original[field]) == len(updated[field]), "Writer changed attribute count")
            old_health, new_health = health_attribute(original), health_attribute(updated)
            require(set(old_health) <= set(new_health) and set(new_health) - set(old_health) <= {"Current", "Max"}, "Writer added unsupported health fields")
            for old_attr, new_attr in zip(original[field], updated[field], strict=True):
                if old_attr is not old_health:
                    require(old_attr.save_to() == new_attr.save_to(), "Writer changed an unrelated attribute")
            require(
                all(old_health[key].save_to() == new_health[key].save_to() for key in old_health if key not in HEALTH_FIELDS),
                "Writer changed health Base or unrelated metadata",
            )


def _read_records(world: Path) -> dict:
    from .nbt_roundtrip import read_records

    return read_records(world)


def _inputs(run_dir: Path) -> tuple[Path, dict, list[dict]]:
    from .runner import WORLD_NAME, sha256, source_hashes

    require(not run_dir.is_symlink() and not run_dir.is_junction(), "Villager run directory may not be a link")
    run_dir = run_dir.resolve(strict=True)
    report = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    require(report.get("format") == "mcbe-engine-check-v1" and report.get("suite") == "villagers", "Worker requires a native villager run")
    require(isinstance(report.get("run_id"), str) and bool(re.fullmatch(r"[a-f0-9]{32}", report["run_id"])), "Missing villager run identity")
    require(report.get("phases", {}).get("seed") == "pass", "Completed live villager seeding is required")
    require(all(report.get("editor", {}).get(key) == value for key, value in source_hashes().items()), "Villager probe/editor sources changed")
    require(sha256(run_dir / "cases.json") == report.get("cases_sha256"), "Villager cases changed after seeding")
    require(sha256(run_dir / "catalog.json") == report.get("catalog_sha256"), "Villager catalog changed after measurement")
    cases = json.loads((run_dir / "cases.json").read_text(encoding="utf-8"))
    validate_case_plan(cases)
    world = run_dir / "server" / "worlds" / WORLD_NAME
    for path in (run_dir / "server", run_dir / "server/worlds", world, world / "db"):
        require(
            path.resolve(strict=True).is_relative_to(run_dir) and not path.is_symlink() and not path.is_junction(), "Villager world escaped its disposable run"
        )
    return world, report, cases


def _exercise_service(world: Path, cases: list[dict], state: dict, action: str) -> dict:
    from mcbe_editor import item_data, villager_service
    from mcbe_editor.backup import get_backups_dir
    from mcbe_editor.services import BedrockEditorService

    service = BedrockEditorService(item_data.ITEMS, item_data.ENCHANTMENTS)
    stage = "edited" if action == "edit" else "revised"
    expected = expected_snapshots(cases, state["stage"])
    groups = edit_groups(cases, action)
    counts = {"backed_up_saves": 0, "no_op_checks": 0, "stale_revision_rejections": 0, "changed_actors": 0, "intermediate_state_checks": 0}

    def prepare(selected, changes):
        scan = villager_service.scan(service, str(world))
        identities = {state["actors"][case["name"]]["unique_id"] for case in selected}
        chosen = [row for row in scan["villagers"] if row["unique_id"] in identities]
        require(len(chosen) == len(identities), "Production scan omitted a planned villager")
        selection = [{key: row[key] for key in ("id", "revision")} for row in chosen]
        plan = villager_service.preview(service, str(world), scan["world_revision"], selection, changes)
        arguments = {
            "world_revision": scan["world_revision"],
            "selection": selection,
            "changes": changes,
            "expected_plan_digest": villager_service.plan_digest(plan),
        }
        return plan, arguments

    if action == "revise":
        return _exercise_workspace(world, cases, state, service, groups, prepare)

    for selected in groups:
        changes = selected[0][action]
        require(all(case[action] == changes for case in selected), "Villager batch contains conflicting changes")
        before = _read_records(world)
        plan, arguments = prepare(selected, changes)
        require(_read_records(world) == before, "Villager scan/preview mutated database records")
        require(
            plan.summary == {"selected": len(selected), "changed": len(selected), "unchanged": 0, "skipped": 0},
            "Production editor skipped planned villager cases",
        )
        result = villager_service.save(service, str(world), **arguments, pre_write_check=lambda: None)
        require(
            result.get("success") is True and result.get("write_committed") is True and result.get("validation", {}).get("ok") is True,
            "Villager service write did not verify success",
        )
        after = _read_records(world)
        verify_write_preservation(before, after, cases, selected, changes, tagged=True)
        for case in selected:
            expected[case["name"]] = deepcopy(case[stage])
        verify_records(after, cases, expected, state["actors"])
        counts["intermediate_state_checks"] += 1
        backup_directory = Path(get_backups_dir(str(world)))
        backup = backup_directory / result["backup_file"]
        require(backup.is_file(), "Villager service omitted its pre-write backup")
        with zipfile.ZipFile(backup) as archive:
            require(archive.testzip() is None and any(name.endswith("level.dat") for name in archive.namelist()), "Invalid villager backup")
        counts["backed_up_saves"] += 1
        counts["changed_actors"] += len(selected)
        backup_names = {path.name for path in backup_directory.iterdir()}
        try:
            villager_service.save(service, str(world), **arguments, pre_write_check=lambda: None)
        except villager_service.VillagerSnapshotStaleError:
            counts["stale_revision_rejections"] += 1
        else:
            raise ProbeError("Villager service accepted a stale world revision")
        require(
            _read_records(world) == after and {path.name for path in backup_directory.iterdir()} == backup_names,
            "Rejected stale write changed database or backups",
        )
        no_op, fresh_arguments = prepare(selected, changes)
        require(no_op.summary["unchanged"] == len(selected) and not no_op.writes, "Identical villager changes are not a no-op")
        repeated = villager_service.save(service, str(world), **fresh_arguments, pre_write_check=lambda: None)
        require(repeated.get("success") is True and repeated.get("write_committed") is False, "Villager no-op attempted a write")
        require(
            _read_records(world) == after and {path.name for path in backup_directory.iterdir()} == backup_names, "Villager no-op changed database or backups"
        )
        counts["no_op_checks"] += 1
    require(counts["backed_up_saves"] == len(groups) and counts["changed_actors"] == sum(map(len, groups)), "Incomplete villager service coverage")
    verify_records(_read_records(world), cases, expected_snapshots(cases, stage), state["actors"])
    return {"status": "pass", "cases": len(cases), "stage": stage, **counts}


def _exercise_workspace(world, cases, state, service, groups, prepare):
    """Stage all native revisions through the signed API and commit one batch.

    The runner has stopped BDS before invoking this isolated worker. Only the
    offline/presence adapters are fixed here; preview signing, request handling,
    backup, serialization, writer and reopened verification are production code.
    """
    import secrets
    from types import SimpleNamespace

    from mcbe_editor import mount_api_routes, villager_api_routes, villager_service
    from mcbe_editor.backup import get_backups_dir
    from mcbe_editor.service_errors import WriteNotAttemptedError

    def nothing(*_args, **_kwargs):
        return None

    common = dict(
        service=service,
        jsonify=lambda data: data,
        api_error=lambda error, status=400: ({"error": str(error)}, status),
        log_api_exception=nothing,
        json_string=lambda data, name: data[name],
        audit_event=nothing,
        require_world_write_allowed=nothing,
        require_server_guard_current=nothing,
        require_final_world_write_allowed=nothing,
        presence_conflict_response=nothing,
        final_write_gate_blocked_error=WriteNotAttemptedError,
    )
    villagers = villager_api_routes.VillagerRouteDeps(
        **common,
        preferences=None,
        secret_key=secrets.token_bytes(32),
        session_identity=lambda: "isolated-engine-worker",
        world_db_access_gate=lambda: {"allowed": True, "read_allowed": True},
        db_access_block_response=lambda gate: ({"error": str(gate)}, 409),
    )
    mounts = mount_api_routes.MountRouteDeps(**common, require_world_db_access_allowed=nothing, server_online_epoch=lambda: 0)
    player = SimpleNamespace(service=service, json_string=common["json_string"])
    before = _read_records(world)
    tokens = []
    for selected in groups:
        _, arguments = prepare(selected, selected[0]["revise"])
        response = villager_api_routes.preview_villagers({"world_path": str(world), **arguments}, villagers)
        require(isinstance(response, dict) and response.get("success") and response.get("preview_token"), "Central preview failed")
        tokens.append(response["preview_token"])
    require(_read_records(world) == before, "Staging central previews wrote to the native world")
    backup_directory = Path(get_backups_dir(str(world)))
    request = {"world_path": str(world), "villager_previews": tokens}
    result, status = mount_api_routes.save_workspace(request, mounts, player, villagers)
    require(status == 200 and result.get("success") and result.get("write_committed") and result.get("atomic_batch"), "Central workspace save failed")
    backup = backup_directory / result["backup_file"]
    with zipfile.ZipFile(backup) as archive:
        require(archive.testzip() is None and any(name.endswith("level.dat") for name in archive.namelist()), "Invalid central workspace backup")
    after = _read_records(world)
    verify_records(after, cases, expected_snapshots(cases, "revised"), state["actors"])
    # Compare each changed actor to its original independently; all other keys
    # (including chunk indexes) must remain exactly as the engine wrote them.
    found = find_actors(before, cases, tagged=True)
    changed_keys = set()
    for selected in groups:
        keys = {found[case["name"]][0] for case in selected}
        isolated = {**before, **{key: after[key] for key in keys}}
        verify_write_preservation(before, isolated, cases, selected, selected[0]["revise"], tagged=True)
        changed_keys.update(keys)
    require(
        all(after[key] == value for key, value in before.items() if key not in changed_keys) and set(after) == set(before),
        "Central save changed unrelated records",
    )
    backup_names = set(backup_directory.iterdir())
    rejected, status = mount_api_routes.save_workspace(request, mounts, player, villagers)
    require(status == 409 and rejected.get("code") == "villager_snapshot_stale", "Central save accepted a consumed snapshot")
    for selected in groups:
        plan, arguments = prepare(selected, selected[0]["revise"])
        require(not plan.writes, "Central persisted change does not read back as a no-op")
        result = villager_service.save(service, str(world), **arguments, pre_write_check=lambda: None)
        require(result.get("success") and result.get("write_committed") is False, "Repeated central values caused a write")
    require(_read_records(world) == after and set(backup_directory.iterdir()) == backup_names, "Stale/no-op central checks changed world or backups")
    return {
        "status": "pass",
        "cases": len(cases),
        "stage": "revised",
        "backed_up_saves": 1,
        "no_op_checks": len(groups),
        "stale_revision_rejections": 1,
        "changed_actors": sum(map(len, groups)),
        "intermediate_state_checks": 1,
        "central_workspace": True,
    }


def run(run_dir: Path, action: str) -> dict:
    from .runner import write_json

    require(action in {"seed", "warmup1", "warmup2", "edit", "verify", "revise"}, "Unknown villager worker action")
    world, report, cases = _inputs(run_dir)
    state_path = run_dir / "villager-state.json"
    binding = {"run_id": report["run_id"], "cases_sha256": report["cases_sha256"], "catalog_sha256": report["catalog_sha256"], "editor": report["editor"]}
    if action == "seed":
        require(not state_path.exists(), "Villager baseline may only be seeded once")
        result = verify_records(_read_records(world), cases, expected_snapshots(cases, "seed"))
        state = {
            "format": STATE_FORMAT,
            **binding,
            "checkpoint": "seed",
            "stage": "seed",
            "actors": result["baselines"],
            "initialization_changes": [],
            "writes": [],
        }
        write_json(state_path, state)
        return {"status": "pass", "cases": len(cases), "stage": "seed"}
    require(state_path.is_file() and not state_path.is_symlink() and not state_path.is_junction(), "Missing private villager baseline")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    require(
        state.get("format") == STATE_FORMAT and all(state.get(key) == value for key, value in binding.items()), "Villager baseline belongs to different inputs"
    )
    if action in {"warmup1", "warmup2"}:
        require(
            state.get("checkpoint") == ("seed" if action == "warmup1" else "warmup1") and not state["writes"] and state["stage"] == "seed",
            "Warmup may only precede editor writes",
        )
        result = verify_records(_read_records(world), cases, expected_snapshots(cases, "seed"), state["actors"], initialize_offers=action == "warmup1")
        state.update(checkpoint=action, actors=result["baselines"])
        state["initialization_changes"].extend(result["initialization_changes"])
        write_json(state_path, state)
        return {"status": "pass", "cases": len(cases), "initialization_changes": len(result["initialization_changes"])}
    if action == "verify":
        require(state.get("checkpoint") in {"edit", "revise"}, "Villager verification requires completed production writes")
        verify_records(_read_records(world), cases, expected_snapshots(cases, state["stage"]), state["actors"])
        return {"status": "pass", "cases": len(cases), "stage": state["stage"]}
    require(state.get("checkpoint") == ("warmup2" if action == "edit" else "edit"), "Villager write action repeated or out of order")
    if action == "revise":
        require(
            all(report.get("phases", {}).get(phase) == "pass" for phase in ("reload1", "reload2")), "Villager revision requires two verified engine reloads"
        )
    verify_records(_read_records(world), cases, expected_snapshots(cases, state["stage"]), state["actors"])
    result = _exercise_service(world, cases, state, action)
    state.update(stage=result["stage"], checkpoint=action)
    state["writes"].append({"action": action, **result})
    write_json(state_path, state)
    return result


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python -m scripts.engine_checks.villager_worker RUN_DIR seed|warmup1|warmup2|edit|verify|revise")
    from .nbt_roundtrip import configure_worker_catalog

    directory = Path(sys.argv[1])
    _inputs(directory)
    configure_worker_catalog(directory)
    print(json.dumps(run(directory, sys.argv[2]), sort_keys=True))
