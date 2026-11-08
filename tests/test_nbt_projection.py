"""Discovery projection retains the full codec's validation contract."""

import struct

import pytest

from mcbe_editor import nbt


def sample():
    return nbt.CompoundTag(
        {
            "UniqueID": nbt.LongTag(-(2**63) + 1),
            "ignored": nbt.CompoundTag(
                {
                    "array": nbt.LongArrayTag([1, -(2**63)]),
                    "bytes": nbt.ByteArrayTag([0, -1]),
                    "ints": nbt.IntArrayTag([-(2**31), 0]),
                    "nested": nbt.ListTag([nbt.CompoundTag({"text": nbt.StringTag("Ä\\xff")})]),
                    "empty": nbt.ListTag([], 0),
                    "floating": nbt.DoubleTag(float("nan")),
                }
            ),
        }
    )


@pytest.mark.parametrize("little_endian", [True, False])
def test_projection_validates_and_retains_exact_selected_values(little_endian):
    raw = sample().save_to(little_endian=little_endian)
    projected = nbt.load(raw, little_endian=little_endian, root_fields=frozenset({"UniqueID"}))
    assert set(projected.tag) == {"UniqueID"}
    assert projected.tag["UniqueID"].py_data == -(2**63) + 1
    for end in range(len(raw)):
        with pytest.raises(nbt.NBTError):
            nbt.load(raw[:end], little_endian=little_endian, root_fields=frozenset({"UniqueID"}))


@pytest.mark.parametrize("limit,value", [("MAX_DEPTH", 1), ("MAX_NODES", 4)])
def test_ignored_fields_still_consume_complexity_budget(monkeypatch, limit, value):
    raw = sample().save_to()
    monkeypatch.setattr(nbt, limit, value)
    for fields in (None, frozenset({"UniqueID"})):
        with pytest.raises(nbt.NBTError):
            nbt.load(raw, root_fields=fields)


@pytest.mark.parametrize(
    "raw",
    [
        b"\x0a\0\0\x0a\x01\0x\x01\x01\0a\0\x01\x01\0a\0\0\0",  # duplicate nested name
        b"\x0a\0\0\x09\x01\0x\x0d\0\0\0\0\0",  # invalid empty-list type
        b"\x0a\0\0\x07\x01\0x" + struct.pack("<i", -1) + b"\0",
        b"\x0a\0\0\x0a\x01\0x\x0d\x01\0y\0\0",  # unknown nested tag
        b"\x0a\0\0\0extra",  # trailing bytes
    ],
)
def test_malformed_ignored_fields_are_rejected(raw):
    for fields in (None, frozenset()):
        with pytest.raises(nbt.NBTError):
            nbt.load(raw, root_fields=fields)
