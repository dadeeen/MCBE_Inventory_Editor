"""Pure-Python write path for Mojang's Bedrock LevelDB fork.

The writer never rewrites an existing database file.  A write session appends
complete, checksummed write batches to one new write-ahead log (WAL); tables,
MANIFEST and CURRENT stay untouched.  Minecraft's LevelDB engine replays such a
log the next time it opens the world, exactly as after an unclean shutdown:

* ``DBImpl::Recover`` replays every ``NNNNNN.log`` numbered at or above the
  MANIFEST log number, in numeric order, including logs the MANIFEST does not
  list, and then moves their contents into its own level-0 tables.
* Each batch continues after the newest sequence of the MANIFEST and of every
  replayed log, so its values and deletions shadow all older versions.
* A batch is a single logical log record.  A torn write leaves an incomplete
  record at the end of the new log, which recovery ignores: the batch applies
  completely or not at all.

Opening a database for writing takes the locks the native engine takes.  It
fails while another editor process or a LevelDB engine that locks ``LOCK``
holds the world, and on Windows also while Minecraft or a server holds it:

* POSIX: an exclusive ``fcntl`` lock on ``LOCK``, as in LevelDB's POSIX env.
  Bedrock Dedicated Server 1.26.51.1 on Linux takes no lock at all and only
  keeps its files open, which POSIX cannot detect.  There the server-status
  gate is the only protection against a running server.
* Windows: Mojang's Windows env does not lock an empty ``LOCK`` file.  A running
  engine keeps write access to ``CURRENT``, its MANIFEST and its log; opening
  them for reading without write sharing therefore fails while it runs.  During
  a session, ``CURRENT`` is held with write access and without write or delete
  sharing, so a starting engine fails before recovery.  An exclusive byte-range
  lock on ``LOCK`` also excludes engines that do lock that file.

Nothing is compacted here; the world's own engine does that on its next open.
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
import struct
import threading
import weakref
from collections.abc import Iterable, Mapping
from contextlib import suppress
from types import ModuleType
from typing import BinaryIO, NoReturn

from .db_state import CommittedDbChange
from .i18n import t
from .leveldb_readonly import (
    _LOG_BLOCK_SIZE,
    _MAX_METADATA_BYTES,
    _MAX_SEQUENCE,
    _RECORD_FIRST,
    _RECORD_FULL,
    _RECORD_LAST,
    _RECORD_MIDDLE,
    _TAG_COMPARATOR,
    _TAG_LAST_SEQUENCE,
    _TAG_LOG_NUMBER,
    _TAG_NEXT_FILE_NUMBER,
    _TYPE_DELETION,
    _TYPE_VALUE,
    CorruptDatabaseError,
    ReadonlyLevelDbAdapter,
    _BlockCache,
    _crc32c,
    _iter_log_records,
    _mask_crc32c,
)
from .service_errors import LevelDbInUseError, LevelDbUncleanLogError

fcntl: ModuleType | None
try:  # pragma: no cover - platform-dependent import
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None
else:  # pragma: no cover - POSIX
    fcntl = _fcntl

# Decided once: the lock backend must match the real platform even when tests
# patch os.name to exercise platform-specific messages.
_WINDOWS = os.name == "nt"
_LOG_HEADER_SIZE = 7
_BYTEWISE_COMPARATOR = b"leveldb.BytewiseComparator"
_MAX_SLICE_BYTES = 0xFFFFFFFF
_MAX_FILE_NUMBER = (1 << 64) - 1
# Lazy upper bound shared by all tables in one session, not a preallocation.
_WRITE_BLOCK_CACHE_BYTES = 64 * 1024 * 1024
_NUMBERED_FILE_RE = re.compile(r"(?:(\d+)\.(?:log|ldb|sst|dbtmp)|MANIFEST-(\d+))")
# Files a native engine may leave in a directory it never finished creating.
_BLANK_DATABASE_NAMES = frozenset({"LOCK", "LOG", "LOG.old"})
# Same policy as backups: these mean "not supported here", not an I/O failure.
_UNSUPPORTED_SYNC_ERRNOS = frozenset(
    code for code in (errno.EINVAL, errno.ENOSYS, getattr(errno, "ENOTSUP", None), getattr(errno, "EOPNOTSUPP", None)) if code is not None
)

_OPEN_DATABASES: set[str] = set()
_OPEN_DATABASES_GUARD = threading.Lock()


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("Varint-Werte dürfen nicht negativ sein.")
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _encode_slice(value: bytes) -> bytes:
    if len(value) > _MAX_SLICE_BYTES:
        raise ValueError("LevelDB-Schlüssel und -Werte sind auf 4 GiB begrenzt.")
    return _encode_varint(len(value)) + value


def encode_write_batch(sequence: int, entries: Iterable[tuple[bytes, bytes | None]]) -> bytes:
    """Encode a LevelDB ``WriteBatch``; a ``None`` value deletes its key."""

    body = bytearray()
    count = 0
    for key, value in entries:
        if value is None:
            body.append(_TYPE_DELETION)
            body += _encode_slice(key)
        else:
            body.append(_TYPE_VALUE)
            body += _encode_slice(key)
            body += _encode_slice(value)
        count += 1
    return struct.pack("<QI", sequence, count) + bytes(body)


def frame_log_record(record: bytes, block_offset: int) -> bytes:
    """Split one logical record into physical records like ``log::Writer::AddRecord``.

    ``block_offset`` is the write position inside the current 32 KiB block.
    Fewer than seven remaining bytes are zero-filled and the record continues in
    the next block; fragments never cross a block boundary.
    """

    if not 0 <= block_offset < _LOG_BLOCK_SIZE:
        raise ValueError("Ungültige Position im Log-Block.")
    framed = bytearray()
    position = 0
    begin = True
    while True:
        leftover = _LOG_BLOCK_SIZE - block_offset
        if leftover < _LOG_HEADER_SIZE:
            framed += bytes(leftover)
            block_offset = 0
        fragment = record[position : position + _LOG_BLOCK_SIZE - block_offset - _LOG_HEADER_SIZE]
        position += len(fragment)
        end = position == len(record)
        if begin and end:
            record_type = _RECORD_FULL
        elif begin:
            record_type = _RECORD_FIRST
        elif end:
            record_type = _RECORD_LAST
        else:
            record_type = _RECORD_MIDDLE
        checksum = _mask_crc32c(_crc32c(bytes((record_type,)) + fragment))
        framed += struct.pack("<IHB", checksum, len(fragment), record_type)
        framed += fragment
        block_offset += _LOG_HEADER_SIZE + len(fragment)
        begin = False
        if end:
            return bytes(framed)


def _new_database_edit() -> bytes:
    """Return the first VersionEdit that ``DBImpl::NewDB`` writes."""

    return b"".join(
        (
            _encode_varint(_TAG_COMPARATOR),
            _encode_slice(_BYTEWISE_COMPARATOR),
            _encode_varint(_TAG_LOG_NUMBER),
            _encode_varint(0),
            _encode_varint(_TAG_NEXT_FILE_NUMBER),
            _encode_varint(2),
            _encode_varint(_TAG_LAST_SEQUENCE),
            _encode_varint(0),
        )
    )


def _sync_directory(path: str) -> None:
    """Sync directory entries on POSIX; no directory flush is provided on Windows.

    Filesystems without directory sync report it as unsupported. Native
    LevelDB does not sync the directory for a new log at all, so continuing
    there is no weaker than the engine. Real I/O errors still fail.
    """

    if _WINDOWS:
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    except OSError as exc:
        if exc.errno not in _UNSUPPORTED_SYNC_ERRNOS:
            raise
    finally:
        os.close(descriptor)


def _write_new_file(path: str, data: bytes) -> None:
    with open(path, "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _is_blank_database_dir(db_path: str) -> bool:
    return all(name in _BLANK_DATABASE_NAMES for name in os.listdir(db_path))


def _create_empty_database(db_path: str) -> None:
    """Create the files ``DBImpl::NewDB`` creates: MANIFEST-000001 and CURRENT."""

    _write_new_file(os.path.join(db_path, "MANIFEST-000001"), frame_log_record(_new_database_edit(), 0))
    temporary = os.path.join(db_path, "000001.dbtmp")
    _write_new_file(temporary, b"MANIFEST-000001\n")
    os.replace(temporary, os.path.join(db_path, "CURRENT"))
    _sync_directory(db_path)


def _highest_file_number(db_path: str) -> int:
    highest = 0
    for name in os.listdir(db_path):
        match = _NUMBERED_FILE_RE.fullmatch(name)
        if match:
            highest = max(highest, int(match.group(1) or match.group(2)))
    return highest


if _WINDOWS:  # pragma: no cover - platform-specific
    import ctypes
    from ctypes import wintypes

    class _Overlapped(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CreateFileW = _kernel32.CreateFileW
    _CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    _CreateFileW.restype = wintypes.HANDLE
    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = (wintypes.HANDLE,)
    _CloseHandle.restype = wintypes.BOOL
    _LockFileEx = _kernel32.LockFileEx
    _LockFileEx.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_Overlapped))
    _LockFileEx.restype = wintypes.BOOL
    _UnlockFileEx = _kernel32.UnlockFileEx
    _UnlockFileEx.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_Overlapped))
    _UnlockFileEx.restype = wintypes.BOOL

    _INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _FILE_SHARE_READ = 0x1
    _FILE_SHARE_WRITE = 0x2
    _OPEN_EXISTING = 3
    _OPEN_ALWAYS = 4
    _FILE_ATTRIBUTE_NORMAL = 0x80
    _LOCKFILE_FAIL_IMMEDIATELY = 0x1
    _LOCKFILE_EXCLUSIVE_LOCK = 0x2
    _ERROR_SHARING_VIOLATION = 32
    _ERROR_LOCK_VIOLATION = 33
    _WHOLE_FILE = 0xFFFFFFFF

    def _raise_windows_error(code: int, path: str, db_path: str) -> NoReturn:
        # The winerror argument selects the matching OSError subclass, e.g.
        # PermissionError for ERROR_ACCESS_DENIED.
        error = OSError(None, ctypes.FormatError(code), path, code)
        if code in (_ERROR_SHARING_VIOLATION, _ERROR_LOCK_VIOLATION):
            raise LevelDbInUseError(db_path=db_path) from error
        raise error

    def _windows_open(path: str, access: int, share: int, disposition: int, db_path: str) -> int:
        handle = _CreateFileW(path, access, share, None, disposition, _FILE_ATTRIBUTE_NORMAL, None)
        if handle is None or handle == _INVALID_HANDLE_VALUE:
            _raise_windows_error(ctypes.get_last_error(), path, db_path)
        return int(handle)

    def _windows_lock_file(path: str, db_path: str) -> int:
        handle = _windows_open(path, _GENERIC_READ | _GENERIC_WRITE, _FILE_SHARE_READ | _FILE_SHARE_WRITE, _OPEN_ALWAYS, db_path)
        overlapped = _Overlapped()
        flags = _LOCKFILE_EXCLUSIVE_LOCK | _LOCKFILE_FAIL_IMMEDIATELY
        if not _LockFileEx(handle, flags, 0, _WHOLE_FILE, _WHOLE_FILE, ctypes.byref(overlapped)):
            code = ctypes.get_last_error()
            _CloseHandle(handle)
            _raise_windows_error(code, path, db_path)
        return handle

    def _windows_unlock_file(handle: int) -> None:
        try:
            _UnlockFileEx(handle, 0, _WHOLE_FILE, _WHOLE_FILE, ctypes.byref(_Overlapped()))
        finally:
            _CloseHandle(handle)


def _posix_lock_file(path: str, db_path: str) -> int:
    assert fcntl is not None
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.lockf(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(descriptor)
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            raise LevelDbInUseError(db_path=db_path) from exc
        raise
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


class _DatabaseAccess:
    """Exclusive access to one database directory for the length of a session."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._key = os.path.normcase(os.path.realpath(db_path))
        self._lock: int | None = None
        self._current: int | None = None
        with _OPEN_DATABASES_GUARD:
            # fcntl locks are per process, so a second session of this process
            # must be refused here; Windows share modes would refuse it anyway.
            if self._key in _OPEN_DATABASES:
                raise LevelDbInUseError(db_path=db_path)
            _OPEN_DATABASES.add(self._key)
        try:
            lock_path = os.path.join(db_path, "LOCK")
            self._lock = _windows_lock_file(lock_path, db_path) if _WINDOWS else _posix_lock_file(lock_path, db_path)
        except BaseException:
            self._unregister()
            raise

    def hold_current(self) -> None:
        """Keep CURRENT so that no engine can start recovery while we write."""

        if _WINDOWS:
            self._current = _windows_open(
                os.path.join(self._db_path, "CURRENT"), _GENERIC_READ | _GENERIC_WRITE, _FILE_SHARE_READ, _OPEN_EXISTING, self._db_path
            )

    def ensure_unused(self, paths: Iterable[str]) -> None:
        """Fail if another process keeps one of ``paths`` open for writing."""

        if _WINDOWS:
            for path in paths:
                _CloseHandle(_windows_open(path, _GENERIC_READ, _FILE_SHARE_READ, _OPEN_EXISTING, self._db_path))

    def release(self) -> None:
        try:
            if self._current is not None:
                current, self._current = self._current, None
                _CloseHandle(current)
        finally:
            try:
                if self._lock is not None:
                    lock, self._lock = self._lock, None
                    if _WINDOWS:
                        _windows_unlock_file(lock)
                    else:
                        try:
                            assert fcntl is not None
                            fcntl.lockf(lock, fcntl.LOCK_UN)
                        finally:
                            os.close(lock)
            finally:
                self._unregister()

    def _unregister(self) -> None:
        with _OPEN_DATABASES_GUARD:
            _OPEN_DATABASES.discard(self._key)


