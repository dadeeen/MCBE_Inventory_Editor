"""Pure-Python LevelDB writer: format, atomicity, locking and native agreement.

Tests marked ``native`` use amulet-leveldb (Mojang's LevelDB fork) as an
independent reference engine when it is installed.
"""

import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mcbe_editor import leveldb_writer
from mcbe_editor.leveldb_readonly import (
    _LOG_BLOCK_SIZE,
    _TAG_COMPARATOR,
    _TAG_LAST_SEQUENCE,
    _TAG_LOG_NUMBER,
    _TAG_NEXT_FILE_NUMBER,
    CorruptDatabaseError,
    ReadonlyLevelDbAdapter,
    _iter_log_records,
    _replay_wal,
)
from mcbe_editor.leveldb_writer import LevelDbWriter, encode_write_batch, frame_log_record
from mcbe_editor.service_errors import LevelDbInUseError, LevelDbUncleanLogError

try:
    import leveldb  # amulet-leveldb, optional reference engine
except ImportError:
    leveldb = None

ROOT = Path(__file__).resolve().parents[1]
native = pytest.mark.skipif(leveldb is None, reason="amulet-leveldb reference engine is not installed")


def _varint(value: int) -> bytes:
    return leveldb_writer._encode_varint(value)


def _snapshot(path: Path) -> dict[str, tuple[bytes, int]]:
    return {name: ((path / name).read_bytes(), (path / name).stat().st_mtime_ns) for name in sorted(os.listdir(path))}


def _read_all(path: Path) -> dict[bytes, bytes]:
    reader = ReadonlyLevelDbAdapter(str(path))
    try:
        return dict(reader.iter_items())
    finally:
        reader.close()


def _native_items(path: Path) -> dict[bytes, bytes]:
    db = leveldb.LevelDB(str(path))
    try:
        return dict(db.items())
    finally:
        db.close()


def _write(path: Path, *batches: dict[bytes, bytes | None]) -> None:
    writer = LevelDbWriter(str(path))
    try:
        for batch in batches:
            writer.put_batch(batch)
    finally:
        writer.close()


def _new_db(tmp_path: Path, name: str = "db") -> Path:
    path = tmp_path / name
    path.mkdir()
    return path


def _logs(path: Path) -> list[str]:
    return sorted(name for name in os.listdir(path) if name.endswith(".log"))


def _manifest(*fields: bytes) -> bytes:
    return frame_log_record(b"".join(fields), 0)


# --- Format ---------------------------------------------------------------


@pytest.mark.parametrize(
    "offset",
    [0, 7, 8, 1000, _LOG_BLOCK_SIZE - 14, _LOG_BLOCK_SIZE - 8, _LOG_BLOCK_SIZE - 7, _LOG_BLOCK_SIZE - 6, _LOG_BLOCK_SIZE - 1],
)
@pytest.mark.parametrize("size", [0, 1, 20, _LOG_BLOCK_SIZE - 7, _LOG_BLOCK_SIZE - 6, 2 * _LOG_BLOCK_SIZE, 100_000])
def test_frames_parse_back_from_every_block_position(offset, size):
    # Valid logs only have record boundaries at 0 or >= 7 inside a block.
    filler = b"f" * (offset - 7) if offset else b""
    prefix = frame_log_record(filler, 0) if offset else b""
    assert len(prefix) == offset
    record = random.Random(size).randbytes(size)

    framed = frame_log_record(record, offset)

    expected = [filler, record] if offset else [record]
    assert list(_iter_log_records(prefix + framed)) == expected


def test_write_batch_encoding_replays_values_deletions_and_sequences():
    batch = encode_write_batch(41, [(b"a", b"1"), (b"gone", None), (b"", b"empty key"), (b"b", b"")])
    memtable = {}

    last_sequence = _replay_wal(frame_log_record(batch, 0), memtable)

    assert last_sequence == 44
    assert memtable == {b"a": (41, 1, b"1"), b"gone": (42, 0, b""), b"": (43, 1, b"empty key"), b"b": (44, 1, b"")}


# --- Sessions -------------------------------------------------------------


def test_blank_directory_becomes_a_database_like_newdb(tmp_path):
    path = _new_db(tmp_path)

    _write(path, {b"a": b"1"}, {b"b": b"2", b"a": None})

    assert sorted(os.listdir(path)) == ["000002.log", "CURRENT", "LOCK", "MANIFEST-000001"]
    assert (path / "CURRENT").read_bytes() == b"MANIFEST-000001\n"
    assert _read_all(path) == {b"b": b"2"}


