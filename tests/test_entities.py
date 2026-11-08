from __future__ import annotations

import struct

import pytest

from mcbe_editor import nbt
from mcbe_editor import entities
from mcbe_editor.bedrock_nbt import SAVE_KWARGS
from mcbe_editor.read_operation import ReadStoppedError, observe


class EntityDb:
    def __init__(self, records=()):
        self.records = dict(records)

    def iter_items(self):
        return iter(self.records.items())


def entity_tag(identity=1, *, identifier="minecraft:villager_v2", x=1.0, z=2.0):
    return nbt.CompoundTag(
        {
            "identifier": nbt.StringTag(identifier),
            "UniqueID": nbt.LongTag(identity),
            "Pos": nbt.ListTag([nbt.FloatTag(x), nbt.FloatTag(64), nbt.FloatTag(z)]),
            "Variant": nbt.IntTag(5),
            "TradeTier": nbt.IntTag(4),
            "TradeExperience": nbt.IntTag(250),
            "Attributes": nbt.ListTag(
                [
                    nbt.CompoundTag(
                        {
                            "Name": nbt.StringTag("minecraft:health"),
                            "Current": nbt.FloatTag(12),
                            "Min": nbt.FloatTag(0),
                            "Base": nbt.FloatTag(20),
                            "Max": nbt.FloatTag(20),
                            "DefaultMin": nbt.FloatTag(0),
                            "DefaultMax": nbt.FloatTag(20),
                        }
                    )
                ]
            ),
        }
    )


def add_actor(db, tag, *, suffix=b"12345678", chunk=(0, 0), dimension=None, with_index=True):
    key = b"actorprefix" + suffix
    db.records[key] = nbt.NamedTag(tag).save_to(**SAVE_KWARGS)
    if with_index:
        index = b"digp" + struct.pack("<ii", *chunk)
        if dimension is not None:
            index += struct.pack("<i", dimension)
        db.records[index] = db.records.get(index, b"") + suffix
    return key


def only_record(db):
    scan = entities.scan_entities(db, identifiers=frozenset({"minecraft:villager_v2", "minecraft:villager"}))
    assert len(scan.records) == 1
    return next(iter(scan.records.values()))


def codes(record):
    return {item["code"] for item in record.issues}


def test_index_dimension_and_negative_chunk_do_not_depend_on_actor_id_encoding():
    db = EntityDb()
    tag = entity_tag(9007199254740997, x=-0.5, z=-16)
    tag["LastDimensionId"] = nbt.IntTag(0)  # Previous dimension is not current context.
    key = add_actor(db, tag, suffix=b"\xff\x00\x80\x00\x01\x00\x00\x00", chunk=(-1, -1), dimension=2)
    record = only_record(db)
    assert record.key == key
    assert record.dimension == 2
    assert record.unique_id == "9007199254740997"
    assert record.issues == []
    assert record.id == entities.entity_id(key)


def test_id_collision_with_a_different_mob_is_detected_even_with_a_villager_filter():
    db = EntityDb()
    add_actor(db, entity_tag(42))
    add_actor(db, entity_tag(42, identifier="minecraft:cow"), suffix=b"abcdefgh")
    assert "duplicate_unique_id" in codes(only_record(db))


@pytest.mark.parametrize("field", ["identifier", "Identifier", "EntityIdentifier", "id", "Id"])
def test_projected_scan_matches_full_decode_with_collisions_and_false_positive_markers(monkeypatch, field):
    from mcbe_editor.villagers import scan_villagers

    db = EntityDb()
    add_actor(db, entity_tag(42))
    cow = entity_tag(42, identifier="minecraft:cow")
    cow[field] = cow.pop("identifier")
    add_actor(db, cow, suffix=b"abcdefgh")
    pig = entity_tag(123, identifier="minecraft:pig")
    pig["CustomName"] = nbt.StringTag("minecraft:villager_v2")
    add_actor(db, pig, suffix=b"87654321")
    optimized = scan_villagers(db)
    real_load = nbt.load

    def full_decode(value, **kwargs):
        kwargs.pop("root_fields", None)
        return real_load(value, **kwargs)

    monkeypatch.setattr(nbt, "load", full_decode)
    assert scan_villagers(db) == optimized


@pytest.mark.parametrize("variant", ["same_index", "other_chunk", "other_dimension"])
def test_duplicate_actor_reference_is_never_editable_evidence(variant):
    db = EntityDb()
    add_actor(db, entity_tag())
    key = b"digp" + struct.pack("<ii", 0, 0)
    if variant == "other_chunk":
        key = b"digp" + struct.pack("<ii", 1, 0)
    if variant == "other_dimension":
        key += struct.pack("<i", 1)
    db.records[key] = db.records.get(key, b"") + b"12345678"
    record = only_record(db)
    assert "duplicate_actor_reference" in codes(record)
    if variant == "other_dimension":
        assert record.dimension is None
        assert "ambiguous_dimension" in codes(record)


def test_orphan_actor_is_visible_with_unknown_dimension():
    db = EntityDb()
    add_actor(db, entity_tag(), with_index=False)
    record = only_record(db)
    assert record.dimension is None
    assert "orphan_actor" in codes(record)


