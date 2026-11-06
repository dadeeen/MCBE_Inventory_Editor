"""CRC backend equivalence and on-disk checksums with an independent oracle."""

import builtins
import importlib.util
import random
import struct
import sys
import types
import zlib

import pytest

from mcbe_editor import leveldb_readonly as reader
from mcbe_editor.leveldb_writer import frame_log_record
from tests.test_leveldb_readonly import _write_batch


def _reference_crc32c(data):
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 if crc & 1 else 0)
    return crc ^ 0xFFFFFFFF


def _stored_checksum(data):
    crc = _reference_crc32c(data)
    return ((((crc << 17) | (crc >> 15)) & 0xFFFFFFFF) + 0xA282EAD8) & 0xFFFFFFFF


def _log_record(payload):
    return struct.pack("<IHB", _stored_checksum(b"\x01" + payload), len(payload), 1) + payload


@pytest.fixture(params=["python", "native"])
def crc_backend(request, monkeypatch):
    if request.param == "python":
        monkeypatch.setattr(reader, "_native_crc32c", None)
    else:
        google_crc32c = pytest.importorskip("google_crc32c")
        if google_crc32c.implementation != "c":
            pytest.skip("google-crc32c's native extension is unavailable")
        monkeypatch.setattr(reader, "_native_crc32c", google_crc32c.value)

        def unexpected_fallback(_data):
            pytest.fail("Native checksum calculation unexpectedly used the Python fallback")

        monkeypatch.setattr(reader, "_crc32c_python", unexpected_fallback)
    return reader._crc32c


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"", 0x00000000),
        (b"123456789", 0xE3069283),
        (bytes(32), 0x8A9136AA),
        (b"\xff" * 32, 0x62A8AB43),
        (bytes(range(32)), 0x46DD794E),
        (bytes(range(31, -1, -1)), 0x113FDB5C),
    ],
)
def test_both_backends_match_standard_and_rfc3720_vectors(crc_backend, data, expected):
    assert _reference_crc32c(data) == expected
    assert crc_backend(data) == expected


@pytest.mark.parametrize("seed", [0, 3720])
def test_buffers_and_block_boundaries_match_independent_oracle(crc_backend, seed):
    rng = random.Random(seed)
    lengths = [0, 1, 2, 3, 4, 5, 7, 8, 15, 16, 17, 31, 32, 33, 255, 256, 257, 4095, 4096, 4097, 32760, 32761, 32762, 65535, 65536, 65537]
    for length in lengths:
        payload = rng.randbytes(length)
        expected = _reference_crc32c(payload)
        assert crc_backend(payload) == expected
        assert crc_backend(bytearray(payload)) == expected
        # Include unaligned, read-only and writable slices of larger buffers.
        offset = length % 8
        padded = b"\xff" * offset + payload + b"\x80"
        for buffer in (padded, bytearray(padded)):
            assert crc_backend(memoryview(buffer)[offset : offset + length]) == expected


@pytest.mark.parametrize("layout", ["strided", "typed", "multidimensional"])
def test_memoryview_layouts_have_the_same_checksum_with_either_backend(crc_backend, layout):
    data = memoryview(bytes(range(128, 160)))
    if layout == "strided":
        data = data[::2]
    elif layout == "typed":
        data = data.cast("I")
    else:
        data = data.cast("B", shape=[4, 8])
    assert crc_backend(data) == _reference_crc32c(data.tobytes())


@pytest.mark.parametrize("invalid", [3, [1, 2, 3], "123456789", None])
def test_backends_reject_non_buffer_inputs(crc_backend, invalid):
    with pytest.raises(TypeError):
        crc_backend(invalid)


@pytest.mark.parametrize("size", [0, 32761, 70000])
def test_writer_physical_records_have_independently_verified_checksums(crc_backend, size):
    payload = random.Random(size).randbytes(size)
    framed = frame_log_record(payload, 0)
    fragments = []
    kinds = []
    for start in range(0, len(framed), 32768):
        checksum, length, kind = struct.unpack_from("<IHB", framed, start)
        assert length <= 32768 - 7
        fragment = framed[start + 7 : start + 7 + length]
        assert len(fragment) == length
        assert checksum == _stored_checksum(bytes([kind]) + fragment)
        fragments.append(fragment)
        kinds.append(kind)
    assert b"".join(fragments) == payload
    assert kinds == ([1] if len(kinds) == 1 else [2, *([3] * (len(kinds) - 2)), 4])
    assert list(reader._iter_log_records(framed)) == [payload]


@pytest.mark.parametrize("block_offset", [0, 32760, 32761, 32762, 32767])
def test_writer_native_and_python_outputs_are_byte_identical(monkeypatch, block_offset):
    google_crc32c = pytest.importorskip("google_crc32c")
    if google_crc32c.implementation != "c":
        pytest.skip("google-crc32c's native extension is unavailable")
    payload = bytes(range(256)) * 257
    monkeypatch.setattr(reader, "_native_crc32c", None)
    expected = frame_log_record(payload, block_offset)
    monkeypatch.setattr(reader, "_native_crc32c", google_crc32c.value)
    assert frame_log_record(payload, block_offset) == expected


