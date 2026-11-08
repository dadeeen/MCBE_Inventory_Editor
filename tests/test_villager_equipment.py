"""Read-only equipment groups distinguish occupied, empty and uncertain slots."""

import pytest

from mcbe_editor import nbt
from mcbe_editor.villagers import load_villager_detail, prepare_health_changes, prepare_villager_changes, scan_villagers
from tests.test_entities import EntityDb, add_actor, entity_tag
from tests.test_villager_inventory import _supplies


def _item(name="", count=0):
    return nbt.CompoundTag({"Name": nbt.StringTag(name), "Count": nbt.ByteTag(count), "Damage": nbt.ShortTag(0), "WasPickedUp": nbt.ByteTag(0)})


def _world(*, armor=None, mainhand=None, offhand=None, indexed=True):
    tag = entity_tag()
    for field, value in (("Armor", armor), ("Mainhand", mainhand), ("Offhand", offhand)):
        if value is not None:
            tag[field] = value
    tag["ChestItems"] = _supplies()
    db = EntityDb()
    add_actor(db, tag, with_index=indexed)
    return db


def _detail(db):
    row = scan_villagers(db)["villagers"][0]
    return row, load_villager_detail(db, row["id"], row["revision"])


def test_seven_native_equipment_slots_do_not_count_as_seven_equipped_items():
    db = _world(armor=nbt.ListTag([_item() for _ in range(5)]), mainhand=nbt.ListTag([_item()]), offhand=nbt.ListTag([_item()]))
    original = dict(db.records)
    row, detail = _detail(db)
    equipment = detail["equipment"]
    assert row["equipment_count"] == equipment["occupied_count"] == 0
    assert equipment["total"] == len(equipment["slots"]) == 7
    assert equipment["unknown_count"] == 0
    assert equipment["unknown_containers"] == []
    assert not equipment["truncated"]
    assert [(group["container"], group["total"], group["occupied_count"]) for group in equipment["containers"]] == [
        ("Armor", 5, 0),
        ("Mainhand", 1, 0),
        ("Offhand", 1, 0),
    ]
    assert [(slot["container"], slot["index"], slot["state"]) for slot in equipment["slots"]] == [
        *[("Armor", index, "empty") for index in range(5)],
        ("Mainhand", 0, "empty"),
        ("Offhand", 0, "empty"),
    ]
    assert db.records == original


def test_armor_and_both_hands_count_occupied_slots_without_wearable_or_vanilla_restrictions():
    armor = [_item() for _ in range(5)]
    armor[4] = _item("example:body_equipment", 2)
    db = _world(armor=nbt.ListTag(armor), mainhand=nbt.ListTag([_item("minecraft:stick", 64)]), offhand=nbt.ListTag([_item("minecraft:shield", 1)]))
    row, detail = _detail(db)
    equipment = detail["equipment"]
    assert row["equipment_count"] == equipment["occupied_count"] == 3
    assert [group["occupied_count"] for group in equipment["containers"]] == [1, 1, 1]
    assert [slot["slot"] for slot in equipment["slots"] if slot["state"] == "occupied"] == ["Armor[4]", "Mainhand[0]", "Offhand[0]"]


def test_equipment_counts_cover_items_after_the_detail_display_limit():
    armor = [_item() for _ in range(80)] + [_item("example:extra_slot", 1) for _ in range(5)]
    db = _world(armor=nbt.ListTag(armor), mainhand=nbt.ListTag([_item("minecraft:stick", 1)]), offhand=nbt.ListTag([_item()]))
    row, detail = _detail(db)
    equipment = detail["equipment"]
    assert row["equipment_count"] == equipment["occupied_count"] == 6
    assert equipment["total"] == 87
    assert len(equipment["slots"]) == 82
    assert equipment["truncated"]
    armor_group = equipment["containers"][0]
    assert armor_group["total"] == 85 and armor_group["occupied_count"] == 5 and armor_group["truncated"]
    assert all(slot["state"] == "empty" for slot in equipment["slots"] if slot["container"] == "Armor")
    assert equipment["raw"]["value"]["Armor"]["type"] == "ListTag"


