"""Pure-Python readonly reader for Mojang's Bedrock LevelDB fork.

Opening a LevelDB with the real engine (amulet-leveldb) always mutates the
database directory: it acquires the LOCK file, replays the write-ahead log and
writes a fresh MANIFEST/CURRENT.  This module parses the on-disk format
directly and never writes a single byte, so worlds can be inspected while the
Bedrock server is running or on read-only media.

Supported on-disk features:

* CURRENT / MANIFEST (VersionEdit records) to discover live table files
* Write-ahead log replay (in memory only) so unflushed saves are visible
* SST/.ldb table files with block index and restart points
* WAL/MANIFEST physical record CRC32C validation
* Mojang compression IDs: 0 (none), 2 (zlib) and 4 (raw zlib);
  Snappy (1) is rejected with a clear error because Bedrock never writes it

Limitations (by design):

* No LOCK handling: reading while another process is actively writing can
  observe a torn state.  Callers should treat results as a best-effort
  snapshot; the write path of this project keeps using amulet-leveldb.
* SST block CRCs are not verified (corruption surfaces as parse errors instead).
"""

from __future__ import annotations

import heapq
import os
import re
import struct
import zlib

_TABLE_MAGIC = 0xDB4775248B80FB57
_LOG_BLOCK_SIZE = 32768
_MAX_SEQUENCE = (1 << 56) - 1
_TYPE_DELETION = 0
_TYPE_VALUE = 1

# Log record types (shared by WAL and MANIFEST files).
_RECORD_FULL = 1
_RECORD_FIRST = 2
_RECORD_MIDDLE = 3
_RECORD_LAST = 4

# VersionEdit tags.
_TAG_COMPARATOR = 1
_TAG_LOG_NUMBER = 2
_TAG_NEXT_FILE_NUMBER = 3
_TAG_LAST_SEQUENCE = 4
_TAG_COMPACT_POINTER = 5
_TAG_DELETED_FILE = 6
_TAG_NEW_FILE = 7
_TAG_PREV_LOG_NUMBER = 9


def _build_crc32c_table() -> tuple[int, ...]:
    polynomial = 0x82F63B78
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ polynomial
            else:
                crc >>= 1
        table.append(crc & 0xFFFFFFFF)
    return tuple(table)


_CRC32C_TABLE = _build_crc32c_table()