@pytest.mark.parametrize("compression", [0, 2, 4])
@pytest.mark.parametrize("damage", ["payload", "compression", "checksum"])
def test_sst_crc_includes_payload_and_compression_type(crc_backend, compression, damage):
    payload = b"Bedrock inventory\0" * 64 + bytes(range(256))
    encoded = payload if compression == 0 else zlib.compress(payload, wbits=15 if compression == 2 else -15)
    stored = encoded + bytes([compression])
    raw = stored + struct.pack("<I", _stored_checksum(stored))
    assert reader._decompress_block(raw) == payload
    corrupted = bytearray(raw)
    corrupted[{"payload": 0, "compression": -5, "checksum": -1}[damage]] ^= 0x80
    with pytest.raises(reader.CorruptDatabaseError, match="CRC"):
        reader._decompress_block(bytes(corrupted))


@pytest.mark.parametrize("case", ["valid", "manifest", "interior_wal", "newest_wal_tail"])
def test_manifest_and_wal_integrity_and_recovery_remain_readonly(crc_backend, tmp_path, caplog, case):
    manifest = bytearray(_log_record(b"\x02\x02"))
    good = _log_record(_write_batch(1, [(b"player", b"saved")]))
    latest = bytearray(_log_record(_write_batch(2, [(b"player", b"latest")])))
    if case == "manifest":
        manifest[0] ^= 1
    if case in {"interior_wal", "newest_wal_tail"}:
        latest[0] ^= 1
    wal = good + bytes(latest) + (good if case == "interior_wal" else b"")
    (tmp_path / "CURRENT").write_bytes(b"MANIFEST-000001\n")
    (tmp_path / "MANIFEST-000001").write_bytes(manifest)
    (tmp_path / "000002.log").write_bytes(wal)

    def snapshot():
        return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.iterdir()}

    before = snapshot()
    if case in {"manifest", "interior_wal"}:
        with pytest.raises(reader.CorruptDatabaseError, match="CRC"):
            reader.ReadonlyLevelDbAdapter(str(tmp_path))
    else:
        db = reader.ReadonlyLevelDbAdapter(str(tmp_path))
        try:
            expected = b"saved" if case == "newest_wal_tail" else b"latest"
            assert db.get(b"player") == expected
            assert dict(db.iter_items()) == {b"player": expected}
        finally:
            db.close()
        if case == "newest_wal_tail":
            assert "CRC-fehlerhafter WAL-Schlussrecord" in caplog.text
    assert snapshot() == before


def _isolated_reader(monkeypatch, *, google_module=None, import_error=None):
    """Exercise real import-time selection without reloading the shared reader."""
    original_import = builtins.__import__

    def controlled_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "google_crc32c":
            if import_error is not None:
                raise import_error("native CRC extension is unavailable")
            return google_module
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", controlled_import)
    name = "mcbe_editor._crc_backend_test"
    spec = importlib.util.spec_from_file_location(name, reader.__file__)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("import_error", [ModuleNotFoundError, OSError, None], ids=["not-installed", "extension-unloadable", "python-only"])
def test_import_falls_back_when_native_extension_is_unavailable(monkeypatch, import_error):
    google_module = types.ModuleType("google_crc32c")
    google_module.implementation = "python"

    def unwanted_python_backend(_data):
        pytest.fail("The slower third-party Python backend must not replace the existing fallback")

    google_module.value = unwanted_python_backend
    module = _isolated_reader(monkeypatch, google_module=google_module, import_error=import_error)
    assert module._native_crc32c is None
    for payload in (b"", b"123456789", bytes(range(256))):
        assert module._crc32c(payload) == _reference_crc32c(payload)


def test_native_selection_normalizes_buffers_without_copying_bytes(monkeypatch):
    google_module = types.ModuleType("google_crc32c")
    google_module.implementation = "c"
    calls = []

    def native_value(data):
        assert isinstance(data, bytes)
        calls.append(data)
        return _reference_crc32c(data)

    google_module.value = native_value
    module = _isolated_reader(monkeypatch, google_module=google_module)
    payload = b"123456789"
    assert module._crc32c(payload) == 0xE3069283
    assert calls[0] is payload
    assert module._crc32c(bytearray(payload)) == 0xE3069283
    assert module._crc32c(memoryview(b"_" + payload)[1:]) == 0xE3069283
    assert len(calls) == 3
    assert module._crc32c_word_tables.cache_info().currsize == 0


def test_native_calculation_errors_are_not_hidden_by_fallback(monkeypatch):
    def failed_native(_data):
        raise RuntimeError("native checksum failure")

    monkeypatch.setattr(reader, "_native_crc32c", failed_native)
    with pytest.raises(RuntimeError, match="native checksum failure"):
        reader._crc32c(b"123456789")
