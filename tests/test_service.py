import pytest
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

nbt = pytest.importorskip("amulet_nbt")

from mcbe_editor.backup import get_backups_dir
from mcbe_editor.inventory import _item_source_digest
from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
from mcbe_editor.players import encode_player_key, snapshot_player_export_for_import
from mcbe_editor.services import BedrockEditorService
from mcbe_editor.world import LOCAL_PLAYER_KEY


class FakeDb:
    _shared_store = {}

    def __init__(self, _db_path):
        self.store = self._shared_store
        self.closed = False

    def get(self, key):
        if key not in self.store:
            raise KeyError(key)
        return self.store[key]

    def put(self, key, value):
        self.store[key] = value

    def put_batch(self, values):
        for key, value in values.items():
            if value is None:
                self.store.pop(key, None)
            else:
                self.store[key] = value

    def close(self):
        self.closed = True

    def iter_items(self):
        return list(self.store.items())


class PathFakeDb:
    _shared_stores = {}

    def __init__(self, db_path):
        self.db_path = str(db_path)
        self._shared_stores.setdefault(self.db_path, {})
        self.store = self._shared_stores[self.db_path]
        self.closed = False

    def get(self, key):
        if key not in self.store:
            raise KeyError(key)
        return self.store[key]

    def put(self, key, value):
        self.store[key] = value

    def put_batch(self, values):
        for key, value in values.items():
            if value is None:
                self.store.pop(key, None)
            else:
                self.store[key] = value

    def close(self):
        self.closed = True

    def iter_items(self):
        return list(self.store.items())


def player_import_token(export_path, world_path):
    snapshot_path, token = snapshot_player_export_for_import(str(export_path), str(world_path))
    Path(snapshot_path).unlink()
    return token


