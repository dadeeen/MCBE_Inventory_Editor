"""Synthetic on-disk fixtures; no native LevelDB or private worlds required."""
from __future__ import annotations

import builtins
import hashlib
import os
import shutil
import struct
import zlib

import pytest

from mcbe_editor import leveldb_readonly
from mcbe_editor.leveldb_readonly import CorruptDatabaseError, ReadonlyLevelDbAdapter, _TABLE_MAGIC
from tests.test_leveldb_readonly import _crc32c, _length_prefixed, _log_record, _mask_crc32c, _varint, _write_batch


def _snapshot(root):
    return {p.name: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in root.iterdir()}


def _world_db(tmp_path, manifest=b"", wal=None):
    root = tmp_path / "db"
    root.mkdir()
    (root / "CURRENT").write_bytes(b"MANIFEST-000001\n")
    (root / "MANIFEST-000001").write_bytes(_log_record(b"\x02\x02" + manifest))
    if wal is not None:
        (root / "000002.log").write_bytes(_log_record(wal))
    return root


@pytest.mark.parametrize("bad_case", ["zero_count", "short_count", "long_count", "trailing_zero", "trailing_put"])
def test_wal_batch_must_match_its_declared_count(tmp_path, bad_case):
    batch = _write_batch(7, [(b"player", b"new"), (b"other", b"value")])
    if bad_case in {"zero_count", "short_count", "long_count"}:
        count = {"zero_count": 0, "short_count": 1, "long_count": 3}[bad_case]
        batch = batch[:8] + struct.pack("<I", count) + batch[12:]
    else:
        batch += b"\x00" if bad_case == "trailing_zero" else b"\x01\x03key\x03val"
    root = _world_db(tmp_path, wal=batch)
    before = _snapshot(root)
    with pytest.raises(CorruptDatabaseError):
        ReadonlyLevelDbAdapter(str(root))
    assert _snapshot(root) == before


@pytest.mark.parametrize("entries", [[], [(b"", b"")], [(b"a", b"1"), (b"a", b"2"), (b"z", b"3")]])
def test_valid_wal_batches_remain_readonly_and_keep_latest_values(tmp_path, entries):
    root = _world_db(tmp_path, wal=_write_batch(1, entries))
    before = _snapshot(root)
    reader = ReadonlyLevelDbAdapter(str(root))
    try:
        assert dict(reader.iter_items()) == dict(entries)
        for key, expected in dict(entries).items():
            assert reader.get(key) == expected
    finally:
        reader.close()
    assert _snapshot(root) == before


def _key(user_key, sequence, entry_type=1):
    return user_key + struct.pack("<Q", (sequence << 8) | entry_type)


def _block(entries):
    body = bytearray()
    restarts = []
    previous = b""
    for i, (key, value) in enumerate(entries):
        shared = 0
        if i % 2:
            while shared < min(len(key), len(previous)) and key[shared] == previous[shared]:
                shared += 1
        else:
            restarts.append(len(body))
        body += _varint(shared) + _varint(len(key) - shared) + _varint(len(value)) + key[shared:] + value
        previous = key
    restarts = restarts or [0]
    return bytes(body) + b"".join(struct.pack("<I", p) for p in restarts) + struct.pack("<I", len(restarts))


def _table(blocks, compression):
    data = bytearray()

    def append_block(raw):
        encoded = raw if compression == 0 else (zlib.compress(raw) if compression == 2 else zlib.compress(raw, wbits=-15))
        handle = _varint(len(data)) + _varint(len(encoded))
        trailer = bytes([compression])
        data.extend(encoded + trailer + struct.pack("<I", _mask_crc32c(_crc32c(encoded + trailer))))
        return handle

    index = [(entries[-1][0], append_block(_block(entries))) for entries in blocks]
    meta_handle = append_block(_block([]))
    index_handle = append_block(_block(index))
    return bytes(data) + (meta_handle + index_handle).ljust(40, b"\0") + struct.pack("<Q", _TABLE_MAGIC)


def _new_file(level, number, data, first, last):
    return (b"\x07" + _varint(level) + _varint(number) + _varint(len(data))
            + _length_prefixed(first) + _length_prefixed(last))


@pytest.mark.parametrize("compression", [0, 2, 4])
@pytest.mark.parametrize("suffix", ["ldb", "sst"])
def test_synthetic_tables_merge_with_wal_versions_and_tombstones(tmp_path, compression, suffix):
    old_entries = [(_key(b"apple", 1), b"old"), (_key(b"apricot", 2), b"fruit"), (_key(b"zebra", 3), b"stripe")]
    new_blocks = [[(_key(b"apple", 5, 0), b""), (_key(b"apple", 4), b"obsolete")],
                  [(_key(b"banana", 6), b"yellow"), (_key(b"berry", 7), b"red")]]
    old = _table([old_entries], compression)
    new = _table(new_blocks, compression)
    manifest = (_new_file(1, 3, old, old_entries[0][0], old_entries[-1][0])
                + _new_file(0, 4, new, new_blocks[0][0][0], new_blocks[-1][-1][0]))
    # A deletion and an overwrite in the WAL must dominate the table records.
    wal = struct.pack("<QI", 8, 2) + b"\x00" + _length_prefixed(b"banana")
    wal += b"\x01" + _length_prefixed(b"berry") + _length_prefixed(b"new red")
    root = _world_db(tmp_path, manifest=manifest, wal=wal)
    (root / f"000003.{suffix}").write_bytes(old)
    (root / f"000004.{suffix}").write_bytes(new)
    before = _snapshot(root)
    reader = ReadonlyLevelDbAdapter(str(root))
    try:
        expected = {b"apricot": b"fruit", b"berry": b"new red", b"zebra": b"stripe"}
        assert dict(reader.iter_items()) == expected
        for key, value in expected.items():
            assert reader.get(key) == value
        for key in (b"apple", b"banana", b"absent"):
            with pytest.raises(KeyError):
                reader.get(key)
    finally:
        reader.close()
    assert _snapshot(root) == before


