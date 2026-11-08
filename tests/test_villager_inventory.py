"""Supply edits preserve unrelated NBT and share the guarded villager workflow."""

from pathlib import Path
import zipfile

import pytest

from mcbe_editor import nbt
from mcbe_editor.bedrock_nbt import LOAD_KWARGS, SAVE_KWARGS
from mcbe_editor.leveldb_writer import LevelDbWriter
from mcbe_editor.villagers import load_villager_detail, prepare_villager_changes, scan_villagers
from tests.test_entities import EntityDb, add_actor, entity_tag
from tests.test_villagers import populated_db
from tests.test_villager_workflow import _records, villager_client as villager_client, villager_world as villager_world

from mcbe_editor.villager_inventory import normalize_inventory_changes


def test_supply_change_normalization_keeps_explicit_clear_and_canonical_slot_order():
    changes = {"inventory": [{"slot": 7, "item": None}, {"slot": 0, "item": {"name": "minecraft:bread", "count": 12}}]}
    assert normalize_inventory_changes(changes) == {"inventory": list(reversed(changes["inventory"]))}


@pytest.mark.parametrize(
    "changes",
    [
        {"inventory": []},
        {"inventory": None},
        {"inventory": [{"slot": 0, "item": None}] * 2},
        {"inventory": [{"slot": True, "item": None}]},
        {"inventory": [{"slot": 8, "item": None}]},
        {"inventory": [{"slot": -1, "item": None}]},
        {"inventory": [{"slot": 0}]},
        {"inventory": [{"slot": 0, "item": None}], "heal": True},
        {"inventory": [{"slot": 0, "item": {"name": "minecraft:diamond", "count": 1}}]},
        {"inventory": [{"slot": 0, "item": {"name": "minecraft:air", "count": 0}}]},
        {"inventory": [{"slot": 0, "item": {"name": "minecraft:bread", "count": 0}}]},
        {"inventory": [{"slot": 0, "item": {"name": "minecraft:bread", "count": 65}}]},
        {"inventory": [{"slot": 0, "item": {"name": "minecraft:bread", "count": True}}]},
        {"inventory": [{"slot": 0, "item": {"name": "minecraft:bread", "count": 2.0}}]},
        {"inventory": [{"slot": 0, "item": {"name": "minecraft:bread", "count": 2, "tag": {}}}]},
    ],
)
def test_supply_changes_reject_ambiguous_slots_extra_fields_and_non_supply_items(changes):
    with pytest.raises(ValueError):
        normalize_inventory_changes(changes)


def _slot(slot, name="", count=0, *, picked_up=0):
    return nbt.CompoundTag(
        {
            "Slot": nbt.ByteTag(slot),
            "Name": nbt.StringTag(name),
            "Count": nbt.ByteTag(count),
            "Damage": nbt.ShortTag(0),
            "WasPickedUp": nbt.ByteTag(picked_up),
        }
    )


def _supplies():
    return nbt.ListTag([_slot(0, "minecraft:bread", 12, picked_up=1), *[_slot(slot, picked_up=1 if slot == 7 else 0) for slot in range(1, 8)]])


def _populated_inventory_db():
    db, key = populated_db()
    root = nbt.load(db.records[key], **LOAD_KWARGS)
    root.tag["ChestItems"] = _supplies()
    root.tag["InventoryVersion"] = nbt.StringTag("1.26.52")
    db.records[key] = root.save_to(**SAVE_KWARGS)
    return db, key


def _selection(db):
    return [{"id": row["id"], "revision": row["revision"]} for row in scan_villagers(db)["villagers"]]


def _set_tag(db, key, change):
    root = nbt.load(db.records[key], **LOAD_KWARGS)
    change(root.tag)
    db.records[key] = root.save_to(**SAVE_KWARGS)


def _serialized(tag):
    return nbt.NamedTag(tag).save_to(**SAVE_KWARGS)


def test_detail_exposes_eight_supply_slots_separate_from_read_only_equipment():
    db, _ = _populated_inventory_db()
    chosen = _selection(db)[0]
    detail = load_villager_detail(db, chosen["id"], chosen["revision"])
    stock = detail["inventory"]
    assert stock["capacity"] == 8 and stock["editable"] is True
    assert len(stock["slots"]) == 8
    assert stock["slots"][0]["item"] == {"name": "minecraft:bread", "count": 12}
    assert stock["slots"][7]["item"] is None
    assert all(slot["editable"] for slot in stock["slots"])
    assert detail["equipment"]["slots"][0]["item"]["name"] == "minecraft:diamond_helmet"
    assert all(item["max_count"] == 64 for item in stock["allowed_items"])


