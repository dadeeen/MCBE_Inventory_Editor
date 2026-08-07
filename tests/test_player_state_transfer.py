from __future__ import annotations

import copy

import amulet_nbt as nbt
import pytest

from mcbe_editor import player_state_transfer as player_state_transfer_module
from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt
from mcbe_editor.player_state_transfer import (
    PLAYER_STATE_TRANSFER_SCHEMA_VERSION,
    TRANSFERABLE_ABILITY_FIELD_ORDER,
    TRANSFERABLE_PLAYER_STATE_FIELD_ORDER,
    build_player_state_transfer_plan,
    merge_player_state,
    validate_player_state_transfer,
)


def _raw(tag: nbt.CompoundTag) -> bytes:
    return nbt.NamedTag(tag).save_to(compressed=False, little_endian=True)


def _item(name: str, *, marker: str) -> nbt.CompoundTag:
    return nbt.CompoundTag(
        {
            "Slot": nbt.ByteTag(0),
            "Name": nbt.StringTag(name),
            "Count": nbt.ByteTag(1),
            "Damage": nbt.ShortTag(0),
            "tag": nbt.CompoundTag({"AddonMarker": nbt.StringTag(marker)}),
        }
    )


def _attribute(name: str, value: float = 1.0) -> nbt.CompoundTag:
    return nbt.CompoundTag(
        {
            "Name": nbt.StringTag(name),
            "Current": nbt.FloatTag(value),
        }
    )


def _recipe_unlocking(recipe_ids: list[str], used_contexts: int, **extra_fields) -> nbt.CompoundTag:
    return nbt.CompoundTag(
        {
            "unlocked_recipes": nbt.ListTag([nbt.StringTag(recipe_id) for recipe_id in recipe_ids]),
            "used_contexts": nbt.IntTag(used_contexts),
            **extra_fields,
        }
    )


def test_merge_player_state_copies_allowlisted_state_and_preserves_target_identity() -> None:
    source = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([_item("minecraft:diamond", marker="source-item")]),
            "EnderChestInventory": nbt.ListTag([_item("minecraft:emerald", marker="source-ender")]),
            "Pos": nbt.ListTag([nbt.DoubleTag(8), nbt.DoubleTag(70), nbt.DoubleTag(-4)]),
            "PlayerLevel": nbt.IntTag(27),
            "ActiveEffects": nbt.ListTag([nbt.CompoundTag({"Id": nbt.ByteTag(1)})]),
            "abilities": nbt.CompoundTag({"mayfly": nbt.ByteTag(1), "SourceAddon": nbt.StringTag("must-not-copy")}),
            "Attributes": nbt.ListTag(
                [
                    nbt.CompoundTag({"Name": nbt.StringTag("minecraft:health"), "Current": nbt.FloatTag(18.0)}),
                    nbt.CompoundTag({"Name": nbt.StringTag("addon:source_state"), "Current": nbt.FloatTag(3.0)}),
                ]
            ),
            "UniqueID": nbt.LongTag(111),
            "SourceAddonIdentity": nbt.StringTag("must-not-copy"),
        }
    )
    target = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([_item("minecraft:dirt", marker="target-item")]),
            "Pos": nbt.ListTag([nbt.DoubleTag(0), nbt.DoubleTag(64), nbt.DoubleTag(0)]),
            "PlayerLevel": nbt.IntTag(2),
            "UniqueID": nbt.LongTag(999),
            "ServerId": nbt.StringTag("target-server-id"),
            "TargetAddonData": nbt.CompoundTag({"keep": nbt.ByteTag(1)}),
            "abilities": nbt.CompoundTag({"mayfly": nbt.ByteTag(0), "TargetAddon": nbt.StringTag("keep")}),
            "Attributes": nbt.ListTag(
                [
                    nbt.CompoundTag({"Name": nbt.StringTag("minecraft:health"), "Current": nbt.FloatTag(4.0)}),
                    nbt.CompoundTag({"Name": nbt.StringTag("addon:target_identity"), "Current": nbt.FloatTag(9.0)}),
                ]
            ),
        }
    )

    merged_raw, plan = merge_player_state(_raw(source), _raw(target))
    merged = load_player_nbt(merged_raw).tag

    assert merged["Inventory"][0]["Name"].py_data == "minecraft:diamond"
    assert merged["Inventory"][0]["tag"]["AddonMarker"].py_data == "source-item"
    assert merged["EnderChestInventory"][0]["tag"]["AddonMarker"].py_data == "source-ender"
    assert [value.py_data for value in merged["Pos"]] == [8.0, 70.0, -4.0]
    assert merged["PlayerLevel"].py_data == 27
    assert merged["UniqueID"].py_data == 999
    assert merged["ServerId"].py_data == "target-server-id"
    assert merged["TargetAddonData"]["keep"].py_data == 1
    assert "SourceAddonIdentity" not in merged
    assert merged["abilities"]["mayfly"].py_data == 1
    assert merged["abilities"]["TargetAddon"].py_data == "keep"
    assert "SourceAddon" not in merged["abilities"]
    attributes = {entry["Name"].py_data: entry for entry in merged["Attributes"]}
    assert attributes["minecraft:health"]["Current"].py_data == 18.0
    assert attributes["addon:target_identity"]["Current"].py_data == 9.0
    assert "addon:source_state" not in attributes
    assert plan["schema_version"] == PLAYER_STATE_TRANSFER_SCHEMA_VERSION
    assert "UniqueID" in plan["preserved_identity_fields"]
    assert "SourceAddonIdentity" in plan["skipped_source_fields"]
    assert "abilities.TargetAddon" in plan["nested_preserved_target_fields"]
    assert "abilities.SourceAddon" in plan["nested_skipped_source_fields"]
    assert "Attributes[addon:target_identity]" in plan["nested_preserved_target_fields"]
    assert "Attributes[addon:source_state]" in plan["nested_skipped_source_fields"]


