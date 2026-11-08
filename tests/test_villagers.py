from __future__ import annotations

import hashlib
import json
import struct

import pytest

from mcbe_editor import nbt
from mcbe_editor.bedrock_nbt import LOAD_KWARGS, SAVE_KWARGS
from mcbe_editor.villagers import load_villager_detail, normalize_health_changes, prepare_health_changes, scan_villagers
from tests.test_entities import EntityDb, add_actor, entity_tag


def selection(scan):
    return [{"id": row["id"], "revision": row["revision"]} for row in scan["villagers"]]


def populated_db():
    db = EntityDb()
    tag = entity_tag(9007199254740999)
    tag["CustomName"] = nbt.StringTag("Rüdiger <script> & Freunde")
    tag["IsBaby"] = nbt.ByteTag(0)
    tag["Offers"] = nbt.CompoundTag(
        {
            "Recipes": nbt.ListTag(
                [
                    nbt.CompoundTag(
                        {
                            "buyA": nbt.CompoundTag({"Name": nbt.StringTag("minecraft:emerald"), "Count": nbt.ByteTag(12)}),
                            "sell": nbt.CompoundTag(
                                {
                                    "Name": nbt.StringTag("minecraft:enchanted_book"),
                                    "Count": nbt.ByteTag(1),
                                    "tag": nbt.CompoundTag({"ench": nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(26), "lvl": nbt.ShortTag(1)})])}),
                                }
                            ),
                            "uses": nbt.IntTag(1),
                            "maxUses": nbt.IntTag(12),
                            "tier": nbt.IntTag(4),
                        }
                    )
                ]
            )
        }
    )
    tag["Armor"] = nbt.ListTag([nbt.CompoundTag({"Name": nbt.StringTag("minecraft:diamond_helmet"), "Count": nbt.ByteTag(1)})])
    tag["UnknownPluginData"] = nbt.CompoundTag(
        {
            "LargeInteger": nbt.LongTag(9007199254740999),
            "NonFinite": nbt.FloatTag(float("nan")),
            "Binary": nbt.StringTag(nbt.utf8_escape_decoder(b"\xff\x00\x80")),
            "Empty": nbt.ListTag([], 12),
        }
    )
    key = add_actor(db, tag)
    return db, key


def test_scan_exposes_meaningful_metadata_without_loading_detail_payloads():
    db, _key = populated_db()
    result = scan_villagers(db)
    row = result["villagers"][0]
    assert row["unique_id"] == "9007199254740999"
    assert row["profession"]["id"] == "librarian"
    assert row["trade_tier"] == 4 and row["trade_tier_label"] == "Meister"
    assert row["health"]["current"] == 12 and row["health"]["max"] == 20
    assert row["editable"] is True and row["is_baby"] is False
    assert row["trade_count"] == row["equipment_count"] == 1
    assert "nbt" not in row and "trades" not in row
    assert result["summary"]["injured"] == 1


@pytest.mark.parametrize("variant,expected", [(0, "unemployed"), (1, "farmer"), (5, "librarian"), (6, "cartographer"), (13, "mason"), (14, "nitwit")])
def test_v2_profession_uses_variant_instead_of_profession_or_biome(variant, expected):
    db = EntityDb()
    tag = entity_tag()
    tag.update({"Variant": nbt.IntTag(variant), "Profession": nbt.IntTag(11), "MarkVariant": nbt.IntTag(4)})
    add_actor(db, tag)
    assert scan_villagers(db)["villagers"][0]["profession"]["id"] == expected


def test_legacy_variant_group_requires_definition_evidence_for_a_subprofession():
    db = EntityDb()
    tag = entity_tag(identifier="minecraft:villager")
    tag["Variant"] = nbt.IntTag(3)
    key = add_actor(db, tag)
    before = scan_villagers(db)["villagers"][0]["profession"]
    assert before["id"] == "legacy_3"
    assert before["source"] == "legacy_group"
    tag["definitions"] = nbt.ListTag([nbt.StringTag("+armorer"), nbt.StringTag("-armorer"), nbt.StringTag("+weaponsmith")])
    db.records[key] = tag.save_to()
    after = scan_villagers(db)["villagers"][0]["profession"]
    assert after["id"] == "weaponsmith" and after["source"] == "definitions"


