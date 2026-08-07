import pytest

nbt = pytest.importorskip("amulet_nbt")

from mcbe_editor.compatibility import analyze_player_compatibility, analyze_world_structure, assert_serialized_player_roundtrip
from mcbe_editor.item_data import ITEMS, ENCHANTMENTS
from mcbe_editor.players import encode_player_key
from mcbe_editor.services import BedrockEditorService
from mcbe_editor.world import LOCAL_PLAYER_KEY
from tests.test_service import FakeDb, make_player_bytes


def _item(name="minecraft:stone", slot=0, count=1):
    return nbt.CompoundTag(
        {
            "Slot": nbt.ByteTag(slot),
            "Name": nbt.StringTag(name),
            "Count": nbt.ByteTag(count),
            "Damage": nbt.ShortTag(0),
        }
    )


def test_world_compatibility_reports_missing_db_as_error(tmp_path):
    world = tmp_path / "world"
    world.mkdir()
    report = analyze_world_structure(world)
    assert report["status"] == "error"
    assert any("db" in err for err in report["errors"])
    assert report["save_policy"]["preserve_unknown_world_files"] is True


def test_world_compatibility_accepts_minimal_world_and_warns_about_level_dat(tmp_path):
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    report = analyze_world_structure(world)
    assert report["status"] == "warning"
    assert not report["errors"]
    assert any(check["kind"] == "leveldb" and check["severity"] == "ok" for check in report["checks"])


def test_world_compatibility_accepts_common_bedrock_entries(tmp_path):
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "texts").mkdir()
    (world / "behavior_packs").mkdir()
    (world / "resource_packs").mkdir()
    (world / "level.dat").write_bytes(b"placeholder")
    (world / "levelname.txt").write_text("Test", encoding="utf-8")
    (world / "world_resource_pack_history.json").write_text("[]", encoding="utf-8")
    report = analyze_world_structure(world)
    assert report["status"] == "ok"
    assert report["unknown_top_level_entries"] == []


def test_world_compatibility_keeps_unknown_top_level_entries_informational(tmp_path):
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "level.dat").write_bytes(b"placeholder")
    (world / "server_extra").mkdir()

    report = analyze_world_structure(world)

    assert report["status"] == "ok"
    assert report["warnings"] == []
    assert report["errors"] == []
    assert report["unknown_top_level_entries"] == ["server_extra"]
    assert any("Zusätzliche Weltdateien" in note for note in report["notes"])


def test_player_compatibility_accepts_runtime_palette_alias_items():
    tag = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([_item("minecraft:item.bed")]),
            "Health": nbt.FloatTag(20.0),
        }
    )

    report = analyze_player_compatibility(tag)

    assert report["unknown_item_ids"]["inventory"] == 0
    assert report["unknown_item_details"]["inventory"] == []
    assert not any("unbekannte Item-ID" in warning for warning in report["warnings"])


def test_player_compatibility_notes_unknown_root_and_warns_unknown_items():
    tag = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([_item("minecraft:future_item")]),
            "Health": nbt.FloatTag(20.0),
            "FutureRootTag": nbt.StringTag("keep me"),
        }
    )
    raw = nbt.NamedTag(tag).save_to(compressed=False, little_endian=True)
    report = analyze_player_compatibility(tag, serialized_before=raw)
    assert report["status"] == "warning"
    assert "FutureRootTag" in report["unknown_root_keys"]
    assert any("FutureRootTag" in note for note in report["notes"])
    assert report["unknown_item_ids"]["inventory"] == 1
    assert report["unknown_item_details"]["inventory"] == ["Inventar 0: minecraft:future_item (Menge 1)"]
    assert any("Inventar 0: minecraft:future_item" in warning for warning in report["warnings"])
    assert report["roundtrip"]["readable_before_edit"] is True
    assert report["save_policy"]["preserve_unknown_tags"] is True


