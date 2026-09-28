"""Pure-Python readonly reader for Mojang's Bedrock LevelDB fork.

Opening a LevelDB with a native engine (Minecraft's own or amulet-leveldb)
always mutates the database directory: it acquires the LOCK file, replays the
write-ahead log and writes a fresh MANIFEST/CURRENT.  This module parses the
on-disk format directly and never writes a single byte, so worlds can be
inspected while the Bedrock server is running or on read-only media.

Supported on-disk features:

* CURRENT / MANIFEST (VersionEdit records) to discover live table files
* Write-ahead log replay (in memory only) so unflushed saves are visible
* SST/.ldb table files with block index and restart points
* WAL/MANIFEST and SST block CRC32C validation
* The newest WAL can discard an incomplete physical record or a CRC-damaged
  physical record ending at EOF, with a warning; other CRC/length errors fail
* Unfinished logical fragments and short EOF headers follow native recovery:
  ignored in every log, with incomplete-tail warnings for the newest WAL
* Mojang compression IDs: 0 (none), 2 (zlib) and 4 (raw zlib);
  Snappy (1) is rejected with a clear error because Bedrock never writes it

Limitations (by design):

* No LOCK handling: reading while another process is actively writing can
  observe a torn state.  Callers should treat results as a best-effort
  snapshot; the write path (``leveldb_writer``) takes the database locks.
* Blocks are limited to 64 MiB stored/decompressed; the combined MANIFEST/WAL
  input is limited to 256 MiB per reader. Larger inputs fail explicitly.
"""

from __future__ import annotations

import array
import functools
import hashlib
import heapq
import logging
import os
import re
import struct
import sys
import threading
import zlib
from collections import OrderedDict
from typing import NamedTuple

LOGGER = logging.getLogger(__name__)

_TABLE_MAGIC = 0xDB4775248B80FB57
_LOG_BLOCK_SIZE = 32768
_MAX_SEQUENCE = (1 << 56) - 1
_MAX_BLOCK_BYTES = 64 * 1024 * 1024
_MAX_METADATA_BYTES = 256 * 1024 * 1024
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
# The CRC consumes 32-bit little-endian words; a wrong word size would compute
# wrong checksums instead of failing, so refuse such a platform outright.
if array.array("I").itemsize != 4:  # pragma: no cover - no such CPython platform
    raise ImportError("CRC-32C benötigt einen 32-Bit-Array-Typ.")