def test_merge_player_state_serializes_new_fields_in_stable_policy_order() -> None:
    source = nbt.CompoundTag(
        {
            "abilities": nbt.CompoundTag(
                {
                    "instabuild": nbt.ByteTag(1),
                    "mayfly": nbt.ByteTag(1),
                    "flySpeed": nbt.FloatTag(0.05),
                }
            ),
            "PlayerLevel": nbt.IntTag(7),
            "Health": nbt.FloatTag(18.0),
            "Pos": nbt.ListTag([nbt.DoubleTag(1), nbt.DoubleTag(2), nbt.DoubleTag(3)]),
            "Inventory": nbt.ListTag([]),
        }
    )
    target = nbt.CompoundTag({"TargetUnknown": nbt.StringTag("keep")})

    merged_raw, _plan = merge_player_state(_raw(source), _raw(target))
    merged = load_player_nbt(merged_raw).tag

    expected_root_order = [field for field in TRANSFERABLE_PLAYER_STATE_FIELD_ORDER if field in source]
    actual_root_order = [str(field) for field in merged if field != "TargetUnknown"]
    assert actual_root_order == expected_root_order

    expected_ability_order = [field for field in TRANSFERABLE_ABILITY_FIELD_ORDER if field in source["abilities"]]
    assert [str(field) for field in merged["abilities"]] == expected_ability_order


def test_merge_player_state_preserves_empty_list_types_and_is_byte_exact_when_state_is_identical() -> None:
    state = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([], 10),
            "PlayerUIItems": nbt.ListTag([], 0),
            "Attributes": nbt.ListTag([], 10),
            "abilities": nbt.CompoundTag({"TargetUnknown": nbt.ListTag([], 3)}),
            "recipe_unlocking": nbt.CompoundTag(
                {
                    "unlocked_recipes": nbt.ListTag([], 8),
                    "used_contexts": nbt.IntTag(0),
                    "TargetUnknown": nbt.ListTag([], 10),
                }
            ),
            "TargetUnknown": nbt.ListTag([], 3),
        }
    )
    raw = _raw(state)

    merged_raw, plan = merge_player_state(raw, raw)
    merged = load_player_nbt(merged_raw).tag

    assert merged_raw == raw
    assert merged["Inventory"].list_data_type == 10
    assert merged["PlayerUIItems"].list_data_type == 0
    assert merged["Attributes"].list_data_type == 10
    assert merged["abilities"]["TargetUnknown"].list_data_type == 3
    assert merged["recipe_unlocking"]["unlocked_recipes"].list_data_type == 8
    assert merged["recipe_unlocking"]["TargetUnknown"].list_data_type == 10
    assert merged["TargetUnknown"].list_data_type == 3
    assert all(group["change_count"] == 0 for group in plan["groups"])