def test_supply_count_type_change_add_and_clear_preserve_native_slots_flags_and_other_nbt():
    db, key = _populated_inventory_db()
    original = dict(db.records)
    changes = {"inventory": [{"slot": 0, "item": {"name": "minecraft:carrot", "count": 64}}, {"slot": 7, "item": {"name": "minecraft:bread", "count": 1}}]}
    plan = prepare_villager_changes(db, _selection(db), changes)
    assert db.records == original
    assert set(plan.writes) == {key}
    assert plan.rows[0]["kind"] == "inventory"
    assert plan.rows[0]["before"]["slots"] == [{"slot": 0, "item": {"name": "minecraft:bread", "count": 12}}, {"slot": 7, "item": None}]
    assert plan.rows[0]["after"]["slots"] == changes["inventory"]
    before, after = nbt.load(original[key], **LOAD_KWARGS).tag, nbt.load(plan.writes[key], **LOAD_KWARGS).tag
    for field in before:
        if field != "ChestItems":
            assert _serialized(after[field]) == _serialized(before[field]), field
    assert len(after["ChestItems"]) == 8
    assert after["ChestItems"][0]["Name"].py_data == "minecraft:carrot"
    for slot in range(8):
        assert after["ChestItems"][slot]["Slot"].py_data == slot
        assert after["ChestItems"][slot]["WasPickedUp"] == before["ChestItems"][slot]["WasPickedUp"]
        if slot not in (0, 7):
            assert _serialized(after["ChestItems"][slot]) == _serialized(before["ChestItems"][slot])
    db.records.update(plan.writes)
    cleared = prepare_villager_changes(db, _selection(db), {"inventory": [{"slot": 0, "item": None}]})
    empty = nbt.load(cleared.writes[key], **LOAD_KWARGS).tag["ChestItems"][0]
    assert empty == _slot(0, picked_up=1)


def test_unchanged_supplies_and_empty_slots_do_not_create_a_write():
    db, _ = _populated_inventory_db()
    plan = prepare_villager_changes(
        db, _selection(db), {"inventory": [{"slot": 0, "item": {"name": "minecraft:bread", "count": 12}}, {"slot": 7, "item": None}]}
    )
    assert not plan.writes
    assert plan.summary == {"selected": 1, "changed": 0, "skipped": 0, "unchanged": 1}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda tag: tag.pop("ChestItems"),
        lambda tag: tag.__setitem__("ChestItems", nbt.StringTag("opaque")),
        lambda tag: tag.__setitem__("ChestItems", nbt.ListTag([], 10)),
        lambda tag: tag["ChestItems"].pop(),
        lambda tag: tag["ChestItems"][0].__setitem__("Slot", nbt.ByteTag(1)),
        lambda tag: tag["ChestItems"][0].__setitem__("Slot", nbt.IntTag(0)),
        lambda tag: tag.__setitem__("Inventory", nbt.ListTag([], 10)),
    ],
)
def test_missing_opaque_or_ambiguous_supply_structure_is_not_replaced(mutate):
    db, key = _populated_inventory_db()
    _set_tag(db, key, mutate)
    original = dict(db.records)
    chosen = _selection(db)[0]
    detail = load_villager_detail(db, chosen["id"], chosen["revision"])
    assert not detail["inventory"]["editable"]
    assert detail["inventory"]["reason"]
    plan = prepare_villager_changes(db, [chosen], {"inventory": [{"slot": 0, "item": None}]})
    assert not plan.writes and plan.summary["skipped"] == 1
    assert db.records == original


@pytest.mark.parametrize(
    "mutate",
    [
        lambda item: item.__setitem__("Name", nbt.StringTag("example:unknown_food")),
        lambda item: item.__setitem__("Name", nbt.StringTag("minecraft:diamond")),
        lambda item: item.__setitem__("Count", nbt.IntTag(12)),
        lambda item: item.__setitem__("Count", nbt.ByteTag(65)),
        lambda item: item.__setitem__("Damage", nbt.ShortTag(1)),
        lambda item: item.__setitem__("WasPickedUp", nbt.ByteTag(2)),
        lambda item: item.__setitem__("tag", nbt.CompoundTag({"Unknown": nbt.LongTag(9007199254740997)})),
    ],
)
def test_unknown_item_data_protects_its_slot_without_blocking_other_supply_slots(mutate):
    db, key = _populated_inventory_db()
    _set_tag(db, key, lambda tag: mutate(tag["ChestItems"][0]))
    chosen = _selection(db)[0]
    detail = load_villager_detail(db, chosen["id"], chosen["revision"])
    assert detail["inventory"]["editable"]
    assert not detail["inventory"]["slots"][0]["editable"]
    assert detail["inventory"]["slots"][7]["editable"]
    attempted = prepare_villager_changes(db, [chosen], {"inventory": [{"slot": 0, "item": None}, {"slot": 7, "item": {"name": "minecraft:bread", "count": 1}}]})
    assert not attempted.writes  # Never partially apply a mixed patch.
    safe = prepare_villager_changes(db, [chosen], {"inventory": [{"slot": 7, "item": {"name": "minecraft:bread", "count": 1}}]})
    before = nbt.load(db.records[key], **LOAD_KWARGS).tag["ChestItems"][0]
    after = nbt.load(safe.writes[key], **LOAD_KWARGS).tag["ChestItems"][0]
    assert _serialized(after) == _serialized(before)


