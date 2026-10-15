"""Malformed export files must remain validation errors at the import boundary."""

import json
import struct
import zipfile

import pytest

from mcbe_editor import nbt, players
from tests.nbt_fixtures import make_minimal_player_tag


def _write_export(path, compression=zipfile.ZIP_DEFLATED):
    raw = nbt.NamedTag(make_minimal_player_tag()).save_to(compressed=False, little_endian=True)
    manifest = {"format": players.EXPORT_FORMAT, "version": players.EXPORT_VERSION, "nbt": {"byte_length": len(raw)}}
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("preview.json", "{}")
        archive.writestr("player.nbt", raw)
    return manifest, {}, raw


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_supported_player_exports_remain_readable(tmp_path, compression):
    if compression == zipfile.ZIP_BZIP2:
        pytest.importorskip("bz2")
    elif compression == zipfile.ZIP_LZMA:
        pytest.importorskip("lzma")
    path = tmp_path / "player.zip"
    expected = _write_export(path, compression)
    assert players.read_player_export(path) == expected


@pytest.mark.parametrize("damage", ["deflate", "bzip2", "lzma", "compression", "version", "filename_encoding", "encrypted", "crc"])
def test_damaged_player_export_is_a_validation_error(tmp_path, damage):
    compression = zipfile.ZIP_DEFLATED
    if damage == "bzip2":
        pytest.importorskip("bz2")
        compression = zipfile.ZIP_BZIP2
    elif damage == "lzma":
        pytest.importorskip("lzma")
        compression = zipfile.ZIP_LZMA
    path = tmp_path / "player.zip"
    _write_export(path, compression)
    raw = bytearray(path.read_bytes())
    local, central = raw.index(b"PK\x03\x04"), raw.index(b"PK\x01\x02")
    name, extra = struct.unpack_from("<HH", raw, local + 26)
    data_offset = local + 30 + name + extra
    if damage == "deflate":
        raw[data_offset] = 7  # Invalid DEFLATE block type.
    elif damage in {"bzip2", "lzma"}:
        raw[data_offset + (4 if damage == "lzma" else 0)] ^= 0xFF
    elif damage == "compression":
        struct.pack_into("<H", raw, local + 8, 99)
        struct.pack_into("<H", raw, central + 10, 99)
    elif damage == "version":
        struct.pack_into("<H", raw, local + 4, 99)
        struct.pack_into("<H", raw, central + 6, 99)
    elif damage == "filename_encoding":
        struct.pack_into("<H", raw, local + 6, 0x800)
        struct.pack_into("<H", raw, central + 8, 0x800)
        raw[local + 30] = raw[central + 46] = 0xFF
    elif damage == "encrypted":
        struct.pack_into("<H", raw, local + 6, 1)
        struct.pack_into("<H", raw, central + 8, 1)
    else:
        raw[central + 16] ^= 0xFF  # Incorrect member CRC.
    path.write_bytes(raw)

    with pytest.raises(ValueError, match="Spieler-Export"):
        players.read_player_export(path)
    assert path.read_bytes() == raw


def test_player_export_read_errors_hide_private_paths(tmp_path, monkeypatch):
    path = tmp_path / "player.zip"
    _write_export(path)

    def fail_read(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied", "/private/world/player.zip")

    monkeypatch.setattr(zipfile.ZipFile, "read", fail_read)
    with pytest.raises(ValueError, match="Spieler-Export") as caught:
        players.read_player_export(path)
    assert "/private/world" not in str(caught.value)


@pytest.mark.parametrize("error", [AssertionError, TypeError])
def test_player_export_reader_does_not_hide_programming_errors(tmp_path, monkeypatch, error):
    path = tmp_path / "player.zip"
    _write_export(path)

    def fail_read(*_args, **_kwargs):
        raise error("implementation bug")

    monkeypatch.setattr(zipfile.ZipFile, "read", fail_read)
    with pytest.raises(error, match="implementation bug"):
        players.read_player_export(path)
