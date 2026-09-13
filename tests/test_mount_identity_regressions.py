"""Mount placement and clone checks independent of the planned record metadata."""
import struct
from dataclasses import replace

import pytest

from mcbe_editor import mount_placement, mount_write, mounts, nbt
from mcbe_editor.bedrock_nbt import LOAD_KWARGS, SAVE_KWARGS
from tests.test_mount_write import FakeDb, _actor_key


def _float32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _saved_db(record):
    return FakeDb({record.actor_key: record.actor_value, record.digp_key: record.digp_value})


@pytest.mark.parametrize("coordinate", [1048575.99, 16777215.5, -16777216.5, 10.5])
@pytest.mark.parametrize("axis", ["x", "z"])
def test_mount_position_and_index_use_stored_float32(coordinate, axis):
    position = {"x": 10.5, "y": 64.0, "z": 0.5, axis: coordinate}
    record = mount_write.build_horse_mount_record(FakeDb({}), position, create_mode="synthetic_full")
    tag = nbt.load(record.actor_value, **LOAD_KWARGS).tag
    stored = dict(zip(("x", "y", "z"), (item.py_data for item in tag["Pos"]), strict=True))
    assert stored == record.position
    assert record.digp_key == mount_write.digp_key_for_position(stored)
    assert mount_write.validate_horse_mount_write(_saved_db(record), record)["ok"]


def test_validator_derives_chunk_from_stored_position():
    record = mount_write.build_horse_mount_record(FakeDb({}), {"x": 0.5, "y": 64, "z": 0.5}, create_mode="synthetic_full")
    tag = nbt.load(record.actor_value, **LOAD_KWARGS).tag
    tag["Pos"][0] = nbt.FloatTag(32.5)
    record = replace(record, actor_value=nbt.NamedTag(tag).save_to(**SAVE_KWARGS))
    assert not mount_write.validate_horse_mount_write(_saved_db(record), record)["ok"]


def test_preview_and_footprint_use_storable_coordinates(monkeypatch):
    position = {"x": 1048575.99, "y": 73.0, "z": -16777216.5}
    preview_position = mounts._candidate_position(position, 0, 0, 0)
    assert preview_position["x"] == _float32(position["x"])
    assert preview_position["z"] == _float32(position["z"])
    observed = []
    original = mount_placement._probe_footprint_column

    def capture(db, candidate, *args):
        observed.append(candidate)
        return original(db, candidate, *args)

    monkeypatch.setattr(mount_placement, "_probe_footprint_column", capture)
    result = mount_placement._candidate_with_footprint_probe(FakeDb({}), position, 0)
    assert observed
    assert result["x"] == _float32(position["x"])
    assert all(row["x"] == result["x"] and row["z"] == result["z"] for row in observed)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1e40, 10**400, 2**35 - 1])
def test_invalid_or_rounded_out_of_range_mount_positions_are_rejected(value):
    with pytest.raises(ValueError):
        mount_write.normalize_mount_position({"x": value, "y": 64, "z": 0})


def _template(**updates):
    key = _actor_key(2, 5)
    raw = mount_write.build_horse_actor_nbt({"x": 0.5, "y": 64, "z": 0.5}, mount_write.unique_id_from_actor_key(key), mount_write.actor_key_suffix(key))
    tag = nbt.load(raw, **LOAD_KWARGS).tag
    tag.update(updates)
    return key, nbt.NamedTag(tag).save_to(**SAVE_KWARGS)


@pytest.mark.parametrize("field,value", [
    ("IsTamed", nbt.ByteTag(1)),
    ("Saddled", nbt.ByteTag(1)),
    ("OwnerNew", nbt.LongTag(42)),
    ("LinksTag", nbt.ListTag([nbt.CompoundTag({"entityID": nbt.LongTag(42)})])),
    ("Dead", nbt.ByteTag(1)),
    ("Armor", nbt.ListTag([nbt.CompoundTag({"Count": nbt.ByteTag(1), "Name": nbt.StringTag("minecraft:diamond_horse_armor")})])),
    ("definitions", nbt.ListTag([nbt.StringTag("+minecraft:horse_tamed")])),
    ("IsBaby", nbt.StringTag("unknown")),
    ("IsBaby", nbt.FloatTag(float("nan"))),
    ("IsBaby", nbt.CompoundTag({"future": nbt.IntTag(1)})),
    ("IsBaby", nbt.ByteTag(2)),
])
def test_active_template_uses_synthetic_fallback_or_rejects_explicit_clone(field, value):
    key, raw = _template(**{field: value})
    db = FakeDb({key: raw})
    position = {"x": 4.5, "y": 64, "z": 0.5}
    record = mount_write.build_horse_mount_record(db, position)
    assert record.create_mode == "synthetic_full"
    assert mount_write.validate_horse_mount_write(_saved_db(record), record)["ok"]
    assert db.get(key) == raw
    with pytest.raises(ValueError):
        mount_write.build_horse_mount_record(db, position, create_mode="template_clone")
    with pytest.raises(ValueError):
        mount_write.build_horse_actor_nbt_from_template(raw, position, -999)


def test_idle_template_preserves_unknown_data():
    future = nbt.CompoundTag({"unknown": nbt.IntTag(7)})
    key, raw = _template(FutureCosmetic=future)
    record = mount_write.build_horse_mount_record(FakeDb({key: raw}), {"x": 4.5, "y": 64, "z": 0.5}, create_mode="template_clone")
    assert nbt.load(record.actor_value, **LOAD_KWARGS).tag["FutureCosmetic"] == future
    assert mount_write.validate_horse_mount_write(_saved_db(record), record)["ok"]


@pytest.mark.parametrize("field,value", [
    ("IsTamed", nbt.ByteTag(1)),
    ("Saddled", nbt.ByteTag(1)),
    ("OwnerNew", nbt.LongTag(42)),
    ("LeasherID", nbt.LongTag(42)),
    ("LinksTag", nbt.ListTag([nbt.CompoundTag({"entityID": nbt.LongTag(42)})])),
    ("IsTamed", nbt.IntTag(0)),
    ("OwnerNew", nbt.IntTag(-1)),
])
def test_validator_rejects_inherited_live_state_even_when_bytes_match_plan(field, value):
    record = mount_write.build_horse_mount_record(FakeDb({}), {"x": 0.5, "y": 64, "z": 0.5}, create_mode="synthetic_full")
    tag = nbt.load(record.actor_value, **LOAD_KWARGS).tag
    tag[field] = value
    record = replace(record, actor_value=nbt.NamedTag(tag).save_to(**SAVE_KWARGS))
    assert not mount_write.validate_horse_mount_write(_saved_db(record), record)["ok"]