def test_merge_player_state_keeps_source_empty_list_type_when_replacing_nonempty_target_list() -> None:
    source = nbt.CompoundTag({"Inventory": nbt.ListTag([], 10)})
    target = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([_item("minecraft:dirt", marker="target-item")]),
            "UniqueID": nbt.LongTag(999),
        }
    )

    merged_raw, _plan = merge_player_state(_raw(source), _raw(target))
    merged = load_player_nbt(merged_raw).tag

    assert len(merged["Inventory"]) == 0
    assert merged["Inventory"].list_data_type == 10
    assert merged["UniqueID"].py_data == 999


def test_merge_player_state_adds_source_recipes_without_removing_target_recipes() -> None:
    source = nbt.CompoundTag(
        {
            "recipe_unlocking": _recipe_unlocking(
                ["minecraft:shared", "minecraft:source_only"],
                2,
                SourceAddon=nbt.StringTag("must-not-copy"),
            )
        }
    )
    target = nbt.CompoundTag(
        {
            "recipe_unlocking": _recipe_unlocking(
                ["minecraft:target_only", "minecraft:shared"],
                12,
                TargetAddon=nbt.StringTag("keep"),
            ),
            "UniqueID": nbt.LongTag(999),
        }
    )

    source_raw = _raw(source)
    target_raw = _raw(target)
    merged_raw, plan = merge_player_state(source_raw, target_raw)
    merged = load_player_nbt(merged_raw).tag
    recipes = merged["recipe_unlocking"]

    assert [entry.py_data for entry in recipes["unlocked_recipes"]] == [
        "minecraft:target_only",
        "minecraft:shared",
        "minecraft:source_only",
    ]
    assert recipes["used_contexts"].py_data == 14
    assert recipes["TargetAddon"].py_data == "keep"
    assert "SourceAddon" not in recipes
    assert merged["UniqueID"].py_data == 999

    recipe_plan = plan["structured_fields"]["recipe_unlocking"]
    assert recipe_plan == {
        "copied_fields": ["unlocked_recipes", "used_contexts"],
        "cleared_fields": [],
        "preserved_target_fields": ["TargetAddon"],
        "skipped_source_fields": ["SourceAddon"],
        "change_count": 2,
        "source_present": True,
        "target_present": True,
        "source_recipe_count": 2,
        "target_recipe_count": 2,
        "added_recipe_count": 1,
        "result_recipe_count": 3,
    }
    assert "recipe_unlocking.TargetAddon" in plan["nested_preserved_target_fields"]
    assert "recipe_unlocking.SourceAddon" in plan["nested_skipped_source_fields"]

    validation = validate_player_state_transfer(
        source_raw,
        target_raw,
        merged_raw,
        source_after_raw=source_raw,
    )
    assert validation["transferred_field_count"] == 2
    assert validation["cleared_field_count"] == 0
    assert validation["preserved_target_field_count"] == 2
    assert validation["source_unchanged"] is True
    assert validation["target_identity_preserved"] is True


