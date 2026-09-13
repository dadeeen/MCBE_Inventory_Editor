"""Binary codec contracts independent of optional third-party NBT libraries."""

import copy
import struct

import pytest

from mcbe_editor import nbt


@pytest.mark.parametrize("little_endian", [True, False])
def test_all_tag_types_roundtrip(little_endian):
    root = nbt.CompoundTag({
        "byte": nbt.ByteTag(-128), "short": nbt.ShortTag(-32768),
        "int": nbt.IntTag(2147483647), "long": nbt.LongTag(-(2**63)),
        "float": nbt.FloatTag(-0.0), "double": nbt.DoubleTag(1.25),
        "bytes": nbt.ByteArrayTag([-128, 0, 127]),
        "ints": nbt.IntArrayTag([-(2**31), 0, 2**31 - 1]),
        "longs": nbt.LongArrayTag([-(2**63), 0, 2**63 - 1]),
        "text": nbt.StringTag("Grüße\x00世界😀"),
        "list": nbt.ListTag([nbt.CompoundTag({"x": nbt.IntTag(7)})]),
        **{f"empty{i}": nbt.ListTag([], i) for i in range(13)},
    })
    raw = nbt.NamedTag(root, "root").save_to(little_endian=little_endian)
    parsed = nbt.load(raw, little_endian=little_endian)
    assert parsed.save_to(little_endian=little_endian) == raw
    assert parsed.tag == root
    for key, value in root.items():
        assert type(parsed.tag[key]) is type(value)


@pytest.mark.parametrize("tag_id,bits", [(5, "0100807f"), (5, "0100c07f"), (6, "010000000000f07f")])
def test_nan_payload_is_not_normalized(tag_id, bits):
    raw = bytes([tag_id, 0, 0]) + bytes.fromhex(bits)
    assert nbt.load(raw).save_to() == raw


@pytest.mark.parametrize("raw_string", [bytes(range(256)), b"\x00\xff\xed\xa0\x80", "␛xff".encode()])
def test_original_string_bytes_survive_escape_collisions(raw_string):
    raw = b"\x08\x00\x00" + struct.pack("<H", len(raw_string)) + raw_string
    assert nbt.load(raw).save_to() == raw


def test_original_compound_name_bytes_survive():
    name = "␛xff".encode()
    raw = b"\x0a\x00\x00\x01" + struct.pack("<H", len(name)) + name + b"\x07\x00"
    parsed = nbt.load(raw)
    parsed.tag["new"] = nbt.IntTag(3)
    del parsed.tag["new"]
    assert parsed.save_to() == raw


def test_every_truncated_prefix_is_rejected():
    raw = nbt.NamedTag(nbt.CompoundTag({"x": nbt.ListTag([nbt.IntTag(1)]), "s": nbt.StringTag("hello")})).save_to()
    for size in range(len(raw)):
        with pytest.raises(nbt.NBTError):
            nbt.load(raw[:size])


@pytest.mark.parametrize("raw", [
    b"\x0a\0\0\x01\x01\0x\x01\x01\x01\0x\x02\0",  # duplicate key
    b"\x09\0\0\x00\x01\0\0\0",  # nonempty TAG_End list
    b"\x09\0\0\x03\xff\xff\xff\xff",  # negative length
    b"\x07\0\0\xff\xff\xff\x7f",  # impossible array length
    b"\x0a\0\0\0junk",  # trailing data
    b"\x0d\0\0",  # unknown type
])
def test_ambiguous_or_malformed_data_is_rejected(raw):
    with pytest.raises(nbt.NBTError):
        nbt.load(raw)


def test_resource_limits_and_cycles_fail_closed(monkeypatch):
    monkeypatch.setattr(nbt, "MAX_DEPTH", 8)
    root = nbt.CompoundTag()
    root["cycle"] = root
    with pytest.raises(nbt.NBTError, match="complexity"):
        nbt.NamedTag(root).save_to()
    raw = b"\x0a\0\0" + b"\x0a\x01\0x" * 9 + b"\0" * 10
    with pytest.raises(nbt.NBTError, match="complexity"):
        nbt.load(raw)
    monkeypatch.setattr(nbt, "MAX_BYTES", 3)
    with pytest.raises(nbt.NBTError, match="size"):
        nbt.load(b"\x0a\0\0\0")


