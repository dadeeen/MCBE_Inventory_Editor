"""Synthetic on-disk fixtures; no native LevelDB or private worlds required."""
from __future__ import annotations

import hashlib
import struct
import zlib

import pytest

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