def test_detail_preserves_source_and_exposes_trades_equipment_and_safe_typed_nbt():
    db, _key = populated_db()
    original = dict(db.records)
    row = scan_villagers(db)["villagers"][0]
    detail = load_villager_detail(db, row["id"], row["revision"])
    assert detail["trades"]["offers"][0]["sell"]["name"] == "minecraft:enchanted_book"
    assert detail["trades"]["offers"][0]["buy_a"]["count"] == 12
    assert detail["equipment"]["slots"][0]["slot"] == "Armor[0]"
    opaque = detail["nbt"]["value"]["UnknownPluginData"]["value"]
    assert opaque["LargeInteger"] == {"type": "LongTag", "value": "9007199254740999"}
    assert opaque["NonFinite"]["value"] == "NaN"
    json.dumps(detail, allow_nan=False)
    assert db.records == original


def test_health_plan_changes_only_explicit_health_float_fields_and_preserves_all_other_bytes():
    db, key = populated_db()
    original = dict(db.records)
    plan = prepare_health_changes(db, selection(scan_villagers(db)), {"max_health": 40, "heal": True})
    assert plan.summary == {"selected": 1, "changed": 1, "skipped": 0, "unchanged": 0}
    assert set(plan.writes) == {key}
    assert plan.before_records == original
    changed = nbt.load(plan.writes[key], **LOAD_KWARGS)
    attribute = changed.tag["Attributes"][0]
    assert attribute["Base"].py_data == 20
    assert attribute["Current"].py_data == attribute["Max"].py_data == attribute["DefaultMax"].py_data == 40
    attribute["Current"], attribute["Max"], attribute["DefaultMax"] = nbt.FloatTag(12), nbt.FloatTag(20), nbt.FloatTag(20)
    assert changed.save_to(**SAVE_KWARGS) == original[key]
    assert db.records == original  # Planning has no storage side effects.


def test_health_batch_has_explicit_skips_and_leaves_orphans_untouched():
    db = EntityDb()
    first = add_actor(db, entity_tag(1))
    second = add_actor(db, entity_tag(2), suffix=b"abcdefgh", with_index=False)
    result = scan_villagers(db)
    assert result["summary"]["total"] == 2 and result["summary"]["editable"] == 1
    plan = prepare_health_changes(db, selection(result), {"heal": True})
    assert plan.summary == {"selected": 2, "changed": 1, "skipped": 1, "unchanged": 0}
    assert set(plan.writes) == {first} and second not in plan.writes
    skipped = next(row for row in plan.rows if row["status"] == "skipped")
    assert skipped["reason"] and skipped["before"] == skipped["after"]


@pytest.mark.parametrize("change", ["modified", "deleted", "different_entity"])
def test_any_stale_selection_aborts_the_complete_plan(change):
    db = EntityDb()
    add_actor(db, entity_tag(1))
    second = add_actor(db, entity_tag(2), suffix=b"abcdefgh")
    original_selection = selection(scan_villagers(db))
    if change == "deleted":
        del db.records[second]
    elif change == "different_entity":
        db.records[second] = entity_tag(2, identifier="minecraft:zombie_villager_v2").save_to()
    else:
        replacement = entity_tag(2)
        replacement["CustomName"] = nbt.StringTag("changed")
        db.records[second] = replacement.save_to()
    before = dict(db.records)
    with pytest.raises(ValueError, match="seit dem Scan"):
        prepare_health_changes(db, original_selection, {"heal": True})
    assert db.records == before


