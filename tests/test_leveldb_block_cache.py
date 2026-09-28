"""Bounded writer block caching, including native recovery and invalidation."""

import random
import shutil
import struct
import zlib
from collections import OrderedDict

import pytest

from mcbe_editor import leveldb_readonly as reader
from mcbe_editor.leveldb_writer import LevelDbWriter


def test_cache_evicts_by_recent_use_and_accounts_for_replacements():
    cache = reader._BlockCache(8)
    keys = [(object(), 0, 4) for _ in range(3)]
    cache.put(keys[0], b"aaaa")
    cache.put(keys[1], b"bbbb")
    assert cache.get(keys[0]) == b"aaaa"
    cache.put(keys[2], b"cccc")
    assert cache.get(keys[1]) is None
    assert cache.get(keys[0]) == b"aaaa"
    assert cache.get(keys[2]) == b"cccc"
    cache.put(keys[0], b"longer")
    assert cache.get(keys[2]) is None
    cache.put(keys[0], b"a")
    cache.put(keys[1], b"bbbbbbb")
    assert cache.get(keys[0]) == b"a"
    assert cache.get(keys[1]) == b"bbbbbbb"
    cache.clear()
    assert all(cache.get(key) is None for key in keys)
    assert cache._size == 0


@pytest.mark.parametrize("value", [b"", b"x"])
def test_cache_bounds_the_number_of_tiny_entries(value):
    cache = reader._BlockCache(1024, max_entries=2)
    keys = [(object(), 0, len(value)) for _ in range(3)]
    for key in keys:
        cache.put(key, value)
    assert cache.get(keys[0]) is None
    assert cache.get(keys[1]) == value
    assert cache.get(keys[2]) == value


def test_oversized_blocks_do_not_flush_useful_entries():
    cache = reader._BlockCache(4)
    small, large = (object(), 0, 4), (object(), 0, 5)
    cache.put(small, b"keep")
    cache.put(large, b"large")
    assert cache.get(small) == b"keep"
    assert cache.get(large) is None


def _block(data, compression=0):
    payload = zlib.compress(data) if compression == 2 else data
    payload += bytes((compression,))
    return payload + struct.pack("<I", reader._mask_crc32c(reader._crc32c(payload)))


@pytest.mark.parametrize("compression", [0, 2])
def test_cached_block_is_read_and_validated_once(tmp_path, monkeypatch, compression):
    data = b"validated block" * 100
    raw = _block(data, compression)
    path = tmp_path / "000003.ldb"
    path.write_bytes(raw)
    cache = reader._BlockCache(len(data))
    table = reader._Table(str(path), block_cache=cache)
    try:
        assert table._read_block(0, len(raw) - 5) == data

        def unexpected_read(*_args):
            raise AssertionError("cached block was read again")

        monkeypatch.setattr(table, "_read_at", unexpected_read)
        assert table._read_block(0, len(raw) - 5) == data
        cache.clear()
        with pytest.raises(AssertionError, match="read again"):
            table._read_block(0, len(raw) - 5)
    finally:
        table.close()


def test_same_filename_and_offsets_in_different_tables_do_not_alias(tmp_path):
    cache = reader._BlockCache(128)
    tables = []
    try:
        for name, data in (("world-a", b"aaaa"), ("world-b", b"bbbb")):
            directory = tmp_path / name
            directory.mkdir()
            path = directory / "000003.ldb"
            path.write_bytes(_block(data))
            tables.append(reader._Table(str(path), block_cache=cache))
        for _ in range(2):
            assert tables[0]._read_block(0, 4) == b"aaaa"
            assert tables[1]._read_block(0, 4) == b"bbbb"
    finally:
        for table in tables:
            table.close()


def test_budget_counts_decompressed_bytes_and_is_shared_between_tables(tmp_path):
    cache = reader._BlockCache(10)
    raw = _block(b"a" * 6, 2)
    path = tmp_path / "000003.ldb"
    path.write_bytes(raw)
    tables = [reader._Table(str(path), block_cache=cache) for _ in range(2)]
    try:
        for table in tables:
            assert table._read_block(0, len(raw) - 5) == b"a" * 6
        assert cache._size == 6
        assert len(cache._entries) == 1
        assert cache.get((tables[0]._cache_identity, 0, len(raw) - 5)) is None
    finally:
        for table in tables:
            table.close()


def test_compressed_block_expanding_beyond_cache_budget_is_not_retained(tmp_path, monkeypatch):
    data = b"x" * 1000
    raw = _block(data, 2)
    assert len(raw) < 100 < len(data)
    path = tmp_path / "000003.ldb"
    path.write_bytes(raw)
    cache = reader._BlockCache(100)
    table = reader._Table(str(path), block_cache=cache)
    reads = []
    original = table._read_at

    def read_at(offset, size):
        reads.append(offset)
        return original(offset, size)

    monkeypatch.setattr(table, "_read_at", read_at)
    try:
        for _ in range(2):
            assert table._read_block(0, len(raw) - 5) == data
        assert reads == [0, 0]
        assert cache._size == 0
        assert not cache._entries
    finally:
        table.close()


