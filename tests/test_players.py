import pytest
import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import Flask

nbt = pytest.importorskip("amulet_nbt")

from mcbe_editor.players import (
    classify_player_record,
    create_player_export,
    decode_player_key,
    encode_player_key,
    player_preview_from_bytes,
    read_player_export,
)
from mcbe_editor.world import LOCAL_PLAYER_KEY
from tests.conftest import make_minimal_player_tag


class TestPlayerKeyEncoding(unittest.TestCase):
    def test_round_trip_encoding(self):
        key = b"player_server_abc123"
        encoded = encode_player_key(key)
        decoded = decode_player_key(encoded)
        self.assertEqual(decoded, key)

    def test_round_trip_local_player(self):
        encoded = encode_player_key(LOCAL_PLAYER_KEY)
        decoded = decode_player_key(encoded)
        self.assertEqual(decoded, LOCAL_PLAYER_KEY)

    def test_rejects_empty_key(self):
        with self.assertRaisesRegex(ValueError, "Spieler-Key"):
            decode_player_key("")

    def test_handles_padding_variants(self):
        for key in (b"a", b"ab", b"abc", b"abcd"):
            encoded = encode_player_key(key)
            decoded = decode_player_key(encoded)
            self.assertEqual(decoded, key)

    def test_rejects_invalid_base64_characters(self):
        with self.assertRaisesRegex(ValueError, "Spieler-Key"):
            decode_player_key("../player")

    def test_rejects_oversized_encoded_key(self):
        with self.assertRaisesRegex(ValueError, "Spieler-Key"):
            decode_player_key("A" * 513)


class TestClassifyPlayerRecord(unittest.TestCase):
    def test_classifies_local_player(self):
        item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
            }
        )
        tag = make_minimal_player_tag()
        tag["Inventory"] = nbt.ListTag([item])
        raw = nbt.NamedTag(tag).save_to(compressed=False, little_endian=True)
        result = classify_player_record(LOCAL_PLAYER_KEY, raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["kind"], "local")
        self.assertTrue(result["editable"])

    def test_classifies_remote_player_with_inventory(self):
        item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
            }
        )
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag([item]),
                "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
            }
        )
        raw = nbt.NamedTag(player).save_to(compressed=False, little_endian=True)
        result = classify_player_record(b"player_server_123", raw)
        self.assertIsNotNone(result)
        self.assertTrue(result["editable"])
        self.assertEqual(result["kind"], "remote")

    def test_returns_none_for_non_player_key(self):
        tag = make_minimal_player_tag()
        raw = nbt.NamedTag(tag).save_to(compressed=False, little_endian=True)
        result = classify_player_record(b"some_other_key", raw)
        self.assertIsNone(result)

    def test_handles_corrupt_nbt_gracefully(self):
        result = classify_player_record(b"player_corrupt", b"not valid nbt")
        self.assertIsNotNone(result)
        self.assertEqual(result["confidence"], "low")
        self.assertFalse(result["editable"])

    def test_ignores_binary_tilde_leveldb_keys_without_player_nbt(self):
        result = classify_player_record(b"~\x01\x00\x00\x08\x01", b"not valid nbt")
        self.assertIsNone(result)

    def test_ignores_server_and_client_prefixes_without_player_nbt(self):
        self.assertIsNone(classify_player_record(b"server_metadata", b"not valid nbt"))
        self.assertIsNone(classify_player_record(b"client_blob", b"not valid nbt"))

    def test_marks_player_without_inventory_as_editable_but_requires_explicit_inventory_creation(self):
        player = nbt.CompoundTag(
            {
                "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
                "Health": nbt.FloatTag(20.0),
            }
        )
        raw = nbt.NamedTag(player).save_to(compressed=False, little_endian=True)
        result = classify_player_record(b"player_no_inv", raw)
        self.assertIsNotNone(result)
        self.assertTrue(result["editable"])
        self.assertFalse(result["inventory_will_be_created"])
        self.assertTrue(result["inventory_create_requires_confirmation"])
        self.assertIn("Inventory-Tag fehlt", result["reason"])

    def test_marks_player_with_bedrock_level_aliases_as_player(self):
        player = nbt.CompoundTag(
            {
                "PlayerGameMode": nbt.IntTag(0),
                "PlayerLevel": nbt.IntTag(8),
                "PlayerLevelProgress": nbt.FloatTag(0.5),
            }
        )
        raw = nbt.NamedTag(player).save_to(compressed=False, little_endian=True)
        result = classify_player_record(b"player_level_aliases", raw)
        self.assertIsNotNone(result)
        self.assertTrue(result["editable"])
        self.assertTrue(result["inventory_create_requires_confirmation"])

    def test_local_player_without_inventory_loads_but_does_not_auto_create_inventory(self):
        player = nbt.CompoundTag(
            {
                "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
            }
        )
        raw = nbt.NamedTag(player).save_to(compressed=False, little_endian=True)
        result = classify_player_record(LOCAL_PLAYER_KEY, raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["kind"], "local")
        self.assertTrue(result["editable"])
        self.assertFalse(result["inventory_will_be_created"])
        self.assertTrue(result["inventory_create_requires_confirmation"])

    def test_marks_opaque_inventory_as_read_only(self):
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.StringTag("opaque"),
                "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
            }
        )
        raw = nbt.NamedTag(player).save_to(compressed=False, little_endian=True)
        result = classify_player_record(b"player_opaque", raw)
        self.assertIsNotNone(result)
        self.assertFalse(result["editable"])
        self.assertTrue(result["exportable"])
        self.assertTrue(result["inventory_opaque"])