@pytest.mark.parametrize("older_type,newer_type", [(1, 1), (0, 1), (1, 0)])
@pytest.mark.parametrize("reverse_manifest_order", [False, True])
def test_deeper_level_versions_follow_sequence_not_manifest_order(tmp_path, older_type, newer_type, reverse_manifest_order):
    old_key = _key(b"player", 5, older_type)
    new_key = _key(b"player", 9, newer_type)
    old = _table([[(old_key, b"old" if older_type else b"")]], 0)
    new = _table([[(new_key, b"new" if newer_type else b"")]], 0)
    files = [_new_file(1, 3, old, old_key, old_key), _new_file(1, 4, new, new_key, new_key)]
    if reverse_manifest_order:
        files.reverse()
    metadata = b"\x01" + _length_prefixed(b"leveldb.BytewiseComparator") + b"\x03\x05\x04\x09"
    root = _world_db(tmp_path, manifest=metadata + b"".join(files))
    (root / "000003.ldb").write_bytes(old)
    (root / "000004.ldb").write_bytes(new)
    before = _snapshot(root)
    expected = {b"player": b"new"} if newer_type else {}
    reader = ReadonlyLevelDbAdapter(str(root))
    try:
        assert dict(reader.iter_items()) == expected
        if newer_type:
            assert reader.get(b"player") == expected[b"player"]
        else:
            with pytest.raises(KeyError):
                reader.get(b"player")
    finally:
        reader.close()
    assert _snapshot(root) == before

    # The internal ranges are valid even though their user-key boundaries touch.
    # Compare on a copy because opening the native engine rewrites metadata.
    leveldb = pytest.importorskip("leveldb")
    native_path = tmp_path / "native-copy"
    shutil.copytree(root, native_path)
    native = leveldb.LevelDB(str(native_path))
    try:
        assert dict(native.items()) == expected
        if newer_type:
            assert native.get(b"player") == expected[b"player"]
        else:
            with pytest.raises(KeyError):
                native.get(b"player")
    finally:
        native.close()


def _many_table_world(tmp_path, *, level_tables=24, with_level0=True):
    """Level 1 holds disjoint key ranges; level 0 and the WAL hold newer versions."""

    expected = {}
    tables = []
    for index in range(level_tables):
        entries = []
        for offset in range(10):
            number = index * 10 + offset
            entries.append((_key(b"k%04d" % number, 1 + number), b"v1-%d" % number))
            expected[b"k%04d" % number] = b"v1-%d" % number
        tables.append((1, entries))
    deleted = []
    if with_level0:
        tables.append((0, [(_key(b"k0005", 1000), b"level0-a"), (_key(b"k0105", 1001), b"level0-a")]))
        tables.append((0, [(_key(b"k0015", 1003), b"level0-b"), (_key(b"k0200", 1002, 0), b"")]))
        expected.update({b"k0005": b"level0-a", b"k0105": b"level0-a", b"k0015": b"level0-b"})
        del expected[b"k0200"]
        deleted.append(b"k0200")
    # The WAL overwrites and deletes the last two keys of the level.
    overwritten, removed = b"k%04d" % (level_tables * 10 - 2), b"k%04d" % (level_tables * 10 - 1)
    wal = struct.pack("<QI", 2000, 2) + b"\x01" + _length_prefixed(overwritten) + _length_prefixed(b"wal")
    wal += b"\x00" + _length_prefixed(removed)
    expected[overwritten] = b"wal"
    del expected[removed]
    deleted.append(removed)
    encoded = [(level, number, _table([entries], 2), entries) for number, (level, entries) in enumerate(tables, start=3)]
    # MANIFEST order must not decide the reading order of a level.
    manifest = b"".join(_new_file(level, number, data, entries[0][0], entries[-1][0]) for level, number, data, entries in reversed(encoded))
    root = _world_db(tmp_path, manifest=manifest, wal=wal)
    for _level, number, data, _entries in encoded:
        (root / f"{number:06d}.ldb").write_bytes(data)
    return root, expected, deleted


