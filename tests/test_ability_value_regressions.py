"""Unrelated ability edits must not normalize unreadable or protected values."""

import pytest

from mcbe_editor import inventory, nbt


@pytest.mark.parametrize(
    "payload",
    [{"_opaque": True}, {"_opaque": False}, {"future_ability": True}, {"mayfly": True, "maybuild": False, "instabuild": True}],
)
@pytest.mark.parametrize("allow_create", [False, True])
def test_marker_only_ability_save_is_noop_without_creating_tags_or_backups(tmp_path, monkeypatch, payload, allow_create):
    from unittest.mock import Mock

    from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
    from mcbe_editor.players import encode_player_key
    from mcbe_editor.services import BedrockEditorService
    from mcbe_editor.world import LOCAL_PLAYER_KEY
    from tests.nbt_fixtures import make_minimal_player_tag
    from tests.test_service import PathFakeDb

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    raw = nbt.NamedTag(make_minimal_player_tag()).save_to(compressed=False, little_endian=True)
    PathFakeDb._shared_stores[str(world / "db")] = {LOCAL_PLAYER_KEY: raw}
    writer = Mock(side_effect=AssertionError("A no-op must not open the mutating database"))
    backup = Mock(side_effect=AssertionError("A no-op must not create a backup"))
    monkeypatch.setattr("mcbe_editor.services.create_backup", backup)
    service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=writer, readonly_db_factory=PathFakeDb)

    result = service.save_player(
        str(world),
        encode_player_key(LOCAL_PLAYER_KEY),
        None,
        {},
        abilities_dict=payload,
        allow_create_abilities=allow_create,
        base_revision=service._player_revision(raw),
    )

    assert result["success"] is True and result["no_op"] is True
    assert PathFakeDb._shared_stores[str(world / "db")][LOCAL_PLAYER_KEY] == raw
    writer.assert_not_called()
    backup.assert_not_called()


SPEED_FIELDS = [
    ("fly_speed", "flySpeed", 2.0),
    ("walk_speed", "walkSpeed", 2.0),
    ("vertical_fly_speed", "verticalFlySpeed", 25.0),
]


@pytest.mark.parametrize("field,tag_name,out_of_range", SPEED_FIELDS)
@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "-0.25", "out_of_range"])
def test_unrepresentable_ability_speed_is_protected(field, tag_name, out_of_range, value):
    stored = out_of_range if value == "out_of_range" else float(value)
    other_field, other_tag = ("fly_speed", "flySpeed") if field != "fly_speed" else ("walk_speed", "walkSpeed")
    player = nbt.CompoundTag(
        {
            "abilities": nbt.CompoundTag(
                {
                    tag_name: nbt.FloatTag(stored),
                    other_tag: nbt.FloatTag(0.1),
                    "mayfly": nbt.ByteTag(0),
                }
            )
        }
    )
    before_speed = player["abilities"][tag_name].save_to()
    flags = inventory.protected_player_nbt_flags(player)["ability_fields_opaque"]
    assert flags[field] == tag_name
    payload = inventory.parse_abilities(player)
    for protected_field in flags:
        payload.pop(protected_field, None)
    payload[other_field] = 0.3
    inventory.apply_abilities(player, payload)
    assert player["abilities"][tag_name].save_to() == before_speed
    assert player["abilities"][other_tag].py_data == pytest.approx(0.3)
    before = player.save_to()
    with pytest.raises(ValueError, match="NBT"):
        inventory.apply_abilities(player, {field: 0.2})
    assert player.save_to() == before


@pytest.mark.parametrize("value", [0.0, 0.05, 1.0])
def test_normal_ability_speeds_stay_editable(value):
    player = nbt.CompoundTag({"abilities": nbt.CompoundTag({"flySpeed": nbt.FloatTag(value)})})
    assert "fly_speed" not in inventory.protected_player_nbt_flags(player)["ability_fields_opaque"]
    inventory.apply_abilities(player, {"fly_speed": 0.3})
    assert player["abilities"]["flySpeed"].py_data == pytest.approx(0.3)