def make_player_bytes(item_tag, *additional_item_tags):
    player = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([item_tag, *additional_item_tags]),
            "Pos": nbt.ListTag([nbt.DoubleTag(1.0), nbt.DoubleTag(2.0), nbt.DoubleTag(3.0)]),
            "Health": nbt.FloatTag(20.0),
            "PlayerGameType": nbt.IntTag(0),
        }
    )
    return nbt.NamedTag(player).save_to(compressed=False, little_endian=True)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        FakeDb._shared_store = {}
        PathFakeDb._shared_stores = {}

    def test_load_world_uses_db_adapter_and_returns_capabilities(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "levelname.txt").write_text("Test World", encoding="utf-8")
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)

            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            result = service.load_world(str(world))

            self.assertTrue(result["success"])
            self.assertEqual(result["world_name"], "Test World")
            self.assertTrue(result["capabilities"]["supports_local_player"])
            self.assertIn(0, result["inventory"])

    def test_load_world_exposes_runtime_registry_ids_without_public_display_names(self):
        import tempfile
        from pathlib import Path

        from mcbe_editor import item_data as item_data_module

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "levelname.txt").write_text("Future Items", encoding="utf-8")
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:white_cushion"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            technical_item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(1),
                    "Name": nbt.StringTag("minecraft:black_wool_double_slab"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item, technical_item)
            service = BedrockEditorService(
                {"minecraft:stone": ("Stein", "Stone")},
                ENCHANTMENTS,
                db_factory=FakeDb,
                readonly_db_factory=FakeDb,
            )

            effective_addable = frozenset({"minecraft:stone", "minecraft:white_cushion"})
            effective_block_only = frozenset({"minecraft:black_wool_double_slab"})
            with (
                patch("mcbe_editor.services.ADDABLE_ITEM_IDS", effective_addable),
                patch("mcbe_editor.services.BLOCK_ONLY_ITEM_IDS", effective_block_only),
                patch.object(item_data_module, "ADDABLE_ITEM_IDS", effective_addable),
                patch.object(item_data_module, "BLOCK_ONLY_ITEM_IDS", effective_block_only),
            ):
                result = service.load_world(str(world))

            self.assertEqual(
                result["items_db"]["minecraft:white_cushion"],
                ("White Cushion", "White Cushion"),
            )
            self.assertEqual(
                result["items_db"]["minecraft:black_wool_double_slab"],
                ("Black Wool Double Slab", "Black Wool Double Slab"),
            )
            self.assertNotIn("minecraft:black_wool_double_slab", result["addable_items"])
            self.assertIn("minecraft:black_wool_double_slab", result["block_only_items"])
            self.assertEqual(result["compatibility"]["player"]["unknown_item_ids"]["inventory"], 0)

    def test_list_players_finds_local_remote_empty_and_read_only_records(self):
        item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
            }
        )
        FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)
        FakeDb._shared_store[b"player_server_123"] = make_player_bytes(item)
        empty_inventory_player = nbt.NamedTag(
            nbt.CompoundTag(
                {
                    "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
                }
            )
        ).save_to(compressed=False, little_endian=True)
        read_only_player = nbt.NamedTag(
            nbt.CompoundTag(
                {
                    "Inventory": nbt.StringTag("opaque"),
                    "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
                }
            )
        ).save_to(compressed=False, little_endian=True)
        FakeDb._shared_store[b"player_empty_inventory"] = empty_inventory_player
        FakeDb._shared_store[b"player_read_only"] = read_only_player

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            result = service.list_players(str(world))

        players = {p["raw_key_preview"]: p for p in result["players"]}
        self.assertIn("Lokaler Spieler", players)
        self.assertIn("player_server_123", players)
        self.assertIn("player_empty_inventory", players)
        self.assertIn("player_read_only", players)
        self.assertTrue(players["player_empty_inventory"]["editable"])
        self.assertFalse(players["player_empty_inventory"]["inventory_will_be_created"])
        self.assertTrue(players["player_empty_inventory"]["inventory_create_requires_confirmation"])
        self.assertFalse(players["player_read_only"]["editable"])
        self.assertTrue(result["capabilities"]["supports_local_player"])
        self.assertTrue(result["capabilities"]["supports_multiple_players"])
        self.assertEqual(result["capabilities"]["write_mode"], "selected_player")
        self.assertEqual(result["capabilities"]["player_count"], 4)
        self.assertEqual(result["capabilities"]["editable_player_count"], 3)

    def test_save_remote_player_keeps_local_player_record_unchanged(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "levelname.txt").write_text("Test World", encoding="utf-8")
            local_item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            remote_item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:dirt"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            remote_key = b"player_server_123"
            local_before = make_player_bytes(local_item)
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = local_before
            FakeDb._shared_store[remote_key] = make_player_bytes(remote_item)
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)

            loaded = service.load_player(str(world), encode_player_key(remote_key))
            self.assertTrue(loaded["capabilities"]["supports_local_player"])
            self.assertTrue(loaded["capabilities"]["supports_multiple_players"])
            self.assertEqual(loaded["capabilities"]["write_mode"], "selected_player")
            result = service.save_player(
                str(world),
                encode_player_key(remote_key),
                [
                    {
                        "slot": 0,
                        "name": "minecraft:dirt",
                        "count": 2,
                        "damage": 0,
                        "display_name": "",
                        "lore": [],
                        "enchantments": [],
                    }
                ],
                {},
                base_revision=loaded["player_revision"],
            )

            saved_remote = nbt.load(FakeDb._shared_store[remote_key], compressed=False, little_endian=True).tag
            self.assertTrue(result["success"])
            self.assertEqual(FakeDb._shared_store[LOCAL_PLAYER_KEY], local_before)
            self.assertEqual(saved_remote["Inventory"][0]["Count"].py_data, 2)

    def test_save_player_preserves_missing_inventory_when_payload_is_empty(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "levelname.txt").write_text("Test World", encoding="utf-8")
            raw = nbt.NamedTag(
                nbt.CompoundTag(
                    {
                        "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
                        "Health": nbt.FloatTag(20.0),
                    }
                )
            ).save_to(compressed=False, little_endian=True)
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = raw
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)

            loaded = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
            self.assertIn("enchantment_compatibility", loaded)
            self.assertIn("compatible_slots", loaded["enchantment_compatibility"])
            self.assertIn("41", loaded["enchantment_compatibility"]["compatible_slots"])
            self.assertIn("item_components", loaded)
            self.assertIn("enchantable", loaded["item_components"])
            self.assertIn("item_availability", loaded)
            self.assertIn("minecraft:barrier", loaded["item_availability"]["classifications"]["technical"])
            result = service.save_player(str(world), encode_player_key(LOCAL_PLAYER_KEY), [], {}, base_revision=loaded["player_revision"])

            saved = nbt.load(FakeDb._shared_store[LOCAL_PLAYER_KEY], compressed=False, little_endian=True).tag
            self.assertNotIn("Inventory", saved)
            self.assertTrue(result["no_op"])
            self.assertIsNone(result["backup_file"])
            backup_dir = Path(get_backups_dir(str(world)))
            self.assertFalse(backup_dir.exists())

    def test_save_player_rejects_creating_missing_inventory_without_confirmation(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "levelname.txt").write_text("Test World", encoding="utf-8")
            raw = nbt.NamedTag(
                nbt.CompoundTag(
                    {
                        "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
                        "Health": nbt.FloatTag(20.0),
                    }
                )
            ).save_to(compressed=False, little_endian=True)
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = raw
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            loaded = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
            item = {"slot": 0, "name": "minecraft:stone", "count": 1, "damage": 0, "enchantments": []}

            with self.assertRaisesRegex(ValueError, "ausdrücklich bestätigt"):
                service.save_player(str(world), encode_player_key(LOCAL_PLAYER_KEY), [item], {}, base_revision=loaded["player_revision"])

            saved = nbt.load(FakeDb._shared_store[LOCAL_PLAYER_KEY], compressed=False, little_endian=True).tag
            self.assertNotIn("Inventory", saved)

    def test_save_player_creates_missing_inventory_only_with_confirmation(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "levelname.txt").write_text("Test World", encoding="utf-8")
            raw = nbt.NamedTag(
                nbt.CompoundTag(
                    {
                        "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
                        "Health": nbt.FloatTag(20.0),
                    }
                )
            ).save_to(compressed=False, little_endian=True)
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = raw
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            loaded = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
            item = {"slot": 0, "name": "minecraft:stone", "count": 1, "damage": 0, "enchantments": []}

            service.save_player(
                str(world),
                encode_player_key(LOCAL_PLAYER_KEY),
                [item],
                {},
                base_revision=loaded["player_revision"],
                allow_create_inventory=True,
            )

            saved = nbt.load(FakeDb._shared_store[LOCAL_PLAYER_KEY], compressed=False, little_endian=True).tag
            self.assertIn("Inventory", saved)
            self.assertEqual(len(saved["Inventory"]), 1)

    def test_save_player_reports_committed_when_backup_prune_fails(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "levelname.txt").write_text("Test World", encoding="utf-8")
            raw = nbt.NamedTag(
                nbt.CompoundTag(
                    {
                        "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
                        "Health": nbt.FloatTag(20.0),
                    }
                )
            ).save_to(compressed=False, little_endian=True)
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = raw
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            loaded = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
            item = {"slot": 0, "name": "minecraft:stone", "count": 1, "damage": 0, "enchantments": []}

            # Backup pruning runs after the write is committed. Its failure must not
            # turn a committed write into a seemingly retryable error.
            with patch("mcbe_editor.services.prune_backups", side_effect=OSError("prune boom")):
                result = service.save_player(
                    str(world),
                    encode_player_key(LOCAL_PLAYER_KEY),
                    [item],
                    {},
                    base_revision=loaded["player_revision"],
                    allow_create_inventory=True,
                )

            self.assertFalse(result["success"])
            self.assertTrue(result["write_committed"])
            self.assertTrue(result["validation_failed"])
            self.assertIn("Backups", result["error"])
            # The player change was actually persisted despite the prune failure.
            saved = nbt.load(FakeDb._shared_store[LOCAL_PLAYER_KEY], compressed=False, little_endian=True).tag
            self.assertIn("Inventory", saved)

    def test_save_player_writes_modern_root_equipment_lists(self):
        import tempfile
        from pathlib import Path

        def armor_item(name):
            return nbt.CompoundTag(
                {
                    "Name": nbt.StringTag(name),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                    "WasPickedUp": nbt.ByteTag(0),
                }
            )

        def empty_root_entry():
            return nbt.CompoundTag(
                {
                    "Count": nbt.ByteTag(0),
                    "Damage": nbt.ShortTag(0),
                    "Name": nbt.StringTag(""),
                    "WasPickedUp": nbt.ByteTag(0),
                }
            )

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "levelname.txt").write_text("Test World", encoding="utf-8")
            raw = nbt.NamedTag(
                nbt.CompoundTag(
                    {
                        "Inventory": nbt.ListTag(
                            [
                                nbt.CompoundTag(
                                    {
                                        "Slot": nbt.ByteTag(0),
                                        "Name": nbt.StringTag("minecraft:stone"),
                                        "Count": nbt.ByteTag(1),
                                        "Damage": nbt.ShortTag(0),
                                    }
                                )
                            ]
                        ),
                        "Armor": nbt.ListTag(
                            [
                                armor_item("minecraft:leather_helmet"),
                                armor_item("minecraft:leather_chestplate"),
                                armor_item("minecraft:leather_leggings"),
                                armor_item("minecraft:leather_boots"),
                                empty_root_entry(),
                            ]
                        ),
                        "Offhand": nbt.ListTag([armor_item("minecraft:shield")]),
                        "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
                        "Health": nbt.FloatTag(20.0),
                    }
                )
            ).save_to(compressed=False, little_endian=True)
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = raw
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)

            loaded = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
            # Modernes Shape: Ausrüstung erscheint editierbar in den UI-Slots.
            self.assertEqual(loaded["inventory"][103]["name"], "minecraft:leather_helmet")
            self.assertEqual(loaded["inventory"][100]["name"], "minecraft:leather_boots")
            self.assertEqual(loaded["inventory"][-106]["name"], "minecraft:shield")
            self.assertNotIn("root_equipment_read_only", loaded["inventory"][103])
            self.assertEqual(loaded["hidden_unknown_slots"]["inventory_protected_known_slots"], [])

            payload = [
                {"slot": 0, "name": "minecraft:stone", "count": 1, "damage": 0, "enchantments": []},
                # Helm getauscht, Brustpanzer/Hose/Stiefel bewusst weggelassen (= leeren).
                {"slot": 103, "name": "minecraft:diamond_helmet", "count": 1, "damage": 0, "enchantments": []},
                {"slot": -106, "name": "minecraft:totem_of_undying", "count": 1, "damage": 0, "enchantments": []},
            ]
            service.save_player(
                str(world),
                encode_player_key(LOCAL_PLAYER_KEY),
                payload,
                {},
                base_revision=loaded["player_revision"],
                root_equipment_editable=True,
            )

            saved = nbt.load(FakeDb._shared_store[LOCAL_PLAYER_KEY], compressed=False, little_endian=True).tag
            armor = saved["Armor"]
            self.assertEqual(len(armor), 5)
            self.assertEqual(armor[0]["Name"].py_data, "minecraft:diamond_helmet")
            self.assertNotIn("Slot", armor[0])
            for index in (1, 2, 3):
                self.assertEqual(armor[index]["Name"].py_data, "")
            self.assertEqual(saved["Offhand"][0]["Name"].py_data, "minecraft:totem_of_undying")
            # Ausrüstung landet nicht als Duplikat in der Inventory-Liste.
            inventory_slots = [int(entry["Slot"].py_data) for entry in saved["Inventory"]]
            self.assertEqual(inventory_slots, [0])

    def test_save_player_preserves_root_equipment_for_stale_clients(self):
        import tempfile
        from pathlib import Path

        def armor_item(name):
            return nbt.CompoundTag(
                {
                    "Name": nbt.StringTag(name),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                    "WasPickedUp": nbt.ByteTag(0),
                }
            )

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "levelname.txt").write_text("Test World", encoding="utf-8")
            raw = nbt.NamedTag(
                nbt.CompoundTag(
                    {
                        "Inventory": nbt.ListTag(
                            [
                                nbt.CompoundTag(
                                    {
                                        "Slot": nbt.ByteTag(0),
                                        "Name": nbt.StringTag("minecraft:stone"),
                                        "Count": nbt.ByteTag(1),
                                        "Damage": nbt.ShortTag(0),
                                    }
                                )
                            ]
                        ),
                        "Armor": nbt.ListTag(
                            [
                                armor_item("minecraft:leather_helmet"),
                                armor_item("minecraft:leather_chestplate"),
                                armor_item("minecraft:leather_leggings"),
                                armor_item("minecraft:leather_boots"),
                            ]
                        ),
                        "Offhand": nbt.ListTag([armor_item("minecraft:shield")]),
                        "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
                        "Health": nbt.FloatTag(20.0),
                    }
                )
            ).save_to(compressed=False, little_endian=True)
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = raw
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            loaded = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))

            # Stale Client: Payload ohne Ausrüstungs-Items und ohne Editable-Flag
            # darf die Root-Listen nicht leeren.
            service.save_player(
                str(world),
                encode_player_key(LOCAL_PLAYER_KEY),
                [{"slot": 0, "name": "minecraft:stone", "count": 2, "damage": 0, "enchantments": []}],
                {},
                base_revision=loaded["player_revision"],
            )

            saved = nbt.load(FakeDb._shared_store[LOCAL_PLAYER_KEY], compressed=False, little_endian=True).tag
            self.assertEqual(saved["Armor"][0]["Name"].py_data, "minecraft:leather_helmet")
            self.assertEqual(saved["Armor"][3]["Name"].py_data, "minecraft:leather_boots")
            self.assertEqual(saved["Offhand"][0]["Name"].py_data, "minecraft:shield")
            self.assertEqual(int(saved["Inventory"][0]["Count"].py_data), 2)

    def test_save_player_rejects_creating_missing_effects_without_confirmation(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag({"Slot": nbt.ByteTag(0), "Name": nbt.StringTag("minecraft:stone"), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0)})
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            loaded = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
            effect = {"id": 1, "amplifier": 0, "duration": 600, "ambient": False, "show_particles": True, "show_icon": True}

            with self.assertRaisesRegex(ValueError, "ActiveEffects.*ausdrücklich bestätigt"):
                service.save_player(str(world), encode_player_key(LOCAL_PLAYER_KEY), None, {}, effects_list=[effect], base_revision=loaded["player_revision"])

            saved = nbt.load(FakeDb._shared_store[LOCAL_PLAYER_KEY], compressed=False, little_endian=True).tag
            self.assertNotIn("ActiveEffects", saved)

    def test_save_player_creates_missing_effects_only_with_confirmation(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag({"Slot": nbt.ByteTag(0), "Name": nbt.StringTag("minecraft:stone"), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0)})
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            loaded = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
            effect = {"id": 1, "amplifier": 0, "duration": 600, "ambient": False, "show_particles": True, "show_icon": True}

            service.save_player(
                str(world),
                encode_player_key(LOCAL_PLAYER_KEY),
                None,
                {},
                effects_list=[effect],
                base_revision=loaded["player_revision"],
                allow_create_effects=True,
            )

            saved = nbt.load(FakeDb._shared_store[LOCAL_PLAYER_KEY], compressed=False, little_endian=True).tag
            self.assertIn("ActiveEffects", saved)
            self.assertEqual(saved["ActiveEffects"][0]["Id"].py_data, 1)

    def test_save_player_rejects_creating_missing_abilities_without_confirmation(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag({"Slot": nbt.ByteTag(0), "Name": nbt.StringTag("minecraft:stone"), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0)})
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            loaded = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))

            with self.assertRaisesRegex(ValueError, "abilities.*ausdrücklich bestätigt"):
                service.save_player(
                    str(world),
                    encode_player_key(LOCAL_PLAYER_KEY),
                    None,
                    {},
                    abilities_dict={"mayfly": True},
                    base_revision=loaded["player_revision"],
                )

            saved = nbt.load(FakeDb._shared_store[LOCAL_PLAYER_KEY], compressed=False, little_endian=True).tag
            self.assertNotIn("abilities", saved)

    def test_save_player_creates_missing_abilities_only_with_confirmation(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag({"Slot": nbt.ByteTag(0), "Name": nbt.StringTag("minecraft:stone"), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0)})
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            loaded = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))

            service.save_player(
                str(world),
                encode_player_key(LOCAL_PLAYER_KEY),
                None,
                {},
                abilities_dict={"mayfly": True},
                base_revision=loaded["player_revision"],
                allow_create_abilities=True,
            )

            saved = nbt.load(FakeDb._shared_store[LOCAL_PLAYER_KEY], compressed=False, little_endian=True).tag
            self.assertIn("abilities", saved)
            self.assertEqual(saved["abilities"]["mayfly"].py_data, 1)

    def test_save_world_preserves_unknown_item_nbt_via_service_layer(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "levelname.txt").write_text("Test World", encoding="utf-8")
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:diamond_sword"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                    "tag": nbt.CompoundTag(
                        {
                            "customData": nbt.StringTag("keep-me"),
                        }
                    ),
                }
            )
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)

            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            result = service.save_world(
                str(world),
                [
                    {
                        "slot": 0,
                        "name": "minecraft:diamond_sword",
                        "count": 1,
                        "damage": 0,
                        "display_name": "",
                        "lore": [],
                        "enchantments": [],
                    }
                ],
                {},
                base_revision=service._player_revision(FakeDb._shared_store[LOCAL_PLAYER_KEY]),
            )

            saved = nbt.load(FakeDb._shared_store[LOCAL_PLAYER_KEY], compressed=False, little_endian=True).tag
            saved_item = saved["Inventory"][0]

            self.assertTrue(result["success"])
            self.assertEqual(saved_item["Count"].py_data, 1)
            self.assertEqual(saved_item["tag"]["customData"].py_data, "keep-me")

    def test_save_rejects_stale_player_revision(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            first = make_player_bytes(item)
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = first
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            stale_revision = service._player_revision(first)

            item["Count"] = nbt.ByteTag(2)
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)

            with self.assertRaisesRegex(ValueError, "seit dem Laden geändert"):
                service.save_world(str(world), [], {}, base_revision=stale_revision)

    def test_save_requires_player_revision(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)

            with self.assertRaisesRegex(ValueError, "Spielerstand fehlt"):
                service.save_world(str(world), [], {})

    def test_export_player_writes_manifest_preview_and_raw_nbt(self):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            raw = make_player_bytes(item)
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = raw

            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            result = service.export_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))

            with zipfile.ZipFile(result["export_path"], "r") as zipf:
                self.assertEqual({"manifest.json", "preview.json", "player.nbt"}, set(zipf.namelist()))
                manifest = json.loads(zipf.read("manifest.json").decode("utf-8"))
                preview = json.loads(zipf.read("preview.json").decode("utf-8"))
                self.assertEqual(raw, zipf.read("player.nbt"))

            self.assertEqual(manifest["format"], "mcbe-player-export")
            self.assertEqual(preview["inventory_count"], 1)

    def test_import_player_requires_explicit_overwrite_confirmation(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            export_zip = Path(tmp) / "bad.mcbe-player.zip"
            export_zip.write_bytes(b"not a zip")
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)

            with self.assertRaisesRegex(ValueError, "bestätigt"):
                service.import_player(str(export_zip), str(world), encode_player_key(LOCAL_PLAYER_KEY), False)

    def test_import_player_rejects_incomplete_export_zip(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            export_zip = Path(tmp) / "incomplete.mcbe-player.zip"
            with zipfile.ZipFile(export_zip, "w") as zipf:
                zipf.writestr("manifest.json", "{}")
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)

            token = player_import_token(export_zip, world)
            with self.assertRaisesRegex(ValueError, "unvollständig"):
                service.import_player(str(export_zip), str(world), encode_player_key(LOCAL_PLAYER_KEY), True, import_token=token)

    def test_import_player_accepts_export_without_inventory_when_player_shape_is_safe(self):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            target_item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:dirt"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            target_raw = make_player_bytes(target_item)
            PathFakeDb._shared_stores[str(world / "db")] = {LOCAL_PLAYER_KEY: target_raw}

            read_only_raw = nbt.NamedTag(
                nbt.CompoundTag(
                    {
                        "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
                        "Health": nbt.FloatTag(20.0),
                    }
                )
            ).save_to(compressed=False, little_endian=True)
            export_zip = Path(tmp) / "read_only.mcbe-player.zip"
            manifest = {
                "format": "mcbe-player-export",
                "version": 1,
                "nbt": {"byte_length": len(read_only_raw)},
            }
            preview = {"inventory_count": 0, "has_inventory": False}
            with zipfile.ZipFile(export_zip, "w") as zipf:
                zipf.writestr("manifest.json", json.dumps(manifest))
                zipf.writestr("preview.json", json.dumps(preview))
                zipf.writestr("player.nbt", read_only_raw)

            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=PathFakeDb)
            token = player_import_token(export_zip, world)
            result = service.import_player(
                str(export_zip),
                str(world),
                encode_player_key(LOCAL_PLAYER_KEY),
                True,
                import_token=token,
                base_revision=service._player_revision(target_raw),
            )
            self.assertTrue(result["success"])
            self.assertEqual(PathFakeDb._shared_stores[str(world / "db")][LOCAL_PLAYER_KEY], read_only_raw)

    def test_import_player_writes_raw_bytes_directly_to_selected_world(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            source_item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            target_item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:dirt"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            source_raw = make_player_bytes(source_item)
            target_raw = make_player_bytes(target_item)
            original_db_path = str(world / "db")
            PathFakeDb._shared_stores[original_db_path] = {LOCAL_PLAYER_KEY: source_raw}
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=PathFakeDb)
            export = service.export_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
            PathFakeDb._shared_stores[original_db_path] = {LOCAL_PLAYER_KEY: target_raw}

            token = player_import_token(export["export_path"], world)
            service.import_player(
                export["export_path"],
                str(world),
                encode_player_key(LOCAL_PLAYER_KEY),
                True,
                import_token=token,
                base_revision=service._player_revision(target_raw),
            )

            self.assertEqual(PathFakeDb._shared_stores[original_db_path][LOCAL_PLAYER_KEY], source_raw)

    def test_import_player_rejects_stale_loaded_target_before_backup(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            source_raw = make_player_bytes(
                nbt.CompoundTag(
                    {
                        "Slot": nbt.ByteTag(0),
                        "Name": nbt.StringTag("minecraft:stone"),
                        "Count": nbt.ByteTag(1),
                        "Damage": nbt.ShortTag(0),
                    }
                )
            )
            loaded_target_raw = make_player_bytes(
                nbt.CompoundTag(
                    {
                        "Slot": nbt.ByteTag(0),
                        "Name": nbt.StringTag("minecraft:dirt"),
                        "Count": nbt.ByteTag(1),
                        "Damage": nbt.ShortTag(0),
                    }
                )
            )
            newer_target_raw = make_player_bytes(
                nbt.CompoundTag(
                    {
                        "Slot": nbt.ByteTag(0),
                        "Name": nbt.StringTag("minecraft:diamond"),
                        "Count": nbt.ByteTag(1),
                        "Damage": nbt.ShortTag(0),
                    }
                )
            )
            db_path = str(world / "db")
            PathFakeDb._shared_stores[db_path] = {LOCAL_PLAYER_KEY: source_raw}
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=PathFakeDb)
            export = service.export_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
            PathFakeDb._shared_stores[db_path][LOCAL_PLAYER_KEY] = newer_target_raw
            token = player_import_token(export["export_path"], world)

            with (
                patch("mcbe_editor.services.create_backup") as create_backup,
                self.assertRaisesRegex(ValueError, "fehlt oder ist veraltet") as raised,
            ):
                service.import_player(
                    export["export_path"],
                    str(world),
                    encode_player_key(LOCAL_PLAYER_KEY),
                    True,
                    import_token=token,
                    base_revision=service._player_revision(loaded_target_raw),
                )

            self.assertTrue(raised.exception.target_revision_stale)
            create_backup.assert_not_called()
            self.assertEqual(PathFakeDb._shared_stores[db_path][LOCAL_PLAYER_KEY], newer_target_raw)

    def test_import_player_write_gate_check_guards_backup_and_write(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            raw = make_player_bytes(item)
            original_db_path = str(world / "db")
            PathFakeDb._shared_stores[original_db_path] = {LOCAL_PLAYER_KEY: raw}
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=PathFakeDb)
            export = service.export_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))

            # A blocking gate check stops the import before backup and write.
            class GateBlocked(RuntimeError):
                pass

            def blocking_check():
                raise GateBlocked("Server läuft")

            token = player_import_token(export["export_path"], world)
            with self.assertRaises(GateBlocked):
                service.import_player(
                    export["export_path"],
                    str(world),
                    encode_player_key(LOCAL_PLAYER_KEY),
                    True,
                    import_token=token,
                    base_revision=service._player_revision(raw),
                    write_gate_check=blocking_check,
                )
            self.assertEqual(PathFakeDb._shared_stores[original_db_path][LOCAL_PLAYER_KEY], raw)

            # A server that becomes unavailable only after backup and NBT
            # validation must still block the actual LevelDB put.
            class TrackingPathFakeDb(PathFakeDb):
                put_calls = 0

                def put(self, key, value):
                    self.__class__.put_calls += 1
                    super().put(key, value)

            late_gate_checks = []

            def block_immediately_before_write():
                late_gate_checks.append("check")
                if len(late_gate_checks) == 3:
                    raise GateBlocked("Server wurde unmittelbar vor dem Schreiben aktiv")

            guarded_service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=TrackingPathFakeDb)
            with self.assertRaisesRegex(GateBlocked, "unmittelbar vor dem Schreiben"):
                guarded_service.import_player(
                    export["export_path"],
                    str(world),
                    encode_player_key(LOCAL_PLAYER_KEY),
                    True,
                    import_token=token,
                    base_revision=guarded_service._player_revision(raw),
                    write_gate_check=block_immediately_before_write,
                )
            self.assertEqual(late_gate_checks, ["check", "check", "check"])
            self.assertEqual(TrackingPathFakeDb.put_calls, 0)
            self.assertEqual(PathFakeDb._shared_stores[original_db_path][LOCAL_PLAYER_KEY], raw)

            # An allowing gate check runs before and after the verified backup
            # and once more immediately before the player record write.
            gate_checks = []
            result = service.import_player(
                export["export_path"],
                str(world),
                encode_player_key(LOCAL_PLAYER_KEY),
                True,
                import_token=token,
                base_revision=service._player_revision(raw),
                write_gate_check=lambda: gate_checks.append("check"),
            )
            self.assertTrue(result["success"])
            self.assertEqual(gate_checks, ["check", "check", "check"])

    def test_load_player_loads_specific_remote_player(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)
            remote_key = b"player_server_abc"
            FakeDb._shared_store[remote_key] = make_player_bytes(item)

            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            result = service.load_player(str(world), encode_player_key(remote_key))

            self.assertTrue(result["success"])
            self.assertIn(0, result["inventory"])
            self.assertIn("stats", result)

    def test_load_player_rejects_non_editable(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            read_only = nbt.NamedTag(
                nbt.CompoundTag(
                    {
                        "Inventory": nbt.StringTag("opaque"),
                        "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
                    }
                )
            ).save_to(compressed=False, little_endian=True)
            FakeDb._shared_store[b"player_ro"] = read_only

            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            with self.assertRaisesRegex(ValueError, "read-only"):
                service.load_player(str(world), encode_player_key(b"player_ro"))

    def test_save_player_saves_and_returns_backup(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)

            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            result = service.save_player(
                str(world),
                encode_player_key(LOCAL_PLAYER_KEY),
                [{"slot": 0, "name": "minecraft:stone", "count": 2, "damage": 0}],
                {},
                base_revision=service._player_revision(FakeDb._shared_store[LOCAL_PLAYER_KEY]),
            )

            self.assertTrue(result["success"])
            self.assertIn("backup_file", result)
            self.assertTrue(result["backup_file"].endswith(".zip"))

    def test_save_player_closes_db_before_backup(self):
        import os
        import tempfile
        from pathlib import Path

        class TrackingDb(FakeDb):
            instances = []

            def __init__(self, db_path):
                super().__init__(db_path)
                self.instances.append(self)

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)

            def fake_create_backup(world_path, *, prune_after=True):
                self.assertTrue(TrackingDb.instances)
                self.assertTrue(all(db.closed for db in TrackingDb.instances))
                backups_dir = get_backups_dir(world_path)
                os.makedirs(backups_dir, exist_ok=True)
                backup_path = os.path.join(backups_dir, "backup.zip")
                with zipfile.ZipFile(backup_path, "w") as zipf:
                    zipf.writestr("levelname.txt", "test")
                return backup_path

            def fake_prune_backups(_world_path, keep_paths=None):
                self.assertIsNotNone(keep_paths)
                self.assertGreaterEqual(len(TrackingDb.instances), 2)
                self.assertTrue(all(db.closed for db in TrackingDb.instances))

            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=TrackingDb)
            with patch("mcbe_editor.services.create_backup", fake_create_backup), patch("mcbe_editor.services.prune_backups", fake_prune_backups):
                result = service.save_player(
                    str(world),
                    encode_player_key(LOCAL_PLAYER_KEY),
                    [{"slot": 0, "name": "minecraft:stone", "count": 2, "damage": 0}],
                    {},
                    base_revision=service._player_revision(FakeDb._shared_store[LOCAL_PLAYER_KEY]),
                )

            self.assertTrue(result["success"])
            self.assertGreaterEqual(len(TrackingDb.instances), 2)

    def test_save_player_preserves_pre_write_error_when_close_also_fails(self):
        import tempfile
        from pathlib import Path

        class FailingCloseDb(FakeDb):
            def close(self):
                self.closed = True
                raise OSError("close masked original")

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FailingCloseDb)

            with self.assertRaisesRegex(ValueError, "seit dem Laden geändert"):
                service.save_player(
                    str(world),
                    encode_player_key(LOCAL_PLAYER_KEY),
                    [{"slot": 0, "name": "minecraft:stone", "count": 2, "damage": 0}],
                    {},
                    base_revision="0" * 64,
                )

    def test_load_player_preserves_read_error_when_close_also_fails(self):
        import tempfile
        from pathlib import Path

        class FailingCloseDb(FakeDb):
            def close(self):
                self.closed = True
                raise OSError("close masked original")

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FailingCloseDb)

            with (
                patch.object(service, "_get_player_info", side_effect=ValueError("original read failure")),
                self.assertRaisesRegex(ValueError, "original read failure"),
            ):
                service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))

    def test_save_player_missing_inventory_preserves_existing_inventory(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(7),
                    "Damage": nbt.ShortTag(0),
                    "tag": nbt.CompoundTag({"addonField": nbt.StringTag("keep")}),
                }
            )
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)

            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            service.save_player(
                str(world),
                encode_player_key(LOCAL_PLAYER_KEY),
                None,
                {"health": 18},
                base_revision=service._player_revision(FakeDb._shared_store[LOCAL_PLAYER_KEY]),
            )

            saved = nbt.load(FakeDb._shared_store[LOCAL_PLAYER_KEY], compressed=False, little_endian=True).tag
            self.assertEqual(saved["Inventory"][0]["Name"].py_data, "minecraft:stone")
            self.assertEqual(saved["Inventory"][0]["Count"].py_data, 7)
            self.assertEqual(saved["Inventory"][0]["tag"]["addonField"].py_data, "keep")
            self.assertEqual(saved["Health"].py_data, 18.0)

    def test_save_player_rejects_read_only(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            read_only = nbt.NamedTag(
                nbt.CompoundTag(
                    {
                        "Inventory": nbt.StringTag("opaque"),
                        "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
                    }
                )
            ).save_to(compressed=False, little_endian=True)
            FakeDb._shared_store[b"player_ro"] = read_only

            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            with self.assertRaisesRegex(ValueError, "read-only"):
                service.save_player(
                    str(world),
                    encode_player_key(b"player_ro"),
                    [],
                    {},
                )

    def test_list_backups_returns_empty_list(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            result = service.list_backups(str(world))
            self.assertTrue(result["success"])
            self.assertEqual(result["backups"], [])

    def test_restore_backup_rejects_invalid_path(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            with self.assertRaises((ValueError, FileNotFoundError)):
                service.restore_backup(str(world), "nonexistent.zip")

    def test_manual_backup_is_not_automatically_pruned(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            backup_path = Path(tmp) / "created.zip"
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)

            with (
                patch("mcbe_editor.services.create_backup", return_value=str(backup_path)) as create,
                patch(
                    "mcbe_editor.services.prune_backups",
                ) as prune,
            ):
                result = service.create_manual_backup(str(world))

            self.assertTrue(result["success"])
            self.assertEqual(result["backup_file"], "created.zip")
            self.assertNotIn("cleanup_warning", result)
            create.assert_called_once_with(
                str(world),
                prune_after=False,
                backup_kind="manual",
            )
            prune.assert_not_called()

    def test_restore_reports_retention_warning_after_world_was_replaced(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            selected = Path(tmp) / "selected.zip"
            selected.write_bytes(b"selected")
            snapshot = Path(tmp) / "snapshot.zip"
            snapshot.write_bytes(b"snapshot")
            pre_restore = Path(tmp) / "before.zip"
            pre_restore.write_bytes(b"before")
            restore_called = []
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)

            with (
                patch("mcbe_editor.services.resolve_backup_path", return_value=str(selected)),
                patch(
                    "mcbe_editor.services.snapshot_backup_for_restore",
                    return_value=str(snapshot),
                ),
                patch("mcbe_editor.services.create_backup", return_value=str(pre_restore)),
                patch(
                    "mcbe_editor.services.restore_world_backup",
                    side_effect=lambda *_args, **_kwargs: restore_called.append(True),
                ),
                patch("mcbe_editor.services.prune_backups", side_effect=OSError("retention failed")),
            ):
                result = service.restore_backup(str(world), selected.name)

            self.assertEqual(restore_called, [True])
            self.assertTrue(result["success"])
            self.assertEqual(result["pre_restore_backup"], pre_restore.name)
            self.assertEqual(result["restored_backup"], selected.name)
            self.assertIn("retention failed", result["cleanup_warning"])
            self.assertFalse(snapshot.exists())

    def test_import_player_rejects_read_only_before_creating_backup(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            read_only = nbt.NamedTag(
                nbt.CompoundTag(
                    {
                        "Inventory": nbt.StringTag("opaque"),
                        "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
                    }
                )
            ).save_to(compressed=False, little_endian=True)
            FakeDb._shared_store[b"player_ro"] = read_only

            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)

            export = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            export_result = export.export_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))

            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)

            token = player_import_token(export_result["export_path"], world)
            with (
                patch("mcbe_editor.services.create_backup") as create_backup,
                self.assertRaisesRegex(ValueError, "read-only"),
            ):
                service.import_player(
                    export_result["export_path"],
                    str(world),
                    encode_player_key(b"player_ro"),
                    True,
                    import_token=token,
                )
            create_backup.assert_not_called()


