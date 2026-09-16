"""Exercise the production service against only a disposable runner world."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .extended import ENCHANTMENT_IDS
from .protocol import ProbeError
from .service_profile import assignments


def exercise_player_service(world: Path, raw_keys: tuple[bytes, ...], cases: list[dict]) -> tuple[list, dict]:
    from mcbe_editor.backup import resolve_backup_path
    from mcbe_editor.bedrock_nbt import load_player_nbt
    from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
    from mcbe_editor.players import encode_player_key
    from mcbe_editor.services import BedrockEditorService

    from .nbt_roundtrip import read_records

    before_records = read_records(world)
    locations = assignments(cases)
    service = BedrockEditorService(ITEMS, ENCHANTMENTS)
    saves = no_ops = stale_rejections = 0
    results = []

    def save(key, loaded, inventory, ender):
        nonlocal saves
        response = service.save_player(str(world), key, list(inventory.values()), {}, ender_chest_list=list(ender.values()),
                                       base_revision=loaded["player_revision"])
        if (not response.get("success") or response.get("no_op") or not response.get("backup_file")
                or not Path(resolve_backup_path(str(world), response["backup_file"])).is_file()):
            raise ProbeError("Player service did not complete a backed-up write")
        saves += 1

    for raw_key in raw_keys:
        original = load_player_nbt(read_records(world)[raw_key]).tag
        untouched = {name: tag.save_to() for name, tag in original.items() if name not in {"Inventory", "EnderChestInventory"}}
        key = encode_player_key(raw_key)
        loaded = service.load_player(str(world), key)
        original_revision = loaded["player_revision"]
        payloads = {"Inventory": deepcopy(loaded["inventory"]), "EnderChestInventory": deepcopy(loaded["ender_chest"])}
        for case in cases:
            field, slot = locations[case["case_id"]]
            if case["mode"] != "preserve":
                payloads[field][slot] = {**payloads[field].get(slot, {}), "slot": slot, "name": case["id"], "count": case["amount"],
                                         "damage": case["damage"], "display_name": case["name"], "lore": case["lore"],
                                         "enchantments": [{"id": ENCHANTMENT_IDS[value["id"]], "lvl": value["level"]} for value in case["enchantments"]]}
        save(key, loaded, payloads["Inventory"], payloads["EnderChestInventory"])
        loaded = service.load_player(str(world), key)
        before = read_records(world)
        response = service.save_player(str(world), key, list(loaded["inventory"].values()), {},
                                       ender_chest_list=list(loaded["ender_chest"].values()), base_revision=loaded["player_revision"])
        if response.get("no_op") is not True or response.get("backup_file") or read_records(world) != before:
            raise ProbeError("Unchanged player save wrote data or created a backup")
        no_ops += 1
        try:
            service.save_player(str(world), key, list(loaded["inventory"].values()), {},
                                ender_chest_list=list(loaded["ender_chest"].values()), base_revision=original_revision)
        except ValueError:
            if read_records(world) != before:
                raise ProbeError("Rejected stale player save changed the database") from None
            stale_rejections += 1
        else:
            raise ProbeError("Player service accepted a stale revision")
        # Move across both containers and back through production origin tracking.
        inventory_slot, ender_slot = min(loaded["inventory"]), min(loaded["ender_chest"])
        for _ in range(2):
            inventory, ender = deepcopy(loaded["inventory"]), deepcopy(loaded["ender_chest"])
            left, right = inventory[inventory_slot], ender[ender_slot]
            inventory[inventory_slot] = {**right, "slot": inventory_slot}
            ender[ender_slot] = {**left, "slot": ender_slot}
            save(key, loaded, inventory, ender)
            loaded = service.load_player(str(world), key)
        # Delete and recreate one new item, preserving all other slots.
        created = next(case for case in cases if case["mode"] == "create" and locations[case["case_id"]][0] == "Inventory")
        _, slot = locations[created["case_id"]]
        inventory = deepcopy(loaded["inventory"])
        del inventory[slot]
        save(key, loaded, inventory, loaded["ender_chest"])
        loaded = service.load_player(str(world), key)
        inventory = deepcopy(loaded["inventory"])
        inventory[slot] = {"slot": slot, "name": created["id"], "count": created["amount"], "damage": created["damage"],
                           "display_name": created["name"], "lore": created["lore"], "enchantments": []}
        save(key, loaded, inventory, loaded["ender_chest"])
        final = load_player_nbt(read_records(world)[raw_key]).tag
        if {name: tag.save_to() for name, tag in final.items() if name not in {"Inventory", "EnderChestInventory"}} != untouched:
            raise ProbeError("Player service changed unrelated typed player fields")
        results.append(final)
    after = read_records(world)
    if before_records.keys() != after.keys() or any(after[key] != value for key, value in before_records.items() if key not in raw_keys):
        raise ProbeError("Player service changed unrelated database records")
    return results, {"status": "pass", "backed_up_saves": saves, "no_op_checks": no_ops,
                     "stale_revision_rejections": stale_rejections, "cross_container_moves": 2 * len(raw_keys)}