@pytest.mark.parametrize("value", [0.0, 1.0, 12.0, 20.0])
def test_vertical_fly_speed_is_editable_up_to_twenty(value):
    player = nbt.CompoundTag({"abilities": nbt.CompoundTag({"verticalFlySpeed": nbt.FloatTag(1.0)})})
    inventory.apply_abilities(player, {"vertical_fly_speed": value})
    assert isinstance(player["abilities"]["verticalFlySpeed"], nbt.FloatTag)
    assert player["abilities"]["verticalFlySpeed"].py_data == pytest.approx(value)
    assert inventory.parse_abilities(player)["vertical_fly_speed"] == pytest.approx(value)
    with pytest.raises(ValueError, match="Vertikale Fluggeschwindigkeit"):
        inventory.apply_abilities(player, {"vertical_fly_speed": 20.5})


def test_game_mode_derived_abilities_are_neither_parsed_nor_written():
    # Bedrock recomputes these from the game mode and the player permission
    # level. An edit of them had no effect in the game, and the Java name
    # mayBuild is not a Bedrock tag at all.
    flags = {
        "mayfly": nbt.ByteTag(1),
        "flying": nbt.ByteTag(0),
        "invulnerable": nbt.ByteTag(1),
        "instabuild": nbt.ByteTag(0),
        "build": nbt.ByteTag(1),
    }
    player = nbt.CompoundTag({"abilities": nbt.CompoundTag({**flags, "flySpeed": nbt.FloatTag(0.05)})})
    parsed = inventory.parse_abilities(player)
    assert set(parsed) == {"fly_speed", "walk_speed", "vertical_fly_speed"}
    before = player.save_to()
    inventory.apply_abilities(player, {"mayfly": False, "flying": True, "invulnerable": False, "maybuild": False, "instabuild": True})
    assert player.save_to() == before
    inventory.apply_abilities(player, {**parsed, "maybuild": False, "fly_speed": 0.2})
    assert "mayBuild" not in player["abilities"] and "maybuild" not in player["abilities"]
    assert {name: player["abilities"][name].py_data for name in flags} == {name: tag.py_data for name, tag in flags.items()}
    assert player["abilities"]["flySpeed"].py_data == pytest.approx(0.2)


def _movement_player(base=0.1, current=None, *, tag_cls=nbt.FloatTag, modifiers=None, abilities=True):
    entry = nbt.CompoundTag(
        {
            "Name": nbt.StringTag("minecraft:movement"),
            "Base": tag_cls(base),
            "Current": tag_cls(base if current is None else current),
            "DefaultMax": nbt.FloatTag(3.4028234663852886e38),
            "DefaultMin": nbt.FloatTag(0.0),
            "Max": nbt.FloatTag(3.4028234663852886e38),
            "Min": nbt.FloatTag(0.0),
        }
    )
    if modifiers is not None:
        entry["Modifiers"] = modifiers
    health = nbt.CompoundTag({"Name": nbt.StringTag("minecraft:health"), "Base": nbt.FloatTag(20.0), "Current": nbt.FloatTag(20.0)})
    player = nbt.CompoundTag({"Attributes": nbt.ListTag([health, entry])})
    if abilities:
        player["abilities"] = nbt.CompoundTag({"walkSpeed": nbt.FloatTag(0.1), "flySpeed": nbt.FloatTag(0.05)})
    return player


def _movement_entry(player):
    return next(entry for entry in player["Attributes"] if entry["Name"].py_data == "minecraft:movement")


