"""Synthetic on-disk fixtures; no native LevelDB or private worlds required."""
from __future__ import annotations

import hashlib
import os
import shutil
import struct
import zlib

import pytest

from mcbe_editor import leveldb_readonly
from mcbe_editor.leveldb_readonly import CorruptDatabaseError, ReadonlyLevelDbAdapter, WorldChangedWhileReadingError, _TABLE_MAGIC
from mcbe_editor.leveldb_writer import LevelDbWriter
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


def _many_table_world(tmp_path, *, level_tables=24, with_level0=True, writable=False):
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
    if writable:
        # A writer continues after the next file number and last sequence.
        manifest = b"\x03" + _varint(100) + b"\x04" + _varint(5000) + manifest
    root = _world_db(tmp_path, manifest=manifest, wal=wal)
    for _level, number, data, _entries in encoded:
        (root / f"{number:06d}.ldb").write_bytes(data)
    return root, expected, deleted


def _track_table_files(monkeypatch):
    opened = []
    open_for_reading = leveldb_readonly._open_for_reading

    def tracking_open(path, **kwargs):
        # The reader owns and closes the handle; the test only observes it.
        handle = open_for_reading(path, **kwargs)
        if str(path).endswith((".ldb", ".sst")):
            opened.append(handle)
        return handle

    monkeypatch.setattr(leveldb_readonly, "_open_for_reading", tracking_open)
    return lambda: sum(not handle.closed for handle in opened), opened


@pytest.mark.parametrize("access", ["scan", "get"])
def test_many_tables_are_read_with_a_bounded_number_of_open_files(tmp_path, monkeypatch, access):
    root, expected, deleted = _many_table_world(tmp_path)
    before = _snapshot(root)
    monkeypatch.setattr(leveldb_readonly, "_MAX_HELD_TABLES", 0)
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
    monkeypatch.setattr(leveldb_readonly, "_MAX_HELD_TABLES", 0)
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
        with pytest.raises(WorldChangedWhileReadingError):
            reader.get(b"k0001")
    finally:
        reader.close()


def test_a_server_compacting_during_a_scan_cannot_take_tables_away(tmp_path, monkeypatch):
    root, expected, deleted = _many_table_world(tmp_path)
    open_now, _opened = _track_table_files(monkeypatch)
    reader = ReadonlyLevelDbAdapter(str(root))
    try:
        # All 26 tables are open before the first read, as the server's
        # compaction may delete any of them from now on.
        assert open_now() == 26
        # The server deletes them at once, on Windows too; the open handles
        # still read what the reader started with.
        for table in root.glob("*.ldb"):
            os.remove(table)
        # A new MANIFEST generation replaces CURRENT the same way.
        (root / "CURRENT.tmp").write_bytes(b"MANIFEST-000009\n")
        os.replace(root / "CURRENT.tmp", root / "CURRENT")
        assert dict(reader.iter_items()) == expected
        for key in deleted:
            with pytest.raises(KeyError):
                reader.get(key)
    finally:
        reader.close()
    assert open_now() == 0
    assert not list(root.glob("*.ldb"))


