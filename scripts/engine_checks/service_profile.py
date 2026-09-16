"""Native player-service checks with explicitly synthetic player envelopes.

Item NBT comes from the engine's generated carriers and goes back through the
engine afterward. The player envelopes are not evidence of client login/save.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .cases import append_case, make_cases
from .protocol import ProbeError

PLAYER_KEYS = (b"~local_player", b"player_server_mcbe_engine_probe")
SERVICE_IDS = ("minecraft:stone", "minecraft:bow", "minecraft:diamond_pickaxe", "minecraft:splash_potion",
               "minecraft:enchanted_book", "minecraft:oak_sign", "minecraft:red_cushion", "minecraft:compass", "minecraft:shield")


def make_service_cases(observations: dict, limits: dict) -> list[dict]:
    cases = make_cases(list(SERVICE_IDS), observations, limits)
    for item, mode, enchantment, level in (("minecraft:bow", "create", "power", 5),
                                          ("minecraft:diamond_pickaxe", "decorate", "efficiency", 5),
                                          ("minecraft:enchanted_book", "preserve", "unbreaking", 3)):
        append_case(cases, observations, item, mode, 1, enchantments=[{"id": enchantment, "level": level}], seeded_metadata=mode == "preserve")
    for mode in ("preserve", "decorate"):
        append_case(cases, observations, "minecraft:splash_potion", mode, 1, damage=21, data_value=21, seeded_metadata=True,
                    potion={"effect": "minecraft:healing", "delivery": "ThrownSplash"}, name="" if mode == "preserve" else "Geprüfter Heiltrank")
    return cases


def assignments(cases: list[dict]) -> dict:
    result = {}
    for parity, field, last_slot in ((0, "Inventory", 35), (1, "EnderChestInventory", 26)):
        selected = cases[parity::2]
        if len(selected) > 24:
            raise ProbeError("Service profile exceeds its explicit fixture slot budget")
        for slot, case in enumerate(selected):
            result[case["case_id"]] = (field, last_slot if slot == len(selected) - 1 else slot)
    return result


def edit_through_service(world: Path, records: dict, cases: list[dict]) -> dict:
    from mcbe_editor import nbt
    from mcbe_editor.bedrock_nbt import save_player_nbt
    from mcbe_editor.db import LevelDbAdapter

    from .nbt_roundtrip import carriers, indexed_items, read_records, verify_saved_items

    if any(key in records for key in PLAYER_KEYS):
        raise ProbeError("Service fixtures must never replace existing player records")
    sources = carriers(records, {case["carrier"] for case in cases})
    source_items = {name: indexed_items(named.tag[field]) for name, (_key, named, field) in sources.items()}
    locations = assignments(cases)
    seed = {field: [] for field in ("Inventory", "EnderChestInventory")}
    for case in cases:
        if case["mode"] != "create":
            item = deepcopy(source_items[case["carrier"]][case["slot"]])
            field, slot = locations[case["case_id"]]
            item["Slot"] = nbt.ByteTag(slot)
            seed[field].append(item)
    player = nbt.NamedTag(nbt.CompoundTag({
        **{field: nbt.ListTag(items) for field, items in seed.items()},
        "Pos": nbt.ListTag([nbt.FloatTag(0), nbt.FloatTag(70), nbt.FloatTag(0)]),
        "Health": nbt.FloatTag(20), "PlayerGameType": nbt.IntTag(1), "DimensionId": nbt.IntTag(0),
        "EngineProbeOpaque": nbt.LongArrayTag([2**50, -123]),
    }))
    db = LevelDbAdapter(str(world / "db"))
    try:
        db.put_batch({key: save_player_nbt(player) for key in PLAYER_KEYS})
    finally:
        db.close()
    from .player_service import exercise_player_service

    results, service_checks = exercise_player_service(world, PLAYER_KEYS, cases)
    after_service = read_records(world)
    if set(after_service) != set(records) | set(PLAYER_KEYS) or any(after_service[key] != value for key, value in records.items()):
        raise ProbeError("Player service changed records outside the two synthetic players")
    writes = {}
    for index, player_tag in enumerate(results):
        restored = deepcopy(records)
        cloned = carriers(restored, {case["carrier"] for case in cases})
        for name, (actor_key, named, field) in cloned.items():
            items = indexed_items(named.tag[field])
            for case in (case for case in cases if case["carrier"] == name):
                source_field, slot = locations[case["case_id"]]
                source = next(item for item in player_tag[source_field] if item["Slot"].py_data == slot)
                item = deepcopy(source)
                item["Slot"] = nbt.ByteTag(case["slot"])
                if case["mode"] == "preserve" and item.save_to() != source_items[name][case["slot"]].save_to():
                    raise ProbeError("Player service changed preserved engine item bytes")
                items[case["slot"]] = item
            named.tag[field] = nbt.ListTag(list(items.values()))
            restored[actor_key] = save_player_nbt(named)
            if int(name.rsplit("_", 1)[1]) % len(results) == index:
                writes[actor_key] = restored[actor_key]
        verify_saved_items(restored, cases)
    db = LevelDbAdapter(str(world / "db"))
    try:
        db.put_batch(writes)
    finally:
        db.close()
    return {**service_checks, "synthetic_players": len(PLAYER_KEYS), "client_login_verified": False}