def test_merge_player_state_copies_vanilla_attributes_last_death_and_rest_state() -> None:
    source = nbt.CompoundTag(
        {
            "Attributes": nbt.ListTag(
                [
                    _attribute("minecraft:player.exhaustion", 1.25),
                    _attribute("minecraft:knockback_resistance", 0.0),
                    _attribute("minecraft:absorption", 4.0),
                    _attribute("minecraft:friction_modifier", 0.8),
                    _attribute("addon:source_state", 3.0),
                ]
            ),
            "HasDiedBefore": nbt.ByteTag(1),
            "DeathDimension": nbt.IntTag(2),
            "DeathPositionX": nbt.IntTag(120),
            "DeathPositionY": nbt.IntTag(64),
            "DeathPositionZ": nbt.IntTag(-33),
            "TimeSinceRest": nbt.IntTag(1909),
        }
    )
    target = nbt.CompoundTag(
        {
            "Attributes": nbt.ListTag(
                [
                    _attribute("minecraft:player.exhaustion", 4.5),
                    _attribute("minecraft:knockback_resistance", 0.4),
                    _attribute("minecraft:absorption", 0.0),
                    _attribute("addon:target_state", 9.0),
                ]
            ),
            "HasDiedBefore": nbt.ByteTag(1),
            "DeathDimension": nbt.IntTag(1),
            "DeathPositionX": nbt.IntTag(-214),
            "DeathPositionY": nbt.IntTag(32),
            "DeathPositionZ": nbt.IntTag(23),
            "TimeSinceRest": nbt.IntTag(5975),
            "UniqueID": nbt.LongTag(999),
        }
    )

    merged_raw, plan = merge_player_state(_raw(source), _raw(target))
    merged = load_player_nbt(merged_raw).tag
    attributes = {entry["Name"].py_data: entry for entry in merged["Attributes"]}

    assert attributes["minecraft:player.exhaustion"]["Current"].py_data == pytest.approx(1.25)
    assert attributes["minecraft:knockback_resistance"]["Current"].py_data == pytest.approx(0.0)
    assert attributes["minecraft:absorption"]["Current"].py_data == pytest.approx(4.0)
    assert attributes["minecraft:friction_modifier"]["Current"].py_data == pytest.approx(0.8)
    assert attributes["addon:target_state"]["Current"].py_data == pytest.approx(9.0)
    assert "addon:source_state" not in attributes
    assert merged["HasDiedBefore"].py_data == 1
    assert merged["DeathDimension"].py_data == 2
    assert merged["DeathPositionX"].py_data == 120
    assert merged["DeathPositionY"].py_data == 64
    assert merged["DeathPositionZ"].py_data == -33
    assert merged["TimeSinceRest"].py_data == 1909
    assert merged["UniqueID"].py_data == 999

    copied_attributes = plan["structured_fields"]["attributes"]["copied_fields"]
    assert "Attributes[minecraft:player.exhaustion]" in copied_attributes
    assert "Attributes[minecraft:knockback_resistance]" in copied_attributes
    assert "Attributes[minecraft:absorption]" in copied_attributes
    assert "Attributes[minecraft:friction_modifier]" in copied_attributes
    assert "Attributes[addon:source_state]" in plan["structured_fields"]["attributes"]["skipped_source_fields"]
    assert "Attributes[addon:target_state]" in plan["structured_fields"]["attributes"]["preserved_target_fields"]


def test_merge_player_state_clears_target_last_death_when_source_has_no_last_death() -> None:
    target = nbt.CompoundTag(
        {
            "HasDiedBefore": nbt.ByteTag(1),
            "DeathDimension": nbt.IntTag(1),
            "DeathPositionX": nbt.IntTag(-214),
            "DeathPositionY": nbt.IntTag(32),
            "DeathPositionZ": nbt.IntTag(23),
            "UniqueID": nbt.LongTag(999),
        }
    )

    merged_raw, plan = merge_player_state(_raw(nbt.CompoundTag()), _raw(target))
    merged = load_player_nbt(merged_raw).tag

    for field in ("HasDiedBefore", "DeathDimension", "DeathPositionX", "DeathPositionY", "DeathPositionZ"):
        assert field not in merged
        assert field in plan["cleared_fields"]
    assert merged["UniqueID"].py_data == 999