class EnderChestServiceTests(unittest.TestCase):
    def setUp(self):
        FakeDb._shared_store = {}

    def test_load_player_returns_has_ender_chest_false_when_tag_missing(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            result = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
            self.assertFalse(result["has_ender_chest"])
            self.assertEqual(result["ender_chest"], {})

    def test_load_player_returns_ender_chest_when_tag_present(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            player_tag = nbt.CompoundTag(
                {
                    "Inventory": nbt.ListTag([item]),
                    "EnderChestInventory": nbt.ListTag(
                        [
                            nbt.CompoundTag(
                                {
                                    "Slot": nbt.ByteTag(3),
                                    "Name": nbt.StringTag("minecraft:diamond"),
                                    "Count": nbt.ByteTag(5),
                                    "Damage": nbt.ShortTag(0),
                                }
                            ),
                        ]
                    ),
                    "Pos": nbt.ListTag([nbt.DoubleTag(1.0), nbt.DoubleTag(2.0), nbt.DoubleTag(3.0)]),
                    "Health": nbt.FloatTag(20.0),
                    "PlayerGameType": nbt.IntTag(0),
                }
            )
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = nbt.NamedTag(player_tag).save_to(compressed=False, little_endian=True)
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            result = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
            self.assertTrue(result["has_ender_chest"])
            self.assertIn(3, result["ender_chest"])

    def test_save_player_writes_ender_chest(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            player_tag = nbt.CompoundTag(
                {
                    "Inventory": nbt.ListTag([]),
                    "EnderChestInventory": nbt.ListTag(
                        [
                            nbt.CompoundTag(
                                {
                                    "Slot": nbt.ByteTag(0),
                                    "Name": nbt.StringTag("minecraft:diamond"),
                                    "Count": nbt.ByteTag(1),
                                    "Damage": nbt.ShortTag(0),
                                }
                            ),
                        ]
                    ),
                    "Pos": nbt.ListTag([nbt.DoubleTag(1.0), nbt.DoubleTag(2.0), nbt.DoubleTag(3.0)]),
                    "Health": nbt.FloatTag(20.0),
                    "PlayerGameType": nbt.IntTag(0),
                }
            )
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = nbt.NamedTag(player_tag).save_to(compressed=False, little_endian=True)
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            result = service.save_player(
                str(world),
                encode_player_key(LOCAL_PLAYER_KEY),
                [],
                {},
                ender_chest_list=[{"slot": 1, "name": "minecraft:emerald", "count": 3, "damage": 0}],
                base_revision=service._player_revision(FakeDb._shared_store[LOCAL_PLAYER_KEY]),
            )
            self.assertTrue(result["success"])
            saved = nbt.load(FakeDb._shared_store[LOCAL_PLAYER_KEY], compressed=False, little_endian=True).tag
            self.assertIn("EnderChestInventory", saved)
            slots = {it["Slot"].py_data for it in saved["EnderChestInventory"]}
            self.assertIn(1, slots)

    def test_save_player_does_not_add_ender_chest_tag_when_not_needed(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)
            result = service.save_player(
                str(world),
                encode_player_key(LOCAL_PLAYER_KEY),
                [{"slot": 0, "name": "minecraft:stone", "count": 1, "damage": 0}],
                {},
                base_revision=service._player_revision(FakeDb._shared_store[LOCAL_PLAYER_KEY]),
            )
            self.assertTrue(result["success"])
            saved = nbt.load(FakeDb._shared_store[LOCAL_PLAYER_KEY], compressed=False, little_endian=True).tag
            self.assertNotIn("EnderChestInventory", saved)


class TestServiceBackupRetention(unittest.TestCase):
    def test_save_player_deletes_backup_on_validation_failure(self):
        import tempfile
        from pathlib import Path

        from mcbe_editor.backup import get_backups_dir

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            FakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FakeDb)

            with self.assertRaises(ValueError):
                service.save_player(
                    str(world),
                    encode_player_key(LOCAL_PLAYER_KEY),
                    [{"slot": 99, "name": "minecraft:stone", "count": 1, "damage": 0}],
                    {},
                    base_revision=service._player_revision(FakeDb._shared_store[LOCAL_PLAYER_KEY]),
                )

            backups = list(Path(get_backups_dir(str(world))).glob("*.zip"))
            self.assertEqual(len(backups), 0)

    def test_save_player_retains_backup_on_write_failure(self):
        import tempfile
        from pathlib import Path

        from mcbe_editor.backup import get_backups_dir

        class FailingFakeDb(FakeDb):
            def put(self, key, value):
                raise RuntimeError("Disk full")

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            FailingFakeDb._shared_store[LOCAL_PLAYER_KEY] = make_player_bytes(item)
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=FailingFakeDb)

            with self.assertRaises(RuntimeError):
                service.save_player(
                    str(world),
                    encode_player_key(LOCAL_PLAYER_KEY),
                    [{"slot": 0, "name": "minecraft:stone", "count": 2, "damage": 0}],
                    {},
                    base_revision=service._player_revision(FailingFakeDb._shared_store[LOCAL_PLAYER_KEY]),
                )

            backups = list(Path(get_backups_dir(str(world))).glob("*.zip"))
            self.assertEqual(len(backups), 1)

    def test_save_player_pre_write_check_blocks_before_db_put(self):
        import tempfile
        from pathlib import Path

        order = []

        class GuardedFakeDb(FakeDb):
            put_calls = 0

            def put(self, key, value):
                order.append("put")
                self.__class__.put_calls += 1
                super().put(key, value)

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            original_bytes = make_player_bytes(item)
            GuardedFakeDb._shared_store = {LOCAL_PLAYER_KEY: original_bytes}
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=GuardedFakeDb)

            def pre_write_check():
                order.append("check")
                raise ValueError("Speichern abgelehnt: finaler Test-Guard")

            with self.assertRaisesRegex(ValueError, "finaler Test-Guard"):
                service.save_player(
                    str(world),
                    encode_player_key(LOCAL_PLAYER_KEY),
                    [{"slot": 0, "name": "minecraft:stone", "count": 2, "damage": 0}],
                    {},
                    base_revision=service._player_revision(original_bytes),
                    pre_write_check=pre_write_check,
                )

            self.assertEqual(order, ["check"])
            self.assertEqual(GuardedFakeDb.put_calls, 0)
            self.assertEqual(GuardedFakeDb._shared_store[LOCAL_PLAYER_KEY], original_bytes)

    def test_import_player_can_create_exported_key_when_missing(self):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            exported_key = b"player_server_new"
            existing_item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:dirt"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            exported_item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(1),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(2),
                    "Damage": nbt.ShortTag(0),
                }
            )
            exported_raw = make_player_bytes(exported_item)
            original_db_path = str(world / "db")
            PathFakeDb._shared_stores[original_db_path] = {LOCAL_PLAYER_KEY: make_player_bytes(existing_item)}

            export_zip = Path(tmp) / "remote.mcbe-player.zip"
            manifest = {
                "format": "mcbe-player-export",
                "version": 1,
                "player": {
                    "player_key": encode_player_key(exported_key),
                    "label": "player_server_new",
                    "editable": True,
                    "exportable": True,
                },
                "nbt": {"byte_length": len(exported_raw)},
            }
            preview = {"inventory_count": 1, "has_inventory": True}
            with zipfile.ZipFile(export_zip, "w") as zipf:
                zipf.writestr("manifest.json", json.dumps(manifest))
                zipf.writestr("preview.json", json.dumps(preview))
                zipf.writestr("player.nbt", exported_raw)

            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=PathFakeDb)
            token = player_import_token(export_zip, world)
            result = service.import_player(
                str(export_zip),
                str(world),
                "",
                True,
                import_as_exported_player=True,
                import_token=token,
            )

            self.assertTrue(result["created_new_player"])
            self.assertTrue(result["post_write_validated"])
            self.assertEqual(PathFakeDb._shared_stores[original_db_path][exported_key], exported_raw)

    def test_import_as_exported_rejects_existing_key_without_overwrite(self):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            exported_key = b"player_server_existing"
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            exported_raw = make_player_bytes(item)
            PathFakeDb._shared_stores[str(world / "db")] = {exported_key: exported_raw}
            export_zip = Path(tmp) / "existing.mcbe-player.zip"
            manifest = {
                "format": "mcbe-player-export",
                "version": 1,
                "player": {"player_key": encode_player_key(exported_key), "editable": True, "exportable": True},
                "nbt": {"byte_length": len(exported_raw)},
            }
            with zipfile.ZipFile(export_zip, "w") as zipf:
                zipf.writestr("manifest.json", json.dumps(manifest))
                zipf.writestr("preview.json", json.dumps({"inventory_count": 1, "has_inventory": True}))
                zipf.writestr("player.nbt", exported_raw)

            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=PathFakeDb)
            token = player_import_token(export_zip, world)
            with self.assertRaisesRegex(ValueError, "existiert"):
                service.import_player(
                    str(export_zip),
                    str(world),
                    "",
                    True,
                    import_as_exported_player=True,
                    import_token=token,
                )

    def test_cross_player_copy_payload_preserves_source_unknown_nbt(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            source_key = b"player_server_source"
            target_key = b"player_server_target"
            source_item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(2),
                    "Name": nbt.StringTag("minecraft:diamond_sword"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                    "tag": nbt.CompoundTag({"customData": nbt.StringTag("from-source")}),
                }
            )
            target_item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(5),
                    "Name": nbt.StringTag("minecraft:diamond_sword"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                    "tag": nbt.CompoundTag({"customData": nbt.StringTag("from-target")}),
                }
            )
            PathFakeDb._shared_stores[str(world / "db")] = {
                source_key: make_player_bytes(source_item),
                target_key: make_player_bytes(target_item),
            }
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=PathFakeDb)
            result = service.save_player(
                str(world),
                encode_player_key(target_key),
                [
                    {
                        "slot": 5,
                        "source_slot": 2,
                        "source_player_key": encode_player_key(source_key),
                        "source_container": "inventory",
                        "source_world_path": str(world),
                        "source_item_digest": _item_source_digest(source_item),
                        "name": "minecraft:diamond_sword",
                        "count": 1,
                        "damage": 0,
                    }
                ],
                {},
                base_revision=service._player_revision(PathFakeDb._shared_stores[str(world / "db")][target_key]),
            )
            saved = nbt.load(PathFakeDb._shared_stores[str(world / "db")][target_key], compressed=False, little_endian=True).tag
            saved_item = saved["Inventory"][0]
            self.assertEqual(saved_item["Slot"].py_data, 5)
            self.assertEqual(saved_item["tag"]["customData"].py_data, "from-source")
            self.assertEqual(result["item_source_digests"]["inventory"]["5"], _item_source_digest(saved_item))

    def test_cross_player_copy_rejects_source_changed_during_backup(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            source_key = b"player_server_source"
            target_key = b"player_server_target"

            def source_item(marker):
                return nbt.CompoundTag(
                    {
                        "Slot": nbt.ByteTag(2),
                        "Name": nbt.StringTag("minecraft:diamond_sword"),
                        "Count": nbt.ByteTag(1),
                        "Damage": nbt.ShortTag(0),
                        "tag": nbt.CompoundTag({"customData": nbt.StringTag(marker)}),
                    }
                )

            source_before = source_item("before-backup")
            source_after = source_item("during-backup")
            target_item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(5),
                    "Name": nbt.StringTag("minecraft:dirt"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            db_path = str(world / "db")
            target_before = make_player_bytes(target_item)
            PathFakeDb._shared_stores[db_path] = {
                source_key: make_player_bytes(source_before),
                target_key: target_before,
            }
            backup_file = Path(tmp) / "aborted-source-save.zip"

            def backup_and_change_source(_world_path, **_kwargs):
                PathFakeDb._shared_stores[db_path][source_key] = make_player_bytes(source_after)
                backup_file.write_bytes(b"backup")
                return str(backup_file)

            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=PathFakeDb)
            with (
                patch("mcbe_editor.services.create_backup", side_effect=backup_and_change_source),
                self.assertRaisesRegex(ValueError, "Item-Herkunft wurde während der Backup-Erstellung geändert"),
            ):
                service.save_player(
                    str(world),
                    encode_player_key(target_key),
                    [
                        {
                            "slot": 5,
                            "source_slot": 2,
                            "source_player_key": encode_player_key(source_key),
                            "source_container": "inventory",
                            "source_world_path": str(world),
                            "source_item_digest": _item_source_digest(source_before),
                            "name": "minecraft:diamond_sword",
                            "count": 1,
                            "damage": 0,
                        }
                    ],
                    {},
                    base_revision=service._player_revision(target_before),
                )

            self.assertEqual(PathFakeDb._shared_stores[db_path][target_key], target_before)
            self.assertFalse(backup_file.exists())

    def test_external_source_recheck_is_limited_to_the_used_slot(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            source_key = b"player_server_source"
            used_item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(2),
                    "Name": nbt.StringTag("minecraft:diamond_sword"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                    "tag": nbt.CompoundTag({"customData": nbt.StringTag("used")}),
                }
            )
            unrelated_item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(3),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                    "tag": nbt.CompoundTag({"customData": nbt.StringTag("changed-elsewhere")}),
                }
            )
            source_player = nbt.CompoundTag(
                {
                    "Inventory": nbt.ListTag([used_item, unrelated_item]),
                    "Pos": nbt.ListTag([nbt.DoubleTag(1.0), nbt.DoubleTag(2.0), nbt.DoubleTag(3.0)]),
                }
            )
            db_path = str(world / "db")
            PathFakeDb._shared_stores[db_path] = {
                source_key: nbt.NamedTag(source_player).save_to(compressed=False, little_endian=True),
            }
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=PathFakeDb)
            source_checks = {
                (
                    encode_player_key(source_key),
                    "inventory",
                    2,
                    "minecraft:diamond_sword",
                    _item_source_digest(used_item),
                )
            }

            db = PathFakeDb(world / "db")
            service._assert_external_item_sources_current(db, source_checks)

    def test_cross_player_copy_without_source_digest_is_rejected(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            source_key = b"player_server_source"
            target_key = b"player_server_target"
            source_item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(2),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                    "WasPickedUp": nbt.ByteTag(1),
                }
            )
            target_item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(5),
                    "Name": nbt.StringTag("minecraft:dirt"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            PathFakeDb._shared_stores[str(world / "db")] = {
                source_key: make_player_bytes(source_item),
                target_key: make_player_bytes(target_item),
            }
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=PathFakeDb)

            with self.assertRaisesRegex(ValueError, "Originalquelle"):
                service.save_player(
                    str(world),
                    encode_player_key(target_key),
                    [
                        {
                            "slot": 5,
                            "source_slot": 2,
                            "source_player_key": encode_player_key(source_key),
                            "source_container": "inventory",
                            "source_world_path": str(world),
                            "name": "minecraft:stone",
                            "count": 1,
                            "damage": 0,
                        }
                    ],
                    {},
                    base_revision=service._player_revision(PathFakeDb._shared_stores[str(world / "db")][target_key]),
                )

            unchanged = nbt.load(PathFakeDb._shared_stores[str(world / "db")][target_key], compressed=False, little_endian=True).tag
            self.assertEqual(unchanged["Inventory"][0]["Name"].py_data, "minecraft:dirt")

    def test_same_player_cross_world_item_origin_is_rejected(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            player_key = b"player_server_target"
            source_item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(2),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                    "tag": nbt.CompoundTag({"marker": nbt.IntTag(7)}),
                }
            )
            PathFakeDb._shared_stores[str(world / "db")] = {player_key: make_player_bytes(source_item)}
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=PathFakeDb)

            with self.assertRaisesRegex(ValueError, "andere Welt"):
                service.save_player(
                    str(world),
                    encode_player_key(player_key),
                    [
                        {
                            "slot": 5,
                            "source_slot": 2,
                            "source_player_key": encode_player_key(player_key),
                            "source_container": "inventory",
                            "source_world_path": str(world.parent / "other-world"),
                            "source_item_digest": _item_source_digest(source_item),
                            "name": "minecraft:stone",
                            "count": 1,
                            "damage": 0,
                            "has_preserved_nbt": True,
                        }
                    ],
                    {},
                    base_revision=service._player_revision(PathFakeDb._shared_stores[str(world / "db")][player_key]),
                )

            unchanged = nbt.load(PathFakeDb._shared_stores[str(world / "db")][player_key], compressed=False, little_endian=True).tag
            self.assertEqual(unchanged["Inventory"][0]["Slot"].py_data, 2)

    def test_safe_player_state_transfer_backs_up_selected_world_and_preserves_target_identity(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            remote_key = b"player_server_remote"
            source_tag = nbt.CompoundTag(
                {
                    "Inventory": nbt.ListTag(
                        [
                            nbt.CompoundTag(
                                {
                                    "Slot": nbt.ByteTag(0),
                                    "Name": nbt.StringTag("minecraft:diamond"),
                                    "Count": nbt.ByteTag(3),
                                    "Damage": nbt.ShortTag(0),
                                }
                            )
                        ]
                    ),
                    "EnderChestInventory": nbt.ListTag([]),
                    "Pos": nbt.ListTag([nbt.DoubleTag(9), nbt.DoubleTag(70), nbt.DoubleTag(-2)]),
                    "PlayerLevel": nbt.IntTag(24),
                    "ActiveEffects": nbt.ListTag([nbt.CompoundTag({"Id": nbt.ByteTag(1)})]),
                    "UniqueID": nbt.LongTag(111),
                    "SourceAddonIdentity": nbt.StringTag("skip"),
                }
            )
            target_tag = nbt.CompoundTag(
                {
                    "Inventory": nbt.ListTag([]),
                    "Pos": nbt.ListTag([nbt.DoubleTag(0), nbt.DoubleTag(64), nbt.DoubleTag(0)]),
                    "PlayerLevel": nbt.IntTag(1),
                    "UniqueID": nbt.LongTag(999),
                    "TargetAddonIdentity": nbt.StringTag("keep"),
                }
            )
            source_raw = nbt.NamedTag(source_tag).save_to(compressed=False, little_endian=True)
            target_raw = nbt.NamedTag(target_tag).save_to(compressed=False, little_endian=True)
            original_db_path = str(world / "db")
            PathFakeDb._shared_stores[original_db_path] = {
                LOCAL_PLAYER_KEY: source_raw,
                remote_key: target_raw,
            }
            service = BedrockEditorService(
                ITEMS,
                ENCHANTMENTS,
                db_factory=PathFakeDb,
                readonly_db_factory=PathFakeDb,
            )

            source_key = encode_player_key(LOCAL_PLAYER_KEY)
            target_key = encode_player_key(remote_key)
            preview = service.preview_player_state_transfer(str(world), source_key, target_key)
            result = service.transfer_player_state(
                str(world),
                source_key,
                target_key,
                confirm_transfer=True,
                transfer_token=preview["transfer_token"],
            )

            self.assertEqual(result["direction"], "local_to_multiplayer")
            self.assertFalse(result["source_deleted"])
            self.assertTrue(result["world_changed"])
            self.assertTrue(result["backup_file"])
            self.assertTrue(result["validation"]["target_identity_preserved"])
            self.assertEqual(PathFakeDb._shared_stores[original_db_path][LOCAL_PLAYER_KEY], source_raw)
            migrated = nbt.load(PathFakeDb._shared_stores[original_db_path][remote_key], compressed=False, little_endian=True).tag
            self.assertEqual(migrated["Inventory"][0]["Name"].py_data, "minecraft:diamond")
            self.assertEqual(migrated["UniqueID"].py_data, 999)
            self.assertEqual(migrated["TargetAddonIdentity"].py_data, "keep")
            self.assertNotIn("SourceAddonIdentity", migrated)

    def test_player_state_transfer_supports_multiplayer_to_local_direction(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            remote_key = b"player_server_remote"
            local_raw = nbt.NamedTag(nbt.CompoundTag({"Inventory": nbt.ListTag([]), "Pos": nbt.ListTag([]), "UniqueID": nbt.LongTag(1)})).save_to(
                compressed=False, little_endian=True
            )
            remote_raw = nbt.NamedTag(
                nbt.CompoundTag(
                    {
                        "Inventory": nbt.ListTag([]),
                        "Pos": nbt.ListTag([]),
                        "PlayerLevel": nbt.IntTag(33),
                        "UniqueID": nbt.LongTag(2),
                    }
                )
            ).save_to(compressed=False, little_endian=True)
            PathFakeDb._shared_stores[str(world / "db")] = {LOCAL_PLAYER_KEY: local_raw, remote_key: remote_raw}
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=PathFakeDb, readonly_db_factory=PathFakeDb)

            preview = service.preview_player_state_transfer(
                str(world),
                encode_player_key(remote_key),
                encode_player_key(LOCAL_PLAYER_KEY),
            )

            self.assertEqual(preview["direction"], "multiplayer_to_local")
            self.assertTrue(preview["safety"]["source_record_preserved"])
            self.assertTrue(preview["safety"]["target_identity_fields_preserved"])

    def test_player_state_transfer_rejects_stale_preview(self):
        import tempfile

        from mcbe_editor.service_errors import PlayerStateTransferPreviewStaleError

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            remote_key = b"player_server_remote"
            local_raw = make_player_bytes(
                nbt.CompoundTag(
                    {
                        "Slot": nbt.ByteTag(0),
                        "Name": nbt.StringTag("minecraft:stone"),
                        "Count": nbt.ByteTag(1),
                        "Damage": nbt.ShortTag(0),
                    }
                )
            )
            remote_raw = make_player_bytes(
                nbt.CompoundTag(
                    {
                        "Slot": nbt.ByteTag(0),
                        "Name": nbt.StringTag("minecraft:dirt"),
                        "Count": nbt.ByteTag(1),
                        "Damage": nbt.ShortTag(0),
                    }
                )
            )
            db_path = str(world / "db")
            PathFakeDb._shared_stores[db_path] = {LOCAL_PLAYER_KEY: local_raw, remote_key: remote_raw}
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=PathFakeDb, readonly_db_factory=PathFakeDb)
            source_key = encode_player_key(LOCAL_PLAYER_KEY)
            target_key = encode_player_key(remote_key)
            preview = service.preview_player_state_transfer(str(world), source_key, target_key)
            PathFakeDb._shared_stores[db_path][remote_key] = local_raw

            with self.assertRaises(PlayerStateTransferPreviewStaleError):
                service.transfer_player_state(
                    str(world),
                    source_key,
                    target_key,
                    confirm_transfer=True,
                    transfer_token=preview["transfer_token"],
                )

    def test_player_state_transfer_rechecks_write_gate_before_backup(self):
        import tempfile
        from unittest.mock import Mock

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            remote_key = b"player_server_remote"
            local_raw = make_player_bytes(
                nbt.CompoundTag(
                    {
                        "Slot": nbt.ByteTag(0),
                        "Name": nbt.StringTag("minecraft:stone"),
                        "Count": nbt.ByteTag(1),
                        "Damage": nbt.ShortTag(0),
                    }
                )
            )
            remote_raw = make_player_bytes(
                nbt.CompoundTag(
                    {
                        "Slot": nbt.ByteTag(0),
                        "Name": nbt.StringTag("minecraft:dirt"),
                        "Count": nbt.ByteTag(1),
                        "Damage": nbt.ShortTag(0),
                    }
                )
            )
            PathFakeDb._shared_stores[str(world / "db")] = {LOCAL_PLAYER_KEY: local_raw, remote_key: remote_raw}
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=PathFakeDb, readonly_db_factory=PathFakeDb)
            source_key = encode_player_key(LOCAL_PLAYER_KEY)
            target_key = encode_player_key(remote_key)
            preview = service.preview_player_state_transfer(str(world), source_key, target_key)
            create_backup = Mock(side_effect=AssertionError("backup must not start"))
            write_gate_check = Mock(side_effect=ValueError("finaler Transfer-Guard"))

            with (
                patch("mcbe_editor.services.create_backup", create_backup),
                self.assertRaisesRegex(ValueError, "finaler Transfer-Guard"),
            ):
                service.transfer_player_state(
                    str(world),
                    source_key,
                    target_key,
                    confirm_transfer=True,
                    transfer_token=preview["transfer_token"],
                    write_gate_check=write_gate_check,
                )

            write_gate_check.assert_called_once()
            create_backup.assert_not_called()

    def test_player_state_transfer_rechecks_write_gate_immediately_before_record_write(self):
        import tempfile
        from unittest.mock import Mock

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            backup_file = Path(tmp) / "world_player_transfer_backup.zip"
            remote_key = b"player_server_remote"
            source_raw = make_player_bytes(
                nbt.CompoundTag(
                    {
                        "Slot": nbt.ByteTag(0),
                        "Name": nbt.StringTag("minecraft:diamond"),
                        "Count": nbt.ByteTag(1),
                        "Damage": nbt.ShortTag(0),
                    }
                )
            )
            target_raw = make_player_bytes(
                nbt.CompoundTag(
                    {
                        "Slot": nbt.ByteTag(0),
                        "Name": nbt.StringTag("minecraft:dirt"),
                        "Count": nbt.ByteTag(1),
                        "Damage": nbt.ShortTag(0),
                    }
                )
            )
            db_path = str(world / "db")
            PathFakeDb._shared_stores[db_path] = {LOCAL_PLAYER_KEY: source_raw, remote_key: target_raw}
            service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=PathFakeDb, readonly_db_factory=PathFakeDb)
            source_key = encode_player_key(LOCAL_PLAYER_KEY)
            target_key = encode_player_key(remote_key)
            preview = service.preview_player_state_transfer(str(world), source_key, target_key)

            def backup_for_test(_world_path, **_kwargs):
                backup_file.write_bytes(b"test-backup")
                return str(backup_file)

            write_gate_check = Mock(side_effect=[None, None, ValueError("finaler Transfer-Guard vor Record-Write")])
            with (
                patch("mcbe_editor.services.create_backup", side_effect=backup_for_test),
                self.assertRaisesRegex(ValueError, "finaler Transfer-Guard vor Record-Write"),
            ):
                service.transfer_player_state(
                    str(world),
                    source_key,
                    target_key,
                    confirm_transfer=True,
                    transfer_token=preview["transfer_token"],
                    write_gate_check=write_gate_check,
                )

            self.assertEqual(write_gate_check.call_count, 3)
            self.assertFalse(backup_file.exists())
            self.assertEqual(PathFakeDb._shared_stores[db_path][LOCAL_PLAYER_KEY], source_raw)
            self.assertEqual(PathFakeDb._shared_stores[db_path][remote_key], target_raw)

    def test_player_state_transfer_validation_failure_restores_target_and_keeps_backup(self):
        import tempfile

        from mcbe_editor.service_errors import PlayerStateTransferRolledBackError

        with tempfile.TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            backup_file = Path(tmp) / "world_player_transfer_backup.zip"
            remote_key = b"player_server_remote"
            source_raw = make_player_bytes(
                nbt.CompoundTag(
                    {
                        "Slot": nbt.ByteTag(0),
                        "Name": nbt.StringTag("minecraft:diamond"),
                        "Count": nbt.ByteTag(1),
                        "Damage": nbt.ShortTag(0),
                    }
                )
            )
            target_raw = make_player_bytes(
                nbt.CompoundTag(
                    {
                        "Slot": nbt.ByteTag(0),
                        "Name": nbt.StringTag("minecraft:dirt"),
                        "Count": nbt.ByteTag(1),
                        "Damage": nbt.ShortTag(0),
                    }
                )
            )
            original_db_path = str(world / "db")
            PathFakeDb._shared_stores[original_db_path] = {
                LOCAL_PLAYER_KEY: source_raw,
                remote_key: target_raw,
            }
            service = BedrockEditorService(
                ITEMS,
                ENCHANTMENTS,
                db_factory=PathFakeDb,
                readonly_db_factory=PathFakeDb,
            )

            def backup_for_test(_world_path, **_kwargs):
                backup_file.write_bytes(b"test-backup")
                return str(backup_file)

            source_key = encode_player_key(LOCAL_PLAYER_KEY)
            target_key = encode_player_key(remote_key)
            preview = service.preview_player_state_transfer(str(world), source_key, target_key)

            with (
                patch("mcbe_editor.services.create_backup", side_effect=backup_for_test),
                patch("mcbe_editor.services.validate_player_state_transfer", side_effect=ValueError("forced validation failure")),
                self.assertRaisesRegex(PlayerStateTransferRolledBackError, "forced validation failure"),
            ):
                service.transfer_player_state(
                    str(world),
                    source_key,
                    target_key,
                    confirm_transfer=True,
                    transfer_token=preview["transfer_token"],
                )

            self.assertTrue(backup_file.exists())
            self.assertEqual(PathFakeDb._shared_stores[original_db_path][LOCAL_PLAYER_KEY], source_raw)
            self.assertEqual(PathFakeDb._shared_stores[original_db_path][remote_key], target_raw)


if __name__ == "__main__":
    unittest.main()