@pytest.mark.parametrize(
    "item",
    [
        nbt.CompoundTag({}),
        nbt.CompoundTag({"Name": nbt.StringTag("")}),
        nbt.CompoundTag({"Count": nbt.ByteTag(0)}),
        nbt.CompoundTag({"Name": nbt.IntTag(1), "Count": nbt.ByteTag(0)}),
        nbt.CompoundTag({"Name": nbt.StringTag(""), "Count": nbt.StringTag("0")}),
        nbt.CompoundTag({"Name": nbt.StringTag(""), "Count": nbt.IntTag(0)}),
        _item("minecraft:stone", 0),
        _item("", 1),
        _item("minecraft:air", 1),
        _item("not an item identifier", 1),
        nbt.CompoundTag({"Name": nbt.StringTag(""), "Count": nbt.ByteTag(0), "Damage": nbt.StringTag("0")}),
        nbt.CompoundTag({"Name": nbt.StringTag(""), "Count": nbt.ByteTag(0), "tag": nbt.CompoundTag({"Unknown": nbt.IntTag(1)})}),
    ],
)
def test_missing_inconsistent_and_unusual_equipment_data_is_not_declared_empty(item):
    db = _world(armor=nbt.ListTag([item]))
    original = dict(db.records)
    row, detail = _detail(db)
    equipment = detail["equipment"]
    assert row["equipment_count"] == equipment["occupied_count"] == 0
    assert equipment["unknown_count"] == 1
    assert equipment["slots"][0]["state"] == "unknown"
    assert equipment["containers"][0]["unknown_count"] == 1
    assert equipment["raw"]["value"]["Armor"]["value"]
    assert db.records == original


def test_opaque_containers_and_noncompound_entries_remain_explicitly_unknown():
    db = _world(armor=nbt.StringTag("opaque armor"), mainhand=nbt.ListTag([nbt.IntTag(42), nbt.IntTag(0)]), offhand=nbt.ListTag([], 8))
    original = dict(db.records)
    row, detail = _detail(db)
    equipment = detail["equipment"]
    assert row["equipment_count"] == 0
    assert equipment["unknown_containers"] == ["Armor", "Mainhand", "Offhand"]
    assert equipment["containers"][0]["total"] is None
    assert equipment["containers"][1]["total"] == equipment["unknown_count"] == equipment["total"] == 2
    assert all(slot["state"] == "unknown" and slot["item"] is None for slot in equipment["slots"])
    assert equipment["raw"]["value"]["Armor"] == {"type": "StringTag", "value": "opaque armor"}
    assert db.records == original


def test_absent_equipment_is_distinct_from_an_unreadable_saved_container():
    _, detail = _detail(_world())
    equipment = detail["equipment"]
    assert equipment["total"] == equipment["occupied_count"] == equipment["unknown_count"] == 0
    assert equipment["unknown_containers"] == []
    assert all(not group["present"] and group["total"] == 0 for group in equipment["containers"])


def test_missing_chunk_assignment_stays_visible_and_blocks_health_and_supply_changes():
    db = _world(armor=nbt.ListTag([_item("minecraft:diamond_helmet", 1)]), indexed=False)
    original = dict(db.records)
    row, detail = _detail(db)
    reason = "Chunk-Zuordnung fehlt. Der gespeicherte Bewohner wird nur angezeigt und bleibt schreibgeschützt."
    assert row["issues"] == [{"code": "orphan_actor", "message": reason}]
    assert not row["editable"] and not row["inventory_editable"]
    assert row["health"]["reason"] == detail["inventory"]["reason"] == reason
    assert detail["equipment"]["occupied_count"] == 1
    selected = [{"id": row["id"], "revision": row["revision"]}]
    health = prepare_health_changes(db, selected, {"heal": True})
    supplies = prepare_villager_changes(db, selected, {"inventory": [{"slot": 0, "item": None}]})
    assert not health.writes and not supplies.writes
    assert health.rows[0]["reason"] == supplies.rows[0]["reason"] == reason
    assert db.records == original


def test_equipment_display_metadata_does_not_create_an_equipment_write_api():
    db = _world(armor=nbt.ListTag([_item("minecraft:diamond_helmet", 1)]))
    row, _ = _detail(db)
    selected = [{"id": row["id"], "revision": row["revision"]}]
    with pytest.raises(ValueError):
        prepare_villager_changes(db, selected, {"equipment": [{"container": "Armor", "index": 0, "item": None}]})
