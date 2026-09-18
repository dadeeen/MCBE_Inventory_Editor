"""Effect edits must preserve values the form cannot represent exactly."""

import pytest

from mcbe_editor import inventory, nbt


def _effect(effect_id=1, **fields):
    return nbt.CompoundTag({
        "Id": nbt.ByteTag(effect_id),
        "Amplifier": nbt.ByteTag(0),
        "Duration": nbt.IntTag(601),
        "Ambient": nbt.ByteTag(0),
        "ShowParticles": nbt.ByteTag(1),
        "ShowIcon": nbt.ByteTag(1),
        **fields,
    })


@pytest.mark.parametrize("field", ["Ambient", "ShowParticles", "ShowIcon"])
@pytest.mark.parametrize("value", [-128, -1, 2, 127])
def test_unchanged_truthy_effect_byte_survives_duration_edit(field, value):
    player = nbt.CompoundTag({"ActiveEffects": nbt.ListTag([_effect(**{field: nbt.ByteTag(value)})])})
    before = player["ActiveEffects"][0][field].save_to()
    payload = inventory.parse_effects(player)
    payload[0]["duration"] = 1200

    inventory.apply_effects(player, payload)

    assert player["ActiveEffects"][0][field].save_to() == before
    assert player["ActiveEffects"][0]["Duration"].py_data == 1200
    payload[0][{"Ambient": "ambient", "ShowParticles": "show_particles", "ShowIcon": "show_icon"}[field]] = False
    inventory.apply_effects(player, payload)
    assert player["ActiveEffects"][0][field].py_data == 0


@pytest.mark.parametrize("duration", [-1, -2_147_483_648])
@pytest.mark.parametrize("echo_protected", [True, False])
def test_negative_effect_duration_is_protected_during_other_effect_edits(duration, echo_protected):
    protected = _effect(Duration=nbt.IntTag(duration))
    before = protected.save_to()
    player = nbt.CompoundTag({"ActiveEffects": nbt.ListTag([protected, _effect(3)])})
    payload = inventory.parse_effects(player)
    assert payload[0].get("opaque") is True
    assert inventory.protected_player_nbt_flags(player)["active_effect_entries_opaque"] == 1
    payload[1]["duration"] = 1200
    if not echo_protected:
        payload.pop(0)

    inventory.apply_effects(player, payload)

    assert player["ActiveEffects"][0].save_to() == before
    assert player["ActiveEffects"][1]["Duration"].py_data == 1200


def test_native_save_keeps_protected_and_untouched_effect_bytes(tmp_path, monkeypatch):
    from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt
    from mcbe_editor.db import LevelDbAdapter
    from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
    from mcbe_editor.players import encode_player_key
    from mcbe_editor.services import BedrockEditorService
    from mcbe_editor.world import LOCAL_PLAYER_KEY
    from tests.conftest import make_minimal_player_tag

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    player = make_minimal_player_tag()
    player["ActiveEffects"] = nbt.ListTag([_effect(Duration=nbt.IntTag(-1)), _effect(3, ShowIcon=nbt.ByteTag(2))])
    effects_before = player["ActiveEffects"].save_to()
    raw = save_player_nbt(nbt.NamedTag(player))
    monkeypatch.setattr("mcbe_editor.db._run_runtime_leveldb_write_guard", lambda *_args: None)
    db = LevelDbAdapter(str(world / "db"))
    try:
        db.put(LOCAL_PLAYER_KEY, raw)
    finally:
        db.close()
    service = BedrockEditorService(ITEMS, ENCHANTMENTS)
    loaded = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))

    result = service.save_player(
        str(world), encode_player_key(LOCAL_PLAYER_KEY), None, {"health": 18},
        effects_list=loaded["effects"], base_revision=loaded["player_revision"],
    )

    assert result["success"] is True and result["no_op"] is False
    reader = service._open_db_readonly(str(world))
    try:
        saved = load_player_nbt(reader.get(LOCAL_PLAYER_KEY)).tag
    finally:
        reader.close()
    assert saved["Health"].py_data == 18
    assert saved["ActiveEffects"].save_to() == effects_before
