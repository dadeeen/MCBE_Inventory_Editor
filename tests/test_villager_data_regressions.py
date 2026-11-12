"""Independent identity and legacy display regressions for villager writes."""

import struct

import pytest

from mcbe_editor import entities, nbt
from mcbe_editor.bedrock_nbt import LOAD_KWARGS, SAVE_KWARGS
from mcbe_editor.villagers import load_villager_detail, prepare_villager_changes, scan_villagers
from tests.test_entities import EntityDb, add_actor, entity_tag
from tests.test_villager_career import career_tag
from tests.test_villager_inventory import _supplies


@pytest.mark.parametrize("alias", ["identifier", "Identifier", "EntityIdentifier", "id", "Id"])
@pytest.mark.parametrize("value", [nbt.IntTag(15), nbt.CompoundTag({"future": nbt.IntTag(15)}), nbt.ListTag([], 8)])
def test_opaque_identity_alias_keeps_villager_visible_but_blocks_every_write_kind(alias, value):
    tag = career_tag()
    tag["ChestItems"] = _supplies()
    tag["EntityIdentifier"] = nbt.StringTag("minecraft:villager_v2")
    tag[alias] = value
    db = EntityDb()
    add_actor(db, tag)
    original = dict(db.records)

    scanned = scan_villagers(db)
    assert scanned["summary"]["total"] == 1
    row = scanned["villagers"][0]
    assert row["identifier"] is None
    assert {issue["code"] for issue in row["issues"]} == {"ambiguous_identifier"}
    assert not any(row[field] for field in ("editable", "name_editable", "inventory_editable", "career_editable"))
    selected = [{"id": row["id"], "revision": row["revision"]}]
    for changes in (
        {"heal": True},
        {"name": "Changed"},
        {"inventory": [{"slot": 0, "item": None}]},
        {"career": {"profession": "farmer"}},
    ):
        plan = prepare_villager_changes(db, selected, changes)
        assert not plan.writes
        assert plan.summary == {"selected": 1, "changed": 0, "skipped": 1, "unchanged": 0}
        assert plan.rows[0]["before"] == plan.rows[0]["after"]
    assert db.records == original


def test_agreeing_string_identity_aliases_still_allow_a_scoped_name_change():
    tag = career_tag()
    for alias in ("Identifier", "EntityIdentifier", "id", "Id"):
        tag[alias] = nbt.StringTag("minecraft:villager_v2")
    db = EntityDb()
    key = add_actor(db, tag)
    original = db.records[key]
    row = scan_villagers(db)["villagers"][0]
    assert row["issues"] == [] and row["name_editable"]

    plan = prepare_villager_changes(db, [{"id": row["id"], "revision": row["revision"]}], {"name": "Händler"})
    changed = nbt.load(plan.writes[key], **LOAD_KWARGS)
    assert changed.tag.pop("CustomName").py_data == "Händler"
    assert changed.save_to(**SAVE_KWARGS) == original


def test_numeric_only_legacy_identity_keeps_its_previous_read_only_scan_contract():
    tag = entity_tag()
    del tag["identifier"]
    tag["id"] = nbt.IntTag(15)
    key = struct.pack("<ii", 0, 0) + b"\x32"
    db = EntityDb({key: tag.save_to(**SAVE_KWARGS)})

    result = entities.scan_entities(db)
    assert len(result.records) == result.scanned_entities == 1
    record = next(iter(result.records.values()))
    assert record.identifier is None
    assert {issue["code"] for issue in record.issues} == {"legacy_read_only", "ambiguous_identifier"}
    assert scan_villagers(db)["villagers"] == []


@pytest.mark.parametrize("storage", ["actor", "legacy"])
@pytest.mark.parametrize(
    "variant,definition,profession,label",
    [
        (0, None, "legacy_0", "Farmer / Fischer / Schäfer / Pfeilmacher"),
        (1, None, "legacy_1", "Bibliothekar / Kartograf"),
        (2, None, "cleric", "Geistlicher"),
        (3, None, "legacy_3", "Rüstungsschmied / Waffenschmied / Werkzeugschmied"),
        (4, None, "legacy_4", "Metzger / Gerber"),
        (5, None, "nitwit", "Nichtsnutz"),
        (0, "+fletcher", "fletcher", "Pfeilmacher"),
        (1, "+cartographer", "cartographer", "Kartograf"),
        (3, "+weaponsmith", "weaponsmith", "Waffenschmied"),
        (4, "+leatherworker", "leatherworker", "Gerber"),
    ],
)
def test_legacy_career_display_and_skipped_preview_use_legacy_profession_mapping(storage, variant, definition, profession, label):
    tag = entity_tag(identifier="minecraft:villager")
    tag["Variant"] = nbt.IntTag(variant)
    if definition:
        tag["definitions"] = nbt.ListTag([nbt.StringTag(definition)])
    db = EntityDb()
    if storage == "actor":
        add_actor(db, tag)
    else:
        db.records[struct.pack("<ii", 0, 0) + b"\x32"] = tag.save_to(**SAVE_KWARGS)
    original = dict(db.records)

    row = scan_villagers(db)["villagers"][0]
    detail = load_villager_detail(db, row["id"], row["revision"])
    assert row["profession"]["id"] == row["career"]["profession"] == detail["career"]["profession"] == profession
    assert not row["career_editable"] and not detail["career"]["tier_editable"]
    plan = prepare_villager_changes(db, [{"id": row["id"], "revision": row["revision"]}], {"career": {"profession": "farmer"}})
    assert not plan.writes and plan.summary["skipped"] == 1
    assert plan.rows[0]["before"]["profession"] == profession
    assert plan.rows[0]["before"]["profession_label"] == label
    assert plan.rows[0]["before"] == plan.rows[0]["after"]
    assert db.records == original


@pytest.mark.parametrize(
    "variant,tier,expected_tier,label",
    [
        *[(variant, None, None, "Unbekannt") for variant in range(5)],
        (5, None, None, "Keine Handelsstufe"),
        (5, nbt.IntTag(4), None, "Keine Handelsstufe"),
        (3, nbt.IntTag(99), None, "Unbekannt"),
        (3, nbt.StringTag("4"), None, "Unbekannt"),
        (3, nbt.ShortTag(2), 2, "Geselle"),
    ],
)
def test_legacy_career_tier_and_skipped_preview_match_the_read_only_list(variant, tier, expected_tier, label):
    tag = entity_tag(identifier="minecraft:villager")
    tag["Variant"] = nbt.IntTag(variant)
    if tier is None:
        del tag["TradeTier"]
    else:
        tag["TradeTier"] = tier
    db = EntityDb()
    add_actor(db, tag)
    original = dict(db.records)

    row = scan_villagers(db)["villagers"][0]
    detail = load_villager_detail(db, row["id"], row["revision"])
    assert row["trade_tier"] == row["career"]["trade_tier"] == detail["career"]["trade_tier"] == expected_tier
    assert row["trade_tier_label"] == label
    plan = prepare_villager_changes(db, [{"id": row["id"], "revision": row["revision"]}], {"career": {"trade_tier": 1}})
    assert plan.summary["skipped"] == 1 and not plan.writes
    assert plan.rows[0]["before"]["trade_tier"] == expected_tier
    assert plan.rows[0]["before"]["trade_tier_label"] == label
    assert plan.rows[0]["before"] == plan.rows[0]["after"]
    assert db.records == original