def test_detail_refuses_a_stale_revision():
    db, _key = populated_db()
    row = scan_villagers(db)["villagers"][0]
    with pytest.raises(ValueError, match="seit dem Scan"):
        load_villager_detail(db, row["id"], "0" * 64)


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"heal": False},
        {"heal": "true"},
        {"heal": True, "current_health": 20},
        {"current_health": 21, "max_health": 20},
        {"max_health": 0},
        {"max_health": 2049},
        {"current_health": float("nan")},
        {"max_health": float("inf")},
        {"current_health": True},
        {"max_health": "40"},
        {"profession": 5},
        {"current_health": -(10**400)},
    ],
)
def test_invalid_or_ambiguous_health_input_is_rejected(changes):
    with pytest.raises(ValueError):
        normalize_health_changes(changes)


@pytest.mark.parametrize(
    "health_change",
    [
        {"Current": nbt.FloatTag(0)},
        {"Current": nbt.FloatTag(-1)},
        {"Current": nbt.FloatTag(float("nan"))},
        {"Max": nbt.FloatTag(float("inf"))},
        {"Current": nbt.ShortTag(12)},
        {"Base": nbt.FloatTag(30)},
        {"DefaultMin": nbt.FloatTag(100)},
        {"DefaultMin": nbt.FloatTag(-1)},
        {"DefaultMax": nbt.FloatTag(-1)},
        {"Modifiers": nbt.ListTag([nbt.CompoundTag({"amount": nbt.FloatTag(3)})])},
    ],
)
def test_malformed_or_modified_health_is_read_only(health_change):
    db = EntityDb()
    tag = entity_tag()
    tag["Attributes"][0].update(health_change)
    add_actor(db, tag)
    scan = scan_villagers(db)
    assert scan["villagers"][0]["editable"] is False
    assert prepare_health_changes(db, selection(scan), {"heal": True}).writes == {}


@pytest.mark.parametrize(
    "root_change",
    [
        {"Health": nbt.ShortTag(12)},
        {"Dead": nbt.ByteTag(1)},
        {"DeathTime": nbt.ShortTag(1)},
        {"ActiveEffects": nbt.ListTag([nbt.CompoundTag({"Id": nbt.ByteTag(21)})])},
        {"ActiveEffects": nbt.ListTag([nbt.CompoundTag({"Id": nbt.StringTag("21")})])},
        {"ActiveEffects": nbt.ListTag([nbt.CompoundTag()])},
    ],
)
def test_dead_entities_and_uninterpretable_health_effects_are_read_only(root_change):
    db = EntityDb()
    tag = entity_tag()
    tag.update(root_change)
    add_actor(db, tag)
    assert scan_villagers(db)["villagers"][0]["editable"] is False


def test_duplicate_health_attributes_are_never_chosen_arbitrarily():
    db = EntityDb()
    tag = entity_tag()
    tag["Attributes"].append(tag["Attributes"][0].copy())
    add_actor(db, tag)
    assert scan_villagers(db)["villagers"][0]["health"]["editable"] is False


def test_legacy_chunk_villagers_are_visible_and_explicitly_skipped():
    key = struct.pack("<ii", 0, 0) + b"\x32"
    db = EntityDb({key: entity_tag().save_to() + entity_tag(2).save_to()})
    scan = scan_villagers(db)
    assert len(scan["villagers"]) == 2
    plan = prepare_health_changes(db, selection(scan), {"heal": True})
    assert plan.summary["skipped"] == 2 and plan.writes == {}


def test_mixed_maxima_generate_correct_per_villager_preview_and_unchanged_rows():
    db = EntityDb()
    first = entity_tag()
    first["Attributes"][0]["Current"] = nbt.FloatTag(20)
    add_actor(db, first)
    second = entity_tag(2)
    second["Attributes"][0].update({"Max": nbt.FloatTag(40), "DefaultMax": nbt.FloatTag(40)})
    second_key = add_actor(db, second, suffix=b"abcdefgh")
    plan = prepare_health_changes(db, selection(scan_villagers(db)), {"heal": True})
    assert plan.summary["unchanged"] == 1
    assert plan.rows[1]["after"] == {"current": 40, "max": 40}
    assert set(plan.writes) == {second_key}
    invalid_current = prepare_health_changes(db, selection(scan_villagers(db)), {"current_health": 30})
    assert invalid_current.summary["skipped"] == 1
    assert invalid_current.summary["changed"] == 1