def test_movement_speed_writes_base_and_current():
    player = _movement_player()
    assert inventory.protected_player_nbt_flags(player)["movement_speed_locked"] is None
    assert inventory.parse_abilities(player)["movement_speed"] == pytest.approx(0.1)
    inventory.apply_abilities(player, {"movement_speed": 0.4})
    entry = _movement_entry(player)
    assert isinstance(entry["Base"], nbt.FloatTag) and isinstance(entry["Current"], nbt.FloatTag)
    assert entry["Base"].py_data == pytest.approx(0.4)
    assert entry["Current"].py_data == pytest.approx(0.4)
    assert entry["Max"].py_data == pytest.approx(3.4028234663852886e38)
    # The movement attribute is independent of the abilities compound.
    assert player["abilities"]["walkSpeed"].py_data == pytest.approx(0.1)


def test_movement_speed_keeps_a_double_attribute_type():
    player = _movement_player(tag_cls=nbt.DoubleTag)
    inventory.apply_abilities(player, {"movement_speed": 0.25})
    entry = _movement_entry(player)
    assert isinstance(entry["Base"], nbt.DoubleTag) and isinstance(entry["Current"], nbt.DoubleTag)
    assert entry["Base"].py_data == 0.25


def test_movement_speed_echo_keeps_the_stored_bits():
    player = _movement_player(base=0.10000000149011612)
    before = player.save_to()
    inventory.apply_abilities(player, inventory.parse_abilities(player))
    assert player.save_to() == before


def test_movement_only_edit_does_not_create_an_abilities_compound():
    player = _movement_player(abilities=False)
    assert inventory.parse_abilities(player) == {"movement_speed": pytest.approx(0.1)}
    inventory.apply_abilities(player, {"movement_speed": 0.2})
    assert "abilities" not in player
    assert _movement_entry(player)["Base"].py_data == pytest.approx(0.2)


SPRINT_MODIFIER = nbt.CompoundTag({"Name": nbt.StringTag("Sprinting speed boost"), "Amount": nbt.FloatTag(0.3)})


@pytest.mark.parametrize(
    "make_player,reason",
    [
        (lambda: nbt.CompoundTag({"abilities": nbt.CompoundTag()}), "missing"),
        (lambda: _movement_player(modifiers=nbt.ListTag([SPRINT_MODIFIER.copy()])), "modifiers"),
        (lambda: _movement_player(modifiers=nbt.IntTag(1)), "modifiers"),
        (lambda: _movement_player(base=0.1, current=0.13), "value"),
        (lambda: _movement_player(base=1.5), "value"),
        (lambda: _movement_player(base=float("nan")), "value"),
        (lambda: _movement_player(tag_cls=nbt.IntTag, base=0), "value"),
    ],
)
def test_locked_movement_speed_is_preserved(make_player, reason):
    player = make_player()
    assert inventory.protected_player_nbt_flags(player)["movement_speed_locked"] == reason
    before = player.save_to()
    with pytest.raises(ValueError, match="minecraft:movement"):
        inventory.apply_abilities(player, {"movement_speed": 0.2})
    assert player.save_to() == before


def test_movement_speed_with_an_empty_modifier_list_stays_editable():
    player = _movement_player(modifiers=nbt.ListTag([]))
    assert inventory.protected_player_nbt_flags(player)["movement_speed_locked"] is None
    inventory.apply_abilities(player, {"movement_speed": 0.3})
    assert _movement_entry(player)["Current"].py_data == pytest.approx(0.3)


def test_duplicate_movement_attributes_are_locked():
    player = _movement_player()
    player["Attributes"].append(_movement_entry(player).copy())
    assert inventory.protected_player_nbt_flags(player)["movement_speed_locked"] == "value"
    assert "movement_speed" not in inventory.parse_abilities(player)


def test_movement_speed_range_is_enforced():
    player = _movement_player()
    before = player.save_to()
    for value in (-0.1, 1.5, float("inf"), "fast"):
        with pytest.raises(ValueError, match="Laufgeschwindigkeit"):
            inventory.apply_abilities(player, {"movement_speed": value})
    assert player.save_to() == before