@pytest.mark.parametrize("state", ["after_compaction", "damaged", "unreadable"])
def test_a_missing_table_is_a_change_only_after_the_manifest_changed(tmp_path, monkeypatch, state):
    root, expected, _deleted = _many_table_world(tmp_path)
    # Tables that are not held open on demand.
    monkeypatch.setattr(leveldb_readonly, "_MAX_HELD_TABLES", 0)
    monkeypatch.setattr(leveldb_readonly, "_MAX_OPEN_TABLES", 4)
    reader = ReadonlyLevelDbAdapter(str(root))
    try:
        os.remove(root / "000013.ldb")
        if state == "after_compaction":
            # LevelDB records a compaction in the MANIFEST before it deletes
            # the tables it replaced.
            with (root / "MANIFEST-000001").open("ab") as manifest:
                manifest.write(b"\0" * 16)
            with pytest.raises(WorldChangedWhileReadingError):
                reader.get(b"k0100")
        elif state == "damaged":
            with pytest.raises(CorruptDatabaseError, match="000013 fehlt") as raised:
                reader.get(b"k0100")
            assert not isinstance(raised.value, WorldChangedWhileReadingError)
        else:
            open_for_reading = leveldb_readonly._open_for_reading

            def refuse_current(path, **kwargs):
                if os.path.basename(path) == "CURRENT":
                    raise PermissionError(13, "Permission denied", path)
                return open_for_reading(path, **kwargs)

            # Missing permissions stay visible instead of passing as a change.
            monkeypatch.setattr(leveldb_readonly, "_open_for_reading", refuse_current)
            with pytest.raises(PermissionError):
                reader.get(b"k0100")
    finally:
        reader.close()


def test_a_reader_that_fails_to_open_closes_its_tables(tmp_path, monkeypatch):
    root, _expected, _deleted = _many_table_world(tmp_path)
    budget = leveldb_readonly._HeldTableBudget(26)
    monkeypatch.setattr(leveldb_readonly, "_HELD_TABLES", budget)
    open_now, opened = _track_table_files(monkeypatch)

    def broken_log(*_args, **_kwargs):
        raise CorruptDatabaseError("broken log")

    # The log is replayed after the tables are open; a failure there must not
    # leave them open.
    monkeypatch.setattr(leveldb_readonly, "_replay_wal", broken_log)
    with pytest.raises(CorruptDatabaseError, match="broken log"):
        ReadonlyLevelDbAdapter(str(root))
    assert len(opened) == 26 and open_now() == 0
    # The held tables went back to the budget.
    assert budget.reserve(26)


def test_readers_of_different_worlds_share_one_budget_of_held_tables(tmp_path, monkeypatch):
    worlds = []
    for name in ("first", "second"):
        (tmp_path / name).mkdir()
        worlds.append(_many_table_world(tmp_path / name))
    budget = leveldb_readonly._HeldTableBudget(40)
    monkeypatch.setattr(leveldb_readonly, "_HELD_TABLES", budget)
    open_now, _opened = _track_table_files(monkeypatch)
    first = ReadonlyLevelDbAdapter(str(worlds[0][0]))
    try:
        assert open_now() == 26
        # 14 tables are left: the second world opens its 26 on demand.
        second = ReadonlyLevelDbAdapter(str(worlds[1][0]))
        try:
            assert open_now() == 26
            assert dict(second.iter_items()) == worlds[1][1]
        finally:
            second.close()
        assert dict(first.iter_items()) == worlds[0][1]
    finally:
        first.close()
    assert open_now() == 0
    # Closing gave the tables back, so the next reader holds its world again.
    again = ReadonlyLevelDbAdapter(str(worlds[1][0]))
    try:
        assert open_now() == 26
    finally:
        again.close()
    assert budget.reserve(40)


def test_a_writer_opens_tables_on_demand(tmp_path, monkeypatch):
    root, expected, _deleted = _many_table_world(tmp_path, writable=True)
    budget = leveldb_readonly._HeldTableBudget(26)
    monkeypatch.setattr(leveldb_readonly, "_HELD_TABLES", budget)
    open_now, _opened = _track_table_files(monkeypatch)
    writer = LevelDbWriter(str(root))
    try:
        # Its exclusive access keeps servers out; it holds nothing up front.
        assert open_now() == 0
        assert writer.get(b"k0000") == expected[b"k0000"]
    finally:
        writer.close()
    assert open_now() == 0
    assert budget.reserve(26)


def _flushing_world(tmp_path):
    """A table holds a and b; log 2 holds a newer a that a server will flush."""

    old = [(_key(b"a", 1), b"old a"), (_key(b"b", 2), b"old b")]
    old_table = _table([old], 0)
    root = _world_db(tmp_path, manifest=_new_file(1, 3, old_table, old[0][0], old[-1][0]),
                     wal=_write_batch(10, [(b"a", b"new a")]))
    (root / "000003.ldb").write_bytes(old_table)
    return root