@functools.cache
def _crc32c_word_tables() -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Tables that advance the CRC by the low and the high half of a 32-bit word.

    Built on first use: 2 x 65,536 entries (about 5 MB) let the loop take four
    bytes with two lookups, more than twice as fast as one byte per step.
    """

    table = _CRC32C_TABLE
    shifted = [table]
    for _ in range(3):
        shifted.append(tuple((value >> 8) ^ table[value & 0xFF] for value in shifted[-1]))
    t0, t1, t2, t3 = shifted
    low = tuple(t3[half & 0xFF] ^ t2[half >> 8] for half in range(65536))
    high = tuple(t1[half & 0xFF] ^ t0[half >> 8] for half in range(65536))
    return low, high


def _crc32c(data: bytes) -> int:
    low, high = _crc32c_word_tables()
    view = memoryview(data)
    aligned = len(view) - len(view) % 4
    words = array.array("I")
    words.frombytes(view[:aligned])
    if sys.byteorder == "big":  # pragma: no cover - little-endian test hosts
        words.byteswap()
    crc = 0xFFFFFFFF
    for word in words:
        crc ^= word
        crc = low[crc & 0xFFFF] ^ high[crc >> 16]
    table = _CRC32C_TABLE
    for byte in view[aligned:]:
        crc = table[(crc ^ byte) & 0xFF] ^ (crc >> 8)
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
        if shift == 63 and byte > 1:
            raise CorruptDatabaseError("Varint zu lang.")
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
    entry_type = tail & 0xFF
    if entry_type not in (_TYPE_DELETION, _TYPE_VALUE):
        raise CorruptDatabaseError("Unbekannter Eintragstyp im internen SST-Schlüssel.")
    return user_key, tail >> 8, entry_type


class LogTail:
    """Where a tolerated incomplete or damaged log tail was discarded."""

    def __init__(self) -> None:
        self.discarded_at: int | None = None

    def discard(self, offset: int, message: str) -> None:
        LOGGER.warning(message, offset)
        if self.discarded_at is None:
            self.discarded_at = offset


def _iter_log_records(data: bytes, *, recover_tail: bool = False, tail: LogTail | None = None):
    """Join log fragments; optionally discard a damaged final WAL record.

    Unlike native non-paranoid recovery, do not skip damaged blocks to look
    for later records. Only the newest WAL opts in to damaged physical-tail
    recovery. Unfinished logical fragments follow native recovery in every log.
    ``tail`` records the offset of a discarded tail for callers that must not
    build on top of it.
    """

    tail = tail if tail is not None else LogTail()
    fragments: list[bytes] = []
    fragment_start = 0
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
            recoverable_type = rec_type in (_RECORD_FULL, _RECORD_FIRST) or (
                bool(fragments) and rec_type in (_RECORD_MIDDLE, _RECORD_LAST)
            )
            if payload_end > block_end:
                # A partial write can end inside a physical record, but a
                # record can never legitimately cross a 32 KiB block boundary.
                if recover_tail and recoverable_type and block_end == length and payload_end <= offset + _LOG_BLOCK_SIZE:
                    tail.discard(fragment_start if fragments else pos, "Unvollständiger WAL-Schlussrecord ab Byte %d verworfen.")
                    return
                raise CorruptDatabaseError("Log-Record ragt über die Blockgrenze hinaus.")
            payload = data[payload_start:payload_end]
            actual_crc = _mask_crc32c(_crc32c(bytes((rec_type,)) + payload))
            if expected_crc != actual_crc:
                if recover_tail and recoverable_type and payload_end == length:
                    tail.discard(fragment_start if fragments else pos, "CRC-fehlerhafter WAL-Schlussrecord ab Byte %d verworfen.")
                    return
                raise CorruptDatabaseError("Log-Record-CRC ist ungültig.")
            if rec_type == _RECORD_FULL:
                # A FULL record starts a new logical record.  Never combine it
                # with an unterminated fragmented record from earlier in the
                # file; the latter can be a torn write at a block boundary.
                fragments = []
                yield payload
            elif rec_type == _RECORD_FIRST:
                fragments = [payload]
                fragment_start = pos
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
        if recover_tail and block_end == length and 0 < block_end - pos < 7 and any(data[pos:block_end]):
            tail.discard(fragment_start if fragments else pos, "Unvollständiger WAL-Schlussrecord ab Byte %d verworfen.")
            return
        offset += _LOG_BLOCK_SIZE
    if recover_tail and fragments:
        tail.discard(fragment_start, "Unvollständiger WAL-Schlussrecord ab Byte %d verworfen.")


class Manifest(NamedTuple):
    """Database state after replaying every VersionEdit of a MANIFEST.

    Counters that no VersionEdit recorded stay ``None``; the reader does not
    need them, but a writer must not guess them.
    """

    files: dict[int, dict[int, tuple[bytes, bytes]]]
    log_number: int | None
    prev_log_number: int | None
    next_file_number: int | None
    last_sequence: int | None
    comparator: bytes | None


def _parse_manifest(data: bytes) -> Manifest:
    """Replay all VersionEdits; return live files per level and the counters."""

    files: dict[int, dict[int, tuple[bytes, bytes]]] = {}
    log_number = None
    prev_log_number = None
    next_file_number = None
    last_sequence = None
    comparator = None
    for record in _iter_log_records(data):
        pos = 0
        while pos < len(record):
            tag, pos = _decode_varint(record, pos)
            if tag == _TAG_COMPARATOR:
                comparator, pos = _decode_length_prefixed(record, pos)
            elif tag in (_TAG_LOG_NUMBER, _TAG_PREV_LOG_NUMBER):
                value, pos = _decode_varint(record, pos)
                if tag == _TAG_LOG_NUMBER:
                    log_number = value
                else:
                    prev_log_number = value
            elif tag == _TAG_NEXT_FILE_NUMBER:
                next_file_number, pos = _decode_varint(record, pos)
            elif tag == _TAG_LAST_SEQUENCE:
                last_sequence, pos = _decode_varint(record, pos)
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
    return Manifest(files, log_number, prev_log_number, next_file_number, last_sequence, comparator)


def _decompress_block(raw: bytes) -> bytes:
    if len(raw) < 5:
        raise CorruptDatabaseError("Block ist zu kurz.")
    if len(raw) - 5 > _MAX_BLOCK_BYTES:
        raise CorruptDatabaseError("SST-Block überschreitet das Größenlimit.")
    expected_crc = struct.unpack_from("<I", raw, len(raw) - 4)[0]
    if expected_crc != _mask_crc32c(_crc32c(raw[:-4])):
        raise CorruptDatabaseError("SST-Block-CRC ist ungültig.")
    compression = raw[-5]
    content = raw[:-5]
    if compression == 0:
        return content
    if compression in (2, 4):
        try:
            decoder = zlib.decompressobj(15 if compression == 2 else -15)
            result = decoder.decompress(content, _MAX_BLOCK_BYTES + 1)
        except zlib.error as exc:
            raise CorruptDatabaseError("Ungültiger komprimierter SST-Block.") from exc
        if len(result) > _MAX_BLOCK_BYTES or decoder.unconsumed_tail:
            raise CorruptDatabaseError("SST-Block überschreitet das Größenlimit.")
        if not decoder.eof or decoder.unused_data:
            raise CorruptDatabaseError("Ungültiger komprimierter SST-Block.")
        return result
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


class _BlockCache:
    """Session-local LRU of validated, decompressed table blocks."""

    def __init__(self, max_bytes: int, *, max_entries: int = 4096):
        self._max_bytes = max_bytes
        self._max_entries = max_entries
        self._entries: OrderedDict[tuple[object, int, int], bytes] = OrderedDict()
        self._size = 0
        self._guard = threading.Lock()

    def get(self, key: tuple[object, int, int]) -> bytes | None:
        with self._guard:
            data = self._entries.get(key)
            if data is not None:
                self._entries.move_to_end(key)
            return data

    def put(self, key: tuple[object, int, int], data: bytes) -> None:
        with self._guard:
            try:
                previous = self._entries.pop(key, None)
                if previous is not None:
                    self._size -= len(previous)
                if len(data) > self._max_bytes or self._max_bytes <= 0 or self._max_entries <= 0:
                    return
                # Bound bookkeeping too, even for very small/empty blocks.
                while self._entries and (self._size + len(data) > self._max_bytes or len(self._entries) >= self._max_entries):
                    _, evicted = self._entries.popitem(last=False)
                    self._size -= len(evicted)
                self._entries[key] = data
                self._size += len(data)
            except MemoryError:
                # Caching is optional; release retained data and use this read.
                self._entries.clear()
                self._size = 0

    def clear(self) -> None:
        with self._guard:
            self._entries.clear()
            self._size = 0


class _Table:
    """Lazy reader for a single .ldb/.sst table file."""

    def __init__(self, path: str, *, block_cache: _BlockCache | None = None):
        self._path = path
        self._block_cache = block_cache
        # No table/path references in cache keys: no cross-world aliasing or
        # cache -> table -> cache cycle keeping file handles alive.
        self._cache_identity = object()
        # Handle intentionally stays open for lazy block reads; closed via close().
        self._handle = open(path, "rb")  # noqa: SIM115
        self._size = os.fstat(self._handle.fileno()).st_size
        self._index: list[tuple[bytes, int, int]] | None = None

    def close(self) -> None:
        self._block_cache = None
        self._handle.close()

    def _read_at(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0 or offset > self._size or size > self._size - offset:
            raise CorruptDatabaseError("SST-Blockreferenz liegt außerhalb der Datei.")
        if size > _MAX_BLOCK_BYTES + 5:
            raise CorruptDatabaseError("SST-Block überschreitet das Größenlimit.")
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
        cache = self._block_cache
        if cache is None:
            return _decompress_block(self._read_at(offset, size + 5))
        key = (self._cache_identity, offset, size)
        cached = cache.get(key)
        if cached is not None:
            return cached
        # Cache only after the original bounds, checksum and decompression checks.
        data = _decompress_block(self._read_at(offset, size + 5))
        cache.put(key, data)
        return data

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


def _replay_wal(
    data: bytes, memtable: dict[bytes, tuple[int, int, bytes]], *, recover_tail: bool = False, tail: LogTail | None = None
) -> int:
    """Apply every WAL batch to ``memtable``; return the newest sequence used."""

    last_sequence = 0
    for record in _iter_log_records(data, recover_tail=recover_tail, tail=tail):
        if len(record) < 12:
            raise CorruptDatabaseError("WAL-Batch ist zu kurz.")
        sequence, count = struct.unpack_from("<QI", record, 0)
        if sequence + count - 1 > _MAX_SEQUENCE:
            raise CorruptDatabaseError("WAL-Batch überschreitet den Sequenzbereich.")
        # Native recovery tracks Sequence + Count - 1 per batch, including
        # empty batches that only move the counter.
        last_sequence = max(last_sequence, sequence + count - 1)
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
        if pos != len(record):
            raise CorruptDatabaseError("Ungültige Eintragsanzahl im WAL-Batch.")
    return last_sequence


class ReadonlyLevelDbAdapter:
    """Readonly implementation of the BedrockDb protocol.

    Parses CURRENT/MANIFEST, replays the write-ahead log in memory and reads
    table files lazily.  Never acquires the LOCK file and never writes.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._tables: dict[int, _Table] = {}
        # Writers opt in after acquiring exclusive access. Ordinary readers
        # may inspect a running world, so they keep reading blocks afresh.
        self._block_cache: _BlockCache | None = None
        self._closed = False
        self._metadata_bytes = 0
        self._metadata_digests: list[tuple[str, int, bytes]] = []
        self._content_token: tuple | None = None

        current_path = os.path.join(db_path, "CURRENT")
        if not os.path.isfile(current_path):
            raise FileNotFoundError(f"Keine LevelDB gefunden (CURRENT fehlt): {db_path}")
        with open(current_path, "rb") as handle:
            manifest_name = handle.read(4096).decode("utf-8", errors="strict").strip()
        if not re.fullmatch(r"MANIFEST-\d{6,}", manifest_name):
            raise CorruptDatabaseError(f"Ungültiger CURRENT-Inhalt: {manifest_name!r}")
        self._manifest_name = manifest_name
        self._manifest = _parse_manifest(self._read_metadata(os.path.join(db_path, manifest_name)))
        self._files = self._manifest.files

        self._memtable: dict[bytes, tuple[int, int, bytes]] = {}
        wal_files = []
        for filename in os.listdir(db_path):
            match = re.fullmatch(r"(\d{6,})\.log", filename)
            if not match:
                continue
            file_number = int(match.group(1))
            if file_number < (self._manifest.log_number or 0) and file_number != self._manifest.prev_log_number:
                continue
            wal_files.append((file_number, filename))
        wal_files.sort()
        self._wal_names = [filename for _file_number, filename in wal_files]
        # Newest sequence in the MANIFEST or any replayed batch; a writer must
        # continue after it so its values shadow every older version.
        self._last_sequence = self._manifest.last_sequence or 0
        self._wal_tail = LogTail()
        for index, filename in enumerate(self._wal_names):
            newest = index == len(self._wal_names) - 1
            self._last_sequence = max(
                self._last_sequence,
                _replay_wal(
                    self._read_metadata(os.path.join(db_path, filename)), self._memtable,
                    recover_tail=newest, tail=self._wal_tail if newest else None,
                ),
            )

    def _read_metadata(self, path: str) -> bytes:
        with open(path, "rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            if size > _MAX_METADATA_BYTES - self._metadata_bytes:
                raise CorruptDatabaseError("MANIFEST/WAL-Daten überschreiten das Leselimit.")
            data = handle.read(size)
        if len(data) != size:
            raise CorruptDatabaseError("MANIFEST/WAL-Datei wurde während des Lesens verkürzt.")
        self._metadata_bytes += size
        self._metadata_digests.append((os.path.basename(path), size, hashlib.blake2b(data, digest_size=16).digest()))
        return data

    def content_token(self) -> tuple:
        """Identify the database state this reader sees, e.g. as a cache key.

        The MANIFEST and the replayed logs can change while an engine runs, so
        they count by the digest of the bytes this reader parsed.  Tables are
        immutable in LevelDB (new content gets a new file number); they count
        by number, size and modification time.
        """

        if self._content_token is None:
            tables = []
            for file_no in sorted({file_no for files in self._files.values() for file_no in files}):
                for extension in ("ldb", "sst"):
                    try:
                        stat = os.stat(os.path.join(self._db_path, f"{file_no:06d}.{extension}"))
                    except FileNotFoundError:
                        continue
                    tables.append((file_no, extension, stat.st_size, stat.st_mtime_ns))
                    break
                else:
                    tables.append((file_no, None, None, None))
            self._content_token = (
                os.path.normcase(os.path.abspath(self._db_path)),
                tuple(self._metadata_digests),
                tuple(tables),
            )
        return self._content_token

    def _table(self, file_no: int) -> _Table:
        table = self._tables.get(file_no)
        if table is None:
            for extension in ("ldb", "sst"):
                path = os.path.join(self._db_path, f"{file_no:06d}.{extension}")
                if os.path.isfile(path):
                    table = _Table(path, block_cache=self._block_cache)
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

        # Deeper levels have disjoint *internal*-key ranges. Versions of the
        # same user key can straddle file boundaries, and MANIFEST insertion
        # order does not rank those versions. Resolve every matching file in
        # this level before applying its newest value or tombstone.
        for level in sorted(level for level in self._files if level > 0):
            best = None
            for file_no, (smallest, largest) in self._files[level].items():
                if _split_internal_key(smallest)[0] <= key <= _split_internal_key(largest)[0]:
                    found = self._table(file_no).get(key)
                    if found is not None and (best is None or found[0] > best[0]):
                        best = found
            if best is not None:
                if best[1] == _TYPE_DELETION:
                    raise KeyError(key)
                return best[2]
        raise KeyError(key)

    def _newest_sequence(self, key: bytes) -> int | None:
        """Return the highest sequence of any stored version or tombstone of ``key``."""

        sequences = []
        entry = self._memtable.get(key)
        if entry is not None:
            sequences.append(entry[0])
        for files in self._files.values():
            for file_no, (smallest, largest) in files.items():
                if _split_internal_key(smallest)[0] <= key <= _split_internal_key(largest)[0]:
                    found = self._table(file_no).get(key)
                    if found is not None:
                        sequences.append(found[0])
        return max(sequences, default=None)

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
        if self._block_cache is not None:
            self._block_cache.clear()
        for table in self._tables.values():
            table.close()
        self._tables.clear()