@pytest.mark.parametrize(
    ("state", "message"),
    [
        ({"TimeSinceRest": nbt.LongTag(1)}, "TimeSinceRest hat einen unbekannten NBT-Typ"),
        ({"HasDiedBefore": nbt.IntTag(1)}, "HasDiedBefore hat einen unbekannten NBT-Typ"),
        (
            {
                "HasDiedBefore": nbt.ByteTag(1),
                "DeathDimension": nbt.IntTag(0),
                "DeathPositionX": nbt.IntTag(1),
            },
            "Der letzte Todesort ist unvollständig",
        ),
        (
            {
                "DeathDimension": nbt.IntTag(0),
                "DeathPositionX": nbt.IntTag(1),
                "DeathPositionY": nbt.IntTag(2),
                "DeathPositionZ": nbt.IntTag(3),
            },
            "Der letzte Todesort besitzt keinen HasDiedBefore-Status",
        ),
        (
            {
                "HasDiedBefore": nbt.ByteTag(1),
                "DeathDimension": nbt.ByteTag(0),
                "DeathPositionX": nbt.IntTag(1),
                "DeathPositionY": nbt.IntTag(2),
                "DeathPositionZ": nbt.IntTag(3),
            },
            "DeathDimension hat einen unbekannten NBT-Typ",
        ),
    ],
)
def test_player_state_transfer_rejects_unknown_rest_and_last_death_shapes(state: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_player_state_transfer_plan(nbt.CompoundTag(state), nbt.CompoundTag())


def test_merge_player_state_preserves_target_recipes_when_source_has_no_recipe_state() -> None:
    source = nbt.CompoundTag({"PlayerLevel": nbt.IntTag(7)})
    target = nbt.CompoundTag(
        {
            "recipe_unlocking": _recipe_unlocking(["minecraft:target_only"], 8),
            "UniqueID": nbt.LongTag(999),
        }
    )

    merged_raw, plan = merge_player_state(_raw(source), _raw(target))
    merged = load_player_nbt(merged_raw).tag

    assert [entry.py_data for entry in merged["recipe_unlocking"]["unlocked_recipes"]] == ["minecraft:target_only"]
    assert merged["recipe_unlocking"]["used_contexts"].py_data == 8
    recipe_plan = plan["structured_fields"]["recipe_unlocking"]
    assert recipe_plan["source_present"] is False
    assert recipe_plan["added_recipe_count"] == 0
    assert recipe_plan["change_count"] == 0
    assert recipe_plan["cleared_fields"] == []


@pytest.mark.parametrize(
    ("recipe_unlocking", "message"),
    [
        (nbt.StringTag("opaque"), "recipe_unlocking hat einen unbekannten NBT-Typ"),
        (
            nbt.CompoundTag({"unlocked_recipes": nbt.IntTag(1)}),
            "recipe_unlocking.unlocked_recipes hat einen unbekannten NBT-Typ",
        ),
        (
            nbt.CompoundTag({"unlocked_recipes": nbt.ListTag([nbt.IntTag(1)])}),
            "recipe_unlocking.unlocked_recipes enthält einen unbekannten Eintragstyp",
        ),
        (
            nbt.CompoundTag({"used_contexts": nbt.ByteTag(1)}),
            "recipe_unlocking.used_contexts hat einen unbekannten NBT-Typ",
        ),
    ],
)
def test_player_state_transfer_rejects_unknown_recipe_unlocking_shapes(recipe_unlocking, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_player_state_transfer_plan(
            nbt.CompoundTag({"recipe_unlocking": recipe_unlocking}),
            nbt.CompoundTag(),
        )


def test_merge_player_state_clears_target_state_absent_from_source() -> None:
    source = nbt.CompoundTag({"Inventory": nbt.ListTag([]), "PlayerLevel": nbt.IntTag(4)})
    target = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([]),
            "PlayerLevel": nbt.IntTag(1),
            "ActiveEffects": nbt.ListTag([nbt.CompoundTag({"Id": nbt.ByteTag(2)})]),
            "UniqueID": nbt.LongTag(10),
        }
    )

    merged_raw, plan = merge_player_state(_raw(source), _raw(target))
    merged = load_player_nbt(merged_raw).tag

    assert "ActiveEffects" not in merged
    assert "ActiveEffects" in plan["cleared_fields"]
    assert merged["UniqueID"].py_data == 10


def test_validate_player_state_transfer_rejects_changed_target_identity() -> None:
    source_raw = _raw(nbt.CompoundTag({"Inventory": nbt.ListTag([]), "PlayerLevel": nbt.IntTag(8)}))
    target_raw = _raw(nbt.CompoundTag({"Inventory": nbt.ListTag([]), "PlayerLevel": nbt.IntTag(1), "UniqueID": nbt.LongTag(20)}))
    merged_raw, _plan = merge_player_state(source_raw, target_raw)
    tampered = load_player_nbt(merged_raw)
    tampered.tag["UniqueID"] = nbt.LongTag(21)

    with pytest.raises(ValueError, match="Zielfeld UniqueID"):
        validate_player_state_transfer(
            source_raw,
            target_raw,
            tampered.save_to(compressed=False, little_endian=True),
            source_after_raw=source_raw,
        )


