"""Integrity and bounded reads for synthetic Bedrock table files."""
import struct
import zlib

import pytest

from mcbe_editor import leveldb_readonly as reader
from tests.test_leveldb_readonly import _varint
from tests.test_readonly_format_regressions import _key, _new_file, _snapshot, _table, _world_db


def _stored_block(data, compression):
    payload = data if compression == 0 else zlib.compress(data, wbits=15 if compression == 2 else -15)
    payload += bytes([compression])
    return payload + struct.pack("<I", reader._mask_crc32c(reader._crc32c(payload)))


@pytest.mark.parametrize("compression", [0, 2, 4])
def test_sst_checksum_corruption_is_rejected(compression):
    raw = _stored_block(b"original", compression)
    assert reader._decompress_block(raw) == b"original"
    corrupt = raw[:-1] + bytes([raw[-1] ^ 1])
    with pytest.raises(reader.CorruptDatabaseError, match="CRC"):
        reader._decompress_block(corrupt)


@pytest.mark.parametrize("access", ["get", "iter_items"])
def test_structurally_valid_corrupt_value_is_rejected_by_adapter(tmp_path, access):
    key = _key(b"player", 1)
    table = _table([[(key, b"original")]], 0)
    db_path = _world_db(tmp_path, manifest=_new_file(0, 3, table, key, key))
    (db_path / "000003.ldb").write_bytes(table.replace(b"original", b"CHANGED!"))
    before = _snapshot(db_path)
    db = reader.ReadonlyLevelDbAdapter(str(db_path))
    try:
        with pytest.raises(reader.CorruptDatabaseError, match="CRC"):
            db.get(b"player") if access == "get" else list(db.iter_items())
    finally:
        db.close()
    assert _snapshot(db_path) == before


@pytest.mark.parametrize("last", [2, 0x7f, 0x81])
def test_varint_cannot_exceed_uint64(last):
    with pytest.raises(reader.CorruptDatabaseError):
        reader._decode_varint(b"\xff" * 9 + bytes([last]), 0)


@pytest.mark.parametrize("value", [0, 2**63, 2**64 - 1])
def test_uint64_varint_controls(value):
    raw = _varint(value)
    assert reader._decode_varint(raw, 0) == (value, len(raw))


@pytest.mark.parametrize("offset,size", [(0, 2**63), (2**63, 1), (1, 2**64 - 1)])
def test_huge_index_handle_is_a_controlled_database_error(tmp_path, offset, size):
    key = _key(b"player", 1)
    table = _table([[(key, b"value")]], 0)
    footer = (_varint(0) + _varint(0) + _varint(offset) + _varint(size)).ljust(40, b"\0")
    table = table[:-48] + footer + struct.pack("<Q", reader._TABLE_MAGIC)
    db_path = _world_db(tmp_path, manifest=_new_file(0, 3, table, key, key))
    (db_path / "000003.ldb").write_bytes(table)
    db = reader.ReadonlyLevelDbAdapter(str(db_path))
    try:
        with pytest.raises(reader.CorruptDatabaseError):
            db.get(b"player")
    finally:
        db.close()


@pytest.mark.parametrize("compression", [0, 2, 4])
def test_block_output_limit_allows_boundary_and_rejects_excess(monkeypatch, compression):
    monkeypatch.setattr(reader, "_MAX_BLOCK_BYTES", 1024, raising=False)
    assert reader._decompress_block(_stored_block(b"x" * 1024, compression)) == b"x" * 1024
    with pytest.raises(reader.CorruptDatabaseError):
        reader._decompress_block(_stored_block(b"x" * 1025, compression))


@pytest.mark.parametrize("compression", [2, 4])
def test_large_legitimate_compressed_block_is_readable(compression):
    payload = b"large-value-data" * (1024 * 1024)
    assert reader._decompress_block(_stored_block(payload, compression)) == payload


@pytest.mark.parametrize("compression", [2, 4])
def test_invalid_compressed_data_is_a_controlled_database_error(compression):
    raw = b"not a compressed stream" + bytes([compression])
    raw += struct.pack("<I", reader._mask_crc32c(reader._crc32c(raw)))
    with pytest.raises(reader.CorruptDatabaseError):
        reader._decompress_block(raw)


def test_combined_manifest_and_log_read_budget(monkeypatch, tmp_path):
    from tests.test_leveldb_readonly import _log_record, _write_batch

    db_path = _world_db(tmp_path, wal=_write_batch(1, [(b"a", b"value")]))
    second = _log_record(_write_batch(2, [(b"b", b"value")]))
    (db_path / "000003.log").write_bytes(second)
    sizes = sum(path.stat().st_size for path in db_path.iterdir() if path.name != "CURRENT")
    monkeypatch.setattr(reader, "_MAX_METADATA_BYTES", sizes - 1, raising=False)
    with pytest.raises(reader.CorruptDatabaseError):
        reader.ReadonlyLevelDbAdapter(str(db_path))
    monkeypatch.setattr(reader, "_MAX_METADATA_BYTES", sizes)
    db = reader.ReadonlyLevelDbAdapter(str(db_path))
    try:
        assert dict(db.iter_items()) == {b"a": b"value", b"b": b"value"}
    finally:
        db.close()