class _SessionLog:
    """The new WAL file that receives this session's batches."""

    def __init__(self, path: str) -> None:
        self.path = path
        # Kept open for the session's appends; closed via close().
        self._handle: BinaryIO = open(path, "xb", buffering=0)  # noqa: SIM115
        self.size = 0
        self.records: list[bytes] = []
        self.verified_digest: bytes | None = None

    def append(self, framed: bytes) -> None:
        self.verified_digest = None
        view = memoryview(framed)
        while view:
            written = self._handle.write(view)
            if not written:
                raise OSError(errno.EIO, "Log-Datei hat keine Daten angenommen.", self.path)
            view = view[written:]
        os.fsync(self._handle.fileno())
        self.size += len(framed)

    def verify(self, expected_records: list[bytes]) -> None:
        with open(self.path, "rb") as handle:
            data = handle.read()
        if len(data) != self.size or list(_iter_log_records(data)) != expected_records:
            raise CorruptDatabaseError("Die geschriebene Log-Datei weicht vom Schreibauftrag ab.")
        # Optional cache evidence, calculated from the already verified bytes.
        # Allocation failure must not change the outcome of the actual write.
        with suppress(MemoryError):
            self.verified_digest = hashlib.blake2b(data, digest_size=16).digest()

    def truncate(self, size: int) -> None:
        self._handle.truncate(size)
        self._handle.seek(size)
        os.fsync(self._handle.fileno())
        self.size = size

    def close(self) -> None:
        self._handle.close()