def test_validate_player_state_transfer_rejects_changed_source_record() -> None:
    source_raw = _raw(nbt.CompoundTag({"Inventory": nbt.ListTag([]), "PlayerLevel": nbt.IntTag(8)}))
    changed_source_raw = _raw(nbt.CompoundTag({"Inventory": nbt.ListTag([]), "PlayerLevel": nbt.IntTag(9)}))
    target_raw = _raw(nbt.CompoundTag({"Inventory": nbt.ListTag([]), "UniqueID": nbt.LongTag(20)}))
    merged_raw, _plan = merge_player_state(source_raw, target_raw)

    with pytest.raises(ValueError, match="Quelldatensatz wurde verändert"):
        validate_player_state_transfer(
            source_raw,
            target_raw,
            merged_raw,
            source_after_raw=changed_source_raw,
        )


def test_merge_player_state_detects_in_place_source_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    source_raw = _raw(nbt.CompoundTag({"Inventory": nbt.ListTag([]), "UniqueID": nbt.LongTag(1)}))
    target_raw = _raw(nbt.CompoundTag({"Inventory": nbt.ListTag([]), "UniqueID": nbt.LongTag(2)}))
    original_apply = player_state_transfer_module._apply_transferable_state

    def mutating_apply(source_tag, target_tag):
        original_apply(source_tag, target_tag)
        source_tag["UnexpectedMutation"] = nbt.IntTag(1)

    monkeypatch.setattr(player_state_transfer_module, "_apply_transferable_state", mutating_apply)

    with pytest.raises(ValueError, match="Quelldatensatz wurde verändert"):
        merge_player_state(source_raw, target_raw)


def test_validate_player_state_transfer_detects_changed_empty_list_element_type() -> None:
    source_raw = _raw(nbt.CompoundTag({"Inventory": nbt.ListTag([], 10)}))
    target_raw = _raw(
        nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag([_item("minecraft:dirt", marker="target-item")]),
                "TargetUnknown": nbt.ListTag([], 10),
                "UniqueID": nbt.LongTag(20),
            }
        )
    )
    merged_raw, _plan = merge_player_state(source_raw, target_raw)
    tampered = load_player_nbt(merged_raw)
    tampered.tag["TargetUnknown"] = nbt.ListTag([], 1)

    with pytest.raises(ValueError, match="Zielfeld TargetUnknown"):
        validate_player_state_transfer(
            source_raw,
            target_raw,
            tampered.save_to(compressed=False, little_endian=True),
            source_after_raw=source_raw,
        )

    tampered = load_player_nbt(merged_raw)
    tampered.tag["Inventory"] = nbt.ListTag([], 1)
    with pytest.raises(ValueError, match="Zustand von Inventory"):
        validate_player_state_transfer(
            source_raw,
            target_raw,
            tampered.save_to(compressed=False, little_endian=True),
            source_after_raw=source_raw,
        )


def test_validate_player_state_transfer_rejects_changed_preserved_nested_ability() -> None:
    source_raw = _raw(
        nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag([]),
                "abilities": nbt.CompoundTag({"mayfly": nbt.ByteTag(1), "SourceAddon": nbt.StringTag("skip")}),
            }
        )
    )
    target_raw = _raw(
        nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag([]),
                "abilities": nbt.CompoundTag({"mayfly": nbt.ByteTag(0), "TargetAddon": nbt.StringTag("keep")}),
            }
        )
    )
    merged_raw, _plan = merge_player_state(source_raw, target_raw)
    tampered = load_player_nbt(merged_raw)
    tampered.tag["abilities"]["TargetAddon"] = nbt.StringTag("changed")

    with pytest.raises(ValueError, match="abilities"):
        validate_player_state_transfer(
            source_raw,
            target_raw,
            tampered.save_to(compressed=False, little_endian=True),
            source_after_raw=source_raw,
        )


def test_transfer_plan_reports_each_reviewed_group() -> None:
    plan = build_player_state_transfer_plan(
        nbt.CompoundTag({"Inventory": nbt.ListTag([]), "Pos": nbt.ListTag([]), "PlayerLevel": nbt.IntTag(1)}),
        nbt.CompoundTag({"UniqueID": nbt.LongTag(1)}),
    )

    assert {group["id"] for group in plan["groups"]} == {"inventory", "location", "vitals", "progress", "gameplay"}
    assert len(plan["policy_id"]) == 64


