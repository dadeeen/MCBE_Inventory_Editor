"""Tests for the pure-Python readonly LevelDB reader."""

import hashlib
import os
import struct
import unittest

from mcbe_editor.leveldb_readonly import (
    CorruptDatabaseError,
    ReadonlyLevelDbAdapter,
    _RECORD_FIRST,
    _RECORD_FULL,
    _RECORD_LAST,
    _RECORD_MIDDLE,
    _TAG_LOG_NUMBER,
    _TAG_PREV_LOG_NUMBER,
    _TYPE_VALUE,
    _crc32c,
    _iter_log_records,
    _mask_crc32c,
    _parse_manifest,
)

try:
    import leveldb  # amulet-leveldb

    HAS_LEVELDB = True
except ImportError:
    HAS_LEVELDB = False

import tempfile


def _snapshot_dir(path):
    result = {}
    for name in os.listdir(path):
        full = os.path.join(path, name)
        stat = os.stat(full)
        result[name] = (stat.st_size, stat.st_mtime_ns)
    return result


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _length_prefixed(value: bytes) -> bytes:
    return _varint(len(value)) + value


def _log_record(payload: bytes, record_type: int = _RECORD_FULL) -> bytes:
    checksum = _mask_crc32c(_crc32c(bytes((record_type,)) + payload))
    return struct.pack("<IHB", checksum, len(payload), record_type) + payload


def _write_batch(sequence: int, entries: list[tuple[bytes, bytes]]) -> bytes:
    payload = bytearray(struct.pack("<QI", sequence, len(entries)))
    for key, value in entries:
        payload.append(_TYPE_VALUE)
        payload.extend(_length_prefixed(key))
        payload.extend(_length_prefixed(value))
    return bytes(payload)


def test_log_record_crc_is_validated():
    record = bytearray(_log_record(b"manifest-entry"))
    record[0] ^= 0x01

    with unittest.TestCase().assertRaises(CorruptDatabaseError):
        list(_iter_log_records(bytes(record)))


def test_fragmented_log_record_requires_first_fragment():
    with unittest.TestCase().assertRaises(CorruptDatabaseError):
        list(_iter_log_records(_log_record(b"middle", _RECORD_MIDDLE)))

    with unittest.TestCase().assertRaises(CorruptDatabaseError):
        list(_iter_log_records(_log_record(b"last", _RECORD_LAST)))


def test_full_log_record_does_not_reuse_unfinished_fragments():
    data = _log_record(b"stale", _RECORD_FIRST) + _log_record(b"complete", _RECORD_FULL)

    assert list(_iter_log_records(data)) == [b"complete"]


def test_valid_fragmented_log_record_is_joined():
    data = _log_record(b"first-", _RECORD_FIRST) + _log_record(b"middle-", _RECORD_MIDDLE) + _log_record(b"last", _RECORD_LAST)

    assert list(_iter_log_records(data)) == [b"first-middle-last"]


def test_manifest_tracks_prev_log_number():
    manifest = _log_record(_varint(_TAG_LOG_NUMBER) + _varint(7) + _varint(_TAG_PREV_LOG_NUMBER) + _varint(6))

    _files, log_number, prev_log_number = _parse_manifest(manifest)

    assert log_number == 7
    assert prev_log_number == 6


def test_prev_log_number_is_replayed(tmp_path):
    db_path = tmp_path / "db"
    db_path.mkdir()
    (db_path / "CURRENT").write_text("MANIFEST-000001\n", encoding="utf-8")
    (db_path / "MANIFEST-000001").write_bytes(_log_record(_varint(_TAG_LOG_NUMBER) + _varint(7) + _varint(_TAG_PREV_LOG_NUMBER) + _varint(6)))
    (db_path / "000005.log").write_bytes(_log_record(_write_batch(1, [(b"ignored", b"old")])))
    (db_path / "000006.log").write_bytes(_log_record(_write_batch(2, [(b"player", b"from-prev-log")])))

    reader = ReadonlyLevelDbAdapter(str(db_path))
    try:
        assert reader.get(b"player") == b"from-prev-log"
        with unittest.TestCase().assertRaises(KeyError):
            reader.get(b"ignored")
    finally:
        reader.close()