def test_lowering_max_clamps_current_visibly_but_never_rewrites_base():
    db = EntityDb()
    tag = entity_tag()
    tag["Attributes"][0].update({"Current": nbt.FloatTag(35), "Max": nbt.FloatTag(40), "DefaultMax": nbt.FloatTag(40)})
    add_actor(db, tag)
    selected = selection(scan_villagers(db))
    plan = prepare_health_changes(db, selected, {"max_health": 20})
    assert plan.rows[0]["before"] == {"current": 35, "max": 40}
    assert plan.rows[0]["after"] == {"current": 20, "max": 20}
    lower_than_base = prepare_health_changes(db, selected, {"max_health": 10, "heal": True})
    assert lower_than_base.summary["skipped"] == 1
    assert lower_than_base.writes == {}


def test_uncoupled_default_max_is_preserved_and_blocks_only_max_edits():
    db = EntityDb()
    tag = entity_tag()
    tag["Attributes"][0]["DefaultMax"] = nbt.FloatTag(30)
    key = add_actor(db, tag)
    scan = scan_villagers(db)
    assert scan["villagers"][0]["editable"]
    assert not scan["villagers"][0]["health"]["max_editable"]
    assert prepare_health_changes(db, selection(scan), {"max_health": 40}).summary["skipped"] == 1
    plan = prepare_health_changes(db, selection(scan), {"heal": True})
    assert nbt.load(plan.writes[key]).tag["Attributes"][0]["DefaultMax"].py_data == 30


def test_default_minimum_is_respected_when_setting_current_health():
    db = EntityDb()
    tag = entity_tag()
    tag["Attributes"][0]["DefaultMin"] = nbt.FloatTag(5)
    add_actor(db, tag)
    plan = prepare_health_changes(db, selection(scan_villagers(db)), {"current_health": 3})
    assert plan.summary["skipped"] == 1


def test_duplicate_selection_and_non_villager_injection_are_refused():
    db = EntityDb()
    add_actor(db, entity_tag())
    cow_key = add_actor(db, entity_tag(2, identifier="minecraft:cow"), suffix=b"abcdefgh")
    selected = selection(scan_villagers(db))
    with pytest.raises(ValueError, match="einmal"):
        prepare_health_changes(db, selected * 2, {"heal": True})
    cow = {"id": "actor:" + "YWN0b3JwcmVmaXhhYmNkZWZnaA", "revision": hashlib.sha256(db.records[cow_key]).hexdigest()}
    with pytest.raises(ValueError, match="seit dem Scan"):
        prepare_health_changes(db, [cow], {"heal": True})


VILLAGE_ID = "bde502e6-990b-4264-be1d-bb1b4c7f07e0"


def dwellers(identity, *, unrelated=False):
    group = nbt.CompoundTag({"actors": nbt.ListTag([nbt.CompoundTag({"ID": nbt.LongTag(identity)})])})
    return nbt.CompoundTag({"unrelated" if unrelated else "Dwellers": nbt.ListTag([group])}).save_to()


def test_village_membership_requires_an_explicit_id_path_and_matching_dimension():
    db = EntityDb()
    add_actor(db, entity_tag(9007199254740999))
    key = f"VILLAGE_Overworld_{VILLAGE_ID}_DWELLERS".encode()
    db.records[key] = dwellers(9007199254740999)
    row = scan_villagers(db)["villagers"][0]
    assert row["village"]["id"] == VILLAGE_ID and row["village_status"] == "verified"
    db.records[key] = dwellers(9007199254740999, unrelated=True)
    result = scan_villagers(db)
    assert result["villagers"][0]["village"] is None
    assert any(diagnostic["code"] == "unsupported_village_record" for diagnostic in result["diagnostics"])