def test_transfer_plan_reports_cleared_and_preserved_structured_values() -> None:
    source = nbt.CompoundTag(
        {
            "abilities": nbt.CompoundTag(
                {
                    "mayfly": nbt.ByteTag(1),
                    "SourceAddon": nbt.StringTag("skip"),
                }
            ),
            "Attributes": nbt.ListTag(
                [
                    _attribute("minecraft:health", 18.0),
                    _attribute("addon:source_state", 3.0),
                ]
            ),
        }
    )
    target = nbt.CompoundTag(
        {
            "abilities": nbt.CompoundTag(
                {
                    "mayfly": nbt.ByteTag(0),
                    "invulnerable": nbt.ByteTag(1),
                    "TargetAddon": nbt.StringTag("keep"),
                }
            ),
            "Attributes": nbt.ListTag(
                [
                    _attribute("minecraft:health", 4.0),
                    _attribute("minecraft:player.hunger", 12.0),
                    _attribute("addon:target_state", 9.0),
                ]
            ),
        }
    )

    plan = build_player_state_transfer_plan(source, target)

    assert plan["structured_fields"]["abilities"] == {
        "copied_fields": ["mayfly"],
        "cleared_fields": ["invulnerable"],
        "preserved_target_fields": ["TargetAddon"],
        "skipped_source_fields": ["SourceAddon"],
        "change_count": 2,
    }
    assert plan["structured_fields"]["attributes"] == {
        "copied_fields": ["Attributes[minecraft:health]"],
        "cleared_fields": ["Attributes[minecraft:player.hunger]"],
        "preserved_target_fields": ["Attributes[addon:target_state]"],
        "skipped_source_fields": ["Attributes[addon:source_state]"],
        "change_count": 2,
    }
    assert "abilities" not in plan["transferred_fields"]
    assert "Attributes" not in plan["transferred_fields"]
    assert "abilities" not in plan["cleared_fields"]
    assert "Attributes" not in plan["cleared_fields"]

    source_raw = _raw(source)
    target_raw = _raw(target)
    merged_raw, _ = merge_player_state(source_raw, target_raw)
    validation = validate_player_state_transfer(
        source_raw,
        target_raw,
        merged_raw,
        source_after_raw=source_raw,
    )
    assert validation["transferred_field_count"] == 2
    assert validation["cleared_field_count"] == 2
    assert validation["preserved_target_field_count"] == 2


def test_merge_player_state_does_not_create_empty_structured_containers() -> None:
    source = nbt.CompoundTag(
        {
            "abilities": nbt.CompoundTag({"SourceAddon": nbt.StringTag("skip")}),
            "Attributes": nbt.ListTag([_attribute("addon:source_state", 3.0)]),
        }
    )

    merged_raw, plan = merge_player_state(_raw(source), _raw(nbt.CompoundTag()))
    merged = load_player_nbt(merged_raw).tag

    assert "abilities" not in merged
    assert "Attributes" not in merged
    assert plan["structured_fields"]["abilities"]["skipped_source_fields"] == ["SourceAddon"]
    assert plan["structured_fields"]["attributes"]["skipped_source_fields"] == ["Attributes[addon:source_state]"]


def test_merge_player_state_preserves_existing_empty_structured_containers() -> None:
    source = nbt.CompoundTag(
        {
            "abilities": nbt.CompoundTag(),
            "Attributes": nbt.ListTag(),
        }
    )
    target = copy.deepcopy(source)

    merged_raw, plan = merge_player_state(_raw(source), _raw(target))
    merged = load_player_nbt(merged_raw).tag
    groups = {group["id"]: group for group in plan["groups"]}

    assert "abilities" in merged
    assert len(merged["abilities"]) == 0
    assert "Attributes" in merged
    assert len(merged["Attributes"]) == 0
    assert groups["gameplay"]["change_count"] == 0
    assert groups["vitals"]["change_count"] == 0


