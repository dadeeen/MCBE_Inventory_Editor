"""Semantic catalog conflicts preserve files and unrelated writable player data."""

import json
from types import SimpleNamespace

import pytest
from flask import Flask

from mcbe_editor import inventory, item_data, nbt
from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt
from mcbe_editor.leveldb_writer import LevelDbWriter
from mcbe_editor.numeric_catalog_policy import numeric_catalog_conflict_messages
from mcbe_editor.players import encode_player_key
from mcbe_editor.services import BedrockEditorService
from mcbe_editor.status_snapshots import item_db_status_snapshot


def _write_catalog(path, sections):
    raw = json.loads(item_data.BUNDLED_ITEM_DB_JSON.read_text(encoding="utf-8"))
    raw["items"]["minecraft:stone"] = ["Eigener Stein", "Custom Stone"]
    raw["items"]["review:custom_item"] = ["Eigenes Item", "Custom Item"]
    for section in sections:
        original_id = "1" if section == "effects" else "17"
        raw[section]["99"] = raw[section][original_id]
    path.write_text(json.dumps(raw), encoding="utf-8")
    return raw


@pytest.mark.parametrize("sections", [("effects",), ("enchantments",), ("effects", "enchantments")])
def test_configured_catalog_conflicts_never_replace_the_file_or_valid_sections(tmp_path, monkeypatch, sections):
    path = tmp_path / "item_db.json"
    raw = _write_catalog(path, sections)
    original = path.read_bytes()
    bundled = item_data.load_item_database(item_data.BUNDLED_ITEM_DB_JSON)
    monkeypatch.setenv("MCBE_ITEM_DB_PATH", str(path))

    loaded = item_data.load_item_database()
    catalog = item_data.prepare_item_catalog()
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("item_db.invalid-*.json"))
    assert set(catalog["ITEM_DB_CONFLICTS"]) == set(sections)
    assert catalog["ITEMS"]["minecraft:stone"] == ("Eigener Stein", "Custom Stone")
    assert catalog["ITEMS"]["review:custom_item"] == ("Eigenes Item", "Custom Item")
    for section in ("effects", "enchantments"):
        if section in sections:
            assert catalog[section.upper()] == {}
            assert loaded[section.upper()][99][:3] == tuple(raw[section]["99"][:3])
            assert 99 in catalog["ITEM_DB_CONFLICTS"][section]["ids"]
        else:
            assert catalog[section.upper()] == bundled[section.upper()]
    with item_data.use_item_catalog(catalog):
        if "effects" not in sections:
            assert inventory.validate_effect({"id": 1, "duration": 200})["id"] == 1
        if "enchantments" not in sections:
            validated = inventory.validate_inventory_item(
                {"slot": 0, "name": "minecraft:diamond_sword", "count": 1, "enchantments": [{"id": 17, "lvl": 1}]},
                catalog["ENCHANTMENTS"],
            )
            assert validated["enchantments"] == [{"id": 17, "lvl": 1}]

    # A repaired section regains editability without carrying a stale block.
    _write_catalog(path, ())
    repaired_bytes = path.read_bytes()
    repaired = item_data.prepare_item_catalog()
    assert repaired["ITEM_DB_CONFLICTS"] == {}
    assert repaired["EFFECTS"] and repaired["ENCHANTMENTS"]
    assert path.read_bytes() == repaired_bytes


def _player():
    return nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag(
                [
                    nbt.CompoundTag(
                        {
                            "Slot": nbt.ByteTag(0),
                            "Name": nbt.StringTag("minecraft:stone"),
                            "Count": nbt.ByteTag(1),
                            "Damage": nbt.ShortTag(0),
                            "tag": nbt.CompoundTag(
                                {
                                    "ench": nbt.ListTag(
                                        [
                                            nbt.CompoundTag(
                                                {
                                                    "id": nbt.ShortTag(17),
                                                    "lvl": nbt.ShortTag(1),
                                                    "Future": nbt.StringTag("keep"),
                                                }
                                            )
                                        ]
                                    ),
                                }
                            ),
                        }
                    )
                ]
            ),
            "ActiveEffects": nbt.ListTag(
                [
                    nbt.CompoundTag(
                        {
                            "Id": nbt.ByteTag(1),
                            "Amplifier": nbt.ByteTag(0),
                            "Duration": nbt.IntTag(200),
                            "Future": nbt.StringTag("keep"),
                        }
                    )
                ]
            ),
            "Health": nbt.ShortTag(20),
            "PlayerGameType": nbt.IntTag(0),
        }
    )