def _track_table_files(monkeypatch):
    opened = []

    def tracking_open(path, *args, **kwargs):
        # The reader owns and closes the handle; the test only observes it.
        handle = builtins.open(path, *args, **kwargs)  # noqa: SIM115
        if str(path).endswith((".ldb", ".sst")):
            opened.append(handle)
        return handle

    monkeypatch.setattr(leveldb_readonly, "open", tracking_open, raising=False)
    return lambda: sum(not handle.closed for handle in opened), opened


@pytest.mark.parametrize("access", ["scan", "get"])
def test_many_tables_are_read_with_a_bounded_number_of_open_files(tmp_path, monkeypatch, access):
    root, expected, deleted = _many_table_world(tmp_path)
    before = _snapshot(root)
    monkeypatch.setattr(leveldb_readonly, "_MAX_OPEN_TABLES", 4)
    open_now, opened = _track_table_files(monkeypatch)
    peak = 0
    reader = ReadonlyLevelDbAdapter(str(root))
    try:
        if access == "scan":
            items = {}
            for key, value in reader.iter_items():
                items[key] = value
                peak = max(peak, open_now())
            assert items == expected
        else:
            # Alternate between both ends so tables are evicted and reopened.
            keys = sorted(expected)
            for key in [key for pair in zip(keys, reversed(keys), strict=True) for key in pair]:
                assert reader.get(key) == expected[key]
                peak = max(peak, open_now())
            for key in deleted:
                with pytest.raises(KeyError):
                    reader.get(key)
    finally:
        reader.close()
    # 26 tables, never more than four open at once, and none left open.
    assert 0 < peak <= 4
    assert opened and all(handle.closed for handle in opened)
    assert _snapshot(root) == before


@pytest.mark.parametrize("change", ["replaced", "deleted"])
def test_a_table_that_changes_while_reading_is_refused(tmp_path, monkeypatch, change):
    root, expected, _deleted = _many_table_world(tmp_path, level_tables=2, with_level0=False)
    monkeypatch.setattr(leveldb_readonly, "_MAX_OPEN_TABLES", 1)
    reader = ReadonlyLevelDbAdapter(str(root))
    try:
        assert reader.get(b"k0000") == expected[b"k0000"]
        # Reading the second table closes the first one.
        assert reader.get(b"k0010") == expected[b"k0010"]
        if change == "replaced":
            replacement = root / "replacement.tmp"
            replacement.write_bytes(_table([[(_key(b"k0000", 1), b"another value")]], 0))
            os.replace(replacement, root / "000003.ldb")
        else:
            os.remove(root / "000003.ldb")
        with pytest.raises(CorruptDatabaseError, match="ersetzt" if change == "replaced" else "verschwunden"):
            reader.get(b"k0001")
    finally:
        reader.close()


@pytest.mark.parametrize("layout", ["next_block", "next_table"])
def test_a_scan_left_running_opens_no_table_after_close(tmp_path, monkeypatch, layout):
    entries = [(_key(b"k%d" % number, 1 + number), b"v%d" % number) for number in range(4)]
    tables = [[entries[:2], entries[2:]]] if layout == "next_block" else [[entries[:2]], [entries[2:]]]
    encoded = [(number, _table(blocks, 0), blocks) for number, blocks in enumerate(tables, start=3)]
    manifest = b"".join(_new_file(1, number, data, blocks[0][0][0], blocks[-1][-1][0]) for number, data, blocks in encoded)
    root = _world_db(tmp_path, manifest=manifest)
    for number, data, _blocks in encoded:
        (root / f"{number:06d}.ldb").write_bytes(data)
    open_now, opened = _track_table_files(monkeypatch)
    reader = ReadonlyLevelDbAdapter(str(root))
    items = reader.iter_items()
    assert next(items) == (b"k0", b"v0")
    reader.close()
    opened_at_close = len(opened)
    # The rest of the scan needs another block or table; neither may be opened.
    with pytest.raises(RuntimeError, match="geschlossen"):
        list(items)
    assert len(opened) == opened_at_close
    assert open_now() == 0


def test_overlapping_deeper_level_is_merged_table_by_table(tmp_path):
    # Level 1 must not overlap; if a MANIFEST says otherwise, reading its
    # tables one after another would miss that b@5 in the WAL is newest.
    first = [(_key(b"a", 1), b"a1"), (_key(b"c", 3), b"c3")]
    second = [(_key(b"b", 2), b"b2"), (_key(b"d", 4), b"d4")]
    first_table, second_table = _table([first], 0), _table([second], 0)
    manifest = _new_file(1, 3, first_table, first[0][0], first[-1][0]) + _new_file(1, 4, second_table, second[0][0], second[-1][0])
    wal = struct.pack("<QI", 5, 1) + b"\x01" + _length_prefixed(b"b") + _length_prefixed(b"b5")
    root = _world_db(tmp_path, manifest=manifest, wal=wal)
    (root / "000003.ldb").write_bytes(first_table)
    (root / "000004.ldb").write_bytes(second_table)
    reader = ReadonlyLevelDbAdapter(str(root))
    try:
        assert reader._disjoint_level_order(1) is None
        assert dict(reader.iter_items()) == {b"a": b"a1", b"b": b"b5", b"c": b"c3", b"d": b"d4"}
    finally:
        reader.close()
