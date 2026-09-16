"""Transport production item NBT through disposable engine-created carriers.

This adapter deliberately makes no claim to exercise player login or the full
player service. It uses the real item builder, codec, backup and native write
batch. It accepts only the runner's fresh world, never a user world argument.
"""

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

from .cases import CARRIER_PREFIX, CONTROL_NAME, expected_snapshot
from .protocol import ProbeError
from .runner import WORLD_NAME, sha256


def configure_worker_catalog(run_dir: Path) -> None:
    """Give the fresh worker one immutable bundled-data snapshot.

    Normal external databases receive bundled curation on load. A proposed
    catalog must instead be tested as the prospective bundled database, using
    the unchanged production loader and validation. This binding is confined
    to this standalone process and never affects the running application.
    """
    if "mcbe_editor.item_data" in sys.modules:
        raise ProbeError("The catalog must be bound before loading editor item data")
    from mcbe_editor import runtime_data

    path = run_dir.resolve(strict=True) / "catalog.json"
    report = json.loads((path.parent / "run.json").read_text(encoding="utf-8"))
    if sha256(path) != report.get("catalog_sha256"):
        raise ProbeError("Catalog changed since engine measurement")
    runtime_data.BUNDLED_ITEM_DB_JSON = path

    from mcbe_editor import item_data

    expected_limits = json.loads(path.read_text(encoding="utf-8"))["stack_limits"]
    if expected_limits != item_data.STACK_LIMITS:
        raise ProbeError("The editor did not load the exact measured stack limits")


def value(compound, key, default=None):
    tag = compound.get(key)
    return default if tag is None else tag.py_data


def read_records(world: Path) -> dict[bytes, bytes]:
    from mcbe_editor.leveldb_readonly import ReadonlyLevelDbAdapter

    db = ReadonlyLevelDbAdapter(str(world / "db"))
    try:
        return dict(db.iter_items())
    finally:
        db.close()


def indexed_items(items) -> dict:
    from mcbe_editor import nbt

    indexed = {}
    for item in items:
        if not isinstance(item, nbt.CompoundTag) or not isinstance(item.get("Slot"), nbt.ByteTag):
            raise ProbeError("Carrier item has an invalid slot encoding")
        slot = value(item, "Slot")
        if not 0 <= slot <= 26 or slot in indexed:
            raise ProbeError("Carrier contains a duplicated or invalid slot")
        indexed[slot] = item
    return indexed


def carriers(records: dict[bytes, bytes], expected_names: set[str]) -> dict:
    from mcbe_editor import nbt
    from mcbe_editor.bedrock_nbt import load_player_nbt

    found = {}
    for key, raw in records.items():
        if not key.startswith(b"actorprefix"):
            continue
        named = load_player_nbt(raw)
        root = named.tag
        name = value(root, "CustomName", "")
        if name not in expected_names:
            continue
        if name in found or value(root, "identifier") != "minecraft:chest_minecart":
            raise ProbeError("Missing, duplicated or wrong engine carrier")
        containers = []
        for field in ("ChestItems", "Inventory", "Items"):
            items = root.get(field)
            if not isinstance(items, nbt.ListTag):
                continue
            controls = [item for item in items if isinstance(item, nbt.CompoundTag) and value(item, "Slot") == 26]
            if len(controls) != 1:
                continue
            control = controls[0]
            tag = control.get("tag", nbt.CompoundTag())
            display = tag.get("display", nbt.CompoundTag())
            if value(control, "Name") == "minecraft:stone" and value(control, "Count") == 1 and value(display, "Name") == CONTROL_NAME:
                containers.append(field)
        if len(containers) != 1:
            raise ProbeError(f"Unknown carrier inventory schema in {name}")
        found[name] = (key, named, containers[0])
    if found.keys() != expected_names:
        raise ProbeError(f"Engine persisted {len(found)}/{len(expected_names)} carriers")
    return found