def test_copies_and_list_mutations_preserve_types():
    inner = nbt.CompoundTag({"x": nbt.IntTag(1)})
    original = nbt.CompoundTag({"child": inner})
    cloned = original.copy()
    del cloned["child"]
    assert original["child"] is inner
    items = nbt.ListTag([], 10)
    assert items.copy().list_data_type == 10
    items.append(inner)
    with pytest.raises(TypeError):
        items.append(nbt.IntTag(1))
    assert len(items) == 1


@pytest.mark.parametrize("tag", [nbt.ByteTag(0), nbt.IntTag(0), nbt.FloatTag(-0.0), nbt.StringTag("")])
def test_empty_scalar_tags_are_false(tag):
    assert not tag
    assert bool(type(tag)("x" if isinstance(tag, nbt.StringTag) else 1))


def test_empty_list_slice_infers_type_and_failed_assignment_is_atomic():
    items = nbt.ListTag([], 10)
    with pytest.raises(TypeError):
        items[:] = [nbt.IntTag(1), nbt.StringTag("mixed")]
    assert len(items) == 0
    assert items.list_data_type == 10
    items[:] = [nbt.IntTag(1)]
    assert items.list_data_type == 3
    assert nbt.load(items.save_to()).tag[0].py_data == 1


def test_custom_encoder_applies_to_loaded_values_and_names():
    raw = nbt.NamedTag(nbt.CompoundTag({"key": nbt.StringTag("value")}), "root").save_to()
    encoded = nbt.load(raw).save_to(string_encoder=lambda value: value.upper().encode("utf-8"))
    result = nbt.load(encoded)
    assert result.name == "ROOT"
    assert result.tag["KEY"].py_data == "VALUE"


@pytest.mark.parametrize("cls", [nbt.ByteArrayTag, nbt.IntArrayTag, nbt.LongArrayTag])
def test_array_elements_share_the_total_read_and_write_budget(monkeypatch, cls):
    tag = nbt.CompoundTag({"a": cls([1, 2, 3]), "b": cls([4, 5, 6])})
    raw = tag.save_to()
    monkeypatch.setattr(nbt, "MAX_NODES", 8)  # root + two arrays + six elements = nine
    with pytest.raises(nbt.NBTError, match="complexity"):
        nbt.load(raw)
    with pytest.raises(nbt.NBTError, match="complexity"):
        tag.save_to()
    monkeypatch.setattr(nbt, "MAX_NODES", 9)
    assert nbt.load(raw).save_to() == raw


def test_writer_rejects_arrays_the_reader_cannot_accept(monkeypatch):
    monkeypatch.setattr(nbt, "MAX_NODES", 4)
    with pytest.raises(nbt.NBTError, match="complexity"):
        nbt.ByteArrayTag(range(5)).save_to()


@pytest.mark.parametrize("layout", ["wide", "multidimensional", "strided"])
def test_memoryview_layouts_are_read_as_bytes(layout):
    raw = b"\x0a\0\0\0"
    if layout == "wide":
        view = memoryview(raw).cast("I")
    elif layout == "multidimensional":
        view = memoryview(raw).cast("B", shape=[2, 2])
    else:
        interleaved = bytearray(len(raw) * 2)
        interleaved[::2] = raw
        view = memoryview(interleaved)[::2]
    assert nbt.load(view).save_to() == raw


def test_memoryview_limit_counts_bytes_before_parsing(monkeypatch):
    monkeypatch.setattr(nbt, "MAX_BYTES", 3)
    with pytest.raises(nbt.NBTError, match="size"):
        nbt.load(memoryview(b"\x0a\0\0\0").cast("I"))


@pytest.mark.parametrize("container", ["compound", "list"])
@pytest.mark.parametrize("operation", ["py_data", "value", "copy"])
def test_container_views_and_shallow_copies_detach_outer_storage(container, operation):
    child = nbt.CompoundTag({"x": nbt.IntTag(1)})
    original = nbt.CompoundTag({"child": child}) if container == "compound" else nbt.ListTag([child])
    key = "child" if container == "compound" else 0
    before = original.save_to()
    detached = copy.copy(original) if operation == "copy" else getattr(original, operation)
    assert detached[key] is child  # Shallow: nested tags intentionally remain shared.
    del detached[key]
    assert original.save_to() == before
    assert original[key] is child


def test_list_membership_requires_matching_nbt_type():
    items = nbt.ListTag([nbt.IntTag(1)])
    assert nbt.IntTag(1) in items
    assert nbt.IntTag(2) not in items
    assert nbt.ByteTag(1) not in items
    assert 1 not in items