def test_merge_player_state_removes_structured_containers_after_clearing_their_only_transferable_values() -> None:
    source = nbt.CompoundTag()
    target = nbt.CompoundTag(
        {
            "abilities": nbt.CompoundTag({"invulnerable": nbt.ByteTag(1)}),
            "Attributes": nbt.ListTag([_attribute("minecraft:player.hunger", 10.0)]),
        }
    )

    merged_raw, plan = merge_player_state(_raw(source), _raw(target))
    merged = load_player_nbt(merged_raw).tag

    assert "abilities" not in merged
    assert "Attributes" not in merged
    assert plan["structured_fields"]["abilities"]["cleared_fields"] == ["invulnerable"]
    assert plan["structured_fields"]["attributes"]["cleared_fields"] == ["Attributes[minecraft:player.hunger]"]


def test_structured_group_change_counts_use_nested_operations() -> None:
    plan = build_player_state_transfer_plan(
        nbt.CompoundTag(
            {
                "PlayerGameMode": nbt.IntTag(1),
                "abilities": nbt.CompoundTag({"mayfly": nbt.ByteTag(1), "flying": nbt.ByteTag(1)}),
                "Health": nbt.FloatTag(20.0),
                "Attributes": nbt.ListTag([_attribute("minecraft:health", 20.0)]),
            }
        ),
        nbt.CompoundTag(
            {
                "PlayerGameType": nbt.IntTag(0),
                "abilities": nbt.CompoundTag({"invulnerable": nbt.ByteTag(1)}),
                "Attributes": nbt.ListTag([_attribute("minecraft:player.hunger", 10.0)]),
            }
        ),
    )
    groups = {group["id"]: group for group in plan["groups"]}

    assert groups["gameplay"]["copied_fields"] == ["PlayerGameMode"]
    assert groups["gameplay"]["cleared_fields"] == ["PlayerGameType"]
    assert groups["gameplay"]["change_count"] == 5
    assert groups["vitals"]["copied_fields"] == ["Health"]
    assert groups["vitals"]["change_count"] == 3


def test_group_change_counts_ignore_values_that_are_already_identical() -> None:
    state = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([]),
            "abilities": nbt.CompoundTag({"mayfly": nbt.ByteTag(1)}),
            "Attributes": nbt.ListTag([_attribute("minecraft:health", 20.0)]),
        }
    )

    plan = build_player_state_transfer_plan(copy.deepcopy(state), copy.deepcopy(state))
    groups = {group["id"]: group for group in plan["groups"]}

    assert groups["inventory"]["copied_fields"] == ["Inventory"]
    assert groups["inventory"]["change_count"] == 0
    assert groups["gameplay"]["change_count"] == 0
    assert groups["vitals"]["change_count"] == 0


@pytest.mark.parametrize(
    ("label", "text"),
    [
        # Java-MUTF-8 kodiert Nicht-BMP-Zeichen als CESU-8-Surrogatpaar und NUL
        # als C0 80. Beides muss beim Klonen Bedrock-kodiert bleiben.
        ("emoji", "Schwert \U0001f9ea"),
        ("nul", "tag\x00nul"),
        ("umlaut", "Grüße"),
        ("cjk", "剣"),
    ],
)
def test_transfer_preserves_bedrock_strings_byte_exact(label: str, text: str) -> None:
    item = nbt.CompoundTag(
        {
            "Slot": nbt.ByteTag(0),
            "Name": nbt.StringTag("minecraft:diamond_sword"),
            "Count": nbt.ByteTag(1),
            "Damage": nbt.ShortTag(0),
            "tag": nbt.CompoundTag({"display": nbt.CompoundTag({"Name": nbt.StringTag(text)})}),
        }
    )
    source = save_player_nbt(nbt.NamedTag(nbt.CompoundTag({"UniqueID": nbt.LongTag(1), "Inventory": nbt.ListTag([item])})))
    target = save_player_nbt(nbt.NamedTag(nbt.CompoundTag({"UniqueID": nbt.LongTag(2)})))

    merged, _plan = merge_player_state(source, target)

    merged_name = load_player_nbt(merged).tag["Inventory"][0]["tag"]["display"]["Name"]
    assert str(merged_name) == text, label
    expected_bytes = save_player_nbt(nbt.NamedTag(nbt.CompoundTag({"value": nbt.StringTag(text)})))
    actual_bytes = save_player_nbt(nbt.NamedTag(nbt.CompoundTag({"value": merged_name})))
    assert actual_bytes == expected_bytes, label
