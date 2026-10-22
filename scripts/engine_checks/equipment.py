"""Real-client equipment cases and an independent dense-list disk observer.

Only the disposable client profile uses these cases. Reading Armor/Offhand here
does not use the production root-equipment parser or its slot classification.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .cases import append_case, expected_snapshot
from .protocol import ProbeError

# Verified dense-list positions and the production service's public UI slots.
EQUIPMENT_SLOTS = {
    "Head": ("Armor", 0, 103),
    "Chest": ("Armor", 1, 102),
    "Legs": ("Armor", 2, 101),
    "Feet": ("Armor", 3, 100),
    "Offhand": ("Offhand", 0, -106),
}


def make_equipment_cases(observations: dict, limits: dict) -> list[dict]:
    profiles = (
        ("Head", "diamond_helmet", "preserve", 0),
        ("Chest", "diamond_chestplate", "decorate", 13),
        ("Legs", "diamond_leggings", "clear", 0),
        ("Feet", "diamond_boots", "create", 1),
        ("Offhand", "shield", "decorate", 7),
    )
    cases = []
    for slot, name, mode, damage in profiles:
        item_id = "minecraft:" + name
        measured = observations.get(item_id, {})
        if type(measured.get("max_amount")) is not int or measured["max_amount"] != 1 or type(limits.get(item_id)) is not int or limits[item_id] != 1:
            raise ProbeError(f"Equipment profile requires a measured, curated stack limit for {item_id}")
        if type(measured.get("max_durability")) is not int or measured["max_durability"] <= damage:
            raise ProbeError(f"Equipment profile requires measured durability for {item_id}")
        append_case(
            cases,
            observations,
            item_id,
            mode,
            1,
            case_id="equipment_" + slot.lower(),
            equipment_slot=slot,
            damage=damage,
            name="" if mode in {"preserve", "clear"} else "§bAusrüstung · " + slot + " 世界",
            lore=[] if mode in {"preserve", "clear"} else ["Equipment roundtrip ✓", "Grüße aus dem Editor"],
            enchantments=[{"id": "unbreaking", "level": 3}] if slot == "Chest" else [],
        )
    return cases


def equipment_items(root) -> dict:
    """Read the five fixed dense slots, rejecting legacy or ambiguous shapes."""
    from mcbe_editor import nbt

    from .nbt_roundtrip import empty_saved_slot

    for field, lengths in (("Armor", {4, 5}), ("Offhand", {1})):
        entries = root.get(field)
        if type(entries) is not nbt.ListTag or len(entries) not in lengths or any(type(item) is not nbt.CompoundTag for item in entries):
            raise ProbeError(f"Client equipment has an invalid dense {field} list")
    if "OffHandItem" in root:
        raise ProbeError("Client equipment contains an ambiguous legacy OffHandItem")
    result = {}
    for slot, (field, index, _ui_slot) in EQUIPMENT_SLOTS.items():
        item = root[field][index]
        if "Slot" in item:
            raise ProbeError("Client equipment dense entries must not contain Slot keys")
        if empty_saved_slot(item):
            result[slot] = None
            continue
        if (
            type(item.get("Name")) is not nbt.StringTag
            or item["Name"].py_data in {"", "air", "minecraft:air"}
            or type(item.get("Count")) is not nbt.ByteTag
            or item["Count"].py_data != 1
            or "Damage" in item
            and (type(item["Damage"]) is not nbt.ShortTag or item["Damage"].py_data != 0)
            or "WasPickedUp" in item
            and type(item["WasPickedUp"]) is not nbt.ByteTag
        ):
            raise ProbeError("Client equipment has invalid typed item fields")
        result[slot] = item
    return result


def verify_equipment(root, cases: list[dict], *, seed: bool = False) -> dict:
    from .nbt_roundtrip import disk_snapshot

    planned = {case.get("equipment_slot") for case in cases}
    if len(cases) != len(EQUIPMENT_SLOTS) or planned != EQUIPMENT_SLOTS.keys():
        raise ProbeError("Client equipment plan must cover each fixed slot exactly once")
    items = equipment_items(root)
    for case in cases:
        item = items[case["equipment_slot"]]
        actual = None if item is None else disk_snapshot(item, case)
        if actual != expected_snapshot(case, seed=seed):
            raise ProbeError("Client equipment changed tested item semantics: " + case["case_id"])
    return {"status": "pass", "cases": len(cases)}


def exercise_equipment_service(world: Path, raw_key: bytes, cases: list[dict]) -> dict:
    """Edit real client Armor/Offhand through the unchanged production service."""
    from mcbe_editor.backup import resolve_backup_path
    from mcbe_editor.bedrock_nbt import load_player_nbt
    from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
    from mcbe_editor.players import encode_player_key
    from mcbe_editor.services import BedrockEditorService

    from .extended import ENCHANTMENT_IDS
    from .nbt_roundtrip import read_records

    before_records = read_records(world)
    before = load_player_nbt(before_records[raw_key]).tag
    verify_equipment(before, cases, seed=True)
    untouched = {field: tag.save_to() for field, tag in before.items() if field not in {"Armor", "Offhand"}}
    original_items = equipment_items(before)
    preserved = {case["equipment_slot"]: original_items[case["equipment_slot"]].save_to() for case in cases if case["mode"] == "preserve"}
    body = [item.save_to() for item in before["Armor"][4:]]
    service = BedrockEditorService(ITEMS, ENCHANTMENTS)
    key = encode_player_key(raw_key)
    loaded = service.load_player(str(world), key)
    inventory = deepcopy(loaded["inventory"])
    for case in cases:
        slot = EQUIPMENT_SLOTS[case["equipment_slot"]][2]
        if case["mode"] == "clear":
            if slot not in inventory:
                raise ProbeError("Player service did not expose equipment to clear")
            del inventory[slot]
        elif case["mode"] == "preserve":
            if slot not in inventory:
                raise ProbeError("Player service did not expose preserved equipment")
        else:
            inventory[slot] = {
                **inventory.get(slot, {}),
                "slot": slot,
                "name": case["id"],
                "count": case["amount"],
                "damage": case["damage"],
                "display_name": case["name"],
                "lore": case["lore"],
                "enchantments": [{"id": ENCHANTMENT_IDS[value["id"]], "lvl": value["level"]} for value in case["enchantments"]],
            }
    response = service.save_player(
        str(world),
        key,
        list(inventory.values()),
        {},
        ender_chest_list=list(loaded["ender_chest"].values()),
        base_revision=loaded["player_revision"],
        root_equipment_editable=True,
    )
    if (
        not response.get("success")
        or response.get("no_op")
        or not response.get("backup_file")
        or not Path(resolve_backup_path(str(world), response["backup_file"])).is_file()
    ):
        raise ProbeError("Equipment service did not complete a backed-up write")
    after_records = read_records(world)
    if before_records.keys() != after_records.keys() or any(after_records[key] != raw for key, raw in before_records.items() if key != raw_key):
        raise ProbeError("Equipment service changed unrelated database records")
    after = load_player_nbt(after_records[raw_key]).tag
    if {field: tag.save_to() for field, tag in after.items() if field not in {"Armor", "Offhand"}} != untouched:
        raise ProbeError("Equipment service changed unrelated player fields")
    verify_equipment(after, cases)
    saved_items = equipment_items(after)
    if any(saved_items[slot].save_to() != original for slot, original in preserved.items()) or [item.save_to() for item in after["Armor"][4:]] != body:
        raise ProbeError("Equipment service changed preserved equipment or the untouched body entry")
    loaded = service.load_player(str(world), key)
    response = service.save_player(
        str(world),
        key,
        list(loaded["inventory"].values()),
        {},
        ender_chest_list=list(loaded["ender_chest"].values()),
        base_revision=loaded["player_revision"],
        root_equipment_editable=True,
    )
    if response.get("no_op") is not True or response.get("backup_file") or read_records(world) != after_records:
        raise ProbeError("Unchanged equipment save wrote data or created a backup")
    return {"status": "pass", "cases": len(cases), "backed_up_saves": 1, "no_op_checks": 1}