def build_item_writes(records: dict[bytes, bytes], cases: list[dict]) -> dict[bytes, bytes]:
    from mcbe_editor import nbt
    from mcbe_editor.bedrock_nbt import save_player_nbt
    from mcbe_editor.inventory import build_inventory_nbt, nbt_to_json
    from mcbe_editor.item_data import ENCHANTMENTS

    found = carriers(records, {case["carrier"] for case in cases})
    grouped = {}
    for case in cases:
        grouped.setdefault(case["carrier"], []).append(case)
    writes = {}
    for name, (key, named, field) in found.items():
        original_items = deepcopy(named.tag[field])
        # Freeze the comparison before any editor code receives these mutable
        # tags. A builder that accidentally mutates its input must not redefine
        # the reference against which its output is checked.
        before_bytes = {slot: item.save_to() for slot, item in indexed_items(original_items).items()}
        wrapper = nbt.CompoundTag({"Inventory": original_items})
        parsed, _ = nbt_to_json(wrapper)
        payloads = dict(parsed)
        for case in grouped[name]:
            slot = case["slot"]
            existing = payloads.get(slot)
            if case["mode"] == "create" and existing is not None:
                raise ProbeError("Engine reference unexpectedly filled an editor creation slot")
            if case["mode"] != "create" and existing is None:
                raise ProbeError("Engine reference omitted an existing item")
            if case["mode"] == "preserve":
                continue
            payloads[slot] = {
                **(existing or {}), "slot": slot, "name": case["id"], "count": case["amount"],
                "damage": case["damage"], "display_name": case["name"], "lore": case["lore"], "enchantments": [],
            }
        result = build_inventory_nbt(wrapper, list(payloads.values()), ENCHANTMENTS)
        after = indexed_items(result)
        for slot in [26, *(case["slot"] for case in grouped[name] if case["mode"] == "preserve")]:
            if slot not in before_bytes or slot not in after or before_bytes[slot] != after[slot].save_to():
                raise ProbeError("Editor changed an untouched engine-created item")
        # Replacing this one field must leave all other typed actor data intact.
        named.tag[field] = result
        serialized = save_player_nbt(named)
        if serialized != records[key]:
            writes[key] = serialized
    if not writes:
        raise ProbeError("Editor produced no item writes")
    return writes


def disk_snapshot(item, case: dict) -> dict:
    """Read the tested fields independently of the production item builder."""
    from mcbe_editor import nbt

    def compound(parent, key):
        result = parent.get(key, nbt.CompoundTag())
        if not isinstance(result, nbt.CompoundTag):
            raise ProbeError(f"Saved NBT has an invalid {key} compound")
        return result

    if not isinstance(item.get("Count"), nbt.ByteTag) or value(item, "Count") != case["amount"]:
        raise ProbeError(f"Saved NBT changed the amount in {case['case_id']}")
    if not isinstance(item.get("Name"), nbt.StringTag):
        raise ProbeError("Saved NBT has an invalid item name")
    tag = compound(item, "tag")
    display = compound(tag, "display")
    name = display.get("Name", nbt.StringTag(""))
    lore = display.get("Lore", nbt.ListTag([]))
    if not isinstance(name, nbt.StringTag) or not isinstance(lore, nbt.ListTag) or any(not isinstance(line, nbt.StringTag) for line in lore):
        raise ProbeError("Saved NBT has invalid display text")
    # No enchanted cases are generated yet. Do not silently discard unknown
    # enchantment entries as a permissive application reader might do.
    for field in ("ench", "enchantments"):
        entries = tag.get(field, nbt.ListTag([]))
        if not isinstance(entries, nbt.ListTag) or entries:
            raise ProbeError("Saved NBT contains unexpected enchantments")
    damage = 0
    if case.get("durable"):
        damage_tag = tag.get("Damage", nbt.IntTag(0))
        if not isinstance(damage_tag, nbt.IntTag):
            raise ProbeError("Saved NBT has invalid durability")
        damage = damage_tag.py_data
    return {"id": value(item, "Name"), "amount": value(item, "Count"), "name": name.py_data,
            "lore": [line.py_data for line in lore], "damage": damage, "enchantments": []}


def empty_saved_slot(item) -> bool:
    """BDS can persist unused carrier slots as explicit, typed empty records."""
    from mcbe_editor import nbt

    return (isinstance(item.get("Name"), nbt.StringTag) and value(item, "Name") == ""
            and isinstance(item.get("Count"), nbt.ByteTag) and value(item, "Count") == 0
            and set(item) <= {"Slot", "Name", "Count", "Damage", "WasPickedUp"}
            and ("Damage" not in item or isinstance(item["Damage"], nbt.ShortTag) and value(item, "Damage") == 0)
            and ("WasPickedUp" not in item or isinstance(item["WasPickedUp"], nbt.ByteTag) and value(item, "WasPickedUp") == 0))