def test_supplies_are_editable_independently_of_unsupported_health_fields():
    db, key = _populated_inventory_db()
    _set_tag(db, key, lambda tag: tag.pop("Attributes"))
    scanned = scan_villagers(db)
    assert not scanned["villagers"][0]["editable"]
    assert scanned["villagers"][0]["inventory_editable"]
    assert scanned["summary"]["editable"] == 1
    assert prepare_villager_changes(db, _selection(db), {"inventory": [{"slot": 0, "item": None}]}).summary["changed"] == 1


@pytest.mark.parametrize("field", ["Dead", "DeathTime"])
def test_dead_villagers_do_not_accept_supply_changes(field):
    db, key = _populated_inventory_db()
    _set_tag(db, key, lambda tag: tag.__setitem__(field, nbt.IntTag(1)))
    assert not prepare_villager_changes(db, _selection(db), {"inventory": [{"slot": 0, "item": None}]}).writes


def test_supply_changes_reject_multiple_villagers_and_stale_actor_revisions():
    db, key = _populated_inventory_db()
    old = _selection(db)
    tag = entity_tag(42)
    tag["ChestItems"] = _supplies()
    add_actor(db, tag, suffix=b"newactor")
    with pytest.raises(ValueError):
        prepare_villager_changes(db, _selection(db), {"inventory": [{"slot": 0, "item": None}]})
    _set_tag(db, key, lambda tag: tag["ChestItems"][0].__setitem__("Count", nbt.ByteTag(13)))
    with pytest.raises(ValueError):
        prepare_villager_changes(db, old, {"inventory": [{"slot": 0, "item": None}]})


def test_orphan_actor_supply_slots_are_read_only():
    db = EntityDb()
    tag = entity_tag()
    tag["ChestItems"] = _supplies()
    add_actor(db, tag, with_index=False)
    assert not prepare_villager_changes(db, _selection(db), {"inventory": [{"slot": 0, "item": None}]}).writes


def test_native_supply_http_preview_save_is_signed_backed_up_and_preserves_equipment(villager_client, villager_world):
    world, records = villager_world
    key = next(key for key in records if key.startswith(b"actorprefix"))
    root = nbt.load(records[key], **LOAD_KWARGS)
    root.tag["ChestItems"] = _supplies()
    root.tag["InventoryVersion"] = nbt.StringTag("1.26.52")
    root.tag["Armor"] = nbt.ListTag([_slot(0, "minecraft:diamond_helmet", 1)])
    records[key] = root.save_to(**SAVE_KWARGS)
    writer = LevelDbWriter(str(Path(world) / "db"))
    writer.put_batch({key: records[key]})
    writer.close()
    scanned = villager_client.post("/api/villagers/scan", json={"world_path": world}).get_json()
    chosen = next(row for row in scanned["villagers"] if row["unique_id"] == "9007199254740993")
    body = {
        "world_path": world,
        "world_revision": scanned["world_revision"],
        "selection": [{"id": chosen["id"], "revision": chosen["revision"]}],
        "changes": {"inventory": [{"slot": 0, "item": {"name": "minecraft:potato", "count": 32}}]},
        "server_guard_epoch": scanned["server_guard_epoch"],
        "server_guard_token": scanned["server_guard_token"],
    }
    preview = villager_client.post("/api/villagers/preview", json=body)
    assert preview.status_code == 200, preview.get_json()
    data = preview.get_json()
    assert data["rows"][0]["kind"] == "inventory" and data["change_count"] == 1
    assert _records(world) == records
    response = villager_client.post("/api/villagers/save", json={"world_path": world, "preview_token": data["preview_token"], "changes": {"heal": True}})
    result = response.get_json()
    assert response.status_code == 200, result
    assert result["write_committed"] and result["validation"]["ok"]
    from mcbe_editor.backup import get_backups_dir

    with zipfile.ZipFile(Path(get_backups_dir(world)) / result["backup_file"]) as backup:
        assert backup.testzip() is None
    saved = _records(world)
    assert {other: value for other, value in saved.items() if other != key} == {other: value for other, value in records.items() if other != key}
    after = nbt.load(saved[key], **LOAD_KWARGS).tag
    assert after["ChestItems"][0]["Name"].py_data == "minecraft:potato"
    assert after["ChestItems"][0]["Count"].py_data == 32
    assert after["Armor"] == root.tag["Armor"]
    assert after["Attributes"] == root.tag["Attributes"]
    assert after["InventoryVersion"] == root.tag["InventoryVersion"]
    repeated = villager_client.post("/api/villagers/save", json={"world_path": world, "preview_token": data["preview_token"]})
    assert repeated.status_code == 409