class TestPlayerPreview(unittest.TestCase):
    def test_preview_returns_correct_counts(self):
        item = nbt.CompoundTag(
            {
                "Slot": nbt.ByteTag(0),
                "Name": nbt.StringTag("minecraft:stone"),
                "Count": nbt.ByteTag(1),
                "Damage": nbt.ShortTag(0),
            }
        )
        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag([item]),
                "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
            }
        )
        raw = nbt.NamedTag(player).save_to(compressed=False, little_endian=True)
        preview = player_preview_from_bytes(raw)
        self.assertEqual(preview["inventory_count"], 1)
        self.assertTrue(preview["has_inventory"])

    def test_preview_identifies_missing_inventory(self):
        player = nbt.CompoundTag(
            {
                "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
            }
        )
        raw = nbt.NamedTag(player).save_to(compressed=False, little_endian=True)
        preview = player_preview_from_bytes(raw)
        self.assertEqual(preview["inventory_count"], 0)
        self.assertFalse(preview["has_inventory"])


class TestReadPlayerExport(unittest.TestCase):
    def test_classify_player_record_handles_non_compound_root(self):
        raw = nbt.NamedTag(nbt.StringTag("not-a-player")).save_to(compressed=False, little_endian=True)

        result = classify_player_record(b"player_server_abc", raw)

        self.assertIsNotNone(result)
        self.assertFalse(result["editable"])
        self.assertFalse(result["exportable"])
        self.assertIn("Compound-Root", result["reason"])

    def test_reads_valid_export_successfully(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "player.mcbe-player.zip"
            item = nbt.CompoundTag(
                {
                    "Slot": nbt.ByteTag(0),
                    "Name": nbt.StringTag("minecraft:stone"),
                    "Count": nbt.ByteTag(1),
                    "Damage": nbt.ShortTag(0),
                }
            )
            player = nbt.CompoundTag(
                {
                    "Inventory": nbt.ListTag([item]),
                    "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
                }
            )
            raw = nbt.NamedTag(player).save_to(compressed=False, little_endian=True)
            manifest_data = {
                "format": "mcbe-player-export",
                "version": 1,
                "nbt": {"byte_length": len(raw)},
            }
            with zipfile.ZipFile(path, "w") as zipf:
                zipf.writestr("manifest.json", json.dumps(manifest_data))
                zipf.writestr("preview.json", json.dumps({"inventory_count": 1}))
                zipf.writestr("player.nbt", raw)
            manifest, preview, raw_bytes = read_player_export(str(path))
            self.assertEqual(manifest["format"], "mcbe-player-export")
            self.assertEqual(preview["inventory_count"], 1)
            self.assertEqual(raw_bytes, raw)

    def test_rejects_missing_file(self):
        with self.assertRaisesRegex(ValueError, "existiert"):
            read_player_export("/nonexistent/file.zip")

    def test_rejects_export_with_path_traversal_member(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.mcbe-player.zip"
            with zipfile.ZipFile(path, "w") as zipf:
                zipf.writestr("manifest.json", json.dumps({"format": "mcbe-player-export", "version": 1}))
                zipf.writestr("../preview.json", "{}")
                zipf.writestr("player.nbt", b"x")
            with self.assertRaisesRegex(ValueError, "unsichere"):
                read_player_export(str(path))

    def test_rejects_non_object_nbt_metadata_cleanly(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-metadata.mcbe-player.zip"
            raw = nbt.NamedTag(make_minimal_player_tag()).save_to(compressed=False, little_endian=True)
            manifest_data = {
                "format": "mcbe-player-export",
                "version": 1,
                "nbt": "not-an-object",
            }
            with zipfile.ZipFile(path, "w") as zipf:
                zipf.writestr("manifest.json", json.dumps(manifest_data))
                zipf.writestr("preview.json", "{}")
                zipf.writestr("player.nbt", raw)
            with self.assertRaisesRegex(ValueError, "NBT-Metadaten"):
                read_player_export(str(path))


def test_create_player_export_removes_partial_archive_on_write_failure(monkeypatch, tmp_path):
    output_dir = tmp_path / "exports"
    raw = nbt.NamedTag(make_minimal_player_tag()).save_to(compressed=False, little_endian=True)
    original_writestr = zipfile.ZipFile.writestr
    calls = 0

    def fail_during_write(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulierter Schreibfehler")
        return original_writestr(self, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "writestr", fail_during_write)
    with pytest.raises(OSError, match="simulierter Schreibfehler"):
        create_player_export(
            str(tmp_path / "world"),
            {"label": "Alex", "player_key": "key", "editable": True, "exportable": True},
            raw,
            output_dir=str(output_dir),
        )

    assert list(output_dir.iterdir()) == []


if __name__ == "__main__":
    unittest.main()


def test_fallback_scanner_detects_player_shape_on_unknown_leveldb_key():
    player = nbt.CompoundTag(
        {
            "Pos": nbt.ListTag([nbt.DoubleTag(5.0), nbt.DoubleTag(70.0), nbt.DoubleTag(5.0)]),
            "Health": nbt.FloatTag(20.0),
            "EnderChestInventory": nbt.ListTag([]),
        }
    )
    raw = nbt.NamedTag(player).save_to(compressed=False, little_endian=True)

    from mcbe_editor.players import PlayerScanner

    class Db:
        def get(self, key):
            raise KeyError(key)

        def iter_items(self):
            return [(b"xuid_123456", raw), (b"not-nbt", b"chunk-ish")]

    players = PlayerScanner(Db()).list_players()

    assert len(players) == 1
    assert players[0]["kind"] == "unknown"
    assert players[0]["editable"] is True
    assert players[0]["inventory_will_be_created"] is False
    assert players[0]["inventory_create_requires_confirmation"] is True


def test_fallback_scanner_detects_unknown_player_alongside_local_player():
    local = make_minimal_player_tag()
    unknown = nbt.CompoundTag(
        {
            "Pos": nbt.ListTag([nbt.DoubleTag(5.0), nbt.DoubleTag(70.0), nbt.DoubleTag(5.0)]),
            "Health": nbt.FloatTag(20.0),
            "EnderChestInventory": nbt.ListTag([]),
        }
    )
    local_raw = nbt.NamedTag(local).save_to(compressed=False, little_endian=True)
    unknown_raw = nbt.NamedTag(unknown).save_to(compressed=False, little_endian=True)

    from mcbe_editor.players import PlayerScanner

    class Db:
        def get(self, key):
            if key == LOCAL_PLAYER_KEY:
                return local_raw
            raise KeyError(key)

        def iter_items(self):
            return [(LOCAL_PLAYER_KEY, local_raw), (b"xuid_123456", unknown_raw)]

    players = PlayerScanner(Db()).list_players()

    assert [(player["kind"], player["raw_key_preview"]) for player in players] == [
        ("local", "Lokaler Spieler"),
        ("unknown", "xuid_123456"),
    ]


def test_unknown_key_fallback_rejects_actor_with_generic_inventory_shape():
    actor = nbt.CompoundTag(
        {
            "Pos": nbt.ListTag([nbt.DoubleTag(5.0), nbt.DoubleTag(70.0), nbt.DoubleTag(5.0)]),
            "Health": nbt.FloatTag(20.0),
            "Inventory": nbt.ListTag([]),
        }
    )
    raw = nbt.NamedTag(actor).save_to(compressed=False, little_endian=True)

    from mcbe_editor.players import PlayerScanner

    class Db:
        def get(self, key):
            raise KeyError(key)

        def iter_items(self):
            return [(b"actorprefix-test", raw)]

    assert PlayerScanner(Db()).list_players() == []


def test_unknown_key_fallback_does_not_fully_parse_generic_actor_candidates(monkeypatch):
    actor = nbt.CompoundTag(
        {
            "Pos": nbt.ListTag([nbt.DoubleTag(5.0), nbt.DoubleTag(70.0), nbt.DoubleTag(5.0)]),
            "Health": nbt.FloatTag(20.0),
            "Inventory": nbt.ListTag([]),
        }
    )
    raw = nbt.NamedTag(actor).save_to(compressed=False, little_endian=True)

    import mcbe_editor.players as players_module

    original_classifier = players_module.classify_player_record
    fallback_calls = 0

    def tracking_classifier(key, raw_bytes, *, allow_unknown_key=False):
        nonlocal fallback_calls
        if allow_unknown_key:
            fallback_calls += 1
        return original_classifier(key, raw_bytes, allow_unknown_key=allow_unknown_key)

    monkeypatch.setattr(players_module, "classify_player_record", tracking_classifier)

    class Db:
        def get(self, key):
            raise KeyError(key)

        def iter_items(self):
            return [(f"actorprefix-{index}".encode(), raw) for index in range(800)]

    assert players_module.PlayerScanner(Db()).list_players() == []
    assert fallback_calls == 0


def test_scanner_does_not_show_binary_tilde_records_when_editable_players_exist():
    item = nbt.CompoundTag({"Slot": nbt.ByteTag(0), "Name": nbt.StringTag("minecraft:stone"), "Count": nbt.ByteTag(1)})
    player = make_minimal_player_tag()
    player["Inventory"] = nbt.ListTag([item])
    raw = nbt.NamedTag(player).save_to(compressed=False, little_endian=True)

    from mcbe_editor.players import PlayerScanner

    class Db:
        def get(self, key):
            raise KeyError(key)

        def iter_items(self):
            return [(b"player_server_abc", raw), (b"~\x01\x00\x00\x08\x01", b"not valid nbt")]

    players = PlayerScanner(Db()).list_players()

    assert [player["raw_key_preview"] for player in players] == ["player_server_abc"]


def test_local_player_alias_without_inventory_is_editable():
    player = nbt.CompoundTag({"Health": nbt.FloatTag(20.0)})
    raw = nbt.NamedTag(player).save_to(compressed=False, little_endian=True)
    result = classify_player_record(b"local_player", raw)

    assert result is not None
    assert result["kind"] == "local"
    assert result["label"] == "Lokaler Spieler"
    assert result["editable"] is True
    assert result["inventory_will_be_created"] is False
    assert result["inventory_create_requires_confirmation"] is True


def test_local_player_alias_label_uses_request_locale():
    player = nbt.CompoundTag({"Health": nbt.FloatTag(20.0)})
    raw = nbt.NamedTag(player).save_to(compressed=False, little_endian=True)
    app = Flask(__name__)

    with app.test_request_context(headers={"Accept-Language": "en"}):
        result = classify_player_record(b"local_player", raw)

    assert result is not None
    assert result["label"] == "Local player"


def test_ender_chest_only_player_is_editable_and_importable():
    player = nbt.CompoundTag({"EnderChestInventory": nbt.ListTag([])})
    raw = nbt.NamedTag(player).save_to(compressed=False, little_endian=True)

    classified = classify_player_record(b"player_ender_only", raw)
    preview = player_preview_from_bytes(raw)
    from mcbe_editor.players import evaluate_player_import_preview

    decision = evaluate_player_import_preview(preview)
    assert classified is not None
    assert classified["editable"] is True
    assert classified["reason_code"] == "ok"
    assert decision["importable"] is True
    assert decision["reason_code"] == "ender_chest"


def test_opaque_ender_chest_makes_player_and_import_read_only():
    player = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([]),
            "EnderChestInventory": nbt.StringTag("opaque"),
        }
    )
    raw = nbt.NamedTag(player).save_to(compressed=False, little_endian=True)

    classified = classify_player_record(b"player_opaque_ender", raw)
    preview = player_preview_from_bytes(raw)
    from mcbe_editor.players import evaluate_player_import_preview

    decision = evaluate_player_import_preview(preview)
    assert classified is not None
    assert classified["editable"] is False
    assert classified["reason_code"] == "ender_chest_opaque"
    assert "unbekannten NBT-Typ" in classified["reason"]
    assert decision["importable"] is False
    assert decision["reason_code"] == "ender_chest_opaque"


def test_parallel_player_exports_never_publish_the_same_path(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, datetime as real_datetime

    raw = nbt.NamedTag(make_minimal_player_tag()).save_to(compressed=False, little_endian=True)

    class FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            value = real_datetime(2026, 7, 12, 12, 0, 0, 123456, tzinfo=UTC)
            return value if tz is not None else value.replace(tzinfo=None)

    monkeypatch.setattr("mcbe_editor.players.datetime", FixedDateTime)

    def export_once():
        return create_player_export(
            str(tmp_path / "world"),
            {"label": "Same", "player_key": "key", "editable": True, "exportable": True},
            raw,
            output_dir=str(tmp_path / "exports"),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        paths = list(pool.map(lambda _index: export_once(), range(2)))

    assert len(set(paths)) == 2
    assert all(Path(path).is_file() for path in paths)


def test_player_export_publish_fallback_never_replaces_existing_target(tmp_path):
    import errno
    import zipfile
    from unittest.mock import patch

    from mcbe_editor.players import _publish_player_export_no_clobber

    source = tmp_path / "source.tmp"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("manifest.json", "{}")
        archive.writestr("preview.json", "{}")
        archive.writestr("player.nbt", b"new")
    existing = tmp_path / "Steve_fixed_deadbeef.mcbe-player.zip"
    existing.write_bytes(b"existing")

    with (
        patch("mcbe_editor.players.secrets.token_hex", return_value="deadbeef"),
        patch("mcbe_editor.players.os.link", side_effect=OSError(errno.EPERM, "no hardlinks")),
        pytest.raises(RuntimeError, match="kollisionsfrei"),
    ):
        _publish_player_export_no_clobber(str(source), str(tmp_path), "Steve", "fixed")

    assert existing.read_bytes() == b"existing"
    assert source.exists()


def test_player_export_integrity_rejects_crc_corruption(tmp_path):
    import struct

    from mcbe_editor.players import _verify_player_export_archive

    export_path = tmp_path / "corrupt.mcbe-player.zip"
    with zipfile.ZipFile(export_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", "{}")
        archive.writestr("preview.json", "{}")
        archive.writestr("player.nbt", b"original-player-data")

    with zipfile.ZipFile(export_path, "r") as archive:
        info = archive.getinfo("player.nbt")
    raw = bytearray(export_path.read_bytes())
    name_length, extra_length = struct.unpack_from("<HH", raw, info.header_offset + 26)
    payload_offset = info.header_offset + 30 + name_length + extra_length
    raw[payload_offset] ^= 0x01
    export_path.write_bytes(raw)

    assert zipfile.is_zipfile(export_path)
    with pytest.raises(ValueError, match="CRC-Fehler"):
        _verify_player_export_archive(str(export_path))


def test_create_player_export_removes_archive_when_integrity_check_fails(monkeypatch, tmp_path):
    raw = nbt.NamedTag(make_minimal_player_tag()).save_to(compressed=False, little_endian=True)
    output_dir = tmp_path / "exports"

    def reject_archive(_path):
        raise ValueError("simulierter CRC-Fehler")

    monkeypatch.setattr("mcbe_editor.players._verify_player_export_archive", reject_archive)
    with pytest.raises(ValueError, match="simulierter CRC-Fehler"):
        create_player_export(
            str(tmp_path / "world"),
            {"label": "Alex", "player_key": "key", "editable": True, "exportable": True},
            raw,
            output_dir=str(output_dir),
        )

    assert list(output_dir.iterdir()) == []