def test_service_readonly_open_does_not_fallback_to_mutating_adapter(monkeypatch, tmp_path):
    from mcbe_editor import services

    world_path = tmp_path / "world"
    (world_path / "db").mkdir(parents=True)
    fallback_calls = []

    def mutating_adapter(_db_path):
        fallback_calls.append(_db_path)
        raise AssertionError("mutating adapter must not be called")

    class FailingReadonlyAdapter:
        def __init__(self, _db_path):
            raise CorruptDatabaseError("broken manifest")

    monkeypatch.setattr(services, "LevelDbAdapter", mutating_adapter)
    monkeypatch.setattr(services, "ReadonlyLevelDbAdapter", FailingReadonlyAdapter)
    service = services.BedrockEditorService({}, {}, db_factory=mutating_adapter)

    with unittest.TestCase().assertRaises(RuntimeError):
        service._open_db_readonly(str(world_path))

    assert fallback_calls == []


@unittest.skipUnless(HAS_LEVELDB, "amulet-leveldb wird für die Fixture-Erstellung benötigt")
class ReadonlyLevelDbAdapterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "db")

    def _create_db(self, entries, *, deletes=(), close=True):
        db = leveldb.LevelDB(self.db_path, True)
        for key, value in entries:
            db.put(key, value)
        for key in deletes:
            db.delete(key)
        if close:
            db.close()
        return db

    def test_reads_wal_only_data(self):
        # Small writes stay in the write-ahead log; no table files exist yet.
        entries = [(f"key_{i}".encode(), f"value_{i}".encode()) for i in range(50)]
        self._create_db(entries)
        self.assertFalse(any(name.endswith((".ldb", ".sst")) for name in os.listdir(self.db_path)))

        reader = ReadonlyLevelDbAdapter(self.db_path)
        try:
            for key, value in entries:
                self.assertEqual(reader.get(key), value)
            self.assertEqual(dict(reader.iter_items()), dict(entries))
        finally:
            reader.close()

    def test_reads_compacted_table_files(self):
        # Large values force memtable flushes into .ldb table files.
        entries = [(f"key_{i:05d}".encode(), os.urandom(64) * 256) for i in range(300)]
        db = self._create_db(entries, close=False)
        db.compact()
        db.close()
        self.assertTrue(any(name.endswith((".ldb", ".sst")) for name in os.listdir(self.db_path)))

        reader = ReadonlyLevelDbAdapter(self.db_path)
        try:
            self.assertEqual(reader.get(entries[0][0]), entries[0][1])
            self.assertEqual(reader.get(entries[-1][0]), entries[-1][1])
            self.assertEqual(dict(reader.iter_items()), dict(entries))
        finally:
            reader.close()

    def test_overwrites_and_deletes(self):
        entries = [(b"stable", b"v1"), (b"changed", b"old"), (b"gone", b"bye")]
        db = self._create_db(entries, close=False)
        db.put(b"changed", b"new")
        db.delete(b"gone")
        db.close()

        reader = ReadonlyLevelDbAdapter(self.db_path)
        try:
            self.assertEqual(reader.get(b"stable"), b"v1")
            self.assertEqual(reader.get(b"changed"), b"new")
            with self.assertRaises(KeyError):
                reader.get(b"gone")
            with self.assertRaises(KeyError):
                reader.get(b"never_existed")
            self.assertEqual(dict(reader.iter_items()), {b"stable": b"v1", b"changed": b"new"})
        finally:
            reader.close()

    def test_overwrite_across_compaction_and_wal(self):
        # Old value lands in a table file, newer value only in the WAL.
        db = self._create_db([(b"player", b"old"), (b"filler", os.urandom(1024))], close=False)
        db.compact()
        db.put(b"player", b"new")
        db.delete(b"filler")
        db.close()

        reader = ReadonlyLevelDbAdapter(self.db_path)
        try:
            self.assertEqual(reader.get(b"player"), b"new")
            with self.assertRaises(KeyError):
                reader.get(b"filler")
            self.assertEqual(dict(reader.iter_items()), {b"player": b"new"})
        finally:
            reader.close()

    def test_matches_amulet_reader(self):
        entries = [(f"k{i}".encode(), f"v{i}".encode() * (i % 7 + 1)) for i in range(200)]
        db = self._create_db(entries, deletes=[b"k13", b"k77"], close=False)
        db.compact()
        db.put(b"k5", b"overwritten")
        db.close()

        expected = {}
        verify = leveldb.LevelDB(self.db_path)
        for key, value in verify.items():
            expected[key] = value
        verify.close()

        reader = ReadonlyLevelDbAdapter(self.db_path)
        try:
            self.assertEqual(dict(reader.iter_items()), expected)
            for key, value in expected.items():
                self.assertEqual(reader.get(key), value)
        finally:
            reader.close()

    def test_prefix_keys_at_block_boundaries(self):
        # Regression: when a key is a prefix of its successor, LevelDB cannot
        # shorten the index separator, so the separator's user-key equals the
        # block's last key.  A bytewise internal-key search would then pick the
        # wrong block and miss the key entirely.  Large values force one entry
        # per block so every such pair sits on a block boundary.
        entries = []
        for i in range(40):
            base = f"prefix_{i:03d}".encode()
            entries.append((base, os.urandom(8) * 1024))
            entries.append((base + b"0", os.urandom(8) * 1024))
        db = self._create_db(entries, close=False)
        db.compact()
        db.close()

        reader = ReadonlyLevelDbAdapter(self.db_path)
        try:
            for key, value in entries:
                self.assertEqual(reader.get(key), value, f"Key {key!r} nicht gefunden")
            self.assertEqual(dict(reader.iter_items()), dict(entries))
        finally:
            reader.close()

    def test_multi_level_compaction(self):
        # Two compaction rounds push tables into levels >= 1; overwrites after
        # the last compaction live only in the WAL.  get() must search all
        # levels and iter_items() must merge them with correct precedence.
        db = leveldb.LevelDB(self.db_path, True)
        for i in range(1500):
            db.put(f"k{i:05d}".encode(), os.urandom(2048))
        db.compact()
        for i in range(1500, 3000):
            db.put(f"k{i:05d}".encode(), os.urandom(2048))
        db.compact()
        overwrites = {f"k{i:05d}".encode(): b"v2_%d" % i for i in range(0, 3000, 7)}
        for key, value in overwrites.items():
            db.put(key, value)
        db.close()

        expected = {}
        verify = leveldb.LevelDB(self.db_path)
        for key, value in verify.items():
            expected[key] = value
        verify.close()

        reader = ReadonlyLevelDbAdapter(self.db_path)
        try:
            deep_levels = [level for level in reader._files if level >= 1]
            self.assertTrue(deep_levels, "Fixture erzeugte keine tiefen Levels")
            for key, value in overwrites.items():
                self.assertEqual(reader.get(key), value)
            self.assertEqual(dict(reader.iter_items()), expected)
        finally:
            reader.close()

    def test_put_is_rejected(self):
        self._create_db([(b"a", b"1")])
        reader = ReadonlyLevelDbAdapter(self.db_path)
        try:
            with self.assertRaises(RuntimeError):
                reader.put(b"a", b"2")
        finally:
            reader.close()

    def test_does_not_modify_database_directory(self):
        entries = [(f"key_{i}".encode(), os.urandom(512)) for i in range(100)]
        db = self._create_db(entries, close=False)
        db.compact()
        db.close()

        before = _snapshot_dir(self.db_path)
        reader = ReadonlyLevelDbAdapter(self.db_path)
        try:
            dict(reader.iter_items())
            reader.get(entries[0][0])
        finally:
            reader.close()
        self.assertEqual(_snapshot_dir(self.db_path), before)

    def test_missing_current_raises(self):
        os.makedirs(self.db_path)
        with self.assertRaises(FileNotFoundError):
            ReadonlyLevelDbAdapter(self.db_path)

    def test_corrupt_current_raises(self):
        os.makedirs(self.db_path)
        with open(os.path.join(self.db_path, "CURRENT"), "wb") as handle:
            handle.write(b"../evil\n")
        with self.assertRaises(CorruptDatabaseError):
            ReadonlyLevelDbAdapter(self.db_path)

    def test_closed_reader_rejects_access(self):
        self._create_db([(b"a", b"1")])
        reader = ReadonlyLevelDbAdapter(self.db_path)
        reader.close()
        with self.assertRaises(RuntimeError):
            reader.get(b"a")
        with self.assertRaises(RuntimeError):
            list(reader.iter_items())


