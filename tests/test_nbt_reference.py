"""Optional independent oracle; CI runs this explicitly on Python 3.12.

The normal application suite never needs Amulet-NBT. This separate comparison
must be run with the reference lock installed before approving codec changes.
"""

import random
from pathlib import Path

import pytest

from mcbe_editor import nbt

reference = pytest.importorskip("amulet_nbt", reason="Independent NBT oracle runs on Python 3.12")


def _random_tag(rng, depth=0):
    ids = list(range(1, 13)) if depth < 4 else [1, 2, 3, 4, 5, 6, 7, 8, 11, 12]
    tag_id = rng.choice(ids)
    cls = nbt._TYPES[tag_id]
    if tag_id <= 4:
        return cls(rng.randrange(-(2 ** (cls.bits - 1)), 2 ** (cls.bits - 1)))
    if tag_id <= 6:
        return cls(rng.uniform(-1e15, 1e15))
    if tag_id == 8:
        return cls(rng.choice(["", "\x00", "Grüße 世界 😀", "slashes\\x00", "line\nnext"]))
    if tag_id == 10:
        return cls({f"key{i}": _random_tag(rng, depth + 1) for i in range(rng.randrange(8))})
    if tag_id == 9:
        count = rng.randrange(5)
        tag = _random_tag(rng, depth + 1)
        return cls([tag.copy() for _ in range(count)], tag.tag_id)
    return cls(rng.randrange(-100, 100) for _ in range(rng.randrange(20)))


@pytest.mark.parametrize("little_endian", [True, False])
def test_randomized_bidirectional_reference_roundtrips(little_endian):
    rng = random.Random(20260912)
    for _ in range(500):
        raw = nbt.NamedTag(_random_tag(rng), "root").save_to(little_endian=little_endian)
        old = reference.load(raw, compressed=False, little_endian=little_endian, string_decoder=reference.utf8_escape_decoder)
        old_raw = old.save_to(compressed=False, little_endian=little_endian, string_encoder=reference.utf8_escape_encoder)
        assert old_raw == raw
        assert nbt.load(old_raw, little_endian=little_endian).save_to(little_endian=little_endian) == old_raw


def test_every_empty_list_type_matches_reference():
    for tag_id in range(13):
        old = reference.NamedTag(reference.ListTag([], tag_id))
        raw = old.save_to(compressed=False, little_endian=True)
        assert nbt.load(raw).save_to() == raw
        assert nbt.load(raw).tag.list_data_type == tag_id


def test_reviewed_entity_records_match_reference():
    files = list((Path(__file__).parent / "data").glob("*.hex"))
    assert files, "Reviewed reference records must be present"
    for path in files:
        raw = bytes.fromhex(path.read_text())
        new = nbt.load(raw)
        old = reference.load(raw, compressed=False, little_endian=True, string_decoder=reference.utf8_escape_decoder)
        assert new.save_to() == raw
        assert old.save_to(compressed=False, little_endian=True, string_encoder=reference.utf8_escape_encoder) == raw
