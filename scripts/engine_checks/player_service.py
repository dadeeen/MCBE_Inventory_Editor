"""Exercise the production service against only a disposable runner world."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .cases import expected_snapshot
from .extended import ENCHANTMENT_IDS
from .protocol import ProbeError
from .service_profile import assignments


def exercise_player_service(world: Path, raw_keys: tuple[bytes, ...], cases: list[dict]) -> tuple[list, dict]:
    from mcbe_editor import nbt
    from mcbe_editor.backup import resolve_backup_path
    from mcbe_editor.bedrock_nbt import load_player_nbt
    from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
    from mcbe_editor.players import encode_player_key
    from mcbe_editor.services import BedrockEditorService

    from .client_profile import player_items
    from .nbt_roundtrip import disk_snapshot, read_records

    before_records = read_records(world)
    locations = assignments(cases)
    service = BedrockEditorService(ITEMS, ENCHANTMENTS)
    saves = no_ops = stale_rejections = intermediate_checks = 0
    results = []

    def containers(root):
        return {field: player_items(root, field) for field in ("Inventory", "EnderChestInventory")}

    def frozen(item_maps):
        return {field: {slot: item.save_to() for slot, item in items.items()} for field, items in item_maps.items()}

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

        def verify_intermediate(expected_items, current_key=raw_key, expected_fields=untouched):
            nonlocal intermediate_checks
            root = load_player_nbt(read_records(world)[current_key]).tag
            other_fields = {name: tag.save_to() for name, tag in root.items() if name not in {"Inventory", "EnderChestInventory"}}
            if frozen(containers(root)) != expected_items or other_fields != expected_fields:
                raise ProbeError("Player service changed the expected intermediate NBT state")
            intermediate_checks += 1
            return root

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
        edited = containers(load_player_nbt(read_records(world)[raw_key]).tag)
        for field, items in containers(original).items():
            expected_slots = set(items) | {slot for location, slot in locations.values() if location == field}
            if set(edited[field]) != expected_slots:
                raise ProbeError("Player service lost items or added unexpected slots in its initial intermediate state")
            changed_slots = {locations[case["case_id"]][1] for case in cases
                             if locations[case["case_id"]][0] == field and case["mode"] != "preserve"}
            if any(edited[field][slot].save_to() != item.save_to() for slot, item in items.items() if slot not in changed_slots):
                raise ProbeError("Player service changed an untouched item in its initial intermediate state")
        for case in cases:
            field, slot = locations[case["case_id"]]
            if slot not in edited[field] or disk_snapshot(edited[field][slot], case) != expected_snapshot(case):
                raise ProbeError("Player service changed item semantics in its initial intermediate state")
        edited_bytes = frozen(edited)
        verify_intermediate(edited_bytes)
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
        selected = next(((left_slot, right_slot) for left_slot, left in sorted(loaded["inventory"].items())
                         for right_slot, right in sorted(loaded["ender_chest"].items())
                         if (left["name"], left["count"]) != (right["name"], right["count"])), None)
        if selected is None:
            raise ProbeError("Player service fixture needs distinguishable items for cross-container moves")
        inventory_slot, ender_slot = selected
        for _ in range(2):
            expected = containers(load_player_nbt(read_records(world)[raw_key]).tag)
            left_item, right_item = expected["Inventory"][inventory_slot], expected["EnderChestInventory"][ender_slot]
            left_item["Slot"], right_item["Slot"] = nbt.ByteTag(ender_slot), nbt.ByteTag(inventory_slot)
            expected["Inventory"][inventory_slot], expected["EnderChestInventory"][ender_slot] = right_item, left_item
            expected_bytes = frozen(expected)
            inventory, ender = deepcopy(loaded["inventory"]), deepcopy(loaded["ender_chest"])
            left, right = inventory[inventory_slot], ender[ender_slot]
            inventory[inventory_slot] = {**right, "slot": inventory_slot}
            ender[ender_slot] = {**left, "slot": ender_slot}
            save(key, loaded, inventory, ender)
            verify_intermediate(expected_bytes)
            loaded = service.load_player(str(world), key)
        # Delete and recreate one new item, preserving all other slots.
        created = next(case for case in cases if case["mode"] == "create" and locations[case["case_id"]][0] == "Inventory")
        _, slot = locations[created["case_id"]]
        inventory = deepcopy(loaded["inventory"])
        del inventory[slot]
        expected_deleted = deepcopy(edited_bytes)
        del expected_deleted["Inventory"][slot]
        save(key, loaded, inventory, loaded["ender_chest"])
        verify_intermediate(expected_deleted)
        loaded = service.load_player(str(world), key)
        inventory = deepcopy(loaded["inventory"])
        inventory[slot] = {"slot": slot, "name": created["id"], "count": created["amount"], "damage": created["damage"],
                           "display_name": created["name"], "lore": created["lore"],
                           "enchantments": [{"id": ENCHANTMENT_IDS[value["id"]], "lvl": value["level"]} for value in created["enchantments"]]}
        save(key, loaded, inventory, loaded["ender_chest"])
        final = verify_intermediate(edited_bytes)
        results.append(final)
    after = read_records(world)
    if before_records.keys() != after.keys() or any(after[key] != value for key, value in before_records.items() if key not in raw_keys):
        raise ProbeError("Player service changed unrelated database records")
    return results, {"status": "pass", "backed_up_saves": saves, "no_op_checks": no_ops,
                     "stale_revision_rejections": stale_rejections, "cross_container_moves": 2 * len(raw_keys),
                     "intermediate_state_checks": intermediate_checks}
