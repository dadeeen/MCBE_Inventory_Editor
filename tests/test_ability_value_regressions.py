"""Unrelated ability edits must not normalize unreadable or boolean values."""

import pytest

from mcbe_editor import inventory, nbt


@pytest.mark.parametrize("payload", [{"_opaque": True}, {"_opaque": False}, {"future_ability": True}])
@pytest.mark.parametrize("allow_create", [False, True])
def test_marker_only_ability_save_is_noop_without_creating_tags_or_backups(tmp_path, monkeypatch, payload, allow_create):
    from unittest.mock import Mock

    from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
    from mcbe_editor.players import encode_player_key
    from mcbe_editor.services import BedrockEditorService
    from mcbe_editor.world import LOCAL_PLAYER_KEY
    from tests.conftest import make_minimal_player_tag
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
        str(world), encode_player_key(LOCAL_PLAYER_KEY), None, {}, abilities_dict=payload,
        allow_create_abilities=allow_create, base_revision=service._player_revision(raw),
    )

    assert result["success"] is True and result["no_op"] is True
    assert PathFakeDb._shared_stores[str(world / "db")][LOCAL_PLAYER_KEY] == raw
    writer.assert_not_called()
    backup.assert_not_called()


@pytest.mark.parametrize("field,tag_name", [("fly_speed", "flySpeed"), ("walk_speed", "walkSpeed")])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -0.25, 2.0])
def test_unrepresentable_ability_speed_is_protected(field, tag_name, value):
    player = nbt.CompoundTag({"abilities": nbt.CompoundTag({
        tag_name: nbt.FloatTag(value), "mayfly": nbt.ByteTag(0),
    })})
    before_speed = player["abilities"][tag_name].save_to()
    flags = inventory.protected_player_nbt_flags(player)["ability_fields_opaque"]
    assert flags[field] == tag_name
    payload = inventory.parse_abilities(player)
    for protected_field in flags:
        payload.pop(protected_field, None)
    payload["mayfly"] = True
    inventory.apply_abilities(player, payload)
    assert player["abilities"][tag_name].save_to() == before_speed
    assert player["abilities"]["mayfly"].py_data == 1
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


@pytest.mark.parametrize("tag_name,field", [("mayfly", "mayfly"), ("mayBuild", "maybuild"), ("maybuild", "maybuild")])
@pytest.mark.parametrize("value", [-128, -1, 2, 127])
def test_truthy_ability_byte_is_preserved_until_boolean_really_changes(tag_name, field, value):
    player = nbt.CompoundTag({"abilities": nbt.CompoundTag({tag_name: nbt.ByteTag(value)})})
    before = player["abilities"][tag_name].save_to()
    payload = inventory.parse_abilities(player)
    payload["flying"] = True
    inventory.apply_abilities(player, payload)
    assert player["abilities"][tag_name].save_to() == before
    assert player["abilities"]["flying"].py_data == 1
    inventory.apply_abilities(player, {field: False})
    assert inventory.parse_abilities(player)[field] is False
