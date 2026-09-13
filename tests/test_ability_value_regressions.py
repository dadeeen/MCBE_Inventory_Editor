"""Unrelated ability edits must not normalize unreadable or boolean values."""

import pytest

from mcbe_editor import inventory, nbt


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