@pytest.mark.parametrize("damage", ["checksum", "compression"])
def test_invalid_blocks_are_never_cached(tmp_path, damage):
    raw = bytearray(_block(b"not a zlib stream", 2 if damage == "checksum" else 0))
    if damage == "checksum":
        raw[-1] ^= 1
    else:
        raw[-5] = 2
        raw[-4:] = struct.pack("<I", reader._mask_crc32c(reader._crc32c(raw[:-4])))
    path = tmp_path / "000003.ldb"
    path.write_bytes(raw)
    cache = reader._BlockCache(1024)
    table = reader._Table(str(path), block_cache=cache)
    try:
        for _ in range(2):
            with pytest.raises(reader.CorruptDatabaseError):
                table._read_block(0, len(raw) - 5)
        assert not cache._entries
    finally:
        table.close()


def test_cache_allocation_failure_does_not_fail_a_valid_read(tmp_path):
    class ExhaustedEntries(OrderedDict):
        def __setitem__(self, _key, _value):
            raise MemoryError("simulated cache allocation failure")

    path = tmp_path / "000003.ldb"
    path.write_bytes(_block(b"value"))
    cache = reader._BlockCache(1024)
    old_key = (object(), 0, 3)
    cache.put(old_key, b"old")
    cache._entries = ExhaustedEntries()
    OrderedDict.__setitem__(cache._entries, old_key, b"old")
    table = reader._Table(str(path), block_cache=cache)
    try:
        assert table._read_block(0, 5) == b"value"
        assert cache._size == 0
        assert not cache._entries
    finally:
        table.close()


@pytest.fixture
def native_database(tmp_path):
    native = pytest.importorskip("leveldb")
    path = tmp_path / "db"
    rng = random.Random(27)
    values = {f"key-{i:05}".encode(): rng.randbytes(64) * 16 for i in range(2000)}
    db = native.LevelDB(str(path), True)
    try:
        db.putBatch(values)
    finally:
        db.close(compact=True)
    assert list(path.glob("*.ldb"))
    return path, values, native


def test_writer_cache_preserves_batch_versions_deletions_and_native_recovery(native_database, monkeypatch):
    path, expected, native = native_database
    writer = LevelDbWriter(str(path))
    cache = writer._block_cache
    try:
        keys = list(expected)[:100]
        for key in keys:
            assert writer.get(key) == expected[key]
        assert cache._entries

        def unexpected_read(*_args):
            raise AssertionError("warmed batch reread its data blocks")

        with monkeypatch.context() as patcher:
            patcher.setattr(reader._Table, "_read_at", unexpected_read)
            batch = {key: None if i % 3 == 0 else b"new" for i, key in enumerate(keys)}
            writer.put_batch(batch)
            # A later version must win over both cached table bytes and a deletion.
            writer.put(keys[0], b"latest")
        for key, value in batch.items():
            if value is None:
                expected.pop(key)
            else:
                expected[key] = value
        expected[keys[0]] = b"latest"
        assert dict(writer.iter_items()) == expected
    finally:
        writer.close()
    assert not cache._entries
    assert cache._size == 0
    with pytest.raises(RuntimeError, match="geschlossen"):
        writer.get(keys[0])
    db = native.LevelDB(str(path))
    try:
        assert dict(db.items()) == expected
    finally:
        db.close()


def test_reopening_after_native_changes_cannot_reuse_old_blocks(native_database):
    path, values, native = native_database
    key = next(iter(values))
    first = LevelDbWriter(str(path))
    first_cache = first._block_cache
    try:
        assert first.get(key) == values[key]
    finally:
        first.close()
    db = native.LevelDB(str(path))
    try:
        db.put(key, b"native replacement")
    finally:
        db.close(compact=True)
    second = LevelDbWriter(str(path))
    try:
        assert second._block_cache is not first_cache
        assert second.get(key) == b"native replacement"
    finally:
        second.close()


def test_readonly_sessions_do_not_keep_blocks(native_database, monkeypatch):
    path, values, _native = native_database
    db = reader.ReadonlyLevelDbAdapter(str(path))
    try:
        key = next(iter(values))
        assert db.get(key) == values[key]
        assert db._block_cache is None
        reads = []
        original = reader._Table._read_at

        def read_at(self, offset, size):
            reads.append((offset, size))
            return original(self, offset, size)

        monkeypatch.setattr(reader._Table, "_read_at", read_at)
        for _ in range(2):
            assert db.get(key) == values[key]
        assert len(reads) == 2
    finally:
        db.close()


def test_concurrent_world_sessions_have_independent_caches(native_database, tmp_path):
    path, values, native = native_database
    other_path = tmp_path / "other-db"
    shutil.copytree(path, other_path)
    key = next(iter(values))
    db = native.LevelDB(str(other_path))
    try:
        db.put(key, b"other world")
    finally:
        db.close(compact=True)
    first, second = LevelDbWriter(str(path)), LevelDbWriter(str(other_path))
    try:
        assert first._block_cache is not second._block_cache
        assert first.get(key) == values[key]
        assert second.get(key) == b"other world"
        assert first.get(key) == values[key]
    finally:
        first.close()
        second.close()