def test_conflicts_preserve_nbt_during_unrelated_edits_and_reject_new_ids(tmp_path, monkeypatch):
    path = tmp_path / "item_db.json"
    _write_catalog(path, ("effects", "enchantments"))
    catalog = item_data.prepare_item_catalog(path)
    player = _player()
    original_effects = player["ActiveEffects"].save_to()
    original_enchantments = player["Inventory"][0]["tag"]["ench"].save_to()

    with item_data.use_item_catalog(catalog):
        parsed, _ = inventory.nbt_to_json(player)
        assert parsed[0]["enchantments"] == []
        edited = inventory.build_inventory_nbt(player, [{**parsed[0], "count": 2}], catalog["ENCHANTMENTS"])
        assert edited[0]["Count"].py_data == 2
        assert edited[0]["tag"]["ench"].save_to() == original_enchantments

        # Neither an omitted entry nor a modified echo may rewrite protected NBT.
        for payload in ([], inventory.parse_effects(player), [{"id": 1, "duration": 999}]):
            inventory.apply_effects(player, payload)
            assert player["ActiveEffects"].save_to() == original_effects
        with pytest.raises(ValueError, match="Effekt"):
            inventory.apply_effects(player, [{"id": 2, "duration": 200}])
        with pytest.raises(ValueError, match="Verzauberung"):
            inventory.build_inventory_nbt(player, [{**parsed[0], "enchantments": [{"id": 17, "lvl": 2}]}], catalog["ENCHANTMENTS"])
        assert player["ActiveEffects"].save_to() == original_effects
        assert player["Inventory"][0]["tag"]["ench"].save_to() == original_enchantments

    # Exercise the complete backup/write/reload path, including its independent
    # round-trip validation, rather than only the in-memory NBT builders.
    monkeypatch.setenv("MCBE_EDITOR_MODE", "local")
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    world = tmp_path / "write_world"
    (world / "db").mkdir(parents=True)
    writer = LevelDbWriter(str(world / "db"))
    try:
        writer.put(b"~local_player", save_player_nbt(nbt.NamedTag(player)))
    finally:
        writer.close()
    service = BedrockEditorService(catalog["ITEMS"], catalog["ENCHANTMENTS"], db_factory=LevelDbWriter, item_catalog=catalog)
    key = encode_player_key(b"~local_player")
    loaded = service.load_player(str(world), key)
    result = service.save_player(
        str(world),
        key,
        [{**loaded["inventory"][0], "count": 2}],
        {"health": 19},
        effects_list=[],
        base_revision=loaded["player_revision"],
    )
    assert result["success"] is True
    assert result["no_op"] is False
    reader = service._open_db_readonly(str(world))
    try:
        saved = load_player_nbt(reader.get(b"~local_player")).tag
    finally:
        reader.close()
    assert saved["Inventory"][0]["Count"].py_data == 2
    assert saved["Health"].py_data == 19
    assert saved["ActiveEffects"].save_to() == original_effects
    assert saved["Inventory"][0]["tag"]["ench"].save_to() == original_enchantments


@pytest.mark.parametrize("locale, expected", [("de", "Betroffene IDs: 1, 99"), ("en", "Affected IDs: 1, 99")])
def test_catalog_conflicts_are_visible_in_status_and_player_load(tmp_path, locale, expected):
    path = tmp_path / "item_db.json"
    _write_catalog(path, ("effects",))
    catalog = item_data.prepare_item_catalog(path)
    config = SimpleNamespace(item_db_path=str(path), source_version_path=None, source_version_history_path=None)
    app = Flask(__name__)
    with app.test_request_context(headers={"Accept-Language": locale}):
        status = item_db_status_snapshot(config, SimpleNamespace(**catalog), tmp_path)
    assert status["status"] == "conflict"
    assert expected in status["message"]
    assert status["catalog_conflicts"] == catalog["ITEM_DB_CONFLICTS"]

    world = tmp_path / "synthetic_world"
    (world / "db").mkdir(parents=True)
    db = LevelDbWriter(str(world / "db"))
    try:
        db.put(b"~local_player", save_player_nbt(nbt.NamedTag(_player())))
    finally:
        db.close()
    service = BedrockEditorService(catalog["ITEMS"], catalog["ENCHANTMENTS"], item_catalog=catalog)
    with app.test_request_context(headers={"Accept-Language": locale}):
        loaded = service.load_player(str(world), encode_player_key(b"~local_player"))
        assert loaded["catalog_warnings"] == numeric_catalog_conflict_messages(catalog["ITEM_DB_CONFLICTS"])
    assert loaded["effects_db"] == {}
    assert loaded["ench_db"]
    assert expected in loaded["catalog_warnings"][0]