def test_player_compatibility_keeps_unknown_root_tags_informational():
    tag = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([_item("minecraft:stone")]),
            "Health": nbt.FloatTag(20.0),
            "FutureRootTag": nbt.StringTag("keep me"),
        }
    )

    report = analyze_player_compatibility(tag)

    assert report["status"] == "ok"
    assert "FutureRootTag" in report["unknown_root_keys"]
    assert report["warnings"] == []
    assert any("FutureRootTag" in note for note in report["notes"])


def test_player_compatibility_reports_specific_protected_nbt_details():
    tag = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([]),
            "Health": nbt.StringTag("twenty"),
            "abilities": nbt.CompoundTag({"flySpeed": nbt.DoubleTag(0.05)}),
            "Armor": nbt.ListTag([_item("minecraft:diamond_helmet")]),
        }
    )

    report = analyze_player_compatibility(tag)

    assert report["status"] == "warning"
    assert "Health für health hat einen unerwarteten Typ" in report["protected_nbt_details"]
    assert "abilities.flySpeed für fly_speed hat einen unerwarteten Typ" in report["protected_nbt_details"]
    assert "Armor enthält 1 zusätzliche Root-Item-Eintrag(e)" in report["protected_nbt_details"]
    assert any("abilities.flySpeed" in warning and "Armor" in warning for warning in report["warnings"])


def test_player_compatibility_accepts_common_bedrock_root_tags_without_warning():
    tag = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([_item("minecraft:stone")]),
            "EnderChestInventory": nbt.ListTag([]),
            "Air": nbt.ShortTag(300),
            "Armor": nbt.ListTag([]),
            "Attributes": nbt.ListTag([]),
            "DimensionId": nbt.IntTag(0),
            "FallDistance": nbt.FloatTag(0.0),
            "Health": nbt.FloatTag(20.0),
            "Mainhand": nbt.ListTag([]),
            "Offhand": nbt.ListTag([]),
            "OnGround": nbt.ByteTag(1),
            "PlayerGameMode": nbt.IntTag(1),
            "PlayerLevel": nbt.IntTag(12),
            "PlayerLevelProgress": nbt.FloatTag(0.25),
            "PlayerUIItems": nbt.ListTag([]),
            "Pos": nbt.ListTag([nbt.DoubleTag(1.0), nbt.DoubleTag(64.0), nbt.DoubleTag(1.0)]),
            "Rotation": nbt.ListTag([nbt.FloatTag(0.0), nbt.FloatTag(0.0)]),
            "SelectedInventorySlot": nbt.IntTag(0),
            "SkinID": nbt.IntTag(0),
            "SpawnX": nbt.IntTag(0),
            "SpawnY": nbt.IntTag(64),
            "SpawnZ": nbt.IntTag(0),
        }
    )
    raw = nbt.NamedTag(tag).save_to(compressed=False, little_endian=True)
    report = analyze_player_compatibility(tag, serialized_before=raw)
    assert report["status"] == "ok"
    assert report["unknown_root_keys"] == []
    assert report["warnings"] == []


def test_service_load_player_includes_compatibility_report(tmp_path):
    FakeDb._shared_store = {LOCAL_PLAYER_KEY: make_player_bytes(_item())}
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb, readonly_db_factory=FakeDb)
    result = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
    assert result["compatibility"]["world"]["status"] in {"ok", "warning"}
    assert result["compatibility"]["player"]["roundtrip"]["readable_before_edit"] is True


def test_service_compatibility_report_can_include_player(tmp_path):
    FakeDb._shared_store = {LOCAL_PLAYER_KEY: make_player_bytes(_item())}
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb, readonly_db_factory=FakeDb)
    result = service.compatibility_report(str(world), encode_player_key(LOCAL_PLAYER_KEY))
    assert result["success"] is True
    assert "world" in result
    assert "player" in result


def test_serialized_roundtrip_rejects_invalid_bytes():
    with pytest.raises(ValueError, match="nicht wieder lesbar"):
        assert_serialized_player_roundtrip(b"not nbt")