def _crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc = _CRC32C_TABLE[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


def _mask_crc32c(crc: int) -> int:
    return (((crc >> 15) | ((crc << 17) & 0xFFFFFFFF)) + 0xA282EAD8) & 0xFFFFFFFF


class CorruptDatabaseError(ValueError):
    """Raised when the LevelDB on-disk structures cannot be parsed."""


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise CorruptDatabaseError("Unerwartetes Datenende beim Varint-Lesen.")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise CorruptDatabaseError("Varint zu lang.")


def _decode_length_prefixed(data: bytes, pos: int) -> tuple[bytes, int]:
    length, pos = _decode_varint(data, pos)
    end = pos + length
    if end > len(data):
        raise CorruptDatabaseError("Unerwartetes Datenende beim Slice-Lesen.")
    return data[pos:end], end


def _split_internal_key(internal_key: bytes) -> tuple[bytes, int, int]:
    if len(internal_key) < 8:
        raise CorruptDatabaseError("Interner Schlüssel ist zu kurz.")
    user_key = internal_key[:-8]
    tail = struct.unpack("<Q", internal_key[-8:])[0]
    return user_key, tail >> 8, tail & 0xFF


def _iter_log_records(data: bytes):
    """Yield full log record payloads, joining FIRST/MIDDLE/LAST fragments."""

    fragments: list[bytes] = []
    offset = 0
    length = len(data)
    while offset < length:
        block_end = min(offset + _LOG_BLOCK_SIZE, length)
        pos = offset
        while pos + 7 <= block_end:
            expected_crc, rec_len, rec_type = struct.unpack_from("<IHB", data, pos)
            payload_start = pos + 7
            payload_end = payload_start + rec_len
            if rec_type == 0 and rec_len == 0:
                break  # trailer padding
            if payload_end > block_end:
                raise CorruptDatabaseError("Log-Record ragt über die Blockgrenze hinaus.")
            payload = data[payload_start:payload_end]
            actual_crc = _mask_crc32c(_crc32c(bytes((rec_type,)) + payload))
            if expected_crc != actual_crc:
                raise CorruptDatabaseError("Log-Record-CRC ist ungültig.")
            if rec_type == _RECORD_FULL:
                # A FULL record starts a new logical record.  Never combine it
                # with an unterminated fragmented record from earlier in the
                # file; the latter can be a torn write at a block boundary.
                fragments = []
                yield payload
            elif rec_type == _RECORD_FIRST:
                fragments = [payload]
            elif rec_type == _RECORD_MIDDLE:
                if not fragments:
                    raise CorruptDatabaseError("Fragmentierter Log-Record enthält MIDDLE ohne FIRST.")
                fragments.append(payload)
            elif rec_type == _RECORD_LAST:
                if not fragments:
                    raise CorruptDatabaseError("Fragmentierter Log-Record enthält LAST ohne FIRST.")
                fragments.append(payload)
                yield b"".join(fragments)
                fragments = []
            else:
                raise CorruptDatabaseError(f"Unbekannter Log-Record-Typ: {rec_type}")
            pos = payload_end
        offset += _LOG_BLOCK_SIZE


def _parse_manifest(data: bytes) -> tuple[dict[int, dict[int, tuple[bytes, bytes]]], int, int | None]:
    """Replay all VersionEdits; return live files per level and the WAL number."""

    files: dict[int, dict[int, tuple[bytes, bytes]]] = {}
    log_number = 0
    prev_log_number = None
    for record in _iter_log_records(data):
        pos = 0
        while pos < len(record):
            tag, pos = _decode_varint(record, pos)
            if tag == _TAG_COMPARATOR:
                _, pos = _decode_length_prefixed(record, pos)
            elif tag in (_TAG_LOG_NUMBER, _TAG_PREV_LOG_NUMBER):
                value, pos = _decode_varint(record, pos)
                if tag == _TAG_LOG_NUMBER:
                    log_number = value
                else:
                    prev_log_number = value
            elif tag in (_TAG_NEXT_FILE_NUMBER, _TAG_LAST_SEQUENCE):
                _, pos = _decode_varint(record, pos)
            elif tag == _TAG_COMPACT_POINTER:
                _, pos = _decode_varint(record, pos)
                _, pos = _decode_length_prefixed(record, pos)
            elif tag == _TAG_DELETED_FILE:
                level, pos = _decode_varint(record, pos)
                file_no, pos = _decode_varint(record, pos)
                files.get(level, {}).pop(file_no, None)
            elif tag == _TAG_NEW_FILE:
                level, pos = _decode_varint(record, pos)
                file_no, pos = _decode_varint(record, pos)
                _, pos = _decode_varint(record, pos)  # file size
                smallest, pos = _decode_length_prefixed(record, pos)
                largest, pos = _decode_length_prefixed(record, pos)
                files.setdefault(level, {})[file_no] = (smallest, largest)
            else:
                raise CorruptDatabaseError(f"Unbekannter VersionEdit-Tag: {tag}")
    return files, log_number, prev_log_number


def _decompress_block(raw: bytes) -> bytes:
    if len(raw) < 5:
        raise CorruptDatabaseError("Block ist zu kurz.")
    compression = raw[-5]
    content = raw[:-5]
    if compression == 0:
        return content
    if compression == 2:
        return zlib.decompress(content)
    if compression == 4:
        return zlib.decompress(content, -15)
    if compression == 1:
        raise CorruptDatabaseError(
            "Snappy-komprimierter Block gefunden. Diese Welt stammt nicht aus Minecraft Bedrock und wird vom Readonly-Reader nicht unterstützt."
        )
    raise CorruptDatabaseError(f"Unbekannte Blockkompression: {compression}")


def _iter_block_entries(block: bytes):
    """Yield (key, value) pairs of a table block in on-disk order."""

    if len(block) < 4:
        raise CorruptDatabaseError("Tabellenblock ist zu kurz.")
    num_restarts = struct.unpack_from("<I", block, len(block) - 4)[0]
    data_end = len(block) - 4 - 4 * num_restarts
    if data_end < 0:
        raise CorruptDatabaseError("Ungültige Restart-Punkte im Tabellenblock.")
    pos = 0
    key = b""
    while pos < data_end:
        shared, pos = _decode_varint(block, pos)
        non_shared, pos = _decode_varint(block, pos)
        value_len, pos = _decode_varint(block, pos)
        if shared > len(key) or pos + non_shared + value_len > data_end:
            raise CorruptDatabaseError("Ungültiger Eintrag im Tabellenblock.")
        key = key[:shared] + block[pos : pos + non_shared]
        pos += non_shared
        value = block[pos : pos + value_len]
        pos += value_len
        yield key, value


class _Table:
    """Lazy reader for a single .ldb/.sst table file."""

    def __init__(self, path: str):
        self._path = path
        # Handle intentionally stays open for lazy block reads; closed via close().
        self._handle = open(path, "rb")  # noqa: SIM115
        self._size = os.fstat(self._handle.fileno()).st_size
        self._index: list[tuple[bytes, int, int]] | None = None

    def close(self) -> None:
        self._handle.close()

    def _read_at(self, offset: int, size: int) -> bytes:
        self._handle.seek(offset)
        data = self._handle.read(size)
        if len(data) != size:
            raise CorruptDatabaseError(f"Unerwartetes Dateiende in {self._path}.")
        return data

    def _load_index(self) -> list[tuple[bytes, int, int]]:
        if self._index is not None:
            return self._index
        if self._size < 48:
            raise CorruptDatabaseError(f"Tabellendatei ist zu klein: {self._path}")
        footer = self._read_at(self._size - 48, 48)
        magic = struct.unpack("<Q", footer[40:48])[0]
        if magic != _TABLE_MAGIC:
            raise CorruptDatabaseError(f"Ungültige Tabellendatei (Magic fehlt): {self._path}")
        pos = 0
        _, pos = _decode_varint(footer, pos)  # metaindex offset
        _, pos = _decode_varint(footer, pos)  # metaindex size
        index_offset, pos = _decode_varint(footer, pos)
        index_size, pos = _decode_varint(footer, pos)
        index_block = _decompress_block(self._read_at(index_offset, index_size + 5))
        index: list[tuple[bytes, int, int]] = []
        for key, value in _iter_block_entries(index_block):
            block_offset, value_pos = _decode_varint(value, 0)
            block_size, _ = _decode_varint(value, value_pos)
            # Store only the user-key part of the separator.  Internal keys
            # order by (user_key asc, sequence DESC) and the sequence tail is
            # little-endian, so raw bytewise comparison of full internal keys
            # would be wrong for the search below.
            separator_user_key, _seq, _type = _split_internal_key(key)
            index.append((separator_user_key, block_offset, block_size))
        self._index = index
        return index

    def _read_block(self, offset: int, size: int) -> bytes:
        return _decompress_block(self._read_at(offset, size + 5))

    def iter_entries(self):
        """Yield (internal_key, value) for every entry, in internal-key order."""

        for _key, offset, size in self._load_index():
            yield from _iter_block_entries(self._read_block(offset, size))

    def get(self, user_key: bytes) -> tuple[int, int, bytes] | None:
        """Return the newest (sequence, type, value) for user_key, if present.

        Each index separator is >= every key in its block.  The first block
        whose separator user-key is >= the sought user-key is therefore the
        block that holds the newest version (internal order puts the highest
        sequence first).
        """

        index = self._load_index()
        lo, hi = 0, len(index)
        while lo < hi:
            mid = (lo + hi) // 2
            if index[mid][0] < user_key:
                lo = mid + 1
            else:
                hi = mid
        if lo >= len(index):
            return None
        best: tuple[int, int, bytes] | None = None
        for internal_key, value in _iter_block_entries(self._read_block(index[lo][1], index[lo][2])):
            entry_user_key, sequence, entry_type = _split_internal_key(internal_key)
            if entry_user_key == user_key and (best is None or sequence > best[0]):
                best = (sequence, entry_type, value)
            elif entry_user_key > user_key:
                break
        return best


def _replay_wal(data: bytes, memtable: dict[bytes, tuple[int, int, bytes]]) -> None:
    for record in _iter_log_records(data):
        if len(record) < 12:
            raise CorruptDatabaseError("WAL-Batch ist zu kurz.")
        sequence, count = struct.unpack_from("<QI", record, 0)
        pos = 12
        for i in range(count):
            if pos >= len(record):
                raise CorruptDatabaseError("WAL-Batch endet unerwartet.")
            entry_type = record[pos]
            pos += 1
            key, pos = _decode_length_prefixed(record, pos)
            if entry_type == _TYPE_VALUE:
                value, pos = _decode_length_prefixed(record, pos)
            elif entry_type == _TYPE_DELETION:
                value = b""
            else:
                raise CorruptDatabaseError(f"Unbekannter WAL-Eintragstyp: {entry_type}")
            entry_sequence = sequence + i
            existing = memtable.get(key)
            if existing is None or entry_sequence >= existing[0]:
                memtable[key] = (entry_sequence, entry_type, value)


class ReadonlyLevelDbAdapter:
    """Readonly implementation of the BedrockDb protocol.

    Parses CURRENT/MANIFEST, replays the write-ahead log in memory and reads
    table files lazily.  Never acquires the LOCK file and never writes.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._tables: dict[int, _Table] = {}
        self._closed = False

        current_path = os.path.join(db_path, "CURRENT")
        if not os.path.isfile(current_path):
            raise FileNotFoundError(f"Keine LevelDB gefunden (CURRENT fehlt): {db_path}")
        with open(current_path, "rb") as handle:
            manifest_name = handle.read(4096).decode("utf-8", errors="strict").strip()
        if not re.fullmatch(r"MANIFEST-\d{6,}", manifest_name):
            raise CorruptDatabaseError(f"Ungültiger CURRENT-Inhalt: {manifest_name!r}")
        with open(os.path.join(db_path, manifest_name), "rb") as handle:
            self._files, log_number, prev_log_number = _parse_manifest(handle.read())

        self._memtable: dict[bytes, tuple[int, int, bytes]] = {}
        for filename in sorted(os.listdir(db_path)):
            match = re.fullmatch(r"(\d{6,})\.log", filename)
            if not match:
                continue
            file_number = int(match.group(1))
            if file_number < log_number and file_number != prev_log_number:
                continue
            with open(os.path.join(db_path, filename), "rb") as handle:
                _replay_wal(handle.read(), self._memtable)

    def _table(self, file_no: int) -> _Table:
        table = self._tables.get(file_no)
        if table is None:
            for extension in ("ldb", "sst"):
                path = os.path.join(self._db_path, f"{file_no:06d}.{extension}")
                if os.path.isfile(path):
                    table = _Table(path)
                    break
            else:
                raise CorruptDatabaseError(f"Tabellendatei {file_no:06d} fehlt.")
            self._tables[file_no] = table
        return table

    def get(self, key: bytes) -> bytes:
        if self._closed:
            raise RuntimeError("Datenbank ist geschlossen.")
        entry = self._memtable.get(key)
        if entry is not None:
            if entry[1] == _TYPE_DELETION:
                raise KeyError(key)
            return entry[2]

        # Level 0 files may overlap; newest file number wins.
        for file_no in sorted(self._files.get(0, {}), reverse=True):
            found = self._table(file_no).get(key)
            if found is not None:
                if found[1] == _TYPE_DELETION:
                    raise KeyError(key)
                return found[2]

        # Deeper levels have disjoint key ranges within each level.
        for level in sorted(level for level in self._files if level > 0):
            for file_no, (smallest, largest) in self._files[level].items():
                if _split_internal_key(smallest)[0] <= key <= _split_internal_key(largest)[0]:
                    found = self._table(file_no).get(key)
                    if found is not None:
                        if found[1] == _TYPE_DELETION:
                            raise KeyError(key)
                        return found[2]
                    break
        raise KeyError(key)

    def put(self, key: bytes, value: bytes) -> None:
        raise RuntimeError("Diese Datenbank ist im Readonly-Modus geöffnet; Schreiben ist nicht möglich.")

    def iter_items(self):
        """Yield (key, value) pairs, newest version per key, tombstones skipped."""

        if self._closed:
            raise RuntimeError("Datenbank ist geschlossen.")

        def memtable_stream():
            for user_key in sorted(self._memtable):
                sequence, entry_type, value = self._memtable[user_key]
                yield user_key, sequence, entry_type, value

        def table_stream(file_no: int):
            for internal_key, value in self._table(file_no).iter_entries():
                user_key, sequence, entry_type = _split_internal_key(internal_key)
                yield user_key, sequence, entry_type, value

        streams = [memtable_stream()]
        for level in sorted(self._files):
            for file_no in sorted(self._files[level]):
                streams.append(table_stream(file_no))

        merged = heapq.merge(*streams, key=lambda item: (item[0], _MAX_SEQUENCE - item[1]))
        previous_key: bytes | None = None
        for user_key, _sequence, entry_type, value in merged:
            if user_key == previous_key:
                continue
            previous_key = user_key
            if entry_type == _TYPE_VALUE:
                yield user_key, value

    def close(self) -> None:
        self._closed = True
        for table in self._tables.values():
            table.close()
        self._tables.clear()