@pytest.mark.parametrize(
    "field,value,issue_code",
    [
        ("UniqueID", nbt.ByteTag(1), "missing_unique_id"),
        ("UniqueID", nbt.ShortTag(1), "missing_unique_id"),
        ("UniqueID", nbt.IntTag(1), "missing_unique_id"),
        ("DimensionId", nbt.IntTag(1), "dimension_mismatch"),
        ("dimension_id", nbt.IntTag(1), "dimension_mismatch"),
        ("dimension", nbt.IntTag(1), "dimension_mismatch"),
    ],
)
def test_untrusted_actor_identity_or_dimension_cannot_verify_village_membership(field, value, issue_code):
    db = EntityDb()
    tag = entity_tag()
    tag[field] = value
    add_actor(db, tag)
    db.records[f"VILLAGE_Overworld_{VILLAGE_ID}_DWELLERS".encode()] = dwellers(1)

    row = scan_villagers(db)["villagers"][0]
    assert issue_code in {diagnostic["code"] for diagnostic in row["issues"]}
    assert row["editable"] is False
    assert row["village"] is None
    assert row["village_status"] == "ambiguous"


@pytest.mark.parametrize("read_only_reason", ["legacy_storage", "unsupported_health"])
def test_unrelated_read_only_restrictions_do_not_hide_verified_village_membership(read_only_reason):
    db = EntityDb()
    tag = entity_tag()
    if read_only_reason == "legacy_storage":
        db.records[struct.pack("<ii", 0, 0) + b"\x32"] = tag.save_to()
    else:
        tag["Attributes"][0]["Current"] = nbt.ShortTag(12)
        add_actor(db, tag)
    db.records[f"VILLAGE_Overworld_{VILLAGE_ID}_DWELLERS".encode()] = dwellers(1)

    row = scan_villagers(db)["villagers"][0]
    assert row["editable"] is False
    assert row["village"]["id"] == VILLAGE_ID
    assert row["village_status"] == "verified"


@pytest.mark.parametrize("variant", ["unknown_dimension", "wrong_dimension", "duplicate_membership", "legacy_duplicate"])
def test_village_ambiguity_never_becomes_a_guessed_assignment(variant):
    db = EntityDb()
    add_actor(db, entity_tag())
    key = f"VILLAGE_Overworld_{VILLAGE_ID}_DWELLERS".encode()
    db.records[key] = dwellers(1)
    if variant == "unknown_dimension":
        db.records[f"VILLAGE_{VILLAGE_ID}_DWELLERS".encode()] = db.records.pop(key)
    elif variant == "wrong_dimension":
        db.records[key.removesuffix(b"_DWELLERS") + b"_INFO"] = nbt.CompoundTag({"DimensionId": nbt.IntTag(1)}).save_to()
    elif variant == "duplicate_membership":
        db.records[b"VILLAGE_Overworld_bde502e6-990b-4264-be1d-bb1b4c7f07e1_DWELLERS"] = dwellers(1)
    else:
        db.records[f"VILLAGE_{VILLAGE_ID}_DWELLERS".encode()] = dwellers(1)
    row = scan_villagers(db)["villagers"][0]
    assert row["village"] is None
    assert row["village_status"] == "ambiguous"


def test_legacy_village_key_can_use_an_explicit_info_dimension():
    db = EntityDb()
    add_actor(db, entity_tag(), dimension=2)
    key = f"VILLAGE_{VILLAGE_ID}".encode()
    db.records[key + b"_DWELLERS"] = dwellers(1)
    db.records[key + b"_INFO"] = nbt.CompoundTag({"data": nbt.CompoundTag({"DimensionId": nbt.IntTag(2)})}).save_to()
    row = scan_villagers(db)["villagers"][0]
    assert row["village"]["dimension"] == 2 and row["village_status"] == "verified"