class _SessionResources:
    """Everything a session must give back, also when it is garbage-collected."""

    def __init__(self, access: _DatabaseAccess) -> None:
        self.access: _DatabaseAccess | None = access
        self.log: _SessionLog | None = None

    def release(self) -> None:
        try:
            if self.log is not None:
                log, self.log = self.log, None
                log.close()
        finally:
            if self.access is not None:
                access, self.access = self.access, None
                access.release()


class LevelDbWriter(ReadonlyLevelDbAdapter):
    """Write session: the readonly view plus batches appended to a new WAL."""

    def __init__(self, db_path: str) -> None:
        db_path = str(db_path)
        self._write_lock = threading.Lock()
        self._failed = False
        # Per thread: another thread's put must not reset the evidence of a
        # batch whose exception this thread is still classifying.
        self._write_attempt = threading.local()
        self._expected_token: tuple | None = None
        self._last_change: CommittedDbChange | None = None
        access = _DatabaseAccess(db_path)
        try:
            resources = _SessionResources(access)
            self._resources = resources
            self._release = weakref.finalize(self, resources.release)
        except BaseException:
            # Nothing owns the lock yet, so give it back before the error leaves.
            access.release()
            raise
        try:
            current = os.path.join(db_path, "CURRENT")
            if not os.path.isfile(current):
                if not _is_blank_database_dir(db_path):
                    raise FileNotFoundError(f"Keine LevelDB gefunden (CURRENT fehlt): {db_path}")
                _create_empty_database(db_path)
            assert resources.access is not None
            resources.access.hold_current()
            # With exclusive access no engine compacts meanwhile, so tables
            # can open on demand.
            super().__init__(db_path, hold_tables=False)
            self._check_writable()
            resources.access.ensure_unused(
                os.path.join(db_path, name) for name in (self._manifest_name, *self._wal_names)
            )
            self._block_cache = _BlockCache(_WRITE_BLOCK_CACHE_BYTES)
        except BaseException:
            try:
                if hasattr(self, "_reserved_tables"):
                    self._close_tables()
            finally:
                self._release()
            raise

    def _check_writable(self) -> None:
        manifest = self._manifest
        if manifest.comparator not in (None, _BYTEWISE_COMPARATOR):
            raise CorruptDatabaseError(f"Nicht unterstützter LevelDB-Comparator: {manifest.comparator!r}")
        if manifest.log_number is None or manifest.next_file_number is None or manifest.last_sequence is None:
            raise CorruptDatabaseError("Das MANIFEST enthält keine vollständigen Datei- und Sequenzzähler.")
        if manifest.next_file_number <= max(manifest.log_number, manifest.prev_log_number or 0):
            # Otherwise a new WAL can be below the recovery cutoff: the write
            # succeeds in this session but vanishes when the world is reopened.
            raise CorruptDatabaseError(t("Das MANIFEST enthält widersprüchliche Dateizähler."))
        for files in manifest.files.values():
            for file_no in files:
                for extension in ("ldb", "sst"):
                    try:
                        mode = os.stat(os.path.join(self._db_path, f"{file_no:06d}.{extension}")).st_mode
                    except FileNotFoundError:
                        continue
                    if not stat.S_ISREG(mode):
                        raise CorruptDatabaseError(t("Tabellendatei {number} ist keine reguläre Datei.", number=f"{file_no:06d}"))
                    break
                else:
                    # Validate presence even when all edited keys live in the
                    # WAL or another table. Never build on a partial world copy.
                    raise CorruptDatabaseError(t("Tabellendatei {number} fehlt.", number=f"{file_no:06d}"))
        if self._wal_tail.discarded_at is not None:
            # A new log after a torn one would hide the damage from recovery
            # checks; the engine that wrote it must recover it first.
            raise LevelDbUncleanLogError(db_path=self._db_path)

    def content_token(self) -> None:  # type: ignore[override]
        """Offer no cache key: this session's own batches change the state it opened."""

        return None

    def committed_change(self) -> CommittedDbChange | None:
        """Evidence for the last successful batch, never a live reader token."""

        with self._write_lock:
            return None if self._failed or self._closed else self._last_change

    def last_write_reached_log(self) -> bool:
        """Whether this thread's last ``put``/``put_batch`` began appending its batch.

        ``False`` proves that none of that batch's bytes were written: every
        check, the log creation and the directory sync happen before the first
        append. ``True`` leaves the outcome open unless the call returned.
        """

        return getattr(self._write_attempt, "reached_log", False)

    def put(self, key: bytes, value: bytes) -> None:
        self._write_attempt.reached_log = False
        if value is None:
            raise TypeError("LevelDB-Werte müssen Bytes sein.")
        self.put_batch({key: value})

    def put_batch(self, data: Mapping[bytes, bytes | None]) -> None:
        self._write_attempt.reached_log = False
        entries = list(data.items())
        for key, value in entries:
            if not isinstance(key, bytes) or not (value is None or isinstance(value, bytes)):
                raise TypeError("LevelDB-Schlüssel und -Werte müssen Bytes sein.")
        if entries:
            with self._write_lock:
                self._append(entries)

    def _append(self, entries: list[tuple[bytes, bytes | None]]) -> None:
        self._last_change = None
        if self._closed:
            raise RuntimeError("Datenbank ist geschlossen.")
        if self._failed:
            raise RuntimeError(t("Nach einem fehlgeschlagenen Schreibversuch nimmt diese Datenbanksitzung keine weiteren Änderungen an."))
        sequence = self._last_sequence + 1
        last_sequence = sequence + len(entries) - 1
        if last_sequence > _MAX_SEQUENCE:
            raise CorruptDatabaseError("Der LevelDB-Sequenzbereich ist erschöpft.")
        start = self._resources.log.size if self._resources.log is not None else 0
        # Refuse oversized payloads before copying them into encoded/framed
        # buffers or computing their CRCs. Framing overhead is checked below.
        record_size = 12
        for key, value in entries:
            record_size += 1
            for part in (key, value):
                if part is not None:
                    size = len(part)
                    if size > _MAX_SLICE_BYTES:
                        raise ValueError("LevelDB-Schlüssel und -Werte sind auf 4 GiB begrenzt.")
                    record_size += size + max(1, (size.bit_length() + 6) // 7)
            if self._metadata_bytes + start + record_size > _MAX_METADATA_BYTES:
                raise ValueError(t("Die Änderung ist zu groß für das Schreibprotokoll der Welt."))
        for key, _value in entries:
            newest = self._newest_sequence(key)
            if newest is not None and newest >= sequence:
                raise CorruptDatabaseError("Ein gespeicherter Eintrag ist neuer als die MANIFEST-Sequenz; die Welt wird nicht beschrieben.")
        record = encode_write_batch(sequence, entries)
        framed = frame_log_record(record, start % _LOG_BLOCK_SIZE)
        if self._metadata_bytes + start + len(framed) > _MAX_METADATA_BYTES:
            raise ValueError(t("Die Änderung ist zu groß für das Schreibprotokoll der Welt."))
        before = self._expected_token
        if self._resources.log is None:
            with suppress(OSError, MemoryError):
                before = super().content_token()
        # Stays set from log creation through in-memory bookkeeping: a failure
        # can leave an unsynced log or durable records the session does not see.
        # Either way, the caller must reopen before attempting another write.
        self._failed = True
        log = self._resources.log or self._open_log()
        self._write_attempt.reached_log = True
        try:
            log.append(framed)
            log.verify([*log.records, record])
        except BaseException:
            with suppress(Exception):
                log.truncate(start)
            raise
        log.records.append(record)
        for offset, (key, value) in enumerate(entries):
            if value is None:
                self._memtable[key] = (sequence + offset, _TYPE_DELETION, b"")
            else:
                self._memtable[key] = (sequence + offset, _TYPE_VALUE, value)
        self._last_sequence = last_sequence
        self._failed = False
        self._expected_token = None
        # Derive the expected state solely from the opened state and this WAL.
        # Never reread a global fingerprint here: an unrelated external change
        # could then be incorrectly certified as part of our batch.
        if before is not None and log.verified_digest is not None:
            with suppress(MemoryError):
                name = os.path.basename(log.path)
                metadata = tuple(entry for entry in before[1] if entry[0] != name)
                after = (before[0], (*metadata, (name, log.size, log.verified_digest)), before[2])
                self._last_change = CommittedDbChange(before, after, tuple(entries))
                self._expected_token = after

    def _open_log(self) -> _SessionLog:
        next_file_number = self._manifest.next_file_number
        assert next_file_number is not None  # Checked when the session opened.
        number = max(next_file_number, _highest_file_number(self._db_path) + 1)
        if number >= _MAX_FILE_NUMBER:
            # Native recovery must still be able to increment this uint64.
            raise CorruptDatabaseError(t("Der LevelDB-Dateinummernbereich ist erschöpft."))
        log = _SessionLog(os.path.join(self._db_path, f"{number:06d}.log"))
        self._resources.log = log
        _sync_directory(self._db_path)
        return log

    def close(self) -> None:
        with self._write_lock:
            try:
                super().close()
            finally:
                self._release()