def test_a_directory_with_leftovers_but_no_current_is_not_initialized(tmp_path):
    path = _new_db(tmp_path)
    (path / "000005.ldb").write_bytes(b"stale table")

    with pytest.raises(FileNotFoundError, match="CURRENT fehlt"):
        LevelDbWriter(str(path))

    assert sorted(os.listdir(path)) == ["000005.ldb", "LOCK"]
    # The lock was released: a later session is not refused as "in use".
    with pytest.raises(FileNotFoundError):
        LevelDbWriter(str(path))


def test_opening_and_reading_without_writing_changes_nothing(tmp_path):
    path = _new_db(tmp_path)
    _write(path, {b"a": b"1", b"b": b"2"})
    before = _snapshot(path)

    writer = LevelDbWriter(str(path))
    try:
        assert writer.get(b"a") == b"1"
        assert dict(writer.iter_items()) == {b"a": b"1", b"b": b"2"}
        writer.put_batch({})
    finally:
        writer.close()

    assert _snapshot(path) == before


def test_each_session_appends_one_new_log_with_continuing_sequences(tmp_path):
    path = _new_db(tmp_path)
    _write(path, {b"a": b"1", b"b": b"old"})
    _write(path, {b"b": b"new", b"c": b"3"})
    writer = LevelDbWriter(str(path))
    try:
        writer.put(b"a", b"latest")
        writer.put_batch({b"c": None})
        # The session sees its own writes without reopening.
        assert dict(writer.iter_items()) == {b"a": b"latest", b"b": b"new"}
        with pytest.raises(KeyError):
            writer.get(b"c")
    finally:
        writer.close()

    assert _logs(path) == ["000002.log", "000003.log", "000004.log"]
    assert _read_all(path) == {b"a": b"latest", b"b": b"new"}
    reader = ReadonlyLevelDbAdapter(str(path))
    try:
        assert reader._last_sequence == 6
    finally:
        reader.close()


def test_writer_view_matches_a_fresh_reader_after_every_batch(tmp_path):
    path = _new_db(tmp_path)
    rng = random.Random(7)
    writer = LevelDbWriter(str(path))
    try:
        for _ in range(25):
            batch = {}
            for _ in range(rng.randrange(1, 6)):
                key = b"k%02d" % rng.randrange(30)
                batch[key] = None if rng.random() < 0.25 else rng.randbytes(rng.randrange(0, 40_000))
            writer.put_batch(batch)
            assert dict(writer.iter_items()) == _read_all(path)
    finally:
        writer.close()


# --- Refusals -------------------------------------------------------------


def test_torn_newest_log_blocks_writes_until_the_engine_recovers(tmp_path, caplog):
    path = _new_db(tmp_path)
    _write(path, {b"a": b"1"}, {b"b": b"x" * 5000})
    log = path / _logs(path)[-1]
    log.write_bytes(log.read_bytes()[:-10])
    before = _snapshot(path)

    with pytest.raises(LevelDbUncleanLogError):
        LevelDbWriter(str(path))

    assert _snapshot(path) == before
    # Reading tolerates the torn tail exactly like the engine's recovery.
    assert _read_all(path) == {b"a": b"1"}
    assert "verworfen" in caplog.text


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ((_varint(_TAG_COMPARATOR) + _varint(5) + b"other" + _varint(_TAG_LOG_NUMBER) + _varint(0)
          + _varint(_TAG_NEXT_FILE_NUMBER) + _varint(2) + _varint(_TAG_LAST_SEQUENCE) + _varint(0)), "Comparator"),
        ((_varint(_TAG_LOG_NUMBER) + _varint(0) + _varint(_TAG_LAST_SEQUENCE) + _varint(0)), "Sequenzzähler"),
        ((_varint(_TAG_LOG_NUMBER) + _varint(0) + _varint(_TAG_NEXT_FILE_NUMBER) + _varint(2)), "Sequenzzähler"),
    ],
)
def test_manifests_the_engine_would_reject_are_not_written(tmp_path, fields, message):
    path = _new_db(tmp_path)
    (path / "MANIFEST-000001").write_bytes(_manifest(fields))
    (path / "CURRENT").write_bytes(b"MANIFEST-000001\n")

    with pytest.raises(CorruptDatabaseError, match=message):
        LevelDbWriter(str(path))

    assert _logs(path) == []


def test_a_second_session_of_the_same_process_is_refused(tmp_path):
    path = _new_db(tmp_path)
    _write(path, {b"a": b"1"})
    first = LevelDbWriter(str(path))
    try:
        for alias in (str(path), str(path) + os.sep, os.path.join(str(path.parent), ".", path.name)):
            with pytest.raises(LevelDbInUseError):
                LevelDbWriter(alias)
    finally:
        first.close()
    _write(path, {b"a": b"2"})
    assert _read_all(path) == {b"a": b"2"}