@pytest.mark.parametrize("malformed_part", ["actor_before", "actor_after", "group_before", "group_after", "village_key"])
def test_partial_village_evidence_cannot_certify_another_membership(malformed_part):
    db = EntityDb()
    add_actor(db, entity_tag())
    valid_key = f"VILLAGE_Overworld_{VILLAGE_ID}_DWELLERS".encode()
    db.records[valid_key] = dwellers(1)
    other_key = b"VILLAGE_Overworld_bde502e6-990b-4264-be1d-bb1b4c7f07e1_DWELLERS"
    inhabitants = nbt.ListTag([nbt.CompoundTag({"ID": nbt.LongTag(1)})])
    groups = nbt.ListTag([nbt.CompoundTag({"actors": inhabitants})])
    if malformed_part.startswith("actor_"):
        inhabitants.insert(0 if malformed_part.endswith("before") else 1, nbt.CompoundTag({"ID": nbt.StringTag("unknown")}))
    elif malformed_part.startswith("group_"):
        groups.insert(0 if malformed_part.endswith("before") else 1, nbt.CompoundTag({"actors": nbt.StringTag("unknown")}))
    else:
        other_key = b"VILLAGE_Overworld_unsupported-village-id_DWELLERS"
    db.records[other_key] = nbt.CompoundTag({"Dwellers": groups}).save_to()

    result = scan_villagers(db)
    row = result["villagers"][0]
    assert row["village"] is None
    assert row["village_status"] == "ambiguous"
    assert any(diagnostic["code"] == "unsupported_village_record" for diagnostic in result["diagnostics"])
    # A corrupt village record does not make a safely indexed actor uneditable.
    assert row["editable"] is True


@pytest.mark.parametrize("outer,inner", [(1, 0), (0, 1), (1, None)])
def test_conflicting_top_level_and_nested_village_dimensions_are_not_verified(outer, inner):
    db = EntityDb()
    add_actor(db, entity_tag())
    key = f"VILLAGE_Overworld_{VILLAGE_ID}".encode()
    db.records[key + b"_DWELLERS"] = dwellers(1)
    data = nbt.CompoundTag({"DimensionId": nbt.IntTag(inner)} if inner is not None else {})
    db.records[key + b"_INFO"] = nbt.CompoundTag({"DimensionId": nbt.IntTag(outer), "data": data}).save_to()

    result = scan_villagers(db)
    assert result["villagers"][0]["village"] is None
    assert result["villagers"][0]["village_status"] == "ambiguous"
    assert any(diagnostic["code"] == "unknown_village_dimension" for diagnostic in result["diagnostics"])


def test_partial_village_record_only_marks_the_ids_it_actually_contains():
    db = EntityDb()
    add_actor(db, entity_tag())
    key = f"VILLAGE_Overworld_{VILLAGE_ID}_DWELLERS".encode()
    db.records[key] = dwellers(1)
    db.records[b"VILLAGE_Overworld_unsupported-id_DWELLERS"] = dwellers(2)
    row = scan_villagers(db)["villagers"][0]
    assert row["village"]["id"] == VILLAGE_ID
    assert row["village_status"] == "verified"


@pytest.mark.parametrize("dimension,key_prefix", [(0, "Overworld_"), (2, "")])
def test_matching_top_level_and_nested_village_dimensions_remain_supported(dimension, key_prefix):
    db = EntityDb()
    add_actor(db, entity_tag(), dimension=dimension)
    key = f"VILLAGE_{key_prefix}{VILLAGE_ID}".encode()
    db.records[key + b"_DWELLERS"] = dwellers(1)
    db.records[key + b"_INFO"] = nbt.CompoundTag(
        {"Dimension": nbt.IntTag(dimension), "data": nbt.CompoundTag({"DimensionId": nbt.IntTag(dimension)})}
    ).save_to()
    row = scan_villagers(db)["villagers"][0]
    assert row["village"]["id"] == VILLAGE_ID
    assert row["village"]["dimension"] == dimension
    assert row["village_status"] == "verified"