def verify_saved_items(records: dict[bytes, bytes], cases: list[dict]) -> dict:
    found = carriers(records, {case["carrier"] for case in cases})
    indexed = {name: {slot: item for slot, item in indexed_items(named.tag[field]).items() if not empty_saved_slot(item)}
               for name, (_key, named, field) in found.items()}
    for name, items in indexed.items():
        expected_slots = {26} | {case["slot"] for case in cases if case["carrier"] == name}
        if items.keys() != expected_slots:
            raise ProbeError("Saved NBT lost items or contains unexpected slots")
        control = {"case_id": f"{name}/control", "id": "minecraft:stone", "amount": 1, "name": CONTROL_NAME,
                   "lore": [], "damage": 0, "enchantments": []}
        if disk_snapshot(items[26], control) != expected_snapshot(control):
            raise ProbeError("Saved NBT changed an untouched control")
    digest = hashlib.sha256()
    for case in cases:
        item = indexed[case["carrier"]][case["slot"]]
        if disk_snapshot(item, case) != expected_snapshot(case):
            raise ProbeError(f"Saved NBT changed item semantics in {case['case_id']}")
        digest.update(case["case_id"].encode() + item.save_to())
    return {"status": "pass", "cases": len(cases), "carriers": len(found), "item_nbt_sha256": digest.hexdigest()}


def verify_rejected_counts(cases: list[dict]) -> int:
    from mcbe_editor import nbt
    from mcbe_editor.inventory import build_inventory_nbt
    from mcbe_editor.item_data import ENCHANTMENTS, get_max_stack

    empty = nbt.CompoundTag({"Inventory": nbt.ListTag([])})
    checked = 0
    for item_id in sorted({case["id"] for case in cases}):
        for count in sorted({-1, 0, get_max_stack(item_id) + 1, 128}):
            try:
                build_inventory_nbt(empty, [{"slot": 0, "name": item_id, "count": count, "damage": 0}], ENCHANTMENTS)
            except ValueError:
                checked += 1
            else:
                raise ProbeError(f"Editor accepted invalid new amount {count} for {item_id}")
    return checked


def run(run_dir: Path, action: str) -> dict:
    from mcbe_editor.backup import create_backup
    from mcbe_editor.db import LevelDbAdapter
    from mcbe_editor.write_transaction import WritePlan, WriteState

    run_dir = run_dir.resolve(strict=True)
    report = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if report.get("format") != "mcbe-engine-check-v1" or report.get("phases", {}).get("seed") != "pass":
        raise ProbeError("A completed engine seed phase is required")
    case_path = run_dir / "cases.json"
    if sha256(case_path) != report.get("cases_sha256"):
        raise ProbeError("Roundtrip cases changed since engine seeding")
    if report.get("catalog_sha256") and sha256(run_dir / "catalog.json") != report["catalog_sha256"]:
        raise ProbeError("Catalog changed since engine measurement")
    cases = json.loads(case_path.read_text(encoding="utf-8"))
    if not cases or any(not case["carrier"].startswith(CARRIER_PREFIX) for case in cases):
        raise ProbeError("Invalid generated test cases")
    world = run_dir / "server" / "worlds" / WORLD_NAME
    if any(not path.resolve(strict=True).is_relative_to(run_dir) or path.is_symlink() or path.is_junction()
           for path in (world, world / "db")):
        raise ProbeError("World escaped the disposable run directory")
    before = read_records(world)
    if action == "verify":
        return verify_saved_items(before, cases)
    writes = build_item_writes(before, cases)
    rejected_counts = verify_rejected_counts(cases)
    backup = create_backup(str(world), prune_after=False)
    if not Path(backup).is_file():
        raise ProbeError("Pre-write backup missing")
    db = LevelDbAdapter(str(world / "db"))
    try:
        for key in writes:
            if db.get(key) != before[key]:
                raise ProbeError("Carrier changed between read and write phases")
        state = WriteState()
        state.execute(db, WritePlan(writes))
    finally:
        db.close()
    after = read_records(world)
    if before.keys() != after.keys() or any(after[key] != writes.get(key, raw) for key, raw in before.items()):
        raise ProbeError("Editor write changed unrelated database records or failed its reread")
    return {**verify_saved_items(after, cases), "changed_records": len(writes), "backup_created": True,
            "untouched_records_verified": len(before) - len(writes), "rejected_count_cases": rejected_counts}


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[2] not in {"edit", "verify"}:
        raise SystemExit("Usage: python -m scripts.engine_checks.nbt_roundtrip RUN_DIR edit|verify")
    configure_worker_catalog(Path(sys.argv[1]))
    print(json.dumps(run(Path(sys.argv[1]), sys.argv[2]), sort_keys=True))
