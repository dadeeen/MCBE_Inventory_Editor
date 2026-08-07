from __future__ import annotations

import pytest

nbt = pytest.importorskip("amulet_nbt")

from mcbe_editor.bedrock_nbt import LOAD_KWARGS
from mcbe_editor.mount_profile import DEFAULT_HORSE_TEMPER
from mcbe_editor.mount_write import (
    ACTOR_PREFIX,
    actor_key_suffix,
    build_horse_actor_nbt,
    build_horse_mount_record,
    unique_id_from_actor_key,
)


class FakeDb:
    def __init__(self, items=None):
        self.store = dict(items or {})

    def get(self, key):
        if key not in self.store:
            raise KeyError(key)
        return self.store[key]

    def iter_items(self):
        return list(self.store.items())


def _actor_key(group: int, local_id: int) -> bytes:
    return ACTOR_PREFIX + group.to_bytes(4, "big") + local_id.to_bytes(4, "big")


def _attributes_by_name(tag):
    return {attribute["Name"].py_data: attribute for attribute in tag["Attributes"]}


def test_build_horse_actor_nbt_applies_custom_horse_profile_to_attributes_and_variant() -> None:
    actor = _actor_key(2, 9)
    profile = {
        "mode": "custom",
        "health": 28.0,
        "movement": 0.25,
        "jump_strength": 0.8,
        "color": 3,
        "mark_variant": 2,
    }

    raw = build_horse_actor_nbt(
        {"x": 12.5, "y": 64.0, "z": -20.25},
        unique_id_from_actor_key(actor),
        actor_key_suffix(actor),
        horse_profile=profile,
    )
    tag = nbt.load(raw, **LOAD_KWARGS).tag
    attributes = _attributes_by_name(tag)

    assert tag["Variant"].py_data == 3
    assert tag["Color"].py_data == 0
    assert tag["MarkVariant"].py_data == 2
    assert attributes["minecraft:health"]["Base"].py_data == 28.0
    assert attributes["minecraft:health"]["Current"].py_data == 28.0
    assert attributes["minecraft:health"]["Max"].py_data == 28.0
    assert round(attributes["minecraft:movement"]["Base"].py_data, 6) == 0.25
    assert round(attributes["minecraft:horse.jump_strength"]["Base"].py_data, 6) == 0.8
    assert "Health" not in tag


def test_build_horse_mount_record_applies_profile_when_reusing_template() -> None:
    template_actor = _actor_key(2, 5)
    template_raw = build_horse_actor_nbt(
        {"x": 1.0, "y": 65.0, "z": 1.0},
        unique_id_from_actor_key(template_actor),
        actor_key_suffix(template_actor),
    )
    db = FakeDb({template_actor: template_raw})
    profile = {
        "mode": "custom",
        "health": 19.0,
        "movement": 0.2,
        "jump_strength": 0.6,
        "color": 6,
        "mark_variant": 4,
    }

    record = build_horse_mount_record(db, {"x": -10.0, "y": 68.0, "z": -62.0}, horse_profile=profile)
    tag = nbt.load(record.actor_value, **LOAD_KWARGS).tag
    attributes = _attributes_by_name(tag)

    assert record.horse_profile == {
        "mode": "custom",
        "health": 19.0,
        "movement": 0.2,
        "jump_strength": 0.6,
        "color": 6,
        "mark_variant": 4,
        "temper": DEFAULT_HORSE_TEMPER,
    }
    # Der Klon darf den Zähmfortschritt des Templates nicht behalten.
    assert tag["Temper"].py_data == DEFAULT_HORSE_TEMPER
    assert tag["Variant"].py_data == 6
    assert tag["Color"].py_data == 0
    assert tag["MarkVariant"].py_data == 4
    assert attributes["minecraft:health"]["Base"].py_data == 19.0
    assert round(attributes["minecraft:movement"]["Base"].py_data, 6) == 0.2
    assert round(attributes["minecraft:horse.jump_strength"]["Base"].py_data, 6) == 0.6
    assert len(tag["Attributes"]) >= 12
