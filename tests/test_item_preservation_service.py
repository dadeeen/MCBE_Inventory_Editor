"""Service-level preservation regressions using disposable, synthetic records."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from mcbe_editor import nbt, services
from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
from mcbe_editor.players import encode_player_key
from mcbe_editor.world import LOCAL_PLAYER_KEY


SOURCE_KEY = b"player_server_source"


def _item(name="minecraft:diamond_helmet", slot=None, **extra):
    fields = {"Name": nbt.StringTag(name), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0)}
    if slot is not None:
        fields["Slot"] = nbt.ByteTag(slot)
    return nbt.CompoundTag({**fields, **extra})


def _empty_root():
    return nbt.CompoundTag({"Name": nbt.StringTag(""), "Count": nbt.ByteTag(0), "Damage": nbt.ShortTag(0)})


def _armor(first=None):
    return nbt.ListTag([first if first is not None else _empty_root(), _empty_root(), _empty_root(), _empty_root()])


def _player(**tags):
    return nbt.CompoundTag({
        "Pos": nbt.ListTag([nbt.FloatTag(0), nbt.FloatTag(64), nbt.FloatTag(0)]),
        "Health": nbt.FloatTag(20),
        **tags,
    }).save_to()


@pytest.fixture
def editor(tmp_path, monkeypatch):
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    state = SimpleNamespace(world=str(world), store={}, writes=[], backups=[], on_backup=None)

    class Db:
        def __init__(self, _path):
            pass

        def get(self, key):
            return state.store[key]

        def iter_items(self):
            return list(state.store.items())

        def put(self, key, value):
            state.writes.append(key)
            state.store[key] = value

        def close(self):
            pass

    def backup(_world, **_kwargs):
        path = tmp_path / f"backup-{len(state.backups)}.zip"
        path.write_bytes(b"synthetic backup")
        state.backups.append(path)
        if state.on_backup is not None:
            state.on_backup()
        return str(path)

    monkeypatch.setattr(services, "create_backup", backup)
    monkeypatch.setattr(services, "prune_backups", lambda *_args, **_kwargs: None)
    state.service = services.BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=Db, readonly_db_factory=Db)
    return state


def _load(editor, key=LOCAL_PLAYER_KEY):
    return editor.service.load_player(editor.world, encode_player_key(key))


def _save(editor, loaded, inventory, **kwargs):
    return editor.service.save_player(
        editor.world, encode_player_key(LOCAL_PLAYER_KEY), inventory, {}, base_revision=loaded["player_revision"], **kwargs,
    )


def _stored(editor):
    return nbt.load(editor.store[LOCAL_PLAYER_KEY]).tag


@pytest.mark.parametrize("slot,root_name,inventory_name,root_item_name", [
    (103, "Armor", "minecraft:iron_helmet", "minecraft:diamond_helmet"),
    (-106, "Offhand", "minecraft:shield", "minecraft:totem_of_undying"),
])
def test_hidden_root_item_survives_an_unrelated_inventory_edit(editor, slot, root_name, inventory_name, root_item_name):
    hidden = _item(root_item_name, Future=nbt.CompoundTag({"values": nbt.ListTag([], 11)}))
    roots = _armor(hidden) if root_name == "Armor" else nbt.ListTag([hidden])
    editor.store[LOCAL_PLAYER_KEY] = _player(
        Inventory=nbt.ListTag([_item(inventory_name, slot), _item("minecraft:stone", 0)]), **{root_name: roots},
    )
    loaded = _load(editor)
    assert loaded["inventory"][slot]["name"] == inventory_name
    payload = deepcopy(list(loaded["inventory"].values()))
    next(item for item in payload if item["slot"] == 0)["count"] = 2

    assert _save(editor, loaded, payload, root_equipment_editable=True)["success"]

    assert _stored(editor)[root_name].save_to() == roots.save_to()
    assert editor.writes == [LOCAL_PLAYER_KEY]


@pytest.mark.parametrize("container,tag_name", [("inventory", "Inventory"), ("ender_chest", "EnderChestInventory")])
def test_cross_player_paste_into_root_equipment_preserves_source_nbt(editor, container, tag_name):
    source = _item(slot=2, Future=nbt.ListTag([], 6))
    editor.store[SOURCE_KEY] = _player(**{tag_name: nbt.ListTag([source])})
    editor.store[LOCAL_PLAYER_KEY] = _player(Inventory=nbt.ListTag([]), Armor=_armor())
    payload = deepcopy(_load(editor, SOURCE_KEY)[container][2])
    payload["slot"] = 103

    assert _save(editor, _load(editor), [payload], root_equipment_editable=True)["success"]

    expected = source.copy()
    del expected["Slot"]
    assert _stored(editor)["Armor"][0].save_to() == expected.save_to()
    assert len(_stored(editor)["Inventory"]) == 0


def test_external_root_equipment_source_is_rechecked_after_backup(editor):
    before = _item(slot=2, Future=nbt.StringTag("before"))
    after = _item(slot=2, Future=nbt.StringTag("after"))
    editor.store[SOURCE_KEY] = _player(Inventory=nbt.ListTag([before]))
    target_before = _player(Inventory=nbt.ListTag([]), Armor=_armor())
    editor.store[LOCAL_PLAYER_KEY] = target_before
    payload = deepcopy(_load(editor, SOURCE_KEY)["inventory"][2])
    payload["slot"] = 103
    editor.on_backup = lambda: editor.store.update({SOURCE_KEY: _player(Inventory=nbt.ListTag([after]))})

    with pytest.raises(ValueError, match="Backup-Erstellung"):
        _save(editor, _load(editor), [payload], root_equipment_editable=True)

    assert editor.store[LOCAL_PLAYER_KEY] == target_before
    assert not editor.writes
    assert len(editor.backups) == 1 and not editor.backups[0].exists()


def test_root_equipment_payload_from_another_world_is_rejected(editor, tmp_path):
    editor.store[LOCAL_PLAYER_KEY] = _player(Inventory=nbt.ListTag([_item(slot=0)]), Armor=_armor())
    loaded = _load(editor)
    payload = deepcopy(loaded["inventory"][0])
    payload.update(slot=103, source_world_path=str(tmp_path / "another-world"))

    with pytest.raises(ValueError, match="andere Welt"):
        _save(editor, loaded, [payload], root_equipment_editable=True)

    assert not editor.writes and not editor.backups


@pytest.mark.parametrize("destination", ["inventory", "ender_chest"])
def test_cross_player_root_source_without_inventory_can_be_copied(editor, destination):
    source = _item(Future=nbt.CompoundTag({"value": nbt.LongTag(456)}))
    editor.store[SOURCE_KEY] = _player(Armor=_armor(source))
    editor.store[LOCAL_PLAYER_KEY] = _player(Inventory=nbt.ListTag([]), EnderChestInventory=nbt.ListTag([]))
    payload = deepcopy(_load(editor, SOURCE_KEY)["inventory"][103])
    assert not payload.get("root_equipment_read_only", False)
    payload["slot"] = 2
    loaded = _load(editor)

    if destination == "inventory":
        result = _save(editor, loaded, [payload])
        saved = _stored(editor)["Inventory"][0]
    else:
        result = _save(editor, loaded, None, ender_chest_list=[payload])
        saved = _stored(editor)["EnderChestInventory"][0]

    assert result["success"]
    expected = source.copy()
    expected["Slot"] = nbt.ByteTag(2)
    assert saved.save_to() == expected.save_to()


@pytest.mark.parametrize("opaque_damage", [nbt.StringTag("future durability"), nbt.CompoundTag({"value": nbt.IntTag(4)})])
def test_durability_edit_cannot_replace_opaque_item_damage(editor, opaque_damage):
    sword = _item("minecraft:diamond_sword", 0, tag=nbt.CompoundTag({"Damage": opaque_damage}))
    before = _player(Inventory=nbt.ListTag([sword]))
    editor.store[LOCAL_PLAYER_KEY] = before
    loaded = _load(editor)
    payload = deepcopy(loaded["inventory"][0])
    assert payload["has_protected_nbt"] and not payload["item_tag_opaque"]
    payload["damage"] = 1

    with pytest.raises(ValueError, match="NBT"):
        _save(editor, loaded, [payload])

    assert editor.store[LOCAL_PLAYER_KEY] == before
    assert not editor.writes and not editor.backups

    payload["damage"] = 0
    payload["display_name"] = "Renamed sword"
    assert _save(editor, loaded, [payload])["success"]
    assert _stored(editor)["Inventory"][0]["tag"]["Damage"].save_to() == opaque_damage.save_to()


def test_legacy_root_durability_can_change_without_touching_opaque_item_damage(editor):
    opaque = nbt.StringTag("future durability")
    sword = _item("minecraft:diamond_sword", 0, Damage=nbt.ShortTag(7), tag=nbt.CompoundTag({"Damage": opaque}))
    editor.store[LOCAL_PLAYER_KEY] = _player(Inventory=nbt.ListTag([sword]))
    loaded = _load(editor)
    payload = {**loaded["inventory"][0], "damage": 1}

    assert _save(editor, loaded, [payload])["success"]

    saved = _stored(editor)["Inventory"][0]
    assert saved["Damage"].py_data == 1
    assert saved["tag"]["Damage"].save_to() == opaque.save_to()


def _enchantment_source(kind, changed=False):
    def entry(level):
        return nbt.CompoundTag({"id": nbt.ShortTag(9), "lvl": nbt.ShortTag(level)})

    if kind == "opaque_level":
        tags = {"ench": nbt.ListTag([entry(999 if changed else 998)])}
    elif kind == "duplicate":
        tags = {"ench": nbt.ListTag([entry(1), entry(3 if changed else 2)])}
    else:
        tags = {"ench": nbt.ListTag([entry(1)]), "enchantments": nbt.ListTag([entry(3 if changed else 2)])}
    return _item("minecraft:diamond_sword", 0, tag=nbt.CompoundTag(tags))


@pytest.mark.parametrize("kind", ["opaque_level", "duplicate", "duplicate_family"])
@pytest.mark.parametrize("when", ["before_save", "during_backup"])
def test_changed_opaque_enchantment_source_cannot_be_copied(editor, kind, when):
    editor.store[SOURCE_KEY] = _player(Inventory=nbt.ListTag([_enchantment_source(kind)]))
    target_before = _player(Inventory=nbt.ListTag([]))
    editor.store[LOCAL_PLAYER_KEY] = target_before
    payload = deepcopy(_load(editor, SOURCE_KEY)["inventory"][0])
    assert payload["has_protected_nbt"]
    payload["slot"] = 2

    def change_source():
        editor.store[SOURCE_KEY] = _player(Inventory=nbt.ListTag([_enchantment_source(kind, changed=True)]))

    if when == "before_save":
        change_source()
    else:
        editor.on_backup = change_source
    with pytest.raises(ValueError, match="Originalquelle|Backup-Erstellung"):
        _save(editor, _load(editor), [payload])

    assert editor.store[LOCAL_PLAYER_KEY] == target_before
    assert not editor.writes
    assert len(editor.backups) == (1 if when == "during_backup" else 0)
    assert all(not path.exists() for path in editor.backups)


@pytest.mark.parametrize("kind,opaque_field", [("axolotl", "Variant"), ("axolotl", "Age"), ("tropical_fish", "Variant")])
def test_bucket_with_opaque_nested_state_is_read_only_and_preserved(editor, kind, opaque_field):
    if kind == "axolotl":
        state = {"Variant": nbt.IntTag(1), "Age": nbt.IntTag(0)}
        edit = {"kind": "axolotl", "variant": 2, "is_baby": False}
    else:
        state = {"Variant": nbt.IntTag(0), "MarkVariant": nbt.IntTag(0), "Color": nbt.IntTag(1), "Color2": nbt.IntTag(2)}
        edit = {"kind": "tropical_fish", "variant": 1, "mark_variant": 2, "color": 3, "color2": 4}
    opaque = nbt.StringTag("future entity state")
    nested = nbt.CompoundTag({**state, opaque_field: opaque})
    bucket = _item(f"minecraft:{kind}_bucket", 0, tag=nbt.CompoundTag({**state, "EntityTag": nested}))
    before = _player(Inventory=nbt.ListTag([bucket]))
    editor.store[LOCAL_PLAYER_KEY] = before
    loaded = _load(editor)
    payload = deepcopy(loaded["inventory"][0])
    assert payload["entity_variant"]["can_edit"] is False
    payload["entity_variant_edit"] = edit

    with pytest.raises(ValueError, match="Entity-Daten"):
        _save(editor, loaded, [payload])

    assert editor.store[LOCAL_PLAYER_KEY] == before
    assert not editor.writes and not editor.backups

    del payload["entity_variant_edit"]
    payload["display_name"] = "Renamed bucket"
    assert _save(editor, loaded, [payload])["success"]
    assert _stored(editor)["Inventory"][0]["tag"]["EntityTag"].save_to() == nested.save_to()