_HOLD_WRITER = """
import sys
sys.path.insert(0, sys.argv[1])
from mcbe_editor.leveldb_writer import LevelDbWriter
writer = LevelDbWriter(sys.argv[2])
print("ready", flush=True)
sys.stdin.readline()
writer.close()
"""

_TRY_WRITER = """
import sys
sys.path.insert(0, sys.argv[1])
from mcbe_editor.leveldb_writer import LevelDbWriter
from mcbe_editor.service_errors import LevelDbInUseError
try:
    LevelDbWriter(sys.argv[2]).close()
except LevelDbInUseError:
    sys.exit(3)
"""


def _hold(script: str, path: Path) -> subprocess.Popen:
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(ROOT), str(path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    assert child.stdout.readline().strip() == "ready"
    return child


def _release(child: subprocess.Popen) -> None:
    child.communicate("done\n", timeout=30)
    assert child.returncode == 0


def test_a_session_of_another_process_is_refused_until_it_closes(tmp_path):
    path = _new_db(tmp_path)
    _write(path, {b"a": b"1"})
    holder = _hold(_HOLD_WRITER, path)
    try:
        with pytest.raises(LevelDbInUseError):
            LevelDbWriter(str(path))
        other = subprocess.run([sys.executable, "-c", _TRY_WRITER, str(ROOT), str(path)], timeout=30)
        assert other.returncode == 3
    finally:
        _release(holder)
    _write(path, {b"a": b"2"})
    assert _read_all(path) == {b"a": b"2"}


@pytest.mark.skipif(os.name != "nt", reason="POSIX cannot see open files of other programs")
@pytest.mark.parametrize("held", ["manifest", "log"])
def test_a_file_another_program_keeps_open_for_writing_blocks_the_writer(tmp_path, held):
    path = _new_db(tmp_path)
    _write(path, {b"a": b"1"})
    name = next(n for n in os.listdir(path) if n.startswith("MANIFEST-")) if held == "manifest" else _logs(path)[-1]
    before = _snapshot(path)
    # A running engine can hold its MANIFEST and log for writing without
    # holding CURRENT or locking LOCK, e.g. BDS behind a Docker Desktop bind
    # mount. Share modes apply per handle, so this process can stand in for it.
    with open(path / name, "ab"):
        with pytest.raises(LevelDbInUseError):
            LevelDbWriter(str(path))
        assert _snapshot(path) == before
    _write(path, {b"b": b"2"})
    assert _read_all(path) == {b"a": b"1", b"b": b"2"}


def _fail_the_next_fsync(monkeypatch):
    real_fsync = os.fsync
    calls = []

    def failing_fsync(descriptor):
        calls.append(descriptor)
        if len(calls) == 1:
            raise OSError("simulated device failure")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", failing_fsync)
    return OSError


def _corrupt_the_next_append(monkeypatch):
    # The device reports success but stores a flipped bit; only the read-back
    # check after the append can notice.
    real_append = leveldb_writer._SessionLog.append

    def corrupting_append(self, framed):
        monkeypatch.setattr(leveldb_writer._SessionLog, "append", real_append)
        real_append(self, framed[:-1] + bytes((framed[-1] ^ 0x01,)))

    monkeypatch.setattr(leveldb_writer._SessionLog, "append", corrupting_append)
    return CorruptDatabaseError


@pytest.mark.parametrize("inject_failure", [_fail_the_next_fsync, _corrupt_the_next_append], ids=["fsync", "read-back"])
def test_failed_append_is_rolled_back_and_ends_the_session(tmp_path, monkeypatch, inject_failure):
    path = _new_db(tmp_path)
    writer = LevelDbWriter(str(path))
    try:
        writer.put_batch({b"a": b"1"})
        size = (path / "000002.log").stat().st_size
        expected_error = inject_failure(monkeypatch)
        with pytest.raises(expected_error):
            writer.put_batch({b"a": b"2", b"b": b"3"})
        monkeypatch.undo()

        assert (path / "000002.log").stat().st_size == size
        with pytest.raises(RuntimeError, match="fehlgeschlagenen Schreibversuch"):
            writer.put_batch({b"c": b"4"})
        assert writer.get(b"a") == b"1"
    finally:
        writer.close()
    assert _read_all(path) == {b"a": b"1"}


@pytest.mark.parametrize("ahead", [0, 10**6], ids=["same-sequence", "far-ahead"])
def test_versions_newer_than_the_manifest_sequence_are_not_shadowed(tmp_path, monkeypatch, ahead):
    path = _new_db(tmp_path)
    _write(path, {b"a": b"1"})
    before = _snapshot(path)
    # A stored version with the batch's own sequence would be ambiguous for the
    # engine, so it must be refused just like a newer one.
    monkeypatch.setattr(LevelDbWriter, "_newest_sequence", lambda self, key: self._last_sequence + 1 + ahead)
    writer = LevelDbWriter(str(path))
    try:
        with pytest.raises(CorruptDatabaseError, match="neuer als die MANIFEST-Sequenz"):
            writer.put_batch({b"a": b"2"})
    finally:
        writer.close()
    assert _snapshot(path) == before


def test_batches_beyond_the_reader_budget_are_refused_before_touching_the_world(tmp_path, monkeypatch):
    path = _new_db(tmp_path)
    _write(path, {b"a": b"1"})
    before = _snapshot(path)
    monkeypatch.setattr(leveldb_writer, "_MAX_METADATA_BYTES", sum(len(data) for data, _mtime in before.values()) + 100)
    writer = LevelDbWriter(str(path))
    try:
        with pytest.raises(ValueError, match="zu groß"):
            writer.put_batch({b"b": b"x" * 1000})
        writer.put_batch({b"b": b"small"})
    finally:
        writer.close()
    assert _read_all(path) == {b"a": b"1", b"b": b"small"}


# --- Atomicity ------------------------------------------------------------


def _torn_copies(tmp_path: Path, path: Path, cut_points: list[int]):
    log_name = _logs(path)[-1]
    data = (path / log_name).read_bytes()
    for cut in cut_points:
        copy = tmp_path / f"cut-{cut}"
        shutil.copytree(path, copy)
        (copy / log_name).write_bytes(data[:cut])
        yield cut, copy


def test_a_torn_batch_applies_completely_or_not_at_all(tmp_path):
    path = _new_db(tmp_path)
    first = {b"a": b"1", b"big": b"old"}
    second = {b"a": None, b"big": random.Random(1).randbytes(3 * _LOG_BLOCK_SIZE), b"c": b"3"}
    _write(path, first)
    before = _read_all(path)
    writer = LevelDbWriter(str(path))
    try:
        writer.put_batch({b"x": b"small"})
        start = writer._resources.log.size
        writer.put_batch(second)
        end = writer._resources.log.size
    finally:
        writer.close()
    after = _read_all(path)
    assert after == {b"big": second[b"big"], b"c": b"3", b"x": b"small"}

    boundaries = {start + 1, start + 7, end - 1}
    for block in range(start // _LOG_BLOCK_SIZE + 1, end // _LOG_BLOCK_SIZE + 1):
        boundaries.update({block * _LOG_BLOCK_SIZE + delta for delta in (-1, 0, 1, 7, 8)})
    cuts = sorted(cut for cut in boundaries | set(range(start + 1, end, 4099)) if start < cut < end)
    for _cut, copy in _torn_copies(tmp_path, path, cuts):
        assert _read_all(copy) == {**before, b"x": b"small"}


# --- Native reference engine ---------------------------------------------


def _record_len_for(offset: int, target: int) -> int:
    """Value length whose single-key batch ends exactly at ``target`` in the block."""

    for varint_len in (1, 2, 3):
        value_len = target - offset - 7 - 15 - varint_len
        if value_len >= 0 and len(_varint(value_len)) == varint_len:
            return value_len
    raise AssertionError("no value length reaches the target")


@native
def test_log_bytes_equal_the_native_engine_for_identical_batches(tmp_path):
    base = _new_db(tmp_path, "base")
    leveldb.LevelDB(str(base), True).close()
    ours = tmp_path / "ours"
    shutil.copytree(base, ours)

    # Drive the log through every framing case: zero trailers, a header that
    # exactly fits (empty FIRST fragment), multi-block records, exact block ends.
    batches: list[dict[bytes, bytes | None]] = []
    offset = 0
    for target in (_LOG_BLOCK_SIZE - 3, _LOG_BLOCK_SIZE - 7):
        batches.append({b"k": b"v" * _record_len_for(offset, target)})
        offset = 0
    batches += [
        {b"huge": bytes(range(256)) * 400},
        {b"k": None},
        {b"a": b"1", b"b": b"", b"gone": None, b"c": b"3" * 200},
    ]
    native_db = leveldb.LevelDB(str(base))
    try:
        for batch in batches:
            native_db.putBatch(batch)
        native_db.put(b"single", b"put")
    finally:
        native_db.close()
    writer = LevelDbWriter(str(ours))
    try:
        for batch in batches:
            writer.put_batch(batch)
        writer.put(b"single", b"put")
    finally:
        writer.close()

    native_log = max((base / name for name in _logs(base)), key=lambda log: log.stat().st_size)
    our_log = ours / _logs(ours)[-1]
    assert our_log.read_bytes() == native_log.read_bytes()


@native
def test_native_engine_opens_a_database_created_from_a_blank_directory(tmp_path):
    path = _new_db(tmp_path)
    _write(path, {b"a": b"1", b"b": b"2"}, {b"a": None})

    assert _native_items(path) == {b"b": b"2"}
    # Native recovery moved the log into its tables; reading still agrees.
    assert _read_all(path) == {b"b": b"2"}
    _write(path, {b"c": b"3"})
    assert _native_items(path) == _read_all(path) == {b"b": b"2", b"c": b"3"}


@native
def test_random_sessions_of_both_engines_agree_with_a_model(tmp_path):
    rng = random.Random(20260925)
    path = _new_db(tmp_path)
    model = {b"key%05d" % i: rng.randbytes(rng.randrange(0, 600)) for i in range(4000)}
    seed = leveldb.LevelDB(str(path), True)
    try:
        seed.putBatch(model)
    finally:
        seed.close(compact=True)

    for session in range(10):
        batches = []
        for _ in range(rng.randrange(1, 4)):
            batch: dict[bytes, bytes | None] = {}
            for _ in range(rng.randrange(1, 40)):
                key = b"key%05d" % rng.randrange(4500)
                roll = rng.random()
                batch[key] = None if roll < 0.2 else rng.randbytes(rng.randrange(0, 90_000 if roll > 0.97 else 800))
            batches.append(batch)
        if session % 3 == 2:
            db = leveldb.LevelDB(str(path))
            try:
                for batch in batches:
                    db.putBatch(batch)
            finally:
                db.close(compact=session % 2 == 0)
        else:
            _write(path, *batches)
        for batch in batches:
            for key, value in batch.items():
                if value is None:
                    model.pop(key, None)
                else:
                    model[key] = value
        assert _read_all(path) == model

    assert _native_items(path) == model
    assert _read_all(path) == model


@native
def test_native_engine_applies_a_torn_batch_of_ours_completely_or_not_at_all(tmp_path):
    path = _new_db(tmp_path)
    _write(path, {b"a": b"1"})
    writer = LevelDbWriter(str(path))
    try:
        start = writer._resources.log.size if writer._resources.log else 0
        writer.put_batch({b"a": None, b"big": b"B" * (2 * _LOG_BLOCK_SIZE), b"c": b"3"})
        end = writer._resources.log.size
    finally:
        writer.close()

    cuts = [start + 1, start + 7, _LOG_BLOCK_SIZE - 1, _LOG_BLOCK_SIZE + 3, 2 * _LOG_BLOCK_SIZE + 8, end - 1]
    for _cut, copy in _torn_copies(tmp_path, path, [cut for cut in cuts if start < cut < end]):
        assert _native_items(copy) == {b"a": b"1"}
    assert _native_items(path) == {b"big": b"B" * (2 * _LOG_BLOCK_SIZE), b"c": b"3"}


_HOLD_NATIVE = """
import sys
import leveldb
db = leveldb.LevelDB(sys.argv[2])
print("ready", flush=True)
sys.stdin.readline()
db.close()
"""

_OPEN_NATIVE = "import leveldb, sys; leveldb.LevelDB(sys.argv[1]).close()"


@native
def test_a_running_native_engine_blocks_the_writer(tmp_path):
    path = _new_db(tmp_path)
    leveldb.LevelDB(str(path), True).close()
    holder = _hold(_HOLD_NATIVE, path)
    try:
        with pytest.raises(LevelDbInUseError):
            LevelDbWriter(str(path))
    finally:
        _release(holder)
    _write(path, {b"a": b"1"})
    assert _native_items(path) == {b"a": b"1"}


@native
def test_a_writer_session_keeps_a_starting_native_engine_out(tmp_path):
    path = _new_db(tmp_path)
    _write(path, {b"a": b"1"})
    writer = LevelDbWriter(str(path))
    try:
        writer.put_batch({b"b": b"2"})
        before = sorted(os.listdir(path))
        child = subprocess.run([sys.executable, "-c", _OPEN_NATIVE, str(path)], capture_output=True, timeout=30)
        assert child.returncode != 0
        assert sorted(os.listdir(path)) == before
        writer.put_batch({b"c": b"3"})
    finally:
        writer.close()
    assert _native_items(path) == {b"a": b"1", b"b": b"2", b"c": b"3"}