@unittest.skipUnless(HAS_LEVELDB, "amulet-leveldb wird für die Fixture-Erstellung benötigt")
class ServiceReadonlyIntegrationTests(unittest.TestCase):
    """End-to-end: read paths of the service must not mutate the world."""

    def setUp(self):
        try:
            import amulet_nbt  # noqa: F401
        except ImportError:
            self.skipTest("amulet_nbt wird für die Fixture-Erstellung benötigt")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.world_path = os.path.join(self._tmp.name, "world")
        os.makedirs(self.world_path)
        with open(os.path.join(self.world_path, "levelname.txt"), "w", encoding="utf-8") as handle:
            handle.write("Readonly Testwelt")
        self._write_local_player()

    def _write_local_player(self):
        import amulet_nbt as nbt

        player = nbt.CompoundTag(
            {
                "Inventory": nbt.ListTag(),
                "Pos": nbt.ListTag([nbt.DoubleTag(1.0), nbt.DoubleTag(64.0), nbt.DoubleTag(3.0)]),
                "Health": nbt.FloatTag(20.0),
                "PlayerGameType": nbt.IntTag(0),
            }
        )
        raw = nbt.NamedTag(player).save_to(compressed=False, little_endian=True)
        db = leveldb.LevelDB(os.path.join(self.world_path, "db"), True)
        db.put(b"~local_player", raw)
        db.close()

    def test_read_paths_leave_world_untouched(self):
        from mcbe_editor.services import BedrockEditorService
        from mcbe_editor.world import LOCAL_PLAYER_KEY

        service = BedrockEditorService({}, {})
        db_dir = os.path.join(self.world_path, "db")
        before = _snapshot_dir(db_dir)

        listed = service.list_players(self.world_path)
        self.assertTrue(listed["success"])
        self.assertEqual(len(listed["players"]), 1)

        from mcbe_editor.players import encode_player_key

        loaded = service.load_player(self.world_path, encode_player_key(LOCAL_PLAYER_KEY))
        self.assertTrue(loaded["success"])

        self.assertEqual(_snapshot_dir(db_dir), before, "Lesepfade dürfen die Welt nicht verändern")

    def _db_content_digest(self):
        """Hash every db file by content, not just size/mtime.

        Opening the mutating adapter rewrites CURRENT in place at identical
        size, so a size-only comparison would miss it.
        """

        db_dir = os.path.join(self.world_path, "db")
        digest = {}
        for name in sorted(os.listdir(db_dir)):
            full = os.path.join(db_dir, name)
            if os.path.isfile(full):
                with open(full, "rb") as handle:
                    digest[name] = hashlib.sha256(handle.read()).hexdigest()
        return digest

    def _loaded_player(self, service):
        from mcbe_editor.players import encode_player_key
        from mcbe_editor.world import LOCAL_PLAYER_KEY

        encoded_key = encode_player_key(LOCAL_PLAYER_KEY)
        loaded = service.load_player(self.world_path, encoded_key)
        self.assertTrue(loaded["success"])
        return encoded_key, loaded

    def _service_with_write_tripwire(self):
        """Service whose mutating adapter fails loudly if phase 1 ever opens it.

        A write gate can mask the effect by refusing the open before any file is
        touched, so comparing file digests alone is not enough to prove that the
        mutating adapter was never reached.
        """

        from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
        from mcbe_editor.leveldb_readonly import ReadonlyLevelDbAdapter as RealReadonlyAdapter
        from mcbe_editor.services import BedrockEditorService

        opened = []

        def tripwire(db_path):
            opened.append(db_path)
            raise AssertionError("Der mutierende LevelDB-Adapter darf hier nicht geöffnet werden.")

        # Pass the real readonly factory explicitly: conftest mirrors an injected
        # db_factory onto readonly_db_factory unless one is given.
        service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=tripwire, readonly_db_factory=RealReadonlyAdapter)
        return service, opened

    def test_no_op_save_leaves_the_world_byte_identical(self):
        """A save that produces identical bytes must not open the mutating adapter.

        The engine replays the write-ahead log and rewrites CURRENT/MANIFEST on
        every open, so phase 1 has to run on the readonly reader.  The payload
        mirrors what buildSavePayload() sends when nothing was touched: only
        changed sections are included, so inventory/effects/abilities stay None.
        """

        service, opened_for_write = self._service_with_write_tripwire()
        encoded_key, loaded = self._loaded_player(service)
        before = self._db_content_digest()

        result = service.save_player(
            self.world_path,
            encoded_key,
            None,
            {},
            base_revision=loaded.get("player_revision"),
        )

        self.assertTrue(result["no_op"], result.get("message"))
        self.assertIsNone(result["backup_file"])
        self.assertEqual(opened_for_write, [], "Ein No-op-Save darf den mutierenden Adapter nicht öffnen")
        self.assertEqual(self._db_content_digest(), before, "Ein No-op-Save darf keine Weltdatei anfassen")

    def test_rejected_save_leaves_the_world_byte_identical(self):
        """Validation runs before any write handle exists, so rejections are inert."""

        service, opened_for_write = self._service_with_write_tripwire()
        encoded_key, _loaded = self._loaded_player(service)
        before = self._db_content_digest()

        with self.assertRaises(ValueError):
            service.save_player(self.world_path, encoded_key, None, {}, base_revision="0" * 64)

        self.assertEqual(opened_for_write, [], "Ein abgelehnter Save darf den mutierenden Adapter nicht öffnen")
        self.assertEqual(self._db_content_digest(), before, "Ein abgelehnter Save darf keine Weltdatei anfassen")

    def test_final_write_guard_rejection_never_opens_the_mutating_adapter(self):
        """A guard rejection after backup creation must still leave the DB untouched."""

        service, opened_for_write = self._service_with_write_tripwire()
        encoded_key, loaded = self._loaded_player(service)
        before = self._db_content_digest()
        guard_calls = []

        def reject_write():
            guard_calls.append("check")
            raise ValueError("finaler Write-Guard blockiert")

        with self.assertRaisesRegex(ValueError, "finaler Write-Guard"):
            service.save_player(
                self.world_path,
                encoded_key,
                [
                    {
                        "slot": 0,
                        "name": "minecraft:stone",
                        "count": 1,
                        "damage": 0,
                        "display_name": "",
                        "lore": [],
                        "enchantments": [],
                    }
                ],
                {},
                base_revision=loaded.get("player_revision"),
                pre_write_check=reject_write,
            )

        self.assertEqual(guard_calls, ["check"])
        self.assertEqual(opened_for_write, [], "Ein blockierter Save darf den mutierenden Adapter nicht öffnen")
        self.assertEqual(self._db_content_digest(), before, "Ein blockierter Save darf keine Weltdatei anfassen")


if __name__ == "__main__":
    unittest.main()