@pytest.mark.parametrize("bad_key", [False, True])
def test_malformed_indexes_are_reported_and_affected_records_are_marked(bad_key):
    db = EntityDb()
    add_actor(db, entity_tag(), with_index=False)
    key = b"digp-bad" if bad_key else b"digp" + struct.pack("<ii", 0, 0)
    db.records[key] = b"12345678" + (b"tail" if not bad_key else b"")
    scan = entities.scan_entities(db)
    record = next(iter(scan.records.values()))
    assert "invalid_actor_index" in codes(record)
    assert any(item["code"] == "invalid_actor_index" for item in scan.diagnostics)


def test_missing_index_target_and_unreadable_actor_are_explicit_diagnostics():
    db = EntityDb(
        {
            b"actorprefix12345678": b"invalid NBT",
            b"digp" + struct.pack("<ii", 0, 0): b"abcdefgh",
        }
    )
    scan = entities.scan_entities(db)
    assert scan.records == {}
    assert {item["code"] for item in scan.diagnostics} == {"unreadable_actor", "missing_actor"}
    assert scan.diagnostic_count == 2


def test_storage_key_retains_raw_binary_bytes_and_rejects_mismatch():
    db = EntityDb()
    suffix = b"\x00\xff\x80\x01\x02\x03\xfe\x04"
    tag = entity_tag()
    tag["internalComponents"] = nbt.CompoundTag(
        {
            "EntityStorageKeyComponent": nbt.CompoundTag(
                {
                    "StorageKey": nbt.StringTag(nbt.utf8_escape_decoder(suffix)),
                }
            )
        }
    )
    add_actor(db, tag, suffix=suffix)
    assert only_record(db).issues == []
    tag["internalComponents"]["EntityStorageKeyComponent"]["StorageKey"] = nbt.StringTag("different")
    db.records[b"actorprefix" + suffix] = tag.save_to(**SAVE_KWARGS)
    assert "storage_key_mismatch" in codes(only_record(db))


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("UniqueID", nbt.IntTag(1), "missing_unique_id"),
        ("DimensionId", nbt.IntTag(1), "dimension_mismatch"),
        ("Pos", nbt.ListTag([nbt.FloatTag(32), nbt.FloatTag(64), nbt.FloatTag(0)]), "position_index_mismatch"),
        ("Pos", nbt.ListTag([nbt.FloatTag(float("nan")), nbt.FloatTag(64), nbt.FloatTag(0)]), "invalid_position"),
        ("Identifier", nbt.StringTag("minecraft:cow"), "ambiguous_identifier"),
    ],
)
def test_ambiguous_record_evidence_survives_filtering_as_read_only(field, value, expected):
    db = EntityDb()
    tag = entity_tag()
    tag[field] = value
    add_actor(db, tag)
    assert expected in codes(only_record(db))


def test_legacy_concatenated_roots_are_all_read_with_names_and_dimension():
    roots = [entity_tag(1, identifier="minecraft:villager"), entity_tag(2), entity_tag(3, identifier="minecraft:pig")]
    key = struct.pack("<iii", 0, 0, 1) + b"\x32"
    raw = b"".join(nbt.NamedTag(root, f"root-{index}").save_to(**SAVE_KWARGS) for index, root in enumerate(roots))
    db = EntityDb({key: raw})
    scan = entities.scan_entities(db, identifiers=frozenset({"minecraft:villager", "minecraft:villager_v2"}))
    assert len(scan.records) == 2
    assert scan.scanned_entities == 3
    assert scan.legacy_records == 1
    for index, record in enumerate(scan.records.values()):
        assert record.named_tag.name == f"root-{index}"
        assert record.legacy_index == index
        assert record.dimension == 1
        assert record.value == raw
        assert "legacy_read_only" in codes(record)


def test_legacy_truncated_tail_is_reported_without_losing_readable_roots():
    key = struct.pack("<ii", 0, 0) + b"\x32"
    db = EntityDb({key: entity_tag().save_to() + b"\x0a\x00\x00\x08"})
    scan = entities.scan_entities(db)
    assert len(scan.records) == 1
    assert "unreadable_legacy_entities" in {item["code"] for item in scan.diagnostics}


def test_modern_actor_cannot_smuggle_multiple_roots():
    db = EntityDb({b"actorprefix12345678": entity_tag().save_to() + entity_tag(2).save_to()})
    scan = entities.scan_entities(db)
    assert not scan.records
    assert scan.diagnostics[0]["code"] == "unreadable_actor"


def test_scan_can_be_cancelled_cooperatively():
    db = EntityDb()
    add_actor(db, entity_tag())
    calls = []

    def cancel(phase=None, **kwargs):
        calls.append(phase)
        if len(calls) == 3:
            raise ReadStoppedError()

    with observe(cancel), pytest.raises(ReadStoppedError):
        entities.scan_entities(db)


def test_scan_capacity_fails_closed_instead_of_returning_an_incomplete_list(monkeypatch):
    db = EntityDb()
    add_actor(db, entity_tag())
    add_actor(db, entity_tag(2), suffix=b"abcdefgh")
    monkeypatch.setattr(entities, "MAX_ENTITY_RECORDS", 1)
    with pytest.raises(ValueError, match="vollständigen Scan"):
        entities.scan_entities(db)


def test_large_diagnostic_sets_remain_bounded_but_keep_the_exact_count(monkeypatch):
    monkeypatch.setattr(entities, "MAX_DIAGNOSTICS", 2)
    db = EntityDb({b"digp" + struct.pack("<ii", index, 0): b"bad" for index in range(5)})
    scan = entities.scan_entities(db)
    assert len(scan.diagnostics) == 2
    assert scan.diagnostic_count == 5