def _flush(root):
    """Do what a running server does when it flushes log 2 into table 4."""

    flushed = [(_key(b"a", 10), b"new a")]
    flushed_table = _table([flushed], 0)
    (root / "000005.log").write_bytes(_log_record(_write_batch(11, [(b"b", b"new b")])))
    (root / "000004.ldb").write_bytes(flushed_table)
    # The MANIFEST records the table and the next log before log 2 goes away.
    with (root / "MANIFEST-000001").open("ab") as manifest:
        manifest.write(_log_record(b"\x02\x05" + _new_file(0, 4, flushed_table, flushed[0][0], flushed[0][0])))
    os.remove(root / "000002.log")


@pytest.mark.parametrize("moment", ["before_the_logs_are_listed", "before_the_log_is_read"])
def test_a_flush_while_opening_is_a_change_not_a_mixed_state(tmp_path, monkeypatch, moment):
    root = _flushing_world(tmp_path)
    if moment == "before_the_logs_are_listed":
        replay_logs = ReadonlyLevelDbAdapter._replay_logs

        def flush_first(self, db_path):
            _flush(root)
            replay_logs(self, db_path)

        monkeypatch.setattr(ReadonlyLevelDbAdapter, "_replay_logs", flush_first)
    else:
        read_metadata = ReadonlyLevelDbAdapter._read_metadata

        def flush_before_the_log(self, path):
            if path.endswith("000002.log"):
                _flush(root)
            return read_metadata(self, path)

        monkeypatch.setattr(ReadonlyLevelDbAdapter, "_read_metadata", flush_before_the_log)
    # The old MANIFEST without log 2 would give the old a with the new b, a
    # state the world never had.
    with pytest.raises(WorldChangedWhileReadingError):
        ReadonlyLevelDbAdapter(str(root))
    monkeypatch.undo()
    reader = ReadonlyLevelDbAdapter(str(root))
    try:
        assert dict(reader.iter_items()) == {b"a": b"new a", b"b": b"new b"}
    finally:
        reader.close()


def test_a_new_manifest_while_opening_is_a_change(tmp_path, monkeypatch):
    root = _flushing_world(tmp_path)
    read_metadata = ReadonlyLevelDbAdapter._read_metadata

    def reopened_by_the_server(self, path):
        if path.endswith("MANIFEST-000001"):
            # Opening a world writes a new MANIFEST, points CURRENT to it and
            # deletes the old one.
            shutil.copyfile(root / "MANIFEST-000001", root / "MANIFEST-000006")
            (root / "CURRENT.tmp").write_bytes(b"MANIFEST-000006\n")
            os.replace(root / "CURRENT.tmp", root / "CURRENT")
            os.remove(root / "MANIFEST-000001")
        return read_metadata(self, path)

    monkeypatch.setattr(ReadonlyLevelDbAdapter, "_read_metadata", reopened_by_the_server)
    with pytest.raises(WorldChangedWhileReadingError):
        ReadonlyLevelDbAdapter(str(root))


@pytest.mark.parametrize("missing", ["MANIFEST-000001", "000002.log"])
def test_a_missing_metadata_file_without_a_change_is_not_reported_as_one(tmp_path, monkeypatch, missing):
    root = _flushing_world(tmp_path)
    read_metadata = ReadonlyLevelDbAdapter._read_metadata

    def missing_first(self, path):
        if path.endswith(missing):
            os.remove(path)
        return read_metadata(self, path)

    monkeypatch.setattr(ReadonlyLevelDbAdapter, "_read_metadata", missing_first)
    with pytest.raises(FileNotFoundError):
        ReadonlyLevelDbAdapter(str(root))


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
